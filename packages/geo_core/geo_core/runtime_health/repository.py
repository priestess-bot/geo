"""Short-transaction PostgreSQL access for runtime operational evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID


ServiceType = Literal[
    "task_worker",
    "outbox_relay",
    "style_browser_worker",
    "synthetic_artifact_maintenance_worker",
    "workflow_c_maintenance_worker",
    "workflow_c_maintenance_scheduler",
    "recommendation_artifact_maintenance_worker",
    "recommendation_artifact_maintenance_scheduler",
    "connector_worker",
    "browser_capture_worker",
]
HeartbeatStatus = Literal["starting", "ready", "stopping", "failed"]


@dataclass(frozen=True)
class RuntimeHealthThresholds:
    heartbeat_stale_seconds: int = 30
    queued_stale_seconds: int = 600
    running_grace_seconds: int = 60
    outbox_stale_seconds: int = 300
    failure_window_seconds: int = 86_400

    def __post_init__(self) -> None:
        ranges = {
            "heartbeat_stale_seconds": (self.heartbeat_stale_seconds, 1, 3_600),
            "queued_stale_seconds": (self.queued_stale_seconds, 1, 604_800),
            "running_grace_seconds": (self.running_grace_seconds, 0, 86_400),
            "outbox_stale_seconds": (self.outbox_stale_seconds, 1, 604_800),
            "failure_window_seconds": (self.failure_window_seconds, 1, 2_592_000),
        }
        for name, (value, minimum, maximum) in ranges.items():
            if not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")

    def as_dict(self) -> dict[str, int]:
        return {
            "heartbeat_stale_seconds": self.heartbeat_stale_seconds,
            "queued_stale_seconds": self.queued_stale_seconds,
            "running_grace_seconds": self.running_grace_seconds,
            "outbox_stale_seconds": self.outbox_stale_seconds,
            "failure_window_seconds": self.failure_window_seconds,
        }


@dataclass(frozen=True)
class RuntimeFinding:
    code: str
    category: str
    severity: str
    project_id: UUID | None
    job_id: UUID | None
    age_seconds: int | None

    def public_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "project_id": str(self.project_id) if self.project_id else None,
            "job_id": str(self.job_id) if self.job_id else None,
            "age_seconds": self.age_seconds,
        }


def _mapping(row: Any, description: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    names = [column.name for column in description]
    return dict(zip(names, row, strict=True))


class RuntimeHealthRepository:
    """Use SECURITY DEFINER functions without granting cross-project table access."""

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def record_heartbeat(
        self,
        *,
        service_type: ServiceType,
        container_id: str,
        instance_id: str,
        release_version: str,
        status: HeartbeatStatus,
    ) -> None:
        with self._connection_factory() as connection:
            connection.execute(
                "SELECT geo_worker_record_runtime_heartbeat(%s, %s, %s, %s, %s)",
                (service_type, container_id, instance_id, release_version, status),
            )

    def findings(
        self,
        *,
        service_type: ServiceType,
        container_id: str,
        expected_instances: int,
        thresholds: RuntimeHealthThresholds,
    ) -> tuple[RuntimeFinding, ...]:
        with self._connection_factory() as connection:
            cursor = connection.execute(
                """SELECT * FROM geo_worker_runtime_findings(
                       %s, %s, %s, %s, %s, %s, %s, %s
                   )""",
                (
                    service_type,
                    container_id,
                    expected_instances,
                    thresholds.heartbeat_stale_seconds,
                    thresholds.queued_stale_seconds,
                    thresholds.running_grace_seconds,
                    thresholds.outbox_stale_seconds,
                    thresholds.failure_window_seconds,
                ),
            )
            return tuple(
                RuntimeFinding(
                    code=values["finding_code"],
                    category=values["finding_category"],
                    severity=values["severity"],
                    project_id=values["project_id"],
                    job_id=values["job_id"],
                    age_seconds=values["age_seconds"],
                )
                for row in cursor.fetchall()
                for values in (_mapping(row, cursor.description),)
            )
