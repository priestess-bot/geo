"""psycopg adapter and unit of work for engineering truth projections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from geo_core.engineering.domain import AxisEvidence, AxisObservation, AxisStatus, WorkItemProjection
from geo_core.engineering.ports import (
    DeliveryReceipt,
    DeliveryConflictError,
    EngineeringEvent,
    EngineeringJobReceipt,
    UnknownRepositoryError,
)


def _row(value: Any) -> dict[str, Any]:
    return dict(value) if value is not None else {}


class PostgresEngineeringRepository:
    def __init__(self, connection: Any, *, project_id: UUID | None) -> None:
        self._connection = connection
        self._project_id = project_id
        if project_id is not None:
            self._set_project(project_id)

    def _set_project(self, project_id: UUID) -> None:
        self._connection.execute(
            "SELECT set_config('geo.project_id', %s, true)", (str(project_id),)
        )
        self._project_id = project_id

    def _fetchone(self, query: str, parameters: tuple[object, ...]) -> dict[str, Any]:
        from psycopg.rows import dict_row

        with self._connection.cursor(row_factory=dict_row) as cursor:
            return _row(cursor.execute(query, parameters).fetchone())

    def _fetchall(
        self, query: str, parameters: tuple[object, ...] = ()
    ) -> tuple[dict[str, Any], ...]:
        from psycopg.rows import dict_row

        with self._connection.cursor(row_factory=dict_row) as cursor:
            return tuple(dict(row) for row in cursor.execute(query, parameters).fetchall())

    def _binding(
        self, *, external_repository_id: int | None = None, repository_id: UUID | None = None
    ) -> dict[str, Any]:
        if external_repository_id is not None:
            predicate, value = "external_repository_id = %s", external_repository_id
        elif repository_id is not None:
            predicate, value = "repository_id = %s", repository_id
        else:
            raise ValueError("a repository identifier is required")
        binding = self._fetchone(
            f"SELECT project_id, repository_id FROM engineering_github_bindings WHERE {predicate}",
            (value,),
        )
        if not binding:
            raise UnknownRepositoryError("GitHub repository is not bound to a GEO project")
        self._set_project(binding["project_id"])
        return binding

    def record_github_delivery(
        self,
        *,
        delivery_id: str,
        event_name: str,
        external_repository_id: int,
        payload_hash: str,
        payload: Mapping[str, object],
        received_at: Any,
    ) -> DeliveryReceipt:
        from psycopg.types.json import Jsonb

        binding = self._binding(external_repository_id=external_repository_id)
        current = self._fetchone(
            """
            SELECT d.event_name, d.payload_hash, d.repository_id, s.job_id, j.status AS job_status
            FROM engineering_webhook_deliveries d
            JOIN engineering_job_specs s
              ON s.delivery_id = d.id AND s.project_id = d.project_id
            JOIN durable_jobs j ON j.id = s.job_id AND j.project_id = s.project_id
            WHERE d.delivery_id = %s
            """,
            (delivery_id,),
        )
        if current:
            immutable = (current["event_name"], current["payload_hash"], current["repository_id"])
            candidate = (event_name, payload_hash, binding["repository_id"])
            if immutable != candidate:
                raise DeliveryConflictError("GitHub delivery id content does not match its inbox row")
            return DeliveryReceipt(
                delivery_id, current["job_id"], True, current["job_status"]
            )

        inbox_id, job_id = uuid4(), uuid4()
        self._connection.execute(
            """
            INSERT INTO engineering_webhook_deliveries (
              id, project_id, repository_id, delivery_id, event_name,
              payload_hash, payload, received_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                inbox_id,
                binding["project_id"],
                binding["repository_id"],
                delivery_id,
                event_name,
                payload_hash,
                Jsonb(dict(payload)),
                received_at,
            ),
        )
        self._connection.execute(
            """
            INSERT INTO durable_jobs (
              id, project_id, kind, input_hash, idempotency_key, next_run_at
            ) VALUES (%s, %s, 'engineering.github_project', %s, %s, %s)
            """,
            (job_id, binding["project_id"], payload_hash, f"github:{delivery_id}", received_at),
        )
        self._connection.execute(
            """
            INSERT INTO engineering_job_specs (
              job_id, project_id, operation, repository_id, delivery_id, reason
            ) VALUES (%s, %s, 'github_project', %s, %s, 'signed GitHub delivery')
            """,
            (job_id, binding["project_id"], binding["repository_id"], inbox_id),
        )
        self._enqueue(job_id=job_id, project_id=binding["project_id"], now=received_at)
        return DeliveryReceipt(delivery_id, job_id, False, "queued")

    def register_repository(
        self,
        *,
        installation_id: int,
        external_repository_id: int,
        full_name: str,
        web_url: str,
        default_branch: str,
    ) -> UUID:
        if self._project_id is None:
            raise RuntimeError("project scope is required to register a GitHub repository")
        row = self._fetchone(
            """
            INSERT INTO engineering_repositories (
              project_id, installation_id, external_repository_id,
              full_name, web_url, default_branch
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, external_repository_id) DO UPDATE SET
              installation_id = EXCLUDED.installation_id,
              full_name = EXCLUDED.full_name,
              web_url = EXCLUDED.web_url,
              default_branch = EXCLUDED.default_branch,
              status = 'configured',
              updated_at = clock_timestamp()
            RETURNING id
            """,
            (
                self._project_id,
                installation_id,
                external_repository_id,
                full_name,
                web_url,
                default_branch,
            ),
        )
        repository_id = row["id"]
        binding = self._connection.execute(
            """
            INSERT INTO engineering_github_bindings (
              external_repository_id, project_id, repository_id
            ) VALUES (%s, %s, %s)
            ON CONFLICT (external_repository_id) DO UPDATE SET
              repository_id = EXCLUDED.repository_id
            WHERE engineering_github_bindings.project_id = EXCLUDED.project_id
            """,
            (external_repository_id, self._project_id, repository_id),
        )
        if binding.rowcount != 1:
            raise ValueError("GitHub repository is already bound to a different project")
        return repository_id

    def _enqueue(self, *, job_id: UUID, project_id: UUID, now: Any) -> None:
        from psycopg.types.json import Jsonb

        self._connection.execute(
            """
            INSERT INTO broker_outbox (
              project_id, job_id, topic, payload, idempotency_key, available_at
            ) VALUES (%s, %s, 'engineering.jobs', %s, %s, %s)
            ON CONFLICT (project_id, idempotency_key) DO NOTHING
            """,
            (project_id, job_id, Jsonb({"job_id": str(job_id)}), f"engineering:{job_id}", now),
        )

    def list_work_items(self, *, now: Any) -> Sequence[WorkItemProjection]:
        if self._project_id is None:
            return ()
        rows = self._fetchall(
            """
            SELECT id, title, summary, blockers, observed_at, observation_interval_seconds,
                   planned_status, planned_evidence, planned_observed_at,
                   implemented_status, implemented_evidence, implemented_observed_at,
                   verified_status, verified_evidence, verified_observed_at,
                   deployed_status, deployed_evidence, deployed_observed_at
            FROM engineering_work_items
            ORDER BY updated_at DESC, id
            """,
        )
        return tuple(_work_item(row) for row in rows)

    def create_job(
        self,
        *,
        operation: str,
        repository_id: UUID | None,
        service_key: str | None,
        reason: str,
        idempotency_key: str,
        now: Any,
    ) -> EngineeringJobReceipt:
        if repository_id is not None:
            binding = self._binding(repository_id=repository_id)
            project_id = binding["project_id"]
        elif self._project_id is not None:
            project_id = self._project_id
        else:
            raise UnknownRepositoryError("an engineering project or repository is required")
        kind = f"engineering.{operation}"
        input_hash = hashlib.sha256(
            json.dumps(
                {"repository_id": str(repository_id or ""), "service_key": service_key or ""},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        row = self._fetchone(
            """
            SELECT id, status FROM durable_jobs
            WHERE project_id = %s AND kind = %s AND idempotency_key = %s AND replay_nonce = 0
            """,
            (project_id, kind, idempotency_key),
        )
        if row:
            return EngineeringJobReceipt(row["id"], row["status"])
        job_id = uuid4()
        self._connection.execute(
            """
            INSERT INTO durable_jobs (
              id, project_id, kind, input_hash, idempotency_key, next_run_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (job_id, project_id, kind, input_hash, idempotency_key, now),
        )
        self._connection.execute(
            """
            INSERT INTO engineering_job_specs (
              job_id, project_id, operation, repository_id, service_key, reason
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (job_id, project_id, operation, repository_id, service_key, reason),
        )
        self._enqueue(job_id=job_id, project_id=project_id, now=now)
        return EngineeringJobReceipt(job_id, "queued")

    def list_events(self, *, after: int, limit: int) -> Sequence[EngineeringEvent]:
        if self._project_id is None:
            return ()
        rows = self._fetchall(
            """
            SELECT sequence, event_type, data, observed_at
            FROM engineering_events WHERE sequence > %s ORDER BY sequence LIMIT %s
            """,
            (after, limit),
        )
        return tuple(
            EngineeringEvent(
                sequence=row["sequence"],
                event_type=row["event_type"],
                data=row["data"],
                observed_at=row["observed_at"],
            )
            for row in rows
        )

    def append_event(
        self, *, event_type: str, data: Mapping[str, object], observed_at: Any
    ) -> int:
        from psycopg.types.json import Jsonb

        if self._project_id is None:
            raise RuntimeError("project scope is required")
        row = self._fetchone(
            """
            INSERT INTO engineering_events (project_id, event_type, data, observed_at)
            VALUES (%s, %s, %s, %s) RETURNING sequence
            """,
            (self._project_id, event_type, Jsonb(dict(data)), observed_at),
        )
        return int(row["sequence"])

    def upsert_pull_request(self, projection: Mapping[str, object]) -> None:
        self._upsert_projection("engineering_pull_requests", "external_number", projection)

    def upsert_ci_run(self, projection: Mapping[str, object]) -> None:
        self._upsert_projection("engineering_ci_runs", "external_id", projection)

    def replace_ci_checks(
        self, *, run_id: UUID, checks: Sequence[Mapping[str, object]]
    ) -> None:
        if self._project_id is None:
            raise RuntimeError("project scope is required")
        self._connection.execute(
            "DELETE FROM engineering_ci_checks WHERE ci_run_id = %s", (run_id,)
        )
        for check in checks:
            values = dict(check) | {"ci_run_id": run_id, "project_id": self._project_id}
            self._insert_mapping("engineering_ci_checks", values)

    def upsert_service_health(self, projection: Mapping[str, object]) -> None:
        self._upsert_projection("engineering_service_health", "service_key", projection)

    def upsert_work_item(self, projection: Mapping[str, object]) -> None:
        self._upsert_projection("engineering_work_items", "external_id", projection)

    def _upsert_projection(
        self, table: str, conflict_column: str, projection: Mapping[str, object]
    ) -> None:
        if self._project_id is None:
            raise RuntimeError("project scope is required")
        values = dict(projection) | {"project_id": self._project_id}
        for column in tuple(values):
            if column.endswith("_evidence") and isinstance(values[column], list):
                from psycopg.types.json import Jsonb

                values[column] = Jsonb(values[column])
        columns = tuple(values)
        assignments = ", ".join(
            f"{column} = EXCLUDED.{column}"
            for column in columns
            if column not in {"project_id", conflict_column, "id"}
        )
        placeholders = ", ".join(["%s"] * len(columns))
        self._connection.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({'repository_id, ' if conflict_column != 'service_key' else 'project_id, '}{conflict_column}) "
            f"DO UPDATE SET {assignments}",
            tuple(values[column] for column in columns),
        )

    def _insert_mapping(self, table: str, values: Mapping[str, object]) -> None:
        columns = tuple(values)
        placeholders = ", ".join(["%s"] * len(columns))
        self._connection.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )


class PostgresEngineeringUnitOfWork:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        project_id: UUID | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._project_id = project_id
        self._connection: Any = None
        self.repository: PostgresEngineeringRepository
        self._committed = False

    def __enter__(self) -> "PostgresEngineeringUnitOfWork":
        self._connection = self._connection_factory()
        self.repository = PostgresEngineeringRepository(
            self._connection, project_id=self._project_id
        )
        return self

    def commit(self) -> None:
        self._connection.commit()
        self._committed = True

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if exc_type is not None or not self._committed:
                self._connection.rollback()
        finally:
            self._connection.close()


def _evidence(value: object) -> tuple[AxisEvidence, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        AxisEvidence(label=str(entry["label"]), url=entry.get("url"))
        for entry in value
        if isinstance(entry, dict) and str(entry.get("label") or "").strip()
    )


def _work_item(row: Mapping[str, Any]) -> WorkItemProjection:
    axes = {
        axis: AxisObservation(
            status=AxisStatus(row[f"{axis}_status"]),
            evidence=_evidence(row[f"{axis}_evidence"]),
            observed_at=row[f"{axis}_observed_at"],
        )
        for axis in ("planned", "implemented", "verified", "deployed")
    }
    return WorkItemProjection(
        id=str(row["id"]),
        title=row["title"],
        summary=row["summary"],
        axes=axes,
        blockers=tuple(row["blockers"] or ()),
        observed_at=row["observed_at"],
        observation_interval=timedelta(seconds=row["observation_interval_seconds"]),
    )
