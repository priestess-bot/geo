"use client";

import { useActionState, useEffect, useMemo, useState } from "react";

import {
  enqueueDirectGenerationAction,
  refreshSyntheticJobAction
} from "./syntheticLabJobActions";
import { SyntheticActionFeedback } from "./SyntheticActionFeedback";
import { SyntheticLabCopyButton } from "./SyntheticLabCopyButton";
import {
  initialSyntheticActionState,
  type DirectGenerationSubject,
  type DirectKnowledgeItem,
  type SyntheticJob,
  type SyntheticChannel,
  type SyntheticReviewResult,
  type SyntheticRuntimeOption,
  type SyntheticWorkspaceData
} from "./syntheticLabTypes";
import {
  LoadProblem,
  StatusBadge,
  channelLabel,
  statusLabel,
  syntheticHref
} from "./SyntheticLabUI";
import styles from "./SyntheticLab.module.css";

const REVIEW_PURPOSES = [
  "synthetic_lab.generation",
  "synthetic_lab.claim_extraction",
  "synthetic_lab.conflict_check",
  "synthetic_lab.revision",
  "synthetic_lab.style_judge",
  "synthetic_lab.arbiter"
] as const;

export function SyntheticGenerationWorkbench({
  canContribute,
  commandKey: initialCommandKey,
  data,
  projectId
}: {
  canContribute: boolean;
  commandKey: string;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  const stylesByChannel = useMemo(
    () => new Map(data.directOptions.channel_styles.map((item) => [item.channel, item])),
    [data.directOptions.channel_styles]
  );
  const initialChannel = stylesByChannel.has("reddit")
    ? "reddit"
    : data.directOptions.channel_styles[0]?.channel || "reddit";
  const [channel, setChannel] = useState(initialChannel);
  const [subjectId, setSubjectId] = useState(
    data.directOptions.subjects.find((item) => item.name.includes("V600"))?.id
      || data.directOptions.subjects[0]?.id
      || ""
  );
  const [includeCompetitor, setIncludeCompetitor] = useState(false);
  const [commandKey, setCommandKey] = useState(initialCommandKey);
  const [actionState, formAction, pending] = useActionState(
    enqueueDirectGenerationAction,
    initialSyntheticActionState
  );
  const [jobs, setJobs] = useState(data.jobs.items);
  const [selectedJob, setSelectedJob] = useState<SyntheticJob | null>(
    data.selectedJob || data.jobs.items[0] || null
  );
  const [result, setResult] = useState<SyntheticReviewResult | null>(data.selectedResult);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const subject = data.directOptions.subjects.find((item) => item.id === subjectId)
    || data.directOptions.subjects[0]
    || null;
  const style = stylesByChannel.get(channel) || null;
  const runtimes = eligibleRuntimes(data.runtimeOptions.items);
  const selectedRuntimeId = data.generationDefaults.runtimeId
    && runtimes.some((item) => item.selection_id === data.generationDefaults.runtimeId)
    ? data.generationDefaults.runtimeId
    : runtimes[0]?.selection_id || "";
  const knowledgeHash = includeCompetitor
    ? subject?.competitor_knowledge_snapshot_hash
    : subject?.knowledge_snapshot_hash;
  const previewKnowledge = includeCompetitor
    ? subject?.competitor_knowledge_items || []
    : subject?.knowledge_items || [];
  const canGenerate = canContribute && Boolean(
    style && subject && knowledgeHash && selectedRuntimeId && !data.directOptionsProblem
  );

  useEffect(() => {
    if (!actionState.job) return;
    setJobs((current) => [
      actionState.job!,
      ...current.filter((item) => item.id !== actionState.job!.id)
    ].slice(0, 10));
    setSelectedJob(actionState.job);
    setResult(null);
    setRefreshMessage(null);
    setCommandKey(`direct-generation:${crypto.randomUUID()}`);
  }, [actionState.responseToken, actionState.job]);

  useEffect(() => {
    if (!selectedJob || result?.job_id === selectedJob.id
        || (terminal(selectedJob.status) && selectedJob.status !== "succeeded")) {
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      setRefreshing(true);
      const next = await refreshSyntheticJobAction(projectId, selectedJob.id);
      if (cancelled) return;
      setRefreshing(false);
      if (!next.ok || !next.job) {
        setRefreshMessage(next.message || "任务状态读取失败，可以稍后重试。");
        return;
      }
      setRefreshMessage(null);
      setSelectedJob(next.job);
      setJobs((current) => current.map((item) => item.id === next.job!.id ? next.job! : item));
      if (next.result) setResult(next.result);
      if (!terminal(next.job.status)) timer = setTimeout(refresh, 2000);
    };
    void refresh();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [projectId, result?.job_id, selectedJob?.id, selectedJob?.status]);

  async function openJob(job: SyntheticJob) {
    setSelectedJob(job);
    setResult(null);
    setRefreshMessage(null);
    setRefreshing(true);
    const next = await refreshSyntheticJobAction(projectId, job.id);
    setRefreshing(false);
    if (!next.ok || !next.job) {
      setRefreshMessage(next.message || "任务读取失败，可以重试。");
      return;
    }
    setSelectedJob(next.job);
    if (next.result) setResult(next.result);
  }

  return (
    <div className={styles.directWorkspace}>
      <div className={styles.directTopGrid}>
        <section className={styles.directComposer} aria-labelledby="direct-generation-heading">
          <div className={styles.directSectionHeader}>
            <div>
              <p>生成工作台</p>
              <h3 id="direct-generation-heading">生成一条仿真用户文案</h3>
            </div>
            <span className={styles.contextBadge}>澳洲英语 · 内部仿真</span>
          </div>

          {data.directOptionsProblem ? (
            <LoadProblem problem={data.directOptionsProblem} title="产品与风格加载失败" />
          ) : null}
          {data.runtimeOptionsProblem ? (
            <LoadProblem problem={data.runtimeOptionsProblem} title="模型加载失败" />
          ) : null}

          <form action={formAction} className={styles.directForm}>
            <input name="project_id" type="hidden" value={projectId} />
            <input name="idempotency_key" type="hidden" value={commandKey} />
            <input name="channel_style_version_id" type="hidden" value={style?.id || ""} />
            <input name="channel_style_hash" type="hidden" value={style?.style_hash || ""} />
            <input name="knowledge_snapshot_hash" type="hidden" value={knowledgeHash || ""} />
            <input name="include_competitor_context" type="hidden" value={String(includeCompetitor)} />

            <div className={styles.directFieldGrid}>
              <label>
                <span>发布渠道</span>
                <select name="channel" value={channel} onChange={(event) => setChannel(event.target.value as SyntheticChannel)}>
                  {data.directOptions.channel_styles.map((item) => (
                    <option key={item.channel} value={item.channel}>{channelLabel(item.channel)}</option>
                  ))}
                </select>
                <small>{style ? `风格版本 ${style.version_number}` : "该渠道还没有风格设置"}</small>
              </label>
              <label>
                <span>目标产品</span>
                <select name="subject_entity_id" value={subject?.id || ""} onChange={(event) => setSubjectId(event.target.value)}>
                  {data.directOptions.subjects.map((item) => (
                    <option disabled={!item.knowledge_snapshot_hash} key={item.id} value={item.id}>
                      {item.name}{item.knowledge_snapshot_hash ? "" : "（缺少产品证据）"}
                    </option>
                  ))}
                </select>
                <small>{previewKnowledge.length} 条已批准事实将作为模型上下文</small>
              </label>
            </div>

            <label className={styles.goalField}>
              <span>生成目标</span>
              <textarea
                name="generation_goal"
                placeholder={`例如：写一段适合 ${channelLabel(channel)} 的用户短评，说明 ${subject?.name || "所选产品"} 适合什么场景，并诚实说明已知信息的边界。`}
                required
                rows={6}
              />
              <small>描述读者、场景和希望强调的重点；这段文字只作为创意参考。</small>
            </label>

            <label>
              <span>模型</span>
              <select defaultValue={selectedRuntimeId} name="runtime_selection_id">
                {runtimes.map((runtime) => (
                  <option key={runtime.selection_id} value={runtime.selection_id}>
                    {runtime.provider} · {runtime.configured_model}
                  </option>
                ))}
              </select>
              {!runtimes.length ? <small className={styles.fieldError}>没有覆盖六步审核流程的可用模型</small> : null}
            </label>

            <details className={styles.advancedPanel}>
              <summary>高级设置与实际输入</summary>
              <div className={styles.advancedContent}>
                <label className={styles.checkboxRow}>
                  <input
                    checked={includeCompetitor}
                    disabled={!subject?.competitor_knowledge_snapshot_hash}
                    onChange={(event) => setIncludeCompetitor(event.target.checked)}
                    type="checkbox"
                  />
                  <span>加入有证据支持的竞品上下文</span>
                </label>
                <label className={styles.thresholdField}>
                  <span>风格通过阈值</span>
                  <input
                    defaultValue={data.generationDefaults.stylePassThreshold}
                    max="5"
                    min="0"
                    name="style_pass_threshold"
                    step="0.1"
                    type="number"
                  />
                </label>
                <div className={styles.frozenContext}>
                  <strong>本次渠道风格</strong>
                  <p>{style?.directive || "尚未设置"}</p>
                </div>
                <KnowledgeList items={previewKnowledge} title="提交时冻结的知识" />
              </div>
            </details>

            {!style ? (
              <p className={styles.blockingMessage}>请先在“渠道风格”中填写该渠道的风格说明。</p>
            ) : null}
            {subject && !knowledgeHash ? (
              <p className={styles.blockingMessage}>该产品缺少当前有效的已批准事实，请先在知识库中审核事实。</p>
            ) : null}
            <div className={styles.formActions}>
              <button className={styles.generateButton} disabled={!canGenerate || pending} type="submit">
                {pending ? "正在创建任务…" : "生成仿真文案"}
              </button>
              <span>自动执行：生成 → 声明提取 → 冲突检查 → 必要修订 → 风格判定</span>
            </div>
          </form>
          <SyntheticActionFeedback state={actionState} />
        </section>

        <HistoryRail
          currentPage={data.jobPage}
          jobs={jobs}
          onOpen={openJob}
          projectId={projectId}
          selectedJobId={selectedJob?.id || null}
          total={data.jobs.total}
        />
      </div>

      <GenerationResult
        job={selectedJob}
        message={refreshMessage}
        refreshing={refreshing}
        result={result}
      />
    </div>
  );
}

function HistoryRail({
  currentPage,
  jobs,
  onOpen,
  projectId,
  selectedJobId,
  total
}: {
  currentPage: number;
  jobs: SyntheticJob[];
  onOpen: (job: SyntheticJob) => void;
  projectId: string;
  selectedJobId: string | null;
  total: number;
}) {
  const pages = Math.max(1, Math.ceil(total / 10));
  return (
    <aside className={styles.historyRail} aria-label="生成记录">
      <div className={styles.directSectionHeader}>
        <div><p>最近记录</p><h3>生成历史</h3></div>
        <span>{total} 条</span>
      </div>
      {!jobs.length ? <p className={styles.historyEmpty}>还没有生成记录。</p> : null}
      <div className={styles.historyList}>
        {jobs.map((job) => (
          <button
            className={`${styles.historyItem}${job.id === selectedJobId ? ` ${styles.historyItemActive}` : ""}`}
            key={job.id}
            onClick={() => void onOpen(job)}
            type="button"
          >
            <span>{statusLabel(job.status)}</span>
            <strong>{historyTitle(job.status)}</strong>
            <small>{job.id.slice(0, 8)} · {job.input_hash.slice(0, 8)}</small>
          </button>
        ))}
      </div>
      {pages > 1 ? (
        <nav className={styles.pagination} aria-label="生成历史分页">
          <a
            aria-disabled={currentPage <= 1}
            href={syntheticHref(projectId, "generate", { synthetic_page: String(Math.max(1, currentPage - 1)) })}
          >上一页</a>
          <span>{currentPage} / {pages}</span>
          <a
            aria-disabled={currentPage >= pages}
            href={syntheticHref(projectId, "generate", { synthetic_page: String(Math.min(pages, currentPage + 1)) })}
          >下一页</a>
        </nav>
      ) : null}
    </aside>
  );
}

function GenerationResult({
  job,
  message,
  refreshing,
  result
}: {
  job: SyntheticJob | null;
  message: string | null;
  refreshing: boolean;
  result: SyntheticReviewResult | null;
}) {
  if (!job) {
    return (
      <section className={styles.resultWorkspace}>
        <div className={styles.resultPlaceholder}>
          <strong>生成结果会显示在这里</strong>
          <span>提交后无需跳转页面，任务状态和最终文案会自动更新。</span>
        </div>
      </section>
    );
  }
  const finalEvaluation = result?.evaluations.find(
    (item) => item.candidate_id === result.resolution_candidate_id
  ) || result?.evaluations.at(-1) || null;
  return (
    <section className={styles.resultWorkspace} aria-live="polite">
      <div className={styles.resultTitleRow}>
        <div>
          <p>任务结果</p>
          <h3>{result ? channelLabel(result.channel) : "正在生成"}</h3>
        </div>
        <StatusBadge value={result?.status || job.status} />
      </div>
      <RunProgress job={job} result={result} />
      {refreshing && !result ? <p className={styles.refreshNote}>正在同步最新状态…</p> : null}
      {message ? <p className={styles.blockingMessage}>{message} 你可以重新点击左侧记录重试读取。</p> : null}
      {terminal(job.status) && job.status !== "succeeded" ? (
        <div className={styles.resultFailure}>
          <strong>任务未生成可用文案</strong>
          <span>状态：{statusLabel(job.status)}。输入不会被锁定，可以修正后重新提交。</span>
        </div>
      ) : null}
      {result ? (
        <>
          <div className={styles.finalCopyBlock}>
            <div><span>最终文案</span><SyntheticLabCopyButton text={result.final_text || ""} /></div>
            <p>{result.final_text || "本次没有可用的最终文案。"}</p>
          </div>
          <div className={styles.resultMetrics}>
            <div><span>风格评分</span><strong>{finalEvaluation ? `${finalEvaluation.style_score.toFixed(1)} / 5` : "-"}</strong></div>
            <div><span>候选数量</span><strong>{result.batches.reduce((sum, item) => sum + item.candidate_count, 0)}</strong></div>
            <div><span>修订轮次</span><strong>{result.revisions.length}</strong></div>
            <div><span>知识声明</span><strong>{finalEvaluation?.claim_assessments.length || 0}</strong></div>
          </div>
          {result.warning_codes.length ? (
            <div className={styles.resultWarning}>
              <strong>需要注意</strong>
              <span>{result.warning_codes.map(warningLabel).join("；")}</span>
            </div>
          ) : null}
          <KnowledgeList items={result.knowledge_context_items} title="本次实际调用的知识" showUsage />
          <details className={styles.executionDetails}>
            <summary>查看冲突检查与修订明细</summary>
            <div className={styles.executionDetailGrid}>
              <div><span>生成批次</span><strong>{result.batches.length}</strong></div>
              <div><span>候选评估</span><strong>{result.evaluations.length}</strong></div>
              <div><span>自动修订</span><strong>{result.revisions.length}</strong></div>
              <div><span>Dify 调用</span><strong>{result.workflow_attempt_ids.length}</strong></div>
            </div>
          </details>
        </>
      ) : null}
    </section>
  );
}

function RunProgress({ job, result }: { job: SyntheticJob; result: SyntheticReviewResult | null }) {
  const current = result ? 4 : job.status === "queued" ? 1 : job.status === "finalizing" ? 3 : 2;
  const labels = ["任务已提交", "生成与冲突检查", "修订与风格判定", "结果完成"];
  return (
    <ol className={styles.runProgress}>
      {labels.map((label, index) => (
        <li className={index + 1 <= current ? styles.progressDone : ""} key={label}>
          <span>{index + 1}</span><strong>{label}</strong>
        </li>
      ))}
    </ol>
  );
}

function KnowledgeList({
  items,
  showUsage = false,
  title
}: {
  items: readonly DirectKnowledgeItem[];
  showUsage?: boolean;
  title: string;
}) {
  return (
    <div className={styles.knowledgeContext}>
      <div className={styles.knowledgeContextHeader}><strong>{title}</strong><span>{items.length} 条</span></div>
      {!items.length ? <p>没有可用知识。</p> : null}
      {items.map((item) => (
        <article className={styles.knowledgeContextItem} key={`${item.evidence_id}:${item.snapshot_hash}`}>
          <div>
            <strong>{item.subject_name}</strong>
            {showUsage ? (
              <span className={item.conflicting ? styles.knowledgeConflict : item.matched ? styles.knowledgeUsed : styles.knowledgeUnused}>
                {item.conflicting ? "发现冲突" : item.matched ? "已匹配" : "已提供，未引用"}
              </span>
            ) : <span>{item.kind === "approved_fact" ? "已批准事实" : "来源证据"}</span>}
          </div>
          <p>{item.summary}</p>
          <a href={item.trace_href}>查看证据与追溯链</a>
        </article>
      ))}
    </div>
  );
}

function eligibleRuntimes(items: SyntheticRuntimeOption[]): SyntheticRuntimeOption[] {
  return items.filter((item) => item.capture_method === "provider_api"
    && item.allowed_search_modes.includes(null)
    && REVIEW_PURPOSES.every((purpose) => item.allowed_purposes.includes(purpose)));
}

function terminal(status: SyntheticJob["status"]): boolean {
  return ["succeeded", "failed", "dead_lettered", "cancelled"].includes(status);
}

function historyTitle(status: SyntheticJob["status"]): string {
  return {
    queued: "等待执行",
    running: "正在生成",
    finalizing: "正在整理结果",
    retry_wait: "等待自动重试",
    succeeded: "查看生成结果",
    failed: "生成失败",
    dead_lettered: "需要人工处理",
    cancelled: "任务已取消"
  }[status] || "查看任务";
}

function warningLabel(code: string): string {
  return {
    derived_or_unknown: "包含知识库未覆盖的推演，已单独标记",
    completed_with_warning: "已生成，但包含需要查看的提示",
    subject_mixup: "检测到商品主体混用",
    explicit_fact_conflict: "检测到与已批准事实冲突"
  }[code] || code.replaceAll("_", " ");
}
