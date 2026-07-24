from datetime import UTC, datetime, timedelta
import hashlib
from types import MappingProxyType
from uuid import uuid4

import pytest

from geo_core.synthetic_lab.authorization import (
    AuthorizationBinding,
    AuthorizationState,
    create_authorization_record,
)
from geo_core.synthetic_lab.collection_application import (
    StyleCollectionExecutionApplication,
)
from geo_core.synthetic_lab.collection_execution_contracts import (
    StyleCollectionExecutionError,
    StyleCollectionTask,
    TmpfsCapturePolicy,
)
from geo_core.synthetic_lab.domain import StyleAccessMode
from geo_core.synthetic_lab.memory import (
    InMemorySyntheticLabStore,
    InMemorySyntheticLabUnitOfWorkFactory,
)
from geo_core.synthetic_lab.ports import AuthorizationEnvelope, LabPrincipal, LabRole
from geo_core.synthetic_lab.style_browser import (
    StyleAdapterAdmission,
    StyleAdapterRegistry,
    StyleAdapterRelease,
)


NOW = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


def test_collection_enqueue_is_atomic_and_rejects_reviewed_fixture_release() -> None:
    project_id = uuid4()
    store = InMemorySyntheticLabStore()
    factory = InMemorySyntheticLabUnitOfWorkFactory(store)
    authorization = _authorization(project_id)
    _seed_authorization(factory, authorization)
    task = _task(project_id, authorization)

    fixture_app = StyleCollectionExecutionApplication(
        factory,
        registry=_registry(StyleAdapterAdmission.REVIEWED_FIXTURE),
        clock=lambda: NOW,
    )
    with pytest.raises(StyleCollectionExecutionError, match="no approved live canary"):
        fixture_app.enqueue(
            principal=_operator(project_id),
            task=task,
            outbox_id=uuid4(),
            idempotency_key="style-collection-fixture-denied",
        )
    assert store.job_count(project_id) == store.outbox_count(project_id) == 0

    app = StyleCollectionExecutionApplication(
        factory,
        registry=_registry(StyleAdapterAdmission.LIVE_CANARY_APPROVED),
        clock=lambda: NOW,
    )
    outbox_id = uuid4()
    receipt = app.enqueue(
        principal=_operator(project_id),
        task=task,
        outbox_id=outbox_id,
        idempotency_key="style-collection-live",
    )
    assert receipt.result.input_hash == task.input_hash
    assert store.get_style_collection_task(
        project_id=project_id, job_id=task.job_id
    ) == task
    replay = app.enqueue(
        principal=_operator(project_id),
        task=task,
        outbox_id=outbox_id,
        idempotency_key="style-collection-live",
    )
    assert replay.replayed is True
    assert store.job_count(project_id) == store.outbox_count(project_id) == 1


def test_collection_enqueue_rechecks_current_authorization_version() -> None:
    project_id = uuid4()
    store = InMemorySyntheticLabStore()
    factory = InMemorySyntheticLabUnitOfWorkFactory(store)
    authorization = _authorization(project_id)
    _seed_authorization(factory, authorization)
    replacement = create_authorization_record(
        id=uuid4(),
        project_id=project_id,
        channel="reddit",
        adapter_release="reddit-public-v1",
        version_number=2,
        previous_version_id=authorization.id,
        state=AuthorizationState.REVOKED,
        evidence_reference_hash=authorization.evidence_reference_hash,
        decided_by=uuid4(),
        decided_at=NOW,
        allowed_purposes=authorization.allowed_purposes,
        max_requests_per_period=authorization.max_requests_per_period,
        period_seconds=authorization.period_seconds,
        max_concurrency=authorization.max_concurrency,
        expires_at=authorization.expires_at,
        decision_reason="Collection authorization revoked.",
    )
    with factory(project_id=project_id) as uow:
        uow.authorizations.stage(
            AuthorizationEnvelope(record=replacement, submitted_by=uuid4()),
            expected_version=1,
        )
        uow.commit()

    app = StyleCollectionExecutionApplication(
        factory,
        registry=_registry(StyleAdapterAdmission.LIVE_CANARY_APPROVED),
        clock=lambda: NOW,
    )
    with pytest.raises(StyleCollectionExecutionError, match="stale or inactive"):
        app.enqueue(
            principal=_operator(project_id),
            task=_task(project_id, authorization),
            outbox_id=uuid4(),
            idempotency_key="style-collection-stale",
        )
    assert store.job_count(project_id) == 0


def _authorization(project_id):
    return create_authorization_record(
        id=uuid4(),
        project_id=project_id,
        channel="reddit",
        adapter_release="reddit-public-v1",
        version_number=1,
        previous_version_id=None,
        state=AuthorizationState.APPROVED,
        evidence_reference_hash=_hash("live-canary-evidence"),
        decided_by=uuid4(),
        decided_at=NOW - timedelta(days=1),
        allowed_purposes=("style_collection",),
        max_requests_per_period=10,
        period_seconds=60,
        max_concurrency=1,
        expires_at=NOW + timedelta(days=30),
        decision_reason="Approved after legal and operational review.",
    )


def _seed_authorization(factory, authorization) -> None:
    with factory(project_id=authorization.project_id) as uow:
        uow.authorizations.stage(
            AuthorizationEnvelope(record=authorization, submitted_by=uuid4()),
            expected_version=0,
        )
        uow.commit()


def _task(project_id, authorization) -> StyleCollectionTask:
    return StyleCollectionTask(
        project_id=project_id,
        job_id=uuid4(),
        collection_run_id=uuid4(),
        style_source_revision_id=uuid4(),
        source_revision_number=1,
        channel="reddit",
        locale="en-AU",
        access_mode=StyleAccessMode.PUBLIC,
        source_url="https://www.reddit.com/r/australia/",
        source_locator_hash=_hash("https://www.reddit.com/r/australia/"),
        adapter_release="reddit-public-v1",
        authorization=AuthorizationBinding(
            authorization_id=authorization.id,
            project_id=project_id,
            channel="reddit",
            adapter_release="reddit-public-v1",
            version_number=authorization.version_number,
            authorization_hash=authorization.record_hash,
            purpose="style_collection",
            expires_at=authorization.expires_at,
        ),
        login_secret=None,
        allowed_redirect_hosts=("www.reddit.com", "www.redditstatic.com"),
        robots_user_agent="GeoStyleResearchBot/1.0",
        raw_artifact_id=uuid4(),
        derived_artifact_id=uuid4(),
        tmpfs=TmpfsCapturePolicy(
            mount_path="/run/geo-style-capture",
            maximum_bytes=1_048_576,
        ),
    )


def _registry(admission: StyleAdapterAdmission) -> StyleAdapterRegistry:
    adapter = StyleAdapterRelease(
        channel="reddit",
        adapter_release="reddit-public-v1",
        content_selectors=("article",),
        allowed_resource_hosts=("www.redditstatic.com",),
        navigation_timeout_ms=10_000,
        settle_timeout_ms=0,
        login_flow=None,
        admission_state=admission,
    )
    return StyleAdapterRegistry(
        release_id="style-registry-v1",
        adapters=MappingProxyType({("reddit", "reddit-public-v1"): adapter}),
        registry_hash=_hash(admission.value),
    )


def _operator(project_id) -> LabPrincipal:
    return LabPrincipal(
        project_id=project_id,
        actor_id=uuid4(),
        roles=frozenset({LabRole.OPERATOR}),
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
