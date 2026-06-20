---
name: triad-codex-dispatch
description: Use when the leader (Triad orchestrator) needs to dispatch a single-shot Codex CLI call via the wrapper framework. Triggering signals — leader is about to run `python3 codex_wrapper.py` raw; user said "codex 한 번 불러줘" / "codex로 X 처리" / "codex CLI 단발 실행" / "코덱스 호출"; a higher-level orchestration SKILL needs the Codex leg of a fan-out; classification-aware routing with self-improving repair-agent fallback is needed instead of raw subprocess. Symptoms of skipping this SKILL — unknown classification failures don't reach the repair sub-agent, run-log files accumulate uncleaned, the framework's self-improving classifier never grows. Do NOT use for Gemini (use `triad-gemini-dispatch`).
version: 0.5.1
---

# triad-codex-dispatch

Single-shot Codex CLI dispatch with classification-based routing and a
self-improving repair loop. The leader's standard "call codex once" path.

## Use when

- Leader has a discrete prompt and needs Codex's answer (or a structured failure signal).
- A higher-level SKILL (e.g. `triad-cross-family-review`) wants the Codex leg of a fan-out.
- User said "codex 한 번 불러서 X" / "codex로 단발 실행".

Going through this SKILL (instead of raw `python3 codex_wrapper.py`) is what
makes the `unknown`-classification path correctly route to the repair sub-agent.

## Skip when

- Gemini-side calls → `triad-gemini-dispatch`.

## Hard rules

1. **Bash invocation only.** No `Agent()` around the wrapper itself. The stderr `[wrapper]` summary line and `run-log:` path emission only surface via Bash.
2. **Path-based agent input.** Pass the run-log file *path* to the repair agent, not its content. Inline-embedding corrupts on JSON-in-JSON / utf-8 / ANSI / large vendor stdout.
3. **Cleanup after dispatch.** `rm -f <run-log-path>` once the repair agent returns (REPAIRED *or* ESCALATE). The wrapper failsafe is for orphans, not normal cleanup.
4. **Repair agent ONLY on `unknown`.** Other classifications carry actionable meaning at the wrapper layer — dispatching the agent on them wastes its 3-attempt budget.
5. **Test isolation — dispatch prompt = production-shape only.** Use the Step 5b template VERBATIM. No meta-context, no test framing, no "this is a verification" / "treat as fake" disclaimers, even when the dispatch is a sample/test scenario. See leader memory `feedback_dispatch_prompt_hygiene.md` for the full reasoning + fake run-log realistic-format guide.
6. **Repair dispatch is MANDATORY and non-deferrable — spawn it in PARALLEL, never skip it.** When Step 4 routes a failure to repair (`unknown` / `extraction-error` / `timeout`), you MUST spawn the `codex-wrapper-repair` sub-agent. Surfacing the failure to the user does NOT discharge this — *surfacing* and *repairing* are SEPARATE obligations; doing one is not doing the other. "I have other / more important work", "the call already failed", "this looks like a one-off" are NEVER valid reasons to skip or defer the spawn. Remove the temptation to defer by dispatching with the `Agent` tool's **`run_in_background: true`** so it runs CONCURRENTLY with your foreground work; parse its output (Step 5c) + clean up (Step 5d) when it completes. Why non-skippable: the repair agent's payoff is FUTURE routing — framework completeness, NOT the immediate call — so it is a fire-in-parallel task, and skipping it is a silent regression that lets the same vendor error keep failing un-routed on every later call (origin: 2026-06-12 — a freshly-installed company plugin leader hit an HTTP 403 → `unknown`, reported only "failed", and skipped the spawn citing "other work"). Complements rule 4: rule 4 = dispatch ONLY for these classes; rule 6 = you MUST, in parallel, for these classes.

## Flow

### Step 1 — Build the wrapper invocation

Single-quoted heredoc for the prompt body so Korean / emoji / `$variables` / backticks / quotes survive intact:

```bash
codex_wrapper.py \
  --prompt "$(cat <<'PROMPT'
<leader-prompt-verbatim>
PROMPT
)" \
  [--cwd /absolute/path] \
  [--sandbox read-only|workspace-write] \
  [--reasoning low|medium|high|xhigh] \
  [--search] \
  [--timeout <seconds>] \
  [--pydantic module:Class] \
  [--image /absolute/path.png ...] \
  [--format text|markdown|json] \
  [--task review|analyze|brainstorm|code] \
  [--fanout N|auto] \
  [--report-dir /absolute/path]
```

Defaults: `--sandbox read-only`. Triad policy disallows `danger-full-access` — argparse rejects it at parse time.

**`--search`** enables codex's live web search (codex's top-level `--search`, inserted
before `exec`; default OFF). Opt in for **research / consult / review** dispatches where
current web grounding matters; leave OFF for routine calls (API-billed + slower).

**Reasoning-effort guideline.** `--reasoning` overrides `model_reasoning_effort` for this dispatch; omit it to inherit the config-alive value (the user's `~/.codex/config.toml`, currently `medium`). Set it by intent, not by default: `high` for **review / planning / non-trivial `code` or `analyze` tasks** (bug-hunting, design/spec review, multi-file reasoning); `xhigh` only for **deep architecture review or long refactors**; `low` for trivial/mechanical work where speed matters. Leave it unset for routine dispatches — config-alive already supplies a sensible default, and over-setting `xhigh` burns latency/quota. (`minimal` is intentionally not exposed — no leader/user use case.)

The prompt is delivered to codex via **stdin** internally (caller still passes `--prompt`). `--pydantic` drives codex's native `--output-schema` (the class is massaged to codex-strict shape); a submit-time refusal surfaces as `schema-rejected` (rc 67). `--image` (repeatable) passes vision inputs as codex `-i` (bad path → `EXIT_ARG_ERROR` pre-spawn). `--format` is output intent — explicit `markdown`/`text` is mutually exclusive with `--pydantic`. `--task` activates the read-only multi-agent fan-out worker layer: it augments the prompt with a deterministic framing + fan-out tier (`--fanout N` 1-12 default 3, or `auto` to let codex decide via the dispatching-parallel-agents skill), pins `--sandbox read-only`, and writes a report — `codex-<task>-synthesis.md` (codex's consolidated answer) + per-agent `codex-<task>-agentN-raw.md` — to `--report-dir` (optional; defaults to a temp dir whose path is logged to stderr). A partial fan-out (a subagent that never completes) carries an `INCOMPLETE` banner in the synthesis. Exception: `--task code` is a write-enabled single TDD implementer (sandbox `workspace-write`, `default_fanout=1`, STATUS-line output) — see § Code task.

### Step 2 — Run via Bash; capture rc, stdout, stderr

Wrapper stderr contains:
- Timestamped wrapper log lines
- Mirrored vendor stderr (Codex `--json` keeps this small, ~39 B)
- 1-line summary: `[wrapper] codex <classification> exit=<int> vendor=<int> elapsed=<s>`
- On failure: `run-log: <absolute-path>`

### Step 3 — Read the classification

Grep the summary line; extract classification. **Use the LAST `[wrapper]` line** — when extraction-error happens, `_run_once` emits an early `ok` summary that is later corrected by a second emission with `extraction-error`. Take the last one only:

```bash
SUMMARY=$(grep '^\[.*\] \[wrapper\] codex ' <stderr-text> | tail -1)
CLS=$(printf '%s' "$SUMMARY" | sed -E 's/.*\[wrapper\] codex ([a-z-]+) .*/\1/')
```

Token set:
`ok | server-capacity | cli-subscription-cap | token-limit | oauth-env | schema-rejected | fanout-spawn-error | config-conflict | timeout | extraction-error | unknown | fanout-partial`

Or branch on wrapper exit code: `0` / `1` / `2` (timeout) / `3` (arg) / `4` (binary missing) / `64` (server-cap exhausted) / `65` (terminal) / `66` (schema fail) / `67` (schema-rejected — `--output-schema` refused at submit) / `68` (fanout-partial — `--task` fan-out incomplete) / `69` (task-blocked — `--task code` implementer BLOCKED/NEEDS_CONTEXT).

### Step 4 — Branch on classification

| classification (rc) | Leader action |
|---|---|
| `ok` (0) | Return wrapper stdout. With `--pydantic`, stdout is the validated JSON object. |
| terminal (65) — cli-subscription-cap / token-limit / oauth-env / fanout-spawn-error / config-conflict | Surface to user with cause (re-login / quota / prompt size / `--task` subagent spawn rejected / inherited `~/.codex/config.toml` parse error). **NOT** repair-agent territory (already matched — only `unknown` routes to repair). |
| `server-capacity` exhausted (64) | Wait + retry, or surface. Wrapper already retried per backoff. |
| `unknown` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 6). Spawn it even when you are busy or also surfacing the failure — never skip.** |
| `extraction-error` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 6).** Vendor returned rc=0 but extractor found no answer (empty JSON envelope, missing last-message file). Repair agent inspects whether the cause is a vendor refusal pattern worth a classifier patch, or a true extraction bug → ESCALATE. |
| `timeout` (2) | **Step 5 — repair agent dispatch.** Likely ESCALATE since hang is rarely a classifier gap, but route through the same path for uniformity. Wrapper already fail-fasts (no retry on timeout). |
| `schema-rejected` (67) | Surface to user: the pydantic class / massaged schema is invalid for codex strict mode, or codex strict-rule drift. Fix the class / massage and re-dispatch. **NOT** repair-agent territory (deterministic, not transient). Distinct from `schema fail (66)` = post-hoc pydantic validation failing after a well-formed answer. |
| `fanout-partial` (68) | The `--task` fan-out did not fully complete (partial / zero / fewer-than-requested subagents). stdout carries an INCOMPLETE banner. Treat the synthesis as partial; inspect the per-agent raw + report. **NOT** repair territory. |
| exit 69 / `EXIT_TASK_BLOCKED` | `--task code` implementer self-reported BLOCKED or NEEDS_CONTEXT. Read the STATUS-line report in stdout, re-dispatch with the missing context, or escalate to the user. **NOT** a repair-agent dispatch — this is a status signal, not a classification failure. No edit was committed. |
| arg (3) / binary missing (4) / schema fail (66) | Surface to user with cause. |

### Step 5 — Unknown branch: repair agent dispatch

#### 5a. Extract the run-log path + derive the output path

```bash
RUN_LOG_PATH=$(grep -oE 'run-log: [^[:space:]]+' <stderr-text> \
                | tail -1 | awk '{print $2}')
[ -f "$RUN_LOG_PATH" ] || { echo "run-log path missing"; exit 1; }
OUTPUT_PATH="${RUN_LOG_PATH}.repair.json"
```

`OUTPUT_PATH` is the file the repair agent will write its JSON response to. Conventionally `<run_log_path>.repair.json` — paired with the input so cleanup is one `rm -f` covering both. Same directory means wrapper's `_prune_run_logs()` failsafe (`*.json` glob) catches orphans automatically.

#### 5b. Dispatch the repair sub-agent

Use the `Agent` tool with `subagent_type` set exactly to `codex-wrapper-repair`, **`run_in_background: true`** (Hard rule 6 — parallel, non-skippable; the `done`/`error` token + `output_path` arrive on completion, at which point you run Step 5c/5d). **Use the prompt body below VERBATIM** — substitute only the `<RUN_LOG_PATH>` and `<OUTPUT_PATH>` placeholders. Hard rule 5: no meta-context, no test framing, no "note that..." lines.

The dispatch prompt is JSON-shaped: `run_log_path` + `output_path` (input) + `output_schema` (output contract). The agent reads the run-log via `Read`, builds the response object, **writes it to `output_path` using the `Write` tool**, and returns only `done` or `error: <reason>` in chat.

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
{"outcome": "REPAIRED", "downstream": "ok", "patch": "_common.py:71 — added 'rate limit' to SERVER_CAPACITY_PATTERNS", "reason": "transient backend rate throttle, framework now classifies", "attempts": 1, "per_attempt_log": [{"n": 1, "hypothesis": "server-capacity", "source": "https://github.com/openai/codex/issues/N", "patch": "SERVER_CAPACITY_PATTERNS += ('rate limit',)", "py_compile": "PASS", "rerun": "rc=0/classification=ok"}]}

Now do the repair work, write the JSON to output_path, then return `done` in chat.
```

#### 5c. Parse the agent's file-based output

The agent's chat response is a single token (`done` or `error: ...`). The actual JSON lives in `OUTPUT_PATH`:

```bash
# Sanity — chat must say `done`. Otherwise the agent didn't write the file.
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

Default schema fields: `outcome`, `downstream` (null when ESCALATE), `patch` (null when ESCALATE), `reason`, `attempts`, `per_attempt_log[]`.

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

REPAIRED and ESCALATE both clean up — leader has the parsed values in shell vars (REASON / per-attempt log surfacing). Wrapper's `_prune_run_logs()` (`glob("*.json")`) is the failsafe for orphans (dispatch SKILL bypassed / leader crash).

## Outputs (what this skill returns)

- `ok`: wrapper stdout (raw answer or pydantic-validated JSON).
- terminal: `{ class, reason, action_required }`.
- server-cap-exhausted: "transient overload, leader-policy retry or surface".
- repair-cycle: ok-path after re-run, OR ESCALATE per-attempt log.
- task-blocked (exit 69): leader reads the STATUS report; re-dispatch with context or escalate. No commit.

## Path scope

- **Reads** `_logs/codex/runs/<id>.json` (run-log) and `_logs/codex/runs/<id>.json.repair.json` (agent's file-based response).
- **Removes** both paths post-dispatch (REPAIRED + ESCALATE).
- **Invokes** `3rd-Agent/wrappers/codex_wrapper.py` via Bash.
- **Dispatches** sub-agent `codex-wrapper-repair`.

Does NOT edit `_common.py` (repair agent's territory) or read `_logs/codex/audit.jsonl` (maintenance SKILL's territory).

## Code task (Archetype B) — autonomous coding worker

`--task code` dispatches codex as a single TDD implementer that edits inside an
isolated git worktree (`workspace-write`) and returns a STATUS-line report.
**codex never commits** (`.git` is read-only under the sandbox by design); the
leader verifies and commits. This mirrors a superpowers implementer subagent,
but the worker is a codex process.

The wrapper is **transport-only**: worktree lifecycle, verification, and the
commit all live here in the leader's deterministic steps. The wrapper only
takes `--cwd`.

**Residual risk (config-alive, `workspace-write`):** A `--task code` worker
runs under `workspace-write` with **network and MCP reachable** (config-alive;
`approval_policy=never` closes auto-approve escalation but does NOT disable
network). A write-enabled worker with a reachable network is a
data-exfiltration residual risk. This is an accepted research-lab posture
(owner decision) and is **NOT** a production isolation guarantee. The leader
should be aware when dispatching code tasks on sensitive repositories.

### Leader procedure

1. **Scope.** Have a well-specified single task, the base ref, and the
   project's verify command (`verify-cmd`, e.g. `bash tests/run.sh ...` for the
   triad repo). The verify-cmd is leader input — the wrapper does not know it.
2. **Isolate.** `git worktree add <path> <base>` (a fresh branch).
   The `--cwd` passed to the wrapper MUST be this freshly-created isolated git
   worktree, NOT the live repo working tree. The wrapper enforces `--cwd`
   presence (rejects `--task code` without it — `EXIT_ARG_ERROR`), but
   worktree-ness is the leader's responsibility. codex edits are write-enabled
   inside `--cwd`; using the live working tree would corrupt it.
3. **Dispatch.** `codex_wrapper.py --task code --cwd <path> --prompt "<task spec>"` for a simple task. For a complex task add `--fanout auto` (codex self-decomposes via its dispatching-parallel-agents skill, parallelizing only independent work and serializing edits). Explicit `--fanout N>1` is rejected.
4. **Branch on the exit code.**
   - `0` (STATUS DONE / DONE_WITH_CONCERNS) → proceed to verify.
     **Note:** if the wrapper returns exit 0 but the report has NO `STATUS:` first
     line (the wrapper's safe fallback for a missing STATUS), treat the result with
     SUSPICION. The leader-side verify-cmd (step 5) is the authoritative gate; do
     not trust a status-less "success".
   - `69` (EXIT_TASK_BLOCKED — codex self-reported BLOCKED / NEEDS_CONTEXT) → read the report, re-dispatch with the missing context, or escalate. Do NOT verify/commit.
   - any other non-zero → a real wrapper/vendor failure (see the Step 4 table); handle per that table.
5. **Verify (leader-side, authoritative).** Run the verify-cmd INSIDE the worktree, outside the sandbox: `( cd <path> && <verify-cmd> )`. codex's in-sandbox TDD is best-effort self-correction; this run is the commit gate.
6. **Review.** `git -C <path> diff`, scoped to intended paths (ignore `__pycache__/` and other build artifacts pytest may create). Read codex's report. For merge-worthy or correctness-critical changes, run `triad-cross-family-review` (self-rule #6) BEFORE committing.
7. **Commit (leader/user judgment).** If verify passed and the review is clean: commit/merge into the main repo, noting "implemented by codex worker (Archetype B)" in the message body (author-disclosure). If verify failed or the change is doubtful: reject, re-dispatch with the failure as context, or escalate.
8. **Cleanup.** `git worktree remove <path>`.

### Escalation tiers

| Task | Invocation |
|---|---|
| simple, well-scoped | `--task code` (single implementer, no fan-out) |
| complex | `--task code --fanout auto` (codex self-decomposes; the safety of this path is scrutinized under self-rule #6) |

**`--fanout auto` assumption (owner decision):** `--task code --fanout auto`
relies on codex's `dispatching-parallel-agents` skill to parallelize only
independent work and serialize conflicting edits. This is an accepted
assumption (owner decision), empirically validated only at `fanout=1` so far.
The leader's out-of-sandbox verify-cmd (step 5) plus diff review (step 6) is
the safety net if codex's decomposition produces unexpected interactions across
edits. The `auto` tier is retained per owner decision — this note documents
the assumption, not a prohibition.

## Direct `codex exec` knowledge — sandbox grants, execpolicy rules, skills

(Added 2026-06-10 — facts proven in the IngenuityPrint cross-CLI authoring
work; Tier-1 verified against the official codex skills doc
(developers.openai.com/codex/skills) + installed `codex-cli 0.137.0` help.)

The wrapper covers single-shot Q&A / `--task` dispatches. Some invocations
are NOT expressible through the wrapper — it pins `--ephemeral` (ephemeral
threads do not support `/goal`) and exposes no `--add-dir` / arbitrary `-c`
passthrough. For those, the leader (or a project-side skill, e.g.
IngenuityPrint `codex-tc-writer`) builds a direct `codex exec` invocation.
Keep these facts straight instead of re-deriving them from memory:

### Extra writable roots (multiple workspaces)

- `--add-dir <DIR>` — additional writable directory alongside the primary
  workspace. **Repeatable** (one flag per dir). Official docs recommend it
  over widening the sandbox level.
- Config-equivalent: `-c 'sandbox_workspace_write.writable_roots=["/a","/b"]'`
  — TOML value, not JSON.
- `/tmp` (and `$TMPDIR`) are writable BY DEFAULT in `workspace-write` — the
  config keys `sandbox_workspace_write.exclude_slash_tmp` /
  `exclude_tmpdir_env_var` exist precisely as opt-OUTs (cross-family
  Tier-1 verification 2026-06-10, refuting the earlier "always needs a
  grant" claim). An explicit `--add-dir /tmp/<dir>` is still good practice:
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
- Prefer-narrow rule (empirical, 2026-06-10): when the helper only needs
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
  (candidate follow-up; touching it triggers the 3rd-Agent doc-sync chain —
  `3rd-Agent/CLAUDE.md` § Mandatory doc updates).
- Proven instance: IngenuityPrint repo
  `.claude/skills/codex-tc-writer/SKILL.md` (leader dispatch procedure) +
  `.claude/skills/nl-to-yaml-author/references/cross-cli.md` (v5 flag notes).

## See also

- `3rd-Agent/wrappers/README.md` — wrapper contract + run-log schema.
- `.claude/agents/codex-wrapper-repair.md` — repair sub-agent body (per-attempt workflow + outcome judgment).
- `triad-codex-reference` — codex CLI flag / sub-command lookup (raw `--help` dumps; this SKILL's § Direct `codex exec` knowledge carries the curated facts).
- `triad-gemini-dispatch` — parallel SKILL for Gemini.
- Leader memory `feedback_dispatch_prompt_hygiene.md` — dispatch prompt hygiene + test isolation rationale.
