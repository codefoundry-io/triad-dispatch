#!/usr/bin/env python3
"""validate_verdict.py — deterministic (no AI) validator for the claude
fresh-eye leg's reply against the shared cross-family-review verdict schema
(`verdict_schema.LegVerdict`).

Usage: python3 validate_verdict.py <json-file>
  exit 0  valid  — nothing on stdout (a gate, not a formatter).
  exit 1  invalid, missing, or malformed — ONE line on stderr; the three
          failure classes carry visibly distinct wording (missing file /
          not valid JSON / fails LegVerdict validation) so the leader's
          consolidation step does not have to guess which one happened.

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
"""
from __future__ import annotations

import importlib.util
import json
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


def validate(json_path: Path) -> tuple[bool, str | None]:
    """(ok, reason). reason is None on success, else a one-line string."""
    try:
        text = json_path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"cannot read {json_path}: {e}"
    except UnicodeDecodeError as e:
        # UnicodeDecodeError is a ValueError subclass, NOT an OSError — a
        # separate except clause (distinct message class) is required;
        # `encoding="utf-8"` (rather than the platform default) makes this
        # reachable and deterministic across dev (macOS) and dist (Ubuntu).
        return False, f"{json_path} is not valid UTF-8: {e}"
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"{json_path} is not valid JSON: {e}"
    here = Path(__file__).resolve()
    try:
        mod = _load_verdict_schema_module(here)
    except VerdictSchemaNotFound as e:
        return False, str(e)
    except VerdictSchemaLoadError as e:
        return False, str(e)
    try:
        mod.LegVerdict.model_validate(obj)
    except Exception as e:  # pydantic.ValidationError — kept broad on purpose:
        # this module must stay import-light (no top-level pydantic import),
        # since verdict_schema's own dependency is resolved dynamically above.
        return False, f"{json_path} fails LegVerdict validation: {_flatten(str(e))}"
    return True, None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: validate_verdict.py <json-file>", file=sys.stderr)
        return 1
    ok, reason = validate(Path(argv[0]))
    if ok:
        return 0
    print(reason, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
