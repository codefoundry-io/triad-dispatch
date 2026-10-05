#!/usr/bin/env python3
"""Render v2 review-leg prompts from the VENDORED shared-spec clause files.

Slice S3 of the host A v2 implementation. The clause text that a review leg
receives is no longer a Python string constant: it is the byte-frozen payload
under ``spec/prompts/`` (``common-clauses.md`` plus one ``leg-<family>.md`` per
family, plus ``investigation.md``). This module is the only thing that turns
those bytes into a prompt, and it does exactly four things:

1. parse each clause (``## <name> (<note>)`` followed by ONE fenced block),
2. concatenate the clauses named by that leg file's ``## order`` list, dropping
   the A-only clauses when the corresponding host control is off,
3. substitute the frozen invocation's binding placeholders, refusing to emit an
   unresolved one,
4. report which clause BYTES were sent (``render_with_manifest`` -> sha256 per
   clause), so a round record can prove provenance.

Spec files are read, never written. A malformed spec file (two fenced blocks
under one header, a header with no block, a duplicate clause name, an unknown
``order`` reference, a non-blank ``## order`` line that is not an order item,
non-blank prose outside a clause's fenced block) is a hard error naming
``file:line`` -- a partially rendered prompt would silently weaken a review
leg's contract. One exception: in a clause LIBRARY (``common-clauses.md``,
``investigation.md``) prose AFTER a clause's fenced body is the spec's
renderer note (the note after ``review-no-web`` says how to fill
``<review-web-policy>``); it is never leg text, so it is skipped.

Review stage (R-PROMPT, case C60)
---------------------------------
``RenderCtx.review_kind`` is the resolved stage of the round
(``contracts/review-kind.schema.json``): ``formal-plan`` selects the shared
``plan-purpose`` clause, ``pre-merge`` and ``implementation-review`` select
``code-purpose``. The leg files' ``common:<review-purpose>`` order item is
replaced by exactly that one clause, the manifest names the selected clause,
and ``<review-kind>`` is filled with the stage. Omission resolves to
``DEFAULT_REVIEW_KIND`` at an INVOCATION boundary only (this module's CLI,
``review_scratch.py prepare --v2``); the library refuses a ``None``, empty or
unknown stage instead of defaulting it.

Review web (R-REVIEW-WEB, case C32)
-----------------------------------
``RenderCtx.review_web_authorized`` is the round's BOUND strict boolean and
``RenderCtx.review_date`` its bound UTC date (``YYYY-MM-DD``). Every
``<review-web-policy>`` is filled with the fenced ``review-web-permission``
clause for true and the fenced ``review-no-web`` clause for false -- the text
is taken from ``common-clauses.md``, never from a code constant -- and the
selected clause joins the manifest right after the clause that carries the
placeholder, so a re-vendored policy text is a changed basis. ``<review-date>``
is filled with the bound date. A ``None`` or non-boolean condition and a date
that is not ``YYYY-MM-DD`` are refused, never defaulted. The investigation
``web-evidence`` clause (R-INVEST) is never part of a review render.

Line discipline
---------------
Clause bytes are parsed by splitting on ``"\\n"`` ONLY. ``str.splitlines()``
also breaks on CR, U+2028, U+2029, U+0085 and the C0 separators, which would
silently REWRITE a clause body and break byte identity with the vendored file;
any of those characters in a spec file is therefore a hard error naming it.

A-only and B-only clauses
-------------------------
A clause (or an ``## order`` item) whose note says ``B-only`` renders on host B
only, so this host skips it. A clause (or an ``## order`` item) is host-A-only
when its parenthetical note
carries one of the EXPLICIT marker phrases in ``A_ONLY_MARKERS`` -- ``A-only``,
``(A)``, ``A raw-reply admission only``, ``A live-hook route only``,
``A active-hook route only``, ``Host-A only``, ``host A only``. Prose that
merely mentions the letter A (``A's shipped ...``, ``Host A ships ...``) or a
rule anchor (``R-AGREE``) is NOT a marker: an earlier standalone-``A`` regex
matched the ``adversarial-framing`` header note and silently dropped that
SHARED clause from the codex prompt (gate 1, rows 1 + 30). A clause marked
A-only in a family that has no A-only axis is a spec inconsistency, not a
silent drop.

An axis may carry a further ROUTE dimension: ``hook_active`` is the agy review
route's PreToolUse hook, so its clause renders only when the control is on AND
``ctx.google_route == "agy"`` (``_axis_live``). ``raw_admission`` has no route
dimension.

Angle tokens
------------
Twelve placeholders are SUBSTITUTED: ``<worktree>``, ``<brief-file>``,
``<packet-files>``, ``<gated-patch-file>``, ``<review-id>``,
``<content-digest>``, ``<leg-name>``, ``<attempt>``, ``<google-route>``,
``<review-kind>``, ``<review-date>``, ``<review-web-policy>``.
Four further angle tokens are LITERAL clause text, not placeholders, and are
allowed to survive: ``<END-VERDICT>`` (the end marker the claude leg must emit
for raw-reply admission) and ``<echo>`` / ``<non-empty>`` / ``<repo-relative>``,
which are part of the JSON-shape template inside ``claude-verdict-shape``.
Anything else surviving substitution is a hard error.

Test seam: ``TRIAD_PROMPTS_V2_DIR`` overrides the clause directory, and is
honored ONLY when ``TRIAD_TEST_SEAMS=1`` is set as well. When it takes effect
the module prints one stderr NOTE and ``--manifest`` records ``spec_dir`` +
``seam_active``, so a production render can never silently read clause bytes
from somewhere other than the vendored directory.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SPEC_DIR = Path(__file__).resolve().parents[1] / "spec" / "prompts"
SPEC_DIR_ENV = "TRIAD_PROMPTS_V2_DIR"
TEST_SEAMS_ENV = "TRIAD_TEST_SEAMS"

COMMON_FILE = "common-clauses.md"
INVESTIGATION_FILE = "investigation.md"
INVESTIGATION_CLAUSE = "web-evidence"
LEG_FILES = {
    "claude": "leg-claude.md",
    "codex": "leg-codex.md",
    "google": "leg-google.md",
}

# The A-only AXIS is per family: the claude leg's host-A difference is raw-reply
# admission (the output-shape notice and the output-integrity marker), the
# Google leg's is the active PreToolUse hook (the hook/audit clause). The codex
# leg carries no A-only clause.
A_ONLY_AXIS: dict[str, str | None] = {
    "claude": "raw_admission",
    "codex": None,
    "google": "hook_active",
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
PURPOSE_REF = "common:<review-purpose>"
# R-REVIEW-WEB (case C32): the bound condition -> the ONE shared clause that
# fills `<review-web-policy>`. The clause TEXT lives in the vendored fence.
REVIEW_WEB_POLICY = {True: "review-web-permission", False: "review-no-web"}
WEB_POLICY_PLACEHOLDER = "<review-web-policy>"
# The bound round date (R-PROMPT): a UTC calendar date YYYY-MM-DD in ASCII
# digits (`\d` also matches other scripts' digits). `_valid_date` is the ONE
# validator; `collect_v2` reads a bound date with it too.
_REVIEW_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

LITERAL_ANGLE_TOKENS = frozenset(
    {"<END-VERDICT>", "<echo>", "<non-empty>", "<repo-relative>"}
)

_HEADER_RE = re.compile(r"^##\s+([A-Za-z0-9][A-Za-z0-9_-]*)\s*(?:\((.*)\))?\s*$")
_ORDER_RE = re.compile(r"^\s*(\d+)\.\s+(\S+)\s*(?:\((.*)\))?\s*$")
_FENCE_RE = re.compile(r"^```")
# An A-only marker is one of these EXACT phrases inside the header note or the
# order-line parenthetical -- case-sensitive on the `A`. Matching is literal
# containment, never a word-boundary heuristic: "A's shipped", "Host A ships"
# and rule anchors such as "R-AGREE" must NOT mark a clause A-only.
A_ONLY_MARKERS = (
    "A-only",
    "(A)",
    "A raw-reply admission only",
    "A live-hook route only",
    "A active-hook route only",
    "Host-A only",
    "host A only",
)
# The other host's marker: its clauses are skipped here (prompts/README.md
# § Clause-file format).
B_ONLY_MARKER = "B-only"
_ANGLE_RE = re.compile(r"<[A-Za-z][A-Za-z0-9_-]*>")
_PLACEHOLDER_RE = re.compile(
    r"<(worktree|brief-file|packet-files|gated-patch-file|review-id"
    r"|content-digest|leg-name|attempt|google-route|review-kind"
    r"|review-date|review-web-policy)>"
)
# Characters `str.splitlines()` treats as line breaks but `split("\n")` does
# not: any of them inside a vendored clause file would make the parsed body
# differ from the file bytes, so they are refused rather than normalized.
_FORBIDDEN_BREAKS = {
    "\r": "CR (U+000D)",
    "\x0b": "VT (U+000B)",
    "\x0c": "FF (U+000C)",
    "\x1c": "FS (U+001C)",
    "\x1d": "GS (U+001D)",
    "\x1e": "RS (U+001E)",
    "\x85": "NEL (U+0085)",
    "\u2028": "LINE SEPARATOR (U+2028)",
    "\u2029": "PARAGRAPH SEPARATOR (U+2029)",
}

ORDER_SECTION = "order"


def _is_a_only(note: str) -> bool:
    """True when a header note / order parenthetical carries an A-only marker."""
    return any(marker in note for marker in A_ONLY_MARKERS)


def _is_b_only(note: str) -> bool:
    """True when a header note / order parenthetical marks a host-B-only clause."""
    return B_ONLY_MARKER in note


class PromptSpecError(Exception):
    """A vendored clause file is malformed, or a render is unresolvable."""


@dataclass(frozen=True)
class Clause:
    name: str
    header_note: str
    body: str

    @property
    def a_only(self) -> bool:
        return _is_a_only(self.header_note)

    def sha256(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OrderItem:
    ref: str
    a_only: bool
    b_only: bool = False


@dataclass(frozen=True)
class HostControls:
    """Which host-A-only clause families are actually live on this host.

    Host A's real values are both True (its claude leg is admitted from a raw
    reply terminated by ``<END-VERDICT>``, and its agy review route runs an
    active PreToolUse hook). False drops the matching A-only clauses, so the
    same clause files also describe a host without those controls.
    """

    hook_active: bool = True
    raw_admission: bool = True


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

    def substitutions(self, family: str) -> dict[str, str]:
        route = self.google_route if family == "google" else None
        return {
            "<worktree>": self.worktree,
            "<brief-file>": self.brief_file,
            "<packet-files>": ", ".join(self.packet_files),
            "<gated-patch-file>": self.gated_patch_file,
            "<review-id>": self.review_id,
            "<content-digest>": self.content_digest,
            "<leg-name>": self.leg_name,
            "<attempt>": str(self.attempt),
            "<google-route>": route if route else "null",
            "<review-kind>": str(self.review_kind),
            "<review-date>": str(self.review_date),
        }


_seam_noted = False


def _seam_active() -> bool:
    """True when the clause-directory TEST SEAM is both set and unlocked."""
    return bool(os.environ.get(SPEC_DIR_ENV)) and (
        os.environ.get(TEST_SEAMS_ENV) == "1"
    )


def spec_dir() -> Path:
    """The clause directory: the vendored one unless the gated seam is active.

    ``TRIAD_PROMPTS_V2_DIR`` alone does nothing -- a production render cannot
    be redirected by a stray environment variable. With ``TRIAD_TEST_SEAMS=1``
    beside it the override applies and says so once on stderr.
    """
    global _seam_noted
    if not _seam_active():
        return DEFAULT_SPEC_DIR
    override = os.environ[SPEC_DIR_ENV]
    if not _seam_noted:
        print(
            f"NOTE: prompts_v2: TEST SEAM active — clauses read from {override}",
            file=sys.stderr,
        )
        _seam_noted = True
    return Path(override)


# ---------------------------------------------------------------------------
# parsing
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
    """The file text, refused when a non-LF line break would rewrite a body.

    ``newline=""`` disables Python's universal-newline translation, which
    would otherwise turn a CR in the vendored bytes into LF before this check
    ever saw it (and `Path.read_text(newline=...)` needs 3.13, while the
    supported floor is 3.12).

    EVERY WAY THE READ CAN FAIL IS A `PromptSpecError` (gate-1 r9 row
    r9-13). The open/read carried no handler, so an OSError — mode 000 on a
    vendored clause file, an EIO on the media it sits on — escaped as a
    traceback out of a library whose every other clause failure is one
    refusal line naming the file. `UnicodeDecodeError` is named beside it:
    non-UTF-8 bytes in a clause file are the same class of "this file cannot
    be read as a clause", and it is not an OSError.
    """
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise PromptSpecError(
            f"{filename}: the vendored clause file at {path} cannot be read "
            f"({' '.join(str(exc).split())})"
        ) from exc
    for char, label in _FORBIDDEN_BREAKS.items():
        if char in text:
            raise PromptSpecError(
                f"{filename}: contains {label}; a vendored clause file uses LF "
                f"line breaks only (any other break would silently rewrite the "
                f"clause bytes)"
            )
    return text


def _parse_file(
    filename: str, *, order_list: bool = True
) -> tuple[dict[str, Clause], list[OrderItem]]:
    """Parse one clause file. ``order_list`` marks a LEG file, whose ``## order``
    section is a machine-read list: every non-blank line there must be an order
    item. In a clause LIBRARY (``common-clauses.md``, ``investigation.md``) the
    same header is documentation prose and is not parsed."""
    path = spec_dir() / filename
    if not path.is_file():
        raise PromptSpecError(f"{filename}: vendored clause file not found at {path}")
    clauses: dict[str, Clause] = {}
    order: list[OrderItem] = []
    cur: tuple[str, str, int] | None = None
    body: list[str] | None = None
    fence: list[str] | None = None
    fence_start = 0
    in_order = False

    for lineno, line in enumerate(
        _read_spec_text(path, filename).split("\n"), start=1
    ):
        if fence is not None:
            if _FENCE_RE.match(line):
                body = fence
                fence = None
            else:
                fence.append(line)
            continue

        header = _HEADER_RE.match(line)
        if header:
            _close_section(clauses, cur, body, filename)
            name = header.group(1)
            cur = (name, (header.group(2) or "").strip(), lineno)
            body = None
            in_order = name == ORDER_SECTION
            continue

        if _FENCE_RE.match(line):
            if cur is None:
                raise PromptSpecError(
                    f"{filename}:{lineno}: fenced block outside any '## <clause>' section"
                )
            if body is not None:
                raise PromptSpecError(
                    f"{filename}:{lineno}: second fenced block under clause "
                    f"'{cur[0]}' (one clause = exactly one fenced body)"
                )
            fence = []
            fence_start = lineno
            continue

        if in_order:
            if not order_list:
                continue
            item = _ORDER_RE.match(line)
            if item:
                number = int(item.group(1))
                if number != len(order) + 1:
                    raise PromptSpecError(
                        f"{filename}:{lineno}: '## order' item numbered {number}, "
                        f"expected {len(order) + 1}"
                    )
                order.append(
                    OrderItem(
                        ref=item.group(2),
                        a_only=_is_a_only(item.group(3) or ""),
                        b_only=_is_b_only(item.group(3) or ""),
                    )
                )
                continue
            if line.strip():
                raise PromptSpecError(
                    f"{filename}:{lineno}: '## order' line is not an order item: "
                    f"{line.strip()[:60]!r} (a skipped line would silently drop a "
                    f"clause from the prompt)"
                )
            continue

        if cur is not None and line.strip():
            if not order_list and body is not None:
                # A LIBRARY clause's renderer note after its fenced body
                # (after `review-no-web`): documentation, never leg text.
                continue
            raise PromptSpecError(
                f"{filename}:{lineno}: non-blank text outside a fenced block "
                f"under clause '{cur[0]}': {line.strip()[:60]!r} (only the fenced "
                f"body is sent to the leg, so this text would be dropped)"
            )

    if fence is not None:
        raise PromptSpecError(f"{filename}:{fence_start}: unterminated fenced block")
    _close_section(clauses, cur, body, filename)
    return clauses, order


def load_clauses(file: str) -> dict[str, Clause]:
    """Parse ``<spec-dir>/<file>`` into ``clause name -> Clause``.

    Reads a clause LIBRARY: a ``## order`` header in such a file documents how
    the host uses the clauses (``investigation.md``) and is not an order list.
    """
    return _parse_file(file, order_list=False)[0]


def load_order(file: str) -> list[OrderItem]:
    """Parse the ``## order`` list of ``<spec-dir>/<file>``."""
    return _parse_file(file)[1]


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def _resolve(
    ref: str,
    own: dict[str, Clause],
    common: dict[str, Clause],
    filename: str,
) -> Clause:
    if ref.startswith("common:"):
        name = ref.split(":", 1)[1]
        clause = common.get(name)
        if clause is None:
            raise PromptSpecError(
                f"{filename}: '## order' names unknown clause '{ref}' "
                f"(not in {COMMON_FILE})"
            )
        return clause
    clause = own.get(ref)
    if clause is None:
        raise PromptSpecError(f"{filename}: '## order' names unknown clause '{ref}'")
    return clause


def _axis_live(axis: str, ctx: RenderCtx, controls: HostControls) -> bool:
    """Whether this render's A-only ``axis`` describes THIS invocation.

    The host control is necessary, not sufficient. ``hook_active`` names the
    PreToolUse hook of host A's **agy** review route, so the clause is a true
    statement only on an agy-routed render; sending it to a gemini-routed leg
    told that leg a hook was auditing its tool steps when none was
    (gate 1 r2, claude Minor). ``raw_admission`` has no route dimension --
    the claude leg is native on every route -- so it reads the control alone.
    """
    live = bool(getattr(controls, axis))
    if axis == "hook_active":
        return live and ctx.google_route == "agy"
    return live


def render_with_manifest(
    family: str,
    ctx: RenderCtx,
    controls: HostControls,
) -> tuple[str, list[tuple[str, str]]]:
    """Render ``family``'s prompt and the ordered ``(clause ref, sha256)`` list.

    The digests are taken over the clause bodies AS VENDORED (before
    substitution), so a round record can name the exact spec bytes that were
    sent to the leg.

    Kept at TWO return values for existing callers; a caller that also needs
    the clause directory and the seam state calls ``render_with_provenance``.
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
    filename = LEG_FILES[family]
    own, order = _parse_file(filename)
    common = load_clauses(COMMON_FILE)
    if not order:
        raise PromptSpecError(f"{filename}: '## order' list is empty")
    policy_ref = "common:" + REVIEW_WEB_POLICY[ctx.review_web_authorized]
    policy = _resolve(policy_ref, own, common, filename)

    axis = A_ONLY_AXIS[family]
    subs = ctx.substitutions(family)
    subs[WEB_POLICY_PLACEHOLDER] = policy.body
    bodies: list[str] = []
    manifest: list[tuple[str, str]] = []

    for item in order:
        ref = item.ref
        if ref == PURPOSE_REF:
            ref = "common:" + REVIEW_PURPOSE[ctx.review_kind]
        clause = _resolve(ref, own, common, filename)
        if item.b_only or _is_b_only(clause.header_note):
            continue
        if item.a_only or clause.a_only:
            if axis is None:
                raise PromptSpecError(
                    f"{filename}: clause '{ref}' is marked A-only, but the "
                    f"{family} leg has no A-only axis — either the marker or the "
                    f"axis table is wrong (a silent drop is not an option)"
                )
            if not _axis_live(axis, ctx, controls):
                continue
        # The leftover check runs on the TEMPLATE, never on the rendered text:
        # a binding VALUE may legitimately contain an angle token (a worktree
        # path under a directory named for the review id), and re-scanning the
        # substituted text would reject it as unresolved.
        leftover = sorted(
            {
                tok
                for tok in _ANGLE_RE.findall(clause.body)
                if tok not in LITERAL_ANGLE_TOKENS and tok not in subs
            }
        )
        if leftover:
            raise PromptSpecError(
                f"{filename}: unresolved placeholder(s) in the {family} clause "
                f"'{ref}': {', '.join(leftover)}"
            )
        # ONE pass: `re.sub` never re-scans what it inserted, so a value that
        # itself spells a placeholder is carried through verbatim.
        bodies.append(_PLACEHOLDER_RE.sub(lambda m: subs[m.group(0)], clause.body))
        manifest.append((ref, clause.sha256()))
        if WEB_POLICY_PLACEHOLDER in clause.body:
            manifest.append((policy_ref, policy.sha256()))

    return "\n\n".join(bodies), manifest


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


def render_with_provenance(
    family: str,
    ctx: RenderCtx,
    controls: HostControls,
) -> tuple[str, list[tuple[str, str]], Path, bool]:
    """``(text, manifest, spec_dir, seam_active)`` for ONE leg prompt.

    The manifest alone proves WHICH clause bytes were sent; it cannot say
    WHERE they came from. A round record that names only the digests cannot
    distinguish a vendored render from a seam render of identical text, so a
    library consumer (`review_scratch`'s `.roster-r<N>.json`) had no way to
    show a seam render at all (gate 1 r2 row r2-13). Both provenance values
    are read AFTER the render, so ``spec_dir`` is the directory the clauses
    were actually read from.
    """
    text, manifest = render_with_manifest(family, ctx, controls)
    return text, manifest, spec_dir(), _seam_active()


def render(family: str, ctx: RenderCtx, controls: HostControls) -> str:
    """Render ``family``'s leg prompt from the vendored clause bytes."""
    return render_with_manifest(family, ctx, controls)[0]


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


def investigation_clause_sha256(route: str) -> str:
    """sha256 of the investigation clause AS RENDERED for ``route``."""
    return hashlib.sha256(
        render_investigation_clause(route).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompts_v2.py",
        description="Render a v2 review-leg prompt from the vendored spec clauses.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render_cmd = sub.add_parser("render", help="render one leg prompt")
    render_cmd.add_argument("family", choices=sorted(LEG_FILES))
    render_cmd.add_argument("--worktree", required=True)
    render_cmd.add_argument("--review-id", required=True)
    render_cmd.add_argument("--content-digest", required=True)
    render_cmd.add_argument("--leg-name", required=True)
    render_cmd.add_argument("--attempt", required=True)
    render_cmd.add_argument("--google-route", choices=list(INVESTIGATION_ROUTES))
    render_cmd.add_argument(
        "--review-kind",
        choices=list(REVIEW_PURPOSE),
        default=DEFAULT_REVIEW_KIND,
        help=f"review stage (R-PROMPT); omitted = {DEFAULT_REVIEW_KIND}",
    )
    render_cmd.add_argument(
        "--review-web-authorized",
        choices=["true", "false"],
        required=True,
        help="the round's bound review-web condition (R-REVIEW-WEB): true "
        "renders the review-web-permission clause, false review-no-web",
    )
    render_cmd.add_argument(
        "--review-date",
        required=True,
        help="the round's bound UTC date YYYY-MM-DD (fills <review-date>)",
    )
    render_cmd.add_argument("--brief-file", default="brief.md")
    render_cmd.add_argument("--gated-patch-file", default="diff.prod.patch")
    render_cmd.add_argument(
        "--packet-file",
        action="append",
        dest="packet_files",
        help="repeatable; defaults to the A packet set",
    )
    render_cmd.add_argument(
        "--no-hook",
        action="store_true",
        help="this host has no active agy PreToolUse hook (drop the hook/audit clause)",
    )
    render_cmd.add_argument(
        "--no-raw-admission",
        action="store_true",
        help="this host does not admit the claude leg from a raw reply "
        "(drop the output-shape and output-integrity clauses)",
    )
    render_cmd.add_argument(
        "--manifest",
        action="store_true",
        help="print the JSON clause manifest instead of the prompt",
    )

    inv_cmd = sub.add_parser("investigation", help="print the web-evidence clause")
    inv_cmd.add_argument("route", choices=list(INVESTIGATION_ROUTES))
    inv_cmd.add_argument(
        "--sha256", action="store_true", help="print the clause digest instead"
    )
    return parser


def _relax_std_stream_errors() -> None:
    """NEVER DIE ON AN ENCODER — the DIAGNOSTIC stream only (gate-1 r6 row
    r6-16, SCOPED by r7 row r7-x2).

    Operator text here is em-dash-bearing English and `sys.stderr`'s error
    handler decides whether a refusal reaches its reader under a non-UTF-8
    locale. Only the ERROR HANDLER changes (the encoding is untouched), and
    a stream that cannot be reconfigured is left alone.

    `sys.stdout` is DELIBERATELY NOT relaxed here: this entry point's stdout
    is the PAYLOAD (the rendered clause bytes, the clause manifest, the
    investigation clause), and `backslashreplace` on a payload is a silent
    REWRITER — under `LC_ALL=C` the render exited 0 with the vendored
    em-dashes replaced, so the prompt no longer matched the manifest the
    round record froze. Every payload goes through `_emit_payload`, which
    writes UTF-8 bytes and never consults the locale at all. Full rationale:
    `review_scratch.py::_relax_std_stream_errors` — each v2 lib is
    separately executable and separately vendored, so the call is repeated
    at each entry rather than imported across them."""
    try:
        sys.stderr.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass


def _emit_payload(text: str) -> None:
    """PAYLOAD = UTF-8 BYTES, never re-encoded (gate-1 r7 row r7-x2).

    The clause bytes this command prints are the bytes the leg receives and
    the bytes the round record's manifest digests, so the locale must not
    get a vote: they are encoded once, as UTF-8, and written to the binary
    buffer. `sys.stdout` is flushed first so an interleaved diagnostic keeps
    its order. A harness that replaced `sys.stdout` with a text object has
    no `.buffer`; there the text is written as text, which is what an
    in-process caller asked for.

    A text this host cannot represent as UTF-8 is REFUSED BY NAME (gate-1 r8
    row r8-12). `text.encode("utf-8")` had no handler, so a binding VALUE
    carrying surrogateescape bytes — an argv token CPython decoded under an
    ASCII locale — escaped as a traceback from a command whose every other
    failure is one line. The sibling `review_scratch._emit_payload` already
    refuses that case (row r7-x2); this is the same rule, one library over:
    the clause bytes are what the round record's manifest digests and what
    the leg receives, so an escaped or half-written payload is worse than
    no payload."""
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PromptSpecError(
            f"this render carries a value this host cannot represent as "
            f"UTF-8 ({exc}) — the prompt bytes are what the round record's "
            f"manifest digests and what the leg receives, so they are never "
            f"escaped or partially written; rename the offending path or "
            f"render under a UTF-8 locale") from None
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        # THE FALLBACK TAKES THE SAME REFUSAL (gate-1 r9 row r9-4). Writing
        # the text straight through carried no handler, so a text sink whose
        # encoder is ASCII — an in-process harness, or a `sys.stdout`
        # replaced under a non-UTF-8 locale — raised UnicodeEncodeError out
        # of this library as a traceback. The payload is never rewritten to
        # get past it (`backslashreplace` here would silently change the
        # clause bytes the round record's manifest digests), so the only
        # honest outcome is the refusal the encode step above already uses.
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except UnicodeEncodeError as exc:
            raise PromptSpecError(
                f"this render carries a value the current stdout cannot "
                f"encode ({exc}) — the prompt bytes are what the round "
                f"record's manifest digests and what the leg receives, so "
                f"they are never escaped or partially written; render to a "
                f"binary stream or under a UTF-8 locale") from None
        return
    sys.stdout.flush()
    buffer.write(data)
    buffer.flush()


def main(argv: list[str] | None = None) -> int:
    _relax_std_stream_errors()
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "investigation":
            if args.sha256:
                _emit_payload(investigation_clause_sha256(args.route) + "\n")
            else:
                _emit_payload(render_investigation_clause(args.route) + "\n")
            return 0

        ctx = RenderCtx(
            worktree=args.worktree,
            review_id=args.review_id,
            content_digest=args.content_digest,
            leg_name=args.leg_name,
            attempt=args.attempt,
            google_route=args.google_route,
            brief_file=args.brief_file,
            gated_patch_file=args.gated_patch_file,
            packet_files=tuple(args.packet_files)
            if args.packet_files
            else RenderCtx.__dataclass_fields__["packet_files"].default,
            review_kind=args.review_kind,
            review_web_authorized=args.review_web_authorized == "true",
            review_date=args.review_date,
        )
        controls = HostControls(
            hook_active=not args.no_hook,
            raw_admission=not args.no_raw_admission,
        )
        text, manifest, used_spec_dir, seam = render_with_provenance(
            args.family, ctx, controls)
        if args.manifest:
            _emit_payload(
                json.dumps(
                    {
                        "family": args.family,
                        "controls": {
                            "hook_active": controls.hook_active,
                            "raw_admission": controls.raw_admission,
                        },
                        "review_kind": args.review_kind,
                        "review_web_authorized": ctx.review_web_authorized,
                        "review_date": ctx.review_date,
                        "spec_dir": str(used_spec_dir),
                        "seam_active": seam,
                        "clauses": [
                            {"ref": ref, "sha256": digest} for ref, digest in manifest
                        ],
                    },
                    indent=2,
                )
                + "\n"
            )
        else:
            _emit_payload(text + "\n")
        return 0
    except PromptSpecError as exc:
        print(f"prompts_v2: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
