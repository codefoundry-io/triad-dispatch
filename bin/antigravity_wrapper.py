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
The permissive baseline (`--sandbox` omitted, non-hardened) adds only the
version-gated danger flag; this host never writes, locks or heals the agy
settings (DL-112). workspace-write
was removed 2026-07-25 (owner directive — 616 audited calls, 0 workspace-write).
Audit log: _logs/antigravity/audit.jsonl (gitignored).
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple, Optional

import json

import _common
from _common import load_pydantic_class

OFFSET_S = 10  # agy --print-timeout = max(timeout - OFFSET, MIN); _run_once kill is backstop
MIN_PRINT_TIMEOUT_S = 5
SERVER_CAP_RETRIES = 2


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
        # ONE token each (M-1; the equals form measured on agy 1.3.2)
        cmd.append(f"--model={model}")
    if effort:
        cmd.append(f"--effort={effort}")
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


def _repair_cmd(cmd, err, web=False):
    """Rebuild the agy cmd with a one-shot JSON-repair hint appended to the
    -p arg (the vendor's own --json-schema repair turn failed to satisfy the
    LOCAL pydantic validation — belt-and-suspenders re-run, exactly once)."""
    new = list(cmd)
    i = new.index("-p") + 1
    # C29: on a --web dispatch the web-evidence clause stays LAST — the
    # repair notice goes between the caller's text and the clause.
    tail = "\n\n" + _common._investigation_clause("agy") if web else None
    head = new[i][:-len(tail)] if tail and new[i].endswith(tail) else new[i]
    new[i] = (head + f"\n\nYour previous output was NOT valid JSON for the "
              f"schema ({err}). Output ONLY the corrected JSON object."
              + new[i][len(head):])
    return new


_VENDOR_TURN_TIMEOUT_RE = re.compile(r"^\s*timeout waiting for response\b", re.I)


def _is_vendor_turn_timeout(result) -> bool:
    """True when the stream's terminal result is agy's own turn timeout: the
    typed `result.error` STARTS with the vendor's literal "timeout waiting
    for response" (agy 1.1.26, observed 2026-09-04 as exactly that string).
    Anchored, not a substring: `result.error` can ECHO model text (a
    finish-schema validation report becomes the turn error — review packets
    quote this very phrase), and such a report never starts with it (gate
    r2 row 15)."""
    err = result.get("error") if isinstance(result, dict) else None
    return isinstance(err, str) and bool(_VENDOR_TURN_TIMEOUT_RE.match(err))


# agy's OWN stderr line when its `--print-timeout` fires mid-turn (agy 1.2.x,
# observed 2026-09-20 / 2026-09-25 / 2026-10-03): `[agy] print timeout after
# 19m50s with turn in progress; returning partial output`, vendor rc 0, and the
# result carries whatever the turn had produced (2026-10-03: a degenerate 289 KB
# repetition, returned as `ok`). R-CLASSIFY: matched only as a WHOLE stderr line
# carrying agy's `[agy] ` prefix — never on stdout or answer text, never a
# fragment quoted inside another line.
_VENDOR_PRINT_TIMEOUT_RE = re.compile(
    r"^\[agy\] print timeout after \S+ with turn in progress; "
    r"returning partial output[ \t\r]*$", re.I | re.M)


def _is_vendor_print_timeout(stderr) -> bool:
    """True when agy's own stderr says its print timeout returned a partial
    turn (`_VENDOR_PRINT_TIMEOUT_RE`)."""
    return isinstance(stderr, str) and bool(_VENDOR_PRINT_TIMEOUT_RE.search(stderr))


def _classify_no_answer(stderr: str, signals, vendor_rc: int,
                        status=None, stdout: str = "") -> tuple:
    """Decide classification for the no-usable-answer case.

    The classify blob is stderr + STRUCTURAL stream signals + a synthetic
    status token (so an L2 pattern or a future extension entry can key on an
    unknown result status). It deliberately does NOT include the raw NDJSON
    stream (r1/R2): that stream carries model-authored prose, tool OUTPUT and
    tool PARAMETERS — the reviewed content itself — so a packet quoting a
    capacity phrase forced spurious `server-capacity` re-dispatches and one
    quoting an auth banner produced a terminal `oauth-env`. `signals` comes
    from `_common.agy_classify_signals` (the result-level `error` only). The full
    raw stream still rides in the record's `stdout` for the run-log, so the repair
    agent's diagnostics are unchanged. `stdout` (the raw stream) reaches
    classify() ONLY for its auth rung, which reads `result.error` alone
    (R-AUTH (ii)); classify() keeps agy's raw stream out of the L2 blob.
    """
    status_tok = f"agy result status={str(status)[:200]}" if status else ""
    # Each stream signal is LABELLED so it never starts a line: it must not
    # impersonate agy's own stderr banner. agy's own carriers are its real
    # stderr lines and `result.error` (read from `stdout` by the auth rung).
    parts = [stderr, *[f"[agy signal] {t}" for t in (signals or []) if t], status_tok]
    blob = "\n".join(t for t in parts if t and t.strip())
    if not blob.strip() and vendor_rc == 0:
        # Nothing structural to classify AND the vendor exited 0. A nonzero rc
        # still goes through classify() so the L1 vendor-exit map keeps its
        # say (a silent vendor failure that only signals through its rc must
        # not be swallowed by this short-circuit).
        return "extraction-error", _common.EXIT_CLI_FAIL
    cls = _common.classify(
        "antigravity", stderr=blob, stdout=stdout,
        exit_code=_common.EXIT_CLI_FAIL, vendor_exit_code=vendor_rc,
    )
    return cls, _common.map_classification_to_exit(cls)


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
# The marker line may end LF or CRLF (C43).
_AGY_TRUNCATION_MARKER_RE = re.compile(r"(?m)^[ \t]*<truncated \d+ (?:bytes|lines)>[ \t]*\r?$")


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


class _AgyVersion(tuple):
    """A parsed agy version tuple that keeps `text`, the version as the CLI
    printed it (C65 / R-CLI-VERSION: recorded as observed)."""
    text = None


def _parse_agy_version(text):
    """Extract the first dotted numeric version tuple from `agy --version`
    output (e.g. '1.1.3' -> (1, 1, 3)); None if unparseable."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?",
                  text or "")
    if not m:
        return None
    major, minor, patch = (int(g) for g in m.groups()[:3])
    ver = _AgyVersion((major, minor, patch))
    ver.text = m.group(0)
    return ver


def _ver_text(ver) -> str:
    """The version as observed: the printed text when the probe kept it."""
    return getattr(ver, "text", None) or ".".join(map(str, ver))


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


def _allowlist_rule(tools) -> str:
    """The standing system-text form of the wrapper's admission census
    (2026-09-04): agy advertises its FULL tool registry to a custom agent
    regardless of `tools:` (init.tools = 57 on 1.1.25/1.1.26), so the agent
    must be TOLD which calls void its answer — one sentence per agent,
    rendered from its own allowlist (a review body never names web tools)."""
    return (
        "TOOL ALLOWLIST (hardest rule): the tool schema you are shown may list\n"
        "many tools, but you are permitted ONLY these: "
        + ", ".join(tools)
        + ".\nEvery other tool — manage_task (never create task lists; plan in your\n"
        "reasoning), run_command or any shell, write_to_file /\n"
        "replace_file_content / sed_file, send_message, define_subagent /\n"
        "invoke_subagent / manage_subagents, browser_* — is off-limits. Off-list\n"
        "mutating and network tools are BLOCKED before they run when the\n"
        "caller's worktree carries a PreToolUse hook (a cross-family review\n"
        "round) — a blocked call is logged, not fatal — but you cannot see from\n"
        "inside whether such a hook is present, so never make one. Any call\n"
        "outside this list that EXECUTES voids your whole answer: the caller\n"
        "audits every tool step and quarantines the result.\n"
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
        f"{_allowlist_rule(tools)}"
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
    forbidden: list         # off-list tool names that EXECUTED or errored for an
                            # unknown reason (voiding; capped)
    omitted: int            # census hits beyond the cap (counted, not stored)
    blocked: tuple = ()     # off-list tool names DENIED before execution on every
                            # occurrence (S2 effect-based Gate A: logged, not voiding)


_UNNAMED_TOOL_STEP = "<unnamed tool step>"
_SUBMIT_TOOL = "finish"     # the model's submission of its answer (both allowlists)


def _census(events, allowlist, read_set):
    """(forbidden, omitted, errored_reads, errored_other, blocked, resubmitted)
    over one attempt's parsed events — admission rule 4 plus the errored-step
    split rule 5 needs. An errored submission (`_SUBMIT_TOOL`) goes to
    `resubmitted` instead of `errored_other` when a LATER successful
    submission follows it in the stream (C40). Runs on EVERY attempt (schema-repair /
    capacity retries included) so a forbidden call in an earlier attempt is
    never erased by a clean retry.

    EFFECT-BASED (S2, 2026-09-17 — plan 2026-09-16-cfr-delivery-and-
    enforcement-redesign § Enforcement, Gate A): an off-list name whose EVERY
    occurrence was DENIED before execution (`_common._agy_step_denied` — the
    round worktree's PreToolUse hook, or the vendor's own permission denial) is
    BLOCKED: nothing ran, so nothing voids; the caller logs it. An off-list
    name with ANY occurrence that was not a denial — executed, or errored for an
    unknown reason (measured 2026-09-17: a `manage_task` rejected at argument
    validation never reaches the hook; its effect is unknown) — is FORBIDDEN and
    voids the answer (Policy D, unchanged). `forbidden` is capped like the
    digest with `omitted` counting the DISTINCT names beyond the cap; `blocked`
    is capped and informational."""
    allowed = set(allowlist)
    executed: list = []
    denied: list = []
    errored_reads: list = []
    errored_other: list = []
    # The TERMINAL update decides each call (S2 gate r1, codex C2 + claude —
    # REPRODUCED against the spike streams): the vendor emits an ACTIVE update
    # before every DONE/ERROR, so counting it as an occurrence made every
    # hook-DENIED call "executed" too and the effect-based split never fired on
    # a real stream. An ACTIVE update is suppressed ONLY by a TRUSTWORTHY
    # matching identity — an INTEGER step_index shared with a terminal update
    # of the same name (S2 gate r2, codex: two distinct STRING indices used to
    # collapse to None, so a denied write's terminal key hid a second,
    # ACTIVE-only write). An ACTIVE record with no integer index, or one that
    # never reached a terminal update (a cut stream), still counts — its effect
    # is UNKNOWN, so fail-closed.
    # A SUCCESSFUL submission (C40, fix wave 1) is the MEASURED shape only
    # (agy 1.2.11, 2026-09-26 — `_common.digest_agy_stream`'s open-step note):
    # a `step_type: finish` update in state DONE without `tool_info.error`. A
    # tool-typed `finish` that did not error, or a `finish` update in any other
    # state, is not one (fail-closed). Positions count over EVERY step_update.
    updates = []
    last_ok_submit = -1
    for pos, ev in enumerate(ev for ev in events or []
                             if isinstance(ev, dict) and isinstance(ev.get("step_update"), dict)):
        su = ev["step_update"]
        if su.get("step_type") == "finish" and su.get("state") == "DONE" and _SUBMIT_TOOL in allowed:
            ti = su.get("tool_info")
            if not (isinstance(ti, dict) and ti.get("error")):
                last_ok_submit = pos
        if su.get("step_type") != "tool":
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
        idx = su.get("step_index")
        idx = idx if isinstance(idx, int) and not isinstance(idx, bool) else None
        updates.append((su, names, idx, pos))
    terminal = {(idx, n) for su, names, idx, _pos in updates
                if su.get("state") != "ACTIVE" and idx is not None for n in names}
    last_err_submit = -1   # stream position of the last errored submission (C40)
    for su, names, idx, pos in updates:
        active = su.get("state") == "ACTIVE"
        if active and idx is not None and all((idx, n) in terminal for n in names):
            continue
        ti = su.get("tool_info")
        errored = (not active) and (su.get("state") == "ERROR"
                                    or (isinstance(ti, dict) and bool(ti.get("error"))))
        step_denied = (not active) and _common._agy_step_denied(su)
        if errored and _SUBMIT_TOOL in names and _SUBMIT_TOOL in allowed:
            last_err_submit = pos
        for n in sorted(names):
            if n not in allowed:
                bucket = denied if step_denied else executed
                if n not in bucket:
                    bucket.append(n)
            elif errored:
                bucket = errored_reads if n in read_set else errored_other
                if n not in bucket:
                    bucket.append(n)
    cap = _common._AGY_DIGEST_LIST_CAP
    forbidden = executed[:cap]
    omitted = len(executed) - len(forbidden)
    blocked = [n for n in denied if n not in executed][:cap]
    resubmitted: list = []
    if _SUBMIT_TOOL in errored_other and last_ok_submit > last_err_submit:
        errored_other.remove(_SUBMIT_TOOL)
        resubmitted.append(_SUBMIT_TOOL)
    return forbidden, omitted, errored_reads, errored_other, blocked, resubmitted


def _early_census(events, allowlist, read_set, prior_forbidden, prior_omitted=0) -> tuple:
    """(errored_reads, forbidden, omitted) for an admission REFUSED before the
    census would normally run (framing / result-count defects — gate r1
    2026-09-04, claude): a run that also called a forbidden tool must still
    classify `admission-refused` and name the tool, never fall back to
    `vendor-error`; the counters ride along so the refusal loses no
    diagnostic (gate r2 row 12)."""
    forbidden, omitted, errored_reads, _eo, _blocked, _rs = _census(events or [], allowlist, read_set)
    for n in prior_forbidden:
        if n not in forbidden:
            forbidden.append(n)
    return errored_reads, forbidden, max(omitted, prior_omitted)


def _forbidden_shown(forbidden, omitted=0) -> str:
    """ASCII-escaped capped list + the (+N more) counter the census path
    prints — one builder for every reason that names forbidden tools."""
    cap = _common._AGY_DIGEST_KEY_CAP
    shown = json.dumps([n[:cap] for n in forbidden[:8]], ensure_ascii=True)
    more = len(forbidden) - 8 + omitted
    return shown + (f" (+{more} more)" if more > 0 else "")


def admit(stream_text, events, result, *, allowlist, read_set, prior_forbidden=(), prior_omitted=0,
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
       EFFECT-BASED since S2 (2026-09-17): an off-list call DENIED before it
       ran (the worktree PreToolUse hook / vendor permission denial) is
       BLOCKED — carried on `.blocked`, logged by the caller, not voiding;
       an off-list call that EXECUTED (or errored for a non-denial reason)
       is FORBIDDEN and refuses the answer as before.
    5. Status: SUCCESS with vendor rc 0 -> ok; anything else (a non-SUCCESS
       status OR a non-zero vendor rc, gate r1) is admitted ONLY when at least
       one errored tool step EXPLAINS it and every errored step named an
       allowed READ tool (`read_set`) — an errored read (paging overshoot,
       nonexistent path, root-grep timeout) is a prompt-quality signal, not a
       discard; an errored non-read step rejects, and a degraded run with NO
       errored step (run-level error / cancel / cut) rejects too (gate r3:
       never admit a possibly partial answer on nothing). ADDED (C40): an
       errored submission (`finish`) that a LATER successful submission of
       the same attempt follows is a resubmission and explains the
       degradation like an errored read; an errored submission with no later
       success still rejects.
       (The caller adds the read-blind guard: such a run must also have read
       something — `files_read` non-empty in the digest.)
    Every vendor-controlled string on the reason is capped at
    `_AGY_DIGEST_KEY_CAP` (gate r1, claude: the engine closed that class).
    (Rule 3 — local validation of the answer — is the caller's existing
    `_validate_structured_detail` path.)"""
    for idx, line in enumerate((stream_text or "").split("\n"), 1):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except (ValueError, RecursionError):
            # RecursionError joins ValueError here for the same reason the
            # parser skips it (gate-1 r6 row r6-8): a line nested past the
            # interpreter's limit is UNDECODABLE, and the framing rule is one
            # blanket rule — a line that does not decode to a JSON object
            # makes the run unusable. Without this the refusal the parser
            # hands us was re-raised as a traceback one line later.
            obj = None
        if not isinstance(obj, dict):
            # name the offending line so a stray vendor stdout line is diagnosable
            # (gate r2, claude); the excerpt is capped and ASCII-escaped
            excerpt = json.dumps(s[:_common._AGY_DIGEST_KEY_CAP], ensure_ascii=True)
            return Admission(False, f"stream line {idx} is not a JSON object (unusable run): {excerpt}",
                             *_early_census(events, allowlist, read_set, prior_forbidden, prior_omitted))
    n_results = sum(1 for ev in events or []
                    if isinstance(ev, dict) and ev.get("event") == "result")
    if n_results != 1:
        return Admission(False, f"{n_results} result events in the stream (expected exactly 1)",
                         *_early_census(events, allowlist, read_set, prior_forbidden, prior_omitted))
    forbidden, omitted, errored_reads, errored_other, blocked, resubmitted = _census(events, allowlist, read_set)
    blocked = tuple(blocked)
    for n in prior_forbidden:          # an earlier attempt's forbidden call is never erased
        if n not in forbidden:
            forbidden.append(n)
    omitted = max(omitted, prior_omitted)   # cross-attempt overflow: MAX, never a sum (row 19 r1)
    cap = _common._AGY_DIGEST_KEY_CAP
    if forbidden:
        return Admission(False, f"tool(s) outside the allowlist appeared in the stream: "
                                f"{_forbidden_shown(forbidden, omitted)} — agy fell back to its "
                                f"default agent or the model slipped; answer quarantined",
                         errored_reads, forbidden, omitted, blocked)
    status = result.get("status") if isinstance(result, dict) else None
    shown_status = str(status)[:cap]
    if status != "SUCCESS" or vendor_rc not in (0, None):
        tag = f"terminal status {shown_status!r} rc={vendor_rc}"
        if errored_other:
            shown = json.dumps([n[:cap] for n in errored_other[:8]], ensure_ascii=True)
            return Admission(False, f"{tag} with errored non-read step(s) {shown}",
                             errored_reads, [], omitted, blocked)
        if errored_reads or resubmitted:
            # each clause only when it explains something (fix wave 2, C8)
            clauses = ([f"an allowed read {json.dumps([n[:cap] for n in errored_reads[:8]], ensure_ascii=True)}"]
                       if errored_reads else []) + (
                [f"a resubmitted submission {json.dumps(resubmitted)}"] if resubmitted else [])
            return Admission(True, f"{tag} admitted: every errored step is {' or '.join(clauses)}",
                             errored_reads, [], omitted, blocked)
        # nothing in the stream explains the degradation (run-level error / cancel /
        # cut / bare rc!=0): a possibly partial answer is not admitted (gate r3).
        # A BLOCKED call does not explain it either — it never ran (Gate B untouched).
        return Admission(False, f"{tag} with no errored tool step in the stream — nothing "
                                f"explains the degradation; answer quarantined", [], [], omitted,
                         blocked)
    return Admission(True, "ok", errored_reads, [], omitted, blocked)


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


def _validate_structured_detail(result, answer, pydantic_cls):
    """Local pydantic validation of a `--pydantic` answer:
    (ok, validated_dict_or_error, nonrepairable). A dict `structured_output`
    is the answer and is validated; anything else (absent, null, not a dict)
    is treated as absent and the raw response text is validated.
    `nonrepairable` is True only for a duplicate JSON member (spec C14)."""
    structured = result.get("structured_output") if isinstance(result, dict) else None
    if isinstance(structured, dict):
        return _common.validate_response_detail(json.dumps(structured), pydantic_cls)
    return _common.validate_response_detail(answer, pydantic_cls)


def _done(rr: _common.RunResult, cls: str, code: int, *, audit, answer=None,
          validated=None, err=None) -> _common.RunResult:
    """This driver's verdict, stamped on the engine's own RunResult. The
    engine's transport facts (stdout, stderr, vendor rc, effective cwd,
    spawned, capture_complete) ride through untouched."""
    rr.classification, rr.exit_code = cls, code
    rr.final_answer = answer or ""
    rr.validated = validated
    rr.extraction_error = err
    rr.read_audit = audit
    return rr


def _run_agy_with_retry(cmd, prompt, timeout, *, cwd=None,
                        repair_mode=False, pydantic_cls=None,
                        admission=None,
                        schema_file_mode=False, web=False) -> tuple[_common.RunResult, list]:
    """Dedicated extract-then-classify driver over the stream-json transport.
    See the plan's decision table (2026-07-31) — ORDER MATTERS. Spawn =
    _common._run_once(classify_and_log=False): shared scrubbed env + setsid +
    SIGTERM->SIGKILL killpg escalation; classification and the canonical
    one-line summary stay THIS driver's job. Returns the engine's own
    RunResult carrying this driver's verdict (`_done`) and the argv of the
    last attempt that spawned."""
    if not repair_mode:
        _common.prune_stale_run_logs("antigravity")

    # F-Q2: the two retry budgets are INDEPENDENT — schema_repaired and the
    # server-capacity budget (max_retries/server_attempt) each gate a
    # different failure shape and do not share state. In particular, schema
    # repair fires exactly ONCE regardless of repair_mode; repair_mode only
    # disables the server-capacity retry (max_retries=0).
    max_retries = 0 if repair_mode else SERVER_CAP_RETRIES
    server_attempt = 0
    schema_repaired = False   # one-shot local-validation repair re-run (Task 5)
    # r1/R4: one digest per ATTEMPT, aggregated on every return path. Emitting
    # only the LAST attempt's digest let a short-circuiting retry CONCEAL an
    # earlier attempt's reads — the review SKILL's mechanical read-audit gate
    # then VOIDed a leg that had demonstrably read the packet.
    attempt_digests: list = []
    # v2 read-only path: `admission` = (allowlist, read_set). Forbidden names
    # accumulate across attempts so a schema-repair or capacity retry cannot
    # erase an earlier attempt's evidence.
    forbidden_seen: list = []
    forbidden_omitted_seen = 0          # census overflow beyond the cap, MAX across attempts (row 19 / rs-r1)
    argv = list(cmd)       # the argv of the last attempt that spawned
    spawned_rr = None      # that attempt's engine record
    last_rr = None         # the previous attempt of this call (C1)
    while True:
        signum = _common._SIGNAL_STATE["signum"]
        interrupted = last_rr is not None and signum is not None
        if interrupted:
            _common._SIGNAL_STATE["signum"] = None
            rr = _common._interrupted_previous(last_rr, signum)
        else:
            rr = last_rr = _common._run_once("antigravity", cmd, cwd, timeout,
                                             classify_and_log=False)
        if interrupted or (attempt_digests and not rr.spawned):
            # C1 / R-READ-AUDIT: a RETRY turn that spawned nothing — a signal
            # BETWEEN attempts (this driver returns the previous attempt's
            # record, now carrying the signal failure) or a spawn failure on
            # the re-run. The attempts that ran are already counted; a digest
            # here would seal an attempt that never ran. R-RECEIPT: the record
            # describes the last turn that spawned, as `argv` does.
            if not rr.spawned and spawned_rr is not None:
                rr.spawned = True
                rr.capture_complete = spawned_rr.capture_complete
            return _done(rr, rr.classification,
                         _common.map_classification_to_exit(rr.classification),
                         audit=_common.merge_agy_digests(attempt_digests),
                         err=rr.extraction_error), argv
        if rr.spawned:
            # the REAL argv of the attempt that ran (gate r3, codex); a turn
            # that spawned nothing (above, or a spawn OSError) keeps the
            # previous one (C1)
            argv, spawned_rr = list(cmd), rr
        stream = rr.stdout
        # A duplicate member refuses the whole stream (C14), held so transport verdicts keep precedence.
        duplicate_member = None
        try:
            events, result = _common.parse_agy_stream(stream)
        except _common._DuplicateJSONMember as exc:
            duplicate_member = exc
            events, result = [], None
        if admission is not None:
            _fb, _om, _er, _eo, _bl, _rs = _census(events, admission[0], admission[1])
            for _n in _fb:
                if _n not in forbidden_seen:
                    forbidden_seen.append(_n)
            forbidden_omitted_seen = max(forbidden_omitted_seen, _om)   # MAX: a repeated set never over-counts
        attempt_digest = _common.digest_agy_stream(events, result)
        # PER-ATTEMPT capture evidence (gate-1 r6 row r6-1): the merged audit
        # unions every attempt's reads, so it has to be able to say WHICH
        # attempt's transcript was a prefix. `merge_agy_digests` carries the
        # flag into `attempts[]` under the omit-when-default rule.
        attempt_digest["capture_complete"] = bool(rr.capture_complete)
        # THE TRANSCRIPT WAS CUT MID-LINE (gate-1 r9 row r9-10): recorded,
        # never refused — an answer before the cut is read like any other
        # (E5-11), and a no-answer run keeps its own diagnosis.
        if _common._agy_tail_fragment(stream):
            attempt_digest["truncated_tail"] = True
        # THE RUN WAS INTERRUPTED, SO ITS TRANSCRIPT IS A KNOWN PREFIX (gate-1
        # r17 row r17-1). A run killed at the wrapper deadline whose capture
        # happens to end on a line boundary carries none of the markers above
        # — `capture_complete` comes from reader failures only and
        # `truncated_tail` from a malformed fragment — yet the timeout return
        # below itself calls the stream "a partial prefix". The engine exposes
        # no `timed_out` field on the RunResult: EXIT_TIMEOUT is set on
        # exactly its `timed_out` arm, so that exit IS the evidence. Any other
        # NEGATIVE vendor rc is a child that died on a signal (POSIX
        # `returncode`), which covers the engine's thread-start failure (it
        # kills and reaps the child) as well as a kill from outside — but
        # only for a SPAWNED child: a pre-spawn refusal keeps the dataclass
        # default rc -1 with nothing run, so nothing was interrupted. The
        # engine's other terminal classes do not cut the stream: the child of
        # `truncated-answer` ran to rc 0 (its reader failure is already
        # `capture_complete` false) and `input-delivery-failed` is a prompt
        # the vendor never confirmed, not a cut output. Omit-when-default.
        # agy's OWN print timeout (its stderr line) cut the turn the same way.
        if (rr.exit_code == _common.EXIT_TIMEOUT
                or _is_vendor_print_timeout(rr.stderr)):
            attempt_digest["interrupted"] = "timeout"
        elif (rr.spawned and isinstance(rr.vendor_exit_code, int)
              and rr.vendor_exit_code < 0):
            attempt_digest["interrupted"] = "signal"
        if duplicate_member is None:
            attempt_digests.append(attempt_digest)
        audit = _common.merge_agy_digests(attempt_digests)
        if rr.exit_code == _common.EXIT_TIMEOUT:
            # Killed short-circuit FIRST: a killed run's stream is a partial
            # prefix — never trust a result event parsed out of it. R-AUTH
            # (ii) / R-CLASSIFY: a timed-out run is still judged on what it
            # printed before — an auth failure in agy's own carrier STOPs.
            if _common._auth_carrier_stop("antigravity", rr.stderr, rr.stdout):
                _common.log("authentication failure printed before the "
                            "timeout: STOP (owner browser re-login; no retry)")
                return _done(rr, "oauth-env", _common.EXIT_TERMINAL, audit=audit,
                             err="authentication failure printed "
                                 "before the timeout: owner "
                                 "browser re-login"), argv
            return _done(rr, "timeout", _common.EXIT_TIMEOUT, audit=audit), argv
        if (rr.exit_code != _common.EXIT_OK
                and rr.classification != "unclassified"):
            # The engine already decided (`unclassified` = the sentinel it parks on
            # the exits it leaves to this driver): forward its token, conform the exit
            # to the vocabulary (input-delivery-failed keeps its own), keep custody.
            forwarded_exit = (
                rr.exit_code if rr.classification == "input-delivery-failed"
                else _common.map_classification_to_exit(rr.classification))
            return _done(rr, rr.classification, forwarded_exit, audit=audit,
                         err=rr.extraction_error), argv
        _res = result if isinstance(result, dict) else {}
        _completed = (rr.vendor_exit_code == 0 and _res.get("status") == "SUCCESS"
                      and not _is_vendor_print_timeout(rr.stderr)
                      and ((isinstance(_res.get("response"), str)
                            and _res["response"].strip())
                           or isinstance(_res.get("structured_output"), dict)))
        if (not _completed
                and _common._auth_carrier_stop("antigravity", rr.stderr, rr.stdout)):
            # R-AUTH (ii), C37: an authentication failure in agy's own carrier
            # (`result.error`, or a stderr line beginning with the auth banner)
            # STOPS this attempt before any other classification of the run —
            # above the print-timeout, capture-prefix, duplicate-member,
            # admission (allowlist) and answer-present rungs and the vendor-timeout
            # branch; never retried. Only the engine-decided verdicts above
            # (nothing of this run is read there) come first. It applies to a
            # call that FAILED: a run that completed with an answer (rc 0,
            # status SUCCESS, a response or structured output, no print
            # timeout) is not stopped by a banner line; "an answer" means a
            # USABLE one — a non-blank response or a `structured_output`
            # OBJECT, never the key's mere presence.
            _common.log("authentication failure in agy's error carrier: STOP "
                        "(owner browser re-login; no retry)")
            return _done(rr, "oauth-env", _common.EXIT_TERMINAL, audit=audit,
                         err="authentication failure in agy's "
                             "error carrier: owner browser "
                             "re-login"), argv
        if (_is_vendor_print_timeout(rr.stderr)
                and not (admission is not None and forbidden_seen)):
            # agy's OWN print timeout (R-CLASSIFY / C43, observed 2026-10-03):
            # the turn did not finish, whatever the vendor rc and however much
            # answer the result carries — the same verdict as the wrapper kill
            # above. BELOW the engine-decided verdicts (rung 1b: never
            # re-derived) and yielding to the read-only allowlist census (a
            # tool outside the allowlist ran: `admission-refused` decides
            # below, a containment signal is never masked); ABOVE every
            # answer / ok / retry branch. The partial stream rides out for the
            # run-log; no answer does, and no retry or repair re-run consumes it.
            # R-AUTH (C37): an auth failure the same run carries was already
            # decided by the auth-carrier rung just above — oauth-env / 65.
            return _done(rr, "timeout", _common.EXIT_TIMEOUT, audit=audit,
                         err="agy print timeout: turn in progress, "
                             "partial output withheld"), argv
        if not rr.capture_complete:
            # THE CAPTURE IS A PREFIX — TERMINAL, ABOVE EVERY BRANCH BELOW
            # (gate-1 r5 row r5-2, HOISTED at r6 row r6-1). The engine's own
            # reader gate fails a run closed only at `rc == 0` (a genuine
            # vendor failure keeps its own diagnosis), so a rc != 0 run whose
            # reader died arrives here looking like an ordinary degraded run.
            # The r5-2 refusal sat INSIDE the answer-present admission arm,
            # which left the NO-ANSWER shape open: a fragment carrying a
            # capacity phrase reached `_classify_no_answer`, took the
            # automatic `server-capacity` retry, and the next iteration
            # replaced `rr` — only the FINAL attempt's flag propagated, while
            # the MERGED read audit still carried the knowingly incomplete
            # earlier transcript under an `ok` result. An attempt whose
            # transcript is a fragment never earns a retry: the wrapper
            # stops here and the LEADER re-dispatches (the contract's one
            # retry), exactly as for every other terminal class.
            #
            # No new token — this is the existing `truncated-answer` terminal
            # class, the same one the engine raises for the rc-0 shape of the
            # identical fact. The stream and the merged read audit ride out
            # for the run-log; no answer does, and nothing is parsed out of a
            # prefix to decide otherwise (a duplicate member or a content
            # verdict read off a fragment would mis-route the leader, the
            # same precedence the killed-run short-circuit above keeps).
            _common.log("the output capture is incomplete (a reader thread "
                        "failed or did not join), so this attempt's "
                        "transcript is a prefix — terminal, never retried")
            return _done(rr, "truncated-answer", _common.EXIT_TERMINAL, audit=audit,
                         err=f"incomplete output capture (vendor "
                             f"rc={rr.vendor_exit_code}): a reader thread "
                             f"failed or did not join, so everything this "
                             f"attempt produced came out of a PREFIX of "
                             f"the stream and is never admitted, never "
                             f"classified from, and never retried"), argv
        if duplicate_member is not None:
            # NON-REPAIRABLE (C14): no repair turn; the refused attempt adds no read-audit row.
            _common.log(f"agy stream line {duplicate_member.line_no} carries a "
                        f"duplicate JSON member "
                        f"{str(duplicate_member.key)[:_common._AGY_DIGEST_KEY_CAP]!r} "
                        f"(original-text reject, spec C14) — the whole stream "
                        f"is refused; a surviving sibling result event must "
                        f"never be admitted in its place")
            return _done(rr, "schema-fail", _common.EXIT_SCHEMA_FAIL, audit=audit), argv
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
        # THE STRUCTURED CHANNEL IS THE ANSWER on the two structured routes
        # (gate-1 r4 row r4-10). The whole arm below used to be gated on a
        # non-blank `response`, so a result carrying a schema-checked
        # `structured_output` and an EMPTY `response` fell through to the
        # no-answer section and was discarded as `extraction-error` /
        # `empty-answer-body` — the authoritative channel thrown away because
        # the incidental one was blank. The widening is scoped to the routes
        # that HAVE a structured channel (`--json-schema-file` /
        # `--pydantic`): on a plain call an empty response stays the no-answer
        # failure it has always been. Admission still runs first, because the
        # arm it guards is where the v2 census lives.
        # The one membership test (discard-10): only the measured dict
        # `structured_output` is the structured channel; a non-dict one is
        # treated as absent here, in the schema-file arm and in the
        # quarantine predicate below.
        structured_member = isinstance(
            result.get("structured_output") if isinstance(result, dict) else None,
            dict)
        structured_route = schema_file_mode or pydantic_cls is not None
        if result is not None and (answer.strip()
                                   or (structured_route and structured_member)):
            if admission is not None:
                # v2 ADMISSION (spec § Admission): judged by what the stream
                # shows — framing, one result, allowlist census, errored steps
                # ⊆ allowed reads — never by the vendor status alone (the
                # `status != SUCCESS` discard below threw away finished reviews:
                # consultation 2026-08-22, r9 attempt 1).
                adm = admit(stream, events, result, allowlist=admission[0],
                            read_set=admission[1], prior_forbidden=forbidden_seen,
                            prior_omitted=forbidden_omitted_seen,
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
                    # DISTINCT token (2026-09-04) for the ALLOWLIST class only:
                    # a tool outside the agent's allowlist in the stream is
                    # `admission-refused` — the review skill's "one retry,
                    # then terminally missing" rule keys on it and the audit
                    # row shows the forbidden tool + that a COMPLETE answer
                    # was discarded (33 LegVerdicts lost under the generic
                    # token, audit 2026-08-22..09-03). Every OTHER refusal
                    # (framing, an unexplained degraded status, read-blind)
                    # stays `vendor-error`. Both surface-not-repair:
                    # deliberately absent from _common.CLASSIFICATION_TOKENS.
                    reason = adm.reason
                    _common.log(f"admission refused: {reason}")   # names are ASCII-escaped by admit()
                    snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                    token = "admission-refused" if adm.forbidden else "vendor-error"
                    return _done(rr, token, _common.EXIT_TERMINAL, audit=audit,
                                 err=f"admission refused: {reason}; "
                                     f"quarantined answer ({len(answer)} chars): {snippet}"), argv
                if adm.blocked:
                    # EFFECT-BASED Gate A (S2, 2026-09-17): denied before execution
                    # — by the round worktree's PreToolUse hook or the vendor's own
                    # permission policy — so nothing ran and nothing voids; the
                    # digest's `denied` list and the hook log carry the detail. An
                    # EXECUTED off-list call took the admission-refused branch above.
                    _common.log("[wrapper] antigravity blocked-calls "
                                f"n={len(adm.blocked)} "
                                f"tools={json.dumps([n[:_common._AGY_DIGEST_KEY_CAP] for n in adm.blocked[:8]], ensure_ascii=True)} "
                                f"— denied before execution; logged, not voiding")
                if degraded or adm.errored_reads:
                    _common.log("[wrapper] antigravity admitted-with-errored-steps "
                                f"n={len(adm.errored_reads)} "
                                f"tools={json.dumps([n[:_common._AGY_DIGEST_KEY_CAP] for n in adm.errored_reads[:8]], ensure_ascii=True)} "
                                f"status={str(status)[:_common._AGY_DIGEST_KEY_CAP]!r} rc={rr.vendor_exit_code} "
                                f"— {adm.reason}")
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
                return _done(rr, "vendor-error", _common.EXIT_TERMINAL, audit=audit,
                             err=f"vendor rc={rr.vendor_exit_code} "
                                 f"status={status!r} returned a non-empty "
                                 f"answer; surfaced as vendor-error. "
                                 f"quarantined answer: {snippet}"), argv
            if _AGY_TRUNCATION_MARKER_RE.search(answer):
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return _done(rr, "truncated-answer", _common.EXIT_TERMINAL, audit=audit,
                             err="agy folded the answer mid-body "
                                 "(own-line <truncated N bytes|lines> marker). "
                                 f"quarantined answer: {snippet}"), argv
            if pydantic_cls is None:
                # --json-schema-file: transport only — a dict
                # `structured_output` is the answer (`response` carries agy's
                # finish-tool metadata too, measured 2026-09-21); anything
                # else is treated as absent and the response text is printed.
                if schema_file_mode:
                    if structured_member:
                        return _done(rr, "ok", _common.EXIT_OK, audit=audit,
                                     answer=answer,
                                     validated=result["structured_output"]), argv
                    _common.log("json-schema-file: structured_output absent in "
                                "the vendor result — printing the response text")
                return _done(rr, "ok", _common.EXIT_OK, audit=audit,
                             answer=answer), argv
            ok, payload, nonrepairable = _validate_structured_detail(
                result, answer, pydantic_cls)
            if ok:
                return _done(rr, "ok", _common.EXIT_OK, audit=audit,
                             answer=answer,
                             validated=payload), argv
            # One repair turn (the validation error replayed into the
            # re-dispatch); a duplicate JSON member (C14) never takes it.
            if not schema_repaired and not nonrepairable:
                cmd = _repair_cmd(cmd, payload, web)
                schema_repaired = True
                continue
            if nonrepairable:
                _common.log("schema validation non-repairable (duplicate JSON "
                            "member) — skipping repair retry")
            # 66. The refused reply is quarantined off stdout (bounded copy in
            # `extraction_error`) when it is a duplicate member or when a dict
            # `structured_output` was the channel judged; a struct-absent
            # failure passes its text through.
            if nonrepairable or structured_member:
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return _done(rr, "schema-fail", _common.EXIT_SCHEMA_FAIL, audit=audit,
                             err=f"schema: {payload} "
                                 f"quarantined answer: {snippet}"), argv
            return _done(rr, "schema-fail", _common.EXIT_SCHEMA_FAIL, audit=audit,
                         answer=answer,
                         err=f"schema: {payload}"), argv
        # ── no usable answer from here ──
        # The ONE measured carrier only (the result-level `error`). The raw
        # stream is deliberately NOT part of the classify blob (r1/R2): it
        # carries the reviewed content, so quoted text could steer a retry or
        # a terminal classification.
        signals = _common.agy_classify_signals(result)
        def _refuse_no_answer() -> _common.RunResult:
            # The model burned the turn on a forbidden tool and returned NO
            # answer: the allowlist class, whatever run-level signal rides
            # along. The (+N more) counter carries the census overflow.
            shown = _forbidden_shown(forbidden_seen, forbidden_omitted_seen)
            _common.log(f"admission refused: tool(s) outside the allowlist appeared in the "
                        f"stream: {shown} (empty answer)")
            return _done(rr, "admission-refused", _common.EXIT_TERMINAL, audit=audit,
                         err=f"admission refused: tool(s) outside the allowlist "
                             f"appeared in the stream: {shown}; no answer")

        if forbidden_seen and admission is not None:
            return _refuse_no_answer(), argv
        if result is not None and status == "ERROR" and _is_vendor_turn_timeout(result):
            # gate r1 row 8 (2026-09-04): agy's OWN turn timeout fired before
            # the wrapper deadline (`result.error` = "timeout waiting for
            # response", empty response, vendor rc 1) — a typed vendor state
            # distinct from the wrapper-kill `timeout` (repair-routed) and
            # from the answer-present `vendor-error`. Named terminal token,
            # surface-not-repair (the repair analyzer escalated exactly this:
            # no existing class fits; rc 1 is generic). Review-leg callers:
            # re-dispatch once with a narrower read scope, then missing.
            return _done(rr, "vendor-timeout", _common.EXIT_TERMINAL, audit=audit,
                         err="vendor turn timeout: result.status=ERROR, "
                             f"error={str(result.get('error'))[:200]!r}"), argv
        if result is not None and status == "SUCCESS":
            # SUCCESS + empty response (spike P2, rc=0): a failed task the
            # vendor reports as success. Never a silent empty ok.
            note = "empty-answer-body"
            if bad_answer_type:
                note += (f" (non-string response payload: "
                         f"{type(raw_answer).__name__})")
            return _done(rr, "extraction-error", _common.EXIT_CLI_FAIL, audit=audit,
                         err=note), argv
        cls, code = _classify_no_answer(rr.stderr, signals,
                                        rr.vendor_exit_code, status, stdout=rr.stdout)
        if cls == "server-capacity" and server_attempt < max_retries:
            _server_cap_backoff(server_attempt)
            server_attempt += 1
            continue
        return _done(rr, cls, code, audit=audit), argv


def _server_cap_backoff(attempt: int) -> None:
    """Politeness sleep before a server-capacity retry (FIX 5). Suppressible
    via AGY_NO_BACKOFF=1 so unit/integration tests don't sleep 15s+."""
    if os.environ.get("AGY_NO_BACKOFF") == "1":
        return
    idx = min(attempt, len(_common.SERVER_CAP_BACKOFF_S) - 1)
    _common._signal_aware_sleep(_common.SERVER_CAP_BACKOFF_S[idx])  # C1


def _terminate_to_exit(signum, frame):
    # The engine's handler (spec C1): from the first dispatch on it only records
    # the signal and the call ends through the terminal record; before the first
    # dispatch (the `--version` probe included) it raises SystemExit(128+signum).
    # No route holds a settings lock or guard to unwind (DL-112).
    _common._terminal_signal_to_exit(signum, frame)


def _dispatch(args, ver, pydantic_cls, agy_bin,
              readonly: bool) -> tuple[_common.RunResult, list]:
    """Run the vendor call; return the driver's RunResult and the argv of the
    last attempt that spawned (the vendor argv `main()` audits).

    READ-ONLY path (v2, spec docs/superpowers/specs/2026-08-22-agy-readonly-v2-spec.md):
    setup-once tools-allowlisted agent (`--agent`, review without web tools or
    research with them under --web), `--add-dir <cwd>` so repository reads are
    auto-allowed in print mode, NO danger flag, NO settings transaction, NO agy
    --sandbox; admission by what the stream shows
    (`admit`). A fallback to agy's default agent cannot write or run a shell
    without the danger flag (ladder round 2, K1/K5) and is rejected by the
    census.

    PERMISSIVE baseline (`--sandbox` omitted, non-hardened): adds only the
    version-gated danger flag — no guard, no lock, no settings read (DL-112);
    an exception inside it reaches `_common._guarded_main` as on the
    read-only route."""
    # agy --json-schema takes a schema STRING or a path to a schema file
    # (Tier 2: `agy --help`), so a caller-owned file rides the same argument
    # as the pydantic-derived string; --json-schema-file and --pydantic are
    # mutually exclusive, checked in main() before this point.
    json_schema = getattr(args, "json_schema_file", None)
    if json_schema is None and pydantic_cls:
        json_schema = json.dumps(pydantic_cls.model_json_schema())
    if readonly:
        # `--review-web` selects exactly what `--web` selects (R-REVIEW-WEB):
        # the research agent, its allowlist and the admission of its two web
        # tools; only the investigation clause differs (appended in main()).
        web_agent = args.web or args.review_web
        agent = AGY_RESEARCH_AGENT if web_agent else AGY_REVIEW_AGENT
        allowlist = AGY_RESEARCH_TOOLS if web_agent else AGY_REVIEW_TOOLS
        read_set = AGY_READ_TOOLS_ADMIT | (AGY_WEB_TOOLS_ADMIT if web_agent else frozenset())
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
            return (_common.RunResult(_common.EXIT_TERMINAL, "", "", 0.0,
                                      classification="config-conflict",
                                      extraction_error=err, spawned=False),
                    [agy_bin])   # no vendor process ran
        cmd = _build_cmd(args.prompt, False, args.model, args.timeout,
                         json_schema=json_schema, skip_permissions=False,
                         effort=args.effort, agent=agent, add_dir=args.cwd)
        cmd[0] = agy_bin   # resolved/pinned path: a PATH shadow cannot win
        # schema_file_mode is wired on the read-only route ONLY: main() refuses
        # --json-schema-file on every other posture, so the permissive call
        # below can never be in it.
        return _run_agy_with_retry(cmd, args.prompt, args.timeout, cwd=args.cwd,
                                   repair_mode=args.repair_mode,
                                   pydantic_cls=pydantic_cls,
                                   admission=(allowlist, read_set),
                                   schema_file_mode=getattr(
                                       args, "json_schema_file", None) is not None,
                                   web=args.web)

    cmd = _build_cmd(args.prompt, False, args.model, args.timeout,
                     json_schema=json_schema,
                     skip_permissions=_agy_needs_skip_permissions(ver),
                     effort=args.effort)
    cmd[0] = agy_bin
    return _run_agy_with_retry(cmd, args.prompt, args.timeout, cwd=args.cwd,
                               repair_mode=args.repair_mode,
                               pydantic_cls=pydantic_cls)


def main() -> int:
    return _common._guarded_main("antigravity", _main)


def _main(ctx: dict) -> int:
    # SIGTERM/SIGHUP unwind instead of dying mid-call, so the vendor child
    # kill runs on the way out. No route holds a settings lock (DL-112).
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
    p.add_argument("--review-web", action="store_true",
                   help="read-only path: a REVIEW leg of a round whose bound "
                        "review_web_authorized is true (R-REVIEW-WEB) — selects "
                        "exactly what --web selects (research agent, admission "
                        "of errored web-tool steps, read-audit) but never "
                        "appends the investigation web-evidence clause; "
                        "recorded in the audit row; not with --web")
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
    p.add_argument("--json-schema-file", default=None,
                   help="Path (a relative one rebased on the process-entry cwd, "
                        "C28) to a caller-owned JSON schema file, "
                        "passed straight to agy --json-schema (which accepts "
                        "a schema string OR a path). Transport only: no local "
                        "validation and no repair re-run — the caller admits "
                        "the answer with its own validator. Read-only v2 route "
                        "only; mutually exclusive with --pydantic")
    p.add_argument("--attempt", type=int, default=1,
                   help="Dispatch attempt number carried on the transport "
                        "receipt (>=1, default 1). RECORDED only — the wrapper "
                        "never retries on it and no control flow reads it")
    # NOTE: --dangerously-* are intentionally NOT defined -> argparse rejects
    # them (danger flags are banned).
    args = p.parse_args()
    # ONE NORMALIZED MODEL REQUEST (gate-1 r13 row r13-4 — the codex shape of
    # row r12-3, generalized: the C35 / DL-3 sentence covers every leg).
    # Empty or whitespace-only = NO request; the argv build and the record
    # (`requested_model` on the summary tail, the audit row and the run-log)
    # read this one value. Surrounding whitespace is stripped (a padded value
    # is a typo) before the value is passed, recorded and compared.
    if args.model is not None:
        args.model = args.model.strip() or None
    ctx.update(attempt=args.attempt, model=args.model, reasoning=args.effort)

    if args.setup_agents:
        d = agents_dir()
        try:
            written = setup_agents(d)
        except OSError as e:
            _common.log(f"--setup-agents failed: {e}")
            return _common.EXIT_ARG_ERROR
        # THE PRINTED PATHS ARE PAYLOAD, NOT OPERATOR PROSE (gate-1 r8 row
        # r8-8; the rule r7-x2 set for the dispatch lines one library over).
        # `print()` uses this process's STRICT stdout handler, so under a
        # non-UTF-8 locale a non-ASCII agents dir raised UnicodeEncodeError
        # HERE — after the agent files had already been written — and the
        # command died at exit 1 on a setup that had SUCCEEDED, printing
        # neither the paths nor the hint. `os.fsencode` reproduces the
        # on-disk bytes exactly (it reverses the surrogateescape a
        # non-UTF-8 filesystem decode introduces), so the path the operator
        # copies is the path that exists.
        for path in written:
            _common._emit_payload(os.fsencode(path) + b"\n")
        # Same channel, same rule (row r8-8): this line is operator-copied
        # text on the payload stream, so it goes out as UTF-8 bytes too.
        _common._emit_payload(
            b"hint: research dispatches (--web) and review legs with web "
            b"(--review-web, every v2 agy leg of a round that binds "
            b"review_web_authorized true) use read_url_content / "
            b"search_web, which need the `read_url(*)` permission allowed "
            b"on this host (~/.gemini/antigravity-cli/settings.json "
            b"permissions.allow); a review dispatch without web uses only "
            b"--add-dir (passed automatically).\n")
        return _common.EXIT_OK

    if args.attempt < 1:
        _common.log(f"--attempt must be >= 1 (got {args.attempt})")
        return _common.EXIT_ARG_ERROR
    # C28: resolve the (possibly relative) --prompt-file once so the absolute
    # path can be RECORDED on the summary line and in the audit/run-log
    # records. load_prompt_text() re-resolves the same way and reads the text.
    _prompt_file_resolved = None
    try:
        if args.prompt_file:
            _prompt_file_resolved = str(
                _common.resolve_prompt_file(args.prompt_file))
        _prompt_text = _common.load_prompt_text(args.prompt, args.prompt_file)
    except Exception as e:
        _common.log(f"prompt load failed: {e}")
        return _common.EXIT_ARG_ERROR
    args.prompt = _prompt_text  # downstream code keeps using args.prompt
    ctx.update(prompt=args.prompt, prompt_file=_prompt_file_resolved)

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

    if args.web and args.review_web:
        # Two meanings for one dispatch: an investigation (the clause rides
        # the prompt) or a review leg (it never does) — refused, not guessed.
        _common.log("--web (an investigation) and --review-web (a review leg "
                    "with web) are mutually exclusive — pass one")
        return _common.EXIT_ARG_ERROR

    if (args.web or args.review_web) and args.sandbox != "read-only":
        # never silently ignored (gate r1, claude): only the read-only path
        # selects an agent, so --web / --review-web mean nothing elsewhere
        flag = "--web" if args.web else "--review-web"
        _common.log(f"{flag} selects the research agent on the read-only path only — "
                    "pass --sandbox read-only (hardened installs do so by default)")
        return _common.EXIT_ARG_ERROR

    clause_err = None
    if args.web:
        # C29: the web-evidence rule rides the END of the prompt on every research
        # dispatch (after the empty-prompt check — the clause never rescues an
        # empty dispatch). args.prompt is what audit/run-log record, so the
        # record shows the prompt as sent. The clause is rendered from the
        # vendored spec (one source); a failure refuses below, before the spawn.
        try:
            args.prompt = args.prompt + "\n\n" + _common._investigation_clause("agy")
        except RuntimeError as e:
            clause_err = str(e)
        ctx["prompt"] = args.prompt

    if args.sandbox == "read-only" and not args.web and args.cwd is None:
        # Review-agent grant precondition (owner ruling 2026-08-26): --add-dir
        # — the leg's ONLY repository read grant — is derived from --cwd, so a
        # review dispatch without it runs read-blind (the 2026-08-22 pre-fix
        # window: 211 grant-less dispatches, 94 admitted ok; the read-blind
        # admission guard catches only a run whose reads visibly errored).
        # Refuse BEFORE any vendor work; the --web research agent may
        # legitimately run grant-less (web-only research) and stays ungated.
        _common.log("--sandbox read-only (review agent) requires --cwd — the wrapper "
                    "derives --add-dir, the leg's only repository read grant, from "
                    "it; pass --cwd <abs root the leg's reads must resolve in> "
                    "(a --web research dispatch is exempt)")
        return _common.EXIT_ARG_ERROR

    # --json-schema-file: checked BEFORE any vendor work — a paid dispatch
    # whose caller-owned schema was silently dropped is worse than an
    # argument error.
    if args.json_schema_file is not None:
        if args.pydantic:
            _common.log("--json-schema-file and --pydantic are mutually "
                        "exclusive (two schema sources for one --json-schema "
                        "flag)")
            return _common.EXIT_ARG_ERROR
        if args.sandbox != "read-only":
            _common.log("--json-schema-file belongs to the read-only v2 route "
                        "(pass --sandbox read-only)")
            return _common.EXIT_ARG_ERROR
        # C28 (spec ccf168a): a relative path is rebased on the process-entry
        # cwd like --prompt-file (agy itself would resolve it against its own
        # cwd), then the same runtime-roots containment `--cwd` and
        # `--prompt-file` get (gate-1 r2 row r2-5). The resolved path is what
        # agy then reads, so the file validated here is the file used, and
        # the argv the audit row records carries that absolute path.
        try:
            args.json_schema_file = str(_common._resolve_input_file(
                args.json_schema_file, "--json-schema-file"))
        except Exception as e:
            _common.log(f"--json-schema-file validation failed: {e}")
            return _common.EXIT_ARG_ERROR

    pydantic_cls = None
    if args.pydantic:
        try:
            pydantic_cls = load_pydantic_class(args.pydantic)
        except Exception as e:
            _common.log(f"--pydantic load failed: {e}")
            return _common.EXIT_ARG_ERROR

    agy_bin = _common.require_binary("agy")
    ctx["cmd"] = [agy_bin]

    r: Optional[_common.RunResult] = None
    elapsed = 0.0
    cmd = [agy_bin]

    # The probe runs on every dispatch that reaches it (only an unrenderable
    # --web clause stops first) BY DESIGN: the stream-json floor gate below needs
    # the version read even when AGY_NO_HEADLESS_AUTOAPPROVE=1 is set — that
    # opt-out governs only the skip-permissions flag (_agy_needs_skip_permissions),
    # never the floor gate.
    # The probe runs outside a dispatch (C1): a signal during it ends 128+signum
    # with no record.
    ver = None if clause_err else _probe_agy_version(agy_bin)
    if clause_err is not None:
        # The --web clause could not be rendered from the vendored spec: no
        # vendor process runs (not even the version probe).
        _common.log(clause_err)
        r = _common.RunResult(_common.EXIT_TERMINAL, "", "", 0.0,
                              classification="config-conflict", spawned=False,
                              extraction_error=clause_err)
    elif ver is None or ver < _STREAM_JSON_FLOOR:
        # Fail-CLOSED floor: the stream-json transport is the only transport
        # (2026-07-31 migration). Surface as config-conflict (user runs
        # `agy update`), audited like every other terminal outcome.
        found = _ver_text(ver) if ver else "unprobeable"
        r = _common.RunResult(_common.EXIT_TERMINAL, "", "", 0.0,
                              classification="config-conflict", spawned=False,
                              extraction_error=(
                                  f"agy {found} < 1.1.8 — the stream-json transport "
                                  f"requires agy >= 1.1.8; run `agy update`"))
    elif (args.model or args.effort) and ver < _MODEL_FLAG_FLOOR:
        # Fail-CLOSED pin floor (see _MODEL_FLAG_FLOOR): below 1.1.10 these
        # flags were silently IGNORED (default-model fallback) — dispatching
        # would void the requested tier with no error.
        found = _ver_text(ver)
        r = _common.RunResult(_common.EXIT_TERMINAL, "", "", 0.0,
                              classification="config-conflict", spawned=False,
                              extraction_error=(
                                  f"agy {found} < 1.1.10 — --model/--effort were "
                                  f"silently ignored (default-model fallback) before "
                                  f"1.1.10; run `agy update` or drop the pin"))
    elif args.sandbox == "read-only" and ver < AGY_V2_FLOOR:
        # Fail-CLOSED v2 floor: `--add-dir` read auto-allow and the allowlist
        # agent were measured on 1.1.18; there is no legacy path (v2).
        found = _ver_text(ver)
        floor_err = (f"agy {found} < 1.1.18 — the read-only path needs agy >= "
                     f"1.1.18 (allowlist agent + --add-dir); run `agy update`")
        _common.log(floor_err)
        r = _common.RunResult(_common.EXIT_TERMINAL, "", "", 0.0,
                              classification="config-conflict", spawned=False,
                              extraction_error=floor_err)
    else:
        start = time.monotonic()
        # `cmd` = the REAL argv for the audit row + run-log
        r, cmd = _dispatch(args, ver, pydantic_cls, agy_bin, args.sandbox == "read-only")
        elapsed = time.monotonic() - start

    # R-MODEL (owner ruling Q10-2): the digest reports, the wrapper decides.
    # The ADMITTED attempt is the last one (`attempts[-1]`, the attempt whose
    # answer the run returns); an exposed model of that attempt that is not
    # byte-equal to the pinned --model is refused — the host never accepts a
    # substituted model. An earlier attempt's model is recorded, not refused.
    # Only a run that otherwise succeeded is refused; a failed run keeps its
    # own classification. Terminal (65): no retry, no repair routing.
    # `runtime_model` = the contradicting value when refused, else the
    # admitted attempt's first exposed value.
    _attempts = (r.read_audit.get("attempts")
                 if isinstance(r.read_audit, dict) else None)
    _admitted = (_attempts[-1].get("runtime_models")
                 if isinstance(_attempts, list) and _attempts
                 and isinstance(_attempts[-1], dict) else None)
    _admitted = _admitted if isinstance(_admitted, list) else []
    _contradicting = ([m for m in _admitted if m != args.model]
                      if args.model is not None else [])
    runtime_model = (_contradicting[0] if _contradicting
                     else _admitted[0] if _admitted else None)
    if _contradicting and r.exit_code == _common.EXIT_OK:
        msg = (f"requested model {args.model!r} but the agy run reported "
               f"model {runtime_model!r} — answer refused; change the model in "
               f"the roster entry (or the --model value)")
        _common.log(msg)
        r.final_answer, r.validated = "", None
        r.classification, r.exit_code = "config-conflict", _common.EXIT_TERMINAL
        r.extraction_error = msg

    # The payload: ONE UTF-8 encode; a code point UTF-8 cannot carry (a lone
    # surrogate) leaves as its `\udXXX` escape, exit and token unchanged.
    if r.validated is not None:
        _answer = json.dumps(r.validated, ensure_ascii=False) + "\n"
    else:
        _answer = r.final_answer or ""
        if _answer and not _answer.endswith("\n"):
            _answer += "\n"
    _payload = _answer.encode("utf-8", "backslashreplace")

    # The record fields only main() knows. vendor_version: `ver` is the SAME
    # _probe_agy_version() tuple the stream-json floor gate above already
    # probed — no second probe; None on a failed/unparseable probe.
    r.vendor_version = _ver_text(ver) if ver is not None else None
    r.elapsed_s = elapsed
    r.mode = "repair" if args.repair_mode else "normal"
    ctx.update(result=r, cmd=cmd)

    # Read-audit digest — emitted BEFORE the canonical summary line, on EVERY
    # completed vendor call (ok or not), so the review SKILL / leader can
    # consume it even on success (outside a review attempt the run-log only
    # exists on failure).
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
        # SUCCESS path too (outside a review attempt emit_run_log only writes on
        # failure). Best-effort — an IO failure here never changes
        # r.exit_code/classification.
        read_audit_path = _common.emit_read_audit("antigravity", r)
        if read_audit_path is not None:
            # THE VALUE IS PERCENT-ESCAPED FILESYSTEM BYTES (gate-1 r13 row
            # r13-5). Written raw, a NEWLINE in the path split the line and
            # an undecodable byte was rewritten by the `backslashreplace`
            # diagnostic stream, so the custody check (`collect_v2.
            # _agy_custody_reason`, which compares the SAME encoding) could
            # never match a legitimate attempt. `_summary_field` is the
            # summary tail's escaping: an ordinary POSIX path is emitted
            # byte-identically, anything else is escaped onto ONE line.
            _common.log(f"read-audit-file: {_common._summary_field(str(read_audit_path))}")

    # Record-only receipt inputs (C9/C10 + C28): the agy driver calls
    # _run_once with classify_and_log=False and emits its own summary below,
    # so the two fields are attached to the RunResult here instead.
    r.dispatch_attempt = args.attempt
    r.prompt_file_resolved = _prompt_file_resolved
    # C35 / DL-3 (gate-1 r13 row r13-4): the normalized model request rides
    # the same record — audit row and run-log, omit-when-None.
    r.requested_model = args.model
    # C35 as amended: the requested effort tier rides the same record.
    r.requested_reasoning = args.effort
    r.runtime_model = runtime_model

    # Canonical 1-line summary — byte-match the format _run_once emits so the
    # dispatch SKILL grep + the parity test see the same shape.
    _common.log(
        f"[wrapper] antigravity {r.classification} "
        f"exit={r.exit_code} vendor={r.vendor_exit_code} "
        f"elapsed={elapsed:.1f}s"
        + _common._summary_tail(args.attempt, _prompt_file_resolved,
                                args.model, args.effort)
    )

    _common.audit("antigravity", cmd, args.prompt, r)
    ctx["recorded"] = True
    if args.debug:
        _common.debug_log("antigravity", args.prompt, r)
    run_log_path = _common.emit_run_log(
        "antigravity", sys.argv, cmd, args.prompt, r)
    if run_log_path is not None:
        _common.log(f"run-log: {run_log_path}")

    # Stdout = the bytes built above, never a locale re-encoding.
    _common._emit_payload(_payload)
    return r.exit_code


if __name__ == "__main__":
    sys.exit(main())
