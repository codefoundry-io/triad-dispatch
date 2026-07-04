#!/usr/bin/env python3
"""Deterministic codex task templates. Pure lookup — zero AI calls.

A task name maps to {framing, output_mode, sandbox, default_fanout}. The
wrapper prepends `framing` + a fan-out instruction to the user prompt. This
module makes NO model calls and imports nothing heavy — it is a routing table.
"""
from __future__ import annotations

# Each task: framing template + sandbox policy + default fan-out. Analysis tasks
# are read-only / fan-out-3; the code task is workspace-write / single-implementer.
TASKS: dict[str, dict] = {
    "review": {
        "framing": (
            "You are a review coordinator. Spawn independent read-only subagents "
            "(an explorer mapping structure, a reviewer hunting bugs/risks, and a "
            "security/risk lens) to analyze the target, wait for all, then "
            "consolidate findings ordered by severity with file:line references. "
            "Do not edit files."
        ),
        "output_mode": "markdown",
        "sandbox": "read-only",
        "default_fanout": 3,
    },
    "analyze": {
        "framing": (
            "You are an analysis coordinator. Spawn independent read-only "
            "subagents to map structure, behavior, dependencies, and entry "
            "points from complementary angles, wait for all, then consolidate a "
            "concrete summary with file:line references. Do not edit files."
        ),
        "output_mode": "markdown",
        "sandbox": "read-only",
        "default_fanout": 3,
    },
    "brainstorm": {
        "framing": (
            "You are a brainstorming coordinator. Spawn independent read-only "
            "subagents to generate ideas from distinct perspectives, wait for "
            "all, then consolidate the strongest options with trade-offs. Do not "
            "edit files."
        ),
        "output_mode": "markdown",
        "sandbox": "read-only",
        "default_fanout": 3,
    },
    "code": {
        "framing": (
            "You are an implementation worker. Implement the task below using "
            "TDD: write a failing test first, then the minimal code to pass it. "
            "Edit files ONLY — do NOT run git add/commit (version control is the "
            "orchestrator's job; .git is read-only by design). Keep changes "
            "minimal and scoped to the task. Your FIRST output line MUST be "
            "exactly 'STATUS: <DONE|DONE_WITH_CONCERNS|NEEDS_CONTEXT|BLOCKED>'. "
            "Then report: files changed, what you did, tests you ran + results, "
            "and any concerns."
        ),
        "output_mode": "markdown",
        "sandbox": "workspace-write",
        "default_fanout": 1,
    },
}

FANOUT_MIN = 1
FANOUT_MAX = 12  # wrapper sanity ceiling. Vendor [agents] max_threads default is 6
                 # (concurrent); codex wave-schedules N>6 sequentially, so 12 is a
                 # cost guard, not a concurrency mirror (comment fixed 2026-07-04).


def fanout_instruction(fanout: "int | str") -> str:
    """Return the deterministic fan-out instruction appended to the prompt.

    `fanout` is an int (explicit N) or the string "auto".
    """
    if fanout == "auto":
        return (
            "Use the dispatching-parallel-agents skill to decide how many "
            "parallel subagents to spawn for this task; you choose the count."
        )
    return (
        f"Spawn exactly {int(fanout)} independent subagents in parallel for "
        f"this task, wait for all, then consolidate."
    )


def augment_prompt(task: str, fanout: "int | str", user_prompt: str) -> str:
    """Prepend task framing + fan-out instruction to the user prompt."""
    spec = TASKS[task]
    if task == "code" and fanout == 1:
        fan = "Work directly as a single implementer; do NOT spawn subagents."
    else:
        fan = fanout_instruction(fanout)
    return f"{spec['framing']}\n\n{fan}\n\n---\n\n{user_prompt}"
