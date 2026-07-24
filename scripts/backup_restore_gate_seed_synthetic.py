"""Synthetic artifact fixtures for authenticated restore verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid5

import psycopg

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.object_store import S3CompatibleObjectStore
from geo_core.synthetic_lab.authorization import (
    AuthorizationBinding,
    AuthorizationState,
    create_authorization_record,
)
from geo_core.synthetic_lab.artifact_keyring import SyntheticArtifactKeyring
from geo_core.synthetic_lab.artifact_keyring_postgres import (
    PostgresArtifactDekVault,
    synchronize_artifact_master_key_canaries,
)
from geo_core.synthetic_lab.collection_application import (
    StyleCollectionExecutionApplication,
)
from geo_core.synthetic_lab.collection_execution_contracts import (
    StyleCollectionTask,
    TmpfsCapturePolicy,
)
from geo_core.synthetic_lab.domain import (
    StyleAccessMode,
    StyleSource,
    StyleSourceStatus,
)
from geo_core.synthetic_lab.ports import LabPrincipal, LabRole
from geo_core.synthetic_lab.postgres import build_synthetic_lab_persistence
from geo_core.synthetic_lab.postgres_artifacts import (
    PostgresRawArtifactManifestRepository,
)
from geo_core.synthetic_lab.raw_artifact_crypto import (
    IndependentDekArtifactEncryptor,
    ProjectTierArtifactEncryptor,
)
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactAccessClass,
    ArtifactForm,
    RawArtifactInspection,
    SensitiveFinding,
)
from geo_core.synthetic_lab.raw_artifact_storage import (
    GovernedRawArtifactStorage,
    RawArtifactStores,
)
from geo_core.synthetic_lab.raw_artifact_storage_contracts import RawArtifactWriteRequest
from geo_core.synthetic_lab.style_browser import (
    StyleAdapterAdmission,
    StyleAdapterRegistry,
    StyleAdapterRelease,
)
from scripts.backup_restore_gate_seed_common import (
    IDS,
    RestoreGateSeedError,
    stable_hash,
)


def seed_synthetic_artifacts(
    *,
    database_url: str,
    raw_object_store: S3CompatibleObjectStore,
    derived_object_store: S3CompatibleObjectStore,
    keyring: SyntheticArtifactKeyring,
) -> dict[str, int]:
    if raw_object_store.bucket == derived_object_store.bucket:
        raise RestoreGateSeedError(
            "Synthetic raw and derived fixtures require separate object-store buckets"
        )

    def connect() -> Any:
        return psycopg.connect(database_url)

    synchronize_artifact_master_key_canaries(connect, keyring)
    now = datetime.now(UTC)
    _admit_public_style_collection(
        database_url=database_url,
        admitted_at=now,
    )
    store = PostgresDurableJobStore(connect)
    claim = store.claim(
        job_id=IDS.synthetic_job,
        project_id=IDS.project,
        expected_kind="style.collect",
        worker_id="restore-gate-synthetic-worker",
        lease_for=timedelta(hours=2),
    )
    if claim.disposition != "claimed" or claim.lease is None:
        raise RestoreGateSeedError("Synthetic artifact seed Job was not claimed")
    lease = claim.lease
    vault = PostgresArtifactDekVault(keyring)
    storage = GovernedRawArtifactStorage(
        stores=RawArtifactStores(
            encrypted_raw=raw_object_store,
            restricted_independent_dek=raw_object_store,
            derived_project=derived_object_store,
        ),
        encryptor=IndependentDekArtifactEncryptor(vault),
        tier_encryptor=ProjectTierArtifactEncryptor(keyring),
        repository=PostgresRawArtifactManifestRepository(store=store, dek_vault=vault),
    )
    restricted = storage.persist(
        _request(
            lease=lease,
            artifact_id=IDS.synthetic_restricted,
            payload=bytearray(b"public style source containing restricted content"),
            captured_at=now,
            access_class=ArtifactAccessClass.PUBLIC,
            form=ArtifactForm.RAW,
            detected_findings=(SensitiveFinding.RESTRICTED_CONTENT,),
        )
    )
    tier = storage.persist(
        _request(
            lease=lease,
            artifact_id=IDS.synthetic_tier,
            payload=bytearray(b'{"style":"anonymous Australian English"}'),
            captured_at=now,
            access_class=ArtifactAccessClass.PUBLIC,
            form=ArtifactForm.DERIVED,
            detected_findings=(),
        )
    )
    if restricted.persisted is None or tier.persisted is None:
        raise RestoreGateSeedError("Synthetic artifact ciphertext was not persisted")
    with store.fenced_transaction(lease) as connection:
        store.complete_in_transaction(
            connection,
            lease,
            result_ref="restore-gate:synthetic-artifacts",
            details={"artifact_count": 2},
        )
    with connect() as connection:
        counts = connection.execute(
            """SELECT
                   (SELECT count(*) FROM synthetic_lab_artifact_deks
                    WHERE status = 'active'),
                   (SELECT count(*) FROM synthetic_lab_raw_artifacts
                    WHERE lifecycle_state <> 'deleted'
                      AND storage_tier <> 'restricted_independent_dek'),
                   (SELECT count(*) FROM synthetic_lab_raw_artifacts
                    WHERE lifecycle_state <> 'deleted')"""
        ).fetchone()
    if counts != (1, 1, 2):
        raise RestoreGateSeedError("Synthetic artifact seed coverage is incomplete")
    return {
        "active_dek_count": counts[0],
        "nondeleted_artifact_count": counts[2],
        "tier_key_artifact_count": counts[1],
    }


def _admit_public_style_collection(*, database_url: str, admitted_at: datetime) -> None:
    """Stage the exact public collection lineage required by artifact triggers."""

    persistence = build_synthetic_lab_persistence(database_url)
    if persistence is None:
        raise RestoreGateSeedError("Synthetic artifact seed requires a database URL")
    operator = LabPrincipal(
        project_id=IDS.project,
        actor_id=IDS.owner,
        roles=frozenset({LabRole.OPERATOR}),
    )
    approver = LabPrincipal(
        project_id=IDS.project,
        actor_id=IDS.reviewer,
        roles=frozenset({LabRole.APPROVER}),
    )
    source_url = "https://www.reddit.com/r/australia/"
    source = StyleSource(
        id=_fixture_id("style-source-revision"),
        project_id=IDS.project,
        source_id=_fixture_id("style-source"),
        revision_number=1,
        channel="reddit",
        access_mode=StyleAccessMode.PUBLIC,
        locale="en-AU",
        source_locator_hash=hashlib.sha256(source_url.encode("utf-8")).hexdigest(),
        status=StyleSourceStatus.ACTIVE,
        source_url=source_url,
    )
    persistence.resources.create_style_source(
        principal=operator,
        source=source,
        expected_version=0,
        idempotency_key="restore-gate-style-source-v1",
    )
    adapter_release = "restore-gate-reddit-v1"
    initial = create_authorization_record(
        id=_fixture_id("style-authorization-v1"),
        project_id=IDS.project,
        channel=source.channel,
        adapter_release=adapter_release,
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
    persistence.style.create_authorization(
        principal=operator,
        record=initial,
        expected_version=0,
        idempotency_key="restore-gate-style-authorization-create-v1",
    )
    approved = create_authorization_record(
        id=_fixture_id("style-authorization-v2"),
        project_id=IDS.project,
        channel=source.channel,
        adapter_release=adapter_release,
        version_number=2,
        previous_version_id=initial.id,
        state=AuthorizationState.APPROVED,
        evidence_reference_hash=stable_hash("restore-gate-style-authorization-evidence"),
        decided_by=IDS.reviewer,
        decided_at=admitted_at,
        allowed_purposes=("style_collection",),
        max_requests_per_period=10,
        period_seconds=60,
        max_concurrency=1,
        expires_at=admitted_at + timedelta(hours=2),
        decision_reason="Approved public restore Gate Style Collection fixture.",
    )
    persistence.style.decide_authorization(
        principal=approver,
        record=approved,
        expected_version=1,
        idempotency_key="restore-gate-style-authorization-approve-v2",
    )
    if approved.expires_at is None:
        raise RestoreGateSeedError("approved Style Collection authorization lacks expiry")
    task = StyleCollectionTask(
        project_id=IDS.project,
        job_id=IDS.synthetic_job,
        collection_run_id=_fixture_id("style-collection-run"),
        style_source_revision_id=source.id,
        source_revision_number=source.revision_number,
        channel=source.channel,
        locale=source.locale,
        access_mode=source.access_mode,
        source_url=source_url,
        source_locator_hash=source.source_locator_hash,
        adapter_release=adapter_release,
        authorization=AuthorizationBinding(
            authorization_id=approved.id,
            project_id=IDS.project,
            channel=source.channel,
            adapter_release=adapter_release,
            version_number=approved.version_number,
            authorization_hash=approved.record_hash,
            purpose="style_collection",
            expires_at=approved.expires_at,
        ),
        login_secret=None,
        allowed_redirect_hosts=("www.reddit.com",),
        robots_user_agent="GeoRestoreGateStyleBot/1.0",
        raw_artifact_id=IDS.synthetic_restricted,
        derived_artifact_id=IDS.synthetic_tier,
        tmpfs=TmpfsCapturePolicy(
            mount_path="/run/geo-restore-gate-style",
            maximum_bytes=1_048_576,
        ),
    )
    registry = _adapter_registry(adapter_release)
    StyleCollectionExecutionApplication(
        persistence.uow_factory,
        registry=registry,
        clock=lambda: admitted_at,
    ).enqueue(
        principal=operator,
        task=task,
        outbox_id=_fixture_id("style-collection-outbox"),
        idempotency_key="restore-gate-style-collection-admission-v1",
    )


def _adapter_registry(adapter_release: str) -> StyleAdapterRegistry:
    adapter = StyleAdapterRelease(
        channel="reddit",
        adapter_release=adapter_release,
        content_selectors=("article",),
        allowed_resource_hosts=("www.reddit.com",),
        navigation_timeout_ms=10_000,
        settle_timeout_ms=0,
        login_flow=None,
        admission_state=StyleAdapterAdmission.LIVE_CANARY_APPROVED,
    )
    return StyleAdapterRegistry(
        release_id="restore-gate-style-registry-v1",
        adapters=MappingProxyType({(adapter.channel, adapter.adapter_release): adapter}),
        registry_hash=stable_hash("restore-gate-style-registry-v1"),
    )


def _fixture_id(name: str) -> UUID:
    return uuid5(IDS.project, f"restore-gate-synthetic:{name}")


def _request(
    *,
    lease: WorkerLease,
    artifact_id: UUID,
    payload: bytearray,
    captured_at: datetime,
    access_class: ArtifactAccessClass,
    form: ArtifactForm,
    detected_findings: tuple[SensitiveFinding, ...],
) -> RawArtifactWriteRequest:
    digest = hashlib.sha256(payload).hexdigest()
    return RawArtifactWriteRequest(
        lease=lease,
        inspection=RawArtifactInspection(
            artifact_id=artifact_id,
            project_id=IDS.project,
            captured_at=captured_at,
            access_class=access_class,
            form=form,
            payload_hash=digest,
            detected_findings=detected_findings,
            unresolved_findings=(),
            redaction_applied=False,
            redaction_verified=False,
            redacted_payload_hash=None,
            anonymization_verified=form is ArtifactForm.DERIVED,
            policy_max_ttl_days=7,
        ),
        payload=payload,
        media_type="application/json" if form is ArtifactForm.DERIVED else "text/html",
        source_identity_hash=stable_hash(f"restore-gate-source:{artifact_id}"),
        record_count=1,
        producer_release="restore-gate-seed-v1",
    )


__all__ = ["seed_synthetic_artifacts"]
