#!/usr/bin/env python3
"""Hermetic tests for gemini_wrapper.py --sandbox read-only (Policy Engine).

A fake `gemini` on PATH captures the argv the wrapper builds; we assert
`--policy <gemini-readonly.toml>` is attached for read-only and NOT otherwise,
and that the banned approval modes (plan / yolo) are rejected BEFORE any spawn.
(The policy's actual ENFORCEMENT needs a live enterprise/Vertex/API-key-tier
gemini — doc-verified only; live e2e pending. See the policy file header.)

stdlib-only (no pytest — artifact-boundary rule: no new deps on either side).
Runs in BOTH layouts: the triad source repo (tests/ beside the wrappers) and the exported plugin (`tests/` with a `bin/` sibling).
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" if (ROOT / "bin").is_dir() else ROOT
POLICY = BIN / "policies" / "gemini-readonly.toml"


def _fake_gemini_dir(tmp_path: Path) -> str:
    fixture = tmp_path / "fake_gemini.py"
    fixture.write_text(
        "import json, os, sys\n"
        "open(os.environ['ARGV_FILE'], 'w').write('\\n'.join(sys.argv[1:]))\n"
        "print(json.dumps({'response': 'FAKE-OK', 'stats': {}, 'error': None}))\n"
    )
    shim = tmp_path / "gemini"
    shim.write_text(f'#!/usr/bin/env bash\nexec python3 {fixture} "$@"\n')
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return str(tmp_path)


def _run(tmp_path: Path, *extra: str):
    argv_file = tmp_path / "argv.txt"
    pathdir = _fake_gemini_dir(tmp_path)
    env = dict(
        os.environ,
        PATH=pathdir + os.pathsep + os.environ["PATH"],
        ARGV_FILE=str(argv_file),
        # never mutate the (possibly installed-plugin) wrapper dir
        TRIAD_DISPATCH_LOG_DIR=str(tmp_path / "_logs"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    r = subprocess.run(
        [sys.executable, str(BIN / "gemini_wrapper.py"), "--prompt", "hi", *extra],
        capture_output=True, text=True, env=env,
    )
    argv = argv_file.read_text() if argv_file.exists() else ""
    return r, argv


def test_readonly_attaches_policy(tmp_path: Path) -> None:
    _r, argv = _run(tmp_path, "--sandbox", "read-only")
    assert "--policy" in argv
    assert str(POLICY) in argv


def test_workspace_write_has_no_policy(tmp_path: Path) -> None:
    # --cwd added 2026-08-26 (write-posture guard): the axis intent — no
    # --policy attached on workspace-write — is unchanged; a write posture
    # without --cwd is now rejected before spawn (its own test below).
    wd = tmp_path / "wd"
    wd.mkdir()
    _r, argv = _run(tmp_path, "--sandbox", "workspace-write", "--cwd", str(wd))
    assert "--policy" not in argv


def test_workspace_write_without_cwd_rejected_before_spawn(tmp_path: Path) -> None:
    # Owner ruling 2026-08-26 (codex/claude symmetry): a write-enabled
    # dispatch's blast radius must be an isolated directory, never the
    # wrapper's inherited cwd — codex --task code and claude workspace-write
    # already carry this guard; gemini was the one write-capable wrapper
    # without it.
    r, argv = _run(tmp_path, "--sandbox", "workspace-write")
    assert r.returncode != 0, "workspace-write without --cwd must be rejected"
    assert "requires --cwd" in r.stderr
    assert argv == "", "gemini must not be spawned on the rejected combo"


def test_auto_edit_without_cwd_rejected_before_spawn(tmp_path: Path) -> None:
    # auto_edit auto-approves writes — same write posture, same guard.
    r, argv = _run(tmp_path, "--approval-mode", "auto_edit")
    assert r.returncode != 0, "auto_edit without --cwd must be rejected"
    assert "requires --cwd" in r.stderr
    assert argv == "", "gemini must not be spawned on the rejected combo"


def test_auto_edit_with_cwd_passes_guard(tmp_path: Path) -> None:
    # Positive control: the guard keys on the MISSING directory, not on the
    # posture itself — with --cwd the dispatch proceeds to the vendor.
    wd = tmp_path / "wd"
    wd.mkdir()
    _r, argv = _run(tmp_path, "--approval-mode", "auto_edit", "--cwd", str(wd))
    assert argv != "", "auto_edit WITH --cwd must reach the vendor spawn"


def test_default_unset_has_no_policy(tmp_path: Path) -> None:
    _r, argv = _run(tmp_path)
    assert "--policy" not in argv


def test_yolo_approval_mode_rejected_before_spawn(tmp_path: Path) -> None:
    r, argv = _run(tmp_path, "--approval-mode", "yolo")
    assert r.returncode != 0, "yolo approval mode must be rejected"
    assert "invalid choice" in r.stderr
    assert argv == "", "gemini must not be spawned on the rejected combo"


def test_plan_approval_mode_rejected_before_spawn(tmp_path: Path) -> None:
    r, argv = _run(tmp_path, "--approval-mode", "plan")
    assert r.returncode != 0, "plan approval mode must be rejected"
    assert "invalid choice" in r.stderr
    assert argv == "", "gemini must not be spawned on the rejected combo"


def test_readonly_plus_auto_edit_rejected_before_spawn(tmp_path: Path) -> None:
    r, argv = _run(tmp_path, "--sandbox", "read-only", "--approval-mode", "auto_edit")
    assert r.returncode != 0, "read-only + auto_edit must be rejected"
    assert "conflicts" in r.stderr
    assert argv == "", "gemini must not be spawned on the rejected combo"


TESTS = [
    test_readonly_attaches_policy,
    test_workspace_write_has_no_policy,
    test_workspace_write_without_cwd_rejected_before_spawn,
    test_auto_edit_without_cwd_rejected_before_spawn,
    test_auto_edit_with_cwd_passes_guard,
    test_default_unset_has_no_policy,
    test_yolo_approval_mode_rejected_before_spawn,
    test_plan_approval_mode_rejected_before_spawn,
    test_readonly_plus_auto_edit_rejected_before_spawn,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
                print(f"  PASS  {fn.__name__}")
            except Exception:
                failed += 1
                print(f"  FAIL  {fn.__name__}")
                traceback.print_exc()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
