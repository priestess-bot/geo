from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from urllib.parse import parse_qs, urlparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import httpx


ROOT = Path(__file__).resolve().parents[1]
AUTO_PORTS_ENV = ROOT / "tmp/docker-compose.auto-ports.env"
DEFAULT_PIPELINE_ARTIFACT = ROOT / "tmp/geo-production-full-pipeline-smoke/latest.json"
DEFAULT_OUTPUT = ROOT / "tmp/frontend-knowledge-lifecycle-smoke/latest.json"
ACTOR_ID = "runtime-console"
LAST_STEPS: list["Step"] = []
LAST_PROJECT_ID = ""


@dataclass(frozen=True)
class Step:
    name: str
    status: str
    detail: str
    duration_ms: int


def _read_auto_ports() -> dict[str, str]:
    if not AUTO_PORTS_ENV.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in AUTO_PORTS_ENV.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _base_urls(admin_url: str | None, api_base: str | None) -> tuple[str, str]:
    ports = _read_auto_ports()
    return (
        (admin_url or f"http://localhost:{ports.get('GEO_ADMIN_WEB_HOST_PORT', '18005')}").rstrip("/"),
        (api_base or f"http://localhost:{ports.get('GEO_API_HOST_PORT', '18003')}").rstrip("/"),
    )


def _project_id(explicit: str | None, artifact_path: Path) -> str:
    if explicit:
        return explicit
    if not artifact_path.exists():
        raise RuntimeError(f"full-pipeline artifact is missing: {artifact_path}")
    report = json.loads(artifact_path.read_text(encoding="utf-8"))
    live = report.get("live_pipeline") if isinstance(report.get("live_pipeline"), dict) else report
    project_id = str(live.get("project_id") or "")
    if not project_id:
        raise RuntimeError(f"full-pipeline artifact has no live project_id: {artifact_path}")
    return project_id


def _api_records(api_base: str, path: str, project_id: str, **filters: object) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{api_base}{path}",
        headers={"X-GEO-Actor-Id": ACTOR_ID},
        params={"project_id": project_id, "limit": 100, **filters},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    records = payload.get("records") if isinstance(payload, dict) else None
    return [dict(record) for record in records] if isinstance(records, list) else []


def _wait_reachable(url: str) -> None:
    deadline = time.monotonic() + 90
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=30)
            if response.status_code < 500:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(1)
    raise RuntimeError(f"service is not reachable: {url}: {last_error}")


def _run_worker(args: argparse.Namespace) -> None:
    command = ["docker", "compose", "-p", args.compose_project]
    env_file = ROOT / args.compose_env_file
    if env_file.exists():
        command.extend(["--env-file", str(env_file)])
    command.extend(
        [
            "-f",
            str(ROOT / "infra/docker-compose.yml"),
            "--profile",
            "knowledge",
            "run",
            "--rm",
            "--no-deps",
            "knowledge-worker",
            "python",
            "workers/knowledge_worker/run_knowledge_pipeline.py",
            "--max-jobs",
            "100",
            "--loop-once",
        ]
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
        timeout=args.worker_timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"knowledge worker failed: exit={completed.returncode}; "
            f"stdout={completed.stdout[-1500:]}; stderr={completed.stderr[-1500:]}"
        )


def _submit_form(page: Any, button_name: str, *, timeout: int = 45_000) -> str:
    button = page.get_by_role("button", name=button_name, exact=True).first
    if not button.is_visible(timeout=3000) or button.is_disabled():
        raise RuntimeError(f"frontend action is unavailable: {button_name}")
    form = button.locator("xpath=ancestor::form").first
    button.click()
    form.locator(".actionResult, .errorText").first.wait_for(state="visible", timeout=timeout)
    error = form.locator(".errorText").first
    if error.count() and error.is_visible(timeout=500):
        raise RuntimeError(f"frontend action failed ({button_name}): {error.inner_text()}")
    result = form.locator(".actionResult").first
    if not result.count():
        raise RuntimeError(f"frontend action returned no result: {button_name}")
    return result.inner_text(timeout=3000).strip()


def _record(steps: list[Step], name: str, operation: Callable[[], str]) -> None:
    started = time.monotonic()
    try:
        detail = operation()
    except Exception as exc:
        steps.append(Step(name, "fail", str(exc), int((time.monotonic() - started) * 1000)))
        raise
    steps.append(Step(name, "pass", detail, int((time.monotonic() - started) * 1000)))


def run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise RuntimeError("Python Playwright is required for the knowledge frontend lifecycle smoke") from exc

    started_at = datetime.now(UTC)
    admin_url, api_base = _base_urls(args.admin_url, args.api_base)
    project_id = _project_id(args.project_id, Path(args.pipeline_artifact))
    _wait_reachable(f"{admin_url}/projects/{project_id}?tab=knowledge&knowledge_tab=import")
    _wait_reachable(f"{api_base}/health")
    steps: list[Step] = []
    global LAST_PROJECT_ID, LAST_STEPS
    LAST_PROJECT_ID = project_id
    LAST_STEPS = steps
    screenshots = Path(args.output).parent / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        page = context.new_page()
        console_errors: list[str] = []
        http_failures: list[str] = []
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on(
            "response",
            lambda response: http_failures.append(f"{response.status} {response.url}")
            if response.status >= 500
            else None,
        )
        try:
            def open_route(route: str) -> None:
                page.goto(f"{admin_url}/projects/{project_id}{route}", wait_until="networkidle", timeout=30_000)
                if not page.locator("main").count() or not page.locator("main").inner_text().strip():
                    raise RuntimeError(f"blank project page: {route}")

            def import_text() -> str:
                open_route("?tab=knowledge&knowledge_tab=import")
                existing_pipeline_ids = {
                    str(record.get("id") or "")
                    for record in _api_records(
                        api_base,
                        "/v1/knowledge/pipeline-runs/runtime",
                        project_id,
                    )
                }
                page.locator("select[name='source_mode']").first.select_option("pasted_text")
                page.locator("input[name='title']").first.fill("Playwright knowledge lifecycle source")
                page.locator("textarea[name='source_text']").first.fill(
                    "KoalaHome provides free Sydney metro delivery over AUD 99 and a documented 30-day returns policy."
                )
                button = page.get_by_role("button", name="创建并启动 Pipeline", exact=True).first
                if not button.is_visible(timeout=3000) or button.is_disabled():
                    raise RuntimeError("frontend action is unavailable: 创建并启动 Pipeline")
                button.click()
                page.wait_for_url("**knowledge_tab=processing&pipeline_run_id=**", timeout=90_000)
                query = parse_qs(urlparse(page.url).query)
                pipeline_run_id = str((query.get("pipeline_run_id") or [""])[0])
                if not pipeline_run_id or pipeline_run_id in existing_pipeline_ids:
                    raise RuntimeError(f"frontend import did not create a new Pipeline: {page.url}")
                pipeline_records = _api_records(
                    api_base,
                    "/v1/knowledge/pipeline-runs/runtime",
                    project_id,
                )
                pipeline = next(
                    (record for record in pipeline_records if str(record.get("id") or "") == pipeline_run_id),
                    None,
                )
                if pipeline is None:
                    raise RuntimeError(f"redirected Pipeline is missing from runtime API: {pipeline_run_id}")
                if str(pipeline.get("status") or "") not in {"queued", "running", "waiting_human_review", "succeeded"}:
                    raise RuntimeError(
                        f"frontend-created Pipeline has an unexpected status: {pipeline.get('status')}"
                    )
                page.screenshot(path=str(screenshots / "01-import-started.png"), full_page=False)
                return f"frontend redirect and runtime Pipeline verified: {pipeline_run_id}"

            _record(steps, "frontend_import_precheck_and_start", import_text)
            _run_worker(args)

            def inspect_processing() -> str:
                open_route("?tab=knowledge&knowledge_tab=processing")
                body = page.locator("main").inner_text()
                for required in ("Pipeline", "Quality Gate", "Source Assets", "Parser Runs"):
                    if required not in body:
                        raise RuntimeError(f"processing page is missing {required}")
                page.screenshot(path=str(screenshots / "02-processing.png"), full_page=False)
                return "pipeline stages, jobs, assets and parser runs rendered"

            _record(steps, "frontend_view_pipeline_processing", inspect_processing)

            pending_facts = _api_records(
                api_base,
                "/v1/knowledge/fact-candidates/runtime",
                project_id,
                status="pending_review",
            )
            safe_fact = next(
                (
                    fact
                    for fact in pending_facts
                    if "fact_forbidden_claim" not in list((fact.get("metadata") or {}).get("quality_flags") or [])
                ),
                None,
            )
            if safe_fact is None:
                raise RuntimeError("knowledge worker produced no reviewable fact candidate")

            def review_fact() -> str:
                open_route("?tab=knowledge&knowledge_tab=quality")
                page.locator("select[name='fact_candidate_id']").first.select_option(str(safe_fact["id"]))
                page.locator("select[name='review_status']").first.select_option("approved")
                page.locator("textarea[name='notes']").first.fill("approved by frontend knowledge lifecycle smoke")
                detail = _submit_form(page, "保存候选审核")
                page.screenshot(path=str(screenshots / "03-fact-approved.png"), full_page=False)
                return detail

            _record(steps, "frontend_fact_candidate_review", review_fact)

            def create_prompt_job() -> str:
                open_route("?tab=prompts&prompt_tab=generate")
                template = page.locator("select[name='prompt_template_id']").first
                if template.locator("option:not([disabled])").count() < 1:
                    raise RuntimeError("no published Prompt generation template is available")
                template.select_option(index=1)
                page.locator("input[name='quantity']").first.fill("2")
                page.get_by_text("限定生成使用的知识范围", exact=True).first.click()
                source_fact_kind = str(safe_fact.get("fact_kind") or "")
                if source_fact_kind in {"brand", "competitor", "market", "source"}:
                    page.locator("select[name='source_fact_kind']").first.select_option(source_fact_kind)
                page.locator("input[name='source_market_code']").first.fill("AU")
                return _submit_form(page, "生成 Prompt 候选")

            _record(steps, "frontend_prompt_generation", create_prompt_job)
            _run_worker(args)
            pending_prompts = _api_records(
                api_base,
                "/v1/knowledge/prompt-candidates/runtime",
                project_id,
                status="pending_review",
            )
            if not pending_prompts:
                raise RuntimeError("Prompt generation produced no pending candidate")
            prompt_candidate = pending_prompts[0]

            def review_and_import_prompt() -> str:
                open_route("?tab=prompts&prompt_tab=candidates")
                page.locator("select[name='prompt_candidate_id']").first.select_option(str(prompt_candidate["id"]))
                page.locator("textarea[name='edited_text']").first.fill(
                    "Which Australian home brands publish verifiable delivery and returns policies?"
                )
                page.locator("select[name='review_status']").first.select_option("edited_approved")
                review_detail = _submit_form(page, "保存 Prompt 审核")
                page.locator("textarea[name='prompt_candidate_ids']").first.fill(str(prompt_candidate["id"]))
                page.locator("input[name='prompt_version']").first.fill("frontend_knowledge_lifecycle_v1")
                import_detail = _submit_form(page, "导入 Prompt")
                imported_candidates = _api_records(
                    api_base,
                    "/v1/knowledge/prompt-candidates/runtime",
                    project_id,
                    status="imported",
                )
                if not any(str(record.get("id") or "") == str(prompt_candidate["id"]) for record in imported_candidates):
                    raise RuntimeError("frontend-imported Prompt candidate is not marked imported by runtime API")
                page.screenshot(path=str(screenshots / "04-prompt-imported.png"), full_page=False)
                return f"{review_detail}; {import_detail}; runtime candidate status verified"

            _record(steps, "frontend_prompt_review_and_import", review_and_import_prompt)

            def create_content_job() -> str:
                open_route("?tab=operations&operation_tab=content")
                page.locator("select[name='content_type']").first.select_option("evidence_brief")
                page.locator("input[name='source_gap_type']").first.fill("weak_citation")
                return _submit_form(page, "生成 GEO 文案")

            _record(steps, "frontend_content_generation", create_content_job)
            _run_worker(args)
            pending_content = _api_records(
                api_base,
                "/v1/knowledge/content-drafts/runtime",
                project_id,
                status="pending_human_review",
            )
            if not pending_content:
                raise RuntimeError("content generation produced no pending draft")
            content_draft = pending_content[0]

            def review_and_export_content() -> str:
                open_route("?tab=operations&operation_tab=content")
                page.locator("select[name='content_draft_id']").first.select_option(str(content_draft["id"]))
                page.locator("select[name='review_status']").last.select_option("approved")
                review_detail = _submit_form(page, "保存内容审核")
                export_link = page.get_by_text("导出 Markdown", exact=True).first
                if not export_link.is_visible(timeout=5000):
                    page.reload(wait_until="networkidle")
                    export_link = page.get_by_text("导出 Markdown", exact=True).first
                with page.expect_download(timeout=30_000) as download_info:
                    export_link.click()
                download = download_info.value
                download_path = Path(args.output).parent / "approved-geo-content.md"
                download.save_as(str(download_path))
                if not download_path.read_text(encoding="utf-8").strip():
                    raise RuntimeError("approved GEO content Markdown download is empty")
                page.screenshot(path=str(screenshots / "05-content-approved.png"), full_page=False)
                return f"{review_detail}; Markdown downloaded"

            _record(steps, "frontend_content_review_and_export", review_and_export_content)

            def search_knowledge() -> str:
                open_route("?tab=knowledge&knowledge_tab=search")
                page.locator("input[name='knowledge_query']").first.fill("delivery returns")
                page.get_by_role("button", name="检索知识库", exact=True).first.click()
                page.wait_for_load_state("networkidle", timeout=10_000)
                if "knowledge_query=delivery" not in page.url:
                    raise RuntimeError(f"knowledge search query did not persist: {page.url}")
                page.screenshot(path=str(screenshots / "06-search.png"), full_page=False)
                return "knowledge search submitted through frontend"

            _record(steps, "frontend_knowledge_search", search_knowledge)
            actionable_console = [text for text in console_errors if "Failed to load resource" not in text]
            if actionable_console:
                raise RuntimeError(f"frontend console errors: {actionable_console[:5]}")
            if http_failures:
                raise RuntimeError(f"frontend HTTP 5xx responses: {http_failures[:5]}")
        finally:
            context.close()
            browser.close()

    report = {
        "run_id": f"frontend-knowledge-lifecycle-{started_at.strftime('%Y%m%d%H%M%S%f')}",
        "status": "passed" if steps and all(step.status == "pass" for step in steps) else "failed",
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "project_id": project_id,
        "admin_url": admin_url,
        "api_base": api_base,
        "browser_backend": "regular_playwright",
        "browser_plugin_reason": "Browser plugin was not available in this execution environment.",
        "steps": [asdict(step) for step in steps],
        "summary": {
            "pass": sum(step.status == "pass" for step in steps),
            "fail": sum(step.status == "fail" for step in steps),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real knowledge lifecycle through Admin Web controls.")
    parser.add_argument("--project-id")
    parser.add_argument("--pipeline-artifact", default=str(DEFAULT_PIPELINE_ARTIFACT))
    parser.add_argument("--admin-url")
    parser.add_argument("--api-base")
    parser.add_argument("--compose-project", default="geo-auto")
    parser.add_argument("--compose-env-file", default="tmp/docker-compose.auto-ports.env")
    parser.add_argument("--worker-timeout", type=int, default=1800)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    try:
        report = run(args)
    except Exception as exc:  # noqa: BLE001 - smoke runner must persist the top-level blocker.
        report = {
            "run_id": f"frontend-knowledge-lifecycle-failed-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
            "status": "failed",
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "project_id": LAST_PROJECT_ID,
            "steps": [asdict(step) for step in LAST_STEPS],
            "summary": {
                "pass": sum(step.status == "pass" for step in LAST_STEPS),
                "fail": max(1, sum(step.status == "fail" for step in LAST_STEPS)),
            },
            "error": str(exc),
        }
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary": report["summary"], "output": args.output}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
