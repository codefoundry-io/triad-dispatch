#!/usr/bin/env python3
"""collect_v2.py — the ALL-ENTRY v2 collector and the diagnosed retry
allocation, host A side (plan `2026-09-21-host-a-v2-implementation`, S5).

It reads the round record `<packet-dir>/.roster-r<N>.json` that
`review_scratch.py prepare --v2` wrote, takes each enabled non-skipped
entry's RECORDED attempt (the one that record names), and folds
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
        configuration differs from the round's bound basis, an installed
        toolkit that differs from the round's recorded map, unknown or
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
# THE CUSTODY LINE, AS THE PRODUCER WRITES IT. The agy wrapper
# emits `read-audit-file: <abs path>` through `_common.log`, which prefixes
# every line with `[<ISO-8601 timestamp>] `. Those two are the whole
# tolerance: the prefix is stripped and the REST of the line must equal the
# marker plus the audit path's filesystem bytes, PERCENT-ESCAPED (below).
_CUSTODY_MARKER = b"read-audit-file: "
_LOG_PREFIX = re.compile(rb"^\[[^\]]*\] ")
# THE VALUE IS PERCENT-ESCAPED FILESYSTEM BYTES: the
# wrapper emits `_common._summary_field(<path>)`, so this side compares the
# SAME encoding. Re-implemented here because this module may not import
# `_common`; t15 axis 66 pins the safe set and the output equal to it.
_CUSTODY_FIELD_SAFE = "/._-~+=@,:"


def _custody_field(raw: bytes) -> bytes:
    """`_common._summary_field` over filesystem bytes, as ASCII bytes."""
    return urllib.parse.quote(raw, safe=_CUSTODY_FIELD_SAFE).encode("ascii")
# The exit BOTH agy evidence tools reserve for "this invocation could not RUN
# at all" (`read_audit_gate.sh` usage, `agy_hook.py check` usage). It is the
# same 64 `verdict_v2` uses for a host fault, and it is treated the same way
# here.
_EVIDENCE_TOOL_HOST_RC = 64
# The run-log directory each WRAPPER route's wrapper writes its receipt under
# (the `cli` its `emit_run_log` call passes), keyed by the binding's route
# (None = codex, the one family with one route) (R-BIND:
# `<attempt>/logs/<cli>/runs/`, set by `TRIAD_REVIEW_LOG_DIR`).
_RUN_LOG_CLI = {None: "codex", "agy": "antigravity", "gemini": "gemini"}
_RECEIPT_REMEDY = ("the leg ran with a command other than the recorded one — "
                   "retry this entry and run its printed line verbatim "
                   "(R-BIND)")

# THE SEAL OF A RECORDED ATTEMPT (R-BIND, case C66). The native admission,
# or on a wrapper route the first collection that judges an answer, writes
# this file into the attempt's own directory, binding the digests of its
# result, receipt and read evidence; every later collection re-checks them. The name is
# `verdict_v2._SEAL_NAME` (read below, after `_load_sibling`), which refuses a
# re-admission into a sealed attempt.
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


_SEAL_NAME = _load_sibling("verdict_v2")._SEAL_NAME


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
    # Read through the one hardened reader: the record names WHICH attempt
    # each entry is evaluated at. An absent record keeps its own "this label
    # was not prepared" reason.
    try:
        os.lstat(path)
    except FileNotFoundError:
        raise CollectError(
            f"no round record at {path} — this round was not prepared by this "
            f"version's `prepare` (an earlier version's round has none): close "
            f"the packet dir and prepare a new round") from None
    except OSError:
        pass        # `_read_regular_file` names every other stat failure
    try:
        data = _read_regular_file(path, "the round record")
    except CollectError as exc:
        raise CollectError(f"{exc} — prepare a new round") from exc
    try:
        doc = json.loads(data.decode("utf-8"))
    # Every way a record load can fail: RecursionError is not a ValueError.
    except (OSError, ValueError, RecursionError, UnicodeDecodeError) as exc:
        raise CollectError(f"the round record {path} is unreadable: "
                           f"{' '.join(str(exc).split())}") from exc
    if not isinstance(doc, dict) or "entries" not in doc:
        raise CollectError(f"the round record {path} is malformed (no entries)")
    return doc


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
    the record (collect, retry) refuses it here. A changed
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
    copies: a retry re-renders a prompt only when the delivery
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
    """The bytes of a plain REGULAR file, or a `CollectError` naming it.

    `Path.read_bytes()` FOLLOWS a symlink, so every helper-owned read in
    this file goes through `verdict_v2._read_regular_file_no_symlink`, the
    review libs' one hardened reader, and refuses a non-regular path BY NAME:
    a link planted at a name this helper allocated would otherwise be read as
    if it were the file. The text names the CAUSE only; each caller names the
    remedy that works where it reads (R1: under `results-r<N>/` nothing is
    removed by hand).
    """
    path = Path(path)
    data, reason = _load_sibling("verdict_v2")._read_regular_file_no_symlink(path)
    if reason is None:
        return data
    unreadable = f"cannot read {path}: "
    if reason.startswith(unreadable):
        cause = " ".join(reason[len(unreadable):].split())
        raise CollectError(f"{label} {path} is unreadable ({cause})")
    if reason == f"{path} is a symlink, refusing to read":
        raise CollectError(
            f"{label} {path} is a symlink — this helper reads the bytes it "
            f"allocated, never a link to somewhere else")
    raise CollectError(
        f"{label} {path} is not a regular file — this helper reads the "
        f"bytes it allocated, never a special path somebody planted")


def _write_json(path: Path, doc: dict) -> None:
    """Write one of this helper's own records: temp file + `os.replace`, so a
    reader sees the old record or the new one, never a half-written one."""
    tmp = path.with_name(f".tmp-{os.getpid()}-{path.name}")
    try:
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise CollectError(f"{path} could not be written "
                           f"({' '.join(str(exc).split())})") from exc


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


_ATTEMPT_NAME = re.compile(r"attempt-([1-9][0-9]*)")


def _attempts(entry_dir: Path) -> list:
    """`[(number, path)]` of the entry's `attempt-<N>` directories, in number
    order. A name starting `attempt-` that is not `attempt-<N>` (N >= 1, no
    leading zero), or such a name that is not a real directory, is refused."""
    found = []
    try:
        entries = list(os.scandir(entry_dir))
    except OSError:
        return []
    for item in entries:
        if not item.name.startswith("attempt-"):
            continue
        m = _ATTEMPT_NAME.fullmatch(item.name)
        if m is None or not item.is_dir(follow_symlinks=False):
            raise CollectError(
                f"{item.path} is not an attempt directory this helper "
                f"allocates (attempt-<N>, N ≥ 1, no leading zero) — prepare a "
                f"new round")
        found.append((int(m.group(1)), Path(item.path)))
    return sorted(found, key=lambda p: p[0])


# ---------------------------------------------------------------------------
# per-entry evaluation
# ---------------------------------------------------------------------------
def _result_filename(family: str) -> str:
    """Where THIS family's admitted result lives inside its attempt dir: a
    wrapper leg's stdout IS its verdict document; the native claude leg's raw
    reply is prose-tolerant, so its admitted canonical form is the subject."""
    return "admitted.json" if family == "claude" else "verdict.json"


def _run(cmd: list) -> subprocess.CompletedProcess:
    # UTF-8 IS PINNED, NEVER TAKEN FROM THE LOCALE: `text=True` alone decodes
    # with `locale.getpreferredencoding()`, and the gate's own diagnostics are
    # UTF-8. `errors="replace"` keeps a byte nobody can decode from raising.
    # Same pin `_common.py` applies to every vendor pipe.
    return subprocess.run(cmd, capture_output=True, text=True, check=False,
                          encoding="utf-8", errors="replace")


def _token(text: str, prefix: str) -> str:
    """The evidence tool's summary token (`<prefix><STATE>`) from its last
    summary line."""
    for line in reversed(text.splitlines()):
        if line.startswith(prefix):
            return line.split()[0]
    return f"{prefix}<no summary line>"


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
    ASSEMBLED directory, not evidence — the misfiling a four-leg round makes
    easy to reach by hand.

    A WHOLE LINE, COMPARED IN FILESYSTEM BYTES: the producer's own
    `_common.log` timestamp prefix REQUIRED and stripped, nothing else
    tolerated, against `os.fsencode` of the audit path (the exact byte
    sequence the kernel holds), percent-escaped exactly as the producer
    escapes it (`_custody_field`), so a longer path that merely contains
    this one never matches and a path carrying a newline or an undecodable
    byte is still ONE line on both sides.

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
    # THE PREFIX MUST BE THERE: the wrapper's `_common.log` always
    # timestamps, so only a line whose
    # prefix MATCHES at its start is the producer's.
    def _custody(line: bytes) -> bool:
        line = line.rstrip(b"\r")
        m = _LOG_PREFIX.match(line)
        return m is not None and line[m.end():] == want
    if not any(_custody(line) for line in raw.split(b"\n")):
        # NO AUDIT AT ALL. This runs only after a
        # valid verdict was admitted, so the attempt RAN and wrote no read
        # audit: the hook load check reads it as a dispatched sibling with no
        # audit (INCONCLUSIVE) for every later attempt of the round, so a
        # re-dispatch inside the round cannot clear it — the remedy is a NEW
        # round. A PRESENT audit with no custody line is a NEW round too: a
        # misfiled or foreign audit stays a sibling (ambiguous or
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


def _agy_evidence_reason(packet_dir: Path, record: dict,
                         attempt_dir: Path) -> str | None:
    """None when this agy attempt's containment evidence holds, else the
    one-line reason it does not. BOTH checks run exactly as `prepare --v2`
    printed them — same audit file, same required-read set, same hook log.

    A `_EVIDENCE_TOOL_HOST_RC` from EITHER tool is a `_HostFault`, never this
    entry's `invalid`. Both reserve that code for "this invocation could not
    RUN at all" — a required file the round named is gone (a round tree
    removed between prepare and collect), an absent `hook_log`, an unusable
    argv — a fault that says nothing about any leg."""
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
            f"round tree removed between prepare and collect, an unusable "
            f"argv), not a verdict about "
            f"this leg; the collection is STOPPED and no per-entry state was "
            f"written, so repair the host and collect again rather than "
            f"re-dispatching the legs")
    if gate.returncode != 0:
        return (f"read-audit gate failed "
                f"({_token(gate.stdout, 'READ_AUDIT_GATE_')}, rc={gate.returncode})"
                f" — an ungated agy answer is UNVERIFIED, never agreement")
    hook = _run(["python3", str(LIB_DIR / "agy_hook.py"), "check",
                 str(audit), str(record.get("hook_log", ""))])
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
                f" — agy's --agent fails OPEN, so an unproven hook layer "
                f"leaves this leg's containment unverified")
    return None


def _expected_binding(record: dict, entry: dict, attempt: int) -> dict:
    """The SIX values an attempt's `binding.json` must EQUAL, derived from
    outside the attempt directory: `review_id` / `content_digest`
    from the ROUND RECORD, `family` / `leg_name` / `route` from the round's
    FROZEN ROSTER ENTRY, `attempt` from the DIRECTORY NAME the caller parsed.

    ONE derivation for every reader: this is the single copy."""
    return {"review_id": record.get("review_id"),
            "family": entry.get("family", entry["vendor"]),
            "content_digest": record.get("content_digest"),
            "leg_name": entry["name"],
            "attempt": attempt,
            "route": entry.get("route")}


def _sealed_paths(attempt_dir: Path, entry: dict) -> dict:
    """The three files a recorded attempt's seal binds, DERIVED from the
    round's frozen roster entry (never read back from the seal, the
    `_expected_binding` rule): the RESULT the collector admits, the RECEIPT of the dispatch that
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
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("not a regular file")
            fh = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
        with fh:
            return hashlib.file_digest(fh, "sha256").hexdigest()
    except OSError as exc:
        # the one reader names the cause (a symlink, a special file, an OS
        # error); the line below answers a path that has changed since
        _read_regular_file(path, "the sealed file")
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


def _seal_files(attempt_dir: Path, entry: dict) -> dict:
    """`{role: None | [file name, sha256 | None]}` for the files a seal binds,
    as they are NOW (a `CollectError` names one that cannot be read)."""
    return {role: (None if path is None
                   else [path.name, _bound_digest(role, path)])
            for role, path in _sealed_paths(attempt_dir, entry).items()}


def _write_seal(attempt_dir: Path, entry: dict, attempt: int, files: dict,
                state: str) -> None:
    """SEAL the attempt this collection records (R-BIND, case C66), with the
    digests of the bytes this collection JUDGED (`files`) and the state it
    judged them in — `valid`, or `invalid` for an answer that was not
    admissible (a retry stays open for that one: it did not return a valid
    verdict, R-RETRY).

    Written ONCE: exclusive-created through a pid-unique temp file and a hard
    link, so an existing seal — or anything planted at its name — is never
    replaced. A refusal is a `CollectError` naming the attempt."""
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
            os.link(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    except OSError as exc:
        raise CollectError(
            f"the seal {target} of {entry['name']!r} attempt {attempt} could "
            f"not be written ({' '.join(str(exc).split())}) — a result is "
            f"recorded only together with its seal; inspect that attempt "
            f"directory, then collect again") from exc


def _seal_replaced(attempt_dir: Path, entry: dict, attempt: int,
                   found: dict, state: str) -> None:
    """RECORD the attempt a retry replaces (R-BIND, case C66; host B's
    FAILED_TO_RUN / INVALID terminals): seal it in the `state` retry's
    judgement gave over `found`, the digests retry took once before that
    judgement — an empty or absent result included, and a refused native
    reply's raw.json — so a later write into it is an integrity failure,
    never an unjudged answer. An existing seal of any kind is kept as it is.
    Runs before the next attempt is allocated; a refusal allocates
    nothing."""
    if os.path.lexists(attempt_dir / _SEAL_NAME):
        return
    try:
        _write_seal(attempt_dir, entry, attempt, found, state)
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


def _raw_admissible(attempt_dir: Path, expected: dict) -> bool:
    """True when the native admission, re-run on raw.json as it is now,
    admits it against `expected`."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return _load_sibling("verdict_v2")._admit_raw_with_text(
                _read_regular_file(attempt_dir / "raw.json", "the native "
                                   "reply").decode("utf-8"), expected,
                _load_sibling("review_scratch")._V2_END_MARKER)[0].ok
    except (CollectError, UnicodeDecodeError):
        return False


def _saved_not_admitted(attempt_dir: Path, expected: dict) -> str | None:
    """`_ADMIT_FIRST` when the attempt holds a native reply saved in a
    regular raw.json that the admission would admit against `expected`,
    with no seal and no admitted.json — a saved answer never admitted (M1);
    else None. A refused reply is no answer to admit: collection reports the
    attempt as not admitted and `retry` stays open (it seals the attempt
    when it replaces it)."""
    if (os.path.lexists(attempt_dir / _SEAL_NAME)
            or os.path.lexists(attempt_dir / "admitted.json")
            or not _raw_admissible(attempt_dir, expected)):
        return None
    return _ADMIT_FIRST


_ADMIT_FIRST = ("the reply was saved (raw.json) but never admitted — run the "
                "printed `admit:` line for this attempt, then collect again")


def _seal_reason(attempt_dir: Path, entry: dict, attempt: int,
                 recorded_sha: str | None = None) -> str | None:
    """None when the attempt is unsealed and no collection recorded it, or
    every file its seal bound still holds the recorded bytes; else the
    integrity failure.

    A recorded attempt is sealed (R-BIND, case C66): a change, removal or
    replacement of its result, receipt, read evidence or seal after the
    record is refused, never re-admitted — the entry is INVALID, so the round
    can never be AGREED on it. `recorded_sha` is the seal digest the round's
    collection record holds for this attempt. An unreadable seal is an
    integrity failure like any other."""
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
                    recorded: dict | None, entry: dict,
                    record: dict) -> str | None:
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
        if _saved_not_admitted(earlier,
                               _expected_binding(record, entry, number)):
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
                               (recorded or {}).get(number))
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


def _evaluate(packet_dir: Path, record: dict, entry: dict,
              recorded: dict | None = None,
              label: str | None = None) -> EntryResult:
    """ONE entry's state at the attempt the ROUND RECORD names — the single
    place `collect` and `retry` both read, so the two can never disagree
    about whether a leg returned a verdict.

    THE RECORD NAMES THE ATTEMPT. Allocation is the record's act, so exactly
    `attempt-<record.attempt>/` is evaluated and a recorded attempt the tree
    does not hold is this entry's `invalid`. An attempt numbered above the
    record's is one this round never allocated: it is named in the entry's
    reason only when the recorded attempt did not itself return a valid
    verdict (it is never read, so it never displaces a completed review).
    Nothing is deleted on either arm."""
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
    # The attempt the round record allocated for this dispatched entry.
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
                               entry, record)
               or _seal_reason(attempt_dir, entry, record_attempt,
                               own.get(record_attempt)))
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
            # `retry` sealed this refused native reply invalid (C66) and
            # its next attempt was not recorded.
            result = EntryResult(**{**base.__dict__, "state": "invalid",
                                    "reason": "`retry` recorded this reply "
                                              "as refused (sealed invalid, no "
                                              "admitted result; its next "
                                              "attempt was not recorded); "
                                              "retry this entry again",
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
    else:
        result = _evaluate_unsealed(packet_dir, record, entry, attempt_dir,
                                    base, result_path)
    unallocated = [n for n, _ in attempts if n > record_attempt]
    # An unallocated attempt always blocks a retry (`_retry_blocked`'s orphan
    # arm), so beside one the entry's reason is retry's own refusal.
    blocked = (_retry_blocked(packet_dir, label, record, entry, attempts,
                              own, result)
               if result.state != "valid" and unallocated else None)
    if blocked is not None:
        # Retry's refusal (its cause and remedy) is the line; the recorded
        # attempt contributes its state only, never a remedy of its own that
        # the refused retry would contradict.
        kind, _, refusal = blocked
        tail = ("" if kind == "admit"
                or "prepare a new round" in refusal.lower()
                else " — prepare a new round")
        # The orphan arm already names the directory: it is stated once.
        orphan = f"{entry_dir}/attempt-{unallocated[-1]}"
        also = ("" if f"{orphan} already exists" in refusal
                else f"{orphan} is an attempt this round never allocated; ")
        return EntryResult(**{**result.__dict__, "reason": (
            f"{refusal}{tail} (also: {also}the recorded attempt "
            f"{record_attempt} is {result.state})")})
    return result


def _retry_blocked(packet_dir: Path, label: str, record: dict,
                   entry: dict, attempts: list, own: dict,
                   result: "EntryResult") -> tuple | None:
    """`retry`'s refusals BEFORE it writes or allocates anything, in its
    order, as `(kind, head, refusal)` — retry prints `head + refusal`,
    collect shows `refusal` (cause and retry's remedy) — else None — the ONE
    predicate `retry` raises on and `collect` reads for an attempt above the
    recorded one (tail V2 and its follow-up; never a reason's text).
    `kind`: "admit" (the printed `admit:` line first), "round" (the cause
    is already the entry's reason, or an attempt already exists above the
    recorded one; a new round). `result` is the entry's `_evaluate` state.
    """
    name = entry["name"]
    attempt = entry["attempt"]
    entry_dir = Path(packet_dir) / record["results_dir"] / name
    by_number = dict(attempts)
    replaced = entry_dir / f"attempt-{attempt}"
    expected = _expected_binding(record, entry, attempt)
    head = f"roster entry {name!r}: "
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
    if unjudged is not None:
        return ("admit", head, f"attempt {attempt}: {unjudged}; a "
                f"retry would put a second answer beside the saved one "
                f"(R-BIND, case C66)")
    if not attempts:
        return ("round", "",
                f"roster entry {name!r} has no attempt directory under "
                f"{entry_dir} — there is nothing to retry; re-prepare the "
                f"round")
    # THE RECORDED ATTEMPT IS ON DISK, OR THIS REFUSES BEFORE IT MUTATES:
    # `retry` writes THAT attempt's diagnosis into THAT directory after
    # allocating the next one, so a missing recorded directory refuses here,
    # before any allocation. Host B refuses the same shape at its custody
    # read, BEFORE anything writes (`bin/review_round_v2.py:238`).
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
    history = _history_reason(entry_dir, by_number, attempt, own, entry,
                              record)
    if history is not None:
        unjudged = any(_saved_not_admitted(by_number[n],
                                           _expected_binding(record, entry, n))
                       for n in range(1, attempt) if n in by_number)
        return ("admit" if unjudged else "round", head, history)
    # The replaced attempt must still hold what its seal bound (K9),
    # or the next attempt sits behind a history that fails the same check.
    broken = _seal_reason(replaced, entry, attempt, own.get(attempt))
    if broken is not None:
        return ("round", head, broken)
    # AN ATTEMPT ABOVE THE RECORDED ONE ALREADY EXISTS (host B's rule,
    # `bin/review_round_v2.py:291-294`): `retry` allocates attempt K+1
    # first and only then writes the diagnosis and the record, so a retry
    # stopped in between leaves `attempt-<K+1>/` beside a record naming K.
    # Allocating past it would run the numbering away from the record, and
    # writing into it would claim a dispatch nobody recorded, so every gap
    # width refuses here, before any write; the packet dir is helper-owned
    # and nothing is deleted. A stop mid-retry is an ordinary failure whose
    # recovery is a new round.
    on_disk = attempts[-1][0]
    if on_disk > attempt:
        return ("round", head,
                f"{entry_dir}/attempt-{on_disk} already exists while the "
                f"round record names attempt {attempt} (an interrupted "
                f"retry) — nothing is allocated; prepare a new round")
    return None


def _evaluate_unsealed(packet_dir: Path, record: dict, entry: dict,
                       attempt_dir: Path, base: EntryResult,
                       result_path: str) -> EntryResult:
    """`_evaluate_recorded` for an attempt no collection or admission has
    sealed yet, carrying the digests of the bytes it JUDGED when the attempt
    holds an answer, so `collect` seals exactly those (case C66).

    The digests are taken once, BEFORE the admission (and the agy gate and
    hook subprocesses). A file that cannot be digested is this entry's
    INVALID, never a collection-wide refusal; `retry` cannot record such an
    attempt either, so the remedy is a new round."""
    try:
        before = _seal_files(attempt_dir, entry)
    except CollectError as exc:
        return EntryResult(**{**base.__dict__, "state": "invalid",
                              "reason": f"this attempt cannot be sealed: "
                                        f"{' '.join(str(exc).split())} — a "
                                        f"result is recorded only together "
                                        f"with its seal, and `retry` cannot "
                                        f"record it either; prepare a new "
                                        f"round",
                              "result_path": result_path})
    result = _evaluate_recorded(packet_dir, record, entry, attempt_dir, base)
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

    Split out so the rules ABOUT which attempt is evaluated read
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
    verdict_v2 = _load_sibling("verdict_v2")
    # The six expected values are DERIVED (round record, frozen roster entry,
    # directory name), never read back from the attempt's binding.json.
    expected = _expected_binding(record, entry, attempt)
    admission = verdict_v2.admit_file(result, expected)
    if not admission.ok:
        # A HOST FAULT IS NOT A LEG RESULT: verdict_v2 reserves exit 64 for
        # the admission it could not RUN at all — absent jsonschema, an
        # unreadable or non-Draft-2020-12 vendored contract. Nothing about
        # this leg (or any other) is known, so the collection stops here;
        # `_HostFault`'s docstring carries the rule.
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


def _check_toolkit(record: dict, what: str) -> None:
    """Refuse unless the installed review toolkit is the one this round
    recorded (R-PREPARE, R-RETRY, R-REREVIEW; cases C13 / C19 / C20; spec
    DL-41, DL-49) — run by `collect` and by `retry` before anything is judged
    or allocated.

    The HOST question comes first: `_get_validator` reserves its reason for
    "this install cannot admit ANY reply" (absent jsonschema, an unreadable /
    corrupt / non-Draft-2020-12 contract), a `_HostFault` at exit 64, never
    this round's exit-2 refusal. Then the round record's `toolkit_map`
    (`roster_v2._toolkit_map` at prepare: every file under `lib/`, the
    vendored `spec/**` and the six shipped presets, each file's sha256) is
    compared with the installed files; every changed, added or missing file is named, and a
    record without a map cannot prove the toolkit, so it is refused."""
    verdict_v2 = _load_sibling("verdict_v2")
    validator, why = verdict_v2._get_validator()
    if validator is None:
        raise _HostFault(
            f"this host cannot admit any reply: {why} — the {what} is "
            f"STOPPED and no per-entry state was written; nothing about the "
            f"legs is known, so repair the install and run it again rather "
            f"than re-dispatching them")
    frozen = record.get("toolkit_map")
    if not isinstance(frozen, dict):
        raise CollectError(
            "this round was prepared before the host recorded its toolkit "
            "map — prepare a new round")
    roster = _load_sibling("roster_v2")
    try:
        live = roster._toolkit_map()
    except roster.RosterError as exc:
        raise _HostFault(
            f"{' '.join(str(exc).split())} — the {what} is STOPPED and no "
            f"per-entry state was written") from exc
    changed = {rel for rel in frozen.keys() | live.keys()
               if frozen.get(rel) != live.get(rel)}
    if changed:
        raise CollectError(
            f"the installed toolkit changed since this round was prepared: "
            f"{', '.join(sorted(changed))} — prepare a new round (R-REREVIEW)")


def collect(packet_dir, label: str) -> Collection:
    """Collect every dispatched entry, write `collect-r<N>.json`, print the
    per-entry table plus the one greppable summary line, and return the
    Collection. Re-runnable by design: a collection is recomputed as legs
    land, so the record is overwritten rather than exclusive-created. The
    packet path is made absolute once (its own `verify` takes no other)."""
    packet_dir = Path(os.path.abspath(packet_dir))
    record = _read_record(packet_dir, label)
    # BEFORE any entry is judged: the toolkit that judges them (the admission
    # contract among it) has to be the one this round recorded, and a refusal
    # must leave the previous collection record untouched.
    _check_toolkit(record, "collection")
    # EVERY ENABLED ENTRY IS COUNTED AND NAMED: a SKIPPED entry is a
    # `missing` result, so it makes the round INCOMPLETE no matter what its
    # siblings cover (R-AGREE: a missing result is not agreement).
    # The selection and configuration must be the ones bound into the
    # round's basis (cases C19 / C33): an entry turned off or re-configured
    # after prepare is refused BY NAME as a change. Prepare refuses an empty
    # selection (R-AGREE: a nonempty roster), so a bound selection is never
    # empty and an empty record can only be a changed one.
    _bound_metadata(packet_dir, label, record, "the collection")
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
        if check.returncode not in (0, 2):  # 2 = verify's own refusal
            tail = " ".join((check.stderr or "").split())[-300:]
            raise _HostFault(f"the round integrity check (`review_scratch.py "
                             f"verify`) did not finish (exit "
                             f"{check.returncode}{': ' + tail if tail else ''})"
                             f" — nothing about the round is known; repair "
                             f"the host and collect again")
        if check.returncode != 0:
            why = " ".join((check.stderr or "").split())
            raise CollectError(
                f"every entry agreed, but the round integrity check "
                f"(`review_scratch.py verify`) failed: {why[-600:]} — the "
                f"round is INVALID; prepare a new round")
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


def retry(packet_dir, label: str, name: str, diagnosis: str) -> Path:
    """Allocate attempt K+1 for an entry that did NOT return a valid verdict.

    Every earlier artifact is retained, and the attempt it replaces is
    sealed first (a refused native reply included: sealed invalid over the
    raw.json it judged). The diagnosis is written INTO the
    failed attempt (it is evidence about that attempt), and the new attempt is
    rendered from the round's OWN frozen roster entry, so the basis is
    provably unchanged (R-RETRY). An attempt that already exists above the
    recorded one (an interrupted retry) refuses before anything is written:
    prepare a new round."""
    packet_dir = Path(packet_dir)
    record = _read_record(packet_dir, label)
    # The installed toolkit, checked BEFORE any evaluation and the allocation
    # below (R-RETRY: a changed control refuses before an attempt is
    # allocated; cases C19 / C20), so a refusal leaves nothing behind.
    _check_toolkit(record, "retry")
    bound = _bound_metadata(packet_dir, label, record, "the retry")
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
    # prerequisite is checked before anything is allocated
    # (R-REVIEW-WEB, case C32), as `prepare` checks it for the round.
    refusal = _load_sibling("review_scratch")._v2_agy_web_refusal(
        bound.get("review_web_authorized", False), [entry.get("route")])
    if refusal is not None:
        raise CollectError(f"roster entry {name!r}: {refusal}")

    # `_evaluate` scopes the attempt-name refusal to the entry, so `retry`
    # runs the same scan itself: it allocates the NEXT number, which it
    # cannot know while a name in the tree is not an attempt directory.
    attempts = _attempts(Path(packet_dir) / record["results_dir"] / name)
    # THE RECORDED ATTEMPT IS JUDGED FIRST: `_evaluate` evaluates exactly
    # attempt K, never the highest on-disk attempt, so a planted `attempt-K+1/` cannot turn the RECORDED
    # attempt's valid verdict into an `invalid` state and get it retried.
    # The replaced attempt's digests are taken once, BEFORE it is judged,
    # and its seal binds exactly these. One that cannot be read is refused
    # after retry's own refusals below, so the two commands agree on them.
    try:
        found, unsealable = _seal_files(
            Path(packet_dir) / record["results_dir"] / name
            / f"attempt-{entry['attempt']}", entry), None
    except CollectError as exc:
        found, unsealable = None, " ".join(str(exc).split())
    result = _evaluate(packet_dir, record, entry, recorded, label)
    if result.state == "valid":
        raise CollectError(
            f"roster entry {name!r} returned a VALID verdict "
            f"({result.verdict!r}) on attempt {result.attempt}: a completed "
            f"review is not a transport failure; a changed basis is a new "
            f"round (prepare r<N+1>) and EVERY entry reviews it again "
            f"(R-REREVIEW)")
    # EVERY REFUSAL BEFORE ANY WRITE OR ALLOCATION is `_retry_blocked` —
    # the one predicate `collect` also asks about an attempt above the
    # recorded one, so the two never disagree about what a retry does here.
    blocked = _retry_blocked(
        packet_dir, label, record, entry, attempts, recorded.get(name, {}),
        result)
    if blocked is not None:
        raise CollectError(blocked[1] + blocked[2])
    if unsealable is not None:
        raise CollectError(f"attempt {result.attempt} cannot be recorded "
                           f"before it is replaced ({unsealable}) — nothing "
                           f"was allocated; prepare a new round")
    # An answered attempt is sealed with its state (an inadmissible answer is
    # `invalid`); one holding no answer failed to run. A native attempt's
    # answer is its saved reply, raw.json.
    answered = ((found["result"][1] is not None and result.state == "invalid")
                or (entry.get("family", entry["vendor"]) == "claude"
                    and found["receipt"][1] is not None))
    judged = (found, "invalid" if answered else "failed-to-run")
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
    # THE INSTALLED TOOLKIT was proven unchanged before any evaluation
    # (`_check_toolkit`, cases C19 / C20), and the render above reads the same
    # installed files, so the allocation below re-runs the SAME basis.
    # ALLOCATE FIRST, diagnose second: the guard above refuses any attempt
    # that already carries a diagnosis, so a diagnosis written before a
    # failed allocation would leave the leg unretryable. `v2_write_attempt`
    # is the exclusive-create allocation.
    _seal_replaced(attempt_dir, entry, result.attempt, *judged)
    review_scratch.v2_write_attempt(alloc)
    # ONE LINE, NEVER A TRACEBACK: this write runs AFTER `v2_write_attempt`
    # allocated attempt K+1, so a failure here names that state.
    try:
        diagnosis_path.write_text(text if text.endswith("\n") else text + "\n",
                                  encoding="utf-8")
    except OSError as exc:
        raise CollectError(
            f"attempt {result.attempt + 1} was allocated at {alloc['dir']}, "
            f"but the diagnosis could not be written to {diagnosis_path} "
            f"({' '.join(str(exc).split())}) — the round record still names "
            f"attempt {result.attempt}, so a retry refuses on the allocated "
            f"attempt; prepare a new round") from exc
    entry["attempt"] = result.attempt + 1
    _write_record(packet_dir, label, record)

    print(f"retry {name}: attempt {result.attempt} ({result.state}: "
          f"{result.reason}) -> attempt {result.attempt + 1}")
    print(f"  diagnosis recorded at {diagnosis_path} (attempt "
          f"{result.attempt}'s own artifacts are retained)")
    print(f"leg outputs ({label}):")
    review_scratch.v2_print_dispatch(alloc, packet_dir, worktree, label)
    return Path(alloc["dir"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list) -> int:
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
