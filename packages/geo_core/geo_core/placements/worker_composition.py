"""Unified handler registry for evidence, generation and publication verification."""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping, Protocol
from uuid import UUID

from geo_core.jobs.postgres import (
    JobCancellationRequested,
    LeaseHeartbeat,
    LostJobLease,
    PostgresDurableJobStore,
    WorkerLease,
)
from geo_core.placements.artifact_worker import (
    ArtifactObjectStore,
    PlacementArtifactRepository,
)
from geo_core.model_gateway import (
    ModelCallBudget,
    ModelGateway,
    ModelGatewayRequest,
    ModelPolicy,
)
from geo_core.model_gateway.contracts import (
    ModelCallBudgetExceeded,
    ModelGatewayError,
    ProviderPolicyViolation,
    RetryableModelGatewayError,
)
from geo_core.placements.domain import (
    PlacementRuleViolation,
    canonical_hash,
    canonical_json_bytes,
)
from geo_core.placements.errors import PlacementContractMigrationRequired
from geo_core.placements.generation_worker import parse_generated_placement, validate_output_schema
from geo_core.placements.publication_verification_worker import (
    PublicationVerificationContractError,
)
from geo_core.placements.runtime_prompts import generation_system_prompt
from geo_core.placements.url_verifier import (
    PermanentVerificationError,
    PublicUrlVerifier,
    RetryableVerificationError,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository


class JobHandler(Protocol):
    def handle(self, lease: WorkerLease) -> Mapping[str, object]: ...


class EvidencePackHandler:
    def __init__(self, repository: PlacementWorkerRepository) -> None:
        self._repository = repository

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        status = self._repository.build_evidence_pack(lease)
        return {"status": status, "job_id": str(lease.job_id)}


class ArtifactFinalizeHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: PlacementArtifactRepository,
        object_store: ArtifactObjectStore,
    ) -> None:
        self._store = store
        self._repository = repository
        self._object_store = object_store

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        artifact = self._repository.load(lease)
        try:
            stored = self._object_store.put_object(
                key=artifact.storage_key,
                content=artifact.content,
                content_type="application/json",
                expected_hash=artifact.content_hash,
            )
        except Exception as exc:
            status = self._store.fail(
                lease,
                error_code=type(exc).__name__,
                details={"message": str(exc)},
                retry_delay=timedelta(seconds=30),
            )
            self._repository.mark_failure(
                project_id=lease.project_id,
                job_id=lease.job_id,
                error=str(exc),
                terminal=status in {"failed", "dead_lettered"},
            )
            return {"status": status, "job_id": str(lease.job_id)}
        self._repository.finalize(lease, artifact, stored)
        return {
            "status": "finalized",
            "job_id": str(lease.job_id),
            "resource_id": str(artifact.resource_id),
        }


class GenerationHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: PlacementWorkerRepository,
        gateway: ModelGateway,
        lease_for: timedelta,
    ) -> None:
        self._store = store
        self._repository = repository
        self._gateway = gateway
        self._lease_for = lease_for

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            claim = self._repository.load_generation(lease)
        except PlacementContractMigrationRequired as exc:
            return self._fail(
                lease,
                exc,
                retry=False,
                classification="migration_contract",
                error_code=exc.error_code,
                operator_action=exc.operator_action,
            )
        except PlacementRuleViolation as exc:
            return self._fail(lease, exc, retry=False, classification="contract")
        serialized_schema = canonical_json_bytes(claim.output_schema).decode("utf-8")
        request = ModelGatewayRequest(
            messages=(
                {
                    "role": "system",
                    "content": generation_system_prompt(serialized_schema),
                },
                {"role": "system", "content": claim.system_prompt},
                {"role": "user", "content": claim.rendered_prompt},
            ),
            configured_model=claim.configured_model,
            prompt_bundle_hash=claim.prompt_bundle_hash,
            project_id=claim.project_id,
            purpose="geo-placement-generation",
        )
        request_hash = canonical_hash(
            {
                "messages": request.messages,
                "configured_model": request.configured_model,
                "prompt_bundle_hash": request.prompt_bundle_hash,
                "purpose": request.purpose,
                "temperature": request.temperature,
                "max_output_tokens": request.max_output_tokens,
            }
        )
        provider = str(getattr(self._gateway, "provider", "unknown"))
        try:
            reservation = self._repository.reserve_model_call(
                lease, claim, provider=provider, request_hash=request_hash
            )
        except ModelCallBudgetExceeded as exc:
            return self._fail(lease, exc, retry=False, classification="budget")
        try:
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=30)),
            ) as heartbeat:
                result = self._gateway.generate(
                    request,
                    policy=ModelPolicy(),
                    budget=ModelCallBudget(1),
                )
                heartbeat.raise_if_stopped()
        except (JobCancellationRequested, LostJobLease):
            raise
        except Exception as exc:
            classification = _model_error_classification(exc)
            self._repository.record_model_call_failure(
                lease,
                claim,
                reservation,
                classification=classification,
                error_code=type(exc).__name__,
            )
            return self._fail(
                lease,
                exc,
                retry=isinstance(exc, RetryableModelGatewayError),
                classification=classification,
            )
        self._repository.record_model_call_success(lease, claim, reservation, result)
        try:
            validate_output_schema(result.output, claim.output_schema)
            placement = parse_generated_placement(result.output, claim=claim)
            version = self._repository.finalize_generation(lease, claim, placement, result)
            return {
                "status": "succeeded",
                "job_id": str(lease.job_id),
                "package_version_id": str(version.id),
                "response_hash": result.response_hash,
            }
        except PlacementRuleViolation as exc:
            return self._fail(lease, exc, retry=False, classification="contract")

    def _fail(
        self,
        lease: WorkerLease,
        error: Exception,
        *,
        retry: bool,
        classification: str,
        error_code: str | None = None,
        operator_action: str | None = None,
    ) -> Mapping[str, object]:
        details = {"message": str(error), "classification": classification}
        if operator_action is not None:
            details["operator_action"] = operator_action
        status = self._store.fail(
            lease,
            error_code=error_code or type(error).__name__,
            details=details,
            retry_delay=timedelta(seconds=30) if retry else None,
        )
        return {"status": status, "job_id": str(lease.job_id)}


class PublicationVerificationHandler:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        repository: PlacementWorkerRepository,
        verifier: PublicUrlVerifier,
        lease_for: timedelta,
    ) -> None:
        self._store = store
        self._repository = repository
        self._verifier = verifier
        self._lease_for = lease_for

    def reconcile_terminal(self, *, job_id: UUID, project_id: UUID) -> None:
        self._repository.reconcile_terminal_verification(job_id=job_id, project_id=project_id)

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        try:
            snapshot = self._repository.begin_verification(lease)
        except PublicationVerificationContractError as exc:
            status = self._repository.persist_verification_error(lease, exc.snapshot, error=exc)
            return {
                "status": status,
                "job_id": str(lease.job_id),
                "error_code": exc.failure.code,
            }
        try:
            with LeaseHeartbeat(
                self._store,
                lease,
                lease_for=self._lease_for,
                interval=min(self._lease_for / 3, timedelta(seconds=20)),
            ) as heartbeat:
                verification = self._verifier.verify(
                    snapshot.submitted_url,
                    expected_text_fragments=snapshot.expected_text_fragments,
                    required_disclosures=snapshot.required_disclosures,
                    expected_links=snapshot.expected_links,
                    allowed_hosts=snapshot.allowed_hosts,
                )
                heartbeat.raise_if_stopped()
        except (RetryableVerificationError, PermanentVerificationError) as exc:
            status = self._repository.persist_verification_error(lease, snapshot, error=exc)
            return {"status": status, "job_id": str(lease.job_id)}
        verified = self._repository.persist_completed_verification(
            lease, snapshot, result=verification
        )
        return {
            "status": "verified" if verified else "verification_failed",
            "job_id": str(lease.job_id),
        }


class MeasurementWindowHandler:
    def __init__(self, repository: PlacementWorkerRepository) -> None:
        self._repository = repository

    def handle(self, lease: WorkerLease) -> Mapping[str, object]:
        details = self._repository.open_measurement_window(lease)
        return {"job_id": str(lease.job_id), **details}


def _model_error_classification(error: Exception) -> str:
    if isinstance(error, RetryableModelGatewayError):
        return "retryable"
    if isinstance(error, ProviderPolicyViolation):
        return "policy"
    if isinstance(error, ModelCallBudgetExceeded):
        return "budget"
    if isinstance(error, ModelGatewayError):
        return "permanent"
    return "unknown"


class PlacementWorkerDispatcher:
    def __init__(
        self,
        *,
        store: PostgresDurableJobStore,
        handlers: Mapping[str, JobHandler],
        worker_id: str,
        lease_for: timedelta = timedelta(minutes=2),
    ) -> None:
        self._store = store
        self._handlers = dict(handlers)
        self._worker_id = worker_id
        self._lease_for = lease_for

    def process(self, *, job_id: UUID, project_id: UUID) -> Mapping[str, object]:
        claim = self._store.claim(
            job_id=job_id,
            project_id=project_id,
            expected_kind="",
            worker_id=self._worker_id,
            lease_for=self._lease_for,
        )
        if claim.lease is None:
            handler = self._handlers.get(claim.kind or "")
            reconcile = getattr(handler, "reconcile_terminal", None)
            if claim.disposition in {"cancelled", "dead_lettered", "terminal"} and callable(
                reconcile
            ):
                reconcile(job_id=job_id, project_id=project_id)
            return {"status": claim.disposition, "job_id": str(job_id)}
        lease = claim.lease
        handler = self._handlers.get(lease.kind)
        if handler is None:
            status = self._store.fail(
                lease,
                error_code="unsupported_job_kind",
                details={"kind": lease.kind},
                retry_delay=None,
            )
            return {"status": status, "job_id": str(job_id)}
        try:
            return handler.handle(lease)
        except JobCancellationRequested:
            self._store.cancel(lease)
            reconcile = getattr(handler, "reconcile_terminal", None)
            if callable(reconcile):
                reconcile(job_id=job_id, project_id=project_id)
            return {"status": "cancelled", "job_id": str(job_id)}
        except LostJobLease:
            return {"status": "fenced", "job_id": str(job_id)}
        except Exception as exc:
            status = self._store.fail(
                lease,
                error_code=type(exc).__name__,
                details={"message": str(exc)},
                retry_delay=timedelta(seconds=30),
            )
            if status in {"failed", "dead_lettered"}:
                reconcile = getattr(handler, "reconcile_terminal", None)
                if callable(reconcile):
                    reconcile(job_id=job_id, project_id=project_id)
            return {"status": status, "job_id": str(job_id)}
