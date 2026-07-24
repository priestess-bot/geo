from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from geo_core.jobs.postgres import WorkerLease
from geo_core.secrets.models import SecretValue, SecretVersionHandle
from geo_core.synthetic_lab.authorization import (
    AuthorizationBinding,
    AuthorizationState,
    create_authorization_record,
)
from geo_core.synthetic_lab.collection_execution import StyleCollectionHandler
from geo_core.synthetic_lab.collection_execution_contracts import (
    CollectionBlockReason,
    ExtractedStyleText,
    InspectedArtifact,
    RobotsAccessDecision,
    StyleCollectionTask,
    StylePageCapture,
    TmpfsCapturePolicy,
)
from geo_core.synthetic_lab.domain import StyleAccessMode, SyntheticLabContractError
from geo_core.synthetic_lab.raw_artifact_governance import (
    ArtifactAccessClass,
    ArtifactForm,
    RawArtifactInspection,
    govern_raw_artifact,
)


PROJECT_ID = UUID("40000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 23, 10, tzinfo=UTC)


class FakeStore:
    def __init__(self) -> None:
        self.heartbeats = 0
        self.connection = object()
        self.completed = []
        self.failed = []
        self.lose_on_complete = False

    def heartbeat(self, lease, *, lease_for) -> None:
        del lease, lease_for
        self.heartbeats += 1

    @contextmanager
    def fenced_transaction(self, lease):
        del lease
        yield self.connection

    def complete_in_transaction(self, connection, lease, *, result_ref, details) -> None:
        if self.lose_on_complete:
            from geo_core.jobs.postgres import LostJobLease

            raise LostJobLease("fixture finalize race")
        self.completed.append((connection, lease, result_ref, details))

    def fail(self, lease, *, error_code, details, retry_delay):
        del lease, error_code
        self.failed.append((details, retry_delay))
        return "retry_wait" if retry_delay else "failed"


class FakeRepository:
    def __init__(self, task: StyleCollectionTask) -> None:
        self.task = task
        self.finalized = []
        self.orphaned = []

    def load(self, lease):
        del lease
        return self.task

    def finalize(self, *, connection, lease, task, output) -> None:
        self.finalized.append((connection, lease, task, output))

    def mark_attempt_orphaned(self, *, lease, reason) -> None:
        self.orphaned.append((lease.job_id, lease.fencing_generation, reason))


class FakeAuthorizations:
    def __init__(self, current) -> None:
        self.value = current
        self.calls = 0

    def current(self, binding):
        del binding
        self.calls += 1
        return self.value


class FakeSecrets:
    def __init__(self) -> None:
        self.handles = []

    def resolve(self, handle):
        self.handles.append(handle)
        return SecretValue("normal-login-test-credential")


class FixtureCollector:
    def __init__(self) -> None:
        self.redirects = ("https://reviews.example.test/final",)
        self.robots_allowed = True
        self.block_reason = None
        self.collect_calls = 0
        self.robots_calls = []
        self.navigated = []
        self.capture_payloads = []

    def check_robots(self, task, url):
        del task
        self.robots_calls.append(url)
        return RobotsAccessDecision(
            allowed=self.robots_allowed,
            checked_at=NOW,
            policy_hash=_hash(f"robots:{url}:{self.robots_allowed}"),
        )

    def collect(self, task, *, credential, before_navigation):
        self.collect_calls += 1
        if task.access_mode is StyleAccessMode.AUTHENTICATED:
            assert credential is not None
            assert credential.matches("normal-login-test-credential")
        else:
            assert credential is None
        chain = (task.source_url, *self.redirects)
        for url in chain:
            before_navigation(url)
            self.navigated.append(url)
        payload = bytearray(
            b"captcha page" if self.block_reason else b"fixture public review page"
        )
        self.capture_payloads.append(payload)
        return StylePageCapture(
            final_url=chain[-1],
            navigation_chain=chain,
            raw_bundle=payload,
            raw_media_type="application/zip",
            captured_at=NOW,
            capture_release="fixture-style-collector-v1",
            block_reason=self.block_reason,
        )


class FixtureExtractor:
    def __init__(self) -> None:
        self.payloads = []

    def extract(self, task, capture):
        del task, capture
        payload = bytearray(b"anonymous Australian English style sample")
        self.payloads.append(payload)
        return ExtractedStyleText(
            payload=payload,
            record_count=1,
            parser_release="fixture-style-parser-v1",
        )


class FixtureInspector:
    def __init__(self) -> None:
        self.payloads = []

    def inspect_raw(self, task, capture):
        payload = bytearray(capture.raw_bundle or b"")
        self.payloads.append(payload)
        access = (
            ArtifactAccessClass.AUTHENTICATED
            if task.access_mode is StyleAccessMode.AUTHENTICATED
            else ArtifactAccessClass.PUBLIC
        )
        return InspectedArtifact(
            inspection=_inspection(
                task,
                task.raw_artifact_id,
                payload,
                access=access,
                form=ArtifactForm.RAW,
            ),
            payload=payload,
        )

    def inspect_derived(self, task, capture, extracted):
        del capture
        payload = bytearray(extracted.payload)
        self.payloads.append(payload)
        return InspectedArtifact(
            inspection=_inspection(
                task,
                task.derived_artifact_id,
                payload,
                access=ArtifactAccessClass.PUBLIC,
                form=ArtifactForm.DERIVED,
            ),
            payload=payload,
        )


class FixtureArtifacts:
    def __init__(self) -> None:
        self.requests = []

    def persist(self, request):
        self.requests.append(request)
        decision = govern_raw_artifact(request.inspection)
        manifest = SimpleNamespace(manifest_hash=_hash(f"manifest:{request.inspection.artifact_id}"))
        persisted = SimpleNamespace(manifest=manifest) if decision.persistence_allowed else None
        for index in range(len(request.payload)):
            request.payload[index] = 0
        return SimpleNamespace(decision=decision, persisted=persisted)


@dataclass(frozen=True)
class Runtime:
    handler: StyleCollectionHandler
    task: StyleCollectionTask
    lease: WorkerLease
    store: FakeStore
    repository: FakeRepository
    authorizations: FakeAuthorizations
    secrets: FakeSecrets
    collector: FixtureCollector
    extractor: FixtureExtractor
    inspector: FixtureInspector
    artifacts: FixtureArtifacts


def test_normal_login_collection_guards_every_navigation_and_persists_raw_and_derived() -> None:
    runtime = _runtime()

    result = runtime.handler.handle(runtime.lease)

    assert result["status"] == "succeeded"
    assert result["outcome"] == "captured"
    assert runtime.secrets.handles == [runtime.task.login_secret]
    assert runtime.collector.navigated == [runtime.task.source_url, *runtime.collector.redirects]
    assert runtime.collector.robots_calls == runtime.collector.navigated
    assert len(runtime.artifacts.requests) == 2
    assert runtime.repository.finalized[0][0] is runtime.store.connection
    assert runtime.store.completed[0][0] is runtime.store.connection
    assert all(not any(payload) for payload in runtime.collector.capture_payloads)
    assert all(not any(payload) for payload in runtime.extractor.payloads)
    assert all(not any(payload) for payload in runtime.inspector.payloads)
    assert "normal-login-test-credential" not in repr(runtime.task)


def test_public_collection_never_resolves_a_login_secret() -> None:
    runtime = _runtime(access_mode=StyleAccessMode.PUBLIC)

    result = runtime.handler.handle(runtime.lease)

    assert result["outcome"] == "captured"
    assert runtime.secrets.handles == []


def test_wrong_secret_purpose_is_rejected_before_worker_or_network() -> None:
    task = _task()
    wrong = SecretVersionHandle(
        reference_id=uuid4(),
        project_id=PROJECT_ID,
        purpose="model_provider.openai",
        version=1,
    )

    with pytest.raises(SyntheticLabContractError, match="exact channel"):
        replace(task, login_secret=wrong)


def test_robots_denial_stops_before_target_navigation_and_writes_no_artifact() -> None:
    runtime = _runtime()
    runtime.collector.robots_allowed = False

    result = runtime.handler.handle(runtime.lease)

    assert result["outcome"] == "access_blocked"
    assert runtime.collector.navigated == []
    assert runtime.collector.collect_calls == 1
    assert runtime.artifacts.requests == []
    assert runtime.repository.finalized[0][3].block_reason is CollectionBlockReason.ROBOTS_DENIED


def test_redirect_outside_allowlist_is_stopped_before_request_without_rotation() -> None:
    runtime = _runtime()
    runtime.collector.redirects = ("https://unapproved.example.test/escape",)

    result = runtime.handler.handle(runtime.lease)

    assert result["outcome"] == "access_blocked"
    assert runtime.collector.navigated == [runtime.task.source_url]
    assert runtime.artifacts.requests == []
    assert runtime.task.allow_proxy_rotation is False
    assert runtime.task.allow_stealth is False
    assert runtime.task.allow_captcha_solver is False
    assert runtime.repository.finalized[0][3].block_reason is CollectionBlockReason.REDIRECT_DENIED


def test_captcha_stops_endpoint_run_without_retry_or_artifact_persistence() -> None:
    runtime = _runtime()
    runtime.collector.block_reason = CollectionBlockReason.CAPTCHA

    result = runtime.handler.handle(runtime.lease)

    assert result["outcome"] == "access_blocked"
    assert runtime.collector.collect_calls == 1
    assert runtime.artifacts.requests == []
    assert runtime.store.failed == []
    assert all(not any(payload) for payload in runtime.collector.capture_payloads)


def test_revoked_authorization_stops_before_secret_resolution_and_network() -> None:
    runtime = _runtime()
    runtime.authorizations.value = _authorization(AuthorizationState.REVOKED, version=3)

    result = runtime.handler.handle(runtime.lease)

    assert result["outcome"] == "access_blocked"
    assert runtime.secrets.handles == []
    assert runtime.collector.collect_calls == 0
    assert runtime.repository.finalized[0][3].block_reason is (
        CollectionBlockReason.AUTHORIZATION_STALE
    )


def test_finalize_lost_lease_orphans_attempt_artifacts_and_never_reports_success() -> None:
    from geo_core.jobs.postgres import LostJobLease

    runtime = _runtime()
    runtime.store.lose_on_complete = True

    with pytest.raises(LostJobLease, match="fixture finalize race"):
        runtime.handler.handle(runtime.lease)

    assert len(runtime.artifacts.requests) == 2
    assert runtime.store.completed == []
    assert runtime.repository.orphaned == [
        (runtime.lease.job_id, runtime.lease.fencing_generation, "lease_lost_or_cancelled")
    ]


def _runtime(*, access_mode: StyleAccessMode = StyleAccessMode.AUTHENTICATED) -> Runtime:
    authorization = _authorization(AuthorizationState.APPROVED)
    task = _task(access_mode=access_mode, authorization=authorization)
    lease = WorkerLease(
        job_id=task.job_id,
        project_id=PROJECT_ID,
        kind="style.collect",
        worker_id="fixture-style-worker",
        lease_token=uuid4(),
        fencing_generation=1,
        attempt_count=1,
        max_attempts=3,
    )
    store = FakeStore()
    repository = FakeRepository(task)
    authorizations = FakeAuthorizations(authorization)
    secrets = FakeSecrets()
    collector = FixtureCollector()
    extractor = FixtureExtractor()
    inspector = FixtureInspector()
    artifacts = FixtureArtifacts()
    handler = StyleCollectionHandler(
        store=store,  # type: ignore[arg-type]
        repository=repository,
        authorizations=authorizations,
        collector=collector,
        secrets=secrets,
        extractor=extractor,
        inspector=inspector,
        artifacts=artifacts,  # type: ignore[arg-type]
        lease_for=timedelta(minutes=2),
        clock=lambda: NOW + timedelta(minutes=1),
    )
    return Runtime(
        handler,
        task,
        lease,
        store,
        repository,
        authorizations,
        secrets,
        collector,
        extractor,
        inspector,
        artifacts,
    )


def _task(
    *,
    access_mode: StyleAccessMode = StyleAccessMode.AUTHENTICATED,
    authorization=None,
) -> StyleCollectionTask:
    authorization = authorization or _authorization(AuthorizationState.APPROVED)
    binding = AuthorizationBinding(
        authorization_id=authorization.id,
        project_id=PROJECT_ID,
        channel="reddit",
        adapter_release="style-reddit-v1",
        version_number=authorization.version_number,
        authorization_hash=authorization.record_hash,
        purpose="style_collection",
        expires_at=authorization.expires_at,  # type: ignore[arg-type]
    )
    secret = (
        SecretVersionHandle(
            reference_id=uuid4(),
            project_id=PROJECT_ID,
            purpose="style_collection_login.reddit",
            version=1,
        )
        if access_mode is StyleAccessMode.AUTHENTICATED
        else None
    )
    return StyleCollectionTask(
        project_id=PROJECT_ID,
        job_id=uuid4(),
        collection_run_id=uuid4(),
        style_source_revision_id=uuid4(),
        source_revision_number=1,
        channel="reddit",
        locale="en-AU",
        access_mode=access_mode,
        source_url="https://reviews.example.test/start",
        source_locator_hash=_hash("reviews.example.test/start"),
        adapter_release="style-reddit-v1",
        authorization=binding,
        login_secret=secret,
        allowed_redirect_hosts=("reviews.example.test",),
        robots_user_agent="GeoStyleResearchBot/1.0",
        raw_artifact_id=uuid4(),
        derived_artifact_id=uuid4(),
        tmpfs=TmpfsCapturePolicy(
            mount_path="/dev/shm/geo-style-collection",
            maximum_bytes=8 * 1024 * 1024,
        ),
    )


def _authorization(state: AuthorizationState, *, version: int = 2):
    values = {
        "id": uuid4(),
        "project_id": PROJECT_ID,
        "channel": "reddit",
        "adapter_release": "style-reddit-v1",
        "version_number": version,
        "previous_version_id": uuid4() if version > 1 else None,
        "state": state,
        "evidence_reference_hash": _hash("authorization-evidence"),
        "decided_by": uuid4(),
        "decided_at": NOW,
        "allowed_purposes": ("style_collection",),
        "max_requests_per_period": 10,
        "period_seconds": 60,
        "max_concurrency": 1,
        "expires_at": NOW + timedelta(days=30),
        "decision_reason": f"fixture-{state.value}",
    }
    if state is AuthorizationState.REVOKED:
        values["expires_at"] = NOW + timedelta(days=30)
    return create_authorization_record(**values)


def _inspection(task, artifact_id, payload, *, access, form):
    return RawArtifactInspection(
        artifact_id=artifact_id,
        project_id=task.project_id,
        captured_at=NOW,
        access_class=access,
        form=form,
        payload_hash=hashlib.sha256(payload).hexdigest(),
        detected_findings=(),
        unresolved_findings=(),
        redaction_applied=False,
        redaction_verified=False,
        redacted_payload_hash=None,
        anonymization_verified=form is ArtifactForm.DERIVED,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
