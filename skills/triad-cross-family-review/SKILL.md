---
name: triad-cross-family-review
description: Use for the FINAL pre-merge (or review-worthy / security-or-correctness-critical) cross-family review mandated by the lab's cross-family review rule — dispatch INDEPENDENT cross-family reviewers (a claude fresh-eye sub-agent via Agent + codex via triad-codex-dispatch + the Google-family CLI selected at runtime, agy via triad-antigravity-dispatch or gemini via triad-gemini-dispatch), frame the suspect/omitted/simplified decisions as QUESTIONS, consolidate their verdicts (SAFE TO MERGE / MERGE WITH FIXES / DO NOT MERGE), then run a fix→re-confirm loop until unanimous SAFE. Trigger when about to merge review-worthy work, ESPECIALLY when the leader chose to OMIT or SIMPLIFY something from a vetted source, or after a subagent-driven implementation before integration.
version: 0.12.0
# changelog:
#   0.12.0 (2026-07-11): codex leg tracks the codex reasoning catalog — top tier
#     bumped xhigh → max. `codex debug models` (0.144.x) exposes low/medium/high/
#     xhigh/max on ALL gpt-5.6-* variants, plus ultra on sol/terra only (the volume
#     variant caps at max); the wrapper exposes up to max (universal). ultra is NOT
#     used — max reasoning + automatic subagent delegation → runaway single-shot,
#     and it is not universal. Fallback ladder max → xhigh → high.
#   0.11.0 (2026-07-10): 9-lens gate round-1 fixes — TRIAD_GOOGLE_REVIEW_CLI
#     normalization (antigravity alias accepted), shallow-fallback Google leg is
#     ADVISORY for the merge gate + degraded 2-family mode needs an owner decision
#     (aligns with the codex-host edition's release gate), gemini-leg depth bullet
#     added, cost note scoped to the Gemini thinking tier, claude-leg model set via
#     the Agent model parameter, provenance dates moved out of rule bodies.
#   0.10.0 (2026-07-09): adversarial anti-rubber-stamp framing generalized to EVERY
#     leg (rule 11) — MAX reasoning tier alone does not stop a rubber-stamp. A codex
#     leg at its top (xhigh) tier returned a bare "faithful/none" that missed a real
#     defect; the same packet with only adversarial framing added surfaced 2 real
#     defects. The framing, not the tier, was the gap.
#   0.9.0 (2026-06-26): large-packet file-IPC rule — for a LARGE diff/multi-doc
#     review the leader PRE-ASSEMBLES a focused packet file; the agy/gemini leg
#     reads only that (never self-assembles git-diff + N files → wall-time timeout);
#     codex inlines the same focused subset. Rules 3/8/9 + Flow + Failure-modes row.
#     Origin: 2026-06-26 large-packet-timeout (3 reviews, agy timed out ~790s
#     self-assembling; same content pre-assembled completed ~190-250s).
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

## Hard rules

1. **INDEPENDENT cross-family reviewers.** (a) a **claude fresh-eye sub-agent**
   dispatched via the `Agent` tool (NOT the leader reasoning in-line — the
   leader holds the originating framing and shares its blind spot), (b) **codex**
   via `triad-codex-dispatch`, (c) the **Google-family CLI**, selected at
   runtime. agy and gemini share the Gemini backend (same family), so exactly
   ONE is the Google-family leg. Select it deterministically (no AI):

   ```bash
   GOOGLE_CLI="${TRIAD_GOOGLE_REVIEW_CLI:-}"          # explicit pin wins
   case "$GOOGLE_CLI" in
     antigravity) GOOGLE_CLI=agy ;;                   # accepted alias
     agy|gemini|"") ;;                                # valid values
     *) echo "[review] unknown TRIAD_GOOGLE_REVIEW_CLI='$GOOGLE_CLI' — ignoring the pin" >&2
        GOOGLE_CLI="" ;;
   esac
   if [ -n "$GOOGLE_CLI" ] && ! command -v "$GOOGLE_CLI" >/dev/null 2>&1; then
     echo "[review] pinned '$GOOGLE_CLI' not installed — falling through to auto-detect" >&2
     GOOGLE_CLI=""
   fi
   if [ -z "$GOOGLE_CLI" ]; then
     if command -v agy >/dev/null 2>&1; then GOOGLE_CLI=agy        # agy-first
     elif command -v gemini >/dev/null 2>&1; then GOOGLE_CLI=gemini # fallback
     else GOOGLE_CLI=""; fi                                         # neither
   fi
   # REASONING TIER (a review-only override of the no-model-pin rule): the agy/gemini
   # DEFAULT is a fast shallow model (Gemini Flash class) — empirically useless for
   # adversarial review, where it finds nothing the deeper tier catches. agy encodes
   # reasoning in the MODEL VARIANT (there is NO --reasoning flag; the separate
   # thinkingLevel param is stripped/buggy — antigravity issue #1675), so force the
   # Pro/High variant via --model. Env-overridable; verify it still exists (Google
   # renames tiers) and fall back to the default + log if absent.
   GOOGLE_REVIEW_MODEL="${TRIAD_GOOGLE_REVIEW_MODEL:-}"
   if [ "$GOOGLE_CLI" = agy ] && [ -z "$GOOGLE_REVIEW_MODEL" ]; then
     GOOGLE_REVIEW_MODEL="Gemini 3.1 Pro (High)"   # verified default for the agy leg ONLY;
   fi                                              # the gemini path stays unpinned unless configured
   if [ "$GOOGLE_CLI" = agy ] && ! agy models 2>/dev/null | grep -qxF "$GOOGLE_REVIEW_MODEL"; then
     echo "[review] '$GOOGLE_REVIEW_MODEL' not in 'agy models' — falling back to agy default; Google leg is ADVISORY this round" >&2
     GOOGLE_REVIEW_MODEL=""
   fi
   ```

   `agy` → `triad-antigravity-dispatch`; `gemini` → `triad-gemini-dispatch`;
   empty → **skip the Google leg and log** "Google-family reviewer unavailable;
   review proceeds with claude(Agent)+codex (2-family)". Normally THREE
   reviewers; degrades to two (claude+codex) only when neither Google CLI is
   installed. A Google leg that fell back to the shallow default tier (the
   model-verify above) is ADVISORY: its findings count, but its SAFE does NOT
   satisfy the unanimous merge gate — for gating, treat that round as the
   degraded two-family mode. Degraded mode itself is advisory for a MERGE
   decision: record an explicit owner decision before merging on fewer than
   three families. Same-family-only reviewers
   inherit the leader's framing; cross-family + fresh-eye is what breaks the
   monoculture.

   **MAX reasoning on EVERY leg.** The pre-merge
   gate is high-stakes, so each reviewer runs at its family's TOP reasoning tier
   — a shallow reviewer rubber-stamps. The tier is necessary but NOT sufficient:
   every leg ALSO needs rule 11's adversarial anti-rubber-stamp framing (a leg at its
   top tier still rubber-stamps when merely asked to "check if this looks fine"):
   - **agy (Google leg):** when `GOOGLE_REVIEW_MODEL` is non-empty, the dispatch
     MUST pass `--model "$GOOGLE_REVIEW_MODEL"` to `antigravity_wrapper.py` (the
     Pro/High variant — agy encodes reasoning in the model variant, no `--reasoning`
     flag; the wrapper pins nothing by default).
   - **gemini (when it is the selected Google leg):** pass an owner-verified
     `TRIAD_GOOGLE_REVIEW_MODEL` to `gemini_wrapper.py --model` when configured;
     otherwise run the CLI default and log that the review tier is unpinned — an
     unpinned-default gemini leg is ADVISORY for gating, like the agy fallback
     above.
   - **codex:** `--reasoning max` — the wrapper's MAX tier (`codex debug models`
     lists `low/medium/high/xhigh/max/ultra`; the wrapper exposes up to `max`, the
     deepest non-delegating tier — so the codex leg reviews at full depth, not a
     shallow rubber-stamp). `ultra` is NOT used — it self-delegates subagents
     (runaway/over-long) and not every model variant supports it. Plus `--search`
     (live web-grounding; see rule 9 example). If a future codex CLI rejects `max`,
     fall back to `xhigh` → `high` + log.
   - **claude fresh-eye `Agent`:** the strongest available Claude tier (set it via
     the `Agent` tool's model parameter where the harness exposes one) + an
     explicit **max-thinking** directive in
     the prompt ("Think as hard as you can / ultrathink before answering"). The
     `Agent` tool exposes no effort flag, so beyond model choice the depth lever is the PROMPT —
     instruct deep, adversarial reasoning (rule 10). Without it the claude leg
     under-reasons and rubber-stamps.
   Cost note: the Gemini thinking tier is API-billed (not subscription-covered);
   the codex/claude deep tiers draw down their subscription budgets faster.
   Acceptable for the high-stakes pre-merge gate; keep cheap single-shot
   dispatches on the defaults per the no-model-pin rule.
2. **Frame suspect decisions as QUESTIONS, not settled facts.** "Is X actually
   safe to omit?" — never "X is a no-op." A biased framing propagates into the
   reviewers and defeats the purpose.
3. **Each reviewer gets the diff scope + reads it themselves.** Give the branch
   ref / SHA range + the list of suspect decisions; let each reviewer run
   `git diff` and read files with its OWN tools (keeps leader context lean).
   EXCEPTION for a LARGE packet (rule 8): a workspace-sandboxed vendor leg must
   NOT self-assemble a large diff / multi-file packet — the leader pre-assembles
   a focused packet file and the leg reads only that. Self-read-themselves applies
   to small/focused reviews; large ones are leader-pre-assembled.
4. **Consolidate, don't average.** ANY reviewer's Critical / must-fix or a
   DO-NOT-MERGE verdict blocks merge. Cross-family complementarity is the
   point: one may catch what the others miss — each family tends to catch a
   different class of issue (an extractor bug, a classifier false-positive, a
   config/safety gap), with little overlap.
5. **Fix→re-confirm loop, with a round budget.** Findings → fix each (own
   implementer + per-fix review) → RE-RUN the 3-way on the fixed branch. A
   first-pass DO-NOT-MERGE is only closed by a re-confirm pass, not by the
   leader asserting it's fixed. Stop after `TRIAD_REVIEW_MAX_ROUNDS` (default 2)
   full rounds: record the remaining findings and get an owner decision instead
   of looping (matches the codex-host edition's circuit breaker).
6. **Codex-path caveat (cross-family-rule nuance).** When the work being reviewed IS
   the codex dispatch path itself, codex reviews the *artifact diff* (e.g.
   Python), not its own reasoning — cross-family + fresh-eye still holds, so
   the full 3-way is valid. Use judgment; when in doubt, keep all three.
7. **Vendor review legs: READ-only, no-exec, generous timeout.** Every vendor
   leg prompt (codex / agy / gemini — and the claude `Agent` leg too) MUST
   instruct the reviewer to review by **READING** (`git diff`, file reads) only:
   "Do NOT run scripts/tests or spawn subprocesses / vendor CLIs." An agentic
   sandboxed reviewer will otherwise live-run the code under review, hang on a
   real vendor API call, and — under its read-only sandbox — be unable to reap
   the hung child, burning the whole timeout with no verdict. Pair the no-exec
   directive with a **generous timeout** (e.g. codex 850-900s) — both, not
   either. Also avoid concurrent same-family API pressure: don't run the gemini
   leg while another leg may also call gemini (429). A live-run finding can
   still be valid (it surfaces real robustness gaps) — capture the gap, then
   re-dispatch read-only. See the lab's recorded incident log (a codex leg that
   live-ran the code under review hung on a real vendor call and burned the whole
   timeout with no verdict; the no-exec directive let the same review finish quickly).
8. **Vendor-leg context files go at a repo-relative gitignored path, never
   `/tmp`.** gemini and agy are **workspace-sandboxed to the repo** — a brief /
   diff / context file handed to them at `/tmp/...` is unreadable (gemini errors
   `Path not in workspace: "/tmp" resolves outside the allowed workspace`; agy
   the same). Put any review-context file at a repo-relative gitignored location
   — a repo-relative gitignored path, e.g. a plain `_shared/<name>.md`
   (`_shared/` `_runs/` `_logs/` are gitignored) —
   so every leg (codex reads it fine too) can `Read` it. The claude `Agent` leg is
   NOT workspace-sandboxed, so it can read `/tmp`; do not rely on that for the
   vendor legs. Clean up the context file after the review (it is itself an IPC
   artifact).

   **LARGE packet → PRE-ASSEMBLE one focused file; the vendor leg reads ONLY
   that, never self-assembles.** When the review's expected packet is LARGE — a big diff (e.g.
   >~1000 changed lines or many files) or a multi-document review (an ADS + a
   big JSON + a design doc) — the leader MUST PRE-ASSEMBLE the packet into ONE
   focused file and instruct the agy/gemini leg to read THAT ONE file (its
   `view_file` on the repo-relative gitignored path) and NOTHING else. NEVER tell
   the vendor leg to self-assemble — i.e. to run `git diff <range>` on a large
   diff itself, or to read N context/interface/mock files itself. A
   workspace-sandboxed leg that self-assembles spends its whole wall-time budget
   reading + stitching the packet and hits its print-timeout → timeout /
   extraction-error with NO verdict (pair this with the rule-7 generous timeout,
   not instead of it). The pre-assembled packet = the rule-2 framing + the
   FOCUSED / high-risk subset of the diff — NOT the whole tree: sample the
   repetitive parts, keep the high-risk files whole. A workspace-sandboxed leg
   told to self-assemble a large packet has timed out (~13 min) where the same
   content, pre-assembled, finished in a few minutes — matching codex (see the
   changelog).
9. **codex leg: INLINE the packet into `--prompt`; never hand it only a file
   path.** Rule 8 places a context FILE for legs that `Read` one, but a codex leg
   under `--sandbox read-only` + the rule-7 no-exec directive may be unable to
   open a handed-over file AT ALL (it has no shell to `cat` and its file-read
   route can silently come back empty — "non-CLI file access routes did not
   expose the files"), returning no verdict. The robust path for codex is to
   **embed the full diff + suspect questions directly in the prompt string**.
   Mechanically: assemble the entire prompt BODY into a file, then pass it with
   command substitution AT THE CALL SITE —

   ```bash
   # build the full review body (diff + questions) in a file, then:
   codex_wrapper.py --sandbox read-only \
     --reasoning max --search --timeout 900 \
     --prompt "$(cat /path/to/review-body.txt)"     # <-- substitution fires here
   ```

   NEVER place `$(cat body.txt)` inside a single-quoted heredoc BODY — i.e.
   `--prompt "$(cat <<'PROMPT'` … a line containing `$(cat body.txt)` …
   `PROMPT)"`: the heredoc is literal, so that inner `$(...)` is NOT expanded
   and codex receives the uninterpreted string `$(cat ...)`. (The outer heredoc
   shape itself stays valid for a literal prompt body — the sibling dispatch
   skills' Step 1 uses exactly that.) (gemini / agy are
   workspace-sandboxed and DO read a repo-relative `_shared/` file per rule 8, so
   inlining is a codex-leg requirement, not a universal one — though inlining a
   small packet works for every leg.) For a LARGE diff (rule 8's large-packet
   case) the INLINED body must ALSO be the FOCUSED / high-risk subset, not the
   whole diff — codex inlines what agy/gemini get as the pre-assembled file; same
   focused content, different transport. See the lab's recorded incident log (Pitfall 3).
10. **claude fresh-eye leg = a TRUE fresh-eye Agent, MAX thinking, adversarial.**
    The claude leg MUST be a separate `Agent`
    (isolated context) — NEVER the leader reasoning inline (the leader holds the
    originating framing and shares its blind spot). Because it is the SAME family
    as a claude leader, its marginal value is CONTEXT-freshness, NOT family
    diversity (codex/agy carry that) — so it must reason MAXIMALLY to earn its
    place. Its prompt MUST: (a) tell it to think as hard as possible before
    answering (ultrathink); (b) frame it adversarially — "a subtle defect is
    PRESENT; find what the same-family leader AND the per-task review missed",
    not "check if this looks fine"; (c) forbid severity-deflation — do NOT
    downgrade a real correctness/robustness issue to Minor/benign to dodge a fix
    loop; rate by impact. The claude leg can otherwise lapse into catching nothing
    while codex/agy escalate residuals it rated Minor — the fix is depth +
    adversarial framing, not replacing the leg. Cross-check: if claude
    returns SAFE but a vendor leg returns must-fix, treat it as a signal the claude
    prompt under-reasoned, and sharpen it next round.
11. **Adversarial anti-rubber-stamp framing on EVERY leg, not just claude.**
    MAX reasoning tier (rule 1) is necessary but NOT sufficient — a leg at
    its top tier still rubber-stamps when the prompt only asks it to "check if this looks
    fine". So apply rule 10's adversarial framing (assume a defect is present; no
    severity-deflation) to the codex and agy legs too, and additionally require every leg
    to (a) ENUMERATE which criteria/rules it checked before concluding and (b) treat a
    bare "SAFE / none / faithful" verdict as a failed review, not a pass. A fast, terse
    SAFE/none from any leg (e.g. a sub-30s pass over a large packet) is a rubber-stamp
    signal → re-dispatch that leg with the adversarial framing. The framing, not the
    tier, is the gap: a leg at its top tier still rubber-stamps a bare "faithful/none"
    when it is only asked to check that things look fine (see the changelog).

## Flow

1. Scope the review: branch ref + base SHA + the list of suspect/omitted/
   simplified decisions (phrased as questions). If the packet is LARGE (rule 8),
   PRE-ASSEMBLE the focused packet file (framing + high-risk diff subset) at a
   repo-relative gitignored path, e.g. `_runs/review/<date>/packet.md`; the
   agy/gemini leg reads only that, codex inlines the same focused body.
2. Resolve the Google-family leg (Hard rule 1 snippet), then dispatch the
   reviewers in parallel, each at its family's MAX reasoning (rule 1) — `Agent`
   (claude fresh-eye at the strongest available Claude tier via the Agent model
   parameter, max-thinking/adversarial prompt per rule 10) +
   `triad-codex-dispatch` (codex `--reasoning max --search`) + the resolved
   Google leg (`triad-antigravity-dispatch`, passing `--model
   "$GOOGLE_REVIEW_MODEL"` ONLY when it is non-empty — on the verify-fallback
   path it is empty, so dispatch without `--model` and treat the leg as ADVISORY
   per rule 1 — or `triad-gemini-dispatch`; skip+log if none) — each with the
   same suspect-question list and the diff scope.
3. Collect the three verdicts + findings.
4. If unanimous SAFE TO MERGE with no must-fix → proceed to merge.
5. Otherwise: fix each finding (implementer + per-fix review), then GOTO 2
   (re-confirm) until unanimous SAFE — stopping after `TRIAD_REVIEW_MAX_ROUNDS`
   (default 2) full rounds; past that, record the residual findings and get an
   owner decision (rule 5).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Reviewers all pass a leader blind-spot | claude leg was leader-inline, or suspect framed as fact | Use a fresh-eye Agent; frame as questions (rules 1-2) |
| claude leg keeps returning SAFE while codex/agy escalate residuals | claude prompt under-reasoned / not adversarial / shallow tier | Max-thinking + adversarial prompt + no severity-deflation (rule 10); legs at family-MAX reasoning (rule 1) |
| A vendor leg (codex/agy) returns a fast bare SAFE/none despite MAX tier | Tier was set but the leg got no adversarial framing — it rubber-stamped | Give EVERY leg the rule-11 framing (assume a defect, enumerate checks, reject bare SAFE, no deflation); a sub-30s terse pass on a large packet → re-dispatch adversarially |
| Merged on 2-of-3 SAFE | Averaged instead of consolidated | ANY Critical/DO-NOT-MERGE blocks (rule 4) |
| First-pass fixes assumed sufficient | No re-confirm | Re-run the 3-way on the fixed branch (rule 5) |
| Vendor leg times out with no verdict | Reviewer live-ran the code → hung on a real vendor call, sandbox couldn't reap it | Add "READ-only, do NOT execute" + generous timeout to the leg prompt (rule 7) |
| A leg returns a repair-routed wrapper failure (`unknown` / `extraction-error` / `timeout`) | The leg's CLI transport hiccuped — not a review verdict | Let that leg's dispatch SKILL run its repair path, then re-dispatch the leg once; if it fails again, that family is unavailable this round (degraded-mode gating applies). Never count a wrapper failure as SAFE |
| agy/gemini leg times out / extraction-error with no verdict on a LARGE review | The leg was told to self-assemble a large diff/packet (`git diff` + read N files itself) and ran out the wall-time budget reading + stitching it | Pre-assemble a focused packet file; the leg reads ONLY that one file (rule 8 large-packet sub-rule); codex inlines the same focused subset (rule 9) |
| codex leg returns no verdict / "couldn't access the files" / reviews the literal string `$(cat ...)` | codex handed a file PATH under read-only+no-exec (file-read route empty), or `$(cat ...)` nested in a single-quoted heredoc (literal, unexpanded) | Inline the diff+questions into `--prompt` via call-site `"$(cat body.txt)"`, not a quoted-heredoc and not a file path (rule 9) |

## Why this exists

the cross-family review rule exists because a same-family review chain shares the leader's blind
spot. In the originating case the leader declared an appium wrap "a no-op," seeded
that into the implementer prompt, and the all-claude review chain passed it — while
codex and gemini independently caught a real device-shell injection hole. It
re-validated later: a strict per-task spec+quality review on every task STILL missed
several Critical and Important cross-cutting issues that the cross-family 3-way
caught. Per-task same-family review is necessary but not sufficient; the final
cross-family pass is the gate.

## Related

- `triad-codex-dispatch` (codex leg) / `triad-antigravity-dispatch` + `triad-gemini-dispatch` (the runtime-selected Google-family leg).
- `superpowers:subagent-driven-development` — the per-task (same-family) review this final pass backstops.
- `superpowers:requesting-code-review` / `superpowers:receiving-code-review` — single-reviewer code-review conventions.
