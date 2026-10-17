"""Explicit provider carriers with terminal guards and original JSON admission."""

from dataclasses import dataclass

from .errors import OutputError
from .json_input import json_member_span, parse_json
from .verdict import validate_binding, validate_verdict


@dataclass(frozen=True)
class ProviderOutput:
    """Host-observed output; hosts own execution and native marker removal."""

    carrier: str
    stdout: str | bytes
    exit_code: int | None
    completed: bool
    timed_out: bool = False
    transport_failed: bool = False


def _guard(output: ProviderOutput) -> None:
    if not isinstance(output, ProviderOutput):
        raise OutputError("invalid_output")
    if not isinstance(output.carrier, str) or output.carrier not in (
        "native-final", "claude-json", "gemini-json", "agy-stream-json"
    ):
        raise OutputError("invalid_carrier")
    if (any(type(value) is not bool for value in (
            output.completed, output.timed_out, output.transport_failed))
            or (output.exit_code is not None and type(output.exit_code) is not int)
            or (output.exit_code is None and output.carrier != "native-final")):
        raise OutputError("invalid_output")
    if not output.completed:
        raise OutputError("not_completed")
    if output.timed_out:
        raise OutputError("timed_out")
    if output.transport_failed:
        raise OutputError("transport_failed")
    if output.exit_code not in (0, None):
        raise OutputError("nonzero_exit")
    if not isinstance(output.stdout, (str, bytes)):
        raise OutputError("invalid_output")


def _object(value):
    if not isinstance(value, dict):
        raise OutputError("invalid_envelope")
    return value


def _no_error(envelope):
    if "is_error" in envelope:
        if type(envelope["is_error"]) is not bool:
            raise OutputError("invalid_envelope")
        if envelope["is_error"]:
            raise OutputError("terminal_failure")
    if envelope.get("error") is not None:
        raise OutputError("terminal_failure")


def extract_final(output: ProviderOutput) -> str | bytes:
    """Extract only the formal final carrier, refusing failed terminals first.

    Full envelopes/JSONL records are strictly parsed before extracting original
    member spans. Gemini's decoded response string is passed intact. No stderr
    or ordinary evidence text is classified as a transport failure.
    """
    _guard(output)
    raw = output.stdout
    if output.carrier == "native-final":
        return raw
    if output.carrier == "agy-stream-json":
        terminal = None
        # Decode strictly before splitting bytes, so invalid UTF-8 cannot hide.
        if isinstance(raw, bytes):
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                # Reuse the parser's stable UTF-8 refusal.
                parse_json(raw)
        separator = b"\n" if isinstance(raw, bytes) else "\n"
        whitespace = b" \t\r" if isinstance(raw, bytes) else " \t\r"
        for line in raw.split(separator):
            if not line.strip(whitespace):
                continue
            record = _object(parse_json(line))
            if record.get("event") != "result":
                continue
            if terminal is not None:
                raise OutputError("multiple_terminals")
            result = _object(record.get("result"))
            if result.get("status") != "SUCCESS":
                raise OutputError("terminal_failure")
            _object(result.get("structured_output"))
            terminal = line
        if terminal is None:
            raise OutputError("missing_terminal")
        return json_member_span(terminal, "result", "structured_output")
    envelope = _object(parse_json(raw))
    _no_error(envelope)
    if output.carrier == "gemini-json":
        response = envelope.get("response")
        if not isinstance(response, str):
            raise OutputError("invalid_envelope")
        return response
    subtype = envelope.get("subtype")
    if subtype is not None and not isinstance(subtype, str):
        raise OutputError("invalid_envelope")
    if (subtype == "error" or (isinstance(subtype, str) and subtype.startswith("error_"))
            or envelope.get("terminal_reason") in ("error", "api_error")
            or envelope.get("status") in ("ERROR", "FAILED", "error", "failed")):
        raise OutputError("terminal_failure")
    _object(envelope.get("structured_output"))
    return json_member_span(raw, "structured_output")


def admit_output(output: ProviderOutput, *, expected: dict) -> dict:
    """Validate bindings, carrier compatibility, terminal state and verdict."""
    validate_binding(expected)
    _guard(output)
    required = {
        "claude-json": ("claude", None),
        "gemini-json": ("google", "gemini"),
        "agy-stream-json": ("google", "agy"),
    }.get(output.carrier)
    if required is not None and required != (expected["family"], expected["route"]):
        raise OutputError("carrier_mismatch")
    return validate_verdict(extract_final(output), expected=expected)
