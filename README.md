> 🌐 **한국어 문서: [README.ko.md](./README.ko.md)**

# triad-dispatch

Single-shot cross-CLI dispatch for a Claude Code **leader**: dispatch **codex**,
**gemini**, and **antigravity (agy)** as single-shot workers with
classification-aware routing, a self-improving classifier, and a cross-family
pre-merge review.

## Requirements

- **Vendor CLIs installed + authenticated** — the wrappers never manage auth:
  - `codex` installed, then `codex login`.
  - `gemini` (Gemini CLI) installed, then its sign-in. **사내: available through
    2026-07-31; after that the Google-family review leg degrades to claude+codex
    (logged, not an error).**
  - `agy` (Antigravity) installed, then its OAuth sign-in. **Not used 사내.**
  - The claude leg of a review is an in-session `Agent` subagent — no separate install.
- **`python3 >= 3.12`** on PATH (the `bin/` wrappers run via `#!/usr/bin/env python3`).

## Install

```
/plugin marketplace add <internal-git-url>
/plugin install triad-dispatch@triad-internal-tools
```

Private-repo auth uses your existing git credentials (an SSH key in `ssh-agent`,
or a `gh`/git credential helper). Background auto-update needs `GITLAB_TOKEN` /
`GITHUB_TOKEN` in your environment.

**Local install (from a built folder).** To test a locally-built copy before
publishing to the internal repo, point `marketplace add` at the plugin directory
itself — **no git repo required** (the directory's `.claude-plugin/marketplace.json`
is what is read; its relative `source` resolves for local-directory adds). The
path must be absolute or start with `./`:

```
/plugin marketplace add ~/triad-dispatch-plugin
/plugin install triad-dispatch@triad-internal-tools
```

**Test from a CLEAN working directory** — not a checkout that already has its own
`.claude/skills/` or `.claude/agents/`. Plugin skills/agents are namespaced
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
  **`triad-cross-family-review`** (self-rule #6): three INDEPENDENT reviewers
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

## What's inside

- **skills** (4): `triad-codex-dispatch`, `triad-gemini-dispatch`,
  `triad-antigravity-dispatch`, `triad-cross-family-review`.
- **agents** (3): `codex-wrapper-repair`, `gemini-wrapper-repair`, `agy-wrapper-repair`.
- **bin**: the Python wrappers (codex / gemini / agy) + `agy-daily-check.sh` +
  `gemini-daily-check.sh`.
