#!/usr/bin/env python3
"""agy_hook.py — the agy leg's PreToolUse hook and its LOAD CHECK
(triad-cross-family-review, S2 enforcement — plan
2026-09-16-cfr-delivery-and-enforcement-redesign § Enforcement).

Two modes, one file, python3 stdlib only, no AI:

  hook mode    agy_hook.py --log <abs-jsonl> [--web]
      (--web: a round with review web — a small-path round the owner asked
      web for, or a v2 round whose bound review_web_authorized is true;
      WEB_TOOLS join the allow set, everything else below is unchanged)
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
                                 [<abs-sibling-read-audit.json> ...]
      The LOAD CHECK the redesign owes: `--agent <unknown>` fails OPEN
      silently (measured 2026-09-16 — a bogus agent name yields a fully
      write-capable default and the stream cannot tell), so the round must
      PROVE the hook layer loaded for EVERY agy run in it.
      It is a ROUND check: one worktree carries one `.agents/hooks.json`, so
      every agy leg and every retry appends to ONE log, and the siblings are
      EVERY OTHER attempt audit of the round (superseded attempts included).
      ATTRIBUTION BY CONVERSATION ID (gate-1 r13 row r13-2, spec case C23
      R-BIND / R-CONTAIN — "one leg's hook/audit cannot satisfy another's").
      The wrapper RECORDS each vendor run's conversation ids on its census
      row (`digest.attempts[].conversation_ids`); the hook logs the same id on
      every row it writes (MEASURED 2026-09-26: the stream's `init` and every
      `step_update` carry the id the PreToolUse row carries). Every census row
      with `tool_steps > 0` must have at least one hook row under one of ITS
      OWN ids — an id NO OTHER census row of the round recorded (one owner
      per id, gate-1 r14 row r14-1; an id two rows share attributes neither,
      and decides nothing when no hook row carries it, row r15-3) — all
      attributed is PASS; an equality of steps and rows is NOT
      required (a call the vendor rejects at argument validation never
      reaches the hook — measured 2026-09-17: 4 tool steps, 3 invocations).
      A row with steps and no hook row under its ids is VOID for every agy
      leg of the round, and the check NAMES it (audit, attempt, conversation,
      steps) — it CAN now say which run was unhooked. Zero-step rows impose
      nothing and certify nothing: a run that only called `finish` or had a
      prompt-shaped call denied owns hook rows the census never counts, and
      those rows attribute to that run alone. Nothing to attribute and no
      hook invocation proves nothing — INCONCLUSIVE (the read-audit gate
      voids a read-blind leg on its own).
      What it CANNOT decide, and so reports as INCONCLUSIVE, never a verdict:
      an attempt whose wrapper recorded no usable id (an older audit with no
      `attempts` census, or a stepped row whose `conversation_ids` is empty,
      absent or malformed); an unattributed attempt while the log holds rows
      with no conversation id (they might be its own); an unattributed
      attempt whose only logged id another census row also recorded; ANY
      census row whose id list cannot be shown whole — its writer omitted
      some of its ids at the cap (gate-1 r15 row r15-1) or its transcript was
      incomplete (r16-1) — since a missing id may be another attempt's, so no
      id's single owner can be established and no attempt is attributed. BROKEN
      EVIDENCE is INCONCLUSIVE too: a log line that is not a hook row, a hook
      log or an audit that is unreadable or not a regular file, a malformed
      census, an INCOMPLETE census (rows omitted at the writer's cap,
      `attempts_omitted` > 0 or missing at the cap), a digest carrying
      `refused_attempt` or a zero-step row whose transcript is incomplete
      (`_census_rows`), or a DISPATCHED sibling attempt that wrote no audit
      (`check_loaded`).
      stdout ends with the greppable summary
      `HOOK_LOAD_<VERDICT> tool_steps=<n> invocations=<n> denied=<n>`, plus
      ` attributed=<hooked>/<must>` when more than one census row must be
      attributed; exit 0 PASS / 2 ABSENT (no read audit) / 3 VOID /
      4 INCONCLUSIVE / 64 usage.

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
import re
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
# A round with review web (`--log <file> --web`: the small review path, or a v2
# round binding review_web_authorized true) also allows these two; t9 pins them
# equal to the wrapper's AGY_WEB_TOOLS_ADMIT.
WEB_TOOLS = frozenset({"read_url_content", "search_web"})

_POLICY = "blocked by triad cross-family review policy"
_REPORT_CAP = 40   # denied rows printed by `check` — the digest's list cap
# THE REMEDY FOR AN UNHOOKED RUN IS A NEW ROUND (gate-1 r12 row r12-6). The
# guidance said "re-dispatch once", but the round check attributes EVERY
# attempt and deletes none, so a retry inside the round leaves the unhooked
# attempt in the census and can never clear it.
_NEW_ROUND_WHY = ("a retry inside this round cannot clear the unhooked "
                  "attempt (every attempt is attributed, none is deleted)")
# The same remedy for BROKEN CENSUS / SIBLING evidence (gate-1 r13 row
# r13-6): a retry re-reads every earlier attempt as a sibling and deletes
# none, so it meets the same unattributable census, the same dispatched
# attempt with no audit and the same unreadable file again.
_NEW_ROUND_CENSUS = ("prepare a NEW round (a fresh hook log) — a retry inside "
                     "this round meets the same attempt again (every attempt "
                     "is read as a sibling, none is deleted)")
# The WRITER's per-attempt census cap (`_common._AGY_DIGEST_ATTEMPT_CAP`):
# `merge_agy_digests` keeps this many `attempts` rows and records the rest as
# `attempts_omitted`. Spelled locally because this module stays stdlib-only
# and importable on its own; t9 axis 20 pins the two constants equal.
_ATTEMPT_CENSUS_CAP = 10
# How many unattributed attempts a VOID / INCONCLUSIVE guidance line names;
# the rest are counted. Every name carries vendor text (a conversation id).
# Kept for the unhooked / complete / partial / omitting lists and the list of
# shared ids (gate-1 r16 row r16-7); each listed shared id names every owner
# (gate-1 r15 row r15-4).
_NAME_CAP = 5
# THE EVIDENCE SIZE CAP (gate-1 r19 row r19-2). `_read_regular` accumulated a
# file of any size, then decoded and parsed it, so a misfiled multi-GB file at
# an audit / hook-log / stderr.log name exhausted memory — and a MemoryError is
# no refusal, it aborts the check (and the collector's in-process retry guard)
# instead of failing one piece of evidence. The largest real read audit seen
# is a few KB and a round's hook log a few hundred rows, so 64 MiB is far
# above any genuine file: a larger one is unreadable evidence, refused BEFORE
# it is read (and the read stops at the cap if it grows meanwhile).
# ONE value, spelled in three modules (this one stays stdlib-only):
# `collect_v2._EVIDENCE_MAX_BYTES` and `verdict_v2._EVIDENCE_MAX_BYTES` (gate-1
# r20 row r20-2) — a change touches all three; t11 axis 27 pins them equal.
_EVIDENCE_MAX_BYTES = 64 * 1024 * 1024
_EVIDENCE_CAP_TEXT = "64 MiB"
# WHY A FILE COULD NOT BE READ, named by the ACTUAL reason (gate-1 r20 row
# r20-6). One parenthetical naming the cap used to ride on EVERY unreadable
# refusal, so an operator saw the cap clause on a merely malformed audit and
# a test grepping for it passed with the cap removed. `_read_regular` returns
# one of these; each follows "<the path> " in a refusal.
_WHY_OVERSIZED = (f"exceeds the {_EVIDENCE_CAP_TEXT} evidence cap (refused "
                  f"before a byte is read)")
# the read LOOP's own reason (gate-1 r21 row r21-6): the fstat size was within
# the cap and the file grew past it while being read — bytes WERE read, so
# `_WHY_OVERSIZED`'s "before a byte is read" would be false here
_WHY_OVERSIZED_GREW = (f"grew past the {_EVIDENCE_CAP_TEXT} evidence cap "
                       f"while being read")
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
          "       agy_hook.py check <abs-read-audit.json> <abs-hook-log.jsonl>"
          " [<abs-sibling-read-audit.json> ...]")


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

    ATTRIBUTION NEEDS PER-ATTEMPT IDS (gate-1 r13 row r13-2, spec case C23).
    Every row with `tool_steps > 0` must carry `conversation_ids` — a
    non-empty list of non-empty strings — or no hook row can be tied to it.
    So an audit with NO `attempts` census (an older wrapper) is not
    attributable, and neither is a stepped row with an empty, absent or
    malformed id list. (Until r13 an absent census took a "documented
    minimum" of one run; attribution retires that.)

    A census PRESENT but malformed (not a list, empty, or carrying a row
    without a non-negative integer `tool_steps`) is BROKEN EVIDENCE (gate-1
    r11 row r11-2): a wrapper-side census bug must never make the check
    easier to satisfy (case C33).

    A census can be INCOMPLETE (gate-1 r11 fix-wave disclosure 2). The writer
    keeps only `_ATTEMPT_CENSUS_CAP` rows and records how many it dropped in
    `attempts_omitted`; a run beyond the cap is a run nobody attributes. So a
    positive `attempts_omitted`, a malformed one, or a census AT the cap with
    no omitted count at all (the writer always emits the pair, so that shape
    cannot show it is complete) are refused. Below the cap the writer cannot
    have truncated.

    A ZERO-STEP ROW OWES NOTHING ONLY WHEN THE ZERO IS REAL (gate-1 r12 row
    r12-2). A duplicate-member REFUSAL resets that attempt's events, so its
    row says 0 steps (and records no id) for a run that DID make hooked calls
    (REPRODUCED, probe B); the wrapper stamps `refused_attempt` on exactly
    that digest. And a zero-step row whose transcript is incomplete — the
    ONE predicate `_incomplete` (gate-1 r17 row r17-6): a reader failure, a
    cut tail, a hole, an interrupted run, or a tool step still in flight
    (gate-1 r18 row r18-1) — can have
    lost the steps it made — steps that would owe attribution. Either is
    a census this check cannot attribute; the refusal names the row's own
    markers (gate-1 r19 row r19-5). A row WITH steps and an incompleteness
    marker still owes attribution by the ids it recorded; when that marker
    may have LOST id-bearing events its id list is not whole, so it disables
    exclusive ownership for the round (`_ids_not_whole`, gate-1 r16 row
    r16-1) — an open tool step alone does not (it loses no id, r19-1(d)).
    """
    if isinstance(digest, dict) and digest.get("refused_attempt") not in (None, False):
        return ("a refused_attempt marker (a duplicate-member refusal resets "
                "the refused attempt's events, so its census row is a "
                "SYNTHETIC zero for a run that may have made hooked calls)")
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
        if row["tool_steps"] > 0:
            if not _ids(row):
                return (f"a digest.attempts row (attempt "
                        f"{repr(row.get('attempt'))[:32]}) that ran "
                        f"{row['tool_steps']} tool step(s) but recorded no "
                        f"conversation id (conversation_ids empty, absent or "
                        f"not a list of non-empty strings) — it cannot be "
                        f"attributed to any hook row")
        elif _incomplete(row):
            return (f"a zero-step digest.attempts row (attempt "
                    f"{repr(row.get('attempt'))[:32]}) whose transcript is incomplete "
                    f"({_incomplete_reasons(row)}) — an incomplete transcript "
                    f"can lose the steps that run made, so its zero is not a "
                    f"real zero")
    # ABSENT and NULL are different: the writer never emits a null, so a
    # present non-count (null included) is malformed, not missing.
    if "attempts_omitted" not in digest:
        if len(rows) >= _ATTEMPT_CENSUS_CAP:
            return (f"a digest.attempts census of {len(rows)} row(s) — at the "
                    f"writer's cap of {_ATTEMPT_CENSUS_CAP} — with no "
                    f"attempts_omitted count, so it cannot show it is complete")
    elif not _count(digest["attempts_omitted"]):
        return ("a malformed digest.attempts_omitted count (present, but not a "
                "non-negative integer)")
    elif digest["attempts_omitted"] > 0:
        omitted = digest["attempts_omitted"]
        return (f"an INCOMPLETE digest.attempts census — {omitted} attempt "
                f"row(s) beyond the writer's cap of {_ATTEMPT_CENSUS_CAP} were "
                f"omitted, so those runs cannot be attributed")
    return rows


def _read_regular(path: Path) -> tuple:
    """(text, None) for a plain REGULAR UTF-8 file within the cap, else
    (None, why) — `why` names the ACTUAL reason (`_WHY_OVERSIZED`,
    `_WHY_OVERSIZED_GREW`, `_WHY_NOT_REGULAR`, `_WHY_UNDECODABLE`,
    `_WHY_UNREADABLE`; gate-1 r20 row r20-6, r21 row r21-6), so every
    refusal built on it says which one fired.

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
    byte is read. BOUNDED (gate-1 r19 row r19-2): a file whose size exceeds
    `_EVIDENCE_MAX_BYTES` is refused on that `fstat`, before a byte is read,
    and the read loop stops at the cap should the file grow meanwhile (its
    own reason, `_WHY_OVERSIZED_GREW`).
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
        if fst.st_size > _EVIDENCE_MAX_BYTES:
            return (None, _WHY_OVERSIZED)
        chunks = []
        total = 0
        while True:
            block = os.read(fd, 1 << 20)
            if not block:
                break
            total += len(block)
            if total > _EVIDENCE_MAX_BYTES:
                return (None, _WHY_OVERSIZED_GREW)
            chunks.append(block)
    except OSError:
        return (None, _WHY_UNREADABLE)
    finally:
        os.close(fd)
    try:
        return (b"".join(chunks).decode("utf-8"), None)
    except UnicodeDecodeError:
        return (None, _WHY_UNDECODABLE)


# The engine's SPAWN line: `_common._run_once` logs `exec cwd=… timeout=…
# argv=[…]` through `log()` (a `[<timestamp>] ` prefix) BEFORE Popen, and no
# pre-spawn refusal path reaches it (gate-1 r13 row r13-1).
_SPAWN_LINE = re.compile(r"^\[[^\]\n]*\] exec ", re.MULTILINE)


def _spawned(stderr_log: Path) -> tuple:
    """(spawned, why) for a sibling attempt that wrote no read audit:
    (False, None) when the attempt never spawned agy (no `stderr.log`, or a
    readable one with no spawn line), (True, None) when it did, and
    (None, why) when `stderr.log` is present but cannot be read — `why` is
    `_read_regular`'s actual reason (row r20-6); dispatched or not is
    unknown."""
    if not os.path.lexists(stderr_log):
        return (False, None)
    text, why = _read_regular(stderr_log)
    if text is None:
        return (None, why)
    return (_SPAWN_LINE.search(text) is not None, None)


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


def _names(items, fmt=None, cap=_NAME_CAP) -> str:
    """The census rows `items` named for a guidance line; `cap=None` names
    every one (the shared-id owner list, gate-1 r15 row r15-4)."""
    fmt = fmt or _name
    shown = items if cap is None else items[:cap]
    named = "; ".join(fmt(p, r) for p, r in shown)
    rest = len(items) - len(shown)
    return named + (f"; (+{rest} more)" if rest > 0 else "")


def _omits(row) -> bool:
    """True when the writer omitted some of this row's conversation ids.
    Only an ABSENT key or a plain integer 0 says "none omitted" — any other
    value (a positive count, or a present non-count) is read as omitting
    (fail-closed: a malformed count cannot show the id list is whole)."""
    v = row.get("conversation_ids_omitted", 0)
    return not (_count(v) and v == 0)


def _shown(v) -> str:
    """A writer-stamped marker value for a guidance line: capped and
    ASCII-escaped like every value this check prints."""
    text = v if isinstance(v, str) else repr(v)
    return json.dumps(text[:32], ensure_ascii=True)[1:-1]


# THE INCOMPLETENESS MARKERS, SPELLED ONCE (gate-1 r18 row r18-3): (key, test
# on the row's PRESENT value, per-row label, loses ids). `_incomplete`,
# `_loses_ids` and the per-row reasons are all derived from this table, so the
# decision and the operator text cannot drift apart (the r16-5 / r17-6 shape;
# the generic list the zero-step refusal printed is gone — it names the row's
# own markers, gate-1 r19 row r19-5). An ABSENT
# key is never a marker. `capture_complete` is read as incomplete only when it
# is exactly False (a present non-boolean is not). `steps_open` is a marker
# unless it is a plain int 0: a present value that is not a non-negative
# plain int (a bool, a string, a float, a negative, null) is read FAIL-CLOSED
# as a marker, like `_omits` reads a present non-count (gate-1 r19 row r19-6
# — the writer never emits one).
# LOSES IDS (gate-1 r19 row r19-1(d)): whether the marker means "id-bearing
# events may have been LOST" — a reader failure, a cut tail, a hole, an
# interrupted run. NOT `steps_open`: the writer records the conversation id of
# EVERY step_update, the ACTIVE one included, so an open step loses no id; it
# only means "this row's zero is not a real zero" (the zero-step refusal).
_INCOMPLETE_TABLE = (
    ("capture_complete", lambda v: v is False,
     lambda v: "capture_complete false", True),
    ("truncated_tail", bool, lambda v: "truncated_tail", True),
    ("undecodable_lines", bool, lambda v: "undecodable_lines", True),
    ("interrupted", bool, lambda v: f"interrupted ({_shown(v)})", True),
    ("steps_open", lambda v: not (_count(v) and v == 0),
     lambda v: f"a tool step still in flight (steps_open {_shown(v)})",
     False),
)


def _incomplete_reasons(row, losing_only: bool = False) -> str:
    """The incompleteness markers one row carries, named for the guidance —
    derived from `_INCOMPLETE_TABLE`, the same entries `_incomplete` decides
    on (`losing_only`: only the id-losing ones `_loses_ids` decides on).
    Empty when the row carries none."""
    return " / ".join(label(row[key])
                      for key, test, label, loses in _INCOMPLETE_TABLE
                      if key in row and test(row[key])
                      and (loses or not losing_only))


def _incomplete(row) -> bool:
    """THE ONE MARKER PREDICATE "this row's TRANSCRIPT is incomplete" (gate-1
    r17 rows r17-1 / r17-6, r18 rows r18-1 / r18-3): `capture_complete` false
    (a reader failed), `truncated_tail` (cut mid-line), `undecodable_lines` (a
    hole), `interrupted` (the wrapper killed the run at its deadline, or it
    died on a signal — a KNOWN PREFIX even when it ends on a line boundary and
    carries no other marker; spec case C1's terminal record), or `steps_open`
    (a tool step went ACTIVE and never reached its terminal update: the run
    exited on its own mid-call and that step is counted nowhere, so a zero is
    not a real zero). `_census_rows`' zero-step refusal reads it; the markers
    themselves live in ONE table (`_INCOMPLETE_TABLE`), so this is exactly
    "the row has a reason". The id-ownership rule reads the narrower
    `_loses_ids` (gate-1 r19 row r19-1(d)).

    A MISSING RESULT EVENT IS NOT A MARKER (leader decision on wave 17): a run
    the VENDOR ended (oauth-env, capacity, extraction-error, a crash after
    steps) with a complete capture, no cut tail, no hole and no step in flight
    lost nothing — every event the child emitted was drained — so neither its
    zero nor its id list is in doubt whatever `result_events` says. An audit
    written before the `interrupted` / `steps_open` stamps existed carries no
    marker for such a run; a NEW round's audits are all written by the
    current wrapper, so that residual is disclosed in the gate ledger, not
    coded."""
    return bool(_incomplete_reasons(row))


def _loses_ids(row) -> bool:
    """True when the row carries a marker meaning "id-bearing events may have
    been LOST" — the `_INCOMPLETE_TABLE` entries whose "loses ids" column is
    True (every marker but `steps_open`, gate-1 r19 row r19-1(d))."""
    return bool(_incomplete_reasons(row, losing_only=True))


def _ids_not_whole(row) -> bool:
    """THE ONE PREDICATE "this row's recorded id list cannot be shown whole"
    (gate-1 r16 rows r16-1 / r16-5), whatever the row's `tool_steps`: its
    writer omitted ids (`_omits`), or its transcript carries a marker that
    may have LOST id-bearing events (`_loses_ids`). It decides BOTH the
    ownership rule (any such row disables exclusive ownership) and the
    partial / complete split of the unattributed rows — two predicates for
    one fact read a present non-count (`false`, `0.0`) as omitting in one
    place and as "none omitted" in the other. An open tool step
    (`steps_open`) is NOT such a marker: the writer records the id of every
    step_update, the ACTIVE one included, so the wave-18 reading made every
    stepped run that exits mid-call blind the round for a loss that cannot
    happen (gate-1 r19 row r19-1(d))."""
    return _omits(row) or _loses_ids(row)


def _omit_name(path, row) -> str:
    """One census row whose id list is not whole, named for the guidance
    with every reason it carries."""
    text = ""
    if _omits(row):
        v = row.get("conversation_ids_omitted")
        n = v if _count(v) else f"an unreadable count ({repr(v)[:16]}) of"
        text = f" omitted {n} conversation id(s) at the writer's cap"
    if _loses_ids(row):
        text += (f"{', and its' if text else ', whose'} transcript was "
                 f"incomplete ({_incomplete_reasons(row, losing_only=True)}), "
                 f"so id-bearing events may be lost")
    return f"attempt {repr(row.get('attempt'))[:32]} of {path}{text}"


def check_loaded(read_audit: Path, hook_log: Path, siblings=()) -> tuple:
    """(verdict, exit_code, report_lines, guidance, tool_steps, invocations,
    denied, hooked, must) — see the module docstring.

    `siblings` are the OTHER agy read audits of the SAME round — every
    ATTEMPT of every agy-route entry, superseded attempts included, because
    their conversations are in the shared log (`collect_v2.
    _agy_round_audits` is the producer). The round worktree carries exactly
    one `.agents/hooks.json`, so every agy leg and every retry appends to the
    same log; passing them makes this a ROUND check.

    THE ATTRIBUTION RULE, stated once (gate-1 r13 row r13-2, spec case C23).
    The census rows in scope are the `attempts` rows of the primary audit and
    of every readable sibling. Each row with `tool_steps > 0` MUST be
    attributed: it is HOOKED iff at least one hook row carries one of the
    conversation ids that row recorded AND that id is recorded by NO OTHER
    census row (gate-1 r14 row r14-1 — ownership is counted over every row,
    zero-step rows included; an id with two owners cannot tell two runs
    apart and attributes neither). Rows with zero steps impose nothing and
    certify nothing. Hook rows with no `conversation_id` attribute to NO
    attempt. Named log ids no census row recorded are an unverified id
    premise: reported on every non-PASS guidance line, never a verdict.
    OMITTED OR LOST IDS DEFEAT OWNERSHIP (gate-1 r15 row r15-1, r16 row
    r16-1): `owners` holds only RETAINED ids, and an id a writer omitted at
    the cap — or an id-bearing event an incomplete transcript lost — may be
    another row's, so while ANY census row (primary or sibling, stepped or
    zero-step) fails `_ids_not_whole`, no stepped row is provably attributed
    (`attributed=0/<must>`). So:
      * every row that must be attributed is hooked and every census row's
        id list is whole -> PASS (however many anonymous rows, zero-step rows or
        leftover conversations ride along);
      * zero hook invocations while any row must be attributed -> VOID;
      * an unhooked row while the log holds anonymous rows -> INCONCLUSIVE
        (they might be its own);
      * otherwise any PROVEN-unhooked row (complete ids, none of them in the
        log — a shared id with no hook row decides nothing, gate-1 r15 row
        r15-3) -> VOID, NAMING the attempt: the check CAN distinguish which
        run was unhooked; undecidable rows beside it are mentioned (gate-1
        r14 row r14-2). The round still falls together — one hooks.json that
        did not load for one run is unproven for all;
      * otherwise an unhooked row holding a LOGGED id another census row also
        recorded -> INCONCLUSIVE naming every owner of every such id (its
        rows might be either's; row r15-4);
      * otherwise -> INCONCLUSIVE naming every row whose id list is not
        whole (the rule above; an unhooked row whose own id list is not
        whole folds into it — the same predicate decides partial vs
        complete, r16-5).
    What it CANNOT decide is an attempt whose wrapper recorded no id: that
    census is INCONCLUSIVE before the log is read (`_census_rows`).
    This retires the r11-r13 COUNT (distinct ids against the runs the census
    accounts for) and r11-3's single-run rule ("any row proves THE run"):
    a count attributes nothing, and the census (`step_type == "tool"` steps)
    and the hook (every call, `finish` and prompt-shaped calls included) see
    different call sets.
    """
    # LEXISTS, NOT `is_file()` (gate-1 r12 row r12-4) — the rule the siblings
    # and the hook log already follow. `is_file()` is False for a dangling
    # symlink, a directory and a FIFO alike, so a non-regular primary read as
    # "no read audit" with the wrong remediation. Only a name that is not
    # there at all is ABSENT; anything present goes to `_audit`, which
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
                f"a verdict; {_NEW_ROUND_CENSUS}", None)
    if isinstance(rows, str):
        return ("INCONCLUSIVE", 4, [],
                f"the read audit at {read_audit} carries {rows} — a census "
                f"this check cannot attribute is broken evidence, never a "
                f"verdict; {_NEW_ROUND_CENSUS}", tool_steps)
    census = [(read_audit, row) for row in rows]
    for sibling in siblings:
        # A sibling that exists but cannot be read leaves the round's census
        # unknown, and an unknown census is broken evidence, never a verdict.
        #
        # LEXISTS, NOT `is_file()` (gate-1 r11 row r11-7). `is_file()` is
        # False for a FIFO, a directory and a dangling symlink alike, so a
        # non-regular path planted at a sibling audit name took the ABSENT
        # branch and SILENTLY REMOVED that attempt from the round. Only a
        # name that is not there at all is skipped; anything present is
        # handed to `_audit`, which refuses every non-regular type BY NAME.
        #
        # AN ABSENT AUDIT IS NOT "NOTHING RAN" WHEN THE ATTEMPT WAS
        # DISPATCHED (gate-1 r12 row r12-1). The collector evaluates only the
        # RECORDED attempt, so nothing else reports a superseded attempt as
        # ABSENT. The wrapper writes the audit best-effort at the END of its
        # run, so an attempt signalled or killed before that write leaves its
        # conversation in the shared log and no audit — a run nobody can
        # attribute (REPRODUCED, probe A). The attempt directory says which it
        # was: the printed dispatch's `2>` redirect creates `stderr.log`
        # there. Dispatched with no audit is an UNKNOWN census; an allocation
        # that was never dispatched, or a directory that does not exist at
        # all, ran nothing — its entry's result is missing, which makes the
        # round INCOMPLETE on its own — and is still skipped.
        #
        # THE MARKER IS THE ENGINE'S SPAWN EVIDENCE (gate-1 r13 row r13-1).
        # The shell creates `stderr.log` for EVERY dispatch, including one
        # the wrapper refused BEFORE agy was spawned (config-conflict,
        # version floors, argument errors): those return with no read audit
        # and ran nothing, and bare presence made every such round
        # INCONCLUSIVE, unrecoverable by retry. `_common._run_once` logs a
        # timestamped `exec ` line BEFORE Popen, so a readable `stderr.log`
        # holding one = spawned (unknown census); holding none = never
        # spawned (skipped); unreadable = which of the two is unknown.
        if not os.path.lexists(sibling):
            spawned, why = _spawned(Path(os.path.dirname(sibling))
                                    / "stderr.log")
            if spawned is None:
                return ("INCONCLUSIVE", 4, [],
                        f"the sibling attempt at {sibling} wrote no read "
                        f"audit and its stderr.log at "
                        f"{os.path.join(os.path.dirname(sibling), 'stderr.log')} "
                        f"{why} — whether it "
                        f"was dispatched or not is unknown, so the round's "
                        f"census is unknown and no agy leg of this round "
                        f"can be certified; {_NEW_ROUND_CENSUS}", tool_steps)
            if spawned:
                return ("INCONCLUSIVE", 4, [],
                        f"the sibling attempt at {sibling} was DISPATCHED "
                        f"(its stderr.log carries the engine's spawn line) "
                        f"but wrote no read audit — a dispatched attempt "
                        f"with no read audit recorded no conversation id "
                        f"its run could be attributed by, and its "
                        f"conversation may be in the log, so no agy leg "
                        f"of this round can be certified; {_NEW_ROUND_CENSUS}",
                        tool_steps)
            continue
        sib_steps, sib_rows, why = _audit(sibling)
        if sib_steps is None:
            return ("INCONCLUSIVE", 4, [],
                    f"the sibling read audit at {sibling} {why} — the round's "
                    f"census is unknown, so no agy leg of this round can be "
                    f"certified; {_NEW_ROUND_CENSUS}", tool_steps)
        if isinstance(sib_rows, str):
            return ("INCONCLUSIVE", 4, [],
                    f"the sibling read audit at {sibling} carries {sib_rows} "
                    f"— no agy leg of this round can be certified (a census "
                    f"this check cannot attribute is never a verdict); "
                    f"{_NEW_ROUND_CENSUS}", tool_steps)
        census.extend((sibling, row) for row in sib_rows)
    must = [(path, row) for path, row in census if row["tool_steps"] > 0]
    # ONE OWNER PER ID (gate-1 r14 row r14-1, spec case C23). Attribution by
    # id assumes an id names exactly one run; nothing checked that, so two
    # attempts recording the same id were both certified by one attempt's
    # rows. Ownership is built over EVERY census row — zero-step rows
    # included, because a zero-step owner sharing the id would otherwise
    # certify a stepped one. An id with more than one owner is AMBIGUOUS: it
    # cannot tell two runs apart, so it attributes neither.
    owners: dict = {}
    for path, row in census:
        for i in dict.fromkeys(_ids(row)):
            owners.setdefault(i, []).append((path, row))
    invocations = 0
    denied = []
    named: dict = {}
    anonymous = 0
    # LEXISTS + `_read_regular` (gate-1 r11 fix-wave disclosure 3): the log
    # used to be guarded by `exists()` and read with `read_text()` — a FIFO
    # blocked forever, a symlink was followed, and a DANGLING link read as
    # "no log" and VOIDed. Anything present that is not a regular UTF-8 file
    # is broken evidence; a name that is not there at all keeps its meaning.
    if os.path.lexists(hook_log):
        text, why = _read_regular(hook_log)
        if text is None:
            return ("INCONCLUSIVE", 4, [],
                    f"the hook log at {hook_log} {why} — broken evidence, not "
                    f"a verdict; {_NEW_ROUND_CENSUS}",
                    tool_steps)
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
                        f"log is broken evidence, not a verdict; "
                        f"{_NEW_ROUND_CENSUS}", tool_steps)
            invocations += 1
            conv = row.get("conversation_id")
            if isinstance(conv, str) and conv:
                named[conv] = named.get(conv, 0) + 1
            else:
                anonymous += 1
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
    # a stepped row is HOOKED only by an UNAMBIGUOUS id present in the log
    unhooked = [(path, row) for path, row in must
                if not any(i in named and len(owners[i]) == 1
                           for i in _ids(row))]
    # Named log ids no census row recorded: the premise that every hooked run
    # recorded its id is unverified for them. Never a verdict by itself (the
    # verdict is decided by the rows that must be attributed); every non-PASS
    # guidance line reports it.
    unrecorded = sum(1 for i in named if i not in owners)
    # OMITTED IDS DEFEAT EXCLUSIVE OWNERSHIP (gate-1 r15 row r15-1). `owners`
    # holds RETAINED ids only; a row whose writer omitted ids at the cap may
    # have omitted an id another row recorded, so that other row only LOOKS
    # single-owned. While ANY census row — primary or sibling, stepped or
    # zero-step — omitted ids, no id's single owner can be established, so
    # no stepped row is provably attributed (counted 0 below) and the round
    # cannot PASS.
    # INCOMPLETE TRANSCRIPTS DEFEAT IT THE SAME WAY (gate-1 r16 row r16-1): a
    # cut or undecodable transcript may have lost id-bearing events, so its
    # retained ids cannot be shown whole either — ONE predicate,
    # `_ids_not_whole`, covers both.
    omitting = [(p, r) for p, r in census if _ids_not_whole(r)]
    blind = bool(omitting and must)

    def _note(guidance: str) -> str:
        if not unrecorded:
            return guidance
        return (f"{guidance}; unverified id premise: {unrecorded} named "
                f"conversation(s) in the log belong to no recorded attempt")
    counts = (tool_steps, invocations, len(denied),
              0 if blind else len(must) - len(unhooked), len(must))
    if invocations == 0 and must:
        steps = sum(row["tool_steps"] for _p, row in must)
        return ("VOID", 3, report, _note(
                f"the enforcement layer did not load: {steps} tool step(s) "
                f"ran across {len(must)} attempt(s) with ZERO hook invocations "
                f"in {hook_log} ({_names(must)}). agy's `--agent` fails OPEN "
                f"silently, so this round's agy containment is unproven — "
                f"treat every agy leg of the round as INVALID; check "
                f"<worktree>/.agents/hooks.json, then prepare a NEW round "
                f"(a fresh hook log) — {_NEW_ROUND_WHY}"), *counts)
    if invocations == 0:
        return ("INCONCLUSIVE", 4, report, _note(
                "no tool call happened and no hook invocation was logged — "
                "nothing proves or disproves the hook; the read-audit gate "
                "voids a read-blind leg on its own"), *counts)
    if not unhooked and not blind:
        return ("PASS", 0, report, None, *counts)
    if unhooked and anonymous:
        # AN ANONYMOUS ROW ATTRIBUTES TO NO ATTEMPT (gate-1 r11 rows r11-3 /
        # r11-4, re-derived at r13-2). It proves a hook FIRED but not in
        # WHOSE run, so it might be the unattributed attempt's own row: the
        # attempt is neither proven hooked nor proven unhooked.
        return ("INCONCLUSIVE", 4, report, _note(
                f"the hook logged {anonymous} row(s) with no conversation id "
                f"in {hook_log}, so whether {_names(unhooked)} hooked cannot "
                f"be told — an anonymous row proves a hook fired but not in "
                f"which run; inspect <worktree>/.agents/hooks.json and the "
                f"vendor's payload, then prepare a NEW round (a fresh hook "
                f"log) — {_NEW_ROUND_WHY}"), *counts)
    # THREE KINDS OF UNATTRIBUTED ROW (gate-1 r14 rows r14-1 / r14-2):
    #   ambiguous — holds an id another census row also recorded AND that id
    #               IS in the log, so the rows under it may be its own or the
    #               other owner's (gate-1 r15 row r15-3: a shared id with no
    #               hook row decides nothing — a row whose ids are all absent
    #               from the log is complete, shared or not);
    #   partial   — its id list is not whole (`_ids_not_whole`: its writer
    #               omitted some of its ids, or its transcript was
    #               incomplete), and a missing id might be the one the hook
    #               logged;
    #   complete  — neither: no hook row carries any id it recorded, which
    #               PROVES it unhooked. Decided by the SAME predicate as the
    #               ownership rule (gate-1 r16 row r16-5).
    # A proven-unhooked row decides the round (VOID, naming it) whatever the
    # undecidable ones are; they are mentioned beside it. INCONCLUSIVE only
    # when every unattributed row is undecidable.
    def _shared_logged(row) -> bool:
        return any(i in named and len(owners[i]) > 1 for i in _ids(row))
    ambiguous = [(p, r) for p, r in unhooked if _shared_logged(r)]
    rest = [(p, r) for p, r in unhooked if not _shared_logged(r)]
    partial = [(p, r) for p, r in rest if _ids_not_whole(r)]
    complete = [(p, r) for p, r in rest if not _ids_not_whole(r)]
    if complete:
        # The step count cannot carry this: a call the vendor rejects at
        # argument validation is a tool step that never reaches the hook
        # (measured 2026-09-17, 4 steps / 3 invocations), so "fewer rows than
        # steps" proves nothing. An attempt with steps and NO row under any id
        # it recorded had no hook.
        also = ""
        if partial:
            also += (f" Additionally undecidable: "
                     f"{_names(partial, _omit_name)} (its id list cannot be "
                     f"shown whole).")
        if ambiguous:
            also += (f" Additionally undecidable: {_names(ambiguous)} (it "
                     f"shares a recorded id with another census row).")
        return ("VOID", 3, report, _note(
                f"the hook did not load for {_names(complete)}: no hook row "
                f"carries its id in {hook_log}. agy's `--agent` fails OPEN "
                f"silently and the round shares ONE hooks.json, so every agy "
                f"leg of this round is unproven and none may be admitted on "
                f"another attempt's rows;{also} check "
                f"<worktree>/.agents/hooks.json, then prepare a NEW round (a "
                f"fresh hook log) — {_NEW_ROUND_WHY}"), *counts)
    if ambiguous:
        # Named with every owner of each shared id.
        shared = list(dict.fromkeys(i for _p, r in ambiguous for i in _ids(r)
                                    if i in named and len(owners[i]) > 1))
        # EVERY owner of each listed id (gate-1 r15 row r15-4): census rows
        # are host-written and bounded by the writer's attempt cap times the
        # round's audits, not vendor-driven, so the owner list is bounded
        # without `_NAME_CAP`. WHICH ids are shared IS vendor-driven (up to
        # the writer's id cap per row), so that list keeps `_NAME_CAP` and a
        # counted tail (gate-1 r16 row r16-7).
        which = "; ".join(
            f"conversation {json.dumps(i[:64], ensure_ascii=True)} is "
            f"recorded by {len(owners[i])} census rows "
            f"({_names(owners[i], cap=None)})"
            for i in shared[:_NAME_CAP])
        more = (f"; (+{len(shared) - _NAME_CAP} more shared id(s))"
                if len(shared) > _NAME_CAP else "")
        also = (f" Additionally undecidable: {_names(partial, _omit_name)} "
                f"(its id list cannot be shown whole)." if partial else "")
        return ("INCONCLUSIVE", 4, report, _note(
                f"{_names(ambiguous)} cannot be attributed: {which}{more} — "
                f"an id that cannot tell two runs apart attributes neither, "
                f"so no agy leg of this round can be certified;{also} "
                f"{_NEW_ROUND_CENSUS}"), *counts)
    # THE NOT-WHOLE RULE (gate-1 r15 row r15-1, r16 row r16-1): every
    # unattributed row is partial, or none is unattributed but some census
    # row's id list is not whole. The former partial-only arm folds into it.
    unowned = (f" (no hook row carries a recorded id of {_names(partial)})"
               if partial else "")
    return ("INCONCLUSIVE", 4, report, _note(
            f"{_names(omitting, _omit_name)}{unowned}; an omitted or lost id "
            f"may be another attempt's, so exclusive ownership cannot be "
            f"established for any id — no agy leg of this round can be "
            f"certified (conversation_ids_omitted / incomplete transcript); "
            f"{_NEW_ROUND_CENSUS}"),
            *counts)

def _check_main(read_audit: Path, hook_log: Path, siblings=()) -> int:
    res = check_loaded(read_audit, hook_log, siblings)
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
    if len(argv) >= 3 and argv[0] == "check":
        return _check_main(_abs(argv[1], "the read audit"),
                           _abs(argv[2], "the hook log"),
                           [_abs(a, "a sibling read audit") for a in argv[3:]])
    if len(argv) in (2, 3) and argv[0] == "--log" and argv[2:] in ([], ["--web"]):
        return _hook_main(_abs(argv[1], "--log"), web=len(argv) == 3)
    print(_USAGE, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
