---
name: triad-cross-family-review
description: Runs the FINAL pre-merge (or review-worthy / security-or-correctness-critical) cross-family review mandated by the lab's cross-family review rule — prepares ONE frozen round from a named ROSTER of INDEPENDENT cross-family reviewers (a claude fresh-eye sub-agent via Agent + codex via triad-codex-dispatch + the Google-family CLI selected at runtime — agy via triad-antigravity-dispatch, with compatibility for the older gemini CLI via triad-gemini-dispatch — plus any entry the project configured), frames the suspect/omitted/simplified decisions as QUESTIONS, admits every entry's verdict (SAFE TO MERGE / MERGE WITH FIXES / DO NOT MERGE) against the canonical schema, and folds them into ONE outcome (AGREED / BLOCKED / INCOMPLETE) driving a fix→NEW-round loop. Trigger when about to merge review-worthy work, ESPECIALLY when the leader chose to OMIT or SIMPLIFY something from a vetted source, or after a subagent-driven implementation before integration.
version: 0.50.2
# changelog: docs/reviews/2026-09-18-cfr-skill-history.md (every entry; the newest section is last)
---

# triad-cross-family-review

The leader's standard **final pre-merge review**: the independent reviewers
of a named roster — by default one per model family — judge a diff/branch,
the suspect decisions are posed as questions, and findings drive a
fix→re-review loop. Codifies the lab's standing cross-family review rule.

## When to use

- About to merge review-worthy or security/correctness-critical work.
- The leader OMITTED or SIMPLIFIED something from a vetted external source
  (the canonical author-blind-spot case).
- After a `superpowers:subagent-driven-development` run, before integrating —
  per-task spec+quality reviews are same-family and miss cross-cutting issues.

## Skip when

- A single-shot codex / gemini / agy / claude call → the per-CLI dispatch SKILLs (the `Agent` tool for claude).
- Trivial / mechanical change with no correctness or security surface.

## Contents

The body below is the whole operating contract: the hard rules and the flow.
Five references carry the detail — open one only when its column applies.

| Reference | Open it when |
|---|---|
| `references/leg-contracts.md` | dispatching entries, or weighing an agy verdict — the roster's per-vendor shapes, the Google-route chain, the producer schema projection, per-leg prompts, the agy READ-GRANT block, **the MECHANICAL read-audit gate (executable form = `lib/read_audit_gate.sh`), the hook load check and the attempt seal**, the agy read/network residual |
| `references/packet-lifecycle.md` | opening/closing a packet dir, the per-attempt results tree, shrinking a large diff, ordering and fencing a round, or freezing it |
| `references/triage.md` | consolidating a round — dispositions, REAL / REACHABLE-UNOBSERVED / SPECULATIVE, the scope-expansion gate, the residual table and the next round's current residual |
| `references/failure-modes.md` | a round misbehaved and you want the rule that already covers it — symptom → cause → rule index |
| `references/evidence.md` | a threshold or policy looks arbitrary — latency measurements, the agy depth study, measured timeouts, origin incidents |

## Hard rules

1. **EVERY selected (enabled) roster entry reviews the round, and the round
   is agreed only when EVERY one explicitly returns `SAFE TO MERGE` (R-AGREE /
   R-ROSTER).** The shipped roster is
   (a) a **claude fresh-eye sub-agent** via the `Agent` tool, spawned with the
   printed `subagent_type: triad-dispatch:cross-family-review-reviewer` (or its `-web` twin) — from the entry's `claude.agent`, one of the presets the skill ships (rule 15),
   LAYOUT-QUALIFIED by the renderer (dist → `<plugin>:<agent>` from the plugin
   manifest, dev → bare; roster DATA stays bare) so no project agent shadows
   it — the read-only reviewer whose `tools: Read, Grep, Glob` (plus `WebSearch`, `WebFetch` on its `-web` twin, which every web round spawns — rule 7) make rule 7's no-execute contract mechanical. Never the leader reasoning
   in-line: the leader holds the originating framing and shares its blind
   spot. (b) **codex** via `codex_wrapper.py` (`triad-codex-dispatch` owns the
   flag contract). (c) the **Google-family CLI**, resolved at runtime — agy
   (compatibility with the older gemini CLI exists; both share the Gemini
   backend, so exactly one serves a Google entry). Same-family-only reviewers
   inherit the leader's framing; cross-family plus fresh-eye breaks it.
   - **`acceptance` is operator DATA, not a gate rule.** No entry is "advisory":
     a leg's label (`required` / `participating` / `informational`) is recorded
     and nothing derives behaviour from it. Any verdict other than
     `SAFE TO MERGE`, a blocking finding or an unresolved open question from ANY
     selected entry leaves the round non-agreed — including a Minor-only
     `MERGE WITH FIXES` / `DO NOT MERGE`, whose verdict is kept and recorded as
     a verdict-selection DEVIATION (`references/triage.md`).
   - **An ENABLED entry that did not RUN is a MISSING RESULT → `INCOMPLETE`
     (exit 5), whatever its family coverage** (R-AGREE) — one the roster
     SKIPPED (R-GOOGLE) is counted and NAMED with its skip reason, never
     hidden behind its family's entries that ran.
   - **Leg count and family coverage are descriptive, never a threshold** —
     a one-leg or one-family roster agrees by the same rule; two entries of
     one family are one family in the coverage report. An owner EXCEPTION is
     a separate ledger record that may authorize a human action; it never
     makes a non-agreed round agreed.
   - **Roster (the legs of a round are DATA).** The shipped default is
     `spec/review-legs.default.json` (three enabled entries, one per family);
     `<source-repo>/.claude/triad-review-legs.json` — the SOURCE repo `prepare` names as its second argument (the live checkout, never the round tree) — (schema
     `triad-review-legs.v2`) is the PROJECT override, merged BY NAME — objects
     field by field, scalars and arrays replaced. Every entry is validated
     enabled or not; a v1
     file (`triad-review-legs.v1`) is REFUSED by the roster schema. No
     user-scope roster file is read. Recommended extra
     entry: the claude `high` arm `cross-family-review-reviewer-high`; Flash
     is RETIRED as a reviewer (Pro + Flash = ONE family). ONE codex entry;
     the shipped default names its model explicitly
     (`spec/review-legs.default.json`, at `high`, roster data — rule 15). Four-leg profile (that
     codex entry + three named agy-route Google entries, `timeout_s` 3600):
     `references/review-legs.four-leg.example.json`. A comparison entry of
     any family is an ordinary opt-in entry whose findings count like any
     leg's; the difference between two entries is a ledger observation, never
     a vote. Fields, per-vendor blocks, the Google chain, evidence:
     `references/leg-contracts.md`.
   - **Depth = the tiers in the roster data (rule 15)**; a deeper tier for a
     round the leader designates very-important AND algorithmically complex
     is a roster change, so a new basis (rule 5).
   - **The agy leg's read/network egress is open by design** — a deployment
     that cannot accept it runs the leg inside an external fs-scoped,
     network-denied OS sandbox.
   Everything per-leg (Google-route chain, rendered argv and prompts,
   MECHANICAL read-audit gate, egress evidence) is in
   `references/leg-contracts.md`. An agy entry's verdict is weighed only after
   CUSTODY (its `stderr.log` carries the whole line `read-audit-file: <path>`),
   the read-audit gate (`lib/read_audit_gate.sh`) AND the per-attempt hook
   LOAD CHECK (`lib/agy_hook.py check`) pass — `prepare` / `retry` print both
   lines; each check's verdicts and remedies are in `references/leg-contracts.md`
   § agy read-audit gate and § agy hook load check.
2. **Frame suspect decisions as QUESTIONS, not settled facts.** "Is X actually
   safe to omit?" — never "X is a no-op." Biased framing propagates.
3. **Every entry gets the SAME scope, through the SAME transport.** Give the
   branch ref / SHA range plus the list of suspect decisions. Every entry is
   dispatched `--cwd <round worktree>` (wrapper entries; a native claude entry gets the same path inside its rendered prompt) and opens `brief.md`,
   `diff.prod.patch`, `diff.tests.patch` and `history.txt` with its OWN read
   tools (rule 8) — never by executing `git diff` or any other subprocess
   (rule 7), which keeps leader context lean; the codex entry reads the same
   files through its read-only shell (rule 9). A diff near a context ceiling
   is shrunk with `--diff-path`, `--tests-path` and `--excerpt` (rule 8).
4. **Consolidate, don't average — the LEADER verifies each finding, then acts
   (R-VERIFY).** Agreement is the collector's alone (rule 1): no leader
   refutation, triage or owner exception turns a non-SAFE verdict into
   approval; only a later round on its own basis agrees. Check each claim
   against the current reviewed bytes, the requirement, its concrete trigger
   and its impact, and keep the original finding and evidence with its
   disposition: verified blocking defect → the smallest adequate in-scope fix
   and a full NEW round (rule 5); verified non-blocking issue → recorded, fix
   optional; refuted claim → the counterevidence and its limits recorded (and
   carried in the next round's current residual); design or scope change →
   the owner (rule 5a); a trigger outside the deployment context (R-THREAT) →
   a recorded fact, no code; speculation → a residual, never code. A
   reviewer's label or suggested design is a claim, and a vote is not
   evidence. **Simplicity (R-SMELL):** a smell needs a concrete current
   correctness or maintenance cost; prefer the smallest correction, never a
   hypothetical extension or new abstraction to satisfy a reviewer; a
   confirmed correctness or security defect is not downgraded because its fix
   is large — disclose the size. Every leg prompt carries the
   verdict-selection rule (SAFE TO MERGE whenever nothing blocks). The
   consolidation duties (verify → classify CONVERGING / CONFLICTED /
   OSCILLATING → the owner on a CONFLICTED item), the severity/triage axes
   and the residual record are in `references/triage.md`. An ADMITTED
   verdict is a validated JSON object, so mapping its `findings[]` into the
   residual table is mechanical (open the file with the Read tool and take the
   fields by name, `references/triage.md` § Consolidating validated LegVerdict
   objects).
   **Admission (v2).** `lib/verdict_v2.py` validates each reply against the
   vendored canonical `spec/contracts/leg-verdict.schema.json` and binds it to
   the attempt that produced it through SIX ALL-OR-NOTHING binding values — a
   wrapper entry's `admit:` line types them as `--expected-review-id /
   --expected-family / --expected-packet / --expected-leg-name /
   --expected-attempt / --expected-route` (`--expected-packet` hashes the delivery record, so no digest is typed); the claude `--admit` line takes them from the attempt's `binding.json`.
   There is no shape-only mode. It REJECTS
   duplicate JSON members at the ORIGINAL text (last-wins parsing would let a
   duplicate `"verdict": "SAFE TO MERGE"` hide an earlier blocking one). Exit
   codes: 0 admitted (one `VERDICT_V2 OK … verdict="<token>"` line, the token
   quoted and LAST) / 1 shape, schema or binding failure / 2 unparseable,
   duplicate member, or a reply not starting with `{` / 3 `--end-marker`
   absent (possible TAIL LOSS) / 64 HOST fault (usage, missing `jsonschema`,
   unusable schema, refused `--admitted-out` target) — a 64 says nothing about
   the leg. The claude entry's RAW reply admits via `--admit … --end-marker
   '<END-VERDICT>' --admitted-out <attempt>/admitted.json`; no repair path:
   only an ADMITTED reply is sealed, a refused one collects as not admitted
   and stays open to `retry` (rule 13), and a new answer comes only from
   `retry` or a new round. A leader-completed reply is never admissible.
5. **Fix→re-review loop — NO round cap, NO focused pass (R-REREVIEW, R-STOP).**
   Findings → fix each (own implementer + per-fix review, SDD/TDD; the leader
   VERIFIES the findings, delegating verification or the implementation to a
   subagent when that keeps its context lean) → a NEW ROUND `r<N+1>`. Any change
   to the reviewed bytes or to the review conditions (prompts, criteria, roster,
   model, effort, route, policy) is a new bound basis that EVERY selected entry
   reviews over the complete agreed scope (the new round's `--diff` covers all
   of it, not the fix's delta); earlier approval never carries forward, and a
   narrow investigation never substitutes for that round. For it the leader
   writes ONE current residual (`--prior-residual`, Flow 2): current findings
   and dispositions, the needed prior excerpts, counterevidence and verification
   results, changes, and remaining uncertainties — rebuilt each round, never
   earlier residuals or transcripts appended (R-CONTEXT: a historical path alone
   is not evidence). In-scope corrections continue at ANY round count while they
   bring new evidence — a material counterexample, a meaningful verification of
   a fix, a resolved necessary unknown; a copied passing test, rewording,
   another vote or the same assertion is not progress.
   Stops: (a) **design change** — a fix that needs a new contract, public
   definition or substantive change to the gated design goes to the OWNER
   before that design work starts (line growth alone is not one); (b)
   **convergence** — `collect` returns `AGREED` (exit 0) on the current
   basis; a fix applied after it is a new basis and owes its own round; (c)
   **no progress** — stop repeating an item no new evidence addresses (items
   still progressing continue), and stop automatic rounds when no remaining
   item has a concrete path to new verification or to resolving a necessary
   fact; record the unresolved dissent, the uncertainty and the stop reason.
   Rule 12's conflict stop and rule 14's TERMINAL exit are stops of this
   kind. A stalled, incomplete, quota-stopped or exception-released round
   stays non-agreed (an owner-set resource limit is a stop reason, never
   agreement). **Docs never gate code** — NARRATIVE documentation only:
   text-only findings on it are batched into one post-merge doc-resync commit;
   a rule, schema, prompt clause or policy file is review scope even as text.
   A plan-gate fold that introduces a NEW semantic contract draws fresh
   findings every round — fold the CONSTRAINTS and delegate the row-level
   design to the owning unit's own gate (`references/triage.md`
   § Scope-expansion gate).
6. **Codex-path caveat (cross-family-rule nuance).** When the work being reviewed IS
   the codex dispatch path itself, codex reviews the *artifact diff*, not its
   own reasoning — cross-family + fresh-eye still holds, so the full set is valid.
7. **Vendor review legs: READ-only, no-mutation/no-execution, generous
   timeout.** Every leg prompt — codex / agy (and the gemini route, kept as
   compatibility with the older gemini CLI), and the claude `Agent` leg, which also enforces no-exec mechanically through its tool allowlist
   (rule 1a) — instructs the reviewer to review by READING (`git diff`, file
   reads): forbidden are file MUTATION, external-state change, and CANDIDATE
   EXECUTION (running tests/scripts/builds or the code under review, spawning
   vendor CLIs). TWO legs' directives are SCOPED to a READ-GRANT: the CODEX
   leg (read-only shell commands explicitly PERMITTED — they are the very
   commands codex reads files with) and the AGY leg
   (the worktree BRIEF read FIRST, the read-audit gate's required entry, then
   verification reads across the pinned tree with file:line cites); both
   trailers are in `references/leg-contracts.md`. For both, the round's
   capture/verify integrity gate (`references/packet-lifecycle.md` § Round
   integrity) is the compensating control — mutation detection, not a
   sandbox claim alone, decides admission. For the AGY leg the containment
   is MECHANICAL: `prepare` writes a PreToolUse hook (`lib/agy_hook.py`) into
   `<worktree>/.agents/hooks.json` that denies every tool outside the
   five-name review allow set (plus `read_url_content` / `search_web` in a
   web round) before it runs, whatever agent resolved (`--agent` fails OPEN
   silently); admission is EFFECT-based (a BLOCKED call is logged, an
   EXECUTED off-list call voids), behind rule 1's two checks. An agentic
   reviewer that live-runs the code can hang on a real vendor call it cannot
   reap under its read-only sandbox, burning the whole timeout. Pair the
   no-exec directive with a **generous timeout** (owner 2026-10-04: a leg can
   reason for 30 minutes): every roster entry sets `timeout_s` 3600; prefer SHRINKING
   the reviewed surface (`--diff-path`, `--tests-path`, `--excerpt`) over raising it.
   For a wrapper leg `timeout_s` is PER ATTEMPT: each server-capacity retry (up to two,
   15 s / 45 s backoff) gets the full `--timeout` again, so its rule-13 wait is 3 × timeout +
   60 s. The claude leg has no capacity retries and its native spawn no deadline: its wait is its `timeout_s`. Avoid concurrent same-family
   pressure (429): dispatch several Google entries, and several codex entries, one after another. A live-run finding can still be valid. Measurements: `references/evidence.md`.
   **REVIEW web is a bound round condition (R-REVIEW-WEB).** Under the
   owner's standing authorization `prepare` binds `review_web_authorized`
   true into every round (a caller's `false` is ignored with a NOTE; only the
   owner revokes it, and a revocation applies to rounds prepared after it). A
   true round dispatches codex with `--search`, agy and gemini with
   `--review-web` (the review web posture, never the investigation
   web-evidence clause) and the claude preset's web twin (rule 15), and
   every prompt carries the shared
   `review-web-permission` clause; the operation stays a REVIEW. Shapes:
   `references/leg-contracts.md` § v2 dispatch shapes. Web on a single-shot
   dispatch is the INVESTIGATION path (R-INVEST), never a leg verdict.
8. **Delivery is the round's WORKTREE, at a repo-relative gitignored path,
   never `/tmp`.** `prepare` creates a DETACHED `git worktree` at
   `<packet-dir>/wt-r<N>` under the gitignored `_runs/review/` — THE ROUND
   LIVES IN THE NAME (`close` derives the round from it, never from the tree's
   content) — pinned at the right-hand side of `--diff`, and writes FOUR
   files into it: `brief.md` (deployment context, a size MANIFEST naming every
   changed file and the surface deliberately excluded, the suspect questions
   LAST), `diff.prod.patch` (the gated material), `diff.tests.patch` (test
   changes, a statement of intended behaviour) and `history.txt` (`git log
   --stat`, commit boundaries without executing anything). Every wrapper leg
   is dispatched `--cwd <worktree>` (a claude Agent leg reads the same tree
   from the paths in its prompt) and reads for itself (the gemini route is
   workspace-sandboxed to the repo and cannot read `/tmp` at all).
   **The LEADER builds the diffs** — every leg must judge the SAME bytes,
   because the binding's `content_digest` ties each verdict to that content.
   `--excerpt` pins a hot function INTO the brief when a diff is near the
   context ceiling. `prepare` runs the round's `capture` (evidence snapshot +
   canonical worktree fingerprint) and the tree stays FROZEN; after every
   dispatched entry terminates, `verify` must print `ROUND_INTEGRITY_OK r<N>`
   (`close` re-runs the check fresh). **Per-entry custody.** `prepare` allocates one
   `results-r<N>/<name>/attempt-K/` per enabled non-skipped entry —
   `binding.json`, `prompt.txt`, `dispatch.json`, `schema.projected.json`
   where the route takes one — and records the frozen roster in
   `.roster-r<N>.json`; `collect` writes `collect-r<N>.json`. One entry plus
   one attempt number is ONE exclusive allocation: a retry allocates the NEXT
   number and never touches attempt K (rule 13). **The packet dir is
   HELPER-OWNED** (owner ruling): for any state it cannot name as its own round
   the helper REFUSES WITHOUT DELETING and points at the one recovery,
   `references/packet-lifecycle.md` § Going on in a new packet dir. Lifecycle
   commands, ownership fences, fencing text, the `Review metadata:` block and
   capture/verify: `references/packet-lifecycle.md`.
9. **codex leg: DE-INLINED — it reads the round worktree like every other leg
   (`--cwd` + READ-GRANT trailer).** The read grant is what lets it
   VERIFY claims (the read-only sandbox blocks writes, never reads; a
   blanket no-exec directive is what would leave it unable to open a file). Its trailer text, the rescoped fast-SAFE
   heuristic, the call-site shape and the single-quoted-heredoc pitfall it must
   avoid are in `references/leg-contracts.md` § codex leg.
10. **claude fresh-eye leg = a separate fresh `Agent`.** Never the leader
    reasoning inline: it does not share the leader's conversation, but it still
    receives the user-global and repo CLAUDE.md and the leader's auto-memory
    index — a fresh conversation proves no isolation from memory or inherited
    instructions (R-PROMPT); record that limit, change no global memory setting.
    Its value is conversation freshness, not family diversity (codex/agy carry
    that). It receives the printed `prompt.txt` unchanged, spawned read-only via
    the reviewer agent (rule 1a); its depth is the preset's frontmatter effort
    (rule 15). `prompt.txt` and every reviewer preset body (the base presets
    and their `-web` twins alike) carry no persona, intensity request or
    predicted-defect list: the prompt of the round carries the purpose and the
    criteria, the body adds none (R-PROMPT).
    A claude SAFE does not average away a vendor must-fix: verify it (rule 4).
11. **Every leg gets the same shared prompt (R-PROMPT).** The vendored clauses
    give every selected entry the same purpose (selected by `--review-kind`),
    requirements, scope and evidence: an evidence-centred independent review
    in which a no-defect conclusion is valid for what was actually checked, no
    severity deflation or inflation, the criteria enumerated before
    concluding, and the verdict-selection rule. The leader adds no per-leg
    framing; its hypotheses go into the brief as questions and never limit
    findings elsewhere; a targeted perspective is an investigation (R-INVEST).
    A fast, terse SAFE is a valid result: it is not retried (R-RETRY), and only
    new evidence justifies another round over it (rule 5). For the agy leg rule
    1's read-audit gate decides first (a VOID leg never counts); latency is a
    signal the leader may record (`references/evidence.md`).
12. **Non-convergence is a STOP, not another round (R-STOP).** Stop repeating
    an ITEM when a new round — without material new evidence — merely flips a
    prior round's settled decision on it, contradicts another leg on it, or
    re-litigates it; items still progressing continue. A flip or contradiction
    that DOES carry new evidence is adjudicated with a deterministic probe
    first. A closed claim reopens only for a new counterexample, a relevant
    source or context change, or a demonstrated error in its refutation. Two
    findings are CONFLICTED only when both survive verification and cannot
    coexist — differing verdicts alone are not a conflict — and the FIRST such
    conflict is an owner call for that decision (rule 4), with a conflict
    table (claim / leg / round / evidence) and no compromise crafted first. A
    refuted side is not a conflict; record its counterevidence. Independent
    legs finding the SAME defect is a CONVERGENCE floor (two entries of one
    family = one leg — `references/triage.md`) — fix it, run the next FULL round.
    **Scope freeze:** a finding outside the agreed scope (a neighbouring
    design, a hypothetical input shape) opens a NEW slice; a verified defect
    inside the agreed scope stays in scope at any round (R-REREVIEW, R-STOP).
    **Two-family floor:** a single-family REACHABLE-UNOBSERVED item without a
    measured probe is a residual, not a fix — it gates code, never agreement.
13. **Leg orchestration: background dispatch, ONE generous wait, no unrelated
    interleaving.** Dispatch every leg in the background and wait
    event-driven: one generous wait per leg, never short repeated polls. An
    expired wait is a wake-up boundary, not evidence of failure — inspect that
    leg ONCE, keep a healthy leg alive to its completion notification, and
    treat it as missing only on a documented terminal failure or an explicit
    owner decision to end the wait; never respawn a healthy leg or re-wait one
    whose result arrived. While legs run, keep the leader's context
    review-adjacent (verification planning, packet hygiene, staging fixes for
    returned findings). Collect once every dispatched entry has returned or
    been logged terminally missing — the collector counts a missing entry as
    `INCOMPLETE`, never as agreement. claude-host mechanics: `Agent` runs in
    the background by default and fires a completion task-notification
    (`SendMessage` resumes a completed agent); wrapper legs are background
    Bash — give a background leg's Bash call a timeout at least as long as that leg's wait, since Claude Code may stop a background command at its default limit (code.claude.com/docs/en/tools-reference); a stop, an error or a dead process shows in the leg's record. **Session-cwd pinning (probe-measured):** the foreground cwd resets
    to the primary working directory at context reinitialization, which lands
    at long-leg wake-ups — RE-READ `pwd` at every wake-up or dispatch boundary
    and dispatch `prepare`'s absolute lines rather than rebuilding them.
    **Retry is a SUBCOMMAND, not a hand-move.** `retry <packet> r<N> <name>
    --diagnosis "<why it failed to RUN>"` allocates attempt K+1 for an entry
    whose RECORDED attempt returned NO valid verdict, re-renders its prompt from
    the round's own frozen roster entry, and leaves attempt K intact (R-RETRY:
    same bound basis). An answer that failed admission (`admit:` exit 1, 2 or 3) is
    a failed attempt for `retry` (it stays unsealed until `retry` seals it
    invalid, spec DL-55) — no need to wait for `collect` (Flow 3). It refuses before any
    mutation a changed review condition, selection or control of that basis
    (a claude entry's shipped preset file is bound by its digest — model,
    effort and body, rule 15), a SKIPPED entry, an absent recorded attempt
    directory and a record with no absolute `hook_log` — each a NEW round.
    A valid NEGATIVE
    verdict is completed work, never retried — correcting what it found changes
    the basis, a NEW ROUND (rule 5). **A recorded attempt is SEALED (R-BIND)**
    and never re-answered: a new answer needs `retry` (never over an attempt
    sealed valid) or a new round, and a sealed file that changes is that
    entry's integrity failure — who seals, what is refused and when to collect
    again: `references/leg-contracts.md` § Attempt seal. Never hand-remove or hand-rename anything under
    `results-r<N>/`, and never chain a file operation on a helper-managed file
    before a dispatch (a failed `mv &&` left a leg unlaunched).
14. **Finding triage and over-design containment (owner directive; R-VERIFY,
    R-SMELL, R-THREAT).** The loop structurally rewards ADDING code, so every
    finding is classified during rule-4 consolidation BEFORE it may enter the
    fix queue: **REAL** (demonstrated — a repro, a logged occurrence, a checked
    source or cited passages read side by side) → the smallest adequate fix;
    **REACHABLE-UNOBSERVED** (mechanism exists, no occurrence evidence) →
    verify the trigger FIRST — for a vendor-output trigger, from REAL vendor
    output (a capture, a run-log, an audit row): a fixture-only repro or a
    failed repro records a DISCLOSED residual, not code (occurrence gate,
    `references/triage.md`); **SPECULATIVE** (cannot occur in this deployment
    — including, in a TRIAD host's own code, a trigger R-THREAT rules out:
    deliberate tampering with the host's own files or a second operation inside
    one working folder) → **no code**, a recorded fact; a stop at any point (a
    token or usage limit too) and a leader's hand-made file layout are ordinary
    failures; a vendor shape no run has shown is a recorded limit
    (HARDENING-SUGGESTION). A fix that
    expands design scope (a new guard / fallback / retry / lock / validation
    layer, a new file / dependency / config surface, a spill beyond the
    finding's file) STOPS for an owner OK, even mid-round, only when it changes
    a contract, adds a public definition or changes the gated design (R-STOP);
    otherwise continue and disclose it, with its size — a confirmed defect is
    never downgraded for size. A round whose remaining findings are all
    SPECULATIVE or repro-failed is TERMINAL (rule 5c): record the residuals and
    route to the owner any whose row would be BLOCKING; every unfixed finding
    keeps its ledger record. Details: `references/triage.md`.
15. **Model and effort are DISPATCH-TIME DATA.** No code in this skill pins a
    vendor catalog slug (`~/.claude/CLAUDE.md` § Web search rules): the tiers
    a round runs at live in the roster files (`agy.model` / `agy.effort`,
    `codex.model` / `codex.reasoning`, `gemini.model` for the legacy gemini-compatibility route, `claude.agent`).
    **The claude leg picks a SHIPPED PRESET.** It runs as a native Claude Code subagent whose model and
    effort are fixed in its agent file: Claude Code has no per-call effort setting, and the spawn passes
    NO `model` parameter (one would override the file's pin). So `claude.model` and `claude.effort` must
    be null (refused, as `gemini.effort` is), and another model or effort is another preset — a host
    release, not a roster value. Name one in `claude.agent` by its bare name, in a plugin install too (a
    `:` is refused; the host adds the scope). A name outside the six shipped presets (the three below
    and their `-web` twins) is refused before the round starts. A web round spawns the twin (same model
    and effort, plus `WebSearch`, `WebFetch`):

    | `claude.agent` | model | effort | web twin |
    |---|---|---|---|
    | `cross-family-review-reviewer` (default) | `opus` | `xhigh` | `-web` |
    | `cross-family-review-reviewer-high` | `opus` | `high` | `-high-web` |
    | `cross-family-review-reviewer-max` | `opus` | `max` | `-max-web` |

    The model is the `opus` alias: Claude Code resolves it to the latest Opus on the subscription login
    route (an `ANTHROPIC_DEFAULT_OPUS_MODEL` setting remaps it). An older model is not selectable.
    `roster_v2.py resolve` prints the model and effort of the preset each enabled claude entry names. The operator's own Claude Code settings — a setting that forces
    the subagent model, an effort environment variable, an organization effort cap — outrank the
    preset's pins. Claude Code keeps each subagent's own transcript. A comparison CAMPAIGN over two arms
    of one family (when the leader declares one) gets a leader-written ledger at
    `docs/reviews/<date>-x-leg-<name>-campaign.md`; per-round fields:
    `references/triage.md` § Fourth-leg comparison record.

## Helpers (`lib/`) and vendored spec (`spec/`)

| Helper | What it owns |
|---|---|
| `lib/review_scratch.py` | packet lifecycle + `prepare` + `collect` / `retry` + `capture` / `verify` / `close` |
| `lib/roster_v2.py` | defaults + project override merged by name, schema validation, capability refusals, the Google chain, the rendered dispatch per entry (`resolve <abs-worktree>` prints the resolved roster) |
| `lib/prompts_v2.py` | one prompt per entry from the VENDORED clause bytes (`spec/prompts/`), with a per-clause sha256 manifest |
| `lib/verdict_v2.py` | admission against the canonical schema + the six-field binding (rule 4) |
| `lib/collect_v2.py` | the all-entry outcome, the seals, and the diagnosed retry allocation (rule 13 / Flow 4) |
| `lib/read_audit_gate.sh`, `lib/agy_hook.py` | the agy entry's mechanical read-audit gate and PreToolUse hook (rules 1 and 7) |

`spec/` holds the SHARED-SPEC payload bytes verbatim — contracts
(`leg-verdict.schema.json`, `review-legs.schema.json`, `exit-tokens.json`,
`receipt-fields.json`), prompt clauses, reference docs — plus HOST DATA, the default roster `review-legs.default.json` (manifest `host_data`, edited here),
with a sha256 per file in `spec/SPEC_MANIFEST.json`. The repo-root `SPEC_REVISION`
names the CANDIDATE commit those bytes came from: reading a candidate is
provenance, NOT adoption of a tagged revision. Never edit a payload; re-vendor
it and update the manifest (a host-data edit updates its digest there). The producer projection a vendor receives
(`schema.projected.json`) is in `references/leg-contracts.md` § Producer schema projection —
admission always runs the FULL canonical schema, never the projection.

**Retired v1 round.** `prepare` always prepares the named-roster round;
`--v2` is accepted and changes nothing. `--x-leg` / `--no-x-leg` are unknown
options, `$TRIAD_REVIEW_X_LEGS` and a user-scope roster file are never read,
and a v1 project roster file is refused by the roster schema. A packet an
earlier version prepared (no `.roster-r<N>.json`): `collect` refuses it —
close it and prepare a new round.

## Flow

1. Scope the review: branch ref + base SHA + the list of suspect/omitted/
   simplified decisions (phrased as questions). Open a packet dir FOR EACH
   ROUND with the rule-8 helper (`python3 <skill>/lib/review_scratch.py open
   <abs>/_runs/review <gate-slug>-r<N>`, which also prunes stale packets from
   crashed past reviews). Author
   the round's BRIEF — deployment context above one `=====QUESTIONS=====`
   marker line, the suspect questions below it — as a standalone file; that
   brief (plus the current residual, rule 5) is the ONLY per-round text the leader writes. Its context (R-CONTEXT): review basis and scope, target runtime/deployment, relevant dependency declarations and resolved versions, the verification actually observed, material assumptions, and unknown or conflicting facts — each cited, `unknown` with a reason rather than a guess, no credentials. Keep the GATED SURFACE
   focused: for a LARGE diff name only the high-risk subset (a narrowed
   `--diff` range, `--diff-path` scoping, `--tests-path` to split test churn
   out of the gated patch, `--excerpt` hot functions into the brief) —
   `references/packet-lifecycle.md` § Large diff.
2. **Prepare the round with ONE deterministic command.**
   `python3 <skill>/lib/review_scratch.py prepare <packet-dir> <source-repo>
   r<N> --brief <abs-brief.md> --diff <range> [--diff-path <rel>]...
   [--tests-path <pathspec>]... [--excerpt <rel>:<start>-<end>]...
   [--prior-residual <abs-file>] [--review-kind formal-plan|pre-merge|implementation-review]`
   — `--diff <range>` spans the COMPLETE agreed scope, never only the latest
   fix's delta (a new basis is reviewed in full, rule 5); `--diff-path` scopes
   the reviewed surface, `--tests-path` splits test churn out of the GATED patch
   (the review-is-CODE-only rule; tests = `--diff-path` scope ∩ `--tests-path`,
   so name test dirs in `--diff-path` too), `--prior-residual` fences the
   leader's ONE current residual (rule 5) once into `brief.md`, which every leg
   reads, as DATA (no residual = omit the flag; an empty file is refused), and
   `--review-kind` selects the purpose clause (omitted = `pre-merge`;
   `formal-plan` = the plan purpose). The round binds the stage,
   `review_web_authorized` (rule 7) and its UTC date. It creates the round
   WORKTREE at `<packet-dir>/wt-r<N>` (a packet dir that already holds a round
   refuses, creating nothing) pinned at the right-hand side of `--diff`, writes its
   four artifacts (`brief.md`, `diff.prod.patch`, `diff.tests.patch`,
   `history.txt`) FILE-TO-FILE (never streamed through leader context), writes
   `delivery-r<N>.md` + `digest-r<N>.txt`, resolves the ROSTER, allocates
   `results-r<N>/<name>/attempt-1/` per enabled non-skipped entry (rule 8),
   records `.roster-r<N>.json`, and runs the round's `capture` — so every byte a
   leg reviews sits inside the census by construction
   (`references/packet-lifecycle.md`). READ ITS STDOUT: any `WARNING:` line
   comes FIRST, then one COMPLETE dispatch line per entry, then
   each `SKIPPED <name>: <reason>` and the roster NOTE.
3. **Dispatch EVERY printed entry — in parallel (rule 13), same-family entries
   one after another (rule 7) — and run the checks each entry's line printed.** Take the wrapper line VERBATIM, `env` members included — the wrapper's run-log under `<attempt>/logs/` is the receipt `collect` compares with the recorded argv, so an env-less line makes that entry INVALID and a line edited after it was printed is refused by the wrapper itself before the vendor runs (exit 3, R-BIND, C32); it already
   carries `--sandbox read-only`, the entry's tier, `--attempt <k>`, the
   producer schema file where the route takes one, the absolute `--prompt-file`
   / `--cwd`, the timeout and the redirections into that attempt dir. The claude
   NATIVE entry is not a wrapper call: spawn `Agent` with the printed
   `subagent_type` and NO `model` parameter (rule 15) on the CONTENT of the printed `prompt.txt` (rule 10) AFTER
   its `guard:` line exits 0, then save its reply VERBATIM to the printed
   `raw.json`, never over an existing file — its LAST `SubagentHandback`
   tool_use `message` if it handed back that way, else its last assistant text.
   Then run each printed check line: for an agy route the read-audit `gate:` and
   the `hook:` LOAD CHECK (both must pass before that entry's verdict is weighed
   or any of its findings enters the residual table), and for EVERY entry the
   `admit:` line — `verdict_v2.py … --admit` for the claude raw reply,
   `verdict_v2.py <verdict.json>` for a wrapper entry, that one carrying the
   six `--expected-*` flags including `--expected-packet
   <packet-dir>/delivery-r<N>.md` (the claude line types none: it reads the attempt's `binding.json`, and a typed flag that disagrees is exit 64). `collect` re-admits a wrapper entry's `verdict.json` itself; for the claude entry it admits `admitted.json` as found — it never admits a `raw.json` alone, so a saved, admissible `raw.json` with no `admitted.json` and no seal is reported "never admitted" and `retry` refuses it until its `admit:` line runs (a refused one collects as not admitted, `retry` open); the printed `admit:` line is the EARLY per-entry check — its exit 1, 2 or 3 is a failed attempt that `retry` may take as soon as the entry has terminated, without waiting for `collect` (rule 13); a sealed attempt refuses the native line (`references/leg-contracts.md` § Attempt seal). Do not retype these commands: a hand-built
   one is how a round gets admitted against the wrong digest. Per-entry flags
   and prompts: `references/leg-contracts.md`.
4. **Once every dispatched entry has terminated, `verify` then `collect`.**
   `verify <packet-dir> <packet-dir>/wt-r<N> r<N>` must print
   `ROUND_INTEGRITY_OK r<N>` (a mismatch INVALIDATES the round: mutation
   detected, never released). Then
   `collect <packet-dir> r<N>` (it runs `verify` itself before `AGREED`; a failed check is exit 2, a host fault 64) folds each enabled entry's attempt AS NAMED BY THE ROUND RECORD (a HIGHER attempt directory on disk — one this round never allocated — makes that entry `invalid` only when the recorded attempt is not valid; `references/triage.md` § Collect outcomes)
   into ONE outcome, which IS the exit code:
   - **`AGREED` (0)** — the selected roster is nonempty and EVERY entry
     returned a valid, explicit `SAFE TO MERGE` with no blocking finding and
     no open question; family coverage is reported, never a threshold. Proceed to Flow 5.
   - **`BLOCKED` (4)** — a valid entry's verdict is not `SAFE TO MERGE` (a
     Minor-only negative included, recorded as a deviation), or it carries a
     blocking finding or an unresolved OPEN QUESTION. VERIFY each finding
     (rule 4) and TRIAGE it (rule 14); fixes are a NEW ROUND (rule 5).
   - **`INCOMPLETE` (5)** — some enabled entry is missing or invalid, INCLUDING one the roster SKIPPED (it is counted and named with its skip reason — rule 1). Each non-valid entry's reason names its cause — an agy evidence tool's failure as its token and exit code; when it says prepare a NEW round, `retry` refuses too. Diagnose WHY it failed to RUN, then `retry <packet-dir> r<N> <name> --diagnosis "<why>"` — it PRINTS the new attempt's dispatch / gate / admit block exactly as `prepare` did; run those lines for that entry only (attempt K+1 on the unchanged basis) and dispatch the new attempt. `retry` REFUSES before any mutation in the rule-13 cases (a recorded attempt directory that is absent: prepare a new round). A valid NEGATIVE verdict is never an `INCOMPLETE` retry, and a SKIPPED entry is settled by the leader installing its route or asking the owner for a roster change (a NEW round), not by retrying it. An entry that ended on a SUBSCRIPTION CAP (`[wrapper] <cli> cli-subscription-cap`, exit 65) is not retried before its quota resets, and the host compensates NOTHING on its own: never another model, never an added or substituted leg. Tell the OWNER which entry hit the cap and offer the three exits — wait for the reset and `retry`; an owner EXCEPTION on the entries that answered (a ledger record; the round stays `INCOMPLETE`, rule 1); or ask for a roster change (an extra entry, or a second entry of an answering family — a separate invocation identity with the same shared prompt), which is a NEW round.
   - **`BASIS CHANGED` (2)** — the installed toolkit differs from the round record's `toolkit_map` (`the installed toolkit changed since this round was prepared: <files> — prepare a new round (R-REREVIEW)`), the record carries no map, or the record's selection or configuration differs from the round's bound basis. A changed basis is a NEW ROUND, never a re-collection (`references/triage.md` § Collect outcomes).
   - **`HOST FAULT` (64)** — THIS host cannot admit any reply (`jsonschema` absent, the vendored contract unusable in ANY way — unreadable, invalid UTF-8, non-JSON, over-nested, not Draft 2020-12) or an agy evidence tool (read-audit gate / hook check) could not RUN at all, or an installed toolkit file cannot be read. `collect` STOPS and writes NO per-entry state: nothing about any leg is known, so repair the host and collect AGAIN — never re-dispatch paid legs over it. A contract that cannot LOAD is 64; one that loads and DIFFERS is the exit-2 basis refusal above (`references/triage.md` § Collect outcomes).
   Then run rule 4's consolidation over the collected findings.
5. **Close the round.** Run any owed REACHABLE-UNOBSERVED repros FIRST — a
   successful repro reclassifies the item REAL and it joins the fix path. Then:
   - Any REAL blocking finding → the smallest adequate fix (implementer +
     per-fix review; a design-expanding fix stops for an owner OK), then GOTO
     1 (open a new packet dir) and 2 for round `r<N+1>` with the current
     residual (rule 5).
   - A CONFLICTED item (both findings survive verification) → the owner
     decides that item, with the rule-12 conflict table; an item oscillating
     without new evidence stops repeating; every other item continues (R-STOP).
   - The round collected `AGREED` and no fix follows → the gate is done once
     every rule-14 obligation is discharged (owed repros run; SPECULATIVE /
     UNKNOWN-CONTEXT residuals and every unfixed REAL Minor recorded).
   - No remaining item has a path to new evidence (rule 5c; rule 14's TERMINAL
     round) → stop: record the dissent, unknowns and stop reason and hand the
     merge decision to the owner. The round stays non-agreed; an owner exception
     is recorded as an exception, never as agreement. Do not GOTO 1.
   Restore a per-round live roster override once `collect` has run (the round
   reads its frozen `.roster-r<N>.json`). Close each round's packet dir once
   the next round is prepared, and the last one at gate end — after the
   COMPLETE residual table is copied to
   `docs/reviews/<UTC-date>-<slug>-residuals.md`: `close <packet-dir>` DELETES
   the dir. Close WARNS when the last captured round does not verify NOW (it
   re-runs `verify`), checks the round tree once and refuses — deleting
   nothing — if a leg wrote into it, and a SECOND close
   of the same (now absent) dir is a no-op at rc 0.

## Failure modes

Symptom → cause → the rule that owns the fix: `references/failure-modes.md`.
It is an index, not a second statement of the rules.

## Why this exists

A same-family review chain shares the leader's blind spot, and a strict per-task
same-family review still misses cross-cutting issues. The originating incident
and the re-validation are in `references/evidence.md`.

## Related

- `triad-codex-dispatch` (codex leg) / `triad-antigravity-dispatch` (the Google-family leg) / `triad-gemini-dispatch` (compatibility with the older gemini CLI) — those SKILLs own the wrapper flag contracts this skill's rendered argv uses.
- `superpowers:subagent-driven-development` — the per-task (same-family) review this final pass backstops.
- `superpowers:requesting-code-review` / `superpowers:receiving-code-review` — single-reviewer code-review conventions.
