# agy repair loop — run-log extraction and the apply/verify branch

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` Step 5. Read this
when a dispatch classified `unknown` / `extraction-error` / `timeout` and the
repair analyzer is in play. The analyzer prompt itself (Step 5b) and the
proposal parse (Step 5c) stay in the SKILL body; this file carries the
surrounding shell.

## Contents

| Section | Open it when |
|---|---|
| Terminal (65) causes | a call classified terminal and you are deciding what to tell the user |
| 5a — extract the run-log path | pulling the run-log path out of wrapper stderr |
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
| `oauth-env` | re-login required; auth stays user-managed |
| `config-conflict` | either the settings deny transaction failed (lock-lease timeout, or a corrupt `~/.gemini/antigravity-cli/settings.json`), or `agy --version` probed below `_STREAM_JSON_FLOOR`, where the wrapper fails CLOSED before any vendor dispatch. Remediation for the latter: `agy update`, then re-dispatch |
| `vendor-error` | the stream's terminal `result` event carried a non-empty answer WITH rc≠0 or a non-`SUCCESS` status. The answer is deliberately NOT on stdout: it survives only in the run-log's quarantined `extraction_error` copy and the raw NDJSON stream, which the leader does not open (Hard rule 2). Surface the classification token + exit codes and name the run-log path; a human can read it out of band to decide re-dispatch vs accept |

`config-conflict`'s floor gate is a deterministic pre-dispatch check and
`vendor-error` is driver-emitted on the answer-present path — neither is
something a classifier patch could express, which is why they stay out of the
repair branch.

## 5a — extract the run-log path

```bash
RUN_LOG_PATH=$(grep -E '^\[[^]]*\] run-log: ' <stderr-text> \
                 | sed -E 's/^\[[^]]*\] run-log: //' | tail -1)
# Shape gate, in order: reject traversal and anything that would break quoting
# downstream, then pin the directory AND the basename the wrapper actually emits.
case "$RUN_LOG_PATH" in
  *..*|*\'*|*\"*|*'`'*|*'$'*|*' '*|*"$(printf '\t')"*|"")
    echo "run-log path rejected (traversal, quote/expansion character, or whitespace): $RUN_LOG_PATH"; exit 1 ;;
esac
case "$RUN_LOG_PATH" in
  */_logs/antigravity/runs/*.json) ;;
  *) echo "run-log path failed shape validation (expected .../_logs/antigravity/runs/*.json): $RUN_LOG_PATH"; exit 1 ;;
esac
case "$(basename -- "$RUN_LOG_PATH")" in
  *.json) ;;
  *) echo "run-log basename is not a .json file: $RUN_LOG_PATH"; exit 1 ;;
esac
[ -f "$RUN_LOG_PATH" ] || { echo "run-log path missing"; exit 1; }
```

The value reaches `rm -f` and the 5b analyzer prompt, so it passes all three
gates BEFORE either use: no `..` segment, no quote / backtick / `$` / whitespace
character, the wrapper's own directory shape, and a `.json` basename. A value
that fails any gate is refused rather than passed through.

Anchor on the wrapper's OWN timestamped log line (`^\[[^]]*\] run-log: `,
mirroring the Step 3 summary grep's anchor): a plain `.*run-log: ` substring
match can be tricked by vendor-influenced stderr text that merely CONTAINS that
phrase, and the stream is untrusted vendor output. Validate the extracted path
against the expected `_logs/antigravity/runs/…json` shape BEFORE using it in
`rm -f` or interpolating it into the analyzer prompt — a value that fails
validation is refused rather than passed through. Take everything after the
anchor to the end of that line (last occurrence), since the path may contain
spaces and a whitespace-delimited grab would truncate it. Keep every later use
double-quoted.

The leader passes this PATH to the analyzer and does not read the run-log content
itself (Hard rule 2). There is no output file: the analyzer replies inline.

## 5d — branch: escalate surfaces, propose applies and verifies

**Control flow (one reading only).** 5a's extraction runs in its OWN Bash call,
right after Step 2's failing dispatch — its output (`RUN_LOG_PATH`) is what gets
substituted into 5b's prompt. Step 5b then spawns the analyzer in the BACKGROUND
(`run_in_background: true`, Hard rule 8) and the leader WAITS for its completion
notification — a separate, non-Bash step; never poll. Only once the analyzer's
inline JSON reply has arrived do 5c's parse and this case block run, and they run
TOGETHER in ONE Bash invocation, re-supplying `RUN_LOG_PATH` there too (re-run
5a's extraction against the same stderr text, or inline the already-known path
literally). Shell state (`RUN_LOG_PATH`, `AGENT_JSON`) does not persist across
separate Bash calls, and a split run silently no-ops the cleanup.

```bash
case "$OUTCOME" in
  escalate)
    echo "repair escalated: $REASON"
    rm -f "$RUN_LOG_PATH"
    ;;
  propose)
    if printf '%s' "$PROPOSAL" \
         | apply_patch.py --cli antigravity; then
      # applier exit 0 → patch landed; re-run in --repair-mode to verify routing.
      # Replay the SAME quoted argv array Step 1 built, with --repair-mode
      # appended as its own DISTINCT element — never reconstruct the
      # invocation as a pasted/retyped string (an optional bracketed value
      # is not quoting-safe once flattened).
      "${AGY_CMD[@]}" --repair-mode
    else
      echo "proposal rejected by applier: $REASON"   # applier exit 3 → treat as escalate
    fi
    rm -f "$RUN_LOG_PATH"
    ;;
  *)
    # Unparseable analyzer output: the agent returned conversational text (or
    # empty), so jq failed and OUTCOME is not propose/escalate. Do NOT silently
    # proceed — SURFACE it. No patch is applied; the original failure
    # classification stands.
    echo "repair skipped — unparseable analyzer output (OUTCOME='$OUTCOME'); the original failure classification stands"
    # Keep the run-log: it is the diagnostic input for the manual follow-up.
    # The wrapper's age-floor sweep reclaims it if abandoned.
    ;;
esac
```

The applier re-validates the proposal independently (enum + pattern-name +
literal bounds), so it is the security backstop even if the analyzer misbehaves:
on exit 3 the extension file is left untouched and the leader surfaces it as an
escalate. Cleanup is the `rm -f "$RUN_LOG_PATH"` inside the propose/escalate arms
(no output file exists); on unparseable analyzer output the run-log stays for
manual diagnosis. The wrapper's `_prune_run_logs()` (`glob("*.json")`) is the
failsafe for orphans.

## Branch summary

| OUTCOME | Next action |
|---|---|
| propose → applier exit 0 | Re-run wrapper `--repair-mode` to verify routing; report the routing result. The framework now catches future identical errors. |
| propose → applier exit 3 | Proposal invalid (analyzer error) — surface REASON, treat as escalate. |
| escalate | Surface REASON. Manual diagnosis needed; no apply. |
