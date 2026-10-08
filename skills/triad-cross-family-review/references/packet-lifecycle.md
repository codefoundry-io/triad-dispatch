# Cross-family review — packet lifecycle, order, and round integrity

Loaded on demand from `triad-cross-family-review/SKILL.md` (Hard rule 8).
Read this when opening or closing a packet dir, shrinking a large diff, or
deciding whether an edit made mid-round invalidates it.

## Contents

| Section | Open it when |
|---|---|
| Where packet files live | choosing a path for a brief / diff / context file a vendor leg has to read |
| Packet dir lifecycle | opening, refreshing, or closing a packet dir — `review_scratch.py` and its ownership fences |
| Per-entry results tree (v2) | finding an entry's attempt artifacts, or asking whether a file is censused |
| Packet dir lifecycle → Going on in a new packet dir | `open` / `prepare` / `verify` / `close` refused (or the prune skipped) over an entry it could not name as its own round tree, or a second round tree — the ONE supported manual intervention |
| Large diff — shrink the reviewed surface | the diff is big or the review spans several documents |
| Packet order and fencing | assembling the packet itself — block order, the data fence, containment placement |
| Deterministic round preparation — prepare | building a round's packet + leg bodies (the normal path — one command) |
| Round integrity — capture / verify | before dispatching any round, after its legs return, or when a fix is ready while legs are still out |

## Where packet files live

gemini and agy (at or below 1.1.2) are workspace-sandboxed to the repo, so a
brief / diff / context file handed to them at `/tmp/...` is unreadable (gemini
errors `Path not in workspace: "/tmp" resolves outside the allowed workspace`).
Current agy builds CAN read outside their cwd — a probe read a `/tmp` canary
under `--sandbox read-only` — but keep the repo-relative convention anyway: the
compatibility route for the older gemini CLI needs it, and it keeps every leg
uniform.

Every review-context file goes inside a helper-managed packet dir under the
gitignored `_runs/review/` — never a bare `_shared/<name>.md`, never `/tmp` — so
every READING leg can `Read` it; the codex leg reads the same files through its read-only shell (rule 9). This is a
DELIVERY convention, not a read boundary: the claude `Agent` leg, the codex leg and current
agy builds can read outside the repository (including `/tmp`), and only the
gemini route is workspace-sandboxed; the read limits that exist are the ones
`references/leg-contracts.md` states per leg.

## Packet dir lifecycle

The deterministic helper `lib/review_scratch.py` (python3 stdlib) owns the
lifecycle. Enforcement is review-owned: a wrapper-side prune of a leader path was
reviewed and REJECTED as scope creep plus a foreign-repo deletion hazard in
exported installs.

- `python3 <skill>/lib/review_scratch.py open <abs-root> <slug>` at review start
  — creates `<root>/<UTC-date>-<slug>/` with an `.active` heartbeat, prunes stale
  HELPER-MANAGED siblings (date-prefixed dirs whose `.active` heartbeat mtime is
  past the floor — a crashed loop stops refreshing it; the floor is the
  review-scratch role's in the cleanup configuration), and prints the packet dir. A
  date-dir WITHOUT a regular `.active` file is unmanaged: it is skipped with a
  note and never deleted (the wrong-root fence). `open` is create-NEW-only — a
  same-day duplicate slug is refused loud rather than silently shared.
  The same stale sweep also runs after every successful `close`, over the
  closed packet's root. The root holds packet dirs and nothing else: the
  helper deletes only what it owns, so a file parked at the root is never
  touched — the leader keeps its own scratch (brief drafts, round scripts,
  digests) outside `_runs/review/`, in the session scratchpad.
  `<abs-root>` = the ABSOLUTE `<repo>/_runs/review` path (canonicalized; the
  final component must not be a symlink).
- `… touch <abs-dir>` when a fix→re-review loop spans days with no
  `prepare` / `capture` / `verify` / `retry` / `collect` / native admission
  inside the floor, so an ACTIVE loop's heartbeat outlives it. `prepare`,
  `capture` and `verify` refresh it when they succeed (a refusal or failure
  never refreshes it) after checking the provenance marker; `retry` and its
  adoption (each round-record write), `collect` (after its record) and the
  native `--admit … --admitted-out` (after it writes the admitted result or a
  refused reply's seal) refresh it best-effort: a `utime` of an existing
  regular `.active`, no provenance check, never minting it, never following
  a link, never failing their command. A gate
  resumed close to the floor runs `touch` first: a sibling `open` / `close`
  sweep may reclaim a packet whose heartbeat is older than the floor while a
  long command is still running (the command then fails, nothing false is
  recorded).
- `… close <abs-dir>` at review end — the primary cleanup path. The
  prune at the next `open` or `close` is only the crash backstop. Close first REPORTS whether
  the highest captured round verifies NOW — it re-runs `verify` fresh and never
  trusts a remembered `.verified-r<N>.json`; a WARNING when it does not (the
  owner-ruled disposition is to proceed), never a
  refusal — then, every check passed, appends one `close verified` line to
  `.active` and deletes the dir in place through the host's deletion command
  (`.active` kept until last). A close stopped part-way (Ctrl-C, a timeout, a
  failing git step) is completed by running close again: it re-checks the
  round tree as a SUBSET of what it checked — a tracked file or a delivered
  artifact may be missing; anything untracked, modified or differing from its
  record still refuses, saying the close was stopped part-way. Until then
  `prepare` and `capture` refuse the packet (no new round in a folder whose
  deletion has started); a partly written `close verified` line reads as not
  started (close checks everything again and rewrites it in full); a close
  stopped after `.active` went leaves an EMPTY dated folder, which close
  removes. A worktree git has LOCKED, at any depth, is refused by every
  deletion — unlocking it is the operator's act. Every check — the cleanup configuration of the
  root's project, the root being the declared one, no link in any component
  of that root — runs before the round tree or anything else is touched. A SECOND `close` of the same (now absent)
  dir is a NO-OP at rc 0 with every shape check and the configuration check
  still run (C7): the first one already deleted it, so a repeat must not look
  like a failure.
- **Deletion follows a CLAIM RECORD, never a name shape (C4/C5).** A
  `<name>.pruning` directory (left by a close of an earlier version, which
  renamed) skips the age floor at a later `open` or `close` sweep only when
  `<name>.pruning/.claim` PROVES this helper claimed THAT directory: a
  regular non-symlink file under 4096 bytes, parsing as a JSON object,
  carrying the provenance magic, and naming an `original` equal to the
  directory's own name minus the suffix. A foreign tree that merely wears the
  suffix, a record copied from another dir, or a symlinked record is NOT ours
  and is preserved and reported. The removal is the host's deletion command,
  which proves the residue by its `.active` (a claim-only residue whose
  `.active` is gone stays, reported); a residue with a managed `.active` but no
  claim is judged like a packet (the floor applies); an EMPTY `<name>.pruning`
  dir goes through the command's empty-folder rule once it is older than the
  floor; a fresher one is left. A residue holding a git-LOCKED worktree is
  left and reported (no deletion ever forces a lock).

Symlinks are refused (root and children), non-date-prefixed entries and plain
files are never touched, and the root is always an explicit absolute path (never
cwd-derived). EVERY ownership-checked operation — the `close`/prune deletions and
the heartbeat refresh by `touch` / `prepare` / `capture` / `verify` alike — operates ONLY on dirs carrying the helper's
`.active` ownership marker WITH its provenance magic inside; a foreign file that
merely happens to be named `.active` never qualifies. The one exception is an
EMPTY dated folder under the declared root (an emptied packet whose close
stopped before its `rmdir` cannot be told from any other empty one, and it holds
nothing to lose): an explicit `close` of it removes it whatever its age, and the
sweep removes one past the floor — both through the host's deletion command's
empty-folder rule. A NON-empty date-named dir without the marker is skipped or
refused rather than rmtree'd, so even a typo'd root cannot reap foreign
directories. A deliberately KEPT record dir retains `.active` and is
pruned by a later `open` or `close` once its heartbeat passes the floor, so keep long-term
records outside the packet root.

Packet `close` DELETES the dir, so copy the residual table to its durable record
first (`references/triage.md` § Residual table).

### Per-entry results tree (v2)

`prepare … --v2` gives every enabled non-skipped roster entry its own
immutable custody under the packet dir:

```
<packet-dir>/
  wt-r<N>/                          the round worktree (4 delivered artifacts)
  delivery-r<N>.md  digest-r<N>.txt the delivery record + digest
  .roster-r<N>.json                 the round's FROZEN roster + where each entry lives
                                    (incl. `projection_digest` and
                                    `contract_digest`, the round's
                                    producer-schema and ADMISSION-contract
                                    bases — see below)
  .snapshot-r<N>.json               capture's census + worktree fingerprint
  .verified-r<N>.json               verify's record (content digest + fingerprint)
  collect-r<N>.json                 the collector's folded per-entry result (the
                                    LAST collection that wrote it; a refused
                                    collect, exit 2, leaves it untouched — the
                                    outcome is the latest collect's exit code)
  agy-hook-r<N>.jsonl               the agy PreToolUse hook log
  results-r<N>/<name>/attempt-K/
      binding.json            the six-field bind (review_id, family,
                              content_digest, leg_name, attempt, route)
      prompt.txt              the clause bytes this entry received
      dispatch.json           the invocation (argv/env, or the native spawn)
      schema.projected.json   the producer projection, on the routes that take one
      verdict.json            a wrapper route's stdout
      raw.json + admitted.json  the claude route's verbatim reply and its
                              `--admitted-out` product
      read-audit.json         an agy route's per-attempt audit
      stderr.log              the entry's stderr — on an agy route it must carry
                              the wrapper's whole `read-audit-file: <abs path>`
                              line for the audit beside it (CUSTODY)
      retry-diagnosis.txt     written by `retry` into the FAILED attempt
```

One entry plus one attempt number is ONE allocation: `mkdir` is exclusive and
each record is exclusive-create, so a second write of any of them fails loud.
`retry` allocates attempt K+1 and never touches attempt K — except to write
that attempt's `retry-diagnosis.txt`. Before anything is allocated `retry`
refuses: a disabled or SKIPPED entry (it never ran); an entry whose recorded
attempt returned a VALID verdict (a completed review is not a transport
failure); and a recorded `attempt-<K>` that is not on disk (prepare a new
round) (`references/failure-modes.md`). Never move, copy or rename an
attempt's artifacts by hand: the custody line ties each read audit to the
attempt that wrote it, and the hook check judges each attempt on its own
audit.

**Recipe facts.** Dispatch exactly the lines `prepare` / `retry` print; `collect`
runs once every dispatched entry has terminated and `verify` has passed. When a
round needs a roster override the committed `.claude/triad-review-legs.json`
does not carry, apply it before `prepare` (it reads the LIVE checkout; the
round record freezes the resolved roster) and restore that file to `HEAD` after
`collect` — never between `prepare` and the round's final `verify`.

**An ORPHAN `attempt-K+1/` is ADOPTED, not skipped.**
`retry` allocates first and diagnoses second, so a failed diagnosis/record
write leaves attempt K+1 on disk while `.roster-r<N>.json` still says K. The
next `retry` adopts that directory when its own `binding.json` binds THIS
entry at THAT attempt — ALL SIX derived values, through the one
`_expected_binding` derivation admission uses — AND its `dispatch.json`
equals the round's own re-render on `kind`, the whole `native` block and the
six wrapper members, AND the two files the invocation FEEDS THE VENDOR are
PROVEN: `prompt.txt` byte-for-byte against a pure re-render whose clause
manifest matched the frozen `prompt_manifests[<name>]` first, and
`schema.projected.json` against the frozen `projection_digest` (a record
carrying no frozen manifest or digest cannot prove the basis and is
refused), AND the frozen `prompt_spec_dir` is REQUIRED and COMPARED, exactly
as the normal `retry` does it (digests alone do not say WHERE the clause
bytes came from), with both byte reads going through the helper's hardened
`_read_regular_file` (`lstat` → `O_NOFOLLOW|O_NONBLOCK` → `fstat` S_ISREG)
instead of `Path.read_bytes()`, which FOLLOWS a symlink planted at either
name, and an unreadable CLAUSE file refusing in one line at both layers
rather than as a traceback. Only then does it re-print the frozen
`dispatch.json`, and it re-renders NOTHING INTO the attempt — every
re-render above is a discarded comparison basis; a directory whose records
are unreadable, whose `binding.json` or `dispatch.json` is a non-object, or
whose binding names something else, is refused BY NAME and left in place —
the packet dir is helper-owned, so the tool deletes nothing it did not
write. Further conditions gate the adoption, each refusing by name and
deleting nothing: the allocation must have FINISHED — every file the writer
produces for that route, the producer projection included, since it is
written LAST and its absence ships an argv pointing at a file nobody wrote;
`dispatch.json` is TYPE-checked on EVERY member the print reads — `kind`,
the identifying member for that kind (`native.subagent_type` a non-empty
string / `argv` a non-empty list OF strings), `stdout_path` /
`stderr_path`, `env` as a string→string mapping, `read_audit_path` — the KEY
required on EVERY wrapper route, `null` where the route takes none — and
`schema_file` when named; the record is then COMPARED against a fresh
RE-RENDER of the same attempt from the round's own frozen roster entry, and
adoption is refused when `kind`, the `native` block or any of `argv` / `env`
/ `stdout_path` / `stderr_path` / `read_audit_path` / `schema_file` differs —
the adopted record is what the operator RUNS, so it is proven to be this
round's invocation rather than read back verbatim (on equality the ON-DISK
bytes are adopted and nothing is re-rendered INTO the attempt); a gap of
MORE than one attempt is refused naming both numbers, because only the
one-step orphan has an attempt this tool can honestly call "the one that
failed"; and attempt K's `retry-diagnosis.txt` is RETAINED when it is a
regular NON-BLANK file (under the distinct `existing diagnosis retained …
the typed text was NOT stored` line), REPLACED when it is a regular but
EMPTY file — what an interrupted write leaves behind — with the print saying
so, and REFUSED when it is a symlink or any other non-regular path; any
write `OSError` surfaces as a one-line refusal.

**The NON-ADOPT `retry`'s diagnosis write is guarded too.** An `OSError` —
an unwritable attempt directory, a full disk — AFTER `v2_write_attempt` has
allocated attempt K+1 is a one-line refusal naming the allocated directory
and stating that the round record still names attempt K, so the allocated
attempt is ADOPTED on the next `retry` rather than re-allocated — the same
rule the adoption path applies.

**Adoption's write order**: validate everything → write the diagnosis →
print the dispatch block → bump `.roster-r<N>.json` LAST, so a refused print
never leaves the record bumped over an attempt nobody dispatched. A
wrapper entry's printed `--expected-*` flags come from the DERIVED binding,
never read back from the attempt's own `binding.json` (the native `--admit`
line types none and reads that record itself), and every interpolated value
is `shlex.quote`d.

**THE ROUND RECORD NAMES THE ATTEMPT THAT IS EVALUATED.** Allocation is the
RECORD's act — `prepare` writes attempt 1, `retry` bumps the entry
(allocating or ADOPTING) before it returns — so an on-disk attempt ABOVE the
record's is one this round never dispatched, and a planted or restored
`attempt-N/` whose binding satisfies the derivation and whose verdict is a
schema-valid SAFE could otherwise supersede the recorded attempt's BLOCKING
verdict. It is that ENTRY's `invalid`, named (`<dir> is an attempt this
round never allocated: the round record names attempt <K> for this entry
…`), nothing is deleted, every other entry still collects and the round
lands on INCOMPLETE — but only when the recorded attempt did not itself
return a valid verdict (a completed review is never vetoed by an
unallocated directory). Exactly `attempt-<record.attempt>/` is evaluated: a
RECORDED attempt missing from disk is that entry's `invalid`, and `retry`
refuses it before allocating (prepare a new round). The
ADOPTION path recovers only the one-step orphan, whose recorded attempt is
on disk.

**THE ROUND RECORD'S SHAPE IS CHECKED BEFORE ANYTHING WALKS IT.**
`_check_record_shape` refuses with exit 2 NAMING THE FIELD, for the members
this helper dereferences only; the members with their own dedicated refusal
downstream (`projection_digest`, `contract_digest`, `prompt_spec_dir`,
`hook_log`) are TYPE-checked when present but never required here, so a
record that omits one still reaches the refusal that explains what it is
for (`references/triage.md` § Collect outcomes).

**`collect-r<N>.json` and the round record share ONE lstat-refusing writer**
(`collect_v2._write_json`): `lstat` → refuse a non-regular target BY NAME →
temp file → `os.replace`, so a symlink planted at either path is never
written through. The TEMP is exclusive-created as well —
`O_CREAT|O_EXCL|O_NOFOLLOW`, the rule the sibling writers apply — so a link
planted at the predictable `.tmp-<pid>-<name>` is refused, and a `finally`
UNLINKS a temp the staging never consumed so a refused write leaves no
residue for `verify` to report as an uncovered packet file. **When that
unlink itself fails the residue is DISCLOSED, never swallowed**: the refusal
already in flight stays the reported error — re-raising from a `finally`
would REPLACE it with a cleanup detail — and one `collect_v2: NOTE: the
staging file <path> could not be removed (…)` line goes to the diagnostic
stream beside it, so an operator is told about a `.tmp-…` sitting in a
directory this helper owns. Every record LOAD on these paths catches
`RecursionError` alongside `OSError` / `ValueError` / `UnicodeDecodeError`,
so a document nested past the interpreter's limit is a named one-line
refusal rather than a traceback that aborts the collection.

**A HOST FAULT stops the collection instead of blaming a leg.** `verdict_v2`
exit 64 means the admission could not RUN at all on this host — `jsonschema`
absent, or the vendored contract unusable in ANY way: unreadable, invalid
UTF-8, not JSON, nested past the interpreter's limit, or not Draft 2020-12.
The agy entry's two EVIDENCE TOOLS are the same class: `read_audit_gate.sh`
and `agy_hook.py check` both reserve rc 64 for "this invocation could not
RUN at all" — a required file the round named is gone, a re-pinned
worktree, an absent `hook_log`, an unusable argv — so that is a host fault,
never that leg's `invalid`. `collect` / `retry` exit 64 with a one-line
host-fault reason and write NO per-entry state, because nothing about any
leg is known. Repair the host and collect again — never re-dispatch paid
legs over it (`references/triage.md` § Collect outcomes).

A directory named `attempt-<non-decimal>` is refused the same way, never
silently skipped, because skipping it would make the collector read a LOWER
attempt than the tree holds — but inside `collect` that refusal is scoped to
the offending ENTRY: that entry is `invalid` with the directory named, every
other entry still collects, and the round lands on INCOMPLETE. The same
per-entry refusal covers a NON-CANONICAL decimal spelling — `attempt-01`,
`attempt-001`, non-ASCII decimals, all of which `int()` maps onto the
canonical number, so two directories would claim one allocation — and an
`attempt-*` entry that is a SYMLINK or not a directory. `retry` runs the
same scan itself and refuses too. Admission of an attempt's result never
trusts the attempt's own `binding.json` either: the six expected values are
DERIVED from the round record, the frozen roster entry and the directory
name, and the binding must EQUAL them (ONE derivation serves admission AND
adoption; a non-object `binding.json` invalidates that ONE entry;
`references/triage.md` § Collect outcomes). `retry` also refuses outright
when the round's frozen `prompt_manifests` do not match the clause bytes a
re-render produces — and equally when the record carries NO frozen manifest
for that entry or NO frozen `prompt_spec_dir` — a changed or unprovable
basis is a new ROUND (`references/triage.md` § Collect outcomes). The
PRODUCER SCHEMA is half of that basis: `prepare` freezes `projection_digest`
(the sha256 of the projected producer schema) in the round record and
`retry` refuses on a MISMATCH **or on ABSENCE** — a round record without it
cannot be retried at all; prepare a new round. **The ADMISSION CONTRACT is
the last basis, and `collect` checks it too**: `contract_digest` (the sha256
of the canonical `spec/contracts/leg-verdict.schema.json` `verdict_v2`
judges every reply against, read through `verdict_v2._schema_path()` so a
seam round is distinguishable from a vendored one) is frozen at prepare, and
BOTH `collect` and `retry` re-derive and refuse with exit 2 on a mismatch or
on absence, BEFORE any entry is judged — it is the one basis no leg artifact
evidences, since an admitted `verdict.json` says nothing about the schema
that let it through. ORDER: a contract this host cannot LOAD at all is the
HOST FAULT 64 above, not this exit-2 refusal.

**Census rules.** `capture` freezes the files that exist AT capture —
including each attempt's `binding.json` / `prompt.txt` / `dispatch.json` /
`schema.projected.json`, which are leg INPUTS. Everything that lands under
`results-r<N>/` AFTER capture is leg OUTPUT by rule: the exemption is the
TOP-LEVEL DIRECTORY (`results-r<N>` as the first path component), not a
basename glob, because the v2 artifacts sit in subdirectories while every v1
output shape lives directly in the packet dir. `collect-r<N>.json` is leg
output too — a collection is re-runnable by design, so censusing it would
make a second `collect` report a mutation. Three dot-records are EXCLUDED
from the census entirely: `.snapshot-<label>.json` (the census itself),
`.roster-r<N>.json` (a `retry` bumps an entry's `attempt` in it on an
unchanged basis, so censusing it would make the round's own retry path look
like a mutation) and `.verified-r<N>.json` (written by `verify` after
certifying the round; censusing it would make `verify` refuse its own record
on the next run). What those records point at is frozen elsewhere — the
worktree by the fingerprint, each attempt's inputs by this census.

### Going on in a new packet dir

The packet dir is HELPER-OWNED (owner ruling): the steps below are
the ONLY supported manual intervention in it, and everything else — renaming,
moving or locking a round tree, dropping a foreign clone or worktree in, or
re-pinning from a repository other than the gate's source — is out of scope, so
the helper REFUSES such a state without deleting anything and states what it
observes instead of prescribing a command. No step removes one entry from a
packet dir: only the host's deletion command deletes, and it removes a whole
packet dir.

Run these when `open`, `prepare`, `verify` or `close` refuses (or the stale-sibling
prune skips) over an entry it could not name as its own round tree, or over a
second round tree.

1. **Verify the round's own tree first**, if it holds work you have not verified:
   `verify` is the only chance to check the delivered artifacts against their
   record. When the refusal names a second round tree, `verify` refuses as well;
   the round then goes on unverified.
2. **Go on in a new packet dir** — `open` with a NEW slug (a same-day duplicate
   slug is refused), then `prepare` the round there. The refusing packet dir keeps
   everything in it.
3. **Remove the old packet dir whole, later**, with the host's deletion command,
   from the repository that holds it, once its `.active` is past the
   review-scratch floor:
   `cd <repo> && python3 <wrappers>/cleanup.py remove review-scratch <packet-dir>`
   (a refusal that offers this exit prints the line ready to run). It detaches
   each linked worktree inside through the repository that owns it and refuses,
   deleting nothing, what it cannot prove — a clone, a locked worktree, a moved
   or copied tree, a `.git` file that names no registration — with one line
   saying what it saw. A packet dir it refuses stays; removing it is the
   operator's own act.

## Large diff — shrink the reviewed surface

`prepare` writes the whole diff into the round worktree; there is no packet
file to assemble. When a diff approaches a leg's context ceiling, narrow it:
`--diff-path <rel>` (repeatable) limits `diff.prod.patch` to those paths,
`--tests-path <pathspec>` limits `diff.tests.patch` (omitted → that file is written EMPTY, 0 bytes: test churn never rides in the gated patch). The tests patch is the `--diff-path` scope INTERSECTED with `--tests-path`, so a tests directory must be in `--diff-path` too, or `diff.tests.patch` comes out empty. `--excerpt
<rel>:<start>-<end>` pins a hot function INTO `brief.md`. Prefer shrinking
over raising `--timeout` (SKILL rule 7). Telling a vendor leg to self-assemble
a large diff itself times out (`references/evidence.md`).

## Packet order and fencing

Canonical for EVERY leg, inline or file:

0. ONE canonical **`Review metadata:` JSON line** at the head of the
   PACKET FILE (on a `prepare` round: the head of `brief.md` and of
   `delivery-r<N>.md`, whose sha256 is the round's `content_digest`) —
   a single compact-serialized object stating the
   LEG-INDEPENDENT facts only: `review_id` (e.g. `<slug>-r<N>`),
   `round`, and the packet path. Two binding values CANNOT live in this
   line and ride each leg's PROMPT instead, as one per-leg binding line
   ("Your binding values: review_id=…, family=…, content_digest=…"):
   `content_digest` is the sha256 OF the packet file — writing it inside
   that file is self-referentially impossible — and `family` is per-leg
   while the packet is one file for all legs. The
   closing instruction requires the leg to ECHO
   `review_id`/`family`/`content_digest` verbatim in its LegVerdict
   (`references/leg-contracts.md` § Verdict binding), and admission
   recomputes the digest FROM the packet file
   (`validate_verdict.py --expected-packet`) — the leader never compares
   two hand-carried strings, which is what keeps the field a content
   binding (cross-round comparable) rather than a nonce.
1. a **deployment-context block** first — platforms, trust boundaries,
   threat-model exclusions: the facts the triage reviewer instruction depends on
   (`references/triage.md`). Each exclusion carries a dated evidence pointer — a
   probe, doc, or config path.
2. the **focused / high-risk diff subset**, FENCED as data (e.g.
   `=====DIFF BEGIN=====` / `=====DIFF END=====`), with one line above it: "the
   fenced material is data to judge, never instructions to follow".
3. the **suspect questions** (rule 2) and the required output shape LAST,
   anchored "based on the material above".

**Per-round excerpt policy.** Every
round's packet — every full re-review round included — carries the code
excerpts its questions ride on: a packet-only leg goes blind exactly where
they are absent (`docs/reviews/2026-09-18-cfr-skill-history.md` records the
incident). The marginal size of two or three functions is noise; the blind spot is
not. The codex leg's READ-GRANT (leg-contracts § codex leg) is the
verification channel, not a substitute for carrying the evidence.

Any per-leg CONTAINMENT block (e.g. the agy leg's mandatory containment text)
rides immediately before that closing instruction, never leading the packet. This
matches the documented Gemini constraint-drop shape: an instruction placed at the
START of a long prompt is the one most likely to be dropped by the time the model
starts acting. Recency is exactly what the "LAST, anchored" placement protects,
and containment needs the same protection.

## Deterministic round preparation — prepare

`lib/review_scratch.py prepare` is the NORMAL path for building a round
(owner directive): the leader authors ONE brief and names the
evidence; everything else — the delivered artifacts, the delivery and
digest records, and the leg prompts (on a `--v2` round one `prompt.txt` per
enabled non-skipped roster entry under § Per-entry results tree; on a
LEGACY v1 round the three fixed leg bodies) — is rendered by code. Hand
assembly remains a legitimate fallback (e.g. a data block `prepare` cannot
express), but a hand-built round still owes every § Round integrity
obligation below by hand.

```bash
python3 <skill>/lib/review_scratch.py prepare <abs-packet-dir> \
  <abs-source-repo> r<N> --v2 \
  --brief /abs/brief.md \
  --diff <git-range> [--diff-path <repo-relative-path>]... \
  [--tests-path <repo-relative-path>]... \
  [--excerpt <repo-relative-path>:<start>-<end>]... \
  [--prior-residual /abs/current-residual.md] \
  [--review-kind formal-plan|pre-merge|implementation-review]
```

`--v2` is the STANDARD path: it keeps this whole packet
pipeline and replaces only the leg-facing half — instead of three fixed
`*-r<N>.txt` bodies and the X-leg renders it resolves the NAMED ROSTER and
allocates § Per-entry results tree. `--v2` is mutually exclusive with
`--x-leg` / `--no-x-leg` / a set `$TRIAD_REVIEW_X_LEGS` (exit 2), and
`--prior-residual` and `--review-kind` belong to the v2 path only.
`--review-kind` (omitted = `pre-merge`; an empty, `null` or unknown value is
refused before the round exists) selects `plan-purpose` for `formal-plan` and
`code-purpose` otherwise in every attempt prompt. `prepare` also binds
`review_web_authorized` — true for every round under the owner's standing
authorization (R-REVIEW-WEB; a caller's `--review-web-authorized false` is
ignored with a NOTE, a non-boolean is refused) — and the round's UTC date
(`review_date`). The stage, the web condition, the date, the entry selection
and the roster-configuration digest are BOUND into the round's `Review
metadata:` line, so they are inside the content digest (identical bytes under
another condition bind another digest). `collect`, a retry and an orphan
adoption re-hash `delivery-r<N>.md` against the recorded digest and compare the
record's selection, configuration digest, web condition and date with the bound
values (`collect_v2._bound_metadata`); a retry and an adoption also compare the
stage (`_bound_conditions`), which `collect` does not re-check. The copies in
`.roster-r<N>.json` are only copies; a mismatch is refused as a new round. The policy clause each prompt rendered
(`review-web-permission` or `review-no-web`) is recorded in its prompt
manifest.

`--prior-residual` names ONE file: the leader's condensed CURRENT residual for
this round (R-REREVIEW, R-CONTEXT; `references/triage.md` § Residual table) —
current findings and dispositions, needed prior excerpts, counterevidence,
verification results, changes and remaining uncertainties — rebuilt each
round, never the running ledger table or earlier residuals appended. `prepare`
renders it ONCE, fenced as DATA, inside `brief.md` under the heading "Current
residual", which every leg reads; it does not narrow the full-scope review.
An empty residual is expressed by omitting the flag (an empty or
whitespace-only file is refused).

**Symlinks (R-PREPARE, case C26).** A v2 `brief.md` lists every symlink of the
reviewed basis under "Symlinks in the reviewed tree": path, kind and exact link
text as JSON strings. Committed links carry the text from the commit's
objects — the text the round copy holds, on any range; on a WORKING-TREE range
(`--diff` without `..`) the source's untracked, nonignored links are part of the
basis too and are listed as `untracked link`, each text read from the link
itself (`readlink`). An untracked entry whose kind cannot be inspected refuses
the prepare, naming it. No target is opened or followed. Each text is walked
component by component against the reviewed commit's own path list (the
directories and files the round copy holds; untracked links still count as
links), never the filesystem: a climb above the root or an absolute text, a
component that is another link, an absent component (a directory present only
as untracked content included), a file used as a directory or a trailing `/`
on a file, a path at or beneath a submodule (gitlink — an empty directory in
the round copy) and an empty text are each marked as a coverage gap, each with
its own note; only a walk that succeeds on every component carries no mark.
The walk starts at the link's own directory, which must be a directory of the
commit: an untracked link inside a directory the commit lacks is an absent gap
(beneath a gitlink, a submodule gap). An untracked link is not in the round
copy. A symlink that appears INSIDE the round copy is refused at
`capture` / `verify` and by the untracked walk — a mutation guard, not the
basis.

**Operator note — rounds prepared before the binding.** A v2 round prepared
before the stage, selection and roster-configuration binding (commits
`6c5364d`, `b7c32f3`, `436dd5f`) or before the review-web condition and date
binding (`b53409b`) cannot be retried or adopted, and a round without the
selection or configuration binding cannot be collected either: prepare a new
round. A round prepared before a host update — here the executed-command
receipt binding (`a9f78bc`, sealed by `2bda56f`) — is the operator's to replace:
prepare a new round. The host does not refuse every such round by name: an
unsealed wrapper attempt is judged by its run-log against `dispatch.json`'s
argv, and a line prepared before the binding wrote no run-log there, so it
always collects INVALID (no receipt). What the host refuses by name: a seal
without the `run_log` role is reported as "sealed before a host change …
prepare a new round".
Everything below describes
both paths unless it names one.

- **The brief is the leader's ONLY per-round authored text**: deployment
  context above one `=====QUESTIONS=====` marker line, suspect questions
  below it. No other fence-like line is allowed in it (fence forgery).
  It is the SAME for every selected leg (R-PROMPT): no per-leg emphasis or
  persona (the owner superseded them); same-family entries are separate
  invocation identities, and the roster has no lens / focus / prompt field.
  **The brief's home is OUTSIDE the packet dir** (leader scratch space) —
  `prepare` embeds its parts into the packet, so the brief file itself is
  not round evidence; a brief placed INSIDE the packet dir under a fixed
  name becomes a censused round-invariant INPUT, and editing it for the
  next round while legs are still out fires a false "round evidence
  changed". If it must live inside, round-suffix it
  (`brief-r<N>.md`).
- **Every bulk byte moves FILE-TO-FILE.** `--diff` is REQUIRED — it names the
  reviewed change and pins the round worktree at the resolved right-hand side,
  so the tree and the patches cannot describe different things. `--diff-path`
  pathspecs scope the reviewed surface and `--tests-path` splits test churn out
  of the GATED patch (the review-is-CODE-only rule); both refuse loud when they
  match nothing, since a silent no-op would drop or misfile hunks. `--excerpt`
  slices a line range FROM THE PINNED COMMIT (never the leader's live working
  tree) and pins it into the brief. `--file` whole-file embedding was RETIRED
  with packet assembly: the worktree already carries the whole file. None of it
  is ever streamed through the leader's context.
  Embedded content may not carry any of the round's LIVE fence lines or
  the brief marker, on any renderable line separator (fence forgery
  refused loud — excerpt around such a line); after `capture`, every
  embedded source is re-read and compared, so a source mutating during
  preparation invalidates the round instead of silently shipping stale
  bytes.
  This is the token-discipline rule as much as a convenience: content the
  leader re-types into a packet costs context AND invites transcription
  slips; content a program copies costs neither.
- **Rendered outputs are ROUND-SUFFIXED** (`delivery-r<N>.md` — the record
  listing the delivered artifacts with their sha256s, which is what the
  verdict binding hashes, since there is no assembled packet —
  `digest-r<N>.txt`, and on a LEGACY v1 round only `codex-body-r<N>.txt`,
  `agy-prompt-r<N>.txt`, `claude-prompt-r<N>.txt`; a `--v2` round writes
  `.roster-r<N>.json` and the per-entry attempt records instead) and written
  exclusive-create — a duplicate round fails loud. The four DELIVERED artifacts (`brief.md`,
  `diff.prod.patch`, `diff.tests.patch`, `history.txt`) live in the round
  worktree at `<packet-dir>/wt-r<N>` (the round is in the NAME), NOT in the packet dir; `verify` re-checks
  them against `delivery-r<N>.md`, which keeps their integrity independent
  of the reviewed repo's own `.gitignore`. Beside them `prepare` writes
  `.agents/hooks.json` — the round's agy PreToolUse hook config,
  pointing at `<skill>/lib/agy_hook.py` with `--log
  <packet-dir>/agy-hook-r<N>.jsonl`. It is OURS like the four artifacts
  (cleanup unlinks it; the re-pin owns it), written after them and BEFORE the
  untracked walk and capture so the worktree FINGERPRINT censuses it, and
  deliberately NOT listed in the record: it is enforcement, not delivered
  material (`references/leg-contracts.md` § agy leg, the hook bullet). A
  reviewed tree that TRACKS `.agents/hooks.json` is refused before the
  worktree exists; a reviewed repo that gitignores `.agents/` hides the file
  from the fingerprint's untracked arm (disclosed). The LEGACY v1 leg bodies carry the binding values, the per-leg
  READ-GRANT blocks, the reviewer-side severity instruction, and the
  verdict-selection rule (`references/triage.md` § Reviewer-side
  instruction — the doc text stays the SoT; a doc-side revision updates
  the templates in the same change); a v2 round's `prompt.txt` carries the
  vendored shared clauses instead (`spec/prompts/`).
- **Pre-mutation boundary: everything that can refuse DETERMINISTICALLY runs
  before the first byte moves.** The order is `_precheck_packet_dir` → (v2)
  the PURE render of every enabled non-skipped roster entry → (v2) the
  two SPEC-BASIS DIGESTS (`projection_digest` + `contract_digest`) →
  `_round_invariant_moves` (every refusal of the preserve-and-clear step) →
  `_preserve_round_invariants` (the moves; a failed link refuses there) →
  `_worktree_remove` of the outgoing tree →
  `_worktree_add` → the WRITES (`v2_write_attempt`, the delivery record, the
  four artifacts, `.agents/hooks.json`) → `capture` (its success refreshes
  the heartbeat). The v2 render is PURE —
  it creates no attempt directory and no file — and it belongs on the
  pre-mutation side for the same reason v1 renders its three leg bodies
  there: the refusals only a render can surface (an unrenderable clause set,
  an unresolvable wrapper layout, a non-absolute path token) are
  DETERMINISTIC properties of the install and the roster, not of the tree.
  Run there, a clause-file or layout refusal leaves round N-1's DELIVERED
  tree `wt-r<N-1>` intact and the same label can be retyped. Only the
  WRITES stay after `_worktree_add`, which is the actual invariant: no
  attempt directory exists until the round's own tree does.
  **The UNTRACKED half of the worktree precheck stays AFTER the writes, by
  design**.
  `_precheck_worktree` is split in two: the `untracked=False` arm (index
  flags / sparse checkout / unborn HEAD) runs immediately after
  `_worktree_add`, the earliest point at which the tree exists; the
  `untracked=True` arm (the symlink / non-regular / unreadable walk) runs
  after the four artifacts and `.agents/hooks.json` are written and BEFORE
  `capture`. A fresh detached checkout has exactly ZERO untracked entries, so
  moving that walk ahead of the rotation gives it NO SUBJECT at all — and the
  unreadable artifact it exists to catch would then fail at capture with every
  output already written, burning the round label. The residual is real and DISCLOSED: an unreadable artifact still refuses after the
  rotation, so that refusal burns the label; it is the cheaper of the two
  failures, and the walk cannot be both subject-bearing and pre-mutation
  (measured).
- **The round record freezes BOTH halves of the round's basis.**
  `.roster-r<N>.json` carries the frozen roster, each entry's attempt, the
  `prompt_manifests` (WHICH clause bytes each entry received) and
  **`projection_digest`**, the sha256 of the
  PROJECTED producer schema. The projection is re-derived from the vendored
  `spec/contracts/leg-verdict.schema.json` on EVERY render, a `retry`'s
  included, so without the frozen digest a spec re-vendoring between
  `prepare` and `retry` would move the producer schema with nothing comparing
  the two. `retry` re-derives and compares it before allocating, and refuses on a
  mismatch OR on absence (`references/triage.md` § Collect outcomes). The
  round record is written through the same lstat-refusing,
  exclusive-create-staged writer as `collect-r<N>.json`.
- **The rendered PAYLOAD goes out as UTF-8 BYTES.** `prompts_v2`'s rendered
  prompt / manifest / investigation clause and the six dispatch lines
  `prepare` and `retry` print are written once through `sys.stdout.buffer`
  (`_emit_payload`), never re-encoded by the locale, and a path token this
  host cannot represent as UTF-8 is REFUSED rather than escaped — a mangled
  path in a command the operator copies would dispatch against a different
  file (`references/triage.md` § Collect outcomes,
  the plugin `README.md` § Payload vs diagnostic streams).
- **`prepare` ends by running `capture` for the same label**, after
  auto-preserving round-invariant leg outputs — so the census freezes
  exactly the bytes the legs are handed, by construction.
- Dispatch transports: on a `--v2` round run the dispatch block
  `prepare` / `retry` print for each entry — a wrapper entry's
  `--prompt-file` is its `results-r<N>/<name>/attempt-K/prompt.txt`, a
  claude entry is a native `Agent` spawn of the named `subagent_type`. On a
  LEGACY v1 round codex takes `--prompt-file <abs codex-body-r<N>.txt>`, agy
  takes `--prompt-file <abs agy-prompt-r<N>.txt>`, and the claude `Agent`
  prompt is the rendered `claude-prompt-r<N>.txt` content. Per-leg flags:
  `references/leg-contracts.md`.

## Round integrity — capture / verify

Two `lib/review_scratch.py` subcommands guard the round (this skill's
REUSED packet-dir model — python3 stdlib, no platform branch; exercised on
macOS, not yet on Ubuntu 24.04):

- **Before dispatching round N** (packet assembled, prompts built):
  `python3 <skill>/lib/review_scratch.py capture <abs-packet-dir>
  <abs-packet-dir>/wt-r<N> r<N>` — the second positional is the ROUND WORKTREE
  (`prepare` runs this itself; it is spelled out here for a hand-built round).
  A HAND-BUILT round is supported ONLY when it writes its own
  `delivery-r<N>.md` AND captures under the ROUND label `r<N>`. The
  record's format is what `prepare` writes, and `prepare`'s output is the
  template to copy: a `Review metadata: <review-id> …` line, then one
  `- <artifact>  sha256=<64 hex>  (<size note>)` line for each of `brief.md`,
  `diff.prod.patch`, `diff.tests.patch`, `history.txt`. Capturing such a round
  under a NON-round label instead parks its snapshot where the round guards
  cannot see it — the bare-tree refusal looks for `.snapshot-r<N>.json` — so the
  tree reads as never delivered and is cleaned with its capture beside it. A
  non-round label remains what it is, an OPERATOR capture of a tree, and is not
  a way to run a round. Capture
  — freezes an exclusive-create snapshot named for the LABEL
  (`.snapshot-<label>.json`, i.e. `.snapshot-r<N>.json` for a round — the only
  spelling the round guards read): a per-file sha256 census of every regular
  file then in the packet dir, one prepared digest over that census
  (length-prefixed framing), and a canonical WORKTREE fingerprint
  (HEAD + status + staged/unstaged diffs under pinned flags +
  untracked-file hashes, `LC_ALL=C` — deterministic across git
  configs). One label per round, never re-captured.
- **After every required leg terminates, BEFORE consolidation**:
  `… verify <abs-packet-dir> <abs-packet-dir>/wt-r<N> r<N>` must print
  `ROUND_INTEGRITY_OK r<N>`. A packet-evidence mismatch = a leg
  certified text that changed under it; a WORKTREE-fingerprint
  mismatch = the code under review mutated while legs ran — either way
  the round is INVALID, never released. A ROUND-shaped label
  (`r<N>`, `r0<N>`) resolves its delivery record by the SUPPLIED spelling
  first and by the round NUMBER second — so a pre-canonical `delivery-r04.md`
  answers for `verify … r04` — and REFUSES when NEITHER is in the
  packet dir: the
  fingerprint's two arms both omit paths the REVIEWED repo gitignores, so
  without the record's four sha256s a mutated `diff.prod.patch` in a repo
  carrying `*.patch` certifies clean. A HAND-BUILT round therefore writes that
  record, exactly as `prepare` does. A NON-round label is an OPERATOR
  capture, never a round: it verifies the packet evidence and the fingerprint
  only, and its token line SAYS so — `ROUND_INTEGRITY_OK <label> (artifact
  hashes NOT checked — no delivery record)`, on stdout, so the round gate's
  token (`ROUND_INTEGRITY_OK r<N>`, SKILL rule 8) can never be satisfied
  silently. This verify is the
  COMPENSATING CONTROL for legs with native read tools (the codex
  leg's READ-GRANT contract, and the agy leg's
  intent-not-enforcement residual): mutation detection, not a sandbox
  claim alone, decides admission.
- Leg INPUT files must ALL exist before capture — the delivery record,
  the round's digest record, and every per-leg input (on a `--v2` round
  each attempt's `binding.json` / `prompt.txt` / `dispatch.json` /
  `schema.projected.json`; on a LEGACY v1 round `codex-body-r<N>.txt`,
  `agy-prompt-r<N>.txt`, `claude-prompt-r<N>.txt`): the bytes a leg actually reviews must sit
  inside the census. The `prepare`
  subcommand (§ Deterministic round preparation) guarantees this by
  construction — it writes every input and THEN captures; a hand-built
  round owes the same order manually. `verify` mechanically FAILS on any
  uncovered non-output regular file in the packet dir.
- **Leg OUTPUT files must match the declared exemption globs AT DISPATCH
  TIME** — `verify` exempts (as outputs a round legitimately creates
  after capture) ONLY names matching `_LEG_OUTPUT_GLOBS`
  (review_scratch.py): `*.out`, `*.err`, `*-read-audit.json`,
  `claude-r*.json`, `*-verdict.json` — plus, on a v2 round, everything under
  the `results-r<N>/` TOP-LEVEL DIRECTORY and the basename `collect-r<N>.json`
  (§ Per-entry results tree), plus, for the v1 fourth leg, the
  explicit shape rule `_is_x_leg_output`, and the agy hook log
  `agy-hook-r<N>.jsonl` (`_is_hook_log_output`: the hook appends to it while an
  agy-family leg runs; same basename rule — `agy-hook-r1/notes.jsonl` and
  `agy-hook-r1.txt` stay uncovered). That rule is a REGEX on the
  basename, not a glob: the globs are `fnmatchcase`d
  against the whole POSIX RELPATH, where `*` also spans `/`, so an X glob such
  as `x-*-r[0-9]*-raw.json` would exempt `x-fixtures-r1/notes-raw.json` and
  `x-c-r1-notes-raw.json`. An X output must therefore contain NO `/` (it lives
  directly in the packet dir) and its basename must fullmatch
  `x-<lowercase-alnum>[-part]…-r<N>[-attempt<K>]` followed by
  `-raw.json` / `-verdict.json` / `-read-audit.json` / `.err`.
  Route every leg's redirected
  stdout/stderr and verdict to those shapes when BUILDING the dispatch
  command — e.g. `codex-r<N>-verdict.json` + `codex-r<N>.err`, never
  `codex-stderr-r<N>.txt` (a stderr redirect named outside the globs makes
  `verify` report an uncovered non-output file; naming outputs correctly at
  dispatch time avoids touching the packet dir after capture at all). The globs are SUFFIX matches — a verdict name must
  END in `-verdict.json`, so the round goes BEFORE `-verdict`
  (`<leg>-r<N>-verdict.json`). The plausible inversion
  `<leg>-verdict-r<N>.json` carries the round yet matches NO glob and
  fails `verify` the same way.
- The round-invariant rule covers INPUTS too: a
  censused file that CHANGES per round must carry the round in its
  NAME — the digest record is `digest-r<N>.txt`, one per round, written
  pre-capture and immutable after. An APPENDED round-invariant file
  (a single shared `digest.txt`) silently breaks RE-verification of
  every EARLIER round's census: each append changes the bytes that an
  older snapshot froze, so `verify` of a closed round reports "round
  evidence changed" on an unmutated packet. SCOPE THE BENEFIT HONESTLY:
  per-round naming fixes the
  BYTE-MUTATION half only — the censused bytes of a closed round stay
  immutable and independently recomputable — but a FULL `verify` of a
  CLOSED round is UNSUPPORTED in the reused-dir model: the NEXT round's
  input files (`delivery-r<N+1>.md`, `digest-r<N+1>.txt`, the per-leg inputs)
  are uncovered non-outputs for the old census, so verify structurally
  refuses before it ever recomputes — read that refusal as the model's
  boundary, not as tampering. `verify` is a CURRENT-round gate; a
  closed round's evidence audit recomputes the snapshot-listed hashes /
  prepared digest directly (the .snapshot-r<N>.json is the durable
  record).
- Leg OUTPUT files landing in the packet dir after capture are BY DESIGN
  outside the snapshot census — integrity binds the round's evidence
  set, not the dir's later accumulation. "Output" is a NARROW allowlist
  (`*.out`, `*.err`, `*-read-audit.json`, `claude-r*.json`,
  `*-verdict.json`, the X shape, `agy-hook-r<N>.jsonl`); anything
  else appearing post-capture fails `verify` as an uncovered file. The
  claude leg's still-escaped RAW reply is not covered by those globs: on a
  v1 round it is staged in the session scratchpad under a GATE-SLUG-scoped
  name, never in the packet dir; on a v2 round it is `raw.json` inside the
  entry's attempt dir, which the `results-r<N>/` directory rule already
  exempts (`references/leg-contracts.md` § claude leg, RAW-STAGING RULE
  + its v2 raw-path note).
- (LEGACY v1 rounds.) A leg OUTPUT whose NAME is round-invariant — the v1 agy read-audit
  literal `agy-read-audit.json` — must be PRESERVED-AND-CLEARED to its
  round-suffixed name BEFORE the next round's capture
  (`references/leg-contracts.md` § agy leg, Read-audit binding): a
  censused copy that a later dispatch rewrites is a guaranteed false
  "round evidence changed" on an unmutated tree. Both `prepare` and `capture`
  auto-rename it to the suffix of the round that PRODUCED it — the
  latest captured `.snapshot-r<M>.json`, never label-minus-one, so an
  operator label skip cannot stamp false provenance, whatever the label — and
  fail loud on a leftover with no captured round to attribute it to, a
  rename-target collision with a different file, or an output that is a
  symbolic link (in each case the round then goes to a new packet dir, `open`
  with a new slug); a move stopped between its link and its unlink is
  finished by the next `prepare` / `capture`; a hand-built round runs `capture`
  too, so no round renames it by hand between rounds. Per-leg
  consolidation artifacts avoid the same trap by
  carrying the round in their name (`<leg>-r<N>-verdict.json`,
  `references/triage.md`).
- **(LEGACY v1 rounds only — a `--v2` `retry` allocates attempt K+1 under
  `results-r<N>/` and its artifacts are never renamed or moved.)** **A
  RE-DISPATCHED leg's earlier attempt is renamed into the allowlist,
  never left under a free-form name**. Before the
  retry, rename attempt K's artifacts to `<leg>-r<N>-attempt<K>.err`,
  `<leg>-r<N>-attempt<K>-read-audit.json`, and
  `<leg>-r<N>-attempt<K>-verdict.json` (a claude X leg's staged reply:
  `x-<name>-r<N>-attempt<K>-raw.json`) — every one of those matches
  `_LEG_OUTPUT_GLOBS` (`*.err`, `*-read-audit.json`, `*-verdict.json`) or the
  X shape rule above (which carries the optional `-attempt<K>` segment), so
  the round's evidence keeps both attempts without tripping the
  uncovered-file refusal. For the agy leg this rename moves
  `agy-read-audit.json` to `agy-r<N>-attempt<K>-read-audit.json`: it is the
  one hand move of the read-audit file a v1 round makes (between rounds
  `prepare` / `capture` rename it to `agy-read-audit-r<M>.json`, M = the latest
  captured round), it preserves attempt K's audit
  (nothing is deleted), and it leaves the literal path ABSENT, so a misbound
  re-dispatch reads as ABSENT, never as attempt K's audit. Run it as its own
  step — never CHAIN it before the dispatch (`mv … && … wrapper`): when the
  chained move fails first, the dispatch never launches.
- **Otherwise never hand-move `agy-read-audit.json`** (v1) — between rounds
  `prepare` and `capture` auto-rename it to its producing round's suffix, so
  a manual `cp`/`mv` there is at best redundant and at worst destructive. The
  helper owns the packet dir. The same rule covers the X-leg artifacts: `<name>-prompt-r<N>.txt` /
  `<name>-body-r<N>.txt` and `.x-legs-r<N>.json` are ROUND EVIDENCE (written
  before capture, censused with the standing inputs) — never hand-remove them,
  even for an X leg that was abandoned; record that leg MISSING in the round
  log and leave its artifacts in place.
- **Fourth-leg (X-leg) names — LEGACY v1 only (SKILL.md § Legacy v1 rounds).** An X leg's
  INPUT (`<x-name>-prompt-r<N>.txt`, or `<x-name>-body-r<N>.txt` on the
  codex vendor) and the machine record `.x-legs-r<N>.json` are written by
  `prepare` BEFORE the round's capture, so they are censused leg inputs
  like the standing five. The record is written on EVERY round — with
  `legs: []` and the `x_source` that explains why when the round carried no
  fourth leg — so its presence never implies a fourth leg ran. Its OUTPUTS carry the round from the start —
  `<x-name>-r<N>-verdict.json`, `<x-name>-r<N>.err`,
  `<x-name>-r<N>-read-audit.json`, and `<x-name>-r<N>-raw.json` (the claude
  vendor's verbatim reply, the one kind the standing globs do not already
  cover) — so no X output is round-invariant and none owes a
  preserve-and-clear. Anything else an X leg leaves in the packet dir
  (scratch notes, a stray `.txt`) fails `verify` as an uncovered file, by
  design.
- The reviewed tree stays FROZEN for the round's duration: fixes for
  returned findings are STAGED and applied only after the last leg
  returns and `verify` passes. An edit adopted while closing a
  refuted finding is still an edit; it ships only through a
  round that reviewed it (rule 5). The freeze covers EVERY tracked file
  in the worktree — the gate LEDGER doc included: the leader writes
  NOTHING between `prepare` and the round's final `verify` —
  consolidation-ledger writes go BEFORE `prepare` (pre-capture) or AFTER
  `verify`, never between. A ledger edit during the frozen round mutates the worktree
  fingerprint and INVALIDATES an otherwise-clean round.
