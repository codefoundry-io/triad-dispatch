"""Render pinned fenced clauses; leave host I/O and native execution outside."""

from datetime import date
import hashlib
from importlib.resources import files
import json
import re

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .contracts import load_verified_bundle
from .errors import ContractError, PromptError
from .json_input import parse_json

PAYLOADS = ("prompts/common-clauses.md", "prompts/leg-codex.md", "contracts/review-kind.schema.json",
            "prompts/leg-claude.md", "prompts/leg-google.md", "prompts/investigation.md")
# These metavariables are literal shape documentation in the canonical Claude clause.
CLAUDE_LITERALS = {"echo", "echo integer", "non-empty", "repo-relative",
    "positive int or null", "one sentence", "concrete scenario", "verified evidence",
    "actually inspected repo-relative path", "unresolved necessary fact, or empty array when none",
    "END-VERDICT"}
PLACEHOLDER = r"<([^<>\n]+)>"
REPLACEMENTS = {"worktree", "brief-file", "packet-files", "review-id", "content-digest", "leg-name", "attempt"}


def _bundle():
    root = files("triad_dispatch_lib").joinpath("data", "prompt-bundle")
    try:
        return {name: raw.decode("utf-8") for name, raw in load_verified_bundle(root, PAYLOADS).items()}
    except UnicodeError:
        raise ContractError("Invalid prompt bundle encoding.") from None


def parse_clauses(text: str, *, host: str | None) -> dict[str, str]:
    """Parse the fixed canonical fenced-clause format, not general Markdown."""
    clauses, seen = {}, set()
    for section in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        heading = section.split("\n", 1)[0]
        name = heading.split()[0]
        if name in seen:
            raise ContractError("Duplicate prompt clause.")
        seen.add(name)
        blocks = re.findall(r"^```text\n(.*?)^```$", section, re.MULTILINE | re.DOTALL)
        if name == "order" and not blocks:
            continue
        if len(blocks) != 1:
            raise ContractError("Invalid prompt clause format.")
        if host is not None and re.search(r"\b" + ("A" if host == "B" else "B") + r"-only\b", heading):
            continue
        clauses[name] = blocks[0].rstrip("\n")
    return clauses


def render_review_clauses(*, family: str, host: str, review_date: str,
                          review_web_authorized: bool, replacements: dict,
                          review_kind: str = "pre-merge", route: str | None = None,
                          agy_hook_active: bool = False,
                          with_manifest: bool = False) -> str | tuple[str, list[dict[str, str]]]:
    """Render a canonical family/host profile with one-pass caller substitution.

    Caller-owned replacement values are already encoded single-line strings.
    This function performs no path inspection and grants no execution authority.
    """
    _validate_profile(family, route)
    if type(with_manifest) is not bool:
        raise PromptError("Manifest flag must be a boolean.")
    if host not in ("A", "B"):
        raise PromptError("Unsupported prompt profile.")
    if type(agy_hook_active) is not bool or (agy_hook_active and (family, host, route) != ("google", "A", "agy")):
        raise PromptError("Invalid active hook profile.")
    if type(review_web_authorized) is not bool:
        raise PromptError("Web permission must be a boolean.")
    try:
        if not isinstance(review_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", review_date):
            raise ValueError
        date.fromisoformat(review_date)
    except ValueError:
        raise PromptError("Review date must be an explicit ISO calendar date.") from None
    if (not isinstance(replacements, dict) or set(replacements) != (REPLACEMENTS | {"gated-patch-file"} if family == "google" else REPLACEMENTS)
            or any(not isinstance(value, str) or "\n" in value or "\r" in value for value in replacements.values())):
        raise PromptError("Invalid caller replacements.")
    bundle = _bundle()
    try:
        phase_schema = parse_json(bundle[PAYLOADS[2]])
        if not isinstance(phase_schema, dict) or phase_schema.get("$schema") != Draft202012Validator.META_SCHEMA["$id"]:
            raise ValueError
        Draft202012Validator.check_schema(phase_schema)
    except (ValueError, SchemaError):
        raise ContractError("Invalid prompt phase contract.") from None
    try:
        if not Draft202012Validator(phase_schema, registry=Registry()).is_valid(review_kind):
            raise PromptError("Invalid review kind.")
    except Unresolvable:
        raise ContractError("Invalid prompt phase contract.") from None
    common = parse_clauses(bundle[PAYLOADS[0]], host=host)
    leg_text = bundle[f"prompts/leg-{family}.md"].replace("common:<review-purpose>",
        "common:" + ("plan-purpose" if review_kind == "formal-plan" else "code-purpose"))
    leg = parse_clauses(leg_text, host=host)
    if not agy_hook_active:
        leg.pop("google-a-hook-audit", None)
    all_common = parse_clauses(bundle[PAYLOADS[0]], host=None)
    all_leg = parse_clauses(leg_text, host=None)
    order = re.findall(r"^\d+\. ([\w:-]+)", leg_text, re.MULTILINE)
    if not order or len(order) != len(set(order)):
        raise ContractError("Invalid prompt clause order.")
    try:
        pieces, manifest = [], []
        web_key = "review-web-permission" if review_web_authorized else "review-no-web"
        web_recorded = False
        for name in order:
            selected, complete, key = (common, all_common, name[7:]) if name.startswith("common:") else (leg, all_leg, name)
            if key not in complete:
                raise KeyError
            if key in selected:
                pieces.append(selected[key])
                if with_manifest:
                    manifest.append({"name": name, "sha256": hashlib.sha256(selected[key].encode("utf-8")).hexdigest()})
                    if "<review-web-policy>" in selected[key] and not web_recorded:
                        manifest.append({"name": "common:" + web_key,
                            "sha256": hashlib.sha256(common[web_key].encode("utf-8")).hexdigest()})
                        web_recorded = True
        values = replacements | {"review-kind": review_kind, "review-date": review_date,
            "review-web-policy": common[web_key]}
    except KeyError:
        raise ContractError("Missing ordered prompt clause.") from None
    if family == "google":
        values["google-route"] = route
    text = "\n\n".join(pieces)
    literals = CLAUDE_LITERALS if family == "claude" else set()
    if not set(re.findall(PLACEHOLDER, text)).issubset(values.keys() | literals):
        raise ContractError("Unexpected prompt placeholders.")
    text = re.sub(PLACEHOLDER, lambda match: values.get(match[1], match[0]), text)
    return (text, manifest) if with_manifest else text


def render_data(value: str) -> str:
    """Transport caller-authored residual text without interpreting its contents."""
    if not isinstance(value, str):
        raise PromptError("Residual data must be text.")
    common = parse_clauses(_bundle()[PAYLOADS[0]], host="B")
    fence = "`" * (max([2, *(len(run) for run in re.findall(r"`+", value))]) + 1)
    return common["data-fence-caveat"] + "\n" + fence + "text\n" + json.dumps(value, ensure_ascii=True) + "\n" + fence


def _validate_profile(family: str, route: str | None) -> None:
    if family not in ("codex", "claude", "google") or (
            route not in ("agy", "gemini") if family == "google" else route is not None):
        raise PromptError("Unsupported prompt profile.")


def render_investigation_prompt(prompt: str, *, family: str, route: str | None = None,
                                web_authorized: bool = False) -> str:
    """Append canonical Google web evidence last; investigations are not ballots."""
    _validate_profile(family, route)
    if not isinstance(prompt, str) or type(web_authorized) is not bool:
        raise PromptError("Invalid investigation arguments.")
    if family != "google" or not web_authorized:
        return prompt
    clauses = parse_clauses(_bundle()["prompts/investigation.md"], host=None)
    try:
        suffix = clauses["web-evidence"]
    except KeyError:
        raise ContractError("Missing investigation clause.") from None
    if route == "gemini":
        suffix = suffix.replace("read_url_content", "web_fetch").replace("search_web", "google_web_search")
    return prompt + "\n\n" + suffix
