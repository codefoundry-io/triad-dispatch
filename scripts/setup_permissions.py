#!/usr/bin/env python3
"""Merge (and remove) the wrapper hardening + allowlist into a Claude Code settings.json.

A Claude Code plugin cannot grant Bash permissions or set persistent env, so this
script writes the few entries the dispatch wrappers need into your own
`settings.json`, key-level JSON-merged, and records them in a provenance sidecar
(`.triad-dispatch-managed.json`) so `--remove` takes out exactly those entries.

An `--install` writes `permissions.allow` (one `Bash(python3 <plugin>/*/bin/<file> *)`
grant per shipped wrapper and the patch applier, the command the dispatch SKILLs
run; the review library's leg lines `Bash(env TRIAD_REVIEW_LOG_DIR=* python3
<plugin>/*/bin/<codex|gemini>_wrapper.py *)` and `Bash(env TRIAD_READ_AUDIT_FILE=*
env TRIAD_REVIEW_LOG_DIR=* python3 <plugin>/*/bin/antigravity_wrapper.py *)`; and
`Bash(python3 <plugin>/*/skills/triad-cross-family-review/lib/<module> *)` for
the library modules the review SKILL has the leader type, `bash` for its
read-audit gate script: `<plugin>` is read
from the install location and `*` stands for the version,
so the grant outlives a plugin update; it matches a command WITH arguments only,
a bare `python3 <plugin>/<ver>/bin/<file>` still prompts; the skills write the
path unquoted, so a home path with a space breaks it — not handled; with a
symlinked home or `~/.claude` the grant names the resolved path and a dispatch
typed with the unresolved one prompts — re-run --install after fixing the layout
or add the unresolved form by hand; a review leg's rendered line carries its
shell redirections (`> verdict.json 2> stderr.log`) inside a noclobber-guarded
subshell, and the claude leg's `guard:` line is shell built-ins with no grant;
Claude Code approves such parts separately from any Bash rule, so an installed
review round asks once per leg — one Bash call per leg (measured 2026-10-11 for
the redirection; the subshell and built-in parts not measured)),
`sandbox.excludedCommands` (the same patterns) and `env` (TRIAD_WRAPPER_HARDENED=1,
TRIAD_WRAPPER_ALLOWED_ROOTS=<roots>). It writes no
hook: it takes out the `hooks.PreToolUse` handlers an earlier version wrote and
its record lists, and the recorded entries this version no longer writes. An
entry in no record is yours and stays. The record is written before the settings
file and completed after it, so an interrupted run is repaired by running
--install again. A symlinked settings path is refused, the file is written
atomically (temp + os.replace), and a malformed settings list is a clean error.

Usage:
    python3 setup_permissions.py [--install] [--target <path-or-dir>] [--dry-run]
                                 [--bin-dir <dir>] [--allowed-roots <a:b:c>]
    python3 setup_permissions.py --remove   [--target <path-or-dir>] [--dry-run]
    python3 setup_permissions.py --uninstall-machine [--dry-run]

    --target        Settings file, or a directory (`<dir>/.claude/settings.json`;
                    default `.`). The record names the file it wrote: another
                    --target of that directory is refused (exit 1). A record of
                    an older version names no file: while none of its entries
                    is in the target it is kept and the run exits 1.
    --remove        Take out the recorded entries and the record. The settings
                    file is rewritten, never deleted; nothing is created.
    --uninstall-machine
                    After --remove in every project: delete the plugin's files
                    outside any project (the classifier patches, the two agy
                    agent files), printing `removed` / `left <path>: <reason>`
                    per item. A symlinked item is left; nothing in the shared
                    temp dir is touched.
    --dry-run       Print what would change and write nothing.
Exit status is 0 on success (including a no-op), non-zero on error.
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Collection
from pathlib import Path

# The shipped bin files that get a Bash grant: the wrappers and the patch applier.
WRAPPER_SCRIPTS = (
    "codex_wrapper.py",
    "gemini_wrapper.py",
    "antigravity_wrapper.py",
    "apply_patch.py",
)

# The commands granted, as (head, file) in the syntax a `Bash(...)` rule and a
# `sandbox.excludedCommands` entry share; `{plugin}` = the directory holding the
# plugin's version directories (see `_sandbox_patterns`). Each bin file as the
# dispatch SKILLs run it; the review library's leg lines, whose env prefix needs
# a rule of its own (measured, Claude Code 2.1.289); the library files the
# review SKILL has the leader run (the read-audit gate with `bash`).
_LOG_ENV = "env TRIAD_REVIEW_LOG_DIR=*"
_REVIEW_LIB = "skills/triad-cross-family-review/lib"
SANDBOX_EXCLUDE_PATTERNS = tuple(
    f"{head} {{plugin}}/*/{path} *" for head, path in (
        *(("python3", f"bin/{name}") for name in WRAPPER_SCRIPTS),
        (f"{_LOG_ENV} python3", "bin/codex_wrapper.py"),
        (f"{_LOG_ENV} python3", "bin/gemini_wrapper.py"),
        (f"env TRIAD_READ_AUDIT_FILE=* {_LOG_ENV} python3",
         "bin/antigravity_wrapper.py"),
        *(("python3", f"{_REVIEW_LIB}/{name}") for name in (
            "review_scratch.py", "verdict_v2.py", "agy_hook.py", "roster_v2.py")),
        ("bash", f"{_REVIEW_LIB}/read_audit_gate.sh"),
    ))

PROVENANCE_NAME = ".triad-dispatch-managed.json"
PROVENANCE_VERSION = 2

# --uninstall-machine: the two agy agent definitions `antigravity_wrapper.py
# --setup-agents` writes (its AGY_REVIEW_AGENT / AGY_RESEARCH_AGENT), duplicated
# so this script never imports the wrapper engine — a shipped test compares them.
AGY_AGENT_NAMES = ("triad-readonly-review", "triad-readonly-research")
# This script's own atomic-write temp names (see write_atomic / _write_provenance):
# the prefix, the 8 random characters `tempfile` appends, the suffix.
_RAND8 = "[a-z0-9_]{8}"
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


def _sandbox_patterns(bin_dir: Path) -> list[str]:
    """`SANDBOX_EXCLUDE_PATTERNS` for the plugin whose `bin/` is `bin_dir`.

    `bin_dir` is `<plugin>/<version>/bin`: `{plugin}` becomes its grandparent
    and the version stays `*`, so the patterns match the commands of every
    version of the plugin. `bin_dir` must exist.
    """
    if not bin_dir.is_dir():
        raise SettingsError(
            f"bin dir not found: {bin_dir} (pass --bin-dir to point at the "
            "plugin's bin/ directory)"
        )
    plugin = bin_dir.resolve().parent.parent
    return [p.format(plugin=plugin) for p in SANDBOX_EXCLUDE_PATTERNS]


def wrapper_grant_entries(bin_dir: Path) -> list[str]:
    """One `Bash(<pattern>)` grant per `SANDBOX_EXCLUDE_PATTERNS` entry: the
    commands the dispatch SKILLs and the review SKILL run, so they stay
    PROMPTLESS. The wrappers contain their inputs under the hardening env."""
    return [f"Bash({p})" for p in _sandbox_patterns(bin_dir)]


def hardening_env(allowed_roots: str) -> dict[str, str]:
    """The full `env` block this installer authors (insertion-ordered)."""
    return {
        "TRIAD_WRAPPER_HARDENED": "1",
        "TRIAD_WRAPPER_ALLOWED_ROOTS": allowed_roots,
    }


def _retire_unwanted(box: dict | list | None, recorded: list[str],
                     wanted: Collection[str]) -> tuple[list[str], list[str]]:
    """Retire what an earlier version wrote and this version no longer writes.

    Returns (dropped, removed), each sorted: `dropped` = the `recorded` entries
    not in `wanted` (they leave the record); `removed` = those of them present
    in `box` and now taken out of it (a dict: the key; a list: the item). An
    entry in `box` that is not in `recorded` is never touched: it is the user's.
    """
    dropped = sorted(set(recorded) - set(wanted))
    removed = []
    for entry in dropped:
        if isinstance(box, dict) and entry in box:
            del box[entry]
            removed.append(entry)
        elif isinstance(box, list) and entry in box:
            box[:] = [item for item in box if item != entry]
            removed.append(entry)
    return dropped, removed


# ── settings IO (symlink-refusing read, atomic write) ───────────────────────
def read_settings_nofollow(target: Path) -> dict:
    """Read settings.json, refusing a symlinked path.

    Absent file -> empty dict. A malformed / non-object payload is a clean
    SettingsError.
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
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsError(f"could not open settings {target}: {exc}") from exc
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
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_provenance()
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
        "settings_file": None,
    }


def _normalize_provenance(data: dict) -> dict:
    """The record's known keys; any other key (an older record's) is ignored."""
    base = _empty_provenance()
    for key in ("allow", "excludedCommands", "env", "hooks_pretooluse"):
        val = data.get(key)
        if isinstance(val, list):
            base[key] = [x for x in val if isinstance(x, str)]
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


def merge_list_entries(container: dict, key: str, entries, where: str) -> list:
    """Append `entries` (missing ones only) to container[key]; return added."""
    lst = _require_str_list(container.setdefault(key, []), where)
    existing = set(lst)
    added = []
    for entry in entries:
        if entry not in existing:
            lst.append(entry)
            existing.add(entry)
            added.append(entry)
    return added


def merge_env(container: dict, desired: dict,
              prior_env_keys: set) -> tuple[list, list, list]:
    """Merge the hardening env into settings['env'].

    Returns (added_keys, updated_keys, foreign_keys). A key we previously authored
    is UPDATED to the current value (e.g. moved allowed roots); a key present but
    NOT authored by us is treated as the user's, left untouched, and returned as
    `foreign` so the caller can warn.
    """
    env = _require_dict(container.setdefault("env", {}), "settings['env']")
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
    return removed


# ── install / remove drivers ─────────────────────────────────────────────────
def do_install(target: Path, bin_dir: Path, allowed_roots: str,
               dry_run: bool) -> int:
    grants = wrapper_grant_entries(bin_dir)
    patterns = _sandbox_patterns(bin_dir)
    desired_env = hardening_env(allowed_roots)

    prior = read_provenance(target)
    named = prior["settings_file"]
    if named and named != target.name:
        wrote = target.parent / named
        print(f"this directory's install record names {wrote}: run --install "
              f"--target {wrote}, or --remove --target {wrote} first",
              file=sys.stderr)
        return 1
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

    permissions = _require_dict(settings.setdefault("permissions", {}),
                                "settings['permissions']")
    added_allow = merge_list_entries(
        permissions, "allow", grants, "settings['permissions']['allow']")

    sandbox = _require_dict(settings.setdefault("sandbox", {}), "settings['sandbox']")
    added_sandbox = merge_list_entries(
        sandbox, "excludedCommands", patterns,
        "settings['sandbox']['excludedCommands']")

    prior_env_keys = set(prior.get("env", []))
    added_env, updated_env, foreign_env = merge_env(
        settings, desired_env, prior_env_keys)
    # the entries an earlier version wrote and this one no longer writes
    dropped_allow, removed_allow = _retire_unwanted(
        permissions.get("allow"), prior["allow"], grants)
    dropped_excl, removed_excl = _retire_unwanted(
        sandbox.get("excludedCommands"), prior["excludedCommands"], patterns)
    dropped_env, removed_env = _retire_unwanted(
        settings["env"], prior["env"], desired_env)
    removed = removed_allow + removed_excl + removed_env

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
        "allow": sorted((set(prior["allow"]) - set(dropped_allow))
                        | set(added_allow)),
        "excludedCommands": sorted(
            (set(prior["excludedCommands"]) - set(dropped_excl))
            | set(added_sandbox)),
        "env": sorted((set(prior["env"]) - set(dropped_env)) | our_env_keys),
        "hooks_pretooluse": [],
        "settings_file": target.name,
    }

    # Every change made to `settings` above is counted here — the entries
    # added or updated and the earlier hook commands taken out (a container
    # is created only together with an entry, since the grants and the env
    # block are never empty) — so the settings file is written only when
    # `changed` is true.
    changed = bool(added_allow or added_sandbox or added_env or updated_env
                   or replaced_hooks or removed)
    # also (re)write if the provenance record drifted from the desired set
    prov_drift = _normalize_provenance(authored) != prior

    if not changed and not prov_drift:
        print(f"already up to date: all wrapper entries present in {target}")
        return 0

    if dry_run:
        _report_install(target, added_allow, added_sandbox,
                        added_env, updated_env, foreign_env,
                        verb="would add")
        if removed:
            print(f"{'would remove' if dry_run else 'removed'} {len(removed)} "
                  f"{'entry' if len(removed) == 1 else 'entries'} an earlier "
                  f"version of the setup wrote: {', '.join(removed)}")
        if replaced_hooks:
            print(f"would remove {replaced_hooks} hook path(s) of a previous version")
        if not changed:
            print(f"would update the install record of {target}")
        return 0

    # The record is written first, so an interrupted run leaves a record
    # of everything that may be in the settings file: the interim record
    # still lists the earlier hook commands and the entries this write
    # takes out.
    interim = dict(authored, hooks_pretooluse=list(prior["hooks_pretooluse"]),
                   allow=sorted(set(authored["allow"]) | set(dropped_allow)),
                   excludedCommands=sorted(
                       set(authored["excludedCommands"]) | set(dropped_excl)),
                   env=sorted(set(authored["env"]) | set(dropped_env)))
    _write_provenance(target, interim)
    if changed:     # a run that changes the record alone leaves the file as it is
        write_atomic(target, settings)
    if interim != authored:
        _write_provenance(target, authored)
    _report_install(target, added_allow, added_sandbox,
                    added_env, updated_env, foreign_env,
                    verb="added")
    if removed:
        print(f"{'would remove' if dry_run else 'removed'} {len(removed)} "
              f"{'entry' if len(removed) == 1 else 'entries'} an earlier "
              f"version of the setup wrote: {', '.join(removed)}")
    if replaced_hooks:
        print(f"removed {replaced_hooks} hook path(s) of a previous version")
    if not changed:
        print(f"updated the install record of {target}")
    return 0


def do_remove(target: Path, dry_run: bool) -> int:
    """Remove what --install authored. Never creates anything: an absent
    parent directory is a no-op, and on success the record and this script's
    stray temp files are gone too."""
    if not target.parent.is_dir():
        print(f"nothing to remove: no managed entries at {target}")
        return 0
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
        print(f"nothing to remove: no managed entries at {target}")
        _drop_stale_record(target, dry_run)
        return 0
    settings = read_settings_nofollow(target)
    removed = remove_authored(settings, record)
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
        print(f"nothing to remove: no managed entries at {target}")
        _drop_stale_record(target, dry_run)
        return 0
    if not dry_run:
        write_atomic(target, settings)
    print(f"{verb} {removed} authored entr"
          f"{'y' if removed == 1 else 'ies'} from {target}")
    _drop_stale_record(target, dry_run)
    return 0


def _write_provenance(target: Path, record: dict) -> None:
    path = provenance_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    reported and the run goes on; nothing in the shared temp dir is touched."""
    home = Path.home()
    # The engine's rule: XDG_CONFIG_HOME when set, else ~/.config. Both are
    # swept (a value set later leaves patches under the default); a relative
    # value is not.
    configs = [home / ".config"]
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if os.path.isabs(xdg) and Path(xdg) != configs[0]:
        configs.append(Path(xdg))
    gemini = home / ".gemini"
    ext = os.environ.get("TRIAD_CLASSIFIER_EXTENSION")
    keep = {os.path.abspath(ext)} if ext else set()
    for config in configs:
        _sweep(config / "triad-dispatch", ("classifier-patches.json",
               "classifier-patches.json.lock", "classifier-patches.json.*.tmp"),
               dry_run, rmdir=True, keep=keep)
    _sweep(gemini / "config" / "agents",
           [f"{n}.md" for n in AGY_AGENT_NAMES] + ["triad-readonly-*.md.*.tmp"],
           dry_run, rmdir=False)
    print(f"machine-scope clean-up finished{' (dry run)' if dry_run else ''}")
    return 0


def _report_install(target, added_allow, added_sandbox, added_env, updated_env,
                    foreign_env, verb: str) -> None:
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
                      "and the install record; the settings file is rewritten, "
                      "never deleted (give the same --target as the --install)")
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
