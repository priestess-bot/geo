import { CampaignWorkspace } from "./CampaignWorkspace";
import { DestinationWorkspace } from "./DestinationWorkspace";
import { entityName, marketName } from "./display";
import { geoHref, Status } from "./common";
import type { GeoSection, GeoWorkspaceData } from "./model";
import { ObservationWorkspace } from "./ObservationWorkspace";
import { PlacementWorkspace } from "./PlacementWorkspace";
import { RouteSelect } from "./RouteSelect";
import styles from "./GeoWorkspace.module.css";
import type { CatalogLoadResult } from "../../../catalogTypes";

export function GeoShell({ projectId, data, catalog }: { projectId: string; data: GeoWorkspaceData; catalog: CatalogLoadResult }) {
  const tabs: Array<{ id: GeoSection; label: string }> = [
    { id: "campaigns", label: "Campaign 总览" }, { id: "observations", label: "AI 观察" },
    { id: "destinations", label: "渠道计划" }, { id: "placement", label: "内容生产" }
  ];
  const campaign = data.campaigns.data.find((item) => item.id === data.selection.campaignId);
  const readiness = readinessState(data);
  const campaignOptions = data.campaigns.data.map((item) => ({
    value: item.id,
    label: item.name,
    href: geoHref(projectId, data.selection, {
      campaign_id: item.id, opportunity_id: undefined, brief_version_id: undefined,
      attempt_id: undefined, bundle_id: undefined, version_id: undefined
    })
  }));
  return <div className={styles.shell}>
    <section className={styles.commandCenter}>
      <div className={styles.contextMain}>
        {campaignOptions.length ? <RouteSelect label="当前 Campaign" options={campaignOptions} value={campaign?.id} /> : <strong>尚未创建 Campaign</strong>}
        <div className={styles.contextMeta}>
          <span>{entityName(catalog.entities.data, campaign?.primary_product_entity_id)}</span>
          <span>{marketName(catalog.markets.data, campaign?.market_profile_id)}</span>
          {campaign ? <Status value={campaign.status} /> : null}
        </div>
      </div>
      <div className={styles.progressBlock}>
        <div><span>工作流完成度</span><strong>{readiness.complete}/5</strong></div>
        <div className={styles.progressTrack}><span style={{ width: `${readiness.complete * 20}%` }} /></div>
      </div>
      <a className={styles.nextAction} href={geoHref(projectId, data.selection, readiness.updates)}>
        <span>下一步</span><strong>{readiness.label}</strong>
      </a>
    </section>

    <nav className={styles.primaryNav} aria-label="GEO 工作区">{tabs.map((tab) => <a key={tab.id}
      className={data.selection.section === tab.id ? styles.active : ""}
      href={geoHref(projectId, data.selection, { section: tab.id })}>{tab.label}</a>)}</nav>

    {data.selection.section === "campaigns" ? <CampaignWorkspace projectId={projectId} data={data} catalog={catalog} /> : null}
    {data.selection.section === "observations" ? <ObservationWorkspace projectId={projectId} data={data} /> : null}
    {data.selection.section === "destinations" ? <DestinationWorkspace projectId={projectId} data={data} /> : null}
    {data.selection.section === "placement" ? <PlacementWorkspace projectId={projectId} data={data} catalog={catalog} /> : null}
  </div>;
}

function readinessState(data: GeoWorkspaceData): {
  complete: number; label: string; updates: { [key: string]: string | undefined };
} {
  const checks = [data.queries.data.length > 0, data.protocols.data.length > 0,
    data.destinations.data.length >= 9, data.briefs.data.length > 0, data.packages.data.length > 0];
  if (!checks[0]) return { complete: 0, label: "添加消费者问题", updates: { section: "campaigns" } };
  if (!checks[1]) return { complete: 1, label: "建立监测方案", updates: { section: "campaigns" } };
  if (!checks[2]) return { complete: 2, label: "补齐渠道任务", updates: { section: "destinations" } };
  if (!checks[3]) return { complete: 3, label: "准备内容要求", updates: { section: "placement", placement_stage: "brief" } };
  if (!checks[4]) return { complete: 4, label: "生成并审核文案", updates: { section: "placement", placement_stage: "generation" } };
  return { complete: 5, label: "查看发布任务", updates: { section: "placement", placement_stage: "publication" } };
}
