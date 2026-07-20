"""Transaction lock identity for a logical Knowledge source."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID


def lock_source_aggregate(connection: Any, logical_source_id: UUID) -> None:
    lock_id = int.from_bytes(logical_source_id.bytes[:8], byteorder="big", signed=True)
    connection.execute("SELECT pg_advisory_xact_lock(%s::bigint)", (lock_id,))


def source_logical_id(connection: Any, *, project_id: UUID, source_id: UUID) -> UUID | None:
    cursor = connection.execute(
        """SELECT COALESCE(logical_source_id, id) AS logical_source_id
           FROM knowledge_sources WHERE id = %s AND project_id = %s""",
        (source_id, project_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return row["logical_source_id"] if isinstance(row, Mapping) else row[0]
