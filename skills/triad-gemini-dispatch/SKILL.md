---
name: triad-gemini-dispatch
description: Use when the leader (Triad orchestrator) needs to dispatch a single-shot Gemini CLI call via the wrapper framework. Triggering signals — leader is about to run `python3 gemini_wrapper.py` raw; user said "gemini 한 번 불러줘" / "gemini로 X 처리" / "gemini CLI 단발 실행" / "제미나이 호출"; a higher-level orchestration SKILL needs the Gemini leg of a fan-out; classification-aware routing with self-improving repair-agent fallback is needed instead of raw subprocess. Symptoms of skipping this SKILL — unknown classification failures don't reach the repair sub-agent, run-log files accumulate uncleaned, the framework's self-improving classifier never grows. Do NOT use for Codex (use `triad-codex-dispatch`).
version: 0.3.1
---

# triad-gemini-dispatch

Single-shot Gemini CLI dispatch with classification-based routing and a
self-improving repair loop. The leader's standard "call gemini once" path.

## Use when

- Leader has a discrete prompt and needs Gemini's answer (or a structured failure signal). Gemini is preferred for Android domain (XML / Compose / Material), vision tasks, Google-ecosystem queries.
- A higher-level SKILL (e.g. `triad-cross-family-review`) wants the Gemini leg of a fan-out.
- User said "gemini 한 번 불러서 X" / "gemini CLI 로 단발 실행" / "제미나이 호출".

Going through this SKILL (instead of raw `python3 gemini_wrapper.py`) is what
makes the `unknown`-classification path correctly route to the repair sub-agent.

## Skip when

- Codex-side calls → `triad-codex-dispatch`.

## Hard rules

1. **Bash invocation only.** No `Agent()` around the wrapper itself. The stderr `[wrapper]` summary line and `run-log:` path emission only surface via Bash.
2. **Path-based agent input.** Pass the run-log file *path* to the repair agent, not its content. Inline-embedding corrupts on JSON-in-JSON / utf-8 / ANSI / large vendor stdout.
3. **Cleanup after dispatch.** `rm -f <run-log-path>` once the repair agent returns (REPAIRED *or* ESCALATE). The wrapper failsafe is for orphans, not normal cleanup.
4. **Repair agent ONLY on `unknown`.** Other classifications carry actionable meaning at the wrapper layer — dispatching the agent on them wastes its 3-attempt budget.
5. **Test isolation — dispatch prompt = production-shape only.** Use the Step 5b template VERBATIM. No meta-context, no test framing, no "this is a verification" / "treat as fake" disclaimers, even when the dispatch is a sample/test scenario. See leader memory `feedback_dispatch_prompt_hygiene.md` for the full reasoning + fake run-log realistic-format guide.
6. **No model name pinning.** Gemini model names rot every few weeks. Use vendor's Auto router by default; `--model <name>` only when the user explicitly named the model. Date-anchor any pinned model usage.
7. **Repair dispatch is MANDATORY and non-deferrable — spawn it in PARALLEL, never skip it.** When Step 4 routes a failure to repair (`unknown` / `extraction-error` / `timeout`), you MUST spawn the `gemini-wrapper-repair` sub-agent. Surfacing the failure to the user does NOT discharge this — *surfacing* and *repairing* are SEPARATE obligations; doing one is not doing the other. "I have other / more important work", "the call already failed", "this looks like a one-off" are NEVER valid reasons to skip or defer the spawn. Remove the temptation to defer by dispatching with the `Agent` tool's **`run_in_background: true`** so it runs CONCURRENTLY with your foreground work; parse its output (Step 5c) + clean up (Step 5d) when it completes. Why non-skippable: the repair agent's payoff is FUTURE routing — framework completeness, NOT the immediate call — so it is a fire-in-parallel task, and skipping it is a silent regression that lets the same vendor error keep failing un-routed on every later call (origin: 2026-06-12 — a freshly-installed company plugin leader hit an HTTP 403 → `unknown`, reported only "failed", and skipped the spawn citing "other work"). Complements rule 4: rule 4 = dispatch ONLY for these classes; rule 7 = you MUST, in parallel, for these classes.
8. **No plan/yolo approval modes.** The wrapper argparse accepts only `--approval-mode default|auto_edit`. Read-only dispatch uses `--sandbox read-only`, which attaches the per-call Policy Engine file instead of Gemini plan mode. `yolo` is not a permitted mode in this repo.

## Flow

### Step 1 — Build the wrapper invocation

Single-quoted heredoc for the prompt body so Korean / emoji / `$variables` / backticks / quotes survive intact:

```bash
gemini_wrapper.py \
  --prompt "$(cat <<'PROMPT'
<leader-prompt-verbatim>
PROMPT
)" \
  [--cwd /absolute/path] \
  [--sandbox read-only|workspace-write] \
  [--approval-mode default|auto_edit] \
  [--model <pinned-model-name>] \
  [--skip-trust] \
  [--timeout <seconds>] \
  [--pydantic module:Class]
```

Defaults: no `--sandbox` policy and `--approval-mode default` (read auto, write/shell prompt). `--sandbox read-only` attaches `bin/policies/gemini-readonly.toml` for that call only. `auto_edit` = write/shell auto (only on explicit leader request) and conflicts with `--sandbox read-only`. `--approval-mode plan/yolo` is rejected by argparse.

> **Historical reason for the ban (2026-06-08): `plan` mode was unreliable for HEAVY multi-file agentic reads.** On a heavy task (e.g. "read 16 source files in full and review"), the Pro plan-loop emitted an empty/malformed turn (vendor `Invalid stream: The model returned an empty response or malformed tool call`), surfacing as `extraction-error` (rc=1) in ~10-25s. That history is why this wrapper no longer exposes `plan`; use `--sandbox read-only` for read-only reviews and `--approval-mode default` for normal reads.

`--skip-trust` is needed when the cwd is not yet trusted in `~/.gemini/trustedFolders.json` — without it the CLI hangs on the trust dialog.

### Step 2 — Run via Bash; capture rc, stdout, stderr

Wrapper stderr contains:
- Timestamped wrapper log lines
- Mirrored vendor stderr (~189 B baseline: `Warning:` + `Ripgrep`; on error, may include trailing JSON `{error: ...}`)
- 1-line summary: `[wrapper] gemini <classification> exit=<int> vendor=<int> elapsed=<s>`
- On failure: `run-log: <absolute-path>`

### Step 3 — Read the classification

Grep the summary line; extract classification. **Use the LAST `[wrapper]` line** — when extraction-error happens (Gemini empty `response` field, valid JSON envelope but no answer), `_run_once` emits an early `ok` summary that is later corrected by a second emission with `extraction-error`. Take the last one only:

```bash
SUMMARY=$(grep '^\[.*\] \[wrapper\] gemini ' <stderr-text> | tail -1)
CLS=$(printf '%s' "$SUMMARY" | sed -E 's/.*\[wrapper\] gemini ([a-z-]+) .*/\1/')
```

Token set:
`ok | server-capacity | cli-subscription-cap | token-limit | oauth-env | timeout | extraction-error | unknown`

Or branch on wrapper exit code: `0` / `1` / `2` (timeout) / `3` (arg) / `4` (binary missing) / `64` (server-cap exhausted) / `65` (terminal) / `66` (schema fail).

### Step 4 — Branch on classification

| classification (rc) | Leader action |
|---|---|
| `ok` (0) | Return wrapper stdout (Gemini's `response` field text or pydantic-validated JSON). |
| terminal (65) — cli-subscription-cap / token-limit / oauth-env | Surface to user with cause (re-login / Pro 200 or Flash 1800 daily reset / prompt size). **NOT** repair-agent territory. |
| `server-capacity` exhausted (64) | Wait + retry, or surface. Wrapper retried per backoff (plus Gemini's own internal retries). |
| `unknown` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 7). Spawn it even when you are busy or also surfacing the failure — never skip.** |
| `extraction-error` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 7).** Vendor returned rc=0 but extractor found no answer (empty `response` field, unparseable JSON, vendor refusal text). Repair agent inspects whether the cause is a vendor refusal pattern worth a classifier patch, or a true extraction bug → ESCALATE. |
| `timeout` (2) | **Step 5 — repair agent dispatch.** Likely ESCALATE since hang is rarely a classifier gap, but route through the same path for uniformity. Wrapper already fail-fasts (no retry on timeout). |
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

Use the `Agent` tool with `subagent_type` set exactly to `gemini-wrapper-repair`, **`run_in_background: true`** (Hard rule 7 — parallel, non-skippable; the `done`/`error` token + `output_path` arrive on completion, at which point you run Step 5c/5d). **Use the prompt body below VERBATIM** — substitute only the `<RUN_LOG_PATH>` and `<OUTPUT_PATH>` placeholders. Hard rule 5: no meta-context, no test framing, no "note that..." lines.

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
{"outcome": "REPAIRED", "downstream": "ok", "patch": "_common.py:78 — added 'quota will reset' to CLI_SUB_CAP_PATTERNS", "reason": "transient quota issue, framework now classifies", "attempts": 1, "per_attempt_log": [{"n": 1, "hypothesis": "cli-subscription-cap", "source": "https://github.com/google-gemini/gemini-cli/issues/N", "patch": "CLI_SUB_CAP_PATTERNS += ('quota will reset',)", "py_compile": "PASS", "rerun": "rc=0/classification=ok"}]}

Now do the repair work, write the JSON to output_path, then return `done` in chat.
```

#### 5c. Parse the agent's file-based output

The agent's chat response is a single token (`done` or `error: ...`). The actual JSON lives in `OUTPUT_PATH`:

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

REPAIRED and ESCALATE both clean up — leader has the parsed values in shell vars. Wrapper's `_prune_run_logs()` (`glob("*.json")`) is the failsafe for orphans (dispatch SKILL bypassed / leader crash).

## Outputs (what this skill returns)

- `ok`: wrapper stdout (Gemini's `response` field or pydantic-validated JSON).
- terminal: `{ class, reason, action_required }`.
- server-cap-exhausted: "transient overload, leader-policy retry or surface".
- repair-cycle: ok-path after re-run, OR ESCALATE per-attempt log.

## Path scope

- **Reads** `_logs/gemini/runs/<id>.json` (run-log) and `_logs/gemini/runs/<id>.json.repair.json` (agent's file-based response).
- **Removes** both paths post-dispatch (REPAIRED + ESCALATE).
- **Invokes** `3rd-Agent/wrappers/gemini_wrapper.py` via Bash.
- **Dispatches** sub-agent `gemini-wrapper-repair`.

Does NOT edit `_common.py` (repair agent's territory) or read `_logs/gemini/audit.jsonl` (maintenance SKILL's territory).

## See also

- `3rd-Agent/wrappers/README.md` — wrapper contract + run-log schema.
- `.claude/agents/gemini-wrapper-repair.md` — repair sub-agent body (per-attempt workflow + outcome judgment).
- `triad-codex-dispatch` — parallel SKILL for Codex.
- Leader memory `feedback_dispatch_prompt_hygiene.md` — dispatch prompt hygiene + test isolation rationale.
