---
name: triad-cross-family-review
description: Runs the FINAL pre-merge (or review-worthy / security-or-correctness-critical) cross-family review mandated by the lab's cross-family review rule — dispatches INDEPENDENT cross-family reviewers (a claude fresh-eye sub-agent via Agent + codex via triad-codex-dispatch + the Google-family CLI selected at runtime, agy via triad-antigravity-dispatch or gemini via triad-gemini-dispatch), frames the suspect/omitted/simplified decisions as QUESTIONS, consolidates their verdicts (SAFE TO MERGE / MERGE WITH FIXES / DO NOT MERGE), then runs a fix→re-confirm loop until the gating legs are unanimously SAFE. Trigger when about to merge review-worthy work, ESPECIALLY when the leader chose to OMIT or SIMPLIFY something from a vetted source, or after a subagent-driven implementation before integration.
version: 0.24.2
# changelog:
#   0.24.2 (2026-08-01): `references/leg-contracts.md` § codex leg — the
#     inline-packet caution quoted the sibling dispatch skills' OLD bare
#     `PROMPT` heredoc terminator, which those skills replaced with
#     per-CLI `TRIAD_<CLI>_PROMPT_EOF` forms (codex 0.9.1 / gemini 0.6.1 /
#     claude 0.4.1, same defect class as antigravity 0.13.0/0.13.1). Text
#     resynced, and corrected on a point the round-1 review refuted: THIS leg
#     uses neither that heredoc nor `--prompt-file` — it inlines the packet
#     through `$(cat -- "$review_body")` per its own bullet heading, which is
#     collision-free because there is no heredoc to terminate early.
#     Doc-only; no gate block, no jq, no contract semantics touched.
#   0.24.1 (2026-08-01): final-gate fix round on the 0.24.0 verdict-schema
#     wiring (pre-merge cross-family gate: MERGE WITH FIXES, codex+claude
#     converged, agy's must-fix probe-refuted). agy leg dispatch step
#     (`references/leg-contracts.md` § agy leg) gains a leader-side
#     `rm -f "$PACKET_DIR/agy-read-audit.json"` immediately before EACH
#     dispatch — the wrapper's own pre-clear
#     (`_common.preclear_read_audit_file`, called at `antigravity_wrapper.py`
#     main()'s call START) closes a stale-file-survives-a-swallowed-write-
#     failure path INSIDE the wrapper, but not a MISBOUND env (dispatch names
#     the wrong path, or the var was never exported) — this leader-side line
#     closes that remaining case. The byte-frozen agy read-audit jq gate
#     3-LINE LIFT TARGET (t41/f9) is untouched. No other SKILL.md/reference
#     content changed in this round; the schema tightening (empty/whitespace-
#     only fields, line<1) and the validator hardening (dist-then-dev
#     resolution order, distinct schema-load-failure class, UTF-8 decode
#     handling) live entirely in `verdict_schema.py` / `lib/validate_verdict.py`,
#     which this SKILL already documents by reference rather than by value.
#     Re-confirm round 2 (claude must-fix G1, same-version fix — the
#     changelog text above already reflects the corrected line): the FIRST
#     draft of this line read the bare `$AGY_READ_AUDIT_FILE`, a GATE-local
#     name first assigned inside the read-audit gate block (below) — unset at
#     DISPATCH time, so it silently expanded to `rm -f ""` (a no-op; the
#     misbound-env case stayed open). Fixed to mirror the gate's OWN binding
#     expression instead of a mismatched variable name.
#     Re-confirm round 3 (claude Minor H5, same-version fix — the changelog
#     text above already reflects the final corrected line): the round-2 fix
#     used a `${TRIAD_READ_AUDIT_FILE:-$PACKET_DIR/agy-read-audit.json}`
#     fallback expression, which risked clearing an unrelated LEFTOVER
#     `TRIAD_READ_AUDIT_FILE` some other ambient shell context left set
#     instead of the packet-relative path THIS dispatch actually binds.
#     Simplified to the plain literal `rm -f "$PACKET_DIR/agy-read-audit.json"`
#     — byte-matching the SAME path the bullet's own dispatch sets
#     unconditionally, removing the ambiguity entirely.
#     Re-confirm round 5 (claude must-fix, same-version fix): the round-3
#     simplification left the GATE's own read binding (inside the gate block,
#     ABOVE the frozen 3-line jq lift) on the old fallback expression, so
#     pre-clear and gate could target DIFFERENT files under an ambient
#     exported TRIAD_READ_AUDIT_FILE. All THREE sites (dispatch binding,
#     leader pre-clear, gate read binding) now carry the byte-identical
#     plain literal `$PACKET_DIR/agy-read-audit.json` — the shared literal
#     itself is the anti-drift property.
#   0.24.0 (2026-08-01): all three legs share ONE pydantic verdict schema
#     (`bin/verdict_schema.py` — `LegVerdict`/`LegFinding`,
#     plan `2026-07-31-agy-post-migration-followups` item 4), so the leader
#     consolidates structured objects instead of re-shaping three legs' free
#     prose by hand. codex leg: `--pydantic verdict_schema:LegVerdict` added
#     to the documented invocation (codex-strict `--output-schema`). agy leg:
#     same flag (native `--json-schema`); the structured output rides the
#     stream's terminal `result` event, so the `truncated-answer` fold guard
#     becomes a non-case on this path (kept for the non-schema fallback).
#     claude leg: no wrapper, so its dispatch prompt now carries the SAME
#     JSON shape as the output contract, validated by the leader with the new
#     deterministic (no-AI) `lib/validate_verdict.py` — a reply that fails
#     validation is the EXISTING INVALID-leg handling (one re-ask, then
#     INVALID), no new chain. `references/triage.md` gained a
#     "Consolidating validated LegVerdict objects (jq)" section: the exact jq
#     commands that map `findings[]` into residual-table rows mechanically,
#     with a stated fallback — a leg dispatched WITHOUT the schema (older
#     invocation) still consolidates the old prose way, and the two paths can
#     coexist within one round. The "empty findings only with SAFE" rule is a
#     `LegVerdict` model-level pydantic validator, making Flow 4's INVALID-leg
#     rule (a non-SAFE verdict with no extractable finding) mechanical rather
#     than a leader-remembered convention. The byte-frozen agy read-audit jq
#     gate block (t41/f9's lift target) is untouched.
#   0.23.0 (2026-08-01): body split into one-level `references/`, after an
#     overlap/dead-content audit, plus a tone and provenance de-scope pass (plan
#     `docs/superpowers/plans/2026-07-31-agy-post-migration-followups.md` item
#     3). Then a 6-leg skill-prompt-review round (round 2, post-split) drove a
#     PART A fix list into this same unreleased version: the degraded-mode
#     predicate corrected to "fewer than three families RETURN a consolidated
#     verdict", a `--search` sensitivity precondition at dispatch, the
#     failure-mode index moved to its own reference, and the remaining
#     multi-home restatements collapsed to pointers. The
#     body now carries the frontmatter, when-to-use, a Contents map, the 14 hard
#     rules each stated ONCE, and the Flow. Per-leg
#     dispatch contracts (including the agy read-audit gate and its jq block,
#     moved VERBATIM), the packet lifecycle, the triage/residual machinery, and
#     the measurement evidence moved to `references/`. Historical changelog
#     entries older than the three kept here were dropped (git history is the
#     archive), as were provenance dates and version pins inside rule text.
#     No contract changed meaning: the gate expression, the
#     ABSENT/INCONCLUSIVE/VOID semantics, the three block-release paths, the
#     degraded-mode rules, and every exit code are the v0.22.0 ones. Consumers
#     that lift the gate block by grep (`tests/unit/wrappers/t41-review-gate-jq.sh`,
#     `tests/integration/wrappers/flow/f9-agy-flow.sh`) now read it from
#     `references/leg-contracts.md`.
#   0.22.0 (2026-07-31): the agy read-audit gate became FILE-based instead of
#     stderr-based — the wrapper writes the `{meta, digest}` JSON to a path the
#     dispatch names up front via `TRIAD_READ_AUDIT_FILE`, on EVERY completed
#     call, and the gate reads that file with `jq` re-rooted at `.digest`,
#     branching on jq's own exit code (0=covered, 1=coverage-miss, >=2=jq could
#     not produce a usable answer=INCONCLUSIVE). That retires the transport-level
#     late-append / first-match-forgery / anchored-extraction class of findings.
#     The owner ruling stands unchanged and is restated in the gate: this is
#     evidence a leg did the reading work, not an authenticated control.
#   0.20.0 (2026-07-31): agy leg reliability policy, from a planted-defect
#     replay of a real merge packet (see `references/evidence.md`): agy verdict
#     = ADVISORY for the unanimous gate, a mandatory CONTAINMENT block in the
#     agy leg prompt, a measured rubber-stamp latency signal, and agy cites
#     verified before entering the residual table.
---

# triad-cross-family-review

The leader's standard **final pre-merge review**: three independent reviewers
from different model families judge a diff/branch, the suspect decisions are
posed as questions, and findings drive a fix→re-confirm loop. Codifies
the lab's standing cross-family review rule.

## When to use

- About to merge review-worthy or security/correctness-critical work.
- The leader OMITTED or SIMPLIFIED something from a vetted external source
  (the canonical author-blind-spot case).
- After a `superpowers:subagent-driven-development` run, before integrating —
  per-task spec+quality reviews are same-family and miss cross-cutting issues.

## Skip when

- A single-shot codex / gemini / agy / claude call → the per-CLI dispatch SKILLs (the `Agent` tool for claude).
- Trivial / mechanical change with no correctness or security surface.

## Contents

The body below is the whole operating contract: the hard rules and the flow.
Five references carry the detail — open one only when its column applies.

| Reference | Open it when |
|---|---|
| `references/leg-contracts.md` | dispatching legs, or weighing an agy verdict — Google-leg selection, per-leg flags/prompts, the agy containment block, **the MECHANICAL read-audit gate and its jq block**, the agy read/network residual |
| `references/packet-lifecycle.md` | opening/closing a packet dir, assembling a LARGE packet, ordering and fencing a packet, or freezing a round |
| `references/triage.md` | consolidating a round — release paths, REAL / REACHABLE-UNOBSERVED / SPECULATIVE, the scope-expansion gate, the residual table, the reviewer-side severity instruction |
| `references/failure-modes.md` | a round misbehaved and you want the rule that already covers it — symptom → cause → rule index |
| `references/evidence.md` | a threshold or policy looks arbitrary — latency measurements, the agy depth study, measured timeouts, origin incidents |

## Hard rules

1. **Three INDEPENDENT cross-family reviewers.** (a) a **claude fresh-eye
   sub-agent** via the `Agent` tool with `subagent_type: triad-dispatch:cross-family-review-reviewer`
   — the dedicated read-only reviewer agent
   (`agents/cross-family-review-reviewer.md`) whose frontmatter pins
   `tools: Read, Grep, Glob`, making rule 7's no-execute contract mechanical
   rather than advisory. Never the leader reasoning in-line: the leader holds the
   originating framing and shares its blind spot. (b) **codex** via
   `triad-codex-dispatch`. (c) the **Google-family CLI**, resolved at runtime —
   agy and gemini share the Gemini backend, so exactly one of them is the Google
   leg. Same-family-only reviewers inherit the leader's framing; cross-family
   plus fresh-eye is what breaks the monoculture.
   - **agy verdict = ADVISORY for the unanimous gate** (standing policy). Its
     findings consolidate like any leg's, but its SAFE does not satisfy the merge
     gate — gate on codex + claude. The same applies to a Google leg that fell
     back to the shallow default tier.
   - **Degraded mode = fewer than three families RETURN a consolidated verdict
     this round** — neither Google CLI installed, or a leg logged terminally
     missing (rule 13). A leg that RAN and was consolidated is not degraded mode,
     whatever its verdict weighs. Degraded mode does not block merge by itself; it
     requires an explicit owner decision before merging on fewer than three
     families.
   - **Depth: xhigh-class by default; max-class only on a round the leader
     designates very-important AND algorithmically complex**, both deep legs
     escalating together. The tier is necessary but not sufficient — every leg
     also needs rule 11's adversarial framing, and rule 10's max-thinking prompt
     directive on the claude leg stays unconditional at every tier.
   - **The agy leg's read/network egress is open by design** — a deployment that
     cannot accept that runs the leg inside an external fs-scoped,
     network-denied OS sandbox.
   Everything per-leg — the deterministic selection snippet, each leg's flags and
   prompt requirements, the agy containment block, the MECHANICAL read-audit gate
   (run it before weighing that leg's verdict and before any agy finding enters
   the residual table), the folded-verdict re-dispatch, and the egress residual's
   evidence — is in `references/leg-contracts.md`.
2. **Frame suspect decisions as QUESTIONS, not settled facts.** "Is X actually
   safe to omit?" — never "X is a no-op." A biased framing propagates into the
   reviewers and defeats the purpose.
3. **Each reviewer gets the diff scope; the transport differs per leg — state it
   once here.** Give the branch ref / SHA range plus the list of suspect
   decisions. The READING legs (claude `Agent`, agy, gemini) open the packet with
   their OWN READ tools rather than by executing `git diff` or any other
   subprocess (rule 7), which keeps leader context lean; the **codex leg is
   always inlined** into `--prompt` instead, because under read-only + no-exec it
   may be unable to open a handed-over file at all (rule 9). For a LARGE packet
   the leader pre-assembles ONE focused file: the reading legs open only that
   file, and codex receives the same focused content inlined (rule 8).
4. **Consolidate, don't average — the LEADER verifies, classifies, then acts.**
   Any reviewer's Critical / must-fix, or a DO-NOT-MERGE verdict, blocks merge.
   A block is released only by a probe that refutes the finding, a fix the
   re-confirm pass clears, or a recorded owner decision — the three paths are
   exhaustive and a leader-side triage never clears a block on its own. The
   leader's three consolidation duties (fact-check → classify the round
   CONVERGING / CONFLICTED / OSCILLATING → call the owner immediately on a
   CONFLICTED item or an OSCILLATING round), the two severity/triage axes, and
   the release paths in full are in `references/triage.md`. A leg wired to the
   shared `LegVerdict` schema (rule 1's per-leg `--pydantic`/output-contract
   wiring) returns a validated JSON object, so mapping its `findings[]` into
   the residual table is mechanical (`jq`, `references/triage.md` §
   Consolidating validated LegVerdict objects) — a leg dispatched without the
   schema still consolidates from prose, the fallback stated there.
5. **Fix→re-confirm loop, no round cap — stops are evidence-based.** Findings →
   fix each (own implementer + per-fix review) → re-run the 3-way on the fixed
   branch. A first-pass DO-NOT-MERGE addressed by a FIX closes only through a
   re-confirm pass, never by the leader asserting it is fixed; a finding refuted
   by a probe closes through that path instead, with the probe recorded. There is
   no round cap (owner directive — the former `TRIAD_REVIEW_MAX_ROUNDS` is
   retired): rounds continue while they keep landing REAL findings, and they stop
   on EVIDENCE — rule 12's non-convergence stop, rule 4's CONFLICTED/OSCILLATING
   owner call, or rule 14's TERMINAL exit. Name the non-termination to the owner
   rather than looping on autopilot. Rule 14 BOUNDS the loop's autonomy: only
   REAL-triaged findings with minimal diffs are fixed autonomously.
6. **Codex-path caveat (cross-family-rule nuance).** When the work being reviewed IS
   the codex dispatch path itself, codex reviews the *artifact diff* (e.g.
   Python), not its own reasoning — cross-family + fresh-eye still holds, so the
   full 3-way is valid. Use judgment; when in doubt, keep all three.
7. **Vendor review legs: READ-only, no-exec, generous timeout.** Every leg prompt
   — codex / agy / gemini, and the claude `Agent` leg, which also enforces
   no-exec mechanically through its tool allowlist (rule 1a) — instructs the
   reviewer to review by READING (`git diff`, file reads): "Do NOT run
   scripts/tests or spawn subprocesses / vendor CLIs." An agentic sandboxed
   reviewer otherwise live-runs the code under review, hangs on a real vendor API
   call, and under its read-only sandbox cannot reap the hung child — burning the
   whole timeout with no verdict. Pair the no-exec directive with a **timeout
   scaled to packet size × reasoning tier** — both, not either: budget
   `--timeout 1500` for a LARGE packet at the max tier, and prefer SHRINKING the
   packet (rules 8-9) over raising the timeout. Also avoid concurrent same-family
   API pressure: keep the gemini leg off the wire while another leg may also call
   gemini (429). A live-run finding can still be valid — capture the gap, then
   re-dispatch read-only. Measurements and the originating incident:
   `references/evidence.md`.
8. **Vendor-leg context files go at a repo-relative gitignored path, never
   `/tmp`.** Put every review-context file inside a helper-managed packet dir
   under the gitignored `_runs/review/` — never a bare `_shared/<name>.md` — so
   every leg can `Read` it; gemini is workspace-sandboxed to the repo and cannot
   read `/tmp` at all. For a LARGE diff or a multi-document review, PRE-ASSEMBLE
   one focused packet file and have the vendor leg read only that; telling a
   sandboxed leg to self-assemble burns its whole wall-time budget and returns no
   verdict. The packet's canonical order is deployment-context → fenced diff
   subset → suspect questions LAST, with any per-leg containment block riding
   immediately before that closing instruction. Before dispatching, digest the
   packet and every reviewed file, and FREEZE the tree for the round. Lifecycle
   commands, the ownership fences, the fencing text, and the digest procedure:
   `references/packet-lifecycle.md`.
9. **codex leg: INLINE the packet into `--prompt`; never hand it only a file
   path.** A codex leg under `--sandbox read-only` plus rule 7's no-exec
   directive may be unable to open a handed-over file at all and returns no
   verdict. The call-site substitution shape, the single-quoted-heredoc pitfall
   it must avoid, and the large-diff focused-subset requirement are in
   `references/leg-contracts.md` § codex leg.
10. **claude fresh-eye leg = a TRUE fresh-eye Agent, MAX thinking, adversarial.**
    The claude leg is a separate `Agent` with isolated context — never the leader
    reasoning inline. Because it is the same family as a claude leader, its
    marginal value is CONTEXT-freshness rather than family diversity (codex/agy
    carry that), so it must reason maximally to earn its place. Its prompt must
    (a) tell it to think as hard as possible before answering (ultrathink);
    (b) frame it adversarially — "a subtle defect is PRESENT; find what the
    same-family leader AND the per-task review missed", not "check if this looks
    fine"; (c) forbid severity-deflation — rate by impact rather than
    downgrading a real correctness/robustness issue to Minor to dodge a fix loop.
    It is spawned mechanically read-only via the dedicated reviewer agent (rule
    1a). Cross-check: if claude returns SAFE while a vendor leg returns must-fix,
    read that as a signal the claude prompt under-reasoned, and sharpen it next
    round.
11. **Adversarial anti-rubber-stamp framing on EVERY leg, not just claude.** The
    rule-1 review tier is necessary but not sufficient: a leg at its deepest tier
    still rubber-stamps when the prompt only asks it to check that things look
    fine. Apply rule 10's framing (assume a defect is present; no
    severity-deflation) to the codex and agy legs too, and additionally require
    every leg to (a) ENUMERATE which criteria/rules it checked before concluding
    and (b) treat a bare "SAFE / none / faithful" verdict as a failed review
    rather than a pass. A fast, terse SAFE from any leg is a rubber-stamp signal
    → re-dispatch that leg with the adversarial framing; the measured threshold
    is under 60s on a packet of 100KB or more. For the agy leg that latency check
    is SECONDARY, behind rule 1's mechanical read-audit gate (a leg the gate rules
    VOID never reaches it); for codex, which has no read-audit instrumentation,
    latency stays the primary heuristic. Criteria enumeration is required but is
    not evidence of depth (`references/evidence.md`).
12. **Non-convergence is a STOP, not another round.** The fix→re-confirm loop
    exists to CONVERGE. Stop dispatching when a new round — without adding
    material new evidence — merely flips a prior round's settled decision,
    contradicts another live leg head-on, or re-litigates an already-adjudicated
    point: consolidate the conflicting claims into a table (claim / leg / round /
    evidence) and hand the conflict to the owner. When a flip or contradiction
    DOES carry new evidence, adjudicate it with a deterministic probe first and
    let the probe decide whether the loop has genuinely stopped converging.
    Owner-call threshold (owner directive): the FIRST head-on same-decision
    contradiction where both sides survive the probe is already an owner call
    (rule 4) — no waiting for oscillation, no compromise crafted first. A
    probe-refuted side is not a conflict; close it by recording the probe. One
    healthy signal is not a conflict either: independent legs finding the SAME
    defect is a CONVERGENCE floor — fix it and run one final confirm.
13. **Leg orchestration: background dispatch, ONE generous wait, no unrelated
    interleaving.** Dispatch every leg in the background and wait event-driven:
    one generous wait per leg, never short repeated polls. A wait that expires is
    a wake-up boundary rather than evidence the leg failed — inspect that leg's
    state ONCE, keep a healthy running leg alive through its completion
    notification, and move a leg to rule 1's degraded/missing handling only on a
    documented terminal failure or an explicit owner decision to end the wait.
    Never interrupt or respawn a healthy leg because a wait elapsed, and never
    re-wait a leg whose result already arrived. While legs run, keep the leader's
    own context review-adjacent (fact-check planning, packet hygiene, staging
    fixes for already-returned findings): unrelated work interleaved here
    pollutes later consolidation and leg prompts. Delegate only concrete, bounded
    work, and tell each leg what to inspect and exactly what to return — a
    distilled verdict plus findings with evidence paths, never a raw dump.
    Consolidate once every dispatched leg has either returned a result or been
    logged terminally missing through that terminal path, never by silently
    dropping one. claude-host mechanics: the `Agent` tool runs in the background
    by default (`run_in_background` overrides per call) and fires a completion
    task-notification; a completed agent is resumed by id/name via `SendMessage`;
    wrapper legs are background Bash plus their completion notification.
14. **Finding triage and over-design containment (owner directive).** The loop
    structurally rewards ADDING code, so every finding is classified during
    rule-4 consolidation BEFORE it may enter the fix queue: **REAL** (demonstrated
    — repro, logged occurrence, or cited passages read side by side) →
    minimal-diff fix; **REACHABLE-UNOBSERVED** (mechanism exists, no occurrence
    evidence) → reproduce FIRST, and a failed repro becomes a DISCLOSED residual
    rather than a reclassification; **SPECULATIVE** (cannot occur in this
    deployment) → **no code**, record a DISCLOSED residual. Any fix that expands
    design scope — a new guard/fallback/retry/lock/validation layer, a new
    file/dependency/config surface, a spill beyond the finding's file, or more
    than 30 changed lines — STOPS for an explicit owner OK, even mid-round. A
    round whose remaining findings are all SPECULATIVE or repro-failed is
    TERMINAL: record the residuals and route a BLOCKING one to the owner. Every
    finding that is not fixed carries a row in the residual table; rows are
    updated, never deleted. The class definitions, the countable scope-gate
    thresholds, the residual-table schema and dispositions, and the reviewer-side
    severity instruction every leg prompt carries are in `references/triage.md`.

## Flow

1. Scope the review: branch ref + base SHA + the list of suspect/omitted/
   simplified decisions (phrased as questions). Open the packet dir with the
   rule-8 helper (`python3 <skill>/lib/review_scratch.py open <abs>/_runs/review
   <slug>`, which also prunes stale packets from crashed past reviews). If the
   packet is LARGE, pre-assemble the focused packet file (framing + high-risk
   diff subset) inside that dir, e.g. `<packet-dir>/packet.md`; the agy/gemini
   leg reads only that, codex inlines the same focused body. At review end,
   `… close <packet-dir>`.
2. Resolve the Google-family leg, then dispatch the reviewers in parallel, each
   at its family's default review tier (rule 1; max-class only on a designated
   escalation round) — `Agent` with
   `subagent_type: triad-dispatch:cross-family-review-reviewer` (escalation round →
   `subagent_type: triad-dispatch:cross-family-review-reviewer-max`; max-thinking + adversarial
   prompt per rule 10) + `triad-codex-dispatch` (codex `--reasoning xhigh
   --search`) + the resolved Google leg (`triad-antigravity-dispatch` with
   `--sandbox read-only` and `TRIAD_READ_AUDIT_FILE` bound, or
   `triad-gemini-dispatch`; skip and log if neither is installed). Each leg gets
   the same suspect-question list and diff scope. The agy leg stays read-only for
   the WHOLE round, including its folded-verdict re-dispatch
   (`references/leg-contracts.md` § agy leg).
   **Dispatch precondition — codex `--search`:** this skill passes `--search` by
   default, so the packet content becomes live web-search query context sent to
   the vendor's search backend. Confirm the packet may reach a vendor search
   backend before dispatching; if it may not, drop `--search` for that round and
   record the choice. The default stays ON, and the egress itself is a disclosed
   residual (`references/leg-contracts.md` § codex leg).
   Per-leg flags and prompts: `references/leg-contracts.md`.
3. Collect the three verdicts + findings, then run rule 4's consolidation:
   fact-check each finding against the source with a deterministic probe, TRIAGE
   each finding REAL / REACHABLE-UNOBSERVED / SPECULATIVE (rule 14 — SPECULATIVE
   → DISCLOSED residual, no code), and classify the round CONVERGING /
   CONFLICTED / OSCILLATING.
4. Merge when the round is CONVERGING — a CONFLICTED item or an OSCILLATING round
   routes to the owner FIRST, and merge never passes one — AND the GATING legs
   (codex + claude) are unanimously SAFE TO MERGE with no must-fix, AND no
   BLOCKING residual row is still `open` or `fix-ordered`, AND every rule-14
   obligation is discharged (owed repros run; SPECULATIVE / UNKNOWN-CONTEXT
   residuals recorded — a non-blocking row needs recording, not an owner
   decision; every REAL finding either fixed or carrying a row, so a REAL Minor
   never silently disappears). The Google-family leg's SAFE weighs findings but
   does not itself satisfy the gate (rule 1). A standing non-SAFE verdict from a
   gating leg can still be released this round, and an unusable one is handled as
   a missing leg — both cases in `references/triage.md` § Verdict release at the
   merge gate.
5. Run any owed REACHABLE-UNOBSERVED repros FIRST — a successful repro
   reclassifies the item REAL and it joins the fix path. Then, if no finding
   triages REAL — decidable only once every dispatched leg has returned a verdict
   or been logged terminally missing (rule 13; a wrapper failure is never counted
   as SAFE or as no-findings), and after any CONFLICTED item has been routed to
   the owner WITH the rule-12 conflict table — the loop is TERMINAL: record the
   DISCLOSED residuals, hand the merge decision to the owner when any residual row
   is BLOCKING, otherwise return to Flow 4. Do not GOTO 2. Otherwise, if the round
   is CONVERGING: fix each REAL finding with a minimal diff (implementer +
   per-fix review; a design-expanding fix stops for an owner OK), then GOTO 2 to
   re-confirm, with no round cap (rule 5). If any item is CONFLICTED or the round
   is OSCILLATING, call the owner instead of re-dispatching and hand over the
   conflict table; non-conflicted findings may continue their fix loop meanwhile.

## Failure modes

Symptom → cause → the rule that owns the fix: `references/failure-modes.md`.
It is an index, not a second statement of the rules.

## Why this exists

A same-family review chain shares the leader's blind spot, and a strict per-task
same-family review still misses cross-cutting issues. The originating incident
and the re-validation are in `references/evidence.md`.

## Related

- `triad-codex-dispatch` (codex leg) / `triad-antigravity-dispatch` + `triad-gemini-dispatch` (the runtime-selected Google-family leg).
- `superpowers:subagent-driven-development` — the per-task (same-family) review this final pass backstops.
- `superpowers:requesting-code-review` / `superpowers:receiving-code-review` — single-reviewer code-review conventions.
