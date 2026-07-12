from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductionV1GateContractsTest(unittest.TestCase):
    def test_checklist_tracks_plan_sections_and_deferred_upgrades(self) -> None:
        checklist = (ROOT / "docs/GEO-Production-v1执行进度-checklist-2026-07-05.md").read_text(encoding="utf-8")

        self.assertIn("GEO-Production-v1完整规划-2026-07-05.md", checklist)
        for item in ("W10-I01", "W2-I01a", "W3-I00", "W4-I01d", "W6-I01f", "W8-I03", "W9-I02"):
            self.assertIn(item, checklist)
        for upgrade in ("额外平台", "自动发布", "高级图谱", "复杂 SSO"):
            self.assertIn(upgrade, checklist)
        self.assertIn("Deferred upgrade", checklist)

    def test_makefile_exposes_production_v1_gate_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        for target in (
            "lint:",
            "typecheck:",
            "rls-smoke:",
            "security-smoke:",
            "production-v1-e2e:",
            "enablement-v1-e2e:",
            "no-fixture-production-smoke:",
            "no-secret-leak-smoke:",
            "report-traceability-smoke:",
            "customer-access-negative-smoke:",
            "connector-real-smoke:",
            "frontend-page-click-smoke:",
            "full-project-lifecycle-smoke:",
            "official-ui-contract-smoke:",
            "development-board-truth-smoke:",
            "ops-smoke:",
            "backup-smoke:",
            "production-v1-final-gate:",
        ):
            self.assertIn(target, makefile)
        self.assertIn("scripts/verify_production_v1_gate.py", makefile)
        self.assertIn("scripts/run_connector_real_smoke.py", makefile)
        self.assertIn("scripts/run_frontend_page_click_smoke.py", makefile)
        self.assertIn("scripts/run_frontend_knowledge_lifecycle_smoke.py", makefile)
        self.assertIn(
            "frontend-knowledge-click-smoke: geo-production-full-pipeline-smoke frontend-page-click-smoke",
            makefile,
        )
        self.assertIn("scripts/run_full_project_lifecycle_smoke.py", makefile)
        self.assertIn("frontend-page-click-smoke", makefile)
        self.assertIn("full-project-lifecycle-smoke", makefile)
        self.assertIn("official-ui-contract-smoke", makefile)
        self.assertIn("development-board-truth-smoke", makefile)
        self.assertIn("knowledge-heavy-components-smoke", makefile)
        self.assertIn("KNOWLEDGE_HEAVY_REBUILD", makefile)
        self.assertIn('docker image inspect "$(KNOWLEDGE_HEAVY_IMAGE)"', makefile)
        self.assertIn("HF_HUB_OFFLINE=1", makefile)
        self.assertIn("TRANSFORMERS_OFFLINE=1", makefile)
        self.assertIn("knowledge-worker-runtime-image: knowledge-heavy-components-smoke", makefile)
        self.assertIn("workers/knowledge_worker/Dockerfile.runtime", makefile)
        self.assertIn('GENO_KNOWLEDGE_WORKER_IMAGE="$(KNOWLEDGE_WORKER_IMAGE)"', makefile)
        self.assertIn("geo-production-full-pipeline-smoke", makefile)
        self.assertIn("frontend-knowledge-click-smoke", makefile)

    def test_connector_real_smoke_is_real_deepseek_execution_not_static_skip(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        gate_script = (ROOT / "scripts/verify_production_v1_gate.py").read_text(encoding="utf-8")
        smoke_script = (ROOT / "scripts/run_connector_real_smoke.py").read_text(encoding="utf-8")

        self.assertIn("scripts/run_connector_real_smoke.py", makefile)
        self.assertIn("scripts/run_connector_real_smoke.py", gate_script)
        self.assertIn("deepseek-v4-flash", smoke_script)
        self.assertIn("https://api.deepseek.com/chat/completions", smoke_script)
        self.assertIn("deepseek_api_key.txt", smoke_script)
        self.assertIn("report contains the raw API key", smoke_script)
        self.assertNotIn("real_provider_smoke_skipped_local", gate_script)
        self.assertNotIn("OPENAI_API_KEY/PERPLEXITY_API_KEY absent", gate_script)

    def test_frontend_page_click_smoke_is_in_final_gate(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        gate_script = (ROOT / "scripts/verify_production_v1_gate.py").read_text(encoding="utf-8")
        smoke_script = (ROOT / "scripts/run_frontend_page_click_smoke.py").read_text(encoding="utf-8")

        self.assertIn("frontend-page-click-smoke:", makefile)
        self.assertIn("frontend-page-click-smoke", gate_script)
        self.assertIn("sync_playwright", smoke_script)
        self.assertIn("/development-board", smoke_script)
        self.assertIn("basic_tab=launch", smoke_script)
        self.assertIn("deepseek-v4-flash", smoke_script)
        self.assertIn("operation_tab=quality", smoke_script)
        self.assertIn("项目负责人", smoke_script)
        self.assertIn("市场与行业", smoke_script)
        self.assertIn("初始状态：暂停中", smoke_script)
        self.assertIn("调度配置 JSON", smoke_script)
        self.assertIn("添加新竞品", smoke_script)
        self.assertIn("项目与品牌", smoke_script)
        self.assertIn("连接状态", smoke_script)
        self.assertIn("当前可用邀请", smoke_script)
        self.assertIn("历史 / 已失效邀请", smoke_script)
        self.assertIn("质量与运维", smoke_script)
        self.assertIn("chunk_query=delivery", smoke_script)
        self.assertIn("source_fact_kind", smoke_script)
        self.assertIn("source-backed Prompt generation scope", smoke_script)
        self.assertIn("source-linked GEO content generation controls", smoke_script)
        self.assertIn("configured URL/site crawl", smoke_script)
        self.assertNotIn("operation_tab=connectors", smoke_script)
        self.assertIn("/portal/traceability", smoke_script)
        self.assertNotIn("/?tab=test", smoke_script)
        self.assertNotIn("/?tab=next", smoke_script)
        self.assertIn("framework error overlay detected", smoke_script)

        knowledge_lifecycle = (ROOT / "scripts/run_frontend_knowledge_lifecycle_smoke.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "frontend_import_precheck_and_start",
            "frontend_view_pipeline_processing",
            "frontend_fact_candidate_review",
            "frontend_prompt_generation",
            "frontend_prompt_review_and_import",
            "frontend_content_generation",
            "frontend_content_review_and_export",
            "frontend_knowledge_search",
            "run_knowledge_pipeline.py",
            "regular_playwright",
        ):
            self.assertIn(required, knowledge_lifecycle)

    def test_full_project_lifecycle_smoke_is_in_final_gate(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        gate_script = (ROOT / "scripts/verify_production_v1_gate.py").read_text(encoding="utf-8")
        smoke_script = (ROOT / "scripts/run_full_project_lifecycle_smoke.py").read_text(encoding="utf-8")

        self.assertIn("full-project-lifecycle-smoke:", makefile)
        self.assertIn("full-project-lifecycle-smoke", gate_script)
        self.assertIn("tmp/full-project-lifecycle-smoke/latest.json", gate_script)
        for step in (
            "create_project",
            "project_status_action_flow",
            "connector_test_launch_config",
            "project_member_crud",
            "invitation_revoke_regenerate",
            "prompt_import_update_export",
            "manual_backfill_single_csv",
            "report_publish_download_revoke",
            "negative_cross_project_backfill",
        ):
            self.assertIn(step, smoke_script)
            self.assertIn(step, gate_script)
        self.assertIn('"/v1/projects/runtime"', smoke_script)
        self.assertNotIn("/v1/projects/runtime/au/dtc-ecommerce", smoke_script)
        self.assertIn("geno-full-lifecycle-secret-do-not-log", smoke_script)
        self.assertIn("full_lifecycle_no_skipped_critical_steps", gate_script)
        self.assertIn("connector_secret_masking", gate_script)
        self.assertIn("deepseek_collection_analysis_scoring", gate_script)
        self.assertNotIn('"fixture_collection_analysis_scoring"', gate_script)

    def test_gate_script_checklist_mode_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/verify_production_v1_gate.py", "checklist"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn('"gate": "checklist"', result.stdout)
        self.assertIn('"status": "passed"', result.stdout)

    def test_production_e2e_requires_fresh_runtime_lifecycle_evidence(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        gate_script = (ROOT / "scripts/verify_production_v1_gate.py").read_text(encoding="utf-8")

        self.assertIn("production-v1-e2e: full-project-lifecycle-smoke", makefile)
        self.assertIn("*_gate_full_project_lifecycle()", gate_script)
        self.assertIn("_runtime_artifact_checks", gate_script)
        self.assertIn("run_id is missing", gate_script)

    def test_gate_script_allow_pending_mode_is_available_for_progress_view(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/verify_production_v1_gate.py",
                "checklist",
                "--allow-pending",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn('"status": "passed"', result.stdout)

    def test_gate_script_official_ui_contract_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/verify_production_v1_gate.py", "official-ui-contract-smoke"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn('"gate": "official-ui-contract-smoke"', result.stdout)
        self.assertIn('"status": "passed"', result.stdout)

    def test_gate_script_development_board_truth_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/verify_production_v1_gate.py", "development-board-truth-smoke"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn('"gate": "development-board-truth-smoke"', result.stdout)
        self.assertIn('"status": "passed"', result.stdout)


if __name__ == "__main__":
    unittest.main()
