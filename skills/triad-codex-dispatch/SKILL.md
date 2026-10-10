---
name: triad-codex-dispatch
description: Use when the leader (Triad orchestrator) needs to dispatch a single-shot Codex CLI call via the wrapper framework. Triggering signals — leader is about to run `python3 codex_wrapper.py` raw; the user asks to call codex once, have codex handle a task, or run a one-shot codex analysis; a higher-level orchestration SKILL needs the Codex leg of a fan-out; classification-aware routing with self-improving repair-agent fallback is needed instead of raw subprocess. Symptoms of skipping this SKILL — unknown classification failures don't reach the repair sub-agent, the framework's self-improving classifier never grows. Do NOT use for Gemini (`triad-gemini-dispatch`), Antigravity (`triad-antigravity-dispatch`), or an isolated Claude worker (served in this plugin by the in-session `Agent` tool).
version: 0.17.1
# changelog:
#   0.17.1 (2026-10-11): Step 5 points at the procedure § 5a-5e (5e promotes a
#     verified phrase to the shared contract; DL-104).
#   0.17.0 (2026-10-11): Step 5 — one apply line verifies the proposal on the
#     failed run's stored record (the applier's `--verify-run-log <run-log path as
#     printed>`: exit 0 routes to the proposal, 4 applied but not routed, 3 refused);
#     the separate verify re-run line is gone with its wrapper flag (DL-104).
#   0.16.0 (2026-10-11): Step 5 — one procedure for the three dispatch skills
#     (`references/repair-loop.md`, § 5a-5e; the export ships a copy inside each
#     dispatch skill); the apply and verify lines stay in this body, the only place
#     the plugin path is filled in. The analyzer is one body rendered to
#     three names, with a bounded web research rule (`tools: Read, Grep, Glob,
#     WebSearch, WebFetch`, C76).
#   0.15.2 (2026-10-11): doc — a wrapper `timeout` (2) surfaces to the user and is never routed to the repair analyzer; the routed set is `unknown` / `extraction-error` (DL-104).
#   0.15.1 (2026-10-11): doc — Step 2 wording only ("— Step 3 reads it from the tool result").
#   0.15.0 (2026-10-11): Flow — the prompt and proposal files live under
#     `<project>/_runs/prompts/` (inside the hardened allowed root; the wrapper's
#     next-run sweep prunes them under the `dispatch-prompts` role, owner option 1);
#     Step 2 says Step 3 reads the summary from the tool result.
#   0.14.1 (2026-10-10): doc — Step 5a: the run-log path is passed on as the wrapper
#     printed it (the last `run-log:` line); no reading rule restates a former shell
#     check; a forged earlier `run-log:` line is a recorded limit.
#   0.14.0 (2026-10-10): doc — the leader reads the tool result (Step 3 summary token,
#     5a run-log path, 5c analyzer JSON keys) with no shell parse; files in
#     /tmp/triad-prompts (prompt and proposal; the OS temporary directory owns expiry).
#   0.13.0 (2026-10-10): doc — Step 1 and Step 5d: every wrapper / applier call is ONE simple
#     command with literal arguments; the prompt (Step 1) and the proposal (Step 5d,
#     `--proposal-file`) go through files the leader writes with the Write tool.
#     Measured (Claude Code 2.1.289): a command substitution / heredoc, an array
#     expansion and a quoted-variable pipe cannot be checked before they run, so the
#     plugin's grant does not match them; the plugin-root variable is substituted in
#     the SKILL.md body only, so references carry no runnable bin command.
#   0.12.0 (2026-10-10): doc — Step 5d: the apply step is a plain pipe into
#     `apply_patch.py` (no `if` / `case`: the permission grant matches a plain
#     command only); the leader reads its exit code (0 applied → `--repair-mode`
#     re-run in its own call; 3 refused, nothing written).
#   0.11.0 (2026-10-10): doc — the payload is one byte-safe UTF-8 encode (a lone
#     surrogate leaves as its `\udXXX` escape, exit and token unchanged); the
#     unemittable-payload demotion and its summary re-emission are removed.
#   0.10.0 (2026-10-05): the `--task` mode is removed (the fan-out worker
#     layer and `--task code`; exits 68 / 69 and the tokens
#     `fanout-spawn-error` / `fanout-partial` / `task-blocked` leave codex).
#     A write call is a plain `--sandbox workspace-write` dispatch (it requires
#     `--cwd`). The no-op `--format` option is removed.
#   0.9.5 (2026-09-21): Step 1 gains two engine flags (host A v2 slices
#     S6/S7/S11). `--attempt <int>` (>= 1, default 1; below 1 = exit 3
#     pre-spawn) is RECORDED on the transport receipt and the summary tail
#     and never interpreted — no retry reads it. `--output-schema-file <abs>`
#     passes a CALLER-OWNED JSON schema file straight to codex
#     `--output-schema`: transport only (the wrapper validates nothing and
#     retries nothing), mutually exclusive with `--pydantic`, and it is the
#     flag the cross-family-review v2 path uses for its per-attempt producer
#     schema projection. Also recorded: C28 — a RELATIVE `--prompt-file` /
#     `--cwd` is no longer refused, it resolves against the wrapper's
#     process-entry cwd and the resolved absolute path is recorded; ABSOLUTE
#     stays the form this SKILL prints. Doc-only.
#   0.9.4 (2026-09-18): `input-delivery-failed` (65) — the shared engine's
#     stdin prompt transport (codex `prompt_via_stdin`) now fails CLOSED: a
#     codex child that exited 0 while the wrapper's stdin writer failed
#     (write / flush / pre-spawn UTF-8 encode) or had not finished within the
#     bounded join gets exit 65 with the answer BLANKED, never `ok`; an
#     unencodable prompt is refused pre-spawn (exit 3); `stdin_delivery`
#     rides the audit record and the failure run-log. Wrapper-SET token (the
#     agy `vendor-error` precedent): not a classify() result, not a repair
#     proposal. Step 4 gains its row. Origin: codex maintainer handoff
#     2026-09-18 (synthetic probe: 1-byte read + early close + success-shaped
#     answer returned rc 0). Tests: t48 (seam) + f12 (end to end).
#   0.9.3 (2026-08-26): doc-only — § Leader procedure step 3's wrapper
#     invocation now carries the absolute wrapper path (was relative,
#     resolvable from exactly one directory; contradicted the Step-1
#     template's absolute shape). Session-cwd hazard rationale: leader
#     CLAUDE.md Pitfall #5.
#   0.9.2 (2026-08-08): `--model <catalog-slug>` dispatch-time model pin
#     (free-form passthrough to `-c model="<slug>"`; config-alive when
#     omitted; no slug ever hardcoded). Origin: config-alive default moved
#     review legs off the recorded review policy silently.
#   0.9.1 (2026-08-01): Step 1 heredoc terminator is now collision-resistant
#     (`TRIAD_CODEX_PROMPT_EOF`, replacing the bare `PROMPT`) and
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
#   0.9.0: Step 5b SECURITY note — address the read-only repair analyzer by its
#     plugin-scoped identity (`triad-dispatch:codex-wrapper-repair`, export-
#     injected) so a same-named project `agents/` agent cannot shadow the
#     read-only plugin agent and act on the untrusted run-log; plus a product-
#     agnostic read-only-verify-before-dispatch guard.
---

# triad-codex-dispatch

Single-shot Codex CLI dispatch with classification-based routing and a
self-improving repair loop. The leader's standard "call codex once" path.

## Use when

- Leader has a discrete prompt and needs Codex's answer (or a structured failure signal).
- A higher-level SKILL (e.g. `triad-cross-family-review`) wants the Codex leg of a fan-out.
- The user asks for a single codex call on a discrete task.

Going through this SKILL (instead of raw `python3 codex_wrapper.py`) is what
makes the `unknown`-classification path correctly route to the repair sub-agent.

## Skip when

- Gemini-side calls → `triad-gemini-dispatch`. Antigravity (agy) → `triad-antigravity-dispatch`.
- Isolated Claude-worker legs → the in-session `Agent` tool (this plugin serves the claude leg with a fresh-eye Agent).
- Final pre-merge cross-family review → `triad-cross-family-review`.

## Hard rules

1. **Bash invocation only.** No `Agent()` around the wrapper itself. The stderr `[wrapper]` summary line and `run-log:` path emission only surface via Bash.
2. **Path-based agent input.** Pass the run-log file *path* to the repair agent, not its content. Inline-embedding corrupts on JSON-in-JSON / utf-8 / ANSI / large vendor stdout. The leader itself does NOT read the run-log content — it only passes the PATH to the read-only analyzer, and reads back (a) the wrapper's deterministic classification token and (b) the analyzer's inline JSON proposal. The run-log is untrusted vendor output; keeping the leader out of it preserves the privilege separation.
3. **Leave the run-log in place.** Never delete the run-log or anything else under `_logs/`: the wrapper's own sweep collects it later. Passing its path to the analyzer (rule 2) is the leader's only act on it.
4. **Repair agent ONLY on `unknown` / `extraction-error`.** Every other classification carries actionable meaning at the wrapper layer — dispatching the agent on them wastes the call.
5. **Test isolation — dispatch prompt = production-shape only.** Use the § 5b prompt of the Step 5 procedure VERBATIM. No meta-context, no test framing, no "this is a verification" / "treat as fake" disclaimers, even when the dispatch is a sample/test scenario. Reasoning: any test framing leaks into the vendor model's behavior and corrupts both the sample and the repair agent's accumulated memory.
6. **Always spawn the repair agent in parallel — surfacing a failure is not repairing it.** When Step 4 routes a failure (`unknown` / `extraction-error`), spawn the `codex-wrapper-repair` sub-agent with the `Agent` tool's `run_in_background: true`, so it runs alongside your foreground work; parse its inline proposal (§ 5c), and apply it (§ 5d) when it completes. The payoff is future routing, not this call — the analyzer grows the classifier so the same vendor error auto-routes next time, so a skipped spawn is a silent regression that keeps the error failing un-routed. Reporting the failure to the user is a separate obligation and does not discharge this one. Mechanism: the agent is a read-only analyzer that returns a JSON patch proposal; the leader applies it via the deterministic `apply_patch.py` (no LLM on the write path), which verifies routing on the failed run's stored record. Rule 4 scopes *which* classes route here; this rule says always follow through when they do.

## Flow

### Step 1 — Write the prompt file, build the wrapper invocation

Write the prompt body to a file with the Write tool, then run the wrapper as
ONE simple command on ONE line. The file is new per dispatch:
`<project>/_runs/prompts/<utc-timestamp>-codex.md`, where `<project>` is the
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
python3 ${CLAUDE_PLUGIN_ROOT}/bin/codex_wrapper.py --prompt-file <project>/_runs/prompts/<utc-timestamp>-codex.md [--cwd /absolute/path] [--sandbox <read-only or workspace-write>] [--reasoning <low, medium, high, xhigh or max>] [--model <catalog-slug>] [--search] [--timeout <seconds>] [--pydantic module:Class] [--output-schema-file /absolute/path/schema.json] [--attempt <int>] [--image /absolute/path.png ...]
```

**`--output-schema-file <path>`** hands a CALLER-OWNED JSON schema
file straight to codex `--output-schema`. It is TRANSPORT ONLY: the wrapper
validates nothing, repairs nothing and retries nothing — the caller admits
the answer with its own validator (this is the path
`triad-cross-family-review`'s v2 rounds use for their per-attempt producer
schema projection). Mutually exclusive with `--pydantic`, which owns the
massage-and-validate path instead. The path must name an existing file (a
relative path is rebased on the wrapper's process-entry cwd, as
`--prompt-file`); the check runs BEFORE any vendor work, so a bad path costs
no dispatch.

**`--attempt <int>`** (>= 1, default 1) is the dispatch attempt number. It is
RECORDED on the transport receipt in the audit row / run-log and on the
summary tail (` attempt=<n>`), and is never interpreted — no wrapper control
flow reads it and it drives no retry. Below 1 is refused with exit 3 before
any spawn.

**Relative paths (C28, 2026-09-19).** A relative `--prompt-file` / `--cwd` is
no longer refused: the wrapper resolves it against its OWN process-entry
working directory (never the child `--cwd`), runs every pre-existing
validation unchanged, and RECORDS the resolved absolute path on the summary
line (`prompt_file=<abs>`) and in the audit row (`prompt_file_resolved`).
ABSOLUTE remains the form this SKILL prints — the record makes a
mis-resolution legible afterwards, it does not prevent one.

Defaults: `--sandbox read-only`. Triad policy disallows `danger-full-access` — argparse rejects it at parse time.

**Write calls.** `--sandbox workspace-write` requires `--cwd` (without it the
wrapper refuses with exit 3) and lets codex edit files inside it. Point `--cwd`
at an isolated git worktree, never the live working tree. Create it under
`_runs/worktrees/<name>` (the declared `code-worktrees` root, kept git-ignored).
codex never commits; verify its changes yourself, then commit. When done, commit
everything in the tree to its branch, then remove it only with
`python3 ${CLAUDE_PLUGIN_ROOT}/bin/cleanup.py remove code-worktrees _runs/worktrees/<name>`
from the repository top level. Network and MCP stay reachable under this sandbox.

**`--search`** enables codex's live web search (codex's top-level `--search`, inserted
before `exec`; default OFF). Opt in for **research / consult / review** dispatches where
current web grounding matters; leave OFF for routine calls (slower). It goes through the codex CLI login like every dispatch — never an API key (R-NOCOST).
When OFF, the wrapper pins `web_search="disabled"` in config, so no search tool is
exposed to the run — the no-search contract is enforced, not just advertised.

**Reasoning-effort guideline.** `--reasoning` overrides `model_reasoning_effort` for this dispatch; omit it to inherit the config-alive value (the user's `~/.codex/config.toml`). Set it by intent, not by default: `high` for **review / planning / non-trivial analysis or coding** (bug-hunting, design/spec review, multi-file reasoning); `xhigh` for **deep architecture review or long refactors**; `max` (the top pure-depth tier the wrapper exposes) only for **the hardest multi-step problems**; `low` for trivial/mechanical work where speed matters. Leave it unset for routine dispatches — config-alive already supplies a sensible default, and over-setting `xhigh`/`max` burns latency/quota. **`ultra` is NOT exposed and MUST NOT be used** for a codex worker dispatch: it is `max` reasoning **plus automatic subagent delegation**, which makes a single-shot dispatch runaway and over-long (observed), and not every model variant supports it (an auto-routed dispatch could hit an ultra-less model). The wrapper's enum stops at `max`; do not add `-c model_reasoning_effort="ultra"` by hand. (`minimal` is likewise not exposed — no leader/user use case.)

**`--model` (dispatch-time model pin, 2026-08-08).** Omit for routine dispatches — the config-alive model (`~/.codex/config.toml`) applies. Pass a CATALOG slug (from `codex debug models`, Tier-2 lookup at dispatch time) when a house policy pins a review/worker tier — e.g. a review-policy leg that must run a specific variant regardless of the owner's interactive config default. The wrapper carries NO slug anywhere (free-form passthrough, `-c model="<slug>"`); slugs rot, so never copy one from memory or docs — read the catalog first. Origin: a config-alive default silently moved review legs off the recorded review policy; dispatch-time pinning restores "model/effort are set at dispatch time" without touching the owner's config.

The prompt is delivered to codex via **stdin** internally (the caller passes `--prompt-file`). `--pydantic` drives codex's native `--output-schema` (the class is massaged to codex-strict shape); a submit-time refusal surfaces as `schema-rejected` (rc 67). `--image` (repeatable) passes vision inputs as codex `-i` (bad path → `EXIT_ARG_ERROR` pre-spawn).

### Step 2 — Run via Bash; capture rc, stdout, stderr

Wrapper stderr contains:
- Timestamped wrapper log lines
- Mirrored vendor stderr (Codex `--json` keeps this small)
- 1-line summary: `[<timestamp>] [wrapper] codex <classification> exit=<int> vendor=<int> elapsed=<s>` followed by the recorded-facts tail ` attempt=<n>`, ` prompt_file=<abs>` when a `--prompt-file` was given, ` model=<slug>` when `--model` was requested and ` reasoning=<tier>` when `--reasoning` was requested (absent = the CLI's config default) (every wrapper log line, this one included, carries the leading timestamp bracket — Step 3 reads it from the tool result)
- On failure: `run-log: <absolute-path>`

### Step 3 — Read the classification

Read the classification from the Bash tool result — no shell parse (a
command substitution or a pipe cannot be checked before it runs, so a parse
command would prompt). In the stderr, read the LAST line that STARTS with
`[<timestamp>] [wrapper] codex ` (the timestamp bracket, then `[wrapper] codex `);
the classification is the token right after `[wrapper] codex ` (e.g. `ok`,
`unknown`, `extraction-error`). Use the LAST such line — when an
`extraction-error` happens, `_run_once` emits an early `ok` summary that a
second emission corrects. On a failure, the run-log path is the value after
`run-log: ` on its line (the last such line).

Only a line that STARTS with that prefix counts (gate-1 r9 row r9-3): the
summary tail carries a free-text field (`prompt_file=<abs>`), and a reading that
took the last `[wrapper] codex <token> ` ANYWHERE in the line once let a prompt
file under a directory named `…[wrapper] codex ok …` override the emitted token
(an `extraction-error` run read as `ok`, and the MANDATORY repair routing never
fired). The engine also percent-escapes every free-text field of the summary
(`_common._summary_field` — SPACE and `[` / `]` are outside the safe set, so the
sequence cannot be built inside `prompt_file=`; an ordinary POSIX path is
emitted byte-identically and the audit row keeps the raw value) — the two
defences are independent. The wrapper's other stderr lines (`run-log: <abs>`,
`exec cwd=… argv=…`) never START with the `[wrapper] codex <token> ` prefix.

Token set:
`ok | server-capacity | cli-subscription-cap | token-limit | oauth-env | schema-fail | schema-rejected | config-conflict | input-delivery-failed | timeout | extraction-error | unknown`

Or branch on wrapper exit code: `0` / `1` / `2` (timeout) / `3` (arg; also an unencodable stdin prompt — `input-delivery-failed` refused pre-spawn) / `4` (binary missing) / `64` (server-cap exhausted) / `65` (terminal — SHARED by the four terminal causes and `input-delivery-failed`, so at 65 read the TOKEN from the summary line before picking a Step 4 row) / `66` (schema fail) / `67` (schema-rejected — `--output-schema` refused at submit).

### Step 4 — Branch on classification

| classification (rc) | Leader action |
|---|---|
| `ok` (0) | Return wrapper stdout. With `--pydantic`, stdout is the validated JSON object. |
| `oauth-env` (65) | STOP. The login is missing or expired, or the CLI presented an API-key-shaped credential. Do not retry, do not try another route or credential, and never read or change the credential store; tell the owner to re-log in through the CLI's own browser flow (`codex login`). A same-basis re-dispatch runs only after the owner reports the re-login. **NOT** repair-agent territory. |
| terminal (65) — cli-subscription-cap / token-limit / config-conflict | Surface to user with cause (quota / prompt size / inherited `~/.codex/config.toml` parse error). **NOT** repair-agent territory (already matched — repair routing is only `unknown` / `extraction-error`). |
| `input-delivery-failed` (65; 3 when refused pre-spawn) | The wrapper's OWN stdin transport did not confirm delivery of the prompt (write/flush failed — typically the child closed its stdin early —, the writer had not finished within the bounded join, or the prompt was not UTF-8-encodable and nothing was sent) while codex exited 0 and answered like a success. The answer is BLANKED (stdout empty) and the raw vendor rc is kept. The cause is on the wrapper's OWN stderr, the deterministic line right before the summary — `exit=0 … but stdin delivery failed:<ExceptionClass>; failing closed` (or `unconfirmed`) — which the leader may read; the audit record and the failure run-log ALSO carry it as `stdin_delivery`, for the analyzer and for forensics only (Hard rule 2: the leader does not read the run-log). Surface to user with that cause; a re-dispatch is reasonable. Leave the failure run-log alone — no Step 5 arm ran, and the NEXT dispatch's own IPC cleanup prunes it (the wrapper clears prior residue on start). **NOT** repair-agent territory (a wrapper transport defect, not a classifier gap — the token is never a repair proposal). A genuine vendor error (rc != 0) after an early close keeps ITS classification; the delivery failure is an annotation there. |
| `server-capacity` exhausted (64) | Wait + retry, or surface. Wrapper already retried per backoff. |
| `unknown` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 6). Spawn it even when you are busy or also surfacing the failure — never skip.** |
| `extraction-error` (1) | **Step 5 — repair agent dispatch (MANDATORY + parallel; Hard rule 6).** Vendor returned rc=0 but extractor found no answer (empty JSON envelope, missing last-message file). Repair agent inspects whether the cause is a vendor refusal pattern worth a classifier patch, or a true extraction bug → ESCALATE. |
| `timeout` (2) | Surface to the user (the wrapper already fails fast). NOT repair-agent territory. |
| `schema-rejected` (67) | Surface to user: the pydantic class / massaged schema is invalid for codex strict mode, or codex strict-rule drift. Fix the class / massage and re-dispatch. **NOT** repair-agent territory (deterministic, not transient). Distinct from `schema fail (66)` = post-hoc pydantic validation failing after a well-formed answer. |
| arg (3) / binary missing (4) / schema fail (66) | Surface to user with cause. |

### Step 5 — Repair branch: read-only analyzer proposes, leader applies (`unknown` / `extraction-error` only)

Use the `Agent` tool with `subagent_type` set exactly to `triad-dispatch:codex-wrapper-repair`, **`run_in_background: true`** (Hard rule 6). `CLI=codex`. Follow [`references/repair-loop.md`](references/repair-loop.md) § 5a-5e with `<CLI>` = `codex` and `<ANALYZER>` = the agent that sentence names: the run-log path, the analyzer prompt and its read-only check, the reply, and the branch. Its one command runs from here — ONE simple command, literal arguments:

- the apply line (§ 5d, `propose`):

  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/bin/apply_patch.py --cli codex --proposal-file <project>/_runs/prompts/<utc-timestamp>-codex-proposal.json --verify-run-log <the run-log path exactly as printed>
  ```

## Outputs (what this skill returns)

- `ok`: wrapper stdout (raw answer or pydantic-validated JSON).
- terminal: `{ class, reason, action_required }`.
- server-cap-exhausted: "transient overload, leader-policy retry or surface".
- repair-cycle: analyzer proposes → leader applies via the applier with `--verify-run-log`, which re-classifies the failed run's stored record (exit 0 routes to the proposal; 4 applied but not routed → escalate); OR escalate (surface REASON, no apply).

## Path scope

- **Passes the PATH of** `_logs/codex/runs/<id>.json` (run-log) to the analyzer. The leader does NOT read the run-log content (Hard rule 2) — the analyzer does, via `Read`.
- **Leaves** the run-log in place; the wrapper's own sweep collects it.
- **Invokes** `bin/codex_wrapper.py` (dispatch) and `bin/apply_patch.py` (deterministic proposal applier + stored-record verifier) via Bash.
- **Dispatches** sub-agent `codex-wrapper-repair` (read-only analyzer).

The leader (not the analyzer) is the only writer to the classifier extension — via the deterministic `apply_patch.py`. Does NOT edit `bin/_common.py` source or read `_logs/codex/audit.jsonl`.

## Direct `codex exec` knowledge

Some invocations are not expressible through the wrapper (it pins `--ephemeral`
and exposes no `--add-dir` / arbitrary `-c` passthrough) — a `/goal`-driving or
skill-invoking dispatch is a direct `codex exec` the leader builds itself. The
curated facts (extra writable roots, execpolicy prefix rules, skill discovery
scopes and explicit `$<skill-name>` invocation, and the wrapper-boundary
rationale) live in [references/codex-exec.md](references/codex-exec.md) — read
it before building a direct invocation.

## See also

- the plugin `README.md` — wrapper contract + run-log schema.
- `agents/codex-wrapper-repair.md` — the repair analyzer (one body for the three CLIs, rendered from one template; never hand-edited).
- `triad-gemini-dispatch` — parallel SKILL for Gemini.
