"""Small PostgreSQL RLS scope helpers shared by new application and worker adapters."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID


def set_project_scope(connection: Any, project_id: UUID) -> None:
    """Set both scalar lineage and the authoritative project array for one transaction."""
    connection.execute(
        """SELECT set_config('geo.project_id', %s, true),
                  set_config('geo.project_ids', %s, true)""",
        (str(project_id), json.dumps([str(project_id)])),
    )
