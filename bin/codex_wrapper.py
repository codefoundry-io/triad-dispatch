#!/usr/bin/env python3
"""Single-shot Codex CLI subprocess wrapper.

Always runs in vendor JSON mode:
  codex exec --json -o <last_msg_file> --ephemeral ...

Stdout = the final agent message text (or, with --pydantic, the validated
JSON object). Stderr = wrapper log + Codex's brief 39 B header.

Audit log: _logs/codex/audit.jsonl (gitignored).

Options:
  --reasoning {low,medium,high,xhigh}
        Override model_reasoning_effort (`-c model_reasoning_effort=...`).
        Default = vendor default. Read-only deep work → high. Heavy
        write/exec deep → xhigh (5h cap token burn — verify status first).
  --pydantic module.path:ClassName
        Inject a JSON schema block into the prompt and validate the answer
        with `cls.model_validate_json()`. On validation fail, retry once
        with a clarifying suffix; second failure → exit 66.
  --repair-mode
        Internal: invoked by Sonnet repair sub-agent (server-cap retry=0).
"""
from __future__ import annotations

import argparse
import codex_tasks
import json
import os
import sys
import tempfile

from _common import (
    EXIT_ARG_ERROR,
    EXIT_FANOUT_PARTIAL,
    EXIT_OK,
    EXIT_TASK_BLOCKED,
    audit,
    debug_log,
    emit_run_log,
    extract_implementer_status,
    load_pydantic_class,
    log,
    prune_stale_tmp_dirs,
    pydantic_to_codex_schema,
    require_binary,
    run_cli_with_retry,
)


SANDBOX_CHOICES = ("read-only", "workspace-write")  # danger-full-access banned (triad no-yolo invariant)
REASONING_CHOICES = ("low", "medium", "high", "xhigh")


def write_fanout_report(
    report_dir: str, task: str, synthesis: str, agents: list, partial: bool
) -> list[str]:
    """Write codex-<task>-synthesis.md + codex-<task>-agentN-raw.md. Returns paths."""
    os.makedirs(report_dir, exist_ok=True)
    paths = []
    banner = (
        "> **INCOMPLETE** — one or more subagents did not complete; this "
        "synthesis is partial.\n\n"
    ) if partial else ""
    syn_path = os.path.join(report_dir, f"codex-{task}-synthesis.md")
    with open(syn_path, "w", encoding="utf-8") as f:
        f.write(banner + (synthesis or ""))
    paths.append(syn_path)
    for i, a in enumerate(agents, 1):
        raw_path = os.path.join(report_dir, f"codex-{task}-agent{i}-raw.md")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(a.get("message") or "")
        paths.append(raw_path)
    return paths


def fanout_is_partial(complete: bool, agents: list, fanout) -> bool:
    """A --task fan-out is partial if extraction said incomplete, OR (for an
    explicit integer --fanout N) fewer than N subagents reached a terminal state."""
    if not complete:
        return True
    if isinstance(fanout, int) and len(agents) < fanout:
        return True
    return False


def codex_invocation(search: bool) -> list[str]:
    """Leading `codex [--search] exec` argv. codex's `--search` (live web search via
    the native Responses web_search tool) is a TOP-LEVEL flag — it MUST precede the
    `exec` subcommand (`codex --search exec ...`; `codex exec --search` errors with
    "unexpected argument"). Emitted ONLY when search=True, so the default stays the
    cheap no-search path."""
    return ["codex"] + (["--search"] if search else []) + ["exec"]


def main() -> int:
    p = argparse.ArgumentParser(description="Codex CLI single-shot wrapper")
    p.add_argument("--prompt", required=True, help="User prompt")
    p.add_argument(
        "--sandbox",
        default=None,
        choices=SANDBOX_CHOICES,
        help="Sandbox policy (default: read-only for raw calls; pinned per --task)",
    )
    p.add_argument("--cwd", default=None, help="Process working directory")
    p.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    p.add_argument(
        "--reasoning",
        default=None,
        choices=REASONING_CHOICES,
        help="Override model_reasoning_effort (default: vendor default)",
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
        "--image",
        action="append",
        default=None,
        help="Image file path for vision input (repeatable) -> codex -i",
    )
    p.add_argument(
        "--format",
        default=None,
        choices=("text", "markdown", "json"),
        help="Output intent: text/markdown=prose via -o file; json=loose JSON. "
             "Omit for auto (prose normally; json with --pydantic). "
             "Explicit markdown/text are mutually exclusive with --pydantic.",
    )
    p.add_argument(
        "--task",
        default=None,
        choices=tuple(codex_tasks.TASKS),
        help="Task type. Analysis tasks (review/analyze/brainstorm) are read-only "
             "fan-out; code task is workspace-write single-implementer. Augments "
             "the prompt with a deterministic framing from codex_tasks.py.",
    )
    p.add_argument(
        "--fanout",
        default=None,
        help="Fan-out tier (requires --task): int 1-12 (explicit N) or 'auto' "
             "(codex decides via skill). Omit for the task's default (3).",
    )
    # --report-dir / fanout_value are consumed by the --task wiring in a later task.
    p.add_argument(
        "--report-dir",
        default=None,
        help="Directory for --task report files (synthesis + per-agent raw). "
             "Default: a temp dir, path printed to stderr.",
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
    args = p.parse_args()

    # Next-run IPC cleanup: sweep prior leaked `codex_report_*` mkdtemp dirs
    # (the --task fan-out path auto-creates one per call and never unlinks it).
    # Age-floor protects the current run's dir, created later in this call.
    prune_stale_tmp_dirs("codex_report_")

    if not args.prompt.strip():
        log("empty prompt")
        return EXIT_ARG_ERROR

    if args.pydantic and args.format in ("markdown", "text"):
        log("--format markdown/text is mutually exclusive with --pydantic "
            "(use --format json or drop --pydantic)")
        return EXIT_ARG_ERROR

    if args.fanout is not None and args.task is None:
        log("--fanout requires --task")
        return EXIT_ARG_ERROR

    if args.task is not None and args.pydantic:
        log("--task and --pydantic are mutually exclusive "
            "(fan-out report vs schema validation are different modes)")
        return EXIT_ARG_ERROR
    if args.task is not None:
        task_sandbox = codex_tasks.TASKS[args.task]["sandbox"]
        if args.sandbox is not None and args.sandbox != task_sandbox:
            log(f"--task {args.task} pins --sandbox {task_sandbox}; refusing "
                f"conflicting --sandbox {args.sandbox} (drop --sandbox)")
            return EXIT_ARG_ERROR

    fanout_value = None
    if args.task is not None:
        if args.fanout is None:
            fanout_value = codex_tasks.TASKS[args.task]["default_fanout"]
        elif args.fanout == "auto":
            fanout_value = "auto"
        else:
            try:
                n = int(args.fanout)
            except ValueError:
                log(f"--fanout must be an int 1-12 or 'auto': {args.fanout!r}")
                return EXIT_ARG_ERROR
            if not (codex_tasks.FANOUT_MIN <= n <= codex_tasks.FANOUT_MAX):
                log(f"--fanout out of range 1-12: {n}")
                return EXIT_ARG_ERROR
            # code = single implementer: only N==1 (== default) is a valid explicit
            # int; N>1 conflicts. 'auto' (handled in the elif above) is the escalation.
            if args.task == "code" and n != 1:
                log("--task code runs a single implementer; explicit --fanout "
                    "N>1 conflicts (parallel edits on one workspace). For a "
                    "complex task use '--task code --fanout auto' (codex "
                    "self-decomposes); for a simple one omit --fanout.")
                return EXIT_ARG_ERROR
            fanout_value = n

    # Fix D: --task code requires --cwd (workspace-write edits would otherwise
    # land in the wrapper's own cwd = the live repo). Reject before any codex spawn.
    if args.task == "code" and args.cwd is None:
        log("--task code requires --cwd <isolated git worktree> (codex edits with "
            "workspace-write; without --cwd it would write into the current "
            "directory). Create a worktree and pass it as --cwd.")
        return EXIT_ARG_ERROR

    effective_user_prompt = args.prompt
    if args.task is not None:
        spec = codex_tasks.TASKS[args.task]
        args.sandbox = spec["sandbox"]  # pin per-task: read-only (analysis) / workspace-write (code)
        if args.format is None:
            args.format = spec["output_mode"]
        effective_user_prompt = codex_tasks.augment_prompt(
            args.task, fanout_value, args.prompt)
    elif args.sandbox is None:
        args.sandbox = "read-only"  # default for raw (non-task) calls

    require_binary("codex")

    if args.image:
        for img in args.image:
            if not os.path.isfile(img):
                log(f"--image path not found: {img}")
                return EXIT_ARG_ERROR

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

    # Per-PID last-message file (concurrent-safe).
    fd, last_msg_path = tempfile.mkstemp(prefix=f"codex_last_{os.getpid()}_", suffix=".txt")
    os.close(fd)

    def build_cmd(effective_prompt: str) -> list[str]:
        cmd = codex_invocation(args.search) + [
            "--sandbox", args.sandbox,
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
        if args.reasoning:
            # TOML string value (canonical -c form). Bare `=high` would rely on
            # codex's literal-string fallback; the quoted form is unambiguous.
            cmd += ["-c", f'model_reasoning_effort="{args.reasoning}"']
        if schema_path is not None:
            cmd += ["--output-schema", schema_path]
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

    audit_cmd = build_cmd(args.prompt)

    partial = False
    # Fan-out extraction only applies when codex is expected to spawn subagents
    # (analysis default_fanout=3, explicit N, or auto). A single implementer
    # (fanout_value == 1) produces no spawn markers, so extract_codex_fanout
    # would false-positive 'partial' on its empty-seen heuristic — skip it.
    # Fix B-68: the code task is also excluded — for code+auto, codex may
    # self-decide to work single-threaded (no spawn markers), which would
    # false-positive as partial-68 on a DONE task. The STATUS line (below) is
    # the authoritative signal for the code task.
    if args.task is not None and args.task != "code" and fanout_value != 1:
        from _common import extract_codex_fanout
        agents, complete = extract_codex_fanout(result.stdout)
        partial = fanout_is_partial(complete, agents, fanout_value)
        try:
            report_dir = args.report_dir or tempfile.mkdtemp(prefix="codex_report_")
            write_fanout_report(
                report_dir, args.task, result.final_answer or "", agents, partial=partial)
            log(f"report: {report_dir} ({len(agents)} agents, partial={partial})")
        except OSError as e:
            # report writing is a side-effect — never lose the codex result over it
            log(f"report-write failed (non-fatal, result preserved): {e}")
        if partial and result.exit_code == 0:
            result.exit_code = EXIT_FANOUT_PARTIAL
            log(f"[wrapper] codex fanout-partial exit={result.exit_code} "
                f"vendor={result.vendor_exit_code} elapsed={result.elapsed_s:.1f}s")
        elif partial:
            # underlying codex call already failed (non-zero) — the real exit code
            # and its [wrapper] classification take priority; do NOT mask it with 68
            # nor add the partial banner to stdout.
            log(f"fanout-partial suppressed — real failure exit={result.exit_code} "
                f"takes priority over the partial-fanout signal")
            partial = False

    # Archetype B: code task self-reported BLOCKED/NEEDS_CONTEXT → exit 69 so the
    # SKILL can branch (skip verify/commit, re-dispatch with context) without
    # semantic parsing. Authoritative only over OK/68 — never masks a real failure.
    if args.task == "code" and result.exit_code in (EXIT_OK, EXIT_FANOUT_PARTIAL):
        status = extract_implementer_status(result.final_answer or "")
        if status in ("BLOCKED", "NEEDS_CONTEXT"):
            result.exit_code = EXIT_TASK_BLOCKED
            log(f"[wrapper] codex task-blocked status={status} "
                f"exit={result.exit_code} vendor={result.vendor_exit_code} "
                f"elapsed={result.elapsed_s:.1f}s")

    # Fix F: audit is called AFTER both exit-code promotions (partial→68 and
    # STATUS→69) so audit.jsonl records the final promoted exit code, not the
    # pre-promotion value.
    audit("codex", audit_cmd, args.prompt, result)

    if args.debug:
        debug_log("codex", args.prompt, result)

    # Per-execution run-log (failure only) — dispatch SKILL input artifact.
    run_log_path = emit_run_log("codex", sys.argv, audit_cmd, args.prompt, result)
    if run_log_path is not None:
        log(f"run-log: {run_log_path}")

    # Stdout = validated JSON (if --pydantic) or raw final answer.
    if pydantic_cls and result.validated is not None:
        sys.stdout.write(json.dumps(result.validated, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        out = result.final_answer or ""
        if partial:
            out = ("> **INCOMPLETE** — fan-out did not fully complete; this "
                   "output is partial (see the report). \n\n") + out
        sys.stdout.write(out)
        if out and not out.endswith("\n"):
            sys.stdout.write("\n")
    sys.stdout.flush()
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
