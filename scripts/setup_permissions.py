#!/usr/bin/env python3
"""Merge the wrapper Bash allowlist into a Claude Code settings.json.

A Claude Code plugin cannot grant Bash permissions, so the wrapper commands
this plugin dispatches must be allow-listed in your own settings.json. This
script does that one mechanical step for you: it reads the target settings
file (creating it if absent), adds the wrapper `Bash(...)` entries to
`permissions.allow` without duplicating any, and writes the file back
atomically. It is deterministic and safe to re-run — a second run is a no-op.

The same run also adds the wrapper command patterns to
`sandbox.excludedCommands`. Permission-allow and sandboxing are orthogonal:
Claude Code's Bash sandbox is OFF by default, but if you enable it (via
`/sandbox`) the wrappers spawn vendor CLIs that make authenticated network API
calls, which a network-restricted sandbox commonly breaks. Excluding them runs
them outside the sandbox (the same pattern the docs use for `gh` / `docker` /
`gcloud`). This is harmless when the sandbox is off.

Usage:
    python3 setup_permissions.py [--target <path-or-dir>] [--dry-run]

    --target   Path to the settings file, or a directory. A directory (or the
               default) resolves to `<dir>/.claude/settings.json`; the default
               target is `./.claude/settings.json` under the current directory.
    --dry-run  Print what would change without writing.

Exit status is 0 on success (including a no-op re-run), non-zero on error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# The wrapper Bash commands this plugin dispatches. A plugin cannot grant Bash
# permissions, so these must be allow-listed in the user's settings.json.
WRAPPER_ALLOW_ENTRIES = [
    "Bash(codex_wrapper.py:*)",
    "Bash(gemini_wrapper.py:*)",
    "Bash(antigravity_wrapper.py:*)",
    "Bash(agy-daily-check.sh:*)",
    "Bash(gemini-daily-check.sh:*)",
]

# The same wrapper commands, in the space-glob form `sandbox.excludedCommands`
# uses (like `docker *`). If the Bash sandbox is enabled, listing them here runs
# them OUTSIDE the sandbox so they can reach the vendor APIs with the user's
# auth (a network-restricted sandbox otherwise breaks these Go/TLS CLIs).
# Harmless when the sandbox is off. Permission-allow and sandboxing are
# orthogonal, so this is a separate merge from WRAPPER_ALLOW_ENTRIES.
WRAPPER_SANDBOX_EXCLUDE_PATTERNS = [
    "codex_wrapper.py *",
    "gemini_wrapper.py *",
    "antigravity_wrapper.py *",
    "agy-daily-check.sh *",
    "gemini-daily-check.sh *",
]


def resolve_target(raw: str) -> Path:
    """Resolve the --target argument to a settings.json file path.

    A path ending in `.json` is treated as the settings file itself. Anything
    else is treated as a directory, and the settings file is
    `<dir>/.claude/settings.json` — so `--target .` (the default) resolves to
    `./.claude/settings.json`.
    """
    path = Path(raw).expanduser()
    if path.suffix == ".json":
        return path
    return path / ".claude" / "settings.json"


def load_settings(target: Path) -> dict:
    """Load the settings JSON, or return an empty dict if the file is absent.

    A present-but-empty file is treated as an empty object. A malformed file is
    an error — we never silently discard a user's settings.
    """
    if not target.exists():
        return {}
    text = target.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(
            f"top-level JSON in {target} is not an object; refusing to modify"
        )
    return data


def merge_allow_entries(settings: dict) -> list[str]:
    """Add the wrapper allow entries into settings['permissions']['allow'].

    Mutates `settings` in place. Returns the list of entries actually added
    (empty when everything was already present). Existing entries and unrelated
    keys are preserved; ordering of existing entries is not disturbed.
    """
    permissions = settings.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError(
            "settings['permissions'] is not an object; refusing to modify"
        )
    allow = permissions.setdefault("allow", [])
    if not isinstance(allow, list):
        raise ValueError(
            "settings['permissions']['allow'] is not a list; refusing to modify"
        )
    existing = set(allow)
    added = []
    for entry in WRAPPER_ALLOW_ENTRIES:
        if entry not in existing:
            allow.append(entry)
            existing.add(entry)
            added.append(entry)
    return added


def merge_sandbox_excluded_commands(settings: dict) -> list[str]:
    """Add the wrapper patterns into settings['sandbox']['excludedCommands'].

    Mutates `settings` in place. Returns the list of patterns actually added
    (empty when everything was already present). An existing `sandbox` object
    and any unrelated sub-keys are preserved; ordering of existing entries is
    not disturbed. Orthogonal to `merge_allow_entries` — being allow-listed
    does not exempt a command from the Bash sandbox.
    """
    sandbox = settings.setdefault("sandbox", {})
    if not isinstance(sandbox, dict):
        raise ValueError(
            "settings['sandbox'] is not an object; refusing to modify"
        )
    excluded = sandbox.setdefault("excludedCommands", [])
    if not isinstance(excluded, list):
        raise ValueError(
            "settings['sandbox']['excludedCommands'] is not a list; refusing to modify"
        )
    existing = set(excluded)
    added = []
    for pattern in WRAPPER_SANDBOX_EXCLUDE_PATTERNS:
        if pattern not in existing:
            excluded.append(pattern)
            existing.add(pattern)
            added.append(pattern)
    return added


def atomic_write(target: Path, settings: dict) -> None:
    """Write settings to target atomically (temp file + rename in the same dir).

    Writing to a temp file in the target's directory and renaming avoids
    leaving a truncated settings.json if the process is interrupted mid-write.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".settings.", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, target)
    except BaseException:
        # Best-effort cleanup of the temp file on any failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge the wrapper Bash allowlist into a Claude Code "
        "settings.json (idempotent).",
    )
    parser.add_argument(
        "--target",
        default=".",
        help="settings.json path, or a directory (default: ./.claude/settings.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would change without writing",
    )
    args = parser.parse_args(argv)

    target = resolve_target(args.target)

    try:
        settings = load_settings(target)
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        print(f"error: could not read {target}: {exc}", file=sys.stderr)
        return 1

    try:
        added_allow = merge_allow_entries(settings)
        added_sandbox = merge_sandbox_excluded_commands(settings)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    def _report(verb: str) -> None:
        if added_allow:
            print(f"{verb} {len(added_allow)} permissions.allow entr"
                  + ("y" if len(added_allow) == 1 else "ies") + f" to {target}:")
            for entry in added_allow:
                print(f"  + {entry}")
        if added_sandbox:
            print(f"{verb} {len(added_sandbox)} sandbox.excludedCommands entr"
                  + ("y" if len(added_sandbox) == 1 else "ies") + f" to {target}:")
            for entry in added_sandbox:
                print(f"  + {entry}")

    if not added_allow and not added_sandbox:
        print(f"already up to date: all wrapper entries present in {target}")
        return 0

    if args.dry_run:
        _report("would add")
        return 0

    try:
        atomic_write(target, settings)
    except OSError as exc:
        print(f"error: could not write {target}: {exc}", file=sys.stderr)
        return 1

    _report("added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
