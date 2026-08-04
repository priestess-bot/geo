"""Production Internal API adapter for project-scoped Synthetic Lab state."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from geo_core.access.models import AccessPrincipal
from geo_core.synthetic_lab.authorization import (
    AuthorizationBinding,
    AuthorizationState,
    create_authorization_record,
)
from geo_core.synthetic_lab.collection_application import StyleCollectionExecutionApplication
from geo_core.synthetic_lab.collection_execution_contracts import (
    StyleCollectionExecutionError,
    StyleCollectionTask,
    TmpfsCapturePolicy,
)
from geo_core.synthetic_lab.channel_styles import (
    ChannelStyleCalibration,
    ChannelStyleProvenance,
    ChannelStyleVersion,
)
from geo_core.synthetic_lab.domain import StyleAccessMode, StyleSourceStatus
from geo_core.synthetic_lab.ports import (
    SyntheticLabIdempotencyConflict,
    SyntheticLabNotFound,
    SyntheticLabPersistenceError,
    SyntheticLabVersionConflict,
)
from geo_core.synthetic_lab.postgres_api_reads import PostgresSyntheticApiReads
from geo_core.synthetic_lab.postgres_api_resources import (
    PostgresSyntheticResourceApiMixin,
    build_manual_import_service,
)
from geo_core.synthetic_lab.postgres_api_support import (
    domain_principal,
    int_value,
    payload,
    project,
    stable_id,
    uuid_value,
)
from geo_core.synthetic_lab.postgres_execution_admission import (
    PostgresSyntheticExecutionAdmission,
)
from geo_core.synthetic_lab.postgres_uow import synthetic_lab_uow_factory
from geo_core.synthetic_lab.resource_application import SyntheticResourceApplication
from geo_core.synthetic_lab.review_application import ReviewApplication
from geo_core.synthetic_lab.style_application import StyleApplication
from geo_core.synthetic_lab.style_browser import (
    StyleAdapterRegistry,
    load_style_adapter_registry,
)


class PostgresSyntheticLabApi(PostgresSyntheticResourceApiMixin):
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

        def connect() -> Any:
            return psycopg.connect(database_url, row_factory=dict_row)

        self._connect = connect
        self._uow_factory = synthetic_lab_uow_factory(database_url)
        self._reads = PostgresSyntheticApiReads(connect)
        self._style = StyleApplication(self._uow_factory)
        self._review = ReviewApplication(self._uow_factory)
        self._resources = SyntheticResourceApplication(self._uow_factory)
        self._registry = _load_registry()
        self._manual_imports = build_manual_import_service(connect)
        self._execution_admission = PostgresSyntheticExecutionAdmission(
            database_url,
            connection_factory=connect,
            uow_factory=self._uow_factory,
            reads=self._reads,
            manual_imports=self._manual_imports,
        )

    def direct_generation_options(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.direct_generation_options(project_id)

    def list_channel_styles(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.channel_styles(
            project_id,
            limit=int_value(values["limit"]),
            offset=int_value(values["offset"]),
            channel=str(values["channel"]) if values.get("channel") else None,
            include_history=bool(values.get("include_history", False)),
        )

    def create_channel_style(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        channel = str(values["channel"])
        expected = int(request["expected_current_version"])
        current = self._reads.current_channel_style(project_id, channel)
        current_version = current.version_number if current is not None else 0
        if current_version != expected:
            raise SyntheticLabVersionConflict("Channel Style changed after it was loaded")
        version_number = expected + 1
        style_id = current.style_id if current is not None else stable_id(
            project_id, channel, "channel-style-identity"
        )
        style = ChannelStyleVersion(
            id=stable_id(project_id, values["idempotency_key"], "channel-style-version"),
            project_id=project_id,
            style_id=style_id,
            version_number=version_number,
            previous_version_id=current.id if current is not None else None,
            channel=channel,
            directive=str(request["directive"]).strip(),
            provenance=(
                ChannelStyleProvenance.MANUAL_INITIAL
                if current is None
                else ChannelStyleProvenance.MANUAL_EDIT
            ),
            calibration_status=ChannelStyleCalibration.PENDING_SAMPLE_CALIBRATION,
        )
        return self._resources.create_channel_style(
            principal=actor,
            style=style,
            expected_version=expected,
            idempotency_key=str(values["idempotency_key"]),
        )

    def list_authorizations(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.authorizations(
            project_id,
            limit=int_value(values["limit"]),
            offset=int_value(values["offset"]),
        )

    def create_authorization(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        record = create_authorization_record(
            id=stable_id(project_id, values["idempotency_key"], "authorization"),
            project_id=project_id,
            channel=request["channel"],
            adapter_release=request["adapter_release"],
            version_number=1,
            previous_version_id=None,
            state=AuthorizationState.NOT_ASSESSED,
            evidence_reference_hash=None,
            decided_by=None,
            decided_at=None,
            allowed_purposes=(),
            max_requests_per_period=None,
            period_seconds=None,
            max_concurrency=None,
            expires_at=None,
            decision_reason=None,
        )
        return self._style.create_authorization(
            principal=actor,
            record=record,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def decide_authorization(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        previous = self._reads.authorization_by_id(
            project_id, uuid_value(values["authorization_id"])
        )
        state = AuthorizationState(str(request["decision"]))
        approved = state is AuthorizationState.APPROVED
        record = create_authorization_record(
            id=stable_id(project_id, values["idempotency_key"], "authorization-decision"),
            project_id=project_id,
            channel=previous.channel,
            adapter_release=previous.adapter_release,
            version_number=previous.version_number + 1,
            previous_version_id=previous.id,
            state=state,
            evidence_reference_hash=(
                hashlib.sha256(str(request["evidence_reference"]).encode()).hexdigest()
                if approved and request["evidence_reference"] is not None
                else None
            ),
            decided_by=actor.actor_id,
            decided_at=datetime.now(UTC),
            allowed_purposes=tuple(request["allowed_purposes"]) if approved else (),
            max_requests_per_period=request["max_requests_per_period"] if approved else None,
            period_seconds=request["period_seconds"] if approved else None,
            max_concurrency=request["max_concurrency"] if approved else None,
            expires_at=request["expires_at"] if approved else None,
            decision_reason=request["decision_reason"],
        )
        return self._style.decide_authorization(
            principal=actor,
            record=record,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def revoke_authorization(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        previous = self._reads.authorization_by_id(
            project_id, uuid_value(values["authorization_id"])
        )
        record = create_authorization_record(
            id=stable_id(project_id, values["idempotency_key"], "authorization-revoke"),
            project_id=project_id,
            channel=previous.channel,
            adapter_release=previous.adapter_release,
            version_number=previous.version_number + 1,
            previous_version_id=previous.id,
            state=AuthorizationState.REVOKED,
            evidence_reference_hash=previous.evidence_reference_hash,
            decided_by=actor.actor_id,
            decided_at=datetime.now(UTC),
            allowed_purposes=previous.allowed_purposes,
            max_requests_per_period=previous.max_requests_per_period,
            period_seconds=previous.period_seconds,
            max_concurrency=previous.max_concurrency,
            expires_at=previous.expires_at,
            decision_reason=request["decision_reason"],
        )
        return self._style.revoke_authorization(
            principal=actor,
            record=record,
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def reassess_authorization(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        previous = self._reads.authorization_by_id(
            project_id, uuid_value(values["authorization_id"])
        )
        return self._style.reassess_authorization(
            principal=actor,
            previous=previous,
            reassessment_id=stable_id(
                project_id, values["idempotency_key"], "authorization-reassessment"
            ),
            opened_at=request["opened_at"],
            reassessment_reason=request["reassessment_reason"],
            expected_version=int(request["expected_version"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def admit_style_collection(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        actor = domain_principal(principal, project_id)
        request = payload(values)
        idempotency_key = values["idempotency_key"]
        job_id = stable_id(project_id, idempotency_key, "style-collection-job")
        source = self._reads.style_source(project_id, request["style_source_revision_id"])
        existing = self._reads.style_collection_task_or_none(project_id, job_id)
        if existing is not None:
            requested_secret = request["login_secret_reference_id"]
            frozen_secret = existing.login_secret.reference_id if existing.login_secret else None
            if (
                existing.style_source_revision_id != source.id
                or existing.adapter_release != request["adapter_release"]
                or frozen_secret != requested_secret
            ):
                raise SyntheticLabIdempotencyConflict(
                    "Style Collection Idempotency-Key was reused for another request"
                )
            return _admission(
                "accepted", "live_collection_queued", True,
                job=self._reads.job(project_id, job_id),
            )
        if source.access_mode is StyleAccessMode.MANUAL_IMPORT:
            return _admission("b_track", "manual_import_has_no_live_job", False)
        if source.status is not StyleSourceStatus.ACTIVE or source.source_url is None:
            return _admission("rejected", "style_source_not_active", False)
        if self._registry is None:
            return _admission("rejected", "adapter_registry_unavailable", False)
        adapter_release = str(request["adapter_release"])
        adapter = self._registry.adapters.get((source.channel, adapter_release))
        if adapter is None:
            return _admission("rejected", "adapter_release_not_frozen", False)
        with self._uow_factory(project_id=project_id) as uow:
            current = uow.authorizations.current(
                project_id=project_id,
                channel=source.channel,
                adapter_release=adapter_release,
            )
        if current is None or current.record.state is not AuthorizationState.APPROVED:
            return _admission("rejected", "authorization_not_approved", False)
        authorization = current.record
        if "style_collection" not in authorization.allowed_purposes:
            return _admission("rejected", "authorization_purpose_denied", False)
        try:
            login_secret = self._login_secret(project_id, source, request)
        except (StyleCollectionExecutionError, SyntheticLabNotFound):
            return _admission("rejected", "login_secret_unavailable", False)
        binding = AuthorizationBinding(
            authorization_id=authorization.id,
            project_id=project_id,
            channel=source.channel,
            adapter_release=adapter_release,
            version_number=authorization.version_number,
            authorization_hash=authorization.record_hash,
            purpose="style_collection",
            expires_at=authorization.expires_at,  # type: ignore[arg-type]
        )
        source_host = (urlsplit(source.source_url).hostname or "").lower()
        task = StyleCollectionTask(
            project_id=project_id,
            job_id=job_id,
            collection_run_id=stable_id(project_id, idempotency_key, "style-collection-run"),
            style_source_revision_id=source.id,
            source_revision_number=source.revision_number,
            channel=source.channel,
            locale=source.locale,
            access_mode=source.access_mode,
            source_url=source.source_url,
            source_locator_hash=source.source_locator_hash,
            adapter_release=adapter_release,
            authorization=binding,
            login_secret=login_secret,
            allowed_redirect_hosts=tuple(sorted({source_host, *adapter.allowed_resource_hosts})),
            robots_user_agent=os.getenv(
                "GEO_STYLE_ROBOTS_USER_AGENT", "GeoStyleResearchBot/1.0"
            ).strip(),
            raw_artifact_id=stable_id(project_id, idempotency_key, "style-collection-raw"),
            derived_artifact_id=stable_id(
                project_id, idempotency_key, "style-collection-derived"
            ),
            tmpfs=TmpfsCapturePolicy(
                mount_path="/run/geo-style-capture", maximum_bytes=536_870_912
            ),
        )
        try:
            receipt = StyleCollectionExecutionApplication(
                self._uow_factory, registry=self._registry
            ).enqueue(
                principal=actor,
                task=task,
                outbox_id=stable_id(project_id, idempotency_key, "style-collection-outbox"),
                idempotency_key=str(idempotency_key),
            )
        except StyleCollectionExecutionError:
            return _admission("rejected", "live_admission_gate_failed", False)
        return _admission("accepted", "live_collection_queued", True, job=receipt)

    def get_job(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.job_view(project_id, uuid_value(values["job_id"]))

    def list_jobs(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.jobs(
            project_id,
            limit=int_value(values["limit"]),
            offset=int_value(values["offset"]),
            kind=str(values["kind"]) if values.get("kind") is not None else None,
            status=str(values["status"]) if values.get("status") is not None else None,
        )

    def get_job_result(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        domain_principal(principal, project_id)
        return self._reads.review_result(project_id, uuid_value(values["job_id"]))

    def cancel_job(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        return self._review.cancel_job(
            principal=domain_principal(principal, project_id),
            job_id=uuid_value(values["job_id"]),
            expected_version=int(request["expected_version"]),
            cancelled_at=datetime.now(UTC),
            idempotency_key=str(values["idempotency_key"]),
        )

    def enqueue_profile_build(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        return self._execution_admission.enqueue_profile_build(
            principal=domain_principal(principal, project_id),
            profile_version_id=request["profile_version_id"],
            fact_snapshot_id=request["fact_snapshot_id"],
            approved_sample_ids=tuple(request["approved_sample_ids"]),
            runtime_selection_id=request["runtime_selection_id"],
            recovery_of_attempt_id=request["recovery_of_attempt_id"],
            dify_reconciliation_token=request["dify_reconciliation_token"],
            idempotency_key=str(values["idempotency_key"]),
        )

    def enqueue_review_case(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        return self._execution_admission.enqueue_review_case(
            principal=domain_principal(principal, project_id),
            suite_version_id=request["suite_version_id"],
            case_id=request["case_id"],
            runtime_selection_id=request["runtime_selection_id"],
            style_pass_threshold=float(request["style_pass_threshold"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def enqueue_direct_generation(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        return self._execution_admission.enqueue_direct_generation(
            principal=domain_principal(principal, project_id),
            channel=str(request["channel"]),
            subject_entity_id=request["subject_entity_id"],
            generation_goal=str(request["generation_goal"]),
            runtime_selection_id=request["runtime_selection_id"],
            channel_style_version_id=request["channel_style_version_id"],
            channel_style_hash=str(request["channel_style_hash"]),
            knowledge_snapshot_hash=str(request["knowledge_snapshot_hash"]),
            style_pass_threshold=float(request["style_pass_threshold"]),
            include_competitor_context=bool(request["include_competitor_context"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def enqueue_corpus_finalize(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        return self._execution_admission.enqueue_corpus_finalize(
            principal=domain_principal(principal, project_id),
            role=request["role"],
            review_job_ids=tuple(request["review_job_ids"]),
            source_corpus_job_id=request["source_corpus_job_id"],
            idempotency_key=str(values["idempotency_key"]),
        )

    def enqueue_offline_experiment(self, principal: AccessPrincipal, **values: object):
        project_id = project(values)
        request = payload(values)
        return self._execution_admission.enqueue_offline_experiment(
            principal=domain_principal(principal, project_id),
            question_set_id=request["question_set_id"],
            current_corpus_job_id=request["current_corpus_job_id"],
            candidate_corpus_job_id=request["candidate_corpus_job_id"],
            runtime_selection_id=request["runtime_selection_id"],
            minimum_valid_pair_ratio=float(request["minimum_valid_pair_ratio"]),
            idempotency_key=str(values["idempotency_key"]),
        )

    def _login_secret(self, project_id: UUID, source: Any, request: dict[str, Any]):
        reference_id = request["login_secret_reference_id"]
        if source.access_mode is StyleAccessMode.PUBLIC:
            if reference_id is not None:
                raise StyleCollectionExecutionError("public Style Source cannot use a Secret")
            return None
        if reference_id is None:
            raise StyleCollectionExecutionError("authenticated Style Source requires a Secret")
        return self._reads.current_secret_handle(
            project_id,
            reference_id=reference_id,
            purpose=f"style_collection_login.{source.channel}",
        )

    def enqueue_job(self, *args: object, **kwargs: object):
        raise SyntheticLabPersistenceError("legacy hash-driven enqueue is disabled")

    def finalize_job(self, *args: object, **kwargs: object):
        raise SyntheticLabPersistenceError("manual Job finalization is disabled")


def _load_registry() -> StyleAdapterRegistry | None:
    path = os.getenv("GEO_STYLE_ADAPTER_REGISTRY_FILE", "").strip()
    expected = os.getenv("GEO_STYLE_ADAPTER_REGISTRY_SHA256", "").strip()
    if not path or not expected:
        return None
    source = Path(path)
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise RuntimeError("Style adapter registry digest changed")
    return load_style_adapter_registry(source)


def _admission(disposition: str, reason: str, may_issue: bool, *, job: object = None):
    return {
        "disposition": disposition,
        "reason_code": reason,
        "may_issue_network_request": may_issue,
        "job": job,
    }


__all__ = ["PostgresSyntheticLabApi"]
