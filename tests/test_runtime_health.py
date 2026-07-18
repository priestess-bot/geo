from __future__ import annotations

import json
from uuid import uuid4

from geo_core.runtime_health import (
    HeartbeatIdentity,
    RuntimeFinding,
    RuntimeHealthThresholds,
    RuntimeHeartbeat,
)
from geo_worker.config import runtime_expected_instances, runtime_health_thresholds
from geo_worker.runtime_health import evaluate_heartbeat_health


RUNTIME_ENVIRONMENT = (
    "GEO_RUNTIME_HEARTBEAT_INTERVAL_SECONDS",
    "GEO_RUNTIME_HEARTBEAT_STALE_SECONDS",
    "GEO_RUNTIME_QUEUED_STALE_SECONDS",
    "GEO_RUNTIME_RUNNING_GRACE_SECONDS",
    "GEO_RUNTIME_OUTBOX_STALE_SECONDS",
    "GEO_RUNTIME_FAILURE_WINDOW_SECONDS",
    "GEO_RUNTIME_EXPECTED_TASK_WORKER_INSTANCES",
    "GEO_RUNTIME_EXPECTED_OUTBOX_RELAY_INSTANCES",
)


class RecordingRepository:
    def __init__(self, findings: tuple[RuntimeFinding, ...] = ()) -> None:
        self.records: list[dict[str, object]] = []
        self.returned_findings = findings

    def record_heartbeat(self, **values: object) -> None:
        self.records.append(values)

    def findings(self, **values: object) -> tuple[RuntimeFinding, ...]:
        del values
        return self.returned_findings


class FailingRepository(RecordingRepository):
    def findings(self, **values: object) -> tuple[RuntimeFinding, ...]:
        del values
        raise RuntimeError("postgresql://worker:do-not-print@database/geo")


def clear_runtime_environment(monkeypatch) -> None:
    for name in RUNTIME_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def test_runtime_health_defaults_match_the_accepted_operational_thresholds(monkeypatch) -> None:
    clear_runtime_environment(monkeypatch)

    assert runtime_health_thresholds().as_dict() == {
        "heartbeat_stale_seconds": 30,
        "queued_stale_seconds": 600,
        "running_grace_seconds": 60,
        "outbox_stale_seconds": 300,
        "failure_window_seconds": 86_400,
    }
    assert runtime_expected_instances("task_worker") == 1
    assert runtime_expected_instances("outbox_relay") == 1


def test_runtime_heartbeat_is_rate_limited_but_forced_state_changes_are_written() -> None:
    repository = RecordingRepository()
    clock = iter((100.0, 105.0, 106.0))
    heartbeat = RuntimeHeartbeat(
        repository,  # type: ignore[arg-type]
        HeartbeatIdentity("task_worker", "container", "worker-1", "release-1"),
        interval_seconds=10,
        monotonic=lambda: next(clock),
    )

    assert heartbeat.pulse()
    assert not heartbeat.pulse()
    assert heartbeat.pulse(status="stopping", force=True)
    assert [record["status"] for record in repository.records] == ["ready", "stopping"]


def test_health_evaluation_returns_nonzero_with_safe_stable_findings(monkeypatch) -> None:
    clear_runtime_environment(monkeypatch)
    project_id, job_id = uuid4(), uuid4()
    repository = RecordingRepository(
        (
            RuntimeFinding(
                "durable_job_queued_stalled", "queued", "error", project_id, job_id, 601
            ),
        )
    )

    exit_code, payload = evaluate_heartbeat_health(
        service_type="task_worker",
        repository=repository,  # type: ignore[arg-type]
        container_id="container",
        broker_probe=lambda: True,
    )

    assert exit_code == 1
    assert payload["status"] == "unhealthy"
    assert payload["error_code"] == "runtime_findings_present"
    assert payload["thresholds"] == {
        **RuntimeHealthThresholds().as_dict(),
        "expected_instances": 1,
    }
    assert payload["checks"] == {
        "database": "ok",
        "broker": "ok",
        "consumer_heartbeat": "ok",
        "queue_progress": "unhealthy",
    }
    rendered = json.dumps(payload)
    assert str(project_id) in rendered and str(job_id) in rendered
    assert "payload" not in rendered and "last_error" not in rendered


def test_health_evaluation_redacts_database_and_broker_errors(monkeypatch) -> None:
    clear_runtime_environment(monkeypatch)
    exit_code, payload = evaluate_heartbeat_health(
        service_type="outbox_relay",
        repository=FailingRepository(),  # type: ignore[arg-type]
        container_id="container",
        broker_probe=lambda: (_ for _ in ()).throw(RuntimeError("redis://:secret@valkey")),
    )

    assert exit_code == 2
    assert payload["error_code"] == "runtime_database_probe_failed"
    rendered = json.dumps(payload)
    assert "do-not-print" not in rendered
    assert "secret" not in rendered


def test_broker_failure_is_a_stable_probe_error(monkeypatch) -> None:
    clear_runtime_environment(monkeypatch)
    exit_code, payload = evaluate_heartbeat_health(
        service_type="task_worker",
        repository=RecordingRepository(),  # type: ignore[arg-type]
        container_id="container",
        broker_probe=lambda: False,
    )

    assert exit_code == 2
    assert payload["error_code"] == "runtime_broker_probe_failed"
    assert payload["checks"]["broker"] == "error"  # type: ignore[index]
