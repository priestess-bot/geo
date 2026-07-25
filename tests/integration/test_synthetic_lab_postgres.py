from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.project_scope import set_project_scope
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.synthetic_lab.application_support import canonical_hash, new_synthetic_job
from geo_core.synthetic_lab.authorization import (
    AuthorizationRecord,
    AuthorizationState,
    CollectionAdmissionRequest,
    CollectionPath,
    create_authorization_record,
    recheck_before_navigation,
)
from geo_core.synthetic_lab.execution_contracts import (
    CorpusFinalizeTask,
    FrozenEvidence,
    FrozenPromptRef,
    StyleProfileBuildOutput,
    StyleProfileBuildTask,
    SyntheticExecutionError,
)
from geo_core.synthetic_lab.execution import SyntheticTaskExecutor
from geo_core.synthetic_lab.corpus import CorpusCandidateEntry, CorpusRole
from geo_core.synthetic_lab.ports import (
    LabPrincipal,
    LabRole,
    RuntimeInputSnapshot,
    StaticRuntimeInputPort,
)
from geo_core.synthetic_lab.postgres import build_synthetic_lab_persistence
from geo_core.synthetic_lab.postgres_execution import build_synthetic_execution_repository
from geo_core.synthetic_lab.postgres_api_reads import PostgresSyntheticApiReads
from geo_core.synthetic_lab.revision import ReviewRunStatus
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


@dataclass(frozen=True)
class _Database:
    admin_url: str
    app_url: str
    worker_url: str
    first: dict[str, UUID]
    second: dict[str, UUID]


@pytest.fixture
def database() -> _Database:
    suffix = uuid4().hex[:10]
    database_name = f"geo_synthetic_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_synthetic_app_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_synthetic_worker_{suffix}", uuid4().hex
    roles: list[str] = []
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0029_model_gateway")
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            roles.append(app_login)
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            roles.append(worker_login)
            first = seed_project(admin, suffix=f"synthetic-{suffix}-a")
            second = seed_project(admin, suffix=f"synthetic-{suffix}-b")
        yield _Database(
            admin_url=target_url,
            app_url=login_url(target_url, user=app_login, password=app_password),
            worker_url=login_url(target_url, user=worker_login, password=worker_password),
            first=first,
            second=second,
        )
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
            for role in reversed(roles):
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def test_synthetic_lab_postgres_authorization_execution_and_guards(
    database: _Database,
) -> None:
    persistence = build_synthetic_lab_persistence(database.app_url)
    assert persistence is not None
    project_id = database.first["project"]
    submitter = _principal(database.first, "owner", LabRole.OPERATOR)
    approver = _principal(database.first, "reviewer", LabRole.APPROVER)
    now = datetime.now(UTC)

    initial = _authorization(
        project_id=project_id,
        state=AuthorizationState.NOT_ASSESSED,
        version=1,
        previous_id=None,
        adapter_release="reddit-style-v1",
    )
    persistence.style.create_authorization(
        principal=submitter,
        record=initial,
        expected_version=0,
        idempotency_key="authorization:create:v1",
    )
    approved = _authorization(
        project_id=project_id,
        state=AuthorizationState.APPROVED,
        version=2,
        previous_id=initial.id,
        adapter_release=initial.adapter_release,
        decided_by=approver.actor_id,
        decided_at=now,
        expires_at=now + timedelta(days=30),
    )
    persistence.style.decide_authorization(
        principal=approver,
        record=approved,
        expected_version=1,
        idempotency_key="authorization:approve:v2",
    )
    admission = persistence.style.admit_automatic_collection(
        principal=submitter,
        request=CollectionAdmissionRequest(
            project_id=project_id,
            channel="reddit",
            adapter_release=approved.adapter_release,
            path=CollectionPath.AUTOMATIC,
            purpose="style_collection",
            requested_at=now + timedelta(minutes=1),
            planned_requests=5,
            planned_period_seconds=60,
            planned_concurrency=1,
        ),
        job_id=uuid4(),
        outbox_id=uuid4(),
        style_source_revision_id=uuid4(),
        idempotency_key="collection:admit:v1",
    ).result
    assert admission.command.binding is not None
    assert admission.job is not None
    old_binding = admission.command.binding

    revoked = _authorization(
        project_id=project_id,
        state=AuthorizationState.REVOKED,
        version=3,
        previous_id=approved.id,
        adapter_release=approved.adapter_release,
        decided_by=approver.actor_id,
        decided_at=now + timedelta(minutes=2),
        expires_at=approved.expires_at,
        grant_from=approved,
    )
    persistence.style.revoke_authorization(
        principal=approver,
        record=revoked,
        expected_version=2,
        idempotency_key="authorization:revoke:v3",
    )
    reassessed = persistence.style.reassess_authorization(
        principal=submitter,
        previous=revoked,
        reassessment_id=uuid4(),
        opened_at=now + timedelta(minutes=3),
        reassessment_reason="Terms and capture policy changed.",
        expected_version=3,
        idempotency_key="authorization:reassess:v4",
    ).result
    current = persistence.collection_authorizations.current(old_binding)
    assert current == reassessed
    assert not recheck_before_navigation(
        old_binding,
        current,
        at=now + timedelta(minutes=4),
    ).proceed

    self_decision = _authorization(
        project_id=project_id,
        state=AuthorizationState.ASSESSED_NO_BASIS,
        version=5,
        previous_id=reassessed.id,
        adapter_release=reassessed.adapter_release,
        decided_by=submitter.actor_id,
        decided_at=now + timedelta(minutes=5),
    )
    with psycopg.connect(database.app_url) as connection:
        set_project_scope(connection, project_id)
        with pytest.raises(psycopg.Error, match="maker-checker"):
            _insert_authorization(connection, self_decision, submitter.actor_id)
            connection.commit()
        connection.rollback()
        set_project_scope(connection, project_id)
        gap = _authorization(
            project_id=project_id,
            state=AuthorizationState.ASSESSED_NO_BASIS,
            version=6,
            previous_id=reassessed.id,
            adapter_release=reassessed.adapter_release,
            decided_by=submitter.actor_id,
            decided_at=now + timedelta(minutes=5),
        )
        with pytest.raises(psycopg.Error, match="CAS"):
            _insert_authorization(connection, gap, submitter.actor_id)
            connection.commit()
        connection.rollback()

    renewed = _authorization(
        project_id=project_id,
        state=AuthorizationState.APPROVED,
        version=5,
        previous_id=reassessed.id,
        adapter_release=reassessed.adapter_release,
        decided_by=approver.actor_id,
        decided_at=now + timedelta(minutes=6),
        expires_at=now + timedelta(days=60),
        evidence_seed="renewed-authorization",
    )
    persistence.style.decide_authorization(
        principal=approver,
        record=renewed,
        expected_version=4,
        idempotency_key="authorization:approve:v5",
    )
    _assert_effectively_expired_approval_can_reassess(
        persistence=persistence,
        project_id=project_id,
        submitter=submitter,
        approver=approver,
        now=now,
    )

    task = _task(project_id, requested_by=submitter.actor_id)
    enqueued = persistence.execution.enqueue(
        principal=submitter,
        task=task,
        outbox_id=uuid4(),
        runtime_inputs=StaticRuntimeInputPort(task.runtime_inputs),
        prompts=_CurrentPrompts(),
        idempotency_key="execution:style-profile:v1",
    )
    assert enqueued.result.input_hash == task.input_hash
    replay = persistence.execution.enqueue(
        principal=submitter,
        task=task,
        outbox_id=_outbox_id(database.app_url, project_id, task.job_id),
        runtime_inputs=StaticRuntimeInputPort(task.runtime_inputs),
        prompts=_CurrentPrompts(),
        idempotency_key="execution:style-profile:v1",
    )
    assert replay.replayed

    def connect_worker() -> psycopg.Connection[dict_row]:
        return psycopg.connect(database.worker_url, row_factory=dict_row)

    store = PostgresDurableJobStore(connect_worker)
    claim = store.claim(
        job_id=task.job_id,
        project_id=project_id,
        expected_kind="style.profile.build",
        worker_id="synthetic-integration-worker",
        lease_for=timedelta(minutes=2),
    )
    assert claim.disposition == "claimed" and claim.lease is not None
    lease = claim.lease
    execution = build_synthetic_execution_repository(database.worker_url)
    assert execution.load(lease) == task
    with pytest.raises(SyntheticExecutionError, match="stale or cancelled"):
        execution.load(replace(lease, kind="review.case.run"))

    output = StyleProfileBuildOutput(
        project_id=project_id,
        profile_version_id=task.profile_version_id,
        profile_hash=_hash("built-profile-v1"),
        artifact_hash=_hash("built-profile-artifact-v1"),
        model_call_ids=(uuid4(),),
    )
    with store.fenced_transaction(lease) as connection:
        execution.finalize(
            connection=connection,
            lease=lease,
            task=task,
            output=output,
            runtime=task.runtime_inputs,
        )
        store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"synthetic://result/{output.result_hash}",
            details={"result_hash": output.result_hash, "task_input_hash": task.input_hash},
        )
    _assert_persisted_guards(database, task, output)
    _assert_unstaged_execution_fails_closed(database, persistence, task.runtime_inputs)

    migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    migration.attributes["geo_database_url_override"] = database.admin_url
    with pytest.raises(Exception, match="Synthetic Lab data exists"):
        alembic_command.downgrade(migration, "0029_model_gateway")


def test_synthetic_corpus_execution_is_fenced_projected_and_downgrade_safe(
    database: _Database,
) -> None:
    persistence = build_synthetic_lab_persistence(database.app_url)
    assert persistence is not None
    project_id = database.first["project"]
    principal = _principal(database.first, "owner", LabRole.OPERATOR)
    runtime = _task(project_id, requested_by=principal.actor_id).runtime_inputs
    candidate_id = uuid4()
    candidate_text = "Plain Australian English candidate grounded in the approved facts."
    candidate = CorpusCandidateEntry(
        project_id=project_id,
        resolution_id=uuid4(),
        candidate_id=candidate_id,
        candidate_output_hash=canonical_hash(candidate_text),
        status=ReviewRunStatus.COMPLETED_WITH_WARNING,
        warning_codes=("derived_or_unknown",),
        channel="reddit",
        scenario_mode="autonomous_scenario",
        competitor_scenario=False,
        model_key="openai:judge-v1",
        model_identity_hash=_hash("corpus-model-identity"),
        question_cluster_key="pressure-washer-comparison",
    )
    task = CorpusFinalizeTask(
        project_id=project_id,
        job_id=uuid4(),
        model_job_version=1,
        requested_by=principal.actor_id,
        corpus_version_id=uuid4(),
        corpus_id=uuid4(),
        version_number=1,
        role=CorpusRole.NEW_CANDIDATE,
        candidates=(candidate,),
        candidate_text={candidate_id: candidate_text},
        source_review_job_ids=(uuid4(),),
        source_corpus_job_id=None,
        runtime_inputs=runtime,
    )
    persistence.execution.enqueue(
        principal=principal,
        task=task,
        outbox_id=uuid4(),
        runtime_inputs=StaticRuntimeInputPort(runtime),
        prompts=_CurrentPrompts(),
        idempotency_key="execution:corpus-finalize:v1",
    )

    def connect_worker() -> psycopg.Connection[dict_row]:
        return psycopg.connect(database.worker_url, row_factory=dict_row)

    store = PostgresDurableJobStore(connect_worker)
    claim = store.claim(
        job_id=task.job_id,
        project_id=project_id,
        expected_kind="corpus.finalize",
        worker_id="synthetic-corpus-integration-worker",
        lease_for=timedelta(minutes=2),
    )
    assert claim.disposition == "claimed" and claim.lease is not None
    lease = claim.lease
    repository = build_synthetic_execution_repository(database.worker_url)
    assert repository.load(lease) == task
    output = SyntheticTaskExecutor(
        prompts=_CurrentPrompts(),
        model_gateway=_NeverModelGateway(),
    ).run(lease=lease, task=task, checkpoint=lambda: runtime)
    with store.fenced_transaction(lease) as connection:
        repository.finalize(
            connection=connection,
            lease=lease,
            task=task,
            output=output,
            runtime=runtime,
        )
        store.complete_in_transaction(
            connection,
            lease,
            result_ref=f"synthetic://result/{output.result_hash}",
            details={"result_hash": output.result_hash, "task_input_hash": task.input_hash},
        )

    reads = PostgresSyntheticApiReads(
        lambda: psycopg.connect(database.app_url, row_factory=dict_row)
    )
    view = reads.job_view(project_id, task.job_id)
    assert view.job.status.value == "succeeded"
    assert view.warning_summary == {
        "warning_count": 1,
        "candidate_count": 1,
        "warning_ratio": 1.0,
        "by_code": {"derived_or_unknown": 1},
        "by_channel": {"reddit": 1},
        "by_scenario_mode": {"autonomous_scenario": 1},
        "by_competitor": {"non_competitor": 1},
        "by_model": {"openai:judge-v1": 1},
        "by_question_cluster": {"pressure-washer-comparison": 1},
    }

    migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    migration.attributes["geo_database_url_override"] = database.admin_url
    with pytest.raises(Exception, match="cannot downgrade synthetic Corpus execution"):
        alembic_command.downgrade(migration, "0079_synth_profile_runtime")


class _CurrentPrompts:
    def assert_current(self, frozen: FrozenPromptRef) -> None:
        del frozen


class _NeverModelGateway:
    def execute(self, invocation: object) -> object:
        del invocation
        raise AssertionError("Corpus finalization must not issue a model call")


def _authorization(
    *,
    project_id: UUID,
    state: AuthorizationState,
    version: int,
    previous_id: UUID | None,
    adapter_release: str,
    decided_by: UUID | None = None,
    decided_at: datetime | None = None,
    expires_at: datetime | None = None,
    grant_from: AuthorizationRecord | None = None,
    evidence_seed: str = "authorization-evidence",
) -> AuthorizationRecord:
    evidence = purposes = rate = period = concurrency = None
    if state in {AuthorizationState.APPROVED, AuthorizationState.REVOKED}:
        evidence = grant_from.evidence_reference_hash if grant_from else _hash(evidence_seed)
        purposes = grant_from.allowed_purposes if grant_from else ("style_collection",)
        rate = grant_from.max_requests_per_period if grant_from else 10
        period = grant_from.period_seconds if grant_from else 60
        concurrency = grant_from.max_concurrency if grant_from else 2
        expires_at = grant_from.expires_at if grant_from else expires_at
    return create_authorization_record(
        id=uuid4(),
        project_id=project_id,
        channel="reddit",
        adapter_release=adapter_release,
        version_number=version,
        previous_version_id=previous_id,
        state=state,
        evidence_reference_hash=evidence,
        decided_by=decided_by,
        decided_at=decided_at,
        allowed_purposes=purposes or (),
        max_requests_per_period=rate,
        period_seconds=period,
        max_concurrency=concurrency,
        expires_at=expires_at,
        decision_reason=f"decision-{state.value}" if state != AuthorizationState.NOT_ASSESSED else None,
    )


def _insert_authorization(
    connection: psycopg.Connection[object],
    record: AuthorizationRecord,
    submitted_by: UUID,
) -> None:
    connection.execute(
        """INSERT INTO synthetic_lab_authorization_versions(
               id, project_id, channel, adapter_release, version_number,
               previous_version_id, state, evidence_reference_hash, decided_by,
               decided_at, allowed_purposes, max_requests_per_period, period_seconds,
               max_concurrency, expires_at, decision_reason, record_hash, submitted_by
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s)""",
        (
            record.id,
            record.project_id,
            record.channel,
            record.adapter_release,
            record.version_number,
            record.previous_version_id,
            record.state.value,
            record.evidence_reference_hash,
            record.decided_by,
            record.decided_at,
            list(record.allowed_purposes),
            record.max_requests_per_period,
            record.period_seconds,
            record.max_concurrency,
            record.expires_at,
            record.decision_reason,
            record.record_hash,
            submitted_by,
        ),
    )


def _assert_effectively_expired_approval_can_reassess(
    *, persistence: object, project_id: UUID, submitter: LabPrincipal,
    approver: LabPrincipal, now: datetime,
) -> None:
    style = persistence.style  # type: ignore[attr-defined]
    initial = _authorization(
        project_id=project_id,
        state=AuthorizationState.NOT_ASSESSED,
        version=1,
        previous_id=None,
        adapter_release="reddit-style-expired-v1",
    )
    style.create_authorization(
        principal=submitter, record=initial, expected_version=0,
        idempotency_key="expired:create:v1",
    )
    expired_effective = _authorization(
        project_id=project_id,
        state=AuthorizationState.APPROVED,
        version=2,
        previous_id=initial.id,
        adapter_release=initial.adapter_release,
        decided_by=approver.actor_id,
        decided_at=now - timedelta(days=3),
        expires_at=now - timedelta(days=2),
    )
    style.decide_authorization(
        principal=approver, record=expired_effective, expected_version=1,
        idempotency_key="expired:approve:v2",
    )
    reassessed = style.reassess_authorization(
        principal=submitter,
        previous=expired_effective,
        reassessment_id=uuid4(),
        opened_at=now,
        reassessment_reason="Expired grant requires a fresh assessment.",
        expected_version=2,
        idempotency_key="expired:reassess:v3",
    ).result
    assert reassessed.state is AuthorizationState.NOT_ASSESSED


def _task(project_id: UUID, *, requested_by: UUID) -> StyleProfileBuildTask:
    runtime = RuntimeInputSnapshot(
        project_id=project_id,
        fact_snapshot_id=uuid4(),
        fact_snapshot_hash=_hash("facts-v1"),
        profile_version_id=uuid4(),
        profile_hash=_hash("profile-draft-v1"),
        prompt_release_id=uuid4(),
        prompt_release_hash=_hash("profile-prompt-v1"),
        facts_current_approved=True,
        profile_frozen=True,
        prompt_frozen=True,
    )
    prompt = FrozenPromptRef(
        project_id=project_id,
        binding_id=uuid4(),
        binding_version=1,
        frozen_state_id=uuid4(),
        frozen_state_version=1,
        release_id=runtime.prompt_release_id,
        release_version=1,
        release_hash=runtime.prompt_release_hash,
        program_kind=ProgramKind.STYLE_PROFILE,
        purpose="synthetic_lab.style_profile",
        route=ModelRoute(
            provider="openai",
            adapter_release_id="openai-adapter-v1",
            adapter_release_hash=_hash("adapter-v1"),
            model_release_id="judge-v1",
            model_release_hash=_hash("model-v1"),
        ),
        configured_model="judge-v1",
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash=_hash("runtime-manifest-v1"),
        runtime_option_id=uuid4(),
        runtime_option_hash=_hash("runtime-option-v1"),
        model_policy=ModelPolicy(),
        model_policy_hash=_hash("policy-v1"),
    )
    return StyleProfileBuildTask(
        project_id=project_id,
        job_id=uuid4(),
        model_job_version=1,
        requested_by=requested_by,
        profile_version_id=runtime.profile_version_id,
        profile_id=uuid4(),
        version_number=1,
        channel="reddit",
        locale="en-AU",
        corpus_hash=_hash("corpus-v1"),
        approved_sample_count=200,
        sample_manifest_hash=_hash("sample-manifest-v1"),
        sample_style_evidence=(
            FrozenEvidence(
                ref="sample-manifest:1",
                subject_id="style:reddit",
                summary="Approved anonymous Australian English style evidence.",
            ),
        ),
        runtime_inputs=runtime,
        prompt=prompt,
    )


def _assert_persisted_guards(
    database: _Database,
    task: StyleProfileBuildTask,
    output: StyleProfileBuildOutput,
) -> None:
    with psycopg.connect(database.app_url) as connection:
        set_project_scope(connection, task.project_id)
        row = connection.execute(
            """SELECT job.status, job.result_ref,
                      (SELECT count(*) FROM synthetic_lab_execution_results),
                      (SELECT count(*) FROM synthetic_lab_terminal_results)
               FROM durable_jobs AS job WHERE job.id = %s""",
            (task.job_id,),
        ).fetchone()
        assert row == (
            "succeeded",
            f"synthetic://result/{output.result_hash}",
            1,
            1,
        )
    with psycopg.connect(database.app_url) as connection:
        set_project_scope(connection, database.second["project"])
        assert connection.execute(
            "SELECT count(*) FROM synthetic_lab_authorization_versions"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM synthetic_lab_execution_results"
        ).fetchone()[0] == 0
    with psycopg.connect(database.admin_url) as admin:
        assert admin.execute(
            """SELECT has_table_privilege(
                   'geo_readonly', 'synthetic_lab_terminal_results', 'SELECT'
               )"""
        ).fetchone()[0] is False
        with pytest.raises(psycopg.Error, match="immutable"):
            admin.execute(
                """UPDATE synthetic_lab_execution_results SET result_hash = %s
                   WHERE project_id = %s AND job_id = %s""",
                ("0" * 64, task.project_id, task.job_id),
            )
        admin.rollback()


def _assert_unstaged_execution_fails_closed(
    database: _Database,
    persistence: object,
    runtime: RuntimeInputSnapshot,
) -> None:
    job_id = uuid4()
    job = new_synthetic_job(
        job_id=job_id,
        project_id=runtime.project_id,
        kind="style_profile_build",
        input_hash=_hash("unstaged-job"),
        idempotency_key_hash=_hash("unstaged-job-idempotency"),
        payload={"profile_version_id": runtime.profile_version_id},
        runtime_inputs=runtime,
    )
    with persistence.uow_factory(project_id=runtime.project_id) as unit_of_work:  # type: ignore[attr-defined]
        unit_of_work.jobs.stage(job, expected_version=0)
        unit_of_work.commit()
    store = PostgresDurableJobStore(
        lambda: psycopg.connect(database.worker_url, row_factory=dict_row)
    )
    claim = store.claim(
        job_id=job_id,
        project_id=runtime.project_id,
        expected_kind="style.profile.build",
        worker_id="synthetic-unstaged-worker",
        lease_for=timedelta(minutes=1),
    )
    assert claim.lease is not None
    repository = build_synthetic_execution_repository(database.worker_url)
    with pytest.raises(SyntheticExecutionError, match="no frozen executable task"):
        repository.load(claim.lease)


def _outbox_id(app_url: str, project_id: UUID, job_id: UUID) -> UUID:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        return connection.execute(
            """SELECT id FROM synthetic_lab_outbox_messages
               WHERE project_id = %s AND job_id = %s""",
            (project_id, job_id),
        ).fetchone()[0]


def _principal(ids: dict[str, UUID], identity: str, role: LabRole) -> LabPrincipal:
    return LabPrincipal(
        project_id=ids["project"],
        actor_id=ids[identity],
        roles=frozenset({role}),
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _database_url(database_url: str, database_name: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
