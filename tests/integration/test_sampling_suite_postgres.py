from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.jobs.postgres import LostJobLease, PostgresDurableJobStore
from geo_core.jobs.outbox import PostgresOutboxStore
from geo_core.project_scope import set_project_scope
from geo_api.workflow_c_sampling_contracts import (
    EnqueueSamplingAttemptRequest,
    StartSamplingRunRequest,
)
from geo_api.workflow_c_sampling_postgres_execution import (
    PostgresWorkflowCProviderSamplingControl,
)
from geo_api.workflow_c_sampling_postgres_policy import (
    PostgresWorkflowCSamplingPolicyControl,
)
from geo_api.workflow_c_sampling_postgres_run import PostgresWorkflowCSamplingRunControl
from geo_core.sampling import (
    PostgresProviderSamplingExecutionInputRepository,
    PostgresProviderSamplingAttemptRepository,
    PostgresSamplingCancellationRepository,
    PostgresSamplingReadRepository,
    PostgresSamplingRunRepository,
    PostgresSamplingSuiteRepository,
    SamplingAdmissionCommand,
    SamplingConflict,
    ProviderSamplingAttemptAdmission,
    admit_sampling_suite,
)
from geo_core.sampling.postgres_admission import PostgresSamplingAdmissionRepository
from geo_core.sampling.postgres_worker_repository import (
    PostgresWorkflowCSamplingRepository,
)
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.sampling_suite_postgres_worker_support import (
    assert_claim_and_retry_project_sampling_state as _assert_claim_and_retry_project_sampling_state,
    provider_attempt_spec as _provider_attempt_spec,
    sampling_attempt_state as _sampling_attempt_state,
)
from tests.integration.sampling_suite_postgres_support import (
    NOW,
    approved_policy as _approved_policy,
    assert_app_cannot_bypass_suite_commands as _assert_app_cannot_bypass_suite_commands,
    assert_canonical_payload_hash as _assert_canonical_payload_hash,
    assert_scope_rejects_foreign_project as _assert_scope_rejects_foreign_project,
    provider_execution_input as _provider_execution_input,
    seed_runtime_option as _seed_runtime_option,
    suite as _suite,
    suite_input as _input,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_sampling_suite_input_and_suite_are_fenced_and_project_scoped() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_sampling_suite_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_sampling_suite_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_sampling_worker_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    created_worker_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0039_workflow_c_alert_control")
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(app_password)
                )
            )
            created_role = True
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            created_worker_role = True
            first = seed_project(admin, suffix=f"sampling-suite-{suffix}-first")
            second = seed_project(admin, suffix=f"sampling-suite-{suffix}-second")
            _seed_runtime_option(admin, project_id=first["project"], marker="first")
            _seed_runtime_option(admin, project_id=second["project"], marker="second")

        app_url = login_url(database_url, user=app_login, password=app_password)
        worker_url = login_url(database_url, user=worker_login, password=worker_password)
        policies = PostgresWorkflowCSamplingPolicyControl(
            repository=PostgresSamplingAdmissionRepository(
                connect=lambda: psycopg.connect(app_url, row_factory=dict_row),
                clock=lambda: NOW,
            ),
            clock=lambda: NOW,
        )
        policy = _approved_policy(policies, project_id=first["project"])
        repository = PostgresSamplingSuiteRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        input_option = _input(
            project_id=first["project"], policy_id=policy.id, policy_hash=policy.definition_hash
        )
        _assert_canonical_payload_hash(app_url, first["project"], input_option)

        created_input = repository.register_input(
            input_option, idempotency_key="sampling-suite-input:first"
        )
        replayed_input = repository.register_input(
            input_option, idempotency_key="sampling-suite-input:first"
        )
        assert created_input == input_option
        assert replayed_input == input_option
        assert (
            repository.resolve_input(
                project_id=first["project"], option_key=input_option.option_key
            )
            == input_option
        )
        execution_repository = PostgresProviderSamplingExecutionInputRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        execution_input = _provider_execution_input(input_option)
        assert (
            execution_repository.register(
                execution_input,
                idempotency_key="sampling-provider-execution-input:first",
            )
            == execution_input
        )

        suite = _suite(input_option)
        created_suite = repository.create_suite(
            suite,
            input_option=input_option,
            idempotency_key="sampling-suite:first",
        )
        replayed_suite = repository.create_suite(
            suite,
            input_option=input_option,
            idempotency_key="sampling-suite:first",
        )
        assert created_suite == suite
        assert replayed_suite == suite
        with psycopg.connect(app_url, row_factory=dict_row) as connection:
            set_project_scope(connection, first["project"])
            ledger_row = connection.execute(
                """SELECT input_hash
                     FROM workflow_c_command_ledger
                    WHERE project_id = %s
                      AND command_scope = 'sampling.suite.create'
                      AND aggregate_id = %s
                      AND idempotency_key_hash = %s""",
                (
                    first["project"],
                    suite.id,
                    _hash_key("sampling-suite:first"),
                ),
            ).fetchone()
        assert ledger_row is not None
        # This is the exact command shape used before 0126. A legacy Suite
        # replay must keep this input hash instead of hashing a null selector.
        assert ledger_row["input_hash"] == _json_hash(
            {
                "operation": "create",
                "suite_id": str(suite.id),
                "suite_hash": suite.suite_hash,
                "input_option_hash": input_option.option_hash,
                "frozen_by": suite.frozen_by,
            }
        )
        assert repository.get_suite(project_id=first["project"], suite_id=suite.id) == suite
        assert repository.list_suites(project_id=first["project"]) == (suite,)

        run_repository = PostgresSamplingRunRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        run_control = PostgresWorkflowCSamplingRunControl(
            runs=run_repository,
            suites=repository,
            policies=policies,
            clock=lambda: NOW,
        )
        start_payload = StartSamplingRunRequest(
            purpose="geo_measurement",
            requested_not_before=NOW,
        )
        created_run, created_tasks = run_control.start_run(
            project_id=first["project"],
            suite_id=suite.id,
            idempotency_key="sampling-run:first",
            payload=start_payload,
        )
        replayed_run, replayed_tasks = run_control.start_run(
            project_id=first["project"],
            suite_id=suite.id,
            idempotency_key="sampling-run:first",
            payload=start_payload,
        )
        grant = admit_sampling_suite(
            suite,
            policy=policy.approved_policy(at=NOW),
            command=SamplingAdmissionCommand(
                idempotency_key="sampling-run:first",
                purpose="geo_measurement",
                requested_at=NOW,
                requested_not_before=NOW,
            ),
        )
        run_id = created_run.id
        assert created_run == replayed_run
        assert created_tasks == replayed_tasks
        assert run_repository.get_run(project_id=first["project"], run_id=run_id) == created_run
        assert (
            run_repository.list_tasks(project_id=first["project"], run_id=run_id, suite=suite)
            == created_tasks
        )
        assert (
            run_repository.reservation(project_id=first["project"], run_id=run_id).unused_task_count
            == suite.planned_task_count
        )
        task = created_tasks[0]
        attempt_repository = PostgresProviderSamplingAttemptRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        provider_enqueue = PostgresWorkflowCProviderSamplingControl(
            runs=run_repository,
            suites=repository,
            execution_inputs=execution_repository,
            attempts=attempt_repository,
            policies=policies,
            clock=lambda: NOW,
        )
        bad_attempt_id = uuid4()
        bad_spec = _provider_attempt_spec(
            run_id=run_id,
            task_id=task.id,
            attempt_id=bad_attempt_id,
            task_version=task.version + 1,
            question_hash=input_option.questions[0].text_hash,
            admitted_at=NOW,
        )
        bad_prompt = dict(bad_spec["prompt"])
        bad_prompt["system_message"] = "Return a different JSON answer."
        bad_spec["prompt"] = bad_prompt
        with pytest.raises(SamplingConflict, match="frozen execution input"):
            attempt_repository.enqueue(
                ProviderSamplingAttemptAdmission(
                    project_id=first["project"],
                    run_id=run_id,
                    task_id=task.id,
                    attempt_id=bad_attempt_id,
                    expected_task_version=task.version,
                    requested_not_before=NOW,
                    authorization_checked_at=NOW,
                    spec_payload=bad_spec,
                ),
                idempotency_key="sampling-attempt:modified-prompt",
            )
        enqueued = provider_enqueue.enqueue(
            project_id=first["project"],
            run_id=run_id,
            task_id=task.id,
            idempotency_key="sampling-attempt:first",
            payload=EnqueueSamplingAttemptRequest(
                expected_task_version=task.version,
                requested_not_before=NOW,
            ),
        )
        replayed = provider_enqueue.enqueue(
            project_id=first["project"],
            run_id=run_id,
            task_id=task.id,
            idempotency_key="sampling-attempt:first",
            payload=EnqueueSamplingAttemptRequest(
                expected_task_version=task.version,
                requested_not_before=NOW,
            ),
        )
        admission = enqueued.admission
        first_attempt = enqueued.attempt
        replayed_attempt = replayed.attempt
        attempt_id = first_attempt.attempt_id
        assert first_attempt.attempt_id == attempt_id
        assert first_attempt.durable_job_id == replayed_attempt.durable_job_id
        assert first_attempt.replayed is False
        assert replayed_attempt.replayed is True
        assert admission.spec.search_mode == suite.source_stratum.search_mode
        assert admission.spec.question_text == "Which provider should I choose?"
        read_repository = PostgresSamplingReadRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        persisted_attempts = read_repository.attempts_for_run(
            project_id=first["project"],
            run_id=run_id,
            source=suite.source_stratum,
        )
        assert len(persisted_attempts) == 1
        assert persisted_attempts[0].id == attempt_id
        assert persisted_attempts[0].job.status.value == "queued"
        assert (
            read_repository.observations_for_run(
                project_id=first["project"],
                run_id=run_id,
                source=suite.source_stratum,
            )
            == ()
        )
        assert (
            run_repository.reservation(project_id=first["project"], run_id=run_id).unused_task_count
            == suite.planned_task_count - 1
        )
        assert (
            run_repository.list_tasks(project_id=first["project"], run_id=run_id, suite=suite)[
                0
            ].version
            == task.version + 1
        )
        with pytest.raises(SamplingConflict, match="quota"):
            run_repository.create_run(
                suite=suite,
                grant=grant,
                run_id=uuid4(),
                idempotency_key="sampling-run:over-quota",
                created_at=NOW,
            )
        _assert_claim_and_retry_project_sampling_state(
            app_url=app_url,
            worker_url=worker_url,
            project_id=first["project"],
            durable_job_id=first_attempt.durable_job_id,
            task_id=task.id,
            attempt_id=attempt_id,
            admission=admission,
            first_task_version=first_attempt.task_version,
            first_attempt_version=first_attempt.attempt_version,
            now=NOW,
        )
        assert (
            run_repository.get_run(project_id=first["project"], run_id=run_id).status.value
            == "cancelled"
        )
        replacement_run, replacement_tasks = run_repository.create_run(
            suite=suite,
            grant=grant,
            run_id=uuid4(),
            idempotency_key="sampling-run:after-cancel",
            created_at=NOW,
        )
        assert replacement_run.id != run_id
        assert len(replacement_tasks) == suite.planned_task_count
        assert {item.id for item in replacement_tasks}.isdisjoint(
            {item.id for item in created_tasks}
        )
        queued_attempt_id = uuid4()
        queued_task = replacement_tasks[0]
        # `NOW` is the frozen clock used when the seven-day authorization
        # window is admitted; wall-clock time would make this fixture
        # invalid once the test data's historical window has elapsed.
        scheduled_at = NOW + timedelta(minutes=5)
        queued_attempt = attempt_repository.enqueue(
            ProviderSamplingAttemptAdmission(
                project_id=first["project"],
                run_id=replacement_run.id,
                task_id=queued_task.id,
                attempt_id=queued_attempt_id,
                expected_task_version=queued_task.version,
                requested_not_before=scheduled_at,
                authorization_checked_at=NOW,
                spec_payload=_provider_attempt_spec(
                    run_id=replacement_run.id,
                    task_id=queued_task.id,
                    attempt_id=queued_attempt_id,
                    task_version=queued_task.version + 1,
                    question_hash=input_option.questions[0].text_hash,
                    admitted_at=NOW,
                ),
            ),
            idempotency_key="sampling-attempt:queued-cancel",
        )
        with psycopg.connect(app_url, row_factory=dict_row) as connection:
            set_project_scope(connection, first["project"])
            row = connection.execute(
                """SELECT next_run_at FROM durable_jobs
                     WHERE project_id = %s AND id = %s""",
                (first["project"], queued_attempt.durable_job_id),
            ).fetchone()
        assert row is not None and row["next_run_at"] == scheduled_at
        queued_cancellation = PostgresSamplingCancellationRepository(
            connect=lambda: psycopg.connect(app_url, row_factory=dict_row)
        )
        queued_cancelled = queued_cancellation.cancel_attempt(
            project_id=first["project"],
            attempt_id=queued_attempt_id,
            expected_task_version=queued_attempt.task_version,
            expected_attempt_version=queued_attempt.attempt_version,
            idempotency_key="sampling-attempt:queued-cancel",
            cancelled_at=NOW,
        )
        queued_cancel_replay = queued_cancellation.cancel_attempt(
            project_id=first["project"],
            attempt_id=queued_attempt_id,
            expected_task_version=queued_attempt.task_version,
            expected_attempt_version=queued_attempt.attempt_version,
            idempotency_key="sampling-attempt:queued-cancel",
            cancelled_at=NOW,
        )
        assert queued_cancelled.cancellation_requested is False
        assert queued_cancelled.run_status == "running"
        assert queued_cancelled.task_version == queued_attempt.task_version + 1
        assert queued_cancelled.attempt_version == queued_attempt.attempt_version + 1
        assert queued_cancel_replay.replayed is True
        replacement_cancelled = queued_cancellation.cancel_run(
            project_id=first["project"],
            run_id=replacement_run.id,
            idempotency_key="sampling-run:after-queued-cancel",
            cancelled_at=NOW,
        )
        assert replacement_cancelled.run_status == "cancelled"
        assert replacement_cancelled.released_task_count == 9
        assert replacement_cancelled.attempt_ids == ()

        recovery_run, recovery_tasks = run_repository.create_run(
            suite=suite,
            grant=grant,
            run_id=uuid4(),
            idempotency_key="sampling-run:unhandled-worker-failure",
            created_at=NOW,
        )
        recovery_task = recovery_tasks[0]
        recovery_attempt_id = uuid4()
        recovery_attempt = attempt_repository.enqueue(
            ProviderSamplingAttemptAdmission(
                project_id=first["project"],
                run_id=recovery_run.id,
                task_id=recovery_task.id,
                attempt_id=recovery_attempt_id,
                expected_task_version=recovery_task.version,
                requested_not_before=NOW,
                authorization_checked_at=NOW,
                spec_payload=_provider_attempt_spec(
                    run_id=recovery_run.id,
                    task_id=recovery_task.id,
                    attempt_id=recovery_attempt_id,
                    task_version=recovery_task.version + 1,
                    question_hash=input_option.questions[0].text_hash,
                    admitted_at=NOW,
                ),
            ),
            idempotency_key="sampling-attempt:unhandled-worker-failure",
        )
        recovery_store = PostgresDurableJobStore(
            lambda: psycopg.connect(worker_url, row_factory=dict_row)
        )
        for expected_status in ("retry_wait", "retry_wait", "dead_lettered"):
            claim = recovery_store.claim(
                job_id=recovery_attempt.durable_job_id,
                project_id=first["project"],
                expected_kind="sampling.provider_execute",
                worker_id="sampling-suite-unhandled-worker",
                lease_for=timedelta(minutes=2),
            )
            assert claim.disposition == "claimed" and claim.lease is not None
            assert (
                recovery_store.fail(
                    claim.lease,
                    error_code="unexpected_worker_failure",
                    details={"sampling_status": "worker_unhandled"},
                    retry_delay=timedelta(0),
                )
                == expected_status
            )
        assert _sampling_attempt_state(
            worker_url=worker_url,
            project_id=first["project"],
            task_id=recovery_task.id,
            attempt_id=recovery_attempt_id,
        )[::2] == ("failed", "failed")
        recovery_cancelled = queued_cancellation.cancel_run(
            project_id=first["project"],
            run_id=recovery_run.id,
            idempotency_key="sampling-run:unhandled-worker-failure:cancel",
            cancelled_at=NOW,
        )
        assert recovery_cancelled.run_status == "cancelled"
        assert recovery_cancelled.released_task_count == 9
        assert recovery_cancelled.attempt_ids == ()
        lease_loss_run, lease_loss_tasks = run_repository.create_run(
            suite=suite,
            grant=grant,
            run_id=uuid4(),
            idempotency_key="sampling-run:lease-loss",
            created_at=NOW,
        )
        lease_loss_task = lease_loss_tasks[0]
        lease_loss_attempt_id = uuid4()
        lease_loss_admission = ProviderSamplingAttemptAdmission(
            project_id=first["project"],
            run_id=lease_loss_run.id,
            task_id=lease_loss_task.id,
            attempt_id=lease_loss_attempt_id,
            expected_task_version=lease_loss_task.version,
            requested_not_before=NOW,
            authorization_checked_at=NOW,
            spec_payload=_provider_attempt_spec(
                run_id=lease_loss_run.id,
                task_id=lease_loss_task.id,
                attempt_id=lease_loss_attempt_id,
                task_version=lease_loss_task.version + 1,
                question_hash=input_option.questions[0].text_hash,
                admitted_at=NOW,
            ),
        )
        lease_loss_attempt = attempt_repository.enqueue(
            lease_loss_admission,
            idempotency_key="sampling-attempt:lease-loss",
        )
        lease_loss_store = PostgresDurableJobStore(
            lambda: psycopg.connect(worker_url, row_factory=dict_row)
        )
        first_lease = lease_loss_store.claim(
            job_id=lease_loss_attempt.durable_job_id,
            project_id=first["project"],
            expected_kind="sampling.provider_execute",
            worker_id="sampling-suite-lease-loss-first",
            lease_for=timedelta(minutes=2),
        )
        assert first_lease.disposition == "claimed" and first_lease.lease is not None
        with psycopg.connect(database_url) as admin:
            admin.execute(
                """UPDATE durable_jobs
                      SET lease_expires_at = clock_timestamp() - interval '1 second'
                    WHERE project_id = %s AND id = %s""",
                (first["project"], lease_loss_attempt.durable_job_id),
            )
        with pytest.raises(LostJobLease):
            with lease_loss_store.fenced_transaction(first_lease.lease):
                pytest.fail("an expired lease must not reach Sampling finalization")
        with pytest.raises(LostJobLease):
            lease_loss_store.fail(
                first_lease.lease,
                error_code="stale_worker",
                details={"sampling_status": "stale_worker"},
                retry_delay=None,
            )
        assert _sampling_attempt_state(
            worker_url=worker_url,
            project_id=first["project"],
            task_id=lease_loss_task.id,
            attempt_id=lease_loss_attempt_id,
        )[::2] == ("running", "running")
        recoverable = PostgresOutboxStore(
            lambda: psycopg.connect(worker_url, row_factory=dict_row)
        ).recoverable(batch_size=10)
        assert any(item.job_id == lease_loss_attempt.durable_job_id for item in recoverable)
        recovered_lease = lease_loss_store.claim(
            job_id=lease_loss_attempt.durable_job_id,
            project_id=first["project"],
            expected_kind="sampling.provider_execute",
            worker_id="sampling-suite-lease-loss-recovered",
            lease_for=timedelta(minutes=2),
        )
        assert recovered_lease.disposition == "claimed" and recovered_lease.lease is not None
        assert recovered_lease.lease.fencing_generation == first_lease.lease.fencing_generation + 1
        worker_repository = PostgresWorkflowCSamplingRepository(
            lambda: psycopg.connect(worker_url, row_factory=dict_row)
        )
        recovered_state = worker_repository.provider_state(
            project_id=first["project"], spec=lease_loss_admission.spec
        )
        with lease_loss_store.fenced_transaction(recovered_lease.lease) as connection:
            worker_repository.record_failure(
                connection=connection,
                lease=recovered_lease.lease,
                spec_hash=lease_loss_admission.spec_hash,
                state=recovered_state,
                task_version=recovered_state.task_version,
                attempt_version=recovered_state.attempt_version,
                error_code="lease_loss_recovered",
                retryable=False,
                occurred_at=NOW,
            )
            lease_loss_store.fail_in_transaction(
                connection,
                recovered_lease.lease,
                error_code="lease_loss_recovered",
                details={"sampling_status": "failed"},
            )
        assert _sampling_attempt_state(
            worker_url=worker_url,
            project_id=first["project"],
            task_id=lease_loss_task.id,
            attempt_id=lease_loss_attempt_id,
        )[::2] == ("failed", "failed")

        with pytest.raises(SamplingConflict):
            repository.register_input(
                _input(
                    project_id=first["project"],
                    policy_id=policy.id,
                    policy_hash=policy.definition_hash,
                    display_name="different content",
                ),
                idempotency_key="sampling-suite-input:first:changed",
            )

        _assert_app_cannot_bypass_suite_commands(
            app_url, project_id=first["project"], suite_id=suite.id, run_id=run_id
        )
        _assert_scope_rejects_foreign_project(
            app_url,
            scoped_project_id=first["project"],
            foreign_project_id=second["project"],
            frozen_suite=suite,
            input_option=input_option,
        )
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_role:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
        if created_worker_role:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )


def _database_url(admin_url: str, database_name: str) -> str:
    parsed = urlsplit(admin_url)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))


def _hash_key(value: str) -> str:
    return _json_hash({"idempotency_key": value.strip()})


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
