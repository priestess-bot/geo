from __future__ import annotations

from datetime import timedelta
import hashlib
import os
import sys
from uuid import UUID, uuid4, uuid5

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.model_gateway.contracts import ModelCaptureMethod, ModelPolicy
from geo_core.model_gateway.releases import ModelRoute
from geo_core.object_store import RetrievedObject, StoredObject
from geo_core.project_scope import set_project_scope
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_spec
from geo_core.prompts.bootstrap_contracts import EvalScenario, thaw_mapping
from geo_core.prompts.compiler_versions import BOOTSTRAP_COMPILER_VERSION
from geo_core.prompts.postgres import build_prompt_program_api
from geo_core.prompts.program import ProgramKind, ProgramReleaseStatus
from geo_core.prompts.test_artifacts import S3PromptTestArtifactStore
from geo_core.prompts.test_execution_contracts import (
    PROMPT_TEST_JOB_KIND,
    PROMPT_TEST_MAXIMUM_PAID_CALLS,
    PromptTestCaseModelResult,
    PromptTestModelSelection,
    PromptTestRouteRequest,
    PromptTestRuntimeOption,
)
from geo_core.prompts.test_execution_repository import (
    build_prompt_test_execution_repository,
)
from geo_core.prompts.test_worker import PromptTestExecutionHandler
from geo_core.secrets.models import SecretVersionHandle
from tests.integration.placement_worker_support import (
    cleanup_projects,
    login_url,
    seed_project,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_prompt_test_enqueue_worker_evidence_and_approval_are_one_frozen_chain() -> None:
    suffix = uuid4().hex[:10]
    app_login, app_password = f"geo_prompt_run_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_prompt_worker_{suffix}", uuid4().hex
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                sql.Identifier(app_login), sql.Literal(app_password)
            )
        )
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                sql.Identifier(worker_login), sql.Literal(worker_password)
            )
        )
        first = seed_project(admin, suffix=f"prompt-run-{suffix}-a")
        second = seed_project(admin, suffix=f"prompt-run-{suffix}-b")
    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    objects = _Objects()
    selection = _selection(first["project"])
    selector = _Selector(selection)
    api = build_prompt_program_api(
        database_url=app_url,
        runtime_selector=selector,
        test_object_store=objects,
    )
    owner = _principal(first, "owner")
    reviewer = _principal(first, "reviewer")
    spec = default_prompt_bootstrap_spec(ProgramKind.RECOMMENDATION)
    try:
        created = api.create_program(
            owner,
            project_id=first["project"],
            program_kind=spec.program_kind,
            purpose=spec.purpose,
            system_template=spec.system_template,
            user_template=spec.user_template,
            schemas=spec.schemas,
            model_policy=spec.model_policy,
            test_set_id=spec.test_set_id,
            test_set_version=1,
            test_set_hash=spec.test_set_hash,
            compiler_version=BOOTSTRAP_COMPILER_VERSION,
            expected_version=0,
            idempotency_key="prompt-run-create-v1",
        )
        options = api.list_test_runtimes(
            owner,
            project_id=first["project"],
        )
        assert len(options) == 1
        assert options[0].runtime_selection_id == selection.runtime_selection_id

        receipt = api.enqueue_test(
            owner,
            project_id=first["project"],
            program_id=created.value.program.id,
            release_id=created.value.release.id,
            test_set_id=spec.test_set_id,
            test_set_version=1,
            test_set_hash=spec.test_set_hash,
            route=PromptTestRouteRequest(selection.runtime_selection_id),
            expected_version=1,
            idempotency_key="prompt-run-test-v1",
        )
        replay = api.enqueue_test(
            owner,
            project_id=first["project"],
            program_id=created.value.program.id,
            release_id=created.value.release.id,
            test_set_id=spec.test_set_id,
            test_set_version=1,
            test_set_hash=spec.test_set_hash,
            route=PromptTestRouteRequest(selection.runtime_selection_id),
            expected_version=1,
            idempotency_key="prompt-run-test-v1",
        )
        assert receipt.replayed is False
        assert replay.replayed is True and replay.value == receipt.value
        _assert_frozen_admission(
            app_url=app_url,
            project_id=first["project"],
            job_id=receipt.value.id,
            selection=selection,
        )

        def connect_worker():
            return psycopg.connect(worker_url, row_factory=dict_row)

        store = PostgresDurableJobStore(connect_worker)
        claimed = store.claim(
            job_id=receipt.value.id,
            project_id=first["project"],
            expected_kind=PROMPT_TEST_JOB_KIND,
            worker_id="prompt-test-integration-worker",
            lease_for=timedelta(minutes=2),
        )
        assert claimed.disposition == "claimed" and claimed.lease is not None
        handler = _FailFastPromptTestExecutionHandler(
            store=store,
            repository=build_prompt_test_execution_repository(worker_url),
            executor=_PassingCaseExecutor(),
            artifacts=S3PromptTestArtifactStore(objects),
            lease_for=timedelta(minutes=2),
        )
        result = handler.handle(claimed.lease)
        assert result["status"] == "succeeded", _job_state(
            app_url=app_url,
            project_id=first["project"],
            job_id=receipt.value.id,
        )
        assert result["passed"] is True and result["score"] == 100

        tested = api.get_release(
            owner,
            project_id=first["project"],
            program_id=created.value.program.id,
            release_id=created.value.release.id,
        )
        assert tested.state.status is ProgramReleaseStatus.TESTED
        approved = api.approve_release(
            reviewer,
            project_id=first["project"],
            program_id=created.value.program.id,
            release_id=created.value.release.id,
            expected_version=2,
            idempotency_key="prompt-run-approve-v1",
        )
        assert approved.value.state.status is ProgramReleaseStatus.APPROVED
        assert approved.value.admitted_test_evidence is not None
        assert approved.value.admitted_test_evidence.output_artifact_ref in objects.values
        _assert_other_project_cannot_read_prompt_run(
            app_url=app_url,
            project_id=second["project"],
        )
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[first, second],
                tenant_ids=[first["tenant"], second["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )


class _Selector:
    def __init__(self, selection: PromptTestModelSelection) -> None:
        self.selection = selection

    def select(
        self,
        *,
        project_id: UUID,
        request: PromptTestRouteRequest,
    ) -> PromptTestModelSelection:
        assert project_id == self.selection.provider_secret_handle.project_id
        assert request.runtime_selection_id == self.selection.runtime_selection_id
        return self.selection

    def list_approved(self, *, project_id: UUID) -> tuple[PromptTestRuntimeOption, ...]:
        assert project_id == self.selection.provider_secret_handle.project_id
        selected = self.selection
        route = selected.route
        return (
            PromptTestRuntimeOption(
                runtime_selection_id=selected.runtime_selection_id,
                runtime_selection_hash=selected.runtime_selection_hash,
                runtime_manifest_id=selected.runtime_manifest_id,
                runtime_manifest_hash=selected.runtime_manifest_hash,
                provider=route.provider,
                adapter_release_id=route.adapter_release_id,
                adapter_release_hash=route.adapter_release_hash,
                model_release_id=route.model_release_id,
                model_release_hash=route.model_release_hash,
                configured_model=selected.configured_model,
                capture_method=selected.capture_method,
                policy_version_id=selected.policy_version_id,
                policy_version_hash=selected.policy_version_hash,
            ),
        )


class _PassingCaseExecutor:
    def execute(self, **values) -> PromptTestCaseModelResult:
        task = values["task"]
        fixture_id = values["fixture_id"]
        fixture_hash = values["fixture_hash"]
        fixture = next(
            item for item in task.test_spec.fixtures if item.fixture_id == fixture_id
        )
        positive = next(
            item
            for item in task.test_spec.fixtures
            if item.scenario is EvalScenario.POSITIVE
        )
        output_source = (
            fixture
            if fixture.scenario is EvalScenario.PROMPT_INJECTION
            else positive
        )
        return PromptTestCaseModelResult(
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            model_call_id=uuid5(task.job_id, fixture_id),
            response_hash=fixture_hash,
            output=thaw_mapping(output_source.expected_output),
        )


class _FailFastPromptTestExecutionHandler(PromptTestExecutionHandler):
    def _fail(self, *args, **kwargs):
        error = sys.exception()
        if error is not None:
            raise error
        return super()._fail(*args, **kwargs)


class _Objects:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def put_object(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        expected_hash: str,
    ) -> StoredObject:
        digest = hashlib.sha256(content).hexdigest()
        assert digest == expected_hash
        uri = f"s3://geo-artifacts/{key}"
        self.values[uri] = content
        return StoredObject(
            uri,
            "geo-artifacts",
            key,
            content_type,
            digest,
            "prompt-test-integration-etag",
        )

    def get_s3_uri(
        self,
        *,
        uri: str,
        expected_hash: str | None = None,
    ) -> RetrievedObject:
        content = self.values[uri]
        digest = hashlib.sha256(content).hexdigest()
        assert expected_hash is None or digest == expected_hash
        return RetrievedObject(
            content,
            "geo-artifacts",
            uri.removeprefix("s3://geo-artifacts/"),
            "application/json",
            digest,
            "prompt-test-integration-etag",
        )


def _selection(project_id: UUID) -> PromptTestModelSelection:
    policy_id = uuid4()
    policy = ModelPolicy(
        allowed_providers=frozenset({"openai"}),
        allowed_adapter_release_ids=frozenset({"openai-prompt-test-v1"}),
        policy_version_id=policy_id,
        maximum_paid_calls=PROMPT_TEST_MAXIMUM_PAID_CALLS,
        maximum_concurrent_calls=1,
    )
    assert policy.policy_version_hash is not None
    return PromptTestModelSelection(
        runtime_selection_id=uuid4(),
        runtime_selection_hash="1" * 64,
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash="2" * 64,
        route=ModelRoute(
            "openai",
            "openai-prompt-test-v1",
            "3" * 64,
            "openai-prompt-test-model-v1",
            "4" * 64,
        ),
        configured_model="openai-prompt-test-model",
        capture_method=ModelCaptureMethod.PROVIDER_API,
        policy_version_id=policy_id,
        policy_version_hash=policy.policy_version_hash,
        policy=policy,
        provider_secret_handle=SecretVersionHandle(
            reference_id=uuid4(),
            project_id=project_id,
            purpose="model_provider.openai",
            version=1,
        ),
    )


def _assert_frozen_admission(
    *,
    app_url: str,
    project_id: UUID,
    job_id: UUID,
    selection: PromptTestModelSelection,
) -> None:
    with psycopg.connect(app_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        row = connection.execute(
            """SELECT job.kind, job.status, job.input_hash, task.task_payload,
                      task.task_payload_hash,
                      (SELECT count(*) FROM broker_outbox WHERE job_id = job.id) AS outbox_count
               FROM durable_jobs AS job
               JOIN prompt_program_test_run_tasks AS task
                 ON task.project_id = job.project_id AND task.job_id = job.id
               WHERE job.project_id = %s AND job.id = %s""",
            (project_id, job_id),
        ).fetchone()
        assert row is not None
        assert row["kind"] == PROMPT_TEST_JOB_KIND and row["status"] == "queued"
        assert row["input_hash"] == row["task_payload_hash"]
        assert row["outbox_count"] == 1
        payload = row["task_payload"]
        assert payload["model"]["runtime_selection_id"] == str(
            selection.runtime_selection_id
        )
        assert payload["model"]["runtime_selection_hash"] == (
            selection.runtime_selection_hash
        )
        persisted = str(payload).casefold()
        assert "plaintext" not in persisted and "credential" not in persisted


def _assert_other_project_cannot_read_prompt_run(
    *,
    app_url: str,
    project_id: UUID,
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, project_id)
        assert connection.execute(
            "SELECT count(*) FROM prompt_program_test_run_tasks"
        ).fetchone()[0] == 0


def _job_state(*, app_url: str, project_id: UUID, job_id: UUID):
    with psycopg.connect(app_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        return connection.execute(
            """SELECT status, error_code, error_detail
               FROM durable_jobs WHERE project_id = %s AND id = %s""",
            (project_id, job_id),
        ).fetchone()


def _principal(ids: dict[str, UUID], identity: str):
    from geo_core.access.models import AccessPrincipal, MembershipRecord

    identity_id = ids[identity]
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=ids["tenant"],
        memberships=(
            MembershipRecord(ids["project"], ids["tenant"], "admin"),
        ),
        auth_method="integration",
    )
