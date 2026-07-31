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
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Single source of truth for the two token sets — a test or a doc that wants
# "every severity/verdict token" iterates these rather than hardcoding a
# second list (same principle t41-review-gate-jq.sh applies to
# `_common._AGY_DIGEST_VALUE_CAP`: read the constant, never retype it).
VERDICT_TOKENS = ("SAFE TO MERGE", "MERGE WITH FIXES", "DO NOT MERGE")
SEVERITY_TOKENS = ("Critical", "must-fix", "Minor", "HARDENING-SUGGESTION")


class LegFinding(BaseModel):
    """One reviewer-reported finding. `line` is optional: a finding is not
    always anchored to a single line (a whole-file, cross-file, or doc/design
    defect)."""

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


class LegVerdict(BaseModel):
    """One reviewer leg's structured verdict — the shape every leg (codex,
    agy, and the claude leg via its prompt's output contract +
    `validate_verdict.py`) returns instead of free prose."""

    verdict: Literal[*VERDICT_TOKENS]
    # min_length=1 (final-gate fix round): rule 11 requires the leg to
    # ENUMERATE which criteria it checked — a bare "SAFE / none / faithful"
    # verdict with no enumerated checks is a failed review (triage.md), so an
    # EMPTY list is itself already a schema violation, not just an
    # underspecified one.
    criteria_checked: List[str] = Field(min_length=1)
    findings: List[LegFinding]                  # empty ONLY when verdict == "SAFE TO MERGE"

    @field_validator("criteria_checked")
    @classmethod
    def _reject_whitespace_only_entries(cls, v: List[str]) -> List[str]:
        """Same whitespace-only close as `LegFinding`'s free-text fields,
        applied per-entry: `min_length=1` on the LIST only guards the item
        COUNT, not each entry's own content."""
        for entry in v:
            if not entry.strip():
                raise ValueError("criteria_checked entries must not be whitespace-only")
        return v

    @model_validator(mode="after")
    def _empty_findings_only_with_safe(self) -> "LegVerdict":
        """Flow 4's INVALID-leg rule made mechanical: "A non-SAFE verdict
        with NO extractable finding is an INVALID leg ... It is handled
        identically to a terminally-missing leg (rule 13): never released,
        never counted SAFE." Raising here (rather than merely documenting the
        rule) means an invalid object can never reach the leader's
        consolidation step in the first place — on the codex path
        (post-hoc `validate_response` after the vendor's own strict
        `--output-schema` check) and on the agy path (local validation over
        `structured_output`, and again over the raw `response` fallback)
        alike, since both wrappers call `model_validate_json` regardless of
        which vendor-side schema enforcement already ran."""
        if not self.findings and self.verdict != "SAFE TO MERGE":
            raise ValueError(
                "findings must be non-empty when verdict != 'SAFE TO MERGE' "
                "(Flow 4's INVALID-leg rule: a non-SAFE verdict needs at "
                "least one extractable finding)"
            )
        return self
