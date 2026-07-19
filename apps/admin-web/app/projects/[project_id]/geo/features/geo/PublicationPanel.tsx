import { ActionForm } from "./ActionForm";
import { blockSubmission, cancelMeasurementCollectionTask, completeMeasurementCollectionTask, createMeasurement, createPublication, createSubmission, setSubmissionUrl, transitionPublication, verifySubmission } from "./placement-actions";
import { CommandPanel, Empty, geoHref, HiddenProject, ResourceBlock, Status, TechnicalInfo } from "./common";
import { channelLabel } from "./display";
import { loadMeasurementCollectionTasks } from "./measurement-task-data";
import { loadPublicationVerificationAttempts } from "./publication-verification-data";
import type { GeoWorkspaceData } from "./model";
import styles from "./GeoWorkspace.module.css";

export async function PublicationPanel({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const version = data.packageVersion.data;
  const publication = data.publications.data.find((item) => item.id === data.selection.publicationId);
  const submission = data.submission.data;
  const opportunity = data.opportunities.data.find((item) => item.id === data.selection.opportunityId);
  const usableDestinations = data.destinations.data.filter((item) => item.id === opportunity?.destination_id && (item.policy_status === "approved" || item.policy_status === "restricted"));
  const [collectionTasks, verificationAttempts] = await Promise.all([
    loadMeasurementCollectionTasks(projectId, data.selection.campaignId || "", submission?.id),
    loadPublicationVerificationAttempts(projectId, data.selection.campaignId || "", submission?.id)
  ]);
  const verificationActive = submission?.status === "verifying";
  const verificationLabel = verificationAttempts.data.length || submission?.verification_result
    ? "重新验证"
    : "请求验证";
  return <div className={styles.workspace}>
    {!version ? <div className={styles.notice}><span>需要先选择并批准一个文案版本。</span><a href={geoHref(projectId, data.selection, { placement_stage: "review" })}>返回审核</a></div> : null}
    <header className={styles.pageHeading}><div><h2>发布与测量</h2><p>显式创建发布任务，记录人工提交，验证公开 URL，并按冻结口径复测。</p></div>
      <CommandPanel label="创建发布任务"><CreatePublicationForm campaignId={data.selection.campaignId || ""} projectId={projectId} versionId={version?.id} versionStatus={version?.workflow_status} destinations={usableDestinations} /></CommandPanel>
    </header>

    <section className={styles.panel}><div className={styles.sectionHeader}><div><p>Publication intent</p><h2>发布任务</h2></div><span className={styles.meta}>{data.publications.data.length} 个</span></div>
      <ResourceBlock resource={data.publications}>{(items) => items.length ? <table className={styles.table}><thead><tr><th>渠道</th><th>目标位置</th><th>批次</th><th>状态</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td><a href={geoHref(projectId, data.selection, { publication_id: item.id, submission_id: undefined })}><strong>{channelLabel(item.publication_channel)}</strong></a></td><td>{item.destination_key}</td><td>第 {item.publication_attempt} 次</td><td><Status value={item.status} /><TechnicalInfo><code>{item.id}</code></TechnicalInfo></td></tr>)}</tbody></table> : <Empty>批准文案后，明确点击“创建发布任务”才会进入待发布队列。导出不会产生发布任务。</Empty>}</ResourceBlock>
      {publication ? <CommandPanel label="阻断或取消当前发布任务"><ActionForm action={transitionPublication} submitLabel="更新任务" danger><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="publication_id" value={publication.id} /><label>操作<select name="command" defaultValue="block"><option value="block">标记受阻</option><option value="cancel">取消任务</option></select></label><label>原因<input name="reason" required /></label></ActionForm></CommandPanel> : null}
    </section>

    <div className={styles.columns}>
      <section className={styles.panel}><div className={styles.sectionHeader}><div><p>人工执行记录</p><h2>平台提交</h2></div></div>
        <CommandPanel label="记录一次人工提交"><ActionForm action={createSubmission} submitLabel="创建提交记录" disabled={!publication}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="publication_id" value={publication?.id || ""} /><label>平台回执或草稿编号<input name="provider_submission_id" placeholder="可选" /></label><label>公开 URL<input name="submitted_url" type="url" placeholder="尚未公开时可以留空" /></label></ActionForm></CommandPanel>
        <ResourceBlock resource={data.submissions}>{(items) => items.length ? <div className={styles.list}>{items.map((item, index) => <a key={item.id} className={item.id === data.selection.submissionId ? styles.selectedRow : styles.row} href={geoHref(projectId, data.selection, { submission_id: item.id })}><span className={styles.rowHeader}><strong>提交记录 {items.length - index}</strong><Status value={item.status} /></span><span className={styles.meta}>{item.submitted_url || item.provider_submission_id || "等待公开 URL"}</span></a>)}</div> : <Empty>运营人员在外部平台实际提交后，在这里保留可追踪记录。</Empty>}</ResourceBlock>
      </section>
      <section className={styles.panel}><div className={styles.sectionHeader}><div><p>URL lifecycle</p><h2>公开 URL 验证</h2></div>{submission ? <Status value={submission.status} /> : null}</div>
        {submission ? <><p>{submission.submitted_url ? <a href={submission.submitted_url} target="_blank" rel="noreferrer">{submission.submitted_url}</a> : "尚未回填公开 URL"}</p><TechnicalInfo><code>{submission.id}</code></TechnicalInfo></> : <Empty>选择一条提交记录。</Empty>}
        <ResourceBlock resource={verificationAttempts}>{(items) => <VerificationEvidence attempts={items} hasLegacyProjection={Boolean(submission?.verification_result)} />}</ResourceBlock>
        <ActionForm action={setSubmissionUrl} submitLabel="保存公开 URL" disabled={!submission}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="submission_id" value={submission?.id || ""} /><label>公开 URL<input name="submitted_url" type="url" required defaultValue={submission?.submitted_url || ""} /></label></ActionForm>
        <div className={styles.toolbar}><ActionForm action={verifySubmission} submitLabel={verificationLabel} pendingLabel="正在创建验证任务..." disabled={!submission?.submitted_url || verificationActive}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="submission_id" value={submission?.id || ""} /></ActionForm><ActionForm action={blockSubmission} submitLabel="标记受阻" danger disabled={!submission}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="submission_id" value={submission?.id || ""} /><input type="hidden" name="reason" value="Blocked by Admin operator" /></ActionForm></div>
      </section>
    </div>

    <section className={styles.panel}><div className={styles.sectionHeader}><div><p>结果证据</p><h2>效果测量</h2></div><CommandPanel label="记录一次测量"><MeasurementForm projectId={projectId} data={data} submissionId={submission?.id} /></CommandPanel></div>
      <ResourceBlock resource={data.measurements}>{(items) => items.length ? <table className={styles.table}><thead><tr><th>测量时间</th><th>消费者问题</th><th>推荐位置</th><th>是否引用</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{new Date(item.measured_at).toLocaleString("zh-CN")}</td><td>{data.queries.data.find((query) => query.id === item.monitoring_query_id)?.query_text || "已归档问题"}</td><td>{item.recommendation_position || "未进入推荐"}</td><td><Status value={item.citation_present ? "verified" : "not_cited"} /><TechnicalInfo><a href={item.result_snapshot_uri}>结果快照</a><code>{item.id}</code></TechnicalInfo></td></tr>)}</tbody></table> : <Empty>URL 验证成功后，按基线、T+28、T+56、T+84 记录结果。</Empty>}</ResourceBlock>
    </section>

    <CommandPanel label="测量采集待办与技术记录"><ResourceBlock resource={collectionTasks}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.id}><span className={styles.rowHeader}><strong>{item.measurement_window} · {new Date(item.scheduled_for).toLocaleString("zh-CN")}</strong><Status value={item.status} /></span><span className={styles.meta}>样本 {item.actual_sample_count}/{item.expected_sample_count}</span>{item.status === "open" ? <div className={styles.toolbar}><ActionForm action={completeMeasurementCollectionTask} submitLabel="核对并完成"><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="task_id" value={item.id} /></ActionForm><ActionForm action={cancelMeasurementCollectionTask} submitLabel="取消待办" danger><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="task_id" value={item.id} /><label>原因<input name="reason" required /></label></ActionForm></div> : null}<TechnicalInfo><code>{item.id}</code><code>Protocol {item.protocol_id}</code><code>Job {item.job_id}</code></TechnicalInfo></div>)}</div> : <Empty>当前没有到期的测量采集任务。</Empty>}</ResourceBlock></CommandPanel>
  </div>;
}

function VerificationEvidence({ attempts, hasLegacyProjection }: {
  attempts: Awaited<ReturnType<typeof loadPublicationVerificationAttempts>>["data"];
  hasLegacyProjection: boolean;
}) {
  const latest = attempts[0];
  if (!latest) {
    return hasLegacyProjection
      ? <div className={styles.notice}>旧版验证结果：仅保留历史投影，没有版本化 Attempt，未补造验证证据。</div>
      : <Empty>尚未执行公开 URL 验证。</Empty>;
  }
  return <div className={styles.list}>
    <div className={styles.row}>
      <span className={styles.rowHeader}><strong>最近验证 · 第 {latest.attempt_number} 次执行</strong><Status value={latest.outcome} /></span>
      <span className={styles.meta}>{new Date(latest.checked_at).toLocaleString("zh-CN")} · HTTP {latest.status_code || "未返回"} · 重定向 {latest.redirect_count}</span>
      <table className={styles.table}><thead><tr><th>检查项</th><th>结果</th><th>失败码</th></tr></thead><tbody>{latest.checks.map((check) => <tr key={check.name}><td>{check.name}</td><td>{check.passed ? "通过" : "失败"}</td><td>{check.failure_code || "-"}</td></tr>)}</tbody></table>
      {latest.failures.length ? <div><strong>失败</strong>{latest.failures.map((failure) => <p className={styles.meta} key={`${failure.check}:${failure.code}`}>{failure.code} · {failure.check} · {failure.disposition}</p>)}</div> : null}
      <TechnicalInfo label="验证规则与证据哈希"><code>规则 {latest.verifier_version}</code><code>Result {latest.result_hash}</code><code>Rule {latest.verification_rule_hash || "无"}</code><code>Content {latest.content_rule_hash || "无"}</code><code>Body {latest.body_hash || "无"}</code><code>Visible {latest.visible_text_hash || "无"}</code><code>Metadata {latest.metadata_hash || "无"}</code><code>Job {latest.job_id}</code></TechnicalInfo>
    </div>
    {attempts.length > 1 ? <TechnicalInfo label="历史验证 Attempt">{attempts.slice(1).map((attempt) => <code key={attempt.id}>第 {attempt.attempt_number} 次 · {attempt.outcome} · {attempt.result_hash}</code>)}</TechnicalInfo> : null}
  </div>;
}

function CreatePublicationForm({ campaignId, projectId, versionId, versionStatus, destinations }: { campaignId: string; projectId: string; versionId?: string; versionStatus?: string; destinations: GeoWorkspaceData["destinations"]["data"] }) {
  return <ActionForm action={createPublication} submitLabel="标记为待发布" disabled={!campaignId || !versionId || versionStatus !== "approved" || destinations.length === 0}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={campaignId} /><input type="hidden" name="version_id" value={versionId || ""} /><label>发布渠道<select name="destination_id" required defaultValue=""><option value="" disabled>选择已复核渠道</option>{destinations.map((item) => <option value={item.id} key={item.id}>{channelLabel(item.publication_channel)} · {item.destination_key}</option>)}</select></label><label>发布批次<input name="publication_attempt" type="number" min="1" defaultValue="1" required /></label><label>政策依据<textarea name="policy_basis" placeholder="记录账号身份、披露和发布方式" /></label><label className={styles.check}><input type="checkbox" name="restricted_policy_acknowledged" />受限渠道的条件已逐项满足</label></ActionForm>;
}

function MeasurementForm({ projectId, data, submissionId }: { projectId: string; data: GeoWorkspaceData; submissionId?: string }) {
  return <ActionForm action={createMeasurement} submitLabel="保存测量" disabled={!submissionId || data.queries.data.length === 0}><HiddenProject projectId={projectId} /><input type="hidden" name="campaign_id" value={data.selection.campaignId || ""} /><input type="hidden" name="submission_id" value={submissionId || ""} /><label>消费者问题<select name="monitoring_query_id" required defaultValue=""><option value="" disabled>选择问题</option>{data.queries.data.map((item) => <option key={item.id} value={item.id}>{item.query_text}</option>)}</select></label><label>测量时间<input name="measured_at" type="datetime-local" required /></label><label>结果截图或快照 URL<input name="result_snapshot_uri" type="url" required /></label><label>推荐位置<input name="recommendation_position" type="number" min="1" /></label><label className={styles.check}><input type="checkbox" name="product_mentioned" />回答提及主产品</label><label className={styles.check}><input type="checkbox" name="recommendation_present" />回答明确推荐主产品</label><label className={styles.check}><input type="checkbox" name="citation_present" />回答引用了该投放 URL</label></ActionForm>;
}
