#!/usr/bin/env python3
"""Single-shot Antigravity CLI (agy) wrapper — stream-json transport.

agy >= 1.1.8 print mode emits typed NDJSON (`--output-format stream-json`:
init / step_update / terminal result), so this wrapper spawns agy via the
shared _common._run_once (scrubbed child env, setsid, SIGTERM->SIGKILL
killpg escalation), parses the stream with _common.parse_agy_stream, and
classifies in a dedicated extract-then-classify driver (the generic
run_cli_with_retry classifies before extracting, which can't host agy's
answer-quotes-an-error-token cases). A deterministic read-audit digest of
the stream's tool_info events (_common.digest_agy_stream) is emitted on
stderr + into the run-log — REPORT-ONLY (policy stays with the caller).
The pre-2026-07-31 pty + sentinel + transcript-read transport was deleted
(git history has it); a version floor fails closed on agy < 1.1.8.

Isolation (--sandbox read-only, v2 since 2026-08-22 — spec
docs/superpowers/specs/2026-08-22-agy-readonly-v2-spec.md): agy runs as a
setup-once tools-allowlisted custom agent (`--agent`; review agent without
web tools, research agent with them under --web) with `--add-dir <cwd>` so
repository reads are auto-allowed; NO danger flag, NO settings transaction,
NO agy --sandbox on this path; admission by what the stream shows (`admit`).
The permissive baseline (`--sandbox` omitted, non-hardened) keeps the
exclusive settings guard and the version-gated danger flag. workspace-write
was removed 2026-07-25 (owner directive — 616 audited calls, 0 workspace-write).
Audit log: _logs/antigravity/audit.jsonl (gitignored).
"""
from __future__ import annotations

import argparse
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, Optional

import json

import _agy_settings
import _common
from _common import (_content_nonrepairable, load_pydantic_class,
                     strip_markdown_fences)

OFFSET_S = 10  # agy --print-timeout = max(timeout - OFFSET, MIN); _run_once kill is backstop
MIN_PRINT_TIMEOUT_S = 5
SERVER_CAP_RETRIES = 2


@dataclass
class AgyResult:
    final_answer: Optional[str]
    classification: str
    exit_code: int
    vendor_exit_code: int
    # Raw NDJSON stream text — preserved on EVERY return path (the run-log
    # transcript: the repair agent reads the literal vendor events).
    stream_output: str = ""
    stderr: str = ""
    extraction_error: Optional[str] = None
    validated: Optional[dict] = None
    # Deterministic fold of the stream's tool_info events (REPORT-ONLY).
    read_audit: Optional[dict] = None
    # Wall-clock of the vendor dispatch (set by _dispatch; audited as elapsed_s).
    elapsed: Optional[float] = None
    # The REAL vendor argv the dispatch ran (set by _dispatch) — main() audits and
    # run-logs this, never its own pre-dispatch placeholder (gate r1, 3 legs).
    cmd: Optional[list] = None


def _build_cmd(prompt, agy_sandbox, model, timeout, *, json_schema=None,
               skip_permissions=False, effort=None, agent=None, add_dir=None):
    """Canonical agy invocation — stream-json transport (agy >= 1.1.8).
    The prompt goes through CLEAN: no sentinel sealing (the 2026-07-31
    migration removed the pty-era completion marker, so the transport no
    longer mutates what the model sees). `effort` (low|medium|high) rides
    agy's own --effort flag (working since 1.1.10 — see _MODEL_FLAG_FLOOR);
    None omits the flag (vendor default). `add_dir` (v2): the validated --cwd
    is added to agy's workspace so repository READS are auto-allowed in print
    mode without the danger flag (ladder round 2, K2; writes stay denied, K5)."""
    print_to = max(timeout - OFFSET_S, MIN_PRINT_TIMEOUT_S)
    cmd = ["agy", "-p", prompt, "--output-format", "stream-json",
           "--print-timeout", f"{print_to}s"]
    if json_schema:
        cmd += ["--json-schema", json_schema]
    if agy_sandbox:
        cmd.append("--sandbox")
    if model:
        cmd += ["--model", model]
    if effort:
        cmd += ["--effort", effort]
    if agent:
        # The custom primary agent carries the read-only tool allowlist (v2
        # spec 2026-08-22-agy-readonly-v2): forbidden tools are ABSENT rather
        # than denied, so a review never produces the errored step that flips
        # agy's terminal status (#826/#839).
        cmd += ["--agent", agent]
    if add_dir:
        cmd += ["--add-dir", add_dir]
    if skip_permissions:
        cmd = _add_skip_permissions(cmd)
    return cmd


def _repair_cmd(cmd, err):
    """Rebuild the agy cmd with a one-shot JSON-repair hint appended to the
    -p arg (the vendor's own --json-schema repair turn failed to satisfy the
    LOCAL pydantic validation — belt-and-suspenders re-run, exactly once)."""
    new = list(cmd)
    i = new.index("-p") + 1
    new[i] = (new[i] + f"\n\nYour previous output was NOT valid JSON for the "
              f"schema ({err}). Output ONLY the corrected JSON object.")
    return new


def _classify_no_answer(stderr: str, signals, vendor_rc: int,
                        status=None) -> tuple:
    """Decide classification for the no-usable-answer case.

    The classify blob is stderr + STRUCTURAL stream signals + a synthetic
    status token (so an L2 pattern or a future extension entry can key on an
    unknown result status). It deliberately does NOT include the raw NDJSON
    stream (r1/R2): that stream carries model-authored prose, tool OUTPUT and
    tool PARAMETERS — the reviewed content itself — so a packet quoting a
    capacity phrase forced spurious `server-capacity` re-dispatches and one
    quoting an auth banner produced a terminal `oauth-env`. `signals` comes
    from `_common.agy_classify_signals` (typed error payloads only). The full
    raw stream still rides in `stream_output` for the run-log, so the repair
    agent's diagnostics are unchanged.
    """
    status_tok = f"agy result status={str(status)[:200]}" if status else ""
    parts = [stderr, *list(signals or []), status_tok]
    blob = "\n".join(t for t in parts if t and t.strip())
    if not blob.strip() and vendor_rc == 0:
        # Nothing structural to classify AND the vendor exited 0. A nonzero rc
        # still goes through classify() so the L1 vendor-exit map keeps its
        # say (a silent vendor failure that only signals through its rc must
        # not be swallowed by this short-circuit).
        return "extraction-error", _common.EXIT_CLI_FAIL
    cls = _common.classify(
        "antigravity", stderr=blob, stdout="",
        exit_code=_common.EXIT_CLI_FAIL, vendor_exit_code=vendor_rc,
    )
    return cls, _common.map_classification_to_exit(cls)


# agy 1.1.3 flipped headless (-p) permission policy: a tool needing a
# confirmation is soft-denied UNCONDITIONALLY (the allow-list is not consulted
# in print mode — verified: allow-rule forms, settings modes, env vars, and a
# PreToolUse decision:allow hook all fail). agy emits this distinctive line:
#   "... a tool required the "read_file" permission that headless mode cannot
#    prompt for, so it was auto-denied."
_HEADLESS_SOFTDENY_SIGNATURE = "headless mode cannot prompt"


def _is_headless_softdeny(text) -> bool:
    """True when agy's output carries the 1.1.3+ headless soft-deny signature.
    Targeted — matches ONLY that vendor message, so a version where the
    allow-list works (<=1.1.2 and any future fix) never trips it, and a plain
    empty/extraction failure is untouched."""
    return _HEADLESS_SOFTDENY_SIGNATURE in (text or "").lower()


# agy CLI-side answer fold (observed 2026-07-22, repro A-F): print output AND
# the transcript PLANNER_RESPONSE/DONE record are BOTH capped (~4KB observed)
# with a literal own-line `<truncated N bytes>` / `<truncated N lines>` marker
# replacing the folded middle (format strings live in the agy binary; every
# transcript record type is capped, incl. VIEW_FILE tool results). The full
# text is NOT preserved anywhere agy-side -> a marker-carrying answer is LOSSY
# and unrecoverable at this layer. Own-line anchor keeps a mid-sentence QUOTE
# of the marker from tripping the gate (observed folds are always own-line).
# Loophole route: agy's write_file is NOT subject to the fold (verified: 24KB
# file intact) -> the SKILL's absolute-path output-file contract, which needs
# the write-capable permissive baseline (unavailable on a hardened install and
# forbidden on the cross-family-review leg -> compact re-dispatch there).
_AGY_TRUNCATION_MARKER_RE = re.compile(r"(?m)^[ \t]*<truncated \d+ (?:bytes|lines)>[ \t]*$")


def _add_skip_permissions(cmd):
    """Insert --dangerously-skip-permissions right after argv[0] (the
    empirically-verified working position `agy --dangerously-skip-permissions
    -p ...`). Idempotent. This is the ONLY internal caller of the danger flag
    — user argv can never supply it (argparse in main() has no such option)."""
    if "--dangerously-skip-permissions" in cmd:
        return list(cmd)
    return list(cmd[:1]) + ["--dangerously-skip-permissions"] + list(cmd[1:])


# Version at/after which agy's headless (-p) mode soft-denies tools that need a
# confirmation. Floor, not a pin: the gate below fires for this version and up.
# STATUS 2026-08-22 (gate r5 resync): on 1.1.17 the PREMISE is dead — headless
# DOES honour permissions.allow (probe F3) — but the flag is still needed on
# hosts WITHOUT a read_file(*) allow preset (probe F1), and it does NOT void the
# deny transaction (Deny > dsp: arm A command, probe G write_file). Retiring the
# flag for good = the allow-merge follow-up slice (ledger W-05); until then this
# floor stays, and the flag is harmless under the allowlist agent (no dangerous
# tool exists to auto-approve).
_HEADLESS_SOFTDENY_FLOOR = (1, 1, 3)


def _parse_agy_version(text):
    """Extract the first dotted numeric version tuple from `agy --version`
    output (e.g. '1.1.3' -> (1, 1, 3)); None if unparseable."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(g) for g in m.groups()) if m else None


# Floor for the stream-json transport (this wrapper's ONLY transport since the
# 2026-07-31 migration; pty+sentinel deleted). Fail-CLOSED: an older or
# unprobeable agy stops loudly with a `config-conflict` (Task 6) — a silent
# fallback would change the prompt shape mid-fleet (the old sentinel sealing
# mutated the prompt) and mask a vendor regression from the repair loop.
_STREAM_JSON_FLOOR = (1, 1, 8)

# Floor for HONORED --model/--effort flags. Before 1.1.10 agy applied both
# flags AFTER model configuration had already initialized, so an interactive
# OR headless (-p) run silently fell back to the persisted/default model —
# a requested tier pin dispatched the shallow default with no error (vendor
# changelog, 1.1.10 2026-08-03; --effort itself also ships there). Fail-CLOSED
# like the stream floor, but ONLY when the caller actually passed --model or
# --effort: a pin that would be silently VOID is refused loudly
# (`config-conflict`, run `agy update`), while pinless dispatches keep working
# on 1.1.8/1.1.9.
_MODEL_FLAG_FLOOR = (1, 1, 10)

# ---------------------------------------------------------------------------
# v2 read-only leg (spec docs/superpowers/specs/2026-08-22-agy-readonly-v2-spec.md,
# three-family consultation 2026-08-22): setup-once tools-allowlisted agents,
# `--add-dir <cwd>` for reads, no danger flag / settings transaction / agy
# --sandbox on the read-only path, status-independent admission. Two agents:
# the REVIEW agent has no web tool (a review must have no egress); the
# RESEARCH agent (`--web`) keeps read_url_content / search_web.
AGY_V2_FLOOR = (1, 1, 18)   # `--add-dir` read auto-allow measured on 1.1.18 only (ladder round 2, K2/K5)
AGY_REVIEW_AGENT = "triad-readonly-review"
AGY_RESEARCH_AGENT = "triad-readonly-research"
AGY_REVIEW_TOOLS = ("view_file", "grep_search", "list_dir", "find_by_name", "finish")
AGY_RESEARCH_TOOLS = ("view_file", "grep_search", "list_dir", "find_by_name",
                      "read_url_content", "search_web", "finish")
# Admission rule 5: an errored step is tolerated only when it names one of these
# READ tools (the research agent additionally tolerates its two web tools).
AGY_READ_TOOLS_ADMIT = frozenset({"view_file", "grep_search", "list_dir", "find_by_name"})
AGY_WEB_TOOLS_ADMIT = frozenset({"read_url_content", "search_web"})

_AGENT_BODY_RULES = (
    "Read files with view_file, search with grep_search using a SPECIFIC\n"
    "subdirectory as SearchPath (never a repository root; add Includes globs when\n"
    "you can). Open only paths you have confirmed exist — a file the prompt's\n"
    "design text names as planned or to-be-created does not exist yet (a file\n"
    "shown as a new-file hunk in a diff exists only when that branch is checked\n"
    "out). Do not pass view_file paging arguments beyond the documented ones, and\n"
    "do not page past the end of a file. When asked for JSON, return only the JSON.\n"
)


def _agent_body(name: str, description: str, tools, persona: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "tools:\n" + "".join(f"  - {t}\n" for t in tools) +
        "mainAgent: true\n"
        "subagent: false\n"
        "model: inherit\n"
        "commandExecutionPolicy: off\n"
        "---\n"
        f"{persona}\n"
        f"{_AGENT_BODY_RULES}"
    )


AGENT_BODIES = {
    AGY_REVIEW_AGENT: _agent_body(
        AGY_REVIEW_AGENT,
        "Read-only review worker. Reads files and searches the repository; has "
        "no shell, no file-writing tool, no MCP/browser tool and no web access.",
        AGY_REVIEW_TOOLS,
        "You are a read-only worker (a code reviewer, as the prompt says). You\n"
        "have no shell, cannot write files and have no web access.",
    ),
    AGY_RESEARCH_AGENT: _agent_body(
        AGY_RESEARCH_AGENT,
        "Read-only research worker. Reads files, searches the repository and "
        "fetches web pages; has no shell, no file-writing tool and no MCP/browser tool.",
        AGY_RESEARCH_TOOLS,
        "You are a read-only worker (a researcher or a reviewer, as the prompt\n"
        "says). You have no shell and cannot write files; fetch web pages with\n"
        "read_url_content / search_web only when the prompt allows it.",
    ),
}


def setup_agents(d: Path) -> list:
    """`--setup-agents`: write BOTH agent definitions under `d` (per-process
    temp + os.replace; overwrites whatever is there). Run once per host at
    setup time — never by a dispatch (v2: no per-dispatch ensure, no lock, no
    ownership marker; a dispatch only CHECKS, see check_agent_file)."""
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in AGENT_BODIES.items():
        target = d / f"{name}.md"
        fd, tmp = tempfile.mkstemp(prefix=f"{name}.md.", suffix=".tmp", dir=str(d))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        written.append(target)
    return written


def check_agent_file(d: Path, name: str) -> bool:
    """Dispatch precondition: the agent file exists and is byte-identical to the
    embedded body (a CRLF-normalized copy is drift). Absent / drifted /
    unreadable -> False (the caller refuses with config-conflict naming
    `--setup-agents`)."""
    body = AGENT_BODIES.get(name)
    if body is None:
        return False
    try:
        return (d / f"{name}.md").read_bytes() == body.encode("utf-8")   # bytes, not text (gate r2)
    except OSError:
        return False


class Admission(NamedTuple):
    ok: bool
    reason: str
    errored_reads: list     # errored tool steps that named an allowed read tool
    forbidden: list         # tool names outside the allowlist (capped)
    omitted: int            # census hits beyond the cap (counted, not stored)


_UNNAMED_TOOL_STEP = "<unnamed tool step>"


def _census(events, allowlist, read_set):
    """(forbidden, omitted, errored_reads, errored_other) over one attempt's
    parsed events — admission rule 4 plus the errored-step split rule 5 needs.
    Runs on EVERY attempt (schema-repair / capacity retries included) so a
    forbidden call in an earlier attempt is never erased by a clean retry."""
    allowed = set(allowlist)
    forbidden: list = []
    omitted = 0
    errored_reads: list = []
    errored_other: list = []
    for ev in events or []:
        su = ev.get("step_update") if isinstance(ev, dict) else None
        if not isinstance(su, dict) or su.get("step_type") != "tool":
            continue
        names = set()
        tn = su.get("tool_name")
        if isinstance(tn, str) and tn:
            names.add(tn)
        ti = su.get("tool_info")
        if isinstance(ti, dict) and isinstance(ti.get("name"), str) and ti["name"]:
            names.add(ti["name"])
        if not names:
            names.add(_UNNAMED_TOOL_STEP)
        errored = su.get("state") == "ERROR" or (isinstance(ti, dict) and bool(ti.get("error")))
        for n in sorted(names):
            if n not in allowed:
                if n in forbidden:
                    continue
                if len(forbidden) < _common._AGY_DIGEST_LIST_CAP:
                    forbidden.append(n)
                else:
                    omitted += 1
            elif errored:
                bucket = errored_reads if n in read_set else errored_other
                if n not in bucket:
                    bucket.append(n)
    return forbidden, omitted, errored_reads, errored_other


def admit(stream_text, events, result, *, allowlist, read_set, prior_forbidden=(),
          vendor_rc=0) -> Admission:
    """v2 admission — judged by what the STREAM shows, never by the vendor's
    terminal status alone (spec § Admission; consultation consensus: the
    `status != SUCCESS` discard threw away finished reviews).

    1. Framing: every non-blank stdout line must decode to a JSON object —
       anything else makes the run unusable (one blanket rule, no per-shape
       enumeration).
    2. Exactly one terminal `result` event.
    4. Census: every tool name on a tool step (`tool_name` AND
       `tool_info.name`, a nameless step counts as a name outside the
       allowlist) must be in `allowlist`; the list is capped like the digest.
    5. Status: SUCCESS with vendor rc 0 -> ok; anything else (a non-SUCCESS
       status OR a non-zero vendor rc, gate r1) is admitted ONLY when at least
       one errored tool step EXPLAINS it and every errored step named an
       allowed READ tool (`read_set`) — an errored read (paging overshoot,
       nonexistent path, root-grep timeout) is a prompt-quality signal, not a
       discard; an errored non-read step rejects, and a degraded run with NO
       errored step (run-level error / cancel / cut) rejects too (gate r3:
       never admit a possibly partial answer on nothing).
       (The caller adds the read-blind guard: such a run must also have read
       something — `files_read` non-empty in the digest.)
    Every vendor-controlled string on the reason is capped at
    `_AGY_DIGEST_KEY_CAP` (gate r1, claude: the engine closed that class).
    (Rule 3 — local validation of the answer — is the caller's existing
    `_validate_structured*` path.)"""
    for idx, line in enumerate((stream_text or "").split("\n"), 1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            # name the offending line so a stray vendor stdout line is diagnosable
            # (gate r2, claude); the excerpt is capped and ASCII-escaped
            excerpt = json.dumps(s[:_common._AGY_DIGEST_KEY_CAP], ensure_ascii=True)
            return Admission(False, f"stream line {idx} is not a JSON object (unusable run): {excerpt}",
                             [], [], 0)
    n_results = sum(1 for ev in events or []
                    if isinstance(ev, dict) and ev.get("event") == "result")
    if n_results != 1:
        return Admission(False, f"{n_results} result events in the stream (expected exactly 1)",
                         [], [], 0)
    forbidden, omitted, errored_reads, errored_other = _census(events, allowlist, read_set)
    for n in prior_forbidden:          # an earlier attempt's forbidden call is never erased
        if n not in forbidden:
            forbidden.append(n)
    cap = _common._AGY_DIGEST_KEY_CAP
    if forbidden:
        shown = json.dumps([n[:cap] for n in forbidden[:8]], ensure_ascii=True)
        more = len(forbidden) - 8 + omitted
        return Admission(False, f"tool(s) outside the allowlist appeared in the stream: {shown}"
                                f"{f' (+{more} more)' if more > 0 else ''} — agy fell back to its "
                                f"default agent or the model slipped; answer quarantined",
                         errored_reads, forbidden, omitted)
    status = result.get("status") if isinstance(result, dict) else None
    shown_status = str(status)[:cap]
    if status != "SUCCESS" or vendor_rc not in (0, None):
        tag = f"terminal status {shown_status!r} rc={vendor_rc}"
        if errored_other:
            shown = json.dumps([n[:cap] for n in errored_other[:8]], ensure_ascii=True)
            return Admission(False, f"{tag} with errored non-read step(s) {shown}",
                             errored_reads, [], omitted)
        if errored_reads:
            return Admission(True, f"{tag} admitted: every errored step is an allowed read "
                                   f"{json.dumps([n[:cap] for n in errored_reads[:8]], ensure_ascii=True)}",
                             errored_reads, [], omitted)
        # nothing in the stream explains the degradation (run-level error / cancel /
        # cut / bare rc!=0): a possibly partial answer is not admitted (gate r3)
        return Admission(False, f"{tag} with no errored tool step in the stream — nothing "
                                f"explains the degradation; answer quarantined", [], [], omitted)
    return Admission(True, "ok", errored_reads, [], omitted)


def agents_dir() -> Path:
    """Where the wrapper WRITES the agent definition: agy's documented GLOBAL
    custom-agent discovery dir (~/.gemini/config/agents; measured 2026-08-22:
    only this path resolves `--agent <name>` in print mode — workspace
    `.agents/` is not loaded there, ladder round 2 K1). `AGY_AGENTS_DIR` is a
    TEST hook for the file location only; on a real host pointing it elsewhere
    makes agy fall back to its default agent, which the admission census then
    rejects. Logged whenever it is set; never a remediation."""
    env = os.environ.get("AGY_AGENTS_DIR")
    return Path(env) if env else Path.home() / ".gemini" / "config" / "agents"


def _lock_wait_seconds(raw) -> float:
    """`AGY_SETTINGS_LOCK_TIMEOUT` as a finite non-negative wait (seconds);
    anything else — unparseable, inf, nan, negative — is 30 (gate r6)."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 30.0
    return v if math.isfinite(v) and v >= 0 else 30.0


def _probe_agy_version(agy_bin):
    """One `agy --version` probe (scrubbed env, 15s). Returns the parsed
    (major, minor, patch) tuple, or None on OSError / non-zero rc /
    unparseable output. Callers interpret None per their own fail
    direction: the stream floor fail-CLOSES (stop), the skip-permissions
    gate fail-SAFES (no danger flag)."""
    try:
        proc = subprocess.run([agy_bin, "--version"], capture_output=True,
                              text=True, timeout=15,
                              env=_common.scrubbed_child_env())
    except (OSError, subprocess.SubprocessError):
        return None
    # Fail-safe (merge-review F4/Q4): a non-zero --version exit is an
    # unreliable read.
    if proc.returncode != 0:
        return None
    return _parse_agy_version(proc.stdout)


def _agy_needs_skip_permissions(ver) -> bool:
    """True when the probed agy version soft-denies headless tools and the
    operator has NOT opted out (AGY_NO_HEADLESS_AUTOAPPROVE=1). Pure on the
    version tuple (probed ONCE in main); None fail-safes to False (never
    enable the isolation-voiding flag on an unreliable read)."""
    if os.environ.get("AGY_NO_HEADLESS_AUTOAPPROVE") == "1":
        return False
    return ver is not None and ver >= _HEADLESS_SOFTDENY_FLOOR


def _validate_structured_with_trigger(result, answer, pydantic_cls):
    """Local pydantic validation over the vendor's --json-schema output.
    PREFER result['structured_output'] (the vendor already schema-checked and
    self-repaired it — spike P4 showed an internal repair turn); fall back to
    the raw response text ONLY when it is ABSENT (vendor drift guard — see r4
    below for why "absent", not "unusable"). Returns
    (True, validated_dict, False, NonrepairableTrigger.NONE) or
    (False, error_message_str, nonrepairable, trigger) — same contract the
    schema-repair re-run and EXIT_SCHEMA_FAIL path consume, plus the
    non-repairable bit and WHICH trigger produced it.

    r1/R11: when structured_output was PRESENT but failed validation, that
    error is what the schema-repair hint must carry. It used to be discarded
    in favour of the raw-response fallback's error, which for the normal shape
    (prose in `response`, the real payload in `structured_output`) is a
    generic 'Invalid JSON: expecting value' — the repair turn was told its
    output was not JSON when the actual violation was a missing/invalid FIELD,
    so it had nothing actionable to fix.

    r2 (3-family): the `nonrepairable` bit is THREADED from the live pydantic
    exception (`_common.validate_response_detail`), never recomputed by
    re-scanning the error STRING this function returns. That string embeds
    pydantic's `input_value=...` AND is truncated and concatenated here, so a
    substring test over it both false-POSITIVES on a reply that merely quotes
    the marker and could false-NEGATIVE on a genuine arm whose message fell
    past the 600-char cap.

    r4 (codex must-fix + agy Critical, 2-family same-defect convergence) —
    the GENERAL rule, superseding r3's arm-scoped form: the raw-response
    fallback is allowed ONLY when `structured_output` is ABSENT. Once the
    vendor emitted a schema-checked object, that object IS the answer channel;
    a raw string that parses is a DIVERGENT second answer, never a recovery
    for the first. r3 suppressed the fallback only on a NON-REPAIRABLE
    structured failure, which left the other cell of the cross-product open:
    a structured payload with BLOCKING content plus a merely REPAIRABLE shape
    slip, next to a clean SAFE raw string, still returned ok/exit 0 with the
    raw object — the blocking payload discarded with no repair turn, no skip
    log, no exit 66 and no run-log at all (`emit_run_log` writes on failure
    only), i.e. the silent leg loss leg-contracts § Verdict binding
    obligation 4 forbids. Both cells now fail LOUD, and they differ only in
    what happens next:

      - REPAIRABLE  -> (False, err, False): the ONE schema-repair retry runs.
        That retry re-dispatches the vendor and re-validates STRUCT-FIRST, so
        it is the recovery channel — the raw string is never promoted into
        one.
      - NON-REPAIRABLE -> (False, err, True): the caller skip-logs and takes
        EXIT_SCHEMA_FAIL (unchanged r3 behavior — replaying that error would
        invite a severity downgrade).

    Struct ABSENT is unchanged: the raw string is the only payload, so it is
    validated directly and its own non-repairable bit is threaded out.

    r7 (claude must-fix) — BOTH CHANNELS are CONTENT-probed. r4's divergence
    rule is UNCHANGED (a present-but-invalid structured payload never resolves
    through the raw string), but "never resolve through it" had silently become
    "never LOOK at it": on the struct-PRESENT path only `json.dumps(structured)`
    reached `validate_response_detail`, so the raw `response` was content-probed
    on the struct-ABSENT path alone. A blocker legible ONLY in the raw channel —
    a non-blocking structured payload with a merely repairable shape slip, next
    to a raw string carrying a must-fix finding — therefore bought the one
    repair turn, and a clean attempt 2 was accepted exit 0 with the blocker
    recorded nowhere (`emit_run_log` is failure-only). The raw answer is now run
    through the same duck-typed `_content_nonrepairable` hook and OR'd into
    `nonrepairable`. This only ever WIDENS refusal: it is reached solely after
    the structured payload has already FAILED, and it cannot turn a failure into
    an acceptance.

    r8 (claude must-fix) — the refusal LABEL is trigger-accurate. It read
    `" (non-repairable arm)"` whenever the OR'd bit was true, so a
    CONTENT-triggered refusal (a field slip suppresses the marked arm; an
    unparseable envelope never reaches one; a blocker legible only in the raw
    channel) was reported as the ARM in `extraction_error` — the very field a
    consumer inspects when deciding how to re-ask the leg. The two bits now
    come through from `_common.validate_response_with_trigger`, the raw
    channel's blocker composes in as a CONTENT bit, and the label is rendered
    by the shared `_common.nonrepairable_log_marker` so this driver and the
    shared engine cannot spell the token differently."""
    structured = result.get("structured_output") if isinstance(result, dict) else None
    if structured is not None:
        ok, payload, nonrepairable, trigger = _common.validate_response_with_trigger(
            json.dumps(structured, ensure_ascii=False, default=str), pydantic_cls)
        if ok:
            return ok, payload, False, _common.NonrepairableTrigger.NONE
        # Bounded (this string is appended to the repair prompt) and
        # attributed to the right source (r1/R11): the structured violation is
        # the actionable one, the raw fallback's generic "Invalid JSON:
        # expecting value" is not. The suppression NOTE is part of the message
        # so the run-log records WHY only one payload was judged.
        struct_err = str(payload)[:600]
        # r7: probe the OTHER channel's content too. Same cleaning the
        # struct-ABSENT path applies, so both channels are judged on identical
        # input; the hook itself is failure-tolerant (absent / raising -> False).
        raw_blocking = _content_nonrepairable(
            strip_markdown_fences(answer or ""), pydantic_cls)
        if raw_blocking:
            trigger |= _common.NonrepairableTrigger.CONTENT
        label = f" {_common.nonrepairable_log_marker(trigger)}" if trigger else ""
        note = " (raw channel carries blocking content)" if raw_blocking else ""
        return False, (f"structured_output invalid: {struct_err} "
                       f"| raw-response fallback suppressed: structured_output "
                       f"present{label}{note}"), bool(trigger), trigger
    return _common.validate_response_with_trigger(answer, pydantic_cls)


def _validate_structured_detail(result, answer, pydantic_cls):
    """(ok, validated_dict_or_error_string, nonrepairable) — 3-tuple façade
    over `_validate_structured_with_trigger`, for callers that drive the
    schema-repair retry but do not report the trigger."""
    ok, payload, nonrepairable, _ = _validate_structured_with_trigger(
        result, answer, pydantic_cls)
    return ok, payload, nonrepairable


def _validate_structured(result, answer, pydantic_cls):
    """(ok, validated_dict_or_error_string) — 2-tuple façade over
    `_validate_structured_with_trigger` for callers that do not drive the
    schema-repair retry."""
    ok, payload, _, _ = _validate_structured_with_trigger(
        result, answer, pydantic_cls)
    return ok, payload


def _run_agy_with_retry(cmd, prompt, timeout, *, cwd=None,
                        repair_mode=False, pydantic_cls=None,
                        allow_skip_retry=True, admission=None,
                        cmd_box=None) -> AgyResult:
    """Dedicated extract-then-classify driver over the stream-json transport.
    See the plan's decision table (2026-07-31) — ORDER MATTERS. Spawn =
    _common._run_once(classify_and_log=False): shared scrubbed env + setsid +
    SIGTERM->SIGKILL killpg escalation; classification and the canonical
    one-line summary stay THIS driver's job."""
    if not repair_mode:
        _common.prune_stale_run_logs("antigravity")

    # F-Q2: these three retry budgets are INDEPENDENT — schema_repaired,
    # skip_retried, and the server-capacity budget (max_retries/server_attempt)
    # each gate a different failure shape and do not share state. In
    # particular, schema repair fires exactly ONCE regardless of repair_mode;
    # repair_mode only disables the server-capacity retry (max_retries=0),
    # never the one-shot schema repair or the one-shot soft-deny retry.
    max_retries = 0 if repair_mode else SERVER_CAP_RETRIES
    server_attempt = 0
    schema_repaired = False   # one-shot local-validation repair re-run (Task 5)
    skip_retried = False      # one-shot headless soft-deny -> skip-permissions retry
    # r1/R4: one digest per ATTEMPT, aggregated on every return path. Emitting
    # only the LAST attempt's digest let a short-circuiting retry CONCEAL an
    # earlier attempt's reads — the review SKILL's mechanical read-audit gate
    # then VOIDed a leg that had demonstrably read the packet.
    attempt_digests: list = []
    # v2 read-only path: `admission` = (allowlist, read_set). Forbidden names
    # accumulate across attempts so a schema-repair or capacity retry cannot
    # erase an earlier attempt's evidence.
    forbidden_seen: list = []
    while True:
        if cmd_box is not None:
            cmd_box[0] = list(cmd)   # the REAL argv of the attempt that runs (gate r3, codex)
        rr = _common._run_once("antigravity", cmd, cwd, timeout,
                               classify_and_log=False)
        stream = rr.stdout
        events, result = _common.parse_agy_stream(stream)
        if admission is not None:
            for _n in _census(events, admission[0], admission[1])[0]:
                if _n not in forbidden_seen:
                    forbidden_seen.append(_n)
        attempt_digests.append(_common.digest_agy_stream(events, result))
        audit = _common.merge_agy_digests(attempt_digests)
        if rr.exit_code == _common.EXIT_TIMEOUT:
            # Killed short-circuit FIRST: a killed run's stream is a partial
            # prefix — never trust a result event parsed out of it.
            return AgyResult(None, "timeout", _common.EXIT_TIMEOUT,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit)
        # r1/R3: every field below is vendor-controlled. A non-dict result or
        # a non-string `response` (the model can emit a JSON object there)
        # must degrade to "no usable answer" — CLASSIFIED, audited, run-logged
        # — never an AttributeError traceback that costs the caller its
        # summary line, audit row and run-log.
        status = result.get("status") if isinstance(result, dict) else None
        raw_answer = result.get("response") if isinstance(result, dict) else None
        answer = raw_answer if isinstance(raw_answer, str) else ""
        bad_answer_type = (raw_answer is not None
                           and not isinstance(raw_answer, str))
        if result is not None and answer.strip():
            if admission is not None:
                # v2 ADMISSION (spec § Admission): judged by what the stream
                # shows — framing, one result, allowlist census, errored steps
                # ⊆ allowed reads — never by the vendor status alone (the
                # `status != SUCCESS` discard below threw away finished reviews:
                # consultation 2026-08-22, r9 attempt 1).
                adm = admit(stream, events, result, allowlist=admission[0],
                            read_set=admission[1], prior_forbidden=forbidden_seen,
                            vendor_rc=rr.vendor_exit_code)
                degraded = status != "SUCCESS" or rr.vendor_exit_code != 0
                read_evidence = (audit.get("files_read") or audit.get("files_read_omitted")
                                 or audit.get("web") or audit.get("web_omitted"))   # web reads count (gate r2, 3 legs)
                if adm.ok and (degraded or adm.errored_reads) and not read_evidence:   # gate r3: not keyed on the vendor's status flip alone
                    # READ-BLIND guard (gate r1, agy must-fix + claude): a degraded
                    # run whose every read errored — no --add-dir / no allow
                    # preset — produced its answer without reading anything.
                    remedy = ("pass --cwd so --add-dir grants repository reads, or allow "
                              "read_file(*) / read_url(*) on this host" if degraded else
                              "every attempted read errored although reads are granted — check the "
                              "read_attempts outcomes (nonexistent paths / paging overshoot)")
                    adm = Admission(False, f"read-blind run: {adm.reason}; no successful read in the "
                                           f"digest (files_read and web empty) — {remedy}",
                                    adm.errored_reads, [], adm.omitted)
                if not adm.ok:
                    _common.log(f"admission refused: {adm.reason}")   # names are ASCII-escaped by admit()
                    snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                    return AgyResult(None, "vendor-error", _common.EXIT_TERMINAL,
                                     rr.vendor_exit_code, stream_output=stream,
                                     stderr=rr.stderr, read_audit=audit,
                                     extraction_error=(f"admission refused: {adm.reason}; "
                                                       f"quarantined answer: {snippet}"))
                if degraded or adm.errored_reads:
                    _common.log("[wrapper] antigravity admitted-with-errored-steps "
                                f"n={len(adm.errored_reads)} "
                                f"tools={json.dumps([n[:_common._AGY_DIGEST_KEY_CAP] for n in adm.errored_reads[:8]], ensure_ascii=True)} "
                                f"status={str(status)[:_common._AGY_DIGEST_KEY_CAP]!r} rc={rr.vendor_exit_code}")
            elif rr.vendor_exit_code != 0 or status != "SUCCESS":
                # rc gate (kept) + status gate (NEW): the status vocabulary
                # beyond SUCCESS is unobserved — a non-SUCCESS answer is never
                # a silent ok and never fed to classify (a real answer can
                # quote error-shaped tokens). Bounded quarantined copy rides
                # in extraction_error for the run-log.
                #
                # "vendor-error" is a DISTINCT token, deliberately absent from
                # _common.CLASSIFICATION_TOKENS (surface-not-repair, P4
                # 2026-07-11): this condition (rc!=0 or non-SUCCESS status
                # WITH a real answer) is something a classifier patch cannot
                # express, so it is emitted directly here rather than routed
                # through classify(). Reusing "extraction-error" for this case
                # would mandate a MANDATORY repair-agent dispatch per the
                # dispatch SKILL's Hard rule 8 — wrong: there is nothing for
                # the repair agent to patch, this is a real answer the caller
                # should just see.
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "vendor-error", _common.EXIT_TERMINAL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 extraction_error=(
                                     f"vendor rc={rr.vendor_exit_code} "
                                     f"status={status!r} returned a non-empty "
                                     f"answer; surfaced as vendor-error. "
                                     f"quarantined answer: {snippet}"))
            if _AGY_TRUNCATION_MARKER_RE.search(answer):
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "truncated-answer", _common.EXIT_TERMINAL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 extraction_error=(
                                     "agy folded the answer mid-body "
                                     "(own-line <truncated N bytes|lines> marker). "
                                     f"quarantined answer: {snippet}"))
            if pydantic_cls is None:
                return AgyResult(answer, "ok", _common.EXIT_OK,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit)
            ok, payload, nonrepairable, trigger = _validate_structured_with_trigger(
                result, answer, pydantic_cls)
            if ok:
                return AgyResult(answer, "ok", _common.EXIT_OK,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 validated=payload)
            # Same non-repairable opt-out `_common.py`'s Layer 4 honours (see
            # `_common.NONREPAIRABLE_MARKER`): this driver is a SECOND copy of
            # the schema-repair loop, and it is the one the review legs
            # actually run `--pydantic verdict_schema:LegVerdict` through — a
            # guard only on the shared engine would leave the hole open
            # exactly where it matters. `_repair_cmd` replays `payload` (the
            # validation error) into the re-dispatch, so a marked arm must
            # never reach it.
            #
            # STRUCTURAL, not a substring over `payload` (r2 3-family
            # finding): the rendered pydantic error embeds the vendor's own
            # `input_value=...`, so a reply that merely QUOTES the marker
            # would steal its own repair turn. See
            # `_validate_structured_detail`.
            if not schema_repaired and not nonrepairable:
                cmd = _repair_cmd(cmd, payload)
                schema_repaired = True
                continue
            if nonrepairable:
                # Same MECHANICAL token as the shared engine's Layer 4 (r8
                # claude must-fix), rendered by the same shared helper so the
                # two loops cannot drift: this branch fires for a CONTENT-gated
                # refusal where NO arm ran as readily as for a marked arm, and
                # r6's honest-but-vague disjunction still made the consumer
                # guess which. The `[NONREPAIRABLE` prefix is preserved, so
                # every pre-r8 grep keeps matching.
                _common.log("schema validation non-repairable "
                            f"{_common.nonrepairable_log_marker(trigger)} "
                            "— skipping repair retry")
            # r4 (claude Minor) — STDOUT QUARANTINE. `main()` writes
            # `final_answer` to stdout on this path, so the very reply
            # `_validate_structured_detail` refused to ACCEPT still rode the
            # channel a consumer captures (`agy-r<N>.out`): a clean SAFE
            # verdict readable as admissible evidence, while the blocking
            # payload sat only in the run-log. Same idiom the vendor-error /
            # truncated-answer paths use — no answer, a bounded copy in
            # `extraction_error`, the full stream still in the run-log.
            #
            # Scope = exactly the two shapes where the stdout reply is NOT the
            # vendor's schema-checked channel: a MARKED arm (whatever payload
            # carried it), or a SUPPRESSED raw fallback (structured_output
            # present). A struct-ABSENT repairable failure keeps the
            # pre-existing pass-through: there the failing text is the
            # vendor's only answer, with no second payload to diverge from,
            # and surfacing it stays a debugging aid.
            structured_present = (isinstance(result, dict)
                                  and result.get("structured_output") is not None)
            if nonrepairable or structured_present:
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "schema-fail", _common.EXIT_SCHEMA_FAIL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 extraction_error=(f"schema: {payload} "
                                                   f"quarantined answer: {snippet}"))
            return AgyResult(answer, "schema-fail", _common.EXIT_SCHEMA_FAIL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             extraction_error=f"schema: {payload}")
        # ── no usable answer from here ──
        # Structural failure signals ONLY (typed tool errors / error_message
        # steps). The raw stream is deliberately NOT part of either the
        # soft-deny match or the classify blob (r1/R2 + the adjudicated F2
        # structural fix): it carries the reviewed content, so quoted text
        # could steer a retry or a terminal classification.
        signals = _common.agy_classify_signals(events, result)
        softdeny_blob = "\n".join([rr.stderr or "", *signals])
        # allow_skip_retry=False on the v2 read-only path: it carries NO danger
        # flag by design, so the soft-deny re-dispatch (which would insert it)
        # must never fire there; the permissive baseline keeps it.
        if (allow_skip_retry and not skip_retried and _is_headless_softdeny(softdeny_blob)
                and os.environ.get("AGY_NO_HEADLESS_AUTOAPPROVE") != "1"):
            # P2 evidence: the jetski soft-deny notice coexists with a
            # SUCCESS+empty result — so this retry covers the empty-response
            # path, not only the missing-result path.
            #
            # SECURITY (owner-authorized 2026-07-18; RE-MEASURED 2026-08-22, gate
            # r5): on 1.1.17 --dangerously-skip-permissions does NOT void the
            # per-call deny transaction (Deny > dsp: arm A command(*), probe G
            # write_file(*)) — the 1.1.3-era "voids" wording is history. The
            # retry is still suppressed in agent mode (allow_skip_retry=False)
            # because an allowlisted agent gains nothing from it. Opt out with
            # AGY_NO_HEADLESS_AUTOAPPROVE=1 (checked just above).
            #
            # Retry ONLY when the flag actually CHANGES the command (the
            # adjudicated F2 structural fix). On every dispatchable build the
            # stream floor (1.1.8) is above the soft-deny floor (1.1.3), so
            # main() already set the flag on call #1 and _add_skip_permissions
            # is idempotent — the retry then re-ran a BYTE-IDENTICAL command,
            # silently doubling the vendor call with no possible change in
            # outcome. skip_retried is consumed either way (one-shot).
            skip_retried = True
            new_cmd = _add_skip_permissions(cmd)
            if new_cmd != cmd:
                cmd = new_cmd
                continue
            _common.log("headless soft-deny signature but the flag is already "
                        "present — skipping an identical re-run")
        if result is not None and status == "SUCCESS":
            # SUCCESS + empty response (spike P2, rc=0): a failed task the
            # vendor reports as success. Never a silent empty ok.
            note = "empty-answer-body"
            if bad_answer_type:
                note += (f" (non-string response payload: "
                         f"{type(raw_answer).__name__})")
            return AgyResult(None, "extraction-error", _common.EXIT_CLI_FAIL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             extraction_error=note)
        cls, code = _classify_no_answer(rr.stderr, signals,
                                        rr.vendor_exit_code, status)
        if cls == "server-capacity" and server_attempt < max_retries:
            _server_cap_backoff(server_attempt)
            server_attempt += 1
            continue
        return AgyResult(None, cls, code, rr.vendor_exit_code,
                         stream_output=stream, stderr=rr.stderr,
                         read_audit=audit)


def _server_cap_backoff(attempt: int) -> None:
    """Politeness sleep before a server-capacity retry (FIX 5). Suppressible
    via AGY_NO_BACKOFF=1 so unit/integration tests don't sleep 15s+."""
    if os.environ.get("AGY_NO_BACKOFF") == "1":
        return
    idx = min(attempt, len(_common.SERVER_CAP_BACKOFF_S) - 1)
    time.sleep(_common.SERVER_CAP_BACKOFF_S[idx])


def _terminate_to_exit(signum, frame):
    raise SystemExit(128 + signum)


def _dispatch(args, ver, pydantic_cls, agy_bin, readonly: bool,
              settings_lock_timeout: float = 30.0) -> "AgyResult":
    """Run the vendor call and return the AgyResult with `.elapsed` + `.cmd`.

    READ-ONLY path (v2, spec docs/superpowers/specs/2026-08-22-agy-readonly-v2-spec.md):
    setup-once tools-allowlisted agent (`--agent`, review without web tools or
    research with them under --web), `--add-dir <cwd>` so repository reads are
    auto-allowed in print mode, NO danger flag, NO settings transaction, NO agy
    --sandbox, NO soft-deny retry; admission by what the stream shows
    (`admit`). A fallback to agy's default agent cannot write or run a shell
    without the danger flag (ladder round 2, K1/K5) and is rejected by the
    census.

    PERMISSIVE baseline (`--sandbox` omitted, non-hardened): unchanged — the
    exclusive settings guard (heals a stale `.agybak`) and the version-gated
    danger flag, as before v2."""
    start = time.monotonic()
    json_schema = json.dumps(pydantic_cls.model_json_schema()) if pydantic_cls else None
    if readonly:
        agent = AGY_RESEARCH_AGENT if args.web else AGY_REVIEW_AGENT
        allowlist = AGY_RESEARCH_TOOLS if args.web else AGY_REVIEW_TOOLS
        read_set = AGY_READ_TOOLS_ADMIT | (AGY_WEB_TOOLS_ADMIT if args.web else frozenset())
        d = agents_dir()
        if os.environ.get("AGY_AGENTS_DIR"):
            _common.log("AGY_AGENTS_DIR is set (test hook): the agent definition is read "
                        "from there, NOT where agy discovers agents — a real host would "
                        "fall back to the default agent (rejected by the census)")
        if not check_agent_file(d, agent):
            err = (f"agy agent definition {d / (agent + '.md')} is missing or differs from "
                   f"the embedded body — run `antigravity_wrapper.py --setup-agents` once "
                   f"on this host (v2 setup step); if two wrapper builds share this "
                   f"directory, align their versions instead of re-running setup")
            _common.log(err)
            r = AgyResult(None, "config-conflict", _common.EXIT_TERMINAL, -1,
                          extraction_error=err)
            r.elapsed = time.monotonic() - start
            r.cmd = [agy_bin]   # no vendor process ran
            return r
        cmd = _build_cmd(args.prompt, False, args.model, args.timeout,
                         json_schema=json_schema, skip_permissions=False,
                         effort=args.effort, agent=agent, add_dir=args.cwd)
        cmd[0] = agy_bin   # resolved/pinned path: a PATH shadow cannot win
        cmd_box = [cmd]
        r = _run_agy_with_retry(cmd, args.prompt, args.timeout, cwd=args.cwd,
                                repair_mode=args.repair_mode,
                                pydantic_cls=pydantic_cls,
                                allow_skip_retry=False,
                                admission=(allowlist, read_set), cmd_box=cmd_box)
        r.elapsed = time.monotonic() - start
        r.cmd = cmd_box[0]   # the argv that actually ran last (a schema-repair retry rewrites -p)
        return r

    cmd = _build_cmd(args.prompt, False, args.model, args.timeout,
                     json_schema=json_schema,
                     skip_permissions=_agy_needs_skip_permissions(ver),
                     effort=args.effort)
    cmd[0] = agy_bin
    r: Optional[AgyResult] = None
    cmd_box = [cmd]
    try:
        with _agy_settings.agy_settings_guard([], lock_timeout=settings_lock_timeout):
            r = _run_agy_with_retry(cmd, args.prompt, args.timeout, cwd=args.cwd,
                                    repair_mode=args.repair_mode,
                                    pydantic_cls=pydantic_cls, cmd_box=cmd_box)
        cmd = cmd_box[0]
    except (TimeoutError, json.JSONDecodeError, ValueError, OSError) as e:
        # Settings-transaction failure (lock timeout / corrupt settings.json /
        # transient fs error) — surface as `config-conflict` (EXIT_TERMINAL),
        # never a traceback. If the vendor run ALREADY completed and only the
        # release failed, suppress the completed answer but keep the
        # transcript for the run-log.
        prior = r
        cmd = cmd_box[0]   # the argv that actually ran (a repair retry rewrites -p) — also on a RELEASE failure (focused pass)
        extraction_error = f"agy settings/config conflict: {e}"
        _common.log(extraction_error)
        if prior is not None:
            extraction_error = (
                f"{e}; completed vendor result suppressed because the agy "
                f"settings transaction did not release cleanly"
            )
            if prior.extraction_error:
                extraction_error += f" | prior: {prior.extraction_error}"
        r = AgyResult(
            None, "config-conflict", _common.EXIT_TERMINAL,
            prior.vendor_exit_code if prior is not None else -1,
            stream_output=prior.stream_output if prior is not None else "",
            stderr=prior.stderr if prior is not None else "",
            read_audit=prior.read_audit if prior is not None else None,
            extraction_error=extraction_error,
        )
        if prior is None:
            cmd = [agy_bin]   # transaction never opened: no vendor process ran
    r.elapsed = time.monotonic() - start
    r.cmd = cmd
    return r


def main() -> int:
    # SIGTERM/SIGHUP unwind instead of dying mid-transaction, so the settings
    # guard restore + vendor child kill run on the way out (SIGKILL stays
    # uncoverable by design — .agybak + next-call heal owns that window).
    try:
        signal.signal(signal.SIGTERM, _terminate_to_exit)
        signal.signal(signal.SIGHUP, _terminate_to_exit)
    except ValueError:
        pass  # not the main thread (in-process test harness): keep defaults
    # STALE-DIGEST pre-clear (final-gate fix round F1(a)) — call START, before
    # ANY other logic (argparse, validation, the vendor dispatch), so EVERY
    # exit path — including an early arg-validation failure that never
    # reaches emit_read_audit's call site at all — leaves TRIAD_READ_AUDIT_FILE
    # ABSENT rather than a prior round's stale digest. See
    # _common.preclear_read_audit_file's own docstring for the full rationale.
    # `repair_mode` is PEEKED from raw `sys.argv` here (mirrors
    # `prune_stale_run_logs`'s own repair_mode skip): argparse has not run
    # yet at this point in main(), so `args.repair_mode` does not exist —
    # a --repair-mode re-run must skip the clear (G3, re-confirm round 2),
    # so the peek has to happen BEFORE the parse, not after.
    _common.preclear_read_audit_file(repair_mode="--repair-mode" in sys.argv)
    p = argparse.ArgumentParser(description="Antigravity (agy) single-shot wrapper",
                                allow_abbrev=False)
    prompt_group = p.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="User prompt")
    prompt_group.add_argument(
        "--setup-agents", action="store_true",
        help="write the two read-only agent definitions (triad-readonly-review / "
             "triad-readonly-research) under ~/.gemini/config/agents and exit; run "
             "once per host (v2 setup step)")
    prompt_group.add_argument(
        "--prompt-file",
        help="Read the user prompt from a UTF-8 file (L12; containment applies "
             "under TRIAD_WRAPPER_ALLOWED_ROOTS)")
    p.add_argument("--cwd", default=None)
    p.add_argument("--sandbox", choices=["read-only"],
                   default=None,
                   help="read-only (v2, agy >= 1.1.18) — the setup-once "
                        "tools-allowlisted agent (--agent; review without web tools, "
                        "research with them under --web) + --add-dir <cwd>; no "
                        "danger flag, no settings transaction, no agy --sandbox; "
                        "admission by the stream (see --setup-agents). Omit = "
                        "permissive baseline. "
                        "(workspace-write removed 2026-07-25 — owner directive, never "
                        "used in 616 audited calls.)")
    p.add_argument("--web", action="store_true",
                   help="read-only path: dispatch the RESEARCH agent (web tools "
                        "read_url_content / search_web) instead of the REVIEW "
                        "agent (no web tool) — v2 spec")
    p.add_argument("--model", default=None)
    p.add_argument("--effort", choices=["low", "medium", "high"], default=None,
                   help="agy reasoning effort (--effort passthrough; agy >= 1.1.10)")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--repair-mode", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--pydantic", default=None,
                   help="pydantic class spec (module:Class) — native "
                        "--json-schema (model_json_schema()) + local "
                        "validate; one repair re-run then exit 66")
    # NOTE: --dangerously-* are intentionally NOT defined -> argparse rejects
    # them (danger flags are banned).
    args = p.parse_args()

    if args.setup_agents:
        d = agents_dir()
        try:
            written = setup_agents(d)
        except OSError as e:
            _common.log(f"--setup-agents failed: {e}")
            return _common.EXIT_ARG_ERROR
        for path in written:
            print(path)
        try:
            # heal a stale `.agybak` a pre-v2 read-only transaction may have left
            # (gate r1, claude): on a hardened host every dispatch is now read-only
            # and never enters the guard, so setup is the remaining heal point
            with _agy_settings.agy_settings_guard([], lock_timeout=30.0):
                pass
        except (TimeoutError, json.JSONDecodeError, ValueError, OSError) as e:
            _common.log(f"--setup-agents: settings heal skipped: {e}")
        print("hint: research dispatches (--web) use read_url_content / search_web, "
              "which need the `read_url(*)` permission allowed on this host "
              "(~/.gemini/antigravity-cli/settings.json permissions.allow); review "
              "dispatches need nothing beyond --add-dir (passed automatically).")
        return _common.EXIT_OK

    try:
        _prompt_text = _common.load_prompt_text(args.prompt, args.prompt_file)
    except Exception as e:
        _common.log(f"prompt load failed: {e}")
        return _common.EXIT_ARG_ERROR
    args.prompt = _prompt_text  # downstream code keeps using args.prompt

    try:
        args.cwd = _common.validate_wrapper_cwd(args.cwd)
    except Exception as e:
        _common.log(f"--cwd validation failed: {e}")
        return _common.EXIT_ARG_ERROR

    if args.sandbox is None and _common._wrapper_hardened():
        # Hardened installs default the Google legs to read-only (raw calls on
        # a public install must not be write-capable by omission).
        args.sandbox = "read-only"

    if not args.prompt.strip():
        _common.log("empty prompt")
        return _common.EXIT_ARG_ERROR

    if args.web and args.sandbox != "read-only":
        # never silently ignored (gate r1, claude): only the read-only path
        # selects an agent, so --web means nothing elsewhere
        _common.log("--web selects the research agent on the read-only path only — "
                    "pass --sandbox read-only (hardened installs do so by default)")
        return _common.EXIT_ARG_ERROR

    pydantic_cls = None
    if args.pydantic:
        try:
            pydantic_cls = load_pydantic_class(args.pydantic)
        except Exception as e:
            _common.log(f"--pydantic load failed: {e}")
            return _common.EXIT_ARG_ERROR

    agy_bin = _common.require_binary("agy")

    r: Optional[AgyResult] = None
    elapsed = 0.0
    cmd = [agy_bin]

    # Probe is unconditional BY DESIGN: the stream-json floor gate below needs
    # the version read even when AGY_NO_HEADLESS_AUTOAPPROVE=1 is set — that
    # opt-out governs only the skip-permissions flag (_agy_needs_skip_permissions),
    # never the floor gate.
    ver = _probe_agy_version(agy_bin)
    if ver is None or ver < _STREAM_JSON_FLOOR:
        # Fail-CLOSED floor: the stream-json transport is the only transport
        # (2026-07-31 migration). Surface as config-conflict (user runs
        # `agy update`), audited like every other terminal outcome.
        found = ".".join(map(str, ver)) if ver else "unprobeable"
        r = AgyResult(None, "config-conflict", _common.EXIT_TERMINAL, -1,
                      extraction_error=(
                          f"agy {found} < 1.1.8 — the stream-json transport "
                          f"requires agy >= 1.1.8; run `agy update`"))
    elif (args.model or args.effort) and ver < _MODEL_FLAG_FLOOR:
        # Fail-CLOSED pin floor (see _MODEL_FLAG_FLOOR): below 1.1.10 these
        # flags were silently IGNORED (default-model fallback) — dispatching
        # would void the requested tier with no error.
        found = ".".join(map(str, ver))
        r = AgyResult(None, "config-conflict", _common.EXIT_TERMINAL, -1,
                      extraction_error=(
                          f"agy {found} < 1.1.10 — --model/--effort were "
                          f"silently ignored (default-model fallback) before "
                          f"1.1.10; run `agy update` or drop the pin"))
    elif args.sandbox == "read-only" and ver < AGY_V2_FLOOR:
        # Fail-CLOSED v2 floor: `--add-dir` read auto-allow and the allowlist
        # agent were measured on 1.1.18; there is no legacy path (v2).
        found = ".".join(map(str, ver))
        floor_err = (f"agy {found} < 1.1.18 — the read-only path needs agy >= "
                     f"1.1.18 (allowlist agent + --add-dir); run `agy update`")
        _common.log(floor_err)
        r = AgyResult(None, "config-conflict", _common.EXIT_TERMINAL, -1,
                      extraction_error=floor_err)
    else:
        settings_lock_timeout = 30.0
        if args.sandbox != "read-only":
            # the settings-lock knob belongs to the permissive baseline's guard;
            # the read-only path v2 enters no transaction (gate r1, codex)
            raw_lt = os.environ.get("AGY_SETTINGS_LOCK_TIMEOUT", "30")
            try:
                float(raw_lt)
            except ValueError:
                _common.log("AGY_SETTINGS_LOCK_TIMEOUT must be a number")
                return _common.EXIT_ARG_ERROR
            settings_lock_timeout = _lock_wait_seconds(raw_lt)   # inf/nan/negative -> 30
        r = _dispatch(args, ver, pydantic_cls, agy_bin, args.sandbox == "read-only",
                      settings_lock_timeout=settings_lock_timeout)
        elapsed = r.elapsed if r.elapsed is not None else 0.0
        if r.cmd:
            cmd = r.cmd  # the REAL argv for the audit row + run-log

    # Build a RunResult for the shared audit / run-log / debug helpers.
    # vendor_version (agy telemetry slice, 2026-08-19): `ver` is the SAME
    # _probe_agy_version() tuple the stream-json floor gate above already
    # probed on every dispatch — no second probe call. None on a failed/
    # unparseable probe (fail-safe path) leaves the field None, same as every
    # other caller of `ver`.
    rr = _common.RunResult(
        exit_code=r.exit_code,
        stdout=r.stream_output,
        stderr=r.stderr,
        elapsed_s=elapsed,
        classification=r.classification,
        mode="repair" if args.repair_mode else "normal",
        final_answer=r.final_answer or "",
        extraction_error=r.extraction_error,
        vendor_exit_code=r.vendor_exit_code,
        read_audit=r.read_audit,
        vendor_version=".".join(map(str, ver)) if ver is not None else None,
    )

    # Read-audit digest — emitted BEFORE the canonical summary line, on EVERY
    # completed vendor call (ok or not), so the review SKILL / leader can
    # consume it even on success (the run-log only exists on failure).
    if r.read_audit is not None:
        # ensure_ascii=True (r1/R9): the digest is vendor/model-controlled and
        # this line carries the TRUSTED `[wrapper] antigravity ` prefix the
        # review SKILL greps. With ensure_ascii=False a raw U+2028/U+2029 (or
        # any other line-terminator a consumer's splitlines() honours) rode
        # straight through, letting the payload forge extra leader-visible
        # lines. Escaping them keeps the line single-line by construction.
        _common.log("[wrapper] antigravity read-audit "
                    + json.dumps(r.read_audit, separators=(",", ":")))
        # Durable file artifact (task-1, 2026-07-31 follow-up): the stderr
        # line above is a transient operator aid; a review-SKILL-grade
        # consumer needs a durable, jq-only artifact that exists on the
        # SUCCESS path too (emit_run_log only writes on failure). Best-effort
        # — an IO failure here never changes rr.exit_code/classification.
        read_audit_path = _common.emit_read_audit("antigravity", rr)
        if read_audit_path is not None:
            _common.log(f"read-audit-file: {read_audit_path}")

    # Canonical 1-line summary — byte-match the format _run_once emits so the
    # dispatch SKILL grep + the parity test see the same shape.
    _common.log(
        f"[wrapper] antigravity {r.classification} "
        f"exit={r.exit_code} vendor={r.vendor_exit_code} "
        f"elapsed={elapsed:.1f}s"
    )

    _common.audit("antigravity", cmd, args.prompt, rr)
    if args.debug:
        _common.debug_log("antigravity", args.prompt, rr)
    run_log_path = _common.emit_run_log(
        "antigravity", sys.argv, cmd, args.prompt, rr)
    if run_log_path is not None:
        _common.log(f"run-log: {run_log_path}")

    if r.validated is not None:
        sys.stdout.write(json.dumps(r.validated, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(r.final_answer or "")
        if r.final_answer and not r.final_answer.endswith("\n"):
            sys.stdout.write("\n")
    sys.stdout.flush()
    return r.exit_code


if __name__ == "__main__":
    sys.exit(main())
