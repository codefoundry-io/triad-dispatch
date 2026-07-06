#!/usr/bin/env python3
"""Per-call isolation for the Antigravity (agy) wrapper.

agy exposes NO per-call permission/settings surface (its per-call flags are
session/transport-only); fs-write isolation lives
only in the single global ~/.gemini/antigravity-cli/settings.json (no
per-directory file, no profile, no --settings flag, no config-dir env — proven
4-source). So a per-call read-only / workspace-write worker is implemented as a
global-settings transaction: merge the per-call permissions.deny, run agy, then
byte-exactly restore. An flock serializes settings state transitions; identical
read-only calls share the active deny lease, while workspace-write stays
exclusive. Read-only holder liveness is proven by per-holder flock files rather
than PIDs, so stale holders can be pruned safely after crashes. A .agybak
sentinel restores after a mid-transaction crash. See the slice-2 design doc
§4-§5.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import sys
import time
import uuid
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


def _shared_state_path(p: Path) -> Path:
    return p.with_name(".agy_settings.shared.json")


def _holder_dir(p: Path) -> Path:
    return p.with_name(".agy_settings.holders")


def _deny_key(deny_rules: list) -> str:
    return json.dumps(deny_rules, sort_keys=True, separators=(",", ":"))


def _shareable_deny(deny_rules: list) -> bool:
    # Read-only calls all install the exact same deny list and can safely share
    # the active settings transaction. Workspace-write stays exclusive because
    # those calls are allowed to edit project files and are rare.
    return deny_rules == _READ_ONLY_DENY


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


def _lock_until(lock_fd: int, deadline: float) -> None:
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EACCES):
                raise
            if time.monotonic() >= deadline:
                raise TimeoutError("agy settings lock timeout")
            time.sleep(0.1)


def _shared_state(path: Path) -> dict | None:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    except OSError as e:
        sys.stderr.write(f"[agy_settings] shared state unreadable, resetting lease: {e}\n")
        return None
    try:
        data = json.loads(text)
    except ValueError as e:
        sys.stderr.write(
            f"[agy_settings] corrupt shared state dropped: {e}; "
            "next entrant will run crash recovery\n"
        )
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return None
    if not isinstance(data, dict):
        return None
    holders = data.get("holders")
    if not isinstance(holders, list):
        return None
    return data


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _holder_live(holder: dict) -> bool:
    lock_path = holder.get("lock_path")
    if lock_path:
        path = Path(lock_path)
        try:
            fd = os.open(str(path), os.O_RDWR)
        except FileNotFoundError:
            return False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EACCES):
                    return True
                raise
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return False
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)

    # Backward compatibility for state files written before holder lock files.
    try:
        pid = int(holder.get("pid"))
    except (AttributeError, TypeError, ValueError):
        return False
    return _pid_alive(pid)


def _live_holders(holders: list) -> list:
    return [holder for holder in holders if isinstance(holder, dict) and _holder_live(holder)]


def _remove_holder_dir_if_empty(holder_dir: Path) -> None:
    try:
        holder_dir.rmdir()
    except OSError:
        pass


def _close_holder(
    holder_fd: int | None,
    holder_path: Path | None,
    *,
    unlink: bool = True,
) -> None:
    if holder_fd is not None:
        try:
            fcntl.flock(holder_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(holder_fd)
    if unlink and holder_path is not None:
        try:
            holder_path.unlink()
        except FileNotFoundError:
            pass


def _cleanup_shared_state(p: Path, bak: Path, state_path: Path) -> dict | None:
    state = _shared_state(state_path)
    if state is None:
        return None

    live = _live_holders(state.get("holders", []))

    if live:
        if len(live) != len(state.get("holders", [])):
            state["holders"] = live
            _atomic_write(state_path, json.dumps(state, indent=2))
        return state

    # All recorded holders died before releasing. Restore the saved pre-shared
    # settings snapshot, then clear the lease so the next caller is not wedged.
    _crash_recover(p, bak)
    try:
        state_path.unlink()
    except FileNotFoundError:
        pass
    _remove_holder_dir_if_empty(_holder_dir(p))
    return None


@contextlib.contextmanager
def _shared_readonly_guard(
    p: Path,
    bak: Path,
    lock: Path,
    deny_rules: list,
    lock_timeout: float,
):
    state_path = _shared_state_path(p)
    holders_dir = _holder_dir(p)
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    holder_path = holders_dir / f"{token}.lock"
    holder_fd: int | None = None
    key = _deny_key(deny_rules)
    deadline = time.monotonic() + lock_timeout
    lock_fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(lock_fd, False)
    acquired = False
    joined = False
    entry_snap: dict | None = None
    mutated = False
    try:
        holders_dir.mkdir(parents=True, exist_ok=True)
        holder_fd = os.open(str(holder_path), os.O_CREAT | os.O_RDWR, 0o600)
        os.set_inheritable(holder_fd, False)
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        while True:
            _lock_until(lock_fd, deadline)
            acquired = True
            state = _cleanup_shared_state(p, bak, state_path)
            if state is not None and state.get("deny_key") != key:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                acquired = False
                if time.monotonic() >= deadline:
                    raise TimeoutError("agy settings lock timeout")
                time.sleep(0.1)
                continue

            if state is None:
                _crash_recover(p, bak)
                entry_snap = _snapshot(p)
                _atomic_write(bak, json.dumps(entry_snap))
                _merge_deny(p, deny_rules)
                mutated = True
                state = {"deny_key": key, "holders": []}

            state["holders"].append(
                {
                    "token": token,
                    "pid": os.getpid(),
                    "lock_path": str(holder_path),
                }
            )
            _atomic_write(state_path, json.dumps(state, indent=2))
            joined = True
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            acquired = False
            break

        yield
    finally:
        body_had_exception = sys.exc_info()[0] is not None

        if not joined:
            if mutated and entry_snap is not None:
                cleanup_fd: int | None = None
                cleanup_acquired = acquired
                try:
                    if not cleanup_acquired:
                        cleanup_fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
                        os.set_inheritable(cleanup_fd, False)
                        _lock_until(cleanup_fd, time.monotonic() + lock_timeout)
                        cleanup_acquired = True
                    _restore(p, entry_snap)
                    try:
                        bak.unlink()
                    except FileNotFoundError:
                        pass
                    try:
                        state_path.unlink()
                    except FileNotFoundError:
                        pass
                finally:
                    if cleanup_fd is not None:
                        if cleanup_acquired:
                            fcntl.flock(cleanup_fd, fcntl.LOCK_UN)
                        os.close(cleanup_fd)
            _close_holder(holder_fd, holder_path)
            _remove_holder_dir_if_empty(holders_dir)
            holder_fd = None
            holder_path = None
        else:
            release_fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
            os.set_inheritable(release_fd, False)
            release_acquired = False
            release_completed = False
            try:
                try:
                    _lock_until(release_fd, time.monotonic() + lock_timeout)
                    release_acquired = True
                except TimeoutError as e:
                    if body_had_exception:
                        sys.stderr.write(
                            f"[agy_settings] release cleanup deferred after "
                            f"body exception: {e}\n"
                        )
                    else:
                        raise
                else:
                    state = _shared_state(state_path)
                    if state is None:
                        _close_holder(holder_fd, holder_path)
                        holder_fd = None
                        holder_path = None
                        _remove_holder_dir_if_empty(holders_dir)
                        release_completed = True
                    else:
                        holders = [
                            holder for holder in state.get("holders", [])
                            if holder.get("token") != token
                        ]
                        _close_holder(holder_fd, holder_path)
                        holder_fd = None
                        holder_path = None
                        holders = _live_holders(holders)
                        if holders:
                            state["holders"] = holders
                            _atomic_write(state_path, json.dumps(state, indent=2))
                        else:
                            _restore(p, json.loads(bak.read_text()))
                            try:
                                bak.unlink()
                            except FileNotFoundError:
                                pass
                            try:
                                state_path.unlink()
                            except FileNotFoundError:
                                pass
                            _remove_holder_dir_if_empty(holders_dir)
                        release_completed = True
            finally:
                if release_acquired:
                    fcntl.flock(release_fd, fcntl.LOCK_UN)
                os.close(release_fd)
                if not release_completed:
                    _close_holder(holder_fd, holder_path, unlink=False)
                    holder_fd = None
                    holder_path = None
                _remove_holder_dir_if_empty(holders_dir)
                if not release_completed and not body_had_exception:
                    if acquired:
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        acquired = False
                    os.close(lock_fd)
                    lock_fd = -1

        if lock_fd != -1 and acquired:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        if lock_fd != -1:
            os.close(lock_fd)


@contextlib.contextmanager
def _exclusive_settings_guard(
    p: Path,
    bak: Path,
    lock: Path,
    deny_rules: list,
    lock_timeout: float,
):
    state_path = _shared_state_path(p)
    lock_fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    os.set_inheritable(lock_fd, False)
    acquired = False
    snap: dict | None = None
    try:
        deadline = time.monotonic() + lock_timeout
        while True:
            _lock_until(lock_fd, deadline)
            acquired = True
            state = _cleanup_shared_state(p, bak, state_path)
            if state is None:
                break
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            acquired = False
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
        if acquired:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


@contextlib.contextmanager
def agy_settings_guard(deny_rules, *, lock_timeout: float = 30.0):
    """Bracket an agy call in a global-settings deny transaction.

    Read-only calls share an active identical deny transaction so multiple
    projects can run read-only agy consults concurrently. Workspace-write and
    other modes remain exclusive. Every first/exclusive entrant runs
    crash-recovery so a stale .agybak from a prior crashed call is healed before
    settings are mutated.
    """
    p = _settings_path()
    bak = p.with_name(".agybak")
    lock = p.with_name(".agy_settings.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    if _shareable_deny(deny_rules):
        with _shared_readonly_guard(p, bak, lock, deny_rules, lock_timeout):
            yield
        return
    with _exclusive_settings_guard(p, bak, lock, deny_rules, lock_timeout):
        yield
