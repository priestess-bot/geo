#!/usr/bin/env python3
"""Capture responsive GEO UI evidence and fail on browser/runtime regressions."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Page, sync_playwright


@dataclass(frozen=True)
class CaptureResult:
    name: str
    url: str
    viewport: str
    screenshot: str
    console_errors: tuple[str, ...]
    page_errors: tuple[str, ...]
    failed_responses: tuple[str, ...]
    horizontal_overflow: bool
    mode: str


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--admin-base", default="http://localhost:3001")
    value.add_argument("--customer-base", default="http://localhost:3000")
    value.add_argument("--project-id", required=True)
    value.add_argument("--acceptance-result", type=Path)
    value.add_argument("--customer-invitation", type=Path)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--mode", choices=("actual", "simulation"), required=True)
    return value


def acceptance_selection(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    campaign = result["campaign"]
    placement = result["placement"]
    completed = next(
        channel for channel in result["channels"] if channel["task_status"] == "completed"
    )
    return {
        "campaign_id": campaign["campaign_id"],
        "protocol_id": campaign["protocol_id"],
        "destination_id": completed["destination_id"],
        "opportunity_id": completed["opportunity_id"],
        "brief_version_id": placement["brief_version_id"],
        "attempt_id": placement["evidence_pack_attempt_id"],
        "bundle_id": placement["prompt_bundle_id"],
        "job_id": placement["generation_job_id"],
        "version_id": placement["package_version_id"],
        "publication_id": placement["publication_request_id"],
        "submission_id": placement["submission_id"],
        "simulation_id": (placement.get("prompt_simulation_ids") or [""])[0],
    }


def selected_path(root: str, selection: dict[str, str], **updates: str) -> str:
    return f"{root}?{urlencode({**selection, **updates})}"


def admin_pages(
    project_id: str, selection: dict[str, str]
) -> tuple[tuple[str, str], ...]:
    root = f"/projects/{project_id}"
    return (
        ("03-admin-project-list", "/projects"),
        ("04-catalog-members", f"/projects/{project_id}"),
        *tuple(
            (
                f"05-knowledge-{view}",
                f"{root}?{urlencode({'tab': 'knowledge', 'knowledge_tab': view})}",
            )
            for view in (
                "import", "processing", "chunks", "search", "dashboard", "quality", "trace"
            )
        ),
        ("06-campaign-monitoring", selected_path(root, selection, tab="geo", geo_section="campaigns")),
        (
            "08-observations",
            selected_path(root, selection, tab="geo", geo_section="observations", measurement_window="t28"),
        ),
        ("07-destinations", selected_path(root, selection, tab="geo", geo_section="destinations")),
        (
            "09-placement-brief",
            selected_path(root, selection, tab="geo", geo_section="placement", placement_stage="brief"),
        ),
        (
            "10-placement-evidence",
            selected_path(root, selection, tab="geo", geo_section="placement", placement_stage="evidence"),
        ),
        (
            "12-placement-review",
            selected_path(root, selection, tab="geo", geo_section="placement", placement_stage="review"),
        ),
        (
            "11-placement-generation",
            selected_path(
                root, selection, tab="geo", geo_section="placement", placement_stage="generation"
            ),
        ),
        (
            "14-placement-simulation",
            selected_path(root, selection, tab="geo", geo_section="placement", placement_stage="simulation"),
        ),
        (
            "15-placement-publication",
            selected_path(
                root, selection, tab="geo", geo_section="placement", placement_stage="publication"
            ),
        ),
    )


def customer_pages(project_id: str) -> tuple[tuple[str, str], ...]:
    project = urlencode({"project_id": project_id})
    return (
        ("16-customer-summary", "/"),
        ("17-customer-metrics", f"/portal/metrics?{project}"),
        ("18-customer-placements", f"/portal/placements?{project}"),
        ("19-customer-reports", f"/portal/reports?{project}"),
    )


def redeem_customer_session(page: Page, *, base_url: str, invitation: Path) -> None:
    credential = json.loads(invitation.read_text(encoding="utf-8"))
    page.goto(base_url, wait_until="networkidle")
    page.locator('input[name="invitation_id"]').fill(credential["invitation"]["id"])
    page.locator('input[name="invite_token"]').fill(credential["invite_token"])
    page.get_by_role("button", name="兑换邀请并登录").click()
    page.locator('nav[aria-label="客户门户视图"]').wait_for()


def capture(
    page: Page, *, name: str, url: str, viewport: str, output: Path, mode: str
) -> CaptureResult:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_responses: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "response",
        lambda response: (
            failed_responses.append(f"{response.status} {response.url}")
            if response.status >= 500
            else None
        ),
    )
    page.goto(url, wait_until="networkidle")
    page.locator("body").wait_for(state="visible")
    body_text = page.locator("body").inner_text()
    for semantic_failure in ("项目不存在", "项目加载失败", "Application error"):
        if semantic_failure in body_text:
            page_errors.append(f"semantic failure: {semantic_failure}")
    overflow = bool(
        page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
        )
    )
    target = output / f"{name}-{viewport}.png"
    page.screenshot(path=str(target), full_page=True)
    return CaptureResult(
        name,
        url,
        viewport,
        str(target),
        tuple(console_errors),
        tuple(page_errors),
        tuple(failed_responses),
        overflow,
        mode,
    )


def main() -> int:
    args = parser().parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    selection = acceptance_selection(args.acceptance_result)
    results: list[CaptureResult] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for viewport, size in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
            context = browser.new_context(
                viewport={"width": size[0], "height": size[1]},
                device_scale_factor=1,
            )
            for name, path in admin_pages(args.project_id, selection):
                results.append(
                    capture(
                        context.new_page(),
                        name=name,
                        url=f"{args.admin_base.rstrip('/')}{path}",
                        viewport=viewport,
                        output=args.output,
                        mode=args.mode,
                    )
                )
            if args.customer_invitation:
                login_page = context.new_page()
                redeem_customer_session(
                    login_page,
                    base_url=args.customer_base,
                    invitation=args.customer_invitation,
                )
                login_page.close()
                for name, path in customer_pages(args.project_id):
                    results.append(
                        capture(
                            context.new_page(),
                            name=name,
                            url=f"{args.customer_base.rstrip('/')}{path}",
                            viewport=viewport,
                            output=args.output,
                            mode=args.mode,
                        )
                    )
            else:
                results.append(
                    capture(
                        context.new_page(),
                        name="16-customer-entry",
                        url=args.customer_base,
                        viewport=viewport,
                        output=args.output,
                        mode=args.mode,
                    )
                )
            context.close()
        browser.close()
    report = args.output / "browser-report.json"
    report.write_text(
        json.dumps([asdict(result) for result in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    failures = [
        result
        for result in results
        if result.console_errors
        or result.page_errors
        or result.failed_responses
        or result.horizontal_overflow
    ]
    print(f"captured {len(results)} views; report={report}; failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
