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
| Consolidating validated LegVerdict objects (jq) | a leg was dispatched with `--pydantic verdict_schema:LegVerdict` (or its claude-leg equivalent) and its findings need mapping into the residual table |
| Reviewer-side instruction | reading the LEGACY v1 leg-prompt text (a v2 round renders the shared clauses) |
| Fourth-leg comparison record | two entries of ONE family ran this round and you are recording the comparison (or reading a LEGACY v1 X-leg row) |

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
| 5 | `INCOMPLETE` | some enabled entry is missing (a SKIPPED entry included), unreadable, or failed admission. NOT agreement and never a silent pass. Diagnose why that entry failed to RUN, then `retry <packet-dir> r<N> <name> --diagnosis "<why>"`; a valid NEGATIVE verdict is completed work and is never a retry case. `retry` refuses — and the remedy is a NEW round — for a SKIPPED entry (`it never ran, so there is no attempt to retry`) and for a saved `raw.json` beside an `admitted.json` that is not a readable file (`… is not a readable file …, so that reply can never be admitted into this attempt — prepare a new round`). |
| 2 | refusal | no or unreadable round record, a round record whose SHAPE is unwalkable (below), a record whose selection or configuration differs from the round's bound basis (`delivery-r<N>.md`), an unknown or non-dispatched entry name, an empty `--diagnosis`, or a retry on a completed review. **Also the INTEGRITY refusal**: before `collect` reports `AGREED` it runs the round integrity check (`review_scratch.py verify`) itself (R-AGREE: no integrity failure), so a skipped or too-early `verify` never yields `AGREED`; when that check fails, `collect` refuses with verify's own reason, leaves the previous collection record untouched and names the remedy by cause: a changed tree or evidence, or a packet file the host did not write → a NEW round; the host's own `.tmp-<pid>-…` staging leftover → a NEW round (the host's deletion command removes a whole packet dir only); a second round tree you made → a NEW round in a new packet dir (`open` with a new slug); a later round prepared over this one → it is superseded, collect that round; a host fault (git unavailable, the verification record unwritable, a check that could not be launched or ended with any exit but its own refusal's 2 — a traceback, a signal) → exit 64, repair the host and collect again. **Also the SPEC-BASIS refusal**: the round record freezes `contract_digest` (sha256 of the canonical ADMISSION schema `verdict_v2` judges every reply against) beside `projection_digest`, and `collect` / `retry` refuse here — `the ADMISSION contract basis changed since this round was prepared (frozen … vs … ) — … prepare a new round (R-REREVIEW)` — on a MISMATCH or on ABSENCE of the frozen value. The contract is the one basis no leg artifact evidences: an admitted `verdict.json` carries no trace of the schema that let it through. A CHANGED basis is a new ROUND, never a re-collection. |
| 64 | HOST FAULT | **THIS HOST cannot admit any reply (or could not RUN the round's evidence tools), so nothing about ANY leg is known.** `verdict_v2` reserves exit 64 for the admission it could not RUN at all — `jsonschema` absent, the vendored contract unreadable / invalid UTF-8 / non-JSON / nested past the interpreter's limit / not Draft 2020-12 (EVERY load-failure class takes this exit). `collect` (and `retry`) STOP at the first such admission with `collect_v2: HOST FAULT: this host cannot admit any reply: <reason> (reached while admitting <path>)` and write NO per-entry state — recording it as the ENTRY's `invalid` would fold the round to `INCOMPLETE` and send the leader to re-dispatch PAID legs over a broken install. **The agy entry's two EVIDENCE TOOLS take the same exit**: `read_audit_gate.sh` and `agy_hook.py check` both reserve rc 64 for "this invocation could not RUN at all" — a required file the round named is gone, a re-pinned worktree, an absent `hook_log`, an unusable argv — and that is a `_HostFault` too, never that leg's `invalid`. **ORDER against the exit-2 basis refusal**: the HOST question comes first — a contract this host cannot even LOAD is 64, and only a contract that loads and DIFFERS is the exit-2 "basis changed — new round". Repair the host and collect AGAIN — the legs' own outputs are untouched and nothing needs re-dispatching. |

**The EXPECTED binding is DERIVED, never read back** (`collect_v2._evaluate`).
The six values an attempt's `binding.json` is checked against come from
OUTSIDE that attempt directory: `review_id` and `content_digest` from the
ROUND RECORD, `family` / `leg_name` / `route` from the round's FROZEN ROSTER
ENTRY, and `attempt` from the DIRECTORY NAME the scan parsed. `binding.json`
must EQUAL that derivation before admission runs at all — a binding and a
result that only validate EACH OTHER would let a pair copied out of one
entry's attempt be credited to another entry. A disagreeing binding is
`invalid` with the offending FIELD named — not a leg that answered wrong, an
attempt directory that does not belong to this entry.

**THE ROUND RECORD DECIDES WHICH ATTEMPT IS EVALUATED** (`collect_v2._evaluate`).
Allocation is the RECORD's act: `prepare` writes attempt 1 and `retry` bumps
the entry (allocating or ADOPTING) before it returns, so an on-disk attempt
ABOVE the record's is one this round never dispatched — restored from a
backup or planted by hand, and able, with a binding that satisfies the
derivation above and a schema-valid SAFE verdict, to supersede the recorded
attempt's BLOCKING verdict. It is refused BY NAME for THAT ENTRY — `<dir> is
an attempt this round never allocated: the round record names attempt <K> for
this entry (evaluated: …). … inspect it, then retry the entry (it adopts this
entry's own orphan) or prepare a new round` when `retry` would adopt it; when
`retry` would refuse first (its own pre-adoption checks, the adoption's
checks on the orphan's files included — one predicate for both), the line
is retry's own refusal, its cause and remedy (the `admit:` line, or a new
round), followed by `(also: <dir> is an attempt this round never allocated;
the recorded attempt <K> is <state>)` — the recorded attempt's own remedy is
not printed — nothing is deleted, every other entry still collects and
the round lands on INCOMPLETE. That refusal fires only when the RECORDED
attempt did not itself return a valid verdict: a completed review is never
vetoed by an unallocated directory, which is then simply not read. Exactly
`attempt-<record.attempt>/` is evaluated, so a RECORDED attempt the tree does
not hold is that entry's `invalid` (`… attempt-<K> is not on disk …`), and
`retry` refuses it BEFORE allocating anything (`… — prepare a new
round`). Adoption is reachable only for the one-step orphan,
where the recorded attempt IS on disk; `retry`'s orphan / wide-gap arms read
the on-disk high-water mark from their own scan.

**THE ROUND RECORD'S SHAPE IS CHECKED BEFORE ANYTHING WALKS IT**
(`collect_v2._check_record_shape`). Unchecked, `"entries": null` or
`"entries": [null]` would meet the iteration as a traceback, a record missing
`results_dir` would crash inside `_evaluate`, and one missing `review_id` /
`content_digest` / `worktree` would degrade SILENTLY (a derived binding of
None mismatches every entry, so a tampered record would read as "every leg
answered wrong"). The check is a SHAPE check, not a contract: only the members
this file dereferences are named, and each refusal (exit 2) NAMES THE FIELD —
`entries` as a list, each `entries[i]` an object with a usable `name` and a
`leg` object and an `attempt` that is a positive int when present, then
`review_id` / `content_digest` / `worktree` / `results_dir` as non-empty
strings. Members with their own dedicated refusal downstream —
`projection_digest`, `contract_digest`, `prompt_spec_dir`, `hook_log` — are
only TYPE-checked when present, so a record that OMITS one still reaches the
refusal that explains what it is for.

**ONE derivation serves BOTH readers** (`collect_v2._expected_binding`).
`collect`'s admission and `retry`'s orphan ADOPTION call the same helper and
compare ALL SIX values, so the two cannot drift. The printed `--expected-*`
flags of a wrapper entry's `admit:` line come from that DERIVED dict too, never
read back out of the attempt's own `binding.json`: the values the operator runs
are the round record, the frozen roster entry and the directory name, exactly
as admission's are. The native `--admit` line types none (R-BIND): it takes the
six from the attempt's `binding.json`, a typed flag that disagrees is exit 64
and seals nothing, and `collect` still re-judges the admitted result against
the derived dict.
Every interpolated value is `shlex.quote`d
(`review_scratch._v2_expected_flags`) — the flags land in a command line the
operator copies into a shell, where an unquoted space or metacharacter would
split an argument, or run. Quoting is the second half of the
derive-never-read-back rule, not a substitute for it.

**A non-object `binding.json` invalidates ONE entry.** `null` and `[]` parse
cleanly but are not the object `binding.get(...)` expects; unscoped, the
resulting error would abort the WHOLE collection and throw away every other
entry's verdict. That entry is `invalid` (reason: `binding record is not an
object (<type>): <path>`), every other entry still collects, and adoption
refuses the same shape BY NAME for both `binding.json` and `dispatch.json`.

**An unusable attempt DIRECTORY invalidates ONLY its own entry.** An
`attempt-<non-decimal>` name is REFUSED rather than skipped (skipping would
make the collector read a LOWER attempt than the tree holds), and the refusal
is scoped: the entry goes `invalid` with the directory named, every OTHER
entry still collects, and the round lands on `INCOMPLETE`. A `retry` of THAT
entry runs the same scan itself and refuses with the same reason.

**ONE NUMBER, ONE SPELLING — and a real DIRECTORY.** `int()` is not injective
over the names `isdecimal()` admits, so `attempt-01`, `attempt-001` and every
non-ASCII decimal spelling map to the same number as the canonical
`attempt-1`: two directories would claim one allocation, FILESYSTEM ORDER
would decide which one's verdict is credited, and a copy dropped in under a
second spelling would admit cleanly, because the derived binding names the
NUMBER, which both spellings satisfy. Only `attempt-<N>` in the canonical
spelling the writer produces (ASCII digits, no leading zero) is usable; any
other is refused by name. A SYMLINKED `attempt-K`, or one that is not a
directory, is refused too — skipping it would read a LOWER attempt than the
tree holds, the same failure the non-decimal refusal exists to prevent,
reached through a link instead of a spelling. A name this helper owns is a
real directory or it is refused; nothing is followed and nothing is deleted.
All three refusals are per-ENTRY inside `collect`: that entry goes `invalid`
with the directory named, every other entry still collects, the round lands
on `INCOMPLETE`, and a `retry` of that entry refuses with the same sentence.

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
record still names attempt K, so the allocated attempt is ADOPTED on the next
`retry` rather than re-allocated. The ADOPTION path converts the same
`OSError` the same way.

**`retry` ADOPTS an orphan `attempt-K+1/`, and refuses a foreign one BY
NAME.** The other side of allocate-then-diagnose is an allocation that
SUCCEEDED while the diagnosis or the record write failed: `attempt-K+1/` is
on disk and the round record still says K. Rendering K+2 over it would write
a fabricated diagnosis into an attempt nobody dispatched and let the
numbering run away from the record. So when the tree's highest attempt is
exactly `record_attempt + 1`, `retry` ADOPTS that directory: adoption is
CONDITIONAL on the orphan's own `binding.json` binding THIS entry at THIS
attempt — ALL SIX derived values, through the one `_expected_binding`
derivation admission uses (above) — NOTHING is re-rendered (the frozen
records are the basis, exactly as R-RETRY requires), the diagnosis is written
into attempt K, the record is bumped and the orphan's own `dispatch.json` is
re-printed as the dispatch line. Any other directory at that path — records
unreadable, a binding that names something else, or an allocation that never
finished (a stop part-way through `v2_write_attempt`) — is REFUSED by name and
NOT deleted: the packet dir is helper-owned, so the tool never removes a
directory it did not write, and nothing under `results-r<N>/` is removed by
hand: prepare a new round.

More conditions gate the adoption, each refusing BY NAME and deleting
nothing:

- **The allocation must have FINISHED.** `binding.json`, `prompt.txt` and
  `dispatch.json` are written in that order and the producer schema
  projection LAST, so an allocation stopped before `dispatch.json` is
  refused as unreadable records, and one stopped after it can lack only
  `schema.projected.json` — adopting it would print an argv whose
  `--output-schema-file` points at a file nobody wrote. Adoption requires EVERY file the writer
  produces for THAT ROUTE (the projection exactly when this attempt's
  `dispatch.json` names one).
- **`dispatch.json` is TYPE-CHECKED on every member the print reads.** The
  adopted record is what the operator actually runs, and a non-emptiness
  test alone would pass `argv: [1]` and let `shlex.quote` raise mid-print.
  Every member `v2_print_dispatch` / `_v2_expected_flags` read is
  TYPE-checked before anything is written: the `kind` (`native` /
  `wrapper`), the identity for that kind (`native.subagent_type` a non-empty
  string — a null one would be spawned under the layout default, the GATING
  reviewer — and `argv` a non-empty list OF STRINGS), `stdout_path` /
  `stderr_path`, `env` as a mapping of strings to strings,
  `read_audit_path` — **the KEY is required on EVERY wrapper route, `null` on
  the routes that take none**: the gate and the hook check are printed from
  it, so the value is a non-empty string on the agy route and `null`
  elsewhere, and the print reads it with `.get()` (both halves, so neither
  side alone decides) — and `schema_file` when the record names one. Each
  unusable member is refused BY NAME; the value itself is vendor- or
  operator-supplied text and is never echoed.
- **The adopted record is COMPARED against a fresh RE-RENDER, not trusted.**
  Everything above proves the orphan's binding names THIS entry at THIS
  attempt and that its `dispatch.json` is well TYPED — but its argv, env and
  paths are printed for the operator to RUN, so a record planted in the
  orphan directory could substitute the PROGRAM under this entry's name.
  `retry` re-renders the K+1 dispatch from the round's OWN FROZEN roster
  entry and refuses adoption when ANY compared invocation member differs
  (`… is not the invocation this round renders for '<name>' attempt K+1
  (differs: …)`). On equality the ON-DISK bytes are adopted and nothing is
  re-rendered INTO the attempt, exactly as R-RETRY requires — the re-render
  is a comparison basis, never a write.
  **`kind` AND `native` ARE PART OF THE INVOCATION.** They decide WHO RUNS on
  the native route — a planted record could otherwise substitute the
  reviewer (`native.subagent_type`) or flip a wrapper record to a native
  spawn while every wrapper member still matched, since a native record
  carries `argv: null` / `env: {}`. The comparison set is `kind`, the WHOLE
  `native` block, and six wrapper members — `argv`, `env`, `stdout_path`,
  `stderr_path`, `read_audit_path`, `schema_file`
  (`collect_v2._ADOPT_COMPARED_FIELDS`) — comparing the whole block also
  states the wrapper case, where the writer emits `native: null` so any
  block at all differs.
- **The two files the adopted invocation FEEDS THE VENDOR are PROVEN, not
  merely present.** A planted prompt could re-instruct the leg under this
  entry's name and a planted projection could change the schema it is
  handed, both while every binding field and every invocation member still
  match. Before the attempt is adopted: `prompt.txt` is compared against a
  PURE re-render — through the one context construction `prepare` itself
  uses — whose own clause manifest is checked against the round's FROZEN
  `prompt_manifests[<name>]` FIRST (a spec re-vendored since prepare is a NEW
  ROUND, never a silently accepted re-render), and then BYTE-for-byte;
  `schema.projected.json` is digested and compared against the frozen
  `projection_digest`. The CLAUSE DIRECTORY is the other half of that basis,
  so adoption requires AND compares `prompt_spec_dir` exactly as the normal
  `retry` does — digests alone do not say WHERE the clause bytes came from.
  A record carrying no frozen manifest, no frozen `prompt_spec_dir` or no
  frozen digest cannot PROVE the basis and is refused rather than guessed at
  ("prepare a new round"); absence and mismatch refuse the same way. The two
  byte reads go through the helper-owned hardened reader
  `collect_v2._read_regular_file`, never `Path.read_bytes()`, which FOLLOWS a
  symlink: a link planted at `prompt.txt` or `schema.projected.json` whose
  target's bytes happen to match would otherwise pass the comparison and then
  feed the vendor whatever it resolves to. Same shape as
  `verdict_v2._read_regular_file_no_symlink` / `roster_v2`: `lstat` decides
  every non-regular type BEFORE the open (a FIFO would otherwise block
  forever), then `O_NOFOLLOW|O_NONBLOCK` and an `fstat` S_ISREG re-check on
  the descriptor. An unreadable CLAUSE file is a one-line refusal at BOTH
  layers: `prompts_v2._read_spec_text` turns `OSError` /
  `UnicodeDecodeError` from the vendored clause open into `PromptSpecError`
  naming the file, and adoption's own except tuple carries `OSError` for any
  other one the pure render can reach. Nothing is re-rendered INTO the
  attempt: the re-render is discarded the moment the comparison is made.
- **The ROUND RECORD is the LAST write.** Adoption's order is validate
  EVERYTHING → write the diagnosis → print the dispatch block → bump
  `.roster-r<N>.json`. A record bumped before a refused print would leave
  the next `retry` fabricating a diagnosis into an attempt this tool never
  dispatched — the runaway adoption exists to stop. A refusal always leaves
  the record naming the attempt the round actually dispatched.
- **A gap of MORE THAN ONE is refused, naming the state.** Only the
  one-step orphan (record K, on-disk K+1) is adopted. With record and tree
  further apart there is no attempt the tool can honestly call "the one that
  failed", so it refuses with both numbers and the gap size rather than
  writing a diagnosis into an attempt this round never dispatched.
- **A NON-BLANK diagnosis is retained, an EMPTY one is replaced, a
  non-regular one is refused.** An EMPTY file is what an interrupted write
  leaves behind — the very failure this adoption path exists for — so
  retaining it would discard the text the operator typed on THIS invocation
  and leave attempt K with no record of why it failed. Three outcomes:
  a REGULAR non-blank file is retained under the DISTINCT line `existing
  diagnosis retained at <path>; the typed text was NOT stored` (the earlier
  retry's record stands and the operator has to be told the typed text went
  nowhere); a REGULAR but blank file is REPLACED by the typed text, and the
  print says so (`the EMPTY diagnosis file at <path> was replaced …`);
  anything that is not a regular file — a SYMLINK above all — is refused
  outright, because evidence about attempt K lives in attempt K's own
  directory as a plain file, never behind a link. **Blankness is decided on
  the WHOLE file's content**: the diagnosis is read through the bounded,
  symlink-refusing reader (`collect_v2._read_regular_file`), so a
  whitespace-only file of any size under the 64 MiB evidence cap is blank and
  replaced, and the retained line says how it was judged (`existing diagnosis
  retained at <path> (blank/non-blank decided on its content); the typed text
  was NOT stored …`). A file over the cap is REFUSED, naming it. An `OSError`
  on the diagnosis read, the
  diagnosis write or the record write is a ONE-LINE refusal, never a
  traceback. **Asymmetry, disclosed**: this is the ADOPTION path only. The
  ordinary (non-adopt) `retry` REFUSES outright on any existing
  `retry-diagnosis.txt`, empty included — `attempt K has already been
  diagnosed and retried` — which is a refusal the operator sees, not a
  silent discard.

An `attempt-<suffix>` whose suffix is not a DECIMAL number is likewise
refused with one line rather than skipped or crashed — `str.isdigit()` is
true for characters `int()` refuses, and silently ignoring such a name would
make the collector read a LOWER attempt than the tree holds; inside `collect`
that refusal is scoped to the offending ENTRY (above). The same one-line,
per-entry refusal covers a NON-CANONICAL decimal spelling (`attempt-01`,
non-ASCII digits) and an `attempt-*` entry that is a symlink or not a
directory at all.

**BOTH records this helper writes go through ONE lstat-refusing writer**
(`collect_v2._write_json`). `collect-r<N>.json` and the round record
(`.roster-r<N>.json`) share one writer: the target is `lstat`ed first and a
NON-REGULAR path is refused BY NAME (`… is not a regular file (a symlink or
another special path)` — inspect it, then prepare the round in a NEW packet dir,
since a later capture in this one refuses it too), then the bytes go to a pid-suffixed temp file and `os.replace`. A
plain `write_text` would FOLLOW a symlink planted at the target and put the
round's collected state wherever it pointed. The replace idiom itself never
writes THROUGH a link; the `lstat` is what turns a planted path into a NAMED
refusal instead of a silently replaced one, and it keeps the rule identical
for both records. **The TEMP file is exclusive-created too, and unlinked when
the staging does not consume it**: the temp is opened
`O_CREAT|O_EXCL|O_NOFOLLOW` (the rule both sibling writers —
`verdict_v2._write_admitted_out` and `review_scratch._write_new_file` —
apply), so a symlink planted at the predictable `.tmp-<pid>-<name>` is never
written through; a pre-existing name of any kind is refused BY NAME, and a
`finally` removes a temp that was never replaced, so a refused write leaves
no `.tmp-…` residue for `verify` to report as an uncovered packet file.

**Every record load tolerates a RECURSIVE document.** `json.loads` raises
more than `ValueError`: a document nested past the interpreter's recursion
limit raises `RecursionError`, which is NOT a `ValueError`. Every record load
in `collect_v2` (and `review_scratch`'s round-record read) catches the same
tuple — `(OSError, ValueError, RecursionError, UnicodeDecodeError)` — and
reports the offending file by name; `roster_v2._read_json` catches
`RecursionError` beside `ValueError` too, so a roster or leg-config document
nested past the limit is a one-line refusal at exit 2 like every other
loader failure.

**Subprocess output is decoded UTF-8, and the collector's own streams never
raise.** `collect_v2._run` — the helper that shells out to the agy
read-audit gate and the hook check — pins `encoding="utf-8",
errors="replace"`, the same pin the wrappers apply to every vendor pipe:
`text=True` alone decodes with `locale.getpreferredencoding()`, and under an
ASCII locale the gate's own em-dash diagnostics would raise
`UnicodeDecodeError` where the agy entry owes a one-line reason. On the
OUTPUT side, every CFR lib's `main()` reconfigures its DIAGNOSTIC stream with
`errors="backslashreplace"`, so a refusal sentence carrying a path or a
vendor token the locale codec cannot encode is printed escaped instead of
raising `UnicodeEncodeError` — a host under a non-UTF-8 locale cannot turn a
one-line refusal into a traceback.

**…but `stdout` is the PAYLOAD stream and is NEVER re-encoded.**
`_relax_std_stream_errors` is **stderr-only**: relaxing `stdout` would be
right for operator prose and wrong for the two things on this stream that a
machine or an operator CONSUMES — `prompts_v2`'s rendered prompt / manifest
/ investigation clause, and `review_scratch`'s six dispatch lines.
`backslashreplace` would silently REWRITE them (a rendered prompt's
em-dashes; a dispatch line's non-ASCII path token printed as `caf\xe9` under
`LC_ALL=C`, i.e. a path that does not exist, handed to an operator with no
warning). Both printers encode ONCE as UTF-8 and write to `sys.stdout.buffer`
(`_emit_payload`), so the locale gets no vote; every token in a dispatch line
is already `shlex.quote`d by the caller. A text this host cannot represent as
UTF-8 — a path decoded with `surrogateescape` — is **REFUSED BY NAME** rather
than escaped (`a dispatch line carries a path this host cannot represent as
UTF-8 … rename the offending path or prepare this round under a UTF-8
locale`), because a mangled path in a command the operator RUNS is the
failure the emitter exists to stop. **The no-`.buffer` FALLBACK takes the
same refusal.** Both emitters fall back to `sys.stdout.write(text)` when
`sys.stdout` exposes no `.buffer` — an in-process harness, or a stream
replaced under a non-UTF-8 locale. The payload is never rewritten to get past
it (`backslashreplace` here would silently change the clause bytes the round
record's manifest digests, or mangle a path in a command the operator RUNS),
so the fallback raises the SAME refusal the encode step above uses:
`prompts_v2` a `PromptSpecError` ("render to a binary stream or under a UTF-8
locale"), `review_scratch` its one-line `review_scratch:` failure.
Wrapper-side counterpart: the plugin `README.md` § Payload vs
diagnostic streams.

**`retry` compares the PROMPT BASIS against the round's frozen manifest.**
R-RETRY re-renders from the round's own frozen roster entry, so the leg
CONFIG cannot move — but the CLAUSES are re-read from the live
`spec/prompts/*.md` on every render, and a spec re-vendored between `prepare`
and `retry` would silently change the instructions the leg receives while the
round record still claimed an unchanged basis. `retry` compares the rendered
clause DIGESTS plus the clause DIRECTORY with the `prompt_manifests` frozen
at prepare, BEFORE `v2_write_attempt`, so a refusal leaves nothing behind: a
mismatch refuses with "the prompt basis changed since this round was
prepared … prepare a new round" (R-REREVIEW: every entry reviews the new
basis again). A changed basis is a NEW ROUND, never a quiet re-render. A
MISSING frozen manifest for that entry **or** a missing frozen
`prompt_spec_dir` refuses the same way: without the directory, a retry could
re-render out of a DIFFERENT clause directory as long as the digests lined
up. Both halves are required, neither is inferred.

**`retry` compares the PRODUCER SCHEMA BASIS too — `projection_digest`.** The
clause check above pins the PROMPT basis, but `roster_v2.render_dispatch`
re-derives `schema.projected.json` from the vendored
`spec/contracts/leg-verdict.schema.json` LIVE on EVERY render, including the
one a `retry` runs for attempt K+1 — so a spec re-vendoring between `prepare`
and `retry` would hand the new attempt a DIFFERENT producer schema while the
round record still claimed an unchanged basis. `prepare … --v2` therefore
freezes `projection_digest` — the sha256 of the PROJECTED schema bytes — in
`.roster-r<N>.json`, and `retry` re-derives and compares it BEFORE
`v2_write_attempt`, so a refusal leaves nothing behind. It is a DIGEST, not
the bytes, because the bytes already live in each attempt's own
`schema.projected.json`. **Absence refuses exactly like a mismatch**: a
record carrying no frozen digest cannot PROVE the basis either (`the round
record carries no frozen producer-schema projection digest … prepare a new
round`) — re-prepare it. A host where the projection cannot be derived at
all (an unreadable or non-conforming vendored contract) refuses with that
reason instead of guessing.

**Minor-only NEGATIVE verdict = `BLOCKED` + a deviation record.** An entry
that returns `MERGE WITH FIXES` or `DO NOT MERGE` with ZERO blocking findings
and ZERO open questions is schema-valid but is NOT agreement (R-AGREE): the
collector keeps its verdict, folds the round to `BLOCKED`, and marks the entry
`deviation` (the verdict token disagrees with its own content). The leader
cannot convert it into SAFE TO MERGE. Record the deviation; the leg prompt
already carries the verdict-selection rule, so the round agrees only when a
later round's entries each return SAFE TO MERGE on their own basis.

On an agy route the CUSTODY check, the per-attempt READ-AUDIT GATE and the
HOOK LOAD CHECK are part of the result, not optional extras: an ungated agy
answer is UNVERIFIED and the collector treats that entry as invalid. CUSTODY
runs first: the attempt's own `stderr.log` must carry the whole line
`read-audit-file: <that absolute path>` (timestamp prefix, percent-escaped
filesystem bytes), or the audit beside it is not this attempt's evidence. The
hook load check is per attempt: hook rows are attributed to the attempt by the
`conversation_id`s its own census rows recorded, and a verdict other than PASS
falls on that leg only (`references/failure-modes.md`).

## A non-SAFE verdict at the merge gate

On a v2 round there is no release carve-out: every verdict other than SAFE TO
MERGE keeps the round non-agreed (`BLOCKED`), whether its findings are refuted,
non-blocking or owner-accepted (R-AGREE). The refutations and dispositions go
into the next round's current residual (§ Residual table); a merge over a
non-agreed round is an owner EXCEPTION (§ Dispositions), never agreement.

**LEGACY v1 rounds only.** A non-SAFE verdict with NO extractable finding is an
INVALID leg — "returned something, but the verdict is unusable". So is **a
reply that does not
VALIDATE — unparseable raw text (truncation included), a schema failure, or
a binding mismatch** (this sentence is the chain's DEFINITIONAL HOME;
the cross-references in
leg-contracts.md and validate_verdict.py point here). The handling chain,
stated once: **ONE TARGETED re-ask that NAMES the defect** (for a syntactic
failure: name it and quote the no-change clause — "re-emit the SAME verdict,
findings and severities as strictly valid JSON — do NOT change the verdict
and do NOT change any severity"; NEVER a verbatim "re-emit unchanged"
request, which anchors the model to its own defective output), **then
terminal INVALID** if the re-ask also fails. **A leader-completed,
leader-repaired, or leader-reconstructed reply is NEVER admissible** —
admission runs through `lib/validate_verdict.py --admit` (raw read, optional
end-marker consumption, one documented html.unescape, no repair path; exit 2
= re-ask, exit 3 = end-marker absent). An INVALID leg is handled identically
to a terminally-missing leg (rule 13): never released, never counted SAFE.
The leg's FINDINGS may still serve as leader-probed evidence (direction
asymmetry: findings only add work).

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
  files or a concurrent operation; a stop at any point (a token or usage limit
  included) and an odd layout of files the leader creates by hand are not among
  them: they are ordinary failures, in scope at full severity). → **no code.**
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
| `x_findings` | count of findings the X leg returned |
| `baseline_findings` | count from the SAME-family standing leg (gating or advisory) it is compared against — name that leg |
| `overlap` | findings both raised: same file + line ±3, OR the same defect by leader judgement — MARK which of the two rules each overlap used |
| `x_unique_real` | X-only findings that triaged REAL |
| `x_unique_refuted` | X-only findings a recorded probe refuted |
| `x_out_of_scope` | X-only findings outside the packet's scope or ruled out by the deployment context |
| `verdict_agreement` | does the X verdict token match the baseline leg's? |
| `wall_s_x` / `wall_s_baseline` | wall-clock seconds per leg |

**Consolidation cross-check — LEGACY v1 rounds only (do this BEFORE filling the
table).** A v2 round has no `.x-legs-r<N>.json`: its entries are named by
`.roster-r<N>.json` and admitted through `verdict_v2.py`. On a v1 round an X leg is
identified by TWO independent markers — its artifact FILE NAMES
(`<name>-r<N>-*`) and the `review_id` suffix its verdict echoes
(`<review-id>.<name>`) — and both must agree with the leg's entry in
`.x-legs-r<N>.json`. A disagreement means a verdict was filed under the wrong
leg; re-admit it with `validate_verdict.py` and the recorded id rather than
reasoning about which leg "probably" produced it.

Standing rules (v2 — SKILL.md rule 1): EVERY enabled entry counts. A finding
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

The `x:<name>` tag belongs to v1 rounds (SKILL.md § Legacy v1 rounds): rows
written by a packet prepared without `--v2` carry it and keep their advisory
reading.

## Residual table

The gate's ledger record — `<packet-dir>/residuals.md` while the round is open,
one row per finding: finding / raising leg / round / class / leg severity +
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

Before `close`-ing the packet dir, copy the residual table WITH dispositions to a
durable record: the COMPLETE table (every row and disposition, not a summary) at
`docs/reviews/<UTC-date>-<slug>-residuals.md`, with the commit body carrying a
pointer to it plus the load-bearing rows. Packet close deletes the dir.

## Consolidating validated LegVerdict objects (jq)

An ADMITTED verdict is a validated JSON object, not free prose. Mapping its
`findings[]` into the residual table (above) is mechanical — read it with
`jq`, never by re-reading the leg's prose.

**v2 rounds.** The authoritative list of entries is `.roster-r<N>.json`
(`.entries[] | select(.enabled and .skipped_reason == null)`), and each
entry's object is `results-r<N>/<name>/attempt-<K>/verdict.json` (a wrapper
route) or `…/admitted.json` (the claude route — the `--admitted-out` product;
the raw marker-bearing `raw.json` is NOT jq-consumable, never point jq at
it). `collect-r<N>.json` already carries the folded per-entry result, so read
the entry list from the RECORD rather than from memory or a glob. The round's
OUTCOME is the exit code and stdout of the LATEST `collect`, never this file:
a refused `collect` (exit 2 — an integrity or basis refusal) leaves the file
untouched, so it is then the EARLIER collection's record (it may still say
`AGREED`), not the current outcome. The
finding's location field is `path` in the v2 schema (`file` in v1).

**v1 rounds** keep the loop below verbatim (`leg-contracts.md` § codex leg /
§ agy leg / § claude fresh-eye leg — `bin/verdict_schema.py`'s
`LegVerdict`):

```bash
# One validated object per leg, at <packet-dir>/<leg>-r<N>-verdict.json
# (codex-r2-verdict.json / agy-r2-verdict.json from the wrappers' stdout;
# claude-r2-verdict.json is PRODUCED BY `validate_verdict.py --admit
# --admitted-out` on successful admission — the raw marker-bearing
# claude-r2.json is NOT jq-consumable; never point jq at it).
# ROUND-SUFFIXED on purpose: a round-free name would be
# censused by the NEXT round's capture and then rewritten by that round's
# consolidation — a guaranteed false "round evidence changed". The suffixed
# names ride verify's `*-verdict.json` leg-output allowlist as post-capture
# arrivals, and each round's file is frozen history thereafter. A
# SAFE-verdict leg with zero findings correctly emits NO rows (`.findings[]`
# on an empty array is a no-op) — that is not a miss, it is the SAFE leg
# contributing nothing to the table.
for leg in codex agy claude; do
  f="$PACKET_DIR/$leg-r$ROUND-verdict.json"   # ROUND=the round number, e.g. 2
  [ -f "$f" ] || { echo "-- $leg: no validated object (fallback below)"; continue; }
  verdict="$(jq -r '.verdict' "$f")"
  jq -r --arg leg "$leg" --arg verdict "$verdict" --arg round "$ROUND" '
    .findings[] |
    "| \(.file):\(.line // "-") | \($leg) | \($round) | <leader-triage-class> | \(.severity) / \($verdict) | <probe-or-repro> | \(.summary) | open |"
  ' "$f"
done

# The FOURTH leg files under its OWN name, so it is never in the loop above.
# `.x-legs-r<N>.json` (written by EVERY prepare, `legs: []` when the round had
# no fourth leg) is the authoritative list of what was rendered this round —
# read the names from it, never from memory. Rows are tagged `x:<name>` so an
# a v1 advisory finding is never counted as a gating leg's.
REC="$PACKET_DIR/.x-legs-r$ROUND.json"
# No record at all = a v1 packet without the record, or a hand-removed one. Say so:
# without this line the loop below emits nothing and reads as "no findings".
[ -f "$REC" ] || echo "MISSING fourth-leg record $REC (a v1 packet without the record, or a hand-removed record — packet-lifecycle § Round integrity)"
[ -f "$REC" ] && for name in $(jq -r '.legs[].name' "$REC"); do
  f="$PACKET_DIR/$name-r$ROUND-verdict.json"
  # A RECORDED leg with no verdict file — or a 0-byte one, the shape a
  # timed-out or refused leg leaves — is a dispatch/admission failure, not a
  # silent skip: the round record says it was rendered, so it owes an answer.
  [ -s "$f" ] || { echo "-- MISSING x:$name: rendered this round, no validated object at $f"; continue; }
  verdict="$(jq -r '.verdict' "$f")"
  jq -r --arg leg "x:$name" --arg verdict "$verdict" --arg round "$ROUND" '
    .findings[] |
    "| \(.file):\(.line // "-") | \($leg) | \($round) | <leader-triage-class> | \(.severity) / \($verdict) | <probe-or-repro> | \(.summary) | open |"
  ' "$f"
done
```

Each emitted row is a residual-table row PREFILLED from the leg's own
structured fields (finding location, raising leg, round, leg severity +
verdict, one-sentence summary as the rationale seed, disposition `open`); the
leader still fills in the two fields the schema cannot supply — the triage
class (REAL / REACHABLE-UNOBSERVED / SPECULATIVE, rule 4's leader-owned
judgment, never mechanical) and the probe/repro evidence once obtained. The
`file`/`line` fields also make the cite-verification step (Consolidation duty
1 — "read the cited lines and reproduce the claim") mechanical to START: `sed
-n '<line>p' <file>` opens exactly the cited line instead of the leader
hunting for it in prose, though confirming the claim itself still requires
reading the surrounding code, and `references/leg-contracts.md` § agy leg
still requires verifying an agy cite before it enters the table (its cites
were fabricated in most traced runs even inside a schema-shaped reply).

**Fallback (stated, not hypothetical).** A leg dispatched WITHOUT the schema
— an older invocation, or a leg whose `--pydantic` call failed closed before
producing a validated object — has no `<leg>-verdict.json` to read. Consolidate
that leg the OLD way: read its prose reply directly and triage each finding by
hand, exactly as rule 4 always has. The two paths are not mutually exclusive
within one round — one leg's structured object and another leg's prose can
both feed the SAME residual table in the SAME round.

## Reviewer-side instruction

The LEGACY v1 `prepare` templates carry the text below (t4 pins it). A v2
round's prompts carry the vendored shared clauses instead —
`adversarial-framing`, `severity-instruction` and `verdict-selection-rule` in
`spec/prompts/common-clauses.md` (under R-AGREE a Minor-only negative is not
approval there) — and the leader adds nothing to them (SKILL rule 11).

Report every finding — coverage first, and rule 11's no-severity-DEFLATION
stands — but no severity INFLATION either. For each finding, state the concrete
trigger scenario in this deployment. Label a scenario the packet's
deployment-context block rules out HARDENING-SUGGESTION rather than
Critical/must-fix. (That is a LEG-emitted severity label, independent of the
leader-owned SPECULATIVE triage class above — severity and triage are separate
axes, and naming it without the word "speculative" keeps the two from being
misread as the same class.) Only an exclusion carrying its evidence pointer
qualifies: an unevidenced exclusion is not a basis for the label — report
UNKNOWN-CONTEXT at impact-rated severity instead. When the packet does not state
the deployment fact your judgement depends on, report at impact-rated severity
marked UNKNOWN-CONTEXT rather than guessing the deployment.

Do not demand error handling, fallbacks, or validation for scenarios the
deployment-context rules out; trust internal code and framework guarantees;
validate at system boundaries only — where "system boundary" includes user input,
external APIs, AND this repo's declared untrusted inputs (vendor stdout,
run-logs, transcripts, review packets — the export SECURITY threat model), so a
missing validation on those IS in scope. Any leg may challenge a
deployment-context claim it holds to be factually wrong: state the evidence
instead of deferring.

**Verdict selection (state it in every leg prompt — the `prepare` templates
carry it verbatim).** The verdict tracks the BLOCKING axis: report every
finding, then set the verdict from what blocks. Zero Critical/must-fix
findings means SAFE TO MERGE — even when Minor or HARDENING-SUGGESTION
findings are present. MERGE WITH FIXES asserts at least one Critical/must-fix
fix is required before merge. DO NOT MERGE means the change must not land in
its current shape. Never inflate a non-blocking finding's severity to justify
a non-SAFE verdict, and never deflate a blocking one to keep SAFE TO MERGE.
If you judge the change must not merge, that judgment itself is a blocking
finding — report it as Critical/must-fix with its concrete trigger; never
return DO NOT MERGE carrying only non-blocking findings.
(Origin: across one 21-verdict gate whose prompts LACKED this rule, every leg
holding only Minor findings returned MERGE WITH FIXES — the schema explicitly
permits SAFE with non-blocking findings, so the omission alone made a literal
unanimous SAFE structurally unreachable. A drift guard in
tests/unit/skills/t4-prepare.sh pins the load-bearing clauses of this section
and of the paragraphs above into the rendered templates — edit BOTH sides
together.)

### What a conforming verdict looks like

This is the FALLBACK prose shape — for a leg dispatched without the schema
(§ Consolidating validated LegVerdict objects above). A leg wired to
`--pydantic verdict_schema:LegVerdict` (codex, agy) or the claude leg's
JSON output contract (`leg-contracts.md` § claude fresh-eye leg) already
returns this same information as a validated JSON object instead; show this
prose shape only when dispatching a leg the old way. Show this shape to each
leg — a verdict line, then one block per finding with file:line, severity,
and the concrete trigger:

```
VERDICT: MERGE WITH FIXES
Criteria checked: 1-5 (contract parity, error paths, input validation,
concurrency, doc-code agreement).

FINDING 1 — must-fix — wrappers/bin/_common.py:412
  The retry loop re-enters _run_once without resetting `attempt_started`, so a
  second attempt inherits the first attempt's deadline.
  Trigger in this deployment: any dispatch that hits the server-capacity retry
  path (observed in the packet's own audit sample, line 88).

FINDING 2 — HARDENING-SUGGESTION — skills/x/SKILL.md:57
  The documented path assumes `jq` is present; the packet's deployment-context
  block rules out hosts without it (evidence pointer: setup doc cited there),
  so this is a suggestion, not a must-fix.
```

A bare "SAFE / none / faithful" with no criteria enumeration and no findings is a
failed review, not a pass (rule 11). The converse composition is VALID and
expected: `VERDICT: SAFE TO MERGE` followed by Minor / HARDENING-SUGGESTION
finding blocks is the CORRECT verdict when nothing blocking was found — per
the verdict-selection rule above, and per the schema's own bidirectional
validator (only Critical/must-fix findings are incompatible with SAFE).
