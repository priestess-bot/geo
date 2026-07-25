from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
from typing import cast
from uuid import uuid4

from alembic import command as alembic_command
from alembic.config import Config
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from geo_api.workflow_c_presenters import semantic_snapshot_response
from geo_core.alerts import AlertRuleKind, AlertSeverity
from geo_core.alerts.postgres_operations import PostgresWorkflowCAlertEvaluateOperation
from geo_core.project_scope import set_project_scope
from geo_core.recommendations import (
    DownstreamDraftKind,
    MetricComparisonRef,
    ObservationRef,
    RecommendationEvidenceKind,
    RecommendationEvidenceSelector,
    RecommendationScope,
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
from geo_core.recommendations.postgres.evidence import (
    PostgresRecommendationEvidenceResolver,
)
from geo_core.recommendations.postgres.generation_submission import (
    PsycopgRecommendationGenerationSubmission,
)
from geo_core.recommendations.postgres.generation_worker import (
    RecommendationParentHandler,
)
from geo_core.recommendations.postgres.generation_worker_repository import (
    PostgresRecommendationGenerationWorkerRepository,
)
from geo_core.recommendations.postgres.prompt_runtime import (
    build_recommendation_prompt_resolver,
)
from geo_core.secrets import EnvelopeCipher, MasterKeyring
from geo_core.workflow_c_analysis_admission import (
    MetricProtocolStatus,
    new_metric_protocol,
)
from geo_core.workflow_c_alert_admission import (
    AlertEvaluationSelector,
    PostgresWorkflowCAlertAdmissionRepository,
)
from geo_core.workflow_c_alert_rules import (
    AlertRuleReleaseStatus,
    PostgresWorkflowCAlertRuleRepository,
)
from geo_core.workflow_c_analysis_protocols import (
    PostgresWorkflowCMetricProtocolRepository,
)
from geo_core.workflow_c_analysis_reads import (
    PostgresWorkflowCAnalysisReadRepository,
)
from geo_core.workflow_c_analysis_worker import (
    PostgresWorkflowCComparisonOperation,
    PostgresWorkflowCDriftOperation,
    PostgresWorkflowCSemanticMetricOperation,
)
from geo_core.workflow_c_artifacts.postgres import (
    synchronize_workflow_c_artifact_master_keys,
)
from geo_core.workflow_c_semantic_admission import (
    PostgresWorkflowCSemanticAdmissionRepository,
)
from geo_core.workflow_c_semantic_materialization import (
    PostgresWorkflowCSemanticInputMaterializer,
)
from geo_core.workflow_c_statistical_admission import (
    PostgresWorkflowCStatisticalAdmissionRepository,
)
from geo_core.workflow_c_statistical_protocols import (
    ComparisonPlanDefinition,
    DriftProtocolDefinition,
    PostgresWorkflowCStatisticalProtocolRepository,
)
from tests.integration.monitoring_postgres_support import (
    isolated_minio_store,
    isolated_valkey_url,
)
from tests.integration.placement_worker_support import login_url, seed_project
from tests.integration.test_workflow_c_artifact_maintenance_postgres import (
    _database_url,
    _seed_manual_runtime_option,
)
from tests.integration.test_recommendation_postgres_lifecycle import (
    _RECOMMENDATION_RUNTIME_OPTION_ID,
    _RecommendationRuntimeCatalog,
    _principal,
    _recommendation_runtime_selection,
    _seed_approved_fact,
    _seed_frozen_question,
    _seed_frozen_recommendation_prompt,
)
from tests.workflow_c_analysis_test_support import metric_protocol_definition_fixture
from tests.integration.workflow_c_semantic_vertical_support import (
    _ProviderRecoveryForbidden,
    _UnusedRecommendationDependency,
    _approved_statistical_protocol,
    _assert_outbox_relayed_through_valkey,
    _assert_secret_free_lineage,
    create_and_process_manual_observations,
)


ADMIN_URL = os.getenv("GEO_PLACEMENT_TEST_ADMIN_URL", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not ADMIN_URL, reason="GEO_PLACEMENT_TEST_ADMIN_URL is required"),
]


def test_real_manual_artifacts_flow_through_v2_job_to_fenced_semantic_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    database_name = f"geo_wfc_semantic_vertical_{suffix}"
    database_url = _database_url(ADMIN_URL, database_name)
    app_login, app_password = f"geo_semantic_app_{suffix}", uuid4().hex
    worker_login, worker_password = f"geo_semantic_worker_{suffix}", uuid4().hex
    created_database = False
    created_roles = False
    try:
        with psycopg.connect(ADMIN_URL, autocommit=True) as server:
            server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created_database = True
        migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        migration.attributes["geo_database_url_override"] = database_url
        alembic_command.upgrade(migration, "head")
        alembic_command.downgrade(migration, "0074_wfc_semantic_job_v2")
        alembic_command.upgrade(migration, "head")
        with psycopg.connect(database_url) as admin:
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
            created_roles = True
            seeded = seed_project(admin, suffix=f"semantic-vertical-{suffix}")
            project_id = seeded["project"]
            fact_id = _seed_approved_fact(admin, seeded=seeded)
            question_id = _seed_frozen_question(admin, seeded=seeded)
            _seed_manual_runtime_option(
                admin,
                project_id=project_id,
                platform="google",
                adapter_release="manual-google-aio-v1",
            )

        app_url = login_url(database_url, user=app_login, password=app_password)
        worker_url = login_url(database_url, user=worker_login, password=worker_password)

        def app_connect():
            return psycopg.connect(app_url, row_factory=dict_row)

        def worker_connect():
            return psycopg.connect(worker_url, row_factory=dict_row)

        now = datetime.now(UTC).replace(microsecond=0)
        creator = _principal(seeded, seeded["owner"], "analyst")
        reviewer = _principal(seeded, seeded["reviewer"], "admin")
        recommendation_prompt_binding_id = _seed_frozen_recommendation_prompt(
            app_url=app_url,
            seeded=seeded,
            owner=creator,
            reviewer=reviewer,
        )
        cipher = EnvelopeCipher(MasterKeyring(keys={1: b"S" * 32}, active_version=1))
        with psycopg.connect(database_url, row_factory=dict_row) as admin:
            assert synchronize_workflow_c_artifact_master_keys(admin, cipher) == (1,)

        with isolated_minio_store() as objects, isolated_valkey_url() as valkey_url:
            (
                run_id,
                runs,
                suite,
                artifact_reader,
                store,
                specs,
            ) = create_and_process_manual_observations(
                objects=objects,
                app_connect=app_connect,
                worker_connect=worker_connect,
                project_id=project_id,
                question_id=question_id,
                now=now,
                cipher=cipher,
            )
            definition = replace(
                metric_protocol_definition_fixture(),
                question_clusters=((str(question_id), "purchase"),),
            )
            protocols = PostgresWorkflowCMetricProtocolRepository(
                connect=app_connect,
                clock=lambda: now,
            )
            draft = protocols.create(
                new_metric_protocol(
                    project_id=project_id,
                    definition=definition,
                    actor_id="metric-maker",
                    idempotency_key="semantic-vertical:protocol",
                    occurred_at=now,
                ),
                idempotency_key="semantic-vertical:protocol",
            )
            submitted_protocol = protocols.transition(
                project_id=project_id,
                protocol_id=draft.id,
                expected_aggregate_version=draft.aggregate_version,
                target_status=MetricProtocolStatus.IN_REVIEW,
                actor_id="metric-maker",
                idempotency_key="semantic-vertical:protocol:submit",
                occurred_at=now,
            )
            approved_protocol = protocols.transition(
                project_id=project_id,
                protocol_id=draft.id,
                expected_aggregate_version=submitted_protocol.aggregate_version,
                target_status=MetricProtocolStatus.APPROVED,
                actor_id="metric-checker",
                reason="fixed semantic regression contract passed",
                idempotency_key="semantic-vertical:protocol:approve",
                occurred_at=now,
            )
            admitted = PostgresWorkflowCSemanticAdmissionRepository(
                connect=app_connect,
                clock=lambda: now,
            ).enqueue(
                project_id=project_id,
                sampling_run_id=run_id,
                metric_protocol_id=approved_protocol.id,
                actor_id="analysis-operator",
                idempotency_key="semantic-vertical:analysis",
            )
            semantic_claim = store.claim(
                job_id=admitted.job.job_id,
                project_id=project_id,
                expected_kind="workflow_c.analysis.semantic_metrics",
                worker_id="semantic-vertical",
                lease_for=timedelta(seconds=60),
            )
            assert semantic_claim.lease is not None
            result = PostgresWorkflowCSemanticMetricOperation(
                store=store,
                specs=specs,
                lease_for=timedelta(seconds=60),
                semantic_materializer=PostgresWorkflowCSemanticInputMaterializer(
                    connect=worker_connect,
                    manual_artifacts=artifact_reader,
                    provider_artifacts=_ProviderRecoveryForbidden(),
                    clock=lambda: now,
                ),
                clock=lambda: now,
            ).execute(semantic_claim.lease)

            assert result["status"] == "complete"
            snapshots = PostgresWorkflowCAnalysisReadRepository(
                connect=app_connect
            ).list_semantic_snapshots(project_id=project_id)
            assert len(snapshots) == 1
            assert snapshots[0].snapshot_hash == result["snapshot_hash"]
            projection = semantic_snapshot_response(project_id, snapshots[0])
            assert projection.results[0].denominator == 3
            assert projection.results[0].valid_input_count == 3
            assert projection.results[0].status == "complete"
            _assert_outbox_relayed_through_valkey(
                monkeypatch,
                worker_connect=worker_connect,
                database_url=database_url,
                valkey_url=valkey_url,
                project_id=project_id,
                semantic_job_id=admitted.job.job_id,
            )
            _assert_secret_free_lineage(
                database_url,
                project_id=project_id,
                job_id=admitted.job.job_id,
            )
            candidate_definition = replace(
                definition,
                approved_corpus_version="corpus-v2",
                approved_corpus_hash="b" * 64,
                corpus_version_id=uuid4(),
                corpus_version_hash="b" * 64,
            )
            candidate_draft = protocols.create(
                new_metric_protocol(
                    project_id=project_id,
                    definition=candidate_definition,
                    actor_id="metric-maker",
                    idempotency_key="semantic-vertical:candidate-protocol",
                    occurred_at=now,
                    predecessor=approved_protocol,
                ),
                idempotency_key="semantic-vertical:candidate-protocol",
            )
            candidate_submitted = protocols.transition(
                project_id=project_id,
                protocol_id=candidate_draft.id,
                expected_aggregate_version=candidate_draft.aggregate_version,
                target_status=MetricProtocolStatus.IN_REVIEW,
                actor_id="metric-maker",
                idempotency_key="semantic-vertical:candidate-protocol:submit",
                occurred_at=now,
            )
            candidate_approved = protocols.transition(
                project_id=project_id,
                protocol_id=candidate_draft.id,
                expected_aggregate_version=candidate_submitted.aggregate_version,
                target_status=MetricProtocolStatus.APPROVED,
                actor_id="metric-checker",
                reason="candidate corpus lineage reviewed",
                idempotency_key="semantic-vertical:candidate-protocol:approve",
                occurred_at=now,
            )
            candidate_job = PostgresWorkflowCSemanticAdmissionRepository(
                connect=app_connect,
                clock=lambda: now,
            ).enqueue(
                project_id=project_id,
                sampling_run_id=run_id,
                metric_protocol_id=candidate_approved.id,
                actor_id="analysis-operator",
                idempotency_key="semantic-vertical:candidate-analysis",
            )
            candidate_claim = store.claim(
                job_id=candidate_job.job.job_id,
                project_id=project_id,
                expected_kind="workflow_c.analysis.semantic_metrics",
                worker_id="semantic-vertical-candidate",
                lease_for=timedelta(seconds=60),
            )
            assert candidate_claim.lease is not None
            candidate_result = PostgresWorkflowCSemanticMetricOperation(
                store=store,
                specs=specs,
                lease_for=timedelta(seconds=60),
                semantic_materializer=PostgresWorkflowCSemanticInputMaterializer(
                    connect=worker_connect,
                    manual_artifacts=artifact_reader,
                    provider_artifacts=_ProviderRecoveryForbidden(),
                    clock=lambda: now,
                ),
                clock=lambda: now,
            ).execute(candidate_claim.lease)
            assert candidate_result["snapshot_hash"] != result["snapshot_hash"]

            statistical_protocols = PostgresWorkflowCStatisticalProtocolRepository(
                connect=app_connect,
                clock=lambda: now,
            )
            comparison_plan = _approved_statistical_protocol(
                statistical_protocols,
                project_id=project_id,
                definition=ComparisonPlanDefinition(
                    family="semantic-primary",
                    question_clusters=("purchase",),
                    alpha=Decimal("0.05"),
                    delta=Decimal("0.05"),
                    target_power=Decimal("0.80"),
                    precision=Decimal("0.20"),
                    min_pairs=3,
                    power_plan_hash="c" * 64,
                    a_priori_design_power=Decimal("0.90"),
                    bootstrap_iterations=100,
                ),
                key="semantic-vertical:comparison-plan",
                now=now,
            )
            drift_protocol = _approved_statistical_protocol(
                statistical_protocols,
                project_id=project_id,
                definition=DriftProtocolDefinition(minimum_question_count=1),
                key="semantic-vertical:drift-protocol",
                now=now,
            )
            statistical_admission = PostgresWorkflowCStatisticalAdmissionRepository(
                connect=app_connect
            )
            comparison_job = statistical_admission.enqueue_comparison(
                project_id=project_id,
                comparison_plan_id=comparison_plan.id,
                baseline_snapshot_hash=result["snapshot_hash"],
                candidate_snapshot_hash=candidate_result["snapshot_hash"],
                actor_id="analysis-operator",
                idempotency_key="semantic-vertical:comparison",
            )
            comparison_replay = statistical_admission.enqueue_comparison(
                project_id=project_id,
                comparison_plan_id=comparison_plan.id,
                baseline_snapshot_hash=result["snapshot_hash"],
                candidate_snapshot_hash=candidate_result["snapshot_hash"],
                actor_id="analysis-operator",
                idempotency_key="semantic-vertical:comparison",
            )
            assert comparison_replay.replayed is True
            assert comparison_replay.job_id == comparison_job.job_id
            comparison_claim = store.claim(
                job_id=comparison_job.job_id,
                project_id=project_id,
                expected_kind="workflow_c.analysis.comparison",
                worker_id="comparison-vertical",
                lease_for=timedelta(seconds=60),
            )
            assert comparison_claim.lease is not None
            comparison_result = PostgresWorkflowCComparisonOperation(
                store=store,
                specs=specs,
                lease_for=timedelta(seconds=60),
            ).execute(comparison_claim.lease)
            drift_job = statistical_admission.enqueue_drift(
                project_id=project_id,
                drift_protocol_id=drift_protocol.id,
                baseline_snapshot_hash=result["snapshot_hash"],
                current_snapshot_hash=candidate_result["snapshot_hash"],
                actor_id="analysis-operator",
                idempotency_key="semantic-vertical:drift",
            )
            drift_claim = store.claim(
                job_id=drift_job.job_id,
                project_id=project_id,
                expected_kind="workflow_c.analysis.drift",
                worker_id="drift-vertical",
                lease_for=timedelta(seconds=60),
            )
            assert drift_claim.lease is not None
            drift_result = PostgresWorkflowCDriftOperation(
                store=store,
                specs=specs,
                lease_for=timedelta(seconds=60),
            ).execute(drift_claim.lease)
            reads = PostgresWorkflowCAnalysisReadRepository(connect=app_connect)
            comparison_projection = reads.get_comparison_family(
                project_id=project_id,
                family_hash=comparison_result["family_hash"],
            )
            drift_projection = reads.get_drift_report(
                project_id=project_id,
                report_hash=drift_result["report_hash"],
            )
            assert comparison_projection.payload["results"][0]["conclusion"] == (
                "insufficient_evidence"
            )
            assert drift_projection.payload["protocol_hash"] == (drift_protocol.definition_hash)
            comparison_id = comparison_projection.payload["results"][0]["comparison_id"]
            with app_connect() as evidence_connection:
                set_project_scope(evidence_connection, project_id)
                observation_ids = tuple(
                    row["id"]
                    for row in evidence_connection.execute(
                        """SELECT id FROM workflow_c_sampling_observations
                             WHERE project_id = %s AND run_id = %s
                             ORDER BY id""",
                        (project_id, run_id),
                    ).fetchall()
                )
                resolver = PostgresRecommendationEvidenceResolver(evidence_connection, project_id)
                resolved_evidence = resolver.resolve_current(
                    project_id=project_id,
                    selectors=(
                        RecommendationEvidenceSelector(
                            RecommendationEvidenceKind.OBSERVATION,
                            str(observation_ids[0]),
                        ),
                        RecommendationEvidenceSelector(
                            RecommendationEvidenceKind.METRIC_COMPARISON,
                            f"{comparison_result['family_hash']}:{comparison_id}",
                        ),
                    ),
                )
            observation_ref, comparison_ref = resolved_evidence
            assert isinstance(observation_ref, ObservationRef)
            assert observation_ref.evidence_class.value == "real_observation"
            assert observation_ref.surface_resource_id == suite.source_stratum.stratum_hash
            assert isinstance(comparison_ref, MetricComparisonRef)
            assert comparison_ref.observation_resource_ids == tuple(
                str(value) for value in observation_ids
            )
            assert comparison_ref.sufficient_evidence is False

            alert_rules = PostgresWorkflowCAlertRuleRepository(
                connect=app_connect,
                clock=lambda: now,
            )
            alert_draft = alert_rules.create(
                project_id=project_id,
                rule_key="semantic-metric-present",
                version=1,
                kind=AlertRuleKind.THRESHOLD,
                severity=AlertSeverity.WARNING,
                parameters={
                    "schema_version": "alert-rule-threshold-v1",
                    "metric_key": projection.results[0].metric_key,
                    "operator": "gte",
                    "threshold": "0",
                },
                actor_id="alert-maker",
                idempotency_key="semantic-vertical:alert-rule",
            )
            alert_rule = alert_rules.transition(
                project_id=project_id,
                rule_id=alert_draft.id,
                expected_aggregate_version=alert_draft.aggregate_version,
                target_status=AlertRuleReleaseStatus.APPROVED,
                actor_id="alert-checker",
                reason="frozen output binding reviewed",
                idempotency_key="semantic-vertical:alert-rule:approve",
            )
            alert_job = PostgresWorkflowCAlertAdmissionRepository(
                connect=app_connect,
                clock=lambda: now,
            ).enqueue(
                project_id=project_id,
                selector=AlertEvaluationSelector(
                    alert_rule_id=alert_rule.id,
                    source_hash=result["snapshot_hash"],
                ),
                actor_id="alert-operator",
                idempotency_key="semantic-vertical:alert-evaluation",
            )
            alert_claim = store.claim(
                job_id=alert_job.job_id,
                project_id=project_id,
                expected_kind="workflow_c.alert.evaluate",
                worker_id="alert-vertical",
                lease_for=timedelta(seconds=60),
            )
            assert alert_claim.lease is not None
            alert_result = PostgresWorkflowCAlertEvaluateOperation(
                store=store,
                specs=specs,
                clock=lambda: now,
            ).execute(alert_claim.lease)
            assert alert_result["status"] == "matched"
            assert alert_result["notification_count"] == 3
            with app_connect() as connection:
                set_project_scope(connection, project_id)
                alert_row = connection.execute(
                    """SELECT count(*) AS alert_count
                         FROM workflow_c_alerts WHERE project_id = %s""",
                    (project_id,),
                ).fetchone()
                notification_row = connection.execute(
                    """SELECT count(*) AS notification_count
                         FROM workflow_c_alert_notifications WHERE project_id = %s""",
                    (project_id,),
                ).fetchone()
            assert alert_row is not None and alert_row["alert_count"] == 1
            assert notification_row is not None and notification_row["notification_count"] == 3

            recommendation_generation = PsycopgRecommendationGenerationSubmission(
                connection_factory=app_connect,
                runtime_catalog=_RecommendationRuntimeCatalog(
                    _recommendation_runtime_selection(project_id)
                ),
                clock=lambda: now,
            )
            recommendation_selection = RecommendationGenerationSelection(
                project_id=project_id,
                scope=RecommendationScope(
                    project_id,
                    "workflow-c-real-lineage-v1",
                    question_or_cluster_ref=str(question_id),
                    surface_ref=suite.source_stratum.stratum_hash,
                ),
                evidence_selectors=(
                    *tuple(
                        RecommendationEvidenceSelector(
                            RecommendationEvidenceKind.OBSERVATION,
                            str(observation_id),
                        )
                        for observation_id in observation_ids
                    ),
                    RecommendationEvidenceSelector(
                        RecommendationEvidenceKind.METRIC_COMPARISON,
                        f"{comparison_result['family_hash']}:{comparison_id}",
                    ),
                    RecommendationEvidenceSelector(
                        RecommendationEvidenceKind.FACT,
                        str(fact_id),
                    ),
                    RecommendationEvidenceSelector(
                        RecommendationEvidenceKind.RULE,
                        str(alert_rule.id),
                    ),
                    RecommendationEvidenceSelector(
                        RecommendationEvidenceKind.QUESTION,
                        str(question_id),
                    ),
                    RecommendationEvidenceSelector(
                        RecommendationEvidenceKind.SURFACE,
                        suite.source_stratum.stratum_hash,
                    ),
                    RecommendationEvidenceSelector(
                        RecommendationEvidenceKind.ATTRIBUTION,
                        "attribution:board-b-excluded",
                    ),
                ),
                prompt_binding_id=recommendation_prompt_binding_id,
                model=GenerationModelSelector(
                    runtime_selection_id=_RECOMMENDATION_RUNTIME_OPTION_ID
                ),
                valid_until=now + timedelta(days=7),
                minimum_real_observations=3,
            )
            recommendation_job = recommendation_generation.enqueue(
                creator,
                selection=recommendation_selection,
                idempotency_key="semantic-vertical:recommendation",
            )
            recommendation_claim = store.claim(
                job_id=recommendation_job.job.id,
                project_id=project_id,
                expected_kind=RECOMMENDATION_PARENT_JOB_KIND,
                worker_id="semantic-recommendation-vertical",
                lease_for=timedelta(seconds=60),
            )
            assert recommendation_claim.lease is not None
            recommendation_worker = RecommendationParentHandler(
                store=store,
                repository=PostgresRecommendationGenerationWorkerRepository(
                    worker_connect,
                    prompts=build_recommendation_prompt_resolver(connection_factory=worker_connect),
                    artifacts=cast(
                        RecommendationTaskArtifactStore,
                        _UnusedRecommendationDependency("artifact store"),
                    ),
                    model_results=cast(
                        GovernedRecommendationModelResultLoader,
                        _UnusedRecommendationDependency("model result loader"),
                    ),
                ),
                clock=lambda: now,
            )
            recommendation_worker_result = recommendation_worker.handle(recommendation_claim.lease)
            completed_recommendation = recommendation_generation.get(
                creator,
                project_id=project_id,
                job_id=recommendation_job.job.id,
            )
            assert (
                recommendation_worker_result["status"] == "succeeded"
            ), completed_recommendation.job
            generated = completed_recommendation.result
            assert generated is not None
            assert generated.recommendation.recommendation_type.value == ("insufficient_evidence")
            assert generated.recommendation.proposed_draft_kind is (
                DownstreamDraftKind.SAMPLING_PLAN
            )
            assert generated.model_call_ids == ()
            assert generated.insufficient_reasons == (
                "missing_sufficient_metric_comparison",
                "attribution_unavailable:connector_attribution_excluded_from_this_phase",
            )
            generated_evidence = generated.recommendation.evidence
            assert {item.resource_id for item in generated_evidence.observations} == {
                str(value) for value in observation_ids
            }
            assert generated_evidence.metric_comparisons == (comparison_ref,)
            assert generated_evidence.facts[0].resource_id == str(fact_id)
            assert generated_evidence.rules[0].resource_id == str(alert_rule.id)
            assert generated_evidence.questions[0].resource_id == str(question_id)
            assert generated_evidence.surfaces[0].resource_id == (suite.source_stratum.stratum_hash)
            assert generated_evidence.attributions[0].reason == (
                "connector_attribution_excluded_from_this_phase"
            )
            assert len(generated_evidence.prompt_releases) == 1
            with worker_connect() as connection:
                set_project_scope(connection, project_id)
                model_rows = connection.execute(
                    """SELECT
                           (SELECT count(*) FROM recommendation_model_tasks
                             WHERE project_id = %s AND parent_job_id = %s) AS tasks,
                           (SELECT count(*) FROM recommendation_model_call_lineage
                             WHERE project_id = %s AND parent_job_id = %s) AS calls""",
                    (
                        project_id,
                        recommendation_job.job.id,
                        project_id,
                        recommendation_job.job.id,
                    ),
                ).fetchone()
            assert model_rows == {"tasks": 0, "calls": 0}
    finally:
        if created_database:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )
        if created_roles:
            with psycopg.connect(ADMIN_URL, autocommit=True) as server:
                server.execute(
                    sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(worker_login))
                )
                server.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(app_login)))
