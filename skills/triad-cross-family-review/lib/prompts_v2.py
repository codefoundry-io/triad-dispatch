"""Render v2 review-leg prompts from the VENDORED shared-spec clause files.

Slice S3 of the host A v2 implementation. The clause text that a review leg
receives is no longer a Python string constant: it is the byte-frozen payload
under ``spec/prompts/`` (``common-clauses.md`` plus one ``leg-<family>.md`` per
family, plus ``investigation.md``). This module is the only thing that turns
those bytes into a prompt, and it does exactly four things:

1. parse each clause (``## <name> (<note>)`` followed by ONE fenced block),
2. concatenate the clauses named by that leg file's ``## order`` list (the
   agy hook clause only on the agy route),
3. substitute the frozen invocation's binding placeholders, refusing to emit an
   unresolved one,
4. report which clause BYTES were sent (``render_with_manifest`` -> sha256 per
   clause), so a round record can prove provenance.

Spec files are read, never written. A malformed spec file (two fenced blocks
under one header, a header with no block, a duplicate clause name, an unknown
``order`` reference) is a hard error naming the file -- a partially rendered
prompt would silently weaken a review leg's contract. Text outside a clause's
fenced block is never leg text and is not read. Recorded limit: a malformed
line in a leg file's ``## order`` list (not ``<n>. <ref>``) is skipped, not
refused; the vendored files are digest-bound (``spec/SPEC_MANIFEST.json``), so
this is a recorded limit, not a runtime check.

Review stage (R-PROMPT, case C60)
---------------------------------
``RenderCtx.review_kind`` is the resolved stage of the round
(``contracts/review-kind.schema.json``): ``formal-plan`` selects the shared
``plan-purpose`` clause, ``pre-merge`` and ``implementation-review`` select
``code-purpose``. The leg files' ``common:<review-purpose>`` order item is
replaced by exactly that one clause, the manifest names the selected clause,
and ``<review-kind>`` is filled with the stage. Omission resolves to
``DEFAULT_REVIEW_KIND`` at the invocation boundary only (``review_scratch.py
prepare``); the library refuses a ``None``, empty or unknown stage instead of
defaulting it.

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

A-only and B-only clauses
-------------------------
A clause (or an ``## order`` item) whose note says ``B-only`` renders on host B
only, so this host skips it. A clause (or an ``## order`` item) whose note
carries the literal marker ``A-only`` is a host-A clause: the claude leg's
raw-reply admission clauses render on every route, and the Google leg's hook
clause renders only when ``ctx.google_route == "agy"`` (the PreToolUse hook
belongs to the agy review route). Prose that merely mentions the letter A
(``A's shipped ...``) is not a marker.

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
"""

from __future__ import annotations

import datetime
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SPEC_DIR = Path(__file__).resolve().parents[1] / "spec" / "prompts"

COMMON_FILE = "common-clauses.md"
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
# The A-only marker: this EXACT phrase inside the header note or the order-line
# parenthetical (literal containment, case-sensitive).
A_ONLY_MARKER = "A-only"
# The other host's marker: its clauses are skipped here (prompts/README.md
# § Clause-file format).
B_ONLY_MARKER = "B-only"
_ANGLE_RE = re.compile(r"<[A-Za-z][A-Za-z0-9_-]*>")
_PLACEHOLDER_RE = re.compile(
    r"<(worktree|brief-file|packet-files|gated-patch-file|review-id"
    r"|content-digest|leg-name|attempt|google-route|review-kind"
    r"|review-date|review-web-policy)>"
)
ORDER_SECTION = "order"


def _is_a_only(note: str) -> bool:
    """True when a header note / order parenthetical carries the A-only marker."""
    return A_ONLY_MARKER in note


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


def _parse_file(
    filename: str, *, order_list: bool = True
) -> tuple[dict[str, Clause], list[OrderItem]]:
    """Parse one clause file. ``order_list`` marks a LEG file, whose ``## order``
    section is a machine-read list of numbered items. In a clause LIBRARY
    (``common-clauses.md``, ``investigation.md``) the same header is
    documentation prose and is not parsed."""
    path = DEFAULT_SPEC_DIR / filename
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
                order.append(
                    OrderItem(
                        ref=item.group(2),
                        a_only=_is_a_only(item.group(3) or ""),
                        b_only=_is_b_only(item.group(3) or ""),
                    )
                )

    if fence is not None:
        raise PromptSpecError(f"{filename}:{fence_start}: unterminated fenced block")
    _close_section(clauses, cur, body, filename)
    return clauses, order


def load_clauses(file: str) -> dict[str, Clause]:
    """Parse ``DEFAULT_SPEC_DIR/<file>`` into ``clause name -> Clause``.

    Reads a clause LIBRARY: a ``## order`` header in such a file documents how
    the host uses the clauses (``investigation.md``) and is not an order list.
    """
    return _parse_file(file, order_list=False)[0]


def load_order(file: str) -> list[OrderItem]:
    """Parse the ``## order`` list of ``DEFAULT_SPEC_DIR/<file>``."""
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


def render_with_manifest(
    family: str,
    ctx: RenderCtx,
) -> tuple[str, list[tuple[str, str]]]:
    """Render ``family``'s prompt and the ordered ``(clause ref, sha256)`` list.

    The digests are taken over the clause bodies AS VENDORED (before
    substitution), so a round record can name the exact spec bytes that were
    sent to the leg.
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
        # The Google leg's A-only clause is the agy review route's hook.
        if ((item.a_only or clause.a_only) and family == "google"
                and ctx.google_route != "agy"):
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
