import { ActionForm } from "./ActionForm";
import { controlJob, createExport, createGenerationJob, reviewPackage, submitPackageReview } from "./placement-actions";
import { CommandPanel, Empty, geoHref, HiddenProject, ResourceBlock, Status, TechnicalInfo } from "./common";
import type { GeoWorkspaceData } from "./model";
import { PackageEditForm } from "./PackageEditForm";
import styles from "./GeoWorkspace.module.css";

export function GenerationPackagePanel({ projectId, data, mode }: {
  projectId: string; data: GeoWorkspaceData; mode: "generation" | "review";
}) {
  return mode === "generation" ? <GenerationStep projectId={projectId} data={data} /> : <ReviewStep projectId={projectId} data={data} />;
}

function GenerationStep({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const bundle = data.bundles.data.find((item) => item.id === data.selection.bundleId) || data.bundles.data[0];
  const version = data.packageVersion.data;
  return <div className={styles.workspace}>
    {!bundle ? <div className={styles.notice}><span>还没有冻结的生成输入。</span><a href={geoHref(projectId, data.selection, { placement_stage: "evidence" })}>返回准备证据</a></div> : null}
    <div className={styles.columns}>
      <section className={styles.panel}><div className={styles.sectionHeader}><div><p>DeepSeek 生成任务</p><h2>生成文案</h2></div>{data.job.data ? <Status value={data.job.data.status} /> : null}</div>
        <ActionForm action={createGenerationJob} submitLabel="开始生成" disabled={!bundle}><HiddenProject projectId={projectId} /><label>生成输入<select name="bundle_id" required defaultValue={bundle?.id || ""}>{data.bundles.data.map((item, index) => <option key={item.id} value={item.id}>生成输入 {data.bundles.data.length - index}</option>)}</select></label><details><summary>模型设置</summary><div className={styles.formInset}><label>模型<input name="configured_model" defaultValue="deepseek-v4-flash" required /></label><label>总调用预算<input name="model_call_budget" type="number" min="1" max="5" defaultValue="2" required /></label></div></details></ActionForm>
        <ResourceBlock resource={data.job}>{(job) => job ? <div className={styles.row}><span className={styles.rowHeader}><strong>生成任务</strong><Status value={job.status} /></span><span className={styles.meta}>{new Date(job.updated_at).toLocaleString("zh-CN")} · {job.result_ref || job.error_code || "等待模型结果"}</span><div className={styles.toolbar}>{(["retry", "replay", "cancel"] as const).map((command) => <ActionForm action={controlJob} submitLabel={command === "retry" ? "重试" : command === "replay" ? "重新执行" : "取消"} key={command} danger={command === "cancel"}><HiddenProject projectId={projectId} /><input type="hidden" name="job_id" value={job.id} /><input type="hidden" name="command" value={command} /></ActionForm>)}</div><TechnicalInfo><code>{job.id}</code><code>{job.kind}</code></TechnicalInfo></div> : <Empty>开始生成后，这里会显示排队、处理和完成状态。</Empty>}</ResourceBlock>
      </section>
      <section className={styles.panel}><div className={styles.sectionHeader}><div><p>生成结果</p><h2>{version ? `文案版本 ${version.version_number}` : "等待生成"}</h2></div>{version ? <Status value={version.workflow_status} /> : null}</div>
        {version ? <><div className={styles.content}>{version.rendered_text}</div><a className="button" href={geoHref(projectId, data.selection, { placement_stage: "review", version_id: version.id })}>进入审核</a><TechnicalInfo><code>{version.id}</code><code>{version.content_hash}</code></TechnicalInfo></> : <Empty>模型输出持久化后会生成不可变文案版本。</Empty>}
      </section>
    </div>
    <CommandPanel label="高级：生成任务事件"><ResourceBlock resource={data.jobEvents}>{(events) => events.length ? <div className={styles.timeline}>{events.map((event) => <div className={styles.timelineItem} key={event.id}><strong>{event.event_type}</strong><span>{new Date(event.created_at).toLocaleString("zh-CN")}</span>{Object.keys(event.details).length ? <code>{JSON.stringify(event.details)}</code> : null}</div>)}</div> : <Empty>当前没有任务事件。</Empty>}</ResourceBlock></CommandPanel>
  </div>;
}

function ReviewStep({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const version = data.packageVersion.data || data.packages.data[0];
  return <div className={styles.workspace}>
    <section className={styles.panel}><div className={styles.sectionHeader}><div><p>不可变版本</p><h2>选择待审核文案</h2></div><span className={styles.meta}>{data.packages.data.length} 个版本</span></div>
      <ResourceBlock resource={data.packages}>{(items) => items.length ? <div className={styles.tabs}>{items.map((item) => <a key={item.id} className={item.id === data.selection.versionId ? styles.active : ""} href={geoHref(projectId, data.selection, { version_id: item.id, publication_id: undefined, submission_id: undefined })}>版本 {item.version_number} · {item.edited_by ? "人工修订" : "模型生成"}</a>)}</div> : <Empty>生成文案后才能进入审核。</Empty>}</ResourceBlock>
    </section>
    <div className={styles.columns}>
      <section className={styles.panel}><div className={styles.sectionHeader}><div><p>正文</p><h2>{version ? `文案版本 ${version.version_number}` : "没有文案"}</h2></div>{version ? <Status value={version.workflow_status} /> : null}</div>{version ? <div className={styles.content}>{version.rendered_text}</div> : <Empty>选择一个版本。</Empty>}
        <h3>事实与表述</h3><ResourceBlock resource={data.claims}>{(claims) => claims.length ? <table className={styles.table}><thead><tr><th>表述</th><th>类型</th><th>证据</th></tr></thead><tbody>{claims.map((claim) => <tr key={claim.id}><td>{claim.claim_text}</td><td>{claimKindLabel(claim.claim_kind)}</td><td><Status value={claim.support_status} /><div className={styles.meta}>{claim.evidence_item_ids.length} 条引用</div></td></tr>)}</tbody></table> : <Empty>尚无 Claim。审核者仍需确认是否存在漏抽取的事实句。</Empty>}</ResourceBlock>
      </section>
      <section className={styles.workspace}>
        <div className={styles.panel}><div className={styles.sectionHeader}><div><p>Maker-checker</p><h2>提交与独立审核</h2></div></div><ActionForm action={submitPackageReview} submitLabel="提交独立审核" disabled={!version}><HiddenProject projectId={projectId} /><input type="hidden" name="version_id" value={version?.id || ""} /></ActionForm>
          <ActionForm action={reviewPackage} submitLabel="保存审核结论" disabled={!version}><HiddenProject projectId={projectId} /><input type="hidden" name="version_id" value={version?.id || ""} /><label>审核结论<select name="decision" defaultValue="approved"><option value="approved">批准发布</option><option value="needs_revision">要求修改</option><option value="rejected">拒绝</option><option value="blocked">阻断</option></select></label><label className={styles.check}><input type="checkbox" name="claim_inventory_complete" />已逐句确认事实清单完整</label><label className={styles.check}><input type="checkbox" name="extracted_claim_support_confirmed" />已确认每条事实的证据支持</label><label>评分<input name="score" type="number" min="0" max="100" /></label><label>审核说明<textarea name="notes" /></label></ActionForm>
          <ResourceBlock resource={data.reviews}>{(reviews) => reviews.length ? <div className={styles.list}>{reviews.map((review) => <div className={styles.row} key={review.id}><span className={styles.rowHeader}><strong>{reviewDecisionLabel(review.decision)}</strong><Status value={review.decision} /></span><span className={styles.meta}>{review.reviewed_at ? new Date(review.reviewed_at).toLocaleString("zh-CN") : "等待完成"}</span><TechnicalInfo><code>Reviewer {review.reviewer_id}</code><code>Submitter {review.submitted_for_review_by}</code></TechnicalInfo></div>)}</div> : <Empty>尚无审核记录。</Empty>}</ResourceBlock>
        </div>
        {version ? <CommandPanel label="人工修改并创建新版本"><PackageEditForm projectId={projectId} version={version} claims={data.claims.data} /></CommandPanel> : null}
      </section>
    </div>
    <section className={styles.panel}><div className={styles.sectionHeader}><div><p>Export is not publication · 导出不是发布</p><h2>导出与交付</h2></div></div><ActionForm action={createExport} submitLabel="创建不可变导出" disabled={!version}><HiddenProject projectId={projectId} /><input type="hidden" name="version_id" value={version?.id || ""} /></ActionForm>
      <ResourceBlock resource={data.exports}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.id}><span className={styles.rowHeader}><strong>{item.export_format} · {new Date(item.exported_at).toLocaleString("zh-CN")}</strong><Status value={item.artifact_status} /></span><a className="button secondary" href={`/projects/${projectId}/export-download/${item.package_version_id}/${item.id}`}>下载</a><TechnicalInfo><code>{item.id}</code><code>{item.content_hash}</code></TechnicalInfo></div>)}</div> : <Empty>导出只用于内部复核、交付或备份，不会创建发布任务。</Empty>}</ResourceBlock>
      {version?.workflow_status === "approved" ? <a className="button" href={geoHref(projectId, data.selection, { placement_stage: "publication", version_id: version.id })}>继续发布</a> : null}
    </section>
  </div>;
}

function claimKindLabel(value: string) { return ({ factual: "事实", comparative: "比较", experience: "体验", non_factual: "非事实表达" } as Record<string, string>)[value] || value; }
function reviewDecisionLabel(value: string) { return ({ approved: "批准发布", needs_revision: "要求修改", rejected: "拒绝", blocked: "阻断" } as Record<string, string>)[value] || value; }
