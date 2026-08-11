"""verdict_schema.py — the shared cross-family-review verdict schema
(plan `2026-07-31-agy-post-migration-followups`, item (4)).

One pydantic model every review leg's structured-output path validates
against, so the leader consolidates typed objects instead of re-shaping three
legs' free prose by hand:

  - codex leg:  `--pydantic verdict_schema:LegVerdict` -> codex-strict
    `--output-schema` massage (`_common.pydantic_to_codex_schema`).
  - agy leg:    `--pydantic verdict_schema:LegVerdict` -> native
    `--json-schema` (`model_json_schema()`), local pydantic re-validate.
  - claude leg: no wrapper — the leg prompt states this SAME shape as the
    reply contract, and the leader validates the reply with
    `.claude/skills/triad-cross-family-review/lib/validate_verdict.py`
    (imports this module with dual dev/dist path resolution).

Resolved as `module:Class` from the wrapper's OWN directory at runtime (see
`_test_schemas.py`'s importable-module pattern — Python inserts a directly
invoked script's own directory at `sys.path[0]`, so no wrapper-side plumbing
change is needed). Ships to the plugin `bin/` alongside the wrappers
(`export_plugin.BIN_FILES`) — unlike `_test_schemas.py`, which is dev/test
scaffolding only and is deliberately NOT shipped, this module backs a real
dispatch path in production.

Severity and verdict tokens are `Literal[...]` enums with the EXACT token
sets `.claude/skills/triad-cross-family-review/references/triage.md` defines:

  - verdict — the leg's own conforming-verdict shape (`references/triage.md`
    § Reviewer-side instruction "What a conforming verdict looks like"):
    SAFE TO MERGE, MERGE WITH FIXES, DO NOT MERGE.
  - severity — `references/triage.md` § Block release paths states the leg's
    blocking/non-blocking axis as Critical / must-fix / Minor; § Reviewer-side
    instruction adds the fourth token, HARDENING-SUGGESTION, for a scenario
    the packet's deployment-context block rules out ("Label a scenario ...
    HARDENING-SUGGESTION rather than Critical/must-fix"). UNKNOWN-CONTEXT is
    deliberately NOT a fifth severity token: triage.md defines it as an
    impact-rated severity MARKED unknown-context ("report at impact-rated
    severity marked UNKNOWN-CONTEXT"), which is exactly what the separate
    `context_known` field below encodes instead of overloading the enum.

The `LegVerdict` model-level validator below is Flow 4's INVALID-leg rule
("a non-SAFE verdict with NO extractable finding ... is handled identically
to a terminally-missing leg") made mechanical. JSON Schema has no native
if-empty-then-invalid constraint, so this cannot be a schema-only rule; it
runs as a pydantic `model_validator` instead, on TOP of the codex-strict
`--output-schema` / agy native `--json-schema` massage, via
`cls.model_validate_json()` — the SAME post-hoc validation call every
wrapper's `--pydantic` plumbing already performs regardless of vendor-side
schema enforcement (belt-and-suspenders, matching the wrappers' existing
convention: "prompt-side inject_schema_to_prompt + post-hoc validate_response
are both retained regardless").

Hardening adopted 2026-08-10 from the codex-host 0.2.533 schema
(`triad-codex-dispatch`'s `bin/verdict_schema.py` — codex-owned since the
2026-07-25 transfer; a leader-side READ of `origin/main` there, never an
edit — see `3rd-Agent/CLAUDE.md` § Plugin re-deploy on the ownership split.
Engine deltas reach the codex side via the triad commit body, not a shared
import, so this is a one-time cross-pollination, not an ongoing link):
`model_config = ConfigDict(extra="forbid", strict=True)` on both models
(closes an extra-field smuggling gap and makes `line` reject a numeric
string instead of silently coercing it); a POSIX-relative-path guard on
`LegFinding.file` (no backslash, no control character, no absolute or
drive-letter form, no empty/`.`/`..` segment, and the value must equal its
own `PurePosixPath(...).as_posix()` normalization); three NEW required
round/leg-binding fields on `LegVerdict` — `review_id`, `family`,
`content_digest` — so a leader-side consumer can refuse a verdict replayed
from a stale round or attributed to the wrong leg; a `criteria_checked`
duplicate-entry reject; and a SECOND, opposite-direction arm on the
model-level validator (`SAFE TO MERGE` must not carry a `Critical`/
`must-fix` finding). Field NAMES and the verdict/severity TOKEN sets are
NOT mirrored from the reference — that schema uses `SAFE`/`NOT-SAFE` verdict
tokens and a `path`/`correction`/`evidence`/`open_questions` shape with no
`HARDENING-SUGGESTION` severity at all; only the validation TECHNIQUES are
adopted, onto this repo's own `VERDICT_TOKENS`/`SEVERITY_TOKENS` contract.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Single source of truth for the two token sets — a test or a doc that wants
# "every severity/verdict token" iterates these rather than hardcoding a
# second list (same principle t41-review-gate-jq.sh applies to
# `_common._AGY_DIGEST_VALUE_CAP`: read the constant, never retype it).
VERDICT_TOKENS = ("SAFE TO MERGE", "MERGE WITH FIXES", "DO NOT MERGE")
SEVERITY_TOKENS = ("Critical", "must-fix", "Minor", "HARDENING-SUGGESTION")
# The BLOCKING subset of SEVERITY_TOKENS, per `triage.md` § Block release
# paths. Read by BOTH the SAFE-arm model validator below and the
# `nonrepairable_content` retry probe, so the two cannot drift into disagreeing
# about what "blocking" means.
BLOCKING_SEVERITY_TOKENS = ("Critical", "must-fix")

# Sentinel token a validation-error message carries when replaying that error
# into a schema-repair re-dispatch would be HARMFUL rather than merely futile
# (cross-family review finding r1-claude-1, 2026-08-11). `_common.py`'s
# Layer-4 block (and `antigravity_wrapper.py`'s own copy of the same repair
# loop) skip the one-shot repair retry and promote straight to schema-fail
# when they see this substring. Deliberately a plain STRING contract, not an
# exception subclass or an import: the engine must stay schema-agnostic (it
# validates against whatever `--pydantic module:Class` names), so any schema
# can opt an arm out of automated repair without the engine knowing about it.
# `tests/unit/wrappers/t44-nonrepairable-schema-arm.sh` axis 7 pins this
# literal against `_common.NONREPAIRABLE_MARKER` so the two spellings cannot
# drift apart silently.
NONREPAIRABLE_MARKER = "[NONREPAIRABLE]"

# round/leg-binding + path-guard constants (2026-08-10 hardening — see module
# docstring). `review_id` is a caller-chosen token (e.g. a round id); the
# regex only constrains its ALPHABET/shape, not a specific format.
_REVIEW_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_REVIEW_ID_MAX_LEN = 200
_CONTENT_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
# A leading `C:\` or `C:/`-style drive letter is rejected in ADDITION to the
# backslash check below — a drive-letter path using FORWARD slashes
# (`C:/Users/x`) contains no backslash at all and would otherwise slip past.
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[\\/]")


# Anchored severity-key matcher — the RAW-TEXT reader of
# `nonrepairable_content`, consulted on EVERY string path since r8. Built from
# `BLOCKING_SEVERITY_TOKENS` so it can never drift from the tree-scan or the
# SAFE-arm validator. It requires the JSON key-value SYNTAX
# (`"severity": "must-fix"`), NOT the bare word: prose that merely MENTIONS a
# blocking token — a reviewer writing "this is a must-fix issue", or a
# schema-repair hint quoting the token set — must keep its repair turn. That
# false-positive control is a pinned test axis (t44 axis 18), because a probe
# that fires on the word would silently retire the one repair turn the engine
# exists to spend. Inner `\s*` mirrors `_is_blocking_severity`'s `.strip()`.
#
# WHY it is safe on the CLEAN-PARSE branch too (r8 claude Minor — r7 withheld
# it there on a rationale that was factually WRONG). r7 reasoned that inside
# valid JSON this syntax "can only appear ESCAPED, i.e. as the content of some
# string VALUE", and concluded the regex "could only add false positives here".
# The premise is right and the conclusion is backwards: escaped is exactly the
# form this regex CANNOT match. A quote inside a JSON string value is rendered
# `\"`, so the bytes are `\"severity\":` — the character after `severity` is a
# BACKSLASH, and the pattern demands a literal `"`. So on any text `json.loads`
# accepts, a match is only ever a REAL key-value pair, never quoted prose:
# ORing it in is strictly true-positive, and it recovers the blockers the
# tree-scan's `_SCAN_MAX_DEPTH` / `_SCAN_MAX_NODES` bounds give up on. t44 axis
# 26 pins both directions (the escape-rendering proof AND the bound recovery);
# axis 23's false-positive control survives unchanged because of it.
_BLOCKING_SEVERITY_KEY_RE = re.compile(
    r'"severity"\s*:\s*"\s*(?:'
    + "|".join(re.escape(tok) for tok in BLOCKING_SEVERITY_TOKENS)
    + r')\s*"',
    re.IGNORECASE,
)

# Bounds on the recursive tree-scan below. A reply is untrusted input, so the
# scan is explicitly finite in BOTH dimensions rather than relying on the
# payload being well-behaved: `_SCAN_MAX_DEPTH` stops the descent (a blocker
# buried deeper is a DISCLOSED miss, pinned in t44 axis 22), and
# `_SCAN_MAX_NODES` bounds total work — which also makes the scan safe for a
# direct caller handing over a CYCLIC python object (JSON can never produce
# one, but the hook is public).
_SCAN_MAX_DEPTH = 8
_SCAN_MAX_NODES = 10000

# How many times a whole-string parse yielding a JSON *string* may be re-probed
# on its decoded text (r8). One is enough to close DOUBLE encoding — a reply
# emitted as a top-level JSON string whose content is the verdict document,
# which the vendor's own JSON envelope produces whenever the leg quotes its
# answer instead of embedding it. A deeper nesting is a DISCLOSED bound (t44
# axis 25), not an oversight: each level is one more `json.loads` over
# attacker-controlled bytes, and no honest serializer emits one.
_MAX_REPROBE_DEPTH = 1


def _is_blocking_severity(value: object) -> bool:
    """True when `value` spells a `BLOCKING_SEVERITY_TOKENS` entry, compared
    case-insensitively after `strip()` (r6).

    Deliberately LAXER than the schema, which requires the exact token via
    `Literal[...]`. That asymmetry is the point: a leg writing `"MUST-FIX"`
    fails the `Literal` on an UNMARKED, perfectly REPAIRABLE arm, so the reply
    reaches the one repair turn — and a strict comparison here would let that
    turn launder the blocking finding away. The probe gates the RETRY, never
    validity, so being laxer than the schema can only cost a repair turn on a
    payload a reader would call blocking anyway.
    """
    if not isinstance(value, str):
        return False
    norm = value.strip().lower()
    return any(norm == tok.lower() for tok in BLOCKING_SEVERITY_TOKENS)


def _tree_carries_blocker(root: Any) -> bool:
    """Recursive, bounded TREE-SCAN over a parsed payload (r7 — the probe's
    final shape). True iff ANY dict node anywhere in the tree has a key that
    case-folds to `severity` whose value spells a `BLOCKING_SEVERITY_TOKENS`
    entry.

    This one rule SUBSUMES every container special case rounds 4-6 accumulated
    (a `findings` LIST, a single finding object, a dict-of-dicts, a top-level
    severity with no container at all) and closes the shapes r7 found still
    open — a TOP-LEVEL ARRAY, and findings nested under an arbitrary outer
    wrapper key. Structure is no longer part of the question: only "does a
    severity-typed key anywhere say something blocking".

    FALSE-POSITIVE PROFILE (the property that makes this strictly better than
    the regex it displaces, pinned by t44 axis 23): the scan reads dict KEYS.
    Blocking-severity SYNTAX quoted inside a string FIELD of a clean-parsing
    payload — a `trigger` that says `the leg drafted "severity": "must-fix"` —
    can never match, because that text is a VALUE and no key there case-folds
    to `severity`. The anchored regex, by contrast, matches those bytes
    wherever they appear, which is exactly why it is now confined to payloads
    whose parse carries no authority.

    Both bounds are disclosed misses rather than errors: past
    `_SCAN_MAX_DEPTH` the descent stops, and past `_SCAN_MAX_NODES` the scan
    gives up — in either case answering False (repairable), the pre-probe
    default, never an exception.
    """
    stack: list = [(root, 0)]
    visited = 0
    while stack:
        node, depth = stack.pop()
        visited += 1
        if visited > _SCAN_MAX_NODES:
            return False
        if depth > _SCAN_MAX_DEPTH:
            continue
        if isinstance(node, dict):
            for key, value in node.items():
                if (isinstance(key, str)
                        and key.strip().casefold() == "severity"
                        and _is_blocking_severity(value)):
                    return True
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    stack.append((item, depth + 1))
    return False


def _parse_detect_duplicates(text: str) -> tuple:
    """`(parsed, duplicate_pairs)` — `json.loads` with an `object_pairs_hook`
    that PRESERVES every member of any object carrying a repeated key, at ANY
    nesting level. `duplicate_pairs` is a list of the full `[(key, value), ...]`
    lists for exactly those objects (empty when the document has no duplicate).
    Raises whatever `json.loads` raises when the text does not parse.

    Needed because `json.loads` accepts a duplicate member and silently keeps
    the LAST one (the codex r7 trigger): a payload spelling
    `"severity":"must-fix"` and then `"severity":"Minor"` in the same object
    parses "cleanly" to the non-blocking value.

    r7 answered that by FLAGGING the duplicate and falling back to the raw-text
    regex. r8 (codex Critical + agy Critical, converged) shows why flagging is
    not enough: the regex reads the payload's SPELLING, so escaping the
    blocking half of the duplicate blinds BOTH readers at once — `json.loads`
    decodes `"must\\u002dfix"` / `"\\u0073everity"` and then DISCARDS that pair
    by last-wins, while the regex, which needs the literal bytes, sees nothing.
    Preserving the pairs puts the DECODED evidence back in front of the scan:
    json decoding is precisely what normalizes every escape spelling, so the
    trick dies at the same step that created it.
    """
    duplicate_pairs: list = []

    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            duplicate_pairs.append(list(pairs))
        return dict(pairs)

    return json.loads(text, object_pairs_hook=hook), duplicate_pairs


def _duplicates_carry_blocker(duplicate_pairs: list) -> bool:
    """True when any PRESERVED duplicate pair (see `_parse_detect_duplicates`)
    carries a blocking severity — the evidence `dict(pairs)` threw away.

    Each `(key, value)` becomes its own single-member dict and the whole
    collection is handed to `_tree_carries_blocker`, so this reuses the ONE
    scan rule rather than adding a second, subtly different reader: a discarded
    value that is itself a container (a whole `findings` list shadowed by a
    later empty one) is walked exactly like any other node, and the same
    depth/node bounds apply.
    """
    if not duplicate_pairs:
        return False
    preserved = [{key: value}
                 for pairs in duplicate_pairs
                 for key, value in pairs]
    return _tree_carries_blocker(preserved)


def nonrepairable_content(parsed: Any, _depth: int = 0) -> bool:
    """CONTENT probe — True when a reply carries a BLOCKING finding (`severity`
    in `BLOCKING_SEVERITY_TOKENS`), regardless of which validation arm actually
    failed, or whether any arm ran at all.

    The engine's duck-typed retry hook (`_common.validate_response_detail`
    resolves it as `getattr(pydantic_cls, "nonrepairable_content", None)` and
    skips when absent, so a generic `--pydantic module:Class` is unaffected).
    Also exposed as a `LegVerdict` staticmethod for discoverability. Callers
    pass ONE argument; `_depth` is the internal re-probe counter of ladder
    branch (b) below and must stay caller-invisible — the engine's hook
    contract is a single-parameter callable.

    WHY the retry gate keys on CONTENT and not on the marked arm
    (cross-family review r5, 3-family convergence; supersedes nothing —
    `NONREPAIRABLE_MARKER` still states the CONTRACT and still carries the
    prescriptive message):

      1. RETRY-TURN laundering. A payload can carry a blocking finding while
         failing for a merely REPAIRABLE reason (a shape slip). That failure
         enters the one schema-repair re-dispatch, and attempt 2 answering
         with a valid CLEAN `SAFE TO MERGE` is accepted exit 0 — the run-log
         is written on FAILURE only, so attempt 1's blocking finding is
         recorded nowhere. The laundering the marked arm closes at the
         schema's own boundary simply moves one level up, into the turn.
      2. ARM SUPPRESSION (probe P7). pydantic v2 runs `mode="after"` model
         validators ONLY when every FIELD validated. So any co-occurring field
         error — a `line` emitted as `"12"` rather than `12` — silently
         bypasses the `[NONREPAIRABLE]` SAFE-arm, and both repair loops then
         re-dispatch the exact payload the schema says must never be re-asked.

    ACCEPTED INPUT — ONE structural rule plus ONE authority ladder (r7 shape,
    r8 corrections). Rounds 4-6 each answered a new fail-open by adding ANOTHER
    container special case, so r7 deleted the container walk entirely; r8 then
    fixed three defects in the LADDER rather than adding a case back:

      - a dict OR a list -> `_tree_carries_blocker`: a bounded recursive scan
        for any dict node carrying a `severity`-typed key with a blocking
        value, at any depth, under any wrapper. This subsumes every shape the
        old walk enumerated (findings as a list / a single object / a
        dict-of-dicts / a bare top-level severity) and closes the two r7
        parsed-input holes: a TOP-LEVEL ARRAY (which matched neither the old
        dict branch nor the str branch and returned a bare False), and
        findings under an arbitrary OUTER wrapper key.
      - a str -> parse AUTHORITY decides what is read:
        (a) the WHOLE string parses to a dict or a list -> tree-scan over the
            parse, OR the scan over any PRESERVED duplicate pairs, OR the raw
            regex. All three, because none is complete alone:
              * `json.loads` resolves a repeated member by keeping the LAST
                one, so `must-fix` then `Minor` in one object reads clean
                (codex r7) — `_parse_detect_duplicates` keeps the discarded
                pairs and `_duplicates_carry_blocker` scans them DECODED, which
                is also what defeats the r8 ESCAPE trick (a duplicate whose
                blocking half is spelled `"must\\u002dfix"` or keyed
                `"\\u0073everity"` is invisible to the raw regex and thrown
                away by last-wins, but json decoding normalizes both).
              * the regex is OR'd in (r8): inside text `json.loads` accepts,
                the key-value syntax in a string VALUE is ESCAPE-rendered and
                so CANNOT match (see `_BLOCKING_SEVERITY_KEY_RE`), which makes
                every match here a real pair and recovers what the tree-scan's
                depth/node bounds give up on.
        (b) the whole string parses to a JSON *string* -> the parse is NOT
            authoritative (r8 claude Minor): a double-encoded reply, whose
            decoded text IS the verdict document, used to answer False on the
            strength of a "clean" parse. Re-probe the DECODED text once
            (`_MAX_REPROBE_DEPTH`). The outer raw text needs no regex pass: a
            valid JSON string literal escapes every inner quote, so the pattern
            is unreachable there by construction.
        (c) the whole string parses to any OTHER scalar (number / bool / null)
            -> not authoritative either, and there is nothing to descend into:
            fall through to the regex.
        (d) the whole string does not parse -> slice from the FIRST `{` to the
            LAST `}` and parse THAT; a slice is NEVER authoritative (it is a
            guess at where the object is), so its tree-scan + duplicate scan
            are OR'd with the regex over the raw string. This recovers the
            fenced/prose envelope (`_common.strip_markdown_fences` strips only
            a LEADING fence) while closing the agy r7 trigger — a fenced ARRAY
            whose brace slice yields a container-less finding dict that used to
            parse "authoritatively" and suppress the regex.
        (e) nothing parses at all -> the regex alone (a trailing comma, a
            truncated tail).
      - anything else -> False.

    REMAINING FAIL-OPEN SURFACE — disclosed, not denied, and NARROWER since r9.
    The probe reads FOUR things: a `severity`-typed dict KEY with a blocking
    value anywhere in a parsed tree, the same key in a DECODED duplicate pair
    the parse discarded, the literal `"severity": "<blocking token>"`
    key-value syntax in the raw text, and that SAME syntax in the CANONICAL
    `json.dumps(obj, ensure_ascii=False)` re-serialization of any
    successfully-parsed dict/list (r9 — corrects an overclaim this docstring
    made at r8: "the regex now runs on every string path, so a blocker deeper
    than `_SCAN_MAX_DEPTH` is still read out of the raw text" held only for a
    LITERALLY-spelled blocker. An ESCAPE-spelled `severity` key or value
    nested past `_SCAN_MAX_DEPTH`/`_SCAN_MAX_NODES` defeated the raw-text
    regex too — it needs the literal bytes an escaped spelling never contains
    — while the tree-scan separately gave up on depth/node grounds; confirmed
    live, an escaped payload nested exactly one level past `_SCAN_MAX_DEPTH`
    read `nonrepairable=False`. `json.dumps` of the DECODED tree normalizes
    every escape back to literal characters and flattens all nesting into one
    flat string, so the regex search over it is complete regardless of depth,
    node count, or escaping). Blocking content carrying NONE of the four
    keeps its repair turn: a severity spelled some other way (an integer
    level, an emoji, a localized word), a blocker stated only in prose
    (`summary`: "this must not merge"), a non-JSON serialisation (YAML,
    single-quoted pseudo-JSON) that never reaches a `json.loads` success at
    all, and a payload nested past `_MAX_REPROBE_DEPTH` encodings. The
    tree-scan's depth/node bounds are a genuine miss ONLY for a DIRECT caller
    handing over an already-parsed dict/list, where there is no source text
    to canonicalize. The claim this probe supports is narrow and exact: a
    blocker expressed in the schema's own vocabulary is refused a retry —
    NOT that a legible blocker can never be re-asked. The class-closing
    option (always write a run-log when a retry fired, even on exit 0, and
    have the leader inspect attempt 1) is an OWNER-PENDING design item, not
    shipped.
    """
    if isinstance(parsed, (dict, list)):
        return _tree_carries_blocker(parsed)
    if not isinstance(parsed, str):
        return False
    try:
        obj, duplicate_pairs = _parse_detect_duplicates(parsed)
    except Exception:
        pass
    else:
        if isinstance(obj, (dict, list)):
            return (_tree_carries_blocker(obj)
                    or _duplicates_carry_blocker(duplicate_pairs)
                    or bool(_BLOCKING_SEVERITY_KEY_RE.search(parsed))
                    # CANONICAL-REGEX BACKSTOP (r9, adopt-gate r9 — 3-family
                    # convergence). `json.dumps` of the DECODED tree is the
                    # CANONICAL re-serialization: it normalizes every escape
                    # spelling back to literal characters AND flattens all
                    # nesting into one flat string, so the anchored regex
                    # search over it is COMPLETE regardless of depth, node
                    # count, or input escaping. This makes
                    # `_SCAN_MAX_DEPTH`/`_SCAN_MAX_NODES` irrelevant to
                    # DETECTION for anything that parses — they still bound
                    # the tree-scan's own WALK, but a `severity` key or value
                    # escape-spelled AND nested past either cap (which
                    # defeats both `_tree_carries_blocker`, bounded, and the
                    # regex above, escape-blind on RAW bytes) is still caught
                    # here. Direct dict/list callers (`_tree_carries_blocker`
                    # at the top of this function) are UNCHANGED — there is
                    # no source text to canonicalize for an already-parsed
                    # object handed in directly.
                    or bool(_BLOCKING_SEVERITY_KEY_RE.search(
                        json.dumps(obj, ensure_ascii=False))))
        if isinstance(obj, str) and _depth < _MAX_REPROBE_DEPTH:
            return nonrepairable_content(obj, _depth + 1)
        return bool(_BLOCKING_SEVERITY_KEY_RE.search(parsed))
    start = parsed.find("{")
    end = parsed.rfind("}")
    if start != -1 and end > start:
        try:
            sliced, sliced_dups = _parse_detect_duplicates(parsed[start:end + 1])
        except Exception:
            pass
        else:
            if (_tree_carries_blocker(sliced)
                    or _duplicates_carry_blocker(sliced_dups)):
                return True
    return bool(_BLOCKING_SEVERITY_KEY_RE.search(parsed))


def _reject_unsafe_repo_relative_path(value: str) -> str:
    """Shared guard for `LegFinding.file` (adopted technique, 2026-08-10 —
    see module docstring). Order matters only for message clarity — each
    check is independently sufficient to reject:
      1. no backslash (this schema's paths are POSIX-only everywhere else;
         `PurePosixPath` itself treats a backslash as an ordinary filename
         character, not a separator, so it would otherwise pass through).
      2. no ASCII control character (C0 range or DEL).
      3. not absolute — POSIX (`/...`) or a Windows drive-letter form.
      4. no empty / `.` / `..` path segment (directory traversal / no-op
         segments) — `PurePosixPath` does NOT collapse `..` itself.
      5. the value must equal its own `PurePosixPath(...).as_posix()`
         normalization — catches a double slash, a trailing slash, or any
         other non-canonical spelling the segment check alone would miss.
    """
    if "\\" in value:
        raise ValueError("file must not contain a backslash (POSIX paths only)")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("file must not contain control characters")
    if value.startswith("/") or _DRIVE_LETTER_RE.match(value):
        raise ValueError("file must be a repo-relative path, not absolute")
    parts = PurePosixPath(value).parts
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("file must not contain an empty, '.', or '..' path segment")
    if value != PurePosixPath(value).as_posix():
        raise ValueError("file must equal its own normalized POSIX form")
    return value


class LegFinding(BaseModel):
    """One reviewer-reported finding. `line` is optional: a finding is not
    always anchored to a single line (a whole-file, cross-file, or doc/design
    defect)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    file: str = Field(min_length=1)             # repo-relative path the finding cites
    line: Optional[int] = Field(default=None, ge=1)  # 1-indexed; None when not line-anchored
    severity: Literal[*SEVERITY_TOKENS]         # see module docstring — triage.md's exact set
    summary: str = Field(min_length=1)          # one-sentence defect statement
    trigger: str = Field(min_length=1)          # concrete inputs/state -> wrong outcome
    context_known: bool                         # False = reviewer lacked context (UNKNOWN-CONTEXT class)

    @field_validator("file", "summary", "trigger")
    @classmethod
    def _reject_whitespace_only(cls, v: str) -> str:
        """`Field(min_length=1)` alone counts a spaces-only string as
        non-empty (its LENGTH is >=1) — this is the belt that closes it
        (final-gate fix round, converged codex+claude finding). Applied to
        the same 3 required free-text fields `Field(min_length=1)` already
        guards; `severity`/`verdict` are `Literal[...]` enums (already
        closed) and `context_known` is a bool (not applicable)."""
        if not v.strip():
            raise ValueError("must not be whitespace-only")
        return v

    @field_validator("file")
    @classmethod
    def _reject_unsafe_path(cls, v: str) -> str:
        """Runs AFTER `_reject_whitespace_only` (declaration order, same
        field) — see `_reject_unsafe_repo_relative_path` above."""
        return _reject_unsafe_repo_relative_path(v)


class LegVerdict(BaseModel):
    """One reviewer leg's structured verdict — the shape every leg (codex,
    agy, and the claude leg via its prompt's output contract +
    `validate_verdict.py`) returns instead of free prose."""

    model_config = ConfigDict(extra="forbid", strict=True)

    # Round/leg-binding fields (2026-08-10 hardening — see module docstring):
    # a verdict object carries its OWN round id / leg family / reviewed-
    # content digest, so a consumer (`validate_verdict.py`'s --expected-*
    # flags) can refuse a verdict that is well-formed but was produced for a
    # DIFFERENT round or a DIFFERENT leg (replay / leg-mixup), not just
    # structurally valid in isolation.
    review_id: str          # caller-chosen round id; see _valid_review_id
    family: Literal["claude", "google", "codex"]
    content_digest: str     # 64 lowercase-hex chars; see _valid_content_digest

    verdict: Literal[*VERDICT_TOKENS]
    # min_length=1 (final-gate fix round): rule 11 requires the leg to
    # ENUMERATE which criteria it checked — a bare "SAFE / none / faithful"
    # verdict with no enumerated checks is a failed review (triage.md), so an
    # EMPTY list is itself already a schema violation, not just an
    # underspecified one.
    criteria_checked: List[str] = Field(min_length=1)
    findings: List[LegFinding]  # empty REQUIRES verdict == "SAFE TO MERGE"; the
    # converse does NOT hold — SAFE MAY carry Minor/HARDENING-SUGGESTION
    # findings (only Critical/must-fix are incompatible with SAFE; see
    # _verdict_findings_consistency). The old one-directional comment here
    # ("empty ONLY when SAFE") read as bidirectional and helped seed the
    # verdict-inflation bias the 2026-08-11 review-skill fix closed.

    # The engine's retry gate resolves the content probe off the CLASS it was
    # handed (`getattr(pydantic_cls, "nonrepairable_content", None)`), so bind
    # the module-level function here. A `staticmethod` in the class body is
    # not annotated, so pydantic treats it as an ordinary class attribute and
    # never as a field.
    nonrepairable_content = staticmethod(nonrepairable_content)

    @field_validator("review_id")
    @classmethod
    def _valid_review_id(cls, v: str) -> str:
        if len(v) > _REVIEW_ID_MAX_LEN or not _REVIEW_ID_RE.fullmatch(v):
            raise ValueError(
                "review_id must match [A-Za-z0-9][A-Za-z0-9._-]* and be "
                f"<= {_REVIEW_ID_MAX_LEN} characters"
            )
        return v

    @field_validator("content_digest")
    @classmethod
    def _valid_content_digest(cls, v: str) -> str:
        if not _CONTENT_DIGEST_RE.fullmatch(v):
            raise ValueError("content_digest must be exactly 64 lowercase hex characters")
        return v

    @field_validator("criteria_checked")
    @classmethod
    def _reject_whitespace_only_entries(cls, v: List[str]) -> List[str]:
        """Same whitespace-only close as `LegFinding`'s free-text fields,
        applied per-entry: `min_length=1` on the LIST only guards the item
        COUNT, not each entry's own content. Duplicate-entry rejection
        (2026-08-10 hardening) runs AFTER the whitespace check, per-task
        order: two entries that both pass the whitespace gate but repeat the
        same enumerated criterion add no new coverage and would otherwise
        let a leg pad `criteria_checked` without actually checking more."""
        for entry in v:
            if not entry.strip():
                raise ValueError("criteria_checked entries must not be whitespace-only")
        if len(v) != len(set(v)):
            raise ValueError("criteria_checked must not contain duplicate entries")
        return v

    @model_validator(mode="after")
    def _verdict_findings_consistency(self) -> "LegVerdict":
        """Flow 4's INVALID-leg rule made mechanical, BIDIRECTIONAL since
        2026-08-10 (adopted technique — see module docstring):

        1. (original direction, unchanged) "A non-SAFE verdict with NO
           extractable finding is an INVALID leg ... handled identically to
           a terminally-missing leg (rule 13): never released, never counted
           SAFE." Raising here (rather than merely documenting the rule)
           means an invalid object can never reach the leader's
           consolidation step in the first place — on the codex path
           (post-hoc `validate_response` after the vendor's own strict
           `--output-schema` check) and on the agy path (local validation
           over `structured_output`, and again over the raw `response`
           fallback) alike, since both wrappers call `model_validate_json`
           regardless of which vendor-side schema enforcement already ran.
        2. (NEW, 2026-08-10) The opposite direction: `SAFE TO MERGE` must
           NOT carry a `Critical` or `must-fix` finding — a leg cannot
           simultaneously report a blocking defect and declare the round
           safe to merge. `Minor` and `HARDENING-SUGGESTION` findings MAY
           still accompany `SAFE TO MERGE` (both are non-blocking by
           `triage.md`'s own severity ladder) — this is a DELIBERATE
           difference from the codex-host reference schema, which has no
           `HARDENING-SUGGESTION` severity at all and folds every finding
           into a binary SAFE/NOT-SAFE blocking test.

        Each direction raises its own distinct message so a caller does not
        have to guess which rule fired. Direction 2's message additionally
        leads with `NONREPAIRABLE_MARKER` (r1-claude-1, 2026-08-11): direction
        1 is a legitimate SHAPE slip a repair turn may fix, but direction 2 is
        a CONTENT contradiction whose cheapest automated "fix" is severity
        laundering, so the engine must never re-ask for it.
        """
        if not self.findings and self.verdict != "SAFE TO MERGE":
            raise ValueError(
                "findings must be non-empty when verdict != 'SAFE TO MERGE' "
                "(Flow 4's INVALID-leg rule: a non-SAFE verdict needs at "
                "least one extractable finding)"
            )
        if self.verdict == "SAFE TO MERGE":
            blocking = [f for f in self.findings
                        if f.severity in BLOCKING_SEVERITY_TOKENS]
            if blocking:
                # NON-REPAIRABLE (r1-claude-1, 2026-08-11). This arm's message
                # used to be replayed verbatim into the engine's one-shot
                # schema-repair re-dispatch, and the CHEAPEST way for a leg to
                # satisfy that repair is to DOWNGRADE its own blocking finding
                # to Minor and keep SAFE — the leader only ever sees the
                # repaired object, so a blocking finding gets laundered into a
                # non-blocking one. The marker makes the engine fail loud
                # (exit 66) instead; the prescription below is for whoever
                # reads the error afterwards (a human, or the leader re-asking
                # the leg explicitly), so the laundering is not simply
                # re-invented one layer up.
                raise ValueError(
                    f"{NONREPAIRABLE_MARKER} "
                    "SAFE TO MERGE must not carry a Critical or must-fix "
                    "finding (Minor and HARDENING-SUGGESTION MAY still "
                    "accompany SAFE TO MERGE). Resolve by RAISING the verdict "
                    "to MERGE WITH FIXES or DO NOT MERGE — NEVER by "
                    "downgrading a finding's severity."
                )
        return self
