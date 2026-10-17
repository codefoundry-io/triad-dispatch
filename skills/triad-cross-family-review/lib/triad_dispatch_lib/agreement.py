"""Unanimous agreement over every explicitly selected invocation."""

from dataclasses import dataclass

from .errors import AdmissionError, AgreementError, OutputError
from .output import ProviderOutput, admit_output
from .verdict import validate_binding


@dataclass(frozen=True)
class AgreementResult:
    agreed: bool
    verdicts: dict[str, dict]
    reasons: dict[str, str]
    integrity_ok: bool


def evaluate_agreement(expected_by_leg: dict[str, dict],
                       outputs: dict[str, ProviderOutput], *,
                       integrity_ok: bool) -> AgreementResult:
    """Re-admit original outputs and require every selected leg to approve.

    Invalid caller maps raise AgreementError. Review failures remain per-leg
    reasons; broken packaged contracts propagate to the caller. Informational
    entries and repeated families count exactly like every other selected leg.
    """
    if type(integrity_ok) is not bool:
        raise AgreementError("invalid_integrity")
    if not isinstance(expected_by_leg, dict):
        raise AgreementError("invalid_expected_map")
    if not expected_by_leg:
        raise AgreementError("empty_selection")
    if not isinstance(outputs, dict) or any(not isinstance(k, str) for k in outputs):
        raise AgreementError("invalid_outputs_map")
    basis = None
    for name, expected in expected_by_leg.items():
        if not isinstance(name, str) or not name:
            raise AgreementError("invalid_expected_map")
        try:
            validate_binding(expected)
        except AdmissionError:
            raise AgreementError("invalid_binding") from None
        if name != expected["leg_name"]:
            raise AgreementError("name_mismatch")
        current_basis = (expected["review_id"], expected["content_digest"])
        if basis is not None and current_basis != basis:
            raise AgreementError("mixed_basis")
        basis = current_basis
    if outputs.keys() - expected_by_leg.keys():
        raise AgreementError("extra_output")
    if any(not isinstance(value, ProviderOutput) for value in outputs.values()):
        raise AgreementError("invalid_output")
    verdicts, reasons = {}, {}
    for name, expected in expected_by_leg.items():
        if name not in outputs:
            reasons[name] = "missing_output"
            continue
        try:
            verdict = admit_output(outputs[name], expected=expected)
        except (AdmissionError, OutputError) as error:
            reasons[name] = error.code
            continue
        verdicts[name] = verdict
        if verdict["verdict"] != "SAFE TO MERGE":
            reasons[name] = "negative_verdict"
    return AgreementResult(integrity_ok and not reasons, verdicts, reasons, integrity_ok)
