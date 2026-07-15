from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from pathlib import Path

from fastapi.testclient import TestClient

from geo_api.app_factory import create_api_app
from geo_api.engineering_routes import encode_sse_event
from geo_core.engineering import (
    AXIS_NAMES,
    AxisEvidence,
    AxisFacts,
    AxisObservation,
    AxisStatus,
    EngineeringService,
    WorkItemProjection,
    derive_axis,
    evaluate_done,
    evaluate_freshness,
)
from geo_core.engineering.ports import DeliveryReceipt


NOW = datetime(2026, 7, 15, 8, tzinfo=UTC)
SECRET = "github-app-test-secret"


class FakeEngineeringRepository:
    def __init__(self) -> None:
        self.deliveries: dict[str, DeliveryReceipt] = {}
        self.record_calls = 0
        self.items: tuple[WorkItemProjection, ...] = ()

    def record_github_delivery(self, **values: object) -> DeliveryReceipt:
        self.record_calls += 1
        delivery_id = str(values["delivery_id"])
        existing = self.deliveries.get(delivery_id)
        if existing:
            return DeliveryReceipt(delivery_id, existing.job_id, True)
        receipt = DeliveryReceipt(delivery_id, uuid4(), False)
        self.deliveries[delivery_id] = receipt
        return receipt

    def list_work_items(self, *, now: datetime):
        del now
        return self.items

    def list_events(self, *, after: int, limit: int):
        del after, limit
        return ()


class FakeEngineeringUnitOfWork:
    def __init__(self, repository: FakeEngineeringRepository) -> None:
        self.repository = repository
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


def _service(repository: FakeEngineeringRepository) -> EngineeringService:
    return EngineeringService(
        unit_of_work_factory=lambda: FakeEngineeringUnitOfWork(repository),
        github_webhook_secret=SECRET,
        clock=lambda: NOW,
    )


def _body() -> bytes:
    return json.dumps({"repository": {"id": 2468}, "action": "opened"}).encode()


def _signature(body: bytes) -> str:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_github_signature_is_verified_before_inbox_write() -> None:
    repository = FakeEngineeringRepository()
    service = _service(repository)
    body = _body()

    app = create_api_app(surface="internal", engineering_service=service)
    with TestClient(app) as client:
        rejected = client.post(
            "/v1/integrations/github/events",
            content=body,
            headers={
                "content-type": "application/json",
                "X-Hub-Signature-256": "sha256=bad",
                "X-GitHub-Delivery": "delivery-one",
                "X-GitHub-Event": "issues",
            },
        )
        accepted = client.post(
            "/v1/integrations/github/events",
            content=body,
            headers={
                "content-type": "application/json",
                "X-Hub-Signature-256": _signature(body),
                "X-GitHub-Delivery": "delivery-one",
                "X-GitHub-Event": "issues",
            },
        )

    assert rejected.status_code == 401
    assert rejected.headers["content-type"].startswith("application/problem+json")
    assert accepted.status_code == 202
    assert accepted.json()["duplicate"] is False
    assert repository.record_calls == 1


def test_github_delivery_replay_returns_the_same_job() -> None:
    repository = FakeEngineeringRepository()
    service = _service(repository)
    body = _body()
    values = {
        "delivery_id": "delivery-replayed",
        "event_name": "pull_request",
        "signature": _signature(body),
        "body": body,
    }

    first = service.accept_github_delivery(**values)
    replay = service.accept_github_delivery(**values)

    assert replay.duplicate is True
    assert replay.job_id == first.job_id
    assert len(repository.deliveries) == 1


def test_four_axis_done_requires_every_required_axis_to_be_satisfied() -> None:
    evidence = (AxisEvidence("GitHub evidence", "https://github.example/evidence"),)
    satisfied = AxisObservation(AxisStatus.SATISFIED, evidence, NOW)
    axes = {axis: satisfied for axis in AXIS_NAMES}

    assert evaluate_done(axes)
    axes["deployed"] = AxisObservation(AxisStatus.UNAVAILABLE, (), NOW)
    assert not evaluate_done(axes)
    assert derive_axis(AxisFacts(source_available=False)).status == AxisStatus.UNAVAILABLE
    assert derive_axis(AxisFacts(source_available=True)).status == AxisStatus.PENDING
    assert derive_axis(
        AxisFacts(source_available=True, blockers=("CI failed",))
    ).status == AxisStatus.BLOCKED


def test_freshness_becomes_stale_only_after_two_intervals() -> None:
    interval = timedelta(seconds=30)
    assert evaluate_freshness(
        observed_at=None, now=NOW, observation_interval=interval
    ).value == "unknown"
    assert evaluate_freshness(
        observed_at=NOW - timedelta(seconds=60), now=NOW, observation_interval=interval
    ).value == "fresh"
    assert evaluate_freshness(
        observed_at=NOW - timedelta(seconds=61), now=NOW, observation_interval=interval
    ).value == "stale"


def test_work_item_response_matches_frontend_contract_and_does_not_infer_progress() -> None:
    repository = FakeEngineeringRepository()
    unavailable = AxisObservation(AxisStatus.UNAVAILABLE, (), NOW)
    repository.items = (
        WorkItemProjection(
            id="github-issue:42",
            title="Ship engineering board",
            summary="No provider status is inferred.",
            axes={axis: unavailable for axis in AXIS_NAMES},
            blockers=("GitHub App is unavailable",),
            observed_at=NOW,
            observation_interval=timedelta(minutes=5),
        ),
    )
    app = create_api_app(surface="internal", engineering_service=_service(repository))

    with TestClient(app) as client:
        response = client.get("/v1/engineering/work-items")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "github-issue:42",
                "title": "Ship engineering board",
                "summary": "No provider status is inferred.",
                "axes": {
                    axis: {"status": "unavailable", "evidence": [], "observed_at": NOW.isoformat().replace("+00:00", "Z")}
                    for axis in AXIS_NAMES
                },
                "blockers": ["GitHub App is unavailable"],
                "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                "freshness": "fresh",
            }
        ],
        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
    }


def test_sse_encoding_and_customer_openapi_isolation() -> None:
    encoded = encode_sse_event(
        event_id=9, event_type="work_item.updated", data={"id": "github-issue:42"}
    )
    assert encoded == (
        'id: 9\nevent: work_item.updated\ndata: {"id":"github-issue:42"}\n\n'
    )

    internal_paths = set(create_api_app(surface="internal").openapi()["paths"])
    customer_paths = set(create_api_app(surface="customer").openapi()["paths"])
    assert "/v1/engineering/events" in internal_paths
    assert "/v1/integrations/github/events" in internal_paths
    assert not any(path.startswith("/v1/engineering") for path in customer_paths)
    assert not any(path.startswith("/v1/integrations/github") for path in customer_paths)


def test_unconfigured_sources_are_reported_as_unavailable() -> None:
    app = create_api_app(surface="internal")
    with TestClient(app) as client:
        response = client.get("/v1/engineering/status")

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["sources"] == {
        "github": "unavailable",
        "ci": "unavailable",
        "runtime-health": "unavailable",
    }


def test_engineering_migration_has_complete_project_scoped_projection_model() -> None:
    sql = Path("infra/db/alembic/sql/0002_engineering_governance.sql").read_text()
    for table in (
        "engineering_repositories",
        "engineering_work_items",
        "engineering_pull_requests",
        "engineering_ci_runs",
        "engineering_ci_checks",
        "engineering_service_health",
        "engineering_webhook_deliveries",
        "engineering_events",
        "engineering_job_specs",
    ):
        assert f"CREATE TABLE {table}" in sql
        assert f"'{table}'" in sql
    assert "UNIQUE (project_id, delivery_id)" in sql
    assert "engineering.github_project" in sql
    assert "engineering.reconcile" in sql
    assert "engineering.health_probe" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
