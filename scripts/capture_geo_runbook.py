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


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--admin-base", default="http://localhost:3001")
    value.add_argument("--customer-base", default="http://localhost:3000")
    value.add_argument("--project-id", required=True)
    value.add_argument("--output", type=Path, required=True)
    return value


def admin_pages(project_id: str) -> tuple[tuple[str, str], ...]:
    root = f"/projects/{project_id}/geo"
    return (
        ("03-admin-project-list", "/projects"),
        ("04-catalog-members", f"/projects/{project_id}"),
        ("06-campaign-monitoring", root),
        ("08-observations", f"{root}?{urlencode({'section': 'observations'})}"),
        ("07-destinations", f"{root}?{urlencode({'section': 'destinations'})}"),
        (
            "11-placement-generation",
            f"{root}?{urlencode({'section': 'placement', 'placement_stage': 'generation'})}",
        ),
        (
            "15-placement-publication",
            f"{root}?{urlencode({'section': 'placement', 'placement_stage': 'publication'})}",
        ),
    )


def capture(page: Page, *, name: str, url: str, viewport: str, output: Path) -> CaptureResult:
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
    )


def main() -> int:
    args = parser().parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results: list[CaptureResult] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for viewport, size in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
            context = browser.new_context(
                viewport={"width": size[0], "height": size[1]},
                device_scale_factor=1,
            )
            for name, path in admin_pages(args.project_id):
                results.append(
                    capture(
                        context.new_page(),
                        name=name,
                        url=f"{args.admin_base.rstrip('/')}{path}",
                        viewport=viewport,
                        output=args.output,
                    )
                )
            results.append(
                capture(
                    context.new_page(),
                    name="16-customer-entry",
                    url=args.customer_base,
                    viewport=viewport,
                    output=args.output,
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
