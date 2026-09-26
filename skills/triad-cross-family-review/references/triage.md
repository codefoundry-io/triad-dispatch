# Cross-family review — consolidation, finding triage, residual table

Loaded on demand from `triad-cross-family-review/SKILL.md` (Hard rules 4 and
14). Read this while consolidating a round's verdicts, before a finding enters
the fix queue, and when recording or updating a residual.

## Contents

| Section | Open it when |
|---|---|
| Consolidation duties | a round's legs have all returned |
| Block release paths | a reviewer's block needs closing |
| Collect outcomes | `collect` returned a non-zero exit and you need the rule it applied |
| Verdict release at the merge gate | Flow 4 and an entry's verdict is still non-SAFE |
| Triage classes | classifying a finding before the fix queue |
| Scope-expansion gate | sizing a fix for a REAL finding |
| Loop exit | the round lands no REAL findings |
| Residual table | recording, updating, or carrying forward a residual |
| Consolidating validated LegVerdict objects (jq) | a leg was dispatched with `--pydantic verdict_schema:LegVerdict` (or its claude-leg equivalent) and its findings need mapping into the residual table |
| Reviewer-side instruction | writing the leg prompts |
| Fourth-leg comparison record | two entries of ONE family ran this round and you are recording the comparison (or reading a LEGACY v1 X-leg row) |

## Consolidation duties

Three duties, in order:

1. **Fact-check every finding against the source before acting on it.** Read the
   cited lines and reproduce the claim with a deterministic probe (grep, a
   controlled fixture, official docs). A finding can be plausible and wrong, and
   a reviewer's confidence is not evidence — a probe-refuted finding is closed by
   recording the probe, never by a counter-argument.
2. **Classify the round**: CONVERGING (new real findings, or independent legs
   hitting the SAME defect — the rule-12 convergence floor), CONFLICTED (legs
   contradict head-on on the SAME decision — one leg approves what another
   requires changed, or two demand mutually exclusive changes — and both sides
   survive the probe), or OSCILLATING (verdict flips or re-litigation without new
   evidence). Then, per finding, triage it REAL / REACHABLE-UNOBSERVED /
   SPECULATIVE before it may enter the fix queue.
3. **On a CONFLICTED item or an OSCILLATING round, call the owner immediately** —
   a push notification where the harness exposes one, else a clearly-marked
   OWNER-CALL section carrying the rule-12 conflict table. The owner adjudicates.
   The leader never self-adjudicates a compromise between live contradicting
   legs, however plausible the middle path, and never spends another round on the
   conflicted item; non-conflicted items keep their fix loop running in parallel
   while the call is pending.

Cross-family complementarity is the point: each family tends to catch a different
class of issue (an extractor bug, a classifier false-positive, a config/safety
gap), with little overlap.

## Block release paths

Any reviewer's Critical / must-fix, or a DO-NOT-MERGE verdict, blocks merge. The
three release paths are exhaustive:

1. a deterministic probe that REFUTES the finding — close it by recording the
   probe. REFUTED means the finding's factual PREMISE is shown false; a repro
   that merely fails to trigger the mechanism is not a refutation;
2. a fix the re-confirm pass clears;
3. an explicit owner decision recorded alongside the DISCLOSED residual.

A leader-side triage to REACHABLE-UNOBSERVED or SPECULATIVE records its rationale
and routes the merge decision to the owner; it never clears the block on its own.

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
| 0 | `AGREED` | every enabled entry returned a valid result with nothing blocking, and at least three FAMILIES are covered. This is the collector's agreement on the reviewed bytes — it does not by itself authorise merge, install or release (SKILL Flow 5 owns that). |
| 4 | `BLOCKED` | a VALID entry carries a Critical / must-fix finding or an unresolved OPEN QUESTION. `acceptance` grants no exemption — an `informational` entry blocks like a `required` one. Verify each finding against the source, triage it, and take the fixes to a NEW round. |
| 5 | `INCOMPLETE` | some enabled entry is missing (a SKIPPED entry included), unreadable, or failed admission. NOT agreement and never a silent pass. Diagnose why that entry failed to RUN, then `retry <packet-dir> r<N> <name> --diagnosis "<why>"`; a valid NEGATIVE verdict is completed work and is never a retry case. `retry` refuses — and the remedy is a NEW round — for a SKIPPED entry (`it never ran, so there is no attempt to retry`) and whenever the entry's reason says `a retry cannot certify this round` (the round's hook load check, `references/failure-modes.md`). |
| 6 | `OWNER_DECISION_REQUIRED` | every enabled entry returned a valid result with nothing blocking, but the results cover fewer than three FAMILIES; two entries of one family are one family. A roster spanning two families (the codex + Google profile of `references/review-legs.four-leg.example.json`) lands here on a clean round by design; a missing or skipped entry is `INCOMPLETE`, which outranks this outcome. Released only by a recorded OWNER decision. |
| 2 | refusal | no or unreadable round record, a round record whose SHAPE is unwalkable (below), an unknown or non-dispatched entry name, an empty `--diagnosis`, or a retry on a completed review. **Also the SPEC-BASIS refusal**: the round record freezes `contract_digest` (sha256 of the canonical ADMISSION schema `verdict_v2` judges every reply against) beside `projection_digest`, and `collect` / `retry` refuse here — `the ADMISSION contract basis changed since this round was prepared (frozen … vs … ) — … prepare a new round (R-REREVIEW)` — on a MISMATCH or on ABSENCE of the frozen value (gate-1 r8 row r8-10). Every other basis was frozen at prepare while the contract was re-read LIVE at collect, and it is the one basis no leg artifact evidences: an admitted `verdict.json` carries no trace of the schema that let it through. A CHANGED basis is a new ROUND, never a re-collection. |
| 64 | HOST FAULT | **THIS HOST cannot admit any reply (or could not RUN the round's evidence tools), so nothing about ANY leg is known** (gate-1 r7 row r7-7, widened at r8 rows r8-4 / r8-9). `verdict_v2` reserves exit 64 for the admission it could not RUN at all — `jsonschema` absent, the vendored contract unreadable / invalid UTF-8 / non-JSON / nested past the interpreter's limit / not Draft 2020-12 (EVERY load-failure class takes this exit since r8-4; two of them used to escape as a traceback) — and `collect` used to record that as the ENTRY's `invalid`, so the round folded to `INCOMPLETE` and told the leader to re-dispatch PAID legs over a broken install. `collect` (and `retry`) now STOP at the first such admission with `collect_v2: HOST FAULT: this host cannot admit any reply: <reason> (reached while admitting <path>)` and write NO per-entry state. **The agy entry's two EVIDENCE TOOLS take the same exit** (row r8-9): `read_audit_gate.sh` and `agy_hook.py check` both reserve rc 64 for "this invocation could not RUN at all" — a required file the round named is gone, a re-pinned worktree, an absent `hook_log`, an unusable argv — and that is a `_HostFault` too, never that leg's `invalid`. **ORDER against the exit-2 basis refusal**: the HOST question comes first — a contract this host cannot even LOAD is 64, and only a contract that loads and DIFFERS is the exit-2 "basis changed — new round". Repair the host and collect AGAIN — the legs' own outputs are untouched and nothing needs re-dispatching. |

**The EXPECTED binding is DERIVED, never read back** (`collect_v2._evaluate`,
gate-1 r5 row r5-1). The six values an attempt's `binding.json` is checked
against come from OUTSIDE that attempt directory: `review_id` and
`content_digest` from the ROUND RECORD, `family` / `leg_name` / `route` from
the round's FROZEN ROSTER ENTRY, and `attempt` from the DIRECTORY NAME the
scan parsed. `binding.json` must EQUAL that derivation before admission runs
at all. They used to be read out of the attempt's own `binding.json`, so the
binding and the result validated EACH OTHER: a `binding.json` + result copied
together out of one entry's attempt into another entry's attempt directory
admitted cleanly and was credited to the DESTINATION entry. A disagreeing
binding is now `invalid` with the offending FIELD named — not a leg that
answered wrong, an attempt directory that does not belong to this entry.

**THE ROUND RECORD DECIDES WHICH ATTEMPT IS EVALUATED** (`collect_v2._evaluate`,
gate-1 r9 row r9-2). `_evaluate` used to take the HIGHEST attempt directory on
disk with nothing requiring that the record had ever ALLOCATED or ADOPTED it —
and the packet dir is helper-owned, so an `attempt-N/` restored from a backup or
planted by hand, carrying a binding that satisfies the derivation above and a
schema-valid SAFE verdict, SUPERSEDED the recorded attempt's BLOCKING verdict
and could drive the round to AGREED. Allocation is the RECORD's act: `prepare`
writes attempt 1 and `retry` bumps the entry (allocating or ADOPTING) before it
returns, so an on-disk attempt ABOVE the record's is one this round never
dispatched. It is refused BY NAME for THAT ENTRY — `<dir> is an attempt this
round never allocated: the round record names attempt <K> for this entry …
inspect it, then remove it yourself or retry the entry so the record adopts it`
— nothing is deleted, every other entry still collects and the round lands on
INCOMPLETE. That refusal fires only when the RECORDED attempt did not itself
return a valid verdict: a completed review is never vetoed by an unallocated
directory, which is then simply not read. Exactly `attempt-<record.attempt>/`
is evaluated, so a RECORDED attempt the tree does not hold is that entry's
`invalid` (`… attempt-<K> is not on disk …`), and `retry` refuses it BEFORE
allocating anything (`Restore attempt-<K>, or re-prepare the round`). Adoption
is reachable only for the one-step orphan, where the recorded attempt IS on
disk; `retry`'s orphan / wide-gap arms read the on-disk high-water mark from
their own scan.

**THE ROUND RECORD'S SHAPE IS CHECKED BEFORE ANYTHING WALKS IT**
(`collect_v2._check_record_shape`, gate-1 r9 row r9-6). `_read_record` probed
the PRESENCE of `entries` and nothing else, so `"entries": null` and
`"entries": [null]` both loaded cleanly and then met `_dispatched`'s iteration
and `entry.get(...)` — a TypeError / AttributeError traceback out of a tool
whose every other failure is one refusal line — while a record missing
`results_dir` crashed inside `_evaluate` and one missing `review_id` /
`content_digest` / `worktree` degraded SILENTLY (a derived binding of None
mismatched every entry, so a tampered record read as "every leg answered
wrong"). The check is a SHAPE check, not a contract: only the members this file
dereferences are named, and each refusal (exit 2) NAMES THE FIELD — `entries`
as a list, each `entries[i]` an object with a usable `name` and a `leg` object
and an `attempt` that is a positive int when present, then `review_id` /
`content_digest` / `worktree` / `results_dir` as non-empty strings. Members
with their own dedicated refusal downstream — `projection_digest`,
`contract_digest`, `prompt_spec_dir`, `hook_log` — are only TYPE-checked when
present, so a record that OMITS one still reaches the refusal that explains
what it was for.

**ONE derivation serves BOTH readers** (`collect_v2._expected_binding`,
gate-1 r6 row r6-3). `collect`'s admission and `retry`'s orphan ADOPTION now
call the same helper, so the two cannot drift: adoption used to compare only
FOUR of the six (`review_id`, `content_digest`, `leg_name`, `attempt`) and
never checked `family` or `route`, so an orphan whose own binding claimed
another family — or a gemini route for the agy-routed entry — was ADOPTED and
then dispatched, gated and admitted under the entry it had been dropped into.
Two copies of one rule is how they diverged; there is now one copy. The
printed `--expected-*` flags come from that DERIVED dict too, never read back
out of the attempt's own `binding.json` (the x amendment to the same row):
the values the operator runs are the round record, the frozen roster entry and
the directory name, exactly as admission's are. Every interpolated value is
`shlex.quote`d (`review_scratch._v2_expected_flags`) — `family`, `attempt` and
`route` were pasted RAW into a command line the operator copies into a shell,
so a value carrying a space or a metacharacter split into two arguments, or
ran. Quoting is the second half of the derive-never-read-back rule, not a
substitute for it.

**A non-object `binding.json` invalidates ONE entry** (gate-1 r6 row r6-4).
`null` and `[]` parse cleanly and then met `binding.get(...)`: the
AttributeError aborted the WHOLE collection, so one malformed file under one
entry threw away every other entry's verdict — the r5-11 class again, in a
tool whose entire output is per-entry state. That entry is now `invalid`
(reason: `binding record is not an object (<type>): <path>`), every other
entry still collects, and adoption refuses the same shape BY NAME for both
`binding.json` and `dispatch.json`.

**An unusable attempt DIRECTORY invalidates ONLY its own entry** (row r5-11).
An `attempt-<non-decimal>` name is still REFUSED rather than skipped (row
r4-15 — skipping would make the collector read a LOWER attempt than the tree
holds), but that refusal is now scoped: the entry goes `invalid` with the
directory named, every OTHER entry still collects, and the round lands on
`INCOMPLETE`. It used to escape the whole `collect`, so one stray
`attempt-1.bak` under one entry threw away every other entry's verdict. A
`retry` of THAT entry runs the same scan itself and still refuses with the
same reason.

**ONE NUMBER, ONE SPELLING — and a real DIRECTORY** (gate-1 r6 rows r6-9 /
r6-10). `int()` is not injective over the names `isdecimal()` admits, so
`attempt-01`, `attempt-001` and every non-ASCII decimal spelling map to the
same number as the canonical `attempt-1`: two directories claimed one
allocation and the stable sort left FILESYSTEM ORDER to decide which one's
verdict was credited to the entry — and a copy dropped in under a second
spelling admitted cleanly, because the derived binding (row r5-1) names the
NUMBER, which both spellings satisfy. Only `attempt-<N>` in the canonical
spelling the writer produces (ASCII digits, no leading zero) is usable; any
other is refused by name. Separately, a SYMLINKED `attempt-K` used to be
SKIPPED by the `is_dir(follow_symlinks=False)` test that ran before the name
check, so the collector read a LOWER attempt than the tree holds — the same
failure the non-decimal refusal exists to prevent, reached through a link
instead of a spelling. A name this helper owns is now a real directory or it
is refused; nothing is followed and nothing is deleted. Both refusals are
per-ENTRY inside `collect` (row r5-11): that entry goes `invalid` with the
directory named, every other entry still collects, the round lands on
`INCOMPLETE`, and a `retry` of that entry refuses with the same sentence.

**Precedence when several conditions hold at once** (`collect_v2._outcome`): `INCOMPLETE` wins over `BLOCKED`, `BLOCKED` over `OWNER_DECISION_REQUIRED`, and `AGREED` only when none of the three applies — an invalid entry is reported before a blocking finding on another entry, and both before the family count.

**`retry` ALLOCATES FIRST, diagnoses second.** The command renders and
`v2_write_attempt`s attempt K+1 (an exclusive-create allocation), and only
once that returns does it write `retry-diagnosis.txt` into attempt K, bump
the record and print the new dispatch line. The order matters because the
guard at the top refuses any attempt that ALREADY carries a diagnosis: with
the diagnosis written first, an allocation that then failed (an unwritable
results tree, a directory that raced in) left the leg PERMANENTLY
unretryable — the only recovery command the round offers refused on a file
the failed run had just planted. Now the diagnosis only ever records a step
that actually happened (gate-1 r3 row r3-18). **That write is GUARDED** (gate-1 r9 row
r9-12): it was bare, so an `OSError` — an unwritable attempt directory, a full
disk — escaped as a traceback out of the ONE recovery command the round
offers, and it did so AFTER `v2_write_attempt` had already allocated attempt
K+1, i.e. in exactly the state an operator most needs a readable refusal. It
now refuses in one line naming the allocated directory and stating that the
round record still names attempt K, so the allocated attempt is ADOPTED on the
next `retry` rather than re-allocated. The ADOPTION path one function over had
always converted this same `OSError`; the rule is now identical on both.

**`retry` ADOPTS an orphan `attempt-K+1/`, and refuses a foreign one BY
NAME.** The other side of allocate-then-diagnose is an allocation that
SUCCEEDED while the diagnosis or the record write failed: `attempt-K+1/` is
on disk and the round record still says K. The next `retry` used to ignore
it — it read the HIGHEST attempt, rendered K+2 and wrote a fabricated
diagnosis into an attempt nobody dispatched, so the numbering ran away from
the record and the dispatch line the operator was holding went stale. Now,
when the tree's highest attempt is exactly `record_attempt + 1`, `retry`
ADOPTS that directory: adoption is CONDITIONAL on the orphan's own
`binding.json` binding THIS entry at THIS attempt — ALL SIX derived values,
through the one `_expected_binding` derivation admission uses (row r6-3,
above) — NOTHING is re-rendered (the frozen
records are the basis, exactly as R-RETRY requires), the diagnosis is written
into attempt K, the record is bumped and the orphan's own `dispatch.json` is
re-printed as the dispatch line. Any other directory at that path — records
unreadable, or a binding that names something else — is REFUSED by name and
NOT deleted: the packet dir is helper-owned, so the tool never removes a
directory it did not write; inspect it, then remove it yourself or prepare a
new round (gate-1 r4 row r4-9).

More conditions gate the adoption, each refusing BY NAME and deleting
nothing (gate-1 r5 rows r5-3 / r5-8 / r5-9 / r5-10, amended by r6 rows
r6-4 / r6-5 / r6-6):

- **The allocation must have FINISHED** (r5-3). `binding.json` and
  `dispatch.json` are the first records the writer produces and the producer
  schema projection is the LAST, so an allocation interrupted between them
  satisfied the identity check while `prompt.txt` or
  `schema.projected.json` was still missing — adopting it printed an argv
  whose `--output-schema-file` pointed at a file nobody wrote. Adoption now
  requires EVERY file the writer produces for THAT ROUTE (the projection
  exactly when this attempt's `dispatch.json` names one).
- **`dispatch.json` is TYPE-CHECKED on every member the print reads** (r5-8,
  corrected by gate-1 r6 row r6-5). The adopted record is what the operator
  actually runs. The r5-8 check asked only whether THREE members were
  non-empty, so `argv: [1]` passed it and `shlex.quote` then raised
  mid-print — after the round record had already been bumped. Now every
  member `v2_print_dispatch` / `_v2_expected_flags` read is TYPE-checked
  before anything is written: the `kind` (`native` / `wrapper`), the
  identity for that kind (`native.subagent_type` a non-empty string, `argv`
  a non-empty list OF STRINGS), `stdout_path` / `stderr_path`, `env` as a
  mapping of strings to strings, `read_audit_path` — **the KEY is required on
  EVERY wrapper route, `null` on the routes that take none** (gate-1 r7 row
  r7-6): the gate and the hook check are printed from it, and the check used
  to ACCEPT an absent key on a non-agy route while the print INDEXED it, so a
  codex or gemini record written without it raised a `KeyError` AFTER the
  diagnosis had been written; the value is a non-empty string on the agy route
  and `null` elsewhere, and the print now reads it with `.get()` (both halves,
  so neither side alone decides) — and `schema_file` when the record
  names one. Each unusable member is refused BY NAME; the value itself is
  vendor- or operator-supplied text and is never echoed. A record with a
  null `subagent_type` used to reach the print and be spawned under the
  layout default — the GATING reviewer.
- **The adopted record is COMPARED against a fresh RE-RENDER, not trusted**
  (gate-1 r7 row r7-11). Everything above proves the orphan's binding names
  THIS entry at THIS attempt and that its `dispatch.json` is well TYPED — but
  the argv, env and paths were then read back VERBATIM and printed for the
  operator to RUN, so a record planted in the orphan directory could
  substitute the PROGRAM under this entry's name (the r5-1 read-back class,
  one file over). `retry` now re-renders the K+1 dispatch from the round's OWN
  FROZEN roster entry and refuses adoption when ANY compared invocation member
  differs (`… is not the invocation this round renders for '<name>'
  attempt K+1 (differs: …)`). On equality the ON-DISK bytes are adopted and
  nothing is re-rendered INTO the attempt, exactly as R-RETRY requires — the
  re-render is a comparison basis, never a write.
  **`kind` AND `native` ARE PART OF THE INVOCATION** (gate-1 r8 row r8-2).
  r7-11 compared the six WRAPPER members only — `argv`, `env`, `stdout_path`,
  `stderr_path`, `read_audit_path`, `schema_file` — so the two members that
  decide WHO RUNS on the native route were never read: a planted record could
  substitute the reviewer (`native.subagent_type`) or flip a wrapper record to
  a native spawn while every compared member still matched, since a native
  record carries `argv: null` / `env: {}` and the wrapper's own argv is simply
  not read on that route. The comparison set is now `kind`, the WHOLE `native`
  block, and those six (`collect_v2._ADOPT_COMPARED_FIELDS`,
  `collect_v2.py:117-118`) — comparing the whole block also states the wrapper
  case, where the writer emits `native: null` so any block at all differs.
- **The two files the adopted invocation FEEDS THE VENDOR are PROVEN, not
  merely present** (gate-1 r8 row r8-7). **Amended at gate-1 r9**: the CLAUSE
  DIRECTORY is the other half of that basis, so adoption now requires AND
  compares `prompt_spec_dir` exactly as the normal `retry` does (row r9-5) —
  digests alone do not say WHERE the clause bytes came from, and a record
  written without the key let the comparison be skipped entirely; absence and
  mismatch refuse the same way ("prepare a new round"). The two byte reads go
  through the helper-owned hardened reader `collect_v2._read_regular_file`
  (row r9-11) rather than `Path.read_bytes()`, which FOLLOWS a symlink: a link
  planted at `prompt.txt` or `schema.projected.json`, pointing at a target
  whose bytes happen to match, used to pass the comparison, after which the
  adopted invocation feeds the vendor whatever that link resolves to. Same
  shape as `verdict_v2._read_regular_file_no_symlink` / `roster_v2`: `lstat`
  decides every non-regular type BEFORE the open (a FIFO would otherwise block
  forever), then `O_NOFOLLOW|O_NONBLOCK` and an `fstat` S_ISREG re-check on the
  descriptor. And an unreadable CLAUSE file is a one-line refusal at BOTH
  layers (row r9-13): `prompts_v2._read_spec_text` turns `OSError` /
  `UnicodeDecodeError` from the vendored clause open into `PromptSpecError`
  naming the file, and adoption's own except tuple gained `OSError` for any
  other one the pure render can reach — before the row, a mode-000 or EIO
  clause file escaped as a traceback out of a path whose every other failure is
  one line. Adoption tested `prompt.txt` and
  `schema.projected.json` for EXISTENCE only, so a planted prompt could
  re-instruct the leg under this entry's name and a planted projection could
  change the schema it is handed, both while every binding field and every
  invocation member still matched. Before the attempt is adopted:
  `prompt.txt` is compared against a PURE re-render — through the one context
  construction `prepare` itself uses — whose own clause manifest is checked
  against the round's FROZEN `prompt_manifests[<name>]` FIRST (a spec
  re-vendored since prepare is a NEW ROUND, never a silently accepted
  re-render), and then BYTE-for-byte; `schema.projected.json` is digested and
  compared against the frozen `projection_digest`. A record carrying no frozen
  manifest or no frozen digest cannot PROVE either basis and is refused rather
  than guessed at ("prepare a new round"). Nothing is re-rendered INTO the
  attempt: the re-render is discarded the moment the comparison is made.
- **The ROUND RECORD is the LAST write** (gate-1 r6 row r6-5). Adoption's
  order is validate EVERYTHING → write the diagnosis → print the dispatch
  block → bump `.roster-r<N>.json`. The record write used to run BEFORE the
  print, so anything the print refused left the record already bumped — and
  the next `retry` then fabricated a diagnosis into an attempt this tool
  never dispatched, the exact runaway row r4-9 exists to stop. A refusal now
  always leaves the record naming the attempt the round actually dispatched.
- **A gap of MORE THAN ONE is refused, naming the state** (r5-10). Only the
  one-step orphan (record K, on-disk K+1) is adopted. With record and tree
  further apart there is no attempt the tool can honestly call "the one that
  failed", so it refuses with both numbers and the gap size rather than
  writing a diagnosis into an attempt this round never dispatched.
- **A NON-BLANK diagnosis is retained, an EMPTY one is replaced, a
  non-regular one is refused** (r5-9, corrected by gate-1 r6 row r6-6). The
  retain branch used to key on `exists()` alone, so an EMPTY file — what an
  interrupted write leaves behind, the very failure this adoption path
  exists for — was "retained" and the text the operator typed on THIS
  invocation was discarded under a success line: attempt K then carried no
  record of why it failed at all. Three outcomes now:
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
  ordinary (non-adopt) `retry` still REFUSES outright on any existing
  `retry-diagnosis.txt`, empty included — `attempt K has already been
  diagnosed and retried` — which is a refusal the operator sees, not a
  silent discard, so the r6-6 class does not reach it.

An `attempt-<suffix>` whose suffix is not a DECIMAL number is likewise
refused with one line rather than skipped or crashed — `str.isdigit()` is
true for characters `int()` refuses, and silently ignoring such a name would
make the collector read a LOWER attempt than the tree holds (row r4-15);
inside `collect` that refusal is scoped to the offending ENTRY (row r5-11,
above). Since gate-1 r6 the same one-line, per-entry refusal covers a
NON-CANONICAL decimal spelling (`attempt-01`, non-ASCII digits — row r6-9)
and a `attempt-*` entry that is a symlink or not a directory at all (row
r6-10).

**BOTH records this helper writes go through ONE lstat-refusing writer**
(`collect_v2._write_json`, gate-1 r6 row r6-11). `collect` used a plain
`write_text` for `collect-r<N>.json`, which FOLLOWS a symlink, so a link
planted at that path put the round's collected state wherever it pointed.
`collect-r<N>.json` and the round record (`.roster-r<N>.json`) now share one
writer: the target is `lstat`ed first and a NON-REGULAR path is refused BY
NAME (`… is not a regular file (a symlink or another special path)` — inspect
it, then remove it yourself or prepare a new round), then the bytes go to a
pid-suffixed temp file and `os.replace`. The replace idiom itself never
writes THROUGH a link; the `lstat` is what turns a planted path into a NAMED
refusal instead of a silently replaced one, and it keeps the rule identical
for both records. **The TEMP file is exclusive-created too, and unlinked when
the staging does not consume it** (gate-1 r7 row r7-2): the `lstat` refuses a
planted TARGET, but the staging used `write_text`, which FOLLOWS a symlink
planted at the predictable `.tmp-<pid>-<name>` — so the round's collected
state was written wherever that link pointed, inside a directory this helper
owns. The temp is now opened `O_CREAT|O_EXCL|O_NOFOLLOW` (the rule both
sibling writers — `verdict_v2._write_admitted_out` and
`review_scratch._write_new_file` — have always applied), a pre-existing name
of any kind is refused BY NAME, and a `finally` removes a temp that was never
replaced, so a refused write leaves no `.tmp-…` residue for `verify` to report
as an uncovered packet file.

**Every record load tolerates a RECURSIVE document** (gate-1 r7 row r7-8).
`json.loads` raises more than `ValueError`: a document nested past the
interpreter's recursion limit raises `RecursionError`, which is NOT a
`ValueError`, so it escaped as a traceback from paths that promise a one-line
refusal and aborted the WHOLE collection. Every record load in `collect_v2`
(and `review_scratch`'s round-record read) now catches the same tuple —
`(OSError, ValueError, RecursionError, UnicodeDecodeError)` — and reports the
offending file by name. **`roster_v2._read_json` joined them at gate-1 r9 row
r9-7**: the roster loader caught `ValueError` alone, so a roster or leg-config
document nested past the limit escaped `main()`'s `RosterError` arm as a
traceback at exit 1 — out of the loader whose every other failure is one
refusal line at exit 2.

**Subprocess output is decoded UTF-8, and the collector's own streams never
raise** (gate-1 r6 rows r6-12 / r6-16). `collect_v2._run` — the helper that
shells out to the agy read-audit gate and the hook check — used `text=True`
alone, which decodes with `locale.getpreferredencoding()`: on a host running
under an ASCII locale the gate's own em-dash diagnostics raised
`UnicodeDecodeError` out of `_agy_evidence_reason`, a traceback where the agy
entry owed a one-line reason, and it took the WHOLE collection with it.
`encoding="utf-8", errors="replace"` is now pinned there, the same pin the
wrappers apply to every vendor pipe. The mirror-image defect on the OUTPUT
side is closed the same round: every CFR lib's `main()` reconfigures its
DIAGNOSTIC stream with `errors="backslashreplace"`, so a refusal sentence
carrying a path or a vendor token the locale codec cannot encode is printed
escaped instead of raising `UnicodeEncodeError` — a host under a non-UTF-8
locale can no longer turn a one-line refusal into a traceback.

**…but `stdout` is the PAYLOAD stream and is NEVER re-encoded** (gate-1 r7 row
r7-4). `_relax_std_stream_errors` is now **stderr-only**: r6-16's relaxation
of `stdout` was right for operator prose and wrong for the two things on this
stream that a machine or an operator CONSUMES — `prompts_v2`'s rendered prompt
/ manifest / investigation clause, and `review_scratch`'s six dispatch lines.
`backslashreplace` silently REWRITES them (a rendered prompt's em-dashes came
out as `—`; a dispatch line's non-ASCII path token printed `caf\xe9`
under `LC_ALL=C`, i.e. a path that does not exist, handed to an operator with
no warning). Both printers now encode ONCE as UTF-8 and write to
`sys.stdout.buffer` (`_emit_payload`), so the locale gets no vote; every token
in a dispatch line is already `shlex.quote`d by the caller. A text this host
cannot represent as UTF-8 — a path decoded with `surrogateescape` — is
**REFUSED BY NAME** rather than escaped (`a dispatch line carries a path this
host cannot represent as UTF-8 … rename the offending path or prepare this
round under a UTF-8 locale`), because a mangled path in a command the operator
RUNS is the failure the emitter exists to stop. **The no-`.buffer` FALLBACK takes the
same refusal** (gate-1 r9 row r9-4). Both emitters fall back to
`sys.stdout.write(text)` when `sys.stdout` exposes no `.buffer` — an
in-process harness, or a stream replaced under a non-UTF-8 locale — and that
write carried no handler, so an ASCII encoder raised `UnicodeEncodeError` as a
traceback out of a library whose every other failure is one line. The payload
is never rewritten to get past it (`backslashreplace` here would silently
change the clause bytes the round record's manifest digests, or mangle a path
in a command the operator RUNS), so the fallback now raises the SAME refusal
the encode step above uses: `prompts_v2` a `PromptSpecError` ("render to a
binary stream or under a UTF-8 locale"), `review_scratch` its one-line
`review_scratch:` failure. Wrapper-side counterpart:
the plugin `README.md` § Payload vs diagnostic streams.

**`retry` compares the PROMPT BASIS against the round's frozen manifest.**
R-RETRY re-renders from the round's own frozen roster entry, so the leg
CONFIG cannot move — but the CLAUSES are re-read from the live
`spec/prompts/*.md` on every render, and a spec re-vendored between `prepare`
and `retry` silently changed the instructions the leg receives while the
round record still claimed an unchanged basis. `retry` now compares the
rendered clause DIGESTS plus the clause DIRECTORY with the `prompt_manifests`
frozen at prepare, BEFORE `v2_write_attempt`, so a refusal leaves nothing
behind: a mismatch — or a record carrying no frozen manifest for that entry —
refuses with "the prompt basis changed since this round was prepared …
prepare a new round" (R-REREVIEW: every entry reviews the new basis again).
A changed basis is a NEW ROUND, never a quiet re-render (gate-1 r4 row
r4-16). A MISSING frozen manifest for that entry **or** a missing frozen
`prompt_spec_dir` refuses the same way (gate-1 r5 row r5-7): the directory
comparison used to be SKIPPED when the record carried no `prompt_spec_dir`,
so a record written without that key let a retry re-render out of a
DIFFERENT clause directory as long as the digests lined up — the same claim
("the basis is provably unchanged") the missing-manifest refusal one line up
already declines to guess at. Both halves are required, neither is inferred.

**`retry` compares the PRODUCER SCHEMA BASIS too — `projection_digest`**
(gate-1 r7 row r7-3). The clause check above pins the PROMPT basis, but
`roster_v2.render_dispatch` re-derives `schema.projected.json` from the
vendored `spec/contracts/leg-verdict.schema.json` LIVE on EVERY render,
including the one a `retry` runs for attempt K+1 — so a spec re-vendoring
between `prepare` and `retry` handed the new attempt a DIFFERENT producer
schema while the round record still claimed an unchanged basis (the
r4-16 / r5-7 class, one file over). `prepare … --v2` therefore freezes
`projection_digest` — the sha256 of the PROJECTED schema bytes — in
`.roster-r<N>.json`, and `retry` re-derives and compares it BEFORE
`v2_write_attempt`, so a refusal leaves nothing behind. It is a DIGEST, not
the bytes, because the bytes already live in each attempt's own
`schema.projected.json`. **Absence refuses exactly like a mismatch**: a
record carrying no frozen digest cannot PROVE the basis either (`the round
record carries no frozen producer-schema projection digest … prepare a new
round`), so **a round prepared BEFORE this wave cannot be retried — re-prepare
it**. A host where the projection cannot be derived at all (an unreadable or
non-conforming vendored contract) refuses with that reason instead of
guessing.

**Minor-only NEGATIVE verdict = agreement + a deviation row.** An entry that
returns `MERGE WITH FIXES` or `DO NOT MERGE` with ZERO blocking findings and
ZERO open questions agrees on the bytes as they stand: the collector counts it
as agreement and records a verdict-selection DEVIATION rather than
normalising it away. Add the deviation to the residual table as a
non-blocking row naming the entry and the verdict token it should have used
(SAFE TO MERGE) — the leg prompt carries the verdict-selection rule
(§ Reviewer-side instruction), so a repeat is a prompt-adherence signal worth
sharpening next round, never a merge block.

On an agy route the CUSTODY check, the per-attempt READ-AUDIT GATE and the
HOOK LOAD CHECK are part of the result, not optional extras: an ungated agy
answer is UNVERIFIED and the collector treats that entry as invalid. CUSTODY
runs first: the attempt's own `stderr.log` must carry the whole line
`read-audit-file: <that absolute path>` (timestamp prefix, percent-escaped
filesystem bytes), or the audit beside it is not this attempt's evidence. The
hook load check is a ROUND check: every agy attempt of the round (superseded
ones included) is a sibling, hook rows are attributed to attempts by the
`conversation_id` each census row recorded, and a verdict other than PASS falls
on every agy leg of the round. The collector runs that check again on a
non-valid entry and, when a retry could not certify the round, says so on the
entry's reason (`a retry cannot certify this round …`) — `retry` refuses on the
same sentence (`references/failure-modes.md`).

## Verdict release at the merge gate

Flow step 4 asks whether THIS round's verdicts still block. Two carve-outs
release a standing non-SAFE verdict from a gating leg:

1. it carries at least ONE extractable finding and EVERY finding behind it is
   `probe-refuted` with the probes recorded; or
2. it carries at least ONE extractable finding and rests only on
   owner-accepted rows (`accepted-residual`).

Separately, a MERGE WITH FIXES whose findings are all non-blocking does not block
merge at all — its findings still triage per the classes below.

A non-SAFE verdict with NO extractable finding is an INVALID leg — "returned
something, but the verdict is unusable". So is **a reply that does not
VALIDATE — unparseable raw text (truncation included), a schema failure, or
a binding mismatch** (this sentence is the chain's DEFINITIONAL HOME —
2026-08-30 verdict-admission hardening; the cross-references in
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
asymmetry: findings only add work; only a verdict can release).

## Triage classes

The fix→re-confirm loop structurally rewards ADDING code — reviewers are rewarded
for findings and nothing rewards simplicity — so unchecked rounds grow defensive
layers. Before ANY finding enters the fix queue the leader classifies it during
consolidation (the deterministic probe doubles as the occurrence check):

- **REAL** — demonstrated rather than argued: a runtime repro, a logged/audited
  occurrence in THIS deployment, or — for a spec/doc/interface defect — the cited
  passages read side by side. A static contradiction, wrong flag, or broken
  cross-reference is REAL as soon as reading reproduces it; the "concrete trigger
  scenario" test applies to runtime-behaviour findings. → minimal-diff fix; rule
  5's autonomous loop applies. A NON-blocking REAL finding the leader declines to
  fix instead carries a recorded residual row — never a silent drop.
- **REACHABLE-UNOBSERVED** — the mechanism exists but there is no occurrence
  evidence. → REPRODUCE FIRST (a TC or live probe) before any fix. A failed repro
  does not prove impossibility: the item never reclassifies to SPECULATIVE — it
  becomes a DISCLOSED residual routed to the owner's merge decision.
- **SPECULATIVE** — cannot occur in this deployment (other platform, inside the
  trust boundary, vendor-guaranteed, absent threat model). → **no code.** Record a
  DISCLOSED residual with the classification rationale; the next round's packet
  carries the disclosure, and a re-raise without new evidence counts as rule-12
  noise.

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
   fix requires are exempt; or
4. exceeds 30 changed lines — added plus removed in the fix's own diff,
   non-generated production code, counted for the whole logical fix (splitting
   across commits or rounds does not reset it; a repro TC or probe is
   investigation, not part of the fix).

**Plan-gate fold of a NEW semantic contract (2026-09-05, P6 entry-plan gate).**
A fold that introduces a new semantic contract — a runtime-evidence rule, a
resolver, a predicate — hands every subsequent round a fresh layer of REAL
material to review: r2 returned 22 rows and r3 another 16, all on the newly
folded text, with no oscillation and no defect in the earlier rows. The entry
plan therefore folds the CONSTRAINTS the contract must satisfy and DELEGATES
the row-level DESIGN to the unit that owns the contract and carries its own
gate. A gate that keeps producing real findings on material the current fold
just created is a scope signal, not a convergence failure.

Design expansion STOPS for an explicit owner OK before implementing, even
mid-round. This bounds the autonomous fix loop rather than suspending it: leader
autonomy covers REAL findings with minimal diffs.

## Loop exit

**Countable stop rules (rule 5 / 12 / 14, owner directive 2026-08-22):**

| rule | trigger | what happens |
|---|---|---|
| design or plan change | a finding's fix requires changing the gated plan or design — a new contract, a restructured order of operations, a new public def/class not in the gated design | OWNER discussion BEFORE any design work; this replaces the 2026-08-22 three-round cap (removed by owner directive 2026-09-17 — no round count is a stop by itself; non-contradicting in-design bug fixes continue at any round) |
| convergence | a round lands zero NEW REAL must-fix, produced NO fix wave, and `collect` returned `AGREED` — or, on a roster spanning fewer than three families, `OWNER_DECISION_REQUIRED` with a recorded owner decision | the gate is done. A round that DID produce a wave has not converged: the wave is a new basis and owes its own FULL round (R-REREVIEW — there is no focused re-confirm, SKILL rule 5) |
| occurrence gate | a REACHABLE-UNOBSERVED item has no repro from REAL vendor output (capture / run-log / audit row) | DISCLOSED residual, no code — a fixture-only repro does not promote it |
| docs never gate | a finding is text-only | batched into one post-merge doc-resync commit; never a round trigger |
| scope freeze | round ≥ 3 and the finding cites no hunk of the gated diff | new slice, not this gate |
| two-family floor | single-family REACHABLE item, no measured probe — **roster entries of the SAME family (two claude arms, two codex entries, several Google entries) count as ONE family**: their agreement never clears this floor | residual |

Precedent: the 2026-08-22 agy v1.2 gate ran nine rounds; rounds 4-9 landed
one narrower parser shape each (null field → malformed container → dropped
line → array line), none ever observed in 22 real captures, plus ~15 text
rows — the shape these rules end.

Distinct from the CONVERGING round class: once every REACHABLE-UNOBSERVED item
has had its repro run, a round whose remaining findings are all SPECULATIVE or
repro-failed is TERMINAL. Record each as a DISCLOSED residual in the residual
table and route the merge decision to the owner through the conflict channel when
any of those rows is BLOCKING; a round whose residuals are all non-blocking
records them and proceeds by Flow 4. Dispatch no further round for them.

Review convergence is NOT merge readiness: for a blocking residual the owner's
recorded decision closes it.

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
the merge-stage gate against the actual diff — plus the codified
non-blocking release above; never more plan-time enumeration rounds
(precedent: an 11-round plan gate whose final rounds' findings were half the
leader's own fold-edit slips).

## Fourth-leg comparison record

A second entry of a family already on the roster is run to be COMPARED with the
SAME-FAMILY baseline entry — a codex comparison entry (`codex-astra`) against the
codex baseline, a claude arm against the GATING claude leg — so each round gets
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
VERIFIED Critical / must-fix raised ONLY by an `informational` entry blocks
exactly like a `required` entry's, and the only release valve for thin family
coverage is the collector's `OWNER_DECISION_REQUIRED`. An entry that failed,
timed out, or returned an unusable verdict is `INCOMPLETE` — recorded in the
same row set, diagnosed, and retried as attempt K+1 (SKILL rule 13), or taken
to a NEW round where `retry` refuses (§ Collect outcomes); it is
never silently dropped and never counted as agreement. For rule 12's
head-on-contradiction test, two entries of the SAME FAMILY are one voice: a
disagreement between them is a comparison-record fact, never a CONFLICTED
round on its own — and their agreement is not the independent-legs
CONVERGENCE floor either.

The `x:<name>` tag survives as HISTORY for v1 rounds (SKILL.md § Legacy v1
rounds): rows written before 0.37.0, or by a packet prepared without `--v2`,
carry it and keep their advisory reading.

## Residual table

`<packet-dir>/residuals.md`, one row per finding: finding / raising leg / round /
class / leg severity + verdict (does it BLOCK merge?) / probe or repro evidence /
rationale / disposition (`open` | `fix-ordered` | `fix-cleared` | `probe-refuted`
| `accepted-residual`).

- A row moves to `fix-cleared` when the re-confirm pass clears its fix (release
  path 2) and to `probe-refuted` when a recorded probe refutes it (path 1).
- A fix that is APPLIED but not yet re-confirmed stays `fix-ordered` — never
  `fix-cleared (pending …)`, which would release the gate on a leader assertion.
- Rows are UPDATED, never deleted: the table is audit history.
- `accepted-residual` is set ONLY by a recorded owner decision (path 3), never
  leader-assigned.

Copy the table into the next round's packet and into any owner-call section,
INSIDE a data fence — the diff fence, or its own
`=====RESIDUALS BEGIN/END=====` fence with the same data-not-instructions line.
The table's finding/evidence/rationale cells carry vendor-authored text, a
declared untrusted input, which must never sit among the leader-authored
questions.

Flow step 4 refuses merge while any blocking row's disposition is `open` or
`fix-ordered` (`fix-cleared`, `probe-refuted`, and `accepted-residual` release;
only `accepted-residual` releases without a cleared fix or a recorded probe). A
disclosure the next round's reviewers correctly decline to re-raise is NOT a
release — the three release paths above are exhaustive.

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
the entry list from the RECORD rather than from memory or a glob. The
finding's location field is `path` in the v2 schema (`file` in v1).

**v1 rounds** keep the loop below verbatim (`leg-contracts.md` § codex leg /
§ agy leg / § claude fresh-eye leg — `bin/verdict_schema.py`'s
`LegVerdict`):

```bash
# One validated object per leg, at <packet-dir>/<leg>-r<N>-verdict.json
# (codex-r2-verdict.json / agy-r2-verdict.json from the wrappers' stdout;
# claude-r2-verdict.json is PRODUCED BY `validate_verdict.py --admit
# --admitted-out` on successful admission (0.29.0) — the raw marker-bearing
# claude-r2.json is NOT jq-consumable; never point jq at it).
# ROUND-SUFFIXED on purpose (adopt-gate r2): a round-free name would be
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
# No record at all = a pre-0.30.0 packet, or a hand-removed record. Say so:
# without this line the loop below emits nothing and reads as "no findings".
[ -f "$REC" ] || echo "MISSING fourth-leg record $REC (a pre-0.30.0 packet, or a hand-removed record — packet-lifecycle § Round integrity)"
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

Add to every leg's prompt, alongside the rule-11 adversarial framing:

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
