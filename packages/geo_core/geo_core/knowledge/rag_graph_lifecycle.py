"""Shared lifecycle projection for approved Knowledge graph rows."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def archive_unreferenced_graph_rows(connection: Any, project_id: UUID) -> None:
    """Archive approved graph rows after their last active source is removed."""

    connection.execute(
        """UPDATE knowledge_graph_entities entity
           SET status = 'archived', updated_at = clock_timestamp()
           WHERE entity.project_id = %s AND entity.status = 'current'
             AND NOT EXISTS (
               SELECT 1 FROM knowledge_graph_entity_sources source
               WHERE source.graph_entity_id = entity.id
                 AND source.project_id = entity.project_id
                 AND source.lifecycle_status = 'active'
             )""",
        (project_id,),
    )
    connection.execute(
        """UPDATE knowledge_graph_relations relation
           SET status = 'archived', updated_at = clock_timestamp()
           WHERE relation.project_id = %s AND relation.status = 'current'
             AND NOT EXISTS (
               SELECT 1 FROM knowledge_graph_relation_sources source
               WHERE source.graph_relation_id = relation.id
                 AND source.project_id = relation.project_id
                 AND source.lifecycle_status = 'active'
             )""",
        (project_id,),
    )
