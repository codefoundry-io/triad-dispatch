# Changelog

## 0.2.538 — 2026-07-30

**Review model-tier policy — cross-family review v0.19.0.** Review
legs now run xhigh-class depth by DEFAULT; max-class depth is an
ESCALATION reserved for rounds the leader designates very-important
AND algorithmically complex. The claude fresh-eye leg pins
`model: opus` + `effort: xhigh` in the reviewer agent's frontmatter
(previously unpinned — it silently inherited the leader's session
model), and a new sibling agent `cross-family-review-reviewer-max`
(identical body, `effort: max`) is the escalation mechanism, because
effort is frontmatter-fixed with no per-invocation override. The
codex leg defaults to `--reasoning xhigh` with `--reasoning max` on
escalation (`ultra` stays banned); the Google leg is unchanged
(`gemini-3.1-pro-high`). Basis: Opus 5 official effort guidance —
xhigh for demanding coding/agentic work, max only when unconstrained
spend is justified.

_(Prior release — **agy `truncated-answer` gate**: agy folds a long
chat answer mid-body at a ~4KB cap and keeps no full copy; the
wrapper detects the own-line marker on the answer-present rc=0 path
and returns terminal `truncated-answer` (65) with the lossy answer
quarantined from stdout, and the antigravity dispatch skill gains a
§ Long-answer output-file contract — absolute-path `write_file` is
fold-exempt, verified 24KB intact.)_

_(Prior release — **cross-family review v0.17.0, CONFLICTED verdicts
call the owner**: a head-on same-decision contradiction between legs,
both sides surviving the deterministic fact-check probe, triggers an
immediate owner call instead of leader-side compromise; probe-refuted
sides, complementary findings, and same-defect convergence remain
non-conflicts.)_

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
