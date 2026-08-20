# Cross-family review — per-leg dispatch contracts

Loaded on demand from `triad-cross-family-review/SKILL.md`. Read this when
dispatching a round's legs (Flow step 2), and again when an agy leg returns —
its verdict may be weighed only after the read-audit gate below passes.

## Contents

| Section | Open it when |
|---|---|
| Verdict binding — all legs | dispatching any leg, or admitting a returned verdict |
| Google-family leg selection | choosing between `agy` and `gemini` for this round |
| agy leg | dispatching agy — model selector, read-audit binding, containment block |
| agy read-audit gate | an agy leg returned and you are about to weigh it |
| agy standing residuals | deciding whether this deployment can run the agy leg at all |
| gemini leg | gemini is the resolved Google leg |
| codex leg | dispatching codex — tier, `--search`, inline packet |
| claude fresh-eye leg | dispatching the claude `Agent` leg |

## Verdict binding — all legs (adopted 2026-08-10, codex-host 0.2.533)

`LegVerdict` carries three REQUIRED binding fields — `review_id`,
`family` (`claude` | `google` | `codex`), `content_digest` (64-hex,
lowercase) — so a verdict is admissible only for the exact round and
leg it was produced for (no cross-round reuse, no leg mixups). The
leader's obligations, every round, every leg:

1. The PACKET FILE's head carries ONE canonical `Review metadata:`
   JSON line with the LEG-INDEPENDENT facts only — `review_id` (e.g.
   `<slug>-r<N>`), `round`, packet path. `family` and `content_digest`
   ride each leg's PROMPT as one per-leg binding line — the digest is
   the sha256 OF the packet file (it cannot live inside it) and family
   is per-leg while the packet is one file for all legs
   (`references/packet-lifecycle.md` § Packet order item 0; adopt-gate
   r2 removed the older wording that put all three in the packet
   line). Instructions tell the leg to ECHO
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
   --expected-packet <abs-packet-path>` — for EVERY leg's JSON, not only
   claude's (the codex/agy wrappers' `--pydantic` enforces SHAPE at
   dispatch; the binding values are checked leader-side because the
   wrapper cannot know them). `--expected-packet` makes the tool compute
   sha256 over the packet FILE itself (adopt-gate r1: a leader-supplied
   digest string could be stale/cross-round; `--expected-content-digest
   <hex>` remains as the mutually-exclusive raw form). The binding flags
   are all-or-nothing — any one present requires all three, and a
   flagless run is loudly labeled shape-only (NOT a gate admission). A
   mismatch is the existing INVALID-leg
   handling (one re-ask, then INVALID) — never a hand-waved pass.
3. The schema also rejects a "SAFE TO MERGE" verdict carrying a
   Critical/must-fix finding (bidirectional validator, engine commit
   `397fade`); Minor / HARDENING-SUGGESTION findings MAY accompany
   SAFE — a deliberate difference from the codex-host reference, which
   has no suggestion severity.
4. **A non-repairable schema-fail preserves the blocker — it is
   never a silent leg loss (adopt-gate r2, generalized r5/r6).** Two
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
   further is an accepted residual (adopt-gate r9, owner decision C):
   this whole 66 path is empirically near-never exercised — across the
   adopt-gate's 18 real schema-bound review dispatches, 18 returned valid
   JSON, the repair retry fired ONCE (a benign field-slip recovery,
   verdict intact), and the laundering path fired ZERO times; every
   laundering "occurrence" was a synthetic fixture. The run-log preserves
   the FULL vendor evidence as the leader-visible unconsolidated signal —
   on a DUAL-PAYLOAD leg (adopt-gate r4/r5) the blocking object rides
   the run-log's `stdout` stream (the vendor's `structured_output`);
   `final_answer` is EMPTIED on these paths (the wrapper quarantines
   it), and the bounded copy of the divergent raw string lives in the
   run-log's `extraction_error` as "quarantined answer: …" — so
   inspect the structured payload in the stdout stream plus
   `extraction_error`, never `final_answer` (guaranteed empty exactly
   where this obligation applies). A 66 is NEVER a
   reply to fall back to: the leg's captured `.out` is quarantined
   whenever the arm is non-repairable OR the raw fallback was
   suppressed (structured_output present — the r4 widening), and must
   not be consolidated on any 66
   regardless. Only a
   leg still failing after that one re-dispatch is terminally missing
   (rule 13), and the round record then names the run-log so the
   blocking content is never dropped on the floor — for the ADVISORY
   Google leg as much as for a gating leg.

## Google-family leg selection

agy and gemini share the Gemini backend (same family), so exactly ONE of them is
the Google-family leg. Select it deterministically, with no AI judgment:

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
# REASONING TIER (a review-only override of the no-model-pin rule): the agy/gemini
# default is a fast shallow model (Gemini Flash class), empirically useless for
# adversarial review — it finds nothing the deeper tier catches. agy's catalog
# encodes reasoning in the MODEL VARIANT slug, so force the Pro/High variant via
# --model. (Since agy 1.1.10 a working --effort low|medium|high also exists —
# the wrapper passes it through — but the catalog still lists effort-suffixed
# selectors, so the slug stays this leg's pinned mechanism; the pre-1.1.10
# thinkingLevel param was stripped/buggy — antigravity issue #1675, now fixed.)
# Env-overridable; verify it still exists (Google renames tiers) and fall back
# to the default + log if absent.
# PIN-FLOOR NOTE (2026-08-07): before agy 1.1.10, --model was silently IGNORED
# in -p runs (default-model fallback) — so a pre-1.1.10 "pinned" leg may have
# been served by the shallow default (identity caveat below was LIVE). The
# wrapper now fail-closes a --model/--effort dispatch on agy < 1.1.10
# (config-conflict 65) instead of dispatching a voided pin.
GOOGLE_REVIEW_MODEL="${TRIAD_GOOGLE_REVIEW_MODEL:-}"
if [ "$GOOGLE_CLI" = agy ] && [ -z "$GOOGLE_REVIEW_MODEL" ]; then
  GOOGLE_REVIEW_MODEL="gemini-3.1-pro-high"   # agy-leg default = the catalog's stable
fi                                            # selector ('agy models' lists selectors, not
                                              # display labels; dispatch acceptance was
                                              # probe-verified at adoption). gemini path stays unpinned
# IDENTITY CAVEAT: catalog membership + dispatch acceptance prove the SELECTOR is
# valid, not which runtime tier actually served the call — agy exposes no runtime
# model identity, so record the leg as identity-unexposed. (The stream-json
# init.model event echoes the requested slug — still the REQUEST, not a serving
# proof.) The primary shallow/void detector is the read-audit gate below; rule
# 11's latency signal is secondary for this leg.
if [ "$GOOGLE_CLI" = agy ] && ! agy models 2>/dev/null | grep -qF -- "$GOOGLE_REVIEW_MODEL"; then
  # substring match (not -x/whole-line): tolerates a leading bullet/marker or a
  # trailing note in agy's listing — a whole-line exact match is brittle to any
  # such decoration and would false-negative a listed model.
  echo "[review] '$GOOGLE_REVIEW_MODEL' not in 'agy models' — falling back to agy default; Google leg is ADVISORY this round" >&2
  GOOGLE_REVIEW_MODEL=""
fi
```

`agy` → `triad-antigravity-dispatch`; `gemini` → `triad-gemini-dispatch`; empty
→ skip the Google leg and log "Google-family reviewer unavailable; review
proceeds with claude(Agent)+codex (2-family)".

A Google leg that fell back to the shallow default tier (the model-verify above)
is advisory for gating exactly like the agy leg — SKILL rule 1 states both. Log
the shallow-tier fact for the round record.

## agy leg

- **Findings-shape pin (2026-08-20, template-rendered).** The rendered
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
- **Tool-convention pin (2026-08-20, template-rendered — codex-side diagnosis
  cross-applied).** The READ-GRANT now states the POSITIVE reading convention:
  grep_search to SEARCH (never a shell command), file-view with the absolute
  path only — NO deprecated paging args (StartLine/EndLine/ContentOffset;
  current agy rejects them and the model emits them spontaneously — our A1/A2
  probes' "ContentOffset 40000" failures were THIS arg-skew, not an agy
  internal pagination bug as first recorded). Rationale: on agy 1.1.15+ any
  errored/denied tool step is turn-terminal (upstream #827), so the prompt
  must remove every occasion for one — the codex-host product verified this
  fix class working on agy 1.1.16. Pinned by `t4-prepare.sh`.
- **Model.** When `GOOGLE_REVIEW_MODEL` is non-empty, the dispatch passes
  `--model "$GOOGLE_REVIEW_MODEL"` to `antigravity_wrapper.py` (the Pro/High
  variant — agy's catalog encodes effort in the model slug, so the slug stays
  this leg's pinned mechanism; the wrapper also passes `--effort` through since
  agy 1.1.10 fixed it, but the catalog lists effort-suffixed selectors, so the
  leg does not add a separate `--effort`). The wrapper fail-closes a `--model`
  dispatch on agy < 1.1.10 (`config-conflict` 65 — the pin was silently VOID
  there, see the pin-floor note above): treat that exit as leg-not-run and
  surface "run `agy update`", never re-dispatch pinless to squeeze a verdict
  out of the shallow default.
- **Read-audit binding.** The SAME dispatch sets
  `TRIAD_READ_AUDIT_FILE="$PACKET_DIR/agy-read-audit.json"` in the wrapper
  invocation's environment — one packet dir per leg, so a parallel fan-out never
  collides. The wrapper writes the read-audit digest to exactly that path on
  every completed call, success or failure (`emit_read_audit`), and that durable
  file is the gate's only evidence source. Bind it AT DISPATCH TIME: the evidence
  cannot be created after the fact, so a leg dispatched without it is
  re-dispatched. **Round-invariant name vs the reused packet dir
  (adopt-gate r2 must-fix — every round from r3 on would otherwise be
  deterministically INVALID):** the digest file keeps ONE round-free
  literal at all three sites, so at round N>=2 the PRIOR round's file
  is still on disk when round N captures — a CENSUSED file the round-N
  dispatch then overwrites, which verify reports as "round evidence
  changed" on an unmutated tree. Therefore BEFORE round N's capture it is
  preserve-and-cleared to `agy-read-audit-r<N-1>.json` (suffixed with the
  round it BELONGED to). MECHANIZED since 2026-08-11:
  `review_scratch.py prepare` and `capture` both perform this rename
  automatically for an `r<N>` label (fail-loud on an unparseable label, a
  round-1 leftover, or a rename-target collision); the manual
  `mv "$PACKET_DIR/agy-read-audit.json" "$PACKET_DIR/agy-read-audit-r<N-1>.json"`
  remains only for hand-built rounds. The literal path is then
  ABSENT at capture; the file the round-N dispatch writes arrives
  post-capture and rides verify's `*-read-audit.json` leg-output
  allowlist, while the preserved copy is censused and frozen as
  history. Additionally, immediately before EACH dispatch,
  `rm -f "$PACKET_DIR/agy-read-audit.json"` — byte-match the SAME path this
  bullet's OWN dispatch binds unconditionally (first sentence above), never a
  bare `$AGY_READ_AUDIT_FILE` (a GATE-local name first assigned inside the
  read-audit gate block, unset at DISPATCH time — a bare
  `rm -f "$AGY_READ_AUDIT_FILE"` silently expands to `rm -f ""`, a no-op that
  clears nothing; re-confirm round 2 / claude must-fix G1) and never an
  `${TRIAD_READ_AUDIT_FILE:-...}` fallback either (re-confirm round 3 / H5
  hardening: since the dispatch ALWAYS binds the packet-relative path, not
  conditionally, a fallback form risks clearing an unrelated LEFTOVER
  `TRIAD_READ_AUDIT_FILE` some other ambient shell context left set, instead
  of the path THIS dispatch is actually about to write — the plain literal
  removes that ambiguity entirely). The wrapper's
  own `preclear_read_audit_file` closes a stale-file-survives path INSIDE the
  wrapper, but not a MISBOUND env (the dispatch names the wrong path, or the
  caller's shell never exported the var the wrapper reads); this leader-side
  `rm -f` — using the SAME plain literal all THREE sites share (this bullet's
  dispatch binding, this clear, and the gate's own binding below) — closes
  that remaining case so a misbound or otherwise unwritten dispatch still
  yields ABSENT, never a stale prior round's file read as this round's
  evidence. One shared literal, no env-var indirection anywhere, is what
  makes that guarantee hold regardless of what an ambient shell happens to
  have exported.
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
- **READ-GRANT block (mandatory, in the leg prompt; rewritten 2026-08-10
  by owner directive — same method as the codex leg).** Include verbatim:
  "Read `packet.md` FIRST and ONCE with your file-view tool (shell readers
  like `cat` are deny-listed under read-only) — it is the round's framing
  and your review's required entry point. You MAY then read files under
  the repo with your file-view tool to VERIFY the packet's claims — cite
  file:line for anything you assert from a repo file. Do NOT read files
  outside the repo, do NOT search the web, and do NOT consult prior
  conversations or scratch space. Do NOT modify any file, do NOT change
  external state, and do NOT run commands, tests, scripts, builds, or
  vendor CLIs. Anything you did not verify against the
  packet or a repo file is an open question, never an asserted finding."
  The mutation/exec sentence is part of the verbatim block on purpose
  (adopt-gate r2): this leg's write/exec containment is UNCONFIRMED
  intent at the dispatched version and the prompt is its only per-call
  carrier — dropping the sentence would ship the one
  unconfirmed-containment leg with no intent carrier at all.
  Packet-FIRST is load-bearing twice over: it is the mechanical read-audit
  gate's required entry (the gate below runs UNCHANGED — the packet path
  must appear in `files_read`), and reading it before any repo browsing
  keeps the gate decisive under the digest's 40-entry `files_read` cap.
  DISCLOSURE (adopt-gate r2): with repo browsing granted,
  `files_read_omitted > 0` becomes the NORM for a leg doing real
  verification work, and the gate's confirmed-VOID arm requires
  `omitted == 0` — so VOID stays decisive only when the leg complied
  with packet-FIRST, an INSTRUCTION-LEVEL property, the same class as
  the codex read boundary (§ codex leg). A non-compliant leg lands
  INCONCLUSIVE — never a silent pass, but no longer the mechanical
  leg-not-run proof the packet-ONLY diet gave; the round notes carry
  that judgment. Mutation
  is denied by INTENT via the per-call deny transaction — enforcement
  is UNCONFIRMED at the dispatched version (§ agy standing residuals) —
  so the round's capture/verify integrity gate is the ACTUAL
  mutation-detection control, not a redundant belt
  (`references/packet-lifecycle.md` § Round integrity); the read/network
  egress residual is UNCHANGED (§ agy standing residuals — owner-owned).
  Rationale: agy's detection record earned the wider view, and the old
  packet-ONLY diet made the leader's packet assembly this leg's ceiling —
  the same blindness the codex READ-GRANT fixed.
  Placement: immediately before the closing instruction, never leading the packet
  (`references/packet-lifecycle.md` § Packet order and fencing).
- **Prompt body.** The rendered `agy-prompt-r<N>.txt` (`prepare` output —
  READ-GRANT block with the round packet filename interpolated, severity
  instruction, verdict-selection rule, binding line): pass it with
  `--prompt-file <abs>`; a hand-built prompt owes the same blocks.
- **Verdict weight.** ADVISORY for the unanimous gate — SKILL rule 1.
- **Cites.** Verify any surviving agy finding's file:line against the packet
  before it enters the residual table. The gate proves the packet was read, not
  that a cite is accurate; cites were fabricated in 4 of 5 traced-or-scored runs
  even where the finding class was right (`references/evidence.md`).
- **Containment carrier.** The prompt is the only PER-CALL carrier: agy 1.1.8
  headless (`-p`) loads no workspace-scoped rules, so a packet-dir `GEMINI.md`
  is inert and reads as false comfort. It does load the global
  `~/.gemini/GEMINI.md`, so a mild owner-installed global rule (e.g. prefer the
  native file-view tool over shell readers) can reinforce the prompt — at the
  cost of affecting every agy session. Hard containment stays in the prompt.
  Provenance: the official rules doc is antigravity.google/docs/rules-workflows
  (6-probe spike); the CLI's own bundled `agy-customizations` skill
  mis-describes both the rule-file names and their paths, so do not author a
  rule file from it.
- **Folded verdict.** If a read-only verdict folds (`truncated-answer`, exit 65),
  re-dispatch ONCE asking for a COMPACT chat-returnable verdict (verdict + top
  findings with evidence, under the ~4KB fold), still `--sandbox read-only`. A
  second fold logs the leg terminally missing → degraded mode (SKILL rule 1).
  Widening the sandbox to let the leg write a long verdict forfeits rule 7's
  mechanical containment on the leg that ingests untrusted input, so it is out.

## agy read-audit gate

Apply this BEFORE weighing the verdict, and before any agy finding enters the
residual table.

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
run-log's `read_audit` key is unchanged and still exists, but the gate no longer
reads it; the run-log stays the repair-agent's input artifact.)

Then apply:

1. every packet file's absolute path must appear as the `AbsolutePath` param
   of a `read_audit.digest.files_read[*]` entry (`read_audit` here names the
   loaded `{meta, digest}` object). The match is KEY-RESTRICTED (review r2,
   codex must-fix — live-corroborated by a real `grep_search {Query,
   SearchPath}` entry in that round's own digest): `files_read` holds every
   successful READ-CLASS call, so a `grep_search` whose `Query` VALUE equals
   the packet path is tool traffic that merely REFERENCED the path — only
   the file-view tool's `AbsolutePath` param evidences a read of the packet
   itself. The key name is a VENDOR coupling (disclosed): empirically pinned
   from real digests + the t41/f9/t5 fixtures; an agy param rename fails
   toward VOID/INCONCLUSIVE (loud, conservative), never a silent PASS.
   `files_read` records only tool calls that SUCCEEDED (terminal DONE with
   no `tool_info.error`), so a hit is real proof the leg's view_file call on
   the packet succeeded (one disclosed limit: a RANGE-limited view — if the
   dispatched build ever emits range params — would satisfy this on a
   partial read; no range params have been observed in real digests,
   recorded as residual r3-1);
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
   (review r2, 2-family convergence) instead of over-claiming a match, and
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
   pre-dedupe TOTAL) and `read_audit.digest.read_attempts[]`. The run-log's
   `stdout` holds the raw NDJSON of the FINAL attempt only — an earlier
   attempt's raw stream is retained nowhere, so never plan to read it. If the
   census does not settle it, re-dispatch with a narrower packet rather than
   guessing. Only a failed match WITH `files_read_omitted == 0` is a confirmed
   VOID: treat it as leg-not-run, re-dispatch ONCE with the containment block
   above, and keep a VOID leg out of the gate count. A leg still VOID after that
   one re-dispatch is terminally missing this round (rule 13) — apply the same
   degraded 2-family (claude+codex) + owner-decision mode as any other
   terminal-failure leg (rule 1), with no second re-dispatch;
2. surface `read_audit.digest.denied` / `read_audit.digest.writes` /
   `read_audit.digest.read_attempts` entries in the round notes — e.g. a write
   rerouted to agy's scratch dir shows up as a `writes` entry whose `TargetFile`
   sits outside the packet dir (worth noting; on its own it does not void the
   leg), and a **read-class** `read_attempts` entry naming a packet file is the
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
the skill's own helper — ONE call per round covers a multi-file packet (every
file must pass):

     ```bash
     bash <skill>/lib/read_audit_gate.sh "$PACKET_DIR" "$PACKET_DIR/packet-r<N>.md" [<more-abs-packet-files>...]
     ```

The helper is the gate's single EXECUTABLE form (skill v0.27.0 — the leader
used to re-type the block inline once per round): the canonical jq invocation
LIVES in `lib/read_audit_gate.sh`, where the t41/f9 self-tests lift it
verbatim and `t5-read-audit-gate.sh` owns the CLI contract. This section
stays the SPEC the helper implements. What each outcome means:

- **Digest path is DERIVED**, never accepted: the shared literal
  `$PACKET_DIR/agy-read-audit.json` — the same ONE literal the § agy leg
  dispatch binding and the leader-side pre-clear use (re-confirm round 5 /
  J1 anti-drift: no env-var fallback anywhere, so an ambient
  `TRIAD_READ_AUDIT_FILE` some OTHER shell context left exported can never
  make the gate open a file nobody bound or cleared for THIS round). The
  wrapper writes it on EVERY completed call, ok or not — no stderr capture,
  no grep/sed extraction (`triad-antigravity-dispatch` § Isolation).
- **Packet-file args are the ROUND-SUFFIXED names** (for a `prepare`-built
  round, `<packet-dir>/packet-r<N>.md` — never the packet DIR itself). Argv
  discipline is LOUD (exit 64), never a verdict: the packet dir and EVERY
  packet file must be absolute paths, the dir must exist, and every packet
  file must exist — a stale generic `packet.md` would otherwise false-VOID
  a compliant leg.
- **Exit 0 PASS** — every packet file's absolute path matched the
  `AbsolutePath` of a successful `view_file` entry in `files_read` (the
  rule-1 tool+key restriction; arguments that survive to this comparison
  are within the cap, so the stored value is the FULL path and equality is
  exact — no truncation is applied to a surviving argument). Proceed to
  weigh the verdict.
- **Exit 2 ABSENT** — no digest file. NOT proof the vendor call failed:
  `TRIAD_READ_AUDIT_FILE` unset/misbound at dispatch time is empty in
  exactly the same way as a call that never completed. Check the dispatch
  env FIRST; only once it is sound, treat as VOID (leg-not-run) and
  re-dispatch once.
- **Exit 3 VOID** — a confirmed miss (`files_read_omitted == 0`):
  re-dispatch ONCE with the containment block; still VOID after that
  re-dispatch is terminally missing this round (rule 13 → rule 1 degraded
  2-family + owner-decision mode, no second re-dispatch).
- **Exit 4 INCONCLUSIVE** — never read as VOID and never as PASS. Four
  causes, each named on stderr: a CAPPED digest (`files_read_omitted > 0` —
  weigh `digest.attempts[]` per-attempt totals + `digest.read_attempts[]`,
  and re-dispatch with a narrower packet if the census does not settle it;
  there is no fuller digest, and only the FINAL attempt's raw stream is
  retained anywhere), BROKEN evidence (jq could not produce a usable
  answer — read, parse, program, or runtime error: inspect the file
  directly, then re-dispatch once), a SYMLINKED digest file (refused,
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
  confirmable).
- **Multi-file aggregation is pinned and LOAD-BEARING**: any INCONCLUSIVE
  file → exit 4; else any VOID file → exit 3; else exit 0. The per-ARGUMENT
  over-cap refusal CAN mix with a digest-side VOID in a single run (only
  the capped/broken digest states are digest-global), so the precedence is
  what keeps a mixed round deterministic — never remove it as dead logic.
  BROKEN evidence stops the loop — later files are never evaluated. The
  summary counters count EVALUATED files only, and whenever any argument
  was NOT evaluated (the broken-evidence stop; the ABSENT/symlink refusals
  evaluate none) the summary line appends ` unevaluated=<n>` so the token
  and the counters cannot disagree silently.
- **The verdict inputs are the jq gate's rc + `files_read_omitted` ONLY.**
  The stderr `ATTEMPTED but failed to read the packet` line — a read-class
  `read_attempts` entry naming a packet file, i.e. the leg TRIED and was
  blocked — is diagnostic text for the round notes, never a verdict input
  (`read_attempts` also carries failed writes/run_commands/web fetches; one
  of those merely NAMING the packet is not a failed read, which is why the
  helper scopes the note with the SAME tool+key restriction as the verdict
  jq — `.class == "read" and .tool == "view_file"`, AbsolutePath-only value
  scan (review r4); the trade — a rename-induced VOID loses the "it tried"
  note too — is recorded as residual r5-1).
- **The 200-char cap is COUPLED to `bin/_common.py`'s `_AGY_DIGEST_VALUE_CAP`**
  (t5 drift-guards the pair and the helper's one-literal property). Within
  the cap the stored value is the FULL path, so equality is exact; over-cap
  arguments are refused INCONCLUSIVE (rule 1 above) — which also retires
  the earlier locale-unit caveat by refusal (a length that units could
  disagree about is over-cap in at least one unit and lands in the refusal,
  conservative in both directions).
- **The stdout contract** for round notes: one `[gate] <VERDICT> <file>`
  line per EVALUATED packet file (the ABSENT/symlink refusals evaluate
  none; the broken-evidence stop evaluates no later file), then the final
  greppable summary
  `READ_AUDIT_GATE_<PASS|VOID|INCONCLUSIVE|ABSENT> checked=<n> pass=<n>
  void=<n> inconclusive=<n>[ unevaluated=<n>]` — the `unevaluated` field
  appears exactly when some argument was not evaluated (ABSENT/symlink
  refusals, the broken-evidence stop), so anchor on the token, not on a
  four-field-only pattern.

One shape to know: a digest file that is valid JSON but carries no `.digest`
key yields jq rc 1, not rc>=2, so it lands in the coverage-miss branch and —
with `omitted` 0 — reads as a confirmed VOID (exit 3). That is intended: a
digest-less file is a leg that produced no read evidence.

## agy standing residuals

Two live claims govern whether a deployment can run this leg at all:

- **Write/exec containment is UNCONFIRMED at the version the wrapper
  dispatches**, and `execute_url` / `mcp` / `unsandboxed` are INTENT.
- **Reads and network are open BY DESIGN on every build** — `read_file` and
  `read_url` are never denied, so an adversarial packet can make the leg read
  OUTSIDE `--cwd` and ship data out over the network (probe-CONFIRMED under
  `--sandbox read-only --cwd <packet dir>`). A deployment that cannot accept
  that runs the leg inside an EXTERNAL fs-scoped, network-denied OS sandbox;
  `AGY_NO_HEADLESS_AUTOAPPROVE=1` does not close it.

The version chronology, the probe record and the deny-set inspection behind both
claims are owned by the `triad-antigravity-dispatch` skill — its § Headless
soft-deny adaptation and the isolation reference it points to.

## gemini leg

When gemini is the resolved Google leg, pass an owner-verified
`TRIAD_GOOGLE_REVIEW_MODEL` to `gemini_wrapper.py --model` where one is
configured; otherwise run the CLI default and log that the review tier is
unpinned. An unpinned-default gemini leg is advisory for gating, like the agy
fallback above.

## codex leg

- **Tier.** `--reasoning xhigh` is the default review tier (deep, one below the
  family top). Escalate to `--reasoning max` — the deepest non-delegating tier —
  only on a round the leader designates very-important AND algorithmically
  complex; at max a LARGE packet has exhausted 900s with no verdict, so max also
  demands the rule-7 large-packet timeout. `ultra` stays out: it self-delegates
  subagents (runaway/over-long) and not every model variant supports it. If the
  CLI rejects the chosen tier, fall back one step (`max` → `xhigh` → `high`) and
  log.
- **`--search` disclosure.** This skill always passes `--search` for the codex
  leg (the wrapper's own default is off), so the packet/diff content this leg
  reasons over can surface as live web-search query context sent to the vendor's
  search backend — the same class of egress residual as the agy read/network leak
  above, on a different leg. For a SENSITIVE packet, drop `--search` to keep the
  leg fully offline.
- **INLINE the packet into `--prompt` AND grant read-only repo access
  (contract revised 2026-08-10, adopted from codex-host 0.2.533).** The
  packet stays inlined — the leg's guaranteed view and its framing.
  ADDITIONALLY pass `--cwd <abs repo root>` and include the READ-GRANT
  trailer below. The historical "cannot open a handed-over file"
  failure was the rule-7 blanket no-exec directive banning the
  read-only shell commands codex uses to open files — `--sandbox
  read-only` never blocked reads, only writes. With reads granted the
  leg verifies packet claims against the repo the way the claude leg
  does (the FU10 plan gate measured the cost of NOT granting this: the
  codex leg's r3 SAFE(0) missed a defect that required reading one
  function outside the packet, and its r2 refuted trigger came from
  reasoning without code access). Containment posture: file WRITES stay
  mechanically blocked by `--sandbox read-only`; execution/network
  limits ride the trailer; the round's capture/verify integrity gate
  (`references/packet-lifecycle.md` § Round integrity) is the belt —
  mutation detection, not a sandbox claim alone, decides admission.
  The READ boundary itself is INSTRUCTION-LEVEL (adopt-gate r1,
  codex+claude converged must-fix): neither `--cwd` nor the read-only
  sandbox mechanically confines what the leg can READ, and `--search`
  is an outbound channel — so the trailer's outside-repo prohibition
  below is a directive the integrity gate cannot verify, the same
  residual class § agy standing residuals discloses for the agy leg.
  For a sensitive packet drop `--search` (disclosure bullet above).
  READ-GRANT trailer (verbatim; it REPLACES the old blanket no-exec
  line for THIS leg only): "You MAY read files under the working
  directory with read-only commands (cat, sed -n, rg, ls, git diff,
  git show, git log) to verify claims beyond the packet — cite
  file:line for anything you assert from them. Do NOT read files
  outside the working directory — no home-directory or dotfiles, no
  credentials, no system paths: nothing outside the repository is
  review material. Do NOT modify any file,
  do NOT change external state, do NOT run tests, scripts, builds, or
  the code under review, and do NOT invoke vendor CLIs; network only
  through your search tool." Fast-SAFE heuristic RESCOPED with this
  contract: a fast terse SAFE is a re-dispatch signal when the leg HAD
  code access and substantive questions; a narrow text-only re-confirm
  may legitimately return fast — criteria-enumeration quality stays the
  primary rubber-stamp check (rule 11). Mechanically: the `prepare`
  subcommand renders this leg's entire body —
  `codex-body-r<N>.txt`, the packet inlined between PACKET fences plus
  the READ-GRANT trailer, severity instruction, verdict-selection rule,
  and binding line (`references/packet-lifecycle.md` § Deterministic
  round preparation) — so the dispatch passes the FILE:

  ```bash
  # body rendered by `review_scratch.py prepare` (canonical order inside);
  # --timeout 900 fits a focused packet, LARGE packet → 1500 (rule 7):
  codex_wrapper.py --sandbox read-only \
    --cwd /abs/repo/root \
    --reasoning xhigh --search --timeout 900 \
    --pydantic verdict_schema:LegVerdict \
    --prompt-file "$PACKET_DIR/codex-body-r<N>.txt"
  # --cwd = the repo the READ-GRANT trailer opens for verification reads
  # (contract revision 2026-08-10 above); writes stay sandbox-blocked.
  # (--reasoning max only on a designated escalation round)
  # (--search = live web-grounding, disclosed above — drop it for a sensitive packet)
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
  retry is `schema-fail` (exit 66). EXCEPTION first (adopt-gate r3,
  generalized r7; § Verdict binding obligation 4): a 66 whose wrapper
  stderr carries the `[NONREPAIRABLE]` token — the marked SAFE-arm OR a
  BLOCKING-CONTENT refusal (the dominant post-r5 trigger: the reply's
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
  there is no heredoc to terminate early.) Inlining is a codex-leg requirement rather than a
  universal one, since gemini and agy read the repo-relative packet file — though
  inlining a small packet works for every leg. For a LARGE diff the inlined body
  must ALSO be the focused, high-risk subset: same focused content agy/gemini get
  as a file, same canonical order, different transport.

## claude fresh-eye leg

- **Identity.** `subagent_type: triad-dispatch:cross-family-review-reviewer` — the dedicated
  read-only reviewer agent (`agents/cross-family-review-reviewer.md`,
  frontmatter `tools: Read, Grep, Glob`), so rule 7's no-execute contract rides
  the agent's tool allowlist rather than the prompt directive alone. The `Agent`
  tool exposes no per-call `tools` allowlist, so a plain
  `subagent_type: general-purpose` Agent would fall back to that advisory
  directive; the frontmatter pin IS the mechanism. (The shipped claude-host
  plugin rewrites this to the plugin-scoped
  `subagent_type: triad-dispatch:cross-family-review-reviewer`, so a consumer's
  same-named project agent cannot shadow the read-only plugin reviewer.)
- **Tier.** That agent's frontmatter pins `model: opus` + `effort: xhigh`. Leave
  the model out of session inheritance: an unpinned agent inherits the leader's
  SESSION model and can silently run a heavier tier such as fable, which is out
  of the review rotation. Escalation for a very-important AND algorithmically
  complex round = `subagent_type: triad-dispatch:cross-family-review-reviewer-max` (identical
  body, `effort: max`). Effort is frontmatter-fixed with no per-invocation
  override, so the sibling definition IS the escalation mechanism.
- **Prompt.** Add the explicit max-thinking directive at every tier ("Think as
  hard as you can / ultrathink before answering") — the depth levers are
  frontmatter effort and the PROMPT (rule 10). Without the directive the claude
  leg under-reasons and rubber-stamps. Frame it adversarially and forbid
  severity-deflation per rule 10.
- **Output contract (structured verdict, no wrapper).** This leg has no
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
  content_digest) to echo verbatim. The leader
  validates the reply with the BOUND admission — `lib/validate_verdict.py
  <reply-as-a-file> --expected-review-id <id> --expected-family claude
  --expected-packet <abs-packet-path>` (§ Verdict binding obligation 2;
  a flagless call is shape-only and is NOT an admission) — before
  consolidating it. A reply that fails validation or binding is
  the EXISTING INVALID-leg handling — one re-ask with the same directive
  restated, then INVALID if it fails again (`references/triage.md` § Verdict
  release at the merge gate); this does not invent a new chain.
- **Rendered prompt + reply transcription.** `prepare` renders this leg's
  full prompt as `claude-prompt-r<N>.txt` — adversarial preamble, packet
  path, severity instruction, verdict-selection rule, binding line, and
  the inline LegVerdict contract above — so the leader dispatches the
  `Agent` with that content (it is small: paste it, or have the agent
  Read the file first; either way the file is the censused input).
  TRANSCRIPTION CAVEAT: the Agent completion notification HTML-escapes
  the reply (`>` → `&gt;`, `&` → `&amp;`, quotes likewise); DE-ESCAPE
  EXACTLY ONCE (`html.unescape`) before writing `claude-r<N>.json` for
  admission, then validate — over/under-de-escape fails schema or
  binding admission, which is the check. DISCLOSED residual: a reply
  whose string fields INTENTIONALLY spell HTML entities is
  indistinguishable from transport escaping after one unescape — when a
  finding's exact bytes matter, resolve against the agent transcript.
  (The reviewer agent is Read/Grep/Glob-only, so a
  write-your-reply-to-a-file contract is NOT available — leader-side
  transcription is the only path, hence the caveat.)
- **Agent definitions are session-start snapshots** — a frontmatter change takes
  effect from the NEXT session.
