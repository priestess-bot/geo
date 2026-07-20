"""Runtime scalar validation for project export adapter inputs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re
from typing import cast
from uuid import UUID

from geo_core.project_exports.errors import ProjectExportRuleViolation


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def required_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ProjectExportRuleViolation(f"{label} must be non-empty text")


def optional_text(value: object, label: str, *, allow_empty: bool = False) -> None:
    if value is None:
        return
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ProjectExportRuleViolation(f"{label} must be text or null")


def uuid_value(value: object, label: str) -> None:
    if not isinstance(value, UUID):
        raise ProjectExportRuleViolation(f"{label} must be a UUID")


def optional_uuid(value: object, label: str) -> None:
    if value is not None:
        uuid_value(value, label)


def lineage_ids(record: object) -> None:
    uuid_value(getattr(record, "project_id"), "record project_id")
    uuid_value(getattr(record, "campaign_id"), "record campaign_id")


def boolean(value: object, label: str) -> None:
    if not isinstance(value, bool):
        raise ProjectExportRuleViolation(f"{label} must be a boolean")


def positive_int(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProjectExportRuleViolation(f"{label} must be a positive integer")


def non_negative_int(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProjectExportRuleViolation(f"{label} must be a non-negative integer")


def sha256(value: object, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ProjectExportRuleViolation(f"{label} must be a lowercase SHA-256")


def optional_sha256(value: object, label: str) -> None:
    if value is not None:
        sha256(value, label)


def ratio(value: object, label: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ProjectExportRuleViolation(f"{label} must be a finite Decimal")
    if not Decimal("0") <= value <= Decimal("1"):
        raise ProjectExportRuleViolation(f"{label} must be between zero and one")
    exponent = cast(int, value.as_tuple().exponent)
    if exponent < -6:
        raise ProjectExportRuleViolation(f"{label} must have at most six decimal places")


def aware_time(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ProjectExportRuleViolation(f"{label} must be a timezone-aware datetime")


def optional_time(value: object, label: str) -> None:
    if value is not None:
        aware_time(value, label)
