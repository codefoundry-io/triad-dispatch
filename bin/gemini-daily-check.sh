#!/usr/bin/env bash
# gemini-daily-check.sh — daily gemini drift detector (self-healing "detect" arm,
# gemini-surface adaptation of agy-daily-check.sh). gemini 0.46.0 has NO
# update/models/changelog/plugins subcommands (Tier-2); it has --version,
# `extensions list`, `skills list`. So this probes version + extensions + skills
# (+superpowers) drift, with an optional deep JSON-adherence probe. NO auto-update
# (gemini is npm-managed; the operator updates manually). Split exit semantics so
# benign churn does not train operators to ignore the alarm:
#   0 = no change
#   1 = ACTIONABLE drift (deep JSON-adherence broke)
#   2 = INFORMATIONAL change (version / extensions / skills)
# A failed `gemini` subcommand KEEPS the previous snapshot (never overwrites with
# an empty result) so a transient CLI failure cannot manufacture false drift.
#
# Wire to launchd (Mac) or cron (Ubuntu) — see 3rd-Agent/wrappers/README.md.
# Env: GEMINI_DAILY_STATE (state dir, default ~/.gemini/triad-daily).
#      GEMINI_DAILY_DEEP=1 runs the deep JSON-adherence probe.
#      GEMINI_DEEP_TIMEOUT_S bounds the deep probe (default 60s; portable watchdog).
set -uo pipefail

STATE="${GEMINI_DAILY_STATE:-$HOME/.gemini/triad-daily}"
mkdir -p "$STATE"
REPORT="$STATE/report.md"
actionable=0      # -> exit 1
informational=0   # -> exit 2
note() { printf '%s\n' "$*" >> "$REPORT"; }

command -v gemini >/dev/null || { echo "gemini not installed" >&2; exit 4; }

{
  printf '# gemini daily-check report\n\n'
  printf 'version: %s\n' "$(gemini --version 2>/dev/null | head -n 1)"
} > "$REPORT"

# 1. version drift (INFORMATIONAL). No `update` subcommand (npm-managed): report
#    the installed version, operator updates manually. Preserve prior on failure.
if gemini --version 2>/dev/null | head -n 1 > "$STATE/version.now" && [ -s "$STATE/version.now" ]; then
  if [ -f "$STATE/version.snapshot" ] && ! diff -q "$STATE/version.snapshot" "$STATE/version.now" >/dev/null; then
    note "- INFO: gemini version changed ($(cat "$STATE/version.snapshot") -> $(cat "$STATE/version.now")) — review for spec impact (npm-managed; update manually)"
    informational=1
  fi
  cp "$STATE/version.now" "$STATE/version.snapshot"
else
  note "- WARN: gemini --version failed/empty; keeping previous version snapshot"
  rm -f "$STATE/version.now"
fi

# 2. extensions-list drift (INFORMATIONAL). Preserve prior snapshot on failure/empty.
if gemini extensions list 2>/dev/null | sort > "$STATE/extensions.now" && [ -s "$STATE/extensions.now" ]; then
  if [ -f "$STATE/extensions.snapshot" ] && ! diff -q "$STATE/extensions.snapshot" "$STATE/extensions.now" >/dev/null; then
    {
      printf -- '- INFO: extensions list changed:\n'
      diff "$STATE/extensions.snapshot" "$STATE/extensions.now" | sed 's/^/    /'
    } >> "$REPORT"
    informational=1
  fi
  cp "$STATE/extensions.now" "$STATE/extensions.snapshot"
else
  note "- WARN: gemini extensions list failed/empty; keeping previous extensions snapshot"
  rm -f "$STATE/extensions.now"
fi

# 3. skills-list drift (INFORMATIONAL) + superpowers presence. gemini supports
#    skills natively (`gemini skills`); the list diff catches superpowers
#    appearing/disappearing (the severity), the note records current state.
if gemini skills list 2>/dev/null | sort > "$STATE/skills.now" && [ -s "$STATE/skills.now" ]; then
  if [ -f "$STATE/skills.snapshot" ] && ! diff -q "$STATE/skills.snapshot" "$STATE/skills.now" >/dev/null; then
    {
      printf -- '- INFO: skills list changed:\n'
      diff "$STATE/skills.snapshot" "$STATE/skills.now" | sed 's/^/    /'
    } >> "$REPORT"
    informational=1
  fi
  cp "$STATE/skills.now" "$STATE/skills.snapshot"
  if grep -qi superpower "$STATE/skills.now"; then
    note "- superpowers present in gemini skills"
  else
    note "- superpowers NOT in gemini skills (install via: gemini skills install <source>)"
  fi
else
  note "- WARN: gemini skills list failed/empty; keeping previous skills snapshot"
  rm -f "$STATE/skills.now"
fi

# 4. deep JSON-adherence smoke (ACTIONABLE; gated by env). gemini has native
#    --output-format json, so no pty hack: parse the envelope + assert the inner
#    response is JSON-only (no backtick fences).
if [ "${GEMINI_DAILY_DEEP:-0}" = "1" ]; then
  # Bound the only network probe so a hung/slow/rate-limited gemini cannot stall a
  # cron run. Portable watchdog (stock macOS lacks GNU `timeout`): background the
  # call, poll, kill if it overruns GEMINI_DEEP_TIMEOUT_S (default 60s).
  jtmp="$STATE/deep.out"; : > "$jtmp"
  gemini -p 'Output a JSON object only, no backticks, no prose: {"k":1}' \
    --output-format json > "$jtmp" 2>/dev/null &
  gpid=$!
  waited=0
  while kill -0 "$gpid" 2>/dev/null; do
    if [ "$waited" -ge "${GEMINI_DEEP_TIMEOUT_S:-60}" ]; then
      kill -TERM "$gpid" 2>/dev/null; sleep 1; kill -KILL "$gpid" 2>/dev/null
      break
    fi
    sleep 1; waited=$((waited + 1))
  done
  wait "$gpid" 2>/dev/null
  jenv=$(cat "$jtmp" 2>/dev/null); rm -f "$jtmp"
  if ! printf '%s' "$jenv" | python3 -c 'import sys,json; d=json.load(sys.stdin); r=d.get("response",""); assert "`" not in r; json.loads(r)' 2>/dev/null; then
    note "- DRIFT (actionable): JSON-only adherence broke or probe timed out (response not clean JSON, backticks present, or no response within ${GEMINI_DEEP_TIMEOUT_S:-60}s)"
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
    2) printf 'exit 2 (informational — review version/extensions/skills)\n' ;;
  esac
} >> "$REPORT"
exit "$status"
