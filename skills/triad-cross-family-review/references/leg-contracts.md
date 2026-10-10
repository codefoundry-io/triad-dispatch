# Cross-family review — per-leg dispatch contracts

Loaded on demand from `triad-cross-family-review/SKILL.md`. Read this when
dispatching a round's legs (Flow step 2), and again when an agy leg returns —
its verdict may be weighed only after the read-audit gate and the hook load
check below pass.

## Contents

| Section | Open it when |
|---|---|
| v2 dispatch shapes | reading or sanity-checking the argv `prepare` printed for an entry |
| Producer schema projection | asking what schema the vendor received, or why it differs from the canonical one |
| Verdict binding — all legs | dispatching any leg, or admitting a returned verdict; the attempt seal |
| Google-family leg selection | resolving a google entry's route (agy; gemini = legacy compatibility) |
| agy leg | dispatching agy — model selector, read-audit binding, containment block, the hook load check |
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
that reason. The run-log directory is one of the attempt's sealed files
(§ Attempt seal). The wrapper entry's early `admit:` line
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

A duplicate entry name in the override document — exact or differing only in
case (`codex` / `Codex`; the name becomes a directory name and the macOS
default volume folds case) — is refused before anything is created. An
override name equal to a shipped entry's name under case folding is refused
the same way; one spelled exactly like the shipped entry merges into it.

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

**The projection's sources are in the round's toolkit map.** Because the
projection is re-derived from the vendored contract on EVERY render — a
`retry`'s render included — a spec re-vendoring between `prepare` and `retry`
would hand attempt K+1 a DIFFERENT producer schema. The contract and the
`lib/` files that project it are files of the `toolkit_map` `prepare` records in
`.roster-r<N>.json`, and `retry` compares that map with the installed files
before allocating; a changed file — or a record carrying NO map — refuses with
"prepare a new round" (`references/triage.md` § Collect outcomes). Each
attempt carries its own `schema.projected.json`.

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
   **The EXPECTED values are DERIVED, never read back**
   (`collect_v2._expected_binding`, the ONE derivation every reader calls):
   `review_id` and `content_digest` from the ROUND RECORD, `family` /
   `leg_name` / `route` from the round's FROZEN ROSTER ENTRY, and `attempt`
   from the attempt DIRECTORY NAME. `binding.json` must EQUAL all six before
   admission runs — a binding and a result that only validate each other would
   let a pair copied out of one entry's attempt be credited to another. A
   disagreeing binding is `invalid` with the offending FIELD named; a
   non-object `binding.json` (`null`, `[]`) invalidates that ONE entry
   (`binding record is not an object (<type>): <path>`) and every other entry
   still collects. A wrapper entry's printed `--expected-*` flags come from
   the same derived values, each `shlex.quote`d
   (`review_scratch._v2_expected_flags`); the native `--admit` line types
   none — it reads the six from the attempt's `binding.json`, a typed flag
   that disagrees is exit 64, and `collect` still re-judges the admitted
   result against the derived values.
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
6. **A dispatch line the host cannot encode is a one-line refusal, never a
   traceback**. `review_scratch._emit_payload` refuses a dispatch line
   carrying a path this host cannot represent as UTF-8 (surrogateescape
   bytes, a token decoded under an ASCII locale) and the command exits
   **2** with the named reason. `prompts_v2` is a library and prints
   nothing: the rendered prompt is written to the attempt's `prompt.txt`,
   the bytes the round record's manifest digests and the leg receives.

### Attempt seal

A recorded attempt is SEALED (R-BIND, case C66): `seal.json` beside it binds
the sha256 of the attempt's result, its receipt (the wrapper run-log
directory, role `run_log`, digested over its `*.json` run-logs only) and its
read evidence, and the state they were recorded in; `collect-r<N>.json` keeps
every seal's digest.

- **Who seals.** The native admission (`verdict_v2.py --admit …
  --admitted-out`) seals an ADMITTED claude reply; a refused reply is not
  sealed, collects as not admitted (`MISSING — no result file at
  <attempt>/admitted.json`) and stays open to `retry`. On a wrapper route the
  first `collect` that judges an answer — valid or not — seals the attempt
  over the bytes it judged. `retry` seals the attempt it replaces
  (`failed-to-run`, or `invalid` over an inadmissible answer, a refused native
  `raw.json` included) before it allocates the next one.
- **No re-answer.** The printed `guard:` line and the guard inside each wrapper
  line refuse a re-run into a sealed attempt, and the native `--admit …
  --admitted-out` is refused on it (exit 64; a wrapper entry's `admit:` line
  only re-validates, read-only). A new answer needs `retry` (an attempt sealed
  `invalid` or `failed-to-run`, never one sealed valid) or a new round. An
  attempt sealed with a valid answer is never re-judged by the argv
  comparison.
- **Integrity.** Every `collect` re-checks the sealed files of every attempt,
  digesting each file once. A sealed file or the seal itself that changed, was
  removed or was replaced — a late answer into a replaced attempt included —
  is that entry's integrity failure: `INCOMPLETE`, a reason ending "prepare a
  new round", and `retry` refuses it. A sealed-role file that cannot be read,
  an unsealed attempt's unreadable run-log (`retry` cannot record an attempt
  it cannot read) and a seal with no `run_log` role (written before the
  receipt binding) each name a new round. When a retried leg may still be
  running, collect once more before using an AGREED: a late answer is caught
  only by the next `collect`.

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
  `python3 <plugin bin>/antigravity_wrapper.py --setup-agents` once (the
  runnable line is in `triad-antigravity-dispatch` SKILL.md Step 1, Host
  setup; a missing/drifted file is
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
  `python3 <plugin bin>/antigravity_wrapper.py --setup-agents` (the
  `triad-antigravity-dispatch` Host setup line) after
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
    and before capture. The handler (`lib/agy_hook.py`,
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
  - **The hook LOAD CHECK** proves, per attempt, that this hook loaded —
    § agy hook load check below.
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
    refused before the worktree exists on every platform, and `close`
    refuses, deleting nothing, when `.agents` is not a real directory (its
    tree check reads it as content this helper did not create — while the
    reviewed repo does not ignore `.agents`; an ignored path is not judged);
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
    installation (the `--setup-agents` hint names it).
  - **The prompt states the same rule** (the vendored `google-read-grant`
    clause, and the agent body written by `--setup-agents`): any tool outside the
    allow set is BLOCKED before it runs (the agent body says "mutating
    and network" — true, narrower, disclosed: changing it
    forces a host-wide `--setup-agents` re-run) WHEN the caller's worktree
    carries a hook (a review round) — logged, not fatal — the leg cannot see
    from inside whether such a hook is present, so it never makes one, and
    any off-list call that EXECUTES voids. The agent-body sentence is shared
    by the research agent, whose own web tools are never called blocked.
    Hosts re-run `python3 <plugin bin>/antigravity_wrapper.py
    --setup-agents` (the `triad-antigravity-dispatch` Host setup line) after
    an upgrade that changes the agent body.
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
- **Read-audit binding.** The agy dispatch line binds the attempt's own audit
  path: `prepare` / `retry` render `env
  TRIAD_READ_AUDIT_FILE=<attempt>/read-audit.json` into it, so no two entries
  or attempts share a path. The wrapper writes the digest to exactly that path
  on every completed call, success or failure (engine side:
  the plugin `README.md` § Read-audit digest file); that file is the
  read-audit gate's only evidence source and cannot be created after the
  fact. **Custody:** the attempt's own `stderr.log` must carry the WHOLE line
  `read-audit-file: <that absolute path>` (the wrapper's timestamp prefix, the
  path percent-escaped from its filesystem bytes); `collect` checks it before
  the gate. An audit no dispatch of that attempt named (misfiled or foreign),
  and a dispatched attempt that wrote no audit, are refused with the remedy
  "prepare a NEW round"; only a genuine audit whose `stderr.log` lost its line
  is cleared by a `retry`. The leader never removes, renames or moves an
  audit. Never a bare `$AGY_READ_AUDIT_FILE` (a gate-local name, unset at
  dispatch time) and never a `${TRIAD_READ_AUDIT_FILE:-...}` fallback (it could
  name a leftover another shell left set).
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

### agy hook load check

A REQUIRED per-attempt check beside the read-audit gate: it proves the round's
PreToolUse hook loaded for this attempt's run. agy's `--agent` fails OPEN
silently, so an attempt whose hook layer is not proven has unverified
containment and does not count (measurements: `references/evidence.md`
§ agy hook load check — measurements). Run the printed `hook:` line:

```bash
python3 <skill>/lib/agy_hook.py check <abs attempt read-audit.json> <abs packet-dir>/agy-hook-r<N>.jsonl
```

Exactly these two arguments — the attempt's own read audit and the round's
hook log; any other argv is usage 64, which `collect` treats as a HOST FAULT.
Output: `HOOK_LOAD_<VERDICT> tool_steps=<n> invocations=<n> denied=<n>`, plus
` attributed=<hooked>/<must>` when more than one census row must be
attributed. `collect` records a nonzero result as the entry's reason `hook
load check failed (HOOK_LOAD_<X>, rc=<n>) — agy's --agent fails OPEN, …`.

**Attribution.** The wrapper records each vendor run's conversation ids on its
census row (`digest.attempts[].conversation_ids`); the hook logs each call's
`conversationId`. Every row of THIS audit with `tool_steps > 0` needs at least
one hook row under one of its own ids. Step counts need not match (a call the
vendor rejects at argument validation never reaches the hook); a zero-step row
certifies nothing; a hook row with no id attributes to no attempt; rows under
other ids belong to other attempts. Only hook-shaped rows (`decision`
allow|deny + `tool`) count. One hook log serves every agy entry and every
retry of the round, and another entry's census never blocks this one.

**Verdicts, in order, and their remedies.**

| Verdict (exit) | Meaning | Remedy |
|---|---|---|
| `ABSENT` (2) | no read audit | settle the read-audit gate's ABSENT first |
| `INCONCLUSIVE` (4) | broken evidence — an audit or hook log that is not a readable regular UTF-8 file, no `digest.tool_steps`, no or a malformed `digest.attempts` census, a stepped row with no recorded id, a log line that is not a hook row | check `hooks.json` in the round worktree, then prepare a new round |
| `VOID` (3) | stepped rows and zero hook invocations, or a stepped row with no hook row under any of its own ids (the check names each such attempt) | check `hooks.json` in the round worktree, then prepare a new round (a fresh hook log) |
| `INCONCLUSIVE` (4) | no stepped row and no invocation — nothing proves or disproves the hook | none here: the read-audit gate voids a read-blind leg on its own |
| `PASS` (0) | every stepped row is attributed | none |

**Four-leg profile.** `references/review-legs.four-leg.example.json` carries
THREE agy-route entries (`google-contracts`, `google-failures`,
`google-state`); they share the one hook log and are told apart by
conversation id. Dispatch the Google entries SEQUENTIALLY — three concurrent
Google calls are not verified.

## agy read-audit gate

The gate decides whether an agy attempt did the reading work. Run it BEFORE
the attempt's verdict is weighed and before any of its findings enters the
residual table; the hook load check runs beside it on the same attempt
(§ agy hook load check), and both must pass. It is a mechanical
anti-shallow-review check, not an authenticated channel: the digest is folded
from vendor stream events, so a hostile vendor process could forge its content
(owner ruling, settled — `docs/reviews/2026-07-31-agy-stream-json-residuals.md`).
The digest's shape, caps and per-attempt rows are the wrapper's
(the plugin `README.md` § Read-audit digest file); how the audit is
bound to the attempt is § agy leg, the Read-audit binding bullet.

**Inputs.** Run the `gate:` line `prepare` / `retry` printed, verbatim, once
per agy attempt:

```bash
bash <skill>/lib/read_audit_gate.sh --audit-file <abs results-r<N>/<name>/attempt-<K>/read-audit.json> "$PACKET_DIR" "$PACKET_DIR/wt-r<N>/brief.md" "$PACKET_DIR/wt-r<N>/diff.prod.patch"
```

- `--audit-file` comes first and is required: an absolute path inside the
  packet dir of exactly the shape `results-r<N>/<name>/attempt-<K>/read-audit.json`.
  There is no environment fallback and no default path.
- The required reads are the worktree brief AND the gated patch (the brief
  alone carries framing, not the code under review). The packet dir and every
  file are absolute paths that exist.
- An argv fault is exit 64 (usage), never a verdict; `collect` treats a 64 as
  a HOST FAULT (`references/triage.md` § Collect outcomes).

**The match.** A required file counts as read when its absolute path equals
the `AbsolutePath` param of a `view_file` entry in `digest.files_read` (a
`grep_search` that merely names the path does not count). `files_read` holds
only calls that succeeded; a failed or denied attempt sits in
`digest.read_attempts` and proves nothing. Every params value is truncated at
200 characters (the gate's `_CAP`, coupled to `bin/_common.py`'s
`_AGY_DIGEST_VALUE_CAP`; t5 drift-guards the pair), so a required path of 200
characters or more cannot be confirmed. The verdict is decided by jq's rc and
`files_read_omitted` only. Recorded limits: the `AbsolutePath` key is a vendor
coupling (a rename fails toward VOID / INCONCLUSIVE, never PASS), and a
range-limited view would satisfy the match on a partial read (no range params
have been observed in real digests).

**The four verdicts and their remedies.** With several files, any
INCONCLUSIVE → INCONCLUSIVE, else any VOID → VOID, else PASS. Take the remedy
the row names; never delete, move or rename anything under `results-r<N>/`
by hand — a failed attempt stays on disk beside the next one.

| Verdict (exit) | Meaning | Remedy |
|---|---|---|
| `PASS` (0) | every required file matched | weigh the verdict; verify each surviving agy cite against the round worktree first (§ agy leg, Cites) |
| `ABSENT` (2) | no audit file at the path | check the dispatch line's `env TRIAD_READ_AUDIT_FILE=…` member first — an unbound env looks exactly like a call that never completed. Then prepare a NEW round; only an attempt that never spawned agy (no `exec` line in its `stderr.log`) is cleared by `retry` |
| `VOID` (3) | a confirmed miss: a required file is not in `files_read` and `files_read_omitted` is 0 (a valid-JSON audit with no `.digest` lands here too); the answer is UNVERIFIED and is not read | `retry <packet-dir> r<N> <name> --diagnosis "<why>"` once on the unchanged basis (SKILL Flow 4) and run the lines it prints; the new attempt is judged on its own audit. Still VOID after that retry: the entry is missing (rule 13) and the round `INCOMPLETE` — no second re-dispatch; a new answer comes only from a NEW round |
| `INCONCLUSIVE` (4) | never PASS and never VOID; stderr names the cause | a CAPPED digest (`files_read_omitted > 0`): weigh `digest.attempts[]` and `digest.read_attempts[]`; if they do not settle it, a narrower packet is a NEW round. BROKEN evidence (jq could not read the file): inspect it, then prepare a NEW round. A required path of 200 characters or more: shorten the packet path and run the gate again |

**Output.** One `[gate] <VERDICT> <file>` line per evaluated file, then the
summary `READ_AUDIT_GATE_<PASS|VOID|INCONCLUSIVE|ABSENT> checked=<n> pass=<n>
void=<n> inconclusive=<n>[ unevaluated=<n>]` (`unevaluated` appears when
ABSENT or broken evidence stopped the evaluation, so anchor on the token).
`collect` runs the same line and records a nonzero result as the entry's
reason `read-audit gate failed (READ_AUDIT_GATE_<X>, rc=<n>) — an ungated agy
answer is UNVERIFIED, never agreement`; the remedy is the row above for that
token.

**Round notes.** Record `digest.denied` and the `read`-class entries of
`digest.read_attempts`: a read-class attempt naming a required file explains a
VOID (the leg tried and was blocked); a blocked write or command that merely
named the file is not a failed read. Latency (rule 11) is a secondary signal
behind this gate.

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
  call voids; the hook LOAD CHECK proves the layer loaded (§ agy hook load check).
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

  THIS leg's path is `--prompt-file` on the rendered `<attempt>/prompt.txt`,
  the same form the sibling dispatch skills' Step 1 uses (the leader writes
  the body to a file and runs one simple command with literal arguments).
  There is no asymmetry to manage:
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
  the agent's tool allowlist rather than the prompt directive alone. The presets
  list `Read, Grep, Glob` and no `Bash`, the shape that returns the dedicated
  search tools on macOS / Linux / WSL (vendor tools reference, read 2026-10-09;
  PR #13 R-AGENT-ROLES). The `Agent`
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
  (SKILL Flow 3, rule 4) — no repair path; only an admitted reply is sealed
  (§ Attempt seal). A
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
