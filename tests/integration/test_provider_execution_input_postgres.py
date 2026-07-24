from __future__ import annotations

from datetime import UTC, datetime, timedelta
from dataclasses import replace
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4, uuid5

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
    EnqueueReadySamplingRunRequest,
    StartSamplingRunRequest,
)
from geo_api.workflow_c_sampling_postgres_execution import (
    PostgresWorkflowCProviderBulkSamplingControl,
    spec_payload,
)
from geo_api.workflow_c_sampling_postgres_runtime import (
    build_postgres_workflow_c_sampling_runtime,
)
from geo_api.workflow_c_manual_artifacts import UnavailableManualArtifactWriter
from geo_api.workflow_c_sampling_postgres_policy import (
    PostgresWorkflowCSamplingPolicyControl,
)
from geo_core.project_scope import set_project_scope
from geo_core.sampling import (
    CaptureMethod,
    LocationControl,
    PersistentProviderSamplingExecutionInput,
    ProviderSamplingExecutionInputRetirement,
    PersistentSamplingSuiteInput,
    PostgresProviderSamplingBulkAttemptRepository,
    PostgresProviderSamplingExecutionInputError,
    PostgresProviderSamplingExecutionInputRepository,
    PostgresSamplingReadRepository,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteError,
    PostgresSamplingSuiteRepository,
    ProviderSamplingBulkAttemptAdmission,
    ProviderSamplingBulkAttemptItem,
    ProviderSamplingExecutionInput,
    SamplingConflict,
    SamplingQuestion,
    SamplingSourceStratum,
    SamplingSuite,
)
from geo_core.sampling.postgres_admission import PostgresSamplingAdmissionRepository
from geo_core.sampling.postgres_suites import SAMPLING_SUITE_INPUT_NAMESPACE
from geo_api.workflow_c_sampling_postgres_run import PostgresWorkflowCSamplingRunControl
from tests.integration.placement_worker_support import login_url, seed_project


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
NOW = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_provider_execution_input_is_scoped_immutable_and_bound_to_a_new_suite() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_provider_execution_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_provider_execution_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as connection:
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_role = True
            project = seed_project(connection, suffix=f"provider-execution-{suffix}")
            _seed_runtime_option(connection, project_id=project["project"])
            connection.commit()

        app_url = login_url(database_url, user=app_login, password=app_password)
        policy = _approved_policy(app_url, project["project"])
        input_option = _suite_input(project["project"], policy.id, policy.definition_hash)
        suite_repository = PostgresSamplingSuiteRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        assert suite_repository.register_input(
            input_option, idempotency_key="suite-input:first"
        ) == input_option

        execution_repository = PostgresProviderSamplingExecutionInputRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        execution = PersistentProviderSamplingExecutionInput(
            project_id=project["project"],
            suite_input_option_id=input_option.id,
            suite_input_option_hash=input_option.option_hash,
            execution=ProviderSamplingExecutionInput.from_payload(_execution_payload()),
            frozen_at=NOW,
        )
        assert execution_repository.register(
            execution, idempotency_key="provider-execution-input:first"
        ) == execution
        assert execution_repository.register(
            execution, idempotency_key="provider-execution-input:first"
        ) == execution

        suite = _suite(input_option)
        assert suite_repository.create_suite(
            suite, input_option=input_option, idempotency_key="suite:first"
        ) == suite
        assert execution_repository.get_for_suite(
            project_id=project["project"], suite_id=suite.id
        ) == execution
        runtime = build_postgres_workflow_c_sampling_runtime(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row),
            artifact_writer=UnavailableManualArtifactWriter(),
            clock=lambda: NOW,
        )
        assert runtime.get_suite(project_id=project["project"], suite_id=suite.id) == suite
        assert runtime.list_suites(project_id=project["project"]) == (suite,)
        unbound_input = replace(
            input_option,
            id=uuid5(
                SAMPLING_SUITE_INPUT_NAMESPACE,
                f"{project['project']}:provider-au-unbound",
            ),
            option_key="provider-au-unbound",
            display_name="Provider AU unbound",
            question_set_hash=_hash("question-set-unbound"),
        )
        assert suite_repository.register_input(
            unbound_input, idempotency_key="suite-input:unbound"
        ) == unbound_input
        with pytest.raises(PostgresSamplingSuiteError, match="no frozen execution input"):
            suite_repository.create_suite(
                _suite(unbound_input),
                input_option=unbound_input,
                idempotency_key="suite:unbound",
            )
        retirement = ProviderSamplingExecutionInputRetirement(
            project_id=project["project"],
            suite_input_option_id=input_option.id,
            execution_input_hash=execution.execution_input_hash,
            expected_version=1,
            actor_id="provider-execution-reviewer",
            reason="provider_decommissioned",
            retired_at=NOW + timedelta(minutes=1),
        )
        retired = replace(
            execution,
            status="retired",
            aggregate_version=2,
            retired_at=retirement.retired_at,
            retired_by=retirement.actor_id,
            retirement_reason=retirement.reason,
        )
        with pytest.raises(
            PostgresProviderSamplingExecutionInputError,
            match="retirement reason is invalid",
        ):
            execution_repository.retire(
                replace(retirement, reason="api_key=must-not-persist"),
                idempotency_key="provider-execution-input:unsafe-reason",
            )
        assert execution_repository.retire(
            retirement, idempotency_key="provider-execution-input:retire"
        ) == retired
        assert execution_repository.retire(
            retirement, idempotency_key="provider-execution-input:retire"
        ) == retired
        assert execution_repository.get_for_suite(
            project_id=project["project"], suite_id=suite.id
        ) == retired
        with pytest.raises(PostgresSamplingSuiteError, match="no frozen execution input"):
            suite_repository.create_suite(
                _suite(input_option),
                input_option=input_option,
                idempotency_key="suite:retired-input",
            )

        policies = PostgresWorkflowCSamplingPolicyControl(
            repository=PostgresSamplingAdmissionRepository(
                connect=lambda: psycopg.connect(app_url, row_factory=dict_row),
                clock=lambda: NOW,
            ),
            clock=lambda: NOW,
        )
        runs = PostgresSamplingRunRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        run, _ = PostgresWorkflowCSamplingRunControl(
            runs=runs,
            suites=suite_repository,
            policies=policies,
            clock=lambda: NOW,
        ).start_run(
            project_id=project["project"],
            suite_id=suite.id,
            idempotency_key="run:retired-input",
            payload=StartSamplingRunRequest(
                purpose="geo_measurement", requested_not_before=NOW
            ),
        )
        enqueued = PostgresWorkflowCProviderBulkSamplingControl(
            runs=runs,
            suites=suite_repository,
            execution_inputs=execution_repository,
            attempts=PostgresProviderSamplingBulkAttemptRepository(
                connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
            ),
            policies=policies,
            clock=lambda: NOW,
        ).enqueue_ready(
            project_id=project["project"],
            run_id=run.id,
            idempotency_key="bulk:retired-input",
            payload=EnqueueReadySamplingRunRequest(
                requested_not_before=NOW + timedelta(minutes=2), max_tasks=1
            ),
        )
        assert enqueued.enqueued_count == 1
        with psycopg.connect(app_url) as connection:
            set_project_scope(connection, project["project"])
            assert not _boolean(
                connection,
                """SELECT has_table_privilege(
                       current_user,
                       'workflow_c_sampling_provider_execution_inputs',
                       'INSERT'
                   )""",
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """INSERT INTO workflow_c_sampling_provider_execution_inputs(
                           project_id, suite_input_option_id, suite_input_option_hash,
                           execution_input_hash, payload, status, frozen_at
                       ) VALUES (%s, %s, %s, %s, %s::jsonb, 'approved', %s)""",
                    (
                        execution.project_id,
                        execution.suite_input_option_id,
                        execution.suite_input_option_hash,
                        execution.execution_input_hash,
                        Jsonb(execution.execution.payload()),
                        NOW,
                    ),
                )
            connection.rollback()
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """UPDATE workflow_c_sampling_provider_execution_inputs
                          SET status = 'approved'
                        WHERE project_id = %s AND suite_input_option_id = %s""",
                    (execution.project_id, execution.suite_input_option_id),
                )
            connection.rollback()
        with pytest.raises(Exception, match="retirement evidence exists"):
            alembic_command.downgrade(migration, "0056_sampling_cancel_lineage")
    finally:
        if created_role:
            with psycopg.connect(database_url, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    """SELECT pg_terminate_backend(pid)
                         FROM pg_stat_activity
                        WHERE datname = %s AND pid <> pg_backend_pid()""",
                    (database_name,),
                )
                server.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


def test_provider_bulk_enqueue_is_atomic_rate_scheduled_and_replayable() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_provider_bulk_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_provider_bulk_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as connection:
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_role = True
            project = seed_project(connection, suffix=f"provider-bulk-{suffix}")
            _seed_runtime_option(connection, project_id=project["project"])
            connection.commit()

        app_url = login_url(database_url, user=app_login, password=app_password)
        policies = PostgresWorkflowCSamplingPolicyControl(
            repository=PostgresSamplingAdmissionRepository(
                connect=lambda: psycopg.connect(app_url, row_factory=dict_row),
                clock=lambda: NOW,
            ),
            clock=lambda: NOW,
        )
        policy = _approved_policy(app_url, project["project"])
        suite_repository = PostgresSamplingSuiteRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        input_option = _suite_input(project["project"], policy.id, policy.definition_hash)
        assert suite_repository.register_input(
            input_option, idempotency_key="suite-input:bulk"
        ) == input_option
        execution_repository = PostgresProviderSamplingExecutionInputRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        execution = PersistentProviderSamplingExecutionInput(
            project_id=project["project"],
            suite_input_option_id=input_option.id,
            suite_input_option_hash=input_option.option_hash,
            execution=ProviderSamplingExecutionInput.from_payload(_execution_payload()),
            frozen_at=NOW,
        )
        assert execution_repository.register(
            execution, idempotency_key="provider-execution-input:bulk"
        ) == execution
        suite = _suite(input_option)
        assert suite_repository.create_suite(
            suite, input_option=input_option, idempotency_key="suite:bulk"
        ) == suite
        runs = PostgresSamplingRunRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        run_control = PostgresWorkflowCSamplingRunControl(
            runs=runs,
            suites=suite_repository,
            policies=policies,
            clock=lambda: NOW,
        )
        run, tasks = run_control.start_run(
            project_id=project["project"],
            suite_id=suite.id,
            idempotency_key="run:bulk",
            payload=StartSamplingRunRequest(
                purpose="geo_measurement", requested_not_before=NOW
            ),
        )
        bulk_repository = PostgresProviderSamplingBulkAttemptRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        control = PostgresWorkflowCProviderBulkSamplingControl(
            runs=runs,
            suites=suite_repository,
            execution_inputs=execution_repository,
            attempts=bulk_repository,
            policies=policies,
            clock=lambda: NOW,
        )
        requested_not_before = NOW + timedelta(minutes=5)
        created = control.enqueue_ready(
            project_id=project["project"],
            run_id=run.id,
            idempotency_key="bulk:one",
            payload=EnqueueReadySamplingRunRequest(
                requested_not_before=requested_not_before, max_tasks=2
            ),
        )
        replayed = control.enqueue_ready(
            project_id=project["project"],
            run_id=run.id,
            idempotency_key="bulk:one",
            payload=EnqueueReadySamplingRunRequest(
                requested_not_before=requested_not_before, max_tasks=2
            ),
        )
        assert created.replayed is False
        assert created.enqueued_count == 2
        assert created.skipped_count == suite.planned_task_count - 2
        assert created.scheduled_at == (
            requested_not_before,
            requested_not_before + timedelta(seconds=suite.minimum_request_interval_seconds),
        )
        assert replayed.replayed is True
        assert tuple(item.attempt_id for item in replayed.attempts) == tuple(
            item.attempt_id for item in created.attempts
        )
        assert all(item.replayed for item in replayed.attempts)
        assert replayed.scheduled_at == created.scheduled_at
        with pytest.raises(SamplingConflict, match="idempotency key was reused"):
            control.enqueue_ready(
                project_id=project["project"],
                run_id=run.id,
                idempotency_key="bulk:one",
                payload=EnqueueReadySamplingRunRequest(
                    requested_not_before=requested_not_before, max_tasks=3
                ),
            )

        def bulk_item(task, expected_version: int) -> ProviderSamplingBulkAttemptItem:
            attempt_id = uuid4()
            spec = execution.execution.build_spec(
                run_id=run.id,
                task_id=task.id,
                attempt_id=attempt_id,
                task_version=expected_version + 1,
                attempt_version=1,
                question_id=task.identity.question_id,
                question_version=task.identity.question_version,
                admitted_by=uuid4(),
                admitted_at=run.admitted_not_before,
                search_mode=suite.source_stratum.search_mode,
            )
            return ProviderSamplingBulkAttemptItem(
                task_id=task.id,
                attempt_id=attempt_id,
                expected_task_version=expected_version,
                spec_payload=spec_payload(spec),
            )

        # The first item is valid.  The second intentionally carries a stale
        # Task version, so PostgreSQL must roll back the first nested admission.
        atomicity_probe = ProviderSamplingBulkAttemptAdmission(
            project_id=project["project"],
            run_id=run.id,
            requested_not_before=requested_not_before,
            authorization_checked_at=NOW,
            max_tasks=2,
            items=(bulk_item(tasks[2], tasks[2].version), bulk_item(tasks[3], tasks[3].version + 1)),
        )
        with pytest.raises(SamplingConflict, match="ready Task slice"):
            bulk_repository.enqueue_ready(atomicity_probe, idempotency_key="bulk:rollback")
        read_repository = PostgresSamplingReadRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        assert len(
            read_repository.attempts_for_run(
                project_id=project["project"], run_id=run.id, source=suite.source_stratum
            )
        ) == 2
        persisted_tasks = runs.list_tasks(
            project_id=project["project"], run_id=run.id, suite=suite
        )
        assert persisted_tasks[2].status.value == persisted_tasks[3].status.value == "planned"
    finally:
        if created_role:
            with psycopg.connect(database_url, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    """SELECT pg_terminate_backend(pid)
                         FROM pg_stat_activity
                        WHERE datname = %s AND pid <> pg_backend_pid()""",
                    (database_name,),
                )
                server.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


def _approved_policy(app_url: str, project_id: UUID):
    control = PostgresWorkflowCSamplingPolicyControl(
        repository=PostgresSamplingAdmissionRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row),
            clock=lambda: NOW,
        ),
        clock=lambda: NOW,
    )
    created = control.create(
        project_id=project_id,
        actor_id="provider-execution-maker",
        idempotency_key="policy:first",
        payload=CreateAdmissionPolicyRequest(
            runtime_authorization_option_key="provider-au-v1",
            purpose="geo_measurement",
            valid_until=NOW + timedelta(days=30),
            quota_remaining=10,
            daily_task_limit=10,
            minimum_request_interval_seconds=1,
            max_concurrency=2,
        ),
    )
    submitted = control.submit(
        project_id=project_id,
        policy_id=created.record.id,
        actor_id="provider-execution-maker",
        idempotency_key="policy:submit",
        payload=AdmissionPolicySubmitRequest(expected_version=created.record.aggregate_version),
    )
    return control.decide(
        project_id=project_id,
        policy_id=created.record.id,
        actor_id="provider-execution-checker",
        idempotency_key="policy:approve",
        payload=AdmissionPolicyDecisionRequest(
            expected_version=submitted.record.aggregate_version,
            reason="approved for provider execution input integration",
        ),
        approved=True,
    ).record


def _suite_input(
    project_id: UUID, policy_id: UUID, policy_hash: str
) -> PersistentSamplingSuiteInput:
    source = SamplingSourceStratum(
        platform="openai",
        surface="web_search",
        configured_model="gpt-5-mini",
        reported_model="gpt-5-mini-2026-07-01",
        capture_method=CaptureMethod.PROVIDER_API,
        adapter_release="openai-web-search@2026-07-23",
        locale="en-AU",
        region="AU",
        language="en",
        search_mode="web_search",
        account_cohort="not_applicable",
        egress_policy_category="not_applicable",
        location_control=LocationControl.COUNTRY,
        location_evidence_hash=_hash("location-au"),
        requested_country="AU",
        requested_region=None,
        requested_locale="en-AU",
        requested_language="en",
        effective_country="AU",
        effective_region=None,
        effective_locale="en-AU",
        effective_language="en",
    )
    return PersistentSamplingSuiteInput(
        id=uuid5(SAMPLING_SUITE_INPUT_NAMESPACE, f"{project_id}:provider-au-v1"),
        project_id=project_id,
        option_key="provider-au-v1",
        display_name="Provider AU",
        question_set_id=uuid4(),
        question_set_version="v1",
        question_set_hash=_hash("question-set"),
        questions=(SamplingQuestion("q-1", "v1", _hash("Which provider should I choose?")),),
        adapter_release_id=uuid4(),
        adapter_release_hash=_hash("adapter-release"),
        model_release_id=uuid4(),
        model_release_hash=_hash("model-release"),
        route_policy_id=uuid4(),
        route_policy_hash=_hash("route-policy"),
        runtime_manifest_id=uuid4(),
        runtime_manifest_hash=_hash("runtime-manifest"),
        runtime_option_id=uuid4(),
        runtime_option_hash=_hash("runtime-option"),
        admission_policy_id=policy_id,
        admission_policy_hash=policy_hash,
        source_stratum=source,
        frozen_at=NOW,
    )


def _suite(input_option: PersistentSamplingSuiteInput) -> SamplingSuite:
    return SamplingSuite(
        id=uuid4(),
        project_id=input_option.project_id,
        question_set_id=input_option.question_set_id,
        question_set_version=input_option.question_set_version,
        question_set_hash=input_option.question_set_hash,
        adapter_release_id=input_option.adapter_release_id,
        adapter_release_hash=input_option.adapter_release_hash,
        model_release_id=input_option.model_release_id,
        model_release_hash=input_option.model_release_hash,
        route_policy_id=input_option.route_policy_id,
        route_policy_hash=input_option.route_policy_hash,
        runtime_manifest_id=input_option.runtime_manifest_id,
        runtime_manifest_hash=input_option.runtime_manifest_hash,
        runtime_option_id=input_option.runtime_option_id,
        runtime_option_hash=input_option.runtime_option_hash,
        admission_policy_id=input_option.admission_policy_id,
        admission_policy_hash=input_option.admission_policy_hash,
        questions=input_option.questions,
        source_stratum=input_option.source_stratum,
        repetitions=10,
        statistics_method_version="sampling-statistics-v1",
        max_planned_tasks=10,
        max_daily_tasks=10,
        minimum_request_interval_seconds=1,
        max_concurrency=2,
        frozen_by="provider-execution-maker",
        frozen_at=NOW,
    )


def _execution_payload() -> dict[str, object]:
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    question = "Which provider should I choose?"
    return {
        "schema_version": 1,
        "runtime_selection_id": str(uuid4()),
        "prompt": {
            "binding_id": str(uuid4()),
            "state_id": str(uuid4()),
            "state_version": 1,
            "release_id": str(uuid4()),
            "release_hash": _hash("prompt-release"),
            "purpose": "geo_measurement",
            "bundle_hash": _hash("prompt-bundle"),
            "system_message": "Return a JSON answer.",
            "answer_field": "answer",
            "output_schema": schema,
            "application_output_schema": schema,
            "temperature": 0.2,
            "max_output_tokens": 256,
            "seed": 7,
            "tool_mode": None,
        },
        "questions": [
            {
                "question_id": "q-1",
                "question_version": "v1",
                "text": question,
                "text_hash": _hash(question),
            }
        ],
        "deadline_at": None,
    }


def _seed_runtime_option(connection, *, project_id: UUID) -> None:
    connection.execute(
        """INSERT INTO workflow_c_sampling_runtime_options(
               project_id, option_key, option_hash, display_name, platform,
               capture_method, adapter_release, location_control,
               location_evidence_hash, authorization_reference, allowed_purposes,
               status, frozen_at
           ) VALUES (
               %s, 'provider-au-v1', %s, 'Provider AU', 'openai', 'provider_api',
               'openai-web-search@2026-07-23', 'country', %s, 'authorization:provider',
               %s::jsonb, 'approved', clock_timestamp()
           )""",
        (project_id, _hash("runtime-option"), _hash("location-au"), Jsonb(["geo_measurement"])),
    )


def _boolean(connection, statement: str) -> bool:
    row = connection.execute(statement).fetchone()
    return bool(next(iter(row.values()))) if isinstance(row, dict) else bool(row[0])


def _database_url(admin_url: str, database_name: str) -> str:
    parsed = urlsplit(admin_url)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
