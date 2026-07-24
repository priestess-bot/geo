from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore, WorkerLease
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.semantic_metrics import (
    DeterministicRuleVersions,
    EvidenceLocator,
    EvidenceLocatorKind,
    FrozenMetricSuite,
    JudgeKind,
    JudgeVersion,
    MetricDefinition,
    MetricJudgeCandidate,
    MetricInputSet,
    MetricKey,
    MetricObservation,
    MetricValueKind,
    PlannedMetricSlot,
    ParsedMetricJudgeProgramOutput,
    SemanticStratum,
    StructuredJudgeOutput,
    SubjectInventory,
    plan_metric_judge_batches,
)
from geo_core.workflow_c_metric_parent_admission import (
    MetricArbiterEvaluatorAdmission,
    MetricJudgeEvaluatorAdmission,
)
from geo_core.workflow_c_metric_parent_orchestration import (
    PostgresWorkflowCMetricParentOrchestrator,
)
from geo_core.workflow_c_metric_parent_specs import MetricModelProgramAdmission
from geo_core.workflow_c_metric_judge_worker_contracts import ModelRequestTask
from geo_core.workflow_c_semantic_specs import SemanticMetricMetadata
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.test_workflow_c_metric_parent_admission_postgres import _seed_parent_lineage


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_metric_parent_first_pass_admits_judges_and_defers_atomically() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_metric_parent_flow_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, password = f"geo_metric_parent_flow_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        command.downgrade(migration, "0066_metric_parent_admission")
        command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(password)
                )
            )
            created_role = True
            project = seed_project(admin, suffix=f"metric-parent-flow-{suffix}")
            parent = _seed_parent_lineage(admin, project=project, now=now)
            admin.commit()

        worker_url = login_url(database_url, user=worker_login, password=password)

        def connect():
            return psycopg.connect(worker_url, row_factory=dict_row)

        store = PostgresDurableJobStore(connect)
        lease = WorkerLease(
            job_id=UUID(str(parent["job_id"])),
            project_id=project["project"],
            kind="workflow_c.analysis.semantic_metrics",
            worker_id="metric-parent-flow",
            lease_token=UUID(str(parent["lease_token"])),
            fencing_generation=1,
            attempt_count=1,
            max_attempts=3,
        )
        input_set = _input_set(UUID(str(parent["observation_id"])))
        suite = _suite(parent)
        operation = PostgresWorkflowCMetricParentOrchestrator(
            store=store,
            cipher=EnvelopeCipher(MasterKeyring(keys={1: b"a" * 32}, active_version=1)),
            lease_for=timedelta(seconds=60),
            clock=lambda: now,
        )
        result = operation.execute(
            lease=lease,
            parent_input_hash=str(parent["input_hash"]),
            metadata=SemanticMetricMetadata(
                run_id=UUID(str(parent["run_id"])),
                source_stratum_hash="d" * 64,
                capture_method="provider_api",
                warning_ratio=Decimal("0"),
                test_only=False,
                synthetic=False,
            ),
            input_set=input_set,
            suite=suite,
            program=_program(parent),
        )

        assert result == {
            "status": "waiting_for_metric_judges",
            "job_id": str(parent["job_id"]),
        }
        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                """SELECT status, error_code FROM durable_jobs
                      WHERE project_id = %s AND id = %s""",
                (project["project"], parent["job_id"]),
            ).fetchone() == ("retry_wait", "metric_judges_admitted")
            assert admin.execute(
                """SELECT count(*) FROM workflow_c_metric_judge_batches
                      WHERE project_id = %s AND parent_job_id = %s""",
                (project["project"], parent["job_id"]),
            ).fetchone() == (1,)
            assert admin.execute(
                """SELECT count(*) FROM workflow_c_metric_model_children
                      WHERE project_id = %s AND parent_job_id = %s
                        AND role = 'metric_judge'""",
                (project["project"], parent["job_id"]),
            ).fetchone() == (2,)
            assert admin.execute(
                """SELECT count(*) FROM broker_outbox
                      WHERE project_id = %s AND job_id = %s
                        AND topic = 'workflow_c.analysis.semantic_metrics'""",
                (project["project"], parent["job_id"]),
            ).fetchone() == (1,)
            reader_lease_token = uuid4()
            admin.execute(
                """UPDATE durable_jobs
                      SET status = 'running', lease_owner = 'metric-parent-reader',
                          lease_token = %s, lease_expires_at = clock_timestamp() + interval '60 seconds',
                          heartbeat_at = clock_timestamp(), fencing_generation = 2,
                          attempt_count = 1, error_code = NULL, error_detail = NULL,
                          completed_at = NULL, updated_at = clock_timestamp()
                    WHERE project_id = %s AND id = %s""",
                (reader_lease_token, project["project"], parent["job_id"]),
            )
            admin.commit()

        reader_lease = WorkerLease(
            job_id=UUID(str(parent["job_id"])),
            project_id=project["project"],
            kind="workflow_c.analysis.semantic_metrics",
            worker_id="metric-parent-reader",
            lease_token=reader_lease_token,
            fencing_generation=2,
            attempt_count=1,
            max_attempts=3,
        )
        plans = tuple(
            batch
            for observation in input_set.observations
            for batch in plan_metric_judge_batches(
                input_set=input_set, suite=suite, observation=observation
            )
        )
        with store.fenced_transaction(reader_lease) as connection:
            batches = operation._progress.batches_in_transaction(
                connection,
                lease=reader_lease,
                parent_input_hash=str(parent["input_hash"]),
                expected=plans,
                input_set_hash=input_set.input_set_hash,
                metric_suite_hash=suite.suite_hash,
            )
            assert len(batches) == 1
            assert (
                operation._progress.judge_resolution_in_transaction(
                    connection,
                    lease=reader_lease,
                    parent_input_hash=str(parent["input_hash"]),
                    batch_id=batches[0].batch_id,
                )
                is None
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
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )


def test_metric_parent_resumes_after_agreed_judges_and_persists_snapshot() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_metric_parent_complete_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    worker_login, password = f"geo_metric_parent_complete_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(password)
                )
            )
            created_role = True
            project = seed_project(admin, suffix=f"metric-parent-complete-{suffix}")
            parent = _seed_parent_lineage(admin, project=project, now=now)
            admin.commit()

        worker_url = login_url(database_url, user=worker_login, password=password)

        def connect():
            return psycopg.connect(worker_url, row_factory=dict_row)

        store = PostgresDurableJobStore(connect)
        with store.open_project(project["project"]) as worker:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker.execute("INSERT INTO workflow_c_semantic_metric_snapshots DEFAULT VALUES")
            worker.rollback()
        input_set = _input_set(UUID(str(parent["observation_id"])))
        suite = _suite(parent)
        operation = PostgresWorkflowCMetricParentOrchestrator(
            store=store,
            cipher=EnvelopeCipher(MasterKeyring(keys={1: b"a" * 32}, active_version=1)),
            lease_for=timedelta(seconds=60),
            clock=lambda: now,
        )
        first_lease = WorkerLease(
            job_id=UUID(str(parent["job_id"])),
            project_id=project["project"],
            kind="workflow_c.analysis.semantic_metrics",
            worker_id="metric-parent-complete",
            lease_token=UUID(str(parent["lease_token"])),
            fencing_generation=1,
            attempt_count=1,
            max_attempts=3,
        )
        assert operation.execute(
            lease=first_lease,
            parent_input_hash=str(parent["input_hash"]),
            metadata=_metadata(parent),
            input_set=input_set,
            suite=suite,
            program=_program(parent),
        ) == {
            "status": "waiting_for_metric_judges",
            "job_id": str(parent["job_id"]),
        }

        with psycopg.connect(database_url, row_factory=dict_row) as admin:
            children = admin.execute(
                """SELECT child.child_job_id, child.candidate_id, child.evaluator_id
                       FROM workflow_c_metric_model_children AS child
                      WHERE child.project_id = %s AND child.parent_job_id = %s
                      ORDER BY child.ordinal""",
                (project["project"], parent["job_id"]),
            ).fetchall()
        assert len(children) == 2

        for child in children:
            claim = store.claim(
                job_id=child["child_job_id"],
                project_id=project["project"],
                expected_kind="workflow_c.metric_judge",
                worker_id="metric-child-complete",
                lease_for=timedelta(seconds=60),
            )
            assert claim.disposition == "claimed" and claim.lease is not None
            projection, output_hash = _agreed_projection(
                input_set=input_set,
                candidate_id=child["candidate_id"],
                evaluator_id=child["evaluator_id"],
            )
            with store.fenced_transaction(claim.lease) as connection:
                completed = connection.execute(
                    """SELECT * FROM geo_complete_workflow_c_metric_child(
                           %s, %s, %s, %s, %s, 'metric_judge', %s, %s, NULL, NULL, %s::jsonb
                       )""",
                    (
                        project["project"],
                        claim.lease.job_id,
                        claim.lease.lease_token,
                        claim.lease.fencing_generation,
                        parent["input_hash"],
                        uuid4(),
                        output_hash,
                        Jsonb(projection),
                    ),
                ).fetchone()
                assert completed is not None
                store.complete_in_transaction(
                    connection,
                    claim.lease,
                    result_ref=f"metric-child:{claim.lease.job_id}",
                    details={"output_hash": output_hash},
                )

        with psycopg.connect(database_url) as admin:
            admin.execute(
                """UPDATE durable_jobs SET next_run_at = clock_timestamp()
                      WHERE project_id = %s AND id = %s AND status = 'retry_wait'""",
                (project["project"], parent["job_id"]),
            )
            admin.commit()
        resumed = store.claim(
            job_id=UUID(str(parent["job_id"])),
            project_id=project["project"],
            expected_kind="workflow_c.analysis.semantic_metrics",
            worker_id="metric-parent-resume",
            lease_for=timedelta(seconds=60),
        )
        assert resumed.disposition == "claimed" and resumed.lease is not None
        result = operation.execute(
            lease=resumed.lease,
            parent_input_hash=str(parent["input_hash"]),
            metadata=_metadata(parent),
            input_set=input_set,
            suite=suite,
            program=_program(parent),
        )
        assert result["status"] == "complete"
        assert isinstance(result["snapshot_hash"], str)

        with psycopg.connect(database_url) as admin:
            assert admin.execute(
                """SELECT status FROM durable_jobs
                      WHERE project_id = %s AND id = %s""",
                (project["project"], parent["job_id"]),
            ).fetchone() == ("succeeded",)
            assert admin.execute(
                """SELECT count(*) FROM workflow_c_semantic_metric_snapshots
                      WHERE project_id = %s AND snapshot_hash = %s""",
                (project["project"], result["snapshot_hash"]),
            ).fetchone() == (1,)
            assert admin.execute(
                """SELECT status FROM workflow_c_semantic_metric_results
                      WHERE project_id = %s AND snapshot_hash = %s AND metric_key = 'recommendation'""",
                (project["project"], result["snapshot_hash"]),
            ).fetchone() == ("complete",)
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
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )


def _input_set(observation_id: UUID) -> MetricInputSet:
    return MetricInputSet(
        stratum=SemanticStratum((("capture_method", "provider_api"), ("locale", "en-AU"))),
        planned_slots=(PlannedMetricSlot("slot-1", "question-1", "purchase"),),
        observations=(
            MetricObservation(
                id=observation_id,
                slot_id="slot-1",
                payload_hash="8" * 64,
                question_id="question-1",
                question_cluster="purchase",
                answer_text="Advinsys is recommended.",
            ),
        ),
        subjects=SubjectInventory(
            primary_subject_key="advinsys",
            brand_aliases=("Advinsys",),
            product_aliases=("Advinsys Suite",),
            competitors=(),
        ),
        approved_facts=(),
        verified_urls=("https://example.com",),
        approved_corpus_version="corpus-v1",
        approved_corpus_hash="9" * 64,
        baseline_question_scores=(),
    )


def _suite(parent: dict[str, UUID | str]) -> FrozenMetricSuite:
    return FrozenMetricSuite(
        definitions=(
            MetricDefinition(
                MetricKey.RECOMMENDATION,
                "metric-v1",
                MetricValueKind.BINARY_RATE,
                JudgeKind.RECOMMENDATION,
            ),
        ),
        judge_version=JudgeVersion(
            key="metric-judge",
            version="metric-judge-v1",
            prompt_release_id=UUID(str(parent["release_id"])),
            prompt_release_hash=str(parent["release_hash"]),
            model_identity="review-provider/model-v1",
            schema_version="metric-judge-output-v1",
        ),
        rule_versions=DeterministicRuleVersions(
            subject="subject-rule-v1",
            url="url-rule-v1",
            citation_order="citation-order-v1",
            denominator="denominator-rule-v1",
            mention="mention-rule-v1",
        ),
    )


def _program(parent: dict[str, UUID | str]) -> MetricModelProgramAdmission:
    return MetricModelProgramAdmission(
        admitted_by=uuid4(),
        admitted_at=datetime.now(UTC),
        judges=(_judge("judge-a", parent), _judge("judge-b", parent)),
        arbiter=_arbiter(parent),
    )


def _metadata(parent: dict[str, UUID | str]) -> SemanticMetricMetadata:
    return SemanticMetricMetadata(
        run_id=UUID(str(parent["run_id"])),
        source_stratum_hash="d" * 64,
        capture_method="provider_api",
        warning_ratio=Decimal("0"),
        test_only=False,
        synthetic=False,
    )


def _agreed_projection(
    *, input_set: MetricInputSet, candidate_id: UUID, evaluator_id: str
) -> tuple[dict[str, object], str]:
    observation = input_set.observations[0]
    output = StructuredJudgeOutput(
        kind=JudgeKind.RECOMMENDATION,
        label="yes",
        score=Decimal("1"),
        reason_codes=(),
        locators=(
            EvidenceLocator(
                EvidenceLocatorKind.ANSWER_SPAN,
                str(observation.id),
                version=observation.artifact_version,
                content_hash=observation.payload_hash,
                start=0,
                end=len("Advinsys"),
            ),
        ),
        schema_version="metric-judge-output-v1",
        metric_id=MetricKey.RECOMMENDATION.value,
    )
    parsed = ParsedMetricJudgeProgramOutput(
        results=(output,), overall_status="pass", output_locale="en-AU"
    )
    candidate = MetricJudgeCandidate.create(
        candidate_id=str(candidate_id), evaluator_id=evaluator_id, output=parsed
    )
    return (
        {
            "results": [output.canonical_value()],
            "overall_status": parsed.overall_status,
            "output_locale": parsed.output_locale,
        },
        candidate.output_hash,
    )


def _judge(evaluator_id: str, parent: dict[str, UUID | str]) -> MetricJudgeEvaluatorAdmission:
    return MetricJudgeEvaluatorAdmission(
        evaluator_id=evaluator_id,
        **_evaluator_values(parent, "monitoring.metric_judge"),
    )


def _arbiter(parent: dict[str, UUID | str]) -> MetricArbiterEvaluatorAdmission:
    return MetricArbiterEvaluatorAdmission(
        evaluator_id="arbiter-a",
        **_evaluator_values(parent, "monitoring.metric_judge"),
    )


def _evaluator_values(parent: dict[str, UUID | str], purpose: str) -> dict[str, object]:
    return {
        "runtime_selection_id": UUID(str(parent["option_id"])),
        "runtime_manifest_id": UUID(str(parent["manifest_id"])),
        "runtime_manifest_hash": str(parent["manifest_hash"]),
        "runtime_option_id": UUID(str(parent["option_id"])),
        "runtime_option_hash": str(parent["option_hash"]),
        "prompt_binding_id": UUID(str(parent["binding_id"])),
        "prompt_binding_version": 1,
        "prompt_frozen_state_id": UUID(str(parent["state_id"])),
        "prompt_state_version": 2,
        "prompt_release_id": UUID(str(parent["release_id"])),
        "prompt_release_version": 1,
        "prompt_release_hash": str(parent["release_hash"]),
        "prompt_purpose": purpose,
        "prompt_bundle_hash": "b" * 64,
        "request": ModelRequestTask(
            messages=({"role": "system", "content": "Return JSON."},),
            configured_model="review-provider/model-v1",
            temperature=0.1,
            max_output_tokens=256,
            output_schema={"type": "object"},
            application_output_schema={"type": "object"},
            seed=1,
            tool_mode=None,
            search_mode=None,
            deadline_at=None,
        ),
    }


def _database_url(base: str, database_name: str) -> str:
    parsed = urlsplit(base)
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database_name}", "", ""))
