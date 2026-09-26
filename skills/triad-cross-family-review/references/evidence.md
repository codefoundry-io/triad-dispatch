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
| agy hook load check — measurements | asking why the hook check attributes by conversation id, or why step counts need not match hook rows |
| Escaped transport on the claude Agent route | a claude-family reply arrives entity-escaped, or `verdict_v2` prints the unescape NOTICE |
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

For the agy leg this is a SECONDARY signal, behind its two mechanical evidence
checks — the read-audit gate and the hook load check
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

Consequences now stated as rules: the mandatory containment block, the
read-audit gate, and cite verification before the residual table. The
"advisory verdict weight" this study originally justified was RETIRED in
0.37.0 — `acceptance` is data and every enabled entry counts (SKILL rule 1),
because discounting a leg's verdict never addressed the mechanism. The
EVIDENCE bar did: an ungated agy answer is UNVERIFIED and counts as invalid,
and an unverified cite never reaches the table.

## agy hook load check — measurements

The hook load check (`lib/agy_hook.py check`) rests on these measurements:

- **`--agent <unknown>` fails OPEN silently** (measured 2026-09-16): a bogus
  agent name yields a fully write-capable default agent and the `init` event
  echoes the requested name, so the stream cannot tell. The round must
  therefore PROVE the PreToolUse hook loaded for every agy run.
- **A broken hook denies every call, reads included** (measured 2026-09-16,
  arm C): the leg produces no answer at all, so the handler stays small.
- **Step count and hook rows need not match** (measured 2026-09-17): 4 tool
  steps against 3 hook invocations — a call the vendor rejects at argument
  validation is a tool step that never reaches the hook. Equality is not
  required; attribution is.
- **The conversation id is shared by the stream and the hook** (measured
  2026-09-26): the stream's `init` and every `step_update` carry the id the
  PreToolUse row carries. The wrapper records each run's ids on its census
  row, which is what lets the check attribute hook rows to the run that made
  them and NAME an unhooked run.

## Escaped transport on the claude Agent route (MEASURED, gate-1 r3 2026-09-21)

The Agent completion notification ENTITY-ESCAPES the reply. Measured in host-A
gate-1 round r3: BOTH claude-family entries (`claude` and the advisory
`x-claude-high`) came back with their bodies escaped, and both were admitted
only on the `html.unescape` pass. This is the normal shape of that transport,
not an anomaly — a leg that returns a literal marker and a leg that returns an
escaped one are both correct, and the leader NEVER de-escapes by hand (a
leader-edited reply is inadmissible).

Two consequences the admission rule is built on:

- **`html.unescape` is the whole test, so every spelling it knows is
  covered** — named (`&lt;END-VERDICT&gt;`) and NUMERIC
  (`&#60;END-VERDICT&#62;`) alike. The earlier code matched one escaper
  spelling only, so a numeric-entity marker was not recognised at all and a
  valid reply died at exit 3.
- **Both validators must derive the SAME object from the same bytes.** The
  legacy `validate_verdict.py` finds only the LITERAL marker on its pass 1 and
  unescapes the WHOLE text on its pass 2; when `verdict_v2` recognised an
  escaped marker inside its RAW pass, a transport that escaped angle brackets
  but not quotes left `&lt;` / `&gt;` entities intact inside the admitted
  strings while the legacy validator on the same reply produced clean ones.
  The one rule now in force (marker literal → raw-first; marker only
  unescapes-to-literal → whole-text unescape + NOTICE) makes the two agree by
  construction (gate-1 r3 row r3-8, cross-checked on the r3 bytes).

## Measured timeouts

- A ~65K-char inline packet at codex `--reasoning max` exhausted 900s with NO
  verdict and completed at ~950-1050s → budget `--timeout 1500` for a LARGE
  packet at max.
- A FOCUSED sub-500-line packet at max completes in a few hundred seconds.
- A workspace-sandboxed leg told to SELF-ASSEMBLE a large packet timed out around
  13 minutes; the same content, pre-assembled, finished in a few minutes.
- An agy Pro-high / high entry hit a 600 s wrapper timeout on a 59 KB gated
  diff + 26 KB brief (89 tool steps, the vendor turn still in progress); the
  same-basis retry completed in 434 s. A's four-leg example therefore sets
  the Google entries' `timeout_s` to 900. `timeout_s` is per attempt: the agy
  capacity ladder (2 retries, 15 s / 45 s backoff) gives every attempt the
  full `--timeout`.

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
