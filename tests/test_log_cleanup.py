#!/usr/bin/env python3
"""Run-log prune + audit-rotation policy tests (stdlib-only, no pytest).

Covers: (1) stale run-log prune removes the run-log AND its `.repair.json`
pair while keeping fresh files; (2) audit() rotates the active audit.jsonl
past AUDIT_ROTATE_BYTES and bounds archives by AUDIT_MAX_ARCHIVES.

Runs in BOTH layouts: the triad source repo (tests/ beside the wrappers) and the
exported plugin (`tests/` with a `bin/` sibling).
"""
from __future__ import annotations

import os
import sys
sys.dont_write_bytecode = True  # keep an installed plugin dir pristine
import tempfile
import time
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BIN = _ROOT / "bin" if (_ROOT / "bin").is_dir() else _ROOT
sys.path.insert(0, str(_BIN))

import _common  # noqa: E402

# Module attrs each test may override; the runner snapshots + restores them so
# tests stay isolated within the single process (the pytest-monkeypatch role).
_PATCHED_ATTRS = (
    "_LOG_DIR", "AUDIT_ROTATE_BYTES", "AUDIT_MAX_ARCHIVES", "AUDIT_ARCHIVE_MAX_BYTES",
)


def _result(stdout: str = "x") -> "_common.RunResult":
    return _common.RunResult(
        exit_code=_common.EXIT_CLI_FAIL,
        stdout=stdout,
        stderr="err",
        elapsed_s=0.1,
        classification="unknown",
        final_answer="",
        vendor_exit_code=1,
    )


def test_stale_run_log_prune_removes_repair_json_pair(tmp_path: Path) -> None:
    _common._LOG_DIR = tmp_path / "_logs"
    runs_dir = tmp_path / "_logs" / "gemini" / "runs"
    runs_dir.mkdir(parents=True)
    run_log = runs_dir / "old.json"
    repair = runs_dir / "old.json.repair.json"
    fresh = runs_dir / "fresh.json"
    for path in (run_log, repair, fresh):
        path.write_text("{}\n", encoding="utf-8")
    old = time.time() - 10_000
    os.utime(run_log, (old, old))
    os.utime(repair, (old, old))

    _common.prune_stale_run_logs("gemini", age_floor_s=7200)

    assert not run_log.exists()
    assert not repair.exists()
    assert fresh.exists()


def test_audit_rotation_prunes_archives_by_count(tmp_path: Path) -> None:
    _common._LOG_DIR = tmp_path / "_logs"
    _common.AUDIT_ROTATE_BYTES = 200
    _common.AUDIT_MAX_ARCHIVES = 2
    _common.AUDIT_ARCHIVE_MAX_BYTES = 10_000

    for _ in range(5):
        _common.audit("gemini", ["fake"], "prompt", _result(stdout="x" * 500))

    log_dir = tmp_path / "_logs" / "gemini"
    assert (log_dir / "audit.jsonl").is_file()
    assert len(list(log_dir.glob("audit.*.jsonl"))) <= 2


TESTS = [
    test_stale_run_log_prune_removes_repair_json_pair,
    test_audit_rotation_prunes_archives_by_count,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        snapshot = {a: getattr(_common, a) for a in _PATCHED_ATTRS}
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
                print(f"  PASS  {fn.__name__}")
            except Exception:
                failed += 1
                print(f"  FAIL  {fn.__name__}")
                traceback.print_exc()
            finally:
                for a, v in snapshot.items():
                    setattr(_common, a, v)
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
