import Link from "next/link";
import { ActionForm } from "./ActionForm";
import { controlJob, createExport, createGenerationJob, editPackage, reviewPackage, submitPackageReview } from "./placement-actions";
import { Empty, HiddenProject, ResourceBlock, SectionHeader, ShortId, Status, geoHref } from "./common";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";

export function GenerationPackagePanel({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const bundle = data.bundles.data.find((item) => item.id === selection.bundleId);
  const version = data.packageVersion.data;
  return <div className={styles.workspace}>
    <div className={styles.columns}>
      <div className={styles.panel}>
        <SectionHeader eyebrow="6 · Durable generation" title="生成任务" />
        <ActionForm action={createGenerationJob} title="从冻结 Bundle 生成" submitLabel="提交生成任务" disabled={!bundle}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="bundle_id" value={bundle?.id || ""} />
          <label>模型<input name="configured_model" defaultValue="deepseek-chat" required /></label>
          <label>总模型调用预算<input name="model_call_budget" type="number" min="1" max="20" defaultValue="3" required /></label>
        </ActionForm>
        <form method="GET" className={styles.form}>
          <input type="hidden" name="section" value="placement" /><input type="hidden" name="opportunity_id" value={selection.opportunityId || ""} /><input type="hidden" name="bundle_id" value={selection.bundleId || ""} />
          <label>跟踪 Job ID<input name="job_id" defaultValue={selection.jobId || ""} required placeholder="粘贴 Job UUID" /></label><button className="button secondary" type="submit">加载任务</button>
        </form>
        <ResourceBlock resource={data.job}>{(job) => job ? <div className={styles.workspace}>
          <div className={styles.rowHeader}><strong>{job.kind} <ShortId value={job.id} /></strong><Status value={job.status} /></div>
          <div className={styles.meta}><span>created {new Date(job.created_at).toLocaleString("zh-CN")}</span><span>updated {new Date(job.updated_at).toLocaleString("zh-CN")}</span><span>{job.result_ref || job.error_code || "等待结果"}</span></div>
          <div className={styles.toolbar}>{(["retry", "replay", "cancel"] as const).map((command) => <ActionForm action={controlJob} submitLabel={command} key={command} danger={command === "cancel"}>
            <HiddenProject projectId={projectId} /><input type="hidden" name="job_id" value={job.id} /><input type="hidden" name="command" value={command} />
          </ActionForm>)}</div>
        </div> : <Empty>提交生成后通过结果链接打开 Job；外部模型调用期间不会持有数据库锁。</Empty>}</ResourceBlock>
      </div>
      <div className={styles.panel}>
        <SectionHeader eyebrow="Audit trail" title="Job Events" />
        <ResourceBlock resource={data.jobEvents}>{(events) => events.length ? <div className={styles.timeline}>{events.map((event) => <div className={styles.timelineItem} key={event.id}>
          <strong>{event.event_type}</strong><span>{new Date(event.created_at).toLocaleString("zh-CN")} · {event.worker_id}</span>
          {Object.keys(event.details).length ? <code>{JSON.stringify(event.details)}</code> : null}
        </div>)}</div> : <Empty>选择 Job 后显示领取、重试、完成与工件 finalize 事件。</Empty>}</ResourceBlock>
      </div>
    </div>
    <div className={styles.split}>
      <aside className={styles.panel}>
        <h3>Package Versions</h3>
        <ResourceBlock resource={data.packages}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link key={item.id}
          className={item.id === selection.versionId ? styles.selectedRow : styles.row}
          href={geoHref(projectId, selection, { version_id: item.id, publication_id: undefined, submission_id: undefined })}>
          <span className={styles.rowHeader}><strong>Version {item.version_number}</strong><Status value={item.workflow_status} /></span>
          <span className={styles.meta}><span>hash {item.content_hash.slice(0, 12)}</span><span>{item.edited_by ? "人工编辑" : "模型生成"}</span></span>
        </Link>)}</div> : <Empty>生成任务成功后会产生首个不可变版本。</Empty>}</ResourceBlock>
      </aside>
      <div className={styles.workspace}>
        <div className={styles.panel}>
          <SectionHeader eyebrow="7 · Immutable package" title={version ? `Package v${version.version_number}` : "文案与 Claim Inventory"}>
            {version ? <Status value={version.workflow_status} /> : null}
          </SectionHeader>
          {version ? <><div className={styles.keyValues}><div><span className={styles.meta}>Content hash</span><br /><code>{version.content_hash.slice(0, 16)}</code></div><div><span className={styles.meta}>Prompt Bundle</span><br /><ShortId value={version.prompt_bundle_id} /></div><div><span className={styles.meta}>Base version</span><br /><ShortId value={version.base_version_id} /></div></div>
            <div className={styles.content}>{version.rendered_text}</div></> : <Empty>选择一个 Package Version。</Empty>}
          <h3>事实 Claim</h3>
          <ResourceBlock resource={data.claims}>{(claims) => claims.length ? <div className={styles.list}>{claims.map((claim) => <div className={styles.row} key={claim.id}>
            <span className={styles.rowHeader}><strong>{claim.claim_text}</strong><Status value={claim.support_status} /></span>
            <span className={styles.meta}><span>{claim.claim_kind}</span><span>{claim.evidence_item_ids.length} evidence refs</span></span>
          </div>)}</div> : <Empty>Claim inventory 为空；这不等于证据覆盖 100%，人工仍需确认抽取完整性。</Empty>}</ResourceBlock>
        </div>
        <div className={styles.columns}>
          <div className={styles.panel}>
            <SectionHeader eyebrow="8 · Maker-checker" title="提交与双人复核" />
            <ActionForm action={submitPackageReview} submitLabel="提交复核" disabled={!version}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="version_id" value={version?.id || ""} />
            </ActionForm>
            <ActionForm action={reviewPackage} title="独立复核结论" submitLabel="保存结论" disabled={!version}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="version_id" value={version?.id || ""} />
              <label>决定<select name="decision" defaultValue="approved"><option value="approved">批准</option><option value="needs_revision">需修订</option><option value="rejected">拒绝</option><option value="blocked">阻断</option></select></label>
              <label className={styles.check}><input type="checkbox" name="claim_inventory_complete" />Claim inventory 已逐句确认完整</label>
              <label className={styles.check}><input type="checkbox" name="extracted_claim_support_confirmed" />已抽取 Claim 的证据支持已确认</label>
              <label>评分<input name="score" type="number" min="0" max="100" /></label><label>备注<textarea name="notes" /></label>
            </ActionForm>
            <ResourceBlock resource={data.reviews}>{(reviews) => reviews.map((review) => <div className={styles.row} key={review.id}><span className={styles.rowHeader}><strong>{review.decision}</strong><ShortId value={review.reviewer_id} /></span><span className={styles.meta}>submitter <ShortId value={review.submitted_for_review_by} /> · inventory {String(review.claim_inventory_complete)} · support {String(review.extracted_claim_support_confirmed)}</span></div>)}</ResourceBlock>
          </div>
          <div className={styles.panel}>
            <SectionHeader eyebrow="9 · New version only" title="人工编辑" />
            <ActionForm action={editPackage} submitLabel="创建新版本" disabled={!version}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="package_id" value={version?.package_id || ""} /><input type="hidden" name="base_version_id" value={version?.id || ""} /><input type="hidden" name="base_content_hash" value={version?.content_hash || ""} />
              <label>正文<textarea name="rendered_text" required defaultValue={version?.rendered_text || ""} /></label>
              <label>结构化内容 JSON<textarea name="content_json" required defaultValue={version ? JSON.stringify(version.content_json, null, 2) : "{}"} /></label>
              <label>完整 Claim 清单 JSON<textarea name="claims" required defaultValue={JSON.stringify(data.claims.data.map((claim) => ({
                text: claim.claim_text, kind: claim.claim_kind, support_status: claim.support_status,
                evidence_item_ids: claim.evidence_item_ids
              })), null, 2)} /></label>
              <label>修改原因<input name="reason" required placeholder="客户要求、事实更新或编辑修订" /></label>
            </ActionForm>
            <p className={styles.meta}>基于精确 hash 创建新版本；Claim 必须逐条更新且只能引用冻结 Evidence Pack，旧审批不会继承。</p>
          </div>
        </div>
        <div className={styles.panel}>
          <SectionHeader eyebrow="10 · Export is not publication" title="不可变导出工件" />
          <ActionForm action={createExport} submitLabel="创建导出" disabled={!version}>
            <HiddenProject projectId={projectId} /><input type="hidden" name="version_id" value={version?.id || ""} />
          </ActionForm>
          <ResourceBlock resource={data.exports}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.id}>
            <span className={styles.rowHeader}><strong>{item.export_format} · {new Date(item.exported_at).toLocaleString("zh-CN")}</strong><Status value={item.artifact_status} /></span>
            <span className={styles.meta}>hash {item.content_hash.slice(0, 12)} · <ShortId value={item.id} /></span>
            <Link className="button secondary" href={`/projects/${projectId}/geo/export-download/${item.package_version_id}/${item.id}`}>下载工件</Link>
          </div>)}</div> : <Empty>导出用于内部复核、交付或备份，不会自动创建待发布记录。</Empty>}</ResourceBlock>
        </div>
      </div>
    </div>
  </div>;
}
