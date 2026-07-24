"""Strict, provider-neutral response value parsing helpers."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.parse import urlparse

from geo_core.model_gateway.contracts import StructuredOutputValidationError


def parse_json_object_text(value: object, *, provider: str) -> dict[str, object]:
    if not isinstance(value, str) or not value.strip():
        raise StructuredOutputValidationError(
            "provider structured output text is empty", provider=provider
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StructuredOutputValidationError(
            "provider structured output text is not valid JSON", provider=provider
        ) from exc
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise StructuredOutputValidationError(
            "provider structured output must be a JSON object", provider=provider
        )
    return parsed


def require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise StructuredOutputValidationError(f"{label} must be a JSON object")
    return value


def require_list(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise StructuredOutputValidationError(f"{label} must be an array")
    return value


def required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StructuredOutputValidationError(f"{label} must be a non-empty string")
    return value


def optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def normalized_citation(
    *,
    provider: str,
    url: object,
    title: object = None,
    ordinal: int,
    citation_type: str = "url_citation",
    source_id: object = None,
    start_index: object = None,
    end_index: object = None,
) -> Mapping[str, object]:
    citation_url = required_text(url, label="provider citation URL")
    parsed = urlparse(citation_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise StructuredOutputValidationError("provider citation URL must be absolute HTTP(S)")
    result: dict[str, object] = {
        "provider": provider,
        "citation_type": citation_type,
        "url": citation_url,
        "ordinal": ordinal,
    }
    if optional_text(title) is not None:
        result["title"] = optional_text(title)
    if optional_text(source_id) is not None:
        result["source_id"] = optional_text(source_id)
    if optional_int(start_index) is not None:
        result["start_index"] = optional_int(start_index)
    if optional_int(end_index) is not None:
        result["end_index"] = optional_int(end_index)
    return result


def canonical_hash(value: Mapping[str, object]) -> str:
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StructuredOutputValidationError("provider response contains non-JSON values") from exc
    return hashlib.sha256(canonical.encode()).hexdigest()


def error_descriptor(body: object) -> str:
    try:
        return json.dumps(body, sort_keys=True).lower()
    except (TypeError, ValueError):
        return ""


def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = next(
        (header_value for name, header_value in headers.items() if name.lower() == "retry-after"),
        None,
    )
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


__all__ = [
    "canonical_hash",
    "error_descriptor",
    "normalized_citation",
    "optional_decimal",
    "optional_int",
    "optional_text",
    "parse_json_object_text",
    "require_list",
    "require_mapping",
    "required_text",
    "retry_after_seconds",
]
