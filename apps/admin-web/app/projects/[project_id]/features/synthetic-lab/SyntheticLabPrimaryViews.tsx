import { randomUUID } from "node:crypto";

import {
  CorpusOfflineExperimentForms,
  ReviewCaseRunForm,
  SelectedJobControls
} from "./SyntheticLabJobForms";
import { SyntheticLabCopyButton } from "./SyntheticLabCopyButton";
import { SyntheticLabWarnings } from "./SyntheticLabWarnings";
import {
  EmptyState,
  LoadProblem,
  SectionHeading,
  StatusBadge,
  TechnicalMetadata,
  ViewHeader,
  caseModeLabel,
  channelLabel,
  jobKindLabel,
  syntheticHref
} from "./SyntheticLabUI";
import type {
  ReviewSuite,
  SyntheticCandidateEvaluation,
  SyntheticLabView,
  SyntheticWorkspaceData
} from "./syntheticLabTypes";
import styles from "./SyntheticLab.module.css";

const REVIEW_PURPOSES = [
  "synthetic_lab.generation",
  "synthetic_lab.claim_extraction",
  "synthetic_lab.conflict_check",
  "synthetic_lab.revision",
  "synthetic_lab.style_judge",
  "synthetic_lab.arbiter"
] as const;

export function SyntheticOverviewView({
  canContribute,
  data,
  projectId
}: {
  canContribute: boolean;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  const readiness = generationReadiness(data);
  const readyCount = readiness.filter((item) => item.ready).length;
  const ready = readyCount === readiness.length && canContribute;
  const activeJobs = data.jobs.items.filter((job) => [
    "queued", "running", "finalizing", "retry_wait"
  ].includes(job.status));
  const completedJobs = data.jobs.items.filter((job) => job.status === "succeeded");
  return (
    <div className={styles.viewStack}>
      <ViewHeader
        eyebrow="从这里开始"
        title="合成测评实验室"
        description="生成澳洲消费者语气的目标仿真文案，并自动完成事实冲突检查与必要修订。"
        action={(
          <a
            aria-disabled={!canContribute}
            className={`${styles.primaryAction}${!canContribute ? ` ${styles.actionDisabled}` : ""}`}
            href={syntheticHref(projectId, "generate")}
          >
            生成目标仿真文案
          </a>
        )}
      />

      <section className={styles.readinessBand} aria-label="生成准备状态">
        <div className={styles.readinessSummary}>
          <span>生成准备</span>
          <strong>{ready ? "可以开始" : `${readyCount}/${readiness.length} 项就绪`}</strong>
          <p>{ready ? "必要资源已经齐全，可以直接进入生成页。" : "按右侧提示补齐资源；不相关的故障不会阻塞生成。"}</p>
        </div>
        <div className={styles.readinessList}>
          {readiness.map((item) => (
            <a href={syntheticHref(projectId, item.view)} key={item.label}>
              <span className={item.ready ? styles.readinessReady : styles.readinessBlocked}>
                {item.ready ? "已就绪" : "待处理"}
              </span>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
            </a>
          ))}
        </div>
      </section>

      <section className={styles.metricStrip} aria-label="实验室摘要">
        <div><span>运行中任务</span><strong>{activeJobs.length}</strong></div>
        <div><span>已完成任务</span><strong>{completedJobs.length}</strong></div>
        <div><span>可用测评套件</span><strong>{data.suites.items.filter((item) => item.status === "frozen").length}</strong></div>
        <div><span>已验证风格画像</span><strong>{data.profiles.items.filter(isUsableProfile).length}</strong></div>
      </section>

      <section className={styles.section}>
        <SectionHeading
          eyebrow="最近活动"
          title="最近任务"
          aside={<a className={styles.textLink} href={syntheticHref(projectId, "results")}>查看全部任务</a>}
        />
        {data.jobsProblem ? <LoadProblem problem={data.jobsProblem} title="任务列表加载失败" /> : null}
        {!data.jobsProblem && data.jobs.items.length === 0 ? (
          <EmptyState
            title="还没有合成任务"
            description="完成准备后，第一条生成任务会显示在这里。"
            action={<a className={styles.secondaryAction} href={syntheticHref(projectId, "generate")}>打开生成页</a>}
          />
        ) : (
          <JobList data={data} jobs={data.jobs.items.slice(0, 6)} projectId={projectId} />
        )}
      </section>
    </div>
  );
}

export function SyntheticGenerateView({
  canContribute,
  data,
  projectId
}: {
  canContribute: boolean;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  const selectedSuite = data.suites.items.find((item) => item.id === data.selectedSuiteId) || null;
  const readiness = generationReadiness(data);
  const blocked = readiness.filter((item) => !item.ready);
  return (
    <div className={styles.viewStack}>
      <ViewHeader
        eyebrow="主要工作路径"
        title="生成目标仿真文案"
        description="选择一个冻结用例和已批准模型运行时。系统会生成候选文案、检查冲突，并自动修订最多两轮。"
        action={<a className={styles.secondaryAction} href={syntheticHref(projectId, "results")}>查看任务结果</a>}
      />

      <div className={styles.generateLayout}>
        <aside className={styles.generateGuide} aria-label="生成前检查">
          <h4>生成前检查</h4>
          <ol>
            {readiness.map((item) => (
              <li className={item.ready ? styles.guideReady : styles.guideBlocked} key={item.label}>
                <span>{item.ready ? "就绪" : "缺少"}</span>
                <div><strong>{item.label}</strong><small>{item.detail}</small></div>
              </li>
            ))}
          </ol>
          <div className={styles.processPreview}>
            <strong>提交后自动执行</strong>
            <span>生成 4 个候选</span>
            <span>提取声明并检查知识冲突</span>
            <span>必要时自动修订，仍失败则重新生成一批</span>
            <span>输出最终文案与完整判定</span>
          </div>
        </aside>

        <section className={styles.generationTool} aria-labelledby="generation-form-heading">
          <SectionHeading
            eyebrow="一次只运行一个固定用例"
            title="生成配置"
            aside={selectedSuite ? <StatusBadge value={selectedSuite.status} /> : null}
          />
          {data.suitesProblem ? <LoadProblem problem={data.suitesProblem} title="测评套件加载失败" /> : null}
          {data.casesProblem ? <LoadProblem problem={data.casesProblem} title="测评用例加载失败" /> : null}
          {data.runtimeOptionsProblem ? <LoadProblem problem={data.runtimeOptionsProblem} title="模型运行时加载失败" /> : null}
          {data.inventoryProblem ? <LoadProblem problem={data.inventoryProblem} title="生成依赖加载失败" /> : null}
          {!selectedSuite ? (
            <EmptyState
              title="没有可用的冻结测评套件"
              description="先创建用例并冻结套件，再回来生成目标文案。"
              action={<a className={styles.secondaryAction} href={syntheticHref(projectId, "suites")}>管理测评套件</a>}
            />
          ) : (
            <>
              <div className={styles.selectedContext}>
                <span>当前套件</span>
                <strong>{channelLabel(selectedSuite.channel)} · 版本 {selectedSuite.version_number}</strong>
                <small>{selectedSuite.case_count} 个固定用例</small>
              </div>
              <ReviewCaseRunForm
                canContribute={canContribute && blocked.length === 0}
                cases={data.selectedCases.items}
                commandKey={commandKey("review-case-run")}
                defaultCaseId={data.generationDefaults.caseId}
                defaultRuntimeId={data.generationDefaults.runtimeId}
                defaultStylePassThreshold={data.generationDefaults.stylePassThreshold}
                projectId={projectId}
                runtimes={data.runtimeOptions.items}
                suite={selectedSuite}
                variant="primary"
              />
            </>
          )}
        </section>
      </div>
    </div>
  );
}

export function SyntheticResultsView({
  canContribute,
  data,
  projectId
}: {
  canContribute: boolean;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  const job = data.selectedJob;
  const result = data.selectedResult;
  const finalEvaluation = result?.evaluations.find(
    (evaluation) => evaluation.candidate_id === result.resolution_candidate_id
  ) || result?.evaluations.at(-1) || null;
  return (
    <div className={styles.viewStack}>
      <ViewHeader
        eyebrow="运行记录"
        title="任务与结果"
        description="先选择任务，再查看最终文案、知识冲突、风格判定和自动修订记录。"
        action={<a className={styles.primaryAction} href={syntheticHref(projectId, "generate")}>新建生成任务</a>}
      />

      <div className={styles.resultsLayout}>
        <aside className={styles.jobRail}>
          <SectionHeading title="任务列表" aside={<span>{data.jobs.total} 条</span>} />
          {data.jobsProblem ? <LoadProblem problem={data.jobsProblem} title="任务列表加载失败" /> : null}
          {!data.jobsProblem && data.jobs.items.length === 0 ? (
            <EmptyState title="暂无任务" description="提交生成任务后会显示在这里。" />
          ) : <JobList compact data={data} jobs={data.jobs.items} projectId={projectId} />}
        </aside>

        <section className={styles.resultCanvas} aria-live="polite">
          {data.jobProblem ? <LoadProblem problem={data.jobProblem} title="任务详情加载失败" /> : null}
          {!job && !data.jobProblem ? (
            <EmptyState
              title="选择一条任务查看结果"
              description="生成文案任务完成后，这里会显示可直接阅读和复制的最终内容。"
            />
          ) : null}
          {job ? (
            <>
              <div className={styles.resultHeader}>
                <div>
                  <span>{jobKindLabel(job.kind)}</span>
                  <h4>{job.kind === "candidate_generation" ? "目标仿真文案" : jobKindLabel(job.kind)}</h4>
                  <small>任务 ID：{job.id}</small>
                </div>
                <StatusBadge value={result?.status || job.status} />
              </div>
              {!["succeeded", "failed", "dead_lettered", "cancelled"].includes(job.status) ? (
                <div className={styles.runningState}>
                  <strong>{job.status === "retry_wait" ? "任务正在等待重试" : "任务正在后台运行"}</strong>
                  <span>状态更新后刷新本页即可查看最终文案；任务不会因离开页面而中断。</span>
                  <a className={styles.secondaryAction} href={syntheticHref(projectId, "results", { synthetic_job_id: job.id })}>刷新状态</a>
                </div>
              ) : null}
              {data.resultProblem ? <LoadProblem problem={data.resultProblem} title="生成结果加载失败" /> : null}
              {["corpus_finalize", "offline_experiment"].includes(job.kind) ? (
                <SyntheticLabWarnings summary={job.warning_summary || undefined} />
              ) : null}
              {result ? (
                <>
                  <section className={styles.resultSummary} aria-label="生成结果摘要">
                    <div><span>最终状态</span><strong>{resultStatusLabel(result.status)}</strong></div>
                    <div><span>风格得分</span><strong>{finalEvaluation ? `${finalEvaluation.style_score.toFixed(1)} / 5` : "未提供"}</strong></div>
                    <div><span>知识冲突</span><strong>{conflictCount(finalEvaluation)}</strong></div>
                    <div><span>自动修订</span><strong>{result.revisions.length} 轮</strong></div>
                  </section>

                  <section className={styles.finalCopy} aria-labelledby="final-copy-heading">
                    <div className={styles.finalCopyHeader}>
                      <div><span>最终输出</span><h4 id="final-copy-heading">目标仿真文案</h4></div>
                      {result.final_text ? <SyntheticLabCopyButton text={result.final_text} /> : null}
                    </div>
                    {result.final_text ? <pre>{result.final_text}</pre> : (
                      <p>任务未产生可用文案。{result.failure_code ? `失败原因：${issueLabel(result.failure_code)}` : ""}</p>
                    )}
                    {result.warning_codes.length ? (
                      <div className={styles.warningLine}>
                        <strong>可用但需留意</strong>
                        <span>{result.warning_codes.map(issueLabel).join("；")}</span>
                      </div>
                    ) : null}
                  </section>

                  <section className={styles.section}>
                    <SectionHeading
                      eyebrow="系统自动完成"
                      title="冲突检查与修订记录"
                      aside={<span>{result.revisions.length ? `${result.revisions.length} 轮修订` : "无需修订"}</span>}
                    />
                    <ResultTimeline evaluation={finalEvaluation} result={result} />
                  </section>

                  <div className={styles.resultActions}>
                    <a
                      className={styles.secondaryAction}
                      href={syntheticHref(projectId, "generate", {
                        synthetic_suite_id: result.review_suite_version_id || "",
                        synthetic_case_id: result.review_case_id || "",
                        synthetic_runtime_id: result.runtime_selection_id,
                        synthetic_style_threshold: String(result.style_pass_threshold)
                      })}
                    >
                      使用相同配置重新生成
                    </a>
                  </div>

                  <details className={styles.technicalDetails}>
                    <summary>技术信息与完整评估</summary>
                    <TechnicalMetadata items={[
                      { label: "结果哈希", value: result.result_hash },
                      { label: "运行 ID", value: result.review_run_id },
                      { label: "用例 ID", value: result.review_case_id || result.scenario_id },
                      { label: "风格画像 ID", value: result.profile_version_id },
                      { label: "事实快照 ID", value: result.fact_snapshot_id },
                      { label: "模型调用数", value: String(result.model_call_ids.length) },
                      { label: "Dify 工作流尝试数", value: String(result.workflow_attempt_ids.length) }
                    ]} />
                    <EvaluationTable evaluations={result.evaluations} />
                  </details>
                </>
              ) : null}
              {!result && job.status === "succeeded" && job.kind !== "candidate_generation" ? (
                <EmptyState title="该任务已完成" description="此任务不产生目标仿真文案详情，可在对应功能页查看后续资源。" />
              ) : null}
              <SelectedJobControls
                canContribute={canContribute}
                commandKey={commandKey("job-cancel")}
                job={job}
                projectId={projectId}
              />
            </>
          ) : null}
        </section>
      </div>
    </div>
  );
}

export function SyntheticCorpusView({
  canApprove,
  canContribute,
  data,
  projectId
}: {
  canApprove: boolean;
  canContribute: boolean;
  data: SyntheticWorkspaceData;
  projectId: string;
}) {
  return (
    <div className={styles.viewStack}>
      <ViewHeader
        eyebrow="离线验证"
        title="语料与三臂实验"
        description="把已通过或带提醒的文案冻结为候选语料，再与无语料基线和当前批准语料进行配对比较。"
      />
      <section className={styles.metricStrip} aria-label="语料资源摘要">
        <div><span>可纳入的生成结果</span><strong>{data.inventory.review_jobs.length}</strong></div>
        <div><span>候选语料</span><strong>{data.inventory.candidate_corpora.length}</strong></div>
        <div><span>当前批准语料</span><strong>{data.inventory.approved_corpora.length}</strong></div>
        <div><span>冻结问题集</span><strong>{data.inventory.question_sets.length}</strong></div>
      </section>
      {data.inventoryProblem ? <LoadProblem problem={data.inventoryProblem} title="语料资源加载失败" /> : null}
      {data.runtimeOptionsProblem ? <LoadProblem problem={data.runtimeOptionsProblem} title="实验运行时加载失败" /> : null}
      <section className={styles.section}>
        <SectionHeading
          eyebrow="按顺序操作"
          title="冻结候选语料、批准版本并运行实验"
        />
        <CorpusOfflineExperimentForms
          canApprove={canApprove}
          canContribute={canContribute && !data.runtimeOptionsProblem && !data.inventoryProblem}
          commandKeys={{
            candidate: commandKey("corpus-candidate"),
            approve: commandKey("corpus-approve"),
            experiment: commandKey("offline-experiment")
          }}
          inventory={data.inventory}
          projectId={projectId}
          runtimes={data.runtimeOptions.items}
        />
      </section>
    </div>
  );
}

function JobList({
  compact = false,
  data,
  jobs,
  projectId
}: {
  compact?: boolean;
  data: SyntheticWorkspaceData;
  jobs: SyntheticWorkspaceData["jobs"]["items"];
  projectId: string;
}) {
  return (
    <div className={`${styles.jobList}${compact ? ` ${styles.jobListCompact}` : ""}`}>
      {jobs.map((job) => (
        <a
          aria-current={job.id === data.selectedJob?.id ? "true" : undefined}
          className={job.id === data.selectedJob?.id ? styles.jobListItemActive : undefined}
          href={syntheticHref(projectId, "results", { synthetic_job_id: job.id })}
          key={job.id}
        >
          <div><strong>{jobKindLabel(job.kind)}</strong><small>{job.id.slice(0, 8)}</small></div>
          <StatusBadge value={job.status} />
        </a>
      ))}
    </div>
  );
}

function ResultTimeline({
  evaluation,
  result
}: {
  evaluation: SyntheticCandidateEvaluation | null;
  result: NonNullable<SyntheticWorkspaceData["selectedResult"]>;
}) {
  const claims = evaluation?.claim_assessments || [];
  const conflicts = claims.filter((claim) => ["explicit_conflict", "subject_mixup"].includes(claim.status));
  const unknown = claims.filter((claim) => claim.status === "derived_or_unknown");
  return (
    <ol className={styles.resultTimeline}>
      <li>
        <span>1</span>
        <div><strong>候选生成</strong><p>{result.batches.reduce((sum, batch) => sum + batch.candidate_count, 0)} 个候选，{result.batches.length} 个批次。</p></div>
        <StatusBadge value="succeeded" />
      </li>
      <li>
        <span>2</span>
        <div>
          <strong>知识冲突检查</strong>
          <p>{conflicts.length ? `发现 ${conflicts.length} 条明确冲突或主体串用。` : "未在最终候选中发现明确冲突或主体串用。"}{unknown.length ? ` 另有 ${unknown.length} 条推演内容标记为“知识未覆盖”。` : ""}</p>
        </div>
        <StatusBadge value={conflicts.length ? "failed" : unknown.length ? "completed_with_warning" : "passed"} />
      </li>
      {result.revisions.map((revision) => (
        <li key={revision.id}>
          <span>{revision.round_number + 2}</span>
          <div>
            <strong>第 {revision.round_number} 轮自动修订</strong>
            <p>{revision.issue_codes.map(issueLabel).join("；")}</p>
            <small>{revision.provider} · {revision.configured_model}</small>
          </div>
          <StatusBadge value="succeeded" />
        </li>
      ))}
      <li>
        <span>{result.revisions.length + 3}</span>
        <div><strong>最终判定</strong><p>{resultStatusDescription(result.status, result.failure_code)}</p></div>
        <StatusBadge value={result.status} />
      </li>
    </ol>
  );
}

function EvaluationTable({ evaluations }: { evaluations: SyntheticCandidateEvaluation[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead><tr><th>候选</th><th>判定</th><th>风格分</th><th>声明</th><th>问题</th><th>运行时</th></tr></thead>
        <tbody>{evaluations.map((evaluation) => (
          <tr key={evaluation.id}>
            <td><code>{evaluation.candidate_id}</code></td>
            <td><StatusBadge value={evaluation.disposition === "pass" ? "passed" : evaluation.disposition === "warning" ? "completed_with_warning" : "failed"} /></td>
            <td>{evaluation.style_score.toFixed(1)} / 5</td>
            <td>{evaluation.claim_assessments.length}</td>
            <td>{[...evaluation.correctable_issue_codes, ...evaluation.soft_issue_codes].map(issueLabel).join("；") || "无"}</td>
            <td><span>{evaluation.provider}</span><small>{evaluation.configured_model}</small></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function generationReadiness(data: SyntheticWorkspaceData): Array<Readonly<{
  label: string;
  detail: string;
  ready: boolean;
  view: SyntheticLabView;
}>> {
  const frozenSuites = data.suites.items.filter((suite) => suite.status === "frozen" && suite.case_count > 0);
  const profiles = data.profiles.items.filter(isUsableProfile);
  const runtimes = data.runtimeOptions.items.filter((runtime) => runtime.capture_method === "provider_api"
    && runtime.allowed_search_modes.includes(null)
    && REVIEW_PURPOSES.every((purpose) => runtime.allowed_purposes.includes(purpose)));
  const promptPurposes = new Set(data.inventory.prompt_bindings.map((item) => item.label.split(" · ")[0]));
  return [
    {
      label: "冻结测评套件",
      detail: frozenSuites.length ? `${frozenSuites.length} 个套件可用` : "需要至少 1 个含用例的冻结套件",
      ready: !data.suitesProblem && frozenSuites.length > 0,
      view: "suites"
    },
    {
      label: "风格画像",
      detail: profiles.length ? `${profiles.length} 个已验证版本` : "需要已冻结且构建验证通过的风格画像",
      ready: !data.profilesProblem && profiles.length > 0,
      view: "style"
    },
    {
      label: "事实快照",
      detail: data.inventory.fact_snapshots.length ? `${data.inventory.fact_snapshots.length} 个可用快照` : "需要当前可用的 Fact 快照",
      ready: !data.inventoryProblem && data.inventory.fact_snapshots.length > 0,
      view: "suites"
    },
    {
      label: "生成与检查流程",
      detail: REVIEW_PURPOSES.every((purpose) => promptPurposes.has(purpose)) ? "6 条 Prompt / Dify 绑定齐全" : "需要生成、声明提取、冲突检查、修订、风格判定和仲裁绑定",
      ready: !data.inventoryProblem && REVIEW_PURPOSES.every((purpose) => promptPurposes.has(purpose)),
      view: "settings"
    },
    {
      label: "模型运行时",
      detail: runtimes.length ? `${runtimes.length} 个已批准运行时` : "需要支持完整生成链路的 Provider API 运行时",
      ready: !data.runtimeOptionsProblem && runtimes.length > 0,
      view: "settings"
    }
  ];
}

function isUsableProfile(profile: SyntheticWorkspaceData["profiles"]["items"][number]): boolean {
  return profile.status === "frozen"
    && profile.build_verification_status === "verified"
    && !profile.rebuild_required;
}

function conflictCount(evaluation: SyntheticCandidateEvaluation | null): number {
  return evaluation?.claim_assessments.filter((claim) => [
    "explicit_conflict", "subject_mixup"
  ].includes(claim.status)).length || 0;
}

function resultStatusLabel(status: string): string {
  return {
    passed: "通过",
    completed_with_warning: "可用，带提醒",
    failed: "未生成合格文案"
  }[status] || status;
}

function resultStatusDescription(status: string, failureCode: string | null): string {
  if (status === "passed") return "文案通过事实、主体与风格检查。";
  if (status === "completed_with_warning") return "文案可以进入离线实验，提醒项会单独统计。";
  return `没有候选通过最终判定${failureCode ? `：${issueLabel(failureCode)}` : "。"}`;
}

function issueLabel(code: string): string {
  return {
    derived_or_unknown: "知识库未覆盖的推演内容",
    explicit_conflict: "与当前批准事实冲突",
    subject_mixup: "商品或竞品主体串用",
    style_below_threshold: "风格得分低于阈值",
    no_candidate_passed: "没有候选通过检查"
  }[code] || code;
}

function commandKey(scope: string): string {
  return `synthetic-${scope}-${randomUUID()}`;
}
