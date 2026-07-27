"""Framework-neutral RAG candidate contracts and adapters."""

from geo_core.rag.contracts import (
    CandidateEntity,
    CandidateFact,
    CandidateGraph,
    CandidateQuestion,
    CandidateRelation,
    CandidateValidationFinding,
    JsonModelInvoker,
    QuestionPlan,
    RagAdapterError,
    RagSourceDocument,
)
from geo_core.rag.native import ProjectNativeRagAdapterV1, RAG_EXTRACTION_OUTPUT_SCHEMA
from geo_core.rag.selection import RagSelection, load_rag_selection
from geo_core.rag.runtime import SelectedRagAdapter, selected_rag_adapter

__all__ = [
    "CandidateEntity",
    "CandidateFact",
    "CandidateGraph",
    "CandidateQuestion",
    "CandidateRelation",
    "CandidateValidationFinding",
    "JsonModelInvoker",
    "ProjectNativeRagAdapterV1",
    "RAG_EXTRACTION_OUTPUT_SCHEMA",
    "QuestionPlan",
    "RagAdapterError",
    "RagSelection",
    "RagSourceDocument",
    "SelectedRagAdapter",
    "load_rag_selection",
    "selected_rag_adapter",
]
