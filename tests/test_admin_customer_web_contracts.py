from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AdminCustomerWebContractsTest(unittest.TestCase):
    def test_admin_new_project_uses_server_action_and_no_inert_buttons(self) -> None:
        form_source = (ROOT / "apps/admin-web/app/projects/new/CreateProjectForm.tsx").read_text(encoding="utf-8")
        action_source = (ROOT / "apps/admin-web/app/projects/new/actions.ts").read_text(encoding="utf-8")
        page_source = (ROOT / "apps/admin-web/app/projects/new/page.tsx").read_text(encoding="utf-8")

        self.assertIn("useActionState(createProjectAction", form_source)
        self.assertIn("POST", action_source)
        self.assertIn("/v1/projects/runtime/au/dtc-ecommerce", action_source)
        self.assertIn("customerInvitationUrl", action_source)
        self.assertIn("parseJsonObject", action_source)
        self.assertIn("3 到 5 个", form_source)
        self.assertNotIn('method="get"', page_source)
        self.assertNotIn('type="button"', form_source)
        self.assertNotIn("后续会改成", page_source)

    def test_admin_project_detail_wires_customer_access_runtime_actions(self) -> None:
        page_source = (ROOT / "apps/admin-web/app/projects/[project_id]/page.tsx").read_text(encoding="utf-8")
        action_source = (ROOT / "apps/admin-web/app/projects/[project_id]/actions.ts").read_text(encoding="utf-8")
        component_source = (ROOT / "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx").read_text(encoding="utf-8")
        compose_source = (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("/v1/project-member-invitations/runtime", action_source)
        self.assertIn("/v1/customer-portal/tokens/runtime", action_source)
        self.assertIn("/v1/customer-portal/tokens/runtime/revoke", action_source)
        self.assertIn("customerInvitationUrl", action_source)
        self.assertIn("NEXT_PUBLIC_CUSTOMER_WEB_BASE_URL", compose_source)
        self.assertIn("/v1/customer-portal/tokens/runtime", page_source)
        self.assertIn("InvitationForm", page_source)
        self.assertIn("TokenCreateForm", page_source)
        self.assertIn("TokenRevokeForm", page_source)
        self.assertIn("useActionState(createPortalTokenAction", component_source)
        self.assertNotIn('type="button"', page_source)

    def test_customer_web_uses_runtime_data_instead_of_placeholder_score(self) -> None:
        home_source = (ROOT / "apps/customer-web/app/page.tsx").read_text(encoding="utf-8")
        runtime_source = (ROOT / "apps/customer-web/app/runtime.ts").read_text(encoding="utf-8")
        module_source = (ROOT / "apps/customer-web/app/portal/[module]/page.tsx").read_text(encoding="utf-8")
        artifact_route_source = (ROOT / "apps/customer-web/app/api/report-artifact/route.ts").read_text(encoding="utf-8")

        self.assertIn("invitation_id", home_source)
        self.assertIn("invite_token", home_source)
        self.assertIn("bundle?.access?.member_user_id", home_source)
        self.assertIn("actorId?: string", runtime_source)
        self.assertIn("latestScore(runtime.scores)", home_source)
        self.assertNotIn("const score = undefined", home_source)
        self.assertNotIn('"36%"', home_source)
        for endpoint in (
            "/v1/visibility-scores/runtime",
            "/v1/evidence-runs/runtime",
            "/v1/collection-runs/runtime",
            "/v1/citation-graphs/runtime",
            "/v1/reports/runtime",
            "/v1/report-export-jobs/runtime",
            "/v1/action-plans/runtime",
            "/v1/traceability/runtime",
        ):
            self.assertIn(endpoint, runtime_source)
        self.assertIn("/api/report-artifact", module_source)
        self.assertIn("/v1/customer-portal/access", artifact_route_source)
        self.assertIn("/v1/reports/runtime/", artifact_route_source)
        self.assertIn("X-GENO-Actor-Id", artifact_route_source)
        self.assertNotIn("接入后会在此页", module_source)


if __name__ == "__main__":
    unittest.main()
