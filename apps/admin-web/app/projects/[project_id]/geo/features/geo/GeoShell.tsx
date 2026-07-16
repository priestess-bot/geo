import Link from "next/link";
import { CampaignWorkspace } from "./CampaignWorkspace";
import { DestinationWorkspace } from "./DestinationWorkspace";
import { geoHref } from "./common";
import type { GeoSection, GeoWorkspaceData } from "./model";
import { ObservationWorkspace } from "./ObservationWorkspace";
import { PlacementWorkspace } from "./PlacementWorkspace";
import styles from "./GeoWorkspace.module.css";
import type { CatalogLoadResult } from "../../../catalogTypes";

export function GeoShell({ projectId, data, catalog }: { projectId: string; data: GeoWorkspaceData; catalog: CatalogLoadResult }) {
  const tabs: Array<{ id: GeoSection; label: string }> = [
    { id: "campaigns", label: "Campaign 与监测" }, { id: "observations", label: "观察样本" },
    { id: "destinations", label: "渠道与机会" }, { id: "placement", label: "文案投放" }
  ];
  return <div className={styles.shell}>
    <div className={styles.summary}>
      <div className={styles.metric}><span>Campaign</span><strong>{data.campaigns.data.length}</strong></div>
      <div className={styles.metric}><span>渠道任务</span><strong>{data.destinations.data.length}</strong></div>
      <div className={styles.metric}><span>投放机会</span><strong>{data.opportunities.data.length}</strong></div>
      <div className={styles.metric}><span>当前窗口观察</span><strong>{data.observations.data.length}</strong></div>
      <div className={styles.metric}><span>当前请求验证</span><strong>{data.submissions.data.filter((item) => item.status === "verified").length}</strong></div>
    </div>
    <nav className={styles.tabs} aria-label="GEO 工作区">{tabs.map((tab) => <Link key={tab.id}
      className={data.selection.section === tab.id ? styles.active : ""}
      href={geoHref(projectId, data.selection, { section: tab.id })}>{tab.label}</Link>)}</nav>
    {data.selection.section === "campaigns" ? <CampaignWorkspace projectId={projectId} data={data} /> : null}
    {data.selection.section === "observations" ? <ObservationWorkspace projectId={projectId} data={data} /> : null}
    {data.selection.section === "destinations" ? <DestinationWorkspace projectId={projectId} data={data} /> : null}
    {data.selection.section === "placement" ? <PlacementWorkspace projectId={projectId} data={data} catalog={catalog} /> : null}
  </div>;
}
