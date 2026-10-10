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
import functools
import importlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

# pydantic optional — only required when --pydantic flag is given, and then
# **v2 only**: `model_validate_json()` / `model_json_schema()` /
# `model_dump(mode="json")` are all v2 APIs absent from 1.x. Ubuntu 24.04 apt
# ships `python3-pydantic` 1.10, where the import SUCCEEDS — a presence-only
# guard would let the run reach an AttributeError deep inside validation
# instead of failing here with an actionable message.
try:
    import pydantic  # type: ignore
    from pydantic import BaseModel  # type: ignore
    # `VERSION` is pydantic's own attribute (present in 1.x and 2.x); a
    # vendored / repackaged build may carry only the PEP 396 `__version__`.
    PYDANTIC_VERSION_FOUND = str(
        getattr(pydantic, "VERSION", None)
        or getattr(pydantic, "__version__", None)
        or "") or None
    PYDANTIC_OK = (PYDANTIC_VERSION_FOUND or "").split(".")[0] == "2"
    if not PYDANTIC_OK:  # pragma: no cover - v1 not installed on the dev Mac
        BaseModel = None  # type: ignore
except ImportError:  # pragma: no cover
    BaseModel = None  # type: ignore
    PYDANTIC_VERSION_FOUND = None
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

# The classification-token → EXIT_* table, lifted OUT of the function body so the
# set of EXPLICIT keys is readable as DATA (`EXIT_MAP_TOKENS`). `.get(cls, ...)`
# below means the function can never report a missing key, so a membership test
# needs the keys themselves — spec case C8 / rule R-TOKENS ("a membership test
# replaces the vacuous `is not None` assert shipped on both hosts"); the shared
# vocabulary is the vendored `spec/contracts/exit-tokens.json`, pinned by t55.
_EXIT_BY_CLASSIFICATION: dict[str, int] = {
        "ok": EXIT_OK,
        "server-capacity": EXIT_RATE_GIVE_UP,
        "cli-subscription-cap": EXIT_TERMINAL,
        "token-limit": EXIT_TERMINAL,
        "oauth-env": EXIT_TERMINAL,
        "timeout": EXIT_TIMEOUT,
        "extraction-error": EXIT_CLI_FAIL,
        "schema-fail": EXIT_SCHEMA_FAIL,
        "schema-rejected": EXIT_SCHEMA_REJECTED,
        "config-conflict": EXIT_TERMINAL,
        "task-blocked": EXIT_TERMINAL,  # the shared contract's claude permission-denial class; the codex host emits it, this host has no producer
        "vendor-error": EXIT_TERMINAL,  # agy: rc!=0 but a non-empty answer — surface, NOT repair
        "admission-refused": EXIT_TERMINAL,  # agy: a tool OUTSIDE the agent allowlist in the stream (v2 census) — surface, NOT repair
        "vendor-timeout": EXIT_TERMINAL,  # agy: the vendor's OWN turn timeout (result.error "timeout waiting for response", empty answer) — surface, NOT repair
        "truncated-answer": EXIT_TERMINAL,  # agy: CLI-side mid-answer fold (driver hardcodes 65 too; the row keeps the map and the registry comment in agreement — gate r2 row 17)
        "input-delivery-failed": EXIT_TERMINAL,  # wrapper-SET, never a classify() result: the stdin prompt was not confirmed delivered (write/flush/encode failed or unconfirmed) while the child exited 0 — surface, NOT repair (codex handoff 2026-09-18; t48/f12)
        "unknown": EXIT_CLI_FAIL,
}

# The map's EXPLICIT keys — the token vocabulary this host can put on an exit
# code. Public because the membership contract (C8) is checked against it.
EXIT_MAP_TOKENS: frozenset[str] = frozenset(_EXIT_BY_CLASSIFICATION)


def map_classification_to_exit(cls: str) -> int:
    """Map a classify() result string to a wrapper EXIT_* code (pure helper).

    Unmapped input keeps falling back to `EXIT_CLI_FAIL` (a caller must never
    crash on an unexpected token); the DRIFT guard is the import-time
    membership assert beside `CLASSIFICATION_TOKENS`, not this fallback.
    """
    return _EXIT_BY_CLASSIFICATION.get(cls, EXIT_CLI_FAIL)


# ─── Pattern lists (per-CLI MEASURED sentences; new ones = extension entries) ─
# Lowercase substring match. Terminal-first ordering when classifying.

# Each CLI's measured failure sentences live in `CLI_PATTERNS`; a new one
# enters as a classifier-extension entry.

# Each CLI's OWN measured sentences, keyed cli -> list name; classify() reads a
# CLI's entries only on that CLI's runs.
CLI_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "codex": {
        "SERVER_CAPACITY_PATTERNS": (
            "selected model is at capacity",  # `Selected model is at capacity. Please try a different model.` — the frozen contracts/vendor-failure-lines.json codex row (JSONL error + turn.failed, vendor rc 1)
            "exceeded retry limit, last status: 429",  # codex's own RetryLimitReachedError (codex-rs protocol/src/error.rs, "exceeded retry limit, last status: {}{}"; openai/codex#30471)
        ),
        "CLI_SUB_CAP_PATTERNS": (
            "you've hit your usage limit",  # codex's own UsageLimitReachedError Display "You've hit your usage limit…" (openai/codex main codex-rs/protocol/src/error.rs, every variant; read 2026-10-05)
        ),
        "SCHEMA_REJECTED_PATTERNS": (
            "invalid schema for response_format",  # codex error event, code invalid_json_schema: "Invalid schema for response_format 'codex_output_schema': …" — 2 real rows (_logs/codex/audit.jsonl, 2026-09-20)
        ),
    },
    "gemini": {
        "SERVER_CAPACITY_PATTERNS": (
            "model_capacity_exhausted",  # gemini 429 stderr (MODEL_CAPACITY_EXHAUSTED): 86 real rows, 10 of them failed runs, _logs/gemini/audit.20260905T202129Z-59949-295f5af7.jsonl (2026-05)
            "resource_exhausted",        # same gemini 429 stderr (status RESOURCE_EXHAUSTED), same rows
            "ratelimitexceeded",         # same gemini 429 stderr (reason rateLimitExceeded), same rows
        ),
        "CLI_SUB_CAP_PATTERNS": (
            "your quota will reset after",  # gemini stderr "…exhausted your capacity on this model. Your quota will reset after <t>." — 158 real rows, 37 classified cli-subscription-cap (same file)
            "no longer supported for gemini code assist for individuals",  # gemini stderr "Error authenticating: IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals." — 43 real rows (same file, 2026-06/07)
            "ineligibletiererror",  # the same captured line's error class
        ),
    },
    "antigravity": {
        "SERVER_CAPACITY_PATTERNS": (
            "network issue connecting to the server",  # `There was a network issue connecting to the server, please try again.` — the frozen contracts/vendor-failure-lines.json agy row (status ERROR, empty response, vendor rc 1)
            "unavailable (code 503)",  # agy stderr `error: UNAVAILABLE (code 503): Deadline expired …` (agy 1.2.11, run-log 20260926T020525Z-78105-da2d3ccf); never a bare "503"
        ),
        "CLI_SUB_CAP_PATTERNS": (
            "your ai credits balance is too low to continue",  # agy "Your AI credits balance is too low to continue." — agy changelog 1.2.15 (vendor source); contracts/vendor-failure-lines.json agy row; stream position not captured
        ),
    },
}

# SEMANTIC classification of stderr (tool-not-installed / vendor warning /
# normal chatter) is the LEADER's job (the AI that receives the mirrored
# stderr via its shell tool). The wrapper only records raw stderr into the
# audit log; the leader judges it and alerts the user. The dispatch SKILLs
# carry the stderr-interpretation guidance.


# Measured vendor exit codes live only in the classifier extension's `vendor_exit_map` (an analyzer proposal the leader applies with apply_patch.py).

# agy only, in no raw-text list (FP-safe). Matched ONLY on a
# line BEGINNING with it (`_agy_banner_line`: lines split on LF only; the
# classifier extension's learned variants too); it decides a class in one
# place: the auth-carrier rung (`_auth_carrier_stop` — agy's stderr, and inside
# a finish-schema validation report in `result.error`).
AGY_AUTH_BANNER_PATTERNS = ("authentication required. please visit the url",)


# ── Original-text JSON guard: duplicate members (spec C14 / R-BIND) ───────
# `json.loads` and pydantic's `model_validate_json` both ACCEPT a repeated
# member and keep the LAST value, so a reply that states a blocking fact and
# then repeats the member with a benign one arrives looking clean — the
# evidence is gone before any validator runs. R-BIND: "Duplicate JSON members
# are rejected at the original-text boundary before extraction or
# normalization can discard evidence (verified gap on BOTH hosts)."
#
# The scan is schema-AGNOSTIC (the engine validates against whatever
# `--pydantic module:Class` names) and reports only the FIRST duplicated key,
# at any depth: the caller needs a reason string, not an inventory. A text that
# is not JSON at all reports None — that failure belongs to the caller's own
# parser, whose message is unchanged.


class _DuplicateJSONMember(ValueError):
    """Raised by the object_pairs_hook; carries the offending key name.

    `line_no` is filled in by a LINE-ORIENTED caller (`parse_agy_stream`) —
    the hook itself sees one object, not a stream — and stays None for the
    whole-document scans. It is 1-based so a wrapper log line points at the
    stream line an operator would count to.
    """

    def __init__(self, key: str, line_no: int | None = None):
        super().__init__(f"duplicate JSON member '{key}'")
        self.key = key
        self.line_no = line_no


def _reject_duplicate_pairs(pairs):
    """`object_pairs_hook` that refuses a repeated member in ONE object.

    Sibling objects that each carry the same key are NOT duplicates — the hook
    is called once per object, so the check is correctly scoped.
    """
    seen: set = set()
    for key, _value in pairs:
        if key in seen:
            raise _DuplicateJSONMember(key)
        seen.add(key)
    return dict(pairs)


def _duplicate_json_member(text: str) -> Optional[str]:
    """The first duplicated member name in `text` at ANY depth, else None.

    None also for text that is not valid JSON (see the section comment).
    """
    if not text:
        return None
    try:
        json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except _DuplicateJSONMember as e:
        return e.key
    except (ValueError, TypeError, RecursionError):
        return None
    return None


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
# Per-attempt breakdown kept in the merged aggregate (r1/R4). The union lists
# carry the evidence; this list is the bounded per-attempt census.
_AGY_DIGEST_ATTEMPT_CAP = 10
# Tool CLASS recorded on every read_attempts entry (r2/C5). read_attempts
# collects EVERY unsuccessful tool, but the review SKILL's VOID diagnostic
# reports a match as "the leg failed to READ the packet" — a failed write or
# command naming the packet produced a false diagnostic. The class is folded
# HERE (one source of truth) so the SKILL filters on `.class == "read"`
# instead of duplicating these tool-name sets into its jq.
_AGY_TOOL_CLASSES = (("read", _AGY_READ_TOOLS), ("write", _AGY_WRITE_TOOLS),
                     ("web", _AGY_WEB_TOOLS))
# The digest's capped lists — each merged pairwise with its _omitted counter.
_AGY_DIGEST_LISTS = ("files_read", "denied", "web", "read_attempts")


def _agy_tail_fragment(text: str) -> int:
    """1-based line number of a trailing fragment, else 0: the text does not
    end in `\\n`, its last segment starts with `{`, and decoding that segment
    raises anything but `_DuplicateJSONMember` (the driver's `truncated_tail`)."""
    if not text or text.endswith("\n"):
        return 0
    lines = text.split("\n")
    stripped = lines[-1].strip()
    if not stripped.startswith("{"):
        return 0
    try:
        json.loads(stripped, object_pairs_hook=_reject_duplicate_pairs)
    except _DuplicateJSONMember:
        return 0
    except Exception:
        return len(lines)
    return 0


def parse_agy_stream(text: str) -> tuple:
    """Parse agy stream-json NDJSON into (events, result).

    Read like the codex host reads its own stream: a line that does not start
    with `{`, a `{` line that does not decode, and a non-dict payload are
    skipped; `result` is the payload dict of the LAST `{"event":"result"}`
    line, or None. Framing is `"\\n"` ONLY (r1/R7): `str.splitlines()` also
    breaks on U+2028 / U+2029 / U+0085, which V8 does not escape in JSON
    strings, so a complete answer would be cut in half. A duplicate member
    anywhere in a line raises `_DuplicateJSONMember(key, line_no)` and the
    whole stream is refused (spec C14 / R-BIND), never edited.
    """
    events: list = []
    result = None
    for line_no, line in enumerate((text or "").split("\n"), 1):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line, object_pairs_hook=_reject_duplicate_pairs)
        except _DuplicateJSONMember as e:
            raise _DuplicateJSONMember(e.key, line_no) from None
        except (RecursionError, ValueError):
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


def _agy_tool_name(info, su) -> str:
    """Vendor-controlled tool name — type-guarded and capped (r1/R3 + R6)."""
    for cand in (info.get("name") if isinstance(info, dict) else None,
                 su.get("tool_name") if isinstance(su, dict) else None):
        if isinstance(cand, str) and cand:
            return cand[:_AGY_DIGEST_KEY_CAP]
    return "?"


# A tool step is a DENIAL when its state is ERROR and the FIRST LINE of
# `tool_info.error.message` STARTS with one of these — the vendor's own
# headless permission denial ("User denied permission to run command:\n<the
# model's command line>") or a PreToolUse hook's refusal ("tool call denied
# by pre-tool hook: <reason>", measured 2026-09-17 on agy 1.2.5; the run stays
# SUCCESS and the call never executes). ANCHORED on purpose (S2 gate r1, codex
# C3 + agy A1, two families): typed error messages echo model-authored
# arguments AFTER a newline (r2/N2), and a diagnostic can QUOTE the phrase
# mid-message ("command exited 1: sh: echo denied by pre-tool hook …") — such a
# call RAN, its effect is unknown, and it must stay an ordinary error.
_AGY_DENIAL_PREFIXES = ("tool call denied by pre-tool hook",
                        "user denied permission")
# The vendor's headless denial as CAPTURED (docs/spikes/2026-08-22-agy-
# permission-ladder/out/*.stream.jsonl; S2 gate r2, claude): `permission check
# failed for <verb> "<arg>": user denied permission …` — the model-authored
# argument sits INSIDE the quotes, so the head is judged at position 0 and
# the denial tail AFTER the last double quote; a quoted phrase cannot forge it.
_AGY_PERMISSION_HEAD = "permission check failed for "
# EVERY captured tail (S2 gate r3, codex): the headless user denial and the
# retired v1.2 settings deny-rule shape (`Permission denied for <verb>(…).
# Matches user-configured deny rule.`, ladder F4 + G). A head followed by any
# other tail (#826 `invalid_args`) is not a denial.
_AGY_PERMISSION_TAILS = ("user denied permission", "permission denied for")


def _agy_step_denied(su) -> bool:
    """True when a tool `step_update` is a DENIAL: state ERROR and the first
    line of its error message starts with a `_AGY_DENIAL_PREFIXES` phrase
    (case-insensitive, leading blanks ignored). ONE predicate, shared by the
    digest fold below (`denied` list, read_attempts outcome `denied`) and the
    antigravity wrapper's admission census (a denied off-list call is BLOCKED
    — logged, not voiding — while an executed one still voids). Type-guarded:
    a non-dict step / info / error, a non-string message, or any state but
    ERROR (a DONE step carrying a denial-shaped error RAN) is not a denial."""
    if not isinstance(su, dict) or su.get("state") != "ERROR":
        return False
    info = su.get("tool_info")
    err = info.get("error") if isinstance(info, dict) else None
    msg = err.get("message") if isinstance(err, dict) else None
    if not isinstance(msg, str):
        return False
    first = _agy_first_line(msg).lower()   # first NON-EMPTY line (r3/G5 shape)
    if first.startswith(_AGY_DENIAL_PREFIXES):
        return True
    if first.startswith(_AGY_PERMISSION_HEAD):
        # after the LAST `": ` — the tail echoes the argument, which may itself
        # carry a double quote (S2 gate r3, claude); a bare last-quote split
        # landed inside that echo
        tail = first.rsplit('": ', 1)[-1] if '": ' in first else ""
        return tail.startswith(_AGY_PERMISSION_TAILS)
    return False


def _agy_tool_class(name: str) -> str:
    """Coarse class of an agy tool name — `read` / `write` / `command` /
    `web` / `other` (r2/C5). Recorded on every read_attempts entry so a
    consumer can tell an attempted PACKET READ from a blocked write or
    command that merely named the same path."""
    for label, names in _AGY_TOOL_CLASSES:
        if name in names:
            return label
    return "command" if name == "run_command" else "other"


def _agy_conversation_ids(values) -> tuple:
    """(ids, omitted) — the ORDERED, DEDUPED vendor conversation ids among
    `values`, bounded by the list cap (gate-1 r13 row r13-2, spec case C23).

    The hook load check attributes each PreToolUse hook row to the run that
    made it BY THIS ID, so an id is recorded WHOLE or not at all: a
    non-string or empty value is ignored, and an id longer than the value cap
    is never truncated (a truncated id is a DIFFERENT id and would attribute
    nothing) — it is counted in `omitted` with the ids beyond the list cap.
    Transport only: the wrapper records what the stream says and validates
    nothing."""
    ids: list = []
    seen: set = set()
    over = 0
    for v in values:
        if not isinstance(v, str) or not v or v in seen:
            continue
        seen.add(v)
        if len(v) > _AGY_DIGEST_VALUE_CAP or len(ids) >= _AGY_DIGEST_LIST_CAP:
            over += 1
            continue
        ids.append(v)
    return ids, over


def _agy_runtime_models(values) -> tuple:
    """(models, omitted) — the ORDERED, DISTINCT exposed models among
    `values` (R-MODEL): only a non-blank string counts, each is capped like
    every other vendor string, and the list is capped like the conversation
    ids, the overflow counted in `omitted`. Report only: which value
    contradicts a request is the wrapper's decision."""
    models: list = []
    over = 0
    for v in values:
        if not isinstance(v, str) or not v.strip():
            continue
        v = v[:_AGY_DIGEST_VALUE_CAP]
        if v in models:
            continue
        if len(models) >= _AGY_DIGEST_LIST_CAP:
            over += 1
            continue
        models.append(v)
    return models, over


def digest_agy_stream(events: list, result=None) -> dict:
    """Fold a parsed event list into a bounded, deterministic read-audit
    digest. REPORT-ONLY: no policy, no judgment — the caller (leader /
    review SKILL) decides what a missing packet-read means. Each tool call
    is counted once, on its terminal DONE/ERROR update (ACTIVE skipped).

    OUTCOME FIDELITY (r1/R1): `files_read` / `web` record only tool calls that actually SUCCEEDED — terminal state DONE with
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

    `runtime_models` (R-MODEL, owner ruling Q10-2): the ordered DISTINCT
    non-blank `init.model` strings the vendor exposed in this attempt
    (`_agy_runtime_models`; `runtime_models_omitted` when the list cap
    overflows); OMITTED when no `init` event exposes one — never inferred.
    """
    files_read: list = []
    runtime_models: list = []
    denied: list = []
    web: list = []
    read_attempts: list = []
    tool_steps = 0
    error_steps = 0
    # WHOSE run this was (gate-1 r13 row r13-2, spec case C23): the vendor
    # conversation id on the `init` event (top level) and on EVERY
    # `step_update` — MEASURED 2026-09-26 to be the id the PreToolUse hook
    # logs. Collected before any step filter, so a run whose only call was a
    # `finish` or a hook-denied prompt-shaped call still records its id.
    conv_seen: list = []
    for ev in events or []:
        if isinstance(ev, dict) and ev.get("event") == "init":
            conv_seen.append(ev.get("conversation_id"))
            init = ev.get("init")
            model = init.get("model") if isinstance(init, dict) else None
            if isinstance(model, str) and model.strip():
                runtime_models.append(model)
        su = ev.get("step_update") if isinstance(ev, dict) else None
        if not isinstance(su, dict):
            continue
        conv_seen.append(su.get("conversation_id"))
        stype = su.get("step_type")
        state = su.get("state")
        state_s = state if isinstance(state, str) else ""
        if stype == "error_message":
            error_steps += 1
            continue
        # Only a terminal `step_type: tool` update is a tool step; the
        # `finish` terminal (step_type `finish`) is not counted as one.
        if stype != "tool" or state_s == "ACTIVE":
            continue
        info = su.get("tool_info")
        if not isinstance(info, dict):
            info = {}
        name = _agy_tool_name(info, su)
        params = info.get("parameters")
        hint = _agy_params_hint(params)
        tool_steps += 1
        err_present = bool(info.get("error"))
        if state_s == "ERROR":
            error_steps += 1
        is_denied = _agy_step_denied(su)
        if is_denied:
            denied.append({"tool": name, "params": hint})
        if state_s == "DONE" and not err_present:
            if name in _AGY_READ_TOOLS:
                files_read.append({"tool": name, "params": hint})
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
    # files_read did, so a truncated denied/web list looked complete to the
    # leader).
    for key, values in (("files_read", files_read), ("denied", denied),
                        ("web", web), ("read_attempts", read_attempts)):
        digest[key] = values[:_AGY_DIGEST_LIST_CAP]
        digest[key + "_omitted"] = max(0, len(values) - _AGY_DIGEST_LIST_CAP)
    # ALWAYS present, possibly empty: "recorded none" must read differently
    # from an older audit that has no key at all.
    digest["conversation_ids"], digest["conversation_ids_omitted"] = \
        _agy_conversation_ids(conv_seen)
    models, over = _agy_runtime_models(runtime_models)
    if models:
        digest["runtime_models"] = models
    if over:
        digest["runtime_models_omitted"] = over
    if isinstance(result, dict):
        # r2/C3: the vendor `status` feeds every per-attempt census row on a
        # leader-visible line — capped like `outcome`; a non-string is None.
        status = result.get("status")
        digest["status"] = (status[:_AGY_DIGEST_KEY_CAP]
                            if isinstance(status, str) else None)
    return digest


def _agy_entry_key(v) -> str:
    """Order-stable identity for a digest list entry, for dedupe (r2/C4).
    Entries are bounded dicts (`{tool, params, ...}`), so a canonical JSON
    rendering is a total, cheap key;
    anything unexpected falls back to `repr` rather than raising."""
    try:
        return json.dumps(v, sort_keys=True, ensure_ascii=True, default=str)
    except (TypeError, ValueError):
        return repr(v)


def merge_agy_digests(digests) -> Optional[dict]:
    """Aggregate per-ATTEMPT digests into ONE bounded read-audit record (r1/R4).

    The driver retries (server-capacity backoff, schema repair) and each
    attempt produces its own digest. Emitting only the LAST
    one let a short-circuiting retry CONCEAL the earlier attempt's evidence —
    a leg that demonstrably read the review packet on attempt 1 reported zero
    reads, which the review SKILL's mechanical gate treats as a VOID leg. The
    aggregate unions every attempt's lists (no evidence lost, DEDUPED in
    first-seen order per r2/C4 so a path re-read on every retry cannot consume
    the cap), and carries a bounded per-attempt census under `attempts`
    (each attempt's own pre-dedupe totals and `status`). Returns None for an
    empty input (no completed vendor call ⇒ no digest, as before). `runtime_models` rides each
    `attempts[]` row (omit-when-empty); the top level carries the ordered
    distinct union. Which attempt is judged against a request is the
    wrapper's decision.
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
    # The UNION of every attempt's conversation ids (gate-1 r13 row r13-2),
    # bounded like the lists above; each attempt's own ids ride on its
    # `attempts[]` row below, which is what the hook load check attributes.
    conv_all: list = []
    conv_omitted = 0
    for d in items:
        vals = d.get("conversation_ids")
        conv_all.extend(vals if isinstance(vals, list) else [])
        conv_omitted += int(d.get("conversation_ids_omitted") or 0)
    merged["conversation_ids"], over = _agy_conversation_ids(conv_all)
    merged["conversation_ids_omitted"] = conv_omitted + over
    exposed: list = []
    models_omitted = 0
    for d in items:
        vals = d.get("runtime_models")
        exposed.extend(vals if isinstance(vals, list) else [])
        models_omitted += int(d.get("runtime_models_omitted") or 0)
    models, over = _agy_runtime_models(exposed)
    if models:
        merged["runtime_models"] = models
    if models_omitted + over:
        merged["runtime_models_omitted"] = models_omitted + over
    attempts = []
    for i, d in enumerate(items[:_AGY_DIGEST_ATTEMPT_CAP]):
        entry: dict = {"attempt": i + 1, "status": d.get("status"),
                       "tool_steps": d.get("tool_steps", 0),
                       "error_steps": d.get("error_steps", 0)}
        # WHICH attempt's transcript was a prefix (gate-1 r6 row r6-1). The
        # driver stamps the engine's reader outcome onto each attempt's own
        # digest, so a merged audit can never present a knowingly incomplete
        # earlier attempt as ordinary evidence. Omit-when-DEFAULT.
        if d.get("capture_complete") is False:
            entry["capture_complete"] = False
        # WHETHER this attempt's transcript was CUT MID-LINE (gate-1 r9 row
        # r9-10). Same omit-when-default rule: a cut tail does not refuse
        # the attempt, so the merged audit is the only place a reader can
        # see that the transcript stops short of the vendor's last event.
        if d.get("truncated_tail"):
            entry["truncated_tail"] = True
        # WHETHER this attempt's run was INTERRUPTED (gate-1 r17 row r17-1):
        # the driver stamps `timeout` (the wrapper killed it at its deadline)
        # or `signal` (a negative vendor rc). Same omit-when-default rule: a
        # transcript that ends on a line boundary carries neither marker
        # above, and this is what tells a reader it is a known prefix.
        if d.get("interrupted"):
            entry["interrupted"] = d["interrupted"]
        if isinstance(d.get("runtime_models"), list) and d["runtime_models"]:
            entry["runtime_models"] = d["runtime_models"]
        if d.get("runtime_models_omitted"):
            entry["runtime_models_omitted"] = d["runtime_models_omitted"]
        for key in _AGY_DIGEST_LISTS:
            vals = d.get(key)
            entry[key] = (len(vals) if isinstance(vals, list) else 0) \
                + int(d.get(key + "_omitted") or 0)
        # THIS attempt's own conversation ids (gate-1 r13 row r13-2, spec
        # case C23) — ALWAYS present, possibly empty, so the hook load check
        # can attribute hook rows to the run that made them. The omitted
        # count follows the omit-when-default rule of this row.
        vals = d.get("conversation_ids")
        entry["conversation_ids"], over = _agy_conversation_ids(
            vals if isinstance(vals, list) else [])
        over += int(d.get("conversation_ids_omitted") or 0)
        if over:
            entry["conversation_ids_omitted"] = over
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


def agy_classify_signals(result) -> list:
    """The failure text classify() reads from an agy stream: the ONE measured
    carrier, the result-level `error` (its `message` when a dict).

    Its first non-empty stripped line, capped at `_AGY_DIGEST_VALUE_CAP` — a
    typed error echoes model-authored text after a newline. A finish-schema
    validation report is model text (R-CLASSIFY): only the first line agy's
    sign-in banner begins is forwarded, else nothing. Step-level and tool-level
    error text never reaches classify() (no capture shows a vendor class
    there); the raw stream stays in the run-log for diagnostics.
    """
    err = result.get("error") if isinstance(result, dict) else None
    msg = err.get("message") if isinstance(err, dict) else err
    if not isinstance(msg, str):
        return []
    head = _agy_first_line(msg)
    if _AGY_SCHEMA_REPORT_RE.match(head):
        for ln in msg.split("\n"):
            if _agy_banner_line(ln):
                return [ln.strip()[:_AGY_DIGEST_VALUE_CAP]]
        return []
    return [head[:_AGY_DIGEST_VALUE_CAP]] if head else []


def _agy_no_answer_blob(stderr: str, signals: list, status) -> str:
    """The classify() stderr of an agy run with no usable answer: stderr + each
    typed stream signal LABELLED (so it never starts a line and cannot
    impersonate agy's own stderr banner) + a synthetic result-status token.
    Never the raw stream: it carries the reviewed content (r1/R2). One builder
    for the driver and for `reclassify_run_record`."""
    status_tok = f"agy result status={str(status)[:200]}" if status else ""
    parts = [stderr, *[f"[agy signal] {t}" for t in (signals or []) if t], status_tok]
    return "\n".join(t for t in parts if t and t.strip())


def _agy_no_answer_class(stderr: str, signals: list, status, stdout: str,
                         vendor_exit_code) -> str:
    """The agy driver's no-usable-answer decision — the one copy, used by the
    driver (`antigravity_wrapper._classify_no_answer`) and by
    `reclassify_run_record`. Nothing structural to classify at vendor exit 0
    is extraction-error; a nonzero exit still goes through classify() so the
    extension's vendor-exit map keeps its say. `stdout` (the raw stream)
    reaches classify() only for its auth rung."""
    blob = _agy_no_answer_blob(stderr, signals, status)
    if not blob.strip() and vendor_exit_code == 0:
        return "extraction-error"
    return classify("antigravity", stderr=blob, stdout=stdout,
                    exit_code=EXIT_CLI_FAIL, vendor_exit_code=vendor_exit_code)


# ─── Retry policy ─────────────────────────────────────────────────────────
SERVER_CAP_BACKOFF_S: tuple[int, ...] = (15, 45)
SERVER_CAP_MAX_RETRIES = len(SERVER_CAP_BACKOFF_S)


# ─── Audit rotation policy ────────────────────────────────────────────────
# audit.jsonl is append-only operational telemetry. After an append that takes
# the active file past AUDIT_ROTATE_BYTES it is rotated, and at that rotation the
# oldest archives past AUDIT_MAX_ARCHIVES / AUDIT_ARCHIVE_MAX_BYTES per CLI are
# deleted (a failed delete is skipped).
# The per-call run-log remains the detailed IPC artifact; audit is durable
# routing telemetry.
AUDIT_ROTATE_BYTES = 10 * 1024 * 1024  # 10 MB
AUDIT_MAX_ARCHIVES = 5
AUDIT_ARCHIVE_MAX_BYTES = AUDIT_ROTATE_BYTES * AUDIT_MAX_ARCHIVES


# ─── Run-log policy (per-execution artifact, dispatch-SKILL input) ────────
# Separate from audit.jsonl: one file per FAILED call (rc != 0) at
# _logs/<cli>/runs/<UTC-ts>-<pid>-<uuid8>.json — successes never dispatch the
# repair agent, so no file (a review attempt writes one for every call, under
# its own TRIAD_REVIEW_LOG_DIR). The dispatch SKILL passes only the PATH in the
# agent prompt and the agent fetches it with its Read tool, isolating large
# vendor stdout / non-ASCII / special-char escaping from prompt transport.
# Nothing outside this code deletes a run-log (R-CLEANUP); two coded layers do:
#   the next-run sweep (`prune_stale_run_logs`, the role's age floor) and
#   the cap prune (`_prune_run_logs`, oldest first past these caps, never a
#   file younger than the floor).
_RUN_LOG_MAX_FILES = 100
_RUN_LOG_MAX_BYTES = 20 * 1024 * 1024  # 20 MB total cap


@dataclass
class RunResult:
    exit_code: int                  # wrapper-normalized (0/1/2/3/4/64/65/66)
    stdout: str
    stderr: str
    elapsed_s: float
    classification: str = "ok"
    mode: str = "normal"            # normal | schema_repair
    # Final-answer + schema layer
    final_answer: str = ""
    validated: Optional[dict] = None
    schema_repair_attempt: int = 0
    extraction_error: Optional[str] = None
    validation_error: Optional[str] = None
    # Vendor raw exit code — the repair agent's web-search key for unobserved codes.
    vendor_exit_code: int = -1
    # Antigravity stream-json read-audit digest (Task 6) — None for every other
    # CLI/wrapper (zero behavior change); the antigravity driver sets it on
    # every completed vendor call.
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
    # forensic value, and the pre-spawn stdin UTF-8 refusal, which names the
    # directory the child WOULD have run in). None only on a RunResult
    # constructed OUTSIDE _run_once (a pre-engine guard failure); the
    # audit/run-log key is then OMITTED (vendor_version shape rule). Never fed
    # back into Popen(cwd=...) — os.getcwd() returns the PHYSICAL path, which
    # would silently change a symlinked-cwd child's view.
    effective_cwd: Optional[str] = None
    # stdin prompt delivery outcome (codex maintainer handoff, 2026-09-18):
    # None for every non-stdin caller (gemini/agy — key OMITTED on the
    # audit/run-log records, same shape rule as vendor_version), otherwise
    # "complete" (write + flush finished), "failed:<ExceptionClass>" (write,
    # flush or pre-spawn UTF-8 encode raised — the CLASS name only, never the
    # prompt bytes) or "unconfirmed" (the writer had not finished within the
    # bounded join after the child terminated). A success-shaped rc 0 whose
    # delivery is not "complete" is refused by _run_once (exit 65,
    # classification input-delivery-failed) — a successful write proves
    # TRANSPORT progress only, never that the vendor processed every byte.
    stdin_delivery: Optional[str] = None
    # ─── Common transport receipt inputs (spec C9/C10, R-RECEIPT) ───────────
    # Caller-supplied dispatch attempt number (`--attempt`, default 1). RECORDED,
    # never interpreted: the wrapper does not retry on it and no control flow
    # reads it — it exists so a cross-host reader can join a wrapper record to
    # the round/attempt the caller allocated.
    dispatch_attempt: int = 1
    # Absolute path the --prompt-file argument resolved to (C28), or None when
    # the prompt came from argv text. Audit/run-log key OMITTED when None (the
    # vendor_version shape rule); masked under hardened redaction.
    prompt_file_resolved: Optional[str] = None
    # The model slug the caller REQUESTED (codex `--model`, spec C35 / shared
    # dev log DL-3), or None when none was requested (= the CLI's config
    # default; the round record freezes the roster value as null). RECORD-ONLY:
    # never a runtime identity (codex exposes none) and never inferred. Audit /
    # run-log key OMITTED when None; NOT redacted — a catalog slug is not
    # prompt-bearing (the vendor_version class).
    requested_model: Optional[str] = None
    # The reasoning / effort tier the caller REQUESTED (codex `--reasoning`,
    # agy `--effort`; spec C35 as amended), or None when none was
    # requested. Same RECORD-ONLY, omit-when-None, unredacted shape as
    # requested_model.
    requested_reasoning: Optional[str] = None
    # The model the vendor EXPOSED at runtime (agy stream `init.model`,
    # R-MODEL / DL-9): the contradicting value when the run is refused, else
    # the admitted (last) attempt's first exposed value; None when that
    # attempt exposed none — never inferred from the request. Same
    # omit-when-None, unredacted record shape as requested_model.
    runtime_model: Optional[str] = None
    # False only when NO vendor process was ever created for this result (the
    # pre-spawn stdin refusal and a Popen OSError). The receipt reports
    # `binary: null` + `stdin_delivery: not-started` in that case — a path that
    # never ran must never claim a binary. Results built outside _run_once keep
    # the True default (their `cmd[0]` is the binary the caller did invoke).
    spawned: bool = True
    # False when a reader raised or outlived its bounded join: the capture is a
    # prefix. Internal; also stamped per agy attempt.
    capture_complete: bool = True


# ─── Helpers ──────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """One diagnostic line on stderr (A4 / R-TERMINAL): a failed write drops
    that line (or its rest), never the answer or the exit, and a dropped line
    is never written later — it goes straight to the descriptor, no buffered
    stream holds it; a stderr closed at start drops every line. A full
    non-blocking pipe drops the line at once and a blocking pipe nobody drains
    blocks — both recorded limits. Encoded with backslashreplace. A stream
    with no descriptor (an in-process harness's text object) gets the line
    through its own write."""
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}\n"
    stream = sys.stderr
    try:
        fd = stream.fileno()
    except (AttributeError, OSError, ValueError):   # None (fd 2 closed) or no descriptor
        try:
            stream.write(line)
        except (AttributeError, OSError, ValueError):
            pass
        return
    try:
        stream.flush()   # text a caller already wrote keeps its order
    except (OSError, ValueError):
        pass
    data = line.encode(getattr(stream, "encoding", None) or "utf-8", "backslashreplace")
    while data:
        try:
            data = data[os.write(fd, data):]   # a partial write is continued
        except OSError:   # a full pipe, a closed reader, a full disk: the rest is dropped
            return


def _emit_payload(data: bytes) -> None:
    """Write the answer BYTES to stdout and flush.

    `sys.stdout` is flushed first so anything a caller already wrote as text
    keeps its order. A harness that replaced `sys.stdout` with a text object
    has no `.buffer`; there the bytes are decoded back, which is what an
    in-process caller asked for."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(data.decode("utf-8", errors="replace"))
        sys.stdout.flush()
        return
    sys.stdout.flush()
    buffer.write(data)
    buffer.flush()


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
    so classify() can never raise on it. The file is parsed on each call, and an
    ignored entry is reported in one line per load."""
    p = _classifier_extension_path()
    try:
        data = json.loads(p.read_bytes().decode("utf-8"))
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
            cleaned["vendor_exit_map"] = {}
            for k, v in vmap.items():
                if not isinstance(v, str):
                    continue
                # R-TOKENS / C8 (26a final fix 1, F6): only the classes the applier
                # allows for an exit-code proposal — any other token would record a
                # pair the summary's exit contradicts
                if v not in VENDOR_EXIT_PROPOSAL_CLASSES:
                    log(f"[wrapper] {cli}: classifier extension vendor_exit_map {k!r}: "
                        f"{v!r} is no exit-code proposal class — entry ignored")
                    continue
                try:
                    if int(k) <= 0:
                        log(f"[wrapper] {cli}: classifier extension vendor_exit_map {k!r}: "
                            f"exit code <= 0 is never a failure code — entry ignored")
                        continue
                except (TypeError, ValueError):
                    pass
                cleaned["vendor_exit_map"][k] = v
        pats = entry.get("patterns")
        if isinstance(pats, dict) and "OAUTH_ENV_PATTERNS" in pats:
            # R-AUTH: no raw-text authentication phrase is kept (a raw-text
            # `401 unauthorized` produced a MEASURED false STOP); the STOPs come
            # only from the structured carriers. The list is ignored, one line per load.
            log(f"[wrapper] {cli}: classifier extension OAUTH_ENV_PATTERNS ignored — "
                f"no raw-text authentication phrase is kept")
            pats = {k: v for k, v in pats.items() if k != "OAUTH_ENV_PATTERNS"}
        if isinstance(pats, dict):
            cleaned["patterns"] = {
                # the applier's own normalization (apply_classifier_patch):
                # lowercased FIRST, then >= _MIN_SUBSTRING_LEN chars, some
                # alphanumeric — a hand-edited short / blank entry would match
                # everything (a substring list) or every line (a line-start
                # list): dropped
                name: [low for s in lst if isinstance(s, str)
                       if len(low := s.lower()) >= _MIN_SUBSTRING_LEN
                       and any(ch.isalnum() for ch in low)]
                for name, lst in pats.items()
                if isinstance(lst, list)
            }
        if cleaned:
            clean[cli] = cleaned
    return clean


# ─── Product hardening mode (L8 twin→SoT port, owner adjudications 2026-07-05) ───
# The lab (SoT callers, skill contracts) runs UNRESTRICTED by default; the
# claude-host installer sets TRIAD_WRAPPER_HARDENED=1, which activates
# allowed-roots containment (required) and audit prompt redaction. Each control
# also has an individual env so it can be engaged on its own (set
# TRIAD_WRAPPER_ALLOWED_ROOTS to enforce
# containment; TRIAD_AUDIT_REDACT_PROMPTS=1 to redact) — per-product defaults,
# one engine.

def _wrapper_hardened() -> bool:
    return os.environ.get("TRIAD_WRAPPER_HARDENED") == "1"


def _audit_redact_enabled() -> bool:
    return _wrapper_hardened() or os.environ.get("TRIAD_AUDIT_REDACT_PROMPTS") == "1"


# The investigation clause `web-evidence` (spec C29, R-INVEST) has ONE source:
# the vendored review library renders it. Located from this module's own
# directory — plugin layout first (`bin/`), then the source tree (two levels
# below the repository root).
_PROMPTS_V2_CANDIDATES = (
    "../skills/triad-cross-family-review/lib/prompts_v2.py",
    "../../.claude/skills/triad-cross-family-review/lib/prompts_v2.py",
)


@functools.lru_cache(maxsize=None)
def _investigation_clause(route: str) -> str:
    """The `web-evidence` clause a `--web` dispatch on `route` (agy / gemini)
    appends, as `prompts_v2.render_investigation_clause(route)` renders it.
    Loaded only when called (a dispatch without --web never reads the file).
    RuntimeError names the path(s) tried when the library is missing or
    unreadable or the clause set does not render; the caller refuses
    `config-conflict` before the spawn."""
    import importlib.util
    here = Path(__file__).resolve().parent
    tried = [str(here / rel) for rel in _PROMPTS_V2_CANDIDATES]
    path = next((p for p in tried if os.path.isfile(p)), None)
    if path is None:
        raise RuntimeError("the web-evidence clause library prompts_v2.py is missing "
                           f"(tried {', '.join(tried)}) — reinstall the plugin")
    spec = importlib.util.spec_from_file_location("_triad_prompts_v2", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # its dataclasses resolve the module by name
    try:
        spec.loader.exec_module(mod)
        return mod.render_investigation_clause(route)
    except (OSError, SyntaxError, ImportError, getattr(mod, "PromptSpecError", OSError)) as e:
        raise RuntimeError(f"the web-evidence clause cannot be rendered from {path}: "
                           f"{e} — reinstall the plugin") from e


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
        try:
            path = Path(item).expanduser()
        except RuntimeError:   # `~<no-such-user>` (C28: the same reason as an argument)
            raise ValueError("TRIAD_WRAPPER_ALLOWED_ROOTS entry cannot be resolved "
                             "(no such home directory)") from None
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
    try:
        roots = runtime_allowed_roots()
    except (ValueError, OSError, RuntimeError) as e:   # a roots-config fault (C28)
        cause = (str(e) if isinstance(e, ValueError) else "TRIAD_WRAPPER_ALLOWED_ROOTS "
                 f"entry cannot be resolved ({_resolve_error(e)})")
        raise ValueError(f"{label} {_refusal_path(resolved, label)}: {cause}") from None
    if not roots:
        return resolved          # lab default: no containment
    if not any(_path_is_within(resolved, root) for root in roots):
        # C28: name the candidate; under the redaction mode the candidate and
        # the roots are masked like every other refusal path.
        if _audit_redact_enabled():
            raise ValueError(f"{label} {_refusal_path(resolved, label)} must be under "
                             f"an allowed runtime root (roots masked)")
        allowed = ", ".join(str(root) for root in roots)
        raise ValueError(f"{label} {resolved} must be under an allowed runtime root: "
                         f"{allowed}")
    return resolved


# Process-ENTRY working directory (C28, owner directive 2026-09-19). Captured
# ONCE at import, before any wrapper code can chdir, so a relative --prompt-file
# / --cwd always resolves against the directory the operator actually launched
# the wrapper from — never against a later cwd and never against the CHILD's
# --cwd. None when the cwd was already unlinked at import (a deleted worktree):
# the relative forms then refuse, the absolute forms are unaffected.
try:
    _PROCESS_ENTRY_CWD: Optional[Path] = Path.cwd()
except OSError:  # pragma: no cover - cwd removed before the wrapper started
    _PROCESS_ENTRY_CWD = None


# C28 refusal masking (spec: "identifying the resolved candidate through the
# same masking policy"; "no unmasked-path expansion"): under the redaction mode
# a refusal names the candidate by its mask, never the given text, the resolved
# path or the process cwd. The prompt-file mask is the one the summary line and
# the audit row already use.
_REFUSAL_MASKS = {"--prompt-file": "<redacted:prompt-file>", "--cwd": "<redacted:cwd>"}


def _refusal_path(path, label: str) -> str:
    if not _audit_redact_enabled():
        return str(path)
    return _REFUSAL_MASKS.get(label, "<redacted:path>")


def _resolve_error(e: BaseException) -> str:
    """The reason a candidate could not be resolved, without its path."""
    return getattr(e, "strerror", None) or type(e).__name__


def _resolve_against_entry_cwd(raw: str, label: str) -> Path:
    """Expand `raw` and, when relative, rebase it on `_PROCESS_ENTRY_CWD`."""
    try:
        path = Path(raw).expanduser()
    except RuntimeError:   # `~<no-such-user>`: no home directory (C28)
        raise ValueError(f"{label} {_refusal_path(repr(raw), label)}: cannot be "
                         f"resolved (no such home directory)") from None
    if path.is_absolute():
        return path
    if _PROCESS_ENTRY_CWD is None:
        given = _refusal_path(repr(raw), label)
        raise ValueError(
            f"{label} {given} is relative but the wrapper's process-entry "
            f"working directory is gone — pass an absolute path")
    return _PROCESS_ENTRY_CWD / path


def resolve_prompt_file(prompt_file: str) -> Path:
    """Resolve --prompt-file to an existing, contained, absolute file path.

    C28 (owner directive 2026-09-19) SUPERSEDES the P3.b D-2 decision (spec
    3-way unanimous 2026-07-11) that a relative --prompt-file must fail loud:
    the refusal fired a third time on a real dispatch, so resolution is now
    MECHANICAL — rebase on the process-entry cwd, then run EVERY pre-existing
    validation unchanged (containment roots, existence, is_file;
    `load_prompt_text` then refuses an empty file with the same masked
    name). The hazard D-2 guarded — a reverted cwd naming a same-named WRONG
    file — is now covered by RECORDING the resolved absolute path on the
    wrapper summary line and in the audit row (`prompt_file_resolved`), so a
    mis-resolution is legible afterwards instead of being refused up front."""
    return _resolve_input_file(prompt_file, "--prompt-file")


def _resolve_input_file(raw: str, label: str) -> Path:
    """The C28 resolution of any option naming an existing input file (spec
    ccf168a: the schema-file options follow the --prompt-file rule): a relative
    path rebased on the process-entry cwd, then containment, existence and
    is_file; a refusal names the resolved candidate through the masking policy."""
    candidate = _resolve_against_entry_cwd(raw, label)
    try:
        resolved = _ensure_within_runtime_roots(candidate, label)
    except (FileNotFoundError, NotADirectoryError):
        raise ValueError(
            f"{label} {_refusal_path(candidate, label)}: not a file") from None
    except (OSError, RuntimeError) as e:   # permission / ELOOP / symlink loop
        raise ValueError(
            f"{label} {_refusal_path(candidate, label)}: cannot be resolved "
            f"({_resolve_error(e)})") from None
    if not resolved.is_file():
        raise ValueError(
            f"{label} {_refusal_path(resolved, label)}: not a file")
    return resolved


def load_prompt_text(prompt: Optional[str], prompt_file: Optional[str]) -> str:
    """Load the wrapper prompt from argv text or a UTF-8 file.

    argparse enforces the XOR at the CLI; this re-check is defense-in-depth
    for direct callers. Path resolution (incl. the C28 relative form) lives in
    `resolve_prompt_file`, which the wrappers also call directly to RECORD the
    resolved path — the return type stays a plain `str` so every existing
    caller is unchanged."""
    if prompt is not None and prompt_file:
        raise ValueError("--prompt and --prompt-file are mutually exclusive")
    if prompt is not None:
        return prompt
    if not prompt_file:
        raise ValueError("either --prompt or --prompt-file is required")
    resolved = resolve_prompt_file(prompt_file)
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:   # name the candidate, masked (C28)
        raise ValueError(f"--prompt-file {_refusal_path(resolved, '--prompt-file')}: "
                         f"{getattr(e, 'strerror', None) or type(e).__name__}") from None
    if not text.strip():   # the same refusal shape for an empty file (C28)
        raise ValueError(f"--prompt-file {_refusal_path(resolved, '--prompt-file')}: "
                         f"empty prompt")
    return text



def validate_wrapper_cwd(cwd: Optional[str]) -> Optional[str]:
    """Validate a vendor cwd without expanding the no-prompt trust boundary.

    C28: a relative --cwd is rebased on the process-entry cwd (never on
    anything the child controls), then the pre-existing containment + is_dir
    checks run unchanged and the refusal names the RESOLVED candidate."""
    if not cwd:
        return None
    candidate = _resolve_against_entry_cwd(cwd, "--cwd")
    try:
        resolved = _ensure_within_runtime_roots(candidate, "--cwd")
    except (FileNotFoundError, NotADirectoryError):
        raise ValueError(
            f"--cwd {_refusal_path(candidate, '--cwd')}: not an existing "
            f"directory") from None
    except (OSError, RuntimeError) as e:   # permission / ELOOP / symlink loop
        raise ValueError(
            f"--cwd {_refusal_path(candidate, '--cwd')}: cannot be resolved "
            f"({_resolve_error(e)})") from None
    if not resolved.is_dir():
        raise ValueError(
            f"--cwd {_refusal_path(resolved, '--cwd')}: not an existing directory")
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



# ─── Common transport receipt (shared spec C9/C10, rule R-RECEIPT) ────────
# The receipt vocabulary names the Google CLI `agy`; host A's own `cli` field
# keeps saying `antigravity`. An unmapped cli (a synthetic caller) reports
# `native`, whose contract branch forbids a binary/version.
_TRANSPORT_ROUTE_BY_CLI: dict[str, str] = {
    "codex": "codex",
    "gemini": "gemini",
    "antigravity": "agy",
}
# Routes that hand the prompt to the vendor over STDIN. Every other route
# passes it by argv (gemini `-p`, agy `-p`), where "stdin was not
# used" is the accurate statement, not "delivery unknown".
_TRANSPORT_STDIN_ROUTES: frozenset[str] = frozenset({"codex"})
TRANSPORT_BINARY_REDACTED = "<redacted:binary-path>"
PROMPT_FILE_REDACTED = "<redacted:prompt-file>"


def build_transport(
    cli: str,
    cmd: list[str],
    stdin_delivery: Optional[str],
    vendor_version: Optional[str],
    attempt: int,
    pre_spawn: bool,
) -> dict:
    """Build the common transport receipt for one wrapper record.

    Pure — no IO, no env reads. Output validates against the vendored
    `spec/contracts/receipt-fields.json` (schema_version 2) for EVERY input
    combination the wrappers can produce. Null `binary` / `cli_version` mean
    NOT OBSERVED; neither is ever inferred from a REQUEST (nothing here is
    filled from what the caller asked for; agy's stream DOES expose a runtime
    model identity on its `init` event — spec DL-9 — and the agy wrapper
    records it as `runtime_model`, so it is not a source here either). `cli_version` sources, both
    observations of the BINARY that ran: the agy wrapper's own pre-spawn
    `agy --version` probe of the resolved binary, and every gemini route
    (C16 / D-GEMINI-FLOOR-20261009 — compatibility with the older gemini CLI)
    carrying the version its floor check probed from the same resolved binary
    moments before the dispatch. A route that probes nothing (codex) keeps null.
    """
    route = _TRANSPORT_ROUTE_BY_CLI.get(cli, "native")
    if pre_spawn:
        delivery = "not-started"
    elif stdin_delivery is None:
        # A's non-stdin callers record nothing; "not-used" is only true for a
        # route that never intended stdin.
        delivery = "unexposed" if route in _TRANSPORT_STDIN_ROUTES else "not-used"
    elif stdin_delivery == "complete":
        delivery = "complete"
    elif stdin_delivery.startswith("failed:"):
        delivery = "failed"
    else:
        # "unconfirmed" — the writer was not reconciled within the bound, so
        # the outcome is genuinely not exposed. Any future A-internal token
        # lands here too rather than inventing a receipt value.
        delivery = "unexposed"
    binary: Optional[str] = None
    version: Optional[str] = None
    if route != "native":
        if not pre_spawn and cmd and isinstance(cmd[0], str) and cmd[0].strip():
            binary = cmd[0]
        if vendor_version and vendor_version.strip():
            version = vendor_version
    elif delivery not in ("not-used", "unexposed"):
        # Contract: the `native` branch admits only these two delivery values.
        delivery = "unexposed"
    return {
        "schema_version": 2,
        "stdin_delivery": delivery,
        "route": route,
        "binary": binary,
        "cli_version": version,
        "attempt": attempt if isinstance(attempt, int) and attempt >= 1 else 1,
    }


_SUMMARY_FIELD_SAFE = "/._-~+=@,:"


def _summary_field(value: str) -> str:
    """One FREE-TEXT value, escaped so it cannot forge a summary line
    (gate-1 r9 row r9-3).

    The dispatch SKILLs read the classification off this line with a GREEDY
    regex — `sed -E 's/.*\\[wrapper\\] <cli> ([a-z-]+) .*/\\1/'` — which takes
    the LAST `[wrapper] <cli> <token> ` occurrence ANYWHERE in the line. The
    tail's only free-text member is a vendor- or caller-supplied PATH, and a
    path is allowed to contain spaces and brackets, so a prompt file living
    under a directory literally named `…[wrapper] codex ok …` overrode the
    token the wrapper emitted: an `extraction-error` run parsed as
    `ok`, and the mandatory repair-agent routing never fired.

    `shlex.quote` does NOT close this — it wraps the value in single quotes
    and leaves every inner byte alone, so the forged sequence survives
    inside the quotes. Percent-escaping does: the safe set below excludes
    SPACE and `[` / `]`, so `[wrapper] <cli> <token> ` is unconstructible
    inside the field, and the whole field is ASCII (a U+2028 a
    `splitlines()` reader would honour as a line break cannot survive
    either). An ordinary POSIX path — alphanumerics plus the safe
    punctuation — is emitted BYTE-IDENTICALLY, so the C28 receipt an
    operator reads is unchanged; only an exotic path is visibly escaped, and
    the audit row keeps the raw value either way.

    THE VALUE IS FILESYSTEM BYTES, NOT TEXT (gate-1 r10 row r10-5).
    `quote()` on a `str` encodes it STRICTLY as UTF-8, and a path is bytes:
    Python hands an undecodable byte back as a lone surrogate
    (`surrogateescape`, the documented `os.fsdecode` round-trip), so a
    prompt file under such a name raised `UnicodeEncodeError` here — inside
    the summary emission, i.e. AFTER the vendor had answered and BEFORE the
    audit row and the answer were written. A completed dispatch lost its
    answer, its record and its receipt to a filename. `os.fsencode`
    reproduces the filesystem's own bytes exactly (it is the inverse of the
    decode that produced the surrogate) and `quote` percent-escapes any
    byte outside the safe set, so an ordinary POSIX path is still emitted
    byte-identically and an exotic one is escaped rather than fatal.
    """
    if isinstance(value, str):
        value = os.fsencode(value)
    return urllib.parse.quote(value, safe=_SUMMARY_FIELD_SAFE)


def _summary_tail(dispatch_attempt: int, prompt_file_resolved: Optional[str],
                  requested_model: Optional[str] = None,
                  requested_reasoning: Optional[str] = None) -> str:
    """Recorded-facts tail of the one-line `[wrapper] <cli> …` summary.

    Appended AFTER `elapsed=` so the dispatch SKILLs' prefix grep
    (`[wrapper] <cli> <classification> …`) and `tests/lib/dispatch.sh`'s sed
    extraction are unaffected. The path is escaped by `_summary_field` (row
    r9-3); the REDACTION sentinel is wrapper-authored ASCII and is emitted
    as it is. `model=` (spec C35 / DL-3) follows `prompt_file=` only when a
    model was REQUESTED; it is escaped by the same `_summary_field` and never
    redacted (a catalog slug is not prompt-bearing). Absent = the CLI's config
    default was used. `reasoning=` (C35 as amended) follows `model=` only when
    a reasoning / effort tier was REQUESTED, escaped and unredacted the same
    way."""
    tail = f" attempt={dispatch_attempt}"
    if prompt_file_resolved:
        tail += (" prompt_file="
                 + (PROMPT_FILE_REDACTED if _audit_redact_enabled()
                    else _summary_field(prompt_file_resolved)))
    if requested_model is not None:
        tail += " model=" + _summary_field(requested_model)
    if requested_reasoning is not None:
        tail += " reasoning=" + _summary_field(requested_reasoning)
    return tail


def _emit_canonical_summary(cli: str, result) -> None:
    """Re-emit the canonical one-line summary from a RunResult's CURRENT state.

    EVERY PROMOTION RE-EMITS THROUGH THIS FUNCTION (gate-1 r12 row r12-3).
    `run_cli_with_retry`'s promotions (schema-fail, the terminal classes,
    schema-rejected, the capacity give-up, extraction-error) used to
    hand-build the line WITHOUT `_summary_tail`, so the LAST line of a
    promoted result carried no `attempt=` / `prompt_file=` / `model=` and
    "absent model = the CLI default" was wrong exactly on failure paths.

    BYTE-FORMAT IDENTICAL to `_run_once`'s own line, `_summary_tail`
    included, so one grep + sed reads either emission."""
    log(
        f"[wrapper] {cli} {result.classification} "
        f"exit={result.exit_code} vendor={result.vendor_exit_code} "
        f"elapsed={result.elapsed_s:.1f}s"
        + _summary_tail(result.dispatch_attempt, result.prompt_file_resolved,
                        result.requested_model, result.requested_reasoning)
    )


def _guarded_main(cli: str, body: Callable[[dict], int]) -> int:
    """The ONE guard per wrapper (essential 3; 26a final fix 1, F1). `body(ctx)`
    is the wrapper's whole `main` — pre-dispatch probes, the run, extraction,
    payload building, classification. It fills `ctx` as it goes: `cmd`,
    `prompt`, `attempt`, `prompt_file`, `model`, `reasoning`; `result` once a
    run returned; `recorded` once its audit row is written. An Exception
    escaping it is ONE stderr line (the class, never the message — vendor
    bytes). Before the records it is a terminal record through the record
    seam: `extraction-error` / 1 after a vendor exit 0, else `unknown` / 1, with
    the summary, the audit row and the run-log. After the records (for example
    a failed stdout write) it is that one line and exit 1, and the records keep
    the run's verdict — a recorded limit (spec DL-98). SystemExit /
    KeyboardInterrupt pass through."""
    ctx: dict = {"cmd": [cli], "prompt": "", "attempt": 1, "prompt_file": None,
                 "model": None, "reasoning": None, "result": None, "recorded": False}
    try:
        return body(ctx)
    except Exception as exc:   # noqa: BLE001 — the guard itself
        log(f"[wrapper] {cli}: wrapper guard caught {type(exc).__name__}")
        if ctx["recorded"]:
            return EXIT_CLI_FAIL   # the records already carry the verdict
        why = f"wrapper guard: {type(exc).__name__}"
        result = ctx["result"]
        if not isinstance(result, RunResult):
            result = RunResult(EXIT_CLI_FAIL, "", "", 0.0, spawned=False,
                               dispatch_attempt=ctx["attempt"],
                               prompt_file_resolved=ctx["prompt_file"],
                               requested_model=ctx["model"],
                               requested_reasoning=ctx["reasoning"])
        result.classification = ("extraction-error" if result.vendor_exit_code == 0
                                 else "unknown")
        result.exit_code = EXIT_CLI_FAIL
        result.extraction_error = why
        result.final_answer = ""
        _emit_canonical_summary(cli, result)
        audit(cli, ctx["cmd"], ctx["prompt"], result)
        run_log_path = emit_run_log(cli, sys.argv, ctx["cmd"], ctx["prompt"], result)
        if run_log_path is not None:
            log(f"run-log: {run_log_path}")
        return EXIT_CLI_FAIL


def _record_transport(result: RunResult, cli: str, cmd: list[str]) -> dict:
    """build_transport() bound to a RunResult — the one shape audit() and
    emit_run_log() both write, so the two records can never drift."""
    return build_transport(
        cli,
        cmd,
        result.stdin_delivery,
        result.vendor_version,
        result.dispatch_attempt,
        pre_spawn=not result.spawned,
    )


# ── R-AUTH (ii): the authentication STOP read from the vendor's ERROR CARRIER ──
# An observed authentication failure (login missing or expired, an API-key-shaped
# credential) STOPS the attempt before any other classification of the run
# (spec R-AUTH, absolute law; R-CLASSIFY; cases C37 / C43). The shared L2 order
# below checks server-capacity before oauth-env, so an auth sentence beside a
# capacity sentence used to be retried. This rung reads ONLY the vendor's own
# error carrier — never an answer, agent message or tool output — so a phrase is
# matched where the vendor put it, not wherever a reviewed file quotes it:
#   codex   the JSONL `error` item message and the `turn.failed` error message
#           (transient retry noise only on a run that exited 0 with an
#           answer and turn.completed); and a stderr line BEGINNING
#           `Error loading configuration:`, printed before any JSONL event
#   gemini  the error object (stdout as one JSON document, any indentation; the
#           trailing stderr envelope): its message, or code 41
#           (FatalAuthenticationError's exit code, gemini CLI 0.60.0 bundle) /
#           401 (HTTP Unauthorized); a fatal TOOL error's message ("Error
#           executing tool …") is tool output — only its code is read
#   agy     the stream's `result.error`, and a stderr line BEGINNING with the
#           auth banner, built-in or the extension's (a line prefix; a banner
#           quoted mid-line does not count)
# Every carrier is split into lines on LF only (spec R-CLASSIFY fact): a bare
# CR or U+2028 inside a message is part of its line.
#   gemini  also the CLI's own exit code 41 (FATAL_AUTHENTICATION_ERROR), whose
#           message is plain stderr text with no error object (read first).
# WHAT matches inside a carrier (R-CLASSIFY, spec fcddd68 / 5ccd661): the text
# there is the vendor's, so the WHOLE authentication vocabulary is the STOP — an
# API key, unauthorized / 401, not logged in, sign in / log in (`/login`),
# authentication / credentials, an expired or unrefreshable token. The vendor
# rows of `contracts/vendor-failure-lines.json` are evidence of it, not the only
# trigger. Word-bounded, so `catalog in` / `design` never read as `log in` /
# `sign in`; an API key needs only no LETTER before it, so a variable name
# (`<VENDOR>_API_KEY`) counts. Outside a carrier this vocabulary is NEVER matched (the plain-
# fragment rule; it is in no raw-blob list). AGY_AUTH_BANNER_PATTERNS also
# counts inside a carrier.
# An api-key helper counts inside an identifier too (`apiKeyHelper`); a token
# needs its qualifier, so token-LIMIT outcomes ("max tokens", "context
# length") stay out.
_AUTH_VOCABULARY = re.compile(
    r"(?<![a-z])api[ _-]?key"
    r"|\b(?:unauthori[sz]ed|unauthenticated|401|not logged in"
    r"|log ?in|sign ?in|log ?out|authenticat\w*|credentials?"
    r"|(?:auth|access|refresh|session|bearer|oauth) token|token data"
    r"|token (?:is |has |has been )?expired|expired (?:token|session)"
    r"|session (?:has )?expired|could not be refreshed|credit balance)\b", re.I)
_CODEX_CONFIG_ERROR_PREFIX = "error loading configuration:"
_GEMINI_AUTH_ERROR_CODES = frozenset({41, 401})
_GEMINI_TOOL_ERROR_PREFIX = "error executing tool "


def _json_lines(text: str):
    """Every JSON object on its own line of `text` (undecodable lines skipped).
    Lines are split on LF only (R-CLASSIFY fact): a bare CR / U+2028 / U+2029 /
    U+0085 inside a JSON string is part of its line — V8 and serde_json emit
    them raw — and `.strip()` absorbs a trailing CR."""
    for ln in (text or "").split("\n"):
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            obj = json.loads(ln)
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict):
            yield obj


def _json_document(text: str) -> Optional[dict]:
    """`text` parsed as ONE JSON object (any indentation), or None."""
    try:
        obj = json.loads((text or "").strip())
    except (ValueError, RecursionError):
        return None
    return obj if isinstance(obj, dict) else None


def _gemini_trailing_envelope(stderr: str) -> Optional[dict]:
    """The JSON object that ENDS gemini's stderr, or None. Reverse scan with
    raw_decode: gemini nests `{"error": {...}}` (and prints it indented), so
    the last `{` starts the INNER object (L5 twin->SoT port, 2026-07-05)."""
    decoder = json.JSONDecoder()
    text = stderr or ""
    for start in reversed([i for i, ch in enumerate(text) if ch == "{"]):
        candidate = text[start:].strip()
        try:
            obj, end = decoder.raw_decode(candidate)
        except (ValueError, RecursionError):
            continue
        if candidate[end:].strip() or not isinstance(obj, dict):
            continue
        return obj
    return None


# agy's `result.error` can echo the model's text through a finish-schema
# validation report (host A's record; spec R-CLASSIFY fact): such a report is
# model text, so only agy's own sign-in banner (at a line start) is read there.
_AGY_SCHEMA_REPORT_RE = re.compile(r"^(?=.*\bschema\b)(?=.*\bvalidat)", re.I)


def _auth_phrase(cli: str, text) -> Optional[str]:
    """The authentication phrase a carrier's `text` shows, or None: the
    authentication vocabulary only (no raw-text phrase list is kept, R-AUTH)."""
    if not isinstance(text, str):
        return None
    m = _AUTH_VOCABULARY.search(text)
    return m.group(0) if m else None


def _agy_banner_line(text) -> bool:
    """True when a line of `text` (split on LF only) BEGINS with an agy sign-in
    banner — built-in or the classifier extension's learned variants."""
    ext = _load_classifier_extension().get("antigravity", {}).get("patterns", {})
    banners = (tuple(AGY_AUTH_BANNER_PATTERNS)
               + tuple(ext.get("AGY_AUTH_BANNER_PATTERNS", ())))
    return isinstance(text, str) and any(
        ln.strip().lower().startswith(banners) for ln in text.split("\n"))


def _auth_carrier_stop(cli: str, stderr: str, stdout: str,
                       vendor_exit_code: Optional[int] = None) -> bool:
    """True when the vendor's own error carrier reports an authentication failure.
    Every carrier is split into lines on LF only, like `_json_lines`."""

    def _said(*items) -> bool:
        return any(_auth_phrase(cli, t) for t in items)

    def _lines_starting(prefixes) -> list:
        return [ln for ln in (stderr or "").split("\n")
                if ln.strip().lower().startswith(prefixes)]

    if cli == "codex":
        if _said(*_lines_starting((_CODEX_CONFIG_ERROR_PREFIX,))):
            return True
        texts: list = []
        completed = failed = answered = False
        for obj in _json_lines(stdout):
            t = obj.get("type")
            if t == "error":
                texts.append(obj.get("message"))
            elif t == "turn.failed":
                failed = True
                err = obj.get("error")
                texts.append(err.get("message") if isinstance(err, dict) else err)
            elif t == "turn.completed":
                completed = True
            elif t == "item.completed":
                item = obj.get("item")
                answered = answered or (
                    isinstance(item, dict) and item.get("type") == "agent_message"
                    and isinstance(item.get("text"), str) and bool(item["text"].strip()))
        # transient retry noise only on a run that COMPLETED WITH AN ANSWER:
        # turn.completed, no turn.failed, vendor exit 0 and an agent_message
        # (codex exec exits 1 after a non-retry Error notification — codex-rs
        # exec/src/lib.rs `error_seen` — whatever turn.completed says)
        if completed and not failed and vendor_exit_code == 0 and answered:
            return False
        return _said(*texts)
    if cli == "gemini":
        # gemini's own authentication exit code (FATAL_AUTHENTICATION_ERROR,
        # gemini CLI v0.60.0 exitCodes.ts): the code IS the carrier — its
        # message is plain stderr text with no error object (R-AUTH (ii)).
        # Judged before the timeout verdict too, and on a signalled run.
        if vendor_exit_code == 41:
            return True
        doc = _json_document(stdout)
        # a gemini envelope has no top-level `type` (a codex event does)
        objs = [o for o in ([doc] if doc is not None else list(_json_lines(stdout)))
                + [_gemini_trailing_envelope(stderr)]
                if isinstance(o, dict) and "error" in o and "type" not in o]
        for o in objs:
            err = o["error"]
            if isinstance(err, dict):
                code = err.get("code")
                if (isinstance(code, int) and not isinstance(code, bool)
                        and code in _GEMINI_AUTH_ERROR_CODES):
                    return True
                err = err.get("message")
            # a fatal TOOL error rides the same object as "Error executing tool
            # <name>: …" (gemini CLI 0.60.0 handleToolError) — that text is tool
            # output, so only the object's code is read for it
            if isinstance(err, str) and err.lstrip().lower().startswith(
                    _GEMINI_TOOL_ERROR_PREFIX):
                continue
            if _said(err):
                return True
        return False
    if cli == "antigravity":
        # the banner (built-in + the extension's learned variants) counts on a
        # stderr line that BEGINS with it (a quoted banner inside another line
        # does not)
        if _agy_banner_line(stderr):
            return True
        for obj in _json_lines(stdout):
            res = obj.get("result") if obj.get("event") == "result" else None
            err = res.get("error") if isinstance(res, dict) else None
            err = err.get("message") if isinstance(err, dict) else err
            # C74: the permission-denied result error embeds the model's command
            # (a quoted banner included) — never authentication evidence
            if isinstance(err, str) and _agy_first_line(err).startswith(_AGY_PERMISSION_HEAD):
                continue
            if isinstance(err, str) and _AGY_SCHEMA_REPORT_RE.match(_agy_first_line(err)):
                if _agy_banner_line(err):    # a schema report: the banner only
                    return True
            elif _said(err):
                return True
    return False


def classify(
    cli: str,
    stderr: str,
    stdout: str,
    exit_code: int,
    vendor_exit_code: Optional[int],
) -> str:
    """Failure classes + ok. Layer order:
      L1 — the classifier extension's vendor_exit_map (measured raw codes)
      L2 — substring fallback (the per-class pattern lists)
      L3 — "unknown" (repair-agent dispatch signal)
    """
    if exit_code == 0:
        return "ok"
    # R-AUTH (ii) — the auth STOP read from the vendor's error carrier, FIRST
    # (before the timeout verdict, L1 and every L2 rung): no other class
    # outranks it, and a run that ended in a TIMEOUT is judged on what it
    # printed before (spec R-CLASSIFY, b8d338f).
    if _auth_carrier_stop(cli, stderr, stdout, vendor_exit_code):
        return "oauth-env"
    # A wrapper timeout is not judged by L2: a hung call's partial stderr carries capacity chatter.
    if exit_code == EXIT_TIMEOUT:
        return "timeout"
    _ext = _load_classifier_extension().get(cli, {})
    _ext_pat = _ext.get("patterns", {})
    vmap = {}
    for _k, _v in _ext.get("vendor_exit_map", {}).items():
        try:
            vmap[int(_k)] = _v
        except (TypeError, ValueError):
            pass

    def _p(name):
        """this CLI's own measured sentences for that list (`CLI_PATTERNS`,
        R-CLASSIFY) + the per-cli extension patterns."""
        return CLI_PATTERNS.get(cli, {}).get(name, ()) + tuple(_ext_pat.get(name, ()))

    # L1 — the extension's vendor_exit_map (measured raw codes only)
    if vendor_exit_code is not None and vendor_exit_code in vmap:
        return vmap[vendor_exit_code]
    # L2 — substring fallback
    # L2 order: subscription cap, capacity, token limit, schema rejected, config conflict
    # (no raw-text oauth-env rung — R-AUTH: an authentication failure outside
    # every carrier ends `unknown`).
    # agy's raw stream never enters the blob (r1/R2): its driver passes the
    # stream as `stdout` only so the auth rung above can read `result.error`.
    blob = ((stderr or "") + "\n"
            + ("" if cli == "antigravity" else (stdout or ""))).lower()
    stderr_blob = (stderr or "").lower()
    if any(p in blob for p in _p("CLI_SUB_CAP_PATTERNS")):
        return "cli-subscription-cap"
    if any(p in blob for p in _p("SERVER_CAPACITY_PATTERNS")):
        return "server-capacity"
    if any(p in blob for p in _p("TOKEN_LIMIT_PATTERNS")):
        return "token-limit"
    # schema-rejected checked LAST in L2 — capacity/terminal classes win.
    # submit-time --output-schema refusal: surfaced to caller (terminal-like),
    # NOT routed to the repair agent.
    if any(p in blob for p in _p("SCHEMA_REJECTED_PATTERNS")):
        return "schema-rejected"
    if any(p in stderr_blob for p in _p("CONFIG_CONFLICT_PATTERNS")):
        return "config-conflict"
    return "unknown"


# ─── Pydantic helpers (NEW) ───────────────────────────────────────────────

def load_pydantic_class(spec: str):
    """Parse 'module.path:ClassName' or 'module.path.ClassName' →
    pydantic BaseModel subclass.

    Raises ImportError / AttributeError / TypeError on failure.
    """
    if not PYDANTIC_OK:
        raise RuntimeError(
            f"pydantic 2.x required (found: {PYDANTIC_VERSION_FOUND or 'none'}) "
            "— install into a venv from the transferred wheel set: "
            "python3 -m venv --system-site-packages .venv && .venv/bin/pip install --no-index "
            "--find-links <wheel-dir> 'pydantic>=2,<3' "
            '(see the wrappers README section "Pydantic schema enforcement", '
            'or the plugin README\'s setup section — "Required" in English, '
            '"필수 설정" in Korean)')
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


def validate_response_detail(answer_text: str, cls) -> Tuple[bool, Any, bool]:
    """(ok, validated_dict_or_error_string, nonrepairable). `nonrepairable` is
    True only for a duplicate JSON member (spec C14 / R-BIND): every other
    validation failure takes the caller's one schema-repair retry."""
    cleaned = strip_markdown_fences(answer_text)
    # ORIGINAL-TEXT duplicate-member reject — BEFORE `model_validate_json`,
    # which shares `json.loads` last-wins semantics and so cannot see the
    # discarded half. Never repaired: a repair turn would ask the model to
    # resend the version that survived.
    dup_key = _duplicate_json_member(cleaned)
    if dup_key is not None:
        return (False,
                f"duplicate JSON member '{dup_key}' — rejected at the original "
                f"text (spec C14): a repeated member discards the first value, "
                f"so the reply cannot be read as sent",
                True)
    try:
        obj = cls.model_validate_json(cleaned)
        return True, obj.model_dump(mode="json"), False
    except Exception as e:
        return False, str(e), False


def validate_response(answer_text: str, cls) -> Tuple[bool, Any]:
    """(ok, validated_dict_or_error_string). 2-tuple façade over
    `validate_response_detail` for callers that do not drive a repair retry."""
    ok, payload, _ = validate_response_detail(answer_text, cls)
    return ok, payload


# ─── CLI-aware answer extraction (NEW) ────────────────────────────────────

def extract_codex_answer(
    stdout: str, last_msg_path: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Codex `--json` extraction. Returns (answer_text, error_or_None).

    Priority:
    1. The `-o` last-message file is the canonical answer: read FIRST, so a bad
       event line never discards a good answer (26a final fix 1, F2).
    2. Absent / empty file: `turn.failed` without `turn.completed` is
       authoritative for failure (a `turn.completed` overrides `error` events —
       codex emits retry-as-error `Reconnecting... N/5` events before an
       HTTP-fallback success).
    3. Fallback: the last `item.completed` `agent_message` in the JSONL. Only
       JSON OBJECT lines are read (`_json_lines`).
    """
    if last_msg_path and os.path.exists(last_msg_path):
        try:
            with open(last_msg_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return "", f"failed to read last_message file: {e}"
        # An empty file (rc 0 but no answer written) falls through to the
        # JSONL fallback; nothing there either -> the explicit error below.
        if content.strip():
            return content, None

    events = list(_json_lines(stdout))
    error_msg: Optional[str] = None
    saw_completed = saw_failed = False
    for obj in events:
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
    if saw_failed and not saw_completed:
        return "", error_msg or "turn.failed without message"

    for obj in reversed(events):
        item = obj.get("item")
        if (obj.get("type") == "item.completed" and isinstance(item, dict)
                and item.get("type") == "agent_message"):
            return item.get("text", ""), None
    return "", "no final answer in JSONL or last-message file"


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

    # stdout empty — the trailing JSON object in stderr (reverse-scan
    # raw_decode picks the OUTER envelope: `_gemini_trailing_envelope`).
    obj = _gemini_trailing_envelope(stderr)
    if obj is not None:
        err = obj.get("error", {})
        if isinstance(err, dict):
            return "", err.get("message", str(err))
        return "", str(err)
    return "", "empty stdout and no parseable error in stderr"


# ─── Subprocess core ──────────────────────────────────────────────────────

# Loader / interpreter injection env vars scrubbed from the vendor child (I-2/I-3).
# `_run_once` is the SINGLE vendor-child spawn site (codex/gemini/agy —
# the pre-2026-07-31 pty transport, agy's former SEPARATE spawn site, is
# deleted). It applies the scrub via the shared `scrubbed_child_env()` below,
# so a poisoned parent env cannot reach the vendor CLI (gemini/agy are
# Node runtimes; codex/agy spawn tools). The classic
# vectors: the dynamic loader (LD_PRELOAD / LD_AUDIT / the macOS DYLD_* family),
# the Node runtime (NODE_OPTIONS=--require=<evil.js> would run workspace code
# OUTSIDE any sandbox; NODE_PATH), the Python / shell / Perl / Ruby interpreters
# (PYTHONPATH / BASH_ENV / ENV / PERL5LIB / RUBYOPT ...). PATH is deliberately
# NOT scrubbed here — PATH policy belongs to the install leg.
_CHILD_ENV_SCRUB = (
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    "NODE_OPTIONS", "NODE_PATH",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
    "BASH_ENV", "ENV", "PERL5LIB", "RUBYOPT", "RUBYLIB",
)

# Vendor CREDENTIAL / ENDPOINT variables, scrubbed from the vendor child on
# EVERY route (spec cases C11 + C17, rule R-NOCOST); the model / effort user
# settings pass through (D-SELECTOR-PROPOSAL-WITHDRAWN-20261009).
#
# Why: login is the CLI's OWN OAuth login — "wrappers check the binary and never
# enter or store credentials", and "billing follows the AUTHENTICATION type, not
# the model flag". A key or a base URL left in the ambient environment would
# silently move the dispatch onto a paid API route, with nothing in the audit
# row to show it. Scrubbing is HYGIENE, NOT PROOF of the billing route (R-NOCOST
# says so in those words): the wrapper still cannot observe which credential the
# CLI finally used.
#
# One route-independent tuple rather than a per-CLI seam: a name that belongs to
# one family is inert in another family's child, and one list is one thing to
# review. Deliberately NOT scrubbed: PATH (see the note above), the CLIs' own
# config-dir pointers, and any variable that selects the APPROVED OAuth route
# (Google `GOOGLE_GENAI_USE_GCA` selects LOGIN_WITH_GOOGLE — removing it could
# DOWNGRADE a correctly configured host).
#
# Names are Tier-2 facts read from the installed CLIs on 2026-09-21, one comment
# per line; nothing here is guessed.
_CHILD_ENV_SCRUB_CREDENTIALS = (
    # ── Google (gemini CLI 0.60.0 bundle: packages/core/dist/src/core/
    # contentGenerator.js `getAuthTypeFromEnv`, and the settings loader's
    # `AUTH_ENV_VAR_WHITELIST`) ──
    "GOOGLE_API_KEY",                 # API-key auth (AUTH_ENV_VAR_WHITELIST)
    "GEMINI_API_KEY",                 # -> AuthType USE_GEMINI (api-key route)
    "GOOGLE_APPLICATION_CREDENTIALS",  # ADC service-account credential file
    "GOOGLE_GENAI_USE_VERTEXAI",      # -> AuthType USE_VERTEX_AI
    "GEMINI_CLI_USE_COMPUTE_ADC",     # -> AuthType COMPUTE_ADC
    "CLOUD_SHELL",                    # -> AuthType COMPUTE_ADC (Cloud Shell)
    "GOOGLE_CLOUD_PROJECT",           # billing project (AUTH_ENV_VAR_WHITELIST)
    "GOOGLE_CLOUD_LOCATION",          # billing region (AUTH_ENV_VAR_WHITELIST)
    "GOOGLE_GEMINI_BASE_URL",         # -> AuthType GATEWAY (endpoint override)
    "GOOGLE_VERTEX_BASE_URL",         # Vertex endpoint override
    # (gemini CLI 0.60.0 bundle, read 2026-10-04 — R-AUTH (i), C37)
    "GEMINI_DEFAULT_AUTH_TYPE",       # selects the auth type (an api-key / Vertex class among them)
    "GOOGLE_CLOUD_ACCESS_TOKEN",      # pre-issued bearer access token
    # ── agy (strings of the installed agy 1.2.16 binary, read 2026-10-04;
    # the same four names the other host removes on its formal agy route) ──
    "AGY_ADC_AUTH",                   # selects agy's ADC login ("unset AGY_ADC_AUTH" logs out)
    "GOOGLE_GENAI_USE_ENTERPRISE",    # enterprise (Vertex-class) backend selector
    "GOOGLE_CLOUD_REGION",            # billing region
    "GOOGLE_CLOUD_QUOTA_PROJECT",     # billing quota project
    # ── OpenAI / codex (strings of the installed codex native binary,
    # @openai/codex vendor/<triple>/bin/codex) ──
    "OPENAI_API_KEY",                 # API-key auth
    "CODEX_API_KEY",                  # codex-specific API-key auth
    "CODEX_ACCESS_TOKEN",             # pre-issued access token
    "OPENAI_BASE_URL",                # endpoint override
    "OPENAI_ORGANIZATION",            # billing organization selector
    "OPENAI_PROJECT",                 # billing project selector
    # ── Anthropic / claude (strings of the installed Claude Code binary
    # 2.1.271) ──
    "ANTHROPIC_API_KEY",              # API-key auth
    "ANTHROPIC_AUTH_TOKEN",           # pre-issued bearer token
    "ANTHROPIC_BASE_URL",             # endpoint override
    # (strings of the installed Claude Code binary 2.1.289, read 2026-10-04 —
    # R-AUTH (i), C37: route switches, keys, tokens, federation, profile, org)
    "CLAUDE_CODE_USE_BEDROCK",        # cloud-provider route switch
    "CLAUDE_CODE_USE_VERTEX",         # cloud-provider route switch
    "CLAUDE_CODE_USE_FOUNDRY",        # cloud-provider route switch
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",  # cloud-provider route switch
    "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",  # cloud-provider route switch
    "CLAUDE_CODE_USE_GATEWAY",        # gateway route switch
    "CLAUDE_CODE_USE_MANTLE",         # cloud-provider route switch
    "CLAUDE_CODE_API_BASE_URL",       # endpoint override
    "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",  # API key passed by descriptor
    "CLAUDE_CODE_OAUTH_TOKEN",        # pre-issued bearer token
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",  # bearer token passed by descriptor
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",  # refresh token
    "CLAUDE_CODE_GATEWAY_TOKEN",      # gateway bearer token
    "CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR",  # gateway token passed by descriptor
    "ANTHROPIC_FOUNDRY_API_KEY",      # cloud-provider API key
    "ANTHROPIC_FOUNDRY_AUTH_TOKEN",   # cloud-provider bearer token
    "ANTHROPIC_AWS_API_KEY",          # cloud-provider API key
    "AWS_BEARER_TOKEN_BEDROCK",       # cloud-provider bearer key
    "ANTHROPIC_IDENTITY_TOKEN",       # federation identity token
    "ANTHROPIC_IDENTITY_TOKEN_FILE",  # federation identity token file
    "ANTHROPIC_FEDERATION_RULE_ID",   # federation route selector
    "ANTHROPIC_SERVICE_ACCOUNT_ID",   # federation service account
    "ANTHROPIC_PROFILE",              # credential profile selector
    "ANTHROPIC_ORGANIZATION_ID",      # billing organization selector
    "ANTHROPIC_WORKSPACE_ID",         # billing workspace selector
)

# One membership set for the spawn site; the two tuples stay separate so each
# keeps its own rationale, and disjoint so no name carries two policies.
_CHILD_ENV_SCRUB_ALL: frozenset[str] = frozenset(
    _CHILD_ENV_SCRUB) | frozenset(_CHILD_ENV_SCRUB_CREDENTIALS)
assert not (set(_CHILD_ENV_SCRUB) & set(_CHILD_ENV_SCRUB_CREDENTIALS)), (
    "a variable is listed in BOTH child-env scrub tuples"
)


# The ONE route-specific exception to the shared list (R-NOCOST, DL-81, the
# other host's gemini route): the gemini CLI documents that a Workspace / Code
# Assist sign-in with Google may need a Google Cloud project set, so the project
# family reaches a GEMINI child and is removed on every other route. The shared
# tuple keeps every name; only this keep-set, keyed by the route, narrows it.
_GEMINI_ROUTE_KEEP: frozenset[str] = frozenset({
    "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_REGION", "GOOGLE_CLOUD_QUOTA_PROJECT",
})
assert _GEMINI_ROUTE_KEEP <= frozenset(_CHILD_ENV_SCRUB_CREDENTIALS)


def scrubbed_child_env(base=None, cli=None) -> dict:
    """The single-source vendor-child env: `base` (default `os.environ`) minus the
    `_CHILD_ENV_SCRUB` injection vars AND the `_CHILD_ENV_SCRUB_CREDENTIALS`
    vendor credential / endpoint vars (C11/C17/C37) — except, on
    the gemini route (`cli == "gemini"`), the `_GEMINI_ROUTE_KEEP` project
    family. Every vendor spawn and standalone probe builds its env here (C75):
    `_run_once` (the Popen dispatch site — codex/gemini/agy), the gemini
    preflight `_probe` (`cli="gemini"`) and `_probe_agy_version`, so the scrub
    policy lives in exactly ONE place.
    Returns a fresh dict (safe to mutate)."""
    src = base if base is not None else os.environ
    drop = (_CHILD_ENV_SCRUB_ALL - _GEMINI_ROUTE_KEEP if cli == "gemini"
            else _CHILD_ENV_SCRUB_ALL)
    return {k: src[k] for k in src if k not in drop}  # names first: an omitted value is never read (C75)


def _drain(stream, accum: list[str], passthrough, state: Optional[dict] = None) -> None:
    """Reader thread — line iter, accumulate, optional mirror to passthrough.

    `state`, when the caller supplies it, is that reader's completion record
    (spec R-TERMINAL / case C1): `state["done"] = True` once the stream hit
    EOF and was closed, `state["error"] = "<ExceptionClass>: <msg>"` when the
    read raised. Before 2026-09-21 the exception was ONLY logged, and
    `_run_once` never looked at the join result either — so an undecodable
    vendor byte (the pipes are strict UTF-8) ended the reader early and the
    captured PREFIX was returned as a rc-0 success. The caller adjudicates;
    this function still never raises into the thread.

    A passthrough (display-mirror) failure stays deliberately swallowed and
    is NOT recorded: R-TERMINAL distinguishes "failed to mirror for the human"
    from "failed to capture the result", and only the latter voids a run.
    """
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
        if state is not None:
            state["done"] = True
    except Exception as e:
        log(f"reader thread error: {e}")
        if state is not None:
            state["error"] = f"{type(e).__name__}: {e}"


def _kill_proc_group(proc: subprocess.Popen, pgid: Optional[int] = None) -> None:
    """SIGTERM->SIGKILL escalation against the child's own process GROUP.

    `pgid` is captured by the CALLER at SPAWN time (r1/R10) — right after
    `Popen` returns, which is after the child has already entered its own
    session (`start_new_session=True`), and while the child is still
    unreaped. Resolving it inside this function instead meant calling
    `getpgid` on a child that the very next line may already have reaped,
    i.e. reading a pgid that could have been recycled. `pgid=None` means "no
    usable group" (no group primitives on this platform, the spawn-time
    lookup failed, or the child never got its own group): the escalation then
    falls back to the DIRECT CHILD
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


# The first terminal signal this process received (spec case C1). Once the
# process has started a dispatch (`_run_once` sets `dispatch`, and it stays set
# until the process exits, so the record writers are covered too) the handler
# ONLY RECORDS the signal — the other host's shape (its `_run_once` handler,
# bin/_common.py:1402-1452). The engine observes it in its wait loop, at its
# next spawn and in its backoff sleeps, finishes the bounded group / reader
# cleanup and returns the terminal record (`unknown` / exit 1, "wrapper
# interrupted (<SIG>)"). Record-only holds from the first `_run_once`; a
# pre-dispatch vendor probe is outside a dispatch, so before the first
# `_run_once` the handler unwinds (128+signum, no record — no child exists).
_SIGNAL_STATE: dict = {"signum": None, "dispatch": False}


def _terminal_signal_to_exit(signum, frame) -> None:  # noqa: ARG001 — signal ABI
    """SIGTERM/SIGHUP handler: record the signal; unwind (128 + signum) only
    before the process's first `_run_once` (a probe is outside a dispatch)."""
    if _SIGNAL_STATE["signum"] is None:
        _SIGNAL_STATE["signum"] = signum
    if _SIGNAL_STATE["dispatch"]:
        return
    raise SystemExit(128 + signum)


def _signal_aware_sleep(seconds: float) -> None:
    """A backoff sleep that ends early once a terminal signal is recorded
    (C1): the next `_run_once` then returns the terminal record at once."""
    end = time.monotonic() + seconds
    while _SIGNAL_STATE["signum"] is None:
        left = end - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 0.1))


def _interrupted_result(signum: int, elapsed: float, stdout: str = "",
                        stderr: str = "") -> "RunResult":
    why = f"wrapper interrupted ({signal.Signals(signum).name})"
    log(f"{why}; no vendor child left running, recording the attempt as failed")
    return RunResult(EXIT_CLI_FAIL, stdout, stderr, elapsed,
                     classification="unknown", extraction_error=why,
                     capture_complete=False)


def _interrupted_previous(prev: "RunResult", signum: int) -> "RunResult":
    """A signal recorded BETWEEN attempts (C1): the driver spawns nothing more
    and returns its previous attempt's record, evidence kept (stderr / stdout,
    binary, vendor rc), marked with the failure in place."""
    why = f"wrapper interrupted ({signal.Signals(signum).name})"
    log(f"{why} between attempts; nothing more spawned, recording the "
        f"previous attempt as failed")
    prev.exit_code, prev.classification = EXIT_CLI_FAIL, "unknown"
    prev.extraction_error = why
    prev.final_answer, prev.validated, prev.capture_complete = "", None, False
    return prev


def install_terminal_signal_handlers() -> None:
    """Install the SIGTERM/SIGHUP handler `_terminal_signal_to_exit` (spec C1).

    A wrapper that dies from the DEFAULT disposition orphans the vendor child
    and everything in its process group, and writes no record. With this
    handler a signal received once the process has started its first dispatch
    is only RECORDED: `_run_once` observes it (after Popen, in its short-step
    wait, inside the timeout kill; the drivers before their next spawn), reaps the
    group with the SIGKILL escalation intact and returns `unknown` / exit 1
    ("wrapper interrupted (<SIG>)") — for codex and gemini the captured
    output goes through the auth-carrier rung first (`oauth-env` / 65 on a
    carrier STOP, gemini's exit 41 included); never retried; a signalled agy
    run's carriers are not read (a recorded limit) — and the wrapper writes its
    summary, audit row and run-log. Record-only holds from the first
    `_run_once`; a pre-dispatch vendor probe is outside a dispatch, so before
    it the handler raises `SystemExit(128 + signum)` (no child exists, no
    record). SIGKILL and SIGSTOP stay uncoverable by design.

    Call it ONCE at the top of `main()`. Not installed by `_run_once` itself:
    the signal disposition belongs to the process, and a library that mutated
    it on every call would fight an embedding caller (and `signal.signal`
    raises outside the main thread, e.g. an in-process test harness — caught
    here so the call is always safe).

    `antigravity_wrapper.py` installs its own `_terminate_to_exit`, which
    DELEGATES to `_terminal_signal_to_exit` (same record-only behaviour).
    """
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue  # platform without this signal — nothing to install
        try:
            signal.signal(sig, _terminal_signal_to_exit)
        except (ValueError, OSError):
            pass  # not the main thread / signal not settable: keep defaults


def _run_once(
    cli: str,
    cmd: list[str],
    cwd: Optional[str],
    timeout: int,
    stdin_text: Optional[str] = None,
    classify_and_log: bool = True,
    dispatch_attempt: int = 1,
    prompt_file_resolved: Optional[str] = None,
    requested_model: Optional[str] = None,
    requested_reasoning: Optional[str] = None,
) -> RunResult:
    """One Popen invocation.

    stdout = capture-only (structured JSON/JSONL — not for human stream).
    stderr = mirror to parent stderr (human progress visibility).
    stdin_text: when provided, feed via a daemon writer thread so a large
    prompt cannot deadlock against a full OS pipe before the child starts
    reading. When None (default), stdin is DEVNULL (gemini/agy behavior
    unchanged). Fail-closed contract (2026-09-18): an unencodable stdin_text
    returns EXIT_ARG_ERROR (3) BEFORE any child exists; a child that exited 0
    while delivery was not confirmed "complete" returns EXIT_TERMINAL (65) —
    both with classification "input-delivery-failed", classify() skipped and
    final_answer blank; a child with rc != 0 keeps its own classification and
    only carries the `stdin_delivery` annotation. Callers must not treat this
    seam as "exit 0 iff the child exited 0" any more.
    Terminal contract (spec R-TERMINAL / cases C1-C2, 2026-09-21): success
    ALSO requires that the owned process group was reaped (probed and reaped
    after a normal child exit) and that both output
    readers completed without error — an errored or still-running reader on a
    rc-0, non-timed-out run returns EXIT_TERMINAL (65) with classification
    "truncated-answer" and the captured PREFIX preserved for the run-log. A
    writer/reader thread that fails to START kills and reaps the child and
    returns "unknown" at EXIT_CLI_FAIL. A terminal signal received during the
    call (C1) reaps the group and returns "unknown" at EXIT_CLI_FAIL with
    extraction_error "wrapper interrupted (<SIG>)" — unless, with
    classify_and_log (codex, gemini), the captured output carries an
    auth-carrier STOP (gemini's exit 41 included): then "oauth-env" at
    EXIT_TERMINAL; never retried (agy's carriers are not read here — a recorded
    limit). Precedence: timeout >
    signal > (vendor rc 0 only) stdin delivery failure / reader incompleteness
    > vendor rc != 0 (its own class) > ok — only a timeout verdict outranks a
    signal; a delivery or reader failure is a verdict only on a rc-0 run. A
    signal recorded BETWEEN attempts is the drivers' check before their next
    `_run_once`: they hold the previous attempt and return it through
    `_interrupted_previous`.
    classify_and_log: default True keeps codex/gemini byte-identical
    (classify() + the "[wrapper] <cli> ..." summary line run here as before).
    False skips BOTH — the agy stream-json driver decides classification and
    emits its own canonical summary line later; a premature line here would
    duplicate the one the dispatch SKILL greps.
    dispatch_attempt / prompt_file_resolved / requested_model: RECORD-ONLY
    inputs for the common transport receipt (C9/C10), the C28 path record and
    the C35 requested-model record. None influences any decision here; all
    ride the RunResult to audit()/emit_run_log() and the summary tail.
    """
    effective_cwd = cwd or os.getcwd()
    _SIGNAL_STATE["dispatch"] = True   # C1: from here the handler only records
    start = time.monotonic()
    log(f"exec cwd={effective_cwd} timeout={timeout}s argv={cmd}")

    # Scrub loader/interpreter injection vars so a poisoned parent env cannot
    # reach the vendor child (I-2/I-3). Explicit env= replaces the implicit
    # full-os.environ inheritance. scrubbed_child_env() is the shared
    # single-source scrub; _run_once is the single vendor-child spawn site.
    child_env = scrubbed_child_env(cli=cli)

    # Fail CLOSED on an unencodable prompt BEFORE any child exists (codex
    # maintainer handoff 2026-09-18, requirement 1). Origin: the writer thread
    # swallowed the UnicodeEncodeError, the child saw EOF after ZERO bytes and
    # its rc 0 became a wrapper success. The diagnostic names the index and
    # the exception CLASS only — never the prompt bytes (requirement 4).
    if stdin_text is not None:
        try:
            stdin_text.encode("utf-8")
        except UnicodeEncodeError as e:
            elapsed = time.monotonic() - start
            msg = (f"stdin text is not UTF-8-encodable at index {e.start} "
                   f"({type(e).__name__}); nothing was sent")
            log(msg)
            result = RunResult(
                EXIT_ARG_ERROR, "", msg + "\n", elapsed,
                classification="input-delivery-failed",
                effective_cwd=effective_cwd,
                stdin_delivery=f"failed:{type(e).__name__}",
                dispatch_attempt=dispatch_attempt,
                prompt_file_resolved=prompt_file_resolved,
                requested_model=requested_model,
                requested_reasoning=requested_reasoning,
                spawned=False,
            )
            if classify_and_log:
                log(
                    f"[wrapper] {cli} input-delivery-failed "
                    f"exit={result.exit_code} vendor={result.vendor_exit_code} "
                    f"elapsed={elapsed:.1f}s"
                    + _summary_tail(dispatch_attempt, prompt_file_resolved, requested_model,
                                    requested_reasoning)
                )
            return result

    popen_kwargs: dict = dict(
        cwd=cwd,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=(subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL),
        text=True,
        # Explicit UTF-8 on every pipe (handoff requirement 1): text=True alone
        # takes the LOCALE's preferred encoding, so the bytes the vendor child
        # received could differ between the Mac dev host and an Ubuntu host
        # with a non-UTF-8 locale. stdin_text is already proven encodable above.
        encoding="utf-8",
        bufsize=1,
    )
    # Own session (= own process group) for the vendor child, so the whole
    # subtree can be signalled as one unit. `start_new_session=True` is the
    # documented spelling of the same `setsid()` call and, unlike a
    # `preexec_fn`, it is fork-safe (CPython runs it in the pre-exec child via
    # the C helper instead of executing arbitrary Python between fork and
    # exec). P4-13 trap: the pgid-capture predicate below keys on THIS kwarg —
    # changing one spelling without the other silently disables the group kill.
    if hasattr(os, "getpgid"):
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except OSError as e:
        elapsed = time.monotonic() - start
        log(f"OSError on spawn: {e}")
        # `unknown` binds to EXIT_CLI_FAIL in the contract (C8 / R-TOKENS:
        # "maps to the SAME exit code there"); this return used exit 3.
        return RunResult(
            EXIT_CLI_FAIL, "", f"spawn failed: {e}\n", elapsed,
            classification="unknown", effective_cwd=effective_cwd,
            dispatch_attempt=dispatch_attempt,
            prompt_file_resolved=prompt_file_resolved,
            requested_model=requested_model,
            requested_reasoning=requested_reasoning,
            spawned=False,
        )

    # Capture the child's process group NOW (r1/R10), while it is guaranteed
    # to be the child's own and the child is still unreaped. Popen only
    # returns after the child entered its new session (start_new_session) and
    # reached exec — the parent blocks on the exec-error pipe — so the group
    # is already established here. Doing this inside _kill_proc_group instead
    # meant a post-reap getpgid on a possibly-recycled pid.
    pgid: Optional[int] = None
    if popen_kwargs.get("start_new_session") and hasattr(os, "getpgid"):
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

    # stdin delivery state (handoff requirement 2): the writer RECORDS its
    # completion or the failure's exception CLASS (bounded, content-free)
    # instead of swallowing it; EOF signalling (close) and the concurrent
    # stdout/stderr drains are unchanged. `t_in` is joined with the same 2 s
    # bound as the drains once the child has terminated (requirement 3) —
    # never an unbounded join behind a blocked pipe or an inherited descriptor.
    stdin_state: dict = {"done": False, "error": None}
    t_in: Optional[threading.Thread] = None
    if stdin_text is not None and proc.stdin is not None:
        def _feed_stdin() -> None:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.flush()
                stdin_state["done"] = True
            except Exception as e:  # noqa: BLE001 — recorded, adjudicated below
                stdin_state["error"] = type(e).__name__
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
        t_in = threading.Thread(target=_feed_stdin, daemon=True)

    stdout_buf: list[str] = []
    stderr_buf: list[str] = []
    out_state: dict = {"done": False, "error": None}
    err_state: dict = {"done": False, "error": None}
    t_out = threading.Thread(
        target=_drain, args=(proc.stdout, stdout_buf, None, out_state), daemon=True
    )
    t_err = threading.Thread(
        target=_drain, args=(proc.stderr, stderr_buf, sys.stderr, err_state), daemon=True
    )

    # One cleanup boundary (spec case C1 / C2): the thread starts and the wait
    # sit in ONE try, so the vendor child is never left running behind an
    # exception — a thread-start failure, a signal-raised SystemExit from a
    # caller's handler, anything.
    started: list[threading.Thread] = []
    timed_out = False
    signalled = False   # C1: a terminal signal was observed in this wait
    deadline = time.monotonic() + timeout
    try:
        for t in (t_in, t_out, t_err):
            if t is not None:
                t.start()
                started.append(t)
        # A short-step wait so a RECORDED signal is observed promptly (the
        # handler no longer interrupts this wait; spec C1).
        while True:
            try:
                proc.wait(timeout=max(0.0, min(0.2, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if _SIGNAL_STATE["signum"] is not None:
                    signalled = True
                    log("terminal signal mid-wait; killing vendor subtree")
                    _kill_proc_group(proc, pgid)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    log(f"timeout after {timeout}s; sending SIGTERM")
                    _kill_proc_group(proc, pgid)
                    break
    except BaseException as e:  # noqa: BLE001 — child reaped, then re-raised or recorded
        log(f"vendor call aborted: {type(e).__name__}: {e}; killing vendor subtree")
        try:
            _kill_proc_group(proc, pgid)
        except BaseException as cleanup_exc:  # noqa: BLE001 — never displace e
            log(f"vendor-subtree cleanup failed: {cleanup_exc!r}")
        for t in started:
            t.join(timeout=2)  # the child is dead: these see EOF and exit
        # Close only pipes no live thread holds: closing one a live reader
        # blocks on would wait behind it without bound (C2).
        for pipe in ((proc.stdin, proc.stdout, proc.stderr)
                     if not any(t.is_alive() for t in started) else ()):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass
        if not isinstance(e, Exception):
            raise   # SystemExit / KeyboardInterrupt: the caller's unwind runs
        elapsed = time.monotonic() - start
        result = RunResult(
            EXIT_CLI_FAIL, "".join(stdout_buf),
            f"vendor call aborted: {type(e).__name__}: {e}\n", elapsed,
            classification="unknown",
            effective_cwd=effective_cwd,
            dispatch_attempt=dispatch_attempt,
            prompt_file_resolved=prompt_file_resolved,
            requested_model=requested_model,
            requested_reasoning=requested_reasoning,
            capture_complete=False,   # no reader completed: a prefix
        )
        result.vendor_exit_code = (
            proc.returncode if proc.returncode is not None else -1)
        if classify_and_log:
            log(
                f"[wrapper] {cli} unknown "
                f"exit={result.exit_code} vendor={result.vendor_exit_code} "
                f"elapsed={elapsed:.1f}s"
                + _summary_tail(dispatch_attempt, prompt_file_resolved, requested_model,
                                requested_reasoning)
            )
        return result

    # Reap the OWNED group after a normal child exit (spec case C1 /
    # R-TERMINAL: "the owned process group reaped" — success requires the
    # REAP, not the absence of descendants). `proc.wait()` reaps the DIRECT
    # child only, so anything the vendor left behind in the child's own group
    # keeps running; when it inherited the child's stdout/stderr it also holds
    # the capture pipes open, which is why this runs BEFORE the reader joins
    # below — otherwise the readers could never reach EOF. The probe is signal
    # 0, so the ordinary run (empty group) costs one syscall and signals
    # nothing. `PermissionError` keeps `_kill_proc_group`'s conservatism: it
    # cannot confirm the group is empty (and is the other arm of the
    # pid-recycle hazard disclosed there), so it counts as "members remain".
    if (not timed_out and not signalled and pgid is not None
            and hasattr(os, "killpg")):
        try:
            os.killpg(pgid, 0)
            members_remain = True
        except ProcessLookupError:
            members_remain = False
        except PermissionError:
            members_remain = True
        if members_remain:
            log("owned process group still has members after the child exited; "
                "reaping before the result is returned")
            _kill_proc_group(proc, pgid)

    t_out.join(timeout=2)
    t_err.join(timeout=2)
    # Reader completion gate (spec case C1 / R-TERMINAL: "all reader threads
    # joined without error"). A reader that RAISED — the pipes are strict
    # UTF-8, so one undecodable vendor byte ends it — or that is still alive
    # after the bounded join captured a PREFIX, not the transcript. The prefix
    # stays in stdout/stderr for the run-log; it is never returned as success.
    reader_failures: list[str] = []
    for _name, _thread, _rstate in (
        ("stdout", t_out, out_state), ("stderr", t_err, err_state),
    ):
        if _rstate["error"] is not None:
            reader_failures.append(f"{_name} reader error: {_rstate['error']}")
        elif _thread.is_alive():
            reader_failures.append(
                f"{_name} reader incomplete: still alive after 2 s")
    for _f in reader_failures:
        log(_f)
    # Reconcile the stdin writer within the same bound (requirement 3). The
    # child has terminated (normally or killed), so a writer still blocked on
    # a full pipe can only be held by an inherited descriptor — that case is
    # "unconfirmed", never a success.
    stdin_delivery: Optional[str] = None
    if t_in is not None:
        t_in.join(timeout=2)
        if stdin_state["error"] is not None:
            stdin_delivery = f"failed:{stdin_state['error']}"
        elif stdin_state["done"] and not t_in.is_alive():
            stdin_delivery = "complete"
        else:
            stdin_delivery = "unconfirmed"

    elapsed = time.monotonic() - start
    stdout = "".join(stdout_buf)
    stderr = "".join(stderr_buf)
    rc = proc.returncode if proc.returncode is not None else -1

    # Precedence (requirement 5): the wrapper's own timeout first; a GENUINE
    # vendor failure (rc != 0) keeps its own classification and only carries
    # the delivery annotation — a provider that rejected the input and closed
    # the pipe must not lose its real error to the consequential BrokenPipe;
    # a success-shaped rc 0 whose prompt was NOT confirmed delivered fails
    # CLOSED (requirement 4) — the answer was produced without the input. The
    # raw vendor rc is preserved on every path.
    delivery_failed = (
        stdin_delivery is not None and stdin_delivery != "complete"
        and not timed_out and rc == 0
    )
    # Reader incompleteness is the LAST rung before ok (spec case C1): a
    # wrapper timeout, a genuine vendor rc != 0 and an unconfirmed stdin
    # delivery each carry a more specific diagnosis and keep it. `rc == 0`
    # plus a broken capture is the one shape that would otherwise have been
    # reported as success. Token: `truncated-answer` — the EXISTING
    # wrapper-SET terminal class for "the answer we hold is a fragment"
    # (EXIT_TERMINAL 65, surface-never-repair); no new token is introduced.
    reader_failed = (
        bool(reader_failures) and not timed_out and rc == 0
        and not delivery_failed
    )
    # C1: a terminal signal received at any point of this call (after Popen,
    # mid-wait, inside the timeout kill, in the collection window) is consumed
    # here. Only a TIMEOUT verdict outranks it: a stdin-delivery or reader
    # failure of the same run becomes `unknown` / 1 "wrapper interrupted" (the
    # other host marks those failures, then `if received and not timed_out:
    # _mark_signal_failure`, bin/_common.py:1663-1679). The group is reaped
    # either way.
    signum = _SIGNAL_STATE["signum"]
    _SIGNAL_STATE["signum"] = None
    interrupted = signum is not None and not timed_out
    if interrupted:
        result = _interrupted_result(signum, elapsed, stdout, stderr)
        # R-AUTH (26a final fix 1, F3): the captured output goes through the
        # same auth-carrier rung a timed-out run's does — a carrier STOP is the
        # re-login STOP (oauth-env / 65), never retried. Nothing else changes.
        if classify_and_log and _auth_carrier_stop(cli, stderr, stdout, rc):
            result.exit_code = EXIT_TERMINAL
            result.classification = "oauth-env"
    elif timed_out:
        log(f"timed out elapsed={elapsed:.1f}s")
        result = RunResult(EXIT_TIMEOUT, stdout, stderr, elapsed)
    elif delivery_failed:
        log(f"exit={rc} elapsed={elapsed:.1f}s but stdin delivery "
            f"{stdin_delivery}; failing closed")
        result = RunResult(EXIT_TERMINAL, stdout, stderr, elapsed,
                           classification="input-delivery-failed")
    elif reader_failed:
        log(f"exit={rc} elapsed={elapsed:.1f}s but the output readers did not "
            f"complete ({'; '.join(reader_failures)}); failing closed")
        result = RunResult(EXIT_TERMINAL, stdout, stderr, elapsed,
                           classification="truncated-answer")
    else:
        log(f"exit={rc} elapsed={elapsed:.1f}s")
        ec = EXIT_OK if rc == 0 else EXIT_CLI_FAIL
        result = RunResult(ec, stdout, stderr, elapsed)

    result.vendor_exit_code = rc
    result.effective_cwd = effective_cwd
    result.stdin_delivery = stdin_delivery
    result.dispatch_attempt = dispatch_attempt
    result.prompt_file_resolved = prompt_file_resolved
    result.requested_model = requested_model
    result.requested_reasoning = requested_reasoning
    # Row r5-2: the reader outcome as EVIDENCE, independent of the rung that
    # consumed it. `reader_failed` above is gated on `rc == 0`; this is not.
    result.capture_complete = not reader_failures and not interrupted
    if classify_and_log:
        # SEMANTIC stderr classification (tool-not-installed / vendor warning)
        # stays the leader's judgment over the mirrored raw stderr. A
        # delivery failure is decided ABOVE from the writer's own record and
        # is never re-derived from stderr text (requirement 6: no
        # error-text reclassification can promote it or trigger a retry). A
        # reader failure is decided the same way, from the reader's own
        # record — and classify() must not overwrite it back to "ok".
        if not delivery_failed and not reader_failed and not interrupted:
            result.classification = classify(
                cli, stderr, stdout, result.exit_code, vendor_exit_code=rc,
            )
        # One-line deterministic summary (immediately visible to leader/user).
        # The exit printed is the CONTRACT's code for the token (C8 / R-TOKENS):
        # a classifier token the driver promotes later (token-limit -> 65,
        # server-capacity -> 64) is never emitted with the provisional 1.
        log(
            f"[wrapper] {cli} {result.classification} "
            f"exit={map_classification_to_exit(result.classification)} "
            f"vendor={result.vendor_exit_code} "
            f"elapsed={elapsed:.1f}s"
            + _summary_tail(dispatch_attempt, prompt_file_resolved, requested_model,
                            requested_reasoning)
        )
    elif not delivery_failed and not reader_failed and not interrupted:
        # r1/R8: do NOT leave the field at its "ok" default — a shared struct
        # reading "ok" for a run that was never classified is a trap for any
        # future consumer of this RunResult. NOT a new classify() token
        # (CLASSIFICATION_TOKENS is unchanged and this value never reaches
        # audit, the summary line or a repair proposal): the sole
        # classify_and_log=False caller is the agy stream-json driver, which
        # sets the real classification on this RunResult before returning it.
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
    prompt_via_stdin: bool = False,
    dispatch_attempt: int = 1,
    prompt_file_resolved: Optional[str] = None,
    requested_model: Optional[str] = None,
    requested_reasoning: Optional[str] = None,
) -> RunResult:
    """Top-level driver.

    Layers (in order):
    1. Schema injection — if `pydantic_cls`, prepend the schema block to prompt.
    2. Server-capacity retry — `SERVER_CAP_BACKOFF_S`.
    3. Answer extraction — cli-aware (JSONL events / single JSON object).
    4. Schema validation — if `pydantic_cls`, validate; on failure, retry once
       (mode = "schema_repair") with a clarifying suffix in the prompt.

    `cmd_builder(prompt) -> argv` lets us rebuild the argv after schema-repair
    prompt mutation without leaking command construction into this function.
    """
    # Next-run IPC cleanup (owner contract: a subsequent run clears prior
    # residue); the age floor keeps a run-log the repair step still reads.
    prune_stale_run_logs(cli)

    effective_prompt = (
        inject_schema_to_prompt(prompt, pydantic_cls) if pydantic_cls else prompt
    )

    def promote_schema_fail(r: RunResult) -> RunResult:
        r.exit_code = EXIT_SCHEMA_FAIL
        r.classification = "schema-fail"
        r.final_answer = ""
        _emit_canonical_summary(cli, r)
        return r

    terminal_classes = (
        "cli-subscription-cap",
        "token-limit",
        "oauth-env",
        "config-conflict",
        "task-blocked",
    )

    def promote_terminal(r: RunResult, cls: str) -> RunResult:
        r.exit_code = EXIT_TERMINAL
        r.classification = cls
        r.final_answer = ""
        _emit_canonical_summary(cli, r)
        return r

    def promote_extraction_classification(
        r: RunResult, ext_err: str
    ) -> Optional[RunResult]:
        if _auth_carrier_stop(cli, r.stderr, r.stdout,     # R-AUTH (ii), rc-0 run
                              r.vendor_exit_code):
            r.extraction_error = ext_err
            return promote_terminal(r, "oauth-env")
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
            _emit_canonical_summary(cli, r)
            return r
        return None

    schema_repair_attempt = 0
    last_r: Optional[RunResult] = None   # the previous attempt of this call (C1)
    while True:
        cmd = cmd_builder(effective_prompt)

        # Layer 2: server-cap retry.
        max_retries = SERVER_CAP_MAX_RETRIES
        result: Optional[RunResult] = None
        for attempt in range(max_retries + 1):
            signum = _SIGNAL_STATE["signum"]
            if last_r is not None and signum is not None:
                # C1: a signal BETWEEN attempts spawns nothing; the previous
                # attempt carries the failure, its own stamps kept.
                _SIGNAL_STATE["signum"] = None
                r = _interrupted_previous(last_r, signum)
                _emit_canonical_summary(cli, r)
                return r
            r = last_r = _run_once(
                cli, cmd, cwd=cwd, timeout=timeout,
                stdin_text=effective_prompt if prompt_via_stdin else None,
                # Record-only (C9/C10 + C28): the caller's dispatch attempt is
                # NOT this loop's server-cap `attempt`, which stays internal.
                dispatch_attempt=dispatch_attempt,
                prompt_file_resolved=prompt_file_resolved,
                requested_model=requested_model,
                requested_reasoning=requested_reasoning,
            )
            r.schema_repair_attempt = schema_repair_attempt
            r.mode = "schema_repair" if schema_repair_attempt > 0 else "normal"
            result = r
            cls = r.classification
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
                _emit_canonical_summary(cli, r)
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
                    _signal_aware_sleep(wait)
                    continue
                r.exit_code = EXIT_RATE_GIVE_UP
                # Re-emit — promote rc=1 → 64 in the [wrapper] line.
                _emit_canonical_summary(cli, r)
                return r
            # cls in {"unknown", "timeout", "input-delivery-failed",
            # "truncated-answer"} — fail-fast. The last two arrive from
            # `_run_once` ALREADY judged (exit 65, the answer blanked), and
            # this rung returns that RunResult UNCHANGED: it is where the
            # two shared-driver wrappers honour an engine-decided terminal
            # exit, and the reason the r3-1 defect was agy-only (that driver
            # spawns `_run_once` itself). Do not "re-classify" here — the
            # engine decided from the reader and writer records, which this
            # layer cannot see. At the dispatch SKILL layer `unknown` routes to
            # the repair analyzer; a `timeout` surfaces and is never routed.
            return r

        assert result is not None

        # Layer 3: extract final answer.
        if cli == "codex":
            answer, ext_err = extract_codex_answer(result.stdout, last_msg_path)
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
                _emit_canonical_summary(cli, result)
            return result

        result.final_answer = answer

        # Layer 4: schema validation.
        if pydantic_cls is None:
            return result

        ok, validated_or_err, nonrepairable = validate_response_detail(
            answer, pydantic_cls)
        if ok:
            result.validated = validated_or_err
            return result

        result.validation_error = str(validated_or_err)
        log(f"schema validation failed: {validated_or_err}")

        if nonrepairable:
            log("schema validation non-repairable (duplicate JSON member) "
                "— skipping repair retry")
            return promote_schema_fail(result)

        if schema_repair_attempt >= 1:
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
_HOST_LOGS = Path(__file__).resolve().parent / "_logs"
_LOG_DIR = Path(os.environ.get("TRIAD_DISPATCH_LOG_DIR") or _HOST_LOGS)
_HOST_DEBUG = Path(__file__).resolve().parent / "_debug"


def _debug_dir_from_env() -> Path:
    """TRIAD_DEBUG_DIR overrides the --debug markdown root (the sibling of
    TRIAD_DISPATCH_LOG_DIR; day dirs, rows and their expiry all move with it).
    Absolute paths only: empty -> the wrapper-adjacent _debug/; a relative
    value -> one note + that default (a cwd-relative dump dir would scatter);
    a value resolving to the filesystem root -> one note + that default."""
    default = _HOST_DEBUG
    raw = os.environ.get("TRIAD_DEBUG_DIR", "")
    if not raw:
        return default
    if not os.path.isabs(raw):
        log(f"[wrapper] debug: ignoring relative TRIAD_DEBUG_DIR {raw!r} "
            f"(absolute path only); using {default}")
        return default
    if os.path.realpath(raw) == os.path.realpath(os.sep):
        log(f"[wrapper] debug: ignoring TRIAD_DEBUG_DIR {raw!r} "
            f"(the filesystem root); using {default}")
        return default
    return Path(raw)


_DEBUG_DIR = _debug_dir_from_env()


# A floor beyond any real age is clamped before any float arithmetic (an
# integer the configuration may hold, 10**400 s included).
_MAX_FLOOR_S = 10 ** 6 * 86400


def _swept_link(mod, where, tops) -> Optional[str]:
    """The deletion module's own link check (`cleanup._link_below`) for a sweep
    of `where`: every component below the base of the first (root, base) of
    `tops` that holds it — the declared root against its base (the project,
    `$TMPDIR`, `~` or `$HOST_DIR`), a re-root against its parent."""
    w = os.path.realpath(where)
    for top, base in tops:
        t = os.path.realpath(top)
        if w == t or os.path.commonpath([w, t]) == t:
            return mod._link_below(str(where), base)
    return mod._link_below(str(where), tops[0][1])


def _swept(role: str, proof: str, where: Optional[Path] = None,
           rerooted: tuple = (), minimum: float = 0) -> Optional[tuple]:
    """R-CLEANUP / C69: the declared `role` for ONE coded sweep — (root,
    min_age_s, base, the deletion module) from the cleanup configuration
    (`cleanup.load_roots`).
    None, after ONE stderr line, when the configuration is missing or invalid,
    the role is not declared, it declares a proof other than `proof` (the one
    this sweep checks), or `where` lies outside its root and outside every
    `rerooted` folder — a test-isolation re-root (a reassigned `_LOG_DIR` /
    `_DEBUG_DIR`, TRIAD_REVIEW_LOG_DIR, an explicit base) standing in for the
    root; proof and floor still come from the file. A symbolic link at the
    root, at a re-root or on the way down to `where` skips the sweep too. The
    floor returned is never below `minimum` (the host's own minimum for files a
    live call may still use). The deletion module is the one beside this file,
    never another `cleanup` on sys.path. Never raises."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cleanup", _HOST_LOGS.parent / "cleanup.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg, roots = mod.load_roots()
        entry = roots.get(role)
        if entry is None:
            why = f"role {role} is not declared in {cfg}"
        elif entry[1] != proof:
            why = f"role {role} declares the proof {entry[1]}, this sweep checks {proof}"
        elif where is not None and not any(
                os.path.realpath(where) == r or os.path.commonpath([os.path.realpath(where), r]) == r
                for r in map(os.path.realpath, (entry[0], *rerooted))):
            why = f"{where} is outside the declared root {entry[0]} of role {role}"
        elif (link := _swept_link(mod, where if where is not None else entry[0],
                                  ((entry[0], entry[3]),
                                   *((r, os.path.dirname(os.path.abspath(r))) for r in rerooted)))):
            why = f"{link} is a symbolic link (role {role})"
        else:
            return entry[0], min(max(entry[2], minimum), _MAX_FLOOR_S), entry[3], mod
    except Exception as exc:  # noqa: BLE001 — missing / invalid / unreadable: nothing deleted
        why = f"no valid cleanup configuration ({exc})"
    try:
        log(f"[wrapper] cleanup: {role} prune skipped — {' '.join(why.split())}; nothing deleted")
    except Exception:  # noqa: BLE001 — a prune never fails its caller
        pass
    return None


def _log_reroots() -> tuple:
    """The re-roots of the wrapper log roles: a `_LOG_DIR` moved off the
    wrapper-adjacent default (TRIAD_DISPATCH_LOG_DIR) and a review attempt's
    TRIAD_REVIEW_LOG_DIR."""
    review = os.environ.get("TRIAD_REVIEW_LOG_DIR")
    return tuple(p for p in (None if _LOG_DIR == _HOST_LOGS else _LOG_DIR,
                             Path(review) if review else None) if p is not None)


def _dispatch_record(writer):
    """The ONE seam every dispatch record write passes — `audit()`,
    `debug_log()`, `emit_run_log()`, `emit_read_audit()`.

    A4 / R-THREAT: a write that fails (an OSError — a full disk, a blocked
    directory — or any other Exception, C8) is ONE stderr line and returns
    None — the record is lost, never the paid answer or the exit code."""
    @functools.wraps(writer)
    def write(cli: str, *args, **kwargs):
        try:
            return writer(cli, *args, **kwargs)
        except Exception as exc:   # noqa: BLE001 — the record seam
            log(f"[wrapper] {cli}: record write failed ({writer.__name__}: "
                f"{type(exc).__name__}: {exc}) — the answer is still published, "
                f"the exit code unchanged")
            return None
    return write


@_dispatch_record
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
        # Key omitted (not null) when absent, so codex/gemini records
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
    if result.stdin_delivery is not None:
        # stdin delivery outcome (codex handoff 2026-09-18): a fixed vocabulary
        # (complete / failed:<ExceptionClass> / unconfirmed) — no prompt
        # content, so no redaction. Key omitted for the non-stdin callers,
        # same shape rule as vendor_version above (t48 axis 7).
        rec["stdin_delivery"] = result.stdin_delivery
    if result.prompt_file_resolved is not None:
        # C28 record (owner directive 2026-09-19): the ABSOLUTE path a
        # possibly-relative --prompt-file resolved to. This is the artifact
        # that replaces the retired fail-loud refusal — a mis-resolved
        # same-named file is legible here afterwards. A host path, so it is
        # masked under the hardened custody mode (unlike `effective_cwd`,
        # which predates the receipt work and keeps its own shape).
        rec["prompt_file_resolved"] = (
            PROMPT_FILE_REDACTED if redact else result.prompt_file_resolved)
    if result.requested_model is not None:
        # C35 record (shared dev log DL-3): the model slug the caller
        # REQUESTED — not a runtime identity. A catalog slug is not
        # prompt-bearing, so no redaction; key omitted when None (= the CLI's
        # config default), same shape rule as prompt_file_resolved above.
        rec["requested_model"] = result.requested_model
    if result.requested_reasoning is not None:
        # C35 as amended: the requested reasoning / effort tier, same shape.
        rec["requested_reasoning"] = result.requested_reasoning
    if result.runtime_model is not None:
        rec["runtime_model"] = result.runtime_model
    # Common transport receipt (spec C9/C10, R-RECEIPT) — written on EVERY
    # audit row, success or failure. Purely ADDITIVE: no pre-existing key is
    # removed or renamed, and A's richer `stdin_delivery` / `vendor_version`
    # stay exactly as they were beside it.
    transport = _record_transport(result, cli, cmd)
    if redact and isinstance(transport.get("binary"), str):
        # The receipt is not a licence to leak host paths: same custody rule
        # the prompt-bearing argv already follows in this mode.
        transport["binary"] = TRANSPORT_BINARY_REDACTED
    rec["transport"] = transport
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
            # errors="backslashreplace" (gate r1 fix, codex must-fix + claude,
            # converged 2026-09-18): the record may carry a prompt head that
            # is NOT UTF-8-encodable (argv is decoded with surrogateescape, so
            # an invalid byte in `--prompt` becomes a lone surrogate — exactly
            # the input `_run_once` now refuses pre-spawn at exit 3). A strict
            # writer re-raised UnicodeEncodeError HERE, killing the wrapper at
            # rc 1 with a traceback and losing the refusal's exit code, this
            # record and the run-log. The escape (`\udcff`) is valid JSON;
            # Python's json round-trips it to the same code point, while jq
            # (1.7.1 measured, gate r2) DISPLAYS it as U+FFFD — the file itself
            # stays intact. Every encodable record is byte-identical.
            with path.open("a", encoding="utf-8", errors="backslashreplace") as f:
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
    """Rotate the active audit log and prune the oldest archives.

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
    """Delete the oldest audit archives past the count and byte caps, never one
    younger than the wrapper-audit-archives role's floor (`_swept`). An archive
    that vanished meanwhile is skipped silently; any other failure to read or
    remove one is reported in one line and the archive left in place."""
    try:
        entries = list(log_dir.glob("audit.*.jsonl"))
    except Exception:
        return
    role = _swept("wrapper-audit-archives", "inside-owned-packet", log_dir, _log_reroots())
    if role is None:
        return
    cut = time.time() - role[1]
    rows: list[tuple[Path, float, int]] = []
    for p in entries:
        try:
            st = p.stat()
            rows.append((p, st.st_mtime, st.st_size))
        except (FileNotFoundError, NotADirectoryError):
            continue  # vanished since the listing
        except OSError as exc:
            log(f"[wrapper] cleanup: wrapper-audit-archives could not read {p} ({exc}); left in place")
    rows.sort(key=lambda x: x[1])
    total_bytes = sum(sz for _, _, sz in rows)
    over_count = max(0, len(rows) - AUDIT_MAX_ARCHIVES)
    over_bytes = total_bytes - AUDIT_ARCHIVE_MAX_BYTES
    for p, mtime, sz in rows:
        if over_count <= 0 and over_bytes <= 0:
            break
        if mtime > cut:
            continue
        try:
            p.unlink()
            over_count -= 1
            over_bytes -= sz
        except FileNotFoundError:
            continue  # another call took it
        except OSError as exc:
            log(f"[wrapper] cleanup: wrapper-audit-archives could not remove {p} ({exc})")


# ─── Deterministic classifier-patch applier (repair read-only redesign) ────
# The repair sub-agent is a READ-ONLY analyzer: it returns a structured patch
# PROPOSAL and has ZERO write authority. This function is the SINGLE trusted
# write path to the classifier extension JSON — validate against the enum +
# pattern-name SoT + literal bounds, then flock + atomic-write. No LLM in the
# write path; safe-by-construction against classifier-poisoning.
#
#   CLASSIFICATION_TOKENS = the classify() result enum (keys of the
#     map_classification_to_exit dict — the single source of truth).
#     EXCEPTIONS (deliberate — driver-emitted agy tokens that live in the exit
#     map but NOT here, so none is ever a proposable repair target): `vendor-error`
#     (P4 2026-07-11: rc!=0 / non-SUCCESS status WITH a non-empty answer),
#     `truncated-answer` (2026-07-22: CLI-side fold), `admission-refused`
#     (2026-09-04: a tool outside the agent allowlist in the stream) and
#     `vendor-timeout` (2026-09-04: agy's own turn timeout, empty answer), and
#     the one SHARED-ENGINE wrapper-set token `input-delivery-failed`
#     (2026-09-18: _run_once could not confirm stdin prompt delivery to a rc-0
#     child, or refused an unencodable prompt pre-spawn — a wrapper transport
#     defect, never a classifier gap; t48 axis 8 pins it OUT of this enum).
#     Each is a condition a classifier patch cannot express; t38 pins the
#     registry contract for the two 2026-09-04 tokens, t14 for vendor-error.
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
        "config-conflict",
        "task-blocked",
        "unknown",
    )
)
# Assert the enum stays in lock-step with map_classification_to_exit() — the SoT.
# MEMBERSHIP, not `is not None` (spec case C8 / R-TOKENS): the old form asked
# whether the helper returned something, and because the helper ends in
# `.get(cls, EXIT_CLI_FAIL)` the answer was ALWAYS yes — a token dropped from the
# map silently fell through to exit 1 and the assert still passed (vacuous on
# BOTH hosts, host-parity audit 2026-09-19 § 2 row C8). The real invariant is
# that every classify() token has its OWN row in the table; `EXIT_MAP_TOKENS`
# exposes those explicit keys. t55 proves this assert can fire.
assert set(CLASSIFICATION_TOKENS) <= EXIT_MAP_TOKENS, (
    "CLASSIFICATION_TOKENS drifted from map_classification_to_exit: "
    + ", ".join(sorted(set(CLASSIFICATION_TOKENS) - EXIT_MAP_TOKENS))
)

PATTERN_LIST_NAMES: frozenset[str] = frozenset(
    (
        "SERVER_CAPACITY_PATTERNS",
        "CLI_SUB_CAP_PATTERNS",
        "TOKEN_LIMIT_PATTERNS",
        "SCHEMA_REJECTED_PATTERNS",
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
#   SCHEMA_REJECTED → schema-rejected,
#   CONFIG_CONFLICT → config-conflict.
# A pattern proposal's `classification` must equal PATTERN_LIST_CLASS[pattern_list]
# (else appending the substring would make classify() return a DIFFERENT class
# than the proposal claims). Locked in step with PATTERN_LIST_NAMES at import.
PATTERN_LIST_CLASS: dict[str, str] = {
    "SERVER_CAPACITY_PATTERNS": "server-capacity",
    "CLI_SUB_CAP_PATTERNS": "cli-subscription-cap",
    "TOKEN_LIMIT_PATTERNS": "token-limit",
    "SCHEMA_REJECTED_PATTERNS": "schema-rejected",
    "CONFIG_CONFLICT_PATTERNS": "config-conflict",
    "AGY_AUTH_BANNER_PATTERNS": "oauth-env",
}
assert (
    set(PATTERN_LIST_CLASS.keys()) == set(PATTERN_LIST_NAMES)
), "PATTERN_LIST_CLASS drifted from PATTERN_LIST_NAMES (classify() mirror broke)"
assert all(
    _c in CLASSIFICATION_TOKENS for _c in PATTERN_LIST_CLASS.values()
), "PATTERN_LIST_CLASS maps to a class not in CLASSIFICATION_TOKENS"

# Bound on a proposed substring literal — a match phrase is a short distinctive
# fragment (R-CLASSIFY).
_MAX_SUBSTRING_LEN = 200
# Floor on a proposed substring length (after lowercase-normalize). A defensible
# floor that rejects the pathological "e"/"the" while allowing real short
# signatures ("oauth", "quota"). NOT a claim of full semantic specificity — that
# is the analyzer's + owner's job (see SECURITY.md), only a coarse over-broad guard.
_MIN_SUBSTRING_LEN = 4

# ── fix2/fix3: L1 vendor_exit_map symmetric guard (round-2 + round-3 re-confirm
# BLOCKERs) ────────────────────────────────────────────────────────────────
# classify() consults the extension's vmap BEFORE the L2 substrings and
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
# L2 `_MIN_SUBSTRING_LEN` over-broad floor.
_VENDOR_EXIT_CODE_MIN = 3
_VENDOR_EXIT_CODE_MAX = 125

# A vendor's own EXIT CODE cannot mean a WRAPPER-determined status, so a vmap
# PROPOSAL is restricted to the vendor-exit-DERIVABLE classes. Kept: the vendor-
# error classes (server-capacity, cli-subscription-cap, token-limit, oauth-env,
# schema-rejected) + extraction-error.
# Excluded (the wrapper/status classes the WRAPPER decides, never a raw vendor
# exit): timeout (wrapper kills the vendor on its own timeout — exit_code==
# EXIT_TIMEOUT in classify(), not a vmap code); schema-fail (wrapper pydantic
# JSON validation — EXIT_SCHEMA_FAIL, not in classify()); task-blocked (a shared
# contract row with no producer on this host — an envelope reading, not an exit);
# config-conflict
# (wrapper/config condition via CONFIG_CONFLICT_PATTERNS + agy settings txn).
# Verified against classify() + the wrapper exit-code semantics (2026-07-06).
# This applies ONLY to the vendor_exit_map path — the PATTERN path already
# enforces classification == PATTERN_LIST_CLASS[pattern_list].
VENDOR_EXIT_PROPOSAL_CLASSES: frozenset[str] = frozenset(
    REPAIR_CLASSIFICATION_TOKENS
    - {"timeout", "schema-fail", "task-blocked", "config-conflict"}
)
assert (
    VENDOR_EXIT_PROPOSAL_CLASSES <= REPAIR_CLASSIFICATION_TOKENS
), "VENDOR_EXIT_PROPOSAL_CLASSES must be a subset of REPAIR_CLASSIFICATION_TOKENS"


def apply_classifier_patch(cli: str, proposal: dict) -> str:
    """Validate + atomically merge a repair-analyzer proposal into the classifier
    extension JSON. The SINGLE trusted write path (zero LLM here).

    proposal = {
        "classification": <one of REPAIR_CLASSIFICATION_TOKENS>,  # required (NOT ok/unknown)
        "reason":         <non-empty str>,                        # required
        # exactly one target:
        "vendor_exit_code": <int > 0>,    # append {code: classification} to vendor_exit_map
        "pattern_list":     <one of PATTERN_LIST_NAMES>,  # + "substring": <bounded str>
        "substring":        <non-empty bounded literal str, stored LOWERCASED>,
    }

    Semantic validation (all BEFORE any file write; ValueError on violation):
      - classification ∈ REPAIR_CLASSIFICATION_TOKENS (ok/unknown rejected — ok
        would suppress real failures, unknown is the default bucket).
      - classification `oauth-env` is never a repair proposal (R-AUTH: escalate).
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
      - reason is a non-empty str.

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
    # R-AUTH: authentication is the user's to fix — refuse every oauth-env
    # proposal (exit-code entry or pattern append) before any file is touched.
    if classification == "oauth-env":
        raise ValueError(
            "apply_classifier_patch: classification 'oauth-env' is never a repair proposal — authentication is the user's to fix through the vendor CLI's own login (R-AUTH); escalate"
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

            if has_exit:
                vmap = entry.get("vendor_exit_map")
                if not isinstance(vmap, dict):
                    vmap = {}
                vmap[str(vendor_exit_code)] = classification
                entry["vendor_exit_map"] = vmap
            else:
                pats = entry.get("patterns")
                if not isinstance(pats, dict):
                    pats = {}
                lst = pats.get(pattern_list)
                if not isinstance(lst, list):
                    lst = []
                if substring not in lst:
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


def _run_record_path(record: dict) -> tuple:
    """The failure path of a stored run-log record, read from its own fields:
    ("c", agy result) / ("b", None) / ("a", None); a record whose class was
    decided outside the classifier raises ValueError. The one path decision
    of `reclassify_run_record` and of the verifier's evidence lines."""
    refused = ValueError("verify on this stored record is not supported "
                         "(class decided outside the classifier)")
    rc = record.get("vendor_exit_code")
    if (record.get("classification") not in CLASSIFICATION_TOKENS - {"ok", "schema-fail", "task-blocked"}
            or isinstance(rc, bool) or not isinstance(rc, int)):
        raise refused
    timed_out = record.get("exit_code") == EXIT_TIMEOUT
    if record.get("cli") == "antigravity":
        if record.get("extraction_error") or timed_out:
            raise refused
        try:
            _events, result = parse_agy_stream(record.get("stdout") or "")
        except _DuplicateJSONMember:
            raise refused from None
        res = result if isinstance(result, dict) else {}
        answer = res.get("response")
        if not ((isinstance(answer, str) and answer.strip())
                or isinstance(res.get("structured_output"), dict)):
            return "c", result
    elif rc == 0 and record.get("extraction_error"):
        return "b", None
    if rc != 0 or timed_out:
        return "a", None
    raise refused


def reclassify_run_record(record: dict) -> str:
    """The class the wrapper's own decision gives a stored failure run-log
    today (built-ins + extension) — how an applied proposal is verified; the
    vendor is never called again and nothing is spawned. The failure path
    (`_run_record_path`) is read from the record's own fields:
      (c) agy, no usable answer in the stored stream — the driver's own
          decision (`_agy_no_answer_class`) over stderr + the stream result's
          typed signal and status;
      (b) non-agy, vendor exit 0, `extraction_error` set — the extraction
          reason as stderr, empty stdout; only a terminal or schema-rejected
          class replaces extraction-error;
      (a) vendor exit != 0 or a wrapper timeout — stderr, stdout, exit, vendor
          exit.
    A class decided outside the classifier is refused (ValueError): a stored
    class classify() never returns, no stored vendor exit, or an agy record an
    earlier driver rung decided (`extraction_error` set, or a wrapper
    timeout)."""
    path, result = _run_record_path(record)
    cli, rc = record["cli"], record["vendor_exit_code"]
    stderr, stdout = record.get("stderr") or "", record.get("stdout") or ""
    if path == "c":
        status = result.get("status") if isinstance(result, dict) else None
        return _agy_no_answer_class(stderr, agy_classify_signals(result), status, stdout, rc)
    if path == "b":
        if _auth_carrier_stop(cli, stderr, stdout, rc):
            return "oauth-env"
        cls = classify(cli, stderr=record["extraction_error"], stdout="",
                       exit_code=EXIT_CLI_FAIL, vendor_exit_code=rc)
        if map_classification_to_exit(cls) == EXIT_TERMINAL or cls == "schema-rejected":
            return cls
        return "extraction-error"
    timed_out = record.get("exit_code") == EXIT_TIMEOUT
    return classify(cli, stderr, stdout, EXIT_TIMEOUT if timed_out else EXIT_CLI_FAIL,
                    vendor_exit_code=rc)


# ─── Per-execution run-log (dispatch SKILL input) ─────────────────────────

@_dispatch_record
def emit_run_log(
    cli: str,
    wrapper_cmd: list[str],
    vendor_cmd: list[str],
    prompt: str,
    result: RunResult,
) -> Optional[Path]:
    """Write per-execution run-log on failure — and, for a v2 REVIEW
    attempt, on success too.

    Run-logs live at `_logs/<cli>/runs/<UTC-ts>-<pid>-<uuid8>.json`. Used by
    the dispatch SKILL to feed the failing call's full context to the repair
    sub-agent without inline-embedding (escape-safe + parallel-safe).

    On success (`exit_code == EXIT_OK`), returns None and writes nothing —
    repair agent dispatch isn't needed — UNLESS `TRIAD_REVIEW_LOG_DIR` is set.
    That env member is the review dispatch's own (only the review skill's
    `roster_v2.render_dispatch` writes it, as `<attempt dir>/logs`): the
    run-log then goes to `<that dir>/<cli>/runs/` on success and failure
    alike, and its `wrapper_cmd` is the attempt's receipt of the command that
    actually ran, which the collector compares with the recorded dispatch
    (R-BIND).

    Self-prunes after write: past `_RUN_LOG_MAX_FILES` or `_RUN_LOG_MAX_BYTES`
    the oldest files are unlinked, never one younger than
    `_STALE_IPC_AGE_FLOOR_S` (best-effort, race-tolerant for parallel writes).
    """
    review_dir = os.environ.get("TRIAD_REVIEW_LOG_DIR")
    if result.exit_code == EXIT_OK and not review_dir:
        return None

    runs_dir = (Path(review_dir) if review_dir else _LOG_DIR) / cli / "runs"
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
        # stdin_delivery (codex handoff 2026-09-18): same omit-when-None spread.
        # A delivery failure is a WRAPPER transport defect, not a classifier
        # gap — the repair analyzer must be able to see that from the one
        # artifact it may open and decline to propose a pattern.
        **({"stdin_delivery": result.stdin_delivery} if result.stdin_delivery is not None else {}),
        # prompt_file_resolved (C28, 2026-09-21): same omit-when-None spread.
        # The run-log is the transient repair-IPC artifact and keeps FULL
        # values in redact mode (the t28 axis-7 rule), so no masking here.
        **({"prompt_file_resolved": result.prompt_file_resolved}
           if result.prompt_file_resolved is not None else {}),
        # requested_model (C35 / DL-3): same omit-when-None spread.
        **({"requested_model": result.requested_model}
           if result.requested_model is not None else {}),
        **({"requested_reasoning": result.requested_reasoning}
           if result.requested_reasoning is not None else {}),
        **({"runtime_model": result.runtime_model}
           if result.runtime_model is not None else {}),
        # transport (spec C9/C10, R-RECEIPT): the same receipt object audit()
        # writes, on EVERY run-log record — the repair analyzer may open only
        # this artifact, and "which binary ran, at which attempt, did the
        # prompt arrive" is exactly what a transport defect turns on.
        "transport": _record_transport(result, cli, vendor_cmd),
    }
    # errors="backslashreplace": the run-log keeps the prompt HEAD (200 chars)
    # plus the full wrapper argv (an inline `--prompt` rides there whole), so
    # a lone surrogate from a surrogateescape-decoded `--prompt` (the input the
    # pre-spawn refusal exists for) must not turn this write into a traceback
    # (gate r1 fix 2026-09-18; the audit writer carries the same guard).
    with path.open("w", encoding="utf-8", errors="backslashreplace") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)

    _prune_run_logs(runs_dir, preserve=path)

    return path


def _prune_dir_by_caps(
    dir_path: Path,
    max_files: int,
    max_bytes: int,
    preserve: Optional[Path],
    glob_patterns: tuple[str, ...],
    age_floor_s: Optional[float] = None,
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

    `age_floor_s` (spec case C3 / rule R-CLEANUP, 2026-09-21) — a MINIMUM AGE
    below which a file is never deleted to satisfy a cap: "mtime is not only a
    sort key". Before it, the oldest-first order alone decided, so a sibling
    leg's run-log written SECONDS ago — the live IPC of a concurrent dispatch
    — was deleted the moment the dir crossed a cap. When the floor leaves the
    dir over its cap the overflow is TOLERATED (a retention cap is a budget,
    not an invariant). `None` (the default) reads
    the module constant `_STALE_IPC_AGE_FLOOR_S` — the same floor the
    TIME-based sweep (`prune_stale_run_logs`) uses — AT CALL TIME rather than
    binding it as a function default: the constant is defined further down
    this module, and the call-time read is the same rule the cap constants
    above follow, so a test can shrink either.
    """
    preserve_paths = {preserve.resolve(strict=False)} if preserve is not None else set()
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
            st = p.lstat()  # never followed: a link is refused, never a candidate
        except (FileNotFoundError, NotADirectoryError):
            continue  # vanished since the listing
        except OSError as exc:
            try:
                log(f"prune {dir_path}: could not read {p.name} ({exc}) — left in place")
            except Exception:  # noqa: BLE001
                pass
            continue
        if not stat.S_ISREG(st.st_mode):
            try:
                log(f"prune {dir_path}: {p.name} is not a regular file (a link?) — left in place")
            except Exception:  # noqa: BLE001
                pass
            continue
        pairs.append((p, st.st_mtime))
    files = [p for p, _ in sorted(pairs, key=lambda x: x[1])]

    over_count = max(0, len(files) - max_files)
    # Per-file accumulation (NOT sum(... if f.exists())): a concurrent unlink
    # between exists() and stat() raises OSError; a single try/except over the
    # whole sum would reset total_bytes to 0 and silently bypass byte-limit
    # pruning (under-prune). Skip vanished files individually instead.
    total_bytes = 0
    for f in files:
        try:
            total_bytes += f.lstat().st_size
        except (FileNotFoundError, NotADirectoryError):
            continue  # vanished since the listing
        except OSError as exc:
            try:
                log(f"prune {dir_path}: could not read the size of {f.name} ({exc}) — not counted")
            except Exception:  # noqa: BLE001
                pass
    over_bytes = total_bytes - max_bytes

    floor_s = _STALE_IPC_AGE_FLOOR_S if age_floor_s is None else age_floor_s
    floor_cut = time.time() - floor_s
    fresh_left = 0
    for f in files:
        if over_count <= 0 and over_bytes <= 0:
            break
        if f.resolve(strict=False) in preserve_paths:
            continue
        try:
            st = f.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue  # vanished between the listing and here — never a delete
        except OSError as exc:
            try:
                log(f"prune {dir_path}: could not read {f.name} ({exc}) — left in place")
            except Exception:  # noqa: BLE001
                pass
            continue
        if st.st_mtime > floor_cut:
            # YOUNGER than the floor: another dispatch's live IPC. The cap is
            # left exceeded on purpose (C3) — deleting here is the failure.
            fresh_left += 1
            continue
        try:
            f.unlink()
            over_count -= 1
            over_bytes -= st.st_size
        except FileNotFoundError:
            pass  # another call took it
        except Exception as exc:  # noqa: BLE001 — reported, never fatal
            try:
                log(f"prune {dir_path}: could not remove {f.name} ({exc})")
            except Exception:  # noqa: BLE001
                pass
    if fresh_left and (over_count > 0 or over_bytes > 0):
        try:
            log(f"prune {dir_path}: cap exceeded by {fresh_left} fresh files "
                f"(age floor {floor_s:g}s) — left in place")
        except Exception:
            pass  # a best-effort prune never raises out of its own report


def _prune_run_logs(runs_dir: Path, preserve: Optional[Path] = None) -> None:
    """Best-effort prune: delete the oldest files past the file-count and
    total-byte caps, never one younger than the age floor.

    Thin wrapper over the shared `_prune_dir_by_caps` (task-1, 2026-07-31 —
    factored out so `emit_read_audit`'s digest dir can reuse the identical
    race-tolerant algorithm). Behavior unchanged from before the factor-out.
    """
    role = _swept("wrapper-run-logs", "inside-owned-packet", runs_dir, _log_reroots(),
                  minimum=_STALE_IPC_AGE_FLOOR_S)
    if role is not None:
        _prune_dir_by_caps(
            runs_dir, _RUN_LOG_MAX_FILES, _RUN_LOG_MAX_BYTES, preserve,
            ("*.json",), age_floor_s=role[1],
        )


# ─── Read-audit digest — durable file artifact (Task 1, 2026-07-31) ───────
# Root cause: emit_run_log writes only on FAILURE, so a successful agy call's
# read-audit digest previously existed only as a transient stderr line (the
# review SKILL's read-audit gate had to text-extract it from a stream that
# also mirrors untrusted vendor bytes verbatim — the anchor-mismatch /
# first-match-forgery / late-append findings this durable file retires).
# emit_read_audit writes on EVERY outcome where `result.read_audit is not
# None` — success AND failure — unlike emit_run_log's failure-only rule
# (a v2 review attempt's TRIAD_REVIEW_LOG_DIR aside; this is a NEW,
# separate artifact).
#
# Owner ruling (do NOT re-open): this file is EVIDENCE THAT A LEG DID THE
# READING WORK, not an authenticated control — no nonce, no dedicated fd,
# nothing framed as authentication. The digest's CONTENT is still folded
# from vendor-supplied stream events regardless of transport.
_READ_AUDIT_MAX_FILES = 100
_READ_AUDIT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB total cap, same policy shape as run-logs


def _publish_json(path: Path, doc: dict, mode: int) -> None:
    """Publish `doc` at `path` ATOMICALLY (gate-1 r19 row r19-4): the JSON is
    written to a temp file in the SAME directory
    (`<final-name>.tmp-<pid>-<uuid8>`, created O_EXCL | O_NOFOLLOW with
    `mode`), fsync'd, then `os.replace`d over the final name — so the final path is always either absent (or its
    previous complete content) or the new complete document, never an empty
    or partial one a concurrent reader (the collector's retry guard / hook
    check reading a sibling still being written) would pronounce permanently
    unreadable. On ANY failure the temp is removed and the error re-raised,
    so the caller's best-effort handling is unchanged. A symlink at the final
    name is replaced, never written through (`os.replace` renames over the
    link itself)."""
    # the uuid nonce (gate-1 r20 row r20-5): a process killed between create
    # and replace leaves its temp behind, and a later wrapper that got the
    # SAME pid failed O_EXCL on `<name>.tmp-<pid>` and emitted NO audit
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@_dispatch_record
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

    Custody is the caller's `read-audit-file:` stderr line alone: the
    override is the only file this call writes (no second copy in the
    default dir), and a symlink already at the override path is replaced by
    the atomic publish, never written through.

    EVERY write here is an ATOMIC PUBLISH (`_publish_json`, gate-1 r19 row
    r19-4): temp file in the same directory, fsync, `os.replace` — the final
    path is absent (or its previous complete content) or the new complete
    document, never a partial one a concurrent reader could see.

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
    `_READ_AUDIT_MAX_BYTES`, same shape as `_prune_run_logs`). An override
    call writes only its override path and runs no prune.
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
        # ATOMIC PUBLISH (gate-1 r19 row r19-4) — `_publish_json`. The
        # override keeps its 0600 mode; the default-dir file keeps the plain
        # `open("w")` mode (0666 less the umask).
        _publish_json(path, rec, 0o600 if override else 0o666)

        if not override:
            role = _swept("wrapper-run-logs", "inside-owned-packet",
                          path.parent, _log_reroots(),
                          minimum=_STALE_IPC_AGE_FLOOR_S)
            if role is not None:
                _prune_dir_by_caps(
                    read_audit_dir, _READ_AUDIT_MAX_FILES, _READ_AUDIT_MAX_BYTES,
                    preserve=path, glob_patterns=("*.json",), age_floor_s=role[1],
                )
        return path
    except Exception as e:
        log(f"emit_read_audit: failed to write digest file — {e}")
        return None


def preclear_read_audit_file() -> None:
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
    override = os.environ.get("TRIAD_READ_AUDIT_FILE")
    if not override:
        return
    # R-CLEANUP (spec 71b7126): a caller-named file is removed only when its
    # content shows this wrapper wrote it — a regular file (never a link)
    # holding exactly the `{meta, digest}` object `emit_read_audit` writes.
    try:
        st = os.lstat(override)
    except FileNotFoundError:
        return
    except OSError as e:
        log(f"preclear_read_audit_file: could not clear stale digest at {override} — {e}")
        return
    why = None
    if not stat.S_ISREG(st.st_mode):
        why = "it is not a regular file (a link, a directory or a special file)"
    else:
        try:
            with open(override, "rb") as f:
                doc = json.loads(f.read(4 * 1024 * 1024).decode("utf-8"))
            if not (isinstance(doc, dict) and set(doc) == {"meta", "digest"}
                    and isinstance(doc["meta"], dict)):
                why = "its content is not the {meta, digest} digest this wrapper writes"
        except (OSError, ValueError) as e:
            why = f"its content could not be read as this wrapper's digest ({type(e).__name__})"
    if why is not None:
        log(f"preclear_read_audit_file: left {override} in place — {why}")
        return
    try:
        os.unlink(override)
    except FileNotFoundError:
        pass
    except OSError as e:
        log(f"preclear_read_audit_file: could not clear stale digest at {override} — {e}")


# Default age floor for the next-run stale-prune. A v2 review attempt's
# run-log lives under its own TRIAD_REVIEW_LOG_DIR, which this sweep never
# scans (it reads `_LOG_DIR / cli / "runs"` only). Every other run-log is
# written when its call ends (`emit_run_log`); the one-day floor keeps a
# run-log the repair step has not read yet out of the deletion window — e.g.
# a failure early in a ` ; `-joined line of same-family calls, whose repair
# waits for the later calls, each of which sweeps at its start.
# The cap prunes — `_prune_run_logs` (`_RUN_LOG_MAX_FILES` / `_RUN_LOG_MAX_BYTES`)
# and the read-audit default-dir prune in `emit_read_audit`
# (`_READ_AUDIT_MAX_FILES` / `_READ_AUDIT_MAX_BYTES`) — keep this same floor
# (C3): a file younger than it is never pruned, so either dir can stay over its
# cap. The sweep and the caps take the floor of the wrapper-run-logs role in the
# cleanup configuration, raised to this host minimum; this constant is also the
# default of a direct `_prune_dir_by_caps` call.
_STALE_IPC_AGE_FLOOR_S = 86400


def _drop_stale(role: str, paths, cutoff: float, say: bool = False) -> None:
    """Remove the regular files among `paths` older than `cutoff` (a link is
    never followed or removed; the age is the file's own). Per-file tolerant —
    a vanishing entry never aborts the sweep; a failure is one line each, and
    with `say` every removal is one line too."""
    for p in paths:
        try:
            st = p.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue  # vanished since the listing
        except OSError as exc:
            log(f"[wrapper] cleanup: {role} could not read {p} ({exc}); left in place")
            continue
        if stat.S_ISREG(st.st_mode) and st.st_mtime < cutoff:
            try:
                p.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                log(f"[wrapper] cleanup: {role} could not remove {p} ({exc})")
                continue
            if say:
                log(f"[wrapper] cleanup: {role} removed {p}")


def prune_stale_run_logs(cli: str) -> None:
    """Next-run cleanup of stale run-logs (owner contract: "clean up on the
    NEXT run", not at exit — a crashed call must leave its evidence).

    Removes `_logs/<cli>/runs/*.json` run-logs
    whose mtime is older than the floor. Called at the START of every
    dispatch, so a SUBSEQUENT run cleans up the residue a
    prior run left on failure — including failure classes (terminal / server-cap
    / schema-rejected / task-blocked) and the run-log a repair
    loop read (no prompt or person deletes one). The cap-based `_prune_run_logs`
    remains the over-cap failsafe; this is the time-based next-run sweep.

    The age floor is what makes this concurrency-safe under 4-way parallel
    dispatch: a live sibling's run-log is freshly written (< floor) so it is
    never deleted while still awaiting consumption. Best-effort + per-file
    tolerant — a vanishing entry never aborts the sweep. The floor is the
    wrapper-run-logs role's (`_swept`), never below the one-day host minimum.
    Only regular files go (a
    link is never followed or removed); the age is the file's own.

    The same sweep covers the dispatch-prompts role: the prompt / proposal
    files the leader writes directly under `<project>/_runs/prompts/` (the
    process-entry working directory's, `_PROCESS_ENTRY_CWD`; skipped when that
    was already gone at import), past that role's floor (never below the host
    minimum), one stderr line per removed file. TRIAD_DISPATCH_PROMPTS_DIR (an
    absolute folder; tests and operators) is swept INSTEAD and stands in for the
    role's root, the role's proof and floor still applying; a relative value or
    the filesystem root is one note and nothing deleted. It runs only when the
    folder exists, so a project without one makes no lookup and prints nothing;
    a failure is at most one note, never an exception.
    """
    runs_dir = _LOG_DIR / cli / "runs"
    try:
        entries = list(runs_dir.glob("*.json"))
    except Exception:
        entries = []
    role = _swept("wrapper-run-logs", "inside-owned-packet", runs_dir, _log_reroots(),
                  minimum=_STALE_IPC_AGE_FLOOR_S) if entries else None
    if role is not None:
        _drop_stale("wrapper-run-logs", entries, time.time() - role[1])
    try:
        raw = os.environ.get("TRIAD_DISPATCH_PROMPTS_DIR", "")
        if raw and (not os.path.isabs(raw) or os.path.realpath(raw) == os.path.realpath(os.sep)):
            what = "a relative" if not os.path.isabs(raw) else "the filesystem root as"
            log(f"[wrapper] cleanup: dispatch-prompts prune skipped — {what} "
                f"TRIAD_DISPATCH_PROMPTS_DIR {raw!r} (an absolute folder only); nothing deleted")
            return
        if raw:   # the knob's folder stands in for the role's root (a re-root, like `_log_reroots`)
            prompts_dir, rerooted = Path(raw), (Path(raw),)
        else:
            entry = _PROCESS_ENTRY_CWD
            prompts_dir, rerooted = (entry / "_runs" / "prompts" if entry is not None else None), ()
        prompts = list(prompts_dir.iterdir()) if prompts_dir is not None and prompts_dir.is_dir() else []
        role = _swept("dispatch-prompts", "inside-owned-packet", prompts_dir, rerooted,
                      minimum=_STALE_IPC_AGE_FLOOR_S) if prompts else None
        if role is not None:
            _drop_stale("dispatch-prompts", prompts, time.time() - role[1], say=True)
    except Exception as exc:  # noqa: BLE001 — a prune never fails its caller
        try:
            log(f"[wrapper] cleanup: dispatch-prompts prune skipped — {type(exc).__name__}; the rest left in place")
        except Exception:  # noqa: BLE001
            pass


# ─── Debug log (human-readable per-call markdown table) ───────────────────
# Opt-in via wrapper's `--debug` flag. Append-only markdown table at
# `_debug/<UTC-YYYY-MM-DD>/<cli>.md`. Header is written exactly once per
# file (race-free under flock). Cell content is truncated to 200 chars and
# escaped (`|` → `\|`, newlines → `<br>`) for markdown table safety.
# Audit.jsonl remains the SoT for full data; debug.md is a sample-grade
# human aid for live triage (cat / glow / bat).
_DEBUG_CELL_LIMIT = 200
# Day-dir retention: `_debug/<YYYY-MM-DD>/` dirs older than the wrapper-debug
# role's floor (the cleanup configuration) are removed after a write
# (`_prune_debug_days`). Env override `TRIAD_DEBUG_MAX_AGE_DAYS` (1-3650;
# anything else -> note + the declared floor).
_DEBUG_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _debug_cell(s: str, n: int = _DEBUG_CELL_LIMIT) -> str:
    s = s or ""
    truncated = len(s) > n
    s = s[:n].replace("\r", "").replace("|", "\\|").replace("\n", "<br>")
    return s + ("…" if truncated else "")


def _debug_header(cli: str, day: str) -> str:
    """The first line `debug_log` writes into `<day>/<cli>.md` — and the
    allocation record `_debug_day_owned` reads back (one literal, both sides)."""
    return f"# {cli} debug log — {day} (UTC)"


@_dispatch_record
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

    # errors="backslashreplace": the debug dump stores a truncated prompt CELL
    # (`_debug_cell`); a lone surrogate (surrogateescape-decoded argv) in that
    # head must not abort the dump with a
    # traceback (gate r1 fix 2026-09-18; same guard as audit / run-log).
    with path.open("a", encoding="utf-8", errors="backslashreplace") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
            # Race-free header — under lock, fstat().st_size==0 means new
            # file. f.tell() in append mode is undefined per Python docs;
            # fstat() reads the actual on-disk size while we hold flock.
            # 2026-05-03 fault test exposed: parallel writers all saw
            # tell()==0 and emitted duplicate headers.
            if os.fstat(f.fileno()).st_size == 0:
                f.write(f"{_debug_header(cli, today)}\n\n")
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
    _prune_debug_days(today)


def _debug_max_age_days(default: float) -> float:
    """The declared floor in days, raised (never lowered) by a valid
    TRIAD_DEBUG_MAX_AGE_DAYS."""
    raw = os.environ.get("TRIAD_DEBUG_MAX_AGE_DAYS", "")
    if not raw:
        return default
    try:
        days = int(raw)
    except ValueError:
        days = 0
    if days < 1 or days > 3650:
        log(f"[wrapper] debug: ignoring invalid TRIAD_DEBUG_MAX_AGE_DAYS "
            f"{raw!r} (valid: 1-3650 days); using {default:g}")
        return default
    return max(days, default)


def _debug_day_records(d: Path) -> list[str]:
    """Names of the REGULAR `<stem>.md` files in day dir `d` whose first line
    is `debug_log`'s own header naming that day (`_debug_header(<stem>,
    <d.name>)`) — the dir's allocation records. The record is the header,
    never the name shape; a symlinked `.md` never counts. Reads at most 200
    bytes per file. A `.md` that vanishes mid-read is not a record. Raises
    OSError when the dir or a `.md` in it cannot be read."""
    with os.scandir(d) as it:
        entries = [e for e in it if e.name.endswith(".md")]
    records: list[str] = []
    for e in entries:
        if not e.is_file(follow_symlinks=False):
            continue
        want = _debug_header(e.name[:-3], d.name).encode("utf-8")
        try:
            fd = os.open(e.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                head = os.read(fd, 200)
            finally:
                os.close(fd)
        except FileNotFoundError:
            continue  # gone mid-read (a concurrent sweep): not a record
        if head.split(b"\n", 1)[0] == want:
            records.append(e.name)
    return records


def _debug_day_owned(d: Path) -> bool:
    """True when day dir `d` holds at least one allocation record
    (`_debug_day_records`). Raises OSError as that does."""
    return bool(_debug_day_records(d))


def _remove_debug_day(d: Path) -> bool:
    """Remove owned day dir `d` with its allocation records LAST: every other
    entry, then the records, then the dir. A failed removal therefore leaves
    the records in place, so the residue stays owned and the next sweep
    retries it (its age is the records'); an interruption between the records
    and the rmdir leaves an EMPTY dir, which stays (a sweep-only role gets no
    empty-folder removal; a recorded limit). Per-entry errors are absorbed; True only when `d`
    is gone. Raises OSError when `d` cannot be listed."""
    records = set(_debug_day_records(d))
    with os.scandir(d) as it:
        entries = [(e.name, e.path, e.is_dir(follow_symlinks=False))
                   for e in it if e.name not in records]
    for _name, path, is_dir in entries:
        if is_dir:
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.unlink(path)
            except OSError:
                pass
    with os.scandir(d) as it:
        if any(e.name not in records for e in it):
            return False
    for name in records:
        try:
            os.unlink(d / name)
        except OSError:
            pass
    try:
        os.rmdir(d)
    except OSError:
        pass
    return not os.path.lexists(d)


def _prune_debug_days(today: str) -> None:
    """Expire `_debug/<YYYY-MM-DD>/` day dirs older than the age floor.

    Runs after `debug_log` has written and released its lock. Candidates are
    DIRECTORIES (never symlinks, never followed) whose name is date-shaped,
    which are not `today`'s dir, and which `debug_log` provably wrote
    (`_debug_day_records`); the AGE is the newest record's own mtime (the
    proof, never the folder) — the floor, not the name, decides. A date dir
    without a record is skipped and counted when its own mtime is past the
    floor — an EMPTY one too: a sweep-only role gets no empty-folder removal
    (R-CLEANUP). A day dir holding a `.git` entry anywhere below it is skipped
    with one line (no deletion around a repository or a worktree). Removal
    takes the header records LAST (`_remove_debug_day`),
    so a failed removal keeps the proof and the next sweep retries it. A
    candidate that no longer exists is skipped (neither removed nor failed).
    Best-effort: nothing here ever raises into the caller; one stderr note
    each for removed, skipped and unremovable dirs (a candidate still present
    after the removal, or an OSError on its lstat/read while it still exists),
    and one note naming the exception class when the sweep itself fails.
    """
    try:
        role = _swept("wrapper-debug", "alloc-record", _DEBUG_DIR,
                      () if _DEBUG_DIR == _HOST_DEBUG else (_DEBUG_DIR,))
        if role is None:
            return
        days = _debug_max_age_days(role[1] / 86400)
        cutoff = time.time() - days * 86400
        removed = 0
        unowned: list[str] = []
        failed: list[str] = []
        for d in _DEBUG_DIR.iterdir():
            try:
                if d.name == today or not _DEBUG_DAY_RE.fullmatch(d.name):
                    continue
                st = d.lstat()
                if not stat.S_ISDIR(st.st_mode):
                    continue
                if not _debug_day_owned(d):
                    if st.st_mtime < cutoff:
                        unowned.append(d.name)
                    continue
                records = _debug_day_records(d)
                if not records or max(os.lstat(d / r).st_mtime for r in records) >= cutoff:
                    continue
                git = role[3]._git_entry_below(d)  # the deletion module's one walk
                if git is not None:  # never deleted around a repository or a worktree (R-CLEANUP)
                    log(f"[wrapper] debug: skipped day dir {d.name} — it holds a .git entry ({git}); "
                        f"nothing deleted")
                    continue
                if _remove_debug_day(d):
                    removed += 1
                elif os.path.lexists(d):
                    failed.append(d.name)
            except OSError:
                # a candidate that vanished (a concurrent sweep took it) is
                # neither removed nor failed — skip it
                if os.path.lexists(d):
                    failed.append(d.name)
        if removed:
            log(f"[wrapper] debug: removed {removed} day dir(s) older than "
                f"{days:g} days")
        if unowned:
            log(f"[wrapper] debug: skipped {len(unowned)} unowned day dir(s) "
                f"(no debug header; e.g. {sorted(unowned)[0]})")
        if failed:
            log(f"[wrapper] debug: could not remove {len(failed)} day dir(s) "
                f"(e.g. {sorted(failed)[0]})")
    except Exception as e:  # noqa: BLE001 - retention is best-effort
        # the debug row is already written; name the class, never a traceback
        try:
            log(f"[wrapper] debug: day-dir expiry skipped ({type(e).__name__})")
        except Exception:  # noqa: BLE001 - never raise into debug_log
            pass
