from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DashboardWebContractsTest(unittest.TestCase):
    def test_dashboard_app_is_static_json_backed_chinese_dashboard(self) -> None:
        package = json.loads((ROOT / "apps/dashboard-web/package.json").read_text(encoding="utf-8"))
        page_source = (ROOT / "apps/dashboard-web/app/page.tsx").read_text(encoding="utf-8")
        layout_source = (ROOT / "apps/dashboard-web/app/layout.tsx").read_text(encoding="utf-8")
        css_source = (ROOT / "apps/dashboard-web/app/globals.css").read_text(encoding="utf-8")
        dockerfile = (ROOT / "apps/dashboard-web/Dockerfile").read_text(encoding="utf-8")

        self.assertEqual(package["name"], "geno-saas-au-dashboard-web")
        self.assertEqual(package["dependencies"]["react"], "19.0.0")
        self.assertEqual(package["dependencies"]["react-dom"], "19.0.0")
        self.assertEqual(package["dependencies"]["next"], "^15.5.19")
        self.assertIn('import data from "../data/dashboard-data.json"', page_source)
        self.assertIn("GENO 工程进展 Dashboard", page_source)
        self.assertIn("总览", page_source)
        self.assertIn("计划", page_source)
        self.assertIn("代码", page_source)
        self.assertIn("测试", page_source)
        self.assertIn("文档", page_source)
        self.assertIn("下一步", page_source)
        self.assertIn("FilterBar", page_source)
        self.assertIn("Audit timeline", page_source)
        self.assertIn("EvidenceBlock", page_source)
        self.assertIn("<html lang=\"zh-CN\">", layout_source)
        self.assertIn(".dashboardShell", css_source)
        self.assertIn(".tabNav", css_source)
        self.assertIn(".anchorNav", css_source)
        self.assertIn(".auditGroup", css_source)
        self.assertIn("grid-template-columns: repeat(6, minmax(150px, 1fr));", css_source)
        self.assertIn("COPY apps/dashboard-web/package.json", dockerfile)
        self.assertIn("COPY apps/dashboard-web ./", dockerfile)
        self.assertNotIn("fetch(", page_source)
        self.assertNotIn("API_INTERNAL_BASE_URL", page_source)

    def test_dashboard_data_covers_plan_handoff_and_all_audit_slices(self) -> None:
        dashboard_data = json.loads((ROOT / "apps/dashboard-web/data/dashboard-data.json").read_text(encoding="utf-8"))
        audit_log = (ROOT / "docs/工程实施审计日志.md").read_text(encoding="utf-8")
        audit_heading_count = sum(1 for line in audit_log.splitlines() if line.startswith("## "))

        self.assertEqual(dashboard_data["meta"]["title"], "GENO 工程进展 Dashboard")
        self.assertIn("summaryMetrics", dashboard_data)
        self.assertIn("milestones", dashboard_data)
        self.assertIn("tasks", dashboard_data)
        self.assertIn("auditTimeline", dashboard_data)
        self.assertIn("qualityGates", dashboard_data)
        self.assertIn("nextActions", dashboard_data)
        self.assertGreaterEqual(len(dashboard_data["milestones"]), 8)
        self.assertGreaterEqual(len(dashboard_data["tasks"]), 100)
        self.assertEqual(len(dashboard_data["auditTimeline"]), audit_heading_count)
        self.assertEqual(dashboard_data["auditStats"]["total"], audit_heading_count)
        self.assertEqual(audit_heading_count, 342)
        self.assertEqual(
            dashboard_data["auditTimeline"][-1]["title"],
            "客户门户 / 内部项目中心拆分与审计入库审计",
        )
        self.assertTrue(
            any(action["title"] == "Admin Web 新建项目接入真实项目创建 API" for action in dashboard_data["nextActions"])
        )
        self.assertTrue(
            any(gate["command"] == "npm --prefix apps/dashboard-web run typecheck" for gate in dashboard_data["qualityGates"])
        )

    def test_dashboard_is_wired_into_make_compose_ci_and_readme(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        compose = (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('"dashboard_web"', makefile)
        self.assertIn("GENO_DASHBOARD_WEB_HOST_PORT", makefile)
        self.assertIn("Dashboard Web:http://localhost", makefile)
        self.assertIn("dashboard-web", makefile)
        self.assertIn("npm --prefix apps/dashboard-web run typecheck", makefile)
        self.assertIn("npm --prefix apps/dashboard-web run build", makefile)
        self.assertIn("dashboard-web:", compose)
        self.assertIn("dockerfile: apps/dashboard-web/Dockerfile", compose)
        self.assertIn("GENO_DASHBOARD_WEB_CONTAINER_PORT", compose)
        self.assertNotIn("dashboard-web:\n    build:\n      context: ..\n      dockerfile: apps/dashboard-web/Dockerfile\n    environment:\n      API_INTERNAL_BASE_URL", compose)
        self.assertIn("apps/dashboard-web/package-lock.json", ci)
        self.assertIn("npm --prefix apps/dashboard-web ci", ci)
        self.assertIn("apps/dashboard-web", readme)
        self.assertIn("Dashboard Web 是只读工程进展看板", readme)
