---
name: triad-antigravity-dispatch
description: Use when the leader (Triad orchestrator) needs to dispatch a single-shot Antigravity CLI (`agy`) call via the wrapper framework. Triggering signals — leader is about to run `python3 antigravity_wrapper.py` raw; the user asks to call agy (antigravity) once, have agy handle a task, or run a one-shot agy analysis; a higher-level orchestration SKILL needs the agy leg of a fan-out (the Google-family leg; `triad-gemini-dispatch` exists for legacy compatibility with the older gemini CLI); the task needs web grounding — vendor / API / CLI documentation research, "what does the latest X say", recent-issue triage — since agy is the toolkit's search/research leg; classification-aware routing with self-improving repair-agent fallback is needed instead of raw subprocess. Symptoms of skipping this SKILL — unknown classification failures don't reach the repair sub-agent, the framework's self-improving classifier never grows. Do NOT use for Codex (use `triad-codex-dispatch`), Gemini (use `triad-gemini-dispatch`).
version: 0.24.4
# changelog: docs/reviews/2026-10-08-dispatch-skill-history.md (every entry; the newest section is last)
---

# triad-antigravity-dispatch

Single-shot Antigravity CLI (`agy`) dispatch with classification-based routing
and a self-improving repair loop. The leader's standard "call agy once" path.
agy is the Google-family leg (the gemini CLI's successor) — Android /
Google-ecosystem domain strength. Compatibility with the older gemini CLI
exists through `triad-gemini-dispatch` (legacy compatibility).

## Use when

- Leader has a discrete prompt and needs agy's answer (or a structured failure signal). agy is the default Google leg; gemini is the legacy compatibility route.
- A higher-level SKILL (e.g. `triad-cross-family-review`) wants the agy leg of a fan-out.
- **The work needs web grounding** — vendor / API / CLI doc research, "what does
  the latest X say", recent-issue triage: agy is the search/research leg, and the
  primary leg when the task is itself fact-finding (§ Routing).
- The user asks for a single agy call on a discrete task.

Going through this SKILL (instead of raw `python3 antigravity_wrapper.py`) is
what makes the `unknown`-classification path correctly route to the repair
sub-agent.

## Skip when

- Final cross-family review → `triad-cross-family-review`.
- Codex-side calls → `triad-codex-dispatch`. Gemini-side → `triad-gemini-dispatch`. Claude worker → the in-session `Agent` tool.

## Contents

The body is the operating path: routing, the isolation and read-audit contracts,
the hard rules, and Flow Steps 1-5. Six references carry the detail — open one
only when its column applies.

| Reference | Open it when |
|---|---|
| `references/invocation.md` | building the call — what each wrapper flag does, and the stream-json transport note |
| `references/isolation.md` | deciding what a `--sandbox read-only` call actually contains — the v2 read-only path, containment posture, standing residuals, the agy settings this host never writes, the tool→action map, who heals a stale `.agybak` |
| `references/read-audit.md` | wiring a caller that consumes the read-audit digest — shape, caps, retry-merge, the durable file |
| `references/terminal-causes.md` | a call classified terminal (65) and you are deciding what to tell the user |
| `references/repair-loop.md` | a dispatch routed to repair — the Step 5 procedure (run-log path, analyzer prompt and read-only check, reply, branch) |

## Routing — agy is the search/research specialist (pass `--web`)

agy's `read_url` action (`read_url_content` / `search_web`) is the toolkit's
external-documentation research reach, which makes agy the research leg. Since
the read-only path v2 the web tools live ONLY in the research agent: a
research dispatch MUST pass `--web` (on a hardened install every dispatch is
read-only, so without `--web` or `--review-web` the REVIEW agent runs — it has
no web tool at all and the model answers from memory, SUCCESS, admitted: a
silently ungrounded research answer). `--web` outside `--sandbox read-only` is
an invocation error. **`--review-web` is not a research flag**: it is the
review leg of a review round that binds `review_web_authorized` true
(`triad-cross-family-review` prints it — every v2 round under the owner's
standing authorization, R-REVIEW-WEB). It selects the same research agent and
web-tool admission as `--web` but NEVER appends the investigation clause
below; it needs `--sandbox read-only` and `--cwd` like a review dispatch, and
`--web` with `--review-web` is refused. Two reasons the routing matters: **grounding** (agy pulls
the current vendor source instead of the leader answering from memory) and
**context hygiene** (the raw page stays in the agy worker; the leader gets
back the grounded answer). Research hosts need `read_url(*)` allowed in
`~/.gemini/antigravity-cli/settings.json` (the `--setup-agents` hint). No
model name is pinned. The wrapper appends the `web-evidence` clause, loaded from
the vendored spec through `prompts_v2.py` (`_common._investigation_clause("agy")`;
an unreadable file → `config-conflict` 65 before the spawn; no embedded
constant), to the END of every `--web` prompt (spec case C29): a `search_web` result is a
pointer, never a citation; every cited web fact must come from a
`read_url_content` fetch and carry that page's own date or version; unfetched
or placeholder URLs and bare years are forbidden; the audit row and run-log
record the prompt as sent — so a caller's brief states WHAT to find, not how
to cite it.

## Read-only path v2 (`--sandbox read-only`, agy >= 1.1.18; spec `docs/superpowers/specs/2026-08-22-agy-readonly-v2-spec.md`)

A read-only dispatch runs agy as a **setup-once** tools-allowlisted custom
agent: `triad-readonly-review` (`view_file`, `grep_search`, `list_dir`,
`find_by_name`, `finish`; `commandExecutionPolicy: off`; NO web tool) or,
under `--web` or `--review-web`, `triad-readonly-research` (the same plus
`read_url_content`, `search_web`). Forbidden tools are ABSENT rather than
denied, so an admitted run never produces the errored step that flips agy's
terminal status (#826 / #839). The call passes `--add-dir <cwd>` (repository
reads are auto-allowed in print mode — measured 1.1.18, ladder round 2 K2;
writes stay denied without the danger flag, K5), and NOTHING else: no
`--dangerously-skip-permissions`, no settings deny transaction, no agy
`--sandbox`, no soft-deny retry.

**Caller obligation — `--cwd` is MANDATORY on this path, and the wrapper
ENFORCES it (owner ruling 2026-08-26).** `--add-dir` is derived from `--cwd`
and from nothing else; a review dispatch (no `--web`; `--review-web`
included) without `--cwd` is refused `EXIT_ARG_ERROR` BEFORE any vendor work,
with the remedy on stderr.
The `--web` research agent stays exempt (web-only research may legitimately
run grant-less). Why the guard exists: a grant-less dispatch runs read-blind
— every read soft-denies, and the admission-side read-blind guard catches
only a run whose reads visibly errored, so a leg that never attempted a read
was admitted `ok` and answered blind. Measured population: 211 of the first
421 `--agent` dispatches in `_logs/antigravity/audit.jsonl` (all in the
2026-08-22 pre-fix window) carried no `--add-dir`; 94 were admitted `ok`.
Build the value from the REAL working directory read at dispatch time
(`pwd`), never from an assumed session cwd (leader CLAUDE.md Pitfall #5).

**Host setup (once):** `python3 ${CLAUDE_PLUGIN_ROOT}/bin/antigravity_wrapper.py --setup-agents` writes
both agent files under `~/.gemini/config/agents/` (workspace `.agents/` is NOT
loaded in print mode — K1). A dispatch only CHECKS the file (byte-identical to
the embedded body); missing or drifted → `config-conflict` (65) naming
`--setup-agents`. Research hosts additionally need `read_url(*)` allowed in
`~/.gemini/antigravity-cli/settings.json` (the setup command prints the hint).

**Admission = what the stream shows, never the vendor status alone:** every
non-blank stdout line must be a JSON object (else the run is unusable), exactly
one `result`, every tool name in any attempt ∈ the agent's allowlist (a
fallback to agy's full-tool default agent, or a model slip, is rejected as
**`admission-refused`** with the name on stderr — since 0.16.3; the other
refusals stay `vendor-error`), and a `status != SUCCESS` run is
admitted ONLY when every errored step named an allowed read tool or is an
answer submission (`finish`) that a LATER successful `finish` follows (the
model corrected its first submission — C40, 0.16.7) — logged as
`[wrapper] antigravity admitted-with-errored-steps n=<k> tools=[...] … — <reason>`. The
`init.agent` echo is a diagnostic only (agy echoes the REQUESTED name even on
fallback). Below 1.1.18 the dispatch is `config-conflict` ("run `agy update`");
there is no legacy path (`TRIAD_AGY_READONLY_MODE` is gone). Evidence:
`docs/spikes/2026-08-22-agy-permission-ladder/` (rounds 1-3); ledger
`docs/agy-vendor-workarounds.md` W-28 (W-05 now permissive-baseline only, W-06
removed, W-11 retired on this path). Reads and — for the research agent — network stay
open BY DESIGN (§ Standing residuals in `references/isolation.md`).

## Headless soft-deny adaptation (PERMISSIVE baseline only)

On the permissive baseline (`--sandbox` omitted, non-hardened install) the
wrapper still inserts `--dangerously-skip-permissions` on every build it
dispatches (opt out with `AGY_NO_HEADLESS_AUTOAPPROVE=1`), the 2026-07-18
adaptation to agy 1.1.3's headless soft-deny. The flag rides the first call,
so a soft-denied run is not re-run (it ends on its own no-answer
classification). The read-only path v2 never carries the flag. Facts that
still matter for the baseline:

- on 1.1.17/1.1.18 `permissions.deny` wins over the flag (Deny > dsp: ladder
  arm A `command(*)`, probe G `write_file(*)`); the 1.1.3-era "voids the
  transaction" statement is history;
- reads and network are open BY DESIGN on every build — `read_file` and
  `read_url` are never denied;
- agy has self-reported a denied write as done, so verify arrival, always.

Mechanism, chronology and residuals: [references/isolation.md](references/isolation.md).

## Isolation — what contains what

- **Read-only path v2**: the agent's tools allowlist (capability removal) +
  the vendor's own headless denial of anything else (no danger flag) + the
  wrapper's admission census. No settings transaction. Concurrent read-only
  dispatches never touch `settings.json`.
- **Permissive baseline** (`--sandbox` omitted, non-hardened): the
  version-gated danger flag only — no settings guard, no lock, no settings
  read. On a HARDENED install
  (`TRIAD_WRAPPER_HARDENED=1`, the consumer default) omission auto-upgrades to
  `read-only`, so every consumer dispatch — research included — takes the v2
  path (research passes `--web`).

Reasoning tier = `--model` passthrough (no-pin default when omitted) — pass a
CATALOG selector from `agy models` and/or `--effort low|medium|high` (agy's own
flag, working since 1.1.10). **Pin floor: `--model` / `--effort` require agy >=
1.1.10** — older builds silently IGNORED both flags in `-p` runs, so the wrapper
fail-closes a pinned dispatch below the floor as `config-conflict` (65).

**Read-audit digest (REPORT-ONLY).** On every completed call the wrapper folds
the stream's tool calls into a bounded digest, emits it on stderr before its
canonical summary as `[wrapper] antigravity read-audit {compact json}`, then
`read-audit-file: <absolute-path>` immediately after — the one custody line. The
digest carries NO policy — it gates, denies and judges nothing by itself; the
caller reads it and decides what a missing or unexpected packet-read means
for that dispatch.

**Durable digest FILE.** A caller that needs the digest as a file sets
`TRIAD_READ_AUDIT_FILE=<absolute-path>` in the wrapper invocation's
environment AT DISPATCH TIME; the wrapper writes `{meta, digest}` to exactly
that path on every completed call, success or failure — best-effort, never
changing the exit code or classification. Shape and caller notes:
[references/read-audit.md](references/read-audit.md). The review skill's use
of it — the per-attempt binding and the gate — is owned by
`triad-cross-family-review` `references/leg-contracts.md` (§ agy leg, the
Read-audit binding bullet; § agy read-audit gate).

## Hard rules

1. **Bash invocation only.** No `Agent()` around the wrapper itself. The stderr `[wrapper]` summary line and `run-log:` path emission only surface via Bash.
2. **Path-based agent input.** Pass the run-log file *path* to the repair agent, not its content. Inline-embedding corrupts on JSON-in-JSON / utf-8 / ANSI / large vendor stdout. The leader itself does NOT read the run-log content — it only passes the PATH to the read-only analyzer, and reads back (a) the wrapper's deterministic classification token and (b) the analyzer's inline JSON proposal. The run-log is untrusted vendor output; keeping the leader out of it preserves the privilege separation.
3. **Leave the run-log in place.** Never delete the run-log or anything else under `_logs/`: the wrapper's own sweep collects it later. Passing its path to the analyzer (rule 2) is the leader's only act on it.
4. **Repair agent ONLY on `unknown` / `extraction-error`.** Every other classification carries actionable meaning at the wrapper layer — dispatching the agent on them wastes the call.
5. **Test isolation — dispatch prompt = production-shape only.** Use the § 5b prompt of the Step 5 procedure VERBATIM. No meta-context, no test framing, no "this is a verification" / "treat as fake" disclaimers, even when the dispatch is a sample/test scenario. Reasoning: any test framing leaks into the vendor model's behavior and corrupts both the sample and the repair agent's accumulated memory.
6. **No model name pinning.** agy model names rot every few weeks. Use the vendor default by default; `--model <name>` only when the user explicitly named the model. Date-anchor any pinned model usage.
7. **Never `--dangerously-*` from user argv.** argparse defines no such option, so a caller can never supply it. ONE scoped internal exception (owner-authorized 2026-07-18): on the PERMISSIVE baseline only, the wrapper inserts `--dangerously-skip-permissions` because agy 1.1.3 made headless tools unusable otherwise (§ Headless soft-deny adaptation). The read-only path v2 never carries the flag — repository reads come from `--add-dir`, and a fallback run's writes/shell are denied by the vendor's own headless policy (ladder round 2, K1/K5). Measured on 1.1.17 under the flag: `permissions.deny` wins for `command(*)` and `write_file(*)` (arm A, probe G); the other deniable actions are inferred. Reads/network stay open by design regardless (`read_file` / `read_url` are never denied). Opt out with `AGY_NO_HEADLESS_AUTOAPPROVE=1`. No OTHER `--dangerously-*` / `--yolo` is ever used.
8. **Always spawn the repair agent — surfacing a failure is not repairing it.**
   When Step 4 routes a failure (`unknown` / `extraction-error`),
   spawn the `agy-wrapper-repair` sub-agent with the `Agent` tool's
   `run_in_background: true` so it runs alongside your foreground work; parse its
   inline proposal (§ 5c), and apply it (§ 5d) when it completes.
   Never skip it, and never treat reporting the failure to the user as
   discharging it — that is a separate obligation. The payoff is future routing
   rather than this call: the analyzer grows the classifier so the same vendor
   error auto-routes next time, which is why a skipped spawn is a silent
   regression that keeps the error failing un-routed. Mechanism: the agent is a
   read-only analyzer returning a JSON patch proposal; the leader applies it via
   the deterministic `apply_patch.py` (no LLM on the write path), which verifies
   routing on the failed run's stored record. Rule 4 scopes *which* classes route here;
   this rule says always follow through when they do.

## Flow

### Step 1 — Write the prompt file, build the wrapper invocation

Write the prompt body to a file with the Write tool, then run the wrapper as
ONE simple command on ONE line. The file is new per dispatch:
`<project>/_runs/prompts/<utc-timestamp>-antigravity.md`, where `<project>` is the
directory the leader runs in (read from `pwd` at dispatch time, like `--cwd`) — the
hardened install's allowed root, so the wrapper accepts the path (create the folder
with the Write tool as needed). The
wrapper's next-run sweep prunes the folder past the `dispatch-prompts` role's
floor; add `_runs/` to the project's `.gitignore` if it is not
already ignored. The file keeps Korean / emoji /
`$variables` / backticks / quotes intact with no shell quoting at all.

The `--cwd` argument is ABSOLUTE and is built from the REAL working directory
read at dispatch time (`pwd`) — never from an assumed session cwd. The session cwd resets to the primary working directory
around context reinitialization (leader CLAUDE.md Pitfall #5; probe-measured
2026-08-26), so a path built from the memory of an earlier `cd` silently
targets the wrong repo.

The command line carries LITERAL values only — no `$(…)`, heredoc, variable,
pipe, array or `\` continuation: the plugin's permission grant matches one
simple command, and a command substitution, a variable or an array cannot be
checked before it runs, so such a call prompts on every dispatch. Fill in the
bracketed options you need with literal values and drop the rest:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/bin/antigravity_wrapper.py --prompt-file <project>/_runs/prompts/<utc-timestamp>-antigravity.md [--cwd /absolute/path] [--sandbox read-only] [--web or --review-web] [--model <pinned-model-name>] [--effort <low, medium or high>] [--pydantic module:Class] [--json-schema-file /absolute/path/schema.json] [--attempt <int>] [--timeout <seconds>] [--debug]
```

**`--json-schema-file <path>`** hands a CALLER-OWNED JSON schema file
straight to agy `--json-schema` (which accepts a schema string OR a path, so
the value is passed as-is — no read, no re-serialization). TRANSPORT ONLY: no
local validation and no repair re-run, the caller admits the answer with its
own validator (the path `triad-cross-family-review`'s v2 rounds use for their
per-attempt producer schema projection). The wrapper still picks the channel:
the result's `structured_output` is printed when it is an object; any other
shape (absent, null, non-object) is treated as absent and falls back to the
response text (logged), on this arm exactly as on `--pydantic`. It belongs to the READ-ONLY
route only (`--sandbox read-only`) and is mutually exclusive with `--pydantic`. The
path must name an existing file (a relative path is rebased on the wrapper's
process-entry cwd, as `--prompt-file`); the check runs BEFORE any vendor work.

**`--attempt <int>`** (>= 1, default 1) is the dispatch attempt number,
RECORDED on the transport receipt and the summary tail and never interpreted
— no control flow reads it, it drives no retry. Below 1 is refused pre-spawn.

Host setup, once: `python3 ${CLAUDE_PLUGIN_ROOT}/bin/antigravity_wrapper.py --setup-agents`
(writes the two read-only agent definitions; § Read-only path v2).

Flags at a glance: `--sandbox read-only` (v2 read-only path, § Read-only path v2) · `--web` (research agent with web tools + the investigation clause; default = review agent without) · `--review-web` (a review round's leg with web: the research agent, no clause)
· `--prompt-file <abs>` (the prompt body, written with the Write tool — Step 1) · `--pydantic
module:Class` (native `--json-schema`; a dict `structured_output` is the
answer, anything else falls back to the response text; one repair turn, then
66) · `--timeout <s>` (default 600) · `--cwd
<abs>` (**REQUIRED with `--sandbox read-only`** — it becomes `--add-dir`, the
leg's only read grant; § Read-only path v2 caller obligation) · `--model
<selector>` · `--effort low|medium|high` (both pin-floored at
agy >= 1.1.10) · `--debug`. Still **no `--dangerously-*`** (Hard
rule 7). What each flag actually does, and the wrapper-internal transport note:
[references/invocation.md](references/invocation.md).

### Step 2 — Run via Bash; capture rc, stdout, stderr

Wrapper stderr contains:
- Timestamped wrapper log lines
- 1-line summary: `[<timestamp>] [wrapper] antigravity <classification> exit=<int> vendor=<int> elapsed=<s>` followed by the recorded-facts tail ` attempt=<n>`, ` prompt_file=<abs>` when a `--prompt-file` was given, ` model=<slug>` when `--model` was requested and ` reasoning=<tier>` when `--effort` was requested (absent = the CLI's config default) (every wrapper log line, this one included, carries the leading timestamp bracket — Step 3 reads it from the tool result)
- On every completed call: `[wrapper] antigravity read-audit {…}` (informational digest, § Isolation above), then `read-audit-file: <absolute-path>` (the durable file `emit_read_audit` just wrote — `$TRIAD_READ_AUDIT_FILE` if set, else the wrapper's own default location)
- On failure: `run-log: <absolute-path>`

Wrapper stdout = agy's final answer (the stream-json terminal `result` event's `response` field — no marker to strip, no ANSI scrub needed).

### Step 3 — Read the classification

Read the classification from the Bash tool result — no shell parse (a
command substitution or a pipe cannot be checked before it runs, so a parse
command would prompt). In the stderr, read the LAST line that STARTS with
`[<timestamp>] [wrapper] antigravity ` (the timestamp bracket, then `[wrapper] antigravity `);
the classification is the token right after `[wrapper] antigravity ` (e.g. `ok`,
`unknown`, `extraction-error`). Use the LAST such line (the codex / gemini
convention — take the last emission only). On a failure, the run-log path is the value after
`run-log: ` on its line (the last such line).

Only a line that STARTS with that prefix counts: the summary tail carries a
free-text field (`prompt_file=<abs>`), so a reading that takes the last
`[wrapper] antigravity <token> ` ANYWHERE in the line could read a token the wrapper
never emitted. The engine also percent-escapes every free-text field of the summary
(`_common._summary_field` — SPACE and `[` / `]` are outside the safe set, so the
sequence cannot be built inside `prompt_file=`; an ordinary POSIX path is
emitted byte-identically and the audit row keeps the raw value) — the two
defences are independent. The wrapper's other stderr lines (`run-log: <abs>`,
`read-audit-file: <abs>`, `exec cwd=… argv=…`) never START with the `[wrapper] antigravity <token> ` prefix;
the read-audit digest line carries `read-audit` (not a token) after the cli name.

Token set:
`ok | server-capacity | cli-subscription-cap | token-limit | oauth-env | schema-fail | timeout | extraction-error | vendor-error | admission-refused | vendor-timeout | truncated-answer | config-conflict | unknown`

**The classification token is the branch key** (Step 4). The exit code is a
coarse signal for shell control flow and does not identify the action on its own
— `65` covers the terminal classes AND `truncated-answer`, which take different
actions. Codes: `0` ok / `1` unknown or extraction-error / `2` timeout / `3` arg
/ `4` binary missing / `64` server-capacity exhausted / `65` terminal or
truncated-answer / `66` schema fail. **`unknown` is ALWAYS exit 1**: exit `3`
means an ARGUMENT error only. A vendor-spawn failure (Popen `OSError`) inside
the shared engine classifies `unknown`, and the agy driver CONFORMS every
forwarded engine verdict through `map_classification_to_exit`, so that shape
arrives as `unknown` / 1 and routes to the repair branch. The stream is read like
the codex host reads its own: a line that does not decode is skipped, two
result events read the last one, and a stream cut mid-line is recorded
(`truncated_tail`), never refused; on the read-only route the admission's own
framing and one-result rules still refuse with `vendor-error` 65. Caveat: an ARGPARSE
rejection also exits 2
with NO `[wrapper]` summary line — an invocation error, not a timeout; fix the
call, and never spawn the repair agent for it.

### Step 4 — Branch on classification

| classification (rc) | Leader action |
|---|---|
| `ok` (0) | Return wrapper stdout (agy's final answer text). |
| `oauth-env` (65) | STOP. The login is missing or expired, or agy reported an authentication failure (its auth banner, or `result.error`) — this outranks agy's own print timeout on the same run. Do not retry, do not try another route or credential, and never read or change the credential store; tell the owner to re-log in through the CLI's own browser flow (the sign-in URL agy's auth banner names). A same-basis re-dispatch runs only after the owner reports the re-login. **NOT** repair-agent territory. |
| terminal (65) — cli-subscription-cap / token-limit / config-conflict / vendor-error | Surface to the user with the cause, and name the run-log path when there is one. Per-class causes and what the leader may say about each — including why `vendor-error` keeps the answer OUT of stdout and why none of these route to repair — [references/terminal-causes.md](references/terminal-causes.md). |
| `admission-refused` (65) | The v2 admission census found a tool OUTSIDE the agent's allowlist in the stream (`manage_task` / `run_command` / `send_message` …) — the allowlist class only; framing / unexplained-degraded / read-blind refusals stay `vendor-error` (an errored `finish` that a later successful `finish` — a `step_type: finish` DONE update without `tool_info.error` — follows EXPLAINS a degraded status and is admitted; one with no later success still refuses as `vendor-error`). The COMPLETE answer is quarantined (run-log copy only, `quarantined answer (N chars)`). Surface, never repair. Review-leg callers: one retry, then terminally missing. If it recurs after 0.16.3, check the host re-ran `--setup-agents` (agent body carries the allowlist rule) — the model is TOLD the five permitted tools; agy still advertises 57. |
| `vendor-timeout` (65) | agy's OWN turn timeout fired before the wrapper deadline (`result.status` ERROR, `result.error` "timeout waiting for response", empty response, vendor rc 1; live 2026-09-04 at 857 s of a 900 s budget with 33 allowlisted reads). Surface, never repair (the analyzer escalated: no existing class fits). Review-leg callers: re-dispatch ONCE with a narrower read scope (smaller packet / fewer cited sites), then terminally missing. |
| `truncated-answer` (65) | agy folded the MIDDLE of a long answer CLI-side (own-line `<truncated N bytes\|lines>` marker; observed cap ~4KB) and keeps NO full copy anywhere, so the loss is unrecoverable at the wrapper layer. The lossy answer is quarantined from stdout (bounded copy in the run-log). **Leader remediation: re-dispatch once asking for a shorter answer; the ~4 KB fold is unmeasured since agy 1.1.9.** **NOT** repair-agent territory (deterministic vendor behavior on the answer-present path; a classifier patch cannot express it). Retrying the same prompt unchanged folds again — do not plain-retry. |
| `server-capacity` exhausted (64) | Wait + retry, or surface. Wrapper already ran the capacity ladder: up to 2 stream-json call re-runs after a 15 s / 45 s backoff, EVERY attempt with the caller's full `--timeout` (the timeout is per attempt, so the leg can take up to 3 × `--timeout` + 60 s wall-clock) — EXCEPT on a read-only run that also called a tool outside the allowlist: that run returns after ONE dispatch (stderr + `extraction_error` name the forbidden tool), the caller's fresh dispatch being the contract's one retry (2026-09-05). |
| `unknown` (1) | **Step 5 — repair agent dispatch; never skip it (Hard rule 8).** Includes the engine-decided transport failures the driver FORWARDS at the conformed exit 1 — a vendor-spawn `OSError` (nothing ran), a reader/writer thread that failed to START, and an `Exception` raised while waiting on the child (in both the child was killed and reaped, its stdout kept). Those three are transport defects, not classifier gaps, so expect the analyzer to ESCALATE rather than propose a pattern. |
| `extraction-error` (1) | **Step 5 — repair agent dispatch; never skip it (Hard rule 8).** agy ran but the driver found no usable answer — a `SUCCESS` status with an EMPTY `response` (`extraction_error = "empty-answer-body"`, agy self-reports success on a task it did not actually do), a fully empty capture, or garbage/no-result stream text with no matching pattern. The repair agent inspects whether the cause is a vendor refusal pattern worth a classifier patch, or a true extraction bug → ESCALATE. |
| `timeout` (2) | Surface to the user (the wrapper already fails fast). NOT repair-agent territory. |
| arg (3) / binary missing (4) / `schema-fail` (66) | Surface to user with cause (empty prompt / `agy` not on PATH / `--pydantic` output still failed local validation after the one schema-repair re-run — fix the schema or prompt and re-dispatch). |

**NOT produced by agy** (do not branch on these — they belong to other CLIs):
`schema-rejected` / `task-blocked`.
`schema-rejected` is a **codex-side submit-time rejection class** (codex's
`--output-schema` is rejected before the run even starts); agy's native
`--json-schema` failures instead surface as `schema-fail` (66) after the
wrapper's own local validation; `task-blocked` is claude's envelope class.
agy's `config-conflict` causes are listed in references/terminal-causes.md.

### Step 5 — Repair branch: read-only analyzer proposes, leader applies (`unknown` / `extraction-error` only)

Use the `Agent` tool with `subagent_type` set exactly to `triad-dispatch:agy-wrapper-repair`, **`run_in_background: true`** (Hard rule 8). `CLI=antigravity`. Follow [`references/repair-loop.md`](references/repair-loop.md) § 5a-5e with `<CLI>` = `antigravity` and `<ANALYZER>` = the agent that sentence names: the run-log path, the analyzer prompt and its read-only check, the reply, and the branch. Its one command runs from here — ONE simple command, literal arguments:

- the apply line (§ 5d, `propose`):

  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/bin/apply_patch.py --cli antigravity --proposal-file <project>/_runs/prompts/<utc-timestamp>-antigravity-proposal.json --verify-run-log <the run-log path exactly as printed>
  ```

## Outputs (what this skill returns)

- `ok`: wrapper stdout (agy's final answer text).
- terminal: `{ class, reason, action_required }`.
- `server-capacity` (64, retries exhausted): transient overload — leader-policy
  retry, or surface.
- repair-cycle: analyzer proposes → leader applies via the applier with `--verify-run-log`, which re-classifies the failed run's stored record (exit 0 routes to the proposal; 4 applied but not routed → escalate); OR escalate (surface REASON, no apply).

## Self-healing

One layer keeps the agy leg healthy, and the leader drives it: the
**`agy-wrapper-repair` analyzer (reactive, per call)** — the Step 5 path:
read-only proposal → deterministic apply → the same vendor error auto-routes
next time. Dispatch frequency falls as the classifier matures.

The wrapper never writes, locks or heals the agy settings; a stale `.agybak`
is the codex host's to heal —
[references/isolation.md](references/isolation.md) § Operational notes.

## Path scope

- **Passes the PATH of** `_logs/antigravity/runs/<id>.json` (run-log) to the analyzer. The leader does NOT read the run-log content (Hard rule 2) — the analyzer does, via `Read`.
- **Leaves** the run-log in place; the wrapper's own sweep collects it.
- **Invokes** `bin/antigravity_wrapper.py` (dispatch) and `bin/apply_patch.py` (deterministic proposal applier + stored-record verifier) via Bash.
- **Dispatches** sub-agent `agy-wrapper-repair` (read-only analyzer).

The leader (not the analyzer) is the only writer to the classifier extension — via the deterministic `apply_patch.py`. Does NOT edit `bin/_common.py` source or read `_logs/antigravity/audit.jsonl`.

## See also

- the plugin `README.md` — wrapper contract + run-log schema.
- `agents/agy-wrapper-repair.md` — the repair analyzer (one body for the three CLIs, rendered from one template; never hand-edited).
- `triad-codex-dispatch` — parallel SKILL for Codex.
- `triad-gemini-dispatch` — legacy compatibility with the older gemini CLI.
- `triad-cross-family-review` — final pre-merge cross-family review (the agy leg there runs the setup-once `triad-readonly-review` agent — no shell / write / web tool — with `--add-dir`, admitted by the stream census; the by-design read residual persists — § Read-only path v2 + § Isolation).
