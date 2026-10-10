#!/usr/bin/env python3
"""roster_v2.py — the v2 named-roster resolver for host A's cross-family review.

Reads the SHIPPED default roster (`spec/review-legs.default.json`: three enabled
entries, one per family — claude / codex / google), merges the project override
(`<worktree>/.claude/triad-review-legs.json` — host A's own location; D-5 renamed
nothing on A) BY NAME, validates both documents against the vendored canonical
contract (`spec/contracts/review-legs.schema.json`, Draft 2020-12), resolves the
Google route, and renders each entry's dispatch (wrapper argv for codex / agy /
gemini, a native in-session Agent spawn for claude).

Rules this file implements (shared spec `reference/review-rules.md`):
  * R-ROSTER — every leg is an ordinary entry with its own vendor, acceptance
    label and timeout; the leg count is variable; NO leg carries a special rule.
    `acceptance` is operator DATA: no behaviour is derived from it here.
  * R-GOOGLE — agy and gemini are two CLIs of ONE family. Host A's shipped
    resolution: explicit pin, else agy if installed, else gemini, else skip and
    log. The resolved route is frozen for the attempt; a started leg never
    switches route, and "neither installed" is never agreement.
  * R-REVIEW-WEB (case C32) — the round's BOUND `review_web_authorized`
    (`DispatchCtx.review_web_authorized`) decides each route's launch switch:
    true adds codex `--search`, agy / gemini `--review-web` and the claude
    preset's web twin (`CLAUDE_WEB_TWINS`); false keeps the no-web argv and
    dispatches a directly named web preset as its no-web base preset. The
    claude leg selects only a preset this host ships, and every shipped
    preset has a twin, so no claude leg runs as a silent no-web leg. The agy
    argv never carries the investigation `--web` (R-INVEST).
  * R-BIND — every wrapper dispatch's env names the attempt's own run-log
    namespace (`TRIAD_REVIEW_LOG_DIR=<attempt>/logs`); the wrapper's run-log
    there is the receipt of the argv it ran with, compared by `collect_v2`.
  * PRD "Configuration and dispatch" — merge objects field by field, replace
    scalars and arrays; reject duplicate names, unknown properties, invalid
    vendor blocks and unresolved placeholders; validate the COMPLETE resolved
    roster, not only the override; never translate an agy slug or effort into an
    unsupported Gemini argument (gemini receives no effort flag).

Model slugs and effort tiers live in the DATA files, never here
(`~/.claude/CLAUDE.md` § Web search rules — no vendor model IDs in code).

Scope (R-ROSTER, PRD): the resolver reads the SHIPPED defaults plus the
PROJECT override, and nothing else.

CLI:
    python3 roster_v2.py resolve <abs-worktree>
        -> stdout: one JSON document {source, enabled, startable, skipped,
           families, legs, warnings}
        -> exit 0 resolved / 2 refused (one stderr line) / 64 jsonschema missing

The Google chain probes the real PATH (`shutil.which`); a test controls which
CLIs are installed through PATH alone.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # presence gate — the canonical contract is Draft 2020-12
    import jsonschema
except ImportError:  # pragma: no cover - exercised by the install hint path
    jsonschema = None

EXIT_REFUSE = 2
EXIT_NO_JSONSCHEMA = 64

SPEC_DIR = Path(__file__).resolve().parents[1] / "spec"
DEFAULTS_PATH = SPEC_DIR / "review-legs.default.json"
SCHEMA_PATH = SPEC_DIR / "contracts" / "review-legs.schema.json"
VERDICT_SCHEMA_PATH = SPEC_DIR / "contracts" / "leg-verdict.schema.json"

SCHEMA_ID_V2 = "triad-review-legs.v2"
PROJECT_OVERRIDE_REL = (".claude", "triad-review-legs.json")

# The PRODUCER schema projection (PRD: "the projection aids generation; it
# never admits"). Every transform below was forced by a LIVE vendor probe
# (measured 2026-09-21); none of them is a preference. Local admission
# (verdict_v2.py) still validates every reply against the FULL contract, so
# nothing removed here can widen what is admitted.
#
# TOP-LEVEL drops: `$schema`/`$id` are meta a provider's structured-output
# mode rejects, and the top-level `allOf` carries cross-field rules a producer
# cannot express.
PROJECTION_DROP_KEYS = ("$schema", "$id", "allOf")
# DEEP drops, at ANY depth. `not` — codex refused the contract with
# `invalid_json_schema: Invalid schema for response_format
# 'codex_output_schema': In context=('not',), schema must have a 'type' key.`
# `uniqueItems` — dropped in the same probe variant; array uniqueness is a
# canonical-admission rule, never a generation constraint.
PROJECTION_DEEP_DROP_KEYS = ("not", "uniqueItems")
# OPTIONAL properties the projection cannot express, as paths into the
# projected document. codex requires every property to be listed in
# `required`: with `not`/`uniqueItems` already gone it still refused with
# `Invalid schema for response_format 'codex_output_schema': In context=(),
# 'required' is required to be supplied and to be an array including every key
# in properties. Missing 'correction'.` `correction` is NOT in the contract's
# `required`, so dropping the property (rather than forcing it required) is
# the transform that leaves every other rule intact.
PROJECTION_DROPPED_OPTIONAL_PROPERTIES = (
    ("$defs", "finding", "properties", "correction"),
)
# `properties.route` rewritten: Gemini function-declaration schemas reject a
# `null` member inside `enum` — agy refused the contract with
# `INVALID_ARGUMENT (code 400): ...properties[route].enum[2]: cannot be
# empty`. The anyOf form is the same value set, expressed so both families
# accept it. Read-only: never mutated, only serialized.
PROJECTION_ROUTE_ANYOF = {
    "anyOf": [{"type": "string", "enum": ["agy", "gemini"]}, {"type": "null"}]
}
PROJECTED_SCHEMA_NAME = "schema.projected.json"

# Vendor -> the adapter blocks an entry of that vendor may carry (the same
# split the contract's `resolvedLeg` encodes; duplicated here so the refusal
# message names the offending block instead of quoting a schema sub-path).
VENDOR_BLOCKS = {
    "claude": ("claude",),
    "codex": ("codex",),
    "google": ("google", "agy", "gemini"),
}
ALL_BLOCKS = ("claude", "codex", "google", "agy", "gemini")
REQUIRED_LEG_FIELDS = ("name", "vendor", "enabled", "acceptance", "timeout_s")
SCALAR_LEG_FIELDS = ("vendor", "enabled", "acceptance", "timeout_s", "note")

# Adapter capability vocabularies — the wrappers' own choice lists, not model
# catalogs: codex_wrapper.py `--reasoning` and antigravity_wrapper.py
# `--effort`. There is no claude tier list: host A cannot apply one, so
# `claude.effort` is REFUSED rather than validated against a vocabulary
# (gate-1 r3 row r3-4).
CODEX_REASONING = ("low", "medium", "high", "xhigh", "max")
AGY_EFFORT = ("low", "medium", "high")

GOOGLE_ROUTES = ("agy", "gemini")
GOOGLE_SKIP_NONE = ("no Google CLI installed — skip and log (R-GOOGLE); "
                    "never agreement")
# A placeholder ANYWHERE in a value, not only a value that IS one: an
# operator's half-edited slug ("pro-<slug>-high") would otherwise reach the
# vendor as a literal model name.
PLACEHOLDER_RE = re.compile(r"<[^<>\n]+>")
# R-ROSTER On A, R-REVIEW-WEB (cases C12, C32): THE CLOSED LIST of reviewer
# presets this host ships (`agents/<name>.md`), each base preset with its web
# twin. A claude entry names one of the six by its BARE name — the host
# scopes it in a plugin install (`review_scratch._qualify_claude_agent_id`) —
# and any other name is refused at resolve: `subagent_type: None` would spawn
# the layout default (the gating reviewer), and a preset this host does not
# ship cannot be bound to the round. Model and effort live only in the preset
# files (a different model or effort is a different shipped preset); a twin
# maps to itself under a true review-web condition and to its base under a
# false one.
CLAUDE_WEB_TWINS = {
    "cross-family-review-reviewer": "cross-family-review-reviewer-web",
    "cross-family-review-reviewer-high": "cross-family-review-reviewer-high-web",
    "cross-family-review-reviewer-max": "cross-family-review-reviewer-max-web",
}
# A shipped preset's two pins, one line each in its frontmatter (the shape the
# build-time check of the shipped files fixes; no YAML is parsed).
_PRESET_PIN_RE = re.compile(r"^(model|effort): (\S+)$", re.M)
# This install's own layout root (the dev tree's `.claude/`, a plugin's root):
# its `agents/` holds the presets the install ships.
_LAYOUT_ROOT = Path(__file__).resolve().parents[3]


class RosterError(Exception):
    """A refusal: the roster cannot be resolved (CLI exit 2, one stderr line)."""


@dataclass(frozen=True)
class Entry:
    """One fully resolved roster entry."""

    name: str
    vendor: str
    enabled: bool
    acceptance: str
    timeout_s: int
    note: str | None = None
    claude: dict | None = None
    codex: dict | None = None
    google: dict | None = None
    agy: dict | None = None
    gemini: dict | None = None
    route: str | None = None
    skipped_reason: str | None = None


@dataclass(frozen=True)
class Resolved:
    """The resolved roster plus its provenance.

    `enabled` is what the operator switched ON; `startable` is what can
    actually be dispatched (enabled AND not skipped). `families` counts
    STARTABLE entries only — a Google leg skipped for a missing CLI is not a
    family that reviewed anything, and counting it would let a two-family
    round look like a three-family one.
    """

    legs: list[Entry]
    enabled: list[Entry]
    families: set[str]
    source: str
    warnings: list[str] = field(default_factory=list)
    startable: list[Entry] = field(default_factory=list)


@dataclass(frozen=True)
class DispatchCtx:
    """Everything the caller (the leader / `prepare --v2`) fixes for one attempt."""

    worktree: Path
    packet_dir: Path
    prompt_file: Path
    attempt_dir: Path
    wrapper_dir: Path
    timeout_override: int | None = None
    # The dispatch attempt number this invocation IS (prepare: 1; the Kth
    # retry: K+1). It rides every wrapper argv as `--attempt`, so the
    # wrapper's audit row and run-log record the real attempt instead of
    # defaulting to 1 on every retry (gate 1 r2 row r2-4).
    attempt: int = 1
    # The round's BOUND review-web condition (R-REVIEW-WEB, case C32): true
    # selects each route's web launch switch, false keeps the no-web argv.
    review_web_authorized: bool = False


@dataclass(frozen=True)
class Dispatch:
    """How ONE entry is actually started (built here, executed by the caller)."""

    kind: str  # "native" (an in-session claude Agent) | "wrapper"
    argv: list[str] | None
    env: dict
    native: dict | None
    stdout_path: Path
    stderr_path: Path
    read_audit_path: Path | None = None
    # The producer schema projection handed to the vendor (codex
    # --output-schema-file / agy --json-schema-file). None on the routes that
    # take none (claude native, gemini). `schema_file` is the TARGET PATH the
    # argv points at and `schema_text` is the exact bytes to put there —
    # rendering never writes them, so the caller decides WHEN (after its own
    # pre-mutation boundary). The ONE writer is
    # `review_scratch.v2_write_attempt`, which allocates the attempt directory
    # exclusively and writes every record through `_write_new_file`; this
    # module has no writer of its own (gate-1 r3 row r3-11).
    schema_file: Path | None = None
    schema_text: str | None = None


# ---------------------------------------------------------------------------
# schema / data loading
# ---------------------------------------------------------------------------
def _require_jsonschema():
    if jsonschema is None:
        print("roster_v2: python3 jsonschema (Draft 2020-12) is required — "
              "Mac: pip3 install --user --break-system-packages 'jsonschema>=4'"
              " | Ubuntu 24.04: sudo apt install python3-jsonschema",
              file=sys.stderr)
        raise SystemExit(EXIT_NO_JSONSCHEMA)
    return jsonschema


def _flat(text: str) -> str:
    """Collapse a multi-line validator message to the one-line stderr contract."""
    return " ".join(str(text).split())


def _read_regular_file(path: Path, label: str) -> bytes:
    """The bytes of a plain regular file, or a RosterError naming it.

    The read is `verdict_v2._read_regular_file_no_symlink`, the review libs'
    one hardened reader, imported from this file's directory (the
    `collect_v2._load_sibling` rule: an already-loaded `verdict_v2` is
    reused). A symlink at a config path is refused outright, dangling or not
    — a dangling one must never look like "no override" — and EVERY OSError,
    including EACCES on the parent directory, becomes this one-line refusal,
    never a traceback.
    """
    verdict_v2 = sys.modules.get("verdict_v2")
    if verdict_v2 is None:
        spec = importlib.util.spec_from_file_location(
            "verdict_v2", Path(__file__).resolve().parent / "verdict_v2.py")
        verdict_v2 = importlib.util.module_from_spec(spec)
        sys.modules["verdict_v2"] = verdict_v2
        try:
            spec.loader.exec_module(verdict_v2)
        except BaseException:
            sys.modules.pop("verdict_v2", None)
            raise
    path = Path(path)
    data, reason = verdict_v2._read_regular_file_no_symlink(path)
    if reason is None:
        return data
    unreadable = f"cannot read {path}: "
    if reason.startswith(unreadable):
        raise RosterError(
            f"{label} {path} is unreadable: {reason[len(unreadable):]}")
    if reason == f"{path} is a symlink, refusing to read":
        raise RosterError(f"{label} {path} is a symlink — symlinked roster "
                          f"refused (the target is not the configured file)")
    raise RosterError(f"{label} {path} is not a regular file — refused")


def _read_json(path: Path, label: str) -> dict:
    try:
        raw = _read_regular_file(path, label).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RosterError(f"{label} {path} is not UTF-8: {exc}") from exc
    try:
        doc = json.loads(raw)
    # EVERY WAY THE PARSE CAN FAIL IS A REFUSAL (gate-1 r9 row r9-7).
    # `json.loads` raises more than ValueError: a document nested past the
    # interpreter's recursion limit raises RecursionError, which is NOT a
    # ValueError, so it escaped `main()`'s `RosterError` arm as a traceback
    # at exit 1 — from the loader whose every other failure is one refusal
    # line at exit 2. UnicodeDecodeError IS a ValueError and is named anyway:
    # the tuple is the rule, not a reader's memory of the class hierarchy.
    # Same tuple `collect_v2._read_record` already carries (row r7-k3).
    except (ValueError, RecursionError, UnicodeDecodeError) as exc:
        raise RosterError(f"{label} {path} is not JSON: {_flat(exc)}") from exc
    if not isinstance(doc, dict):
        raise RosterError(f"{label} {path} must be a JSON object, "
                          f"got {type(doc).__name__}")
    return doc


def _schema() -> dict:
    return _read_json(SCHEMA_PATH, "vendored contract")


def _validate(doc: dict, schema: dict, label: str) -> None:
    js = _require_jsonschema()
    validator = js.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        err = errors[0]
        where = "/".join(str(p) for p in err.absolute_path) or "<root>"
        raise RosterError(f"{label} is invalid at {where}: {_flat(err.message)}")


def _resolved_roster_schema(schema: dict) -> dict:
    """The `$defs/resolvedRoster` sub-schema, re-rooted so its `$ref`s resolve."""
    resolved = dict(schema["$defs"]["resolvedRoster"])
    resolved["$defs"] = schema["$defs"]
    return resolved


def load_defaults() -> dict:
    """Host A's shipped default roster, validated as a COMPLETE resolved roster.

    A corrupt shipped default is a hard failure: nothing downstream may run on a
    half-readable roster.
    """
    doc = _read_json(DEFAULTS_PATH, "shipped default roster")
    try:
        _validate(doc, _resolved_roster_schema(_schema()), "shipped default roster")
    except RosterError as exc:
        raise RosterError(f"shipped default roster is corrupt — {exc}") from exc
    return doc


def project_override_path(worktree: Path) -> Path:
    """Host A's project override location (D-5 renamed nothing on A)."""
    return Path(worktree).joinpath(*PROJECT_OVERRIDE_REL)


def _override_present(path: Path) -> bool:
    """True when SOMETHING sits at the override path — a symlink included.

    `Path.exists()` follows links, so a DANGLING symlink there reads as "no
    override" and the round silently runs the shipped defaults; `lstat` sees
    the link itself and the hardened read then refuses it.
    """
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RosterError(f"project override {path} is unreadable: "
                          f"{exc}") from exc
    return True


# ---------------------------------------------------------------------------
# merge + capability refusals
# ---------------------------------------------------------------------------
def _merge_leg(base: dict, over: dict) -> dict:
    """Objects merge field by field; scalars and arrays are REPLACED (PRD)."""
    merged = dict(base)
    for key, value in over.items():
        if (isinstance(value, dict) and isinstance(merged.get(key), dict)):
            block = dict(merged[key])
            block.update(value)
            merged[key] = block
        else:
            merged[key] = value
    return merged


def _strings(obj) -> list:
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings(v)]
    return [obj] if isinstance(obj, str) else []


def _check_required(leg: dict, known_names: set) -> None:
    for fieldname in REQUIRED_LEG_FIELDS:
        if fieldname not in leg:
            name = leg.get("name", "<unnamed>")
            origin = ("is a NEW name and must be a complete leg"
                      if name not in known_names else "is incomplete")
            raise RosterError(f"roster entry '{name}' {origin}: missing required "
                              f"field '{fieldname}'")


def _check_blocks(leg: dict) -> None:
    vendor = leg["vendor"]
    allowed = VENDOR_BLOCKS.get(vendor)
    if allowed is None:
        # An unknown vendor is the resolved schema's refusal to word: this
        # table has no row for it, and guessing one would name the wrong
        # block. Runs first, so it must never mask that message.
        return
    for block in ALL_BLOCKS:
        if block in leg and block not in allowed:
            raise RosterError(
                f"roster entry '{leg['name']}': vendor block '{block}' is not "
                f"allowed on a {vendor} entry (a {vendor} entry carries: "
                f"{', '.join(allowed)})")
    if vendor == "google" and not any(b in leg for b in GOOGLE_ROUTES):
        raise RosterError(
            f"roster entry '{leg['name']}': a google entry needs an 'agy' or a "
            f"'gemini' block (the Google CLI is named only by its route block)")


def _claude_web_twin(agent, web: bool) -> str:
    """The shipped preset a claude entry's native spawn names: under a true
    review-web condition the web twin of `agent`, under a false one its base
    preset (a twin maps to itself, resp. to its base) — or a RosterError when
    `agent` is not one of the presets this host ships (`CLAUDE_WEB_TWINS`)."""
    bases = {twin: base for base, twin in CLAUDE_WEB_TWINS.items()}
    base = bases.get(agent, agent) if isinstance(agent, str) else None
    if base not in CLAUDE_WEB_TWINS:
        raise RosterError(
            f"{agent!r} is not a reviewer preset this host ships — name one "
            f"of {', '.join(sorted([*CLAUDE_WEB_TWINS, *bases]))} by its bare "
            f"name (the host scopes it); a preset fixes its own model and "
            f"effort, so another model or effort is another shipped preset")
    return CLAUDE_WEB_TWINS[base] if web else base


def _claude_preset(named: str, web: bool) -> dict:
    """`{agent, file_sha256, model, effort}` of the shipped preset a claude
    entry spawns (`_claude_web_twin`), read from this install's own
    `agents/<agent>.md` — or a RosterError (R-ROSTER, cases C12 / C19 / C33).
    `prepare` binds it into the round record; the file's bytes are also in
    the toolkit map (`_toolkit_map`) that `collect` and `retry` compare.
    `model` and `effort` come from the same bytes, for the record and the
    roster preview."""
    agent = _claude_web_twin(named, web)
    path = _LAYOUT_ROOT / "agents" / f"{agent}.md"
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RosterError(f"the shipped preset {path} cannot be read "
                          f"({exc.strerror or exc}) — reinstall this host") \
            from exc
    head = data.decode("utf-8", "replace").split("\n---", 1)[0]
    found = _PRESET_PIN_RE.findall(head)
    pins = dict(found)
    if len(found) != 2 or len(pins) != 2:
        raise RosterError(f"the shipped preset {path} does not carry exactly "
                          f"one `model:` and one `effort:` line — reinstall "
                          f"this host")
    return {"agent": agent, "file_sha256": hashlib.sha256(data).hexdigest(),
            "model": pins["model"], "effort": pins["effort"]}


def _toolkit_map() -> dict[str, str]:
    """`{relpath: sha256}` of this install's review toolkit — every regular
    file directly under `lib/` (`.py` and `.sh`), the vendored `spec/**` and
    the six shipped reviewer presets — relpaths relative to `_LAYOUT_ROOT`,
    keys sorted, `__pycache__` / `*.pyc` skipped, or a RosterError naming an
    unreadable file (R-PREPARE, R-RETRY; case C19). `prepare` records it;
    `collect` and `retry` compare it with this one."""
    skill = Path(__file__).resolve().parents[1]
    files = [*(p for p in skill.joinpath("lib").iterdir()
               if p.is_file() and p.suffix != ".pyc"),
             *(p for p in skill.joinpath("spec").rglob("*")
               if p.is_file() and "__pycache__" not in p.parts
               and p.suffix != ".pyc"),
             *(_LAYOUT_ROOT / "agents" / f"{agent}.md"
               for pair in CLAUDE_WEB_TWINS.items() for agent in pair)]
    found = {}
    for path in files:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            continue  # an absent file is absent from the map, so it compares
        except OSError as exc:
            raise RosterError(f"the installed toolkit file {path} cannot be "
                              f"read ({exc.strerror or exc}) — reinstall "
                              f"this host") from exc
        found[path.relative_to(_LAYOUT_ROOT).as_posix()] = \
            hashlib.sha256(data).hexdigest()
    return dict(sorted(found.items()))


def _check_capabilities(leg: dict) -> None:
    """Refusals EVERY entry must pass — enabled or not.

    Every configured leg is validated, enabled or not: a disabled entry is a
    leg the operator intends to switch on later, so
    letting its slug rot unnoticed only moves the failure to the round that
    finally enables it (gate 1, row 17).

    A claude entry names a preset this host ships (`_claude_web_twin`); every
    shipped preset has a web twin, so the claude route supports web under
    either condition (R-REVIEW-WEB, case C32).
    """
    name = leg["name"]
    for value in _strings({k: v for k, v in leg.items() if k != "note"}):
        hit = PLACEHOLDER_RE.search(value)
        if hit:
            raise RosterError(
                f"roster entry '{name}': unresolved placeholder "
                f"{hit.group(0)!r} in {value!r} — replace it with a real value "
                f"from the route's catalog or remove the entry")
    if leg.get("vendor") == "claude":
        # An exact member of the closed list: a trailing newline or any other
        # byte (gate-1 r5 row r5-4) is not a member, so it never rides into
        # the spawn instruction.
        try:
            _claude_web_twin((leg.get("claude") or {}).get("agent"), False)
        except RosterError as exc:
            raise RosterError(
                f"claude entry '{name}' requires claude.agent naming a "
                f"reviewer preset (the layout default would be the gating "
                f"reviewer): {exc}") from None
    gemini = leg.get("gemini") or {}
    if gemini.get("effort") is not None:
        raise RosterError(
            f"roster entry '{name}': gemini takes no effort flag on host A "
            f"(gemini_wrapper.py has no --effort); set gemini.effort to null")
    codex = leg.get("codex") or {}
    if codex.get("reasoning") is not None and codex["reasoning"] not in CODEX_REASONING:
        raise RosterError(
            f"roster entry '{name}': codex.reasoning {codex['reasoning']!r} is "
            f"not a codex_wrapper.py --reasoning choice "
            f"({', '.join(CODEX_REASONING)})")
    claude = leg.get("claude") or {}
    if claude.get("effort") is not None:
        # Same shape as the gemini rule above, and for the same reason: the
        # HOST cannot apply the value. A claude leg is a NATIVE in-session
        # Agent spawn, and that spawn has no effort parameter — the effort
        # tier is pinned INSIDE the named agent preset (owner model-tier
        # policy: effort has no per-invocation override, so a different tier
        # is a different agent id). Accepting
        # the field validated it, recorded it in `Dispatch.native` and then
        # dropped it on the floor, which reads as a configured tier that
        # silently never applied (gate-1 r3 row r3-4).
        raise RosterError(
            f"roster entry '{name}': claude.effort is not applicable on host A "
            f"— the effort tier is pinned by the named agent preset (a "
            f"different tier is a different agent id); set claude.effort to "
            f"null")
    if claude.get("model") is not None:
        # The SIBLING field (gate-1 r4 row r4-3). The Agent tool DOES take a
        # per-call `model`, and it outranks the subagent's `model`
        # frontmatter; host A's dispatch passes none (the printed native line
        # says so), so the MODEL rides in the named agent preset's
        # frontmatter exactly as the effort tier does.
        # Accepting the field validated it, recorded it in `Dispatch.native`
        # and then dropped it on the floor — a configured model that silently
        # never applied, which is the r3-4 defect one field over.
        raise RosterError(
            f"roster entry '{name}': claude.model is not applicable on host A "
            f"— the model is pinned by the named agent preset's frontmatter "
            f"and the native Agent spawn passes no `model` parameter (one "
            f"would override that pin); name a preset in claude.agent and set "
            f"claude.model to null")
    agy = leg.get("agy") or {}
    if agy.get("effort") is not None and agy["effort"] not in AGY_EFFORT:
        raise RosterError(
            f"roster entry '{name}': agy.effort {agy['effort']!r} is not an "
            f"antigravity_wrapper.py --effort choice ({', '.join(AGY_EFFORT)})")


def _resolve_google(leg: dict, which) -> tuple:
    """(route, skipped_reason) for ONE enabled google entry — R-GOOGLE.

    The chain is per ENTRY, not per host: an explicit pin wins; an entry that
    carries exactly ONE route block IS that route (a gemini-only entry does
    not become an agy entry because agy happens to be installed); only an
    entry carrying both blocks falls back to the host chain agy -> gemini.
    Every unusable outcome SKIPS THAT ENTRY — one entry's missing CLI is
    never a reason to refuse the whole roster.
    """
    pin = (leg.get("google") or {}).get("route")
    if pin:
        if which(pin):
            return pin, None
        return pin, (f"pinned Google route '{pin}' is not installed — skip and "
                     f"log (R-GOOGLE); a started leg never switches route, and "
                     f"this is never agreement")
    own = [route for route in GOOGLE_ROUTES if route in leg]
    if len(own) == 1:
        route = own[0]
        if which(route):
            return route, None
        return route, (f"this entry's only Google route '{route}' is not "
                       f"installed — skip and log (R-GOOGLE); never agreement")
    for candidate in GOOGLE_ROUTES:
        if which(candidate):
            return candidate, None
    return None, GOOGLE_SKIP_NONE


def resolve_roster(worktree: Path, which=shutil.which) -> Resolved:
    """The shipped defaults, merged with the project override, fully validated."""
    schema = _schema()
    defaults = load_defaults()
    legs = [dict(leg) for leg in defaults["legs"]]
    known = {leg["name"] for leg in legs}
    source = "defaults"

    shipped = {leg["name"]: dict(leg) for leg in legs}
    path = project_override_path(worktree)
    if _override_present(path):
        over = _read_json(path, "project override")
        _validate(over, schema, f"project override {path}")
        # An entry name becomes a DIRECTORY name (`results-r<N>/<name>/`) and
        # the macOS default volume folds case, so a repeat that differs only
        # in case would fail partway through `prepare`: refused here, once,
        # over the override document, before anything is created. The walk
        # knows the shipped names: an override spelled exactly like a shipped
        # entry merges into it, one differing only in case is refused.
        shipped_folded = {name.casefold(): name for name in shipped}
        seen = set()
        for leg in over["legs"]:
            name = leg["name"]
            folded = name.casefold()
            clash = shipped_folded.get(folded, name)
            if folded in seen or clash != name:
                where = (f"; clashes with the shipped entry '{clash}'"
                         if clash != name and folded not in seen else "")
                raise RosterError(f"project override {path} has duplicate leg "
                                  f"name '{name}' (case-folded{where}) — the "
                                  f"merge key and the results directory name "
                                  f"must be unique")
            seen.add(folded)
        by_name = {leg["name"]: i for i, leg in enumerate(legs)}
        for leg in over["legs"]:
            if leg["name"] in by_name:
                idx = by_name[leg["name"]]
                legs[idx] = _merge_leg(legs[idx], leg)
            else:
                legs.append(dict(leg))
        source = f"defaults+project:{path}"

    for leg in legs:
        _check_required(leg, known)
    # BEFORE the resolved-schema validation: an override that re-vendors a
    # shipped entry leaves that entry's SHIPPED adapter block in place, and
    # the schema reports only "'codex' is a required property" — the missing
    # block, never the inherited one that is the actual defect (gate 1 r2
    # row r2-7). `_check_blocks` names it. An unknown vendor has no block
    # table, so it falls through to the schema, which owns that vocabulary.
    for leg in legs:
        _check_blocks(leg)
    _validate({"schema": SCHEMA_ID_V2, "legs": legs},
              _resolved_roster_schema(schema), "resolved roster")

    entries: list[Entry] = []
    warnings: list[str] = []
    for leg in legs:
        route = None
        skipped = None
        _check_capabilities(leg)
        if leg["enabled"] and leg["vendor"] == "google":
            route, skipped = _resolve_google(leg, which)
            if route is not None and route not in leg:
                # Membership, never truthiness: `"agy": {}` IS a block (take
                # the wrapper defaults). A genuinely missing block skips THIS
                # entry — the rest of the roster still runs.
                skipped = (f"the resolved Google route '{route}' has no "
                           f"'{route}' block — skip and log (R-GOOGLE); the "
                           f"selected route must carry its own adapter block")
            if skipped:
                warnings.append(f"leg '{leg['name']}': {skipped}")
        entries.append(Entry(
            name=leg["name"], vendor=leg["vendor"], enabled=leg["enabled"],
            acceptance=leg["acceptance"], timeout_s=leg["timeout_s"],
            note=leg.get("note"), claude=leg.get("claude"),
            codex=leg.get("codex"), google=leg.get("google"),
            agy=leg.get("agy"), gemini=leg.get("gemini"),
            route=route, skipped_reason=skipped))

    enabled = [e for e in entries if e.enabled]
    if not enabled:
        # R-ROSTER / R-AGREE: the owner selects any NONEMPTY roster; a round
        # with no selected entry could never be agreement.
        raise RosterError("the selected roster is empty — no entry is "
                          "enabled; select at least one entry (R-ROSTER, "
                          "R-AGREE)")
    startable = [e for e in enabled if not e.skipped_reason]
    return Resolved(legs=entries, enabled=enabled,
                    families={e.vendor for e in startable}, source=source,
                    warnings=warnings, startable=startable)


# ---------------------------------------------------------------------------
# dispatch rendering (built, never executed, here — and never WRITTEN here:
# every function below is pure, so a caller can refuse a bad roster entry
# with nothing created; gate 1 r2 row r2-1)
# ---------------------------------------------------------------------------
def _token(value, what: str, *, absolute: bool = False) -> str:
    text = str(value)
    if not text or any(ch in text for ch in ("\n", "\r", "\0")):
        raise RosterError(f"{what} is not a usable command token: {text!r}")
    if absolute and not text.startswith("/"):
        # A relative path would be resolved by the VENDOR against its own
        # working directory, which is the reviewed worktree — a silently
        # different file from the one the caller meant.
        raise RosterError(f"{what} must be an ABSOLUTE path: {text!r}")
    return text


def _deep_drop(node):
    """The vendored contract with every `PROJECTION_DEEP_DROP_KEYS` member
    removed at any depth, byte-derived otherwise (same key order, same values).

    Naive by design: the drop is keyed on the MEMBER NAME wherever it appears,
    which is what the two vendors reject. The canonical contract names no
    property `not` or `uniqueItems`, so no real property is lost today; a
    future contract that added one would need this rule narrowed to schema
    positions, and the t12 projection axis would catch it.
    """
    if isinstance(node, dict):
        return {k: _deep_drop(v) for k, v in node.items()
                if k not in PROJECTION_DEEP_DROP_KEYS}
    if isinstance(node, list):
        return [_deep_drop(x) for x in node]
    return node


def projected_schema_text() -> str:
    """The producer schema projection BYTES — a pure read-and-transform.

    The projection is a PRODUCER projection for CLI GENERATION ONLY; admission
    stays the full canonical schema (`verdict_v2.py`). It is the vendored
    canonical contract transformed by exactly six steps, each forced by a live
    vendor probe (measured 2026-09-21, constants above): drop `$schema`/`$id`
    and the top-level `allOf` (`PROJECTION_DROP_KEYS`); drop every `not` and
    every `uniqueItems` at any depth (`PROJECTION_DEEP_DROP_KEYS`); drop the
    optional `correction` property of a finding
    (`PROJECTION_DROPPED_OPTIONAL_PROPERTIES` — it is not in `required`, so
    nothing else changes); and rewrite `properties.route` as
    `PROJECTION_ROUTE_ANYOF`. Everything else is byte-derived (same key order,
    `json.dumps(indent=2)`).

    The canonical rules removed here — the newline guards, the array
    uniqueness constraints, the SAFE/non-SAFE consistency `allOf` and the
    family-to-route coupling — are enforced at ADMISSION, so the projection
    can never widen what is accepted; what it CAN do is fail to express an
    optional member (a finding's `correction`), which is why it never admits.

    PURE: it reads the vendored contract and returns text. `render_dispatch`
    calls it so a Dispatch can carry the bytes without touching the
    filesystem (gate 1 r2 row r2-1); `review_scratch.v2_write_attempt` is the
    one writer that puts them on disk.
    """
    schema = _read_json(VERDICT_SCHEMA_PATH, "vendored verdict contract")
    projected = {k: _deep_drop(v) for k, v in schema.items()
                 if k not in PROJECTION_DROP_KEYS}
    for path in PROJECTION_DROPPED_OPTIONAL_PROPERTIES:
        node = projected
        for step in path[:-1]:
            node = node.get(step) if isinstance(node, dict) else None
        if not isinstance(node, dict) or path[-1] not in node:
            raise RosterError(f"vendored verdict contract has no "
                              f"{'/'.join(path)} — the producer projection is "
                              f"out of step with the contract it projects")
        del node[path[-1]]
    props = projected.get("properties")
    if not isinstance(props, dict) or "route" not in props:
        raise RosterError("vendored verdict contract has no properties/route — "
                          "the producer projection is out of step with the "
                          "contract it projects")
    # Assigning an existing key keeps its position; the shared constant is
    # serialized, never mutated.
    props["route"] = PROJECTION_ROUTE_ANYOF
    return json.dumps(projected, indent=2, ensure_ascii=False) + "\n"


def render_dispatch(entry: Entry, ctx: DispatchCtx) -> Dispatch:
    """The exact invocation for ONE entry — wrapper argv, or a native Agent spawn.

    The caller owns `wrapper_dir` (the dev tree's wrappers package, the
    export's `bin/`), so no install layout is pinned here.

    PURE: nothing is created, opened for writing or removed. The producer
    schema projection travels as `Dispatch.schema_text` (bytes) plus
    `Dispatch.schema_file` (the path the argv points at); the caller writes
    it after its own pre-mutation boundary.
    """
    if entry.skipped_reason:
        raise RosterError(f"roster entry '{entry.name}' is not startable: "
                          f"{entry.skipped_reason}")
    timeout = ctx.timeout_override or entry.timeout_s
    stderr_path = ctx.attempt_dir / "stderr.log"

    if entry.vendor == "claude":
        block = entry.claude or {}
        agent = block.get("agent")
        if isinstance(agent, str):
            # The preset's WEB TWIN under a true condition, its no-web base
            # under a false one (R-REVIEW-WEB); the record names it as
            # `subagent_type`.
            agent = _claude_web_twin(agent, ctx.review_web_authorized)
        return Dispatch(
            kind="native", argv=None, env={},
            # `effort` is recorded, and on host A it is ALWAYS null:
            # `_check_capabilities` refuses any other value, because the tier
            # rides in the named agent preset and this dispatch passes no
            # effort and no `model` parameter (row r3-4; a per-call model
            # would override the preset's pin). The key stays so the record shape
            # does not differ between hosts.
            native={"subagent_type": agent,
                    "model": block.get("model"),
                    "effort": block.get("effort")},
            stdout_path=ctx.attempt_dir / "raw.json", stderr_path=stderr_path)

    stdout_path = ctx.attempt_dir / "verdict.json"
    # THE RECEIPT NAMESPACE (R-BIND): with this env member the wrapper writes
    # its run-log — the argv it actually ran with — into the attempt's own
    # `logs/<cli>/runs/` on success too, and `collect` compares it with this
    # dispatch's argv, so a line edited before it ran never counts.
    logs_dir = _token(ctx.attempt_dir / "logs", "review log dir", absolute=True)

    def review_env() -> dict:
        return {"TRIAD_REVIEW_LOG_DIR": logs_dir}

    def pin(flag: str, value, what: str) -> str:
        # ONE option token (M-1): `--model=<v>` keeps a value shaped like an
        # option (`--help`, `-x`) out of the wrapper parser's option scan.
        return f"{flag}={_token(value, what)}"
    common_tail = ["--prompt-file",
                   _token(ctx.prompt_file, "prompt file", absolute=True),
                   "--cwd", _token(ctx.worktree, "worktree", absolute=True),
                   "--timeout", _token(timeout, "timeout"),
                   # Every wrapper takes `--attempt` and RECORDS it; without
                   # it every retry's audit row claimed attempt 1.
                   "--attempt", _token(ctx.attempt, "attempt")]

    if entry.vendor == "codex":
        block = entry.codex or {}
        # `--search` only for a true review-web condition (R-REVIEW-WEB); the
        # read-only sandbox stays. Never --pydantic (v2 admission runs on the
        # output file, in verdict_v2.py).
        argv = ["python3",
                _token(ctx.wrapper_dir / "codex_wrapper.py", "wrapper",
                       absolute=True),
                "--sandbox", "read-only"]
        if ctx.review_web_authorized:
            argv.append("--search")
        if block.get("reasoning"):
            argv += ["--reasoning", _token(block["reasoning"], "codex reasoning")]
        if block.get("model"):
            argv.append(pin("--model", block["model"], "codex model"))
        schema_file = ctx.attempt_dir / PROJECTED_SCHEMA_NAME
        argv += ["--output-schema-file",
                 _token(schema_file, "producer schema projection", absolute=True)]
        return Dispatch(kind="wrapper", argv=argv + common_tail,
                        env=review_env(),
                        native=None, stdout_path=stdout_path,
                        stderr_path=stderr_path, schema_file=schema_file,
                        schema_text=projected_schema_text())

    if entry.route == "agy":
        block = entry.agy or {}
        read_audit = ctx.attempt_dir / "read-audit.json"
        argv = ["python3",
                _token(ctx.wrapper_dir / "antigravity_wrapper.py", "wrapper",
                       absolute=True),
                "--sandbox", "read-only"]
        if ctx.review_web_authorized:
            # The wrapper's REVIEW web option: the research agent without the
            # investigation clause (R-REVIEW-WEB); never `--web` (R-INVEST).
            argv.append("--review-web")
        if block.get("model"):
            argv.append(pin("--model", block["model"], "agy model"))
        if block.get("effort"):
            argv.append(pin("--effort", block["effort"], "agy effort"))
        schema_file = ctx.attempt_dir / PROJECTED_SCHEMA_NAME
        argv += ["--json-schema-file",
                 _token(schema_file, "producer schema projection", absolute=True)]
        # The read audit is part of the agy leg's contract.
        return Dispatch(kind="wrapper", argv=argv + common_tail,
                        env={**review_env(),
                             "TRIAD_READ_AUDIT_FILE":
                             _token(read_audit, "read audit file", absolute=True)},
                        native=None, stdout_path=stdout_path,
                        stderr_path=stderr_path, read_audit_path=read_audit,
                        schema_file=schema_file,
                        schema_text=projected_schema_text())

    if entry.route == "gemini":
        block = entry.gemini or {}
        argv = ["python3",
                _token(ctx.wrapper_dir / "gemini_wrapper.py", "wrapper",
                       absolute=True),
                "--sandbox", "read-only", "--approval-mode", "default"]
        if ctx.review_web_authorized:
            # The complete web profile, never an overlay (R-REVIEW-WEB).
            argv.append("--review-web")
        if block.get("model"):
            argv.append(pin("--model", block["model"], "gemini model"))
        # No effort flag on this route, ever (PRD: never translate an agy effort
        # into an unsupported Gemini argument).
        return Dispatch(kind="wrapper", argv=argv + common_tail,
                        env=review_env(),
                        native=None, stdout_path=stdout_path,
                        stderr_path=stderr_path)

    raise RosterError(f"roster entry '{entry.name}': no dispatch for vendor "
                      f"{entry.vendor!r} route {entry.route!r}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _entry_json(entry: Entry) -> dict:
    return {"name": entry.name, "vendor": entry.vendor, "enabled": entry.enabled,
            "acceptance": entry.acceptance, "timeout_s": entry.timeout_s,
            "route": entry.route, "skipped_reason": entry.skipped_reason,
            "note": entry.note, "claude": entry.claude, "codex": entry.codex,
            "google": entry.google, "agy": entry.agy, "gemini": entry.gemini}


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="roster_v2.py", allow_abbrev=False,
        description="Resolve the v2 review roster (defaults + project override)")
    sub = parser.add_subparsers(dest="command", required=True)
    resolve_cmd = sub.add_parser("resolve", help="print the resolved roster JSON")
    resolve_cmd.add_argument("worktree", help="absolute worktree path")
    args = parser.parse_args(argv)

    try:
        resolved = resolve_roster(Path(args.worktree), which=shutil.which)
    except RosterError as exc:
        print(f"roster_v2: refused: {_flat(exc)}", file=sys.stderr)
        return EXIT_REFUSE
    # THE RESOLVED ROSTER IS PRINTED BEFORE DISPATCH (C12, A2): each startable
    # claude entry shows the model and effort its shipped preset pins, read
    # the way prepare reads them from BOTH files a round may spawn — the base
    # preset and its web twin (every round under the standing authorization
    # spawns the twin; the build-time check keeps the two pairs equal); a
    # file prepare could not bind is refused here the same way.
    legs = []
    for entry in resolved.legs:
        leg = _entry_json(entry)
        if entry.vendor == "claude" and entry.enabled \
                and not entry.skipped_reason:
            try:
                preset = _claude_preset(entry.claude["agent"], False)
                _claude_preset(entry.claude["agent"], True)
            except RosterError as exc:
                print(f"roster_v2: refused: roster entry '{entry.name}': "
                      f"{_flat(exc)}", file=sys.stderr)
                return EXIT_REFUSE
            leg["preset"] = {"model": preset["model"],
                             "effort": preset["effort"]}
        legs.append(leg)
    for warning in resolved.warnings:
        print(f"roster_v2: WARNING: {_flat(warning)}", file=sys.stderr)
    print(json.dumps({"source": resolved.source,
                      "enabled": [e.name for e in resolved.enabled],
                      "startable": [e.name for e in resolved.startable],
                      "skipped": [{"name": e.name, "reason": e.skipped_reason}
                                  for e in resolved.legs if e.skipped_reason],
                      "families": sorted(resolved.families),
                      "legs": legs,
                      "warnings": resolved.warnings}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
