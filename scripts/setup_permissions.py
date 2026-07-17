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
    dispatch SKILLs emit (`bin/` is on PATH) so dispatch stays PROMPTLESS. This is
    the vendor-recommended split: the basename grant exists for the promptless UX
    ONLY — it is deliberately NOT the security boundary. Claude Code's docs note
    that Bash permission patterns constraining arguments are "fragile" and "can be
    bypassed", and recommend a PreToolUse hook for reliable validation
    (https://docs.claude.com/en/docs/claude-code/hooks). The RELIABLE security gate
    is therefore the PreToolUse hook (installed separately), which validates the
    invocation + args and rejects a foreign same-named script by resolving the
    invoked path. A stranded basename grant matching a foreign same-named script on
    PATH is a low-severity residual, closed by the hook + `--remove`.
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
  * `hooks.PreToolUse` — a matcher-group ("Bash") that runs the shipped
    `hooks/pretooluse_wrapper_guard.py` on every Bash tool call. This hook is the
    RELIABLE security gate the basename grant defers to (Claude Code's docs flag
    Bash arg-patterns as fragile; a PreToolUse hook is the recommended validation):
    it resolves-and-rejects a foreign same-named wrapper on PATH and gates
    --prompt-file/--image/--cwd against the workspace roots. We append our OWN
    dedicated matcher-group (never mutate a user's), so `--remove` strips exactly
    it. The hook script is pinned by absolute path (a user-authored settings entry
    does not expand ${CLAUDE_PLUGIN_ROOT}).

Robustness: the settings file is read with O_NOFOLLOW (a symlinked settings path
is refused), the whole read-merge-write runs under an advisory `flock`, and the
new content is written atomically (temp + os.replace). A malformed settings list
(e.g. a dict where a string is expected) is a clean non-zero error, never a
traceback.

Usage:
    python3 setup_permissions.py [--install] [--target <path-or-dir>]
                                 [--bin-dir <dir>] [--hooks-dir <dir>]
                                 [--allowed-roots <a:b:c>] [--dry-run]
    python3 setup_permissions.py --remove   [--target <path-or-dir>] [--dry-run]

    --target        Settings file, or a directory. A directory (or the default)
                    resolves to `<dir>/.claude/settings.json`; the default target
                    is `./.claude/settings.json`.
    --bin-dir       Directory holding the shipped wrapper scripts (default: the
                    plugin `bin/` sibling of this script's `scripts/` dir).
    --hooks-dir     Directory holding the shipped PreToolUse hook (default: the
                    plugin `hooks/` sibling of this script's `scripts/` dir).
    --allowed-roots Colon-separated absolute paths for TRIAD_WRAPPER_ALLOWED_ROOTS
                    (default: the project root derived from --target).
    --remove        Delete exactly the entries a prior --install authored.
    --dry-run       Print what would change without writing.

Exit status is 0 on success (including a no-op re-run/remove), non-zero on error.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shlex
import shutil
import stat
import sys
import tempfile
from pathlib import Path

# The vendor CLIs whose wrappers this (claude-host) product ships. claude is the
# leader here, not a worker, so it is intentionally absent. Each name is the
# vendor binary the matching wrapper execs (antigravity_wrapper.py -> `agy`).
VENDOR_CLIS = ("codex", "gemini", "agy")

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

# The PreToolUse hook this installer registers — the RELIABLE security gate the
# basename grant defers to. It ships in the plugin `hooks/` dir (a sibling of this
# script's `scripts/` dir); the install writes a settings hooks.PreToolUse entry
# that invokes it on every Bash tool call.
HOOK_SCRIPT_NAME = "pretooluse_wrapper_guard.py"
HOOK_MATCHER = "Bash"
HOOK_INTERPRETER = "python3"

PROVENANCE_NAME = ".triad-dispatch-managed.json"
LOCK_NAME = ".triad-dispatch.lock"
PROVENANCE_VERSION = 1


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


def resolve_hooks_dir(explicit: str | None) -> Path:
    """Directory holding the shipped PreToolUse hook.

    Default: the plugin `hooks/` sibling of this script's `scripts/` dir
    (`<plugin>/scripts/setup_permissions.py` -> `<plugin>/hooks`).
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "hooks").resolve()


def hook_command(hooks_dir: Path) -> str:
    """The settings `hooks.PreToolUse` command string that runs the guard.

    Resolves the shipped hook to an absolute path (the install target's settings
    are consumed by a runtime that does not expand `${CLAUDE_PLUGIN_ROOT}` for a
    user-authored entry, so pin the absolute path) and invokes it via `python3`.
    The hook must actually be present — a registration pointing at a missing file
    would make Claude Code error on every Bash call — so an absent hook is a clean
    error, mirroring the bin-dir guard.
    """
    hook_path = (hooks_dir / HOOK_SCRIPT_NAME).resolve()
    if not hook_path.is_file():
        raise SettingsError(
            f"hook script not found: {hook_path} (pass --hooks-dir to point at "
            "the plugin's hooks/ directory)"
        )
    return f"{HOOK_INTERPRETER} {shlex.quote(str(hook_path))}"


def wrapper_grant_entries(bin_dir: Path) -> list[str]:
    """One `Bash(<wrapper>:*)` BASENAME grant per shipped wrapper.

    The grant is the bare basename (`Bash(codex_wrapper.py:*)`), matching the bare
    invocation the dispatch SKILLs emit (`bin/` is on PATH) so dispatch stays
    PROMPTLESS. This is the vendor-recommended split: the basename `permissions.allow`
    grant provides the promptless UX; the RELIABLE security gate is the PreToolUse
    hook (installed separately), which validates the invocation and rejects a foreign
    same-named script by resolving the invoked path — Claude Code's docs flag Bash
    argument patterns as fragile/bypassable and recommend a PreToolUse hook instead.
    `bin_dir` must still exist so the grant is only written when the wrappers are
    actually shipped (a sanity guard, not the source of the grant string).
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
            pins[f"TRIAD_{cli.upper()}_BIN"] = str(Path(found).resolve())
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


def _open_lock(target: Path) -> int:
    """Open (creating) an advisory lock file next to the settings and flock it.

    The lock is a sidecar so it never disturbs the settings file's own
    O_NOFOLLOW read / atomic replace. Opened O_NOFOLLOW so a planted symlink at
    the lock path is refused rather than followed.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / LOCK_NAME
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _release_lock(fd: int) -> None:
    try:
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
    }


def _normalize_provenance(data: dict) -> dict:
    base = _empty_provenance()
    for key in ("allow", "excludedCommands", "env", "hooks_pretooluse",
                "created_containers"):
        val = data.get(key)
        if isinstance(val, list):
            base[key] = [x for x in val if isinstance(x, str)]
    base["created_settings_file"] = bool(data.get("created_settings_file", False))
    return base


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


def merge_hook_entry(settings: dict, matcher: str, command: str,
                     created_containers: list) -> bool:
    """Ensure a `hooks.PreToolUse` matcher-group runs `command`; return True if added.

    Appends a DEDICATED matcher-group `{matcher, hooks:[{type:command, command}]}`
    (we own the whole group, so removal is exact and never mutates a user's group).
    A no-op when a handler with the same command already exists anywhere in
    PreToolUse (idempotent). The user's own hook groups are left untouched.
    """
    if "hooks" not in settings:
        settings["hooks"] = {}
        created_containers.append("hooks")
    hooks = _require_dict(settings["hooks"], "settings['hooks']")
    if "PreToolUse" not in hooks:
        hooks["PreToolUse"] = []
        created_containers.append("hooks.PreToolUse")
    pretool = hooks["PreToolUse"]
    if not isinstance(pretool, list):
        raise SettingsError(
            "settings['hooks']['PreToolUse'] is not a list; refusing to modify")
    for group in pretool:
        if not isinstance(group, dict):
            continue
        for handler in group.get("hooks") or []:
            if isinstance(handler, dict) and handler.get("command") == command:
                return False  # already present -> idempotent no-op
    pretool.append({
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command}],
    })
    return True


# ── remove (provenance-scoped) ───────────────────────────────────────────────
def remove_authored_hooks(settings: dict, authored_commands: set) -> int:
    """Remove exactly the PreToolUse handlers whose command we authored.

    A matcher-group left with no handlers (and no other meaningful keys) is
    dropped; a user's other handlers and groups are untouched. Returns the count
    of handlers removed.
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
        if kept_handlers:
            group["hooks"] = kept_handlers
            kept_groups.append(group)
        elif set(group.keys()) - {"matcher", "hooks"}:
            # the group carried unexpected user keys -> preserve it (empty hooks)
            group["hooks"] = kept_handlers
            kept_groups.append(group)
        # else: a group that was only our authored handler(s) -> drop it entirely
    hooks["PreToolUse"] = kept_groups
    return removed


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
def do_install(target: Path, bin_dir: Path, hooks_dir: Path, allowed_roots: str,
               dry_run: bool) -> int:
    grants = wrapper_grant_entries(bin_dir)
    hook_cmd = hook_command(hooks_dir)
    pins, missing = resolve_vendor_pins()
    desired_env = hardening_env(allowed_roots, pins)

    lock_fd = _open_lock(target)
    try:
        prior = read_provenance(target)
        settings_existed = target.exists()
        settings = read_settings_nofollow(target)

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

        added_hook = merge_hook_entry(
            settings, HOOK_MATCHER, hook_cmd, created_containers)

        # provenance = the union of everything we author-and-keep. A foreign env
        # key (the user's own, left untouched) is NOT claimed as authored, so
        # --remove never deletes it.
        our_env_keys = set(desired_env) - set(foreign_env)
        authored = {
            "version": PROVENANCE_VERSION,
            "allow": sorted(set(prior.get("allow", [])) | set(grants)),
            "excludedCommands": sorted(
                set(prior.get("excludedCommands", [])) | set(SANDBOX_EXCLUDE_PATTERNS)),
            "env": sorted(set(prior.get("env", [])) | our_env_keys),
            "hooks_pretooluse": sorted(
                set(prior.get("hooks_pretooluse", [])) | {hook_cmd}),
            "created_containers": sorted(set(created_containers)),
            "created_settings_file": bool(
                prior.get("created_settings_file", False) or not settings_existed),
        }

        changed = bool(added_allow or added_sandbox or added_env or updated_env
                       or added_hook)
        # also (re)write if the provenance record drifted from the desired set
        prov_drift = _normalize_provenance(authored) != prior

        if not changed and not prov_drift:
            print(f"already up to date: all wrapper entries present in {target}")
            return 0

        if dry_run:
            _report_install(target, added_allow, added_sandbox,
                            added_env, updated_env, added_hook, foreign_env, missing,
                            verb="would add")
            return 0

        write_atomic(target, settings)
        _write_provenance(target, authored)
        _report_install(target, added_allow, added_sandbox,
                        added_env, updated_env, added_hook, foreign_env, missing,
                        verb="added")
        return 0
    finally:
        _release_lock(lock_fd)


def do_remove(target: Path, dry_run: bool) -> int:
    if not target.exists() and not provenance_path(target).exists():
        print(f"nothing to remove: no managed entries at {target}")
        return 0
    lock_fd = _open_lock(target)
    try:
        record = read_provenance(target)
        if not (record.get("allow") or record.get("excludedCommands")
                or record.get("env") or record.get("hooks_pretooluse")):
            print(f"nothing to remove: no provenance record at {target}")
            return 0
        settings = read_settings_nofollow(target)
        removed = remove_authored(settings, record)
        if dry_run:
            print(f"would remove {removed} authored entr"
                  f"{'y' if removed == 1 else 'ies'} from {target}")
            return 0
        if record.get("created_settings_file") and not settings:
            # we created the file and nothing of the user's remains -> delete it.
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        else:
            write_atomic(target, settings)
        _remove_provenance(target)
        print(f"removed {removed} authored entr"
              f"{'y' if removed == 1 else 'ies'} from {target}")
        return 0
    finally:
        _release_lock(lock_fd)


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


def _report_install(target, added_allow, added_sandbox, added_env, updated_env,
                    added_hook, foreign_env, missing, verb: str) -> None:
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
    if added_hook:
        print(f"{verb} the PreToolUse wrapper-validation hook (the security gate)")
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
                      help="remove exactly the entries a prior --install authored")
    parser.add_argument(
        "--target", default=".",
        help="settings.json path, or a directory (default: ./.claude/settings.json)")
    parser.add_argument(
        "--bin-dir", default=None,
        help="dir holding the wrapper scripts (default: the plugin bin/ sibling)")
    parser.add_argument(
        "--hooks-dir", default=None,
        help="dir holding the PreToolUse hook (default: the plugin hooks/ sibling)")
    parser.add_argument(
        "--allowed-roots", default=None,
        help="colon-separated absolute paths for TRIAD_WRAPPER_ALLOWED_ROOTS")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would change without writing")
    args = parser.parse_args(argv)

    target = resolve_target(args.target)
    try:
        if args.remove:
            return do_remove(target, args.dry_run)
        allowed_roots = resolve_allowed_roots(target, args.allowed_roots)
        bin_dir = resolve_bin_dir(args.bin_dir)
        hooks_dir = resolve_hooks_dir(args.hooks_dir)
        return do_install(target, bin_dir, hooks_dir, allowed_roots, args.dry_run)
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, TypeError, ValueError) as exc:
        # last-resort clean error (never a raw traceback for expected failures).
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
