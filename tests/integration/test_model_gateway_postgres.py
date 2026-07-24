from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.jobs.lifecycle import JobStatus
from geo_core.model_gateway import (
    AdapterRelease,
    ModelAudience,
    ModelCallBudget,
    ModelCallBudgetExceeded,
    ModelGatewayErrorCode,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
    ModelRoute,
)
from geo_core.model_gateway.application import ModelCallApplication, ReconcileModelCall
from geo_core.model_gateway.application_support import ModelCallUnknownOutcome, empty_lineage
from geo_core.model_gateway.ports import (
    ModelCallIdempotencyConflict,
    ModelCallJobAdmission,
    ModelCallPersistenceError,
    ModelCallTerminalStatus,
    canonical_json_hash,
)
from geo_core.model_gateway.postgres import build_model_gateway_persistence
from geo_core.model_gateway.provider_adapters.artifacts import MinioProviderArtifactSink
from geo_core.project_scope import set_project_scope
from geo_core.secrets import SecretValue
from tests.integration.model_gateway_postgres_fixtures import (
    RAW_REFERENCE,
    SECRET_MARKER,
    active_provider_secret as _active_provider_secret,
    frozen_prompt as _frozen_prompt,
    model_command as _command,
    model_result as _result,
    register_openai_runtime as _register_openai_runtime,
    running_job as _running_job,
)
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.model_gateway_postgres_support import (
    attach_provider_artifacts,
    assert_terminal_shape_guards,
    provider_artifact_sink,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


class SequenceGateway:
    def __init__(
        self,
        actions: list[ModelGatewayResult | Exception],
        *,
        artifact_sink: MinioProviderArtifactSink,
        adapter: AdapterRelease,
    ) -> None:
        self.actions = actions
        self.artifact_sink = artifact_sink
        self.adapter = adapter
        self.calls = 0

    def generate(
        self,
        route: ModelRoute,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        del policy
        self.calls += 1
        budget.consume()
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return attach_provider_artifacts(
            sink=self.artifact_sink,
            route=route,
            adapter=self.adapter,
            request=request,
            result=action,
        )


def test_model_gateway_postgres_exact_call_lifecycle_and_guards(tmp_path: Path) -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_model_gateway_{suffix}"
    test_admin_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_model_gateway_{suffix}", uuid4().hex
    role_created = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = test_admin_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0028_secret_store")
        alembic_command.upgrade(migration, "head")

        with psycopg.connect(test_admin_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            role_created = True
            first = seed_project(admin, suffix=f"model-gateway-{suffix}-a")
            second = seed_project(admin, suffix=f"model-gateway-{suffix}-b")
        app_url = login_url(test_admin_url, user=app_login, password=password)
        secret_api, secret_handle = _active_provider_secret(
            app_url=app_url,
            ids=first,
            directory=tmp_path,
        )
        prompt, schema = _frozen_prompt(app_url, first)
        persistence = build_model_gateway_persistence(app_url)
        assert persistence is not None
        assert persistence.require_active_provider_secret_handle(
            first["project"], "openai", secret_handle.reference_id
        ) == secret_handle

        now = datetime.now(UTC)
        runtime = _register_openai_runtime(
            app_url=app_url,
            ids=first,
            provider_secret_handle=secret_handle,
            approved_at=now,
        )
        adapter, model, route = runtime.adapter, runtime.model, runtime.route
        selection = runtime.selection
        assert persistence.load_release_registry().resolve(route) == (adapter, model)
        policy = selection.policy
        assert policy.policy_version_id is not None
        assert policy.policy_version_hash is not None
        assert (
            persistence.get_project_policy(
                project_id=first["project"],
                policy_version_id=policy.policy_version_id,
                policy_version_hash=policy.policy_version_hash,
            )
            == policy
        )

        job_id, lease_token = uuid4(), uuid4()
        _running_job(
            app_url,
            project_id=first["project"],
            job_id=job_id,
            lease_token=lease_token,
            now=now,
        )
        job = ModelCallJobAdmission(
            project_id=first["project"],
            job_id=job_id,
            job_kind="model.gateway.integration",
            job_version=1,
            admission_mode=prompt.admission_mode,
            status=JobStatus.RUNNING,
            lease_token=lease_token,
            fencing_generation=1,
            purpose=prompt.purpose,
            usage_audience=ModelAudience.INTERNAL_WORKER,
            route=route,
            runtime_manifest_id=selection.runtime_manifest_id,
            runtime_manifest_hash=selection.runtime_manifest_hash,
            runtime_option_id=selection.runtime_option_id,
            runtime_option_hash=selection.runtime_option_hash,
            provider_secret_handle=selection.provider_secret_handle,
            prompt_binding_id=prompt.binding_id,
            prompt_release_id=prompt.release_id,
            prompt_release_hash=prompt.release_hash,
            prompt_state_id=prompt.state_id,
            prompt_state_version=prompt.state_version,
            prompt_test_set_hash=prompt.test_set_hash,
            prompt_bundle_hash="b" * 64,
            output_schema_hash=canonical_json_hash(schema),
            application_output_schema_hash=canonical_json_hash(schema),
            policy_version_id=policy.policy_version_id,
            policy_version_hash=policy.policy_version_hash,
            maximum_paid_calls=4,
            maximum_concurrent_calls=1,
            raw_artifact_policy_hash=adapter.data_policy_hash,
            raw_artifact_storage_decision=adapter.data_policy.storage.value,
            raw_artifact_cache_decision=adapter.data_policy.cache.value,
            raw_artifact_display_decision=adapter.data_policy.display.value,
            raw_artifact_redistribution_decision=(
                adapter.data_policy.redistribution.value
            ),
            raw_artifact_retention_days=adapter.data_policy.retention_days,
        )
        persistence.admit_job(
            job,
            prompt=prompt,
            admitted_by=first["reviewer"],
            admitted_at=now,
        )
        assert persistence.load_job_admission(first["project"], job_id) == job
        assert persistence.admit_job(
            job,
            prompt=prompt,
            admitted_by=first["reviewer"],
            admitted_at=now,
        ).job_id == job_id
        with pytest.raises(ModelCallPersistenceError, match="different frozen content"):
            persistence.admit_job(
                replace(job, maximum_concurrent_calls=2),
                prompt=prompt,
                admitted_by=first["reviewer"],
                admitted_at=now,
            )

        secret_api.stage_rotation(
            _principal(first, "owner"),
            project_id=first["project"],
            reference_id=secret_handle.reference_id,
            value=SecretValue("model-gateway-provider-key-v2"),
            expected_version=3,
            idempotency_key="model-gateway-secret-stage-v2",
        )
        secret_api.verify(
            _principal(first, "owner"),
            project_id=first["project"],
            reference_id=secret_handle.reference_id,
            version=2,
            expected_version=4,
            idempotency_key="model-gateway-secret-verify-v2",
        )
        secret_api.activate(
            _principal(first, "reviewer"),
            project_id=first["project"],
            reference_id=secret_handle.reference_id,
            version=2,
            expected_version=5,
            idempotency_key="model-gateway-secret-activate-v2",
        )

        successful_result = _result(adapter, model)
        gateway = SequenceGateway(
            [
                successful_result,
                RuntimeError("provider socket outcome is unknown"),
                successful_result,
                RuntimeError("second provider socket outcome is unknown"),
            ],
            artifact_sink=provider_artifact_sink(
                database_url=test_admin_url,
                directory=tmp_path,
            ),
            adapter=adapter,
        )
        application = ModelCallApplication(
            gateway=gateway,
            release_registry=persistence.load_release_registry(),
            uow_factory=persistence.uow_factory,
        )
        base = _command(
            project_id=first["project"],
            job_id=job_id,
            lease_token=lease_token,
            route=route,
            runtime_manifest_id=selection.runtime_manifest_id,
            runtime_manifest_hash=selection.runtime_manifest_hash,
            runtime_option_id=selection.runtime_option_id,
            runtime_option_hash=selection.runtime_option_hash,
            prompt=prompt,
            schema=schema,
            model=model,
            provider_secret_handle=secret_handle,
            idempotency_key="model-call-success-1",
        )

        first_result = application.execute(base, policy=policy)
        first_replay = application.execute(base, policy=policy)
        assert first_result.replayed is False
        assert first_replay.replayed is True
        assert gateway.calls == 1
        with pytest.raises(ModelCallIdempotencyConflict):
            application.execute(
                replace(
                    base,
                    request=replace(
                        base.request,
                        messages=({"role": "user", "content": "changed input"},),
                    ),
                ),
                policy=policy,
            )

        unknown = replace(base, attempt_idempotency_key="model-call-unknown-2")
        with pytest.raises(ModelCallUnknownOutcome) as captured:
            application.execute(unknown, policy=policy)
        blocked = replace(base, attempt_idempotency_key="model-call-concurrency-blocked")
        with pytest.raises(ModelCallBudgetExceeded, match="concurrent"):
            application.execute(blocked, policy=policy)
        assert gateway.calls == 2

        with persistence.uow_factory(project_id=first["project"]) as unit_of_work:
            unknown_attempt = unit_of_work.calls.get_attempt(
                project_id=first["project"], attempt_id=captured.value.attempt_id
            )
        assert unknown_attempt is not None
        application.reconcile(
            ReconcileModelCall(
                project_id=first["project"],
                attempt_id=unknown_attempt.spec.id,
                expected_budget_version=3,
                idempotency_key="reconcile-model-call-unknown-2",
                status=ModelCallTerminalStatus.FAILED,
                paid_call_consumed=True,
                reconciled_by=first["reviewer"],
                evidence_ref="operator:provider-console:unknown-call-paid",
                lineage=empty_lineage(unknown_attempt),
                provider_reported_model=model.configured_model,
                error_code=ModelGatewayErrorCode.TIMEOUT,
                error_retryable=False,
            )
        )
        final = application.execute(blocked, policy=policy)
        assert final.terminal_event.status is ModelCallTerminalStatus.SUCCEEDED
        assert gateway.calls == 3

        shape_probe = replace(base, attempt_idempotency_key="model-call-shape-probe-4")
        with pytest.raises(ModelCallUnknownOutcome) as shape_unknown:
            application.execute(shape_probe, policy=policy)
        assert_terminal_shape_guards(
            app_url=app_url,
            project_id=first["project"],
            job_id=job_id,
            attempt_id=shape_unknown.value.attempt_id,
            actor_id=first["reviewer"],
        )
        with persistence.uow_factory(project_id=first["project"]) as unit_of_work:
            shape_attempt = unit_of_work.calls.get_attempt(
                project_id=first["project"], attempt_id=shape_unknown.value.attempt_id
            )
        assert shape_attempt is not None
        application.reconcile(
            ReconcileModelCall(
                project_id=first["project"],
                attempt_id=shape_attempt.spec.id,
                expected_budget_version=7,
                idempotency_key="reconcile-model-call-shape-probe-4",
                status=ModelCallTerminalStatus.FAILED,
                paid_call_consumed=False,
                reconciled_by=first["reviewer"],
                evidence_ref="operator:provider-console:shape-probe-not-charged",
                lineage=empty_lineage(shape_attempt),
                error_code=ModelGatewayErrorCode.CONFIGURATION,
                error_retryable=False,
            )
        )
        assert gateway.calls == 4

        secret_api.revoke(
            _principal(first, "reviewer"),
            project_id=first["project"],
            reference_id=secret_handle.reference_id,
            version=1,
            expected_version=6,
            idempotency_key="model-gateway-secret-revoke-v1",
        )
        with pytest.raises(ModelCallPersistenceError):
            application.execute(
                replace(base, attempt_idempotency_key="model-call-revoked-secret"),
                policy=policy,
            )
        assert gateway.calls == 4

        _assert_persisted_contracts(
            app_url=app_url,
            admin_url=test_admin_url,
            first=first,
            second=second,
            adapter=adapter,
            job_id=job_id,
        )
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
            if role_created:
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login))
                )


def _assert_persisted_contracts(
    *,
    app_url: str,
    admin_url: str,
    first: dict[str, UUID],
    second: dict[str, UUID],
    adapter: AdapterRelease,
    job_id: UUID,
) -> None:
    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, first["project"])
        counts = connection.execute(
            """SELECT
                 (SELECT count(*) FROM model_gateway_call_attempts),
                 (SELECT count(*) FROM model_gateway_terminal_events),
                 (SELECT paid_calls FROM model_gateway_job_admissions WHERE job_id = %s),
                 (SELECT reserved_calls FROM model_gateway_job_admissions WHERE job_id = %s)""",
            (job_id, job_id),
        ).fetchone()
        assert counts == (4, 4, 3, 0)
        persisted = str(
            connection.execute(
                """SELECT row_to_json(attempt), row_to_json(event)
                   FROM model_gateway_call_attempts AS attempt
                   JOIN model_gateway_terminal_events AS event
                     ON event.attempt_id = attempt.id
                   ORDER BY attempt.attempt_number"""
            ).fetchall()
        )
        assert SECRET_MARKER not in persisted
        assert RAW_REFERENCE not in persisted
        artifact_lineage = connection.execute(
            """SELECT artifact.manifest_uri, event.raw_artifact_reference_hash
               FROM model_gateway_artifacts AS artifact
               JOIN model_gateway_artifact_bundles AS bundle
                 ON bundle.id = artifact.bundle_id AND bundle.project_id = artifact.project_id
               JOIN model_gateway_terminal_events AS event
                 ON event.id = bundle.terminal_event_id AND event.project_id = bundle.project_id
               WHERE artifact.kind = 'raw'
               ORDER BY bundle.staged_at"""
        ).fetchall()
        assert len(artifact_lineage) == 2
        assert all(
            hashlib.sha256(uri.encode()).hexdigest() == reference_hash
            for uri, reference_hash in artifact_lineage
        )
        assert connection.execute(
            """SELECT
                 (SELECT count(*) FROM model_gateway_artifact_bundles
                  WHERE status = 'committed'),
                 (SELECT count(*) FROM model_gateway_artifacts),
                 (SELECT count(*) FROM model_gateway_artifact_deks
                  WHERE status = 'active')"""
        ).fetchone() == (2, 4, 4)
        with pytest.raises(psycopg.Error, match="budget counters"):
            connection.execute(
                """UPDATE model_gateway_job_admissions
                   SET reserved_calls = reserved_calls + 1,
                       budget_version = budget_version + 1,
                       next_attempt_number = next_attempt_number + 1
                   WHERE project_id = %s AND job_id = %s""",
                (first["project"], job_id),
            )
            connection.commit()
        connection.rollback()

    with psycopg.connect(app_url) as connection:
        set_project_scope(connection, second["project"])
        assert connection.execute(
            "SELECT count(*) FROM model_gateway_job_admissions"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM model_gateway_call_attempts"
        ).fetchone()[0] == 0

    with psycopg.connect(admin_url) as admin:
        with pytest.raises(psycopg.Error, match="immutable"):
            admin.execute(
                """UPDATE model_gateway_adapter_releases
                   SET release_hash = %s
                   WHERE provider = %s AND adapter_release_id = %s""",
                ("0" * 64, adapter.provider, adapter.adapter_release_id),
            )
        admin.rollback()
        assert admin.execute(
            """SELECT has_table_privilege(
                   'geo_readonly', 'model_gateway_terminal_events', 'SELECT'
               )"""
        ).fetchone()[0] is False


def _principal(ids: dict[str, UUID], identity: str) -> AccessPrincipal:
    identity_id = ids[identity]
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=ids["tenant"],
        memberships=(MembershipRecord(ids["project"], ids["tenant"], "admin"),),
        auth_method="integration",
    )


def _database_url(database_url: str, database_name: str) -> str:
    parsed = urlsplit(database_url)
    return urlunsplit(parsed._replace(path=f"/{database_name}"))
