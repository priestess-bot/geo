"""Strict row decoding for Recommendation generation workers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from geo_core.recommendations.generation_contracts import RecommendationGenerationStale


def row_uuid(row: Mapping[str, Any], key: str) -> UUID:
    value = row.get(key)
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as error:
        raise RecommendationGenerationStale(
            f"Recommendation row {key} is not a UUID"
        ) from error


__all__ = ["row_uuid"]
