export const workbenchTabs = [
  { id: "basic", label: "基础配置" },
  { id: "entry", label: "用户入口" },
  { id: "prompts", label: "Prompt Programs" },
  { id: "secrets", label: "Secret Store" },
  { id: "synthetic-lab", label: "Synthetic Lab" },
  { id: "recommendations", label: "Recommendations" },
  { id: "measurement", label: "Measurement & Alerts" },
  { id: "knowledge", label: "知识库" },
  { id: "operations", label: "运营工作台" },
  { id: "geo", label: "GEO 投放" },
  { id: "status", label: "项目状态" },
  { id: "e2e", label: "全流程测试" }
] as const;

export type WorkbenchTab = (typeof workbenchTabs)[number]["id"];

export function normalizeWorkbenchTab(value: string | undefined): WorkbenchTab {
  return workbenchTabs.some((tab) => tab.id === value) ? value as WorkbenchTab : "basic";
}

export function workbenchHref(projectId: string, tab: WorkbenchTab): string {
  const params = new URLSearchParams();
  params.set("tab", tab);
  return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
}
