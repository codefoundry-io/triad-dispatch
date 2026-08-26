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

import enum
import fcntl
import importlib
import json
import math
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

# ─── Non-repairable schema-validation contract ─────────────────────────────
# A `--pydantic module:Class` schema marks a validator arm NON-REPAIRABLE by
# leading its ValueError message with this token. The schema-repair path
# (Layer 4 below, and `antigravity_wrapper.py`'s own copy of the same loop)
# then SKIPS the one-shot repair re-dispatch and promotes straight to
# schema-fail (66).
#
# Why the engine needs an opt-out at all (cross-family review r1-claude-1,
# 2026-08-11): the repair re-dispatch replays the validation error VERBATIM
# back to the model. For most violations that is harmless — the model fixes a
# missing field. But for an arm that encodes a CONTENT contradiction (the
# review-verdict schema's "SAFE TO MERGE must not carry a blocking finding"),
# the cheapest way to satisfy the replayed error is to weaken the CONTENT —
# downgrade the blocking finding and keep the SAFE verdict. The caller only
# ever sees the repaired object, so the automated retry silently launders the
# very signal the schema exists to protect.
#
# Deliberately a plain SUBSTRING contract, not an exception subclass or an
# import of any schema module: `_common.py` validates against whatever class
# `--pydantic` names and must stay schema-agnostic.
NONREPAIRABLE_MARKER = "[NONREPAIRABLE]"


class NonrepairableTrigger(enum.IntFlag):
    """WHICH of the two independent refusal reasons fired (r8 claude must-fix).

    Both bits are computed on every validation failure and were then OR'd into
    a single bool, so a CONTENT-triggered refusal was indistinguishable from —
    and, in the agy driver's refusal label, actively MISREPORTED as — the
    marked ARM. That distinction is load-bearing downstream: the review skill's
    verdict-binding obligation branches on it, and telling a leader "the arm
    fired" for a content-only refusal orders it to RAISE a verdict that may
    already be non-SAFE, manufacturing the mirror image of the laundering this
    machinery exists to stop.

      ARM      the live pydantic error carries `NONREPAIRABLE_MARKER` in a
               validator's own message (`_validation_error_nonrepairable`).
      CONTENT  the failed payload's own content is blocking per the schema's
               duck-typed probe (`_content_nonrepairable`) — this fires where
               NO arm ran at all (a co-occurring field error suppresses
               `mode="after"` validators; an unparseable envelope never reaches
               one).

    A flag rather than two bools so the two producers (the shared engine, and
    `antigravity_wrapper`'s second copy of the loop, which ORs in a probe of
    the RAW channel) compose with `|` instead of re-deriving the pairing.
    """

    NONE = 0
    ARM = 1
    CONTENT = 2


# The ONE grep-stable token every consumer binds to. Rendered into the
# wrapper's own TIMESTAMPED stderr log line, so a consumer anchors on the
# wrapper's line and never on vendor-mirrored bytes (same discipline the
# read-audit digest gate follows). The `[NONREPAIRABLE` prefix is deliberately
# preserved from the pre-r8 wording so existing greps keep matching.
_TRIGGER_LABELS = {
    NonrepairableTrigger.NONE: "",
    NonrepairableTrigger.ARM: "arm",
    NonrepairableTrigger.CONTENT: "content",
    NonrepairableTrigger.ARM | NonrepairableTrigger.CONTENT: "arm+content",
}


def nonrepairable_trigger_label(trigger: NonrepairableTrigger) -> str:
    """`"arm"` / `"content"` / `"arm+content"`, or `""` when nothing fired."""
    return _TRIGGER_LABELS.get(NonrepairableTrigger(trigger), "")


def nonrepairable_log_marker(trigger: NonrepairableTrigger) -> str:
    """`[NONREPAIRABLE trigger=<label>]` — the exact token a consumer greps.

    Kept a single function so the two repair loops cannot spell it differently:
    a leader that reads `trigger=` off the WRONG loop's line would branch on a
    trigger that never fired.
    """
    return f"[NONREPAIRABLE trigger={nonrepairable_trigger_label(trigger)}]"


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


# ── agy stream-json transport helpers (2026-07-31 migration) ──────────────
# agy >= 1.1.8 print mode emits typed NDJSON (`init` / `step_update` /
# terminal `result`). These two pure helpers are the ONLY place that couples
# to the vendor event schema — consumers (driver, review SKILL) see the
# stable digest shape, so a vendor schema drift is fixed here + t13 only.

_AGY_READ_TOOLS = {"view_file", "list_dir", "grep_search", "find_by_name",
                   "code_search", "codebase_search", "skill_search"}
_AGY_WRITE_TOOLS = {"write_to_file", "replace_file_content",
                    "multi_replace_file_content", "sed_file", "notebook_edit"}
_AGY_WEB_TOOLS = {"read_url_content", "search_web", "open_browser_url"}
_AGY_DIGEST_LIST_CAP = 40
_AGY_DIGEST_VALUE_CAP = 200
# Every vendor-controlled STRING that lands in the digest is capped. r1/R6:
# parameter KEYS and tool NAMES were uncapped (only VALUES were), so a vendor
# could still balloon the leader-visible read-audit line through either.
_AGY_DIGEST_KEY_CAP = 64
_AGY_DIGEST_USAGE_KEY_CAP = 12
# Per-attempt breakdown kept in the merged aggregate (r1/R4). The union lists
# carry the evidence; this list is the bounded per-attempt census.
_AGY_DIGEST_ATTEMPT_CAP = 10
# Structural failure strings handed to classify() (r1/R2). Bounded count.
_AGY_SIGNAL_CAP = 12
# Max signal strings ONE event may contribute (r3/G2). A single malformed
# `error_message` step could otherwise emit up to 16 (4 text keys on the step
# itself + 4 on each of its 3 sub-containers) and monopolise its bucket,
# crowding out every later event's signal.
_AGY_SIGNAL_EVENT_CAP = 2
_AGY_ERROR_TEXT_KEYS = ("message", "text", "detail", "description")
# Tool CLASS recorded on every read_attempts entry (r2/C5). read_attempts
# collects EVERY unsuccessful tool, but the review SKILL's VOID diagnostic
# reports a match as "the leg failed to READ the packet" — a failed write or
# command naming the packet produced a false diagnostic. The class is folded
# HERE (one source of truth) so the SKILL filters on `.class == "read"`
# instead of duplicating these tool-name sets into its jq.
_AGY_TOOL_CLASSES = (("read", _AGY_READ_TOOLS), ("write", _AGY_WRITE_TOOLS),
                     ("web", _AGY_WEB_TOOLS))
# The digest's capped lists — each merged pairwise with its _omitted counter.
_AGY_DIGEST_LISTS = ("files_read", "writes", "commands", "denied", "web",
                     "read_attempts")


def parse_agy_stream(text: str) -> tuple:
    """Parse agy `--output-format stream-json` NDJSON into (events, result).

    Tolerant by design: non-JSON lines, truncated trailing lines (killed
    runs), and non-dict payloads are skipped — a partial stream still yields
    its parsed prefix. `result` is the payload dict of the LAST
    `{"event":"result"}` line, or None.

    Framing is `"\\n"` ONLY (r1/R7). `str.splitlines()` additionally breaks on
    U+2028 / U+2029 / U+0085, and V8 (agy's runtime) does NOT escape those in
    JSON string output — so one legal NDJSON line carrying any of them would
    be cut in half, both halves would fail to parse, and a COMPLETE answer
    would vanish silently. A trailing `\\r` is absorbed by the `.strip()`.
    """
    events: list = []
    result = None
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        events.append(obj)
        if obj.get("event") == "result" and isinstance(obj.get("result"), dict):
            result = obj["result"]
    return events, result


def _agy_params_hint(params) -> dict:
    """Bounded, schema-agnostic copy of a tool_info.parameters dict: scalar
    values only, keys AND values truncated, at most 6 keys — the digest must
    never balloon on a huge parameter (e.g. an inline file body) nor on a huge
    parameter NAME (r1/R6)."""
    out = {}
    if not isinstance(params, dict):
        return out
    for k, v in list(params.items())[:6]:
        if isinstance(v, (str, int, float, bool)):
            out[str(k)[:_AGY_DIGEST_KEY_CAP]] = str(v)[:_AGY_DIGEST_VALUE_CAP]
    return out


def _agy_finite(v) -> bool:
    """False for a NON-FINITE float — NaN / Infinity / -Infinity (r2/N4).

    `json.loads` ACCEPTS those literals, so a vendor result can carry them, and
    `json.dumps` writes them back BARE (`NaN`), which is not valid JSON per
    RFC 8259. Empirically (jq 1.7.1) jq does not reject such a line: it
    silently COERCES (NaN -> null, Infinity -> 1.797e308), so the damage is a
    silently corrupted leader-visible audit value plus a hard parse failure on
    any strict consumer. Dropping the value at the digest boundary is the fix;
    `allow_nan=False` on the dumps is NOT (it raises inside main(), costing the
    caller its summary line, audit row and run-log).
    """
    return not isinstance(v, float) or math.isfinite(v)


def _agy_scalar(v, cap: int = _AGY_DIGEST_VALUE_CAP):
    """Bounded, JSON-SAFE copy of a vendor-controlled scalar: strings capped,
    non-finite numerics dropped, anything else -> None."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v[:cap]
    if isinstance(v, (int, float)):
        return v if _agy_finite(v) else None
    return None


def _agy_usage_hint(usage) -> dict:
    """Bounded copy of the terminal result's `usage` object (r1/R6). The whole
    object used to ride verbatim into a leader-visible line; it is
    vendor-controlled, so cap the key count, the key length and any string
    value, and keep scalars only. Non-finite numerics are dropped (r2/N4)."""
    out: dict = {}
    if not isinstance(usage, dict):
        return out
    for k, v in list(usage.items())[:_AGY_DIGEST_USAGE_KEY_CAP]:
        key = str(k)[:_AGY_DIGEST_KEY_CAP]
        if isinstance(v, (bool, int, float)):
            if _agy_finite(v):
                out[key] = v
        elif isinstance(v, str):
            out[key] = v[:_AGY_DIGEST_VALUE_CAP]
    return out


def _agy_tool_name(info, su) -> str:
    """Vendor-controlled tool name — type-guarded and capped (r1/R3 + R6)."""
    for cand in (info.get("name") if isinstance(info, dict) else None,
                 su.get("tool_name") if isinstance(su, dict) else None):
        if isinstance(cand, str) and cand:
            return cand[:_AGY_DIGEST_KEY_CAP]
    return "?"


def _agy_tool_class(name: str) -> str:
    """Coarse class of an agy tool name — `read` / `write` / `command` /
    `web` / `other` (r2/C5). Recorded on every read_attempts entry so a
    consumer can tell an attempted PACKET READ from a blocked write or
    command that merely named the same path."""
    for label, names in _AGY_TOOL_CLASSES:
        if name in names:
            return label
    return "command" if name == "run_command" else "other"


def digest_agy_stream(events: list, result=None) -> dict:
    """Fold a parsed event list into a bounded, deterministic read-audit
    digest. REPORT-ONLY: no policy, no judgment — the caller (leader /
    review SKILL) decides what a missing packet-read means. Each tool call
    is counted once, on its terminal DONE/ERROR update (ACTIVE skipped).

    OUTCOME FIDELITY (r1/R1): `files_read` / `writes` / `commands` / `web`
    record only tool calls that actually SUCCEEDED — terminal state DONE with
    no `tool_info.error`. The review SKILL's mechanical gate reads a
    `files_read` hit as PROOF the reviewer received the packet bytes, and its
    own text declares a `denied` entry non-voiding, so appending errored /
    permission-denied attempts to that same list made the gate FAIL-OPEN.
    Nothing is hidden: every non-successful attempt is preserved in
    `read_attempts` as `{tool, params, outcome, class}` (outcome = `denied` |
    `error` | the vendor's own terminal state, lowercased; class = `read` |
    `write` | `command` | `web` | `other`, r2/C5 — read_attempts collects
    EVERY unsuccessful tool, so a consumer reporting "the leg failed to READ
    the packet" must filter on the class, not on the path alone).

    Every nested vendor field is type-guarded (r1/R3): a non-dict
    `tool_info` / `parameters` / `error`, or a non-string `name` / `state`,
    folds to a bounded default instead of raising — a traceback here would
    cost the caller its classification, summary line, audit row and run-log.
    """
    files_read: list = []
    writes: list = []
    commands: list = []
    denied: list = []
    web: list = []
    read_attempts: list = []
    tool_steps = 0
    error_steps = 0
    for ev in events or []:
        su = ev.get("step_update") if isinstance(ev, dict) else None
        if not isinstance(su, dict):
            continue
        stype = su.get("step_type")
        if stype == "error_message":
            error_steps += 1
            continue
        state = su.get("state")
        state_s = state if isinstance(state, str) else ""
        if stype != "tool" or state_s == "ACTIVE":
            continue
        info = su.get("tool_info")
        if not isinstance(info, dict):
            info = {}
        name = _agy_tool_name(info, su)
        params = info.get("parameters")
        hint = _agy_params_hint(params)
        tool_steps += 1
        raw_err = info.get("error")
        err_present = bool(raw_err)
        err = raw_err if isinstance(raw_err, dict) else {}
        if state_s == "ERROR":
            error_steps += 1
        err_msg = err.get("message")
        is_denied = "denied permission" in (
            err_msg if isinstance(err_msg, str) else "").lower()
        if is_denied:
            denied.append({"tool": name, "params": hint})
        if state_s == "DONE" and not err_present:
            if name in _AGY_READ_TOOLS:
                files_read.append({"tool": name, "params": hint})
            elif name in _AGY_WRITE_TOOLS:
                writes.append({"tool": name, "params": hint})
            elif name == "run_command":
                cmdline = params.get("CommandLine", "") if isinstance(params, dict) else ""
                commands.append(str(cmdline)[:_AGY_DIGEST_VALUE_CAP])
            elif name in _AGY_WEB_TOOLS:
                web.append({"tool": name, "params": hint})
            continue
        if is_denied:
            outcome = "denied"
        elif err_present or state_s == "ERROR":
            outcome = "error"
        else:
            outcome = (state_s.lower() or "unknown")[:_AGY_DIGEST_KEY_CAP]
        read_attempts.append({"tool": name, "params": hint, "outcome": outcome,
                              "class": _agy_tool_class(name)})
    digest = {
        "event_count": len(events or []),
        "tool_steps": tool_steps,
        "error_steps": error_steps,
    }
    # EVERY capped list carries its own omitted counter (r1/R6 — only
    # files_read did, so a truncated writes/commands/denied/web list looked
    # complete to the leader).
    for key, values in (("files_read", files_read), ("writes", writes),
                        ("commands", commands), ("denied", denied),
                        ("web", web), ("read_attempts", read_attempts)):
        digest[key] = values[:_AGY_DIGEST_LIST_CAP]
        digest[key + "_omitted"] = max(0, len(values) - _AGY_DIGEST_LIST_CAP)
    if isinstance(result, dict):
        # r2/C3: `status` was the ONE uncapped vendor string left in the
        # digest, and it is replicated into the merged terminal fields AND
        # into every per-attempt census row — three copies of an unbounded
        # vendor value on a leader-visible line. Capped like `outcome`.
        digest["status"] = _agy_scalar(result.get("status"),
                                       _AGY_DIGEST_KEY_CAP)
        dur = result.get("duration_seconds")
        digest["duration_seconds"] = (dur if isinstance(dur, (int, float))
                                      and _agy_finite(dur) else None)
        if isinstance(result.get("usage"), dict):
            digest["usage"] = _agy_usage_hint(result["usage"])
    return digest


def _agy_entry_key(v) -> str:
    """Order-stable identity for a digest list entry, for dedupe (r2/C4).
    Entries are either bounded dicts (`{tool, params, ...}`) or bounded
    strings (commands), so a canonical JSON rendering is a total, cheap key;
    anything unexpected falls back to `repr` rather than raising."""
    try:
        return json.dumps(v, sort_keys=True, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        return repr(v)


def merge_agy_digests(digests) -> Optional[dict]:
    """Aggregate per-ATTEMPT digests into ONE bounded read-audit record (r1/R4).

    The driver retries (soft-deny escalation, server-capacity backoff, schema
    repair) and each attempt produces its own digest. Emitting only the LAST
    one let a short-circuiting retry CONCEAL the earlier attempt's evidence —
    a leg that demonstrably read the review packet on attempt 1 reported zero
    reads, which the review SKILL's mechanical gate treats as a VOID leg. The
    aggregate unions every attempt's lists (no evidence lost, DEDUPED in
    first-seen order per r2/C4 so a path re-read on every retry cannot consume
    the cap), carries a bounded per-attempt census under `attempts` (which
    keeps each attempt's own pre-dedupe totals), and takes the terminal fields
    (status / duration / usage) from the LAST attempt — the one whose
    classification the caller returns. Returns None for an empty input (no
    completed vendor call ⇒ no digest, as before).
    """
    items = [d for d in (digests or []) if isinstance(d, dict)]
    if not items:
        return None
    merged: dict = {
        "event_count": sum(int(d.get("event_count") or 0) for d in items),
        "tool_steps": sum(int(d.get("tool_steps") or 0) for d in items),
        "error_steps": sum(int(d.get("error_steps") or 0) for d in items),
    }
    for key in _AGY_DIGEST_LISTS:
        union: list = []
        seen: set = set()
        omitted = 0
        for d in items:
            vals = d.get(key)
            if isinstance(vals, list):
                # r2/C4: DEDUPE, first-seen order. A plain extend let the same
                # path/tool re-read on every retry consume the 40-entry cap and
                # push a DISTINCT later entry (e.g. a packet read that only
                # happened on the final attempt) out of the emitted union —
                # exactly the shape that VOIDs a leg which did read the packet.
                # A dropped duplicate is not hidden evidence, so it does NOT
                # count toward `_omitted`; the per-attempt census below still
                # carries each attempt's own totals.
                for v in vals:
                    k = _agy_entry_key(v)
                    if k in seen:
                        continue
                    seen.add(k)
                    union.append(v)
            omitted += int(d.get(key + "_omitted") or 0)
        omitted += max(0, len(union) - _AGY_DIGEST_LIST_CAP)
        merged[key] = union[:_AGY_DIGEST_LIST_CAP]
        merged[key + "_omitted"] = omitted
    last = items[-1]
    for key in ("status", "duration_seconds", "usage"):
        if key in last:
            merged[key] = last[key]
    attempts = []
    for i, d in enumerate(items[:_AGY_DIGEST_ATTEMPT_CAP]):
        entry: dict = {"attempt": i + 1, "status": d.get("status"),
                       "tool_steps": d.get("tool_steps", 0),
                       "error_steps": d.get("error_steps", 0)}
        for key in _AGY_DIGEST_LISTS:
            vals = d.get(key)
            entry[key] = (len(vals) if isinstance(vals, list) else 0) \
                + int(d.get(key + "_omitted") or 0)
        attempts.append(entry)
    merged["attempts"] = attempts
    merged["attempts_omitted"] = max(0, len(items) - _AGY_DIGEST_ATTEMPT_CAP)
    return merged


def _agy_first_line(v: str) -> str:
    """First NON-EMPTY, stripped line of a typed error message (r3/G5).

    r2/N2 took `split("\\n", 1)[0]` blindly, which DROPS a message whose first
    line is empty: `"\\nUser denied permission to run command:\\n<arg>"`
    contributed nothing at all, losing the structural head the pre-N2 code
    kept. Scanning for the first non-empty line keeps the head and still leaves
    the model-authored echo (which follows it) out.
    """
    for ln in (v or "").split("\n"):
        ln = ln.strip()
        if ln:
            return ln
    return ""


def _agy_emit_signals(buckets, cap: int = _AGY_SIGNAL_CAP) -> list:
    """Flatten priority-ordered signal buckets under ONE global cap, RESERVING
    a floor for every non-empty bucket (r3/G2).

    r2/C1 fixed the ORDER (terminal error first) but kept a single global cap
    consumed in bucket order, so an earlier bucket could still STARVE a later
    one: 12 `error_message` step strings — or one terminal error plus eleven
    steps — exhaust the cap before a single per-tool error is emitted, and a
    capacity/auth indication present ONLY in `tool_info.error` never reaches
    classify() at all. Each non-empty bucket now gets `cap // <non-empty>`
    slots first (never more than `cap` in total), then the leftovers are handed
    out in priority order — terminal-first is preserved.

    Scope of the guarantee (r4/H1 correction — narrowed from a prior claim
    that "starvation is not possible"): this floor protects only a bucket
    that is ALREADY non-empty by the time this function runs. It says
    nothing about whether a signal reaches a bucket in the first place —
    `agy_classify_signals`'s per-event COLLECTION can still drop a signal
    before it is ever handed to a bucket (see that function's r4/H2 fix for
    a case where it did). The floor is also blind to informativeness: a
    reserved slot can go to a low-value string ahead of a more useful one
    waiting later in the same bucket.
    """
    live = sum(1 for b in buckets if b)
    if not live:
        return []
    floor = max(1, cap // live)
    out: list = []
    for b in buckets:
        out.extend(b[:floor])
    for b in buckets:
        for s in b[floor:]:
            if len(out) >= cap:
                return out[:cap]
            out.append(s)
    return out[:cap]


def agy_classify_signals(events: list, result=None) -> list:
    """STRUCTURAL failure strings from an agy stream, for classify() (r1/R2).

    The no-answer classify blob used to be `stderr + the RAW NDJSON stream`,
    which carries model-authored prose, tool OUTPUT and tool PARAMETERS — the
    reviewed content itself. A packet quoting a capacity phrase therefore
    forced spurious `server-capacity` retries, and one quoting an auth banner
    produced a terminal `oauth-env`. This helper returns ONLY typed error
    payloads: `step_type == "error_message"` step text, `tool_info.error`
    message strings, and a result-level typed error. The full raw stream is
    still preserved verbatim in the run-log — diagnostics are unchanged; only
    what CLASSIFICATION sees is narrowed.

    PRIORITY (r2/C1): the cap used to be filled in EVENT order with the
    result-level error appended LAST and then sliced away, so a run whose tools
    failed repeatedly reached classify() carrying only per-tool noise — the one
    signal that decides the class (capacity / auth / quota, reported at the
    RESULT level) was discarded and the call landed on `unknown`. Signals are
    now collected into three buckets and emitted terminal-first: the
    result-level typed error, then `error_message` steps, then per-tool errors.
    Emission goes through `_agy_emit_signals`, which RESERVES a floor for
    every bucket that is non-empty BY THE TIME emission runs (r3/G2) — see
    that function's docstring for the r4/H1 correction: this narrows
    starvation, it does not eliminate it, because it cannot protect a
    bucket a signal never reached in the first place.

    PER-EVENT BUDGET, SPLIT PER SINK (r3/G2, corrected r4/H2): each event
    contributes at most `_AGY_SIGNAL_EVENT_CAP` strings to the STEP sink
    and, INDEPENDENTLY, up to `_AGY_SIGNAL_EVENT_CAP` more to the TOOL
    sink — two separate per-event budgets, not one shared between them.
    r3 gave the whole event a single shared budget: a `step_type ==
    "error_message"` step carrying its own `message`/`text`/`detail`/
    `description` (or nested `content`/`error`/`error_message`) fields
    could exhaust that shared budget on the STEPS sink before the SAME
    event's `tool_info.error` was ever examined, silently dropping the
    tool error — if that string was the only capacity/auth phrase in the
    whole run, classification degraded to `unknown`. Splitting the budget
    per sink means a step-heavy event can no longer spend its own
    tool-error slot.

    FIRST LINE ONLY (r2/N2), and what it does NOT close (r3/G6): a typed error
    message ECHOES a model-authored argument — the observed denial shape is
    `"User denied permission to run command:\\n<the model's own command line>"`
    — so a model-chosen argument quoting a classifier phrase re-entered the
    blob through the channel that is supposed to be structural. Taking only the
    first non-empty line removes an echo that FOLLOWS a newline. It does NOT
    close the channel: a typed error that INLINES the argument on line 1
    (`"Denied: run_command(find / -name 'model overloaded')"`) still carries
    model-authored text into the classify blob, and the r1/R2 damage direction
    (a quoted capacity/auth phrase forcing a spurious retry or a wrong terminal
    class) remains reachable through that shape. The channel is NARROWED to
    typed error fields and to line 1 of each — not eliminated. Second residual:
    a genuine classifier phrase appearing ONLY on a later line is lost, which
    degrades to `unknown` → the repair agent (the safe direction).
    """
    terminal: list = []   # result-level typed error — THE terminal signal
    steps: list = []      # error_message step payloads
    tools: list = []      # per-tool typed errors

    def _take(container, sink: list, budget: list) -> None:
        def _add(v: str) -> None:
            # budget = this EVENT's remaining contribution (r3/G2).
            if budget[0] <= 0 or len(sink) >= _AGY_SIGNAL_CAP:
                return
            head = _agy_first_line(v)
            if head:
                sink.append(head[:_AGY_DIGEST_VALUE_CAP])
                budget[0] -= 1

        if isinstance(container, str):
            _add(container)
            return
        if not isinstance(container, dict):
            return
        for k in _AGY_ERROR_TEXT_KEYS:
            v = container.get(k)
            if isinstance(v, str):
                _add(v)

    for ev in events or []:
        if len(steps) >= _AGY_SIGNAL_CAP and len(tools) >= _AGY_SIGNAL_CAP:
            break
        if not isinstance(ev, dict):
            continue
        su = ev.get("step_update")
        if not isinstance(su, dict):
            continue
        # r4/H2: SEPARATE per-event budgets per sink. A budget SHARED across
        # the error_message arm below and the tool_info arm let the former
        # spend both slots on `steps` and starve THIS SAME EVENT's
        # `tool_info.error` before it was ever examined.
        step_budget = [_AGY_SIGNAL_EVENT_CAP]
        if su.get("step_type") == "error_message":
            _take(su, steps, step_budget)
            for k in ("content", "error", "error_message"):
                _take(su.get(k), steps, step_budget)
        info = su.get("tool_info")
        if isinstance(info, dict):
            tool_budget = [_AGY_SIGNAL_EVENT_CAP]
            _take(info.get("error"), tools, tool_budget)
    if isinstance(result, dict):
        _take(result.get("error"), terminal, [_AGY_SIGNAL_EVENT_CAP])

    return _agy_emit_signals((terminal, steps, tools))


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
    # Antigravity stream-json read-audit digest (Task 6) — None for every other
    # CLI/wrapper (zero behavior change); antigravity fills it from
    # AgyResult.read_audit on every completed vendor call.
    read_audit: Optional[dict] = None
    # Vendor CLI's own dotted version string (agy telemetry slice,
    # 2026-08-19 — origin: agy 1.1.15's release-day vendor-error outage was
    # investigated with the wrapper's binary MTIME standing in for a version
    # record). None for every other CLI/wrapper (zero behavior change);
    # antigravity threads it from the SAME _probe_agy_version() call the
    # stream-json floor gate already runs on every dispatch — no second probe.
    # Rendered from the PARSED numeric triple, so a pre-release/build suffix
    # the CLI prints (e.g. "-rc1") is not captured (r2 claude m2, disclosed).
    vendor_version: Optional[str] = None
    # Effective working directory of the vendor spawn (cwd record-integrity
    # slice, 2026-08-26 — origin: the 2026-08-22 grant-less agy window could
    # not be adjudicated afterwards because no durable artifact recorded WHICH
    # directory the vendor child ran in; _run_once computed the value for its
    # log f-string and threw it away). Set by _run_once on every spawn attempt
    # (the validated --cwd, or the inherited process cwd when --cwd is absent
    # — including a failed spawn, where the attempted directory IS the
    # forensic value). None on a RunResult that never reached a spawn; the
    # audit/run-log key is then OMITTED (vendor_version shape rule). Never fed
    # back into Popen(cwd=...) — os.getcwd() returns the PHYSICAL path, which
    # would silently change a symlinked-cwd child's view.
    effective_cwd: Optional[str] = None


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


def _validation_error_nonrepairable(exc: Exception) -> bool:
    """STRUCTURAL `[NONREPAIRABLE]` detection — over pydantic's ERROR LIST,
    never over the rendered `str(exc)`.

    `str(ValidationError)` embeds `input_value=<the vendor's own bytes>`, so a
    reply whose CONTENT happens to carry the literal marker (reflected back out
    of the schema text it was shown, or planted) makes an UNRELATED, perfectly
    repairable SHAPE error match a substring test over the rendered string —
    and the leg silently loses its one repair turn (r2 3-family finding;
    probe-confirmed: `errors()[0]["msg"]` was `Input should be a valid integer`
    while the rendered string carried the marker). `errors()[i]["msg"]` carries
    only the validator's own text — for a `model_validator`'s `ValueError` that
    is `"Value error, <the schema's static message>"` — and pydantic never
    interpolates the input value into it.

    Schema-agnostic on purpose (see `NONREPAIRABLE_MARKER`): the contract is
    the token inside a validator's MESSAGE, not an exception subclass and not
    an import of any schema module. Anything that is not a pydantic
    `ValidationError` (a JSON decode error, say) is repairable by definition
    here — a shape/parse slip is exactly what the one repair turn exists for.
    """
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return False
    try:
        items = errors()
    except Exception:
        # A vendored/duck-typed exception whose errors() misbehaves must not
        # take the wrapper down; fall back to "repairable" (the pre-marker
        # default), never to a silent skip of the repair turn.
        return False
    for item in items:
        msg = item.get("msg") if isinstance(item, dict) else None
        if isinstance(msg, str) and NONREPAIRABLE_MARKER in msg:
            return True
    return False


def _content_nonrepairable(cleaned: str, cls) -> bool:
    """The schema's own CONTENT probe, applied to a payload that FAILED
    validation. True when the reply must never be replayed into the one
    schema-repair re-dispatch because of WHAT IT SAYS, independent of which
    validator arm fired.

    Duck-typed exactly like the `NONREPAIRABLE_MARKER` token contract, and for
    the same reason: this engine validates against whatever
    `--pydantic module:Class` names, so it must not import or know any schema.
    A class that exposes no `nonrepairable_content` (every generic schema) is
    unaffected — the probe is skipped and the retry behaves as before.

    Needed because the marker alone gates on the ARM, one level too low
    (cross-family review r5, 3-family convergence + probe P7):

      - a payload carrying a BLOCKING finding can fail for a merely REPAIRABLE
        reason, take the repair turn, and come back a valid CLEAN reply that
        is accepted exit 0 — and since `emit_run_log` writes on FAILURE only,
        attempt 1's blocker is then recorded NOWHERE (retry-turn laundering);
      - pydantic v2 runs `mode="after"` model validators ONLY when every FIELD
        validated, so ANY co-occurring field error suppresses a marked arm
        entirely (P7) and the marker never appears in the error list at all.

    The engine hands the probe the CLEANED RAW STRING — always, unconditionally
    (r7). It used to pre-parse with `json.loads` and pass the parsed object,
    falling back to the string only when that raised (r6). ONE parsing brain is
    the point: the schema's probe owns whole-parse / duplicate-member / brace-
    slice / regex semantics as a single authority ladder, and an engine-side
    pre-parse silently stripped the evidence the schema needs to run it — a
    repeated member (which `json.loads` resolves by keeping the LAST value) is
    unrecoverable once the object exists, so a payload spelling a blocking
    severity and then a non-blocking one arrived looking clean. The engine
    still makes no attempt to INTERPRET the bytes; it just stops deciding for
    the schema which of them survive. The hook keeps accepting a dict or a list
    for direct callers.

    Every remaining failure mode resolves to False (repairable — the pre-probe
    default): no hook, or a probe that raises. A probe must never be able to
    take the wrapper down or silently swallow a repair turn.
    """
    probe = getattr(cls, "nonrepairable_content", None)
    if not callable(probe):
        return False
    try:
        return bool(probe(cleaned))
    except Exception:
        return False


def validate_response_with_trigger(
    answer_text: str, cls
) -> Tuple[bool, Any, bool, NonrepairableTrigger]:
    """(ok, validated_dict_or_error_string, nonrepairable, trigger) — the
    canonical form; `validate_response_detail` / `validate_response` are thin
    façades over it.

    `nonrepairable` is True when EITHER the live exception carries the schema's
    `[NONREPAIRABLE]` marker (`_validation_error_nonrepairable`, decided BEFORE
    the exception is stringified) OR the failed payload's own CONTENT says so
    (`_content_nonrepairable` — the r5 gate that survives a suppressed arm).
    Always False when `ok`. Callers that drive a schema-repair retry MUST
    branch on this flag, never on a substring of the error string they render
    or forward.

    `trigger` (r8 claude must-fix) reports WHICH of those two fired — the
    distinction the bool destroys. Both probes now run unconditionally on a
    failure instead of short-circuiting: the OR'd answer was identical, but the
    second bit is exactly what a consumer needs, and the content probe is a
    pure bounded read. See `NonrepairableTrigger` for why the difference is
    load-bearing, and `nonrepairable_log_marker` for the emitted token.
    """
    cleaned = strip_markdown_fences(answer_text)
    try:
        obj = cls.model_validate_json(cleaned)
        return True, obj.model_dump(mode="json"), False, NonrepairableTrigger.NONE
    except Exception as e:
        trigger = NonrepairableTrigger.NONE
        if _validation_error_nonrepairable(e):
            trigger |= NonrepairableTrigger.ARM
        if _content_nonrepairable(cleaned, cls):
            trigger |= NonrepairableTrigger.CONTENT
        return False, str(e), bool(trigger), trigger


def validate_response_detail(answer_text: str, cls) -> Tuple[bool, Any, bool]:
    """(ok, validated_dict_or_error_string, nonrepairable). 3-tuple façade over
    `validate_response_with_trigger`, kept for callers that drive a repair
    retry but do not report the trigger. The third element stays a plain bool
    — several callers identity-test it."""
    ok, payload, nonrepairable, _ = validate_response_with_trigger(answer_text, cls)
    return ok, payload, nonrepairable


def validate_response(answer_text: str, cls) -> Tuple[bool, Any]:
    """(ok, validated_dict_or_error_string). Thin 2-tuple façade over
    `validate_response_with_trigger`, kept for callers that do not drive a
    repair retry and so do not need the non-repairable bit."""
    ok, payload, _, _ = validate_response_with_trigger(answer_text, cls)
    return ok, payload


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


# ─── Subprocess core ──────────────────────────────────────────────────────

# Loader / interpreter injection env vars scrubbed from the vendor child (I-2/I-3).
# `_run_once` is the SINGLE vendor-child spawn site (codex/gemini/claude/agy —
# the pre-2026-07-31 pty transport, agy's former SEPARATE spawn site, is
# deleted). It applies the scrub via the shared `scrubbed_child_env()` below,
# so a poisoned parent env cannot reach the vendor CLI (gemini/claude/agy are
# Node runtimes; codex/agy spawn tools). The classic
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
    `_CHILD_ENV_SCRUB` injection vars. Applied at the single vendor-child spawn
    site (`_run_once`, Popen — codex/gemini/claude/agy all go through it since
    the 2026-07-31 pty-transport deletion), so the scrub policy lives in
    exactly ONE place. Returns a fresh dict (safe to mutate)."""
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


def _kill_proc_group(proc: subprocess.Popen, pgid: Optional[int] = None) -> None:
    """SIGTERM->SIGKILL escalation against the child's own process GROUP.

    `pgid` is captured by the CALLER at SPAWN time (r1/R10) — right after
    `Popen` returns, which is after the child has already run the `setsid`
    preexec_fn, and while the child is still unreaped. Resolving it inside
    this function instead meant calling `getpgid` on a child that the very
    next line may already have reaped, i.e. reading a pgid that could have
    been recycled. `pgid=None` means "no usable group" (no `setsid` on this
    platform, the spawn-time lookup failed, or the child never got its own
    group): the escalation then falls back to the DIRECT CHILD
    (`terminate()`/`kill()` + the wait-timeout gate), never to a killpg on a
    group we did not verify is the child's own.

    The escalation gate is the GROUP, not the direct child: `proc.wait()`
    only reaps the direct child, so a grandchild reparented within the same
    group (e.g. a backgrounded sub-process the vendor CLI spawned) can still
    be alive after the direct child has exited. After SIGTERM + a bounded
    wait, the group is re-probed with `killpg(pgid, 0)` and SIGKILL escalates
    whenever the probe indicates members remain — `ProcessLookupError` means
    the group is empty (done); `PermissionError` cannot confirm emptiness, so
    it is treated conservatively as "members remain" (escalate).

    RESIDUAL (disclosure carried over from the retired `_pty._killpg`, whose
    text was dropped in the 2026-07-31 transport migration): this narrows but
    does NOT close the pid-recycle hazard. The group-empty probe and the
    SIGKILL both run AFTER `proc.wait()` reaped the direct child, so between
    the reap and the signal the OS may recycle that pid — and therefore the
    pgid — for an unrelated group. If the recycled group is a same-uid group
    we are permitted to signal, `killpg` SUCCEEDS and mis-signals it with no
    exception raised. The window is microseconds and requires pid wraparound
    under load; a pidfd-based implementation would be the stronger fix if it
    is ever observed. `EPERM` on either call is the OTHER arm of the same
    hazard (a recycled group we may not signal) and is handled above.

    Shared by both `_run_once` callers: our own timeout, and an abnormal
    unwind (a signal-raised SystemExit/KeyboardInterrupt while `proc.wait()`
    is blocked) — the vendor subtree must never be left orphaned in either
    case.
    """
    has_pg = pgid is not None and hasattr(os, "killpg")

    try:
        if has_pg:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError) as e:
        log(f"SIGTERM failed: {e}")

    child_timed_out = False
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        child_timed_out = True
        log("direct child still alive 5s after SIGTERM")

    if has_pg:
        try:
            os.killpg(pgid, 0)  # group-empty probe (signal 0, no side effect)
            escalate = True  # probe succeeded: at least one member remains
        except ProcessLookupError:
            escalate = False  # group empty: nothing left to escalate against
        except PermissionError:
            escalate = True  # cannot confirm empty: treat as members remain
    else:
        escalate = child_timed_out  # no group primitives: fall back to child gate

    if not escalate:
        return

    log("group still has members after SIGTERM; sending SIGKILL")
    try:
        if has_pg:
            os.killpg(pgid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        log("zombie: SIGKILL also unresponsive")


def _run_once(
    cli: str,
    cmd: list[str],
    cwd: Optional[str],
    timeout: int,
    stdin_text: Optional[str] = None,
    classify_and_log: bool = True,
) -> RunResult:
    """One Popen invocation.

    stdout = capture-only (structured JSON/JSONL — not for human stream).
    stderr = mirror to parent stderr (human progress visibility).
    stdin_text: when provided, feed via a daemon writer thread so a large
    prompt cannot deadlock against a full OS pipe before the child starts
    reading. When None (default), stdin is DEVNULL (gemini/claude behavior
    unchanged).
    classify_and_log: default True keeps codex/gemini/claude byte-identical
    (classify() + the "[wrapper] <cli> ..." summary line run here as before).
    False skips BOTH — the agy stream-json driver decides classification and
    emits its own canonical summary line later; a premature line here would
    duplicate the one the dispatch SKILL greps.
    """
    effective_cwd = cwd or os.getcwd()
    log(f"exec cwd={effective_cwd} timeout={timeout}s argv={cmd}")
    start = time.monotonic()

    # Scrub loader/interpreter injection vars so a poisoned parent env cannot
    # reach the vendor child (I-2/I-3). Explicit env= replaces the implicit
    # full-os.environ inheritance. scrubbed_child_env() is the shared
    # single-source scrub; _run_once is the single vendor-child spawn site.
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
            classification="unknown", effective_cwd=effective_cwd,
        )

    # Capture the child's process group NOW (r1/R10), while it is guaranteed
    # to be the child's own and the child is still unreaped. Popen only
    # returns after the child ran preexec_fn (setsid) and reached exec — the
    # parent blocks on the exec-error pipe — so the group is already
    # established here. Doing this inside _kill_proc_group instead meant a
    # post-reap getpgid on a possibly-recycled pid.
    pgid: Optional[int] = None
    if popen_kwargs.get("preexec_fn") is not None and hasattr(os, "getpgid"):
        try:
            pgid = os.getpgid(proc.pid)
        except OSError as e:
            log(f"getpgid at spawn failed: {e}")
        else:
            # Defensive: if setsid did not take effect the child shares OUR
            # group, and a killpg would signal the wrapper itself.
            if hasattr(os, "getpgrp") and pgid == os.getpgrp():
                log("child shares the parent process group; group kill disabled")
                pgid = None

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
        _kill_proc_group(proc, pgid)
    except BaseException:
        # Abnormal unwind while the vendor child is still running (e.g. a
        # signal-raised SystemExit from a caller's own SIGTERM/SIGHUP
        # handler — antigravity_wrapper.py's _terminate_to_exit interrupts
        # exactly this wait()) must not leave the vendor subtree orphaned:
        # kill+reap before the exception propagates. Never swallowed —
        # the caller's unwind (settings-guard restore, exit code) still runs
        # as the exception continues up the stack.
        #
        # The cleanup is itself exception-safe (r1/R5): an unexpected raise
        # from _kill_proc_group must NEVER replace the in-flight exception.
        # It did — an OSError here displaced the signal-raised SystemExit,
        # and antigravity_wrapper.main() maps OSError to `config-conflict`,
        # so an operator SIGTERM was reported as a settings conflict. The
        # BaseException catch is deliberate: a KeyboardInterrupt arriving
        # DURING cleanup must not win over the original either.
        log("abnormal unwind mid-wait; killing vendor subtree")
        try:
            _kill_proc_group(proc, pgid)
        except BaseException as cleanup_exc:  # noqa: BLE001 — see above
            log(f"vendor-subtree cleanup failed during unwind: {cleanup_exc!r}")
        raise

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
    result.effective_cwd = effective_cwd
    if classify_and_log:
        # SEMANTIC stderr classification (tool-not-installed / vendor warning)
        # stays the leader's judgment over the mirrored raw stderr.
        result.classification = classify(
            cli, stderr, stdout, result.exit_code, vendor_exit_code=rc,
        )
        # One-line deterministic summary (immediately visible to leader/user).
        log(
            f"[wrapper] {cli} {result.classification} "
            f"exit={result.exit_code} vendor={result.vendor_exit_code} "
            f"elapsed={elapsed:.1f}s"
        )
    else:
        # r1/R8: do NOT leave the field at its "ok" default — a shared struct
        # reading "ok" for a run that was never classified is a trap for any
        # future consumer of this RunResult. NOT a new classify() token
        # (CLASSIFICATION_TOKENS is unchanged and this value never reaches
        # audit, the summary line or a repair proposal): the sole
        # classify_and_log=False caller is the agy stream-json driver, which
        # sets the real classification on its own AgyResult/RunResult.
        result.classification = "unclassified"

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

        ok, validated_or_err, nonrepairable, trigger = (
            validate_response_with_trigger(answer, pydantic_cls))
        if ok:
            result.validated = validated_or_err
            return result

        result.validation_error = str(validated_or_err)
        log(f"schema validation failed: {validated_or_err}")

        # The schema opted this arm out of automated repair — see
        # NONREPAIRABLE_MARKER at the top of this module. Replaying such an
        # error into the repair prompt below invites the model to weaken its
        # own CONTENT until validation passes (for the review-verdict schema:
        # downgrade a Critical/must-fix finding to Minor and keep SAFE), and
        # the caller only ever sees the repaired object. Fail loud instead:
        # exit 66, handled by the leader's INVALID-leg path, where a re-ask is
        # explicit and visible.
        #
        # The decision is STRUCTURAL (`validate_response_detail`'s third
        # value, read off pydantic's error list) — never a substring of
        # `result.validation_error`, which embeds the vendor's own
        # `input_value=...` bytes and so lets a reply REFLECT the marker back
        # to steal its own repair turn (r2 3-family finding).
        if nonrepairable:
            # The line states WHICH trigger fired, MECHANICALLY (r8 claude
            # must-fix). r6 already corrected "on a [NONREPAIRABLE] arm" to the
            # honest disjunction "(marked arm or blocking content)", but a
            # disjunction still leaves the consumer guessing — and the review
            # skill's verdict-binding obligation BRANCHES on the answer, so a
            # guess there manufactures verdict inflation. `trigger=` is that
            # answer as an exact token; the `[NONREPAIRABLE` prefix is kept so
            # every pre-r8 grep still matches.
            log(f"schema validation non-repairable "
                f"{nonrepairable_log_marker(trigger)} — skipping repair retry")
            return promote_schema_fail(result)

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
    if result.vendor_version is not None:
        # Not prompt-bearing (the vendor CLI's own dotted version string, no
        # user/model content) — exempt from the custody taxonomy above (P4.b,
        # spec 3-way 2026-07-11), unlike every other field in this record.
        # Key omitted (not null) when absent, so codex/gemini/claude records
        # keep their existing shape byte-for-byte (agy-only today).
        rec["vendor_version"] = result.vendor_version
    if result.effective_cwd is not None:
        # Effective spawn directory (cwd record-integrity slice, 2026-08-26).
        # A filesystem path — the same custody class as the path args already
        # riding `cmd` un-redacted in redact mode (P4.b strips prompt-bearing
        # args only), so no redaction. Key omitted when the record never
        # reached a spawn (pre-spawn guard failures), same shape rule as
        # vendor_version above.
        rec["effective_cwd"] = result.effective_cwd
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
        **({"read_audit": result.read_audit} if result.read_audit is not None else {}),
        # vendor_version (fix wave W1 item 3, claude m3, 2026-08-19): same
        # omit-when-None spread pattern as read_audit above. The repair
        # analyzer reads ONLY this run-log (barred from audit.jsonl by its
        # Scope boundary), and the motivating failure class — agy 1.1.15's
        # release-day vendor-error outage — is version-correlated, so the
        # version needs to ride the artifact the analyzer can actually see.
        **({"vendor_version": result.vendor_version} if result.vendor_version is not None else {}),
        # effective_cwd (cwd record-integrity slice, 2026-08-26): same
        # omit-when-None spread pattern. The repair analyzer reads ONLY this
        # run-log, and a wrong-root dispatch is exactly the class it must be
        # able to see in the artifact it is allowed to open.
        **({"effective_cwd": result.effective_cwd} if result.effective_cwd is not None else {}),
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)

    _prune_run_logs(runs_dir, preserve=path)

    return path


def _prune_dir_by_caps(
    dir_path: Path,
    max_files: int,
    max_bytes: int,
    preserve: Optional[Path],
    glob_patterns: tuple[str, ...],
    extra_preserve: Optional[Path] = None,
) -> None:
    """Shared oldest-first prune-by-cap logic (file count + total bytes).

    Factored out of the original run-log-only implementation (task-1,
    2026-07-31 read-audit durable-artifact follow-up) so the read-audit
    digest dir (`emit_read_audit`) can reuse the exact same race-tolerant
    algorithm instead of a parallel copy. Callers pass their OWN cap
    constants read at call time (never bound as function defaults), so a
    test that reassigns e.g. `_RUN_LOG_MAX_FILES` on the module still takes
    effect on the next call.

    Race-tolerant — parallel writes that all hit the cap may all attempt to
    prune; duplicate unlink attempts are absorbed by try/except. Worst case =
    slight over-prune. `preserve` is never deleted by this writer: a single
    large fresh artifact IS the current call's own IPC and must survive even
    when it alone exceeds the byte cap (mtime order alone did not protect
    the only-file case).

    `extra_preserve` (fix wave W1 item 5, claude m1, 2026-08-19) — an
    OPTIONAL second path to protect in the SAME call, additive to
    `preserve`. `emit_read_audit`'s default-location copy needed this: when
    a caller parks `TRIAD_READ_AUDIT_FILE` INSIDE the default read-audit
    dir, that override file sits in the SAME glob the copy-write's own
    prune walks, and `preserve` alone (the fresh copy's path) left the
    override file — written moments earlier by the SAME call — as the one
    unprotected candidate. Every other caller (`_prune_run_logs`, the
    override-unset default-dir prune) passes `None` here and is unaffected.
    """
    preserve_paths = {p.resolve(strict=False) for p in (preserve, extra_preserve) if p is not None}
    # Race-resilient listing: a concurrent unlink (or a dangling symlink) makes
    # p.stat() raise mid-sort. Materialize (path, mtime) per-file, skipping any
    # entry that vanishes — a single bad entry must NOT abort the whole prune
    # (the previous `sorted(..., key=p.stat)` form aborted on the first OSError).
    try:
        entries: list[Path] = []
        for pat in glob_patterns:
            entries.extend(dir_path.glob(pat))
    except Exception:
        return
    pairs: list[tuple[Path, float]] = []
    for p in entries:
        try:
            pairs.append((p, p.stat().st_mtime))
        except OSError:
            continue
    files = [p for p, _ in sorted(pairs, key=lambda x: x[1])]

    over_count = max(0, len(files) - max_files)
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
    over_bytes = total_bytes - max_bytes

    for f in files:
        if over_count <= 0 and over_bytes <= 0:
            break
        if f.resolve(strict=False) in preserve_paths:
            continue
        try:
            sz = f.stat().st_size
            f.unlink()
            over_count -= 1
            over_bytes -= sz
        except Exception:
            pass


def _prune_run_logs(runs_dir: Path, preserve: Optional[Path] = None) -> None:
    """Best-effort prune: enforce file count + total byte caps.

    Thin wrapper over the shared `_prune_dir_by_caps` (task-1, 2026-07-31 —
    factored out so `emit_read_audit`'s digest dir can reuse the identical
    race-tolerant algorithm). Behavior unchanged from before the factor-out.
    """
    _prune_dir_by_caps(
        runs_dir, _RUN_LOG_MAX_FILES, _RUN_LOG_MAX_BYTES, preserve,
        ("*.json", "*.prompt.tmp"),
    )


# ─── Read-audit digest — durable file artifact (Task 1, 2026-07-31) ───────
# Root cause: emit_run_log writes only on FAILURE, so a successful agy call's
# read-audit digest previously existed only as a transient stderr line (the
# review SKILL's read-audit gate had to text-extract it from a stream that
# also mirrors untrusted vendor bytes verbatim — the anchor-mismatch /
# first-match-forgery / late-append findings this durable file retires).
# emit_read_audit writes on EVERY outcome where `result.read_audit is not
# None` — success AND failure — unlike emit_run_log's failure-only rule
# (which stays exactly as it is; this is a NEW, separate artifact).
#
# Owner ruling (do NOT re-open): this file is EVIDENCE THAT A LEG DID THE
# READING WORK, not an authenticated control — no nonce, no dedicated fd,
# nothing framed as authentication. The digest's CONTENT is still folded
# from vendor-supplied stream events regardless of transport.
# 100 -> 200 (fix wave W1 item 6, claude m2, 2026-08-19; precision r2): the
# dir now holds TWO record classes (override-unset PRIMARY digests and
# override-set copies -- each call writes exactly ONE file in either mode),
# so the cap doubles to grow the shared retention window; how many of the
# 200 are primaries depends on the workload mix (a review-dominated mix
# retains mostly copies). No consumer binds to this dir, so the caps bound
# operator-forensics depth only. The 20 MB byte cap is untouched -- digest
# values are already capped at 200 chars (_AGY_DIGEST_VALUE_CAP), so the
# extra writer's byte impact is small relative to the file-count pressure.
_READ_AUDIT_MAX_FILES = 200
_READ_AUDIT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB total cap, same policy shape as run-logs


def emit_read_audit(cli: str, result: RunResult) -> Optional[Path]:
    """Write the per-call read-audit digest to a durable JSON file.

    Default path: `_LOG_DIR / cli / "read-audit" / <UTC-ts>-<pid>-<uuid8>.json`
    (NOTE: the dir is named `read-audit/`, deliberately NOT `audit/` — the
    sibling `_logs/<cli>/audit.jsonl` already owns the name "audit", and a
    colliding dir name would confuse the two artifacts).

    `TRIAD_READ_AUDIT_FILE` (absolute path) overrides the default: writes to
    EXACTLY that path instead (parent dirs created, existing content
    overwritten). This mirrors the existing `TRIAD_DISPATCH_LOG_DIR` override
    pattern and is what lets a consumer (e.g. the cross-family-review SKILL)
    know the path a priori — zero stderr parsing. Concurrency note: the
    override names ONE file, so a caller running parallel legs must give each
    call its own path (the review SKILL uses one `<packet-dir>/agy-read-audit.json`
    per packet dir, one packet dir per leg).

    Default-location copy (task-1, 2026-08-19 telemetry slice, behavior 2):
    when the override is set, this function ALSO writes the SAME record to
    the default location (below) — origin: a review packet dir is deleted at
    gate close, so the override was the ONLY copy of a round's digest and it
    was lost along with the packet. The override write stays PRIMARY: this
    function's return value and the caller's `read-audit-file:` stderr
    contract are UNCHANGED (still the override path). The copy runs the SAME
    self-prune the default dir already runs, and logs one additional stderr
    line via `log()`: `read-audit-copy: <abs-path>`. Best-effort exactly like
    every other clause here — a copy-write failure never touches the
    (already-succeeded) override write or the wrapper's exit code/classification.

    The OVERRIDE-path write uses `os.open(..., O_NOFOLLOW)` (final-gate fix
    round, converged claude must-fix / codex hardening): the override path is
    CALLER-supplied (an env var a review-leg dispatch sets), so a symlink
    planted there must be refused rather than followed — the same
    leader-privileged-write convention `setup_permissions.py`'s
    `read_settings_nofollow`/lock-file opens already use elsewhere in this
    repo. The DEFAULT-dir path stays a plain `path.open("w")`: its basename
    is a fresh uuid8 this function itself mints, so it cannot be
    pre-planted the way a caller-NAMED override path can.

    File content is a single JSON object with exactly two top-level keys, so
    digest keys can never collide with metadata keys:
        {"meta": {"cli", "ts_utc", "classification", "exit_code",
                   "vendor_exit_code", "elapsed_s"},
         "digest": <result.read_audit, verbatim>}

    Returns None (and writes nothing) when `result.read_audit is None` — the
    caller (currently only antigravity_wrapper.py) is expected to skip the
    `read-audit-file:` stderr line in that case, same as `emit_run_log`'s
    None-on-success convention.

    Best-effort: an IO failure (unwritable dir, blocked path component, …)
    must NOT change the wrapper's exit code or classification — it logs one
    stderr line via `log()` and returns None. `result` (the RunResult) is
    never mutated on this path.

    The default dir self-prunes after write (`_READ_AUDIT_MAX_FILES` /
    `_READ_AUDIT_MAX_BYTES`, same shape as `_prune_run_logs`). PRECISE prune
    invariant (fix wave W1 item 5, claude m1, 2026-08-19 — narrows the prior
    unconditional "never pruned" claim): the override path is never pruned
    BY THE CALL THAT WROTE IT — this function protects its own override
    write even when that path happens to sit inside the default dir (an
    edge case: `TRIAD_READ_AUDIT_FILE` parked under `_LOG_DIR/<cli>/read-audit/`).
    An override path PARKED inside the default dir is, however, subject to
    LATER calls' caps, same as any other file there — a caller that needs
    durability for an override path independent of subsequent calls uses a
    path OUTSIDE the default dir (the `triad-cross-family-review` packet-dir
    convention already does this).
    """
    if result.read_audit is None:
        return None

    override = os.environ.get("TRIAD_READ_AUDIT_FILE")
    try:
        if override:
            path = Path(override)
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            read_audit_dir = _LOG_DIR / cli / "read-audit"
            read_audit_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            pid = os.getpid()
            suffix = uuid.uuid4().hex[:8]
            path = read_audit_dir / f"{ts}-{pid}-{suffix}.json"

        rec = {
            "meta": {
                "cli": cli,
                "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "classification": result.classification,
                "exit_code": result.exit_code,
                "vendor_exit_code": result.vendor_exit_code,
                "elapsed_s": round(result.elapsed_s, 2),
            },
            "digest": result.read_audit,
        }
        if override:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
        else:
            with path.open("w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)

        if not override:
            _prune_dir_by_caps(
                read_audit_dir, _READ_AUDIT_MAX_FILES, _READ_AUDIT_MAX_BYTES,
                preserve=path, glob_patterns=("*.json",),
            )
        else:
            # Telemetry copy for post-hoc forensics (fix wave W1 item 7,
            # claude HS1, reworded 2026-08-19 to not overclaim bindability):
            # the binding artifact REMAINS the override path written above —
            # consumers never bind to this dir. This is a best-effort
            # ADDITIONAL copy at the default location a non-override call
            # would have used, so a consumer that scans the default dir for
            # post-hoc forensics (e.g. after a packet dir was already
            # deleted) still finds the digest. Own try/except: a copy
            # failure must never affect the override write already on disk
            # or the wrapper's exit code/classification.
            try:
                copy_dir = _LOG_DIR / cli / "read-audit"
                copy_dir.mkdir(parents=True, exist_ok=True)
                copy_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                copy_suffix = uuid.uuid4().hex[:8]
                copy_path = copy_dir / f"{copy_ts}-{os.getpid()}-{copy_suffix}.json"
                # copied_from (fix wave W1 item 4, claude m4): the COPY's own
                # meta gains provenance — which override path it was copied
                # from — so two same-day gates/rounds can be told apart once
                # their packet dir (and its override path) is gone. Built as
                # a SEPARATE dict from the override's `rec["meta"]` (never
                # mutated in place): the primary override file's shape is a
                # consumer contract and must stay byte-unchanged.
                copy_rec = {
                    "meta": {**rec["meta"], "copied_from": override},
                    "digest": rec["digest"],
                }
                # Explicit mode 0600 (fix wave W1 item 1, codex must-fix /
                # claude HS — was a plain `path.open("w")`, umask-dependent
                # mode): the SAME bits the override write above uses. No
                # O_NOFOLLOW here (unlike the override write): this
                # basename is a fresh uuid8 THIS function mints, so — same
                # reasoning as the plain default-path write a few lines up —
                # it cannot be pre-planted the way a caller-NAMED override
                # path can; the sensitivity of the DATA (the same digest)
                # still warrants the same explicit permission bits.
                copy_fd = os.open(str(copy_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(copy_fd, "w", encoding="utf-8") as f:
                    json.dump(copy_rec, f, ensure_ascii=False, indent=2)
                # extra_preserve (fix wave W1 item 5, claude m1): protect
                # THIS call's own override write too, when it happens to sit
                # inside `copy_dir` (TRIAD_READ_AUDIT_FILE parked under the
                # default read-audit dir) — see the docstring's PRECISE
                # prune invariant above. `preserve=copy_path` alone left
                # that override file, written moments earlier by this SAME
                # call, as the one candidate this prune step didn't know to
                # protect.
                extra = (path if path.resolve(strict=False).parent
                         == copy_dir.resolve(strict=False) else None)
                _prune_dir_by_caps(
                    copy_dir, _READ_AUDIT_MAX_FILES, _READ_AUDIT_MAX_BYTES,
                    preserve=copy_path, glob_patterns=("*.json",),
                    extra_preserve=extra,
                )
                log(f"read-audit-copy: {copy_path}")
            except Exception as e:
                log(f"emit_read_audit: failed to write default-location copy — {e}")
        return path
    except Exception as e:
        log(f"emit_read_audit: failed to write digest file — {e}")
        return None


def preclear_read_audit_file(repair_mode: bool = False) -> None:
    """STALE-DIGEST close (final-gate fix round, converged codex+claude
    finding). A review leg's packet dir is REUSED across rounds — if a call's
    `emit_read_audit` write silently failed (best-effort, § above), a PRIOR
    round's digest file was left in place at the SAME `TRIAD_READ_AUDIT_FILE`
    path, where it reads as if it were THIS round's evidence (a stale-but-
    present file is indistinguishable from a fresh PASS to a consumer that
    only checks file existence + content, not provenance). Pre-clearing at
    call START restores the correct degraded state — ABSENT — for a call that
    fails before ever reaching `emit_read_audit`'s call site, or whose write
    fails again.

    Called by `antigravity_wrapper.py`'s `main()` at the very top, before ANY
    other logic (argparse, validation, the vendor dispatch) — so EVERY exit
    path, including an early arg-validation failure that never reaches
    `emit_read_audit` at all, still leaves the file ABSENT rather than stale.

    `repair_mode=True` SKIPS the clear entirely (re-confirm round 2 / G3,
    claude Minor): a `--repair-mode` re-run re-executes the wrapper for
    VERIFICATION purposes (the repair flow's Step 5d), a call unrelated to
    the review leg's own evidence collection — if that re-run's environment
    still carries the SAME `TRIAD_READ_AUDIT_FILE` the original leg used,
    unconditional clearing DELETED the already-completed leg's digest before
    the repair attempt even started (fail-closed, but a wasted re-dispatch
    that then has to re-collect evidence it already had). Mirrors
    `prune_stale_run_logs`'s own `if not repair_mode` skip inside
    `_run_agy_with_retry` — a sibling next-run-cleanup step with the exact
    same concern (a repair-mode call must not disturb ambient artifacts a
    normal dispatch owns).

    No-op when `TRIAD_READ_AUDIT_FILE` is unset (the default-dir path uses a
    fresh uuid8-suffixed filename every call, so it can never collide with a
    stale prior file in the first place — nothing to pre-clear there).
    `FileNotFoundError` (nothing to clear — the common case) is silently
    fine. Any OTHER `OSError` (permission denied, a directory sits at the
    path, ...) logs ONE loud stderr line and CONTINUES: pre-clear is a
    best-effort hygiene step, not a hard precondition, and failing the whole
    dispatch over an unlinkable stale file would be worse than the stale-file
    risk it closes.
    """
    if repair_mode:
        return
    override = os.environ.get("TRIAD_READ_AUDIT_FILE")
    if not override:
        return
    try:
        os.unlink(override)
    except FileNotFoundError:
        pass
    except OSError as e:
        log(f"preclear_read_audit_file: could not clear stale digest at {override} — {e}")


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
