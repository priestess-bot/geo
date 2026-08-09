from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.project_scope import set_project_scope
from geo_core.recommendations import (
    DownstreamDraftKind,
    InputChangeReason,
    RecommendationApplication,
    RecommendationDecision,
    RecommendationEvidenceKind,
    RecommendationEvidenceSelector,
    RecommendationScope,
    RecommendationType,
)
from geo_core.recommendations.generation_admission import (
    GenerationModelSelector,
    RecommendationGenerationSelection,
)
from geo_core.recommendations.generation_artifact_contracts import (
    RecommendationTaskArtifactStore,
)
from geo_core.recommendations.generation_result_recovery import (
    GovernedRecommendationModelResultLoader,
)
from geo_core.recommendations.generation_worker_contracts import (
    RECOMMENDATION_PARENT_JOB_KIND,
)
from geo_core.recommendations.postgres import build_recommendation_api
from geo_core.recommendations.postgres.generation_worker import (
    RecommendationParentHandler,
)
from geo_core.recommendations.postgres.generation_worker_repository import (
    PostgresRecommendationGenerationWorkerRepository,
)
from geo_core.recommendations.postgres.generation_submission import (
    PsycopgRecommendationGenerationSubmission,
)
from geo_core.recommendations.postgres.prompt_runtime import (
    build_recommendation_prompt_resolver,
)
from geo_core.recommendations.postgres.uow import RecommendationUnitOfWorkFactory
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.recommendation_postgres_lifecycle_support import (
    RECOMMENDATION_RUNTIME_OPTION_ID,
    RecommendationRuntimeCatalog,
    UnusedRecommendationDependency,
    hash_text,
    recommendation_runtime_selection,
    seed_frozen_recommendation_prompt,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_recommendation_lifecycle_uses_append_only_app_privileges() -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_recommendation_{suffix}"
    target_url = _database_url(ADMIN_URL, database_name)
    app_login, password = f"geo_recommendation_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_recommendation_worker_{suffix}", uuid4().hex
    created_database = False
    created_role = False
    created_worker_role = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = target_url
        command.upgrade(migration, "head")

        now = datetime.now(UTC).replace(microsecond=0)
        with psycopg.connect(target_url) as admin:
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_app").format(
                    sql.Identifier(app_login), sql.Literal(password)
                )
            )
            created_role = True
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE geo_worker").format(
                    sql.Identifier(worker_login), sql.Literal(worker_password)
                )
            )
            created_worker_role = True
            seeded = seed_project(admin, suffix=f"recommendation-{suffix}")
            approver_id = uuid4()
            admin.execute(
                """INSERT INTO identities(id, issuer, subject)
                   VALUES (%s, 'integration', %s)""",
                (approver_id, f"approver-{suffix}"),
            )
            fact_id = _seed_approved_fact(admin, seeded=seeded)
            question_id = _seed_frozen_question(admin, seeded=seeded)

        app_url = login_url(target_url, user=app_login, password=password)
        worker_url = login_url(
            target_url,
            user=worker_login,
            password=worker_password,
        )
        application = RecommendationApplication(
            RecommendationUnitOfWorkFactory(
                lambda: psycopg.connect(app_url, row_factory=dict_row),
                block_drafts=_block_drafts,
            ),
            clock=lambda: now,
        )
        creator = _principal(seeded, seeded["owner"], "analyst")
        reviewer = _principal(seeded, seeded["reviewer"], "admin")
        approver = _principal(seeded, approver_id, "admin")
        values = {
            "project_id": seeded["project"],
            "recommendation_type": RecommendationType.INSUFFICIENT_EVIDENCE,
            "scope": RecommendationScope(
                seeded["project"],
                "recommendation-integration-v1",
                question_or_cluster_ref=str(question_id),
                surface_ref="surface:integration-au",
            ),
            "decision": RecommendationDecision(
                impact_chain=("Observed evidence", "Address the evidence-backed gap"),
                risk="low",
                effort="small",
                business_value="Improve qualified discovery",
                confidence=Decimal("0.8"),
                counterevidence=(),
                validation_plan=("Review a future approved report",),
                stale_conditions=("Approved fact changes",),
            ),
            "evidence_selectors": (
                RecommendationEvidenceSelector(RecommendationEvidenceKind.FACT, str(fact_id)),
                RecommendationEvidenceSelector(
                    RecommendationEvidenceKind.QUESTION, str(question_id)
                ),
            ),
            "proposed_draft_kind": DownstreamDraftKind.SAMPLING_PLAN,
            "valid_until": now + timedelta(days=30),
            "expected_version": 0,
            "idempotency_key": "recommendation:create:postgres",
        }

        created = application.create_recommendation(creator, **values).value
        submitted = application.submit_recommendation(
            creator,
            project_id=seeded["project"],
            recommendation_id=created.recommendation.id,
            expected_version=1,
            idempotency_key="recommendation:submit:postgres",
        ).value
        reviewed = application.review_recommendation(
            reviewer,
            project_id=seeded["project"],
            recommendation_id=submitted.recommendation.id,
            notes="Reviewed against the current approved fact.",
            expected_version=2,
            idempotency_key="recommendation:review:postgres",
        ).value
        approved = application.approve_recommendation(
            approver,
            project_id=seeded["project"],
            recommendation_id=reviewed.workflow.recommendation.id,
            expected_version=2,
            idempotency_key="recommendation:approve:postgres",
        ).value

        assert approved.workflow.recommendation.version == 3
        assert approved.downstream_draft is not None
        api = build_recommendation_api(database_url=app_url)
        loaded = api.get_recommendation(
            creator,
            project_id=seeded["project"],
            recommendation_id=created.recommendation.id,
        )
        listed = api.list_recommendations(
            creator,
            project_id=seeded["project"],
            limit=20,
            offset=0,
        )
        assert loaded == approved.workflow
        assert listed.total == 1
        assert listed.items == (approved.workflow,)

        generation = PsycopgRecommendationGenerationSubmission(
            connection_factory=lambda: psycopg.connect(app_url, row_factory=dict_row),
            runtime_catalog=RecommendationRuntimeCatalog(
                recommendation_runtime_selection(seeded["project"])
            ),
            clock=lambda: now,
        )
        prompt_binding_id = seed_frozen_recommendation_prompt(
            app_url=app_url,
            seeded=seeded,
            owner=creator,
            reviewer=reviewer,
        )
        generation_selection = RecommendationGenerationSelection(
            project_id=seeded["project"],
            scope=RecommendationScope(
                seeded["project"],
                "recommendation-generation-integration-v1",
                question_or_cluster_ref=str(question_id),
            ),
            evidence_selectors=(
                RecommendationEvidenceSelector(RecommendationEvidenceKind.FACT, str(fact_id)),
                RecommendationEvidenceSelector(
                    RecommendationEvidenceKind.QUESTION, str(question_id)
                ),
                RecommendationEvidenceSelector(
                    RecommendationEvidenceKind.ATTRIBUTION,
                    "attribution:board-b-excluded",
                ),
            ),
            prompt_binding_id=prompt_binding_id,
            model=GenerationModelSelector(runtime_selection_id=RECOMMENDATION_RUNTIME_OPTION_ID),
            valid_until=now + timedelta(days=7),
            minimum_real_observations=1,
        )
        enqueued = generation.enqueue(
            creator,
            selection=generation_selection,
            idempotency_key="recommendation-generation:postgres",
        )
        replayed = generation.enqueue(
            creator,
            selection=generation_selection,
            idempotency_key="recommendation-generation:postgres",
        )
        assert enqueued.replayed is False
        assert replayed.replayed is True
        assert replayed.job == enqueued.job
        with psycopg.connect(target_url, row_factory=dict_row) as admin:
            persisted = admin.execute(
                """SELECT
                       (SELECT count(*) FROM durable_jobs WHERE id = %s) AS jobs,
                       (SELECT count(*) FROM recommendation_generation_specs WHERE job_id = %s)
                           AS specs,
                       (SELECT count(*) FROM broker_outbox WHERE job_id = %s) AS outbox,
                       (SELECT count(*) FROM durable_job_events
                         WHERE job_id = %s AND event_type = 'job_enqueued') AS events,
                       (SELECT count(*) FROM recommendation_generation_command_receipts
                         WHERE project_id = %s AND operation = 'enqueue') AS receipts""",
                (
                    enqueued.job.id,
                    enqueued.job.id,
                    enqueued.job.id,
                    enqueued.job.id,
                    seeded["project"],
                ),
            ).fetchone()
        assert persisted == {
            "jobs": 1,
            "specs": 1,
            "outbox": 1,
            "events": 1,
            "receipts": 1,
        }

        def worker_connect():
            return psycopg.connect(worker_url, row_factory=dict_row)

        job_store = PostgresDurableJobStore(worker_connect)
        claimed = job_store.claim(
            job_id=enqueued.job.id,
            project_id=seeded["project"],
            expected_kind=RECOMMENDATION_PARENT_JOB_KIND,
            worker_id="recommendation-integration-worker",
            lease_for=timedelta(minutes=2),
        )
        assert claimed.disposition == "claimed" and claimed.lease is not None
        parent_handler = RecommendationParentHandler(
            store=job_store,
            repository=PostgresRecommendationGenerationWorkerRepository(
                worker_connect,
                prompts=build_recommendation_prompt_resolver(connection_factory=worker_connect),
                artifacts=cast(
                    RecommendationTaskArtifactStore,
                    UnusedRecommendationDependency("artifact store"),
                ),
                model_results=cast(
                    GovernedRecommendationModelResultLoader,
                    UnusedRecommendationDependency("model result loader"),
                ),
            ),
            clock=lambda: now,
        )
        worker_result = parent_handler.handle(claimed.lease)
        worker_execution = generation.get(
            creator,
            project_id=seeded["project"],
            job_id=enqueued.job.id,
        )
        assert worker_result["status"] == "succeeded", worker_execution.job
        completed = generation.get(
            creator,
            project_id=seeded["project"],
            job_id=enqueued.job.id,
        )
        assert completed.job.status.value == "succeeded"
        assert completed.result is not None
        assert completed.result.recommendation.recommendation_type.value == (
            "insufficient_evidence"
        )
        assert completed.result.recommendation.proposed_draft_kind is (
            DownstreamDraftKind.SAMPLING_PLAN
        )
        assert completed.result.model_call_ids == ()
        assert completed.result.insufficient_reasons == (
            "insufficient_real_observation_count",
            "missing_sufficient_metric_comparison",
            "missing_question_or_surface_lineage",
            "missing_active_rule",
            "attribution_unavailable:connector_attribution_excluded_from_this_phase",
        )
        assert len(completed.result.recommendation.evidence.prompt_releases) == 1
        generated_workflow = api.get_recommendation(
            creator,
            project_id=seeded["project"],
            recommendation_id=completed.result.recommendation.id,
        )
        generated_list = api.list_recommendations(
            creator,
            project_id=seeded["project"],
            limit=20,
            offset=0,
        )
        assert generated_workflow.recommendation == completed.result.recommendation
        assert generated_workflow.recommendation.status.value == "draft"
        assert generated_workflow.drafts == ()
        assert generated_list.total == 2
        assert completed.result.recommendation.id in {
            item.recommendation.id for item in generated_list.items
        }
        with psycopg.connect(target_url, row_factory=dict_row) as admin:
            model_lineage = admin.execute(
                """SELECT
                       (SELECT count(*) FROM recommendation_model_tasks
                         WHERE project_id = %s AND parent_job_id = %s) AS tasks,
                       (SELECT count(*) FROM recommendation_model_call_lineage
                         WHERE project_id = %s AND parent_job_id = %s) AS calls,
                       (SELECT count(*) FROM recommendation_evidence_bindings
                         WHERE project_id = %s AND recommendation_id = %s
                           AND evidence_kind = 'attribution') AS attribution_bindings,
                       has_table_privilege(
                           %s, 'recommendation_workflow_versions', 'INSERT'
                       ) AS worker_direct_workflow_insert,
                       has_table_privilege(
                           %s, 'recommendation_evidence_bindings', 'INSERT'
                       ) AS worker_direct_evidence_insert,
                       has_function_privilege(
                           %s,
                           'geo_materialize_recommendation_generation_draft(uuid,uuid,uuid,bigint)',
                           'EXECUTE'
                       ) AS worker_materialization_execute""",
                (
                    seeded["project"],
                    enqueued.job.id,
                    seeded["project"],
                    enqueued.job.id,
                    seeded["project"],
                    completed.result.recommendation.id,
                    worker_login,
                    worker_login,
                    worker_login,
                ),
            ).fetchone()
        assert model_lineage == {
            "tasks": 0,
            "calls": 0,
            "attribution_bindings": 1,
            "worker_direct_workflow_insert": False,
            "worker_direct_evidence_insert": False,
            "worker_materialization_execute": True,
        }

        stale_created = application.create_recommendation(
            creator,
            **{
                **values,
                "idempotency_key": "recommendation:create:fact-retirement",
            },
        ).value
        stale_submitted = application.submit_recommendation(
            creator,
            project_id=seeded["project"],
            recommendation_id=stale_created.recommendation.id,
            expected_version=1,
            idempotency_key="recommendation:submit:fact-retirement",
        ).value
        stale_reviewed = application.review_recommendation(
            reviewer,
            project_id=seeded["project"],
            recommendation_id=stale_submitted.recommendation.id,
            notes="Reviewed before the source Fact retirement.",
            expected_version=2,
            idempotency_key="recommendation:review:fact-retirement",
        ).value
        stale_approved = application.approve_recommendation(
            approver,
            project_id=seeded["project"],
            recommendation_id=stale_reviewed.workflow.recommendation.id,
            expected_version=2,
            idempotency_key="recommendation:approve:fact-retirement",
        ).value
        pending_message_id = uuid4()
        with psycopg.connect(app_url) as app:
            set_project_scope(app, seeded["project"])
            app.execute(
                """INSERT INTO recommendation_outbox_messages(
                       id, project_id, recommendation_id, recommendation_version,
                       message_type, payload_hash, status
                   ) VALUES (%s, %s, %s, 3, 'recommendation.approved', %s, 'pending')""",
                (
                    pending_message_id,
                    seeded["project"],
                    stale_approved.workflow.recommendation.id,
                    hash_text("recommendation-approved-fact-retirement"),
                ),
            )
            app.commit()
        with psycopg.connect(target_url) as admin:
            admin.execute(
                """UPDATE knowledge_fact_candidates
                   SET lifecycle_status = 'withdrawn', updated_at = clock_timestamp()
                   WHERE project_id = %s AND id = %s""",
                (seeded["project"], fact_id),
            )
            admin.commit()

        stale = application.reconcile_stale(
            creator,
            project_id=seeded["project"],
            recommendation_id=stale_approved.workflow.recommendation.id,
            change_reason=InputChangeReason.FACT_RETIRED,
            expected_version=3,
            idempotency_key="recommendation:stale:fact-retirement",
        ).value
        assert stale.workflow.recommendation.status.value == "stale"
        assert stale.workflow.recommendation.evidence.facts[0].retired is False
        assert stale.cancelled_outbox_ids == (pending_message_id,)
        with psycopg.connect(app_url, row_factory=dict_row) as app:
            set_project_scope(app, seeded["project"])
            stale_projection = app.execute(
                """SELECT
                       (SELECT status FROM recommendation_drafts
                         WHERE project_id = %s AND recommendation_id = %s) AS draft_status,
                       (SELECT status FROM recommendation_outbox_messages
                         WHERE project_id = %s AND id = %s) AS outbox_status,
                       (SELECT result->>'retired'
                          FROM (SELECT geo_resolve_recommendation_evidence(
                              %s, 'fact', %s
                          ) AS result) AS resolved) AS fact_retired""",
                (
                    seeded["project"],
                    stale_approved.workflow.recommendation.id,
                    seeded["project"],
                    pending_message_id,
                    seeded["project"],
                    str(fact_id),
                ),
            ).fetchone()
        assert stale_projection == {
            "draft_status": "blocked_source_stale",
            "outbox_status": "cancelled",
            "fact_retired": "true",
        }

        expired = application.expire_recommendation(
            approver,
            project_id=seeded["project"],
            recommendation_id=approved.workflow.recommendation.id,
            reason="approved evidence window elapsed",
            expected_version=3,
            idempotency_key="recommendation:expire:postgres",
        ).value
        assert expired.workflow.recommendation.status.value == "expired"

        with psycopg.connect(app_url, row_factory=dict_row) as app:
            set_project_scope(app, seeded["project"])
            draft = app.execute(
                """SELECT status FROM recommendation_drafts
                   WHERE project_id = %s AND recommendation_id = %s""",
                (seeded["project"], created.recommendation.id),
            ).fetchone()
            assert draft == {"status": "blocked_source_expired"}
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute(
                    """UPDATE recommendation_workflow_versions SET status = 'approved'
                       WHERE project_id = %s AND recommendation_id = %s""",
                    (seeded["project"], created.recommendation.id),
                )
            app.rollback()
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


def _principal(seeded: dict[str, UUID], identity_id: UUID, role: str) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=seeded["tenant"],
        memberships=(MembershipRecord(seeded["project"], seeded["tenant"], role),),
        auth_method="integration",
    )


def _seed_approved_fact(connection: Any, *, seeded: dict[str, UUID]) -> UUID:
    """Seed only the producer projection fields consumed by the resolver.

    The append-only source chain is outside this Recommendation adapter test.  The
    fixture uses the same isolated database and disables relational triggers only
    while establishing that upstream producer state; the application role never
    receives that bypass.
    """

    fact_id = uuid4()
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO knowledge_fact_candidates(
               id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
               statement, statement_hash, status, reviewed_by, review_notes, reviewed_at
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'approved', %s, %s, clock_timestamp())""",
        (
            fact_id,
            seeded["project"],
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            "The approved product fact is current for this Project.",
            hash_text(f"fact:{fact_id}"),
            seeded["owner"],
            "integration fixture approval",
        ),
    )
    connection.commit()
    return fact_id


def _seed_frozen_question(connection: Any, *, seeded: dict[str, UUID]) -> UUID:
    """Seed the approved Question producer projection used by Sampling Plans."""

    question_set_id, question_id = uuid4(), uuid4()
    question_text = "Which Australian customers need more sampling evidence?"
    connection.execute("SET LOCAL session_replication_role = replica")
    connection.execute(
        """INSERT INTO knowledge_question_sets(
               id, project_id, campaign_id, series_id, version_number, generated_by_job_id,
               name, status, dimension_count, covered_dimension_count,
               possible_duplicate_count, coverage_ratio, duplicate_ratio, content_hash,
               created_by, approved_by, approved_at, frozen_by, frozen_at
           ) VALUES (%s, %s, %s, %s, 1, %s, %s, 'frozen', 1, 1, 0, 1, 0, %s,
                     %s, %s, clock_timestamp(), %s, clock_timestamp())""",
        (
            question_set_id,
            seeded["project"],
            uuid4(),
            question_set_id,
            uuid4(),
            "Recommendation integration QuestionSet",
            hash_text(f"question-set:{question_set_id}"),
            seeded["owner"],
            seeded["owner"],
            seeded["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO knowledge_question_set_items(
               id, project_id, campaign_id, question_set_id, generated_by_job_id,
               question_candidate_id, ordinal, dimension_key, query_text_snapshot,
               query_text_hash, normalized_text_hash, query_kind_snapshot,
               query_cluster_key, source_lineage_hash, brand_scope_snapshot,
               coverage_role_snapshot, topic_cluster_snapshot, funnel_snapshot
           ) SELECT %s, project_id, campaign_id, id, generated_by_job_id, %s, 1,
                    'recommendation-gap', %s, %s, %s, 'recommendation',
                    'recommendation-gap', %s, 'brand', 'product_fit',
                    'recommendation-gap', 'consideration'
                FROM knowledge_question_sets
               WHERE id = %s AND project_id = %s""",
        (
            question_id,
            uuid4(),
            question_text,
            hash_text(question_text),
            hash_text(question_text.lower()),
            hash_text(f"question-source:{question_id}"),
            question_set_id,
            seeded["project"],
        ),
    )
    connection.commit()
    return question_id


def _block_drafts(
    connection: Any,
    project_id: UUID,
    recommendation_id: UUID,
    source_status: str,
    blocked_at: datetime,
    reason: str,
) -> tuple[UUID, ...]:
    status = f"blocked_source_{source_status}"
    rows = connection.execute(
        """UPDATE recommendation_drafts
           SET status = %s, blocked_at = %s, blocked_reason = %s
           WHERE project_id = %s AND recommendation_id = %s
             AND status = 'draft'
           RETURNING id""",
        (status, blocked_at, reason, project_id, recommendation_id),
    ).fetchall()
    return tuple(sorted((row["id"] for row in rows), key=str))


def _database_url(admin_url: str, database_name: str) -> str:
    parts = urlsplit(admin_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, ""))
