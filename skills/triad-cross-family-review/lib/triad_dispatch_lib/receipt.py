"""Offline transport-object shape validation, separate from host custody."""

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .contracts import _load_receipt_contract
from .errors import ContractError, ReceiptError


def validate_transport_receipt(doc: dict) -> None:
    """Validate only the nested transport object without mutating caller data."""
    schema = _load_receipt_contract()
    try:
        Draft202012Validator(schema, registry=Registry()).validate(doc)
    except ValidationError:
        raise ReceiptError("schema_violation") from None
    except Unresolvable:
        raise ContractError("External or unresolved receipt schema reference.") from None
    except RecursionError:
        raise ReceiptError("nesting_limit") from None
