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
    capture <abs-packet-dir> <abs-worktree-root> <label>
                             snapshot a round's evidence: sha256 census of
                             the packet dir + canonical worktree fingerprint,
                             written EXCLUSIVE-CREATE to
                             <packet-dir>/.snapshot-<label>.json. Prints the
                             covered-file count on stderr (an accidentally
                             EARLY capture is then visible at dispatch time).
    verify <abs-packet-dir> <abs-worktree-root> <label>
                             recompute + compare against the captured
                             snapshot; prints `ROUND_INTEGRITY_OK <label>`
                             or fails loud naming what diverged.

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

Round integrity (adopted 2026-08-10 from codex-host 0.2.533's
bin/review_round.py, adapted to the REUSED packet-dir model): codex-host
mints a FRESH evidence root per review round. Triad's packet dir is created
ONCE by `open` and accumulates every leg's output ACROSS rounds (e.g.
codex-r1.out, then codex-r2.out on the next round) — so a round's integrity
is captured over a per-round SNAPSHOT-LISTED file set, never the whole
directory. `capture` folds a sha256 census of the packet dir (regular files
only, symlinks refused) plus a canonical worktree fingerprint (HEAD, status,
staged/unstaged diff with git flags PINNED so local repo config can never
perturb the bytes, the index-flag state, and every untracked file's content)
into one prepared digest, written exclusive-create so a label is captured at
most once. `verify` recomputes over exactly the snapshot-listed files — a
file that appears LATER (a subsequent round's leg output) is ignored by
design — with the worktree-fingerprint recompute bracketed by two digest
checks (TOCTOU: catches a mutation racing the fingerprint computation
itself).

Two holes found by the 2026-08-11 cross-family gate and closed here:
  - INDEX FLAGS (codex Critical, probe-confirmed). git suppresses an entry
    marked assume-unchanged or skip-worktree from `status --porcelain` and
    from BOTH diffs, so a flagged tracked file could be rewritten mid-round
    with every fingerprint arm staying byte-identical. Fail-closed in
    `_index_flag_state`: an outright REFUSAL, at capture AND at verify, of any
    lowercase (assume-unchanged) or S/s (skip-worktree) tag — that is the
    layer that fires — plus an INDEXFLAGS fingerprint arm folding `git
    ls-files -v -z`, retained as defense-in-depth should the refusal ever be
    relaxed (see that function's docstring). A git SPARSE-CHECKOUT worktree
    trips the refusal by construction (every out-of-cone entry is
    skip-worktree) and gets its own message: capture/verify do not support a
    sparse worktree, and the generic `--no-skip-worktree` prescription would
    materialize the excluded paths there.
  - UNCOVERED FILES (3-family convergence; claude demonstrated it live). Only
    iterating snapshot['files'] made every post-capture addition invisible —
    including leg INPUT files written after capture, i.e. the exact bytes the
    reviewers were handed. `verify` now re-enumerates the packet dir and
    refuses any uncovered file that is not a declared leg OUTPUT
    (`_LEG_OUTPUT_GLOBS`); leg inputs must therefore exist BEFORE capture.

File hashing is STREAMED (`_digest_regular_file` feeds each chunk into the
hasher instead of joining a chunk list): the untracked arm walks every
untracked file in the worktree, and only digests are ever needed. Digest
bytes are unchanged — the tests pin a multi-chunk file against a plain
hashlib pass.

Python3 stdlib on purpose: BSD (macOS) and GNU (Ubuntu 24.04) `date` flags
diverge, python3.12 is identical on both artifact platforms. Git is invoked
via subprocess (LC_ALL=C pinned) rather than a git-porcelain library, for
the same cross-platform-stdlib-only reason.
"""

import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
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


# ---------------------------------------------------------------------------
# Round integrity (capture / verify) — see the module docstring for the
# user-facing contract and the codex-host provenance/adaptation note.
# ---------------------------------------------------------------------------

# git diff flags PINNED on every invocation (capture AND verify use the same
# list) so a reviewer's or a repo's LOCAL git config (diff.algorithm,
# diff.context, rename-detection thresholds, textconv filters, ...) can
# never perturb the fingerprint — the explicit flags always win over config,
# so flipping config between capture and verify is a no-op by construction.
_DIFF_FLAGS = (
    "--binary",
    "--full-index",
    "--no-color",
    "--no-ext-diff",
    "--unified=3",
    "--diff-algorithm=myers",
    "--no-indent-heuristic",
    "--find-renames=50%",
    "--no-textconv",
)


# Declared LEG-OUTPUT patterns: the only files a leg may add to the REUSED
# packet dir AFTER a round's capture. Everything else that shows up uncovered
# at verify time is refused — above all a leg INPUT (packet.md, digest.txt,
# <cli>-body.txt, *-prompt.txt), which must exist BEFORE capture so the census
# actually freezes the bytes the reviewers were handed. Matched with
# fnmatchcase against the POSIX relpath (so `*` also spans a subdirectory
# separator — a nested `sub/codex-r1.out` is still leg output).
# `*-verdict.json` (r2 claude Minor): the skill's own triage reference
# documents a per-leg consolidation artifact written AFTER the leg answers, so
# it is leg OUTPUT by the same rule as `*.out` — it was hitting the
# uncovered-file refusal purely because the allowlist predated it.
_LEG_OUTPUT_GLOBS = ("*.out", "*.err", "*-read-audit.json", "claude-r*.json",
                     "*-verdict.json")


def _record(hasher, tag: bytes, payload: bytes) -> None:
    """Length-prefixed tag/payload framing (mirrors codex-host's `_record`):
    folding raw concatenated bytes into a hash is ambiguous — a filename
    boundary can be forged by another (filename, content) split with the
    same total bytes. The explicit tag + length prefix removes that
    ambiguity."""
    hasher.update(tag)
    hasher.update(b"\0")
    hasher.update(str(len(payload)).encode("ascii"))
    hasher.update(b"\0")
    hasher.update(payload)


def _digest_regular_file(path: Path, label: str) -> str:
    """sha256 hex of a regular file, hashed INCREMENTALLY (each chunk is fed
    straight into the hasher, never accumulated into a chunk list that is then
    joined into one buffer: every caller here wants only a digest, and the
    untracked-file arm walks EVERY untracked file in the worktree — a repo
    carrying multi-hundred-MB scratch artifacts would otherwise pay 2x peak
    memory per file for bytes nobody looks at). O_NOFOLLOW: a symlink swapped
    in between a listing walk and this read is refused rather than silently
    followed. Digest bytes are unchanged by the streaming — sha256 over the
    same content is the same hash however it is fed in."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError as e:
        _fail(f"{label} could not be read: {path}: {e}")
    hasher = hashlib.sha256()
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            _fail(f"{label} is not a regular file: {path}")
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    finally:
        os.close(fd)
    return hasher.hexdigest()


def _packet_relpaths(packet_dir: Path) -> list:
    """Recursive census of `packet_dir`: every REGULAR file, sorted by
    relative POSIX path, excluding the lifecycle `.active` marker and any
    `.snapshot-*.json` round file (both live directly under packet_dir — the
    helper's own bookkeeping, never round evidence). A symlink or other
    non-regular entry ANYWHERE under the tree fails loud — never followed,
    never silently skipped."""
    found = []

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda e: os.fsencode(e.name))
        except OSError as e:
            _fail(f"packet dir could not be read: {e}")
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                _fail(f"packet dir contains a symlink: {path}")
            if entry.is_dir(follow_symlinks=False):
                visit(path)
            elif entry.is_file(follow_symlinks=False):
                rel = path.relative_to(packet_dir)
                if rel.parts == (".active",):
                    continue
                if (
                    len(rel.parts) == 1
                    and rel.parts[0].startswith(".snapshot-")
                    and rel.parts[0].endswith(".json")
                ):
                    continue
                found.append(path)
            else:
                _fail(f"packet dir contains an unsupported entry: {path}")

    visit(packet_dir)
    found.sort(key=lambda p: p.relative_to(packet_dir).as_posix())
    return found


def _hash_packet_files(packet_dir: Path, files: list) -> list:
    """(relpath, sha256-hex) pairs, sorted by relpath — the shape captured
    into the snapshot's "files" array and folded into the prepared
    digest."""
    out = []
    for path in files:
        rel = path.relative_to(packet_dir).as_posix()
        out.append((rel, _digest_regular_file(path, "packet file")))
    out.sort(key=lambda pair: pair[0])
    return out


def _prepared_digest(entries: list) -> str:
    """Fold (relpath, sha256-hex) pairs into one digest via the
    length-prefixed `_record` framing. Order-independent input is made
    order-DEPENDENT by the caller pre-sorting `entries`, so this stays a
    pure fold."""
    hasher = hashlib.sha256()
    for rel, filehash in entries:
        payload = rel.encode("utf-8") + b"\0" + filehash.encode("ascii")
        _record(hasher, b"FILE", payload)
    return hasher.hexdigest()


def _git(cwd: Path, *args: str) -> bytes:
    """Run one git inspection call with LC_ALL=C pinned (porcelain output
    must never localize) — the env is COPIED and only LC_ALL is overridden
    (blanking the env would drop PATH/HOME and break git's own lookups on
    some setups). Any non-zero exit fails loud with git's own stderr."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as e:
        _fail(f"git {' '.join(args)} could not be run: {e}")
    if proc.returncode != 0:
        diagnostic = proc.stderr.decode("utf-8", "replace").strip()
        _fail(f"git {' '.join(args)} failed: {diagnostic}")
    return proc.stdout


def _require_worktree_toplevel(arg: str) -> Path:
    """Validate + canonicalize a caller-supplied worktree-root: absolute,
    not a symlink, and must resolve to the SAME path git itself reports as
    the toplevel — a subdirectory of a repo or a non-repo path is refused (a
    round's fingerprint is only meaningful over the whole repo state)."""
    worktree = _require_abs(arg, "worktree")
    if worktree.is_symlink():
        _fail("worktree is a symlink — refused")
    worktree = worktree.resolve()
    if not worktree.is_dir():
        _fail(f"worktree is not a directory: {worktree}")
    raw = _git(worktree, "rev-parse", "--show-toplevel")
    try:
        toplevel = Path(raw.decode("utf-8", "strict").strip()).resolve()
    except UnicodeDecodeError:
        _fail("git toplevel path is not UTF-8")
    if toplevel != worktree:
        _fail(f"worktree must be the git toplevel (got {worktree}, "
              f"toplevel is {toplevel})")
    return worktree


def _sparse_checkout_enabled(worktree: Path) -> bool:
    """True when `core.sparseCheckout` is configured true for this worktree.

    Deliberately NOT routed through `_git`: `git config` exits 1 when the key
    is simply UNSET, which is the ordinary non-sparse case and must not fail
    loud. Any other trouble (git missing, unreadable config) also reports
    False — this only ever selects WHICH refusal message is printed, never
    whether the refusal happens.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    try:
        proc = subprocess.run(
            ["git", "config", "--bool", "core.sparseCheckout"],
            cwd=str(worktree),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return False
    if proc.returncode != 0:
        return False
    return proc.stdout.decode("utf-8", "replace").strip() == "true"


def _index_flag_state(worktree: Path) -> bytes:
    """Return `git ls-files -v -z` verbatim (the INDEXFLAGS fingerprint arm),
    REFUSING loud first if any entry carries an index flag that blinds every
    other arm.

    `ls-files -v` emits `<tag> <path>` per record; the tag is uppercase
    normally (`H` tracked, `M` unmerged, `R`/`C` unstaged removal/change, `K`,
    `?`, `U`), LOWERCASE when the entry is marked assume-unchanged, and `S`
    (or `s`, when both flags are set) when it is marked skip-worktree. git
    suppresses such an entry from `status --porcelain` AND from both diffs —
    probe-confirmed — so a flagged tracked file can be rewritten mid-round
    while HEAD/STATUS/STAGED/UNSTAGED stay byte-identical and `verify` still
    prints ROUND_INTEGRITY_OK.

    The REFUSAL is what actually fires (r2 claude Q3). It is unconditional and
    runs at capture AND at verify, so any flagged entry aborts before the
    fingerprint it would have poisoned is ever compared — the INDEXFLAGS arm
    (folding this same `ls-files -v -z` output in, so a mid-round flag FLIP
    moves the fingerprint) is therefore NOT a live second catcher today. It is
    retained as DEFENSE-IN-DEPTH for the case where the refusal policy is ever
    relaxed (an allowlist for one flag, a specific path, say); as written, the
    refusal fires first and the arm never gets the chance. Fail-closed,
    following the untracked-symlink refusal precedent.

    SPARSE CHECKOUT (r2 claude Minor) gets its own message: `git
    sparse-checkout` sets skip-worktree on EVERY out-of-cone entry, so a
    sparse worktree trips this refusal by construction — and the generic
    message's `git update-index --no-skip-worktree` prescription would
    MATERIALIZE the excluded paths, which is actively wrong advice there. The
    refusal itself is unchanged: round integrity needs the full tracked
    surface, so a sparse worktree is simply unsupported."""
    raw = _git(worktree, "ls-files", "-v", "-z")
    for record in raw.split(b"\0"):
        if not record:
            continue
        tag = record[:1]
        if record[1:2] != b" ":
            _fail(f"git ls-files -v emitted an unparsable record: {record!r}")
        if tag.islower() or tag == b"S":
            path = record[2:].decode("utf-8", "replace")
            if _sparse_checkout_enabled(worktree):
                _fail(f"worktree uses git sparse-checkout "
                      f"(core.sparseCheckout=true) — refused: sparse-checkout "
                      f"marks every out-of-cone entry skip-worktree (e.g. "
                      f"{path}), and git hides such an entry's content "
                      f"mutations from status AND both diffs, so a round "
                      f"fingerprint over it proves nothing. capture/verify do "
                      f"NOT support a sparse worktree — round integrity needs "
                      f"the FULL tracked surface; re-run the round against a "
                      f"fully checked-out worktree")
            _fail(f"worktree index-flag refused: {path} is marked "
                  f"assume-unchanged/skip-worktree (ls-files -v tag "
                  f"{tag.decode('ascii', 'replace')!r}) — git hides such an "
                  f"entry's content mutations from status AND both diffs, so "
                  f"a round fingerprint over it proves nothing; clear it "
                  f"(git update-index --no-assume-unchanged "
                  f"--no-skip-worktree <path>) and re-run")
    return raw


def _worktree_fingerprint(worktree: Path) -> str:
    """Canonical fold of the worktree's mutable surface: HEAD, `status
    --porcelain`, staged + unstaged diff (both with `_DIFF_FLAGS` pinned so
    LOCAL git config can never perturb the bytes), the index-flag state (see
    `_index_flag_state` — it also REFUSES a flagged entry outright, at capture
    and at verify alike), and every untracked file's (relpath,
    content-sha256). A symlink among the untracked entries fails loud (never
    followed)."""
    hasher = hashlib.sha256()
    _record(hasher, b"HEAD", _git(worktree, "rev-parse", "HEAD"))
    _record(hasher, b"STATUS", _git(worktree, "status", "--porcelain"))
    _record(hasher, b"STAGED", _git(worktree, "diff", "--cached", *_DIFF_FLAGS))
    _record(hasher, b"UNSTAGED", _git(worktree, "diff", *_DIFF_FLAGS))
    _record(hasher, b"INDEXFLAGS", _index_flag_state(worktree))

    raw_list = _git(worktree, "ls-files", "--others", "--exclude-standard", "-z")
    untracked = sorted(v for v in raw_list.split(b"\0") if v)
    for raw_path in untracked:
        try:
            relative = raw_path.decode("utf-8", "strict")
        except UnicodeDecodeError:
            _fail("untracked path is not UTF-8")
        full = worktree / relative
        try:
            lst = full.lstat()
        except OSError as e:
            _fail(f"untracked entry vanished: {relative}: {e}")
        if stat.S_ISLNK(lst.st_mode):
            _fail(f"worktree contains an untracked symlink: {relative}")
        if not stat.S_ISREG(lst.st_mode):
            _fail(f"worktree contains an unsupported untracked entry: {relative}")
        digest = _digest_regular_file(full, "untracked file").encode("ascii")
        _record(hasher, b"UNTRACKED", raw_path + b"\0" + digest)
    return hasher.hexdigest()


def _snapshot_path(packet_dir: Path, label: str) -> Path:
    return packet_dir / f".snapshot-{label}.json"


def _require_label(label: str) -> str:
    # Same character class as slug (_SLUG_RE) — fullmatch, not $-anchored
    # match, for the same trailing-newline reason documented at _SLUG_RE.
    # No "/" in the class, so a label can never introduce a new path
    # segment — it only ever produces a (possibly odd-looking) literal
    # filename component embedded inside ".snapshot-<label>.json".
    if not _SLUG_RE.fullmatch(label):
        _fail(f"label must fully match [A-Za-z0-9._-]+ (got {label!r})")
    return label


def cmd_capture(packet_arg: str, worktree_arg: str, label: str) -> None:
    packet_dir = _require_date_dir(_require_abs(packet_arg, "packet dir"), "packet dir")
    label = _require_label(label)
    snapshot_path = _snapshot_path(packet_dir, label)
    if snapshot_path.is_symlink() or snapshot_path.exists():
        _fail(f"label {label!r} already captured at {snapshot_path.name} — "
              f"one label = one round; a re-capture is a FRESH label")
    worktree = _require_worktree_toplevel(worktree_arg)

    files_before = _packet_relpaths(packet_dir)
    entries_before = _hash_packet_files(packet_dir, files_before)
    digest_before = _prepared_digest(entries_before)

    fingerprint = _worktree_fingerprint(worktree)

    files_after = _packet_relpaths(packet_dir)
    entries_after = _hash_packet_files(packet_dir, files_after)
    digest_after = _prepared_digest(entries_after)
    if digest_before != digest_after:
        # TOCTOU (mirrors codex-host capture_round): the packet dir mutated
        # WHILE we were fingerprinting the worktree — abort before writing a
        # snapshot that would silently miss the mutation.
        _fail("packet dir changed during capture")

    snapshot = {
        "label": label,
        "packet_dir": str(packet_dir),
        "worktree": str(worktree),
        "files": [{"path": rel, "sha256": h} for rel, h in entries_after],
        "prepared_digest": digest_after,
        "worktree_fingerprint": fingerprint,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
    }
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        # exclusive-create: a race against a concurrent capture of the SAME
        # label fails loud instead of one silently overwriting the other's
        # evidence.
        fd = os.open(
            str(snapshot_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o644,
        )
    except FileExistsError:
        _fail(f"label {label!r} already captured — one label = one round; "
              f"a re-capture is a FRESH label")
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
    print(f"captured {label} {digest_after}")
    # Coverage count on STDERR (stdout stays the one-line `captured <label>
    # <digest>` contract): an accidentally-EARLY capture — fired before the
    # leg INPUT files (packet.md, digest.txt, <cli>-body.txt, *-prompt.txt)
    # were written — otherwise freezes a near-empty census silently. Seeing
    # "captured 1 packet files" at dispatch time makes that visible.
    print(f"review_scratch: captured {len(entries_after)} packet files",
          file=sys.stderr)


def _load_snapshot(path: Path) -> dict:
    if path.is_symlink():
        _fail(f"snapshot {path.name} is a symlink — refused")
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        _fail(f"no snapshot captured for {path.name}")
    except OSError as e:
        _fail(f"snapshot {path.name} could not be read: {e}")
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            _fail(f"snapshot {path.name} is not a regular file")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        _fail(f"snapshot {path.name} is not valid JSON: {e}")
    if not isinstance(decoded, dict):
        _fail(f"snapshot {path.name} is malformed")
    return decoded


def _require_no_uncovered_files(packet_dir: Path, covered: set) -> None:
    """Re-enumerate the packet dir's regular files (same census filter as
    capture — `.active` and `.snapshot-*.json` excluded, symlinks refused) and
    refuse any file the snapshot does NOT cover unless it matches a declared
    LEG-OUTPUT pattern.

    Without this, `verify` only ever looked at snapshot['files'], so ANY file
    added after capture was invisible — demonstrated live: the census froze
    packet.md + digest.txt while the codex leg's actual inlined body file
    (codex-body.txt) and agy-prompt.txt were written AFTER capture, i.e. the
    bytes the reviewers were handed were never under integrity at all. The
    reused-dir model still stands (a later round's leg OUTPUT must not break
    an earlier round — `_LEG_OUTPUT_GLOBS`); what is closed is the hole for
    everything else."""
    for path in _packet_relpaths(packet_dir):
        rel = path.relative_to(packet_dir).as_posix()
        if rel in covered:
            continue
        if any(fnmatch.fnmatchcase(rel, pattern) for pattern in _LEG_OUTPUT_GLOBS):
            continue
        _fail(f"uncovered non-output file in packet dir: {rel} — it is absent "
              f"from the round's snapshot census and matches no declared "
              f"leg-output pattern ({', '.join(_LEG_OUTPUT_GLOBS)}); a leg "
              f"INPUT file must exist BEFORE capture")


def _recompute_snapshot_digest(packet_dir: Path, listed, when: str) -> str:
    entries = []
    for item in listed:
        try:
            rel = item["path"]
            expected_hash = item["sha256"]
        except (KeyError, TypeError):
            _fail("snapshot is malformed (files)")
        full = packet_dir / rel
        try:
            lst = full.lstat()
        except OSError:
            _fail(f"round evidence missing{when}: {rel}")
        if stat.S_ISLNK(lst.st_mode):
            _fail(f"round evidence became a symlink{when}: {rel}")
        if not stat.S_ISREG(lst.st_mode):
            _fail(f"round evidence is no longer a regular file{when}: {rel}")
        actual_hash = _digest_regular_file(full, "round evidence")
        if actual_hash != expected_hash:
            _fail(f"round evidence changed{when}: {rel}")
        entries.append((rel, actual_hash))
    entries.sort(key=lambda pair: pair[0])
    return _prepared_digest(entries)


def cmd_verify(packet_arg: str, worktree_arg: str, label: str) -> None:
    packet_dir = _require_date_dir(_require_abs(packet_arg, "packet dir"), "packet dir")
    label = _require_label(label)
    worktree = _require_worktree_toplevel(worktree_arg)

    snapshot = _load_snapshot(_snapshot_path(packet_dir, label))
    if snapshot.get("packet_dir") != str(packet_dir):
        _fail("snapshot was captured for a different packet dir")
    if snapshot.get("worktree") != str(worktree):
        _fail("snapshot was captured for a different worktree")
    listed = snapshot.get("files")
    if not isinstance(listed, list):
        _fail("snapshot is malformed (files)")
    covered = set()
    for item in listed:
        try:
            rel = item["path"]
        except (KeyError, TypeError):
            _fail("snapshot is malformed (files)")
        if not isinstance(rel, str):
            _fail("snapshot is malformed (files)")
        covered.add(rel)

    # Coverage gate FIRST: the snapshot-listed set is the round's evidence,
    # but a file that the census never saw is not thereby innocent — only a
    # declared leg OUTPUT may appear uncovered.
    _require_no_uncovered_files(packet_dir, covered)

    # Per-round evidence set = SNAPSHOT-LISTED files only. A file that
    # appeared AFTER capture (a later leg's output — the packet dir is
    # REUSED across rounds, never fresh per round) is intentionally never
    # looked at here.
    digest = _recompute_snapshot_digest(packet_dir, listed, when="")
    if digest != snapshot.get("prepared_digest"):
        _fail("packet evidence digest mismatch")

    fingerprint = _worktree_fingerprint(worktree)

    # TOCTOU bracketing (mirrors codex-host verify_round): re-check the
    # packet evidence AFTER fingerprinting so a mutation racing the
    # fingerprint computation itself is caught too.
    digest_after = _recompute_snapshot_digest(packet_dir, listed, when=" during verification")
    if digest_after != snapshot.get("prepared_digest"):
        _fail("packet evidence changed during verification")

    if fingerprint != snapshot.get("worktree_fingerprint"):
        _fail(f"round {label!r} is INVALID — worktree mutation detected "
              f"(fingerprint mismatch)")

    print(f"ROUND_INTEGRITY_OK {label}")


def main(argv: list) -> None:
    if len(argv) == 3 and argv[0] == "open":
        cmd_open(argv[1], argv[2])
    elif len(argv) == 2 and argv[0] == "touch":
        cmd_touch(argv[1])
    elif len(argv) == 2 and argv[0] == "close":
        cmd_close(argv[1])
    elif len(argv) == 4 and argv[0] == "capture":
        cmd_capture(argv[1], argv[2], argv[3])
    elif len(argv) == 4 and argv[0] == "verify":
        cmd_verify(argv[1], argv[2], argv[3])
    else:
        _fail("usage: review_scratch.py open <abs-root> <slug> | "
              "touch <abs-dir> | close <abs-dir> | "
              "capture <abs-packet-dir> <abs-worktree-root> <label> | "
              "verify <abs-packet-dir> <abs-worktree-root> <label>")


if __name__ == "__main__":
    main(sys.argv[1:])
