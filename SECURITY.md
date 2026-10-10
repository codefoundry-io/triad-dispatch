# Security model

This toolkit runs on the Claude Code host: the Claude Code session is the leader,
and it dispatches the vendor CLIs codex, gemini and agy as single-shot workers. It
also grows a shared error classifier over time from the **vendor run-logs**. This
document states the threat model, the control that keeps that learning loop from
writing anything it should not, and — explicitly — what is NOT the control.

## Threat model — one operator, and vendor output is not ours

The toolkit serves one operator, and there is no malicious actor. Its guards defend
against ordinary failures: a full disk, a stop at any point, a wrong argument, a
bad vendor answer a run has shown, an operation started from another folder (or by
the other host's toolkit) meeting the same machine-level files, and a reviewer's
or the leader's mistake.

When a dispatch fails in a way the classifier does not yet recognize, a repair
step reads the failing call's **run-log** (the vendor CLI's stderr / stdout /
exit code) to propose one new classifier entry. The run-log is vendor output the
toolkit did not write: a model's answer, a quoted web page or a vendor message can
put any text in it, and a misreading of that text must never become a write
anywhere but the classifier file.

## The control — privilege separation, not model trust

The durable control is **privilege separation between reading and writing**: the
component that reads the run-log has zero write authority.

- **The analyzer that reads the run-log cannot write.** It is a read-only
  analyzer. Its only output is a fixed-shape structured JSON proposal — one
  classifier delta (a `vendor_exit_map` code→class entry, or a `patterns` list
  append). It never edits a file or spawns a process. Its only network reach is
  bounded research (`WebSearch` / `WebFetch`): a query carries only sanitized
  error text and version context — never a credential, private prompt or source
  content, or the full run-log — and a search result never proves an error the
  run did not show.
- **The write path is deterministic and LLM-free.** The leader applies the
  proposal with `bin/apply_patch.py`, a zero-LLM validator + applier and the only
  writer of the classifier extension (`~/.config/<product>/classifier-patches.json`).
  It holds the lock file beside that file for the whole read-validate-write cycle
  and writes atomically. It refuses every `oauth-env` proposal (authentication is
  the operator's to fix through the vendor CLI's own login), a class of `ok` or
  `unknown`, an exit code outside `[3, 125]` or paired with a class a vendor exit
  code cannot carry, and a fragment that is not 4 to 200 characters long with a
  letter or digit in it or that names a pattern list yielding another class. A
  refused proposal leaves the file untouched.

Because the reader has no write authority and the writer runs no model, a run-log
cannot turn into code execution or a write outside the classifier file. What the
validator does not guarantee is that an in-bounds proposal is RIGHT: a plausible
fragment or a specific exit code can still map some failures to the wrong
(already-valid) class. That worst case is a persistent routing MIS-classification
— an integrity issue, not code execution — bounded by the analyzer's judgment and
the operator's review of the applied deltas.

## Enforcement on the Claude Code host

The repair analyzer runs IN-SESSION as a subagent whose tool allowlist is
**harness-enforced** to `Read, Grep, Glob, WebSearch, WebFetch` — no Write, Edit,
Bash, or Agent. It returns the inline proposal; the leader applies it by running
`bin/apply_patch.py`. The privilege boundary is the harness tool allowlist plus
the deterministic applier.

**Agent-name collision.** Claude Code resolves a project's own agent at
`.claude/agents/<name>.md` over a plugin agent of the same bare name. The shipped
dispatch skills therefore spawn the analyzer by its plugin-scoped name
(`triad-dispatch:<name>-wrapper-repair`), which resolves to the plugin's read-only
agent, and they have the leader confirm, before the dispatch, that the resolved
analyzer's tools are only `Read, Grep, Glob, WebSearch, WebFetch` — a same-named
agent with other tools is refused.

## Intent-gated broad-capability surface (accepted residual)

The leader (Claude Code) is **user-driven**, and this toolkit lets it
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

The always-on layers below are what DOES apply; they guard against ordinary
mistakes and odd vendor output, not against the user:

- **Privilege separation** on the repair path (above) — the component that reads
  the run-log has zero write authority.
- **Wrapper roots-containment** — `--prompt-file` / `--image` / `--cwd` are
  confined to the configured workspace roots under the hardening env
  (`TRIAD_WRAPPER_HARDENED=1`) that the setup writes.
- **The Bash grants** — no layer of their own. The plugin-path Bash grant
  (`Bash(python3 <plugin>/*/bin/codex_wrapper.py *)`, `<plugin>` = the installed
  plugin's directory in the plugin cache, `*` = its version) runs the plugin's own
  file without asking; so do the review library's leg lines
  (`Bash(env TRIAD_REVIEW_LOG_DIR=* python3 <plugin>/*/bin/<wrapper> *)`, the agy
  line with `env TRIAD_READ_AUDIT_FILE=*` before it) and the library files the
  review skill has the leader run
  (`Bash(python3 <plugin>/*/skills/triad-cross-family-review/lib/<module> *)`,
  and `Bash(bash <plugin>/*/skills/triad-cross-family-review/lib/read_audit_gate.sh *)`
  for the agy read-audit gate). A leg line carries its shell redirections inside
  a noclobber-guarded subshell, and the claude leg's `guard:` line is shell
  built-ins with no grant; Claude Code approves such parts separately from any
  Bash rule, so an installed review round asks once per leg (measured 2026-10-11
  for the redirection; the subshell and built-in parts not measured). Recorded
  limit: an env-prefixed grant's `=*` matches any text up to the plugin path, so
  a line with a second assignment before `python3` (for example `PYTHONPATH=…`)
  would also run without asking — the same class as the version `*`; not
  measured live; the plugin's environment assumes one operator.

Those layers are the security posture. The broad promptless capability is the one
item we accept and document rather than harden: hardening it would over-restrict
the user's own intent.

## What is NOT the control

- **"The model resists prompt injection" is NOT the security boundary.** Any
  observation that a model tended to ignore injected instructions is anecdotal
  (small-n) and version-dependent, not a control. The boundary does not depend on
  the analyzer "behaving" — it holds because the analyzer has no write authority
  and the writer runs no model.
- **The toolkit never manages authentication.** It issues no tokens, refreshes no
  credentials, and injects no API keys. Vendor login is the operator's, done with
  each vendor CLI's native login. An auth-shaped error is surfaced for the operator
  to re-login; the toolkit never tries to re-authenticate on its behalf. Keeping
  credentials entirely outside the toolkit is itself a safety boundary.

## Reporting

Report security-sensitive issues on the product's issue tracker with the title
prefixed `[security]`. Do not include secrets or tokens in the report body.
