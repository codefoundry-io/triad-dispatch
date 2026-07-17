#!/usr/bin/env python3
"""Tests for the claude-host permission-setup script (stdlib-only, no pytest).

Covers the redesigned merge / provenance / --remove / hardening / robustness
contract of `setup_permissions.py`:
  (1) a fresh --install writes the bare BASENAME wrapper grants (matching the bare
      invocation the dispatch SKILLs emit so dispatch stays promptless; the
      PreToolUse hook, not the grant, is the security gate — vendor-recommended),
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

import importlib.util
import json
import os
import stat
import sys
import tempfile
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


def _make_hooks(tmp: Path) -> Path:
    """A fake plugin hooks/ holding the PreToolUse guard (install requires it)."""
    h = tmp / "plugin" / "hooks"
    h.mkdir(parents=True)
    (h / "pretooluse_wrapper_guard.py").write_text(
        "#!/usr/bin/env python3\n", encoding="utf-8")
    return h


class _Env:
    """Context manager: fake vendors on PATH + fake bin/ + fake hooks/ + a work
    root, restoring os.environ['PATH'] on exit."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.bin = _make_bin(tmp)
        self.hooks = _make_hooks(tmp)
        self.vbin = _make_vendor_path(tmp)
        self.work = tmp / "work"
        self.work.mkdir()
        self._saved_path = os.environ.get("PATH", "")

    def __enter__(self):
        os.environ["PATH"] = f"{self.vbin}{os.pathsep}{self._saved_path}"
        return self

    def __exit__(self, *exc):
        os.environ["PATH"] = self._saved_path

    def install(self, target: Path, extra=()):
        return setup_permissions.main(
            ["--install", "--target", str(target), "--bin-dir", str(self.bin),
             "--hooks-dir", str(self.hooks),
             "--allowed-roots", str(self.work), *extra]
        )

    def remove(self, target: Path, extra=()):
        return setup_permissions.main(["--remove", "--target", str(target), *extra])


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


# ── (11) the PreToolUse hook is registered (authored + provenance) + removed ──
def test_registers_and_removes_pretooluse_hook():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        with _Env(tmp) as e:
            target = tmp / "proj" / ".claude" / "settings.json"
            assert e.install(target) == 0
            data = json.loads(target.read_text(encoding="utf-8"))
            pretool = data["hooks"]["PreToolUse"]
            cmds = [h.get("command", "")
                    for g in pretool if isinstance(g, dict)
                    for h in (g.get("hooks") or []) if isinstance(h, dict)]
            assert any("pretooluse_wrapper_guard.py" in c for c in cmds), pretool
            # the matcher-group targets Bash tool calls
            assert any(g.get("matcher") == "Bash" for g in pretool
                       if isinstance(g, dict)), pretool
            # provenance records the authored hook command (so --remove strips it)
            prov = json.loads(
                (target.parent / setup_permissions.PROVENANCE_NAME)
                .read_text(encoding="utf-8"))
            assert "pretooluse_wrapper_guard.py" in json.dumps(prov)
            # --remove strips the hook; since this install CREATED the settings
            # file (no pre-existing one), the byte-exact round-trip deletes it.
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
    test_registers_and_removes_pretooluse_hook,
    test_preserves_user_pretooluse_hook,
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
