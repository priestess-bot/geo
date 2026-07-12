from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "tmp/frontend-page-click-smoke"
AUTO_PORTS_ENV = ROOT / "tmp/docker-compose.auto-ports.env"
DEFAULT_PROJECT_ID = "4a6c168e-c596-56a8-932a-3271e2ef16f0"
FRAMEWORK_ERROR_PATTERNS = (
    "Unhandled Runtime Error",
    "Application error:",
    "Hydration failed",
    "A tree hydrated but some attributes",
    "data-nextjs-dialog",
    "nextjs__container_errors",
    "Build Error",
)


@dataclass(frozen=True)
class PageCheck:
    app: str
    route: str
    viewport: str
    status: str
    detail: str
    screenshot_path: str | None = None


def _read_auto_ports() -> dict[str, str]:
    if not AUTO_PORTS_ENV.exists():
        return {}
    values: dict[str, str] = {}
    for line in AUTO_PORTS_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _base_urls(admin_url: str | None, customer_url: str | None) -> dict[str, str]:
    ports = _read_auto_ports()
    return {
        "admin": admin_url or f"http://localhost:{ports.get('GENO_ADMIN_WEB_HOST_PORT', '18005')}",
        "customer": customer_url or f"http://localhost:{ports.get('GENO_CUSTOMER_WEB_HOST_PORT', '18004')}",
    }


def _server_reachable(url: str) -> bool:
    deadline = time.monotonic() + 30
    while True:
        try:
            response = httpx.get(url, timeout=10)
            if response.status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:120] or "page"


def _routes(project_id: str) -> dict[str, list[str]]:
    project = f"/projects/{project_id}"
    return {
        "admin": [
            "/",
            "/development-board",
            "/projects",
            "/projects/new",
            f"{project}?tab=basic&basic_tab=project",
            f"{project}?tab=basic&basic_tab=launch",
            f"{project}?tab=basic&basic_tab=competitors",
            f"{project}?tab=entry",
            f"{project}?tab=prompts&prompt_tab=config",
            f"{project}?tab=prompts&prompt_tab=generate",
            f"{project}?tab=prompts&prompt_tab=candidates",
            f"{project}?tab=prompts&prompt_tab=templates",
            f"{project}?tab=prompts&prompt_tab=imports",
            f"{project}?tab=knowledge&knowledge_tab=import",
            f"{project}?tab=knowledge&knowledge_tab=processing",
            f"{project}?tab=knowledge&knowledge_tab=chunks",
            f"{project}?tab=knowledge&knowledge_tab=search",
            f"{project}?tab=knowledge&knowledge_tab=dashboard",
            f"{project}?tab=knowledge&knowledge_tab=quality",
            f"{project}?tab=knowledge&knowledge_tab=trace",
            f"{project}?tab=operations&operation_tab=backfill",
            f"{project}?tab=operations&operation_tab=review",
            f"{project}?tab=operations&operation_tab=reports",
            f"{project}?tab=operations&operation_tab=actions",
            f"{project}?tab=operations&operation_tab=content",
            f"{project}?tab=operations&operation_tab=assets",
            f"{project}?tab=operations&operation_tab=quality",
            f"{project}?tab=status",
            f"{project}?tab=e2e",
        ],
        "customer": [
            "/portal/visibility",
            "/portal/sources",
            "/portal/evidence",
            "/portal/reports",
            "/portal/actions",
            "/portal/handoff",
            "/portal/traceability",
        ],
    }


def _page_has_framework_overlay(html: str) -> bool:
    return any(pattern in html for pattern in FRAMEWORK_ERROR_PATTERNS)


def _meaningful_text(page: Any) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=3000)).strip()
    except Exception:
        return ""


def _assert_text(body_text: str, route: str, required: tuple[str, ...], forbidden: tuple[str, ...] = ()) -> str:
    missing = [item for item in required if item not in body_text]
    present_forbidden = [item for item in forbidden if item in body_text]
    if missing or present_forbidden:
        detail = []
        if missing:
            detail.append(f"missing={missing}")
        if present_forbidden:
            detail.append(f"forbidden={present_forbidden}")
        raise AssertionError(f"{route} text assertions failed: {'; '.join(detail)}")
    return f"text assertions passed: {len(required)} required"


def _route_assertions(route: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if route == "/projects/new":
        return (
            (
                "新建 GEO 项目",
                "竞品范围",
                "竞品 1 名称",
                "竞品 1 域名",
                "添加新竞品",
                "项目负责人",
                "市场与行业",
                "市场代码",
                "语言区域",
                "初始状态：暂停中",
            ),
            (
                "项目 owner",
                "生成 viewer 邀请",
                "不保存 raw secret",
                "调度配置 JSON",
                "连接器配置 JSON",
            ),
        )
    if route == "/projects":
        return (("项目列表", "状态筛选", "新建项目", "返回首页"), ("暂停中（历史已配置）", "<option value=\"configured\""))
    if "basic_tab=project" in route:
        return (("项目与品牌", "项目、租户和目标品牌", "保存项目与品牌", "官网域名"), ("保存基础配置", "保存品牌配置", "<option value=\"configured\""))
    if "basic_tab=launch" in route:
        return (
            (
                "评分配置",
                "评分方案",
                "另存为自定义评分方案",
                "连接器配置",
                "连接状态",
                "运行模式",
                "模型 / 服务",
                "API key",
                "测试连接",
                "显示已保存 API key",
            ),
            ("高级 JSON 配置", "配置文件 / 记录", "权重合计"),
        )
    if "basic_tab=competitors" in route:
        return (("逐条管理竞品", "新增竞品", "启动", "暂停", "归档"), ("<select",))
    if "tab=entry" in route:
        return (("客户邀请", "成员权限", "安全会话", "当前可用邀请", "历史 / 已失效邀请"), ())
    if "prompt_tab=config" in route:
        return (("Prompt 配置", "正式采集 Prompt", "Prompt 总数", "导入 Prompt CSV"), ())
    if "prompt_tab=generate" in route:
        return (("Prompt 生成", "生成提问 Prompt 候选", "生成模板", "仅已批准知识", "生成 Prompt 候选"), ())
    if "prompt_tab=candidates" in route:
        return (("候选审核", "审核并导入 Prompt 候选", "导入已批准 Prompt"), ())
    if "prompt_tab=templates" in route:
        return (("生成模板", "本地模板库与 Langfuse 兼容字段", "新增或更新 Prompt 生成模板"), ())
    if "prompt_tab=imports" in route:
        return (("导入记录", "CSV 与候选导入追踪", "候选导入记录"), ())
    if "knowledge_tab=import" in route:
        return (("知识库导入", "来源导入、解析和事实抽取", "创建完整知识库 Pipeline", "Docling", "创建并启动 Pipeline"), ())
    if "knowledge_tab=processing" in route:
        return (("知识库处理任务", "Pipeline、Job 和 Quality Gate", "Source Assets", "Parser Runs"), ())
    if "knowledge_tab=chunks" in route:
        return (("Chunk 可视化", "文件与网页", "Chunks", "选择一个 Chunk"), ())
    if "knowledge_tab=search" in route:
        return (("知识库检索", "验证已批准知识是否可用", "检索知识库", "检索结果"), ())
    if "knowledge_tab=dashboard" in route:
        return (("知识库看板", "覆盖、质量和应用状态", "知识来源", "Prompt 候选"), ())
    if "knowledge_tab=quality" in route:
        return (("知识库质检", "事实审核、去重和风险处理", "保存事实审核"), ())
    if "knowledge_tab=trace" in route:
        return (("证据追踪", "Source Asset 到 Chunk 到 Fact 到 Prompt / Content", "Trace Refs"), ())
    if "operation_tab=backfill" in route:
        return (("Google 补录", "写入证据链", "选择 Prompt 或导入 CSV"), ("连接器密钥",))
    if "operation_tab=review" in route:
        return (("人工复核", "修正自动解析", "复核队列"), ("连接器密钥",))
    if "operation_tab=reports" in route:
        return (("报告中心", "生成、审批、发布和撤回", "客户门户下载"), ("连接器密钥",))
    if "operation_tab=actions" in route:
        return (("行动与复测", "before/after/delta"), ("连接器密钥",))
    if "operation_tab=content" in route:
        return (("内容与分发", "URL/proof"), ("连接器密钥",))
    if "operation_tab=assets" in route:
        return (("品牌资产", "登记资产 URL"), ("连接器密钥",))
    if "operation_tab=quality" in route:
        return (("质量与运维", "fidelity check", "不负责配置连接器密钥"), ())
    return ((), ())


def _click_by_text(page: Any, label: str) -> str:
    locator = page.get_by_text(label, exact=True)
    count = min(locator.count(), 3)
    for index in range(count):
        item = locator.nth(index)
        try:
            if item.is_visible(timeout=500):
                item.click(timeout=1500)
                page.wait_for_load_state("networkidle", timeout=5000)
                return f"clicked text: {label}"
        except Exception:
            continue
    return f"text not clickable: {label}"


def _targeted_interaction(page: Any, route: str) -> str:
    if route == "/projects/new":
        before = page.locator("input[name='competitor_name']").count()
        clicked = _click_by_text(page, "添加新竞品")
        after = page.locator("input[name='competitor_name']").count()
        if after <= before:
            raise AssertionError(f"添加新竞品 did not add a row: before={before}, after={after}, {clicked}")
        return f"{clicked}; competitor rows {before}->{after}"
    if "basic_tab=competitors" in route:
        before = page.locator(".accordionItem.addItem").count()
        clicked = _click_by_text(page, "新增竞品")
        after = page.locator(".accordionItem.addItem").count()
        if after <= before:
            raise AssertionError(f"新增竞品 did not add an accordion item: before={before}, after={after}, {clicked}")
        return f"{clicked}; draft competitors {before}->{after}"
    if "basic_tab=launch" in route:
        mode = page.locator("select[name='connector_openai_mode']").first
        model = page.locator("select[name='connector_openai_model']").first
        if mode.is_visible(timeout=1000) and model.is_visible(timeout=1000):
            mode.select_option("deepseek_fallback")
            model.select_option("deepseek-v4-flash")
            return "selected OpenAI connector deepseek fallback"
    if "tab=entry" in route:
        return _click_by_text(page, "历史 / 已失效邀请")
    if "prompt_tab=generate" in route:
        interactions: list[str] = []
        template = page.locator("select[name='prompt_template_id']").first
        if template.is_visible(timeout=1000):
            options = template.locator("option:not([disabled])")
            if options.count() > 0:
                template.select_option(index=1)
                interactions.append("selected published prompt generation template version")
        scope_summary = page.get_by_text("限定生成使用的知识范围", exact=True).first
        if scope_summary.is_visible(timeout=1000):
            scope_summary.click()
            page.locator("select[name='source_fact_kind']").first.select_option("brand")
            page.locator("input[name='source_market_code']").first.fill("AU")
            page.locator("select[name='source_chunk_type']").first.select_option("text")
            page.locator("input[name='source_chunk_query']").first.fill("delivery")
            interactions.append("configured source-backed Prompt generation scope")
        return "; ".join(interactions) or "Prompt generation controls visible"
    if "prompt_tab=templates" in route:
        return _click_by_text(page, "查看模板规则")
    if "knowledge_tab=import" in route:
        source_mode = page.locator("select[name='source_mode']").first
        source_mode.select_option("url")
        page.locator("textarea[name='source_urls']").first.fill("https://example.com/faq")
        source_mode.select_option("site_crawl")
        page.locator("textarea[name='source_urls']").first.fill("https://example.com/help")
        page.locator("input[name='max_pages']").first.fill("5")
        page.locator("input[name='depth_limit']").first.fill("1")
        page.locator("select[name='respect_robots']").first.select_option("1")
        source_mode.select_option("file")
        file_input = page.locator("input[name='source_files']").first
        file_input.set_input_files(
            [
                {"name": "playwright-brand.md", "mimeType": "text/markdown", "buffer": b"# Brand policy\nFree delivery over AUD 99."},
                {"name": "playwright-market.csv", "mimeType": "text/csv", "buffer": b"subject,predicate,value\nBrand,returns,30 days\n"},
            ]
        )
        page.wait_for_function("document.querySelectorAll('.knowledgeFileQueueRow').length === 2", timeout=10000)
        return "configured URL/site crawl and rendered a two-file precheck queue"
    if "knowledge_tab=processing" in route:
        return "pipeline stages and parser artifacts visible"
    if "knowledge_tab=chunks" in route:
        query = page.locator("input[name='chunk_query']").first
        if not query.is_visible(timeout=1000):
            raise AssertionError("knowledge chunk filter form is missing")
        query.fill("delivery")
        page.locator("select[name='chunk_status']").first.select_option("active")
        page.locator("select[name='chunk_type']").first.select_option("text")
        page.get_by_text("应用筛选", exact=True).first.click()
        page.wait_for_load_state("networkidle", timeout=5000)
        if "chunk_query=delivery" not in page.url or "chunk_status=active" not in page.url:
            raise AssertionError(f"knowledge chunk filters did not persist in URL: {page.url}")
        fact_source = page.locator("select[name='source_pipeline_run_id']").last
        if fact_source.is_visible(timeout=1000) and fact_source.locator("option:not([disabled])").count() > 0:
            fact_source.select_option(index=1)
            page.locator("select[name='chunk_type']").last.select_option("text")
            page.locator("textarea[name='fact_kinds']").first.fill("brand\ncompetitor\nmarket\nsource")
            page.locator("input[name='max_facts']").first.fill("12")
        chunks = page.locator(".knowledgeChunkItem")
        if chunks.count() > 0 and chunks.first.is_visible(timeout=1000):
            chunks.first.click()
            page.wait_for_load_state("networkidle", timeout=5000)
            return "applied chunk filters, configured fact extraction, and opened evidence pane"
        return "applied chunk filters and verified fact extraction controls with empty result state"
    if "knowledge_tab=search" in route:
        button = page.get_by_text("检索知识库", exact=True).first
        if button.is_visible(timeout=1000):
            return "knowledge search form visible"
    if "knowledge_tab=dashboard" in route or "knowledge_tab=quality" in route or "knowledge_tab=trace" in route:
        return "knowledge subtab visible"
    if "operation_tab=" in route:
        if "operation_tab=content" in route:
            page.locator("select[name='content_type']").first.select_option("evidence_brief")
            page.locator("input[name='source_action_id']").first.fill("00000000-0000-0000-0000-000000000001")
            page.locator("input[name='source_report_id']").first.fill("00000000-0000-0000-0000-000000000002")
            page.locator("input[name='source_retest_id']").first.fill("00000000-0000-0000-0000-000000000003")
            page.locator("input[name='source_gap_type']").first.fill("weak_citation")
            return "configured source-linked GEO content generation controls"
        summary = page.locator(".operationGuide").first
        if summary.is_visible(timeout=1000):
            return "operation guide visible"
    return _click_first_available(page)


def _click_first_available(page: Any) -> str:
    candidates = (
        "a",
        "button",
        "summary",
        "select",
        "input:not([type=hidden])",
    )
    for selector in candidates:
        locator = page.locator(selector)
        try:
            count = min(locator.count(), 8)
        except Exception:
            continue
        for index in range(count):
            item = locator.nth(index)
            try:
                if not item.is_visible(timeout=500):
                    continue
                label = (item.inner_text(timeout=500) if selector not in {"input:not([type=hidden])", "select"} else selector).strip()
                if selector == "a":
                    href = item.get_attribute("href")
                    if href and href.startswith(("http://", "https://")):
                        continue
                item.click(timeout=1500)
                page.wait_for_load_state("networkidle", timeout=5000)
                return f"clicked {selector}: {label[:80] or index}"
            except Exception:
                continue
    return "no visible clickable control found"


def run_smoke(
    *,
    output_dir: Path,
    project_id: str,
    admin_url: str | None,
    customer_url: str | None,
    mobile: bool,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("Python Playwright is not installed. Install it before running frontend-page-click-smoke.") from exc

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bases = _base_urls(admin_url, customer_url)
    routes = _routes(project_id)
    checks: list[PageCheck] = []
    console_events: list[dict[str, str]] = []
    viewports = [("desktop", {"width": 1440, "height": 900})]
    if mobile:
        viewports.append(("mobile", {"width": 390, "height": 844}))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for app, base_url in bases.items():
                if not _server_reachable(base_url):
                    checks.append(PageCheck(app, "/", "server", "fail", f"server is not reachable: {base_url}"))
                    continue
                for viewport_name, viewport in viewports:
                    context = browser.new_context(viewport=viewport)
                    page = context.new_page()
                    page.on(
                        "console",
                        lambda message, app=app: console_events.append(
                            {"app": app, "type": message.type, "text": message.text[:500]}
                        )
                        if message.type in {"error", "warning"}
                        else None,
                    )
                    try:
                        for route in routes[app]:
                            url = f"{base_url}{route}"
                            screenshot_path: Path | None = None
                            try:
                                page.goto(url, wait_until="networkidle", timeout=20000)
                                html = page.content()
                                body_text = _meaningful_text(page)
                                screenshot_path = output_dir / f"{app}-{viewport_name}-{_safe_name(route)}.png"
                                page.screenshot(path=str(screenshot_path), full_page=False)
                                if not body_text:
                                    checks.append(PageCheck(app, route, viewport_name, "fail", "blank body", str(screenshot_path)))
                                    continue
                                if _page_has_framework_overlay(html):
                                    checks.append(
                                        PageCheck(app, route, viewport_name, "fail", "framework error overlay detected", str(screenshot_path))
                                    )
                                    continue
                                required, forbidden = _route_assertions(route)
                                assertion_detail = _assert_text(body_text, route, required, forbidden)
                                interaction = _targeted_interaction(page, route)
                                checks.append(
                                    PageCheck(
                                        app,
                                        route,
                                        viewport_name,
                                        "pass",
                                        f"rendered; {assertion_detail}; interaction checked: {interaction}",
                                        str(screenshot_path),
                                    )
                                )
                            except Exception as exc:  # noqa: BLE001 - report page-level smoke failures.
                                checks.append(
                                    PageCheck(
                                        app,
                                        route,
                                        viewport_name,
                                        "fail",
                                        str(exc),
                                        str(screenshot_path) if screenshot_path else None,
                                    )
                                )
                    finally:
                        context.close()
        finally:
            browser.close()

    actionable_console = [
        event
        for event in console_events
        if event["type"] == "error"
        and "Failed to load resource" not in event["text"]
        and "favicon" not in event["text"].lower()
    ]
    if actionable_console:
        checks.append(PageCheck("all", "console", "all", "fail", json.dumps(actionable_console[:10], ensure_ascii=False)))

    report = {
        "run_id": f"frontend-click-{started_at.strftime('%Y%m%d%H%M%S%f')}",
        "status": "passed" if all(check.status == "pass" for check in checks) else "failed",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "base_urls": bases,
        "project_id": project_id,
        "checks": [asdict(check) for check in checks],
        "summary": {
            "pass": sum(1 for check in checks if check.status == "pass"),
            "fail": sum(1 for check in checks if check.status == "fail"),
            "viewports": [name for name, _ in viewports],
        },
    }
    report_path = output_dir / "latest.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rendered frontend page-click smoke tests with Playwright.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--admin-url")
    parser.add_argument("--customer-url")
    parser.add_argument("--mobile", action="store_true")
    args = parser.parse_args()
    report = run_smoke(
        output_dir=Path(args.output_dir),
        project_id=args.project_id,
        admin_url=args.admin_url,
        customer_url=args.customer_url,
        mobile=args.mobile,
    )
    print(json.dumps({"status": report["status"], "summary": report["summary"], "output_dir": args.output_dir}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
