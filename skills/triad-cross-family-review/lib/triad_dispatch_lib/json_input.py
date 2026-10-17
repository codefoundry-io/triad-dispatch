"""Parse original JSON without losing duplicate-member evidence."""

import json
import math

from .errors import AdmissionError


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AdmissionError("duplicate_member")
        result[key] = value
    return result


def _constant(_value):
    raise AdmissionError("nonfinite_number")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise AdmissionError("nonfinite_number")
    return result


def parse_json(raw: str | bytes) -> object:
    """Decode UTF-8 JSON once; reject duplicate members and nonfinite numbers.

    No fence stripping, repair, coercion, or extraction is performed. Callers
    must bound input sizes according to their execution environment.
    """
    if not isinstance(raw, (str, bytes)):
        raise AdmissionError("invalid_input_type")
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw, object_pairs_hook=_object,
                          parse_constant=_constant, parse_float=_float)
    except AdmissionError:
        raise
    except UnicodeDecodeError:
        raise AdmissionError("invalid_utf8") from None
    except RecursionError:
        raise AdmissionError("nesting_limit") from None
    except ValueError:
        raise AdmissionError("invalid_json") from None


def json_member_span(raw: str | bytes, *path: str) -> str | bytes:
    """Return an original member value, after strict full-document validation.

    The ordinary decoder is used only to find offsets in already validated
    JSON. It never reconstructs a verdict or bypasses duplicate detection.
    ``path`` must identify existing object members in the validated document.
    """
    parse_json(raw)
    source = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    decoder = json.JSONDecoder()

    def skip_space(index):
        while index < len(source) and source[index] in " \t\r\n":
            index += 1
        return index

    start = skip_space(0)
    end = len(source)
    for member in path:
        if source[start] != "{":
            raise KeyError(member)
        index = skip_space(start + 1)
        while source[index] != "}":
            key, index = decoder.raw_decode(source, index)
            index = skip_space(index)
            value_start = skip_space(index + 1)  # validated colon
            _, value_end = decoder.raw_decode(source, value_start)
            if key == member:
                start, end = value_start, value_end
                break
            index = skip_space(value_end)
            if source[index] == ",":
                index = skip_space(index + 1)
        else:
            raise KeyError(member)
    if isinstance(raw, bytes):
        # Translate character offsets, then slice the original byte carrier;
        # never serialize or encode the extracted verdict object/value.
        byte_start = len(source[:start].encode("utf-8"))
        byte_end = len(source[:end].encode("utf-8"))
        return raw[byte_start:byte_end]
    return raw[start:end]
