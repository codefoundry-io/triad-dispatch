---
name: triad-antigravity-dispatch
description: Use when the leader (Triad orchestrator) needs to dispatch a single-shot Antigravity CLI (`agy`) call via the wrapper framework. Triggering signals — leader is about to run `python3 antigravity_wrapper.py` raw; user said "agy 한 번 불러줘" / "antigravity로 X 처리" / "agy CLI 단발 실행" / "안티그래비티 호출"; a higher-level orchestration SKILL needs the agy leg of a fan-out (gemini CLI successor; gemini public EOL 2026-06-18, but 사내 keeps gemini until ~2026-07-31 so both ship in the interim); classification-aware routing with self-improving repair-agent fallback is needed instead of raw subprocess. Symptoms of skipping this SKILL — unknown classification failures don't reach the repair sub-agent, run-log files accumulate uncleaned, the framework's self-improving classifier never grows. Do NOT use for Codex (use `triad-codex-dispatch`), Gemini (use `triad-gemini-dispatch`), multi-turn dialogue / pair-coding (use `triad-pair-brainstorm` or `triad-pair-plan`), or 3-CLI fact-check fan-out (use `triad-3way-question`).
version: 0.2.0
---

# triad-antigravity-dispatch

Single-shot Antigravity CLI (`agy`) dispatch with classification-based routing
and a self-improving repair loop. The leader's standard "call agy once" path.
agy is the gemini CLI successor (gemini CLI public EOL 2026-06-18) — Android /
Google-ecosystem domain strength. **사내 deployment caveat:** 사내 keeps using
gemini through ~2026-07-31 (and cannot run agy), so the gemini leg is NOT dropped
on the public EOL date — agy succeeds gemini only after the 사내 sunset. Both
ship in the distributable plugin in the interim.

## Use when

- Leader has a discrete prompt and needs agy's answer (or a structured failure signal). agy is preferred for Android domain (XML / Compose / Material), Google-ecosystem queries — the gemini successor.
- A higher-level SKILL (e.g. `triad-cross-family-review`) wants the agy leg of a fan-out.
- User said "agy 한 번 불러서 X" / "antigravity CLI 로 단발 실행" / "안티그래비티 호출".

Going through this SKILL (instead of raw `python3 antigravity_wrapper.py`) is
what makes the `unknown`-classification path correctly route to the repair
sub-agent.

## Routing — agy is the search/research specialist

agy's `read_url` action (`read_url_content` / `search_web`) is **always allowed**
— never touched by the per-call deny transaction (§ Isolation tool→action map).
Web-grounded lookup is agy's structural advantage.

- The leader **MUST** include `triad-antigravity-dispatch` in any search /
  research dispatch — alongside the other legs, or as the **primary** leg when
  the task is web-grounded fact-finding.
- The leader **SHOULD** prefer agy for web-grounded lookups (documentation
  search, "what does the latest X say", recent-issue triage) over a non-search
  CLI leg.

This is a routing preference, not an isolation change: a search dispatch still
runs under whatever `--sandbox` mode the leader picks (or the permissive
baseline), and `read_url` stays allowed in every mode.

## Skip when

- Multi-turn dialogue / pair-coding → `triad-pair-brainstorm` / `triad-pair-plan`.
- 3-CLI fact-check fan-out → `triad-3way-question`; final cross-family review → `triad-cross-family-review`.
- Live tmux observation → `triad-orchestrate` + tmux session.

## Isolation — per-call deny transaction (codex parity)

`--sandbox read-only|workspace-write` brackets the agy call in a global-settings
deny transaction (`_agy_settings.agy_settings_guard`): the wrapper merges
`permissions.deny` into `~/.gemini/antigravity-cli/settings.json`, runs agy, then
byte-exactly restores (flock-serialized, `.agybak` crash sentinel).

**agy tool → permission action map** (probed on agy 1.0.7, 2026-06-11 — re-confirm
with `agy -p "list your built-in tools and their permission actions"`):

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
  `triad-cross-family-review` / 사자회담 as an enforced read-only worker for the
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
2. **Path-based agent input.** Pass the run-log file *path* to the repair agent, not its content. Inline-embedding corrupts on JSON-in-JSON / utf-8 / ANSI / large vendor stdout.
3. **Cleanup after dispatch.** `rm -f <run-log-path>` once the repair agent returns (REPAIRED *or* ESCALATE). The wrapper failsafe is for orphans, not normal cleanup.
4. **Repair agent ONLY on `unknown` / `extraction-error` / `timeout`.** Every other classification carries actionable meaning at the wrapper layer — dispatching the agent on them wastes its 3-attempt budget.
5. **Test isolation — dispatch prompt = production-shape only.** Use the Step 5b template VERBATIM. No meta-context, no test framing, no "this is a verification" / "treat as fake" disclaimers, even when the dispatch is a sample/test scenario. See leader memory `feedback_dispatch_prompt_hygiene.md` for the full reasoning + fake run-log realistic-format guide.
6. **No model name pinning.** agy model names rot every few weeks. Use the vendor default by default; `--model <name>` only when the user explicitly named the model. Date-anchor any pinned model usage.
7. **Never `--dangerously-*`.** argparse rejects it (the flag is intentionally undefined), and it voids agy's `--sandbox` (agy issue #36). The Triad safety invariant forbids it regardless.
8. **Repair dispatch is MANDATORY and non-deferrable — spawn it in PARALLEL, never skip it.** When Step 4 routes a failure to repair (`unknown` / `extraction-error` / `timeout`), you MUST spawn the `agy-wrapper-repair` sub-agent. Surfacing the failure to the user does NOT discharge this — *surfacing* and *repairing* are SEPARATE obligations; doing one is not doing the other. "I have other / more important work", "the call already failed", "this looks like a one-off" are NEVER valid reasons to skip or defer the spawn. Remove the temptation to defer by dispatching with the `Agent` tool's **`run_in_background: true`** so it runs CONCURRENTLY with your foreground work; parse its output (Step 5c) + clean up (Step 5d) when it completes. Why non-skippable: the repair agent's payoff is FUTURE routing — framework completeness, NOT the immediate call — so it is a fire-in-parallel task, and skipping it is a silent regression that lets the same vendor error keep failing un-routed on every later call (origin: 2026-06-12 — a freshly-installed company plugin leader hit an HTTP 403 → `unknown`, reported only "failed", and skipped the spawn citing "other work"). Complements rule 4: rule 4 = dispatch ONLY for these classes; rule 8 = you MUST, in parallel, for these classes.

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
  the gemini wrapper. **Deferred e2e gate**: the real-agy "marker-after-JSON"
  adherence is **NOT yet e2e-verified** — the owner's earlier spike tested plain
  JSON WITHOUT the completion marker. The fake-agy integration proves the wrapper
  plumbing (sentinel parse + validate + repair re-run), not real-model adherence;
  a manual real-agy e2e run is the open verification gate.
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

Token set (slice 1):
`ok | server-capacity | cli-subscription-cap | token-limit | oauth-env | timeout | extraction-error | unknown`

Or branch on wrapper exit code: `0` / `1` / `2` (timeout) / `3` (arg) /
`4` (binary missing) / `64` (server-cap exhausted) / `65` (terminal).

### Step 4 — Branch on classification

| classification (rc) | Leader action |
|---|---|
| `ok` (0) | Return wrapper stdout (agy's final answer text). |
| terminal (65) — cli-subscription-cap / token-limit / oauth-env | Surface to user with cause (re-login / quota daily reset / prompt size too large). **NOT** repair-agent territory (already matched — only `unknown` / `extraction-error` / `timeout` route to repair). |
| `server-capacity` exhausted (64) | Wait + retry, or surface. Wrapper already retried per backoff (cap 2 pty re-runs). |
| `unknown` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 8). Spawn it even when you are busy or also surfacing the failure — never skip.** |
| `extraction-error` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 8).** agy ran but the extractor found no answer (clean output but empty, missing sentinel, vendor refusal text). Repair agent inspects whether the cause is a vendor refusal pattern worth a classifier patch, or a true extraction bug → ESCALATE. |
| `timeout` (2) | **Step 5 — repair agent dispatch.** Likely ESCALATE since a hang (pty killed at the print-timeout backstop) is rarely a classifier gap, but route through the same path for uniformity. Wrapper already fail-fasts (no retry on timeout). |
| arg (3) / binary missing (4) | Surface to user with cause (empty prompt / `agy` not on PATH). |

**NOT produced by agy slice 1** (do not branch on these — they belong to other
CLIs): `schema-rejected` / `fanout-spawn-error` / `config-conflict` /
`fanout-partial` / `task-blocked`. agy slice 1 has **no native schema** (so no
`schema-rejected`) and **no `--task` layer** (so no fan-out / code-task signals).

### Step 5 — Repair branch: repair agent dispatch (`unknown` / `extraction-error` / `timeout` only)

#### 5a. Extract the run-log path + derive the output path

```bash
RUN_LOG_PATH=$(grep -oE 'run-log: [^[:space:]]+' <stderr-text> \
                | tail -1 | awk '{print $2}')
[ -f "$RUN_LOG_PATH" ] || { echo "run-log path missing"; exit 1; }
OUTPUT_PATH="${RUN_LOG_PATH}.repair.json"
```

`OUTPUT_PATH` is the file the repair agent will write its JSON response to.
Conventionally `<run_log_path>.repair.json` — paired with the input so cleanup
is one `rm -f` covering both. Same directory means the wrapper's
`_prune_run_logs()` failsafe (`*.json` glob) catches orphans automatically.

#### 5b. Dispatch the repair sub-agent

Use the `Agent` tool with `subagent_type` set exactly to `agy-wrapper-repair`, **`run_in_background: true`** (Hard rule 8 — parallel, non-skippable; the `done`/`error` token + `output_path` arrive on completion, at which point you run Step 5c/5d).
**Use the prompt body below VERBATIM** — substitute only the `<RUN_LOG_PATH>`
and `<OUTPUT_PATH>` placeholders. Hard rule 5: no meta-context, no test framing,
no "note that..." lines.

The dispatch prompt is JSON-shaped: `run_log_path` + `output_path` (input) +
`output_schema` (output contract). The agent reads the run-log via `Read`,
builds the response object, **writes it to `output_path` using the `Write`
tool**, and returns only `done` or `error: <reason>` in chat.

```
You are a repair agent with a file-based response contract. Read the run-log, run repair workflow, then write your JSON response to output_path using the Write tool. Return ONLY a single token in chat: `done` (file written successfully) or `error: <one-line reason>` (Write failed). Do NOT include the JSON object in chat.

Input:
{
  "run_log_path": "<RUN_LOG_PATH>",
  "output_path": "<OUTPUT_PATH>",
  "output_schema": {
    "outcome":          "<string>  // 'REPAIRED' if framework now classifies the error correctly, 'ESCALATE' if 3 attempts failed or out of scope",
    "downstream":       "<string|null>  // leader's next-action signal mapped from re-run rc — 'ok' (rc=0, transient resolved), 'terminal:<class>' (rc=65, user action needed), 'retry-exhausted' (rc=64), 'timeout' (rc=2, if patch was timeout-related), null when ESCALATE",
    "patch":            "<string|null>  // description in '<file:line> — entry added' form, null when ESCALATE",
    "reason":           "<string>  // one-line semantic summary of what happened",
    "attempts":         "<int>  // 1-3",
    "per_attempt_log":  "<array>  // per-attempt records, each {n, hypothesis, source, patch, py_compile, rerun}"
  },
  "task": "Read the run-log, run repair workflow (extract literal error → WebSearch date-anchored → patch _common.py → py_compile → re-run with --repair-mode), then write the JSON object matching output_schema to output_path. 3-attempt ceiling, then escalate."
}

Example response (Write this JSON object to output_path):
{"outcome": "REPAIRED", "downstream": "oauth-env", "patch": "_common.py — added a verified auth-banner phrase to AGY_AUTH_BANNER_PATTERNS", "reason": "agy emitted a new re-login banner the seed pattern missed; framework now classifies it as oauth-env (user re-login signal)", "attempts": 1, "per_attempt_log": [{"n": 1, "hypothesis": "oauth-env", "source": "https://github.com/google/antigravity/issues/N", "patch": "AGY_AUTH_BANNER_PATTERNS += ('please re-authenticate to continue',)", "py_compile": "PASS", "rerun": "rc=65/classification=oauth-env"}]}

Now do the repair work, write the JSON to output_path, then return `done` in chat.
```

#### 5c. Parse the agent's file-based output

The agent's chat response is a single token (`done` or `error: ...`). The actual
JSON lives in `OUTPUT_PATH`:

```bash
case "$(printf '%s' "$AGENT_RESPONSE" | tr -d '[:space:]' | head -c 5)" in
  done) : ;;
  *) echo "agent did not complete: $AGENT_RESPONSE"; exit 1 ;;
esac

[ -f "$OUTPUT_PATH" ] || { echo "agent did not write output_path"; exit 1; }

OUTCOME=$(jq -r '.outcome' "$OUTPUT_PATH")
DOWNSTREAM=$(jq -r '.downstream // empty' "$OUTPUT_PATH")
REASON=$(jq -r '.reason' "$OUTPUT_PATH")
PATCH=$(jq -r '.patch // empty' "$OUTPUT_PATH")
ATTEMPTS=$(jq -r '.attempts' "$OUTPUT_PATH")
```

Default schema fields: `outcome`, `downstream` (null when ESCALATE), `patch`
(null when ESCALATE), `reason`, `attempts`, `per_attempt_log[]`.

Branch on (OUTCOME, DOWNSTREAM):

| OUTCOME | DOWNSTREAM | Next action |
|---|---|---|
| REPAIRED | ok | Re-run the original wrapper call. |
| REPAIRED | terminal:`<class>` | Surface to user with REASON. Framework now catches future calls. |
| REPAIRED | retry-exhausted | Wait + retry, or surface. Patch in place for future calls. |
| REPAIRED | timeout | Retry with adjusted timeout, or surface. |
| ESCALATE | (omit) | Surface per-attempt log + REASON. Manual diagnosis needed. |

#### 5d. Cleanup both run-log + repair-log

```bash
rm -f "$RUN_LOG_PATH" "$OUTPUT_PATH"
```

REPAIRED and ESCALATE both clean up — the leader has the parsed values in shell
vars. The wrapper's `_prune_run_logs()` (`glob("*.json")`) is the failsafe for
orphans (dispatch SKILL bypassed / leader crash).

## Outputs (what this skill returns)

- `ok`: wrapper stdout (agy's final answer text).
- terminal: `{ class, reason, action_required }`.
- server-cap-exhausted: "transient overload, leader-policy retry or surface".
- repair-cycle: ok-path after re-run, OR ESCALATE per-attempt log.

## Self-healing

Three layers keep the agy leg healthy without manual babysitting — two reactive
(per-call), one proactive (daily):

1. **`agy-wrapper-repair` sub-agent (reactive, per-call).** On an `unknown` /
   `extraction-error` / `timeout` classification, the dispatch flow (Step 5)
   routes to this agent, which patches `_common.py`'s classifier (one
   `ANTIGRAVITY_VENDOR_EXIT_MAP` entry or one L2 substring) so the next call
   auto-routes. Self-improving: dispatch frequency falls as the classifier
   matures.
2. **`.agybak` crash-recovery (reactive, per-call integrity).** Every agy call
   acquires an flock and heals a stale `.agybak` left by a crashed settings
   transaction *before* it runs, so no agy call ever executes against
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
   flags = `3rd-Agent/wrappers/README.md` § agy daily-check.

## Path scope

- **Reads** `_logs/antigravity/runs/<id>.json` (run-log) and `_logs/antigravity/runs/<id>.json.repair.json` (agent's file-based response).
- **Removes** both paths post-dispatch (REPAIRED + ESCALATE).
- **Invokes** `3rd-Agent/wrappers/antigravity_wrapper.py` via Bash.
- **Dispatches** sub-agent `agy-wrapper-repair`.

Does NOT edit `_common.py` (repair agent's territory) or read
`_logs/antigravity/audit.jsonl` (maintenance SKILL's territory).

## See also

- `3rd-Agent/wrappers/README.md` — wrapper contract + run-log schema.
- `.claude/agents/agy-wrapper-repair.md` — repair sub-agent body (per-attempt workflow + outcome judgment).
- `triad-codex-dispatch` — parallel SKILL for Codex.
- `triad-gemini-dispatch` — parallel SKILL for Gemini (agy's predecessor; gemini CLI public EOL 2026-06-18, but retained 사내 until ~2026-07-31 — both ship in the plugin until the 사내 sunset).
- `triad-cross-family-review` — final pre-merge cross-family review (the agy leg here is best-effort non-write, not enforced — see § Isolation HARD WARNING).
- `triad-orchestrate` — sibling SKILL (tmux base infra). 본 SKILL = wrapper subprocess only (tmux 미사용) — boundary 명확.
- Leader memory `feedback_dispatch_prompt_hygiene.md` — dispatch prompt hygiene + test isolation rationale.
