# agy wrapper invocation — flag reference

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` Step 1. Read this
when you need what a flag actually does; the invocation SHAPE (heredoc
terminator, `--prompt-file` rule, argv-array retention) stays in Step 1 itself.

## Flags

- `--sandbox read-only` selects the read-only path v2 (agy >= 1.1.18): the
  setup-once tools-allowlisted agent (`--agent triad-readonly-review`, or
  `triad-readonly-research` under `--web`) + `--add-dir <cwd>`; no danger
  flag, no settings transaction, no agy `--sandbox`; admission by the stream
  (§ Read-only path v2 in isolation.md). Below 1.1.18 → `config-conflict`.
  `--setup-agents` writes the two agent files once per host (no prompt
  needed). `AGY_AGENTS_DIR` is a TEST hook for the file location (default
  `~/.gemini/config/agents`; logged when set). Omit `--sandbox` for the
  permissive baseline.
- `--pydantic module:Class` forces JSON output through agy's **native
  `--json-schema`** flag: the wrapper passes `json.dumps(cls.model_json_schema())`
  as its argv value — no prompt-side instruction, no completion marker. The
  driver's `_validate_structured` PREFERS the vendor's own schema-checked
  `result["structured_output"]` and falls back to the raw response text when it
  is absent (vendor-drift guard); local pydantic re-validates either way. On
  failure it does ONE schema-repair re-run (a text hint appended to the `-p`
  prompt), then exits `EXIT_SCHEMA_FAIL=66`. e2e-verified against real agy
  (`tests/e2e/wrappers/agy-stream/s1-real-stream.sh` case 3).
- `--timeout` default is `600` seconds. The wrapper derives agy's `--print-timeout` from it (`max(timeout - 10, 5)s`); the wrapper's own SIGTERM→SIGKILL process-group kill (shared with codex/gemini/claude) is the backstop.
- `--prompt-file <absolute-path>` reads the prompt body from a file INSTEAD of
  `--prompt` (the two are mutually exclusive — argparse rejects both together).
  Use it whenever the body is not leader-authored, OR whenever the body quotes
  a dispatch template or a SKILL body — quoted text carries the house heredoc
  terminator verbatim and would close the heredoc early (Step 1). The path is
  absolute, and a hardened install gates it against the allowed roots.
- `--cwd` sets agy's working directory.
- `--model <selector>` passes a CATALOG selector from `agy models` (no-pin
  default when omitted). **Pin floor: agy >= 1.1.10** — before 1.1.10 the
  vendor applied `--model`/`--effort` after model configuration had already
  initialized, so `-p` runs silently fell back to the persisted/default model
  (vendor changelog, 1.1.10 2026-08-03). The wrapper fail-closes a pinned
  dispatch below the floor (`_MODEL_FLAG_FLOOR`) as `config-conflict` (65)
  rather than dispatching a voided pin; pinless dispatches are not gated.
- `--effort low|medium|high` passes agy's own `--effort` (reasoning effort;
  ships in 1.1.10, retiring the stripped/buggy `thinkingLevel` era of issue
  #1675). Same pin floor as `--model`; omit for the vendor default.
- `--debug` accumulates a markdown debug table.

Still **no `--dangerously-*`** (Hard rule 7).

## Transport note (wrapper-internal)

The leader just calls the wrapper. agy at or above `_STREAM_JSON_FLOOR` emits
typed NDJSON via `--output-format stream-json`, so the wrapper
spawns it through the SAME shared subprocess core codex/gemini/claude use
(`_common._run_once`) — no pty, no completion sentinel, no prompt mutation — and
fails CLOSED with `config-conflict` on a build below that floor. The
earlier pty + sentinel + transcript-read transport is RETIRED; git history has
the machinery.
