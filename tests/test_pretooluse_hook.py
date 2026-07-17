#!/usr/bin/env python3
"""Unit tests for the claude-host PreToolUse wrapper-validation hook (stdlib-only,
no pytest).

The hook is the RELIABLE security gate for the claude-host product: the basename
Bash grant makes a legitimate dispatch promptless, and this hook is what actually
validates the invocation. It fires on a Bash tool call and, when the command
invokes a shipped wrapper (codex/gemini/antigravity wrapper), it:

  1. FOREIGN-SCRIPT REJECTION — resolves the invoked script the way the shell
     would (absolute/relative path, or PATH lookup for a bare basename) and DENIES
     when the resolved script is NOT the plugin's own wrapper (a foreign
     same-named script planted on PATH). This is the unique value only the hook
     can provide — the wrapper cannot self-defend against BEING a foreign script.
  2. ARG-GATING (defense-in-depth) — DENIES when --prompt-file / --image / --cwd
     points OUTSIDE the workspace roots (read from TRIAD_WRAPPER_ALLOWED_ROOTS),
     ALLOWS otherwise.
  3. PASS-THROUGH — a non-wrapper Bash command gets no opinion (ALLOW).

The decision logic lives in a PURE function `decide(command, roots, real_bin)`
that is unit-testable WITHOUT the Claude Code runtime. `main()` reads the
PreToolUse JSON on stdin and emits the documented `hookSpecificOutput`
allow/deny structure — exercised here by running the hook as a subprocess.

Dual-layout, like test_setup_permissions.py: the hook resolves via the plugin
`hooks/` sibling when present (exported plugin) or the source
`export_assets/claude-host/hooks/` tree.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

sys.dont_write_bytecode = True  # keep an installed plugin dir pristine

_TESTS_DIR = Path(__file__).resolve().parent
_HOOK_CANDIDATES = (
    # exported plugin layout: tests/ has a hooks/ sibling
    _TESTS_DIR.parent / "hooks" / "pretooluse_wrapper_guard.py",
    # source repo layout: the hook lives under export_assets/claude-host/hooks/
    _TESTS_DIR.parents[1]
    / "export_assets"
    / "claude-host"
    / "hooks"
    / "pretooluse_wrapper_guard.py",
)


def _load_hook():
    for candidate in _HOOK_CANDIDATES:
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "pretooluse_wrapper_guard", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.__file__ = str(candidate)  # ensure __file__ is set for the loader
            return module, candidate
    raise AssertionError(
        "pretooluse_wrapper_guard.py not found in any known layout: "
        + ", ".join(str(c) for c in _HOOK_CANDIDATES)
    )


hook, HOOK_PATH = _load_hook()
decide = hook.decide


# ── fixtures ─────────────────────────────────────────────────────────────────
def _real_bin(tmp: Path) -> Path:
    """A plugin bin/ holding the real wrapper scripts."""
    b = tmp / "plugin" / "bin"
    b.mkdir(parents=True)
    for name in ("codex_wrapper.py", "gemini_wrapper.py", "antigravity_wrapper.py"):
        f = b / name
        f.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return b


def _work_root(tmp: Path) -> Path:
    w = tmp / "work"
    w.mkdir()
    return w


# ── decide(): arg-gating ──────────────────────────────────────────────────────
def test_prompt_file_outside_roots_denies():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"python3 {rb}/codex_wrapper.py --prompt-file /etc/passwd"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)
        assert "prompt-file" in (reason or "") or "/etc/passwd" in (reason or "")


def test_prompt_file_inside_roots_allows():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        p = work / "p.txt"
        p.write_text("prompt", encoding="utf-8")
        cmd = f"python3 {rb}/codex_wrapper.py --prompt-file {p}"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "allow", (decision, reason)


def test_image_outside_roots_denies():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        outside = tmp / "outside" / "screen.png"
        cmd = f"python3 {rb}/codex_wrapper.py --prompt hi --image {outside}"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_cwd_outside_roots_denies():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        outside = tmp / "elsewhere"
        cmd = f"python3 {rb}/gemini_wrapper.py --cwd {outside} --prompt hi"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_equals_form_flag_outside_roots_denies():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"python3 {rb}/codex_wrapper.py --prompt-file=/etc/passwd"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_real_wrapper_safe_args_allows():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"python3 {rb}/codex_wrapper.py --prompt 'hello world'"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "allow", (decision, reason)


# ── decide(): foreign-script rejection ────────────────────────────────────────
def test_foreign_absolute_wrapper_denies():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("print('pwned')\n", encoding="utf-8")
        cmd = f"python3 {evil}/codex_wrapper.py --prompt hi"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)
        assert "foreign" in (reason or "").lower() or "not the plugin" in (reason or "").lower()


def test_foreign_bare_wrapper_on_path_denies():
    """A bare `codex_wrapper.py` resolving (via PATH) to a foreign script denies."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evilbin"
        evil.mkdir()
        f = evil / "codex_wrapper.py"
        f.write_text("print('pwned')\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
        saved = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{evil}{os.pathsep}{saved}"
        try:
            decision, reason = decide("codex_wrapper.py --prompt hi", [work], rb)
        finally:
            os.environ["PATH"] = saved
        assert decision == "deny", (decision, reason)


def test_real_bare_wrapper_on_path_allows():
    """A bare `codex_wrapper.py` resolving (via PATH) to the REAL plugin bin allows."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        # make the real bin executable-discoverable + first on PATH
        (rb / "codex_wrapper.py").chmod(
            (rb / "codex_wrapper.py").stat().st_mode | stat.S_IEXEC)
        saved = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{rb}{os.pathsep}{saved}"
        try:
            decision, reason = decide("codex_wrapper.py --prompt hi", [work], rb)
        finally:
            os.environ["PATH"] = saved
        assert decision == "allow", (decision, reason)


# ── decide(): smuggling — chained wrapper + bash -c payload (IMPORTANT-2) ─────
def test_chained_second_wrapper_denies():
    """A real FIRST wrapper && a FOREIGN second wrapper must DENY (every
    wrapper-looking token is validated, not just the first)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("print('pwned')\n", encoding="utf-8")
        cmd = (f"{rb}/codex_wrapper.py --prompt ok && "
               f"{evil}/codex_wrapper.py --prompt hi")
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_bash_c_payload_foreign_wrapper_denies():
    """`bash -c '<foreign wrapper> …'` must DENY (recursively parse the -c payload)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("print('pwned')\n", encoding="utf-8")
        cmd = f"bash -c '{evil}/codex_wrapper.py --prompt-file /etc/passwd'"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_bash_lc_payload_foreign_wrapper_denies():
    """`bash -lc '…'` (combined short-flag bundle ending in c) parses the payload too."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "gemini_wrapper.py").write_text("print('pwned')\n", encoding="utf-8")
        cmd = f"bash -lc '{evil}/gemini_wrapper.py --prompt hi'"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_sh_c_payload_foreign_wrapper_denies():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("print('pwned')\n", encoding="utf-8")
        cmd = f"sh -c '{evil}/codex_wrapper.py --prompt hi'"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_bash_c_payload_real_wrapper_allows():
    """`bash -c '<real wrapper> --prompt hi'` resolves to the real bin -> ALLOW."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"bash -c '{rb}/codex_wrapper.py --prompt hi'"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "allow", (decision, reason)


def test_bash_c_non_wrapper_passthrough():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        assert decide("bash -c 'ls -la'", [work], rb) == ("allow", None)


def test_bash_c_payload_gated_flag_outside_denies():
    """A real wrapper INSIDE a -c payload with an out-of-root gated flag denies."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"bash -c '{rb}/codex_wrapper.py --prompt-file /etc/passwd'"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


# ── decide(): command-substitution / backtick / here-string / process-subst /
#    chained smuggling (T5 RE-REVIEW — the fail-closed text-scan backstop) ─────
#
# Each vector below reached ALLOW while NAMING (and, for the substitution forms,
# EXECUTING) a FOREIGN wrapper: shlex leaves `$(/evil/codex_wrapper.py)` a single
# token whose trailing `)` / backtick defeats `_is_wrapper_token`'s endswith, and
# `_expand_command_tokens` recurses ONLY shell `-c` payloads, not substitutions.
# The RAW-text backstop must extract the smuggled path and DENY. The invoked leg is
# the REAL wrapper so the DENY can ONLY come from catching the substitution.
def _evil_wrapper(tmp: Path, name: str = "codex_wrapper.py") -> Path:
    evil = tmp / "evil"
    evil.mkdir(exist_ok=True)
    f = evil / name
    f.write_text("print('pwned')\n", encoding="utf-8")
    return f


def test_cmd_subst_dquote_denies():
    """`… --prompt "$(/evil/codex_wrapper.py)"` executes a foreign wrapper -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f'{rb}/codex_wrapper.py --prompt "$({evil})"'
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_backtick_subst_denies():
    """`… --prompt "`/evil/codex_wrapper.py`"` (backtick substitution) -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f'{rb}/codex_wrapper.py --prompt "`{evil}`"'
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_here_string_subst_denies():
    """`… <<< "$(/evil/codex_wrapper.py)"` (here-string substitution) -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f'{rb}/codex_wrapper.py <<< "$({evil})"'
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_cmd_subst_bare_denies():
    """`… --prompt $(/evil/codex_wrapper.py)` (unquoted substitution) -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"{rb}/codex_wrapper.py --prompt $({evil})"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_proc_subst_denies():
    """`… --prompt <(/evil/codex_wrapper.py)` (process substitution) -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"{rb}/codex_wrapper.py --prompt <({evil})"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_chained_echo_subst_denies():
    """`… --prompt hi; echo $(/evil/codex_wrapper.py)` (chained + substitution) -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"{rb}/codex_wrapper.py --prompt hi; echo $({evil})"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_echo_subst_only_denies():
    """`echo $(/evil/codex_wrapper.py)` — the invocation is a non-wrapper command,
    the wrapper hides ENTIRELY in the substitution -> DENY (no wrapper token reaches
    the existing loop; only the backstop catches this)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"echo $({evil})"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_echo_backtick_only_denies():
    """`echo `/evil/codex_wrapper.py`` (backtick, non-wrapper outer command) -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"echo `{evil}`"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_bash_c_cmd_subst_denies():
    """A substitution smuggled INSIDE a `bash -c` payload (recursive backstop)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"bash -c 'echo $({evil})'"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_real_wrapper_inside_subst_allows():
    """Precision proof: the backstop is NOT a blanket `$()` deny — a substitution
    that references the REAL plugin wrapper resolves to the real bin -> ALLOW."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f'{rb}/codex_wrapper.py --prompt "$({rb}/codex_wrapper.py)"'
        decision, reason = decide(cmd, [work], rb)
        assert decision == "allow", (decision, reason)


def test_echo_date_subst_passthrough():
    """A non-wrapper substitution `echo $(date)` names no wrapper -> pass-through."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        assert decide("echo $(date)", [work], rb) == ("allow", None)


# ── decide(): brace parameter-default smuggle (T5 RE-REVIEW, adjacent Critical) ─
#
# `${x:-/evil/codex_wrapper.py}` (and the `:=` / `:+` siblings) fuse the literal
# foreign path to the surrounding braces. The OLD metachar split omitted `{ } : =`,
# so `_extract_wrapper_path_tokens` recovered `{x:-/evil/codex_wrapper.py}` whose
# trailing `}` defeats `_is_wrapper_token`'s `/codex_wrapper.py` endswith — the path
# never surfaced, the backstop never fired, the smuggle reached ALLOW while a foreign
# wrapper EXECUTED. Unlike the `$X` residual, the literal path IS present in
# plaintext, so once `{ } : =` bound the token the text scan CAN see it. Each
# vector's invoked leg is the REAL wrapper (or a non-wrapper `echo`), so the DENY
# can ONLY come from catching the smuggled substitution.
def test_brace_default_cmd_subst_denies():
    """`echo $(${x:-/evil/codex_wrapper.py})` executes a foreign wrapper -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"echo $(${{x:-{evil}}})"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_brace_assign_default_cmd_subst_denies():
    """`echo $(${x:=/evil/codex_wrapper.py})` (`:=` assign-default sibling) -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"echo $(${{x:={evil}}})"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_brace_alt_cmd_subst_denies():
    """`echo $(${x:+/evil/codex_wrapper.py})` (`:+` alternate sibling) -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"echo $(${{x:+{evil}}})"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_brace_default_bare_leading_wrapper_denies():
    """WORST CASE — a bare-leading REAL wrapper (auto-approved promptless by the
    basename grant) whose `--prompt` smuggles a foreign wrapper via `$(${x:-…})`.
    The real bin is first on PATH so the leading `codex_wrapper.py` resolves to the
    REAL bin -> the DENY can ONLY come from catching the brace-param-default
    substitution, not from an unresolvable bare token."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        (rb / "codex_wrapper.py").chmod(
            (rb / "codex_wrapper.py").stat().st_mode | stat.S_IEXEC)
        evil = _evil_wrapper(tmp)
        cmd = f'codex_wrapper.py --prompt "$(${{x:-{evil}}})"'
        saved = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{rb}{os.pathsep}{saved}"
        try:
            decision, reason = decide(cmd, [work], rb)
        finally:
            os.environ["PATH"] = saved
        assert decision == "deny", (decision, reason)


def test_accepted_residual_variable_indirection_passthrough():
    """ACCEPTED RESIDUAL (documented boundary, pinned): when the wrapper path lives
    in a shell variable assigned ELSEWHERE (a prior command / sourced file) it is
    ABSENT from THIS command's text, so the deterministic text scan cannot see it —
    `$X` alone names no wrapper -> pass-through ALLOW. (The wrapper's own
    TRIAD_WRAPPER_HARDENED roots-isolation is the backstop for this class.) NOTE the
    SAME-LINE `X=/evil/codex_wrapper.py; $X` is NOT this residual — the literal path
    is present and IS denied — so this pins strictly the path-absent case."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        assert decide('echo "$X"', [work], rb) == ("allow", None)


# ── decide(): real-bin path with '=' / ':' in a dir name — T5 OVER-CORRECTION ─
#
# The T5 re-review widened `_METACHAR_SPLIT_RE` to include `{ } : =` so a
# brace-default smuggle (`${x:-/evil/…}`) surfaces its literal path. That widening
# ALSO over-fragmented a LEGIT real plugin-bin absolute path whose directory name
# contains a literal `=` or `:` — `/…/my=plug:in/bin/codex_wrapper.py` split into
# `in/bin/codex_wrapper.py`, which resolves cwd-relative (≠ real bin) -> a FALSE
# DENY of a real invocation. The fix EXEMPTS a real-bin-resolving path BEFORE the
# aggressive split; a FOREIGN path (even one containing `=`/`:`) never resolves to
# the real bin, so it still hits the split and DENIES (fail-closed preserved).
def _real_bin_metachars(tmp: Path) -> Path:
    """A plugin bin/ under a directory whose name contains a literal `=` and `:`
    (the over-correction surface). Seeds the same wrappers as `_real_bin`."""
    b = tmp / "my=plug:in" / "bin"
    b.mkdir(parents=True)
    for name in ("codex_wrapper.py", "gemini_wrapper.py", "antigravity_wrapper.py"):
        f = b / name
        f.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return b


def test_real_bin_metachar_dir_direct_allows():
    """A real-bin invocation whose path contains `=` and `:` must ALLOW (the
    over-correction regression: the widened split fragmented the real path)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin_metachars(tmp), _work_root(tmp)
        cmd = f"python3 {rb}/codex_wrapper.py --prompt hi"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "allow", (decision, reason)


def test_real_bin_metachar_dir_cmd_subst_allows():
    """`echo $(<real-bin-with-=:>/codex_wrapper.py)` — the real bin inside a command
    substitution must ALLOW (backstop exempts the real-bin path before the split)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin_metachars(tmp), _work_root(tmp)
        cmd = f"echo $({rb}/codex_wrapper.py)"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "allow", (decision, reason)


def test_real_bin_metachar_dir_gated_flag_outside_still_denies():
    """The real-bin exemption must NOT disable arg-gating: a real-bin path with
    `=`/`:` plus an out-of-root --prompt-file still DENIES (at the gate, not the
    backstop)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin_metachars(tmp), _work_root(tmp)
        cmd = f"python3 {rb}/codex_wrapper.py --prompt-file /etc/passwd"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_foreign_path_with_equals_denies():
    """REGRESSION GUARD — a FOREIGN wrapper path that itself contains `=` must still
    DENY: it never resolves to the real bin, so the aggressive split still catches
    it (`/ev=il/codex_wrapper.py` -> `il/codex_wrapper.py` -> foreign)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin_metachars(tmp), _work_root(tmp)
        evil = tmp / "ev=il"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("print('pwned')\n", encoding="utf-8")
        cmd = f"echo $({evil}/codex_wrapper.py)"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_real_bin_metachar_brace_default_foreign_denies():
    """REGRESSION GUARD — with a real bin whose dir contains `=`/`:`, a brace-default
    smuggle of a FOREIGN wrapper (`$(${x:-/evil/…})`) must still DENY (the fix does
    not disable the brace-default closure)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin_metachars(tmp), _work_root(tmp)
        evil = _evil_wrapper(tmp)
        cmd = f"echo $(${{x:-{evil}}})"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


# ── decide(): argparse-abbreviation defense-in-depth (IMPORTANT-3) ────────────
def test_abbrev_prompt_file_outside_denies():
    """The hook gates an unambiguous abbreviation `--prompt-f` of `--prompt-file`."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"python3 {rb}/codex_wrapper.py --prompt-f /etc/passwd"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_abbrev_image_outside_denies():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        outside = tmp / "outside" / "s.png"
        cmd = f"python3 {rb}/codex_wrapper.py --prompt hi --im {outside}"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_abbrev_cwd_outside_denies():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        outside = tmp / "elsewhere"
        cmd = f"python3 {rb}/gemini_wrapper.py --cw {outside} --prompt hi"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_inline_prompt_not_treated_as_gated():
    """`--prompt` (inline, non-gated) shares a stem with `--prompt-file` but must
    NOT be gated — a legitimate inline prompt is not a path."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"python3 {rb}/codex_wrapper.py --prompt /etc/passwd"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "allow", (decision, reason)


# ── decide(): malformed / missing value posture (MINOR-2) ─────────────────────
def test_trailing_gated_flag_no_value_denies():
    """A gated flag with no value (trailing) is a malformed wrapper call -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"python3 {rb}/codex_wrapper.py --prompt-file"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


# ── decide(): empty-roots fail-closed (pin existing behavior) ─────────────────
def test_empty_roots_gated_flag_denies():
    """With NO allowed roots, any gated flag value is outside -> DENY (fail-closed)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb = _real_bin(tmp)
        p = tmp / "some" / "p.txt"
        cmd = f"python3 {rb}/codex_wrapper.py --prompt-file {p}"
        decision, reason = decide(cmd, [], rb)
        assert decision == "deny", (decision, reason)


# ── decide(): foreign-wrapper REFERENCE friction (documented fail-closed) ─────
def test_reference_foreign_wrapper_path_denies():
    """A command that merely references a FOREIGN wrapper path (grep) denies —
    accepted fail-closed posture (documented in the hook docstring)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = "grep needle /evil/codex_wrapper.py"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_reference_real_wrapper_path_allows():
    """Referencing the REAL plugin wrapper path resolves to the real bin -> ALLOW."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = f"cat {rb}/codex_wrapper.py"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "allow", (decision, reason)


# ── decide(): unparseable command posture ─────────────────────────────────────
def test_unparseable_wrapper_mention_denies():
    """An unparseable command (unbalanced quote) that names a wrapper -> DENY."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        cmd = "codex_wrapper.py --prompt 'unterminated"
        decision, reason = decide(cmd, [work], rb)
        assert decision == "deny", (decision, reason)


def test_unparseable_non_wrapper_passthrough():
    """An unparseable command that names no wrapper is left alone -> ALLOW."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        assert decide("echo 'unterminated", [work], rb) == ("allow", None)


# ── decide(): pass-through ────────────────────────────────────────────────────
def test_non_wrapper_ls_allows():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        assert decide("ls -la", [work], rb) == ("allow", None)


def test_non_wrapper_git_status_allows():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        assert decide("git status", [work], rb) == ("allow", None)


def test_empty_command_allows():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        assert decide("", [work], rb) == ("allow", None)


# ── main(): the stdin->stdout hook I/O contract ──────────────────────────────
def _run_hook(payload: dict, env_extra: dict):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        env=env,
        capture_output=True,
        text=True,
    )


def test_main_denies_foreign_and_emits_hook_output():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("x\n", encoding="utf-8")
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(tmp),
            "tool_input": {"command": f"python3 {evil}/codex_wrapper.py --prompt hi"},
        }
        r = _run_hook(payload, {
            "TRIAD_WRAPPER_REAL_BIN": str(rb),
            "TRIAD_WRAPPER_ALLOWED_ROOTS": str(work),
        })
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        assert hso["permissionDecision"] == "deny"
        assert hso["permissionDecisionReason"]


def test_main_passes_through_non_wrapper():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(tmp),
            "tool_input": {"command": "ls -la"},
        }
        r = _run_hook(payload, {
            "TRIAD_WRAPPER_REAL_BIN": str(rb),
            "TRIAD_WRAPPER_ALLOWED_ROOTS": str(work),
        })
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "", f"pass-through must emit no decision: {r.stdout!r}"


def test_main_allows_real_wrapper_safe_args_no_deny():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        p = work / "p.txt"
        p.write_text("x", encoding="utf-8")
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(tmp),
            "tool_input": {"command": f"python3 {rb}/codex_wrapper.py --prompt-file {p}"},
        }
        r = _run_hook(payload, {
            "TRIAD_WRAPPER_REAL_BIN": str(rb),
            "TRIAD_WRAPPER_ALLOWED_ROOTS": str(work),
        })
        assert r.returncode == 0, r.stderr
        # allow == no deny emitted (silent exit 0 -> normal permission flow)
        assert '"permissionDecision": "deny"' not in r.stdout


def test_main_fail_open_repro_now_denies():
    """CRITICAL-1 repro: a gated-flag value with a `~unknownuser` reference makes
    `Path(...).expanduser()` raise RuntimeError. The gate must FAIL CLOSED — the
    hook subprocess emits a DENY and exits 0 (previously it crashed exit 1 with no
    decision = fail-open = the tool proceeds)."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(tmp),
            "tool_input": {
                "command": f"{rb}/codex_wrapper.py "
                           "--prompt-file=~nouser999/../../etc/passwd"
            },
        }
        r = _run_hook(payload, {
            "TRIAD_WRAPPER_REAL_BIN": str(rb),
            "TRIAD_WRAPPER_ALLOWED_ROOTS": str(work),
        })
        assert r.returncode == 0, (r.returncode, r.stderr)
        out = json.loads(r.stdout)
        hso = out["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny", r.stdout
        assert hso["permissionDecisionReason"]


def test_main_chained_second_wrapper_denies():
    """IMPORTANT-2 end-to-end: real first wrapper && foreign second wrapper denies."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("x\n", encoding="utf-8")
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(tmp),
            "tool_input": {
                "command": f"{rb}/codex_wrapper.py --prompt ok && "
                           f"{evil}/codex_wrapper.py --prompt hi"
            },
        }
        r = _run_hook(payload, {
            "TRIAD_WRAPPER_REAL_BIN": str(rb),
            "TRIAD_WRAPPER_ALLOWED_ROOTS": str(work),
        })
        assert r.returncode == 0, (r.returncode, r.stderr)
        out = json.loads(r.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", r.stdout


def test_main_cmd_subst_smuggle_denies():
    """T5 RE-REVIEW end-to-end: a real wrapper whose --prompt smuggles a foreign
    wrapper via `$(…)` must DENY through the real hook subprocess."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("x\n", encoding="utf-8")
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(tmp),
            "tool_input": {
                "command": f'{rb}/codex_wrapper.py --prompt "$({evil}/codex_wrapper.py)"'
            },
        }
        r = _run_hook(payload, {
            "TRIAD_WRAPPER_REAL_BIN": str(rb),
            "TRIAD_WRAPPER_ALLOWED_ROOTS": str(work),
        })
        assert r.returncode == 0, (r.returncode, r.stderr)
        out = json.loads(r.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", r.stdout
        assert out["hookSpecificOutput"]["permissionDecisionReason"]


def test_main_brace_default_smuggle_denies():
    """T5 RE-REVIEW end-to-end: a real wrapper whose --prompt smuggles a foreign
    wrapper via `$(${x:-…})` (brace parameter-default) must DENY through the real
    hook subprocess."""
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        rb, work = _real_bin(tmp), _work_root(tmp)
        evil = tmp / "evil"
        evil.mkdir()
        (evil / "codex_wrapper.py").write_text("x\n", encoding="utf-8")
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "cwd": str(tmp),
            "tool_input": {
                "command": f'{rb}/codex_wrapper.py '
                           f'--prompt "$(${{x:-{evil}/codex_wrapper.py}})"'
            },
        }
        r = _run_hook(payload, {
            "TRIAD_WRAPPER_REAL_BIN": str(rb),
            "TRIAD_WRAPPER_ALLOWED_ROOTS": str(work),
        })
        assert r.returncode == 0, (r.returncode, r.stderr)
        out = json.loads(r.stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", r.stdout
        assert out["hookSpecificOutput"]["permissionDecisionReason"]


TESTS = [
    test_prompt_file_outside_roots_denies,
    test_prompt_file_inside_roots_allows,
    test_image_outside_roots_denies,
    test_cwd_outside_roots_denies,
    test_equals_form_flag_outside_roots_denies,
    test_real_wrapper_safe_args_allows,
    test_foreign_absolute_wrapper_denies,
    test_foreign_bare_wrapper_on_path_denies,
    test_real_bare_wrapper_on_path_allows,
    test_chained_second_wrapper_denies,
    test_bash_c_payload_foreign_wrapper_denies,
    test_bash_lc_payload_foreign_wrapper_denies,
    test_sh_c_payload_foreign_wrapper_denies,
    test_bash_c_payload_real_wrapper_allows,
    test_bash_c_non_wrapper_passthrough,
    test_bash_c_payload_gated_flag_outside_denies,
    test_cmd_subst_dquote_denies,
    test_backtick_subst_denies,
    test_here_string_subst_denies,
    test_cmd_subst_bare_denies,
    test_proc_subst_denies,
    test_chained_echo_subst_denies,
    test_echo_subst_only_denies,
    test_echo_backtick_only_denies,
    test_bash_c_cmd_subst_denies,
    test_real_wrapper_inside_subst_allows,
    test_echo_date_subst_passthrough,
    test_brace_default_cmd_subst_denies,
    test_brace_assign_default_cmd_subst_denies,
    test_brace_alt_cmd_subst_denies,
    test_brace_default_bare_leading_wrapper_denies,
    test_accepted_residual_variable_indirection_passthrough,
    test_real_bin_metachar_dir_direct_allows,
    test_real_bin_metachar_dir_cmd_subst_allows,
    test_real_bin_metachar_dir_gated_flag_outside_still_denies,
    test_foreign_path_with_equals_denies,
    test_real_bin_metachar_brace_default_foreign_denies,
    test_abbrev_prompt_file_outside_denies,
    test_abbrev_image_outside_denies,
    test_abbrev_cwd_outside_denies,
    test_inline_prompt_not_treated_as_gated,
    test_trailing_gated_flag_no_value_denies,
    test_empty_roots_gated_flag_denies,
    test_reference_foreign_wrapper_path_denies,
    test_reference_real_wrapper_path_allows,
    test_unparseable_wrapper_mention_denies,
    test_unparseable_non_wrapper_passthrough,
    test_non_wrapper_ls_allows,
    test_non_wrapper_git_status_allows,
    test_empty_command_allows,
    test_main_denies_foreign_and_emits_hook_output,
    test_main_passes_through_non_wrapper,
    test_main_allows_real_wrapper_safe_args_no_deny,
    test_main_fail_open_repro_now_denies,
    test_main_chained_second_wrapper_denies,
    test_main_cmd_subst_smuggle_denies,
    test_main_brace_default_smuggle_denies,
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
