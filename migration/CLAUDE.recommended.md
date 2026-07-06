# CLAUDE.md — working-practices base

> Drop this into `~/.claude/CLAUDE.md` (global) and/or extend it in a
> project-root `CLAUDE.md`. It encodes the *habits* that make the human↔Claude
> pair effective — distilled to what transfers across projects. Sections marked
> **[tailor]** are placeholders to fill per project; the rest are universal.
>
> Environment assumed: a POSIX shell with the vendor CLIs = Codex + a
> Google-family CLI (Gemini CLI or Antigravity/agy) + Claude Code. The
> `triad-dispatch` plugin provides the cross-CLI dispatch + review skills
> referenced below.
>
> **Gemini leg prerequisites (post-2026-06-18):** the Gemini CLI serves only
> Code Assist Standard/Enterprise licenses or API-key/Vertex auth — personal
> Google-account OAuth is deprecated (`IneligibleTierError`; individual users
> were migrated to Antigravity). Enterprise users: sign in with the org
> account and set `GOOGLE_CLOUD_PROJECT` (or use `GEMINI_API_KEY`/Vertex).
> Individual users: use the `triad-antigravity-dispatch` (agy) leg instead —
> the review skill selects the available Google-family CLI at runtime. A
> wrapper dispatch failing with classification `oauth-env` (exit 65) is this
> auth boundary, not a bug.

## Pre-execution discipline

Before any non-trivial command (scripts, multi-step ops, file creation, external
CLI/network calls, sub-agent dispatch, retries):

1. **Explain in 3-5 lines** — what, where (paths), expected outcome.
2. **Ask "OK to proceed?"** and list any open decisions.
3. **Only run after explicit OK.**

No "just one more test" without explaining it first. If a step fails, explain the
proposed fix and ask before retrying — **no auto-retry**. **At the second
failure, STOP and ask.** This is pair coding, not autopilot.

**Exceptions** — read-only ops (`rg`, `ls`, Read, a single doc lookup); a trivial
command already authorized in this conversation.

## Vendor CLI cost is not a constraint

Codex / Gemini / Claude Code subscription limits are high and the CLIs cap
gracefully (they stop at the limit; no overage). Never skip or weaken real
tests/verification to "save tokens". Quality and thoroughness over token economy.
Pre-execution discipline still applies — but cost is never the reason to hold back.

## Testing discipline — the test is a tool, the subject's quality is the point

A test case exists to **find defects in and improve the thing under test** —
not to be authored or to go green for its own sake.

- **TDD-strict (RED → GREEN → REFACTOR)**: write the failing test first; watch it
  fail for the right reason; minimal code to pass; refactor.
- **Verification before completion**: declare "done" only on *fresh evidence*
  (a real run), never "should pass".
- When a test reveals a deeper problem, **fix the root cause** — do not weaken the
  test's expectation, add a forced timeout, insert sleep/race margins, or
  bypass the assertion. Those hide the defect. Record the finding, fix the
  subject, then return to the test.
- **Fixture lifecycle**: every test sets up its own isolated resources and tears
  them down (own IDs, `trap ... EXIT INT TERM`); never rely on a shared cleaner.
- **Flake check**: run the suspect area twice (`--rounds=2` or equivalent) and
  require **0 flakes** before committing.

## Cross-family review before merge (highest-value habit)

For review-worthy or correctness/security-critical work — *especially* when you
chose to omit or simplify something from a vetted source — run **three
independent reviewers from different model families**, not one:

1. a **Claude fresh-eye sub-agent** (a general-purpose `Agent`, NOT the leader
   reasoning in-line — the leader shares its own blind spot),
2. **Codex** via `triad-codex-dispatch`,
3. **Gemini** via `triad-gemini-dispatch` (or `triad-cross-family-review`, which
   orchestrates all three).

Rules: **frame suspect decisions as QUESTIONS** ("is X actually safe to omit?"),
never as settled facts. **Any** reviewer's Critical/DO-NOT-MERGE blocks the
merge. Findings → fix each → **re-run the 3-way** on the fixed branch until
unanimous SAFE. Same-family-only review inherits the author's framing and misses
the author's blind spot; cross-family is what breaks the monoculture (this pays
off repeatedly — a finding one family rates "safe" is often the exact thing
another family catches).

When dispatching a vendor CLI as a review leg: tell it to **review by READING
only — do not run scripts/tests or spawn CLIs** (a sandboxed agentic reviewer can
live-run the code and hang). Put any context file at a **repo-relative gitignored
path**, never `/tmp` (sandboxed reviewers can't read outside the workspace). For
the **Codex** leg specifically, if a read-only sandbox can't read the files,
**embed the diff/context inline** in the prompt.

## Lookup priority for CLI / command facts

1. **Tier 1** — official sources (vendor docs, repo README/CHANGELOG, recent
   issues).
2. **Tier 2** — `--help` of the installed binary.
3. **Tier 3** — local notes.

**Never guess** flags / config keys / schema. If none gives a clear answer,
**stop and ask**. When a command fails, run the full Tier 1→2→3 lookup *before*
the next attempt — don't patch-by-guess across turns. Cite which tier a fact came
from. CLIs change often; re-verify rather than trust memory.

## Artifact cross-platform compatibility

The working environment may use convenience tools freely, but **artifacts**
(`.sh` / `.py` / config / tests / lib committed to a repo) must run identically
on the target/deployment environment, not just the dev machine.

- **Bash**: `#!/usr/bin/env bash`, target **5.x** features. Never `#!/bin/bash`
  pinned to an old version.
- **Python**: `#!/usr/bin/env python3`, target **3.12**. No version pinning in
  shebangs.
- **Artifact-callable tools only** (packaged on both dev and target, identical
  syntax): `rg` `fd` `jq` `yq`(Go binary) `shellcheck` `shfmt` `ruff` `expect`
  `parallel` `pv` `tokei` `difft` `git` `bash` `python3`. **Never** call from
  artifacts: platform-specific (`osascript` `open` `pbcopy`), interactive-only
  (`fzf` `lazygit`), shell-hook tools (`direnv`), or `httpie` (use the vendor
  CLI, not raw HTTP).
- Verify a new artifact command resolves on the target (`which <cmd>`) and
  document its install path before adding it.

## Sandbox choices

Claude Code's Bash sandbox is **OFF by default** — simpler, and relies on the
permission allowlist for safety. Turning it ON adds OS-level isolation, but
the wrapper commands must then run **outside** it (the setup script already
adds them to `sandbox.excludedCommands`, since they need network + vendor
auth). For a dispatch-plugin setup like this one, OFF is the simpler default.
See https://code.claude.com/docs/en/sandboxing.md for the full model.

## Sub-agents and AI calls — minimum-judgment only

Put AI calls only where a deterministic program *cannot* do the job (semantic
judgment, free-form classification, vision, code-intent review). Anything
deterministic — pane/dialog/file-existence checks, routing, parameter lookup,
env validation — goes to regex/parser/bash, **not** an AI call. Libraries and
SKILL helpers stay AI-free; a sub-agent dispatch is the leader's explicit
decision at call time, not buried inside a helper. Delegate to a sub-agent only
when it genuinely **saves leader context** (small prompt in, small summary out,
the agent fetches the heavy data itself).

## Language

- **Conversation with the user: Korean.** Switch to English for code, file
  content, command output, error messages, and technical artifacts.
- **Instruction docs (this file, SKILL.md, knowledge docs): English-dominant**,
  Korean only for a specific term or short emphasis.
- Avoid emoji in files unless asked. Prefer relative paths in committed
  code/scripts; absolute paths only in docs that intentionally cite a layout.

## Surfacing changes (when an IDE is connected)

When a VS Code / IDE session is connected, never edit silently — open a
`code --diff` of the change (or list the changed files with a one-line
what-changed each) and report clickable paths, so every change is reviewable.
Flag changes made inside a gitignored or nested-repo subdir (they won't appear in
the parent repo's source-control view).

## Memory

Keep a persistent note of decisions/discoveries that are **not** derivable from
the code or git history — user preferences, the *why* behind a non-obvious
choice, ongoing project constraints. Don't save what the repo already records.
Verify a remembered file/flag still exists before acting on it.

## Compaction

When context fills, wrap up at a task boundary (not mid-task): confirm the tree
is clean (commit pending work), refresh README/docs/memory for anything this
session changed, then compact.

---

## [tailor] Project specifics

Fill these per project (this section is a stub):

- **Build / test commands**: <how to build, the single test launcher, per-tier
  scope, time budget>
- **Repo layout**: <where the real code lives — a mental map>
- **Domain rules**: <framework/library conventions, safety invariants, what NOT
  to touch>
- **Leader / dispatch policy**: <who is the leader CLI here; when to dispatch
  Codex vs Gemini vs an in-process Claude sub-agent>
- **Safety invariants**: <never force-push protected branches without sign-off;
  never commit secrets / local settings; held files that must not be staged>
