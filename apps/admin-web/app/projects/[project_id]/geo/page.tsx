import Link from "next/link";

import { runtimeRequest } from "../../../runtime";
import { GeoWorkspace } from "./GeoWorkspace";

type RecordItem = Record<string, unknown>;
type Page = { total_count: number; records: RecordItem[] };

const emptyPage: Page = { total_count: 0, records: [] };

async function load(path: string, projectId: string): Promise<Page> {
  const response = await runtimeRequest<Page>(path, { query: { project_id: projectId } });
  return response.ok && response.data ? response.data : emptyPage;
}

export default async function GeoPlacementPage({ params }: { params: Promise<{ project_id: string }> }) {
  const { project_id: projectId } = await params;
  const [products, campaigns, destinations, publishers, promptTemplates] = await Promise.all([
    load("/v1/geo/products", projectId), load("/v1/geo/campaigns", projectId),
    load("/v1/geo/destinations", projectId), load("/v1/geo/publishers", projectId), load("/v1/geo/prompt-templates", projectId)
  ]);
  const queryPages = await Promise.all(campaigns.records.map((campaign) => load(`/v1/geo/campaigns/${String(campaign.id)}/queries`, projectId)));
  const [observationPages, opportunityPages, packagePages, submissionPages, measurementPages] = await Promise.all([
    Promise.all(campaigns.records.map((campaign) => load(`/v1/geo/campaigns/${String(campaign.id)}/observations`, projectId))),
    Promise.all(campaigns.records.map((campaign) => load(`/v1/geo/campaigns/${String(campaign.id)}/placement-opportunities`, projectId))),
    Promise.all(campaigns.records.map((campaign) => load(`/v1/geo/campaigns/${String(campaign.id)}/placement-packages`, projectId))),
    Promise.all(campaigns.records.map((campaign) => load(`/v1/geo/campaigns/${String(campaign.id)}/submissions`, projectId))),
    Promise.all(campaigns.records.map((campaign) => load(`/v1/geo/campaigns/${String(campaign.id)}/measurements`, projectId)))
  ]);
  const queries: Page = { total_count: queryPages.reduce((total, page) => total + page.total_count, 0), records: queryPages.flatMap((page) => page.records) };
  const merge = (pages: Page[]): Page => ({ total_count: pages.reduce((total, page) => total + page.total_count, 0), records: pages.flatMap((page) => page.records) });
  const opportunities = merge(opportunityPages);
  const observations = merge(observationPages);
  const packages = merge(packagePages);
  const submissions = merge(submissionPages);
  const measurements = merge(measurementPages);
  return <main className="projectDetailPage">
    <div className="projectHeader"><div><p className="eyebrow">Admin Web / GEO Placement</p><h1>GEO 投放工作区</h1><p className="muted">从商品与查询到渠道任务、审核、人工提交与公开验证。</p></div><Link className="button secondary" href={`/projects/${projectId}`}>返回项目工作台</Link></div>
    <GeoWorkspace campaigns={campaigns} destinations={destinations} measurements={measurements} observations={observations} opportunities={opportunities} packages={packages} products={products} promptTemplates={promptTemplates} publishers={publishers} queries={queries} projectId={projectId} submissions={submissions} />
  </main>;
}
