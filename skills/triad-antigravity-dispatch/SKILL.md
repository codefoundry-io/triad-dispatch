---
name: triad-antigravity-dispatch
description: Use when the leader (Triad orchestrator) needs to dispatch a single-shot Antigravity CLI (`agy`) call via the wrapper framework. Triggering signals — leader is about to run `python3 antigravity_wrapper.py` raw; user said "agy 한 번 불러줘" / "antigravity로 X 처리" / "agy CLI 단발 실행" / "안티그래비티 호출"; a higher-level orchestration SKILL needs the agy leg of a fan-out (gemini CLI successor for individual users; the enterprise gemini tier stays active, so both legs ship); classification-aware routing with self-improving repair-agent fallback is needed instead of raw subprocess. Symptoms of skipping this SKILL — unknown classification failures don't reach the repair sub-agent, run-log files accumulate uncleaned, the framework's self-improving classifier never grows. Do NOT use for Codex (use `triad-codex-dispatch`), Gemini (use `triad-gemini-dispatch`).
version: 0.5.0
---

# triad-antigravity-dispatch

Single-shot Antigravity CLI (`agy`) dispatch with classification-based routing
and a self-improving repair loop. The leader's standard "call agy once" path.
agy is the gemini CLI successor for individual users (the Gemini CLI *individual*
tier is deprecated — Google migrated it to Antigravity) — Android /
Google-ecosystem domain strength. **Deployment caveat:** the **enterprise** Gemini
CLI tier stays active (the individual-tier deprecation does not affect it), so the
gemini leg is NOT dropped — environments on enterprise Gemini keep using it while
individual users move to agy. Both ship in the distributable plugin.

## Use when

- Leader has a discrete prompt and needs agy's answer (or a structured failure signal). agy is preferred for Android domain (XML / Compose / Material), Google-ecosystem queries — the gemini successor.
- A higher-level SKILL (e.g. `triad-cross-family-review`) wants the agy leg of a fan-out.
- User said "agy 한 번 불러서 X" / "antigravity CLI 로 단발 실행" / "안티그래비티 호출".

Going through this SKILL (instead of raw `python3 antigravity_wrapper.py`) is
what makes the `unknown`-classification path correctly route to the repair
sub-agent.

## Routing — agy is the search/research specialist (external-doc research leg)

agy's `read_url` action (`read_url_content` / `search_web`) is **always allowed**
— never touched by the per-call deny transaction (§ Isolation tool→action map).
Web-grounded lookup is agy's structural advantage.

**agy is the toolkit's external-documentation research leg.** When a dispatch or
a review needs to be grounded in **vendor / API / CLI documentation** — the OpenAI
developer docs, the Google / Gemini docs, a CLI's reference pages, a library's
README, a recent changelog or issue — send that doc-reading to agy via its
`read_url` / `search_web`. Two reasons this is a routing rule, not a nice-to-have:

- **Grounding.** A 3-way dispatch or a cross-family review is only as good as the
  facts under it; agy pulls the current vendor/API/CLI source instead of the
  leader answering from stale memory.
- **Context hygiene.** Fetching a long doc page into the leader's own context
  pollutes it (and evicts task-relevant context). Doing the doc-read in the agy
  worker keeps the raw page OUT of the leader's context — the leader gets back the
  grounded answer, not the whole document.

- The leader **MUST** include `triad-antigravity-dispatch` in any search /
  research dispatch — alongside the other legs, or as the **primary** leg when
  the task is web-grounded fact-finding or vendor-doc grounding.
- The leader **SHOULD** prefer agy for web-grounded lookups (vendor/API/CLI
  documentation search, "what does the latest X say", recent-issue triage) over a
  non-search CLI leg, and route doc-heavy reads to agy rather than reading the
  page into its own context.

This is a routing / role preference, not a new capability or an isolation change:
a search dispatch still runs under whatever `--sandbox` mode the leader picks (or
the permissive baseline), and `read_url` stays allowed in every mode. No model
name is pinned — agy uses the vendor default.

## Skip when

- Final cross-family review → `triad-cross-family-review`.

## Isolation — per-call deny transaction (codex parity)

`--sandbox read-only|workspace-write` brackets the agy call in a global-settings
deny transaction (`_agy_settings.agy_settings_guard`): the wrapper merges
`permissions.deny` into `~/.gemini/antigravity-cli/settings.json`, runs agy, then
byte-exactly restores (flock-serialized state transitions, `.agybak` crash
sentinel). Identical **read-only** transactions SHARE the active deny lease via
a holder registry (per-holder flock liveness files), so concurrent read-only agy
dispatches are safe; `workspace-write` stays exclusive. Lease/lock waits are
bounded by `AGY_SETTINGS_LOCK_TIMEOUT` (env, seconds, default 30); a settings
transaction failure surfaces as `config-conflict` (exit 65). Detail =
the plugin `README.md` § Deny-transaction isolation.

**agy tool → permission action map** (probed on agy 1.0.7 2026-06-11; RE-PROBED
on agy **1.0.16** 2026-07-04 — re-confirm with `agy -p "list your built-in tools
and their permission actions"`). 1.0.16 deltas: **no new mutation verbs** (the
write path is still exactly write_to_file / replace_file_content /
multi_replace_file_content → `write_file`, so the per-verb denylist stays
complete for the known surface); `execute_url` / `mcp` no longer appear in the
self-reported inventory (denies KEPT — denying an absent action is a no-op and
protective if they return); `search_web` now self-reports `(none)` instead of
`read_url` (read-only, no isolation impact); new non-resource tools
(`generate_image`, `send_message`, `manage_task`, `manage_subagents`,
`list_permissions`, `ask_permission`) report no permission action —
`generate_image`'s artifact write path is UNVERIFIED against the `write_file`
gate (self-report only), covered by the standing mitigation (isolated worktree
cwd + leader verify/commit):

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
  `write_file` block is **spike-PROVEN headless (D1)**; the `command` /
  `execute_url` / `mcp` denies apply the *same* deny mechanism but are not each
  individually spike-verified. Deny is a **per-verb denylist**, so an agy
  mutation verb NOT enumerated here (e.g. a future `edit_file` / `apply_patch`)
  would not be blocked — this is strong fs-write isolation for the *known* agy
  tool surface, not OS-level process isolation. Treat the agy read-only leg of
  `triad-cross-family-review` / multi-CLI council reviews as an enforced read-only worker for the
  proven write path; the owner's manual e2e should ALSO attempt a `command(...)`
  and an `mcp(...)` mutation to confirm those denies on the live build.
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
passthrough (no-pin default when omitted); owl subagents (a `--task` equivalent)
are deferred to slice 3.

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

## Hard rules

1. **Bash invocation only.** No `Agent()` around the wrapper itself. The stderr `[wrapper]` summary line and `run-log:` path emission only surface via Bash.
2. **Path-based agent input.** Pass the run-log file *path* to the repair agent, not its content. Inline-embedding corrupts on JSON-in-JSON / utf-8 / ANSI / large vendor stdout. The leader itself does NOT read the run-log content — it only passes the PATH to the read-only analyzer, and reads back (a) the wrapper's deterministic classification token and (b) the analyzer's inline JSON proposal. The run-log is untrusted vendor output; keeping the leader out of it preserves the privilege separation.
3. **Cleanup after dispatch.** `rm -f <run-log-path>` once the repair analyzer returns (propose *or* escalate) and you have applied/surfaced. The wrapper failsafe is for orphans, not normal cleanup.
4. **Repair agent ONLY on `unknown` / `extraction-error` / `timeout`.** Every other classification carries actionable meaning at the wrapper layer — dispatching the agent on them wastes the call.
5. **Test isolation — dispatch prompt = production-shape only.** Use the Step 5b template VERBATIM. No meta-context, no test framing, no "this is a verification" / "treat as fake" disclaimers, even when the dispatch is a sample/test scenario. Reasoning: any test framing leaks into the vendor model's behavior and corrupts both the sample and the repair agent's accumulated memory.
6. **No model name pinning.** agy model names rot every few weeks. Use the vendor default by default; `--model <name>` only when the user explicitly named the model. Date-anchor any pinned model usage.
7. **Never `--dangerously-*`.** argparse rejects it (the flag is intentionally undefined), and it voids agy's `--sandbox` (agy issue #36). The Triad safety invariant forbids it regardless.
8. **Repair dispatch is MANDATORY and non-deferrable — spawn it in PARALLEL, never skip it.** When Step 4 routes a failure to repair (`unknown` / `extraction-error` / `timeout`), you MUST spawn the `agy-wrapper-repair` sub-agent. Surfacing the failure to the user does NOT discharge this — *surfacing* and *repairing* are SEPARATE obligations; doing one is not doing the other. "I have other / more important work", "the call already failed", "this looks like a one-off" are NEVER valid reasons to skip or defer the spawn. Remove the temptation to defer by dispatching with the `Agent` tool's **`run_in_background: true`** so it runs CONCURRENTLY with your foreground work; parse its inline proposal (Step 5c) + apply it + clean up (Step 5d) when it completes. **Mechanism:** the repair agent is a read-only ANALYZER that returns an inline JSON patch proposal; the LEADER applies it via the deterministic `apply_patch.py` and verifies routing with a `--repair-mode` re-run. The analyzer has zero write authority; the write path has zero LLM. Why non-skippable: the repair analyzer's payoff is FUTURE routing — framework completeness, NOT the immediate call — so it is a fire-in-parallel task, and skipping it is a silent regression that lets the same vendor error keep failing un-routed on every later call (origin: 2026-06-12 — a freshly-installed company plugin leader hit an HTTP 403 → `unknown`, reported only "failed", and skipped the spawn citing "other work"). Complements rule 4: rule 4 = dispatch ONLY for these classes; rule 8 = you MUST, in parallel, for these classes.

## Flow

### Step 1 — Build the wrapper invocation

Single-quoted heredoc for the prompt body so Korean / emoji / `$variables` /
backticks / quotes survive intact:

```bash
antigravity_wrapper.py \
  --prompt "$(cat <<'PROMPT'
<leader-prompt-verbatim>
PROMPT
)" \
  [--cwd /absolute/path] \
  [--sandbox read-only|workspace-write] \
  [--model <pinned-model-name>] \
  [--pydantic module:Class] \
  [--timeout <seconds>] \
  [--debug]
```

- `--sandbox read-only|workspace-write` selects the per-call deny transaction
  (§ Isolation). Omit for the permissive baseline. `workspace-write` requires
  `--cwd` (isolated worktree) — argparse/`EXIT_ARG_ERROR` if missing.
- `--pydantic module:Class` forces JSON output. agy has **no native JSON
  schema**, so the wrapper instructs JSON via a prompt addendum: the completion
  sentinel is a REQUIRED trailing line emitted on its own NEW line AFTER the JSON
  object (the marker is NOT part of the JSON). The wrapper validates the
  pre-marker text with `_common.validate_response`, does ONE schema-repair re-run
  on failure, then exits `EXIT_SCHEMA_FAIL=66`. Same prompt-instructed approach as
  the gemini wrapper. **e2e gate CLOSED (2026-07-05)**: real-agy
  "marker-after-JSON" adherence live-verified — `--pydantic _test_schemas:CityResponse`
  returned schema-valid JSON with correct sentinel placement (rc=0, 8s, agy 1.0.16).
- `--timeout` default is `600` seconds. The wrapper derives agy's `--print-timeout` from it (`max(timeout - 10, 5)s`); the pty kill is the backstop.
- `--cwd` sets agy's working directory.
- `--debug` accumulates a markdown debug table.

**`--pydantic` is prompt-instructed, not native** (agy has no `--output-schema`).
Still **no `--dangerously-*`** (Hard rule 7).

Transport note (wrapper-internal — the leader just calls the wrapper): agy is
driven through a **pty** (it drops stdout on a non-TTY and has no
`--output-format json`) plus a per-call **completion sentinel** the wrapper
appends to the prompt. The leader does not manage the pty or the sentinel.

### Step 2 — Run via Bash; capture rc, stdout, stderr

Wrapper stderr contains:
- Timestamped wrapper log lines
- 1-line summary: `[wrapper] antigravity <classification> exit=<int> vendor=<int> elapsed=<s>`
- On failure: `run-log: <absolute-path>`

Wrapper stdout = agy's final answer (sentinel-delimited, scrubbed of control bytes).

### Step 3 — Read the classification

Grep the summary line; extract classification. **Use the LAST
`[wrapper] antigravity <classification> exit=<int> vendor=<int> elapsed=<s>`
line** from stderr (mirror the codex/gemini dispatch convention — take the last
emission only):

```bash
SUMMARY=$(grep '^\[.*\] \[wrapper\] antigravity ' <stderr-text> | tail -1)
CLS=$(printf '%s' "$SUMMARY" | sed -E 's/.*\[wrapper\] antigravity ([a-z-]+) .*/\1/')
```

Token set:
`ok | server-capacity | cli-subscription-cap | token-limit | oauth-env | timeout | extraction-error | config-conflict | unknown`

Or branch on wrapper exit code: `0` / `1` / `2` (timeout) / `3` (arg) /
`4` (binary missing) / `64` (server-cap exhausted) / `65` (terminal).

### Step 4 — Branch on classification

| classification (rc) | Leader action |
|---|---|
| `ok` (0) | Return wrapper stdout (agy's final answer text). |
| terminal (65) — cli-subscription-cap / token-limit / oauth-env / config-conflict | Surface to user with cause (re-login / quota daily reset / prompt size too large / settings deny-transaction failed: lock-lease timeout or corrupt `~/.gemini/antigravity-cli/settings.json`). **NOT** repair-agent territory (already matched — only `unknown` / `extraction-error` / `timeout` route to repair). |
| `server-capacity` exhausted (64) | Wait + retry, or surface. Wrapper already retried per backoff (cap 2 pty re-runs). |
| `unknown` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 8). Spawn it even when you are busy or also surfacing the failure — never skip.** |
| `extraction-error` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 8).** agy ran but the extractor found no answer (clean output but empty, missing sentinel, vendor refusal text). Repair agent inspects whether the cause is a vendor refusal pattern worth a classifier patch, or a true extraction bug → ESCALATE. |
| `timeout` (2) | **Step 5 — repair agent dispatch.** Likely ESCALATE since a hang (pty killed at the print-timeout backstop) is rarely a classifier gap, but route through the same path for uniformity. Wrapper already fail-fasts (no retry on timeout). |
| arg (3) / binary missing (4) | Surface to user with cause (empty prompt / `agy` not on PATH). |

**NOT produced by agy** (do not branch on these — they belong to other
CLIs): `schema-rejected` / `fanout-spawn-error` /
`fanout-partial` / `task-blocked`. agy has **no native schema** (so no
`schema-rejected`) and **no `--task` layer** (so no fan-out / code-task
signals). agy's `config-conflict` (unlike codex's config.toml case) means the
`_agy_settings` deny transaction failed — see the terminal (65) row above.

### Step 5 — Repair branch: read-only analyzer proposes, leader applies (`unknown` / `extraction-error` / `timeout` only)

The repair agent is a READ-ONLY analyzer: it reads the run-log (untrusted vendor
output) and returns a structured patch PROPOSAL as inline JSON. The LEADER applies
that proposal via the deterministic, zero-LLM `apply_patch.py`, then re-runs the
wrapper in `--repair-mode` to verify routing. Safe-by-construction: the
untrusted-input handler has no write authority; the write path has no LLM. This
holds for `extraction-error` / `timeout` too — the analyzer just proposes or
escalates for those.

#### 5a. Extract the run-log path

```bash
RUN_LOG_PATH=$(grep -oE 'run-log: [^[:space:]]+' <stderr-text> \
                | tail -1 | awk '{print $2}')
[ -f "$RUN_LOG_PATH" ] || { echo "run-log path missing"; exit 1; }
```

The leader passes this PATH to the analyzer — it does NOT read the run-log content
itself (Hard rule 2). There is no output file: the analyzer replies inline.

#### 5b. Dispatch the repair analyzer

Use the `Agent` tool with `subagent_type` set exactly to `agy-wrapper-repair`, **`run_in_background: true`** (Hard rule 8 — parallel, non-skippable; the inline JSON proposal arrives on completion, at which point you run Step 5c/5d). **Use the prompt body below VERBATIM** — substitute only the `<RUN_LOG_PATH>` placeholder. Hard rule 5: no meta-context, no test framing, no "note that..." lines.

The dispatch prompt is JSON-shaped: `run_log_path` (input) + `output_schema` (output contract). The analyzer reads the run-log via `Read`, decides the classification, and returns the proposal as a single inline JSON object in its chat reply — no file write.

```
You are a read-only repair analyzer. Read the run-log with the Read tool, decide the classification, and return your patch proposal as a SINGLE inline JSON object — the JSON is your ENTIRE chat reply (no markdown fences, no prose, no file write).

Input:
{
  "run_log_path": "<RUN_LOG_PATH>",
  "output_schema": {
    "outcome":  "<string>  // 'propose' if an existing classification should catch this error, 'escalate' if you cannot classify (novel error, true bug, out of scope)",
    "reason":   "<string>  // one-line semantic summary for the leader/owner",
    "proposal": "<object|null>  // null when escalate; when propose, the exact apply_patch.py input: {classification, reason, and EITHER vendor_exit_code:int XOR (pattern_list:NAME + substring:str)}"
  },
  "task": "Read the run-log, extract the literal error, Read/Grep bin/_common.py to see which existing class should catch it, then return the inline JSON proposal matching output_schema. Network is OFF — decide from the run-log + local framework, or escalate. You do NOT apply or verify — the leader does. Single pass."
}

Example response (return this inline JSON as your entire chat reply):
{"outcome": "propose", "reason": "agy emitted a new re-login banner the seed list missed — improves oauth-env routing only", "proposal": {"classification": "oauth-env", "reason": "re-login banner on the no-answer path; auth stays user-managed", "pattern_list": "AGY_AUTH_BANNER_PATTERNS", "substring": "please re-authenticate to continue"}}

Now do the analysis and return the inline JSON.
```

#### 5c. Parse the analyzer's inline JSON proposal

The Agent tool returns the analyzer's final chat text, which is the inline JSON object. Parse it with `jq`:

```bash
AGENT_JSON="$AGENT_RESPONSE"   # the agent's inline JSON chat reply
OUTCOME=$(jq -r '.outcome' <<<"$AGENT_JSON")
REASON=$(jq -r '.reason' <<<"$AGENT_JSON")
PROPOSAL=$(jq -c '.proposal' <<<"$AGENT_JSON")
```

Schema top-level keys: `outcome` (`propose` | `escalate`), `reason`, `proposal` (null when escalate).

#### 5d. Branch: escalate → surface; propose → leader applies + verifies

```bash
case "$OUTCOME" in
  escalate)
    echo "repair escalated: $REASON"
    ;;
  propose)
    if printf '%s' "$PROPOSAL" \
         | apply_patch.py --cli antigravity; then
      # applier exit 0 → patch landed; re-run in --repair-mode to verify routing.
      antigravity_wrapper.py \
        --repair-mode <reconstructed-original-args>   # report the routing result
    else
      echo "proposal rejected by applier: $REASON"   # applier exit 3 → treat as escalate
    fi
    ;;
  *)
    # Unparseable analyzer output: the agent returned conversational text (or
    # empty), so jq failed and OUTCOME is not propose/escalate. Do NOT silently
    # proceed — SURFACE it. No patch is applied; the original failure
    # classification stands.
    echo "repair skipped — unparseable analyzer output (OUTCOME='$OUTCOME'); the original failure classification stands"
    ;;
esac

rm -f "$RUN_LOG_PATH"
```

The applier re-validates the proposal independently (enum + pattern-name + literal bounds), so it is the security backstop even if the analyzer misbehaves: on exit 3 the extension file is left untouched and the leader surfaces it as an escalate. Cleanup is one `rm -f "$RUN_LOG_PATH"` (no output file exists). The wrapper's `_prune_run_logs()` (`glob("*.json")`) is the failsafe for orphans.

Branch summary:

| OUTCOME | Next action |
|---|---|
| propose → applier exit 0 | Re-run wrapper `--repair-mode` to verify routing; report the routing result. Framework now catches future identical errors. |
| propose → applier exit 3 | Proposal invalid (analyzer error) — surface REASON, treat as escalate. |
| escalate | Surface REASON. Manual diagnosis needed; no apply. |

## Outputs (what this skill returns)

- `ok`: wrapper stdout (agy's final answer text).
- terminal: `{ class, reason, action_required }`.
- server-cap-exhausted: "transient overload, leader-policy retry or surface".
- repair-cycle: analyzer proposes → leader applies via `apply_patch.py` → `--repair-mode` re-run verifies routing; OR escalate (surface REASON, no apply).

## Self-healing

Three layers keep the agy leg healthy without manual babysitting — two reactive
(per-call), one proactive (daily):

1. **`agy-wrapper-repair` analyzer (reactive, per-call).** On an `unknown` /
   `extraction-error` / `timeout` classification, the dispatch flow (Step 5)
   routes to this read-only analyzer, which returns an inline JSON patch proposal
   (one vendor-exit-map entry or one L2 substring); the LEADER applies it via the
   deterministic `apply_patch.py` so the next call auto-routes. Self-improving:
   dispatch frequency falls as the classifier matures.
2. **`.agybak` crash-recovery (reactive, per-call integrity).** Every agy call
   acquires the settings flock for its state transition; every first/exclusive
   entrant heals a stale `.agybak` left by a crashed settings transaction
   *before* settings are mutated (read-only calls joining an already-active
   shared lease inherit the healed state), so no agy call ever executes against
   deny-polluted global settings (§ Isolation operational notes). Writes are
   atomic (temp + `os.replace`).
3. **`agy-daily-check.sh` (proactive, daily drift).** A scheduled
   `agy update` + drift detector — model-list / changelog / plugin-list
   snapshots (+ optional JSON-adherence deep probe) diffed against a stored
   baseline, plus a superpowers-for-agy availability probe. **Split exit
   semantics** so benign vendor churn does not train operators to ignore the
   alarm: `0` = no change / `1` = ACTIONABLE drift (model list changed or deep
   JSON-adherence broke) / `2` = INFORMATIONAL change (changelog version /
   plugin list / superpowers-available). A failed `agy` subcommand preserves the
   previous snapshot. Surfaced as a dated report for owner review. Scheduling +
   flags = the plugin `README.md` § agy daily-check.

## Path scope

- **Passes the PATH of** `_logs/antigravity/runs/<id>.json` (run-log) to the analyzer. The leader does NOT read the run-log content (Hard rule 2) — the analyzer does, via `Read`.
- **Removes** the run-log post-dispatch (propose + escalate).
- **Invokes** `bin/antigravity_wrapper.py` (dispatch + `--repair-mode` verify) and `bin/apply_patch.py` (deterministic proposal applier) via Bash.
- **Dispatches** sub-agent `agy-wrapper-repair` (read-only analyzer).

The leader (not the analyzer) is the only writer to the classifier extension — via the deterministic `apply_patch.py`. Does NOT edit `bin/_common.py` source or read `_logs/antigravity/audit.jsonl` (maintenance SKILL's territory).

## See also

- the plugin `README.md` — wrapper contract + run-log schema.
- `agents/agy-wrapper-repair.md` — repair sub-agent body (per-attempt workflow + outcome judgment).
- `triad-codex-dispatch` — parallel SKILL for Codex.
- `triad-gemini-dispatch` — parallel SKILL for Gemini (agy's predecessor; the individual Gemini tier is deprecated but the enterprise tier stays active — both legs ship in the plugin).
- `triad-cross-family-review` — final pre-merge cross-family review (the agy leg here is best-effort non-write, see § Isolation for the enforced deny surface).
