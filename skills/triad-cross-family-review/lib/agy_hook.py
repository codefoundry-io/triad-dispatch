#!/usr/bin/env python3
"""agy_hook.py — the agy leg's PreToolUse hook and its LOAD CHECK
(triad-cross-family-review, S2 enforcement — plan
2026-09-16-cfr-delivery-and-enforcement-redesign § Enforcement).

Two modes, one file, python3 stdlib only, no AI:

  hook mode    agy_hook.py --log <abs-jsonl> [--web]
      (--web: a round with review web — a v2 round whose bound
      review_web_authorized is true; WEB_TOOLS join the allow set,
      everything else below is unchanged)
      agy runs this on EVERY tool call of a review leg (the round worktree's
      `.agents/hooks.json`, written by `review_scratch.py prepare`, matcher
      "*"). stdin: the vendor's PreToolUse payload (`toolCall.name`,
      `toolCall.args`, `conversationId`, `stepIdx`, ...); stdout: ONE JSON
      object `{"decision": "allow"}` or `{"decision": "deny", "reason": ...}`.
      `decide()` is the whole policy — an ALLOW-LIST (H1, plan
      2026-09-18-cfr-post-review-hardening): the five review tools the
      wrapper census admits (`ALLOW_TOOLS`, pinned equal to the wrapper's
      `AGY_REVIEW_TOOLS` by t9) are allowed; EVERY other name — mutating,
      command, network, subagent, planner, prompt-shaped, or one agy ships
      tomorrow — is denied before it runs (logged, non-voiding). This
      reverses the S2 "unknown → allow" choice: an unknown tool that mutates
      must be blocked before it executes, not voided after. The vendor's
      hooks.json matcher is a regex with no documented no-match default, so
      the allow-list lives here behind the `*` matcher. A broken hook denies
      every call including reads and the leg produces no answer at all
      (measured 2026-09-16, arm C), so this handler stays small enough to be
      obviously correct. The reply is ONLY `decision` (+ `reason`); the
      documented `permissionOverrides` field is never emitted. A payload it
      cannot read, or a call with no name, is DENIED (fail-closed; that is
      loud, never a silent write). One JSON line per invocation is
      appended to --log — tool, decision, conversation id, step index — and
      NEVER the tool arguments (a write's args carry the file body). A log the
      hook cannot write is reported on stderr and the decision still answers.

  check mode   agy_hook.py check <abs-read-audit.json> <abs-hook-log.jsonl>
      The LOAD CHECK the redesign owes, for ONE attempt: `--agent <unknown>`
      fails OPEN silently (measured 2026-09-16 — a bogus agent name yields a
      fully write-capable default and the stream cannot tell), so each agy
      attempt must PROVE the hook layer loaded for its own run. Exactly two
      paths: the attempt's read audit and the round's hook log (one
      `.agents/hooks.json` per round worktree, so every leg appends to one
      log); any other argv is usage 64. ATTRIBUTION BY THE ATTEMPT'S OWN
      CONVERSATION IDS (spec case C23): the wrapper records each vendor run's
      ids on its census row (`digest.attempts[].conversation_ids`) and the
      hook logs the payload's `conversationId` on every row (MEASURED
      2026-09-26, DL-6). A hook row with no id attributes nothing. Verdicts,
      in this order: ABSENT (2) — no read audit; INCONCLUSIVE (4) — broken
      evidence: an unreadable audit, no `digest.tool_steps`, no `attempts`
      census, a malformed census, a stepped row with no usable id, or a log
      line that is not a hook row; VOID (3) — stepped rows and zero hook
      invocations; INCONCLUSIVE (4) — no stepped row and no invocation
      (nothing proves or disproves the hook); VOID (3) — a stepped row of
      THIS audit with no hook row under any of its own ids, each one named;
      else PASS (0). Equality of steps and rows is NOT required (a call the
      vendor rejects at argument validation never reaches the hook —
      measured 2026-09-17: 4 tool steps, 3 invocations).
      stdout ends with the greppable summary
      `HOOK_LOAD_<VERDICT> tool_steps=<n> invocations=<n> denied=<n>`, plus
      ` attributed=<hooked>/<must>` when more than one census row must be
      attributed; exit 0 PASS / 2 ABSENT / 3 VOID / 4 INCONCLUSIVE / 64 usage.

Measured vocabulary (agy 1.2.5, 2026-09-17): a denied call reaches the stream
as state ERROR with tool_info.error.message "tool call denied by pre-tool
hook: <reason>"; the run stays SUCCESS / rc 0 and the file is never written.
The wrapper's admission census reads that denial as BLOCKED (logged, not
voiding) — an off-list call that EXECUTES still voids the answer. A denied
PROMPT-shaped call (`ask_question`, measured 2026-09-18, h1-deny-probe) reaches
the stream as `step_type: unknown`, state ERROR, with NO tool name, so the
census and the digest's `denied` list cannot attribute it — the hook log is
the record that names it (H3 carries the evidence duty).
"""
from __future__ import annotations

import errno
import json
import os
import stat
import sys
import time
from pathlib import Path

# ONE allow set, shared with the wrapper's admission census (AGY_REVIEW_TOOLS in
# the wrapper's antigravity_wrapper.py, shipped as bin/ — t9 pins the two equal at
# test time, no runtime import across the artifacts). Every other tool name — mutating,
# executing, network, subagent, MCP, prompt-shaped or one agy ships tomorrow —
# is DENIED before it runs: logged, non-voiding. The vendor's hooks.json matcher
# is a regular expression with no documented no-match default decision
# (antigravity.google/docs/hooks, accessed 2026-09-18), so a config-level
# allow-list could not fail closed; the policy lives here behind `*`.
ALLOW_TOOLS = frozenset({"view_file", "grep_search", "list_dir", "find_by_name", "finish"})
# A round with review web (`--log <file> --web`: a v2 round binding
# review_web_authorized true) also allows these two; t9 pins them equal to the
# wrapper's AGY_WEB_TOOLS_ADMIT.
WEB_TOOLS = frozenset({"read_url_content", "search_web"})

_POLICY = "blocked by triad cross-family review policy"
_REPORT_CAP = 40   # denied rows printed by `check` — the digest's list cap
# THE ONE REMEDY for an unhooked attempt and for broken evidence: a fresh hook
# log comes only with a new round, after the round worktree's hooks.json is
# checked.
_REMEDY = "check hooks.json in the round worktree, then prepare a new round"
# WHY A FILE COULD NOT BE READ, named by the ACTUAL reason (gate-1 r20 row
# r20-6). `_read_regular` returns one of these; each follows "<the path> " in
# a refusal.
_WHY_NOT_REGULAR = ("is not a readable regular UTF-8 file: not a regular file "
                    "(a symlink, a FIFO or a directory is refused before it "
                    "is opened)")
_WHY_UNDECODABLE = ("is not a readable regular UTF-8 file: its bytes are not "
                    "valid UTF-8")
_WHY_UNREADABLE = "is not a readable regular UTF-8 file: it could not be read"
# the one CONTENT reason (the file was read): no JSON object with a count
_WHY_NO_TOOL_STEPS = ("carries no readable digest.tool_steps (not a JSON "
                      "document whose digest.tool_steps is a count)")
_USAGE = ("usage: agy_hook.py --log <abs-jsonl> [--web]   (hook mode, stdin = PreToolUse payload)\n"
          "       agy_hook.py check <abs-read-audit.json> <abs-hook-log.jsonl>")


def decide(name, web=False) -> tuple:
    """(decision, reason) for one tool name — the ENTIRE hook policy.
    Non-string / empty names deny (fail-closed): a payload this handler
    cannot read must never let a mutating call through."""
    if not isinstance(name, str) or not name:
        return ("deny", f"{_POLICY}: the tool call carries no readable name")
    if name in ALLOW_TOOLS or (web and name in WEB_TOOLS):
        return ("allow", None)
    return ("deny", f"{_POLICY}: {name[:64]} is outside this leg's allow set "
                    f"— a read-only review leg may not call it")


def _hook_main(log_path: Path, web: bool = False) -> int:
    # BYTES, decoded as UTF-8 with replacement (S2 gate r1, agy A4 — REPRODUCED):
    # a text-mode read under an ASCII stdio encoding (a legacy locale) raised
    # UnicodeDecodeError on a payload carrying a non-ASCII path, and a crashed
    # hook denies every later call, reads included. Only the tool NAME matters.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    except (OSError, AttributeError, ValueError):
        raw = ""
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError):
        # RecursionError: a payload nested past the interpreter's recursion
        # limit is not a ValueError (gate-1 r18 row r18-4) — unreadable, so
        # it denies like any other unreadable payload instead of crashing.
        payload = None
    name = conversation = step = None
    if isinstance(payload, dict):
        call = payload.get("toolCall")
        if isinstance(call, dict):
            name = call.get("name")
        conversation = payload.get("conversationId")
        step = payload.get("stepIdx")
    decision, reason = decide(name, web)
    row = {
        "ts": time.time(),
        "conversation_id": conversation if isinstance(conversation, str) else None,
        "step_idx": step if isinstance(step, int) and not isinstance(step, bool) else None,
        "tool": name if isinstance(name, str) else None,
        "decision": decision,
    }
    if reason is not None:
        row["reason"] = reason
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")
    except OSError as e:
        # availability over bookkeeping: the decision still answers, and the
        # load check will report the missing invocations loudly
        print(f"agy_hook: hook log {log_path} could not be written: {e}",
              file=sys.stderr)
    out = {"decision": decision}
    if reason is not None:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=True))
    return 0


def _count(value) -> bool:
    """True for a non-negative plain int (bools are not counts)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _ids(row) -> list:
    """The row's recorded conversation ids when they are a NON-EMPTY list of
    non-empty strings, else [] (nothing usable to attribute by)."""
    ids = row.get("conversation_ids")
    if (not isinstance(ids, list) or not ids
            or not all(isinstance(i, str) and i for i in ids)):
        return []
    return ids


def _census_rows(digest):
    """The `digest.attempts` census rows of one read audit (one row per agy
    CLI run — `merge_agy_digests` writes them, the driver retries inside one
    wrapper invocation), or a STRING saying why they cannot be attributed.

    ATTRIBUTION NEEDS PER-ATTEMPT IDS (spec case C23). Every row with
    `tool_steps > 0` must carry `conversation_ids` — a non-empty list of
    non-empty strings — or no hook row can be tied to it. So an audit with
    NO `attempts` census (an older wrapper) is not attributable, and neither
    is a stepped row with an empty, absent or malformed id list. A census
    PRESENT but malformed (not a list, empty, or carrying a row without a
    non-negative integer `tool_steps`) is BROKEN EVIDENCE: a wrapper-side
    census bug must never make the check easier to satisfy (case C33).
    Zero-step rows owe no id.
    """
    if not isinstance(digest, dict) or "attempts" not in digest:
        return ("no digest.attempts census (an audit written before the "
                "per-attempt census) — no attempt carries a recorded "
                "conversation id, so no attempt can be attributed to a hook "
                "row")
    rows = digest["attempts"]
    malformed = ("a malformed digest.attempts census (present, but not a list "
                 "of per-run rows each holding a non-negative integer tool_steps)")
    if not isinstance(rows, list) or not rows:
        return malformed
    for row in rows:
        if not isinstance(row, dict) or not _count(row.get("tool_steps")):
            return malformed
        if row["tool_steps"] > 0 and not _ids(row):
            return (f"a digest.attempts row (attempt "
                    f"{repr(row.get('attempt'))[:32]}) that ran "
                    f"{row['tool_steps']} tool step(s) but recorded no "
                    f"conversation id (conversation_ids empty, absent or "
                    f"not a list of non-empty strings) — it cannot be "
                    f"attributed to any hook row")
    return rows


def _read_regular(path: Path) -> tuple:
    """(text, None) for a plain REGULAR UTF-8 file, else (None, why) — `why`
    names the ACTUAL reason (`_WHY_NOT_REGULAR`, `_WHY_UNDECODABLE`,
    `_WHY_UNREADABLE`; gate-1 r20 row r20-6), so every refusal built on it
    says which one fired.

    HARDENED (gate-1 r11 row r11-7): `_audit` read every audit — including
    the SIBLING audits the round check takes as arguments — with
    `path.read_text()`, which FOLLOWS a symlink and BLOCKS FOREVER on a FIFO.
    That is the r10-7 class `collect_v2._read_regular_file` closed one file
    over, reopened here by a new argument. Same shape as
    `verdict_v2._read_regular_file_no_symlink`, spelled LOCALLY because this
    module is the vendor's hook handler and must stay stdlib-only and
    importable on its own: `lstat` decides for every non-regular type BEFORE
    the open (so a FIFO cannot block), `O_NONBLOCK` closes the window where
    one appears in between, `O_NOFOLLOW` covers a symlink swapped in after
    the lstat, and the descriptor's own `fstat` re-checks S_ISREG before a
    byte is read.
    """
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            return (None, _WHY_NOT_REGULAR)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        # ELOOP: a symlink swapped in after the lstat (O_NOFOLLOW refused it)
        return (None, _WHY_NOT_REGULAR if exc.errno == errno.ELOOP
                else _WHY_UNREADABLE)
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return (None, _WHY_NOT_REGULAR)
        chunks = []
        while True:
            block = os.read(fd, 1 << 20)
            if not block:
                break
            chunks.append(block)
    except OSError:
        return (None, _WHY_UNREADABLE)
    finally:
        os.close(fd)
    try:
        return (b"".join(chunks).decode("utf-8"), None)
    except UnicodeDecodeError:
        return (None, _WHY_UNDECODABLE)


def _audit(path: Path) -> tuple:
    """(tool_steps, rows, why) for one read audit; `tool_steps` is None when
    the file carries no readable `digest.tool_steps` — `why` then names the
    ACTUAL reason (the reader's, or `_WHY_NO_TOOL_STEPS` for a file that was
    read; row r20-6) — and `rows` is a STRING when its `attempts` census
    cannot be attributed (`_census_rows`) — the caller decides what each
    means for the leg it belongs to."""
    text, why = _read_regular(path)
    if text is None:
        return (None, None, why)
    try:
        digest = json.loads(text).get("digest")
        tool_steps = digest.get("tool_steps")
    except (ValueError, AttributeError, RecursionError):
        # RecursionError (gate-1 r18 row r18-4): a document nested past the
        # interpreter's recursion limit raises it instead of a ValueError, and
        # it escaped through the collector's in-process retry guard into its
        # `collect` / `retry`, aborting the whole command. It is the same
        # unreadable audit as any other malformed file.
        return (None, None, _WHY_NO_TOOL_STEPS)
    if not _count(tool_steps):
        return (None, None, _WHY_NO_TOOL_STEPS)
    return (tool_steps, _census_rows(digest), None)


def _name(path, row) -> str:
    """One unattributed attempt, named for the guidance: its audit, its
    attempt number, its first recorded conversation id (vendor text — capped
    and ASCII-escaped) and its tool-step count."""
    ids = _ids(row)
    conv = json.dumps(ids[0][:64], ensure_ascii=True) if ids else "none"
    more = f" +{len(ids) - 1} more id(s)" if len(ids) > 1 else ""
    return (f"attempt {repr(row.get('attempt'))[:32]} of {path} (conversation "
            f"{conv}{more}, {row['tool_steps']} tool step(s))")


def check_loaded(read_audit: Path, hook_log: Path) -> tuple:
    """(verdict, exit_code, report_lines, guidance, tool_steps, invocations,
    denied, hooked, must) for ONE attempt — the verdict order is the module
    docstring's. A stepped census row of THIS audit is hooked iff at least
    one hook row carries one of the conversation ids that row recorded; a
    hook row with no conversation id attributes nothing (the measured
    PreToolUse payload always carries `conversationId`, DL-6), and rows under
    ids this audit did not record belong to other attempts."""
    # LEXISTS, NOT `is_file()` (gate-1 r12 row r12-4): only a name that is
    # not there at all is ABSENT; anything present goes to `_audit`, which
    # refuses every non-regular type before the open (INCONCLUSIVE below).
    if not os.path.lexists(read_audit):
        return ("ABSENT", 2, [],
                f"no read audit at {read_audit} — the leg never completed or "
                f"TRIAD_READ_AUDIT_FILE was not set at dispatch; the read-audit "
                f"gate reports the same ABSENT — settle that first", None)
    tool_steps, rows, why = _audit(read_audit)
    if tool_steps is None:
        return ("INCONCLUSIVE", 4, [],
                f"the read audit at {read_audit} {why} — broken evidence, not "
                f"a verdict; {_REMEDY}", None)
    if isinstance(rows, str):
        return ("INCONCLUSIVE", 4, [],
                f"the read audit at {read_audit} carries {rows} — a census "
                f"this check cannot attribute is broken evidence, never a "
                f"verdict; {_REMEDY}", tool_steps)
    must = [row for row in rows if row["tool_steps"] > 0]
    invocations = 0
    denied = []
    named = set()
    # LEXISTS + `_read_regular`: anything present that is not a regular
    # UTF-8 file is broken evidence; a name that is not there at all is a log
    # with zero invocations.
    if os.path.lexists(hook_log):
        text, why = _read_regular(hook_log)
        if text is None:
            return ("INCONCLUSIVE", 4, [],
                    f"the hook log at {hook_log} {why} — broken evidence, not "
                    f"a verdict; {_REMEDY}", tool_steps)
        for idx, line in enumerate(text.split("\n"), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):   # r18-4: over-nested line
                row = None
            # a HOOK row, not any JSON object (S2 gate r1, codex C4): a vendor
            # stream or `{}` handed to this check must never count as proof
            if (not isinstance(row, dict) or row.get("decision") not in ("allow", "deny")
                    or "tool" not in row):
                return ("INCONCLUSIVE", 4, [],
                        f"hook log line {idx} is not a hook row (a JSON object "
                        f"with decision allow|deny and a tool key) — the hook "
                        f"log is broken evidence, not a verdict; {_REMEDY}",
                        tool_steps)
            invocations += 1
            conv = row.get("conversation_id")
            if isinstance(conv, str) and conv:
                named.add(conv)
            if row.get("decision") == "deny":
                denied.append(row)
    # the name came from the vendor payload: capped and ASCII-escaped, one line
    # (S2 gate r2, claude) — a newline or an ANSI sequence in it must not split
    # or repaint the output the leader greps for `HOOK_LOAD_*`
    def _idx(v):
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    report = [f"[hook] denied {json.dumps(str(r.get('tool'))[:64], ensure_ascii=True)} "
              f"(step {_idx(r.get('step_idx'))})"
              for r in denied[:_REPORT_CAP]]
    if len(denied) > _REPORT_CAP:
        # the list is bounded like every vendor-driven list (S2 gate r3, claude)
        report.append(f"[hook] (+{len(denied) - _REPORT_CAP} more)")
    unhooked = [row for row in must if not any(i in named for i in _ids(row))]
    counts = (tool_steps, invocations, len(denied), len(must) - len(unhooked),
              len(must))
    names = "; ".join(_name(read_audit, row) for row in unhooked)
    if invocations == 0 and must:
        steps = sum(row["tool_steps"] for row in must)
        return ("VOID", 3, report,
                f"the enforcement layer did not load: {steps} tool step(s) "
                f"ran across {len(must)} attempt(s) with ZERO hook invocations "
                f"in {hook_log} ({names}). agy's `--agent` fails OPEN "
                f"silently, so this attempt's containment is unproven; "
                f"{_REMEDY}", *counts)
    if invocations == 0:
        return ("INCONCLUSIVE", 4, report,
                "no tool call happened and no hook invocation was logged — "
                "nothing proves or disproves the hook; the read-audit gate "
                "voids a read-blind leg on its own", *counts)
    if unhooked:
        # The step count cannot carry this: a call the vendor rejects at
        # argument validation is a tool step that never reaches the hook
        # (measured 2026-09-17, 4 steps / 3 invocations). An attempt with
        # steps and NO row under any id it recorded had no hook.
        return ("VOID", 3, report,
                f"the hook did not load for {names}: no hook row carries its "
                f"id in {hook_log}. agy's `--agent` fails OPEN silently, so "
                f"this attempt's containment is unproven; {_REMEDY}", *counts)
    return ("PASS", 0, report, None, *counts)


def _check_main(read_audit: Path, hook_log: Path) -> int:
    res = check_loaded(read_audit, hook_log)
    verdict, rc, report, guidance = res[0], res[1], res[2], res[3]
    tool_steps = res[4] if len(res) > 4 and res[4] is not None else "unknown"
    invocations = res[5] if len(res) > 5 else 0
    n_denied = res[6] if len(res) > 6 else 0
    hooked = res[7] if len(res) > 7 else 0
    must = res[8] if len(res) > 8 else 0
    for line in report:
        print(line)
    if guidance:
        print(f"[review] agy hook load check {verdict} — {guidance}", file=sys.stderr)
    # Omit-when-default, the convention the audit row and the run log already
    # follow: the attribution evidence appears exactly where it decides
    # something — more than one census row that must be attributed.
    tail = f" attributed={hooked}/{must}" if must > 1 else ""
    print(f"HOOK_LOAD_{verdict} tool_steps={tool_steps} invocations={invocations} "
          f"denied={n_denied}{tail}")
    return rc


def _abs(arg: str, what: str) -> Path:
    p = Path(arg)
    if not p.is_absolute():
        print(f"agy_hook: {what} must be an absolute path: {arg}\n{_USAGE}",
              file=sys.stderr)
        sys.exit(64)
    return p


def main(argv: list) -> int:
    if len(argv) == 3 and argv[0] == "check":
        return _check_main(_abs(argv[1], "the read audit"),
                           _abs(argv[2], "the hook log"))
    if len(argv) in (2, 3) and argv[0] == "--log" and argv[2:] in ([], ["--web"]):
        return _hook_main(_abs(argv[1], "--log"), web=len(argv) == 3)
    print(_USAGE, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
