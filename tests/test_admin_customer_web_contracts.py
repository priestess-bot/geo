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
        self.assertIn("role=\"dialog\"", form_source)
        self.assertIn("提交前确认", form_source)
        self.assertIn("返回修改", form_source)
        self.assertIn("确认创建项目", form_source)
        self.assertIn("邀请 token 只显示一次", form_source)
        self.assertIn("打开项目详情", form_source)
        self.assertIn("打开客户邀请入口", form_source)
        self.assertIn("onClick={handleEdit}", form_source)
        self.assertIn("onClick={handleConfirmSubmit}", form_source)
        self.assertIn("<option value=\"api\">真实 API</option>", form_source)
        self.assertIn("<option value=\"manual\">手工补录</option>", form_source)
        self.assertIn('collectionMode: "api"', form_source)
        self.assertIn('requiredString(formData, "collection_mode", "api")', action_source)
        self.assertNotIn("<option value=\"fixture\"", form_source)
        self.assertNotIn("AU GEO Pilot", form_source)
        self.assertNotIn("ExampleBrand", form_source)
        self.assertNotIn('method="get"', page_source)
        self.assertNotIn("后续会改成", page_source)

    def test_admin_project_detail_wires_customer_access_runtime_actions(self) -> None:
        page_source = (ROOT / "apps/admin-web/app/projects/[project_id]/page.tsx").read_text(encoding="utf-8")
        action_source = (ROOT / "apps/admin-web/app/projects/[project_id]/actions.ts").read_text(encoding="utf-8")
        component_source = (ROOT / "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx").read_text(encoding="utf-8")
        compose_source = (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("/v1/projects/runtime/action", action_source)
        self.assertIn("/v1/project-launch-configs/runtime", action_source)
        self.assertIn("/v1/project-entities/runtime/brand", action_source)
        self.assertIn("/v1/project-entities/runtime/competitors", action_source)
        self.assertIn("/v1/collection-runs/runtime/fixture", action_source)
        self.assertIn('"/v1/prompts/runtime"', action_source)
        self.assertIn("/v1/prompts/runtime/import.csv", action_source)
        self.assertIn("/v1/project-member-invitations/runtime", action_source)
        self.assertIn("/v1/customer-portal/tokens/runtime", action_source)
        self.assertIn("/v1/customer-portal/tokens/runtime/revoke", action_source)
        self.assertIn("/v1/project-member-invitations/runtime/action", action_source)
        self.assertIn("redirect(`/projects/${pid}?tab=prompts", action_source)
        self.assertIn("revalidateProject", action_source)
        self.assertIn("customerInvitationUrl", action_source)
        self.assertIn("NEXT_PUBLIC_CUSTOMER_WEB_BASE_URL", compose_source)
        self.assertIn("/v1/customer-portal/tokens/runtime", page_source)
        self.assertIn("/v1/score-weight-configs/runtime", page_source)
        self.assertIn("/v1/score-formulas/runtime", page_source)
        self.assertIn("InvitationForm", page_source)
        self.assertIn("InvitationList", page_source)
        self.assertIn("TokenList", page_source)
        self.assertIn("MemberList", page_source)
        self.assertIn("TokenCreateForm", page_source)
        self.assertIn("TokenRevokeForm", page_source)
        self.assertIn("ProjectBasicsForm", page_source)
        self.assertIn("LaunchConfigForm", page_source)
        self.assertIn("BrandEntityForm", page_source)
        self.assertIn("CompetitorEditor", page_source)
        self.assertIn("FixtureE2EForm", page_source)
        self.assertIn("adminDevToolsEnabled", page_source)
        self.assertIn("devToolsEnabled ?", page_source)
        self.assertIn("生产环境不暴露本地测试入口", page_source)
        self.assertIn("PromptEditor", page_source)
        self.assertIn("PromptImportForm", page_source)
        self.assertIn("mainTabs", page_source)
        self.assertIn("basicTabs", page_source)
        self.assertIn("statusTabs", page_source)
        self.assertIn("tab: \"prompts\"", page_source)
        self.assertIn("Prompt 总数", page_source)
        self.assertIn("每页显示", page_source)
        self.assertIn("prompt_limit", page_source)
        self.assertIn("导出 CSV", page_source)
        self.assertIn("项目看板", page_source)
        self.assertIn("/v1/collection-runs/runtime", page_source)
        self.assertIn("useActionState(createPortalTokenAction", component_source)
        self.assertIn("useActionState(updateProjectAction", component_source)
        self.assertIn("useActionState(saveLaunchConfigAction", component_source)
        self.assertIn("useActionState(saveCompetitorEntityAction", component_source)
        self.assertIn("useActionState(savePromptAction", component_source)
        self.assertIn("useActionState(runFixtureE2EAction", component_source)
        self.assertIn("<option value=\"api\">真实 API</option>", component_source)
        self.assertIn("<option value=\"manual\">手工补录</option>", component_source)
        self.assertNotIn("<option value=\"fixture\"", component_source)
        self.assertNotIn("<option value=\"fixture_only\"", component_source)
        self.assertIn("competitor_domains_snapshot", component_source)
        self.assertIn("accordionItem", component_source)
        self.assertIn("ConnectorConfigCard", component_source)
        self.assertIn("score_weight_config", page_source)
        self.assertIn("配置记录", component_source)
        self.assertIn("OpenAI 连接器", component_source)
        self.assertIn("Perplexity 连接器", component_source)
        self.assertIn("Google AI Mode", component_source)
        self.assertIn("type=\"button\"", component_source)
        self.assertIn("setDraftCount", component_source)
        self.assertIn("新增竞品", component_source)
        self.assertIn("修改", component_source)
        self.assertIn("撤销邀请", component_source)
        self.assertIn("Prompt 文本", component_source)
        self.assertIn("调度频率", component_source)
        self.assertNotIn("<summary><span>新增竞品</span>", component_source)
        self.assertNotIn("高级 JSON 配置", page_source)
        self.assertNotIn("当前页样本", page_source)
        self.assertNotIn("<pre>{JSON.stringify(record", page_source)
        self.assertNotIn("<pre>{JSON.stringify(launchConfig", page_source)

    def test_admin_projects_list_supports_filters_and_archive_restore(self) -> None:
        page_source = (ROOT / "apps/admin-web/app/projects/page.tsx").read_text(encoding="utf-8")
        component_source = (ROOT / "apps/admin-web/app/projects/[project_id]/ProjectActions.tsx").read_text(encoding="utf-8")

        self.assertIn("status", page_source)
        self.assertIn("include_archived", page_source)
        self.assertIn("搜索项目", page_source)
        self.assertIn("ProjectLifecycleForm", page_source)
        self.assertIn("归档项目", component_source)
        self.assertIn("恢复项目", component_source)
        self.assertIn("window.confirm", component_source)

    def test_runtime_project_e2e_verifier_targets_existing_project(self) -> None:
        script_source = (ROOT / "scripts/verify_runtime_project_e2e.py").read_text(encoding="utf-8")

        self.assertIn("--project-id", script_source)
        self.assertIn("workers/collector_worker/run_collection_slice.py", script_source)
        self.assertIn("--persist-analysis", script_source)
        self.assertIn("answer_runs", script_source)
        self.assertIn("visibility_score_snapshots", script_source)
        self.assertIn("report_exports", script_source)
        self.assertIn("traceability_bundles", script_source)

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
