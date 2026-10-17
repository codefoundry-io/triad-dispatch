"""Offline named-roster resolution without provider defaults or host I/O."""

from copy import deepcopy

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from .contracts import load_roster_contract
from .errors import AdmissionError, ContractError, RosterError
from .json_input import parse_json


def _validate(value: dict, schema: dict, *, resolved: bool, document: str = "resolved") -> None:
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012))
    target = {"$ref": schema["$id"] + "#/$defs/resolvedRoster"} if resolved else schema
    try:
        validation_error = next(Draft202012Validator(target, registry=registry).iter_errors(value), None)
        if validation_error is not None:
            error = RosterError("schema_violation")
            error.path = tuple(validation_error.absolute_schema_path)
            error.document = document
            if (validation_error.validator == "required"
                    and isinstance(validation_error.validator_value, list)
                    and all(isinstance(name, str) for name in validation_error.validator_value)
                    and isinstance(validation_error.instance, dict)):
                error.missing = next(
                    (name for name in validation_error.validator_value
                     if name not in validation_error.instance), None,
                )
            raise error
        names = [leg["name"] for leg in value["legs"]]
        if len(names) != len(set(names)):
            raise RosterError("duplicate_name")
    except Unresolvable:
        raise ContractError("External or unresolved roster schema reference.") from None
    except RecursionError:
        raise RosterError("nesting_limit") from None


def _merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        result = deepcopy(base)
        for key, value in override.items():
            result[key] = _merge(result.get(key), value)
        return result
    return deepcopy(override)


def _merge_roster(defaults: dict, overrides: str | bytes | None, schema: dict) -> dict:
    _validate(defaults, schema, resolved=True, document="defaults")
    result = deepcopy(defaults)
    if overrides is not None:
        try:
            override = parse_json(overrides)
        except AdmissionError:
            raise RosterError("invalid_json") from None
        _validate(override, schema, resolved=False, document="override")
        entries = {leg["name"]: index for index, leg in enumerate(result["legs"])}
        for leg in override["legs"]:
            if leg["name"] in entries:
                index = entries[leg["name"]]
                result["legs"][index] = _merge(result["legs"][index], leg)
            else:
                result["legs"].append(deepcopy(leg))
        for key, value in override.items():
            if key != "legs":
                result[key] = deepcopy(value)
    return result


def merge_roster(defaults: dict, overrides: str | bytes | None = None) -> dict:
    """Validate inputs and return an independent, not finally validated merge."""
    return _merge_roster(defaults, overrides, load_roster_contract())


def validate_resolved(roster: dict) -> None:
    """Validate all resolved entries without mutating the supplied roster."""
    _validate(roster, load_roster_contract(), resolved=True)


def resolve_roster(defaults: dict, overrides: str | bytes | None = None) -> dict:
    """Validate defaults, merge strict named overrides, then validate all entries."""
    schema = load_roster_contract()
    result = _merge_roster(defaults, overrides, schema)
    _validate(result, schema, resolved=True)
    return result


def select_entries(roster: dict) -> list[dict]:
    """Return independent enabled entries in canonical roster order."""
    _validate(roster, load_roster_contract(), resolved=True)
    selected = [deepcopy(leg) for leg in roster["legs"] if leg["enabled"]]
    if not selected:
        raise RosterError("empty_selection")
    return selected
