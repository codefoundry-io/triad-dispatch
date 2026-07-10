# Direct `codex exec` knowledge — sandbox grants, execpolicy rules, skills

Reference for invocations the wrapper cannot express (it pins `--ephemeral` and
exposes no `--add-dir` / arbitrary `-c` passthrough). Loaded on demand from
`triad-codex-dispatch/SKILL.md`.


(Verified against the official codex skills doc — developers.openai.com/codex/skills
— and the installed `codex` CLI help.)

The wrapper covers single-shot Q&A / `--task` dispatches. Some invocations
are NOT expressible through the wrapper — it pins `--ephemeral` (ephemeral
threads do not support `/goal`) and exposes no `--add-dir` / arbitrary `-c`
passthrough. For those, the leader (or a project-side skill, e.g.
a lab project's `codex-tc-writer`) builds a direct `codex exec` invocation.
Keep these facts straight instead of re-deriving them from memory:

### Extra writable roots (multiple workspaces)

- `--add-dir <DIR>` — additional writable directory alongside the primary
  workspace. **Repeatable** (one flag per dir). Official docs recommend it
  over widening the sandbox level.
- Config-equivalent: `-c 'sandbox_workspace_write.writable_roots=["/a","/b"]'`
  — TOML value, not JSON.
- `/tmp` (and `$TMPDIR`) are writable BY DEFAULT in `workspace-write` — the
  config keys `sandbox_workspace_write.exclude_slash_tmp` /
  `exclude_tmpdir_env_var` exist precisely as opt-OUTs. An explicit
  `--add-dir /tmp/<dir>` is still good practice:
  it pins the output dir as intent and survives a user config that sets
  `exclude_slash_tmp=true`.
- Loopback/network inside `workspace-write` is OFF by default; opt in with
  `-c sandbox_workspace_write.network_access=true` (e.g. the adb server on
  127.0.0.1:5037). Opted-in network = the sandbox is no longer a no-egress
  guarantee.
- Even under `workspace-write`, `<root>/.git`, `.codex`, and `.agents` stay
  recursively read-only.

### Running/saving OUTSIDE the sandbox — execpolicy prefix rules

- Mechanism: `.rules` files (user `~/.codex/rules/*.rules` or project-level)
  carry allow-prefix entries that let a named command run OUTSIDE the
  sandbox (e.g. `allow prefix: <cmd>`). Validate a rules file with
  `codex execpolicy check --rules <file>`; `codex exec --ignore-rules`
  skips loading user/project rules files.
- Prefer-narrow rule: when the helper only needs
  extra file writes + loopback, `--add-dir` + `network_access=true` keeps it
  INSIDE `workspace-write` — narrower than a prefix rule and no config-file
  side effects. Reach for prefix rules only when the command genuinely
  cannot run sandboxed.

### Skills — storage locations + explicit invocation

- Discovery scopes (official): `$CWD/.agents/skills` → parent dirs within
  the git repo → `$REPO_ROOT/.agents/skills` → user `$HOME/.agents/skills`
  → admin `/etc/codex/skills` → bundled system skills. NOTE: the user-level
  dir is `~/.agents/skills`, NOT `~/.codex/skills` (an empty `~/.codex/skills/`
  may exist on a machine — it is not a discovery path).
- A skill = `<scope>/<name>/SKILL.md` + optional `agents/openai.yaml`
  metadata (`allow_implicit_invocation` — default true, `interface`,
  `dependencies`). Per-skill disable via `[[skills.config]]` in
  `~/.codex/config.toml`.
- Explicit invocation in exec: prepend `$<skill-name>` to the prompt,
  **single-quoted** so the shell does not expand it:
  `codex exec … '$my-skill <prompt text>'` (`$my-skill` is a codex skill
  reference, not a shell variable). Interactive equivalents: `/skills` or
  typing `$`.
- Run `codex exec` from the repo root (or below it) so repo-scope skills
  are discovered; `< /dev/null` guards against codex exec blocking on
  piped stdin.

### Wrapper boundary (why these are not wrapper flags)

- `codex_wrapper.py` pins `--ephemeral`; a `/goal`-driving or skill-invoking
  dispatch must be a direct `codex exec` WITHOUT `--ephemeral`.
- `--add-dir` / arbitrary `-c` passthrough is NOT implemented in the wrapper
  (candidate follow-up; in the source repo this triggers the doc-sync chain).
- Proven instance: a lab-project repo
  `.claude/skills/codex-tc-writer/SKILL.md` (leader dispatch procedure) +
  `.claude/skills/nl-to-yaml-author/references/cross-cli.md` (v5 flag notes).

