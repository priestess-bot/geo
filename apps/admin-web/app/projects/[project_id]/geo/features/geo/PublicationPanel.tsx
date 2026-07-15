import Link from "next/link";
import { ActionForm } from "./ActionForm";
import { blockSubmission, cancelMeasurementCollectionTask, completeMeasurementCollectionTask, createMeasurement, createPublication, createSubmission, setSubmissionUrl, transitionPublication, verifySubmission } from "./placement-actions";
import { Empty, HiddenProject, ResourceBlock, SectionHeader, ShortId, Status, geoHref } from "./common";
import type { GeoWorkspaceData } from "./model";
import { loadMeasurementCollectionTasks } from "./measurement-task-data";
import styles from "./GeoWorkspace.module.css";

export async function PublicationPanel({ projectId, data }: { projectId: string; data: GeoWorkspaceData }) {
  const { selection } = data;
  const version = data.packageVersion.data;
  const publication = data.publications.data.find((item) => item.id === selection.publicationId);
  const submission = data.submission.data;
  const opportunity = data.opportunities.data.find((item) => item.id === selection.opportunityId);
  const usableDestinations = data.destinations.data.filter((item) =>
    item.id === opportunity?.destination_id &&
    (item.policy_status === "approved" || item.policy_status === "restricted")
  );
  const collectionTasks = await loadMeasurementCollectionTasks(projectId, submission?.id);
  return <div className={styles.workspace}>
    <SectionHeader eyebrow="Explicit publication intent" title="投放请求、人工提交与效果测量" />
    <div className={styles.threeColumns}>
      <div className={styles.panel}>
        <SectionHeader eyebrow="11 · Deliberate handoff" title="创建发布请求" />
        <ActionForm action={createPublication} submitLabel="标记为待发布" disabled={!version || version.workflow_status !== "approved" || usableDestinations.length === 0}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="version_id" value={version?.id || ""} />
          <label>目的地<select name="destination_id" required defaultValue=""><option value="" disabled>选择已复核目的地</option>{usableDestinations.map((item) => <option value={item.id} key={item.id}>{item.publication_channel} · {item.destination_key} · {item.policy_status}</option>)}</select></label>
          <label>发布批次<input name="publication_attempt" type="number" min="1" defaultValue="1" required /></label>
          <label>政策依据<textarea name="policy_basis" placeholder="记录允许的身份、披露与投放方式" /></label>
          <label className={styles.check}><input type="checkbox" name="restricted_policy_acknowledged" />若渠道受限，已阅读并满足限制</label>
        </ActionForm>
        <p className={styles.meta}>这个动作才会产生待发布任务。下载、导出和客户交付不会触发它。</p>
      </div>
      <div className={styles.panel}>
        <SectionHeader eyebrow="12 · Publication task" title="发布请求" />
        <ResourceBlock resource={data.publications}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link key={item.id}
          className={item.id === selection.publicationId ? styles.selectedRow : styles.row}
          href={geoHref(projectId, selection, { publication_id: item.id, submission_id: undefined })}>
          <span className={styles.rowHeader}><strong>{item.publication_channel} · attempt {item.publication_attempt}</strong><Status value={item.status} /></span>
          <span className={styles.meta}><span>{item.destination_key}</span><ShortId value={item.id} /></span>
        </Link>)}</div> : <Empty>当前版本没有发布意图。</Empty>}</ResourceBlock>
        {publication ? <ActionForm action={transitionPublication} title="阻断或取消" submitLabel="更新任务" danger>
          <HiddenProject projectId={projectId} /><input type="hidden" name="publication_id" value={publication.id} />
          <label>操作<select name="command" defaultValue="block"><option value="block">阻断</option><option value="cancel">取消</option></select></label><label>原因<input name="reason" required /></label>
        </ActionForm> : null}
      </div>
      <div className={styles.panel}>
        <SectionHeader eyebrow="13 · Manual delivery" title="记录人工提交" />
        <ActionForm action={createSubmission} submitLabel="创建提交记录" disabled={!publication}>
          <HiddenProject projectId={projectId} /><input type="hidden" name="publication_id" value={publication?.id || ""} />
          <label>平台提交 ID<input name="provider_submission_id" placeholder="可选，平台回执或草稿 ID" /></label>
          <label>已知公开 URL<input name="submitted_url" type="url" placeholder="未知时留空，之后回填" /></label>
        </ActionForm>
        <p className={styles.meta}>系统不代替操作员向外部平台自动发帖；这里记录真实人工投放事实。</p>
      </div>
    </div>
    <div className={styles.split}>
      <aside className={styles.panel}>
        <h3>Submission Attempts</h3>
        <ResourceBlock resource={data.submissions}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <Link key={item.id}
          className={item.id === selection.submissionId ? styles.selectedRow : styles.row}
          href={geoHref(projectId, selection, { submission_id: item.id })}>
          <span className={styles.rowHeader}><strong><ShortId value={item.id} /></strong><Status value={item.status} /></span>
          <span className={styles.meta}>{item.submitted_url || item.provider_submission_id || "等待 URL 回填"}</span>
        </Link>)}</div> : <Empty>尚无人工提交记录。</Empty>}</ResourceBlock>
      </aside>
      <div className={styles.workspace}>
        <div className={styles.columns}>
          <div className={styles.panel}>
            <SectionHeader eyebrow="14 · URL lifecycle" title="回填、阻断与验证" />
            {submission ? <><div className={styles.rowHeader}><strong>Submission <ShortId value={submission.id} /></strong><Status value={submission.status} /></div>
              <p><a href={submission.submitted_url || "#"} target="_blank" rel="noreferrer">{submission.submitted_url || "尚未回填公开 URL"}</a></p>
              {submission.verification_result ? <pre className={styles.code}>{JSON.stringify(submission.verification_result, null, 2)}</pre> : null}</> : <Empty>选择一个提交记录。</Empty>}
            <ActionForm action={setSubmissionUrl} submitLabel="回填 URL" disabled={!submission}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="submission_id" value={submission?.id || ""} /><label>公开 URL<input name="submitted_url" type="url" required defaultValue={submission?.submitted_url || ""} /></label>
            </ActionForm>
            <div className={styles.toolbar}>
              <ActionForm action={verifySubmission} submitLabel="请求验证" disabled={!submission?.submitted_url}><HiddenProject projectId={projectId} /><input type="hidden" name="submission_id" value={submission?.id || ""} /></ActionForm>
              <ActionForm action={blockSubmission} submitLabel="阻断" danger disabled={!submission}><HiddenProject projectId={projectId} /><input type="hidden" name="submission_id" value={submission?.id || ""} /><input type="hidden" name="reason" value="Blocked by Admin operator" /></ActionForm>
            </div>
          </div>
          <div className={styles.panel}>
            <SectionHeader eyebrow="15 · Outcome evidence" title="记录投放测量" />
            <ActionForm action={createMeasurement} submitLabel="保存测量" disabled={!submission || data.queries.data.length === 0}>
              <HiddenProject projectId={projectId} /><input type="hidden" name="submission_id" value={submission?.id || ""} />
              <label>监测查询<select name="monitoring_query_id" required defaultValue=""><option value="" disabled>选择消费者查询</option>{data.queries.data.map((item) => <option key={item.id} value={item.id}>{item.query_text}</option>)}</select></label>
              <label>测量时间<input name="measured_at" type="datetime-local" required /></label>
              <label>结果快照 URI<input name="result_snapshot_uri" type="url" required /></label>
              <label>推荐位置<input name="recommendation_position" type="number" min="1" /></label>
              <label className={styles.check}><input type="checkbox" name="citation_present" />AI 结果引用该投放 URL</label>
              <label>附加指标 JSON<textarea name="metrics" defaultValue={'{"product_mentioned":true,"recommendation_present":true}'} /></label>
            </ActionForm>
          </div>
        </div>
        <div className={styles.panel}>
          <SectionHeader eyebrow="Due collection queue" title="T+28 / T+56 / T+84 采集待办" />
          <ResourceBlock resource={collectionTasks}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.id}>
            <span className={styles.rowHeader}><strong>{item.measurement_window} · {new Date(item.scheduled_for).toLocaleString("zh-CN")}</strong><Status value={item.status} /></span>
            <span className={styles.meta}><span>protocol <ShortId value={item.protocol_id} /></span><span>samples {item.actual_sample_count}/{item.expected_sample_count}</span><span>job <ShortId value={item.job_id} /></span></span>
            {item.status === "open" ? <div className={styles.toolbar}>
              <ActionForm action={completeMeasurementCollectionTask} submitLabel="核对样本并完成"><HiddenProject projectId={projectId} /><input type="hidden" name="task_id" value={item.id} /></ActionForm>
              <ActionForm action={cancelMeasurementCollectionTask} submitLabel="取消待办" danger><HiddenProject projectId={projectId} /><input type="hidden" name="task_id" value={item.id} /><label>原因<input name="reason" required /></label></ActionForm>
            </div> : null}
          </div>)}</div> : <Empty>验证成功后，冻结协议会在到期日生成可操作的采集待办。</Empty>}</ResourceBlock>
        </div>
        <div className={styles.panel}>
          <SectionHeader eyebrow="Measurement lineage" title="历史测量" />
          <ResourceBlock resource={data.measurements}>{(items) => items.length ? <div className={styles.list}>{items.map((item) => <div className={styles.row} key={item.id}>
            <span className={styles.rowHeader}><strong>{new Date(item.measured_at).toLocaleString("zh-CN")}</strong><Status value={item.citation_present ? "citation present" : "not cited"} /></span>
            <span className={styles.meta}><span>query <ShortId value={item.monitoring_query_id} /></span><span>position {item.recommendation_position || "-"}</span><span>{item.result_snapshot_uri}</span></span>
          </div>)}</div> : <Empty>URL 验证后，以冻结监测协议记录 T+28/T+56/T+84 结果。</Empty>}</ResourceBlock>
        </div>
      </div>
    </div>
  </div>;
}
