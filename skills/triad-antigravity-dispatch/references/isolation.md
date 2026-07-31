# agy isolation reference — containment posture, deny model, operational notes

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` § Headless soft-deny
adaptation and § Isolation. Read this before changing a sandbox mode, auditing
the deny surface, judging what an agy leg can reach, or diagnosing a
settings-transaction failure.

## Contents

| Section | Open it when |
|---|---|
| Containment posture (start here) | deciding what a `--sandbox read-only` agy call actually contains |
| Headless soft-deny adaptation | asking why the wrapper inserts `--dangerously-skip-permissions` |
| Standing residuals | judging whether a deployment can accept the agy leg |
| Deny transaction | diagnosing `config-conflict`, lock waits, or a polluted settings file |
| Mode selection | choosing `--sandbox read-only` vs the permissive baseline |
| Tool to permission-action map | auditing or extending the deny set |
| Operational notes | interactive agy suddenly cannot write files |
| Self-healing coverage | asking which layer heals a leaked deny transaction, and when |

## Containment posture (start here)

Four facts; the sections below carry the mechanism behind each.

- **Write/exec containment is UNCONFIRMED at the dispatch floor.** The
  differential probe that found `read-only` blocking `write_file` and `command`
  headless ran on agy 1.1.7 — below `_STREAM_JSON_FLOOR` (1.1.8), the version
  this wrapper requires for any dispatch — so every dispatched build is one the
  finding was never re-probed on.
- **`execute_url`, `mcp` and `unsandboxed` are INTENT**: same deny mechanism,
  not individually probed (§ Standing residuals).
- **Reads and network are open BY DESIGN on every build** (§ Standing residuals).
- **agy self-reported a denied write as done**, so deterministic arrival checks
  stay mandatory whatever the containment status.

Provenance: differential probes on agy 1.1.7 (2026-07-25); the 1.1.3-era
soft-deny window; the 1.1.8 stream-json dispatch floor (2026-07-31).

## Headless soft-deny adaptation

agy 1.1.3 flipped headless (`-p`) permission policy: a tool needing a
confirmation is soft-denied unconditionally, and the `permissions.allow` list is
not consulted in print mode. That was empirically exhausted — allow-rule forms,
settings modes, env vars, and a `PreToolUse decision:allow` hook all fail; only
`--dangerously-skip-permissions` bypasses it. Without adaptation, every agy
review/research dispatch on 1.1.3 and later returns an empty or narration answer
and the leg is dead.

The wrapper therefore **version-gates auto-approve**: when `agy --version` is at
or above `_HEADLESS_SOFTDENY_FLOOR` (1.1.3) and `--version` exits rc=0 (a nonzero
exit fails safe to no-flag), it inserts `--dangerously-skip-permissions` so a
read-only-INTENT dispatch can run its own read tools. Because the wrapper's own
dispatch floor (`_STREAM_JSON_FLOOR`, 1.1.8) sits ABOVE the soft-deny floor, the
gate fires unconditionally (opt-out aside) on every build the wrapper dispatches
— there is no reachable dispatched version below 1.1.3 to compare against. No
version is pinned, so updates keep flowing.

**Floor, not a range — a known over-application.** Once agy eventually RESTORES
the headless allow-list in some later release, this floor still fires (voiding
isolation) until a human narrows it to a bounded range. `agy-daily-check.sh`
tracks the version bump but not the allow-list-restored behavior, so nothing
auto-detects the narrow trigger; that is a standing residual. The only
behavior-adaptive part is the secondary in-loop retry
(`_is_headless_softdeny`), which fires on the zero-output edge.

Opt-out: `AGY_NO_HEADLESS_AUTOAPPROVE=1` for strict deployments — agy then stays
unusable headless, but nothing is auto-approved. The wrapper is the ONLY caller
of the danger flag; user argv can never supply it (argparse defines no such
option).

**What the flag costs.** `--dangerously-skip-permissions` VOIDS the wrapper's
deny transaction AND agy's own `--sandbox` OS-ring (agy issue #36): it
auto-approves every tool — `write_file`, `command` (arbitrary shell), and
network. Deny-beats-Allow does not hold while the flag is set (verified: a write
BREACH file was created under deny + skip-perms), so a `--sandbox read-only`
dispatch gets no enforced containment FROM THE WRAPPER'S deny transaction — it is
read-only by INTENT. agy's OWN engine appeared to re-enforce `write_file` and
`command` separately on the probed 1.1.7 build; see § Containment posture for why
that is unconfirmed at the current floor.

## Standing residuals

What the disposable `--cwd` does NOT contain (owner-accepted for the review use
case) — two distinct causes, only one of which a vendor re-fix retired:

1. **Skip-perms window.** Under the flag agy could also run a `command` that
   reads sensitive files outside `--cwd` and write anywhere. The 1.1.7 probe
   found this CLOSED (`write_file` + `command` both denied) — unconfirmed at the
   1.1.8+ floor this wrapper dispatches.
2. **By design, on every build including enforcing ones.** The deny set covers
   write/exec/mcp: `read_file` and `read_url`/`search_web` are deliberately never
   denied, because the search leg needs them (deny-set inspection). So the leg can
   read ANY file the user can read, including outside `--cwd` (`~/.ssh`, tokens),
   and ship it out over the network. Probe-CONFIRMED present on 1.1.7 for
   `read_file` + `read_url` (a `/tmp` canary read plus a live URL fetch under
   `--sandbox read-only --cwd <dir>`); `search_web` rides the same never-denied
   action but was not itself probed.

Because this leg ingests UNTRUSTED review content (a prompt-injection surface), a
strict deployment that cannot accept residual (2) runs the dispatch inside an
EXTERNAL fs-scoped, network-denied OS sandbox. `AGY_NO_HEADLESS_AUTOAPPROVE=1`
addresses only residual (1).

Still owed on current builds: an `execute_url(...)`, an `mcp(...)`, and an
`unsandboxed(*)` attempt to confirm those three denies (the probe's
`run_command` cannot show which of `command`/`unsandboxed` agy requested).

## Deny transaction

`--sandbox read-only` brackets the agy call in a global-settings deny
transaction (`_agy_settings.agy_settings_guard`): the wrapper merges
`permissions.deny` into `~/.gemini/antigravity-cli/settings.json`, runs agy, then
restores byte-exactly (flock-serialized state transitions, `.agybak` crash
sentinel).

Identical **read-only** transactions SHARE the active deny lease through a holder
registry (per-holder flock liveness files), so concurrent read-only agy dispatches
are safe; the permissive (no `--sandbox`) baseline stays exclusive. Lease and lock
waits are bounded by `AGY_SETTINGS_LOCK_TIMEOUT` (env, seconds, default 30). A
settings transaction failure surfaces as `config-conflict` (exit 65). Engine
detail: the plugin `README.md` § Deny-transaction isolation.

agy `--sandbox` alone is a shell/network OS-ring only — it does not block
`write_file`. The deny transaction is what enforces fs isolation.

`toolPermission` presets are NOT exposed: they auto-proceed in headless (no TTY
to prompt) and would imply a guarantee that does not exist.

## Mode selection

- **`read-only`** — `deny:[write_file(*), command(*), unsandboxed(*),
  execute_url(*), mcp(*)]`; `read_url`/`search_web` stay allowed, so the search
  leg keeps working. `unsandboxed(*)` is the second `run_command` action (see the
  tool map). Deny is a **per-verb denylist** over the KNOWN agy tool surface, so a
  future mutation verb that is not enumerated (e.g. `edit_file` / `apply_patch`)
  would not be blocked: this is strong fs-write isolation for the known surface,
  not OS-level process isolation.
- **omitted** — no deny transaction; the owner's permissive global baseline stays
  intact (the call still acquires the lock and heals a stale `.agybak` first). A
  write-needing dispatch therefore runs with NO deny rules on any dispatchable agy
  build, and with `AGY_NO_HEADLESS_AUTOAPPROVE=1` set it also lacks the
  dangerous-path, `unsandboxed(*)`, `execute_url(*)` and `mcp(*)` denies the
  removed workspace-write mode used to add (web reach is then no longer bounded to
  `read_url`/`search_web`).
- On a HARDENED install (`TRIAD_WRAPPER_HARDENED=1`, the consumer default)
  omission auto-upgrades to `read-only`, so no write-INTENT agy mode remains
  there.

`workspace-write` was REMOVED (owner directive) — it was never used in 616
audited agy wrapper calls, so `--sandbox` now takes only `read-only`, and the
write-mode deny set plus the app-level `--cwd` requirement went with it. The
exclusive lock path is retained: it still brackets the permissive baseline.
Upstream lock issues google-antigravity/antigravity-cli #573/#627 remain open.

Reasoning tier = `--model` passthrough (no-pin default when omitted) — pass a
CATALOG selector from `agy models` (e.g. `gemini-3.1-pro-high`); the old display
label form ("Gemini 3.1 Pro (High)") is no longer listed by current agy builds.
Owl subagents (a `--task` equivalent) are not currently used by the wrapper.

## Tool to permission-action map

Re-confirm against your installed agy with
`agy -p "list your built-in tools and their permission actions"`.

| agy tool | permission action | notes |
|---|---|---|
| `view_file` / `list_dir` / `grep_search` | `read_file` | native reads (NOT shell) — auto-allowed in workspace |
| `write_to_file` / `replace_file_content` / `multi_replace_file_content` | `write_file` | governed per-call by the deny transaction |
| `run_command` | `command` OR `unsandboxed` | both denied in read-only (`unsandboxed(*)` = OS-ring escape) |
| `execute_url` (code-exec-from-URL) | `execute_url` | denied in read-only |
| `mcp` (MCP server reach) | `mcp` | denied in read-only |
| `read_url_content` / `search_web` | `read_url` | **always allowed** (never denied) — agy's search/research advantage; the only web access left even under read-only |
| `invoke_subagent` / `ask_question` / `schedule` | (no resource permission) | not gated by `permissions.deny` |

The write path is exactly write_to_file / replace_file_content /
multi_replace_file_content → `write_file`, so the per-verb denylist is complete
for the known surface. Denies for `execute_url` / `mcp` are kept even when they do
not appear in the self-reported inventory: denying an absent action is a no-op
today and protective if it returns.

Non-resource tools (`generate_image`, `send_message`, `manage_task`,
`manage_subagents`, `list_permissions`, `ask_permission`) report no permission
action. `generate_image`'s artifact write path is UNVERIFIED against the
`write_file` gate (self-report only), covered instead by the surviving practice:
run write-needing dispatches in a disposable `--cwd` and have the leader verify
results before use. That practice is UNENFORCED — nothing in the wrapper requires
`--cwd`, and agy resolves RELATIVE paths against its own scratch project rather
than `--cwd`, so hand it absolute paths.

## Self-healing coverage

- **`.agybak` crash-recovery.** The deny transaction restores through a `.agybak`
  crash sentinel healed on the NEXT agy call — every call, permissive ones
  included, acquires the lock and heals first. The crash window is narrowed by
  SIGTERM/SIGHUP unwind handlers (settings restore + vendor child kill on the way
  out) plus a process-group kill on abnormal unwind inside `_common._run_once`.
  Only SIGKILL-class death still leaves the sentinel, by design.
- **Leaked-transaction probe.** `agy-daily-check.sh` fires ACTIONABLE on a stale
  `.agybak` or shared-lease sentinel older than 2h — the SIGKILL-class residual,
  which would otherwise be healed only on the NEXT wrapper call while interactive
  agy mis-runs silently.

## Operational notes

- **Stale-sentinel recovery.** The transaction restores through a `.agybak` crash
  sentinel healed on the NEXT agy call — every call, including a permissive one,
  acquires the lock and heals first. If an agy call crashes and no subsequent agy
  call runs, the owner's global `settings.json` stays in the deny state. So: if
  interactive `agy` suddenly cannot write files, remove a stale
  `~/.gemini/antigravity-cli/.agybak`. Writes are atomic (temp + `os.replace`), so
  the file is never left half-written.
- The SIGKILL-class residual window is capped by `agy-daily-check.sh`, which
  fires ACTIONABLE on a leaked deny transaction (a stale `.agybak` or shared-lease
  sentinel older than 2h).
