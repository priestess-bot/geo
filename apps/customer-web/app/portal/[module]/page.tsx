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
  type PortalModule
} from "../../_components/PortalChrome";
import {
  loadCustomerGeoReadModel,
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
    return (
      <PortalAccessState
        detail={session.problem?.detail || "当前会话没有客户门户可见的项目。"}
        requestId={session.problem?.request_id}
        title={session.problem ? "项目加载失败" : "暂无授权项目"}
      />
    );
  }

  const model = await loadCustomerGeoReadModel(
    session.selectedProject.project_id,
    campaignId
  );
  return (
    <PortalChrome active={rawModule} problems={resourceProblems(model)} session={session}>
      {view(rawModule, model)}
    </PortalChrome>
  );
}

function view(
  module: PortalModule,
  model: Awaited<ReturnType<typeof loadCustomerGeoReadModel>>
) {
  if (module === "summary") return <SummaryView model={model} />;
  if (module === "metrics") return <MetricsView state={model.metrics} />;
  if (module === "placements") {
    return <PlacementsView urls={model.verifiedUrls} windows={model.windows} />;
  }
  return <ReportsView state={model.reports} />;
}

function isPortalModule(value: string): value is PortalModule {
  return MODULES.has(value as PortalModule);
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
