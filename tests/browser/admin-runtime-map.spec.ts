import { expect, test, type Page } from "@playwright/test";

function collectRuntimeErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

test("Admin 运行地图嵌入唯一架构快照并支持四个视图和独立宽高缩放", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  const homeResponse = await page.goto("/", { waitUntil: "domcontentloaded" });

  expect(homeResponse?.ok()).toBe(true);
  await page.getByRole("link", { name: /查看运行地图/ }).click();
  await expect(page).toHaveURL(/\/runtime-map$/);
  await expect(page.getByRole("heading", { level: 1, name: "运行地图" })).toBeVisible();

  const documentResponse = await page.request.get("/runtime-map/document");
  expect(documentResponse.ok()).toBe(true);
  expect(documentResponse.headers()["cache-control"]).toBe("no-store");
  expect(documentResponse.headers()["content-security-policy"]).toContain("frame-ancestors 'self'");
  expect(documentResponse.headers()["x-frame-options"]).toBe("SAMEORIGIN");

  const map = page.frameLocator('iframe[title="GEO 项目运行地图"]');
  await expect(map.getByRole("heading", { level: 2, name: "ADVINSYS Australia" })).toBeVisible();
  await expect(map.locator("body")).toHaveClass("admin-embedded");
  await expect(map.locator(".app-header")).toHaveCSS("display", "none");
  const detailLink = map.getByRole("link", { name: "打开对应工作区" });
  await expect(detailLink).toHaveAttribute("href", /^\/projects\//);
  await map.getByRole("button", { name: /测试问题与 QuestionSet/ }).click();
  await expect(map.locator("#detail-status")).toContainText("SAT30 已冻结");
  await expect(map.locator("#detail-fact")).toContainText("SAT30 v2 frozen：100/100");
  await expect(detailLink).toHaveAttribute("href", /tab=measurement.*workflow_view=questions/);

  await page.screenshot({ path: testInfo.outputPath("runtime-map-business-desktop.png"), fullPage: true });

  await map.getByRole("tab", { name: "任务链路" }).click();
  await expect(map.getByLabel("所选任务摘要")).toBeVisible();
  await map.getByLabel("选择真实运行").selectOption("test-questions");
  await expect(map.locator("#trace-business-status")).toHaveText("frozen");
  await expect(map.locator("#trace-grid")).toContainText("QuestionSet 冻结");
  await expect(map.locator("#trace-grid .trace-step")).toHaveCount(10);
  await page.screenshot({ path: testInfo.outputPath("runtime-map-question-trace-desktop.png"), fullPage: true });
  await map.getByLabel("选择真实运行").selectOption("simulation");
  await expect(map.locator("#trace-business-status")).toHaveText("TEST ONLY");
  await page.screenshot({ path: testInfo.outputPath("runtime-map-trace-desktop.png"), fullPage: true });

  await map.getByRole("tab", { name: "调用拓扑" }).click();
  await map.getByLabel("调用场景").selectOption("browser-capture");
  const edgePaths = map.locator(".topology-edge-line");
  expect(await edgePaths.count()).toBeGreaterThan(0);
  const edgePathCommands = await edgePaths.evaluateAll((paths) => paths.map((path) => path.getAttribute("d") || ""));
  expect(edgePathCommands.every((path) => /\bC\b/.test(path) && !/\bL\b/.test(path))).toBe(true);
  const widthScale = map.getByLabel("拓扑宽度缩放比例");
  const heightScale = map.getByLabel("拓扑高度缩放比例");
  const canvas = map.locator("#runtime-topology-canvas");
  const workerNode = map.locator('[data-topology-node="browser-capture-worker"]');
  const stickyLabel = map.locator(".topology-edge-label").filter({ hasText: "HTTPS 粘性会话" });
  const baselineNodeBox = await workerNode.boundingBox();
  const baselineLabelBox = await stickyLabel.boundingBox();
  expect(baselineNodeBox).not.toBeNull();
  expect(baselineLabelBox).not.toBeNull();

  await widthScale.selectOption("500");
  await expect(widthScale).toHaveValue("500");
  await expect(heightScale).toHaveValue("100");
  await expect(canvas).toHaveCSS("transform", "matrix(5, 0, 0, 1, 0, 0)");
  expect(Math.round((await workerNode.boundingBox())?.width || 0)).toBe(Math.round(baselineNodeBox?.width || 0));
  expect(Math.round((await stickyLabel.boundingBox())?.width || 0)).toBe(Math.round(baselineLabelBox?.width || 0));

  await heightScale.selectOption("500");
  await expect(canvas).toHaveCSS("transform", "matrix(5, 0, 0, 5, 0, 0)");
  await expect(map.locator(".topology-edge-label text").filter({ hasText: "HTTPS 粘性会话" })).toHaveCount(1);
  expect(Math.round((await workerNode.boundingBox())?.height || 0)).toBe(Math.round(baselineNodeBox?.height || 0));
  expect(Math.round((await stickyLabel.boundingBox())?.height || 0)).toBe(Math.round(baselineLabelBox?.height || 0));

  await widthScale.selectOption("100");
  await expect(widthScale).toHaveValue("100");
  await expect(heightScale).toHaveValue("500");
  await expect(canvas).toHaveCSS("transform", "matrix(1, 0, 0, 5, 0, 0)");
  expect(runtimeErrors).toEqual([]);

  await page.screenshot({ path: testInfo.outputPath("runtime-map-topology-desktop.png"), fullPage: true });

  await map.getByRole("tab", { name: "系统健康" }).click();
  await expect(map.getByText("运行健康只证明进程和依赖可用")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("runtime-map-health-desktop.png"), fullPage: true });

  await map.getByRole("tab", { name: "业务全景" }).click();
  await detailLink.click();
  await expect(page).toHaveURL((url) => (
    /^\/projects\/[^/]+$/.test(url.pathname)
    && url.searchParams.get("tab") === "measurement"
    && url.searchParams.get("workflow_view") === "questions"
  ));
});

test("Admin 运行地图在移动视口使用可操作的关系清单", async ({ page }, testInfo) => {
  const runtimeErrors = collectRuntimeErrors(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/runtime-map", { waitUntil: "domcontentloaded" });

  const map = page.frameLocator('iframe[title="GEO 项目运行地图"]');
  await map.getByRole("tab", { name: "调用拓扑" }).click();
  await expect(map.locator(".topology-axis-scales")).toHaveCSS("display", "none");
  await expect(map.locator("[data-mobile-topology-edge]").first()).toBeVisible();
  await map.locator("[data-mobile-topology-edge]").first().click();
  await expect(map.locator("#topology-inspector")).toHaveClass(/mobile-open/);

  const parentOverflow = await page.locator("html").evaluate(
    (element) => element.scrollWidth > element.clientWidth
  );
  const mapOverflow = await map.locator("html").evaluate(
    (element) => element.scrollWidth > element.clientWidth
  );
  expect(parentOverflow).toBe(false);
  expect(mapOverflow).toBe(false);
  expect(runtimeErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("runtime-map-topology-mobile.png"), fullPage: true });
});
