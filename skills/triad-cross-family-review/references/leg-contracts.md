# Cross-family review — per-leg dispatch contracts

Loaded on demand from `triad-cross-family-review/SKILL.md`. Read this when
dispatching a round's legs (Flow step 2), and again when an agy leg returns —
its verdict may be weighed only after the read-audit gate below passes.

## Contents

| Section | Open it when |
|---|---|
| Google-family leg selection | choosing between `agy` and `gemini` for this round |
| agy leg | dispatching agy — model selector, read-audit binding, containment block |
| agy read-audit gate | an agy leg returned and you are about to weigh it |
| agy standing residuals | deciding whether this deployment can run the agy leg at all |
| gemini leg | gemini is the resolved Google leg |
| codex leg | dispatching codex — tier, `--search`, inline packet |
| claude fresh-eye leg | dispatching the claude `Agent` leg |

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
# adversarial review — it finds nothing the deeper tier catches. agy encodes
# reasoning in the MODEL VARIANT (there is no --reasoning flag; the separate
# thinkingLevel param is stripped/buggy — antigravity issue #1675), so force the
# Pro/High variant via --model. Env-overridable; verify it still exists (Google
# renames tiers) and fall back to the default + log if absent.
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

- **Model.** When `GOOGLE_REVIEW_MODEL` is non-empty, the dispatch passes
  `--model "$GOOGLE_REVIEW_MODEL"` to `antigravity_wrapper.py` (the Pro/High
  variant — agy encodes effort in the model slug; an `--effort` flag exists but
  the wrapper does not pass it, so the slug stays the supported mechanism).
- **Read-audit binding.** The SAME dispatch sets
  `TRIAD_READ_AUDIT_FILE="$PACKET_DIR/agy-read-audit.json"` in the wrapper
  invocation's environment — one packet dir per leg, so a parallel fan-out never
  collides. The wrapper writes the read-audit digest to exactly that path on
  every completed call, success or failure (`emit_read_audit`), and that durable
  file is the gate's only evidence source. Bind it AT DISPATCH TIME: the evidence
  cannot be created after the fact, so a leg dispatched without it is
  re-dispatched.
- **Containment block (mandatory, in the leg prompt).** Include verbatim:
  "Read `packet.md` ONCE with your file-view tool (shell readers like `cat` are
  deny-listed under read-only) and base the review on it ALONE. Do NOT read or
  search any other file or directory, do NOT list directories, do NOT search the
  filesystem or the web, and do NOT consult prior conversations or scratch
  space. Anything not in the packet is an open question, never an asserted
  finding." A traced containment run dropped exploration tool calls to zero.
  Placement: immediately before the closing instruction, never leading the packet
  (`references/packet-lifecycle.md` § Packet order and fencing).
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

1. every packet file's absolute path must appear among
   `read_audit.digest.files_read[*].params` values (`read_audit` here names the
   loaded `{meta, digest}` object — see the code below). `files_read` records
   only tool calls that SUCCEEDED (terminal DONE with no `tool_info.error`), so
   a hit is real proof the leg received the bytes; an ERRORED or
   permission-DENIED read attempt appears instead under
   `read_audit.digest.read_attempts[*]` with an `outcome` of `error`/`denied`
   and does not satisfy this gate. The digest is CAPPED (every `params` value
   truncated at 200 chars; `files_read` itself capped at the first 40 entries,
   with `files_read_omitted` counting the rest), so match the packet path
   truncated the same way — equality once truncated is sufficient, since both
   sides carry the same 200-char cap, so a prefix/`startswith` comparison adds
   only false positives and never coverage. If that capped match fails AND
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
MECHANICAL means extract-and-gate deterministically, with no AI judgment. For a
multi-file packet, loop this whole check once per packet file; every file must
pass:

     ```bash
     # for a multi-file packet, loop this block once per file — every file must pass.
     # PACKET_ABS_PATH = the absolute path of the ONE packet FILE this loop
     # iteration checks (NOT the packet DIR `review_scratch.py open` printed
     # — that is a directory; for a single-file packet this is
     # <packet-dir>/packet.md).
     # ONE artifact: AGY_READ_AUDIT_FILE = the path the dispatch actually bound
     # to TRIAD_READ_AUDIT_FILE. Read that variable when it is still in scope and
     # fall back to the dispatch convention, so the gate can never check a
     # different file than the wrapper wrote (`triad-antigravity-dispatch`
     # § Isolation; the wrapper writes on EVERY completed call, ok or not — no
     # stderr capture, no grep/sed extraction, no separate validity pre-check).
     AGY_READ_AUDIT_FILE="${TRIAD_READ_AUDIT_FILE:-$PACKET_DIR/agy-read-audit.json}"
     if [ ! -f "$AGY_READ_AUDIT_FILE" ]; then
       # ABSENT is NOT proof the vendor call failed — TRIAD_READ_AUDIT_FILE
       # unset/misbound at dispatch time is empty in exactly the same way as a
       # call that never completed. Check the dispatch env FIRST; only once
       # that is sound does an absent file mean the leg did not run.
       echo "[review] agy leg read-audit ABSENT — no digest file at \$AGY_READ_AUDIT_FILE. Cause is EITHER a vendor call that never completed OR TRIAD_READ_AUDIT_FILE was never set at dispatch time. Verify the dispatch env; only once it is sound does this mean the leg did not run — then treat as VOID (leg-not-run) and re-dispatch once." >&2
     else
       # 200 = bin/_common.py's _AGY_DIGEST_VALUE_CAP (the digest's own params-value
       # truncation) — coupled to that constant; a wrapper-side cap change must
       # update this literal too, or a real match can silently false-VOID.
       p_trunc="${PACKET_ABS_PATH:0:200}"
       jq -e --arg p "$p_trunc" \
         '[.digest.files_read[]?.params // {} | to_entries[]?.value | select(type == "string")] | any(. == $p)' \
         "$AGY_READ_AUDIT_FILE" >/dev/null 2>/dev/null
       jq_rc=$?
       if [ "$jq_rc" -ge 2 ]; then
         # jq could not produce a usable answer — a BROKEN reading of the
         # evidence, not evidence. Never silently VOID (or PASS) on it. rc>=2
         # covers every jq failure mode, not just malformed JSON: a read error,
         # a parse error, a program error, or a runtime error all land here.
         echo "[review] agy leg read-audit INCONCLUSIVE — jq could not produce a usable answer from \$AGY_READ_AUDIT_FILE (rc=$jq_rc: read, parse, program, or runtime error). Do NOT read this as VOID and do NOT read it as PASS: inspect the file directly, then re-dispatch once." >&2
       elif [ "$jq_rc" -eq 1 ]; then
         omitted="$(jq -r '.digest.files_read_omitted // 0' "$AGY_READ_AUDIT_FILE")"
         # Diagnostic: a BLOCKED read is recorded in read_attempts, not
         # files_read — print it so a VOID verdict says whether the leg tried.
         # Filter on `.class == "read"` — read_attempts also carries failed
         # WRITES / run_commands / web fetches, and one of those merely NAMING
         # the packet is not "the leg failed to read the packet". This filter
         # is DIAGNOSTIC-ONLY: the VOID/PASS decision is jq_rc + `omitted`
         # above, never this line, so a miss costs explanatory text and never
         # a verdict.
         jq -r --arg p "$p_trunc" \
           '[.digest.read_attempts[]? | select(.class == "read")
            | select([.params // {} | to_entries[]?.value
              | select(type == "string")] | any(. == $p))
            | "\(.tool):\(.outcome)"] | select(length > 0)
            | "[review] agy leg ATTEMPTED but failed to read the packet: \(join(", "))"' \
           "$AGY_READ_AUDIT_FILE" >&2
         if [ "${omitted:-0}" -gt 0 ]; then
           echo "[review] agy leg read-audit INCONCLUSIVE ($omitted files_read entries capped) — weigh read_audit.digest.attempts[] (per-attempt totals) + read_audit.digest.read_attempts[] before voiding; there is no fuller digest and only the FINAL attempt's raw stream is retained, so re-dispatch with a narrower packet if the census does not settle it" >&2
         else
           echo "[review] agy leg VOID — packet path not in read_audit.digest.files_read; re-dispatch once with the containment block; still VOID after that re-dispatch is terminally missing this round (2-family + owner decision, rule 1 degraded mode — no second re-dispatch)" >&2
         fi
       fi
       # jq_rc == 0 -> PASS (fall through; no message needed).
     fi
     ```

One shape to know: a file that is valid JSON but carries no `.digest` key yields
rc 1, not rc>=2, so it lands in the coverage-miss branch and — with `omitted` 0 —
reads as a confirmed VOID. That is intended: a digest-less file is a leg that
produced no read evidence.

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
- **INLINE the packet into `--prompt`; never hand codex only a file path.**
  A codex leg under `--sandbox read-only` plus the rule-7 no-exec directive may
  be unable to open a handed-over file at all — it has no shell to `cat` and its
  file-read route can come back empty ("non-CLI file access routes did not expose
  the files"), returning no verdict. Embed the full diff + suspect questions
  directly in the prompt string. Mechanically: assemble the entire prompt BODY
  into a file, then pass it with command substitution AT THE CALL SITE:

  ```bash
  # build the full review body in a file (packet-lifecycle.md canonical order);
  # --timeout 900 fits a focused packet, LARGE packet → 1500 (rule 7):
  review_body=/path/to/review-body.txt
  codex_wrapper.py --sandbox read-only \
    --reasoning xhigh --search --timeout 900 \
    --prompt "$(cat -- "$review_body")"     # <-- substitution fires here
  # (--reasoning max only on a designated escalation round)
  # (--search = live web-grounding, disclosed above — drop it for a sensitive packet)
  ```

  Keep `$(cat body.txt)` OUT of a single-quoted heredoc BODY — i.e.
  `--prompt "$(cat <<'PROMPT'` … a line containing `$(cat body.txt)` …
  `PROMPT)"`. The heredoc is literal, so that inner `$(...)` is never expanded
  and codex receives the uninterpreted string `$(cat ...)`. (The outer heredoc
  shape stays valid for a literal prompt body — the sibling dispatch skills'
  Step 1 uses exactly that.) Inlining is a codex-leg requirement rather than a
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
- **Agent definitions are session-start snapshots** — a frontmatter change takes
  effect from the NEXT session.
