# agy isolation reference — tool→action map, deny lists, operational notes

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` § Isolation.
Read this before changing a sandbox mode, auditing the deny surface, or
diagnosing a settings-transaction failure.

> **UPDATE (2026-07-25, live differential probe on agy 1.1.7): the deny model
> below ENFORCES again on current builds — `read-only` BLOCKED `write_file`
> headless while the permissive baseline wrote; `read_url`/`search_web`
> stayed allowed under `read-only` (probed). The vendor fixed the soft-deny
> void at some version ≤1.1.7 (boundary unknown). The banner below describes
> the 1.1.3-era soft-deny WINDOW and stays as the conservative floor for
> older builds; agy also self-reported the denied write as done — verify
> arrival, always.**
>
> **⚠️ agy ≥1.1.3 (soft-deny window) — the deny model below was NEUTERED at runtime.**
> On agy ≥1.1.3 the wrapper inserts `--dangerously-skip-permissions` (headless
> soft-deny adaptation — SKILL.md § Headless soft-deny adaptation), which VOIDS
> the deny transaction AND agy's `--sandbox` OS-ring (agy issue #36): every
> `deny` below (`write_file`/`command`/`unsandboxed`/`execute_url`/`mcp`) is
> auto-approved. So on ≥1.1.3 the "enforced read-only worker" language in this
> file describes only ≤1.1.2. (Note the floor OVER-applies: even a future
> ≥1.1.3 release that restores the allow-list still trips the gate until a
> human narrows the floor.) On ≥1.1.3 the leg is read-only by INTENT, not
> enforcement; the owner-accepted residual of THAT window = agy can run a
> `command` that reads sensitive files OUTSIDE `--cwd` (`~/.ssh`, tokens) —
> closed again on enforcing builds. **Independent of this window, a
> read/exfiltration residual survives BY DESIGN on every build:** `read_file`
> and `read_url`/`search_web` are never denied, so the leg can read any
> user-readable file (outside `--cwd` included) and send it over the network
> — probe-CONFIRMED on 1.1.7. `AGY_NO_HEADLESS_AUTOAPPROVE=1` does NOT close
> that; only an EXTERNAL fs-scoped + network-denied OS sandbox does. Full
> caveat: SKILL's § Headless soft-deny adaptation.

**agy tool → permission action map** — re-confirm against your installed agy with
`agy -p "list your built-in tools and their permission actions"`. The write path
is exactly write_to_file / replace_file_content / multi_replace_file_content →
`write_file`, so the per-verb denylist below is complete for the known surface.
Denies for `execute_url` / `mcp` are kept even when they do not appear in the
self-reported inventory (denying an absent action is a no-op and protective if
they return). Non-resource tools (`generate_image`, `send_message`,
`manage_task`, `manage_subagents`, `list_permissions`, `ask_permission`) report
no permission action; `generate_image`'s artifact write path is UNVERIFIED
against the `write_file` gate (self-report only), covered by the surviving
practice — run write-needing dispatches in a disposable `--cwd` and have the
leader verify results before use (isolation caveats: SKILL.md § Headless
soft-deny adaptation; the dedicated workspace-write worktree contract is
gone). This practice is UNENFORCED: nothing in the wrapper requires `--cwd`,
and agy resolves RELATIVE paths against its own scratch project, not `--cwd`
— hand it absolute paths. Note: on a NON-hardened install (a hardened one
auto-upgrades omission to `read-only` — SKILL.md § Isolation), a
write-needing agy dispatch runs as the permissive
baseline with NO deny rules and NO agy `--sandbox` OS ring — on any build
where the deny enforces (≤1.1.2, current 1.1.7-class builds, or with
`AGY_NO_HEADLESS_AUTOAPPROVE=1`) it lacks the dangerous-path,
`unsandboxed(*)`, `execute_url(*)`, and `mcp(*)` denies workspace-write used
to add (web reach is then no longer bounded to `read_url`/`search_web`):

| agy tool | permission action | notes |
|---|---|---|
| `view_file` / `list_dir` / `grep_search` | `read_file` | native reads (NOT shell) — auto-allowed in workspace |
| `write_to_file` / `replace_file_content` / `multi_replace_file_content` | `write_file` | governed per-call by the deny transaction |
| `run_command` | `command` OR `unsandboxed` | BOTH denied in read-only (`unsandboxed(*)` = OS-ring escape) |
| `execute_url` (code-exec-from-URL) | `execute_url` | denied in read-only |
| `mcp` (MCP server reach) | `mcp` | denied in read-only |
| `read_url_content` / `search_web` | `read_url` | **always allowed** (never denied) — agy's search/research advantage; the ONLY web access left even under read-only |
| `invoke_subagent` / `ask_question` / `schedule` | (no resource permission) | not gated by `permissions.deny` |

`run_command` maps to EITHER the `command` OR the `unsandboxed` action, so the
read-only deny set enumerates **both** — a command run "unsandboxed" (escaping
the OS sandbox ring) is blocked too (`unsandboxed(*)`). `execute_url(*)`
(code-exec-from-URL) and `mcp(*)` (MCP server reach) are likewise denied, so
`read_url` (search / web fetch) is the **one and only** web access the
transaction ever leaves allowed (§ Routing).

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
  write path **on agy ≤1.1.2 AND on current builds** — `write_file` and
  `command` are both probe-CONFIRMED denied on 1.1.7 (differential probes
  2026-07-25); only the 1.1.3-era soft-deny window voided this (see the
  UPDATE banner at the top). Still OWED on current builds: an
  `execute_url(...)` and an `mcp(...)` attempt to confirm those two denies.
- omitted — no deny transaction; the owner's permissive global baseline is left
  intact (the call still acquires the lock + heals a stale `.agybak`, see below).

(`workspace-write` was removed 2026-07-25 — owner directive, never used in 616
audited calls; the wrapper no longer offers a write-enabled agy mode, so
`--sandbox` now takes only `read-only`.)

agy `--sandbox` alone is shell/network OS-ring only (does NOT block `write_file`);
the deny transaction is what enforces fs isolation. `toolPermission` presets are
NOT exposed — they auto-proceed in headless (no TTY to prompt) and would imply a
guarantee that does not exist. Reasoning tier = `--model` passthrough with a
CATALOG selector from `agy models` (e.g. `gemini-3.1-pro-high`; display labels
are no longer listed); no-pin default when omitted; owl subagents (a `--task`
equivalent) are not currently used by the wrapper.

**Operational notes**:
- *Stale-sentinel recovery* — the transaction restores via a `.agybak` crash
  sentinel healed on the *next* agy call (EVERY call, including a permissive
  one, acquires the lock and heals first). If an agy call crashes and **no**
  subsequent agy call runs, the owner's global `settings.json` stays in the deny
  state. If interactive `agy` suddenly cannot write files, remove a stale
  `~/.gemini/antigravity-cli/.agybak`. Writes are atomic (temp + `os.replace`),
  so the file is never left half-written.
