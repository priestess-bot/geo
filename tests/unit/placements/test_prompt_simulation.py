from contextlib import AbstractContextManager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from geo_core.placements.application import PlacementApplication
from geo_core.placements.domain import JobReference, PlacementRuleViolation
from geo_core.placements.simulation import PromptSimulation


class _UnitOfWork(AbstractContextManager[Any]):
    def __init__(self, repository: Any) -> None:
        self.placements = repository
        self.committed = False

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def _values() -> dict[str, Any]:
    return {
        "project_id": uuid4(),
        "destination_id": uuid4(),
        "template_release_id": uuid4(),
        "primary_brand_entity_id": uuid4(),
        "product_entity_id": uuid4(),
        "goals": {},
        "constraints": {},
        "variables": {},
        "model_policy_hash": "a" * 64,
        "configured_model": "deepseek-v4-flash",
        "model_call_budget": 2,
        "requested_by": uuid4(),
        "idempotency_key": "simulation-unit-test-0001",
    }


def test_simulation_rejects_empty_and_duplicate_evidence_before_persistence() -> None:
    application = PlacementApplication(lambda project_id: _UnitOfWork(SimpleNamespace()))
    with pytest.raises(PlacementRuleViolation, match="requires governed evidence"):
        application.create_prompt_simulation(evidence_item_ids=(), **_values())
    evidence_id = uuid4()
    with pytest.raises(PlacementRuleViolation, match="must be unique"):
        application.create_prompt_simulation(
            evidence_item_ids=(evidence_id, evidence_id), **_values()
        )


def test_simulation_rejects_an_invalid_model_policy_hash() -> None:
    values = _values()
    values["model_policy_hash"] = "not-a-hash"
    application = PlacementApplication(lambda project_id: _UnitOfWork(SimpleNamespace()))

    with pytest.raises(PlacementRuleViolation, match="lowercase SHA-256"):
        application.create_prompt_simulation(evidence_item_ids=(uuid4(),), **values)


def test_simulation_domain_cannot_be_marked_publishable() -> None:
    with pytest.raises(ValueError, match="non-publishable"):
        PromptSimulation(
            id=uuid4(),
            project_id=uuid4(),
            destination_id=uuid4(),
            destination_policy_version_id=None,
            template_release_id=uuid4(),
            primary_brand_entity_id=uuid4(),
            product_entity_id=uuid4(),
            requested_by=uuid4(),
            input_hash="a" * 64,
            test_only=True,
            publication_eligible=True,
            created_at=datetime.now(UTC),
            generation_job_id=uuid4(),
            generation_status="queued",
            configured_model="deepseek-v4-flash",
            model_call_budget=2,
            artifact_status="not_created",
        )


def test_simulation_create_commits_repository_result() -> None:
    simulation = SimpleNamespace(input_hash="a" * 64)
    project_id = uuid4()
    job = JobReference(uuid4(), project_id, "prompt_simulation.generate", "queued")

    class Repository:
        def create_prompt_simulation(self, **values: object):
            assert values["model_call_budget"] == 1
            return simulation, job

    uow = _UnitOfWork(Repository())
    application = PlacementApplication(lambda scoped_project_id: uow)
    values = _values()
    values.update(project_id=project_id, model_call_budget=1)

    result = application.create_prompt_simulation(
        evidence_item_ids=(uuid4(),), **values
    )

    assert result == (simulation, job)
    assert uow.committed is True
