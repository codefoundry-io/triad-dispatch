"""Shared deterministic TRIAD admission."""

from .errors import AdmissionError, ContractError, PromptError, RosterError
from .json_input import parse_json
from .verdict import validate_binding, validate_verdict
from .prompts import render_data, render_review_clauses, render_investigation_prompt
from .contracts import load_roster_contract
from .roster import merge_roster, validate_resolved, resolve_roster, select_entries
from .errors import OutputError, AgreementError
from .output import ProviderOutput, extract_final, admit_output
from .agreement import AgreementResult, evaluate_agreement
from .errors import DispatchError
from .dispatch import (ReviewRequest, InvestigationRequest, CallOutcome, ReviewRun,
                       run_review, run_investigations)
from .errors import ReceiptError
from .receipt import validate_transport_receipt

__all__ = ["ReceiptError", "validate_transport_receipt",
           "OutputError", "AgreementError", "ProviderOutput", "extract_final", "admit_output",
           "DispatchError", "ReviewRequest", "InvestigationRequest", "CallOutcome", "ReviewRun",
           "run_review", "run_investigations",
           "AgreementResult", "evaluate_agreement",
           "RosterError", "merge_roster", "validate_resolved", "resolve_roster", "select_entries", "load_roster_contract",
           "render_investigation_prompt", "AdmissionError", "ContractError", "PromptError", "parse_json",
           "validate_binding", "validate_verdict", "render_data", "render_review_clauses"]
