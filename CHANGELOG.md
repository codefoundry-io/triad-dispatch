# Changelog

## 0.2.1995 — 2026-11-08

This release adapts the agy (Antigravity CLI) review and research leg to agy 1.5.3, which offers a custom agent only `read_file` (plus `search_web` on the research agent; `manage_task` and `finish` are always present) and no longer `view_file`, `grep_search`, `list_dir`, `find_by_name` or a working `read_url_content` in print mode. The read-only agy route now requires agy 1.5.3 or later: an older agy is refused before any call with one line telling you to run `agy update` (exit 65, `config-conflict`). The two read-only agents list only the 1.5.3 tools, and the admission check, the review hook and the read-audit gate accept `read_file` only. While the shared review prompt still names the old read tools, a call to one of them that ends in an error is treated as an errored read, not as a forbidden tool; one that runs still voids the answer.

Before or right after you update:

- agy: update to 1.5.3 or later (`agy update`), then re-install the two read-only agent files once: `python3 <plugin>/bin/antigravity_wrapper.py --setup-agents`. Until you do, every read-only agy call stops with a `config-conflict` line naming `--setup-agents` (the installed files no longer match).
- A review packet an earlier version prepared: close it with `review_scratch.py close` and prepare a new round.
- From a version before 0.2.1959: install the review library's dependencies at its floors, `jsonschema>=4.26,<5` and `referencing>=0.37,<1` (the README's install section has the Mac and Ubuntu lines); without them the review stops with one host-fault line (exit 64) that carries the install hint.
- From a version before 0.2.1702, also (that version removed the agy and gemini daily checks, the agy settings handling, the v1 and the small review paths, the old verdict schema, the starter CLAUDE.md under `migration/` and the `TRIAD_DEBUG_MAX_AGE_DAYS` environment knob):
  - Close any open small-path round with `review_small.py close <round directory>` before you update; a round left after the update stays and is yours.
  - Run `python3 <plugin>/scripts/setup_permissions.py --install` once in each project an earlier version set up: it retires the vendor-binary pins, the `TRIAD_AUDIT_REDACT_PROMPTS` key, the daily-check grants and the bare-name grants its record shows it wrote.
  - Remove any cron or launchd entry you made for the daily checks.
  - agy: this version never writes, locks or heals the agy settings; a stale `~/.gemini/antigravity-cli/.agybak` beside them comes from the codex host's per-call deny transaction or an older build of this plugin and is the codex host's to heal — never delete it, it holds the only settings snapshot. On a machine with no codex host, restore it by hand: `.agybak` is a JSON object `{"existed": <bool>, "content": "<the settings.json text before the transaction>"}` — when `existed` is true write the `content` text back to `~/.gemini/antigravity-cli/settings.json`, when it is false remove `settings.json` — then remove `.agybak`.
  - `setup_permissions.py --uninstall-machine` leaves what an earlier version wrote beside the agy settings — `~/.gemini/antigravity-cli/.agy_settings.lock` and the `.agy_settings.holders/` folder — and the two daily-check folders `~/.gemini/antigravity-cli/triad-daily/` and `~/.gemini/triad-daily/`: no command of this version removes them, and they are yours (the lock may be shared with the codex host).
  - The user-scope cleanup file (`$XDG_CONFIG_HOME/triad/cleanup.json`, else `~/.config/triad/cleanup.json`) is no longer read: move its roles into the project's `.claude/triad-cleanup.json`.
  - Update the gemini CLI to 0.63.0 or later (the wrapper refuses an older one); codex `--task` / `--fanout` / `--report-dir` now exit 2 (an argument error); a `:`-scoped `claude.agent` name in a review roster is refused.

Full history: https://github.com/codefoundry-io/triad-dispatch/commits/main
