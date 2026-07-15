import Link from "next/link";
import { BriefPromptPanel } from "./BriefPromptPanel";
import { Empty, ResourceBlock, SectionHeader, ShortId, Status, geoHref } from "./common";
import { GenerationPackagePanel } from "./GenerationPackagePanel";
import type { GeoWorkspaceData } from "./model";
import { PublicationPanel } from "./PublicationPanel";
import styles from "./GeoWorkspace.module.css";

export function PlacementWorkspace({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const stages = [{ id: "intake", label: "Brief / Evidence / Prompt" }, { id: "generation", label: "Generation / Review / Export" }, { id: "publication", label: "Publication / Measurement" }] as const;
  return <section className={styles.workspace}>
    <SectionHeader eyebrow="Controlled content production" title="文案投放生产线" />
    <div className={styles.panel}>
      <div className={styles.toolbar}>{data.campaigns.data.map((campaign) => <Link key={campaign.id} className={campaign.id === selection.campaignId ? "button" : "button secondary"}
        href={geoHref(projectId, selection, { campaign_id: campaign.id, opportunity_id: undefined, brief_version_id: undefined, version_id: undefined })}>{campaign.name}</Link>)}</div>
      <h3>投放机会</h3>
      <ResourceBlock resource={data.opportunities}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => {
        const destination = data.destinations.data.find((candidate) => candidate.id === item.destination_id);
        return <Link key={item.id} className={item.id === selection.opportunityId ? styles.selectedRow : styles.row}
          href={geoHref(projectId, selection, { opportunity_id: item.id, brief_version_id: undefined, attempt_id: undefined, bundle_id: undefined, version_id: undefined, publication_id: undefined, submission_id: undefined })}>
          <span className={styles.rowHeader}><strong>{destination?.publication_channel || "channel"} · {item.opportunity_ref}</strong><Status value={item.status} /></span>
          <span className={styles.meta}><span>{item.rationale}</span><ShortId value={item.id} /></span>
        </Link>;
      })}</div> : <Empty>先在 Campaign 中选择渠道并资格化投放机会。</Empty>}</ResourceBlock>
    </div>
    <nav className={styles.tabs} aria-label="投放生产阶段">{stages.map((stage) => <Link key={stage.id}
      className={selection.placementStage === stage.id ? styles.active : ""}
      href={geoHref(projectId, selection, { placement_stage: stage.id })}>{stage.label}</Link>)}</nav>
    {selection.placementStage === "intake" ? <BriefPromptPanel projectId={projectId} data={data} /> : null}
    {selection.placementStage === "generation" ? <GenerationPackagePanel projectId={projectId} data={data} /> : null}
    {selection.placementStage === "publication" ? <PublicationPanel projectId={projectId} data={data} /> : null}
  </section>;
}
