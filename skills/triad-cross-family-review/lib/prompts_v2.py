"""Render v2 review-leg prompts through the vendored ``triad_dispatch_lib``.

The clause text a review leg receives is the library's
``render_review_clauses`` over its own packaged prompt bundle
(``lib/triad_dispatch_lib/data/prompt-bundle``), host ``A``. This module keeps
the host's side of that call:

1. its own argument refusals (family, Google route, review stage, the bound
   strict-boolean web condition and the bound date) -- a ``PromptSpecError``,
2. the library import (``verdict_v2._library_import``, loaded LAZILY from this
   file's directory: the wrappers execute this file by path with no ``lib/``
   on ``sys.path`` for the investigation clause, which must render with no
   library at all),
3. the two-stage identity check, by plain file reading: (i) every payload the
   four vendored bundle manifests list equals its manifest digest -- a
   missing, unreadable or differing payload, or a missing, unreadable or
   malformed manifest or adoption record, is a ``_PromptHostFault`` naming the
   ``lib/`` relpath (the callers' HOST FAULT, exit 64); (ii) every pair of
   ``lib-adoption.json["pairs"]`` is byte-equal, the host's ``spec/`` copy
   against the vendored payload -- a missing, unreadable or differing
   ``spec/`` file is a ``PromptSpecError`` naming the ``spec/`` relpath (the
   one-copy rule; exit 2),
4. the mapping of ``RenderCtx`` onto the library's ``replacements`` and the
   library's errors onto the host's: ``PromptError`` -> ``PromptSpecError``,
   ``ContractError`` -> ``_PromptHostFault``. The manifest rows
   ``{name, sha256}`` become ``(name, sha256)`` tuples.

``RenderCtx.review_kind`` is the resolved stage of the round
(``contracts/review-kind.schema.json``); omission resolves to
``DEFAULT_REVIEW_KIND`` at the invocation boundary only (``review_scratch.py
prepare``), and this module refuses a ``None``, empty or unknown stage instead
of defaulting it. ``RenderCtx.review_web_authorized`` and
``RenderCtx.review_date`` are the round's BOUND condition and UTC date: a
``None`` or non-boolean condition and a date that is not ``YYYY-MM-DD`` are
refused, never defaulted.

The investigation ``web-evidence`` clause (R-INVEST) is never part of a review
render. ``render_investigation_clause`` reads it from the host's vendored
``spec/prompts/investigation.md`` with the parser below and imports nothing
else.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
_SKILL_DIR = _LIB_DIR.parent
DEFAULT_SPEC_DIR = _SKILL_DIR / "spec" / "prompts"
_PACKAGE = "triad_dispatch_lib"
# The four vendored bundles (relative to the package): each one's
# `source-manifest.json` lists its payloads and their sha256.
_BUNDLES = ("data", "data/prompt-bundle", "data/roster-bundle",
            "data/receipt-bundle")
_RECORD = "lib-adoption.json"

INVESTIGATION_FILE = "investigation.md"
INVESTIGATION_CLAUSE = "web-evidence"
LEG_FILES = {
    "claude": "leg-claude.md",
    "codex": "leg-codex.md",
    "google": "leg-google.md",
}

# investigation.md, section `## order`: on a gemini route only these two tool
# names change; nothing else in the clause does.
GEMINI_TOOL_SUBSTITUTIONS = (
    ("read_url_content", "web_fetch"),
    ("search_web", "google_web_search"),
)
INVESTIGATION_ROUTES = ("agy", "gemini")

# R-PROMPT (case C60): review stage -> the ONE shared purpose clause it selects.
# The keys are the vocabulary of the vendored `contracts/review-kind.schema.json`
# and DEFAULT_REVIEW_KIND is that schema's annotated default.
REVIEW_PURPOSE = {
    "formal-plan": "plan-purpose",
    "pre-merge": "code-purpose",
    "implementation-review": "code-purpose",
}
DEFAULT_REVIEW_KIND = "pre-merge"
# The bound round date (R-PROMPT): a UTC calendar date YYYY-MM-DD in ASCII
# digits (`\d` also matches other scripts' digits). `_valid_date` is the ONE
# validator; `collect_v2` reads a bound date with it too.
_REVIEW_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

_HEADER_RE = re.compile(r"^##\s+([A-Za-z0-9][A-Za-z0-9_-]*)\s*(?:\((.*)\))?\s*$")
_FENCE_RE = re.compile(r"^```")
ORDER_SECTION = "order"


class PromptSpecError(Exception):
    """A clause file is malformed, a render is unresolvable, or the host's
    `spec/` copy differs from the vendored library payload (exit 2)."""


class _PromptHostFault(Exception):
    """This install cannot render: the vendored library cannot be imported,
    a vendored payload, bundle manifest or the adoption record is missing,
    unreadable or inconsistent, or the library reports a packaged-contract
    fault. ONE line; every caller reports it as its HOST FAULT (exit 64)."""


@dataclass(frozen=True)
class Clause:
    name: str
    header_note: str
    body: str


@dataclass(frozen=True)
class RenderCtx:
    worktree: str
    review_id: str
    content_digest: str
    leg_name: str
    attempt: int | str
    google_route: str | None = None
    brief_file: str = "brief.md"
    gated_patch_file: str = "diff.prod.patch"
    packet_files: tuple[str, ...] = field(
        default=("brief.md", "diff.prod.patch", "diff.tests.patch", "history.txt")
    )
    # No default stage here: omission is resolved at an invocation boundary,
    # and a None / unknown stage is refused by the render (R-PROMPT).
    review_kind: str | None = None
    # The round's BOUND review-web condition and date (R-REVIEW-WEB,
    # R-PROMPT; case C32). No default either: the render refuses None.
    review_web_authorized: bool | None = None
    review_date: str | None = None


# ---------------------------------------------------------------------------
# parsing (the investigation clause library only)
# ---------------------------------------------------------------------------
def _close_section(
    clauses: dict[str, Clause],
    cur: tuple[str, str, int] | None,
    body: list[str] | None,
    filename: str,
) -> None:
    if cur is None:
        return
    name, note, lineno = cur
    if name == ORDER_SECTION:
        if body is not None:
            raise PromptSpecError(
                f"{filename}:{lineno}: the '## order' section must not carry a fenced block"
            )
        return
    if body is None:
        raise PromptSpecError(
            f"{filename}:{lineno}: clause '{name}' has no fenced body"
        )
    if name in clauses:
        raise PromptSpecError(
            f"{filename}:{lineno}: duplicate clause name '{name}'"
        )
    clauses[name] = Clause(name=name, header_note=note, body="\n".join(body))


def _read_spec_text(path: Path, filename: str) -> str:
    """The file text, read with ``newline=""`` (no universal-newline
    translation, so the parsed bytes are the vendored bytes). Every way the
    read can fail -- an OSError or non-UTF-8 bytes -- is a `PromptSpecError`
    naming the file."""
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise PromptSpecError(
            f"{filename}: the vendored clause file at {path} cannot be read "
            f"({' '.join(str(exc).split())})"
        ) from exc


def load_clauses(file: str) -> dict[str, Clause]:
    """Parse the clause LIBRARY ``DEFAULT_SPEC_DIR/<file>`` into ``clause name
    -> Clause``: ``## <name> (<note>)`` followed by ONE fenced block. A
    ``## order`` header documents how the host uses the clauses and is not
    read. Two fenced blocks under one header, a header with no block, a
    duplicate name or an unterminated block is a hard error naming the file."""
    path = DEFAULT_SPEC_DIR / file
    if not path.is_file():
        raise PromptSpecError(f"{file}: vendored clause file not found at {path}")
    clauses: dict[str, Clause] = {}
    cur: tuple[str, str, int] | None = None
    body: list[str] | None = None
    fence: list[str] | None = None
    fence_start = 0
    for lineno, line in enumerate(_read_spec_text(path, file).split("\n"), start=1):
        if fence is not None:
            if _FENCE_RE.match(line):
                body = fence
                fence = None
            else:
                fence.append(line)
            continue
        header = _HEADER_RE.match(line)
        if header:
            _close_section(clauses, cur, body, file)
            cur = (header.group(1), (header.group(2) or "").strip(), lineno)
            body = None
            continue
        if _FENCE_RE.match(line):
            if cur is None:
                raise PromptSpecError(
                    f"{file}:{lineno}: fenced block outside any '## <clause>' section"
                )
            if body is not None:
                raise PromptSpecError(
                    f"{file}:{lineno}: second fenced block under clause "
                    f"'{cur[0]}' (one clause = exactly one fenced body)"
                )
            fence = []
            fence_start = lineno
    if fence is not None:
        raise PromptSpecError(f"{file}:{fence_start}: unterminated fenced block")
    _close_section(clauses, cur, body, file)
    return clauses


# ---------------------------------------------------------------------------
# rendering (through the vendored library)
# ---------------------------------------------------------------------------
def _verdict_v2():
    """The sibling `verdict_v2`, loaded LAZILY by file path (an already-loaded
    one is reused, as `collect_v2._load_sibling` does)."""
    mod = sys.modules.get("verdict_v2")
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(
        "verdict_v2", _LIB_DIR / "verdict_v2.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verdict_v2"] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException as exc:
        sys.modules.pop("verdict_v2", None)
        if not isinstance(exc, Exception):
            raise
        raise _PromptHostFault(
            f"host fault: lib/verdict_v2.py cannot be loaded "
            f"({type(exc).__name__}) — reinstall this host") from exc
    return mod


def _check_identity(read) -> None:
    """Stage (i), the data side against the bundle manifests (host fault),
    then stage (ii), the nine spec<->data pairs byte for byte (caller fault).
    `read(path) -> (bytes | None, reason)` is the hardened regular-file reader
    (lstat, no symlink)."""
    for bundle in _BUNDLES:
        mrel = f"{_PACKAGE}/{bundle}/source-manifest.json"
        raw = read(_LIB_DIR / mrel)[0]
        try:
            listed = json.loads(raw)["sha256"] if raw is not None else None
        except (ValueError, TypeError, KeyError, RecursionError):
            listed = None
        if not (isinstance(listed, dict) and listed and all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in listed.items())):
            raise _PromptHostFault(
                f"host fault: the vendored bundle manifest lib/{mrel} is "
                f"missing, unreadable or malformed — reinstall this host")
        for name, digest in sorted(listed.items()):
            prel = f"{_PACKAGE}/{bundle}/{name}"
            data = read(_LIB_DIR / prel)[0]
            if data is None or hashlib.sha256(data).hexdigest() != digest:
                raise _PromptHostFault(
                    f"host fault: the vendored payload lib/{prel} is missing, "
                    f"unreadable or differs from its bundle manifest "
                    f"lib/{mrel} — reinstall this host")
    raw = read(_LIB_DIR / _RECORD)[0]
    try:
        pairs = json.loads(raw)["pairs"] if raw is not None else None
    except (ValueError, TypeError, KeyError, RecursionError):
        pairs = None
    if not (isinstance(pairs, dict) and pairs and all(
            isinstance(k, str) and isinstance(v, str) for k, v in pairs.items())):
        raise _PromptHostFault(
            f"host fault: the adoption record lib/{_RECORD} is missing, "
            f"unreadable or carries no `pairs` object — reinstall this host")
    for data_rel, spec_rel in sorted(pairs.items()):
        data = read(_LIB_DIR / _PACKAGE / data_rel)[0]
        if data is None:
            raise _PromptHostFault(
                f"host fault: the vendored payload lib/{_PACKAGE}/{data_rel} "
                f"is missing or unreadable — reinstall this host")
        if read(_SKILL_DIR / spec_rel)[0] != data:
            raise PromptSpecError(
                f"{spec_rel}: the spec copy is missing, unreadable or differs "
                f"from the vendored library payload lib/{_PACKAGE}/{data_rel} "
                f"(one-copy rule) — re-vendor the spec from the pinned tag")


def render_with_manifest(
    family: str,
    ctx: RenderCtx,
) -> tuple[str, list[tuple[str, str]]]:
    """Render ``family``'s prompt and the ordered ``(clause ref, sha256)`` list.

    The digests are the library's, over the clause bodies AS VENDORED (before
    substitution), so a round record can name the exact bytes that were sent
    to the leg. Raises `PromptSpecError` (caller fault) or `_PromptHostFault`
    (host fault); see the module docstring for which is which.
    """
    if family not in LEG_FILES:
        raise PromptSpecError(
            f"unknown family '{family}' (expected one of {sorted(LEG_FILES)})"
        )
    if family == "google" and ctx.google_route not in INVESTIGATION_ROUTES:
        raise PromptSpecError(
            f"the google leg needs google_route in {list(INVESTIGATION_ROUTES)}, "
            f"got {ctx.google_route!r}"
        )

    if ctx.review_kind not in REVIEW_PURPOSE:
        raise PromptSpecError(
            f"review_kind {ctx.review_kind!r} is not a review stage "
            f"(expected one of {list(REVIEW_PURPOSE)}); a null or unknown "
            f"stage is refused, never defaulted"
        )
    if type(ctx.review_web_authorized) is not bool:
        raise PromptSpecError(
            f"review_web_authorized {ctx.review_web_authorized!r} is not a "
            f"strict boolean; the round's bound condition is refused, never "
            f"defaulted (R-REVIEW-WEB)")
    if not _valid_date(ctx.review_date):
        raise PromptSpecError(
            f"review_date {ctx.review_date!r} is not a UTC date YYYY-MM-DD; "
            f"the round's bound date is refused, never defaulted (R-PROMPT)")
    verdict_v2 = _verdict_v2()
    lib, why = verdict_v2._library_import()
    if lib is None:
        raise _PromptHostFault(why)
    _check_identity(verdict_v2._read_regular_file_no_symlink)
    route = ctx.google_route if family == "google" else None
    replacements = {
        "worktree": ctx.worktree, "brief-file": ctx.brief_file,
        "packet-files": ", ".join(ctx.packet_files),
        "review-id": ctx.review_id, "content-digest": ctx.content_digest,
        "leg-name": ctx.leg_name, "attempt": str(ctx.attempt),
    }
    if family == "google":
        replacements["gated-patch-file"] = ctx.gated_patch_file
    try:
        text, rows = lib.render_review_clauses(
            family=family, host="A", review_date=ctx.review_date,
            review_web_authorized=ctx.review_web_authorized,
            replacements=replacements, review_kind=ctx.review_kind,
            route=route, agy_hook_active=route == "agy", with_manifest=True)
    except lib.PromptError as exc:
        raise PromptSpecError(
            f"the review library refused the {family} render: {exc}") from exc
    except lib.ContractError as exc:
        raise _PromptHostFault(
            f"host fault: the vendored review library cannot render the "
            f"{family} prompt: {exc} — reinstall this host") from exc
    return text, [(row["name"], row["sha256"]) for row in rows]


def _valid_date(value) -> bool:
    """True for a bound round date: a string, `YYYY-MM-DD` in ASCII digits,
    and a real calendar day. The ONE strict validator — the renderer and
    `collect_v2._bound_metadata` both ask it (A2)."""
    if not (isinstance(value, str) and _REVIEW_DATE_RE.fullmatch(value)):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def render(family: str, ctx: RenderCtx) -> str:
    """Render ``family``'s leg prompt from the vendored clause bytes."""
    return render_with_manifest(family, ctx)[0]


def render_investigation_clause(route: str) -> str:
    """The shared ``web-evidence`` clause for a research (web) dispatch.

    ``agy`` returns the vendored block verbatim; ``gemini`` substitutes the two
    tool names named in ``investigation.md`` § order and changes nothing else.
    """
    clauses = load_clauses(INVESTIGATION_FILE)
    clause = clauses.get(INVESTIGATION_CLAUSE)
    if clause is None:
        raise PromptSpecError(
            f"{INVESTIGATION_FILE}: clause '{INVESTIGATION_CLAUSE}' not found"
        )
    if route == "agy":
        return clause.body
    if route == "gemini":
        text = clause.body
        for agy_name, gemini_name in GEMINI_TOOL_SUBSTITUTIONS:
            text = text.replace(agy_name, gemini_name)
        return text
    raise PromptSpecError(
        f"unknown investigation route '{route}' "
        f"(expected one of {list(INVESTIGATION_ROUTES)})"
    )


if __name__ == "__main__":
    raise SystemExit("prompts_v2.py is a library: import it (it has no command line)")
