---
name: triad-gemini-dispatch
description: Use when the leader (Triad orchestrator) needs to dispatch a single-shot Gemini CLI call via the wrapper framework. Triggering signals — leader is about to run `python3 gemini_wrapper.py` raw; the user asks to call gemini once, have gemini handle a task, or run a one-shot gemini analysis; a higher-level orchestration SKILL needs the Gemini leg of a fan-out; classification-aware routing with self-improving repair-agent fallback is needed instead of raw subprocess. Symptoms of skipping this SKILL — unknown classification failures don't reach the repair sub-agent, the framework's self-improving classifier never grows. Do NOT use for Codex (`triad-codex-dispatch`), Antigravity (`triad-antigravity-dispatch`), or an isolated Claude worker (served in this plugin by the in-session `Agent` tool).
version: 0.14.1
# changelog:
#   0.14.1 (2026-10-11): Step 5 points at the procedure § 5a-5e (5e promotes a
#     verified phrase to the shared contract; DL-104).
#   0.14.0 (2026-10-11): Step 5 — one apply line verifies the proposal on the
#     failed run's stored record (the applier's `--verify-run-log <run-log path as
#     printed>`: exit 0 routes to the proposal, 4 applied but not routed, 3 refused);
#     the separate verify re-run line is gone with its wrapper flag (DL-104).
#   0.13.0 (2026-10-11): Step 5 — one procedure for the three dispatch skills
#     (`references/repair-loop.md`, § 5a-5e; the export ships a copy inside each
#     dispatch skill); the apply and verify lines stay in this body, the only place
#     the plugin path is filled in. The analyzer is one body rendered to
#     three names, with a bounded web research rule (`tools: Read, Grep, Glob,
#     WebSearch, WebFetch`, C76).
#   0.12.2 (2026-10-11): doc — a wrapper `timeout` (2) surfaces to the user and is never routed to the repair analyzer; the routed set is `unknown` / `extraction-error` (DL-104).
#   0.12.1 (2026-10-11): doc — Step 2 wording only ("— Step 3 reads it from the tool result").
#   0.12.0 (2026-10-11): Flow — the prompt and proposal files live under
#     `<project>/_runs/prompts/` (inside the hardened allowed root; the wrapper's
#     next-run sweep prunes them under the `dispatch-prompts` role, owner option 1);
#     Step 2 says Step 3 reads the summary from the tool result.
#   0.11.1 (2026-10-10): doc — Step 5a: the run-log path is passed on as the wrapper
#     printed it (the last `run-log:` line); no reading rule restates a former shell
#     check; a forged earlier `run-log:` line is a recorded limit.
#   0.11.0 (2026-10-10): doc — the leader reads the tool result (Step 3 summary token,
#     5a run-log path, 5c analyzer JSON keys) with no shell parse; files in
#     /tmp/triad-prompts (prompt and proposal; the OS temporary directory owns expiry).
#   0.10.0 (2026-10-10): doc — Step 1 and Step 5d: every wrapper / applier call is ONE simple
#     command with literal arguments; the prompt (Step 1) and the proposal (Step 5d,
#     `--proposal-file`) go through files the leader writes with the Write tool.
#     Measured (Claude Code 2.1.289): a command substitution / heredoc, an array
#     expansion and a quoted-variable pipe cannot be checked before they run, so the
#     plugin's grant does not match them; the plugin-root variable is substituted in
#     the SKILL.md body only, so references carry no runnable bin command.
#   0.9.0 (2026-10-10): doc — Step 5d: the apply step is a plain pipe into
#     `apply_patch.py` (no `if` / `case`: the permission grant matches a plain
#     command only); the leader reads its exit code (0 applied → `--repair-mode`
#     re-run in its own call; 3 refused, nothing written).
#   0.8.0 (2026-10-10): doc — the payload is one byte-safe UTF-8 encode (a lone
#     surrogate leaves as its `\udXXX` escape, exit and token unchanged); the
#     unemittable-payload demotion and its summary re-emission are removed.
#   0.7.0 (2026-10-10): doc — `--review-web` is no longer recorded as an audit
#     key (`review_web` is written nowhere; the recorded argv shows the launch).
#   0.6.5 (2026-10-09): doc — one Gemini CLI floor `>= 0.63.0` on EVERY route
#     (raw, write, `--web`, review; owner decision D-GEMINI-FLOOR-20261009),
#     `cli_version` recorded on every route; `--help` stays review-route only.
#   0.6.4 (2026-10-03): doc — `--review-web` (a review round's leg with web,
#     R-REVIEW-WEB / C32: the complete review web profile, no investigation
#     clause) beside `--web`; the summary tail names ` model=`.
#   0.6.3 (2026-09-21): Step 1 records the flags S10/S6 landed — `--web` (the
#     INVESTIGATION route: research policy + the shared web-evidence clause
#     LAST; refused with `--sandbox`, with `auto_edit`, and with a
#     verdict-schema `--pydantic`) and `--attempt <int>` (recorded on the
#     transport receipt, never interpreted) — plus the C16 review-route
#     preflight (version floor, `--help` capability probe, auth
#     class) as pre-spawn refusals. NOT RUN live: gemini is not in service at
#     the leaders' site, so these are implementation facts (t57/t58), not
#     measured runtime behaviour. Doc-only.
#   0.6.2 (2026-08-26): write-posture `--cwd` guard ENFORCED (owner ruling,
#     closing the codex/claude symmetry gap) — `--sandbox workspace-write` or
#     `--approval-mode auto_edit` without `--cwd` is refused EXIT_ARG_ERROR
#     before any vendor spawn (gemini was the one write-capable wrapper
#     without the guard). Defaults paragraph documents it; wrapper:
#     gemini_wrapper.py main() precondition; test_gemini_sandbox.py +3 cases
#     (existing workspace-write axis now passes --cwd, intent unchanged).
#   0.6.1 (2026-08-01): Step 1 heredoc terminator is now collision-resistant
#     (`TRIAD_GEMINI_PROMPT_EOF`, replacing the bare `PROMPT`) and
#     `--prompt-file <absolute-path>` is the STANDING path for content the
#     leader did not author AND for any body that QUOTES a dispatch template
#     or a SKILL body (quoted text carries the house terminator verbatim —
#     that is how this defect was first observed); it REPLACES the heredoc,
#     the two being argparse-mutually-exclusive. A bare `PROMPT`
#     line inside the body closed the heredoc early, and because the heredoc
#     sits inside `$( … )` the remainder of the prompt then parsed as SHELL in
#     the leader's own session — outside every worker-side sandbox. The prior
#     wording asked the leader to predict whether pasted content might contain
#     such a line, which is a gate that fails silently. Same fix as
#     `triad-antigravity-dispatch` 0.13.0 (terminator) + 0.13.1 (the widened
#     rule above), found by its skill-prompt-review round: the review packet
#     quoting this very template tripped it.
#   0.6.0: Step 5b SECURITY note — address the read-only repair analyzer by its
#     plugin-scoped identity (`triad-dispatch:gemini-wrapper-repair`, export-
#     injected) so a same-named project `agents/` agent cannot shadow the
#     read-only plugin agent and act on the untrusted run-log; plus a product-
#     agnostic read-only-verify-before-dispatch guard.
---

# triad-gemini-dispatch

Single-shot Gemini CLI dispatch with classification-based routing and a
self-improving repair loop. The leader's standard "call gemini once" path.

## Use when

- Leader has a discrete prompt and needs Gemini's answer (or a structured failure signal). Gemini is preferred for Android domain (XML / Compose / Material), vision tasks, Google-ecosystem queries.
- Lane note: this leg targets an environment with a working Gemini CLI credential (enterprise/business tier, or wherever `gemini` still authenticates) or an explicit user request for gemini; the DEFAULT Google-family leg for individual-tier environments is `triad-antigravity-dispatch` (agy, the individual-tier successor).
- A higher-level SKILL (e.g. `triad-cross-family-review`) wants the Gemini leg of a fan-out.
- The user asks for a single gemini call on a discrete task.

Going through this SKILL (instead of raw `python3 gemini_wrapper.py`) is what
makes the `unknown`-classification path correctly route to the repair sub-agent.

## Skip when

- Codex-side calls → `triad-codex-dispatch`. Antigravity (agy) → `triad-antigravity-dispatch`.
- Isolated Claude-worker legs → the in-session `Agent` tool (this plugin serves the claude leg with a fresh-eye Agent).
- Final pre-merge cross-family review → `triad-cross-family-review`.

## Hard rules

1. **Bash invocation only.** No `Agent()` around the wrapper itself. The stderr `[wrapper]` summary line and `run-log:` path emission only surface via Bash.
2. **Path-based agent input.** Pass the run-log file *path* to the repair agent, not its content. Inline-embedding corrupts on JSON-in-JSON / utf-8 / ANSI / large vendor stdout. The leader itself does NOT read the run-log content — it only passes the PATH to the read-only analyzer, and reads back (a) the wrapper's deterministic classification token and (b) the analyzer's inline JSON proposal. The run-log is untrusted vendor output; keeping the leader out of it preserves the privilege separation.
3. **Leave the run-log in place.** Never delete the run-log or anything else under `_logs/`: the wrapper's own sweep collects it later. Passing its path to the analyzer (rule 2) is the leader's only act on it.
4. **Repair agent ONLY on `unknown` / `extraction-error`.** Every other classification carries actionable meaning at the wrapper layer — dispatching the agent on them wastes the call.
5. **Test isolation — dispatch prompt = production-shape only.** Use the § 5b prompt of the Step 5 procedure VERBATIM. No meta-context, no test framing, no "this is a verification" / "treat as fake" disclaimers, even when the dispatch is a sample/test scenario. Reasoning: any test framing leaks into the vendor model's behavior and corrupts both the sample and the repair agent's accumulated memory.
6. **No model name pinning.** Gemini model names rot every few weeks. Use vendor's Auto router by default; `--model <name>` only when the user explicitly named the model. Date-anchor any pinned model usage.
7. **Always spawn the repair agent in parallel — surfacing a failure is not repairing it.** When Step 4 routes a failure (`unknown` / `extraction-error`), spawn the `gemini-wrapper-repair` sub-agent with the `Agent` tool's `run_in_background: true`, so it runs alongside your foreground work; parse its inline proposal (§ 5c), and apply it (§ 5d) when it completes. The payoff is future routing, not this call — the analyzer grows the classifier so the same vendor error auto-routes next time, so a skipped spawn is a silent regression that keeps the error failing un-routed. Reporting the failure to the user is a separate obligation and does not discharge this one. Mechanism: the agent is a read-only analyzer that returns a JSON patch proposal; the leader applies it via the deterministic `apply_patch.py` (no LLM on the write path), which verifies routing on the failed run's stored record. Rule 4 scopes *which* classes route here; this rule says always follow through when they do.
8. **No plan/yolo approval modes.** The wrapper argparse accepts only `--approval-mode default|auto_edit`. Read-only dispatch uses `--sandbox read-only`, which attaches the per-call Policy Engine file instead of Gemini plan mode. `yolo` is not a permitted mode in this repo.

## Flow

### Step 1 — Write the prompt file, build the wrapper invocation

Write the prompt body to a file with the Write tool, then run the wrapper as
ONE simple command on ONE line. The file is new per dispatch:
`<project>/_runs/prompts/<utc-timestamp>-gemini.md`, where `<project>` is the
directory the leader runs in — the hardened install's allowed root, so the
wrapper accepts the path (create the folder with the Write tool as needed). The
wrapper's next-run sweep prunes the folder past the `dispatch-prompts` role's
floor; add `_runs/` to the project's `.gitignore` if it is not
already ignored. The file keeps Korean / emoji /
`$variables` / backticks / quotes intact with no shell quoting at all.

The command line carries LITERAL values only — no `$(…)`, heredoc, variable,
pipe, array or `\` continuation: the plugin's permission grant matches one
simple command, and a command substitution, a variable or an array cannot be
checked before it runs, so such a call prompts on every dispatch. Fill in the
bracketed options you need with literal values and drop the rest:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/gemini_wrapper.py --prompt-file <project>/_runs/prompts/<utc-timestamp>-gemini.md [--cwd /absolute/path] [--sandbox <read-only or workspace-write>] [--approval-mode <default or auto_edit>] [--web or --review-web] [--model <pinned-model-name>] [--skip-trust] [--attempt <int>] [--timeout <seconds>] [--pydantic module:Class]
```

**`--web` = the INVESTIGATION route (spec C29 / R-INVEST), never a review.**
It attaches the wrapper-adjacent research profile
`policies/gemini-research.toml` (read tools + `web_fetch` +
`google_web_search`; write / shell / mcp denied) and appends the shared
web-evidence clause LAST — a search result is a POINTER, a cited web fact
comes from a `web_fetch` of the page with that page's own date or version,
and an unfetched or placeholder URL is not evidence. It is REFUSED with
`--sandbox` (a review's web is `--review-web` below, never the research
profile; a write posture contradicts the research profile's own denies) and
with `--approval-mode auto_edit`. Each refusal is an arg error before any
spawn.

**`--review-web` = a REVIEW leg with web (spec C32 / R-REVIEW-WEB).** The
review leg of a round that binds `review_web_authorized` true
(`triad-cross-family-review` prints it). With `--sandbox read-only` it
attaches the complete review web profile `policies/gemini-readonly-web.toml`
INSTEAD of `gemini-readonly.toml` (never an overlay: only `google_web_search`
and `web_fetch` move to allow) and appends no clause. It needs
`--sandbox read-only` and is refused with `--web`. Without it the read-only
review profile denies both web tools.

**`--attempt <int>`** (>= 1, default 1) is the dispatch attempt number,
RECORDED on the transport receipt and the summary tail and never interpreted.
Below 1 is refused pre-spawn.

**Auth-class gate (R-AUTH, spec C37) — on EVERY posture, before any vendor
process:** `security.auth.selectedType` from the CLI's own settings chain —
`gemini-api-key` / `vertex-ai` / `compute-default-credentials` are REFUSED as
`oauth-env` (65); the remedy is the owner's browser re-login (run `gemini`,
choose Login with Google) — never a flag change, never a retry. `oauth-personal`
is the approved subscription login; an unexposed or unknown class is reported
on stderr and allowed to run.

**Preflight (spec C16) — provider-free checks run BEFORE any vendor call.**
On EVERY route (raw, write, `--web`, review) a VERSION FLOOR: `gemini >=
0.63.0`, one route floor independent of the requested model (owner decision
D-GEMINI-FLOOR-20261009); a pre-release of 0.63.0 is below it, build metadata
is ignored, no model list or catalog probe is consulted, and the observed
`cli_version` is recorded on every route. When `--sandbox read-only` is in
effect (including the hardened-install default), after the effective posture
is computed, a CAPABILITY probe follows (`--help` must advertise `--policy`,
`--approval-mode`, `--output-format`). Each is a `config-conflict` (65)
refusal with 0 vendor calls that records the version it observed; the remedy
for the floor is updating the gemini CLI.
**NOT RUN live** on this host: these are
deterministic implementation facts (`tests/unit/wrappers/t57`), not measured
runtime behaviour.

Defaults: no `--sandbox` policy and `--approval-mode default` (read auto, write/shell prompt). `--sandbox read-only` attaches the wrapper-adjacent `policies/gemini-readonly.toml` for that call only. `auto_edit` = write/shell auto (only on explicit leader request) and conflicts with `--sandbox read-only`. `--approval-mode plan/yolo` is rejected by argparse. **Write postures require `--cwd` (owner ruling 2026-08-26, enforced)**: `--sandbox workspace-write` or `--approval-mode auto_edit` without `--cwd` is refused `EXIT_ARG_ERROR` before any vendor spawn — a write-enabled dispatch's blast radius must be an isolated directory, never the wrapper's inherited cwd (the same guard claude and codex workspace-write carry). Build `--cwd` from the real working directory read at dispatch time (`pwd`), never an assumed session cwd (leader CLAUDE.md Pitfall #5).

> **Why `plan` mode is not exposed: it is unreliable for heavy multi-file agentic reads.** On a heavy task (e.g. "read 16 source files in full and review"), the Pro plan-loop emits an empty/malformed turn (vendor `Invalid stream: The model returned an empty response or malformed tool call`), surfacing as `extraction-error` (rc=1) in ~10-25s. So this wrapper no longer exposes `plan`; use `--sandbox read-only` for read-only reviews and `--approval-mode default` for normal reads.

`--skip-trust` is needed when the cwd is not yet trusted in `~/.gemini/trustedFolders.json` — without it the CLI hangs on the trust dialog.

### Step 2 — Run via Bash; capture rc, stdout, stderr

Wrapper stderr contains:
- Timestamped wrapper log lines
- Mirrored vendor stderr (small baseline: `Warning:` + `Ripgrep` lines; on error, may include trailing JSON `{error: ...}`)
- 1-line summary: `[<timestamp>] [wrapper] gemini <classification> exit=<int> vendor=<int> elapsed=<s>` followed by the recorded-facts tail ` attempt=<n>`, ` prompt_file=<abs>` when a `--prompt-file` was given and ` model=<slug>` when `--model` was requested (absent = the CLI's config default; this wrapper has no reasoning flag) (every wrapper log line, this one included, carries the leading timestamp bracket — Step 3 reads it from the tool result)
- On failure: `run-log: <absolute-path>`

### Step 3 — Read the classification

Read the classification from the Bash tool result — no shell parse (a
command substitution or a pipe cannot be checked before it runs, so a parse
command would prompt). In the stderr, read the LAST line that STARTS with
`[<timestamp>] [wrapper] gemini ` (the timestamp bracket, then `[wrapper] gemini `);
the classification is the token right after `[wrapper] gemini ` (e.g. `ok`,
`unknown`, `extraction-error`). Use the LAST such line — when an
`extraction-error` happens, `_run_once` emits an early `ok` summary that a
second emission corrects. On a failure, the run-log path is the value after
`run-log: ` on its line (the last such line).

Only a line that STARTS with that prefix counts (gate-1 r9 row r9-3): the
summary tail carries a free-text field (`prompt_file=<abs>`), and a reading that
took the last `[wrapper] gemini <token> ` ANYWHERE in the line once let a prompt
file under a directory named `…[wrapper] gemini ok …` override the emitted token
(an `extraction-error` run read as `ok`, and the MANDATORY repair routing never
fired). The engine also percent-escapes every free-text field of the summary
(`_common._summary_field` — SPACE and `[` / `]` are outside the safe set, so the
sequence cannot be built inside `prompt_file=`; an ordinary POSIX path is
emitted byte-identically and the audit row keeps the raw value) — the two
defences are independent. The wrapper's other stderr lines (`run-log: <abs>`,
`exec cwd=… argv=…`) never START with the `[wrapper] gemini <token> ` prefix.

Token set:
`ok | server-capacity | cli-subscription-cap | token-limit | oauth-env | schema-fail | timeout | extraction-error | unknown`

Or branch on wrapper exit code: `0` / `1` / `2` (timeout) / `3` (arg) / `4` (binary missing) / `64` (server-cap exhausted) / `65` (terminal) / `66` (schema fail).

### Step 4 — Branch on classification

| classification (rc) | Leader action |
|---|---|
| `ok` (0) | Return wrapper stdout (Gemini's `response` field text or pydantic-validated JSON). |
| `oauth-env` (65) | STOP. The login is missing or expired (gemini's own exit 41 included), or the CLI used an API-key / Vertex / ADC class. Do not retry, do not try another route or credential, and never read or change the credential store; tell the owner to re-log in through the CLI's own browser flow (run `gemini`, choose Login with Google). A same-basis re-dispatch runs only after the owner reports the re-login. **NOT** repair-agent territory. |
| terminal (65) — cli-subscription-cap / token-limit | Surface to user with cause (Code Assist license daily-quota or API-key RPM-tier reset / prompt size — see the Lane note in § Use when). **NOT** repair-agent territory. |
| `server-capacity` exhausted (64) | Wait + retry, or surface. Wrapper retried per backoff (plus Gemini's own internal retries). |
| `unknown` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 7). Spawn it even when you are busy or also surfacing the failure — never skip.** |
| `extraction-error` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 7).** Vendor returned rc=0 but extractor found no answer (empty `response` field, unparseable JSON, vendor refusal text). Repair agent inspects whether the cause is a vendor refusal pattern worth a classifier patch, or a true extraction bug → ESCALATE. |
| `timeout` (2) | Surface to the user (the wrapper already fails fast). NOT repair-agent territory. |
| arg (3) / binary missing (4) / schema fail (66) | Surface to user with cause. |

### Step 5 — Repair branch: read-only analyzer proposes, leader applies (`unknown` / `extraction-error` only)

Use the `Agent` tool with `subagent_type` set exactly to `triad-dispatch:gemini-wrapper-repair`, **`run_in_background: true`** (Hard rule 7). `CLI=gemini`. Follow [`references/repair-loop.md`](references/repair-loop.md) § 5a-5e with `<CLI>` = `gemini` and `<ANALYZER>` = the agent that sentence names: the run-log path, the analyzer prompt and its read-only check, the reply, and the branch. Its one command runs from here — ONE simple command, literal arguments:

- the apply line (§ 5d, `propose`):

  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/bin/apply_patch.py --cli gemini --proposal-file <project>/_runs/prompts/<utc-timestamp>-gemini-proposal.json --verify-run-log <the run-log path exactly as printed>
  ```

## Outputs (what this skill returns)

- `ok`: wrapper stdout (Gemini's `response` field or pydantic-validated JSON).
- terminal: `{ class, reason, action_required }`.
- server-cap-exhausted: "transient overload, leader-policy retry or surface".
- repair-cycle: analyzer proposes → leader applies via the applier with `--verify-run-log`, which re-classifies the failed run's stored record (exit 0 routes to the proposal; 4 applied but not routed → escalate); OR escalate (surface REASON, no apply).

## Path scope

- **Passes the PATH of** `_logs/gemini/runs/<id>.json` (run-log) to the analyzer. The leader does NOT read the run-log content (Hard rule 2) — the analyzer does, via `Read`.
- **Leaves** the run-log in place; the wrapper's own sweep collects it.
- **Invokes** `bin/gemini_wrapper.py` (dispatch) and `bin/apply_patch.py` (deterministic proposal applier + stored-record verifier) via Bash.
- **Dispatches** sub-agent `gemini-wrapper-repair` (read-only analyzer).

The leader (not the analyzer) is the only writer to the classifier extension — via the deterministic `apply_patch.py`. Does NOT edit `bin/_common.py` source or read `_logs/gemini/audit.jsonl`.

## See also

- the plugin `README.md` — wrapper contract + run-log schema.
- `agents/gemini-wrapper-repair.md` — the repair analyzer (one body for the three CLIs, rendered from one template; never hand-edited).
- `triad-codex-dispatch` — parallel SKILL for Codex.
