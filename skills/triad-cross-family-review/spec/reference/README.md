# reference/ — common guidance, written once

Every rule has exactly ONE normative location. Everything else — host `CLAUDE.md` / `AGENTS.md`, skill bodies,
diagrams, tables in plans — points at it. When two places disagree, the location named below wins and the other is a
bug to fix in the same change.

`AGENTS.md`, `CLAUDE.md` and `GEMINI.md` are identical link maps. Keep rules in
the sources below and update the three maps together when a destination changes.

## One source per fact

| Fact | Source of truth (in this repository unless noted) | Derived forms (conform to the source — by hand or by generation; a normative change happens only in the source) |
|---|---|---|
| Result wire: `LegVerdict` fields, enums, finding fields | `contracts/leg-verdict.schema.json` (v2 candidate; host adoption is separate) | host adapters; shape pins inside `prompts/` |
| Review phase values | `contracts/review-kind.schema.json` | invocation defaulting and shared purpose selection under R-PROMPT; host adoption pending |
| Leg roster: fields, allowed values, recommended defaults | fields and allowed values: `contracts/review-legs.schema.json`; recommended defaults: `reference/review-rules.md#R-ROSTER`; illustrative shape in `contracts/review-legs.example.json`; runnable defaults in each host's data file | host loaders; SKILL text points here |
| Exit tokens and receipt vocabulary | `contracts/exit-tokens.json`; `contracts/receipt-fields.json` | host `_common.py` tables and adapters, checked against these files |
| Known vendor failure sentences: CLI, sentence, match phrase, token | `contracts/vendor-failure-lines.json` (rule `R-CLASSIFY`) | host classifier pattern lists, checked against this file |
| Review rules: agreement, correction re-review, phase/context, roster semantics, Google leg, leader triage, convergence, containment, CLI compatibility, no-cost | `reference/review-rules.md` | SKILL.md rule text (pointers + host invocation syntax), prompt clauses |
| Process flow and failure diagnosis | `reference/process.md` (one diagram) | SKILL flow sections |
| Latest-source verification and cross-host change coordination | `reference/spec-authoring.md#R-AUTHORING-SYNC` | shared agent entry files and host instructions point here |
| The order of deciding a gap found while implementing; what the other host must learn goes into the specification | `reference/spec-authoring.md#R-DECISION-ORDER` | host instructions and the dev-log's cross-check rule point here |
| PRD/Spec authoring structure and requirement links | `authoring/implementation-map.schema.json`; current bundles in `authoring/maps/` | [Authoring guide and checks](../authoring/README.md); document prose remains at the linked anchors |
| Prompt text | `prompts/*.md` | vendored copies in host skills (vendoring rule: `README.md` § How a host uses a revision) |
| Behavioral cases (inputs, expected results, rule anchor) | `cases/cases.json` | host tests carrying the case ids in their names |
| Which host file implements which surface; which tests carry which cases | `units.json` | none |
| Owner decisions | `decisions/owner-register.md` | quotes in plans and ledgers |
| Revision agreement and signatures | `decisions/rev-N-agreement.md` (rev-1: `decisions/rev-1-agreement.md`) | the relayed round documents point here |
| Which revision a host conforms to | On A: the host repository's `SPEC_REVISION` file; On B: `source_commit` in the manifest files listed there (`README.md` § How a host uses a revision) | drift reports |
| Gemini read-only host profiles | no-web: `contracts/gemini-readonly.toml` (A), `contracts/gemini-readonly-b.toml` (B); web (true R-REVIEW-WEB condition): `contracts/gemini-readonly-web.toml` (A), `contracts/gemini-readonly-web-b.toml` (B); selected under R-CONTAIN / D-B1 / R-REVIEW-WEB | exact selected payload and adjacent digest at the host's adopted revision |
| Defects and drift found while a host implements the common items (which host acts, `file:line @ commit`, status) | `authoring/shared-dev-log.md` (`R-DEV-LOG`) | host checklists and ledgers point at rows by id (`DL-n`); the case a row minted lives in `cases/cases.json` |
| Measured evidence behind a rule or case change (a spike record: observation with `path:line`, cause chain, the fix on the owning host, the live before/after run, what the other host should touch) | `spikes/<UTC-date>-<slug>.md` | quotes in host plans and ledgers; the case in `cases/cases.json` it produced |

## Anchors

Normative sentences in `review-rules.md` and `process.md` carry stable anchors (`<a id="R-xx"></a>`). Cases and units
reference anchors, never line numbers. Renaming an anchor is a revision.

## Files

- `spec-authoring.md` — how a spec is written and changed in this lab (the method the owner asked to try).
- `review-rules.md` — the rules both hosts implement.
- `process.md` — the shared flow and the failure-diagnosis rules.

## Review strategy implementation handoff

[Claude-host guide](../decisions/claude-review-strategy-handoff.md) connects the normative anchors, acceptance cases and verified B evidence. A conformance and host adoption remain separately recorded.
