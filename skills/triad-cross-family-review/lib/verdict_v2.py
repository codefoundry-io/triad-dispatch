#!/usr/bin/env python3
"""verdict_v2.py - deterministic (no AI) admission helper for the CANONICAL
v2 LegVerdict, host A side.

This is the OPT-IN v2 path. The legacy v1 validator (`validate_verdict.py`,
pydantic `verdict_schema.LegVerdict`) is untouched and stays the gate for
existing v1 rounds; nothing here imports it and nothing there imports this.
The two shapes are mutually rejecting on purpose (v2 adds
`schema_version`/`leg_name`/`attempt`/`route` and renames a finding's `file`
to `path`), so a reply produced for one path can never be silently admitted
by the other.

Authority: the vendored canonical contract
`<skill-root>/spec/contracts/leg-verdict.schema.json` (JSON Schema Draft
2020-12), resolved relative to THIS file so the dev checkout and the
flattened plugin export behave identically - in both layouts the lib
directory sits one level under the skill root, beside `spec/`.

What admission means (in order, each step with its own exit code):
  1. the reply is read as a plain REGULAR file, never through a symlink;
  2. it decodes as UTF-8 and parses as JSON with DUPLICATE MEMBERS REJECTED
     at any depth - `json.loads` is last-wins, so a reply hiding an earlier
     blocking verdict behind a duplicate `"verdict": "SAFE TO MERGE"` member
     would otherwise admit as SAFE;
  3. it validates against the whole canonical schema (the schema itself
     carries the SAFE-vs-open-questions, SAFE-vs-severity, non-SAFE-needs-
     content and family-vs-route rules, so this module states none of them
     a second time);
  4. the SIX binding fields (review_id, family, content_digest, leg_name,
     attempt, route) match what the caller says it dispatched. Binding is
     ALL-OR-NOTHING: v2 admission never runs shape-only, because a partial
     check is indistinguishable from a full one at the call site. The digest
     comes from `--expected-content-digest` OR from `--expected-packet`
     (this tool hashes the packet bytes itself, through the same hardened
     read) - never both.

Exit codes:
  0   admitted - exactly one stdout line:
      `VERDICT_V2 OK leg=<leg_name> attempt=<k> findings=<n> blocking=<n>
       open_questions=<n> verdict="<token>"`
      The verdict token is QUOTED and LAST: it is the only field that
      contains spaces, so an unquoted one in the middle made the line
      ambiguous to a field-splitting reader.
  1   shape / schema / binding failure (also: unreadable reply)
  2   unparseable, a duplicate JSON member, a reply that does not begin
      with `{`, or nesting past the interpreter's recursion limit (leader:
      ONE targeted re-ask that names the syntactic defect, then terminal
      INVALID)
  3   `--end-marker` absent from the raw reply - possible TAIL LOSS
  64  usage error, `jsonschema` not importable, an unusable canonical
      schema file, or a REFUSED `--admitted-out` target - the HOST-fault
      class. A missing, unreadable, non-JSON or non-Draft-2020-12 schema
      says nothing about the leg's reply, so it must never be reported as
      "invalid reply" (exit 1); neither does a symlink / FIFO / occupied
      target at the path the caller chose to copy an ALREADY-ADMITTED reply
      into.

Every stderr reason is ONE line of plain ASCII, capped at 300 characters:
a schema message may otherwise inline the whole reply.

Consumers (the collector slice) use `admit_file()` / `admit_raw()`, which
return an `Admission`. A consumer that loads this file BY PATH rather than
by a normal import must register the module in `sys.modules` before
`exec_module` - `from __future__ import annotations` makes `Admission`'s
field annotations strings, and `dataclasses` resolves them through
`sys.modules[cls.__module__]` (the same registration gotcha the v1 module
documents for its pydantic schema loader).

ADMIT mode (`--admit <raw-reply.txt>`) exists for the NATIVE claude leg,
whose reply is raw text terminated by a marker line rather than a
machine-written file:
  * the end marker must be the final non-empty line (split on `"\\n"` only,
    tolerating a trailing CR on that line), spelled either literally or in
    its one-level `html.escape` form - an escaping transport escapes the
    marker's angle brackets too, and refusing it here killed the reply
    before the unescape retry could run;
  * the candidate object is the ORIGINAL TEXT before the marker line, taken
    by OFFSET - never `splitlines()` + `join`, which rewrites CRLF and the
    Unicode separators U+2028/U+2029 that may sit INSIDE a JSON string, so
    that a valid reply could fail and the admitted bytes could differ from
    what the leg actually sent;
  * that text must BEGIN with `{` after leading whitespace. The prompt's
    OUTPUT-SHAPE NOTICE promises the leg exactly this rule, and the earlier
    first-`{`/last-`}` slice quietly contradicted it (it would admit an
    object buried in prose);
  * the pass runs RAW FIRST. A single `html.unescape` retry runs ONLY when
    the raw pass failed to PARSE as JSON and entity tokens are present (the
    escaped-transport case). A raw pass that PARSED and then failed the
    schema or the duplicate check is FINAL: unescaping a whole reply can
    restructure the object - a `&quot;` inside a string becomes a real
    quote - and a second verdict must never be conjured that way.
`--admitted-out` writes the ORIGINAL admitted bytes (never a
re-serialization) through a same-directory pid-unique temp file plus
`os.link`, so an interrupted write can never leave a truncated canonical
file; an existing target is inspected through the SAME hardened read the
reply gets (lstat first, `O_NONBLOCK`, never a blocking `read_bytes()`),
holding exactly those bytes is an idempotent success, and any other state
is refused as a host fault (exit 64).

Test seam: `TRIAD_VERDICT_V2_SCHEMA` overrides the canonical schema path,
honored ONLY with `TRIAD_TEST_SEAMS=1` beside it (announced on stderr).
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

# jsonschema optional at IMPORT time so this module stays importable (and
# its usage text printable) on a host that lacks it; every entry point calls
# `_get_validator()` first and turns the absence into the documented usage
# exit 64 with an install hint. Draft 2020-12 needs jsonschema >= 4.0 -
# satisfied by both the dev pip build and the Ubuntu 24.04 apt package
# (python3-jsonschema 4.10.3), so a presence-only gate is enough here; there
# is no 3.x-shaped fallback to detect.
try:
    from jsonschema import Draft202012Validator  # type: ignore
except ImportError:  # pragma: no cover - exercised by the PYTHONPATH stub axis
    Draft202012Validator = None  # type: ignore

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNPARSEABLE = 2
EXIT_MARKER_ABSENT = 3
EXIT_USAGE = 64

# THE EVIDENCE SIZE CAP (gate-1 r20 row r20-2) — ONE value, spelled in three
# modules: `agy_hook._EVIDENCE_MAX_BYTES` (stdlib-only, importable on its
# own), `collect_v2._EVIDENCE_MAX_BYTES`, and this one (this module imports
# neither sibling). A change touches all three; t11 axis 27 pins them equal.
# Every genuine reply is a few KB, so a file above the cap is misfiled or
# corrupt, refused on the descriptor's fstat BEFORE a byte is read.
_EVIDENCE_MAX_BYTES = 64 * 1024 * 1024
_EVIDENCE_CAP_TEXT = "64 MiB"

_JSONSCHEMA_MISSING_MSG = (
    "jsonschema is not importable - v2 verdict admission needs it "
    "(pip install jsonschema; Ubuntu 24.04: apt install python3-jsonschema)"
)

# The canonical contract ships INSIDE the skill, one level above this file in
# both the dev checkout and the flattened plugin export.
SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "spec" / "contracts" / "leg-verdict.schema.json"
)
SCHEMA_PATH_ENV = "TRIAD_VERDICT_V2_SCHEMA"
TEST_SEAMS_ENV = "TRIAD_TEST_SEAMS"
MAX_REASON_CHARS = 300

# The three cross-field rules the vendored contract carries in its TOP-LEVEL
# `allOf`, keyed by the prefix of the failing error's `schema_path`. jsonschema
# reports such a failure against the WHOLE instance (an `anyOf` message inlines
# the entire reply) or against a sub-enum that reads like a bogus severity
# vocabulary; a named rule is what the leader and the leg can act on. Keep in
# step with `spec/contracts/leg-verdict.schema.json` -> `allOf`.
_NAMED_ROOT_RULES = (
    (("allOf", 0),
     "family google requires route agy|gemini; other families require "
     "route null"),
    (("allOf", 1, "then"),
     "SAFE TO MERGE allows only Minor/HARDENING-SUGGESTION findings and no "
     "open_questions"),
    (("allOf", 1, "else"),
     "a non-SAFE verdict requires at least one finding or one open question"),
)

_BINDING_FIELDS = (
    "review_id",
    "family",
    "content_digest",
    "leg_name",
    "attempt",
    "route",
)
_EXPECTED_FLAGS = {"--expected-" + f.replace("_", "-"): f for f in _BINDING_FIELDS}
_BLOCKING_SEVERITIES = ("Critical", "must-fix")
_HTML_ENTITY_TOKENS = ("&quot;", "&amp;", "&lt;", "&gt;", "&#")

_USAGE = (
    "usage: verdict_v2.py <verdict.json> --expected-review-id ID "
    "--expected-family claude|codex|google "
    "(--expected-content-digest HEX64 | --expected-packet FILE) "
    "--expected-leg-name NAME --expected-attempt K "
    "--expected-route agy|gemini|null\n"
    "       verdict_v2.py --admit <raw-reply.txt> --end-marker TOKEN "
    "[--admitted-out FILE] <the same six --expected-* flags>\n"
    "  binding is all-or-nothing: all six --expected-* flags are REQUIRED; "
    "v2 admission never runs shape-only. --expected-packet derives the "
    "digest from the packet bytes and is mutually exclusive with "
    "--expected-content-digest.\n"
    "  exits: 0 admitted; 1 shape/schema/binding; 2 unparseable or duplicate "
    "member; 3 end marker absent (tail loss); 64 usage"
)


def _flatten(text: str) -> str:
    """Collapse a possibly multi-line message onto ONE physical line and cap
    it: the module contract is one stderr line per failure, a schema message
    or an OSError string can legitimately span several, and a jsonschema
    message can inline the entire reply."""
    one = text.replace("\r", " ").replace("\n", " ")
    if len(one) > MAX_REASON_CHARS:
        one = one[: MAX_REASON_CHARS - 3] + "..."
    return one


def _safe(text: object) -> str:
    """One LEG-CONTROLLED fragment, rendered printable-ASCII-only.

    A duplicate member NAME, the JSON POINTER PATH built from such names and
    a schema message are all text the leg chose. `_flatten` folds CR and LF,
    but U+2028 / U+2029 / U+0085 are line terminators to a `splitlines()`
    reader and a C0 control can rewrite a terminal line, so an unescaped
    fragment could forge extra leader-visible lines inside what the contract
    promises is ONE line (gate 1 r2 row r2-8). `ascii()` is `repr()` with
    every non-printable and non-ASCII character escaped; the surrounding
    quotes are stripped so the caller keeps its own quoting. Applied to the
    FRAGMENT, before `_flatten`'s 300-character cap.
    """
    return ascii(str(text))[1:-1]


def _schema_path() -> Path:
    """The canonical contract path; the seam applies only when unlocked."""
    override = os.environ.get(SCHEMA_PATH_ENV)
    if override and os.environ.get(TEST_SEAMS_ENV) == "1":
        print(f"NOTE: verdict_v2: TEST SEAM active - canonical schema read "
              f"from {override}", file=sys.stderr)
        return Path(override)
    return SCHEMA_PATH


@dataclass
class Admission:
    """Result of one admission attempt. `verdict` is the parsed object on
    success only; `reason` is a one-line string on failure only."""

    ok: bool
    exit_code: int
    reason: str | None
    verdict: dict | None
    blocking: int
    open_questions: int


def _fail(exit_code: int, reason: str) -> Admission:
    return Admission(False, exit_code, _flatten(reason), None, 0, 0)


def _succeed(obj: dict) -> Admission:
    findings = obj.get("findings") or []
    blocking = sum(
        1 for f in findings if f.get("severity") in _BLOCKING_SEVERITIES
    )
    return Admission(
        True, EXIT_OK, None, obj, blocking, len(obj.get("open_questions") or [])
    )


# ── schema ────────────────────────────────────────────────────────────────
_VALIDATOR = None


def _get_validator() -> tuple[object | None, str | None]:
    """(validator, reason). Built once per process. `check_schema` runs on
    the vendored contract itself before any payload is judged, so a corrupted
    vendored file is reported as such instead of silently accepting or
    rejecting every reply. Every reason returned here is a HOST fault (exit
    64): none of them says anything about the leg's reply."""
    global _VALIDATOR
    if _VALIDATOR is not None:
        return _VALIDATOR, None
    if Draft202012Validator is None:
        return None, _JSONSCHEMA_MISSING_MSG
    path = _schema_path()
    # EVERY WAY THE VENDORED FILE CAN BE UNUSABLE IS A HOST FAULT (gate-1 r8
    # row r8-4). The read caught OSError only and the parse ValueError only,
    # so two classes escaped as a TRACEBACK from the one path the collector
    # relies on for its exit-64 `_HostFault` (row r7-c4): invalid UTF-8
    # raises UnicodeDecodeError, which is a ValueError and NOT an OSError,
    # and a document nested past the interpreter's limit raises
    # RecursionError, which is neither. Both say the same thing every reason
    # here says — this host cannot admit ANY reply — so both take the
    # host-fault exit instead of killing the caller mid-collection.
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return None, f"cannot read the canonical schema {path}: {e}"
    try:
        schema = json.loads(raw)
    except (ValueError, RecursionError) as e:
        return None, f"canonical schema {path} is not valid JSON: {e}"
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as e:
        return None, f"canonical schema {path} is not a valid Draft 2020-12 schema: {e}"
    _VALIDATOR = Draft202012Validator(schema)
    return _VALIDATOR, None


def _named_root_rule(error) -> str | None:
    """The human rule name for a failure of a TOP-LEVEL cross-field rule."""
    schema_path = tuple(error.schema_path)
    for prefix, rule in _NAMED_ROOT_RULES:
        if schema_path[: len(prefix)] == prefix:
            return rule
    return None


def _schema_reason(obj: object) -> str | None:
    """None when `obj` satisfies the canonical schema, else a one-line
    reason. The DEEPEST error wins: a root `allOf`/`anyOf` failure knows only
    that "the whole object is wrong" and jsonschema renders it by inlining
    the entire reply, while a sibling error one level down names the field
    that actually broke. A failure of one of the contract's top-level
    cross-field rules is reported as that RULE, never as its sub-schema
    (whose enum reads like a bogus severity vocabulary)."""
    validator, err = _get_validator()
    if err is not None:
        return err
    errors = sorted(
        validator.iter_errors(obj),  # type: ignore[union-attr]
        key=lambda e: (
            -len(e.absolute_path),
            [str(p) for p in e.absolute_path],
            e.message,
        ),
    )
    if not errors:
        return None
    first = errors[0]
    rule = _named_root_rule(first)
    if rule is not None:
        return f"schema rule violated: {rule}"
    # Both fragments are leg-controlled: the pointer path is built from the
    # reply's own member names and the message can inline reply text.
    path = _safe("/".join(str(p) for p in first.absolute_path)) or "<root>"
    return f"schema validation failed at {path}: {_safe(first.message)}"


# ── duplicate-member rejection at the ORIGINAL text ───────────────────────
class _DuplicateTracker:
    """`object_pairs_hook` that records every object carrying a repeated
    member instead of raising immediately. Recording (rather than raising)
    is what makes a JSON PATH reportable: the hook runs innermost-first and
    has no parent context, but the dict it returns IS the object embedded in
    the finished structure, so an identity walk over the parse result
    recovers where the duplicate sat."""

    def __init__(self) -> None:
        self.dups: list[tuple[str, dict]] = []

    def hook(self, pairs: list[tuple[str, object]]) -> dict:
        seen: set[str] = set()
        dup: str | None = None
        for key, _ in pairs:
            if key in seen and dup is None:
                dup = key
            seen.add(key)
        obj = dict(pairs)
        if dup is not None:
            self.dups.append((dup, obj))
        return obj


def _identity_path(root: object, target: object, path: str = "") -> str | None:
    if root is target:
        return path or "<root>"
    if isinstance(root, dict):
        for key, value in root.items():
            found = _identity_path(value, target, f"{path}/{key}" if path else str(key))
            if found is not None:
                return found
    elif isinstance(root, list):
        for index, value in enumerate(root):
            found = _identity_path(value, target, f"{path}/{index}" if path else str(index))
            if found is not None:
                return found
    return None


def _parse_strict(text: str, label: str) -> tuple[bool, object, str | None, str | None]:
    """(ok, obj, reason, failure_kind). Rejects a duplicate member at ANY
    depth. `ok` is an explicit flag because a valid top-level `null` parses
    to None and must still reach schema validation as a shape failure, not
    be mistaken for a parse failure. `failure_kind` is "json" only for a
    genuine JSON syntax error - the one failure an escaped-transport retry
    could legitimately repair - and "duplicate" for the last-wins guard.
    A reply nested past the interpreter's recursion limit is a syntax-class
    failure too, reported on one line instead of a traceback."""
    tracker = _DuplicateTracker()
    try:
        obj = json.loads(text, object_pairs_hook=tracker.hook)
    except ValueError as e:
        return False, None, f"{label} is not valid JSON: {e}", "json"
    except RecursionError:
        return False, None, f"{label} nesting too deep", "json"
    try:
        dups = list(tracker.dups)
        for key, container in dups:
            where = _identity_path(obj, container)
            if where is not None:
                return False, None, (
                    f"duplicate JSON member '{_safe(key)}' at {_safe(where)} "
                    f"in {label} - last-wins parsing would hide the earlier "
                    "value"
                ), "duplicate"
        if dups:
            key = dups[0][0]
            return False, None, (
                f"duplicate JSON member '{_safe(key)}' at <unknown> in "
                f"{label} - last-wins parsing would hide the earlier value"
            ), "duplicate"
    except RecursionError:
        return False, None, f"{label} nesting too deep", "json"
    return True, obj, None, None


# ── hardened read ─────────────────────────────────────────────────────────
def _read_regular_file_no_symlink(path: Path) -> tuple[bytes | None, str | None]:
    """(data, reason). Refuses anything that is not a plain regular file -
    above all a SYMLINK planted at the expected reply path, which would
    otherwise let this tool read and admit an arbitrary target. `lstat` makes
    the decision for EVERY non-regular type before the open: a FIFO left at
    the reply path would otherwise block the open forever (the fstat check
    sits behind it), so the tool must refuse it on the stat, and `O_NONBLOCK`
    closes the TOCTOU window where one appears in between. `O_NOFOLLOW`
    covers a symlink swapped in after the lstat, and the descriptor's own
    `fstat` re-checks S_ISREG before any byte is read. All POSIX - no
    platform branch."""
    try:
        st = path.lstat()
    except OSError as e:
        return None, f"cannot read {path}: {e}"
    if stat.S_ISLNK(st.st_mode):
        return None, f"{path} is a symlink, refusing to read"
    if not stat.S_ISREG(st.st_mode):
        return None, f"{path} is not a regular file, refusing to read"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        return None, f"cannot read {path}: {e}"
    too_big = (f"{path} exceeds the {_EVIDENCE_CAP_TEXT} evidence cap, "
               f"refusing to read (no genuine reply is anywhere near that "
               f"size: misfiled or corrupt)")
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return None, f"{path} is not a regular file"
        # BOUNDED (gate-1 r20 row r20-2): refused on the fstat before a byte
        # is read, and the loop stops at the cap should the file grow.
        if fst.st_size > _EVIDENCE_MAX_BYTES:
            return None, too_big
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _EVIDENCE_MAX_BYTES:
                return None, too_big
            chunks.append(chunk)
        return b"".join(chunks), None
    # THE DESCRIPTOR PHASE ANSWERS IN THE SAME SHAPE (gate-1 r10 row r10-8).
    # The two arms above convert their OSError into `(None, reason)`; the
    # fstat and the read loop had none, so an EIO (a failing disk, a stale
    # NFS handle, a device-backed path that satisfied both S_ISREG checks)
    # raised out of `admit_file` as a TRACEBACK — out of the one function
    # `collect_v2._evaluate` calls per entry, so ONE unreadable reply file
    # killed the whole collection instead of invalidating that entry (the
    # r5-11 class).
    #
    # The caller maps this reason to EXIT_INVALID (1), which is deliberate:
    # exit 64 is reserved here for `_get_validator`'s reasons — "this host
    # cannot admit ANY reply" — and a read failure on ONE path is not
    # evidence about the install. At 64 the collector raises `_HostFault`
    # and STOPS the round with no per-entry state written; at 1 the entry
    # is invalid with the OS error named and every other entry still
    # collects. Same class, same wording, as the lstat/open arms above.
    except OSError as e:
        return None, f"cannot read {path}: {e}"
    finally:
        os.close(fd)


# ── binding ───────────────────────────────────────────────────────────────
def _binding_reason(obj: dict, expected: dict) -> str | None:
    """The first binding mismatch, each field with its OWN wording naming the
    field, the expected value and the actual one - the leader branches on
    which bind broke (replay of another round, another leg, a stale attempt,
    a wrong Google route) and must never have to guess."""
    for field in _BINDING_FIELDS:
        want = expected[field]
        got = obj.get(field)
        if got != want:
            return (
                f"{field} mismatch: expected {want!r}, actual {got!r} - the "
                "reply was not produced for this dispatch"
            )
    return None


def _admit_obj(obj: object, expected: dict, label: str) -> Admission:
    # A host-side schema fault (absent jsonschema, unreadable / corrupt /
    # non-Draft-2020-12 contract) is exit 64 and is NEVER dressed up as an
    # invalid reply: the leg's work has not been judged at all.
    _, host_err = _get_validator()
    if host_err is not None:
        return _fail(EXIT_USAGE, host_err)
    reason = _schema_reason(obj)
    if reason is not None:
        return _fail(EXIT_INVALID, f"{label}: {reason}")
    reason = _binding_reason(obj, expected)  # type: ignore[arg-type]
    if reason is not None:
        return _fail(EXIT_INVALID, f"{label}: {reason}")
    return _succeed(obj)  # type: ignore[arg-type]


# ── public API ────────────────────────────────────────────────────────────
def admit_file(path: Path, expected: dict) -> Admission:
    """Admit a machine-written verdict FILE (the wrapper-backed legs)."""
    data, err = _read_regular_file_no_symlink(path)
    if err is not None:
        return _fail(EXIT_INVALID, err)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        return _fail(EXIT_UNPARSEABLE, f"{path} is not valid UTF-8: {e}")
    ok, obj, reason, _kind = _parse_strict(text, str(path))
    if not ok:
        return _fail(EXIT_UNPARSEABLE, reason or f"{path} is unparseable")
    return _admit_obj(obj, expected, str(path))


def admit_raw(text: str, expected: dict, end_marker: str) -> Admission:
    """Admit a leg's prose-tolerant RAW reply text (the native claude leg)."""
    return _admit_raw_with_text(text, expected, end_marker)[0]


def _extract_object_text(text: str, end_marker: str) -> tuple[str | None, str | None, bool]:
    """(object_text, reason, marker_missing). The marker must be the final
    NON-EMPTY line: a reply whose tail was truncated mid-JSON loses it, and
    that loss must be reported as its own class (exit 3) rather than as a
    generic parse failure, because the leader's next step differs.

    The split is on `"\\n"` ONLY and the candidate object is sliced OUT OF
    THE ORIGINAL TEXT by offset, so CRLF line ends and U+2028/U+2029 inside
    JSON strings reach the parser - and `--admitted-out` - exactly as the leg
    wrote them.

    The marker must be the LITERAL token here. An escaped spelling is not
    accepted at this stage: `_marker_needs_unescape` detects it one level up
    and re-runs the whole pass on `html.unescape(text)`, so by the time this
    function sees an escaped-transport reply the marker is literal again
    (gate 1 r3 row r3-8). The earlier form accepted `html.escape(end_marker)`
    HERE, which admitted the RAW body of a transport that had escaped the
    angle brackets but not the quotes - entities left inside the strings,
    and a different object from the one the legacy validator derives from
    the same bytes."""
    lines = text.split("\n")
    last = None
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            last = index
            break
    if last is None or lines[last].strip() != end_marker:
        return None, (
            f"end marker {end_marker!r} absent as the final non-empty line - "
            "possible tail loss; treat as unparseable (ONE targeted re-ask, "
            "then terminal INVALID)"
        ), True
    # everything before the marker LINE, original bytes included
    head = text[: sum(len(line) + 1 for line in lines[:last])]
    if not head.lstrip().startswith("{"):
        return None, (
            "reply does not begin with '{' - the OUTPUT-SHAPE NOTICE the leg "
            "was given admits only a reply that starts with the JSON object "
            "(no introduction sentence, no markdown fence)"
        ), False
    return head, None, False


def _marker_needs_unescape(text: str, end_marker: str) -> bool:
    """True when the reply's final non-empty line is NOT the literal end
    marker but `html.unescape` of it IS - i.e. the TRANSPORT escaped.

    It covers every spelling `html.unescape` knows, so the named-entity form
    (`&lt;END-VERDICT&gt;`) and the numeric character references
    (`&#60;...&#62;`, `&#x3C;...`) are one rule instead of the single
    `html.escape` special case that recognized only the first
    (gate 1 r3 row r3-8)."""
    for line in reversed(text.split("\n")):
        stripped = line.strip()
        if not stripped:
            continue
        return stripped != end_marker and html.unescape(stripped) == end_marker
    return False


def _admit_raw_with_text(
    text: str, expected: dict, end_marker: str
) -> tuple[Admission, str | None]:
    """(admission, admitted_object_text). The MARKER decides which text is
    admitted, and it is the only thing that decides it.

    ESCAPED TRANSPORT (the marker itself came through escaped): the whole
    reply is unescaped ONCE and admitted from that - the legacy
    `validate_verdict.py` pass-2 semantics, on the same bytes. Admitting the
    raw body of such a reply is what let `&lt;`/`&gt;` survive inside the
    admitted strings when the transport escaped angle brackets but not
    quotes, so the two validators derived DIFFERENT objects from one reply
    (gate 1 r3 row r3-8).

    LITERAL MARKER: RAW FIRST, unchanged. An already-valid reply - including
    one whose string fields legitimately spell HTML entities - is admitted
    byte-exact, and the single `html.unescape` retry runs ONLY when the raw
    pass failed to PARSE as JSON and entity tokens are present. A raw pass
    that parsed and then failed the schema or the duplicate guard is FINAL:
    unescaping the whole text can restructure the object (a `&quot;` inside a
    string becomes a real quote), so a retry there would judge a DIFFERENT
    document than the leg sent. No third pass, no repair."""
    if _marker_needs_unescape(text, end_marker):
        escaped, escaped_text, escaped_marker_missing, _ = _admit_raw_pass(
            html.unescape(text), expected, end_marker
        )
        if escaped.ok:
            print("NOTICE: admitted on the html.unescape pass", file=sys.stderr)
            return escaped, escaped_text
        if escaped_marker_missing:
            return _fail(EXIT_MARKER_ABSENT,
                         escaped.reason or "end marker absent"), None
        return escaped, None
    admission, obj_text, marker_missing, parse_failed = _admit_raw_pass(
        text, expected, end_marker
    )
    retryable = (
        not admission.ok
        and parse_failed
        and any(tok in text for tok in _HTML_ENTITY_TOKENS)
    )
    if not retryable:
        if not admission.ok and marker_missing:
            return _fail(EXIT_MARKER_ABSENT, admission.reason or "end marker absent"), None
        return admission, obj_text
    retry, retry_text, retry_marker_missing, _ = _admit_raw_pass(
        html.unescape(text), expected, end_marker
    )
    if retry.ok:
        print("NOTICE: admitted on the html.unescape pass", file=sys.stderr)
        return retry, retry_text
    if retry_marker_missing:
        return _fail(EXIT_MARKER_ABSENT, retry.reason or "end marker absent"), None
    return retry, None


def _admit_raw_pass(
    text: str, expected: dict, end_marker: str
) -> tuple[Admission, str | None, bool, bool]:
    """(admission, object_text, marker_missing, parse_failed). `parse_failed`
    is True only for a JSON SYNTAX failure - the sole class an escaped-
    transport retry may attempt."""
    obj_text, reason, marker_missing = _extract_object_text(text, end_marker)
    if obj_text is None:
        code = EXIT_MARKER_ABSENT if marker_missing else EXIT_UNPARSEABLE
        return (
            _fail(code, reason or "unparseable raw reply"),
            None,
            marker_missing,
            False,
        )
    ok, obj, parse_reason, kind = _parse_strict(obj_text, "the raw reply")
    if not ok:
        return (
            _fail(EXIT_UNPARSEABLE, parse_reason or "unparseable raw reply"),
            None,
            False,
            kind == "json",
        )
    return _admit_obj(obj, expected, "the raw reply"), obj_text, False, False


# ── CLI ───────────────────────────────────────────────────────────────────
def _ok_line(admission: Admission) -> str:
    """The single stdout line. The verdict token is the only field carrying
    spaces, so it is QUOTED and placed LAST: every other field then survives
    plain whitespace splitting by a reader of this line."""
    obj = admission.verdict or {}
    return (
        f"VERDICT_V2 OK leg={obj.get('leg_name')} "
        f"attempt={obj.get('attempt')} "
        f"findings={len(obj.get('findings') or [])} "
        f"blocking={admission.blocking} "
        f"open_questions={admission.open_questions} "
        f'verdict="{obj.get("verdict")}"'
    )


def _write_admitted_out(target: Path, payload: str) -> str | None:
    """None on success, else a one-line reason. The ORIGINAL admitted bytes
    are materialized in a same-directory pid-unique temp file and hard-linked
    into place, so an interrupted write never leaves a truncated canonical
    file and a concurrent writer cannot be clobbered."""
    if target.is_symlink():
        return "--admitted-out: refuses a symlink target"
    data = payload.encode("utf-8")
    # PRESENCE by lstat, CONTENT by the hardened reader - never
    # `read_bytes()`. A FIFO planted at the target blocked that open forever
    # (gate 1 r2 row r2-6), and by then the reply had already been admitted,
    # so the tool hung holding a finished verdict. `lstat` refuses every
    # non-regular type before the open and `O_NONBLOCK` closes the window
    # where one appears in between.
    try:
        target.lstat()
        present = True
    except FileNotFoundError:
        present = False
    except OSError as e:
        return f"--admitted-out: {e}"
    if present:
        existing, read_err = _read_regular_file_no_symlink(target)
        if read_err is not None:
            return f"--admitted-out: {read_err}"
        if existing == data:
            print(
                "NOTICE: --admitted-out already holds these exact bytes - "
                "idempotent re-admission",
                file=sys.stderr,
            )
            return None
        return "--admitted-out: target exists with DIFFERENT content - refusing to overwrite"
    tmp = target.with_name(f".tmp-admit-{os.getpid()}-{target.name}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.link(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    except OSError as e:
        return f"--admitted-out: {e}"
    return None


def _parse_argv(argv: list[str]) -> tuple[dict, str | None]:
    """(parsed, reason). Pure SHAPE parse plus the value-domain checks the
    six binding flags carry; the all-or-nothing rule is applied by the
    caller so the missing flags can be named."""
    values: dict[str, str] = {}
    positional: list[str] = []
    admit: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in _EXPECTED_FLAGS or arg in ("--admit", "--end-marker",
                                             "--admitted-out",
                                             "--expected-packet"):
            if i + 1 >= len(argv):
                return {}, f"{arg} requires a value"
            if arg == "--admit":
                admit = argv[i + 1]
            else:
                values[arg] = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--"):
            return {}, f"unknown flag {arg}"
        positional.append(arg)
        i += 1

    if admit is None and len(positional) != 1:
        return {}, "exactly one verdict file is required (or --admit <raw-reply.txt>)"
    if admit is not None and positional:
        return {}, "--admit takes the raw reply as its own value; no positional file"
    if admit is None and ("--end-marker" in values or "--admitted-out" in values):
        return {}, "--end-marker and --admitted-out belong to --admit mode only"
    if admit is not None and not values.get("--end-marker"):
        return {}, "--admit requires a non-empty --end-marker"

    packet = values.get("--expected-packet")
    if packet is not None and "--expected-content-digest" in values:
        return {}, ("--expected-packet and --expected-content-digest are "
                    "mutually exclusive: name ONE digest source")

    # The packet file IS the digest source, so it satisfies the digest slot
    # of the all-or-nothing binding set.
    missing = [
        flag for flag in _EXPECTED_FLAGS
        if flag not in values
        and not (flag == "--expected-content-digest" and packet is not None)
    ]
    if missing:
        return {}, (
            "binding is all-or-nothing: missing " + ", ".join(sorted(missing))
            + " (all six --expected-* flags are required, the digest either "
            "as --expected-content-digest or as --expected-packet; v2 "
            "admission never runs shape-only)"
        )

    if packet is not None:
        # Derived from the packet BYTES through the same hardened read the
        # reply gets: the caller cannot mis-transcribe a digest it never
        # types, and a symlinked packet is refused rather than followed.
        data, err = _read_regular_file_no_symlink(Path(packet))
        if err is not None:
            return {}, f"--expected-packet: {err}"
        values["--expected-content-digest"] = hashlib.sha256(data).hexdigest()

    expected: dict = {}
    for flag, field in _EXPECTED_FLAGS.items():
        expected[field] = values[flag]
    raw_attempt = expected["attempt"]
    # `str.isdigit()` is TRUE for characters `int()` refuses - U+00B2 and the
    # other superscripts among them - so the guard admitted a value the very
    # next line crashed on, and the ValueError escaped as a traceback instead
    # of the one-line usage refusal this tool promises. `isdecimal()` is the
    # narrower predicate, and `int()` is wrapped anyway: the parse decides,
    # never the predicate alone.
    if not raw_attempt.isdecimal():
        return {}, "--expected-attempt must be an integer >= 1"
    try:
        attempt = int(raw_attempt)
    except ValueError:
        return {}, "--expected-attempt must be an integer >= 1"
    if attempt < 1:
        return {}, "--expected-attempt must be an integer >= 1"
    expected["attempt"] = attempt
    if expected["route"] not in ("agy", "gemini", "null"):
        return {}, "--expected-route must be one of agy, gemini, null"
    if expected["route"] == "null":
        expected["route"] = None

    return {
        "expected": expected,
        "file": positional[0] if admit is None else None,
        "admit": admit,
        "end_marker": values.get("--end-marker"),
        "admitted_out": values.get("--admitted-out"),
    }, None


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


def main(argv: list[str]) -> int:
    _relax_std_stream_errors()
    parsed, reason = _parse_argv(argv)
    if reason is not None:
        print(reason, file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return EXIT_USAGE

    # A host-fault schema state is decided BEFORE the reply is touched, so
    # the operator is told their install is broken instead of being told the
    # leg produced an invalid reply.
    _, schema_err = _get_validator()
    if schema_err is not None:
        print(_flatten(schema_err), file=sys.stderr)
        return EXIT_USAGE

    expected = parsed["expected"]
    if parsed["admit"] is None:
        admission = admit_file(Path(parsed["file"]), expected)
        if not admission.ok:
            print(admission.reason, file=sys.stderr)
            return admission.exit_code
        print(_ok_line(admission))
        return EXIT_OK

    data, err = _read_regular_file_no_symlink(Path(parsed["admit"]))
    if err is not None:
        print(err, file=sys.stderr)
        return EXIT_INVALID
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        print(f"{parsed['admit']} is not valid UTF-8: {e}", file=sys.stderr)
        return EXIT_UNPARSEABLE
    admission, obj_text = _admit_raw_with_text(text, expected, parsed["end_marker"])
    if not admission.ok:
        print(admission.reason, file=sys.stderr)
        return admission.exit_code
    if parsed["admitted_out"] is not None:
        write_err = _write_admitted_out(Path(parsed["admitted_out"]), obj_text or "")
        if write_err is not None:
            # HOST fault (exit 64), never exit 1: the reply itself was
            # ADMITTED two lines up, and the target - a symlink, a FIFO, a
            # file with other content, an unwritable directory - says nothing
            # about the leg's work. Reporting it as "invalid reply" made the
            # leader re-ask a leg that had already answered correctly.
            print(write_err, file=sys.stderr)
            return EXIT_USAGE
    print(_ok_line(admission))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
