"""Errors that never interpolate untrusted verdict contents."""

_MESSAGES = {
    "invalid_json": "Invalid original JSON.",
    "invalid_utf8": "JSON bytes must be UTF-8.",
    "duplicate_member": "Duplicate JSON object member.",
    "nonfinite_number": "Nonfinite JSON number.",
    "invalid_input_type": "Original JSON must be str or bytes.",
    "nesting_limit": "JSON nesting exceeds the decoder limit.",
    "schema_violation": "Verdict violates the canonical schema.",
    "invalid_expected": "Invalid expected invocation binding.",
    "binding_mismatch": "Verdict does not match the expected invocation.",
}


class AdmissionError(ValueError):
    """Rejected input; ``code`` is stable, human-readable wording is not."""

    def __init__(self, code: str):
        self.code = code
        self.field: str | None = None
        self.path: tuple[str | int, ...] | None = None
        self.missing: str | None = None
        super().__init__(_MESSAGES[code])


class ContractError(RuntimeError):
    """The packaged validation contract is unavailable or inconsistent."""


class DispatchError(ValueError):
    """Invalid coordination inputs or preflight; no invocation has started."""

    def __init__(self, code: str):
        self.code = code
        super().__init__({
            'invalid_concurrency': 'Concurrency must be a positive integer.',
            'invalid_callback': 'Callbacks must be callable.',
            'invalid_requests': 'Invalid dispatch requests.',
            'empty_selection': 'No dispatch requests selected.',
            'invalid_entries': 'Invalid canonical dispatch entries.',
            'disabled_entry': 'Dispatch entry is disabled.',
            'unresolved_route': 'Google invocation route is unresolved.',
            'invalid_binding': 'Invalid formal invocation binding.',
            'binding_mismatch': 'Formal binding does not match entry.',
            'mixed_basis': 'Formal requests have different review bases.',
            'preflight_failed': 'Host preflight did not succeed.',
        }[code])


class PromptError(ValueError):
    """Invalid rendering arguments, separate from verdict admission."""


class RosterError(ValueError):
    """Caller roster refusal with fixed text and a stable reason code."""

    def __init__(self, code: str):
        self.code = code
        self.path: tuple[str | int, ...] | None = None
        self.missing: str | None = None
        self.document: str | None = None
        super().__init__({
            "invalid_json": "Invalid roster override JSON.",
            "schema_violation": "Roster violates the canonical schema.",
            "duplicate_name": "Duplicate roster entry name.",
            "empty_selection": "Roster has no enabled entries.",
            "nesting_limit": "Roster nesting exceeds the validation limit.",
        }[code])


class ReceiptError(ValueError):
    """Transport shape refusal with fixed text and a stable reason code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__({
            "schema_violation": "Transport receipt violates the canonical schema.",
            "nesting_limit": "Transport receipt nesting exceeds the validation limit.",
        }[code])


class OutputError(ValueError):
    """Carrier or terminal-state refusal; never includes provider text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__({
            "invalid_output": "Invalid provider output metadata.",
            "invalid_carrier": "Unknown provider output carrier.",
            "not_completed": "Provider output did not complete.",
            "timed_out": "Provider output timed out.",
            "transport_failed": "Provider output transport failed.",
            "nonzero_exit": "Provider process did not exit successfully.",
            "invalid_envelope": "Invalid provider output envelope.",
            "terminal_failure": "Provider reported terminal failure.",
            "missing_terminal": "Provider stream has no terminal result.",
            "multiple_terminals": "Provider stream has multiple terminal results.",
            "carrier_mismatch": "Provider carrier does not match invocation binding.",
        }[code])


class AgreementError(ValueError):
    """Invalid caller selection or output map, separate from review failures."""

    def __init__(self, code: str):
        self.code = code
        super().__init__({
            "invalid_expected_map": "Invalid expected invocation map.",
            "invalid_binding": "Invalid selected invocation binding.",
            "invalid_outputs_map": "Invalid provider output map.",
            "invalid_output": "Output map values must be provider outputs.",
            "empty_selection": "No selected review entries.",
            "name_mismatch": "Selected name does not match invocation binding.",
            "mixed_basis": "Selected bindings have different review bases.",
            "extra_output": "Output supplied for an unselected review entry.",
            "invalid_integrity": "Host integrity must be a boolean.",
        }[code])
