import { notFound } from "next/navigation";

import {
  MetricsView,
  PlacementsView,
  ReportsView,
  SummaryView
} from "../../_components/GeoViews";
import {
  PortalAccessState,
  PortalChrome,
  PortalSelectionState,
  type PortalModule
} from "../../_components/PortalChrome";
import {
  loadCampaignPortal,
  loadCustomerGeoReadModel,
  loadCustomerWorkflowCReports,
  loadSessionPortal,
  resourceProblems
} from "../../runtime";

const MODULES = new Set<PortalModule>(["summary", "metrics", "placements", "reports"]);

export default async function PortalModulePage({
  params,
  searchParams
}: Readonly<{
  params: Promise<{ module: string }>;
  searchParams?: Promise<{ [key: string]: string | string[] | undefined }>;
}>) {
  const [{ module: rawModule }, query] = await Promise.all([params, searchParams]);
  if (!isPortalModule(rawModule)) notFound();

  const requestedProjectId = first(query?.project_id);
  const campaignId = first(query?.campaign_id);
  const session = await loadSessionPortal(requestedProjectId);
  if (!session.authenticated) {
    return (
      <PortalAccessState
        detail="客户会话已失效或尚未登录。"
        requestId={session.problem?.request_id}
        title="需要登录"
      />
    );
  }
  if (!session.selectedProject) {
    if (session.selectionStatus === "empty" || session.selectionStatus === "error") {
      return (
        <PortalAccessState
          detail={session.problem?.detail || "当前会话没有客户门户可见的项目。"}
          requestId={session.problem?.request_id}
          title={session.problem ? "项目加载失败" : "暂无授权项目"}
        />
      );
    }
    return (
      <PortalChrome
        active={rawModule}
        campaignPortal={null}
        problems={[]}
        session={session}
      >
        <PortalSelectionState
          detail={session.selectionStatus === "unauthorized"
            ? "请求的项目不在当前客户会话授权范围内。"
            : "请从授权项目中选择一个项目。"}
          title={session.selectionStatus === "unauthorized" ? "无权访问所选项目" : "未选择项目"}
        />
      </PortalChrome>
    );
  }

  const campaignPortal = await loadCampaignPortal(
    session.selectedProject.project_id,
    campaignId
  );
  if (!campaignPortal.selectedCampaign) {
    const problem = campaignPortal.problem ? [campaignPortal.problem] : [];
    const state = campaignSelectionState(campaignPortal.selectionStatus);
    return (
      <PortalChrome
        active={rawModule}
        campaignPortal={campaignPortal}
        problems={problem}
        session={session}
      >
        <PortalSelectionState detail={state.detail} title={state.title} />
      </PortalChrome>
    );
  }

  const projectId = session.selectedProject.project_id;
  const selectedCampaignId = campaignPortal.selectedCampaign.id;
  const modelPromise = loadCustomerGeoReadModel(projectId, selectedCampaignId);
  const workflowCReportsPromise = moduleUsesWorkflowCReports(rawModule)
    ? loadCustomerWorkflowCReports(projectId, selectedCampaignId)
    : null;
  let model: Awaited<ReturnType<typeof loadCustomerGeoReadModel>>;
  let workflowCReports: Awaited<ReturnType<typeof loadCustomerWorkflowCReports>> | null;
  if (workflowCReportsPromise) {
    [model, workflowCReports] = await Promise.all([modelPromise, workflowCReportsPromise]);
  } else {
    model = await modelPromise;
    workflowCReports = null;
  }
  return (
    <PortalChrome
      active={rawModule}
      campaignPortal={campaignPortal}
      problems={workflowCReports
        ? resourceProblems(model, workflowCReports)
        : resourceProblems(model)}
      session={session}
    >
      {view(rawModule, model, workflowCReports)}
    </PortalChrome>
  );
}

function view(
  module: PortalModule,
  model: Awaited<ReturnType<typeof loadCustomerGeoReadModel>>,
  workflowCReports: Awaited<ReturnType<typeof loadCustomerWorkflowCReports>> | null
) {
  if (module === "summary") {
    return <SummaryView model={model} workflowCReports={requiredWorkflowCReports(workflowCReports)} />;
  }
  if (module === "metrics") return <MetricsView model={model} />;
  if (module === "placements") return <PlacementsView model={model} />;
  return <ReportsView model={model} workflowCReports={requiredWorkflowCReports(workflowCReports)} />;
}

function moduleUsesWorkflowCReports(module: PortalModule): boolean {
  return module === "summary" || module === "reports";
}

function requiredWorkflowCReports(
  reports: Awaited<ReturnType<typeof loadCustomerWorkflowCReports>> | null
): Awaited<ReturnType<typeof loadCustomerWorkflowCReports>> {
  if (!reports) throw new Error("Workflow C reports were not loaded for this portal module");
  return reports;
}

function campaignSelectionState(status: string): Readonly<{ detail: string; title: string }> {
  if (status === "unauthorized") {
    return {
      detail: "请求的 Campaign 不在当前项目的客户可见范围内。",
      title: "无权访问所选 Campaign"
    };
  }
  if (status === "empty") {
    return { detail: "当前项目尚未建立 Campaign。", title: "暂无 Campaign" };
  }
  if (status === "error") {
    return { detail: "Campaign 列表暂时无法读取。", title: "Campaign 加载失败" };
  }
  return { detail: "请从当前项目中选择一个 Campaign。", title: "未选择 Campaign" };
}

function isPortalModule(value: string): value is PortalModule {
  return MODULES.has(value as PortalModule);
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
