"""PostgreSQL read projections for direct Synthetic Lab generation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

from geo_core.synthetic_lab.channel_styles import ChannelStyleVersion
from geo_core.synthetic_lab.direct_generation import (
    DirectKnowledgeItem,
    DirectKnowledgeSnapshot,
)
from geo_core.synthetic_lab.postgres_api_read_models import SyntheticApiPage
from geo_core.synthetic_lab.postgres_rows import aggregate_from_row

if TYPE_CHECKING:
    from collections.abc import Callable


class _PostgresSyntheticApiDirectReads:
    if TYPE_CHECKING:
        # These members are supplied by ``_PostgresSyntheticApiReadsTail`` at runtime.
        _connection_factory: Callable[[], Any]

        def _open(self, project_id: UUID) -> Any: ...
    def channel_styles(
        self,
        project_id: UUID,
        *,
        limit: int,
        offset: int,
        channel: str | None = None,
        include_history: bool = False,
    ) -> SyntheticApiPage:
        connection = self._open(project_id)
        try:
            rows = connection.execute(
                """SELECT * FROM synthetic_lab_aggregate_versions
                   WHERE project_id = %s AND kind = 'channel_style'
                   ORDER BY created_at DESC, resource_id""",
                (project_id,),
            ).fetchall()
            styles: list[ChannelStyleVersion] = []
            for row in rows:
                item = aggregate_from_row(dict(row)).payload
                if isinstance(item, ChannelStyleVersion) and (
                    channel is None or item.channel == channel
                ):
                    styles.append(item)
            styles.sort(key=lambda item: (item.channel, -item.version_number))
            if not include_history:
                current: dict[str, ChannelStyleVersion] = {}
                for item in styles:
                    current.setdefault(item.channel, item)
                styles = list(current.values())
            total = len(styles)
            return SyntheticApiPage(tuple(styles[offset : offset + limit]), total, limit, offset)
        finally:
            connection.rollback()
            connection.close()

    def current_channel_style(self, project_id: UUID, channel: str) -> ChannelStyleVersion | None:
        page = self.channel_styles(
            project_id,
            limit=1000,
            offset=0,
            channel=channel,
            include_history=False,
        )
        item = page.items[0] if page.items else None
        return item if isinstance(item, ChannelStyleVersion) else None

    def direct_generation_options(self, project_id: UUID) -> dict[str, object]:
        connection = self._open(project_id)
        try:
            entities = connection.execute(
                """SELECT id, entity_type, canonical_name, canonical_url
                   FROM product_entities
                   WHERE project_id = %s AND status = 'active'
                     AND entity_type IN ('brand', 'product', 'competitor')
                   ORDER BY entity_type, canonical_name, id""",
                (project_id,),
            ).fetchall()
            evidence = connection.execute(
                """SELECT evidence.id, evidence.item_type,
                          evidence.subject_entity_id, entity.canonical_name,
                          evidence.snapshot_text, evidence.snapshot_hash,
                          evidence.public_source_title, evidence.public_source_url
                   FROM evidence_items AS evidence
                   JOIN product_entities AS entity
                     ON entity.project_id = evidence.project_id
                    AND entity.id = evidence.subject_entity_id
                   JOIN knowledge_fact_evidence_lineages AS lineage
                     ON lineage.evidence_item_id = evidence.id
                    AND lineage.project_id = evidence.project_id
                   JOIN knowledge_fact_candidates AS fact
                     ON fact.id = lineage.knowledge_fact_id
                    AND fact.project_id = lineage.project_id
                    AND fact.pipeline_run_id = lineage.pipeline_run_id
                    AND fact.source_id = lineage.knowledge_source_id
                    AND fact.document_id = lineage.knowledge_document_id
                    AND fact.chunk_id = lineage.knowledge_chunk_id
                    AND fact.statement_hash = lineage.fact_statement_hash
                   JOIN knowledge_chunks AS chunk
                     ON chunk.id = lineage.knowledge_chunk_id
                    AND chunk.project_id = lineage.project_id
                    AND chunk.pipeline_run_id = lineage.pipeline_run_id
                    AND chunk.source_id = lineage.knowledge_source_id
                    AND chunk.document_id = lineage.knowledge_document_id
                    AND chunk.text_hash = lineage.chunk_text_hash
                   WHERE evidence.project_id = %s
                     AND evidence.item_type = 'approved_fact'
                     AND evidence.fact_lineage_status = 'verified'
                     AND evidence.source_id = fact.id
                     AND evidence.source_revision_kind = 'content_hash'
                     AND evidence.source_revision_value = lineage.fact_statement_hash
                     AND evidence.snapshot_text = fact.statement
                     AND evidence.snapshot_hash = lineage.evidence_snapshot_hash
                     AND lineage.lineage_contract_version = 'knowledge-fact-evidence-v1'
                     AND fact.status = 'approved'
                     AND fact.lifecycle_status = 'active'
                     AND chunk.status = 'active'
                     AND evidence.snapshot_text IS NOT NULL
                   ORDER BY CASE WHEN entity.entity_type = 'brand' THEN 0 ELSE 1 END,
                            entity.canonical_name, evidence.item_type, evidence.id""",
                (project_id,),
            ).fetchall()
        finally:
            connection.rollback()
            connection.close()
        styles = self.channel_styles(project_id, limit=100, offset=0, include_history=False).items
        brand_ids = {row["id"] for row in entities if row["entity_type"] == "brand"}
        competitor_ids = {row["id"] for row in entities if row["entity_type"] == "competitor"}
        subjects = []
        for entity in entities:
            if entity["entity_type"] != "product":
                continue
            selected = [
                row for row in evidence if row["subject_entity_id"] in {*brand_ids, entity["id"]}
            ]
            items = tuple(
                DirectKnowledgeItem(
                    evidence_id=row["id"],
                    subject_entity_id=row["subject_entity_id"],
                    subject_name=row["canonical_name"],
                    kind=row["item_type"],
                    summary=row["snapshot_text"],
                    snapshot_hash=row["snapshot_hash"],
                    source_title=row["public_source_title"],
                    source_url=row["public_source_url"],
                )
                for row in selected
            )
            snapshot = (
                DirectKnowledgeSnapshot(
                    id=uuid5(project_id, f"direct-preview:{entity['id']}"),
                    project_id=project_id,
                    primary_subject_id=entity["id"],
                    items=items,
                )
                if any(item.subject_entity_id == entity["id"] for item in items)
                else None
            )
            competitor_items = tuple(
                DirectKnowledgeItem(
                    evidence_id=row["id"],
                    subject_entity_id=row["subject_entity_id"],
                    subject_name=row["canonical_name"],
                    kind=row["item_type"],
                    summary=row["snapshot_text"],
                    snapshot_hash=row["snapshot_hash"],
                    source_title=row["public_source_title"],
                    source_url=row["public_source_url"],
                )
                for row in evidence
                if row["subject_entity_id"] in competitor_ids
            )
            comparison_items = (*items, *competitor_items)
            comparison_snapshot = (
                DirectKnowledgeSnapshot(
                    id=uuid5(project_id, f"direct-preview-competitor:{entity['id']}"),
                    project_id=project_id,
                    primary_subject_id=entity["id"],
                    items=comparison_items,
                )
                if snapshot is not None and competitor_items
                else None
            )
            subjects.append(
                {
                    "id": entity["id"],
                    "name": entity["canonical_name"],
                    "canonical_url": entity["canonical_url"],
                    "knowledge_snapshot_hash": (
                        snapshot.snapshot_hash if snapshot is not None else None
                    ),
                    "knowledge_items": items,
                    "competitor_knowledge_snapshot_hash": (
                        comparison_snapshot.snapshot_hash
                        if comparison_snapshot is not None
                        else None
                    ),
                    "competitor_knowledge_items": comparison_items,
                }
            )
        return {
            "subjects": tuple(subjects),
            "channel_styles": tuple(styles),
            "has_competitor_knowledge": bool(competitor_ids)
            and any(row["subject_entity_id"] in competitor_ids for row in evidence),
        }


__all__ = ["_PostgresSyntheticApiDirectReads"]
