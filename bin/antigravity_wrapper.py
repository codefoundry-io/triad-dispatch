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
import hashlib
import os
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


def _make_sentinel(prompt: str, attempt: int) -> str:
    """Deterministic per-call id (no random / Date — reproducible).

    Hashes the FULL prompt (plus length + attempt), not a 64-char prefix, so
    two prompts sharing a long common prefix cannot collide on the sentinel.
    """
    h = hashlib.sha1(
        f"{len(prompt)}:{prompt}:{attempt}".encode()
    ).hexdigest()[:10]
    return f"AGY_DONE_{h}"


def _build_cmd(prompt, sentinel, agy_sandbox, model, timeout, *, pydantic=False):
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
    return cmd


def _repair_cmd(cmd, err):
    """Rebuild the agy cmd with a one-shot JSON-repair hint appended to the -p arg."""
    new = list(cmd)
    i = new.index("-p") + 1
    new[i] = (new[i] + f"\n\nYour previous output was NOT valid JSON for the "
              f"schema ({err}). Output ONLY corrected JSON, then the marker line.")
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


def _run_agy_with_retry(cmd, prompt, timeout, *, expected_sentinel,
                        cwd=None, sandbox=False, model=None,
                        repair_mode=False, pydantic_cls=None) -> AgyResult:
    """Dedicated driver (design §6): pty-run -> scrub -> extract -> classify
    with a bounded server-capacity retry (cap SERVER_CAP_RETRIES).

    Decision table (extract-then-classify so a rc=0 auth banner the model
    quotes inside a real answer never mis-classifies):
      - answer present + non-empty -> ("ok", EXIT_OK)   [classify NOT called]
      - sentinel found, body empty -> ("extraction-error", EXIT_CLI_FAIL)
                                       [direct — NOT via classify, whose blob
                                        still holds the marker and would
                                        misroute an empty answer to unknown]
      - killed          -> ("timeout", EXIT_TIMEOUT)
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
    while True:
        # P4.5 transcript-read transport (spike-verified 2026-07-05): snapshot
        # agy's per-conversation transcript store BEFORE the run so the new
        # conversation (this call's) is identifiable afterward.
        _brain_before = _common.snapshot_agy_transcripts()
        result = _pty.run_via_pty(cmd, cwd=cwd, timeout=timeout, env=None)
        scrubbed = _common.scrub_agy_output(result.output_bytes)
        # PRIMARY: read the complete answer from agy's own transcript.jsonl
        # (sentinel-independent — kills the "long answer drops the trailing
        # marker" data-loss class). Only on a NON-killed run (a killed/timeout
        # run has no complete DONE record). FALLBACK to pty-scrub+sentinel.
        answer = ext_err = None
        if not result.killed:
            answer = _common.extract_agy_answer_from_transcript(
                None, _brain_before, sentinel=expected_sentinel)
        if answer is None:
            answer, ext_err = _common.extract_antigravity_answer(
                scrubbed, result.killed, expected_sentinel)
        if answer is not None and answer.strip():
            if pydantic_cls is None:
                return AgyResult(answer, "ok", _common.EXIT_OK, result.rc,
                                 scrubbed_output=scrubbed)
            ok, payload = validate_response(answer, pydantic_cls)
            if ok:
                return AgyResult(answer, "ok", _common.EXIT_OK, result.rc,
                                 scrubbed_output=scrubbed, validated=payload)
            if not schema_repaired:   # exactly one schema-repair re-run, independent
                cmd = _repair_cmd(cmd, payload)
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
    p = argparse.ArgumentParser(description="Antigravity (agy) single-shot wrapper")
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

    sentinel = _make_sentinel(args.prompt, 0)
    eff_prompt = inject_schema_to_prompt(args.prompt, pydantic_cls) if pydantic_cls else args.prompt
    cmd = _build_cmd(eff_prompt, sentinel, agy_sandbox, args.model, args.timeout,
                     pydantic=pydantic_cls is not None)
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
