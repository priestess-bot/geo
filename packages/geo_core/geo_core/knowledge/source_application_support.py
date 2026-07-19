"""Shared validation and identity helpers for Knowledge source commands."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping
from uuid import UUID

from geo_core.knowledge.domain import KnowledgeValidationError, SourceInput


def validate_source(source: SourceInput) -> None:
    if source.source_kind not in {"url", "file", "text"}:
        raise KnowledgeValidationError("source_kind must be url, file or text")
    if not source.title.strip() or len(source.title) > 300:
        raise KnowledgeValidationError(
            "source title is required and must be at most 300 characters"
        )
    if not source.media_type.strip():
        raise KnowledgeValidationError("source media type is required")
    if source.source_kind == "url" and not source.source_url:
        raise KnowledgeValidationError("URL source requires source_url")
    if source.source_kind != "url" and source.raw_content is None:
        raise KnowledgeValidationError("file and text sources require content")
    if source.raw_content is not None and len(source.raw_content) > 5 * 1024 * 1024:
        raise KnowledgeValidationError("source exceeds the 5 MB limit")


def idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not 1 <= len(normalized) <= 200:
        raise KnowledgeValidationError("Idempotency-Key must contain 1 to 200 characters")
    return normalized


def canonical_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def run_exists(connection: Any, run_id: UUID, project_id: UUID) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM knowledge_pipeline_runs WHERE id = %s AND project_id = %s",
            (run_id, project_id),
        ).fetchone()
        is not None
    )
