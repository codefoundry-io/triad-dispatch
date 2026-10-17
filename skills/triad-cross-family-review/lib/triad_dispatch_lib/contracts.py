"""Read a verified specification payload from package resources."""

import hashlib
from importlib.resources import files

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .bundle_manifest import SCHEMA_NAMESPACE, SOURCE_REPOSITORY, valid_manifest
from .errors import ContractError
from .json_input import parse_json

SCHEMA_NAME = "leg-verdict.schema.json"


def load_verified_bundle(root, names: tuple[str, ...]) -> dict[str, bytes]:
    """Verify an exact set of pinned resource paths; no remote I/O or caching."""
    try:
        manifest = parse_json(root.joinpath("source-manifest.json").read_bytes())
        if not valid_manifest(manifest, names):
            raise ContractError("Invalid packaged contract provenance.")
        payloads = {}
        for name in names:
            raw = root.joinpath(*name.split("/")).read_bytes()
            if hashlib.sha256(raw).hexdigest() != manifest["sha256"][name]:
                raise ContractError("Packaged contract digest mismatch.")
            payloads[name] = raw
        return payloads
    except (OSError, ValueError, RecursionError):
        raise ContractError("Unreadable or invalid packaged contract.") from None


def load_contract() -> dict:
    """Return fresh schema data; hashes establish consistency, not authenticity."""
    try:
        root = files("triad_dispatch_lib").joinpath("data")
        raw = load_verified_bundle(root, (SCHEMA_NAME,))[SCHEMA_NAME]
        schema = parse_json(raw)
        if not isinstance(schema, dict) or schema.get("$schema") != Draft202012Validator.META_SCHEMA["$id"]:
            raise ContractError("Unsupported packaged contract dialect.")
        Draft202012Validator.check_schema(schema)
        return schema
    except (OSError, ValueError, SchemaError, RecursionError):
        raise ContractError("Unreadable or invalid packaged contract.") from None


def load_roster_contract() -> dict:
    """Return the canonical roster schema with its own pinned provenance."""
    try:
        root = files("triad_dispatch_lib").joinpath("data", "roster-bundle")
        name = "contracts/review-legs.schema.json"
        schema = parse_json(load_verified_bundle(root, (name,))[name])
        if (not isinstance(schema, dict)
                or schema.get("$schema") != Draft202012Validator.META_SCHEMA["$id"]
                or schema.get("$id") != SCHEMA_NAMESPACE + "/" + name):
            raise ValueError
        Draft202012Validator.check_schema(schema)
        return schema
    except (OSError, ValueError, SchemaError, RecursionError):
        raise ContractError("Unreadable or invalid packaged roster contract.") from None


def _load_receipt_contract() -> dict:
    """Return the unchanged transport schema from its own verified bundle."""
    try:
        root = files("triad_dispatch_lib").joinpath("data", "receipt-bundle")
        name = "contracts/receipt-fields.json"
        schema = parse_json(load_verified_bundle(root, (name,))[name])
        if (not isinstance(schema, dict)
                or schema.get("$schema") != Draft202012Validator.META_SCHEMA["$id"]
                or schema.get("$id") != SCHEMA_NAMESPACE + "/" + name):
            raise ValueError
        Draft202012Validator.check_schema(schema)
        return schema
    except (OSError, ValueError, SchemaError, RecursionError):
        raise ContractError("Unreadable or invalid packaged receipt contract.") from None
