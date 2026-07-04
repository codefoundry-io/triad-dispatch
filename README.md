> 🌐 **한국어 문서: [README.ko.md](./README.ko.md)**

# triad-dispatch

Single-shot cross-CLI dispatch for a Claude Code **leader**: dispatch **codex**,
**gemini**, and **antigravity (agy)** as single-shot workers with
classification-aware routing, a self-improving classifier, and a cross-family
pre-merge review.

## Requirements

- **Vendor CLIs installed + authenticated** — the wrappers never manage auth:
  - `codex` installed, then `codex login`.
  - **Google-family leg — pick the one that matches your Gemini access:**
    - **Individual Gemini access → `agy` (Antigravity)**, installed + OAuth sign-in.
      The Gemini CLI *individual* tier is deprecated (Google migrated it to the
      Antigravity suite), so agy is the Google-family leg for individual users.
    - **Enterprise / organization Gemini access → `gemini` (Gemini CLI)**, installed
      + your org sign-in. The **enterprise** Gemini tier stays in use (the
      individual-tier deprecation does not affect it); use `gemini` there, not agy.
  - The claude leg of a review is an in-session `Agent` subagent — no separate install.
- **`python3 >= 3.12`** on PATH (the `bin/` wrappers run via `#!/usr/bin/env python3`).

## Install

```
/plugin marketplace add codefoundry-io/triad-dispatch
/plugin install triad-dispatch@triad-dispatch
```

The repo is public, so installing needs no special auth. Background auto-update
works over public GitHub as-is; set `GITHUB_TOKEN` in your environment only to
raise the API rate limit.

**Local install (from a built folder).** To test a locally-built copy before
publishing, point `marketplace add` at the plugin directory
itself — **no git repo required** (the directory's `.claude-plugin/marketplace.json`
is what is read; its relative `source` resolves for local-directory adds). The
path must be absolute or start with `./`:

```
/plugin marketplace add /absolute/path/to/triad-dispatch
/plugin install triad-dispatch@triad-dispatch
```

**Test from a CLEAN working directory** — not a checkout that already has its own
`.claude/skills/` or `agents/`. Plugin skills/agents are namespaced
(e.g. `triad-dispatch:triad-codex-dispatch`), and a project's own same-named
`.claude/skills` / `.claude/agents` **override** the plugin's — so run from a
directory without those to exercise the plugin's own copies.

## Permission setup (required)

A plugin **cannot** grant Bash permissions, so you add them to your own
`.claude/settings.json` (or `.claude/settings.local.json`):

```json
{ "permissions": { "allow": [
  "Bash(codex_wrapper.py:*)",
  "Bash(gemini_wrapper.py:*)",
  "Bash(antigravity_wrapper.py:*)",
  "Bash(agy-daily-check.sh:*)",
  "Bash(gemini-daily-check.sh:*)"
] } }
```

Without this you are prompted on every dispatch (or denied when headless). The
commands need **network egress** — the wrappers spawn the vendor CLIs, which
make the API calls — so do not run them inside a no-network Bash sandbox.

## Verify the install

After install + the permission allowlist, confirm the plugin is live:

1. **bin on PATH** — in a Bash tool call, `command -v codex_wrapper.py` resolves
   under the installed plugin's `bin/` (auto-added to PATH; no user action needed).
2. **single-shot dispatch** — have the leader use `triad-codex-dispatch` (or
   `triad-gemini-dispatch`) on a trivial prompt; expect the answer plus a
   `[wrapper] <cli> ok …` summary line on stderr.
3. **self-improving classifier** — on an unrecognized failure the matching
   wrapper-repair agent appends a pattern to
   `~/.config/triad-dispatch/classifier-patches.json` (in your home, not the
   plugin dir); that file gains an entry and persists across plugin updates.
4. **cross-family review** — `triad-cross-family-review` resolves its
   Google-family leg at runtime (`TRIAD_GOOGLE_REVIEW_CLI`, else agy, else gemini)
   and runs claude(`Agent`) + codex + that leg.

## Recommended companion — Superpowers

Link: https://github.com/obra/superpowers . Install it via its marketplace
(`/plugin marketplace add https://github.com/obra/superpowers` then
`/plugin install superpowers`), or follow its README.

- **codex**: Superpowers is **recommended** — install it. The toolkit's codex
  `--task code` mirrors a Superpowers implementer subagent, and
  `triad-cross-family-review` is the capstone of
  `superpowers:subagent-driven-development`.
- **gemini**: Superpowers is **supported** — gemini has native skills
  (`gemini skills`), so install Superpowers as a companion. The bundled
  `gemini-daily-check.sh` tracks the installed skill set (incl. superpowers).
- **antigravity (agy)**: Superpowers does **not yet support** the Antigravity
  CLI — a **future update is planned**. `agy-daily-check.sh` probes daily for a
  "superpowers-for-agy" release.

## Recommended usage

How the leader and the owner actually use the toolkit:

- The Claude Code **leader** dispatches a single-shot worker when it needs an
  answer from outside its own context: `triad-codex-dispatch` (codex),
  `triad-gemini-dispatch` (gemini), or `triad-antigravity-dispatch` (agy). It
  does **not** shell out raw — the SKILL handles classification routing and the
  self-improving repair fallback.
- **agy = the search / research specialist** — its web `read_url` / `search_web`
  is always allowed. Include agy on any web-grounded lookup.
- Before merging review-worthy or correctness-critical work, the leader runs
  **`triad-cross-family-review`** (the cross-family review rule): three INDEPENDENT reviewers
  from different model families — a claude fresh-eye `Agent` subagent + codex +
  the Google-family CLI (agy or gemini, runtime-selected) — each frames the
  suspect decisions as questions; the leader consolidates
  verdicts and fixes → re-confirms until the verdict is unanimous SAFE.
- The classifier **self-improves**: an unrecognized error routes to a
  wrapper-repair agent that appends a pattern to the persistent extension JSON,
  so future identical errors auto-route.

## Usage scenarios

1. **Single-shot codex call** — the leader needs codex's answer to a discrete
   prompt → `triad-codex-dispatch`. It returns codex's answer (with classification
   on stderr); an `unknown` failure auto-routes to the `codex-wrapper-repair` agent.
2. **Single-shot gemini call** — an Android/XML/vision or Google-ecosystem prompt
   → `triad-gemini-dispatch`.
3. **Web research via agy** — a web-grounded lookup → `triad-antigravity-dispatch`
   (agy's `read_url` is always allowed). Always include agy on search.
4. **Structured output** — need validated JSON → the wrapper's
   `--pydantic module:Class` (prompt-instructed JSON + validation + one repair
   retry; exit 66 on schema failure).
5. **Pre-merge cross-family review** — about to merge a risky change →
   `triad-cross-family-review` (claude + codex + the Google-family CLI — agy or
   gemini, runtime-selected; fix → re-confirm until SAFE).

## Self-improvement (persistent)

The classifier learns across plugin updates via
`~/.config/triad-dispatch/classifier-patches.json` — in your home directory, so
it **survives plugin updates** (NOT the ephemeral plugin dir). The repair
sub-agents append new `error → class` entries there; the engine merges them at
runtime. It is portable — a team can curate and share it.

## Runtime Artifacts And Cleanup

Wrapper telemetry is local and bounded. Runtime files live under
`bin/_logs/<cli>/` for each wrapper family (`codex`, `gemini`, `antigravity`):

- `audit.jsonl` rotates when the active file exceeds 10 MB and keeps at most
  five archives / 50 MB per CLI.
- Failure IPC run logs live under `bin/_logs/<cli>/runs/*.json`. File names
  include UTC timestamp, process id, and an 8-character random UUID suffix, so
  parallel dispatches do not collide.
- Normal dispatch cleanup deletes the run log and matching `.repair.json` after
  the repair agent returns.
- Wrapper failsafes cap run logs at 100 files / 20 MB per CLI and sweep stale
  run logs plus `.repair.json` files older than 7200 seconds on the next normal
  dispatch.

Classifier patches live in `~/.config/triad-dispatch/classifier-patches.json`.
Repair agents use the adjacent lock file before editing it so concurrent repairs
do not silently overwrite each other.

## What's inside

- **skills** (4): `triad-codex-dispatch`, `triad-gemini-dispatch`,
  `triad-antigravity-dispatch`, `triad-cross-family-review`.
- **agents** (3): `codex-wrapper-repair`, `gemini-wrapper-repair`, `agy-wrapper-repair`.
- **bin**: the Python wrappers (codex / gemini / agy) + `agy-daily-check.sh` +
  `gemini-daily-check.sh` + `policies/gemini-readonly.toml` (the per-call
  read-only Policy Engine file the gemini `--sandbox read-only` mode attaches).
- **tests**: stdlib-only wrapper tests you can run as-is to verify the install:

  ```bash
  python3 tests/test_gemini_sandbox.py   # 6 checks — gemini sandbox argv contract
  python3 tests/test_log_cleanup.py      # 2 checks — log prune + audit rotation
  ```

- **migration**: `CLAUDE.recommended.md` — a starter CLAUDE.md encoding the
  working practices this toolkit assumes (pre-execution discipline,
  cross-family review, artifact portability).
