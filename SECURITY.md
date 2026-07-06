# Security model

This toolkit dispatches vendor CLIs (codex / gemini / agy / claude) as single-shot
workers and grows a shared error classifier over time. The classifier learns from
**vendor run-logs**, and that learning loop is the one place where an attacker's
input meets a component that could write. This document states the threat, the
control that actually stops it, and — explicitly — what is NOT the control.

## Threat model — the run-log is untrusted

When a dispatch fails in a way the classifier does not yet recognize, a repair
step reads the failing call's **run-log** (the vendor CLI's stderr / stdout /
exit code) to propose one new classifier entry. That run-log is **untrusted
vendor output**: its contents are whatever the model emitted, and a prompt or a
compromised upstream can plant arbitrary text in it.

A repair component that both READS that untrusted run-log AND has WRITE authority
is a classic confused deputy. An injected run-log could try to:

- hijack the write to reach the caller's workspace (code execution via build
  scripts, git hooks, or a poisoned config the next tool run honors), or
- exfiltrate — write learned state or secrets somewhere it can be read back.

## The control — privilege separation, not model trust

The durable control is **privilege separation between reading and writing**, so
that the component exposed to the untrusted run-log has zero write authority:

- **The analyzer that reads the run-log cannot write.** It is a read-only
  analyzer. Its only output is a fixed-shape structured JSON proposal — one
  classifier delta (a `vendor_exit_map` code→class entry, or a `patterns` list
  append). It never edits a file, spawns a process, or reaches the network.
- **The write path is deterministic and LLM-free.** The proposal is applied by
  `apply_patch.py` (over `apply_classifier_patch`), a zero-LLM validator +
  applier. It re-validates every field independently — the class must be a
  meaningful-failure enum value (not `ok`/`unknown`). The validator bounds BOTH
  poison surfaces symmetrically:
    - **L1 `vendor_exit_map`** — a `vendor_exit_code` must be a positive int,
      bounded to the application-specific range `[3, 125]` (`{0,1,2}`=generic,
      `{126,127}`=shell, `>=128`=signal-death/reserved are too broad to auto-route,
      since the classifier consults the vmap before the substrings and returns
      immediately, so a poisoned code would misroute every unrelated future
      failure carrying it — a sound range, not an enumeration, so no signal-death
      code such as SIGSEGV/SIGPIPE/SIGABRT can slip through an incomplete list),
      AND its class must be vendor-exit-DERIVABLE (a wrapper/status class such as
      `timeout`/`schema-fail`/`task-blocked` cannot be inferred from a raw vendor
      exit code).
    - **L2 `patterns` substring** — the pattern-list name must be a known list AND
      the class must be the one that list actually yields; the literal is lowercase-
      normalized (matching how the classifier lowercases the blob) then bounded above
      and floored below a minimum length with alphanumeric signal required.
  The free-text `reason` is length-bounded, and the per-cli entry count is capped —
  takes a file lock, and writes atomically. An invalid or hostile proposal leaves the classifier file
  untouched. The applier is the ONLY writer to the persistent classifier
  extension (`~/.config/<product>/classifier-patches.json`).

Because the reader has no write authority and the writer runs no model, an
injected run-log cannot hijack code execution or exfiltration — those are fully
closed by privilege separation. The validator additionally blocks the worst
structural abuses on BOTH poison surfaces symmetrically — the L2 substring (length
floor + alphanumeric signal + lowercase-normalize + pattern↔class match) AND the L1
`vendor_exit_map` (bounded to the application-specific range `[3, 125]` + restricts
to vendor-exit-derivable classes), plus mapping a failure to `ok`/`unknown`, an
exit-0 or negative code, and unbounded growth. What the deterministic validator does NOT fully
guarantee is fine-grained CORRECTNESS of an in-bounds proposal: a specific, validation-
passing entry (a plausible substring, or a specific non-generic exit code with a
vendor-error class) could still assert a wrong-but-plausible mapping and route some
genuine failures to the wrong (already-valid) class. That residual worst case is a
persistent routing MIS-classification — an integrity/robustness issue, NOT code
execution or exfiltration — and it is bounded by the read-only analyzer's judgment
plus owner review of the applied deltas, not claimed as a hard deterministic control.

## Per-product enforcement

The two products enforce the read/write split with different mechanisms, matching
their host:

- **claude-host** (Claude Code leader). The repair analyzer runs IN-SESSION as a
  subagent whose tool allowlist is **harness-enforced** to `Read, Grep, Glob` —
  no Write, Edit, Bash, or network. It literally cannot write. It returns the
  inline proposal; the leader applies it by running `bin/apply_patch.py`. The
  privilege boundary is the harness tool allowlist plus the deterministic applier.

- **codex-host** (codex leader). A codex subagent inherits the leader's sandbox
  and cannot be confined by an agent file, so this product ships **no in-session
  repair worker at all**. Instead, on a novel `unknown` error the dispatch SKILL
  surfaces a top-level `codex exec -s read-only` analyzer command the owner runs
  in a **fresh terminal**. `-s read-only` is a hard read-only sandbox — the
  analyzer cannot write — and its proposal is piped to `bin/apply_patch.py`, the
  same deterministic applier. The generated profile also pins
  `features.multi_agent = false` as a defensive backstop so no stray subagent can
  be spawned. The privilege boundary is the top-level read-only sandbox plus the
  deterministic applier.

## What is NOT the control

- **"The model resists prompt injection" is NOT the security boundary.** Any
  observation that a model tended to ignore injected instructions is anecdotal
  (small-n) and version-dependent, not a control. The boundary does not depend on
  the analyzer "behaving" — it holds because the analyzer has no write authority
  and the writer runs no model.
- **The toolkit never manages authentication.** It issues no tokens, refreshes no
  credentials, and injects no API keys. Vendor login is the owner's, done with
  each vendor CLI's native login. An auth-shaped error is surfaced for the owner
  to re-login; the toolkit never tries to re-authenticate on its behalf. Keeping
  credentials entirely outside the toolkit is itself a safety boundary.

## Reporting

Report security-sensitive issues on the product's issue tracker with the title
prefixed `[security]`. Do not include secrets or tokens in the report body.
