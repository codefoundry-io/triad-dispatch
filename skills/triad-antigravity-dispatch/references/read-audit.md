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
| stderr `read-audit-file: <absolute-path>` | every completed call | the path just written, immediately after the digest line — the one custody line |
| the digest FILE | every completed call, success or failure | `{"meta": {cli, ts_utc, classification, exit_code, vendor_exit_code, elapsed_s}, "digest": <the digest object, verbatim>}` |

The run-log's `read_audit` key carries the same digest on FAILURE only, and stays
the repair-agent's input artifact.

## Binding the file

Set `TRIAD_READ_AUDIT_FILE=<absolute-path>` in the wrapper invocation's
environment, AT DISPATCH TIME — the evidence cannot be created afterwards. The
wrapper then writes only that path (the engine side — atomic publish, mode,
the unset default location and its prune: the plugin `README.md`
§ Read-audit digest file). Writing is best-effort: an IO failure leaves the
exit code and classification unchanged and omits the `read-audit-file:` line.

## Notes for a consuming gate

- Read the FILE with `jq`, re-rooted at `.digest` — never the stderr digest
  line: the wrapper mirrors the vendor's stderr verbatim, so a forged LINE is
  possible; the file is a channel the vendor process never touches.
- The digest's keys, the success-only `files_read` rule, the per-attempt
  `attempts[]` rows and the retry merge are the wrapper's
  (the plugin `README.md` § `antigravity_wrapper.py`, the
  read-audit digest paragraphs).
- The `params`-value truncation (`_AGY_DIGEST_VALUE_CAP`, 200 chars) and the
  40-entry list caps are coupling points: a consumer matching a path
  truncates its own copy the same way, and a wrapper-side cap change has to
  reach the consumer too.
- The review skill's gate over this file — its inputs, verdicts and remedies —
  is `triad-cross-family-review` `references/leg-contracts.md` § agy
  read-audit gate.
