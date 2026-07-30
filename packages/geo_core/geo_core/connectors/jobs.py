"""Secret-free durable Job admission for Connector syncs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hmac
import re
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from geo_core.connectors.contracts import ConnectorSyncPlan, canonical_hash
from geo_core.project_scope import set_project_scope


CONNECTOR_SYNC_JOB_KIND = "connector.sync"


class ConnectorJobError(RuntimeError):
    """Connector Job admission or immutable spec validation failed."""


@dataclass(frozen=True)
class ConnectorJobSpec:
    project_id: UUID
    run_id: UUID
    expected_run_version: int
    plan_hash: str

    def __post_init__(self) -> None:
        if self.project_id.int == 0 or self.run_id.int == 0:
            raise ConnectorJobError("Connector Job identities cannot be nil")
        if self.expected_run_version < 1:
            raise ConnectorJobError("Connector Run version must be positive")
        if re.fullmatch(r"[0-9a-f]{64}", self.plan_hash) is None:
            raise ConnectorJobError("Connector plan hash must be SHA-256")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": CONNECTOR_SYNC_JOB_KIND,
            "project_id": str(self.project_id),
            "run_id": str(self.run_id),
            "expected_run_version": self.expected_run_version,
            "plan_hash": self.plan_hash,
        }

    @property
    def spec_hash(self) -> str:
        return canonical_hash(self.payload())


@dataclass(frozen=True)
class EnqueuedConnectorJob:
    job_id: UUID
    input_hash: str
    replayed: bool


class PostgresConnectorJobRepository:
    def __init__(self, *, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def enqueue(
        self,
        *,
        plan: ConnectorSyncPlan,
        run_id: UUID,
        expected_run_version: int,
        max_attempts: int = 3,
    ) -> EnqueuedConnectorJob:
        spec = ConnectorJobSpec(
            project_id=plan.project_id,
            run_id=run_id,
            expected_run_version=expected_run_version,
            plan_hash=plan.plan_hash,
        )
        with self._connect() as connection:
            set_project_scope(connection, plan.project_id)
            row = connection.execute(
                """SELECT * FROM geo_enqueue_connector_sync(
                       %s, %s, %s, %s, %s, %s
                   )""",
                (
                    plan.project_id,
                    run_id,
                    expected_run_version,
                    spec.spec_hash,
                    Jsonb(spec.payload()),
                    max_attempts,
                ),
            ).fetchone()
        values = _row(row)
        if not hmac.compare_digest(values["input_hash"], spec.spec_hash):
            raise ConnectorJobError("Connector Job input hash changed during admission")
        return EnqueuedConnectorJob(
            job_id=values["job_id"],
            input_hash=values["input_hash"],
            replayed=values["replayed"],
        )


def _row(row: object) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        values = row
    elif isinstance(row, tuple) and len(row) == 3:
        values = {"job_id": row[0], "input_hash": row[1], "replayed": row[2]}
    else:
        raise ConnectorJobError("Connector Job admission returned no result")
    if (
        not isinstance(values.get("job_id"), UUID)
        or not isinstance(values.get("input_hash"), str)
        or not isinstance(values.get("replayed"), bool)
    ):
        raise ConnectorJobError("Connector Job admission result is invalid")
    return values


__all__ = [
    "CONNECTOR_SYNC_JOB_KIND",
    "ConnectorJobError",
    "ConnectorJobSpec",
    "EnqueuedConnectorJob",
    "PostgresConnectorJobRepository",
]
