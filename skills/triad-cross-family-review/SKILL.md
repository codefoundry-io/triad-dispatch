---
name: triad-cross-family-review
description: Runs the FINAL pre-merge (or review-worthy / security-or-correctness-critical) cross-family review mandated by the lab's cross-family review rule — dispatches INDEPENDENT cross-family reviewers (a claude fresh-eye sub-agent via Agent + codex via triad-codex-dispatch + the Google-family CLI selected at runtime, agy via triad-antigravity-dispatch or gemini via triad-gemini-dispatch), frames the suspect/omitted/simplified decisions as QUESTIONS, consolidates their verdicts (SAFE TO MERGE / MERGE WITH FIXES / DO NOT MERGE), then runs a fix→re-confirm loop until the gating legs are unanimously SAFE (a MERGE WITH FIXES carrying only non-blocking findings satisfies the gate). Trigger when about to merge review-worthy work, ESPECIALLY when the leader chose to OMIT or SIMPLIFY something from a vetted source, or after a subagent-driven implementation before integration.
version: 0.36.0
# changelog:
#  0.36.0 (2026-09-18): H0 (plan `docs/superpowers/plans/2026-09-18-cfr-post-review-hardening.md`) — the runtime doc carries rules, not history: changelog 0.23.0-0.35.3 moved verbatim to `docs/reviews/2026-09-18-cfr-skill-history.md` (551 lines; vendor guidance 500 — the rules-body reorder toward the 5k compaction re-attach window is D8, its own gate); every packet-era transport directive retargeted — rule 3 (every leg reads the round worktree; codex through its read-only shell), rule 4 (`--expected-packet` hashes the file it names), rule 11 (a DIFF of 100 KB), the reference index row and the Flow pointer (§ Large diff), `packet-lifecycle.md` header / index / § Large diff / the codex sentence, `failure-modes.md` row 21; the three reviewer agent bodies collapse § Output to the round prompt's contract and § Adversarial stance to the clauses the rendered prompt does not carry (120 → 82 lines each). `t7` pins: ≤ 560 lines, no packet-era transport phrase, no dangling Large-packet section anchor. Doc-only; no contract changed meaning.
#  0.35.5 (2026-09-18): owner ask — every wrapper path argument is ABSOLUTE (`--prompt-file`, `--cwd`, `$PACKET_DIR`); the wrappers refuse a relative path before any vendor call (rc 3, stdout EMPTY). Stated at the codex call site in `references/leg-contracts.md` and as a symptom row in `references/failure-modes.md` (observed 2026-09-18 on an ad-hoc plan-gate brief dispatched outside a round). Doc-only.
#  0.35.4 (2026-09-18): S2-9 — the S2 ledger's owner-optional row, ACCEPTED by the owner on resume (2026-09-18): `codex_wrapper.py` passes `--ignore-rules` on EVERY posture, not only read-only — a wrapper dispatch pins `approval_policy=never` and never wants an escalation outside the sandbox on the write posture (`--task code`) either; the operator's execpolicy allow rules (`git add/commit`, `gh …`, `rm -rf _runs` on this host) were the one path around that pin, and inside workspace-write the same commands still run when the sandbox permits them. Skill behaviour is unchanged (the codex leg was already read-only); `references/leg-contracts.md` W16 bullet + call-site note, the plugin `README.md`, root `CLAUDE.md` resynced; `t24` write-posture axis flipped from absence to presence (RED observed, then GREEN). Same day, before this change: the 41 commits `27640ed..929d971` PUSHED and the S3 dist re-export DONE (`~/triad-dispatch` 0.2.821, SKILL 0.31.0→0.35.3 in one export); this change re-exports again.
#  older entries (0.23.0-0.35.3): docs/reviews/2026-09-18-cfr-skill-history.md
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
| `references/leg-contracts.md` | dispatching legs, or weighing an agy verdict — Google-leg selection, per-leg flags/prompts, the agy READ-GRANT block, **the MECHANICAL read-audit gate (executable form = `lib/read_audit_gate.sh`)**, the agy read/network residual |
| `references/packet-lifecycle.md` | opening/closing a packet dir, shrinking a large diff, ordering and fencing a round, or freezing it |
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
   - **(d) Standing FOURTH leg(s) — ADVISORY, configured by the skill USER.**
     A fourth leg runs on the SAME packet and is consolidated like any leg,
     tagged `x:<name>` (rule 15). It never gates, never counts toward the three
     families. The legs of a round come from
     `<worktree>/.claude/triad-review-legs.json` (project) or
     `~/.config/triad/review-legs.json` (user, `$XDG_CONFIG_HOME`-aware — an
     unset, empty or RELATIVE value falls back to `~/.config`) —
     schema + example in `references/leg-contracts.md` § Fourth leg and
     `references/review-legs.example.json`; an explicit `--x-leg` (repeatable)
     replaces the file's legs for the round, `--no-x-leg` drops them, the two
     flags together are refused (exit 2); `$TRIAD_REVIEW_X_LEGS` is a
     DEPRECATED fallback honored only when no config file exists (its NOTE says
     so). Exactly one source ARM fires (its NOTE on stdout; every ignored
     source is mirrored to stderr); a gemini fourth leg WITH an effort field
     additionally prints its effort NOTE. `prepare` records the source, the
     config path and the disabled entries in `.x-legs-r<N>.json` on EVERY
     round. **No config = three standing legs** — the `NOTE — no fourth leg
     configured this round` line is information, NOT a defect.
     **Recommended default (owner 2026-09-14, ten-round evidence
     `docs/reviews/2026-09-07-design-campaign-gate.md`):** the claude `high`
     comparison arm `cross-family-review-reviewer-high` as a yield-justified
     SECOND claude arm (it raised 8 must-fix the gating claude arm missed, 2 of
     them found by no other leg). The Google Flash tier is no longer the
     standing fourth leg (0 unique blocking defects over 10 rounds); keep it on
     file with `enabled: false` if a deployment wants to re-enable it. Whenever
     a Flash leg IS configured, Pro + Flash agreement is ONE family for every
     two-family rule (`references/triage.md` § Countable stop rules).
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
   prompt requirements, the agy READ-GRANT block, the MECHANICAL read-audit gate
   (run `lib/read_audit_gate.sh` AND the hook LOAD CHECK `lib/agy_hook.py
   check` — `HOOK_LOAD_PASS`, 0.35.0 — before weighing that leg's verdict and before
   any agy finding enters the residual table), the folded-verdict re-dispatch,
   and the egress residual's evidence — is in `references/leg-contracts.md`.
2. **Frame suspect decisions as QUESTIONS, not settled facts.** "Is X actually
   safe to omit?" — never "X is a no-op." A biased framing propagates into the
   reviewers and defeats the purpose.
3. **Each reviewer gets the diff scope; the transport differs per leg — state it
   once here.** Give the branch ref / SHA range plus the list of suspect
   decisions. Every leg is dispatched `--cwd <round worktree>` and opens
   `brief.md`, `diff.prod.patch`, `diff.tests.patch` and `history.txt` with its
   OWN read tools (rule 8) — never by executing `git diff` or any other
   subprocess (rule 7), which keeps leader context lean; the codex leg reads the
   same files through its read-only shell (rule 9). A diff near a context
   ceiling is shrunk with `--diff-path`, `--tests-path` and `--excerpt` (rule 8),
   never by assembling a packet file.
4. **Consolidate, don't average — the LEADER verifies, classifies, then acts.**
   Any reviewer's Critical / must-fix, or a DO-NOT-MERGE verdict, blocks merge —
   and ONLY those do: a MERGE WITH FIXES whose findings are all non-blocking
   (Minor / HARDENING-SUGGESTION) imposes no block (`references/triage.md`
   § Verdict release), and every leg prompt carries the verdict-selection rule
   so a leg with nothing blocking says SAFE outright instead of a
   Minor-only MERGE WITH FIXES.
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
   schema still consolidates from prose, the fallback stated there. The
   schema BINDS each verdict to its round and leg
   (`review_id`/`family`/`content_digest`, required): admission runs
   `lib/validate_verdict.py --expected-review-id/--expected-family/
   --expected-packet` for EVERY leg's JSON — the binding flags are
   all-or-nothing (a flagless run is loudly shape-only, never an
   admission), `--expected-packet` recomputes the digest from the file it
   names — and a binding mismatch is
   the INVALID-leg handling, never a pass
   (`references/leg-contracts.md` § Verdict binding). The claude leg's
   RAW reply file admits via `--admit` (+ `--end-marker <END-VERDICT>`,
   which the rendered prompt instructs, + `--admitted-out
   claude-r<N>-verdict.json` — the ONLY producer of the canonical file
   the consolidation jq loop reads) — no repair path; an unparseable
   reply takes the ONE-targeted-re-ask-then-INVALID chain whose
   definitional home is `references/triage.md` § Verdict release; a
   leader-completed reply is never admissible (2026-08-30 hardening).
5. **Fix→re-confirm loop — NO round cap (owner directive 2026-09-17,
   superseding the 2026-08-22 three-round cap).** Findings → fix each (own
   implementer + per-fix review, SDD/TDD — the leader VERIFIES the findings,
   delegating the verification to a subagent when that helps, and delegates
   the IMPLEMENTATION to a subagent whenever that keeps the leader's context
   lean at a worthwhile effort/model-cost trade) → re-confirm on the fixed
   branch. A first-pass DO-NOT-MERGE addressed by a FIX closes only through a
   re-confirm pass, never by the leader asserting it is fixed; a finding
   refuted by a probe closes through that path instead, with the probe
   recorded. **Non-contradicting findings that catch bugs or completeness
   gaps INSIDE the existing design are welcome at ANY round count** — fix them
   and re-confirm without asking; round arithmetic was never the problem.
   Stops: (a) **design or plan change** — a finding whose fix requires
   changing the gated plan or design (a new contract, a restructured order of
   operations, a new public def/class not in the gated design) goes to the
   OWNER before any design work starts. Accepting a review and sliding into
   over-design without that discussion is the failure this rule exists to
   prevent; (b) **convergence** — a round with zero NEW REAL must-fix findings
   ends the gate: if that round produced a fix wave, apply it and run ONE
   focused re-confirm scoped to the wave's hunks — the two GATING legs
   (codex + claude) at minimum, agy optional; a clean round with no wave
   skips the focused pass; then merge, PROVIDED every prior blocking row
   already carries a rule-4 release disposition (re-confirmed fix, recorded
   probe, or owner decision); (c) rule 12's contradiction stop and rule 4's
   CONFLICTED/OSCILLATING owner call, rule 14's TERMINAL exit. **Docs never gate code**: text-only
   findings are batched into one post-merge doc-resync commit and never
   trigger a round. A plan-gate fold that introduces a NEW semantic contract
   draws a fresh layer of REAL findings every round — fold the CONSTRAINTS
   and delegate the row-level design to the owning unit's own gate
   (`references/triage.md` § Scope-expansion gate). Name the non-termination to the owner rather than looping
   on autopilot. Rule 14 BOUNDS the loop's autonomy: only REAL-triaged
   findings with minimal diffs are fixed autonomously.
6. **Codex-path caveat (cross-family-rule nuance).** When the work being reviewed IS
   the codex dispatch path itself, codex reviews the *artifact diff* (e.g.
   Python), not its own reasoning — cross-family + fresh-eye still holds, so the
   full 3-way is valid. Use judgment; when in doubt, keep all three.
7. **Vendor review legs: READ-only, no-mutation/no-execution, generous
   timeout.** Every leg prompt — codex / agy / gemini, and the claude `Agent`
   leg, which also enforces no-exec mechanically through its tool allowlist
   (rule 1a) — instructs the reviewer to review by READING (`git diff`, file
   reads): forbidden are file MUTATION, external-state change, and CANDIDATE
   EXECUTION (running tests/scripts/builds or the code under review, spawning
   vendor CLIs). TWO legs' directives are SCOPED to a READ-GRANT: the CODEX
   leg (read-only shell commands explicitly PERMITTED; the old blanket
   wording banned the very commands codex reads files with; trailer in
   `references/leg-contracts.md` § codex leg) and the AGY leg (the worktree
   BRIEF read FIRST, still the mechanical read-audit gate's required entry,
   then verification reads across the pinned tree with file:line cites;
   `references/leg-contracts.md` § agy leg). For both, the round's
   capture/verify integrity gate (`references/packet-lifecycle.md` § Round
   integrity) is the compensating control — mutation detection, not a
   sandbox claim alone, decides admission. For the AGY leg the containment
   is MECHANICAL since 0.35.0 (S2): the round worktree carries a PreToolUse
   hook (`lib/agy_hook.py`, written by `prepare` into
   `<worktree>/.agents/hooks.json`) that DENIES mutating / command / network /
   subagent / planner tools before they run — whatever agent resolved, since
   `--agent` fails OPEN silently; admission is EFFECT-based (a BLOCKED call is
   logged, an EXECUTED off-list call voids); and the hook LOAD CHECK
   (`agy_hook.py check …` → `HOOK_LOAD_PASS`) must pass beside the read-audit
   gate before that leg's verdict is weighed (`references/leg-contracts.md`
   § agy leg). An agentic sandboxed
   reviewer otherwise live-runs the code under review, hangs on a real vendor API
   call, and under its read-only sandbox cannot reap the hung child — burning the
   whole timeout with no verdict. Pair the no-exec directive with a **timeout
   scaled to DIFF size × reasoning tier** — both, not either: budget
   `--timeout 1500` for a large diff at the max tier, and prefer SHRINKING the
   reviewed surface (`--diff-path`, `--tests-path`, `--excerpt`; rules 8-9)
   over raising the timeout. Also avoid concurrent same-family
   API pressure: keep the gemini leg off the wire while another leg may also call
   gemini (429). A live-run finding can still be valid — capture the gap, then
   re-dispatch read-only. Measurements and the originating incident:
   `references/evidence.md`.
8. **Delivery is the round's WORKTREE, at a repo-relative gitignored path,
   never `/tmp`.** `prepare` creates a DETACHED `git worktree` at
   `<packet-dir>/wt-r<N>` — THE ROUND LIVES IN THE NAME, and `close` derives
   the round from that name, never from anything inside the tree — under the
   gitignored `_runs/review/`, pinned at the
   right-hand side of `--diff`, and writes FOUR files into it: `brief.md`
   (deployment context, a size MANIFEST naming every changed file and the
   surface deliberately excluded, and the suspect questions LAST),
   `diff.prod.patch` (the gated material), `diff.tests.patch` (test changes,
   labelled as a statement of intended behaviour) and `history.txt`
   (`git log --stat`, so a leg sees commit boundaries without executing
   anything). Every leg is dispatched `--cwd <worktree>` and reads for itself;
   gemini is workspace-sandboxed to the repo and cannot read `/tmp` at all.
   **The LEADER builds the diffs** — every leg must judge the SAME bytes,
   because the binding's `content_digest` ties each verdict to that content and
   cross-family corroboration means nothing if three legs each computed their
   own diff. Retired with this design: packet assembly and `--file` whole-file
   embedding (the pinned tree already carries the whole file); `--excerpt`
   survives to pin a hot function INTO the brief, which is the mitigation when
   a diff is near the context ceiling. Before dispatching, run the round's
   `capture` (per-round evidence snapshot + canonical worktree fingerprint —
   `lib/review_scratch.py capture`, over the ROUND WORKTREE) and FREEZE the
   tree; after every required leg terminates, `verify` must print
   `ROUND_INTEGRITY_OK r<N>` before consolidation (the round-suffixed token, as
   the Flow's step 3 requires — a NON-round label's qualified line says the
   artifact hashes were not checked and never satisfies this gate). **The packet
   dir is HELPER-OWNED** (owner ruling 2026-09-17): manual manipulation beyond
   the ONE documented recovery — `references/packet-lifecycle.md` § Removing a
   stray checkout — is out of scope, and for any state it cannot name as its own
   round tree the helper REFUSES WITHOUT DELETING, states what it OBSERVES, and
   points at that section. For an entry it only OBSERVED — a stray or
   unremovable one — it prescribes no per-shape recovery command: do not expect
   a runnable exit in that refusal, and do not add one. The ONE runnable escape
   is the ROUND TREE's own `git worktree remove --force`, printed only after the
   helper has established LIVE — on that same call, before any unlink — that the
   source repository owns the tree and registers it at that path; it offers the
   operator the exit of accepting that the round's material is unverifiable.
   Lifecycle commands, the ownership fences, the fencing text, the
   `Review metadata:` block, and the capture/verify procedure:
   `references/packet-lifecycle.md`.
9. **codex leg: DE-INLINED — it reads the round worktree like every other leg
   (`--cwd` + READ-GRANT trailer).** Until this design the packet was inlined
   into `--prompt` as codex's guaranteed view; a tree checked out at the
   reviewed commit removes that premise, and the 2026-09-16 spike measured
   codex holding a 128 KB diff straight from the worktree (307.8 s `ok`, 13 of
   13 cited lines verified real against the tree). The read grant is what lets
   it VERIFY claims (the historical cannot-open-a-file failure was the old
   blanket no-exec directive, not the sandbox — reads were never
   sandbox-blocked, writes still are). Its trailer text, the rescoped fast-SAFE
   heuristic, the call-site shape and the single-quoted-heredoc pitfall it must
   avoid are in `references/leg-contracts.md` § codex leg.
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
    is under 60s on a diff of 100 KB or more. For the agy leg that latency check
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
    (rule 4; Pro + Flash = one voice) — no waiting for oscillation, no
    compromise crafted first. A
    probe-refuted side is not a conflict; close it by recording the probe. One
    healthy signal is not a conflict either: independent legs finding the SAME
    defect is a CONVERGENCE floor (Pro + Flash = one leg —
    `references/triage.md`) — fix it and run one final confirm.
    **Scope freeze (2026-08-22):** from round 3 on, a finding must cite a hunk
    of the gated diff; anything else (a pre-existing line, a neighbouring
    design, a hypothetical input shape) opens a NEW slice rather than another
    round of this one. **Two-family floor:** a single-family
    REACHABLE-UNOBSERVED item without a measured probe is a residual, not a
    fix.
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
    **Session-cwd pinning (probe-measured 2026-08-26):** the leader's
    foreground cwd is NOT durable across the wait — it resets to the primary
    working directory at context reinitialization, which lands exactly at
    long-leg wake-up boundaries (both recorded 2026-08-15 F40 occurrences).
    At every wake-up or dispatch boundary, RE-READ the real cwd (`pwd`)
    before the first repo-dependent command, and build every leg argument
    (`--cwd`, `--prompt-file`, packet paths) absolute at dispatch time —
    never from the memory of an earlier `cd`.
    **Retry artifacts + no hand-moves (2026-09-05):** a re-dispatched leg's
    earlier attempt is renamed `<leg>-r<N>-attempt<K>.err` /
    `<leg>-r<N>-attempt<K>-read-audit.json` /
    `<leg>-r<N>-attempt<K>-verdict.json` — all inside the leg-output
    allowlist. NEVER hand-move `agy-read-audit.json` (`prepare`/`capture`
    auto-rename it to the round suffix), never hand-remove an X leg's rendered
    input or `.x-legs-r<N>.json` (round evidence — an abandoned X leg is
    recorded MISSING in the round log and its artifacts stay), and never chain
    a file operation on a helper-managed file before a dispatch: a failed
    `mv &&` meant the codex leg never launched.
14. **Finding triage and over-design containment (owner directive).** The loop
    structurally rewards ADDING code, so every finding is classified during
    rule-4 consolidation BEFORE it may enter the fix queue: **REAL** (demonstrated
    — repro, logged occurrence, or cited passages read side by side) →
    minimal-diff fix; **REACHABLE-UNOBSERVED** (mechanism exists, no occurrence
    evidence) → reproduce FIRST — **from REAL vendor output** (a capture, a
    run-log, an audit row): a repro that exists only in a fixture records a
    DISCLOSED residual, it does not earn code (occurrence gate, 2026-08-22 —
    the v1.2 agy gate spent five rounds on parser shapes that never occurred
    in 22 real captures); a failed repro likewise becomes a DISCLOSED residual
    rather than a reclassification; **SPECULATIVE** (cannot occur in this
    deployment) → **no code**, record a DISCLOSED residual. Any fix that expands
    design scope — a new guard/fallback/retry/lock/validation layer, a new
    file/dependency/config surface, a spill beyond the finding's file, or more
    than 30 changed lines — STOPS for an explicit owner OK, even mid-round. A
    round whose remaining findings are all SPECULATIVE or repro-failed is
    TERMINAL: record the residuals and route to the owner any repro-failed
    REACHABLE item whose residual row would be BLOCKING (a SPECULATIVE item
    cannot block by definition). Every
    finding that is not fixed carries a row in the residual table; rows are
    updated, never deleted. The class definitions, the countable scope-gate
    thresholds, the residual-table schema and dispositions, and the reviewer-side
    severity instruction every leg prompt carries are in `references/triage.md`.
15. **Fourth leg (standing, advisory; 0.30.0 — was the experimental X leg of
    0.29.2).** An X leg is a FOURTH,
    purely ADVISORY reviewer pointed at another vendor / model / effort so its
    output can be compared with the standing leg of the same family. It NEVER
    gates, never counts toward rule 1's three families, and never substitutes
    for one — a failed or missing X leg cannot delay a round. Source order per
    round: `--x-leg` and `--no-x-leg` together are refused (exit 2); otherwise
    explicit `--x-leg` (repeatable) > `--no-x-leg` > the PROJECT config
    `<worktree>/.claude/triad-review-legs.json` > the USER config
    `$XDG_CONFIG_HOME/triad/review-legs.json` (`~/.config` when that variable
    is unset, empty or RELATIVE — a relative value is invalid and ignored per
    the XDG spec) > the DEPRECATED `$TRIAD_REVIEW_X_LEGS` (rule 1(d)) >
    none; exactly one source ARM fires (its NOTE on stdout; every ignored
    source is mirrored to stderr), and a gemini fourth leg WITH
    an effort field additionally prints its effort NOTE.
    Vendor ∈ agy|gemini|codex|claude, and model/effort
    are DISPATCH-TIME values the leader types, never pinned in code
    (`~/.claude/CLAUDE.md` § Web search rules). Per-vendor fields: agy and
    gemini take `[:<model>[:low|medium|high]]`, codex
    `[:<model>[:low|medium|high|xhigh|max]]`, and claude takes an AGENT TYPE
    only — which may itself be scoped `<plugin>:<agent>` — with NO effort
    field (a different tier is a different agent type, so a trailing effort
    token is refused). Names match `x-<lowercase-alnum>[-part]…`;
    `prepare` prints the leg's complete dispatch command and records
    `.x-legs-r<N>.json`. Each X leg is BOUND to its own
    `review_id` = `<review-id>.<name>`, so admission mechanically refuses an X
    verdict filed under the standing leg's id (and vice versa). An agy X leg's
    read audit is gated with `lib/read_audit_gate.sh --audit-file <its own
    x-…-r<N>-read-audit.json>` — that override must sit directly in the packet
    dir and carry the X basename shape; the standing audit is never legal. X
    findings enter the residual table tagged `x:<name>` and take the same
    triage; each round's comparison fields are `references/triage.md`
    § Fourth-leg comparison record, and a comparison CAMPAIGN (when the leader
    declares one) gets a leader-written ledger at
    `docs/reviews/<date>-x-leg-<name>-campaign.md`.

## Flow

1. Scope the review: branch ref + base SHA + the list of suspect/omitted/
   simplified decisions (phrased as questions). Open the packet dir with the
   rule-8 helper (`python3 <skill>/lib/review_scratch.py open <abs>/_runs/review
   <slug>`, which also prunes stale packets from crashed past reviews). Author
   the round's BRIEF — deployment context above one `=====QUESTIONS=====`
   marker line, the suspect questions below it — as a standalone file; that
   brief is the ONLY per-round text the leader writes. Keep the GATED SURFACE
   focused: for a LARGE diff name only the high-risk subset (a narrowed
   `--diff` range, `--diff-path` scoping, `--tests-path` to split test churn
   out of the gated patch, `--excerpt` hot functions into the brief) —
   `references/packet-lifecycle.md` § Large diff. At review end,
   `… close <packet-dir>` — which removes the round worktree FIRST, and
   refuses rather than forcing if a leg wrote into the reviewed tree.
2. Prepare the round with ONE deterministic command:
   `python3 <skill>/lib/review_scratch.py prepare <packet-dir>
   <source-repo> r<N> --brief <abs-brief.md>
   --diff <range> [--diff-path <rel>]... [--tests-path <pathspec>]...
   [--excerpt <rel>:<start>-<end>]...` — `--diff-path` pathspecs scope the
   reviewed surface, and `--tests-path` splits test churn out of the GATED
   patch (the review-is-CODE-only rule). It
   preserve-and-clears round-invariant leg outputs (`agy-read-audit.json`
   → its PRODUCING round's suffixed name, derived from the latest
   captured snapshot), creates the round WORKTREE at `<packet-dir>/wt-r<N>`
   (re-pinning REMOVES the round tree present, identified by its OWN name —
   never by the incoming label — after checking it against that round's record)
   pinned at the right-hand side of `--diff` and writes its four artifacts
   (`brief.md`, `diff.prod.patch`, `diff.tests.patch`, `history.txt`) with
   every byte moved FILE-TO-FILE (never streamed through leader context),
   writes `digest-r<N>.txt`, renders the three round-suffixed leg bodies
   (all three POINT AT the worktree — codex is no longer inlined)
   carrying the binding values, the per-leg READ-GRANT, and
   the verdict-selection rule, renders the CONFIGURED fourth leg's input from
   `.claude/triad-review-legs.json` (project) or
   `~/.config/triad/review-legs.json` (user) — rule 1(d); `--x-leg` /
   `--no-x-leg` override, `$TRIAD_REVIEW_X_LEGS` a deprecated fallback — and
   prints its dispatch command plus the source `NOTE`, and runs the round's
   `capture` (evidence
   snapshot + worktree fingerprint) — so every byte a leg reviews sits
   inside the census by construction (adopt-gate r1 lesson;
   `references/packet-lifecycle.md` § Round integrity + § Deterministic
   round preparation). Then resolve the
   Google-family leg and dispatch the reviewers in parallel, each
   at its family's default review tier (rule 1; max-class only on a designated
   escalation round) — `Agent` with
   `subagent_type: triad-dispatch:cross-family-review-reviewer` (escalation round →
   `subagent_type: triad-dispatch:cross-family-review-reviewer-max`; max-thinking + adversarial
   prompt per rule 10) + `triad-codex-dispatch` (codex `--reasoning xhigh
   --search`) + the resolved Google leg (`triad-antigravity-dispatch` with
   `--sandbox read-only` and `TRIAD_READ_AUDIT_FILE` bound, or
   `triad-gemini-dispatch`; skip and log if neither is installed) + the fourth
   leg by the command `prepare` printed (rule 1(d)). Each leg gets
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
3. Once every required leg has terminated, run `verify` for the round — it
   must print `ROUND_INTEGRITY_OK r<N>` (a mismatch INVALIDATES the round:
   mutation detected, never released) — validate every leg (claude: via the `--admit` route, rule 4)'s JSON with
   `lib/validate_verdict.py --expected-*` (rule 4's binding admission), then
   collect every returned leg's verdict and findings (the fourth leg included —
   for an agy fourth leg (a gemini override writes no audit —
   `references/leg-contracts.md` § gemini leg) gate its read audit with
   `lib/read_audit_gate.sh --audit-file <its own
   x-…-r<N>-read-audit.json>` first) and run rule 4's consolidation:
   fact-check each finding against the source with a deterministic probe, TRIAGE
   each finding REAL / REACHABLE-UNOBSERVED / SPECULATIVE (rule 14 — SPECULATIVE
   → DISCLOSED residual, no code), and classify the round CONVERGING /
   CONFLICTED / OSCILLATING.
4. Merge when the round is CONVERGING — a CONFLICTED item or an OSCILLATING round
   routes to the owner FIRST, and merge never passes one — AND the GATING legs
   (codex + claude) are unanimously SAFE TO MERGE with no must-fix — where a
   gating leg's MERGE WITH FIXES whose findings are ALL non-blocking
   (Minor / HARDENING-SUGGESTION) SATISFIES this clause (`references/triage.md`
   § Verdict release: it does not block merge; its findings still triage and
   carry residual rows) — AND no
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
   re-confirm — there is no round cap (a zero-new-REAL-must-fix round
   ends the gate with one focused re-confirm). If any item is CONFLICTED or the round
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
