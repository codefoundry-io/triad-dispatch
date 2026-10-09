# Cross-family review — per-leg dispatch contracts

Loaded on demand from `triad-cross-family-review/SKILL.md`. Read this when
dispatching a round's legs (Flow step 2), and again when an agy leg returns —
its verdict may be weighed only after the read-audit gate below passes.

## Contents

| Section | Open it when |
|---|---|
| v2 dispatch shapes | reading or sanity-checking the argv `prepare` printed for an entry |
| Producer schema projection | asking what schema the vendor received, or why it differs from the canonical one |
| Verdict binding — all legs | dispatching any leg, or admitting a returned verdict |
| Google-family leg selection | resolving a google entry's route (agy; gemini = legacy compatibility) |
| agy leg | dispatching agy — model selector, read-audit binding, containment block |
| agy read-audit gate | an agy leg returned and you are about to weigh it |
| agy standing residuals | deciding whether this deployment can run the agy leg at all |
| gemini leg | a google entry resolved to the gemini route (legacy compatibility) |
| codex leg | dispatching codex — tier, review web (`--search`), worktree delivery |
| claude fresh-eye leg | dispatching the claude `Agent` leg |

## v2 dispatch shapes

`prepare` PRINTS the complete invocation for every enabled non-skipped
roster entry; the leader runs those lines verbatim. The shapes below are what
`lib/roster_v2.render_dispatch` builds, so a printed line that does not match
one of them is a defect worth stopping on. `<attempt>` =
`<packet-dir>/results-r<N>/<name>/attempt-<K>`. Every path token is ABSOLUTE
in the rendered argv (the renderer refuses a relative one), and every wrapper
argv ends with the same tail: `--prompt-file <attempt>/prompt.txt --cwd
<worktree> --timeout <entry timeout_s> --attempt <K>`.

**Every wrapper line runs with `env TRIAD_REVIEW_LOG_DIR=<attempt>/logs`, and the
wrapper's run-log is the attempt's receipt (R-BIND).** A line edited before it
ran still runs; `collect` compares its receipt with the recorded argv and
makes the entry INVALID. A line run without that env member writes no
receipt, and `collect` makes the entry INVALID too — a recorded known limit
(owner, 2026-10-03). The line's own redirections have created that attempt's
output files, so `retry` the entry and run the new attempt's printed line
verbatim. With the log-dir member
the wrapper writes its run-log on success too, into `<attempt>/logs/<cli>/runs/`
(`<cli>` = `codex` / `antigravity` / `gemini`), and its `wrapper_cmd` is the
argv the wrapper actually ran with. `collect` compares every run-log there with
`dispatch.json`'s argv before it admits the answer: a missing run-log (the line
ran without its env) or any differing element — a removed `--search` /
`--review-web`, a changed `--model` — makes the entry INVALID ("the leg ran
with a command other than the recorded one"), sealed so; `retry` it and run its
printed line verbatim; the entry's line shows the answer the leg gave beside
that reason. The run-log directory joins the attempt's seal (role `run_log`,
digested over its `*.json` run-logs only — exactly the files the receipt reader
reads, so an OS side file there changes nothing), so a later change, removal or
unreadable run-log of a SEALED attempt is an integrity failure whose remedy is a
new round (`retry` refuses an attempt whose sealed files changed); an unsealed
attempt's unreadable run-log names `retry`. An attempt sealed with a valid
answer is never re-judged by the argv comparison (C66). A seal written before
this binding (no `run_log` role) names a new round. The wrapper entry's early `admit:` line
admits the answer alone and says so on stderr; the receipt is `collect`'s.
The native claude spawn has no wrapper and so no receipt (DL-18).
The model pin and the agy effort ride as ONE option token each (`--model=<v>`,
`--effort=<v>`), so a value shaped like an option (`--help`, `-x`) reaches the
wrapper verbatim; the gemini and agy wrappers pass it on in the same one-token
form, codex as its one `-c model="<v>"` token.

- **codex** — `env TRIAD_REVIEW_LOG_DIR=<attempt>/logs python3
  <wrappers>/codex_wrapper.py --sandbox read-only
  [--search] [--reasoning <tier>] [--model=<slug>] --output-schema-file
  <attempt>/schema.projected.json` + the common tail, redirected to
  `<attempt>/verdict.json` and `<attempt>/stderr.log`. `--search` follows
  the round's bound `review_web_authorized` (R-REVIEW-WEB; true under the
  owner's standing authorization, so present on every round today; absent on
  a false round, where the wrapper pins `web_search="disabled"`). Never
  `--pydantic`: v2 admission runs on the output FILE, in `verdict_v2.py`.
- **agy** — `env TRIAD_READ_AUDIT_FILE=<attempt>/read-audit.json env
  TRIAD_REVIEW_LOG_DIR=<attempt>/logs python3
  <wrappers>/antigravity_wrapper.py --sandbox read-only [--review-web]
  [--model=<slug>] [--effort=<tier>] --json-schema-file <attempt>/schema.projected.json` + the
  common tail, same redirections. A true `review_web_authorized` adds
  `--review-web` — the read-only research agent (the review tools plus
  `read_url_content` / `search_web`) WITHOUT the investigation web-evidence
  clause — and `prepare` writes the round's hook in its web mode; never the
  investigation `--web` (R-INVEST). The per-attempt read audit is part of
  this entry's contract, gated below.
- **gemini** — `env TRIAD_REVIEW_LOG_DIR=<attempt>/logs python3
  <wrappers>/gemini_wrapper.py --sandbox read-only
  --approval-mode default [--review-web] [--model=<slug>]` + the common tail
  (`--review-web` on a true `review_web_authorized`: the complete review web
  profile `policies/gemini-readonly-web.toml` instead of
  `gemini-readonly.toml`, never an overlay, no investigation clause). NO schema
  slot: the gemini route has no native producer-schema argument on host A, so
  the verdict SHAPE is pinned by the prompt text alone and admission is the
  only mechanical check. Never an `--effort` flag (the wrapper has none; the
  resolver refuses a `gemini.effort` value). The gemini route is
  compatibility with the older gemini CLI (legacy compatibility), not a
  standing review leg; this shape is a textual pin, not a measured one.
- **claude** — no wrapper. Spawn `Agent` with EXACTLY the `subagent_type`
  the dispatch line prints (from `dispatch.json`) and no `model` parameter
  (the Agent tool's per-call `model` outranks the preset's `model`
  frontmatter, so passing one replaces the pinned model) on the CONTENT of
  `<attempt>/prompt.txt` — the renderer derives it from the entry's
  `claude.agent`: under a true `review_web_authorized` the preset's web twin
  (`-web` / `-high-web` / `-max-web`), under a false one the
  no-web base preset (`roster_v2.render_dispatch`, `CLAUDE_WEB_TWINS`) — save
  the final message VERBATIM to `<attempt>/raw.json`, then admit with
  `verdict_v2.py --admit … --end-marker '<END-VERDICT>' --admitted-out
  <attempt>/admitted.json`. The admit line types no `--expected-*` value: it
  takes the six from `<attempt>/binding.json` beside the reply; a typed flag
  that disagrees with that record is an argument error (exit 64) that seals
  nothing.
  **The printed agent id is LAYOUT-QUALIFIED**
  (`review_scratch._qualify_claude_agent_id`). In a DIST
  (plugin) install a BARE id is scoped to `<plugin>:<agent>`, with the plugin
  name READ from `.claude-plugin/plugin.json` — an unreadable, non-JSON or
  name-less manifest inside a plugin install is a HARD REFUSAL, never a
  fall-through to the bare name, because a consumer's same-named PROJECT
  agent resolves over a plugin agent and would silently shadow the read-only
  reviewer. In the DEV tree there is no manifest and the bare name is the
  correct id. The ROSTER DATA is always BARE: `claude.agent` names one of the
  six presets this host ships (`roster_v2.CLAUDE_WEB_TWINS`, the closed list —
  SKILL rule 15), and any other value — a `:`-scoped id, an unlisted name, a
  name with a trailing newline or any other byte — is refused at resolve
  (`roster_v2._check_capabilities`), so nothing but a listed name ever reaches
  the spawn instruction. The qualification happens at render time, in
  `_v2_dispatch_json`, and `v2_print_dispatch` reads the id back OUT of
  `dispatch.json`, so the printed line and the round record cannot disagree.
  **A missing `subagent_type` in the RECORD is a refusal, never a default**
  (`review_scratch.v2_print_dispatch`). The print reads the id back out of
  `dispatch.json`, and falling back to the layout default when the record
  carries none would print the GATING reviewer under some other leg's name —
  the exact confusion the null-`claude.agent` refusal exists to prevent. A
  record that cannot name its own agent is a broken record: `v2_print_dispatch` FAILS
  naming the record path (`… names no subagent_type (<attempt>/dispatch.json)
  — … the layout default is the GATING reviewer and is never substituted for
  a missing one. Prepare a new round`).
  A non-null `claude.effort` or `claude.model` is REFUSED by the resolver
  (`roster_v2._check_capabilities`, mirroring the `gemini.effort`
  refusal beside them): the native `Agent` dispatch names a `subagent_type`
  and passes no effort (the tool has no effort parameter) and no `model`
  (a per-call model outranks the frontmatter), so BOTH the effort tier and
  the model are pinned INSIDE the named agent preset's frontmatter and a
  different tier or model is a DIFFERENT SHIPPED preset, named by its bare
  name (effort has no per-invocation override; the closed list and the guide:
  SKILL rule 15).
  A roster that records an effort or a model
  the dispatch cannot apply is a lie frozen into the round record, so both
  fields must be null on host A.
  **Admission of the saved reply** — the end marker decides which text is
  admitted, and it is the only thing that decides it
  (`verdict_v2._marker_needs_unescape` / `_admit_raw_with_text`). Final non-empty line IS the literal marker → RAW
  FIRST, byte-exact, so a reply whose string fields legitimately spell HTML
  entities is admitted unchanged; the single `html.unescape` retry runs ONLY
  when that raw pass failed to PARSE and entity tokens are present (a raw
  pass that parsed and then failed the schema or the duplicate guard is
  FINAL — unescaping could restructure the object into a DIFFERENT document
  than the leg sent). Final non-empty line is NOT the literal marker but
  `html.unescape` of it IS → the TRANSPORT escaped: the WHOLE reply is
  unescaped once and admitted from that, printing `NOTICE: admitted on the
  html.unescape pass`. `html.unescape` covers every spelling it knows, so
  both the NAMED (`&lt;END-VERDICT&gt;`) and the NUMERIC
  (`&#60;END-VERDICT&#62;`) forms are recognized. No escaper spelling is
  special-cased inside the RAW pass: that would admit a body with
  `&lt;`/`&gt;` entities intact from a transport that escaped angle brackets
  but not quotes.

The Google ROUTE for a google entry is resolved per ENTRY by
`roster_v2._resolve_google`: an explicit `google.route` pin wins (missing
binary → skip that entry and log); an entry carrying exactly ONE route block
IS that route (a gemini-only entry does not become an agy entry because agy
happens to be installed); only an entry carrying BOTH blocks falls through
the host chain agy → gemini; neither installed → skip that entry and log.
Every unusable outcome skips THAT ENTRY, never the roster, and a skip is
never agreement: the collector counts a SKIPPED enabled entry as `missing`,
NAMED with its skip reason, which folds the round to `INCOMPLETE` whatever its
siblings cover (`collect_v2.py` "SKIPPED at prepare and never dispatched").

**Roster drift = ONE `WARNING:` per CHANGED FIELD** (`roster_v2._drift_warnings`).
An override that moves a SHIPPED entry is never a veto (R-ROSTER keeps every
leg switchable), but every moved field — top-level and adapter-block alike —
gets its own warning carrying `old->new`, printed on stdout and frozen into
`.roster-r<N>.json`. `note` is excluded (operator prose) and `vendor` is
excluded because it is REFUSED rather than warned. Exactly one line per
change: `enabled` is both a drift field and the subject of its own dedicated
line, so when the dedicated line fires the generic one is skipped FOR THAT
FIELD ONLY (a round record that counts warnings must not read one move as two
changes); an `enabled: false -> true` move, which has no dedicated line,
still gets the generic `old->new`.

**A DUPLICATE entry name is refused over the MERGED roster, BEFORE any
mutation — both the EXACT and the CASE-FOLDED reading**. An entry name is the merge key AND becomes a
DIRECTORY name (`results-r<N>/<name>/`), so two entries sharing one name
survive the pure render and the SECOND `mkdir` then fails — on a
case-insensitive volume (the macOS default) for `codex` vs `Codex`, and
unconditionally for an exact repeat — AFTER `prepare` has already re-pinned
the round: a mutation made, then a refusal. Both readings run over `legs`
AFTER the defaults+override merge (`roster_v2._resolve`) — a repeat inside
the SHIPPED `review-legs.default.json` included — naming the offending
entries and the document(s) they came from. The override-side duplicate check still fires
FIRST for an override duplicate, so its message (the merge key must be unique)
is unchanged.

## Producer schema projection

`<attempt>/schema.projected.json` is a PROJECTION of the vendored canonical
`spec/contracts/leg-verdict.schema.json`, handed to codex
(`--output-schema-file`) and agy (`--json-schema-file`) so the producer emits
the right shape. It AIDS GENERATION and NEVER ADMITS: admission
(`verdict_v2.py`) always validates against the FULL canonical schema.

Every transform was forced by a LIVE vendor probe (measured), none
is a preference: codex rejects `not` without `type` (`invalid_json_schema`)
and the optional `correction` property; agy rejects `null` inside `enum`
(`route.enum[2]: cannot be empty`). The accepted projection is the canonical
schema minus `$schema` / `$id` / the top-level `allOf` / every `not` / every
`uniqueItems` / `correction`, with `route` re-expressed as
`anyOf[string enum, null]`. Consequence to know: a codex or agy entry cannot
emit the optional `correction` field even though the shared Google prompt
mentions it (harmless — the field is optional; the claude native entry keeps
it). `render_dispatch` is PURE — it returns the projection text and its
target path, and the ONE production writer is
`review_scratch.v2_write_attempt` (exclusive-create, so a pre-existing file
at the target is refused), called after `prepare`'s own pre-mutation
boundary; a refused prepare leaves no attempt directory behind. There is no
second writer inside `roster_v2` — `v2_write_attempt` is the only writer of
these bytes.

**The projection is a ROUND BASIS, so the round record freezes its digest.**
Because the projection is re-derived from the vendored
contract on EVERY render — a `retry`'s render included — a spec re-vendoring
between `prepare` and `retry` would hand attempt K+1 a DIFFERENT producer
schema while the round record still claimed an unchanged basis. `prepare`
therefore stores `projection_digest` (sha256 of the projected schema
bytes) in `.roster-r<N>.json`, and `retry` re-derives and compares it before
allocating; a MISMATCH — or a record carrying NO frozen digest — refuses with
"prepare a new round" (`references/triage.md` § Collect outcomes). The digest,
not the bytes: each attempt already carries its own
`schema.projected.json`.

**The answer channel the producer schema selects.** On the agy route
(`--json-schema-file`) only the MEASURED dict `structured_output` is the
answer (the response text carries agy's own finish-tool metadata, which
canonical admission then rejects as additional properties, so the channel
choice is load-bearing). Any other shape — the key ABSENT, or a present but
non-object value, an explicit `null` included — is treated as absent: the
logged response text is printed, which stays legitimate only because
canonical admission gates whatever arrives. The SAME membership test holds on
the wrapper's other arm, `--pydantic`
(`antigravity_wrapper._validate_structured_detail`) — v2 review entries
do not use that arm, but the rule is one rule. For a leg a 66 on the agy
schema-file route means a duplicate JSON member (C14) — terminal for that
attempt (`retry`, never a repair dispatch).

A result carrying a VALID structured channel is admitted even when `response`
is EMPTY: the structured channel is evaluated BEFORE the empty-answer guard,
so an agy entry whose verdict rides only in `structured_output` never loses
its answer to an `extraction-error` / `empty-answer-body` discard.

**Test seams are gated.** `TRIAD_ROSTER_WHICH` (the roster's binary probe)
and the prompt renderer's spec-dir seam are honored ONLY when
`TRIAD_TEST_SEAMS=1` is set beside them, and each announces itself once on
stderr. Production can never have its binary probe or its clause source
redirected by a stray environment variable.

## Verdict binding — all legs

`LegVerdict` carries six REQUIRED binding fields — `review_id`, `family`
(`claude` | `google` | `codex`), `content_digest` (64-hex, lowercase),
`leg_name`, `attempt`, `route` — so a verdict is admissible only for the
exact round, entry and attempt it was produced for (no cross-round reuse, no
leg mixups). The leader's obligations, every round, every entry:

1. Every attempt's `binding.json` states the six values, and the entry's
   `prompt.txt` tells the leg to ECHO them verbatim. `content_digest` is the
   sha256 of the round's delivery record `delivery-r<N>.md` (it cannot live
   inside the record it hashes). Per-entry `family` token mapping (fixed):
   the claude fresh-eye leg echoes `"claude"`, the codex leg `"codex"`, and
   the Google-family leg — WHICHEVER CLI resolved, agy or gemini — echoes
   `"google"` (the token names the model family, not the CLI).
2. Admission is MECHANICAL: the printed `admit:` line runs `lib/verdict_v2.py`
   with all six `--expected-*` flags (`--expected-packet
   <packet-dir>/delivery-r<N>.md` derives the digest from the record's own
   bytes; `--expected-content-digest <hex>` is the mutually-exclusive raw
   form). The binding flags are all-or-nothing and an admission never runs
   shape-only (SKILL rule 4, Flow 3). A mismatch makes the entry invalid; a
   new answer needs `retry` or a new round — never a hand-waved pass.
3. The schema also rejects a "SAFE TO MERGE" verdict carrying a
   Critical/must-fix finding (bidirectional validator, engine commit
   `397fade`); Minor / HARDENING-SUGGESTION findings MAY accompany
   SAFE — a deliberate difference from the codex-host reference, which
   has no suggestion severity.
4. **A schema-fail preserves the leg's evidence — it is never a silent
   leg loss.** Every schema-validation failure of a leg reply takes the
   wrapper's ONE schema-repair retry; nothing is gated on the reply's
   content. The single exception is a duplicate JSON member (C14): it is
   never repaired — the wrapper exits schema-fail 66 and logs
   `schema validation non-repairable (duplicate JSON member) — skipping
   repair retry`. On a 66 the run-log preserves the FULL vendor evidence:
   the vendor's `structured_output` rides the run-log's `stdout` stream;
   `final_answer` is EMPTIED where the wrapper quarantines it (a duplicate
   member, or a present `structured_output` that suppressed the raw
   fallback), and the bounded copy of the raw string lives in the
   run-log's `extraction_error` as "quarantined answer: …" — so inspect
   the stdout stream plus `extraction_error`, never `final_answer`. A 66
   is NEVER a reply to fall back to: the leg's captured `.out` must not be
   consolidated on any 66. The leader re-dispatches the leg ONCE
   (`retry`); only a leg still failing after that one re-dispatch is
   terminally missing (rule 13), and the round record then names the
   run-log so the evidence is never dropped on the floor — for the
   ADVISORY Google leg as much as for a gating leg.
5. **A SCHEMA-LOAD failure of ANY class is a HOST FAULT (exit 64), never a
   leg verdict**. `verdict_v2._get_validator` reserves
   exit 64 for "this install cannot admit ANY reply", and that covers
   every way the vendored canonical schema can be unusable: absent
   `jsonschema`, an unreadable file, INVALID UTF-8 (`UnicodeDecodeError` — a
   `ValueError`, not an `OSError`), a non-JSON document, one nested past the
   interpreter's limit (`RecursionError` — neither), and a document that is
   not a valid Draft 2020-12 schema — none of them escapes as a TRACEBACK
   out of the one path the collector's exit-64 `_HostFault` depends on.
   Every one of them says the same thing — this host cannot
   judge any reply — so the collection STOPS and writes no per-entry state
   (`references/triage.md` § Collect outcomes).
6. **A prompt the host cannot encode is a one-line refusal, never a
   traceback**. `prompts_v2._emit_payload` refuses a
   render carrying a value this host cannot represent as UTF-8 — a binding
   value with surrogateescape bytes, an argv token decoded under an ASCII
   locale — and the command exits **2** with the named reason, the same rule
   `review_scratch._emit_payload` applies to the dispatch lines. The clause
   bytes are what the round record's manifest digests and
   what the leg receives, so they are never escaped or partially written:
   rename the offending path or render under a UTF-8 locale.

## Google-family leg selection

agy and gemini share the Gemini backend, so both routes are the one `google`
family; each google entry resolves to exactly ONE route. The gemini route is
compatibility with the older gemini CLI (legacy compatibility).

**The resolver does this** — `roster_v2._resolve_google`, per
ENTRY, no AI judgment and no env knob: explicit `google.route` pin → the
entry's SINGLE route block when it carries only one → the host chain agy,
then gemini → skip that entry and log. A missing binary at any step skips
THAT ENTRY (never the roster) and is never agreement; the resolved route is
frozen into `.roster-r<N>.json` for the attempt, and a started entry never
switches route. The model/effort values come from that entry's `agy` /
`gemini` block (§ v2 dispatch shapes).

**Model rule (R-MODEL).** The model is the roster entry's value, passed to
the wrapper as given: the host runs no catalog probe
(`agy models` / `gemini models`) and never substitutes or falls back to another
model. A model the CLI refuses ends the attempt as a terminal failed-to-run
record; the user changes the roster entry. The agy stream's `init.model` is
recorded as `runtime_model`, and a value that is not byte-equal to the requested
`--model` is refused (`config-conflict` 65, answer withheld).

## agy leg

A round's agy `prompt.txt` is rendered from the vendored clauses
(`spec/prompts/leg-google.md` — its `google-read-grant` and shape clauses).

- **Read-only path v2 (wrapper-side).** The agy
  leg runs as the setup-once tools-allowlisted agent `triad-readonly-review`
  (`--agent`; view_file / grep_search / list_dir / find_by_name / finish —
  NO web tool) with `--add-dir <cwd>` for repository reads; no danger flag,
  no settings deny transaction, no agy `--sandbox`. **Caller obligation:
  pass `--cwd <absolute root the leg's reads must resolve in>` — the wrapper
  forwards it as `--add-dir`, the leg's ONLY read grant, and ENFORCES it
  (owner ruling): a review dispatch without `--cwd` is refused
  `EXIT_ARG_ERROR` before any vendor work (a grant-less dispatch reads
  blind).
  Symmetric with the codex leg's rule-9 READ-GRANT + `--cwd` duty; build the
  value from the real cwd read at dispatch time (`pwd`), never an assumed
  session directory.** The host runs
  `antigravity_wrapper.py
  --setup-agents` once (a missing/drifted file is
  `config-conflict` naming it). **`--setup-agents` prints the written agent
  paths and its permission hint as PAYLOAD BYTES**:
  `_emit_payload(os.fsencode(path))`, so a non-ASCII agents directory
  reproduces its on-disk bytes exactly and the command cannot die at exit 1
  on a setup that already SUCCEEDED (the plugin `README.md` § Payload
  vs diagnostic streams). Admission is the wrapper's `admit()`: framing,
  one result, allowlist census over every attempt, and a
  `status != SUCCESS` run whose verdict validates and whose errored steps
  are all allowed reads is ADMITTED (stderr `admitted-with-errored-steps`);
  the mechanical read-audit gate below runs UNCHANGED over such a run.
  Evidence: `docs/spikes/2026-08-22-agy-permission-ladder/` rounds 1-3; spec
  `docs/superpowers/specs/2026-08-22-agy-readonly-v2-spec.md`. Expected
  read-audit: `commands=0 writes=0 web=0` (a web round's `--review-web` leg
  runs the research agent instead, so `web` may be above 0 and errored steps
  of its two web tools are admitted); `denied` may
  list hook-BLOCKED calls — logged, not voiding (bullet below).
- **Tool-allowlist instruction + `admission-refused`.**
  The agent's `tools:` list is NOT a model-visible restriction on agy
  1.1.25/1.1.26: the stream's `init.tools` advertises the FULL registry (57
  tools, `manage_task` / `run_command` / `write_to_file` / `send_message` /
  browser included) to `triad-readonly-review`; only the wrapper's census
  refuses, AFTER the answer exists (measured cost without the instruction,
  `_logs/antigravity/audit.jsonl`: 110 refusals, 33 of them discarding a
  COMPLETE LegVerdict). Two carriers state the rule the census
  enforces — the round's `prompt.txt` (the vendored `google-read-grant`
  clause) and the agent body written by `--setup-agents`
  (`_allowlist_rule`, pinned by `t28-agy-agent-mode.sh`; a host must re-run
  `antigravity_wrapper.py --setup-agents` after
  an upgrade that changes the agent body, or every dispatch fails
  `config-conflict` naming the file). The allowlist refusal itself is the
  DISTINCT classification
  **`admission-refused`** (exit 65, surface-not-repair — the allowlist class
  only; framing / unexplained-degraded / read-blind refusals stay
  `vendor-error`; `t38-agy-admission-refused.sh`): stderr
  `[wrapper] antigravity admission-refused …`, run-log `extraction_error`
  "admission refused: tool(s) outside the allowlist … quarantined answer
  (N chars)". Standing handling keys on the token: ONE retry of the leg,
  a second `admission-refused` in the same round = terminally missing
  (rule 13); never a repair-agent dispatch. A forbidden run is
  `admission-refused` naming the tool whatever run-level signal rides along
  (a capacity or cap sentence, agy's own turn timeout) — one dispatch, no
  annotation; only agy's own auth carrier STOPs first as `oauth-env`. Count
  it as an allowlist slip in the round log. **Policy D (owner ruling):
  a complete verdict whose only forbidden call was
  `manage_task` (no fs / network effect) stays REFUSED — fail-closed.**
  Basis: the instruction gap was the cause (3/3 measured live runs under the
  instruction made 0 forbidden attempts), and a model that ignores the
  allowlist rule is itself a compliance signal the census must not launder.
  Re-evaluation trigger: `admission-refused` recurring under the allowlist
  instruction (audit rows), at which point the shape is a NEW defect, not a
  policy relaxation. **The trigger has FIRED** (agy 1.2.2, Pro `--effort
  high`, research agent active in the stream: two consecutive
  `admission-refused` on an identical packet, both `manage_task`, read-audit
  PASS both times — `docs/reviews/2026-09-18-cfr-skill-history.md`). Policy D
  stays fail-closed; the shape is a NEW defect class (skill backlog B4:
  drop `manage_task` from the review / research agents' advertised tool list
  if agy exposes a per-agent schema, else an explicit never-call sentence in
  the allowlist block).
  **Vendor narrowing (agy 1.1.26 and later):** the vendor REJECTS a
  `run_command` call at EXECUTION time — the stream carries "unknown tool:
  run_command — check spelling" — while `init.tools` still advertises all 57
  tools to `triad-readonly-review`. That is a vendor-side narrowing of one
  tool, not the model-visible restriction the agent's `tools:` list was
  supposed to be: the wrapper census remains the enforcement, and Policy D
  (fail-closed on any forbidden call, `manage_task` included) is unchanged.
  **`vendor-timeout` (65):** agy's OWN turn timeout (`result.error`
  "timeout waiting for response", empty response) — measured live at 857 s
  of a 900 s budget with 33 allowlisted reads over 23
  repo files: the leg read too widely for the vendor's internal turn budget.
  Never `unknown` (the repair analyzer escalated: no existing class fits).
  Handling: `retry` re-dispatches the SAME frozen prompt and scope
  once; a narrower read scope (tighter `--diff-path` / `--tests-path`, fewer
  "cite each site" demands, `--excerpt` the hot functions into the brief) is
  a changed basis — a NEW round (R-RETRY). Consolidate the other legs
  regardless; a missing entry keeps the round `INCOMPLETE`.
- **PreToolUse hook + EFFECT-based admission + the hook LOAD CHECK
  (plan `docs/superpowers/plans/2026-09-16-cfr-delivery-and-enforcement-redesign.md`
  § Enforcement).** Containment is a MECHANICAL layer the round carries
  itself, not the prompt or the agent allowlist. MEASURED on agy 1.2.5 (two
  runs) and 1.2.3: a workspace
  `<cwd>/.agents/hooks.json` PreToolUse hook FIRES in print mode (Tier 1:
  antigravity.google/docs/hooks — matcher `*` = every tool; stdin
  `conversationId` / `workspacePaths` / `stepIdx` / `toolCall.{name,args}`;
  stdout `{"decision": "deny", "reason": …}`); a denied call reaches the
  stream as state ERROR + `tool call denied by pre-tool hook: <reason>`, the
  run stays SUCCESS / rc 0, the file is never written; a call the vendor
  rejects at ARGUMENT VALIDATION never reaches the hook; and `--agent
  <unknown>` fails OPEN silently (a bogus name yields a fully write-capable
  default agent, the `init` event echoes the requested name) — so the hook is
  the backstop that holds when the allowlist does not.
  - `prepare` writes `<worktree>/.agents/hooks.json` (one named hook,
    `enabled`, matcher `*`, handler `python3 <skill>/lib/agy_hook.py --log
    <packet-dir>/agy-hook-r<N>.jsonl`, timeout 10 s) after the four artifacts
    and before the untracked walk and capture. The handler (`lib/agy_hook.py`,
    stdlib, no AI) denies a FIXED set — filesystem mutation (`write_to_file`,
    `replace_file_content`, `multi_replace_file_content`, `sed_file`,
    `notebook_*`, `delete_knowledge`), commands (`run_command`,
    `send_command_input`, `command_status`), network / browser
    (`read_url_content`, `search_web`, `open_browser_url`, every `browser_*`
    and the un-prefixed browser tools), subagents / messaging / planning
    (`define_subagent`, `invoke_subagent`, `manage_subagents`, `send_message`,
    `manage_task`, `manage_inbox`, `schedule`), MCP / generation
    (`call_mcp_tool`, `list_resources`, `read_resource`, `generate_image`) —
    the measured 57-tool registry (kept in `tests/unit/skills/t9-agy-hook.sh` as a
    DENY-side pin) — and EVERY OTHER NAME: the handler is an
    ALLOW-LIST whose set is the census's five review tools (`ALLOW_TOOLS`,
    t9-pinned equal to the wrapper's `AGY_REVIEW_TOOLS`); an unknown tool, a
    prompt-shaped tool (`ask_*`, `list_permissions`) and the waits are DENIED
    before they run — blocked, non-voiding — never left to the census. Read
    tools outside the five (`code_search`, `codebase_search`, `skill_search`)
    are denied too (disclosed). A broken hook denies every call,
    reads included, and the leg produces no answer at all (arm C, measured); an
    unreadable or nameless payload is DENIED (fail-closed); tool ARGS are never
    logged (a write's args carry the file body); a log the hook cannot write is
    reported on stderr and the decision still answers. A denied PROMPT-shaped
    call reaches the stream as `step_type: unknown`, state ERROR, with no tool
    name (measured, h1-deny-probe) — the hook log is the only record
    that names it; the digest's `denied` list cannot.
  - **Admission is EFFECT-based (Gate A only).** The wrapper's census splits
    off-list names by what HAPPENED: every occurrence DENIED before execution
    (the hook, or the vendor's own `denied permission` — ONE predicate,
    `_common._agy_step_denied`, shared with the digest's `denied` list) →
    BLOCKED: stderr `[wrapper] antigravity blocked-calls n=… tools=[…]`, the
    verdict stands; any occurrence that EXECUTED, or errored for a non-denial
    reason (its effect is unknown — the validation-rejected `manage_task` above
    is this shape) → FORBIDDEN: `admission-refused` (Policy D). Gate B — a degraded status is admitted only when an errored
    READ explains it — is UNTOUCHED; a blocked call explains nothing.
    **The TERMINAL `step_update` decides each call** — the vendor emits an
    ACTIVE update before every DONE/ERROR, and counting it would make every
    denied call "executed" too; an ACTIVE update with no terminal update (a cut stream) still counts
    as executed (unknown effect); an ACTIVE record is suppressed ONLY by a
    TRUSTWORTHY identity — an INTEGER `step_index` shared with a terminal
    update of the same name. The denial predicate is ANCHORED: state
    ERROR and the first NON-EMPTY line of `tool_info.error.message` STARTS
    with `tool call denied by pre-tool hook` or `user denied permission`, or
    carries the vendor's STRUCTURAL head `permission check failed for <verb>
    "<arg>": <tail>` whose tail — read after the last `": `, since the
    echoed argument sits inside the quotes and may itself carry a quote —
    starts with `user denied permission` or `Permission denied for` (the
    retired settings deny-rule shape; EVERY tail captured in
    `docs/spikes/2026-08-22-agy-permission-ladder`) — a diagnostic that
    quotes a phrase mid-message is an ordinary error (the call ran). Unknown
    shapes fail CLOSED and are disclosed, not enumerated (owner rule: the
    vendor is a paid service; no vendor-exotica negatives).
  - **The hook LOAD CHECK — a REQUIRED mechanical check beside the read-audit
    gate, per attempt.** `python3 <skill>/lib/agy_hook.py check
    <abs-read-audit.json> <abs-hook-log.jsonl>` — exactly the attempt's own
    read audit and the round's hook log (any other argv is usage 64) — prints
    `HOOK_LOAD_<VERDICT> tool_steps=<n> invocations=<n> denied=<n>`, plus
    ` attributed=<hooked>/<must>` when more than one census row must be
    attributed. `prepare`, `retry` and the collector run the same two
    arguments. The worktree's one `hooks.json` serves every agy leg and every
    retry, so the log is shared; each attempt is judged on its own ids.
    **Attribution rule.** The wrapper records each vendor run's conversation
    ids on its census row (`digest.attempts[].conversation_ids`, from `init`
    and every `step_update`); the hook logs the payload's `conversationId` on
    every row. Every row of THIS audit with `tool_steps > 0` must have at
    least one hook row under one of its own ids. Step-count equality is NOT
    required (a call the vendor rejects at argument validation never reaches
    the hook). Zero-step rows impose nothing and certify nothing; a hook row
    with no `conversation_id` attributes to no attempt; rows under ids this
    audit did not record belong to other attempts.
    **Verdicts, in order:** ABSENT (exit 2) — no read audit; settle the
    read-audit gate's ABSENT first. INCONCLUSIVE (exit 4) — broken evidence:
    an audit or hook log that is not a readable regular UTF-8 file, no
    `digest.tool_steps`, no `digest.attempts` census, a malformed census, a
    stepped row with no recorded id, or a log line that is not a hook row.
    VOID (exit 3) — stepped rows and zero hook invocations. INCONCLUSIVE — no
    stepped row and no invocation (nothing proves or disproves the hook).
    VOID — a stepped row of this audit with no hook row under any of its own
    ids (the check NAMES every such attempt). Otherwise PASS (exit 0). Every
    refusal names its actual reason.
    **Remedy.** `check hooks.json in the round worktree, then prepare a new
    round` (a fresh hook log). A retry is the leader's decision: the check
    reads only the attempt's own audit, so another entry's census never
    blocks one.
    **Four-leg profile.** `references/review-legs.four-leg.example.json`
    carries THREE agy-route entries (`google-contracts`, `google-failures`,
    `google-state`); they share this one hook log and are told apart by
    conversation id. Dispatch the Google entries SEQUENTIALLY — three
    concurrent Google calls are not verified.
  - **Files.** `agy-hook-r<N>.jsonl` is a leg OUTPUT for `verify`
    (basename rule, no `/`, like the X shape); `.agents/hooks.json` is OWNED
    by cleanup like the four artifacts and censused by the worktree
    FINGERPRINT — deliberately NOT listed in `delivery-r<N>.md`: it is
    enforcement, not delivered material, and a mutation the hook failed to
    stop is what the effect-based census catches. Disclosed: a reviewed repo
    that gitignores `.agents/` hides the file from the fingerprint's
    untracked arm; a reviewed tree that TRACKS `.agents/hooks.json`, or
    tracks `.agents` itself as anything but a directory (a symlink to a
    shared config dir, a file — `close` would otherwise unlink `hooks.json`
    THROUGH such a symlink), or tracks ANY case alias of an owned name
    (`.AGENTS`, `.Agents/`, `BRIEF.md` — the dev filesystem folds case, so an
    exact-name lookup would let the checkout materialise them and wedge the
    round after the artifacts exist; compared with `casefold()` over raw
    `-z` names, never whitespace-stripped), is
    refused before the worktree exists on every platform, and cleanup
    refuses before any unlink when `.agents` is not a real directory;
    the hook is an ALLOW-LIST: `ALLOW_TOOLS` = the census's five
    review tools (t9 pins them equal to the wrapper's `AGY_REVIEW_TOOLS`), and
    EVERY other name — the permission-prompt tools, the waits, a tool agy
    ships tomorrow — is DENIED before it runs (blocked, non-voiding: an
    unknown tool that mutates must be blocked before it executes, not voided
    after). A round binding `review_web_authorized` true (R-REVIEW-WEB —
    every round under the owner's standing authorization) writes the hook in
    its web mode (`agy_hook.py --log <file> --web`), which also allows
    `read_url_content` / `search_web`; every other control stays. The
    operator's user-level agy settings allow `read_url(*)` once at
    installation (the `--setup-agents` hint names it). The load
    check counts only hook-shaped rows (`decision` allow|deny + `tool`) and
    attributes them by conversation id (the bullet above).
  - **The prompt states the same rule** (the vendored `google-read-grant`
    clause, and the agent body written by `--setup-agents`): any tool outside the
    allow set is BLOCKED before it runs (the agent body says "mutating
    and network" — true, narrower, disclosed: changing it
    forces a host-wide `--setup-agents` re-run) WHEN the caller's worktree
    carries a hook (a review round) — logged, not fatal — the leg cannot see
    from inside whether such a hook is present, so it never makes one, and
    any off-list call that EXECUTES voids. The agent-body sentence is shared
    by the research agent, whose own web tools are never called blocked.
    Hosts re-run `antigravity_wrapper.py
    --setup-agents` after an upgrade that changes the agent body.
- **Model.** The entry's `agy.model` is passed as
  `--model=<value>` to `antigravity_wrapper.py` (the Pro/High
  variant — agy's catalog encodes effort in the model slug, so the slug stays
  this leg's pinned mechanism; the wrapper also passes `--effort` through on
  agy >= 1.1.10, but the catalog lists effort-suffixed selectors, so the
  leg does not add a separate `--effort`). The wrapper fail-closes a `--model`
  dispatch on agy < 1.1.10 (`config-conflict` 65 — the pin was silently VOID
  there, see the pin-floor note above): treat that exit as leg-not-run and
  surface "run `agy update`", never re-dispatch pinless to squeeze a verdict
  out of the shallow default.
- **Read-audit binding.** The SAME dispatch sets `TRIAD_READ_AUDIT_FILE` in the
  wrapper invocation's environment. That value is the entry's
  PER-ATTEMPT path `<attempt>/read-audit.json` (`prepare` renders it into
  the printed `env …` prefix), so two agy entries — or two attempts of one
  entry — can never collide. **Custody (v2):** the attempt's own `stderr.log`
  must carry the WHOLE line `read-audit-file: <that absolute path>` (the
  wrapper's timestamp prefix, the path percent-escaped from its filesystem
  bytes); the collector refuses an audit no dispatch of that attempt named.
  A misfiled or foreign audit stays a SIBLING of every later attempt and is
  never hand-removed, so the remedy is a NEW round; only a genuine audit
  whose stderr lost its line clears on a retry. The wrapper publishes the
  audit ATOMICALLY (a same-directory temp file, fsync, `os.replace`; a
  symlink at the named path is refused), so a reader never sees a partial
  audit. The wrapper writes the read-audit digest to exactly that path on
  every completed call, success or failure (`emit_read_audit`), and that
  durable file is the gate's only evidence source. Bind it AT DISPATCH TIME:
  the evidence cannot be created after the fact. The leader never removes
  or renames it. Never a bare `$AGY_READ_AUDIT_FILE` (a GATE-local name,
  unset at dispatch time) and never a `${TRIAD_READ_AUDIT_FILE:-...}`
  fallback (it could name a leftover some other shell left set).
- **Prompt body.** It is `<attempt>/prompt.txt` (rendered from the vendored
  clause bytes by `lib/prompts_v2.py`): the round worktree path and its
  `brief.md` entry point, the vendored `google-read-grant` clause, the
  severity instruction, the verdict-selection rule and the binding line,
  passed with `--prompt-file <abs>`.
- **Verdict weight.** Like every other entry: its `acceptance` label is DATA,
  and any verdict from it other than SAFE TO MERGE keeps the round
  non-agreed (SKILL rule 1, R-AGREE). What is
  special about this route is the EVIDENCE bar below — an ungated answer is
  UNVERIFIED and counts as invalid, not as agreement.
- **Cites.** Verify any surviving agy finding's file:line against the round
  WORKTREE before it enters the residual table. The gate proves the brief was
  read, not
  that a cite is accurate; cites were fabricated in 4 of 5 traced-or-scored runs
  even where the finding class was right (`references/evidence.md`).
- **Containment carriers.** TWO per-call carriers
  exist: (1) the setup-once custom agent `triad-readonly-review`
  (`bin/antigravity_wrapper.py`, `AGENT_BODIES`; written by
  `--setup-agents` under `~/.gemini/config/agents/`, checked byte-for-byte
  and selected with `--agent` on every `--sandbox read-only` dispatch, agy >=
  1.1.18) — its `tools:` ALLOWLIST omits every shell / write / MCP / browser
  / web tool, so a denied-shell step cannot occur at all, and its body
  carries the scope / existence / no-paging rules as always-applied system
  text; the wrapper admits the run by `admit()` (allowlist census over every
  attempt; a status=ERROR run with a valid answer and only errored reads is
  admitted; the `init.agent` echo is NOT a proof, agy echoes the requested
  name even on fallback); (2) the rendered prompt (this block), which
  carries every pin — the model can ignore system text but cannot call a
  tool it was not given. A packet-dir `GEMINI.md` is inert under `-p`; the
  global `~/.gemini/GEMINI.md` loads.
  Provenance: the official rules doc is antigravity.google/docs/rules-workflows
  (6-probe spike); the CLI's own bundled `agy-customizations` skill
  mis-describes both the rule-file names and their paths, so do not author a
  rule file from it.
- **Folded verdict.** If a read-only verdict folds (`truncated-answer`, exit 65):
  `retry` re-dispatches the SAME frozen prompt once (asking for a
  more compact verdict is a changed prompt — a NEW round, R-RETRY); a second
  fold leaves the entry missing and the round `INCOMPLETE` (SKILL rule 1).
  Widening the sandbox to let the leg write a long verdict forfeits rule 7's
  mechanical containment on the leg that ingests untrusted input, so it is out.

## agy read-audit gate

Apply this BEFORE weighing the verdict, and before any agy finding enters the
residual table.

The hook LOAD CHECK runs BESIDE it, per attempt:
`python3 <skill>/lib/agy_hook.py check <abs-read-audit.json>
<abs-hook-log.jsonl>` must print `HOOK_LOAD_PASS`. `HOOK_LOAD_VOID` — a
stepped census row of the attempt with no hook row under any of its own
conversation ids, or zero hook invocations while a row has tool steps —
means the enforcement layer did not load for that attempt, so its leg is
INVALID whatever this gate says. `HOOK_LOAD_INCONCLUSIVE` (broken evidence,
or nothing ran and nothing was logged) certifies the leg neither. The
attribution rule and the remedy are in § agy leg, the hook bullet.

**Threat model (owner ruling — settled; do not re-open; recorded in
`docs/reviews/2026-07-31-agy-stream-json-residuals.md`).** The gate is evidence
that the leg DID THE READING WORK, a mechanical anti-shallow-review check. It is
not an authenticated channel: the digest's content is folded from
vendor-supplied stream events, so a hostile vendor process could fabricate a read
event however the digest reaches the leader. What the dedicated file DOES close
is the transport vector — the wrapper writes the digest once, to a file it alone
owns, strictly after the vendor subprocess is reaped, so no shared stream
survives for a stray grandchild to append to. That retires the late-append /
first-match-forgery / anchored-extraction class of findings the stderr-based gate
carried. The content-forgery question stays open by design.

The wrapper writes the digest to `TRIAD_READ_AUDIT_FILE` on every completed call,
success or failure — ONE artifact: extract it with `jq`, never grep/sed. (The
run-log's `read_audit` key exists, but the gate does not read it; the run-log
is the repair-agent's input artifact.)

Then apply:

1. each of the round's REQUIRED-READ files — the worktree brief AND the
   gated patch (`<packet-dir>/wt-r<N>/brief.md`,
   `<packet-dir>/wt-r<N>/diff.prod.patch`), which the gate takes as
   ARGUMENTS. The brief alone is not enough: it
   carries framing and a manifest, so a leg could pass while never opening
   the code under review — must appear as the `AbsolutePath` param
   of a `read_audit.digest.files_read[*]` entry (`read_audit` here names the
   loaded `{meta, digest}` object). The match is KEY-RESTRICTED
   (live-corroborated by a real `grep_search {Query, SearchPath}` digest
   entry): `files_read` holds every
   successful READ-CLASS call, so a `grep_search` whose `Query` VALUE equals
   that path is tool traffic that merely REFERENCED it — only
   the file-view tool's `AbsolutePath` param evidences a read of the file
   itself. The key name is a VENDOR coupling (disclosed): empirically pinned
   from real digests + the t41/f9/t5 fixtures; an agy param rename fails
   toward VOID/INCONCLUSIVE (loud, conservative), never a silent PASS.
   `files_read` records only tool calls that SUCCEEDED (terminal DONE with
   no `tool_info.error`), so a hit is real proof the leg's view_file call on
   the packet succeeded (one disclosed limit: a RANGE-limited view — if the
   dispatched build ever emits range params — would satisfy this on a
   partial read; no range params have been observed in real digests — a
   recorded residual);
   an ERRORED or permission-DENIED read attempt appears instead under
   `read_audit.digest.read_attempts[*]` with an `outcome` of `error`/`denied`
   and does not satisfy this gate. The digest is CAPPED (every `params` value
   truncated at 200 chars; `files_read` itself capped at the first 40 entries,
   with `files_read_omitted` counting the rest). WITHIN the cap the stored
   value IS the full path, so equality is exact; a packet path AT OR BEYOND
   the cap (an exactly-cap stored value could equally be a LONGER path's
   truncation) is a PREFIX-identity the digest cannot tell apart from
   any same-prefix file (a sibling argument, a digest-side file that was
   never an argument, or a stale `packet-r<N-1>.md` whose round-suffix the
   cap erases) — the helper refuses such arguments INCONCLUSIVE outright
   instead of over-claiming a match, and
   this refusal also subsumes the arg-side collision case (two DISTINCT
   within-cap arguments can never share a capped identity). If a within-cap
   match fails AND
   `files_read_omitted > 0`, the result is INCONCLUSIVE rather than VOID. The
   digest is the merged aggregate over every retry attempt — there is no bigger
   digest to open. Recoverable evidence is the per-attempt census
   (`read_audit.digest.attempts[]` — one row per attempt with `attempt` /
   `status` / `tool_steps` / `error_steps`, plus ONE NUMBER per list key that
   already folds that attempt's own entries AND its own omitted overflow
   together; a row carries no separate `_omitted` fields, so the number is a
   pre-dedupe TOTAL) and `read_audit.digest.read_attempts[]`. A row ALSO
   carries **`capture_complete`** under the
   omit-when-DEFAULT rule — present only as `capture_complete: false`, which
   says THAT attempt's transcript was a PREFIX (a wrapper reader thread failed
   or did not join). The merge unions every attempt's reads, so without the
   per-attempt flag a merged audit would present a knowingly incomplete
   earlier attempt as ordinary evidence. Read it before you weigh a census row: a
   `false` row's read counts are a lower bound on a stream nobody finished
   capturing, not a coverage claim. (The attempt that CARRIES the flag is
   terminal for the wrapper — `truncated-answer` 65, never retried inside the
   driver — so a `false` row can only be an EARLIER attempt or the last one.)
   The other omit-when-default row keys: the capture markers `truncated_tail`
   (cut mid-line) and `interrupted` (`"timeout"` = killed at the wrapper
   deadline, `"signal"` = the spawned child died on a signal) — with
   `capture_complete` the only three — and `conversation_ids_omitted` (ids
   dropped at the cap). `conversation_ids` is ALWAYS present, possibly empty — the ids the
   hook load check attributes by. The run-log's
   `stdout` holds the raw NDJSON of the FINAL attempt only — an earlier
   attempt's raw stream is retained nowhere, so never plan to read it. If the
   census does not settle it, do not guess: a narrower packet is a NEW round.
   Only a failed match WITH `files_read_omitted == 0` is a confirmed VOID:
   treat it as leg-not-run. A `retry` (the same frozen prompt) clears it: the
   new attempt is judged on its own read audit and its own conversation ids.
   An entry still VOID after that one retry is missing this round (rule 13):
   the round is `INCOMPLETE`, never agreed (SKILL rule 1); no second
   re-dispatch;
2. surface `read_audit.digest.denied` / `read_audit.digest.read_attempts`
   entries in the round notes — a **read-class** `read_attempts` entry naming a packet file is the
   diagnostic for a VOID verdict (the leg TRIED and was blocked, rather than
   never looking). `read_attempts` holds every unsuccessful tool, so filter on
   its `class` field (`read`/`write`/`command`/`web`/`other`): a blocked write or
   `run_command` that merely NAMED the packet is not a failed read and must not
   be reported as one;
3. the latency signal (rule 11: under 60s on a packet of 100KB or more implies a
   shallow pass) is a SECONDARY signal here — the read-audit is the primary,
   deterministic evidence.

agy verdict weight is unchanged (rule 1).
MECHANICAL means extract-and-gate deterministically, with no AI judgment. Run
the skill's own helper — ONE call per round covers several required-read files
(every file must pass):

     ```bash
     bash <skill>/lib/read_audit_gate.sh --audit-file <abs results-r<N>/<name>/attempt-<K>/read-audit.json> "$PACKET_DIR" "$PACKET_DIR/wt-r<N>/brief.md" "$PACKET_DIR/wt-r<N>/diff.prod.patch" [<more-abs-files>...]
     ```

The helper is the gate's single EXECUTABLE form: the canonical jq invocation
LIVES in `lib/read_audit_gate.sh`, where the t41/f9 self-tests lift it
verbatim and `t5-read-audit-gate.sh` owns the CLI contract. This section
stays the SPEC the helper implements. What each outcome means:

- **The audit is NAMED, never derived**: the REQUIRED leading
  `--audit-file <abs>` flag (argv-only, no env fallback, no default path — an
  ambient `TRIAD_READ_AUDIT_FILE` some OTHER shell context left exported can
  never make the gate open a file nobody bound for THIS attempt). The value
  must be ABSOLUTE, live inside `$PACKET_DIR` (no symlink resolution: an
  audit outside the census'd round dir is not this round's evidence), and
  match exactly ONE shape — the per-attempt audit
  `results-r<N>/<name>/attempt-<K>/read-audit.json`. `prepare` binds
  `TRIAD_READ_AUDIT_FILE` to that path on the agy entry's argv and PRINTS the
  matching `gate:` line; run it verbatim, once per agy attempt. Any other
  path (the packet dir itself, a foreign subdirectory, outside the packet
  dir) and a missing flag are a LOUD usage exit 64, never a verdict — gating
  one entry on another's evidence would be a false PASS. The wrapper writes
  the audit on EVERY completed call, ok or not — no stderr capture, no
  grep/sed extraction (`triad-antigravity-dispatch` § Isolation).
- **The required-read args are the worktree BRIEF and the GATED PATCH** (for a
  `prepare`-built round: `<packet-dir>/wt-r<N>/brief.md` and
  `<packet-dir>/wt-r<N>/diff.prod.patch` — never the packet DIR itself). `prepare`
  prints the exact command; keep it and the READ-GRANT in step, since a
  required read the leg is not instructed to make VOIDs a compliant leg.
  Argv discipline is LOUD (exit 64), never a verdict: the packet dir
  and EVERY file argument must be absolute paths, the dir must exist, and
  every named file must exist — a stale generic `packet.md`, or a prior
  round's entry file, would otherwise false-VOID a compliant leg.
- **Exit 0 PASS** — every packet file's absolute path matched the
  `AbsolutePath` of a successful `view_file` entry in `files_read` (the
  rule-1 tool+key restriction; arguments that survive to this comparison
  are within the cap, so the stored value is the FULL path and equality is
  exact — no truncation is applied to a surviving argument). Proceed to
  weigh the verdict.
- **Exit 2 ABSENT** — no digest file. NOT proof the vendor call failed:
  `TRIAD_READ_AUDIT_FILE` unset/misbound at dispatch time is empty in
  exactly the same way as a call that never completed. Check the dispatch
  env FIRST; only once it is sound, treat as VOID (leg-not-run). The attempt
  stays a SIBLING of
  every later attempt of the round (the hook load check reads a dispatched
  attempt with no audit as INCONCLUSIVE), so prepare a NEW round — unless the
  attempt never spawned agy (no `exec` line in its `stderr.log`): the hook
  check skips it and a retry does clear it.
- **Exit 3 VOID** — a confirmed miss (`files_read_omitted == 0`). A `retry`
  clears it (the new attempt is judged on its own audit); still VOID after
  that retry is missing this round (rule 13, no second re-dispatch). (A duplicate-JSON-member refusal, spec C14, is
  schema-fail 66 with no answer, so its merged audit never reaches this gate:
  the gate runs only after an admission succeeded.)
- **Exit 4 INCONCLUSIVE** — never read as VOID and never as PASS. Four
  causes, each named on stderr: a CAPPED digest (`files_read_omitted > 0` —
  weigh `digest.attempts[]` per-attempt totals + `digest.read_attempts[]`,
  and, if the census does not settle it, use a narrower packet — a NEW
  round (a retry re-renders the frozen prompt); there is no fuller digest, and only the FINAL attempt's raw stream is
  retained anywhere), BROKEN evidence (jq could not produce a usable
  answer — read, parse, program, or runtime error: inspect the file
  directly), a SYMLINKED digest file (refused,
  never followed — the wrapper writes a regular file it alone owns, so a
  symlink at that path is a redirect nobody's dispatch bound; note this is
  a check-then-open guard, WEAKER than an O_NOFOLLOW read — acceptable here because the gate runs strictly after
  the agy child is reaped and no other round participant writes that path),
  or an at-or-over-cap packet path (200 characters or longer — stored in
  the digest as a PREFIX-identity that cannot be told apart from any
  same-prefix file, an exactly-cap value being possibly a longer path's
  truncation, so the gate refuses to over-claim; shorten the packet path
  and re-run; this refusal subsumes the arg-side collision case, and the
  same argument passed twice remains ONE identity, legitimately
  confirmable). Remedy for the BROKEN case: the audit stays a
  SIBLING of every later attempt (the hook load check refuses it as broken
  evidence), so prepare a NEW round.
- **Multi-file aggregation is pinned and LOAD-BEARING**: any INCONCLUSIVE
  file → exit 4; else any VOID file → exit 3; else exit 0. The per-ARGUMENT
  over-cap refusal CAN mix with a digest-side VOID in a single run (only
  the capped/broken digest states are digest-global), so the precedence is
  what keeps a mixed round deterministic — never remove it as dead logic.
  BROKEN evidence stops the loop — later files are never evaluated. The
  summary counters count EVALUATED files only, and whenever any argument
  was NOT evaluated (the broken-evidence stop; the ABSENT/symlink refusals
  evaluate none) the summary line appends
  ` unevaluated=<n>` so the token and the counters cannot disagree
  silently.
- **The verdict inputs are the jq gate's rc + `files_read_omitted` ONLY.**
  The stderr `ATTEMPTED but failed to read the packet` line — a read-class
  `read_attempts` entry naming a packet file, i.e. the leg TRIED and was
  blocked — is diagnostic text for the round notes, never a verdict input
  (`read_attempts` also carries failed writes/run_commands/web fetches; one
  of those merely NAMING the packet is not a failed read, which is why the
  helper scopes the note with the SAME tool+key restriction as the verdict
  jq — `.class == "read" and .tool == "view_file"`, AbsolutePath-only value
  scan; the trade — a rename-induced VOID loses the "it tried" note too — is
  a recorded residual).
- **The 200-char cap is COUPLED to `bin/_common.py`'s `_AGY_DIGEST_VALUE_CAP`**
  (t5 drift-guards the pair and the helper's one-literal property). Within
  the cap the stored value is the FULL path, so equality is exact; over-cap
  arguments are refused INCONCLUSIVE (rule 1 above) — which also settles
  the locale-unit question by refusal (a length that units could
  disagree about is over-cap in at least one unit and lands in the refusal,
  conservative in both directions).
- **The stdout contract** for round notes: one `[gate] <VERDICT> <file>`
  line per EVALUATED packet file (the ABSENT/symlink refusals evaluate
  none; the broken-evidence stop evaluates no later file), then the final
  greppable summary
  `READ_AUDIT_GATE_<PASS|VOID|INCONCLUSIVE|ABSENT> checked=<n> pass=<n>
  void=<n> inconclusive=<n>[ unevaluated=<n>]` — the
  `unevaluated` field appears exactly when some argument was not evaluated
  (ABSENT/symlink refusals, the broken-evidence stop), so anchor on
  the token, not on a four-field-only pattern.

One shape to know: a digest file that is valid JSON but carries no `.digest`
key yields jq rc 1, not rc>=2, so it lands in the coverage-miss branch and —
with `omitted` 0 — reads as a confirmed VOID (exit 3). That is intended: a
digest-less file is a leg that produced no read evidence.

## agy standing residuals

Two live claims govern whether a deployment can run this leg at all:

- **Write/exec are ABSENT on the v2 read-only path** (allowlist agent, no
  danger flag): a fallback run's writes/shell are denied by the vendor's own
  headless policy (measured in the permission-ladder spike, agy 1.1.18) and
  the admission
  census rejects the run; tools with NO permission action (notebook /
  subagent / message / browser_* family) are detection-only. A status=ERROR
  run is admitted when its verdict validates and its errored steps are all
  allowed reads — the read-audit still shows every errored step. The round
  worktree's PreToolUse
  hook denies every tool outside the five-name allow set (mutating / command / network / subagent / planner tools included)
  whatever agent resolved — the backstop for `--agent` failing OPEN — and
  admission is EFFECT-based: a BLOCKED call is logged, an EXECUTED off-list
  call voids; the hook LOAD CHECK proves the layer loaded (§ agy leg).
- **Other disclosed v2 residuals:** a fallback that calls nothing forbidden is
  indistinguishable and accepted (side-effect-free); two agent files outside
  the repo per host (`--setup-agents`); a vendor rename of an allowlisted
  tool blinds the agent (no `files_read` → this gate VOIDs the leg);
  `_common._run_once` mirrors raw vendor stderr on every path.
- **Reads are open BY DESIGN on every build** — `read_file` is never denied,
  so the leg can read ANY file the user can read OUTSIDE `--cwd`
  (probe-CONFIRMED under `--sandbox read-only --cwd <packet dir>`). Network:
  the REVIEW agent (`triad-readonly-review`) carries NO web tool; a review
  leg of a web round (`--review-web`) and an investigation (`--web`) run the
  research agent, which keeps `read_url_content` / `search_web`, so on a web
  round the leg's own tools can send queries and fetch pages (the shared
  `review-web-permission` clause forbids sending the reviewed material, a
  local path or a person's name). A deployment that cannot accept the read
  residual runs the leg inside an EXTERNAL fs-scoped OS sandbox.
- **Host hooks (owner-accepted residual):** a PreToolUse hook the
  operator installed in `~/.gemini/config/hooks.json` runs its command on every
  matching tool call in print mode, outside agy's permission model and outside
  the stream the census sees; host configuration is inside the trust boundary
  and no wrapper path governs it.

The version chronology, the probe record and the deny-set inspection behind both
claims are owned by the `triad-antigravity-dispatch` skill — its § Headless
soft-deny adaptation and the isolation reference it points to.

## gemini leg

The gemini route is compatibility with the older gemini CLI (legacy
compatibility), not a standing review leg. When gemini is the resolved Google
route, the model comes from that entry's
`gemini.model`; without one, the CLI default runs and the round record says the review tier
is unpinned. The route takes NO effort flag — `gemini_wrapper.py` has none,
and the roster refuses a `gemini.effort` value rather than translating an agy
tier into an unsupported argument. It also takes no producer schema: the
verdict shape is pinned by the prompt text, and `verdict_v2.py` admission is
the only mechanical check.

**Auth-class gate (R-AUTH / C37) — every posture, before any vendor
process:** `security.auth.selectedType` `gemini-api-key` / `vertex-ai` /
`compute-default-credentials` is refused as `oauth-env` (65), remedy = the
owner's browser re-login (no flag change, no retry).

**Review preflight (C16) — provider-free checks BEFORE any vendor
call.** In order: the effective posture is computed FIRST, then (1) a VERSION
FLOOR — `gemini >= 0.63.0`, one route floor independent of the requested
model that the wrapper applies on EVERY gemini route, review included (owner
decision D-GEMINI-FLOOR-20261009; a pre-release of 0.63.0 is below it, build
metadata is ignored, no model list or catalog probe); (2) on the
`--sandbox read-only` review route only, a CAPABILITY probe — `--help` must advertise
`--policy`, `--approval-mode` and `--output-format`, the three flags the
read-only argv depends on. The AUTH CLASS gate above runs first, on every
posture: `oauth-personal` is the approved subscription login, and an
UNEXPOSED or unknown class is reported on stderr and allowed to run — a
refusal list is a claim about billing, and guessing one would block a
legitimately configured in-service host. Each refusal is pre-spawn
(`config-conflict` / `oauth-env`, 65), names the cause, and writes its audit
row and run-log carrying the version observed before it.

**NOT RUN live.** Every gemini statement here is a deterministic,
provider-free implementation fact (t57 / t58) — not a measured runtime
effect. The policy's runtime effect is unmeasured; its check is recorded in
spec `contracts/gemini-readonly.verify.toml` (V1-V5).

## codex leg

- **Tier.** The tier is the entry's `codex.reasoning` (the
  shipped default: ONE codex entry, the model the shipped default names, at
  `high`, roster data). A deeper tier (`xhigh`, or
  `max` — the deepest non-delegating tier) for a round the leader designates
  very-important AND algorithmically complex is a roster change, so a new
  basis; at max a LARGE packet has exhausted 900s with no verdict, which the
  roster's `timeout_s` 3600 on every entry (rule 7) covers. `ultra` stays out: it self-delegates
  subagents (runaway/over-long) and not every model variant supports it. A tier the
  CLI rejects ends the attempt as a failed-to-run record; the user changes the
  entry's value — the host never steps down to another tier (R-MODEL).
- **Review web = `--search`, bound per round (R-REVIEW-WEB).** The rendered
  v2 codex argv carries `--search` exactly when the round binds
  `review_web_authorized` true — every round under the owner's standing
  authorization; only the owner revokes it, for rounds prepared after the
  revocation. Without `--search` the wrapper pins `web_search="disabled"` in
  config, so no search tool is exposed (omission alone would leave codex's
  cached default available). The read-only sandbox, `approval_policy=never`
  and `--ignore-rules` stay either way, and the operation stays a REVIEW with
  its normal verdict, containment and entry accounting; every prompt carries
  the shared `review-web-permission` (or `review-no-web`) clause. `--search`
  through `triad-codex-dispatch` is also the codex INVESTIGATION path
  (R-INVEST); its answer enters a round as leader-verified brief material,
  never as a leg verdict.
- **`--ignore-rules` rides every codex dispatch (read-only and write
  posture).** Tier 1 (`openai/codex` `codex-rs/exec/src/cli.rs`, global exec
  flag): "Do not load user or project execpolicy `.rules` files"; the rules
  doc: a rule with `decision="allow"` "run[s] the command outside the sandbox
  without prompting". This host's `~/.codex/rules/` allow `git add`, `git
  commit`, `gh …`, even `rm -rf _runs` — so without the flag `--sandbox
  read-only` would be one operator rule away from a real write. `codex_wrapper.py` appends
  `--ignore-rules` itself on every posture — the raw default, this leg, and
  `--sandbox workspace-write` (a wrapper dispatch pins `approval_policy=never` and never
  wants an escalation outside the sandbox on the write posture either; inside
  workspace-write the same commands still run when the sandbox permits them).
  Nothing to add at the call site; `tests/unit/wrappers/t24-codex-search.sh`
  pins the placement.
- **DE-INLINED — `--cwd <round worktree>` and the read grant.** `prepare` hands every leg a worktree pinned at
  the reviewed commit, so the guaranteed view IS that tree, entered through
  `brief.md`; inlining would only re-spend context on bytes the leg can read
  for itself. Measured: codex held a 128 KB diff straight from the
  worktree — 307.8 s `ok`, 13 of 13 cited lines verified real against the tree.
  `--sandbox read-only` blocks writes, never reads; a blanket no-exec
  directive that bans the read-only shell commands codex uses to open files
  is what leaves it unable to open a handed-over file. With reads granted the
  leg verifies the brief's claims against the tree the way the claude leg
  does — without the grant it misses defects that need one function outside
  the packet and reasons its triggers without code access. Containment posture: file WRITES stay
  mechanically blocked by `--sandbox read-only`; execution/network
  limits ride the read grant; the round's capture/verify integrity gate
  (`references/packet-lifecycle.md` § Round integrity) is the belt —
  mutation detection, not a sandbox claim alone, decides admission.
  The READ boundary itself is INSTRUCTION-LEVEL: neither `--cwd` nor the read-only
  sandbox mechanically confines what the leg can READ — so the read grant's
  outside-repo prohibition is a directive the integrity gate cannot
  verify, the same residual class § agy standing residuals discloses for the
  agy leg. The outbound half follows the round's web condition (`--search`
  above).
  READ-GRANT: the vendored `codex-read-grant` clause
  (`spec/prompts/leg-codex.md`) — read-only commands (cat, sed -n, rg, ls, git
  diff, git show, git log) inside the working directory to verify claims,
  cite file:line, nothing outside the repository, no modification or
  execution; its `<review-web-policy>` is filled by the round's web clause.
  Fast-SAFE heuristic RESCOPED with this contract: a fast terse SAFE is a
  signal worth recording when the leg HAD code access and substantive
  questions — still a valid result, never re-dispatched (R-RETRY, SKILL rule
  11). Mechanically: `prepare` renders this entry's entire body as
  `<attempt>/prompt.txt` — POINTING AT the round worktree plus the read
  grant, severity instruction, verdict-selection rule and binding line — and
  PRINTS the dispatch line (§ v2 dispatch shapes); run that line verbatim.
  PATHS (C28): a RELATIVE `--prompt-file` / `--cwd` is not refused — the
  wrapper resolves it MECHANICALLY against its own process-entry cwd (never
  the child `--cwd`), runs every pre-existing validation unchanged, and
  RECORDS the resolved absolute path on the summary line
  (`prompt_file=<abs>`) and in the audit row (`prompt_file_resolved`).
  ABSOLUTE stays the printed form — `prepare` emits nothing else — because the
  record is what makes a mis-resolution legible after the fact, not a
  guarantee it cannot happen.

  Keep `$(cat body.txt)` OUT of a single-quoted heredoc BODY — i.e.
  `--prompt "$(cat <<'TRIAD_CODEX_PROMPT_EOF'` … a line containing
  `$(cat body.txt)` … `TRIAD_CODEX_PROMPT_EOF)"`. The heredoc is literal, so
  that inner `$(...)` is never expanded and codex receives the uninterpreted
  string `$(cat ...)`. (The sibling dispatch skills' Step 1 uses the heredoc
  shape for a literal prompt body, each with its own collision-resistant
  `TRIAD_<CLI>_PROMPT_EOF` terminator. THIS leg's path is `--prompt-file` on
  the rendered `<attempt>/prompt.txt` — collision-free precisely because
  there is no heredoc to terminate early.) There is no asymmetry to manage:
  every leg — codex, agy/gemini and claude — is pointed at the SAME
  round worktree and enters through the same `brief.md`, so the transport is
  uniform and the bytes each leg judges are identical. That identity is what the
  binding's `content_digest` and cross-family corroboration both rest on.

## claude fresh-eye leg

- **Identity.** The leader spawns EXACTLY the printed `subagent_type`
  (§ v2 dispatch shapes). Under a true web condition — every round under
  the owner's standing authorization — that is the named preset's `-web` twin
  (`cross-family-review-reviewer-web`, `-high-web`, `-max-web`; frontmatter
  `tools: Read, Grep, Glob, WebSearch, WebFetch`, the preset's model and
  effort); under a false condition it is the base preset itself.
- **The base preset (a false-condition round).**
  `subagent_type: triad-dispatch:cross-family-review-reviewer` — the dedicated
  read-only reviewer agent (`agents/cross-family-review-reviewer.md`,
  frontmatter `tools: Read, Grep, Glob`), so rule 7's no-execute contract rides
  the agent's tool allowlist rather than the prompt directive alone. The `Agent`
  tool exposes no per-call `tools` allowlist, so a plain
  `subagent_type: general-purpose` Agent would fall back to that advisory
  directive; the frontmatter pin IS the mechanism. (The shipped claude-host
  plugin rewrites this to the plugin-scoped
  `subagent_type: triad-dispatch:cross-family-review-reviewer`, so a consumer's
  same-named project agent cannot shadow the read-only plugin reviewer.)
- **Tier.** The tier is that of the preset the entry's `claude.agent`
  names; its `-web` twin carries the same model and effort. The base preset's
  frontmatter pins the current model (its `model:` line) and `effort: xhigh`. Leave
  the model out of session inheritance: an unpinned agent inherits the leader's
  SESSION model and can silently run a heavier tier such as fable, which is out
  of the review rotation. Escalation for a very-important AND algorithmically
  complex round = `subagent_type: triad-dispatch:cross-family-review-reviewer-max` (identical
  body, `effort: max`; the entry's `claude.agent` names it and a true web
  condition spawns `-max-web`). Effort is frontmatter-fixed with no per-invocation
  override, so the sibling definition IS the escalation mechanism. A THIRD
  sibling, `cross-family-review-reviewer-high` (identical body, `effort:
  high`), is the second claude arm (evidence:
  `docs/reviews/2026-09-06-claude-effort-high-vs-xhigh-campaign.md`). The
  `-high` sibling is an ORDINARY roster entry — `x-claude-high`, whose nested
  `claude.agent` block names this `-high` sibling, carried by the project
  override `.claude/triad-review-legs.json`; its `acceptance` is DATA
  and any verdict from it other than SAFE TO MERGE keeps the round non-agreed like any entry's (SKILL
  rule 1) — never the standing claude leg. Both claude arms
  read the same packet bytes and the same shared clauses; only the entry's
  binding (`leg_name`) differs, so a verdict difference is an EFFORT
  difference, never a framing one. Every preset names the model by the `opus`
  alias (Claude Code resolves it to the latest Opus; an older model is not
  selectable). These three and their `-web` twins are the CLOSED list a v2
  entry may name (C12);
  `prepare` binds the spawned file's sha256 (with the model and effort it
  pins), and `collect` / `retry` refuse a changed or missing file — a new
  round (C19).
- **Prompt.** The leg receives the printed `prompt.txt`
  unchanged — the vendored shared clauses (evidence-centred independent
  review, no severity deflation or inflation, the verdict-selection rule); the
  leader adds no persona, intensity request or predicted-defect list (SKILL
  rules 10-11, R-PROMPT). Its depth lever is the preset's frontmatter effort.
- **Output contract (structured verdict, no wrapper).** The printed
  `prompt.txt` already carries the verdict shape (the vendored
  `claude-verdict-shape` clause) and the leader appends nothing (SKILL rule
  10). The reply admits ONLY through the printed `verdict_v2.py --admit` line
  (SKILL Flow 3, rule 4) — no repair path; only an admitted reply is sealed: a
  reply that fails admission is not sealed, collects as not admitted, and a
  new answer needs `retry` (it seals that attempt `invalid`) or a new round. A
  leader-completed, leader-repaired, or leader-reconstructed reply is NEVER
  admissible.
- **Reply transcription.** The leader dispatches the `Agent` with the
  printed `prompt.txt` (the file is the censused input).
  TRANSCRIPTION CAVEAT: the Agent completion
  notification HTML-escapes the reply (`>` → `&gt;`, `&` → `&amp;`,
  quotes likewise); the transcript-extraction path may instead yield the
  UNESCAPED text. **Do NOT unescape manually** — write the staged raw
  VERBATIM as `claude-r<N>.json` and let `--admit` perform the SINGLE
  mechanical unescape (RAW-FIRST two-pass: marker check + parse
  run on the raw bytes first — an already-valid reply admits BYTE-EXACT,
  entity-spelling strings preserved — and the unescape+retry runs only
  when that pass fails with entity tokens present, so an escaped marker
  still admits, on pass 2).
  OVER-de-escaping by hand is the hazard that remains (it is a leader
  edit — never admissible); UNDER-de-escaping is absorbed by the tool.
  DISCLOSED residual: a reply
  whose string fields INTENTIONALLY spell HTML entities is
  indistinguishable from transport escaping after one unescape — when a
  finding's exact bytes matter, resolve against the agent transcript.
  (The reviewer agent is Read/Grep/Glob-only, so a
  write-your-reply-to-a-file contract is NOT available — leader-side
  transcription is the only path, hence the caveat.)
  **Raw path.** The raw reply's home is the entry's own attempt dir,
  `<attempt>/raw.json`, and the admitted object is `<attempt>/admitted.json`
  — both printed by `prepare`. The whole `results-r<N>/` tree is LEG OUTPUT
  by census rule (`references/packet-lifecycle.md` § Per-entry results tree),
  so a raw reply there cannot fail `verify` as an uncovered file, and the
  path carries the round, the entry name and the attempt number. Write
  VERBATIM, never de-escape by hand, and let `--admit` do the single
  mechanical unescape.
- **Agent definitions and the session.** A NEW definition file registers
  mid-session (measured on a desktop build: the harness announced it and a
  smoke dispatch ran on it — transcript `effort: high`); whether an EDITED frontmatter
  re-loads mid-session is unmeasured. Before the first gate that uses a new or
  re-tiered sibling, check the Agent tool's available-types list, and prove
  the tier from the transcript's `effort` field (the campaign's fingerprint
  column).
