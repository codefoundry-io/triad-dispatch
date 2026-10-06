> 🌐 **한국어 문서: [README.ko.md](./README.ko.md)**

# triad-dispatch

**Your AI coding assistant shares blind spots with its own reviewers.** Ask
Claude to check Claude's work and it inherits the same framing — the reasoning
that produced the bug is the reasoning that reviews it. triad-dispatch gets you a
second and third opinion from a **different model family**: from your Claude Code
session you dispatch **codex** (OpenAI) and **antigravity / `agy`** (Google) as
single-shot workers, and before you merge a risky change you run a review where
each family independently challenges the decision — so the bug your main model
rationalized away gets caught by a model that never had that blind spot.

You add it to Claude Code as a plugin. You keep working in Claude Code; when a
question needs an outside opinion, or a change is risky enough to merge-block,
the assistant reaches out to the other families for you.

> **Sibling product:** if your team leads with the **codex** CLI instead of
> Claude Code, see **[triad-codex-dispatch](https://github.com/codefoundry-io/triad-codex-dispatch)**
> — the same three-family model with codex as the driver. This one is for a
> Claude Code driver.

## Your first dispatch (2 minutes)

After [Install](#install) + the [permission allowlist](#permission-setup-required),
ask Claude Code, in a normal turn:

> Use triad-codex-dispatch to ask codex: what does `git rebase --onto` do? One paragraph.

Claude runs the `triad-codex-dispatch` skill, which shells out to the codex
wrapper and returns codex's answer. You will see a one-line success summary on
stderr that looks like this:

```
[wrapper] codex ok exit=0 vendor=0 elapsed=6.4s
```

- `[wrapper] codex` — which worker ran.
- `ok` — the classification (a clean answer; other values like
  `oauth-env` or `server-capacity` name a specific failure — see
  [Troubleshooting](#troubleshooting)).
- `exit=0` — success. Followed by codex's answer as the reply.

That `[wrapper] <cli> ok …` line is your signal the dispatch worked. If you see it
and an answer, the plugin is live. Swap `triad-codex-dispatch` for
`triad-antigravity-dispatch` to try the Google-family (`agy`) leg the same way.

## Required (~2 minutes)

Four steps get you a working install. Everything past this section is optional.

1. **Install + log in to ONE worker CLI.** You need at least one non-Claude
   family to dispatch to; add the others later (see [Optional](#optional--advanced)).
   Pick the one you have access to and use its native login — the wrappers never
   manage auth:
   - `codex` (OpenAI) — install, then `codex login`.
   - **Google family** — `agy` (Antigravity), install + OAuth sign-in, for
     individual Google access; or `gemini` (Gemini CLI) + your org sign-in for
     enterprise / organization Gemini access. The Gemini CLI *individual* tier is
     deprecated (migrated to the Antigravity suite), so use `agy` there; the
     **enterprise** Gemini tier stays in use.

   You also need **`python3 >= 3.12`** on PATH (the wrappers run via
   `#!/usr/bin/env python3`), **pydantic 2.x** (`'pydantic>=2,<3'`) importable by that same
   `python3` (the cross-family-review legs dispatch `--pydantic
   verdict_schema:LegVerdict`, and the schema uses v2-only APIs), the
   cross-family review's **jsonschema** (Draft 2020-12;
   Mac `pip3 install jsonschema`, Ubuntu 24.04 `apt install python3-jsonschema`) — without
   it the review helper stops with exit 64 and that install hint — and a
   **recent Claude Code** — new enough for plugin marketplaces and namespaced
   plugin skills. The claude review leg is an in-session `Agent`, so it needs
   no separate login.

   > **Ubuntu 24.04 note.** `apt install python3-pydantic` gives **1.10**, which
   > does NOT work, and PEP 668 marks the system interpreter externally-managed
   > so `pip3 install --user` aborts. Use a venv that still sees apt's
   > `python3-jsonschema` — `python3 -m venv --system-site-packages ~/.venvs/triad
   > && ~/.venvs/triad/bin/pip install 'pydantic>=2,<3'` (the venv's pydantic 2
   > comes first on `sys.path`) — and activate it in the
   > shell that launches Claude Code, so `#!/usr/bin/env python3` resolves to the
   > venv interpreter. To install from a local wheel set instead of an index,
   > add `--no-index --find-links <wheel-dir>` to that same command. **That set is FIVE wheels, not three** — pydantic 2.x's
   > full runtime closure: `pydantic-2.x-py3-none-any.whl` +
   > `pydantic_core-*-cp312-*manylinux*.whl` (pinned `==` by the pydantic release)
   > + `typing_extensions-*.whl` + `annotated_types-*.whl` (>= 0.6) +
   > `typing_inspection-*.whl` (>= 0.4.2, required from pydantic 2.10 on).
   > `pip download 'pydantic>=2,<3' --only-binary=:all:
   > --platform manylinux_2_17_x86_64 --python-version 312 -d <dir>` produces
   > exactly that set.

2. **Add the plugin.**

   ```
   /plugin marketplace add codefoundry-io/triad-dispatch
   /plugin install triad-dispatch@triad-dispatch
   ```

   The repo is public — installing needs no special auth.

3. **Grant the wrapper Bash permissions (one command).** A plugin cannot grant
   Bash permissions, so the wrapper commands must be allow-listed in your
   `.claude/settings.json`. This script does it for you — deterministic,
   idempotent, safe to re-run:

   ```bash
   python3 <plugin-dir>/scripts/setup_permissions.py
   ```

   Run it from your project root (it writes `./.claude/settings.json`, creating it
   if absent, and merges the entries without duplicating). To find `<plugin-dir>`,
   ask Claude Code in a Bash tool call: `command -v codex_wrapper.py` resolves
   under the installed plugin's `bin/`; the plugin root is its parent. You can also
   point the script elsewhere with `--target <path-or-dir>`, or preview with
   `--dry-run`. The [manual allowlist](#manual-allowlist-what-the-script-does) is
   below if you prefer to edit the file yourself.

4. **Restart the session, then smoke-test.** Plugin skills and the settings
   allowlist load at session start, so reload / restart Claude Code once. Then, in
   a normal turn, ask the leader:

   > Use triad-codex-dispatch to ask codex: what does `git rebase --onto` do? One paragraph.

   An answer plus a `[wrapper] <cli> ok …` line on stderr means the install is
   live. (Swap in `triad-antigravity-dispatch` for the `agy` leg.)

That is the whole required path. Repair is automatic and needs no setup: on an
unrecognized failure the leader self-improves the classifier for you (details in
[How it works](#how-it-works) and [Security](#security)).

## Optional / Advanced

Nothing in this section is needed for a normal install. Reach for a subsection
only when its "do this ONLY if…" line applies to you.

### Add a 2nd / 3rd worker CLI

*Do this ONLY if you want cross-family review* (three independent families instead
of one worker + the claude leg). Install and log in to the other CLIs the same way
as step 1: `codex login`; `agy` OAuth sign-in; or `gemini` org sign-in
(enterprise / organization accounts only). `triad-cross-family-review` resolves
its Google-family leg at runtime (`TRIAD_GOOGLE_REVIEW_CLI`, else agy, else gemini)
and runs claude (`Agent`) + codex + that leg.

### Choose the claude review leg's model and effort

*Do this ONLY if you want the claude leg of `triad-cross-family-review` at another
effort than the default.* That leg runs as a native Claude Code subagent, and its
model and effort are fixed in its agent file. Claude Code has no per-call effort
setting, so another effort is another preset. The plugin ships these (each with a
`-web` twin of the same model and effort, which a review round with web spawns):

| `claude.agent` | model | effort |
|---|---|---|
| `cross-family-review-reviewer` (default) | `opus` | `xhigh` |
| `cross-family-review-reviewer-high` | `opus` | `high` |
| `cross-family-review-reviewer-max` | `opus` | `max` |

The model is the `opus` alias: Claude Code resolves it to the latest Opus on the
subscription login route (an `ANTHROPIC_DEFAULT_OPUS_MODEL` setting remaps it). An
older model is not selectable.

Name one in the claude entry of your project roster
`<repo>/.claude/triad-review-legs.json`, for example
`{"schema": "triad-review-legs.v2", "legs": [{"name": "claude", "claude": {"agent": "cross-family-review-reviewer-high"}}]}`.
Write the bare name: the helper adds the plugin prefix itself, and a name with
`:` or a name outside the six shipped presets (these three and their `-web`
twins) is refused before the round starts. Any other model or effort needs
another shipped preset, that is, a new plugin release. Your own Claude Code
settings — a setting that forces the subagent model, an effort environment
variable, an organization effort cap — outrank the preset's pins. Claude Code
keeps each subagent's own transcript; the plugin adds no logging for it.

### If you enable the Bash sandbox

The sandbox is **OFF by default**, so the permission allowlist from step 3 is
all a normal install needs. If you do turn it on (`/sandbox`), the setup script
already exempts the wrappers via `sandbox.excludedCommands` — they need network +
your vendor auth. To also pre-approve the vendor APIs and set a fallback, add
`sandbox.network.allowedDomains` and `allowUnsandboxedCommands` yourself; see the
[Claude Code sandboxing docs](https://code.claude.com/docs/en/sandboxing).

### Optional: daily drift checks

`bin/agy-daily-check.sh` and `bin/gemini-daily-check.sh` are optional drift
detectors — they check for CLI / model-list / skill-set drift (for example, a
Superpowers release for agy, or a gemini extension/skill change). Run them
occasionally, or wire one up to a daily cron/launchd job; each splits its exit
code into 0 (no change), 1 (actionable), and 2 (informational).
`agy-daily-check.sh` runs `agy update` only when passed `--update` (the default
run never updates) and sends no prompt; when the agy model list changed, its
report names the removed and added models — check the model pinned in your
roster entry. Neither is required for normal use — read the scripts' own header comments for exact
behavior.

### Recommended companion — Superpowers

*Do this ONLY if you want the implementer / TDD / review workflow skills.*
Superpowers is a companion skill set that pairs well with this toolkit. Install it
via its own marketplace
(`/plugin marketplace add https://github.com/obra/superpowers` then
`/plugin install superpowers`), or follow its README:
https://github.com/obra/superpowers .

- **codex**: recommended — `triad-cross-family-review` is the capstone of
  `superpowers:subagent-driven-development`.
- **gemini**: supported — gemini has native skills (`gemini skills`), so
  Superpowers installs as a companion. The bundled `gemini-daily-check.sh` tracks
  the installed skill set.
- **antigravity (agy)**: Superpowers does not yet support the Antigravity CLI — a
  future update is planned. `agy-daily-check.sh` probes daily for it.

### Extra verify steps

*Do this ONLY if the smoke test in step 4 was not enough and you want to confirm
each layer.*

- **bin on PATH** — `command -v codex_wrapper.py` resolves under the installed
  plugin's `bin/` (auto-added to PATH; no user action needed).
- **self-improving classifier** — on an unrecognized failure the matching
  wrapper-repair agent's proposal is applied to
  `~/.config/triad-dispatch/classifier-patches.json` (in your home, not the plugin
  dir); that file gains an entry and persists across plugin updates.
- **cross-family review** — run `triad-cross-family-review`; it resolves its
  Google-family leg at runtime and runs claude (`Agent`) + codex + that leg.
- **bundled tests** — `python3 <plugin-dir>/tests/test_*.py` (stdlib-only).

### Manual allowlist — what the script does

*Do this ONLY if you prefer editing the file by hand instead of running
`scripts/setup_permissions.py`.* Add these entries to `.claude/settings.json`
(or `.claude/settings.local.json`) — these are the `permissions.allow` entries
the script merges in; the script also writes `sandbox.excludedCommands`, the
hardening `env` block and two sidecar files (see
[Files this plugin writes](#files-this-plugin-writes)):

```json
{ "permissions": { "allow": [
  "Bash(codex_wrapper.py:*)",
  "Bash(gemini_wrapper.py:*)",
  "Bash(antigravity_wrapper.py:*)",
  "Bash(agy-daily-check.sh:*)",
  "Bash(gemini-daily-check.sh:*)"
] } }
```

Without the allowlist you are prompted on every dispatch (or denied when
headless). Being allow-listed and being sandboxed are **orthogonal** — the
allowlist does not exempt a command from the Bash sandbox.

The Bash sandbox is **OFF by default** (opt-in via `/sandbox`). If you enable
it, network is restricted and the wrappers — which spawn the vendor CLIs that
make authenticated API calls with your auth — must run **outside** the sandbox.
`scripts/setup_permissions.py` already adds them to `sandbox.excludedCommands`;
the manual form is:

```json
{ "sandbox": { "excludedCommands": [
  "codex_wrapper.py *",
  "gemini_wrapper.py *",
  "antigravity_wrapper.py *"
] } }
```

### Local install (from a built folder)

*Do this ONLY if you are testing a locally-built copy before publishing.* Point
`marketplace add` at the plugin directory itself — **no git repo required** (the
directory's `.claude-plugin/marketplace.json` is read; its relative `source`
resolves for local-directory adds). The path must be absolute or start with `./`:

```
/plugin marketplace add /absolute/path/to/triad-dispatch
/plugin install triad-dispatch@triad-dispatch
```

Test from a CLEAN working directory — not a checkout that already has its own
`.claude/skills/` or `agents/`. Plugin skills/agents are namespaced
(e.g. `triad-dispatch:triad-codex-dispatch`), and a project's own same-named
`.claude/skills` / `.claude/agents` **override** the plugin's — so run from a
directory without those to exercise the plugin's own copies.

### Read the security model

*Do this ONLY if you want the full threat model before relying on the toolkit.*
See [SECURITY.md](SECURITY.md) — the durable control is privilege separation, not
model trust (summarized under [Security](#security) below).

### Background auto-update rate limit

*Do this ONLY if background auto-update hits GitHub API rate limits.* Set
`GITHUB_TOKEN` in your environment to raise the limit; installing and updating
otherwise work over public GitHub as-is.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Every dispatch prompts for permission, or is denied outright (headless) | The wrapper `Bash(...)` commands are not in your allowlist | Add the entries from [Permission setup](#permission-setup-required) to `.claude/settings.json`, then **restart the session** (the allowlist loads at start). |
| A new skill/agent doesn't fire after install | Plugin skills load at session start | Restart / reload the Claude Code session once after install + settings edit. |
| Dispatch fails with `oauth-env` | The worker CLI's login expired or is missing | Re-run that vendor's native login (`codex login`, or `agy` OAuth sign-in). The wrapper never re-authenticates for you — it surfaces the signal so you log in. |
| The gemini leg fails with `IneligibleTier` (individual account) | The Gemini CLI *individual* tier is deprecated | Use the `agy` (Antigravity) leg instead — it is the Google-family leg for individual users. `gemini` is only for enterprise / org accounts. |
| A dispatch returns non-zero and you want to know what happened | Each failure has a classification + exit code | See the exit-code legend below and the classification on the `[wrapper] …` stderr line. |

**Exit-code legend** (the wrapper's process exit code; the same failure classes
appear as the word on the `[wrapper] <cli> <class> …` stderr line):

| Exit | Meaning | What to do |
|---|---|---|
| `0` | Success — the answer follows | Nothing. |
| `64` | Server capacity exhausted after retries | Transient vendor overload; wait and retry. |
| `65` | Auth / config / quota (e.g. `oauth-env`, `cli-subscription-cap`) | Re-login or wait for the quota reset — see the classification word. |
| `66` | Structured-output (`--pydantic`) schema validation failed | The model's JSON did not match the schema after one repair retry. |

## Scope & limits — what this does NOT do

Honest boundaries, so you know where the plugin stops:

- **It does NOT manage vendor auth or tokens.** No token issue/refresh, no API-key
  injection. You log in with each vendor CLI's native login; an auth-shaped error
  is surfaced for you to re-login. Keeping credentials outside the toolkit is a
  deliberate safety boundary.
- **It does NOT install OS packages.** You install the vendor CLIs and `python3`
  yourself; the plugin only orchestrates what is already on PATH.
- **The self-improving classifier is a heuristic, not an oracle.** It can route a
  genuine failure to a wrong-but-plausible class. The worst case is an *integrity*
  issue — a persistent routing mis-classification, NOT code execution (see
  [Security](#security)) — but you should periodically review the applied deltas in
  `~/.config/triad-dispatch/classifier-patches.json`.
- **Wrapper containment is process/permission-level, not OS-level confinement.**
  The read-only review leg enforces an fs-write denylist for the *known* agy tool
  surface; it is not a sandbox jail. Isolation ultimately rests on the isolated
  working directory + your review before commit.

## How it works

The mechanics, once the value above makes sense:

- **Leader / worker.** Your Claude Code session is the *leader*. When it needs an
  outside opinion it dispatches a *worker* — a single-shot call to `codex`,
  `gemini`, or `agy` — through a skill, gets one answer back, and continues. The
  worker has no memory of your session; it answers the one prompt.
- **Classification-aware routing.** Every dispatch goes through a skill, not a raw
  shell call. The wrapper tags the result with a *classification* (`ok`, or a
  named failure like `oauth-env` / `server-capacity`) so the leader reacts
  correctly instead of guessing from raw output.
- **Self-improving classifier.** When a failure doesn't match any known class, a
  read-only analyzer proposes one new rule and the leader applies it
  deterministically. The next identical failure auto-routes. This state persists
  across plugin updates in your home directory.
- **Cross-family review (the merge gate).** For a risky change, the leader fans
  out to all three families at once — each an independent reviewer — and
  consolidates their verdicts. A *leg* is just one family's slice of that fan-out.

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
  from different model families — a claude fresh-eye subagent (a shipped reviewer
  preset chosen by name; see [Choose the claude review leg's model and effort](#choose-the-claude-review-legs-model-and-effort))
  + codex + the Google-family CLI (agy or gemini, runtime-selected) — each frames the
  suspect decisions as questions; the leader consolidates
  verdicts and fixes → re-confirms until the verdict is unanimous SAFE.
- The classifier **self-improves**: an unrecognized error routes to the
  read-only wrapper-repair analyzer, which proposes one entry from the
  run-log's measured sentence; the leader applies it with `bin/apply_patch.py`
  to the persistent extension JSON, so future identical errors auto-route.

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
sub-agents propose new `error → class` entries and the leader applies them via
`bin/apply_patch.py`; the engine merges them at runtime. It is portable — a team
can curate and share it.

## Security

The durable control is **privilege separation**, not model trust. The classifier
learns from untrusted vendor run-logs, so the component that reads a run-log has
ZERO write authority: the in-session repair agent is a READ-ONLY analyzer
(harness-enforced `Read, Grep, Glob` — no Write/Edit/Bash/network) whose only
output is an inline proposal, and the leader applies it via the deterministic,
zero-LLM `bin/apply_patch.py`. "The model resists injection" is explicitly NOT
the boundary. The wrapper never manages authentication. Full threat model and
per-product enforcement: [SECURITY.md](SECURITY.md).

## Runtime Artifacts And Cleanup

Wrapper telemetry stays local and only the wrappers' own code prunes it, inside the
folders the cleanup configuration declares (`bin/cleanup-roots.default.json`, or the
project's `.claude/triad-cleanup.json`), each with its role's age floor. Runtime files
live under `bin/_logs/<cli>/` for each wrapper family (`codex`, `gemini`, `antigravity`):

- `audit.jsonl` rotates when the active file passes a size cap; at each rotation
  the oldest archives past a count / byte cap are deleted.
- Run logs live under `bin/_logs/<cli>/runs/*.json`: one per failed call (a review
  attempt writes one for every call, inside its own attempt folder). File names
  include UTC timestamp, process id, and an 8-character random UUID suffix, so
  parallel dispatches do not collide.
- Nothing deletes a run log after the repair loop: the next normal dispatch sweeps
  run logs and `.repair.json` files past the role's floor, and a cap prune deletes
  the oldest past a count / byte cap. A file younger than the floor is never pruned,
  so the run-log directory (and the read-audit directory) can stay over its cap —
  the caps do not keep the disk from filling.

Classifier patches live in `~/.config/triad-dispatch/classifier-patches.json`.
Repair agents use the adjacent lock file before editing it so concurrent repairs
do not silently overwrite each other.

### Files this plugin writes

`~/.config` below means `$XDG_CONFIG_HOME` when that is set to an absolute path
(the config home). A relative `XDG_CONFIG_HOME` is resolved by the wrappers
against the directory the wrapper command ran from; the uninstall reports it
and removes nothing there.

| scope | path | written when | removed by |
|---|---|---|---|
| project | `.claude/settings.json` — `permissions.allow`, `sandbox.excludedCommands`, `env` (and the file itself when it was absent; `--install` and `--remove` also take out the `hooks.PreToolUse` entry an earlier version wrote and its record lists; `--remove` also takes out the containers the install created once they are empty, also when you removed the entries by hand (when the install record names its settings file; for a record that names none, see [Uninstall](#uninstall) step 2), and the file it created when nothing else is left in it; a hook group you emptied by hand is left) | `scripts/setup_permissions.py` | `setup_permissions.py --remove` with the same `--target` as the install |
| project | `.claude/.triad-dispatch-managed.json` (the record of what the setup wrote, naming the one settings file it wrote; written before the settings file and completed after it, so a run that stops between the two is repaired by running the setup again; a run that changes only the record writes the record alone) | `scripts/setup_permissions.py` | `setup_permissions.py --remove` with the same `--target` as the install |
| project | `.claude/.triad-dispatch.lock` | each `setup_permissions.py --install` (a `--dry-run` preview creates none); a `--remove` holds it while it runs | `setup_permissions.py --remove` with the same `--target` as the install |
| project | `_runs/review/<date>-<slug>/` review packets and their per-round git worktrees; `_runs/review/<round name>/` rounds of the small review path, each with its git worktree | each `triad-cross-family-review` gate; for a round, `review_small.py prepare` | `review_scratch.py close <packet-dir>`; a stale packet is pruned by the next `open`; a round: `review_small.py close <round directory>`, and a round older than the review-small floor (the cleanup configuration; `TRIAD_REVIEW_SCRATCH_MAX_AGE_DAYS` may raise it) is removed by the next `prepare`; the empty `_runs/review/` directory stays |
| project | `_runs/worktrees/<name>/` git worktrees for codex write calls (`triad-codex-dispatch` § Write calls; keep `_runs/worktrees/` in the project's `.gitignore`, so a commit never stages a tree as an embedded repository) | the leader, per that paragraph; the codex wrapper removes an empty leftover folder there at the start of a call | `python3 <plugin-dir>/bin/cleanup.py remove code-worktrees _runs/worktrees/<name>` from the project's top level, after everything in the tree is committed to its branch (a tree with uncommitted or untracked changes is refused) |
| machine | `~/.config/triad-dispatch/classifier-patches.json` and `classifier-patches.json.lock` | when a repair proposal is applied | `setup_permissions.py --uninstall-machine` |
| machine | `~/.gemini/config/agents/triad-readonly-review.md` and `triad-readonly-research.md` | `bin/antigravity_wrapper.py --setup-agents` | `setup_permissions.py --uninstall-machine` |
| machine | `~/.gemini/antigravity-cli/.agy_settings.lock` | `--setup-agents`, and an agy dispatch without `--sandbox read-only` | `setup_permissions.py --uninstall-machine` |
| machine | the agy settings transaction state in `~/.gemini/antigravity-cli/`: `.agybak`, `.agy_settings.shared.json`, `.agy_settings.holders/`, and the temporary `.agybak.tmp` and `.agy_settings.shared.json.tmp` | an agy settings transaction (`--setup-agents`, an agy dispatch without `--sandbox read-only`), while it runs; a run that stops early leaves them | the transaction when it ends; when `.agybak` or `.agy_settings.shared.json` is left, run `bin/antigravity_wrapper.py --setup-agents` once (it restores the agy settings); `setup_permissions.py --uninstall-machine` removes the rest, and while `.agybak` or `.agy_settings.shared.json` is there it removes none of these and names each one that exists |
| machine | `~/.gemini/antigravity-cli/triad-daily/` and `~/.gemini/triad-daily/` | `bin/agy-daily-check.sh`, `bin/gemini-daily-check.sh` | `setup_permissions.py --uninstall-machine` |
| temporary | `$TMPDIR/codex_last_*.txt`, `$TMPDIR/codex_schema_*.json` | each codex dispatch | the wrapper after each call; what is left stays (`setup_permissions.py --uninstall-machine` lists it and removes nothing there) |
| plugin directory | `bin/_logs/<cli>/` (audit log, run logs, read-audit digests) | every dispatch | the wrappers' rotation, sweep and cap prunes above (a file younger than its role's floor stays); the plugin directory's removal |
| plugin directory | `bin/_debug/<UTC-date>/` | only with `--debug` | day directories past the `wrapper-debug` floor, by the next `--debug` call; the plugin directory's removal |

- A repair proposal is applied AUTOMATICALLY into the classifier file; nothing
  asks you first.
- `bin/agy-daily-check.sh` runs `agy update` (it changes your agy install) only
  when you pass `--update`; a plain run updates nothing and sends no prompt.
- The plugin may create these directories when they are absent and never
  removes them: `<project>/.claude/`, `<project>/_runs/`, the config home,
  `~/.gemini/`, `~/.gemini/config/`, `~/.gemini/config/agents/`,
  `~/.gemini/antigravity-cli/`.
- A location you moved with an environment variable (`TRIAD_DISPATCH_LOG_DIR`,
  `TRIAD_DEBUG_DIR`, `TRIAD_CLASSIFIER_EXTENSION`, `AGY_DAILY_STATE`,
  `GEMINI_DAILY_STATE`, `AGY_SETTINGS_PATH`, `AGY_AGENTS_DIR`,
  `TRIAD_READ_AUDIT_FILE`) is yours:
  nothing removes it. `TRIAD_READ_AUDIT_FILE` names a read-audit file the caller
  chose; the review helper puts it inside the review packet, which `close`
  removes.
- While a file is being written, a temporary file of a similar name sits beside
  it for a moment; a run that ends normally leaves none.
- The machine-scope paths are shared by every triad-dispatch build on the
  machine (a second checkout, the source tree): after uninstalling one build,
  run `bin/antigravity_wrapper.py --setup-agents` in the other.
- The uninstall leaves an item that is a symlink, and a plugin-named directory
  (`triad-dispatch/`, `triad-daily/`) that is a symlink. A symlinked parent
  (`~/.config`, `~/.gemini`) is your layout: the wrappers wrote through it, so
  the uninstall removes through it. The uninstall removes nothing in the shared
  temporary directory.
- The vendor CLIs' own session and history stores are not the plugin's; the
  uninstall does not touch them.

### Uninstall

Run these steps in this order. When the host's plugin uninstall ran first and
`scripts/setup_permissions.py` is gone, no code of the plugin is left to remove
the paths in [Files this plugin writes](#files-this-plugin-writes): they stay, and
they are yours.

1. **Close any open review packet and any open round of the small review path**:
   `python3 <plugin-dir>/skills/triad-cross-family-review/lib/review_scratch.py close <packet-dir>`;
   `python3 <plugin-dir>/skills/triad-cross-family-review/lib/review_small.py close <round directory>`.
2. **In EACH project where you ran the setup**:
   `python3 <plugin-dir>/scripts/setup_permissions.py --remove` with the SAME
   `--target` you gave `--install` (none, when you ran the setup from the project
   root). The record of what the setup wrote names the one settings file the
   install wrote: `--remove` with another `--target` changes nothing and names
   that file. A record written by an older version names no file: when none of
   its entries is in the target, `--remove` and `--install` change nothing and
   say so — give the `--target` that install used. Neither command removes such
   a record while none of its entries is found: entries taken out by hand cannot
   be told from entries in another settings file of that directory; the kept record is
   yours. An entry of the plugin's that is in the
   settings file and in no record (the record was deleted, or an earlier version
   wrote it) is treated as yours, and neither command removes it: `--install`
   and `--remove` both name it — the grants, sandbox patterns and env keys (by
   name) in one note, and a PreToolUse handler whose command contains the hook's
   file name in a `left <target>: hook <command>` line — edit it out of the settings file yourself. A
   record that lists nothing is removed by `--remove` also when the settings
   file cannot be read; a `left <target>: <reason>` line says the file was not
   checked. Do this BEFORE
   the host uninstall, which deletes this script. A project an EARLIER version
   set up holds a `hooks.PreToolUse` entry pinned to that version's directory;
   once the host deletes that directory, every shell command of the project
   fails. After updating the plugin, run `setup_permissions.py` once, with the
   same `--target` as the install, in each project an earlier version set up: it
   takes out that hook entry.
3. **Remove the scheduled daily check** — the cron or launchd entry that runs
   `agy-daily-check.sh` or `gemini-daily-check.sh`, if you made one. Do this
   BEFORE the next step: a scheduled run writes the daily-check state again.
4. **ONCE per machine, after the last project**:
   `python3 <plugin-dir>/scripts/setup_permissions.py --uninstall-machine`. It
   prints `removed <path>` or `left <path>: <reason>` per item (a recorded agy
   settings transaction is left whole, each of its items named); `--dry-run`
   previews it. It removes nothing in the shared temporary directory, which holds
   no record of what is the plugin's: it lists the codex temporary entries there;
   they are yours to remove.
5. **The host steps.** From a shell:

   ```
   claude plugin uninstall triad-dispatch@triad-dispatch
   claude plugin marketplace remove triad-dispatch
   ```

   In a session: `/plugin uninstall triad-dispatch@triad-dispatch`, then
   `/plugin marketplace remove triad-dispatch`. The uninstall removes the plugin's
   entry from your settings and its data directory. The cached plugin directory —
   which holds `bin/_logs` and `bin/_debug` — is marked and removed by a background
   clean-up 14 days later, and that clean-up runs only while at least one plugin
   is still installed: when this was your last plugin,
   `~/.claude/plugins/cache/triad-dispatch/` stays. Removing the marketplace
   also uninstalls every plugin installed from it.
6. **What stays — yours**: the `_runs/review/` and `_runs/worktrees/` lines in `.gitignore`; roster files
   (`.claude/triad-review-legs.json`, `~/.config/triad/review-legs.json`); review
   ledgers under `docs/reviews/`; anything you added to `~/.claude/CLAUDE.md` from
   `migration/CLAUDE.recommended.md`.

## What's inside

- **skills** (4): `triad-codex-dispatch`, `triad-gemini-dispatch`,
  `triad-antigravity-dispatch`, `triad-cross-family-review`.
- **agents** (9): `codex-wrapper-repair`, `gemini-wrapper-repair`, `agy-wrapper-repair`,
  and the six claude review presets (see [Choose the claude review leg's model and effort](#choose-the-claude-review-legs-model-and-effort)).
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
