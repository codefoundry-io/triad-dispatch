# Changelog

## 0.2.578 — 2026-07-31

**agy read-audit digest = durable FILE artifact
(`TRIAD_READ_AUDIT_FILE`) — cross-family review v0.22.0.** The agy
wrapper now writes its per-call read-audit digest to a JSON file on
EVERY completed call (success included — the failure-only run-log
never covered the review leg's normal case): default
`_logs/antigravity/read-audit/<UTC-ts>-<pid>-<uuid8>.json` with
run-log-style prune caps, or the exact path bound via the
`TRIAD_READ_AUDIT_FILE` env override (caller-owned, never pruned).
The cross-family review skill's mechanical read-audit gate reads
that file directly and the whole stderr-parsing surface is retired
(anchored grep/sed extraction, `AGY_STDERR` binding + truncate
rules, the separate JSON validity pre-check, and the
late-append/first-match forgery residuals those rules contained).
The digest remains evidence that the leg did the reading work, not
an authenticated control. The antigravity dispatch skill (v0.12.0)
documents the new `read-audit-file:` stderr line + override.

_(Prior release 0.2.572 — **agy transport = native stream-json (agy
>= 1.1.8)**: the pty + completion-sentinel + transcript-scan stack is
deleted behind a fail-closed version floor; the wrapper spawns
through the shared vendor-child site over `-p --output-format
stream-json` NDJSON, folds a deterministic read-audit digest from
`tool_info` events, and gains a native `--json-schema` structured
output path.)_

_(Prior release — **review model-tier policy, cross-family review
v0.19.0**: review legs run xhigh-class depth by default; max-class
depth is an escalation for rounds designated very-important AND
algorithmically complex — claude via the `effort: max` sibling
reviewer agent, codex via `--reasoning max` (`ultra` stays
banned).)_

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
