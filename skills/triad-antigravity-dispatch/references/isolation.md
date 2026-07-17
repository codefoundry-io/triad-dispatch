# agy isolation reference — tool→action map, deny lists, operational notes

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` § Isolation.
Read this before changing a sandbox mode, auditing the deny surface, or
diagnosing a settings-transaction failure.

> **⚠️ agy ≥1.1.3 — the entire deny model below is NEUTERED at runtime.**
> On agy ≥1.1.3 the wrapper inserts `--dangerously-skip-permissions` (headless
> soft-deny adaptation — SKILL.md § Headless soft-deny adaptation), which VOIDS
> the deny transaction AND agy's `--sandbox` OS-ring (agy issue #36): every
> `deny` below (`write_file`/`command`/`unsandboxed`/`execute_url`/`mcp`) is
> auto-approved. So on ≥1.1.3 the "enforced read-only worker" language in this
> file describes only ≤1.1.2. (Note the floor OVER-applies: even a future
> ≥1.1.3 release that restores the allow-list still trips the gate until a
> human narrows the floor.) On ≥1.1.3 the leg is read-only by INTENT, not
> enforcement; the owner-accepted residual = agy can run a `command` that reads
> sensitive files OUTSIDE `--cwd` (`~/.ssh`, tokens) and exfiltrate over the
> network — the disposable `--cwd` does NOT contain either. A strict deployment
> that cannot accept that residual must EITHER set `AGY_NO_HEADLESS_AUTOAPPROVE=1`
> (keeps the deny model; agy then unusable headless) OR run the ≥1.1.3 dispatch
> inside an EXTERNAL fs-scoped + network-denied OS sandbox. Full caveat: SKILL's
> § Headless soft-deny adaptation.

**agy tool → permission action map** — re-confirm against your installed agy with
`agy -p "list your built-in tools and their permission actions"`. The write path
is exactly write_to_file / replace_file_content / multi_replace_file_content →
`write_file`, so the per-verb denylist below is complete for the known surface.
Denies for `execute_url` / `mcp` are kept even when they do not appear in the
self-reported inventory (denying an absent action is a no-op and protective if
they return). Non-resource tools (`generate_image`, `send_message`,
`manage_task`, `manage_subagents`, `list_permissions`, `ask_permission`) report
no permission action; `generate_image`'s artifact write path is UNVERIFIED
against the `write_file` gate (self-report only), covered by the standing
mitigation (isolated worktree cwd + leader verify/commit):

| agy tool | permission action | notes |
|---|---|---|
| `view_file` / `list_dir` / `grep_search` | `read_file` | native reads (NOT shell) — auto-allowed in workspace |
| `write_to_file` / `replace_file_content` / `multi_replace_file_content` | `write_file` | governed per-call by the deny transaction |
| `run_command` | `command` OR `unsandboxed` | BOTH denied in read-only; `unsandboxed(*)` also denied in workspace-write (OS-ring escape) |
| `execute_url` (code-exec-from-URL) | `execute_url` | denied in **BOTH** read-only AND workspace-write |
| `mcp` (MCP server reach) | `mcp` | denied in **BOTH** read-only AND workspace-write |
| `read_url_content` / `search_web` | `read_url` | **always allowed** (never denied) — agy's search/research advantage; the ONLY web access left in either mode |
| `invoke_subagent` / `ask_question` / `schedule` | (no resource permission) | not gated by `permissions.deny` |

`run_command` maps to EITHER the `command` OR the `unsandboxed` action, so the
deny sets enumerate **both** — a command run "unsandboxed" (escaping the OS
sandbox ring) is blocked in read-only AND workspace-write (`unsandboxed(*)`).
`execute_url(*)` (code-exec-from-URL) and `mcp(*)` (MCP server reach) are likewise
denied in **BOTH** modes, so `read_url` (search / web fetch) is the **one and only**
web access the transaction ever leaves allowed (§ Routing) — `execute_url` and
`mcp` are never permitted under either `--sandbox` mode.

- `read-only` — `deny:[write_file(*),command(*),unsandboxed(*),execute_url(*),mcp(*)]`
  (`unsandboxed(*)` is the second `run_command` action — see the tool→action map).
  The
  `write_file` block is **proven headless**; the `command` / `execute_url` /
  `mcp` denies apply the *same* deny mechanism but are not each individually
  spike-verified. Deny is a **per-verb denylist**, so an agy mutation verb NOT
  enumerated here (e.g. a future `edit_file` / `apply_patch`) would not be
  blocked — this is strong fs-write isolation for the *known* agy tool surface,
  not OS-level process isolation. Treat the agy read-only leg of
  `triad-cross-family-review` as an enforced read-only worker for the proven
  write path **on agy ≤1.1.2 only** (on ≥1.1.3 the skip-perms gate voids this —
  see the top banner); the owner's manual e2e should ALSO attempt a `command(...)` and an
  `mcp(...)` mutation to confirm those denies on the live build.
- `workspace-write` — dangerous-path/command denies (incl. `unsandboxed(*)` so a
  command cannot escape the OS sandbox ring, plus `execute_url(*)` + `mcp(*)` —
  denied here exactly as in read-only, so `read_url`/`search_web` stays the only
  permitted web access in this mode too) + agy `--sandbox` + a
  leader-supplied isolated git worktree as `--cwd` (**required**; the wrapper
  rejects a missing / relative / non-existent `--cwd` with `EXIT_ARG_ERROR`,
  but worktree-ness itself is the leader's responsibility). **Residual** (codex
  `--task code` parity): a `write_file` can still target outside the worktree
  because Deny>Allow precedence makes a confine-to-cwd whitelist impossible — the
  worktree cwd + leader verify/commit is the mitigation.
- omitted — no deny transaction; the owner's permissive global baseline is left
  intact (the call still acquires the lock + heals a stale `.agybak`, see below).

agy `--sandbox` alone is shell/network OS-ring only (does NOT block `write_file`);
the deny transaction is what enforces fs isolation. `toolPermission` presets are
NOT exposed — they auto-proceed in headless (no TTY to prompt) and would imply a
guarantee that does not exist. Reasoning tier = `--model "<family> (<tier>)"`
passthrough (no-pin default when omitted); owl subagents (a `--task`
equivalent) are not currently used by the wrapper.

**Operational notes**:
- *Stale-sentinel recovery* — the transaction restores via a `.agybak` crash
  sentinel healed on the *next* agy call (EVERY call, including a permissive
  one, acquires the lock and heals first). If an agy call crashes and **no**
  subsequent agy call runs, the owner's global `settings.json` stays in the deny
  state. If interactive `agy` suddenly cannot write files, remove a stale
  `~/.gemini/antigravity-cli/.agybak`. Writes are atomic (temp + `os.replace`),
  so the file is never left half-written.
- *workspace-write deny list is illustrative* — `.git/`, `~/.gemini`, `~/.ssh`,
  `~/.aws`, `rm -rf`, `sudo`, `curl` is a hand-picked danger list, **not** a
  confinement boundary (paths like `~/.bashrc` / `~/.config` stay writable).
  Safety rests on the isolated worktree `--cwd` + leader verify/commit, not the
  list. (`~/.gemini` is denied specifically to stop a worker rewriting its own
  deny rules.)
