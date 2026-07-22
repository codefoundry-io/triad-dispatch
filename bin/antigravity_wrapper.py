#!/usr/bin/env python3
"""Single-shot Antigravity CLI (agy) wrapper — pty transport + dedicated driver.

agy -p drops stdout on a non-TTY and has no --output-format json, so this
wrapper drives agy through a pty (_pty), scrubs control bytes, checks a
per-call completion sentinel, and classifies via _common pure helpers in a
dedicated extract-then-classify driver (the generic run_cli_with_retry
classifies before extracting, which can't host agy's rc=0 auth-banner case).

Isolation is a per-call global-settings deny transaction (--sandbox
read-only|workspace-write -> _agy_settings.agy_settings_guard mutates
permissions.deny then restores; agy --sandbox adds the terminal OS-ring).
Audit log: _logs/antigravity/audit.jsonl (gitignored).
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional

import json

import _agy_settings
import _common
import _pty
from _common import load_pydantic_class, inject_schema_to_prompt, validate_response

OFFSET_S = 10  # agy --print-timeout = max(timeout - OFFSET, MIN); pty kill is backstop
MIN_PRINT_TIMEOUT_S = 5
SERVER_CAP_RETRIES = 2


@dataclass
class AgyResult:
    final_answer: Optional[str]
    classification: str
    exit_code: int
    vendor_exit_code: int
    # Raw scrubbed pty transcript — preserved on EVERY return path so the
    # run-log + audit carry it for the agy-wrapper-repair agent (FIX 1).
    scrubbed_output: str = ""
    extraction_error: Optional[str] = None
    validated: Optional[dict] = None


def _make_sentinel() -> str:
    """Per-INVOCATION identity marker, generated ONCE in main() and held constant
    across the schema-repair re-run (reproducibility comes from reuse, not from
    deriving it from the prompt).

    A random 128-bit id (secrets.token_hex(16)) so two concurrent calls — even
    with an IDENTICAL prompt AND identical cwd — get DISTINCT sentinels, and a
    marker embedded in a reviewed document/log cannot forge a live call's
    identity. Randomness defeats prediction and copy-from-a-past-log; the
    transcript-extractor's structural "the marker is the USER_INPUT footer" check
    (see _common._scan_transcript) defeats copy-from-a-concurrent-live-prompt.
    Format AGY_DONE_<32 lowercase hex>; the extractor + fake-agy match the marker
    length-agnostically."""
    return f"AGY_DONE_{secrets.token_hex(16)}"


def _build_cmd(prompt, sentinel, agy_sandbox, model, timeout, *, pydantic=False,
               skip_permissions=False):
    if pydantic:
        sealed = (
            f"{prompt}\n\n"
            f"Respond with the JSON object only — no prose, no markdown fences. "
            f"Immediately after the closing brace, on its own new line, emit the "
            f"exact completion marker <<<{sentinel}>>> and nothing after it. "
            f"The marker line is REQUIRED and is NOT part of the JSON."
        )
    else:
        sealed = (
            f"{prompt}\n\n"
            f"End your final answer with the exact marker <<<{sentinel}>>> "
            f"on its own line."
        )
    print_to = max(timeout - OFFSET_S, MIN_PRINT_TIMEOUT_S)
    cmd = ["agy", "-p", sealed, "--print-timeout", f"{print_to}s"]
    if agy_sandbox:
        cmd.append("--sandbox")
    if model:
        cmd += ["--model", model]
    if skip_permissions:
        cmd = _add_skip_permissions(cmd)
    return cmd


def _repair_cmd(cmd, err, sentinel):
    """Rebuild the agy cmd with a one-shot JSON-repair hint appended to the -p arg.

    RESEALS the prompt (P4 round-3, codex finding): `err` is DYNAMIC text (a
    pydantic validation message that can echo the failing value — potentially
    containing a marker-shaped string from reviewed content), and the
    transcript-identity rule keys on the LAST agy-marker in the USER_INPUT
    footer. Re-appending this call's own marker after the hint guarantees it
    stays last, so the repair re-run's transcript is still owned by THIS call
    and can never be claimed by (or claim) another live call's sentinel."""
    new = list(cmd)
    i = new.index("-p") + 1
    new[i] = (new[i] + f"\n\nYour previous output was NOT valid JSON for the "
              f"schema ({err}). Output ONLY corrected JSON, then the marker "
              f"line <<<{sentinel}>>> on its own new line.")
    return new


def _classify_no_answer(scrubbed: str, killed: bool, vendor_rc: int) -> tuple:
    """§6: decide classification for the no-answer case. Returns (cls, exit)."""
    if killed:
        return "timeout", _common.EXIT_TIMEOUT
    if not scrubbed.strip():
        return "extraction-error", _common.EXIT_CLI_FAIL
    cls = _common.classify(
        "antigravity", stderr=scrubbed, stdout="",
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
# file intact) -> the SKILL's absolute-path output-file contract.
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


def _agy_needs_skip_permissions(agy_bin) -> bool:
    """True when the installed agy version soft-denies headless tools and the
    operator has NOT opted out (AGY_NO_HEADLESS_AUTOAPPROVE=1). Deterministic
    (version compare, ~instant) — no per-dispatch probe. Version-adaptive: the
    wrapper follows agy instead of pinning a version, so updates keep flowing.
    An unparseable/failed `--version` is treated as NOT needing the flag
    (fail-safe toward the stronger deny-transaction isolation)."""
    if os.environ.get("AGY_NO_HEADLESS_AUTOAPPROVE") == "1":
        return False
    try:
        proc = subprocess.run([agy_bin, "--version"], capture_output=True,
                              text=True, timeout=15,
                              env=_common.scrubbed_child_env())
    except (OSError, subprocess.SubprocessError):
        return False
    # Fail-safe (merge-review F4/Q4): a NON-ZERO `--version` exit is an
    # unreliable read — even if its stdout happens to carry a semver, do not
    # trust it to enable the isolation-voiding flag. Only a clean rc=0 counts.
    if proc.returncode != 0:
        return False
    ver = _parse_agy_version(proc.stdout)
    return ver is not None and ver >= _HEADLESS_SOFTDENY_FLOOR


def _run_agy_with_retry(cmd, prompt, timeout, *, expected_sentinel,
                        cwd=None, sandbox=False, model=None,
                        repair_mode=False, pydantic_cls=None) -> AgyResult:
    """Dedicated driver (design §6): pty-run -> scrub -> extract -> classify
    with a bounded server-capacity retry (cap SERVER_CAP_RETRIES).

    Decision table (extract-then-classify so a rc=0 auth banner the model
    quotes inside a real answer never mis-classifies; ORDER MATTERS):
      - killed          -> ("timeout", EXIT_TIMEOUT)   [FIRST — P4 round 2:
                            a killed run has no complete DONE record, so any
                            pty "answer" is partial, and its rc=128+signal
                            would otherwise hit the rc gate and mislabel a
                            retriable timeout as terminal vendor-error]
      - answer present + non-empty, vendor rc==0, own-line
        `<truncated N bytes|lines>` marker inside -> ("truncated-answer",
                            EXIT_TERMINAL)   [agy folded the middle of the
                            answer CLI-side and kept no full copy anywhere
                            (transcript DONE record is capped too) — lossy,
                            never a silent ok, never classify/repair; answer
                            quarantined like vendor-error; leader re-dispatches
                            under the output-file contract]
      - answer present + non-empty, vendor rc==0 -> ("ok", EXIT_OK)
                                                     [classify NOT called]
      - answer present + non-empty, vendor rc!=0 -> ("vendor-error",
                            EXIT_TERMINAL)   [P4 rc gate — never a silent ok,
                            never via classify; answer quarantined from stdout,
                            bounded copy in extraction_error -> run-log]
      - sentinel found, body empty -> ("extraction-error", EXIT_CLI_FAIL)
                                       [direct — NOT via classify, whose blob
                                        still holds the marker and would
                                        misroute an empty answer to unknown]
      - clean + empty   -> ("extraction-error", EXIT_CLI_FAIL)
      - else            -> classify(antigravity, scrubbed) -> mapped exit;
                            server-capacity retries the whole pty run.

    Two INDEPENDENT retry budgets (F-Q2): `server_attempt` governs the
    server-capacity retry (cap SERVER_CAP_RETRIES), while `schema_repaired`
    is a one-shot bool for the single schema-repair re-run. They are
    decoupled — a transient server-capacity blip never consumes the lone
    schema-repair slot, and a schema repair never reduces the server-cap
    budget. The schema-repair re-run fires exactly once regardless of
    `repair_mode` (schema validity is orthogonal to the classifier re-run
    that `repair_mode` governs).

    `repair_mode` disables the server-capacity retry (the repair agent IS the
    retry — spec §4 + agy-wrapper-repair.md). `cwd` is a normal kwarg
    (defaults None) — no instance state, so the t15 monkeypatched calls that
    omit cwd work unchanged. The scrubbed transcript is carried on EVERY
    return path (FIX 1) so the run-log feeds the repair agent the literal error.
    """
    # Next-run IPC cleanup (owner contract) — see run_cli_with_retry. agy has
    # its own driver, so the prune-at-START is wired here too. Skipped in
    # repair_mode (repair agent is inspecting the run-log).
    if not repair_mode:
        _common.prune_stale_run_logs("antigravity")

    max_retries = 0 if repair_mode else SERVER_CAP_RETRIES
    server_attempt = 0       # server-capacity retry budget (independent)
    schema_repaired = False  # one-shot schema-repair (independent of server-cap + repair_mode)
    skip_retried = False     # one-shot headless soft-deny -> skip-permissions retry
    while True:
        # P4.5 transcript-read transport (spike-verified 2026-07-05): snapshot
        # agy's per-conversation transcript store BEFORE the run so the new
        # conversation (this call's) is identifiable afterward.
        _brain_before = _common.snapshot_agy_transcripts()
        # env=None => _pty inherits the SCRUBBED child env (loader/interpreter
        # injection vars dropped via _common.scrubbed_child_env, I-2/I-3) — the
        # agy-transport equivalent of _run_once's Popen env= scrub.
        result = _pty.run_via_pty(cmd, cwd=cwd, timeout=timeout, env=None)
        scrubbed = _common.scrub_agy_output(result.output_bytes)
        if result.killed:
            # Killed short-circuit (P4 review round 2, 3-family convergent):
            # a killed run has no complete DONE record — that is exactly why
            # transcript-read is skipped for it — so any pty-scrub "answer"
            # (e.g. an early-echoed marker) is partial and unreliable, and a
            # kill reaps rc=128+signal, which would otherwise fall into the
            # rc gate and mislabel a retriable timeout as terminal
            # vendor-error. The scrubbed partial output still reaches the
            # run-log for inspection.
            return AgyResult(None, "timeout", _common.EXIT_TIMEOUT,
                             result.rc, scrubbed_output=scrubbed)
        # PRIMARY: read the complete answer from agy's own transcript.jsonl
        # (the identity anchor is the USER_INPUT footer, so a long answer that
        # drops the trailing marker is still recovered). FALLBACK to
        # pty-scrub+sentinel.
        answer = _common.extract_agy_answer_from_transcript(
            None, _brain_before, sentinel=expected_sentinel)
        ext_err = None
        if answer is None:
            answer, ext_err = _common.extract_antigravity_answer(
                scrubbed, result.killed, expected_sentinel)
        if answer is not None and answer.strip():
            if result.rc != 0:
                # rc gate (P4). success => rc=0 (agy audit: 36/36 ok at rc=0).
                # A non-empty answer at a FAILING vendor rc is NOT a silent ok,
                # and is NOT fed to classify (a real answer can quote error-shaped
                # tokens -> a spurious server-capacity re-run / oauth-env terminal
                # that discards a valid answer). A DISTINCT token routed to
                # surface-not-repair: reusing `extraction-error` would MANDATE a
                # repair-agent dispatch (SKILL Hard rule 8) and violate its
                # documented "rc=0, no answer" invariant. The answer is
                # QUARANTINED from stdout (final_answer=None, like every other
                # failure); a bounded copy rides in extraction_error so the
                # RUN-LOG genuinely carries it even when it was recovered from
                # the transcript (not the pty output) — review round-2 fix.
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "vendor-error", _common.EXIT_TERMINAL,
                                 result.rc, scrubbed_output=scrubbed,
                                 extraction_error=(
                                     f"vendor rc={result.rc} returned a non-empty "
                                     f"answer; surfaced as vendor-error (not ok, "
                                     f"not repair). quarantined answer: {snippet}"))
            if _AGY_TRUNCATION_MARKER_RE.search(answer):
                # Vendor mid-answer fold (see _AGY_TRUNCATION_MARKER_RE note):
                # the answer LOOKS complete but its middle was replaced by the
                # marker and the lost bytes exist nowhere agy-side. Never a
                # silent ok. Driver-emitted terminal token (NOT classify, NOT
                # repair — deterministic vendor behavior on the answer-present
                # path, which a classifier patch cannot express; mirrors the
                # vendor-error quarantine). Leader remediation = re-dispatch
                # under the SKILL's absolute-path output-file contract
                # (write_file is not subject to the fold).
                snippet = answer if len(answer) <= 2000 else answer[:2000] + " …[truncated]"
                return AgyResult(None, "truncated-answer", _common.EXIT_TERMINAL,
                                 result.rc, scrubbed_output=scrubbed,
                                 extraction_error=(
                                     "agy folded the answer mid-body "
                                     "(own-line <truncated N bytes|lines> marker); "
                                     "lossy and unrecoverable at this layer. "
                                     f"quarantined answer: {snippet}"))
            if pydantic_cls is None:
                return AgyResult(answer, "ok", _common.EXIT_OK, result.rc,
                                 scrubbed_output=scrubbed)
            ok, payload = validate_response(answer, pydantic_cls)
            if ok:
                return AgyResult(answer, "ok", _common.EXIT_OK, result.rc,
                                 scrubbed_output=scrubbed, validated=payload)
            if not schema_repaired:   # exactly one schema-repair re-run, independent
                cmd = _repair_cmd(cmd, payload, expected_sentinel)
                schema_repaired = True
                continue
            return AgyResult(answer, "schema-fail", _common.EXIT_SCHEMA_FAIL,
                             result.rc, scrubbed_output=scrubbed,
                             extraction_error=f"schema: {payload}")
        if answer is not None:
            # Sentinel present but the answer body is empty — a real
            # extraction failure, NOT a silent empty ok. Do not fall through
            # to classify (the scrubbed blob still carries the marker).
            return AgyResult(None, "extraction-error", _common.EXIT_CLI_FAIL,
                             result.rc, scrubbed_output=scrubbed,
                             extraction_error="empty-answer-body")
        # agy 1.1.3+ headless soft-deny adaptation (owner-authorized 2026-07-18).
        # When agy auto-denied a tool because print mode cannot prompt, the ONLY
        # way the (read-only-intent) dispatch can run its tools is to
        # auto-approve permissions. Retry ONCE with --dangerously-skip-permissions.
        # SELF-ADAPTING + TARGETED: keyed on the exact vendor signature, so it
        # NEVER fires on a version where the allow-list works (<=1.1.2, any future
        # fix) — the wrapper follows agy's behavior instead of pinning a version.
        # Opt-out: AGY_NO_HEADLESS_AUTOAPPROVE=1 (strict deployments; agy then
        # stays unusable headless but no auto-approve).
        # CAVEAT: --dangerously-skip-permissions VOIDS the deny transaction (write
        # and command tools become auto-approved too — Deny>Allow no longer holds).
        # The dispatch's containment then rests on the review INTENT + disposable
        # --cwd + leader verification, NOT the deny list. Documented in the SKILL
        # § Isolation + the safety boundary.
        if (answer is None and not skip_retried
                and _is_headless_softdeny(scrubbed)
                and os.environ.get("AGY_NO_HEADLESS_AUTOAPPROVE") != "1"):
            cmd = _add_skip_permissions(cmd)
            skip_retried = True
            continue
        cls, code = _classify_no_answer(scrubbed, result.killed, result.rc)
        if cls == "server-capacity" and server_attempt < max_retries:
            _server_cap_backoff(server_attempt)
            server_attempt += 1
            continue
        return AgyResult(None, cls, code, result.rc, scrubbed_output=scrubbed,
                         extraction_error=ext_err)


def _server_cap_backoff(attempt: int) -> None:
    """Politeness sleep before a server-capacity retry (FIX 5). Suppressible
    via AGY_NO_BACKOFF=1 so unit/integration tests don't sleep 15s+."""
    if os.environ.get("AGY_NO_BACKOFF") == "1":
        return
    idx = min(attempt, len(_common.SERVER_CAP_BACKOFF_S) - 1)
    time.sleep(_common.SERVER_CAP_BACKOFF_S[idx])


def main() -> int:
    p = argparse.ArgumentParser(description="Antigravity (agy) single-shot wrapper",
                                allow_abbrev=False)
    prompt_group = p.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="User prompt")
    prompt_group.add_argument(
        "--prompt-file",
        help="Read the user prompt from a UTF-8 file (L12; containment applies "
             "under TRIAD_WRAPPER_ALLOWED_ROOTS)")
    p.add_argument("--cwd", default=None)
    p.add_argument("--sandbox", choices=["read-only", "workspace-write"],
                   default=None,
                   help="read-only|workspace-write — per-call deny transaction "
                        "(global settings mutate+restore). Omit = permissive baseline.")
    p.add_argument("--model", default=None)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--repair-mode", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--pydantic", default=None,
                   help="pydantic class spec (module:Class) — prompt-instructed "
                        "JSON + validate (agy has no native schema)")
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

    sandbox_mode = args.sandbox
    if sandbox_mode == "workspace-write":
        if not args.cwd:
            _common.log("--sandbox workspace-write requires --cwd (isolated worktree)")
            return _common.EXIT_ARG_ERROR
        if not os.path.isabs(args.cwd) or not os.path.isdir(args.cwd):
            _common.log("--sandbox workspace-write --cwd must be an absolute existing directory (isolated worktree)")
            return _common.EXIT_ARG_ERROR

    deny_rules = _agy_settings.build_deny_rules(sandbox_mode) if sandbox_mode else []
    agy_sandbox = sandbox_mode is not None  # both modes pass agy --sandbox (terminal ring)
    try:
        settings_lock_timeout = float(os.environ.get("AGY_SETTINGS_LOCK_TIMEOUT", "30"))
    except ValueError:
        _common.log("AGY_SETTINGS_LOCK_TIMEOUT must be a number")
        return _common.EXIT_ARG_ERROR

    sentinel = _make_sentinel()
    eff_prompt = inject_schema_to_prompt(args.prompt, pydantic_cls) if pydantic_cls else args.prompt
    # agy 1.1.3+ headless soft-deny adaptation (owner-authorized 2026-07-18):
    # version-gated auto-approve so a read-only-INTENT dispatch can actually run
    # its own read tools (the vendor stopped consulting the allow-list in print
    # mode). See _agy_needs_skip_permissions + § Isolation caveat.
    skip_permissions = _agy_needs_skip_permissions(agy_bin)
    cmd = _build_cmd(eff_prompt, sentinel, agy_sandbox, args.model, args.timeout,
                     pydantic=pydantic_cls is not None,
                     skip_permissions=skip_permissions)
    # argv[0] = resolved/pinned agy path (finding #3). _build_cmd stays pure ("agy"
    # literal) so its unit test is unaffected; the pin is substituted here at the
    # run site so a PATH shadow cannot win when the pty execs argv[0].
    cmd[0] = agy_bin

    start = time.monotonic()
    r: Optional[AgyResult] = None
    try:
        with _agy_settings.agy_settings_guard(
            deny_rules,
            lock_timeout=settings_lock_timeout,
        ):
            r = _run_agy_with_retry(cmd, args.prompt, args.timeout,
                                    expected_sentinel=sentinel, cwd=args.cwd,
                                    sandbox=agy_sandbox, model=args.model,
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
                # for a transcript-recovered vendor-error answer this carries
                # the only run-log copy of the quarantined answer.
                extraction_error += f" | prior: {prior.extraction_error}"
        r = AgyResult(
            None,
            "config-conflict",
            _common.EXIT_TERMINAL,
            prior.vendor_exit_code if prior is not None else -1,
            scrubbed_output=prior.scrubbed_output if prior is not None else "",
            extraction_error=extraction_error,
        )
    elapsed = time.monotonic() - start

    # Build a RunResult for the shared audit / run-log / debug helpers.
    # Convention (matches the generic run_cli_with_retry): RunResult.stdout =
    # the RAW vendor transcript (here the scrubbed pty output), final_answer =
    # the extracted answer (or ""). emit_run_log writes result.stdout, so the
    # failure run-log now carries the literal transcript for the repair agent
    # (FIX 1) instead of an empty string on unknown/oauth-env/extraction-error.
    rr = _common.RunResult(
        exit_code=r.exit_code,
        stdout=r.scrubbed_output,
        stderr="",
        elapsed_s=elapsed,
        classification=r.classification,
        mode="repair" if args.repair_mode else "normal",
        final_answer=r.final_answer or "",
        extraction_error=r.extraction_error,
        vendor_exit_code=r.vendor_exit_code,
    )

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
