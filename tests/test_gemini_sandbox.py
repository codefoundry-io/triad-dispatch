# Hermetic tests for gemini_wrapper.py --sandbox read-only (Policy Engine).
# A fake `gemini` on PATH captures the argv the wrapper builds; we assert
# --policy <readonly.toml> is attached for read-only and NOT otherwise.
# (The policy's actual enforcement needs a live gemini — verified company-side.)
import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "bin" / "policies" / "gemini-readonly.toml"


def _fake_gemini_dir(tmp_path):
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


def _run(tmp_path, *extra):
    argv_file = tmp_path / "argv.txt"
    pathdir = _fake_gemini_dir(tmp_path)
    env = dict(
        os.environ,
        PATH=pathdir + os.pathsep + os.environ["PATH"],
        ARGV_FILE=str(argv_file),
    )
    r = subprocess.run(
        [sys.executable, str(ROOT / "bin/gemini_wrapper.py"), "--prompt", "hi", *extra],
        capture_output=True, text=True, env=env,
    )
    argv = argv_file.read_text() if argv_file.exists() else ""
    return r, argv


def test_readonly_attaches_policy(tmp_path):
    _r, argv = _run(tmp_path, "--sandbox", "read-only")
    assert "--policy" in argv
    assert str(POLICY) in argv


def test_workspace_write_has_no_policy(tmp_path):
    _r, argv = _run(tmp_path, "--sandbox", "workspace-write")
    assert "--policy" not in argv


def test_default_unset_has_no_policy(tmp_path):
    _r, argv = _run(tmp_path)
    assert "--policy" not in argv


def test_readonly_plus_yolo_rejected_before_spawn(tmp_path):
    r, argv = _run(tmp_path, "--sandbox", "read-only", "--approval-mode", "yolo")
    assert r.returncode != 0, "read-only + yolo must be rejected"
    assert "conflicts" in r.stderr
    assert argv == "", "gemini must not be spawned on the rejected combo"
