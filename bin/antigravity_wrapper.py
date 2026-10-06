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
    # Effective working directory of the vendor spawn — threaded VERBATIM from
    # RunResult.effective_cwd by every rr-based return in _run_agy_with_retry
    # (cwd record-integrity slice, 2026-08-26). None on the guard paths that
    # never spawned (config-conflict etc.), so the audit/run-log key is
    # omitted there — same shape rule as vendor_version.
    effective_cwd: Optional[str] = None
    # ENGINE transport facts, carried so `main()`'s AgyResult -> RunResult
    # rebuild does not drop them (gate-1 r4 row r4-8). `spawned` is the one
    # `RunResult` field `_common.build_transport` reads that this driver can
    # contradict: a Popen OSError creates no child, and a receipt built from
    # the default True then claimed the binary and a stdin delivery that never
    # happened. `orphans_reaped` is the C1/R-TERMINAL evidence that the owned
    # process group had members to reap. The other receipt inputs need no
    # carrier: `stdin_delivery` is structurally None on this route (agy takes
    # the prompt by argv, so `_run_once` is never given `stdin_text`), and
    # `vendor_version` / `dispatch_attempt` are set by `main()` itself.
    # `_dispatch` stamps both from the engine's LAST RunResult.
    #
    # `spawned` DEFAULTS FALSE (gate-1 r5 row r5-5). It is an OBSERVATION,
    # and the only observer is the engine: a True default meant every path
    # that refuses BEFORE the engine is reached — the stream-json floor, the
    # --model/--effort pin floor, the v2 read-only floor, a missing or
    # mismatched allowlist agent — rebuilt a RunResult claiming a spawn that
    # never happened, and `build_transport` then printed the resolved binary
    # and a stdin-delivery vocabulary value for a child that was never
    # created. Those receipts now read `binary: null` /
    # `stdin_delivery: not-started`, which is what "the engine was never
    # reached" means. Only the engine-stamped assignments in `_dispatch` can
    # set it True.
    spawned: bool = False
    orphans_reaped: bool = False
    # `RunResult.capture_complete` (gate-1 r5 row r5-2), carried for the same
    # reason as the two above: `main()` REBUILDS a RunResult out of this
    # record, so an engine fact that is not carried here is silently replaced
    # by the dataclass default — and "the capture is a prefix" would then be
    # missing from exactly the route whose driver can promote a nonzero rc.
    capture_complete: bool = True


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
    # C29: on a --web dispatch the web-evidence clause stays LAST — the
    # repair notice goes between the caller's text and the clause.
    tail = "\n\n" + AGY_WEB_EVIDENCE_CLAUSE
    head = new[i][:-len(tail)] if new[i].endswith(tail) else new[i]
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


_DIAG_NUMBER_BOUND = 10**9


def _bounded_number(value):
    """A numeric vendor field for a diagnostic line, or None: never an
    unbounded / untyped / non-finite vendor value (gate r2 row 11, post-close
    row 20 — the JSON parser admits NaN / Infinity)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if abs(value) >= _DIAG_NUMBER_BOUND:     # exact int compare FIRST — isfinite() on a
        return None                          # >float-range int raises OverflowError
    if not math.isfinite(value):
        return None
    return value


@_common._never_raises(lambda exc: ("unknown", _common.EXIT_CLI_FAIL), cli="antigravity")
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
    from `_common.agy_classify_signals` (typed error payloads only). The full
    raw stream still rides in `stream_output` for the run-log, so the repair
    agent's diagnostics are unchanged. `stdout` (the raw stream) reaches
    classify() ONLY for its auth rung, which reads `result.error` alone
    (R-AUTH (ii)); classify() keeps agy's raw stream out of the L2 blob.
    """
    status_tok = f"agy result status={str(status)[:200]}" if status else ""
    # Each typed stream signal is LABELLED so it never starts a line: a tool's
    # error text (a fetched page saying "Authentication required …") must not
    # impersonate agy's own stderr banner (R-CLASSIFY: tool output is never a
    # carrier). agy's own carriers are its real stderr lines and `result.error`
    # (read from `stdout` by the auth rung).
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


class _AgyVersion(tuple):
    """A parsed agy version tuple that keeps `text`, the version as the CLI
    printed it (C65 / R-CLI-VERSION: recorded as observed)."""
    text = None


def _parse_agy_version(text):
    """Extract the first dotted numeric version tuple from `agy --version`
    output (e.g. '1.1.3' -> (1, 1, 3)); None if unparseable. A pre-release
    (`1.1.18-rc.1`) sorts BELOW its release, so a pre-release of a floor
    version is below that floor (C18 / R-CLI-VERSION; the other host's
    rule, bin/google_preflight_v2.py:22-23): its patch reads as patch - 0.5."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?",
                  text or "")
    if not m:
        return None
    major, minor, patch = (int(g) for g in m.groups()[:3])
    ver = _AgyVersion((major, minor, patch - 0.5 if m.group(4) else patch))
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

# Research dispatches (`--web`) get this rule appended LAST to the caller's prompt
# (spec case C29, rule R-INVEST; seed of the shared clause `web-evidence`).
# Origin 2026-09-19 (host-parity rounds r1/r2): the research agent made ZERO
# read_url_content calls in both rounds and cited placeholder URLs in r2 —
# nothing told it what counts as web evidence, and agy `search_web` returns a
# model summary with grounding-redirect links, never a page (measured
# 2026-09-16). The tail position follows the documented constraint-drop shape
# (a rule at the START of a long prompt is the one most likely dropped). The
# audit row and the run-log record the prompt AS SENT, clause included.
AGY_WEB_EVIDENCE_CLAUSE = (
    "WEB EVIDENCE PROCEDURE (appended by the caller to every research dispatch; it "
    "binds every external fact in your answer). search_web returns a model-written "
    "summary and grounding-redirect links: a POINTER to sources, never a citation. For "
    "every fact you take from the web, call read_url_content on the source page itself "
    "(the official document, the version-tagged source file, the release note or the "
    "repository page) and cite the exact URL you fetched together with the date or "
    "version string visible ON that page. Never write a URL you did not fetch, a "
    "placeholder such as `https://example.com/...`, or a bare year in place of a page "
    "date. If the fetch fails or the page shows no date or version, report that fact as "
    "UNSURE and name the URL you tried. Local file facts come first, cited as "
    "path:line; web facts follow, each with its fetched URL and page date."
)

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
    `_validate_structured*` path.)"""
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
        shown = json.dumps([n[:cap] for n in forbidden[:8]], ensure_ascii=True)
        more = len(forbidden) - 8 + omitted
        return Admission(False, f"tool(s) outside the allowlist appeared in the stream: {shown}"
                                f"{f' (+{more} more)' if more > 0 else ''} — agy fell back to its "
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


# The catalog call's own timeout (a module constant, so an in-process test can
# lower it; the call is bounded either way).
_CATALOG_TIMEOUT_S = 30


@_common._never_raises(lambda exc: None, cli="antigravity")
def _catalog_auth_observed(text):
    """What a FAILED `agy models` call's output (a non-zero exit, a timeout, an
    undecodable listing or the model absent) shows of an AUTHENTICATION
    outcome, or None.

    The catalog output is the CLI's own text (a model listing — no answer, no
    reviewed file, no tool output), so it is read like every auth carrier
    (spec R-NOCOST: "judged for an authentication outcome first"; R-CLASSIFY):
    a line beginning with an agy sign-in banner (built-in or the classifier
    extension's), then the whole authentication vocabulary. Its pipe is
    binary, so a bare CR is turned into a line feed here as the engine's
    text-mode pipe does (on a CLI's own output a bare CR
    starts a line); lines are then split on LF only. No other class is
    consulted."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if _common._agy_banner_line(text):
        return "agy printed its sign-in banner"
    phrase = _common._auth_phrase("antigravity", text)
    if phrase:
        low = phrase.lower()
        kind = ("an API-key-shaped authentication failure"
                if "api_key" in low or "api key" in low or "api-key" in low
                or "apikey" in low else "an authentication failure")
        return f"agy printed {kind} ({phrase!r})"
    return None


def _model_catalog_refusal(agy_bin, model):
    """C18 / R-MODEL: None when `agy models` (one `<slug>\\t<label>` line per
    model) advertises the requested model, else (classification, reason). A
    call that exited 0 listing the model completed with its answer and is not
    judged further; a FAILED call's own output — a timed-out call's captured
    output included — is judged for an AUTHENTICATION outcome first (R-AUTH:
    the oauth-env STOP);
    every other failure, an unreadable or undecodable catalog included, is the
    configuration refusal — an unchecked model is never admitted as checked."""
    unchecked = (f"the requested model {model!r} cannot be checked against "
                 f"the route's catalog")
    def _text(raw):
        return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else (raw or "")
    # SIGTERM / SIGHUP are only RECORDED from before the spawn until the group
    # is reaped (spec e17521f): the catalog child is a dispatched child, so the
    # wrapper's handler takes the record-only mode a dispatch uses — nothing a
    # signal does can raise inside the call; once the group is gone a recorded
    # signal is RETURNED as the signal record (`unknown`), which main writes like
    # every refusal — summary, audit row, run-log (spec C1 / R-TERMINAL)
    prev = _common._SIGNAL_STATE["dispatch"]
    _common._SIGNAL_STATE["dispatch"] = True
    try:
        try:
            # its own process group, reaped like _run_once's
            proc = subprocess.Popen([agy_bin, "models"], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                    env=_common.scrubbed_child_env(),
                                    start_new_session=hasattr(os, "getpgid"))
        except (OSError, subprocess.SubprocessError) as e:
            return "config-conflict", f"`agy models` could not run ({type(e).__name__}) — {unchecked}"
        pgid = proc.pid if hasattr(os, "getpgid") else None
        cut = True
        try:
            deadline = time.monotonic() + _CATALOG_TIMEOUT_S
            while True:   # short steps: a recorded signal cuts the call short
                try:
                    out, err = proc.communicate(
                        timeout=max(0.0, min(0.1, deadline - time.monotonic())))
                    cut = False
                    break
                except subprocess.TimeoutExpired:
                    if (_common._SIGNAL_STATE["signum"] is not None
                            or time.monotonic() >= deadline):
                        break
        finally:
            if cut:   # cut short (the deadline, a signal) or unwinding: reap the group
                _common._kill_proc_group(proc, pgid)
                out = err = b""
                try:   # what it printed before; bounded, a pipe a stray holder keeps is closed
                    out, err = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired as e:
                    out, err = e.stdout, e.stderr
                    for pipe in (proc.stdout, proc.stderr):
                        if pipe is not None:
                            pipe.close()
                proc.wait()   # killed above: reaped, never a zombie
            elif pgid is not None:   # a normal exit: a helper left in the owned group
                try:                 # is reaped too (R-TERMINAL), like _run_once's
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    pass             # the group is empty
                except PermissionError:
                    _common._kill_proc_group(proc, pgid)   # cannot confirm empty
                else:
                    _common._kill_proc_group(proc, pgid)
        output = _text(out) + "\n" + _text(err)
        if cut:
            proc = None
            failure = f"`agy models` could not run (TimeoutExpired) — {unchecked}"
    finally:
        # a signal recorded during the call keeps the record-only mode on until
        # main has written its refusal (C1: a second signal never loses it)
        if _common._SIGNAL_STATE["signum"] is None:
            _common._SIGNAL_STATE["dispatch"] = prev
    signum = _common._SIGNAL_STATE["signum"]
    if signum is not None and not prev:
        _common._SIGNAL_STATE["signum"] = None
        return "unknown", (f"wrapper interrupted ({signal.Signals(signum).name}) during the "
                           f"`agy models` catalog call — nothing was dispatched")
    listing = advertised = None
    if proc is not None and proc.returncode == 0:
        try:
            listing = out.decode("utf-8")
        except UnicodeDecodeError:
            listing = None
    if listing is not None:
        def _row(line):   # a `<slug>\t<label>` listing line, or None
            slug, sep, label = line.partition("\t")
            return slug.strip() if sep and slug.strip() and label.strip() else None
        lines = listing.splitlines()
        advertised = {s for s in map(_row, lines) if s}
        if model in advertised:
            # the call COMPLETED with its answer: nothing else of its output is
            # judged (R-CLASSIFY — a label or notice carrying an auth word
            # never stops the leg)
            return None
        # a completed listing without the model: its listing lines are data,
        # only the other lines (and stderr) are read for the auth outcome
        output = "\n".join(ln for ln in lines if _row(ln) is None) + "\n" + _text(err)
    seen = _catalog_auth_observed(output)    # a FAILED call's output, first
    if seen:
        return "oauth-env", (f"`agy models`: {seen} — the owner re-logins through "
                             f"agy's own browser flow; the wrapper does not retry "
                             f"or try another route")
    if proc is None:
        return "config-conflict", failure
    if proc.returncode != 0:
        return "config-conflict", f"`agy models` exited {proc.returncode} — {unchecked}"
    if listing is None:
        return "config-conflict", f"`agy models` printed an undecodable listing — {unchecked}"
    return "config-conflict", (
        f"the agy model catalog (`agy models`) does not advertise the "
        f"requested model {model!r} — change the model in the roster entry "
        f"(or the --model value) to a listed slug")


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
    log, no exit 66 and no run-log at all (outside a review attempt
    `emit_run_log` writes on failure only), i.e. the silent leg loss
    leg-contracts § Verdict binding obligation 4 forbids. Both cells now fail LOUD, and they differ only in
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
    recorded nowhere (outside a review attempt `emit_run_log` is
    failure-only). The raw answer is now run through the same duck-typed
    `_content_nonrepairable` hook and OR'd into
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
    # PRESENCE is MEMBERSHIP, never truthiness (gate-1 r3 row r3-3b, the
    # pydantic twin of r3-3). `.get()` collapses "no such key" and
    # "`structured_output`: null" into the same None, so one JSON literal put
    # an explicitly-null schema channel on the struct-ABSENT branch below and
    # the raw `response` was validated and RETURNED as the answer — the
    # divergent second answer the r4 rule suppresses whenever the vendor
    # emitted a schema-checked channel. A present-but-unusable channel takes
    # the suppression path; only a genuinely ABSENT one keeps the
    # vendor-drift fallback.
    if isinstance(result, dict) and "structured_output" in result:
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


# The classification values that mean "the ENGINE reached no verdict here"
# (gate-1 r4 row r4-2). `unclassified` is the sentinel `_common._run_once`
# parks under `classify_and_log=False` on exactly the exits it leaves UNJUDGED
# — the discriminator the forwarding guard below tests. `ok` is the
# RunResult DATACLASS DEFAULT and is impossible from that call: the engine
# either classifies (classify_and_log=True) or parks the sentinel. Pairing it
# with a non-OK exit is self-contradictory, so it is treated as "no engine
# verdict" rather than forwarded — forwarding would report `ok` at exit 0
# with no answer, the silent success this whole rung exists to prevent.
_ENGINE_UNDECIDED = frozenset(("unclassified", "ok"))


def _run_agy_with_retry(cmd, prompt, timeout, *, cwd=None,
                        repair_mode=False, pydantic_cls=None,
                        allow_skip_retry=True, admission=None,
                        cmd_box=None, schema_file_mode=False,
                        rr_box=None) -> AgyResult:
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
    forbidden_omitted_seen = 0          # census overflow beyond the cap, MAX across attempts (row 19 / rs-r1)
    while True:
        prev_rr = _common._SIGNAL_STATE["last"]   # C1: returned AGAIN when nothing spawned
        rr = _common._run_once("antigravity", cmd, cwd, timeout,
                               classify_and_log=False)
        if rr_box is not None and (rr.spawned or rr_box[0] is None):
            # the ENGINE's own transport facts of the attempt that runs, for
            # the AgyResult rebuild in main() (row r4-8) — same out-parameter
            # idiom as cmd_box, and for the same reason: every return below
            # would otherwise have to thread them by hand. A later turn that
            # spawned nothing keeps the last turn that did, as cmd_box does
            # (the receipt and the audit `cmd` describe the same turn).
            rr_box[0] = rr
        if rr is prev_rr or (attempt_digests and not rr.spawned):
            # C1 / R-READ-AUDIT: a RETRY turn that spawned nothing — a signal
            # BETWEEN attempts (the engine handed back the previous attempt's
            # record, now carrying the signal failure) or a spawn failure on
            # the re-run. The attempts that ran are already counted; a digest
            # here would seal an attempt that never ran.
            return AgyResult(None, rr.classification,
                             _common.map_classification_to_exit(rr.classification),
                             rr.vendor_exit_code, stream_output=rr.stdout,
                             stderr=rr.stderr,
                             read_audit=_common.merge_agy_digests(attempt_digests),
                             effective_cwd=rr.effective_cwd,
                             extraction_error=rr.extraction_error)
        if cmd_box is not None and rr.spawned:
            # the REAL argv of the attempt that ran (gate r3, codex); a turn
            # that spawned nothing (above, or a spawn OSError) keeps the
            # previous one (C1)
            cmd_box[0] = list(cmd)
        stream = rr.stdout
        # A duplicate JSON member ANYWHERE in the stream refuses the whole
        # stream (spec C14; gate-1 r3 row r3-2). It is held rather than
        # returned on the spot so the TRANSPORT verdicts below keep their
        # precedence: a killed run's tail is a fragment, and diagnosing a
        # fragment as a content violation would mis-route the leader.
        duplicate_member = None
        # The census the parser had collected BEFORE a duplicate-member
        # raise (gate-1 r9 row r9-15). It is kept apart from `undecodable`
        # on purpose: the duplicate refusal has PRECEDENCE (it is the
        # non-repairable content violation, schema-fail 66), so these lines
        # are evidence on the refused attempt's digest, never a second
        # refusal that would change the token.
        partial_undecodable: list = []
        try:
            events, result, undecodable = _common.parse_agy_stream(stream)
        except _common._DuplicateJSONMember as exc:
            duplicate_member = exc
            events, result, undecodable = [], None, []
            partial_undecodable = list(exc.undecodable_lines)
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
        # PER-ATTEMPT undecodable-line census (gate-1 r7 row r7-k1), stamped
        # on the SAME record and carried into `attempts[]` by the same
        # omit-when-default rule, so the merged audit NAMES the hole in this
        # attempt's transcript instead of presenting it as ordinary evidence.
        if undecodable or partial_undecodable:
            attempt_digest["undecodable_lines"] = (undecodable
                                                   or partial_undecodable)
        # THE TRANSCRIPT WAS CUT MID-LINE (gate-1 r9 row r9-10). The parser
        # excludes a trailing fragment from its undecodable census — it is
        # a CUT, not a hole, and refusing on it blinded the no-answer
        # classifier to the actionable token (`oauth-env`,
        # `cli-subscription-cap`, the capacity retry) the run really
        # carried. The fact is still evidence, so it is recorded here under
        # the same omit-when-default rule, from the SAME helper the parser
        # uses, so the two can never disagree about which line it was.
        truncated_tail = bool(_common._agy_tail_fragment(stream))
        if truncated_tail:
            attempt_digest["truncated_tail"] = True
        # HOW MANY TERMINAL RESULTS THIS ATTEMPT'S TRANSCRIPT CARRIED
        # (gate-1 r9 row r9-1). Omit-when-DEFAULT, the same rule
        # `capture_complete` and `undecodable_lines` follow: the key appears
        # exactly where the count is not the expected 1, so the merged audit
        # NAMES the ambiguity instead of presenting the attempt as ordinary
        # evidence. Stamped BEFORE the refusal below, so the refused
        # attempt's own digest carries it.
        n_results = sum(1 for ev in events
                        if isinstance(ev, dict) and ev.get("event") == "result")
        # NOT A COUNT THE PARSE EVER MADE (gate-1 r10 row r10-10). On a
        # duplicate-member refusal the handler above resets `events` to `[]`
        # — the parse is evidence of nothing, which is exactly why it does —
        # so this stamped `result_events: 0` on the attempt digest and a
        # reader of the merged audit saw a DRAINED transcript where the
        # truth is "the stream was refused before it could be counted". The
        # `undecodable_lines` partial census (row r9-15) and the
        # `refused_attempt` marker already say what happened to this
        # attempt; an invented count is not evidence.
        if n_results != 1 and duplicate_member is None:
            attempt_digest["result_events"] = n_results
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
        attempt_digests.append(attempt_digest)
        audit = _common.merge_agy_digests(attempt_digests)
        # The key is DECODED VENDOR TEXT (row r4-6): logged verbatim, a
        # newline plus the trusted `[wrapper] antigravity ` prefix — or a
        # U+2028 / C0 control a `splitlines()` reader honours — forges
        # leader-visible lines out of a refusal. Cap first (bounded input),
        # then `ascii()`-escape, keeping the caller's own quoting; the same
        # rule verdict_v2's `_safe` applies (row r2-8). Computed ONCE, here,
        # for the marker below and the refusal's log line.
        safe_key = (None if duplicate_member is None else ascii(
            str(duplicate_member.key)[:_common._AGY_DIGEST_KEY_CAP])[1:-1])
        # THE MARKER IS STAMPED BEFORE ANY RETURN (gate-1 r13 row r13-3).
        # It lived inside the schema-fail branch below, so a refused attempt
        # that ALSO ended on the wrapper timeout — or on any other engine-
        # decided terminal verdict — returned first, and its census row read
        # as a plain synthetic zero with no marker (the hook load check
        # attributes a zero-step row nothing — 0 steps, no recorded id — for
        # a run that may have made hooked calls; with the marker it refuses
        # that census instead). Every return path now carries it; there is
        # no `continue` between here and the returns, so the merged audit a
        # return hands back is this object.
        if duplicate_member is not None and audit is not None:
            audit["refused_attempt"] = {"attempt": len(attempt_digests),
                                        "line_no": duplicate_member.line_no,
                                        "key": safe_key}
        if rr.exit_code == _common.EXIT_TIMEOUT:
            # Killed short-circuit FIRST: a killed run's stream is a partial
            # prefix — never trust a result event parsed out of it. R-AUTH
            # (ii) / R-CLASSIFY: a timed-out run is still judged on what it
            # printed before — an auth failure in agy's own carrier STOPs.
            if _common._auth_carrier_stop("antigravity", rr.stderr, rr.stdout):
                # the allowlist census rides on this STOP too, like the
                # failed-call STOP below
                note = ""
                if forbidden_seen:
                    note = ("; tool(s) outside the allowlist also appeared in "
                            "the stream: " + _forbidden_shown(
                                forbidden_seen, forbidden_omitted_seen))
                _common.log("authentication failure printed before the "
                            "timeout: STOP (owner browser re-login; no retry)"
                            + note)
                return AgyResult(None, "oauth-env", _common.EXIT_TERMINAL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 effective_cwd=rr.effective_cwd,
                                 extraction_error="authentication failure printed "
                                                  "before the timeout: owner "
                                                  "browser re-login" + note)
            return AgyResult(None, "timeout", _common.EXIT_TIMEOUT,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd)
        if (rr.exit_code != _common.EXIT_OK
                and rr.classification not in _ENGINE_UNDECIDED):
            # EVERY OTHER ENGINE-DECIDED verdict, on the same rung (gate-1 r3
            # row r3-1, widened by r4 row r4-2). The timeout arm above used to
            # be the only one, so a TERMINAL verdict `_run_once` reached on
            # its own — `truncated-answer` (a reader died on a rc-0 run, so
            # the capture is a PREFIX) or `input-delivery-failed` (the prompt
            # was never confirmed delivered) — was invisible here: this driver
            # re-derives its outcome from `vendor_exit_code` and the result
            # `status`, and BOTH read perfectly healthy in exactly those two
            # shapes, so the ok branches below printed a COMPLETE-looking
            # answer at exit 0. The other three wrappers never had the gap:
            # they reach `_run_once` only through `run_cli_with_retry`, whose
            # attempt loop returns the RunResult unchanged for every class it
            # neither retries nor promotes.
            #
            # THE DISCRIMINATOR IS THE CLASSIFICATION, NEVER THE EXIT CODE
            # (row r4-2). The r3-1 spelling was `exit_code not in (EXIT_OK,
            # EXIT_CLI_FAIL)`, which EXEMPTS every exit-1 result — and the
            # engine returns EXIT_CLI_FAIL with classification `unknown` when
            # a reader/writer thread fails to START (the child is killed and
            # reaped, its stdout kept). That engine-DECIDED failure reached
            # the ok branches again. `unclassified` is the sentinel the engine
            # parks on exactly the pairs it leaves UNJUDGED under
            # `classify_and_log=False`, so testing for it — not for an exit
            # code — is what separates "this driver decides" from "the engine
            # already decided".
            #
            # EVERY (exit_code, classification) pair `_run_once` can return
            # under `classify_and_log=False` (_common.py `_run_once`):
            #
            #   exit               classification           who owns it here
            #   -----------------  -----------------------  ----------------
            #   EXIT_ARG_ERROR 3   input-delivery-failed    forwarded (pre-spawn
            #                                               refusal: unencodable
            #                                               stdin, never on this
            #                                               argv route)
            #   EXIT_CLI_FAIL 1    unknown                  forwarded (Popen
            #                                               OSError; nothing ran)
            #   EXIT_CLI_FAIL 1    unknown                  forwarded (reader/
            #                                               writer thread start;
            #                                               a terminal signal
            #                                               mid-dispatch, C1)
            #   EXIT_CLI_FAIL 1    unknown                  forwarded ABOVE,
            #                                               before any digest (a
            #                                               signal between
            #                                               attempts: the engine
            #                                               spawned nothing and
            #                                               returned the previous
            #                                               record, C1; or a
            #                                               spawn OSError on a
            #                                               retry turn)
            #   EXIT_TIMEOUT 2     unclassified             the timeout arm ABOVE
            #                                               short-circuits first
            #   EXIT_TERMINAL 65   input-delivery-failed    forwarded
            #   EXIT_TERMINAL 65   truncated-answer         forwarded
            #   EXIT_OK 0          unclassified             this driver decides
            #   EXIT_CLI_FAIL 1    unclassified             this driver decides
            #                                               (the rc-gate /
            #                                               status-gate /
            #                                               no-answer arms)
            #
            # A forwarded verdict keeps the engine's TOKEN — a second opinion
            # re-derived from the same stdout is what this row forbids — but
            # its EXIT is conformed to the vendored vocabulary
            # (`spec/contracts/exit-tokens.json`, C8/R-TOKENS: `unknown` binds
            # to 1). Forwarding a spawn OSError verbatim would have reported
            # `unknown` at exit 3, a pairing that contract does not bind. The
            # ONE carve-out is `input-delivery-failed`, whose PRE-SPAWN arm is
            # deliberately an argument error (nothing was sent, no child
            # existed); its post-spawn arm already sits at the mapped 65, so
            # keeping `rr.exit_code` serves both. Stream and read-audit
            # custody are kept so the run-log and the leg's read evidence
            # survive the refusal.
            forwarded_exit = (
                rr.exit_code if rr.classification == "input-delivery-failed"
                else _common.map_classification_to_exit(rr.classification))
            return AgyResult(None, rr.classification, forwarded_exit,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             effective_cwd=rr.effective_cwd,
                             extraction_error=rr.extraction_error)
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
            # above the print-timeout, capture-prefix, transcript, admission
            # (allowlist) and answer-present rungs and the vendor-timeout
            # branch; never retried. Only the engine-decided verdicts above
            # (nothing of this run is read there) come first. It applies to a
            # call that FAILED: a run that completed with an answer (rc 0,
            # status SUCCESS, a response or structured output, no print
            # timeout) is not stopped by a banner line; "an answer" means a
            # USABLE one — a non-blank response or a `structured_output`
            # OBJECT, never the key's mere presence. The allowlist census
            # rides on the record when a tool outside it also ran.
            note = ""
            if forbidden_seen:
                note = ("; tool(s) outside the allowlist also appeared in the "
                        "stream: " + _forbidden_shown(forbidden_seen,
                                                      forbidden_omitted_seen))
            _common.log("authentication failure in agy's error carrier: STOP "
                        "(owner browser re-login; no retry)" + note)
            return AgyResult(None, "oauth-env", _common.EXIT_TERMINAL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             effective_cwd=rr.effective_cwd,
                             extraction_error="authentication failure in agy's "
                                              "error carrier: owner browser "
                                              "re-login" + note)
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
            return AgyResult(None, "timeout", _common.EXIT_TIMEOUT,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
                             extraction_error="agy print timeout: turn in progress, "
                                              "partial output withheld")
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
            return AgyResult(None, "truncated-answer", _common.EXIT_TERMINAL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             effective_cwd=rr.effective_cwd,
                             capture_complete=False,
                             extraction_error=(
                                 f"incomplete output capture (vendor "
                                 f"rc={rr.vendor_exit_code}): a reader thread "
                                 f"failed or did not join, so everything this "
                                 f"attempt produced came out of a PREFIX of "
                                 f"the stream and is never admitted, never "
                                 f"classified from, and never retried"))
        if n_results > 1:
            # MORE THAN ONE TERMINAL RESULT REFUSES THIS ATTEMPT (gate-1 r9
            # row r9-1), on the same PRE-RETRY rung as the undecodable and
            # duplicate-member refusals below and for the same reason: the
            # transcript does not have one unambiguous terminal answer, so
            # nothing may be read out of it.
            #
            # `parse_agy_stream` keeps the LAST result event, and the
            # exactly-one-result rule lived in `admit()` — which runs ONLY
            # in the answer-present v2 branch. So a FULLY CAPTURED stream
            # carrying a completed BLOCKING verdict followed by an ERROR
            # result with an empty `response` and a capacity phrase went the
            # other way entirely: the empty last result took the no-answer
            # road, `_classify_no_answer` read `model overloaded`, the
            # driver took its automatic server-capacity RETRY, and a clean
            # attempt 2 returned a SAFE answer that REPLACED the blocking
            # one. The count is a property of the TRANSCRIPT, so it is
            # checked here for every posture and every exit code.
            #
            # ZERO results is NOT this refusal. A drained attempt is the
            # ordinary no-answer shape whose diagnosis (`oauth-env`,
            # `cli-subscription-cap`, the capacity retry) is exactly what
            # the arms below exist for; refusing it here would blind every
            # actionable no-answer class. `admit()` keeps its own `!= 1`
            # rule for the answer-present branch, where an answer is in hand
            # and a missing terminal result IS a framing violation.
            #
            # Same token and exit as the sibling transcript refusals —
            # `vendor-error` / EXIT_TERMINAL, TERMINAL, never retried: the
            # LEADER re-dispatches (the contract's one retry).
            reason = (f"{n_results} result events in the stream (expected "
                      f"exactly 1), so this attempt has no unambiguous "
                      f"terminal answer and nothing is read out of it")
            # THE ALLOWLIST CLASS SURVIVES THIS RUNG (gate-1 r10 row r10-9).
            # The refusal returned a generic `vendor-error` and dropped the
            # census, so a multi-result stream that ALSO executed an
            # off-allowlist tool stopped classifying `admission-refused` and
            # stopped naming the tool — and the leader's handling of that
            # class (`spec/leg-contracts.md` § admission-refused: one retry,
            # then terminally missing, with the tool named) keys on the
            # token. The answer-arm refusal has always appended the census
            # to its reason (gate r1 row 2); same rule, same wording, on the
            # pre-retry rung.
            token = "vendor-error"
            if forbidden_seen:
                reason += ("; tool(s) outside the allowlist also appeared in "
                           "the stream: "
                           + _forbidden_shown(forbidden_seen,
                                              forbidden_omitted_seen))
                token = "admission-refused"
            _common.log(f"admission refused: {reason}")
            return AgyResult(None, token, _common.EXIT_TERMINAL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             effective_cwd=rr.effective_cwd,
                             extraction_error=reason)
        if undecodable:
            # AN UNDECODABLE LINE REFUSES THIS ATTEMPT (gate-1 r7 row r7-k1),
            # on the SAME rung as the duplicate member and for the same
            # reason: the transcript has a hole, so nothing read out of it can
            # be trusted — neither an answer, nor the absence of one, nor the
            # capacity phrase that would otherwise earn the automatic retry
            # below. r6-8 made the parser SKIP such a line rather than let it
            # escape as a traceback (correct), but left no flag: a drained
            # no-answer attempt carrying `model overloaded` took the
            # server-capacity retry, and a clean second attempt returned `ok`
            # with a merged audit that omitted the event entirely.
            #
            # The framing rule is ONE blanket rule and `admit` already emits
            # exactly this class for a line that does not decode to a JSON
            # object — `vendor-error` at EXIT_TERMINAL — but it runs only on
            # the answer-present v2 path, so the no-answer shape and the whole
            # permissive posture were open. Same token, same exit, decided
            # here so every posture is covered. TERMINAL: the LEADER
            # re-dispatches (the contract's one retry), as for every other
            # terminal class. The log carries the LINE NUMBER and the
            # EXCEPTION CLASS only — never the vendor bytes (row r4-6).
            shown = json.dumps(undecodable[:_common._AGY_UNDECODABLE_LOG_CAP],
                               ensure_ascii=True)
            reason = (f"stream line(s) undecodable, so this attempt's "
                      f"transcript has a hole and nothing is read out of it: "
                      f"{shown}")
            # the allowlist class survives this rung too (as on the
            # multi-result rung above): the census names the tool
            token = "vendor-error"
            if forbidden_seen:
                reason += ("; tool(s) outside the allowlist also appeared in "
                           "the stream: "
                           + _forbidden_shown(forbidden_seen,
                                              forbidden_omitted_seen))
                token = "admission-refused"
            _common.log(f"admission refused: {reason}")
            return AgyResult(None, token, _common.EXIT_TERMINAL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             effective_cwd=rr.effective_cwd,
                             extraction_error=reason)
        if duplicate_member is not None:
            # NON-REPAIRABLE (C14): a repair turn would re-dispatch on the
            # very evidence the duplicate hid, so this takes EXIT_SCHEMA_FAIL
            # directly instead of the one schema-repair re-run. The refused
            # attempt's OWN digest is empty (it comes from the parse that just
            # refused, so it is evidence of nothing); the raw stream still
            # rides out for the run-log. `safe_key` is the escaped key
            # computed once after the merge (rows r4-6 / r13-3).
            _common.log(f"agy stream line {duplicate_member.line_no} carries a "
                        f"duplicate JSON member '{safe_key}' "
                        f"(original-text reject, spec C14) — the whole stream "
                        f"is refused; a surviving sibling result event must "
                        f"never be admitted in its place")
            # CUSTODY (row r4-4): this return used to hand back `read_audit=
            # None`, which discards the AGGREGATE — and on attempt 2 of a
            # schema-repair chain the aggregate is the only record of attempt
            # 1's reads. main() then wrote neither the read-audit line nor
            # `agy-read-audit.json`, losing evidence gathered BEFORE the
            # untrusted-input violation (evidence preservation is the
            # terminating shape). The leg is INVALID either way — the token
            # and the 66 are unchanged — so nothing can PASS on this audit;
            # what it buys is that the reads stay accounted for. The marker
            # names WHICH attempt was refused, so a reader never mistakes the
            # aggregate for a complete transcript. The marker itself is
            # stamped right after the merge, before every return (row
            # r13-3), so this branch no longer re-stamps it.
            return AgyResult(None, "schema-fail", _common.EXIT_SCHEMA_FAIL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             effective_cwd=rr.effective_cwd)
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
        structured_member = (isinstance(result, dict)
                             and "structured_output" in result)
        structured_route = schema_file_mode or pydantic_cls is not None
        if result is not None and (answer.strip()
                                   or (structured_route and structured_member)):
            if truncated_tail:
                # AN ANSWER READ OUT OF A CUT TRANSCRIPT IS A FRAGMENT'S
                # ANSWER (gate-1 r10 row r10-13). Row r9-10 exempts a
                # trailing fragment from the undecodable census so the
                # NO-ANSWER classifier can still name the actionable token
                # (`oauth-env`, `cli-subscription-cap`, the capacity retry)
                # — that path is untouched, and this rung sits INSIDE the
                # answer-present branch for exactly that reason. But when
                # an answer IS in hand, the cut is the thing that decided
                # WHICH answer: a stream killed while a SECOND result event
                # was being written returned result #1 as `ok` on the
                # permissive posture. The v2 path was covered by `admit()`'s
                # framing rule (a line that does not decode to a JSON object
                # makes the run unusable), so this states the same rule on
                # EVERY posture and with the precise token.
                #
                # `truncated-answer` / EXIT_TERMINAL is the existing class
                # for "everything this attempt produced came out of a
                # PREFIX" — the same token the incomplete-capture rung
                # above uses for the identical fact. TERMINAL: the LEADER
                # re-dispatches (the contract's one retry); no answer rides
                # out, a bounded copy goes to the run-log.
                snippet = (answer if len(answer) <= 2000
                           else answer[:2000] + " …[truncated]")
                reason = ("the transcript was CUT mid-line (a trailing "
                          "fragment), so the answer this attempt carries is "
                          "whatever the cut left behind — a later result "
                          "event may have been in flight; nothing is "
                          "admitted out of a fragment. quarantined answer "
                          f"({len(answer)} chars): {snippet}")
                _common.log("the stream was cut mid-line and this attempt "
                            "carries an answer — terminal, never retried")
                return AgyResult(None, "truncated-answer",
                                 _common.EXIT_TERMINAL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 effective_cwd=rr.effective_cwd,
                                 extraction_error=reason)
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
                    if adm.forbidden and not reason.startswith("tool(s) outside the allowlist"):
                        # an early (framing / result-count) refusal still names
                        # the forbidden tool(s) the census saw (gate r1 row 2);
                        # the test is on the wrapper-authored PREFIX, never on
                        # a substring a vendor stdout excerpt could spoof
                        reason += ("; tool(s) outside the allowlist also appeared in the stream: "
                                   + _forbidden_shown(adm.forbidden, adm.omitted))
                    _common.log(f"admission refused: {reason}")   # names are ASCII-escaped by admit()
                    snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                    token = "admission-refused" if adm.forbidden else "vendor-error"
                    return AgyResult(None, token, _common.EXIT_TERMINAL,
                                     rr.vendor_exit_code, stream_output=stream,
                                     stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
                                     extraction_error=(f"admission refused: {reason}; "
                                                       f"quarantined answer ({len(answer)} chars): {snippet}"))
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
                return AgyResult(None, "vendor-error", _common.EXIT_TERMINAL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
                                 extraction_error=(
                                     f"vendor rc={rr.vendor_exit_code} "
                                     f"status={status!r} returned a non-empty "
                                     f"answer; surfaced as vendor-error. "
                                     f"quarantined answer: {snippet}"))
            if _AGY_TRUNCATION_MARKER_RE.search(answer):
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "truncated-answer", _common.EXIT_TERMINAL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
                                 extraction_error=(
                                     "agy folded the answer mid-body "
                                     "(own-line <truncated N bytes|lines> marker). "
                                     f"quarantined answer: {snippet}"))
            if pydantic_cls is None:
                # --json-schema-file (caller-owned producer schema): the
                # SCHEMA-CONSTRAINED channel is the answer, exactly as on the
                # pydantic path (`_validate_structured_with_trigger` prefers
                # `structured_output` and main() prints `validated`). Measured
                # 2026-09-21: agy's result event carries BOTH channels, and
                # `response` is the same JSON plus agy's own finish-tool
                # metadata (`toolAction`, `toolSummary`) — printing it made
                # verdict_v2 admission fail with "Additional properties are
                # not allowed ('toolAction', 'toolSummary' were unexpected)".
                # This wrapper still validates nothing and retries nothing:
                # it only picks the channel the vendor schema-checked.
                #
                # PRESENCE is decided by MEMBERSHIP, never by truthiness
                # (gate-1 r3 row r3-3): `.get()` returns None both for a
                # missing key and for `"structured_output": null`, so one JSON
                # literal put an explicitly-null schema channel on the ABSENT
                # branch and printed the response text at exit 0 — the very
                # divergent answer the present-but-unusable arm below refuses.
                # `structured_member` is computed ONCE, above the answer
                # guard, because that guard now reads it too (row r4-10).
                structured = (result.get("structured_output")
                              if isinstance(result, dict) else None)
                if schema_file_mode:
                    if isinstance(structured, dict):
                        return AgyResult(answer, "ok", _common.EXIT_OK,
                                         rr.vendor_exit_code, stream_output=stream,
                                         stderr=rr.stderr, read_audit=audit,
                                         effective_cwd=rr.effective_cwd,
                                         validated=structured)
                    if structured_member:
                        # PRESENT but not an object (gate-1 r2 row r2-2): the
                        # schema-constrained channel EXISTS and is unusable, so
                        # this dispatch has NO admissible answer. Falling
                        # through to `response` here would hand the caller a
                        # divergent answer the vendor never schema-checked —
                        # exactly the fallback the pydantic arm suppresses
                        # (`_validate_structured_with_trigger`). The response
                        # text is quarantined in the reason, never on stdout.
                        #
                        # ONE CONDITION, ONE TOKEN (gate-1 r4 row r4-13): the
                        # IDENTICAL vendor shape on the `--pydantic` arm is
                        # the suppressed-raw-fallback failure and emits
                        # `schema-fail` / EXIT_SCHEMA_FAIL. This arm emitted
                        # `extraction-error` / EXIT_CLI_FAIL for the same
                        # fact, and `extraction-error` MANDATES a repair-agent
                        # dispatch (dispatch SKILL Hard rule 8) — with nothing
                        # for that agent to patch, because the defect is the
                        # vendor's channel, not this host's classifier. It is
                        # NON-REPAIRABLE by construction here: this arm runs
                        # only when `pydantic_cls is None`, so there is no
                        # schema-repair loop to re-enter, and the return is
                        # terminal. Reason text takes the pydantic arm's
                        # wording so one grep finds both.
                        snippet = (answer if len(answer) <= 2000
                                   else answer[:2000] + " …[truncated]")
                        return AgyResult(None, "schema-fail",
                                         _common.EXIT_SCHEMA_FAIL,
                                         rr.vendor_exit_code, stream_output=stream,
                                         stderr=rr.stderr, read_audit=audit,
                                         effective_cwd=rr.effective_cwd,
                                         extraction_error=(
                                             f"structured_output present but "
                                             f"unusable "
                                             f"({type(structured).__name__}); "
                                             f"raw-response fallback "
                                             f"suppressed: the "
                                             f"schema-constrained channel is "
                                             f"the only answer the vendor "
                                             f"checked and the response text "
                                             f"is not a substitute. "
                                             f"quarantined answer: {snippet}"))
                    _common.log("json-schema-file: structured_output absent in "
                                "the vendor result — printing the response text")
                return AgyResult(answer, "ok", _common.EXIT_OK,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd)
            ok, payload, nonrepairable, trigger = _validate_structured_with_trigger(
                result, answer, pydantic_cls)
            if ok:
                return AgyResult(answer, "ok", _common.EXIT_OK,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
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
            #
            # PRESENCE is MEMBERSHIP here too (row r3-3b): this predicate has
            # to agree with `_validate_structured_with_trigger`'s, or a null
            # channel would be refused by the validator and then have its
            # suppressed raw reply printed to stdout anyway.
            structured_present = (isinstance(result, dict)
                                  and "structured_output" in result)
            if nonrepairable or structured_present:
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "schema-fail", _common.EXIT_SCHEMA_FAIL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
                                 extraction_error=(f"schema: {payload} "
                                                   f"quarantined answer: {snippet}"))
            return AgyResult(answer, "schema-fail", _common.EXIT_SCHEMA_FAIL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
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
        def _refuse_no_answer(vendor_class=None) -> AgyResult:
            # gate r1 row 3 / r2 row 14 (2026-09-04/05): the model burned the
            # turn on a forbidden tool (manage_task …) and returned NO answer —
            # the allowlist class, not extraction-error / unknown (a repair
            # dispatch with nothing to patch). Same token, no answer; the
            # (+N more) counter carries the accumulated census overflow (row 19).
            shown = _forbidden_shown(forbidden_seen, forbidden_omitted_seen)
            note = f"; vendor terminal signal also present: {vendor_class}" if vendor_class else ""
            _common.log(f"admission refused: tool(s) outside the allowlist appeared in the "
                        f"stream: {shown} (empty answer){note}")
            return AgyResult(None, "admission-refused", _common.EXIT_TERMINAL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
                             extraction_error=(f"admission refused: tool(s) outside the allowlist "
                                               f"appeared in the stream: {shown}; no answer{note}"))

        if forbidden_seen and admission is not None:
            # A forbidden-tool run with NO answer is decided HERE, before any
            # retry loop or tool-signal classification (residual-slice r1):
            # run-level evidence ONLY (stderr + vendor rc + the result status
            # token) — a forbidden tool's own error text can ECHO model-authored
            # arguments ("… model overloaded …"), so tool-step signals never
            # decide a forbidden run's class.
            # run-level signals = stderr + STANDALONE error_message steps +
            # the result-level error (agy's own channel, but NOT auth carriers:
            # R-CLASSIFY's closed carrier list for agy is `result.error` and a
            # stderr line beginning with the banner, read by
            # `_auth_carrier_stop` above). Any step carrying a `tool_info` dict is
            # dropped WHATEVER its step_type or envelope (the signal harvester
            # reads tool_info.error from every step, and a tool error can echo
            # model-authored arguments — rs-r2/rs-r3, codex + claude). The
            # result-level error is a vendor-typed carrier; it only ever
            # ANNOTATES here (a result event forces the refusal below).
            run_level_events = [ev for ev in (events or [])
                                if not (isinstance(ev, dict)
                                        and isinstance(ev.get("step_update"), dict)
                                        and (ev["step_update"].get("step_type") == "tool"
                                             or isinstance(ev["step_update"].get("tool_info"), dict)))]
            run_level_signals = _common.agy_classify_signals(run_level_events, result)
            run_level_cls, run_level_code = _classify_no_answer(rr.stderr, run_level_signals,
                                                                rr.vendor_exit_code, status,
                                                                stdout=rr.stdout)
            if run_level_cls in ("unknown", "extraction-error"):
                run_level_cls = None
            if result is not None and status == "ERROR" and _is_vendor_turn_timeout(result):
                # ADDITIVE: both remedies stay visible (rs-r3, claude F4/F5)
                run_level_cls = f"{run_level_cls} + vendor-timeout" if run_level_cls else "vendor-timeout"
            if result is not None or run_level_cls is None:
                # a terminal result event, or no recognised vendor class → the
                # allowlist token (Policy D's audited signal), annotated with
                # any run-level vendor class seen (claude M7)
                return _refuse_no_answer(vendor_class=run_level_cls)
            # no result event + a recognised run-level TERMINAL vendor class:
            # keep its attribution — but never a capacity RETRY here (a fresh
            # dispatch by the CALLER is the contract's one retry; claude M4 /
            # agy HS). The allowlist slip still reaches stderr (rs-r2).
            _common.log(f"{run_level_cls} on a run that also called tool(s) outside the allowlist: "
                        f"{_forbidden_shown(forbidden_seen, forbidden_omitted_seen)}")
            return AgyResult(None, run_level_cls, run_level_code, rr.vendor_exit_code,
                             stream_output=stream, stderr=rr.stderr,
                             read_audit=audit, effective_cwd=rr.effective_cwd,
                             extraction_error=(f"{run_level_cls} on a run that also called tool(s) "
                                               f"outside the allowlist: "
                                               f"{_forbidden_shown(forbidden_seen, forbidden_omitted_seen)}"))
        if result is not None and status == "ERROR" and _is_vendor_turn_timeout(result):
            # gate r1 row 8 (2026-09-04): agy's OWN turn timeout fired before
            # the wrapper deadline (`result.error` = "timeout waiting for
            # response", empty response, vendor rc 1) — a typed vendor state
            # distinct from the wrapper-kill `timeout` (repair-routed) and
            # from the answer-present `vendor-error`. Named terminal token,
            # surface-not-repair (the repair analyzer escalated exactly this:
            # no existing class fits; rc 1 is generic). Review-leg callers:
            # re-dispatch once with a narrower read scope, then missing.
            return AgyResult(None, "vendor-timeout", _common.EXIT_TERMINAL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
                             extraction_error=("vendor turn timeout: result.status=ERROR, "
                                               f"error={str(result.get('error'))[:200]!r}, "
                                               f"duration_seconds={_bounded_number(result.get('duration_seconds'))}"))
        if result is not None and status == "SUCCESS":
            # SUCCESS + empty response (spike P2, rc=0): a failed task the
            # vendor reports as success. Never a silent empty ok.
            note = "empty-answer-body"
            if bad_answer_type:
                note += (f" (non-string response payload: "
                         f"{type(raw_answer).__name__})")
            return AgyResult(None, "extraction-error", _common.EXIT_CLI_FAIL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit, effective_cwd=rr.effective_cwd,
                             extraction_error=note)
        cls, code = _classify_no_answer(rr.stderr, signals,
                                        rr.vendor_exit_code, status, stdout=rr.stdout)
        if cls == "server-capacity" and server_attempt < max_retries:
            _server_cap_backoff(server_attempt)
            server_attempt += 1
            continue
        return AgyResult(None, cls, code, rr.vendor_exit_code,
                         stream_output=stream, stderr=rr.stderr,
                         read_audit=audit, effective_cwd=rr.effective_cwd)


def _server_cap_backoff(attempt: int) -> None:
    """Politeness sleep before a server-capacity retry (FIX 5). Suppressible
    via AGY_NO_BACKOFF=1 so unit/integration tests don't sleep 15s+."""
    if os.environ.get("AGY_NO_BACKOFF") == "1":
        return
    idx = min(attempt, len(_common.SERVER_CAP_BACKOFF_S) - 1)
    _common._signal_aware_sleep(_common.SERVER_CAP_BACKOFF_S[idx])  # C1


def _terminate_to_exit(signum, frame):
    # The engine's handler (spec C1): during a pre-dispatch probe (`--version`,
    # the catalog) and from the first dispatch on it only records the signal
    # and the call ends through the terminal record; outside those windows
    # before the first dispatch it raises SystemExit(128+signum); a
    # permissive-baseline call then unwinds through its settings guard, which
    # holds an empty deny list (lock + stale-`.agybak` heal, nothing to
    # restore) and releases the lock. The read-only route enters no guard.
    _common._terminal_signal_to_exit(signum, frame)


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
        rr_box = [None]
        # schema_file_mode is wired on the read-only route ONLY: main() refuses
        # --json-schema-file on every other posture, so the permissive call
        # below can never be in it.
        r = _run_agy_with_retry(cmd, args.prompt, args.timeout, cwd=args.cwd,
                                repair_mode=args.repair_mode,
                                pydantic_cls=pydantic_cls,
                                allow_skip_retry=False,
                                admission=(allowlist, read_set), cmd_box=cmd_box,
                                schema_file_mode=getattr(
                                    args, "json_schema_file", None) is not None,
                                rr_box=rr_box)
        r.elapsed = time.monotonic() - start
        r.cmd = cmd_box[0]   # the argv that actually ran last (a schema-repair retry rewrites -p)
        # row r4-8: the engine's transport facts, or the AgyResult defaults
        # when the engine was never reached (rr_box[0] is None).
        if rr_box[0] is not None:
            r.spawned = rr_box[0].spawned
            r.orphans_reaped = rr_box[0].orphans_reaped
            r.capture_complete = rr_box[0].capture_complete
        return r

    cmd = _build_cmd(args.prompt, False, args.model, args.timeout,
                     json_schema=json_schema,
                     skip_permissions=_agy_needs_skip_permissions(ver),
                     effort=args.effort)
    cmd[0] = agy_bin
    r: Optional[AgyResult] = None
    cmd_box = [cmd]
    rr_box = [None]
    try:
        with _agy_settings.agy_settings_guard([], lock_timeout=settings_lock_timeout):
            r = _run_agy_with_retry(cmd, args.prompt, args.timeout, cwd=args.cwd,
                                    repair_mode=args.repair_mode,
                                    pydantic_cls=pydantic_cls, cmd_box=cmd_box,
                                    rr_box=rr_box)
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
    # row r4-8, as on the read-only branch above.
    if rr_box[0] is not None:
        r.spawned = rr_box[0].spawned
        r.orphans_reaped = rr_box[0].orphans_reaped
        r.capture_complete = rr_box[0].capture_complete
    return r


def main() -> int:
    return _common._guarded_main("antigravity", _main)


def _main(ctx: dict) -> int:
    # The DIAGNOSTIC stream survives any locale; the PAYLOAD stream is never
    # re-encoded (gate-1 r7 row r7-c2 — `_common` § payload vs diagnostic).
    _common._relax_diagnostic_stream()
    # SIGTERM/SIGHUP unwind instead of dying mid-call, so the vendor child
    # kill and (permissive baseline only) the settings guard's lock release run
    # on the way out; that guard holds an empty deny list, so it writes no
    # snapshot and restores nothing. SIGKILL stays uncoverable by design — the
    # kernel drops the lock and the next guard entry heals a stale `.agybak`.
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
        try:
            # heal a stale `.agybak` a deny transaction left (the codex host's copy,
            # which shares the settings file, or a pre-v2 build)
            # (gate r1, claude): on a hardened host every dispatch is now read-only
            # and never enters the guard, so setup is the remaining heal point
            with _agy_settings.agy_settings_guard([], lock_timeout=30.0):
                pass
        except (TimeoutError, json.JSONDecodeError, ValueError, OSError) as e:
            _common.log(f"--setup-agents: settings heal skipped: {e}")
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
    _refused = _common._review_argv_refusal()
    if _refused is not None:  # C32: an edited review line, before any vendor work
        _common.log(_refused)
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

    if args.web:
        # C29: the web-evidence rule rides the END of the prompt on every research
        # dispatch (after the empty-prompt check — the clause never rescues an
        # empty dispatch). args.prompt is what audit/run-log record, so the
        # record shows the prompt as sent.
        args.prompt = args.prompt + "\n\n" + AGY_WEB_EVIDENCE_CLAUSE
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

    r: Optional[AgyResult] = None
    elapsed = 0.0
    cmd = [agy_bin]

    # Probe is unconditional BY DESIGN: the stream-json floor gate below needs
    # the version read even when AGY_NO_HEADLESS_AUTOAPPROVE=1 is set — that
    # opt-out governs only the skip-permissions flag (_agy_needs_skip_permissions),
    # never the floor gate.
    # The settings-lock knob is an ARGUMENT check, so it runs BEFORE the version
    # probe (C65: a refusal after the probe would discard an observed version
    # without a record). It belongs to the permissive baseline's guard; the
    # read-only path v2 enters no transaction (gate r1, codex).
    settings_lock_timeout = 30.0
    if args.sandbox != "read-only":
        raw_lt = os.environ.get("AGY_SETTINGS_LOCK_TIMEOUT", "30")
        try:
            float(raw_lt)
        except ValueError:
            _common.log("AGY_SETTINGS_LOCK_TIMEOUT must be a number")
            return _common.EXIT_ARG_ERROR
        settings_lock_timeout = _lock_wait_seconds(raw_lt)   # inf/nan/negative -> 30
    # A pre-dispatch vendor probe runs in the record-only signal mode a dispatch
    # uses (C1 / R-TERMINAL): a SIGTERM / SIGHUP during it ends through the
    # interrupted-run record below — summary, audit row, run-log — never a bare
    # 128 + signum exit (the bounded probe finishes first, at most 15 s).
    prev_dispatch = _common._SIGNAL_STATE["dispatch"]
    _common._SIGNAL_STATE["dispatch"] = True
    try:
        ver = _probe_agy_version(agy_bin)
    finally:
        # a signal recorded during the probe keeps the record-only mode on
        # until its refusal is written (C1: a second signal never loses it)
        if _common._SIGNAL_STATE["signum"] is None:
            _common._SIGNAL_STATE["dispatch"] = prev_dispatch
    probe_signum = None if prev_dispatch else _common._SIGNAL_STATE["signum"]
    if probe_signum is not None:
        _common._SIGNAL_STATE["signum"] = None
        why = (f"wrapper interrupted ({signal.Signals(probe_signum).name}) during the "
               f"`agy --version` probe — nothing was dispatched")
        _common.log(why)
        r = AgyResult(None, "unknown", _common.EXIT_CLI_FAIL, -1, extraction_error=why)
    elif ver is None or ver < _STREAM_JSON_FLOOR:
        # Fail-CLOSED floor: the stream-json transport is the only transport
        # (2026-07-31 migration). Surface as config-conflict (user runs
        # `agy update`), audited like every other terminal outcome.
        found = _ver_text(ver) if ver else "unprobeable"
        r = AgyResult(None, "config-conflict", _common.EXIT_TERMINAL, -1,
                      extraction_error=(
                          f"agy {found} < 1.1.8 — the stream-json transport "
                          f"requires agy >= 1.1.8; run `agy update`"))
    elif (args.model or args.effort) and ver < _MODEL_FLAG_FLOOR:
        # Fail-CLOSED pin floor (see _MODEL_FLAG_FLOOR): below 1.1.10 these
        # flags were silently IGNORED (default-model fallback) — dispatching
        # would void the requested tier with no error.
        found = _ver_text(ver)
        r = AgyResult(None, "config-conflict", _common.EXIT_TERMINAL, -1,
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
        r = AgyResult(None, "config-conflict", _common.EXIT_TERMINAL, -1,
                      extraction_error=floor_err)
    elif (args.sandbox == "read-only" and not args.web and args.model and
          (catalog := _model_catalog_refusal(agy_bin, args.model))):
        # C18: the review route (with or without --review-web) checks the
        # requested model against the route's catalog BEFORE inference
        # (R-MODEL); a raw call and a --web investigation keep caller
        # passthrough.
        _common.log(catalog[1])
        r = AgyResult(None, catalog[0], _common.map_classification_to_exit(catalog[0]), -1,
                      extraction_error=catalog[1])
    else:
        r = _dispatch(args, ver, pydantic_cls, agy_bin, args.sandbox == "read-only",
                      settings_lock_timeout=settings_lock_timeout)
        elapsed = r.elapsed if r.elapsed is not None else 0.0
        if r.cmd:
            cmd = r.cmd  # the REAL argv for the audit row + run-log

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
        r.final_answer, r.validated = None, None
        r.classification, r.exit_code = "config-conflict", _common.EXIT_TERMINAL
        r.extraction_error = msg

    # THE PAYLOAD IS DECIDED BEFORE THE AUDIT ROW (gate-1 r7 rows r7-c2 /
    # r7-k5). stdout is the payload channel and was written LAST with the
    # strict locale encoder, so two shapes lost a finished verdict after every
    # record claimed `ok`: an em-dash under a non-UTF-8 locale, and a
    # `structured_output` string carrying an escaped lone surrogate (which has
    # no UTF-8 encoding at ANY locale). The bytes are built HERE, above the
    # `rr` rebuild, so a demotion reaches the audit row, the run-log, the
    # canonical summary line and this function's exit code by construction;
    # `_common._emit_payload` at the tail only writes them.
    if r.validated is not None:
        _payload = _common._payload_or_demote(
            "antigravity", r,
            json.dumps(r.validated, ensure_ascii=False) + "\n", r.validated)
    else:
        _answer = r.final_answer or ""
        if _answer and not _answer.endswith("\n"):
            _answer += "\n"
        _payload = _common._payload_or_demote("antigravity", r, _answer)

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
        vendor_version=_ver_text(ver) if ver is not None else None,
        effective_cwd=r.effective_cwd,
        # row r4-8: the ENGINE's transport facts, not this rebuild's defaults.
        spawned=r.spawned,
        orphans_reaped=r.orphans_reaped,
        # row r5-2: the engine's reader outcome, so the receipt and the
        # run-log say whether the transcript behind this record was whole.
        capture_complete=r.capture_complete,
    )
    ctx.update(result=rr, cmd=cmd)

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
        # rr.exit_code/classification.
        read_audit_path = _common.emit_read_audit("antigravity", rr)
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
    rr.dispatch_attempt = args.attempt
    rr.prompt_file_resolved = _prompt_file_resolved
    # C35 / DL-3 (gate-1 r13 row r13-4): the normalized model request rides
    # the same record — audit row and run-log, omit-when-None.
    rr.requested_model = args.model
    # C35 as amended: the requested effort tier rides the same record.
    rr.requested_reasoning = args.effort
    rr.runtime_model = runtime_model
    # R-REVIEW-WEB (case C32): a review leg dispatched with web is recorded.
    rr.review_web = args.review_web

    # Canonical 1-line summary — byte-match the format _run_once emits so the
    # dispatch SKILL grep + the parity test see the same shape.
    _common.log(
        f"[wrapper] antigravity {r.classification} "
        f"exit={r.exit_code} vendor={r.vendor_exit_code} "
        f"elapsed={elapsed:.1f}s"
        + _common._summary_tail(args.attempt, _prompt_file_resolved,
                                args.model, args.effort)
    )

    _common.audit("antigravity", cmd, args.prompt, rr)
    ctx["recorded"] = True
    if args.debug:
        _common.debug_log("antigravity", args.prompt, rr)
    run_log_path = _common.emit_run_log(
        "antigravity", sys.argv, cmd, args.prompt, rr)
    if run_log_path is not None:
        _common.log(f"run-log: {run_log_path}")

    # Stdout = the UTF-8 BYTES built above, never a locale re-encoding.
    _common._emit_payload(_payload)
    return r.exit_code


if __name__ == "__main__":
    sys.exit(main())
