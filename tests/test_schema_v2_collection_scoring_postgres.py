from __future__ import annotations

import hashlib
import os
import threading
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Iterator
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb


BEHAVIOR_TEST_ENABLED = os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1"

DOMAIN_TABLES = (
    "product_entities",
    "product_entity_aliases",
    "monitoring_queries",
    "monitoring_query_entities",
    "collection_runs",
    "collection_run_queries",
    "collection_jobs",
    "durable_job_dispatch_outbox",
    "collection_run_summaries",
    "answer_runs",
    "raw_answers",
    "answer_citations",
    "evidence_assets",
    "artifact_finalize_outbox",
    "raw_answer_evidence_assets",
    "answer_citation_evidence_assets",
    "answer_analyses",
    "answer_analysis_entity_mentions",
    "answer_analysis_evidence_assets",
    "collection_costs",
    "model_call_logs",
    "visibility_weight_profiles",
    "visibility_weight_profile_components",
    "visibility_score_runs",
    "visibility_score_run_analyses",
    "visibility_score_snapshots",
    "visibility_score_dimensions",
    "score_contributions",
    "score_contribution_evidence_assets",
    "source_graphs",
    "source_nodes",
    "source_graph_edges",
    "source_node_citations",
    "source_gaps",
    "source_gap_citations",
    "source_gap_score_contributions",
    "competitor_benchmarks",
    "competitor_benchmark_contributions",
    "action_recommendations",
    "action_source_gaps",
    "action_score_contributions",
    "action_competitor_benchmarks",
    "action_tasks",
    "retest_runs",
    "retest_run_queries",
    "retest_comparisons",
    "review_assignments",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2CollectionScoringPostgresTest(unittest.TestCase):
    tenant_id: UUID
    project_a: UUID
    project_b: UUID
    entity_a: UUID
    entity_b: UUID
    actor_id: str
    session_hash: str
    market_code: str
    industry_code: str

    @classmethod
    def setUpClass(cls) -> None:
        unique = uuid4().hex
        cls.tenant_id = uuid4()
        cls.project_a = uuid4()
        cls.project_b = uuid4()
        cls.entity_a = uuid4()
        cls.entity_b = uuid4()
        cls.actor_id = f"collection-scoring-{unique}@example.test"
        cls.session_hash = _digest(f"collection-scoring-session-{unique}")
        cls.market_code = f"B2-{unique}"
        cls.industry_code = f"geo-{unique}"

        now = datetime.now(UTC)
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_profiles (market_code, payload) VALUES (%s, %s)",
                (cls.market_code, Jsonb({"fixture": "collection-scoring"})),
            )
            cursor.execute(
                "INSERT INTO industry_profiles "
                "(market_code, industry_code, payload) VALUES (%s, %s, %s)",
                (
                    cls.market_code,
                    cls.industry_code,
                    Jsonb({"fixture": "collection-scoring"}),
                ),
            )
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                (cls.tenant_id, f"Collection Scoring {unique}", f"collection-scoring-{unique}"),
            )
            for project_id, name in (
                (cls.project_a, "Collection scoring A"),
                (cls.project_b, "Collection scoring B"),
            ):
                cursor.execute(
                    "INSERT INTO projects ("
                    "id, tenant_id, name, market_code, industry_code, target_brand, "
                    "category, prompt_version, status) "
                    "VALUES (%s, %s, %s, %s, %s, 'B2 Brand', 'GEO', 'v1', 'active')",
                    (
                        project_id,
                        cls.tenant_id,
                        name,
                        cls.market_code,
                        cls.industry_code,
                    ),
                )
            cursor.execute(
                "INSERT INTO project_members "
                "(tenant_id, project_id, user_id, role) "
                "VALUES (%s, %s, %s, 'project_owner')",
                (cls.tenant_id, cls.project_a, cls.actor_id),
            )
            for entity_id, project_id, name in (
                (cls.entity_a, cls.project_a, "Primary Brand"),
                (cls.entity_b, cls.project_b, "Other Project Brand"),
            ):
                cursor.execute(
                    "INSERT INTO product_entities ("
                    "id, tenant_id, project_id, entity_kind, canonical_name, "
                    "created_by, updated_by) VALUES (%s, %s, %s, 'brand', %s, %s, %s)",
                    (
                        entity_id,
                        cls.tenant_id,
                        project_id,
                        name,
                        "postgres-fixture",
                        "postgres-fixture",
                    ),
                )

            cursor.execute(
                "SELECT permission FROM unnest("
                "geno_v2_permissions_for_role('project_owner')) AS item(permission) "
                "ORDER BY permission"
            )
            permissions = [row[0] for row in cursor.fetchall()]
            project_scope = {
                "project_id": str(cls.project_a),
                "roles": ["project_owner"],
                "permissions": permissions,
                "portal_capabilities": ["portal.admin.access"],
                "scope_sources": ["direct_member"],
            }
            invitation_id = uuid4()
            attempt_id = uuid4()
            session_id = uuid4()
            invitation_token_hash = _digest(f"collection-scoring-invitation-{unique}")
            invitation_created_at = now - timedelta(seconds=3)
            attempt_created_at = now - timedelta(seconds=2)
            accepted_at = now - timedelta(seconds=1)
            invitation_expires_at = now + timedelta(days=2)
            cursor.execute(
                "INSERT INTO project_member_invitations ("
                "id, tenant_id, project_id, email, role, invite_token_hash, audience, "
                "allowed_surfaces, invited_by, expires_at, created_at) "
                "VALUES (%s, %s, %s, %s, 'project_owner', %s, 'admin', "
                "ARRAY['admin']::text[], 'collection-scoring-test', %s, %s)",
                (
                    invitation_id,
                    cls.tenant_id,
                    cls.project_a,
                    cls.actor_id,
                    invitation_token_hash,
                    invitation_expires_at,
                    invitation_created_at,
                ),
            )
            cursor.execute(
                "INSERT INTO auth_invitation_redemption_attempts ("
                "id, tenant_id, project_id, invitation_id, requested_surface, "
                "idempotency_key_hash, request_hash, token_fingerprint, created_at) "
                "VALUES (%s, %s, %s, %s, 'admin', %s, %s, %s, %s)",
                (
                    attempt_id,
                    cls.tenant_id,
                    cls.project_a,
                    invitation_id,
                    _digest(f"collection-scoring-idempotency-{unique}"),
                    _digest(f"collection-scoring-request-{unique}"),
                    invitation_token_hash,
                    attempt_created_at,
                ),
            )
            cursor.execute(
                "INSERT INTO runtime_sessions ("
                "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
                "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
                "issued_by, issued_at, expires_at, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, %s, %s, "
                "'collection-scoring-test', %s, %s, %s)",
                (
                    session_id,
                    cls.session_hash,
                    cls.actor_id,
                    cls.tenant_id,
                    Jsonb([str(cls.project_a)]),
                    Jsonb(["project_owner"]),
                    Jsonb(permissions),
                    Jsonb([project_scope]),
                    attempt_id,
                    now,
                    now + timedelta(days=1),
                    Jsonb({"fixture": "collection-scoring"}),
                ),
            )
            cursor.execute(
                "UPDATE project_member_invitations SET status = 'accepted', "
                "accepted_by_attempt_id = %s, accepted_at = %s, "
                "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
                "WHERE id = %s",
                (attempt_id, accepted_at, invitation_id),
            )
            cursor.execute(
                "UPDATE auth_invitation_redemption_attempts SET status = 'succeeded', "
                "session_id = %s, delivery_ciphertext = %s, delivery_key_id = %s, "
                "delivery_nonce = %s, delivery_expires_at = %s, "
                "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
                "WHERE id = %s",
                (
                    session_id,
                    b"collection-scoring-encrypted-fixture",
                    "collection-scoring-key",
                    b"b2-nonce-12!",
                    now + timedelta(minutes=15),
                    attempt_id,
                ),
            )

    @contextmanager
    def _runtime_transaction(self) -> Iterator[psycopg.Cursor[object]]:
        connection = psycopg.connect(autocommit=True)
        cursor = connection.cursor()
        try:
            cursor.execute("SET ROLE geno_v2_api_login")
            cursor.execute("BEGIN")
            cursor.execute("SET LOCAL ROLE geno_v2_runtime")
            cursor.execute(
                "SELECT set_config('app.session_token_hash', %s, true)",
                (self.session_hash,),
            )
            yield cursor
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise
        finally:
            cursor.close()
            connection.close()

    @contextmanager
    def _worker_transaction(self) -> Iterator[psycopg.Cursor[object]]:
        connection = psycopg.connect(autocommit=True)
        cursor = connection.cursor()
        try:
            cursor.execute("SET ROLE geno_v2_worker_login")
            cursor.execute("BEGIN")
            cursor.execute("SET LOCAL ROLE geno_v2_worker")
            cursor.execute("SELECT set_config('app.session_token_hash', '', true)")
            yield cursor
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise
        finally:
            cursor.close()
            connection.close()

    def _insert_collection_scope(
        self,
        *,
        job_status: str = "queued",
        max_attempts: int = 3,
    ) -> tuple[UUID, UUID, UUID, UUID | None]:
        marker = uuid4().hex
        query_id = uuid4()
        run_id = uuid4()
        job_id = uuid4()
        old_token = uuid4() if job_status == "running" else None
        now = datetime.now(UTC)
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO monitoring_queries ("
                "id, tenant_id, project_id, query_text, query_hash, "
                "observation_objective, intent_type, market_code, language_code, "
                "device_class, created_by, updated_by) "
                "VALUES (%s, %s, %s, %s, %s, 'discovery', 'informational', "
                "%s, 'en', 'desktop', 'postgres-test', 'postgres-test')",
                (
                    query_id,
                    self.tenant_id,
                    self.project_a,
                    f"How visible is the primary brand? {marker}",
                    _digest(f"query-{marker}"),
                    self.market_code,
                ),
            )
            cursor.execute(
                "INSERT INTO monitoring_query_entities ("
                "tenant_id, project_id, monitoring_query_id, entity_id, subject_role) "
                "VALUES (%s, %s, %s, %s, 'primary_subject')",
                (self.tenant_id, self.project_a, query_id, self.entity_a),
            )
            cursor.execute(
                "INSERT INTO collection_runs ("
                "id, tenant_id, project_id, status, idempotency_key, requested_by, "
                "collection_method_version, expected_job_count) "
                "VALUES (%s, %s, %s, 'queued', %s, 'postgres-test', 'v2', 1)",
                (run_id, self.tenant_id, self.project_a, f"collection-{marker}"),
            )
            cursor.execute(
                "INSERT INTO collection_run_queries ("
                "tenant_id, project_id, collection_run_id, monitoring_query_id, "
                "ordinal, sample_size, query_text_snapshot, query_hash_snapshot, "
                "market_code_snapshot, language_code_snapshot, device_class_snapshot) "
                "SELECT %s, %s, %s, id, 0, 1, query_text, query_hash, market_code, "
                "language_code, device_class FROM monitoring_queries WHERE id = %s",
                (self.tenant_id, self.project_a, run_id, query_id),
            )
            if job_status == "running":
                cursor.execute(
                    "INSERT INTO collection_jobs ("
                    "id, tenant_id, project_id, collection_run_id, monitoring_query_id, "
                    "platform, surface, access_method, sample_index, status, "
                    "idempotency_key, attempt_count, max_attempts, lease_owner, "
                    "lease_token, lease_expires_at, heartbeat_at, started_at, "
                    "created_at, updated_at) VALUES ("
                    "%s, %s, %s, %s, %s, 'openai', 'responses', 'official_api', 1, "
                    "'running', %s, 1, %s, 'crashed-owner', %s, %s, %s, %s, %s, %s)",
                    (
                        job_id,
                        self.tenant_id,
                        self.project_a,
                        run_id,
                        query_id,
                        f"job-{marker}",
                        max_attempts,
                        old_token,
                        now - timedelta(seconds=1),
                        now - timedelta(seconds=10),
                        now - timedelta(seconds=10),
                        now - timedelta(seconds=20),
                        now - timedelta(seconds=10),
                    ),
                )
            else:
                cursor.execute(
                    "INSERT INTO collection_jobs ("
                    "id, tenant_id, project_id, collection_run_id, monitoring_query_id, "
                    "platform, surface, access_method, sample_index, idempotency_key, "
                    "max_attempts) VALUES (%s, %s, %s, %s, %s, 'openai', 'responses', "
                    "'official_api', 1, %s, %s)",
                    (
                        job_id,
                        self.tenant_id,
                        self.project_a,
                        run_id,
                        query_id,
                        f"job-{marker}",
                        max_attempts,
                    ),
                )
        return query_id, run_id, job_id, old_token

    def _claim_collection_job(self, worker_id: str) -> tuple[UUID, UUID, int] | None:
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT id, lease_token, attempt_count "
                "FROM geno_v2_claim_collection_job(%s, 30, %s)",
                (worker_id, self.project_a),
            )
            row = cursor.fetchone()
        return row

    def _full_collection_result_payload(
        self,
        *,
        marker: str,
    ) -> tuple[dict[str, object], dict[str, UUID]]:
        ids = {
            name: uuid4()
            for name in (
                "answer_run",
                "raw_answer",
                "citation",
                "evidence_asset",
                "artifact_outbox",
                "raw_evidence_link",
                "citation_evidence_link",
                "analysis",
                "mention",
                "analysis_evidence_link",
                "cost",
                "model_call",
            )
        }
        now = datetime.now(UTC)
        evidence_hash = _digest(f"evidence-{marker}")
        payload: dict[str, object] = {
            "answer_run_id": str(ids["answer_run"]),
            "raw_answer_id": str(ids["raw_answer"]),
            "status": "succeeded",
            "answer_present": True,
            "surface_triggered": True,
            "provider_request_id": f"provider-{marker}",
            "configured_model": "configured-model",
            "provider_reported_model": "reported-model",
            "collector_version": "collector-v2",
            "collected_at": now.isoformat(),
            "duration_ms": 12,
            "answer_text": "The primary brand is visible.",
            "raw_payload_hash": _digest(f"raw-answer-{marker}"),
            "content_type": "application/json",
            "data_classification": "internal",
            "retention_policy": "default-90d",
            "citations": [
                {
                    "id": str(ids["citation"]),
                    "position": 0,
                    "source_url": "https://example.test/source",
                    "normalized_url_hash": _digest("https://example.test/source"),
                    "source_domain": "example.test",
                    "source_title": "Source",
                    "source_snippet": "Primary brand source.",
                    "source_type": "official",
                    "public_disclosure_allowed": True,
                    "quotation_allowed": True,
                    "attribution_required": True,
                }
            ],
            "evidence_assets": [
                {
                    "id": str(ids["evidence_asset"]),
                    "finalize_outbox_id": str(ids["artifact_outbox"]),
                    "asset_type": "raw_payload",
                    "storage_uri": f"s3://pending/{marker}.json",
                    "storage_key": f"pending/{marker}.json",
                    "content_hash": evidence_hash,
                    "size_bytes": 128,
                    "content_type": "application/json",
                    "access_policy": "project_internal",
                    "retention_policy": "default-90d",
                    "source_kind": "collection_raw_payload",
                    "created_by": self.actor_id,
                }
            ],
            "raw_answer_evidence_assets": [
                {
                    "id": str(ids["raw_evidence_link"]),
                    "evidence_asset_id": str(ids["evidence_asset"]),
                    "evidence_role": "raw_payload",
                }
            ],
            "citation_evidence_assets": [
                {
                    "id": str(ids["citation_evidence_link"]),
                    "answer_citation_id": str(ids["citation"]),
                    "evidence_asset_id": str(ids["evidence_asset"]),
                    "evidence_role": "page_capture",
                }
            ],
            "analysis": {
                "id": str(ids["analysis"]),
                "analysis_version": "analysis-v2",
                "analyzer_kind": "deterministic-test",
                "trigger_detected": True,
                "mention_detected": True,
                "recommendation_detected": True,
                "citation_detected": True,
                "sentiment_score": 0.5,
                "confidence": 0.9,
                "claim_inventory_complete": False,
                "claim_inventory_reviewed_by": None,
                "claim_inventory_reviewed_at": None,
                "analysis_payload": {"fixture": marker},
                "analysis_hash": _digest(f"analysis-{marker}"),
                "created_by": self.actor_id,
                "entity_mentions": [
                    {
                        "id": str(ids["mention"]),
                        "entity_id": str(self.entity_a),
                        "mention_role": "primary_brand",
                        "mention_count": 1,
                        "first_position": 4,
                        "confidence": 0.9,
                    }
                ],
                "evidence_assets": [
                    {
                        "id": str(ids["analysis_evidence_link"]),
                        "evidence_asset_id": str(ids["evidence_asset"]),
                        "evidence_role": "analysis_input",
                    }
                ],
            },
            "collection_costs": [
                {
                    "id": str(ids["cost"]),
                    "provider": "test-provider",
                    "configured_model": "configured-model",
                    "currency": "USD",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "provider_cost": "0.01",
                    "vendor_cost": "0.02",
                    "compute_cost": "0.03",
                    "total_cost": "0.06",
                    "cost_method": "provider_reported",
                    "duration_ms": 12,
                    "recorded_at": now.isoformat(),
                }
            ],
            "model_call_logs": [
                {
                    "id": str(ids["model_call"]),
                    "answer_analysis_id": str(ids["analysis"]),
                    "purpose": "answer_analysis",
                    "provider": "test-provider",
                    "provider_request_id": f"provider-{marker}",
                    "configured_model": "configured-model",
                    "provider_reported_model": "reported-model",
                    "prompt_template_release": "analysis-release-v2",
                    "request_hash": _digest(f"request-{marker}"),
                    "response_hash": _digest(f"response-{marker}"),
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "cost_usd": "0.01",
                    "latency_ms": 12,
                    "finish_reason": "stop",
                    "status": "succeeded",
                    "error_code": None,
                }
            ],
        }
        return payload, ids

    def _create_completed_score_snapshot(
        self,
        *,
        collection_run_id: UUID,
        weight_profile_id: UUID,
        score: int,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        payload_overrides: dict[str, object] | None = None,
    ) -> tuple[UUID, UUID]:
        marker = uuid4().hex
        score_run_id = uuid4()
        snapshot_id = uuid4()
        end = window_end or datetime.now(UTC)
        start = window_start or (end - timedelta(hours=1))
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "INSERT INTO visibility_score_runs ("
                "id, tenant_id, project_id, collection_run_id, weight_profile_id, "
                "idempotency_key, window_start, window_end, requested_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    score_run_id,
                    self.tenant_id,
                    self.project_a,
                    collection_run_id,
                    weight_profile_id,
                    f"score-{marker}",
                    start,
                    end,
                    self.actor_id,
                ),
            )
        worker_id = f"score-worker-{marker}"
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT lease_token FROM geno_v2_claim_visibility_score_run(%s, 30, %s) "
                "WHERE id = %s",
                (worker_id, self.project_a, score_run_id),
            )
            lease_token = cursor.fetchone()[0]
            cursor.execute(
                "SELECT status FROM geno_v2_complete_visibility_score_run(%s, %s, %s, %s)",
                (
                    score_run_id,
                    worker_id,
                    lease_token,
                    Jsonb(
                        {
                            "snapshot_id": str(snapshot_id),
                            "formula_version": "geo-v2",
                            "window_start": start.isoformat(),
                            "window_end": end.isoformat(),
                            "total_score": score,
                            "trigger_rate": 0.5,
                            "mention_rate": 0.5,
                            "recommendation_rate": 0.5,
                            "citation_rate": 0.5,
                            "sample_count": 1,
                            "excluded_sample_count": 0,
                            "limitations": "",
                            "snapshot_hash": _digest(f"snapshot-{marker}"),
                            "created_by": self.actor_id,
                            "run_analyses": [],
                            "dimensions": [],
                            "contributions": [],
                            "contribution_evidence_assets": [],
                            "source_graphs": [],
                            "source_nodes": [],
                            "source_graph_edges": [],
                            "source_node_citations": [],
                            "source_gaps": [],
                            "source_gap_citations": [],
                            "source_gap_contributions": [],
                            "competitor_benchmarks": [],
                            "benchmark_contributions": [],
                            "actions": [],
                            "action_source_gaps": [],
                            "action_score_contributions": [],
                            "action_benchmarks": [],
                            "action_tasks": [],
                        }
                        | (payload_overrides or {})
                    ),
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")
        return score_run_id, snapshot_id

    def test_catalog_forces_rls_and_composite_fks_reject_cross_project_links(self) -> None:
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(%s) "
                "ORDER BY relname",
                (list(DOMAIN_TABLES),),
            )
            rows = cursor.fetchall()
            self.assertEqual([row[0] for row in rows], sorted(DOMAIN_TABLES))
            self.assertTrue(all(row[1] and row[2] for row in rows))

            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    "INSERT INTO product_entity_aliases ("
                    "tenant_id, project_id, entity_id, alias, alias_type, language_code, "
                    "source_type, confidence, created_by) "
                    "VALUES (%s, %s, %s, 'Cross project alias', 'common', 'en', "
                    "'manual', 1, 'postgres-test')",
                    (self.tenant_id, self.project_a, self.entity_b),
                )

    def test_runtime_rls_hides_and_rejects_other_project_rows(self) -> None:
        with self._runtime_transaction() as cursor:
            cursor.execute("SELECT id FROM product_entities ORDER BY id")
            self.assertEqual(cursor.fetchall(), [(self.entity_a,)])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                cursor.execute(
                    "INSERT INTO product_entities ("
                    "tenant_id, project_id, entity_kind, canonical_name, "
                    "created_by, updated_by) VALUES (%s, %s, 'product', %s, %s, %s)",
                    (
                        self.tenant_id,
                        self.project_b,
                        f"Forbidden {uuid4().hex}",
                        self.actor_id,
                        self.actor_id,
                    ),
                )

        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT * FROM geno_v2_claim_collection_job('forged-worker', 30, %s)",
                    (self.project_a,),
                )
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self._worker_transaction() as cursor:
                cursor.execute("SELECT id FROM collection_jobs LIMIT 1")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self._runtime_transaction() as cursor:
                cursor.execute("SELECT id FROM durable_job_dispatch_outbox LIMIT 1")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "UPDATE durable_job_dispatch_outbox SET next_attempt_at = "
                    "clock_timestamp() WHERE id = %s",
                    (uuid4(),),
                )

    def test_job_roles_are_membership_free_and_acl_is_narrow(self) -> None:
        worker_functions = (
            "geno_v2_claim_durable_job_dispatch",
            "geno_v2_heartbeat_durable_job_dispatch",
            "geno_v2_complete_durable_job_dispatch",
            "geno_v2_fail_durable_job_dispatch",
            "geno_v2_claim_artifact_finalize",
            "geno_v2_heartbeat_artifact_finalize",
            "geno_v2_complete_artifact_finalize",
            "geno_v2_fail_artifact_finalize",
            "geno_v2_claim_collection_job",
            "geno_v2_heartbeat_collection_job",
            "geno_v2_complete_collection_job",
            "geno_v2_fail_collection_job",
            "geno_v2_ack_collection_job_cancel",
            "geno_v2_claim_visibility_score_run",
            "geno_v2_heartbeat_visibility_score_run",
            "geno_v2_complete_visibility_score_run",
            "geno_v2_fail_visibility_score_run",
            "geno_v2_ack_visibility_score_run_cancel",
            "geno_v2_claim_retest_run",
            "geno_v2_heartbeat_retest_run",
            "geno_v2_complete_retest_run",
            "geno_v2_fail_retest_run",
            "geno_v2_ack_retest_run_cancel",
        )
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolinherit, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = ANY(%s) "
                "ORDER BY rolname",
                (
                    [
                        "geno_v2_worker",
                        "geno_v2_job_owner",
                        "geno_v2_result_owner",
                        "geno_v2_job_command_owner",
                        "geno_v2_worker_login",
                    ],
                ),
            )
            rows = cursor.fetchall()
            self.assertEqual(len(rows), 5)
            for role_name, can_login, superuser, create_db, create_role, inherit, replication, bypass in rows:
                self.assertFalse(can_login, role_name)
                self.assertFalse(superuser, role_name)
                self.assertFalse(create_db, role_name)
                self.assertFalse(create_role, role_name)
                self.assertFalse(inherit, role_name)
                self.assertFalse(replication, role_name)
                self.assertEqual(
                    bypass,
                    role_name
                    in {
                        "geno_v2_job_owner",
                        "geno_v2_result_owner",
                        "geno_v2_job_command_owner",
                    },
                )
            cursor.execute(
                "SELECT granted.rolname, member.rolname, membership.admin_option, "
                "membership.inherit_option, membership.set_option "
                "FROM pg_auth_members AS membership "
                "JOIN pg_roles AS granted ON granted.oid = membership.roleid "
                "JOIN pg_roles AS member ON member.oid = membership.member "
                "WHERE granted.rolname = ANY(%s) OR member.rolname = ANY(%s)",
                ([row[0] for row in rows], [row[0] for row in rows]),
            )
            self.assertEqual(
                cursor.fetchall(),
                [("geno_v2_worker", "geno_v2_worker_login", False, False, True)],
            )
            cursor.execute(
                "SELECT rolpassword IS NULL FROM pg_authid "
                "WHERE rolname = 'geno_v2_worker_login'"
            )
            self.assertTrue(cursor.fetchone()[0])
            cursor.execute(
                "SELECT proname, pg_get_userbyid(proowner), prosecdef, proconfig, "
                "has_function_privilege('geno_v2_worker', pg_proc.oid, 'EXECUTE'), "
                "has_function_privilege('geno_v2_runtime', pg_proc.oid, 'EXECUTE') "
                "FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
                "AND proname = ANY(%s) ORDER BY proname",
                (list(worker_functions),),
            )
            functions = cursor.fetchall()
            self.assertEqual({row[0] for row in functions}, set(worker_functions))
            self.assertTrue(all(row[1] == "geno_v2_job_owner" for row in functions))
            self.assertTrue(all(row[2] for row in functions))
            self.assertTrue(all(row[3] == ["search_path=pg_catalog"] for row in functions))
            self.assertTrue(all(row[4] and not row[5] for row in functions))

    def test_dispatch_outbox_is_atomic_reclaimable_and_fenced(self) -> None:
        query_id, run_id, job_id, _ = self._insert_collection_scope()
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, job_kind, job_id, collection_job_id, "
                "visibility_score_run_id, retest_run_id, status, attempt_count "
                "FROM durable_job_dispatch_outbox WHERE job_kind = 'collection' "
                "AND job_id = %s",
                (job_id,),
            )
            dispatch_id, *projection = cursor.fetchone()
            self.assertEqual(
                projection,
                ["collection", job_id, job_id, None, None, "pending", 0],
            )

        rolled_back_job_id = uuid4()
        with psycopg.connect(autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute("BEGIN")
            try:
                cursor.execute(
                    "INSERT INTO collection_jobs ("
                    "id, tenant_id, project_id, collection_run_id, monitoring_query_id, "
                    "platform, surface, access_method, sample_index, idempotency_key) "
                    "VALUES (%s, %s, %s, %s, %s, 'openai', 'responses', "
                    "'official_api', 2, %s)",
                    (
                        rolled_back_job_id,
                        self.tenant_id,
                        self.project_a,
                        run_id,
                        query_id,
                        f"rollback-{uuid4().hex}",
                    ),
                )
                cursor.execute(
                    "SELECT count(*) FROM durable_job_dispatch_outbox "
                    "WHERE job_kind = 'collection' AND job_id = %s",
                    (rolled_back_job_id,),
                )
                self.assertEqual(cursor.fetchone()[0], 1)
            finally:
                cursor.execute("ROLLBACK")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT (SELECT count(*) FROM collection_jobs WHERE id = %s), "
                "(SELECT count(*) FROM durable_job_dispatch_outbox WHERE job_id = %s)",
                (rolled_back_job_id, rolled_back_job_id),
            )
            self.assertEqual(cursor.fetchone(), (0, 0))

        first_worker = f"dispatch-first-{uuid4().hex}"
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT lease_token, attempt_count "
                "FROM geno_v2_claim_durable_job_dispatch(%s, 30, %s, %s)",
                (first_worker, self.project_a, dispatch_id),
            )
            first_token, first_attempt = cursor.fetchone()
            self.assertEqual(first_attempt, 1)
            cursor.execute(
                "SELECT status, lease_token, attempt_count "
                "FROM geno_v2_heartbeat_durable_job_dispatch(%s, %s, %s, 30)",
                (dispatch_id, first_worker, first_token),
            )
            self.assertEqual(
                cursor.fetchone(),
                ("dispatching", first_token, 1),
            )
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE durable_job_dispatch_outbox SET lease_expires_at = "
                "clock_timestamp() - interval '1 second' WHERE id = %s",
                (dispatch_id,),
            )

        barrier = threading.Barrier(2)
        outcomes: list[tuple[UUID, int] | None] = []
        failures: list[BaseException] = []

        def reclaim(worker_id: str) -> None:
            try:
                barrier.wait(timeout=5)
                with self._worker_transaction() as cursor:
                    cursor.execute(
                        "SELECT lease_token, attempt_count "
                        "FROM geno_v2_claim_durable_job_dispatch(%s, 30, %s, %s)",
                        (worker_id, self.project_a, dispatch_id),
                    )
                    outcomes.append(cursor.fetchone())
            except BaseException as exc:
                failures.append(exc)

        worker_ids = [f"dispatch-reclaimer-{index}-{uuid4().hex}" for index in range(2)]
        threads = [threading.Thread(target=reclaim, args=(worker_id,)) for worker_id in worker_ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(failures)
        claimed = [row for row in outcomes if row is not None]
        self.assertEqual(len(claimed), 1)
        winning_token, winning_attempt = claimed[0]
        self.assertEqual(winning_attempt, 2)
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT lease_owner FROM durable_job_dispatch_outbox WHERE id = %s",
                (dispatch_id,),
            )
            winning_worker = cursor.fetchone()[0]

        for function_sql in (
            "SELECT geno_v2_heartbeat_durable_job_dispatch(%s, %s, %s, 30)",
            "SELECT geno_v2_complete_durable_job_dispatch(%s, %s, %s)",
        ):
            with self.assertRaises(psycopg.Error) as stale_lease:
                with self._worker_transaction() as cursor:
                    cursor.execute(function_sql, (dispatch_id, first_worker, first_token))
            self.assertEqual(stale_lease.exception.sqlstate, "55000")

        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_complete_durable_job_dispatch(%s, %s, %s)",
                (dispatch_id, winning_worker, winning_token),
            )
            self.assertEqual(cursor.fetchone()[0], "dispatched")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT (SELECT status FROM collection_jobs WHERE id = %s), "
                "(SELECT status FROM durable_job_dispatch_outbox WHERE id = %s)",
                (job_id, dispatch_id),
            )
            self.assertEqual(cursor.fetchone(), ("queued", "dispatched"))

        _, _, retry_job_id, _ = self._insert_collection_scope()
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE durable_job_dispatch_outbox SET max_attempts = 2 "
                "WHERE job_kind = 'collection' AND job_id = %s RETURNING id",
                (retry_job_id,),
            )
            retry_dispatch_id = cursor.fetchone()[0]
        retry_worker = f"dispatch-retry-{uuid4().hex}"
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT lease_token FROM geno_v2_claim_durable_job_dispatch(%s, 30, %s, %s)",
                (retry_worker, self.project_a, retry_dispatch_id),
            )
            retry_token = cursor.fetchone()[0]
            cursor.execute(
                "SELECT status, attempt_count FROM geno_v2_fail_durable_job_dispatch("
                "%s, %s, %s, 'temporary', 'retry dispatch', true, 0)",
                (retry_dispatch_id, retry_worker, retry_token),
            )
            self.assertEqual(cursor.fetchone(), ("pending", 1))
            cursor.execute(
                "SELECT lease_token, attempt_count "
                "FROM geno_v2_claim_durable_job_dispatch(%s, 30, %s, %s)",
                (retry_worker, self.project_a, retry_dispatch_id),
            )
            final_token, final_attempt = cursor.fetchone()
            self.assertEqual(final_attempt, 2)
            cursor.execute(
                "SELECT status, attempt_count FROM geno_v2_fail_durable_job_dispatch("
                "%s, %s, %s, 'still_failing', 'budget exhausted', true, 0)",
                (retry_dispatch_id, retry_worker, final_token),
            )
            self.assertEqual(cursor.fetchone(), ("dead_letter", 2))

        _, _, expired_job_id, _ = self._insert_collection_scope()
        expired_worker = f"dispatch-expired-budget-{uuid4().hex}"
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE durable_job_dispatch_outbox SET max_attempts = 1 "
                "WHERE job_kind = 'collection' AND job_id = %s RETURNING id",
                (expired_job_id,),
            )
            expired_dispatch_id = cursor.fetchone()[0]
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT lease_token FROM geno_v2_claim_durable_job_dispatch(%s, 30, %s, %s)",
                (expired_worker, self.project_a, expired_dispatch_id),
            )
            self.assertIsNotNone(cursor.fetchone())
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE durable_job_dispatch_outbox SET lease_expires_at = "
                "clock_timestamp() - interval '1 second' WHERE id = %s",
                (expired_dispatch_id,),
            )
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT id FROM geno_v2_claim_durable_job_dispatch(%s, 30, %s, %s)",
                (expired_worker, self.project_a, expired_dispatch_id),
            )
            self.assertIsNone(cursor.fetchone())
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, attempt_count, dispatched_by "
                "FROM durable_job_dispatch_outbox WHERE id = %s",
                (expired_dispatch_id,),
            )
            self.assertEqual(cursor.fetchone(), ("dead_letter", 1, "lease-recovery"))

        with self._runtime_transaction() as cursor:
            for cleanup_job_id in (job_id, retry_job_id, expired_job_id):
                cursor.execute(
                    "SELECT status FROM geno_v2_request_collection_job_cancel(%s, %s)",
                    (cleanup_job_id, "dispatch projection test cleanup"),
                )
                self.assertEqual(cursor.fetchone()[0], "cancelled")

    def test_expired_collection_lease_is_reclaimed_once_and_stale_owner_is_fenced(self) -> None:
        query_id, run_id, job_id, old_token = self._insert_collection_scope(
            job_status="running"
        )
        assert old_token is not None
        barrier = threading.Barrier(2)
        outcomes: list[tuple[UUID, UUID, int] | None] = []
        failures: list[BaseException] = []

        def reclaim(worker_id: str) -> None:
            try:
                barrier.wait(timeout=5)
                outcomes.append(self._claim_collection_job(worker_id))
            except BaseException as exc:
                failures.append(exc)

        threads = [
            threading.Thread(target=reclaim, args=(f"reclaimer-{index}",))
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(failures)
        claimed = [row for row in outcomes if row is not None]
        self.assertEqual(len(claimed), 1)
        claimed_job_id, new_token, attempt_count = claimed[0]
        self.assertEqual(claimed_job_id, job_id)
        self.assertNotEqual(new_token, old_token)
        self.assertEqual(attempt_count, 2)

        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT geno_v2_complete_collection_job(%s, %s, %s, '{}'::jsonb)",
                    (job_id, "crashed-owner", old_token),
                )

        with self.assertRaises(psycopg.Error) as stale_context:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT geno_v2_complete_collection_job(%s, %s, %s, '{}'::jsonb)",
                    (job_id, "crashed-owner", old_token),
                )
        self.assertEqual(stale_context.exception.sqlstate, "55000")

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT lease_owner FROM collection_jobs WHERE id = %s",
                (job_id,),
            )
            winning_worker = cursor.fetchone()[0]

        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT lease_token FROM geno_v2_heartbeat_collection_job(%s, %s, %s, 30)",
                (job_id, winning_worker, new_token),
            )
            if cursor.fetchone() is None:
                self.fail("the winning worker must retain its lease")

        with self.assertRaises(psycopg.Error) as malformed_result:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT geno_v2_complete_collection_job(%s, %s, %s, '{}'::jsonb)",
                    (job_id, winning_worker, new_token),
                )
        self.assertEqual(malformed_result.exception.sqlstate, "22023")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, lease_token, "
                "(SELECT count(*) FROM answer_runs WHERE collection_job_id = %s) "
                "FROM collection_jobs WHERE id = %s",
                (job_id, job_id),
            )
            self.assertEqual(cursor.fetchone(), ("running", new_token, 0))

        result_payload, result_ids = self._full_collection_result_payload(
            marker=uuid4().hex
        )
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_complete_collection_job(%s, %s, %s, %s)",
                (
                    job_id,
                    winning_worker,
                    new_token,
                    Jsonb(result_payload),
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, lease_owner, lease_token, attempt_count "
                "FROM collection_jobs WHERE id = %s",
                (job_id,),
            )
            self.assertEqual(cursor.fetchone(), ("succeeded", None, None, 2))
            cursor.execute(
                "SELECT queued_count, running_count, succeeded_count, "
                "answer_present_count, citation_count, total_cost_usd, "
                "total_duration_ms FROM collection_run_summaries "
                "WHERE collection_run_id = %s",
                (run_id,),
            )
            self.assertEqual(
                cursor.fetchone(),
                (0, 0, 1, 1, 1, Decimal("0.06000000"), 12),
            )
            for table_name, row_id in (
                ("raw_answers", result_ids["raw_answer"]),
                ("answer_citations", result_ids["citation"]),
                ("evidence_assets", result_ids["evidence_asset"]),
                ("raw_answer_evidence_assets", result_ids["raw_evidence_link"]),
                (
                    "answer_citation_evidence_assets",
                    result_ids["citation_evidence_link"],
                ),
                ("answer_analyses", result_ids["analysis"]),
                ("answer_analysis_entity_mentions", result_ids["mention"]),
                (
                    "answer_analysis_evidence_assets",
                    result_ids["analysis_evidence_link"],
                ),
                ("collection_costs", result_ids["cost"]),
                ("model_call_logs", result_ids["model_call"]),
            ):
                with self.subTest(writer_table=table_name):
                    cursor.execute(f"SELECT count(*) FROM {table_name} WHERE id = %s", (row_id,))
                    self.assertEqual(cursor.fetchone()[0], 1)

        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT count(*) FROM evidence_assets WHERE id = %s",
                (result_ids["evidence_asset"],),
            )
            self.assertEqual(cursor.fetchone()[0], 0)

        finalize_worker = f"artifact-finalizer-{uuid4().hex}"
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT id, lease_token FROM geno_v2_claim_artifact_finalize(%s, 30, %s) "
                "WHERE id = %s",
                (finalize_worker, self.project_a, result_ids["artifact_outbox"]),
            )
            outbox_id, finalize_token = cursor.fetchone()
        with self.assertRaises(psycopg.Error) as hash_mismatch:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT geno_v2_complete_artifact_finalize(%s, %s, %s, %s)",
                    (outbox_id, finalize_worker, finalize_token, _digest("wrong")),
                )
        self.assertEqual(hash_mismatch.exception.sqlstate, "22000")
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_complete_artifact_finalize(%s, %s, %s, %s)",
                (
                    outbox_id,
                    finalize_worker,
                    finalize_token,
                    result_payload["evidence_assets"][0]["content_hash"],
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_complete_artifact_finalize(%s, %s, %s, %s)",
                (
                    outbox_id,
                    finalize_worker,
                    finalize_token,
                    result_payload["evidence_assets"][0]["content_hash"],
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT artifact_status FROM evidence_assets WHERE id = %s",
                (result_ids["evidence_asset"],),
            )
            self.assertEqual(cursor.fetchone()[0], "finalized")
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT count(*) FROM evidence_assets WHERE id = %s",
                (result_ids["evidence_asset"],),
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_score_and_retest_queues_require_exact_immutable_results(self) -> None:
        query_id, collection_run_id, collection_job_id, _ = self._insert_collection_scope()
        collection_worker = f"score-input-worker-{uuid4().hex}"
        collection_claim = self._claim_collection_job(collection_worker)
        assert collection_claim is not None
        _, collection_token, _ = collection_claim
        collection_payload, collection_ids = self._full_collection_result_payload(
            marker=uuid4().hex
        )
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_complete_collection_job(%s, %s, %s, %s)",
                (
                    collection_job_id,
                    collection_worker,
                    collection_token,
                    Jsonb(collection_payload),
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")

        artifact_worker = f"score-evidence-finalizer-{uuid4().hex}"
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT id, lease_token FROM geno_v2_claim_artifact_finalize(%s, 30, %s) "
                "WHERE id = %s",
                (
                    artifact_worker,
                    self.project_a,
                    collection_ids["artifact_outbox"],
                ),
            )
            artifact_outbox_id, artifact_token = cursor.fetchone()
            cursor.execute(
                "SELECT status FROM geno_v2_complete_artifact_finalize(%s, %s, %s, %s)",
                (
                    artifact_outbox_id,
                    artifact_worker,
                    artifact_token,
                    collection_payload["evidence_assets"][0]["content_hash"],
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")

        weight_profile_id = uuid4()
        used_component_id = uuid4()
        competitor_entity_id = uuid4()
        now = datetime.now(UTC)
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "INSERT INTO product_entities ("
                "id, tenant_id, project_id, entity_kind, canonical_name, "
                "created_by, updated_by) VALUES (%s, %s, %s, 'competitor', %s, %s, %s)",
                (
                    competitor_entity_id,
                    self.tenant_id,
                    self.project_a,
                    f"Competitor {uuid4().hex}",
                    self.actor_id,
                    self.actor_id,
                ),
            )
            cursor.execute(
                "INSERT INTO visibility_weight_profiles ("
                "id, tenant_id, project_id, profile_name, profile_version, "
                "formula_version, normalization_method, status, created_by, "
                "activated_by, activated_at) VALUES ("
                "%s, %s, %s, 'Default GEO', 1, 'geo-v2', 'weighted_mean', "
                "'active', %s, %s, %s)",
                (
                    weight_profile_id,
                    self.tenant_id,
                    self.project_a,
                    self.actor_id,
                    self.actor_id,
                    now,
                ),
            )
            cursor.execute(
                "INSERT INTO visibility_weight_profile_components ("
                "id, tenant_id, project_id, weight_profile_id, metric_name, "
                "dimension_type, dimension_key, weight) "
                "VALUES (%s, %s, %s, %s, 'mention_rate', 'global', 'all', 1)",
                (used_component_id, self.tenant_id, self.project_a, weight_profile_id),
            )

        baseline_start = now - timedelta(hours=3)
        baseline_end = now - timedelta(hours=2)
        retest_start = now - timedelta(hours=1)
        retest_end = now
        baseline_score_run_id, baseline_snapshot_id = self._create_completed_score_snapshot(
            collection_run_id=collection_run_id,
            weight_profile_id=weight_profile_id,
            score=40,
            window_start=baseline_start,
            window_end=baseline_end,
        )

        score_ids = {
            name: uuid4()
            for name in (
                "run_analysis",
                "dimension",
                "contribution",
                "contribution_evidence",
                "graph",
                "node_primary",
                "node_competitor",
                "edge",
                "node_citation",
                "gap",
                "gap_citation",
                "gap_contribution",
                "benchmark",
                "benchmark_contribution",
                "action",
                "action_gap",
                "action_contribution",
                "action_benchmark",
                "task",
            )
        }
        score_overrides: dict[str, object] = {
            "run_analyses": [
                {
                    "id": str(score_ids["run_analysis"]),
                    "answer_analysis_id": str(collection_ids["analysis"]),
                    "inclusion_role": "included",
                }
            ],
            "dimensions": [
                {
                    "id": str(score_ids["dimension"]),
                    "dimension_type": "platform",
                    "dimension_key": "openai",
                    "dimension_score": 55,
                    "trigger_rate": 0.5,
                    "mention_rate": 0.5,
                    "recommendation_rate": 0.5,
                    "citation_rate": 0.5,
                    "sample_count": 1,
                }
            ],
            "contributions": [
                {
                    "id": str(score_ids["contribution"]),
                    "answer_analysis_id": str(collection_ids["analysis"]),
                    "metric_name": "mention_rate",
                    "dimension_type": "global",
                    "dimension_key": "all",
                    "weight": 1,
                    "raw_value": 1,
                    "normalized_value": 1,
                    "contribution": 1,
                    "positive_evidence": "Brand mentioned.",
                    "negative_evidence": "",
                    "explanation": "Primary brand mention contributes positively.",
                }
            ],
            "contribution_evidence_assets": [
                {
                    "id": str(score_ids["contribution_evidence"]),
                    "score_contribution_id": str(score_ids["contribution"]),
                    "evidence_asset_id": str(collection_ids["evidence_asset"]),
                    "evidence_role": "source_result",
                }
            ],
            "source_graphs": [
                {
                    "id": str(score_ids["graph"]),
                    "graph_version": f"graph-{uuid4().hex}",
                    "graph_hash": _digest(f"graph-{score_ids['graph']}"),
                    "status": "ready",
                    "created_by": self.actor_id,
                }
            ],
            "source_nodes": [
                {
                    "id": str(score_ids["node_primary"]),
                    "source_graph_id": str(score_ids["graph"]),
                    "entity_id": str(self.entity_a),
                    "source_url": "https://example.test/primary",
                    "normalized_url_hash": _digest("https://example.test/primary"),
                    "source_domain": "example.test",
                    "source_type": "official",
                    "source_title": "Primary",
                    "citation_count": 1,
                    "authority_score": 0.8,
                },
                {
                    "id": str(score_ids["node_competitor"]),
                    "source_graph_id": str(score_ids["graph"]),
                    "entity_id": str(competitor_entity_id),
                    "source_url": "https://competitor.test/source",
                    "normalized_url_hash": _digest("https://competitor.test/source"),
                    "source_domain": "competitor.test",
                    "source_type": "editorial",
                    "source_title": "Competitor",
                    "citation_count": 0,
                    "authority_score": 0.7,
                },
            ],
            "source_graph_edges": [
                {
                    "id": str(score_ids["edge"]),
                    "source_graph_id": str(score_ids["graph"]),
                    "from_source_node_id": str(score_ids["node_primary"]),
                    "to_source_node_id": str(score_ids["node_competitor"]),
                    "relation_type": "compares",
                    "weight": 0.5,
                }
            ],
            "source_node_citations": [
                {
                    "id": str(score_ids["node_citation"]),
                    "source_node_id": str(score_ids["node_primary"]),
                    "answer_citation_id": str(collection_ids["citation"]),
                }
            ],
            "source_gaps": [
                {
                    "id": str(score_ids["gap"]),
                    "source_graph_id": str(score_ids["graph"]),
                    "entity_id": str(self.entity_a),
                    "gap_type": "authority_source_gap",
                    "source_type": "editorial",
                    "severity": "high",
                    "observed_count": 1,
                    "expected_count": 2,
                    "expected_weight": 0.5,
                    "recommendation": "Add an authoritative third-party source.",
                    "status": "open",
                    "detected_by": self.actor_id,
                    "resolved_by": None,
                    "resolved_at": None,
                }
            ],
            "source_gap_citations": [
                {
                    "id": str(score_ids["gap_citation"]),
                    "source_gap_id": str(score_ids["gap"]),
                    "answer_citation_id": str(collection_ids["citation"]),
                    "evidence_role": "observed_source",
                }
            ],
            "source_gap_contributions": [
                {
                    "id": str(score_ids["gap_contribution"]),
                    "source_gap_id": str(score_ids["gap"]),
                    "score_contribution_id": str(score_ids["contribution"]),
                    "evidence_role": "metric_impact",
                }
            ],
            "competitor_benchmarks": [
                {
                    "id": str(score_ids["benchmark"]),
                    "primary_entity_id": str(self.entity_a),
                    "compared_entity_id": str(competitor_entity_id),
                    "metric_scope": "global",
                    "metric_name": "mention_rate",
                    "primary_value": 0.5,
                    "compared_value": 0.7,
                    "value_delta": 0.2,
                    "sample_count": 1,
                    "benchmark_hash": _digest(f"benchmark-{score_ids['benchmark']}"),
                    "created_by": self.actor_id,
                }
            ],
            "benchmark_contributions": [
                {
                    "id": str(score_ids["benchmark_contribution"]),
                    "competitor_benchmark_id": str(score_ids["benchmark"]),
                    "score_contribution_id": str(score_ids["contribution"]),
                    "comparison_role": "primary",
                }
            ],
            "actions": [
                {
                    "id": str(score_ids["action"]),
                    "title": "Close authority source gap",
                    "description": "Publish evidence suitable for editorial citation.",
                    "action_type": "source_development",
                    "priority": "high",
                    "status": "open",
                    "owner_id": None,
                    "customer_visible": True,
                    "revision": 1,
                    "next_check_at": None,
                    "created_by": self.actor_id,
                    "updated_by": self.actor_id,
                }
            ],
            "action_source_gaps": [
                {
                    "id": str(score_ids["action_gap"]),
                    "action_recommendation_id": str(score_ids["action"]),
                    "source_gap_id": str(score_ids["gap"]),
                    "relation_type": "addresses",
                }
            ],
            "action_score_contributions": [
                {
                    "id": str(score_ids["action_contribution"]),
                    "action_recommendation_id": str(score_ids["action"]),
                    "score_contribution_id": str(score_ids["contribution"]),
                    "relation_type": "improves",
                }
            ],
            "action_benchmarks": [
                {
                    "id": str(score_ids["action_benchmark"]),
                    "action_recommendation_id": str(score_ids["action"]),
                    "competitor_benchmark_id": str(score_ids["benchmark"]),
                    "relation_type": "closes_gap",
                }
            ],
            "action_tasks": [
                {
                    "id": str(score_ids["task"]),
                    "action_recommendation_id": str(score_ids["action"]),
                    "title": "Prepare source asset",
                    "status": "todo",
                    "owner_id": None,
                    "due_at": None,
                    "completed_at": None,
                    "created_by": self.actor_id,
                    "updated_by": self.actor_id,
                }
            ],
        }
        output_score_run_id, output_snapshot_id = self._create_completed_score_snapshot(
            collection_run_id=collection_run_id,
            weight_profile_id=weight_profile_id,
            score=55,
            window_start=retest_start,
            window_end=retest_end,
            payload_overrides=score_overrides,
        )

        with psycopg.connect() as connection, connection.cursor() as cursor:
            with self.assertRaises(psycopg.Error) as immutable_snapshot:
                cursor.execute(
                    "UPDATE visibility_score_snapshots SET total_score = 99 WHERE id = %s",
                    (baseline_snapshot_id,),
                )
            self.assertEqual(immutable_snapshot.exception.sqlstate, "55000")
            connection.rollback()
            with self.assertRaises(psycopg.Error) as immutable_profile:
                cursor.execute(
                    "UPDATE visibility_weight_profiles SET notes = 'changed' WHERE id = %s",
                    (weight_profile_id,),
                )
            self.assertEqual(immutable_profile.exception.sqlstate, "55000")
            connection.rollback()
            with self.assertRaises(psycopg.Error) as immutable_component_set:
                cursor.execute(
                    "INSERT INTO visibility_weight_profile_components ("
                    "tenant_id, project_id, weight_profile_id, metric_name, "
                    "dimension_type, dimension_key, weight) VALUES ("
                    "%s, %s, %s, 'citation_rate', 'global', 'all', 0.5)",
                    (self.tenant_id, self.project_a, weight_profile_id),
                )
            self.assertEqual(immutable_component_set.exception.sqlstate, "55000")
            connection.rollback()
            with self.assertRaises(psycopg.Error) as immutable_component_update:
                cursor.execute(
                    "UPDATE visibility_weight_profile_components SET weight = 0.5 "
                    "WHERE id = %s",
                    (used_component_id,),
                )
            self.assertEqual(immutable_component_update.exception.sqlstate, "55000")
            connection.rollback()
            with self.assertRaises(psycopg.Error) as immutable_component_delete:
                cursor.execute(
                    "DELETE FROM visibility_weight_profile_components WHERE id = %s",
                    (used_component_id,),
                )
            self.assertEqual(immutable_component_delete.exception.sqlstate, "55000")
            connection.rollback()

            unused_profile_id = uuid4()
            unused_component_id = uuid4()
            cursor.execute(
                "INSERT INTO visibility_weight_profiles ("
                "id, tenant_id, project_id, profile_name, profile_version, "
                "formula_version, normalization_method, status, created_by) "
                "VALUES (%s, %s, %s, %s, 1, 'geo-v2', 'weighted_mean', "
                "'draft', %s)",
                (
                    unused_profile_id,
                    self.tenant_id,
                    self.project_a,
                    f"Unused {uuid4().hex}",
                    self.actor_id,
                ),
            )
            cursor.execute(
                "INSERT INTO visibility_weight_profile_components ("
                "id, tenant_id, project_id, weight_profile_id, metric_name, "
                "dimension_type, dimension_key, weight) VALUES ("
                "%s, %s, %s, %s, 'citation_rate', 'global', 'all', 0.5)",
                (
                    unused_component_id,
                    self.tenant_id,
                    self.project_a,
                    unused_profile_id,
                ),
            )
            connection.commit()
            with self.assertRaises(psycopg.Error) as component_move_into_used:
                cursor.execute(
                    "UPDATE visibility_weight_profile_components "
                    "SET weight_profile_id = %s WHERE id = %s",
                    (weight_profile_id, unused_component_id),
                )
            self.assertEqual(component_move_into_used.exception.sqlstate, "55000")
            connection.rollback()

        retest_run_id = uuid4()
        worker_id = f"retest-worker-{uuid4().hex}"
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "INSERT INTO retest_runs ("
                "id, tenant_id, project_id, baseline_score_snapshot_id, "
                "idempotency_key, scheduled_for, window_start, window_end, requested_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    retest_run_id,
                    self.tenant_id,
                    self.project_a,
                    baseline_snapshot_id,
                    f"retest-{uuid4().hex}",
                    now - timedelta(minutes=1),
                    retest_start,
                    retest_end,
                    self.actor_id,
                ),
            )
            cursor.execute(
                "INSERT INTO retest_run_queries ("
                "tenant_id, project_id, retest_run_id, monitoring_query_id, ordinal) "
                "VALUES (%s, %s, %s, %s, 0)",
                (self.tenant_id, self.project_a, retest_run_id, query_id),
            )
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT lease_token FROM geno_v2_claim_retest_run(%s, 30, %s) "
                "WHERE id = %s",
                (worker_id, self.project_a, retest_run_id),
            )
            lease_token = cursor.fetchone()[0]
            cursor.execute(
                "SELECT status FROM geno_v2_complete_retest_run(%s, %s, %s, %s, %s)",
                (
                    retest_run_id,
                    worker_id,
                    lease_token,
                    output_snapshot_id,
                    Jsonb(
                        {
                            "comparison_id": str(uuid4()),
                            "comparison_hash": _digest(f"comparison-{retest_run_id}"),
                            "created_by": self.actor_id,
                        }
                    ),
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")

        with psycopg.connect() as connection, connection.cursor() as cursor:
            for table_name, row_id in (
                ("visibility_score_run_analyses", score_ids["run_analysis"]),
                ("visibility_score_dimensions", score_ids["dimension"]),
                ("score_contributions", score_ids["contribution"]),
                (
                    "score_contribution_evidence_assets",
                    score_ids["contribution_evidence"],
                ),
                ("source_graphs", score_ids["graph"]),
                ("source_nodes", score_ids["node_primary"]),
                ("source_graph_edges", score_ids["edge"]),
                ("source_node_citations", score_ids["node_citation"]),
                ("source_gaps", score_ids["gap"]),
                ("source_gap_citations", score_ids["gap_citation"]),
                ("source_gap_score_contributions", score_ids["gap_contribution"]),
                ("competitor_benchmarks", score_ids["benchmark"]),
                (
                    "competitor_benchmark_contributions",
                    score_ids["benchmark_contribution"],
                ),
                ("action_recommendations", score_ids["action"]),
                ("action_source_gaps", score_ids["action_gap"]),
                ("action_score_contributions", score_ids["action_contribution"]),
                (
                    "action_competitor_benchmarks",
                    score_ids["action_benchmark"],
                ),
                ("action_tasks", score_ids["task"]),
            ):
                with self.subTest(writer_table=table_name):
                    cursor.execute(f"SELECT count(*) FROM {table_name} WHERE id = %s", (row_id,))
                    self.assertEqual(cursor.fetchone()[0], 1)
            unfinalized_asset_id = uuid4()
            cursor.execute(
                "INSERT INTO evidence_assets ("
                "id, tenant_id, project_id, asset_type, storage_uri, storage_key, "
                "content_hash, size_bytes, content_type, access_policy, "
                "retention_policy, source_kind, created_by) VALUES ("
                "%s, %s, %s, 'score-source', %s, %s, %s, 1, "
                "'text/plain', 'internal', 'test', 'postgres-test', %s)",
                (
                    unfinalized_asset_id,
                    self.tenant_id,
                    self.project_a,
                    f"s3://pending/{unfinalized_asset_id}",
                    f"pending/{unfinalized_asset_id}",
                    _digest(f"pending-{unfinalized_asset_id}"),
                    self.actor_id,
                ),
            )
            connection.commit()
            with self.assertRaises(psycopg.Error) as pending_evidence:
                cursor.execute(
                    "INSERT INTO score_contribution_evidence_assets ("
                    "tenant_id, project_id, score_contribution_id, "
                    "evidence_asset_id, evidence_role) VALUES (%s, %s, %s, %s, 'pending')",
                    (
                        self.tenant_id,
                        self.project_a,
                        score_ids["contribution"],
                        unfinalized_asset_id,
                    ),
                )
            self.assertEqual(pending_evidence.exception.sqlstate, "55000")
            connection.rollback()
            cursor.execute(
                "UPDATE evidence_assets SET artifact_status = 'failed', "
                "failure_reason = 'test finalize failure' WHERE id = %s",
                (unfinalized_asset_id,),
            )
            connection.commit()
            with self.assertRaises(psycopg.Error) as failed_evidence:
                cursor.execute(
                    "INSERT INTO score_contribution_evidence_assets ("
                    "tenant_id, project_id, score_contribution_id, "
                    "evidence_asset_id, evidence_role) VALUES (%s, %s, %s, %s, 'failed')",
                    (
                        self.tenant_id,
                        self.project_a,
                        score_ids["contribution"],
                        unfinalized_asset_id,
                    ),
                )
            self.assertEqual(failed_evidence.exception.sqlstate, "55000")
            connection.rollback()
            cursor.execute(
                "SELECT baseline_score, retest_score, score_delta, trend "
                "FROM retest_comparisons WHERE retest_run_id = %s",
                (retest_run_id,),
            )
            self.assertEqual(cursor.fetchone(), (40, 55, 15, "improved"))
            cursor.execute(
                "SELECT job_kind, job_id, collection_job_id, "
                "visibility_score_run_id, retest_run_id "
                "FROM durable_job_dispatch_outbox WHERE (job_kind, job_id) IN ("
                "('visibility_score', %s), ('visibility_score', %s), ('retest', %s)) "
                "ORDER BY job_kind, job_id",
                (baseline_score_run_id, output_score_run_id, retest_run_id),
            )
            dispatch_rows = cursor.fetchall()
            self.assertEqual(len(dispatch_rows), 3)
            for job_kind, dispatched_job_id, collection_ref, score_ref, retest_ref in dispatch_rows:
                if job_kind == "visibility_score":
                    self.assertEqual(
                        (collection_ref, score_ref, retest_ref),
                        (None, dispatched_job_id, None),
                    )
                else:
                    self.assertEqual(
                        (collection_ref, score_ref, retest_ref),
                        (None, None, dispatched_job_id),
                    )

        with self.assertRaises(psycopg.Error) as stale_heartbeat:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT geno_v2_heartbeat_retest_run(%s, %s, %s, 30)",
                    (retest_run_id, worker_id, lease_token),
                )
        self.assertEqual(stale_heartbeat.exception.sqlstate, "55000")

    def test_used_weight_profile_freeze_serializes_component_moves(self) -> None:
        _, collection_run_id, collection_job_id, _ = self._insert_collection_scope()
        target_profile_id = uuid4()
        source_profile_id = uuid4()
        source_component_id = uuid4()
        score_run_id = uuid4()
        now = datetime.now(UTC)
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO visibility_weight_profiles ("
                "id, tenant_id, project_id, profile_name, profile_version, "
                "formula_version, normalization_method, status, created_by, "
                "activated_by, activated_at) VALUES ("
                "%s, %s, %s, %s, 1, 'geo-v2', 'weighted_mean', "
                "'active', %s, %s, %s)",
                (
                    target_profile_id,
                    self.tenant_id,
                    self.project_a,
                    f"Concurrent target {uuid4().hex}",
                    self.actor_id,
                    self.actor_id,
                    now,
                ),
            )
            cursor.execute(
                "INSERT INTO visibility_weight_profiles ("
                "id, tenant_id, project_id, profile_name, profile_version, "
                "formula_version, normalization_method, status, created_by) "
                "VALUES (%s, %s, %s, %s, 1, 'geo-v2', 'weighted_mean', "
                "'draft', %s)",
                (
                    source_profile_id,
                    self.tenant_id,
                    self.project_a,
                    f"Concurrent source {uuid4().hex}",
                    self.actor_id,
                ),
            )
            cursor.execute(
                "INSERT INTO visibility_weight_profile_components ("
                "id, tenant_id, project_id, weight_profile_id, metric_name, "
                "dimension_type, dimension_key, weight) VALUES ("
                "%s, %s, %s, %s, 'mention_rate', 'global', 'all', 1)",
                (
                    source_component_id,
                    self.tenant_id,
                    self.project_a,
                    source_profile_id,
                ),
            )

        score_inserted = threading.Event()
        move_started = threading.Event()
        release_score = threading.Event()
        score_failures: list[BaseException] = []
        move_sqlstates: list[str | None] = []

        def insert_score_run() -> None:
            try:
                with psycopg.connect() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO visibility_score_runs ("
                        "id, tenant_id, project_id, collection_run_id, weight_profile_id, "
                        "idempotency_key, window_start, window_end, requested_by) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            score_run_id,
                            self.tenant_id,
                            self.project_a,
                            collection_run_id,
                            target_profile_id,
                            f"concurrent-score-{uuid4().hex}",
                            now - timedelta(hours=1),
                            now,
                            self.actor_id,
                        ),
                    )
                    score_inserted.set()
                    if not release_score.wait(timeout=10):
                        raise TimeoutError("component move did not start")
            except BaseException as exc:
                score_failures.append(exc)
                score_inserted.set()

        def move_component() -> None:
            if not score_inserted.wait(timeout=10):
                move_sqlstates.append("timeout")
                return
            try:
                with psycopg.connect() as connection, connection.cursor() as cursor:
                    move_started.set()
                    cursor.execute(
                        "UPDATE visibility_weight_profile_components "
                        "SET weight_profile_id = %s WHERE id = %s",
                        (target_profile_id, source_component_id),
                    )
            except psycopg.Error as exc:
                move_sqlstates.append(exc.sqlstate)

        score_thread = threading.Thread(target=insert_score_run)
        move_thread = threading.Thread(target=move_component)
        score_thread.start()
        self.assertTrue(score_inserted.wait(timeout=10))
        move_thread.start()
        self.assertTrue(move_started.wait(timeout=10))
        release_score.set()
        score_thread.join(timeout=10)
        move_thread.join(timeout=10)
        self.assertFalse(score_thread.is_alive())
        self.assertFalse(move_thread.is_alive())
        self.assertFalse(score_failures)
        self.assertEqual(move_sqlstates, ["55000"])
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT weight_profile_id FROM visibility_weight_profile_components "
                "WHERE id = %s",
                (source_component_id,),
            )
            self.assertEqual(cursor.fetchone()[0], source_profile_id)
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_request_visibility_score_run_cancel(%s, %s)",
                (score_run_id, "concurrency test cleanup"),
            )
            self.assertEqual(cursor.fetchone()[0], "cancelled")
            cursor.execute(
                "SELECT status FROM geno_v2_request_collection_job_cancel(%s, %s)",
                (collection_job_id, "concurrency test cleanup"),
            )
            self.assertEqual(cursor.fetchone()[0], "cancelled")

    def test_cancel_recovery_and_operator_replay_are_fenced_and_idempotent(self) -> None:
        monitoring_query_id, collection_run_id, collection_job_id, _ = (
            self._insert_collection_scope()
        )
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_request_collection_job_cancel(%s, %s)",
                (collection_job_id, "operator cancelled queued collection"),
            )
            self.assertEqual(cursor.fetchone()[0], "cancelled")

        profile_id = uuid4()
        marker = uuid4().hex
        now = datetime.now(UTC)
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "INSERT INTO visibility_weight_profiles ("
                "id, tenant_id, project_id, profile_name, profile_version, "
                "formula_version, normalization_method, status, created_by, "
                "activated_by, activated_at) VALUES ("
                "%s, %s, %s, %s, 1, 'geo-v2', 'weighted_mean', 'active', %s, %s, %s)",
                (
                    profile_id,
                    self.tenant_id,
                    self.project_a,
                    f"Replay profile {marker}",
                    self.actor_id,
                    self.actor_id,
                    now,
                ),
            )
        _, baseline_snapshot_id = self._create_completed_score_snapshot(
            collection_run_id=collection_run_id,
            weight_profile_id=profile_id,
            score=50,
        )

        score_run_id = uuid4()
        retest_run_id = uuid4()
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "INSERT INTO visibility_score_runs ("
                "id, tenant_id, project_id, collection_run_id, weight_profile_id, "
                "idempotency_key, window_start, window_end, requested_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    score_run_id,
                    self.tenant_id,
                    self.project_a,
                    collection_run_id,
                    profile_id,
                    f"score-cancel-{marker}",
                    now - timedelta(hours=1),
                    now,
                    self.actor_id,
                ),
            )
            cursor.execute(
                "SELECT status FROM geno_v2_request_visibility_score_run_cancel(%s, %s)",
                (score_run_id, "operator cancelled queued score"),
            )
            self.assertEqual(cursor.fetchone()[0], "cancelled")
            cursor.execute(
                "INSERT INTO retest_runs ("
                "id, tenant_id, project_id, baseline_score_snapshot_id, idempotency_key, "
                "scheduled_for, window_start, window_end, requested_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    retest_run_id,
                    self.tenant_id,
                    self.project_a,
                    baseline_snapshot_id,
                    f"retest-cancel-{marker}",
                    now - timedelta(minutes=1),
                    now - timedelta(hours=1),
                    now,
                    self.actor_id,
                ),
            )
            cursor.execute(
                "INSERT INTO retest_run_queries ("
                "tenant_id, project_id, retest_run_id, monitoring_query_id, ordinal) "
                "VALUES (%s, %s, %s, %s, 0)",
                (
                    self.tenant_id,
                    self.project_a,
                    retest_run_id,
                    monitoring_query_id,
                ),
            )
            cursor.execute(
                "SELECT status FROM geno_v2_request_retest_run_cancel(%s, %s)",
                (retest_run_id, "operator cancelled queued retest"),
            )
            self.assertEqual(cursor.fetchone()[0], "cancelled")

        replay_specs = (
            (
                "geno_v2_replay_collection_job",
                "geno_v2_request_collection_job_cancel",
                "collection",
                collection_job_id,
                uuid4(),
                f"collection-replay-{marker}",
            ),
            (
                "geno_v2_replay_visibility_score_run",
                "geno_v2_request_visibility_score_run_cancel",
                "visibility_score",
                score_run_id,
                uuid4(),
                f"score-replay-{marker}",
            ),
            (
                "geno_v2_replay_retest_run",
                "geno_v2_request_retest_run_cancel",
                "retest",
                retest_run_id,
                uuid4(),
                f"retest-replay-{marker}",
            ),
        )
        for (
            function_name,
            cancel_function_name,
            job_kind,
            source_id,
            child_id,
            idempotency_key,
        ) in replay_specs:
            barrier = threading.Barrier(2)
            outcomes: list[tuple[UUID, UUID, int]] = []
            failures: list[BaseException] = []

            def replay() -> None:
                try:
                    barrier.wait(timeout=5)
                    with self._runtime_transaction() as cursor:
                        cursor.execute(
                            f"SELECT id, parent_job_id, replay_nonce FROM {function_name}(%s, %s, %s)",
                            (source_id, child_id, idempotency_key),
                        )
                        outcomes.append(cursor.fetchone())
                except BaseException as exc:
                    failures.append(exc)

            threads = [threading.Thread(target=replay) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            with self.subTest(function_name=function_name):
                self.assertFalse(failures)
                self.assertEqual(outcomes, [(child_id, source_id, 1)] * 2)
                with psycopg.connect() as connection, connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT job_kind, job_id, collection_job_id, "
                        "visibility_score_run_id, retest_run_id "
                        "FROM durable_job_dispatch_outbox "
                        "WHERE job_kind = %s AND job_id = %s",
                        (job_kind, child_id),
                    )
                    child_dispatch_rows = cursor.fetchall()
                self.assertEqual(len(child_dispatch_rows), 1)
                _, dispatched_job_id, collection_ref, score_ref, retest_ref = (
                    child_dispatch_rows[0]
                )
                expected_refs = {
                    "collection": (child_id, None, None),
                    "visibility_score": (None, child_id, None),
                    "retest": (None, None, child_id),
                }
                self.assertEqual(dispatched_job_id, child_id)
                self.assertEqual(
                    (collection_ref, score_ref, retest_ref),
                    expected_refs[job_kind],
                )
                with self.assertRaises(psycopg.Error) as conflict:
                    with self._runtime_transaction() as cursor:
                        cursor.execute(
                            f"SELECT id FROM {function_name}(%s, %s, %s)",
                            (source_id, uuid4(), f"conflict-{idempotency_key}"),
                        )
                self.assertEqual(conflict.exception.sqlstate, "23505")
                with self._runtime_transaction() as cursor:
                    cursor.execute(
                        f"SELECT status FROM {cancel_function_name}(%s, %s)",
                        (child_id, "test replay isolation"),
                    )
                    self.assertEqual(cursor.fetchone()[0], "cancelled")

        running_score_id = uuid4()
        running_retest_id = uuid4()
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "INSERT INTO visibility_score_runs ("
                "id, tenant_id, project_id, collection_run_id, weight_profile_id, "
                "idempotency_key, window_start, window_end, requested_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    running_score_id,
                    self.tenant_id,
                    self.project_a,
                    collection_run_id,
                    profile_id,
                    f"score-running-cancel-{marker}",
                    now - timedelta(minutes=30),
                    now,
                    self.actor_id,
                ),
            )
            cursor.execute(
                "INSERT INTO retest_runs ("
                "id, tenant_id, project_id, baseline_score_snapshot_id, idempotency_key, "
                "scheduled_for, window_start, window_end, requested_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    running_retest_id,
                    self.tenant_id,
                    self.project_a,
                    baseline_snapshot_id,
                    f"retest-running-cancel-{marker}",
                    now - timedelta(minutes=1),
                    now - timedelta(minutes=30),
                    now,
                    self.actor_id,
                ),
            )
            cursor.execute(
                "INSERT INTO retest_run_queries ("
                "tenant_id, project_id, retest_run_id, monitoring_query_id, ordinal) "
                "VALUES (%s, %s, %s, %s, 0)",
                (
                    self.tenant_id,
                    self.project_a,
                    running_retest_id,
                    monitoring_query_id,
                ),
            )

        active_cancel_specs = (
            (
                "visibility_score_run",
                running_score_id,
                "geno_v2_claim_visibility_score_run",
                "geno_v2_request_visibility_score_run_cancel",
                "geno_v2_heartbeat_visibility_score_run",
                "geno_v2_ack_visibility_score_run_cancel",
            ),
            (
                "retest_run",
                running_retest_id,
                "geno_v2_claim_retest_run",
                "geno_v2_request_retest_run_cancel",
                "geno_v2_heartbeat_retest_run",
                "geno_v2_ack_retest_run_cancel",
            ),
        )
        for (
            target_type,
            target_id,
            claim_function,
            cancel_function,
            heartbeat_function,
            ack_function,
        ) in active_cancel_specs:
            active_worker = f"cancel-{target_type}-{marker}"
            with self._worker_transaction() as cursor:
                cursor.execute(
                    f"SELECT lease_token FROM {claim_function}(%s, 30, %s) "
                    "WHERE id = %s",
                    (active_worker, self.project_a, target_id),
                )
                active_token = cursor.fetchone()[0]
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    f"SELECT status FROM {cancel_function}(%s, %s)",
                    (target_id, f"cancel active {target_type}"),
                )
                self.assertEqual(cursor.fetchone()[0], "running")
            with self.assertRaises(psycopg.Error) as cancelled_heartbeat:
                with self._worker_transaction() as cursor:
                    cursor.execute(
                        f"SELECT {heartbeat_function}(%s, %s, %s, 30)",
                        (target_id, active_worker, active_token),
                    )
            self.assertEqual(cancelled_heartbeat.exception.sqlstate, "55000")
            with self._worker_transaction() as cursor:
                cursor.execute(
                    f"SELECT status FROM {ack_function}(%s, %s, %s)",
                    (target_id, active_worker, active_token),
                )
                self.assertEqual(cursor.fetchone()[0], "cancelled")

        _, _, running_job_id, _ = self._insert_collection_scope(job_status="running")
        worker_id = f"cancel-worker-{marker}"
        claim = self._claim_collection_job(worker_id)
        assert claim is not None
        _, lease_token, _ = claim
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status, cancel_requested_at IS NOT NULL "
                "FROM geno_v2_request_collection_job_cancel(%s, %s)",
                (running_job_id, "cancel active collection"),
            )
            self.assertEqual(cursor.fetchone(), ("running", True))
        with self.assertRaises(psycopg.Error) as cancelled_heartbeat:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT geno_v2_heartbeat_collection_job(%s, %s, %s, 30)",
                    (running_job_id, worker_id, lease_token),
                )
        self.assertEqual(cancelled_heartbeat.exception.sqlstate, "55000")
        with self.assertRaises(psycopg.Error) as blocked_complete:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT geno_v2_complete_collection_job(%s, %s, %s, '{}'::jsonb)",
                    (running_job_id, worker_id, lease_token),
                )
        self.assertEqual(blocked_complete.exception.sqlstate, "55000")
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_ack_collection_job_cancel(%s, %s, %s)",
                (running_job_id, worker_id, lease_token),
            )
            self.assertEqual(cursor.fetchone()[0], "cancelled")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT input_refs::text FROM audit_events "
                "WHERE target_type = 'collection_job' AND target_id = %s",
                (str(running_job_id),),
            )
            audit_payload = " ".join(row[0] for row in cursor.fetchall())
            self.assertNotIn(str(lease_token), audit_payload)

        _, _, expired_cancel_job_id, _ = self._insert_collection_scope(job_status="running")
        expired_worker = f"expired-cancel-{marker}"
        expired_claim = self._claim_collection_job(expired_worker)
        assert expired_claim is not None
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geno_v2_request_collection_job_cancel(%s, %s)",
                (expired_cancel_job_id, "recover cancelled crashed owner"),
            )
            self.assertEqual(cursor.fetchone()[0], "running")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE collection_jobs SET lease_expires_at = clock_timestamp() - "
                "interval '1 second' WHERE id = %s",
                (expired_cancel_job_id,),
            )
        self._claim_collection_job(f"recovery-sweeper-{marker}")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, completed_by FROM collection_jobs WHERE id = %s",
                (expired_cancel_job_id,),
            )
            self.assertEqual(cursor.fetchone(), ("cancelled", "lease-recovery"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
