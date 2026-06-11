#!/usr/bin/env python3
"""Per-call isolation for the Antigravity (agy) wrapper.

agy has only two per-call flags (--model, --sandbox); fs-write isolation lives
only in the single global ~/.gemini/antigravity-cli/settings.json (no
per-directory file, no profile, no --settings flag, no config-dir env — proven
4-source). So a per-call read-only / workspace-write worker is implemented as a
global-settings transaction: merge the per-call permissions.deny, run agy, then
byte-exactly restore. An flock serializes the agy leg; a .agybak sentinel
restores after a mid-transaction crash. See the slice-2 design doc §4-§5.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import sys
import time
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".gemini" / "antigravity-cli" / "settings.json"

# read-only: every mutation + shell (sandboxed OR unsandboxed) blocked; reads
# succeed. read_url is intentionally NOT denied — agy's web search/research is
# its key advantage and the internet is always allowed (owner directive).
_READ_ONLY_DENY = [
    "write_file(*)",
    "command(*)",
    "unsandboxed(*)",
    "execute_url(*)",
    "mcp(*)",
]


def _workspace_write_deny() -> list:
    # workspace-write: writes allowed (in the worktree cwd) but dangerous paths
    # + destructive commands denied. ~ is expanded so the rule is absolute
    # (agy matches absolute paths or workspace-relative paths).
    gem = os.path.expanduser("~/.gemini")   # protect agy's own config (deny-rule self-overwrite escape)
    ssh = os.path.expanduser("~/.ssh")
    aws = os.path.expanduser("~/.aws")
    return [
        f"write_file({gem})",
        "write_file(.git/)",
        f"write_file({ssh})",
        f"write_file({aws})",
        "command(rm -rf)",
        "command(sudo)",
        "command(curl .*)",
        "unsandboxed(*)",   # commands must stay inside the OS sandbox ring
        "execute_url(*)",   # no code-exec-from-URL even in a write worker
        "mcp(*)",           # no MCP reach (read_url/search_web remain the only web access)
    ]


def build_deny_rules(mode: str) -> list:
    """Return the permissions.deny list for an agy sandbox mode."""
    if mode == "read-only":
        return list(_READ_ONLY_DENY)
    if mode == "workspace-write":
        return _workspace_write_deny()
    raise ValueError(f"unknown sandbox mode: {mode!r}")


def _settings_path() -> Path:
    env = os.environ.get("AGY_SETTINGS_PATH")
    return Path(env) if env else _DEFAULT_PATH


def _snapshot(p: Path) -> dict:
    if p.exists():
        return {"existed": True, "content": p.read_text()}
    return {"existed": False, "content": ""}


def _atomic_write(p: Path, text: str) -> None:
    """Atomic durable write: fully write a temp file in the SAME dir -> fsync ->
    os.replace (atomic on POSIX same-filesystem). Buffered write guarantees every
    byte lands (raw os.write may short-write); the parent-dir fsync makes the
    rename itself durable across a power loss."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(text.encode())
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)
    dfd = os.open(str(p.parent), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _restore(p: Path, snap: dict) -> None:
    if snap["existed"]:
        _atomic_write(p, snap["content"])
    else:
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def _crash_recover(p: Path, bak: Path) -> None:
    """Heal a stale .agybak from a prior crashed transaction.

    Two distinct failure modes are handled differently:
      - the sentinel is UNREADABLE/UNPARSEABLE -> its snapshot is unknowable, so
        a faithful restore is impossible; drop it and proceed (atomic writes make
        this near-unreachable), WARNING that settings.json may retain leaked deny
        rules from the crashed transaction.
      - the sentinel parses OK but _restore FAILS (e.g. transient OSError) ->
        KEEP the sentinel so a later call can retry, and let the error propagate
        loudly. Never discard a valid snapshot.
    """
    if not bak.exists():
        return
    try:
        snap = json.loads(bak.read_text())
    except (ValueError, OSError) as e:
        sys.stderr.write(
            f"[agy_settings] corrupt .agybak dropped: {e}; "
            f"~/.gemini/antigravity-cli/settings.json may retain leaked deny "
            f"rules from a crashed transaction — verify/remove manually\n")
        try:
            bak.unlink()
        except FileNotFoundError:
            pass
        return
    _restore(p, snap)          # may raise OSError -> propagate, sentinel kept
    try:
        bak.unlink()
    except FileNotFoundError:
        pass


def _merge_deny(p: Path, deny_rules: list) -> None:
    data: dict = {}
    if p.exists():
        txt = p.read_text().strip()
        if txt:
            data = json.loads(txt)
    perms = data.setdefault("permissions", {})
    deny = perms.setdefault("deny", [])
    for r in deny_rules:
        if r not in deny:
            deny.append(r)
    _atomic_write(p, json.dumps(data, indent=2))


@contextlib.contextmanager
def agy_settings_guard(deny_rules, *, lock_timeout: float = 30.0):
    """Bracket an agy call in a global-settings deny transaction.

    EVERY call (including the permissive deny_rules == [] no-op) acquires the
    flock and runs crash-recovery so a stale .agybak from a prior crashed call
    is always healed and no agy call ever runs against deny-polluted settings.
    Only the snapshot/merge/restore is conditional on deny_rules.
    """
    p = _settings_path()
    bak = p.with_name(".agybak")
    lock = p.with_name(".agy_settings.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + lock_timeout
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("agy settings lock timeout")
                time.sleep(0.1)
        _crash_recover(p, bak)
        if not deny_rules:
            yield
            return
        snap = _snapshot(p)
        _atomic_write(bak, json.dumps(snap))
        try:
            _merge_deny(p, deny_rules)
            yield
        finally:
            _restore(p, snap)
            try:
                bak.unlink()
            except FileNotFoundError:
                pass
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
