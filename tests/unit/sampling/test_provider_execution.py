from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from geo_core.jobs import LeaseConflict
from geo_core.model_gateway import (
    ModelGatewayError,
    ModelGatewayErrorCode,
    RetryableModelGatewayError,
    StructuredOutputValidationError,
)
from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryRequest,
    RecoveredProviderArtifact,
    RecoveredProviderArtifactBundle,
)
from geo_core.model_gateway.ports import canonical_json_hash
from geo_core.model_gateway.releases import ModelRoute
from geo_core.sampling import SamplingConflict, SamplingRuleViolation, SamplingTaskStatus
from geo_core.sampling.provider_execution import (
    ProviderSamplingAdmissionError,
    ProviderSamplingExecutionService,
    ProviderSamplingFailure,
    ProviderSamplingFailureClass,
    ProviderSamplingUnknownOutcome,
    _SamplingContext,
    _build_model_command,
)

from tests.unit.model_gateway.model_call_application_test_support import RecordingExactGateway
from tests.unit.sampling.factories import NOW
from tests.unit.sampling.provider_execution_test_support import (
    QUESTION_TEXT,
    ProviderIdentity,
    execution_fixture,
    model_result,
    persisted_state_text,
)


def test_success_joins_exact_model_lineage_to_fenced_observation() -> None:
    fixture = execution_fixture()

    completed = fixture.service.execute(fixture.command, policy=fixture.policy)

    assert completed.sampling.task.status is SamplingTaskStatus.SUCCEEDED
    assert completed.sampling.task.identity == fixture.task.identity
    assert completed.sampling.observation.source_stratum_hash == fixture.task.identity.source_stratum_hash
    evidence = completed.sampling.observation.evidence
    assert evidence.derived_summary == (
        "Governed provider evidence is available to approved viewers."
    )
    assert evidence.evidence_locator.endswith("#/answer")
    assert evidence.raw_artifact.manifest_reference.startswith("s3://")
    assert evidence.derived_artifact.manifest_reference.startswith("s3://")
    assert completed.sampling.observation.evidence.result_parameters_hash == (
        completed.lineage.result_parameters_hash
    )
    assert completed.sampling.attempt.provider_response_id == "openai-response-fixture"
    assert completed.sampling.attempt.actual_location is not None
    assert completed.sampling.observation.actual_location == (
        completed.sampling.attempt.actual_location
    )
    assert completed.sampling.attempt.actual_location.location_evidence_hash == (
        completed.lineage.location_evidence_hash
    )
    assert completed.lineage.sampling_attempt_id == fixture.attempt.id
    assert completed.lineage.model_call_attempt_id == completed.model_call.attempt.spec.id
    assert completed.lineage.gateway_call_log_id == completed.model_call.result.call_log_id
    assert completed.lineage.citation_count == 1
    assert completed.lineage.search_event_count == 1
    job = fixture.model_store.job(
        project_id=fixture.suite.project_id,
        job_id=fixture.attempt.id,
    )
    assert job is not None and job.paid_calls == 1
    assert QUESTION_TEXT not in persisted_state_text(fixture)


def test_replayed_success_recovers_artifact_without_second_provider_call() -> None:
    fixture = execution_fixture()
    model_command = _build_model_command(
        fixture.command,
        _SamplingContext(fixture.suite, fixture.run, fixture.task, fixture.attempt),
    )
    first = fixture.model_application.execute(model_command, policy=fixture.policy)
    assert first.result is not None
    recovery = _Recovery(first.result)
    service = ProviderSamplingExecutionService(
        sampling_uow_factory=fixture.sampling_store.unit_of_work_factory(),
        model_calls=fixture.model_application,
        result_recovery=recovery,
        clock=lambda: fixture.run.admitted_not_before + timedelta(seconds=3),
    )

    completed = service.execute(fixture.command, policy=fixture.policy)

    assert completed.model_call.replayed is True
    assert completed.model_call.result is not None
    assert completed.model_call.result.output == first.result.output
    assert completed.sampling.task.status is SamplingTaskStatus.SUCCEEDED
    assert recovery.requests[0].source_model_job_id == fixture.attempt.id
    assert recovery.requests[0].recovery_job_id == fixture.attempt.id
    assert isinstance(fixture.gateway, RecordingExactGateway)
    assert fixture.gateway.calls == 1


class _Recovery:
    def __init__(self, result) -> None:
        self._result = result
        self.requests: list[ProviderArtifactRecoveryRequest] = []

    def recover_derived(
        self, request: ProviderArtifactRecoveryRequest
    ) -> RecoveredProviderArtifact:
        self.requests.append(request)
        result = self._result
        assert result.raw_artifact_reference is not None
        assert result.raw_artifact_manifest_hash is not None
        assert result.raw_artifact_content_hash is not None
        assert result.raw_artifact_byte_size is not None
        assert result.derived_artifact_reference is not None
        assert result.derived_artifact_manifest_hash is not None
        assert result.derived_artifact_content_hash is not None
        assert result.derived_artifact_byte_size is not None
        assert result.raw_artifact_policy_hash is not None
        assert result.raw_artifact_storage_decision is not None
        assert result.raw_artifact_cache_decision is not None
        assert result.raw_artifact_display_decision is not None
        assert result.raw_artifact_redistribution_decision is not None
        output_hash = canonical_json_hash(result.output)
        assert request.expected_output_hash == output_hash
        return RecoveredProviderArtifact(
            model_call_attempt_id=request.model_call_attempt_id,
            artifact_id=uuid4(),
            manifest_hash=result.derived_artifact_manifest_hash,
            content_hash=result.derived_artifact_content_hash,
            output_hash=output_hash,
            output=result.output,
            recovery_receipt_id=uuid4(),
            recovery_receipt_hash="a" * 64,
            recovered_at=NOW,
            bundle_lineage=RecoveredProviderArtifactBundle(
                raw_manifest_reference=result.raw_artifact_reference,
                raw_manifest_hash=result.raw_artifact_manifest_hash,
                raw_content_hash=result.raw_artifact_content_hash,
                raw_byte_size=result.raw_artifact_byte_size,
                derived_manifest_reference=result.derived_artifact_reference,
                derived_manifest_hash=result.derived_artifact_manifest_hash,
                derived_content_hash=result.derived_artifact_content_hash,
                derived_byte_size=result.derived_artifact_byte_size,
                data_policy_hash=result.raw_artifact_policy_hash,
                storage_decision=result.raw_artifact_storage_decision,
                cache_decision=result.raw_artifact_cache_decision,
                display_decision=result.raw_artifact_display_decision,
                redistribution_decision=result.raw_artifact_redistribution_decision,
                retention_days=result.raw_artifact_retention_days,
            ),
        )


def test_observation_never_persists_raw_answer_pii_or_secret_prefix() -> None:
    identity = ProviderIdentity()
    sensitive_answer = (
        "Contact Jane Citizen at jane@example.com or +61 412 345 678; "
        "api_key=provider-secret-value."
    )
    fixture = execution_fixture(
        identity=identity,
        gateway_factory=lambda route: RecordingExactGateway(
            [model_result(identity, route, answer=sensitive_answer)]
        ),
    )

    completed = fixture.service.execute(fixture.command, policy=fixture.policy)

    evidence = completed.sampling.observation.evidence
    assert evidence.derived_summary == (
        "Governed provider evidence is available to approved viewers."
    )
    persisted = persisted_state_text(fixture)
    for prohibited in (
        "Jane Citizen",
        "jane@example.com",
        "+61 412 345 678",
        "provider-secret-value",
    ):
        assert prohibited not in persisted


def test_runtime_question_must_match_before_io() -> None:
    fixture = execution_fixture()

    with pytest.raises(ProviderSamplingAdmissionError, match="question text"):
        fixture.service.execute(
            replace(fixture.command, question_text="a different question"),
            policy=fixture.policy,
        )

    assert isinstance(fixture.gateway, RecordingExactGateway)
    assert fixture.gateway.calls == 0
    assert fixture.model_store.attempts(
        project_id=fixture.suite.project_id,
        job_id=fixture.attempt.id,
    ) == ()


def test_exact_model_release_hash_is_checked_before_provider_io() -> None:
    fixture = execution_fixture()
    wrong_route = ModelRoute(
        provider=fixture.route.provider,
        adapter_release_id=fixture.route.adapter_release_id,
        adapter_release_hash=fixture.route.adapter_release_hash,
        model_release_id=fixture.route.model_release_id,
        model_release_hash="f" * 64,
    )

    with pytest.raises(ProviderSamplingFailure) as captured:
        fixture.service.execute(
            replace(fixture.command, route=wrong_route),
            policy=fixture.policy,
        )

    assert captured.value.classification is ProviderSamplingFailureClass.CONFIGURATION
    assert captured.value.automatic_retry_allowed is False
    assert isinstance(fixture.gateway, RecordingExactGateway)
    assert fixture.gateway.calls == 0


@pytest.mark.parametrize(
    ("error", "classification", "retryable"),
    (
        (
            StructuredOutputValidationError("bad schema", provider="openai"),
            ProviderSamplingFailureClass.INVALID_SCHEMA,
            True,
        ),
        (
            ModelGatewayError(
                "refused",
                code=ModelGatewayErrorCode.CONTENT_REFUSAL,
                provider="openai",
                status_code=400,
            ),
            ProviderSamplingFailureClass.REFUSAL,
            False,
        ),
        (
            RetryableModelGatewayError(
                "limited",
                code=ModelGatewayErrorCode.RATE_LIMIT,
                provider="openai",
                status_code=429,
            ),
            ProviderSamplingFailureClass.RATE_LIMIT,
            True,
        ),
        (
            ModelGatewayError(
                "bad credential",
                code=ModelGatewayErrorCode.AUTH,
                provider="openai",
                status_code=401,
            ),
            ProviderSamplingFailureClass.AUTHENTICATION,
            False,
        ),
    ),
)
def test_known_failures_are_classified_and_only_retryable_failures_allow_auto_retry(
    error: ModelGatewayError,
    classification: ProviderSamplingFailureClass,
    retryable: bool,
) -> None:
    fixture = execution_fixture(
        gateway_factory=lambda _: RecordingExactGateway([error])
    )

    with pytest.raises(ProviderSamplingFailure) as captured:
        fixture.service.execute(fixture.command, policy=fixture.policy)

    failure = captured.value
    assert failure.classification is classification
    assert failure.retryable is retryable
    assert failure.automatic_retry_allowed is retryable
    assert failure.transition.attempt.job.error_code == f"provider_sampling.{classification.value}"
    assert failure.transition.task.status is SamplingTaskStatus.RETRY_READY
    assert fixture.sampling_store.observation(
        project_id=fixture.suite.project_id,
        run_id=fixture.run.id,
        task_id=fixture.task.id,
    ) is None
    if retryable:
        retried = fixture.sampling_application.enqueue_attempt(
            project_id=fixture.suite.project_id,
            run_id=fixture.run.id,
            task_id=fixture.task.id,
            expected_task_version=failure.transition.task.version,
            attempt_id=uuid4(),
            requested_not_before=fixture.run.admitted_not_before + timedelta(minutes=1),
        )
        assert retried.attempt.ordinal == 2
        assert retried.task.identity.task_key == fixture.task.identity.task_key
        assert fixture.task.identity.task_key in fixture.run.planned_task_keys


def test_unknown_paid_outcome_keeps_attempt_running_and_blocks_new_attempt() -> None:
    error = RetryableModelGatewayError(
        "connection ended without a response",
        code=ModelGatewayErrorCode.TIMEOUT,
        provider="openai",
    )
    fixture = execution_fixture(
        gateway_factory=lambda _: RecordingExactGateway([error])
    )

    with pytest.raises(ProviderSamplingUnknownOutcome) as captured:
        fixture.service.execute(fixture.command, policy=fixture.policy)

    assert captured.value.model_call_attempt_id.int != 0
    stored_task = fixture.sampling_store.task(
        project_id=fixture.suite.project_id,
        run_id=fixture.run.id,
        task_id=fixture.task.id,
    )
    assert stored_task is not None
    assert stored_task.status is SamplingTaskStatus.RUNNING
    assert fixture.sampling_store.observation(
        project_id=fixture.suite.project_id,
        run_id=fixture.run.id,
        task_id=fixture.task.id,
    ) is None
    job = fixture.model_store.job(
        project_id=fixture.suite.project_id,
        job_id=fixture.attempt.id,
    )
    assert job is not None and job.reserved_calls == 1 and job.paid_calls == 0
    with pytest.raises(SamplingRuleViolation, match="not ready"):
        fixture.sampling_application.enqueue_attempt(
            project_id=fixture.suite.project_id,
            run_id=fixture.run.id,
            task_id=fixture.task.id,
            expected_task_version=stored_task.version,
            attempt_id=uuid4(),
            requested_not_before=fixture.run.admitted_not_before,
        )


def test_post_io_cancel_cannot_commit_an_observation() -> None:
    fixture = execution_fixture()
    assert isinstance(fixture.gateway, RecordingExactGateway)

    def cancel() -> None:
        fixture.sampling_application.request_cancel(
            project_id=fixture.suite.project_id,
            run_id=fixture.run.id,
            task_id=fixture.task.id,
            attempt_id=fixture.attempt.id,
            expected_task_version=fixture.task.version,
            expected_attempt_version=fixture.attempt.record_version,
            now=fixture.run.admitted_not_before + timedelta(seconds=2),
        )

    fixture.gateway.before_call = cancel

    with pytest.raises(SamplingConflict, match="optimistic version"):
        fixture.service.execute(fixture.command, policy=fixture.policy)

    assert fixture.gateway.calls == 1
    assert fixture.sampling_store.observation(
        project_id=fixture.suite.project_id,
        run_id=fixture.run.id,
        task_id=fixture.task.id,
    ) is None


def test_post_io_expired_lease_cannot_commit_an_observation() -> None:
    fixture = execution_fixture()
    lease_expiry = fixture.attempt.job.lease_expires_at
    assert lease_expiry is not None
    times = iter((fixture.run.admitted_not_before + timedelta(seconds=2), lease_expiry))
    service = ProviderSamplingExecutionService(
        sampling_uow_factory=fixture.sampling_store.unit_of_work_factory(),
        model_calls=fixture.model_application,
        clock=lambda: next(times),
    )

    with pytest.raises(LeaseConflict):
        service.execute(fixture.command, policy=fixture.policy)

    assert fixture.sampling_store.observation(
        project_id=fixture.suite.project_id,
        run_id=fixture.run.id,
        task_id=fixture.task.id,
    ) is None


def test_reported_model_mismatch_fails_sampling_after_audited_call() -> None:
    identity = ProviderIdentity()

    def mismatched_gateway(route: ModelRoute) -> RecordingExactGateway:
        result = replace(model_result(identity, route), provider_reported_model="other")
        return RecordingExactGateway([result])

    fixture = execution_fixture(identity=identity, gateway_factory=mismatched_gateway)

    with pytest.raises(ProviderSamplingFailure) as captured:
        fixture.service.execute(fixture.command, policy=fixture.policy)

    assert captured.value.classification is ProviderSamplingFailureClass.RESULT_CONTRACT
    assert captured.value.automatic_retry_allowed is False
    job = fixture.model_store.job(
        project_id=fixture.suite.project_id,
        job_id=fixture.attempt.id,
    )
    assert job is not None and job.paid_calls == 1
    assert fixture.sampling_store.observation(
        project_id=fixture.suite.project_id,
        run_id=fixture.run.id,
        task_id=fixture.task.id,
    ) is None
