# agy repair loop — run-log extraction and the apply/verify branch

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` Step 5. Read this
when a dispatch classified `unknown` / `extraction-error` / `timeout` and the
repair analyzer is in play. The analyzer prompt itself (Step 5b), the proposal
read (Step 5c) and every command stay in the SKILL body; this file carries the
surrounding rules.

## Contents

| Section | Open it when |
|---|---|
| Terminal (65) causes | a call classified terminal and you are deciding what to tell the user |
| 5a — read the run-log path | reading the run-log path from the wrapper's stderr |
| 5d — branch | the analyzer returned and you are applying or escalating |
| Branch summary | you want the outcome table only |

## Terminal (65) causes — what the leader surfaces

Each of these is already matched at the wrapper layer, so none of them routes to
the repair agent (Hard rule 4): only `unknown` / `extraction-error` / `timeout`
do.

| cause | what to tell the user |
|---|---|
| `cli-subscription-cap` | quota — daily reset, or re-dispatch later |
| `token-limit` | prompt size too large — shrink the prompt |
| `oauth-env` | STOP — re-login required through the CLI's own browser flow; no retry, no other route, the credential store is never read; auth stays user-managed |
| `config-conflict` | either the settings deny transaction failed (lock-lease timeout, or a corrupt `~/.gemini/antigravity-cli/settings.json`), or `agy --version` probed below `_STREAM_JSON_FLOOR`, where the wrapper fails CLOSED before any vendor dispatch (remediation: `agy update`, then re-dispatch), or the run's exposed runtime model (`init.model`) contradicts the pinned `--model` — the answer is withheld and the stderr line names both; the user changes the roster entry (or `--model`), the leader never substitutes a model |
| `admission-refused` | the v2 admission census found a tool OUTSIDE the agent's allowlist in the stream (the allowlist class only; other refusals stay `vendor-error`); the complete answer is quarantined in the run-log. Driver-emitted, never a classifier patch — surface, one retry at most. |
| `vendor-timeout` | the stream's terminal `result` is `status: ERROR` with the typed `error` "timeout waiting for response" and an empty response — agy's own turn budget ran out. Driver-emitted (`_is_vendor_turn_timeout`), never a classifier patch; surface, one narrower re-dispatch at most. |
| `vendor-error` | the stream's terminal `result` event carried a non-empty answer WITH rc≠0 or a non-`SUCCESS` status. The answer is deliberately NOT on stdout: it survives only in the run-log's quarantined `extraction_error` copy and the raw NDJSON stream, which the leader does not open (Hard rule 2). Surface the classification token + exit codes and name the run-log path; a human can read it out of band to decide re-dispatch vs accept |

`config-conflict`'s floor gate is a deterministic pre-dispatch check and
`vendor-error` is driver-emitted on the answer-present path — neither is
something a classifier patch could express, which is why they stay out of the
repair branch.

## 5a — read the run-log path

Take the path from the Bash tool result (SKILL.md Step 3) exactly as the wrapper
printed it: the value after `run-log: ` on the LAST `run-log:` line of stderr —
a file the wrapper wrote under its own `_logs/antigravity/runs/`. The leader
passes it on unchanged; it is not re-checked. Recorded limit: a vendor child
printing a forged `run-log:` line earlier in stderr is a constructed shape — the
wrapper's own line comes last and the leader reads the last; not guarded.

The leader passes this PATH to the analyzer and does not read the run-log content
itself (Hard rule 2). There is no output file: the analyzer replies inline.

## 5d — branch: escalate surfaces, propose applies and verifies

**Control flow (one reading only).** 5a reads the path from the failing dispatch's tool result,
right after Step 2's failing dispatch — the path it reads is what gets
substituted into 5b's prompt. Step 5b then spawns the analyzer in the BACKGROUND
(`run_in_background: true`, Hard rule 8) and the leader WAITS for its completion
notification — a separate, non-Bash step; never poll. Only once the analyzer's
inline JSON reply has arrived does the leader pick the branch from its `outcome`
(the value 5c parses). The run-log stays in every branch: never delete it, or
anything else under `_logs/` — the wrapper's own sweep collects it later.

The commands themselves are in SKILL.md Step 5d — run them from there, never
from this file: the skill body is where the plugin path is filled in.

- **`propose`** — the leader writes the analyzer's `proposal` object to a new
  absolute file (the Write tool) and runs the apply step, one simple command
  with literal arguments (the command in SKILL.md Step 5d). It reads the
  applier's exit code from the Bash tool result:
  - **0** — applied. The leader verifies routing in a separate Bash call: Step
    1's literal command line again, unchanged, with `--repair-mode` appended
    (SKILL.md Step 5d).
  - **3** — invalid proposal or bad input; the extension file is untouched.
    Surface `proposal rejected by applier: <REASON>` and treat it as an escalate.
- **`escalate`** — the analyzer could not classify: surface
  `repair escalated: <REASON>`; no apply.
- **anything else** — unparseable analyzer output: the agent returned
  conversational text (or nothing), or its `outcome` is neither value. Do NOT
  proceed silently — surface `repair skipped — unparseable analyzer output; the
  original failure classification stands`. No patch is
  applied; the run-log is the diagnostic input for the manual follow-up.

The applier re-validates the proposal independently (enum + pattern-name +
literal bounds), so it is the security backstop even if the analyzer misbehaves:
on exit 3 the extension file is left untouched and the leader surfaces it as an
escalate. No output file exists; on unparseable analyzer output the run-log is
the input for manual diagnosis.

## Branch summary

| OUTCOME | Next action |
|---|---|
| propose → applier exit 0 | Re-run wrapper `--repair-mode` to verify routing; report the routing result. The framework now catches future identical errors. |
| propose → applier exit 3 | Proposal invalid (analyzer error) — surface REASON, treat as escalate. |
| escalate | Surface REASON. Manual diagnosis needed; no apply. |
