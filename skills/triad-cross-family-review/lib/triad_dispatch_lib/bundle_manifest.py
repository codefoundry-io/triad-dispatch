"""Deterministic per-bundle identity and strict source metadata."""
import hashlib
import json
import re

SOURCE_REPOSITORY = "https://github.com/codefoundry-io/triad-dispatch-lib"
SOURCE_PATH = "spec"
SCHEMA_NAMESPACE = "https://github.com/codefoundry-io/triad-dispatch-spec"
FIELDS = {"schema_version", "source_repository", "source_path", "status", "sha256", "contract_id"}


def contract_id(digests: dict[str, str]) -> str:
    """Identify one bundle independently of repository revision and map order."""
    serialized = json.dumps(digests, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(b"triad-dispatch-lib:bundle:v1\n" + serialized.encode("utf-8")).hexdigest()


def make_manifest(digests: dict[str, str]) -> dict:
    return {"schema_version": 1, "source_repository": SOURCE_REPOSITORY,
            "source_path": SOURCE_PATH, "status": "candidate", "sha256": digests,
            "contract_id": contract_id(digests)}


def valid_manifest(manifest, names: tuple[str, ...]) -> bool:
    """Validate metadata before reading payloads; consistency is not authenticity."""
    return (
        isinstance(manifest, dict) and set(manifest) == FIELDS
        and type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
        and manifest["source_repository"] == SOURCE_REPOSITORY
        and manifest["source_path"] == SOURCE_PATH and manifest["status"] == "candidate"
        and isinstance(manifest["sha256"], dict) and set(manifest["sha256"]) == set(names)
        and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                for value in manifest["sha256"].values())
        and isinstance(manifest["contract_id"], str)
        and manifest["contract_id"] == contract_id(manifest["sha256"])
    )
