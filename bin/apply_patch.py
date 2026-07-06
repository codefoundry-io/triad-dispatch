#!/usr/bin/env python3
"""Thin CLI over `_common.apply_classifier_patch` — the SKILL-callable applier.

The repair sub-agent is a READ-ONLY analyzer (no Write/Edit/Bash): it returns a
structured patch PROPOSAL as inline JSON. The leader (or the codex-host top-level
`codex exec -s read-only` shell) then feeds that proposal to THIS command, which
is the single deterministic, validated, zero-LLM write path to the classifier
extension JSON.

Usage:
  python3 apply_patch.py --cli <name> < proposal.json
  python3 apply_patch.py --cli <name> --proposal-file <path>

Proposal shape (see apply_classifier_patch):
  {"classification": <enum>, "reason": <str>,
   "vendor_exit_code": <int>            # OR
   "pattern_list": <NAME>, "substring": <str>}

Exit codes:
  0  applied
  3  invalid proposal (ValueError) or bad input (arg / JSON parse) — file untouched
"""
from __future__ import annotations

import argparse
import json
import sys

from _common import apply_classifier_patch

EXIT_OK = 0
EXIT_INVALID = 3


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply a validated classifier patch proposal.")
    ap.add_argument("--cli", required=True, help="Target CLI name (codex/gemini/claude/antigravity).")
    ap.add_argument(
        "--proposal-file",
        default=None,
        help="Read the proposal JSON from this file instead of stdin.",
    )
    args = ap.parse_args()

    try:
        if args.proposal_file:
            with open(args.proposal_file, "r", encoding="utf-8") as f:
                raw = f.read()
        else:
            raw = sys.stdin.read()
    except OSError as e:
        print(f"[apply_patch] cannot read proposal: {e}", file=sys.stderr)
        return EXIT_INVALID

    try:
        proposal = json.loads(raw)
    except ValueError as e:
        print(f"[apply_patch] invalid proposal JSON: {e}", file=sys.stderr)
        return EXIT_INVALID

    if not isinstance(proposal, dict):
        print("[apply_patch] proposal must be a JSON object", file=sys.stderr)
        return EXIT_INVALID

    try:
        result = apply_classifier_patch(args.cli, proposal)
    except ValueError as e:
        print(f"[apply_patch] rejected: {e}", file=sys.stderr)
        return EXIT_INVALID

    print(result)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
