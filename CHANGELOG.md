# Changelog

## 0.2.1708 — 2026-10-10

This release removes the agy and gemini daily checks, the agy settings handling, the v1 and the small review paths, the old verdict schema, the starter CLAUDE.md under `migration/` and the `TRIAD_DEBUG_MAX_AGE_DAYS` environment knob.

Before or right after you update:

- Close any open small-path round with `review_small.py close <round directory>` before you update; a round left after the update stays and is yours.
- Run `python3 <plugin>/scripts/setup_permissions.py --install` once in each project an earlier version set up: it retires the vendor-binary pins, the `TRIAD_AUDIT_REDACT_PROMPTS` key, the daily-check grants and the bare-name grants its record shows it wrote.
- Remove any cron or launchd entry you made for the daily checks.
- A review packet an earlier version prepared: close it with `review_scratch.py close` and prepare a new round.
- agy: this version never writes, locks or heals the agy settings; a stale `~/.gemini/antigravity-cli/.agybak` beside them comes from the codex host's per-call deny transaction or an older build of this plugin and is the codex host's to heal — never delete it, it holds the only settings snapshot.
- Update the gemini CLI to 0.63.0 or later (the wrapper refuses an older one); codex `--task` / `--fanout` / `--report-dir` now exit 2 (an argument error); a `:`-scoped `claude.agent` name in a review roster is refused.

Full history: https://github.com/codefoundry-io/triad-dispatch/commits/main
