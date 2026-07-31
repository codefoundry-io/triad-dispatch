# agy wrapper invocation — flag reference

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` Step 1. Read this
when you need what a flag actually does; the invocation SHAPE (heredoc
terminator, `--prompt-file` rule, argv-array retention) stays in Step 1 itself.

## Flags

- `--sandbox read-only` selects the per-call deny transaction (§ Isolation).
  Omit for the permissive baseline.
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
- `--prompt-file <absolute-path>` reads the prompt body from a file instead of
  `--prompt`. Use it whenever the body is not leader-authored (see above); the
  path is absolute, and a hardened install gates it against the allowed roots.
- `--cwd` sets agy's working directory.
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
