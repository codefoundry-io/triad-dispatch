# agy read-audit digest — the consumer contract

Loaded on demand from `triad-antigravity-dispatch/SKILL.md` § Isolation. Read
this when wiring a caller that consumes the digest — above all
`triad-cross-family-review`, whose agy leg gate reads the durable file. The
engine-side schema (fold rules, prune caps, wiring) is documented once in
the plugin `README.md` § Read-audit digest file; this file is the
caller's half of the contract.

## The three artifacts

| Artifact | When it exists | Shape |
|---|---|---|
| stderr `[wrapper] antigravity read-audit {…}` | every completed call, before the canonical summary | compact JSON, timestamp-prefixed like every wrapper log line |
| stderr `read-audit-file: <absolute-path>` | every completed call, right after the digest line | the path just written |
| the digest FILE | every completed call, success or failure | `{"meta": {cli, ts_utc, classification, exit_code, vendor_exit_code, elapsed_s}, "digest": <the digest object, verbatim>}` |

The run-log's `read_audit` key carries the same digest on FAILURE only, and stays
the repair-agent's input artifact.

## Binding the file

Set `TRIAD_READ_AUDIT_FILE=<absolute-path>` in the wrapper invocation's
environment. The wrapper writes the digest to exactly that path — parent dirs
created, existing content overwritten. Unset, it writes to its own default
location (`_logs/antigravity/read-audit/<UTC-ts>-<pid>-<uuid8>.json`, self-pruned
like run-logs) as an operator convenience; no caller reads that default today.
Writing is best-effort: an IO failure leaves the exit code and classification
unchanged, and the `read-audit-file:` line is omitted.

## Notes for a consuming gate

- Bind the env var AT DISPATCH TIME. The evidence cannot be created afterwards.
- Read the FILE with `jq`, re-rooted at `.digest`. The wrapper mirrors the
  vendor's stderr verbatim, so a forged digest LINE on stderr is possible; the
  file is a channel the vendor process never touches.
- A hit in `files_read` means the tool call SUCCEEDED; a failed or denied attempt
  lands in `read_attempts` with an `outcome` and a `class`, and does not prove a
  read. Across retries the per-attempt digests are MERGED, so a retry cannot
  conceal an earlier attempt's reads.
- The `params`-value truncation (`_AGY_DIGEST_VALUE_CAP`, 200 chars) and the
  40-entry list caps are coupling points: a consumer matching a path truncates
  its own copy the same way, and a wrapper-side cap change has to reach the
  consumer too.
