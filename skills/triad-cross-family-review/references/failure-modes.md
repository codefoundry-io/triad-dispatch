# Cross-family review — failure-mode index

Loaded on demand from `triad-cross-family-review/SKILL.md`. This is a
symptom → cause → rule lookup, not a second statement of the rules: each Fix
cell names the rule (or reference) that owns the behaviour. Open it when a round
misbehaves and you want to know which rule already covers it.

| Symptom | Cause | Where the fix lives |
|---|---|---|
| Reviewers all pass a leader blind-spot | claude leg was leader-inline, or a suspect was framed as fact | rules 1-2 |
| claude leg keeps returning SAFE while codex/agy escalate residuals | claude prompt under-reasoned / not adversarial / shallow tier | rule 10 (max-thinking + adversarial + no severity-deflation); rule 1 for the tier |
| A vendor leg returns a fast bare SAFE/none despite a deep tier | Tier was set but the leg got no adversarial framing — it rubber-stamped | rule 11 (framing, and the latency threshold); an agy pass is advisory regardless, rule 1 |
| agy leg's `read_audit.digest.files_read` never lists a packet file's path | The agy HARNESS wandered outside the packet dir, or never opened it, before answering | `references/leg-contracts.md` § agy read-audit gate — it owns the VOID / INCONCLUSIVE branch and the re-dispatch rule |
| Merged on 2-of-3 SAFE | Averaged instead of consolidated | rule 4 |
| First-pass fixes assumed sufficient | No re-confirm | rule 5 |
| Vendor leg times out with no verdict | Reviewer live-ran the code → hung on a real vendor call, sandbox couldn't reap it | rule 7 (no-exec directive AND a scaled timeout) |
| A leg returns a repair-routed wrapper failure (`unknown` / `extraction-error` / `timeout`) | The leg's CLI transport hiccuped — not a review verdict | Let that leg's dispatch SKILL run its repair path, then re-dispatch the leg once; if it fails again the family is missing this round (rules 13 + 1). A wrapper failure is never counted as SAFE |
| agy leg returns `truncated-answer` (65) with no verdict | The verdict folded CLI-side; widening the sandbox to let it write would forfeit rule-7 containment on the untrusted-input leg | `references/leg-contracts.md` § agy leg, "Folded verdict" — it owns the one re-dispatch and the never-widen rule |
| agy/gemini leg times out / extraction-error with no verdict on a LARGE review | The leg was told to self-assemble a large diff/packet and ran out its wall-time budget stitching it | rule 8 (pre-assemble one focused file); codex gets the same subset inlined, rule 9 |
| codex leg returns no verdict / "couldn't access the files" / reviews the literal string `$(cat ...)` | codex was handed a file PATH under read-only+no-exec, or `$(cat ...)` sat in a single-quoted heredoc (literal, unexpanded) | rule 9 and `references/leg-contracts.md` § codex leg |
| codex leg times out at max tier on a big inline packet | Timeout not scaled to packet × tier | Shrink to the focused subset first (rules 8-9); if the packet must stay large, raise the timeout per rule 7 |
| Rounds keep flipping each other's verdicts / re-litigating settled points | The loop stopped converging — more rounds only oscillate | rule 12 (stop; conflict table to the owner) |
| Leader burns the wait busy-polling legs, or picks up unrelated work mid-review | Poll loops / context interleaving instead of event-driven waits | rule 13 |
| Codebase grows guards/fallbacks each round; leader lands new defensive layers mid-round without sign-off | The loop rewards adding code; speculative findings entered the fix queue as must-fix | rule 14 and `references/triage.md` |
