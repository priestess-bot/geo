from __future__ import annotations

from datetime import timedelta
from typing import cast
from types import SimpleNamespace

import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.prompts.test_execution_contracts import PROMPT_TEST_REQUIRED_JOB_KINDS
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_REQUIRED_JOB_KINDS,
)
from geo_worker import tasks
from geo_worker.non_b_handlers import SYNTHETIC_REQUIRED_JOB_KINDS
from geo_worker import workflow_c_production
from geo_worker.workflow_c_handlers import WORKFLOW_C_REQUIRED_JOB_KINDS


class _Handler:
    def handle(self, lease):
        del lease
        return {}


class _Heartbeat:
    def __init__(self) -> None:
        self.started = False

    def mark_starting(self) -> None:
        self.started = True


def _handler_map(kinds: frozenset[str]) -> dict[str, _Handler]:
    return {kind: _Handler() for kind in kinds}


def test_shared_worker_composition_registers_all_real_builder_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked: list[str] = []

    def prompt(*, store, lease_for):
        del store, lease_for
        invoked.append("prompt")
        return _handler_map(PROMPT_TEST_REQUIRED_JOB_KINDS)

    def synthetic(*, store, lease_for):
        del store, lease_for
        invoked.append("synthetic")
        return _handler_map(SYNTHETIC_REQUIRED_JOB_KINDS)

    def recommendations(*, store, lease_for):
        del store, lease_for
        invoked.append("recommendations")
        return _handler_map(RECOMMENDATION_REQUIRED_JOB_KINDS)

    def workflow_c(*, store, lease_for):
        del store, lease_for
        invoked.append("workflow_c")
        return _handler_map(WORKFLOW_C_REQUIRED_JOB_KINDS)

    monkeypatch.setattr(tasks, "build_prompt_program_worker_handlers", prompt)
    monkeypatch.setattr(tasks, "build_synthetic_lab_worker_handlers", synthetic)
    monkeypatch.setattr(
        tasks,
        "build_recommendation_generation_worker_handlers",
        recommendations,
    )
    monkeypatch.setattr(tasks, "build_workflow_c_production_worker_handlers", workflow_c)

    handlers = tasks.build_shared_non_b_handlers(
        base={},
        store=cast(PostgresDurableJobStore, object()),
        lease_for=timedelta(seconds=120),
    )

    assert invoked == ["prompt", "synthetic", "recommendations", "workflow_c"]
    assert (
        PROMPT_TEST_REQUIRED_JOB_KINDS
        | SYNTHETIC_REQUIRED_JOB_KINDS
        | RECOMMENDATION_REQUIRED_JOB_KINDS
        | WORKFLOW_C_REQUIRED_JOB_KINDS
    ) <= frozenset(handlers)


def test_shared_worker_composition_fails_before_consumption_when_builder_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks,
        "build_prompt_program_worker_handlers",
        lambda **_kwargs: _handler_map(PROMPT_TEST_REQUIRED_JOB_KINDS),
    )
    monkeypatch.setattr(
        tasks,
        "build_synthetic_lab_worker_handlers",
        lambda **_kwargs: _handler_map(SYNTHETIC_REQUIRED_JOB_KINDS),
    )
    monkeypatch.setattr(
        tasks,
        "build_recommendation_generation_worker_handlers",
        lambda **_kwargs: _handler_map(RECOMMENDATION_REQUIRED_JOB_KINDS),
    )

    def unavailable(**_kwargs):
        raise RuntimeError("Workflow C PostgreSQL composition is unavailable")

    monkeypatch.setattr(tasks, "build_workflow_c_production_worker_handlers", unavailable)

    with pytest.raises(RuntimeError, match="Workflow C PostgreSQL composition"):
        tasks.build_shared_non_b_handlers(
            base={},
            store=cast(PostgresDurableJobStore, object()),
            lease_for=timedelta(seconds=120),
        )


def test_task_worker_boot_composes_dispatcher_before_marking_runtime_starting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed: list[bool] = []
    heartbeat = _Heartbeat()
    middleware = tasks.RuntimeHeartbeatMiddleware()

    monkeypatch.setattr(tasks, "dispatcher", lambda: composed.append(True))
    monkeypatch.setattr(middleware, "_heartbeat", lambda: heartbeat)

    middleware.after_process_boot(object())

    assert composed == [True]
    assert heartbeat.started is True


def test_workflow_c_production_composes_the_exact_real_operation_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = _workflow_c_operations()
    monkeypatch.setattr(
        workflow_c_production,
        "PostgresWorkflowCJobSpecRepository",
        lambda _connect: object(),
    )
    monkeypatch.setattr(
        workflow_c_production,
        "build_workflow_c_sampling_operations",
        lambda **_kwargs: {
            "sampling.provider_execute": operations["provider"],
            "sampling.manual_import": operations["manual"],
        },
    )
    monkeypatch.setattr(
        workflow_c_production,
        "build_workflow_c_metric_judge_operations",
        lambda **_kwargs: {
            "workflow_c.metric_judge": operations["judge"],
            "workflow_c.metric_arbiter": operations["arbiter"],
        },
    )
    monkeypatch.setattr(
        workflow_c_production,
        "build_workflow_c_analysis_operations",
        lambda **_kwargs: SimpleNamespace(
            semantic_metrics=operations["semantic"],
            comparison=operations["comparison"],
            drift=operations["drift"],
        ),
    )
    monkeypatch.setattr(
        workflow_c_production,
        "build_workflow_c_alert_operations",
        lambda **_kwargs: SimpleNamespace(
            schedule=operations["schedule"], evaluate=operations["evaluate"]
        ),
    )
    monkeypatch.setattr(
        workflow_c_production,
        "PostgresWorkflowCAdminInboxWriter",
        lambda _connect: object(),
    )
    monkeypatch.setattr(
        workflow_c_production,
        "build_workflow_c_notification_dispatcher",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        workflow_c_production,
        "PostgresWorkflowCAlertNotificationOperation",
        lambda **_kwargs: operations["notify"],
    )

    handlers = workflow_c_production.build_workflow_c_production_worker_handlers(
        database_url="postgresql://unused",
        store=cast(PostgresDurableJobStore, object()),
        model_runtime=object(),
        provider_result_recovery=object(),
        workflow_c_artifact_keyring_path="/unused",
        lease_for=timedelta(seconds=120),
    )

    assert frozenset(handlers) == WORKFLOW_C_REQUIRED_JOB_KINDS


def test_workflow_c_production_composition_rejects_a_missing_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow_c_production,
        "PostgresWorkflowCJobSpecRepository",
        lambda _connect: object(),
    )
    monkeypatch.setattr(
        workflow_c_production,
        "build_workflow_c_sampling_operations",
        lambda **_kwargs: {},
    )

    with pytest.raises(
        workflow_c_production.WorkflowCProductionCompositionError,
        match="sampling.provider_execute",
    ):
        workflow_c_production.build_workflow_c_production_worker_handlers(
            database_url="postgresql://unused",
            store=cast(PostgresDurableJobStore, object()),
            model_runtime=object(),
            provider_result_recovery=object(),
            workflow_c_artifact_keyring_path="/unused",
            lease_for=timedelta(seconds=120),
        )


def _workflow_c_operations() -> dict[str, _Operation]:
    return {
        "provider": _Operation(),
        "manual": _Operation(),
        "semantic": _Operation(),
        "judge": _Operation(),
        "arbiter": _Operation(),
        "comparison": _Operation(),
        "drift": _Operation(),
        "schedule": _Operation(),
        "evaluate": _Operation(),
        "notify": _Operation(),
    }


class _Operation:
    def execute(self, lease):
        del lease
        return {}
