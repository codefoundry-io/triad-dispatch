# agy terminal (65) causes — what the leader surfaces

Each of these is already matched at the wrapper layer, so none of them routes to
the repair agent (Hard rule 4): only `unknown` / `extraction-error` do.

| cause | what to tell the user |
|---|---|
| `cli-subscription-cap` | quota — daily reset, or re-dispatch later |
| `token-limit` | prompt size too large — shrink the prompt |
| `oauth-env` | STOP — re-login required through the CLI's own browser flow; no retry, no other route, the credential store is never read; auth stays user-managed |
| `config-conflict` | either `agy --version` probed below `_STREAM_JSON_FLOOR`, where the wrapper fails CLOSED before any vendor dispatch (remediation: `agy update`, then re-dispatch), or the run's exposed runtime model (`init.model`) contradicts the pinned `--model` — the answer is withheld and the stderr line names both; the user changes the roster entry (or `--model`), the leader never substitutes a model |
| `admission-refused` | the v2 admission census found a tool OUTSIDE the agent's allowlist in the stream (the allowlist class only; other refusals stay `vendor-error`); the complete answer is quarantined in the run-log. Driver-emitted, never a classifier patch — surface, one retry at most. |
| `vendor-timeout` | the stream's terminal `result` is `status: ERROR` with the typed `error` "timeout waiting for response" and an empty response — agy's own turn budget ran out. Driver-emitted (`_is_vendor_turn_timeout`), never a classifier patch; surface, one narrower re-dispatch at most. |
| `vendor-error` | the stream's terminal `result` event carried a non-empty answer WITH rc≠0 or a non-`SUCCESS` status. The answer is deliberately NOT on stdout: it survives only in the run-log's quarantined `extraction_error` copy and the raw NDJSON stream, which the leader does not open (Hard rule 2). Surface the classification token + exit codes and name the run-log path; a human can read it out of band to decide re-dispatch vs accept |

`config-conflict`'s floor gate is a deterministic pre-dispatch check and
`vendor-error` is driver-emitted on the answer-present path — neither is
something a classifier patch could express, which is why they stay out of the
repair branch.
