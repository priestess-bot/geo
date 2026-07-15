import Link from "next/link";
import { GeoShell } from "./features/geo/GeoShell";
import { loadGeoWorkspace } from "./features/geo/data";

type SearchParams = { [key: string]: string | string[] | undefined };

export default async function GeoPlacementPage({ params, searchParams }: {
  params: Promise<{ project_id: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const [{ project_id: projectId }, query] = await Promise.all([params, searchParams]);
  const data = await loadGeoWorkspace(projectId, query);
  return <main className="projectDetailPage">
    <div className="projectHeader">
      <div><p className="eyebrow">Admin Web / GEO</p><h1>GEO 投放工作区</h1>
        <p className="muted">从消费者查询和渠道资格，到证据约束文案、人工投放与 AI 搜索复测。</p></div>
      <Link className="button secondary" href={`/projects/${projectId}`}>返回项目工作台</Link>
    </div>
    <GeoShell projectId={projectId} data={data} />
  </main>;
}
