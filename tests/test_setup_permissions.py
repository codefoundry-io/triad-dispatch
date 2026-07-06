#!/usr/bin/env python3
"""Tests for the claude-host permission-setup script (stdlib-only, no pytest).

Covers the idempotent-merge contract of `setup_permissions.py`:
  (1) a fresh run creates settings.json with the full wrapper allowlist;
  (2) a second run is a no-op — every entry present exactly once (idempotent);
  (3) an existing unrelated settings key + a pre-existing allow entry survive;
  (4) the output is valid JSON;
  (5) the same run populates `sandbox.excludedCommands` with the wrapper
      patterns (so the wrappers reach the vendor APIs when a user opts the Bash
      sandbox on) — idempotently, valid JSON, and preserving an unrelated
      pre-existing `sandbox` key.

Runs in BOTH layouts: the source repo (the script lives under
`export_assets/claude-host/scripts/`) and the exported plugin (`tests/` with a
`scripts/` sibling). The script is loaded by file path, not import name.
"""
from __future__ import annotations

import importlib.util
import json
import sys

sys.dont_write_bytecode = True  # keep an installed plugin dir pristine
import tempfile
import traceback
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_CANDIDATES = (
    # exported plugin layout: tests/ has a scripts/ sibling
    _TESTS_DIR.parent / "scripts" / "setup_permissions.py",
    # source repo layout: the script lives under an export_assets/claude-host/
    # scripts/ dir two levels up from this tests/ directory
    _TESTS_DIR.parents[1]
    / "export_assets"
    / "claude-host"
    / "scripts"
    / "setup_permissions.py",
)


def _load_script():
    for candidate in _CANDIDATES:
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("setup_permissions", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise AssertionError(
        "setup_permissions.py not found in any known layout: "
        + ", ".join(str(c) for c in _CANDIDATES)
    )


setup_permissions = _load_script()
EXPECTED_ENTRIES = setup_permissions.WRAPPER_ALLOW_ENTRIES
EXPECTED_SANDBOX_PATTERNS = setup_permissions.WRAPPER_SANDBOX_EXCLUDE_PATTERNS


def test_fresh_run_creates_full_allowlist():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".claude" / "settings.json"
        rc = setup_permissions.main(["--target", str(target)])
        assert rc == 0, f"expected rc 0, got {rc}"
        assert target.is_file(), "settings.json was not created"
        data = json.loads(target.read_text(encoding="utf-8"))
        allow = data["permissions"]["allow"]
        for entry in EXPECTED_ENTRIES:
            assert entry in allow, f"missing allow entry: {entry}"
        # the same run seeds sandbox.excludedCommands with the wrapper patterns
        excluded = data["sandbox"]["excludedCommands"]
        for pattern in EXPECTED_SANDBOX_PATTERNS:
            assert pattern in excluded, f"missing sandbox exclude: {pattern}"


def test_second_run_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".claude" / "settings.json"
        assert setup_permissions.main(["--target", str(target)]) == 0
        first = target.read_text(encoding="utf-8")
        assert setup_permissions.main(["--target", str(target)]) == 0
        second = target.read_text(encoding="utf-8")
        # byte-identical: a re-run must not append, reorder, or rewrite anything
        assert first == second, "second run mutated the file (not idempotent)"
        data = json.loads(second)
        allow = data["permissions"]["allow"]
        # each wrapper entry appears EXACTLY once
        for entry in EXPECTED_ENTRIES:
            assert allow.count(entry) == 1, f"{entry} present {allow.count(entry)}x, want 1"
        # each sandbox exclude pattern also appears EXACTLY once across two runs
        excluded = data["sandbox"]["excludedCommands"]
        for pattern in EXPECTED_SANDBOX_PATTERNS:
            assert (
                excluded.count(pattern) == 1
            ), f"{pattern} present {excluded.count(pattern)}x, want 1"


def test_directory_target_resolves_to_dot_claude():
    # --target <dir> (not ending in .json) resolves to <dir>/.claude/settings.json
    with tempfile.TemporaryDirectory() as tmp:
        assert setup_permissions.main(["--target", tmp]) == 0
        resolved = Path(tmp) / ".claude" / "settings.json"
        assert resolved.is_file(), "directory target did not resolve to .claude/settings.json"


def test_preserves_unrelated_keys_and_existing_allow():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".claude" / "settings.json"
        target.parent.mkdir(parents=True)
        target.write_text(
            json.dumps(
                {
                    "model": "sonnet",
                    "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(rm:*)"]},
                    "env": {"FOO": "bar"},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        assert setup_permissions.main(["--target", str(target)]) == 0
        data = json.loads(target.read_text(encoding="utf-8"))
        # unrelated top-level keys preserved
        assert data["model"] == "sonnet"
        assert data["env"] == {"FOO": "bar"}
        # unrelated permissions sub-keys preserved
        assert data["permissions"]["deny"] == ["Bash(rm:*)"]
        # the pre-existing allow entry survives, and the wrapper entries are added
        allow = data["permissions"]["allow"]
        assert "Bash(ls:*)" in allow
        for entry in EXPECTED_ENTRIES:
            assert entry in allow


def test_preserves_existing_sandbox_key():
    # a pre-existing, unrelated sandbox sub-key must survive the merge, and the
    # wrapper exclude patterns get added alongside it (not clobbering it)
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".claude" / "settings.json"
        target.parent.mkdir(parents=True)
        target.write_text(
            json.dumps(
                {
                    "sandbox": {
                        "network": {"allowUnixSockets": True},
                        "excludedCommands": ["gh *"],
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        assert setup_permissions.main(["--target", str(target)]) == 0
        sandbox = json.loads(target.read_text(encoding="utf-8"))["sandbox"]
        # unrelated sandbox sub-key preserved
        assert sandbox["network"] == {"allowUnixSockets": True}
        excluded = sandbox["excludedCommands"]
        # the pre-existing unrelated exclude survives
        assert "gh *" in excluded
        # the wrapper patterns are added, each exactly once
        for pattern in EXPECTED_SANDBOX_PATTERNS:
            assert excluded.count(pattern) == 1, f"{pattern} not added exactly once"


def test_sandbox_excluded_is_valid_json():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".claude" / "settings.json"
        assert setup_permissions.main(["--target", str(target)]) == 0
        # json.loads raises on malformed content; the sandbox key must parse too
        data = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(data["sandbox"]["excludedCommands"], list)


def test_output_is_valid_json():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".claude" / "settings.json"
        assert setup_permissions.main(["--target", str(target)]) == 0
        # json.loads raises on malformed content — the assertion is that it does not
        json.loads(target.read_text(encoding="utf-8"))


def test_malformed_settings_is_an_error_not_a_clobber():
    # a malformed settings.json must NOT be silently discarded
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".claude" / "settings.json"
        target.parent.mkdir(parents=True)
        target.write_text("{ this is not json", encoding="utf-8")
        rc = setup_permissions.main(["--target", str(target)])
        assert rc != 0, "expected non-zero rc on malformed settings.json"
        # the original (malformed) content is left untouched
        assert target.read_text(encoding="utf-8") == "{ this is not json"


TESTS = [
    test_fresh_run_creates_full_allowlist,
    test_second_run_is_idempotent,
    test_directory_target_resolves_to_dot_claude,
    test_preserves_unrelated_keys_and_existing_allow,
    test_preserves_existing_sandbox_key,
    test_sandbox_excluded_is_valid_json,
    test_output_is_valid_json,
    test_malformed_settings_is_an_error_not_a_clobber,
]


def main() -> int:
    failures = 0
    for test in TESTS:
        try:
            test()
            print(f"ok   {test.__name__}")
        except Exception:  # noqa: BLE001 — a test harness reports every failure
            failures += 1
            print(f"FAIL {test.__name__}")
            traceback.print_exc()
    total = len(TESTS)
    print(f"{total - failures}/{total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
