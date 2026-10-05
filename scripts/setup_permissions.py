#!/usr/bin/env python3
"""Merge (and remove) the wrapper hardening + allowlist into a Claude Code settings.json.

A Claude Code plugin cannot grant Bash permissions or set persistent env, so the
few things the dispatch wrappers need must be written into your own
`settings.json`. This script does that one mechanical, idempotent step — and can
undo it (`--remove`) — WITHOUT clobbering your own settings: every entry it
writes is key-level JSON-merged and recorded in a provenance sidecar so `--remove`
deletes exactly what this installer authored and nothing else.

What an `--install` writes (excluded-command posture — the wrappers run OUTSIDE
the Bash sandbox so they can reach the vendor APIs with your auth):

  * `permissions.allow` — one `Bash(<wrapper>:*)` BASENAME grant per shipped
    wrapper (e.g. `Bash(codex_wrapper.py:*)`), matching the BARE invocation the
    dispatch SKILLs emit (`bin/` is on PATH) so dispatch stays PROMPTLESS. The
    grant is by the script's NAME: it runs a script of that name without asking.
    The plugin's environment assumes one operator and nothing planted on PATH;
    the wrappers themselves contain --prompt-file / --image / --cwd in the
    allowed roots and pin the vendor binary under the hardening env below.
  * `sandbox.excludedCommands` — the space-glob form (`codex_wrapper.py *`) that
    runs the wrappers outside the Bash sandbox if you enable it. Harmless when the
    sandbox is off; the same bare basename form as the allow grant, so both match
    the one bare invocation the dispatch SKILLs use.
  * `env` — the wrapper self-defense bundle, applied by Claude Code to every Bash
    subprocess it spawns (including excluded commands, which run as ordinary
    subprocesses outside the sandbox — docs.claude.com/en/settings "env" +
    /en/sandboxing "excludedCommands ... runs outside the sandbox"):
      TRIAD_WRAPPER_HARDENED=1        contain --prompt-file/--cwd/--image in roots
      TRIAD_REQUIRE_PINNED_VENDOR=1   refuse a PATH-planted vendor binary
      TRIAD_<CLI>_BIN=<abs>           the resolved vendor pin (codex/gemini/agy)
      TRIAD_WRAPPER_ALLOWED_ROOTS=…   the workspace root the wrappers may touch
      TRIAD_AUDIT_REDACT_PROMPTS=1    redact prompt text from the audit log

An `--install` writes no hook. It takes out the `hooks.PreToolUse` handlers an
earlier version of the plugin wrote and its record lists: such a handler is
pinned to that version's directory, and once the host deletes the directory
every shell command of the project fails.

Robustness: the settings file is read with O_NOFOLLOW (a symlinked settings path
is refused), the whole read-merge-write runs under an advisory `flock`, and the
new content is written atomically (temp + os.replace). A malformed settings list
(e.g. a dict where a string is expected) is a clean non-zero error, never a
traceback.

Usage:
    python3 setup_permissions.py [--install] [--target <path-or-dir>]
                                 [--bin-dir <dir>]
                                 [--allowed-roots <a:b:c>] [--dry-run]
    python3 setup_permissions.py --remove   [--target <path-or-dir>] [--dry-run]
    python3 setup_permissions.py --uninstall-machine [--dry-run]

    --install       Write the entries (the default mode). The record is written
                    before the settings file and completed after it, so a run
                    that stops between the writes is repaired by running
                    --install again; a run that changes only the record
                    writes the record alone. It takes out the hook entry an
                    earlier version wrote. An entry of the plugin's that is
                    in the settings file and in no record is yours: it is not
                    recorded, and --install and --remove both name it — the
                    grants, sandbox patterns and env keys (by name) in one note,
                    and a PreToolUse handler whose command contains the hook's
                    file name in a `left <target>: hook <command>` line.
    --target        Settings file, or a directory. A directory (or the default)
                    resolves to `<dir>/.claude/settings.json`; the default target
                    is `./.claude/settings.json`. The record of an install names
                    the one settings file it wrote: an --install into another
                    settings file of the same directory is refused (exit 1).
                    A record of an older version names no file: an --install
                    into a file that holds none of its entries is refused
                    (exit 1) — give the --target that install used. Such a
                    record is never removed while none of its entries is
                    found: entries taken out by hand cannot be told from
                    entries in another settings file of that directory. The
                    kept record is the operator's.
    --bin-dir       Directory holding the shipped wrapper scripts (default: the
                    plugin `bin/` sibling of this script's `scripts/` dir).
    --allowed-roots Colon-separated absolute paths for TRIAD_WRAPPER_ALLOWED_ROOTS
                    (default: the project root derived from --target).
    --remove        Delete exactly the entries a prior --install authored, this
                    script's two sidecar files, the empty containers the
                    install created, and the settings file the install
                    created when nothing else is left in it — also when the
                    entries were taken out by hand. It creates nothing. Give the
                    same --target as the --install: a --target that is not the
                    file the record names is refused (exit 1, the record kept).
                    A record of an older version names no file: when none of
                    its entries is in the target it is kept (exit 1) — give the
                    --target the install used (entries taken out by hand cannot
                    be told from entries in another file). A record whose entries are all
                    gone is stale and is removed; so is a record that lists
                    nothing, also when the settings file cannot be read (a
                    `left <target>: <reason>` line says it was not checked).
                    An entry of the plugin's in no record is left and named,
                    as with --install.
    --uninstall-machine
                    Once per machine, after --remove in every project: delete
                    the plugin's files outside any project (the classifier
                    patches, the two agy agent files, the agy settings lock and
                    transaction residue, the daily-check state); prints
                    `removed` / `left <path>: <reason>` per item — while an agy
                    settings transaction is recorded, every item of it is left
                    and named. Nothing in the
                    shared temp dir is removed: the codex temp entries there are
                    only listed. An item, or a plugin-named
                    directory, that is a symlink is left; a symlinked PARENT
                    (~/.config, ~/.gemini) is the user's layout — the wrappers
                    wrote through it, so this removes through it. A directory
                    that cannot be listed is reported and the run goes on.
    --dry-run       Print what would change, by name or by count, and write
                    nothing.

Exit status is 0 on success (including a no-op re-run/remove), non-zero on error.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import fnmatch
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

# The vendor CLIs whose wrappers this (claude-host) product ships. claude is the
# leader here, not a worker, so it is intentionally absent. Each name is the
# vendor binary the matching wrapper execs (antigravity_wrapper.py -> `agy`).
VENDOR_CLIS = ("codex", "gemini", "agy")

# The env key of a vendor pin: TRIAD_<CLI>_BIN.
_PIN_NAME = "TRIAD_{}_BIN"

# The shipped wrapper scripts that get a basename Bash grant.
WRAPPER_SCRIPTS = (
    "codex_wrapper.py",
    "gemini_wrapper.py",
    "antigravity_wrapper.py",
    "agy-daily-check.sh",
    "gemini-daily-check.sh",
)

# The same wrappers in the space-glob form `sandbox.excludedCommands` uses: the
# bare basename + " *". The dispatch SKILLs invoke the wrappers bare (bin/ is on
# PATH), and an excluded-command entry must match the actual invocation to run it
# outside the sandbox. This is the SAME bare-basename form as the permissions.allow
# grant above — both target the one bare invocation, no absolute/bare split.
SANDBOX_EXCLUDE_PATTERNS = tuple(f"{name} *" for name in WRAPPER_SCRIPTS)

# The file name of the PreToolUse hook earlier versions of the plugin wrote into
# the settings: a handler in no record whose command contains it is named.
HOOK_SCRIPT_NAME = "pretooluse_wrapper_guard.py"

PROVENANCE_NAME = ".triad-dispatch-managed.json"
LOCK_NAME = ".triad-dispatch.lock"
PROVENANCE_VERSION = 2

# --uninstall-machine: the two agy agent definitions `antigravity_wrapper.py
# --setup-agents` writes (its AGY_REVIEW_AGENT / AGY_RESEARCH_AGENT), duplicated
# so this script never imports the wrapper engine — a shipped test compares them.
AGY_AGENT_NAMES = ("triad-readonly-review", "triad-readonly-research")
# The known file set of the two daily-check scripts' state directories.
DAILY_STATE_FILES = ("report.md", "*.snapshot", "*.now", "changelog.raw", "deep.out")
# The exact names Python's `tempfile` gives the wrappers' calls in
# codex_wrapper.py (`mkstemp(prefix=f"codex_last_{pid}_", suffix=".txt")`,
# `mkstemp(prefix=f"codex_schema_{pid}_", suffix=".json")`): the prefix, 8
# random characters of [a-z0-9_], the suffix. A shipped test compares the
# prefixes with the wrapper.
_RAND8 = "[a-z0-9_]{8}"
TEMP_FILE_RE = re.compile(
    rf"codex_last_\d+_{_RAND8}\.txt|codex_schema_\d+_{_RAND8}\.json")
# This script's own atomic-write temp names (see write_atomic / _write_provenance).
STRAY_RE = re.compile(rf"(\.settings\.|\.triad-prov\.){_RAND8}\.json\.tmp")


class SettingsError(Exception):
    """A user-facing, clean error (no traceback) reported by main()."""


# ── target / root / bin resolution ───────────────────────────────────────────
def resolve_target(raw: str) -> Path:
    """Resolve --target to a settings.json file path.

    A path ending in `.json` is the settings file itself; anything else is a
    directory whose settings file is `<dir>/.claude/settings.json`.
    """
    path = Path(raw).expanduser()
    if path.suffix == ".json":
        return path
    return path / ".claude" / "settings.json"


def resolve_project_root(target: Path) -> Path:
    """Derive the workspace/project root from the settings path.

    `<root>/.claude/settings.json` -> `<root>`; any other settings file -> its
    parent directory. Resolved to an absolute path.
    """
    parent = target.parent
    if parent.name == ".claude":
        return parent.parent.resolve()
    return parent.resolve()


def resolve_allowed_roots(target: Path, explicit: str | None) -> str:
    """The value for TRIAD_WRAPPER_ALLOWED_ROOTS (colon-separated absolute paths).

    An explicit --allowed-roots wins (each entry must be absolute); otherwise the
    single project root derived from --target.
    """
    if explicit:
        roots = [Path(p).expanduser() for p in explicit.split(os.pathsep) if p]
        for r in roots:
            if not r.is_absolute():
                raise SettingsError(f"--allowed-roots entry is not absolute: {r}")
        return os.pathsep.join(str(r.resolve()) for r in roots)
    return str(resolve_project_root(target))


def resolve_bin_dir(explicit: str | None) -> Path:
    """Directory holding the shipped wrapper scripts.

    Default: the plugin `bin/` sibling of this script's `scripts/` dir
    (`<plugin>/scripts/setup_permissions.py` -> `<plugin>/bin`).
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "bin").resolve()


def wrapper_grant_entries(bin_dir: Path) -> list[str]:
    """One `Bash(<wrapper>:*)` BASENAME grant per shipped wrapper.

    The grant is the bare basename (`Bash(codex_wrapper.py:*)`), matching the bare
    invocation the dispatch SKILLs emit (`bin/` is on PATH) so dispatch stays
    PROMPTLESS. It runs a script of that name without asking; the wrappers
    contain their inputs under the hardening env. `bin_dir` must still exist so
    the grant is only written when the wrappers are actually shipped (a sanity
    guard, not the source of the grant string).
    """
    if not bin_dir.is_dir():
        raise SettingsError(
            f"bin dir not found: {bin_dir} (pass --bin-dir to point at the "
            "plugin's bin/ directory)"
        )
    return [f"Bash({name}:*)" for name in WRAPPER_SCRIPTS]


def resolve_vendor_pins() -> tuple[dict[str, str], list[str]]:
    """Resolve TRIAD_<CLI>_BIN pins for the installed vendors.

    Returns (pins, missing): `pins` maps the env var name to the resolved,
    canonical absolute path for each vendor found on PATH; `missing` lists the
    vendors not found (their wrappers fail closed under TRIAD_REQUIRE_PINNED_VENDOR
    until a re-run resolves them).
    """
    pins: dict[str, str] = {}
    missing: list[str] = []
    for cli in VENDOR_CLIS:
        found = shutil.which(cli)
        if found:
            pins[_PIN_NAME.format(cli.upper())] = str(Path(found).resolve())
        else:
            missing.append(cli)
    return pins, missing


def hardening_env(allowed_roots: str, pins: dict[str, str]) -> dict[str, str]:
    """The full `env` block this installer authors (insertion-ordered)."""
    env = {
        "TRIAD_WRAPPER_HARDENED": "1",
        "TRIAD_REQUIRE_PINNED_VENDOR": "1",
    }
    env.update(pins)
    env["TRIAD_WRAPPER_ALLOWED_ROOTS"] = allowed_roots
    env["TRIAD_AUDIT_REDACT_PROMPTS"] = "1"
    return env


# ── settings IO (O_NOFOLLOW read, flock, atomic write) ───────────────────────
def read_settings_nofollow(target: Path) -> dict:
    """Read settings.json, refusing a symlinked path (lstat + O_NOFOLLOW).

    Absent file -> empty dict. A symlink at the settings path is refused (an
    attacker could aim it at a file this process is entitled to overwrite). A
    malformed / non-object payload is a clean SettingsError.
    """
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        return {}
    if stat.S_ISLNK(st.st_mode):
        raise SettingsError(
            f"refusing to use a symlinked settings path: {target}"
        )
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        # ELOOP here means the path became a symlink between lstat and open.
        raise SettingsError(f"could not open settings {target}: {exc}") from exc
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        text = handle.read()
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError(f"settings {target} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(
            f"top-level JSON in {target} is not an object; refusing to modify"
        )
    return data


def _open_lock(target: Path, create: bool = True) -> int | None:
    """Open an advisory lock file next to the settings and flock it.

    The lock is a sidecar so it never disturbs the settings file's own
    O_NOFOLLOW read / atomic replace. Opened O_NOFOLLOW so a planted symlink at
    the lock path is refused rather than followed. With `create=False` (a
    `--remove --dry-run` or an `--install --dry-run`, which create nothing) an
    absent lock file is not created and None is returned. A run that waited on
    a lock file another run then unlinked opens the path again, so every holder
    locks the file the path names now.
    """
    flags = os.O_RDWR | os.O_NOFOLLOW
    if create:
        target.parent.mkdir(parents=True, exist_ok=True)
        flags |= os.O_CREAT
    lock_path = target.parent / LOCK_NAME
    while True:
        try:
            fd = os.open(lock_path, flags, 0o600)
        except FileNotFoundError:
            if create:
                raise
            return None
        fcntl.flock(fd, fcntl.LOCK_EX)
        held = os.fstat(fd)
        try:
            now = os.stat(lock_path, follow_symlinks=False)
        except FileNotFoundError:
            now = None
        if now and (now.st_dev, now.st_ino) == (held.st_dev, held.st_ino):
            return fd
        os.close(fd)


def _release_lock(fd: int | None, unlink: Path | None = None) -> None:
    """Release the lock; with `unlink`, remove the lock file FIRST, while the
    descriptor is still held (unlink-then-close), so no sidecar is left."""
    if fd is None:
        return
    try:
        if unlink is not None:
            unlink.unlink(missing_ok=True)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def write_atomic(target: Path, settings: dict) -> None:
    """Write settings to target atomically (temp file + os.replace in same dir)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(settings, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".settings.", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ── provenance sidecar ───────────────────────────────────────────────────────
def provenance_path(target: Path) -> Path:
    return target.parent / PROVENANCE_NAME


def read_provenance(target: Path) -> dict:
    """Prior provenance record, or an empty template if none exists."""
    path = provenance_path(target)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return _empty_provenance()
    if stat.S_ISLNK(st.st_mode):
        raise SettingsError(f"refusing to use a symlinked provenance path: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError(f"provenance {path} unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"provenance {path} is not an object")
    return _normalize_provenance(data)


def _empty_provenance() -> dict:
    return {
        "version": PROVENANCE_VERSION,
        "allow": [],
        "excludedCommands": [],
        "env": [],
        "hooks_pretooluse": [],
        "created_containers": [],
        "created_settings_file": False,
        "settings_file": None,
    }


def _normalize_provenance(data: dict) -> dict:
    base = _empty_provenance()
    for key in ("allow", "excludedCommands", "env", "hooks_pretooluse",
                "created_containers"):
        val = data.get(key)
        if isinstance(val, list):
            base[key] = [x for x in val if isinstance(x, str)]
    base["created_settings_file"] = bool(data.get("created_settings_file", False))
    if isinstance(data.get("settings_file"), str):
        base["settings_file"] = data["settings_file"]
    return base


def _has_entries(record: dict) -> bool:
    """A record that lists no entry at all is stale, whatever it names."""
    return bool(record["allow"] or record["excludedCommands"]
                or record["env"] or record["hooks_pretooluse"])


# ── merge helpers (small, single-responsibility) ─────────────────────────────
def _require_str_list(value, where: str) -> list:
    """Return value as a list, raising a clean error if it (or an element) is the
    wrong type — the guard that turns codex #9 (a dict in permissions.allow) from
    a TypeError traceback into a clean non-zero error."""
    if not isinstance(value, list):
        raise SettingsError(f"{where} is not a list; refusing to modify")
    for elem in value:
        if not isinstance(elem, str):
            raise SettingsError(
                f"{where} contains a non-string entry ({type(elem).__name__}); "
                "refusing to modify"
            )
    return value


def _require_dict(value, where: str) -> dict:
    if not isinstance(value, dict):
        raise SettingsError(f"{where} is not an object; refusing to modify")
    return value


def merge_list_entries(container: dict, key: str, entries, where: str,
                       created_containers: list, container_label: str) -> list:
    """Append `entries` (missing ones only) to container[key]; return added."""
    if key not in container:
        container[key] = []
        created_containers.append(container_label)
    lst = _require_str_list(container[key], where)
    existing = set(lst)
    added = []
    for entry in entries:
        if entry not in existing:
            lst.append(entry)
            existing.add(entry)
            added.append(entry)
    return added


def merge_env(container: dict, desired: dict, prior_env_keys: set,
              created_containers: list) -> tuple[list, list, list]:
    """Merge the hardening env into settings['env'].

    Returns (added_keys, updated_keys, foreign_keys). A key we previously authored
    is UPDATED to the current value (e.g. a moved vendor pin); a key present but
    NOT authored by us is treated as the user's, left untouched, and returned as
    `foreign` so the caller can warn.
    """
    if "env" not in container:
        container["env"] = {}
        created_containers.append("env")
    env = _require_dict(container["env"], "settings['env']")
    added, updated, foreign = [], [], []
    for key, value in desired.items():
        if key not in env:
            env[key] = value
            added.append(key)
        elif key in prior_env_keys:
            if env[key] != value:
                env[key] = value
                updated.append(key)
        else:
            foreign.append(key)
    return added, updated, foreign


# ── remove (provenance-scoped) ───────────────────────────────────────────────
def remove_authored_hooks(settings: dict, authored_commands: set) -> int:
    """Remove exactly the PreToolUse handlers whose command we authored.

    A matcher-group this call took a handler out of and left with none (and
    with no other meaningful keys) is dropped; a group it took nothing out of is
    kept as it is, empty or not, and a user's other handlers are untouched.
    Returns the count of handlers removed.
    """
    removed = 0
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    pretool = hooks.get("PreToolUse")
    if not isinstance(pretool, list):
        return 0
    kept_groups = []
    for group in pretool:
        if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
            kept_groups.append(group)
            continue
        kept_handlers = []
        for handler in group["hooks"]:
            if isinstance(handler, dict) and handler.get("command") in authored_commands:
                removed += 1
            else:
                kept_handlers.append(handler)
        if kept_handlers or not group["hooks"]:   # not emptied by this call
            group["hooks"] = kept_handlers
            kept_groups.append(group)
        elif set(group.keys()) - {"matcher", "hooks"}:
            # the group carried unexpected user keys -> preserve it (empty hooks)
            group["hooks"] = kept_handlers
            kept_groups.append(group)
        # else: a group that was only our authored handler(s) -> drop it entirely
    hooks["PreToolUse"] = kept_groups
    return removed


def _report_unrecorded(target: Path, settings: dict, record: dict) -> None:
    """Name on stderr what of the plugin's is in `settings` and not in `record`
    (an earlier install whose record is gone, an earlier plugin version): ONE
    note for the grants, the sandbox patterns and the env keys (by name, never
    the value), then one line per PreToolUse handler whose command contains the
    hook's file name. Prints only; nothing is changed."""
    def member(key: str, sub: str | None = None):
        box = settings.get(key)
        return (box.get(sub) if isinstance(box, dict) else None) if sub else box

    env_names = list(hardening_env(
        "", {_PIN_NAME.format(cli.upper()): "" for cli in VENDOR_CLIS}))
    yours = [entry for present, kind, names, recorded in (
        (member("permissions", "allow"), list,
         [f"Bash({n}:*)" for n in WRAPPER_SCRIPTS], record["allow"]),
        (member("sandbox", "excludedCommands"), list, SANDBOX_EXCLUDE_PATTERNS,
         record["excludedCommands"]),
        (member("env"), dict, env_names, record["env"]))
        if isinstance(present, kind)
        for entry in names if entry in present and entry not in recorded]
    if yours:
        noun, verb, they, it = (("entry", "is", "it is", "it") if len(yours) == 1
                                else ("entries", "are", "they are", "them"))
        print(f"note: {len(yours)} {noun} of the plugin's {verb} in {target} "
              "and in no install record "
              f"({', '.join(yours)}); {they} treated as yours and --remove leaves "
              f"{it}. Edit {it} out of the settings file yourself if an earlier "
              f"install wrote {it}.",
              file=sys.stderr)
    pretool = member("hooks", "PreToolUse")
    for group in pretool if isinstance(pretool, list) else ():
        handlers = group.get("hooks") if isinstance(group, dict) else None
        for handler in handlers if isinstance(handlers, list) else ():
            command = handler.get("command") if isinstance(handler, dict) else None
            if (isinstance(command, str) and HOOK_SCRIPT_NAME in command
                    and command not in record["hooks_pretooluse"]):
                print(f"left {target}: hook {command} — in no install record, not "
                      "removed; edit it out of the settings file yourself if an "
                      "earlier install wrote it",
                      file=sys.stderr)


def _prune_if_created(settings: dict, created: set) -> None:
    """Delete containers this installer created, deepest-first, only if empty."""
    perms = settings.get("permissions")
    if isinstance(perms, dict):
        allow = perms.get("allow")
        if "permissions.allow" in created and isinstance(allow, list) and not allow:
            perms.pop("allow", None)
        if "permissions" in created and not perms:
            settings.pop("permissions", None)
    sandbox = settings.get("sandbox")
    if isinstance(sandbox, dict):
        excluded = sandbox.get("excludedCommands")
        if ("sandbox.excludedCommands" in created and isinstance(excluded, list)
                and not excluded):
            sandbox.pop("excludedCommands", None)
        if "sandbox" in created and not sandbox:
            settings.pop("sandbox", None)
    env = settings.get("env")
    if "env" in created and isinstance(env, dict) and not env:
        settings.pop("env", None)
    hooks = settings.get("hooks")
    if isinstance(hooks, dict):
        pretool = hooks.get("PreToolUse")
        if ("hooks.PreToolUse" in created and isinstance(pretool, list)
                and not pretool):
            hooks.pop("PreToolUse", None)
        if "hooks" in created and not hooks:
            settings.pop("hooks", None)


def remove_authored(settings: dict, record: dict) -> int:
    """Remove exactly the entries the provenance record says we authored.

    Returns the count of entries removed. Non-authored (user) content is
    untouched. Raises a clean error on a malformed list rather than a traceback.
    """
    removed = 0
    perms = settings.get("permissions")
    if isinstance(perms, dict) and isinstance(perms.get("allow"), list):
        allow = _require_str_list(perms["allow"], "settings['permissions']['allow']")
        authored = set(record.get("allow", []))
        kept = [a for a in allow if a not in authored]
        removed += len(allow) - len(kept)
        perms["allow"] = kept
    sandbox = settings.get("sandbox")
    if isinstance(sandbox, dict) and isinstance(sandbox.get("excludedCommands"), list):
        excluded = _require_str_list(
            sandbox["excludedCommands"], "settings['sandbox']['excludedCommands']")
        authored = set(record.get("excludedCommands", []))
        kept = [e for e in excluded if e not in authored]
        removed += len(excluded) - len(kept)
        sandbox["excludedCommands"] = kept
    env = settings.get("env")
    if isinstance(env, dict):
        for key in record.get("env", []):
            if key in env:
                del env[key]
                removed += 1
    removed += remove_authored_hooks(settings, set(record.get("hooks_pretooluse", [])))
    _prune_if_created(settings, set(record.get("created_containers", [])))
    return removed


# ── install / remove drivers ─────────────────────────────────────────────────
def do_install(target: Path, bin_dir: Path, allowed_roots: str,
               dry_run: bool) -> int:
    grants = wrapper_grant_entries(bin_dir)
    pins, missing = resolve_vendor_pins()
    desired_env = hardening_env(allowed_roots, pins)

    lock_fd = _open_lock(target, create=not dry_run)
    try:
        prior = read_provenance(target)
        named = prior["settings_file"]
        if named and named != target.name:
            wrote = target.parent / named
            print(f"this directory's install record names {wrote}: run --install "
                  f"--target {wrote}, or --remove --target {wrote} first",
                  file=sys.stderr)
            return 1
        settings_existed = target.exists()
        settings = read_settings_nofollow(target)
        # A record of an older version names no file: adopt this target only
        # when it holds an entry of the record (checked on a copy).
        if (not named and _has_entries(prior)
                and not remove_authored(copy.deepcopy(settings), prior)):
            print("the install record of an earlier version lists entries that "
                  f"are not in {target}: if that install wrote another settings "
                  "file of this directory, run --install --target <that file>; "
                  f"the record {provenance_path(target)} names no settings file, "
                  "so it is kept: entries taken out by hand cannot be told from "
                  "entries in another file; the kept record is yours", file=sys.stderr)
            return 1

        created_containers = list(prior.get("created_containers", []))
        if "permissions" not in settings:
            settings["permissions"] = {}
            created_containers.append("permissions")
        permissions = _require_dict(settings["permissions"], "settings['permissions']")
        added_allow = merge_list_entries(
            permissions, "allow", grants,
            "settings['permissions']['allow']", created_containers,
            "permissions.allow")

        if "sandbox" not in settings:
            settings["sandbox"] = {}
            created_containers.append("sandbox")
        sandbox = _require_dict(settings["sandbox"], "settings['sandbox']")
        added_sandbox = merge_list_entries(
            sandbox, "excludedCommands", SANDBOX_EXCLUDE_PATTERNS,
            "settings['sandbox']['excludedCommands']", created_containers,
            "sandbox.excludedCommands")

        prior_env_keys = set(prior.get("env", []))
        added_env, updated_env, foreign_env = merge_env(
            settings, desired_env, prior_env_keys, created_containers)

        # The hook commands an earlier version wrote are pinned inside its
        # versioned cache dir, which the host deletes later: take them out.
        replaced_hooks = remove_authored_hooks(
            settings, set(prior["hooks_pretooluse"]))

        # provenance = what the prior record lists plus what THIS run added.
        # An entry that was already in the file and is not in the prior record
        # is the user's (a foreign env key likewise), so --remove never
        # deletes it.
        our_env_keys = set(desired_env) - set(foreign_env)
        authored = {
            "version": PROVENANCE_VERSION,
            "allow": sorted(set(prior["allow"]) | set(added_allow)),
            "excludedCommands": sorted(
                set(prior["excludedCommands"]) | set(added_sandbox)),
            "env": sorted(set(prior["env"]) | our_env_keys),
            "hooks_pretooluse": [],
            "created_containers": sorted(set(created_containers)),
            "created_settings_file": bool(
                prior["created_settings_file"] or not settings_existed),
            "settings_file": target.name,
        }

        # Every change made to `settings` above is counted here — the entries
        # added or updated and the earlier hook commands taken out (a container
        # is created only together with an entry, since the grants and the env
        # block are never empty) — so the settings file is written only when
        # `changed` is true.
        changed = bool(added_allow or added_sandbox or added_env or updated_env
                       or replaced_hooks)
        # also (re)write if the provenance record drifted from the desired set
        prov_drift = _normalize_provenance(authored) != prior

        _report_unrecorded(target, settings, authored)

        if not changed and not prov_drift:
            print(f"already up to date: all wrapper entries present in {target}")
            return 0

        if dry_run:
            _report_install(target, added_allow, added_sandbox,
                            added_env, updated_env, foreign_env, missing,
                            verb="would add")
            if replaced_hooks:
                print(f"would remove {replaced_hooks} hook path(s) of a previous version")
            if not changed:
                print(f"would update the install record of {target}")
            return 0

        # The record is written first, so an interrupted run leaves a record
        # of everything that may be in the settings file: the interim record
        # still lists the earlier hook commands this write takes out.
        interim = dict(authored, hooks_pretooluse=list(prior["hooks_pretooluse"]))
        _write_provenance(target, interim)
        if changed:     # a run that changes the record alone leaves the file as it is
            write_atomic(target, settings)
        if interim != authored:
            _write_provenance(target, authored)
        _report_install(target, added_allow, added_sandbox,
                        added_env, updated_env, foreign_env, missing,
                        verb="added")
        if replaced_hooks:
            print(f"removed {replaced_hooks} hook path(s) of a previous version")
        if not changed:
            print(f"updated the install record of {target}")
        return 0
    finally:
        _release_lock(lock_fd)


def do_remove(target: Path, dry_run: bool) -> int:
    """Remove what --install authored. Never creates anything: an absent
    parent directory is a no-op, and on success the lock sidecar, the record
    and this script's stray temp files are gone too."""
    if not target.parent.is_dir():
        print(f"nothing to remove: no managed entries at {target}")
        return 0
    lock_path = target.parent / LOCK_NAME
    lock_existed = os.path.lexists(lock_path)
    lock_fd = _open_lock(target, create=not dry_run)
    done = False
    try:
        if not dry_run:
            for stray in _listing(target.parent) or ():
                if STRAY_RE.fullmatch(stray.name):
                    stray.unlink(missing_ok=True)
        record = read_provenance(target)
        named = record["settings_file"]
        if named and named != target.name:
            wrote = target.parent / named
            print(f"the install wrote {wrote}: run --remove --target {wrote}",
                  file=sys.stderr)
            return 1
        if not _has_entries(record):
            # the read is for the report alone: a file that cannot be read
            # is named and the stale record goes all the same
            try:
                _report_unrecorded(target, read_settings_nofollow(target), record)
            except (SettingsError, OSError, ValueError) as exc:
                print(f"left {target}: {exc} — not checked for entries of the "
                      "plugin's", file=sys.stderr)
            print(f"nothing to remove: no managed entries at {target}")
            _drop_stale_record(target, dry_run)
            done = True
            return 0
        settings_existed = os.path.lexists(target)
        settings = read_settings_nofollow(target)
        read = copy.deepcopy(settings)
        removed = remove_authored(settings, record)
        _report_unrecorded(target, settings, record)
        verb = "would remove" if dry_run else "removed"
        if not removed:
            # The record names this file and none of its entries is left in
            # it: the record is stale. A record of an older version names no
            # file, so the entries may be in another one: keep it.
            if not named:
                print(f"nothing recorded was found in {target}; the record does "
                      "not name its settings file — run --remove with the "
                      "--target the install used; the record "
                      f"{provenance_path(target)} is kept (entries taken out by "
                      "hand cannot be told from entries in another file); the "
                      "kept record is yours", file=sys.stderr)
                return 1
            # the empty containers the install created go (the file too,
            # when the install created it and nothing else is in it — also
            # when the user emptied it by hand)
            if settings != read or (settings_existed and not settings and
                                    record.get("created_settings_file")):
                gone = _write_back(target, settings, record, settings_existed,
                                   dry_run)
                print(f"{verb} {target}" if gone else f"{verb} the empty "
                      f"containers the install created from {target}")
                print(f"no managed entries were left in {target}")
            else:
                print(f"nothing to remove: no managed entries at {target}")
            _drop_stale_record(target, dry_run)
            done = True
            return 0
        gone = _write_back(target, settings, record, settings_existed, dry_run)
        print(f"{verb} {removed} authored entr"
              f"{'y' if removed == 1 else 'ies'} from {target}")
        if gone:
            print(f"{verb} {target}")
        _drop_stale_record(target, dry_run)
        done = True
        return 0
    finally:
        _release_lock(lock_fd, lock_path
                      if (done or not lock_existed) and not dry_run else None)


def _write_provenance(target: Path, record: dict) -> None:
    path = provenance_path(target)
    payload = json.dumps(record, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".triad-prov.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _remove_provenance(target: Path) -> None:
    try:
        provenance_path(target).unlink()
    except FileNotFoundError:
        pass


def _write_back(target: Path, settings: dict, record: dict, settings_existed: bool,
                dry_run: bool) -> bool:
    """Write the settings the removal left, or delete the file when the install
    created it and nothing is left in it (True then); a preview writes nothing."""
    gone = bool(record.get("created_settings_file") and not settings)
    if not dry_run:
        if gone:
            target.unlink(missing_ok=True)
        elif settings_existed:
            write_atomic(target, settings)
    return gone


def _drop_stale_record(target: Path, dry_run: bool) -> None:
    """Remove a record that has nothing left to remove, and say so."""
    if os.path.lexists(provenance_path(target)):
        if not dry_run:
            _remove_provenance(target)
        print(f"{'would remove' if dry_run else 'removed'} the install "
              f"record of {target}")


# ── uninstall (machine scope) ────────────────────────────────────────────────
def _drop(path: Path, dry_run: bool, remove=os.unlink) -> None:
    if dry_run:
        print(f"would remove {path}")
        return
    try:
        remove(path)
    except OSError as exc:  # one item never stops the run
        print(f"left {path}: {exc.strerror or exc}")
    else:
        print(f"removed {path}")


def _listing(d: Path) -> list[Path] | None:
    """The entries of `d`, sorted; a directory that cannot be listed is
    reported (`left <d>: <error>`) and None is returned, so the run goes on."""
    try:
        return sorted(d.iterdir())
    except OSError as exc:
        print(f"left {d}: {exc.strerror or exc}")
        return None


def _sweep(d: Path, patterns, dry_run: bool, rmdir: bool, keep=()) -> None:
    """Remove the regular files in `d` whose names match `patterns` (a symlink
    is never followed, a path in `keep` is never touched), then — with `rmdir` —
    `d` itself when nothing else is inside."""
    try:
        mode = os.lstat(d).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as exc:  # a path that cannot be examined is not absent
        print(f"left {d}: {exc.strerror or exc}")
        return
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        print(f"left {d}: {'symlink' if stat.S_ISLNK(mode) else 'not a directory'}")
        return
    entries = _listing(d)
    if entries is None:
        return
    others = False
    for entry in entries:
        if (str(entry) in keep
                or not any(fnmatch.fnmatchcase(entry.name, p) for p in patterns)):
            others = True
        elif entry.is_symlink() or not entry.is_file():
            print(f"left {entry}: "
                  f"{'symlink' if entry.is_symlink() else 'not a regular file'}")
            others = True
        else:
            _drop(entry, dry_run)
    if rmdir and others:
        print(f"left {d}: not empty")
    elif rmdir:
        _drop(d, dry_run, os.rmdir)


def do_uninstall_machine(dry_run: bool) -> int:
    """Remove what the plugin wrote OUTSIDE any project, by fixed plugin-named
    paths only. Creates nothing, leaves an item or a plugin-named directory
    that is a symlink (a symlinked parent such as ~/.gemini is the user's
    layout and is removed through), and leaves every location an environment
    variable moved (those are the user's). One item that cannot be removed is
    reported and the run goes on; nothing in the shared temp dir is removed."""
    home = Path.home()
    # The engine's rule: XDG_CONFIG_HOME when set, else ~/.config. Both are
    # swept (a value set later leaves patches under the default); a RELATIVE
    # value was resolved against the directory each wrapper command ran from,
    # so its location cannot be known here and is reported instead.
    configs = [home / ".config"]
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if os.path.isabs(xdg) and Path(xdg) != configs[0]:
        configs.append(Path(xdg))
    elif xdg and not os.path.isabs(xdg):
        print(f"left {xdg}/triad-dispatch: XDG_CONFIG_HOME is relative — the "
              "wrappers resolved it against the directory each wrapper command "
              "ran from, so this cannot find it")
    gemini = home / ".gemini"
    keep = set()
    ext = os.environ.get("TRIAD_CLASSIFIER_EXTENSION")
    if ext:
        print(f"left {ext}: set by TRIAD_CLASSIFIER_EXTENSION (yours)")
        keep.add(os.path.abspath(ext))
    for config in configs:
        _sweep(config / "triad-dispatch", ("classifier-patches.json",
               "classifier-patches.json.lock", "classifier-patches.json.*.tmp"),
               dry_run, rmdir=True, keep=keep)
    _sweep(gemini / "config" / "agents",
           [f"{n}.md" for n in AGY_AGENT_NAMES] + ["triad-readonly-*.md.*.tmp"],
           dry_run, rmdir=False)
    cli = gemini / "antigravity-cli"
    agy_settings = os.environ.get("AGY_SETTINGS_PATH")
    if agy_settings:
        print(f"left {Path(agy_settings).parent}: set by AGY_SETTINGS_PATH (yours)")
    # A recorded agy settings transaction (_agy_settings.py) is `.agybak` or
    # the shared state; without them the lock, the two crash temp files and
    # the holders directory go. `settings.json.tmp` is never touched (not the
    # plugin's alone).
    if any(os.path.lexists(cli / n)
           for n in (".agybak", ".agy_settings.shared.json")):
        wrapper = resolve_bin_dir(None) / "antigravity_wrapper.py"
        print(f"left {cli / '.agy_settings.lock'}: an agy settings transaction is "
              f"recorded — run {wrapper} --setup-agents once (it restores the agy "
              "settings the transaction recorded), then run --uninstall-machine "
              "again")
        for name in (".agybak", ".agy_settings.shared.json", ".agybak.tmp",
                     ".agy_settings.shared.json.tmp", ".agy_settings.holders"):
            if os.path.lexists(cli / name):
                print(f"left {cli / name}: part of the recorded agy settings "
                      "transaction")
    else:
        _sweep(cli, (".agy_settings.lock", ".agybak.tmp",
                     ".agy_settings.shared.json.tmp"), dry_run, rmdir=False)
        _sweep(cli / ".agy_settings.holders", ("*",), dry_run, rmdir=True)
    for var, default in (("AGY_DAILY_STATE", cli / "triad-daily"),
                         ("GEMINI_DAILY_STATE", gemini / "triad-daily")):
        moved = os.environ.get(var)
        if moved:
            print(f"left {moved}: set by {var} (yours)")
        if not moved or os.path.abspath(moved) != str(default):
            _sweep(default, DAILY_STATE_FILES, dry_run, rmdir=True)
    # The shared temp dir holds no record of what is the plugin's: nothing is
    # removed there, the user's entries of the wrappers' name shapes are listed.
    try:
        tmp = Path(tempfile.gettempdir())
    except OSError as exc:  # no usable temp dir (a full disk): report, go on
        print(f"left {os.environ.get('TMPDIR') or 'the temporary directory'}: "
              f"{exc.strerror or exc}")
        tmp = None
    for entry in (_listing(tmp) or ()) if tmp and tmp.is_dir() else ():
        if not TEMP_FILE_RE.fullmatch(entry.name):
            continue
        try:
            st = entry.lstat()
        except OSError as exc:
            print(f"left {entry}: {exc.strerror or exc}")
            continue
        if st.st_uid == os.getuid():
            print(f"left {entry}: in the shared temporary directory, which "
                  "holds no record of what is the plugin's")
    print(f"machine-scope clean-up finished{' (dry run)' if dry_run else ''}")
    return 0


def _report_install(target, added_allow, added_sandbox, added_env, updated_env,
                    foreign_env, missing, verb: str) -> None:
    if added_allow:
        print(f"{verb} {len(added_allow)} permissions.allow grant"
              f"{'' if len(added_allow) == 1 else 's'} to {target}:")
        for entry in added_allow:
            print(f"  + {entry}")
    if added_sandbox:
        print(f"{verb} {len(added_sandbox)} sandbox.excludedCommands entr"
              f"{'y' if len(added_sandbox) == 1 else 'ies'} to {target}")
    if added_env or updated_env:
        print(f"{verb} hardening env: "
              f"{len(added_env)} new, {len(updated_env)} updated")
    if foreign_env:
        print(f"note: left your own env var(s) untouched ({', '.join(foreign_env)}); "
              "not overwriting a value you set. Remove them if you want the "
              "hardening default.", file=sys.stderr)
    if missing:
        print(f"note: vendor(s) not found on PATH ({', '.join(missing)}); their "
              "wrappers fail closed under TRIAD_REQUIRE_PINNED_VENDOR until you "
              "install them and re-run --install.", file=sys.stderr)


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Merge (or remove) the wrapper hardening + Bash allowlist in "
        "a Claude Code settings.json (merge-aware, provenance-tagged, idempotent).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--install", action="store_true",
                      help="install the hardening + allowlist (default)")
    mode.add_argument("--remove", action="store_true",
                      help="remove exactly the entries a prior --install authored "
                      "and the two sidecar files, the empty containers the "
                      "install created, and the settings file the install "
                      "created when nothing else is left in it — also when the "
                      "entries were taken out by hand, for a record that names "
                      "its settings file (give the same --target as the "
                      "--install)")
    mode.add_argument("--uninstall-machine", action="store_true",
                      help="remove the plugin's files outside any project (once per "
                      "machine, after --remove in every project)")
    parser.add_argument(
        "--target", default=".",
        help="settings.json path, or a directory (default: ./.claude/settings.json)")
    parser.add_argument(
        "--bin-dir", default=None,
        help="dir holding the wrapper scripts (default: the plugin bin/ sibling)")
    parser.add_argument(
        "--allowed-roots", default=None,
        help="colon-separated absolute paths for TRIAD_WRAPPER_ALLOWED_ROOTS")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would change without writing")
    args = parser.parse_args(argv)

    target = resolve_target(args.target)
    try:
        if args.uninstall_machine:
            return do_uninstall_machine(args.dry_run)
        if args.remove:
            return do_remove(target, args.dry_run)
        allowed_roots = resolve_allowed_roots(target, args.allowed_roots)
        bin_dir = resolve_bin_dir(args.bin_dir)
        return do_install(target, bin_dir, allowed_roots, args.dry_run)
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, TypeError, ValueError) as exc:
        # last-resort clean error (never a raw traceback for expected failures).
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
