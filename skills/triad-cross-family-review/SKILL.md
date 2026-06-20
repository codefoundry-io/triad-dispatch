---
name: triad-cross-family-review
description: Use for the FINAL pre-merge (or review-worthy / security-or-correctness-critical) cross-family review mandated by self-rule #6 — dispatch INDEPENDENT cross-family reviewers (a claude fresh-eye sub-agent via Agent + codex via triad-codex-dispatch + the Google-family CLI selected at runtime, agy via triad-antigravity-dispatch or gemini via triad-gemini-dispatch), frame the suspect/omitted/simplified decisions as QUESTIONS, consolidate their verdicts (SAFE TO MERGE / MERGE WITH FIXES / DO NOT MERGE), then run a fix→re-confirm loop until unanimous SAFE. Trigger when about to merge review-worthy work, ESPECIALLY when the leader chose to OMIT or SIMPLIFY something from a vetted source, or after a subagent-driven implementation before integration.
version: 0.7.0
---

# triad-cross-family-review

The leader's standard **final pre-merge review**: three independent reviewers
from different model families judge a diff/branch, the suspect decisions are
posed as questions, and findings drive a fix→re-confirm loop. Codifies
self-rule #6 (`CLAUDE.md` § Self-rules 6).

## When to use

- About to merge review-worthy or security/correctness-critical work.
- The leader OMITTED or SIMPLIFIED something from a vetted external source
  (the canonical self-rule #6 blind-spot case).
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
   if [ -z "$GOOGLE_CLI" ]; then
     if command -v agy >/dev/null 2>&1; then GOOGLE_CLI=agy        # agy-first
     elif command -v gemini >/dev/null 2>&1; then GOOGLE_CLI=gemini # fallback
     else GOOGLE_CLI=""; fi                                         # neither
   fi
   # REASONING TIER (review-only override of the no-model-pin rule, owner directive
   # 2026-06-14): the agy/gemini DEFAULT is a fast shallow model (Gemini 3.5 Flash)
   # — empirically USELESS for adversarial review. Measured 2026-06-14 on the
   # IngenuityPrint B5 diff: agy on the Flash default found 0 real issues across 4
   # rounds, while the SAME diff at the Pro tier surfaced 3 real findings (a dead-code
   # path + 2 wrong-descriptor edges) that even codex+claude had missed. agy encodes
   # reasoning in the MODEL VARIANT (there is NO --reasoning flag; the separate
   # thinkingLevel param is stripped/buggy — antigravity issue #1675), so force the
   # Pro/High variant via --model. Env-overridable; verify it still exists (Google
   # renames tiers) and fall back to the default + log if absent.
   GOOGLE_REVIEW_MODEL="${TRIAD_GOOGLE_REVIEW_MODEL:-Gemini 3.1 Pro (High)}"
   if [ "$GOOGLE_CLI" = agy ] && ! agy models 2>/dev/null | grep -qxF "$GOOGLE_REVIEW_MODEL"; then
     echo "[review] '$GOOGLE_REVIEW_MODEL' not in 'agy models' — falling back to agy default (Flash); log + proceed" >&2
     GOOGLE_REVIEW_MODEL=""
   fi
   ```

   `agy` → `triad-antigravity-dispatch`; `gemini` → `triad-gemini-dispatch`;
   empty → **skip the Google leg and log** "Google-family reviewer unavailable;
   review proceeds with claude(Agent)+codex (2-family)". Normally THREE
   reviewers; degrades to two (claude+codex) only when neither Google CLI is
   installed (e.g. 사내 after the gemini sunset). Same-family-only reviewers
   inherit the leader's framing; cross-family + fresh-eye is what breaks the
   monoculture.

   **Pass the Pro tier to the Google leg.** When `GOOGLE_REVIEW_MODEL` is
   non-empty, the agy review dispatch MUST pass `--model "$GOOGLE_REVIEW_MODEL"`
   to `antigravity_wrapper.py` (the wrapper has a `--model` passthrough; it pins
   nothing by default). The codex leg already runs at `--reasoning high` and the
   claude `Agent` leg at opus, so only the Google leg needed this. Cost note: the
   Pro/thinking tier is API-billed (not subscription-covered) — acceptable for the
   high-stakes pre-merge gate by owner directive; do NOT use it for cheap
   single-shot dispatches (those stay on the default per the no-model-pin rule).
2. **Frame suspect decisions as QUESTIONS, not settled facts.** "Is X actually
   safe to omit?" — never "X is a no-op." A biased framing propagates into the
   reviewers and defeats the purpose (2026-05-24 IngenuityPrint incident).
3. **Each reviewer gets the diff scope + reads it themselves.** Give the branch
   ref / SHA range + the list of suspect decisions; let each reviewer run
   `git diff` and read files with its OWN tools (keeps leader context lean).
4. **Consolidate, don't average.** ANY reviewer's Critical / must-fix or a
   DO-NOT-MERGE verdict blocks merge. Cross-family complementarity is the
   point: one may catch what the others miss (validated 2026-05-30 — codex
   caught extractor bugs, gemini caught a classifier false-positive, claude
   caught a config/safety gap; none overlapped fully).
5. **Fix→re-confirm loop.** Findings → fix each (own implementer + per-fix
   review) → RE-RUN the 3-way on the fixed branch. A first-pass DO-NOT-MERGE
   is only closed by a re-confirm pass, not by the leader asserting it's fixed.
6. **Codex-path caveat (self-rule #6 nuance).** When the work being reviewed IS
   the codex dispatch path itself, codex reviews the *artifact diff* (e.g.
   Python), not its own reasoning — cross-family + fresh-eye still holds, so
   the full 3-way is valid (2026-05-30 owner directive overrode the earlier
   gemini-only conservatism). Use judgment; when in doubt, keep all three.
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
   re-dispatch read-only. Origin: 2026-06-11 gemini-agy-parity gate, codex
   live-ran `gemini-daily-check.sh`'s deep probe → 580s timeout, no verdict;
   adding the no-exec directive → same review completed in 101s. See leader
   memory `feedback_vendor_review_leg_readonly_no_exec_2026_06_11.md`.
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
   artifact). Origin: 2026-06-12 IPC-cleanup review — a `/tmp` brief was invisible
   to gemini/agy until moved under `_shared/`.
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
     --reasoning high --timeout 900 \
     --prompt "$(cat /path/to/review-body.txt)"     # <-- substitution fires here
   ```

   NEVER nest `$(cat ...)` inside a **single-quoted heredoc** (`--prompt "$(cat <<'PROMPT' ... PROMPT)"`):
   a single-quoted heredoc is literal, so `$(...)` is NOT expanded and codex
   receives the uninterpreted string `$(cat ...)`. (gemini / agy are
   workspace-sandboxed and DO read a repo-relative `_shared/` file per rule 8, so
   inlining is a codex-leg requirement, not a universal one — though inlining a
   small packet works for every leg.) Origin: 2026-06-11 slice-1 cross-family gate;
   see leader memory `feedback_vendor_review_leg_readonly_no_exec_2026_06_11.md` (Pitfall 3).

## Flow

1. Scope the review: branch ref + base SHA + the list of suspect/omitted/
   simplified decisions (phrased as questions).
2. Resolve the Google-family leg (Hard rule 1 snippet), then dispatch the
   reviewers in parallel — `Agent` (claude fresh-eye, opus for high-stakes) +
   `triad-codex-dispatch` + the resolved Google leg (`triad-antigravity-dispatch`
   or `triad-gemini-dispatch`; skip+log if none) — each with the same
   suspect-question list and the diff scope.
3. Collect the three verdicts + findings.
4. If unanimous SAFE TO MERGE with no must-fix → proceed to merge.
5. Otherwise: fix each finding (implementer + per-fix review), then GOTO 2
   (re-confirm) until unanimous SAFE.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Reviewers all pass a leader blind-spot | claude leg was leader-inline, or suspect framed as fact | Use a fresh-eye Agent; frame as questions (rules 1-2) |
| Merged on 2-of-3 SAFE | Averaged instead of consolidated | ANY Critical/DO-NOT-MERGE blocks (rule 4) |
| First-pass fixes assumed sufficient | No re-confirm | Re-run the 3-way on the fixed branch (rule 5) |
| Vendor leg times out with no verdict | Reviewer live-ran the code → hung on a real vendor call, sandbox couldn't reap it | Add "READ-only, do NOT execute" + generous timeout to the leg prompt (rule 7) |
| codex leg returns no verdict / "couldn't access the files" / reviews the literal string `$(cat ...)` | codex handed a file PATH under read-only+no-exec (file-read route empty), or `$(cat ...)` nested in a single-quoted heredoc (literal, unexpanded) | Inline the diff+questions into `--prompt` via call-site `"$(cat body.txt)"`, not a quoted-heredoc and not a file path (rule 9) |

## Why this exists

self-rule #6 (codified 2026-05-24, IngenuityPrint device-shell injection: the
leader declared an appium wrap "a no-op," seeded it into the implementer prompt,
the all-claude review chain passed it, codex+gemini independently caught a real
hole). Re-validated 2026-05-30 (codex-dispatch Foundation+Archetype A): a strict
per-task spec+quality review on every task STILL missed 3 Critical + 4 Important
cross-cutting issues that the cross-family 3-way caught. Per-task same-family
review is necessary but not sufficient; the final cross-family pass is the gate.

## Related

- `CLAUDE.md` § Self-rules 6 — the originating rule.
- leader memory `feedback_three_way_fresh_eye_cross_check.md` — origin narrative + 2026-05-30 re-validation.
- leader memory `feedback_vendor_review_leg_readonly_no_exec_2026_06_11.md` — Hard rule 7 origin (codex live-run hang).
- `triad-codex-dispatch` (codex leg) / `triad-antigravity-dispatch` + `triad-gemini-dispatch` (the runtime-selected Google-family leg).
- `superpowers:subagent-driven-development` — the per-task (same-family) review this final pass backstops.
- `superpowers:requesting-code-review` / `superpowers:receiving-code-review` — single-reviewer code-review conventions.
