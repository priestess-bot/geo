import Link from "next/link";
import type { ReactNode } from "react";
import type { GeoSelection, LoadFailure, Resource } from "./model";
import { statusLabel } from "./display";
import styles from "./GeoWorkspace.module.css";

export function geoHref(projectId: string, selection: GeoSelection, updates: { [key: string]: string | undefined }): string {
  const params = new URLSearchParams();
  const nextSection = updates.geo_section || updates.section || selection.section;
  const normalizedUpdates = { ...updates };
  delete normalizedUpdates.geo_section;
  delete normalizedUpdates.section;
  const current: { [key: string]: string | undefined } = {
    tab: "geo", geo_section: nextSection, placement_stage: selection.placementStage, measurement_window: selection.measurementWindow, campaign_id: selection.campaignId,
    protocol_id: selection.protocolId, destination_id: selection.destinationId, opportunity_id: selection.opportunityId,
    brief_version_id: selection.briefVersionId, attempt_id: selection.attemptId, skill_id: selection.skillId,
    bundle_id: selection.bundleId, job_id: selection.jobId, version_id: selection.versionId,
    publication_id: selection.publicationId, submission_id: selection.submissionId,
    simulation_id: selection.simulationId, ...normalizedUpdates
  };
  Object.entries(current).forEach(([key, value]) => { if (value) params.set(key, value); });
  return `/projects/${projectId}?${params.toString()}`;
}

export function Status({ value }: { value: string }) {
  const tone = /approved|ready|succeeded|complete|verified|qualified|active/.test(value) ? styles.good
    : /failed|blocked|prohibited|rejected|cancelled|dead/.test(value) ? styles.bad : styles.neutral;
  return <span className={`${styles.status} ${tone}`}>{statusLabel(value)}</span>;
}
export function Empty({ children }: { children: ReactNode }) { return <div className={styles.empty}>{children}</div>; }
export function SectionHeader({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return <div className={styles.sectionHeader}><div><p>{eyebrow}</p><h2>{title}</h2></div>{children}</div>;
}
export function FailureNotice({ failure }: { failure: LoadFailure }) {
  const label = failure.status === 403 ? "无权读取此资源" : failure.status === 409 ? "资源状态已变化" : failure.status === 422 ? "查询条件无效" : "数据加载失败";
  return <div className={styles.failure} role="alert"><strong>{label}</strong><span>{failure.detail}</span>
    {failure.correlationId ? <code>Correlation {failure.correlationId}</code> : null}
    <Link href="">重新加载</Link></div>;
}
export function ResourceBlock<T>({ resource, children }: { resource: Resource<T>; children: (data: T) => ReactNode }) {
  return <>{resource.failure ? <FailureNotice failure={resource.failure} /> : null}{children(resource.data)}</>;
}
export function KeyValue({ label, children }: { label: string; children: ReactNode }) {
  return <div className={styles.keyValue}><span>{label}</span><strong>{children}</strong></div>;
}
export function ShortId({ value }: { value?: string | null }) { return <code title={value || ""}>{value ? value.slice(0, 8) : "-"}</code>; }
export function HiddenProject({ projectId }: { projectId: string }) { return <input type="hidden" name="project_id" value={projectId} />; }
export function TechnicalInfo({ children, label = "技术信息" }: { children: ReactNode; label?: string }) {
  return <details className={styles.technical}><summary>{label}</summary><div>{children}</div></details>;
}
export function CommandPanel({ children, label }: { children: ReactNode; label: string }) {
  return <details className={styles.commandPanel}><summary>{label}</summary><div className={styles.commandBody}>{children}</div></details>;
}
