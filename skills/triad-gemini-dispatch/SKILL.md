---
name: triad-gemini-dispatch
description: Use when the leader (Triad orchestrator) needs to dispatch a single-shot Gemini CLI call via the wrapper framework. Triggering signals — leader is about to run `python3 gemini_wrapper.py` raw; user said "gemini 한 번 불러줘" / "gemini로 X 처리" / "gemini CLI 단발 실행" / "제미나이 호출"; a higher-level orchestration SKILL needs the Gemini leg of a fan-out; classification-aware routing with self-improving repair-agent fallback is needed instead of raw subprocess. Symptoms of skipping this SKILL — unknown classification failures don't reach the repair sub-agent, run-log files accumulate uncleaned, the framework's self-improving classifier never grows. Do NOT use for Codex (use `triad-codex-dispatch`).
version: 0.4.0
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
2. **Path-based agent input.** Pass the run-log file *path* to the repair agent, not its content. Inline-embedding corrupts on JSON-in-JSON / utf-8 / ANSI / large vendor stdout. The leader itself does NOT read the run-log content — it only passes the PATH to the read-only analyzer, and reads back (a) the wrapper's deterministic classification token and (b) the analyzer's inline JSON proposal. The run-log is untrusted vendor output; keeping the leader out of it preserves the privilege separation.
3. **Cleanup after dispatch.** `rm -f <run-log-path>` once the repair analyzer returns (propose *or* escalate) and you have applied/surfaced. The wrapper failsafe is for orphans, not normal cleanup.
4. **Repair agent ONLY on `unknown` / `extraction-error` / `timeout`.** Every other classification carries actionable meaning at the wrapper layer — dispatching the agent on them wastes the call.
5. **Test isolation — dispatch prompt = production-shape only.** Use the Step 5b template VERBATIM. No meta-context, no test framing, no "this is a verification" / "treat as fake" disclaimers, even when the dispatch is a sample/test scenario. Reasoning: any test framing leaks into the vendor model's behavior and corrupts both the sample and the repair agent's accumulated memory.
6. **No model name pinning.** Gemini model names rot every few weeks. Use vendor's Auto router by default; `--model <name>` only when the user explicitly named the model. Date-anchor any pinned model usage.
7. **Repair dispatch is MANDATORY and non-deferrable — spawn it in PARALLEL, never skip it.** When Step 4 routes a failure to repair (`unknown` / `extraction-error` / `timeout`), you MUST spawn the `gemini-wrapper-repair` sub-agent. Surfacing the failure to the user does NOT discharge this — *surfacing* and *repairing* are SEPARATE obligations; doing one is not doing the other. "I have other / more important work", "the call already failed", "this looks like a one-off" are NEVER valid reasons to skip or defer the spawn. Remove the temptation to defer by dispatching with the `Agent` tool's **`run_in_background: true`** so it runs CONCURRENTLY with your foreground work; parse its inline proposal (Step 5c) + apply it + clean up (Step 5d) when it completes. **Mechanism:** the repair agent is a read-only ANALYZER that returns an inline JSON patch proposal; the LEADER applies it via the deterministic `apply_patch.py` and verifies routing with a `--repair-mode` re-run. The analyzer has zero write authority; the write path has zero LLM. Why non-skippable: the repair analyzer's payoff is FUTURE routing — framework completeness, NOT the immediate call — so it is a fire-in-parallel task, and skipping it is a silent regression that lets the same vendor error keep failing un-routed on every later call (origin: 2026-06-12 — a freshly-installed company plugin leader hit an HTTP 403 → `unknown`, reported only "failed", and skipped the spawn citing "other work"). Complements rule 4: rule 4 = dispatch ONLY for these classes; rule 7 = you MUST, in parallel, for these classes.
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

Defaults: no `--sandbox` policy and `--approval-mode default` (read auto, write/shell prompt). `--sandbox read-only` attaches the wrapper-adjacent `policies/gemini-readonly.toml` for that call only. `auto_edit` = write/shell auto (only on explicit leader request) and conflicts with `--sandbox read-only`. `--approval-mode plan/yolo` is rejected by argparse.

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
| terminal (65) — cli-subscription-cap / token-limit / oauth-env | Surface to user with cause (re-login / Code Assist license daily-quota or API-key RPM-tier reset / prompt size — see the enterprise auth note). **NOT** repair-agent territory. |
| `server-capacity` exhausted (64) | Wait + retry, or surface. Wrapper retried per backoff (plus Gemini's own internal retries). |
| `unknown` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 7). Spawn it even when you are busy or also surfacing the failure — never skip.** |
| `extraction-error` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 7).** Vendor returned rc=0 but extractor found no answer (empty `response` field, unparseable JSON, vendor refusal text). Repair agent inspects whether the cause is a vendor refusal pattern worth a classifier patch, or a true extraction bug → ESCALATE. |
| `timeout` (2) | **Step 5 — repair agent dispatch.** Likely ESCALATE since hang is rarely a classifier gap, but route through the same path for uniformity. Wrapper already fail-fasts (no retry on timeout). |
| arg (3) / binary missing (4) / schema fail (66) | Surface to user with cause. |

### Step 5 — Repair branch: read-only analyzer proposes, leader applies

The repair agent is a READ-ONLY analyzer: it reads the run-log (untrusted vendor
output) and returns a structured patch PROPOSAL as inline JSON. The LEADER applies
that proposal via the deterministic, zero-LLM `apply_patch.py`, then re-runs the
wrapper in `--repair-mode` to verify routing. Safe-by-construction: the
untrusted-input handler has no write authority; the write path has no LLM.

#### 5a. Extract the run-log path

```bash
RUN_LOG_PATH=$(grep -oE 'run-log: [^[:space:]]+' <stderr-text> \
                | tail -1 | awk '{print $2}')
[ -f "$RUN_LOG_PATH" ] || { echo "run-log path missing"; exit 1; }
```

The leader passes this PATH to the analyzer — it does NOT read the run-log content
itself (Hard rule 2). There is no output file: the analyzer replies inline.

#### 5b. Dispatch the repair analyzer

Use the `Agent` tool with `subagent_type` set exactly to `gemini-wrapper-repair`, **`run_in_background: true`** (Hard rule 7 — parallel, non-skippable; the inline JSON proposal arrives on completion, at which point you run Step 5c/5d). **Use the prompt body below VERBATIM** — substitute only the `<RUN_LOG_PATH>` placeholder. Hard rule 5: no meta-context, no test framing, no "note that..." lines.

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
{"outcome": "propose", "reason": "transient quota reset phrase an existing class catches", "proposal": {"classification": "cli-subscription-cap", "reason": "quota will reset = subscription cap, terminal", "pattern_list": "CLI_SUB_CAP_PATTERNS", "substring": "quota will reset"}}

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
         | apply_patch.py --cli gemini; then
      # applier exit 0 → patch landed; re-run in --repair-mode to verify routing.
      gemini_wrapper.py \
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

The applier re-validates the proposal independently (enum + pattern-name + literal bounds), so it is the security backstop even if the analyzer misbehaves: on exit 3 the extension file is left untouched and the leader surfaces it as an escalate. Cleanup is one `rm -f "$RUN_LOG_PATH"` (no output file exists). Wrapper's `_prune_run_logs()` (`glob("*.json")`) is the failsafe for orphans.

Branch summary:

| OUTCOME | Next action |
|---|---|
| propose → applier exit 0 | Re-run wrapper `--repair-mode` to verify routing; report the routing result. Framework now catches future identical errors. |
| propose → applier exit 3 | Proposal invalid (analyzer error) — surface REASON, treat as escalate. |
| escalate | Surface REASON. Manual diagnosis needed; no apply. |

## Outputs (what this skill returns)

- `ok`: wrapper stdout (Gemini's `response` field or pydantic-validated JSON).
- terminal: `{ class, reason, action_required }`.
- server-cap-exhausted: "transient overload, leader-policy retry or surface".
- repair-cycle: analyzer proposes → leader applies via `apply_patch.py` → `--repair-mode` re-run verifies routing; OR escalate (surface REASON, no apply).

## Path scope

- **Passes the PATH of** `_logs/gemini/runs/<id>.json` (run-log) to the analyzer. The leader does NOT read the run-log content (Hard rule 2) — the analyzer does, via `Read`.
- **Removes** the run-log post-dispatch (propose + escalate).
- **Invokes** `bin/gemini_wrapper.py` (dispatch + `--repair-mode` verify) and `bin/apply_patch.py` (deterministic proposal applier) via Bash.
- **Dispatches** sub-agent `gemini-wrapper-repair` (read-only analyzer).

The leader (not the analyzer) is the only writer to the classifier extension — via the deterministic `apply_patch.py`. Does NOT edit `bin/_common.py` source or read `_logs/gemini/audit.jsonl` (maintenance SKILL's territory).

## See also

- the plugin `README.md` — wrapper contract + run-log schema.
- `agents/gemini-wrapper-repair.md` — repair sub-agent body (per-attempt workflow + outcome judgment).
- `triad-codex-dispatch` — parallel SKILL for Codex.
