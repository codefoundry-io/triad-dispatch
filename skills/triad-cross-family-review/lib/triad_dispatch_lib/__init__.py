"""Shared deterministic TRIAD admission."""

from .errors import AdmissionError, ContractError, PromptError, RosterError
from .json_input import parse_json
from .verdict import validate_binding, validate_verdict
from .prompts import render_data, render_review_clauses, render_investigation_prompt
from .contracts import load_roster_contract
from .roster import merge_roster, validate_resolved, resolve_roster, select_entries
from .errors import OutputError, AgreementError
from .output import ProviderOutput, extract_final, separate_agy_metadata, admit_output
from .agreement import AgreementResult, evaluate_agreement
from .errors import DispatchError
from .dispatch import (ReviewRequest, InvestigationRequest, CallOutcome, ReviewRun,
                       run_review, run_investigations)
from .errors import ReceiptError
from .receipt import validate_transport_receipt
from .errors import RuntimeCompatibilityError
from .runtime_compat import (ConsumerBinding, RuntimeDescriptor, RuntimeRetention,
                             validate_consumer_binding, validate_runtime_descriptor,
                             check_consumer_compatibility, select_consumer_binding,
                             plan_runtime_retention)

__all__ = ["RuntimeCompatibilityError", "ConsumerBinding", "RuntimeDescriptor", "RuntimeRetention",
           "validate_consumer_binding", "validate_runtime_descriptor", "check_consumer_compatibility",
           "select_consumer_binding", "plan_runtime_retention",
           "ReceiptError", "validate_transport_receipt",
           "OutputError", "AgreementError", "ProviderOutput", "extract_final", "separate_agy_metadata", "admit_output",
           "DispatchError", "ReviewRequest", "InvestigationRequest", "CallOutcome", "ReviewRun",
           "run_review", "run_investigations",
           "AgreementResult", "evaluate_agreement",
           "RosterError", "merge_roster", "validate_resolved", "resolve_roster", "select_entries", "load_roster_contract",
           "render_investigation_prompt", "AdmissionError", "ContractError", "PromptError", "parse_json",
           "validate_binding", "validate_verdict", "render_data", "render_review_clauses"]
