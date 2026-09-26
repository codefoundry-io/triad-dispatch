---
name: triad-cross-family-review
description: Runs the FINAL pre-merge (or review-worthy / security-or-correctness-critical) cross-family review mandated by the lab's cross-family review rule — prepares ONE frozen round from a named ROSTER of INDEPENDENT cross-family reviewers (a claude fresh-eye sub-agent via Agent + codex via triad-codex-dispatch + the Google-family CLI selected at runtime — agy via triad-antigravity-dispatch, with compatibility for the older gemini CLI via triad-gemini-dispatch — plus any entry the project configured), frames the suspect/omitted/simplified decisions as QUESTIONS, admits every entry's verdict (SAFE TO MERGE / MERGE WITH FIXES / DO NOT MERGE) against the canonical schema, and folds them into ONE outcome (AGREED / BLOCKED / INCOMPLETE / OWNER_DECISION_REQUIRED) driving a fix→NEW-round loop. Trigger when about to merge review-worthy work, ESPECIALLY when the leader chose to OMIT or SIMPLIFY something from a vetted source, or after a subagent-driven implementation before integration.
version: 0.38.1
# changelog:
#  0.38.1 (2026-09-26): DOC RESYNC to the code gate 1 closed on (ledger `docs/reviews/2026-09-21-host-a-v2-gate1.md`). (1) **The hook LOAD CHECK attributes hook rows BY conversation id** — every census row with tool steps needs a hook row under an id NO OTHER census row recorded (a shared logged id attributes neither → INCONCLUSIVE); while ANY census row's id list is not provably whole (`conversation_ids_omitted`, or an id-losing marker: `capture_complete` false, `truncated_tail`, `undecodable_lines`, `interrupted`) no row is attributed and the round is INCONCLUSIVE; a zero-step row whose transcript is incomplete (those markers or `steps_open` > 0) refuses the census, and `steps_open` never blinds a stepped row (an open step loses no id); `result_events` is a count, NOT an incompleteness marker. Summary: `HOOK_LOAD_<VERDICT> tool_steps=<n> invocations=<n> denied=<n>`, plus ` attributed=<hooked>/<must>` when more than one row must be attributed. A sibling attempt with no audit is INCONCLUSIVE when its `stderr.log` carries the engine's `exec` spawn line or is unreadable, and skipped when it never spawned; `attempts_omitted` (the writer's census cap, 10) is INCONCLUSIVE; every refusal names its reason (the `_WHY_*` texts). (2) **Evidence reads are bounded at 64 MiB** in `agy_hook`, `collect_v2`, `verdict_v2` and the read-audit gate (a size check before `jq` → `READ_AUDIT_GATE_INCONCLUSIVE`); over-nested JSON is unreadable evidence, never a traceback; a result file over the cap is INVALID before admission. (3) **`retry` runs the round's hook load check itself** and refuses every verdict a later attempt cannot clear (only "no invocation and no stepped row" is retried); ANOTHER entry's current attempt that was dispatched and has no audit yet is a WAIT at `retry` time and a NEW round at `collect` time; a round record with no absolute `hook_log` refuses `retry` on EVERY route. Collect reasons carry the evidence tool's own WHY and remedy. (4) **Wrappers:** every wrapper records `requested_model` (` model=<slug>` on the summary line, `requested_model` in the audit row); the custody line `read-audit-file:` / `read-audit-copy:` is percent-escaped filesystem bytes; the read audit is published atomically (temp file, fsync, `os.replace`); the agy per-attempt census gains `interrupted` (`timeout` / `signal`) and `steps_open`; the built-in server-capacity patterns include `unavailable (code 503)` (never a bare `503`). (5) **`timeout_s` is PER ATTEMPT** — the server-capacity ladder (two retries, 15 s / 45 s backoff) gives every attempt the full `--timeout`; the leg-budget rule is WITHDRAWN. (6) **Roster data:** the shipped codex entry names its model and `xhigh` reasoning explicitly; `references/review-legs.four-leg.example.json` carries the four-leg profile (three agy-route Google entries at `timeout_s` 900) plus the optional comparison entry `codex-astra`, whose difference from the baseline is a ledger observation, never a vote; the reviewer presets pin `model: claude-opus-5-5`. (7) **Recipe:** save the claude leg's LAST `SubagentHandback` `message` byte-exact when it handed back through that tool; put the test directories in `--diff-path` too; dispatch the Google entries and the codex entries one after another; restore the live roster override after `collect`. (8) The gemini route is stated as compatibility with the older gemini CLI.
#  0.38.0 (2026-09-22): DOC RESYNC onto the shared spec's `main` (the normative set landed there: PRs #1-#3, head `af5533c`) plus the gate-1 behaviour changes of that date. Four rule corrections. (1) **REVIEW web is CONDITIONAL, not absolute** — R-REVIEW-WEB makes no-web the DEFAULT; the owner may DIRECTLY request web for one named round, and it then applies to EVERY participating leg through the transient `review_web_authorized` condition and the shared `review-web-permission` clause, the operation staying a REVIEW (normal verdict, containment, accounting) with the authorization change forming a new basis. Every "REVIEW has no web, ever / on any family (D-9)" sentence is restated as the default, in rule 7, `references/leg-contracts.md` (the codex and agy dispatch shapes and the `--search` bullet). **NOT IMPLEMENTED HERE (case C32):** the vendored payload is pinned at spec `140dda4`, before the amendment — no clause, no `<review-web-policy>` placeholder, no condition — so an owner request cannot be honoured yet and the skill now says so instead of running a silent no-web round. (2) **The agy hook LOAD CHECK is a ROUND check** — `agy_hook.py check <audit> <hook-log> [<sibling-audit> ...]`, over EVERY allocated attempt of every agy-route entry (superseded attempts included); `prepare`, `retry` and the collector pass the same sibling set, and a round may carry several agy-route entries. Its counting rule is superseded by 0.38.1's attribution by conversation id. A PRESENT-but-malformed `digest.attempts` census is INCONCLUSIVE, never a smaller run count. (3) **An ENABLED entry that did not RUN is a MISSING RESULT** (`INCOMPLETE` 5) whatever its family coverage, INCLUDING one the roster SKIPPED, which is now counted and NAMED with its skip reason; the skip itself is unchanged (R-GOOGLE). `OWNER_DECISION_REQUIRED` (6) now means every enabled entry answered and fewer than three families are covered — where the owner's four-leg profile (one codex + three named Google entries) lands BY DESIGN. The shared rules did not decide the skipped-sibling case; the gap is spec `decisions/host-a-skipped-entry-outcome-gap.md`. (4) `retry` REFUSES before any mutation when the recorded attempt directory is absent. Code: `0dde61e`, `d9d7d3d`, `38e2fe1`; ledger `docs/reviews/2026-09-21-host-a-v2-gate1.md`; checklist `docs/superpowers/plans/2026-09-22-host-a-conformance-checklist.md`.
#  older entries (0.23.0-0.36.2): docs/reviews/2026-09-18-cfr-skill-history.md
---

# triad-cross-family-review

The leader's standard **final pre-merge review**: independent reviewers from
different model families — at least three, one per family — judge a
diff/branch, the suspect decisions are posed as questions, and findings drive
a fix→re-review loop. Codifies the lab's standing cross-family review rule.

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
| `references/leg-contracts.md` | dispatching entries, or weighing an agy verdict — the roster's per-vendor shapes, the Google-route chain, the producer schema projection, per-leg prompts, the agy READ-GRANT block, **the MECHANICAL read-audit gate (executable form = `lib/read_audit_gate.sh`)**, the agy read/network residual, the legacy v1 fourth leg |
| `references/packet-lifecycle.md` | opening/closing a packet dir, the per-attempt results tree, shrinking a large diff, ordering and fencing a round, or freezing it |
| `references/triage.md` | consolidating a round — release paths, REAL / REACHABLE-UNOBSERVED / SPECULATIVE, the scope-expansion gate, the residual table, the reviewer-side severity instruction |
| `references/failure-modes.md` | a round misbehaved and you want the rule that already covers it — symptom → cause → rule index |
| `references/evidence.md` | a threshold or policy looks arbitrary — latency measurements, the agy depth study, measured timeouts, origin incidents |

## Hard rules

1. **EVERY enabled roster entry reviews the round; at least three FAMILIES
   must return a valid result (R-AGREE / R-ROSTER).** The shipped roster is
   (a) a **claude fresh-eye sub-agent** via the `Agent` tool, spawned with
   `subagent_type: triad-dispatch:cross-family-review-reviewer` — the entry's `claude.agent`,
   LAYOUT-QUALIFIED by the renderer (dist → `<plugin>:<agent>` from the plugin
   manifest, dev → bare; roster DATA stays bare) so no project agent shadows
   it — the read-only reviewer whose `tools: Read, Grep, Glob` make rule 7's no-execute contract mechanical. Never the leader reasoning
   in-line: the leader holds the originating framing and shares its blind
   spot. (b) **codex** via `codex_wrapper.py` (`triad-codex-dispatch` owns the
   flag contract). (c) the **Google-family CLI**, resolved at runtime — agy
   (compatibility with the older gemini CLI exists; both share the Gemini
   backend, so exactly one serves a Google entry). Same-family-only reviewers
   inherit the leader's framing; cross-family plus fresh-eye breaks it.
   - **`acceptance` is operator DATA, not a gate rule.** No entry is
     "advisory": a leg's label (`required` / `participating` /
     `informational`) is recorded and nothing derives behaviour from it. A
     VERIFIED blocking finding — Critical / must-fix, or an unresolved open
     question — from ANY enabled entry blocks (rules 4 and 14 decide what is
     verified). A Minor-only non-SAFE verdict is agreement on the bytes plus a
     recorded verdict-selection DEVIATION row (`references/triage.md`).
   - **An ENABLED entry that did not RUN is a MISSING RESULT → `INCOMPLETE`
     (exit 5), whatever its family coverage** (R-AGREE) — one the roster
     SKIPPED (R-GOOGLE) is counted and NAMED with its skip reason, never
     hidden behind its family's entries that ran.
   - **Every entry answered but fewer than three FAMILIES →
     `OWNER_DECISION_REQUIRED` (exit 6)** — where the owner's four-leg profile
     (one codex + three named Google entries) lands by design. The valve is an
     OWNER DECISION in the ledger, never an implicit pass; two entries of one
     family are one family.
   - **Roster (the legs of a round are DATA).** The shipped default is
     `spec/review-legs.default.json` (three enabled entries, one per family);
     `<source-repo>/.claude/triad-review-legs.json` — the SOURCE repo `prepare` names as its second argument (the live checkout, never the round tree) — (schema
     `triad-review-legs.v2`) is the PROJECT override, merged BY NAME — objects
     field by field, scalars and arrays replaced. Every entry is validated
     enabled or not; an override that moves a SHIPPED entry prints a
     `WARNING:` line on stdout and is recorded in `.roster-r<N>.json`; a v1
     file is REFUSED with a pointer to `--v2`. The user-scope file is not read
     under v2 (a stderr NOTE says so when one exists). Recommended extra
     entry: the claude `high` arm `cross-family-review-reviewer-high`; Flash
     is RETIRED as a reviewer (Pro + Flash = ONE family). Four-leg profile
     (one codex + three named agy-route Google entries, `timeout_s` 900) and
     the optional comparison entry `codex-astra` (a ledger OBSERVATION, never
     a vote): `references/review-legs.four-leg.example.json`. Fields,
     per-vendor blocks, the Google chain, evidence: `references/leg-contracts.md`.
   - **Depth: xhigh-class by default; max-class only on a round the leader
     designates very-important AND algorithmically complex**, both deep legs
     escalating together. The tier is necessary but not sufficient — every leg
     also needs rule 11's adversarial framing, and rule 10's max-thinking prompt
     directive on the claude leg stays unconditional at every tier.
   - **The agy leg's read/network egress is open by design** — a deployment
     that cannot accept it runs the leg inside an external fs-scoped,
     network-denied OS sandbox.
   Everything per-leg (Google-route chain, rendered argv and prompts, agy
   READ-GRANT block, MECHANICAL read-audit gate, folded-verdict re-dispatch,
   egress evidence) is in `references/leg-contracts.md`. An agy entry's
   verdict is weighed only after `lib/read_audit_gate.sh --audit-file <attempt>/read-audit.json`
   AND the ROUND hook LOAD CHECK `lib/agy_hook.py check <abs-read-audit.json>
   <abs-hook-log.jsonl> [<abs-sibling-audit> ...]` pass (`prepare` / `retry`
   print both): every stepped census row owns a hook row under a conversation
   id no other row recorded (`HOOK_LOAD_PASS`); a row whose id list is not
   provably whole leaves every stepped row INCONCLUSIVE. CUSTODY is checked first:
   the attempt's `stderr.log` carries the whole line `read-audit-file: <path>`.
2. **Frame suspect decisions as QUESTIONS, not settled facts.** "Is X actually
   safe to omit?" — never "X is a no-op." Biased framing propagates.
3. **Every entry gets the SAME scope, through the SAME transport.** Give the
   branch ref / SHA range plus the list of suspect decisions. Every entry is
   dispatched `--cwd <round worktree>` (wrapper entries; a native claude entry gets the same path inside its rendered prompt) and opens `brief.md`,
   `diff.prod.patch`, `diff.tests.patch` and `history.txt` with its OWN read
   tools (rule 8) — never by executing `git diff` or any other subprocess
   (rule 7), which keeps leader context lean; the codex entry reads the same
   files through its read-only shell (rule 9). A diff near a context ceiling
   is shrunk with `--diff-path`, `--tests-path` and `--excerpt` (rule 8).
4. **Consolidate, don't average — the LEADER verifies, classifies, then acts.**
   Any reviewer's Critical / must-fix, or a DO-NOT-MERGE verdict, blocks merge —
   and ONLY those do: a MERGE WITH FIXES whose findings are all non-blocking
   (Minor / HARDENING-SUGGESTION) imposes no block (`references/triage.md`
   § Verdict release), and every leg prompt carries the verdict-selection rule
   so a leg with nothing blocking says SAFE outright instead of a
   Minor-only MERGE WITH FIXES.
   A block is released only by a probe that refutes the finding, a fix the
   NEXT round clears, or a recorded owner decision — the three paths are
   exhaustive and a leader-side triage never clears a block on its own. The
   leader's three consolidation duties (fact-check → classify the round
   CONVERGING / CONFLICTED / OSCILLATING → call the owner immediately on a
   CONFLICTED item or an OSCILLATING round), the two severity/triage axes, and
   the release paths in full are in `references/triage.md`. An ADMITTED
   verdict is a validated JSON object, so mapping its `findings[]` into the
   residual table is mechanical (`jq`, `references/triage.md` § Consolidating
   validated LegVerdict objects).
   **Admission (v2).** `lib/verdict_v2.py` validates each reply against the
   vendored canonical `spec/contracts/leg-verdict.schema.json` and binds it to
   the attempt that produced it through SIX ALL-OR-NOTHING flags
   (`--expected-review-id / --expected-family / --expected-packet /
   --expected-leg-name / --expected-attempt / --expected-route`) — there is no
   shape-only mode, and `--expected-packet <packet>/delivery-r<N>.md` hashes
   the delivery record itself so no digest is transcribed by hand. It REJECTS
   duplicate JSON members at the ORIGINAL text (last-wins parsing would let a
   duplicate `"verdict": "SAFE TO MERGE"` hide an earlier blocking one). Exit
   codes: 0 admitted (one `VERDICT_V2 OK … verdict="<token>"` line, the token
   quoted and LAST) / 1 shape, schema or binding failure / 2 unparseable,
   duplicate member, or a reply not starting with `{` / 3 `--end-marker`
   absent (possible TAIL LOSS) / 64 HOST fault (usage, missing `jsonschema`,
   unusable schema, refused `--admitted-out` target) — a 64 says nothing about
   the leg. The claude entry's RAW reply admits via `--admit … --end-marker
   '<END-VERDICT>' --admitted-out <attempt>/admitted.json`; no repair path,
   and an unparseable reply takes the ONE-targeted-re-ask-then-INVALID chain
   whose definitional home is `references/triage.md` § Verdict release. A
   leader-completed reply is never admissible (2026-08-30 hardening). Legacy
   v1 rounds keep `lib/validate_verdict.py` unchanged.
5. **Fix→re-review loop — NO round cap (owner directive), NO focused pass.**
   Findings → fix each (own implementer + per-fix review, SDD/TDD — the leader
   VERIFIES the findings, delegating verification to a subagent when that
   helps, and the IMPLEMENTATION whenever it keeps the leader's context lean
   at a worthwhile effort/model-cost trade) → a NEW ROUND `r<N+1>` on the
   fixed bytes. **R-REREVIEW: any change to the reviewed
   bytes or to the review conditions (roster, prompts, spec revision) is a new
   round that EVERY enabled entry reviews — a fix wave is never re-confirmed by
   a subset of legs on a subset of hunks.** A first-pass DO-NOT-MERGE
   addressed by a FIX closes only through that new round, never by the leader
   asserting it is fixed; a finding refuted by a probe closes through that
   path instead, with the probe recorded. **Non-contradicting findings that
   catch bugs or completeness gaps INSIDE the existing design are welcome at
   ANY round count** — fix them and re-review without asking; round arithmetic
   was never the problem.
   Stops: (a) **design or plan change** — a finding whose fix requires
   changing the gated plan or design (a new contract, a restructured order of
   operations, a new public def/class not in the gated design) goes to the
   OWNER before any design work starts. Accepting a review and sliding into
   over-design without that discussion is the failure this rule exists to
   prevent; (b) **convergence** — a round that produced NO fix wave, lands
   ZERO new REAL blocking findings and collects `AGREED` (exit 0) ends the
   gate, PROVIDED every prior blocking row already carries a rule-4 release
   disposition (re-confirmed fix, recorded probe, or owner decision). A round
   that DID produce a fix wave has not converged: the wave is a new basis and
   owes its own full round; (c) rule 12's contradiction stop and rule 4's
   CONFLICTED/OSCILLATING owner call, rule 14's TERMINAL exit. **Docs never gate code**: text-only
   findings are batched into one post-merge doc-resync commit and never
   trigger a round. A plan-gate fold that introduces a NEW semantic contract
   draws a fresh layer of REAL findings every round — fold the CONSTRAINTS
   and delegate the row-level design to the owning unit's own gate
   (`references/triage.md` § Scope-expansion gate). Name the non-termination to the owner rather than looping
   on autopilot. Rule 14 BOUNDS the loop's autonomy: only REAL-triaged
   findings with minimal diffs are fixed autonomously.
6. **Codex-path caveat (cross-family-rule nuance).** When the work being reviewed IS
   the codex dispatch path itself, codex reviews the *artifact diff*, not its
   own reasoning — cross-family + fresh-eye still holds, so the full set is valid.
7. **Vendor review legs: READ-only, no-mutation/no-execution, generous
   timeout.** Every leg prompt — codex / agy (and the gemini route, kept as
   compatibility with the older gemini CLI), and the claude `Agent` leg, which also enforces no-exec mechanically through its tool allowlist
   (rule 1a) — instructs the reviewer to review by READING (`git diff`, file
   reads): forbidden are file MUTATION, external-state change, and CANDIDATE
   EXECUTION (running tests/scripts/builds or the code under review, spawning
   vendor CLIs). TWO legs' directives are SCOPED to a READ-GRANT: the CODEX
   leg (read-only shell commands explicitly PERMITTED — the old blanket
   wording banned the very commands codex reads files with) and the AGY leg
   (the worktree BRIEF read FIRST, the read-audit gate's required entry, then
   verification reads across the pinned tree with file:line cites); both
   trailers are in `references/leg-contracts.md`. For both, the round's
   capture/verify integrity gate (`references/packet-lifecycle.md` § Round
   integrity) is the compensating control — mutation detection, not a
   sandbox claim alone, decides admission. For the AGY leg the containment
   is MECHANICAL since 0.35.0 (S2): the round worktree carries a PreToolUse
   hook (`lib/agy_hook.py`, written by `prepare` into
   `<worktree>/.agents/hooks.json`) that denies every tool outside the
   five-name review allow set before it runs — whatever agent
   resolved, since `--agent` fails OPEN silently; admission is EFFECT-based (a
   BLOCKED call is logged, an EXECUTED off-list call voids); and the ROUND
   hook LOAD CHECK (rule 1) must pass beside the read-audit gate before that
   leg's verdict is weighed. An agentic sandboxed reviewer otherwise
   live-runs the code under review, hangs on a real vendor API
   call, and under its read-only sandbox cannot reap the hung child — burning the
   whole timeout with no verdict. Pair the no-exec directive with a **timeout
   scaled to DIFF size × reasoning tier** — both, not either: budget
   `--timeout 1500` for a large diff at the max tier, and prefer SHRINKING the
   reviewed surface (`--diff-path`, `--tests-path`, `--excerpt`; rules 8-9)
   over raising the timeout. `timeout_s` is PER ATTEMPT: each server-capacity
   retry (up to two, 15 s / 45 s backoff) gets the full `--timeout` again, so
   size the rule-13 wait for 3 × timeout + 60 s. Avoid concurrent same-family
   pressure (429): dispatch several Google entries, and several codex
   entries, one after another. A live-run finding can still be valid —
   capture the gap, then re-dispatch read-only. Measurements: `references/evidence.md`.
   **REVIEW has no web BY DEFAULT (D-9), the only posture this host
   implements**: no `--search` on codex and no `--web` on agy (the legacy
   gemini-compatibility route's review profile also denies both web tools); web is otherwise the INVESTIGATION
   path (leader-verified brief material, never a leg verdict). The SHARED
   rule is CONDITIONAL (R-REVIEW-WEB: the owner may request web for one named
   round, for EVERY participating leg, a new basis) — **NOT IMPLEMENTED HERE
   (C32)**: say so rather than run a silent no-web round.
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
   anything). Every wrapper leg is dispatched `--cwd <worktree>` (a claude Agent leg reads the same tree from the paths in its prompt) and reads for itself
   (the legacy gemini-compatibility route is workspace-sandboxed to the repo
   and cannot read `/tmp` at all).
   **The LEADER builds the diffs** — every leg must judge the SAME bytes,
   because the binding's `content_digest` ties each verdict to that content and
   cross-family corroboration means nothing if three legs each computed their
   own diff. `--excerpt` pins a hot function INTO the brief, the mitigation
   when a diff is near the context ceiling. Before dispatching, run the
   round's `capture` (per-round evidence snapshot + canonical worktree
   fingerprint, over the ROUND WORKTREE) and FREEZE the tree; after every
   dispatched entry terminates, `verify` must print `ROUND_INTEGRITY_OK r<N>`
   before consolidation (the round-suffixed token — a NON-round label's
   qualified line says the artifact hashes were not checked and never
   satisfies this gate) and leaves `.verified-r<N>.json`, the record `close`
   reads. **Per-entry custody (v2).** Beside the worktree, `prepare --v2`
   allocates one IMMUTABLE `results-r<N>/<name>/attempt-K/` per enabled
   non-skipped entry — `binding.json`, `prompt.txt`, `dispatch.json`,
   `schema.projected.json` where the route takes one — and writes the round's
   frozen roster to `.roster-r<N>.json`; `collect` writes `collect-r<N>.json`.
   One entry plus one attempt number is ONE allocation (exclusive create): a
   retry allocates the NEXT number and never touches attempt K. Layout and
   census rules: `references/packet-lifecycle.md`. **The packet
   dir is HELPER-OWNED** (owner ruling 2026-09-17): manual manipulation beyond
   the ONE documented recovery — `references/packet-lifecycle.md` § Removing a
   stray checkout — is out of scope, and for any state it cannot name as its own
   round tree the helper REFUSES WITHOUT DELETING, states what it OBSERVES, and
   points at that section without prescribing a per-shape command; do not
   expect a runnable exit in that refusal, and do not add one. Lifecycle
   commands, the ownership fences, the fencing text, the `Review metadata:`
   block, and the capture/verify procedure: `references/packet-lifecycle.md`.
9. **codex leg: DE-INLINED — it reads the round worktree like every other leg
   (`--cwd` + READ-GRANT trailer).** The read grant is what lets it
   VERIFY claims (the historical cannot-open-a-file failure was the old
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
    downgrading a real correctness/robustness issue to Minor to dodge a fix
    loop. It is spawned mechanically read-only via the dedicated reviewer
    agent (rule 1a). Cross-check: if claude returns SAFE while a vendor entry
    returns must-fix, read that as the claude prompt under-reasoning, and
    sharpen it next round.
11. **Adversarial anti-rubber-stamp framing on EVERY leg, not just claude.** The
    rule-1 review tier is necessary but not sufficient: a leg at its deepest tier
    still rubber-stamps when the prompt only asks it to check that things look
    fine. Apply rule 10's framing (assume a defect is present; no
    severity-deflation) to the codex and agy legs too, and additionally require
    every leg to (a) ENUMERATE which criteria/rules it checked before concluding
    and (b) treat a bare "SAFE / none / faithful" verdict as a failed review
    rather than a pass. A fast, terse SAFE from any leg is a rubber-stamp signal
    → the verdict is valid, so it cannot be retried on the same basis
    (R-RETRY): prepare a NEW round with the adversarial framing sharpened; the measured threshold
    is under 60s on a diff of 100 KB or more. For the agy leg that latency
    check is SECONDARY, behind rule 1's mechanical read-audit gate (a leg the
    gate rules VOID never reaches it); for codex, which has no read-audit
    instrumentation, latency stays the primary heuristic. Criteria enumeration
    is required but is not evidence of depth (`references/evidence.md`).
12. **Non-convergence is a STOP, not another round.** The fix→re-review loop
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
    defect is a CONVERGENCE floor (two entries of one family = one leg —
    `references/triage.md`) — fix it and run the next FULL round.
    **Scope freeze (2026-08-22):** from round 3 on, a finding must cite a hunk
    of the gated diff; anything else (a pre-existing line, a neighbouring
    design, a hypothetical input shape) opens a NEW slice rather than another
    round of this one. **Two-family floor:** a single-family
    REACHABLE-UNOBSERVED item without a measured probe is a residual, not a fix.
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
    pollutes later consolidation and leg prompts. Collect once every dispatched
    entry has either returned a result or been logged terminally missing
    through that terminal path, never by silently dropping one — the collector
    counts a missing entry as `INCOMPLETE`, never as agreement.
    claude-host mechanics: the `Agent` tool runs in the background
    by default (`run_in_background` overrides per call) and fires a completion
    task-notification; a completed agent is resumed by id/name via `SendMessage`;
    wrapper legs are background Bash plus their completion notification.
    **Session-cwd pinning (probe-measured 2026-08-26):** the leader's
    foreground cwd is NOT durable across the wait — it resets to the primary
    working directory at context reinitialization, which lands exactly at
    long-leg wake-up boundaries. At every wake-up or dispatch boundary,
    RE-READ the real cwd (`pwd`) before the first repo-dependent command;
    `prepare` already prints every leg argument absolute, so dispatch its
    lines rather than rebuilding them from the memory of an earlier `cd`.
    **Retry is a SUBCOMMAND, not a hand-move.** `retry <packet> r<N> <name>
    --diagnosis "<why it failed to RUN>"` allocates attempt K+1 for an entry
    whose RECORDED attempt returned NO valid verdict, re-renders its prompt
    from the round's own frozen roster entry, and leaves attempt K intact. It
    refuses before any mutation a SKIPPED entry, an absent recorded attempt
    directory, a record with no absolute `hook_log`, and an agy hook load
    check (`retry` runs it) that a later attempt cannot clear — a NEW round;
    ANOTHER entry's dispatched attempt with no audit yet is a WAIT (retry once
    it returns; a NEW round only if it returned without one). A valid
    NEGATIVE verdict is completed work, never retried — correcting what it
    found changes the reviewed bytes, a NEW ROUND (rule 5, R-REREVIEW). Never
    hand-remove or hand-rename anything under `results-r<N>/`, never hand-move
    `agy-read-audit.json` (`prepare`/`capture` auto-rename the v1 literal to
    the round suffix), and never chain a file operation on a helper-managed
    file before a dispatch (a failed `mv &&` left a leg unlaunched). Legacy v1
    attempt names: `references/packet-lifecycle.md`.
14. **Finding triage and over-design containment (owner directive).** The loop
    structurally rewards ADDING code, so every finding is classified during
    rule-4 consolidation BEFORE it may enter the fix queue: **REAL** (demonstrated
    — repro, logged occurrence, or cited passages read side by side) →
    minimal-diff fix; **REACHABLE-UNOBSERVED** (mechanism exists, no occurrence
    evidence) → reproduce FIRST — **from REAL vendor output** (a capture, a
    run-log, an audit row): a repro that exists only in a fixture records a
    DISCLOSED residual, it does not earn code (occurrence gate,
    `references/triage.md`); a failed repro likewise becomes a DISCLOSED residual
    rather than a reclassification; **SPECULATIVE** (cannot occur in this
    deployment) → **no code**, record a DISCLOSED residual. Any fix that expands
    design scope — a new guard/fallback/retry/lock/validation layer, a new
    file/dependency/config surface, a spill beyond the finding's file, or more
    than 30 changed lines — STOPS for an explicit owner OK, even mid-round. A
    round whose remaining findings are all SPECULATIVE or repro-failed is
    TERMINAL: record the residuals and route to the owner any repro-failed
    REACHABLE item whose residual row would be BLOCKING (a SPECULATIVE item
    cannot block by definition). Every finding that is not fixed carries a row
    in the residual table; rows are updated, never deleted. The class
    definitions, the countable scope-gate thresholds, the residual-table
    schema and dispositions, and the reviewer-side severity instruction every
    prompt carries are in `references/triage.md`.
15. **Model and effort are DISPATCH-TIME DATA.** Nothing in this skill pins a
    vendor catalog slug (`~/.claude/CLAUDE.md` § Web search rules): the tiers
    a round runs at live in the roster files (`agy.model` / `agy.effort`,
    `codex.model` / `codex.reasoning`, `gemini.model` for the legacy gemini-compatibility route, `claude.agent`). **The
    TIER AND THE MODEL BOTH RIDE IN THE AGENT ID on the claude route**: they
    are frontmatter-fixed and a native `Agent` spawn names only a
    `subagent_type`, so `claude.effort` AND `claude.model` must be null and a
    different tier is a different agent file (`cross-family-review-reviewer`
    xhigh / `-max` / `-high`) — the resolver refuses either non-null value,
    exactly as it refuses `gemini.effort` (that wrapper has no `--effort`). A comparison CAMPAIGN over two
    arms of one family (when the leader declares one) gets a leader-written
    ledger at `docs/reviews/<date>-x-leg-<name>-campaign.md`; per-round
    fields: `references/triage.md` § Fourth-leg comparison record.

## Helpers (`lib/`) and vendored spec (`spec/`)

| Helper | What it owns |
|---|---|
| `lib/review_scratch.py` | packet lifecycle + `prepare --v2` + `collect` / `retry` + `capture` / `verify` / `close` |
| `lib/roster_v2.py` | defaults + project override merged by name, schema validation, capability refusals, the Google chain, the rendered dispatch per entry (`resolve <abs-worktree>` prints the resolved roster) |
| `lib/prompts_v2.py` | one prompt per entry from the VENDORED clause bytes (`spec/prompts/`), with a per-clause sha256 manifest |
| `lib/verdict_v2.py` | admission against the canonical schema + the six-field binding (rule 4) |
| `lib/collect_v2.py` | the all-entry outcome + the diagnosed retry allocation (rule 5 / Flow 5) |
| `lib/read_audit_gate.sh`, `lib/agy_hook.py` | the agy entry's mechanical read-audit gate and PreToolUse hook (rules 1 and 7) |

`spec/` holds the SHARED-SPEC payload bytes verbatim — contracts
(`leg-verdict.schema.json`, `review-legs.schema.json`, `exit-tokens.json`,
`receipt-fields.json`), prompt clauses, and the default roster — with a
sha256 per file in `spec/SPEC_MANIFEST.json`. The repo-root `SPEC_REVISION`
names the CANDIDATE commit those bytes came from: reading a candidate is
provenance, NOT adoption of a tagged revision. Never edit a payload; re-vendor
it and update the manifest. The producer projection a vendor receives
(`schema.projected.json`) and the `TRIAD_TEST_SEAMS=1` gate every seam here
requires are in `references/leg-contracts.md` § Producer schema projection —
admission always runs the FULL canonical schema, never the projection.

**Legacy v1 rounds.** A packet prepared WITHOUT `--v2` keeps the pre-0.37.0
contract unchanged: three fixed leg bodies, `validate_verdict.py` admission,
and the ADVISORY fourth-leg (X-leg) arms — `--x-leg` (repeatable) /
`--no-x-leg` (the two together refused, exit 2), the project file read as
`triad-review-legs.v1`, the user file
`$XDG_CONFIG_HOME/triad/review-legs.json`, and the DEPRECATED
`$TRIAD_REVIEW_X_LEGS` — plus `.x-legs-r<N>.json` and the `x:<name>` residual
tag. None of it applies to a `--v2` round: the roster is the only leg source
there, and `--v2` with any X-leg arm is refused (exit 2). A v1 project file
hits a v2 `prepare` as a refusal naming `--v2`, and a v2 file hits the legacy
`prepare` as a refusal naming the same flag. The v1 shapes in full:
`references/leg-contracts.md` § Fourth leg.

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
   `references/packet-lifecycle.md` § Large diff.
2. **Prepare the round with ONE deterministic command.**
   `python3 <skill>/lib/review_scratch.py prepare <packet-dir> <source-repo>
   r<N> --v2 --brief <abs-brief.md> --diff <range> [--diff-path <rel>]...
   [--tests-path <pathspec>]... [--excerpt <rel>:<start>-<end>]...
   [--prior-residual <abs-file>]` — `--diff-path` scopes the reviewed
   surface, `--tests-path` splits test churn out of the GATED patch (the
   review-is-CODE-only rule; tests = `--diff-path` scope ∩ `--tests-path`, so
   name test dirs in `--diff-path` too), `--prior-residual` fences the previous
   round's residual table into every prompt as DATA. It preserve-and-clears
   round-invariant leg outputs, creates the round WORKTREE at
   `<packet-dir>/wt-r<N>` (re-pinning REMOVES the round tree present,
   identified by its OWN name — never by the incoming label — after checking
   it against that round's record) pinned at the right-hand side of `--diff`,
   writes its four artifacts (`brief.md`, `diff.prod.patch`,
   `diff.tests.patch`, `history.txt`) FILE-TO-FILE (never streamed through
   leader context), writes `delivery-r<N>.md` + `digest-r<N>.txt`, resolves
   the ROSTER, allocates `results-r<N>/<name>/attempt-1/` per enabled
   non-skipped entry (rule 8), records `.roster-r<N>.json`, and runs the
   round's `capture` — so every byte a leg reviews sits inside the census by
   construction (`references/packet-lifecycle.md`). READ ITS STDOUT: any
   `WARNING:` line (roster drift, ONE per CHANGED FIELD — a shipped entry
   disabled, re-pointed or re-timed) comes FIRST, then one COMPLETE dispatch
   line per entry, then each `SKIPPED <name>: <reason>` and the roster NOTE.
3. **Dispatch EVERY printed entry — in parallel (rule 13), same-family entries
   one after another (rule 7) — and run the checks each entry's line printed.** Take the wrapper argv VERBATIM — it already
   carries `--sandbox read-only`, the entry's tier, `--attempt <k>`, the
   producer schema file where the route takes one, the absolute
   `--prompt-file` / `--cwd`, the timeout and the redirections into that
   attempt dir. The claude NATIVE entry is not a wrapper call: spawn `Agent`
   with the printed `subagent_type` on the CONTENT of the printed
   `prompt.txt` (max-thinking + adversarial, rule 10), then save its reply
   VERBATIM to the printed `raw.json` — its LAST `SubagentHandback` tool_use
   `message` if it handed back that way, else its last assistant text. Then
   run each printed check line: for an agy route the read-audit `gate:`
   and the `hook:` LOAD CHECK (both must pass before that entry's verdict is
   weighed or any of its findings enters the residual table), and for EVERY
   entry the `admit:` line — `verdict_v2.py … --admit` for the claude raw
   reply, `verdict_v2.py <verdict.json>` for a wrapper entry, each already
   carrying the six `--expected-*` flags including `--expected-packet
   <packet-dir>/delivery-r<N>.md`. `collect` re-runs the same admission itself; the printed `admit:` line is the EARLY per-entry check that decides a `retry` before the fold. Do not retype these commands: a hand-built
   one is how a round gets admitted against the wrong digest. Per-entry flags
   and prompts: `references/leg-contracts.md`.
4. **Once every dispatched entry has terminated, `verify` then `collect`.**
   `verify <packet-dir> <packet-dir>/wt-r<N> r<N>` must print
   `ROUND_INTEGRITY_OK r<N>` (a mismatch INVALIDATES the round: mutation
   detected, never released) and leaves `.verified-r<N>.json`. Then
   `collect <packet-dir> r<N>` folds each enabled entry's attempt AS NAMED BY THE ROUND RECORD (a HIGHER attempt directory on disk is that entry's `invalid` — an attempt this round never allocated)
   into ONE outcome, which IS the exit code:
   - **`AGREED` (0)** — every entry returned a valid affirmative-or-Minor-only
     result, three or more families covered. Proceed to Flow 5.
   - **`BLOCKED` (4)** — a valid entry carries a blocking finding or an
     unresolved OPEN QUESTION. VERIFY each against the source with a
     deterministic probe and TRIAGE it REAL / REACHABLE-UNOBSERVED /
     SPECULATIVE (rule 14); the fixes are a NEW ROUND (rule 5).
   - **`INCOMPLETE` (5)** — some enabled entry is missing or invalid, INCLUDING one the roster SKIPPED (it is counted and named with its skip reason — rule 1). A result file over 64 MiB is invalid before admission. Each non-valid entry's reason carries the evidence tool's own WHY and remedy; when it says prepare a NEW round, `retry` refuses too. Diagnose WHY it failed to RUN, then `retry <packet-dir> r<N> <name> --diagnosis "<why>"` — it PRINTS the new attempt's dispatch / gate / admit block exactly as `prepare` did; run those lines for that entry only (attempt K+1 on the unchanged basis) and dispatch the new attempt. `retry` REFUSES before any mutation in the rule-13 cases (a recorded attempt directory that is absent: restore it or re-prepare the round). A valid NEGATIVE verdict is never an `INCOMPLETE` retry, and a SKIPPED entry is settled by installing its route or disabling it in the roster, not by retrying it.
   - **`OWNER_DECISION_REQUIRED` (6)** — every enabled entry returned a valid
     result but fewer than three FAMILIES are covered (the owner's four-leg
     profile lands here by design). Call the OWNER with what is missing and
     why; there is no implicit degraded pass.
   - **`BASIS CHANGED` (2)** — the round record's frozen `contract_digest` (the ADMISSION schema every reply is judged against) is absent or no longer matches the installed contract. A changed basis is a NEW ROUND, never a re-collection (`references/triage.md` § Collect outcomes).
   - **`HOST FAULT` (64)** — THIS host cannot admit any reply (`jsonschema` absent, the vendored contract unusable in ANY way — unreadable, invalid UTF-8, non-JSON, over-nested, not Draft 2020-12) or an agy evidence tool (read-audit gate / hook check) could not RUN at all. `collect` STOPS and writes NO per-entry state: nothing about any leg is known, so repair the host and collect AGAIN — never re-dispatch paid legs over it. A contract that cannot LOAD is 64; one that loads and DIFFERS is the exit-2 basis refusal above (`references/triage.md` § Collect outcomes).
   Then run rule 4's consolidation over the collected findings: fact-check
   each against the source, and classify the round CONVERGING / CONFLICTED /
   OSCILLATING.
5. **Close the round.** Run any owed REACHABLE-UNOBSERVED repros FIRST — a
   successful repro reclassifies the item REAL and it joins the fix path.
   Then:
   - Any REAL blocking finding → fix each with a minimal diff (implementer +
     per-fix review; a design-expanding fix stops for an owner OK), then GOTO
     2 for round `r<N+1>`, which EVERY enabled entry reviews (rule 5,
     R-REREVIEW). There is no round cap and no focused pass.
   - CONFLICTED item or OSCILLATING round → call the owner instead of
     re-dispatching and hand over the rule-12 conflict table; non-conflicted
     findings may continue their fix loop meanwhile.
   - No REAL finding left and the round collected `AGREED` with no fix wave →
     the gate is done, PROVIDED no BLOCKING residual row is still `open` or
     `fix-ordered` and every rule-14 obligation is discharged (owed repros
     run; SPECULATIVE / UNKNOWN-CONTEXT residuals recorded — a non-blocking
     row needs recording, not an owner decision; every REAL finding either
     fixed or carrying a row, so a REAL Minor never silently disappears).
     A round whose remaining findings are all SPECULATIVE or repro-failed is
     TERMINAL: record the DISCLOSED residuals and hand the merge decision to
     the owner when any residual row is BLOCKING. Do not GOTO 2.
   Restore a per-round live roster override once `collect` has run (the round
   reads its frozen `.roster-r<N>.json`). Copy the COMPLETE residual table to
   `docs/reviews/<UTC-date>-<slug>-residuals.md` BEFORE `close <packet-dir>` —
   close DELETES the dir. Close removes the round worktree first, refuses
   rather than forcing if a leg wrote into the reviewed tree, WARNS when the
   last captured round carries no `.verified-r<N>.json`, and a SECOND close
   of the same (now absent) dir is a no-op at rc 0.

## Failure modes

Symptom → cause → the rule that owns the fix: `references/failure-modes.md`.
It is an index, not a second statement of the rules.

## Why this exists

A same-family review chain shares the leader's blind spot, and a strict per-task
same-family review still misses cross-cutting issues. The originating incident
and the re-validation are in `references/evidence.md`.

## Related

- `triad-codex-dispatch` (codex leg) / `triad-antigravity-dispatch` (the Google-family leg) / `triad-gemini-dispatch` (compatibility with the older gemini CLI) — those SKILLs own the wrapper flag contracts this skill's rendered argv uses.
- `superpowers:subagent-driven-development` — the per-task (same-family) review this final pass backstops.
- `superpowers:requesting-code-review` / `superpowers:receiving-code-review` — single-reviewer code-review conventions.
