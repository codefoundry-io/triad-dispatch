"""Pure compatibility decisions over host-authenticated runtime metadata.

Membership declares tested combinations; it does not authenticate artifacts,
bindings or context. Hosts own provenance, discovery and lifecycle operations.
"""
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
import re

from .errors import RuntimeCompatibilityError


@dataclass(frozen=True)
class ConsumerBinding:
    schema: str
    consumer: str
    baseline_digest: str
    library_digest: str
    adapter: str
    capabilities: tuple[str, ...]
    commands: tuple[str, ...]
    context_digest: str
    binding_id: str


@dataclass(frozen=True)
class RuntimeDescriptor:
    schema: str
    artifact_digest: str
    commands: tuple[str, ...]
    capabilities: tuple[str, ...]
    supported_bindings: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeRetention:
    retain: tuple[str, ...]
    remove: tuple[str, ...]
    diagnostic: str


_DIGEST = re.compile(r'[0-9a-f]{64}')
_IDENTIFIER = re.compile(r'[a-z][a-z0-9._:-]{0,127}')
_COMMAND = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
_BINDING_FIELDS = ('schema', 'consumer', 'baseline_digest', 'library_digest',
                   'adapter', 'capabilities', 'commands', 'context_digest')
_RUNTIME_FIELDS = ('schema', 'artifact_digest', 'commands', 'capabilities',
                   'supported_bindings')


def _refuse(code):
    raise RuntimeCompatibilityError(code)


def _matches(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _sequence(value, code):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        _refuse(code)
    return value


def _items(value, pattern, code, *, nonempty=False, duplicates=False):
    if not isinstance(value, (list, tuple)):
        _refuse(code)
    items = value
    if nonempty and not items:
        _refuse(code)
    if any(not _matches(item, pattern) for item in items):
        _refuse(code)
    if not duplicates and len(set(items)) != len(items):
        _refuse(code)
    return tuple(sorted(set(items)))


def _document(document, fields, schema, code):
    if not isinstance(document, dict) or set(document) != set(fields):
        _refuse(code)
    if not isinstance(document['schema'], str):
        _refuse(code)
    if document['schema'] != schema:
        _refuse('unsupported_schema')
    for name in ('commands', 'capabilities', 'supported_bindings'):
        if name in fields and not isinstance(document[name], list):
            _refuse(code)


def validate_consumer_binding(document: dict) -> ConsumerBinding:
    """Normalize a complete binding and derive its context-sensitive identity."""
    code = 'invalid_binding'
    _document(document, _BINDING_FIELDS, 'triad-consumer-binding.v1', code)
    for name in ('consumer', 'adapter'):
        if not _matches(document[name], _IDENTIFIER):
            _refuse(code)
    for name in ('baseline_digest', 'library_digest', 'context_digest'):
        if not _matches(document[name], _DIGEST):
            _refuse(code)
    normalized = dict(document)
    normalized['commands'] = _items(document['commands'], _COMMAND, code, nonempty=True)
    normalized['capabilities'] = _items(document['capabilities'], _IDENTIFIER, code)
    canonical = json.dumps(normalized, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    identity = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    return ConsumerBinding(**normalized, binding_id=identity)


def validate_runtime_descriptor(document: dict) -> RuntimeDescriptor:
    """Validate metadata whose provenance has already been checked by the host."""
    code = 'invalid_descriptor'
    _document(document, _RUNTIME_FIELDS, 'triad-runtime-compat.v1', code)
    if not _matches(document['artifact_digest'], _DIGEST):
        _refuse(code)
    return RuntimeDescriptor(
        schema=document['schema'], artifact_digest=document['artifact_digest'],
        commands=_items(document['commands'], _COMMAND, code, nonempty=True),
        capabilities=_items(document['capabilities'], _IDENTIFIER, code),
        supported_bindings=_items(document['supported_bindings'], _DIGEST, code, nonempty=True))


def _binding_record(binding):
    if not isinstance(binding, ConsumerBinding):
        _refuse('invalid_binding')
    document = {name: getattr(binding, name) for name in _BINDING_FIELDS}
    for name in ('commands', 'capabilities'):
        if not isinstance(document[name], tuple):
            _refuse('invalid_binding')
        document[name] = list(document[name])
    validated = validate_consumer_binding(document)
    if not _matches(binding.binding_id, _DIGEST) or binding.binding_id != validated.binding_id:
        _refuse('invalid_binding')
    return validated


def _runtime_record(runtime):
    if not isinstance(runtime, RuntimeDescriptor):
        _refuse('invalid_descriptor')
    document = {name: getattr(runtime, name) for name in _RUNTIME_FIELDS}
    for name in ('commands', 'capabilities', 'supported_bindings'):
        if not isinstance(document[name], tuple):
            _refuse('invalid_descriptor')
        document[name] = list(document[name])
    return validate_runtime_descriptor(document)


def check_consumer_compatibility(runtime: RuntimeDescriptor, binding: ConsumerBinding) -> None:
    """Require declared exact support and all commands/capabilities."""
    runtime, binding = _runtime_record(runtime), _binding_record(binding)
    if binding.binding_id not in runtime.supported_bindings:
        _refuse('unsupported_binding')
    if not set(binding.commands).issubset(runtime.commands):
        _refuse('command_mismatch')
    if not set(binding.capabilities).issubset(runtime.capabilities):
        _refuse('capability_mismatch')


def select_consumer_binding(runtime: RuntimeDescriptor, bindings: Sequence[ConsumerBinding], *,
                            explicit_binding: str | None, legacy_binding: str | None) -> ConsumerBinding:
    """Select only an explicit or established legacy identity; never guess."""
    validated_runtime = _runtime_record(runtime)
    inventory = [_binding_record(item) for item in _sequence(bindings, 'invalid_inventory')]
    by_id = {item.binding_id: item for item in inventory}
    if len(by_id) != len(inventory):
        _refuse('ambiguous_binding')
    for selector in (explicit_binding, legacy_binding):
        if selector is not None and not _matches(selector, _DIGEST):
            _refuse('invalid_selector')
    selected = explicit_binding if explicit_binding is not None else legacy_binding
    if selected is None:
        _refuse('missing_context')
    if selected not in by_id:
        _refuse('unknown_binding')
    result = by_id[selected]
    check_consumer_compatibility(validated_runtime, result)
    return result


def plan_runtime_retention(artifacts: Sequence[str], *, consumer_references: Sequence[str],
                           active_references: Sequence[str], dependencies_known: bool) -> RuntimeRetention:
    """Decide retention from a complete inventory without performing removals."""
    code = 'invalid_inventory'
    if not isinstance(dependencies_known, bool):
        _refuse(code)
    artifacts = _items(artifacts, _DIGEST, code)
    consumers = _items(consumer_references, _DIGEST, code, duplicates=True)
    active = _items(active_references, _DIGEST, code, duplicates=True)
    references = set(consumers) | set(active)
    if not references.issubset(artifacts):
        _refuse('incomplete_inventory')
    if not dependencies_known:
        return RuntimeRetention(artifacts, (), 'dependencies_unknown')
    return RuntimeRetention(tuple(sorted(references)), tuple(sorted(set(artifacts) - references)),
                            'references_preserved')
