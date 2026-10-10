#!/usr/bin/env python3
"""Thin CLI over `_common.apply_classifier_patch` — the SKILL-callable applier.

The repair sub-agent is a READ-ONLY analyzer (no Write/Edit/Bash): it returns a
structured patch PROPOSAL as inline JSON. The leader (or the codex-host top-level
`codex exec -s read-only` shell) then feeds that proposal to THIS command, which
is the single deterministic, validated, zero-LLM write path to the classifier
extension JSON.

Usage:
  python3 apply_patch.py --cli <name> < proposal.json
  python3 apply_patch.py --cli <name> --proposal-file <path> [--verify-run-log <path>]

`--verify-run-log <path>` verifies the proposal on the failed run's STORED record
(`_common.reclassify_run_record`; the vendor is never called again). The run-log
is read and checked BEFORE the apply; after it, three lines are printed:
  [apply_patch] verify: <path> -> <class> (stored <class>, before the apply <class>)
  [apply_patch] evidence: cli=<cli> ts=<ts> vendor_version=<v|unknown> field=<field> run_log=<path>
  [apply_patch] sentence: <the first stored line carrying the substring, 300 chars>
                          (a vendor_exit_code proposal: `vendor exit <stored code>`)

Proposal shape (see apply_classifier_patch):
  {"classification": <enum>, "reason": <str>,
   "vendor_exit_code": <int>            # OR
   "pattern_list": <NAME>, "substring": <str>}

Exit codes:
  0  applied (with --verify-run-log: and the record now routes to the proposed
     class, which differs from its pre-apply re-classification)
  3  invalid proposal (ValueError) or bad input (arg / JSON parse), or a run-log
     that is missing, empty, unreadable, not JSON, of another cli or refused for
     verification — file untouched
  4  applied, but the stored record does not route to the proposed class (or did
     already): the entry stays applied
"""
from __future__ import annotations

import argparse
import json
import sys

from _common import (_run_record_path, agy_classify_signals, apply_classifier_patch,
                     reclassify_run_record)

EXIT_OK = 0
EXIT_INVALID = 3
EXIT_NOT_VERIFIED = 4


def _evidence(record: dict, proposal: dict) -> tuple:
    """(field, sentence): where the stored record carries the proposal, in the
    fields the classifier read on the record's path (`_run_record_path`):
    (b) `extraction_error`; (c) stderr, then the stream result's typed
    `result.error` (never a tool-output or model line of the raw stream);
    (a) stderr, then stdout (agy: stderr only)."""
    if proposal.get("vendor_exit_code") is not None:
        return "vendor_exit_code", f"vendor exit {record.get('vendor_exit_code')}"
    path, result = _run_record_path(record)
    if path == "b":
        fields = [("extraction_error", record.get("extraction_error"))]
    elif path == "c":
        fields = [("stderr", record.get("stderr")),
                  ("result.error", "\n".join(agy_classify_signals(result)))]
    else:
        fields = [("stderr", record.get("stderr"))]
        if record.get("cli") != "antigravity":
            fields.append(("stdout", record.get("stdout")))
    needle = str(proposal.get("substring") or "").lower()
    for field, text in fields:
        for line in str(text or "").split("\n"):
            if needle and needle in line.lower():
                return field, line[:300]
    return "none", "(the substring is in no line the classifier read)"


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply a validated classifier patch proposal.")
    ap.add_argument("--cli", required=True, help="Target CLI name (codex/gemini/antigravity).")
    ap.add_argument(
        "--proposal-file",
        default=None,
        help="Read the proposal JSON from this file instead of stdin.",
    )
    ap.add_argument(
        "--verify-run-log",
        default=None,
        help="Verify the proposal on this failed run's stored run-log record.",
    )
    args = ap.parse_args()

    record = before = None
    if args.verify_run_log is not None:
        try:
            if not args.verify_run_log:
                raise OSError("empty path")
            with open(args.verify_run_log, "r", encoding="utf-8") as f:
                record = json.loads(f.read())
            if not isinstance(record, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError) as e:
            print(f"[apply_patch] cannot read run-log {args.verify_run_log}: {e}", file=sys.stderr)
            return EXIT_INVALID
        if record.get("cli") != args.cli:
            print(f"[apply_patch] run-log cli {record.get('cli')!r} is not --cli {args.cli!r}",
                  file=sys.stderr)
            return EXIT_INVALID
        try:
            before = reclassify_run_record(record)
        except ValueError as e:
            print(f"[apply_patch] {e}", file=sys.stderr)
            return EXIT_INVALID

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
    if record is None:
        return EXIT_OK

    after = reclassify_run_record(record)
    field, sentence = _evidence(record, proposal)
    print(f"[apply_patch] verify: {args.verify_run_log} -> {after} "
          f"(stored {record.get('classification')}, before the apply {before})")
    print(f"[apply_patch] evidence: cli={record.get('cli')} ts={record.get('ts')} "
          f"vendor_version={record.get('vendor_version') or 'unknown'} field={field} "
          f"run_log={args.verify_run_log}")
    print(f"[apply_patch] sentence: {sentence}")
    if after == proposal.get("classification") and after != before:
        return EXIT_OK
    return EXIT_NOT_VERIFIED


if __name__ == "__main__":
    sys.exit(main())
