#!/usr/bin/env python3
"""Single-shot Antigravity CLI (agy) wrapper — stream-json transport.

agy >= 1.1.8 print mode emits typed NDJSON (`--output-format stream-json`:
init / step_update / terminal result), so this wrapper spawns agy via the
shared _common._run_once (scrubbed child env, setsid, SIGTERM->SIGKILL
killpg escalation), parses the stream with _common.parse_agy_stream, and
classifies in a dedicated extract-then-classify driver (the generic
run_cli_with_retry classifies before extracting, which can't host agy's
answer-quotes-an-error-token cases). A deterministic read-audit digest of
the stream's tool_info events (_common.digest_agy_stream) is emitted on
stderr + into the run-log — REPORT-ONLY (policy stays with the caller).
The pre-2026-07-31 pty + sentinel + transcript-read transport was deleted
(git history has it); a version floor fails closed on agy < 1.1.8.

Isolation is a per-call global-settings deny transaction (--sandbox
read-only -> _agy_settings.agy_settings_guard mutates permissions.deny then
restores; agy --sandbox adds the terminal OS-ring). workspace-write was
removed 2026-07-25 (owner directive — 616 audited calls, 0 workspace-write).
Audit log: _logs/antigravity/audit.jsonl (gitignored).
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

import json

import _agy_settings
import _common
from _common import load_pydantic_class, validate_response

OFFSET_S = 10  # agy --print-timeout = max(timeout - OFFSET, MIN); _run_once kill is backstop
MIN_PRINT_TIMEOUT_S = 5
SERVER_CAP_RETRIES = 2


@dataclass
class AgyResult:
    final_answer: Optional[str]
    classification: str
    exit_code: int
    vendor_exit_code: int
    # Raw NDJSON stream text — preserved on EVERY return path (the run-log
    # transcript: the repair agent reads the literal vendor events).
    stream_output: str = ""
    stderr: str = ""
    extraction_error: Optional[str] = None
    validated: Optional[dict] = None
    # Deterministic fold of the stream's tool_info events (REPORT-ONLY).
    read_audit: Optional[dict] = None


def _build_cmd(prompt, agy_sandbox, model, timeout, *, json_schema=None,
               skip_permissions=False):
    """Canonical agy invocation — stream-json transport (agy >= 1.1.8).
    The prompt goes through CLEAN: no sentinel sealing (the 2026-07-31
    migration removed the pty-era completion marker, so the transport no
    longer mutates what the model sees)."""
    print_to = max(timeout - OFFSET_S, MIN_PRINT_TIMEOUT_S)
    cmd = ["agy", "-p", prompt, "--output-format", "stream-json",
           "--print-timeout", f"{print_to}s"]
    if json_schema:
        cmd += ["--json-schema", json_schema]
    if agy_sandbox:
        cmd.append("--sandbox")
    if model:
        cmd += ["--model", model]
    if skip_permissions:
        cmd = _add_skip_permissions(cmd)
    return cmd


def _repair_cmd(cmd, err):
    """Rebuild the agy cmd with a one-shot JSON-repair hint appended to the
    -p arg (the vendor's own --json-schema repair turn failed to satisfy the
    LOCAL pydantic validation — belt-and-suspenders re-run, exactly once)."""
    new = list(cmd)
    i = new.index("-p") + 1
    new[i] = (new[i] + f"\n\nYour previous output was NOT valid JSON for the "
              f"schema ({err}). Output ONLY the corrected JSON object.")
    return new


def _classify_no_answer(stderr: str, signals, vendor_rc: int,
                        status=None) -> tuple:
    """Decide classification for the no-usable-answer case.

    The classify blob is stderr + STRUCTURAL stream signals + a synthetic
    status token (so an L2 pattern or a future extension entry can key on an
    unknown result status). It deliberately does NOT include the raw NDJSON
    stream (r1/R2): that stream carries model-authored prose, tool OUTPUT and
    tool PARAMETERS — the reviewed content itself — so a packet quoting a
    capacity phrase forced spurious `server-capacity` re-dispatches and one
    quoting an auth banner produced a terminal `oauth-env`. `signals` comes
    from `_common.agy_classify_signals` (typed error payloads only). The full
    raw stream still rides in `stream_output` for the run-log, so the repair
    agent's diagnostics are unchanged.
    """
    status_tok = f"agy result status={str(status)[:200]}" if status else ""
    parts = [stderr, *list(signals or []), status_tok]
    blob = "\n".join(t for t in parts if t and t.strip())
    if not blob.strip() and vendor_rc == 0:
        # Nothing structural to classify AND the vendor exited 0. A nonzero rc
        # still goes through classify() so the L1 vendor-exit map keeps its
        # say (a silent vendor failure that only signals through its rc must
        # not be swallowed by this short-circuit).
        return "extraction-error", _common.EXIT_CLI_FAIL
    cls = _common.classify(
        "antigravity", stderr=blob, stdout="",
        exit_code=_common.EXIT_CLI_FAIL, vendor_exit_code=vendor_rc,
    )
    return cls, _common.map_classification_to_exit(cls)


# agy 1.1.3 flipped headless (-p) permission policy: a tool needing a
# confirmation is soft-denied UNCONDITIONALLY (the allow-list is not consulted
# in print mode — verified: allow-rule forms, settings modes, env vars, and a
# PreToolUse decision:allow hook all fail). agy emits this distinctive line:
#   "... a tool required the "read_file" permission that headless mode cannot
#    prompt for, so it was auto-denied."
_HEADLESS_SOFTDENY_SIGNATURE = "headless mode cannot prompt"


def _is_headless_softdeny(text) -> bool:
    """True when agy's output carries the 1.1.3+ headless soft-deny signature.
    Targeted — matches ONLY that vendor message, so a version where the
    allow-list works (<=1.1.2 and any future fix) never trips it, and a plain
    empty/extraction failure is untouched."""
    return _HEADLESS_SOFTDENY_SIGNATURE in (text or "").lower()


# agy CLI-side answer fold (observed 2026-07-22, repro A-F): print output AND
# the transcript PLANNER_RESPONSE/DONE record are BOTH capped (~4KB observed)
# with a literal own-line `<truncated N bytes>` / `<truncated N lines>` marker
# replacing the folded middle (format strings live in the agy binary; every
# transcript record type is capped, incl. VIEW_FILE tool results). The full
# text is NOT preserved anywhere agy-side -> a marker-carrying answer is LOSSY
# and unrecoverable at this layer. Own-line anchor keeps a mid-sentence QUOTE
# of the marker from tripping the gate (observed folds are always own-line).
# Loophole route: agy's write_file is NOT subject to the fold (verified: 24KB
# file intact) -> the SKILL's absolute-path output-file contract, which needs
# the write-capable permissive baseline (unavailable on a hardened install and
# forbidden on the cross-family-review leg -> compact re-dispatch there).
_AGY_TRUNCATION_MARKER_RE = re.compile(r"(?m)^[ \t]*<truncated \d+ (?:bytes|lines)>[ \t]*$")


def _add_skip_permissions(cmd):
    """Insert --dangerously-skip-permissions right after argv[0] (the
    empirically-verified working position `agy --dangerously-skip-permissions
    -p ...`). Idempotent. This is the ONLY internal caller of the danger flag
    — user argv can never supply it (argparse in main() has no such option)."""
    if "--dangerously-skip-permissions" in cmd:
        return list(cmd)
    return list(cmd[:1]) + ["--dangerously-skip-permissions"] + list(cmd[1:])


# Version at/after which agy's headless (-p) mode soft-denies tools that need a
# confirmation — the allow-list is no longer consulted in print mode, so a
# read-only dispatch cannot run its own read tools. Floor, not a pin: the gate
# below fires for this version and up. When agy restores headless allow-list
# support in some future release, narrow this to a range (the daily-check tracks
# the version bump but NOT the allow-list-restored behavior, so this narrowing is
# a MANUAL trigger — merge-review F3). The flag never breaks a working dispatch
# (agy would auto-approve anyway), but on a future fixed version it still VOIDS
# the deny transaction + OS-ring — a security-relevant standing residual for the
# untrusted-review use case, NOT a harmless no-op (SKILL § Headless soft-deny
# adaptation), until the floor is narrowed.
_HEADLESS_SOFTDENY_FLOOR = (1, 1, 3)


def _parse_agy_version(text):
    """Extract the first dotted numeric version tuple from `agy --version`
    output (e.g. '1.1.3' -> (1, 1, 3)); None if unparseable."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(g) for g in m.groups()) if m else None


# Floor for the stream-json transport (this wrapper's ONLY transport since the
# 2026-07-31 migration; pty+sentinel deleted). Fail-CLOSED: an older or
# unprobeable agy stops loudly with a `config-conflict` (Task 6) — a silent
# fallback would change the prompt shape mid-fleet (the old sentinel sealing
# mutated the prompt) and mask a vendor regression from the repair loop.
_STREAM_JSON_FLOOR = (1, 1, 8)


def _probe_agy_version(agy_bin):
    """One `agy --version` probe (scrubbed env, 15s). Returns the parsed
    (major, minor, patch) tuple, or None on OSError / non-zero rc /
    unparseable output. Callers interpret None per their own fail
    direction: the stream floor fail-CLOSES (stop), the skip-permissions
    gate fail-SAFES (no danger flag)."""
    try:
        proc = subprocess.run([agy_bin, "--version"], capture_output=True,
                              text=True, timeout=15,
                              env=_common.scrubbed_child_env())
    except (OSError, subprocess.SubprocessError):
        return None
    # Fail-safe (merge-review F4/Q4): a non-zero --version exit is an
    # unreliable read.
    if proc.returncode != 0:
        return None
    return _parse_agy_version(proc.stdout)


def _agy_needs_skip_permissions(ver) -> bool:
    """True when the probed agy version soft-denies headless tools and the
    operator has NOT opted out (AGY_NO_HEADLESS_AUTOAPPROVE=1). Pure on the
    version tuple (probed ONCE in main); None fail-safes to False (never
    enable the isolation-voiding flag on an unreliable read)."""
    if os.environ.get("AGY_NO_HEADLESS_AUTOAPPROVE") == "1":
        return False
    return ver is not None and ver >= _HEADLESS_SOFTDENY_FLOOR


def _validate_structured(result, answer, pydantic_cls):
    """Local pydantic validation over the vendor's --json-schema output.
    PREFER result['structured_output'] (the vendor already schema-checked and
    self-repaired it — spike P4 showed an internal repair turn); fall back to
    the raw response text when absent (vendor drift guard). Returns
    (True, validated_dict) or (False, error_message_str) — same contract the
    schema-repair re-run and EXIT_SCHEMA_FAIL path consume.

    r1/R11: when structured_output was PRESENT but failed validation, that
    error is what the schema-repair hint must carry. It used to be discarded
    in favour of the raw-response fallback's error, which for the normal shape
    (prose in `response`, the real payload in `structured_output`) is a
    generic 'Invalid JSON: expecting value' — the repair turn was told its
    output was not JSON when the actual violation was a missing/invalid FIELD,
    so it had nothing actionable to fix."""
    structured = result.get("structured_output") if isinstance(result, dict) else None
    struct_err = None
    if structured is not None:
        ok, payload = validate_response(
            json.dumps(structured, ensure_ascii=False, default=str), pydantic_cls)
        if ok:
            return ok, payload
        struct_err = str(payload)[:600]
    ok, payload = validate_response(answer, pydantic_cls)
    if ok or struct_err is None:
        return ok, payload
    # Lead with the real violation; keep the fallback error too (nothing
    # hidden), both bounded — this string is appended to the repair prompt.
    return False, (f"structured_output invalid: {struct_err} "
                   f"| raw-response fallback also invalid: {str(payload)[:300]}")


def _run_agy_with_retry(cmd, prompt, timeout, *, cwd=None,
                        repair_mode=False, pydantic_cls=None) -> AgyResult:
    """Dedicated extract-then-classify driver over the stream-json transport.
    See the plan's decision table (2026-07-31) — ORDER MATTERS. Spawn =
    _common._run_once(classify_and_log=False): shared scrubbed env + setsid +
    SIGTERM->SIGKILL killpg escalation; classification and the canonical
    one-line summary stay THIS driver's job."""
    if not repair_mode:
        _common.prune_stale_run_logs("antigravity")

    # F-Q2: these three retry budgets are INDEPENDENT — schema_repaired,
    # skip_retried, and the server-capacity budget (max_retries/server_attempt)
    # each gate a different failure shape and do not share state. In
    # particular, schema repair fires exactly ONCE regardless of repair_mode;
    # repair_mode only disables the server-capacity retry (max_retries=0),
    # never the one-shot schema repair or the one-shot soft-deny retry.
    max_retries = 0 if repair_mode else SERVER_CAP_RETRIES
    server_attempt = 0
    schema_repaired = False   # one-shot local-validation repair re-run (Task 5)
    skip_retried = False      # one-shot headless soft-deny -> skip-permissions retry
    # r1/R4: one digest per ATTEMPT, aggregated on every return path. Emitting
    # only the LAST attempt's digest let a short-circuiting retry CONCEAL an
    # earlier attempt's reads — the review SKILL's mechanical read-audit gate
    # then VOIDed a leg that had demonstrably read the packet.
    attempt_digests: list = []
    while True:
        rr = _common._run_once("antigravity", cmd, cwd, timeout,
                               classify_and_log=False)
        stream = rr.stdout
        events, result = _common.parse_agy_stream(stream)
        attempt_digests.append(_common.digest_agy_stream(events, result))
        audit = _common.merge_agy_digests(attempt_digests)
        if rr.exit_code == _common.EXIT_TIMEOUT:
            # Killed short-circuit FIRST: a killed run's stream is a partial
            # prefix — never trust a result event parsed out of it.
            return AgyResult(None, "timeout", _common.EXIT_TIMEOUT,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit)
        # r1/R3: every field below is vendor-controlled. A non-dict result or
        # a non-string `response` (the model can emit a JSON object there)
        # must degrade to "no usable answer" — CLASSIFIED, audited, run-logged
        # — never an AttributeError traceback that costs the caller its
        # summary line, audit row and run-log.
        status = result.get("status") if isinstance(result, dict) else None
        raw_answer = result.get("response") if isinstance(result, dict) else None
        answer = raw_answer if isinstance(raw_answer, str) else ""
        bad_answer_type = (raw_answer is not None
                           and not isinstance(raw_answer, str))
        if result is not None and answer.strip():
            if rr.vendor_exit_code != 0 or status != "SUCCESS":
                # rc gate (kept) + status gate (NEW): the status vocabulary
                # beyond SUCCESS is unobserved — a non-SUCCESS answer is never
                # a silent ok and never fed to classify (a real answer can
                # quote error-shaped tokens). Bounded quarantined copy rides
                # in extraction_error for the run-log.
                #
                # "vendor-error" is a DISTINCT token, deliberately absent from
                # _common.CLASSIFICATION_TOKENS (surface-not-repair, P4
                # 2026-07-11): this condition (rc!=0 or non-SUCCESS status
                # WITH a real answer) is something a classifier patch cannot
                # express, so it is emitted directly here rather than routed
                # through classify(). Reusing "extraction-error" for this case
                # would mandate a MANDATORY repair-agent dispatch per the
                # dispatch SKILL's Hard rule 8 — wrong: there is nothing for
                # the repair agent to patch, this is a real answer the caller
                # should just see.
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "vendor-error", _common.EXIT_TERMINAL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 extraction_error=(
                                     f"vendor rc={rr.vendor_exit_code} "
                                     f"status={status!r} returned a non-empty "
                                     f"answer; surfaced as vendor-error. "
                                     f"quarantined answer: {snippet}"))
            if _AGY_TRUNCATION_MARKER_RE.search(answer):
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "truncated-answer", _common.EXIT_TERMINAL,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 extraction_error=(
                                     "agy folded the answer mid-body "
                                     "(own-line <truncated N bytes|lines> marker). "
                                     f"quarantined answer: {snippet}"))
            if pydantic_cls is None:
                return AgyResult(answer, "ok", _common.EXIT_OK,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit)
            ok, payload = _validate_structured(result, answer, pydantic_cls)
            if ok:
                return AgyResult(answer, "ok", _common.EXIT_OK,
                                 rr.vendor_exit_code, stream_output=stream,
                                 stderr=rr.stderr, read_audit=audit,
                                 validated=payload)
            if not schema_repaired:
                cmd = _repair_cmd(cmd, payload)
                schema_repaired = True
                continue
            return AgyResult(answer, "schema-fail", _common.EXIT_SCHEMA_FAIL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             extraction_error=f"schema: {payload}")
        # ── no usable answer from here ──
        # Structural failure signals ONLY (typed tool errors / error_message
        # steps). The raw stream is deliberately NOT part of either the
        # soft-deny match or the classify blob (r1/R2 + the adjudicated F2
        # structural fix): it carries the reviewed content, so quoted text
        # could steer a retry or a terminal classification.
        signals = _common.agy_classify_signals(events, result)
        softdeny_blob = "\n".join([rr.stderr or "", *signals])
        if (not skip_retried and _is_headless_softdeny(softdeny_blob)
                and os.environ.get("AGY_NO_HEADLESS_AUTOAPPROVE") != "1"):
            # P2 evidence: the jetski soft-deny notice coexists with a
            # SUCCESS+empty result — so this retry covers the empty-response
            # path, not only the missing-result path.
            #
            # SECURITY (owner-authorized 2026-07-18): --dangerously-skip-
            # permissions VOIDS the per-call deny transaction for this retry
            # attempt — write_file/command (and everything else the deny
            # transaction would otherwise block) is auto-approved, not just
            # the soft-denied read. Containment for this retry then rests on
            # review INTENT (read-only/research dispatch) + a disposable
            # --cwd + leader verification of the result, NOT on the deny
            # list. Opt out with AGY_NO_HEADLESS_AUTOAPPROVE=1 (checked just
            # above) when that residual is unacceptable for a given call.
            #
            # Retry ONLY when the flag actually CHANGES the command (the
            # adjudicated F2 structural fix). On every dispatchable build the
            # stream floor (1.1.8) is above the soft-deny floor (1.1.3), so
            # main() already set the flag on call #1 and _add_skip_permissions
            # is idempotent — the retry then re-ran a BYTE-IDENTICAL command,
            # silently doubling the vendor call with no possible change in
            # outcome. skip_retried is consumed either way (one-shot).
            skip_retried = True
            new_cmd = _add_skip_permissions(cmd)
            if new_cmd != cmd:
                cmd = new_cmd
                continue
            _common.log("headless soft-deny signature but the flag is already "
                        "present — skipping an identical re-run")
        if result is not None and status == "SUCCESS":
            # SUCCESS + empty response (spike P2, rc=0): a failed task the
            # vendor reports as success. Never a silent empty ok.
            note = "empty-answer-body"
            if bad_answer_type:
                note += (f" (non-string response payload: "
                         f"{type(raw_answer).__name__})")
            return AgyResult(None, "extraction-error", _common.EXIT_CLI_FAIL,
                             rr.vendor_exit_code, stream_output=stream,
                             stderr=rr.stderr, read_audit=audit,
                             extraction_error=note)
        cls, code = _classify_no_answer(rr.stderr, signals,
                                        rr.vendor_exit_code, status)
        if cls == "server-capacity" and server_attempt < max_retries:
            _server_cap_backoff(server_attempt)
            server_attempt += 1
            continue
        return AgyResult(None, cls, code, rr.vendor_exit_code,
                         stream_output=stream, stderr=rr.stderr,
                         read_audit=audit)


def _server_cap_backoff(attempt: int) -> None:
    """Politeness sleep before a server-capacity retry (FIX 5). Suppressible
    via AGY_NO_BACKOFF=1 so unit/integration tests don't sleep 15s+."""
    if os.environ.get("AGY_NO_BACKOFF") == "1":
        return
    idx = min(attempt, len(_common.SERVER_CAP_BACKOFF_S) - 1)
    time.sleep(_common.SERVER_CAP_BACKOFF_S[idx])


def _terminate_to_exit(signum, frame):
    raise SystemExit(128 + signum)


def main() -> int:
    # SIGTERM/SIGHUP unwind instead of dying mid-transaction, so the settings
    # guard restore + vendor child kill run on the way out (SIGKILL stays
    # uncoverable by design — .agybak + next-call heal owns that window).
    try:
        signal.signal(signal.SIGTERM, _terminate_to_exit)
        signal.signal(signal.SIGHUP, _terminate_to_exit)
    except ValueError:
        pass  # not the main thread (in-process test harness): keep defaults
    # STALE-DIGEST pre-clear (final-gate fix round F1(a)) — call START, before
    # ANY other logic (argparse, validation, the vendor dispatch), so EVERY
    # exit path — including an early arg-validation failure that never
    # reaches emit_read_audit's call site at all — leaves TRIAD_READ_AUDIT_FILE
    # ABSENT rather than a prior round's stale digest. See
    # _common.preclear_read_audit_file's own docstring for the full rationale.
    # `repair_mode` is PEEKED from raw `sys.argv` here (mirrors
    # `prune_stale_run_logs`'s own repair_mode skip): argparse has not run
    # yet at this point in main(), so `args.repair_mode` does not exist —
    # a --repair-mode re-run must skip the clear (G3, re-confirm round 2),
    # so the peek has to happen BEFORE the parse, not after.
    _common.preclear_read_audit_file(repair_mode="--repair-mode" in sys.argv)
    p = argparse.ArgumentParser(description="Antigravity (agy) single-shot wrapper",
                                allow_abbrev=False)
    prompt_group = p.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="User prompt")
    prompt_group.add_argument(
        "--prompt-file",
        help="Read the user prompt from a UTF-8 file (L12; containment applies "
             "under TRIAD_WRAPPER_ALLOWED_ROOTS)")
    p.add_argument("--cwd", default=None)
    p.add_argument("--sandbox", choices=["read-only"],
                   default=None,
                   help="read-only — per-call deny transaction "
                        "(global settings mutate+restore). Omit = permissive baseline. "
                        "(workspace-write removed 2026-07-25 — owner directive, never "
                        "used in 616 audited calls.)")
    p.add_argument("--model", default=None)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--repair-mode", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--pydantic", default=None,
                   help="pydantic class spec (module:Class) — native "
                        "--json-schema (model_json_schema()) + local "
                        "validate; one repair re-run then exit 66")
    # NOTE: --dangerously-* are intentionally NOT defined -> argparse rejects
    # them (danger flags are banned).
    args = p.parse_args()

    try:
        _prompt_text = _common.load_prompt_text(args.prompt, args.prompt_file)
    except Exception as e:
        _common.log(f"prompt load failed: {e}")
        return _common.EXIT_ARG_ERROR
    args.prompt = _prompt_text  # downstream code keeps using args.prompt

    try:
        args.cwd = _common.validate_wrapper_cwd(args.cwd)
    except Exception as e:
        _common.log(f"--cwd validation failed: {e}")
        return _common.EXIT_ARG_ERROR

    if args.sandbox is None and _common._wrapper_hardened():
        # Hardened installs default the Google legs to read-only (raw calls on
        # a public install must not be write-capable by omission).
        args.sandbox = "read-only"

    if not args.prompt.strip():
        _common.log("empty prompt")
        return _common.EXIT_ARG_ERROR

    pydantic_cls = None
    if args.pydantic:
        try:
            pydantic_cls = load_pydantic_class(args.pydantic)
        except Exception as e:
            _common.log(f"--pydantic load failed: {e}")
            return _common.EXIT_ARG_ERROR

    agy_bin = _common.require_binary("agy")

    r: Optional[AgyResult] = None
    elapsed = 0.0
    cmd = [agy_bin]

    # Probe is unconditional BY DESIGN: the stream-json floor gate below needs
    # the version read even when AGY_NO_HEADLESS_AUTOAPPROVE=1 is set — that
    # opt-out governs only the skip-permissions flag (_agy_needs_skip_permissions),
    # never the floor gate.
    ver = _probe_agy_version(agy_bin)
    if ver is None or ver < _STREAM_JSON_FLOOR:
        # Fail-CLOSED floor: the stream-json transport is the only transport
        # (2026-07-31 migration). Surface as config-conflict (user runs
        # `agy update`), audited like every other terminal outcome.
        found = ".".join(map(str, ver)) if ver else "unprobeable"
        r = AgyResult(None, "config-conflict", _common.EXIT_TERMINAL, -1,
                      extraction_error=(
                          f"agy {found} < 1.1.8 — the stream-json transport "
                          f"requires agy >= 1.1.8; run `agy update`"))
    else:
        sandbox_mode = args.sandbox
        deny_rules = _agy_settings.build_deny_rules(sandbox_mode) if sandbox_mode else []
        agy_sandbox = sandbox_mode is not None  # read-only passes agy --sandbox (terminal ring)
        try:
            settings_lock_timeout = float(os.environ.get("AGY_SETTINGS_LOCK_TIMEOUT", "30"))
        except ValueError:
            _common.log("AGY_SETTINGS_LOCK_TIMEOUT must be a number")
            return _common.EXIT_ARG_ERROR

        # agy 1.1.3+ headless soft-deny adaptation (owner-authorized 2026-07-18):
        # version-gated auto-approve so a read-only-INTENT dispatch can actually run
        # its own read tools (the vendor stopped consulting the allow-list in print
        # mode). See _agy_needs_skip_permissions + § Isolation caveat. Reuses the
        # single probe above — no second implicit probe site.
        skip_permissions = _agy_needs_skip_permissions(ver)
        json_schema = json.dumps(pydantic_cls.model_json_schema()) if pydantic_cls else None
        cmd = _build_cmd(args.prompt, agy_sandbox, args.model, args.timeout,
                         json_schema=json_schema,
                         skip_permissions=skip_permissions)
        # argv[0] = resolved/pinned agy path (finding #3). _build_cmd stays pure ("agy"
        # literal) so its unit test is unaffected; the pin is substituted here at the
        # run site so a PATH shadow cannot win when the pty execs argv[0].
        cmd[0] = agy_bin

        start = time.monotonic()
        try:
            with _agy_settings.agy_settings_guard(
                deny_rules,
                lock_timeout=settings_lock_timeout,
            ):
                r = _run_agy_with_retry(cmd, args.prompt, args.timeout,
                                        cwd=args.cwd,
                                        repair_mode=args.repair_mode,
                                        pydantic_cls=pydantic_cls)
        except (TimeoutError, json.JSONDecodeError, ValueError, OSError) as e:
            # Settings-transaction failure (lock timeout / corrupt settings.json /
            # transient fs error) — surface as classification `config-conflict`
            # (EXIT_TERMINAL, user escalate), never a traceback. If the vendor run
            # ALREADY completed and only the transaction release failed, suppress
            # the completed answer (the deny lease did not close cleanly) but keep
            # the transcript for the run-log.
            prior = r
            extraction_error = f"agy settings/config conflict: {e}"
            _common.log(extraction_error)
            if prior is not None:
                extraction_error = (
                    f"{e}; completed vendor result suppressed because the agy "
                    f"settings transaction did not release cleanly"
                )
                if prior.extraction_error:
                    # P4 round-3: never DISCARD the prior result's diagnostic —
                    # for a vendor-error answer this carries the only run-log
                    # copy of the quarantined answer.
                    extraction_error += f" | prior: {prior.extraction_error}"
            r = AgyResult(
                None,
                "config-conflict",
                _common.EXIT_TERMINAL,
                prior.vendor_exit_code if prior is not None else -1,
                stream_output=prior.stream_output if prior is not None else "",
                stderr=prior.stderr if prior is not None else "",
                read_audit=prior.read_audit if prior is not None else None,
                extraction_error=extraction_error,
            )
        elapsed = time.monotonic() - start

    # Build a RunResult for the shared audit / run-log / debug helpers.
    rr = _common.RunResult(
        exit_code=r.exit_code,
        stdout=r.stream_output,
        stderr=r.stderr,
        elapsed_s=elapsed,
        classification=r.classification,
        mode="repair" if args.repair_mode else "normal",
        final_answer=r.final_answer or "",
        extraction_error=r.extraction_error,
        vendor_exit_code=r.vendor_exit_code,
        read_audit=r.read_audit,
    )

    # Read-audit digest — emitted BEFORE the canonical summary line, on EVERY
    # completed vendor call (ok or not), so the review SKILL / leader can
    # consume it even on success (the run-log only exists on failure).
    if r.read_audit is not None:
        # ensure_ascii=True (r1/R9): the digest is vendor/model-controlled and
        # this line carries the TRUSTED `[wrapper] antigravity ` prefix the
        # review SKILL greps. With ensure_ascii=False a raw U+2028/U+2029 (or
        # any other line-terminator a consumer's splitlines() honours) rode
        # straight through, letting the payload forge extra leader-visible
        # lines. Escaping them keeps the line single-line by construction.
        _common.log("[wrapper] antigravity read-audit "
                    + json.dumps(r.read_audit, separators=(",", ":")))
        # Durable file artifact (task-1, 2026-07-31 follow-up): the stderr
        # line above is a transient operator aid; a review-SKILL-grade
        # consumer needs a durable, jq-only artifact that exists on the
        # SUCCESS path too (emit_run_log only writes on failure). Best-effort
        # — an IO failure here never changes rr.exit_code/classification.
        read_audit_path = _common.emit_read_audit("antigravity", rr)
        if read_audit_path is not None:
            _common.log(f"read-audit-file: {read_audit_path}")

    # Canonical 1-line summary — byte-match the format _run_once emits so the
    # dispatch SKILL grep + the parity test see the same shape.
    _common.log(
        f"[wrapper] antigravity {r.classification} "
        f"exit={r.exit_code} vendor={r.vendor_exit_code} "
        f"elapsed={elapsed:.1f}s"
    )

    _common.audit("antigravity", cmd, args.prompt, rr)
    if args.debug:
        _common.debug_log("antigravity", args.prompt, rr)
    run_log_path = _common.emit_run_log(
        "antigravity", sys.argv, cmd, args.prompt, rr)
    if run_log_path is not None:
        _common.log(f"run-log: {run_log_path}")

    if r.validated is not None:
        sys.stdout.write(json.dumps(r.validated, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(r.final_answer or "")
        if r.final_answer and not r.final_answer.endswith("\n"):
            sys.stdout.write("\n")
    sys.stdout.flush()
    return r.exit_code


if __name__ == "__main__":
    sys.exit(main())
