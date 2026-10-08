# Cross-family review — per-leg dispatch contracts

Loaded on demand from `triad-cross-family-review/SKILL.md`. Read this when
dispatching a round's legs (Flow step 2), and again when an agy leg returns —
its verdict may be weighed only after the read-audit gate below passes.

## Contents

| Section | Open it when |
|---|---|
| v2 dispatch shapes | reading or sanity-checking the argv `prepare --v2` printed for an entry |
| Producer schema projection | asking what schema the vendor received, or why it differs from the canonical one |
| Verdict binding — all legs | dispatching any leg, or admitting a returned verdict |
| Google-family leg selection | resolving a google entry's route (agy; gemini = legacy compatibility) |
| agy leg | dispatching agy — model selector, read-audit binding, containment block |
| agy read-audit gate | an agy leg returned and you are about to weigh it |
| agy standing residuals | deciding whether this deployment can run the agy leg at all |
| gemini leg | a google entry resolved to the gemini route (legacy compatibility) |
| codex leg | dispatching codex — tier, review web (`--search`), worktree delivery |
| claude fresh-eye leg | dispatching the claude `Agent` leg |
| Fourth leg (LEGACY v1) | reading a v1 packet or residual row, or running `prepare` WITHOUT `--v2` — the retired `--x-leg` / `--no-x-leg` / `$TRIAD_REVIEW_X_LEGS` arms |

## v2 dispatch shapes

`prepare … --v2` PRINTS the complete invocation for every enabled non-skipped
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

- **codex** — `env TRIAD_REVIEW_LOG_DIR=<attempt>/logs python3
  <wrappers>/codex_wrapper.py --sandbox read-only
  [--search] [--reasoning <tier>] [--model <slug>] --output-schema-file
  <attempt>/schema.projected.json` + the common tail, redirected to
  `<attempt>/verdict.json` and `<attempt>/stderr.log`. `--search` follows
  the round's bound `review_web_authorized` (R-REVIEW-WEB; true under the
  owner's standing authorization, so present on every round today; absent on
  a false round, where the wrapper pins `web_search="disabled"`). Never
  `--pydantic`: v2 admission runs on the output FILE, in `verdict_v2.py`.
- **agy** — `env TRIAD_READ_AUDIT_FILE=<attempt>/read-audit.json env
  TRIAD_REVIEW_LOG_DIR=<attempt>/logs python3
  <wrappers>/antigravity_wrapper.py --sandbox read-only [--review-web]
  [--model <slug>] [--effort <tier>] --json-schema-file <attempt>/schema.projected.json` + the
  common tail, same redirections. A true `review_web_authorized` adds
  `--review-web` — the read-only research agent (the review tools plus
  `read_url_content` / `search_web`) WITHOUT the investigation web-evidence
  clause — and `prepare` writes the round's hook in its web mode; never the
  investigation `--web` (R-INVEST). The per-attempt read audit is part of
  this entry's contract, gated below.
- **gemini** — `env TRIAD_REVIEW_LOG_DIR=<attempt>/logs python3
  <wrappers>/gemini_wrapper.py --sandbox read-only
  --approval-mode default [--review-web] [--model <slug>]` + the common tail
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
  **The printed agent id is LAYOUT-QUALIFIED, exactly as on the v1 route**
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
  the exact confusion the null-`claude.agent` refusal exists to prevent;
  orphan adoption shape-checks `dispatch.json` itself. A record that
  cannot name its own agent is a broken record: `v2_print_dispatch` FAILS
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
  unescaped once and admitted from that (legacy `validate_verdict.py` pass-2
  semantics, on the same bytes), printing `NOTICE: admitted on the
  html.unescape pass`. `html.unescape` covers every spelling it knows, so
  both the NAMED (`&lt;END-VERDICT&gt;`) and the NUMERIC
  (`&#60;END-VERDICT&#62;`) forms are recognized. No escaper spelling is
  special-cased inside the RAW pass: that would admit a body with
  `&lt;`/`&gt;` entities intact from a transport that escaped angle brackets
  but not quotes, while the legacy validator unescapes the whole text — two
  validators deriving DIFFERENT objects from one reply.

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
schema while the round record still claimed an unchanged basis. `prepare …
--v2` therefore stores `projection_digest` (sha256 of the projected schema
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
(`antigravity_wrapper._validate_structured_with_trigger`) — v2 review entries
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

`LegVerdict` carries three REQUIRED binding fields — `review_id`,
`family` (`claude` | `google` | `codex`), `content_digest` (64-hex,
lowercase) — so a verdict is admissible only for the exact round and
leg it was produced for (no cross-round reuse, no leg mixups). The
obligations below are the LEGACY v1 shapes (`validate_verdict.py`, three
binding fields); a v2 round binds six fields through `verdict_v2.py` and the
printed `admit:` lines (SKILL rule 4, Flow 3). The leader's v1 obligations,
every round, every leg:

1. The PACKET FILE's head carries ONE canonical `Review metadata:`
   JSON line with the LEG-INDEPENDENT facts only — `review_id` (e.g.
   `<slug>-r<N>`), `round`, packet path. `family` and `content_digest`
   ride each leg's PROMPT as one per-leg binding line — the digest is
   the sha256 OF the packet file (it cannot live inside it) and family
   is per-leg while the packet is one file for all legs
   (`references/packet-lifecycle.md` § Packet order item 0). Instructions tell the leg to ECHO
   `review_id`/`family`/`content_digest` verbatim in its LegVerdict.
   Per-leg `family` token mapping (fixed):
   the claude fresh-eye leg echoes `"claude"`, the codex leg `"codex"`,
   and the Google-family leg — WHICHEVER CLI resolved, agy or gemini —
   echoes `"google"` (the token names the model family, not the CLI).
   The `prepare` subcommand renders the per-leg binding line and the
   echo instruction into every leg body mechanically
   (`references/packet-lifecycle.md` § Deterministic round preparation);
   a hand-built body owes the same line by hand.
2. Admission is MECHANICAL: `lib/validate_verdict.py <reply-file>
   --expected-review-id <id> --expected-family <token>
   --expected-packet <abs-packet-path>` — for the codex and agy legs' stdout JSON (claude EXCEPTION: the claude RAW reply admits ONLY via the `--admit` route below), not only
   claude's (the codex/agy wrappers' `--pydantic` enforces SHAPE at
   dispatch; the binding values are checked leader-side because the
   wrapper cannot know them). `--expected-packet` makes the tool compute
   sha256 over the packet FILE itself (a leader-supplied digest string
   could be stale/cross-round; `--expected-content-digest <hex>` is the
   mutually-exclusive raw form). The binding flags
   are all-or-nothing — any one present requires all three, and a
   flagless run is loudly labeled shape-only (NOT a gate admission). A
   mismatch is the existing INVALID-leg
   handling (v1: one re-ask, then INVALID; v2: the entry is invalid and a new
   answer needs `retry` or a new round) — never a hand-waved pass.
3. The schema also rejects a "SAFE TO MERGE" verdict carrying a
   Critical/must-fix finding (bidirectional validator, engine commit
   `397fade`); Minor / HARDENING-SUGGESTION findings MAY accompany
   SAFE — a deliberate difference from the codex-host reference, which
   has no suggestion severity.
4. **A non-repairable schema-fail preserves the blocker — it is
   never a silent leg loss.** Two
   triggers, one handling: the marked `[NONREPAIRABLE]` SAFE-arm, OR
   the BLOCKING-CONTENT probe (the failed payload's parsed-or-scanned
   content carries a Critical/must-fix finding — this fires even when
   NO validator arm ran, e.g. a co-occurring field error or a
   non-parseable envelope). Either way the wrapper
   deliberately SKIPS its schema-repair replay (a replay invites the
   leg to launder the blocker by downgrading or dropping it) and exits
   schema-fail 66 with a stderr log carrying the `[NONREPAIRABLE]`
   token and stating which trigger fired (marked arm or blocking
   content) — so grep for the token, but do not expect the ARM's
   prescriptive message on a content-triggered refusal.
   On seeing that log the leader re-dispatches ONCE with an explicit
   instruction BRANCHED on the leg's ACTUAL verdict — an unconditional
   "raise the verdict" order to a leg whose verdict was already non-SAFE
   (or whose refusal was a false-positive on quoted code) would
   MANUFACTURE verdict inflation, the mirror image of the laundering this
   rule exists to stop. The discriminator is the run-log's STRUCTURED
   payload, not a log grep: on any `[NONREPAIRABLE]`-token 66, READ the
   verdict + finding severities in the run-log's `stdout` stream (the
   vendor's `structured_output`) and branch on what they ARE. A
   `[NONREPAIRABLE trigger=…]` token also rides the wrapper's stderr, but
   it is only a HINT that a non-repairable refusal occurred — the wrapper
   later mirrors vendor bytes on its own timestamped lines (the
   read-audit digest can carry a planted `[NONREPAIRABLE trigger=arm]`
   substring), so a bare token grep is forgeable; the structured payload
   is content-agnostic and sidesteps it. Branch: the payload's verdict is
   SAFE TO MERGE while it carries a Critical/must-fix finding → "raise
   the verdict to MERGE WITH FIXES or DO NOT MERGE — NEVER downgrade a
   finding's severity"; the payload's verdict is already non-SAFE
   (a shape slip the content probe caught) → "re-emit the SAME verdict,
   findings and severities as strictly valid JSON — do NOT change the
   verdict and do NOT change any severity". Not hardening the token
   further is an accepted residual (owner decision): this whole 66 path
   is empirically near-never exercised — across 18 measured real
   schema-bound review dispatches, 18 returned valid
   JSON, the repair retry fired ONCE (a benign field-slip recovery,
   verdict intact), and the laundering path fired ZERO times; every
   laundering "occurrence" was a synthetic fixture. The run-log preserves
   the FULL vendor evidence as the leader-visible unconsolidated signal —
   on a DUAL-PAYLOAD leg the blocking object rides
   the run-log's `stdout` stream (the vendor's `structured_output`);
   `final_answer` is EMPTIED on these paths (the wrapper quarantines
   it), and the bounded copy of the divergent raw string lives in the
   run-log's `extraction_error` as "quarantined answer: …" — so
   inspect the structured payload in the stdout stream plus
   `extraction_error`, never `final_answer` (guaranteed empty exactly
   where this obligation applies). A 66 is NEVER a
   reply to fall back to: the leg's captured `.out` is quarantined
   whenever the arm is non-repairable OR the raw fallback was
   suppressed (structured_output present), and must
   not be consolidated on any 66
   regardless. Only a
   leg still failing after that one re-dispatch is terminally missing
   (rule 13), and the round record then names the run-log so the
   blocking content is never dropped on the floor — for the ADVISORY
   Google leg as much as for a gating leg.
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

**On a v2 round the resolver does this** — `roster_v2._resolve_google`, per
ENTRY, no AI judgment and no env knob: explicit `google.route` pin → the
entry's SINGLE route block when it carries only one → the host chain agy,
then gemini → skip that entry and log. A missing binary at any step skips
THAT ENTRY (never the roster) and is never agreement; the resolved route is
frozen into `.roster-r<N>.json` for the attempt, and a started entry never
switches route. The model/effort values come from that entry's `agy` /
`gemini` block (§ v2 dispatch shapes).

**Legacy v1 rounds** select it with the snippet below (`$TRIAD_GOOGLE_REVIEW_CLI`
/ `$TRIAD_GOOGLE_REVIEW_MODEL`; `<skill>` is this skill's folder). Its agy
model comes from the shipped roster data (`spec/review-legs.default.json`, the
`google` entry's `agy.model`), so the snippet names no model itself:

```bash
GOOGLE_CLI="${TRIAD_GOOGLE_REVIEW_CLI:-}"          # explicit pin wins
case "$GOOGLE_CLI" in
  antigravity) GOOGLE_CLI=agy ;;                   # accepted alias
  agy|gemini|"") ;;                                # valid values
  *) echo "[review] unknown TRIAD_GOOGLE_REVIEW_CLI='$GOOGLE_CLI' — ignoring the pin" >&2
     GOOGLE_CLI="" ;;
esac
if [ -n "$GOOGLE_CLI" ] && ! command -v "$GOOGLE_CLI" >/dev/null 2>&1; then
  echo "[review] pinned '$GOOGLE_CLI' not installed — falling through to auto-detect" >&2
  GOOGLE_CLI=""
fi
if [ -z "$GOOGLE_CLI" ]; then
  if command -v agy >/dev/null 2>&1; then GOOGLE_CLI=agy        # agy-first
  elif command -v gemini >/dev/null 2>&1; then GOOGLE_CLI=gemini # fallback
  else GOOGLE_CLI=""; fi                                         # neither
fi
# REASONING TIER: the agy/gemini default is a fast shallow model (Gemini Flash
# class), empirically useless for adversarial review, so the agy leg pins the
# Pro/High catalog selector via --model (agy's catalog encodes reasoning in the
# selector; the wrapper also passes --effort through on agy >= 1.1.10).
# PIN-FLOOR NOTE: agy < 1.1.10 silently IGNORES --model in -p runs, so the
# wrapper fail-closes a --model/--effort dispatch there (config-conflict 65).
GOOGLE_REVIEW_MODEL="${TRIAD_GOOGLE_REVIEW_MODEL:-}"
if [ "$GOOGLE_CLI" = agy ] && [ -z "$GOOGLE_REVIEW_MODEL" ]; then
  GOOGLE_REVIEW_MODEL="$(jq -r '.legs[] | select(.name == "google") | .agy.model // empty' \
    "<skill>/spec/review-legs.default.json")"   # the shipped roster's agy selector
fi                                              # gemini path stays unpinned
```

`agy` → `triad-antigravity-dispatch`; `gemini` → `triad-gemini-dispatch`; empty
→ skip the Google leg and log "Google-family reviewer unavailable; review
proceeds with claude(Agent)+codex (2-family)".

**Model rule (R-MODEL).** The model is the roster entry's value (v1: the
variable above), passed to the wrapper as given: the host runs no catalog probe
(`agy models` / `gemini models`) and never substitutes or falls back to another
model. A model the CLI refuses ends the attempt as a terminal failed-to-run
record; the user changes the roster entry. The agy stream's `init.model` is
recorded as `runtime_model`, and a value that is not byte-equal to the requested
`--model` is refused (`config-conflict` 65, answer withheld).

## agy leg

Every bullet below marked "template-rendered" describes the LEGACY v1
renderer's `agy-prompt-r<N>.txt` (pinned by `t4-prepare.sh`). A v2 round's
`prompt.txt` is rendered from the vendored clauses (`spec/prompts/leg-google.md`
— its `google-read-grant` and shape clauses), not from these pins.

- **Findings-shape pin (template-rendered).** The rendered
  `agy-prompt-r<N>.txt` carries a FINDINGS SHAPE PIN block naming the exact
  LegVerdict findings keys (`summary`/`trigger`/`context_known`; `line` =
  integer-or-null; the exact severity enum) and banning the observed aliases
  (`trigger_scenario`/`description`). Reason: agy treats a finish-schema
  validation failure as TERMINAL — no model retry; the validation report
  becomes the turn error and the COMPLETED review is quarantined (EVAL-03
  attempt, 2x identical deviation on pro-high, run-logs
  `20260820T124833Z`/`20260820T125233Z`). The pin rides at the END of the
  prompt per this leg's containment-placement rule. Pinned by
  `tests/unit/skills/t4-prepare.sh`.
- **Tool-convention pin (template-rendered).** The READ-GRANT states the
  POSITIVE reading convention:
  grep_search to SEARCH (never a shell command), file-view with the absolute
  path only — paging args (StartLine/EndLine/ContentOffset) ONLY within the
  size the tool reports, never past the end (they are VALID view_file
  arguments; paging PAST EOF, `ContentOffset N exceeds line range size N`, is
  an errored step that voids the turn). Rationale: on agy 1.1.15+ any
  errored/denied tool step is turn-terminal (upstream #827), so the prompt
  must remove every occasion for one — the codex-host product verified this
  fix class working on agy 1.1.16. Pinned by `t4-prepare.sh`.
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
  enforces — the rendered `agy-prompt-r<N>.txt` READ-GRANT (the five
  permitted tools by name, the forbidden planner / shell / write / subagent /
  browser / web tools by name, "any other call voids your whole review";
  pinned by `t4-prepare.sh`) and the agent body written by `--setup-agents`
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
  Handling on v2: `retry` re-dispatches the SAME frozen prompt and scope
  once; a narrower read scope (tighter `--diff-path` / `--tests-path`, fewer
  "cite each site" demands, `--excerpt` the hot functions into the brief) is
  a changed basis — a NEW round (R-RETRY). LEGACY v1: re-dispatch ONCE (attempt K's files renamed first: `references/packet-lifecycle.md` § Round integrity) with
  that narrower scope, then terminally missing. Consolidate the other legs
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
    an audit or hook log that is not a readable regular UTF-8 file or exceeds
    the 64 MiB evidence cap (refused before a byte is read), no
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
  - **The prompt states the same rule** (v2: the vendored `google-read-grant`
    clause; v1: the READ-GRANT block quoted below; and
    the agent body written by `--setup-agents`): any tool outside the
    allow set is BLOCKED before it runs (the agent body says "mutating
    and network" — true, narrower, disclosed: changing it
    forces a host-wide `--setup-agents` re-run) WHEN the caller's worktree
    carries a hook (a review round) — logged, not fatal — the leg cannot see
    from inside whether such a hook is present, so it never makes one, and
    any off-list call that EXECUTES voids. The agent-body sentence is shared
    by the research agent, whose own web tools are never called blocked.
    Hosts re-run `antigravity_wrapper.py
    --setup-agents` after an upgrade that changes the agent body.
- **Existence pin (template-rendered).** The
  READ-GRANT forbids opening any path that does not exist on disk, naming
  the plan-stage case explicitly (a file the BRIEF's DESIGN TEXT marks
  planned / to-be-created does not exist yet) while exempting NEW-FILE HUNKS
  in `diff.prod.patch`, which DO exist in the round worktree — it is checked
  out AT the reviewed commit, so that holds unconditionally. agy's file-view dies on a missing path
  at "convert tool call for permissions ... invalid_args" (upstream #826,
  OPEN, bug-labelled 1.1.15 + 1.1.17; reproduced WITHOUT a sandbox), and the
  errored step flips the run to ERROR. The agent body carries the same rule
  as system text; the prompt keeps it because the prompt is the
  round-specific carrier. StartLine/EndLine/ContentOffset are VALID
  view_file arguments — the failures are the model paging past EOF
  (`ContentOffset N exceeds line range size N`), not a rejected argument. Pinned by `t4-prepare.sh`.
- **Grep-scope pin (template-rendered — 1.1.17 probe matrix).**
  The READ-GRANT additionally requires grep_search's `SearchPath` to be a
  SPECIFIC subdirectory, never the repository root. Empirical basis (three
  probes on agy 1.1.17, read-audits preserved): a root-wide search on a
  large tree dies on the tool's internal ~20s timeout — vendor message
  "Grep command timed out due to the size of the codebase" — and the
  errored step then voids the turn (#827); the SAME query scoped to
  `analyzer/` passed clean (error_steps=0, rc 0). grep_search tool errors of
  this kind are SIZE-dependent timeouts on repo-root SearchPaths (Argus-class repos carry multi-app
  source checkouts under gitignored dirs), not an arg or sandbox problem
  (the sandbox-off probe failed identically; the audited calls carried
  only the official Query/SearchPath args). Policy OWNER-GATED: on agy
  1.1.17 and later an ERROR-status turn CARRIES its complete
  `result.response` — the wrapper still classifies
  rc 65 and discards it by design (record-not-trust); whether a
  schema-valid LegVerdict inside an ERROR turn should ever be admitted is
  an owner decision, not a wrapper default. Pinned by `t4-prepare.sh`.
- **Model.** When `GOOGLE_REVIEW_MODEL` is non-empty, the dispatch passes
  `--model "$GOOGLE_REVIEW_MODEL"` to `antigravity_wrapper.py` (the Pro/High
  variant — agy's catalog encodes effort in the model slug, so the slug stays
  this leg's pinned mechanism; the wrapper also passes `--effort` through on
  agy >= 1.1.10, but the catalog lists effort-suffixed selectors, so the
  leg does not add a separate `--effort`). The wrapper fail-closes a `--model`
  dispatch on agy < 1.1.10 (`config-conflict` 65 — the pin was silently VOID
  there, see the pin-floor note above): treat that exit as leg-not-run and
  surface "run `agy update`", never re-dispatch pinless to squeeze a verdict
  out of the shallow default.
- **Read-audit binding.** The SAME dispatch sets `TRIAD_READ_AUDIT_FILE` in the
  wrapper invocation's environment. On a v2 round that value is the entry's
  PER-ATTEMPT path `<attempt>/read-audit.json` (`prepare --v2` renders it into
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
  audit. On a legacy v1 round it is the round-invariant
  literal `TRIAD_READ_AUDIT_FILE="$PACKET_DIR/agy-read-audit.json"`, one
  packet dir per leg, preserve-and-cleared to its producing round's suffix by
  the next `prepare`/`capture`. The wrapper writes the read-audit digest to exactly that path on
  every completed call, success or failure (`emit_read_audit`), and that durable
  file is the gate's only evidence source. Bind it AT DISPATCH TIME: the evidence
  cannot be created after the fact, so a leg dispatched without it is
  re-dispatched. **Round-invariant name vs the reused packet dir
  (every round from r3 on would otherwise be deterministically INVALID):** the digest file keeps ONE round-free
  literal at all three sites, so at round N>=2 the PRIOR round's file
  is still on disk when round N captures — a CENSUSED file the round-N
  dispatch then overwrites, which verify reports as "round evidence
  changed" on an unmutated tree. Therefore BEFORE round N's capture it is
  preserve-and-cleared to `agy-read-audit-r<M>.json`, M = the latest captured
  round (the one that produced it). MECHANIZED:
  `review_scratch.py prepare` and `capture` both perform this rename
  automatically, whatever the label (fail-loud on a leftover with no captured
  round to attribute it to, a rename-target collision with a different file, or
  an output that is a symbolic link — in each case the round then goes to a new
  packet dir, `open` with a new slug; a move stopped between its link and
  its unlink is finished by the next `prepare` / `capture`); a hand-built
  round runs `capture` too, so no round renames it by hand between rounds. The literal path is then
  ABSENT at capture; the file the round-N dispatch writes arrives
  post-capture and rides verify's `*-read-audit.json` leg-output
  allowlist, while the preserved copy is censused and frozen as
  history. The leader never removes that file. A v1 re-dispatch of the leg
  inside the round first renames attempt K's file to
  `agy-r<N>-attempt<K>-read-audit.json` — the one hand move of the read-audit
  file a v1 round makes, beside the same rename of attempt K's `.err` and
  `-verdict.json`
  (`references/packet-lifecycle.md` § Round integrity, the re-dispatch rename) —
  so the literal path is ABSENT before every dispatch. A misbound dispatch (one
  that names another path, or a shell that never exported the variable)
  therefore leaves the path ABSENT, never an earlier attempt's or round's file
  read as this one's evidence. One shared plain literal at all THREE sites
  (this bullet's dispatch binding, the gate's own binding below, and the
  renames that clear it) — never a bare `$AGY_READ_AUDIT_FILE` (a
  GATE-local name, unset at dispatch time) and never a
  `${TRIAD_READ_AUDIT_FILE:-...}` fallback (it could name a leftover some
  other shell left set) — is what makes that guarantee hold regardless of what
  an ambient shell happens to have exported.
- **Structured verdict (`--pydantic verdict_schema:LegVerdict`).** Pass the
  same flag `triad-antigravity-dispatch` accepts for any `--pydantic` call:
  native `--json-schema` (`bin/verdict_schema.py`'s
  `model_json_schema()`), `_validate_structured` preferring the vendor's own
  schema-checked `structured_output`, one local schema-repair retry, then
  `schema-fail` (exit 66) — stdout is then the validated JSON object, and the
  leader consolidates it directly (`references/triage.md` § Consolidating
  validated LegVerdict objects). **Fold-exemption:** the structured output
  rides the stream's terminal `result` event's `structured_output` field, not
  the folded chat body the "Folded verdict" bullet below guards against — an
  incomplete/folded answer fails `LegVerdict` validation and takes the
  schema-repair path instead, so the `truncated-answer` re-dispatch below is a
  NON-CASE on this path. Keep that guard text for the non-schema fallback (a
  leg dispatched WITHOUT `--pydantic`, per the stated fallback in
  `references/triage.md`).
- **LEGACY v1 READ-GRANT block.** A v2 round's agy prompt carries the vendored
  `google-read-grant` clause (`spec/prompts/leg-google.md`) instead, with
  `<review-web-policy>` filled by the round's `review-web-permission` or
  `review-no-web` clause; the block below is the v1 renderer's only.
  (Mandatory in the v1 leg prompt; owner directive — same
  method as the codex leg; the entry file is the worktree `brief.md`, not an
  assembled packet — the CODE
  (`review_scratch.py` `_agy_read_grant`) is the SoT, this quote mirrors it —
  `tests/unit/skills/t4-prepare.sh` axis 60 ENFORCES the mirror, comparing
  the two whitespace-normalized, so any edit here that the code does not carry
  FAILS the suite).**
  **Placeholders: `review_scratch.py` renders this block with the round's REAL
  absolute worktree path, and this QUOTE is the only part of the doc the code
  renders — but it is NOT the only place `<packet-dir>/wt-r<N>` appears here. The
  gate-invocation and required-read lines further down carry the same
  placeholder and nothing expands them for you; treat every occurrence in this
  file the same way. If you
  ever hand-build a prompt or a gate command from this doc, expand every `<packet-dir>`
  placeholder — the entry file AND the gated patch — before sending: the
  read-audit gate compares `params.AbsolutePath` by exact string equality, so
  a pasted literal placeholder, or a bare filename, VOIDs a compliant leg.
  This instruction is the DOC's, not the code's — it
  stays OUTSIDE the verbatim block, because a sentence inside it that the code
  never renders is exactly the drift axis 60 exists to catch.**
  Include verbatim:
  "Read `<packet-dir>/wt-r<N>/brief.md` FIRST and ONCE with your file-read
  tool (agy: view_file; gemini: read_file) — it is the round's framing and
  your review's required entry point. TOOL ALLOWLIST (the single hardest rule
  of this review). On agy you run as the `triad-readonly-review` agent: your
  tool schema may ADVERTISE many tools, but you are PERMITTED exactly five —
  view_file, grep_search, list_dir, find_by_name, finish. Every other tool —
  manage_task (do not create task lists; keep your plan in your reasoning),
  run_command or any shell, write_to_file / replace_file_content / sed_file,
  send_message, define_subagent / invoke_subagent / manage_subagents,
  browser_* , read_url_content / search_web — is off-limits. On agy, tools
  outside the five are BLOCKED before they run by a PreToolUse hook in this
  worktree; a blocked call costs you the step and is logged — it does not void
  your review — but you cannot see from inside whether the hook loaded, so
  never make one. ANY call outside the five that EXECUTES voids your whole
  review: the caller audits every tool step and QUARANTINES the answer, so a
  complete verdict is thrown away. On gemini (the fallback Google leg) the
  five names above do not apply: use ONLY your native file-read and search
  tools, and never a shell command — the policy engine denies commands. Then
  OPEN `<packet-dir>/wt-r<N>/diff.prod.patch` — it is the GATED material and
  the caller's read audit REQUIRES it, so a review that never opens it is
  discarded even when the verdict is complete. You MAY then read anything else
  in the worktree with your file-read tool to VERIFY the brief's claims — cite
  file:line for anything you assert from a file in the tree. TOOL CONVENTION
  (on agy an errored read is tolerated as long as some read succeeds, but it
  wastes a step and is logged in the read audit, so follow it exactly): to
  SEARCH, use your search tool — agy: grep_search; gemini: search_file_content
  — never a shell command — and set its search path to a SPECIFIC subdirectory
  of the repo (for example its analyzer/ or docs/ tree), never the repository
  root: a root-wide search times out on large trees and the errored step is a
  wasted, logged read; to OPEN a file, call your file-read tool — agy:
  view_file; gemini: read_file — with its CURRENT native arguments — the
  absolute path; agy paging arguments (StartLine, EndLine, ContentOffset) are
  allowed only WITHIN the size the tool reports, never past the end of the
  file (an overshoot is an errored step — tolerated, but logged and wasted);
  and OPEN ONLY paths that exist on disk NOW — a file the brief's DESIGN TEXT
  names as planned or to-be-created does NOT exist yet, so never call your
  file-read tool on it: review its design from the brief text alone (a
  does-not-exist open is an errored step — tolerated, but logged and wasted);
  a file that appears as a new-file hunk in `diff.prod.patch` DOES exist here
  — this worktree is checked out at the reviewed commit. Do NOT read files
  outside the repo, do NOT search the web, and do NOT consult prior
  conversations or scratch space. Do NOT modify any file, do NOT change
  external state, and do NOT run commands, tests, scripts, builds, or vendor
  CLIs. Anything you did not verify against the brief or a file in the
  worktree is an open question, never an asserted finding."
  The mutation/exec sentence is part of the verbatim block on purpose: on agy the setup-once
  `triad-readonly-review` agent has no write/shell/web tool and a fallback
  run's writes/shell are denied by the vendor's headless policy (no danger
  flag), on gemini the policy engine denies — the sentence is the INTENT
  carrier the model reads, and it still covers the tools no rule can deny
  (notebook / subagent / message / browser_* family — census detection
  only); dropping it would leave those with no intent carrier at all.
  BRIEF-FIRST is load-bearing twice over: it is the mechanical read-audit
  gate's required entry (the gate below runs UNCHANGED — it takes the file as
  ARGUMENTS — BOTH `<packet-dir>/wt-r<N>/brief.md` and
  `<packet-dir>/wt-r<N>/diff.prod.patch`, which must appear in
  `files_read`; the READ-GRANT instructs both reads, because a gate that
  requires a file the leg was never told to open VOIDs a compliant leg),
  and reading them before browsing the tree keeps the gate
  decisive under the digest's 40-entry `files_read` cap.
  DISCLOSURE: with repo browsing granted,
  `files_read_omitted > 0` becomes the NORM for a leg doing real
  verification work, and the gate's confirmed-VOID arm requires
  `omitted == 0` — so VOID stays decisive only when the leg complied
  with brief-FIRST, an INSTRUCTION-LEVEL property, the same class as
  the codex read boundary (§ codex leg). A non-compliant leg lands
  INCONCLUSIVE — never a silent pass, but not a mechanical leg-not-run
  proof either; the round notes carry that judgment. Mutation
  is ABSENT on the v2 read-only path (the allowlist agent carries no
  write/shell tool; a fallback's attempts are denied by the vendor's headless
  policy without the danger flag — measured in the permission-ladder spike
  `docs/spikes/2026-08-22-agy-permission-ladder/`; § agy standing residuals), detection-only for the tools no rule can deny — so the
  round's capture/verify integrity gate stays the mutation-detection
  control of record, not a redundant belt
  (`references/packet-lifecycle.md` § Round integrity); the read/network
  egress residual is UNCHANGED (§ agy standing residuals — owner-owned).
  Rationale: agy's detection record earned the wider view — a packet-ONLY
  diet would make the leader's packet assembly this leg's ceiling, the same
  blindness the codex READ-GRANT prevents; the leg holds the whole tree,
  pinned at the reviewed commit.
  Placement: immediately before the closing instruction, never leading the
  prompt (`references/packet-lifecycle.md` § Packet order and fencing).
- **Prompt body.** On a v2 round it is `<attempt>/prompt.txt` (rendered from
  the vendored clause bytes by `lib/prompts_v2.py`); on a legacy v1 round the
  rendered `agy-prompt-r<N>.txt`. Either way it carries the round worktree
  path and its `brief.md` entry point, a read grant (v2: the vendored
  `google-read-grant` clause; v1: the READ-GRANT block above), the severity
  instruction, the verdict-selection rule and the binding line, and is passed
  with `--prompt-file <abs>`; a hand-built prompt owes the same blocks.
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
  on a v2 round `retry` re-dispatches the SAME frozen prompt once (asking for a
  more compact verdict is a changed prompt — a NEW round, R-RETRY); a second
  fold leaves the entry missing and the round `INCOMPLETE` (SKILL rule 1).
  LEGACY v1: re-dispatch ONCE asking for a COMPACT chat-returnable verdict
  (verdict + top findings with evidence, under the ~4KB fold), still
  `--sandbox read-only`; a second fold logs the leg terminally missing.
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
   census does not settle it, do not guess: on v1 re-dispatch with a narrower
   packet; on v2 a narrower packet is a NEW round. Only a failed match WITH
   `files_read_omitted == 0` is a confirmed VOID: treat it as leg-not-run. On
   a v2 round a `retry` (the same frozen prompt) clears it: the new attempt
   is judged on its own read audit and its own conversation ids.
   On a LEGACY v1 round re-dispatch ONCE (attempt K's files renamed first: `references/packet-lifecycle.md` § Round integrity) with the containment block above. A
   leg still VOID after that one re-dispatch is terminally missing this round
   (rule 13): on v2 the entry is missing and the round is `INCOMPLETE`, never
   agreed (SKILL rule 1); no second re-dispatch;
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
     bash <skill>/lib/read_audit_gate.sh [--audit-file <abs>] "$PACKET_DIR" "$PACKET_DIR/wt-r<N>/brief.md" "$PACKET_DIR/wt-r<N>/diff.prod.patch" [<more-abs-files>...]
     ```

The helper is the gate's single EXECUTABLE form: the canonical jq invocation
LIVES in `lib/read_audit_gate.sh`, where the t41/f9 self-tests lift it
verbatim and `t5-read-audit-gate.sh` owns the CLI contract. This section
stays the SPEC the helper implements. What each outcome means:

- **Digest path is DERIVED**, never accepted: the shared literal
  `$PACKET_DIR/agy-read-audit.json` — the same ONE literal the § agy leg
  dispatch binding and the renames that clear it (`prepare` / `capture`, and the
  v1 in-round re-dispatch rename) use (anti-drift: no env-var
  fallback anywhere, so an ambient
  `TRIAD_READ_AUDIT_FILE` some OTHER shell context left exported can never
  make the gate open a file nobody bound or cleared for THIS round). The
  wrapper writes it on EVERY completed call, ok or not — no stderr capture,
  no grep/sed extraction (`triad-antigravity-dispatch` § Isolation).
  **The ONE exception is the leading `--audit-file <abs>` flag**: still
  argv-only and still no env fallback, and narrow by construction — the value
  must be ABSOLUTE, live inside `$PACKET_DIR` (no symlink resolution: an audit
  outside the census'd round dir is not this round's evidence), and match
  exactly ONE of two shapes:
  - **v2 (the normal path)** — the per-attempt audit
    `results-r<N>/<name>/attempt-<K>/read-audit.json`. `prepare --v2` binds
    `TRIAD_READ_AUDIT_FILE` to that path on the agy entry's argv and PRINTS
    the matching `gate:` line; run it verbatim, once per agy attempt.
  - **v1** — an X leg's own round-suffixed audit DIRECTLY in the packet dir,
    basename `x-<name>-r<N>-read-audit.json` (§ Fourth leg).
  The STANDING `agy-read-audit.json` is never a legal override — containment
  alone cannot tell the two apart, and gating one entry on another's evidence
  is a false PASS. Every violation is a LOUD usage exit 64, never a verdict.
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
  env FIRST; only once it is sound, treat as VOID (leg-not-run). v1:
  re-dispatch once (attempt K's files renamed first: `references/packet-lifecycle.md` § Round integrity). v2 (per-attempt audit): the attempt stays a SIBLING of
  every later attempt of the round (the hook load check reads a dispatched
  attempt with no audit as INCONCLUSIVE), so prepare a NEW round — unless the
  attempt never spawned agy (no `exec` line in its `stderr.log`): the hook
  check skips it and a retry does clear it.
- **Exit 3 VOID** — a confirmed miss (`files_read_omitted == 0`). On v1:
  re-dispatch ONCE (attempt K's files renamed first: `references/packet-lifecycle.md` § Round integrity) with the containment block; still
  VOID after that re-dispatch is terminally missing this round (rule 13, no
  second re-dispatch). On v2: a `retry` clears it (the new attempt is judged
  on its own audit). (A duplicate-JSON-member refusal, spec C14, is
  schema-fail 66 with no answer, so its merged audit never reaches this gate:
  the gate runs only after an admission succeeded.)
- **Exit 4 INCONCLUSIVE** — never read as VOID and never as PASS. Five
  causes, each named on stderr: an OVERSIZED audit (over the 64 MiB evidence
  cap, measured with `wc -c` BEFORE jq reads it), a CAPPED digest (`files_read_omitted > 0` —
  weigh `digest.attempts[]` per-attempt totals + `digest.read_attempts[]`,
  and, if the census does not settle it, use a narrower packet — on v2 a
  NEW round (a retry re-renders the frozen prompt), on v1 a re-dispatch;
  there is no fuller digest, and only the FINAL attempt's raw stream is
  retained anywhere), BROKEN evidence (jq could not produce a usable
  answer — read, parse, program, or runtime error: inspect the file
  directly), a SYMLINKED digest file (refused,
  never followed — the wrapper writes a regular file it alone owns, so a
  symlink at that path is a redirect nobody's dispatch bound; note this is
  a check-then-open guard, WEAKER than `validate_verdict.py`'s
  O_NOFOLLOW read — acceptable here because the gate runs strictly after
  the agy child is reaped and no other round participant writes that path),
  or an at-or-over-cap packet path (200 characters or longer — stored in
  the digest as a PREFIX-identity that cannot be told apart from any
  same-prefix file, an exactly-cap value being possibly a longer path's
  truncation, so the gate refuses to over-claim; shorten the packet path
  and re-run; this refusal subsumes the arg-side collision case, and the
  same argument passed twice remains ONE identity, legitimately
  confirmable). Remedy for the OVERSIZED and BROKEN cases: v1 — re-dispatch
  once; v2 — the audit stays a SIBLING of every later attempt (the hook load
  check refuses it as broken evidence), so prepare a NEW round.
- **Multi-file aggregation is pinned and LOAD-BEARING**: any INCONCLUSIVE
  file → exit 4; else any VOID file → exit 3; else exit 0. The per-ARGUMENT
  over-cap refusal CAN mix with a digest-side VOID in a single run (only
  the capped/broken digest states are digest-global), so the precedence is
  what keeps a mixed round deterministic — never remove it as dead logic.
  BROKEN evidence stops the loop — later files are never evaluated. The
  summary counters count EVALUATED files only, and whenever any argument
  was NOT evaluated (the broken-evidence stop; the ABSENT/symlink/oversized refusals
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
  line per EVALUATED packet file (the ABSENT/symlink/oversized refusals evaluate
  none; the broken-evidence stop evaluates no later file), then the final
  greppable summary
  `READ_AUDIT_GATE_<PASS|VOID|INCONCLUSIVE|ABSENT> checked=<n> pass=<n>
  void=<n> inconclusive=<n>[ unevaluated=<n>]` — the
  `unevaluated` field appears exactly when some argument was not evaluated
  (ABSENT/symlink/oversized refusals, the broken-evidence stop), so anchor on
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
`gemini.model` (v2) or an owner-verified `TRIAD_GOOGLE_REVIEW_MODEL` (v1);
with neither, the CLI default runs and the round record says the review tier
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
call**, on the `--sandbox read-only` review route only (an investigation or
write dispatch keeps its single spawn). In order: the effective posture is
computed FIRST, then (1) a VERSION FLOOR — `gemini >= 0.34.0`, the release
carrying the headless policy-allow fix (PR #20639); below it the `--policy`
read-only rows do not take effect headlessly, so the posture would be a claim
rather than a control; (2) a CAPABILITY probe — `--help` must advertise
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

- **Tier.** On a v2 round the tier is the entry's `codex.reasoning` (the
  shipped default: ONE codex entry, the model the shipped default names, at
  `high`, roster data);
  the hand-built v1 example below keeps `xhigh`. A deeper tier (`xhigh`, or
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
- **DE-INLINED — pass `--cwd <round worktree>` and include the
  READ-GRANT trailer below.** `prepare` hands every leg a worktree pinned at
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
  limits ride the trailer; the round's capture/verify integrity gate
  (`references/packet-lifecycle.md` § Round integrity) is the belt —
  mutation detection, not a sandbox claim alone, decides admission.
  The READ boundary itself is INSTRUCTION-LEVEL: neither `--cwd` nor the read-only
  sandbox mechanically confines what the leg can READ — so the trailer's
  outside-repo prohibition below is a directive the integrity gate cannot
  verify, the same residual class § agy standing residuals discloses for the
  agy leg. The outbound half follows the round's web condition (`--search`
  above).
  READ-GRANT trailer (verbatim; it REPLACES the old blanket no-exec
  line for THIS leg only): "You MAY read files under the working
  directory with read-only commands (cat, sed -n, rg, ls, git diff,
  git show, git log) to verify claims beyond the brief and the two
  patches — cite file:line for anything you assert from them. Do NOT
  read files
  outside the working directory — no home-directory or dotfiles, no
  credentials, no system paths: nothing outside the repository is
  review material. Do NOT modify any file,
  do NOT change external state, do NOT run tests, scripts, builds, or
  the code under review, and do NOT invoke vendor CLIs; network only
  through your search tool." Fast-SAFE heuristic RESCOPED with this
  contract: a fast terse SAFE is a signal worth recording when the leg HAD
  code access and substantive questions — on a v2 round it is still a valid
  result, never re-dispatched (R-RETRY, SKILL rule 11). Mechanically: `prepare` renders this
  entry's entire body — `<attempt>/prompt.txt` on a v2 round,
  `codex-body-r<N>.txt` on a legacy v1 one — POINTING AT the round worktree
  plus the READ-GRANT trailer, severity instruction, verdict-selection rule
  and binding line, and PRINTS the dispatch line; run that line verbatim. The
  v1 hand-built equivalent:

  ```bash
  # body rendered by `review_scratch.py prepare` (it names the worktree);
  # --timeout 3600 = the roster value for every leg (rule 7).
  # PATHS (C28): a RELATIVE --prompt-file / --cwd
  # is not refused — the wrapper resolves it MECHANICALLY against its
  # own process-entry cwd (never the child --cwd), runs every pre-existing
  # validation unchanged, and RECORDS the resolved absolute path on the
  # summary line (`prompt_file=<abs>`) and in the audit row
  # (`prompt_file_resolved`). ABSOLUTE stays the printed form — `prepare`
  # emits nothing else — because the record is what makes a mis-resolution
  # legible after the fact, not a guarantee it cannot happen. Root CLAUDE.md
  # § Pitfalls 5 names the session-cwd hazard the rule mitigates.
  codex_wrapper.py --sandbox read-only \
    --cwd "$PACKET_DIR/wt-r<N>" \
    --reasoning xhigh --timeout 3600 \
    --pydantic verdict_schema:LegVerdict \
    --prompt-file "$PACKET_DIR/codex-body-r<N>.txt"
  # --cwd = the repo the READ-GRANT trailer opens for verification reads
  # (the READ-GRANT contract above); writes stay sandbox-blocked.
  # (--reasoning max only on a designated escalation round)
  # (the wrapper itself appends --ignore-rules on every posture)
  # (v1 hand-built shape: no --search; a v2 round adds it from its bound web condition)
  # (v2 replaces --pydantic with --output-schema-file <attempt>/schema.projected.json
  #  and adds --attempt <K> — § v2 dispatch shapes)
  ```

  For a HAND-BUILT body (the fallback path) the equivalent inline form is
  `--prompt "$(cat -- "$review_body")"` — command substitution at the
  call site:

  **Structured verdict (`--pydantic verdict_schema:LegVerdict`).** codex-strict
  `--output-schema` massage enforces the shared `LegVerdict` shape
  (`bin/verdict_schema.py`) natively; stdout is then the
  validated JSON object, not free prose — the leader consolidates it directly
  (`references/triage.md` § Consolidating validated LegVerdict objects). A
  submit-time schema refusal is `schema-rejected` (exit 67, caller fixes the
  massage); a post-hoc validation failure that survives the one schema-repair
  retry is `schema-fail` (exit 66). EXCEPTION first (§ Verdict binding
  obligation 4): a 66 whose wrapper
  stderr carries the `[NONREPAIRABLE]` token — the marked SAFE-arm OR a
  BLOCKING-CONTENT refusal (the dominant trigger: the reply's
  content carries a Critical/must-fix finding, e.g. a DO-NOT-MERGE
  verdict with a shape slip; NO arm message appears in that case) — is
  a reply whose blocking content must be preserved: the leader owes the
  obligation-4 TRIGGER-BRANCHED re-dispatch (SAFE-arm → "raise the
  verdict"; content-triggered → "re-emit the SAME verdict and
  severities as valid JSON"), with the reply evidence preserved in the
  run-log (inspect the structured payload in the run-log's stdout
  stream, not only final_answer), BEFORE the
  leg may be logged terminally missing. Every OTHER 67/66 — one with NO
  `[NONREPAIRABLE]` token in the stderr evidence — is handled as
  a terminally-missing leg for the round (rule 13), never as a prose
  reply to fall back to.

  Keep `$(cat body.txt)` OUT of a single-quoted heredoc BODY — i.e.
  `--prompt "$(cat <<'TRIAD_CODEX_PROMPT_EOF'` … a line containing
  `$(cat body.txt)` … `TRIAD_CODEX_PROMPT_EOF)"`. The heredoc is literal, so
  that inner `$(...)` is never expanded and codex receives the uninterpreted
  string `$(cat ...)`. (The sibling dispatch skills' Step 1 uses the heredoc
  shape for a literal prompt body, each with its own collision-resistant
  `TRIAD_<CLI>_PROMPT_EOF` terminator. THIS leg's normal path is
  `--prompt-file` on the rendered `codex-body-r<N>.txt`; the hand-built
  fallback inlines through `$(cat -- "$review_body")` — both are
  collision-free precisely because
  there is no heredoc to terminate early.) There is no asymmetry to manage:
  every leg — codex, agy/gemini and claude — is pointed at the SAME
  round worktree and enters through the same `brief.md`, so the transport is
  uniform and the bytes each leg judges are identical. That identity is what the
  binding's `content_digest` and cross-family corroboration both rest on.

## claude fresh-eye leg

- **Identity (v2).** The leader spawns EXACTLY the printed `subagent_type`
  (§ v2 dispatch shapes). Under a true web condition — every v2 round under
  the owner's standing authorization — that is the named preset's `-web` twin
  (`cross-family-review-reviewer-web`, `-high-web`, `-max-web`; frontmatter
  `tools: Read, Grep, Glob, WebSearch, WebFetch`, the preset's model and
  effort); under a false condition it is the base preset itself.
- **Identity (LEGACY v1, and the base preset of a false-condition v2
  round).** `subagent_type: triad-dispatch:cross-family-review-reviewer` — the dedicated
  read-only reviewer agent (`agents/cross-family-review-reviewer.md`,
  frontmatter `tools: Read, Grep, Glob`), so rule 7's no-execute contract rides
  the agent's tool allowlist rather than the prompt directive alone. The `Agent`
  tool exposes no per-call `tools` allowlist, so a plain
  `subagent_type: general-purpose` Agent would fall back to that advisory
  directive; the frontmatter pin IS the mechanism. (The shipped claude-host
  plugin rewrites this to the plugin-scoped
  `subagent_type: triad-dispatch:cross-family-review-reviewer`, so a consumer's
  same-named project agent cannot shadow the read-only plugin reviewer.)
- **Tier.** On v2 the tier is that of the preset the entry's `claude.agent`
  names; its `-web` twin carries the same model and effort. The base preset's
  frontmatter pins the current model (its `model:` line) and `effort: xhigh`. Leave
  the model out of session inheritance: an unpinned agent inherits the leader's
  SESSION model and can silently run a heavier tier such as fable, which is out
  of the review rotation. Escalation for a very-important AND algorithmically
  complex round = `subagent_type: triad-dispatch:cross-family-review-reviewer-max` (identical
  body, `effort: max`; on v2 the entry's `claude.agent` names it and a true web
  condition spawns `-max-web`). Effort is frontmatter-fixed with no per-invocation
  override, so the sibling definition IS the escalation mechanism. A THIRD
  sibling, `cross-family-review-reviewer-high` (identical body, `effort:
  high`), is the second claude arm (evidence:
  `docs/reviews/2026-09-06-claude-effort-high-vs-xhigh-campaign.md`). On a v2
  round the `-high` sibling is an ORDINARY roster entry — `x-claude-high`, whose nested
  `claude.agent` block names this `-high` sibling, carried by the project
  override `.claude/triad-review-legs.json`; its `acceptance` is DATA
  and any verdict from it other than SAFE TO MERGE keeps the round non-agreed like any entry's (SKILL
  rule 1), and `--x-leg` is refused on `--v2`. On a legacy v1 round it is
  dispatched as a fourth leg — the RECOMMENDED default entry of the
  fourth-leg config file (`{"name": "x-claude-high",
  "vendor": "claude", "agent": "triad-dispatch:cross-family-review-reviewer-high"}`; in a
  plugin install the agent id carries the plugin scope), or typed for one round
  as `prepare … --x-leg x-claude-high:claude:cross-family-review-reviewer-high` (in a plugin install type the SCOPED id: `x-claude-high:claude:triad-dispatch:cross-family-review-reviewer-high` — a bare id is shadowable by a consumer's same-named project agent)
  (an explicit `--x-leg` replaces the file's legs for that round, so every leg
  wanted must be typed) — never as the standing claude leg. Both claude arms
  read the same packet bytes and the same family template; only the binding
  `review_id` differs (§ Fourth leg), so a verdict difference is an EFFORT
  difference, never a framing one. Every preset names the model by the `opus`
  alias (Claude Code resolves it to the latest Opus; an older model is not
  selectable). These three and their `-web` twins are the CLOSED list a v2
  entry may name (C12);
  `prepare` binds the spawned file's sha256 (with the model and effort it
  pins), and `collect` / `retry` refuse a changed or missing file — a new
  round (C19).
- **Prompt.** On a v2 round the leg receives the printed `prompt.txt`
  unchanged — the vendored shared clauses (evidence-centred independent
  review, no severity deflation or inflation, the verdict-selection rule); the
  leader adds no persona, intensity request or predicted-defect list (SKILL
  rules 10-11, R-PROMPT). Its depth lever is the preset's frontmatter effort.
  The LEGACY v1 claude prompt (`_render_claude_prompt`) keeps its own text.
- **Output contract (structured verdict, no wrapper) — LEGACY v1.** On a v2
  round the printed `prompt.txt` already carries the v2 verdict shape (the
  vendored `claude-verdict-shape` clause) and the leader appends nothing (SKILL
  rule 10). On v1 this leg has no
  `--pydantic` plumbing to enforce a schema, so the LEADER'S dispatch prompt
  carries the contract instead: append the `LegVerdict` shape
  (`bin/verdict_schema.py` — the REQUIRED binding fields
  `review_id`/`family`/`content_digest` (this leg echoes
  `family="claude"`; § Verdict binding above), then `verdict`,
  `criteria_checked`,
  `findings[].{file,line,severity,summary,trigger,context_known}`, the exact
  token sets from `references/triage.md`) as the closing instruction, with an
  explicit "reply with ONLY that JSON object, no markdown fence, no
  surrounding prose" directive — the same shape codex/agy get natively,
  mirroring how the wrapper-repair analyzers carry a static
  `output_schema (JSON, inline)` contract in their own agent body. The
  prompt also carries this leg's binding values (review_id, family,
  content_digest) to echo verbatim. **LEGACY v1 (a v2 round admits through
  the printed `verdict_v2.py --admit` line instead — SKILL Flow 3, rule 4).**
  The leader validates the reply with the BOUND admission — `lib/validate_verdict.py
  <reply-as-a-file> --expected-review-id <id> --expected-family claude
  --expected-packet <abs-packet-path>` (§ Verdict binding obligation 2;
  a flagless call is shape-only and is NOT an admission) — before
  consolidating it. **The ONE authoritative claude-leg admission command
  (a plain invocation without `--admit` is not an admission for this leg;
  `prepare` prints this command with the real values):**
  `validate_verdict.py --admit <claude-rN.json> --expected-review-id …
  --expected-family claude --expected-packet … --end-marker
  '<END-VERDICT>' --admitted-out <claude-rN-verdict.json>` — no repair
  path; the tool never rewrites the raw file; `--admitted-out` writes the
  TOOL-normalized canonical object (success only; never overwrites —
  byte-identical re-run = idempotent rc 0, different content refused) that
  the consolidation jq loop reads. A reply that fails
  to validate is the v1 INVALID-leg chain STATED in `references/triage.md`
  § A non-SAFE verdict at the merge gate (its definitional home): **one TARGETED re-ask that
  NAMES the defect and quotes the no-change clause — never a verbatim
  "re-emit unchanged" request (it anchors the model to its own defective
  output; measured) — then terminal INVALID.** A
  leader-completed, leader-repaired, or leader-reconstructed reply is
  NEVER admissible.
- **Rendered prompt + reply transcription.** On a LEGACY v1 round `prepare`
  renders this leg's full prompt as `claude-prompt-r<N>.txt` (on v2 it is
  `<attempt>/prompt.txt` from the vendored clauses, no adversarial preamble) —
  adversarial preamble, packet
  path, severity instruction, verdict-selection rule, binding line, and
  the inline LegVerdict contract above — so the leader dispatches the
  `Agent` with that content (it is small: paste it, or have the agent
  Read the file first; either way the file is the censused input).
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
  RAW-STAGING RULE (v1 rounds; **a v2 round replaces it — see the note
  below**): on a v1 round the raw reply staged for VERBATIM MATERIALIZATION
  goes in the session SCRATCHPAD, never the packet dir (a raw file inside the
  packet fails `verify` as an uncovered non-output), and its name must carry the
  GATE SLUG + round — `<gate-slug>-claude-r<N>.raw` — with the
  write → materialize-verbatim → `--admit` chain run in ONE sitting:
  a bare `claude-r<N>.raw` name is REUSED across same-session gates,
  and a later gate can materialize the EARLIER gate's stale bytes (the
  binding validator refuses them — review-ID mismatch — as the backstop,
  but slug-scoped naming PREVENTS the hazard instead of catching it). DISCLOSED residual: a reply
  whose string fields INTENTIONALLY spell HTML entities is
  indistinguishable from transport escaping after one unescape — when a
  finding's exact bytes matter, resolve against the agent transcript.
  (The reviewer agent is Read/Grep/Glob-only, so a
  write-your-reply-to-a-file contract is NOT available — leader-side
  transcription is the only path, hence the caveat.)
  **v2 raw path.** On a `--v2` round the raw reply's home is the entry's own
  attempt dir, `<attempt>/raw.json`, and the admitted object is
  `<attempt>/admitted.json` — both printed by `prepare`. That is NOT the
  scratchpad hazard the rule above guards: the whole `results-r<N>/` tree is
  LEG OUTPUT by census rule (`references/packet-lifecycle.md` § Per-entry
  results tree), so a raw reply there cannot fail `verify` as an uncovered
  file, and the path already carries the round, the entry name and the
  attempt number, which is exactly what the gate-slug naming was buying.
  Everything else is unchanged: write VERBATIM, never de-escape by hand, and
  let `--admit` do the single mechanical unescape.
- **Agent definitions and the session.** A NEW definition file registers
  mid-session (measured on a desktop build: the harness announced it and a
  smoke dispatch ran on it — transcript `effort: high`); whether an EDITED frontmatter
  re-loads mid-session is unmeasured. Before the first gate that uses a new or
  re-tiered sibling, check the Agent tool's available-types list, and prove
  the tier from the transcript's `effort` field (the campaign's fingerprint
  column).

## Fourth leg (LEGACY v1 — `prepare` without `--v2`)

**Replaced by the v2 named roster on a `--v2` round (SKILL.md rule 1 +
§ Legacy v1 rounds).** On a `--v2` round there is no "fourth leg": every reviewer is an
ordinary roster entry, `acceptance` is data, and the arms below
(`--x-leg` / `--no-x-leg` / `$TRIAD_REVIEW_X_LEGS` / the user-scope file) are
REFUSED (exit 2). This section is the contract for rounds prepared WITHOUT
`--v2`, and the reference for reading a v1 packet or residual row.

The v1 fourth leg is an ADVISORY extra reviewer the skill USER configures in
a JSON FILE, rendered by `prepare` from the SAME packet as the standing legs
(same bytes, same `content_digest`, the same family template), so a
difference in its verdict is a difference in the MODEL or the TIER, never in
the framing. On a v1 round it never gates and never replaces a family.

**Recommended default (owner decision, ten-round evidence
`docs/reviews/2026-09-07-design-campaign-gate.md`):** the claude `high`
comparison arm as a second claude arm (8 must-fix the gating claude arm
missed, 2 of them found by no other leg). The Google Flash tier is not a
standing fourth leg — 0 unique blocking defects over the same ten rounds —
and stays on file `enabled: false`. Whenever a Flash leg IS configured, Pro +
Flash agreement is ONE family (`references/triage.md` § Countable stop rules).

**Config file (pure JSON, no comments) — `references/review-legs.example.json`
ships this file with every bare claude `agent` id rewritten to the
plugin-scoped spelling (`triad-dispatch:<agent>`):**

    {
      "schema": "triad-review-legs.v1",
      "x_legs": [
        {"name": "x-claude-high", "vendor": "claude",
         "agent": "triad-dispatch:cross-family-review-reviewer-high", "enabled": true},
        {"name": "x-agy-flash", "vendor": "agy",
         "model": "REPLACE-WITH-CURRENT-FLASH-SLUG", "effort": "high",
         "enabled": false}
      ]
    }

- `schema` MUST be `"triad-review-legs.v1"`; `x_legs` MUST be a list — an
  EMPTY list is an explicit "no fourth leg this round" (its own NOTE).
- Per entry: `name` (required, `x-<lowercase-alnum>[-part]…`), `vendor`
  (required, `agy|gemini|codex|claude`), `enabled` (optional bool, default
  true), and EITHER `agent` (claude vendor ONLY, and REQUIRED there — a Claude
  Code agent id, which may carry a plugin scope `<plugin>:<agent>`; an omitted
  id would resolve to the layout-derived DEFAULT, i.e. the GATING reviewer, so
  a config entry — enabled or disabled — must name its arm explicitly,
  recommended `cross-family-review-reviewer-high`) OR `model` (+ optional
  `effort`) for the other vendors. Model slugs
  and agent ids are DEPLOYMENT values in this file, never pinned in code
  (`~/.claude/CLAUDE.md` § Web search rules): when the vendor retires a slug,
  edit the file. The SHIPPED template therefore carries the placeholder
  `REPLACE-WITH-CURRENT-FLASH-SLUG` for its (disabled) Flash entry rather than
  a dated slug that rots — a deployment fills it in with the tier it wants.
- A DISABLED entry runs the SAME parser as an enabled one — name regex, vendor
  set, per-vendor effort vocabulary, the claude rules, and duplicate names
  across the enabled/disabled boundary — so a leg kept on file for a later
  round cannot rot; it is then dropped from the rendered set and its name is
  recorded in the round record's `x_disabled`.
- No structured field (`name`, `vendor`, `model`, `effort`) may contain `':'`
  — the entry is round-tripped through the colon-joined leg spec, so a colon
  there silently re-partitions the leg. The claude `agent` is the ONE field that may carry a colon (the plugin scope `<plugin>:<agent>`), and its SHAPE is checked at the boundary: a bare id or exactly ONE plugin-scope colon, every segment `[A-Za-z0-9._-]+` — so `a:b:c`, `:`, `::`, `x:` and whitespace are refused naming the `agent` field; it may not END with an effort token (`low|medium|high|xhigh|max`) — that vendor has no effort field at all.
- The PROJECT config file is trusted at the SAME level as the reviewed source
  it sits beside — whoever can write
  `<source-repo>/.claude/triad-review-legs.json`
  can already write the code under review — and the leader reads the agent id
  on the printed dispatch line before spawning it.
- The SHIPPED plugin copy of `references/review-legs.example.json` carries the
  PLUGIN-SCOPED claude agent id (`<plugin>:<agent>`, rewritten by the
  exporter); a consumer whose project defines a same-named agent must scope the
  id explicitly, or its own agent silently shadows the reviewer.
- Every refusal fires BEFORE `prepare`'s first mutation and NAMES THE FILE: a
  wrong `schema`, an unknown top-level or per-entry key, a non-object entry,
  non-JSON bytes, a SYMLINKED config file, `agent` on a non-claude vendor, `model`/`effort` on claude, both `agent` and `model`, an OMITTED `agent` on the claude vendor, an `agent` failing the shape rule above, plus every existing `--x-leg` spec refusal (name regex, vendor set, per-vendor effort vocabulary, duplicate name, claude-effort ban) — ALL entries, enabled or disabled, run through the same parser. One more exit-2 class belongs to the USER-config probe, not the file: when that probe is DECISIVE (no flag, no project file) and the home directory cannot be resolved (`Path.home()` fails, or `HOME` is not absolute, with `XDG_CONFIG_HOME` unset or invalid), `prepare` refuses naming the cause; a flag arm never READS the user config to decide the round (it only probes it non-decisively to mirror it on stderr), so `--x-leg` / `--no-x-leg` bypass this class (a non-decisive probe turns the same failure into a stderr NOTE).

**Precedence per round** (exactly one source ARM fires, its NOTE on stdout;
every ignored source is mirrored to stderr):

1. `prepare … --x-leg <spec>` (repeatable, explicit wins) / `--no-x-leg`
   (three standing legs only) — the two together are refused (exit 2);
2. PROJECT `<source-repo>/.claude/triad-review-legs.json` — read from the
   SOURCE repo `prepare` names as its SECOND POSITIONAL (the live checkout
   holding the reviewed history), never from the round tree the command
   creates under the packet dir;
3. USER `$XDG_CONFIG_HOME/triad/review-legs.json`, falling back to
   `~/.config/triad/review-legs.json` when that variable is unset, empty or
   RELATIVE (a relative value is invalid and ignored — XDG Base Directory
   Specification 0.8; the ignored value is named on stderr);
4. `$TRIAD_REVIEW_X_LEGS` — **DEPRECATED** (`docs/setting_vs.md` § 6.2b). It
   still works when no config file exists, and its NOTE says DEPRECATED; move
   the value into a config file.
5. Nothing: `NOTE — no fourth leg configured this round (three standing legs)`.
   That is information, NOT a defect — advisory legs are the deployment's
   choice.

A config CANDIDATE the probe cannot even look at (a mode-000 parent
directory) aborts the round ONLY when it is the candidate that DECIDES the arm
— the project file always, the user file when no project file exists. Any other
unreadable candidate, and every candidate under an explicit `--x-leg` /
`--no-x-leg`, is a stderr NOTE (`config candidate <path> unreadable (<errno>)
— not consulted`): a flag arm is never abortable by a broken config directory.

**The bypass NOTE names a v2 roster.** When an explicit `--x-leg` /
`--no-x-leg` skips an EXISTING project file, the stderr line
`NOTE — fourth leg config <path> ignored this round: <flag> wins` appends
` — this file is a v2 ROSTER; a roster-driven round is \`prepare … --v2\``
whenever that file's top-level `schema` reads `triad-review-legs.v2`
(`review_scratch._ignored_config_roster_hint`). The two documents share ONE
path, so "the file was ignored" alone would be true and useless for an
operator who migrated it and then typed `--x-leg`: the file is not a
fourth-leg config at all, and the command that reads it is `prepare … --v2`.
The v1 LOADER path carries the same hint; this arm needs its own because the
explicit flag skips the load. The hint
REFUSES NOTHING — this arm is deliberately non-decisive, so every probe
failure (unreadable, non-regular, oversized, not JSON, not an object) yields
no hint at all, and the read is hardened the same way the real readers are
(lstat + `O_NOFOLLOW` + `O_NONBLOCK` + an fstat re-check + a bounded read),
so a FIFO or symlink planted at that path can neither hang nor redirect a
round nobody asked to configure.

A gemini fourth leg WITH an effort field additionally prints its effort NOTE.
`.x-legs-r<N>.json` records `x_source` (`flag|config|env|suppressed|null`),
`x_config_path` (absolute or null) and `x_disabled` on EVERY round.

**Contract:** advisory whenever configured; the read-audit gate stays
MANDATORY for an
agy fourth leg (a gemini override writes no audit — § gemini leg)
(`lib/read_audit_gate.sh --audit-file <its own x-…-r<N>-read-audit.json>`
— an ungated agy fourth leg is an UNVERIFIED answer); `admission-refused` (65)
takes the same one-retry-then-missing rule as the standing agy leg, with the
attempt-1 artifacts renamed `<name>-r<N>-attempt1-*`; a failed fourth leg
never delays the round.

- **Binding identity.** The one value the fourth leg does NOT share with the
  standing leg is `review_id`: the fourth leg is bound to
  `<review-id>.<x-name>` (e.g. `<slug>-r1.x-agy-flash`), rendered into its
  prompt's binding line and recorded in `.x-legs-r<N>.json`. The packet's own
  `Review metadata:` line is inside the content digest and therefore always
  names the STANDING round id, so an X render carries one extra sentence
  telling the reviewer which of the two ids to echo. Admission runs
  `validate_verdict.py` with the X id, so a Flash verdict saved under the Pro
  leg's name is INVALID BY BINDING — the mechanical check, not leader
  vigilance, keeps the comparison honest. (The separator is `.` and not `+`:
  `LegVerdict.review_id` is constrained to `[A-Za-z0-9][A-Za-z0-9._-]*`, so a
  `+` would schema-fail every X verdict at the wrapper.)

- **Naming.** `x-<lowercase-alnum>[-part]…`. Input:
  `<name>-prompt-r<N>.txt` (agy / gemini / claude) or `<name>-body-r<N>.txt`
  (codex). Outputs: `<name>-r<N>-verdict.json`, `<name>-r<N>.err`,
  `<name>-r<N>-read-audit.json` (agy), `<name>-r<N>-raw.json` (claude) — all
  inside the leg-output allowlist (X outputs are matched by an explicit
  basename SHAPE, never a path-spanning glob —
  `references/packet-lifecycle.md` § Round integrity).
- **model / effort are DISPATCH-TIME values** the leader types; nothing in
  this skill pins a vendor catalog slug (`~/.claude/CLAUDE.md` § Web search
  rules). Effort vocabulary: agy / gemini `low|medium|high`, codex
  `low|medium|high|xhigh|max` (default `xhigh`); for the claude vendor the
  MODEL field is an AGENT TYPE and effort is not accepted — effort is
  frontmatter-fixed on the agent, so a different tier IS a different agent id
  (the shipped reviewer presets: `cross-family-review-reviewer` xhigh, `-max`,
  `-high` — § claude fresh-eye leg, SKILL rule 15).
  A claude agent id may carry a plugin scope, so for that vendor EVERY field
  after the vendor rejoins as one id (`x-c:claude:<plugin>:<agent>`); for the
  other vendors a fifth field is a loud "too many fields" refusal. Because
  that rejoin swallows any trailing field, a FINAL segment that is exactly an
  effort token (`low|medium|high|xhigh|max`) is refused outright with the
  same explanation — otherwise `x-c:claude:<agent>:high` would look accepted
  while nothing carried the tier. An all-empty remainder (`x-c:claude::`) is
  an EMPTY id, not an id spelled `:`, and falls back to the default. When the
  model slot is empty the default id is LAYOUT-DERIVED: in a plugin install
  the reviewer agent scoped with the plugin's own manifest name (a bare name
  is shadowable by a consumer's same-named project agent), in the dev tree the
  bare reviewer-agent name. In a plugin install a manifest that is unreadable,
  not JSON, or without a non-empty string `name` is a LOUD failure (exit 2
  naming the manifest), never a silent fall back to the shadowable bare
  name.
- **Dispatch shapes** (printed in full by `prepare`, values elided here):
  - agy — `env TRIAD_READ_AUDIT_FILE=<dir>/<name>-r<N>-read-audit.json
    python3 <…>/antigravity_wrapper.py --sandbox read-only --cwd <worktree>
    [--model …] [--effort …] --timeout 3600 --pydantic
    verdict_schema:LegVerdict --prompt-file <input> > <verdict> 2> <err>`;
    gate it with `lib/read_audit_gate.sh --audit-file <its own read audit>
    <packet-dir> <packet-dir>/wt-r<N>/brief.md <packet-dir>/wt-r<N>/diff.prod.patch`.
  - gemini — the same shape through `gemini_wrapper.py`, minus the read-audit
    env (that wrapper writes none) and minus `--effort` (it exposes no such
    flag; `prepare` prints a NOTE when one was recorded).
  - codex — `python3 <…>/codex_wrapper.py --sandbox read-only --cwd
    <worktree> [--model …] --reasoning <effort or xhigh> --timeout
    3600 --pydantic verdict_schema:LegVerdict --prompt-file <body> > <verdict>
    2> <err>`.
  - claude — no wrapper: spawn `Agent` with the agent id above (the model
    field, else the layout-derived default) on the rendered prompt, save the final
    message VERBATIM to `<name>-r<N>-raw.json`, then admit it with
    `validate_verdict.py --admit … --expected-family claude … --admitted-out
    <name>-r<N>-verdict.json` (the claude-leg RAW-STAGING and no-manual-
    de-escape rules above apply unchanged).
- **A failed fourth leg never blocks the round** — record it in the comparison
  record and consolidate the three families as usual.
- **Machine record.** `.x-legs-r<N>.json` (`round`, `x_source`
  (`"config"` / `"env"` / `"flag"` / `"suppressed"` / `null`),
  `x_config_path` (the ABSOLUTE path of the file that configured the round, or
  `null`), `x_disabled` (the names the file kept switched off, `[]` when
  none), then per leg `name`,
  `vendor`, `family`, `model`, `effort`, `prompt_file` (a BASENAME — the
  record already lives in the packet dir), `review_id`) is written by EVERY
  `prepare` — `legs: []` with the source that explains why when the round
  carried no fourth leg, so deliberate suppression, an unconfigured round and a
  config file that declares none are distinguishable to a later audit. It lands with the round's
  other inputs, before capture, so the census covers it. It is round evidence:
  never hand-removed, even for an abandoned leg
  (`references/packet-lifecycle.md` § Round integrity).
