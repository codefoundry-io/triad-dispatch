#!/usr/bin/env python3
"""Deletion by code: the declared deletion roots and the one deletion command.

Only host code deletes, and only inside a root declared in one JSON
configuration file (shape: the shared contract `cleanup-roots.schema.json`).
An AI at most chooses a declared role and a folder, then runs:

    python3 <this directory>/cleanup.py remove <role> <path>

`remove` runs every check before any action, and a check that cannot be made
(an unreadable entry, a configuration file that is no regular file, a
repository that cannot list its worktrees or name its top level, any
unexpected error) refuses; git runs with no inherited GIT_* variable and never discovers a
repository above the folder holding the `.git` entry meant (a path holding
':', which no GIT_CEILING_DIRECTORIES value can carry, refuses):
a `..` component, a symbolic link as the path or in any component below the
base its root resolves against (the project directory, or the `$TMPDIR` /
`~` / `$HOST_DIR` directory; links above it, such as macOS `/var`, pass), a
link in any component of the declared root below that base (the root's own
components included, also when the path is given by its real spelling), then
containment — the path inside the role's declared root,
never the root itself, also for a path that no longer exists — then the
role's ownership proof, the role's `min_age_s` and a writable parent. An
action touches only the one thing named, inside its declared root:
  marker:<name>   a folder holding <name> as a regular file directly in it (age:
                  the marker's own mtime): each linked worktree inside is
                  detached through the repository that owns it, deepest first;
                  then the folder is emptied, the marker goes last, then rmdir.
                  An EMPTY folder of a marker role, not inside a folder that
                  carries ANY declared role's marker (roots may be shared), not
                  under a root shared with other programs (one beginning with
                  `$TMPDIR` or `~`) and past the floor (its own mtime), is
                  removed with rmdir — the only empty-folder removal.
  git-registered  a registered linked worktree (never the main worktree; age:
                  its registration directory's): refused while `git status`
                  shows an uncommitted or untracked change (git's own guard;
                  a deleted tracked file and an ignored entry are not one);
                  worktrees inside detached
                  first, then the worktree is emptied with its `.git` file kept
                  and removed with `git worktree remove --force` — git drops a
                  registration even when its own removal fails, so it is left
                  nothing to fail on.
  alloc-record, inside-owned-packet
                  proved only inside the role's own coded sweep: refused, and
                  so is every empty folder of such a role.
Emptying a folder never follows a link: a symbolic link inside it (to a file,
to a folder, inside or outside the folder) is removed as a link — unlinked,
never followed, never rmdir'd. It runs in two passes: first everything but the
ignore files (at any depth, any name that case-folds to `.gitignore` — git
reads `.GITIGNORE` on a case-insensitive volume, so this holds on every
platform), then the ignore files, the deepest first and, in one folder, the
exact `.gitignore` after its case variants (on a case-sensitive volume a
variant is an ordinary file the real one may ignore), then the emptied folders
— so a stop at any point never shows a file they ignore as new work, and the
same command completes the removal later.
A name that case-folds to `.git` is git's entry (git takes a `.GIT` folder as a
repository's git dir on a case-insensitive volume): the named folder's own proof
(the one git opens as `<folder>/.git`) is kept to the end whatever its case, and
ANY OTHER such entry anywhere below refuses the folder on either volume kind —
never skipped, never emptied (`_git_named`, shared by discovery, emptying and the
export wipe). A `.git` entry inside the folder that is neither a detachable linked worktree
nor one of git's own failed-remove states (a clone, a link, a FIFO, a `.git`
file beside other content), or a path the root's repository registers inside
it that no `.git` entry names and that still holds something (a lost `.git`
file), refuses the folder; so does a worktree git has LOCKED (`git worktree
lock`), at any depth — the target itself, a nested one, or a registered path
that is missing or empty: unlocking it is the operator's own act. git's
failed-remove states — the only exemptions — are completed: a folder holding
only a `.git` file that points into `<common>/worktrees/<id>` and whose registration is gone or no longer valid (no
HEAD, gitdir or commondir; age: the registration directory's while any of it
survives, else the `.git` file's mtime) is removed — any other gitfile (a
submodule, a separate git directory) refuses — and a registered path that is missing or empty (age: its
registration's; as the path named, for a git-registered role only) loses its
ONE registration through `git worktree remove --force` — never a
repository-wide prune. So a removal stopped or failed at any step is completed
by the same command later — except a stop between the `.git` unlink and the
rmdir of an unregistered leftover named directly, which leaves an empty folder
this command refuses (no empty-folder removal for a git-registered role).

A root is one folder and covers its whole subtree (never a glob, never `..`,
never a NUL, never an absolute remainder after `$TMPDIR` / `~` / `$HOST_DIR`).

Exit codes: 0 removed, or nothing at the path (a second removal is a no-op);
64 refused, a host fault — a usage error, a missing, invalid or unprobeable
configuration, an undeclared role, a `..` or a symbolic link, a path outside
the root, an unproven owner, an entry younger than the floor, a parent that
is not writable, a `.git` entry that cannot be detached, a lost `.git` file or
a check that could not be made — with ONE stderr line naming what was observed
and nothing deleted; 1 an action that failed (a git step's exit code is always
checked), with ONE stderr line naming the step and nothing further deleted
(its proof is kept, so the same command completes it later).
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_EXIT_REFUSED = 64
_PROJECT_REL = (".claude", "triad-cleanup.json")
_HOST_DIR = Path(__file__).resolve().parent
_DEFAULT = _HOST_DIR / "cleanup-roots.default.json"
_KEYS = {"role", "root", "proof", "min_age_s"}
_ROLE_RE = re.compile(r"[a-z][a-z0-9-]*")
_PROOF_RE = re.compile(r"marker:[^/\s\x00]+|alloc-record|inside-owned-packet|git-registered")


def _project_root(folder: Path | None = None) -> Path:
    """The git top-level of `folder` (default: the working directory); the
    folder itself when no folder at or above it holds a `.git` entry. A
    repository that cannot name its top level raises ValueError — never a
    fallback to the folder."""
    cwd = Path(os.path.abspath(folder)) if folder is not None else Path.cwd()
    holder = _git_holder(str(cwd))
    if holder is None:
        return cwd
    r = _git(holder if not os.path.isdir(cwd) else str(cwd), "rev-parse", "--show-toplevel", ceiling=holder)
    top = os.fsdecode(r.stdout).strip()
    if r.returncode != 0 or not top:
        raise ValueError(f"the repository holding {cwd} cannot name its top level ({_said(r)})")
    return Path(top)


def _validate(path: Path, project: Path) -> dict[str, tuple[str, str, int, str]]:
    """The schema's rules, checked here (no runtime dependency): role -> (root
    as an absolute lexical path, proof, min_age_s, the base the root was
    resolved against). Raises ValueError."""
    def bad(why: str):
        raise ValueError(f"invalid cleanup configuration {path}: {why}")
    if not stat.S_ISREG(os.lstat(path).st_mode):  # never opened otherwise (a FIFO would block)
        bad("the file is not a regular file (a symbolic link, a FIFO or a directory)")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        bad(f"unreadable JSON ({exc})")
    if not isinstance(doc, dict) or set(doc) != {"version", "roots"}:
        bad("the top level must hold exactly version and roots")
    if isinstance(doc["version"], bool) or doc["version"] != 1:
        bad(f"version must be 1, not {doc['version']!r}")
    if not isinstance(doc["roots"], list) or not doc["roots"]:
        bad("roots must be a non-empty array")
    out: dict[str, tuple[str, str, int, str]] = {}
    for i, e in enumerate(doc["roots"]):
        if not isinstance(e, dict) or set(e) != _KEYS:
            bad(f"roots[{i}] must hold exactly role, root, proof and min_age_s")
        role, root, proof, age = e["role"], e["root"], e["proof"], e["min_age_s"]
        if not isinstance(role, str) or not _ROLE_RE.fullmatch(role):
            bad(f"roots[{i}].role {role!r} is not a lower-case role name")
        if role in out:
            bad(f"role {role!r} is declared twice")
        if not isinstance(proof, str) or not _PROOF_RE.fullmatch(proof):
            bad(f"roots[{i}].proof {proof!r} is not one of marker:<name>, alloc-record, "
                f"inside-owned-packet, git-registered")
        if (isinstance(age, bool) or not isinstance(age, (int, float))
                or (isinstance(age, float) and not age.is_integer()) or age < 0):
            bad(f"roots[{i}].min_age_s {age!r} is not a non-negative integer")
        if not isinstance(root, str) or not root:
            bad(f"roots[{i}].root must be a non-empty string")
        if ".." in root.split("/") or "\0" in root:
            bad(f"roots[{i}].root {root!r} has a '..' component or a NUL")
        head, _, rest = root.partition("/")
        if head in ("$TMPDIR", "~", "$HOST_DIR") and rest.startswith("/"):
            bad(f"roots[{i}].root {root!r} leaves its base (the remainder after {head} is absolute)")
        try:
            if head == "$TMPDIR":
                base = tempfile.gettempdir()
            elif head == "~":
                base = str(Path.home())
            elif head == "$HOST_DIR":
                base = str(_HOST_DIR)
            elif os.path.isabs(root) or head.startswith(("$", "~")):
                bad(f"roots[{i}].root {root!r} is neither repository-relative nor under "
                    f"$TMPDIR, ~ or $HOST_DIR")
            else:
                base, rest = str(project), root
        except (OSError, RuntimeError) as exc:
            bad(f"roots[{i}].root {root!r}: its base cannot be resolved ({exc})")
        out[role] = (os.path.normpath(os.path.join(base, rest)), proof, int(age), base)
    return out


def load_roots(project: Path | None = None) -> tuple[Path, dict[str, tuple[str, str, int, str]]]:
    """Find, read and validate the declared deletion roots.

    Lookup, first file present wins: the project file
    `<project>/.claude/triad-cleanup.json`, then the shipped default
    `cleanup-roots.default.json` beside this module. A file that is present but invalid (or a symbolic
    link), or one that cannot be probed (only "does not exist" is absent),
    raises — it never falls through to a later file — and no file at all
    raises too: either way nothing may be deleted.

    `<project>` is the git top-level of the folder `project` names (the folder
    itself outside a repository); the current working directory when it is
    None. A repository-relative root is
    resolved against that same project directory, whichever file declared it; a
    root beginning with `$TMPDIR` is resolved against the system temporary
    directory, one beginning with `~` against the home directory, and one
    beginning with `$HOST_DIR` against the directory holding this module (the
    host's own deletion command: the wrappers directory in the source tree, the
    plugin's `bin/` when exported). A root is one folder covering its subtree;
    a root with a `..` component is invalid.

    Returns (the file read, {role: (absolute root, proof, min_age_s, base)}) —
    base = the project directory, the temporary directory, the home directory
    or this module's directory, whichever the root was resolved against; raises
    ValueError with a one-line reason — also when the lookup itself fails (a
    removed working directory, git missing, an unsearchable folder)."""
    try:
        project = _project_root(project)
        looked: list[Path] = []
        for cand in (project.joinpath(*_PROJECT_REL), _DEFAULT):
            looked.append(cand)
            if _present(cand):
                return cand, _validate(cand, project)
    except OSError as exc:
        raise ValueError(f"the cleanup configuration cannot be looked up ({exc})") from None
    looked = ", ".join(str(c) for c in looked)
    raise ValueError(f"no cleanup configuration file (looked at {looked})")


def _present(cand: Path) -> bool:
    """Only "does not exist" is absent; a candidate that cannot be probed raises."""
    try:
        os.lstat(cand)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as exc:
        raise ValueError(f"cleanup configuration {cand} cannot be probed ({exc})") from None
    return True


def _refuse(msg: str) -> int:
    print(f"cleanup: refused — {' '.join(msg.split())}; nothing deleted", file=sys.stderr)
    return _EXIT_REFUSED


class _Refused(ValueError):
    """A check failed, or could not be made: exit 64, nothing deleted."""


def _lstat(p: str) -> os.stat_result | None:
    """None when nothing is at `p`; any other error raises (a check that cannot be made)."""
    try:
        return os.lstat(p)
    except (FileNotFoundError, NotADirectoryError):
        return None


def _git_named(d: str, name: str, names: list[str] | None = None) -> str | None:
    """Git's entry in `d` (R-CLEANUP): None for a name that does not case-fold to
    `.git`; "own" for the one git opens as `d/.git` — the folder's proof, kept to
    the end whatever its case (a case-insensitive volume hands a `.GIT` over);
    "other" for any other such name, refused wherever it sits (never skipped,
    never emptied) — and for every such name once the listing holds two (a hand
    hard link `.GIT` -> `.git` on a case-sensitive volume shares the inode: only
    a case-insensitive volume, where one name exists, hands a case variant over).
    `names` is the caller's listing of `d` (else it is read). The one test
    discovery, emptying and the export wipe share."""
    if name.casefold() != ".git":
        return None
    own, st = _lstat(os.path.join(d, ".git")), _lstat(os.path.join(d, name))
    same = own is not None and st is not None and (own.st_dev, own.st_ino) == (st.st_dev, st.st_ino)
    if same and any(n != name and n.casefold() == ".git"
                    for n in (os.listdir(d) if names is None else names)):
        return "other"
    return "own" if same else "other"


def _git(cwd: str, *args: str, ceiling: str | None = None) -> subprocess.CompletedProcess:
    """git in `cwd` only (no inherited GIT_* redirection), C-locale messages; with
    `ceiling` (the folder holding the `.git` entry meant) git may not discover a
    repository above that folder."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = _ceiling(ceiling)
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, env={**env, "LC_ALL": "C"})


def _ceiling(holder: str) -> str:
    """The GIT_CEILING_DIRECTORIES value confining git to the repository whose
    `.git` entry `holder` holds; refuses a path holding ':' (git's list separator:
    no ceiling could hold). Checked for every repository before any action."""
    value = os.path.dirname(os.path.realpath(holder))
    if ":" in value:
        raise _Refused(f"git cannot be confined to the repository at {holder}: the path {value} holds ':'")
    return value


def _stdout_gone() -> None:
    """After a stdout error: point fd 1 at os.devnull, so the exit-time flush of
    the pending buffer cannot fail (the documented SIGPIPE pattern)."""
    try:
        fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(fd, 1)
        os.close(fd)
    except OSError:
        pass


def _git_holder(start: str) -> str | None:
    """The nearest existing folder at or above `start` holding a `.git` entry."""
    here = start
    while _lstat(here) is None:
        here = os.path.dirname(here)
    while _lstat(os.path.join(here, ".git")) is None:
        if os.path.dirname(here) == here:
            return None
        here = os.path.dirname(here)
    return here


def _said(r: subprocess.CompletedProcess) -> str:
    return " ".join(os.fsdecode(r.stderr).split()) or f"exit {r.returncode}"


def _worktrees(cwd: str) -> tuple[str, set[str]]:
    """(main worktree, {registered linked worktree real paths}) of the repository
    whose `.git` entry `cwd` holds (never one git finds above it), from
    `git worktree list --porcelain -z` (a path may hold a newline); refuses when
    git cannot list them."""
    r = _git(cwd, "worktree", "list", "--porcelain", "-z", ceiling=cwd)
    if r.returncode != 0:
        raise _Refused(f"the repository at {cwd} cannot list its worktrees ({_said(r)})")
    paths = [os.path.realpath(f[len("worktree "):]) for f in os.fsdecode(r.stdout).split("\0")
             if f.startswith("worktree ")]
    return paths[0], set(paths[1:])


def _root_repo(root_real: str) -> tuple[str | None, set[str]]:
    """(where git runs for the root's repository, its registered linked worktrees);
    (None, empty) when no folder at or above the root holds a `.git` entry."""
    holder = _git_holder(root_real)
    return (None, set()) if holder is None else (holder, _worktrees(holder)[1])


def _gitfile(d: str) -> str | None:
    """None when `d` holds no `.git`; the registration directory a regular `.git`
    FILE names; refuses any other `.git` entry (a directory, a link, a FIFO), never
    opening it, and a `.git` file that names no registration."""
    p = os.path.join(d, ".git")
    st = _lstat(p)
    if st is None:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise _Refused(f"{p} cannot be detached: it is no .git file of a linked worktree "
                       f"(a clone, a link or a special file)")
    with open(p, "rb") as f:
        line = os.fsdecode(f.read(4096).split(b"\n")[0]).strip()
    if not line.startswith("gitdir: "):
        raise _Refused(f"{p} cannot be detached: it names no registration")
    return os.path.normpath(os.path.join(d, line[len("gitdir: "):]))


def _among(path: str, paths: set[str]) -> bool:
    """`path` is one of `paths` — by spelling, or by identity (device + inode)
    when both exist: realpath keeps a case-variant spelling on a
    case-insensitive filesystem, while git reports the true one."""
    if path in paths:
        return True
    try:
        st = os.stat(path)
    except OSError:
        return False
    for q in paths:
        try:
            if os.path.samestat(st, os.stat(q)):
                return True
        except OSError:
            continue
    return False


def _valid(reg: str) -> bool:
    """A registration git can still use: HEAD, gitdir and commondir in it."""
    return all((st := _lstat(os.path.join(reg, n))) is not None and stat.S_ISREG(st.st_mode)
               for n in ("HEAD", "gitdir", "commondir"))


def _worktree_steps(d: str, repo: str | None, regs: set[str]) -> list[tuple]:
    """The steps for a folder `d` holding a `.git` file: detach a registered linked
    worktree through its owner; complete git's failed-remove state (only the
    `.git` file left, its registration gone or no longer valid) — the root's
    repository's ONE registration of `d`, if listed, removed after the folder;
    refuse anything else."""
    reg = _gitfile(d)
    if reg is None:
        raise _Refused(f"{d} holds no .git file")
    _unlocked(reg, d)
    if _valid(reg):
        owner, linked = _worktrees(d)
        if not _among(d, linked):
            raise _Refused(f"{d} is not a registered linked worktree of the repository its .git file names")
        _ceiling(owner)  # the owner's git is confined too: checked before any action
        return [("detach", owner, d)]
    if os.path.basename(os.path.dirname(reg)) != "worktrees":
        raise _Refused(f"{d} cannot be detached: its .git file names {reg}, which is no worktree "
                       f"registration (a submodule or a separate git directory)")
    if [n for n in os.listdir(d) if _git_named(d, n) != "own"]:  # only the gitfile, whatever its case
        raise _Refused(f"{d} cannot be detached: its .git file's registration is gone or no longer "
                       f"valid, and other content sits beside it")
    return [("residue", d)] + ([("unregister", repo, d)] if _among(d, regs) else [])


def _plan(real: str, self_wt: bool, repo: str | None, regs: set[str]) -> list[tuple]:
    """Every step inside `real` before its own removal, deepest first: each `.git`
    entry inside (the target's own excluded when it is the worktree) through
    `_worktree_steps`; each path the root's repository registers inside that no
    `.git` entry names — missing: its ONE registration removed; empty: removed,
    then its registration; holding something (a lost `.git` file): refused."""
    def stop(exc: OSError):
        raise exc
    steps: dict[str, list[tuple]] = {}
    for dirpath, dirnames, filenames in os.walk(real, onerror=stop):
        kinds = {n: k for n in dirnames + filenames if (k := _git_named(dirpath, n, dirnames + filenames))}
        if other := sorted(n for n, k in kinds.items() if k == "other"):
            raise _Refused(f"{os.path.join(dirpath, other[0])} spells .git in another case beside "
                           f"git's own entry (or where git opens none)")
        if kinds and not (self_wt and dirpath == real):
            if dirpath == real:
                raise _Refused(f"{real} holds a .git entry of its own")
            steps[dirpath] = _worktree_steps(dirpath, repo, regs)
        dirnames[:] = [n for n in dirnames if n not in kinds]
    for wt in sorted(regs):
        if wt in steps or not _inside(wt, real, not self_wt):
            continue
        st = _lstat(wt)
        _unlocked(_regdir(repo, wt), wt)
        if st is None:
            steps[wt] = [("unregister", repo, wt)]
        elif stat.S_ISDIR(st.st_mode) and not os.listdir(wt):
            steps[wt] = [("rmdir", wt), ("unregister", repo, wt)]
        else:
            raise _Refused(f"the repository at {repo} registers {wt} inside the folder, "
                           f"but no .git entry there names it (a lost .git file)")
    return [s for p in sorted(steps, key=lambda p: p.count(os.sep), reverse=True) for s in steps[p]]


def _regdir(repo: str, path: str) -> str:
    """The registration directory the root's repository keeps for `path`."""
    r = _git(repo, "rev-parse", "--git-common-dir", ceiling=repo)
    if r.returncode != 0:
        raise _Refused(f"the repository at {repo} cannot name its git directory ({_said(r)})")
    common = os.path.join(repo, os.fsdecode(r.stdout).strip())
    for wid in sorted(os.listdir(os.path.join(common, "worktrees"))):
        reg = os.path.join(common, "worktrees", wid)
        if _lstat(os.path.join(reg, "gitdir")) is None:
            continue
        with open(os.path.join(reg, "gitdir"), encoding="utf-8", errors="surrogateescape") as f:
            named = os.path.normpath(os.path.join(reg, f.read().strip()))
        if os.path.realpath(os.path.dirname(named)) == path:
            return reg
    raise _Refused(f"the registration of {path} cannot be found, so its age cannot be read")


def _git_entry_below(d: str | Path, own: bool = True) -> str | None:
    """The first `.git` entry (any case) anywhere below the folder `d` (links never
    followed; `own=False` leaves out only `d`'s own git entry, whatever its case —
    any other one at the top is returned), or None.
    Raises OSError when a folder below cannot be listed — a check that cannot
    be made. The one walk every host deletion that refuses around a `.git`
    entry shares (R-CLEANUP), run before its first deletion."""
    def stop(exc: OSError):
        raise exc
    top = os.fspath(d)
    for dirpath, dirnames, filenames in os.walk(top, onerror=stop):
        names = dirnames + filenames
        if not own and dirpath == top:  # only `d`'s own proof is left out, whatever its case
            dirnames[:] = [n for n in dirnames if _git_named(dirpath, n, names) != "own"]
            filenames = [n for n in filenames if _git_named(dirpath, n, names) != "own"]
        if hit := next((n for n in dirnames + filenames if _git_named(dirpath, n, names)), None):
            return os.path.join(dirpath, hit)
    return None


def _inside(real: str, root_real: str, or_equal: bool) -> bool:
    if real == root_real:
        return or_equal
    return os.path.commonpath([real, root_real]) == root_real


def _link_below(target: str, base: str) -> str | None:
    """The last symbolic link in any component of `target` (itself included)
    below the folder it resolves to as `base`; None when there is none. Links
    above the base (macOS `/var`) pass; with no component resolving to the
    base, a link that resolves inside the base counts. Shared with the hosts'
    own sweeps (R-CLEANUP: a link is refused in every component below the
    base)."""
    target, base_real = os.path.abspath(target), os.path.realpath(base)
    prefixes = [target]
    while os.path.dirname(prefixes[-1]) != prefixes[-1]:
        prefixes.append(os.path.dirname(prefixes[-1]))
    prefixes.reverse()  # shortest first; the first one resolving to the base is the base
    at = next((i for i, q in enumerate(prefixes) if os.path.realpath(q) == base_real), None)
    links = [q for q in prefixes[(at or 0) + 1:] if os.path.islink(q)]
    bad = links if at is not None else [q for q in links if _inside(os.path.realpath(q), base_real, True)]
    return bad[-1] if bad else None


def _lock_reason(reg: str) -> str | None:
    """None when the registration `reg` carries no `locked` file; else the
    lock's reason as one line (git's own "initializing" from a stopped `git
    worktree add` included), "no reason given" for an empty one, or why it
    cannot be read — never empty."""
    p = os.path.join(reg, "locked")
    try:
        with open(p, "rb") as f:
            said = " ".join(f.read(512).decode("utf-8", "replace").split())
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        return f"its reason cannot be read ({exc})"
    return f'reason: "{said}"' if said else "no reason given"


def _unlocked(reg: str, wt: str) -> str:
    """`reg`, the registration of the worktree `wt`, when git has not LOCKED it
    (`git worktree lock`: a `locked` file in it); refuses a locked one — at any
    depth, for every caller, printing the lock's reason: unlocking is the
    operator's own act (R-CLEANUP)."""
    if (why := _lock_reason(reg)) is not None:
        raise _Refused(f"{wt} is a worktree git has locked (`git worktree lock`; {why}) — unlocking it is the "
                       f"operator's own act")
    return reg


def _locked(wt: str) -> str | None:
    """Why `wt` counts as a linked worktree git has LOCKED (`git worktree lock`:
    a `locked` file in the registration its `.git` file names) — the lock's
    reason (`_lock_reason`) — or None. Every deletion leaves it (R-CLEANUP;
    this command refuses one at any depth in its check phase): the review
    helpers' own checks name it first, with this reason. None when `wt` holds
    no `.git` entry; a `.git` that cannot be read (a directory included) or
    names no registration is left like a lock (never delete on doubt), its reason
    saying the lock state cannot be read — it is no git lock."""
    p = os.path.join(wt, ".git")
    try:
        with open(p, "rb") as f:
            line = os.fsdecode(f.read(4096).split(b"\n")[0]).strip()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        return f"its lock state cannot be read: its .git cannot be read ({exc})"
    if not line.startswith("gitdir: "):
        return "its lock state cannot be read: its .git names no registration"
    return _lock_reason(os.path.join(wt, line[len("gitdir: "):]))


def _check(path: str, role: str, markers: set[str], root: str, proof: str, min_age: int,
           base: str) -> tuple[str, list[tuple]]:
    """Every check, before any action: (the resolved target, its steps); raises
    _Refused (or OSError: a check that could not be made). `markers` = every
    declared role's marker name (an empty folder inside any of them is live)."""
    if ".." in Path(path).parts:
        raise _Refused(f"{path} has a '..' component — give the folder's own path")
    target, root_real = os.path.abspath(path), os.path.realpath(root)
    st = _lstat(target)
    if st is not None and stat.S_ISLNK(st.st_mode):
        raise _Refused(f"{target} is a symbolic link — give the folder's own path")
    if (link := _link_below(target, base)) is not None:
        raise _Refused(f"{target} goes through the symbolic link {link} — give the folder's own path")
    if (link := _link_below(root, base)) is not None:  # the root's own components included
        raise _Refused(f"the declared root {root} of role {role!r} goes through the symbolic link {link}")
    real = os.path.realpath(target)
    if not _inside(real, root_real, False):
        raise _Refused(f"{real} is outside the declared root {root_real} of role {role!r} "
                       f"(the root itself is never removed)")
    kind, _, name = proof.partition(":")
    if kind not in ("marker", "git-registered"):
        raise _Refused(f"the proof {proof} of role {role!r} is checked only by that role's coded "
                       f"sweep — this command cannot prove {real} was allocated")
    repo, regs = _root_repo(root_real)
    if st is None:  # nothing here; git's failed-remove state: a missing registered path
        if kind != "git-registered" or real not in regs:
            return real, []
        born, steps = os.lstat(_unlocked(_regdir(repo, real), real)).st_mtime, [("unregister", repo, real)]
    elif not stat.S_ISDIR(st.st_mode):
        raise _Refused(f"{real} is not a folder")
    elif kind == "marker":
        mst = _lstat(os.path.join(real, name))
        if mst is not None and stat.S_ISREG(mst.st_mode):
            born = mst.st_mtime  # the proof's own age, never the folder being emptied
            steps = _plan(real, False, repo, regs) + [("marker", real, name)]
        elif not os.listdir(real):  # an empty leftover: nothing to lose
            if os.path.realpath(base) in {os.path.realpath(tempfile.gettempdir()), os.path.realpath(Path.home())}:
                raise _Refused(f"{real} is an empty folder in a shared root ($TMPDIR or ~) — "
                               f"not removed (proof {proof})")
            up = real
            while up != root_real:
                up = os.path.dirname(up)
                for mk in sorted(markers):  # ANY declared role's marker: roots may be shared
                    if (m := _lstat(os.path.join(up, mk))) is not None and stat.S_ISREG(m.st_mode):
                        raise _Refused(f"{real} is an empty folder inside {up}, which carries {mk} (a live folder)")
            if _among(real, regs):
                raise _Refused(f"{real} is an empty folder the repository at {repo} registers")
            born, steps = st.st_mtime, [("rmdir", real)]
        else:
            raise _Refused(f"{real} carries no {name} regular file — its owner is not proven (proof {proof})")
    elif _lstat(os.path.join(real, ".git")) is not None:
        steps = _worktree_steps(real, repo, regs)
        reg = _gitfile(real)
        # the registration's age while any of it survives; the .git file's once it is gone
        born = os.lstat(reg if _lstat(reg) is not None else os.path.join(real, ".git")).st_mtime
        if steps[0][0] == "detach":
            # git's own guard for the NAMED worktree (spec 62b154a): uncommitted or
            # untracked work refuses; a deleted tracked file loses nothing (what a
            # stopped removal leaves), and an ignored entry is not a change
            r = _git(real, "--no-optional-locks", "status", "--porcelain", "--untracked-files=all",
                     ceiling=real)  # every untracked file, whatever status.showUntrackedFiles says
            if r.returncode != 0:
                raise _Refused(f"{real} cannot be checked for uncommitted work ({_said(r)})")
            changed = [ln for ln in os.fsdecode(r.stdout).splitlines() if ln[:2].strip(" D")]
            n = len(changed)
            git_named = [ln[3:].strip('"') for ln in changed
                         if any(c.casefold() == ".git" for c in ln[3:].strip('"').split("/"))]
            if git_named:  # git refuses any path component spelled .git in any case
                raise _Refused(f"{real} holds {n} uncommitted or untracked change(s) (`git status`), "
                               f"among them {git_named[0]}, a path spelled .git in another case — git can "
                               f"never commit such an entry; resolving it is the operator's act")
            if n:
                raise _Refused(f"{real} holds {n} uncommitted or untracked change(s) (`git status`) — "
                               f"committing them to the worktree's own branch keeps them and is the "
                               f"leader's step (then run this again); discarding them is the operator's act")
            steps = _plan(real, True, repo, regs) + steps
    elif not os.listdir(real) and _among(real, regs):  # git's failed-remove state: an empty registered path
        born, steps = os.lstat(_unlocked(_regdir(repo, real), real)).st_mtime, [("rmdir", real), ("unregister", repo, real)]
    else:
        raise _Refused(f"{real} is not a registered linked worktree (proof {proof})")
    age = time.time() - born
    if age < min_age:
        raise _Refused(f"{real} is younger than the floor of role {role!r} "
                       f"({int(age)} s old, min_age_s {min_age})")
    if st is not None and not os.access(os.path.dirname(real), os.W_OK | os.X_OK):
        raise _Refused(f"the parent folder of {real} is not writable, so it could not be removed")
    return real, steps


def _empty(d: str, keep: str) -> None:
    """Remove every entry of `d` except `keep` (the proof stays until last), in two
    passes: first everything but the ignore files (at any depth, any name that
    case-folds to `.gitignore`: git reads `.GITIGNORE` on a case-insensitive volume) and
    the folders holding them, then those, the DEEPEST first and, in one folder, the
    exact `.gitignore` after its case variants (a rule governs only its own folder
    and below, so each removal exposes nothing), then the emptied
    folders (an ignore file that is a symbolic link, even to a folder, is
    unlinked, never rmdir'd). A stop in the first pass leaves every ignore rule
    in place, so the files they cover never read as new work on the re-run; a
    stop in the second leaves only deleted ignore files no remaining rule hides."""
    def kept(n: str) -> bool:  # the proof, whatever its case when it is git's own entry
        return _git_named(d, n) == "own" if keep == ".git" else n == keep

    def strip(p: str, top: bool) -> None:
        with os.scandir(p) as it:
            entries = [e for e in it if not (top and kept(e.name))]
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                strip(e.path, False)
                if not os.listdir(e.path):
                    os.rmdir(e.path)
            elif e.name.casefold() != ".gitignore":  # a case-insensitive volume reads `.GITIGNORE`
                os.unlink(e.path)
    strip(d, True)
    files, dirs = [], []
    for dirpath, dirnames, filenames in os.walk(d):
        if dirpath == d:
            dirnames[:] = [n for n in dirnames if not kept(n)]
            filenames = [n for n in filenames if not kept(n)]
        links = [n for n in dirnames if os.path.islink(os.path.join(dirpath, n))]
        files += [os.path.join(dirpath, n) for n in filenames + links]  # a link is unlinked
        dirs += [os.path.join(dirpath, n) for n in dirnames if n not in links]
    # only ignore files are left: the deepest first, and in one folder the exact
    # `.gitignore` after its case variants (a variant may be a file it ignores)
    for path in sorted(files, key=lambda p: (p.count(os.sep), os.path.basename(p) != ".gitignore"),
                       reverse=True):
        os.unlink(path)
    for path in sorted(dirs, key=lambda p: p.count(os.sep), reverse=True):
        os.rmdir(path)


def _git_remove(repo: str, wt: str) -> None:
    """Remove the ONE worktree `wt` of the repository at `repo` (its registration;
    its tree too, when one is left) — never a repository-wide prune."""
    r = _git(repo, "worktree", "remove", "--force", wt, ceiling=repo)  # never twice: a lock is refused before
    if r.returncode != 0:
        raise OSError(f"git worktree remove --force {wt} in {repo}: {_said(r)}")


def _act(step: tuple) -> None:
    kind, *a = step
    if kind == "detach":  # emptied first, .git kept: git drops a registration even when its removal fails
        owner, wt = a
        _empty(wt, ".git")
        _git_remove(owner, wt)
        if _lstat(wt) is not None:
            raise OSError(f"git worktree remove left {wt} in place")
    elif kind == "unregister":
        _git_remove(*a)
    elif kind == "residue":
        os.unlink(os.path.join(a[0], ".git"))
        os.rmdir(a[0])
    elif kind == "rmdir":
        os.rmdir(a[0])
    else:  # "marker": the proof last, so a stopped removal resumes
        _empty(*a)
        os.unlink(os.path.join(*a))
        os.rmdir(a[0])


def remove(role: str, path: str, *, project: Path | str | None = None,
           apply_floor: bool = True, check_only: bool = False) -> int:
    """The one deletion command (see the module docstring); returns the exit code.

    In-process callers only: `project` names a folder whose project's
    configuration is read (as `load_roots`), and `apply_floor=False` is the
    owning helper's explicit close of a folder it has already identified by its
    own stronger check — every check runs except the age floor;
    `check_only=True` runs the whole check phase and returns its verdict (0 or
    the refusal) without acting, so a caller can finish its own read-only
    checks before the first action. The command line reaches none of them."""
    try:
        cfg, roots = load_roots(project)
    except (ValueError, _Refused) as exc:
        return _refuse(str(exc))
    except Exception as exc:  # noqa: BLE001 — any error before an action refuses
        return _refuse(f"the cleanup configuration could not be read ({type(exc).__name__}: {exc})")
    if role not in roots:
        return _refuse(f"role {role!r} is not declared in {cfg} (declared: {', '.join(sorted(roots))})")
    try:
        markers = {p.partition(":")[2] for _r, p, _a, _b in roots.values() if p.startswith("marker:")}
        root, proof, floor, base = roots[role]
        real, steps = _check(path, role, markers, root, proof, floor if apply_floor else 0, base)
    except _Refused as exc:
        return _refuse(str(exc))
    except Exception as exc:  # noqa: BLE001 — a check that cannot be made refuses
        return _refuse(f"a check on {path} could not be made ({type(exc).__name__}: {exc})")
    if check_only:
        return 0
    if not steps:  # no action taken: an unprintable result is still a no-op
        try:
            print(f"cleanup: nothing to remove at {real}", flush=True)
        except Exception:  # noqa: BLE001
            _stdout_gone()
        return 0
    for step in steps:
        try:
            _act(step)
        except Exception as exc:  # noqa: BLE001 — every failure reported, in ONE line
            line = f"cleanup: removing {real} failed at step {step[0]} {step[-1]}: {type(exc).__name__}: {exc}"
            print(" ".join(line.split()), file=sys.stderr)
            return 1
    try:  # the removal stands: printed escaped, a closed stdout ignored
        line = f"cleanup: removed {real} (role {role})\n"
        out = getattr(sys.stdout, "buffer", None)
        if out is not None:
            out.write(line.encode(sys.stdout.encoding or "utf-8", "backslashreplace"))
            out.flush()
        elif sys.stdout is not None:  # an in-process caller's text stream
            sys.stdout.write(line)
    except (BrokenPipeError, OSError, ValueError):
        _stdout_gone()
    return 0


_USAGE = "usage: cleanup.py remove <role> <path>"


def _main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        try:
            print(_USAGE, flush=True)
        except Exception:  # noqa: BLE001 — a closed stdout: the help had no reader
            _stdout_gone()
        return 0
    if len(argv) != 3 or argv[0] != "remove":
        return _refuse(f"{_USAGE} (got {len(argv)} argument(s): {' '.join(argv)!r})")
    return remove(argv[1], argv[2])


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
