# Changelog

## 0.2.689 — 2026-08-29

**Cross-family review hardening — verdict binding, mechanized round
integrity, and a read-grant for the codex/agy legs** (adopted from
the codex-host 0.2.533 toolchain). Every review leg's `LegVerdict` is
now BOUND to its round and leg (`review_id`/`family`/`content_digest`,
all required) and admitted with `lib/validate_verdict.py`
`--expected-review-id`/`--expected-family`/`--expected-packet` (the
digest is recomputed from the packet file, not a hand-carried
string); a bidirectional validator rejects a `SAFE TO MERGE` verdict
that still carries a Critical/must-fix finding. Round integrity is
mechanized in `skills/triad-cross-family-review/lib/review_scratch.py`
(`capture`/`verify`): a per-round evidence snapshot plus a
git-config-independent worktree fingerprint gate every round with
`ROUND_INTEGRITY_OK`. The codex and agy review legs get a READ-GRANT
— read the repo to verify a packet claim — while the packet is still
read FIRST and mutation stays denied, with capture/verify as the
compensating control. The schema-repair retry no longer lets a leg
launder a blocking finding into a clean `SAFE` on the re-ask (the
retry is gated on the reply's parsed CONTENT, not on which validator
arm fired).

_(Prior release — **prompt-transport hardening across every dispatch
skill**: the Step 1 heredoc terminator is collision-resistant
(`TRIAD_<CLI>_PROMPT_EOF`) and `--prompt-file <absolute-path>` is the
standing path for content the caller did not author or that quotes a
template, so a prompt body can no longer close the heredoc early and
parse as SHELL in the caller's own session.)_

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
