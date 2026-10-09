#!/usr/bin/env bash
# read_audit_gate.sh — the agy read-audit MECHANICAL gate (spec:
# references/leg-contracts.md § agy read-audit gate).
#
#   usage: read_audit_gate.sh --audit-file <abs-path> <abs-packet-dir> <abs-packet-file> [<abs-packet-file>...]
#
# stdout: one "[gate] <VERDICT> <file>" line per EVALUATED packet file
#   (the ABSENT refusal evaluates none; the broken-evidence
#   stop evaluates no later file), then
#   the final greppable summary
#   "READ_AUDIT_GATE_<VERDICT> checked=<n> pass=<n> void=<n>
#   inconclusive=<n>[ unevaluated=<n>]" — the unevaluated field appears
#   exactly when some argument was not evaluated, so anchor on the token,
#   never on a four-field-only pattern.
# stderr: operator guidance (the canonical leg-contracts messages).
# exit:  0 PASS (every file matched)
#        2 ABSENT       (no digest file — check the dispatch env FIRST)
#        3 VOID         (>=1 confirmed miss with files_read_omitted == 0)
#        4 INCONCLUSIVE (broken evidence, capped digest, or an
#                        at-or-over-cap packet path — a prefix identity
#                        the digest cannot confirm)
#       64 usage        (bad argv — incl. a nonexistent packet file: a stale
#                        or mistyped packet name would false-VOID a
#                        compliant leg, so it fails loud here instead)
#
# The verdict is decided by jq_rc + files_read_omitted ONLY.
# Aggregate precedence INCONCLUSIVE > VOID > PASS is LOAD-BEARING: the
# per-ARGUMENT over-cap refusal can mix with a digest-side VOID in one run
# (only the capped/broken digest states are digest-global).

# Interpreter floor: under `sh` (dash), `set -o pipefail` below dies with
# status 2 — ALIASING the ABSENT exit. This POSIX `BASH_VERSION` guard runs
# first, parses in any POSIX shell and routes the wrong-interpreter case to
# the LOUD usage code instead.
[ -n "${BASH_VERSION:-}" ] || { echo "read_audit_gate.sh: must be run with bash (documented invocation: bash <skill>/lib/read_audit_gate.sh ...)" >&2; exit 64; }
set -euo pipefail

usage_die() {
  echo "usage: read_audit_gate.sh --audit-file <abs-path> <abs-packet-dir> <abs-packet-file> [<abs-packet-file>...]" >&2
  echo "error: $*" >&2
  exit 64
}

# REQUIRED LEADING `--audit-file <abs-path>`: the attempt's own read audit.
# EXPLICIT and no env fallback (leg-contracts J1 anti-drift): the value comes
# from argv, never from the environment, and there is no default path.
[ "${1:-}" = "--audit-file" ] || usage_die "--audit-file <abs results-r<N>/<name>/attempt-<K>/read-audit.json> is required"
[ "$#" -ge 2 ] || usage_die "--audit-file requires an absolute path"
AUDIT_FILE_OVERRIDE="$2"
shift 2
case "$AUDIT_FILE_OVERRIDE" in /*) : ;; *) usage_die "--audit-file must be an absolute path: $AUDIT_FILE_OVERRIDE" ;; esac

[ "$#" -ge 2 ] || usage_die "need an absolute packet dir and at least one absolute packet file"
PACKET_DIR="$1"
shift
case "$PACKET_DIR" in /*) : ;; *) usage_die "packet dir must be an absolute path: $PACKET_DIR" ;; esac
[ -d "$PACKET_DIR" ] || usage_die "packet dir not found: $PACKET_DIR"

# CONTAINMENT + SHAPE: checked here because both rules are relative to the
# now-validated PACKET_DIR. A round gives every roster entry its own
# immutable `results-r<N>/<name>/attempt-<K>/`, and the agy entry's read audit
# lives there. It is inside the census'd packet dir; the exact four-component
# shape is what keeps "inside the packet dir" from degenerating into
# "anywhere below it" — an audit anywhere else (the packet dir itself, a
# foreign subdirectory, outside it) was never this attempt's evidence. The
# attempt stays a SIBLING of every later attempt of the round, so the remedies
# below say which cases a retry clears and which need a NEW round.
_pkt_norm="${PACKET_DIR%/}"
case "$AUDIT_FILE_OVERRIDE" in
  "$_pkt_norm"/*) : ;;
  *) usage_die "--audit-file must live inside the packet dir $_pkt_norm (got $AUDIT_FILE_OVERRIDE) — an audit outside the census'd round dir is not this round's evidence" ;;
esac
_audit_rel="${AUDIT_FILE_OVERRIDE#"$_pkt_norm"/}"
if ! [[ "$_audit_rel" =~ ^results-r[1-9][0-9]*/[A-Za-z0-9][A-Za-z0-9._-]*/attempt-[1-9][0-9]*/read-audit\.json$ ]]; then
  usage_die "--audit-file must be an attempt's read audit (results-r<N>/<name>/attempt-<K>/read-audit.json): $AUDIT_FILE_OVERRIDE"
fi
for f in "$@"; do
  case "$f" in /*) : ;; *) usage_die "packet file must be an absolute path: $f" ;; esac
  [ -f "$f" ] || usage_die "packet file not found: $f (for a prepare-built round the packet IS the round worktree, so these are its artifacts — <packet-dir>/wt-r<N>/brief.md and <packet-dir>/wt-r<N>/diff.prod.patch; a stale round number or a path from a prior round would false-VOID a compliant leg)"
done

# _CAP = _common.py's _AGY_DIGEST_VALUE_CAP (the digest's own params-value
# truncation) — the helper's ONE cap literal, coupled to that constant; a
# wrapper-side cap change must update it too, or a real match can silently
# false-VOID (the source repo's unit self-test drift-guards the pair AND
# the one-literal property).
_CAP=200

# The dispatch binding (env TRIAD_READ_AUDIT_FILE on the agy dispatch line)
# and this gate name the SAME per-attempt path — no env-var fallback.
AGY_READ_AUDIT_FILE="$AUDIT_FILE_OVERRIDE"

if [ ! -f "$AGY_READ_AUDIT_FILE" ]; then
  # ABSENT is NOT proof the vendor call failed — TRIAD_READ_AUDIT_FILE
  # unset/misbound at dispatch time is empty in exactly the same way as a
  # call that never completed. Check the dispatch env FIRST; only once that
  # is sound does an absent file mean the leg did not run.
  # The remedy is a NEW round, never a re-dispatch inside it (gate-1 r15 row
  # r15-2): the attempt stays a sibling of every later attempt of the round,
  # and the hook load check reads a DISPATCHED attempt with no audit as
  # INCONCLUSIVE — one that never spawned agy is skipped, so a retry does
  # clear that case (row r16-4).
  echo "[review] agy leg read-audit ABSENT — no digest file at $AGY_READ_AUDIT_FILE. Cause is EITHER a vendor call that never completed OR TRIAD_READ_AUDIT_FILE was never set at dispatch time. Verify the dispatch env; only once it is sound does this mean the leg did not run — then treat as VOID (leg-not-run). The attempt stays a SIBLING of every later attempt of this round (a dispatched attempt with no read audit is INCONCLUSIVE in the hook load check, which reads every attempt and deletes none), so a re-dispatch inside the round cannot clear it: prepare a NEW round (a fresh hook log) (if the attempt never spawned agy — no \`exec\` line in its stderr.log — the hook check skips it and a retry does clear it)." >&2
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
    # The remedy is a NEW round (gate-1 r15 row r15-2) — the unreadable audit
    # stays a sibling of every later attempt, INCONCLUSIVE in the hook check.
    echo "[review] agy leg read-audit INCONCLUSIVE — jq could not produce a usable answer from $AGY_READ_AUDIT_FILE (rc=$jq_rc: read, parse, program, or runtime error). Do NOT read this as VOID and do NOT read it as PASS: inspect the file directly. The unreadable audit stays a SIBLING of every later attempt of this round (the hook load check reads it as broken evidence — INCONCLUSIVE — and deletes none), so a re-dispatch inside the round cannot clear it: prepare a NEW round (a fresh hook log)." >&2
    echo "[gate] INCONCLUSIVE $PACKET_ABS_PATH"
    n_inconclusive=$((n_inconclusive + 1))
    # Parse state is digest-global — further files would fail identically.
    break
  elif [ "$jq_rc" -eq 1 ]; then
    omitted="$(jq -r '.digest.files_read_omitted // 0' "$AGY_READ_AUDIT_FILE" 2>/dev/null)" || omitted=0
    if [ "${omitted:-0}" -gt 0 ]; then
      echo "[review] agy leg read-audit INCONCLUSIVE ($omitted files_read entries capped) — weigh read_audit.digest.attempts[] (per-attempt totals) + read_audit.digest.read_attempts[] before voiding; there is no fuller digest and only the FINAL attempt's raw stream is retained, so if the census does not settle it, a narrower packet is a NEW round (a retry re-renders the frozen prompt)" >&2
      echo "[gate] INCONCLUSIVE $PACKET_ABS_PATH"
      n_inconclusive=$((n_inconclusive + 1))
    else
      # RETRY-CLEARABLE, unlike the ABSENT / jq rc>=2 arms
      # (gate-1 r15 row r15-2): a read-blind attempt wrote a readable audit
      # with its census, so the hook load check attributes it like any other
      # hooked attempt and a later attempt of the same round can stand beside
      # it — a re-dispatch inside the round CAN clear this one. The message
      # names that CONDITION (gate-1 r16 row r16-8): a census that is missing
      # or incomplete is refused by the hook check, and then only a NEW round
      # clears it.
      echo "[review] agy leg VOID — packet path not in read_audit.digest.files_read ($PACKET_ABS_PATH); retry the entry once on the unchanged basis — a retry inside the round clears this because the read-blind attempt wrote a readable census with its conversation ids and is attributed like any other attempt; if that census is missing or incomplete the hook check refuses and a NEW round is needed; still VOID after that retry is a missing result and the round stays INCOMPLETE (R-AGREE — no second re-dispatch)" >&2
      echo "[gate] VOID $PACKET_ABS_PATH"
      n_void=$((n_void + 1))
    fi
  else
    echo "[gate] PASS $PACKET_ABS_PATH"
    n_pass=$((n_pass + 1))
  fi
done

# Counters count EVALUATED files. Whenever any argument was NOT evaluated
# (the broken-evidence break stops the loop; the ABSENT refusal above
# evaluates none), the summary appends unevaluated=<n> so the token
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
