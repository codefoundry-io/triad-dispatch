"""Shared helpers for codex/gemini subprocess wrappers.

Framework — vendor-JSON IO + 5-class classification + noise-tag extraction
+ pydantic schema validation (optional) with 1 schema-repair retry.

Per-CLI vendor JSON modes (always on):
- Codex: `codex exec --json -o <last_msg> --ephemeral -c approval_policy=never`
  (config-alive 2026-05-30: no `--ignore-user-config`; approval pinned)
  → stdout = JSONL events stream (vendor schema), stderr ≈ 39 B (vendor quiet).
- Gemini: `gemini -p ... --output-format json`
  → stdout = single JSON object {response, stats, error}, stderr ≈ 189 B.

Schema enforcement (`--pydantic module:Class`) uses the prompt-side few-shot
pattern (verified Step A3 = 15/15 PASS): JSON-only instruction + shape line
+ dummy example + USER REQUEST. Vendor settings.json `responseSchema` path
NOT used (Issue #13388 = open / settings silent-ignored).

Audit log schema = the RunResult dataclass + audit() body. There is no
separate schema file. _logs/<cli>/audit.jsonl is the output; cleanup is
the maintenance agent's responsibility.
"""
from __future__ import annotations

import fcntl
import importlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# pydantic optional — only required when --pydantic flag is given.
try:
    from pydantic import BaseModel  # type: ignore
    PYDANTIC_OK = True
except ImportError:  # pragma: no cover
    BaseModel = None  # type: ignore
    PYDANTIC_OK = False


# ─── Exit codes ────────────────────────────────────────────────────────────
EXIT_OK = 0
EXIT_CLI_FAIL = 1
EXIT_TIMEOUT = 2
EXIT_ARG_ERROR = 3
EXIT_BINARY_MISSING = 4
EXIT_RATE_GIVE_UP = 64   # transient retry exhausted → Sonnet repair sub-agent
EXIT_TERMINAL = 65       # cli-sub-cap / token-limit / oauth-env → user escalate
EXIT_SCHEMA_FAIL = 66    # pydantic validation failed even after 1 retry
EXIT_SCHEMA_REJECTED = 67  # codex refused --output-schema at submit (massage/strict-rule drift)
EXIT_FANOUT_PARTIAL = 68   # --task fan-out incomplete (partial / zero / fewer-than-requested subagents) — surfaced, never silent
EXIT_TASK_BLOCKED = 69   # --task code: codex self-reported BLOCKED / NEEDS_CONTEXT (no edit to commit)


def map_classification_to_exit(cls: str) -> int:
    """Map a classify() result string to a wrapper EXIT_* code (pure helper)."""
    return {
        "ok": EXIT_OK,
        "server-capacity": EXIT_RATE_GIVE_UP,
        "cli-subscription-cap": EXIT_TERMINAL,
        "token-limit": EXIT_TERMINAL,
        "oauth-env": EXIT_TERMINAL,
        "timeout": EXIT_TIMEOUT,
        "extraction-error": EXIT_CLI_FAIL,
        "schema-fail": EXIT_SCHEMA_FAIL,
        "schema-rejected": EXIT_SCHEMA_REJECTED,
        "fanout-spawn-error": EXIT_TERMINAL,
        "config-conflict": EXIT_TERMINAL,
        "task-blocked": EXIT_TERMINAL,
        "vendor-error": EXIT_TERMINAL,  # agy: rc!=0 but a non-empty answer — surface, NOT repair
        "unknown": EXIT_CLI_FAIL,
    }.get(cls, EXIT_CLI_FAIL)


# ─── Pattern lists (seed — living value, Step D maintenance updates) ──────
# Lowercase substring match. Terminal-first ordering when classifying.

SERVER_CAPACITY_PATTERNS: tuple[str, ...] = (
    "model_capacity_exhausted",
    "resource_exhausted",
    "ratelimitexceeded",
    "model overloaded",
    "overloaded_error",  # 2026-07-05: Anthropic 529 overload api_error_status enum,
    # surfaced by extract_claude_answer into the claude is_error ext_err blob
    # (`is_error=true (api_error_status=overloaded_error): ...`). Retry-eligible.
    # Specific vendor enum token — passes the false-positive guard (unlike bare
    # `"529"`). `rate_limit_error` (429) deliberately NOT added: it is ambiguous
    # between a transient rate limit (retry) and a subscription cap (terminal),
    # and mis-routing it either way costs a wasted cycle.
    # `"503"`, `"429"` removed 2026-05-03 (later-2): standalone numeric matched
    # natural occurrences in answer text (line numbers, byte counts, timestamps,
    # spec docs e.g. "see RFC 429"). The phrase forms below already cover real
    # capacity errors. If a future failure surfaces a status-only stderr without
    # the phrase form, add a more specific substring (e.g. `"http 429"`,
    # `"status: 503"`) — never bare `"429"` / `"503"`.
    "service unavailable",
    "too many requests",
    "aborterror",  # 2026-05-02: Gemini CLI _recoverFromLoop tool-call loop detection abort; transient — retry eligible. github.com/google-gemini/gemini-cli/issues/23509
)

CLI_SUB_CAP_PATTERNS: tuple[str, ...] = (
    "your quota will reset after",
    "5h limit reached",
    "weekly limit reached",
    "subscription limit reached",
    "usage limit reached",
    "no longer supported for gemini code assist for individuals",
    # L10 union (twin→SoT 2026-07-05): the raw error CLASS token — distinctive,
    # exception-name form, FP-safe. (Twin's third token "migrate to antigravity"
    # was DROPPED: prose form could match ordinary migration discussions.)
    "ineligibletiererror",  # 2026-06-30: IneligibleTierError — Gemini Code Assist individuals tier discontinued 2026-06-18; user must migrate to Antigravity. github.com/google-gemini/gemini-cli/discussions/28017
)

TOKEN_LIMIT_PATTERNS: tuple[str, ...] = (
    "payload size exceeds",
    "token count exceeds",
    # `"context window"`, `"maximum context"` removed 2026-05-03 (later-2):
    # generic LLM jargon that naturally appears in answer text (e.g. user asks
    # "explain context window in Claude" → response text matches the substring
    # → token-limit mis-classify on otherwise OK call). Replaced with the
    # exceeded-form which only appears in real token-limit errors.
    "context window exceeded",
    "exceeds maximum context",
    "context length exceeded",
    "400 bad request",
    "400 invalid",
)

SCHEMA_REJECTED_PATTERNS: tuple[str, ...] = (
    "invalid output schema",
    "output schema rejected",
    "schema validation failed",
    "unsupported schema",
    # NOTE: bare "schema" is NOT added — it appears in normal answer text.
    # Only schema-REJECTION phrases (submit-time refusal) belong here.
)

# Fan-out: terminal spawn_agent failure (NOT the self-corrected full-history
# fork error, which the model recovers from). Phrases are specific to a
# terminal quota/parameter rejection.
FANOUT_SPAWN_PATTERNS: tuple[str, ...] = (
    "spawn_agent failed",
    "agent quota exceeded",
    "could not spawn subagent",
)

# Config-alive: an inherited ~/.codex config that breaks the call.
# Phrases are anchored to "config.toml" to avoid false positives on
# natural answer text (bare "invalid profile" / "unknown config key"
# are too broad — same guard that removed "401"/"oauth"/"context window").
CONFIG_CONFLICT_PATTERNS: tuple[str, ...] = (
    "failed to parse config.toml",
    "error loading config.toml",
    "invalid config.toml",
)

OAUTH_ENV_PATTERNS: tuple[str, ...] = (
    # `"401"` (bare) removed 2026-05-03 (later-2): standalone numeric matched
    # natural occurrences (line numbers, status code arrays, etc.). Replaced
    # with the phrase form. Same fix family as `"503"`/`"429"` in
    # SERVER_CAPACITY_PATTERNS and `"oauth"`/`"unauthorized"` in this list.
    "401 unauthorized",
    "http 401",
    # 2026-07-01 (twin, L9 port 2026-07-05): real claude `is_error=true /
    # api_error_status=401` capture. Phrase is distinctive and FP-safe: it
    # appears exclusively in the claude vendor envelope's `result` field on an
    # auth-401 failure. Never add bare "401" / "oauth" (removed above for FP).
    "invalid authentication credentials",
    # `"unauthorized"` removed 2026-05-03: matched `[LocalAgentExecutor]
    # Blocked call: Unauthorized tool call: ...` (1/152 false positive in
    # 200-verify batch — misled user toward "re-login" when the actual
    # cause was tool-block). HTTP-form 401 errors are still caught above.
    # `"oauth"` removed 2026-05-03 (later): matched `_OAuth2Client.requestAsync`
    # google-auth-library stack trace (always present in Gemini capacity-
    # exhausted stderr — github.com/google-gemini/gemini-cli/issues/24159).
    # 100% false positive on the capacity-exhausted code path because L2
    # checked OAUTH_ENV before SERVER_CAPACITY. Replaced with the standalone
    # `"oauth error"` form which doesn't match library identifiers.
    "oauth error",
    "token refresh failed",
    "openai_api_key",
    "auth error",
    "please log in",
    "please authenticate",
)

# SEMANTIC classification of stderr (tool-not-installed / vendor warning /
# normal chatter) is the LEADER's job (the AI that receives the mirrored
# stderr via its shell tool). The wrapper only records raw stderr into the
# audit log; the leader judges it and alerts the user. The dispatch SKILLs
# carry the stderr-interpretation guidance.


# ─── Vendor exit code maps (EMPIRICAL ONLY) ───────────────────────────────
# ONLY empirically observed exit codes are entered. An unobserved code =>
# "unknown" => repair-agent dispatch (the repair agent web-searches, analyzes,
# and patches an entry into this map).
# Tier 1 docs (Gemini PR #13728: 41/42/52/53/130, Codex mintlify: 2/3/4/130)
# never triggered in this environment, so NOT entered — add after observing.

GEMINI_VENDOR_EXIT_MAP: dict[int, str] = {
    0: "ok",
    # 41/42/52/53/130 = docs-only so far (anthropics/claude-code#13728 /
    # headless docs) — add after empirical observation.
}

CODEX_VENDOR_EXIT_MAP: dict[int, str] = {
    0: "ok",
    # 130 = possibly anthropics/claude-code#4721 (unresolved) — add after observing.
    # 2/3/4 = third-party (mintlify) sources only, not officially confirmed —
    # add after empirical observation.
}

CLAUDE_VENDOR_EXIT_MAP: dict[int, str] = {
    0: "ok",
    # Further claude `--print` vendor exit codes: add after observing.
    # An ENV/AUTH failure carrying `is_error: true` still exits rc=0
    # (envelope-only signal); extract_claude_answer analyzes the envelope
    # and propagates extraction-error.
}

ANTIGRAVITY_VENDOR_EXIT_MAP: dict[int, str] = {
    0: "extraction-error",  # 2026-06-25: agy rc=0 + no-sentinel (answer present, sentinel not emitted);
                            # classify() is called ONLY on the no-answer path so rc=0 + no-sentinel
                            # → extraction-error is safe (answer-present path returns "ok" before calling classify).
                            # Source: run-log 20260625T082029Z-98429-e4610255.json (vendor_exit_code=0,
                            # extraction_error=no-sentinel, full Korean answer in stdout, classification=unknown).
}
# populated empirically by the agy-wrapper-repair sub-agent

# Matched ONLY in the antigravity classify arm, only on the no-answer path;
# NOT added to shared OAUTH_ENV_PATTERNS (FP-safe).
AGY_AUTH_BANNER_PATTERNS = ("authentication required. please visit the url",)


# ─── Retry policy ─────────────────────────────────────────────────────────
SERVER_CAP_BACKOFF_S: tuple[int, ...] = (15, 45)
SERVER_CAP_MAX_RETRIES = len(SERVER_CAP_BACKOFF_S)


# ─── Audit rotation policy ────────────────────────────────────────────────
# audit.jsonl is append-only operational telemetry, so it must be bounded too.
# Rotate the active file after append once it crosses 10 MB, then keep at most
# five archives / 50 MB per CLI. The per-call run-log remains the detailed IPC
# artifact; audit is durable routing telemetry, not an unbounded datastore.
AUDIT_ROTATE_BYTES = 10 * 1024 * 1024  # 10 MB
AUDIT_MAX_ARCHIVES = 5
AUDIT_ARCHIVE_MAX_BYTES = AUDIT_ROTATE_BYTES * AUDIT_MAX_ARCHIVES


# ─── Run-log policy (per-execution artifact, dispatch-SKILL input) ────────
# Separate from audit.jsonl: one file per FAILED call (rc != 0) at
# _logs/<cli>/runs/<UTC-ts>-<pid>-<uuid8>.json — successes never dispatch the
# repair agent, so no file. The dispatch SKILL passes only the PATH in the
# agent prompt and the agent fetches it with its Read tool, isolating large
# vendor stdout / non-ASCII / special-char escaping from prompt transport.
# 2-layer cleanup:
#   Primary  = the dispatch SKILL rm's it right after the repair agent returns
#   Failsafe = this function unlinks oldest-first when the dir cap is exceeded
_RUN_LOG_MAX_FILES = 100
_RUN_LOG_MAX_BYTES = 20 * 1024 * 1024  # 20 MB total cap


@dataclass
class RunResult:
    exit_code: int                  # wrapper-normalized (0/1/2/3/4/64/65/66)
    stdout: str
    stderr: str
    elapsed_s: float
    classification: str = "ok"
    mode: str = "normal"            # normal | repair | schema_repair
    repair_attempt: int = 0
    # Final-answer + schema layer
    final_answer: str = ""
    validated: Optional[dict] = None
    schema_repair_attempt: int = 0
    extraction_error: Optional[str] = None
    validation_error: Optional[str] = None
    # Vendor raw exit code — the repair agent's web-search key for unobserved codes.
    vendor_exit_code: int = -1


# ─── Helpers ──────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)


def require_binary(name: str) -> str:
    """Resolve the vendor binary, honoring an install-time pin (finding #3).

    A codex-host launcher execs the wrapper with
    `TRIAD_<name.upper()>_BIN=<resolved absolute path>` and
    `TRIAD_REQUIRE_PINNED_VENDOR=1`, so a workspace-planted `<name>` earlier on
    PATH cannot shadow the real vendor CLI an allow-listed launcher executes.
    Lab default (neither env set) = `shutil.which` (PATH), unchanged.

    - a valid pin (absolute, existing, executable) always wins over PATH;
    - `TRIAD_REQUIRE_PINNED_VENDOR=1` with the pin unset OR invalid fails closed
      (`EXIT_BINARY_MISSING`) — NEVER a silent PATH fallback (that is the vuln);
    - an invalid pin WITHOUT the require flag falls through to PATH (lab convenience).
    """
    pin = os.environ.get(f"TRIAD_{name.upper()}_BIN")
    require_pinned = os.environ.get("TRIAD_REQUIRE_PINNED_VENDOR") == "1"
    if pin:
        if os.path.isabs(pin) and os.path.isfile(pin) and os.access(pin, os.X_OK):
            return pin
        log(
            f"pinned vendor binary TRIAD_{name.upper()}_BIN is not an executable "
            f"absolute path: {pin}"
        )
        if require_pinned:
            sys.exit(EXIT_BINARY_MISSING)
    elif require_pinned:
        log(
            f"TRIAD_REQUIRE_PINNED_VENDOR=1 but TRIAD_{name.upper()}_BIN is unset "
            f"for '{name}' — refusing PATH fallback"
        )
        sys.exit(EXIT_BINARY_MISSING)
    path = shutil.which(name)
    if not path:
        log(f"binary '{name}' not found on PATH")
        sys.exit(EXIT_BINARY_MISSING)
    return path


def _classifier_extension_path() -> Path:
    """Persistent, env-independent location for the user-writable classifier
    extension. Distributed plugin self-improvement persists HERE (user home),
    not in the ephemeral plugin dir. `TRIAD_CLASSIFIER_EXTENSION` overrides
    (tests / custom location)."""
    override = os.environ.get("TRIAD_CLASSIFIER_EXTENSION")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "triad-dispatch" / "classifier-patches.json"


def _load_classifier_extension() -> dict:
    """Load + SANITIZE the user classifier extension. Shape:
        { "<cli>": { "vendor_exit_map": {"<int-str>": "<class-str>"},
                     "patterns": {"<LIST_NAME>": ["<substr>", ...]} } }
    This file is trusted user-curated input, but it is hand/agent-editable, so the
    loader is defensive: any wrong-typed node is dropped (never propagated into
    classify()). Missing / unreadable / corrupt / non-dict -> {}. A
    structurally-malformed-but-valid-JSON file yields only its well-typed entries,
    so classify() can never raise on it."""
    p = _classifier_extension_path()
    try:
        if not p.exists():
            return {}
        data = json.loads(p.read_text())
    except (ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    clean: dict = {}
    for cli, entry in data.items():
        if not isinstance(entry, dict):
            continue
        cleaned: dict = {}
        vmap = entry.get("vendor_exit_map")
        if isinstance(vmap, dict):
            cleaned["vendor_exit_map"] = {
                k: v for k, v in vmap.items() if isinstance(v, str)
            }
        pats = entry.get("patterns")
        if isinstance(pats, dict):
            cleaned["patterns"] = {
                name: [s for s in lst if isinstance(s, str)]
                for name, lst in pats.items()
                if isinstance(lst, list)
            }
        if cleaned:
            clean[cli] = cleaned
    return clean


# ─── Product hardening mode (L8 twin→SoT port, owner adjudications 2026-07-05) ───
# The lab (SoT callers, skill contracts) runs UNRESTRICTED by default; the
# public codex-host product's bootstrap sets TRIAD_WRAPPER_HARDENED=1, which
# activates: allowed-roots containment (required), the pydantic import gate,
# and audit prompt redaction. Each control also has an individual env so it
# can be engaged on its own (set TRIAD_WRAPPER_ALLOWED_ROOTS to enforce
# containment; TRIAD_AUDIT_REDACT_PROMPTS=1 to redact) — per-product defaults,
# one engine.

def _wrapper_hardened() -> bool:
    return os.environ.get("TRIAD_WRAPPER_HARDENED") == "1"


def _audit_redact_enabled() -> bool:
    return _wrapper_hardened() or os.environ.get("TRIAD_AUDIT_REDACT_PROMPTS") == "1"


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False



def runtime_allowed_roots() -> list[Path]:
    """Containment roots for --cwd / --prompt-file. Env unset → NO containment
    in the lab (callers own isolation per the SKILL contracts); under
    TRIAD_WRAPPER_HARDENED=1 the env is REQUIRED (refuse rather than guess —
    the public product's bootstrap pins it; a hardened run without pinned
    roots must not silently fall back to cwd)."""
    raw = os.environ.get("TRIAD_WRAPPER_ALLOWED_ROOTS", "")
    if not raw:
        if _wrapper_hardened():
            raise ValueError(
                "TRIAD_WRAPPER_HARDENED=1 requires TRIAD_WRAPPER_ALLOWED_ROOTS "
                "(colon-separated absolute paths)")
        return []
    roots = []
    for item in raw.split(os.pathsep):
        if not item:
            continue
        path = Path(item).expanduser()
        if not path.is_absolute():
            raise ValueError(
                "TRIAD_WRAPPER_ALLOWED_ROOTS entries must be absolute paths")
        roots.append(path.resolve(strict=False))
    result: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        text = str(root)
        if text in seen:
            continue
        seen.add(text)
        result.append(root)
    return result


def _ensure_within_runtime_roots(path: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    roots = runtime_allowed_roots()
    if not roots:
        return resolved          # lab default: no containment
    if not any(_path_is_within(resolved, root) for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise ValueError(f"{label} must be under an allowed runtime root: {allowed}")
    return resolved


def load_prompt_text(prompt: Optional[str], prompt_file: Optional[str]) -> str:
    """Load the wrapper prompt from argv text or an absolute UTF-8 file.

    argparse enforces the XOR at the CLI; this re-check is defense-in-depth
    for direct callers."""
    if prompt is not None and prompt_file:
        raise ValueError("--prompt and --prompt-file are mutually exclusive")
    if prompt is not None:
        return prompt
    if not prompt_file:
        raise ValueError("either --prompt or --prompt-file is required")
    path = Path(prompt_file).expanduser()
    if not path.is_absolute():
        # P3.b D-2 (spec 3-way unanimous 2026-07-11): stay FAIL-LOUD —
        # silent relative resolution against a reverted/unexpected cwd could
        # read the wrong same-named file and pass containment silently. The
        # candidate below is cwd-DERIVED, not necessarily the intended path.
        cwd = Path.cwd()
        raise ValueError(
            f"--prompt-file must be an absolute path (got {prompt_file!r}; "
            f"caller cwd: {cwd}). If that cwd is the intended base, retry "
            f"with --prompt-file {cwd / path}; note the foreground shell cwd "
            f"can revert between turns — verify it before trusting the "
            f"candidate."
        )
    resolved = _ensure_within_runtime_roots(path, "--prompt-file")
    if not resolved.is_file():
        raise ValueError(f"--prompt-file must be a file: {resolved}")
    return resolved.read_text(encoding="utf-8")



def validate_wrapper_cwd(cwd: Optional[str]) -> Optional[str]:
    """Validate a vendor cwd without expanding the no-prompt trust boundary."""
    if not cwd:
        return None
    path = Path(cwd).expanduser()
    if not path.is_absolute():
        raise ValueError("--cwd must be an absolute path")
    resolved = _ensure_within_runtime_roots(path, "--cwd")
    if not resolved.is_dir():
        raise ValueError(f"--cwd must be an existing directory: {resolved}")
    return str(resolved)



def _redact_prompt_args(cmd: list[str]) -> list[str]:
    """Keep argv shape in durable audit logs without storing prompt payloads."""
    redacted: list[str] = []
    redact_next: str | None = None
    for arg in cmd:
        if redact_next is not None:
            if redact_next == "prompt":
                redacted.append(f"<redacted:{len(arg)} chars>")
            else:
                redacted.append("<redacted:prompt-file-path>")
            redact_next = None
            continue
        if arg in {"-p", "--prompt"}:
            redacted.append(arg)
            redact_next = "prompt"
            continue
        if arg == "--prompt-file":
            redacted.append(arg)
            redact_next = "prompt-file"
            continue
        if arg.startswith("--prompt="):
            value = arg.split("=", 1)[1]
            redacted.append(f"--prompt=<redacted:{len(value)} chars>")
            continue
        if arg.startswith("--prompt-file="):
            redacted.append("--prompt-file=<redacted:prompt-file-path>")
            continue
        redacted.append(arg)
    if redact_next is not None:
        redacted.append("<redacted:missing-value>")
    return redacted



def _json_len(value: Any) -> int:
    if value is None:
        return 0
    try:
        return len(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return len(str(value))

def classify(
    cli: str,
    stderr: str,
    stdout: str,
    exit_code: int,
    vendor_exit_code: Optional[int] = None,
) -> str:
    """Failure classes + ok. Layer order:
      L1 — vendor exit code map (empirically observed raw codes only)
      L2 — substring fallback (the per-class pattern lists)
      L3 — "unknown" (repair-agent dispatch signal)

    `vendor_exit_code` is the raw CLI subprocess exit (e.g. 7, 130). When
    omitted, falls back to `exit_code` for legacy callers, but L1 is
    effectively dead in that case because `exit_code` is the wrapper's own
    {EXIT_OK, EXIT_CLI_FAIL, ...} code, not the vendor's. Pass
    `vendor_exit_code` explicitly to make the vendor exit map functional
    (2026-05-03 fix: prior to this, both CODEX_VENDOR_EXIT_MAP and
    GEMINI_VENDOR_EXIT_MAP were decoration; future repair-agent
    enrichments can now route vendor-specific exit codes correctly).
    """
    if exit_code == 0:
        return "ok"
    # Wrapper-level timeout: do NOT fall through to L2 substring matching.
    # Partial stderr captured before SIGTERM often contains capacity-class
    # phrases (Gemini "_OAuth2Client.requestAsync" + retry chatter, Codex
    # mid-stream events) which would mis-classify a hung call as transient
    # and trigger a 3× full-timeout retry (worst case 46 min @ timeout=900s).
    # Vendor's own retry logic already ran inside that timeout window —
    # wrapper retry on top is redundant. Surface as "timeout" → fail-fast.
    # 2026-05-03 (later-3) framework gap fix.
    if exit_code == EXIT_TIMEOUT:
        return "timeout"
    # L1 — vendor exit code map (empirical only). Use vendor_exit_code when
    # available; legacy callers fall back to exit_code (dead-code path).
    raw = vendor_exit_code if vendor_exit_code is not None else exit_code
    _ext = _load_classifier_extension().get(cli, {})
    _ext_vmap = {}
    for _k, _v in _ext.get("vendor_exit_map", {}).items():
        try:
            _ext_vmap[int(_k)] = _v
        except (TypeError, ValueError):
            pass
    _ext_pat = _ext.get("patterns", {})

    def _p(name, builtin):
        """built-in patterns + per-cli extension patterns for that list."""
        extra = _ext_pat.get(name, ())
        return tuple(builtin) + tuple(extra)

    if cli == "gemini":
        vmap = GEMINI_VENDOR_EXIT_MAP
    elif cli == "claude":
        vmap = CLAUDE_VENDOR_EXIT_MAP
    elif cli == "antigravity":
        vmap = ANTIGRAVITY_VENDOR_EXIT_MAP
    else:
        vmap = CODEX_VENDOR_EXIT_MAP
    vmap = {**_ext_vmap, **vmap}
    # A vmap entry of "extraction-error" is a WEAK no-answer fallback (e.g.
    # ANTIGRAVITY_VENDOR_EXIT_MAP[0], 2026-06-25 repair patch): the specific
    # L2 classes (agy auth banner / capacity / sub-cap / token-limit / oauth)
    # must keep winning — an early return here swallowed ALL of them on the
    # agy no-answer path (t14/t15/f9 regression found on the 2026-07-04
    # backport pass). The weak entry replaces only the terminal "unknown", so
    # a pattern-less no-sentinel answer still routes to repair as
    # extraction-error instead of unknown.
    _weak_fallback = None
    if raw in vmap and vmap[raw] != "ok":
        if vmap[raw] == "extraction-error":
            _weak_fallback = "extraction-error"
        else:
            return vmap[raw]
    # L2 — substring fallback
    # Order rationale: terminal user-action class (cli-sub-cap) first (most
    # specific phrases, near-zero false positive). Then transient
    # SERVER_CAPACITY (most-frequent failure mode for Gemini Pro, retry
    # eligible). Then TOKEN_LIMIT (terminal but rarer). Then OAUTH_ENV
    # (terminal, lowest natural-occurrence risk). The 2026-05-03 (later)
    # reorder moves SERVER_CAPACITY before OAUTH_ENV because Gemini's
    # capacity-exhausted stderr ALWAYS includes the Google
    # `OAuth2Client.requestAsync` library stack trace. The 2026-05-03
    # (later-2) further moves SERVER_CAPACITY before TOKEN_LIMIT for
    # transient-first routing (capacity is far more frequent than token
    # limit; mis-classifying a capacity event as terminal token-limit costs
    # a wasted retry-give-up cycle).
    blob = ((stderr or "") + "\n" + (stdout or "")).lower()
    stderr_blob = (stderr or "").lower()
    if cli == "antigravity" and any(p in blob for p in _p("AGY_AUTH_BANNER_PATTERNS", AGY_AUTH_BANNER_PATTERNS)):
        return "oauth-env"
    if any(p in blob for p in _p("CLI_SUB_CAP_PATTERNS", CLI_SUB_CAP_PATTERNS)):
        return "cli-subscription-cap"
    if any(p in blob for p in _p("SERVER_CAPACITY_PATTERNS", SERVER_CAPACITY_PATTERNS)):
        return "server-capacity"
    if any(p in blob for p in _p("TOKEN_LIMIT_PATTERNS", TOKEN_LIMIT_PATTERNS)):
        return "token-limit"
    if any(p in blob for p in _p("OAUTH_ENV_PATTERNS", OAUTH_ENV_PATTERNS)):
        return "oauth-env"
    # schema-rejected checked LAST in L2 — capacity/terminal classes win.
    # submit-time --output-schema refusal: surfaced to caller (terminal-like),
    # NOT routed to the repair agent.
    if any(p in blob for p in _p("SCHEMA_REJECTED_PATTERNS", SCHEMA_REJECTED_PATTERNS)):
        return "schema-rejected"
    if any(p in stderr_blob for p in _p("FANOUT_SPAWN_PATTERNS", FANOUT_SPAWN_PATTERNS)):
        return "fanout-spawn-error"
    if any(p in stderr_blob for p in _p("CONFIG_CONFLICT_PATTERNS", CONFIG_CONFLICT_PATTERNS)):
        return "config-conflict"
    # L3 — weak vmap fallback (extraction-error) wins over the repair-dispatch
    # "unknown" ONLY when no L2 class matched.
    return _weak_fallback or "unknown"


# ─── Pydantic helpers (NEW) ───────────────────────────────────────────────

def load_pydantic_class(spec: str):
    """Parse 'module.path:ClassName' or 'module.path.ClassName' →
    pydantic BaseModel subclass.

    Raises ImportError / AttributeError / TypeError on failure.
    """
    if not PYDANTIC_OK:
        raise RuntimeError("pydantic not installed — `pip3 install --user pydantic`")
    if _wrapper_hardened() and os.environ.get("TRIAD_ALLOW_PYDANTIC_IMPORT") != "1":
        # Hardened installs (public codex-host product) must opt in explicitly:
        # --pydantic imports arbitrary Python outside the vendor sandbox.
        raise PermissionError(
            "--pydantic imports Python code outside the sandbox; under "
            "TRIAD_WRAPPER_HARDENED=1 set TRIAD_ALLOW_PYDANTIC_IMPORT=1 only "
            "for trusted schema modules")
    if ":" in spec:
        mod_path, cls_name = spec.rsplit(":", 1)
    else:
        mod_path, cls_name = spec.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name)
    if not (isinstance(cls, type) and BaseModel is not None and issubclass(cls, BaseModel)):
        raise TypeError(f"{spec} is not a pydantic BaseModel subclass")
    return cls


def _dummy_for_type(t: str) -> Any:
    return {
        "string": "<value>",
        "number": 0.0,
        "integer": 0,
        "boolean": False,
        "array": [],
        "object": {},
        "null": None,
    }.get(t, None)


def schema_block_for_prompt(cls) -> str:
    """Build the schema injection block for the prompt.

    Format verified by Step A3 spike (Gemini 10/10 + Codex 5/5 PASS):
        - JSON-only instruction (emphasised)
        - Shape line in human-readable form
        - One dummy example
    """
    schema = cls.model_json_schema()
    fields = schema.get("properties", {})
    required = set(schema.get("required", []))

    shape_parts = []
    dummy: dict = {}
    for name, sch in fields.items():
        t = sch.get("type", "any")
        marker = "" if name in required else "?"
        shape_parts.append(f'"{name}{marker}": <{t}>')
        dummy[name] = _dummy_for_type(t)
    shape_line = "{" + ", ".join(shape_parts) + "}"

    return (
        "You are a JSON-only response API. Your output MUST be valid JSON "
        "and nothing else. No markdown fences. No prose. No commentary. "
        "Just a single JSON object.\n\n"
        f"The JSON object must match exactly this shape:\n{shape_line}\n\n"
        "JSON output example:\n"
        f"{json.dumps(dummy, ensure_ascii=False)}\n\n"
        "Now produce the JSON output for the user's request below. "
        "Return ONLY the JSON object — no ```, no explanation."
    )


def inject_schema_to_prompt(prompt: str, cls) -> str:
    block = schema_block_for_prompt(cls)
    return f"{block}\n\n=== USER REQUEST ===\n{prompt}\n\nJSON:"


def _strictify_schema_node(node: Any) -> None:
    """Recursively enforce codex (OpenAI strict structured-output) object rules:
    every object node gets `additionalProperties: false` and `required` = all
    property keys. Recurse into nested properties, array `items`, and unions.
    Mutates in place.
    """
    if not isinstance(node, dict):
        return
    if node.get("type") == "object" or "properties" in node:
        props = node.get("properties", {})
        node["additionalProperties"] = False
        node["required"] = list(props.keys())
        for sub in props.values():
            _strictify_schema_node(sub)
    items = node.get("items")
    if isinstance(items, dict):
        _strictify_schema_node(items)
    for union_key in ("anyOf", "oneOf", "allOf"):
        for sub in node.get(union_key, []):
            _strictify_schema_node(sub)


def pydantic_to_codex_schema(cls) -> dict:
    """Derive a codex `--output-schema` JSON Schema from a pydantic BaseModel.

    `model_json_schema()` does not set `additionalProperties:false` or list
    every field as required; codex's strict structured-output validator
    demands both on every object. This strictifies the root and every
    `$defs` entry (nested models). `$defs`/`$ref` are kept — confirmed
    accepted by real codex 0.135.0.
    """
    schema = cls.model_json_schema()
    _strictify_schema_node(schema)
    for d in schema.get("$defs", {}).values():
        _strictify_schema_node(d)
    return schema


def strip_markdown_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        nl = s.find("\n")
        s = s[nl + 1:] if nl != -1 else ""
    if s.endswith("```"):
        s = s[:-3].rstrip()
    return s.strip()


def validate_response(answer_text: str, cls) -> Tuple[bool, Any]:
    """(ok, validated_dict_or_error_string)."""
    cleaned = strip_markdown_fences(answer_text)
    try:
        obj = cls.model_validate_json(cleaned)
        return True, obj.model_dump(mode="json")
    except Exception as e:
        return False, str(e)


# ─── CLI-aware answer extraction (NEW) ────────────────────────────────────

def extract_codex_answer(
    stdout: str, last_msg_path: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Codex `--json` extraction. Returns (answer_text, error_or_None).

    Priority:
    1. `turn.completed` overrides `error` events (Codex emits retry-as-error
       events like `Reconnecting... N/5 (...403...)` followed by HTTP-fallback
       success — these are not real failures).
    2. `turn.failed` without `turn.completed` is authoritative for failure.
    3. Read -o file (final agent_message) → success.
    4. Fallback: last `item.completed` of type `agent_message` in JSONL.
    """
    error_msg: Optional[str] = None
    saw_completed = False
    saw_failed = False
    for ln in stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        t = obj.get("type")
        if t == "error":
            msg = obj.get("message")
            if isinstance(msg, str):
                error_msg = msg
        elif t == "turn.failed":
            saw_failed = True
            err = obj.get("error", {})
            if isinstance(err, dict):
                error_msg = err.get("message", str(err))
        elif t == "turn.completed":
            saw_completed = True
    # Only return error if turn explicitly failed without completion. When
    # turn.completed is present, prior `error` events were transient retry
    # noise (Codex emits Reconnecting... N/5 as `type:error` even when HTTP
    # fallback succeeds). Bailing on first error text caused ~48% silent-fail
    # rate under sustained load (2026-05-03 stress test, 628/1307 codex).
    if saw_failed and not saw_completed:
        return "", error_msg or "turn.failed without message"

    if last_msg_path and os.path.exists(last_msg_path):
        try:
            with open(last_msg_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return "", f"failed to read last_message file: {e}"
        # Empty last_msg file = abnormal — vendor reported success (rc=0)
        # but didn't write any answer. Fall through to JSONL agent_message
        # fallback; if that also yields nothing, the final return at the
        # bottom emits the explicit ext_err. (2026-05-03 later-3 fault test
        # exposed: empty file silently returned as ok.)
        if content.strip():
            return content, None

    for ln in reversed(stdout.splitlines()):
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if obj.get("type") == "item.completed":
            item = obj.get("item", {})
            if item.get("type") == "agent_message":
                return item.get("text", ""), None
    return "", "no final answer in JSONL or last-message file"


def extract_codex_fanout(stdout: str) -> Tuple[list[dict], bool]:
    """Extract per-subagent raw messages from a codex --json collab stream.

    Returns (agents, complete). `agents` is a list of {thread_id, message}
    for each subagent that reached a TERMINAL state (completed / errored /
    interrupted / shutdown / not_found — the codex-rs exec_events wire enum),
    de-duplicated by thread_id (last terminal state wins, since `wait` then
    `close_agent` re-emit the same state). A failed thread's `message` may be
    absent and is recorded as "".

    `complete` is True ONLY if at least one subagent was spawned AND every
    referenced thread reached a `completed` terminal state; False for
    zero-agent fan-out, any failed thread, or any thread that never reached
    a terminal state.
    """
    by_thread: dict[str, dict] = {}
    seen: set[str] = set()                 # every thread the parent referenced
    final_status: dict[str, str] = {}      # last TERMINAL status per thread
    for ln in stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if obj.get("type") != "item.completed":
            continue
        item = obj.get("item", {})
        if item.get("type") != "collab_tool_call":
            continue
        for tid in item.get("receiver_thread_ids") or []:
            if isinstance(tid, str):
                seen.add(tid)
        states = item.get("agents_states") or {}
        for tid, st in states.items():
            if not isinstance(st, dict):
                continue
            seen.add(tid)
            status = st.get("status")
            # Wire enum (codex-rs exec_events, verified rust-v0.135.0 and
            # v0.142.5): pending_init | running | interrupted | completed |
            # errored | shutdown | not_found. "running" is the in-flight
            # value ("in_progress"/"failed" never appear on the wire — the
            # pre-2026-07-04 skip set matched a nonexistent token, so a
            # running snapshot was mis-recorded as terminal).
            if status in ("pending_init", "running", None):
                continue  # not yet terminal — a later event may supersede it
            by_thread[tid] = {"thread_id": tid, "message": st.get("message") or ""}
            final_status[tid] = status  # last terminal status wins (completed OR errored/…)
    # complete iff at least one thread was referenced AND every referenced thread
    # reached a "completed" terminal state. Zero agents (fan-out ignored) or any
    # non-completed/never-terminated thread → False. (no-silent-partial)
    complete = bool(seen) and all(final_status.get(tid) == "completed" for tid in seen)
    return list(by_thread.values()), complete


# --- Implementer-report status helper (Archetype B) ---
# re.match semantics (anchored to start of string) — only the first non-empty
# line is consulted. A buried/echoed "STATUS:" later in the report does NOT
# fire. Fix C (cross-family review 2026-05-31): dropped re.MULTILINE search
# and replaced with first-non-empty-line iteration.
_IMPL_STATUS_RE = re.compile(
    r"STATUS:\s*(DONE_WITH_CONCERNS|DONE|NEEDS_CONTEXT|BLOCKED)\b"
)


def extract_implementer_status(text: str) -> Optional[str]:
    """Deterministic grep of the implementer report's mandated first line
    (`STATUS: <DONE|DONE_WITH_CONCERNS|NEEDS_CONTEXT|BLOCKED>`). Returns the
    status token or None when absent/unrecognized. NOT an AI call — a
    structural check on a constrained output. A None result is a safe
    fallback: leader-side verification is authoritative regardless.

    Only the FIRST non-empty line is consulted (Fix C). A buried or echoed
    `STATUS:` later in the report cannot false-match.
    """
    if not text:
        return None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue  # skip leading blank lines
        m = _IMPL_STATUS_RE.match(s)  # reuse the compiled pattern (anchored)
        return m.group(1) if m else None  # the first non-empty line decides
    return None


def extract_gemini_answer(stdout: str, stderr: str) -> Tuple[str, Optional[str]]:
    """Gemini `--output-format json` extraction.

    Success: stdout = `{response, stats}`. Returns (response, None).
    Failure: stdout often empty, stderr ends with `{...,"error":{...}}`.
    """
    s = stdout.strip()
    if s:
        try:
            obj = json.loads(s)
            err = obj.get("error")
            if err:
                if isinstance(err, dict):
                    return "", err.get("message", str(err))
                return "", str(err)
            response = obj.get("response", "")
            if not isinstance(response, str):
                response = json.dumps(response, ensure_ascii=False)
            # Empty response is silent failure surface — vendor returned
            # valid JSON envelope but no answer. caller (run_cli_with_retry
            # line 637) propagates this to RunResult.extraction_error +
            # exit_code=EXIT_CLI_FAIL so the leader sees explicit failure
            # instead of a silent empty stdout (2026-05-03 later-2 fix).
            if not response:
                return "", "vendor JSON valid but response field empty"
            return response, None
        except Exception as e:
            return "", f"stdout is not valid JSON: {e}"

    # stdout empty — look for a trailing JSON object in stderr. Do not use
    # rfind("{"): Gemini errors are nested as {"error": {"message": ...}}, so
    # the last brace starts the INNER object, not the envelope (L5 twin→SoT
    # port, 2026-07-05 — reverse-scan raw_decode picks the outer envelope).
    decoder = json.JSONDecoder()
    starts = [idx for idx, ch in enumerate(stderr) if ch == "{"]
    for start in reversed(starts):
        candidate = stderr[start:].strip()
        try:
            obj, end = decoder.raw_decode(candidate)
        except ValueError:
            continue
        if candidate[end:].strip():
            continue
        if not isinstance(obj, dict):
            continue
        err = obj.get("error", {})
        if isinstance(err, dict):
            return "", err.get("message", str(err))
        return "", str(err)
    return "", "empty stdout and no parseable error in stderr"


def extract_claude_answer(stdout: str, stderr: str) -> Tuple[str, Optional[str]]:
    """Claude `-p ... --output-format json` extraction.

    Envelope shape (verified 2026-05-05 via spike):
      {"type": "result", "subtype": "success",
       "is_error": bool, "api_error_status": <str|null>,
       "result": "<final answer text>",
       "stop_reason": "...", "session_id": "...",
       "permission_denials": [...], "terminal_reason": "...",
       "total_cost_usd": <float>, "usage": {...}, "modelUsage": {...},
       ...}

    Success: `is_error == false` → returns (result, None).
    Failure surfaces:
      - `is_error == true` (e.g. "Not logged in", API error) → ext_err = result text
      - permission_denials non-empty → ext_err = denial summary (objective signal)
      - JSON parse fail / empty stdout → ext_err = parse description

    Markdown fence-strip safety: `--print` emits no fence (envelope = raw
    JSON) but `--agent` mode can fence-wrap (haiku pattern, recorded in the
    empirical observations). This helper strips a fence safely.
    """
    s = (stdout or "").strip()
    if not s:
        # stdout empty — claude's envelope always arrives on stdout (rc=0
        # case); stderr carries only progress/warnings. A missing envelope
        # is abnormal.
        return "", "empty stdout — claude envelope missing"

    # Fence-strip safety (--agent mode can markdown-wrap the envelope).
    if s.startswith("```"):
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()

    try:
        obj = json.loads(s)
    except Exception as e:
        return "", f"stdout is not valid JSON: {e}"
    if not isinstance(obj, dict):
        return "", "stdout JSON is not an object"

    subtype = obj.get("subtype", "")
    if subtype == "error_max_structured_output_retries":
        return "", "schema-retries-exhausted: structured output failed validation"
    structured = obj.get("structured_output")
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False), None

    is_error = obj.get("is_error", False)
    result = obj.get("result", "")
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False)

    if is_error:
        # Vendor returned an envelope with is_error=true. The result field
        # carries the detailed message (e.g. "Not logged in · Please run
        # /login", an API error description). The repair agent classifies
        # from this message.
        api_status = obj.get("api_error_status")
        prefix = f"is_error=true (api_error_status={api_status})"
        if result:
            return "", f"{prefix}: {result}"
        return "", prefix

    permission_denials = obj.get("permission_denials")
    if permission_denials and not result.strip():
        return "", (
            "task-blocked: permission_denials: "
            f"{json.dumps(permission_denials, ensure_ascii=False)}"
        )

    # A permission_denials entry = a tool block was observed (an objective
    # signal from the claude worker, not the leader's framing). With a
    # NON-EMPTY result the answer is returned first and denials are never
    # surfaced as failure; the EMPTY-result + denials case above promotes to
    # task-blocked (owner adjudication 2026-07-05 — the two rules compose).
    if not result:
        return "", "vendor JSON valid but result field empty"
    return result, None


# ─── Antigravity (agy) pty scrub + sentinel extraction ────────────────────

_AGY_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"       # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[()][AB0]|\x1b[=>]"          # charset / other 2-byte
)


def scrub_agy_output(raw_bytes: bytes) -> str:
    """Pure scrub of agy pty output: decode, strip EOT/backspace, CRLF->LF,
    strip ANSI/control. No sentinel logic (see extract_antigravity_answer)."""
    text = raw_bytes.decode("utf-8", errors="replace")
    text = text.replace("\x04", "").replace("\x08", "")
    text = text.replace("\r\n", "\n").replace("\r", "")
    text = _AGY_ANSI_RE.sub("", text)
    return text


import glob as _glob


_AGY_BRAIN_GLOB = "*/.system_generated/logs/transcript.jsonl"


def _agy_brain_dir() -> str:
    """The agy conversation-store root (override via AGY_BRAIN_DIR for tests)."""
    return os.environ.get(
        "AGY_BRAIN_DIR",
        os.path.expanduser("~/.gemini/antigravity-cli/brain"),
    )


def snapshot_agy_transcripts(brain_dir: str | None = None) -> dict:
    """{transcript_path: mtime} for every conversation transcript, BEFORE a run.

    Paired with extract_agy_answer_from_transcript to BOUND the candidate set to
    conversations created/touched during this call. Identity within that set is
    by the per-invocation sentinel (see extract_agy_answer_from_transcript), NOT
    by mtime — several agy calls may be in flight concurrently. Missing brain dir
    -> {} (first-ever run)."""
    base = brain_dir or _agy_brain_dir()
    out: dict = {}
    for pth in _glob.glob(os.path.join(base, _AGY_BRAIN_GLOB)):
        try:
            out[pth] = os.path.getmtime(pth)
        except OSError:
            # The path EXISTS (glob saw it) — record its presence with a 0.0
            # mtime rather than dropping it (P4 round-3): a transiently
            # stat-failing PRE-EXISTING transcript must never look "new" to
            # the post-run candidate rule, which keys on path presence.
            out[pth] = 0.0
    return out


_AGY_MARKER_RE = re.compile(r"<<<AGY_DONE_[0-9a-f]+>>>")

# Scan refusal threshold for one transcript candidate (see _scan_transcript).
_AGY_TRANSCRIPT_MAX_BYTES = 50 * 1024 * 1024


def _scan_transcript(pth: str, marker: str) -> Tuple[bool, Optional[str]]:
    """Stream ONE transcript once (context-managed, UTF-8-safe). Returns
    (owns, final_done_content):

      - `owns` = a USER_INPUT/USER_EXPLICIT record's content has `marker` as its
        LAST agy-marker (the wrapper-appended sealed-prompt footer). A foreign
        call that merely QUOTES `marker` mid-prompt has its OWN footer marker
        last, so it does NOT own this sentinel (replay defense).
      - `final_done_content` = the last PLANNER_RESPONSE/MODEL/DONE record's
        content (str), or None.

    Malformed/partial JSON lines, valid-JSON non-object records, and non-str
    content are all skipped so a concurrently-appended foreign transcript can
    never crash the scan (errors='replace' handles a truncated multi-byte char;
    the isinstance guards handle `null`/`[]`/`123`/dict-content). (False, None)
    on OSError. Streaming (not `.read()`) bounds memory on a large transcript.

    ASSUMPTION (ground-truthed 500/500 real transcripts, 2026-07-11): a
    single-shot `agy -p` conversation holds EXACTLY ONE USER_INPUT/USER_EXPLICIT
    record, so `owns` and the global last-DONE `final` always belong to the same
    turn. If a future agy multiplexes several turns into one transcript.jsonl
    (e.g. a --resume path), bind `final` to the segment FOLLOWING the owning
    USER_INPUT record instead of the whole file before routing such calls here."""
    owns = False
    final: Optional[str] = None
    try:
        # Resource bound (P4 round-2): a real agy transcript is KB-MB scale;
        # refuse to scan a pathological/foreign multi-GB candidate rather than
        # buffer it — skipping fails closed (not an owner -> pty-scrub path).
        if os.path.getsize(pth) > _AGY_TRANSCRIPT_MAX_BYTES:
            return (False, None)
        with open(pth, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                content = rec.get("content")
                if not isinstance(content, str):
                    continue
                if (rec.get("type") == "USER_INPUT"
                        and rec.get("source") == "USER_EXPLICIT"):
                    ms = _AGY_MARKER_RE.findall(content)
                    if ms and ms[-1] == marker:
                        owns = True
                elif (rec.get("type") == "PLANNER_RESPONSE"
                        and rec.get("source") == "MODEL"
                        and rec.get("status") == "DONE"):
                    final = content
    except OSError:
        return (False, None)
    return (owns, final)


def extract_agy_answer_from_transcript(
    brain_dir: str | None,
    before: dict,
    sentinel: str,
) -> Optional[str]:
    """Read THIS call's final answer from agy's own transcript.jsonl (P4.5
    transport, concurrency-hardened 2026-07-11).

    agy has no native JSON/-o-file output; every run writes a per-conversation
    transcript whose last `PLANNER_RESPONSE/MODEL/DONE` record carries the
    complete ANSI-free answer. A long agentic run drops the trailing marker from
    the ANSWER, but the wrapper-sealed marker is ALWAYS present in the USER_INPUT
    record — that (not the answer, not mtime) is the identity anchor.

    `before` = snapshot_agy_transcripts() taken BEFORE the run bounds the
    candidate set to conversations CREATED during this call (new paths only —
    a single-shot `agy -p` always starts a new conversation). Among those, THIS
    call's transcript is the one that OWNS `sentinel` (_scan_transcript: its
    USER_INPUT footer's LAST marker == this sentinel). EXACTLY ONE owner with a
    DONE record -> return its answer; ZERO owners (crash before USER_INPUT / not
    yet flushed / schema drift) or MORE THAN ONE (a genuine collision) -> None,
    and the caller falls back to the per-call pty-scrub (which reads THIS
    process's own bytes and can NEVER return a foreign answer). Selection is
    NEVER by mtime.

    Concurrency contract: the identity guarantee covers calls dispatched
    THROUGH this wrapper (each seals its own footer marker last). A concurrent
    RAW/manual agy call that quotes a live wrapper call's sealed prompt
    verbatim while that call's own transcript is absent is outside the
    contract — documented residual, not a supported flow.

    `sentinel` is REQUIRED — the wrapper always supplies its per-invocation id."""
    base = brain_dir or _agy_brain_dir()
    after = snapshot_agy_transcripts(base)
    # Ownership candidates are NEW conversations only (P4 round-2 tightening):
    # a single-shot `agy -p` ALWAYS creates a new conversation dir (ground-
    # truthed across the whole brain store), so a pre-existing transcript can
    # never be this call's — excluding mtime-bumped old paths removes both the
    # stale-schema-repair corner and needless scanning of foreign transcripts
    # that were created before the snapshot and are still being appended.
    fresh = [pth for pth in after if pth not in before]
    if not fresh:
        return None
    marker = f"<<<{sentinel}>>>"
    owner_count = 0
    owner_final: Optional[str] = None
    for pth in fresh:
        owns, final = _scan_transcript(pth, marker)
        if owns:
            owner_count += 1
            owner_final = final
    if owner_count != 1 or owner_final is None:
        return None
    content = owner_final.rstrip()
    if content.endswith(marker):
        content = content[:-len(marker)].rstrip()
    return content or None


def extract_antigravity_answer(
    scrubbed: str, killed: bool, expected_sentinel: str
) -> Tuple[Optional[str], Optional[str]]:
    """Find the exact per-call sentinel in already-scrubbed text. Present and
    TERMINAL -> (answer_without_sentinel, None). Absent -> (None, 'no-sentinel').

    Uses the LAST marker occurrence (rfind) so an early echoed marker — e.g.
    the model quoting the closing instruction back at the top — does not
    truncate a real answer that ends at the genuine terminal marker.

    P4.c strictness (spec 3-way 2026-07-11): the accepted marker must be
    TERMINAL — the tail after it is whitespace only (the sealed prompt says
    "and nothing after it"; the live-spike healthy tail is a single '\\n')
    AND the marker is newline-preceded (own-line floor, re-confirm round-2:
    the sealed prompt instructs the marker "on its own line", so an INLINE
    early echo at the exact end of a truncated capture must not pass).
    Either violation means the genuine terminal marker never arrived
    -> (None, 'non-terminal-marker'), never a partial prefix as ok. Widen to
    a residue allowlist ONLY on captured real-fixture evidence (anchored
    full-tail match, <=1024 chars), never a broad pattern.

    killed=True fails closed here as belt-and-suspenders — the driver
    already short-circuits killed -> timeout BEFORE extraction; this guards
    a future caller that skips that ordering.
    """
    if killed:
        return None, "killed-partial"
    marker = f"<<<{expected_sentinel}>>>"
    idx = scrubbed.rfind(marker)
    if idx == -1:
        return None, "no-sentinel"
    if scrubbed[idx + len(marker):].strip():
        return None, "non-terminal-marker"
    if idx > 0 and not scrubbed[:idx].endswith("\n"):
        # Own-line floor (re-confirm round-2, both families): the sealed
        # prompt instructs the marker "on its own line", so a genuine
        # terminal marker is newline-preceded. An INLINE marker at the exact
        # end of a truncated capture ("I will end with <<<S>>>") would
        # otherwise pass the whitespace-tail check and surface the partial
        # prefix as ok. idx==0 stays allowed: an empty body routes to the
        # driver's empty-answer-body, not here.
        return None, "non-terminal-marker"
    return scrubbed[:idx].rstrip(), None


# ─── Subprocess core ──────────────────────────────────────────────────────

# Loader / interpreter injection env vars scrubbed from the vendor child (I-2/I-3).
# `_run_once` is the one `subprocess.Popen` site (codex/gemini/claude), and
# `_pty.run_via_pty` (the agy transport) is a SEPARATE vendor-child spawn — agy
# does NOT go through Popen. BOTH spawn sites apply the SAME scrub via the shared
# `scrubbed_child_env()` below, so a poisoned parent env cannot reach the vendor
# CLI (gemini/claude/agy are Node runtimes; codex/agy spawn tools). The classic
# vectors: the dynamic loader (LD_PRELOAD / LD_AUDIT / the macOS DYLD_* family),
# the Node runtime (NODE_OPTIONS=--require=<evil.js> would run workspace code
# OUTSIDE any sandbox; NODE_PATH), the Python / shell / Perl / Ruby interpreters
# (PYTHONPATH / BASH_ENV / ENV / PERL5LIB / RUBYOPT ...). PATH is deliberately
# NOT scrubbed here — the vendor-binary pin (`require_binary` / `TRIAD_<CLI>_BIN`)
# fixes the vendor bin, and PATH policy belongs to the install leg, not this
# shared engine change.
_CHILD_ENV_SCRUB = (
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    "NODE_OPTIONS", "NODE_PATH",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
    "BASH_ENV", "ENV", "PERL5LIB", "RUBYOPT", "RUBYLIB",
)


def scrubbed_child_env(base=None) -> dict:
    """The single-source vendor-child env: `base` (default `os.environ`) minus the
    `_CHILD_ENV_SCRUB` injection vars. Applied at BOTH vendor-child spawn sites —
    `_run_once` (Popen) and `_pty.run_via_pty` (agy pty transport, env=None) — so
    the scrub policy lives in exactly ONE place. Returns a fresh dict (safe to
    mutate, e.g. the pty transport's `setdefault("TERM", "dumb")`)."""
    src = base if base is not None else os.environ
    return {k: v for k, v in src.items() if k not in _CHILD_ENV_SCRUB}


def _drain(stream, accum: list[str], passthrough) -> None:
    """Reader thread — line iter, accumulate, optional mirror to passthrough."""
    try:
        for line in iter(stream.readline, ""):
            accum.append(line)
            if passthrough is not None:
                try:
                    passthrough.write(line)
                    passthrough.flush()
                except Exception:
                    pass
        try:
            stream.close()
        except Exception:
            pass
    except Exception as e:
        log(f"reader thread error: {e}")


def _run_once(
    cli: str,
    cmd: list[str],
    cwd: Optional[str],
    timeout: int,
    stdin_text: Optional[str] = None,
) -> RunResult:
    """One Popen invocation.

    stdout = capture-only (structured JSON/JSONL — not for human stream).
    stderr = mirror to parent stderr (human progress visibility).
    stdin_text: when provided, feed via a daemon writer thread so a large
    prompt cannot deadlock against a full OS pipe before the child starts
    reading. When None (default), stdin is DEVNULL (gemini/claude behavior
    unchanged).
    """
    log(f"exec cwd={cwd or os.getcwd()} timeout={timeout}s argv={cmd}")
    start = time.monotonic()

    # Scrub loader/interpreter injection vars so a poisoned parent env cannot
    # reach the vendor child (I-2/I-3). Explicit env= replaces the implicit
    # full-os.environ inheritance. scrubbed_child_env() is the shared
    # single-source scrub (the agy pty transport applies the same one).
    child_env = scrubbed_child_env()

    popen_kwargs: dict = dict(
        cwd=cwd,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=(subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL),
        text=True,
        bufsize=1,
    )
    if hasattr(os, "setsid"):
        popen_kwargs["preexec_fn"] = os.setsid

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as e:
        elapsed = time.monotonic() - start
        log(f"OSError on spawn: {e}")
        return RunResult(
            EXIT_ARG_ERROR, "", f"spawn failed: {e}\n", elapsed,
            classification="unknown",
        )

    if stdin_text is not None and proc.stdin is not None:
        def _feed_stdin() -> None:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.flush()
            except Exception:
                pass
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
        threading.Thread(target=_feed_stdin, daemon=True).start()

    stdout_buf: list[str] = []
    stderr_buf: list[str] = []
    t_out = threading.Thread(
        target=_drain, args=(proc.stdout, stdout_buf, None), daemon=True
    )
    t_err = threading.Thread(
        target=_drain, args=(proc.stderr, stderr_buf, sys.stderr), daemon=True
    )
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        log(f"timeout after {timeout}s; sending SIGTERM")
        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except (ProcessLookupError, PermissionError) as e:
            log(f"SIGTERM failed: {e}")
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log("SIGTERM ignored; sending SIGKILL")
            try:
                if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except (ProcessLookupError, PermissionError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log("zombie: SIGKILL also unresponsive")

    t_out.join(timeout=2)
    t_err.join(timeout=2)

    elapsed = time.monotonic() - start
    stdout = "".join(stdout_buf)
    stderr = "".join(stderr_buf)
    rc = proc.returncode if proc.returncode is not None else -1

    if timed_out:
        log(f"timed out elapsed={elapsed:.1f}s")
        result = RunResult(EXIT_TIMEOUT, stdout, stderr, elapsed)
    else:
        log(f"exit={rc} elapsed={elapsed:.1f}s")
        ec = EXIT_OK if rc == 0 else EXIT_CLI_FAIL
        result = RunResult(ec, stdout, stderr, elapsed)

    result.vendor_exit_code = rc
    result.classification = classify(
        cli, stderr, stdout, result.exit_code, vendor_exit_code=rc,
    )

    # One-line deterministic summary (immediately visible to leader/user).
    # SEMANTIC stderr classification (tool-not-installed / vendor warning)
    # stays the leader's judgment over the mirrored raw stderr.
    log(
        f"[wrapper] {cli} {result.classification} "
        f"exit={result.exit_code} vendor={result.vendor_exit_code} "
        f"elapsed={elapsed:.1f}s"
    )

    return result


def run_cli_with_retry(
    cli: str,
    cmd_builder: Callable[[str], list[str]],
    prompt: str,
    cwd: Optional[str],
    timeout: int,
    pydantic_cls: Any = None,
    last_msg_path: Optional[str] = None,
    repair_mode: bool = False,
    prompt_via_stdin: bool = False,
) -> RunResult:
    """Top-level driver.

    Layers (in order):
    1. Schema injection — if `pydantic_cls`, prepend the schema block to prompt.
    2. Server-capacity retry — `SERVER_CAP_BACKOFF_S` (skipped if `repair_mode`).
    3. Answer extraction — cli-aware (JSONL events / single JSON object).
    4. Schema validation — if `pydantic_cls`, validate; on failure, retry once
       (mode = "schema_repair") with a clarifying suffix in the prompt.

    `cmd_builder(prompt) -> argv` lets us rebuild the argv after schema-repair
    prompt mutation without leaking command construction into this function.
    """
    # Next-run IPC cleanup (owner contract: a subsequent run clears prior
    # residue). Skipped in repair_mode — the repair agent is actively inspecting
    # the just-written run-log; the age floor protects it anyway, but skipping
    # avoids touching the runs dir mid-repair.
    if not repair_mode:
        prune_stale_run_logs(cli)

    effective_prompt = (
        inject_schema_to_prompt(prompt, pydantic_cls) if pydantic_cls else prompt
    )

    def promote_schema_fail(r: RunResult) -> RunResult:
        r.exit_code = EXIT_SCHEMA_FAIL
        r.classification = "schema-fail"
        r.final_answer = ""
        log(
            f"[wrapper] {cli} schema-fail "
            f"exit={r.exit_code} vendor={r.vendor_exit_code} "
            f"elapsed={r.elapsed_s:.1f}s"
        )
        return r

    terminal_classes = (
        "cli-subscription-cap",
        "token-limit",
        "oauth-env",
        "fanout-spawn-error",
        "config-conflict",
        "task-blocked",
    )

    def promote_terminal(r: RunResult, cls: str) -> RunResult:
        r.exit_code = EXIT_TERMINAL
        r.classification = cls
        r.final_answer = ""
        log(
            f"[wrapper] {cli} {cls} "
            f"exit={r.exit_code} vendor={r.vendor_exit_code} "
            f"elapsed={r.elapsed_s:.1f}s"
        )
        return r

    def promote_claude_extraction(r: RunResult, ext_err: str) -> Optional[RunResult]:
        if ext_err.startswith("schema-retries-exhausted:"):
            log(f"answer extraction error: {ext_err}")
            r.extraction_error = ext_err
            return promote_schema_fail(r)
        if ext_err.startswith("task-blocked:"):
            log(f"answer extraction error: {ext_err}")
            r.extraction_error = ext_err
            return promote_terminal(r, "task-blocked")
        if ext_err.startswith("is_error=true"):
            cls = classify(
                "claude",
                stderr=ext_err,
                stdout="",
                exit_code=EXIT_CLI_FAIL,
                vendor_exit_code=r.vendor_exit_code,
            )
            if cls in terminal_classes:
                log(f"answer extraction error: {ext_err}")
                r.extraction_error = ext_err
                return promote_terminal(r, cls)
        return None

    def promote_extraction_classification(
        r: RunResult, ext_err: str
    ) -> Optional[RunResult]:
        if cli == "claude":
            promoted = promote_claude_extraction(r, ext_err)
            if promoted is not None:
                return promoted
        cls = classify(
            cli,
            stderr=ext_err,
            stdout="",
            exit_code=EXIT_CLI_FAIL,
            vendor_exit_code=r.vendor_exit_code,
        )
        if cls in terminal_classes:
            r.extraction_error = ext_err
            return promote_terminal(r, cls)
        if cls == "schema-rejected":
            r.exit_code = EXIT_SCHEMA_REJECTED
            r.classification = cls
            r.final_answer = ""
            log(
                f"[wrapper] {cli} {cls} "
                f"exit={r.exit_code} vendor={r.vendor_exit_code} "
                f"elapsed={r.elapsed_s:.1f}s"
            )
            return r
        return None

    schema_repair_attempt = 0
    while True:
        cmd = cmd_builder(effective_prompt)

        # Layer 2: server-cap retry.
        max_retries = 0 if repair_mode else SERVER_CAP_MAX_RETRIES
        result: Optional[RunResult] = None
        for attempt in range(max_retries + 1):
            r = _run_once(
                cli, cmd, cwd=cwd, timeout=timeout,
                stdin_text=effective_prompt if prompt_via_stdin else None,
            )
            r.repair_attempt = attempt if repair_mode else 0
            r.schema_repair_attempt = schema_repair_attempt
            if repair_mode:
                r.mode = "repair"
            elif schema_repair_attempt > 0:
                r.mode = "schema_repair"
            else:
                r.mode = "normal"
            result = r
            cls = r.classification
            if cli == "claude":
                _answer, ext_err = extract_claude_answer(r.stdout, r.stderr)
                if ext_err:
                    promoted = promote_claude_extraction(r, ext_err)
                    if promoted is not None:
                        return promoted
                    # Finding #1 (2026-07-05): a claude API error envelope
                    # (is_error=true, rc=0) is classified "ok" by the rc-based
                    # `classify` above (cls = r.classification). promote_claude_
                    # extraction returns None for a NON-terminal re-classification
                    # (server-capacity is retryable, not terminal), so cls stayed
                    # "ok" and the loop broke BELOW before the server-cap retry —
                    # a retryable overload surfaced as extraction-error with zero
                    # retries. Propagate a retryable re-classification into cls
                    # (and r.classification, so a retry-exhaust returns a consistent
                    # rc=64/server-capacity result) to engage the retry branch.
                    if ext_err.startswith("is_error=true"):
                        recls = classify(
                            "claude", stderr=ext_err, stdout="",
                            exit_code=EXIT_CLI_FAIL,
                            vendor_exit_code=r.vendor_exit_code,
                        )
                        if recls == "server-capacity":
                            r.classification = cls = "server-capacity"
            if cls == "ok":
                break
            if cls in terminal_classes:
                # Re-emit summary so the [wrapper] line's exit token matches
                # the wrapper's actual final rc (65). Without this the line
                # carries _run_once's stale rc=1 which contradicts the
                # wrapper's $? (2026-05-03 later-3 fault test exposed).
                return promote_terminal(r, cls)
            if cls == "schema-rejected":
                r.exit_code = EXIT_SCHEMA_REJECTED
                log(
                    f"[wrapper] {cli} {cls} "
                    f"exit={r.exit_code} vendor={r.vendor_exit_code} "
                    f"elapsed={r.elapsed_s:.1f}s"
                )
                return r
            if cls == "server-capacity":
                if attempt < max_retries:
                    wait = SERVER_CAP_BACKOFF_S[attempt]
                    # Test seam (mirrors agy's AGY_NO_BACKOFF): zero the backoff so
                    # the retry PATH can be verified without the (15,45)s wall.
                    # Off by default — consumers keep the real backoff.
                    if os.environ.get("TRIAD_SERVER_CAP_NO_BACKOFF") == "1":
                        wait = 0
                    log(
                        f"server-capacity (attempt {attempt+1}/{max_retries+1}); "
                        f"sleep {wait}s"
                    )
                    time.sleep(wait)
                    continue
                r.exit_code = EXIT_RATE_GIVE_UP
                # Re-emit — promote rc=1 → 64 in the [wrapper] line.
                log(
                    f"[wrapper] {cli} {cls} "
                    f"exit={r.exit_code} vendor={r.vendor_exit_code} "
                    f"elapsed={r.elapsed_s:.1f}s"
                )
                return r
            # cls in {"unknown", "timeout"} — fail-fast. Both surface as
            # repair-agent territory at the dispatch SKILL layer (timeout =
            # likely ESCALATE since hang isn't a classifier gap, but the
            # SKILL still routes through the same path for uniformity).
            return r

        assert result is not None

        # Layer 3: extract final answer.
        if cli == "codex":
            answer, ext_err = extract_codex_answer(result.stdout, last_msg_path)
        elif cli == "claude":
            answer, ext_err = extract_claude_answer(result.stdout, result.stderr)
        else:
            answer, ext_err = extract_gemini_answer(result.stdout, result.stderr)

        if ext_err:
            log(f"answer extraction error: {ext_err}")
            result.extraction_error = ext_err
            result.final_answer = ""
            promoted = promote_extraction_classification(result, ext_err)
            if promoted is not None:
                return promoted
            if result.exit_code == EXIT_OK:
                # Vendor returned rc=0 but extractor found no answer (empty
                # JSON envelope, missing last-message file, etc.). Promote
                # to wrapper failure AND re-classify — `_run_once` had set
                # classification="ok" based on rc alone, which is now stale.
                # Re-emit the 1-line summary so dispatch SKILL Step 3 grep
                # gets the corrected token (2026-05-03 later-3).
                result.exit_code = EXIT_CLI_FAIL
                result.classification = "extraction-error"
                log(
                    f"[wrapper] {cli} extraction-error "
                    f"exit={result.exit_code} vendor={result.vendor_exit_code} "
                    f"elapsed={result.elapsed_s:.1f}s"
                )
            return result

        result.final_answer = answer

        # Layer 4: schema validation.
        if pydantic_cls is None:
            return result

        ok, validated_or_err = validate_response(answer, pydantic_cls)
        if ok:
            result.validated = validated_or_err
            return result

        result.validation_error = str(validated_or_err)
        log(f"schema validation failed: {validated_or_err}")

        if schema_repair_attempt >= 1 or repair_mode:
            return promote_schema_fail(result)

        # 1 retry — augment prompt with the failure notice and loop.
        schema_repair_attempt += 1
        effective_prompt = (
            effective_prompt
            + "\n\nIMPORTANT: Your previous response failed JSON schema validation:\n"
            + f"{validated_or_err}\n\n"
            + "Reply again with valid JSON only — no prose, no markdown fences."
        )
        log(f"schema_repair_attempt {schema_repair_attempt}/1 — retrying")


# ─── Audit log ────────────────────────────────────────────────────────────

# TRIAD_DISPATCH_LOG_DIR overrides the log root (audit + run-logs; the --debug
# markdown dir is separate). Default = wrapper-adjacent _logs/. Consumers/tests point it
# at a temp dir so an installed plugin dir is never mutated (plugin roots are
# ephemeral per the Claude Code plugin docs).
_LOG_DIR = Path(os.environ.get("TRIAD_DISPATCH_LOG_DIR")
                or Path(__file__).resolve().parent / "_logs")
_DEBUG_DIR = Path(__file__).resolve().parent / "_debug"


def audit(cli: str, cmd: list[str], prompt: str, result: RunResult) -> None:
    """Append one JSONL record per invocation to _logs/<cli>/audit.jsonl.

    A per-CLI lock file serializes append + rotation across processes.
    `final_answer_head` caps at 500 chars; full answer flows to caller via
    `result.final_answer`.
    """
    log_dir = _LOG_DIR / cli
    log_dir.mkdir(parents=True, exist_ok=True)
    ok = result.exit_code == EXIT_OK
    redact = _audit_redact_enabled()
    # Custody taxonomy (P4.b, spec 3-way 2026-07-11; extends the 2026-07-05
    # prompt-custody adjudication): in redact mode, MODEL-OUTPUT fields
    # (final_answer_head, extraction_error) are allowed at a 500 cap, but
    # STREAMS that can carry PROMPT content (stdout, stdout_head, stderr —
    # vendor UIs/JSON envelopes may reflect the input) are fully "<redacted>"
    # (+ lengths): a partial cap cannot guarantee prompt custody because a
    # prompt echo rides the stream HEAD. Applied to this record only — the
    # RunResult is never mutated (emit_run_log() runs AFTER audit() and must
    # keep the full copies in the transient, pruned run-log).
    def _redact_cap(text: Optional[str]) -> Optional[str]:
        """Model-output field custody: the adjudicated 500 cap in redact mode."""
        if redact and text and len(text) > 500:
            return text[:500] + " …[redact-cap]"
        return text

    rec: dict = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cli": cli,
        # Prompt custody (adjudication 2026-07-05): lab default = full evidence;
        # hardened/redact mode strips prompt-bearing argv + prompt text (length
        # only) so a public install's durable audit never MECHANICALLY stores
        # prompts. Explicit allowance (re-confirm 2026-07-11): the 500-capped
        # model-output fields (final_answer_head / extraction_error /
        # validation_error) may incidentally contain prompt text the MODEL
        # chose to echo into its answer — the guarantee covers mechanical
        # storage of the input, not model-echoed content.
        "cmd": _redact_prompt_args(cmd) if redact else cmd,
        "prompt_head": "<redacted>" if redact else prompt[:200],
        "prompt_len": len(prompt),
        "vendor_exit_code": result.vendor_exit_code,
        "exit_code": result.exit_code,
        "elapsed_s": round(result.elapsed_s, 2),
        "classification": result.classification,
        "mode": result.mode,
        "repair_attempt": result.repair_attempt,
        "schema_repair_attempt": result.schema_repair_attempt,
        "stderr": "<redacted>" if redact else result.stderr,
        "final_answer_head": (result.final_answer or "")[:500],
        "final_answer_len": len(result.final_answer or ""),
        # validated (the full pydantic dict) and validation_error (pydantic's
        # message embeds the model's failing input) are the SAME model-output
        # class as final_answer_head — the taxonomy bounds them too (panel
        # custody-lens finding 2026-07-11; schema-fail empties final_answer
        # but validation_error would otherwise carry the answer uncapped).
        "validated": ("<redacted>" if (redact and result.validated is not None)
                      else result.validated),
        "extraction_error": _redact_cap(result.extraction_error),
        "validation_error": _redact_cap(result.validation_error),
    }
    if redact:
        rec["stderr_len"] = len(result.stderr or "")
    if ok:
        rec["stdout_head"] = "<redacted>" if redact else result.stdout[:500]
        rec["stdout_len"] = len(result.stdout)
    elif redact:
        rec["stdout"] = "<redacted>"
        rec["stdout_len"] = len(result.stdout or "")
    else:
        rec["stdout"] = result.stdout
    path = log_dir / "audit.jsonl"
    lock_path = log_dir / ".audit.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                # Flush the record while the audit lock is held so append and
                # possible rotation are one serialized critical section.
                f.flush()
            _rotate_audit_if_needed(log_dir, path, cli)
        finally:
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
            except Exception:
                pass


def _rotate_audit_if_needed(log_dir: Path, path: Path, cli: str) -> None:
    """Rotate active audit log and cap archives.

    Called under `.audit.lock`. Best-effort: audit must never fail the wrapper
    call path.
    """
    try:
        if path.stat().st_size <= AUDIT_ROTATE_BYTES:
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = log_dir / f"audit.{stamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}.jsonl"
        path.rename(archive)
        path.touch()
        log(
            f"WARN: rotated {cli}/audit.jsonl to {archive.name} "
            f"(>{AUDIT_ROTATE_BYTES // (1024*1024)} MB)"
        )
        _prune_audit_archives(log_dir)
    except Exception:
        pass


def _prune_audit_archives(log_dir: Path) -> None:
    """Bound audit archives by count and aggregate bytes."""
    try:
        entries = list(log_dir.glob("audit.*.jsonl"))
    except Exception:
        return
    rows: list[tuple[Path, float, int]] = []
    for p in entries:
        try:
            st = p.stat()
            rows.append((p, st.st_mtime, st.st_size))
        except OSError:
            continue
    rows.sort(key=lambda x: x[1])
    total_bytes = sum(sz for _, _, sz in rows)
    over_count = max(0, len(rows) - AUDIT_MAX_ARCHIVES)
    over_bytes = total_bytes - AUDIT_ARCHIVE_MAX_BYTES
    for p, _, sz in rows:
        if over_count <= 0 and over_bytes <= 0:
            break
        try:
            p.unlink()
            over_count -= 1
            over_bytes -= sz
        except OSError:
            continue


# ─── Deterministic classifier-patch applier (repair read-only redesign) ────
# The repair sub-agent is a READ-ONLY analyzer: it returns a structured patch
# PROPOSAL and has ZERO write authority. This function is the SINGLE trusted
# write path to the classifier extension JSON — validate against the enum +
# pattern-name SoT + literal bounds, then flock + atomic-write. No LLM in the
# write path; safe-by-construction against classifier-poisoning.
#
#   CLASSIFICATION_TOKENS = the classify() result enum (keys of the
#     map_classification_to_exit dict — the single source of truth).
#     EXCEPTION (deliberate, P4 2026-07-11): `vendor-error` is in the exit map
#     but NOT here — it is emitted directly by the agy driver when rc!=0 with a
#     non-empty answer (a condition a classifier patch cannot express), so it
#     must never be a proposable repair target.
#   PATTERN_LIST_NAMES    = the built-in pattern-list constant names an
#     extension may extend (a proposal's pattern_list must be one of these).

CLASSIFICATION_TOKENS: frozenset[str] = frozenset(
    (
        "ok",
        "server-capacity",
        "cli-subscription-cap",
        "token-limit",
        "oauth-env",
        "timeout",
        "extraction-error",
        "schema-fail",
        "schema-rejected",
        "fanout-spawn-error",
        "config-conflict",
        "task-blocked",
        "unknown",
    )
)
# Assert the enum stays in lock-step with map_classification_to_exit() — the SoT.
# `.get(cls, ...)` there means every literal branch is a valid classification;
# a drift here (token added to one and not the other) fails fast at import.
assert all(
    map_classification_to_exit(_t) is not None for _t in CLASSIFICATION_TOKENS
), "CLASSIFICATION_TOKENS drifted from map_classification_to_exit"

PATTERN_LIST_NAMES: frozenset[str] = frozenset(
    (
        "SERVER_CAPACITY_PATTERNS",
        "CLI_SUB_CAP_PATTERNS",
        "TOKEN_LIMIT_PATTERNS",
        "OAUTH_ENV_PATTERNS",
        "SCHEMA_REJECTED_PATTERNS",
        "FANOUT_SPAWN_PATTERNS",
        "CONFIG_CONFLICT_PATTERNS",
        "AGY_AUTH_BANNER_PATTERNS",
    )
)

# The meaningful-failure subset a repair PROPOSAL may target. `ok` = success →
# mapping a real failure to it SUPPRESSES failures; `unknown` = the default/meta
# bucket, never a useful patch target. (fix1 round, review BLOCKER.)
REPAIR_CLASSIFICATION_TOKENS: frozenset[str] = frozenset(
    CLASSIFICATION_TOKENS - {"ok", "unknown"}
)

# Each pattern-list name → the canonical classification classify() returns when
# that list matches. An EXACT mirror of classify() (see the L2 substring block):
#   AGY_AUTH_BANNER → oauth-env, CLI_SUB_CAP → cli-subscription-cap,
#   SERVER_CAPACITY → server-capacity, TOKEN_LIMIT → token-limit,
#   OAUTH_ENV → oauth-env, SCHEMA_REJECTED → schema-rejected,
#   FANOUT_SPAWN → fanout-spawn-error, CONFIG_CONFLICT → config-conflict.
# A pattern proposal's `classification` must equal PATTERN_LIST_CLASS[pattern_list]
# (else appending the substring would make classify() return a DIFFERENT class
# than the proposal claims). Locked in step with PATTERN_LIST_NAMES at import.
PATTERN_LIST_CLASS: dict[str, str] = {
    "SERVER_CAPACITY_PATTERNS": "server-capacity",
    "CLI_SUB_CAP_PATTERNS": "cli-subscription-cap",
    "TOKEN_LIMIT_PATTERNS": "token-limit",
    "OAUTH_ENV_PATTERNS": "oauth-env",
    "SCHEMA_REJECTED_PATTERNS": "schema-rejected",
    "FANOUT_SPAWN_PATTERNS": "fanout-spawn-error",
    "CONFIG_CONFLICT_PATTERNS": "config-conflict",
    "AGY_AUTH_BANNER_PATTERNS": "oauth-env",
}
assert (
    set(PATTERN_LIST_CLASS.keys()) == set(PATTERN_LIST_NAMES)
), "PATTERN_LIST_CLASS drifted from PATTERN_LIST_NAMES (classify() mirror broke)"
assert all(
    _c in CLASSIFICATION_TOKENS for _c in PATTERN_LIST_CLASS.values()
), "PATTERN_LIST_CLASS maps to a class not in CLASSIFICATION_TOKENS"

# Bound on a proposed substring literal — long enough for real vendor phrases,
# short enough that a poisoned proposal cannot smuggle a huge blob into the
# classifier or bloat the extension file.
_MAX_SUBSTRING_LEN = 200
# Floor on a proposed substring length (after lowercase-normalize). A defensible
# floor that rejects the pathological "e"/"the" while allowing real short
# signatures ("oauth", "quota"). NOT a claim of full semantic specificity — that
# is the analyzer's + owner's job (see SECURITY.md), only a coarse over-broad guard.
_MIN_SUBSTRING_LEN = 4
# Per-cli total entry cap across vendor_exit_map + all pattern lists — bounded
# growth so a stream of proposals cannot unboundedly bloat the extension.
_MAX_EXTENSION_ENTRIES = 500
# Bound on the analyzer's free-text `reason` (untrusted-derived, surfaced into
# the leader's context — defense-in-depth against an over-long injection blob).
_MAX_REASON_LEN = 500

# ── fix2/fix3: L1 vendor_exit_map symmetric guard (round-2 + round-3 re-confirm
# BLOCKERs) ────────────────────────────────────────────────────────────────
# classify() consults the (extension-merged) vmap BEFORE the L2 substrings and
# returns immediately, so a poisoned vmap entry has HIGHER blast radius than a
# poisoned substring — round-1 floored L2, round-2 made L1 symmetric via a
# hardcoded enumeration (`_GENERIC_EXIT_CODES`). Round-3 found that enumeration
# LEAKY: it listed 130/137/143 (128+SIGINT/SIGKILL/SIGTERM) but missed the other
# 128+N signal-death codes — e.g. 139 (SIGSEGV), 141 (SIGPIPE), 134 (SIGABRT) —
# so a proposal like {"vendor_exit_code": 139, ...} still passed and could
# poison every future segfault's routing. An enumeration of "the other 128+N
# codes" can never be complete (any signum 1-31 not yet listed is a fresh gap).
#
# Fix: a SOUND RANGE, not an enumeration. A legitimate vendor application-
# specific exit code lives in [3, 125]. Outside that range is either too
# generic or reserved/signal-death, and too broad to safely auto-route:
#   - {0, 1, 2}     = generic (success / general error / misuse-or-EXIT_TIMEOUT)
#   - {126, 127}    = shell (not-executable / not-found)
#   - [128, 255]    = signal-death (128+signum, e.g. 130=SIGINT, 137=SIGKILL,
#                     139=SIGSEGV, 141=SIGPIPE, 143=SIGTERM) or reserved/OOR
# A vmap PROPOSAL outside [3, 125] is refused — the analyzer must propose a
# specific stderr `substring` (L2) or escalate. This is the L1 analog of the
# L2 `_MIN_SUBSTRING_LEN` over-broad floor. (The built-in `<CLI>_VENDOR_EXIT_MAP`
# dicts are trusted hardcoded maps, NOT proposals — this bounds PROPOSALS only.)
_VENDOR_EXIT_CODE_MIN = 3
_VENDOR_EXIT_CODE_MAX = 125

# A vendor's own EXIT CODE cannot mean a WRAPPER-determined status, so a vmap
# PROPOSAL is restricted to the vendor-exit-DERIVABLE classes. Kept: the vendor-
# error classes (server-capacity, cli-subscription-cap, token-limit, oauth-env,
# schema-rejected) + extraction-error (the built-in ANTIGRAVITY_VENDOR_EXIT_MAP[0]
# weak no-answer fallback legitimately uses it, so it stays a valid vmap class).
# Excluded (the wrapper/status classes the WRAPPER decides, never a raw vendor
# exit): timeout (wrapper kills the vendor on its own timeout — exit_code==
# EXIT_TIMEOUT in classify(), not a vmap code); schema-fail (wrapper pydantic
# JSON validation — EXIT_SCHEMA_FAIL, not in classify()); task-blocked (codex
# --task STATUS parse — extract_implementer_status→exit 69); fanout-spawn-error
# (wrapper fan-out condition via FANOUT_SPAWN_PATTERNS substring); config-conflict
# (wrapper/config condition via CONFIG_CONFLICT_PATTERNS + agy settings txn).
# Verified against classify() + the wrapper exit-code semantics (2026-07-06).
# This applies ONLY to the vendor_exit_map path — the PATTERN path already
# enforces classification == PATTERN_LIST_CLASS[pattern_list].
VENDOR_EXIT_PROPOSAL_CLASSES: frozenset[str] = frozenset(
    REPAIR_CLASSIFICATION_TOKENS
    - {"timeout", "schema-fail", "task-blocked", "fanout-spawn-error", "config-conflict"}
)
assert (
    VENDOR_EXIT_PROPOSAL_CLASSES <= REPAIR_CLASSIFICATION_TOKENS
), "VENDOR_EXIT_PROPOSAL_CLASSES must be a subset of REPAIR_CLASSIFICATION_TOKENS"


def apply_classifier_patch(cli: str, proposal: dict) -> str:
    """Validate + atomically merge a repair-analyzer proposal into the classifier
    extension JSON. The SINGLE trusted write path (zero LLM here).

    proposal = {
        "classification": <one of REPAIR_CLASSIFICATION_TOKENS>,  # required (NOT ok/unknown)
        "reason":         <one-line str, <= _MAX_REASON_LEN>,     # required
        # exactly one target:
        "vendor_exit_code": <int > 0>,    # append {code: classification} to vendor_exit_map
        "pattern_list":     <one of PATTERN_LIST_NAMES>,  # + "substring": <bounded str>
        "substring":        <non-empty bounded literal str, stored LOWERCASED>,
    }

    Semantic validation (all BEFORE any file write; ValueError on violation):
      - classification ∈ REPAIR_CLASSIFICATION_TOKENS (ok/unknown rejected — ok
        would suppress real failures, unknown is the default bucket).
      - vendor_exit_code must be an int bounded to the application-specific
        range [3, 125] ({0,1,2}=generic, {126,127}=shell, >=128=signal-death/
        reserved are too broad to auto-route — the L1 analog of the L2 length
        floor; a sound range, not an enumeration [fix3]), AND its classification
        must be vendor-exit-derivable (∈ VENDOR_EXIT_PROPOSAL_CLASSES — a wrapper/
        status class cannot be inferred from a raw vendor exit code). [fix2]
      - substring is lowercased (classify() lowercases the blob), then floored at
        _MIN_SUBSTRING_LEN and required to carry alphanumeric signal — rejects the
        over-broad "e"/whitespace-only case. (Fine-grained SPECIFICITY rests on the
        analyzer + owner review, not this coarse floor — see SECURITY.md.)
      - pattern proposals require classification == PATTERN_LIST_CLASS[pattern_list]
        (the class that list actually yields in classify()).
      - reason length <= _MAX_REASON_LEN.
      - per-cli total entries (vendor_exit_map + all pattern lists) may not exceed
        _MAX_EXTENSION_ENTRIES (bounded growth).

    Returns "applied" on success. Raises ValueError on ANY invalid field and
    leaves the extension file UNTOUCHED. A transient read OSError (EACCES/EMFILE/
    EISDIR — NOT FileNotFoundError) PROPAGATES and preserves the existing file
    (never laundered into a `{}` reset that os.replace would clobber). Holds
    fcntl.flock(LOCK_EX) on the `<ext>.lock` sibling for the whole
    read->validate->merge->write cycle (mirrors audit()); writes atomically via a
    temp file + os.replace().
    """
    # ── Validate the proposal shape BEFORE touching any file ────────────────
    if not isinstance(cli, str) or not cli.strip():
        raise ValueError("apply_classifier_patch: cli must be a non-empty str")
    if not isinstance(proposal, dict):
        raise ValueError("apply_classifier_patch: proposal must be a dict")

    classification = proposal.get("classification")
    # SEMANTIC: only a meaningful-failure class is a valid patch target. Reject
    # `ok` (would suppress real failures) and `unknown` (meta/default bucket).
    if classification not in REPAIR_CLASSIFICATION_TOKENS:
        raise ValueError(
            f"apply_classifier_patch: invalid classification "
            f"{classification!r} (not in REPAIR_CLASSIFICATION_TOKENS; "
            f"ok/unknown are not valid patch targets)"
        )

    vendor_exit_code = proposal.get("vendor_exit_code")
    pattern_list = proposal.get("pattern_list")
    substring = proposal.get("substring")

    has_exit = vendor_exit_code is not None
    has_pattern = pattern_list is not None or substring is not None

    if not has_exit and not has_pattern:
        raise ValueError(
            "apply_classifier_patch: proposal has no target "
            "(need vendor_exit_code or pattern_list+substring)"
        )
    if has_exit and has_pattern:
        raise ValueError(
            "apply_classifier_patch: proposal targets both vendor_exit_map and "
            "patterns — supply exactly one"
        )

    if has_exit:
        # bool is an int subclass — reject it explicitly (a poisoned True/False)
        if isinstance(vendor_exit_code, bool) or not isinstance(vendor_exit_code, int):
            raise ValueError(
                f"apply_classifier_patch: vendor_exit_code must be an int, "
                f"got {type(vendor_exit_code).__name__}"
            )
        # SEMANTIC: 0 = success (a failure class for it is nonsensical); a vendor
        # exit code is never negative on a real process.
        if vendor_exit_code <= 0:
            raise ValueError(
                f"apply_classifier_patch: vendor_exit_code must be > 0 "
                f"(0 = success; got {vendor_exit_code})"
            )
        # fix2/fix3 (L1 analog of the L2 _MIN_SUBSTRING_LEN floor): bound the
        # vendor_exit_code to the application-specific SOUND RANGE [3, 125] —
        # not an enumeration (fix2's `_GENERIC_EXIT_CODES` listed 130/137/143 but
        # missed other 128+N signal-death codes like 139/141/134, a structural
        # leak any enumeration is prone to repeat). {0,1,2}=generic, {126,127}=
        # shell, >=128=signal-death/reserved are all too broad to safely auto-
        # route — each would misroute EVERY unrelated future failure carrying
        # that code (e.g. rc=1, or rc=139 on any future segfault). classify()
        # consults the vmap BEFORE the L2 substrings and returns immediately, so
        # a poisoned vmap entry outweighs a poisoned substring. Propose a
        # specific stderr `substring` (L2) or escalate instead.
        if not (_VENDOR_EXIT_CODE_MIN <= vendor_exit_code <= _VENDOR_EXIT_CODE_MAX):
            raise ValueError(
                f"apply_classifier_patch: vendor_exit_code {vendor_exit_code} is "
                f"outside the application-specific range "
                f"[{_VENDOR_EXIT_CODE_MIN}, {_VENDOR_EXIT_CODE_MAX}] — "
                f"{{0,1,2}}=generic, {{126,127}}=shell, >=128=signal-death/reserved "
                f"are too broad to safely auto-route (each would misroute unrelated "
                f"future failures carrying that code). Propose a specific stderr "
                f"substring instead, or escalate."
            )
        # fix2: a vendor's own EXIT CODE cannot mean a WRAPPER-determined status —
        # restrict a vmap PROPOSAL to the vendor-exit-derivable classes (the PATTERN
        # path already enforces classification == PATTERN_LIST_CLASS[pattern_list],
        # so this check applies ONLY here).
        if classification not in VENDOR_EXIT_PROPOSAL_CLASSES:
            raise ValueError(
                f"apply_classifier_patch: classification {classification!r} is not "
                f"vendor-exit-derivable (a wrapper/status class cannot be inferred "
                f"from a raw vendor exit code); vmap proposals must be one of "
                f"{sorted(VENDOR_EXIT_PROPOSAL_CLASSES)}"
            )
    else:  # pattern branch
        if pattern_list not in PATTERN_LIST_NAMES:
            raise ValueError(
                f"apply_classifier_patch: invalid pattern_list {pattern_list!r} "
                f"(not a built-in pattern-list name)"
            )
        if not isinstance(substring, str):
            raise ValueError(
                f"apply_classifier_patch: substring must be a str, "
                f"got {type(substring).__name__}"
            )
        if not substring:
            raise ValueError("apply_classifier_patch: substring must be non-empty")
        if len(substring) > _MAX_SUBSTRING_LEN:
            raise ValueError(
                f"apply_classifier_patch: substring exceeds "
                f"{_MAX_SUBSTRING_LEN} chars ({len(substring)})"
            )
        # SEMANTIC: classify() lowercases the blob before substring matching
        # (see the L2 block). Store the substring lowercased so a mixed-case
        # proposal actually matches; normalize BEFORE the length floor.
        substring = substring.lower()
        # Over-broad guard: reject sub-floor length and all-whitespace/punct
        # (no alphanumeric signal → would smear across unrelated blobs).
        if len(substring) < _MIN_SUBSTRING_LEN:
            raise ValueError(
                f"apply_classifier_patch: substring too short "
                f"(< {_MIN_SUBSTRING_LEN} chars after normalize): {substring!r}"
            )
        if not any(ch.isalnum() for ch in substring):
            raise ValueError(
                f"apply_classifier_patch: substring has no alphanumeric signal "
                f"(whitespace/punctuation only): {substring!r}"
            )
        # SEMANTIC: classification must be the class this list actually yields —
        # appending to a list whose classify() class differs from the proposal's
        # `classification` would silently route to a DIFFERENT class than claimed.
        expected_class = PATTERN_LIST_CLASS[pattern_list]
        if classification != expected_class:
            raise ValueError(
                f"apply_classifier_patch: classification {classification!r} does "
                f"not match pattern_list {pattern_list!r} "
                f"(that list classifies as {expected_class!r})"
            )

    reason = proposal.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("apply_classifier_patch: reason must be a non-empty str")
    if len(reason) > _MAX_REASON_LEN:
        raise ValueError(
            f"apply_classifier_patch: reason exceeds {_MAX_REASON_LEN} chars "
            f"({len(reason)})"
        )

    ext_path = _classifier_extension_path()
    ext_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ext_path.parent / (ext_path.name + ".lock")

    with lock_path.open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)

            # Read-or-{} defensively. Order matters (Q6a fix):
            #   FileNotFoundError → {}   (first patch — no file yet, fine)
            #   ValueError (corrupt JSON) → {} + a stderr warning (reset)
            #   any OTHER OSError (EACCES/EMFILE/EISDIR — transient) → PROPAGATE.
            # A transient OSError must NOT be laundered into `data = {}`: that
            # would let the os.replace below OVERWRITE a healthy existing file
            # with a single-entry {}, destroying all prior rules. Propagating
            # aborts the patch and leaves the file intact.
            data: dict = {}
            try:
                raw = ext_path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data = parsed
            except FileNotFoundError:
                data = {}
            except ValueError:
                # Valid-file-but-corrupt-JSON → reset (mirrors _load_classifier_extension).
                sys.stderr.write(
                    f"[apply] {cli}: corrupt classifier extension JSON at "
                    f"{ext_path} — resetting to a fresh entry\n"
                )
                data = {}

            # Merge into the per-cli entry (create intermediate keys).
            entry = data.get(cli)
            if not isinstance(entry, dict):
                entry = {}

            # Bounded growth: count the target cli's total entries across
            # vendor_exit_map + all pattern lists. Reject only when adding a NEW
            # entry would exceed the cap (an idempotent re-append of an existing
            # code/substring is fine — it doesn't grow the file).
            def _cli_entry_count(e: dict) -> int:
                total = 0
                vm = e.get("vendor_exit_map")
                if isinstance(vm, dict):
                    total += len(vm)
                ps = e.get("patterns")
                if isinstance(ps, dict):
                    for _lst in ps.values():
                        if isinstance(_lst, list):
                            total += len(_lst)
                return total

            if has_exit:
                vmap = entry.get("vendor_exit_map")
                if not isinstance(vmap, dict):
                    vmap = {}
                is_new = str(vendor_exit_code) not in vmap
                if is_new and _cli_entry_count(entry) + 1 > _MAX_EXTENSION_ENTRIES:
                    raise ValueError(
                        f"apply_classifier_patch: per-cli entry cap reached for "
                        f"{cli!r} ({_MAX_EXTENSION_ENTRIES}); refusing unbounded growth"
                    )
                vmap[str(vendor_exit_code)] = classification
                entry["vendor_exit_map"] = vmap
            else:
                pats = entry.get("patterns")
                if not isinstance(pats, dict):
                    pats = {}
                lst = pats.get(pattern_list)
                if not isinstance(lst, list):
                    lst = []
                is_new = substring not in lst
                if is_new and _cli_entry_count(entry) + 1 > _MAX_EXTENSION_ENTRIES:
                    raise ValueError(
                        f"apply_classifier_patch: per-cli entry cap reached for "
                        f"{cli!r} ({_MAX_EXTENSION_ENTRIES}); refusing unbounded growth"
                    )
                if is_new:
                    lst.append(substring)
                pats[pattern_list] = lst
                entry["patterns"] = pats
            data[cli] = entry

            # Atomic write: temp file in the SAME dir, JSON-serialize (which is
            # itself a validation of the merged shape), flush+fsync, os.replace.
            serialized = json.dumps(data, ensure_ascii=False, indent=2)
            fd, tmp = tempfile.mkstemp(
                dir=str(ext_path.parent), prefix=ext_path.name + ".", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tf:
                    tf.write(serialized)
                    tf.flush()
                    os.fsync(tf.fileno())
                os.replace(tmp, ext_path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        finally:
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
            except Exception:
                pass

    log(f"[apply] {cli} {classification} — {reason}")
    return "applied"


# ─── Per-execution run-log (dispatch SKILL input) ─────────────────────────

def emit_run_log(
    cli: str,
    wrapper_cmd: list[str],
    vendor_cmd: list[str],
    prompt: str,
    result: RunResult,
) -> Optional[Path]:
    """Write per-execution run-log on failure only.

    Run-logs live at `_logs/<cli>/runs/<UTC-ts>-<pid>-<uuid8>.json`. Used by
    the dispatch SKILL to feed the failing call's full context to the repair
    sub-agent without inline-embedding (escape-safe + parallel-safe).

    On success (`exit_code == EXIT_OK`), returns None and writes nothing —
    repair agent dispatch isn't needed.

    Self-prunes after write: if dir exceeds `_RUN_LOG_MAX_FILES` or
    `_RUN_LOG_MAX_BYTES`, oldest files are unlinked until under threshold
    (best-effort, race-tolerant for parallel writes).
    """
    if result.exit_code == EXIT_OK:
        return None

    runs_dir = _LOG_DIR / cli / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pid = os.getpid()
    suffix = uuid.uuid4().hex[:8]
    fname = f"{ts}-{pid}-{suffix}.json"
    path = runs_dir / fname

    rec: dict = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cli": cli,
        "wrapper_cmd": wrapper_cmd,
        "vendor_cmd": vendor_cmd,
        "prompt_head": prompt[:200],
        "prompt_len": len(prompt),
        "exit_code": result.exit_code,
        "vendor_exit_code": result.vendor_exit_code,
        "classification": result.classification,
        "mode": result.mode,
        "elapsed_s": round(result.elapsed_s, 2),
        "stderr": result.stderr,
        "stdout": result.stdout,
        "final_answer": result.final_answer,
        "extraction_error": result.extraction_error,
        "validation_error": result.validation_error,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)

    _prune_run_logs(runs_dir, preserve=path)

    return path


def _prune_run_logs(runs_dir: Path, preserve: Optional[Path] = None) -> None:
    """Best-effort prune: enforce file count + total byte caps.

    Race-tolerant — parallel writes that all hit the cap may all attempt to
    prune; duplicate unlink attempts are absorbed by try/except. Worst case =
    slight over-prune. `preserve` (L6 twin→SoT port, 2026-07-05) is never
    deleted by this writer: a single large fresh run-log IS the current
    call's repair IPC and must survive even when it alone exceeds the byte
    cap (mtime order alone did not protect the only-file case).
    """
    preserve_resolved = preserve.resolve(strict=False) if preserve else None
    # Race-resilient listing: a concurrent unlink (or a dangling symlink) makes
    # p.stat() raise mid-sort. Materialize (path, mtime) per-file, skipping any
    # entry that vanishes — a single bad entry must NOT abort the whole prune
    # (the previous `sorted(..., key=p.stat)` form aborted on the first OSError).
    try:
        entries = list(runs_dir.glob("*.json")) + list(runs_dir.glob("*.prompt.tmp"))
    except Exception:
        return
    pairs: list[tuple[Path, float]] = []
    for p in entries:
        try:
            pairs.append((p, p.stat().st_mtime))
        except OSError:
            continue
    files = [p for p, _ in sorted(pairs, key=lambda x: x[1])]

    over_count = max(0, len(files) - _RUN_LOG_MAX_FILES)
    # Per-file accumulation (NOT sum(... if f.exists())): a concurrent unlink
    # between exists() and stat() raises OSError; a single try/except over the
    # whole sum would reset total_bytes to 0 and silently bypass byte-limit
    # pruning (under-prune). Skip vanished files individually instead.
    total_bytes = 0
    for f in files:
        try:
            total_bytes += f.stat().st_size
        except OSError:
            continue
    over_bytes = total_bytes - _RUN_LOG_MAX_BYTES

    for f in files:
        if over_count <= 0 and over_bytes <= 0:
            break
        if preserve_resolved is not None and f.resolve(strict=False) == preserve_resolved:
            continue
        try:
            sz = f.stat().st_size
            f.unlink()
            over_count -= 1
            over_bytes -= sz
        except Exception:
            pass


# Default age floor for the next-run stale-prune. Must comfortably exceed the
# longest window a run-log can be present-but-still-in-use: one failed dispatch
# plus the repair agent's 3-attempt ceiling (each attempt re-runs the wrapper in
# repair_mode — no server-cap retry, 600 s default --timeout — plus agent
# reasoning), so a worst case of ~3 × 600 s + overhead ≈ 40 min. The floor is set
# to 2 h (well above that) so a concurrent (live) sibling's freshly written
# run-log is NEVER inside the deletion window under 4-way parallel dispatch.
# repair_mode itself skips the prune, so an in-flight repair never races its own
# log; the cap-based `_prune_run_logs` (100 files / 20 MB) bounds disk regardless,
# so a generous floor costs nothing. Raised 3600→7200 after the merge-gate review
# flagged the 60-min margin as thin (owner decision 2026-06-12).
_STALE_IPC_AGE_FLOOR_S = 7200


def prune_stale_run_logs(cli: str, age_floor_s: int = _STALE_IPC_AGE_FLOOR_S) -> None:
    """Next-run cleanup of stale run-logs (owner contract: "clean up on the
    NEXT run", not at exit — a crashed call must leave its evidence).

    Removes `_logs/<cli>/runs/*.json` (run-logs AND their `.repair.json` pairs)
    whose mtime is older than `age_floor_s`. Called at the START of every normal
    (non-repair-mode) dispatch, so a SUBSEQUENT run cleans up the residue a
    prior run left on failure — including failure classes (terminal / server-cap
    / schema-rejected / fanout-partial / task-blocked) whose dispatch path never
    reaches the SKILL's Step 5d `rm`. The cap-based `_prune_run_logs` remains the
    over-cap failsafe; this is the time-based next-run sweep.

    The age floor is what makes this concurrency-safe under 4-way parallel
    dispatch: a live sibling's run-log is freshly written (< floor) so it is
    never deleted while still awaiting consumption. Best-effort + per-file
    tolerant — a vanishing entry never aborts the sweep.
    """
    runs_dir = _LOG_DIR / cli / "runs"
    cutoff = time.time() - max(0, age_floor_s)
    try:
        entries = list(runs_dir.glob("*.json")) + list(runs_dir.glob("*.prompt.tmp"))
    except Exception:
        return
    for p in entries:
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            continue


def prune_stale_tmp_dirs(
    prefix: str,
    age_floor_s: int = _STALE_IPC_AGE_FLOOR_S,
    base: Optional[str] = None,
) -> None:
    """Next-run cleanup of leaked `tempfile.mkdtemp(prefix=...)` report dirs.

    The codex `--task` fan-out path auto-creates `<TMPDIR>/codex_report_*` dirs
    (synthesis + per-agent raw reports) for leader inspection and never unlinks
    them — a true per-fan-out leak. This sweeps prior ones older than
    `age_floor_s` at the START of a dispatch, mirroring `prune_stale_run_logs`:
    the current run's dir is freshly created (< floor) so it is preserved for
    the leader to read. Best-effort, per-dir tolerant.

    `base` defaults to the system temp dir (`tempfile.gettempdir()`).
    """
    base_dir = Path(base) if base else Path(tempfile.gettempdir())
    cutoff = time.time() - max(0, age_floor_s)
    try:
        entries = list(base_dir.glob(prefix + "*"))
    except Exception:
        return
    for d in entries:
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue


# ─── Debug log (human-readable per-call markdown table) ───────────────────
# Opt-in via wrapper's `--debug` flag. Append-only markdown table at
# `_debug/<UTC-YYYY-MM-DD>/<cli>.md`. Header is written exactly once per
# file (race-free under flock). Cell content is truncated to 200 chars and
# escaped (`|` → `\|`, newlines → `<br>`) for markdown table safety.
# Audit.jsonl remains the SoT for full data; debug.md is a sample-grade
# human aid for live triage (cat / glow / bat).
_DEBUG_CELL_LIMIT = 200


def _debug_cell(s: str, n: int = _DEBUG_CELL_LIMIT) -> str:
    s = s or ""
    truncated = len(s) > n
    s = s[:n].replace("\r", "").replace("|", "\\|").replace("\n", "<br>")
    return s + ("…" if truncated else "")


def debug_log(cli: str, prompt: str, result: RunResult) -> None:
    """Append one human-readable markdown row per call. Opt-in only.

    Path: `_debug/<UTC-YYYY-MM-DD>/<cli>.md`. Header (table head) written
    exactly once on first append per file, race-free under fcntl lock.
    """
    if _audit_redact_enabled():
        # Redact-mode custody (panel custody-lens, 2026-07-11): the debug dump
        # stores the FULL prompt + streams in a durable-ish per-day file. A
        # hardened install must not get a prompt-custody bypass via --debug.
        log("debug dump skipped: redact mode (prompt/stream custody)")
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = _DEBUG_DIR / today
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"{cli}.md"

    with path.open("a", encoding="utf-8") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            # Race-free header — under lock, fstat().st_size==0 means new
            # file. f.tell() in append mode is undefined per Python docs;
            # fstat() reads the actual on-disk size while we hold flock.
            # 2026-05-03 fault test exposed: parallel writers all saw
            # tell()==0 and emitted duplicate headers.
            if os.fstat(f.fileno()).st_size == 0:
                f.write(f"# {cli} debug log — {today} (UTC)\n\n")
                f.write("| time | request | exitcode | stderr | stdout |\n")
                f.write("|---|---|---|---|---|\n")
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            f.write(
                f"| {ts} | {_debug_cell(prompt)} | {result.exit_code} "
                f"| {_debug_cell(result.stderr)} "
                f"| {_debug_cell(result.stdout)} |\n"
            )
            # Flush the buffered header/row BEFORE releasing the lock. The
            # header check (`fstat().st_size == 0`) reads the kernel inode
            # size, but Python block-buffers the writes until close — which the
            # `with` block performs AFTER this `finally` releases the lock.
            # Without this flush a concurrent writer can acquire the lock in the
            # release→close window, still observe size 0, and emit a duplicate
            # header (a latent TOCTOU that surfaces only under heavy scheduling
            # load). flush() issues the write() syscall, so the new size is
            # immediately visible to any subsequent fstat; no fsync needed —
            # debug.md is a sample-grade aid (audit.jsonl is the durable SoT).
            f.flush()
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass
