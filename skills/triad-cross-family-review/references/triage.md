# Cross-family review — consolidation, finding triage, residual table

Loaded on demand from `triad-cross-family-review/SKILL.md` (Hard rules 4 and
14). Read this while consolidating a round's verdicts, before a finding enters
the fix queue, and when recording or updating a residual.

## Contents

| Section | Open it when |
|---|---|
| Consolidation duties | a round's legs have all returned |
| Dispositions | deciding what a verified, refuted or unverifiable finding becomes |
| Collect outcomes | `collect` returned a non-zero exit and you need the rule it applied |
| A non-SAFE verdict at the merge gate | Flow 4 and an entry's verdict is still non-SAFE |
| Triage classes | classifying a finding before the fix queue |
| Scope-expansion gate | sizing a fix for a REAL finding |
| Loop exit | the round lands no REAL findings |
| Residual table | recording a residual, or writing the next round's current residual |
| Consolidating validated LegVerdict objects (Read tool) | an entry's admitted verdict needs mapping into the residual table |
| Fourth-leg comparison record | two entries of ONE family ran this round and you are recording the comparison |

## Consolidation duties

Three duties, in order:

1. **Verify every finding against the current reviewed bytes before acting on
   it (R-VERIFY).** Read the cited lines and check the claim against the
   requirement, its concrete trigger and its impact — a deterministic probe
   (grep, a controlled fixture, official docs), a checked source or a static
   contradiction (R-STOP). A finding can be plausible and wrong; a reviewer's
   confidence, label or suggested design is a claim, and a vote is not
   evidence. Verify a proposed repair the same way.
2. **Classify the round**: CONVERGING (new verified findings, or independent
   legs hitting the SAME defect — the rule-12 convergence floor), CONFLICTED
   (two findings that both survive verification and cannot coexist — one
   requires what the other forbids; differing verdicts alone are not a
   conflict), or OSCILLATING (verdict flips or re-litigation without new
   evidence). Then, per finding, triage it REAL / REACHABLE-UNOBSERVED /
   SPECULATIVE before it may enter the fix queue.
3. **On a CONFLICTED item, call the owner for that decision immediately** — a
   push notification where the harness exposes one, else a clearly-marked
   OWNER-CALL section carrying the rule-12 conflict table. The leader never
   self-adjudicates a compromise between surviving contradicting findings and
   spends no further round on that item; other items keep their fix loop
   running meanwhile. **On OSCILLATION, stop repeating the items no new
   evidence addresses (R-STOP)**; when no remaining item has a concrete path
   to new verification, stop the automatic rounds, record the unresolved
   dissent, the uncertainty and the stop reason, and brief the owner.

Cross-family complementarity is the point: each family tends to catch a different
class of issue (an extractor bug, a classifier false-positive, a config/safety
gap), with little overlap.

## Dispositions

Agreement is the collector's alone (R-AGREE): a round is agreed only when EVERY
selected entry explicitly returns SAFE TO MERGE on the current basis. No
disposition below rewrites a leg's negative verdict into approval; only a later
round on its own basis can agree. Keep the original finding and its evidence
with each disposition (R-VERIFY):

1. **verified blocking defect** → the smallest adequate fix and a full NEW round
   (R-REREVIEW);
2. **verified non-blocking issue** → recorded; fixing it is the maintainer's
   option (a fix is a new basis);
3. **refuted claim** → record the specific counterevidence and its limits.
   REFUTED means the finding's factual PREMISE is shown false; a repro that
   merely fails to trigger the mechanism is not a refutation. The refutation
   travels in the next round's current residual, where every leg checks it as
   a claim;
4. **design or scope change** → the owner before the design work (R-STOP);
5. **outside the deployment context** (R-THREAT, a TRIAD host's own code) → a
   recorded fact, no code, never blocking;
6. **speculation** → a residual, never speculative code.

An owner EXCEPTION may authorize a separate human action (a merge over a
non-agreed round); it is recorded as an exception to that round, never as
agreement.

Two axes travel as a pair per finding: the LEG's severity (Critical / must-fix /
Minor, verdict-level DO-NOT-MERGE) decides whether merge is blocked; the LEADER's
triage decides whether code is written.

## Collect outcomes

`review_scratch.py collect <packet-dir> r<N>` (`lib/collect_v2.py`) reads
`.roster-r<N>.json`, walks EVERY enabled entry — a SKIPPED one is counted and
named as a `missing` result (`SKIPPED at prepare and never dispatched: …`),
never passed over — takes each dispatched entry's attempt AS NAMED BY THE ROUND
RECORD (an unallocated higher directory on disk is that ENTRY's `invalid` when
the recorded attempt did not return a valid verdict, below), admits it through
`lib/verdict_v2.py`, and returns ONE outcome as its exit code. The rules it applies — none of them re-stated anywhere else:

| exit | outcome | what it means and what the leader does |
|---|---|---|
| 0 | `AGREED` | the selected roster is nonempty and EVERY selected entry returned a valid, explicit `SAFE TO MERGE` with no blocking finding and no open question. Leg count and family coverage are reported, never a threshold (a one-leg or one-family roster agrees by the same rule). This is the collector's agreement on the reviewed bytes — it does not by itself authorise merge, install or release (SKILL Flow 5 owns that). |
| 4 | `BLOCKED` | a VALID entry's verdict is not `SAFE TO MERGE` — a Minor-only negative included (below) — or it carries a Critical / must-fix finding or an unresolved OPEN QUESTION. `acceptance` grants no exemption — an `informational` entry blocks like a `required` one. Verify each finding (§ Dispositions), triage it, and take the fixes to a NEW round. |
| 5 | `INCOMPLETE` | some enabled entry is missing (a SKIPPED entry included), unreadable, or failed admission. NOT agreement and never a silent pass. Diagnose why that entry failed to RUN, then `retry <packet-dir> r<N> <name> --diagnosis "<why>"`; a valid NEGATIVE verdict is completed work and is never a retry case. A claude reply the admission refused collects as not admitted (`MISSING — no result file at <attempt>/admitted.json`) and stays open to `retry` (`references/leg-contracts.md` § Attempt seal). `retry` refuses — and the remedy is a NEW round — for a SKIPPED entry (`it never ran, so there is no attempt to retry`). |
| 2 | refusal | no or unreadable round record, a round record with no `entries`, a record whose selection or configuration differs from the round's bound basis (`delivery-r<N>.md`), an unknown or non-dispatched entry name, an empty `--diagnosis`, or a retry on a completed review. **Also the INTEGRITY refusal**: before `collect` reports `AGREED` it runs the round integrity check (`review_scratch.py verify`) itself (R-AGREE: no integrity failure), so a skipped or too-early `verify` never yields `AGREED`; when that check fails, `collect` gives ONE refusal — ``every entry agreed, but the round integrity check (`review_scratch.py verify`) failed: <verify's reason> — the round is INVALID; prepare a new round`` — and leaves the previous collection record untouched. A check that could not be launched, or ended with any exit but its own refusal's 2 (a traceback, a signal), is a host fault: exit 64, repair the host and collect again. **Also the TOOLKIT refusal**: a changed, added or missing toolkit file, or a round record with no toolkit map — prepare a new round (the TOOLKIT MAP paragraph below). |
| 64 | HOST FAULT | **THIS HOST cannot admit any reply (or could not RUN the round's evidence tools), so nothing about ANY leg is known.** `verdict_v2` reserves exit 64 for the admission it could not RUN at all — `jsonschema` absent, the vendored contract unreadable / invalid UTF-8 / non-JSON / nested past the interpreter's limit / not Draft 2020-12 (EVERY load-failure class takes this exit). `collect` (and `retry`) STOP at the first such admission with `collect_v2: HOST FAULT: this host cannot admit any reply: <reason> (reached while admitting <path>)` and write NO per-entry state — recording it as the ENTRY's `invalid` would fold the round to `INCOMPLETE` and send the leader to re-dispatch PAID legs over a broken install. **The agy entry's two EVIDENCE TOOLS take the same exit**: `read_audit_gate.sh` and `agy_hook.py check` both reserve rc 64 for "this invocation could not RUN at all" — a required file the round named is gone, a removed worktree, an absent `hook_log`, an unusable argv — and that is a `_HostFault` too, never that leg's `invalid`. **ORDER against the exit-2 toolkit refusal**: the HOST question comes first — a contract this host cannot even LOAD is 64, and only a contract that loads and DIFFERS is the exit-2 "the installed toolkit changed — new round". An installed toolkit file this host cannot READ is 64 too. Repair the host and collect AGAIN — the legs' own outputs are untouched and nothing needs re-dispatching. |

**The binding is DERIVED, never read back.** `collect` checks each attempt's
`binding.json` against the six values it derives from the round record, the
frozen roster entry and the directory name — `references/leg-contracts.md`
§ Verdict binding — all legs, item 1.

**THE ROUND RECORD DECIDES WHICH ATTEMPT IS EVALUATED — an attempt above the
record's is refused, not adopted** (`collect_v2._evaluate`, `retry`).
Allocation is the RECORD's act: `prepare` writes attempt 1 and `retry`
allocates first, then writes the diagnosis and bumps the record. A retry that
stopped in between (a failed diagnosis or record write, an interrupted
process) leaves `attempt-K+1/` on disk while the record still says K; an
attempt above the record's may also be restored from a backup or planted by
hand, and with a binding that satisfies the derivation and a schema-valid SAFE
verdict it could otherwise supersede the recorded attempt's BLOCKING verdict.
So it is never taken over:
- `retry` refuses before it writes or allocates anything, at every gap width:
  `<dir>/attempt-<N> already exists while the round record names attempt <K>
  (an interrupted retry) — nothing is allocated; prepare a new round`.
- `collect` makes THAT ENTRY `invalid` with the same refusal (or an earlier
  refusal of `retry`'s — the `admit:` line, or a new round) followed by
  `(also: <dir> is an attempt this round never allocated; the recorded attempt
  <K> is <state>)`; every other entry still collects and the round lands on
  INCOMPLETE. It fires only when the RECORDED attempt did not return a valid
  verdict: a completed review is never vetoed by an unallocated directory,
  which is then simply not read.
- Nothing is deleted: the packet dir is helper-owned, and nothing under
  `results-r<N>/` is removed by hand. Remedy: prepare a new round.
Exactly `attempt-<record.attempt>/` is evaluated, so a RECORDED attempt the
tree does not hold is that entry's `invalid` (`… attempt-<K> is not on disk
…`), and `retry` refuses it BEFORE allocating anything (`… — prepare a new
round`).

**THE ROUND RECORD is read, not shape-checked** (`collect_v2._read_record`).
An absent record refuses (`no round record at <path> — this round was not
prepared …`), and so does one with no `entries` (exit 2). The record is this
helper's own: a hand-corrupted one is tampering (R-THREAT), and a stop
mid-write is covered by the temp file + `os.replace` writer below.

**An attempt directory is `attempt-<N>` (N ≥ 1, ASCII digits, no leading
zero) and a real directory.** Any other name starting `attempt-` — a
non-decimal suffix, `attempt-01`, a symlinked or non-directory `attempt-K` —
is refused by name, never skipped (skipping would read a LOWER attempt than
the tree holds): `<path> is not an attempt directory this helper allocates
(attempt-<N>, N ≥ 1, no leading zero) — prepare a new round`. Inside
`collect` the refusal is scoped to that ENTRY (it goes `invalid`, every other
entry still collects, the round lands on `INCOMPLETE`), and a `retry` of that
entry refuses with the same sentence. Nothing is followed or deleted.

**Precedence when several conditions hold at once** (`collect_v2._outcome`): `INCOMPLETE` wins over `BLOCKED`, and `AGREED` only when neither applies — an invalid entry is reported before a blocking finding on another entry. Family coverage never enters the outcome.

**`retry` ALLOCATES FIRST, diagnoses second.** The command renders and
`v2_write_attempt`s attempt K+1 (an exclusive-create allocation), and only
once that returns does it write `retry-diagnosis.txt` into attempt K, bump
the record and print the new dispatch line. The order matters because the
guard at the top refuses any attempt that ALREADY carries a diagnosis: a
diagnosis written first, followed by an allocation that failed (an
unwritable results tree, a directory that raced in), would leave the leg
PERMANENTLY unretryable. The diagnosis only ever records a step that actually
happened. **That write is GUARDED**: an `OSError` (an unwritable attempt
directory, a full disk) AFTER `v2_write_attempt` has allocated attempt K+1 is
a one-line refusal naming the allocated directory and stating that the round
record still names attempt K, so the next `retry` refuses on the allocated
attempt: prepare a new round.

**An attempt above the recorded one refuses `retry`** — the ROUND RECORD
paragraph above. The ordinary `retry` also refuses outright on any existing
`retry-diagnosis.txt` in attempt K — `attempt K has already been diagnosed and
retried` — a symlink included, and nothing is written through it.

**BOTH records this helper writes go through ONE writer**
(`collect_v2._write_json`): `collect-r<N>.json` and the round record
(`.roster-r<N>.json`) are written to a pid-suffixed temp file and
`os.replace`d, so a reader sees the old record or the new one, never half of
one, and a link at the target is replaced, never written through. A write
that fails is one refusal naming the record, and the temp is removed.

**Every record load tolerates a RECURSIVE document.** `json.loads` raises
more than `ValueError`: a document nested past the interpreter's recursion
limit raises `RecursionError`, which is NOT a `ValueError`. Every record load
in `collect_v2` (and `review_scratch`'s round-record read) catches the same
tuple — `(OSError, ValueError, RecursionError, UnicodeDecodeError)` — and
reports the offending file by name; `roster_v2._read_json` catches
`RecursionError` beside `ValueError` too, so a roster or leg-config document
nested past the limit is a one-line refusal at exit 2 like every other
loader failure.

**Subprocess output is decoded UTF-8, and under the C locale the collector's
own streams print UTF-8.** `collect_v2._run` — the helper that shells out to the agy
read-audit gate and the hook check — pins `encoding="utf-8",
errors="replace"`, the same pin the wrappers apply to every vendor pipe:
`text=True` alone decodes with `locale.getpreferredencoding()`, and under an
ASCII locale the gate's own em-dash diagnostics would raise
`UnicodeDecodeError` where the agy entry owes a one-line reason. On the
OUTPUT side the review libs relax nothing: under the C locale Python 3.12
runs in UTF-8 mode (measured on macOS and Ubuntu 24.04), so a refusal
sentence carrying an em-dash, a path or a vendor token prints as UTF-8. A
recorded limit, no code: under a UTF-8 locale that is not the C locale, UTF-8
mode is off and stdout is strict, so a surrogate-escaped path could still
raise on stdout.

**…and `stdout` is the PAYLOAD stream and is NEVER re-encoded.**
An error handler such as `backslashreplace` on `stdout` would be
right for operator prose and wrong for what a machine or an operator
CONSUMES on this stream — `review_scratch`'s six dispatch lines (`prompts_v2`
is a library and prints nothing). `backslashreplace` would silently REWRITE
them (a dispatch line's non-ASCII path token printed as `caf\xe9` under
`LC_ALL=C`, i.e. a path that does not exist, handed to an operator with no
warning). The printer encodes ONCE as UTF-8 and writes to `sys.stdout.buffer`
(`review_scratch._emit_payload`), so the locale gets no vote; every token in a dispatch line
is already `shlex.quote`d by the caller. A text this host cannot represent as
UTF-8 — a path decoded with `surrogateescape` — is **REFUSED BY NAME** rather
than escaped (`a dispatch line carries a path this host cannot represent as
UTF-8 … rename the offending path`), because a mangled path in a command the
operator RUNS is the failure the emitter exists to stop.
Wrapper-side counterpart: the plugin `README.md` § Payload vs
diagnostic streams.

**`collect` and `retry` compare the round's TOOLKIT MAP with the installed
files.** R-RETRY re-renders from the round's own frozen roster entry, so the
leg CONFIG cannot move — but the CLAUSES are re-read from the live
`spec/prompts/*.md`, `roster_v2.render_dispatch` re-derives
`schema.projected.json` from the vendored
`spec/contracts/leg-verdict.schema.json`, `verdict_v2` judges every reply
against that same contract, and a claude entry spawns a shipped preset file.
`prepare` records `toolkit_map` in `.roster-r<N>.json` — every file directly under `lib/`,
every file of the vendored `spec/` and the six shipped reviewer presets, each
with its sha256 — and `collect` (before any entry is judged) and `retry`
(before `v2_write_attempt`, so a refusal leaves nothing behind) compare it
with the installed files. Any changed, added or missing file refuses: `the
installed toolkit changed since this round was prepared: <files> — prepare a
new round (R-REREVIEW)`, every entry reviewing the new basis again. A changed
toolkit is a NEW ROUND, never a quiet re-render or a re-collection. The
admission contract is the one basis no leg artifact evidences: an admitted
`verdict.json` carries no trace of the schema that let it through. A record
with no map refuses the same way — `this round was prepared before the host
recorded its toolkit map — prepare a new round`: a toolkit that cannot be
proven is never inferred. The `prompt_manifests` member stays recorded as
evidence of each entry's clauses; it is not compared.

**Minor-only NEGATIVE verdict = `BLOCKED` + a deviation record.** An entry
that returns `MERGE WITH FIXES` or `DO NOT MERGE` with ZERO blocking findings
and ZERO open questions is schema-valid but is NOT agreement (R-AGREE): the
collector keeps its verdict, folds the round to `BLOCKED`, and marks the entry
`deviation` (the verdict token disagrees with its own content). The leader
cannot convert it into SAFE TO MERGE. Record the deviation; the leg prompt
already carries the verdict-selection rule, so the round agrees only when a
later round's entries each return SAFE TO MERGE on their own basis.

On an agy route the CUSTODY check, the per-attempt READ-AUDIT GATE and the
HOOK LOAD CHECK are part of the result: an entry that fails one is `invalid`,
its reason naming the check (an ungated agy answer is UNVERIFIED, never
agreement). Each check's contract and remedy: `references/leg-contracts.md`
§ agy leg (the Read-audit binding bullet), § agy hook load check and § agy
read-audit gate.

## A non-SAFE verdict at the merge gate

On a v2 round there is no release carve-out: every verdict other than SAFE TO
MERGE keeps the round non-agreed (`BLOCKED`), whether its findings are refuted,
non-blocking or owner-accepted (R-AGREE). The refutations and dispositions go
into the next round's current residual (§ Residual table); a merge over a
non-agreed round is an owner EXCEPTION (§ Dispositions), never agreement.

## Triage classes

The fix→re-review loop structurally rewards ADDING code — reviewers are rewarded
for findings and nothing rewards simplicity — so unchecked rounds grow defensive
layers. Before ANY finding enters the fix queue the leader classifies it during
consolidation (the deterministic probe doubles as the occurrence check):

- **REAL** — demonstrated rather than argued: a runtime repro, a logged/audited
  occurrence in THIS deployment, or — for a spec/doc/interface defect — the cited
  passages read side by side. A static contradiction, wrong flag, or broken
  cross-reference is REAL as soon as reading reproduces it; the "concrete trigger
  scenario" test applies to runtime-behaviour findings. → the smallest adequate
  fix; rule 5's loop applies. A NON-blocking REAL finding the leader declines to
  fix instead carries a recorded residual row — never a silent drop.
- **REACHABLE-UNOBSERVED** — the mechanism exists but there is no occurrence
  evidence. → REPRODUCE FIRST (a TC or live probe) before any fix; a
  vendor-output trigger needs REAL vendor output (§ Loop exit, occurrence gate).
  A failed repro
  does not prove impossibility: the item never reclassifies to SPECULATIVE — it
  becomes a DISCLOSED residual routed to the owner's merge decision.
- **SPECULATIVE** — cannot occur in this deployment (other platform, inside the
  trust boundary, vendor-guaranteed, absent threat model; for a TRIAD host's own
  code, a trigger R-THREAT rules out — deliberate tampering with the host's own
  files or a second operation inside one working folder; a stop at any point (a
  token or usage limit included) and an odd layout of files the leader creates
  by hand are not among them: they are ordinary failures, in scope at full
  severity; a vendor shape no run has shown is a recorded limit
  (HARDENING-SUGGESTION)). → **no code.**
  Record it with the classification rationale;
  the next round's current residual carries the disclosure, and a re-raise
  without new evidence is not progress (R-STOP).

When the reviewed target is a skill or a prompt, R-STOP's skills-and-prompts
paragraph governs what counts as evidence (structural checks and static
contradictions versus claims about model behaviour; no arranged fresh-context
experiment, and a leader's reenactment is not evidence) — spec
`reference/review-rules.md` § R-STOP.

The burden of proof is on whoever proposes the fix, leader included. A
classification dispute where both legs survive the probe is CONFLICTED → owner
call.

## Scope-expansion gate

Even for a REAL finding, a fix is DESIGN EXPANSION when it:

1. introduces a new guard/fallback/retry/lock/validation LAYER — a new runtime
   responsibility or control path, rather than a local conditional inside an
   existing function; or
2. adds a new file, module, dependency, or config/env surface; or
3. spills beyond the finding's file — mechanical caller/import updates the same
   fix requires are exempt.

These three are what the leader WATCHES for; an item stops for the owner only
when it changes a contract, adds a public definition or substantively changes
the gated design (R-STOP). Otherwise the fix continues and its expansion is
disclosed with it. Line growth or a file count alone is never the trigger: a fix of a confirmed
correctness or security defect is never downgraded because it is large — record
its size (added plus removed production lines for the whole logical fix) with
the fix (R-SMELL).

**Plan-gate fold of a NEW semantic contract.**
A fold that introduces a new semantic contract — a runtime-evidence rule, a
resolver, a predicate — hands every subsequent round a fresh layer of REAL
material to review, all on the newly folded text. The plan under review
therefore folds the CONSTRAINTS the contract must satisfy and DELEGATES
the row-level DESIGN to the unit that owns the contract and carries its own
gate. A gate that keeps producing real findings on material the current fold
just created is a scope signal, not a convergence failure.

A fix that changes a contract, adds a public definition or substantively changes
the gated design STOPS for an explicit owner OK before implementing, even
mid-round (R-STOP). This bounds the autonomous fix loop rather than suspending
it: leader autonomy covers REAL findings with the smallest adequate fix.

## Loop exit

**Countable stop rules (rule 5 / 12 / 14, owner directive):**

| rule | trigger | what happens |
|---|---|---|
| design or plan change | a finding's fix requires changing the gated plan or design — a new contract, a restructured order of operations, a new public def/class not in the gated design | OWNER discussion BEFORE any design work; no round count is a stop by itself — non-contradicting in-design bug fixes continue at any round |
| convergence | `collect` returned `AGREED` on the current basis and no fix follows | the gate is done. A fix after it is a new basis and owes its own FULL round (R-REREVIEW — there is no focused re-confirm, SKILL rule 5) |
| no progress | no new evidence addresses an item, or no remaining item has a concrete path to new verification or to resolving a necessary fact | stop repeating that item; stop the automatic rounds when nothing has a path; record dissent, uncertainty and the stop reason (R-STOP). The round stays non-agreed |
| occurrence gate | a REACHABLE-UNOBSERVED item has no repro from REAL vendor output (capture / run-log / audit row) | DISCLOSED residual, no code — a fixture-only repro does not promote it |
| docs never gate | a finding is text-only on NARRATIVE documentation | batched into one post-merge doc-resync commit; never a round trigger. A rule, schema, prompt clause or policy file is review scope even as text (R-PREPARE, SKILL rule 5) |
| scope freeze | a finding outside the agreed scope (a neighbouring design, a hypothetical input shape) | new slice, not this gate. A verified defect INSIDE the agreed scope stays in scope at any round, whether or not it cites a changed hunk (R-REREVIEW, R-STOP); a reopened closed claim needs a new counterexample, a relevant change or a demonstrated error in its refutation |
| two-family floor | single-family REACHABLE item, no measured probe — **roster entries of the SAME family (two claude arms, two codex entries, several Google entries) count as ONE family**: their agreement never clears this floor | residual. This floor gates whether a REACHABLE-UNOBSERVED item earns code; it never decides agreement (R-AGREE) |

Distinct from the CONVERGING round class: once every REACHABLE-UNOBSERVED item
has had its repro run, a round whose remaining findings are all SPECULATIVE or
repro-failed is TERMINAL. Record each as a DISCLOSED residual in the residual
table and route the merge decision to the owner through the conflict channel when
any of those rows is BLOCKING. Dispatch no further round for them. The round is
agreed only if `collect` returned `AGREED`; otherwise it stays non-agreed, and
an owner decision to merge is recorded as an exception (§ Dispositions).

A reviewer UNKNOWN-CONTEXT finding is triaged by first OBTAINING the missing
deployment fact (a probe or a document); if the fact is unavailable or
inconclusive, the finding becomes a DISCLOSED residual recording the fact gap and
routes to the owner — it is never guessed into a class.

**Self-recording review targets do not converge to literal SAFE.** A target
document that records its own review — a plan carrying its fold history,
round tables, or gate-cost counters — regenerates the non-blocking
prose-tail finding class at review time by construction: every fold ADDS
text, each fix sentence becomes next-round review surface, and
self-referential records (a round counter, a cost tally) lag one round no
matter how carefully they are folded. Recognize the pattern once (a) two or
more consecutive rounds confirm every prior fold faithful AND (b) each
round's findings are exclusively non-blocking prose tails on the recording
artifact itself. The structural remedy is then a class-level MECHANICAL
census obligation at IMPLEMENTATION time — a deterministic script over the
falsifiable prose classes, its hit-list committed as evidence, verified by
the merge-stage gate against the actual diff — plus, when the non-blocking
tail keeps the round non-agreed, a recorded stop reason (R-STOP) or an owner
exception (§ Dispositions), never agreement; never more plan-time enumeration
rounds
(precedent: an 11-round plan gate whose final rounds' findings were half the
leader's own fold-edit slips).

## Fourth-leg comparison record

A second entry of a family already on the roster is run to be COMPARED with the
SAME-FAMILY baseline entry — an opt-in comparison entry against the ONE codex
entry, a claude arm against the shipped claude leg — so each round gets
one deterministic record per compared pair (co-equal same-family entries with no
baseline, such as the named Google entries, need none) —
leader-filled, in the gate ledger (a campaign roll-up
`docs/reviews/<date>-x-leg-<name>-campaign.md` only when the leader declares a
campaign):

| Field | What it holds |
|---|---|
| `x_findings` | count of findings the comparison entry returned |
| `baseline_findings` | count from the SAME-family standing leg (gating or advisory) it is compared against — name that leg |
| `overlap` | findings both raised: same file + line ±3, OR the same defect by leader judgement — MARK which of the two rules each overlap used |
| `x_unique_real` | comparison-only findings that triaged REAL |
| `x_unique_refuted` | comparison-only findings a recorded probe refuted |
| `x_out_of_scope` | comparison-only findings outside the packet's scope or ruled out by the deployment context |
| `verdict_agreement` | does the comparison entry's verdict token match the baseline leg's? |
| `wall_s_x` / `wall_s_baseline` | wall-clock seconds per leg |

Standing rules (SKILL.md rule 1): EVERY enabled entry counts. A finding
from a comparison arm enters the residual table like any other, in its own
raising-leg cell, and takes the SAME triage (REAL / REACHABLE-UNOBSERVED /
SPECULATIVE). `acceptance` is operator DATA and grants NO exemption: a
Critical / must-fix raised ONLY by an `informational` entry blocks exactly like
a `required` entry's, and family coverage is descriptive, never a threshold
(R-AGREE). An entry that failed,
timed out, or returned an unusable verdict is `INCOMPLETE` — recorded in the
same row set, diagnosed, and retried as attempt K+1 (SKILL rule 13), or taken
to a NEW round where `retry` refuses (§ Collect outcomes); it is
never silently dropped and never counted as agreement. A disagreement
between two entries of the SAME FAMILY is recorded in the comparison record;
when two of their findings both survive verification and cannot coexist, that
decision is CONFLICTED and goes to the owner like any other (R-STOP —
irrespective of family). Their agreement is not the independent-legs
CONVERGENCE floor.

## Residual table

The gate's ledger record — kept OUTSIDE every packet dir while the gate runs
(the session scratchpad, beside the brief drafts: a file written into a packet
dir after its capture is one `verify` refuses as uncovered, and a refused
packet dir is left exactly as it is), one row per finding: finding / raising leg / round / class / leg severity +
verdict / probe, repro or counterevidence / rationale / disposition
(§ Dispositions). A fix that is applied stays open until a later round's
`collect` covers its bytes — never closed on a leader assertion. An owner
exception is a separate record naming the round it excepts. The ledger keeps
every row: it is audit history.

**The next round's current residual (`--prior-residual`, R-REREVIEW,
R-CONTEXT)** is NOT this table. The leader REBUILDS one condensed text per new
round: the current findings and their dispositions, the prior excerpts the
next judgment needs, the counterevidence and its limits, verification results,
what changed, and the remaining uncertainties — never earlier residuals,
prompts or transcripts appended, and never only a path to an old round (a
historical path is provenance, not evidence). Preserve unresolved risks and
relevant counterevidence when condensing. `prepare` fences it once, as DATA,
inside `brief.md`, which every leg reads; it does not narrow the full-scope
review. No residual = omit `--prior-residual` (an empty or whitespace-only file
is refused). A residual line equal to one of the round's fence lines is
refused. For an owner-call section use the same data fence: finding, evidence
and rationale cells carry vendor-authored text, a declared untrusted input,
which must never sit among the leader-authored questions.

At gate end, before the last `close`, copy the residual table WITH dispositions
to a durable record: the COMPLETE table (every row and disposition, not a summary) at
`docs/reviews/<UTC-date>-<slug>-residuals.md`, with the commit body carrying a
pointer to it plus the load-bearing rows. Packet close deletes the dir.

## Consolidating validated LegVerdict objects (Read tool)

An ADMITTED verdict is a validated JSON object, not free prose. Mapping its
`findings[]` into the residual table (above) is mechanical — open the file
with the Read tool and take the fields by name, never by re-reading the leg's
prose. No Bash call (no grep, sed or JSON query tool): the files are small,
and the Read tool needs no permission grant.

The authoritative list of entries is `.roster-r<N>.json` — open it with Read
and take the entries in `entries` whose `enabled` is true and whose
`skipped_reason` is null — and each entry's object is
`results-r<N>/<name>/attempt-<K>/verdict.json` (a wrapper route) or
`…/admitted.json` (the claude route — the `--admitted-out` product). Open that
file with Read and take `verdict` and each `findings[]` item's fields by name.
Never read the raw marker-bearing `raw.json` as the verdict: it is the leg's
unadmitted reply, not the admitted object. `collect-r<N>.json` already carries
the folded per-entry result, so read the entry list from the RECORD rather
than from memory or a glob. The round's OUTCOME is the exit code and stdout of
the LATEST `collect`, never this file: a refused `collect` (exit 2 — an
integrity or basis refusal) leaves the file untouched, so it is then the
EARLIER collection's record (it may still say `AGREED`), not the current
outcome. The finding's location field is `path`.

Each row mapped from an admitted object is a residual-table row PREFILLED from
the leg's own structured fields (finding location, raising leg, round, leg
severity + verdict, one-sentence summary as the rationale seed, disposition
`open`); the leader still fills in the two fields the schema cannot supply —
the triage class (REAL / REACHABLE-UNOBSERVED / SPECULATIVE, rule 4's
leader-owned judgment, never mechanical) and the probe/repro evidence once
obtained. The `path`/`line` fields also make the cite-verification step
(Consolidation duty 1 — "read the cited lines and reproduce the claim")
mechanical to START: Read the file with an offset / limit at that line to open
exactly the cited line instead of the leader hunting for it in prose, though
confirming the claim itself still requires reading the surrounding code, and
`references/leg-contracts.md` § agy leg still requires verifying an agy cite
before it enters the table (its cites were fabricated in most traced runs even
inside a schema-shaped reply).

**Fallback (stated, not hypothetical).** An entry with no admitted object —
its reply failed admission (not sealed — `references/leg-contracts.md`
§ Attempt seal), or it never answered — keeps the round `INCOMPLETE`
(§ Collect outcomes); its prose findings may still be read by hand and triaged
as leader-probed evidence (direction asymmetry: findings only add work) —
except an agy entry the read-audit gate or the hook load check refused: its
answer is UNVERIFIED and is not read this way (`references/leg-contracts.md`
§ agy read-audit gate). One entry's admitted object and another entry's prose
can both feed the SAME residual table in the SAME round.
