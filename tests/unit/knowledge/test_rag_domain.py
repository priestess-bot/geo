from __future__ import annotations

from dataclasses import replace
import hashlib
from uuid import uuid4

import pytest

from geo_core.knowledge.rag_domain import (
    KnowledgeRagChunk,
    KnowledgeRagClaim,
    KnowledgeRagContractError,
    canonical_candidate_artifact,
    validate_candidate_graph,
)
from geo_core.rag import (
    CandidateEntity,
    CandidateFact,
    CandidateGraph,
    CandidateRelation,
)


def _chunk(index: int, text: str) -> KnowledgeRagChunk:
    return KnowledgeRagChunk(uuid4(), index, text, hashlib.sha256(text.encode()).hexdigest())


def _claim() -> KnowledgeRagClaim:
    chunks = (
        _chunk(0, "A1 的流量为每分钟 2 升。\nA1 belongs_to 星澜"),
        _chunk(1, "页脚和导航内容。"),
    )
    return KnowledgeRagClaim(
        project_id=uuid4(),
        pipeline_run_id=uuid4(),
        source_id=uuid4(),
        logical_source_id=uuid4(),
        document_id=uuid4(),
        title="A1 文档",
        input_hash="a" * 64,
        adapter_release="project-native-rag-v1",
        selection_manifest_hash="b" * 64,
        configured_model="deepseek-v4-flash",
        model_call_budget=6,
        requested_by=uuid4(),
        chunks=chunks,
    )


def _graph(claim: KnowledgeRagClaim) -> CandidateGraph:
    source = str(claim.chunks[0].chunk_id)
    project = str(claim.project_id)
    return CandidateGraph(
        facts=(CandidateFact("fact-1", project, "A1 的流量为每分钟 2 升。", source, "line:1"),),
        entities=(
            CandidateEntity("entity-1", project, "Product", "A1", (source,)),
            CandidateEntity("entity-2", project, "Brand", "星澜", (source,)),
        ),
        relations=(
            CandidateRelation("relation-1", project, "A1", "belongs_to", "星澜", source, "line:2"),
        ),
        questions=(),
    )


def test_claim_maps_chunks_to_one_document_group_and_validates_graph_lineage() -> None:
    claim = _claim()

    documents = claim.source_documents()
    validate_candidate_graph(claim, _graph(claim))

    assert len(documents) == 2
    assert {item.group_id for item in documents} == {str(claim.document_id)}
    assert {item.document_id for item in documents} == {str(item.chunk_id) for item in claim.chunks}


def test_candidate_artifact_is_canonical_and_framework_neutral() -> None:
    claim = _claim()
    first, first_hash = canonical_candidate_artifact(claim, _graph(claim))
    second, second_hash = canonical_candidate_artifact(claim, _graph(claim))

    assert first == second
    assert first_hash == second_hash == hashlib.sha256(first).hexdigest()
    assert b"knowledge-rag-candidate-artifact-v1" in first
    assert b"llama_index" not in first


def test_graph_rejects_cross_project_and_unknown_chunk_sources() -> None:
    claim = _claim()
    graph = _graph(claim)

    with pytest.raises(KnowledgeRagContractError, match="project or source"):
        validate_candidate_graph(
            claim,
            replace(graph, facts=(replace(graph.facts[0], project_id=str(uuid4())),)),
        )

    with pytest.raises(KnowledgeRagContractError, match="project or source"):
        validate_candidate_graph(
            claim,
            replace(
                graph,
                facts=(replace(graph.facts[0], source_document_id=str(uuid4())),),
            ),
        )
