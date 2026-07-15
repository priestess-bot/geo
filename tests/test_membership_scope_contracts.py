from __future__ import annotations

import unittest
from datetime import UTC, datetime

from geo_core.models import RuntimeMembershipScope, RuntimeTenantMemberInput
from geo_core.repository import PostgresEvidenceRepository


class RecordingCursor:
    def __init__(self, calls: list[tuple[str, tuple[object, ...]]], result_sets: list[object]) -> None:
        self.calls = calls
        self.result_sets = result_sets

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self) -> object:
        result = self.result_sets.pop(0)
        if isinstance(result, list):
            return result[0] if result else None
        return result

    def fetchall(self) -> object:
        result = self.result_sets.pop(0)
        return result


class RecordingConnection:
    def __init__(self, result_sets: list[object] | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commit_count = 0
        self.result_sets = result_sets or []

    def cursor(self) -> RecordingCursor:
        return RecordingCursor(self.calls, self.result_sets)

    def commit(self) -> None:
        self.commit_count += 1


class MembershipScopeContractTests(unittest.TestCase):
    def test_save_tenant_member_upserts_lowercase_member_and_writes_audit(self) -> None:
        tenant_id = "b926f81f-037c-5f93-aeef-9397f9c5724b"
        member_id = "06bff80a-a1ef-5dcc-9f60-f9956b1ea5e8"
        now = datetime(2026, 7, 5, tzinfo=UTC)
        connection = RecordingConnection(
            result_sets=[
                None,
                {
                    "id": member_id,
                    "tenant_id": tenant_id,
                    "user_id": "owner@example.com",
                    "role": "tenant_admin",
                    "status": "active",
                    "invited_by": "root@example.com",
                    "created_at": now,
                    "updated_at": now,
                },
            ]
        )

        record = PostgresEvidenceRepository(connection).save_tenant_member(
            RuntimeTenantMemberInput(
                tenant_id=tenant_id,
                user_id="OWNER@EXAMPLE.COM",
                role="Tenant Admin",
                updated_by="root@example.com",
            )
        )

        self.assertEqual(record["user_id"], "owner@example.com")
        self.assertEqual(record["role"], "tenant_admin")
        self.assertEqual(record["status"], "active")
        self.assertEqual(connection.commit_count, 1)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("INSERT INTO tenant_members", executed_sql)
        self.assertIn("ON CONFLICT (tenant_id, user_id) DO UPDATE", executed_sql)
        self.assertIn("INSERT INTO audit_events", executed_sql)
        self.assertEqual(connection.calls[1][1][1], tenant_id)
        self.assertEqual(connection.calls[1][1][2], "owner@example.com")

    def test_get_runtime_membership_scope_combines_tenant_and_project_roles(self) -> None:
        tenant_id = "b926f81f-037c-5f93-aeef-9397f9c5724b"
        project_id = "4a6c168e-c596-56a8-932a-3271e2ef16f0"
        connection = RecordingConnection(
            result_sets=[
                [{"tenant_id": tenant_id, "role": "tenant_admin"}],
                [{"project_id": project_id, "role": "analyst", "tenant_id": tenant_id}],
            ]
        )

        scope = PostgresEvidenceRepository(connection).get_runtime_membership_scope(
            actor_id="ANALYST@EXAMPLE.COM",
            tenant_id=tenant_id,
            project_id=project_id,
        )

        self.assertIsInstance(scope, RuntimeMembershipScope)
        self.assertEqual(scope.actor_id, "analyst@example.com")
        self.assertEqual(scope.tenant_id, tenant_id)
        self.assertEqual(scope.tenant_roles, ("tenant_admin",))
        self.assertEqual(scope.project_ids, (project_id,))
        self.assertEqual(scope.project_roles, {project_id: "analyst"})
        self.assertIn("project.update", scope.permissions)
        self.assertIn("collection.run", scope.permissions)
        self.assertIn("analysis.review", scope.permissions)
        executed_sql = "\n".join(sql for sql, _ in connection.calls)
        self.assertIn("FROM tenant_members tm", executed_sql)
        self.assertIn("JOIN projects p ON p.id = pm.project_id", executed_sql)
        self.assertEqual(connection.calls[0][1], ("analyst@example.com", tenant_id))
        self.assertEqual(connection.calls[1][1], ("analyst@example.com", tenant_id, project_id))

    def test_project_filter_without_membership_is_denied(self) -> None:
        connection = RecordingConnection(result_sets=[[], []])

        with self.assertRaises(PermissionError):
            PostgresEvidenceRepository(connection).get_runtime_membership_scope(
                actor_id="viewer@example.com",
                tenant_id="b926f81f-037c-5f93-aeef-9397f9c5724b",
                project_id="4a6c168e-c596-56a8-932a-3271e2ef16f0",
            )

    def test_tenant_scope_without_membership_is_denied(self) -> None:
        connection = RecordingConnection(result_sets=[[], []])

        with self.assertRaises(PermissionError):
            PostgresEvidenceRepository(connection).get_runtime_membership_scope(
                actor_id="viewer@example.com",
                tenant_id="b926f81f-037c-5f93-aeef-9397f9c5724b",
            )


if __name__ == "__main__":
    unittest.main()
