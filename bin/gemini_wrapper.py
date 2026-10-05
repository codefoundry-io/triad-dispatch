#!/usr/bin/env python3
"""Single-shot Gemini CLI subprocess wrapper.

Always runs in vendor JSON mode:
  gemini -p ... --output-format json --approval-mode ...

Stdout = Gemini's final response text (or, with --pydantic, the validated
JSON object). Stderr = wrapper log + Gemini's two-line warning noise
(Ripgrep / 256-color).

Audit log: _logs/gemini/audit.jsonl (gitignored).

Options:
  --model <name>
        Pin a specific model (free-form). Default = CLI Auto router.
        Use sparingly — model names rot; verify with `/model manage`.
  --pydantic module.path:ClassName
        Inject a JSON schema block into the prompt and validate the answer
        with `cls.model_validate_json()`. On validation fail, retry once
        with a clarifying suffix; second failure → exit 66.
  --repair-mode
        Internal: invoked by Sonnet repair sub-agent (server-cap retry=0).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from _common import (
    _emit_payload,
    _guarded_main,
    _emit_canonical_summary,
    _SIGNAL_STATE,
    map_classification_to_exit,
    _payload_or_demote,
    _relax_diagnostic_stream,
    _summary_tail,
    _review_argv_refusal,
    _wrapper_hardened,
    validate_wrapper_cwd,
    load_prompt_text,
    resolve_prompt_file,
    scrubbed_child_env,
    EXIT_ARG_ERROR,
    audit,
    debug_log,
    emit_run_log,
    install_terminal_signal_handlers,
    load_pydantic_class,
    log,
    require_binary,
    run_cli_with_retry,
    RunResult,
)


APPROVAL_CHOICES = ("default", "auto_edit")
SANDBOX_CHOICES = ("read-only", "workspace-write")

# Per-call READ-ONLY via the Gemini CLI Policy Engine (--policy) instead of the
# crashy `--approval-mode plan` (plan mode OOMs the Node/V8 heap on heavy files
# — gemini-cli issues #11321 / #18331 / #26588). The policy denies mutation +
# shell tools for THIS call only, so the same leg still does code work under
# `--sandbox workspace-write` (per-call, mirrors codex; agy dropped its write
# mode 2026-07-25). The exact policy
# tool identifiers are per the Policy Engine docs but NOT e2e-verified here
# (individual-tier gemini auth is deprecated) — see the policy file header.
_READONLY_POLICY = Path(__file__).resolve().parent / "policies" / "gemini-readonly.toml"

# ── REVIEW-route preflight (spec case C16, rules R-CONTAIN + R-NOCOST) ─────
# Three provider-free checks run BEFORE the review dispatch, because each of
# them decides whether the run can be trusted at all:
#   * VERSION FLOOR — "Gemini formal review requires CLI >= 0.34.0 (PR #20639
#     lands the headless policy-allow fix)" (R-NOCOST). Below the floor the
#     `--policy` allow rows do not take effect headlessly, so the read-only
#     posture would be a claim, not a control.
#   * CAPABILITY — the wrapper's read-only argv needs `--policy`,
#     `--approval-mode` and `--output-format`; a CLI that does not advertise
#     one of them would either ignore the flag or die mid-dispatch.
#   * AUTH CLASS — R-NOCOST: CLI subscriptions only, login is the user's own
#     OAuth login. An api-key / Vertex / ADC selection changes the BILLING
#     route, so the review leg refuses rather than spending on it.
# SCOPE: the REVIEW route (`--sandbox read-only`, including the hardened
# default) — both spec sentences scope these to the formal review route, and
# `--policy` (what the floor is about) is attached only there. An investigation
# or write dispatch keeps its single spawn and is not probed.
# NOT RUN LIVE on this host; every check here is
# deterministic and provider-free (t57). The runtime effect of the policy and
# the real principal stay owner-briefing items (R-GOOGLE).
_GEMINI_VERSION_FLOOR = (0, 34, 0)
_VERSION_RE = re.compile(
    r"(?<![0-9.])(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?(?![0-9])")
_PREFLIGHT_TIMEOUT_S = 10
_REQUIRED_HELP_FLAGS = ("--policy", "--approval-mode", "--output-format")
# C18 / R-NOCOST: the gemini CLI exposes no model listing, so the review route
# checks an explicit --model against this versioned list of the CLI's own model
# table (its source and CLI version are recorded in the file).
_MODEL_LIST = Path(__file__).resolve().parent / "gemini-models.json"

# Tier-2 (installed gemini CLI 0.60.0 bundle, packages/core/dist/src/core/
# contentGenerator.js `AuthType`): the non-OAuth selections. `oauth-personal`
# (LOGIN_WITH_GOOGLE) is the approved subscription route and is never refused;
# `gateway`, `cloud-shell` and any value this table does not know are reported
# and allowed to run — a refusal list is a claim about billing, and guessing
# one would block a legitimately configured in-service host.
_REFUSED_AUTH_CLASSES = {
    "gemini-api-key": "a Gemini API key (AuthType USE_GEMINI)",
    "vertex-ai": "Vertex AI credentials (AuthType USE_VERTEX_AI)",
    "compute-default-credentials": "Application Default Credentials (AuthType COMPUTE_ADC)",
}
# Tier-2 (same bundle): `security.auth.selectedType` in the settings file —
# `settings.merged.security.auth.selectedType` in packages/cli/src/core/
# initializer.ts, declared in the settings schema as auth.properties.selectedType.
_AUTH_SETTING_PATH = ("security", "auth", "selectedType")

# ── INVESTIGATION route: `--web` (spec case C29, rule R-INVEST) ───────────
# A's own research profile for the gemini route. NOT the shared review
# contract: `policies/gemini-readonly.toml` is the vendored byte-identical
# review policy and DENIES both web tools (D-9 — "REVIEW has no web on any
# family"), so a web-authorized investigation needs its own file rather than a
# loosened review one. The two never mix: `--web` is refused on the review
# posture (below).
_RESEARCH_POLICY = Path(__file__).resolve().parent / "policies" / "gemini-research.toml"
# The REVIEW route's complete web profile (R-REVIEW-WEB, case C32): byte-equal
# to the shared contract `contracts/gemini-readonly-web.toml` — the no-web
# profile with ONLY google_web_search / web_fetch moved to allow. Attached
# instead of `_READONLY_POLICY` under `--review-web`, never as an overlay.
_READONLY_WEB_POLICY = Path(__file__).resolve().parent / "policies" / "gemini-readonly-web.toml"

# The shared clause `web-evidence` (`spec/prompts/investigation.md`), whose seed
# is `antigravity_wrapper.AGY_WEB_EVIDENCE_CLAUSE`. § order of that file: "On a
# gemini route the tool names read `web_fetch` for the page fetch and
# `google_web_search` for the summary; a host renderer substitutes the names of
# the CLI it dispatches and changes nothing else." So these bytes are the agy
# bytes with exactly two substitutions (`read_url_content` -> `web_fetch`,
# `search_web` -> `google_web_search`) — t58 axis 8 imports BOTH constants and
# proves the derivation, which is also the drift guard: editing one without the
# other fails that axis. Written out literally rather than computed from the
# agy module, so this wrapper never imports its sibling at runtime.
GEMINI_WEB_EVIDENCE_CLAUSE = (
    "WEB EVIDENCE PROCEDURE (appended by the caller to every research dispatch; it "
    "binds every external fact in your answer). google_web_search returns a "
    "model-written summary and grounding-redirect links: a POINTER to sources, "
    "never a citation. For every fact you take from the web, call web_fetch on the "
    "source page itself (the official document, the version-tagged source file, the "
    "release note or the repository page) and cite the exact URL you fetched "
    "together with the date or version string visible ON that page. Never write a "
    "URL you did not fetch, a placeholder such as `https://example.com/...`, or a "
    "bare year in place of a page date. If the fetch fails or the page shows no "
    "date or version, report that fact as UNSURE and name the URL you tried. Local "
    "file facts come first, cited as path:line; web facts follow, each with its "
    "fetched URL and page date."
)


def _probe(gemini_bin: str, probe_args: list[str]) -> Tuple[int, str]:
    """One bounded vendor probe. Returns (rc, stdout+stderr); rc -1 = the probe
    itself could not run. The child env is the same scrubbed env the dispatch
    gets, so the probe cannot be answered by a credential the run will not see."""
    try:
        proc = subprocess.run(
            [gemini_bin, *probe_args], capture_output=True, text=True,
            timeout=_PREFLIGHT_TIMEOUT_S, env=scrubbed_child_env(cli="gemini"))
    except (OSError, subprocess.SubprocessError) as e:
        return -1, f"{type(e).__name__}: {e}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _parse_version(text: str) -> Optional[tuple]:
    """First dotted `major.minor.patch` in the probe output, or None.

    Deliberately NOT a lenient "find any number" read: an unparsable version is
    refused by the caller, never assumed current (R-NOCOST — an unrun check is
    unverified, never green). A pre-release (`0.34.0-rc.1`) sorts BELOW its
    release, so a pre-release of a floor version is below that floor (spec
    R-NOCOST; the other host's rule, bin/google_preflight_v2.py:22-23): its
    patch reads as patch - 0.5. `_version_text` gives the printed form."""
    m = _VERSION_RE.search(text or "")
    if not m:
        return None
    major, minor, patch = (int(g) for g in m.groups()[:3])
    return (major, minor, patch - 0.5 if m.group(4) else patch)


def _version_text(text: str) -> str:
    """The version exactly as the CLI printed it (C65: recorded as observed)."""
    m = _VERSION_RE.search(text or "")
    return m.group(0) if m else ""


def _system_settings_path() -> Path:
    """Tier-2 (bundle `getSystemSettingsPath`): the env override, else the
    per-platform system settings file."""
    override = os.environ.get("GEMINI_CLI_SYSTEM_SETTINGS_PATH")
    if override:
        return Path(override)
    if platform.system() == "Darwin":
        return Path("/Library/Application Support/GeminiCli/settings.json")
    return Path("/etc/gemini-cli/settings.json")


def _settings_files(cwd: Optional[str]) -> list:
    """The settings files in MERGE order, lowest precedence first.

    Tier-2 (bundle `mergeSettings`): `customDeepMerge(defaults, systemDefaults,
    user, workspace, system)` — later wins, so system outranks workspace
    outranks user. User dir = `GEMINI_CLI_HOME` or `~/.gemini` (bundle
    `getMemoryNodeArgs`); workspace = `<cwd>/.gemini` (bundle: project settings
    `.gemini/settings.json`)."""
    user_dir = Path(os.environ.get("GEMINI_CLI_HOME") or (Path.home() / ".gemini"))
    workspace = Path(cwd) if cwd else Path.cwd()
    return [user_dir / "settings.json",
            workspace / ".gemini" / "settings.json",
            _system_settings_path()]


def _selected_auth_class(cwd: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(auth class, the file it came from) per the CLI's own precedence, or
    (None, None) when NO settings file exposes one.

    Never infers: an unreadable or silent settings chain means the class is
    UNEXPOSED, which the caller reports and lets run (the owner runs the live
    checks where gemini is in service)."""
    found: Tuple[Optional[str], Optional[str]] = (None, None)
    for path in _settings_files(cwd):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        node = data
        for key in _AUTH_SETTING_PATH:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, str) and node:
            found = (node, str(path))   # later file wins (merge order)
    return found


def _auth_refusal(cwd: Optional[str]) -> Optional[str]:
    """The R-AUTH gate (spec C37), on EVERY posture: a refusal reason when the
    settings select an API-key-shaped auth class, else None (an unexposed class
    is reported, never inferred). Reads settings files only — no vendor call.
    The remedy is the owner's browser re-login; it names no flag change, since
    every posture is gated."""
    auth_class, auth_src = _selected_auth_class(cwd)
    if auth_class is None:
        # NOT an inference: say so and continue (the authenticated check is the
        # owner's, run where gemini is in service — R-GOOGLE).
        log("NOTE: auth class unexposed — no gemini settings file declares "
            "security.auth.selectedType; the billing route is NOT verified here")
        return None
    if auth_class in _REFUSED_AUTH_CLASSES:
        return (f"gemini auth class {auth_class!r} ({_REFUSED_AUTH_CLASSES[auth_class]}) "
                f"selected in {auth_src} — every gemini dispatch runs on the CLI's "
                f"own subscription login only (no API key, no paid API route). "
                f"Remedy: the owner re-logins through the CLI's browser flow (run "
                f"`gemini` and choose Login with Google); the wrapper does not "
                f"retry, read or change the credential store")
    log(f"NOTE: gemini auth class {auth_class!r} (from {auth_src})")
    return None


def _model_list_refusal(model: str, version: tuple,
                        version_str: str) -> Optional[str]:
    """None when the versioned gemini model list supports `model` on the
    probed CLI `version`, else the refusal reason (C18; an unreadable list
    refuses — an unchecked model is never admitted as checked)."""
    try:
        data = json.loads(_MODEL_LIST.read_text(encoding="utf-8"))
        minimum = _parse_version(data["minimum_version"])
        models = data["models"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return (f"gemini model list {_MODEL_LIST} unreadable "
                f"({type(e).__name__}) — the requested model {model!r} cannot "
                f"be checked against the route's catalog")
    if minimum is None or version < minimum:
        return (f"gemini {version_str} is older than the model "
                f"list's version {data['minimum_version']} — no support evidence "
                f"for the requested model {model!r}; update the gemini CLI")
    if model not in models:
        return (f"the gemini model list ({_MODEL_LIST.name}, CLI "
                f"{data.get('cli_version')}) does not list the requested model "
                f"{model!r} — change the model in the roster entry (or the "
                f"--model value) to a listed one")
    return None


def _review_preflight(gemini_bin: str,
                      cwd: Optional[str],
                      model: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """(refusal reason or None, observed CLI version or None) for the review route.

    The observed version rides EVERY return made after it was observed — a
    refusal included (spec C65: "Record the version actually observed")."""
    rc, out = _probe(gemini_bin, ["--version"])
    if rc != 0:
        return (f"`gemini --version` probe failed (rc={rc}): {out.strip()[:200]}"), None
    version = _parse_version(out)
    if version is None:
        return (f"`gemini --version` output is not a version: {out.strip()[:200]!r} — "
                f"the review route needs a proven CLI >= "
                f"{'.'.join(map(str, _GEMINI_VERSION_FLOOR))}"), None
    version_str = _version_text(out)
    if version < _GEMINI_VERSION_FLOOR:
        return (f"gemini {version_str} < 0.34.0 — the formal review route needs "
                f"CLI >= 0.34.0 (the headless policy-allow fix, PR #20639); below "
                f"it the --policy read-only rows do not take effect headlessly. "
                f"Update the gemini CLI or run this dispatch without "
                f"--sandbox read-only"), version_str
    rc, help_text = _probe(gemini_bin, ["--help"])
    if rc != 0:
        return (f"`gemini --help` probe failed (rc={rc}): "
                f"{help_text.strip()[:200]}"), version_str
    missing = [f for f in _REQUIRED_HELP_FLAGS if f not in help_text]
    if missing:
        return (f"gemini {version_str} does not advertise {', '.join(missing)} in "
                f"--help — the read-only review argv depends on every one of "
                f"{', '.join(_REQUIRED_HELP_FLAGS)}"), version_str
    if model:
        return _model_list_refusal(model, version, version_str), version_str
    return None, version_str


def main() -> int:
    return _guarded_main("gemini", _main)


def _main(ctx: dict) -> int:
    # The DIAGNOSTIC stream survives any locale; the PAYLOAD stream is never
    # re-encoded (gate-1 r7 row r7-c2 — `_common` § payload vs diagnostic).
    _relax_diagnostic_stream()
    # SIGTERM/SIGHUP: during the review preflight probe (a plain
    # subprocess.run, no process group) the handler only records the signal and
    # the run ends as the interrupted-run refusal (`unknown` / 1), written while
    # the mode is still on. From the first dispatch on it only records too:
    # during a dispatch _run_once reaps the vendor group and the run ends as
    # the interrupted-run record (`unknown` / 1), `oauth-env` / 65 on a carrier
    # STOP, or `timeout` / 2 when the run had already timed out (the timeout
    # verdict outranks it); a signal after the last _run_once is not
    # consumed (the completed answer is published). Outside those windows it
    # exits 128+signum (spec case C1 / R-TERMINAL).
    install_terminal_signal_handlers()
    p = argparse.ArgumentParser(description="Gemini CLI single-shot wrapper",
                                allow_abbrev=False)
    prompt_group = p.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument("--prompt", help="User prompt")
    prompt_group.add_argument(
        "--prompt-file",
        help="Read the user prompt from a UTF-8 file (>=50K-char prompts: pass "
             "a file, not inline argv — L12; containment applies under "
             "TRIAD_WRAPPER_ALLOWED_ROOTS)")
    p.add_argument(
        "--approval-mode",
        default="default",
        choices=APPROVAL_CHOICES,
        help="Approval mode (default: default — read auto, write/shell prompt)",
    )
    p.add_argument("--cwd", default=None, help="Process working directory")
    p.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    p.add_argument(
        "--skip-trust",
        action="store_true",
        help="Skip workspace trust dialog",
    )
    p.add_argument(
        "--sandbox",
        choices=SANDBOX_CHOICES,
        default=None,
        help="read-only -> attach a per-call Policy Engine deny (write_file/replace/"
             "run_shell_command) INSTEAD of the crashy plan mode; workspace-write -> "
             "write-enabled (code-agent). Default: unset (no policy attached).",
    )
    p.add_argument(
        "--web",
        action="store_true",
        help="INVESTIGATION route (spec C29/R-INVEST): attach the research "
             "policy (read tools + web_fetch + google_web_search; write/shell/"
             "mcp denied) and append the shared web-evidence clause LAST. "
             "Refused with --sandbox (the review profile denies web) and with "
             "a review-verdict schema.",
    )
    p.add_argument(
        "--review-web",
        action="store_true",
        help="REVIEW route with web (spec C32/R-REVIEW-WEB): with --sandbox "
             "read-only, attach the complete web profile "
             "policies/gemini-readonly-web.toml instead of "
             "gemini-readonly.toml; never appends the investigation clause; "
             "recorded in the audit row. Not with --web.",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Pin a specific model (free-form). Default = CLI Auto router.",
    )
    p.add_argument(
        "--pydantic",
        default=None,
        help="pydantic class spec (module.path:ClassName) for schema enforcement",
    )
    p.add_argument(
        "--repair-mode",
        action="store_true",
        help="Internal: invoked by Sonnet repair sub-agent (server-cap retry=0)",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Append a human-readable markdown row to "
             "_debug/<UTC-YYYY-MM-DD>/gemini.md (per-call summary)",
    )
    p.add_argument(
        "--attempt",
        type=int,
        default=1,
        help="Dispatch attempt number carried on the transport receipt "
             "(>=1, default 1). RECORDED only — the wrapper never retries "
             "on it and no control flow reads it",
    )
    args = p.parse_args()
    # ONE NORMALIZED MODEL REQUEST (gate-1 r13 row r13-4 — the codex shape of
    # row r12-3, generalized: the C35 / DL-3 sentence covers every leg).
    # Empty or whitespace-only = NO request; the argv build and the record
    # (`requested_model` on the summary tail, the audit row and the run-log)
    # read this one value.
    if args.model is not None and not args.model.strip():
        args.model = None
    ctx.update(attempt=args.attempt, model=args.model, reasoning=None)

    if args.attempt < 1:
        log(f"--attempt must be >= 1 (got {args.attempt})")
        return EXIT_ARG_ERROR
    _refused = _review_argv_refusal()
    if _refused is not None:  # C32: an edited review line, before any vendor work
        log(_refused)
        return EXIT_ARG_ERROR

    # C28: resolve the (possibly relative) --prompt-file once so the absolute
    # path can be RECORDED on the summary line and in the audit/run-log
    # records. load_prompt_text() re-resolves the same way and reads the text.
    _prompt_file_resolved = None
    try:
        if args.prompt_file:
            _prompt_file_resolved = str(resolve_prompt_file(args.prompt_file))
        _prompt_text = load_prompt_text(args.prompt, args.prompt_file)
    except Exception as e:
        log(f"prompt load failed: {e}")
        return EXIT_ARG_ERROR
    args.prompt = _prompt_text  # downstream code keeps using args.prompt
    ctx.update(prompt=args.prompt, prompt_file=_prompt_file_resolved)

    try:
        args.cwd = validate_wrapper_cwd(args.cwd)
    except Exception as e:
        log(f"--cwd validation failed: {e}")
        return EXIT_ARG_ERROR

    if not args.prompt.strip():
        # Checked BEFORE the --web clause append, so the clause can never
        # rescue an empty dispatch (t49's agy precedent, C29).
        log("empty prompt")
        return EXIT_ARG_ERROR

    if args.web and args.review_web:
        # An investigation (`--web`: research profile + clause) and a review
        # leg with web (`--review-web`: the review web profile, no clause)
        # are two different dispatches — refused, never guessed.
        log("--web (an investigation) and --review-web (a review leg with "
            "web) are mutually exclusive — pass one")
        return EXIT_ARG_ERROR

    if args.web:
        # INVESTIGATION vs REVIEW (C29 / R-INVEST + R-CONTAIN). The two
        # postures are mutually exclusive by CONTRACT, not by convenience: the
        # review policy denies `google_web_search` / `web_fetch` (D-9), so a
        # `--web` review dispatch could only mean "loosen the review profile".
        # Refused for a write posture too — the research profile denies
        # write_file/replace/run_shell_command, and only ONE --policy is
        # attached, so the combination cannot be honoured as asked.
        if args.sandbox is not None:
            log(f"--web is the investigation route and cannot be combined with "
                f"--sandbox {args.sandbox}: the read-only review policy DENIES "
                f"google_web_search / web_fetch (D-9), and a write posture "
                f"contradicts the research policy's own denies. Drop --sandbox "
                f"for a web investigation.")
            return EXIT_ARG_ERROR
        if args.approval_mode != "default":
            # Same contradiction as above on the approval channel: the research
            # profile denies the write tools `auto_edit` exists to auto-approve.
            log(f"--web runs with --approval-mode default, not "
                f"{args.approval_mode} (the research policy denies the write "
                f"tools an auto-approving mode exists for)")
            return EXIT_ARG_ERROR
        if args.pydantic and args.pydantic.split(":")[0].endswith("verdict_schema"):
            # R-INVEST: an investigation returns free-form or a CUSTOM schema,
            # "never a review verdict (owner Q-D)". A verdict shape produced by
            # a web-reading leg would enter the round as if it had been
            # reviewed under the contained review profile.
            log("--web cannot request a review-verdict schema "
                f"({args.pydantic}): an investigation returns research, never a "
                "leg verdict (R-INVEST). Run the review route for a verdict.")
            return EXIT_ARG_ERROR
        if not _RESEARCH_POLICY.is_file():
            log(f"research policy file missing: {_RESEARCH_POLICY}")
            return EXIT_ARG_ERROR

    # EFFECTIVE POSTURE FIRST (spec C16 / R-CONTAIN: "Effective posture is
    # computed BEFORE the conflict and policy checks (verified defect on A:
    # the hardened default is assigned after the checks)"). Until 2026-09-21
    # this assignment sat BELOW the two checks, so a hardened install whose
    # caller omitted `--sandbox` skipped both of them: an `--approval-mode
    # auto_edit` call became read-only WITHOUT the conflict refusal and ran
    # with a write-auto-approving mode, and a missing policy file was never
    # noticed until the vendor had already been spawned.
    if args.sandbox is None and not args.web and _wrapper_hardened():
        # Hardened installs default the Google legs to read-only: a raw call
        # on a public install must not be write-capable by omission. `--web` is
        # exempt because it is not an omission — it selects the research
        # profile, which denies write_file / replace / run_shell_command /
        # mcp_* exactly like the review one. Without this exemption a hardened
        # install could not investigate at all (the default would turn every
        # --web call into the refusal above).
        args.sandbox = "read-only"

    if args.review_web and args.sandbox != "read-only":
        # The review web profile replaces the read-only REVIEW profile; there
        # is nothing for it to replace on any other posture.
        log(f"--review-web is the read-only review route's web condition and "
            f"needs --sandbox read-only (got {args.sandbox or 'no --sandbox'})")
        return EXIT_ARG_ERROR

    if args.sandbox == "read-only" and args.approval_mode == "auto_edit":
        log(f"--sandbox read-only conflicts with --approval-mode {args.approval_mode} "
            "(a write-auto-approving mode). Use --approval-mode default with read-only.")
        return EXIT_ARG_ERROR
    # ONE complete review profile per call: the web one under --review-web.
    review_policy = _READONLY_WEB_POLICY if args.review_web else _READONLY_POLICY
    if args.sandbox == "read-only" and not review_policy.is_file():
        log(f"read-only policy file missing: {review_policy}")
        return EXIT_ARG_ERROR

    if (args.sandbox == "workspace-write" or args.approval_mode == "auto_edit") \
            and not args.cwd:
        # Write-posture directory precondition (owner ruling 2026-08-26,
        # closing the codex/claude symmetry gap): a write-enabled dispatch's
        # blast radius must be an isolated directory, never the wrapper's
        # inherited cwd — claude_wrapper (workspace-write) already carries the
        # same guard, and so does codex_wrapper (workspace-write); gemini was
        # the one write-capable wrapper without it. The read-only/auto_edit CONFLICT
        # above still fires first (more specific diagnosis).
        log("--sandbox workspace-write / --approval-mode auto_edit requires --cwd "
            "(write-enabled dispatch: the blast radius must be an isolated "
            "directory, never the wrapper's inherited cwd)")
        return EXIT_ARG_ERROR

    gemini_bin = require_binary("gemini")
    ctx["cmd"] = [gemini_bin]

    def _refuse(token: str, reason: str, version: Optional[str]) -> int:
        # A pre-spawn refusal is a TERMINAL RECORD like any failed run: the
        # summary line below, an audit row and the failure run-log, carrying
        # the version observed before the refusal (C65) and a not-started
        # receipt (nothing ran).
        code = map_classification_to_exit(token)   # unknown -> 1, the refusals -> 65
        result = RunResult(code, "", reason + "\n", 0.0,
                           classification=token, extraction_error=reason,
                           spawned=False, dispatch_attempt=args.attempt,
                           prompt_file_resolved=_prompt_file_resolved,
                           requested_model=args.model)
        result.vendor_version = version
        result.review_web = args.review_web
        log(f"[wrapper] gemini {token} exit={code} "
            f"vendor=-1 elapsed=0.0s"
            + _summary_tail(args.attempt, _prompt_file_resolved, args.model))
        audit("gemini", [gemini_bin], args.prompt, result)
        run_log_path = emit_run_log("gemini", sys.argv, [gemini_bin], args.prompt, result)
        if run_log_path is not None:
            log(f"run-log: {run_log_path}")
        return code

    # R-AUTH gate (spec C37) — EVERY posture, before any vendor process: an
    # observed API-key-shaped auth class is `oauth-env` (65), remedy = the
    # owner's browser re-login; never a flag change that skips the gate.
    auth_refusal = _auth_refusal(args.cwd)
    if auth_refusal is not None:
        log(auth_refusal)
        return _refuse("oauth-env", auth_refusal, None)

    # Review-route preflight — refuses BEFORE any vendor dispatch (C16).
    probed_version = None
    if args.sandbox == "read-only":
        # The pre-dispatch vendor probes run in the record-only signal mode a
        # dispatch uses (C1 / R-TERMINAL): a SIGTERM / SIGHUP during them ends
        # through the interrupted-run record, never a bare 128 + signum exit.
        prev_dispatch = _SIGNAL_STATE["dispatch"]
        _SIGNAL_STATE["dispatch"] = True
        try:
            refusal, probed_version = _review_preflight(gemini_bin, args.cwd,
                                                        args.model)
        finally:
            # a signal recorded during the probe keeps the record-only mode on
            # until its refusal is written (C1: a second signal never loses it)
            if _SIGNAL_STATE["signum"] is None:
                _SIGNAL_STATE["dispatch"] = prev_dispatch
        probe_signum = None if prev_dispatch else _SIGNAL_STATE["signum"]
        if probe_signum is not None:
            _SIGNAL_STATE["signum"] = None
            why = (f"wrapper interrupted ({signal.Signals(probe_signum).name}) during "
                   f"the review preflight probe — nothing was dispatched")
            log(why)
            return _refuse("unknown", why, probed_version)
        if refusal is not None:
            log(refusal)
            # The canonical one-line summary the dispatch SKILLs grep, with the
            # classification token the refusal maps to. `config-conflict` is a
            # terminal class (EXIT_TERMINAL 65): the operator changes the
            # install or the posture — a retry would fail identically.
            #
            # THE TAIL COMES FROM THE SHARED FORMATTER (gate-1 r10 row
            # r10-11). This line was hand-built and carried `attempt=` only,
            # so it dropped the C28 `prompt_file=` field although the
            # resolved absolute path was already in hand — and this refusal
            # is PRE-SPAWN, so its own records are the only ones the dispatch
            # writes (`_refuse` writes this line, an audit row and the failure
            # run-log), and this line is the one the dispatch SKILLs read. The
            # one question C28 exists to answer went unrecorded on the line
            # where the caller looks. `_summary_tail` also owns the redaction
            # rule and the free-text escaping (row r9-3), so building the tail
            # by hand here silently opted out of both.
            return _refuse("config-conflict", refusal, probed_version)

    if args.web:
        # C29: the web-evidence rule rides the END of the prompt on every
        # research dispatch — after every refusal above, so the clause never
        # rescues a dispatch that should not run, and after the caller's own
        # text, because a rule at the START of a long prompt is the one most
        # likely dropped. `args.prompt` is what audit/run-log record, so the
        # record shows the prompt AS SENT.
        args.prompt = args.prompt + "\n\n" + GEMINI_WEB_EVIDENCE_CLAUSE
    # The engine gets the caller's text alone; build_cmd appends the clause
    # LAST after whatever the engine adds (schema instruction, repair notice),
    # so no caller text is ever moved or stripped (C29).
    engine_prompt = (args.prompt[:-len("\n\n" + GEMINI_WEB_EVIDENCE_CLAUSE)]
                     if args.web else args.prompt)

    pydantic_cls = None
    if args.pydantic:
        try:
            pydantic_cls = load_pydantic_class(args.pydantic)
        except Exception as e:
            log(f"--pydantic load failed: {e}")
            return EXIT_ARG_ERROR

    def build_cmd(effective_prompt: str) -> list[str]:
        if args.web:
            # C29: the host-appended clause is LAST, after every instruction.
            effective_prompt = effective_prompt + "\n\n" + GEMINI_WEB_EVIDENCE_CLAUSE
        cmd = [
            gemini_bin,   # resolved/pinned path (finding #3) — never a bare name
            "-p", effective_prompt,
            "--approval-mode", args.approval_mode,
            "--output-format", "json",
        ]
        if args.model:
            cmd += ["-m", args.model]
        if args.skip_trust:
            cmd.append("--skip-trust")
        if args.sandbox == "read-only":
            cmd += ["--policy", str(review_policy)]
        elif args.web:
            # Investigation profile (C29). Mutually exclusive with the review
            # policy by the refusal above, so exactly one --policy is attached.
            cmd += ["--policy", str(_RESEARCH_POLICY)]
        return cmd

    result = run_cli_with_retry(
        "gemini",
        build_cmd,
        engine_prompt,
        cwd=args.cwd,
        timeout=args.timeout,
        pydantic_cls=pydantic_cls,
        last_msg_path=None,
        repair_mode=args.repair_mode,
        dispatch_attempt=args.attempt,
        prompt_file_resolved=_prompt_file_resolved,
        requested_model=args.model,
    )
    ctx["result"] = result

    # The OBSERVED CLI version for the transport receipt (C9/C16): probed from
    # the SAME resolved binary the dispatch then executed, moments earlier — an
    # observation of the binary, never of the request. Only the review route
    # probes, so other postures keep `cli_version: null` (= not observed).
    if probed_version:
        result.vendor_version = probed_version

    audit_cmd = build_cmd(engine_prompt)
    ctx["cmd"] = audit_cmd
    # THE PAYLOAD IS DECIDED BEFORE THE AUDIT ROW (gate-1 r7 rows r7-c2 /
    # r7-k5): an answer this host cannot carry on the payload channel is not
    # an `ok` run, and the record must say so instead of being written first
    # and contradicted by a traceback at the tail.
    _pre_payload_classification = result.classification
    if pydantic_cls and result.validated is not None:
        payload = _payload_or_demote(
            "gemini", result,
            json.dumps(result.validated, ensure_ascii=False) + "\n",
            result.validated)
    else:
        out = result.final_answer or ""
        if out and not out.endswith("\n"):
            out += "\n"
        payload = _payload_or_demote("gemini", result, out)
    # THE SUMMARY LINE IS CORRECTED BY A SECOND EMISSION (gate-1 r8 row
    # r8-5): the canonical line was printed inside run_cli_with_retry, i.e.
    # BEFORE the demotion above, so without this the LAST `[wrapper] gemini`
    # line the dispatch SKILL parses still said `ok exit=0` for a run that
    # exits 1 with an empty stdout.
    if result.classification != _pre_payload_classification:
        _emit_canonical_summary("gemini", result)

    # R-REVIEW-WEB (case C32): a review leg dispatched with web is recorded.
    result.review_web = args.review_web
    audit("gemini", audit_cmd, args.prompt, result)
    ctx["recorded"] = True

    if args.debug:
        debug_log("gemini", args.prompt, result)

    # Per-execution run-log (failure only; a v2 review attempt with
    # TRIAD_REVIEW_LOG_DIR: every outcome) — dispatch SKILL input artifact.
    run_log_path = emit_run_log("gemini", sys.argv, audit_cmd, args.prompt, result)
    if run_log_path is not None:
        log(f"run-log: {run_log_path}")

    # Stdout = the UTF-8 BYTES built above, never a locale re-encoding.
    _emit_payload(payload)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
