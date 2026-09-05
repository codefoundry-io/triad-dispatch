#!/usr/bin/env bash
# read_audit_gate.sh — the agy read-audit MECHANICAL gate as ONE executable
# helper (triad-cross-family-review; owner approval 2026-08-13, backlog
# record 2026-08-07: the leader re-typed this block inline once per round).
#
# SPEC lives in references/leg-contracts.md § agy read-audit gate (threat
# model, the three semantic rules, the INCONCLUSIVE/VOID release paths).
# This file is the gate's single executable form: the source repo's
# self-tests lift the 3-line jq invocation below VERBATIM with a
# fixed-string grep -A2 on its first line — keep that block's shape and
# variable names stable, and keep it the ONLY site spelling that
# invocation (this comment deliberately does not, or the grep would
# double-match).
#
#   usage: read_audit_gate.sh [--audit-file <abs-path>] <abs-packet-dir> <abs-packet-file> [<abs-packet-file>...]
#
# The digest path is DERIVED from <abs-packet-dir> as the shared literal
# "$PACKET_DIR/agy-read-audit.json" — no env fallback (leg-contracts J1
# anti-drift: an ambient TRIAD_READ_AUDIT_FILE some other shell context
# left exported can never redirect this gate). The optional LEADING
# `--audit-file <abs-path>` (CFR 0.29.2) is the ONE explicit override: an
# experimental X leg (SKILL.md rule 15) writes its own round-suffixed
# `<x-name>-r<N>-read-audit.json`, and the gate reads THAT instead. Still
# argv-only, and narrow: the value must be ABSOLUTE, live DIRECTLY inside
# <abs-packet-dir> (no subdirectory, no symlink resolution), and its basename
# must match `x-<name>-r<N>-read-audit.json` — the STANDING agy-read-audit.json
# is never a legal override. Anything else is a usage error (64).
#
# stdout: one "[gate] <VERDICT> <file>" line per EVALUATED packet file
#   (the ABSENT/symlink refusals evaluate none; the broken-evidence stop
#   evaluates no later file), then the final greppable summary
#   "READ_AUDIT_GATE_<VERDICT> checked=<n> pass=<n> void=<n>
#   inconclusive=<n>[ unevaluated=<n>]" — the unevaluated field appears
#   exactly when some argument was not evaluated, so anchor on the token,
#   never on a four-field-only pattern.
# stderr: operator guidance (the canonical leg-contracts messages).
# exit:  0 PASS (every file matched)
#        2 ABSENT       (no digest file — check the dispatch env FIRST)
#        3 VOID         (>=1 confirmed miss with files_read_omitted == 0)
#        4 INCONCLUSIVE (broken evidence, capped digest, symlinked digest,
#                        or an at-or-over-cap packet path — a prefix
#                        identity the digest cannot confirm)
#       64 usage        (bad argv — incl. a nonexistent packet file: a stale
#                        or mistyped packet name would false-VOID a
#                        compliant leg, so it fails loud here instead)
#
# The verdict is decided by jq_rc + files_read_omitted ONLY; the
# read_attempts diagnostic below is explanatory text, never an input.
# Aggregate precedence INCONCLUSIVE > VOID > PASS is LOAD-BEARING: the
# per-ARGUMENT over-cap refusal can mix with a digest-side VOID in one run
# (only the capped/broken digest states are digest-global).

# Interpreter floor (review r5): under `sh` (dash), `set -o pipefail`
# below dies with status 2 — ALIASING the ABSENT exit — before the
# bash-version guard can run. This line parses in any POSIX shell and
# routes the wrong-interpreter case to the LOUD usage code instead.
[ -n "${BASH_VERSION:-}" ] || { echo "read_audit_gate.sh: must be run with bash (documented invocation: bash <skill>/lib/read_audit_gate.sh ...)" >&2; exit 64; }
set -euo pipefail

# bash-4+ floor — a POLICY floor, not a live-construct guard (review r2
# claude HS, rationale corrected r3 after wave 2 deleted the last bash-4
# construct): the artifact standard is bash 5.x (macOS brew bash ∩
# Ubuntu 24.04 stock), and the r2 hazard class this
# protects against is a future 4+ construct dying mid-run under set -e
# with a status that ALIASES a verdict exit (a bare status-2 death reads
# as ABSENT). Enforce the floor up front on the LOUD usage code instead —
# do not remove this as vestigial when no 4+ construct is present.
if [ "${BASH_VERSINFO[0]:-0}" -lt 4 ]; then
  echo "read_audit_gate.sh: bash >= 4 required (artifact standard is bash 5.x; found ${BASH_VERSION:-unknown})" >&2
  exit 64
fi

usage_die() {
  echo "usage: read_audit_gate.sh [--audit-file <abs-path>] <abs-packet-dir> <abs-packet-file> [<abs-packet-file>...]" >&2
  echo "error: $*" >&2
  exit 64
}

# Optional LEADING `--audit-file <abs-path>` (CFR 0.29.2): an experimental X
# leg (SKILL.md rule 15) writes its OWN round-suffixed read audit
# (`<x-name>-r<N>-read-audit.json`), so the gate must be retargetable. Still
# EXPLICIT and still no env fallback (leg-contracts J1 anti-drift): the value
# comes from argv or the shared literal below, never from the environment.
AUDIT_FILE_OVERRIDE=""
if [ "${1:-}" = "--audit-file" ]; then
  [ "$#" -ge 2 ] || usage_die "--audit-file requires an absolute path"
  AUDIT_FILE_OVERRIDE="$2"
  shift 2
  case "$AUDIT_FILE_OVERRIDE" in /*) : ;; *) usage_die "--audit-file must be an absolute path: $AUDIT_FILE_OVERRIDE" ;; esac
fi

[ "$#" -ge 2 ] || usage_die "need an absolute packet dir and at least one absolute packet file"
PACKET_DIR="$1"
shift
case "$PACKET_DIR" in /*) : ;; *) usage_die "packet dir must be an absolute path: $PACKET_DIR" ;; esac
[ -d "$PACKET_DIR" ] || usage_die "packet dir not found: $PACKET_DIR"

# Override CONTAINMENT + SHAPE (CFR 0.29.2 gate r1): checked here because both
# rules are relative to the now-validated PACKET_DIR.
#   containment — the override must live DIRECTLY in the packet dir (no
#     subdirectory, no path outside it, no symlink resolution): the round's
#     evidence is exactly the census'd packet dir, and an audit read from
#     anywhere else was never frozen by `capture`.
#   X shape — the basename must be an X leg's own round-suffixed audit
#     (`x-<name>-r<N>-read-audit.json`). Containment ALONE cannot tell the
#     STANDING `agy-read-audit.json` from an X audit, so without this the
#     standing Pro-leg evidence could be passed as an X leg's override and
#     produce a false PASS for a leg that read nothing.
if [ -n "$AUDIT_FILE_OVERRIDE" ]; then
  _pkt_norm="${PACKET_DIR%/}"
  case "$AUDIT_FILE_OVERRIDE" in
    "$_pkt_norm"/*) : ;;
    *) usage_die "--audit-file must live inside the packet dir $_pkt_norm (got $AUDIT_FILE_OVERRIDE) — an audit outside the census'd round dir is not this round's evidence" ;;
  esac
  [ "${AUDIT_FILE_OVERRIDE%/*}" = "$_pkt_norm" ] \
    || usage_die "--audit-file must sit DIRECTLY in the packet dir, not in a subdirectory: $AUDIT_FILE_OVERRIDE"
  case "${AUDIT_FILE_OVERRIDE##*/}" in
    x-*-r[0-9]*-read-audit.json) : ;;
    *) usage_die "--audit-file must name an X leg's own round-suffixed audit (x-<name>-r<N>-read-audit.json), got ${AUDIT_FILE_OVERRIDE##*/} — the STANDING agy-read-audit.json is never a legal override (gating an X leg on the standing leg's evidence is a false PASS)" ;;
  esac
fi
for f in "$@"; do
  case "$f" in /*) : ;; *) usage_die "packet file must be an absolute path: $f" ;; esac
  [ -f "$f" ] || usage_die "packet file not found: $f (for a prepare-built round the packet is the ROUND-SUFFIXED packet-r<N>.md; a stale generic name here would false-VOID a compliant leg)"
done

# _CAP = _common.py's _AGY_DIGEST_VALUE_CAP (the digest's own params-value
# truncation) — the helper's ONE cap literal, coupled to that constant; a
# wrapper-side cap change must update it too, or a real match can silently
# false-VOID (the source repo's unit self-test drift-guards the pair AND
# the one-literal property).
_CAP=200

# ONE literal across all THREE sites (leg-contracts J1): the dispatch
# binding, the leader-side pre-clear, and this gate all read/write the SAME
# "$PACKET_DIR/agy-read-audit.json" — byte-identical, no env-var fallback.
AGY_READ_AUDIT_FILE="${AUDIT_FILE_OVERRIDE:-$PACKET_DIR/agy-read-audit.json}"

if [ -h "$AGY_READ_AUDIT_FILE" ]; then
  # Check-then-open symlink refusal — deliberately WEAKER than
  # validate_verdict.py's O_NOFOLLOW read (recorded residual r2-2):
  # acceptable because the gate runs strictly after the agy child is
  # reaped and no other round participant writes this path. A symlink
  # here is a redirect nobody's dispatch bound — refuse it, never follow.
  echo "[review] agy leg read-audit REFUSED — $AGY_READ_AUDIT_FILE is a symlink (the wrapper writes a regular file; a symlink here redirects the gate to bytes nobody bound for this round). Inspect the packet dir; do NOT read this as VOID or PASS." >&2
  echo "READ_AUDIT_GATE_INCONCLUSIVE checked=0 pass=0 void=0 inconclusive=0 unevaluated=$#"
  exit 4
fi

if [ ! -f "$AGY_READ_AUDIT_FILE" ]; then
  # ABSENT is NOT proof the vendor call failed — TRIAD_READ_AUDIT_FILE
  # unset/misbound at dispatch time is empty in exactly the same way as a
  # call that never completed. Check the dispatch env FIRST; only once that
  # is sound does an absent file mean the leg did not run.
  echo "[review] agy leg read-audit ABSENT — no digest file at $AGY_READ_AUDIT_FILE. Cause is EITHER a vendor call that never completed OR TRIAD_READ_AUDIT_FILE was never set at dispatch time. Verify the dispatch env; only once it is sound does this mean the leg did not run — then treat as VOID (leg-not-run) and re-dispatch once." >&2
  echo "READ_AUDIT_GATE_ABSENT checked=0 pass=0 void=0 inconclusive=0 unevaluated=$#"
  exit 2
fi

n_args=$#
checked=0
n_pass=0
n_void=0
n_inconclusive=0

for PACKET_ABS_PATH in "$@"; do
  checked=$((checked + 1))
  # Over-cap refusal (review r2 — codex must-fix ≡ claude Minor, 2-family
  # convergence, replacing r1's narrower arg-census): a path longer than
  # _CAP is stored in the digest as a PREFIX, not an identity — the digest
  # cannot distinguish it from ANY same-prefix file (a colliding sibling
  # argument, a digest-side file that was never an argument, or a stale
  # packet-r<N-1>.md whose ROUND-SUFFIX the cap erases). Refuse to
  # over-claim: INCONCLUSIVE, digest content irrelevant. Within the cap
  # the truncated form IS the full path, so equality is exact — and two
  # DISTINCT within-cap arguments can never share a capped identity, which
  # is why this single check subsumes the retired collision census.
  # (surviving args are strictly under the cap, so the :0:_CAP slice on
  # p_trunc below is an identity — kept deliberately for the lifted
  # block's variable contract and as the cap-coupling site; review r5.)
  if [ "${#PACKET_ABS_PATH}" -ge "$_CAP" ]; then
    echo "[review] agy leg read-audit INCONCLUSIVE — packet path is $_CAP characters or longer, so the capped digest stores only a prefix-identity for it and cannot confirm THIS file (an exactly-cap value could equally be a LONGER path's truncation; vs any same-prefix file, including a stale prior-round packet). Shorten the packet path and re-run the gate." >&2
    echo "[gate] INCONCLUSIVE $PACKET_ABS_PATH"
    n_inconclusive=$((n_inconclusive + 1))
    continue
  fi
  p_trunc="${PACKET_ABS_PATH:0:_CAP}"
  set +e
  jq -e --arg p "$p_trunc" \
    '[.digest.files_read[]? | select(.tool == "view_file") | .params.AbsolutePath? // empty | select(type == "string")] | any(. == $p)' \
    "$AGY_READ_AUDIT_FILE" >/dev/null 2>/dev/null
  jq_rc=$?
  set -e
  if [ "$jq_rc" -ge 2 ]; then
    # jq could not produce a usable answer — a BROKEN reading of the
    # evidence, not evidence. Never silently VOID (or PASS) on it. rc>=2
    # covers every jq failure mode: read, parse, program, or runtime error.
    echo "[review] agy leg read-audit INCONCLUSIVE — jq could not produce a usable answer from $AGY_READ_AUDIT_FILE (rc=$jq_rc: read, parse, program, or runtime error). Do NOT read this as VOID and do NOT read it as PASS: inspect the file directly, then re-dispatch once." >&2
    echo "[gate] INCONCLUSIVE $PACKET_ABS_PATH"
    n_inconclusive=$((n_inconclusive + 1))
    # Parse state is digest-global — further files would fail identically.
    break
  elif [ "$jq_rc" -eq 1 ]; then
    omitted="$(jq -r '.digest.files_read_omitted // 0' "$AGY_READ_AUDIT_FILE" 2>/dev/null)" || omitted=0
    # Diagnostic ONLY: a BLOCKED read lives in read_attempts, not
    # files_read — say whether the leg TRIED. Same tool+key scope as the
    # verdict jq (review r4): a blocked write/run_command — or a blocked
    # read-class grep_search whose Query merely NAMED the packet — is not
    # a failed read of the packet. The VOID/PASS decision is jq_rc +
    # omitted above, never this line — a miss costs explanatory text,
    # never a verdict.
    jq -r --arg p "$p_trunc" \
      '[.digest.read_attempts[]? | select(.class == "read" and .tool == "view_file")
       | select(([.params // {} | objects | .AbsolutePath? // empty
         | select(type == "string")] | any(. == $p)))
       | "\(.tool):\(.outcome)"] | select(length > 0)
       | "[review] agy leg ATTEMPTED but failed to read the packet: \(join(", "))"' \
      "$AGY_READ_AUDIT_FILE" >&2 || true
    if [ "${omitted:-0}" -gt 0 ]; then
      echo "[review] agy leg read-audit INCONCLUSIVE ($omitted files_read entries capped) — weigh read_audit.digest.attempts[] (per-attempt totals) + read_audit.digest.read_attempts[] before voiding; there is no fuller digest and only the FINAL attempt's raw stream is retained, so re-dispatch with a narrower packet if the census does not settle it" >&2
      echo "[gate] INCONCLUSIVE $PACKET_ABS_PATH"
      n_inconclusive=$((n_inconclusive + 1))
    else
      echo "[review] agy leg VOID — packet path not in read_audit.digest.files_read ($PACKET_ABS_PATH); re-dispatch once with the containment block; still VOID after that re-dispatch is terminally missing this round (2-family + owner decision, rule 1 degraded mode — no second re-dispatch)" >&2
      echo "[gate] VOID $PACKET_ABS_PATH"
      n_void=$((n_void + 1))
    fi
  else
    echo "[gate] PASS $PACKET_ABS_PATH"
    n_pass=$((n_pass + 1))
  fi
done

# Counters count EVALUATED files. Whenever any argument was NOT evaluated
# (the broken-evidence break stops the loop; the ABSENT/symlink refusals
# above evaluate none), the summary appends unevaluated=<n> so the token
# and the counters can never disagree silently (review r1, claude Minor 3).
_suffix=""
if [ "$checked" -lt "$n_args" ]; then
  _suffix=" unevaluated=$((n_args - checked))"
fi

if [ "$n_inconclusive" -gt 0 ]; then
  echo "READ_AUDIT_GATE_INCONCLUSIVE checked=$checked pass=$n_pass void=$n_void inconclusive=$n_inconclusive$_suffix"
  exit 4
elif [ "$n_void" -gt 0 ]; then
  echo "READ_AUDIT_GATE_VOID checked=$checked pass=$n_pass void=$n_void inconclusive=$n_inconclusive$_suffix"
  exit 3
fi
echo "READ_AUDIT_GATE_PASS checked=$checked pass=$n_pass void=$n_void inconclusive=$n_inconclusive$_suffix"
exit 0
