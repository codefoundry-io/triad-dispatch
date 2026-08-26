---
name: triad-cross-family-review
description: Runs the FINAL pre-merge (or review-worthy / security-or-correctness-critical) cross-family review mandated by the lab's cross-family review rule — dispatches INDEPENDENT cross-family reviewers (a claude fresh-eye sub-agent via Agent + codex via triad-codex-dispatch + the Google-family CLI selected at runtime, agy via triad-antigravity-dispatch or gemini via triad-gemini-dispatch), frames the suspect/omitted/simplified decisions as QUESTIONS, consolidates their verdicts (SAFE TO MERGE / MERGE WITH FIXES / DO NOT MERGE), then runs a fix→re-confirm loop until the gating legs are unanimously SAFE (a MERGE WITH FIXES carrying only non-blocking findings satisfies the gate). Trigger when about to merge review-worthy work, ESPECIALLY when the leader chose to OMIT or SIMPLIFY something from a vetted source, or after a subagent-driven implementation before integration.
version: 0.28.1
# changelog:
#   0.28.1 (2026-08-26): doc-only — rule 13 gains the session-cwd-pinning
#     project_f40_residual_discharge_merged_2026_08_19): the leader's cwd
#     resets to the primary working directory at context reinitialization
#     (probe-measured 2026-08-26 — tied to reinit, NOT to background
#     dispatch itself), which lands at long-leg wake-up boundaries; at every
#     wake-up/dispatch boundary re-read the real cwd (`pwd`) and build leg
#     args absolute at dispatch time. references/leg-contracts.md: the agy
#     leg's `--cwd` caller obligation stated (symmetric with the codex leg's
#     rule-9 READ-GRANT duty; audit census 211/421 grant-less pre-fix
#     dispatches on 2026-08-22). No flow/contract change.
#   0.28.0 (2026-08-22): GATE STOP RULES + agy leg v2. Rules 5 / 12 / 14 now
#     carry the countable stop rules the three-family consultation proposed
#     after the 9-round v1.2 gate: a 3-full-round cap (a 4th needs an owner
#     re-budget citing a NEW defect observed in real output), the occurrence
#     gate (REACHABLE-UNOBSERVED becomes code only from REAL vendor output; a
#     fixture-only repro is a residual), convergence on a round with zero new
#     REAL must-fix (then ONE hunk-scoped focused re-confirm), docs never gate
#     code (batched post-merge), scope freeze after round 2, two-family floor
#     for single-family REACHABLE items. agy leg: the wrapper's read-only
#     path v2 (setup-once allowlist agents, --add-dir, no danger flag / deny
#     transaction; a status=ERROR run with a valid bound verdict and a clean
#     census is ADMITTED) — leg-contracts resynced, READ-GRANT block
#     regenerated from the template.
#   0.27.4 (2026-08-22): agy leg = tools-allowlisted custom agent + EXISTENCE
#     pin. (a) The wrapper's `--sandbox read-only` now dispatches agy as the
#     `triad-readonly-review` custom primary agent (no shell/write/MCP/browser
#     tool; v1.2: the settings deny transaction and the headless auto-approve
#     flag are RETAINED as belt + read-tool approval, agy --sandbox is
#     dropped) — the 2026-08-22 permission-ladder spike measured
#     every deny/ask shape ending status=ERROR on ONE denied step while the
#     allowlist ends SUCCESS; the rendered READ-GRANT now says "you have NO
#     shell tool" instead of the retired "cat is deny-listed" line, and the
#     agy-leg bullets in leg-contracts.md replace the agy-1.1.8-era "prompt
#     is the only per-call carrier" sentence (3-family cross-check finding).
#     (b) EXISTENCE pin: the READ-GRANT forbids opening paths that do not
#     exist (plan-stage NEW/planned files) — upstream #826 kills the turn at
#     permission-conversion; the ContentOffset clause's rationale is
#     corrected (valid arg; the failure is paging past EOF). Pinned by
#     tests/unit/skills/t4-prepare.sh. Ledger: docs/agy-vendor-workarounds.md.
#   0.27.0 (2026-08-13): agy read-audit gate -> ONE executable lib helper
#     (owner approval; backlog record 2026-08-07 — the leader re-typed the
#     canonical jq block inline once per round, ~6x/gate observed). NEW
#     `lib/read_audit_gate.sh <abs-packet-dir> <abs-packet-file>...`:
#     digest path DERIVED as the shared "$PACKET_DIR/agy-read-audit.json"
#     literal (J1 anti-drift, no env fallback), exit 0 PASS / 2 ABSENT /
#     3 VOID / 4 INCONCLUSIVE / 64 usage (a nonexistent packet-file arg
#     fails LOUD instead of false-VOIDing on a stale name), greppable
#     READ_AUDIT_GATE_<VERDICT> summary line (+' unevaluated=<n>' when
#     some argument was not evaluated), symlinked-digest check-then-open
#     refusal (weaker than validate_verdict.py's O_NOFOLLOW read;
#     compensated by the gate running strictly post-reap on a path only
#     the wrapper writes). Gate-review waves (3-family, ledger
#     docs/reviews/2026-08-13-read-audit-helper-residuals.md): OVER-CAP
#     packet paths (>=200 chars, -ge) refused INCONCLUSIVE — a capped digest
#     stores only a prefix-identity, indistinguishable from any
#     same-prefix file incl. a stale prior-round packet (2-family
#     convergence; -ge boundary — an exactly-cap value could be a longer
#     path's truncation) — and the jq match TOOL+KEY-RESTRICTED to
#     view_file.AbsolutePath (a grep_search whose Query VALUE equals the
#     packet path is reference, not a read — live-corroborated; a
#     non-view_file entry carrying AbsolutePath is refused too); bash-4+
#     POLICY-floor guard (a 3.x death would alias exit 2 = ABSENT).
#     leg-contracts.md § agy read-audit gate keeps the SPEC and points at
#     the helper; the canonical liftable jq block now lives ONLY in the
#     helper (t41/f9 lift from it; t5-read-audit-gate.sh owns the CLI
#     contract; export ships lib/*.sh next to lib/*.py).
#   0.26.0 (2026-08-11): FU10-gate lessons — verdict-inflation fix +
#     deterministic round preparation. (1) BUG-1: the verdict-selection
#     rule ("verdict tracks the BLOCKING axis — zero Critical/must-fix
#     => SAFE TO MERGE even with Minor/HARDENING-SUGGESTION findings")
#     now rides EVERY leg prompt: stated in triage.md § Reviewer-side
#     instruction and baked into the rendered templates. Across the
#     21-verdict FU10 plan gate no leg ever returned SAFE+Minor although
#     the schema permits it (spike-confirmed through binding admission),
#     which alone made a literal unanimous SAFE unreachable. (2) Flow 4
#     and Hard rule 4 restate the non-blocking-MWF carve-out INLINE (the
#     literal-SAFE misread cost an owner call at FU10). (3) triage.md
#     § Loop exit codifies the self-recording-target non-convergence
#     pattern + the mechanical-census remedy. (4) NEW review_scratch.py
#     `prepare` subcommand (owner directive — token discipline): the
#     leader authors ONE brief (context / =====QUESTIONS===== marker /
#     questions) and NAMES evidence (--file/--diff/--excerpt); the tool
#     assembles packet-r<N>.md canonically FILE-TO-FILE, writes
#     digest-r<N>.txt, renders all three round-suffixed leg bodies
#     (binding lines + per-leg READ-GRANT + severity instruction +
#     verdict-selection rule), auto-preserves round-invariant leg
#     outputs (agy-read-audit.json -> -r<N-1>; capture too), then
#     captures — replacing the manual per-round assembly that burned
#     leader context and produced the FU10 fold-edit slips. codex/agy
#     dispatch via --prompt-file on the rendered bodies. (5) claude-leg
#     reply HTML-escape transcription caveat (de-escape before
#     admission). Tests: tests/unit/skills/t4-prepare.sh (22 axes);
#     verdict_schema.py findings comment made explicitly bidirectional.
#     This version itself passed a THREE-ROUND 3-family gate, every
#     round PREPARED BY the new subcommand (dogfood). r1 (3x MWF, 25
#     findings) landed: severity instruction restored to the full
#     triage.md SoT text (3-family convergence — the condensed template
#     had dropped the untrusted-input scope / anti-over-hardening /
#     may-challenge clauses, the BUG-1 defect class reintroduced inside
#     BUG-1's own fix) + a t4 drift-guard axis pinning template<->doc
#     clauses both directions; a DO-NOT-MERGE clause (a must-not-merge
#     judgment is itself a blocking finding); review_id validated
#     against the LegVerdict contract at prepare time; preserve suffix
#     derived from the latest captured snapshot (true provenance) with
#     os.link no-clobber; fence-set + QUESTIONS-marker refusal over all
#     embedded content; dir_fd O_NOFOLLOW component chain for
#     --file/--excerpt; capture-refusal prechecks +
#     render-all-before-write; post-capture embedded-source recheck
#     (embed-vs-capture TOCTOU). r2 (codex MWF 1C+3m; claude SAFE+5m —
#     the FIRST SAFE-with-Minors composition, the BUG-1 fix observed
#     working live; agy MWF) landed: fence scan moved to
#     str.splitlines() (full boundary set incl. VT/FF/FS/GS/RS); brief
#     refuses alternate line separators outright; path guard also
#     rejects NEL/U+2028/U+2029 + empty paths; readability
#     open/close-probe on untracked + packet-dir files; --diff-path
#     disk-or-HEAD existence gate (git exits 0 on a no-match pathspec —
#     probe-confirmed); untracked-omission stderr NOTE; agy binding line
#     above the READ-GRANT. r3 (codex SAFE+2m, claude SAFE+3m, agy
#     SAFE(0) — gate CLOSED): pathspec gate gained a per-spec range-diff
#     third arm; in-scope untracked WARNING with repr()-escaped names;
#     unborn-HEAD precheck. Slice bundling (verdict policy + prepare
#     subsystem in one gate) = accepted residual per the owner's
#     explicit same-session bundle order; ledger =
#     docs/reviews/2026-08-11-skill-0260-gate-residuals.md.
#   0.25.10 (2026-08-11): codex-host 0.2.533 adoption — CLOSED (owner
#     decision C). ADOPTED and solid: LegVerdict round/leg BINDING
#     (review_id/family/content_digest, REQUIRED) + bidirectional SAFE
#     validator (SAFE must not carry Critical/must-fix; Minor/HS may) +
#     strict/forbid + POSIX finding paths, admitted via
#     validate_verdict.py --expected-review-id/--expected-family/
#     --expected-packet (all-or-nothing; digest recomputed from the
#     packet file); mechanized round integrity (review_scratch.py
#     capture/verify — per-round evidence snapshot + git-config-
#     independent worktree fingerprint incl. index-flag/uncovered-file
#     guards, ROUND_INTEGRITY_OK); codex AND agy READ-GRANT (packet read
#     FIRST, then repo verification reads; mutation denied + capture/
#     verify belt); Review-metadata packet head + per-round excerpt
#     policy + per-round digest-r<N> / agy-read-audit-r<N> naming. The
#     schema-repair-retry "severity laundering" channel was hardened
#     across a fix loop and STOPPED at round 9 (rule 12): a detection
#     probe does not converge over the adversarial JSON-encoding space,
#     and the path fired ZERO times in 18 real dispatches (all valid
#     JSON), so per owner decision C the realistic cooperative-model
#     failure is closed (marker-skip + content probe + a canonical
#     json.dumps regex backstop, terminating for the parseable space)
#     and three residuals are ACCEPTED/disclosed: the trigger token is a
#     non-authoritative hint (authority = the run-log structured
#     payload), unparseable escape-spelled content stays fail-open, and
#     the content-agnostic class-close (run-log on every retried call +
#     leader attempt-1 inspection) is a recorded FUTURE option. Declined
#     from the reference: severity/verdict token collapse, context_known
#     removal, round-scoped invalidation, no-schema-repair sentinel.
#     Full gate ledger + round-by-round history:
#     docs/reviews/2026-08-10-adopt-02533-gate-STATE.md + git log. This
#     version also folds a skill-prompt-review polish (obligation-4
#     discriminator reconciled to one source, provenance dates stripped
#     from rule bodies, changelog pruned to the file's own convention).
#   0.24.0-0.24.2 (2026-08-01): all three legs share ONE pydantic verdict
#     schema (verdict_schema.py LegVerdict/LegFinding); codex/agy via
#     native --output-schema / --json-schema, claude via its prompt's
#     output contract + the deterministic lib/validate_verdict.py; the
#     leader consolidates validated objects (references/triage.md § jq)
#     instead of reshaping three legs' prose. (Binding admission
#     superseded by 0.25.10; interim re-confirm fixes in git log.)
#   0.23.0 (2026-08-01): body split into one-level references/ after an
#     overlap/dead-content audit + a tone/provenance de-scope pass — the
#     body now carries frontmatter, when-to-use, a Contents map, the hard
#     rules stated ONCE, and the Flow; per-leg contracts, packet
#     lifecycle, triage machinery and measurement evidence moved to
#     references/. No contract changed meaning. (Older entries: git log.)
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
   prompt requirements, the agy READ-GRANT block, the MECHANICAL read-audit gate
   (run `lib/read_audit_gate.sh` before weighing that leg's verdict and before
   any agy finding enters the residual table), the folded-verdict re-dispatch,
   and the egress residual's evidence — is in `references/leg-contracts.md`.
2. **Frame suspect decisions as QUESTIONS, not settled facts.** "Is X actually
   safe to omit?" — never "X is a no-op." A biased framing propagates into the
   reviewers and defeats the purpose.
3. **Each reviewer gets the diff scope; the transport differs per leg — state it
   once here.** Give the branch ref / SHA range plus the list of suspect
   decisions. The READING legs (claude `Agent`, agy, gemini) open the packet with
   their OWN READ tools rather than by executing `git diff` or any other
   subprocess (rule 7), which keeps leader context lean; the **codex leg is
   always inlined** into `--prompt` (its guaranteed view; it ALSO gets
   `--cwd` + a READ-GRANT for verification reads — rule 9). For a LARGE packet
   the leader pre-assembles ONE focused file: the reading legs open only that
   file, and codex receives the same focused content inlined (rule 8).
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
   admission), `--expected-packet` recomputes the digest from the packet
   file itself — and a binding mismatch is
   the INVALID-leg handling, never a pass
   (`references/leg-contracts.md` § Verdict binding).
5. **Fix→re-confirm loop with a COUNTABLE cap (owner directive 2026-08-22,
   after the 9-round v1.2 agy gate).** Findings → fix each (own implementer +
   per-fix review) → re-confirm on the fixed branch. A first-pass DO-NOT-MERGE
   addressed by a FIX closes only through a re-confirm pass, never by the
   leader asserting it is fixed; a finding refuted by a probe closes through
   that path instead, with the probe recorded. Stops: (a) **round cap** — at
   most THREE full-family rounds per gate (initial, fix re-confirm, final
   re-confirm); a fourth needs an owner re-budget citing a NEW defect observed
   in real output, never "one more round"; (b) **convergence** — a round with
   zero NEW REAL must-fix findings ends the gate: if that round produced a
   fix wave, apply it and run ONE focused re-confirm scoped to the wave's
   hunks — the two GATING legs (codex + claude) at minimum, agy optional;
   this focused pass is NOT a full round and does not count against the cap
   — a clean round with no wave skips the focused pass; then merge, PROVIDED every prior
   blocking row already carries a rule-4 release disposition (re-confirmed
   fix, recorded probe, or owner decision); (c) rule 12's non-convergence stop, rule 4's CONFLICTED/OSCILLATING
   owner call, rule 14's TERMINAL exit. **Docs never gate code**: text-only
   findings are batched into one post-merge doc-resync commit and never
   trigger a round. Name the non-termination to the owner rather than looping
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
   `references/leg-contracts.md` § codex leg) and the AGY leg (packet read
   FIRST, still the mechanical read-audit gate's required entry, then repo
   verification reads via its file-view tool with file:line cites;
   `references/leg-contracts.md` § agy leg). For both, the round's
   capture/verify integrity gate (`references/packet-lifecycle.md` § Round
   integrity) is the compensating control — mutation detection, not a
   sandbox claim alone, decides admission. An agentic sandboxed
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
   immediately before that closing instruction. Before dispatching, run the
   round's `capture` (per-round evidence snapshot + canonical worktree
   fingerprint — `lib/review_scratch.py capture`) and
   FREEZE the tree; after every required leg terminates, `verify` must print
   `ROUND_INTEGRITY_OK` before consolidation. Lifecycle commands, the
   ownership fences, the fencing text, the `Review metadata:` block, and the
   capture/verify procedure: `references/packet-lifecycle.md`.
9. **codex leg: INLINE the packet into `--prompt` AND grant read-only repo
   access (`--cwd` + READ-GRANT trailer).** The
   inlined packet stays the leg's guaranteed view; the read grant restores its
   ability to VERIFY claims against the repo (the historical
   cannot-open-a-file failure was the old blanket no-exec directive, not the
   sandbox — reads were never sandbox-blocked, writes still are). The revised
   contract, its trailer text, the rescoped fast-SAFE heuristic, the call-site
   substitution shape, the single-quoted-heredoc pitfall
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

## Flow

1. Scope the review: branch ref + base SHA + the list of suspect/omitted/
   simplified decisions (phrased as questions). Open the packet dir with the
   rule-8 helper (`python3 <skill>/lib/review_scratch.py open <abs>/_runs/review
   <slug>`, which also prunes stale packets from crashed past reviews). Author
   the round's BRIEF — deployment context above one `=====QUESTIONS=====`
   marker line, the suspect questions below it — as a standalone file; that
   brief is the ONLY per-round text the leader writes. Keep the packet
   FOCUSED: for a LARGE diff name only the high-risk subset (a narrowed
   `--diff` range, `--excerpt` hot functions, `--file` load-bearing
   documents) — `references/packet-lifecycle.md` § Large packet. At review
   end, `… close <packet-dir>`.
2. Prepare the round with ONE deterministic command:
   `python3 <skill>/lib/review_scratch.py prepare <packet-dir>
   <worktree-root> r<N> --brief <abs-brief.md> [--file <rel>]...
   [--diff <range>] [--diff-path <rel>]...
   [--excerpt <rel>:<start>-<end>]...` — `--diff-path` pathspecs keep a
   working-tree `--diff` inside the packet-is-CODE-only rule (no
   test/catalog churn). It
   preserve-and-clears round-invariant leg outputs (`agy-read-audit.json`
   → its PRODUCING round's suffixed name, derived from the latest
   captured snapshot), assembles `packet-r<N>.md` in the
   canonical order with every diff/file/excerpt byte moved FILE-TO-FILE
   (never streamed through leader context), writes `digest-r<N>.txt`,
   renders the three round-suffixed leg bodies (`codex-body-r<N>.txt`
   inlines the packet; `agy-prompt-r<N>.txt` / `claude-prompt-r<N>.txt`
   point at it) carrying the binding values, the per-leg READ-GRANT, and
   the verdict-selection rule, and runs the round's `capture` (evidence
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
3. Once every required leg has terminated, run `verify` for the round — it
   must print `ROUND_INTEGRITY_OK r<N>` (a mismatch INVALIDATES the round:
   mutation detected, never released) — validate every leg's JSON with
   `lib/validate_verdict.py --expected-*` (rule 4's binding admission), then
   collect the three verdicts + findings and run rule 4's consolidation:
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
   re-confirm within rule 5's three-round cap (a zero-new-REAL-must-fix round
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
