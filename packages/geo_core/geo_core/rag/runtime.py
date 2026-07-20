"""Instantiate the hash-validated selected adapter without leaking framework types."""

from __future__ import annotations

from typing import Protocol, Sequence

from geo_core.rag.contracts import (
    CandidateGraph,
    JsonModelInvoker,
    QuestionPlan,
    RagAdapterError,
    RagSourceDocument,
)
from geo_core.rag.native import ProjectNativeRagAdapterV1
from geo_core.rag.selection import RagSelection


class SelectedRagAdapter(Protocol):
    adapter_release: str

    def extract(
        self,
        documents: Sequence[RagSourceDocument],
        question_plans: Sequence[QuestionPlan] = (),
    ) -> CandidateGraph: ...


def selected_rag_adapter(selection: RagSelection, model: JsonModelInvoker) -> SelectedRagAdapter:
    if selection.adapter_release == ProjectNativeRagAdapterV1.adapter_release:
        return ProjectNativeRagAdapterV1(model)
    if selection.adapter_release == "llamaindex-property-graph-v1":
        from geo_core.rag.llamaindex import LlamaIndexPropertyGraphAdapterV1

        return LlamaIndexPropertyGraphAdapterV1(model)
    raise RagAdapterError("selected RAG adapter release is not installed")
