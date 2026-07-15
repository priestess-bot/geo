from __future__ import annotations

import hashlib
import os
import threading
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Iterator
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb


BEHAVIOR_TEST_ENABLED = os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@unittest.skipUnless(BEHAVIOR_TEST_ENABLED, "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2KnowledgePostgresTest(unittest.TestCase):
    tenant_id: UUID
    project_a: UUID
    project_b: UUID
    entity_a: UUID
    entity_b: UUID
    actor_id: str
    session_hash: str
    content_actor_id: str
    content_session_hash: str
    client_actor_id: str
    client_session_hash: str
    market_code: str
    industry_code: str
    import_quality_definition_id: UUID

    @classmethod
    def setUpClass(cls) -> None:
        marker = uuid4().hex
        cls.tenant_id = uuid4()
        cls.project_a = uuid4()
        cls.project_b = uuid4()
        cls.entity_a = uuid4()
        cls.entity_b = uuid4()
        cls.actor_id = f"knowledge-architect-{marker}@example.test"
        cls.session_hash = _digest(f"knowledge-session-{marker}")
        cls.content_actor_id = f"content-operator-{marker}@example.test"
        cls.content_session_hash = _digest(f"content-session-{marker}")
        cls.client_actor_id = f"client-viewer-{marker}@example.test"
        cls.client_session_hash = _digest(f"client-session-{marker}")
        cls.market_code = f"K-{marker}"
        cls.industry_code = f"geo-{marker}"
        cls.import_quality_definition_id = uuid4()
        now = datetime.now(UTC)

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO market_profiles (market_code, payload) VALUES (%s, %s)",
                (cls.market_code, Jsonb({"fixture": "knowledge"})),
            )
            cursor.execute(
                "INSERT INTO industry_profiles "
                "(market_code, industry_code, payload) VALUES (%s, %s, %s)",
                (
                    cls.market_code,
                    cls.industry_code,
                    Jsonb({"fixture": "knowledge"}),
                ),
            )
            cursor.execute(
                "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
                (cls.tenant_id, f"Knowledge {marker}", f"knowledge-{marker}"),
            )
            for project_id, name in (
                (cls.project_a, "Knowledge A"),
                (cls.project_b, "Knowledge B"),
            ):
                cursor.execute(
                    "INSERT INTO projects ("
                    "id, tenant_id, name, market_code, industry_code, target_brand, "
                    "category, prompt_version, status) "
                    "VALUES (%s, %s, %s, %s, %s, 'Knowledge Brand', "
                    "'GEO', 'v1', 'active')",
                    (
                        project_id,
                        cls.tenant_id,
                        name,
                        cls.market_code,
                        cls.industry_code,
                    ),
                )
            for entity_id, project_id, name in (
                (cls.entity_a, cls.project_a, "Primary Knowledge Brand"),
                (cls.entity_b, cls.project_b, "Other Project Brand"),
            ):
                cursor.execute(
                    "INSERT INTO product_entities ("
                    "id, tenant_id, project_id, entity_kind, canonical_name, "
                    "created_by, updated_by) "
                    "VALUES (%s, %s, %s, 'brand', %s, 'fixture', 'fixture')",
                    (entity_id, cls.tenant_id, project_id, name),
                )
            cursor.execute(
                "INSERT INTO project_members "
                "(tenant_id, project_id, user_id, role) "
                "VALUES (%s, %s, %s, 'knowledge_architect')",
                (cls.tenant_id, cls.project_a, cls.actor_id),
            )
            cursor.execute(
                "SELECT permission FROM unnest("
                "geo_v2_permissions_for_role('knowledge_architect')) "
                "AS item(permission) ORDER BY permission"
            )
            permissions = [row[0] for row in cursor.fetchall()]
            project_scope = {
                "project_id": str(cls.project_a),
                "roles": ["knowledge_architect"],
                "permissions": permissions,
                "portal_capabilities": ["portal.admin.access"],
                "scope_sources": ["direct_member"],
            }

            invitation_id = uuid4()
            attempt_id = uuid4()
            session_id = uuid4()
            invitation_hash = _digest(f"knowledge-invitation-{marker}")
            cursor.execute(
                "INSERT INTO project_member_invitations ("
                "id, tenant_id, project_id, email, role, invite_token_hash, audience, "
                "allowed_surfaces, invited_by, expires_at, created_at) "
                "VALUES (%s, %s, %s, %s, 'knowledge_architect', %s, 'admin', "
                "ARRAY['admin']::text[], 'knowledge-test', %s, %s)",
                (
                    invitation_id,
                    cls.tenant_id,
                    cls.project_a,
                    cls.actor_id,
                    invitation_hash,
                    now + timedelta(days=2),
                    now - timedelta(seconds=3),
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
                    _digest(f"knowledge-idempotency-{marker}"),
                    _digest(f"knowledge-request-{marker}"),
                    invitation_hash,
                    now - timedelta(seconds=2),
                ),
            )
            cursor.execute(
                "INSERT INTO runtime_sessions ("
                "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
                "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
                "issued_by, issued_at, expires_at, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, %s, %s, "
                "'knowledge-test', %s, %s, %s)",
                (
                    session_id,
                    cls.session_hash,
                    cls.actor_id,
                    cls.tenant_id,
                    Jsonb([str(cls.project_a)]),
                    Jsonb(["knowledge_architect"]),
                    Jsonb(permissions),
                    Jsonb([project_scope]),
                    attempt_id,
                    now,
                    now + timedelta(days=1),
                    Jsonb({"fixture": "knowledge"}),
                ),
            )
            cursor.execute(
                "UPDATE project_member_invitations SET status = 'accepted', "
                "accepted_by_attempt_id = %s, accepted_at = %s, "
                "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
                "WHERE id = %s",
                (attempt_id, now - timedelta(seconds=1), invitation_id),
            )
            cursor.execute(
                "UPDATE auth_invitation_redemption_attempts SET status = 'succeeded', "
                "session_id = %s, delivery_ciphertext = %s, delivery_key_id = %s, "
                "delivery_nonce = %s, delivery_expires_at = %s, "
                "updated_at = greatest(clock_timestamp(), updated_at + interval '1 microsecond') "
                "WHERE id = %s",
                (
                    session_id,
                    b"knowledge-encrypted-fixture",
                    "knowledge-key",
                    b"knowledge-12",
                    now + timedelta(minutes=15),
                    attempt_id,
                ),
            )
            for role, actor_id, session_hash, surface, portal_capability in (
                (
                    "content_operator",
                    cls.content_actor_id,
                    cls.content_session_hash,
                    "admin",
                    "portal.admin.access",
                ),
                (
                    "client_viewer",
                    cls.client_actor_id,
                    cls.client_session_hash,
                    "customer",
                    "portal.customer.access",
                ),
            ):
                cursor.execute(
                    "INSERT INTO project_members "
                    "(tenant_id, project_id, user_id, role) VALUES (%s, %s, %s, %s)",
                    (cls.tenant_id, cls.project_a, actor_id, role),
                )
                cursor.execute(
                    "SELECT permission FROM unnest(geo_v2_permissions_for_role(%s)) "
                    "AS item(permission) ORDER BY permission",
                    (role,),
                )
                scoped_permissions = [row[0] for row in cursor.fetchall()]
                scoped_project = {
                    "project_id": str(cls.project_a),
                    "roles": [role],
                    "permissions": scoped_permissions,
                    "portal_capabilities": [portal_capability],
                    "scope_sources": ["direct_member"],
                }
                scoped_invitation_id = uuid4()
                scoped_attempt_id = uuid4()
                scoped_session_id = uuid4()
                scoped_invitation_hash = _digest(
                    f"knowledge-{role}-invitation-{marker}"
                )
                cursor.execute(
                    "INSERT INTO project_member_invitations ("
                    "id, tenant_id, project_id, email, role, invite_token_hash, "
                    "audience, allowed_surfaces, invited_by, expires_at, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, ARRAY[%s]::text[], "
                    "'knowledge-test', %s, %s)",
                    (
                        scoped_invitation_id,
                        cls.tenant_id,
                        cls.project_a,
                        actor_id,
                        role,
                        scoped_invitation_hash,
                        surface,
                        surface,
                        now + timedelta(days=2),
                        now - timedelta(seconds=3),
                    ),
                )
                cursor.execute(
                    "INSERT INTO auth_invitation_redemption_attempts ("
                    "id, tenant_id, project_id, invitation_id, requested_surface, "
                    "idempotency_key_hash, request_hash, token_fingerprint, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        scoped_attempt_id,
                        cls.tenant_id,
                        cls.project_a,
                        scoped_invitation_id,
                        surface,
                        _digest(f"knowledge-{role}-idempotency-{marker}"),
                        _digest(f"knowledge-{role}-request-{marker}"),
                        scoped_invitation_hash,
                        now - timedelta(seconds=2),
                    ),
                )
                cursor.execute(
                    "INSERT INTO runtime_sessions ("
                    "id, session_token_hash, actor_id, tenant_id, project_ids, roles, "
                    "permissions, tenant_roles, project_scopes, redemption_attempt_id, "
                    "issued_by, issued_at, expires_at, metadata) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, %s, %s, "
                    "'knowledge-test', %s, %s, %s)",
                    (
                        scoped_session_id,
                        session_hash,
                        actor_id,
                        cls.tenant_id,
                        Jsonb([str(cls.project_a)]),
                        Jsonb([role]),
                        Jsonb(scoped_permissions),
                        Jsonb([scoped_project]),
                        scoped_attempt_id,
                        now,
                        now + timedelta(days=1),
                        Jsonb({"fixture": "knowledge", "role": role}),
                    ),
                )
                cursor.execute(
                    "UPDATE project_member_invitations SET status = 'accepted', "
                    "accepted_by_attempt_id = %s, accepted_at = %s, "
                    "updated_at = greatest(clock_timestamp(), "
                    "updated_at + interval '1 microsecond') WHERE id = %s",
                    (
                        scoped_attempt_id,
                        now - timedelta(seconds=1),
                        scoped_invitation_id,
                    ),
                )
                cursor.execute(
                    "UPDATE auth_invitation_redemption_attempts SET status = 'succeeded', "
                    "session_id = %s, delivery_ciphertext = %s, delivery_key_id = %s, "
                    "delivery_nonce = %s, delivery_expires_at = %s, "
                    "updated_at = greatest(clock_timestamp(), "
                    "updated_at + interval '1 microsecond') WHERE id = %s",
                    (
                        scoped_session_id,
                        b"knowledge-encrypted-fixture",
                        "knowledge-key",
                        b"knowledge-12",
                        now + timedelta(minutes=15),
                        scoped_attempt_id,
                    ),
                )
            cursor.execute(
                "INSERT INTO knowledge_quality_definitions ("
                "id, tenant_id, project_id, definition_key, version, job_type, "
                "target_kind, severity_on_failure, rule_contract, policy_class, "
                "required, active, created_by) VALUES ("
                "%s, %s, %s, 'import-source-integrity', 1, 'import', "
                "'source_revision', 'hard_block', %s, 'traceability', true, true, "
                "'system-fixture')",
                (
                    cls.import_quality_definition_id,
                    cls.tenant_id,
                    cls.project_a,
                    Jsonb(
                        {
                            "policy_class": "traceability",
                            "rule": "source snapshot must retain exact lineage",
                        }
                    ),
                ),
            )

    @contextmanager
    def _runtime_transaction(
        self, session_hash: str | None = None
    ) -> Iterator[psycopg.Cursor[object]]:
        connection = psycopg.connect(autocommit=True)
        cursor = connection.cursor()
        try:
            cursor.execute("SET ROLE geo_v2_api_login")
            cursor.execute("BEGIN")
            cursor.execute("SET LOCAL ROLE geo_v2_runtime")
            cursor.execute(
                "SELECT set_config('app.session_token_hash', %s, true)",
                (session_hash or self.session_hash,),
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
            cursor.execute("SET ROLE geo_v2_worker_login")
            cursor.execute("BEGIN")
            cursor.execute("SET LOCAL ROLE geo_v2_worker")
            cursor.execute("SELECT set_config('app.session_token_hash', '', true)")
            yield cursor
            cursor.execute("COMMIT")
        except BaseException:
            cursor.execute("ROLLBACK")
            raise
        finally:
            cursor.close()
            connection.close()

    def _import_snapshot(
        self,
        *,
        source_asset_id: UUID,
        artifact_id: UUID,
        artifact_outbox_id: UUID,
        suffix: str,
        entity_id: UUID | None = None,
    ) -> dict[str, object]:
        content_hash = _digest(f"knowledge-input-{suffix}")
        return {
            "run_kind": "ingest",
            "source": {
                "source_asset_id": str(source_asset_id),
                "source_mode": "text",
                "source_text_hash": content_hash,
                "source_label": f"Customer source {suffix}",
                "authority_grade": "A",
                # The command must replace these caller-supplied governance claims
                # with the fixed upload-attestation policy for text/file/csv input.
                "usage_rights_status": "public_reuse",
                "authorization_basis": "caller-asserted-and-untrusted",
                "policy_version": "caller-policy-must-not-win",
                "external_model_use_allowed": False,
                "public_adaptation_allowed": False,
                "confidentiality": "internal",
                "consent_status": "granted",
                "claim_risk": "low",
                "subjects": [
                    {
                        "id": str(uuid4()),
                        "subject_entity_id": str(entity_id or self.entity_a),
                        "subject_role": "primary_brand",
                    }
                ],
                "allowed_channels": [
                    {"publication_channel": "website", "allowed": True}
                ],
                "artifact": {
                    "id": str(artifact_id),
                    "outbox_id": str(artifact_outbox_id),
                    "storage_uri": f"s3://knowledge/{suffix}/input.txt",
                    "storage_key": f"knowledge/{suffix}/input.txt",
                    "content_hash": content_hash,
                    "size_bytes": 42,
                    "content_type": "text/plain",
                },
            },
        }

    def _create_import_job(
        self,
        *,
        suffix: str | None = None,
        project_id: UUID | None = None,
        entity_id: UUID | None = None,
    ) -> dict[str, object]:
        suffix = suffix or uuid4().hex
        job_id = uuid4()
        run_id = uuid4()
        stage_id = uuid4()
        source_id = uuid4()
        source_asset_id = uuid4()
        artifact_id = uuid4()
        artifact_outbox_id = uuid4()
        snapshot = self._import_snapshot(
            source_asset_id=source_asset_id,
            artifact_id=artifact_id,
            artifact_outbox_id=artifact_outbox_id,
            suffix=suffix,
            entity_id=entity_id,
        )
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT id, input_hash, request_hash, status "
                "FROM geo_v2_create_knowledge_job("
                "%s, %s, %s, %s, %s, 'import', %s, %s, NULL)",
                (
                    job_id,
                    project_id or self.project_a,
                    run_id,
                    stage_id,
                    source_id,
                    f"knowledge-import-{suffix}",
                    Jsonb(snapshot),
                ),
            )
            row = cursor.fetchone()
        return {
            "job_id": job_id,
            "run_id": run_id,
            "stage_id": stage_id,
            "source_id": source_id,
            "source_asset_id": source_asset_id,
            "artifact_id": artifact_id,
            "artifact_outbox_id": artifact_outbox_id,
            "snapshot": snapshot,
            "input_hash": row[1],
            "request_hash": row[2],
            "status": row[3],
            "idempotency_key": f"knowledge-import-{suffix}",
        }

    def _finalize_artifact(self, target_outbox_id: UUID) -> None:
        for _ in range(50):
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id, lease_token, expected_content_hash "
                    "FROM geo_v2_claim_artifact_finalize(%s, 60, %s)",
                    ("knowledge-artifact-finalizer", self.project_a),
                )
                claimed = cursor.fetchone()
                if claimed is None:
                    self.fail(f"artifact finalize outbox {target_outbox_id} was not claimable")
                cursor.execute(
                    "SELECT id FROM geo_v2_complete_artifact_finalize(%s, %s, %s, %s)",
                    (claimed[0], "knowledge-artifact-finalizer", claimed[1], claimed[2]),
                )
            if claimed[0] == target_outbox_id:
                return
        self.fail(f"artifact finalize outbox {target_outbox_id} was starved")

    def _claim_target_artifact(self, target_outbox_id: UUID) -> tuple[UUID, str]:
        for _ in range(50):
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id, lease_token, expected_content_hash "
                    "FROM geo_v2_claim_artifact_finalize(%s, 60, %s)",
                    ("knowledge-artifact-failure", self.project_a),
                )
                claimed = cursor.fetchone()
                if claimed is None:
                    self.fail(f"artifact finalize outbox {target_outbox_id} was not claimable")
                if claimed[0] == target_outbox_id:
                    return claimed[1], claimed[2]
                cursor.execute(
                    "SELECT id FROM geo_v2_complete_artifact_finalize(%s, %s, %s, %s)",
                    (
                        claimed[0],
                        "knowledge-artifact-failure",
                        claimed[1],
                        claimed[2],
                    ),
                )
        self.fail(f"artifact finalize outbox {target_outbox_id} was starved")

    def _claim_job(
        self,
        expected_job_id: UUID,
        worker_id: str = "knowledge-worker",
    ) -> tuple[UUID, UUID, str]:
        # Each test owns a target job, while earlier tests may intentionally leave
        # terminal/finalizing fixtures behind. Scheduling the target explicitly
        # keeps test order from affecting which row SKIP LOCKED returns.
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE knowledge_pipeline_jobs SET priority = 1000000, "
                "next_attempt_at = clock_timestamp() WHERE id = %s",
                (expected_job_id,),
            )
            cursor.execute(
                "UPDATE knowledge_pipeline_jobs SET next_attempt_at = "
                "clock_timestamp() + interval '1 day' "
                "WHERE project_id = %s AND job_type = 'import' AND status = 'queued' "
                "AND id <> %s",
                (self.project_a, expected_job_id),
            )
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT id, lease_token, status FROM "
                "geo_v2_claim_knowledge_job(%s, 60, %s, 'import')",
                (worker_id, self.project_a),
            )
            row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], expected_job_id)
        return row[0], row[1], row[2]

    def _canonical_json_hash(self, payload: dict[str, object]) -> str:
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT encode(digest(%s::jsonb::text, 'sha256'), 'hex')",
                (Jsonb(payload),),
            )
            return cursor.fetchone()[0]

    def _import_result(self, ids: dict[str, object]) -> dict[str, object]:
        suffix = uuid4().hex
        output_artifact_id = uuid4()
        output_outbox_id = uuid4()
        revision_id = uuid4()
        governance_id = uuid4()
        quality_run_id = uuid4()
        content_hash = _digest(f"knowledge-output-{suffix}")
        return {
            "artifacts": [
                {
                    "id": str(output_artifact_id),
                    "outbox_id": str(output_outbox_id),
                    "job_artifact_id": str(uuid4()),
                    "asset_type": "knowledge_source_snapshot",
                    "storage_uri": f"s3://knowledge/{suffix}/source.txt",
                    "storage_key": f"knowledge/{suffix}/source.txt",
                    "content_hash": content_hash,
                    "size_bytes": 40,
                    "content_type": "text/plain",
                    "artifact_role": "source_snapshot",
                }
            ],
            "source_asset": {
                "id": str(ids["source_asset_id"]),
                "revision_id": str(revision_id),
                "governance_id": str(governance_id),
            },
            "source_artifact_links": [
                {
                    "id": str(uuid4()),
                    "evidence_asset_id": str(output_artifact_id),
                    "artifact_role": "source_snapshot",
                }
            ],
            "quality_runs": [
                {
                    "id": str(quality_run_id),
                    "quality_definition_id": str(self.import_quality_definition_id),
                    "target_kind": "source_revision",
                    "source_revision_id": str(revision_id),
                    "status": "passed",
                    "result_hash": _digest(f"quality-{suffix}"),
                }
            ],
            "quality_findings": [],
            "_test_ids": {
                "output_artifact_id": str(output_artifact_id),
                "output_outbox_id": str(output_outbox_id),
                "revision_id": str(revision_id),
                "governance_id": str(governance_id),
                "quality_run_id": str(quality_run_id),
            },
        }

    def _seed_review_graph(self) -> dict[str, UUID | str]:
        marker = uuid4().hex
        run_id = uuid4()
        import_stage_id = uuid4()
        chunk_stage_id = uuid4()
        fact_stage_id = uuid4()
        import_job_id = uuid4()
        chunk_job_id = uuid4()
        fact_job_id = uuid4()
        import_source_id = uuid4()
        source_asset_id = uuid4()
        revision_id = uuid4()
        governance_id = uuid4()
        source_artifact_id = uuid4()
        input_artifact_id = uuid4()
        raw_artifact_id = uuid4()
        chunk_id = uuid4()
        quality_definition_id = uuid4()
        valid_candidate_id = uuid4()
        maker_candidate_id = uuid4()
        source_hash = _digest(f"review-source-{marker}")
        chunk_hash = _digest(f"review-chunk-{marker}")
        result_hash = _digest(f"review-result-{marker}")
        fact_input_snapshot = {"fixture": "review", "chunk_id": str(chunk_id)}
        fact_input_hash = self._canonical_json_hash(fact_input_snapshot)
        now = datetime.now(UTC)

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO knowledge_pipeline_runs ("
                "id, tenant_id, project_id, run_kind, status, idempotency_key, "
                "requested_by, created_at, updated_at) "
                "VALUES (%s, %s, %s, 'fact_refresh', 'running', %s, %s, %s, %s)",
                (
                    run_id,
                    self.tenant_id,
                    self.project_a,
                    f"review-run-{marker}",
                    "source-uploader@example.test",
                    now - timedelta(minutes=5),
                    now,
                ),
            )
            for stage_id, stage_key, ordinal, status in (
                (import_stage_id, "import", 10, "succeeded"),
                (chunk_stage_id, "chunk", 40, "succeeded"),
                (fact_stage_id, "fact_extract", 60, "running"),
            ):
                cursor.execute(
                    "INSERT INTO knowledge_pipeline_stages ("
                    "id, tenant_id, project_id, pipeline_run_id, stage_key, ordinal, "
                    "status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, "
                    "%s, %s, %s, %s)",
                    (
                        stage_id,
                        self.tenant_id,
                        self.project_a,
                        run_id,
                        stage_key,
                        ordinal,
                        status,
                        now - timedelta(minutes=5),
                        now,
                    ),
                )
            cursor.execute(
                "INSERT INTO evidence_assets ("
                "id, tenant_id, project_id, asset_type, storage_uri, storage_key, "
                "content_hash, size_bytes, content_type, access_policy, retention_policy, "
                "source_kind, artifact_status, finalized_at, finalized_by, created_by) "
                "VALUES (%s, %s, %s, 'knowledge_import_snapshot', %s, %s, %s, 100, "
                "'text/plain', 'knowledge-internal', 'knowledge-source-v2', "
                "'knowledge_import_input', 'finalized', %s, 'artifact-finalizer', "
                "'source-uploader@example.test')",
                (
                    input_artifact_id,
                    self.tenant_id,
                    self.project_a,
                    f"s3://knowledge/review/{marker}/input",
                    f"knowledge/review/{marker}/input",
                    _digest(f"review-input-{marker}"),
                    now,
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_import_sources ("
                "id, tenant_id, project_id, pipeline_run_id, target_source_asset_id, "
                "source_mode, source_text_hash, upload_evidence_asset_id, source_label, "
                "authority_grade, usage_rights_status, authorization_basis, "
                "authorised_by, authorised_at, confidentiality, consent_status, "
                "external_model_use_allowed, public_adaptation_allowed, customer_visible, "
                "public_disclosure_allowed, public_source_url, public_source_title, "
                "citation_label, quotation_allowed, attribution_required, claim_risk, "
                "policy_version, governance_hash, valid_from, requested_by) VALUES ("
                "%s, %s, %s, %s, %s, 'text', %s, %s, %s, 'A', "
                "'customer_authorised', 'project_upload_attestation_v1', %s, %s, "
                "'internal', 'granted', true, true, true, true, %s, %s, %s, true, "
                "true, 'low', 'project_upload_policy_v1', %s, %s, %s)",
                (
                    import_source_id,
                    self.tenant_id,
                    self.project_a,
                    run_id,
                    source_asset_id,
                    _digest(f"review-input-{marker}"),
                    input_artifact_id,
                    f"Review source {marker}",
                    "source-uploader@example.test",
                    now - timedelta(days=1),
                    f"https://example.test/source/{marker}",
                    f"Source {marker}",
                    f"Source {marker}",
                    _digest(f"import-governance-{marker}"),
                    now - timedelta(days=1),
                    "source-uploader@example.test",
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_import_source_subjects ("
                "tenant_id, project_id, import_source_id, subject_entity_id, subject_role) "
                "VALUES (%s, %s, %s, %s, 'primary_brand')",
                (self.tenant_id, self.project_a, import_source_id, self.entity_a),
            )
            cursor.execute(
                "INSERT INTO knowledge_import_source_channels ("
                "tenant_id, project_id, import_source_id, publication_channel, allowed) "
                "VALUES (%s, %s, %s, 'website', true)",
                (self.tenant_id, self.project_a, import_source_id),
            )
            for job_id, stage_id, job_type, requested_by, import_source in (
                (
                    import_job_id,
                    import_stage_id,
                    "import",
                    "source-uploader@example.test",
                    import_source_id,
                ),
                (chunk_job_id, chunk_stage_id, "chunk", "pipeline-worker", None),
            ):
                cursor.execute(
                    "INSERT INTO knowledge_pipeline_jobs ("
                    "id, tenant_id, project_id, pipeline_run_id, pipeline_stage_id, "
                    "import_source_id, job_type, status, idempotency_key, request_hash, "
                    "input_hash, attempt_count, finalizing_result_hash, result_hash, "
                    "completed_at, completed_by, requested_by, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 'succeeded', %s, %s, "
                    "%s, 1, %s, %s, %s, 'pipeline-worker', %s, %s, %s)",
                    (
                        job_id,
                        self.tenant_id,
                        self.project_a,
                        run_id,
                        stage_id,
                        import_source,
                        job_type,
                        f"{job_type}-{marker}",
                        _digest(f"{job_type}-request-{marker}"),
                        _digest(f"{job_type}-input-{marker}"),
                        result_hash,
                        result_hash,
                        now,
                        requested_by,
                        now - timedelta(minutes=4),
                        now,
                    ),
                )
            fact_lease_token = uuid4()
            cursor.execute(
                "INSERT INTO knowledge_pipeline_jobs ("
                "id, tenant_id, project_id, pipeline_run_id, pipeline_stage_id, "
                "job_type, status, idempotency_key, request_hash, input_hash, "
                "attempt_count, lease_owner, lease_token, lease_expires_at, heartbeat_at, "
                "started_at, requested_by, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, 'fact_extract', 'running', %s, %s, %s, "
                "1, 'fact-worker', %s, %s, %s, %s, 'fact-operator', %s, %s)",
                (
                    fact_job_id,
                    self.tenant_id,
                    self.project_a,
                    run_id,
                    fact_stage_id,
                    f"fact-{marker}",
                    _digest(f"fact-request-{marker}"),
                    fact_input_hash,
                    fact_lease_token,
                    now + timedelta(hours=1),
                    now,
                    now - timedelta(minutes=2),
                    now - timedelta(minutes=3),
                    now,
                ),
            )
            for artifact_id, asset_type, content_hash, source_kind in (
                (source_artifact_id, "knowledge_source_snapshot", source_hash, "knowledge_import"),
                (raw_artifact_id, "knowledge_raw_model_output", result_hash, "knowledge_fact_extract"),
            ):
                cursor.execute(
                    "INSERT INTO evidence_assets ("
                    "id, tenant_id, project_id, asset_type, storage_uri, storage_key, "
                    "content_hash, size_bytes, content_type, access_policy, "
                    "retention_policy, source_kind, artifact_status, finalized_at, "
                    "finalized_by, created_by) VALUES ("
                    "%s, %s, %s, %s, %s, %s, %s, 100, 'application/json', "
                    "'knowledge-internal', 'knowledge-source-v2', %s, 'finalized', "
                    "%s, 'artifact-finalizer', 'pipeline-worker')",
                    (
                        artifact_id,
                        self.tenant_id,
                        self.project_a,
                        asset_type,
                        f"s3://knowledge/review/{marker}/{artifact_id}",
                        f"knowledge/review/{marker}/{artifact_id}",
                        content_hash,
                        source_kind,
                        now,
                    ),
                )
            cursor.execute(
                "INSERT INTO knowledge_job_artifacts ("
                "tenant_id, project_id, knowledge_job_id, evidence_asset_id, artifact_role) "
                "VALUES (%s, %s, %s, %s, 'source_snapshot'), "
                "(%s, %s, %s, %s, 'raw_model_output')",
                (
                    self.tenant_id,
                    self.project_a,
                    import_job_id,
                    source_artifact_id,
                    self.tenant_id,
                    self.project_a,
                    fact_job_id,
                    raw_artifact_id,
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_source_assets ("
                "id, tenant_id, project_id, asset_kind, status, title, created_by) "
                "VALUES (%s, %s, %s, 'pasted_text', 'active', %s, %s)",
                (
                    source_asset_id,
                    self.tenant_id,
                    self.project_a,
                    f"Review source {marker}",
                    "source-uploader@example.test",
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_source_asset_revisions ("
                "id, tenant_id, project_id, knowledge_job_id, source_asset_id, "
                "revision_number, source_content_hash, source_uri, mime_type, "
                "byte_size, status, created_by) VALUES ("
                "%s, %s, %s, %s, %s, 1, %s, %s, 'text/plain', 100, "
                "'active', 'pipeline-worker')",
                (
                    revision_id,
                    self.tenant_id,
                    self.project_a,
                    import_job_id,
                    source_asset_id,
                    source_hash,
                    f"s3://knowledge/review/{marker}/source",
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_source_governance_versions ("
                "id, tenant_id, project_id, source_asset_id, source_revision_id, "
                "governance_version, authority_grade, usage_rights_status, "
                "authorization_basis, authorised_by, authorised_at, confidentiality, "
                "consent_status, external_model_use_allowed, public_adaptation_allowed, "
                "customer_visible, public_disclosure_allowed, public_source_url, "
                "public_source_title, citation_label, quotation_allowed, "
                "attribution_required, claim_risk, policy_version, governance_hash, "
                "valid_from, created_by) VALUES ("
                "%s, %s, %s, %s, %s, 1, 'A', 'customer_authorised', "
                "'project_upload_attestation_v1', 'source-uploader@example.test', %s, "
                "'internal', 'granted', true, true, true, true, %s, %s, %s, true, "
                "true, 'low', 'project_upload_policy_v1', %s, %s, 'pipeline-worker')",
                (
                    governance_id,
                    self.tenant_id,
                    self.project_a,
                    source_asset_id,
                    revision_id,
                    now - timedelta(days=1),
                    f"https://example.test/source/{marker}",
                    f"Source {marker}",
                    f"Source {marker}",
                    _digest(f"governance-{marker}"),
                    now - timedelta(days=1),
                ),
            )
            cursor.execute(
                "UPDATE knowledge_source_assets SET current_revision_id = %s, "
                "current_governance_version_id = %s, updated_at = %s WHERE id = %s",
                (revision_id, governance_id, now, source_asset_id),
            )
            cursor.execute(
                "INSERT INTO knowledge_source_governance_channels ("
                "tenant_id, project_id, governance_version_id, publication_channel, allowed) "
                "VALUES (%s, %s, %s, 'website', true)",
                (self.tenant_id, self.project_a, governance_id),
            )
            cursor.execute(
                "INSERT INTO knowledge_source_subjects ("
                "tenant_id, project_id, source_revision_id, subject_entity_id, subject_role) "
                "VALUES (%s, %s, %s, %s, 'primary_brand')",
                (self.tenant_id, self.project_a, revision_id, self.entity_a),
            )
            cursor.execute(
                "INSERT INTO knowledge_source_revision_artifacts ("
                "tenant_id, project_id, source_revision_id, evidence_asset_id, artifact_role) "
                "VALUES (%s, %s, %s, %s, 'source_snapshot')",
                (self.tenant_id, self.project_a, revision_id, source_artifact_id),
            )
            cursor.execute(
                "INSERT INTO knowledge_chunks ("
                "id, tenant_id, project_id, knowledge_job_id, source_revision_id, "
                "chunk_index, chunk_kind, text_content, token_count, content_hash, "
                "locale, status) VALUES (%s, %s, %s, %s, %s, 0, 'text', %s, "
                "12, %s, 'zh-CN', 'active')",
                (
                    chunk_id,
                    self.tenant_id,
                    self.project_a,
                    chunk_job_id,
                    revision_id,
                    "该产品在已验证的使用场景中表现稳定。",
                    chunk_hash,
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_quality_definitions ("
                "id, tenant_id, project_id, definition_key, version, job_type, "
                "target_kind, severity_on_failure, rule_contract, policy_class, "
                "required, active, created_by) VALUES ("
                "%s, %s, %s, %s, 1, 'fact_extract', 'fact_candidate', "
                "'hard_block', %s, 'traceability', true, true, 'system-fixture')",
                (
                    quality_definition_id,
                    self.tenant_id,
                    self.project_a,
                    f"fact-candidate-integrity-{marker}",
                    Jsonb({"policy_class": "traceability", "rule": "candidate-lineage"}),
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_job_quality_definitions ("
                "tenant_id, project_id, knowledge_job_id, quality_definition_id) "
                "VALUES (%s, %s, %s, %s)",
                (
                    self.tenant_id,
                    self.project_a,
                    fact_job_id,
                    quality_definition_id,
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_job_input_snapshots ("
                "tenant_id, project_id, knowledge_job_id, snapshot, snapshot_hash) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    self.tenant_id,
                    self.project_a,
                    fact_job_id,
                    Jsonb(fact_input_snapshot),
                    fact_input_hash,
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_chunk_set_job_inputs ("
                "tenant_id, project_id, knowledge_job_id, chunk_id, "
                "governance_version_id, input_kind) "
                "VALUES (%s, %s, %s, %s, %s, 'fact_extract')",
                (
                    self.tenant_id,
                    self.project_a,
                    fact_job_id,
                    chunk_id,
                    governance_id,
                ),
            )
            for candidate_id, submitter, statement in (
                (
                    valid_candidate_id,
                    "fact-worker",
                    "该品牌产品在真实消费者描述的场景中表现稳定。",
                ),
                (
                    maker_candidate_id,
                    self.actor_id,
                    "提交者不能审核自己提交的候选事实。",
                ),
            ):
                cursor.execute(
                    "INSERT INTO knowledge_fact_candidates ("
                    "id, tenant_id, project_id, knowledge_job_id, subject_entity_id, "
                    "subject_role, fact_type, statement, locale, confidence, "
                    "submitted_for_review_by) VALUES ("
                    "%s, %s, %s, %s, %s, 'primary_brand', 'product_experience', "
                    "%s, 'zh-CN', 0.98, %s)",
                    (
                        candidate_id,
                        self.tenant_id,
                        self.project_a,
                        fact_job_id,
                        self.entity_a,
                        statement,
                        submitter,
                    ),
                )
                cursor.execute(
                    "INSERT INTO knowledge_fact_candidate_sources ("
                    "tenant_id, project_id, fact_candidate_id, chunk_id, locator, "
                    "source_snapshot_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        self.tenant_id,
                        self.project_a,
                        candidate_id,
                        chunk_id,
                        Jsonb({"chunk_index": 0}),
                        chunk_hash,
                    ),
                )
                cursor.execute(
                    "INSERT INTO knowledge_quality_runs ("
                    "tenant_id, project_id, knowledge_job_id, quality_definition_id, "
                    "target_kind, fact_candidate_id, status, result_hash) "
                    "VALUES (%s, %s, %s, %s, 'fact_candidate', %s, 'passed', %s)",
                    (
                        self.tenant_id,
                        self.project_a,
                        fact_job_id,
                        quality_definition_id,
                        candidate_id,
                        _digest(f"candidate-quality-{candidate_id}"),
                    ),
                )
        return {
            "run_id": run_id,
            "fact_stage_id": fact_stage_id,
            "fact_job_id": fact_job_id,
            "fact_lease_token": fact_lease_token,
            "source_asset_id": source_asset_id,
            "revision_id": revision_id,
            "governance_id": governance_id,
            "chunk_id": chunk_id,
            "chunk_hash": chunk_hash,
            "quality_definition_id": quality_definition_id,
            "valid_candidate_id": valid_candidate_id,
            "maker_candidate_id": maker_candidate_id,
            "result_hash": result_hash,
        }

    def _append_review_candidate(
        self,
        graph: dict[str, UUID | str],
        *,
        statement: str,
    ) -> UUID:
        candidate_id = uuid4()
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO knowledge_fact_candidates ("
                "id, tenant_id, project_id, knowledge_job_id, subject_entity_id, "
                "subject_role, fact_type, statement, locale, confidence, "
                "submitted_for_review_by) VALUES ("
                "%s, %s, %s, %s, %s, 'primary_brand', 'product_experience', "
                "%s, 'zh-CN', 0.97, 'fact-worker')",
                (
                    candidate_id,
                    self.tenant_id,
                    self.project_a,
                    graph["fact_job_id"],
                    self.entity_a,
                    statement,
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_fact_candidate_sources ("
                "tenant_id, project_id, fact_candidate_id, chunk_id, locator, "
                "source_snapshot_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    self.tenant_id,
                    self.project_a,
                    candidate_id,
                    graph["chunk_id"],
                    Jsonb({"chunk_index": 0}),
                    graph["chunk_hash"],
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_quality_runs ("
                "tenant_id, project_id, knowledge_job_id, quality_definition_id, "
                "target_kind, fact_candidate_id, status, result_hash) "
                "VALUES (%s, %s, %s, %s, 'fact_candidate', %s, 'passed', %s)",
                (
                    self.tenant_id,
                    self.project_a,
                    graph["fact_job_id"],
                    graph["quality_definition_id"],
                    candidate_id,
                    _digest(f"candidate-quality-{candidate_id}"),
                ),
            )
        return candidate_id

    def test_runtime_and_worker_have_no_table_dml_and_cross_project_is_atomic(self) -> None:
        with psycopg.connect() as connection, connection.cursor() as cursor:
            for role_name in ("geo_v2_runtime", "geo_v2_worker"):
                cursor.execute(
                    "SELECT has_table_privilege(%s, 'knowledge_pipeline_jobs', %s)",
                    (role_name, "INSERT,UPDATE,DELETE"),
                )
                self.assertFalse(cursor.fetchone()[0])
            cursor.execute(
                "SELECT has_function_privilege("
                "'geo_v2_worker', "
                "'geo_v2_claim_knowledge_job(text,integer,uuid,text)', 'EXECUTE'), "
                "has_function_privilege("
                "'geo_v2_runtime', "
                "'geo_v2_claim_knowledge_job(text,integer,uuid,text)', 'EXECUTE')"
            )
            worker_can_claim, runtime_can_claim = cursor.fetchone()
            self.assertTrue(worker_can_claim)
            self.assertFalse(runtime_can_claim)

        before: int
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM knowledge_pipeline_jobs")
            before = cursor.fetchone()[0]
        with self.assertRaises(psycopg.Error) as denied:
            self._create_import_job(
                project_id=self.project_b,
                entity_id=self.entity_b,
                suffix=f"cross-project-{uuid4().hex}",
            )
        self.assertEqual(denied.exception.sqlstate, "42501")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM knowledge_pipeline_jobs")
            self.assertEqual(cursor.fetchone()[0], before)

    def test_create_is_exactly_idempotent_and_dispatch_is_atomic(self) -> None:
        ids = self._create_import_job()
        self.assertEqual(ids["status"], "queued")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT snapshot_hash, snapshot, "
                "snapshot ? 'required_quality_definition_ids', "
                "snapshot::text ~* 'password|secret|api_key' "
                "FROM knowledge_job_input_snapshots WHERE knowledge_job_id = %s",
                (ids["job_id"],),
            )
            snapshot_hash, frozen, has_quality, leaks_secret = cursor.fetchone()
            self.assertEqual(snapshot_hash, ids["input_hash"])
            self.assertTrue(has_quality)
            self.assertFalse(leaks_secret)
            frozen_source = frozen["request"]["source"]
            self.assertEqual(frozen_source["usage_rights_status"], "customer_authorised")
            self.assertEqual(
                frozen_source["authorization_basis"],
                "project_upload_attestation_v1",
            )
            self.assertEqual(frozen_source["policy_version"], "project_upload_policy_v1")
            self.assertTrue(frozen_source["external_model_use_allowed"])
            self.assertTrue(frozen_source["public_adaptation_allowed"])
            self.assertNotEqual(
                frozen_source["authorization_basis"],
                ids["snapshot"]["source"]["authorization_basis"],
            )
            cursor.execute(
                "SELECT job_kind, knowledge_pipeline_job_id, job_id "
                "FROM durable_job_dispatch_outbox WHERE job_id = %s",
                (ids["job_id"],),
            )
            outbox = cursor.fetchone()
            self.assertEqual(outbox, ("knowledge_import", ids["job_id"], ids["job_id"]))

        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT id, input_hash FROM geo_v2_create_knowledge_job("
                "%s, %s, %s, %s, %s, 'import', %s, %s, NULL)",
                (
                    ids["job_id"],
                    self.project_a,
                    ids["run_id"],
                    ids["stage_id"],
                    ids["source_id"],
                    ids["idempotency_key"],
                    Jsonb(ids["snapshot"]),
                ),
            )
            self.assertEqual(cursor.fetchone(), (ids["job_id"], ids["input_hash"]))

        bad_snapshot = dict(ids["snapshot"])
        bad_snapshot["source"] = dict(bad_snapshot["source"])
        bad_snapshot["source"]["source_label"] = "changed"
        with self.assertRaises(psycopg.Error) as conflict:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_create_knowledge_job("
                    "%s, %s, %s, %s, %s, 'import', %s, %s, NULL)",
                    (
                        ids["job_id"],
                        self.project_a,
                        ids["run_id"],
                        ids["stage_id"],
                        ids["source_id"],
                        ids["idempotency_key"],
                        Jsonb(bad_snapshot),
                    ),
                )
        self.assertEqual(conflict.exception.sqlstate, "23505")

        secret_snapshot = self._import_snapshot(
            source_asset_id=uuid4(),
            artifact_id=uuid4(),
            artifact_outbox_id=uuid4(),
            suffix=uuid4().hex,
        )
        secret_snapshot["source"]["api_key"] = "must-never-persist"
        with self.assertRaises(psycopg.Error) as rejected:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_create_knowledge_job("
                    "%s, %s, %s, %s, %s, 'import', %s, %s, NULL)",
                    (
                        uuid4(),
                        self.project_a,
                        uuid4(),
                        uuid4(),
                        uuid4(),
                        f"secret-{uuid4()}",
                        Jsonb(secret_snapshot),
                    ),
                )
        self.assertEqual(rejected.exception.sqlstate, "22023")

    def test_claim_requires_finalized_input_and_read_is_lease_fenced(self) -> None:
        ids = self._create_import_job()
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT id FROM geo_v2_claim_knowledge_job(%s, 60, %s, 'import')",
                ("pre-finalize-worker", self.project_a),
            )
            self.assertIsNone(cursor.fetchone())

        self._finalize_artifact(ids["artifact_outbox_id"])
        job_id, lease_token, status = self._claim_job(ids["job_id"], "input-reader")
        self.assertEqual(job_id, ids["job_id"])
        self.assertEqual(status, "running")
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT geo_v2_read_knowledge_job_input(%s, %s, %s)",
                (job_id, "input-reader", lease_token),
            )
            payload = cursor.fetchone()[0]
            self.assertEqual(payload["input_hash"], ids["input_hash"])
            self.assertEqual(
                payload["snapshot"]["request"]["source"]["source_label"],
                ids["snapshot"]["source"]["source_label"],
            )
            self.assertEqual(
                payload["snapshot"]["request"]["source"]["usage_rights_status"],
                "customer_authorised",
            )
            self.assertNotIn("session_token_hash", payload)
        with self.assertRaises(psycopg.Error) as stale:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT geo_v2_read_knowledge_job_input(%s, %s, %s)",
                    (job_id, "input-reader", uuid4()),
                )
        self.assertEqual(stale.exception.sqlstate, "55000")

    def test_expired_lease_is_reclaimed_and_cancel_stops_heartbeat(self) -> None:
        ids = self._create_import_job()
        self._finalize_artifact(ids["artifact_outbox_id"])
        job_id, first_token, _ = self._claim_job(ids["job_id"], "crashed-worker")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE knowledge_pipeline_jobs SET lease_expires_at = "
                "clock_timestamp() - interval '1 second' WHERE id = %s",
                (job_id,),
            )
        reclaimed_id, second_token, _ = self._claim_job(job_id, "recovery-worker")
        self.assertEqual(reclaimed_id, job_id)
        self.assertNotEqual(second_token, first_token)
        with self.assertRaises(psycopg.Error) as stale:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_heartbeat_knowledge_job(%s, %s, %s, 60)",
                    (job_id, "crashed-worker", first_token),
                )
        self.assertEqual(stale.exception.sqlstate, "55000")

        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_request_knowledge_job_cancel(%s, %s)",
                (job_id, "operator cancelled test job"),
            )
            self.assertEqual(cursor.fetchone()[0], "running")
        with self.assertRaises(psycopg.Error) as cancelled_heartbeat:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_heartbeat_knowledge_job(%s, %s, %s, 60)",
                    (job_id, "recovery-worker", second_token),
                )
        self.assertEqual(cancelled_heartbeat.exception.sqlstate, "55000")
        with self.assertRaises(psycopg.Error) as cancelled_fail:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_fail_knowledge_job("
                    "%s, %s, %s, 'worker_error', 'must not replace cancel', "
                    "false, 0)",
                    (job_id, "recovery-worker", second_token),
                )
        self.assertEqual(cancelled_fail.exception.sqlstate, "55000")
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_ack_knowledge_job_cancel(%s, %s, %s)",
                (job_id, "recovery-worker", second_token),
            )
            self.assertEqual(cursor.fetchone()[0], "cancelled")

        replay_id = uuid4()
        replay_key = f"knowledge-replay-{uuid4().hex}"
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT id, parent_job_id, replay_nonce FROM "
                "geo_v2_replay_knowledge_job(%s, %s, %s)",
                (job_id, replay_id, replay_key),
            )
            replay = cursor.fetchone()
            self.assertEqual(replay[0], replay_id)
            self.assertEqual(replay[1], job_id)
            self.assertEqual(replay[2], 1)
            cursor.execute(
                "SELECT id FROM geo_v2_replay_knowledge_job(%s, %s, %s)",
                (job_id, replay_id, replay_key),
            )
            self.assertEqual(cursor.fetchone()[0], replay_id)

    def test_result_hash_required_artifact_quality_and_aggregate_completion(self) -> None:
        ids = self._create_import_job()
        self._finalize_artifact(ids["artifact_outbox_id"])
        job_id, lease_token, _ = self._claim_job(ids["job_id"], "result-worker")
        result = self._import_result(ids)
        test_ids = result.pop("_test_ids")
        result_hash = self._canonical_json_hash(result)

        with self.assertRaises(psycopg.Error) as bad_hash:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_begin_finalizing_knowledge_job("
                    "%s, %s, %s, %s, %s)",
                    (job_id, "result-worker", lease_token, _digest("wrong"), Jsonb(result)),
                )
        self.assertEqual(bad_hash.exception.sqlstate, "22023")

        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status, finalizing_result_hash FROM "
                "geo_v2_begin_finalizing_knowledge_job(%s, %s, %s, %s, %s)",
                (job_id, "result-worker", lease_token, result_hash, Jsonb(result)),
            )
            self.assertEqual(cursor.fetchone(), ("finalizing", result_hash))
        with self.assertRaises(psycopg.Error) as pending:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_complete_knowledge_job(%s, %s, %s)",
                    (job_id, "result-worker", lease_token),
                )
        self.assertEqual(pending.exception.sqlstate, "55000")

        self._finalize_artifact(UUID(test_ids["output_outbox_id"]))
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status, result_hash FROM geo_v2_complete_knowledge_job(%s, %s, %s)",
                (job_id, "result-worker", lease_token),
            )
            self.assertEqual(cursor.fetchone(), ("succeeded", result_hash))

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT run.status, stage.status, revision.source_content_hash, "
                "artifact.content_hash, governance.source_revision_id, "
                "asset.current_revision_id, asset.current_governance_version_id "
                "FROM knowledge_pipeline_runs AS run "
                "JOIN knowledge_pipeline_stages AS stage ON stage.pipeline_run_id = run.id "
                "JOIN knowledge_source_assets AS asset ON asset.id = %s "
                "JOIN knowledge_source_asset_revisions AS revision "
                "  ON revision.id = asset.current_revision_id "
                "JOIN knowledge_source_governance_versions AS governance "
                "  ON governance.id = asset.current_governance_version_id "
                "JOIN knowledge_source_revision_artifacts AS link "
                "  ON link.source_revision_id = revision.id "
                "JOIN evidence_assets AS artifact ON artifact.id = link.evidence_asset_id "
                "WHERE run.id = %s",
                (ids["source_asset_id"], ids["run_id"]),
            )
            row = cursor.fetchone()
            self.assertEqual(row[0:2], ("succeeded", "succeeded"))
            self.assertEqual(row[2], row[3])
            self.assertEqual(row[4], row[5])
            self.assertEqual(row[5], UUID(test_ids["revision_id"]))
            self.assertEqual(row[6], UUID(test_ids["governance_id"]))

    def test_hard_block_quality_cannot_be_accepted_or_completed(self) -> None:
        ids = self._create_import_job()
        self._finalize_artifact(ids["artifact_outbox_id"])
        job_id, lease_token, _ = self._claim_job(ids["job_id"], "hard-block-worker")
        result = self._import_result(ids)
        test_ids = result.pop("_test_ids")
        quality_run = result["quality_runs"][0]
        quality_run["status"] = "failed"
        finding_id = uuid4()
        result["quality_findings"] = [
            {
                "id": str(finding_id),
                "quality_run_id": quality_run["id"],
                "finding_code": "rights.source_lineage_failed",
                "message": "required source lineage did not pass",
                "finding_hash": _digest(f"hard-block-{finding_id}"),
            }
        ]
        result_hash = self._canonical_json_hash(result)
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_begin_finalizing_knowledge_job("
                "%s, %s, %s, %s, %s)",
                (job_id, "hard-block-worker", lease_token, result_hash, Jsonb(result)),
            )
            self.assertEqual(cursor.fetchone()[0], "finalizing")
        self._finalize_artifact(UUID(test_ids["output_outbox_id"]))

        with self.assertRaises(psycopg.Error) as incomplete:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_complete_knowledge_job(%s, %s, %s)",
                    (job_id, "hard-block-worker", lease_token),
                )
        self.assertEqual(incomplete.exception.sqlstate, "55000")
        with self.assertRaises(psycopg.Error) as non_overridable:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_accept_knowledge_risk(%s, %s, %s)",
                    (uuid4(), finding_id, "must not override a hard block"),
                )
        self.assertEqual(non_overridable.exception.sqlstate, "55000")

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, (SELECT count(*) FROM knowledge_risk_acceptances "
                "WHERE quality_finding_id = %s) "
                "FROM knowledge_pipeline_jobs WHERE id = %s",
                (finding_id, job_id),
            )
            self.assertEqual(cursor.fetchone(), ("finalizing", 0))

    def test_missing_required_quality_target_cannot_complete(self) -> None:
        ids = self._create_import_job()
        self._finalize_artifact(ids["artifact_outbox_id"])
        job_id, lease_token, _ = self._claim_job(ids["job_id"], "missing-quality-worker")
        result = self._import_result(ids)
        test_ids = result.pop("_test_ids")
        result["quality_runs"] = []
        result_hash = self._canonical_json_hash(result)
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_begin_finalizing_knowledge_job("
                "%s, %s, %s, %s, %s)",
                (
                    job_id,
                    "missing-quality-worker",
                    lease_token,
                    result_hash,
                    Jsonb(result),
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "finalizing")
        self._finalize_artifact(UUID(test_ids["output_outbox_id"]))
        with self.assertRaises(psycopg.Error) as incomplete:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_complete_knowledge_job(%s, %s, %s)",
                    (job_id, "missing-quality-worker", lease_token),
                )
        self.assertEqual(incomplete.exception.sqlstate, "55000")

    def test_quality_certificate_requires_every_target_and_nonempty_definition(self) -> None:
        graph = self._seed_review_graph()
        uncovered_candidate_id = uuid4()
        uncovered_quality_run_id = uuid4()
        zero_target_definition_id = uuid4()

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT geo_v2_knowledge_quality_certificate_complete(%s)",
                (graph["fact_job_id"],),
            )
            self.assertTrue(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO knowledge_fact_candidates ("
                "id, tenant_id, project_id, knowledge_job_id, subject_entity_id, "
                "subject_role, fact_type, statement, locale, confidence, "
                "submitted_for_review_by) VALUES ("
                "%s, %s, %s, %s, %s, 'primary_brand', 'product_experience', "
                "%s, 'zh-CN', 0.96, 'fact-worker')",
                (
                    uncovered_candidate_id,
                    self.tenant_id,
                    self.project_a,
                    graph["fact_job_id"],
                    self.entity_a,
                    "新增候选事实也必须拥有独立且完整的质量结论。",
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_fact_candidate_sources ("
                "tenant_id, project_id, fact_candidate_id, chunk_id, locator, "
                "source_snapshot_hash) VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    self.tenant_id,
                    self.project_a,
                    uncovered_candidate_id,
                    graph["chunk_id"],
                    Jsonb({"chunk_index": 0}),
                    graph["chunk_hash"],
                ),
            )

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT geo_v2_knowledge_quality_certificate_complete(%s)",
                (graph["fact_job_id"],),
            )
            self.assertFalse(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO knowledge_quality_runs ("
                "id, tenant_id, project_id, knowledge_job_id, quality_definition_id, "
                "target_kind, fact_candidate_id, status, result_hash) VALUES ("
                "%s, %s, %s, %s, %s, 'fact_candidate', %s, 'passed', %s)",
                (
                    uncovered_quality_run_id,
                    self.tenant_id,
                    self.project_a,
                    graph["fact_job_id"],
                    graph["quality_definition_id"],
                    uncovered_candidate_id,
                    _digest(f"candidate-quality-{uncovered_candidate_id}"),
                ),
            )

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT geo_v2_knowledge_quality_certificate_complete(%s)",
                (graph["fact_job_id"],),
            )
            self.assertTrue(cursor.fetchone()[0])
            cursor.execute(
                "INSERT INTO knowledge_quality_definitions ("
                "id, tenant_id, project_id, definition_key, version, job_type, "
                "target_kind, severity_on_failure, rule_contract, policy_class, "
                "required, active, created_by) VALUES ("
                "%s, %s, %s, %s, 1, 'fact_extract', 'parser_run', "
                "'hard_block', %s, 'traceability', true, true, 'system-fixture')",
                (
                    zero_target_definition_id,
                    self.tenant_id,
                    self.project_a,
                    f"zero-target-{uuid4().hex}",
                    Jsonb(
                        {
                            "policy_class": "traceability",
                            "rule": "a required definition must resolve at least one target",
                        }
                    ),
                ),
            )
            cursor.execute(
                "INSERT INTO knowledge_job_quality_definitions ("
                "tenant_id, project_id, knowledge_job_id, quality_definition_id) "
                "VALUES (%s, %s, %s, %s)",
                (
                    self.tenant_id,
                    self.project_a,
                    graph["fact_job_id"],
                    zero_target_definition_id,
                ),
            )

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT geo_v2_knowledge_quality_certificate_complete(%s)",
                (graph["fact_job_id"],),
            )
            self.assertFalse(cursor.fetchone()[0])

    def test_cross_job_child_pollution_rolls_back_the_entire_result(self) -> None:
        ids = self._create_import_job()
        self._finalize_artifact(ids["artifact_outbox_id"])
        job_id, lease_token, _ = self._claim_job(ids["job_id"], "pollution-worker")
        result = self._import_result(ids)
        result.pop("_test_ids")
        result["source_artifact_links"].append(
            {
                "id": str(uuid4()),
                "evidence_asset_id": str(ids["artifact_id"]),
                "artifact_role": "foreign_input_artifact",
            }
        )
        result_hash = self._canonical_json_hash(result)
        with self.assertRaises(psycopg.Error) as polluted:
            with self._worker_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_begin_finalizing_knowledge_job("
                    "%s, %s, %s, %s, %s)",
                    (job_id, "pollution-worker", lease_token, result_hash, Jsonb(result)),
                )
        self.assertEqual(polluted.exception.sqlstate, "23514")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, "
                "(SELECT count(*) FROM knowledge_source_asset_revisions "
                " WHERE knowledge_job_id = %s), "
                "(SELECT count(*) FROM knowledge_job_artifacts "
                " WHERE knowledge_job_id = %s) "
                "FROM knowledge_pipeline_jobs WHERE id = %s",
                (job_id, job_id, job_id),
            )
            self.assertEqual(cursor.fetchone(), ("running", 0, 0))

    def test_failed_input_artifact_reconciles_the_job_and_pipeline(self) -> None:
        ids = self._create_import_job()
        lease_token, _ = self._claim_target_artifact(ids["artifact_outbox_id"])
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_fail_artifact_finalize("
                "%s, %s, %s, 'object_missing', 'object did not exist', false, 0)",
                (ids["artifact_outbox_id"], "knowledge-artifact-failure", lease_token),
            )
            self.assertEqual(cursor.fetchone()[0], "failed")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE knowledge_pipeline_jobs SET next_attempt_at = "
                "clock_timestamp() + interval '1 day' "
                "WHERE project_id = %s AND job_type = 'import' AND status = 'queued' "
                "AND id <> %s",
                (self.project_a, ids["job_id"]),
            )
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT id FROM geo_v2_claim_knowledge_job(%s, 60, %s, 'import')",
                ("artifact-reconcile-worker", self.project_a),
            )
            cursor.fetchone()  # Claim is also the bounded artifact-failure reconciler.
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT job.status, job.last_error_code, run.status, stage.status, "
                "artifact.artifact_status "
                "FROM knowledge_pipeline_jobs AS job "
                "JOIN knowledge_pipeline_runs AS run ON run.id = job.pipeline_run_id "
                "JOIN knowledge_pipeline_stages AS stage ON stage.id = job.pipeline_stage_id "
                "JOIN evidence_assets AS artifact ON artifact.id = %s "
                "WHERE job.id = %s",
                (ids["artifact_id"], ids["job_id"]),
            )
            self.assertEqual(
                cursor.fetchone(),
                ("failed", "artifact_finalize_failed", "failed", "failed", "failed"),
            )

    def test_failed_output_artifact_reconciles_a_finalizing_job(self) -> None:
        ids = self._create_import_job()
        self._finalize_artifact(ids["artifact_outbox_id"])
        job_id, job_lease, _ = self._claim_job(ids["job_id"], "output-failure-worker")
        result = self._import_result(ids)
        test_ids = result.pop("_test_ids")
        result_hash = self._canonical_json_hash(result)
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_begin_finalizing_knowledge_job("
                "%s, %s, %s, %s, %s)",
                (
                    job_id,
                    "output-failure-worker",
                    job_lease,
                    result_hash,
                    Jsonb(result),
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "finalizing")
        outbox_id = UUID(test_ids["output_outbox_id"])
        artifact_lease, _ = self._claim_target_artifact(outbox_id)
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_fail_artifact_finalize("
                "%s, %s, %s, 'hash_unavailable', 'output could not be verified', "
                "false, 0)",
                (outbox_id, "knowledge-artifact-failure", artifact_lease),
            )
            self.assertEqual(cursor.fetchone()[0], "failed")
            cursor.execute(
                "SELECT id FROM geo_v2_claim_knowledge_job(%s, 60, %s, 'import')",
                ("output-reconcile-worker", self.project_a),
            )
            cursor.fetchone()
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT job.status, job.last_error_code, run.status, stage.status, "
                "artifact.artifact_status "
                "FROM knowledge_pipeline_jobs AS job "
                "JOIN knowledge_pipeline_runs AS run ON run.id = job.pipeline_run_id "
                "JOIN knowledge_pipeline_stages AS stage ON stage.id = job.pipeline_stage_id "
                "JOIN evidence_assets AS artifact ON artifact.id = %s "
                "WHERE job.id = %s",
                (UUID(test_ids["output_artifact_id"]), job_id),
            )
            self.assertEqual(
                cursor.fetchone(),
                ("failed", "artifact_finalize_failed", "failed", "failed", "failed"),
            )

    def test_finalized_content_addressed_artifact_is_reused_without_new_outbox(self) -> None:
        first = self._create_import_job()
        self._finalize_artifact(first["artifact_outbox_id"])
        first_job, first_lease, _ = self._claim_job(first["job_id"], "reuse-worker-1")
        first_result = self._import_result(first)
        first_test_ids = first_result.pop("_test_ids")
        first_hash = self._canonical_json_hash(first_result)
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_begin_finalizing_knowledge_job("
                "%s, %s, %s, %s, %s)",
                (first_job, "reuse-worker-1", first_lease, first_hash, Jsonb(first_result)),
            )
        self._finalize_artifact(UUID(first_test_ids["output_outbox_id"]))
        with self._worker_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_complete_knowledge_job(%s, %s, %s)",
                (first_job, "reuse-worker-1", first_lease),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")

        second = self._create_import_job()
        self._finalize_artifact(second["artifact_outbox_id"])
        second_job, second_lease, _ = self._claim_job(second["job_id"], "reuse-worker-2")
        second_result = self._import_result(second)
        second_test_ids = second_result.pop("_test_ids")
        requested_second_artifact_id = UUID(second_test_ids["output_artifact_id"])
        requested_second_outbox_id = UUID(second_test_ids["output_outbox_id"])
        reusable_fields = (
            "asset_type",
            "storage_uri",
            "storage_key",
            "content_hash",
            "size_bytes",
            "content_type",
            "artifact_role",
        )
        for field in reusable_fields:
            second_result["artifacts"][0][field] = first_result["artifacts"][0][field]
        second_hash = self._canonical_json_hash(second_result)
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM evidence_assets WHERE project_id = %s "
                "AND content_hash = %s AND asset_type = %s",
                (
                    self.project_a,
                    first_result["artifacts"][0]["content_hash"],
                    first_result["artifacts"][0]["asset_type"],
                ),
            )
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute(
                "SELECT count(*) FROM artifact_finalize_outbox WHERE evidence_asset_id = %s",
                (UUID(first_test_ids["output_artifact_id"]),),
            )
            outbox_count_before = cursor.fetchone()[0]

        with self._worker_transaction() as cursor:
            for _ in range(2):
                cursor.execute(
                    "SELECT status FROM geo_v2_begin_finalizing_knowledge_job("
                    "%s, %s, %s, %s, %s)",
                    (
                        second_job,
                        "reuse-worker-2",
                        second_lease,
                        second_hash,
                        Jsonb(second_result),
                    ),
                )
                self.assertEqual(cursor.fetchone()[0], "finalizing")
            cursor.execute(
                "SELECT status FROM geo_v2_complete_knowledge_job(%s, %s, %s)",
                (second_job, "reuse-worker-2", second_lease),
            )
            self.assertEqual(cursor.fetchone()[0], "succeeded")

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*), bool_and(artifact_status = 'finalized') "
                "FROM evidence_assets WHERE project_id = %s AND content_hash = %s "
                "AND asset_type = %s",
                (
                    self.project_a,
                    first_result["artifacts"][0]["content_hash"],
                    first_result["artifacts"][0]["asset_type"],
                ),
            )
            self.assertEqual(cursor.fetchone(), (1, True))
            cursor.execute(
                "SELECT count(*) FROM artifact_finalize_outbox WHERE evidence_asset_id = %s",
                (UUID(first_test_ids["output_artifact_id"]),),
            )
            self.assertEqual(cursor.fetchone()[0], outbox_count_before)
            cursor.execute(
                "SELECT (SELECT count(*) FROM evidence_assets WHERE id = %s), "
                "(SELECT count(*) FROM artifact_finalize_outbox WHERE id = %s), "
                "(SELECT count(*) FROM knowledge_job_artifacts "
                " WHERE knowledge_job_id = %s AND evidence_asset_id = %s), "
                "(SELECT count(*) FROM knowledge_job_artifacts "
                " WHERE knowledge_job_id = %s AND evidence_asset_id = %s)",
                (
                    requested_second_artifact_id,
                    requested_second_outbox_id,
                    first_job,
                    UUID(first_test_ids["output_artifact_id"]),
                    second_job,
                    UUID(first_test_ids["output_artifact_id"]),
                ),
            )
            self.assertEqual(cursor.fetchone(), (0, 0, 1, 1))

    def test_review_fact_versions_and_governance_revocation_are_fail_closed(self) -> None:
        graph = self._seed_review_graph()
        fact_id = uuid4()
        fact_v1_id = uuid4()
        review_v1_id = uuid4()

        with self.assertRaises(psycopg.Error) as producer_not_done:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT status FROM geo_v2_review_knowledge_fact_candidate("
                    "%s, %s, %s, %s, 'approved', %s, NULL, NULL)",
                    (
                        graph["valid_candidate_id"],
                        review_v1_id,
                        fact_id,
                        fact_v1_id,
                        "producer is still running",
                    ),
                )
        self.assertEqual(producer_not_done.exception.sqlstate, "55000")

        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE knowledge_pipeline_jobs SET status = 'succeeded', "
                "finalizing_result_hash = %s, result_hash = %s, lease_owner = NULL, "
                "lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL, "
                "completed_at = clock_timestamp(), completed_by = 'fact-worker', "
                "updated_at = clock_timestamp() WHERE id = %s",
                (graph["result_hash"], graph["result_hash"], graph["fact_job_id"]),
            )

        with self.assertRaises(psycopg.Error) as maker_checker:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT status FROM geo_v2_review_knowledge_fact_candidate("
                    "%s, %s, NULL, NULL, 'rejected', %s, NULL, NULL)",
                    (
                        graph["maker_candidate_id"],
                        uuid4(),
                        "maker cannot review own candidate",
                    ),
                )
        self.assertEqual(maker_checker.exception.sqlstate, "42501")

        review_args = (
            graph["valid_candidate_id"],
            review_v1_id,
            fact_id,
            fact_v1_id,
            "approved with exact governed lineage",
        )
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_review_knowledge_fact_candidate("
                "%s, %s, %s, %s, 'approved', %s, NULL, NULL)",
                review_args,
            )
            self.assertEqual(cursor.fetchone()[0], "approved")
            cursor.execute(
                "SELECT status FROM geo_v2_review_knowledge_fact_candidate("
                "%s, %s, %s, %s, 'approved', %s, NULL, NULL)",
                review_args,
            )
            self.assertEqual(cursor.fetchone()[0], "approved")
            cursor.execute(
                "SELECT fact_id, fact_version_id FROM "
                "geo_v2_read_approved_knowledge(%s, NULL)",
                (self.project_a,),
            )
            self.assertIn((fact_id, fact_v1_id), cursor.fetchall())

        with self.assertRaises(psycopg.Error) as review_conflict:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT status FROM geo_v2_review_knowledge_fact_candidate("
                    "%s, %s, %s, %s, 'approved', %s, NULL, NULL)",
                    (
                        graph["valid_candidate_id"],
                        uuid4(),
                        fact_id,
                        fact_v1_id,
                        "different command identity",
                    ),
                )
        self.assertEqual(review_conflict.exception.sqlstate, "23505")

        candidate_v2_id = self._append_review_candidate(
            graph,
            statement="该品牌产品在真实消费者描述的场景中持续表现稳定。",
        )
        fact_v2_id = uuid4()
        review_v2_id = uuid4()
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT statement_hash FROM knowledge_fact_versions WHERE id = %s",
                (fact_v1_id,),
            )
            v1_statement_hash = cursor.fetchone()[0]
        with self.assertRaises(psycopg.Error) as stale_base:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT status FROM geo_v2_review_knowledge_fact_candidate("
                    "%s, %s, %s, %s, 'approved', %s, %s, %s)",
                    (
                        candidate_v2_id,
                        review_v2_id,
                        fact_id,
                        fact_v2_id,
                        "stale base must fail",
                        fact_v1_id,
                        _digest("wrong-base"),
                    ),
                )
        self.assertEqual(stale_base.exception.sqlstate, "40001")
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_review_knowledge_fact_candidate("
                "%s, %s, %s, %s, 'approved', %s, %s, %s)",
                (
                    candidate_v2_id,
                    review_v2_id,
                    fact_id,
                    fact_v2_id,
                    "exact base creates immutable v2",
                    fact_v1_id,
                    v1_statement_hash,
                ),
            )
            self.assertEqual(cursor.fetchone()[0], "approved")
            cursor.execute(
                "SELECT fact_version_id FROM geo_v2_read_approved_knowledge(%s, NULL) "
                "WHERE fact_id = %s",
                (self.project_a, fact_id),
            )
            self.assertEqual(cursor.fetchone()[0], fact_v2_id)
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT fact.current_version_id, version_row.base_version_id, "
                "version_row.base_statement_hash, version_row.version_number "
                "FROM knowledge_facts AS fact JOIN knowledge_fact_versions AS version_row "
                "ON version_row.id = fact.current_version_id WHERE fact.id = %s",
                (fact_id,),
            )
            self.assertEqual(
                cursor.fetchone(),
                (fact_v2_id, fact_v1_id, v1_statement_hash, 2),
            )

        with self._runtime_transaction(self.content_session_hash) as cursor:
            cursor.execute(
                "SELECT fact_version_id FROM geo_v2_read_approved_knowledge(%s, NULL) "
                "WHERE fact_id = %s",
                (self.project_a, fact_id),
            )
            self.assertEqual(cursor.fetchone()[0], fact_v2_id)
        with self.assertRaises(psycopg.Error) as client_requires_channel:
            with self._runtime_transaction(self.client_session_hash) as cursor:
                cursor.execute(
                    "SELECT fact_id FROM geo_v2_read_approved_knowledge(%s, NULL)",
                    (self.project_a,),
                )
        self.assertEqual(client_requires_channel.exception.sqlstate, "22023")
        with self._runtime_transaction(self.client_session_hash) as cursor:
            cursor.execute(
                "SELECT fact_version_id, customer_visible, "
                "public_disclosure_allowed, public_source_url "
                "FROM geo_v2_read_approved_knowledge(%s, 'website') "
                "WHERE fact_id = %s",
                (self.project_a, fact_id),
            )
            client_row = cursor.fetchone()
            self.assertEqual(client_row[0], fact_v2_id)
            self.assertEqual(client_row[1:3], (True, True))
            self.assertTrue(client_row[3].startswith("https://example.test/source/"))
            cursor.execute(
                "SELECT count(*) FROM geo_v2_read_approved_knowledge(%s, 'email') "
                "WHERE fact_id = %s",
                (self.project_a, fact_id),
            )
            self.assertEqual(cursor.fetchone()[0], 0)

        with self.assertRaises(psycopg.Error) as stale_governance:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_create_knowledge_governance_version("
                    "%s, %s, %s, %s, %s)",
                    (
                        graph["source_asset_id"],
                        uuid4(),
                        uuid4(),
                        Jsonb({"policy_version": "revoked-v2"}),
                        "stale governance head",
                    ),
                )
        self.assertEqual(stale_governance.exception.sqlstate, "40001")

        governance_v2_id = uuid4()
        revoked_governance = {
            "authority_grade": "A",
            "usage_rights_status": "internal_only",
            "authorization_basis": "publication rights revoked",
            "confidentiality": "internal",
            "consent_status": "granted",
            "external_model_use_allowed": False,
            "public_adaptation_allowed": False,
            "customer_visible": False,
            "public_disclosure_allowed": False,
            "quotation_allowed": False,
            "attribution_required": False,
            "claim_risk": "low",
            "policy_version": "governance-revoked-v2",
            "allowed_channels": [
                {"publication_channel": "website", "allowed": False}
            ],
        }
        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT id FROM geo_v2_create_knowledge_governance_version("
                "%s, %s, %s, %s, %s)",
                (
                    graph["source_asset_id"],
                    governance_v2_id,
                    graph["governance_id"],
                    Jsonb(revoked_governance),
                    "source rights were revoked",
                ),
            )
            self.assertEqual(cursor.fetchone()[0], governance_v2_id)
            cursor.execute(
                "SELECT count(*) FROM geo_v2_read_approved_knowledge(%s, 'website') "
                "WHERE fact_id = %s",
                (self.project_a, fact_id),
            )
            self.assertEqual(cursor.fetchone()[0], 0)

        with self._runtime_transaction(self.content_session_hash) as cursor:
            cursor.execute(
                "SELECT count(*) FROM geo_v2_read_approved_knowledge(%s, NULL) "
                "WHERE fact_id = %s",
                (self.project_a, fact_id),
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        with self._runtime_transaction(self.client_session_hash) as cursor:
            cursor.execute(
                "SELECT count(*) FROM geo_v2_read_approved_knowledge(%s, 'website') "
                "WHERE fact_id = %s",
                (self.project_a, fact_id),
            )
            self.assertEqual(cursor.fetchone()[0], 0)

        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_set_knowledge_source_status(%s, 'disabled', %s)",
                (graph["source_asset_id"], "source is no longer approved"),
            )
            self.assertEqual(cursor.fetchone()[0], "disabled")
            cursor.execute(
                "SELECT status FROM geo_v2_withdraw_knowledge_fact(%s, %s)",
                (fact_id, "fact invalidated after source withdrawal"),
            )
            self.assertEqual(cursor.fetchone()[0], "withdrawn")
            cursor.execute(
                "SELECT count(*) FROM geo_v2_read_approved_knowledge(%s, NULL) "
                "WHERE fact_id = %s",
                (self.project_a, fact_id),
            )
            self.assertEqual(cursor.fetchone()[0], 0)

        with self._runtime_transaction() as cursor:
            cursor.execute(
                "SELECT status FROM geo_v2_set_knowledge_source_status(%s, 'archived', %s)",
                (graph["source_asset_id"], "source retention lifecycle completed"),
            )
            self.assertEqual(cursor.fetchone()[0], "archived")
        with self.assertRaises(psycopg.Error) as archived_is_terminal:
            with self._runtime_transaction() as cursor:
                cursor.execute(
                    "SELECT id FROM geo_v2_create_knowledge_governance_version("
                    "%s, %s, %s, %s, %s)",
                    (
                        graph["source_asset_id"],
                        uuid4(),
                        governance_v2_id,
                        Jsonb(revoked_governance),
                        "archived source must not be reactivated",
                    ),
                )
        self.assertEqual(archived_is_terminal.exception.sqlstate, "55000")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT asset.status, asset.current_governance_version_id, count(version.id) "
                "FROM knowledge_source_assets AS asset "
                "JOIN knowledge_source_governance_versions AS version "
                "ON version.source_asset_id = asset.id AND version.project_id = asset.project_id "
                "WHERE asset.id = %s GROUP BY asset.status, "
                "asset.current_governance_version_id",
                (graph["source_asset_id"],),
            )
            self.assertEqual(cursor.fetchone(), ("archived", governance_v2_id, 2))

    def test_concurrent_create_returns_one_job_and_one_dispatch(self) -> None:
        suffix = uuid4().hex
        job_id = uuid4()
        run_id = uuid4()
        stage_id = uuid4()
        source_id = uuid4()
        snapshot = self._import_snapshot(
            source_asset_id=uuid4(),
            artifact_id=uuid4(),
            artifact_outbox_id=uuid4(),
            suffix=suffix,
        )
        barrier = threading.Barrier(2)
        outcomes: list[UUID] = []
        errors: list[BaseException] = []

        def create() -> None:
            try:
                barrier.wait(timeout=5)
                with self._runtime_transaction() as cursor:
                    cursor.execute(
                        "SELECT id FROM geo_v2_create_knowledge_job("
                        "%s, %s, %s, %s, %s, 'import', %s, %s, NULL)",
                        (
                            job_id,
                            self.project_a,
                            run_id,
                            stage_id,
                            source_id,
                            f"knowledge-concurrent-{suffix}",
                            Jsonb(snapshot),
                        ),
                    )
                    outcomes.append(cursor.fetchone()[0])
            except BaseException as error:  # pragma: no cover - asserted below
                errors.append(error)

        threads = [threading.Thread(target=create) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(errors)
        self.assertEqual(outcomes, [job_id, job_id])
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT (SELECT count(*) FROM knowledge_pipeline_jobs WHERE id = %s), "
                "(SELECT count(*) FROM durable_job_dispatch_outbox WHERE job_id = %s), "
                "(SELECT count(*) FROM knowledge_job_input_snapshots "
                " WHERE knowledge_job_id = %s)",
                (job_id, job_id, job_id),
            )
            self.assertEqual(cursor.fetchone(), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
