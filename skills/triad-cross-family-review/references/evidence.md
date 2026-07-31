# Cross-family review — measurements and origin evidence

Loaded on demand from `triad-cross-family-review/SKILL.md`. Read this when a
rule's threshold looks arbitrary, when budgeting a timeout, or when someone
proposes re-opening a policy the measurements settled. Nothing here branches at
runtime; the rules that consume it live in the SKILL body.

## Contents

| Section | Open it when |
|---|---|
| Latency as a rubber-stamp signal | judging whether a fast SAFE was a real review |
| agy leg depth study | someone proposes making the agy verdict gating again |
| Measured timeouts | budgeting `--timeout` for a packet and tier |
| Known-harmless codex artifact | codex reports it cannot persist its scratch file |
| Vendor-leg no-exec origin | someone proposes letting a leg run the code |
| Budget note | weighing the cost of a deep tier |
| Max-thinking directive — provenance | asking what evidence backs the ultrathink directive |
| Why the cross-family gate exists | explaining the whole practice to someone new |

## Latency as a rubber-stamp signal

Measured on a 134KB packet across 8 runs: both 20s-class runs found zero
mid-packet real defects, while every run of 79s or more found at least one.
Threshold in force: under 60s on a packet of 100KB or more reads as a shallow
pass → re-dispatch that leg with the adversarial framing. The older sub-30s guide
was too lenient.

For the agy leg this is a SECONDARY signal, behind the mechanical read-audit gate
(`references/leg-contracts.md`). For codex, which has no read-audit
instrumentation, latency stays the primary rubber-stamp heuristic.

Criteria enumeration is required of every leg but is NOT evidence of depth: agy
echoed "Criteria checked: 1-5" in 8 of 8 runs regardless of what it verified.

## agy leg depth study (basis for the ADVISORY policy)

A planted-defect replay of a real merge packet — 8 production-shape runs plus 2
stream-json traced runs — measured:

- real-defect recall 21% (3 of 14);
- identical-run verdict flip (2/3 ↔ 1/3), unstable severity;
- file:line cites fabricated in 4 of 5 traced-or-scored runs;
- "Criteria checked" echoed in 8 of 8 runs regardless of depth.

Traced mechanism: the agy agent HARNESS wanders outside the packet dir before
reading it — other projects' review dirs and its own conversation logs (a 126KB
grep of its prior verdicts into context), which re-ingested its own round-1
finding as a recurring false Must-fix in 6 of 8 runs; plus 5x whole-file re-reads
diluting attention.

Ruled OUT as causes: the compact output contract (an uncapped run stayed 2.3KB),
prompt depth directives (depth-directive arms scored 0/4 versus 1/4), and the
model tier — the Pro/High tier nailed the exact defect plus its fix twice when
the context stayed clean.

Consequences now stated as rules: agy verdict = ADVISORY (rule 1), the mandatory
containment block, the read-audit gate, and cite verification before the residual
table.

## Measured timeouts

- A ~65K-char inline packet at codex `--reasoning max` exhausted 900s with NO
  verdict and completed at ~950-1050s → budget `--timeout 1500` for a LARGE
  packet at max.
- A FOCUSED sub-500-line packet at max completes in a few hundred seconds.
- A workspace-sandboxed leg told to SELF-ASSEMBLE a large packet timed out around
  13 minutes; the same content, pre-assembled, finished in a few minutes.

Prefer shrinking the packet over raising the timeout.

## Known-harmless codex artifact

Under `--sandbox read-only` codex may REPORT that it lacks permission to persist
its own session/scratch file. Observed in real review use, not reproducible on
demand; the verdict still returned complete. Treat THAT specific
self-persistence complaint as expected — do not widen the sandbox for it, and do
not normalize other permission failures under this note.

## Vendor-leg no-exec origin

A codex leg that live-ran the code under review hung on a real vendor API call
and — under its read-only sandbox — could not reap the hung child, burning the
whole timeout with no verdict. The same review finished quickly once the prompt
carried the no-exec directive. That is the origin of Hard rule 7, and of the
pairing rule: the no-exec directive AND a generous timeout, not either alone.

A live-run finding can still be valid — it surfaces real robustness gaps — so
capture the gap, then re-dispatch read-only.

## Budget note

The Gemini thinking tier is API-billed rather than subscription-covered; the
codex/claude deep tiers draw down their subscription budgets faster. Acceptable
for the high-stakes pre-merge gate — keep cheap single-shot dispatches on the
defaults per the no-model-pin rule.

## Max-thinking directive — provenance

The unconditional "think as hard as you can / ultrathink" directive on the claude
leg (rule 10) is a STANDING LAB OBSERVATION, not a measured threshold: legs
dispatched without it were repeatedly seen to under-reason and return bare SAFE
verdicts, and adding it recovered depth. It is the one lever in this skill with
no number behind it — treat it as cheap insurance rather than as evidence, and
measure it if it is ever the thing in dispute.

## Why the cross-family gate exists

The lab's standing cross-family review rule exists because a same-family review
chain shares the leader's blind spot. In the originating case the leader declared
an appium wrap "a no-op", seeded that into the implementer prompt, and the
all-claude review chain passed it — while codex and gemini independently caught a
real device-shell injection hole.

It re-validated later: a strict per-task spec+quality review on every task still
missed several Critical and Important cross-cutting issues that the cross-family
3-way caught. Per-task same-family review is necessary but not sufficient; the
final cross-family pass is the gate.
