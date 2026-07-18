# Changelog

## 0.2.524 — 2026-07-18

**claude worker `--model` dispatch-time selection.** `claude_wrapper.py`
now accepts `--model <alias-or-name>` (forwarded to the claude CLI
`--model`; free string, never pinned in code — the leader picks the
model per call, the same shape as codex `-m`). Omit = vendor default.
`--effort` (reasoning level) was already wired. Guidance: a
fable-class model for long-running leader/worker operation, opus-4.8
with `--effort xhigh` for review legs.

_(Prior release 0.2.521 — **agy ≥1.1.3 headless permission fix**: the
wrapper version-gates `--dangerously-skip-permissions` on agy ≥1.1.3
so the soft-denied headless leg runs again; that flag voids the
`--sandbox` deny transaction, so on ≥1.1.3 an agy dispatch is
read-only by INTENT not enforcement — opt-out
`AGY_NO_HEADLESS_AUTOAPPROVE=1`, enforced on ≤1.1.2.)_

**Review orchestration discipline** (from an earlier release's
hardened-audit custody + agy extraction strictness + review-packet
lifecycle):

- The cross-family-review skill now spells out the LEADER's
  consolidation role (fact-check every finding with a deterministic
  probe, classify the round CONVERGING vs OSCILLATING, and hand an
  oscillating round's conflict table to the user instead of another
  round), plus leg-orchestration rules: background dispatch with ONE
  generous event-driven wait (a wait timeout is a wake-up boundary,
  not a failure), no unrelated work while legs run, bounded
  delegation with an explicit return contract, and timeouts scaled
  to packet size x reasoning tier.
- Redact mode (`TRIAD_AUDIT_REDACT_PROMPTS=1` / hardened default):
  the durable audit now stores `stdout`/`stdout_head`/`stderr` as
  `"<redacted>"` plus lengths on every record (a prompt echo can ride
  a stream head, so a cap cannot guarantee prompt custody), and caps
  `extraction_error` at 500 chars. The transient failure run-log keeps
  full copies. NOTE: audit files written by earlier hardened installs
  may contain full non-ok streams — rotate/purge them once.
- The antigravity pty-fallback extractor accepts its completion marker
  only when TERMINAL (whitespace-only tail AND newline-preceded, per the
  sealed prompt's own-line instruction); a truncated run whose only
  marker is an early echo now fails closed (`non-terminal-marker`)
  instead of returning a partial answer as ok.
- The cross-family-review skill ships a deterministic packet-lifecycle
  helper (`skills/triad-cross-family-review/lib/review_scratch.py`):
  open/touch/close plus a stale-packet prune, so packets stranded by a
  crashed review are swept at the next review `open`.
- Relative `--prompt-file` stays fail-loud; the error now shows the
  caller cwd and a cwd-derived absolute candidate.

Built from the Triad source of truth. Full history: https://github.com/codefoundry-io/triad-dispatch/commits/main (each release commit summarizes its delta).

### Upgrading from 0.1.x (installed before 2026-07-05)

The marketplace was renamed `triad-internal-tools` → `triad-dispatch`,
so a bare `claude plugin update triad-dispatch` reports *not found*
(verified). Use either path once:

```bash
claude plugin update triad-dispatch@triad-internal-tools   # keeps the old key
# — or a clean re-key —
claude plugin marketplace remove triad-internal-tools
claude plugin marketplace add <repo-or-path>
claude plugin install triad-dispatch
```

Both were tested; neither leaves a ghost install or duplicate skills.
