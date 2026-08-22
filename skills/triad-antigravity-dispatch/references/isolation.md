# agy isolation reference — containment posture, deny model, operational notes

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` § Read-only path v2,
§ Headless soft-deny adaptation and § Isolation. Read this before changing a sandbox mode, auditing
the deny surface, judging what an agy leg can reach, or diagnosing a
settings-transaction failure.

## Contents

| Section | Open it when |
|---|---|
| Containment posture (start here) | deciding what a `--sandbox read-only` agy call actually contains |
| Read-only path v2 | what the allowlist agents, `--add-dir` and the admission census do |
| Headless soft-deny adaptation | asking why the PERMISSIVE baseline inserts `--dangerously-skip-permissions` |
| Standing residuals | judging whether a deployment can accept the agy leg |
| Deny transaction (permissive baseline) | diagnosing `config-conflict`, lock waits, or a polluted settings file on the permissive baseline |
| Mode selection | choosing `--sandbox read-only` vs the permissive baseline |
| Tool to permission-action map | auditing or extending the deny set |
| Operational notes | interactive agy suddenly cannot write files |
| Self-healing coverage | asking which layer heals a leaked deny transaction, and when |

## Containment posture (start here)

Five facts; the sections below carry the mechanism behind each.

- **The read-only path v2 removes the write/shell/MCP/browser tools before the
  run** (setup-once allowlist agent, `--agent`) and carries NO danger flag: a
  fallback to agy's default agent cannot write or run a shell under the
  vendor's own headless policy (ladder round 2, K1 / K5) and is rejected by
  the admission census. No settings transaction is involved.
- **Write/exec denial under the danger flag is MEASURED on agy 1.1.17** for
  `command(*)` (arm A / F4) and `write_file(*)` (probe G) — Deny > dsp — which
  matters only for the PERMISSIVE baseline now.
- **`execute_url`, `mcp` and `unsandboxed` are INTENT** on the baseline: same
  deny mechanism, not individually probed (§ Standing residuals).
- **Reads and network are open BY DESIGN on every build** (§ Standing residuals).
- **agy self-reported a denied write as done**, so deterministic arrival checks
  stay mandatory whatever the containment status.

Provenance: the 2026-08-22 permission ladder on agy 1.1.17 (arms A-D, probes
E-G); differential probes on agy 1.1.7 (2026-07-25); the 1.1.3-era
soft-deny window; the 1.1.8 stream-json dispatch floor (2026-07-31).

## Read-only path v2 (`--sandbox read-only`, agy >= 1.1.18)

Spec: `docs/superpowers/specs/2026-08-22-agy-readonly-v2-spec.md`. Two
setup-once agent definitions under `~/.gemini/config/agents/` (written by
`antigravity_wrapper.py --setup-agents`; bodies embedded in the wrapper;
workspace `.agents/` is NOT loaded in print mode — ladder round 2 K1):

- `triad-readonly-review` — `view_file`, `grep_search`, `list_dir`,
  `find_by_name`, `finish`; no web tool (a review has no egress).
- `triad-readonly-research` (`--web`) — the same plus `read_url_content`,
  `search_web`.

The dispatch = `agy -p <prompt> --agent <name> --add-dir <cwd>
--output-format stream-json [--json-schema …]`. `--add-dir` makes repository
reads auto-allowed in print mode (K2) while writes stay denied without the
danger flag (K5); the research agent's web tools additionally need
`read_url(*)` allowed on the host. Precondition: the agent file is
byte-identical to the embedded body, else `config-conflict` naming
`--setup-agents`. Admission (`admit()` in the wrapper): every non-blank
stdout line is a JSON object; exactly one `result`; every tool name in any
attempt ∈ the allowlist (both `tool_name` and `tool_info.name`; a nameless
tool step counts as outside); a `status != SUCCESS` run is admitted only when
every errored step named an allowed read (logged
`admitted-with-errored-steps`), otherwise `vendor-error`. `init.agent` is a
diagnostic only (it echoes the requested name even on fallback — probe E,
re-measured on 1.1.18). Below 1.1.18: `config-conflict`, no legacy path.
Residuals: reads (and, for research, network) open by design; a fallback that
calls nothing forbidden is indistinguishable and accepted (side-effect-free
under the vendor's headless denial); two files outside the repo per host; a
vendor rename of an allowlisted tool blinds the agent (the read-audit shows
no reads → the CFR gate VOIDs the leg).

## Headless soft-deny adaptation (PERMISSIVE baseline only)

agy 1.1.3 flipped headless (`-p`) permission policy: a tool needing a
confirmation is soft-denied unconditionally, and the `permissions.allow` list is
not consulted in print mode. That was empirically exhausted — allow-rule forms,
settings modes, env vars, and a `PreToolUse decision:allow` hook all fail; only
`--dangerously-skip-permissions` bypasses it. Without adaptation, every agy
review/research dispatch on 1.1.3 and later returns an empty or narration answer
and the leg is dead.

The wrapper therefore **version-gates auto-approve on the permissive
baseline**: when `agy --version` is at or above `_HEADLESS_SOFTDENY_FLOOR`
(1.1.3) and `--version` exits rc=0 (a nonzero exit fails safe to no-flag), it
inserts `--dangerously-skip-permissions`. The read-only path v2 never carries
the flag (reads come from `--add-dir`, 1.1.18). Because the wrapper's own
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

**What the flag costs (version-scoped).** In the 1.1.3-era window
`--dangerously-skip-permissions` VOIDED the wrapper's deny transaction AND agy's
own `--sandbox` OS-ring (agy issue #36; a write BREACH file was created under
deny + skip-perms on that build). RE-MEASURED 2026-08-22 on 1.1.17:
`permissions.deny` wins over the flag — `command(*)` denied (ladder arm A / F4),
`write_file(*)` denied (probe G) — so a `--sandbox read-only` dispatch DOES get
enforced containment from the deny transaction on current builds;
`unsandboxed` / `execute_url` / `mcp` follow from the same precedence but are
asserted, not measured. The flag's remaining cost is exactly what the deny set
never names: reads and network (§ Standing residuals 2) and, on an agent-mode
fallback, the tools with no permission action (§ Tool to permission-action map).

## Standing residuals

What the disposable `--cwd` does NOT contain (owner-accepted for the review use
case) — two distinct causes, only one of which a vendor re-fix retired:

1. **Skip-perms window.** Under the flag agy could also run a `command` that
   reads sensitive files outside `--cwd` and write anywhere. The 1.1.7 probe
   found this CLOSED (`write_file` + `command` both denied) and the 2026-08-22
   ladder CONFIRMED it on 1.1.17 (arm A, probe G): Deny > dsp. Closed for the
   deny set on current builds; what the flag still auto-approves is only what
   the deny set never names (residual 2), plus — on an agent-mode fallback —
   the tools with no permission action (§ Tool to permission-action map).
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

## Deny transaction (PERMISSIVE baseline only since v2)

The read-only path v2 enters NO settings transaction. The permissive baseline
(`--sandbox` omitted, non-hardened) still brackets the call in the exclusive
settings guard (`_agy_settings.agy_settings_guard` with empty deny rules:
lock, `.agybak` heal, byte-exact restore). The deny-merging read-only
transaction below is kept in `_agy_settings.py` for codex-host, which still
drives it; this host's wrapper no longer selects it.

Identical **read-only** transactions (codex-host) SHARE the active deny lease
through a holder registry (per-holder flock liveness files); the permissive (no
`--sandbox`) baseline stays exclusive. Lease and lock
waits are bounded by `AGY_SETTINGS_LOCK_TIMEOUT` (env, seconds, default 30). A
settings transaction failure surfaces as `config-conflict` (exit 65). Engine
detail: the plugin `README.md` § Deny-transaction isolation.

agy `--sandbox` alone is a shell/network OS-ring only — it does not block
`write_file`. The deny transaction is what enforces fs isolation.

`toolPermission` presets are NOT exposed: they auto-proceed in headless (no TTY
to prompt) and would imply a guarantee that does not exist.

## Mode selection

- **`read-only`** — the v2 path (§ Read-only path v2): allowlist agent +
  `--add-dir`, no deny rules, no danger flag. The per-verb deny set
  (`write_file(*), command(*), unsandboxed(*), execute_url(*), mcp(*)`) lives on
  in `_agy_settings.build_deny_rules` for codex-host only.
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
| `read_url_content` / `search_web` | `read_url` | never denied by the wrapper; since v2 present ONLY in the research agent (`--web`) — the review agent has no web tool — agy's search/research advantage; the only web access left even under read-only |
| `invoke_subagent` / `ask_question` / `schedule` | (no resource permission) | not gated by `permissions.deny` |
| `open_browser_url` / `read_browser_page` / `execute_browser_javascript` / `browser_*` (~20 tools in the 1.1.17 `init.tools` inventory, probe F4) | (no MEASURED action) | never probed against any deny rule; absent from the `triad-readonly-review` allowlist, so under agent mode = detection-only via the census (gate r8) |
| `notebook_edit` / `notebook_execution` / `send_message` / `generate_image` | (no resource permission reported) | detection-only under the agent-mode census (disclosed residual) |

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
