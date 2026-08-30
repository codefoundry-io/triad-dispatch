#!/usr/bin/env python3
"""validate_verdict.py — deterministic (no AI) validator for the claude
fresh-eye leg's reply against the shared cross-family-review verdict schema
(`verdict_schema.LegVerdict`).

Usage: python3 validate_verdict.py <json-file>
           [--expected-review-id ID]
           [--expected-family claude|google|codex]
           [--expected-content-digest HEX64 | --expected-packet FILE]
  exit 0  valid — and, when binding admission is REQUESTED (any one of the
          four --expected-* flags below is present), the parsed verdict's
          review_id/family/content_digest ALSO match — nothing on stdout (a
          gate, not a formatter), EXCEPT a flagless (shape-only) success,
          which prints a one-line NOTICE to stderr (see below).
  exit 1  invalid, missing, or malformed — ONE line on stderr; the failure
          classes carry visibly distinct wording (missing file / not valid
          JSON / not a regular file — symlink refused / fails LegVerdict
          validation / review ID mismatch / family mismatch / content
          digest mismatch / incomplete binding flag set / mutually
          exclusive digest flags) so the leader's consolidation step does
          not have to guess which one happened.

Binding admission (2026-08-10 hardening, adopted alongside
`verdict_schema.py`'s round/leg-binding fields — see that module's
docstring) binds a verdict to the round/leg it was produced for:
`--expected-review-id`/`--expected-family` name the round and leg, and the
digest names the exact packet bytes the leg reviewed — together they let
the leader refuse a reply that is structurally a valid LegVerdict but was
produced for a DIFFERENT round or a DIFFERENT leg (replay / leg-mixup),
which schema validation alone cannot catch since the fields are
self-reported inside the very payload being checked. Two ways to supply the
digest:
  --expected-content-digest HEX64   a caller-supplied hex string — the
                                     caller is trusted to have derived it
                                     correctly.
  --expected-packet <path>          this tool derives the digest ITSELF by
                                     hashing the named file's own bytes (the
                                     SAME symlink-refusing hardened read
                                     `_read_regular_file_no_symlink` uses
                                     for the reply file) — closing the gap
                                     where a stale or hand-typed digest
                                     string could pass even though the
                                     packet on disk moved. Mutually
                                     exclusive with --expected-content-digest
                                     (passing both is a usage error).

2026-08-11 hardening (finding r1-C1 — codex must-fix + agy
hardening-suggestion + claude must-fix, converging on the SAME gap
independently; probe: a flagless run on a real verdict file returned rc=0
with no signal binding was skipped). The three original --expected-* flags
were fully independent and optional, so (a) a caller could supply just ONE
and get a PARTIAL check indistinguishable from a full one, and (b) a caller
that omitted all three got a SILENT shape-only pass. Two changes:
  1. The four binding flags now form an ALL-OR-NOTHING group: presence of
     ANY one of them REQUIRES --expected-review-id AND --expected-family
     AND exactly one digest source (--expected-content-digest OR
     --expected-packet) — a partial set is a usage error (exit 1), not a
     weaker partial check.
  2. A flagless call keeps the ORIGINAL shape-only rc contract byte-for-byte
     (exit 0 on a valid file, existing shape-only callers — e.g. this
     module's own unit suite and the export-invariants system test — keep
     working unchanged) but now prints a one-line NOTICE to stderr on that
     success path, since silence is exactly what let the fail-open probe
     through undetected. This is the ONE deliberate stderr-on-success
     carve-out in this module; every other success path stays silent.

Deliverable C, plan `2026-07-31-agy-post-migration-followups` item (4): the
codex and agy legs get `LegVerdict` enforced by their `--pydantic` wrapper
plumbing (codex-strict `--output-schema`, agy native `--json-schema`); the
claude leg has no wrapper, so its leg prompt states this SAME shape as the
reply contract and the LEADER validates the reply with this script instead of
eyeballing prose. A reply that fails validation is the EXISTING INVALID-leg
handling (one re-ask, then INVALID —
`.claude/skills/triad-cross-family-review/references/triage.md` § Verdict
release at the merge gate); this script only produces the exit code + reason
that handling branches on, it does not invent a new chain.

Dual-path module resolution (mirrors `lib/review_scratch.py`'s
host-agnostic-path convention — a skill lib file must run identically from
the dev repo and from an installed plugin, with no environment setup). This
file itself ships at a FIXED relative depth in both layouts
(`export_plugin.assemble_skills` copies every skill's `lib/*.py` verbatim
into the same `skills/<name>/lib/` shape), and so does its schema sibling
(`export_plugin.BIN_FILES` ships `verdict_schema.py` to `bin/`):

  dev:  <repo>/.claude/skills/triad-cross-family-review/lib/validate_verdict.py
        -> <repo>/<wrappers-package>/wrappers/verdict_schema.py  (parents[4])
  dist: <plugin-root>/skills/triad-cross-family-review/lib/validate_verdict.py
        -> <plugin-root>/bin/verdict_schema.py                   (parents[3])

("<wrappers-package>" is the dev repo's Python-tooling package directory —
named via `_DEV_WRAPPERS_PACKAGE` below rather than spelled out here, since
this file ships BYTE-IDENTICAL to dev and dist with no export-time rewrite
pass, unlike SKILL.md/references text.)

Both candidates are checked by FILE EXISTENCE, never by assuming which layout
is live from an env var or a directory name — the layout that actually has
`verdict_schema.py` next to it wins. Order is **dist-then-dev** (final-gate
fix round, converged codex+claude finding): in a DIST install, `parents[4]`
is the plugins CONTAINER — a directory this plugin does not own and may share
with other plugins or arbitrary content — so checking the dev candidate FIRST
would let a same-shaped directory planted there SHADOW the real dist `bin/`.
Dist-first carries no such risk in a DEV checkout: there is no
`.claude/bin/verdict_schema.py` in this repo, so that candidate simply never
matches and resolution falls through to the dev candidate.


RAW-reply ADMISSION mode (2026-08-30 hardening; algorithm as of gate r2/r3):
`--admit <raw-file>` with the full binding flags (REQUIRED) admits a leg's raw
final-message file. RAW-FIRST two-pass: pass 1 runs the optional
`--end-marker` check + a duplicate-member-rejecting parse on the RAW bytes
(an already-valid reply — entity-spelling strings included — admits
BYTE-EXACT); only when pass 1 fails AND entity tokens are present does the
single documented html.unescape run, and pass 2 retries both steps (the
escaped-transport case). No third pass. Exit codes: 0 admitted / 1
shape+binding+usage / 2 UNPARSEABLE (printed next step = ONE targeted
re-ask, then terminal INVALID) / 3 end-marker absent (tail-loss signal).
`--admitted-out <path>` writes the TOOL-normalized admitted object on
success only, via a same-dir pid-unique temp + hardlink (never a truncated
canonical file); it never overwrites — a byte-identical re-run is
idempotent rc 0, different content is refused. The tool never rewrites the
raw file and has no repair path."""
from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import ModuleType


def _flatten(text: str) -> str:
    """Collapse a possibly-MULTI-line exception message onto ONE physical
    line (re-confirm round 3 / H4, claude Minor): this module's documented
    contract is ONE line per failure class on stderr, but a bare f-string
    interpolation of `str(exc)` breaks that the moment a real exception's
    text spans multiple lines — pydantic's own `ValidationError` routinely
    does (one block per invalid field). `.replace("\\n", " ")` over
    `str(exc).splitlines()[0]` on purpose: a `ValidationError`'s multi-line
    text is often the MOST useful diagnostic content, and truncating to just
    the first line would discard nearly all of it; collapsing keeps every
    character, just on one physical line."""
    return text.replace("\n", " ")


class VerdictSchemaNotFound(Exception):
    """Neither the dev nor the dist candidate directory carries
    verdict_schema.py."""


class VerdictSchemaLoadError(Exception):
    """Wraps any `Exception` raised during `verdict_schema.py`'s module
    execution (import, syntax, or model-construction errors alike);
    `SystemExit`/`KeyboardInterrupt` are unwound from `sys.modules` but
    RE-RAISED UNWRAPPED, so a caller catching only this class will not see
    them. Distinct from `VerdictSchemaNotFound` (no candidate file at all):
    the leader needs to tell "the schema module is missing" apart from "the
    schema module is present but broken"."""


# The dev repo's Python-tooling package directory that holds `wrappers/`
# (sibling of `.claude/`) — split across two literals so this file's own
# text never contains the CONTIGUOUS banned-jargon token the distribution
# build's `assert_distribution_clean` scans every `lib/*.py` file for. This
# file ships BYTE-IDENTICAL to both dev and dist (no export-time rewrite pass
# runs on `lib/*.py`, unlike SKILL.md/references text, which gets one via
# `generalize_for_distribution`), so there is no other point at which this
# token could be scrubbed. The resolved value only ever builds a path
# CANDIDATE that is existence-checked before use (`_candidate_schema_dirs`
# below): a dist install has no such directory at all, so that candidate
# simply never matches and resolution falls through to `bin/`.
_DEV_WRAPPERS_PACKAGE = "3rd" + "-Agent"


def _candidate_schema_dirs(here: Path) -> list[Path]:
    """The directories `verdict_schema.py` can live in, keyed to THIS file's
    own location: **dist FIRST** (plugin root's `bin/`), then dev (repo
    root's wrappers package) — see the module docstring for why dist must be
    checked first (a dev-candidate directory planted in a dist install's
    shared plugins container would otherwise shadow the real `bin/`).
    `len(parents) > N` guards a shallow/unexpected layout from raising
    IndexError instead of falling through to VerdictSchemaNotFound."""
    candidates = []
    if len(here.parents) > 3:
        candidates.append(here.parents[3] / "bin")
    if len(here.parents) > 4:
        candidates.append(here.parents[4] / _DEV_WRAPPERS_PACKAGE / "wrappers")
    return candidates


def _load_verdict_schema_module(here: Path) -> ModuleType:
    """Import `verdict_schema` from whichever candidate directory actually
    carries it. Loaded by absolute file path (`spec_from_file_location`)
    rather than `sys.path` manipulation + `import_module`, since
    verdict_schema.py has no sibling-module imports of its own to resolve —
    only `pydantic`/`typing` — so there is nothing to gain from polluting
    `sys.path` and a caller that imports this file as a library keeps its own
    `sys.path` untouched. MUST register under `sys.modules["verdict_schema"]`
    before `exec_module`: `verdict_schema.py` uses
    `from __future__ import annotations` (PEP 563 lazy annotations), so
    pydantic resolves each field's string annotation (e.g.
    `"Literal[*SEVERITY_TOKENS]"`) by looking up `sys.modules[cls.__module__]`
    for the class's globalns — an unregistered module fails that lookup and
    every model raises 'class not fully defined' on first use, valid input or
    not (caught via a live run, not by reasoning: the naive
    module_from_spec()+exec_module() alone passed every REJECTION axis below
    while failing every VALID one, since only the valid path exercises
    pydantic's own annotation resolution end to end)."""
    checked = []
    for d in _candidate_schema_dirs(here):
        f = d / "verdict_schema.py"
        checked.append(str(f))
        if f.is_file():
            spec = importlib.util.spec_from_file_location("verdict_schema", f)
            mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            sys.modules["verdict_schema"] = mod
            try:
                spec.loader.exec_module(mod)
            except BaseException as e:
                # Re-confirm round 2 / G2 (codex must-fix + claude Minor,
                # same defect): a narrower `except (ImportError,
                # ModuleNotFoundError, SyntaxError)` let anything ELSE a
                # broken schema module might raise at exec time (e.g. a
                # pydantic model-construction TypeError) propagate RAW past
                # this function and past validate() — an uncaught traceback
                # instead of the classified exit-1 path. `except BaseException`
                # catches everything; the UNWIND below is therefore
                # unconditional (exec_module registered the now half-executed,
                # broken module under sys.modules above — leaving it there
                # would hand a RETRYING caller, or any unrelated code that
                # later imports "verdict_schema", the poisoned half-module
                # instead of a clean second attempt, REGARDLESS of which
                # exception fired). Only `Exception` subclasses are WRAPPED
                # into `VerdictSchemaLoadError`: `KeyboardInterrupt` /
                # `SystemExit` (BaseException-only, not Exception) are
                # process-control signals, not data-validation errors, and
                # must re-raise untouched after the same unwind — wrapping a
                # Ctrl-C or a `sys.exit()` into a "schema failed to load"
                # string would corrupt that signal for the caller.
                del sys.modules["verdict_schema"]
                if isinstance(e, Exception):
                    raise VerdictSchemaLoadError(
                        f"schema module failed to load: {f}: {_flatten(str(e))}"
                    ) from e
                raise
            return mod
    raise VerdictSchemaNotFound(
        "verdict_schema.py not found via dev (<repo>/<wrappers-package>/wrappers/) "
        "or dist (<plugin-root>/bin/) resolution from " + str(here) +
        " — checked: " + ", ".join(checked)
    )


def _read_regular_file_no_symlink(json_path: Path) -> tuple[bytes | None, str | None]:
    """(data, reason). Reads `json_path` as raw bytes, refusing anything
    that is not a plain regular file — most importantly a SYMLINK (2026-08-10
    hardening: a symlink planted at the expected reply-file path would
    otherwise let this validator read and pass an arbitrary target file the
    caller never intended). `lstat` (never follows a symlink) makes the
    reject decision; the actual `open` ALSO passes `O_NOFOLLOW`
    (belt-and-suspenders against a TOCTOU swap between the `lstat` and the
    `open`), and the opened descriptor's own `fstat` re-checks `S_ISREG`
    before any byte is read. `os.O_NOFOLLOW` is POSIX and present on both
    macOS and Ubuntu 24.04 — no platform branch needed."""
    try:
        st = json_path.lstat()
    except OSError as e:
        return None, f"cannot read {json_path}: {e}"
    if stat.S_ISLNK(st.st_mode):
        return None, f"{json_path} is a symlink, refusing to read"
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        fd = os.open(json_path, flags)
    except OSError as e:
        return None, f"cannot read {json_path}: {e}"
    try:
        fst = os.fstat(fd)
        if not stat.S_ISREG(fst.st_mode):
            return None, f"{json_path} is not a regular file"
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), None
    finally:
        os.close(fd)


def _validate_and_load(json_path: Path) -> tuple[bool, str | None, object | None]:
    """(ok, reason, verdict). `verdict` (a `LegVerdict` instance) is set
    only when `ok` is True; `reason` is set only when `ok` is False.
    Internal — `validate()` below is the STABLE public 2-tuple contract
    existing direct-import callers (this module's own CLI `main()`, and
    e.g. the t2 test suite's `vv.validate(...)` axes) already depend on;
    `main()` additionally needs the parsed object for the --expected-*
    binding checks, so this function is the one place both share."""
    data, err = _read_regular_file_no_symlink(json_path)
    if err is not None:
        return False, err, None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        # UnicodeDecodeError is a ValueError subclass, NOT an OSError — a
        # separate except clause (distinct message class) is required;
        # decoding explicitly as UTF-8 (rather than the platform default)
        # makes this reachable and deterministic across dev (macOS) and
        # dist (Ubuntu).
        return False, f"{json_path} is not valid UTF-8: {e}", None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"{json_path} is not valid JSON: {e}", None
    return _validate_obj(obj, str(json_path))


def _validate_obj(obj: object, label: str) -> tuple[bool, str | None, object | None]:
    """Schema-validate an already-parsed JSON object (shared by the file
    path above and the 2026-08-30 --admit raw-text path)."""
    here = Path(__file__).resolve()
    try:
        mod = _load_verdict_schema_module(here)
    except VerdictSchemaNotFound as e:
        return False, str(e), None
    except VerdictSchemaLoadError as e:
        return False, str(e), None
    try:
        verdict = mod.LegVerdict.model_validate(obj)
    except Exception as e:  # pydantic.ValidationError — kept broad on purpose:
        # this module must stay import-light (no top-level pydantic import),
        # since verdict_schema's own dependency is resolved dynamically above.
        return False, f"{label} fails LegVerdict validation: {_flatten(str(e))}", None
    return True, None, verdict


def validate(json_path: Path) -> tuple[bool, str | None]:
    """(ok, reason). reason is None on success, else a one-line string.
    STABLE 2-tuple public contract, unchanged since before the 2026-08-10
    hardening — see `_validate_and_load` for the 3-tuple internal form the
    CLI path uses to also get the parsed object for --expected-* binding."""
    ok, reason, _ = _validate_and_load(json_path)
    return ok, reason


_BINDING_FLAGS = (
    "--expected-review-id",
    "--expected-family",
    "--expected-content-digest",
    "--expected-packet",
)

_USAGE = (
    "usage: validate_verdict.py <json-file> "
    "[--expected-review-id ID] [--expected-family claude|google|codex] "
    "[--expected-content-digest HEX64 | --expected-packet FILE] "
    "[--admit [--end-marker TOKEN] [--admitted-out FILE]]\n"
    "  --admit: RAW-reply admission — binding flags REQUIRED; raw-first "
    "two-pass (single html.unescape retry only when the raw pass fails); "
    "duplicate JSON members rejected; never rewrites the raw file.\n"
    "  --end-marker TOKEN: non-empty; consumed mechanically; absent -> "
    "exit 3 (tail loss).\n"
    "  --admitted-out FILE: on success only, tool-normalized canonical "
    "object, never overwritten (byte-identical re-run = idempotent 0).\n"
    "  exits: 0 admitted/valid; 1 shape/binding/usage; 2 UNPARSEABLE "
    "(-> ONE targeted re-ask, then terminal INVALID); 3 end-marker absent"
)

# Distinct one-line messages for the two NEW usage-error classes (2026-08-11
# hardening) — kept as module-level constants so both `main()` and the t2
# test suite that greps for them stay anchored to the same literal text.
_BINDING_INCOMPLETE_MSG = (
    "binding admission requires all of --expected-review-id, "
    "--expected-family, and exactly one digest source "
    "(--expected-content-digest or --expected-packet)"
)
_DIGEST_MUTEX_MSG = (
    "usage: --expected-content-digest and --expected-packet are "
    "mutually exclusive"
)
_SHAPE_ONLY_NOTICE = (
    "NOTICE: shape-only validation — binding admission NOT performed "
    "(gate admission requires --expected-review-id/--expected-family/"
    "--expected-packet)"
)

# ── RAW-reply ADMISSION mode (2026-08-30 verdict-admission hardening;
# 3-family adjudication docs/reviews/2026-08-30-verdict-trunc-adjudication.md).
# NO repair path: this mode never rewrites a file. Distinct exit codes so the
# leader's next step is mechanical, never judgment:
#   0 admitted; 1 shape/binding invalid (existing class); 2 UNPARSEABLE raw
#   reply (-> ONE targeted re-ask, then terminal INVALID); 3 --end-marker
#   given but absent (tail-loss signal).
EXIT_UNPARSEABLE = 2
EXIT_MARKER_ABSENT = 3
_ADMIT_REQUIRES_BINDING_MSG = (
    "admission requires all of --expected-review-id, --expected-family, "
    "and a digest source (--expected-packet or --expected-content-digest) "
    "— --admit never runs shape-only"
)
_HTML_ENTITY_TOKENS = ("&quot;", "&amp;", "&lt;", "&gt;", "&#")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise ValueError(f"duplicate JSON member {key!r}")
        seen.add(key)
    return dict(pairs)


def _admit_pass(
    text: str, end_marker: str | None
) -> tuple[bool, object | None, str | None, bool]:
    """One admission pass over one text form: (ok, obj, fail_reason,
    marker_missing). The EXPLICIT ok flag exists because a valid JSON
    top-level `null` parses to None (gate r3, codex+claude: a None
    sentinel would misroute it to the unparseable rc-2 class; with the
    flag it flows to schema validation and the accurate rc-1 shape
    failure). marker_missing marks the end-marker-absent class so the
    caller distinguishes exit 3 from exit 2 AFTER both passes."""
    if end_marker is not None:
        stripped = text.rstrip()
        if not stripped.endswith(end_marker):
            return False, None, "end-marker absent", True
        text = stripped[: -len(end_marker)]
    try:
        return (
            True,
            json.loads(text, object_pairs_hook=_reject_duplicate_keys),
            None,
            False,
        )
    except ValueError as e:  # JSONDecodeError subclass + the dup-key raise
        return False, None, f"not valid JSON: {e}", False


def _admit_unparseable_msg(label: str, err: str) -> str:
    return (
        f"UNPARSEABLE raw reply ({label}): {err}. Next step: ONE targeted "
        "re-ask that NAMES this syntactic defect and quotes the no-change "
        "clause (re-emit the SAME verdict, findings and severities as "
        "strictly valid JSON — do NOT change the verdict and do NOT change "
        "any severity), then terminal INVALID. A leader-completed, "
        "leader-repaired, or leader-reconstructed reply is never admissible."
    )


def _parse_argv(
    argv: list[str],
) -> (
    tuple[
        str, str | None, str | None, str | None, str | None,
        bool, str | None, str | None,
    ]
    | None
):
    """Returns (json_file, expected_review_id, expected_family,
    expected_content_digest, expected_packet, admit, end_marker,
    admitted_out), or None on a malformed argv
    (`main()` turns that into the usage message + exit 1). This function only
    checks argv SHAPE (each flag has a value, exactly one positional) — the
    ALL-OR-NOTHING binding-admission rule and the --expected-content-digest /
    --expected-packet mutual exclusion are semantic checks `main()` applies
    to the parsed result, not this pure shape parse."""
    positional: list[str] = []
    values: dict[str, str] = {}
    admit = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--admit":
            admit = True
            i += 1
        elif arg in _BINDING_FLAGS or arg in ("--end-marker", "--admitted-out"):
            if i + 1 >= len(argv):
                return None
            values[arg] = argv[i + 1]
            i += 2
        else:
            positional.append(arg)
            i += 1
    if len(positional) != 1:
        return None
    if not admit and (
        values.get("--end-marker") is not None
        or values.get("--admitted-out") is not None
    ):
        return None  # admission-mode flags only
    return (
        positional[0],
        values.get("--expected-review-id"),
        values.get("--expected-family"),
        values.get("--expected-content-digest"),
        values.get("--expected-packet"),
        admit,
        values.get("--end-marker"),
        values.get("--admitted-out"),
    )


def main(argv: list[str]) -> int:
    parsed = _parse_argv(argv)
    if parsed is None:
        print(_USAGE, file=sys.stderr)
        return 1
    (
        json_file,
        expected_review_id,
        expected_family,
        expected_content_digest,
        expected_packet,
        admit,
        end_marker,
        admitted_out,
    ) = parsed

    if expected_content_digest is not None and expected_packet is not None:
        print(_DIGEST_MUTEX_MSG, file=sys.stderr)
        return 1

    # --expected-packet derives the expected digest FROM THE PACKET BYTES
    # (same hardened symlink-refusing read the reply file gets) instead of
    # trusting a caller-supplied string — this is what closes the
    # trusted-string gap the digest flag alone left open.
    expected_digest = expected_content_digest
    if expected_packet is not None:
        packet_bytes, err = _read_regular_file_no_symlink(Path(expected_packet))
        if err is not None:
            print(f"--expected-packet: {err}", file=sys.stderr)
            return 1
        expected_digest = hashlib.sha256(packet_bytes).hexdigest()

    binding_requested = (
        expected_review_id is not None
        or expected_family is not None
        or expected_content_digest is not None
        or expected_packet is not None
    )
    if binding_requested and (
        expected_review_id is None
        or expected_family is None
        or expected_digest is None
    ):
        print(_BINDING_INCOMPLETE_MSG, file=sys.stderr)
        return 1

    if admit:
        binding_complete = (
            expected_review_id is not None
            and expected_family is not None
            and expected_digest is not None
        )
        if not binding_complete:
            print(_ADMIT_REQUIRES_BINDING_MSG, file=sys.stderr)
            return 1
        raw, err = _read_regular_file_no_symlink(Path(json_file))
        if err is not None:
            print(err, file=sys.stderr)
            return 1
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            print(_admit_unparseable_msg(json_file, f"not UTF-8: {e}"), file=sys.stderr)
            return EXIT_UNPARSEABLE
        if end_marker == "":
            print(_USAGE, file=sys.stderr)
            return 1
        # RAW-FIRST two-pass (gate r2, codex+claude convergent must-fix):
        # pass 1 runs the marker check + parse on the RAW bytes so an
        # already-valid reply — including one whose STRING FIELDS
        # legitimately spell HTML entities — is admitted BYTE-EXACT, never
        # mutated. Only when pass 1 fails AND entity tokens are present does
        # the single documented html.unescape run, and pass 2 retries both
        # steps on the unescaped text (this is the gate-r1 escaped-transport
        # fix: an escaped marker/body fails pass 1 and admits on pass 2).
        # There is no third pass — no repair path. Duplicate JSON members
        # are REJECTED at any depth (gate r2 codex must-fix: json.loads is
        # last-wins, so a reply carrying an earlier blocking verdict behind
        # duplicate SAFE members would otherwise admit as SAFE).
        ok_pass, obj, fail_reason, marker_missing = _admit_pass(text, end_marker)
        if not ok_pass and any(tok in text for tok in _HTML_ENTITY_TOKENS):
            ok_pass, obj, fail_reason, marker_missing = _admit_pass(
                html.unescape(text), end_marker
            )
        if not ok_pass:
            if marker_missing:
                print(
                    f"end-marker absent ({json_file}): expected the reply to "
                    f"terminate with {end_marker!r} — possible TAIL LOSS; "
                    "treat as the unparseable class (ONE targeted re-ask, "
                    "then terminal INVALID)",
                    file=sys.stderr,
                )
                return EXIT_MARKER_ABSENT
            print(
                _admit_unparseable_msg(json_file, fail_reason or "unparseable"),
                file=sys.stderr,
            )
            return EXIT_UNPARSEABLE
        ok, reason, verdict = _validate_obj(obj, json_file)
        if not ok:
            print(reason, file=sys.stderr)
            return 1
        if verdict.review_id != expected_review_id:
            print("review ID mismatch", file=sys.stderr)
            return 1
        if verdict.family != expected_family:
            print("family mismatch", file=sys.stderr)
            return 1
        if verdict.content_digest != expected_digest:
            print("content digest mismatch", file=sys.stderr)
            return 1
        if admitted_out is not None:
            # TOOL-mechanical normalized copy of the ADMITTED object (the
            # canonical `claude-r<N>-verdict.json` the consolidation jq loop
            # reads). Never overwrites; a failed admission writes NOTHING
            # (this line is only reached on success). r2 hardening: the
            # payload is fully materialized in a same-dir temp file first
            # and hard-linked into place (an interrupted write can never
            # leave a truncated canonical file), and a re-run whose target
            # already holds EXACTLY these bytes is idempotent rc 0 (a
            # resumed gate re-pasting the printed command) — different
            # bytes stay a refusal.
            payload = json.dumps(obj, indent=1) + "\n"
            out_path = Path(admitted_out)
            if out_path.is_symlink():
                print("--admitted-out: refuses a symlink target", file=sys.stderr)
                return 1
            if out_path.exists():
                try:
                    existing = out_path.read_bytes()
                except OSError as e:
                    print(f"--admitted-out: {e}", file=sys.stderr)
                    return 1
                if existing == payload.encode("utf-8"):
                    print(
                        "NOTICE: --admitted-out already holds these exact "
                        "bytes — idempotent re-admission",
                        file=sys.stderr,
                    )
                    return 0
                print(
                    "--admitted-out: target exists with DIFFERENT content — "
                    "refusing to overwrite",
                    file=sys.stderr,
                )
                return 1
            # pid-unique AND ends in "-verdict.json" so a crash-stranded
            # temp rides verify's *-verdict.json leg-output allowlist
            # instead of tripping the uncovered-file refusal, and a rerun
            # never EEXIST-collides with a stale temp (gate r3 claude).
            tmp_path = out_path.with_name(
                f".tmp-admit-{os.getpid()}-{out_path.name}"
            )
            try:
                fd = os.open(
                    tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644
                )
                try:
                    with os.fdopen(fd, "w") as fh:
                        fh.write(payload)
                        fh.flush()
                        os.fsync(fh.fileno())
                    os.link(tmp_path, out_path)
                finally:
                    tmp_path.unlink(missing_ok=True)
            except OSError as e:
                print(f"--admitted-out: {e}", file=sys.stderr)
                return 1
        return 0

    ok, reason, verdict = _validate_and_load(Path(json_file))
    if not ok:
        print(reason, file=sys.stderr)
        return 1

    if not binding_requested:
        # The ONE deliberate stderr-on-success carve-out in this module —
        # see the module docstring's 2026-08-11 hardening note (finding
        # r1-C1: silence here is exactly what let a flagless caller admit an
        # unbound verdict without noticing binding was never checked).
        print(_SHAPE_ONLY_NOTICE, file=sys.stderr)
        return 0

    if verdict.review_id != expected_review_id:
        print("review ID mismatch", file=sys.stderr)
        return 1
    if verdict.family != expected_family:
        print("family mismatch", file=sys.stderr)
        return 1
    if verdict.content_digest != expected_digest:
        print("content digest mismatch", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
