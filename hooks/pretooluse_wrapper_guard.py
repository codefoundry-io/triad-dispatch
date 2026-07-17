#!/usr/bin/env python3
"""PreToolUse hook — the reliable security gate for the dispatch wrappers.

A Claude Code plugin cannot grant Bash permissions, so a companion
`setup_permissions.py --install` writes a bare-BASENAME `permissions.allow` grant
(`Bash(codex_wrapper.py:*)`) into your settings so a legitimate dispatch runs
PROMPTLESS. Claude Code's own docs warn that Bash permission patterns constraining
arguments are "fragile" and "can be bypassed", and recommend a PreToolUse hook for
reliable validation (https://code.claude.com/docs/en/hooks). This is that hook.

It fires on every Bash tool call (matcher "Bash"). When the command invokes (or
merely NAMES) one of the shipped wrapper scripts it performs two deterministic
checks — NO AI, regex / argv parsing only:

  1. FOREIGN-SCRIPT REJECTION — it resolves EVERY wrapper-looking token the way the
     shell would (an absolute/relative path as written, or a PATH lookup for a bare
     basename) and DENIES when a resolved script is NOT this plugin's own wrapper.
     This closes the residual that a basename grant leaves open: a foreign
     same-named `codex_wrapper.py` planted earlier on PATH would be auto-approved by
     the basename grant and would run instead of ours. Only the hook can catch this
     — the wrapper cannot defend against BEING replaced. Every wrapper-looking token
     is validated, not just the first, so a chained second wrapper
     (`real … && /evil/codex_wrapper.py …`) and a wrapper smuggled inside a shell
     interpreter payload (`bash -c '/evil/codex_wrapper.py …'`, also sh/zsh/dash and
     combined bundles like `bash -lc '…'`) are caught — the -c payload is
     recursively re-parsed and scanned with the same rules.

     A wrapper can ALSO hide inside a COMMAND SUBSTITUTION (`$(/evil/codex_wrapper.py)`
     or a backtick), a HERE-STRING (`… <<< "$(/evil/…)"`), a PROCESS SUBSTITUTION
     (`<(/evil/…)`), or the second half of a chained command (`… ; echo $(/evil/…)`)
     — forms where shlex leaves the path FUSED to its surrounding metacharacters
     (a trailing `)` / backtick), so no wrapper TOKEN ever surfaces. A FAIL-CLOSED
     TEXT-SCAN BACKSTOP (`_smuggle_backstop`) closes these: it runs FIRST, over the
     raw command AND every nested -c payload, splits each on shell metacharacters to
     recover the bare path, and DENIES any recovered wrapper mention that does not
     resolve to the plugin's own bin. It is a static TEXT SCAN, not a shell parser,
     so it deterministically catches the CONCRETE substitution / backtick /
     here-string / process-subst / chained forms above, AND — because `{ } : =` are
     in the metachar boundary class — a brace parameter-default that embeds a LITERAL
     path (`${x:-/abs/codex_wrapper.py}`, and the `${x:=…}` / `${x:+…}` siblings) is
     now CLOSED: the trailing `}` no longer fuses onto the path, so the literal path
     surfaces and resolves as foreign -> DENY. Because `= :` are boundaries in that
     split, a LEGIT real plugin-bin absolute path whose directory name contains a
     literal `=` or `:` (`/…/my=plug:in/bin/codex_wrapper.py`) is EXEMPTED first
     (`_mask_real_bin_refs` recognises the wider path run, resolves it, and — only
     when it is the plugin's own bin — masks it before the split), so the widening
     does not FALSE-DENY a real invocation. A foreign path never resolves to the real
     bin, so it is never exempted and still hits the split -> DENY.

     What remains genuinely OUT of deterministic text-scan scope (accepted residual,
     for which the wrapper's own TRIAD_WRAPPER_HARDENED containment — roots isolation
     + pinned vendor bin — remains the backstop):
       (a) a path STORED in a variable assigned ELSEWHERE and thus ABSENT from the
           command text (`X=/evil/w.py` in a prior command, then `$X` here) — the
           text scan has no literal path to see. (The SAME-LINE `X=/evil/w.py; $X`
           is NOT residual: the `=` boundary surfaces the literal path -> DENY.)
       (b) the bare-basename-in-braces form `${x:-codex_wrapper.py}` with NO `/`
           separator — needs a hostile PATH plant to resolve to anything.
       (c) glob obfuscation (`codex_wrap*.py`).
       (d) a shell-DECODED / encoded literal — an ANSI-C `$'\x2f…'` (hex/octal) form,
           or any construct where the literal path is NOT present in plaintext and
           only bash's own decoder would materialise it — is out of deterministic
           text-scan scope (same family as (a) var-indirection and (c) glob).
     A substitution that references the REAL plugin wrapper path (it resolves to the
     real bin) still passes.

  2. ARG-GATING (defense-in-depth atop the wrapper's own containment) — it DENIES
     when `--prompt-file` / `--image` / `--cwd` (space or `=` form, incl. an
     unambiguous argparse-style abbreviation such as `--prompt-f` / `--im` / `--cw`)
     points OUTSIDE the workspace roots (read from TRIAD_WRAPPER_ALLOWED_ROOTS, which
     the install step sets), ALLOWS otherwise. A gated flag with NO value (trailing)
     is a malformed wrapper call and DENIES.

Any non-wrapper Bash command is passed through with no opinion (normal permission
flow). Fail-CLOSED posture for a wrapper mention: an UNPARSEABLE command (unbalanced
quote) or any unexpected internal error is DENIED when the command names a wrapper,
and left alone (silent pass-through) when it does not — a hook bug must never break
every Bash call in the user's session, but it must never let a wrapper invocation
slip through unvalidated either.

ACCEPTED FRICTION (documented, fail-closed): a command that merely REFERENCES a
foreign wrapper path — e.g. `grep needle /evil/codex_wrapper.py` — now DENIES,
because the token ends in a wrapper basename and does not resolve to the plugin's
own bin. Referencing the REAL plugin wrapper path (e.g. `cat <plugin-bin>/codex_wrapper.py`)
still passes (it resolves to the real bin). This is the intended posture: any
wrapper mention outside the plugin is refused.

I/O contract (Claude Code PreToolUse hook, https://code.claude.com/docs/en/hooks):
  * stdin: a JSON object with `tool_name`, `tool_input.command`, `cwd`, ...
  * stdout: on DENY, exit 0 + a JSON object
      {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                              "permissionDecision": "deny",
                              "permissionDecisionReason": "..."}}
    on ALLOW / pass-through: exit 0 with no output (defer to the normal flow, so
    the hook never force-allows over the user's own deny rules).

Stdlib only (json / os / sys / shlex / shutil / pathlib); Python 3.12; macOS +
Ubuntu.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path

# The shipped wrapper scripts a dispatch may invoke. Kept in lock-step with the
# installer's WRAPPER_SCRIPTS (scripts/setup_permissions.py) — the same set gets a
# basename Bash grant, so the same set is the foreign-script attack surface. Only
# the `.py` wrappers accept the gated path flags; the `.sh` daily-checks do not,
# so arg-gating naturally no-ops for them while foreign-script rejection still
# applies.
WRAPPER_SCRIPTS = (
    "codex_wrapper.py",
    "gemini_wrapper.py",
    "antigravity_wrapper.py",
    "agy-daily-check.sh",
    "gemini-daily-check.sh",
)

# Flags whose value is a filesystem path that must stay inside the workspace roots.
GATED_PATH_FLAGS = ("--prompt-file", "--image", "--cwd")
# Non-gated long flags that could collide with a gated flag by prefix — argparse
# resolves an EXACT flag before any abbreviation, so `--prompt` (the inline prompt)
# must NEVER be gated even though `--prompt-file` starts with it.
_NON_GATED_EXACT = ("--prompt",)
# The smallest abbreviation we recognise as a gated flag (e.g. `--im`, `--cw`).
_MIN_ABBREV_LEN = 4

# Shell interpreters whose `-c <payload>` argument is itself a command we must
# recursively parse (a wrapper smuggled inside a quoted payload is invisible to a
# single shlex.split of the outer command).
SHELL_INTERPRETERS = ("bash", "sh", "zsh", "dash")
# Bound recursion so a pathological nesting cannot spin the hook.
_MAX_SHELL_DEPTH = 6
# Tokens that terminate a single shell command (so a shell interpreter's -c search
# does not run past the command it introduces).
_CMD_SEPARATORS = ("&&", "||", ";", "|", "&")

ALLOW = "allow"
DENY = "deny"

# Sentinel for a gated flag present with no value (trailing) — malformed.
_MISSING = object()


class _UnparseableWrapperError(Exception):
    """A nested shell payload could not be shlex-parsed AND names a wrapper.

    Raised from token expansion so the caller can DENY (fail-closed) rather than
    silently pass a payload we could not inspect.
    """


def _basename(token: str) -> str:
    return os.path.basename(token)


def _is_wrapper_token(token: str) -> bool:
    """A token that NAMES a wrapper script: equal to a wrapper basename, or ending
    in `/<wrapper>` (an absolute/relative path to one)."""
    for w in WRAPPER_SCRIPTS:
        if token == w or token.endswith("/" + w):
            return True
    return False


def _wrapper_basename(token: str) -> str:
    """The wrapper basename a wrapper-looking token denotes."""
    for w in WRAPPER_SCRIPTS:
        if token == w or token.endswith("/" + w):
            return w
    return _basename(token)


def _text_mentions_wrapper(text: str) -> bool:
    """A never-raising substring scan — does the raw command text name any wrapper?

    Used (a) to decide fail-closed vs pass-through on an unparseable command, and
    (b) as the belt-and-suspenders wrapper-relatedness test in main()'s except path.
    """
    return any(w in text for w in WRAPPER_SCRIPTS)


# Shell metacharacters that BOUND a wrapper path smuggled inside command
# substitution (`$(…)` / backticks), a here-string (`<<<`), process substitution
# (`<(…)`), a redirection, a chained / second command, OR a brace parameter
# expansion (`${x:-…}` / `${x:=…}` / `${x:+…}`). Splitting a RAW string on runs of
# these isolates the path token — stripping the surrounding `$ { } : = ( ) `` < > ;
# | & " '` and whitespace — so the trailing `)` / `}` / backtick that defeats
# `_is_wrapper_token`'s endswith is removed and the bare path remains. `{ } : =` are
# in the class so a brace parameter-default (`${x:-/abs/codex_wrapper.py}`) no longer
# fuses its `}` onto the path, which previously hid the literal path from the scan.
# This is a deterministic TEXT SCAN, not a shell parser. ($ and the added chars are
# literal inside the character class; no `-` is present, so no range is formed.)
_METACHAR_SPLIT_RE = re.compile(r"[${}:=()`<>;|&\"'\s]+")

# A WIDENED path-like run: every maximal run of characters that are NOT one of the
# HARD shell metacharacters (`$ { } ( ) ` < > ; | & " '` + whitespace). Unlike
# `_METACHAR_SPLIT_RE` this class KEEPS `:` and `=`, so a real plugin-bin absolute
# path whose directory name contains a literal `=` or `:`
# (`/…/my=plug:in/bin/codex_wrapper.py`) stays a SINGLE run. Used ONLY to recognise —
# and RESOLVE — a legit real-bin reference so it can be exempted BEFORE the aggressive
# `_METACHAR_SPLIT_RE` split runs (see `_mask_real_bin_refs`). A foreign path never
# resolves to the real bin, so the exemption is fail-closed: only the plugin's own bin
# is spared.
_PATHLIKE_WIDE_RE = re.compile(r"[^${}()`<>;|&\"'\s]+")


def _mask_real_bin_refs(text: str, real_bin: Path, cwd: Path) -> str:
    """Blank out (space-fill, in place by character position) every maximal path-like
    run in `text` that NAMES a wrapper AND RESOLVES to the plugin's own real bin, so
    the subsequent aggressive `_METACHAR_SPLIT_RE` split cannot fragment a legit
    real-bin absolute path that contains a literal `=` or `:` in a directory component
    (the T5 over-correction: `/…/my=plug:in/bin/codex_wrapper.py` split into
    `in/bin/codex_wrapper.py`, which resolved cwd-relative ≠ real bin -> a false DENY).

    Fail-closed by construction: a FOREIGN path — even one that itself contains `=`/`:`
    (`/ev=il/codex_wrapper.py`), a foreign path that merely SHARES a suffix with the
    real-bin path, or a brace-default smuggle (`${x:-/evil/…}`) — never resolves to the
    real bin, so it is NEVER masked and still reaches the split -> DENY. Masking is done
    by character SPAN (not string-replace) so a real-bin reference and a foreign path
    that shares its suffix cannot be conflated: only the exact resolving span is spared.
    """
    result = list(text)
    for m in _PATHLIKE_WIDE_RE.finditer(text):
        run = m.group(0)
        if not _is_wrapper_token(run):
            continue
        resolved = _resolve_invoked_script(run, cwd)
        expected = (real_bin / _wrapper_basename(run)).resolve()
        if resolved is not None and resolved == expected:
            for i in range(m.start(), m.end()):
                result[i] = " "
    return "".join(result)


def _extract_wrapper_path_tokens(text: str) -> list[str]:
    """Every maximal non-metachar run in `text` that NAMES a wrapper script (equals a
    wrapper basename, or ends in `/<wrapper>`). This catches a wrapper smuggled inside
    `$(…)` / backticks / `<<<` / `<(…)` / a chained command, which shlex tokenisation
    leaves fused to the surrounding metacharacters and thus invisible to
    `_is_wrapper_token`. A static text scan CANNOT see through variable-indirection
    (`$X`) or glob (`codex_wrap*.py`) obfuscation — that is the documented residual
    (the wrapper's own TRIAD_WRAPPER_HARDENED containment is the backstop there)."""
    out: list[str] = []
    for run in _METACHAR_SPLIT_RE.split(text):
        if run and _is_wrapper_token(run):
            out.append(run)
    return out


def _real_bin_dir() -> Path:
    """The plugin's own `bin/` — the only legitimate home of the wrappers.

    Prefer an explicit TRIAD_WRAPPER_REAL_BIN (set for tests / belt-and-suspenders
    pinning); otherwise derive it from this hook's own location — the hook ships in
    `<plugin>/hooks/` and the wrappers in the sibling `<plugin>/bin/`.
    """
    override = os.environ.get("TRIAD_WRAPPER_REAL_BIN")
    if override:
        return Path(override).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "bin").resolve()


def parse_roots(raw: str | None) -> list[Path]:
    """Parse TRIAD_WRAPPER_ALLOWED_ROOTS (os.pathsep-separated) into resolved Paths."""
    if not raw:
        return []
    roots = []
    for entry in raw.split(os.pathsep):
        entry = entry.strip()
        if entry:
            roots.append(Path(entry).expanduser().resolve())
    return roots


def _dash_c_payload(tokens: list[str], start: int) -> str | None:
    """Within a shell-interpreter invocation beginning at `start`, find the argument
    string introduced by `-c` (or a combined short-flag bundle ending in `c`, e.g.
    `-lc`). Returns the payload token, or None if there is no -c payload before the
    command ends.
    """
    j = start
    while j < len(tokens):
        tok = tokens[j]
        if tok in _CMD_SEPARATORS:
            return None
        is_c = tok == "-c" or (
            len(tok) >= 2
            and tok.startswith("-")
            and not tok.startswith("--")
            and tok.endswith("c")
        )
        if is_c:
            return tokens[j + 1] if j + 1 < len(tokens) else None
        j += 1
    return None


def _expand_command_tokens(command: str, depth: int = 0) -> list[str]:
    """shlex-split `command`, then recursively expand any shell-interpreter `-c`
    payload so a smuggled wrapper is visible in the flat token list.

    Raises ValueError if `command` itself is unparseable. Raises
    _UnparseableWrapperError if a NESTED payload is unparseable AND names a wrapper.
    """
    tokens = shlex.split(command)
    if depth >= _MAX_SHELL_DEPTH:
        return tokens
    expanded: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        expanded.append(tok)
        if _basename(tok) in SHELL_INTERPRETERS:
            payload = _dash_c_payload(tokens, i + 1)
            if payload is not None:
                try:
                    expanded.extend(_expand_command_tokens(payload, depth + 1))
                except ValueError:
                    if _text_mentions_wrapper(payload):
                        raise _UnparseableWrapperError() from None
                    # a non-wrapper unparseable payload is not our concern
        i += 1
    return expanded


def _shell_payloads(command: str, depth: int = 0) -> list[str]:
    """Every shell-interpreter `-c` payload STRING reachable from `command`,
    recursively (the raw payload strings, for the text-scan backstop — a payload's
    de-quoted path run can differ from its appearance in the outer command). Never
    raises: an unparseable segment simply yields no further payloads (the raw
    `command` is still scanned by the caller)."""
    if depth >= _MAX_SHELL_DEPTH:
        return []
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if _basename(tokens[i]) in SHELL_INTERPRETERS:
            payload = _dash_c_payload(tokens, i + 1)
            if payload is not None:
                out.append(payload)
                out.extend(_shell_payloads(payload, depth + 1))
        i += 1
    return out


def _texts_to_scan(command: str) -> list[str]:
    """The raw command plus every nested shell `-c` payload — the inputs the
    fail-closed text-scan backstop runs over."""
    return [command, *_shell_payloads(command)]


def _resolve_invoked_script(token: str, cwd: Path) -> Path | None:
    """Resolve the wrapper token the way the shell would.

    A token with a path separator is a path (absolute, or relative to cwd); a bare
    basename is resolved via PATH (shutil.which). Returns the resolved absolute
    Path, or None if a bare name is not found on PATH or the path cannot be resolved
    (a `~unknownuser` reference etc. -> None -> fail-closed DENY at the caller).
    """
    try:
        has_sep = os.sep in token or (os.altsep is not None and os.altsep in token)
        if has_sep:
            p = Path(token).expanduser()
            if not p.is_absolute():
                p = cwd / p
            return p.resolve()
        found = shutil.which(token)
        return Path(found).resolve() if found else None
    except Exception:
        return None


def _gated_flag_of(flagpart: str) -> str | None:
    """The gated flag a token's flag-part denotes, mirroring argparse resolution:
    an EXACT gated flag, or an unambiguous prefix-abbreviation of exactly one gated
    flag that does not collide with a non-gated flag (`--prompt`). Returns None for
    a non-gated or ambiguous flag.
    """
    if flagpart in GATED_PATH_FLAGS:
        return flagpart
    if flagpart in _NON_GATED_EXACT:
        return None  # exact non-gated flag beats any abbreviation
    if not flagpart.startswith("--") or len(flagpart) < _MIN_ABBREV_LEN:
        return None
    matches = [g for g in GATED_PATH_FLAGS if g.startswith(flagpart)]
    if len(matches) != 1:
        return None
    # ambiguous with a non-gated flag (e.g. `--pr` prefixes both `--prompt` and
    # `--prompt-file`) -> not gated (argparse would reject it as ambiguous too).
    if any(nf.startswith(flagpart) for nf in _NON_GATED_EXACT):
        return None
    return matches[0]


def _gated_path_values(args: list[str]) -> list[tuple[str, object]]:
    """(flag, value) pairs for every gated flag present across the token stream
    (space or `=` form, incl. unambiguous abbreviations). A trailing gated flag
    with no value yields (flag, _MISSING)."""
    out: list[tuple[str, object]] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok.startswith("--") and "=" in tok:
            flagpart, _, value = tok.partition("=")
            g = _gated_flag_of(flagpart)
            if g is not None:
                out.append((g, value))
            i += 1
            continue
        g = _gated_flag_of(tok)
        if g is not None:
            if i + 1 < len(args):
                out.append((g, args[i + 1]))
                i += 2
                continue
            out.append((g, _MISSING))
            i += 1
            continue
        i += 1
    return out


def _within_roots(p: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            p.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _smuggle_backstop(command: str, real_bin: Path,
                      cwd: Path) -> tuple[str, str] | None:
    """Fail-closed TEXT-SCAN backstop over the RAW command AND every nested shell
    `-c` payload. For each wrapper mention the scan extracts (see
    `_extract_wrapper_path_tokens`), resolve it exactly as the foreign-script check
    does and DENY unless it is the plugin's own `bin/<wrapper>`. Returns a
    (DENY, reason) tuple on the first offending mention, else None.

    This closes the command-substitution / backtick / here-string / process-subst /
    chained smuggle that `_expand_command_tokens` cannot see: those forms fuse the
    wrapper path to metacharacters (`$(/evil/codex_wrapper.py)`), so no wrapper TOKEN
    reaches the main-path loop — the scan works on the de-metachar'd text instead.
    Residual (documented, out of deterministic scope): variable-indirection (`$X`)
    and glob (`codex_wrap*.py`) obfuscation are NOT caught here — the wrapper's own
    TRIAD_WRAPPER_HARDENED containment remains the backstop for those."""
    for text in _texts_to_scan(command):
        # Exempt a legit real-bin absolute path (which may contain `=`/`:` in a dir
        # name) BEFORE the aggressive `_METACHAR_SPLIT_RE` split fragments it. Only a
        # run that RESOLVES to the plugin's own bin is masked — a foreign path is left
        # intact for the split-and-validate below to DENY (fail-closed preserved).
        text = _mask_real_bin_refs(text, real_bin, cwd)
        for token in _extract_wrapper_path_tokens(text):
            resolved = _resolve_invoked_script(token, cwd)
            expected = (real_bin / _wrapper_basename(token)).resolve()
            if resolved is None:
                return (DENY, f"wrapper reference '{token}' does not resolve to the "
                              f"plugin's {expected} (not found on PATH / unresolvable); "
                              "refusing a foreign or smuggled script (fail-closed)")
            if resolved != expected:
                return (DENY, f"wrapper reference '{token}' resolves to {resolved}, not "
                              f"the plugin's own {expected}; refusing a foreign or "
                              "smuggled (command-substitution / backtick / here-string) "
                              "script")
    return None


def decide(command: str, roots: list[Path], real_bin: Path,
           cwd: Path | None = None) -> tuple[str, str | None]:
    """Pure decision function — (decision, reason) with decision in {allow, deny}.

    `command`  : the Bash tool's command string (tool_input.command).
    `roots`    : allowed workspace roots (resolved absolute Paths).
    `real_bin` : the plugin's own bin/ — the only legitimate wrapper location.
    `cwd`      : the tool's working directory (for resolving relative paths);
                 defaults to the process cwd.
    """
    cwd = (cwd or Path.cwd()).expanduser().resolve()
    real_bin = Path(real_bin).resolve()
    # Resolve the roots so symlinked prefixes (e.g. macOS /var -> /private/var)
    # match a resolved value path; parse_roots already resolves for main(), but a
    # direct caller may pass raw paths.
    roots = [Path(r).expanduser().resolve() for r in roots]

    # (0) FAIL-CLOSED TEXT-SCAN BACKSTOP — runs FIRST, before the token-based
    #     early-outs below, so a wrapper smuggled inside command substitution /
    #     backticks / a here-string / a chained command (which never surfaces as a
    #     wrapper TOKEN) cannot slip past the `not wrapper_tokens -> ALLOW` return.
    backstop = _smuggle_backstop(command, real_bin, cwd)
    if backstop is not None:
        return backstop

    try:
        tokens = _expand_command_tokens(command)
    except _UnparseableWrapperError:
        return (DENY, "a nested shell payload references a wrapper script but could "
                      "not be parsed; refusing (fail-closed)")
    except ValueError:
        # An unparseable outer command. Fail-closed only if it names a wrapper;
        # otherwise it is not ours and would also fail to run in bash.
        if _text_mentions_wrapper(command):
            return (DENY, "unparseable command references a wrapper script; "
                          "refusing (fail-closed)")
        return (ALLOW, None)

    if not tokens:
        return (ALLOW, None)

    wrapper_tokens = [t for t in tokens if _is_wrapper_token(t)]
    if not wrapper_tokens:
        return (ALLOW, None)  # not a triad-wrapper command -> pass through

    # (1) foreign-script rejection — EVERY wrapper-looking token must resolve to the
    #     plugin's own bin.
    for token in wrapper_tokens:
        basename = _wrapper_basename(token)
        resolved = _resolve_invoked_script(token, cwd)
        expected = (real_bin / basename).resolve()
        if resolved is None:
            return (DENY, f"wrapper '{token}' does not resolve to the plugin's "
                          f"{expected} (not found on PATH / unresolvable); refusing "
                          "a foreign or missing script")
        if resolved != expected:
            return (DENY, f"wrapper '{token}' resolves to {resolved}, not the "
                          f"plugin's own {expected}; refusing a foreign same-named "
                          "script")

    # (2) arg-gating on --prompt-file / --image / --cwd across the full token stream.
    for flag, value in _gated_path_values(tokens):
        if value is _MISSING:
            return (DENY, f"{flag} given with no value; refusing a malformed "
                          "wrapper call")
        try:
            vp = Path(str(value)).expanduser()
            if not vp.is_absolute():
                vp = cwd / vp
            vp = vp.resolve()
        except Exception:
            return (DENY, f"{flag} {value!r} cannot be resolved to a filesystem "
                          "path; refusing (fail-closed)")
        if not _within_roots(vp, roots):
            allowed = os.pathsep.join(str(r) for r in roots) or "<none set>"
            return (DENY, f"{flag} {value} points outside the allowed workspace "
                          f"roots ({allowed})")

    return (ALLOW, None)


def _emit_deny(reason: str | None) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": DENY,
            "permissionDecisionReason": reason or "blocked by the wrapper guard",
        }
    }))


def _command_mentions_wrapper(command: str) -> bool:
    """Never-raising wrapper-relatedness test for main()'s fail-closed backstop."""
    if _text_mentions_wrapper(command):
        return True
    try:
        tokens = _expand_command_tokens(command)
    except Exception:
        return False
    return any(_is_wrapper_token(t) for t in tokens)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        # Cannot parse the hook input — a non-blocking no-op (exit 0, no decision).
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("tool_name") != "Bash":
        return 0  # the matcher should ensure Bash; double-check defensively
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return 0

    cwd_raw = payload.get("cwd")
    cwd = Path(cwd_raw) if isinstance(cwd_raw, str) and cwd_raw else None

    # The ENTIRE decision path is wrapped: on ANY unexpected error the gate must
    # FAIL CLOSED for a wrapper-related command (emit a DENY) and pass through
    # silently for a non-wrapper command (a hook bug must not break every Bash call
    # in the user's session).
    try:
        roots = parse_roots(os.environ.get("TRIAD_WRAPPER_ALLOWED_ROOTS"))
        real_bin = _real_bin_dir()
        decision, reason = decide(command, roots, real_bin, cwd=cwd)
    except Exception as exc:  # noqa: BLE001 — the gate must never crash open
        if _command_mentions_wrapper(command):
            _emit_deny(
                f"wrapper guard encountered an unexpected {type(exc).__name__}; "
                "refusing (fail-closed)")
        return 0

    if decision == DENY:
        _emit_deny(reason)
    # ALLOW / pass-through: exit 0 with no output so the hook never force-allows
    # over the user's own deny rules — the basename grant already makes a
    # legitimate dispatch promptless.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
