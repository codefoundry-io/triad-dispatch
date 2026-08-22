# agy long-answer output-file contract (the truncation loophole)

Loaded on demand from `triad-antigravity-dispatch/SKILL.md`. Read this when a
dispatch's answer may exceed ~3KB, or when a call came back
`truncated-answer` (65).

## What agy does to a long answer

agy's print path caps a long answer's content CLI-side — observed around 4KB,
with own-line `<truncated N bytes|lines>` markers; the format strings live in the
agy binary. A long single answer is FOLDED mid-body and the lost text is
preserved NOWHERE agy-side: the wrapper no longer reads agy's own transcript
store at all since the stream-json migration, so there is no fallback recovery
path there either. Behavior is unchanged across that migration.

`write_file` output is NOT subject to the fold — verified with a 24KB file intact
while the chat answer folded.

## The contract

For any dispatch whose answer may exceed ~3KB (review legs, research reports,
multi-section documents):

1. Prompt the worker to WRITE the full deliverable to an **ABSOLUTE path** — a
   leader-chosen file under the dispatch's working area, because agy resolves
   relative paths against its own scratch project rather than `--cwd`, so
   relative paths land in `~/.gemini/antigravity-cli/scratch/` — and to print
   only a one-line confirmation (e.g. `DONE <filename>`) to the chat.
2. The leader reads the file as the deliverable; the chat answer is only a
   completion signal.
3. **Availability caveat.** On agy 1.1.17 the WRAPPER's deny transaction
   denies `write_file(*)` even under `--dangerously-skip-permissions` (probe G,
   2026-08-22 — Deny > dsp; `references/isolation.md` § Containment posture),
   and under agent mode the `triad-readonly-review` allowlist carries no write
   tool at all. So a `--sandbox read-only` dispatch CANNOT write the output
   file — and agy may SELF-REPORT `DONE` either way, so verify arrival, always. The contract
   therefore still REQUIRES the write-capable permissive baseline (`--sandbox`
   omitted, non-hardened) as the reliable path.
4. If a stdout-shaped dispatch comes back `truncated-answer` (65), re-dispatch
   once under this contract instead of plain-retrying.

## Where the contract is unavailable

- **Hardened install** (`TRIAD_WRAPPER_HARDENED=1`): omission auto-upgrades to
  `read-only`, so this contract is unavailable at any agy version — prefer
  ACCEPTING the chat-answer fold. Unsetting `TRIAD_WRAPPER_HARDENED` for the call
  drops the pydantic import gate, makes allowed-roots containment optional
  (containment and audit redaction key off their own env vars, which a hardened
  install sets alongside), and disables the auto-read-only guard itself — the
  control that keeps raw public-install calls from being write-capable by
  omission.
- **The cross-family-review agy leg**: forbidden there by that skill's Hard rule
  7 (READ-only / no-exec containment; not this skill's own rule 7, which governs
  the danger flag). Re-dispatch once read-only asking for a COMPACT verdict
  instead.
