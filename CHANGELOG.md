# Changelog

## 0.2.601 — 2026-08-01

**Prompt-transport hardening across every dispatch skill.** The
Step 1 invocation template's heredoc terminator is now
collision-resistant (`TRIAD_<CLI>_PROMPT_EOF`, replacing a bare
`PROMPT`): a prompt body containing the terminator word on its own
line closed the heredoc early, and because the heredoc sits inside
`$( … )` the remainder then parsed as SHELL in the caller's own
session — outside every worker-side sandbox. Each dispatch skill
pins its own terminator, and `--prompt-file <absolute-path>` is
named as the standing path (REPLACING the heredoc — the two are
mutually exclusive) for content the caller did not author AND for
any body that quotes a dispatch template or a skill body, since
quoted text carries the terminator verbatim.

_(Prior release — **one structured verdict schema across all three
review legs, cross-family review v0.24.x**: every review leg
returns ONE
validated `LegVerdict` object (verdict token, enumerated
criteria_checked, findings[] with file/line/severity/trigger/
context-known) instead of free prose: the codex leg via
`--pydantic verdict_schema:LegVerdict` (native `--output-schema`,
strict-massaged), the agy leg via the same flag (native
`--json-schema`, fold-exempt — a long verdict rides the terminal
stream event instead of the ~4KB chat fold), and the claude leg
via a prompt contract validated by the shipped deterministic
`lib/validate_verdict.py`. Consolidation maps `findings[]` into
the residual table mechanically with jq. The read-audit digest
file gained stale-round hardening: the wrapper pre-clears the
bound path at call start (skipped on `--repair-mode`), the
override write refuses symlinks (O_NOFOLLOW), and dispatch /
pre-clear / gate all bind one byte-identical packet-relative
literal. Schema floors: non-SAFE verdicts need >=1 finding,
criteria and finding fields reject empty/whitespace, line >= 1.)_

_(Prior release — **skill progressive-disclosure split, review
v0.23.0 / antigravity dispatch v0.13.0**: both bodies became lean
overviews backed by ten on-demand `references/*.md`, duplicated
rules collapsed to one home each; a 6-leg skill-prompt-review
round then hardened the agy heredoc terminator, the repair-loop
run-log path check, the degraded-mode trigger wording, and added
a codex `--search` sensitivity precondition.)_

_(Prior release 0.2.572 — **agy transport = native stream-json (agy
>= 1.1.8)**: the pty + completion-sentinel + transcript-scan stack is
deleted behind a fail-closed version floor; the wrapper spawns
through the shared vendor-child site over `-p --output-format
stream-json` NDJSON, folds a deterministic read-audit digest from
`tool_info` events, and gains a native `--json-schema` structured
output path.)_

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
