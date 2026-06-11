#!/usr/bin/env python3
"""Single-shot Gemini CLI subprocess wrapper.

Always runs in vendor JSON mode:
  gemini -p ... --output-format json --approval-mode ...

Stdout = Gemini's final response text (or, with --pydantic, the validated
JSON object). Stderr = wrapper log + Gemini's two-line warning noise
(Ripgrep / 256-color).

Audit log: _logs/gemini/audit.jsonl (gitignored).

Options:
  --model <name>
        Pin a specific model (free-form). Default = CLI Auto router.
        Use sparingly — model names rot; verify with `/model manage`.
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
import sys

from _common import (
    EXIT_ARG_ERROR,
    audit,
    debug_log,
    emit_run_log,
    load_pydantic_class,
    log,
    require_binary,
    run_cli_with_retry,
)


APPROVAL_CHOICES = ("default", "auto_edit", "plan", "yolo")


def main() -> int:
    p = argparse.ArgumentParser(description="Gemini CLI single-shot wrapper")
    p.add_argument("--prompt", required=True, help="User prompt")
    p.add_argument(
        "--approval-mode",
        default="default",
        choices=APPROVAL_CHOICES,
        help="Approval mode (default: default — read auto, write/shell prompt)",
    )
    p.add_argument("--cwd", default=None, help="Process working directory")
    p.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    p.add_argument(
        "--skip-trust",
        action="store_true",
        help="Skip workspace trust dialog",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Pin a specific model (free-form). Default = CLI Auto router.",
    )
    p.add_argument(
        "--pydantic",
        default=None,
        help="pydantic class spec (module.path:ClassName) for schema enforcement",
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
             "_debug/<UTC-YYYY-MM-DD>/gemini.md (per-call summary)",
    )
    args = p.parse_args()

    if not args.prompt.strip():
        log("empty prompt")
        return EXIT_ARG_ERROR

    require_binary("gemini")

    pydantic_cls = None
    if args.pydantic:
        try:
            pydantic_cls = load_pydantic_class(args.pydantic)
        except Exception as e:
            log(f"--pydantic load failed: {e}")
            return EXIT_ARG_ERROR

    def build_cmd(effective_prompt: str) -> list[str]:
        cmd = [
            "gemini",
            "-p", effective_prompt,
            "--approval-mode", args.approval_mode,
            "--output-format", "json",
        ]
        if args.model:
            cmd += ["-m", args.model]
        if args.skip_trust:
            cmd.append("--skip-trust")
        return cmd

    result = run_cli_with_retry(
        "gemini",
        build_cmd,
        args.prompt,
        cwd=args.cwd,
        timeout=args.timeout,
        pydantic_cls=pydantic_cls,
        last_msg_path=None,
        repair_mode=args.repair_mode,
    )

    audit_cmd = build_cmd(args.prompt)
    audit("gemini", audit_cmd, args.prompt, result)

    if args.debug:
        debug_log("gemini", args.prompt, result)

    # Per-execution run-log (failure only) — dispatch SKILL input artifact.
    run_log_path = emit_run_log("gemini", sys.argv, audit_cmd, args.prompt, result)
    if run_log_path is not None:
        log(f"run-log: {run_log_path}")

    if pydantic_cls and result.validated is not None:
        sys.stdout.write(json.dumps(result.validated, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(result.final_answer or "")
        if result.final_answer and not result.final_answer.endswith("\n"):
            sys.stdout.write("\n")
    sys.stdout.flush()
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
