import os
import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

import _common  # noqa: E402


def _result(stdout: str = "x") -> _common.RunResult:
    return _common.RunResult(
        exit_code=_common.EXIT_CLI_FAIL,
        stdout=stdout,
        stderr="err",
        elapsed_s=0.1,
        classification="unknown",
        final_answer="",
        vendor_exit_code=1,
    )


def test_stale_run_log_prune_removes_repair_json_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "_LOG_DIR", tmp_path / "_logs")
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


def test_audit_rotation_prunes_archives_by_count(tmp_path, monkeypatch):
    monkeypatch.setattr(_common, "_LOG_DIR", tmp_path / "_logs")
    monkeypatch.setattr(_common, "AUDIT_ROTATE_BYTES", 200)
    monkeypatch.setattr(_common, "AUDIT_MAX_ARCHIVES", 2)
    monkeypatch.setattr(_common, "AUDIT_ARCHIVE_MAX_BYTES", 10_000)

    for _ in range(5):
        _common.audit("gemini", ["fake"], "prompt", _result(stdout="x" * 500))

    log_dir = tmp_path / "_logs" / "gemini"
    assert (log_dir / "audit.jsonl").is_file()
    assert len(list(log_dir.glob("audit.*.jsonl"))) <= 2
