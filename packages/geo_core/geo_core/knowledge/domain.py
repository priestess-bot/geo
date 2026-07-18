"""Knowledge preprocessing domain contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from uuid import UUID


class KnowledgeError(RuntimeError):
    pass


class KnowledgeForbidden(KnowledgeError):
    pass


class KnowledgeNotFound(KnowledgeError):
    pass


class KnowledgeConflict(KnowledgeError):
    pass


class KnowledgeValidationError(KnowledgeError):
    pass


class KnowledgeProcessingError(KnowledgeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class SourceInput:
    source_kind: str
    title: str
    source_url: str | None
    filename: str | None
    media_type: str
    raw_content: bytes | None


@dataclass(frozen=True)
class ProcessingInput:
    source_id: UUID
    pipeline_run_id: UUID
    project_id: UUID
    source_kind: str
    title: str
    source_url: str | None
    filename: str | None
    media_type: str
    raw_content: bytes | None


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    text_hash: str
    char_count: int
    quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class FactDraft:
    chunk_index: int
    statement: str
    statement_hash: str


@dataclass(frozen=True)
class QualityFindingDraft:
    chunk_index: int | None
    finding_code: str
    severity: str
    message: str
    details: Mapping[str, object]


@dataclass(frozen=True)
class ProcessingResult:
    raw_content: bytes
    resolved_url: str | None
    raw_text: str
    cleaned_text: str
    raw_text_hash: str
    cleaned_text_hash: str
    parser_version: str
    chunks: tuple[ChunkDraft, ...]
    facts: tuple[FactDraft, ...]
    findings: tuple[QualityFindingDraft, ...]
