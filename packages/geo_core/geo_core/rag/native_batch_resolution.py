"""Cross-document entity resolution for the project-native RAG adapter."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from collections.abc import Mapping, Sequence

from geo_core.rag.contracts import (
    CandidateEntity,
    CandidateRelation,
    CandidateValidationFinding,
    RagSourceDocument,
)


_ENTITY_TYPE_RANK = {
    value: index
    for index, value in enumerate(
        (
            "Brand",
            "Product",
            "Competitor",
            "Feature",
            "Specification",
            "UseCase",
            "Persona",
            "PainPoint",
            "Market",
            "Channel",
        )
    )
}


def resolve_batch_entities(
    *,
    entity_sources: Mapping[tuple[str, str, str], set[str]],
    relations: Sequence[CandidateRelation],
    documents: Mapping[str, RagSourceDocument],
) -> tuple[
    tuple[CandidateEntity, ...],
    tuple[CandidateRelation, ...],
    tuple[CandidateValidationFinding, ...],
]:
    """Select one stable type per entity name and reject ambiguous relation endpoints."""
    types_by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    for project_id, entity_type, name in entity_sources:
        types_by_name[(project_id, name)].add(entity_type)
    ambiguous_names = {
        key for key, entity_types in types_by_name.items() if len(entity_types) > 1
    }
    selected_types = {
        key: min(entity_types, key=lambda value: (_ENTITY_TYPE_RANK[value], value))
        for key, entity_types in types_by_name.items()
    }
    findings: list[CandidateValidationFinding] = []
    filtered_sources: dict[tuple[str, str, str], set[str]] = {}
    for key, source_ids in entity_sources.items():
        project_id, entity_type, name = key
        if entity_type != selected_types[(project_id, name)]:
            findings.append(
                finding(
                    documents[sorted(source_ids)[0]],
                    "entity",
                    "ambiguous_entity_name_across_documents",
                    {
                        "name": name,
                        "discarded_type": entity_type,
                        "selected_type": selected_types[(project_id, name)],
                    },
                )
            )
            continue
        filtered_sources[key] = source_ids

    filtered_relations: list[CandidateRelation] = []
    for relation in relations:
        if (relation.project_id, relation.subject) in ambiguous_names or (
            relation.project_id,
            relation.object,
        ) in ambiguous_names:
            findings.append(
                finding(
                    documents[relation.source_document_id],
                    "relation",
                    "ambiguous_relation_endpoint_across_documents",
                    {
                        "subject": relation.subject,
                        "predicate": relation.predicate,
                        "object": relation.object,
                    },
                )
            )
            continue
        filtered_relations.append(relation)

    entities = tuple(
        CandidateEntity(
            candidate_id=candidate_id("entity", *key),
            project_id=key[0],
            entity_type=key[1],
            name=key[2],
            source_document_ids=tuple(sorted(source_ids)),
        )
        for key, source_ids in sorted(filtered_sources.items())
    )
    return entities, tuple(filtered_relations), tuple(findings)


def finding(
    document: RagSourceDocument,
    candidate_kind: str,
    reason_code: str,
    row: Mapping[str, object],
) -> CandidateValidationFinding:
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return CandidateValidationFinding(
        project_id=document.project_id,
        source_document_id=document.document_id,
        candidate_kind=candidate_kind,
        reason_code=reason_code,
        candidate_hash=sha256_text(canonical),
    )


def candidate_id(kind: str, *values: str) -> str:
    return f"{kind}-{hashlib.sha256('|'.join(values).encode()).hexdigest()[:24]}"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = ["candidate_id", "finding", "resolve_batch_entities", "sha256_text"]
