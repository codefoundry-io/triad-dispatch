"""Canonical offline verdict admission with complete invocation binding."""

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .contracts import load_contract
from .errors import AdmissionError, ContractError
from .json_input import parse_json

BINDING_FIELDS = ("review_id", "family", "content_digest", "leg_name", "attempt", "route")


def _validate_binding(expected: dict, schema: dict) -> None:
    binding_schema = {
        "type": "object", "additionalProperties": False,
        "required": list(BINDING_FIELDS),
        "properties": {name: schema["properties"][name] for name in BINDING_FIELDS},
        # In the pinned contract, allOf[0] owns family/route compatibility.
        "allOf": [schema["allOf"][0]],
    }
    if not Draft202012Validator(binding_schema, registry=Registry()).is_valid(expected):
        raise AdmissionError("invalid_expected")


def validate_binding(expected: dict) -> None:
    """Validate exactly the six canonical invocation binding fields."""
    _validate_binding(expected, load_contract())


def validate_verdict(raw: str | bytes, *, expected: dict) -> dict:
    """Admit original JSON without rewriting it or making a merge decision.

    ``expected`` must contain exactly the six invocation bindings. Schema-valid
    negative verdicts are returned normally. No remote references are retrieved.
    """
    data = parse_json(raw)
    schema = load_contract()
    try:
        Draft202012Validator(schema, registry=Registry()).validate(data)
        _validate_binding(expected, schema)
        for name in BINDING_FIELDS:
            if data[name] != expected[name]:
                error = AdmissionError("binding_mismatch")
                error.field = name
                raise error
        return data
    except ValidationError as validation_error:
        error = AdmissionError("schema_violation")
        error.path = tuple(validation_error.absolute_schema_path)
        if (validation_error.validator == "required"
                and isinstance(validation_error.validator_value, list)
                and all(isinstance(name, str) for name in validation_error.validator_value)
                and isinstance(validation_error.instance, dict)):
            error.missing = next(
                (name for name in validation_error.validator_value
                 if name not in validation_error.instance), None,
            )
        raise error from None
    except Unresolvable:
        raise ContractError("External or unresolved schema reference.") from None
    except RecursionError:
        raise AdmissionError("nesting_limit") from None
