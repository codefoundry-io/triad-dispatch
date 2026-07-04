#!/usr/bin/env bash
# agy-daily-check.sh — daily agy update + spec drift detector (self-healing
# "detect" arm). Snapshot model list / changelog / plugin list (and an optional
# heavy JSON-adherence probe) vs the stored baseline, probe superpowers-for-agy,
# write a dated drift report. Split exit semantics so benign vendor churn does
# not train operators to ignore the alarm:
#   0 = no change
#   1 = ACTIONABLE drift (model list changed, or deep JSON-adherence broke)
#   2 = INFORMATIONAL change (changelog version / plugin list / superpowers-available)
#
# A failed `agy` subcommand KEEPS the previous snapshot (never overwrites with an
# empty result) so a transient CLI failure cannot manufacture false drift next run.
#
# Wire to launchd (Mac) or cron (Ubuntu) — see the plugin README.md.
# Env: AGY_DAILY_STATE (state dir, default ~/.gemini/antigravity-cli/triad-daily).
#      --no-update skips `agy update` (tests / offline).
#      AGY_DAILY_DEEP=1 runs the heavy pty JSON-adherence probe (portable `script`).
set -uo pipefail

STATE="${AGY_DAILY_STATE:-$HOME/.gemini/antigravity-cli/triad-daily}"
mkdir -p "$STATE"
NO_UPDATE=0; [ "${1:-}" = "--no-update" ] && NO_UPDATE=1
REPORT="$STATE/report.md"
actionable=0      # -> exit 1
informational=0   # -> exit 2
note() { printf '%s\n' "$*" >> "$REPORT"; }

command -v agy >/dev/null || { echo "agy not installed" >&2; exit 4; }

{
  printf '# agy daily-check report\n\n'
  printf 'version: %s\n' "$(agy --version 2>/dev/null | head -n 1)"
} > "$REPORT"

# 1. update (unless suppressed)
if [ "$NO_UPDATE" -eq 0 ]; then
  agy update >/dev/null 2>&1 || note "- WARN: agy update failed"
fi

# 2. model-list drift (ACTIONABLE). Preserve prior snapshot on failure/empty.
if agy models 2>/dev/null | sort > "$STATE/models.now" && [ -s "$STATE/models.now" ]; then
  if [ -f "$STATE/models.snapshot" ] && ! diff -q "$STATE/models.snapshot" "$STATE/models.now" >/dev/null; then
    {
      printf -- '- DRIFT (actionable): model list changed:\n'
      diff "$STATE/models.snapshot" "$STATE/models.now" | sed 's/^/    /'
    } >> "$REPORT"
    actionable=1
  fi
  cp "$STATE/models.now" "$STATE/models.snapshot"
else
  note "- WARN: agy models failed/empty; keeping previous model snapshot"
  rm -f "$STATE/models.now"
fi

# 3. changelog drift (INFORMATIONAL). Normalize to the latest version token so
#    only a real release bump (not formatting) registers.
if agy changelog 2>/dev/null > "$STATE/changelog.raw" && [ -s "$STATE/changelog.raw" ]; then
  grep -oE 'v?[0-9]+\.[0-9]+\.[0-9]+' "$STATE/changelog.raw" | head -n 1 > "$STATE/changelog.now"
  [ -s "$STATE/changelog.now" ] || head -n 1 "$STATE/changelog.raw" > "$STATE/changelog.now"
  if [ -f "$STATE/changelog.snapshot" ] && ! diff -q "$STATE/changelog.snapshot" "$STATE/changelog.now" >/dev/null; then
    note "- INFO: changelog latest version changed ($(cat "$STATE/changelog.snapshot") -> $(cat "$STATE/changelog.now")) — review for spec impact"
    informational=1
  fi
  cp "$STATE/changelog.now" "$STATE/changelog.snapshot"
else
  note "- WARN: agy changelog failed/empty; keeping previous changelog snapshot"
fi
rm -f "$STATE/changelog.raw"

# 4. plugin-list drift (INFORMATIONAL) + superpowers-for-agy probe.
if agy plugins list 2>/dev/null | sort > "$STATE/plugins.now" && [ -s "$STATE/plugins.now" ]; then
  if [ -f "$STATE/plugins.snapshot" ] && ! diff -q "$STATE/plugins.snapshot" "$STATE/plugins.now" >/dev/null; then
    {
      printf -- '- INFO: plugin list changed:\n'
      diff "$STATE/plugins.snapshot" "$STATE/plugins.now" | sed 's/^/    /'
    } >> "$REPORT"
    informational=1
  fi
  cp "$STATE/plugins.now" "$STATE/plugins.snapshot"
  if grep -qi superpower "$STATE/plugins.now"; then
    note "- ★ superpowers-for-agy AVAILABLE — integrate (homework)"
    informational=1
  fi
else
  note "- WARN: agy plugins list failed/empty; keeping previous plugin snapshot"
  rm -f "$STATE/plugins.now"
fi

# 5. spec-assumption smoke (ACTIONABLE; heavy pty, gated by env). Portable script(1):
#    GNU/util-linux needs `-c "<cmd>"`; BSD/macOS takes the command as trailing args.
if [ "${AGY_DAILY_DEEP:-0}" = "1" ]; then
  if script --version 2>&1 | grep -qi util-linux; then
    jout=$(script -q -c 'agy -p '\''Output JSON only, no backticks: {"k":1}'\'' --print-timeout 60s' /dev/null </dev/null 2>/dev/null | tr -d '\004')
  else
    jout=$(script -q /dev/null agy -p 'Output JSON only, no backticks: {"k":1}' --print-timeout 60s </dev/null 2>/dev/null | tr -d '\004')
  fi
  if printf '%s' "$jout" | grep -q '`'; then
    note "- DRIFT (actionable): JSON-only adherence broke (backticks present)"
    actionable=1
  fi
fi

# exit precedence: actionable > informational > none
if [ "$actionable" -ne 0 ]; then status=1
elif [ "$informational" -ne 0 ]; then status=2
else status=0; fi
{
  printf '\n'
  case "$status" in
    0) printf 'exit 0 (no action)\n' ;;
    1) printf 'exit 1 (ACTIONABLE — review + update spec)\n' ;;
    2) printf 'exit 2 (informational — review changelog/plugins)\n' ;;
  esac
} >> "$REPORT"
exit "$status"
