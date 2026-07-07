from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DashboardWebContractsTest(unittest.TestCase):
    def test_dashboard_app_is_retired_and_points_to_development_board(self) -> None:
        page_source = (ROOT / "apps/dashboard-web/app/page.tsx").read_text(encoding="utf-8")
        layout_source = (ROOT / "apps/dashboard-web/app/layout.tsx").read_text(encoding="utf-8")
        css_source = (ROOT / "apps/dashboard-web/app/globals.css").read_text(encoding="utf-8")

        self.assertIn("独立工程看板已合并", page_source)
        self.assertIn("/development-board", page_source)
        self.assertIn("不再作为默认服务维护", page_source)
        self.assertNotIn("dashboard-data.json", page_source)
        self.assertNotIn("GENO 工程进展 Dashboard", page_source)
        self.assertIn("GEO Dashboard 已合并", layout_source)
        self.assertIn(".retiredShell", css_source)

    def test_development_board_absorbs_dashboard_information(self) -> None:
        page_source = (ROOT / "apps/admin-web/app/development-board/page.tsx").read_text(encoding="utf-8")
        css_source = (ROOT / "apps/admin-web/app/globals.css").read_text(encoding="utf-8")

        self.assertIn("18006 独立 Dashboard 不再作为默认入口", page_source)
        self.assertIn("GEO-Production-v1正式可用性复查报告-2026-07-05.md", page_source)
        self.assertIn("make production-v1-final-gate", page_source)
        self.assertIn("tmp/frontend-page-click-smoke/latest.json", page_source)
        self.assertIn("buildFocusItems", page_source)
        self.assertIn(".developmentDocPanel", css_source)
        self.assertIn(".developmentArtifactGrid", css_source)
        self.assertIn(".developmentFocusList", css_source)

    def test_dashboard_is_not_in_default_stack_or_ci(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        compose = (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Development:  http://localhost", makefile)
        self.assertNotIn("Dashboard Web:http://localhost", makefile)
        self.assertNotIn("dashboard-web run typecheck", makefile)
        self.assertNotIn("dashboard-web run build", makefile)
        self.assertNotIn("customer-web admin-web dashboard-web", makefile)
        self.assertIn("retired-dashboard", compose)
        self.assertNotIn("apps/dashboard-web/package-lock.json", ci)
        self.assertNotIn("npm --prefix apps/dashboard-web ci", ci)
        self.assertIn("Development Board", readme)
        self.assertIn("旧 `apps/dashboard-web` 只保留退役提示页", readme)


if __name__ == "__main__":
    unittest.main()
