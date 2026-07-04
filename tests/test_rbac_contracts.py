from __future__ import annotations

import unittest

from geno_core.rbac import (
    ANALYST_ROLE,
    CLIENT_VIEWER_ROLE,
    CONTENT_OPERATOR_ROLE,
    KNOWLEDGE_ARCHITECT_ROLE,
    PERMISSION_VOCABULARY,
    PROJECT_OWNER_ROLE,
    REVIEWER_ROLE,
    ROLE_PERMISSION_CONDITIONS,
    ROLE_PERMISSION_MATRIX,
    SUPER_ADMIN_ROLE,
    TENANT_ADMIN_ROLE,
    UnknownPermissionError,
    UnknownRoleError,
    is_permission_declared,
    normalize_role,
    permission_conditions,
    permissions_for_roles,
    role_has_permission,
    roles_have_permission,
    validate_permission_matrix,
)


class RbacContractTests(unittest.TestCase):
    def test_permission_vocabulary_contains_production_v1_required_permissions(self) -> None:
        required = {
            "report.read",
            "report.download",
            "action.manage",
            "action.read",
            "retest.run",
            "retest.read",
            "knowledge.read",
            "knowledge.read_approved",
            "content.read",
            "content.update",
            "distribution.read",
            "connector.secret.manage",
            "audit.read",
        }

        self.assertTrue(required.issubset(set(PERMISSION_VOCABULARY)))

    def test_role_matrix_only_references_declared_permissions(self) -> None:
        validate_permission_matrix()
        vocabulary = set(PERMISSION_VOCABULARY)

        for role, permissions in ROLE_PERMISSION_MATRIX.items():
            with self.subTest(role=role):
                self.assertTrue(set(permissions).issubset(vocabulary))

    def test_legacy_project_roles_normalize_to_production_roles(self) -> None:
        self.assertEqual(normalize_role("owner"), PROJECT_OWNER_ROLE)
        self.assertEqual(normalize_role("admin"), PROJECT_OWNER_ROLE)
        self.assertEqual(normalize_role("viewer"), CLIENT_VIEWER_ROLE)
        self.assertEqual(normalize_role("Tenant Admin"), TENANT_ADMIN_ROLE)

    def test_unknown_role_or_permission_is_denied_by_contract(self) -> None:
        with self.assertRaises(UnknownRoleError):
            normalize_role("finance-admin")
        with self.assertRaises(UnknownPermissionError):
            role_has_permission(PROJECT_OWNER_ROLE, "provider.key.read")
        self.assertFalse(is_permission_declared("provider.key.read"))

    def test_super_admin_has_every_declared_permission(self) -> None:
        self.assertEqual(ROLE_PERMISSION_MATRIX[SUPER_ADMIN_ROLE], frozenset(PERMISSION_VOCABULARY))

    def test_project_owner_can_manage_project_and_connector_secrets(self) -> None:
        self.assertTrue(role_has_permission("owner", "project.update"))
        self.assertTrue(role_has_permission("admin", "connector.secret.manage"))
        self.assertTrue(role_has_permission(PROJECT_OWNER_ROLE, "retest.run"))
        self.assertFalse(role_has_permission(PROJECT_OWNER_ROLE, "system.admin"))

    def test_analyst_can_collect_and_review_but_not_publish_or_manage_secrets(self) -> None:
        self.assertTrue(role_has_permission(ANALYST_ROLE, "collection.run"))
        self.assertTrue(role_has_permission(ANALYST_ROLE, "analysis.review"))
        self.assertTrue(role_has_permission(ANALYST_ROLE, "evidence.read_raw"))
        self.assertFalse(role_has_permission(ANALYST_ROLE, "report.publish"))
        self.assertFalse(role_has_permission(ANALYST_ROLE, "connector.secret.manage"))

    def test_reviewer_can_approve_or_revoke_but_not_run_connectors(self) -> None:
        self.assertTrue(role_has_permission(REVIEWER_ROLE, "report.approve"))
        self.assertTrue(role_has_permission(REVIEWER_ROLE, "report.revoke"))
        self.assertFalse(role_has_permission(REVIEWER_ROLE, "collection.run"))
        self.assertFalse(role_has_permission(REVIEWER_ROLE, "connector.manage"))

    def test_knowledge_and_content_roles_are_scoped_to_enablement_work(self) -> None:
        self.assertTrue(role_has_permission(KNOWLEDGE_ARCHITECT_ROLE, "knowledge.import"))
        self.assertTrue(role_has_permission(CONTENT_OPERATOR_ROLE, "content.generate"))
        self.assertTrue(role_has_permission(CONTENT_OPERATOR_ROLE, "distribution.create"))
        self.assertFalse(role_has_permission(CONTENT_OPERATOR_ROLE, "report.approve"))

    def test_client_viewer_can_only_read_customer_visible_delivery_outputs(self) -> None:
        self.assertTrue(role_has_permission(CLIENT_VIEWER_ROLE, "report.read"))
        self.assertTrue(role_has_permission(CLIENT_VIEWER_ROLE, "report.download"))
        self.assertTrue(role_has_permission(CLIENT_VIEWER_ROLE, "action.read"))
        self.assertTrue(role_has_permission(CLIENT_VIEWER_ROLE, "retest.read"))
        self.assertFalse(role_has_permission(CLIENT_VIEWER_ROLE, "evidence.read_raw"))
        self.assertFalse(role_has_permission(CLIENT_VIEWER_ROLE, "connector.read"))
        self.assertFalse(role_has_permission(CLIENT_VIEWER_ROLE, "audit.read"))

    def test_customer_visibility_and_internal_conditions_are_conditions_not_permissions(self) -> None:
        self.assertNotIn("published-only", PERMISSION_VOCABULARY)
        self.assertNotIn("customer-visible", PERMISSION_VOCABULARY)
        self.assertEqual(permission_conditions(CLIENT_VIEWER_ROLE, "report.download"), ("published-only",))
        self.assertEqual(permission_conditions(CLIENT_VIEWER_ROLE, "project.read"), ("customer-visible",))
        self.assertEqual(permission_conditions(ANALYST_ROLE, "evidence.read_raw"), ("internal-only",))
        self.assertIn((CLIENT_VIEWER_ROLE, "report.download"), ROLE_PERMISSION_CONDITIONS)

    def test_multiple_roles_union_and_explicit_permissions(self) -> None:
        permissions = permissions_for_roles([ANALYST_ROLE, REVIEWER_ROLE])

        self.assertIn("collection.run", permissions)
        self.assertIn("report.approve", permissions)
        self.assertFalse(roles_have_permission([ANALYST_ROLE], "connector.secret.manage"))
        self.assertTrue(
            roles_have_permission(
                [ANALYST_ROLE],
                "connector.secret.manage",
                explicit_permissions=["connector.secret.manage"],
            )
        )


if __name__ == "__main__":
    unittest.main()
