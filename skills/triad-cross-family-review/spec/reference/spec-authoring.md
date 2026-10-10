# How specs are written in this lab

Adapted from the owner's Spec Rebuild Lab blueprint (2026-09-19) to a documentation-and-contracts repository with no
application code: no UI, no LikeC4, no generated docs (owner Q-V). The point is that a fact is decided once, written
once, referenced everywhere, and tested by cases that accumulate.

## 1. The three things a human approves

1. **Who talks to whom** — the surfaces: file names, subcommands, options, prompt files, receipt fields, tokens.
2. **What result is correct** — behavioral cases: input, expected result, the rule it proves.
3. **What may not change without a revision** — the frozen surfaces: contracts, prompt files, the rules' normative text.

Everything else (how a host implements a surface, its internal test tree, its install layer) is the host maintainer's.

## 2. The authoring conversation (one decision at a time)

When a rule or surface is added or changed, the author answers these questions before writing; the answers go where the
table says. A question the owner already answered is not asked again (`decisions/owner-register.md`).

| Question | Where the answer lives |
|---|---|
| What does a maintainer or a reviewer observably get? | `review-rules.md` / `process.md` normative sentence with an anchor |
| Which existing surface is reused (file, option, token, prompt clause)? | a reference to `contracts/` or `prompts/`, never a copy |
| Which host files may change for it, and who owns them? | `units.json` row |
| Does it call a vendor, read outside the review tree, use a clock, or network? | the containment section of `review-rules.md` |
| One normal example and one failure or boundary example? | `cases/cases.json` entries (before any host code) |
| What is still ambiguous? | an owner question, asked in advance, recorded verbatim |

## 3. Writing rules

- One normative location per rule, with an anchor. Other documents point; diagrams navigate; tables summarise with a link.
- Types live in schemas (`contracts/*.schema.json`), not in prose; prose describes, the schema decides.
- Owner decisions are quoted verbatim; a leader's option label is marked as such.
- A "must survive" list cites the host file and symbol that ships the guard today.
- No per-leg special rules, no ceremony fields: a leg is an entry with recommended defaults (owner Q-M).
- A behaviour that holds on one host only is written as "On A: …" or "On B: …", never left implicit; each host must be
  rebuildable from the specification alone, so a host-specific mechanism names its files, tools and switches
  (owner, [D-REVIEW-LEGS-20261003](../decisions/owner-register.md#D-REVIEW-LEGS-20261003)).
- Prompts are files, one clause per rule, editable by the owner without touching code; hosts vendor them at the revision
  they adopt (owner Q-U; vendoring rule: `README.md` § How a host uses a revision). A host skill body carries invocation
  syntax and pointers, not the clauses.

### PRD and Spec bundles

<a id="R-PRD-SPEC"></a>
Implementation PRDs state purpose, scope and acceptance. Specs connect those
requirements to the existing rule anchors, typed contracts, behavioral cases and
owning units. Keep the prose at its source; record only references in a bundle
under `authoring/maps/`, using [the authoring schema](../authoring/implementation-map.schema.json).
The [authoring guide](../authoring/README.md) defines the editing and checking entry points.
Run the offline check before handing off a changed bundle. Structural validity
does not establish semantic completeness, owner approval or host conformance.

## 4. Cases accumulate; they are never weakened

```
defect or ambiguity found (any host, any round)
→ reproduce it against the reviewed bytes
→ write the case FIRST: id, rule anchor, input, expected — in cases/cases.json
→ the owning host fixes and names its test after the case id
→ the other host runs the same case at its next conformance run
→ the case stays; the rule text gains the anchor if it lacked one
```

A case that fails is a defect in the host or in the spec, never a reason to change the expected result without a
recorded decision. An unrun case is listed NOT RUN, never green. A refuted finding is recorded in the round ledger, not as a
case. A change whose effect cannot be exercised where it is written is applied anyway and ships with a verification
manifest (`contracts/<file>.verify.toml`) that whoever has the capability runs. For a manifest that verifies a policy
file (it carries `policy_sha256`) the convention is `review-rules.md#R-GOOGLE`: the result is written once, in
`decisions/owner-register.md`, never re-narrated per host. A service or conformance manifest names its result channel in
its own `result_channel` field.

## 5. Revisions

A revision (`rev-N` tag) is the freeze: after it, changing a contract, a prompt file or a normative sentence is a new
revision with a `CHANGELOG.md` entry naming the anchors, cases and units it touches. The owner tags after the other
leader has read the change (owner Q-T).
Hosts adopt explicitly (`SPEC_REVISION`) and may lag; the drift report lists which revision each conforms to and which
case ids are red.

### Current-source and cross-host coordination

<a id="R-AUTHORING-SYNC"></a>
At session start, before changing a shared design or contract, and before final review, fetch this repository's remote
`main`, record its actual commit, and read new changes. A remembered commit or local cache is not evidence of the latest
specification. If remote verification is unavailable, disclose that limit and defer affected design decisions.

Before implementing any change to common design, contracts, prompts or behavior, regardless of whether it comes from
web research, a CLI update, review or implementation, record it here and request the other host leader's review of the
same commit. Record: evidence and source/version → current behavior → proposed behavior → effects on both hosts →
features to preserve → verification method. Resolve surviving disagreements and required owner decisions before
implementation; neither host silently establishes a different common design. Follow R-STOP for a confirmed design defect.

Audit current functionality before optimizing it. Verify each guard's necessity or replacement against source, tests,
design records and relevant official CLI evidence; an unknown historical reason remains unknown. Any discovered loss or
omission of existing functionality, however small, receives independent Claude, Google and fresh Codex diagnosis and is
shared with the other leader. The owning leader verifies findings and changes only its own host.

When the owner designates a lead host, it implements and verifies first; the other host's implementation or review
reply is not a prerequisite for work under settled contracts. At each change, inspect the corresponding other-host
source and update the handoff with its commit, file, line, actual difference and necessary follow-up. Keep the other
host unchanged until the owner-designated handoff point. This sequencing does not authorize a silent contract change
or override unresolved owner decisions, review gates, adoption, merge or publication boundaries.

Task-specific exception: for the 2026-10-02 review-strategy amendment, the owner explicitly excludes A implementation
inspection before it adopts the spec. Follow [the recorded direction](../decisions/owner-register.md#D-REVIEW-STRATEGY-20261002),
keep prior A source pointers historical, and mark current A behavior unverified. This does not prevent review of the shared
specification commit or change the later host-adoption and publication boundaries.

This section is the one normative copy of this authoring protocol. Shared `AGENTS.md`, `CLAUDE.md` and `GEMINI.md` carry the same
pointer; host instructions also point here. Reading latest authoring `main` does not change a host's adopted revision,
vendored payload bytes or digest manifest; adoption and publication still follow `README.md` § How a host uses a revision.

<a id="R-DECISION-ORDER"></a>
When implementing a common item finds a behaviour, a gap or a defect, decide it in this order: (1) what this
specification already decides; (2) otherwise the other host's code — when it settles the behaviour, this specification
gains the rule and the other host is not changed; (3) otherwise a fact or limit that neither host closes is recorded here
(the rule it limits, a case, a dev-log row) without an owner question; (4) the owner is asked only for a design choice
with a trade-off that neither the specification nor either host settles. An absolute law (R-AUTH,
[D-AUTH-ABSOLUTE-20261004](../decisions/owner-register.md#D-AUTH-ABSOLUTE-20261004)) is never a design choice and never a
limit both hosts lack: a gap against it is a defect both hosts fix. Whatever the other host must learn — a gap that
made a leader read the other host's code, a defect both hosts share, a defect of the other host — is written into this
specification (rule text, case, or an `authoring/shared-dev-log.md` row naming the host that acts) in the same turn it is
found, never only into a host's private record. Neither a plan nor this specification is assumed complete. Owner
direction: [D-DECISION-ORDER-20261004](../decisions/owner-register.md#D-DECISION-ORDER-20261004),
[D-SPEC-GAPS-20261003](../decisions/owner-register.md#D-SPEC-GAPS-20261003).

## 6. What code does and what AI does

- Code: `tools/check_authoring.py` validates registered PRD/Spec bundles against
  the authoring schema and resolves their local files, explicit anchors, case IDs
  and unit IDs. It does not inspect unregistered narrative documents or prove
  requirement completeness. Host payload digest/adoption checks remain host-owned.
- AI: detecting ambiguity while authoring, reviewing a rule's meaning, judging a finding semantically. AI never decides a case's pass/fail; deterministic schema and integrity validation is code.

## 7. Not in this lab (rev-0)

LikeC4 or any architecture GUI; generated documentation; cross-host release gates; synchronized releases; a contract
"controller" role. Any of these needs an owner decision and a recorded reason.
