from pathlib import Path

from playwright.sync_api import sync_playwright


PROJECT_ID = "f981915e-945a-5e1e-b1ff-4c5a55d31461"
URL = f"http://localhost:3001/projects/{PROJECT_ID}/geo"
SCREENSHOT = Path("docs/runtime_preflight/geo-v3-admin-workspace.png")
RESPONSIVE_SCREENSHOTS = (
    (900, 1000, Path("docs/runtime_preflight/geo-v3-admin-workspace-tablet.png")),
    (390, 844, Path("docs/runtime_preflight/geo-v3-admin-workspace-mobile.png")),
)


def main() -> None:
    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        # Next development mode keeps a hot-reload connection open, so
        # networkidle never becomes a meaningful readiness signal.
        page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
        page.get_by_role("heading", name="GEO 投放工作区").wait_for(timeout=15_000)
        page.get_by_role("heading", name="建立渠道投放任务").wait_for(timeout=15_000)
        page.get_by_role("heading", name="导入基线/复测观察").wait_for(timeout=15_000)
        page.get_by_role("heading", name="渠道准备度").wait_for(timeout=15_000)
        page.get_by_text("DeepSeek 文案生成", exact=True).wait_for(timeout=15_000)
        page.get_by_role("heading", name="独立 Reviewer 决定").wait_for(timeout=15_000)
        page.get_by_role("heading", name="创建修订版本").wait_for(timeout=15_000)
        page.get_by_role("heading", name="本轮交付停在 approved").wait_for(timeout=15_000)
        assert page.get_by_text("Prompt Bundle", exact=False).count() > 0
        assert page.get_by_text("supported", exact=False).count() > 0
        with page.expect_download(timeout=15_000) as download_info:
            page.get_by_role("button", name="下载 Markdown 文案包").first.click()
        download = download_info.value
        assert download.suggested_filename.endswith(".md")
        page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOT), full_page=True)
        assert SCREENSHOT.exists() and SCREENSHOT.stat().st_size > 10_000
        browser.close()
        for width, height, screenshot in RESPONSIVE_SCREENSHOTS:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
            page.get_by_role("heading", name="渠道准备度").wait_for(timeout=15_000)
            page.get_by_role("heading", name="本轮交付停在 approved").wait_for(timeout=15_000)
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            assert overflow <= 1, f"horizontal overflow at {width}px: {overflow}px"
            page.screenshot(path=str(screenshot), full_page=True)
            assert screenshot.exists() and screenshot.stat().st_size > 10_000
            browser.close()


if __name__ == "__main__":
    main()
