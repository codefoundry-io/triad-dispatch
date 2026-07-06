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

## Requirements

- A **recent Claude Code** — one new enough to support plugin marketplaces
  (`/plugin marketplace add` + install), namespaced plugin skills, and
  harness-enforced subagent `tools:` allowlists (the security control below relies
  on that allowlist). Older releases fail these opaquely; if `/plugin marketplace`
  is unavailable, update Claude Code first.
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

## Setup checklist (do these in order)

A fresh owner reproduces the working setup with these three steps. The split is
**manual login (human) → config → automatic repair** — the wrapper NEVER manages
tokens (a deliberate safety boundary; see [SECURITY.md](SECURITY.md)).

1. **One-time manual login (human) — WORKER CLIs only.** Log in to each worker CLI
   this plugin dispatches, using the vendor's native login (the wrappers issue no
   tokens and refresh no credentials):
   - `codex` — `codex login`.
   - `agy` (Antigravity) — OAuth sign-in, for individual Google-family access.
   - `gemini` — your org sign-in, for enterprise / organization Gemini access.
   The **claude** leg is the in-session leader (and the review's fresh-eye
   `Agent`), so it needs NO separate login.
2. **Config — the Bash permission allowlist.** Add the wrapper `Bash(...)` entries
   to your `.claude/settings.json` (see Permission setup below). A plugin cannot
   grant Bash permissions, so this one manual config step is required; without it
   every dispatch prompts (or is denied when headless).
3. **Repair is AUTOMATIC in-session — no manual step.** On an unrecognized failure
   the leader dispatches the matching wrapper-repair agent, a READ-ONLY analyzer
   (`Read, Grep, Glob` only — no write) that returns an inline proposal; the
   leader applies it via `bin/apply_patch.py` (the deterministic, zero-LLM
   applier). You do nothing — the classifier self-improves. The analyzer that
   reads the untrusted run-log has zero write authority by design.

**Then restart the Claude Code session.** Plugin skills and the `.claude/settings.json`
permission allowlist load at session start, so after installing the plugin and
editing settings, reload / restart Claude Code once. Until you do, the new skills
may not fire and every dispatch will still prompt.

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
| `69` | A code task was blocked / needs more context (codex `--task code`) | Provide the missing context and re-dispatch. |

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
