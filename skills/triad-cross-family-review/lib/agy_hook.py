#!/usr/bin/env python3
"""agy_hook.py — the agy leg's PreToolUse hook and its LOAD CHECK
(triad-cross-family-review, S2 enforcement — plan
2026-09-16-cfr-delivery-and-enforcement-redesign § Enforcement).

Two modes, one file, python3 stdlib only, no AI:

  hook mode    agy_hook.py --log <abs-jsonl>
      agy runs this on EVERY tool call of a review leg (the round worktree's
      `.agents/hooks.json`, written by `review_scratch.py prepare`, matcher
      "*"). stdin: the vendor's PreToolUse payload (`toolCall.name`,
      `toolCall.args`, `conversationId`, `stepIdx`, ...); stdout: ONE JSON
      object `{"decision": "allow"}` or `{"decision": "deny", "reason": ...}`.
      `decide()` is the whole policy: a fixed set of MUTATING / command /
      network / subagent / planner tools is denied, everything else — every
      read tool, every tool this table has never heard of — is allowed. Reads
      are never denied on purpose: a broken hook denies every call including
      reads and the leg produces no answer at all (measured 2026-09-16, arm
      C), so this handler stays small enough to be obviously correct. A
      payload it cannot read, or a call with no name, is DENIED (fail-closed;
      that is loud, never a silent write). One JSON line per invocation is
      appended to --log — tool, decision, conversation id, step index — and
      NEVER the tool arguments (a write's args carry the file body). A log the
      hook cannot write is reported on stderr and the decision still answers.

  check mode   agy_hook.py check <abs-read-audit.json> <abs-hook-log.jsonl>
      The LOAD CHECK the redesign owes: `--agent <unknown>` fails OPEN
      silently (measured 2026-09-16 — a bogus agent name yields a fully
      write-capable default and the stream cannot tell), so the round must
      PROVE the hook layer loaded. Zero hook invocations while the read audit
      counts tool_steps > 0 means the enforcement layer did not load — VOID.
      One invocation proves it did — PASS; an equality is NOT required: a call
      the vendor rejects at argument validation never reaches the hook
      (measured 2026-09-17: 4 tool steps, 3 invocations). No tool call and no
      log proves nothing — INCONCLUSIVE (the read-audit gate voids a read-blind
      leg on its own). stdout ends with the greppable summary
      `HOOK_LOAD_<VERDICT> tool_steps=<n> invocations=<n> denied=<n>`;
      exit 0 PASS / 2 ABSENT (no read audit) / 3 VOID / 4 INCONCLUSIVE /
      64 usage.

Measured vocabulary (agy 1.2.5, 2026-09-17): a denied call reaches the stream
as state ERROR with tool_info.error.message "tool call denied by pre-tool
hook: <reason>"; the run stays SUCCESS / rc 0 and the file is never written.
The wrapper's admission census reads that denial as BLOCKED (logged, not
voiding) — an off-list call that EXECUTES still voids the answer.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# The MEASURED registry (57 tools advertised by agy 1.2.5 to a print-mode
# agent), classified once: every name below mutates the filesystem, runs a
# command, reaches the network / a browser / an MCP server, spawns or messages
# an agent, or plans out of band. Not here: the five review tools (view_file,
# grep_search, list_dir, find_by_name, finish), the permission-prompt tools
# (ask_*, list_permissions) and the waits — none of them has an effect a
# review leg must not have. The `browser_*` family is a prefix (16 names).
DENY_TOOLS = frozenset({
    # filesystem mutation
    "write_to_file", "replace_file_content", "multi_replace_file_content",
    "sed_file", "notebook_edit", "notebook_execution", "delete_knowledge",
    # command execution
    "run_command", "send_command_input", "command_status",
    # network / browser (the un-prefixed members of the browser family)
    "read_url_content", "search_web", "open_browser_url",
    "capture_browser_console_logs", "capture_browser_screenshot",
    "click_browser_pixel", "execute_browser_javascript", "list_browser_pages",
    "read_browser_page",
    # subagents / messaging / planning
    "define_subagent", "invoke_subagent", "manage_subagents",
    "send_message", "manage_task", "manage_inbox", "schedule",
    # MCP / resources / generation
    "call_mcp_tool", "list_resources", "read_resource", "generate_image",
})
DENY_PREFIXES = ("browser_",)

_POLICY = "blocked by triad cross-family review policy"
_REPORT_CAP = 40   # denied rows printed by `check` — the digest's list cap
_USAGE = ("usage: agy_hook.py --log <abs-jsonl>   (hook mode, stdin = PreToolUse payload)\n"
          "       agy_hook.py check <abs-read-audit.json> <abs-hook-log.jsonl>")


def decide(name) -> tuple:
    """(decision, reason) for one tool name — the ENTIRE hook policy.
    Non-string / empty names deny (fail-closed): a payload this handler
    cannot read must never let a mutating call through."""
    if not isinstance(name, str) or not name:
        return ("deny", f"{_POLICY}: the tool call carries no readable name")
    if name in DENY_TOOLS or name.startswith(DENY_PREFIXES):
        return ("deny", f"{_POLICY}: {name} mutates, executes, or reaches "
                        f"outside the reviewed tree — a read-only review leg "
                        f"may not call it")
    return ("allow", None)


def _hook_main(log_path: Path) -> int:
    # BYTES, decoded as UTF-8 with replacement (S2 gate r1, agy A4 — REPRODUCED):
    # a text-mode read under an ASCII stdio encoding (a legacy locale) raised
    # UnicodeDecodeError on a payload carrying a non-ASCII path, and a crashed
    # hook denies every later call, reads included. Only the tool NAME matters.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    except (OSError, AttributeError, ValueError):
        raw = ""
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    name = conversation = step = None
    if isinstance(payload, dict):
        call = payload.get("toolCall")
        if isinstance(call, dict):
            name = call.get("name")
        conversation = payload.get("conversationId")
        step = payload.get("stepIdx")
    decision, reason = decide(name)
    row = {
        "ts": time.time(),
        "conversation_id": conversation if isinstance(conversation, str) else None,
        "step_idx": step if isinstance(step, int) and not isinstance(step, bool) else None,
        "tool": name if isinstance(name, str) else None,
        "decision": decision,
    }
    if reason is not None:
        row["reason"] = reason
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")
    except OSError as e:
        # availability over bookkeeping: the decision still answers, and the
        # load check will report the missing invocations loudly
        print(f"agy_hook: hook log {log_path} could not be written: {e}",
              file=sys.stderr)
    out = {"decision": decision}
    if reason is not None:
        out["reason"] = reason
    print(json.dumps(out, ensure_ascii=True))
    return 0


def check_loaded(read_audit: Path, hook_log: Path) -> tuple:
    """(verdict, exit_code, report_lines, guidance) — see the module docstring."""
    if not read_audit.is_file():
        return ("ABSENT", 2, [],
                f"no read audit at {read_audit} — the leg never completed or "
                f"TRIAD_READ_AUDIT_FILE was not set at dispatch; the read-audit "
                f"gate reports the same ABSENT — settle that first", None)
    try:
        digest = json.loads(read_audit.read_text(encoding="utf-8")).get("digest")
        tool_steps = digest.get("tool_steps")
    except (OSError, ValueError, AttributeError):
        tool_steps = None
    if not isinstance(tool_steps, int) or isinstance(tool_steps, bool) or tool_steps < 0:
        return ("INCONCLUSIVE", 4, [],
                f"the read audit at {read_audit} carries no readable "
                f"digest.tool_steps — broken evidence, not a verdict", None)
    invocations = 0
    denied = []
    if hook_log.exists():
        try:
            lines = hook_log.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError) as e:
            return ("INCONCLUSIVE", 4, [],
                    f"the hook log at {hook_log} could not be read ({e})", tool_steps)
        for idx, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            # a HOOK row, not any JSON object (S2 gate r1, codex C4): a vendor
            # stream or `{}` handed to this check must never count as proof
            if (not isinstance(row, dict) or row.get("decision") not in ("allow", "deny")
                    or "tool" not in row):
                return ("INCONCLUSIVE", 4, [],
                        f"hook log line {idx} is not a hook row (a JSON object "
                        f"with decision allow|deny and a tool key) — the hook "
                        f"log is broken evidence, not a verdict", tool_steps)
            invocations += 1
            if row.get("decision") == "deny":
                denied.append(row)
    # the name came from the vendor payload: capped and ASCII-escaped, one line
    # (S2 gate r2, claude) — a newline or an ANSI sequence in it must not split
    # or repaint the output the leader greps for `HOOK_LOAD_*`
    def _idx(v):
        return v if isinstance(v, int) and not isinstance(v, bool) else None
    report = [f"[hook] denied {json.dumps(str(r.get('tool'))[:64], ensure_ascii=True)} "
              f"(step {_idx(r.get('step_idx'))})"
              for r in denied[:_REPORT_CAP]]
    if len(denied) > _REPORT_CAP:
        # the list is bounded like every vendor-driven list (S2 gate r3, claude)
        report.append(f"[hook] (+{len(denied) - _REPORT_CAP} more)")
    if invocations == 0 and tool_steps > 0:
        return ("VOID", 3, report,
                f"the enforcement layer did not load: {tool_steps} tool "
                f"step(s) ran with ZERO hook invocations in {hook_log}. agy's "
                f"`--agent` fails OPEN silently, so this leg's containment is "
                f"unproven — treat the leg as INVALID this round; check "
                f"<worktree>/.agents/hooks.json and re-dispatch once",
                tool_steps, invocations, len(denied))
    if invocations == 0:
        return ("INCONCLUSIVE", 4, report,
                "no tool call happened and no hook invocation was logged — "
                "nothing proves or disproves the hook; the read-audit gate "
                "voids a read-blind leg on its own", tool_steps, invocations,
                len(denied))
    return ("PASS", 0, report, None, tool_steps, invocations, len(denied))


def _check_main(read_audit: Path, hook_log: Path) -> int:
    res = check_loaded(read_audit, hook_log)
    verdict, rc, report, guidance = res[0], res[1], res[2], res[3]
    tool_steps = res[4] if len(res) > 4 and res[4] is not None else "unknown"
    invocations = res[5] if len(res) > 5 else 0
    n_denied = res[6] if len(res) > 6 else 0
    for line in report:
        print(line)
    if guidance:
        print(f"[review] agy hook load check {verdict} — {guidance}", file=sys.stderr)
    print(f"HOOK_LOAD_{verdict} tool_steps={tool_steps} invocations={invocations} "
          f"denied={n_denied}")
    return rc


def _abs(arg: str, what: str) -> Path:
    p = Path(arg)
    if not p.is_absolute():
        print(f"agy_hook: {what} must be an absolute path: {arg}\n{_USAGE}",
              file=sys.stderr)
        sys.exit(64)
    return p


def main(argv: list) -> int:
    if len(argv) == 3 and argv[0] == "check":
        return _check_main(_abs(argv[1], "the read audit"),
                           _abs(argv[2], "the hook log"))
    if len(argv) == 2 and argv[0] == "--log":
        return _hook_main(_abs(argv[1], "--log"))
    print(_USAGE, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
