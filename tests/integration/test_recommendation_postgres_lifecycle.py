from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.model_gateway.contracts import ModelPolicy
from geo_core.model_gateway.runtime_catalog import NewModelCallJobSelection
from geo_core.project_scope import set_project_scope
from geo_core.prompts.application import PromptProgramApplication
from geo_core.prompts.postgres import prompt_program_uow_factory
from geo_core.prompts.program import (
    ModelPolicySnapshot,
    ProgramKind,
    ProgramSchemaContract,
)
from geo_core.recommendations import (
    DownstreamDraftKind,
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
from geo_core.recommendations.postgres import build_recommendation_api
from geo_core.recommendations.postgres.generation_submission import (
    PsycopgRecommendationGenerationSubmission,
)
from geo_core.recommendations.postgres.uow import RecommendationUnitOfWorkFactory
from geo_core.secrets import SecretVersionHandle
from tests.integration.model_gateway_postgres_fixtures import releases
from tests.integration.placement_worker_support import login_url, seed_project


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
    created_database = False
    created_role = False
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
            runtime_catalog=_RecommendationRuntimeCatalog(
                _recommendation_runtime_selection(seeded["project"])
            ),
            clock=lambda: now,
        )
        prompt_binding_id = _seed_frozen_recommendation_prompt(
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
            ),
            prompt_binding_id=prompt_binding_id,
            model=GenerationModelSelector(runtime_selection_id=_RECOMMENDATION_RUNTIME_OPTION_ID),
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
            _hash(f"fact:{fact_id}"),
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
            _hash(f"question-set:{question_set_id}"),
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
               query_cluster_key, source_lineage_hash
           ) SELECT %s, project_id, campaign_id, id, generated_by_job_id, %s, 1,
                    'recommendation-gap', %s, %s, %s, 'recommendation',
                    'recommendation-gap', %s
                FROM knowledge_question_sets
               WHERE id = %s AND project_id = %s""",
        (
            question_id,
            uuid4(),
            question_text,
            _hash(question_text),
            _hash(question_text.lower()),
            _hash(f"question-source:{question_id}"),
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
             AND status IN ('draft', 'started')
           RETURNING id""",
        (status, blocked_at, reason, project_id, recommendation_id),
    ).fetchall()
    return tuple(sorted((row["id"] for row in rows), key=str))


def _database_url(admin_url: str, database_name: str) -> str:
    parts = urlsplit(admin_url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", parts.query, ""))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_RECOMMENDATION_RUNTIME_OPTION_ID = UUID("90000000-0000-4000-8000-000000000001")


class _RecommendationRuntimeCatalog:
    """Deterministic catalog fixture; provider execution is outside this DB contract."""

    def __init__(self, selection: NewModelCallJobSelection) -> None:
        self._selection = selection

    def resolve_approved_runtime(
        self,
        *,
        project_id: UUID,
        runtime_selection_id: UUID,
        required_purpose: str,
        search_mode: str | None,
    ) -> NewModelCallJobSelection:
        assert project_id == self._selection.provider_secret_handle.project_id
        assert runtime_selection_id == _RECOMMENDATION_RUNTIME_OPTION_ID
        assert required_purpose == "recommendations.recommendation"
        assert search_mode is None
        return self._selection


def _recommendation_runtime_selection(project_id: UUID) -> NewModelCallJobSelection:
    adapter, model, route = releases()
    return NewModelCallJobSelection(
        runtime_manifest_id=UUID("90000000-0000-4000-8000-000000000002"),
        runtime_manifest_hash=_hash("recommendation-runtime-manifest"),
        runtime_option_id=_RECOMMENDATION_RUNTIME_OPTION_ID,
        runtime_option_hash=_hash("recommendation-runtime-option"),
        route=route,
        configured_model=model.configured_model,
        policy=ModelPolicy(
            allowed_providers=frozenset({"openai"}),
            allowed_adapter_release_ids=frozenset({route.adapter_release_id}),
        ),
        provider_secret_handle=SecretVersionHandle(
            reference_id=UUID("90000000-0000-4000-8000-000000000003"),
            project_id=project_id,
            purpose="model_provider.openai",
            version=1,
        ),
        adapter_release=adapter,
        allowed_purposes=frozenset({"recommendations.recommendation"}),
        allowed_search_modes=frozenset({None}),
        provider_config_hash=_hash("recommendation-provider-config"),
    )


def _seed_frozen_recommendation_prompt(
    *,
    app_url: str,
    seeded: dict[str, UUID],
    owner: AccessPrincipal,
    reviewer: AccessPrincipal,
) -> UUID:
    factory = prompt_program_uow_factory(lambda: psycopg.connect(app_url))
    schema = {
        "type": "object",
        "properties": {"subject_id": {"type": "string"}},
        "required": ["subject_id"],
        "additionalProperties": False,
    }
    schemas = ProgramSchemaContract(
        variable_schema_version="recommendation-vars-v1",
        variable_schema={"type": "object", "properties": {}, "additionalProperties": False},
        input_schema_version="recommendation-input-v1",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema_version="recommendation-output-v1",
        output_schema=schema,
        application_output_schema_version="recommendation-application-output-v1",
        application_output_schema=schema,
    )

    def command(operation):
        with factory(seeded["project"]) as unit_of_work:
            result = operation(
                PromptProgramApplication(
                    unit_of_work.prompts,
                    test_evidence_verifier=_RecommendationPromptEvidenceVerifier(),
                )
            )
            unit_of_work.commit()
            return result

    created = command(
        lambda app: app.create_program(
            owner,
            project_id=seeded["project"],
            program_kind=ProgramKind.RECOMMENDATION,
            purpose="recommendations.recommendation",
            system_template="Return one structured recommendation.",
            user_template="Assess the frozen evidence.",
            schemas=schemas,
            model_policy=ModelPolicySnapshot(
                version="recommendation-model-policy-v1",
                policy={"allowed_providers": ["openai"], "fallback": False},
            ),
            test_set_id=uuid4(),
            test_set_version=1,
            test_set_hash=_hash("recommendation-prompt-test-set"),
            compiler_version="geo-prompt-compiler-v2",
            expected_version=0,
            idempotency_key="recommendation-generation-prompt:create",
        )
    )
    command(
        lambda app: app.record_test(
            owner,
            project_id=seeded["project"],
            release_id=created.value.release.id,
            output_artifact_ref="s3://prompt-tests/recommendation-generation.json",
            output_hash=_hash("recommendation-generation-prompt-output"),
            expected_version=1,
            idempotency_key="recommendation-generation-prompt:test",
        )
    )
    command(
        lambda app: app.approve_release(
            reviewer,
            project_id=seeded["project"],
            release_id=created.value.release.id,
            expected_version=2,
            idempotency_key="recommendation-generation-prompt:approve",
        )
    )
    command(
        lambda app: app.freeze_release(
            reviewer,
            project_id=seeded["project"],
            release_id=created.value.release.id,
            expected_version=3,
            idempotency_key="recommendation-generation-prompt:freeze",
        )
    )
    bound = command(
        lambda app: app.bind_release(
            reviewer,
            project_id=seeded["project"],
            release_id=created.value.release.id,
            purpose="recommendations.recommendation",
            expected_version=0,
            idempotency_key="recommendation-generation-prompt:bind",
        )
    )
    return bound.value.binding.id


class _RecommendationPromptEvidenceVerifier:
    def verify(self, *, release, evidence) -> None:
        assert evidence.project_id == release.project_id
        assert evidence.release_id == release.id
        assert evidence.release_hash == release.release_hash
        assert evidence.output_artifact_ref.startswith("s3://prompt-tests/")
