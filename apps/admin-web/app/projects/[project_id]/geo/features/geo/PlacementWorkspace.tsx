import { BriefPromptPanel } from "./BriefPromptPanel";
import { channelLabel, opportunityName } from "./display";
import { geoHref, Status } from "./common";
import { GenerationPackagePanel } from "./GenerationPackagePanel";
import type { GeoWorkspaceData } from "./model";
import { PublicationPanel } from "./PublicationPanel";
import { PromptSimulationPanel } from "./PromptSimulationPanel";
import { RouteSelect } from "./RouteSelect";
import type { CatalogLoadResult } from "../../../catalogTypes";
import styles from "./GeoWorkspace.module.css";

const stages = [
  { id: "brief", number: "1", label: "内容要求" },
  { id: "evidence", number: "2", label: "证据与规则" },
  { id: "generation", number: "3", label: "生成文案" },
  { id: "review", number: "4", label: "审核定稿" },
  { id: "publication", number: "5", label: "发布与测量" }
] as const;

export function PlacementWorkspace({ projectId, data, catalog }: { projectId: string; data: GeoWorkspaceData; catalog: CatalogLoadResult }) {
  const { selection } = data;
  const opportunity = data.opportunities.data.find((item) => item.id === selection.opportunityId);
  const destination = data.destinations.data.find((item) => item.id === opportunity?.destination_id);
  const opportunityOptions = data.opportunities.data.map((item) => ({
    value: item.id,
    label: `${opportunityName(data.opportunities.data, data.destinations.data, item.id)} · ${item.status === "blocked" ? "受阻" : "可处理"}`,
    href: geoHref(projectId, selection, {
      opportunity_id: item.id, destination_id: undefined, brief_version_id: undefined,
      attempt_id: undefined, bundle_id: undefined, job_id: undefined, version_id: undefined,
      publication_id: undefined, submission_id: undefined, simulation_id: undefined,
      placement_stage: "brief"
    })
  }));
  return <section className={styles.workspace}>
    <header className={styles.pageHeading}><div><h2>内容生产</h2><p>为一个明确的产品和渠道完成内容准备、证据校验、生成、审核和人工发布。</p></div>
      {opportunity ? <a className="button secondary" href={geoHref(projectId, selection, { placement_stage: "simulation" })}>打开 TEST ONLY 预览</a> : null}
    </header>
    <section className={styles.panel}>
      {opportunityOptions.length ? <RouteSelect label="当前渠道任务" options={opportunityOptions}
        placeholder="选择渠道任务" value={opportunity?.id} /> : <strong>当前 Campaign 没有渠道任务</strong>}
      <div className={styles.contextMeta}><span>{destination ? channelLabel(destination.publication_channel) : "未选择渠道"}</span><span>{destination?.destination_key || "-"}</span>{opportunity ? <Status value={opportunity.status} /> : null}</div>
    </section>
    {!opportunity ? <div className={styles.empty}>请选择一个渠道任务。</div> : null}
    {opportunity?.status === "blocked" ? <div className={styles.notice}><span>这个渠道任务当前受政策限制。任务会保留，但需先在“渠道计划”解决阻断条件。</span><a href={geoHref(projectId, selection, { section: "destinations" })}>查看阻断原因</a></div> : null}
    {opportunity && selection.placementStage !== "simulation" ? <nav className={styles.stepper} aria-label="内容生产步骤">{stages.map((stage) => <a key={stage.id} className={selection.placementStage === stage.id ? styles.active : ""} href={geoHref(projectId, selection, { placement_stage: stage.id })}><span>步骤 {stage.number}</span><strong>{stage.label}</strong></a>)}</nav> : null}
    {opportunity && selection.placementStage === "brief" ? <BriefPromptPanel projectId={projectId} data={data} catalog={catalog} mode="brief" /> : null}
    {opportunity && selection.placementStage === "evidence" ? <BriefPromptPanel projectId={projectId} data={data} catalog={catalog} mode="evidence" /> : null}
    {opportunity && selection.placementStage === "generation" ? <GenerationPackagePanel projectId={projectId} data={data} mode="generation" /> : null}
    {opportunity && selection.placementStage === "review" ? <GenerationPackagePanel projectId={projectId} data={data} mode="review" /> : null}
    {opportunity && selection.placementStage === "publication" ? <PublicationPanel projectId={projectId} data={data} /> : null}
    {opportunity && selection.placementStage === "simulation" ? <PromptSimulationPanel projectId={projectId} data={data} catalog={catalog} /> : null}
  </section>;
}
