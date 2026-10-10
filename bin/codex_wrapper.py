#!/usr/bin/env python3
"""Single-shot Codex CLI subprocess wrapper.

Always runs in vendor JSON mode:
  codex exec --json -o <last_msg_file> --ephemeral ...

Stdout = the final agent message text (or, with --pydantic, the validated
JSON object). Stderr = wrapper log + Codex's brief 39 B header.

Audit log: _logs/codex/audit.jsonl (gitignored).

Options:
  --reasoning {low,medium,high,xhigh,max}
        Override model_reasoning_effort (`-c model_reasoning_effort=...`).
        Default = vendor default. Read-only deep work → high; deep
        architecture / long refactor → xhigh; hardest problems → max
        (the top pure-depth tier the wrapper exposes; 5h cap token burn —
        verify status first). `ultra` (max reasoning + automatic subagent
        delegation) is intentionally NOT exposed: it makes a single-shot
        dispatch runaway/over-long, and not every model variant supports
        it (an auto-routed dispatch could hit an ultra-less model).
  --pydantic module.path:ClassName
        Inject a JSON schema block into the prompt and validate the answer
        with `cls.model_validate_json()`. On validation fail, retry once
        with a clarifying suffix; second failure → exit 66.
  --repair-mode
        Internal: invoked by Sonnet repair sub-agent (server-cap retry=0).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from _common import (
    validate_wrapper_cwd,
    _emit_payload,
    _guarded_main,
    load_prompt_text,
    resolve_prompt_file,
    _ensure_within_runtime_roots,
    _resolve_input_file,
    _refusal_path,
    EXIT_ARG_ERROR,
    audit,
    debug_log,
    emit_run_log,
    install_terminal_signal_handlers,
    load_pydantic_class,
    log,
    pydantic_to_codex_schema,
    require_binary,
    run_cli_with_retry,
)


SANDBOX_CHOICES = ("read-only", "workspace-write")  # danger-full-access banned (triad no-yolo invariant)
REASONING_CHOICES = ("low", "medium", "high", "xhigh", "max")  # ultra excluded: self-delegates subagents (runaway single-shot) + not every variant supports it


def codex_invocation(search: bool) -> list[str]:
    """Leading `codex [--search] exec` argv. codex's `--search` (live web search via
    the native Responses web_search tool) is a TOP-LEVEL flag — it MUST precede the
    `exec` subcommand (`codex --search exec ...`; `codex exec --search` errors with
    "unexpected argument").

    Contract: --search OFF really means NO web search. Since codex 0.14x the
    vendor default for the `web_search` config is "cached" (an OpenAI-maintained
    index — a search tool is silently available even without --search), so the
    OFF branch pins `-c web_search="disabled"` to restore the advertised
    no-search default (review legs stay deterministic / offline). Verified
    against the official config reference (web_search: disabled|cached|live,
    default "cached") on 2026-07-04, codex-cli 0.142.5."""
    return ["codex"] + (["--search"] if search else []) + ["exec"]


def main() -> int:
    return _guarded_main("codex", _main)


def _main(ctx: dict) -> int:
    # SIGTERM/SIGHUP: from the first dispatch on the handler only records the
    # signal. During a dispatch _run_once reaps the vendor group and the run
    # ends as the interrupted-run record (`unknown` / 1), `oauth-env` / 65 on a
    # carrier STOP, or `timeout` / 2 when the run had already timed out (the
    # timeout verdict outranks it); a signal after the last _run_once
    # is not consumed (the completed answer is published). Before the first
    # dispatch the handler exits 128+signum (spec case C1 / R-TERMINAL).
    install_terminal_signal_handlers()
    p = argparse.ArgumentParser(description="Codex CLI single-shot wrapper",
                                allow_abbrev=False)
    prompt_group = p.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="User prompt")
    prompt_group.add_argument(
        "--prompt-file",
        help="Read the user prompt from a UTF-8 file (>=50K-char prompts: pass "
             "a file, not inline argv — L12; containment applies under "
             "TRIAD_WRAPPER_ALLOWED_ROOTS)")
    p.add_argument(
        "--sandbox",
        default=None,
        choices=SANDBOX_CHOICES,
        help="Sandbox policy (default: read-only)",
    )
    p.add_argument("--cwd", default=None, help="Process working directory")
    p.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    p.add_argument(
        "--reasoning",
        default=None,
        choices=REASONING_CHOICES,
        help="Override model_reasoning_effort (default: vendor default). "
             "Recorded as `reasoning=<tier>` on the `[wrapper] codex` summary "
             "line and as `requested_reasoning` in the audit row",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Override model for this dispatch (`-c model=\"<slug>\"`); free-form "
             "catalog slug from `codex debug models` (default: config-alive model). "
             "No slug is ever hardcoded here — dispatch-time pin only. "
             "Recorded as `model=<slug>` on the `[wrapper] codex` summary line and "
             "as `requested_model` in the audit row; absent = the CLI's config "
             "default was used (the round record freezes the roster value)",
    )
    p.add_argument(
        "--search",
        action="store_true",
        help="Enable codex live web search (codex's top-level --search, inserted before "
             "exec; default OFF — opt in for research/consult/review legs)",
    )
    p.add_argument(
        "--pydantic",
        default=None,
        help="pydantic class spec (module.path:ClassName) for schema enforcement",
    )
    p.add_argument(
        "--output-schema-file",
        default=None,
        help="Path (a relative one rebased on the process-entry cwd, C28) to a "
             "caller-owned JSON schema file, passed straight "
             "to codex --output-schema. Transport only: the wrapper validates "
             "nothing and retries nothing (the caller admits the answer with "
             "its own validator). Mutually exclusive with --pydantic",
    )
    p.add_argument(
        "--image",
        action="append",
        default=None,
        help="Image file path for vision input (repeatable) -> codex -i",
    )
    p.add_argument(
        "--repair-mode",
        action="store_true",
        help="Internal: invoked by Sonnet repair sub-agent (server-cap retry=0)",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Append a human-readable markdown row to "
             "_debug/<UTC-YYYY-MM-DD>/codex.md (per-call summary)",
    )
    p.add_argument(
        "--attempt",
        type=int,
        default=1,
        help="Dispatch attempt number carried on the transport receipt "
             "(>=1, default 1). RECORDED only — the wrapper never retries "
             "on it and no control flow reads it",
    )
    args = p.parse_args()
    # ONE NORMALIZED MODEL REQUEST (gate-1 r12 row r12-3). The argv build
    # dropped an empty `--model` by truthiness while the engine recorded
    # `requested_model=''`, and a whitespace-only value reached the vendor as
    # `-c model="   "`. Empty or whitespace-only = NO request; both sites
    # below read this one value.
    if args.model is not None and not args.model.strip():
        args.model = None
    ctx.update(attempt=args.attempt, model=args.model, reasoning=args.reasoning)

    if args.attempt < 1:
        log(f"--attempt must be >= 1 (got {args.attempt})")
        return EXIT_ARG_ERROR
    # C28: resolve the (possibly relative) --prompt-file once so the absolute
    # path can be RECORDED on the summary line and in the audit/run-log
    # records. load_prompt_text() re-resolves the same way and reads the text.
    _prompt_file_resolved = None
    try:
        if args.prompt_file:
            _prompt_file_resolved = str(resolve_prompt_file(args.prompt_file))
        _prompt_text = load_prompt_text(args.prompt, args.prompt_file)
    except Exception as e:
        log(f"prompt load failed: {e}")
        return EXIT_ARG_ERROR
    args.prompt = _prompt_text  # downstream code keeps using args.prompt
    ctx.update(prompt=args.prompt, prompt_file=_prompt_file_resolved)

    try:
        args.cwd = validate_wrapper_cwd(args.cwd)
    except Exception as e:
        log(f"--cwd validation failed: {e}")
        return EXIT_ARG_ERROR
    if args.sandbox == "workspace-write" and not args.cwd:
        log("--sandbox workspace-write requires --cwd (codex edits files in its "
            "working directory — the blast radius must be an isolated directory)")
        return EXIT_ARG_ERROR

    if not args.prompt.strip():
        log("empty prompt")
        return EXIT_ARG_ERROR

    # --output-schema-file: checked BEFORE any vendor work — a paid dispatch
    # that would run with no schema (or with the caller's schema silently
    # ignored) is worse than an argument error.
    if args.output_schema_file is not None:
        if args.pydantic:
            log("--output-schema-file and --pydantic are mutually exclusive "
                "(two schema sources for one --output-schema flag)")
            return EXIT_ARG_ERROR
        # C28 (spec ccf168a): a relative path is rebased on the process-entry
        # cwd like --prompt-file (codex itself would resolve it against the
        # child --cwd), then the same runtime-roots containment --image gets
        # (gate-1 r2 row r2-5: under TRIAD_WRAPPER_ALLOWED_ROOTS an out-of-root
        # schema is an uncontained file-read -> vendor channel). codex reads
        # exactly the RESOLVED file validated here, and the argv the audit row
        # records carries that absolute path.
        try:
            args.output_schema_file = str(_resolve_input_file(
                args.output_schema_file, "--output-schema-file"))
        except Exception as e:
            log(f"--output-schema-file validation failed: {e}")
            return EXIT_ARG_ERROR
    effective_user_prompt = args.prompt
    if args.sandbox is None:
        args.sandbox = "read-only"  # the default posture

    codex_bin = require_binary("codex")
    ctx["cmd"] = [codex_bin]

    if args.image:
        contained_images = []
        for img in args.image:
            if not os.path.isfile(img):
                log(f"--image path not found: {_refusal_path(img, '--image')}")
                return EXIT_ARG_ERROR
            # Route --image through the SAME runtime-roots containment as
            # --prompt-file (load_prompt_text) and --cwd (validate_wrapper_cwd):
            # under TRIAD_WRAPPER_ALLOWED_ROOTS an out-of-root image is an
            # uncontained file-read -> vendor channel (codex -i). Roots unset
            # (lab default) -> returned unchanged (resolved). Use the resolved
            # path so codex reads exactly the file we validated.
            try:
                img = str(_ensure_within_runtime_roots(Path(img), "--image"))
            except Exception as e:
                log(f"--image validation failed: {e}")
                return EXIT_ARG_ERROR
            contained_images.append(img)
        args.image = contained_images

    pydantic_cls = None
    if args.pydantic:
        try:
            pydantic_cls = load_pydantic_class(args.pydantic)
        except Exception as e:
            log(f"--pydantic load failed: {e}")
            return EXIT_ARG_ERROR

    # When --pydantic is given, build a strict massaged schema into a temp file
    # and pass --output-schema to codex for native enforcement.
    # belt-and-suspenders: prompt-side inject_schema_to_prompt + post-hoc
    # validate_response are both retained regardless.
    schema_path = None
    if pydantic_cls is not None:
        try:
            codex_schema = pydantic_to_codex_schema(pydantic_cls)
            fd2, schema_path = tempfile.mkstemp(
                prefix=f"codex_schema_{os.getpid()}_", suffix=".json")
            os.close(fd2)  # close fd immediately (mirror last_msg_path) — no
                           # fd leak if the subsequent open/dump raises.
            with open(schema_path, "w", encoding="utf-8") as f:
                json.dump(codex_schema, f)
        except Exception as e:
            log(f"--output-schema build failed: {e}")
            if schema_path is not None:
                try:
                    os.unlink(schema_path)
                except Exception:
                    pass
            return EXIT_ARG_ERROR

    # The value handed to codex --output-schema: either the wrapper-built
    # pydantic temp file (cleaned up below) or the caller's own file, which
    # the wrapper never writes, reads, or deletes.
    output_schema_arg = args.output_schema_file or schema_path

    # Per-PID last-message file (concurrent-safe).
    fd, last_msg_path = tempfile.mkstemp(prefix=f"codex_last_{os.getpid()}_", suffix=".txt")
    os.close(fd)

    def build_cmd(effective_prompt: str) -> list[str]:
        cmd = codex_invocation(args.search) + ["--sandbox", args.sandbox]
        # W16 (CFR S2, 2026-09-17; Tier 1: codex-rs/exec/src/cli.rs — "Do not
        # load user or project execpolicy `.rules` files"): an execpolicy rule
        # with decision="allow" runs its command OUTSIDE the sandbox without
        # prompting, so this host's ~/.codex/rules (git add/commit, gh ...,
        # rm -rf _runs) put a READ-ONLY review leg one operator rule away from
        # a real write. S2-9 (owner-accepted 2026-09-18): EVERY posture — a
        # wrapper dispatch pins approval_policy=never below and never wants an
        # escalation outside the sandbox on the write posture either; the
        # operator's allow rules were the one path around that pin. Inside
        # workspace-write the same commands still run when the sandbox permits
        # them; what goes away is the unsandboxed escape.
        cmd.append("--ignore-rules")
        cmd += [
            "--skip-git-repo-check",
            "--json",
            "-o", last_msg_path,
            "--ephemeral",
            # config-alive (global config inherited, no hermetic flag): pin approval=never
            # so inherited config can't auto-approve an escalation. Live web search is
            # controlled by --search (codex's native Responses web_search tool, enabled via
            # the top-level flag in codex_invocation); default OFF. (3-way review A, owner)
            "-c", "approval_policy=never",
        ]
        # argv[0] = resolved/pinned codex path (finding #3). codex_invocation
        # stays pure ("codex" literal) so its unit test is unaffected; the pin
        # is substituted here at the run site so a PATH shadow cannot win at exec.
        cmd[0] = codex_bin
        if not args.search:
            # Vendor default for `web_search` is "cached" since 0.14x (an
            # OpenAI-maintained index — a search tool is silently available even
            # without --search). Pin it off so --search OFF really means NO web
            # search (advertised contract; review legs stay deterministic).
            # Config reference verified 2026-07-04 (disabled|cached|live).
            cmd += ["-c", 'web_search="disabled"']
        if args.reasoning:
            # TOML string value (canonical -c form). Bare `=high` would rely on
            # codex's literal-string fallback; the quoted form is unambiguous.
            cmd += ["-c", f'model_reasoning_effort="{args.reasoning}"']
        if args.model:
            cmd += ["-c", f'model="{args.model}"']
        if output_schema_arg is not None:
            cmd += ["--output-schema", output_schema_arg]
        if args.image:
            for img in args.image:
                cmd += ["-i", img]
        # Prompt is delivered via stdin (not argv) — large-prompt safe and
        # shell-special-char safe. See run_cli_with_retry prompt_via_stdin.
        return cmd

    try:
        result = run_cli_with_retry(
            "codex",
            build_cmd,
            effective_user_prompt,
            cwd=args.cwd,
            timeout=args.timeout,
            pydantic_cls=pydantic_cls,
            last_msg_path=last_msg_path,
            repair_mode=args.repair_mode,
            prompt_via_stdin=True,
            dispatch_attempt=args.attempt,
            prompt_file_resolved=_prompt_file_resolved,
            requested_model=args.model,
            requested_reasoning=args.reasoning,
        )
    finally:
        try:
            os.unlink(last_msg_path)
        except Exception:
            pass
        if schema_path is not None:
            try:
                os.unlink(schema_path)
            except Exception:
                pass

    ctx["result"] = result
    audit_cmd = build_cmd(args.prompt)
    ctx["cmd"] = audit_cmd

    # The payload: ONE UTF-8 encode; a code point UTF-8 cannot carry (a lone
    # surrogate) leaves as its `\udXXX` escape, exit and token unchanged.
    if pydantic_cls and result.validated is not None:
        out = json.dumps(result.validated, ensure_ascii=False) + "\n"
    else:
        out = result.final_answer or ""
        if out and not out.endswith("\n"):
            out += "\n"
    payload = out.encode("utf-8", "backslashreplace")

    audit("codex", audit_cmd, args.prompt, result)
    ctx["recorded"] = True

    if args.debug:
        debug_log("codex", args.prompt, result)

    # Per-execution run-log (failure only; a v2 review attempt with
    # TRIAD_REVIEW_LOG_DIR: every outcome) — dispatch SKILL input artifact.
    run_log_path = emit_run_log("codex", sys.argv, audit_cmd, args.prompt, result)
    if run_log_path is not None:
        log(f"run-log: {run_log_path}")

    # Stdout = validated JSON (if --pydantic) or raw final answer, as the
    # bytes built above.
    _emit_payload(payload)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
