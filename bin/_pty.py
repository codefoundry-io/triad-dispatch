#!/usr/bin/env python3
"""Stdlib-pty runner for CLIs (agy) that drop stdout on a non-TTY stdout.

agy -p emits nothing and hangs when stdout is not a tty (GitHub
google-antigravity/antigravity-cli#76). Driving it through a pty makes it
believe it has a terminal. No `script`/`pexpect` dependency (BSD vs util-linux
`script` syntax differs — would break artifact portability).
"""
from __future__ import annotations

import errno
import os
import pty
import select
import signal
import time
from dataclasses import dataclass


@dataclass
class PtyResult:
    output_bytes: bytes
    rc: int
    killed: bool


def run_via_pty(cmd, cwd=None, timeout=600, env=None) -> PtyResult:
    """Run cmd under a pty, capture combined output, enforce timeout.

    EOF is handled cross-platform: macOS returns b"" on the master fd after the
    child closes; Linux raises OSError(EIO). The child runs in its own session
    (setsid via forkpty) so a timeout kills the whole subtree via killpg.
    """
    full_env = dict(os.environ if env is None else env)
    full_env.setdefault("TERM", "dumb")  # suppress TUI escapes

    pid, master_fd = pty.fork()
    if pid == 0:  # child — own session courtesy of pty.fork()
        try:
            if cwd:
                os.chdir(cwd)
            os.execvpe(cmd[0], list(cmd), full_env)
        except Exception:
            os._exit(127)

    chunks = bytearray()
    killed = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                killed = True
                break
            r, _, _ = select.select([master_fd], [], [], min(remaining, 1.0))
            if master_fd in r:
                try:
                    data = os.read(master_fd, 65536)
                except OSError as e:
                    if e.errno == errno.EIO:  # Linux EOF
                        break
                    raise
                if not data:  # macOS EOF
                    break
                chunks.extend(data)
    finally:
        os.close(master_fd)
        child_status = _killpg(pid) if killed else None
        rc = _reap(pid, child_status)
    return PtyResult(bytes(chunks), rc, killed)


def _killpg(pid: int):
    """Signal the child's process GROUP down (SIGTERM, escalate to SIGKILL).

    Returns the direct child's raw wait status if we reaped it here (so the
    caller's _reap can recover it after ChildProcessError), else None.

    The escalation gate is the GROUP, not the direct child: after the direct
    child is reaped on SIGTERM, lingering descendants in the same group still
    warrant SIGKILL. We probe the group with signal 0 (ProcessLookupError =>
    empty => done) instead of inferring "group gone" from the direct child.
    """
    try:
        pgid = os.getpgid(pid)
    except OSError as e:
        # ESRCH: the child is already gone. EPERM: the pid was reused by a
        # process in another session whose pgid we may not query (PID reuse
        # under load) — getpgid itself can raise EPERM, not just killpg. Either
        # way we cannot resolve the group; nothing to signal. Re-raise anything
        # unexpected (not ESRCH/EPERM) loudly rather than swallowing it.
        if e.errno not in (errno.ESRCH, errno.EPERM):
            raise
        return None
    captured_status = None
    for sig in (signal.SIGTERM, signal.SIGKILL):
        # Escalate only if the group still has at least one member.
        try:
            os.killpg(pgid, sig)
        except OSError as e:
            # kill(-pgid) raises ESRCH when no process remains in the group,
            # and EPERM when it could signal NO member — i.e. the pgid no
            # longer maps to a group we may signal (emptied, or reused by a
            # group we do not own). kill(-pgid) succeeds as long as it can
            # signal at least one member, so an EPERM here means there is
            # nothing left we can act on; stop escalating.
            #
            # Residual NOT closed by this guard: if the reused pgid is a
            # same-uid group we CAN signal, killpg SUCCEEDS and mis-signals it
            # (no exception raised), so the getpgid->killpg TOCTOU window is
            # still a (rare, microsecond) wrong-signal hazard — a pidfd-based
            # approach would be the stronger fix if that is ever observed.
            # Anything other than ESRCH/EPERM is unexpected — re-raise loudly.
            if e.errno not in (errno.ESRCH, errno.EPERM):
                raise
            break
        for _ in range(20):  # up to ~1s for the signal to land
            # Reap the direct child non-blocking; capture its status so the
            # real exit (WIFSIGNALED -> 128+sig) is not lost to -1 later.
            if captured_status is None:
                try:
                    wpid, status = os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    wpid, status = pid, None
                if wpid == pid and status is not None:
                    captured_status = status
            # Group-empty probe: kill(-pgid, 0) raises ESRCH when no process
            # remains, and EPERM when nothing remaining is signalable by us.
            # Either way there is nothing left for the SIGKILL escalation to
            # act on. Re-raise anything other than ESRCH/EPERM loudly.
            try:
                os.killpg(pgid, 0)
            except OSError as e:
                if e.errno not in (errno.ESRCH, errno.EPERM):
                    raise
                return captured_status
            time.sleep(0.05)
    return captured_status


def _reap(pid: int, prereaped_status=None) -> int:
    """Reap the child and map its wait status to an rc.

    `prereaped_status` is the raw status captured by `_killpg` (if it already
    reaped the direct child). On ChildProcessError — the child was already
    reaped — fall back to that status instead of the -1 sentinel so a killed
    child reports its real 128+signal code.
    """
    try:
        _, status = os.waitpid(pid, 0)
    except ChildProcessError:
        status = prereaped_status
    if status is None:
        return -1
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return -1
