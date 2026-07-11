#!/usr/bin/env python3
"""review_scratch.py — review-packet scratch lifecycle (P3 cleanup guarantee).

The cross-family review flow creates reviewer-owned packet dirs under a
gitignored scratch root. A prose "clean up after the review" instruction
cannot survive a crashed/abandoned review, which strands packets. This
helper makes the guarantee deterministic and review-owned by design:
enforcement lives in the review skill, NEVER the dispatch wrappers — a
wrapper-side prune of a caller-owned path is scope-creep and, in a plugin
install, a foreign-repo deletion hazard.

Subcommands (absolute paths only):
    open <abs-root> <slug>   create <root>/<UTC-date>-<slug>/ with an
                             `.active` heartbeat file, prune stale siblings,
                             print the created dir on stdout.
    touch <abs-dir>          refresh the `.active` heartbeat (long
                             fix->re-confirm loops outlive any fixed floor).
    close <abs-dir>          delete the dir (the normal end-of-review path).

Prune rules (applied only during `open`, only to DIRECT children of the
explicit root, only to DATE-PREFIXED (YYYY-MM-DD-...) real directories that
CARRY the helper's `.active` ownership marker):
    - stale when the `.active` heartbeat mtime is older than the floor (a
      crashed loop stops refreshing it; a normally-closed dir was deleted
      whole by `close`, so every helper-managed dir carries the marker).
    - `.active` absent -> NOT helper-managed -> skipped with a note, never
      deleted. This makes every deletion in this file ownership-fenced: a
      typo'd root cannot reap foreign date-named directories. TWO bounded
      self-healing exceptions: an EMPTY unmanaged date-dir is os.rmdir'd
      (an open-crash shell; rmdir can only ever remove an empty dir, never
      content), and a `<name>.pruning` dir (the helper-reserved claim
      suffix) is reclaimed — it passed the fence when a prior prune/close
      renamed it and its deletion failed partway.
    - symlinks are refused (never followed, never deleted); non-date names
      and plain files are never touched.

Floor: TRIAD_REVIEW_SCRATCH_MAX_AGE_DAYS (default 7).

Python3 stdlib on purpose: BSD (macOS) and GNU (Ubuntu 24.04) `date` flags
diverge, python3.12 is identical on both artifact platforms.
"""

import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-.+")
_SLUG_RE = re.compile(r"[A-Za-z0-9._-]+")  # used via fullmatch (a $-anchored
# match() would accept a trailing newline — Python's $ matches before it)
_DEFAULT_FLOOR_DAYS = 7
# Provenance magic: minted into `.active` at open-time and REQUIRED by every
# ownership check. An ordinary file that merely happens to be named .active
# (a foreign tool's, a stray touch) never authorizes a deletion. Compared as
# BYTES (round-4 codex: text-mode reads apply universal-newline translation,
# so a CRLF/CR variant would forge the LF magic).
_MARKER_MAGIC = b"review_scratch/1\n"
# Helper-reserved suffix: a stale dir is atomically RENAMED to <name>.pruning
# before rmtree; a partially-failed deletion is therefore reclaimed by the
# next open regardless of its (possibly already-deleted) marker.
_PRUNING_SUFFIX = ".pruning"


def _fail(msg: str) -> "NoReturn":  # noqa: F821 - py3.12 accepts the string form
    print(f"review_scratch: {msg}", file=sys.stderr)
    sys.exit(2)


def _floor_days() -> int:
    raw = os.environ.get("TRIAD_REVIEW_SCRATCH_MAX_AGE_DAYS", "")
    try:
        days = int(raw) if raw else _DEFAULT_FLOOR_DAYS
    except ValueError:
        print(f"review_scratch: ignoring non-numeric floor {raw!r}; "
              f"using {_DEFAULT_FLOOR_DAYS}", file=sys.stderr)
        return _DEFAULT_FLOOR_DAYS
    if days < 1 or days > 3650:
        # A floor < 1 day would classify a sibling whose heartbeat was touched
        # SECONDS ago (a live concurrent review) as stale — out of contract;
        # an absurdly large one can overflow datetime arithmetic. Invalid knob
        # values fall back to the default, loudly.
        print(f"review_scratch: ignoring invalid floor {days!r} "
              f"(valid: 1-3650 days); using {_DEFAULT_FLOOR_DAYS}",
              file=sys.stderr)
        return _DEFAULT_FLOOR_DAYS
    return days


def _require_abs(arg: str, label: str) -> Path:
    if "\n" in arg or "\r" in arg:
        # the printed packet path is a ONE-LINE stdout contract (round-4)
        _fail(f"{label} must not contain line terminators")
    path = Path(arg)
    if not path.is_absolute():
        _fail(f"{label} must be an absolute path (got {arg!r})")
    return path


def _is_managed_marker(heartbeat: Path) -> bool:
    """True only for a marker this helper MINTED: a regular non-symlink file
    whose content is the provenance magic. An ordinary file that merely
    happens to be named .active (a foreign tool's) never proves ownership
    (round-3: deletion must be provenance-bound, not name-bound)."""
    if heartbeat.is_symlink() or not heartbeat.is_file():
        return False
    try:
        # bounded BINARY read (round-4): binary mode dodges universal-newline
        # translation (a CRLF variant must not forge the LF magic), and
        # len+1 bytes decide ownership either way — a huge foreign file
        # named .active must not OOM the prune loop.
        with heartbeat.open("rb") as f:
            return f.read(len(_MARKER_MAGIC) + 1) == _MARKER_MAGIC
    except OSError:
        return False  # unreadable — never treat as owned


def _require_date_dir(path: Path, label: str) -> Path:
    """Validate + CANONICALIZE a caller-supplied managed-dir path. Returns
    the resolved path so later operations act on the same file the checks
    inspected (a symlinked ANCESTOR must not redirect an rmtree)."""
    if path.is_symlink():
        _fail(f"{label} is a symlink — refused")
    path = path.resolve()
    if not path.is_dir():
        _fail(f"{label} is not a directory: {path}")
    if not _DATE_PREFIX_RE.match(path.name):
        _fail(f"{label} basename must be YYYY-MM-DD-<slug> (got {path.name!r})")
    # Ownership fence: only dirs this helper created (via `open`) carry the
    # MAGIC-bearing `.active` heartbeat. Without it, a caller-supplied
    # absolute path that merely HAPPENS to be date-prefixed (a downloads
    # folder, a data dir) would be one typo away from an rmtree — refuse.
    if not _is_managed_marker(path / ".active"):
        _fail(f"{label} carries no helper-minted .active ownership marker — "
              f"not a review_scratch-managed dir; remove it manually if "
              f"intended")
    return path


def _prune_stale(root: Path, keep: Path, now: datetime, floor_days: int) -> None:
    cutoff_ts = (now - timedelta(days=floor_days)).timestamp()
    for child in sorted(root.iterdir()):
        if child == keep:
            continue
        if child.is_symlink():
            print(f"review_scratch: skip symlink {child.name}", file=sys.stderr)
            continue
        if not child.is_dir():
            continue
        if not _DATE_PREFIX_RE.match(child.name):
            continue
        if child.name.endswith(_PRUNING_SUFFIX):
            # A prior claimed-but-failed deletion (round-4 failure atomicity):
            # the dir passed the ownership fence WHEN it was claimed/renamed
            # (open refuses *.pruning slugs, so no live packet can wear this
            # name), so reclaim it even though its marker may already be gone.
            shutil.rmtree(child, ignore_errors=True)
            if child.exists():
                print(f"review_scratch: reclaim FAILED for {child.name} "
                      f"(left for the next open)", file=sys.stderr)
            else:
                print(f"review_scratch: reclaimed {child.name}",
                      file=sys.stderr)
            continue
        heartbeat = child / ".active"
        if not _is_managed_marker(heartbeat):
            # Ownership fence (rounds 2-3): every helper-created dir carries
            # the MAGIC-bearing `.active` file (open mints it; close removes
            # the WHOLE dir), so a marker-less — or foreign-marker — date-dir
            # is NOT ours: a typo'd root must never reap foreign date-named
            # directories. ONE self-healing exception (round-4 open-crash
            # residue: mkdir landed, the marker mint did not): an EMPTY
            # unmanaged date-dir is removed with os.rmdir — which can only
            # ever delete an empty shell, never content — unblocking the
            # slug. Anything non-empty is skipped, loudly.
            try:
                child.rmdir()
                print(f"review_scratch: removed empty unmanaged {child.name}",
                      file=sys.stderr)
            except OSError:
                print(f"review_scratch: skip unmanaged {child.name} "
                      f"(no helper-minted .active)", file=sys.stderr)
            continue
        try:
            stale = heartbeat.stat().st_mtime < cutoff_ts
        except OSError:
            continue  # racing/unreadable — never delete on uncertainty
        if stale:
            # atomic CLAIM before delete (round-4): rename first, so a
            # concurrent `touch` racing the staleness check fails loudly on
            # the vanished path (its FileNotFoundError guard) instead of
            # refreshing a dir mid-rmtree.
            claim = child.with_name(child.name + ".pruning")
            try:
                child.rename(claim)
            except OSError:
                continue  # raced/vanished — never delete on uncertainty
            shutil.rmtree(claim, ignore_errors=True)
            if claim.exists():
                print(f"review_scratch: prune FAILED for {child.name} "
                      f"(left for the next open)", file=sys.stderr)
            else:
                print(f"review_scratch: pruned stale {child.name}",
                      file=sys.stderr)


def cmd_open(root_arg: str, slug: str) -> None:
    root = _require_abs(root_arg, "root")
    if root.is_symlink():
        _fail("root is a symlink — refused (consistent with the child rule)")
    # Canonicalize (round-3): a symlinked ANCESTOR must not let later
    # operations act on a different path than the one inspected here.
    root = root.resolve()
    if not _SLUG_RE.fullmatch(slug):
        # fullmatch, not $-anchored match: Python's $ matches before a
        # trailing newline, and a newline-bearing dirname breaks the printed
        # one-line path contract (round-3 codex finding).
        _fail(f"slug must fully match [A-Za-z0-9._-]+ (got {slug!r})")
    if slug.lower().endswith(_PRUNING_SUFFIX):
        # round-5 (all three reviewer families converged): a live packet
        # named *.pruning would be unconditionally reclaimed by the NEXT
        # open — the suffix is helper-reserved for claimed deletions, never
        # a valid slug tail. Case-insensitive: common macOS filesystems are.
        _fail(f"slug must not end with the reserved {_PRUNING_SUFFIX!r} suffix")
    now = datetime.now(timezone.utc)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except (FileExistsError, NotADirectoryError):
        _fail(f"root exists but is not a directory: {root}")
    target = root / f"{now.date().isoformat()}-{slug}"
    try:
        # create-NEW-only (round-3): adopting a pre-existing dir would mint
        # ownership over content this invocation did not create — and a
        # same-day duplicate slug would silently SHARE a packet dir, letting
        # one review's close delete the other's. Fail loud instead.
        target.mkdir()
    except FileExistsError:
        _fail(f"{target} already exists — open never adopts an existing "
              f"dir; pick a distinct slug (or touch/close the existing one "
              f"explicitly)")
    (target / ".active").write_bytes(_MARKER_MAGIC)
    _prune_stale(root, keep=target, now=now, floor_days=_floor_days())
    print(target)


def cmd_touch(dir_arg: str) -> None:
    path = _require_date_dir(_require_abs(dir_arg, "dir"), "dir")
    try:
        # refresh-only (round-3): utime on the EXISTING marker — touch must
        # never mint ownership, even if the marker vanishes mid-call.
        os.utime(path / ".active")
    except FileNotFoundError:
        _fail("heartbeat vanished mid-refresh — touch never mints ownership")


def cmd_close(dir_arg: str) -> None:
    path = _require_date_dir(_require_abs(dir_arg, "dir"), "dir")
    # claim-then-delete (round-4 failure atomicity, same mechanism as the
    # prune): a partially-failed rmtree would otherwise strip `.active` and
    # leave a dir the fence refuses forever; a claimed `.pruning` dir is
    # reclaimed by the next open.
    claim = path.with_name(path.name + _PRUNING_SUFFIX)
    try:
        path.rename(claim)
    except OSError as e:
        _fail(f"close could not claim {path.name}: {e}")
    shutil.rmtree(claim, ignore_errors=True)
    if claim.exists():
        _fail(f"close left partial state at {claim.name} — the next open "
              f"reclaims it")
    print(f"review_scratch: closed {path.name}", file=sys.stderr)


def main(argv: list) -> None:
    if len(argv) == 3 and argv[0] == "open":
        cmd_open(argv[1], argv[2])
    elif len(argv) == 2 and argv[0] == "touch":
        cmd_touch(argv[1])
    elif len(argv) == 2 and argv[0] == "close":
        cmd_close(argv[1])
    else:
        _fail("usage: review_scratch.py open <abs-root> <slug> | "
              "touch <abs-dir> | close <abs-dir>")


if __name__ == "__main__":
    main(sys.argv[1:])
