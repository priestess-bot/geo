import { expect, test } from "@playwright/test";

const FIXTURE_API = process.env.PLAYWRIGHT_FIXTURE_API_URL || "http://127.0.0.1:3199";
const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const MAX_FILE_BYTES = 5 * 1024 * 1024;

test("Knowledge upload accepts 5 MiB and rejects the next byte", async ({ page, request }) => {
  test.setTimeout(60_000);
  expect((await request.delete(`${FIXTURE_API}/__requests`)).ok()).toBe(true);

  await page.goto(`/projects/${PROJECT_ID}?tab=knowledge&knowledge_tab=import`);
  let uploadForm = page.locator("form").filter({
    has: page.getByRole("button", { name: "上传文件" })
  });
  await uploadForm.getByLabel("来源标题").fill("Five MiB boundary fixture");
  await uploadForm.getByLabel("文件").setInputFiles({
    name: "at-limit.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(MAX_FILE_BYTES, 0x61)
  });
  await uploadForm.getByRole("button", { name: "上传文件" }).click();
  await expect(page).toHaveURL(/knowledge_tab=processing/);

  // Release the large captured API payload before checking the rejection path.
  expect((await request.delete(`${FIXTURE_API}/__requests`)).ok()).toBe(true);
  await page.goto(`/projects/${PROJECT_ID}?tab=knowledge&knowledge_tab=import`);
  uploadForm = page.locator("form").filter({
    has: page.getByRole("button", { name: "上传文件" })
  });
  await uploadForm.getByLabel("来源标题").fill("Over boundary fixture");
  await uploadForm.getByLabel("文件").setInputFiles({
    name: "over-limit.txt",
    mimeType: "text/plain",
    buffer: Buffer.alloc(MAX_FILE_BYTES + 1, 0x61)
  });
  await uploadForm.getByRole("button", { name: "上传文件" }).click();

  await expect(uploadForm.getByRole("alert")).toHaveText("文件不能超过 5 MB。");
  const writes = await (await request.get(`${FIXTURE_API}/__requests`)).json() as Array<{
    method: string;
    path: string;
  }>;
  expect(writes.some((item) => item.method === "POST"
    && item.path.endsWith("/knowledge/sources"))).toBe(false);
});
