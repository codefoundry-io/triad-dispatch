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
        "unknown": EXIT_CLI_FAIL,
    }.get(cls, EXIT_CLI_FAIL)


# ─── Pattern lists (seed — living value, Step D maintenance updates) ──────
# Lowercase substring match. Terminal-first ordering when classifying.

SERVER_CAPACITY_PATTERNS: tuple[str, ...] = (
    "model_capacity_exhausted",
    "resource_exhausted",
    "ratelimitexceeded",
    "model overloaded",
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

# Stderr 의 semantic 분류 (도구 미설치 / vendor warning / 정상 동작 등) 은
# leader (Bash tool 통해 stderr mirror 받는 AI) 의 책임. wrapper 는 raw stderr
# 만 audit 에 박고, leader 가 직접 판단 + 사용자 alert. dispatch SKILL (Step C)
# 의 description 에 stderr 해석 가이드 명시 예정.


# ─── Vendor exit code maps (EMPIRICAL ONLY) ───────────────────────────────
# 실측 검증된 exit code 만 박음. 실측 안 된 code = "unknown" → 수리공 dispatch
# (수리공이 WebSearch + 분석 + python source 즉시 patch 로 entry 추가).
# Tier 1 docs (Gemini PR #13728: 41/42/52/53/130, Codex mintlify: 2/3/4/130)
# 는 우리 환경에서 trigger 시켜본 적 없으므로 박지 않음 — Step A3 검증 후 추가.

GEMINI_VENDOR_EXIT_MAP: dict[int, str] = {
    0: "ok",
    # 41/42/52/53/130 = docs 만 (PR #13728 / headless docs) — 실측 후 추가.
}

CODEX_VENDOR_EXIT_MAP: dict[int, str] = {
    0: "ok",
    # 130 = Issue #4721 미해결 가능 — 실측 후 추가.
    # 2/3/4 = mintlify 출처만, 공식 미확정 — 실측 후 추가.
}

CLAUDE_VENDOR_EXIT_MAP: dict[int, str] = {
    0: "ok",
    # claude `--print` 의 본 추가 vendor exit code 는 실측 후 추가.
    # `is_error: true` 안 박혀있는 ENV/AUTH fail 은 rc=0 (envelope-only signal).
    # extract_claude_answer 가 본 envelope 분석 → extraction-error 전파.
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


# ─── Audit oversize alert policy ──────────────────────────────────────────
# 매 audit() append 후 size check. 임계치 초과 시 1줄 stderr alert (deterministic).
# Auto-archive / rotation 미적용 — 10 MB 면 이미 통계 분석 충분 분량,
# 사용자가 maintenance SKILL (jq cross-tab) 호출 후 직접 rm 으로 처리.
AUDIT_OVERSIZE_ALERT_BYTES = 10 * 1024 * 1024  # 10 MB


# ─── Run-log policy (per-execution artifact, dispatch-SKILL input) ────────
# audit.jsonl 와 별개로 _logs/<cli>/runs/<UTC-ts>-<pid>-<uuid8>.json 에 호출당
# 1 파일. 실패 호출만 (rc != 0) — 성공은 dispatch agent 안 부르므로 불필요.
# Dispatch SKILL 이 path 만 prompt 에 박고 agent 가 Read tool 로 가져감 →
# 대용량 vendor stdout / 한글 / 특수문자 escape 격리.
# 2-layer cleanup:
#   Primary  = dispatch SKILL 이 agent 호출 종료 직후 rm
#   Failsafe = 본 함수가 매 write 후 dir cap 초과 시 oldest 부터 unlink
_RUN_LOG_MAX_FILES = 100
_RUN_LOG_MAX_BYTES = 20 * 1024 * 1024  # 20 MB total cap


@dataclass
class RunResult:
    exit_code: int                  # wrapper 정렬 (0/1/2/3/4/64/65/66)
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
    # Vendor raw exit code — 수리공의 WebSearch 검색 키 (실측 안 된 code 시).
    vendor_exit_code: int = -1


# ─── Helpers ──────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)


def require_binary(name: str) -> str:
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


def classify(
    cli: str,
    stderr: str,
    stdout: str,
    exit_code: int,
    vendor_exit_code: Optional[int] = None,
) -> str:
    """5분류 + ok. Layer order:
      L1 — vendor exit code map (실측 검증된 raw code 만)
      L2 — substring fallback (5분류 pattern lists)
      L3 — "unknown" (수리공 dispatch 신호)

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
    # L1 — vendor exit code map (실측 only). Use vendor_exit_code when
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
    if raw in vmap and vmap[raw] != "ok":
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
    # L3 — 수리공 dispatch 신호
    return "unknown"


# ─── Pydantic helpers (NEW) ───────────────────────────────────────────────

def load_pydantic_class(spec: str):
    """Parse 'module.path:ClassName' or 'module.path.ClassName' →
    pydantic BaseModel subclass.

    Raises ImportError / AttributeError / TypeError on failure.
    """
    if not PYDANTIC_OK:
        raise RuntimeError("pydantic not installed — `pip3 install --user pydantic`")
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
    for each subagent that reached a TERMINAL state (completed or failed),
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
            if status in ("pending_init", "in_progress", None):
                continue  # not yet terminal — a later event may supersede it
            by_thread[tid] = {"thread_id": tid, "message": st.get("message") or ""}
            final_status[tid] = status  # last terminal status wins (completed OR failed)
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

    # stdout empty — look for trailing JSON in stderr
    last_brace = stderr.rfind("{")
    if last_brace != -1:
        try:
            obj = json.loads(stderr[last_brace:].strip())
            err = obj.get("error", {})
            if isinstance(err, dict):
                return "", err.get("message", str(err))
            return "", str(err)
        except Exception:
            pass
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

    Markdown fence-strip safety: `--print` 안 fence X (envelope = raw JSON)
    이지만 `--agent` mode 안 fence wrap 가능 (haiku 패턴 — singleshot.md
    Empirical observations 박힘). 본 helper 가 안전 fence-strip.
    """
    s = (stdout or "").strip()
    if not s:
        # stdout empty — claude 의 본 envelope 항상 stdout (rc=0 케이스).
        # stderr 은 progress / warning 만. envelope 부재 = abnormal.
        return "", "empty stdout — claude envelope missing"

    # Fence-strip safety (--agent mode 안 markdown wrap 가능).
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

    is_error = obj.get("is_error", False)
    result = obj.get("result", "")
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False)

    if is_error:
        # vendor returned envelope with is_error=true. result field 안
        # 본 자세한 message 박힘 (e.g. "Not logged in · Please run /login",
        # API error description 등). repair-agent 가 본 message 으로 분류.
        api_status = obj.get("api_error_status")
        prefix = f"is_error=true (api_error_status={api_status})"
        if result:
            return "", f"{prefix}: {result}"
        return "", prefix

    # permission_denials 안 entry 박힘 = tool block 발견 (objective signal —
    # claude worker 의 본 본질, leader 의 본 frame X). caller (SKILL) 가
    # 본 신호로 추가 분석. extraction-error 으로 surface 박지 X (정상 답 안
    # tool block 표시) — answer 우선 return, denials 별 audit 박을 방법 후속.
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


def extract_antigravity_answer(
    scrubbed: str, killed: bool, expected_sentinel: str
) -> Tuple[Optional[str], Optional[str]]:
    """Find the exact per-call sentinel in already-scrubbed text. Present ->
    (answer_without_sentinel, None). Absent -> (None, 'no-sentinel').

    Uses the LAST marker occurrence (rfind) so an early echoed marker — e.g.
    the model quoting the closing instruction back at the top — does not
    truncate a real answer that ends at the genuine terminal marker.
    """
    marker = f"<<<{expected_sentinel}>>>"
    idx = scrubbed.rfind(marker)
    if idx == -1:
        return None, "no-sentinel"
    return scrubbed[:idx].rstrip(), None


# ─── Subprocess core ──────────────────────────────────────────────────────

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

    popen_kwargs: dict = dict(
        cwd=cwd,
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

    # 1줄 deterministic 요약 (leader / 사용자 즉시 가시화). stderr 의 semantic
    # 분류 (도구 미설치 / vendor warning) 은 leader 가 raw stderr mirror 보고 판단.
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
            if cls == "ok":
                break
            if cls in ("cli-subscription-cap", "token-limit", "oauth-env",
                       "fanout-spawn-error", "config-conflict"):
                r.exit_code = EXIT_TERMINAL
                # Re-emit summary so the [wrapper] line's exit token matches
                # the wrapper's actual final rc (65). Without this the line
                # carries _run_once's stale rc=1 which contradicts the
                # wrapper's $? (2026-05-03 later-3 fault test exposed).
                log(
                    f"[wrapper] {cli} {cls} "
                    f"exit={r.exit_code} vendor={r.vendor_exit_code} "
                    f"elapsed={r.elapsed_s:.1f}s"
                )
                return r
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
            result.exit_code = EXIT_SCHEMA_FAIL
            return result

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

_LOG_DIR = Path(__file__).resolve().parent / "_logs"
_DEBUG_DIR = Path(__file__).resolve().parent / "_debug"


def audit(cli: str, cmd: list[str], prompt: str, result: RunResult) -> None:
    """Append one JSONL record per invocation to _logs/<cli>/audit.jsonl.

    flock(LOCK_EX) for cross-process append safety. `final_answer_head` cap
    at 500 chars; full answer flows to caller via `result.final_answer`.
    """
    log_dir = _LOG_DIR / cli
    log_dir.mkdir(parents=True, exist_ok=True)
    ok = result.exit_code == EXIT_OK
    rec: dict = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cli": cli,
        "cmd": cmd,
        "prompt_head": prompt[:200],
        "prompt_len": len(prompt),
        "vendor_exit_code": result.vendor_exit_code,
        "exit_code": result.exit_code,
        "elapsed_s": round(result.elapsed_s, 2),
        "classification": result.classification,
        "mode": result.mode,
        "repair_attempt": result.repair_attempt,
        "schema_repair_attempt": result.schema_repair_attempt,
        "stderr": result.stderr,
        "final_answer_head": (result.final_answer or "")[:500],
        "final_answer_len": len(result.final_answer or ""),
        "validated": result.validated,
        "extraction_error": result.extraction_error,
        "validation_error": result.validation_error,
    }
    if ok:
        rec["stdout_head"] = result.stdout[:500]
        rec["stdout_len"] = len(result.stdout)
    else:
        rec["stdout"] = result.stdout
    path = log_dir / "audit.jsonl"
    with path.open("a", encoding="utf-8") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            # Flush the record under the lock so the write() that appends it
            # happens while the lock is held — making the flock the thing that
            # serializes the append, not an implicit reliance on O_APPEND. A
            # small record (< the ~8 KiB buffer) would otherwise stay buffered
            # past LOCK_UN and its write() would only fire at close (outside
            # the lock; flush makes the bytes kernel-visible, not durable);
            # large records already flush mid-write under the lock. Measured:
            # the unflushed path does NOT corrupt the JSONL (each record is one
            # atomic O_APPEND write), so this is a lock-coverage/uniformity
            # hardening (mirrors debug_log), not a fix for a present bug.
            f.flush()
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except Exception:
                pass

    # Oversize alert (deterministic, no archive — user runs maintenance SKILL).
    try:
        size = path.stat().st_size
        if size > AUDIT_OVERSIZE_ALERT_BYTES:
            mb = size / (1024 * 1024)
            log(
                f"WARN: {cli}/audit.jsonl = {mb:.1f} MB "
                f"(> {AUDIT_OVERSIZE_ALERT_BYTES // (1024*1024)} MB) — "
                f"maintenance SKILL 호출 권장 (jq cross-tab + rm)"
            )
    except Exception:
        pass


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

    _prune_run_logs(runs_dir)

    return path


def _prune_run_logs(runs_dir: Path) -> None:
    """Best-effort prune: enforce file count + total byte caps.

    Race-tolerant — parallel writes that all hit the cap may all attempt to
    prune; duplicate unlink attempts are absorbed by try/except. Worst case =
    slight over-prune, never data loss for the latest writer (its own file
    is freshly written and last by mtime).
    """
    # Race-resilient listing: a concurrent unlink (or a dangling symlink) makes
    # p.stat() raise mid-sort. Materialize (path, mtime) per-file, skipping any
    # entry that vanishes — a single bad entry must NOT abort the whole prune
    # (the previous `sorted(..., key=p.stat)` form aborted on the first OSError).
    try:
        entries = list(runs_dir.glob("*.json"))
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
    """Next-run cleanup of stale run-logs (the owner's "다음 run 에 클린업").

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
        entries = list(runs_dir.glob("*.json"))
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
