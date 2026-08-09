from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import hashlib
import json
import os
from typing import Any, Mapping
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.catalog.domain import (
    Confidentiality,
    PublicCitation,
    SubjectRole,
    UsageRights,
)
from geo_core.knowledge import KnowledgeApplication
from geo_core.knowledge.domain import KnowledgeValidationError, SourceInput
from geo_core.knowledge.question_domain import QuestionDimensionDraft
from geo_core.knowledge.question_postgres import KnowledgeQuestionPostgresRepository
from geo_core.knowledge.question_worker import KnowledgeQuestionGenerateHandler
from geo_core.knowledge.rag_domain import KnowledgeRagEnqueuePolicy
from geo_core.model_gateway import ModelGatewayResult
from geo_core.monitoring.application import MonitoringApplication
from geo_core.monitoring.domain import Device, Platform
from geo_core.monitoring.postgres import PsycopgMonitoringUnitOfWorkFactory
from geo_core.monitoring.source_contract import (
    CaptureMethod,
    ClientKind,
    ModelIdentity,
    ModelIdentityState,
    ObservationDevice,
    ObservationPlatform,
    ObservationRunParameters,
    ObservationSource,
    ObservationSurface,
    RawEvidence,
    RawEvidenceKind,
    SearchMode,
    SourceStratumKey,
    SurfaceKind,
)
from geo_core.placements.worker_composition import PlacementWorkerDispatcher
from geo_core.placements.application import PlacementApplication
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.simulation_worker import PromptSimulationHandler
from geo_core.placements.worker_composition import ArtifactFinalizeHandler
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import (
    cleanup_projects,
    FakeGateway,
    login_url,
    MemoryArtifactStore,
    seed_project,
)
from tests.integration.question_set_postgres_support import (
    CoverageQuestionGateway,
    revise_possible_duplicate_candidates,
)
from tests.integration.test_knowledge_rag_postgres import (
    SELECTION,
    SELECTION_HASH,
    _approve_graph,
    _dispatcher,
    _object_store,
    _principal,
    _process_source,
    _source,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()
MINIO_ENDPOINT = os.getenv("GEO_F019_TEST_MINIO_ENDPOINT", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
    pytest.mark.skipif(not MINIO_ENDPOINT, reason="GEO_F019_TEST_MINIO_ENDPOINT is required"),
]


class QuestionGateway:
    provider = "integration-question-gateway"

    def generate(self, request, *, policy, budget):
        del policy
        budget.consume()
        payload = json.loads(request.messages[1]["content"])
        fact_id = payload["facts"][0]["fact_candidate_id"]
        entity_ids = [item["graph_entity_id"] for item in payload["entities"]]
        questions = []
        for index, dimension in enumerate(payload["dimensions"]):
            questions.append(
                _question(
                    candidate_id=f"candidate-{index}-1",
                    dimension_key=dimension["dimension_key"],
                    variant_index=1,
                    text=f"How should a buyer evaluate criterion {index} for A1?",
                    semantic=f"buyer criterion {index} A1",
                    fact_id=fact_id,
                    entity_ids=entity_ids,
                )
            )
        first = payload["dimensions"][0]
        questions.append(
            _question(
                candidate_id="candidate-0-2",
                dimension_key=first["dimension_key"],
                variant_index=2,
                text="How should a buyer evaluate criterion 0 for A1 today?",
                semantic="buyer criterion 0 A1",
                fact_id=fact_id,
                entity_ids=entity_ids,
            )
        )
        output = {"questions": questions}
        response_hash = hashlib.sha256(json.dumps(output, sort_keys=True).encode()).hexdigest()
        return ModelGatewayResult(
            output=output,
            call_log_id=uuid4(),
            provider_request_id=f"question-{uuid4()}",
            configured_model=request.configured_model,
            provider_reported_model=request.configured_model,
            prompt_tokens=300,
            completion_tokens=600,
            cost_usd=Decimal("0.003"),
            finish_reason="stop",
            response_hash=response_hash,
        )


def test_question_coverage_pack_edits_and_freezes_unique_items_idempotently() -> None:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_coverage_app_{suffix}", f"geo_coverage_worker_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    campaign_id = uuid4()
    source_url = f"https://example.test/products/v600-{suffix}"
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
        project = seed_project(admin, suffix=f"coverage-{suffix}")
        admin.execute(
            """UPDATE product_entities
               SET canonical_name = 'ADVINSYS TerraMow V600', canonical_url = %s,
                   attributes = '{"category":"robotic_lawn_mower"}'::jsonb
               WHERE id = %s AND project_id = %s""",
            (source_url, project["entity"], project["project"]),
        )
        admin.execute(
            """INSERT INTO geo_campaigns
                 (id, project_id, market_profile_id, primary_product_entity_id,
                  name, status, created_by)
               VALUES (%s, %s, %s, %s, %s, 'active', %s)""",
            (
                campaign_id,
                project["project"],
                project["market"],
                project["entity"],
                f"Coverage campaign {suffix}",
                project["owner"],
            ),
        )
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    principal = _principal(project, suffix)
    policy = KnowledgeRagEnqueuePolicy(
        adapter_release=SELECTION.adapter_release,
        selection_manifest_hash=SELECTION_HASH,
        configured_model="deepseek-v4-flash",
    )
    knowledge = KnowledgeApplication(app_url, question_policy=policy)
    try:
        source = knowledge.create_source(
            principal,
            project_id=project["project"],
            source=SourceInput(
                "text",
                "V600 official specification",
                source_url,
                "v600.txt",
                "text/plain",
                (
                    "A1 的流量为每分钟 2 升。\n"
                    "Product A1\n"
                    "Brand 星澜\n"
                    "A1 belongs_to 星澜"
                ).encode(),
            ),
            idempotency_key=f"coverage-source-{suffix}",
        )
        source_ids = _process_source(
            _dispatcher(worker_url, suffix), source, project["project"]
        )
        fact = next(
            item
            for item in knowledge.list_facts(principal, project_id=project["project"])
            if item["pipeline_run_id"] == source_ids["run_id"]
        )
        knowledge.review_fact(
            principal,
            project_id=project["project"],
            fact_id=fact["id"],
            decision="approved",
            notes="coverage integration fact",
        )
        created = knowledge.create_question_coverage_pack(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            configured_model="deepseek-v4-flash",
            model_call_budget=60,
            semantic_duplicate_threshold=0.92,
            idempotency_key=f"coverage-generation-{suffix}",
        )
        with psycopg.connect(ADMIN_URL) as admin:
            admin.execute(
                """UPDATE durable_jobs
                   SET status = 'dead_lettered', attempt_count = 3, max_attempts = 3,
                       error_code = 'retryable_model_output',
                       error_detail = '{"detail":"simulated invalid model batch"}'::jsonb,
                       completed_at = clock_timestamp(), updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (created["job_id"], project["project"]),
            )
            admin.commit()
        resumed = knowledge.resume_question_coverage_pack(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            generation_job_id=created["job_id"],
            idempotency_key=f"coverage-resume-{suffix}",
        )
        replayed_resume = knowledge.resume_question_coverage_pack(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            generation_job_id=created["job_id"],
            idempotency_key=f"coverage-resume-{suffix}",
        )
        assert resumed["status"] == replayed_resume["status"] == "retry_wait"
        with psycopg.connect(ADMIN_URL) as admin:
            recovery_counts = admin.execute(
                """SELECT
                     (SELECT count(*) FROM job_retry_requests
                      WHERE project_id = %s AND job_id = %s),
                     (SELECT count(*) FROM durable_job_events
                      WHERE project_id = %s AND job_id = %s
                        AND event_type = 'question_generation_resumed'),
                     (SELECT count(*) FROM broker_outbox
                      WHERE project_id = %s AND job_id = %s
                        AND idempotency_key LIKE 'resume:knowledge-question:%%'),
                     (SELECT max_attempts FROM durable_jobs
                      WHERE project_id = %s AND id = %s)""",
                (
                    project["project"],
                    created["job_id"],
                    project["project"],
                    created["job_id"],
                    project["project"],
                    created["job_id"],
                    project["project"],
                    created["job_id"],
                ),
            ).fetchone()
        assert recovery_counts == (1, 1, 1, 4)
        gateway = CoverageQuestionGateway()
        result = _question_dispatcher(worker_url, suffix, gateway=gateway).process(
            job_id=created["job_id"], project_id=project["project"]
        )
        if result["status"] != "succeeded":
            with psycopg.connect(ADMIN_URL) as diagnostic:
                result = {
                    **result,
                    "failure": diagnostic.execute(
                        "SELECT error_code, error_detail FROM durable_jobs WHERE id = %s",
                        (created["job_id"],),
                    ).fetchone(),
                }
        assert result["status"] == "succeeded", result
        assert gateway.calls == 10
        candidates = knowledge.list_question_candidates(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            generation_job_id=created["job_id"],
        )
        assert len(candidates) == 100
        assert sum(item["coverage_role"] == "category_benchmark" for item in candidates) == 50
        assert sum(item["coverage_role"] == "product_fit" for item in candidates) == 40
        assert sum(item["coverage_role"] == "brand_control" for item in candidates) == 10
        assert any(
            item["dedup_status"] == "possible_duplicate"
            and item["semantic_fingerprint"] == "buying priorities shared product fit"
            for item in candidates
        )
        with pytest.raises(
            KnowledgeValidationError, match="non-brand coverage question exposed product identity"
        ):
            knowledge.edit_question_candidate(
                principal,
                project_id=project["project"],
                campaign_id=campaign_id,
                candidate_id=candidates[0]["id"],
                query_text="Should I buy the ADVINSYS TerraMow V600?",
            )
        repair_candidates = tuple(
            candidate
            for candidate in candidates
            if candidate["dedup_status"] == "possible_duplicate"
        )
        for candidate in repair_candidates:
            knowledge.review_question_candidate(
                principal,
                project_id=project["project"],
                campaign_id=campaign_id,
                candidate_id=candidate["id"],
                decision="rejected",
            )
        with pytest.raises(
            KnowledgeValidationError,
            match="rejected duplicate repair must change the effective question",
        ):
            knowledge.edit_question_candidate(
                principal,
                project_id=project["project"],
                campaign_id=campaign_id,
                candidate_id=repair_candidates[0]["id"],
                query_text=repair_candidates[0]["query_text"],
            )
        with psycopg.connect(ADMIN_URL) as admin:
            with pytest.raises(
                psycopg.errors.CheckViolation,
                match="invalid Question candidate repair transition",
            ):
                admin.execute(
                    """UPDATE knowledge_question_candidates
                          SET workflow_status = 'pending_review', reviewed_by = NULL,
                              review_notes = NULL, reviewed_at = NULL,
                              updated_at = clock_timestamp()
                        WHERE id = %s AND project_id = %s AND campaign_id = %s""",
                    (
                        repair_candidates[0]["id"],
                        project["project"],
                        campaign_id,
                    ),
                )
            admin.rollback()
        revised_questions = revise_possible_duplicate_candidates(
            knowledge,
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            candidates=candidates,
        )
        unique_candidates = tuple(item["id"] for item in candidates if item["dedup_status"] == "unique")
        assert len(unique_candidates) == 90
        included = tuple(item["id"] for item in candidates)
        frozen = knowledge.finalize_question_coverage_pack(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            name="AU V600 100-question measurement pack",
            generation_job_id=created["job_id"],
            included_candidate_ids=included,
            idempotency_key=f"coverage-finalize-{suffix}",
        )
        replayed = knowledge.finalize_question_coverage_pack(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            name="AU V600 100-question measurement pack",
            generation_job_id=created["job_id"],
            included_candidate_ids=included,
            idempotency_key=f"coverage-finalize-{suffix}",
        )
        assert frozen["status"] == replayed["status"] == "frozen"
        assert frozen["id"] == replayed["id"]
        assert frozen["covered_dimension_count"] == len(frozen["items"]) == 100
        assert frozen["coverage_ratio"] == Decimal("1.0000")
        assert frozen["possible_duplicate_count"] == 0
        assert frozen["duplicate_ratio"] == Decimal("0.0000")
        frozen_questions = {
            item["question_candidate_id"]: item["query_text_snapshot"]
            for item in frozen["items"]
        }
        assert all(
            frozen_questions[candidate_id] == revised_text
            for candidate_id, revised_text in revised_questions.items()
        )
        with psycopg.connect(ADMIN_URL) as admin:
            counts = admin.execute(
                """SELECT
                     (SELECT count(*) FROM knowledge_question_generation_batches
                      WHERE job_id = %s),
                     (SELECT count(*) FROM knowledge_question_candidate_revisions
                      WHERE generated_by_job_id = %s),
                     (SELECT count(*) FROM knowledge_question_candidates
                      WHERE generated_by_job_id = %s AND workflow_status = 'approved'),
                     (SELECT count(*) FROM knowledge_question_candidates
                      WHERE generated_by_job_id = %s AND workflow_status = 'rejected')""",
                (created["job_id"],) * 4,
            ).fetchone()
        assert counts == (10, len(repair_candidates), 100, 0)
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[project],
                tenant_ids=[project["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def test_f019_int_03_question_candidates_freeze_bind_and_immutable_versions() -> None:
    suffix = uuid4().hex[:10]
    app_login, worker_login = f"geo_question_app_{suffix}", f"geo_question_worker_{suffix}"
    app_password, worker_password = uuid4().hex, uuid4().hex
    campaign_id = uuid4()
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
        project = seed_project(admin, suffix=f"question-{suffix}")
        admin.execute(
            """INSERT INTO geo_campaigns
                 (id, project_id, market_profile_id, primary_product_entity_id,
                  name, status, created_by)
               VALUES (%s, %s, %s, %s, %s, 'active', %s)""",
            (
                campaign_id,
                project["project"],
                project["market"],
                project["entity"],
                f"Question campaign {suffix}",
                project["owner"],
            ),
        )
        admin.commit()

    app_url = login_url(ADMIN_URL, user=app_login, password=app_password)
    worker_url = login_url(ADMIN_URL, user=worker_login, password=worker_password)
    principal = _principal(project, suffix)
    policy = KnowledgeRagEnqueuePolicy(
        adapter_release=SELECTION.adapter_release,
        selection_manifest_hash=SELECTION_HASH,
        configured_model="deepseek-v4-flash",
    )
    knowledge = KnowledgeApplication(app_url, question_policy=policy)
    try:
        source = knowledge.create_source(
            principal,
            project_id=project["project"],
            source=_source("每分钟 2 升"),
            idempotency_key=f"question-source-{suffix}",
        )
        _process_source(_dispatcher(worker_url, suffix), source, project["project"])
        entities = knowledge.list_rag_entity_candidates(principal, project_id=project["project"])
        relations = knowledge.list_rag_relation_candidates(principal, project_id=project["project"])
        _approve_graph(knowledge, principal, project["project"], entities, relations)
        entities = knowledge.list_rag_entity_candidates(principal, project_id=project["project"])
        fact = knowledge.list_facts(principal, project_id=project["project"])[0]
        knowledge.review_fact(
            principal,
            project_id=project["project"],
            fact_id=fact["id"],
            decision="approved",
            notes="approved for grounded question generation",
        )

        created = knowledge.create_question_generation(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            dimensions=_dimensions(),
            fact_candidate_ids=(fact["id"],),
            graph_entity_ids=tuple(dict.fromkeys(item["graph_entity_id"] for item in entities)),
            configured_model="deepseek-v4-flash",
            model_call_budget=10,
            semantic_duplicate_threshold=0.92,
            idempotency_key=f"question-generation-{suffix}",
        )
        generated = _question_dispatcher(worker_url, suffix).process(
            job_id=created["job_id"], project_id=project["project"]
        )
        if generated["status"] != "succeeded":
            with psycopg.connect(ADMIN_URL) as diagnostic:
                generated = {
                    **generated,
                    "failure": diagnostic.execute(
                        "SELECT error_code, error_detail FROM durable_jobs WHERE id = %s",
                        (created["job_id"],),
                    ).fetchone(),
                }
        assert generated["status"] == "succeeded", generated
        generations = knowledge.list_question_generations(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
        )
        assert len(generations) == 1
        assert generations[0]["configured_model"] == "deepseek-v4-flash"
        assert generations[0]["execution_backend"] == "native"
        assert generations[0]["actual_model"] == "deepseek-v4-flash"
        candidates = knowledge.list_question_candidates(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            generation_job_id=created["job_id"],
        )
        assert len(candidates) == 11
        assert sum(item["dedup_status"] == "possible_duplicate" for item in candidates) == 1
        assert all(item["fact_source_ids"] == [fact["id"]] for item in candidates)
        for candidate in candidates:
            knowledge.review_question_candidate(
                principal,
                project_id=project["project"],
                campaign_id=campaign_id,
                candidate_id=candidate["id"],
                decision="approved",
            )

        question_set = knowledge.create_question_set(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            name="F019 governed test questions",
            generation_job_id=created["job_id"],
            candidate_ids=tuple(item["id"] for item in candidates),
            series_id=None,
            previous_version_id=None,
            idempotency_key=f"question-set-{suffix}",
        )
        assert question_set["coverage_ratio"] == Decimal("1.0000")
        assert question_set["duplicate_ratio"] == Decimal("0.0909")
        knowledge.approve_question_set(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            question_set_id=question_set["id"],
        )
        frozen = knowledge.freeze_question_set(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            question_set_id=question_set["id"],
        )
        assert frozen["status"] == "frozen"
        assert len(str(frozen["content_hash"])) == 64

        protocol = _monitoring(app_url).create_protocol(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            market_profile_id=project["market"],
            name=f"Question protocol {suffix}",
            platform=Platform.CHATGPT_SEARCH,
            locale="en-AU",
            device=Device.DESKTOP,
            sample_size=3,
            minimum_valid_repeats=3,
            window_days=84,
            source_strata=(_stratum(),),
        )
        bound = _monitoring(app_url).bind_question_set(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            protocol_id=protocol.id,
            question_set_id=frozen["id"],
            confirmed_content_hash=str(frozen["content_hash"]),
        )
        assert bound.question_set_id == frozen["id"]
        assert bound.question_set_hash == frozen["content_hash"]
        _assert_inventory_and_immutability(
            app_url,
            project["project"],
            campaign_id,
            protocol.id,
            frozen["id"],
            len(candidates),
        )
        next_version = knowledge.create_question_set(
            principal,
            project_id=project["project"],
            campaign_id=campaign_id,
            name="F019 governed test questions v2",
            generation_job_id=created["job_id"],
            candidate_ids=tuple(item["id"] for item in candidates),
            series_id=frozen["series_id"],
            previous_version_id=frozen["id"],
            idempotency_key=f"question-set-v2-{suffix}",
        )
        assert next_version["version_number"] == 2
        assert next_version["status"] == "draft"
        assert (
            frozen["content_hash"]
            == knowledge.list_question_sets(
                principal, project_id=project["project"], campaign_id=campaign_id
            )[1]["content_hash"]
        )
        _assert_geo_question_simulation(
            knowledge=knowledge,
            principal=principal,
            app_url=app_url,
            worker_url=worker_url,
            project=project,
            campaign_id=campaign_id,
            fact_id=fact["id"],
            question_set=frozen,
            suffix=suffix,
        )
    finally:
        with psycopg.connect(ADMIN_URL) as admin:
            cleanup_projects(
                admin,
                projects=[project],
                tenant_ids=[project["tenant"]],
                app_login=app_login,
                worker_login=worker_login,
            )
            admin.commit()


def _question(**values: object) -> dict[str, object]:
    return {
        "candidate_id": values["candidate_id"],
        "dimension_key": values["dimension_key"],
        "variant_index": values["variant_index"],
        "text": values["text"],
        "semantic_fingerprint": values["semantic"],
        "supported_fact_ids": [values["fact_id"]],
        "supported_entity_ids": values["entity_ids"],
        "parent_candidate_id": None,
    }


def _assert_geo_question_simulation(
    *,
    knowledge: KnowledgeApplication,
    principal: Any,
    app_url: str,
    worker_url: str,
    project: dict[str, UUID],
    campaign_id: UUID,
    fact_id: UUID,
    question_set: Mapping[str, object],
    suffix: str,
) -> None:
    promoted = knowledge.promote_fact_to_evidence(
        principal,
        project_id=project["project"],
        fact_id=fact_id,
        idempotency_key=f"question-evidence-{suffix}",
        title="F019 grounded simulation Evidence",
        subject_entity_id=project["entity"],
        subject_role=SubjectRole.PRODUCT,
        usage_rights=UsageRights.PUBLIC_REFERENCE,
        confidentiality=Confidentiality.PUBLIC,
        public_citation=PublicCitation(
            True,
            source_url="https://example.test/f019-fact",
            source_title="F019 grounded Fact",
            label="F019 Fact",
            attribution_required=True,
        ),
    )
    evidence = promoted["evidence"]
    assert isinstance(evidence, Mapping)
    evidence_id = evidence["id"]
    assert isinstance(evidence_id, UUID)
    brand_id, opportunity_id = uuid4(), uuid4()
    placement = PlacementApplication(
        placement_uow_factory(lambda: psycopg.connect(app_url)),
        artifact_reader=MemoryArtifactStore(),
    )
    destination = placement.create_destination(
        project_id=project["project"],
        publication_channel="productreview",
        destination_key=f"question-simulation-{suffix}",
        operation_mode="manual",
        destination_account_id=None,
        canonical_url="https://www.productreview.com.au/",
    )
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """INSERT INTO product_entities
                 (id, project_id, entity_type, canonical_name)
               VALUES (%s, %s, 'brand', %s)""",
            (brand_id, project["project"], f"Question Brand {suffix}"),
        )
        admin.execute(
            """INSERT INTO placement_opportunities
                 (id, project_id, campaign_id, destination_id,
                  opportunity_ref, rationale)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                opportunity_id,
                project["project"],
                campaign_id,
                destination.id,
                f"question-simulation-{suffix}",
                "Exercise the frozen GEO question",
            ),
        )
        admin.execute(
            """INSERT INTO opportunity_prompt_release_bindings
                 (project_id, campaign_id, opportunity_id, destination_id,
                  binding_version, binding_state, changed_by, change_reason)
               VALUES (%s, %s, %s, %s, 1, 'unbound', %s, %s)""",
            (
                project["project"],
                campaign_id,
                opportunity_id,
                destination.id,
                project["owner"],
                "Initial F019 simulation binding state",
            ),
        )
        admin.commit()
    bindings = placement.install_default_prompt_catalog(
        project_id=project["project"], actor_id=project["owner"]
    )
    release_id = next(
        item["template_release_id"] for item in bindings if item["task_key"] == "productreview"
    )
    release = next(
        item
        for skill in placement.list_prompt_skills(project_id=project["project"])
        for item in placement.list_prompt_releases(project_id=project["project"], skill_id=skill.id)
        if item.id == release_id
    )
    prompt_binding = placement.bind_opportunity_prompt_release(
        project_id=project["project"],
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        release_id=release.id,
        expected_binding_version=1,
        reason="Freeze F019 GEO simulation Release",
        actor_id=project["owner"],
        idempotency_key=f"question-prompt-binding-{suffix}",
    )
    items = question_set["items"]
    assert isinstance(items, list) and items
    first_item = items[0]
    assert isinstance(first_item, Mapping)
    artifact_store = MemoryArtifactStore()
    artifact_store.fail_next = False
    placement = PlacementApplication(
        placement_uow_factory(lambda: psycopg.connect(app_url)),
        artifact_reader=artifact_store,
    )
    before = _formal_output_counts(project["project"])
    simulation, job = placement.create_prompt_simulation(
        project_id=project["project"],
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        destination_id=destination.id,
        prompt_release_binding_id=prompt_binding.id,
        confirmed_release_hash=release.release_hash,
        primary_brand_entity_id=brand_id,
        product_entity_id=project["entity"],
        authenticity_mode="synthetic_testimonial",
        evidence_item_ids=(evidence_id,),
        goals={"deliverable": "grounded GEO question test"},
        constraints={"locale": "en-AU"},
        variables={},
        model_policy_hash="a" * 64,
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        requested_by=project["owner"],
        idempotency_key=f"question-simulation-{suffix}",
        simulation_purpose="geo_question_test",
        question_set_id=question_set["id"],
        confirmed_question_set_hash=str(question_set["content_hash"]),
        question_set_item_id=first_item["id"],
    )
    stale_simulation, stale_job = placement.create_prompt_simulation(
        project_id=project["project"],
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        destination_id=destination.id,
        prompt_release_binding_id=prompt_binding.id,
        confirmed_release_hash=release.release_hash,
        primary_brand_entity_id=brand_id,
        product_entity_id=project["entity"],
        authenticity_mode="synthetic_testimonial",
        evidence_item_ids=(evidence_id,),
        goals={"deliverable": "queued stale GEO question test"},
        constraints={"locale": "en-AU"},
        variables={},
        model_policy_hash="b" * 64,
        configured_model="deepseek-v4-flash",
        model_call_budget=1,
        requested_by=project["owner"],
        idempotency_key=f"question-simulation-stale-{suffix}",
        simulation_purpose="geo_question_test",
        question_set_id=question_set["id"],
        confirmed_question_set_hash=str(question_set["content_hash"]),
        question_set_item_id=first_item["id"],
    )
    assert simulation.simulation_purpose == "geo_question_test"
    assert simulation.question_candidate_id == first_item["question_candidate_id"]
    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    repository = PlacementWorkerRepository(store)
    generated = PlacementWorkerDispatcher(
        store=store,
        handlers={
            "prompt_simulation.generate": PromptSimulationHandler(
                store=store,
                repository=repository,
                gateway=FakeGateway(evidence_id),
                lease_for=timedelta(seconds=30),
            )
        },
        worker_id=f"question-simulation-{suffix}",
        lease_for=timedelta(seconds=30),
    ).process(job_id=job.id, project_id=project["project"])
    if generated["status"] != "succeeded":
        with psycopg.connect(ADMIN_URL) as diagnostic:
            generated = {
                **generated,
                "failure": diagnostic.execute(
                    "SELECT error_code, error_detail FROM durable_jobs WHERE id = %s",
                    (job.id,),
                ).fetchone(),
            }
    assert generated["status"] == "succeeded", generated
    artifact_job_id = _artifact_job(store, project["project"], simulation.id)
    finalized = PlacementWorkerDispatcher(
        store=store,
        handlers={
            "artifact.finalize": ArtifactFinalizeHandler(
                store=store,
                repository=PlacementArtifactRepository(store),
                object_store=artifact_store,
            )
        },
        worker_id=f"question-artifact-{suffix}",
        lease_for=timedelta(seconds=30),
    ).process(job_id=artifact_job_id, project_id=project["project"])
    assert finalized["status"] == "finalized"
    detail = placement.get_prompt_simulation(
        project_id=project["project"],
        campaign_id=campaign_id,
        simulation_id=simulation.id,
    )
    assert detail is not None and detail.artifact_manifest is not None
    assert detail.input_snapshot is not None
    assert detail.artifact_manifest["question_binding"] == detail.input_snapshot["question_binding"]
    assert detail.artifact_manifest["test_only"] is True
    assert detail.artifact_manifest["publication_eligible"] is False
    with psycopg.connect(ADMIN_URL) as admin:
        admin.execute(
            """UPDATE knowledge_chunks SET status = 'disabled'
               WHERE project_id = %s AND id = (
                 SELECT chunk_id FROM knowledge_fact_candidates
                 WHERE project_id = %s AND id = %s
               )""",
            (project["project"], project["project"], fact_id),
        )
        admin.commit()
    stale_gateway = FakeGateway(evidence_id)
    stale = PlacementWorkerDispatcher(
        store=store,
        handlers={
            "prompt_simulation.generate": PromptSimulationHandler(
                store=store,
                repository=repository,
                gateway=stale_gateway,
                lease_for=timedelta(seconds=30),
            )
        },
        worker_id=f"question-simulation-stale-{suffix}",
        lease_for=timedelta(seconds=30),
    ).process(job_id=stale_job.id, project_id=project["project"])
    assert stale["status"] == "failed"
    assert stale_gateway.requests == []
    assert (
        placement.get_prompt_simulation(
            project_id=project["project"],
            campaign_id=campaign_id,
            simulation_id=stale_simulation.id,
        )
        is not None
    )
    assert _formal_output_counts(project["project"]) == before


def _artifact_job(store: PostgresDurableJobStore, project_id: UUID, simulation_id: UUID) -> UUID:
    connection = store.open_project(project_id)
    try:
        row = connection.execute(
            """SELECT job_id FROM artifact_finalize_outbox
               WHERE project_id = %s AND resource_kind = 'prompt_simulation'
                 AND resource_id = %s""",
            (project_id, simulation_id),
        ).fetchone()
        connection.commit()
    finally:
        connection.close()
    assert row is not None
    return row[0]


def _formal_output_counts(project_id: UUID) -> tuple[int, ...]:
    with psycopg.connect(ADMIN_URL) as admin:
        row = admin.execute(
            """SELECT
                 (SELECT count(*) FROM monitoring_observations WHERE project_id = %s),
                 (SELECT count(*) FROM monitoring_metric_snapshots WHERE project_id = %s),
                 (SELECT count(*) FROM monitoring_reports WHERE project_id = %s),
                 (SELECT count(*) FROM publication_requests WHERE project_id = %s),
                 (SELECT count(*) FROM publication_submissions WHERE project_id = %s)""",
            (project_id,) * 5,
        ).fetchone()
    assert row is not None
    return tuple(int(value) for value in row)


def _dimensions() -> tuple[QuestionDimensionDraft, ...]:
    return tuple(
        QuestionDimensionDraft(
            dimension_key=f"dimension-{index:02d}",
            persona=f"buyer-{index}",
            scenario=f"evaluation-{index}",
            intent=f"criterion-{index}",
            funnel="consideration",
            region="AU",
            language="en-AU",
            brand_scope="brand",
            platform="chatgpt_search",
            query_kind="research",
            subject=f"A1 criterion {index}",
        )
        for index in range(10)
    )


def _question_dispatcher(
    worker_url: str, suffix: str, *, gateway: Any | None = None
) -> PlacementWorkerDispatcher:
    store = PostgresDurableJobStore(lambda: psycopg.connect(worker_url))
    return PlacementWorkerDispatcher(
        store=store,
        handlers={
            "knowledge.question.generate": KnowledgeQuestionGenerateHandler(
                store=store,
                repository=KnowledgeQuestionPostgresRepository(store),
                gateway=gateway or QuestionGateway(),
                object_store=_object_store(suffix),
                selection=SELECTION,
                selection_manifest_hash=SELECTION_HASH,
                lease_for=timedelta(seconds=30),
            )
        },
        worker_id=f"f019-question-{suffix}",
        lease_for=timedelta(seconds=30),
    )


def _monitoring(database_url: str) -> MonitoringApplication:
    return MonitoringApplication(PsycopgMonitoringUnitOfWorkFactory(database_url))


def _stratum() -> SourceStratumKey:
    return ObservationSource(
        capture_method=CaptureMethod.MANUAL_UI,
        platform=ObservationPlatform.OPENAI,
        surface=ObservationSurface.CHATGPT_SEARCH,
        surface_kind=SurfaceKind.CONSUMER_UI,
        platform_detail=None,
        surface_detail=None,
        configured_model=ModelIdentity(ModelIdentityState.DISCLOSED, "integration-model"),
        reported_model=ModelIdentity(ModelIdentityState.NOT_DISCLOSED, None),
        run=ObservationRunParameters(
            engine="chatgpt",
            locale="en-AU",
            region="AU",
            language="en",
            device=ObservationDevice.DESKTOP,
            client_kind=ClientKind.BROWSER,
            search_enabled=True,
            search_mode=SearchMode.LIVE_WEB,
            prompt_text=None,
        ),
        raw_evidence=RawEvidence(RawEvidenceKind.ANSWER, answer="fixture"),
        citations_captured=True,
    ).stratum_key()


def _assert_inventory_and_immutability(
    app_url: str,
    project_id: UUID,
    campaign_id: UUID,
    protocol_id: UUID,
    question_set_id: UUID,
    item_count: int,
) -> None:
    with psycopg.connect(app_url) as connection:
        connection.execute("SELECT set_config('geo.project_id', %s, true)", (str(project_id),))
        connection.execute(
            "SELECT set_config('geo.project_ids', %s, true)",
            (json.dumps([str(project_id)]),),
        )
        counts = connection.execute(
            """SELECT
                 (SELECT count(*) FROM knowledge_question_set_items
                  WHERE question_set_id = %s),
                 (SELECT count(*) FROM monitoring_query_suggestions
                  WHERE protocol_id = %s AND question_set_item_id IS NOT NULL),
                 (SELECT count(*) FROM monitoring_protocol_queries
                  WHERE protocol_id = %s AND question_set_item_id IS NOT NULL),
                 geo_protocol_question_inventory_complete(%s)""",
            (question_set_id, protocol_id, protocol_id, protocol_id),
        ).fetchone()
        assert counts == (item_count, item_count, item_count, True)
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                "UPDATE knowledge_question_sets SET name = 'mutated' WHERE id = %s",
                (question_set_id,),
            )
        connection.rollback()
        connection.execute("SELECT set_config('geo.project_id', %s, true)", (str(project_id),))
        connection.execute(
            "SELECT set_config('geo.project_ids', %s, true)",
            (json.dumps([str(project_id)]),),
        )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                """UPDATE monitoring_protocols
                   SET question_set_id = NULL, question_set_hash = NULL,
                       question_set_bound_by = NULL, question_set_bound_at = NULL
                   WHERE id = %s AND campaign_id = %s""",
                (protocol_id, campaign_id),
            )
