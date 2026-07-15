from __future__ import annotations

import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@unittest.skipUnless(os.getenv("SCHEMA_V2_BEHAVIOR_TEST") == "1", "SCHEMA_V2_BEHAVIOR_TEST=1 is required")
class SchemaV2ReportsPostgresTest(unittest.TestCase):
    tenant_id: UUID
    project_a: UUID
    project_b: UUID
    report_a: UUID
    report_b: UUID

    @classmethod
    def setUpClass(cls) -> None:
        marker = uuid4().hex
        cls.tenant_id = uuid4()
        cls.project_a = uuid4()
        cls.project_b = uuid4()
        cls.report_a = uuid4()
        cls.report_b = uuid4()
        market_code = f"R-{marker}"
        industry_code = f"reports-{marker}"
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO market_profiles (market_code, payload) VALUES (%s, %s)", (market_code, Jsonb({"fixture": "reports"})))
            cursor.execute("INSERT INTO industry_profiles (market_code, industry_code, payload) VALUES (%s, %s, %s)", (market_code, industry_code, Jsonb({"fixture": "reports"})))
            cursor.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)", (cls.tenant_id, f"Reports {marker}", f"reports-{marker}"))
            for project_id, name in ((cls.project_a, "Reports A"), (cls.project_b, "Reports B")):
                cursor.execute(
                    "INSERT INTO projects (id, tenant_id, name, market_code, industry_code, target_brand, category, prompt_version, status) "
                    "VALUES (%s, %s, %s, %s, %s, 'Reports Brand', 'GEO', 'v1', 'active')",
                    (project_id, cls.tenant_id, name, market_code, industry_code),
                )
            for report_id, project_id in ((cls.report_a, cls.project_a), (cls.report_b, cls.project_b)):
                cursor.execute(
                    "INSERT INTO reports (id, tenant_id, project_id, report_kind, created_by) "
                    "VALUES (%s, %s, %s, 'geo_visibility', 'report-fixture')",
                    (report_id, cls.tenant_id, project_id),
                )
            connection.commit()

    def _create_report_job(self, key: str) -> UUID:
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO report_generation_jobs (tenant_id, project_id, report_id, requested_version_number, idempotency_key, input_snapshot, input_snapshot_hash, requested_by) "
                "VALUES (%s, %s, %s, 1, %s, %s, %s, 'report-fixture') RETURNING id",
                (self.tenant_id, self.project_a, self.report_a, key, Jsonb({"fixture": key}), _digest(f'{{"fixture": "{key}"}}')),
            )
            job_id = cursor.fetchone()[0]
            connection.commit()
            return job_id

    def test_report_job_reclaims_expired_lease_and_fences_result_writes(self) -> None:
        job_id = self._create_report_job(f"report-lease-{uuid4().hex}")
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, lease_token FROM geo_v2_claim_report_generation_job('worker-a', 5, %s)", (self.project_a,))
            claimed_id, stale_token = cursor.fetchone()
            self.assertEqual(claimed_id, job_id)
            cursor.execute("UPDATE report_generation_jobs SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = %s", (job_id,))
            cursor.execute("SELECT id, lease_token, attempt_count FROM geo_v2_claim_report_generation_job('worker-b', 30, %s)", (self.project_a,))
            reclaimed_id, active_token, attempts = cursor.fetchone()
            self.assertEqual(reclaimed_id, job_id)
            self.assertNotEqual(stale_token, active_token)
            self.assertEqual(attempts, 2)
            connection.commit()
            with self.assertRaises(psycopg.Error):
                cursor.execute(
                    "SELECT geo_v2_persist_report_generation_result(%s, 'worker-a', %s, 'Blocked', 'en-AU', 'stale result', %s, %s)",
                    (job_id, stale_token, _digest("stale"), _digest("method")),
                )
            connection.rollback()
            cursor.execute(
                "SELECT (geo_v2_persist_report_generation_result(%s, 'worker-b', %s, 'Report', 'en-AU', 'fresh result', %s, %s)).id",
                (job_id, active_token, _digest("fresh"), _digest("method")),
            )
            version_id = cursor.fetchone()[0]
            connection.commit()
            with self.assertRaises(psycopg.Error):
                cursor.execute("SELECT geo_v2_complete_report_generation_job(%s, 'worker-a', %s, %s)", (job_id, stale_token, version_id))
            connection.rollback()
            cursor.execute("SELECT (geo_v2_complete_report_generation_job(%s, 'worker-b', %s, %s)).status", (job_id, active_token, version_id))
            self.assertEqual(cursor.fetchone()[0], "succeeded")
            connection.commit()

    def test_notification_delivery_reclaims_expired_lease_and_fences_completion(self) -> None:
        with psycopg.connect() as connection, connection.cursor() as cursor:
            recipient_id = uuid4()
            notification_id = uuid4()
            cursor.execute("INSERT INTO notification_recipients (id, tenant_id, project_id, recipient_kind, actor_id, created_by) VALUES (%s, %s, %s, 'project_member', 'recipient', 'fixture')", (recipient_id, self.tenant_id, self.project_a))
            cursor.execute("INSERT INTO notifications (id, tenant_id, project_id, event_type, title, body, target_type, payload_hash, created_by) VALUES (%s, %s, %s, 'report.ready', 'Ready', 'Report ready', 'report', %s, 'fixture')", (notification_id, self.tenant_id, self.project_a, _digest("notification")))
            cursor.execute("INSERT INTO notification_deliveries (tenant_id, project_id, notification_id, recipient_id) VALUES (%s, %s, %s, %s) RETURNING id", (self.tenant_id, self.project_a, notification_id, recipient_id))
            delivery_id = cursor.fetchone()[0]
            cursor.execute("SELECT id, lease_token FROM geo_v2_claim_notification_delivery('worker-a', 5, %s)", (self.project_a,))
            self.assertEqual(cursor.fetchone()[0], delivery_id)
            cursor.execute("SELECT lease_token FROM notification_deliveries WHERE id = %s", (delivery_id,))
            stale_token = cursor.fetchone()[0]
            cursor.execute("UPDATE notification_deliveries SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = %s", (delivery_id,))
            cursor.execute("SELECT id, lease_token FROM geo_v2_claim_notification_delivery('worker-b', 30, %s)", (self.project_a,))
            _, active_token = cursor.fetchone()
            connection.commit()
            with self.assertRaises(psycopg.Error):
                cursor.execute("SELECT geo_v2_complete_notification_delivery(%s, 'worker-a', %s, %s)", (delivery_id, stale_token, _digest("stale")))
            connection.rollback()
            cursor.execute("SELECT (geo_v2_complete_notification_delivery(%s, 'worker-b', %s, %s)).status", (delivery_id, active_token, _digest("delivered")))
            self.assertEqual(cursor.fetchone()[0], "delivered")
            connection.commit()

    def test_cross_project_report_lineage_is_rejected(self) -> None:
        with psycopg.connect() as connection, connection.cursor() as cursor:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    "INSERT INTO report_versions (tenant_id, project_id, report_id, version_number, title, rendered_markdown, content_hash, methodology_hash, input_snapshot_hash, created_by) "
                    "VALUES (%s, %s, %s, 99, 'Wrong project', 'content', %s, %s, %s, 'fixture')",
                    (self.tenant_id, self.project_b, self.report_a, _digest("c"), _digest("m"), _digest("i")),
                )
            connection.rollback()

    def test_report_and_notification_database_contract_is_installed(self) -> None:
        with psycopg.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT relname, relforcerowsecurity FROM pg_class WHERE relname = ANY(%s) ORDER BY relname", (["report_exports", "report_generation_jobs", "notification_deliveries"],))
            self.assertEqual(cursor.fetchall(), [("notification_deliveries", True), ("report_exports", True), ("report_generation_jobs", True)])
            cursor.execute("SELECT proname FROM pg_proc WHERE proname = ANY(%s) ORDER BY proname", (["geo_v2_claim_report_generation_job", "geo_v2_persist_report_generation_result", "geo_v2_read_portal_reports"],))
            self.assertEqual(cursor.fetchall(), [("geo_v2_claim_report_generation_job",), ("geo_v2_persist_report_generation_result",), ("geo_v2_read_portal_reports",)])


if __name__ == "__main__":
    unittest.main()
