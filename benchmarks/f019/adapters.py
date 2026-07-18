"""Isolated adapters that emit only the project-owned intermediate contract."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import re
import time
from collections import defaultdict
from collections.abc import Callable, Sequence

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


FACT_PATTERN = re.compile(r"^【事实】(?P<text>.+)$")
ENTITY_PATTERN = re.compile(r"^【实体】(?P<type>[A-Za-z]+)｜(?P<name>.+)$")
RELATION_PATTERN = re.compile(
    r"^【关系】(?P<subject>.+?)｜(?P<predicate>[a-z_]+)｜(?P<object>.+)$"
)


class DeterministicBaselineAdapter:
    """A no-model structured-document baseline for validating the benchmark harness."""

    candidate_id = "project-deterministic-baseline-v1"
    adapter_kind = "project_baseline"
    # This structured-fixture parser proves the harness, not a production framework choice.
    eligible_for_selection = False

    def run(
        self,
        documents: Sequence[Document],
        delta_operations: Sequence[DeltaOperation],
    ) -> CandidateRun:
        started = time.perf_counter()
        base = self._extract(documents)
        delta = self._extract(apply_delta(documents, delta_operations))
        elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
        return CandidateRun(
            candidate_id=self.candidate_id,
            adapter_kind=self.adapter_kind,
            framework_version="deterministic-v1",
            eligible_for_selection=self.eligible_for_selection,
            available=True,
            unavailable_reason=None,
            base=base,
            delta=delta,
            usage=UsageMetrics(
                input_tokens=0,
                output_tokens=0,
                model_calls=0,
                estimated_cost_usd=0.0,
                wall_clock_ms=elapsed_ms,
            ),
        )

    def _extract(self, documents: Sequence[Document]) -> CandidateArtifacts:
        facts: list[FactCandidate] = []
        relations: list[RelationCandidate] = []
        questions: list[QuestionCandidate] = []
        entity_sources: dict[tuple[str, str, str], set[str]] = defaultdict(set)
        first_fact_by_project: dict[str, str] = {}

        for document in sorted(documents, key=lambda item: (item.project_id, item.document_id)):
            document_facts: list[FactCandidate] = []
            for line_number, raw_line in enumerate(document.content.splitlines(), start=1):
                line = raw_line.strip()
                if match := FACT_PATTERN.fullmatch(line):
                    fact = FactCandidate(
                        candidate_id=f"fact-{document.document_id}-{len(document_facts) + 1:02d}",
                        project_id=document.project_id,
                        text=match.group("text"),
                        source_document_id=document.document_id,
                        source_locator=f"line:{line_number}",
                    )
                    document_facts.append(fact)
                    facts.append(fact)
                    first_fact_by_project.setdefault(document.project_id, fact.candidate_id)
                elif match := ENTITY_PATTERN.fullmatch(line):
                    entity_sources[
                        (document.project_id, match.group("type"), match.group("name"))
                    ].add(document.document_id)
                elif match := RELATION_PATTERN.fullmatch(line):
                    relations.append(
                        RelationCandidate(
                            candidate_id=f"rel-{document.document_id}-{len(relations) + 1:03d}",
                            project_id=document.project_id,
                            subject=match.group("subject"),
                            predicate=match.group("predicate"),
                            object=match.group("object"),
                            source_document_id=document.document_id,
                            source_locator=f"line:{line_number}",
                        )
                    )

            for index, context in enumerate(document.question_contexts):
                if not document_facts:
                    continue
                support = _select_support_fact(document_facts, context, index).candidate_id
                questions.append(
                    QuestionCandidate(
                        candidate_id=f"question-{document.document_id}-{index + 1:02d}",
                        project_id=document.project_id,
                        text=_question_text(context, index),
                        dimension_key=context["dimension_key"],
                        source_fact_ids=(support,),
                        source_document_ids=(document.document_id,),
                    )
                )

        entities = tuple(
            EntityCandidate(
                candidate_id=f"entity-{_stable_id('|'.join(key))}",
                project_id=key[0],
                entity_type=key[1],
                name=key[2],
                source_document_ids=tuple(sorted(source_document_ids)),
            )
            for key, source_document_ids in sorted(entity_sources.items())
        )
        simulations = tuple(
            SimulationCandidate(
                candidate_id=f"simulation-{project_id}",
                project_id=project_id,
                source_fact_ids=(fact_id,),
                test_only=True,
                publication_eligible=False,
            )
            for project_id, fact_id in sorted(first_fact_by_project.items())
        )
        return CandidateArtifacts(
            facts=tuple(facts),
            entities=entities,
            relations=tuple(relations),
            questions=tuple(questions),
            simulations=simulations,
        )


class OptionalFrameworkAdapter:
    """Dependency probe plus opt-in executor; framework objects never cross this boundary."""

    def __init__(
        self,
        *,
        candidate_id: str,
        adapter_kind: str,
        import_name: str,
        distribution_name: str,
        eligible_for_selection: bool = True,
        executor: Callable[[Sequence[Document], Sequence[DeltaOperation]], CandidateRun]
        | None = None,
    ) -> None:
        self.candidate_id = candidate_id
        self.adapter_kind = adapter_kind
        self.import_name = import_name
        self.distribution_name = distribution_name
        self.executor = executor
        self.eligible_for_selection = eligible_for_selection

    def run(
        self,
        documents: Sequence[Document],
        delta_operations: Sequence[DeltaOperation],
    ) -> CandidateRun:
        if importlib.util.find_spec(self.import_name) is None:
            return self._unavailable("dependency_not_installed", None)
        try:
            version = importlib.metadata.version(self.distribution_name)
        except importlib.metadata.PackageNotFoundError:
            version = "installed-version-unknown"
        if self.executor is None:
            return self._unavailable("isolated_executor_not_configured", version)
        run = self.executor(documents, delta_operations)
        if run.adapter_kind != self.adapter_kind:
            raise ValueError("framework executor returned an incompatible adapter_kind")
        return run

    def _unavailable(self, reason: str, version: str | None) -> CandidateRun:
        return CandidateRun(
            candidate_id=self.candidate_id,
            adapter_kind=self.adapter_kind,
            framework_version=version,
            eligible_for_selection=self.eligible_for_selection,
            available=False,
            unavailable_reason=reason,
            base=None,
            delta=None,
            usage=None,
        )


def llamaindex_adapter() -> OptionalFrameworkAdapter:
    return OptionalFrameworkAdapter(
        candidate_id="llamaindex-property-graph-poc",
        adapter_kind="llamaindex",
        import_name="llama_index",
        distribution_name="llama-index-core",
    )


def graphrag_adapter() -> OptionalFrameworkAdapter:
    return OptionalFrameworkAdapter(
        candidate_id="microsoft-graphrag-isolated-poc",
        adapter_kind="graphrag",
        import_name="graphrag",
        distribution_name="graphrag",
        eligible_for_selection=False,
    )


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _question_text(context: dict[str, str], index: int) -> str:
    if index % 2 == 0:
        return (
            f"{context['persona']}在{context['scenario']}时，如何判断{context['subject']}"
            f"能否满足{context['intent']}需求？"
        )
    return (
        f"面向{context['region']}的{context['persona']}，在{context['platform']}比较"
        f"{context['subject']}时，应重点验证哪些{context['intent']}事实？"
    )


def _select_support_fact(
    facts: Sequence[FactCandidate], context: dict[str, str], fallback_index: int
) -> FactCandidate:
    intent_bigrams = _bigrams(context.get("intent", ""))
    scenario_bigrams = _bigrams(context.get("scenario", ""))
    scored = [
        (
            3 * len(intent_bigrams & _bigrams(fact.text))
            + len(scenario_bigrams & _bigrams(fact.text)),
            -index,
            fact,
        )
        for index, fact in enumerate(facts)
    ]
    best_score, _position, best_fact = max(scored, key=lambda item: (item[0], item[1]))
    return best_fact if best_score else facts[fallback_index % len(facts)]


def _bigrams(value: str) -> set[str]:
    normalized = re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())
    return {normalized[index : index + 2] for index in range(max(0, len(normalized) - 1))}
