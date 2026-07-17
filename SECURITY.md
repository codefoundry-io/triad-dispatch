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

## Project-agent shadow (claude-host) — a second confused-deputy path

The claude-host privilege boundary above assumes the repair analyzer that runs
is the shipped **read-only** plugin agent (`tools: Read, Grep, Glob`). A second
way that assumption can break is **agent-name shadowing**. Claude Code resolves a
consumer's own project agent at `.claude/agents/<name>.md` **over** a plugin agent
of the same bare name. So if the dispatch skill spawned the analyzer by the bare
`subagent_type` (`codex-wrapper-repair`), a consumer who happens to have — or is
tricked into adding — a same-named **writable** project agent would have THAT
agent, with its own tools, read the untrusted run-log: the confused deputy
re-opens, this time through the harness's agent-resolution order rather than the
analyzer's own grants.

The mitigation is two-layered:

- **Address the plugin agent by its plugin-scoped identity.** The shipped
  dispatch skills spawn the analyzer as `triad-dispatch:<name>-wrapper-repair`
  (the export injects the `triad-dispatch:` scope; the source repo, which has no
  plugin, keeps the bare project-agent name). The scoped identity resolves to the
  plugin's read-only agent unambiguously, so a same-named project agent cannot be
  what runs.
- **Confirm read-only before dispatch (product-agnostic).** Because a consumer
  can still install agents the toolkit does not control, the skill also instructs
  the leader to CONFIRM the resolved analyzer's tools are only `Read, Grep, Glob`
  before dispatch and REFUSE if a same-named writable agent shadows it — a check
  that needs no plugin name and also covers the source/dev repo (project agent,
  no scoping).

The **codex-host** product is structurally immune to this path: it spawns no
named in-session subagent at all — the analyzer is a top-level
`codex exec -s read-only` command in a fresh terminal — so there is no
`subagent_type` a project agent could override.

## Intent-gated broad-capability surface (accepted residual)

The leader (Claude Code, or codex) is **user-driven**, and this toolkit lets it
dispatch a wrapper with broad arguments once the install leg allow-lists the
wrapper command (so the user is not re-prompted on every dispatch). That broad,
promptless capability is a **documented residual, deliberately not hardened**.

The reason is the threat model, not an oversight. A user-issued action is
**intent, not an attack**: when the user tells the leader to run a wrapper with
some argument, that is the user doing what they could already do directly at a
shell. Allow-listing only removes a repeated approval prompt — it grants no
capability the user did not already have. Hardening this surface would therefore
restrict the **user's own legitimate use** more than it protects them: it blocks
often, protects rarely. So we do not split, gate, or auto-revoke the capability.

What this residual is NOT is a free pass for *untrusted* input. The durable,
always-on controls below are the defense-in-depth layers that DO apply — and
they are aimed at the real distributed threats (untrusted content injected into
the leader, and a poisoned parent-start environment), not at the user:

- **Privilege separation** on the repair path (above) — the component that reads
  the untrusted run-log has zero write authority.
- **Wrapper roots-containment** — `--prompt-file` / `--image` / `--cwd` are
  confined to the configured workspace roots by the shared engine, regardless of
  which product runs it.
- **Pinned vendor binary** — `TRIAD_REQUIRE_PINNED_VENDOR=1` + `TRIAD_<CLI>_BIN`
  resolve the real vendor, defeating a workspace-planted same-named binary.
- **Audit redaction** — `TRIAD_AUDIT_REDACT_PROMPTS=1` keeps prompt/stream text
  out of the durable audit.
- **claude-host** — a **PreToolUse hook** validates each wrapper invocation and
  resolves-and-rejects a foreign same-named script on PATH (the reliable gate the
  basename Bash grant defers to).
- **codex-host** — `[shell_environment_policy] inherit = "core"` in the merged
  config drops loader/interpreter injection vars (`LD_PRELOAD`, `NODE_OPTIONS`,
  `PYTHONPATH`, …) from every subprocess codex spawns, closing the
  parent-start-env boundary the launcher's own scrub cannot reach.

Those layers are the security posture. The broad promptless capability is the one
item we accept and document rather than harden, because its only reachable abuse
is via untrusted-content injection into the leader — for which the layers above
are the defense — and hardening it would over-restrict the user's own intent.

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
