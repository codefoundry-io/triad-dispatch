#!/usr/bin/env python3
"""collect_v2.py — the ALL-ENTRY v2 collector and the diagnosed retry
allocation, host A side (plan `2026-09-21-host-a-v2-implementation`, S5).

It reads the round record `<packet-dir>/.roster-r<N>.json` that
`review_scratch.py prepare --v2` wrote, takes each enabled non-skipped
entry's RECORDED attempt (the one that record names — row r10-2), and folds
the whole roster into ONE outcome.

What "counts" (PRD § Agreement, correction and retry; `reference/review-rules.md`
R-AGREE):
  * EVERY enabled participating entry counts, informational entries INCLUDED.
    `acceptance` is operator DATA (R-ROSTER, owner Q-O): nothing here derives
    a rule from it, so an informational entry's Critical blocks exactly like a
    required entry's. There is no majority vote.
  * AGREED only when the selected roster is nonempty and EVERY selected
    enabled entry explicitly returned SAFE TO MERGE on the current basis.
  * A missing, invalid or failed result is NOT agreement (INCOMPLETE).
  * Any verdict other than SAFE TO MERGE, a Critical / must-fix finding, or an
    unresolved OPEN QUESTION blocks (BLOCKED). A Minor-only NEGATIVE verdict
    ("MERGE WITH FIXES" or "DO NOT MERGE" with zero blocking findings and zero
    open questions) is schema-valid but NOT agreement; its verdict is kept and
    recorded as a verdict-selection DEVIATION.
  * Family coverage is reported SEPARATELY from the entry tally and is
    descriptive, never a threshold: a one-leg or one-family roster has no
    family minimum (R-AGREE, R-ROSTER).
  * Repetition changes nothing: a stalled, quota-stopped or exception-released
    round stays BLOCKED or INCOMPLETE until a later round on its own current
    basis satisfies the rule above (R-STOP).
  * A leg/attempt's own evidence decides it: a sibling's evidence, even from
    the same family or model, can never satisfy an entry. On an agy route the
    per-attempt READ-AUDIT GATE and the HOOK LOAD CHECK are part of the
    result, not optional extras — an ungated agy answer is UNVERIFIED, and
    `--agent` fails OPEN silently, so a leg whose hook layer cannot be proven
    loaded is invalid.
  * A recorded attempt is sealed (R-BIND, case C66): `seal.json` beside it
    binds the digests of its result, receipt and read evidence and the
    state they were recorded in. The native route's admission
    (`verdict_v2 --admit … --admitted-out`) writes it; on a wrapper route
    the first collection that judges an answer — valid or not — writes it,
    over the bytes it judged. The collection record keeps every seal digest,
    so a later change, removal or replacement of a sealed file or of the
    seal itself is an integrity failure (INVALID, so never AGREED). A retry
    of an attempt sealed as valid is refused (one sealed as an inadmissible
    answer stays retryable), and the recorded attempt is evaluated — and
    retried — only behind earlier attempts that failed to run and were
    diagnosed by `retry`. `retry` RECORDS the attempt it replaces: it seals
    it `failed-to-run` over what it holds then, so a later write into it is
    an integrity failure too.

`AGREED` is this collector's outcome. It does not itself satisfy a project
formal gate or authorise merge, installation or release.

Retry (R-RETRY, owner Q-C): only an entry that did NOT return a valid verdict
may retry on the UNCHANGED basis, after a written diagnosis. A valid negative
review is completed work, not a transport failure — correcting what it found
changes the reviewed content, which is a NEW ROUND (R-REREVIEW). A retry
allocates attempt K+1 and never deletes, rewrites or reopens attempt K; the
prompt is re-rendered from the round's OWN frozen roster entry with the new
attempt number, so nothing but the attempt changes.

CLI:
    python3 collect_v2.py collect <abs-packet-dir> r<N>
    python3 collect_v2.py retry   <abs-packet-dir> r<N> <name> --diagnosis TEXT
(`review_scratch.py collect|retry` is the same code through the lifecycle
command every other round operation already goes through.)

Exit codes:
    0   AGREED
    2   refusal — no/unreadable round record, a record whose selection or
        configuration differs from the round's bound basis, unknown or
        non-dispatched entry, an empty diagnosis, or a retry on a completed
        review
    4   BLOCKED                  a valid entry's verdict is not SAFE TO MERGE,
                                 or it has a blocking finding or an open
                                 question
    5   INCOMPLETE               some entry is missing or invalid
   64   usage

Stdlib only. The v2 siblings (`verdict_v2`, and `review_scratch` for the
attempt allocation a retry reuses) are loaded BY PATH from this file's own
directory: they use `from __future__ import annotations`, so each module is
registered in `sys.modules` BEFORE `exec_module` — `dataclasses` resolves
their field annotations through `sys.modules[cls.__module__]`.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

EXIT_AGREED = 0
EXIT_REFUSE = 2
EXIT_BLOCKED = 4
EXIT_INCOMPLETE = 5
EXIT_USAGE = 64

OUTCOME_EXIT = {
    "AGREED": EXIT_AGREED,
    "BLOCKED": EXIT_BLOCKED,
    "INCOMPLETE": EXIT_INCOMPLETE,
}
SAFE_VERDICT = "SAFE TO MERGE"
LIB_DIR = Path(__file__).resolve().parent
# THE CUSTODY LINE, AS THE PRODUCER WRITES IT (row r11-6). The agy wrapper
# emits `read-audit-file: <abs path>` through `_common.log`, which prefixes
# every line with `[<ISO-8601 timestamp>] `. Those two are the whole
# tolerance: the prefix is stripped and the REST of the line must equal the
# marker plus the audit path's filesystem bytes, PERCENT-ESCAPED (below).
_CUSTODY_MARKER = b"read-audit-file: "
_LOG_PREFIX = re.compile(rb"^\[[^\]]*\] ")
# THE VALUE IS PERCENT-ESCAPED FILESYSTEM BYTES (gate-1 r13 row r13-5): the
# wrapper emits `_common._summary_field(<path>)`, so this side compares the
# SAME encoding. Re-implemented here because this module may not import
# `_common`; t15 axis 66 pins the safe set and the output equal to it.
_CUSTODY_FIELD_SAFE = "/._-~+=@,:"


def _custody_field(raw: bytes) -> bytes:
    """`_common._summary_field` over filesystem bytes, as ASCII bytes."""
    return urllib.parse.quote(raw, safe=_CUSTODY_FIELD_SAFE).encode("ascii")
# The invocation members an adopted `dispatch.json` must EQUAL in the
# dispatch the round's OWN frozen roster entry re-renders (row r7-x4,
# completed by r8 row r8-2).
#
# `kind` AND `native` ARE PART OF THE INVOCATION. r7-x4 compared the six
# WRAPPER members only, so the two that decide WHO RUNS on the native route
# were never read: a planted orphan record could substitute the reviewer
# (`native.subagent_type`) or flip a wrapper record to a native spawn while
# every compared member still matched — a native record carries `argv: null`
# and `env: {}`, and the wrapper's own argv is simply not read on that route.
# Comparing the WHOLE `native` block also states the wrapper case: the writer
# emits `native: null` there, so any block at all differs from the render.
_ADOPT_COMPARED_FIELDS = ("kind", "native", "argv", "env", "stdout_path",
                          "stderr_path", "read_audit_path", "schema_file")
# The exit BOTH agy evidence tools reserve for "this invocation could not RUN
# at all" (`read_audit_gate.sh` usage, `agy_hook.py check` usage). It is the
# same 64 `verdict_v2` uses for a host fault, and it is treated the same way
# here (row r8-9).
_EVIDENCE_TOOL_HOST_RC = 64
# The launch switch each WRAPPER route carries for a true review-web
# condition (R-REVIEW-WEB, case C32), keyed by the binding's route (None =
# codex, the one family with one route). `roster_v2.render_dispatch` is the
# writer; `_check_dispatch_record` compares a recorded argv against the bound
# condition in both directions.
_WEB_SWITCH = {None: "--search", "agy": "--review-web", "gemini": "--review-web"}
# The run-log directory each WRAPPER route's wrapper writes its receipt under
# (the `cli` its `emit_run_log` call passes), keyed like `_WEB_SWITCH`
# (R-BIND: `<attempt>/logs/<cli>/runs/`, set by `TRIAD_REVIEW_LOG_DIR`).
_RUN_LOG_CLI = {None: "codex", "agy": "antigravity", "gemini": "gemini"}
_RECEIPT_REMEDY = ("the leg ran with a command other than the recorded one — "
                   "retry this entry and run its printed line verbatim "
                   "(R-BIND)")

# THE EVIDENCE SIZE CAP (gate-1 r19 row r19-2) — the same 64 MiB bound as
# `agy_hook._EVIDENCE_MAX_BYTES` and `verdict_v2._EVIDENCE_MAX_BYTES` (gate-1
# r20 row r20-2), spelled locally in each (that module stays stdlib-only and
# importable on its own, and this reader must not depend on loading it); a
# change touches all three — t11 axis 27 pins them equal. Every record and
# log this helper reads is a few KB.
_EVIDENCE_MAX_BYTES = 64 * 1024 * 1024
_EVIDENCE_CAP_TEXT = "64 MiB"

# THE SEAL OF A RECORDED ATTEMPT (R-BIND, case C66). The native admission,
# or on a wrapper route the first collection that judges an answer, writes
# this file into the attempt's own directory, binding the digests of its
# result, receipt and read evidence; every later collection re-checks them. `verdict_v2._SEAL_NAME` spells the
# same name (that module imports no sibling) to refuse a re-admission into a
# sealed attempt; t15 axis 81 pins the two equal.
_SEAL_NAME = "seal.json"
# A file a `failed-to-run` seal found unreadable is sealed as found: a
# later re-check that can read it calls it changed.
_UNREADABLE = "unreadable"
_SEAL_REMEDY = ("a recorded attempt is sealed (R-BIND, case C66): a new answer "
                "from this entry needs a new attempt, allowed only after a "
                "failure to run (R-RETRY), or a new round (R-REREVIEW) — "
                "prepare a new round")

_USAGE = (
    "usage: collect_v2.py collect <abs-packet-dir> r<N>\n"
    "       collect_v2.py retry <abs-packet-dir> r<N> <leg-name> "
    "--diagnosis TEXT"
)


class CollectError(Exception):
    """A refusal: the collection or the retry cannot proceed (exit 2)."""


class _HostFault(CollectError):
    """THIS HOST is broken, and nothing about any leg is known (row r7-c4).

    `verdict_v2` exits 64 for exactly one class: the admission could not RUN
    — jsonschema absent, the vendored contract unreadable / corrupt / not
    Draft 2020-12, the target refused as a host fault. Recording that as the
    entry's `invalid` folded the round to INCOMPLETE, which is the leader's
    instruction to RE-DISPATCH the paid legs — over an install that cannot
    judge any reply. The collection STOPS instead, with its own usage/host
    exit 64 and a one-line reason naming the fault, and writes NO per-entry
    state: the outcome vocabulary (0/2/4/5/64) is unchanged, because 64 was
    always this file's usage/host exit.
    """


def _load_sibling(name: str):
    """Import a sibling module from THIS file's directory (see the docstring's
    `sys.modules`-before-`exec_module` note)."""
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    path = LIB_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CollectError(f"the v2 helper {name}.py is not beside "
                           f"{Path(__file__).name} ({path})")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


@dataclass(frozen=True)
class EntryResult:
    """One roster entry's collected state at its RECORDED attempt."""

    name: str
    family: str
    route: str | None
    acceptance: str
    attempt: int | None
    state: str                  # "valid" | "missing" | "invalid"
    reason: str | None = None
    verdict: str | None = None
    blocking: int = 0
    open_questions: int = 0
    deviation: bool = False
    result_path: str | None = None
    exit_code: int | None = None
    # C66: the digests this evaluation JUDGED, when the collection is to seal
    # the attempt (never written to the record), and every seal of this
    # entry the collection record holds ({attempt: sha256 of seal.json}).
    seal_files: dict | None = None
    seals: dict | None = None

    def json(self) -> dict:
        return {"name": self.name, "family": self.family, "route": self.route,
                "acceptance": self.acceptance, "attempt": self.attempt,
                "state": self.state, "reason": self.reason,
                "verdict": self.verdict, "blocking": self.blocking,
                "open_questions": self.open_questions,
                "deviation": self.deviation, "result_path": self.result_path,
                "exit_code": self.exit_code,
                "seals": {str(k): v for k, v in sorted((self.seals
                                                        or {}).items())}}


@dataclass(frozen=True)
class Collection:
    """The round's all-entry outcome plus its separately reported coverage."""

    outcome: str
    entries: list = field(default_factory=list)
    families_covered: list = field(default_factory=list)
    deviations: list = field(default_factory=list)
    blocking: int = 0
    open_questions: int = 0
    record_path: Path | None = None

    @property
    def exit_code(self) -> int:
        return OUTCOME_EXIT[self.outcome]

    @property
    def valid(self) -> int:
        return sum(1 for e in self.entries if e.state == "valid")


# ---------------------------------------------------------------------------
# round record
# ---------------------------------------------------------------------------
def record_path(packet_dir: Path, label: str) -> Path:
    return Path(packet_dir) / f".roster-{label}.json"


def _read_record(packet_dir: Path, label: str) -> dict:
    path = record_path(packet_dir, label)
    # HARDENED, like every other helper-owned read (gate-1 r10 row r10-7,
    # extended by the x leg). This is the r9-2 AUTHORITY — the file that
    # names WHICH attempt each entry is evaluated at — and it was read with
    # `read_text()`, which FOLLOWS a symlink and blocks forever on a FIFO,
    # inside a directory this helper owns. `_read_regular_file` refuses a
    # non-regular path BY NAME before a byte is read; FileNotFoundError
    # keeps its own "this label was not prepared" reason below, so the
    # missing-record diagnosis is unchanged.
    try:
        os.lstat(path)
    except FileNotFoundError:
        raise CollectError(
            f"no v2 round record at {path} — this label was not prepared with "
            f"`prepare ... --v2`, so there is no roster to collect") from None
    except OSError:
        pass        # `_read_regular_file` names every other stat failure
    try:
        data = _read_regular_file(path, "the round record")
    except CollectError as exc:
        raise CollectError(f"{exc} — prepare a new round") from exc
    try:
        doc = json.loads(data.decode("utf-8"))
    # EVERY WAY A RECORD LOAD CAN FAIL (gate-1 r7 row r7-k3). `json.loads`
    # raises more than OSError/ValueError: a document nested past the
    # interpreter's recursion limit raises RecursionError, which is NOT a
    # ValueError, so it escaped this catch as a traceback. UnicodeDecodeError
    # IS a ValueError and is named anyway — the tuple is the rule, not a
    # reader's memory of the class hierarchy. Same tuple at every record load
    # in this file (round record, binding, dispatch).
    except (OSError, ValueError, RecursionError, UnicodeDecodeError) as exc:
        raise CollectError(f"the round record {path} is unreadable: "
                           f"{' '.join(str(exc).split())}") from exc
    if not isinstance(doc, dict) or "entries" not in doc:
        raise CollectError(f"the round record {path} is malformed (no entries)")
    _check_record_shape(doc, path)
    return doc


def _check_record_shape(doc: dict, path: Path) -> None:
    """The record is walkable, or it is refused BY FIELD (gate-1 r9 row r9-6).

    `_read_record` probed the PRESENCE of `entries` and nothing else, so
    `"entries": null` and `"entries": [null]` both loaded cleanly and then
    met `_dispatched`'s iteration and `entry.get(...)` — a TypeError /
    AttributeError traceback out of a tool whose every other failure is one
    refusal line. The same held for every scalar the collector dereferences
    with `record[...]`: a record missing `results_dir` crashed inside
    `_evaluate`, and one missing `review_id` / `content_digest` / `worktree`
    degraded SILENTLY (a derived binding of None mismatched every entry, so
    a tampered record read as "every leg answered wrong").

    This is a SHAPE check, not a contract: only the members this file
    dereferences are named, each with its own field in the refusal. Members
    with their own dedicated refusal downstream (`projection_digest`,
    `contract_digest`, `prompt_spec_dir`, `hook_log`) keep it — they are
    only TYPE-checked here when present, so a record that omits one still
    reaches the refusal that explains what it was for.
    """
    entries = doc.get("entries")
    if not isinstance(entries, list):
        raise CollectError(
            f"the round record {path} is malformed: `entries` is "
            f"{type(entries).__name__}, not a list")
    for idx, entry in enumerate(entries):
        where = f"`entries[{idx}]`"
        if not isinstance(entry, dict):
            raise CollectError(
                f"the round record {path} is malformed: {where} is "
                f"{type(entry).__name__}, not an object")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise CollectError(
                f"the round record {path} is malformed: {where} has no "
                f"usable `name` ({type(name).__name__})")
        where = f"entry {name!r}"
        if not isinstance(entry.get("leg"), dict):
            raise CollectError(
                f"the round record {path} is malformed: {where} has no "
                f"`leg` object ({type(entry.get('leg')).__name__}) — a retry "
                f"re-renders from the round's OWN frozen roster entry")
        # `vendor` IS CONSUMED, SO IT IS CHECKED (gate-1 r10 row r10-6).
        # `_evaluate` and `_expected_binding` both read it as the EAGER
        # default of a `get` — `entry.get("family", entry["vendor"])` — so a
        # record without the key raised a KeyError out of a tool whose every
        # other failure is one refusal line, and it raised it even when
        # `family` was present. The writer emits it on every entry.
        if not isinstance(entry.get("vendor"), str) or not entry["vendor"]:
            raise CollectError(
                f"the round record {path} is malformed: {where} has no "
                f"usable `vendor` ({type(entry.get('vendor')).__name__}) — "
                f"it is the family this entry's result is admitted under")
        # A DISPATCHED ENTRY NAMES ITS ATTEMPT (gate-1 r10 row r10-2). The
        # type check below ran only on a PRESENT non-null value, so a
        # dispatched entry carrying `"attempt": null` (or no key at all)
        # reached `_evaluate` as None — and `_evaluate` now evaluates
        # EXACTLY the attempt the record names, so a record that names none
        # cannot be walked at all. `prepare` allocates one for every
        # dispatched entry and `retry` bumps it; null stays legal on the
        # entries that were never dispatched (disabled / skipped), which is
        # exactly what the writer emits for them.
        attempt = entry.get("attempt")
        dispatched = bool(entry.get("enabled")) and not entry.get(
            "skipped_reason")
        if attempt is None and dispatched:
            raise CollectError(
                f"the round record {path} is malformed: {where} is "
                f"dispatched but names no `attempt` — the attempt this round "
                f"allocated is what the collector evaluates")
        if attempt is not None and (isinstance(attempt, bool)
                                    or not isinstance(attempt, int)
                                    or attempt < 1):
            raise CollectError(
                f"the round record {path} is malformed: {where} has a "
                f"non-numeric `attempt` ({attempt!r}) — the attempt this "
                f"round allocated is what the collector evaluates")
    for key in ("review_id", "content_digest", "worktree", "results_dir"):
        value = doc.get(key)
        if not isinstance(value, str) or not value:
            raise CollectError(
                f"the round record {path} is malformed: `{key}` is "
                f"{type(value).__name__}, not a non-empty string")
    for key in ("projection_digest", "contract_digest", "prompt_spec_dir",
                "hook_log"):
        if key in doc and doc[key] is not None \
                and not isinstance(doc[key], str):
            raise CollectError(
                f"the round record {path} is malformed: `{key}` is "
                f"{type(doc[key]).__name__}, not a string")
    # THE TWO CONTAINERS THIS FILE WALKS (gate-1 r10 row r10-6). Both are
    # read with a `.get` default, which covers ABSENCE and nothing else:
    # `gate_files: null` met the agy gate's argv build as an iteration
    # (TypeError), a non-string member reached `read_audit_gate.sh` as an
    # argv token and came back as an exit-64 HOST FAULT that named the
    # script instead of the record, and a LIST `prompt_manifests` met
    # `(… or {}).get(name)` as an AttributeError. Type-checked here, by
    # field, before any of them is dereferenced.
    #
    # `null` IS REFUSED, not tolerated: `.get(key, default)` answers the
    # default for an ABSENT key only, so an explicit null is exactly the
    # value that reached the dereference. A record this helper wrote always
    # carries both keys. Absence is not refused HERE: a record old enough to
    # lack them binds no stage, selection or configuration either, so
    # `_bound_metadata` refuses it anyway ("prepare a new round").
    gate_files = doc.get("gate_files")
    if "gate_files" in doc and not (
            isinstance(gate_files, list)
            and all(isinstance(f, str) and f for f in gate_files)):
        raise CollectError(
            f"the round record {path} is malformed: `gate_files` is not a "
            f"list of non-empty strings — it is the required-read set the "
            f"agy read-audit gate is run with")
    manifests = doc.get("prompt_manifests")
    if "prompt_manifests" in doc and not (
            isinstance(manifests, dict)
            and all(isinstance(k, str) for k in manifests)
            and all(isinstance(v, list)
                    and all(isinstance(pair, list) for pair in v)
                    for v in manifests.values())):
        raise CollectError(
            f"the round record {path} is malformed: `prompt_manifests` is "
            f"not a mapping of leg name to a list of clause digest pairs — "
            f"it is the frozen prompt basis a retry proves unchanged")


def _bound_metadata(packet_dir: Path, label: str, record: dict,
                    what: str) -> dict:
    """The `Review metadata:` object BOUND into this round's content digest,
    after proving the round record still carries the round's bound identity,
    SELECTION and CONFIGURATION (R-ROSTER, R-AGREE, R-RETRY, R-REREVIEW;
    cases C19 / C33) — or a refusal.

    The roster record is census-exempt and mutable. `prepare --v2` writes the
    worktree, review id, round, the selected (enabled) entry names and the
    configuration digest (`review_scratch._v2_config_digest`: every entry
    minus its runtime `attempt`, plus the evidence paths) into the metadata
    line of `delivery-r<N>.md`, whose sha256 IS the round's content_digest.
    A record that moved — an entry dropped or added, a model, effort,
    reasoning, route, agent, acceptance or path changed — would be collected
    or re-rendered on conditions nobody reviewed under, so every reader of
    the record (collect, retry, adoption) refuses it here. A changed
    condition is a new round."""
    delivery = packet_dir / f"delivery-{label}.md"
    try:
        raw = _read_regular_file(delivery, "the round's delivery record")
    except CollectError as exc:
        raise CollectError(f"{exc} — prepare a new round") from exc
    if hashlib.sha256(raw).hexdigest() != record["content_digest"]:
        raise CollectError(
            f"{delivery} no longer hashes to the round's content_digest, so "
            f"the review conditions bound into it cannot be read for "
            f"{what} — prepare a new round")
    first = raw.decode("utf-8", "replace").split("\n", 1)[0]
    prefix = "Review metadata: "
    try:
        bound = json.loads(first[len(prefix):]) \
            if first.startswith(prefix) else None
    except ValueError:
        bound = None
    if not isinstance(bound, dict):
        raise CollectError(
            f"{delivery} binds no review metadata, so {what} cannot prove "
            f"this round's basis — prepare a new round")
    selected = bound.get("selected_entries")
    if not (isinstance(selected, list)
            and all(isinstance(n, str) for n in selected)):
        raise CollectError(
            f"{delivery} binds no entry selection, so {what} cannot prove "
            f"which entries this round selected — prepare a new round")
    for key in ("worktree", "review_id", "round"):
        if record.get(key) != bound.get(key):
            raise CollectError(
                f"the round record's {key} {record.get(key)!r} differs from "
                f"the one bound into this round {bound.get(key)!r} — {what} "
                f"is refused; prepare a new round")
    recorded = sorted(e.get("name") for e in record["entries"]
                      if e.get("enabled"))
    if recorded != sorted(selected):
        raise CollectError(
            f"the round record's entry selection {recorded} differs from the "
            f"selection bound into this round {sorted(selected)} — a changed "
            f"roster is a new round on a new basis, never a dropped or added "
            f"entry (R-ROSTER, R-AGREE, R-REREVIEW); {what} is refused")
    config = bound.get("roster_config_digest")
    if not isinstance(config, str):
        raise CollectError(
            f"{delivery} binds no roster configuration digest, so {what} "
            f"cannot prove the round's controls are unchanged — prepare a new "
            f"round")
    live = _load_sibling("review_scratch")._v2_config_digest(record)
    if live != config:
        raise CollectError(
            f"the round record's roster configuration (an entry's model, "
            f"effort, reasoning, route, agent, acceptance, timeout or an "
            f"evidence path) differs from the configuration bound into this "
            f"round (bound {config}, record {live}) — a changed condition is "
            f"a new round on a new basis, never a retry or a collection "
            f"(R-RETRY, R-REREVIEW); {what} is refused")
    # THE REVIEW-WEB CONDITION AND THE ROUND DATE (R-REVIEW-WEB, R-PROMPT;
    # case C32). A strict boolean; an ABSENT condition in an older bound
    # record means false. The record's copies must equal the bound values.
    web = bound.get("review_web_authorized", False)
    if type(web) is not bool:
        raise CollectError(
            f"{delivery} binds review_web_authorized {web!r}, not a strict "
            f"boolean, so {what} cannot prove the round's review-web "
            f"condition — prepare a new round")
    recorded_web = record.get("review_web_authorized", False)
    if type(recorded_web) is not bool or recorded_web != web:
        raise CollectError(
            f"the round record's review_web_authorized {recorded_web!r} "
            f"differs from the condition bound into this round ({web!r}) — a "
            f"changed condition is a new round on a new basis (R-REVIEW-WEB, "
            f"R-REREVIEW); {what} is refused")
    date = bound.get("review_date")
    # ONE strict validator with the renderer (A2): a calendar day in ASCII
    # digits, never a date-shaped string.
    if date is not None and not _load_sibling("prompts_v2")._valid_date(date):
        raise CollectError(
            f"{delivery} binds review_date {date!r}, not a UTC date "
            f"YYYY-MM-DD — prepare a new round")
    if record.get("review_date") != date:
        raise CollectError(
            f"the round record's review_date {record.get('review_date')!r} "
            f"differs from the date bound into this round ({date!r}) — a "
            f"changed condition is a new round on a new basis (R-PROMPT, "
            f"R-REREVIEW); {what} is refused")
    return bound


def _bound_conditions(packet_dir: Path, label: str, record: dict,
                      name: str) -> dict:
    """The review conditions BOUND into this round's content digest — the
    stage (R-PROMPT, case C60), the review-web condition and the round date
    (R-REVIEW-WEB, case C32) — as the `conditions` mapping a re-render takes,
    or a refusal (R-REREVIEW; case C33).

    `prepare --v2` writes them into the `Review metadata:` line of
    `delivery-r<N>.md`, whose sha256 IS the round's content_digest. The
    roster record is census-exempt and mutable, so its copies are only
    copies: a retry or an adoption re-renders a prompt only when the delivery
    record still hashes to the recorded digest and every copy equals the
    bound value (`_bound_metadata`). An absent review-web condition reads as
    false; a round that binds no date cannot re-render the current-date
    clause and is refused. Any mismatch is a changed review condition — a new
    round, never a re-render."""
    delivery = packet_dir / f"delivery-{label}.md"
    bound = _bound_metadata(packet_dir, label, record, repr(name))
    if not isinstance(bound.get("review_kind"), str):
        raise CollectError(
            f"{delivery} binds no review_kind, so the prompt for {name!r} "
            f"cannot be re-rendered on this round's basis — prepare a new "
            f"round")
    kind = bound["review_kind"]
    if record.get("review_kind") != kind:
        raise CollectError(
            f"roster entry {name!r}: the round record says review_kind "
            f"{record.get('review_kind')!r} but the round's bound basis says "
            f"{kind!r} — a changed review condition is a new round, never a "
            f"retry (R-REREVIEW)")
    if bound.get("review_date") is None:
        raise CollectError(
            f"{delivery} binds no review_date, so the prompt for {name!r} "
            f"cannot be re-rendered on this round's basis — prepare a new "
            f"round")
    return {"review_kind": kind,
            "review_web_authorized": bound.get("review_web_authorized", False),
            "review_date": bound["review_date"]}


def _read_regular_file(path: Path, label: str) -> bytes:
    """The bytes of a plain REGULAR file, or a `CollectError` naming it
    (gate-1 r9 row r9-11).

    `_check_adopted_bytes` read the adopted `prompt.txt` and
    `schema.projected.json` with `Path.read_bytes()`, which FOLLOWS a
    symlink — while every other helper-owned read in this file refuses a
    non-regular path BY NAME. A link planted at either name, pointing at a
    target whose bytes happen to match, passed the comparison, and the
    adopted invocation feeds the vendor whatever that link resolves to from
    then on.

    Same shape as `verdict_v2._read_regular_file_no_symlink` and
    `roster_v2._read_regular_file`: `lstat` decides for every non-regular
    type BEFORE the open (a FIFO would otherwise block it forever),
    `O_NONBLOCK` closes the window where one appears in between,
    `O_NOFOLLOW` covers a symlink swapped in after the lstat, and the
    descriptor's own `fstat` re-checks S_ISREG before a byte is read. All
    POSIX — no platform branch.

    BOUNDED (gate-1 r19 row r19-2): a file over `_EVIDENCE_MAX_BYTES` is a
    `CollectError` naming it and the cap, raised on the descriptor's `fstat`
    BEFORE a byte is read (and the read stops at the cap should it grow
    meanwhile) — a misfiled multi-GB file must fail its ONE entry through
    the callers' per-entry isolation, never exhaust memory for the command.

    The text names the CAUSE only; each caller names the remedy that works
    where it reads (R1: under `results-r<N>/` nothing is removed by hand).
    """
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise CollectError(f"{label} {path} is unreadable "
                           f"({' '.join(str(exc).split())})") from exc
    if stat.S_ISLNK(st.st_mode):
        raise CollectError(
            f"{label} {path} is a symlink — this helper reads the bytes it "
            f"allocated, never a link to somewhere else")
    if not stat.S_ISREG(st.st_mode):
        raise CollectError(
            f"{label} {path} is not a regular file — this helper reads the "
            f"bytes it allocated, never a special path somebody planted")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
    except OSError as exc:
        raise CollectError(f"{label} {path} is unreadable "
                           f"({' '.join(str(exc).split())})") from exc
    too_big = (f"{label} {path} exceeds the {_EVIDENCE_CAP_TEXT} evidence "
               f"cap — no file this helper reads is anywhere near that size, "
               f"so it is misfiled or corrupt")
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            raise CollectError(f"{label} {path} is not a regular file")
        if fst.st_size > _EVIDENCE_MAX_BYTES:
            raise CollectError(too_big)
        chunks: list = []
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _EVIDENCE_MAX_BYTES:
                raise CollectError(too_big)
            chunks.append(chunk)
    except OSError as exc:
        raise CollectError(f"{label} {path} is unreadable "
                           f"({' '.join(str(exc).split())})") from exc
    finally:
        os.close(fd)
    return b"".join(chunks)


def _write_json(path: Path, doc: dict) -> None:
    """Write one of this helper's OWN records: temp file + `os.replace`.

    A NON-REGULAR target is refused BY NAME first (gate-1 r6 row r6-11).
    `collect` used a plain `write_text` for `collect-r<N>.json`, which FOLLOWS
    a symlink — a link planted at that path put the round's collected state
    wherever it pointed. The replace idiom itself never writes THROUGH a link
    (it swaps the name), but the lstat is what turns a planted path into a
    named refusal instead of a silently replaced one, and it keeps the rule
    identical for both records this file writes."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise CollectError(f"{path} cannot be inspected "
                           f"({' '.join(str(exc).split())}) — this helper "
                           f"writes its own records only where it can prove "
                           f"what is already there") from exc
    else:
        if not stat.S_ISREG(st.st_mode):
            raise CollectError(
                f"{path} is not a regular file (a symlink or another special "
                f"path) — this helper never writes a round record through a "
                f"path somebody else planted, and a later capture in this "
                f"packet dir refuses it too; inspect it, then prepare the round "
                f"in a new packet dir (`review_scratch.py open` with a new slug)")
    # THE TEMP FILE IS EXCLUSIVE-CREATED TOO (gate-1 r7 rows r7-x3 / r7-k2).
    # The lstat above refuses a planted TARGET, but the staging used
    # `write_text`, which FOLLOWS a symlink planted at this predictable
    # `.tmp-<pid>-<name>` — so the round's collected state was written
    # wherever that link pointed, in a directory this helper owns. Both
    # sibling writers (`verdict_v2._write_admitted_out`,
    # `review_scratch._write_new_file`) have always opened theirs with
    # O_CREAT|O_EXCL; this is the same rule, one file over. `O_EXCL` refuses
    # any pre-existing name (a symlink included, dangling or not) and
    # `O_NOFOLLOW` states the intent at the syscall. The `finally` removes a
    # temp the staging did not consume, so a refused write leaves no
    # `.tmp-…` residue for `verify` to report as an uncovered packet file.
    tmp = path.with_name(f".tmp-{os.getpid()}-{path.name}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError as exc:
        raise CollectError(
            f"{tmp} cannot be exclusive-created "
            f"({' '.join(str(exc).split())}) — this helper stages its own "
            f"records through a temp file it creates itself and never "
            f"writes through a name somebody else planted; inspect it, then "
            f"prepare the round in a new packet dir (`review_scratch.py open` "
            f"with a new slug)") from exc
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        os.replace(tmp, path)
        replaced = True
    except OSError as exc:
        raise CollectError(f"{path} could not be written through its staging "
                           f"file {tmp} "
                           f"({' '.join(str(exc).split())})") from exc
    finally:
        if not replaced:
            try:
                os.unlink(tmp)
            except OSError as cleanup_exc:
                # THE RESIDUE IS DISCLOSED, NEVER SWALLOWED (gate-1 r8 row
                # r8-6). The refusal already in flight is the reported error
                # — re-raising from a `finally` would REPLACE it with a
                # cleanup detail — but a `.tmp-…` this helper could not
                # remove stays in a directory it owns, where `verify` reports
                # it as an uncovered packet file and the operator has been
                # told nothing about it. One line naming the path, on the
                # diagnostic stream, beside the refusal.
                print(f"collect_v2: NOTE: the staging file {tmp} could not "
                      f"be removed ({' '.join(str(cleanup_exc).split())}) — "
                      f"it is residue of the refused write above, which "
                      f"`verify` reports as an uncovered packet file; prepare "
                      f"a new round", file=sys.stderr)


def _write_record(packet_dir: Path, label: str, doc: dict) -> None:
    """Rewrite the round record. It is DELIBERATELY outside the packet census
    (`review_scratch._packet_relpaths`), because `retry` bumps an entry's
    attempt on an UNCHANGED basis — the delivered bytes it points at stay
    frozen in the worktree fingerprint and in each attempt's own records."""
    _write_json(record_path(packet_dir, label), doc)
    _heartbeat(packet_dir)


def _heartbeat(packet_dir: Path) -> None:
    """Refresh the packet's `.active` mtime (M3: a retry or a collection is
    activity, so a paused round is not pruned as stale). Refresh-only and
    best-effort: never mints the marker, never follows a link."""
    marker = Path(packet_dir) / ".active"
    try:
        if stat.S_ISREG(os.lstat(marker).st_mode):
            os.utime(marker, follow_symlinks=False)
    except OSError:
        pass


def _dispatched(record: dict) -> list:
    """The entries a round actually dispatched: enabled and not skipped —
    the ones that have an attempt directory to evaluate.

    NOT the entries the COLLECTION reports (gate-1 r11 row r11-9). A skipped
    entry is still ENABLED, so `collect` counts and names it as a missing
    result; this helper answers the narrower question "whose attempt is on
    disk", which is what the per-attempt readers need."""
    return [e for e in record["entries"]
            if e.get("enabled") and not e.get("skipped_reason")]


def _attempts(entry_dir: Path) -> list:
    found = []
    try:
        entries = list(os.scandir(entry_dir))
    except OSError:
        return []
    for item in entries:
        head, _, tail = item.name.partition("-")
        if head != "attempt" or not tail:
            continue
        # A NAME THIS HELPER OWNS IS A REAL DIRECTORY OR IT IS REFUSED
        # (gate-1 r6 row r6-10). The `is_dir(follow_symlinks=False)` test used
        # to run BEFORE the name check and `continue` on a false, so a
        # SYMLINKED `attempt-3` was silently skipped and the collector read a
        # LOWER attempt than the tree holds — the same failure the
        # non-decimal refusal below exists to prevent, reached through a link
        # instead of a spelling. Nothing is deleted or followed; the entry is
        # named and refused.
        if not item.is_dir(follow_symlinks=False):
            raise CollectError(
                f"{item.path} is not a usable attempt directory: it is a "
                f"symlink or not a directory — an attempt directory is one "
                f"this helper allocated, never a link to somewhere else; "
                f"prepare a new round")
        # `str.isdigit()` is TRUE for characters `int()` refuses — U+00B2 and
        # the other superscripts among them — so the guard admitted a name the
        # very next line crashed on, and the ValueError escaped as a traceback
        # instead of the one-line refusal this tool promises (gate-1 r4 row
        # r4-15, the r2-20 class one file over). `isdecimal()` is the narrower
        # predicate and `int()` is wrapped anyway: the parse decides, never the
        # predicate alone. A name that looks like an attempt directory but
        # carries no decimal number is REFUSED, not skipped — silently
        # ignoring it would make the collector read a LOWER attempt than the
        # tree holds, inside a directory this helper owns.
        if not tail.isdecimal():
            raise CollectError(
                f"{item.path} is not a usable attempt directory: the suffix "
                f"{tail!r} is not a decimal attempt number — one entry + one "
                f"attempt number = one allocation; prepare a new round")
        try:
            number = int(tail)
        except ValueError:
            raise CollectError(
                f"{item.path} is not a usable attempt directory: the suffix "
                f"{tail!r} is not a decimal attempt number — one entry + one "
                f"attempt number = one allocation; prepare a new round")
        # ONE NUMBER, ONE SPELLING (gate-1 r6 row r6-9). `int()` is not
        # injective over the names `isdecimal()` admits: `attempt-01`,
        # `attempt-001` and every non-ASCII decimal spelling map to the same
        # number as the canonical `attempt-1`. The sort below is stable, so
        # FILESYSTEM ORDER decided which of two directories claiming the same
        # attempt had its verdict credited to the entry — and a copy dropped
        # in under a second spelling admits cleanly, because the derived
        # binding (row r5-1) names the NUMBER, which both spellings satisfy.
        # The writer only ever produces the canonical form.
        if item.name != f"attempt-{number}":
            raise CollectError(
                f"{item.path} is not a usable attempt directory: "
                f"{item.name!r} is not the canonical spelling "
                f"'attempt-{number}' (ASCII digits, no leading zero) — one "
                f"entry + one attempt number = one allocation, and two "
                f"spellings of one number are two directories for it; "
                f"prepare a new round")
        if number >= 1:
            found.append((number, Path(item.path)))
    return [pair for pair in sorted(found, key=lambda p: p[0])]


# ---------------------------------------------------------------------------
# per-entry evaluation
# ---------------------------------------------------------------------------
def _result_filename(family: str) -> str:
    """Where THIS family's admitted result lives inside its attempt dir: a
    wrapper leg's stdout IS its verdict document; the native claude leg's raw
    reply is prose-tolerant, so its admitted canonical form is the subject."""
    return "admitted.json" if family == "claude" else "verdict.json"


def _run(cmd: list) -> subprocess.CompletedProcess:
    # UTF-8 IS PINNED, NEVER TAKEN FROM THE LOCALE (gate-1 r6 row r6-12).
    # `text=True` alone decodes with `locale.getpreferredencoding()`, so on a
    # host running under an ASCII locale the gate's own em-dash diagnostics
    # raised UnicodeDecodeError out of `_agy_evidence_reason` — a traceback
    # where the agy entry owed a one-line reason, taking the WHOLE collection
    # with it. `errors="replace"` keeps a byte nobody can decode from doing
    # the same. Same pin `_common.py` applies to every vendor pipe.
    return subprocess.run(cmd, capture_output=True, text=True, check=False,
                          encoding="utf-8", errors="replace")


def _token(text: str, prefix: str) -> str:
    for line in reversed(text.splitlines()):
        if line.startswith(prefix):
            return line.strip()
    return f"{prefix}<no summary line>"


# The evidence tools' guidance tail on an entry reason (gate-1 r15 row r15-2).
# 500, not 300 (gate-1 r16 row r16-2): with the remedy starting at the
# hooks.json step it is ~200-290 characters on its own, and 300 left the WHY
# too little room to name the attempt it is about.
_GUIDANCE_CAP = 500
_GUIDANCE_HEAD = re.compile(r"^\[review\] [^\n]{0,80}? — ")
_GUIDANCE_REMEDY = "prepare a NEW round"
# The step the hook check's two VOID arms put BEFORE the NEW-round clause
# ("check <worktree>/.agents/hooks.json, then prepare a NEW round …"): when the
# text before the remedy ends with it, the remedy starts at it (row r16-2).
_GUIDANCE_CHECK = re.compile(r"check \S*hooks\.json, then\s*$")
_SENTENCE_END = re.compile(r"\.\s")
# An absolute path, kept as its last THREE components when the WHY must
# shrink, so `<name>/attempt-K/read-audit.json` keeps the entry name (row
# r16-2; two components dropped it).
_GUIDANCE_PATH = re.compile(
    r"/[^\s\"'()]*/([^/\s\"'()]+/[^/\s\"'()]+/[^/\s\"'()]+)")


def _elide(text: str, budget: int, keep: int = 0) -> str:
    """`text` shortened to `budget` characters by eliding its MIDDLE (the
    head names the subject, the tail carries the finding). `keep` is a head
    length to preserve — the end of the first shortened path, i.e. the
    attempt the WHY is about — when it leaves room for a tail."""
    if len(text) <= budget:
        return text
    if budget < 2:
        return ""
    head = keep if 0 < keep <= budget * 3 // 4 else min(40, budget // 4)
    return text[:head] + "…" + text[len(text) - (budget - head - 1):]


def _guidance(stderr) -> str:
    """` — <WHY>[; <REMEDY>]` from the LAST `[review] …` line an evidence
    tool wrote to stderr, or "" when it wrote none.

    The entry reason used to carry only the tool's summary token, so the WHY
    and the remedy (often: prepare a NEW round) never reached the collect
    report. The tool's own header (`[review] agy hook load check VOID — `)
    repeats the token and is dropped; the rest is whitespace-collapsed to
    ONE line. WHY = its first sentence; REMEDY = the clause starting at
    "prepare a NEW round", up to its end of sentence, when the line has one
    — or at the "check <worktree>/.agents/hooks.json, then" step directly
    before it (the hook check's two VOID arms, row r16-2) — and a clause
    starting inside the first sentence ends the WHY there. The two are
    joined with "; " and capped at `_GUIDANCE_CAP` characters (a vendor id
    or a long path cannot grow the report). When the join is over the cap
    the WHY shrinks FIRST so the remedy survives — its absolute paths down
    to their last three components (`<name>/attempt-K/read-audit.json`),
    then its middle elided, keeping the head through the first path."""
    lines = [ln for ln in (stderr or "").splitlines()
             if ln.startswith("[review] ")]
    if not lines:
        return ""
    text = " ".join(lines[-1].split())
    head = _GUIDANCE_HEAD.match(text)
    text = text[head.end():] if head else text[len("[review] "):]
    end = _SENTENCE_END.search(text)
    why = text[:end.start() + 1] if end else text
    remedy = ""
    at = text.find(_GUIDANCE_REMEDY)
    if at >= 0:
        step = _GUIDANCE_CHECK.search(text, 0, at)
        if step:
            at = step.start()
        stop = _SENTENCE_END.search(text, at)
        remedy = text[at:stop.start() + 1] if stop else text[at:]
        if at < len(why):
            why = text[:at].rstrip(" ;,:—")
    joined = "; ".join(part for part in (why, remedy) if part)
    if len(joined) > _GUIDANCE_CAP and remedy:
        why = _GUIDANCE_PATH.sub(r"…/\1", why)
        first = re.search(r"…/\S+", why)
        why = _elide(why, _GUIDANCE_CAP - len(remedy) - 2,
                     first.end() if first else 0)
        joined = "; ".join(part for part in (why, remedy) if part)
    if len(joined) > _GUIDANCE_CAP:
        joined = joined[:_GUIDANCE_CAP - 1] + "…"
    return f" — {joined}" if joined else ""


def _agy_round_audits(packet_dir: Path, record: dict, primary) -> list:
    """Every OTHER agy read audit in this round — EVERY ATTEMPT of every
    agy-route entry, `primary` (the one the caller is checking) excluded.

    The round worktree carries ONE `.agents/hooks.json`, so every agy leg and
    every retry of the round appends to the SAME hook log. The load check can
    therefore only answer per ROUND: it ATTRIBUTES hook rows to attempts by
    the conversation ids each attempt's census row recorded
    (`lib/agy_hook.py`, spec case C23) — every row with tool steps needs a
    hook row under an id that NO OTHER census row of the round recorded (one
    owner per id), and while any census row omitted ids at the writer's cap
    no id's single owner can be established, so nothing is attributed.
    Without these paths the check sees one leg's census beside every leg's
    rows, cannot tell whether an id is single-owned, and admits a leg on its
    SIBLINGS' evidence — the swap case C33 forbids.

    SUPERSEDED ATTEMPTS ARE CENSUS ROWS (gate-1 r11 row r11-1). This used to
    pass each entry's RECORDED attempt only, on the reasoning that leaving
    one out could only make the check stricter. It cannot: the superseded
    attempt's rows are STILL in the shared log, and a check that never sees
    that attempt's census can neither attribute those rows to it nor tell
    whether an id it recorded is shared — a run whose hook never loaded was
    covered by a stale attempt's rows (REPRODUCED by the leader at r11: two
    audits of one run each, a log holding leg A's current AND superseded
    rows and nothing from leg B, reported PASS). Every attempt of the round
    is a census row of the check.

    The attempt-directory scan is DELIBERATELY tolerant where `_attempts` is
    strict: this runs inside ONE entry's evaluation, and a `CollectError`
    raised for a directory under ANOTHER entry would throw away every
    entry's verdict (the r5-11 rule). A name this helper cannot read as an
    attempt directory belongs to an entry whose OWN evaluation refuses it by
    name, which makes the round INCOMPLETE on its own; anything present at
    a `read-audit.json` name is handed to the load check, which refuses
    every non-regular type itself (row r11-7).

    The ALLOCATED ATTEMPT DIRECTORY is what this enumerates, not the audit
    file's presence: the file appears when the leg is dispatched, and the
    load check skips a name that is not there only while its attempt was
    never DISPATCHED (no `stderr.log` beside it, or one without the engine's
    spawn line — gate-1 r12 row r12-1 / r13 row r13-1; a dispatched attempt
    with no audit is INCONCLUSIVE there). That keeps ONE
    answer for the collector and for the printers that put this
    command in front of the operator BEFORE any dispatch has run (row
    r11-5) — a printed command weaker than the collector's would certify a
    leg the collection refuses.
    """
    out = []
    primary = None if primary is None else str(primary)
    for other in _dispatched(record):
        if other.get("route") != "agy":
            continue
        entry_dir = Path(packet_dir) / record["results_dir"] / other["name"]
        try:
            items = sorted(os.scandir(entry_dir), key=lambda i: i.name)
        except OSError:
            continue
        for item in items:
            if not item.name.startswith("attempt-"):
                continue
            if not item.is_dir(follow_symlinks=False):
                continue
            audit = Path(item.path) / "read-audit.json"
            if str(audit) != primary:
                out.append(audit)
    return out


def _print_round_hook_checks(packet_dir: Path, record: dict, label: str,
                             retried: str) -> None:
    """After a `retry` allocates (or adopts) attempt K+1, re-print the hook
    load check of EVERY OTHER agy-route entry of the round.

    A HAND-RUN CHECK MUST NEVER BE WEAKER THAN THE COLLECTOR (gate-1 r12 row
    r12-5). The checks `prepare` printed for the other agy entries name the
    sibling audits that existed THEN, so after a retry they lack the new
    attempt — whose run the collector counts (row r11-1). Each entry's check
    is printed for its RECORDED attempt, with the sibling set
    `_agy_round_audits` computes now, i.e. exactly what `_agy_evidence_reason`
    will run. An entry whose record carries no usable attempt is left to the
    collector, which refuses it by name.

    AN AGY RETRY ONLY (gate-1 r13 row r13-7): the sibling set is the agy
    attempts of the round, so a codex / claude retry changes nothing any
    agy check counts — re-printing then claimed a false "now includes …
    new attempt" and repeated commands the operator already holds. A
    retried entry whose recorded route is not `agy` prints nothing."""
    if not any(e.get("name") == retried and e.get("route") == "agy"
               for e in _dispatched(record)):
        return
    review_scratch = _load_sibling("review_scratch")
    for other in _dispatched(record):
        if other.get("route") != "agy" or other.get("name") == retried:
            continue
        attempt = other.get("attempt")
        if (not isinstance(attempt, int) or isinstance(attempt, bool)
                or attempt < 1):
            continue
        audit = (Path(packet_dir) / record["results_dir"] / other["name"]
                 / f"attempt-{attempt}" / "read-audit.json")
        print(f"  {other['name']} (attempt {attempt}) — hook check RE-PRINTED: "
              f"every attempt is attributed; the sibling set now includes "
              f"{retried}'s new attempt")
        review_scratch._v2_print_hook_check(
            Path(packet_dir), label, audit,
            _agy_round_audits(packet_dir, record, audit))


def _agy_custody_reason(attempt_dir: Path, audit: Path) -> str | None:
    """None when THIS attempt's OWN dispatch produced the read audit beside it.

    The agy read audit is the WRAPPER's artifact and carries no leg identity:
    host A keeps admission on the HOST side and the wrapper transport-only, so
    no binding travels into it. (Host B stamps one from inside its wrapper —
    `bin/review_round_v2.py:306` refuses read evidence whose `review_binding`
    is not this invocation's — but it can do that only because B validates the
    verdict inside the vendor process. Porting that would cost A its
    transport-only wrapper and its host-side admission.)

    What A has instead is CUSTODY. `roster_v2.render_dispatch` gives every
    entry and every attempt its OWN `TRIAD_READ_AUDIT_FILE`, the dispatch
    redirects the wrapper's stderr into the same directory, and the wrapper
    logs `read-audit-file: <that absolute path>` there. So an attempt
    directory holding an audit that no dispatch of ITS OWN ever named is an
    ASSEMBLED directory, not evidence — the r7-13 misfiling class, and the
    shape a four-leg round makes easy to reach by hand.

    A WHOLE LINE, COMPARED IN FILESYSTEM BYTES (gate-1 r11 row r11-6). This
    was `f"read-audit-file: {audit}" in stderr_text`, and a SUBSTRING test
    over a replacement-decoded string is defeatable twice over: a line naming
    a LONGER path that merely CONTAINS this attempt's audit
    (`…/read-audit.json.bak`, or the same tail under another root) satisfied
    it, and a path byte that is not valid UTF-8 became U+FFFD on both sides
    so distinct paths compared equal. The line is now matched WHOLE — the
    producer's own `_common.log` timestamp prefix REQUIRED and stripped
    (row r12-7), nothing else tolerated — against `os.fsencode` of the audit
    path, which is the exact byte sequence the kernel holds, percent-escaped
    exactly as the producer escapes it (`_custody_field`, row r13-5), so a
    path carrying a newline or an undecodable byte is still ONE line on both
    sides.

    LIMIT, disclosed rather than implied: this ties the audit FILE to this
    attempt's dispatch. It cannot detect a sibling's audit CONTENT written
    over an audit this dispatch did produce, because nothing inside the file
    names a leg. Closing that needs the binding to reach the wrapper.
    """
    stderr_path = attempt_dir / "stderr.log"
    want = _CUSTODY_MARKER + _custody_field(os.fsencode(str(audit)))
    # the line as the producer writes it — escaped, so the reason stays ONE line
    wanted = want.decode("ascii")
    try:
        raw = _read_regular_file(stderr_path, "the dispatch stderr")
    except (CollectError, OSError) as exc:
        detail = (" ".join(str(exc).split()) if isinstance(exc, CollectError)
                  else f"{stderr_path} could not be read ({exc.strerror or exc})")
        return (f"{detail} — this attempt's dispatch stderr is where the "
                f"`{wanted}` line lives, and without it "
                f"nothing ties the read audit beside it to this entry, which "
                f"stays a SIBLING of every later attempt — prepare a new round")
    # THE PREFIX MUST BE THERE (gate-1 r12 row r12-7): `sub(..., count=1)` was
    # a no-op on a line WITHOUT the prefix, so an untimestamped line matched.
    # The wrapper's `_common.log` always timestamps, so only a line whose
    # prefix MATCHES at its start is the producer's.
    def _custody(line: bytes) -> bool:
        line = line.rstrip(b"\r")
        m = _LOG_PREFIX.match(line)
        return m is not None and line[m.end():] == want
    if not any(_custody(line) for line in raw.split(b"\n")):
        # NO AUDIT AT ALL (gate-1 r15 row r15-2). This runs only after a
        # valid verdict was admitted, so the attempt RAN and wrote no read
        # audit: the hook load check reads it as a dispatched sibling with no
        # audit (INCONCLUSIVE) for every later attempt of the round, so a
        # re-dispatch inside the round cannot clear it — the remedy is a NEW
        # round. A PRESENT audit with no custody line is a NEW round too (row
        # r16-3): a misfiled or foreign audit stays a sibling (ambiguous or
        # complete-VOID for the whole round) and hand-removal is forbidden;
        # only a genuine audit whose stderr lost its line clears on a retry.
        if not os.path.lexists(audit):
            return (f"{stderr_path} carries no `{wanted}` line and no read "
                    f"audit exists at {audit} — this attempt wrote no read "
                    f"evidence; it stays a SIBLING of every later attempt of "
                    f"this round (the hook load check reads a dispatched "
                    f"attempt with no audit as INCONCLUSIVE and deletes "
                    f"none), so prepare a NEW round (a fresh hook log) rather "
                    f"than re-dispatching inside this one")
        return (f"the audit at {audit} was not written by this dispatch "
                f"(no `{_CUSTODY_MARKER.decode('ascii').strip()}` line in its "
                f"stderr.log): a misfiled or foreign audit stays a SIBLING of every later "
                f"attempt of the round and cannot be hand-removed, so prepare "
                f"a NEW round; only a genuine audit whose stderr lost its line "
                f"is cleared by a retry")
    return None


def _retry_cannot_certify(packet_dir: Path, record: dict, entry: dict,
                          attempt: int, *, collecting: bool = False
                          ) -> str | None:
    """The sentence saying a retry of this entry cannot certify the round,
    or None (gate-1 r17 row r17-4, r18 row r18-2, r19 row r19-3; the
    missing-hook_log refusal covers every route, the rest agy-route entries
    only). ONE builder for both places that must say it: `retry` refuses on
    it BEFORE any allocation, and the collector puts it on a non-valid
    entry's reason, so the operator reads it in the collect report before
    reaching for `retry`.

    IT RUNS THE ROUND'S HOOK LOAD CHECK ITSELF (row r19-3). r18-2 mirrored the
    check by reading the round's AUDITS one by one, so every verdict decided
    by the HOOK LOG (a proven-unhooked stepped row, an anonymous hook row
    beside an unattributed one, a shared logged id, an unreadable log or a
    line that is not a hook row) and every OTHER entry's absent-with-spawn-
    line audit still let `retry` allocate a paid attempt that could never
    certify. Now the census is built exactly as the collector builds it for
    the entry — `_agy_round_audits` (every OTHER agy attempt of the round,
    absent ones included: `check_loaded` evaluates an absent audit by the
    spawn-line rule) — with the retried entry's recorded audit as the
    PRIMARY when it is present, else the first PRESENT sibling as primary and
    the own audit path among the siblings; the log is the round's hook log.
    `agy_hook.check_loaded` runs in-process (stdlib, importable).

    WHICH VERDICTS REFUSE. Every non-PASS verdict is PERMANENT by
    construction except two: a later attempt only ADDS a census row and hook
    rows — it cannot remove an anonymous hook row, un-share a logged id, hook
    a finished unhooked run, make an absent audit's spawn line disappear,
    complete an incomplete transcript, or repair an unreadable file. The
    first exception is "no hook invocation and NO census row with tool steps"
    (the check's INCONCLUSIVE "nothing proves or disproves the hook" — the
    brief called it the zero-invocation VOID with no stepped row): the
    retry's own hooked attempt adds the first stepped row and its hook rows,
    so it is allocated. (Residual, disclosed: that verdict also stays
    clearable when a zero-step row's id list is not whole — a shape the
    writer cannot produce, a zero-step run records no omitted ids.)

    THE SECOND IS NOT PERMANENT, IT IS NOT YET DECIDED (gate-1 r20 row
    r20-1): ANOTHER entry's CURRENTLY RECORDED attempt that was dispatched
    (its `stderr.log` carries the spawn line) and has no read audit may
    still be RUNNING — SKILL.md documents deciding a per-entry retry BEFORE
    the fold, while the other legs are out. The check reads it as the
    dispatched-no-audit INCONCLUSIVE, so the retry is still refused (exit 2,
    nothing allocated), but with a WAIT remedy: the round is re-checked
    without those in-flight attempts, and only when THAT check passes (or
    is the clearable verdict) is the refusal a wait — any other verdict is
    permanent whatever the in-flight legs do, and wins. A SUPERSEDED
    attempt of another entry, and every attempt of the retried entry
    itself, cannot be in flight, so they keep the permanent refusal. The
    check itself is unchanged; this guard only classifies its reason.
    THE WAIT IS A `retry`-TIME CLASSIFICATION ONLY (gate-1 r21 row r21-4):
    `collect` runs once every dispatched entry has TERMINATED (SKILL.md), so
    `_evaluate` passes `collecting=True` and such an attempt is one that
    RETURNED WITHOUT an audit — the permanent NEW-round text, never "may
    still be running".

    THE HOOK LOG IS VALIDATED FIRST, FOR EVERY ROUTE (gate-1 r20 row r20-4
    and the leader's R4b ruling): a record without an absolute `hook_log`
    refuses every retry — codex, claude or agy — whatever the audits show:
    `prepare` always writes one, and without it the collection stops on that
    same host fault, so any retry is a paid dispatch nobody can collect. It
    is the ONE check here that is not agy-only; everything below is.

    WHEN NO AUDIT OF THE ROUND IS PRESENT at all there is no primary to check;
    every absent attempt (the retried entry's own first) is read by the
    spawn-line rule the check would apply once the retry's audit exists: a
    dispatched attempt with no audit, or one whose `stderr.log` is
    unreadable, refuses (another entry's current dispatched attempt with a
    WAIT, as above); a never-dispatched allocation is retried."""
    hook_log = record.get("hook_log")
    if not isinstance(hook_log, str) or not os.path.isabs(hook_log):
        return ("a retry cannot certify this round: the round record names "
                "no absolute hook_log, so the round's hook load check "
                "cannot run (the collection stops on the same host fault) "
                "— prepare a NEW round (a fresh hook log)")
    if entry.get("route") != "agy":
        return None
    hook = _load_sibling("agy_hook")
    name = entry["name"]
    own = (Path(packet_dir) / record["results_dir"] / name
           / f"attempt-{attempt}" / "read-audit.json")
    everyone = [own, *_agy_round_audits(packet_dir, record, own)]
    # ANOTHER entry's CURRENTLY RECORDED attempt (row r20-1): the only
    # attempts that may still be running when `retry` is called — none at
    # collect time, when every dispatched entry has terminated (row r21-4)
    current = {}
    for other in ([] if collecting else _dispatched(record)):
        other_attempt = other.get("attempt")
        if (other.get("route") != "agy" or other.get("name") == name
                or not isinstance(other_attempt, int)
                or isinstance(other_attempt, bool)):
            continue
        current[str(Path(packet_dir) / record["results_dir"] / other["name"]
                     / f"attempt-{other_attempt}" / "read-audit.json")] = (
            other["name"], other_attempt)
    in_flight = [a for a in everyone
                 if str(a) in current and not os.path.lexists(a)
                 and hook._spawned(a.parent / "stderr.log")[0] is True]
    census = [a for a in everyone if a not in in_flight]
    present = [a for a in census if os.path.lexists(a)]
    why = None
    if not present:
        for audit in census:
            spawned, unread = hook._spawned(audit.parent / "stderr.log")
            if spawned is None:
                why = (f" — {audit} wrote no read audit and its stderr.log "
                       f"{unread}, so whether it was DISPATCHED is unknown "
                       f"(the hook check reads it as INCONCLUSIVE); prepare a "
                       f"NEW round (a fresh hook log)")
                break
            if spawned:
                why = (f" — {audit} was DISPATCHED (its stderr.log carries the "
                       f"engine's spawn line) but wrote no read audit, so no "
                       f"conversation id records its run (the hook check reads "
                       f"it as INCONCLUSIVE); prepare a NEW round (a fresh hook "
                       f"log)")
                break
        verdict = "INCONCLUSIVE"
    else:
        primary = present[0]
        res = hook.check_loaded(primary, Path(hook_log),
                                [a for a in census if a != primary])
        verdict, guidance = res[0], res[3]
        # PASS, or the ONE clearable verdict (see the docstring): nothing
        # logged and no census row with tool steps anywhere in the round
        if verdict != "PASS" and not (len(res) > 8 and res[5] == 0
                                      and res[8] == 0):
            why = _guidance(f"[review] agy hook load check {verdict} — "
                            f"{guidance or ''}")
    if why is not None:
        return (f"a retry cannot certify this round: the round's hook load "
                f"check is {verdict}, and a later attempt only ADDS a census "
                f"row and hook rows (it deletes none), so every agy leg would "
                f"stay {verdict}{why}")
    if not in_flight:
        return None
    named = ", ".join(f"attempt {current[str(a)][1]} of {current[str(a)][0]}"
                      for a in in_flight)
    one = len(in_flight) == 1
    return (f"a retry cannot certify this round yet: {named} "
            f"{'was' if one else 'were'} dispatched and "
            f"{'has' if one else 'have'} not written "
            f"{'its' if one else 'their'} read audit yet — "
            f"{'it' if one else 'they'} may still be running; wait for "
            f"{'it' if one else 'them'} to return, then retry; prepare a NEW "
            f"round only if {'it' if one else 'one'} returned WITHOUT an audit")


def _agy_evidence_reason(packet_dir: Path, record: dict,
                         attempt_dir: Path) -> str | None:
    """None when this agy attempt's containment evidence holds, else the
    one-line reason it does not. BOTH checks run exactly as `prepare --v2`
    printed them — same audit file, same required-read set, same hook log.

    A `_EVIDENCE_TOOL_HOST_RC` from EITHER tool is a `_HostFault`, never this
    entry's `invalid` (gate-1 r8 row r8-9). Both reserve that code for "this
    invocation could not RUN at all" — a required file the round named is
    gone (a worktree re-pinned between prepare and collect), an absent
    `hook_log`, an unusable argv. Recording it per-entry folded the round to
    INCOMPLETE, which is the leader's instruction to RE-DISPATCH THE PAID
    LEGS over a fault that says nothing about any leg: the r7-7 / r7-c4 class
    reached through the other two evidence tools."""
    audit = attempt_dir / "read-audit.json"
    custody = _agy_custody_reason(attempt_dir, audit)
    if custody is not None:
        return custody
    gate = _run(["bash", str(LIB_DIR / "read_audit_gate.sh"),
                 "--audit-file", str(audit), str(packet_dir),
                 *[str(f) for f in record.get("gate_files", [])]])
    if gate.returncode == _EVIDENCE_TOOL_HOST_RC:
        raise _HostFault(
            f"the read-audit gate could not RUN on this host "
            f"({_token(gate.stdout, 'READ_AUDIT_GATE_')}; "
            f"{' '.join((gate.stderr or '').split())[:200]}) — that is a "
            f"USAGE/HOST fault (a required file the round named is gone, a "
            f"re-pinned worktree, an unusable argv), not a verdict about "
            f"this leg; the collection is STOPPED and no per-entry state was "
            f"written, so repair the host and collect again rather than "
            f"re-dispatching the legs")
    if gate.returncode != 0:
        return (f"read-audit gate failed "
                f"({_token(gate.stdout, 'READ_AUDIT_GATE_')}, rc={gate.returncode})"
                f"{_guidance(gate.stderr)}"
                f" — an ungated agy answer is UNVERIFIED, never agreement")
    hook = _run(["python3", str(LIB_DIR / "agy_hook.py"), "check",
                 str(audit), str(record.get("hook_log", "")),
                 *[str(p) for p in _agy_round_audits(packet_dir, record, audit)]])
    if hook.returncode == _EVIDENCE_TOOL_HOST_RC:
        raise _HostFault(
            f"the agy hook load check could not RUN on this host "
            f"({_token(hook.stdout, 'HOOK_LOAD_')}; "
            f"{' '.join((hook.stderr or '').split())[:200]}) — that is a "
            f"USAGE/HOST fault (an absent `hook_log` in the round record, a "
            f"non-absolute path, an unusable argv), not a verdict about this "
            f"leg; the collection is STOPPED and no per-entry state was "
            f"written, so repair the host and collect again rather than "
            f"re-dispatching the legs")
    if hook.returncode != 0:
        return (f"hook load check failed "
                f"({_token(hook.stdout, 'HOOK_LOAD_')}, rc={hook.returncode})"
                f"{_guidance(hook.stderr)}"
                f" — agy's --agent fails OPEN, so an unproven hook layer "
                f"leaves this leg's containment unverified")
    return None


def _expected_binding(record: dict, entry: dict, attempt: int) -> dict:
    """The SIX values an attempt's `binding.json` must EQUAL, derived from
    outside the attempt directory (row r5-1): `review_id` / `content_digest`
    from the ROUND RECORD, `family` / `leg_name` / `route` from the round's
    FROZEN ROSTER ENTRY, `attempt` from the DIRECTORY NAME the caller parsed.

    ONE derivation for both readers (gate-1 r6 row r6-3). `_evaluate` compared
    all six while adoption compared only four — `family` and `route` were
    never checked there, so an orphan whose own binding claimed another
    family, or a gemini route for the agy-routed entry, was ADOPTED and then
    dispatched, gated and admitted under the entry it had been dropped into.
    Two copies of one rule is how they diverged; this is the single copy."""
    return {"review_id": record.get("review_id"),
            "family": entry.get("family", entry["vendor"]),
            "content_digest": record.get("content_digest"),
            "leg_name": entry["name"],
            "attempt": attempt,
            "route": entry.get("route")}


def _sealed_paths(attempt_dir: Path, entry: dict) -> dict:
    """The three files a recorded attempt's seal binds, DERIVED from the
    round's frozen roster entry (never read back from the seal — the r5-1
    rule): the RESULT the collector admits, the RECEIPT of the dispatch that
    produced it (the native leg's verbatim raw reply, a wrapper leg's
    stderr), and the READ EVIDENCE (the agy route's read audit; no other
    route writes any, so None). A wrapper route adds its RUN LOG: the
    directory holding the wrapper's executed-command receipt (R-BIND),
    digested over its `*.json` run-logs only (`_bound_digest`)."""
    family = entry.get("family", entry["vendor"])
    paths = {"result": attempt_dir / _result_filename(family),
             "receipt": attempt_dir / ("raw.json" if family == "claude"
                                       else "stderr.log"),
             "read_evidence": (attempt_dir / "read-audit.json"
                               if entry.get("route") == "agy" else None)}
    if family != "claude":
        paths["run_log"] = (attempt_dir / "logs"
                            / _RUN_LOG_CLI[entry.get("route")] / "runs")
    return paths


def _seal_digest(path: Path) -> str | None:
    """sha256 of a sealed file, None when it is absent; anything that is not a
    plain regular file is a `CollectError` naming it."""
    if not os.path.lexists(path):
        return None
    try:  # STREAMED, never capped: a seal binds every byte it judged (M6)
        if not stat.S_ISREG(os.lstat(path).st_mode):
            _read_regular_file(path, "the sealed file")  # raises, naming it
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                raise OSError("not a regular file")
            return hashlib.file_digest(fh, "sha256").hexdigest()
    except OSError as exc:
        raise CollectError(f"the sealed file {path} is unreadable "
                           f"({' '.join(str(exc).split())})") from exc


def _bound_digest(role: str, path: Path) -> str | None:
    """`_seal_digest`, except for the run-log role when it is a directory:
    the sha256 over the name and `_seal_digest` of each `*.json` run-log in
    it (exactly the files the receipt reader reads), in name order."""
    if role != "run_log" or os.path.islink(path) or not os.path.isdir(path):
        return _seal_digest(path)
    try:
        names = sorted(e.name for e in os.scandir(path)
                       if e.name.endswith(".json"))
        return hashlib.sha256("".join(
            f"{n}\0{_seal_digest(path / n)}\n" for n in names
        ).encode("utf-8", "surrogateescape")).hexdigest()
    except (OSError, CollectError) as exc:
        raise CollectError(f"the run-log under {path} cannot be read "
                           f"({' '.join(str(exc).split())})") from exc


def _seal_files(attempt_dir: Path, entry: dict,
                as_found: bool = False) -> dict:
    """`{role: None | [file name, sha256 | None]}` for the files a seal binds,
    as they are NOW (a `CollectError` names one that cannot be read; with
    `as_found`, retry's record of a replaced attempt, it is `_UNREADABLE`)."""
    def digest(role, path):
        try:
            return _bound_digest(role, path)
        except CollectError:
            if not as_found:
                raise
            return _UNREADABLE
    return {role: (None if path is None else [path.name, digest(role, path)])
            for role, path in _sealed_paths(attempt_dir, entry).items()}


def _write_seal(attempt_dir: Path, entry: dict, attempt: int, files: dict,
                state: str, replace: bool = False) -> None:
    """SEAL the attempt this collection records (R-BIND, case C66), with the
    digests of the bytes this collection JUDGED (`files`) and the state it
    judged them in — `valid`, or `invalid` for an answer that was not
    admissible (a retry stays open for that one: it did not return a valid
    verdict, R-RETRY).

    Written ONCE: exclusive-created through a pid-unique temp file and a hard
    link, so an existing seal — or anything planted at its name — is never
    replaced (`replace`: retry completing a refused reply's cut-short seal,
    V2). A refusal is a `CollectError` naming the attempt."""
    doc = {"schema_version": 1, "leg_name": entry["name"], "attempt": attempt,
           "state": state, "files": files}
    target = attempt_dir / _SEAL_NAME
    tmp = attempt_dir / f".tmp-{os.getpid()}-{_SEAL_NAME}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                     | getattr(os, "O_NOFOLLOW", 0), 0o644)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(doc, indent=2, sort_keys=True) + "\n")
            (os.replace if replace else os.link)(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    except OSError as exc:
        raise CollectError(
            f"the seal {target} of {entry['name']!r} attempt {attempt} could "
            f"not be written ({' '.join(str(exc).split())}) — a result is "
            f"recorded only together with its seal; inspect that attempt "
            f"directory, then collect again") from exc


def _seal_replaced(attempt_dir: Path, entry: dict, attempt: int,
                   found: dict, state: str, expected: dict) -> None:
    """RECORD the attempt a retry replaces (R-BIND, case C66; host B's
    FAILED_TO_RUN / INVALID terminals): seal it in the `state` retry's
    judgement gave over `found`, the as-found digests taken BEFORE that
    judgement (V1) — an empty or absent result included — so a late write
    into it is an integrity failure, never an unjudged answer. A write that
    landed while retry judged it refuses the retry. An existing seal is
    kept, except a refused reply's cut-short seal, which binds nothing: it
    is completed over what the attempt holds, still `invalid` (V2) — only
    while raw.json is not admissible against `expected`; an admissible one
    (saved after the refusal) must be judged, so the retry refuses (G4).
    Runs before the next attempt is allocated; a refusal allocates nothing."""
    stub = os.path.lexists(attempt_dir / _SEAL_NAME)
    if stub:
        try:
            _read_seal(attempt_dir / _SEAL_NAME)
            return
        except CollectError:
            if not _refusal_cut_short(attempt_dir):
                return
            if stat.S_ISDIR(os.lstat(attempt_dir / _SEAL_NAME).st_mode):
                raise CollectError(_SEAL_DIR.format(
                    attempt=attempt, seal=attempt_dir / _SEAL_NAME)
                    + "; nothing was allocated")
        state = "invalid"
    if _seal_files(attempt_dir, entry, as_found=True) != found:
        raise CollectError(f"attempt {attempt} changed while retry judged it "
                           f"(a leg still running wrote into it) — nothing "
                           f"was sealed or allocated; collect again")
    if stub and _raw_admissible(attempt_dir, expected):
        # Y1: the helper-written stub is removed here, never by hand; a stop
        # after the removal leaves a reply saved but never admitted (M1).
        try:
            os.unlink(attempt_dir / _SEAL_NAME)
        except OSError as exc:
            raise CollectError(
                f"attempt {attempt}: raw.json holds an admissible reply beside "
                f"a cut-short seal that could not be removed "
                f"({' '.join(str(exc).split())}) — nothing was allocated; free "
                f"the cause and retry again") from exc
        raise CollectError(
            f"attempt {attempt}: the refused reply's seal was cut short and "
            f"raw.json now holds an admissible reply (saved after the "
            f"refusal), which must be judged — the cut-short seal was removed "
            f"and nothing was allocated; run the printed `admit:` line for "
            f"this attempt, then collect again")
    try:
        _write_seal(attempt_dir, entry, attempt, found, state, replace=stub)
    except CollectError as exc:
        why = " ".join(str(exc.__cause__ or exc).split())
        raise CollectError(f"attempt {attempt} could not be recorded before "
                           f"it is replaced ({why}) — nothing was allocated; "
                           f"free the cause and retry again") from exc


def _read_seal(seal: Path) -> tuple:
    """`(raw bytes, document)` of a seal, or a `CollectError` naming it."""
    raw = _read_regular_file(seal, "the attempt seal")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError, UnicodeDecodeError) as exc:
        raise CollectError(f"the attempt seal {seal} is unreadable "
                           f"({' '.join(str(exc).split())})") from exc
    if not isinstance(doc, dict):
        raise CollectError(f"the attempt seal {seal} is not an object")
    return raw, doc


def _recorded_seals(packet_dir: Path, label: str) -> dict:
    """`{entry name: {attempt: sha256 of its seal}}` from the round's own
    collection record — what an earlier collection already RECORDED (case
    C66, K2). A seal missing or changed under an attempt the record names
    is an integrity failure, never "not recorded yet". An absent record is
    `{}`; a record this helper cannot read refuses the command."""
    path = Path(packet_dir) / f"collect-{label}.json"
    if not os.path.lexists(path):
        return {}
    try:
        doc = json.loads(_read_regular_file(path, "the collection record")
                         .decode("utf-8"))
        out = {}
        for e in doc["entries"]:
            seals = e.get("seals") or {}
            out[e["name"]] = {int(k): v for k, v in seals.items()
                              if isinstance(v, str)}
        return out
    except CollectError as exc:
        raise CollectError(f"{' '.join(str(exc).split())} — it holds the "
                           f"seals this round already recorded; prepare a "
                           f"new round") from exc
    except (ValueError, RecursionError, UnicodeDecodeError, KeyError,
            TypeError, AttributeError) as exc:
        raise CollectError(
            f"the collection record {path} is unreadable "
            f"({' '.join(str(exc).split())}) — it holds the seals this round "
            f"already recorded; prepare a new round") from exc


def _refusal_cut_short(attempt_dir: Path) -> bool:
    """A native refused reply whose seal write was cut short (M2): the
    admission creates that seal at its final name, so its unreadable seal
    sits beside a raw reply and NO admitted result — a valid seal is always
    linked whole, after its result."""
    return (os.path.lexists(attempt_dir / "raw.json")
            and not os.path.lexists(attempt_dir / "admitted.json"))


def _raw_unusable(attempt_dir: Path) -> str | None:
    """Why raw.json is not a reply the admission can judge (P4: a link, a
    directory, an unreadable path), else None."""
    raw = attempt_dir / "raw.json"
    try:
        if not stat.S_ISREG(os.lstat(raw).st_mode):
            return f"{raw} is not a readable regular file (a link or a directory)"
    except OSError:
        return None
    return None if os.access(raw, os.R_OK) else (
        f"{raw} is not a readable regular file (unreadable)")


def _raw_admissible(attempt_dir: Path, expected: dict) -> bool:
    """True when the native admission, re-run on raw.json as it is now,
    admits it against `expected` (G4)."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return _load_sibling("verdict_v2")._admit_raw_with_text(
                _read_regular_file(attempt_dir / "raw.json", "the native "
                                   "reply").decode("utf-8"), expected,
                _load_sibling("review_scratch")._V2_END_MARKER)[0].ok
    except (CollectError, UnicodeDecodeError):
        return False


def _saved_not_admitted(attempt_dir: Path,
                        expected: dict | None = None) -> str | None:
    """Why a native reply saved in a regular raw.json, with no seal, was
    never admitted, else None: no admitted.json (M1, `_ADMIT_FIRST`), or —
    given `expected` — a regular admitted.json the admission refuses (empty
    included) beside an admissible raw.json its own binding.json binds (G2,
    `_ADMIT_BAD`) — or an admitted.json that is not a readable regular
    file (a link, a directory, unreadable, over the cap), beside which the
    reply can never be admitted (Z1: a new round)."""
    if (not os.path.lexists(attempt_dir / "raw.json")
            or os.path.lexists(attempt_dir / _SEAL_NAME)
            or _raw_unusable(attempt_dir) is not None):
        return None
    admitted = attempt_dir / "admitted.json"
    if not os.path.lexists(admitted):
        return _ADMIT_FIRST
    if expected is None:
        return None
    vv = _load_sibling("verdict_v2")
    unreadable = vv._read_regular_file_no_symlink(admitted)[1]
    if unreadable is not None:
        return (f"the reply was saved (raw.json) but the attempt's "
                f"admitted.json is not a readable file ({unreadable}), so "
                f"that reply can never be admitted into this attempt — "
                f"prepare a new round")
    if vv._attempt_binding(attempt_dir / "raw.json", expected)[1] is not None:
        return None
    admission = vv.admit_file(admitted, expected)
    if (admission.ok or admission.exit_code == vv.EXIT_USAGE
            or not _raw_admissible(attempt_dir, expected)):
        return None
    return f"{_ADMIT_BAD} ({admission.reason})"


def _unbound_reason(by_number: dict, record: dict, entry: dict,
                    attempt: int) -> str | None:
    """Why attempt 1's or the recorded `attempt`'s binding.json (those of
    `by_number`, `{number: attempt dir}`, on disk) does not equal the
    derivation (edited, copied in, unreadable, removed), else None (Z6, R3).

    THE EXPECTED SIX ARE DERIVED, NEVER READ BACK (gate-1 r5 row r5-1): a
    `binding.json` + result copied together from another entry's attempt
    used to validate each other; a binding that disagrees is an attempt
    that does not belong to this entry. The binding no longer names this
    entry, so no answer in that attempt can be credited to it — whichever
    attempt it is (host B refuses the same retry) — and neither the admit
    line nor a retry helps: `collect` and `retry` both name a new round.
    Attempt 1's binding.json is round evidence too (censused at prepare, no
    seal binds it), so an edit to it after a retry refuses the same way."""
    for number in sorted({1, attempt} & set(by_number)):
        binding_path = by_number[number] / "binding.json"
        expected = _expected_binding(record, entry, number)
        try:
            # A FIFO or a link at this helper-owned name is refused by the
            # reader (r10-7); RecursionError is not a ValueError (r7-k3).
            binding = json.loads(
                _read_regular_file(binding_path, "the binding record")
                .decode("utf-8"))
        except CollectError as exc:
            cause = f"binding record unreadable: {' '.join(str(exc).split())}"
        except (OSError, ValueError, RecursionError) as exc:
            cause = (f"binding record unreadable: {binding_path} "
                     f"({' '.join(str(exc).split())})")
        else:
            drift = (sorted(f for f, want in expected.items()
                            if binding.get(f) != want)
                     if isinstance(binding, dict) else None)  # r6-4: `null`
            if drift == []:
                continue
            cause = (f"binding record is not an object "
                     f"({type(binding).__name__}): {binding_path}"
                     if drift is None else
                     f"binding mismatch: {', '.join(drift)} — {binding_path} "
                     f"does not bind this entry at attempt {number} (the "
                     f"round record, the frozen roster entry and the "
                     f"directory name decide, never the binding's own copy)")
        return f"{cause} — {_UNBOUND_TAIL}"
    return None


_UNBOUND_TAIL = "the binding no longer binds this entry — prepare a new round"


# V4: a directory at seal.json can be neither taken away nor completed by
# any step, so the reply beside it can never be judged in this attempt.
_SEAL_DIR = ("attempt {attempt}: {seal} is a directory, not a seal — no step "
             "takes it away or completes it, so this attempt can never be "
             "judged — prepare a new round")


_ADMIT_FIRST = ("the reply was saved (raw.json) but never admitted — run the "
                "printed `admit:` line for this attempt, then collect again")
# G2: an admitted.json the admission never wrote (a leader's `> admitted.json`
# redirect) hides the saved reply the same way; the admit line refuses it, so
# `retry` takes it away (Y1).
_ADMIT_BAD = ("the reply was saved (raw.json) but never admitted: the "
              "admitted.json beside it is not its admitted result — `retry` "
              "this entry (it takes that file away and allocates nothing), "
              "then run the printed `admit:` line for this attempt and "
              "collect again")


def _seal_reason(attempt_dir: Path, entry: dict, attempt: int,
                 recorded_sha: str | None = None,
                 earlier: bool = False,
                 expected: dict | None = None) -> str | None:
    """None when the attempt is unsealed and no collection recorded it, or
    every file its seal bound still holds the recorded bytes; else the
    integrity failure.

    A recorded attempt is sealed (R-BIND, case C66): a change, removal or
    replacement of its result, receipt, read evidence or seal after the
    record is refused, never re-admitted — the entry is INVALID, so the round
    can never be AGREED on it. `recorded_sha` is the seal digest the round's
    collection record holds for this attempt (K2). `earlier` (the history
    check) passes a refused reply's cut-short seal: its retry is open (M2);
    with `expected`, one beside an admissible raw.json names retry and the
    admit line, as `retry` does (G4)."""
    seal = attempt_dir / _SEAL_NAME
    head = f"integrity failure: attempt {attempt} is sealed but"
    if not os.path.lexists(seal):
        if recorded_sha is None:
            return None
        return (f"integrity failure: attempt {attempt} was recorded by an "
                f"earlier collection (its seal sha256 {recorded_sha}) but the "
                f"seal {seal} is gone — {_SEAL_REMEDY}")
    try:
        raw, doc = _read_seal(seal)
    except CollectError as exc:
        if _refusal_cut_short(attempt_dir):
            if earlier:
                return None
            if stat.S_ISDIR(os.lstat(seal).st_mode):
                return _SEAL_DIR.format(attempt=attempt, seal=seal)
            if expected is not None and _raw_admissible(attempt_dir, expected):
                return (f"attempt {attempt}: the admission refused its reply "
                        f"and its seal could not be written in full, and "
                        f"raw.json now holds an admissible reply (saved after "
                        f"the refusal), which must be judged — `retry` this "
                        f"entry (it takes that seal away and allocates "
                        f"nothing), then run the printed `admit:` line for "
                        f"this attempt and collect again")
            return (f"attempt {attempt}: the admission refused its reply and "
                    f"its seal could not be written in full (the attempt is "
                    f"closed to any other reply); diagnose it, then retry "
                    f"this entry")
        return f"{head} {' '.join(str(exc).split())} — {_SEAL_REMEDY}"
    if (recorded_sha is not None
            and hashlib.sha256(raw).hexdigest() != recorded_sha):
        return (f"{head} its seal {seal} changed since a collection recorded "
                f"it (recorded sha256 {recorded_sha}) — {_SEAL_REMEDY}")
    derived = _sealed_paths(attempt_dir, entry)
    files = doc.get("files")
    shaped = (isinstance(files, dict) and set(files) == set(derived)
              and doc.get("leg_name") == entry["name"]
              and doc.get("attempt") == attempt
              and doc.get("state") in ("valid", "invalid", "failed-to-run")
              and all((files[role] is None) if path is None
                      else (isinstance(files[role], list)
                            and len(files[role]) == 2
                            and files[role][0] == path.name)
                      for role, path in derived.items()))
    if not shaped and isinstance(files, dict) and "run_log" not in files \
            and set(files) | {"run_log"} == set(derived):
        return (f"attempt {attempt} was sealed before a host change (the "
                f"run-log receipt binding) and cannot be judged under it — "
                f"prepare a new round")
    if not shaped:
        return (f"{head} its seal {seal} does not bind this entry's result, "
                f"receipt and read evidence at this attempt — {_SEAL_REMEDY}")
    broken = []
    for role, path in derived.items():
        if path is None:
            continue
        sealed = files[role][1]
        try:
            now = _bound_digest(role, path)
        except CollectError as exc:
            if sealed == _UNREADABLE:
                continue  # still unreadable, as retry found it
            broken.append(f"its {role.replace('_', ' ')} "
                          f"{' '.join(str(exc).split())}")
            continue
        if now == sealed:
            continue
        what = ("was removed" if now is None
                else "appeared" if sealed is None else "changed")
        broken.append(f"its {role.replace('_', ' ')} {path} {what} since it "
                      f"was recorded (sealed sha256 {sealed}, now {now})")
    if not broken:
        return None
    return f"{head} {'; '.join(broken)} — {_SEAL_REMEDY}"


def _sealed_valid_reason(attempt_dir: Path, attempt: int,
                         recorded_sha: str | None) -> str | None:
    """None unless the attempt is RECORDED as completed work: sealed with a
    valid answer, or sealed / recorded in a way that cannot be proven to be
    an inadmissible answer (unreadable, changed, gone). Used by `retry` and
    the history check — an attempt that returned a valid verdict is never a
    failure to run (R-RETRY, case C66)."""
    seal = attempt_dir / _SEAL_NAME
    if not os.path.lexists(seal) and recorded_sha is None:
        return None
    try:
        raw, doc = _read_seal(seal)
    except CollectError as exc:
        if _refusal_cut_short(attempt_dir):
            return None  # a refused reply is no answer: retry stays open
        return (f"attempt {attempt} was recorded and its seal cannot be read "
                f"({' '.join(str(exc).split())})")
    if (recorded_sha is not None
            and hashlib.sha256(raw).hexdigest() != recorded_sha):
        return (f"attempt {attempt} is sealed and its seal changed since a "
                f"collection recorded it")
    if doc.get("state") not in ("invalid", "failed-to-run"):
        return (f"attempt {attempt} is sealed: a valid answer was recorded "
                f"for it")
    return None


def _history_reason(entry_dir: Path, by_number: dict, record_attempt: int,
                    recorded: dict | None, entry: dict) -> str | None:
    """None when every attempt BEFORE the recorded one is a diagnosed
    failed-to-run terminal; else the refusal (R-BIND, R-RETRY, case C66).

    A failed-to-run terminal on this host is an attempt directory that
    `retry` diagnosed — a non-blank `retry-diagnosis.txt`, written only for
    an attempt that returned no valid verdict — and that is not RECORDED as
    a valid answer (`_sealed_valid_reason`; `recorded` is this entry's
    `{attempt: seal sha256}` from the collection record) — and that is
    SEALED with every file it bound unchanged (`retry` seals the attempt it
    replaces, R1). Anything else behind the recorded attempt means the
    record moved past an answer, so the history is refused."""
    tail = (f"collection evaluates the recorded attempt {record_attempt} only "
            f"behind earlier attempts that FAILED TO RUN and were diagnosed by "
            f"`retry` (R-BIND, R-RETRY, case C66) — prepare a new round")
    for number in range(1, record_attempt):
        earlier = by_number.get(number)
        if earlier is None:
            return (f"earlier attempt {number} is not on disk "
                    f"({entry_dir}/attempt-{number}) — {tail}")
        if _saved_not_admitted(earlier):
            return (f"earlier attempt {number}: {_ADMIT_FIRST} (an unjudged "
                    f"reply blocks agreement on a later attempt)")
        sealed = _sealed_valid_reason(earlier, number,
                                      (recorded or {}).get(number))
        if sealed is not None:
            return (f"earlier {sealed}, so it is not a failed-to-run "
                    f"terminal — {tail}")
        if not os.path.lexists(earlier / _SEAL_NAME):
            return (f"earlier attempt {number} is not sealed (`retry` records "
                    f"the attempt it replaces) — {tail}")
        changed = _seal_reason(earlier, entry, number,
                               (recorded or {}).get(number), earlier=True)
        if changed is not None:
            return f"earlier attempt {number}: {changed}"
        diagnosis = earlier / "retry-diagnosis.txt"
        try:
            text = _read_regular_file(diagnosis, "the retry diagnosis")
        except CollectError as exc:
            return (f"earlier attempt {number} carries no usable retry "
                    f"diagnosis ({' '.join(str(exc).split())}) — {tail}")
        if not text.decode("utf-8", errors="replace").strip():
            return (f"earlier attempt {number} carries a blank retry "
                    f"diagnosis ({diagnosis}) — {tail}")
    return None


def _readmission_reason(attempt_dir: Path, record: dict, entry: dict,
                        attempt: int, files: dict) -> str | None:
    """None when the native attempt's unsealed `admitted.json` is the
    admission of the `raw.json` beside it (the same admission code path,
    re-run), both as judged (`files`); else the integrity failure (R2: a
    second reply saved over the receipt before the seal)."""
    raw_path = attempt_dir / "raw.json"
    try:
        raw = _read_regular_file(raw_path, "the native reply")
        admitted = _read_regular_file(attempt_dir / "admitted.json",
                                      "the admitted result")
        with contextlib.redirect_stderr(io.StringIO()):
            _, text = _load_sibling("verdict_v2")._admit_raw_with_text(
                raw.decode("utf-8"), _expected_binding(record, entry, attempt),
                _load_sibling("review_scratch")._V2_END_MARKER)
    except (CollectError, UnicodeDecodeError):
        text = None
    if (text is not None and text.encode("utf-8") == admitted
            and hashlib.sha256(raw).hexdigest() == files["receipt"][1]
            and hashlib.sha256(admitted).hexdigest() == files["result"][1]):
        return None
    return (f"integrity failure: attempt {attempt}'s admitted result is not "
            f"the admission of the reply {raw_path} beside it (a reply was "
            f"saved over the admitted one before its seal), so no record can "
            f"show which reply was judged — prepare a new round")


def _evaluate(packet_dir: Path, record: dict, entry: dict,
              recorded: dict | None = None,
              label: str | None = None) -> EntryResult:
    """ONE entry's state at the attempt the ROUND RECORD names — the single
    place `collect` and `retry` both read, so the two can never disagree
    about whether a leg returned a verdict.

    THE RECORD NAMES THE ATTEMPT, IN BOTH DIRECTIONS (gate-1 r10 row r10-2,
    completing r9-2). The r9-2 gate read `attempts[-1]` and refused only a
    HIGHER on-disk directory, so the ROLLBACK direction stayed open: with
    the record naming attempt 2 and only `attempt-1/` surviving, the
    SUPERSEDED attempt's verdict decided the entry — a SAFE attempt 1 behind
    a failed, then removed, attempt 2 collected as AGREEMENT. Allocation is
    the record's act, so exactly `attempt-<record.attempt>/` is evaluated
    and a recorded attempt the tree does not hold is this entry's `invalid`.

    The r9-2 DISCLOSURE survives on top of it: an attempt numbered above the
    record's is one this round never allocated, and it is still refused BY
    NAME — but only when the recorded attempt did not itself return a valid
    verdict. A completed review is the strongest evidence this entry has and
    an unallocated directory can no longer displace it (it is never read),
    so refusing there would only let a planted directory VETO the verdict —
    and, through `retry`'s adoption path, PROMOTE the record past it (row
    r10-1). Nothing is deleted on either arm."""
    name = entry["name"]
    base = EntryResult(name=name, family=entry.get("family", entry["vendor"]),
                       route=entry.get("route"),
                       acceptance=entry.get("acceptance", ""),
                       attempt=None, state="missing")
    entry_dir = Path(packet_dir) / record["results_dir"] / name
    try:
        attempts = _attempts(entry_dir)
    except CollectError as exc:
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": " ".join(str(exc).split())})
    # A positive int on every DISPATCHED entry, proven by `_check_record_shape`
    # (row r10-2) — and `_dispatched` / `retry` are the only two callers.
    record_attempt = entry["attempt"]
    base = EntryResult(**{**base.__dict__, "attempt": record_attempt})
    by_number = dict(attempts)
    attempt_dir = by_number.get(record_attempt)
    if attempt_dir is None:
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": f"the round record names attempt "
                                        f"{record_attempt} for this entry and "
                                        f"{entry_dir}/attempt-{record_attempt}"
                                        f" is not on disk — the collector "
                                        f"evaluates the attempt this round "
                                        f"allocated, never another one the "
                                        f"tree happens to hold; prepare a new "
                                        f"round"})
    # C66 (R-BIND, R-RETRY): the recorded attempt is evaluated only behind a
    # history of diagnosed failed-to-run attempts, and only while the files
    # its seal bound are the ones it was recorded with.
    own = (recorded or {}).get(name, {})
    refused = (_history_reason(entry_dir, by_number, record_attempt, own,
                               entry)
               or _unbound_reason(by_number, record, entry, record_attempt)
               or _seal_reason(attempt_dir, entry, record_attempt,
                               own.get(record_attempt),
                               expected=_expected_binding(record, entry,
                                                          record_attempt)))
    result_path = str(attempt_dir / _result_filename(base.family))
    if refused is not None:
        result = EntryResult(**{**base.__dict__, "state": "invalid",
                                "reason": refused,
                                "result_path": result_path})
    elif os.path.lexists(attempt_dir / _SEAL_NAME):
        sealed = _read_seal(attempt_dir / _SEAL_NAME)[1]
        if sealed["state"] == "failed-to-run":
            result = EntryResult(**{**base.__dict__, "state": "invalid",
                                    "reason": "`retry` recorded this attempt "
                                              "as failed to run (its next "
                                              "attempt was not recorded); "
                                              "retry this entry again",
                                    "result_path": result_path})
        elif sealed["state"] == "invalid" and sealed["files"]["result"][1] is None:
            # The native admission refused this reply and sealed it (C66).
            result = EntryResult(**{**base.__dict__, "state": "invalid",
                                    "reason": "the admission refused this "
                                              "reply and sealed the attempt "
                                              "invalid (no admitted result); "
                                              "diagnose it, then retry this "
                                              "entry",
                                    "result_path": result_path})
        else:
            # A seal that recorded a VALID answer was judged with its receipt
            # once, at the seal; it is never re-judged by it (C66).
            result = _evaluate_recorded(packet_dir, record, entry,
                                        attempt_dir, base,
                                        receipt=sealed["state"] != "valid")
    elif base.family == "claude" and (unjudged := _saved_not_admitted(
            attempt_dir, _expected_binding(record, entry, record_attempt))):
        result = EntryResult(**{**base.__dict__, "state": "invalid",
                                "reason": unjudged,
                                "result_path": result_path})
    elif (base.family == "claude" and _refusal_cut_short(attempt_dir)
            and (unusable := _raw_unusable(attempt_dir))):
        result = EntryResult(**{**base.__dict__, "state": "invalid",
                                "reason": f"{unusable}: the admission refuses "
                                          f"it; diagnose it, then retry this "
                                          f"entry",
                                "result_path": result_path})
    else:
        result = _evaluate_unsealed(packet_dir, record, entry, attempt_dir,
                                    base, result_path)
    if result.state != "valid":
        # gate-1 r17 row r17-4 / r18 row r18-2 / r19 row r19-3: say BEFORE
        # the operator reaches for `retry` that a retry cannot certify this
        # round (`retry` refuses on the same sentence: the round's own hook
        # load check, run by `_retry_cannot_certify`).
        # collecting=True (gate-1 r21 row r21-4): at collect time every
        # dispatched entry has terminated, so an absent-with-spawn-line
        # attempt RETURNED without an audit — never the retry-time WAIT
        blind = _retry_cannot_certify(packet_dir, record, entry,
                                      record_attempt, collecting=True)
        if blind is not None:
            result = EntryResult(**{**result.__dict__, "reason": (
                blind if result.reason is None
                else f"{result.reason} — {blind}")})
    unallocated = [n for n, _ in attempts if n > record_attempt]
    blocked = (_adoption_blocked(packet_dir, label, record, entry, attempts,
                                 own, lambda: blind, result, collecting=True)
               if result.state != "valid" and unallocated else None)
    if blocked is not None:
        # V2: `retry` refuses before any adoption, so the reason keeps its
        # cause first and names retry's own remedy, never the adoption.
        # W1: retry's refusal (its cause and remedy) is the line; the
        # recorded attempt contributes its state only, never a remedy of
        # its own that the refused retry would contradict.
        kind, _, refusal = blocked
        tail = ("" if kind in ("admit", "take")
                or "prepare a new round" in refusal.lower()
                else " — prepare a new round")
        return EntryResult(**{**result.__dict__, "reason": (
            f"{refusal}{tail} (also: {entry_dir}/attempt-{unallocated[-1]} "
            f"is an attempt this round never allocated; the recorded attempt "
            f"{record_attempt} is {result.state})")})
    if result.state != "valid" and unallocated:
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": f"{entry_dir}/attempt-"
                                        f"{unallocated[-1]} is an attempt "
                                        f"this round never allocated: the "
                                        f"round record names attempt "
                                        f"{record_attempt} for this entry "
                                        f"(evaluated: {result.state}"
                                        f"{'' if result.reason is None else ' — ' + result.reason}"
                                        f"). An attempt directory is one "
                                        f"this helper allocated (prepare) or "
                                        f"adopted (retry), never one found "
                                        f"in the tree; inspect it, then "
                                        f"retry the entry (it adopts this "
                                        f"entry's own orphan) or prepare a "
                                        f"new round"})
    return result


def _adoption_blocked(packet_dir: Path, label: str, record: dict,
                      entry: dict, attempts: list, own: dict, blind,
                      result: "EntryResult",
                      collecting: bool = False) -> tuple | None:
    """`retry`'s refusals BEFORE it adopts an orphan or allocates, in its
    order, as `(kind, head, refusal)` — retry prints `head + refusal`,
    collect shows `refusal` (cause and retry's remedy) — else None — the ONE
    predicate `retry` raises on and `collect` reads for an orphan beside the
    recorded attempt (tail V2 and its follow-up; never a reason's text).
    `kind`: "take" (a bad admitted.json retry takes away, then the admit
    line), "admit" (the printed `admit:` line first), "round" (the cause is
    already the entry's reason; a new round), "orphan" (the wider gap or the
    adoption's own checks on the orphan's files; a new round). `blind` is a
    callable giving the round's retry-cannot-certify sentence; `result` is
    the entry's `_evaluate` state. `collecting` adds the cut-short seal
    `_seal_replaced` meets at retry's action point (retry runs that itself).
    """
    name = entry["name"]
    attempt = entry["attempt"]
    entry_dir = Path(packet_dir) / record["results_dir"] / name
    by_number = dict(attempts)
    replaced = entry_dir / f"attempt-{attempt}"
    expected = _expected_binding(record, entry, attempt)
    head = f"roster entry {name!r}: "
    # Z6 / R3: an attempt whose binding (or attempt 1's, round evidence) no
    # longer binds can never agree — a retry would spend a paid attempt
    # nobody can collect as AGREED. (A recorded attempt not on disk is
    # refused below, naming a new round.)
    unbound = (_unbound_reason(by_number, record, entry, attempt)
               if attempt in by_number else None)
    if unbound is not None:
        return ("round", head, f"{unbound}; nothing was allocated")
    # A RECORDED VALID ANSWER IS COMPLETED WORK, WHATEVER ITS STATE NOW (case
    # C66): once it was sealed as valid, a retry would put a second answer
    # beside the recorded one. Its current state (an integrity failure
    # included) changes nothing; a new answer from this entry is a new round.
    # An attempt sealed as an INADMISSIBLE answer did not return a valid
    # verdict, so R-RETRY's diagnosed retry stays open for it.
    sealed = _sealed_valid_reason(replaced, attempt, own.get(attempt))
    if sealed is not None:
        # The entry's own reason often IS this sentence (an integrity
        # failure of the seal): it is said once, never nested (A8).
        state = (result.state if result.reason is None or sealed in result.reason
                 else f"{result.state}: {result.reason}")
        return ("round", head,
                f"{sealed} — a collection or admission "
                f"recorded it ({state}), so "
                f"it did not fail to run and a retry of it is refused "
                f"(R-RETRY, R-BIND, case C66); a new answer from this entry is "
                f"a new round (prepare r<N+1>) and EVERY entry reviews it "
                f"again (R-REREVIEW)")
    unjudged = (_saved_not_admitted(replaced, expected)
                if entry.get("family", entry["vendor"]) == "claude" else None)
    if unjudged is not None and unjudged.startswith(_ADMIT_BAD):
        return ("take", head, unjudged)
    if unjudged is not None:
        return ("admit" if unjudged.startswith(_ADMIT_FIRST) else "round",
                head, f"attempt {attempt}: {unjudged}; a "
                f"retry would put a second answer beside the saved one "
                f"(R-BIND, case C66)")
    if not attempts:
        return ("round", "",
                f"roster entry {name!r} has no attempt directory under "
                f"{entry_dir} — there is nothing to retry; re-prepare the "
                f"round")
    # THE RECORDED ATTEMPT IS ON DISK, OR THIS REFUSES BEFORE IT MUTATES
    # (gate-1 r11 row r11-8). Wave 10 made the collector evaluate exactly
    # `attempt-<record.attempt>`; `retry` then writes THAT attempt's
    # diagnosis into THAT directory (both on the normal path and, as
    # `attempt-{failed_attempt}`, on the adoption path) after allocating the
    # next one. With the recorded directory gone, the allocation succeeded
    # and the diagnosis write then raised ENOENT — so every retry allocated
    # one more attempt and refused again, an unrecoverable loop in the one
    # recovery command this round offers, with a reason ("fix the
    # permissions") that named neither the cause nor the cure. Host B
    # refuses the same shape at its custody read, BEFORE anything writes
    # (`bin/review_round_v2.py:238`); the PROPERTY is ported, not B's strict
    # contiguity rule — A's `retry` deliberately ADOPTS a one-step orphan,
    # which is the very next rung.
    if attempt not in by_number:
        return ("round", head,
                f"the round record names attempt "
                f"{attempt} and {entry_dir}/attempt-{attempt} is not on disk "
                f"— a retry diagnoses the attempt that failed, and that "
                f"attempt's own directory is where the diagnosis belongs, so "
                f"nothing is allocated here (the tree holds "
                f"{', '.join('attempt-' + str(n) for n, _ in attempts)}) — "
                f"prepare a new round")
    # A BROKEN HISTORY CANNOT BE COLLECTED, SO IT IS NEVER RETRIED (case C66,
    # K9): an attempt behind which the record moved past an answer stays
    # INVALID whatever the next attempt returns — allocating one would spend
    # a paid dispatch nobody can collect.
    history = _history_reason(entry_dir, by_number, attempt, own, entry)
    if history is not None:
        return ("admit" if any(_saved_not_admitted(by_number[n])
                               for n in range(1, attempt) if n in by_number)
                else "round", head, history)
    # A RETRY THAT CANNOT CERTIFY THE ROUND IS REFUSED BEFORE IT IS SPENT
    # (gate-1 r17 row r17-4). Under the round-wide blind rule the recorded
    # attempt's read audit stays a sibling of every later attempt, so when
    # the hook load check cannot attribute its census — or one of its rows'
    # id lists is not whole — every agy leg of the round is INCONCLUSIVE and
    # attempt K+1 is a paid dispatch that can never succeed. Before the
    # orphan adoption and the allocation, so a refusal leaves nothing
    # behind. ROUND-WIDE (gate-1 r18 row r18-2): since r19-3 the guard runs
    # the round's hook load check itself (census AND hook log) and refuses on
    # every verdict a later attempt cannot clear — `_retry_cannot_certify`.
    cannot = blind()
    if cannot is not None:
        return ("round", head, cannot)
    # The replaced attempt must still hold what its seal bound (K9),
    # or the next attempt sits behind a history that fails the same check.
    broken = _seal_reason(replaced, entry, attempt, own.get(attempt),
                          earlier=True)
    if broken is not None:
        return ("round", head, broken)
    # The ORPHAN case (row r4-9): the tree holds attempt K+1 while the record
    # still says K, i.e. a previous retry allocated and then failed before it
    # could record; `retry` adopts it instead of skipping past it, so its own
    # checks on the orphan's files are part of this predicate (a dry run).
    #
    # KEYED ON THE TREE, NOT ON THE EVALUATED ATTEMPT (row r10-1): the
    # on-disk high-water mark is read from the scan.
    on_disk = attempts[-1][0]
    if on_disk == attempt + 1:
        try:
            _adopt_orphan_attempt(packet_dir, label, record, entry, attempt,
                                  "", None, dry_run=True)
        except _HostFault:
            raise  # W3: a host fault is never one entry's refusal
        except CollectError as exc:
            return ("orphan", "", " ".join(str(exc).split()))
    if on_disk > attempt + 1:
        # A GAP OF MORE THAN ONE (gate-1 r5 row r5-10). Adoption covers the
        # one-step orphan; anything wider used to fall through to the normal
        # path, which allocated on top of the highest on-disk attempt and
        # wrote a diagnosis into an attempt this tool never dispatched — the
        # fabricated-diagnosis + runaway-numbering behaviour row r4-9 exists
        # to stop, reached through the gap instead of the step. With the
        # record and the tree that far apart there is no attempt this tool
        # can honestly call "the one that failed", so it refuses and NAMES
        # the state. The packet dir is helper-owned: the remedy is a new round.
        return ("orphan", head,
                f"the round record says attempt "
                f"{attempt} while the results tree already holds attempt "
                f"{on_disk} — a gap of {on_disk - attempt} attempts. Only the "
                f"ONE-step orphan (record K, on-disk K+1) is adopted; a wider "
                f"gap means attempts this round never dispatched, and writing "
                f"a diagnosis into one of them would fabricate evidence — "
                f"prepare a new round")
    seal = replaced / _SEAL_NAME  # `_seal_replaced`, run before adoption
    if collecting and os.path.lexists(seal) and _refusal_cut_short(replaced):
        try:
            _read_seal(seal)
        except CollectError:
            if stat.S_ISDIR(os.lstat(seal).st_mode):
                return ("round", "",
                        _SEAL_DIR.format(attempt=attempt, seal=seal))
            if _raw_admissible(replaced, expected):
                return ("take", "", _seal_reason(
                    replaced, entry, attempt, own.get(attempt),
                    expected=expected))
    return None


def _evaluate_unsealed(packet_dir: Path, record: dict, entry: dict,
                       attempt_dir: Path, base: EntryResult,
                       result_path: str) -> EntryResult:
    """`_evaluate_recorded` for an attempt no collection or admission has
    sealed yet, carrying the digests of the bytes it JUDGED when the attempt
    holds an answer, so `collect` seals exactly those (case C66, K7/K8).

    The digests are taken BEFORE the admission (and the agy gate and hook
    subprocesses) and again after; a difference is this entry's INVALID —
    the bytes moved while they were judged. A file that cannot be digested
    is this entry's INVALID too, never a collection-wide refusal (r5-11)."""
    try:
        before = _seal_files(attempt_dir, entry)
    except CollectError as exc:
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": f"this attempt cannot be sealed: "
                                        f"{' '.join(str(exc).split())} — a "
                                        f"result is recorded only together "
                                        f"with its seal; retry this entry",
                              "result_path": result_path})
    result = _evaluate_recorded(packet_dir, record, entry, attempt_dir, base)
    try:
        after = _seal_files(attempt_dir, entry)
    except CollectError as exc:
        after = f"unreadable ({' '.join(str(exc).split())})"
    if after != before:
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": f"integrity failure: the result, "
                                        f"receipt or read evidence of attempt "
                                        f"{base.attempt} changed while this "
                                        f"collection judged it — "
                                        f"{_SEAL_REMEDY}",
                              "result_path": result_path})
    if before["result"][1] is not None and result.state != "missing":
        return EntryResult(**{**result.__dict__, "seal_files": before})
    return result


def _receipt_reason(attempt_dir: Path, route) -> str | None:
    """None when the wrapper's run-log receipt in this attempt's own namespace
    records the argv `dispatch.json` recorded; else why the answer does not
    count (R-BIND). Every run-log there must match, and one must exist: the
    wrapper writes it only when it runs with the recorded env."""
    runs = attempt_dir / "logs" / _RUN_LOG_CLI[route] / "runs"
    try:
        argv = json.loads(_read_regular_file(
            attempt_dir / "dispatch.json", "the dispatch record"))["argv"][1:]
    except (CollectError, ValueError, RecursionError, KeyError,
            TypeError) as exc:
        return (f"the recorded command is unknown, so the receipt cannot be "
                f"compared: {' '.join(str(exc).split())} — retry this entry "
                f"(R-BIND)")
    try:
        logs = sorted(Path(e.path) for e in os.scandir(runs)
                      if e.name.endswith(".json"))
    except FileNotFoundError:
        logs = []
    except OSError as exc:
        return (f"the run-log directory {runs} cannot be read "
                f"({' '.join(str(exc).split())}) — retry this entry (R-BIND)")
    if not logs:
        return (f"no run-log under {runs}: the wrapper writes one there only "
                f"when it runs with the recorded env — {_RECEIPT_REMEDY}")
    for path in logs:
        try:
            ran = json.loads(_read_regular_file(path, "the run-log"))
            ran = ran.get("wrapper_cmd") if isinstance(ran, dict) else None
        except (CollectError, ValueError, RecursionError) as exc:
            return (f"the run-log {path} cannot be read "
                    f"({' '.join(str(exc).split())}) — retry this entry "
                    f"(R-BIND)")
        if ran != argv:
            return (f"the run-log {path} records an executed command that is "
                    f"not {attempt_dir}/dispatch.json's argv — "
                    f"{_RECEIPT_REMEDY}")
    return None


def _evaluate_recorded(packet_dir: Path, record: dict, entry: dict,
                       attempt_dir: Path, base: EntryResult,
                       receipt: bool = True) -> EntryResult:
    """`_evaluate`'s body for the ONE attempt directory the record names.

    Split out so the rules ABOUT which attempt is evaluated (row r10-2) read
    as one block in the caller. `receipt` False skips the executed-command
    receipt check, for a seal that already recorded a valid answer."""
    attempt = base.attempt

    result = attempt_dir / _result_filename(base.family)
    try:
        size = result.stat().st_size
    except OSError:
        return EntryResult(**{**base.__dict__,
                              "reason": f"no result file at {result}",
                              "result_path": str(result)})
    if size == 0:
        return EntryResult(**{**base.__dict__,
                              "reason": f"the result file {result} is empty",
                              "result_path": str(result)})
    # THE RESULT FILE IS EVIDENCE TOO (gate-1 r20 row r20-2): the one file
    # read in-process for EVERY entry is bounded like every other — above the
    # cap it is this entry's INVALID before admission reads a byte (the
    # verdict reader enforces the same cap on its own descriptor).
    if size > _EVIDENCE_MAX_BYTES:
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": f"the result file {result} exceeds "
                                        f"the {_EVIDENCE_CAP_TEXT} evidence "
                                        f"cap — no genuine reply is anywhere "
                                        f"near that size, so it is misfiled "
                                        f"or corrupt; inspect it, then retry "
                                        f"this entry",
                              "result_path": str(result)})

    verdict_v2 = _load_sibling("verdict_v2")
    # The binding was compared with the derivation first (`_unbound_reason`).
    expected = _expected_binding(record, entry, attempt)
    admission = verdict_v2.admit_file(result, expected)
    if not admission.ok:
        # A HOST FAULT IS NOT A LEG RESULT (gate-1 r7 row r7-c4). verdict_v2
        # reserves exit 64 for the admission it could not RUN at all — absent
        # jsonschema, an unreadable or non-Draft-2020-12 vendored contract —
        # and this branch recorded it as the ENTRY's `invalid`, so the round
        # folded to INCOMPLETE and told the leader to re-dispatch PAID legs
        # over a broken install. Nothing about this leg (or any other) is
        # known, so the collection stops here; `_HostFault`'s docstring
        # carries the rule.
        if admission.exit_code == verdict_v2.EXIT_USAGE:
            raise _HostFault(
                f"this host cannot admit any reply: {admission.reason} "
                f"(reached while admitting {result}) — the collection is "
                f"STOPPED and no per-entry state was written; nothing about "
                f"the legs is known, so repair the install and collect again "
                f"rather than re-dispatching them")
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": admission.reason,
                              "result_path": str(result),
                              "exit_code": admission.exit_code})

    obj = admission.verdict or {}
    verdict = obj.get("verdict")
    blocking = admission.blocking
    open_questions = admission.open_questions
    why = (_receipt_reason(attempt_dir, base.route)
           if receipt and base.family != "claude" else None)
    if why is not None:
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": why, "verdict": verdict,
                              "result_path": str(result)})
    if base.route == "agy":
        reason = _agy_evidence_reason(Path(packet_dir), record, attempt_dir)
        if reason is not None:
            return EntryResult(**{**base.__dict__, "state": "invalid",
                                  "reason": reason, "verdict": verdict,
                                  "result_path": str(result)})
    return EntryResult(**{**base.__dict__, "state": "valid",
                          "verdict": verdict, "blocking": blocking,
                          "open_questions": open_questions,
                          # R-AGREE: a negative verdict carrying no blocking
                          # finding and no open question is schema-valid but
                          # NOT agreement; the mismatch between the verdict
                          # token and its own content is recorded.
                          "deviation": (verdict != SAFE_VERDICT
                                        and blocking == 0
                                        and open_questions == 0),
                          "result_path": str(result)})


def _outcome(entries: list) -> str:
    """R-AGREE: AGREED only over a NONEMPTY entry list. The bound selection is
    nonempty (prepare refuses an empty roster, `collect` refuses a changed
    one), and an empty list is still never agreement on its own: it folds to
    INCOMPLETE, the outcome of a missing selection."""
    if not entries or any(e.state != "valid" for e in entries):
        return "INCOMPLETE"
    if any(e.verdict != SAFE_VERDICT or e.blocking or e.open_questions
           for e in entries):
        return "BLOCKED"
    return "AGREED"


_OUTCOME_NOTE = {
    "AGREED": ("every selected entry explicitly returned SAFE TO MERGE with "
               "no blocking finding and no open question; family coverage is "
               "reported, never a threshold; this is the collector's outcome, "
               "NOT a merge authorisation"),
    "BLOCKED": ("an entry returned a verdict other than SAFE TO MERGE (a "
                "Minor-only negative included), a blocking finding or an open "
                "question; acceptance grants no exemption (R-AGREE)"),
    "INCOMPLETE": ("some entry is missing or invalid — a non-affirmative "
                   "result is never agreement"),
}


def _report(collection: Collection, label: str) -> None:
    print(f"collection {label}: {collection.outcome} — "
          f"{_OUTCOME_NOTE[collection.outcome]}")
    for e in collection.entries:
        head = (f"  {e.name} : family={e.family} attempt="
                f"{e.attempt if e.attempt is not None else '-'} "
                f"acceptance={e.acceptance} {e.state.upper()}")
        if e.state == "valid":
            tail = (f" verdict={e.verdict!r} blocking={e.blocking} "
                    f"open_questions={e.open_questions}")
            if e.deviation:
                tail += ("  [verdict-selection deviation: a negative verdict "
                         "with no blocking finding and no open question — "
                         "kept as given, NOT agreement (R-AGREE)]")
            print(head + tail)
        elif e.verdict is not None:  # an answer that does not count (N5)
            print(head + f" — the leg answered {e.verdict!r}, but {e.reason}")
        else:
            print(head + f" — {e.reason}")
    print(f"COLLECT_V2 {collection.outcome} "
          f"entries={collection.valid}/{len(collection.entries)} "
          f"families={len(collection.families_covered)} "
          f"blocking={collection.blocking} "
          f"open_questions={collection.open_questions}")


def _check_contract_basis(record: dict, what: str) -> None:
    """Refuse unless the ADMISSION contract is the one this round froze
    (gate-1 r8 row r8-10).

    The prompt clauses, the clause directory and the producer projection are
    all frozen at prepare and re-derived before a retry and a collection
    (`_check_installed_basis`); the contract
    `verdict_v2` judges every reply against was re-read LIVE here, so a
    re-vendoring between dispatch and collect judged the round's replies
    against a DIFFERENT contract while the record still claimed an unchanged
    basis — and unlike every other basis, no leg artifact carries a trace of
    it (an admitted `verdict.json` says nothing about the schema that let it
    through). Same shape as the `projection_digest` refusal in `retry`: a
    mismatch is a NEW ROUND, and a record that carries no digest cannot
    PROVE the basis either, so it is refused rather than guessed at.

    ORDER: the HOST question comes first. `_get_validator` reserves its
    reason for "this install cannot admit ANY reply" (absent jsonschema, an
    unreadable / corrupt / non-Draft-2020-12 contract), which is a
    `_HostFault` at exit 64 — never this round's exit-2 basis refusal,
    because a file this host cannot even load is not evidence that the SPEC
    moved."""
    verdict_v2 = _load_sibling("verdict_v2")
    validator, why = verdict_v2._get_validator()
    if validator is None:
        raise _HostFault(
            f"this host cannot admit any reply: {why} (reached while proving "
            f"the admission-contract basis of this round) — the {what} is "
            f"STOPPED and no per-entry state was written; nothing about the "
            f"legs is known, so repair the install and run it again rather "
            f"than re-dispatching them")
    frozen = record.get("contract_digest")
    if not isinstance(frozen, str) or not frozen:
        raise CollectError(
            f"the round record carries no frozen ADMISSION contract digest, "
            f"so this {what} cannot prove the replies are judged against the "
            f"contract the round was prepared with — prepare a new round")
    path = verdict_v2._schema_path()
    try:
        live = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise _HostFault(
            f"this host cannot read the admission contract {path} "
            f"({' '.join(str(exc).split())}), so no reply can be judged — "
            f"the {what} is STOPPED and no per-entry state was written") \
            from exc
    if live != frozen:
        raise CollectError(
            f"the ADMISSION contract basis changed since this round was "
            f"prepared (frozen {frozen} vs {path} {live}) — every reply "
            f"would be judged against a contract this round never agreed to, "
            f"so prepare a new round (R-REREVIEW: every entry reviews the "
            f"new basis again)")


def _check_installed_basis(packet_dir: Path, label: str, record: dict,
                           what: str) -> None:
    """Refuse unless the round's basis members recorded at prepare still
    equal what the INSTALLED files derive (R-PREPARE, R-RETRY; cases C13 /
    C19 / C20 / C33; spec DL-41, DL-49) — run by `collect` and by `retry`
    (whose orphan adoption comes after it) before anything is judged or
    allocated.

    Three members a leg's result carries no trace of are recorded in the
    mutable `.roster-r<N>.json`, not in the digest-covered delivery record:
    each dispatched entry's clause manifest and the clause directory
    (`prompt_manifests`, `prompt_spec_dir`), the producer schema projection
    (`projection_digest`), and a claude entry's spawned shipped preset with
    its file digest and the model and effort it pins (`preset`, bound
    through the configuration digest). Each is RE-DERIVED here from the
    installed files — the pure prompt render `prepare` itself uses, the
    projection `roster_v2` renders, the shipped preset
    `roster_v2._claude_preset` reads, re-derived from the BARE name the
    roster gave (the bound `preset.agent` is the layout-qualified spawn id)
    and compared by its digest alone, which covers model, effort and body.
    A changed member is a changed basis: a new round, never a re-render, a
    collection or a retry on it (R-REREVIEW). A record that carries no
    member cannot prove it, so it is refused rather than guessed at."""
    review_scratch = _load_sibling("review_scratch")
    roster = _load_sibling("roster_v2")
    prompts = _load_sibling("prompts_v2")
    manifests = record.get("prompt_manifests") or {}
    frozen_dir = record.get("prompt_spec_dir")
    for entry in _dispatched(record):
        name = entry["name"]
        conditions = _bound_conditions(packet_dir, label, record, name)
        frozen = manifests.get(name)
        if frozen is None:
            raise CollectError(
                f"the round record carries no frozen prompt manifest for "
                f"{name!r}, so {what} cannot prove the clause basis is "
                f"unchanged — prepare a new round")
        if frozen_dir is None:
            raise CollectError(
                f"the round record carries no frozen prompt clause directory, "
                f"so {what} of {name!r} cannot prove the clause basis is "
                f"unchanged — prepare a new round")
        try:
            _text, manifest, spec_dir, _seam = review_scratch._v2_render_prompt(
                Path(record["worktree"]), record["review_id"],
                record["content_digest"], roster.Entry(**entry["leg"]),
                entry["attempt"], conditions)
        except (roster.RosterError, prompts.PromptSpecError, OSError,
                KeyError, TypeError, ValueError, SystemExit) as exc:
            raise CollectError(
                f"the prompt for {name!r} cannot be re-rendered on this host "
                f"({' '.join(str(exc).split())}), so {what} cannot prove the "
                f"clause basis is unchanged — prepare a new round") from exc
        if ([list(pair) for pair in frozen]
                != [list(pair) for pair in manifest]
                or str(spec_dir) != str(frozen_dir)):
            raise CollectError(
                f"roster entry {name!r}: the prompt basis changed since this "
                f"round was prepared (clause digests or clause directory "
                f"differ: frozen {frozen_dir!r} vs rendered "
                f"{str(spec_dir)!r}) — {what} is refused on a changed basis, "
                f"so prepare a new round (R-REREVIEW: every entry reviews the "
                f"new basis again)")
        if entry.get("family", entry["vendor"]) != "claude":
            continue
        bound = entry.get("preset")
        if not (isinstance(bound, dict)
                and isinstance(bound.get("file_sha256"), str)):
            raise CollectError(
                f"roster entry {name!r}: the round record binds no claude "
                f"preset (spawned agent, file digest), so {what} cannot prove "
                f"the preset is unchanged — prepare a new round")
        try:
            installed = roster._claude_preset(
                (entry["leg"].get("claude") or {}).get("agent") or "",
                conditions["review_web_authorized"])
        except roster.RosterError as exc:
            installed = f"missing ({' '.join(str(exc).split())})"
        if (not isinstance(installed, dict)
                or installed["file_sha256"] != bound["file_sha256"]):
            keys = ("agent", "model", "effort", "file_sha256")
            if isinstance(installed, dict):
                installed = {key: installed.get(key) for key in keys}
            raise CollectError(
                f"roster entry {name!r}: the claude preset the leg spawns "
                f"changed since this round was prepared (bound "
                f"{ {key: bound.get(key) for key in keys}!r} vs installed "
                f"{installed}) — its model and effort are controls of the "
                f"bound basis, so {what} is refused; prepare a new round "
                f"(R-RETRY, R-REREVIEW)")
    frozen_projection = record.get("projection_digest")
    if not isinstance(frozen_projection, str) or not frozen_projection:
        raise CollectError(
            f"the round record carries no frozen producer-schema projection "
            f"digest, so {what} cannot prove the PRODUCER SCHEMA basis is "
            f"unchanged — prepare a new round")
    try:
        projection = hashlib.sha256(
            roster.projected_schema_text().encode("utf-8")).hexdigest()
    except roster.RosterError as exc:
        raise CollectError(
            f"the producer schema projection cannot be derived on this host "
            f"({' '.join(str(exc).split())}), so {what} cannot prove the "
            f"basis is unchanged") from exc
    if projection != frozen_projection:
        raise CollectError(
            f"the PRODUCER SCHEMA basis changed since this round was prepared "
            f"(projection digest frozen {frozen_projection} vs rendered "
            f"{projection}) — {what} is refused on a changed basis, so "
            f"prepare a new round (R-REREVIEW: every entry reviews the new "
            f"basis again)")


def collect(packet_dir, label: str) -> Collection:
    """Collect every dispatched entry, write `collect-r<N>.json`, print the
    per-entry table plus the one greppable summary line, and return the
    Collection. Re-runnable by design: a collection is recomputed as legs
    land, so the record is overwritten rather than exclusive-created. The
    packet path is made absolute once (its own `verify` takes no other)."""
    packet_dir = Path(os.path.abspath(packet_dir))
    record = _read_record(packet_dir, label)
    # BEFORE any entry is judged (row r8-10): the contract that judges them
    # has to be the one this round froze, and a refusal must leave the
    # previous collection record untouched.
    _check_contract_basis(record, "collection")
    # EVERY ENABLED ENTRY IS COUNTED AND NAMED (gate-1 r11 row r11-9). A
    # SKIPPED entry was dropped from the collection outright, so it left no
    # trace in the outcome at all: with three same-family entries a skipped
    # sibling still left that family COVERED, and a round in which a leg
    # never ran reported AGREED — a result nobody produced counted as
    # agreement, which R-AGREE already forbids ("a missing result is not
    # agreement"). Host B is right here and its shape is ported:
    # `bin/review_round_v2.py:505-530` iterates every enabled entry and
    # sends any without a COMPLETE terminal to `missing`. The SKIP itself is
    # untouched (R-GOOGLE still skips at prepare, and `prepare`/`roster_v2`
    # decide it); only the OUTCOME accounting moves, and a `missing` entry
    # makes the round INCOMPLETE no matter what its siblings cover.
    # The selection and configuration must be the ones bound into the
    # round's basis (cases C19 / C33): an entry turned off or re-configured
    # after prepare is refused BY NAME as a change. Prepare refuses an empty
    # selection (R-AGREE: a nonempty roster), so a bound selection is never
    # empty and an empty record can only be a changed one.
    _bound_metadata(packet_dir, label, record, "the collection")
    # The basis members only the installed files can prove (C13 / C19 / C20 /
    # C33): re-derived and compared before any entry is judged.
    _check_installed_basis(packet_dir, label, record, "the collection")
    recorded = _recorded_seals(packet_dir, label)
    entries = []
    evaluated = []
    for entry in record["entries"]:
        if not entry.get("enabled"):
            continue
        skipped = entry.get("skipped_reason")
        if skipped:
            entries.append(EntryResult(
                name=entry["name"],
                family=entry.get("family", entry["vendor"]),
                route=entry.get("route"),
                acceptance=entry.get("acceptance", ""),
                attempt=None, state="missing",
                reason=f"SKIPPED at prepare and never dispatched: {skipped}. "
                       f"An enabled entry that produced no result is not "
                       f"agreement (R-AGREE), whatever its siblings cover"))
            continue
        entries.append(_evaluate(packet_dir, record, entry, recorded,
                                 label))
        evaluated.append((len(entries) - 1, entry))
    # RECORD = SEAL (R-BIND, case C66): every attempt this collection records
    # with an answer — valid or not — is sealed once, with the digests of the
    # bytes it judged (an answer the native admission already sealed keeps
    # that seal). The collection record keeps every seal digest of the entry,
    # so a seal that later goes missing or changes is an integrity failure.
    for idx, entry in evaluated:
        result = entries[idx]
        if result.attempt is None:
            continue
        attempt_dir = (packet_dir / record["results_dir"] / entry["name"]
                       / f"attempt-{result.attempt}")
        why = (_readmission_reason(attempt_dir, record, entry, result.attempt,
                                   result.seal_files)
               if result.seal_files is not None and result.family == "claude"
               and result.state == "valid" else None)
        if why is not None:
            result = EntryResult(**{**result.__dict__, "state": "invalid",
                                    "reason": why, "seal_files": None})
        if result.seal_files is not None:
            try:
                _write_seal(attempt_dir, entry, result.attempt,
                            result.seal_files, result.state)
            except CollectError as exc:
                result = EntryResult(**{**result.__dict__, "state": "invalid",
                                        "reason": " ".join(str(exc).split())})
        seals = dict(recorded.get(entry["name"], {}))
        if result.attempt not in seals:
            try:
                sha = _seal_digest(attempt_dir / _SEAL_NAME)
                if sha is not None and _refusal_cut_short(attempt_dir):
                    # G1: a refused reply's cut-short seal binds nothing, so
                    # it is not recorded; `retry` completes it (V2).
                    _read_seal(attempt_dir / _SEAL_NAME)
            except CollectError:
                sha = None
            if sha is not None:
                seals[result.attempt] = sha
        entries[idx] = EntryResult(**{**result.__dict__, "seal_files": None,
                                      "seals": seals})
    outcome = _outcome(entries)
    if outcome == "AGREED":
        # R-AGREE: no integrity failure. The round integrity check runs HERE
        # too, so a skipped or too-early `verify` (a leader's mistake,
        # R-THREAT) never yields AGREED; a refusal leaves the previous
        # collection record untouched.
        try:
            check = _run([sys.executable, str(LIB_DIR / "review_scratch.py"),
                          "verify", str(packet_dir), str(record["worktree"]),
                          label])
        except OSError as exc:
            raise _HostFault(f"the round integrity check (`review_scratch.py "
                             f"verify`) could not be launched "
                             f"({' '.join(str(exc).split())}) — nothing about "
                             f"the round is known; repair the host and "
                             f"collect again") from exc
        if check.returncode not in (0, 2):  # 2 = verify's own refusal (V3)
            tail = " ".join((check.stderr or "").split())[-300:]
            raise _HostFault(f"the round integrity check (`review_scratch.py "
                             f"verify`) did not finish (exit "
                             f"{check.returncode}{': ' + tail if tail else ''})"
                             f" — nothing about the round is known; repair "
                             f"the host and collect again")
        if check.returncode != 0:
            _integrity_refusal(packet_dir, label,
                               " ".join((check.stderr or "").split()))
        # G3: a leg still running may have written into an earlier attempt
        # since this collection checked it, so that custody is re-checked
        # right before an AGREED record is written.
        for _, entry in evaluated:
            entry_dir = packet_dir / record["results_dir"] / entry["name"]
            late = _history_reason(entry_dir, dict(_attempts(entry_dir)),
                                   entry["attempt"],
                                   recorded.get(entry["name"]), entry)
            if late is not None:
                raise CollectError(f"roster entry {entry['name']!r} changed "
                                   f"while this collection ran: {late} — "
                                   f"nothing was recorded")
    families = sorted({e.family for e in entries if e.state == "valid"})
    deviations = [{"name": e.name, "verdict": e.verdict, "attempt": e.attempt}
                  for e in entries if e.deviation]
    collection = Collection(
        outcome=outcome, entries=entries, families_covered=families,
        deviations=deviations,
        blocking=sum(e.blocking for e in entries),
        open_questions=sum(e.open_questions for e in entries),
        record_path=packet_dir / f"collect-{label}.json")
    _write_json(collection.record_path, {
        "schema_version": 2,
        "label": label,
        "round": record.get("round"),
        "review_id": record.get("review_id"),
        "content_digest": record.get("content_digest"),
        "outcome": outcome,
        "outcome_note": _OUTCOME_NOTE[outcome],
        "entries": [e.json() for e in entries],
        "families_covered": families,
        "deviations": deviations,
        "blocking": collection.blocking,
        "open_questions": collection.open_questions,
        "skipped": record.get("skipped", []),
    })
    _heartbeat(packet_dir)
    _report(collection, label)
    return collection


def _integrity_refusal(packet_dir: Path, label: str, why: str) -> None:
    """Raise the AGREED refusal for a failed round integrity check, naming
    the remedy BY CAUSE (R-AGREE, R-PREPARE; M4)."""
    head = (f"every entry agreed, but the round integrity check "
            f"(`review_scratch.py verify`) failed: {why[-600:]} — ")
    if re.search(r"could not be run|verification record \S+ could not be "
                 r"written|heartbeat could not be refreshed", why):
        raise _HostFault(f"{head}nothing about the round is known; repair "
                         f"the host and collect again")
    later = sorted(int(m.group(1)) for p in Path(packet_dir).iterdir()
                   if (m := re.fullmatch(r"\.snapshot-r(\d+)\.json", p.name))
                   and int(m.group(1)) > int(label[1:]))
    stray = re.search(r"uncovered non-output file in packet dir: (.+?) — it "
                      r"is absent", why)  # the WHOLE name (P1)
    if later:
        remedy = (f"round {label} is superseded by r{later[-1]} (its prepare "
                  f"re-pinned the tree), so it cannot be AGREED; collect "
                  f"r{later[-1]}")
    elif re.search(r"holds \d+ round worktrees", why):
        remedy = ("this round cannot be AGREED while a second round tree "
                  "sits in the packet dir; prepare a new round in a new "
                  "packet dir (`review_scratch.py open` with a new slug)")
    elif stray and re.fullmatch(r"\.tmp-\d+-(?:collect-r\d+\.json|\.roster-r"
                                r"\d+\.json|\.verified-r\d+\.json)",
                                stray.group(1)):
        remedy = ("that file is this host's own staging leftover from a "
                  "stopped write, and the host's deletion command removes a "
                  "whole packet dir only: prepare a new round")
    else:
        remedy = ("this round cannot be AGREED: it is INVALID (a leg may "
                  "have read bytes the round did not bind); prepare a new "
                  "round")
    raise CollectError(head + remedy)


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_dispatch_record(dispatch: dict, attempt_dir: Path, route,
                           refusal_tail: str, web: bool = False,
                           family: str | None = None,
                           bound_agent: str | None = None) -> None:
    """Refuse an adopted `dispatch.json` that the print could not render.

    TYPES, not truthiness (gate-1 r5 row r5-8, corrected by r6 row r6-5 and
    its claude amendment). The r5-8 check asked only whether three members
    were non-empty, so `argv: [1]` passed it — and `shlex.quote` then raised
    mid-print, AFTER the round record had been bumped. EVERY member
    `v2_print_dispatch` / `_v2_expected_flags` read is checked here, BEFORE
    anything is written: the kind, the identity for that kind, the stdout /
    stderr paths, the env mapping, the agy route's read-audit path (the gate
    and the hook check are printed from it) and the producer schema
    projection when the record names one. Each unusable member is REFUSED BY
    NAME — the value itself is vendor- or operator-supplied text and is not
    echoed.

    THE LAUNCH SWITCH AGREES WITH THE BOUND CONDITION IN BOTH DIRECTIONS
    (R-REVIEW-WEB, case C32): `web` is the round's bound
    `review_web_authorized`. A wrapper argv carries its route's web switch
    exactly when it is true (and never the investigation `--web`); a native
    record names the preset this round BOUND (`bound_agent`, the shipped
    preset `roster_v2._claude_preset` maps for the bound condition) — never
    judged by a `-web` name. Judged only on a record
    whose kind is the one `family` dispatches (claude native, the rest
    wrapper): a flipped kind is the adoption comparison's to name."""
    kind = dispatch.get("kind")
    if kind not in ("native", "wrapper"):
        raise CollectError(
            f"{attempt_dir}/dispatch.json names no usable dispatch kind "
            f"({kind!r}; this helper writes 'native' or 'wrapper') — "
            f"{refusal_tail}")
    broken: list = []
    if kind == "native":
        native = dispatch.get("native")
        identity = native.get("subagent_type") if isinstance(native, dict) \
            else None
        if not _nonempty_str(identity):
            broken.append("native.subagent_type (a non-empty string)")
        if not _nonempty_str(dispatch.get("stdout_path")):
            broken.append("stdout_path (a non-empty string)")
    else:
        argv = dispatch.get("argv")
        if not (isinstance(argv, list) and argv
                and all(isinstance(token, str) for token in argv)):
            broken.append("argv (a non-empty list of strings)")
        for key in ("stdout_path", "stderr_path"):
            if not _nonempty_str(dispatch.get(key)):
                broken.append(f"{key} (a non-empty string)")
        env = dispatch.get("env")
        if not (isinstance(env, dict)
                and all(isinstance(k, str) and isinstance(v, str)
                        for k, v in env.items())):
            broken.append("env (a mapping of strings to strings)")
        # THE KEY ITSELF, ON EVERY WRAPPER ROUTE (gate-1 r7 row r7-c3).
        # `.get()` answers None for "absent" and for "null" alike, so an
        # ABSENT key passed the non-agy reading here and then met
        # `v2_print_dispatch`'s `dispatch["read_audit_path"]` — a KeyError
        # raised AFTER the diagnosis had been written into attempt K, which
        # is the half-done state rows r5-8 / r6-5 exist to prevent. The
        # writer emits the key on every wrapper route (an absolute path on
        # agy, an explicit null elsewhere), so its ABSENCE is a broken
        # record, not a default to infer.
        if "read_audit_path" not in dispatch:
            broken.append("read_audit_path (the key itself is absent; every "
                          "wrapper record carries it — a non-empty absolute "
                          "path on the agy route, explicitly null on the "
                          "others — and the dispatch print reads it)")
        audit_path = dispatch.get("read_audit_path")
        if route == "agy":
            # The agy leg's read-audit gate and hook check are PRINTED from
            # this member; a record without it used to reach the print and
            # raise a KeyError there.
            if not _nonempty_str(audit_path):
                broken.append("read_audit_path (a non-empty string; the agy "
                              "route's gate and hook check are printed from "
                              "it)")
        elif audit_path is not None:
            # NULL, not merely "a usable string" (gate-1 r7 row r7-x4). A
            # non-agy route writes no read audit, so ANY value here is a
            # planted one — and a planted path would have been printed as
            # this entry's gate command.
            broken.append("read_audit_path (null on a route that takes none; "
                          "only the agy route writes a read audit, so a path "
                          "here belongs to no dispatch this round rendered)")
    schema_file = dispatch.get("schema_file")
    if schema_file is not None and not _nonempty_str(schema_file):
        broken.append("schema_file (a non-empty string, or null on a route "
                      "that takes none)")
    if not broken and (kind == "native") == (family == "claude"):
        broken.extend(_web_switch_mismatch(dispatch, kind, route, web,
                                           bound_agent=bound_agent))
    if broken:
        raise CollectError(
            f"{attempt_dir}/dispatch.json is not a usable {kind} dispatch "
            f"record (unusable: {'; '.join(broken)}) — the adopted attempt "
            f"is DISPATCHED from this record, and a native leg with no "
            f"subagent_type would be spawned under the layout default, i.e. "
            f"the gating reviewer; {refusal_tail}")


def _web_switch_mismatch(dispatch: dict, kind: str, route, web: bool,
                         bound_agent: str | None = None) -> list:
    """The `_check_dispatch_record` rows for a launch switch that disagrees
    with the bound review-web condition `web` (empty when they agree). A
    native record must name `bound_agent`: the shipped preset prepare bound
    for this condition (H5) — a `-web` name proves nothing."""
    if kind == "native":
        agent = dispatch["native"]["subagent_type"]
        if bound_agent is None or agent != bound_agent:
            return [f"native.subagent_type (not the preset this round bound "
                    f"for its review_web_authorized="
                    f"{str(web).lower()})"]
        return []
    argv = dispatch["argv"]
    switch = _WEB_SWITCH.get(route)
    rows = []
    if "--web" in argv:
        rows.append("argv (carries the investigation --web, never a review "
                    "switch — R-INVEST)")
    if switch is not None and (switch in argv) != web:
        rows.append(f"argv (the launch web switch {switch} is "
                    f"{'absent' if web else 'present'}, but this round's "
                    f"bound review_web_authorized is {str(web).lower()})")
    return rows


def _rendered_dispatch(packet_dir: Path, record: dict, entry: dict,
                       attempt: int, attempt_dir: Path, web: bool) -> dict:
    """The dispatch THIS round's FROZEN roster entry renders for `attempt`.

    PURE (`roster_v2.render_dispatch` creates nothing; gate 1 r2 row r2-1),
    and derived from OUTSIDE the attempt directory, exactly as
    `_expected_binding` is: the round record's worktree, the frozen `leg`,
    the attempt number the caller parsed. Adoption compares the on-disk
    record against it (row r7-x4) instead of trusting the record's own copy
    of the invocation.

    Nothing rendered here is WRITTEN: the adopted attempt keeps its own
    bytes, so R-RETRY's "nothing is re-rendered" still holds — this render
    is a comparison basis that is discarded."""
    roster = _load_sibling("roster_v2")
    review_scratch = _load_sibling("review_scratch")
    try:
        leg = roster.Entry(**entry["leg"])
        dispatch = roster.render_dispatch(leg, roster.DispatchCtx(
            worktree=Path(record["worktree"]), packet_dir=Path(packet_dir),
            prompt_file=attempt_dir / "prompt.txt", attempt_dir=attempt_dir,
            wrapper_dir=review_scratch._v2_wrapper_dir(),
            timeout_override=None, attempt=attempt,
            review_web_authorized=web))
        return review_scratch._v2_dispatch_json(dispatch)
    except (roster.RosterError, KeyError, TypeError, ValueError,
            SystemExit) as exc:
        raise CollectError(
            f"the frozen roster entry for {entry.get('name')!r} cannot be "
            f"re-rendered at attempt {attempt} "
            f"({' '.join(str(exc).split())}), so the attempt on disk cannot "
            f"be compared against the invocation this round would issue — "
            f"prepare a new round") from exc


def _check_adopted_bytes(record: dict, entry: dict, attempt: int,
                         attempt_dir: Path, dispatch: dict,
                         refusal_tail: str, conditions: dict) -> None:
    """Refuse an orphan whose PROMPT or PRODUCER SCHEMA bytes are not the
    ones this round froze (gate-1 r8 row r8-7).

    The adoption path returns BEFORE the frozen-manifest / clause-directory
    / projection-digest checks `retry` runs, and it tested `prompt.txt` and
    `schema.projected.json` for EXISTENCE only (row r5-3) — so the two files
    the adopted invocation FEEDS THE VENDOR were compared with nothing. A
    planted prompt re-instructs the leg under this entry's name and a
    planted projection changes the schema it is handed, both while every
    binding field and every invocation member still matches (rows r6-3 /
    r7-x4 / r8-2). This is the r5-1 read-back class over the last two files
    in the attempt directory.

    NOTHING IS RE-RENDERED INTO THE ATTEMPT (R-RETRY). The prompt is
    re-rendered PURELY — through `review_scratch._v2_render_prompt`, the one
    context construction `prepare` itself uses — as a comparison basis that
    is discarded, and the render's own clause manifest is compared against
    the round's FROZEN `prompt_manifests[name]` first, so a spec re-vendored
    since prepare is a NEW ROUND rather than a silently accepted re-render.
    The projection is a pure digest comparison against the frozen
    `projection_digest`; a record carrying no frozen value cannot PROVE
    either basis, so it is refused instead of guessed at."""
    name = entry["name"]
    roster = _load_sibling("roster_v2")
    prompts = _load_sibling("prompts_v2")
    review_scratch = _load_sibling("review_scratch")
    frozen_manifest = (record.get("prompt_manifests") or {}).get(name)
    if frozen_manifest is None:
        raise CollectError(
            f"the round record carries no frozen prompt manifest for "
            f"{name!r}, so the bytes in {attempt_dir} cannot be proven to be "
            f"the ones this round renders — prepare a new round")
    try:
        leg = roster.Entry(**entry["leg"])
        text, manifest, _spec_dir, _seam = review_scratch._v2_render_prompt(
            Path(record["worktree"]), record["review_id"],
            record["content_digest"], leg, attempt, conditions)
    # `OSError` joins the tuple (gate-1 r9 row r9-13): the render reads the
    # vendored clause files, and an unreadable one (mode 000, EIO) used to
    # escape this refusal path as a traceback — although this same function
    # already converts OSError for its two on-disk reads. Both layers now
    # refuse: `prompts_v2._read_spec_text` raises `PromptSpecError` for the
    # clause file itself, and this tuple covers any other OSError the pure
    # render can reach.
    except (roster.RosterError, prompts.PromptSpecError, OSError, KeyError,
            TypeError, ValueError, SystemExit) as exc:
        raise CollectError(
            f"the prompt for {name!r} attempt {attempt} cannot be re-rendered "
            f"on this host ({' '.join(str(exc).split())}), so the "
            f"{attempt_dir}/prompt.txt on disk cannot be compared against the "
            f"bytes this round sends — prepare a new round") from exc
    if ([list(pair) for pair in frozen_manifest]
            != [list(pair) for pair in manifest]):
        raise CollectError(
            f"roster entry {name!r}: the prompt CLAUSE basis changed since "
            f"this round was prepared, so the adopted {attempt_dir} cannot be "
            f"proven to carry this round's instructions — a retry re-runs the "
            f"SAME basis, so prepare a new round (R-REREVIEW)")
    # THE CLAUSE DIRECTORY IS THE OTHER HALF OF THAT BASIS (gate-1 r9 row
    # r9-5). The normal `retry` refuses BOTH a missing and a changed
    # `prompt_spec_dir` (row r5-7) — digests alone do not say WHERE the
    # clause bytes came from, and a record written without the key let the
    # comparison be skipped entirely. Adoption returns before that rung, so
    # it carried neither rule: same claim ("the basis is provably
    # unchanged"), same two refusals, one path over.
    frozen_spec_dir = record.get("prompt_spec_dir")
    if frozen_spec_dir is None:
        raise CollectError(
            f"the round record carries no frozen prompt clause directory, so "
            f"the adopted {attempt_dir} cannot be proven to carry {name!r}'s "
            f"basis for this round — prepare a new round")
    if str(_spec_dir) != str(frozen_spec_dir):
        raise CollectError(
            f"roster entry {name!r}: the prompt CLAUSE DIRECTORY changed "
            f"since this round was prepared (frozen {frozen_spec_dir!r} vs "
            f"rendered {str(_spec_dir)!r}), so the adopted {attempt_dir} "
            f"cannot be proven to carry this round's instructions — a retry "
            f"re-runs the SAME basis, so prepare a new round (R-REREVIEW)")
    prompt_path = attempt_dir / "prompt.txt"
    # HARDENED, like every other helper-owned read (row r9-11): a symlink at
    # this name refuses BY NAME instead of being followed to a target whose
    # bytes happen to match.
    try:
        on_disk = _read_regular_file(prompt_path, "the adopted prompt")
    except CollectError as exc:
        raise CollectError(f"{exc} — {refusal_tail}") from exc
    if on_disk != text.encode("utf-8"):
        raise CollectError(
            f"{prompt_path} is not the prompt this round renders for {name!r} "
            f"attempt {attempt} — the adopted attempt is DISPATCHED with "
            f"these bytes, so they are compared against the round's own "
            f"frozen clause basis before they are adopted; {refusal_tail}")
    schema_file = dispatch.get("schema_file")
    if not schema_file:
        return
    frozen_projection = record.get("projection_digest")
    if not isinstance(frozen_projection, str) or not frozen_projection:
        raise CollectError(
            f"the round record carries no frozen producer-schema projection "
            f"digest, so the schema.projected.json in {attempt_dir} cannot be "
            f"proven to be this round's — prepare a new round")
    # Hardened for the same reason as `prompt.txt` above (row r9-11).
    try:
        projection = _read_regular_file(
            Path(schema_file), "the adopted producer schema projection")
    except CollectError as exc:
        raise CollectError(f"{exc} — {refusal_tail}") from exc
    live = hashlib.sha256(projection).hexdigest()
    if live != frozen_projection:
        raise CollectError(
            f"{schema_file} is not the producer schema projection this round "
            f"froze (digest frozen {frozen_projection} vs on disk {live}) — "
            f"the adopted attempt's argv points the vendor at THIS file, so "
            f"its bytes are compared before they are adopted; {refusal_tail}")


def _adopt_orphan_attempt(packet_dir: Path, label: str, record: dict,
                          entry: dict, failed_attempt: int,
                          diagnosis: str, judged: tuple | None,
                          dry_run: bool = False) -> Path | None:
    """ADOPT an attempt K+1 that exists on disk while the record still says K.

    `retry` allocates K+1 FIRST and only then writes the diagnosis and the
    record (r3-18: allocate, then diagnose, so a failed allocation cannot make
    the leg permanently unretryable). The other side of that ordering is this
    one (gate-1 r4 row r4-9): when the diagnosis or the record write fails,
    `attempt-K+1/` is on disk and the record still names K. The next `retry`
    used to ignore the orphan entirely — it read the HIGHEST attempt, rendered
    K+2, and wrote a fabricated diagnosis into an attempt that was never
    dispatched. The numbering ran away from the record and the dispatch line
    the operator was holding went stale.

    Adoption is CONDITIONAL on the orphan's own records binding THIS entry at
    THIS attempt — ALL SIX derived values, through the one `_expected_binding`
    derivation `_evaluate` uses (gate-1 r6 row r6-3). Anything else is refused
    BY NAME: the packet dir is helper-owned, so this function never deletes a
    directory it did not write. Nothing is re-rendered — the frozen records
    are the basis, exactly as R-RETRY requires.

    ORDER (gate-1 r6, the r6-5 amendment): validate EVERYTHING, write the
    diagnosis, print the dispatch block, and write the ROUND RECORD LAST. The
    record write used to run before the print, so anything the print refused
    left the record already bumped — and the next retry then fabricated a
    diagnosis into an attempt this tool never dispatched, the exact runaway
    row r4-9 exists to stop."""
    name = entry["name"]
    adopt_attempt = failed_attempt + 1
    entry_dir = Path(packet_dir) / record["results_dir"] / name
    attempt_dir = entry_dir / f"attempt-{adopt_attempt}"
    refusal_tail = ("the packet dir is helper-owned, so nothing is deleted "
                    "and nothing is adopted: prepare a new round")
    try:
        # HARDENED, like the two adopted BYTE bases below (gate-1 r10 row
        # r10-7): these two records decide the adoption and are then
        # PRINTED for the operator to run, and they were read with
        # `read_text()` — a symlink at either name was followed and a FIFO
        # blocked the one recovery command this round offers, forever, in a
        # directory this helper owns. `_read_regular_file` raises
        # `CollectError` with the path named, which is this function's own
        # refusal shape, so it rides out unchanged.
        binding = json.loads(
            _read_regular_file(attempt_dir / "binding.json",
                               "the orphan binding record").decode("utf-8"))
        dispatch = json.loads(
            _read_regular_file(attempt_dir / "dispatch.json",
                               "the orphan dispatch record").decode("utf-8"))
    # row r7-k3: same tuple as every other record load in this file — a
    # RecursionError out of `json.loads` used to escape as a traceback from
    # a path that promises a one-line refusal.
    except (CollectError, OSError, ValueError, RecursionError,
            UnicodeDecodeError) as exc:  # V3: every reader refusal too
        raise CollectError(
            f"{attempt_dir} already exists but its own records are unreadable "
            f"({' '.join(str(exc).split())}) — {refusal_tail}")
    # A NON-OBJECT PARSES CLEANLY AND IS STILL NOT A RECORD (row r6-4): both
    # `binding.get(...)` and every `dispatch.get(...)` below would raise an
    # AttributeError traceback out of a refusal path that promises one line.
    for record_name, doc in (("binding.json", binding),
                             ("dispatch.json", dispatch)):
        if not isinstance(doc, dict):
            raise CollectError(
                f"{attempt_dir}/{record_name} is not an object "
                f"({type(doc).__name__}) — {refusal_tail}")
    expected = _expected_binding(record, entry, adopt_attempt)
    mismatch = sorted(k for k, v in expected.items() if binding.get(k) != v)
    if mismatch:
        raise CollectError(
            f"{attempt_dir} already exists but its binding does not bind this "
            f"entry at attempt {adopt_attempt} (mismatched: "
            f"{', '.join(mismatch)}) — {refusal_tail}")
    # The round's BOUND review conditions (R-PROMPT, R-REVIEW-WEB): the
    # launch switch, the re-rendered dispatch and the re-rendered prompt are
    # all judged against them.
    conditions = _bound_conditions(packet_dir, label, record, name)
    _check_dispatch_record(dispatch, attempt_dir, expected["route"],
                           refusal_tail,
                           web=conditions["review_web_authorized"],
                           family=expected["family"],
                           bound_agent=(entry.get("preset") or {}).get("agent"))
    # THE RECORD IS COMPARED, NOT TRUSTED (gate-1 r7 row r7-x4). Everything
    # above proves the orphan's binding names THIS entry at THIS attempt and
    # that its dispatch record is well TYPED — but the argv, env and paths
    # were then read back verbatim and printed for the operator to RUN, so a
    # record planted in the orphan directory substituted the PROGRAM under
    # this entry's name (the r5-1 read-back class, one file over). The
    # round's own frozen roster entry re-renders the same attempt and the six
    # invocation members must EQUAL the record. Nothing is re-rendered INTO
    # the attempt: on equality the ON-DISK bytes are adopted, exactly as
    # R-RETRY requires.
    rendered = _rendered_dispatch(packet_dir, record, entry, adopt_attempt,
                                  attempt_dir,
                                  conditions["review_web_authorized"])
    differs = sorted(f for f in _ADOPT_COMPARED_FIELDS
                     if dispatch.get(f) != rendered.get(f))
    if differs:
        raise CollectError(
            f"{attempt_dir}/dispatch.json is not the invocation this round "
            f"renders for {name!r} attempt {adopt_attempt} (differs: "
            f"{', '.join(differs)}) — the adopted record is what the "
            f"operator DISPATCHES, so it is compared against the frozen "
            f"roster entry's own render before its bytes are adopted; "
            f"{refusal_tail}")

    # THE ALLOCATION MUST HAVE FINISHED (gate-1 r5 row r5-3). `binding.json`
    # and `dispatch.json` are the 1st and 3rd of the files `v2_write_attempt`
    # writes, and the producer schema projection is the LAST — so an
    # allocation interrupted between them satisfied both checks above while
    # `prompt.txt` or `schema.projected.json` was still missing. Adopting
    # that printed the operator an argv whose `--output-schema-file` points
    # at a file nobody wrote. The route rule is the WRITER's own: a
    # projection is required exactly when this attempt's `dispatch.json`
    # names one. Refused BY NAME; nothing is deleted.
    required = [attempt_dir / "binding.json", attempt_dir / "prompt.txt",
                attempt_dir / "dispatch.json"]
    schema_file = dispatch.get("schema_file") if isinstance(dispatch, dict) \
        else None
    if schema_file:
        required.append(Path(schema_file))
    absent = [str(path) for path in required if not path.is_file()]
    if absent:
        raise CollectError(
            f"{attempt_dir} already exists but its allocation never finished "
            f"(missing: {', '.join(absent)}) — an attempt is adopted only "
            f"when every record its route writes is on disk; {refusal_tail}")
    # EXISTENCE IS NOT IDENTITY (gate-1 r8 row r8-7). The two files above are
    # only proven to BE there; they are also the two the adopted invocation
    # feeds the vendor, so their BYTES are compared against this round's
    # frozen prompt-clause manifest and producer-schema digest before the
    # attempt is adopted. Runs before anything is written.
    _check_adopted_bytes(record, entry, adopt_attempt, attempt_dir, dispatch,
                         refusal_tail, conditions)
    diagnosis_path = (entry_dir / f"attempt-{failed_attempt}"
                      / "retry-diagnosis.txt")
    # A SYMLINK IS NEVER WRITTEN THROUGH (gate-1 r5 row r5-9). The non-adopt
    # path already refuses one at this path; here it was folded into the
    # same condition as "already diagnosed" and treated as evidence that
    # exists — so a link somebody planted silently stood in for attempt
    # {failed_attempt}'s own record.
    if diagnosis_path.is_symlink():
        raise CollectError(
            f"{diagnosis_path} is a symlink — the retry diagnosis is "
            f"evidence about attempt {failed_attempt} and lives in that "
            f"attempt's own directory, never behind a link; {refusal_tail}")
    # EXISTENCE IS NOT A DIAGNOSIS (gate-1 r6 row r6-6). The retain branch
    # keyed on `exists()`, so an EMPTY file — what an interrupted write
    # leaves behind, the very failure this adoption path exists for — was
    # "retained" and the text the operator typed on THIS invocation was
    # discarded under a success line: attempt K then carried no record of
    # why it failed at all. Only a REGULAR, non-blank file is a prior
    # diagnosis; a blank one is replaced (and the print says so); anything
    # that is not a regular file is refused, as the symlink above is.
    diagnosis_existed = False
    diagnosis_was_blank = False
    if diagnosis_path.exists():
        if not diagnosis_path.is_file():
            raise CollectError(
                f"{diagnosis_path} exists but is not a regular file — the "
                f"retry diagnosis is evidence about attempt {failed_attempt} "
                f"and lives in that attempt's own directory as a plain file; "
                f"{refusal_tail}")
        # THROUGH THE BOUNDED, SYMLINK-REFUSING READER (gate-1 r20 row
        # r20-3): this was `stat()` then `read_text()` — the one unbounded,
        # link-following read of evidence left here, so a file that grew, or
        # a symlink swapped in after the checks above, was read whole (and a
        # blank link target was then overwritten THROUGH the link). A file
        # over the evidence cap is refused naming it.
        try:
            raw = _read_regular_file(diagnosis_path,
                                     "the existing retry diagnosis")
        except CollectError as exc:
            raise CollectError(f"{' '.join(str(exc).split())} — "
                               f"{refusal_tail}") from exc
        # WHITESPACE IS BLANK AT ANY SIZE THIS HELPER WILL READ (row r7-k4,
        # completed by gate-1 r21 row r21-5). The probe stopped at 4096
        # bytes and called anything larger content, so 4097 bytes of
        # whitespace was RETAINED as a prior diagnosis and the operator's
        # typed text was dropped; a later 1 MiB probe constant kept the same
        # shape one size up. The read above is already bounded by the 64 MiB
        # evidence cap, so blankness is decided on the bytes it returned —
        # at ANY size under the cap.
        blank = not raw.decode("utf-8", errors="replace").strip()
        diagnosis_existed = not blank
        diagnosis_was_blank = blank
    if dry_run:  # `_adoption_blocked`: every check above, nothing written
        return None
    _seal_replaced(entry_dir / f"attempt-{failed_attempt}", entry,
                   failed_attempt, *judged)
    try:
        if not diagnosis_existed:
            diagnosis_path.write_text(
                diagnosis if diagnosis.endswith("\n") else diagnosis + "\n",
                encoding="utf-8")
    except OSError as exc:
        # One line, never a traceback — the same promise every other refusal
        # in this file keeps (row r5-9).
        raise CollectError(
            f"could not record the adoption of {attempt_dir} "
            f"({' '.join(str(exc).split())}) — free the cause and retry "
            f"again (it adopts the same attempt)") from exc
    review_scratch = _load_sibling("review_scratch")
    print(f"retry {name}: attempt {adopt_attempt} was already allocated while "
          f"the round record still said {failed_attempt} — ADOPTED (its "
          f"binding names this entry at attempt {adopt_attempt}); nothing was "
          f"re-rendered")
    if diagnosis_existed:
        # NEVER CLAIM A WRITE THAT DID NOT HAPPEN (row r5-9). The interrupted
        # retry had already diagnosed attempt {failed_attempt}; that record
        # stands, and the text typed on THIS invocation was not stored
        # anywhere. Saying "diagnosis recorded" here dropped the operator's
        # freshly typed explanation under a success line.
        # SAY HOW IT WAS JUDGED (gate-1 r21 row r21-5): the whole file was
        # read (bounded by the evidence cap), so "retained" is a reading of
        # its content — never a size judgement.
        print(f"  existing diagnosis retained at {diagnosis_path} "
              f"(blank/non-blank decided on its content); the typed "
              f"text was NOT stored (attempt {failed_attempt} was already "
              f"diagnosed by the retry that allocated attempt "
              f"{adopt_attempt})")
    elif diagnosis_was_blank:
        print(f"  the EMPTY (or whitespace-only) diagnosis file at "
              f"{diagnosis_path} was replaced by the text typed on this "
              f"invocation (an interrupted retry left it blank, so attempt "
              f"{failed_attempt} carried no diagnosis)")
    else:
        print(f"  diagnosis recorded at {diagnosis_path} (attempt "
              f"{failed_attempt}'s own artifacts are retained)")
    print(f"leg outputs ({label}):")
    # THE PRINTED BINDING IS THE DERIVATION, NEVER THE ON-DISK COPY (row r6-3,
    # the x amendment). The two are proven equal above, so this changes no
    # printed byte today — it removes the READ-BACK: the `--expected-*` flags
    # the operator runs come from the round record, the frozen roster entry
    # and the directory name, exactly as `_evaluate`'s admission does.
    # THE SAME SIBLING SET THE COLLECTOR USES (gate-1 r11 row r11-5): the
    # hook load check is a ROUND check, and a printed command that named
    # only this attempt's audit read a PASS out of one leg's runs against
    # every leg's conversations.
    review_scratch.v2_print_dispatch(
        {"entry": entry["leg"], "dir": str(attempt_dir),
         "attempt": adopt_attempt, "dispatch": dispatch,
         "binding": dict(expected)},
        Path(packet_dir), Path(record["worktree"]), label,
        _agy_round_audits(packet_dir, record,
                          dispatch.get("read_audit_path")))
    _print_round_hook_checks(packet_dir, record, label, name)
    # THE ROUND RECORD IS THE LAST WRITE (the r6-5 amendment): everything
    # above can still refuse, and a refusal must leave the record naming the
    # attempt this round actually dispatched.
    try:
        entry["attempt"] = adopt_attempt
        _write_record(packet_dir, label, record)
    except OSError as exc:
        raise CollectError(
            f"could not record the adoption of {attempt_dir} "
            f"({' '.join(str(exc).split())}) — free the cause and retry "
            f"again (it adopts the same attempt)") from exc
    return attempt_dir


def retry(packet_dir, label: str, name: str, diagnosis: str) -> Path:
    """Allocate attempt K+1 for an entry that did NOT return a valid verdict.

    Every earlier artifact is retained, with two exceptions that `retry`
    removes and then refuses, allocating nothing: a refused reply's cut-short
    seal beside an admissible raw.json (G4) and an unsealed admitted.json the
    admission refuses beside an admissible raw.json (G2). Neither is bound by
    any seal or record (a collection never records a cut-short seal, G1), and
    each stands between the saved reply and its `admit:` line, so its removal
    only lets that reply be judged (Y1). The diagnosis is written INTO the
    failed attempt (it is evidence about that attempt), and the new attempt is
    rendered from the round's OWN frozen roster entry, so the basis is
    provably unchanged (R-RETRY)."""
    packet_dir = Path(packet_dir)
    record = _read_record(packet_dir, label)
    # The ADMISSION basis is checked here too (row r8-10): `retry` evaluates
    # the entry through the same admission, and R-RETRY's "nothing changed"
    # covers the contract exactly as it covers the clauses and the producer
    # projection. Before any evaluation, so a refusal leaves nothing behind.
    _check_contract_basis(record, "retry")
    bound = _bound_metadata(packet_dir, label, record, "the retry")
    # The clause, projection and preset basis, re-derived from the installed
    # files BEFORE the adoption and the allocation below (R-RETRY: a changed
    # control refuses before an attempt is allocated; cases C19 / C20).
    _check_installed_basis(packet_dir, label, record, "the retry")
    recorded = _recorded_seals(packet_dir, label)
    by_name = {e["name"]: e for e in record["entries"]}
    entry = by_name.get(name)
    if entry is None:
        raise CollectError(
            f"no roster entry named {name!r} in this round "
            f"(entries: {', '.join(sorted(by_name))})")
    if not entry.get("enabled"):
        raise CollectError(f"roster entry {name!r} is disabled in this round — "
                           f"an unselected leg is never started")
    if entry.get("skipped_reason"):
        raise CollectError(
            f"roster entry {name!r} was SKIPPED this round "
            f"({entry['skipped_reason']}) — it never ran, so there is no "
            f"attempt to retry; a skipped leg is not agreement either")
    text = (diagnosis or "").strip()
    if not text:
        raise CollectError(
            "retry requires a non-empty diagnosis: R-RETRY allows a retry only "
            "for a leg that FAILED TO RUN, and the diagnosis is the record of "
            "what that failure was")
    # A retried agy leg is a new inference with web on a true round: its
    # prerequisite is checked before anything is adopted or allocated
    # (R-REVIEW-WEB, case C32), as `prepare` checks it for the round.
    refusal = _load_sibling("review_scratch")._v2_agy_web_refusal(
        bound.get("review_web_authorized", False), [entry.get("route")])
    if refusal is not None:
        raise CollectError(f"roster entry {name!r}: {refusal}")

    # `_evaluate` now SCOPES the unusable-attempt-directory refusal to the
    # entry (row r5-11), so `retry` runs the same scan itself: a retry has to
    # allocate the NEXT number, and it cannot know what that is while a
    # directory in the tree carries no readable attempt number. Same reason
    # text, raised as the refusal it has always been.
    attempts = _attempts(Path(packet_dir) / record["results_dir"] / name)
    # THE RECORDED ATTEMPT IS ADMITTED FIRST, BEFORE ANY ADOPTION LOGIC
    # (gate-1 r10 row r10-1). `_evaluate` used to read the HIGHEST on-disk
    # attempt, so a planted `attempt-K+1/` turned the RECORDED attempt K's
    # valid BLOCKING verdict into an `invalid` state: this refusal never
    # fired, the orphan arm below adopted the planted directory, and the
    # next collection admitted ITS verdict — the completed review was gone.
    # `_evaluate` now evaluates exactly attempt K (row r10-2), so this rung
    # is the recorded attempt's own state and adoption is reachable only
    # when that attempt did NOT complete.
    # V1: the replaced attempt's digests are taken BEFORE it is judged, and
    # its seal binds exactly these (`_seal_replaced` refuses on a change).
    found = _seal_files(Path(packet_dir) / record["results_dir"] / name
                        / f"attempt-{entry['attempt']}", entry, as_found=True)
    result = _evaluate(packet_dir, record, entry, recorded, label)
    # V4: an answered attempt is sealed with its state (an inadmissible
    # answer is `invalid`); one holding no answer failed to run. A native
    # attempt's answer is its saved reply, raw.json (Z4).
    answered = ((found["result"][1] is not None and result.state == "invalid")
                or (entry.get("family", entry["vendor"]) == "claude"
                    and found["receipt"][1] is not None))
    judged = (found, "invalid" if answered else "failed-to-run",
              _expected_binding(record, entry, entry["attempt"]))
    if result.state == "valid":
        raise CollectError(
            f"roster entry {name!r} returned a VALID verdict "
            f"({result.verdict!r}) on attempt {result.attempt}: a completed "
            f"review is not a transport failure; a changed basis is a new "
            f"round (prepare r<N+1>) and EVERY entry reviews it again "
            f"(R-REREVIEW)")
    # EVERY REFUSAL BEFORE ANY ADOPTION OR ALLOCATION is `_adoption_blocked`
    # — the one predicate `collect` also asks about an orphan, so the two
    # never disagree about what a retry does here (tail follow-up).
    blocked = _adoption_blocked(
        packet_dir, label, record, entry, attempts, recorded.get(name, {}),
        lambda: _retry_cannot_certify(packet_dir, record, entry,
                                      entry["attempt"]), result)
    if blocked is not None and blocked[0] == "take":
        # G2 / Y1: the bad admitted.json is taken away here, never by hand.
        replaced = (Path(packet_dir) / record["results_dir"] / name
                    / f"attempt-{entry['attempt']}")
        try:
            os.unlink(replaced / "admitted.json")
        except OSError as exc:
            raise CollectError(
                f"roster entry {name!r}: attempt {entry['attempt']}: "
                f"{blocked[2]}; it could not be removed "
                f"({' '.join(str(exc).split())}) — free the cause and retry "
                f"again") from exc
        raise CollectError(
            f"roster entry {name!r}: attempt {entry['attempt']}: the reply "
            f"was saved (raw.json) but never admitted; the admitted.json "
            f"beside it was not its admitted result and was removed, nothing "
            f"was allocated — run the printed `admit:` line for this attempt, "
            f"then collect again; a retry would put a second answer beside "
            f"the saved one (R-BIND, case C66)")
    if blocked is not None:
        raise CollectError(blocked[1] + blocked[2])
    record_attempt = entry["attempt"]
    if attempts[-1][0] == record_attempt + 1:
        return _adopt_orphan_attempt(packet_dir, label, record, entry,
                                     record_attempt, text, judged)
    attempt_dir = (packet_dir / record["results_dir"] / name
                   / f"attempt-{result.attempt}")
    diagnosis_path = attempt_dir / "retry-diagnosis.txt"
    if diagnosis_path.is_symlink() or diagnosis_path.exists():
        raise CollectError(
            f"{diagnosis_path} already exists — attempt {result.attempt} has "
            f"already been diagnosed and retried; collect the CURRENT attempt "
            f"instead of re-diagnosing a closed one")

    review_scratch = _load_sibling("review_scratch")
    worktree = Path(record["worktree"])
    alloc = review_scratch.v2_render_attempt(
        packet_dir, worktree, label, record["review_id"],
        record["content_digest"], entry["leg"], result.attempt + 1,
        _bound_conditions(packet_dir, label, record, name))
    # THE PROMPT, PRODUCER-SCHEMA AND PRESET BASIS were proven unchanged
    # before any evaluation (`_check_installed_basis`, gate-1 rows r4-16 /
    # r5-7 / r7-x1, cases C19 / C20), and the render above reads the same
    # installed files, so the allocation below re-runs the SAME basis.
    # ALLOCATE FIRST, diagnose second (gate-1 r3 row r3-18). The diagnosis
    # used to be written before the allocation, and the guard above refuses
    # any attempt that already carries one — so an allocation that failed
    # (an unwritable results tree, a directory that raced in) left the leg
    # PERMANENTLY unretryable: the only recovery command this round offers
    # refused on a file the failed run had just planted. `v2_write_attempt`
    # is itself the exclusive-create allocation, so once it returns the
    # diagnosis records a step that actually happened.
    _seal_replaced(attempt_dir, entry, result.attempt, *judged)
    review_scratch.v2_write_attempt(alloc)
    # ONE LINE, NEVER A TRACEBACK (gate-1 r9 row r9-12). This write was bare,
    # so an OSError here — an unwritable attempt directory, a full disk —
    # escaped as a traceback out of the ONE recovery command this round
    # offers, and it does so AFTER `v2_write_attempt` has already allocated
    # attempt K+1, i.e. in the state the operator most needs a readable
    # refusal for. The adoption path one function over has always converted
    # this exact OSError; same rule on the normal path.
    try:
        diagnosis_path.write_text(text if text.endswith("\n") else text + "\n",
                                  encoding="utf-8")
    except OSError as exc:
        raise CollectError(
            f"attempt {result.attempt + 1} was allocated at {alloc['dir']}, "
            f"but the diagnosis could not be written to {diagnosis_path} "
            f"({' '.join(str(exc).split())}) — the round record still names "
            f"attempt {result.attempt}; fix the permissions and retry "
            f"{name!r} again (the allocated attempt is ADOPTED, never "
            f"re-allocated)") from exc
    entry["attempt"] = result.attempt + 1
    _write_record(packet_dir, label, record)

    print(f"retry {name}: attempt {result.attempt} ({result.state}: "
          f"{result.reason}) -> attempt {result.attempt + 1}")
    print(f"  diagnosis recorded at {diagnosis_path} (attempt "
          f"{result.attempt}'s own artifacts are retained)")
    print(f"leg outputs ({label}):")
    # THE SAME SIBLING SET THE COLLECTOR USES (gate-1 r11 row r11-5) — see
    # the adoption path's note. The record already names attempt K+1 here,
    # so the retried entry's own SUPERSEDED attempt is one of the siblings,
    # which is exactly what the shared hook log holds (row r11-1).
    review_scratch.v2_print_dispatch(
        alloc, packet_dir, worktree, label,
        _agy_round_audits(packet_dir, record,
                          (alloc.get("dispatch") or {}).get("read_audit_path")))
    _print_round_hook_checks(packet_dir, record, label, name)
    return Path(alloc["dir"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _relax_std_stream_errors() -> None:
    """NEVER DIE ON AN ENCODER (gate-1 r6 row r6-16). Entry-point only.

    Operator text here is em-dash-bearing English and `sys.stdout`'s error
    handler is STRICT, so under a non-UTF-8 locale the first such line raised
    UnicodeEncodeError and took the command down instead of printing its
    outcome. Only the ERROR HANDLER changes (the encoding is untouched), and
    a stream that cannot be reconfigured is left alone. Full rationale:
    `review_scratch.py::_relax_std_stream_errors` — each v2 lib is separately
    executable and separately vendored, so the call is repeated at each entry
    rather than imported across them."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass


def main(argv: list) -> int:
    _relax_std_stream_errors()
    try:
        if len(argv) == 3 and argv[0] == "collect":
            return collect(Path(argv[1]), argv[2]).exit_code
        if len(argv) == 6 and argv[0] == "retry" and argv[4] == "--diagnosis":
            retry(Path(argv[1]), argv[2], argv[3], argv[5])
            return EXIT_AGREED
    except _HostFault as exc:
        # BEFORE the CollectError arm: a host fault is not a refusal about
        # the round (row r7-c4), and 64 is this file's host/usage exit.
        print(f"collect_v2: HOST FAULT: {' '.join(str(exc).split())}",
              file=sys.stderr)
        return EXIT_USAGE
    except CollectError as exc:
        print(f"collect_v2: refused: {' '.join(str(exc).split())}",
              file=sys.stderr)
        return EXIT_REFUSE
    print(_USAGE, file=sys.stderr)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
