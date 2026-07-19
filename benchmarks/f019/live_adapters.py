"""Benchmark bridges from production RAG adapters to the frozen candidate DTO."""

from __future__ import annotations

from dataclasses import asdict
import importlib.metadata
import importlib.util
import time
from typing import Protocol, Sequence

from geo_core.rag import ProjectNativeRagAdapterV1, QuestionPlan, RagSourceDocument
from geo_core.rag.contracts import (
    CandidateGraph as ProductCandidateGraph,
    CandidateValidationFinding,
    JsonModelInvoker,
)

from .contracts import (
    CandidateArtifacts,
    CandidateRun,
    DeltaOperation,
    Document,
    EntityCandidate,
    FactCandidate,
    QuestionCandidate,
    RelationCandidate,
    SimulationCandidate,
    UsageMetrics,
)
from .dataset import apply_delta


class UsageRecorder(JsonModelInvoker, Protocol):
    def usage_totals(self) -> dict[str, int | float]: ...

    def usage_evidence(self) -> dict[str, object]: ...


class ProjectNativeBenchmarkAdapter:
    candidate_id = "project-native-rag-v1"
    adapter_kind = "project"
    framework_version = "project-native-rag-v1"
    eligible_for_selection = True

    def __init__(self, model: UsageRecorder | None = None) -> None:
        self._model = model
        self._evidence: dict[str, object] | None = None
        self._validation: dict[str, object] | None = None

    def run(
        self,
        documents: Sequence[Document],
        delta_operations: Sequence[DeltaOperation],
    ) -> CandidateRun:
        if self._model is None:
            return self._unavailable("model_invoker_not_configured")
        started = time.perf_counter()
        adapter = ProjectNativeRagAdapterV1(self._model)
        base_graph: ProductCandidateGraph | None = None
        try:
            base_graph = adapter.extract(*_product_inputs(documents))
            base = _candidate_artifacts(base_graph)
            delta_documents = apply_delta(documents, delta_operations)
            delta_graph = adapter.extract(*_product_inputs(delta_documents))
            delta = _candidate_artifacts(delta_graph)
        except Exception as exc:
            current_findings = adapter.last_validation_findings
            self._validation = _validation_evidence(
                current_findings if base_graph is None else base_graph.validation_findings,
                () if base_graph is None else current_findings,
                failure_stage="base" if base_graph is None else "delta",
            )
            self._evidence = {
                **self._model.usage_evidence(),
                "adapter_failure": {"exception_type": type(exc).__name__},
            }
            return self._unavailable(f"executor_failed:{type(exc).__name__}")
        self._validation = _validation_evidence(
            base_graph.validation_findings,
            delta_graph.validation_findings,
        )
        elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
        usage = self._model.usage_totals()
        self._evidence = self._model.usage_evidence()
        return CandidateRun(
            candidate_id=self.candidate_id,
            adapter_kind=self.adapter_kind,
            framework_version=self.framework_version,
            eligible_for_selection=True,
            available=True,
            unavailable_reason=None,
            base=base,
            delta=delta,
            usage=_usage(usage, elapsed_ms),
        )

    def usage_evidence(self) -> dict[str, object] | None:
        return self._evidence

    def validation_evidence(self) -> dict[str, object] | None:
        return self._validation

    def _unavailable(self, reason: str) -> CandidateRun:
        return CandidateRun(
            candidate_id=self.candidate_id,
            adapter_kind=self.adapter_kind,
            framework_version=self.framework_version,
            eligible_for_selection=True,
            available=False,
            unavailable_reason=reason,
            base=None,
            delta=None,
            usage=None,
        )


class LlamaIndexBenchmarkAdapter:
    candidate_id = "llamaindex-property-graph-v1"
    adapter_kind = "llamaindex"
    eligible_for_selection = True

    def __init__(self, model: UsageRecorder | None = None) -> None:
        self._model = model
        self._evidence: dict[str, object] | None = None
        self._validation: dict[str, object] | None = None

    def run(
        self,
        documents: Sequence[Document],
        delta_operations: Sequence[DeltaOperation],
    ) -> CandidateRun:
        if importlib.util.find_spec("llama_index") is None:
            return self._unavailable("dependency_not_installed", None)
        version = _llamaindex_version()
        if self._model is None:
            return self._unavailable("model_invoker_not_configured", version)
        from geo_core.rag.llamaindex import LlamaIndexPropertyGraphAdapterV1

        started = time.perf_counter()
        adapter = LlamaIndexPropertyGraphAdapterV1(self._model)
        base_graph: ProductCandidateGraph | None = None
        try:
            base_graph = adapter.extract(*_product_inputs(documents))
            base = _candidate_artifacts(base_graph)
            delta_documents = apply_delta(documents, delta_operations)
            delta_graph = adapter.extract(*_product_inputs(delta_documents))
            delta = _candidate_artifacts(delta_graph)
        except Exception as exc:
            current_findings = adapter.last_validation_findings
            self._validation = _validation_evidence(
                current_findings if base_graph is None else base_graph.validation_findings,
                () if base_graph is None else current_findings,
                failure_stage="base" if base_graph is None else "delta",
            )
            self._evidence = {
                **self._model.usage_evidence(),
                "adapter_failure": {"exception_type": type(exc).__name__},
            }
            return self._unavailable(f"executor_failed:{type(exc).__name__}", version)
        self._validation = _validation_evidence(
            base_graph.validation_findings,
            delta_graph.validation_findings,
        )
        elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
        usage = self._model.usage_totals()
        self._evidence = self._model.usage_evidence()
        return CandidateRun(
            candidate_id=self.candidate_id,
            adapter_kind=self.adapter_kind,
            framework_version=f"llama-index-core-{version}",
            eligible_for_selection=True,
            available=True,
            unavailable_reason=None,
            base=base,
            delta=delta,
            usage=_usage(usage, elapsed_ms),
        )

    def usage_evidence(self) -> dict[str, object] | None:
        return self._evidence

    def validation_evidence(self) -> dict[str, object] | None:
        return self._validation

    def _unavailable(self, reason: str, version: str | None) -> CandidateRun:
        return CandidateRun(
            candidate_id=self.candidate_id,
            adapter_kind=self.adapter_kind,
            framework_version=f"llama-index-core-{version}" if version else None,
            eligible_for_selection=True,
            available=False,
            unavailable_reason=reason,
            base=None,
            delta=None,
            usage=None,
        )


def _llamaindex_version() -> str:
    try:
        return importlib.metadata.version("llama-index-core")
    except importlib.metadata.PackageNotFoundError:
        return "installed-version-unknown"


def _product_inputs(
    documents: Sequence[Document],
) -> tuple[tuple[RagSourceDocument, ...], tuple[QuestionPlan, ...]]:
    product_documents = tuple(
        RagSourceDocument(
            document_id=item.document_id,
            project_id=item.project_id,
            title=item.title,
            content=item.content,
            source_locator=item.source_uri,
        )
        for item in documents
    )
    plans = tuple(
        QuestionPlan(
            dimension_key=context["dimension_key"],
            source_document_id=item.document_id,
            persona=context["persona"],
            scenario=context["scenario"],
            intent=context["intent"],
            funnel=context["funnel"],
            region=context["region"],
            language=context["language"],
            brand_scope=context["brand_scope"],
            platform=context["platform"],
            subject=context["subject"],
        )
        for item in documents
        for context in item.question_contexts
    )
    return product_documents, plans


def _candidate_artifacts(graph: ProductCandidateGraph) -> CandidateArtifacts:
    facts = tuple(
        FactCandidate(
            item.candidate_id,
            item.project_id,
            item.text,
            item.source_document_id,
            item.source_locator,
        )
        for item in graph.facts
    )
    entities = tuple(
        EntityCandidate(
            item.candidate_id,
            item.project_id,
            item.entity_type,
            item.name,
            item.source_document_ids,
        )
        for item in graph.entities
    )
    relations = tuple(
        RelationCandidate(
            item.candidate_id,
            item.project_id,
            item.subject,
            item.predicate,
            item.object,
            item.source_document_id,
            item.source_locator,
        )
        for item in graph.relations
    )
    questions = tuple(
        QuestionCandidate(
            item.candidate_id,
            item.project_id,
            item.text,
            item.dimension_key,
            item.source_fact_ids,
            item.source_document_ids,
        )
        for item in graph.questions
    )
    first_fact: dict[str, str] = {}
    for fact in facts:
        first_fact.setdefault(fact.project_id, fact.candidate_id)
    simulations = tuple(
        SimulationCandidate(
            candidate_id=f"simulation-{project_id}",
            project_id=project_id,
            source_fact_ids=(fact_id,),
            test_only=True,
            publication_eligible=False,
        )
        for project_id, fact_id in sorted(first_fact.items())
    )
    return CandidateArtifacts(facts, entities, relations, questions, simulations)


def _usage(values: dict[str, int | float], elapsed_ms: int) -> UsageMetrics:
    return UsageMetrics(
        input_tokens=int(values["input_tokens"]),
        output_tokens=int(values["output_tokens"]),
        model_calls=int(values["model_calls"]),
        estimated_cost_usd=float(values["estimated_cost_usd"]),
        wall_clock_ms=elapsed_ms,
    )


def _validation_evidence(
    base: Sequence[CandidateValidationFinding],
    delta: Sequence[CandidateValidationFinding],
    *,
    failure_stage: str | None = None,
) -> dict[str, object]:
    return {
        "policy": "drop_invalid_candidate_fail_document_without_traceable_fact",
        "dropped_candidate_count": len(base) + len(delta),
        "failure_stage": failure_stage,
        "base": {
            "dropped_candidate_count": len(base),
            "findings": [asdict(item) for item in base],
        },
        "delta": {
            "dropped_candidate_count": len(delta),
            "findings": [asdict(item) for item in delta],
        },
    }
