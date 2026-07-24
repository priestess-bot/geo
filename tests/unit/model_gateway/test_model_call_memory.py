from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from geo_core.model_gateway.application_support import attempt_draft, request_identity
from geo_core.model_gateway.ports import (
    ModelCallPersistenceError,
    ModelCallVersionConflict,
)

from .model_call_application_test_support import NOW, application_fixture


def test_commit_time_cas_prevents_concurrent_budget_overcommit() -> None:
    fixture = application_fixture(maximum_paid_calls=1)
    first_command = fixture.command
    second_command = replace(
        fixture.command,
        attempt_idempotency_key="concurrent-second-attempt",
    )
    first_uow = fixture.store.unit_of_work_factory()(project_id=fixture.command.project_id)
    second_uow = fixture.store.unit_of_work_factory()(project_id=fixture.command.project_id)

    with first_uow, second_uow:
        first_job = first_uow.calls.get_job(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        second_job = second_uow.calls.get_job(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        assert first_job is not None and second_job is not None
        first_uow.calls.reserve_attempt(
            draft=attempt_draft(
                first_command,
                identity=request_identity(first_command, policy=fixture.policy),
                attempt_id=uuid4(),
                job=first_job,
            ),
            expected_job_version=first_command.expected_job_version,
            expected_budget_version=first_job.budget_version,
            reserved_at=NOW,
        )
        second_uow.calls.reserve_attempt(
            draft=attempt_draft(
                second_command,
                identity=request_identity(second_command, policy=fixture.policy),
                attempt_id=uuid4(),
                job=second_job,
            ),
            expected_job_version=second_command.expected_job_version,
            expected_budget_version=second_job.budget_version,
            reserved_at=NOW,
        )
        first_uow.commit()
        with pytest.raises(ModelCallVersionConflict, match="concurrently"):
            second_uow.commit()

    attempts = fixture.store.attempts(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )
    assert len(attempts) == 1
    job = fixture.store.job(
        project_id=fixture.command.project_id,
        job_id=fixture.command.job_id,
    )
    assert job is not None
    assert (job.paid_calls, job.reserved_calls) == (0, 1)


def test_terminal_event_is_append_only() -> None:
    fixture = application_fixture()
    receipt = fixture.application.execute(fixture.command, policy=fixture.policy)

    with fixture.store.unit_of_work_factory()(project_id=fixture.command.project_id) as uow:
        job = uow.calls.get_job(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        assert job is not None
        with pytest.raises(ModelCallVersionConflict, match="terminal event"):
            uow.calls.append_terminal_event(
                event=replace(receipt.terminal_event, id=uuid4()),
                expected_budget_version=job.budget_version,
            )


def test_prompt_release_lookup_is_scoped_by_binding_and_release() -> None:
    fixture = application_fixture()
    original = fixture.command.prompt_binding_id
    assert original is not None
    alternate = uuid4()
    with fixture.store.unit_of_work_factory()(project_id=fixture.command.project_id) as uow:
        original_prompt = uow.calls.get_prompt_release(
            project_id=fixture.command.project_id,
            binding_id=original,
            release_id=fixture.command.prompt_release_id,
        )
    assert original_prompt is not None
    fixture.store.seed_prompt_release(
        replace(original_prompt, binding_id=alternate, state_id=uuid4())
    )

    with fixture.store.unit_of_work_factory()(project_id=fixture.command.project_id) as uow:
        first = uow.calls.get_prompt_release(
            project_id=fixture.command.project_id,
            binding_id=original,
            release_id=fixture.command.prompt_release_id,
        )
        second = uow.calls.get_prompt_release(
            project_id=fixture.command.project_id,
            binding_id=alternate,
            release_id=fixture.command.prompt_release_id,
        )

    assert first is not None and first.binding_id == original
    assert second is not None and second.binding_id == alternate


def test_uow_scope_and_failed_commit_do_not_leak_partial_state() -> None:
    fixture = application_fixture()
    fixture.store.fail_next_commit()
    identity = request_identity(fixture.command, policy=fixture.policy)

    with fixture.store.unit_of_work_factory()(project_id=fixture.command.project_id) as uow:
        job = uow.calls.get_job(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        assert job is not None
        uow.calls.reserve_attempt(
            draft=attempt_draft(
                fixture.command,
                identity=identity,
                attempt_id=uuid4(),
                job=job,
            ),
            expected_job_version=fixture.command.expected_job_version,
            expected_budget_version=job.budget_version,
            reserved_at=NOW,
        )
        with pytest.raises(ModelCallPersistenceError, match="simulated"):
            uow.commit()

    assert (
        fixture.store.attempts(
            project_id=fixture.command.project_id,
            job_id=fixture.command.job_id,
        )
        == ()
    )
