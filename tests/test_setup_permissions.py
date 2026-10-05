#!/usr/bin/env python3
"""Tests for the claude-host permission-setup script (stdlib-only, no pytest).

Covers the redesigned merge / provenance / --remove / hardening / robustness
contract of `setup_permissions.py`:
  (1) a fresh --install writes the bare BASENAME wrapper grants (matching the bare
      invocation the dispatch SKILLs emit so dispatch stays promptless),
      the sandbox.excludedCommands (excluded posture), and the wrapper hardening
      `env` block (TRIAD_WRAPPER_HARDENED / TRIAD_REQUIRE_PINNED_VENDOR / resolved
      TRIAD_<CLI>_BIN pins / TRIAD_WRAPPER_ALLOWED_ROOTS /
      TRIAD_AUDIT_REDACT_PROMPTS), and a provenance sidecar records them;
  (2) a second --install is a byte-identical no-op (idempotent);
  (3) a directory --target resolves to <dir>/.claude/settings.json;
  (4) an unrelated settings key + a pre-existing allow entry survive;
  (5) a pre-existing unrelated sandbox sub-key survives the merge;
  (6) the output is valid JSON;
  (7) malformed settings (bad JSON) is an error, not a clobber;
  (8) a malformed list (a dict in permissions.allow) is a CLEAN error, not a
      TypeError traceback;
  (9) --install then --remove round-trips a pre-existing settings.json for
      unrelated keys, removing ONLY the authored entries;
  (10) a symlinked settings path is refused on read (O_NOFOLLOW / lstat).

Runs in BOTH layouts: the source repo (the script lives under
`export_assets/claude-host/scripts/`) and the exported plugin (`tests/` with a
`scripts/` sibling). The script is loaded by file path, not import name.

Hermetic: a fake plugin `bin/` (the wrapper scripts — the installer requires the
bin dir to exist before it writes the basename grants) and a fake vendor-bin dir
on PATH (codex/gemini/agy, for the pin resolution) are
built in a tempdir per test, so the assertions do not depend on the host's
installed vendors.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

sys.dont_write_bytecode = True  # keep an installed plugin dir pristine (runs before _load_script)

_TESTS_DIR = Path(__file__).resolve().parent
_CANDIDATES = (
    # exported plugin layout: tests/ has a scripts/ sibling
    _TESTS_DIR.parent / "scripts" / "setup_permissions.py",
    # source repo layout: the script lives under an export_assets/claude-host/
    # scripts/ dir two levels up from this tests/ directory
    _TESTS_DIR.parents[1]
    / "export_assets"
    / "claude-host"
    / "scripts"
    / "setup_permissions.py",
)


def _load_script():
    for candidate in _CANDIDATES:
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("setup_permissions", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise AssertionError(
        "setup_permissions.py not found in any known layout: "
        + ", ".join(str(c) for c in _CANDIDATES)
    )


setup_permissions = _load_script()
WRAPPER_SCRIPTS = setup_permissions.WRAPPER_SCRIPTS
SANDBOX_PATTERNS = setup_permissions.SANDBOX_EXCLUDE_PATTERNS
VENDOR_CLIS = setup_permissions.VENDOR_CLIS


# ── hermetic fixtures ────────────────────────────────────────────────────────
def _make_bin(tmp: Path) -> Path:
    bin_dir = tmp / "plugin" / "bin"
    bin_dir.mkdir(parents=True)
    for name in WRAPPER_SCRIPTS:
        f = bin_dir / name
        f.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return bin_dir


def _make_vendor_path(tmp: Path) -> Path:
    vbin = tmp / "vbin"
    vbin.mkdir()
    for name in VENDOR_CLIS:
        f = vbin / name
        f.write_text("#!/usr/bin/env bash\necho fake\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return vbin


class _Env:
    """Context manager: fake vendors on PATH + fake bin/ + a work
    root, with HOME, XDG_CONFIG_HOME and TMPDIR pointed inside the test's own
    temp dir; every value is restored on exit."""

    VARS = ("PATH", "HOME", "XDG_CONFIG_HOME", "TMPDIR")

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.bin = _make_bin(tmp)
        self.vbin = _make_vendor_path(tmp)
        self.work = tmp / "work"
        self.work.mkdir()
        self.throwaway = tmp / "env-home"
        self.throwaway.mkdir()

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in self.VARS}
        self._saved_tempdir = tempfile.tempdir
        os.environ["PATH"] = f"{self.vbin}{os.pathsep}{self._saved['PATH'] or ''}"
        os.environ["HOME"] = str(self.throwaway)
        os.environ["XDG_CONFIG_HOME"] = str(self.throwaway / ".config")
        os.environ["TMPDIR"] = str(self.throwaway)
        tempfile.tempdir = None
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tempfile.tempdir = self._saved_tempdir

    def install_args(self, target: Path) -> list:
        return ["--install", "--target", str(target), "--bin-dir", str(self.bin),
                "--allowed-roots", str(self.work)]

    def install(self, target: Path, extra=()):
        return setup_permissions.main([*self.install_args(target), *extra])

    def remove(self, target: Path, extra=()):
        return setup_permissions.main(["--remove", "--target", str(target), *extra])


class _Machine:
    """Context manager: HOME, XDG_CONFIG_HOME and TMPDIR point INSIDE the test's
    own temp dir, the override variables are unset, and tempfile's cached temp
    dir is reset so the script's `gettempdir()` reads the test's TMPDIR. Every
    value is restored on exit — a test never touches the real home, the real
    `~/.gemini`, the real `~/.config`, or the real system temp dir."""

    VARS = ("HOME", "XDG_CONFIG_HOME", "TMPDIR", "TRIAD_CLASSIFIER_EXTENSION",
            "AGY_DAILY_STATE", "GEMINI_DAILY_STATE", "AGY_SETTINGS_PATH")

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.config = tmp / "xdg"
        self.systmp = tmp / "systmp"
        for d in (self.home, self.config, self.systmp):
            d.mkdir()

    def __enter__(self):
        self._saved = {k: os.environ.get(k) for k in self.VARS}
        self._saved_tempdir = tempfile.tempdir
        for k in self.VARS:
            os.environ.pop(k, None)
        os.environ["HOME"] = str(self.home)
        os.environ["XDG_CONFIG_HOME"] = str(self.config)
        os.environ["TMPDIR"] = str(self.systmp)
        tempfile.tempdir = None
        return self

    def __exit__(self, *exc):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        tempfile.tempdir = self._saved_tempdir

    def run(self, *args):
        """main(args) with stdout+stderr captured -> (rc, combined output)."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                rc = setup_permissions.main(list(args))
            except SystemExit as exc:  # argparse usage errors
                rc = exc.code
        return rc, buf.getvalue()


def _snapshot(root: Path) -> dict:
    """Every path under root (symlinks not followed) -> file bytes / link target
    / None for a directory: equal snapshots = nothing created, removed or changed."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            rel = str(p.relative_to(root))
            if p.is_symlink():
                snap[rel] = "->" + os.readlink(p)
            elif p.is_dir():
                snap[rel] = None
            else:
                snap[rel] = p.read_bytes()
    return snap


def _touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _plant_machine(m: _Machine) -> dict:
    """Every machine-scope item the plugin writes, at its default location, plus
    a foreign file beside each kept directory. Returns name -> path."""
    g = m.home / ".gemini"
    items = {
        "patches": _touch(m.config / "triad-dispatch" / "classifier-patches.json", "{}"),
        "patches_lock": _touch(m.config / "triad-dispatch" / "classifier-patches.json.lock", ""),
        "patches_tmp": _touch(m.config / "triad-dispatch" / "classifier-patches.json.a1b2.tmp"),
        "agent_review": _touch(g / "config" / "agents" / "triad-readonly-review.md"),
        "agent_research": _touch(g / "config" / "agents" / "triad-readonly-research.md"),
        "agent_tmp": _touch(g / "config" / "agents" / "triad-readonly-review.md.x9.tmp"),
        "agy_lock": _touch(g / "antigravity-cli" / ".agy_settings.lock", ""),
        "agy_report": _touch(g / "antigravity-cli" / "triad-daily" / "report.md"),
        "agy_snap": _touch(g / "antigravity-cli" / "triad-daily" / "models.snapshot"),
        "agy_now": _touch(g / "antigravity-cli" / "triad-daily" / "models.now"),
        "agy_raw": _touch(g / "antigravity-cli" / "triad-daily" / "changelog.raw"),
        "gem_report": _touch(g / "triad-daily" / "report.md"),
        "gem_snap": _touch(g / "triad-daily" / "version.snapshot"),
        "gem_deep": _touch(g / "triad-daily" / "deep.out"),
    }
    return items


def _plant_temp(m: _Machine) -> dict:
    """The codex temp entries of a FINISHED dispatch (older than two hours) in
    the shared temp dir. Returns name -> path."""
    items = {
        "codex_last": _touch(m.systmp / "codex_last_42_ab12cd34.txt"),
        "codex_schema": _touch(m.systmp / "codex_schema_42_cd34ef56.json"),
    }
    _age(*items.values())
    return items


TEMP_LEFT = ": in the shared temporary directory, which holds no record of what is the plugin's"


def _age(*paths: Path, seconds: int = 3 * 3600) -> None:
    then = time.time() - seconds
    for path in paths:
        os.utime(path, (then, then), follow_symlinks=False)


# ── (1) fresh install: basename grants + sandbox + hardening env + provenance ─
def test_fresh_install_writes_basename_grants_and_hardening():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            assert e.install(target) == 0
            data = json.loads(target.read_text(encoding="utf-8"))
            allow = data["permissions"]["allow"]
            for grant in setup_permissions.wrapper_grant_entries(e.bin):
                assert grant in allow, f"missing basename grant: {grant}"
            # the basename form matches the bare SKILL invocation -> promptless
            assert "Bash(codex_wrapper.py:*)" in allow
            # the install-absolute form must NOT be written (would never match the
            # bare invocation, re-introducing a prompt on every dispatch)
            abs_codex = str((e.bin / "codex_wrapper.py").resolve())
            assert f"Bash({abs_codex}:*)" not in allow
            excluded = data["sandbox"]["excludedCommands"]
            for pat in SANDBOX_PATTERNS:
                assert pat in excluded, f"missing sandbox exclude: {pat}"
            env = data["env"]
            assert env["TRIAD_WRAPPER_HARDENED"] == "1"
            assert env["TRIAD_REQUIRE_PINNED_VENDOR"] == "1"
            assert env["TRIAD_AUDIT_REDACT_PROMPTS"] == "1"
            assert env["TRIAD_WRAPPER_ALLOWED_ROOTS"] == str(e.work.resolve())
            assert env["TRIAD_CODEX_BIN"] == str((e.vbin / "codex").resolve())
            assert env["TRIAD_GEMINI_BIN"] == str((e.vbin / "gemini").resolve())
            assert env["TRIAD_AGY_BIN"] == str((e.vbin / "agy").resolve())
            prov = target.parent / setup_permissions.PROVENANCE_NAME
            assert prov.exists(), "install must write a provenance sidecar"


# ── (2) idempotent second install is a byte-identical no-op ───────────────────
def test_second_install_is_idempotent():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            assert e.install(target) == 0
            first = target.read_text(encoding="utf-8")
            assert e.install(target) == 0
            second = target.read_text(encoding="utf-8")
            assert first == second, "second install mutated the file (not idempotent)"


# ── (3) directory target resolves to .claude/settings.json ────────────────────
def test_directory_target_resolves():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            proj = tmp / "proj"
            proj.mkdir()
            assert e.install(proj) == 0
            assert (proj / ".claude" / "settings.json").is_file()


# ── (4) preserve unrelated keys + a pre-existing allow entry ──────────────────
def test_preserves_unrelated_keys_and_existing_allow():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({
                "model": "sonnet",
                "permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(rm:*)"]},
                "env": {"FOO": "bar"},
            }, indent=2), encoding="utf-8")
            assert e.install(target) == 0
            data = json.loads(target.read_text(encoding="utf-8"))
            assert data["model"] == "sonnet"
            assert data["env"]["FOO"] == "bar"
            assert data["permissions"]["deny"] == ["Bash(rm:*)"]
            assert "Bash(ls:*)" in data["permissions"]["allow"]


# ── (5) preserve a pre-existing unrelated sandbox sub-key ─────────────────────
def test_preserves_existing_sandbox_key():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({
                "sandbox": {"network": {"allowUnixSockets": True},
                            "excludedCommands": ["gh *"]},
            }, indent=2), encoding="utf-8")
            assert e.install(target) == 0
            sandbox = json.loads(target.read_text(encoding="utf-8"))["sandbox"]
            assert sandbox["network"] == {"allowUnixSockets": True}
            assert "gh *" in sandbox["excludedCommands"]
            for pat in SANDBOX_PATTERNS:
                assert sandbox["excludedCommands"].count(pat) == 1


# ── (6) output is valid JSON ─────────────────────────────────────────────────
def test_output_is_valid_json():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            assert e.install(target) == 0
            json.loads(target.read_text(encoding="utf-8"))


# ── (7) malformed settings (bad JSON) is an error, not a clobber ─────────────
def test_malformed_json_is_error_not_clobber():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            target.write_text("{ this is not json", encoding="utf-8")
            assert e.install(target) != 0
            assert target.read_text(encoding="utf-8") == "{ this is not json"


# ── (8) a dict in permissions.allow is a CLEAN error, not a TypeError ────────
def test_malformed_allow_list_clean_error():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps({"permissions": {"allow": [{"not": "a-string"}]}}),
                encoding="utf-8")
            # a clean non-zero rc (not an uncaught TypeError bubbling out)
            assert e.install(target) != 0


# ── (9) --install then --remove round-trips unrelated keys ───────────────────
def test_install_remove_round_trip():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            original = {
                "model": "opus",
                "permissions": {"allow": ["Bash(ls *)"], "deny": ["Bash(rm *)"]},
                "env": {"MY_VAR": "keep-me"},
            }
            target.write_text(json.dumps(original, indent=2), encoding="utf-8")
            assert e.install(target) == 0
            assert e.remove(target) == 0
            restored = json.loads(target.read_text(encoding="utf-8"))
            assert restored == original, "remove must restore the pre-install state"
            assert not (target.parent / setup_permissions.PROVENANCE_NAME).exists()


# ── (10) a symlinked settings path is refused (O_NOFOLLOW / lstat) ───────────
def test_symlinked_settings_refused():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            real = tmp / "real.json"
            real.write_text(json.dumps({"model": "opus"}), encoding="utf-8")
            link_dir = tmp / "proj" / ".claude"
            link_dir.mkdir(parents=True)
            link = link_dir / "settings.json"
            os.symlink(real, link)
            assert e.install(link) != 0
            # the real target is untouched
            assert json.loads(real.read_text(encoding="utf-8")) == {"model": "opus"}


# ── (11) the recorded hook of an earlier version is taken out + removed ─────
def test_takes_out_the_recorded_pretooluse_hook_of_an_earlier_version():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            assert e.install(target) == 0
            _plant_an_earlier_versions_hook(target)
            assert e.install(target) == 0
            data = json.loads(target.read_text(encoding="utf-8"))
            assert _pretooluse_commands(data) == [], data
            prov = json.loads(
                (target.parent / setup_permissions.PROVENANCE_NAME)
                .read_text(encoding="utf-8"))
            assert "pretooluse_wrapper_guard.py" not in json.dumps(prov), prov
            # the install CREATED the settings file (no pre-existing one), and
            # the earlier version created the hook containers: --remove deletes
            # the file.
            assert e.remove(target) == 0
            assert not target.exists(), "self-created settings file must be removed"


# ── (12) a pre-existing user PreToolUse hook survives install + remove ────────
def test_preserves_user_pretooluse_hook():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            user_hook = {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "/usr/bin/true"}]}
            target.write_text(json.dumps(
                {"hooks": {"PreToolUse": [user_hook]}}, indent=2), encoding="utf-8")
            assert e.install(target) == 0
            assert e.remove(target) == 0
            after = json.loads(target.read_text(encoding="utf-8"))
            # the user's own hook is intact; only our authored entry was removed
            assert after["hooks"]["PreToolUse"] == [user_hook]


# ── (13) an install over an earlier version keeps the user's hook ────────────
def test_reinstall_over_an_earlier_version_keeps_the_users_hook():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            target.parent.mkdir(parents=True)
            user_hook = {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "/usr/bin/true"}]}
            target.write_text(json.dumps(
                {"hooks": {"PreToolUse": [user_hook]}}, indent=2), encoding="utf-8")
            assert e.install(target) == 0
            _plant_an_earlier_versions_hook(target)             # version A
            assert e.install(target) == 0
            pretool = json.loads(target.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
            assert pretool == [user_hook], pretool
            prov = json.loads((target.parent / setup_permissions.PROVENANCE_NAME)
                              .read_text(encoding="utf-8"))
            assert prov["hooks_pretooluse"] == [], prov
            assert e.remove(target) == 0
            after = json.loads(target.read_text(encoding="utf-8"))
            assert after["hooks"]["PreToolUse"] == [user_hook], after


# ── (14) entries the user already had are not recorded, so --remove keeps them
def test_user_entries_already_present_survive_install_and_remove():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            hook_group = {"matcher": "Bash", "hooks": [
                {"type": "command", "command": LEGACY_HOOK}]}
            original = {
                "permissions": {"allow": ["Bash(codex_wrapper.py:*)"]},
                "sandbox": {"excludedCommands": ["codex_wrapper.py *"]},
                "hooks": {"PreToolUse": [hook_group]},
            }
            _touch(target, json.dumps(original, indent=2))
            assert e.install(target) == 0
            installed = json.loads(target.read_text(encoding="utf-8"))
            assert len(installed["permissions"]["allow"]) == len(WRAPPER_SCRIPTS)
            assert e.remove(target) == 0
            assert json.loads(target.read_text(encoding="utf-8")) == original


# The hook entry an earlier version of the plugin wrote (the setup writes none).
LEGACY_HOOK = "python3 /old/hooks/pretooluse_wrapper_guard.py"
LEGACY_GROUP = {"matcher": "Bash", "hooks": [{"type": "command", "command": LEGACY_HOOK}]}


def _plant_an_earlier_versions_hook(target: Path) -> None:
    """Add to an installed settings file and its record the hook entry an earlier
    version wrote: its own group, recorded, with the containers it created."""
    prov = target.parent / setup_permissions.PROVENANCE_NAME
    data = json.loads(target.read_text(encoding="utf-8"))
    record = json.loads(prov.read_text(encoding="utf-8"))
    if "hooks" not in data:
        data["hooks"] = {}
        record["created_containers"].append("hooks")
    if "PreToolUse" not in data["hooks"]:
        data["hooks"]["PreToolUse"] = []
        record["created_containers"].append("hooks.PreToolUse")
    data["hooks"]["PreToolUse"].append(LEGACY_GROUP)
    record["hooks_pretooluse"] = [LEGACY_HOOK]
    record["created_containers"].sort()
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    prov.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


# ── (H1) --install writes no hook ────────────────────────────────────────────
def test_install_writes_no_hook():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            assert e.install(target) == 0
            data = json.loads(target.read_text(encoding="utf-8"))
            assert "hooks" not in data, data
            record = json.loads((target.parent / setup_permissions.PROVENANCE_NAME)
                                .read_text(encoding="utf-8"))
            assert record["hooks_pretooluse"] == [], record
            assert not any(c.startswith("hooks") for c in record["created_containers"]), \
                record


# ── (H2) --install takes out the hook an earlier version wrote ───────────────
def test_install_removes_the_hook_an_earlier_version_wrote():
    user_group = {"matcher": "Bash", "hooks": [
        {"type": "command", "command": "/usr/bin/true"}]}
    for original in (USER_CONTENT, {**USER_CONTENT,
                                    "hooks": {"PreToolUse": [user_group]}}):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Env(tmp) as e, _Machine(tmp) as m:
                target = _touch(tmp / "proj" / ".claude" / "settings.json",
                                json.dumps(original, indent=2))
                prov = target.parent / setup_permissions.PROVENANCE_NAME
                assert e.install(target) == 0
                _plant_an_earlier_versions_hook(target)
                before = _snapshot(tmp)
                rc, out = m.run(*e.install_args(target), "--dry-run")
                assert rc == 0, out
                assert "would remove 1 hook path(s) of a previous version\n" in out, out
                assert _snapshot(tmp) == before, out
                rc, out = m.run(*e.install_args(target))
                assert rc == 0, out
                assert "removed 1 hook path(s) of a previous version\n" in out, out
                data = json.loads(target.read_text(encoding="utf-8"))
                assert _pretooluse_commands(data) == _pretooluse_commands(original), data
                assert LEGACY_GROUP not in data["hooks"]["PreToolUse"], data
                assert json.loads(prov.read_text(encoding="utf-8"))[
                    "hooks_pretooluse"] == [], out
                # --remove leaves the settings as they were before any install,
                # dropping the hook containers the earlier version created
                rc, out = m.run("--remove", "--target", str(target))
                assert rc == 0, out
                assert json.loads(target.read_text(encoding="utf-8")) == original, out


# ── (H3) --install runs when the plugin ships no hooks/ directory ────────────
def test_install_runs_without_a_hooks_directory():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            plugin = tmp / "bare-plugin"
            script = _touch(plugin / "scripts" / "setup_permissions.py",
                            Path(setup_permissions.__file__).read_text(encoding="utf-8"))
            for name in WRAPPER_SCRIPTS:
                _touch(plugin / "bin" / name, "#!/usr/bin/env python3\n")
            spec = importlib.util.spec_from_file_location("setup_copy", script)
            copy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(copy)
            target = tmp / "proj" / ".claude" / "settings.json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = copy.main(["--install", "--target", str(target),
                                "--allowed-roots", str(e.work)])
            assert rc == 0, buf.getvalue()
            assert not (plugin / "hooks").exists()
            assert "hooks" not in json.loads(target.read_text(encoding="utf-8"))


# ── (A1) --remove on a project with no .claude/ creates nothing ──────────────
def test_remove_without_claude_dir_creates_nothing():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            proj = tmp / "proj"
            proj.mkdir()
            before = _snapshot(tmp)
            rc, out = m.run("--remove", "--target", str(proj))
            assert rc == 0, out
            assert _snapshot(tmp) == before, "remove created something"
            assert not (proj / ".claude").exists()


# ── (A2) an empty provenance record is removed, and no lock is left ──────────
def test_remove_empty_record_deletes_provenance():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            claude = tmp / "proj" / ".claude"
            settings = _touch(claude / "settings.json", '{"model": "opus"}\n')
            _touch(claude / setup_permissions.PROVENANCE_NAME, json.dumps(
                {"version": 1, "allow": [], "excludedCommands": [], "env": [],
                 "hooks_pretooluse": [], "created_containers": [],
                 "created_settings_file": False}))
            rc, out = m.run("--remove", "--target", str(tmp / "proj"))
            assert rc == 0, out
            assert sorted(os.listdir(claude)) == ["settings.json"], os.listdir(claude)
            assert settings.read_text(encoding="utf-8") == '{"model": "opus"}\n'


# ── (A3) --remove never re-creates a settings.json the user deleted ──────────
def test_remove_with_absent_settings_does_not_create_it():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = _touch(tmp / "proj" / ".claude" / "settings.json", "{}\n")
            assert e.install(target) == 0
            target.unlink()  # the user deleted it; the record says we did not create it
            rc, out = m.run("--remove", "--target", str(target))
            # no settings file beside the target holds a recorded entry: the
            # record is stale -> removed, nothing left, nothing created
            assert rc == 0, out
            assert not target.exists(), "remove re-created the deleted settings.json"
            assert os.listdir(target.parent) == [], os.listdir(target.parent)


# ── (A4) install then remove leaves NO sidecar and the user's keys intact ────
def test_install_remove_leaves_no_sidecar():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            original = {"model": "opus", "env": {"MY_VAR": "keep-me"},
                        "permissions": {"allow": ["Bash(ls *)"]}}
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            json.dumps(original, indent=2))
            assert e.install(target) == 0
            # crash residue of this script's own atomic writes
            _touch(target.parent / ".settings.k3j2m4n5.json.tmp")
            _touch(target.parent / ".triad-prov.p0q9r8s7.json.tmp")
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert os.listdir(target.parent) == ["settings.json"], os.listdir(target.parent)
            assert json.loads(target.read_text(encoding="utf-8")) == original
            assert (tmp / "proj" / ".claude").is_dir(), "the user's .claude/ must stay"


# ── (A5) --remove --dry-run creates and removes nothing ──────────────────────
def test_remove_dry_run_changes_nothing():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = tmp / "proj" / ".claude" / "settings.json"
            assert e.install(target) == 0
            (target.parent / setup_permissions.LOCK_NAME).unlink()
            _touch(target.parent / ".settings.k3j2m4n5.json.tmp")
            before = _snapshot(tmp)
            rc, out = m.run("--remove", "--dry-run", "--target", str(target))
            assert rc == 0, out
            assert "would remove" in out, out
            assert _snapshot(tmp) == before, "a dry run changed the tree"


# ── (A6) --remove with another --target than the install's is refused ───────
def test_remove_other_target_is_refused():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            proj = tmp / "proj"
            local = proj / ".claude" / "settings.local.json"
            assert e.install(local) == 0
            prov = local.parent / setup_permissions.PROVENANCE_NAME
            record = json.loads(prov.read_text(encoding="utf-8"))
            assert record["settings_file"] == "settings.local.json", record
            assert record["version"] == 2, record
            before = _snapshot(tmp)
            rc, out = m.run("--remove", "--target", str(proj))
            assert rc == 1, out
            assert out == (f"the install wrote {local}: "
                           f"run --remove --target {local}\n"), out
            assert _snapshot(tmp) == before, out
            rc, out = m.run("--remove", "--target", str(local))
            assert rc == 0, out
            assert os.listdir(local.parent) == [], os.listdir(local.parent)


# ── (A9) an install into a second settings file of the directory is refused ──
def test_install_into_a_second_settings_file_is_refused():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            claude = tmp / "proj" / ".claude"
            local = claude / "settings.local.json"
            assert e.install(local) == 0
            before = _snapshot(tmp)
            rc, out = m.run(*e.install_args(claude / "settings.json"))
            assert rc == 1, out
            assert out == (f"this directory's install record names {local}: "
                           f"run --install --target {local}, "
                           f"or --remove --target {local} first\n"), out
            assert _snapshot(tmp) == before, out


# ── (A10) a record of version 1 (no settings_file member) ────────────────────
def _make_v1_record(prov: Path) -> None:
    record = json.loads(prov.read_text(encoding="utf-8"))
    del record["settings_file"]
    record["version"] = 1
    prov.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def test_version1_record_without_settings_file():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            claude = tmp / "proj" / ".claude"
            target = claude / "settings.json"
            other = claude / "settings.local.json"
            prov = claude / setup_permissions.PROVENANCE_NAME
            assert e.install(target) == 0
            _make_v1_record(prov)
            # --remove of another target: nothing recorded there -> record kept
            before = _snapshot(tmp)
            rc, out = m.run("--remove", "--target", str(other))
            assert rc == 1, out
            assert out == (f"nothing recorded was found in {other}; the record does "
                           "not name its settings file — run --remove with the "
                           f"--target the install used; the record {prov} is kept "
                           "(entries taken out by hand cannot be told from entries "
                           "in another file); the kept record is yours\n"), out
            assert _snapshot(tmp) == before, out
            # --install adopts the given target and writes the member
            assert e.install(target) == 0
            record = json.loads(prov.read_text(encoding="utf-8"))
            assert record["settings_file"] == "settings.json", record
            assert record["version"] == 2, record
            # --remove of the right target works (a version-1 record as well)
            _make_v1_record(prov)
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert os.listdir(claude) == [], os.listdir(claude)


def _v1_refusal(target: Path, prov: Path) -> str:
    return (f"the install record of an earlier version lists entries that are not "
            f"in {target}: if that install wrote another settings file of this "
            f"directory, run --install --target <that file>; the record {prov} "
            f"names no settings file, so it is kept: entries taken out by hand "
            f"cannot be told from entries in another file; the kept record is "
            f"yours\n")


# ── (A11) a version-1 record whose entries are in another settings file ──────
def test_version1_record_install_into_a_file_without_its_entries_is_refused():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            claude = tmp / "proj" / ".claude"
            local = claude / "settings.local.json"
            target = claude / "settings.json"
            prov = claude / setup_permissions.PROVENANCE_NAME
            assert e.install(local) == 0
            _make_v1_record(prov)
            before = _snapshot(tmp)
            rc, out = m.run(*e.install_args(target))
            assert rc == 1, out
            assert out == _v1_refusal(target, prov), out
            assert not target.exists(), out
            assert _snapshot(tmp) == before, out


# ── (A12) a version-1 record none of whose entries is anywhere ───────────────
def test_version1_record_with_no_entry_left_names_both_ways_out():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            claude = tmp / "proj" / ".claude"
            target = claude / "settings.json"
            prov = claude / setup_permissions.PROVENANCE_NAME
            assert e.install(target) == 0
            _make_v1_record(prov)
            target.write_text('{"model": "opus"}\n', encoding="utf-8")
            before = _snapshot(tmp)
            rc, out = m.run(*e.install_args(target))
            assert rc == 1, out
            assert out == _v1_refusal(target, prov), out
            assert _snapshot(tmp) == before, out
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 1, out
            assert out == (f"nothing recorded was found in {target}; the record does "
                           "not name its settings file — run --remove with the "
                           f"--target the install used; the record {prov} is kept "
                           "(entries taken out by hand cannot be told from entries "
                           "in another file); the kept record is yours\n"), out
            assert _snapshot(tmp) == before, out
            prov.unlink()
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            assert json.loads(prov.read_text(encoding="utf-8"))["settings_file"] == \
                "settings.json"


# ── (W1) an interrupted install can be repaired ──────────────────────────────
@contextlib.contextmanager
def _record_write_fails_after_settings_write():
    """A record write that comes AFTER a settings write raises OSError (a full
    disk, an interruption between the two writes)."""
    real_write, real_prov = setup_permissions.write_atomic, setup_permissions._write_provenance
    wrote_settings = []

    def write(target, settings):
        real_write(target, settings)
        wrote_settings.append(target)

    def prov(target, record):
        if wrote_settings:
            raise OSError(28, "No space left on device")
        real_prov(target, record)

    setup_permissions.write_atomic, setup_permissions._write_provenance = write, prov
    try:
        yield
    finally:
        setup_permissions.write_atomic, setup_permissions._write_provenance = \
            real_write, real_prov


def _pretooluse_commands(settings: dict) -> list:
    return [h.get("command") for g in settings.get("hooks", {}).get("PreToolUse", [])
            for h in g.get("hooks", [])]


def test_the_record_is_written_first_and_an_interrupted_first_install_is_repaired():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            original = {"model": "opus", "env": {"MY_VAR": "keep-me"}}
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            json.dumps(original, indent=2))
            # before wave 3 the one record write came after the settings write
            # and failed here (rc 1); now the record is written first and, on
            # a fresh install, is final already — the run may end 0 or 1
            with _record_write_fails_after_settings_write():
                m.run(*e.install_args(target))
            assert (target.parent / setup_permissions.PROVENANCE_NAME).exists()
            assert e.install(target) == 0
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert json.loads(target.read_text(encoding="utf-8")) == original, out
            assert not (target.parent / setup_permissions.PROVENANCE_NAME).exists()


def test_install_interrupted_before_the_settings_write_is_removable():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            '{"model": "opus"}\n')
            prov = target.parent / setup_permissions.PROVENANCE_NAME
            real_write = setup_permissions.write_atomic

            def fail(target, settings):
                raise OSError(28, "No space left on device")

            setup_permissions.write_atomic = fail
            try:
                rc, out = m.run(*e.install_args(target))
            finally:
                setup_permissions.write_atomic = real_write
            assert rc == 1, out
            assert prov.exists(), "the record must be written before the settings"
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert not prov.exists(), out
            assert target.read_text(encoding="utf-8") == '{"model": "opus"}\n'


def test_plugin_update_interrupted_after_the_settings_write_is_repaired():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = tmp / "proj" / ".claude" / "settings.json"
            prov = target.parent / setup_permissions.PROVENANCE_NAME
            assert e.install(target) == 0
            _plant_an_earlier_versions_hook(target)             # hook OLD
            with _record_write_fails_after_settings_write():
                rc, out = m.run(*e.install_args(target))
            assert rc == 1, out
            # the interim record still lists the hook the settings write took out
            assert json.loads(prov.read_text(encoding="utf-8"))["hooks_pretooluse"] == \
                [LEGACY_HOOK]
            assert _pretooluse_commands(json.loads(target.read_text(encoding="utf-8"))) == []
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            assert json.loads(prov.read_text(encoding="utf-8"))["hooks_pretooluse"] == []
            assert _pretooluse_commands(json.loads(target.read_text(encoding="utf-8"))) == []


def _left_hook(target: Path, command: str) -> str:
    return (f"left {target}: hook {command} — in no install record, not removed; "
            "edit it out of the settings file yourself if an earlier install wrote it\n")


# The env key names the plugin writes (written out here, not read from the
# script, so a change of the script's set shows in this test).
PLUGIN_ENV_NAMES = ("TRIAD_WRAPPER_HARDENED", "TRIAD_REQUIRE_PINNED_VENDOR",
                    "TRIAD_CODEX_BIN", "TRIAD_GEMINI_BIN", "TRIAD_AGY_BIN",
                    "TRIAD_WRAPPER_ALLOWED_ROOTS", "TRIAD_AUDIT_REDACT_PROMPTS")
USER_CONTENT = {"model": "opus", "env": {"MY_VAR": "keep-me"},
                "permissions": {"allow": ["Bash(ls *)"]}}


def _unrecorded_note(target: Path, entries) -> str:
    if len(entries) == 1:
        return (f"note: 1 entry of the plugin's is in {target} and in no install "
                f"record ({entries[0]}); it is treated as yours and --remove leaves "
                "it. Edit it out of the settings file yourself if an earlier "
                "install wrote it.\n")
    return (f"note: {len(entries)} entries of the plugin's are in {target} and in no "
            f"install record ({', '.join(entries)}); they are treated as yours and "
            "--remove leaves them. Edit them out of the settings file yourself if an "
            "earlier install wrote them.\n")


def _every_plugin_entry(e: _Env) -> list:
    return [*setup_permissions.wrapper_grant_entries(e.bin), *SANDBOX_PATTERNS,
            *PLUGIN_ENV_NAMES]


def _add_an_unrecorded_hook(target: Path) -> None:
    """The hook entry an earlier version wrote, in the settings and in no record."""
    data = json.loads(target.read_text(encoding="utf-8"))
    data.setdefault("hooks", {}).setdefault("PreToolUse", []).append(LEGACY_GROUP)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _assert_user_content_unnamed(out: str, e: _Env) -> None:
    # the user's own env key and grant, and the VALUES of the plugin's env keys
    for text in ("MY_VAR", "keep-me", "Bash(ls *)", str(e.vbin.resolve()),
                 str(e.work.resolve())):
        assert text not in out, (text, out)


def test_entries_in_no_record_are_named():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            json.dumps(USER_CONTENT, indent=2))
            prov = target.parent / setup_permissions.PROVENANCE_NAME
            assert e.install(target) == 0
            prov.unlink()                    # the user deleted the record
            _add_an_unrecorded_hook(target)
            cmd = LEGACY_HOOK
            note = _unrecorded_note(target, _every_plugin_entry(e))
            for run in range(2):             # a run that writes, then an up-to-date one
                rc, out = m.run(*e.install_args(target))
                assert rc == 0, out
                assert note in out, out
                assert _left_hook(target, cmd) in out, out
                _assert_user_content_unnamed(out, e)
                record = json.loads(prov.read_text(encoding="utf-8"))
                assert (record["allow"], record["excludedCommands"],
                        record["hooks_pretooluse"]) == ([], [], []), record
            assert "already up to date" in out, out
            before = target.read_bytes()
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert "nothing to remove" in out, out
            assert note in out, out
            assert _left_hook(target, cmd) in out, out
            assert target.read_bytes() == before, out


def test_remove_names_every_entry_of_the_plugins_in_no_record():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            json.dumps(USER_CONTENT, indent=2))
            assert e.install(target) == 0
            (target.parent / setup_permissions.PROVENANCE_NAME).unlink()
            _add_an_unrecorded_hook(target)
            cmd = LEGACY_HOOK
            before = target.read_bytes()
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert out.count("note: ") == 1, out
            assert _unrecorded_note(target, _every_plugin_entry(e)) in out, out
            assert _left_hook(target, cmd) in out, out
            _assert_user_content_unnamed(out, e)
            assert target.read_bytes() == before, out
            # one entry: the singular text
            target.write_text('{"env": {"TRIAD_AUDIT_REDACT_PROMPTS": "1"}}\n',
                              encoding="utf-8")
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert _unrecorded_note(target, ["TRIAD_AUDIT_REDACT_PROMPTS"]) in out, out


def test_a_record_of_every_entry_gets_no_note():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            json.dumps(USER_CONTENT, indent=2))
            outs = [m.run(*e.install_args(target)), m.run(*e.install_args(target)),
                    m.run("--remove", "--target", str(target))]
            for rc, out in outs:
                assert rc == 0, out
                assert "no install record" not in out, out
                _assert_user_content_unnamed(out, e)
            assert json.loads(target.read_text(encoding="utf-8")) == USER_CONTENT


def test_remove_of_a_record_without_entries_goes_on_past_an_unreadable_settings_file():
    for kind in ("not json", "symlink"):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Machine(tmp) as m:
                claude = tmp / "proj" / ".claude"
                target = claude / "settings.json"
                prov = _touch(claude / setup_permissions.PROVENANCE_NAME, json.dumps(
                    {"version": 2, "allow": [], "excludedCommands": [], "env": [],
                     "hooks_pretooluse": [], "created_containers": [],
                     "created_settings_file": False, "settings_file": "settings.json"}))
                if kind == "not json":
                    _touch(target, "{ not json")
                else:
                    os.symlink(_touch(tmp / "real.json", '{"model": "opus"}\n'), target)
                before = _snapshot(tmp)
                rc, out = m.run("--remove", "--target", str(target))
                assert rc == 0, (kind, out)
                assert re.search(rf"^left {re.escape(str(target))}: .+ — not checked "
                                 "for entries of the plugin's$", out, re.M), (kind, out)
                assert f"nothing to remove: no managed entries at {target}\n" in out, out
                assert not prov.exists(), (kind, out)
                after = _snapshot(tmp)
                del before[str(prov.relative_to(tmp))]
                assert after == before, (kind, out)


def test_a_hook_joined_to_a_shell_operator_is_named():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            cmd = "python3 /old/hooks/pretooluse_wrapper_guard.py&&true"
            group = {"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]}
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            json.dumps({"hooks": {"PreToolUse": [group]}}, indent=2))
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            assert _left_hook(target, cmd) in out, out
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert _left_hook(target, cmd) in out, out
            assert json.loads(target.read_text(encoding="utf-8")) == \
                {"hooks": {"PreToolUse": [group]}}


def test_a_hook_of_an_earlier_version_is_named_and_left():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            cmd_old = f"python3 {tmp / 'cache' / '0.9.0' / 'hooks'}/pretooluse_wrapper_guard.py"
            old_group = {"matcher": "Bash", "hooks": [{"type": "command", "command": cmd_old}]}
            text = json.dumps({"hooks": {"PreToolUse": [old_group]}}, indent=2)
            target = _touch(tmp / "proj" / ".claude" / "settings.json", text)
            prov = target.parent / setup_permissions.PROVENANCE_NAME
            rc, out = m.run(*e.install_args(target), "--dry-run")
            assert rc == 0, out
            assert _left_hook(target, cmd_old) in out, out
            assert target.read_text(encoding="utf-8") == text and not prov.exists()
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            assert _left_hook(target, cmd_old) in out, out
            assert json.loads(prov.read_text(encoding="utf-8"))["hooks_pretooluse"] == []
            assert _pretooluse_commands(json.loads(target.read_text(encoding="utf-8"))) == \
                [cmd_old]
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert _left_hook(target, cmd_old) in out, out
            assert json.loads(target.read_text(encoding="utf-8")) == \
                {"hooks": {"PreToolUse": [old_group]}}


def test_a_users_own_hook_gets_no_line():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            groups = [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": "/usr/bin/true"},
                {"type": "command", "command": "python3 /home/me/guards/other_guard.py"}]}]
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            json.dumps({"hooks": {"PreToolUse": groups}}, indent=2))
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            rc, out_remove = m.run("--remove", "--target", str(target))
            assert rc == 0, out_remove
            for text in (out, out_remove):
                assert "in no install record" not in text, text
            assert json.loads(target.read_text(encoding="utf-8")) == \
                {"hooks": {"PreToolUse": groups}}


def _empty_record(claude: Path, settings_file: str = "settings.json") -> Path:
    return _touch(claude / setup_permissions.PROVENANCE_NAME, json.dumps(
        {"version": 2, "allow": [], "excludedCommands": [], "env": [],
         "hooks_pretooluse": [], "created_containers": [],
         "created_settings_file": False, "settings_file": settings_file}))


# ── (W5-1) a record that names another file is refused, whatever it lists ───
def test_remove_of_a_record_without_entries_that_names_another_file_is_refused():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            proj = tmp / "proj"
            claude = proj / ".claude"
            local = claude / "settings.local.json"
            prov = claude / setup_permissions.PROVENANCE_NAME
            assert e.install(local) == 0
            prov.unlink()
            assert e.install(local) == 0     # every entry present: a record of none
            record = setup_permissions.read_provenance(local)
            assert record["settings_file"] == "settings.local.json", record
            assert not setup_permissions._has_entries(record), record
            _add_an_unrecorded_hook(local)
            # an entry of the plugin's in the default file too: a read would name it
            _touch(claude / "settings.json",
                   '{"env": {"TRIAD_AUDIT_REDACT_PROMPTS": "1"}}\n')
            before = _snapshot(tmp)
            with contextlib.chdir(proj):     # the default target, a relative path
                rc, out = m.run("--remove")
            named = Path(".claude") / "settings.local.json"
            assert rc == 1, out
            assert out == (f"the install wrote {named}: "
                           f"run --remove --target {named}\n"), out
            assert _snapshot(tmp) == before, out
            rc, out = m.run("--remove", "--target", str(local))
            assert rc == 0, out
            assert _unrecorded_note(local, _every_plugin_entry(e)) in out, out
            assert _left_hook(local, LEGACY_HOOK) in out, out
            assert f"nothing to remove: no managed entries at {local}\n" in out, out
            assert not prov.exists(), out


# ── (W5-2) a container that is no object holds no entry ─────────────────────
def test_a_container_that_is_no_object_holds_no_entry():
    handler = {"type": "command",
               "command": "python3 /old/hooks/pretooluse_wrapper_guard.py"}
    for settings in ({"permissions": ["Bash(codex_wrapper.py:*)"]},
                     {"sandbox": ["codex_wrapper.py *"]},
                     {"hooks": [{"matcher": "Bash", "hooks": [handler]}]}):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Machine(tmp) as m:
                claude = tmp / "proj" / ".claude"
                target = _touch(claude / "settings.json", json.dumps(settings))
                _empty_record(claude)
                rc, out = m.run("--remove", "--target", str(target))
                assert rc == 0, (settings, out)
                assert out == (f"nothing to remove: no managed entries at {target}\n"
                               f"removed the install record of {target}\n"), \
                    (settings, out)


# ── (W5-3) every env key the install writes is named by the note ─────────────
def test_every_env_key_the_install_writes_is_named():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            pins, missing = setup_permissions.resolve_vendor_pins()
            assert missing == [] and len(pins) == len(VENDOR_CLIS), (pins, missing)
            env = setup_permissions.hardening_env(str(e.work), pins)
            claude = tmp / "proj" / ".claude"
            target = _touch(claude / "settings.json", json.dumps({"env": env}))
            _empty_record(claude)
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert _unrecorded_note(target, list(env)) in out, out


# ── (W5-4) the preview names the hook path of an earlier version it would take out
def test_install_dry_run_names_the_hook_path_it_would_remove():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = tmp / "proj" / ".claude" / "settings.json"
            prov = target.parent / setup_permissions.PROVENANCE_NAME
            assert e.install(target) == 0
            _plant_an_earlier_versions_hook(target)             # hook OLD
            settings_before, record_before = target.read_bytes(), prov.read_bytes()
            rc, out = m.run(*e.install_args(target), "--dry-run")
            assert rc == 0, out
            assert "would remove 1 hook path(s) of a previous version\n" in out, out
            assert target.read_bytes() == settings_before, out
            assert prov.read_bytes() == record_before, out


# ── (W6-1) the note reads each container in the shape the host reads ────────
def test_a_container_of_another_type_than_the_host_reads_holds_no_entry():
    for settings in ({"env": ["TRIAD_WRAPPER_HARDENED"]},
                     {"permissions": {"allow": {"Bash(codex_wrapper.py:*)": True}}},
                     {"sandbox": {"excludedCommands": {"codex_wrapper.py *": True}}}):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Machine(tmp) as m:
                claude = tmp / "proj" / ".claude"
                target = _touch(claude / "settings.json", json.dumps(settings))
                _empty_record(claude)
                rc, out = m.run("--remove", "--target", str(target))
                assert rc == 0, (settings, out)
                assert out == (f"nothing to remove: no managed entries at {target}\n"
                               f"removed the install record of {target}\n"), \
                    (settings, out)


# ── (W6-2) a preview of the install writes nothing ──────────────────────────
def test_install_dry_run_creates_no_directory_and_no_lock_file():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            proj = tmp / "proj"
            proj.mkdir()
            target = proj / ".claude" / "settings.json"
            before = _snapshot(tmp)
            rc, out = m.run(*e.install_args(target), "--dry-run")
            assert rc == 0, out
            assert f"would add {len(WRAPPER_SCRIPTS)} permissions.allow grants to " \
                   f"{target}:\n" in out, out
            assert _snapshot(tmp) == before, out
            assert not (proj / ".claude").exists(), out
            # a .claude/ without a lock file: the preview creates none
            target.parent.mkdir()
            rc, out = m.run(*e.install_args(target), "--dry-run")
            assert rc == 0, out
            assert os.listdir(target.parent) == [], os.listdir(target.parent)


# ── (W6-3) an install into another file than the record names is refused,
#    whatever the record lists ──────────────────────────────────────────────────
def test_install_beside_a_record_without_entries_that_names_another_file_is_refused():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            claude = tmp / "proj" / ".claude"
            local = claude / "settings.local.json"
            target = claude / "settings.json"
            prov = claude / setup_permissions.PROVENANCE_NAME
            assert e.install(local) == 0
            prov.unlink()
            assert e.install(local) == 0     # every entry present: a record of none
            record = setup_permissions.read_provenance(local)
            assert record["settings_file"] == "settings.local.json", record
            assert not setup_permissions._has_entries(record), record
            before = _snapshot(tmp)
            rc, out = m.run(*e.install_args(target))
            assert rc == 1, out
            assert out == (f"this directory's install record names {local}: "
                           f"run --install --target {local}, "
                           f"or --remove --target {local} first\n"), out
            assert not target.exists(), out
            assert _snapshot(tmp) == before, out
            # the advice of the line succeeds
            rc, out = m.run("--remove", "--target", str(local))
            assert rc == 0, out
            assert not prov.exists(), out
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            assert json.loads(prov.read_text(encoding="utf-8"))["settings_file"] == \
                "settings.json"


# ── (W6-4) a run that changes the record alone says so ──────────────────────
def test_a_run_that_changes_the_record_alone_says_so():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            target = tmp / "proj" / ".claude" / "settings.json"
            prov = target.parent / setup_permissions.PROVENANCE_NAME
            rc, out = m.run(*e.install_args(target))     # a run that adds entries
            assert rc == 0, out
            assert "install record of" not in out, out
            _make_v1_record(prov)            # a record of the shipped version
            settings_before, record_before = target.read_bytes(), prov.read_bytes()
            rc, out = m.run(*e.install_args(target), "--dry-run")
            assert rc == 0, out
            assert f"would update the install record of {target}\n" in out, out
            assert f"updated the install record of {target}\n" not in out, out
            assert target.read_bytes() == settings_before, out
            assert prov.read_bytes() == record_before, out
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            assert f"updated the install record of {target}\n" in out, out
            assert "would update" not in out, out
            assert target.read_bytes() == settings_before, out
            assert json.loads(prov.read_text(encoding="utf-8"))["settings_file"] == \
                "settings.json"
            # up to date: neither line
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            assert "already up to date" in out and "install record of" not in out, out


# ── (W7-1) a run that changes the record alone does not write the settings file
def _rewrite_by_hand(target: Path) -> bytes:
    """The settings file in another form than the script writes: four spaces of
    indentation, Korean characters in an entry of the user's own (escaped in
    this source, written as UTF-8), mode 0644."""
    data = json.loads(target.read_text(encoding="utf-8"))
    data["env"]["MY_NOTE"] = "\uc548\ub155\ud558\uc138\uc694"
    raw = (json.dumps(data, indent=4, ensure_ascii=False) + "\n").encode("utf-8")
    target.write_bytes(raw)
    target.chmod(0o644)
    return raw


def test_a_run_that_changes_the_record_alone_leaves_the_settings_file_as_it_is():
    for record in ("of the shipped version", "none"):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Env(tmp) as e, _Machine(tmp) as m:
                target = tmp / "proj" / ".claude" / "settings.json"
                prov = target.parent / setup_permissions.PROVENANCE_NAME
                rc, out = m.run(*e.install_args(target))   # every entry of the plugin
                assert rc == 0, out
                raw = _rewrite_by_hand(target)
                if record == "none":
                    prov.unlink()
                else:
                    _make_v1_record(prov)                   # lists the entries, no file
                inode = target.stat().st_ino
                rc, out = m.run(*e.install_args(target))
                assert rc == 0, (record, out)
                assert f"updated the install record of {target}\n" in out, (record, out)
                assert target.read_bytes() == raw, (record, target.read_text("utf-8"))
                st = target.stat()
                assert stat.S_IMODE(st.st_mode) == 0o644, (record, oct(st.st_mode))
                assert st.st_ino == inode, record
                assert json.loads(prov.read_text(encoding="utf-8"))["settings_file"] == \
                    "settings.json", record


# ── (W7-2) --remove says that it removes a record ───────────────────────────
def test_remove_says_that_it_removes_the_record():
    for record in ("lists nothing", "entries gone by hand", "none"):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Env(tmp) as e, _Machine(tmp) as m:
                claude = tmp / "proj" / ".claude"
                target = claude / "settings.json"
                prov = claude / setup_permissions.PROVENANCE_NAME
                if record == "entries gone by hand":
                    assert e.install(target) == 0
                    assert setup_permissions._has_entries(
                        setup_permissions.read_provenance(target))
                elif record == "lists nothing":
                    _empty_record(claude)
                _touch(target, '{"model": "opus"}\n')
                nothing = f"nothing to remove: no managed entries at {target}\n"
                rc, out = m.run("--remove", "--dry-run", "--target", str(target))
                assert rc == 0, (record, out)
                if record == "none":
                    assert out == nothing, (record, out)
                else:
                    assert out == nothing + f"would remove the install record of " \
                        f"{target}\n", (record, out)
                    assert prov.exists(), record
                rc, out = m.run("--remove", "--target", str(target))
                assert rc == 0, (record, out)
                if record == "none":
                    assert out == nothing, (record, out)
                else:
                    assert out == nothing + f"removed the install record of " \
                        f"{target}\n", (record, out)
                assert not prov.exists(), record
                assert target.read_text(encoding="utf-8") == '{"model": "opus"}\n'


# ── (W7-3) a group of the user's that was empty stays ───────────────────────
def test_an_empty_group_of_the_users_stays():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            empty = {"matcher": "Bash", "hooks": []}
            original = {"hooks": {"PreToolUse": [empty]}}
            target = _touch(tmp / "proj" / ".claude" / "settings.json",
                            json.dumps(original))
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            _plant_an_earlier_versions_hook(target)
            assert json.loads(target.read_text(encoding="utf-8"))["hooks"] == \
                {"PreToolUse": [empty, LEGACY_GROUP]}
            # the install takes the earlier version's group out, the user's stays
            rc, out = m.run(*e.install_args(target))
            assert rc == 0, out
            assert json.loads(target.read_text(encoding="utf-8"))["hooks"] == \
                {"PreToolUse": [empty]}, out
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert json.loads(target.read_text(encoding="utf-8")) == original, out


# ── (W8-1) the ordinary branch of --remove says what it removes ─────────────
def test_remove_names_the_settings_file_and_the_record_it_removes():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            claude = tmp / "proj" / ".claude"
            target = claude / "settings.json"
            prov = claude / setup_permissions.PROVENANCE_NAME
            # every entry of the plugin's
            count = f"{len(_every_plugin_entry(e))} authored entries from {target}\n"
            # the install creates the settings file: --remove deletes it
            assert e.install(target) == 0
            before = _snapshot(tmp)
            rc, out = m.run("--remove", "--dry-run", "--target", str(target))
            assert rc == 0, out
            assert out == (f"would remove {count}would remove {target}\n"
                           f"would remove the install record of {target}\n"), out
            assert _snapshot(tmp) == before, out
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert out == (f"removed {count}removed {target}\n"
                           f"removed the install record of {target}\n"), out
            assert os.listdir(claude) == [], os.listdir(claude)
            # a settings file with an entry of the user's stays
            _touch(target, json.dumps(USER_CONTENT, indent=2))
            assert e.install(target) == 0
            rc, out = m.run("--remove", "--dry-run", "--target", str(target))
            assert rc == 0, out
            assert out == (f"would remove {count}"
                           f"would remove the install record of {target}\n"), out
            rc, out = m.run("--remove", "--target", str(target))
            assert rc == 0, out
            assert out == (f"removed {count}"
                           f"removed the install record of {target}\n"), out
            assert json.loads(target.read_text(encoding="utf-8")) == USER_CONTENT
            assert not prov.exists(), out


# ── (W8-2) entries taken out by hand: --remove clears what the install created
def test_remove_clears_the_empty_containers_the_install_created():
    empty = {"permissions": {"allow": []}, "sandbox": {"excludedCommands": []},
             "env": {}}
    for case in ("the install created the file", "the user's entry",
                 "no container left"):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Env(tmp) as e, _Machine(tmp) as m:
                claude = tmp / "proj" / ".claude"
                target = claude / "settings.json"
                prov = claude / setup_permissions.PROVENANCE_NAME
                if case != "the install created the file":
                    _touch(target, json.dumps(USER_CONTENT, indent=2))
                assert e.install(target) == 0
                # the user takes every entry of the plugin's out by hand
                if case == "the install created the file":
                    _touch(target, json.dumps(empty, indent=2))
                elif case == "the user's entry":
                    _touch(target, json.dumps(
                        {**USER_CONTENT, "sandbox": {"excludedCommands": []}},
                        indent=2))
                else:
                    target.write_bytes(
                        (json.dumps(USER_CONTENT, indent=4) + "\n").encode("utf-8"))
                    target.chmod(0o644)
                raw, inode = target.read_bytes(), target.stat().st_ino
                done = {"the install created the file": f"{target}\n",
                        "the user's entry": "the empty containers the install "
                                            f"created from {target}\n",
                        "no container left": None}[case]
                # (W9-2) a run that removed something does not say `nothing to remove`
                tail = (f"no managed entries were left in {target}\n" if done else
                        f"nothing to remove: no managed entries at {target}\n")
                before = _snapshot(tmp)
                rc, out = m.run("--remove", "--dry-run", "--target", str(target))
                assert rc == 0, (case, out)
                assert out == (f"would remove {done}" if done else "") + tail + \
                    f"would remove the install record of {target}\n", (case, out)
                assert _snapshot(tmp) == before, (case, out)
                rc, out = m.run("--remove", "--target", str(target))
                assert rc == 0, (case, out)
                assert out == (f"removed {done}" if done else "") + tail + \
                    f"removed the install record of {target}\n", (case, out)
                assert not prov.exists(), case
                if case == "the install created the file":
                    assert os.listdir(claude) == [], os.listdir(claude)
                elif case == "the user's entry":
                    assert json.loads(target.read_text(encoding="utf-8")) == \
                        USER_CONTENT, target.read_text(encoding="utf-8")
                else:
                    assert target.read_bytes() == raw, case
                    st = target.stat()
                    assert stat.S_IMODE(st.st_mode) == 0o644, oct(st.st_mode)
                    assert st.st_ino == inode, case


# ── (W9-1) a settings file the install created, emptied by hand, goes too ────
def test_remove_deletes_a_settings_file_the_install_created_emptied_by_hand():
    for case in ("{}", "zero bytes", "the user's file", "deleted"):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Env(tmp) as e, _Machine(tmp) as m:
                claude = tmp / "proj" / ".claude"
                target = claude / "settings.json"
                prov = claude / setup_permissions.PROVENANCE_NAME
                if case == "the user's file":
                    _touch(target, json.dumps(USER_CONTENT, indent=2))
                assert e.install(target) == 0
                if case == "deleted":
                    # the user deletes the file the install created: the
                    # branch stays silent about it and only drops the record
                    target.unlink()
                    tail = f"nothing to remove: no managed entries at {target}\n"
                    before = _snapshot(tmp)
                    rc, out = m.run("--remove", "--dry-run", "--target", str(target))
                    assert (rc, out) == (0, tail + "would remove the install "
                                         f"record of {target}\n"), (case, out)
                    assert _snapshot(tmp) == before, (case, out)
                    rc, out = m.run("--remove", "--target", str(target))
                    assert (rc, out) == (0, tail + "removed the install "
                                         f"record of {target}\n"), (case, out)
                    assert os.listdir(claude) == [], (case, os.listdir(claude))
                    continue
                # the user empties the file by hand
                target.write_bytes(b"" if case == "zero bytes" else b"{}\n")
                target.chmod(0o644)
                raw, inode = target.read_bytes(), target.stat().st_ino
                ours = case != "the user's file"
                tail = (f"no managed entries were left in {target}\n" if ours else
                        f"nothing to remove: no managed entries at {target}\n")
                before = _snapshot(tmp)
                rc, out = m.run("--remove", "--dry-run", "--target", str(target))
                assert rc == 0, (case, out)
                assert out == (f"would remove {target}\n" if ours else "") + tail + \
                    f"would remove the install record of {target}\n", (case, out)
                assert _snapshot(tmp) == before, (case, out)
                rc, out = m.run("--remove", "--target", str(target))
                assert rc == 0, (case, out)
                assert out == (f"removed {target}\n" if ours else "") + tail + \
                    f"removed the install record of {target}\n", (case, out)
                assert not prov.exists(), case
                if ours:
                    assert os.listdir(claude) == [], (case, os.listdir(claude))
                else:
                    assert target.read_bytes() == raw, case
                    st = target.stat()
                    assert stat.S_IMODE(st.st_mode) == 0o644, oct(st.st_mode)
                    assert st.st_ino == inode, case


# ── (A7) an unlinked lock file cannot split the lock ─────────────────────────
def _same_inode(fd: int, path: Path) -> bool:
    st, fst = os.stat(path, follow_symlinks=False), os.fstat(fd)
    return (st.st_dev, st.st_ino) == (fst.st_dev, fst.st_ino)


def test_open_lock_follows_an_unlinked_lock_file():
    with tempfile.TemporaryDirectory() as t:
        target = Path(t) / "proj" / ".claude" / "settings.json"
        lock = target.parent / setup_permissions.LOCK_NAME
        # a released, unlinked lock: a fresh open takes the path's inode
        fd1 = setup_permissions._open_lock(target)
        setup_permissions._release_lock(fd1, lock)
        fd2 = setup_permissions._open_lock(target)
        try:
            assert _same_inode(fd2, lock)
        finally:
            setup_permissions._release_lock(fd2)
        # a waiter blocked on the old inode while the holder unlinks and releases
        # ends up on the inode the path names now, not on the unlinked one
        holder = setup_permissions._open_lock(target)
        blocking = threading.Event()
        real = setup_permissions.fcntl

        class _Shim:
            LOCK_EX, LOCK_UN = real.LOCK_EX, real.LOCK_UN

            @staticmethod
            def flock(fd, op):
                if op == real.LOCK_EX:
                    blocking.set()
                real.flock(fd, op)

        def _unlink_and_release():
            blocking.wait()
            setup_permissions._release_lock(holder, lock)

        worker = threading.Thread(target=_unlink_and_release)
        worker.start()
        setup_permissions.fcntl = _Shim
        try:
            waiter = setup_permissions._open_lock(target)
        finally:
            setup_permissions.fcntl = real
            worker.join()
        try:
            assert lock.exists(), "the waiter holds a lock on an unlinked file"
            assert _same_inode(waiter, lock)
        finally:
            setup_permissions._release_lock(waiter)


# ── (A8) a lock file --remove created is removed when the run errors ─────────
def test_remove_error_removes_only_a_lock_it_created():
    for lock_before in (False, True):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Env(tmp) as e, _Machine(tmp) as m:
                target = tmp / "proj" / ".claude" / "settings.json"
                assert e.install(target) == 0
                target.write_text("{ not json", encoding="utf-8")
                lock = target.parent / setup_permissions.LOCK_NAME
                if not lock_before:
                    lock.unlink()
                rc, out = m.run("--remove", "--target", str(target))
                assert rc == 1, out
                assert lock.exists() == lock_before, (lock_before, out)


# ── (B1) --uninstall-machine removes every machine item and says so ──────────
def test_uninstall_machine_removes_every_item():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            items = _plant_machine(m)
            g = m.home / ".gemini"
            foreign = [_touch(g / "config" / "agents" / "my-own-agent.md"),
                       _touch(g / "antigravity-cli" / "settings.json", "{}"),
                       _touch(m.systmp / "unrelated.txt")]
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            for name, path in items.items():
                assert not path.exists(), f"{name} survived: {path}\n{out}"
            for path in (items["patches"], items["agent_review"], items["agy_lock"]):
                assert f"removed {path}" in out, f"no 'removed {path}' line:\n{out}"
            for gone in (m.config / "triad-dispatch",
                         g / "antigravity-cli" / "triad-daily", g / "triad-daily"):
                assert not gone.exists(), f"{gone} not removed\n{out}"
            for kept in foreign:
                assert kept.exists(), f"a file that is not the plugin's was removed: {kept}"


# ── (B2) nothing present -> nothing created, rc 0 ────────────────────────────
def test_uninstall_machine_nothing_present_creates_nothing():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            before = _snapshot(tmp)
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            assert _snapshot(tmp) == before, "the uninstall created something"


# ── (B3) a location moved by an environment variable is the user's ───────────
def test_uninstall_machine_leaves_env_override_locations():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            ext = _touch(tmp / "mine" / "patches.json", "{}")
            agyd = _touch(tmp / "mine" / "agyd" / "report.md").parent
            gemd = _touch(tmp / "mine" / "gemd" / "report.md").parent
            os.environ["TRIAD_CLASSIFIER_EXTENSION"] = str(ext)
            os.environ["AGY_DAILY_STATE"] = str(agyd)
            os.environ["GEMINI_DAILY_STATE"] = str(gemd)
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            for path, var in ((ext, "TRIAD_CLASSIFIER_EXTENSION"),
                              (agyd, "AGY_DAILY_STATE"), (gemd, "GEMINI_DAILY_STATE")):
                assert path.exists(), f"{path} (set by {var}) was removed"
                assert f"left {path}: set by {var} (yours)" in out, out
            assert (agyd / "report.md").exists() and (gemd / "report.md").exists()


# ── (B4) the agy settings lock stays while a transaction is recorded ─────────
def test_uninstall_machine_leaves_agy_lock_with_transaction_state():
    for state in (".agybak", ".agy_settings.shared.json"):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            with _Machine(tmp) as m:
                cli = m.home / ".gemini" / "antigravity-cli"
                lock = _touch(cli / ".agy_settings.lock", "")
                recorded = _touch(cli / state)
                rest = [_touch(cli / ".agybak.tmp"),
                        _touch(cli / ".agy_settings.shared.json.tmp"),
                        _touch(cli / ".agy_settings.holders" / "tok123.lock")]
                rc, out = m.run("--uninstall-machine")
                assert rc == 0, out
                assert lock.exists(), f"lock removed beside {state}"
                assert recorded.exists(), f"{state} removed"
                for path in rest:
                    assert path.exists(), f"{path} removed beside {state}\n{out}"
                assert (f"left {lock}: an agy settings transaction is recorded"
                        in out), out
                # the advice that heals a hardened install (a read-only
                # dispatch never enters the settings guard)
                assert "antigravity_wrapper.py --setup-agents once" in out, out
                assert "then run --uninstall-machine again" in out, out
                assert "run one agy dispatch" not in out, out


# ── (B15) no transaction recorded: the empty holders dir goes, settings.json.tmp stays
def test_uninstall_machine_agy_residue_without_transaction():
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            cli = m.home / ".gemini" / "antigravity-cli"
            lock = _touch(cli / ".agy_settings.lock", "")
            holders = cli / ".agy_settings.holders"
            holders.mkdir()
            not_ours = _touch(cli / "settings.json.tmp", "{}")
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            assert not lock.exists() and not holders.exists(), out
            assert f"removed {holders}" in out, out
            assert not_ours.exists(), "settings.json.tmp is not the plugin's alone"


# ── (B17) temp files and holder files alone are no recorded transaction ──────
def test_uninstall_machine_agy_temp_and_holder_files_are_no_transaction():
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            cli = m.home / ".gemini" / "antigravity-cli"
            lock = _touch(cli / ".agy_settings.lock", "")
            tmp_file = _touch(cli / ".agybak.tmp")
            holder = _touch(cli / ".agy_settings.holders" / "tok123.lock")
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            for path in (lock, tmp_file, holder, holder.parent):
                assert not path.exists(), f"{path} survived\n{out}"
            assert "an agy settings transaction is recorded" not in out, out
            assert "--setup-agents" not in out, out


# ── (B19) every item of a recorded agy transaction that exists gets its line ─
def test_uninstall_machine_names_every_item_of_a_recorded_agy_transaction():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            cli = m.home / ".gemini" / "antigravity-cli"
            lock = _touch(cli / ".agy_settings.lock", "")
            present = [_touch(cli / ".agybak"), _touch(cli / ".agy_settings.shared.json"),
                       _touch(cli / ".agy_settings.holders" / "tok123.lock").parent]
            absent = [cli / ".agybak.tmp", cli / ".agy_settings.shared.json.tmp"]
            before = _snapshot(tmp)
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            assert _snapshot(tmp) == before, out
            assert f"left {lock}: an agy settings transaction is recorded" in out, out
            for path in present:
                assert (f"left {path}: part of the recorded agy settings transaction\n"
                        in out), out
            for path in absent:
                assert f"left {path}:" not in out, out


# ── (B20) no usable temporary directory: reported, and the run goes on ───────
def test_uninstall_machine_without_a_usable_temporary_directory():
    class _NoTemp:
        @staticmethod
        def gettempdir():
            raise FileNotFoundError(2, "No usable temporary directory found")

    for tmpdir_set in (True, False):
        with tempfile.TemporaryDirectory() as t:
            with _Machine(Path(t)) as m:
                if not tmpdir_set:
                    os.environ.pop("TMPDIR")
                real = setup_permissions.tempfile
                setup_permissions.tempfile = _NoTemp
                try:
                    rc, out = m.run("--uninstall-machine")
                finally:
                    setup_permissions.tempfile = real
                where = m.systmp if tmpdir_set else "the temporary directory"
                assert rc == 0, out
                assert f"left {where}: No usable temporary directory found\n" in out, out
                assert out.endswith("machine-scope clean-up finished\n"), out


# ── (B16) AGY_SETTINGS_PATH moves the agy settings: its directory is the user's
def test_uninstall_machine_reports_agy_settings_path():
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            moved = _touch(m.tmp / "mine" / "agy" / ".agy_settings.lock", "")
            os.environ["AGY_SETTINGS_PATH"] = str(moved.parent / "settings.json")
            lock = _touch(m.home / ".gemini" / "antigravity-cli" / ".agy_settings.lock", "")
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            assert f"left {moved.parent}: set by AGY_SETTINGS_PATH (yours)" in out, out
            assert moved.exists(), out
            assert not lock.exists(), "the default location is still handled"


# ── (B5) a symlinked item is left, and its target is untouched ───────────────
def test_uninstall_machine_leaves_symlinks():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            real = _touch(tmp / "elsewhere" / "real.json", "{}")
            real_dir = _touch(tmp / "elsewhere" / "daily" / "report.md").parent
            link = m.config / "triad-dispatch" / "classifier-patches.json"
            link.parent.mkdir(parents=True)
            os.symlink(real, link)
            dlink = m.home / ".gemini" / "triad-daily"
            dlink.parent.mkdir(parents=True)
            os.symlink(real_dir, dlink)
            tlink = m.systmp / "codex_last_1_zzzzzzzz.txt"
            os.symlink(real, tlink)
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            for p in (link, dlink, tlink):
                assert p.is_symlink(), f"symlink removed: {p}"
            for p in (link, dlink):
                assert f"left {p}: symlink" in out, out
            assert f"left {tlink}{TEMP_LEFT}" in out, out
            assert real.exists() and (real_dir / "report.md").exists()


# ── (B6) a foreign file keeps ~/.config/triad-dispatch/ ──────────────────────
def test_uninstall_machine_keeps_dir_with_foreign_file():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            d = m.config / "triad-dispatch"
            patches = _touch(d / "classifier-patches.json", "{}")
            mine = _touch(d / "notes.txt")
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            assert not patches.exists()
            assert mine.exists() and d.is_dir()
            assert f"left {d}: not empty" in out, out


# ── (B7) --uninstall-machine --dry-run removes nothing ───────────────────────
def test_uninstall_machine_dry_run_changes_nothing():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            items = _plant_machine(m)
            before = _snapshot(tmp)
            rc, out = m.run("--uninstall-machine", "--dry-run")
            assert rc == 0, out
            assert _snapshot(tmp) == before, "a dry run changed the tree"
            assert f"would remove {items['patches']}" in out, out
            assert "removed " not in out, out


# ── (B10) nothing is removed in the shared temp dir: what matches is listed ──
def test_uninstall_machine_removes_nothing_in_the_shared_temp_dir():
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            items = _plant_temp(m)
            unrelated = _touch(m.systmp / "codex_last_notes.txt")
            _age(unrelated)
            before = _snapshot(m.systmp)
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            assert _snapshot(m.systmp) == before, out
            for name, p in items.items():
                assert f"left {p}{TEMP_LEFT}" in out, f"{name}: no line\n{out}"
            assert str(unrelated) not in out, out


# ── (B11) the config home follows the engine: XDG_CONFIG_HOME when set, else ~/.config
def test_uninstall_machine_config_home_follows_the_engine():
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            os.environ.pop("XDG_CONFIG_HOME")
            home_patch = _touch(m.home / ".config" / "triad-dispatch" / "classifier-patches.json", "{}")
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            assert not home_patch.exists() and not home_patch.parent.exists(), out
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            os.environ["XDG_CONFIG_HOME"] = "relative/config"
            before = _snapshot(m.tmp)
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            assert "left relative/config/triad-dispatch: XDG_CONFIG_HOME is relative" in out, out
            assert _snapshot(m.tmp) == before, "a relative XDG_CONFIG_HOME run changed the tree"


# ── (B13) one item that cannot be removed does not stop the uninstall ────────
def test_uninstall_machine_continues_past_an_item_it_cannot_remove():
    if os.geteuid() == 0:
        print("skip test_uninstall_machine_continues_past_an_item_it_cannot_remove: root")
        return
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            stuck = _touch(m.config / "triad-dispatch" / "classifier-patches.json", "{}")
            later = _touch(m.home / ".gemini" / "config" / "agents"
                           / "triad-readonly-review.md")
            stuck.parent.chmod(0o500)
            try:
                rc, out = m.run("--uninstall-machine")
            finally:
                stuck.parent.chmod(0o700)
            assert rc == 0, out
            assert stuck.exists(), out
            assert f"left {stuck}: " in out and "ermission denied" in out, out
            assert not later.exists(), out
            assert f"removed {later}" in out, out


# ── (B19) a directory that cannot be examined is reported, not taken as absent
def test_a_directory_that_cannot_be_examined_is_reported():
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            locked = m.config / "triad-dispatch"
            patches = _touch(locked / "classifier-patches.json", "{}")
            real_lstat = os.lstat

            def lstat(path, *args, **kwargs):
                if os.fspath(path) == str(locked):
                    raise PermissionError(13, "Permission denied", str(locked))
                return real_lstat(path, *args, **kwargs)

            setup_permissions.os.lstat = lstat
            try:
                rc, out = m.run("--uninstall-machine")
            finally:
                setup_permissions.os.lstat = real_lstat
            assert rc == 0, out
            assert f"left {locked}: Permission denied\n" in out, out
            assert patches.exists(), out
            assert out.endswith("machine-scope clean-up finished\n"), out
    # a path that does not exist, or whose parent is a file: no line
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            _touch(m.home / ".gemini", "a file, not a directory")
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            for d in (m.config / "triad-dispatch", m.home / ".gemini" / "config" / "agents",
                      m.home / ".gemini" / "antigravity-cli"):
                assert f"left {d}" not in out, out


# ── (B18) a directory that cannot be listed does not end the run ─────────────
def test_a_directory_that_cannot_be_listed_does_not_end_the_run():
    if os.geteuid() == 0:
        print("skip test_a_directory_that_cannot_be_listed_does_not_end_the_run: "
              "root lists a directory without read permission all the same")
        return
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e, _Machine(tmp) as m:
            locked = m.config / "triad-dispatch"
            patches = _touch(locked / "classifier-patches.json", "{}")
            later = _touch(m.home / ".gemini" / "config" / "agents"
                           / "triad-readonly-review.md")
            target = tmp / "proj" / ".claude" / "settings.json"
            assert e.install(target) == 0
            locked.chmod(0o300)
            target.parent.chmod(0o300)
            try:
                rc, out = m.run("--uninstall-machine")
                rc_remove, out_remove = m.run("--remove", "--target", str(target))
            finally:
                locked.chmod(0o700)
                target.parent.chmod(0o700)
            assert rc == 0, out
            assert f"left {locked}: " in out and "ermission denied" in out, out
            assert patches.exists(), out
            assert not later.exists() and f"removed {later}" in out, out
            assert rc_remove == 0, out_remove
            assert f"left {target.parent}: " in out_remove, out_remove
            assert not target.exists(), out_remove


# ── (B14) temp names match the exact shapes the wrappers create ──────────────
def test_temp_names_match_the_wrapper_shapes_only():
    candidates = (_TESTS_DIR.parent / "bin" / "codex_wrapper.py",  # export
                  _TESTS_DIR.parent / "codex_wrapper.py")          # source
    wrapper = next((c for c in candidates if c.is_file()), None)
    assert wrapper is not None, f"codex_wrapper.py not found: {candidates}"
    text = wrapper.read_text(encoding="utf-8")
    for call in ('prefix=f"codex_last_{os.getpid()}_", suffix=".txt"',
                 'prefix=f"codex_schema_{os.getpid()}_", suffix=".json"'):
        assert call in text, f"the wrapper's temp name changed: {call}"
    # the 8 random characters tempfile appends
    assert set(tempfile._RandomNameSequence.characters) == set(
        "abcdefghijklmnopqrstuvwxyz0123456789_")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Machine(tmp) as m:
            shapes = [_touch(m.systmp / "codex_last_901_x7y8z9w0.txt"),
                      _touch(m.systmp / "codex_schema_901_k_l_m_n_.json")]
            # a report dir of the removed codex `--task` mode is no wrapper name now
            others = [_touch(m.systmp / "codex_report_ab_1cd2e" / "synthesis.md").parent,
                      _touch(m.systmp / "codex_last_notes.txt"),
                      _touch(m.systmp / "codex_schema_mine.json"),
                      _touch(m.systmp / "codex_schema_901_k_l_m_n_X.json")]
            _age(*shapes, *others)
            rc, out = m.run("--uninstall-machine")
            assert rc == 0, out
            for p in shapes:
                assert f"left {p}{TEMP_LEFT}" in out, f"{p}: no line\n{out}"
            for p in others:
                assert f"left {p}:" not in out, f"{p} is not a wrapper temp name\n{out}"
            # this script's own stray temp names in a project's .claude/
            claude = tmp / "proj" / ".claude"
            strays = [_touch(claude / ".settings.a1b2c3d4.json.tmp"),
                      _touch(claude / ".triad-prov.a1b2c3d4.json.tmp")]
            kept = [_touch(claude / ".settings.backup.json.tmp"),
                    _touch(claude / ".triad-prov.mine.json.tmp")]
            rc, out = m.run("--remove", "--target", str(tmp / "proj"))
            assert rc == 0, out
            assert not any(p.exists() for p in strays), os.listdir(claude)
            assert all(p.exists() for p in kept), os.listdir(claude)


# ── (B8) the agy agent names and dir match the wrapper's (drift guard) ───────
def test_agy_agent_names_match_the_wrapper():
    candidates = (_TESTS_DIR.parent / "bin" / "antigravity_wrapper.py",  # export
                  _TESTS_DIR.parent / "antigravity_wrapper.py")          # source
    wrapper = next((c for c in candidates if c.is_file()), None)
    assert wrapper is not None, f"antigravity_wrapper.py not found: {candidates}"
    text = wrapper.read_text(encoding="utf-8")
    names = tuple(re.search(rf'^{var} = "([^"]+)"$', text, re.M).group(1)
                  for var in ("AGY_REVIEW_AGENT", "AGY_RESEARCH_AGENT"))
    assert names == setup_permissions.AGY_AGENT_NAMES, (
        names, setup_permissions.AGY_AGENT_NAMES)
    assert 'Path.home() / ".gemini" / "config" / "agents"' in text, (
        "the wrapper's agents dir moved; update setup_permissions.py")


# ── (B9) --install / --remove / --uninstall-machine are mutually exclusive ───
def test_modes_are_mutually_exclusive():
    with tempfile.TemporaryDirectory() as t:
        with _Machine(Path(t)) as m:
            for pair in (("--install", "--uninstall-machine"),
                         ("--remove", "--uninstall-machine"),
                         ("--install", "--remove")):
                rc, out = m.run(*pair)
                assert rc == 2, (pair, rc, out)
                assert "not allowed with argument" in out, (pair, out)


TESTS = [
    test_fresh_install_writes_basename_grants_and_hardening,
    test_second_install_is_idempotent,
    test_directory_target_resolves,
    test_preserves_unrelated_keys_and_existing_allow,
    test_preserves_existing_sandbox_key,
    test_output_is_valid_json,
    test_malformed_json_is_error_not_clobber,
    test_malformed_allow_list_clean_error,
    test_install_remove_round_trip,
    test_symlinked_settings_refused,
    test_takes_out_the_recorded_pretooluse_hook_of_an_earlier_version,
    test_preserves_user_pretooluse_hook,
    test_reinstall_over_an_earlier_version_keeps_the_users_hook,
    test_user_entries_already_present_survive_install_and_remove,
    test_install_writes_no_hook,
    test_install_removes_the_hook_an_earlier_version_wrote,
    test_install_runs_without_a_hooks_directory,
    test_remove_without_claude_dir_creates_nothing,
    test_remove_empty_record_deletes_provenance,
    test_remove_with_absent_settings_does_not_create_it,
    test_install_remove_leaves_no_sidecar,
    test_remove_dry_run_changes_nothing,
    test_remove_other_target_is_refused,
    test_install_into_a_second_settings_file_is_refused,
    test_version1_record_without_settings_file,
    test_version1_record_install_into_a_file_without_its_entries_is_refused,
    test_version1_record_with_no_entry_left_names_both_ways_out,
    test_the_record_is_written_first_and_an_interrupted_first_install_is_repaired,
    test_install_interrupted_before_the_settings_write_is_removable,
    test_plugin_update_interrupted_after_the_settings_write_is_repaired,
    test_entries_in_no_record_are_named,
    test_remove_names_every_entry_of_the_plugins_in_no_record,
    test_a_record_of_every_entry_gets_no_note,
    test_remove_of_a_record_without_entries_goes_on_past_an_unreadable_settings_file,
    test_a_hook_joined_to_a_shell_operator_is_named,
    test_a_hook_of_an_earlier_version_is_named_and_left,
    test_a_users_own_hook_gets_no_line,
    test_remove_of_a_record_without_entries_that_names_another_file_is_refused,
    test_a_container_that_is_no_object_holds_no_entry,
    test_every_env_key_the_install_writes_is_named,
    test_install_dry_run_names_the_hook_path_it_would_remove,
    test_a_container_of_another_type_than_the_host_reads_holds_no_entry,
    test_install_dry_run_creates_no_directory_and_no_lock_file,
    test_install_beside_a_record_without_entries_that_names_another_file_is_refused,
    test_a_run_that_changes_the_record_alone_says_so,
    test_a_run_that_changes_the_record_alone_leaves_the_settings_file_as_it_is,
    test_remove_says_that_it_removes_the_record,
    test_an_empty_group_of_the_users_stays,
    test_remove_names_the_settings_file_and_the_record_it_removes,
    test_remove_clears_the_empty_containers_the_install_created,
    test_remove_deletes_a_settings_file_the_install_created_emptied_by_hand,
    test_open_lock_follows_an_unlinked_lock_file,
    test_remove_error_removes_only_a_lock_it_created,
    test_uninstall_machine_removes_every_item,
    test_uninstall_machine_nothing_present_creates_nothing,
    test_uninstall_machine_leaves_env_override_locations,
    test_uninstall_machine_leaves_agy_lock_with_transaction_state,
    test_uninstall_machine_agy_residue_without_transaction,
    test_uninstall_machine_agy_temp_and_holder_files_are_no_transaction,
    test_uninstall_machine_names_every_item_of_a_recorded_agy_transaction,
    test_uninstall_machine_without_a_usable_temporary_directory,
    test_uninstall_machine_reports_agy_settings_path,
    test_uninstall_machine_leaves_symlinks,
    test_uninstall_machine_keeps_dir_with_foreign_file,
    test_uninstall_machine_dry_run_changes_nothing,
    test_uninstall_machine_removes_nothing_in_the_shared_temp_dir,
    test_uninstall_machine_config_home_follows_the_engine,
    test_uninstall_machine_continues_past_an_item_it_cannot_remove,
    test_a_directory_that_cannot_be_examined_is_reported,
    test_a_directory_that_cannot_be_listed_does_not_end_the_run,
    test_temp_names_match_the_wrapper_shapes_only,
    test_agy_agent_names_match_the_wrapper,
    test_modes_are_mutually_exclusive,
]


def main() -> int:
    failures = 0
    for test in TESTS:
        try:
            test()
            print(f"ok   {test.__name__}")
        except Exception:  # noqa: BLE001 — a test harness reports every failure
            failures += 1
            print(f"FAIL {test.__name__}")
            traceback.print_exc()
    total = len(TESTS)
    print(f"{total - failures}/{total} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
