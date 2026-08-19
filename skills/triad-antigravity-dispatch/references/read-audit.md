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
| stderr `read-audit-file: <absolute-path>` | every completed call | the path just written — immediately after the digest line when no override copy fires; under `TRIAD_READ_AUDIT_FILE` a `read-audit-copy:` line (below) is logged FIRST and sits between them |
| the digest FILE | every completed call, success or failure | `{"meta": {cli, ts_utc, classification, exit_code, vendor_exit_code, elapsed_s}, "digest": <the digest object, verbatim>}` |

The run-log's `read_audit` key carries the same digest on FAILURE only, and stays
the repair-agent's input artifact.

**Default-location copy (task-1, 2026-08-19 telemetry slice)** — when
`TRIAD_READ_AUDIT_FILE` is set, the wrapper ALSO writes the same digest to its
default location (`_logs/antigravity/read-audit/<UTC-ts>-<pid>-<uuid8>.json`,
self-pruned; the COPY is written mode `0600` — an override-unset call's PRIMARY digest at the same location is a plain umask-mode write) and logs one more stderr line:
`read-audit-copy: <absolute-path>` (logged BEFORE the caller's
`read-audit-file:` line — see the table above). The COPY's `meta` carries one
extra key the override file's own `meta` does not: `copied_from`, the
`TRIAD_READ_AUDIT_FILE` value it was copied from (fix wave W1 item 4) — lets
two same-day gates/rounds be told apart once a packet dir (and its override
path) is gone. Origin: a review packet dir is deleted at gate close, so the
override used to be the *only* copy of a round's digest and it was lost along
with the packet. This does NOT change what a consuming gate should bind to —
see below. **This copy is telemetry for post-hoc forensics, not a second
binding artifact** — a consuming gate never reads from this dir; it exists
so a human (or a later audit pass) can still find the digest after the
packet dir that held the override path is gone.

## Binding the file

Set `TRIAD_READ_AUDIT_FILE=<absolute-path>` in the wrapper invocation's
environment. The wrapper writes the digest to exactly that path — parent dirs
created, existing content overwritten. This **override path stays the
BINDING artifact** a consuming gate should read (the default-location copy
above is a courtesy for a consumer that always looks in the default dir, not
a second contract — its filename is a fresh uuid8 the caller doesn't control,
so it cannot be bound to a priori the way the override path can). Unset, the
wrapper writes ONLY to its own default location (self-pruned like run-logs)
as an operator convenience; no caller reads that default today. Writing is
best-effort throughout: an IO failure (override write, or the default-
location copy when the override succeeded) leaves the exit code and
classification unchanged, and the corresponding stderr line
(`read-audit-file:` / `read-audit-copy:`) is simply omitted.

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
