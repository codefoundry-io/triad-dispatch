# Company environment setup — Claude Code, optimized

> 🌐 **한국어: [COMPANY-SETUP.ko.md](./COMPANY-SETUP.ko.md)**
>
> 사내 (closed-network, limited-proxy) Claude Code 환경을 우리가 함께 일하던 방식으로
> 최적화하기 위한 설치/구성 가이드. 동봉된 `CLAUDE.recommended.md` 와 짝.

This guide bootstraps a company Claude Code environment with the tools and
working practices that make the human↔Claude pair effective. It targets:

- **OS**: Ubuntu 24.04 (Noble) — the internal prod baseline.
- **Vendor CLIs available**: Codex CLI, Gemini CLI, Claude Code. (No Antigravity.)
- **Network**: closed network with a **limited proxy** — external marketplaces are
  not directly reachable; install from an **internal GHE mirror** or a **local
  folder copy**, not a public `github.com` URL.

---

## 0. Prerequisites (apt)

```bash
sudo apt update
sudo apt install -y python3 python3-venv git ripgrep fd-find jq \
  shellcheck shfmt expect parallel pv
# yq: the apt `yq` is a DIFFERENT tool — install the Go yq from a GitHub release
#     binary (or your internal mirror), not `apt install yq`.
# ruff / tokei / difft: install via your internal mirror or cargo if available.
```

- Python must resolve to **3.12** (`python3 --version`) — Ubuntu 24.04 ships it.
- Bash must be **5.x** (`bash --version`) — Ubuntu 24.04 stock 5.2 is fine.
- `fd` is `fdfind` on Ubuntu; alias `fd=fdfind` in your shell rc if you want.

> Why this exact set: every tool here is **artifact-callable** on both macOS
> (dev) and Ubuntu 24.04 (prod) with identical syntax, so scripts written with
> them run unchanged on both sides. Do not put Mac-only tools (`osascript`,
> `open`, `direnv` hooks, `httpie` in scripts) into artifacts.

---

## 1. Vendor CLIs + auth

Install and **log in interactively** to each CLI you will use. Claude never
issues or manages tokens — it reuses whatever credentials you set up here.

| CLI | install | auth (you do this) |
|-----|---------|--------------------|
| **Codex** | per your internal package mirror | `codex login` |
| **Gemini** | per your internal package mirror | `gemini auth login` (or your org SSO) |
| **Claude Code** | per your internal package mirror | `claude` first-run login |

Codex/Gemini are the dispatch *workers*; Claude Code is the *leader* (and the
fresh-eye review leg). See the dispatch section below.

---

## 2. Plugins / marketplaces (limited-proxy install)

External marketplaces (e.g. `github.com/obra/superpowers`) are not directly
reachable. Use one of:

- **Internal GHE mirror**: mirror the marketplace repo into your GHE, then
  `/plugin marketplace add https://<your-ghe-host>/<org>/<repo>.git`
  (needs a GHE Personal Access Token via a git credential helper, or an SSH key
  in `ssh-agent` + the host in `known_hosts`).
- **Local folder** (no git, no token, no network): copy the built plugin
  directory onto the machine, then `/plugin marketplace add /abs/path/to/folder`.

### 2a. Superpowers (Anthropic methodology skills) — STRONGLY recommended

This is the backbone of how we work. Mirror `obra/superpowers` internally (or
copy a built snapshot), then add it and install. Skills we lean on constantly:

- `brainstorming` — idea → design/spec (gate before any implementation)
- `writing-plans` — design → bite-sized TDD task plan
- `subagent-driven-development` — execute a plan task-by-task with spec+quality review
- `test-driven-development` — RED → GREEN → REFACTOR (Iron Law)
- `verification-before-completion` — fresh evidence before declaring done
- `systematic-debugging` — reproduce → isolate mechanism → fix (no patch-by-guess)
- `writing-skills` — author new SKILLs the right way
- `requesting-code-review` / `receiving-code-review`
- `using-git-worktrees` / `finishing-a-development-branch`

### 2b. triad-dispatch (this plugin)

Single-shot cross-CLI dispatch with a self-improving repair loop + cross-family
review. Add it (internal mirror or local folder) and install:

```
/plugin marketplace add <internal-ghe-url-or-local-path>
/plugin install triad-dispatch@triad-internal-tools
```

Skills you will actually invoke (Codex+Gemini+Claude env):

- **`triad-codex-dispatch`** — "call codex once" with classification routing +
  auto repair-agent on unknown failures. Also `--task code` (codex as an
  isolated TDD implementer the leader verifies).
- **`triad-gemini-dispatch`** — same, Gemini side (Android/docs/Google domain).
- **`triad-cross-family-review`** — the pre-merge gate: three independent
  reviewers from different model families (a Claude fresh-eye `Agent` + Codex +
  Gemini) judge a diff, suspect decisions framed as questions, fix→re-confirm
  loop. *This is the single highest-value habit to bring over* (see CLAUDE.md
  self-rule on cross-family review).

> The plugin also ships `triad-antigravity-dispatch` + an `agy` repair agent.
> With no Antigravity in this env they simply go unused; the Google review leg
> auto-falls back from agy → **gemini**, so cross-family review works as-is.

### 2c. Plugin Bash allowlist (manual — plugins cannot self-authorize)

A plugin cannot grant its own tool permissions. Add to your Claude Code
settings (`allow` list) so the wrappers run without a prompt each time:

```
Bash(codex_wrapper.py:*)
Bash(gemini_wrapper.py:*)
```

### 2d. Updating to a new plugin version (closed network)

An *already-installed* plugin does not update itself in a closed network. When a
new build is published you re-sync the source, then refresh + update.

> **Version gotcha (read first):** Claude Code gates updates on the plugin
> `version` string — **if the new build's version equals the one you already
> have, `/plugin update` and auto-update silently SKIP it** and you keep the old
> code. Our builds bump `version` in `.claude-plugin/plugin.json` +
> `marketplace.json` every release; confirm the version actually changed
> (`/plugin` shows the installed version) before/after updating.

**Path A — internal GHE mirror** (marketplace was added from a GHE URL):

1. Re-mirror the new build into your GHE (push the updated repo).
2. In Claude Code:
   ```
   /plugin marketplace update triad-internal-tools   # pull the new marketplace.json + version
   /plugin update triad-dispatch                      # fetch the new plugin build
   /reload-plugins                                    # apply without restarting Claude Code
   ```

**Path B — local folder** (marketplace was added from a directory path):

1. Overwrite the local folder's contents with the new build (or copy the build
   to a folder and re-add it — re-adding the SAME marketplace name replaces the
   old registration).
   ```
   /plugin marketplace update triad-internal-tools    # refresh from the folder path
   # — or, if you copied the build to a new path —
   /plugin marketplace add /abs/path/to/new/folder    # same name replaces the old one
   /plugin update triad-dispatch
   /reload-plugins
   ```

**Verify:** `/plugin` lists `triad-dispatch` at the new version; spot-check a
changed behavior.

> **Admin-seeded / managed installs:** if your org distributes via a seed image
> (`CLAUDE_CODE_PLUGIN_CACHE_DIR`) or `managed-settings.json`
> (`extraKnownMarketplaces` / `strictKnownMarketplaces`), `/plugin marketplace
> update` is blocked for individual users — the administrator updates the seed
> image / managed settings instead. See the GitHub Enterprise Server section of
> the Claude Code plugin docs.

---

## 3. Drop in the working-practices CLAUDE.md

Copy `CLAUDE.recommended.md` (next to this file) into your environment as the
base instruction doc:

- **Global / cross-project**: `~/.claude/CLAUDE.md` — the working-practices core.
- **Per project**: a project-root `CLAUDE.md` that *extends* it with that
  project's specifics (build/test commands, layout, domain rules).

Read its header — it explains which sections are universal and which you should
tailor.

---

## 4. Verify the setup

```bash
# CLIs resolve + authed
codex --version && gemini --version && claude --version
# artifact tool baseline
rg --version && jq --version && shellcheck --version && bash --version | head -1
# dispatch wrapper smoke (after plugin install — bin/ is on PATH)
codex_wrapper.py --prompt 'reply with OK'        # expects a one-line answer
gemini_wrapper.py --prompt 'reply with OK'
```

In a Claude Code session, confirm the skills are visible:
`/plugin` → marketplace + installed plugins listed; ask Claude to "use
triad-codex-dispatch to ask codex a quick question" and watch it route.

---

## 5. What "optimized like our pairing" actually means

The tools above are necessary but not sufficient. The *practices* in
`CLAUDE.recommended.md` are what made the collaboration work:

1. **Explain-then-ask before non-trivial actions** (pair discipline, not vibe).
2. **TDD-strict** — a failing test first; the test exists to expose real defects,
   not to be green.
3. **Cross-family review before merge** — different model families catch each
   other's blind spots (repeatedly proven: a same-family review chain passed
   issues that Codex/Gemini independently caught).
4. **Tier-1 lookup, never guess** flags/config — in a closed network, that means
   approved mirrors/cached vendor docs; if unsure, stop and ask.
5. **Artifacts must run on Ubuntu 24.04** — unversioned shebangs, apt-available
   tools only.

Bring the tools *and* the habits. The habits are the optimization.
