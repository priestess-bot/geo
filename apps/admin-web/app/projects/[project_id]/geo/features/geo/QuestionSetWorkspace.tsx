import type {
  KnowledgeQuestionCandidateView,
  KnowledgeQuestionFactView,
  KnowledgeQuestionGenerationView,
  KnowledgeQuestionSetView
} from "@geo/types/geo";
import type { ReactNode } from "react";

import { QuestionJobWatcher } from "../../../features/workflow-c/QuestionJobWatcher";
import { QuestionFactPicker } from "../../../features/workflow-c/QuestionFactPicker";
import { QuestionCoverageReview } from "../../../features/workflow-c/QuestionCoverageReview";
import type {
  QuestionStep,
  QuestionWorkspaceData
} from "../../../features/workflow-c/questionWorkspaceData";
import { questionWorkspaceHref } from "../../../features/workflow-c/questionWorkspaceLinks";
import layoutStyles from "../../../features/workflow-c/QuestionWorkspace.module.css";
import layoutResponsiveStyles from "../../../features/workflow-c/QuestionWorkspaceResponsive.module.css";
import reviewStyles from "../../../features/workflow-c/QuestionReviewWorkspace.module.css";
import reviewResponsiveStyles from "../../../features/workflow-c/QuestionReviewResponsive.module.css";
import { mergeCssModules } from "../../../features/workflow-c/cssModules";
import { ActionForm } from "./ActionForm";
import {
  bindQuestionSetToProtocol,
  createQuestionCoveragePack,
  createQuestionGeneration,
  createQuestionSet,
  resumeQuestionCoveragePack,
  reviewQuestionCandidate,
  transitionQuestionSet
} from "./question-set-actions";
import {
  Empty,
  HiddenProject,
  ResourceBlock,
  ShortId,
  Status,
  TechnicalInfo
} from "./common";

export type QuestionSetWorkspaceData = QuestionWorkspaceData;

const questionStyles = mergeCssModules(
  layoutStyles,
  layoutResponsiveStyles,
  reviewStyles,
  reviewResponsiveStyles
);

type WorkspaceProps = Readonly<{
  activeStep: QuestionStep;
  campaignName: string;
  data: QuestionSetWorkspaceData;
  embedded?: boolean;
  projectId: string;
}>;

export function QuestionSetWorkspace({
  activeStep,
  campaignName,
  data,
  embedded = true,
  projectId
}: WorkspaceProps) {
  const campaignId = data.selection.campaignId || "";
  const facts = data.questionFacts.data.filter(
    (fact) => fact.status === "approved" && fact.lifecycle_status === "active"
  );
  const jobs = [...data.questionGenerations.data].sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)
  );
  const selectedJob = jobs.find(
    (job) => job.job_id === data.selection.questionGenerationJobId
  ) || jobs[0];
  const candidates = data.questionCandidates.data;
  const approvedCandidates = candidates.filter((item) => item.workflow_status === "approved");
  const factLabels = new Map(
    data.questionFacts.data.map((fact) => [
      fact.id,
      `${fact.source_title} · ${fact.statement}`
    ])
  );
  const defaultFactIds = Array.from(new Set(
    candidates.flatMap((candidate) => candidate.fact_source_ids)
  ));

  return <div className={questionStyles.workArea} aria-label="测试问题工作区">
    <aside className={questionStyles.jobRail} aria-label="生成记录">
      <div className={questionStyles.railHeading}>
        <div><strong>生成记录</strong><span>{jobs.length} 次</span></div>
        <a href={questionWorkspaceHref({
          campaignId,
          embedded,
          projectId,
          step: "generate"
        })} aria-label="新建生成任务">+</a>
      </div>
      <ResourceBlock resource={data.questionGenerations}>{() => jobs.length
        ? <div className={questionStyles.jobList}>{jobs.map((job, index) => (
          <JobRow
            campaignId={campaignId}
            embedded={embedded}
            index={jobs.length - index}
            job={job}
            key={job.job_id}
            projectId={projectId}
            selected={job.job_id === selectedJob?.job_id}
          />
        ))}</div>
        : <Empty>还没有生成记录。</Empty>}
      </ResourceBlock>
    </aside>

    <main className={questionStyles.stepContent}>
      {selectedJob ? <div className={questionStyles.mobileJobSummary}>
        <span>当前记录</span>
        <strong>生成 #{jobs.findIndex((item) => item.job_id === selectedJob.job_id) + 1}</strong>
        <Status value={selectedJob.status} />
      </div> : null}

      {activeStep === "generate" ? <ResourceBlock resource={data.questionFacts}>{() => (
        <GenerationStep
          campaignId={campaignId}
          embedded={embedded}
          defaultFactIds={defaultFactIds}
          facts={facts}
          projectId={projectId}
          selectedJob={selectedJob}
        />
      )}</ResourceBlock> : null}

      {activeStep === "review" ? <ResourceBlock resource={data.questionCandidates}>{() => (
        <ReviewStep
          approvedCandidates={approvedCandidates}
          campaignId={campaignId}
          campaignName={campaignName}
          candidates={candidates}
          embedded={embedded}
          factLabels={factLabels}
          projectId={projectId}
          selectedJob={selectedJob}
        />
      )}</ResourceBlock> : null}

      {activeStep === "sets" ? <QuestionSetsStep
        approvedCandidates={approvedCandidates}
        campaignId={campaignId}
        campaignName={campaignName}
        data={data}
        projectId={projectId}
        selectedJob={selectedJob}
      /> : null}
    </main>
  </div>;
}

function JobRow({
  campaignId,
  embedded,
  index,
  job,
  projectId,
  selected
}: {
  campaignId: string;
  embedded: boolean;
  index: number;
  job: KnowledgeQuestionGenerationView;
  projectId: string;
  selected: boolean;
}) {
  const targetStep: QuestionStep = job.status === "succeeded" ? "review" : "generate";
  return <article
    className={selected ? questionStyles.selectedJob : questionStyles.jobRow}
    data-testid="question-generation-job"
  >
    <a href={questionWorkspaceHref({
      campaignId,
      embedded,
      projectId,
      questionGenerationJobId: job.job_id,
      step: targetStep
    })}>
      <span className={questionStyles.jobTitle}>
        <strong>生成 #{index}</strong><Status value={job.status} />
      </span>
      <span className={questionStyles.jobMeta}>
        {formatTime(job.created_at)} · {job.candidate_count
          ?? job.checkpoint_candidate_count
          ?? 0} 条候选
      </span>
      {job.generation_mode === "coverage_pack" ? <span className={questionStyles.jobMeta}>
        100 题覆盖库 · {job.completed_batch_count}/{job.batch_count} 批
      </span> : null}
      <span className={questionStyles.jobMeta}>{actualModelLabel(job)}</span>
    </a>
    <TechnicalInfo>
      <span>请求模型 {job.configured_model}</span>
      <span>{job.adapter_release}</span>
      <code>{job.input_hash}</code>
      {job.artifact_hash ? <code>{job.artifact_hash}</code> : null}
    </TechnicalInfo>
    {selected ? <QuestionJobWatcher status={job.status} /> : null}
  </article>;
}

function GenerationStep({ campaignId, defaultFactIds, embedded, facts, projectId, selectedJob }: {
  campaignId: string;
  defaultFactIds: readonly string[];
  embedded: boolean;
  facts: KnowledgeQuestionFactView[];
  projectId: string;
  selectedJob?: KnowledgeQuestionGenerationView;
}) {
  return <section className={questionStyles.stepPanel} aria-labelledby="generate-title">
    <StepHeading
      description="为当前产品一次生成完整的澳洲消费者测量问题库；同一批问题可原样用于所有搜索引擎。"
      title="生成 100 个测试问题"
      titleId="generate-title"
    />
    <div className={questionStyles.guidance}>
      <strong>默认覆盖已经配置好</strong>
      <span>系统自动读取当前产品的已批准知识，生成 90 个非品牌主问题和 10 个品牌控制问题。你无需选择知识条目或逐个填写场景。</span>
    </div>
    <div className={questionStyles.coveragePreset}>
      <div className={questionStyles.presetHeader}>
        <div><span>澳洲跨引擎均衡配置</span><strong>完整 100 题测量库</strong></div>
        <span>en-AU · 第 1 轮</span>
      </div>
      <dl className={questionStyles.presetMetrics}>
        <div><dt>类别基准</dt><dd>50</dd></div>
        <div><dt>产品适配</dt><dd>40</dd></div>
        <div><dt>品牌控制</dt><dd>10</dd></div>
        <div><dt>主题</dt><dd>10</dd></div>
      </dl>
      <ActionForm
        action={createQuestionCoveragePack}
        disabled={!campaignId || !facts.length}
        pendingLabel="正在创建 100 题任务..."
        refreshOnSuccess
        submitLabel="生成完整 100 题"
      >
        <HiddenProject projectId={projectId} />
        <input name="campaign_id" type="hidden" value={campaignId} />
        <details className={questionStyles.advancedSettings}>
          <summary>高级设置</summary>
          <label>补充要求（可选）
            <textarea name="custom_requirements" maxLength={120}
              placeholder="例如：额外关注斜坡、狭窄通道或可更换电池；不要在这里粘贴指令或知识全文。" />
          </label>
          <div className={questionStyles.twoColumns}>
            <label>语义重复阈值<input name="semantic_duplicate_threshold" type="number"
              min="0.8" max="1" step="0.0001" defaultValue="0.92" /></label>
            <label>模型调用预算<input name="model_call_budget" type="number"
              min="30" max="1000" defaultValue="60" /></label>
          </div>
        </details>
      </ActionForm>
      {!facts.length ? <p className={questionStyles.presetWarning}>
        当前项目还没有可用的已批准知识，暂时不能生成。
      </p> : null}
    </div>

    <details className={questionStyles.legacyGenerator}>
      <summary>只生成一个自定义问题（兼容旧流程）</summary>
    <div className={questionStyles.generationForm}>
        <ActionForm
          action={createQuestionGeneration}
          disabled={!campaignId || !facts.length}
          pendingLabel="正在创建任务..."
          refreshOnSuccess
          submitLabel="生成候选问题"
        >
          <HiddenProject projectId={projectId} />
          <input name="campaign_id" type="hidden" value={campaignId} />
          {facts.length
            ? <QuestionFactPicker
              defaultFactIds={defaultFactIds}
              facts={facts}
              key={`${campaignId}:${selectedJob?.job_id || "new"}`}
            />
            : <Empty>知识库中没有已批准且启用的事实。</Empty>}

          <fieldset>
            <legend>2. 描述要覆盖的搜索场景</legend>
            <div className={questionStyles.twoColumns}>
              <label>目标人群<input name="persona" required placeholder="例如：澳洲独栋住宅业主" /></label>
              <label>产品或主题<input name="subject" required placeholder="例如：机器人割草机" /></label>
            </div>
            <label>具体场景<textarea name="scenario" required
              placeholder="例如：为 800 平方米、有斜坡的草坪寻找无需埋线且维护简单的割草机" /></label>
            <label>用户意图<input name="intent" required
              placeholder="例如：比较适合的产品并了解避障和安装差异" /></label>
          </fieldset>

          <fieldset>
            <legend>3. 设置问题范围</legend>
            <div className={questionStyles.twoColumns}>
              <label>用户决策位置<select name="funnel" defaultValue="consideration">
                <option value="awareness">初步了解</option>
                <option value="consideration">比较考虑</option>
                <option value="decision">购买决策</option>
                <option value="retention">使用与复购</option>
              </select></label>
              <label>问题类型<select name="query_kind" defaultValue="recommendation">
                <option value="recommendation">推荐</option>
                <option value="comparison">比较</option>
                <option value="research">信息调研</option>
                <option value="support">使用支持</option>
              </select></label>
              <label>目标界面<select name="platform" defaultValue="chatgpt_search">
                <option value="chatgpt_search">ChatGPT Search</option>
                <option value="google_ai_overviews">Google AI Overviews</option>
                <option value="google_search">Google Search</option>
                <option value="perplexity">Perplexity</option>
                <option value="gemini">Gemini</option>
                <option value="other">其他</option>
              </select></label>
              <label>品牌范围<select name="brand_scope" defaultValue="non_brand">
                <option value="non_brand">非品牌搜索</option>
                <option value="brand">品牌搜索</option>
                <option value="competitor">竞品搜索</option>
              </select></label>
              <label>市场<input name="region" required defaultValue="AU" /></label>
              <label>语言<input name="language" required defaultValue="en-AU" /></label>
            </div>
          </fieldset>

          <details className={questionStyles.advancedSettings}>
            <summary>高级设置</summary>
            <div className={questionStyles.twoColumns}>
              <label>批准图谱实体 ID<textarea name="graph_entity_ids" /></label>
              <label>竞品实体 ID<input name="competitor_entity_id" /></label>
              <label>语义重复阈值<input name="semantic_duplicate_threshold" type="number"
                min="0.8" max="1" step="0.0001" defaultValue="0.92" /></label>
              <label>模型调用预算<input name="model_call_budget" type="number"
                min="1" max="1000" defaultValue="60" /></label>
            </div>
          </details>
        </ActionForm>
    </div>
    </details>

    {selectedJob ? <div className={questionStyles.currentJob}>
      <div><span>最近任务</span><strong>任务 <ShortId value={selectedJob.job_id} /></strong></div>
      <Status value={selectedJob.status} />
      <span>{selectedJob.candidate_count ?? selectedJob.checkpoint_candidate_count ?? 0} 条候选</span>
      {selectedJob.generation_mode === "coverage_pack" ? <div className={questionStyles.batchProgress}>
        <span>批次进度 {selectedJob.completed_batch_count}/{selectedJob.batch_count}</span>
        <progress max={selectedJob.batch_count || 10}
          value={selectedJob.completed_batch_count} />
      </div> : null}
      <QuestionJobWatcher status={selectedJob.status} />
      {selectedJob.status === "succeeded" ? <a className={questionStyles.reviewLink}
        href={questionWorkspaceHref({
          campaignId,
          embedded,
          projectId,
          questionGenerationJobId: selectedJob.job_id,
          step: "review"
        })}>审核候选</a> : null}
      {selectedJob.error_code ? <span className={questionStyles.jobError}>
        失败原因：{selectedJob.error_code}。可从已经保存的批次继续，不必重新生成整套问题。
      </span> : null}
      {selectedJob.generation_mode === "coverage_pack"
        && ["failed", "dead_lettered"].includes(selectedJob.status)
        ? <ActionForm
          action={resumeQuestionCoveragePack}
          pendingLabel="正在恢复..."
          refreshOnSuccess
          submitLabel="从已保存批次继续"
        >
          <HiddenProject projectId={projectId} />
          <input name="campaign_id" type="hidden" value={campaignId} />
          <input name="job_id" type="hidden" value={selectedJob.job_id} />
        </ActionForm>
        : null}
    </div> : null}
  </section>;
}

function ReviewStep({
  approvedCandidates,
  campaignId,
  campaignName,
  candidates,
  embedded,
  factLabels,
  projectId,
  selectedJob
}: {
  approvedCandidates: KnowledgeQuestionCandidateView[];
  campaignId: string;
  campaignName: string;
  candidates: KnowledgeQuestionCandidateView[];
  embedded: boolean;
  factLabels: ReadonlyMap<string, string>;
  projectId: string;
  selectedJob?: KnowledgeQuestionGenerationView;
}) {
  if (selectedJob?.generation_mode === "coverage_pack") {
    return <section className={questionStyles.stepPanel} aria-labelledby="review-title">
      <StepHeading
        description="搜索、编辑或排除问题；生成时参考的知识条目会逐题显示。确认后一次形成冻结清单。"
        title="检查 100 题测量库"
        titleId="review-title"
      >
        <span className={questionStyles.countPill}>{candidates.length} 条候选</span>
      </StepHeading>
      {selectedJob.status !== "succeeded" ? <div className={questionStyles.guidance}>
        <strong>正在分批生成</strong>
        <span>已保存 {selectedJob.checkpoint_candidate_count} / 100 条，完成 {selectedJob.completed_batch_count} / {selectedJob.batch_count} 批。</span>
        <QuestionJobWatcher status={selectedJob.status} />
      </div> : candidates.length === 100 ? <QuestionCoverageReview
        campaignId={campaignId}
        campaignName={campaignName}
        candidates={candidates}
        factLabels={Object.fromEntries(factLabels)}
        generationJobId={selectedJob.job_id}
        projectId={projectId}
        setsHref={questionWorkspaceHref({
          campaignId,
          embedded,
          projectId,
          questionGenerationJobId: selectedJob.job_id,
          step: "sets"
        })}
      /> : <Empty>任务显示完成，但候选数量不是 100；请保留现场并重新执行失败批次。</Empty>}
    </section>;
  }
  const pending = candidates.filter((item) => item.workflow_status === "pending_review");
  const reviewed = candidates.filter((item) => item.workflow_status !== "pending_review");
  return <section className={questionStyles.stepPanel} aria-labelledby="review-title">
    <StepHeading
      description="逐条确认问题是否自然、明确且适合用于 GEO 测量。来源知识始终显示在问题下方。"
      title="审核候选问题"
      titleId="review-title"
    >
      <span className={questionStyles.countPill}>{pending.length} 条待审核</span>
    </StepHeading>

    {!selectedJob ? <Empty>先生成一批候选问题。</Empty>
      : selectedJob.status !== "succeeded" ? <div className={questionStyles.guidance}>
        <strong>任务尚未完成</strong>
        <span>当前状态：<Status value={selectedJob.status} />。完成后候选会自动出现在这里。</span>
        <QuestionJobWatcher status={selectedJob.status} />
      </div>
        : null}

    {candidates.length ? <div className={questionStyles.candidateList}>
        {pending.map((candidate, index) => <CandidateRow
          campaignId={campaignId}
          candidate={candidate}
          factLabels={factLabels}
          index={index + 1}
          key={candidate.id}
          projectId={projectId}
        />)}
        {reviewed.length ? <details className={questionStyles.reviewedGroup}>
          <summary>查看已处理问题（{reviewed.length}）</summary>
          <div>{reviewed.map((candidate, index) => <CandidateRow
            campaignId={campaignId}
            candidate={candidate}
            factLabels={factLabels}
            index={pending.length + index + 1}
            key={candidate.id}
            projectId={projectId}
          />)}</div>
        </details> : null}
      </div>
      : <Empty>这次任务还没有候选问题。可返回生成步骤重试。</Empty>}

    <div className={questionStyles.nextActionBar}>
      <div>
        <strong>{approvedCandidates.length
          ? `已批准 ${approvedCandidates.length} 条问题`
          : "至少批准一条候选后可继续"}</strong>
        <span>下一步会把选中的问题固化为可复用的问题清单。</span>
      </div>
      {approvedCandidates.length ? <a href={questionWorkspaceHref({
        campaignId,
        embedded,
        projectId,
        questionGenerationJobId: selectedJob?.job_id,
        step: "sets"
      })}>进入问题清单</a> : <span className={questionStyles.disabledAction} aria-disabled="true">
        进入问题清单
      </span>}
    </div>
  </section>;
}

function CandidateRow({ campaignId, candidate, factLabels, index, projectId }: {
  campaignId: string;
  candidate: KnowledgeQuestionCandidateView;
  factLabels: ReadonlyMap<string, string>;
  index: number;
  projectId: string;
}) {
  const canApprove = candidate.dedup_status !== "exact_duplicate";
  return <article className={questionStyles.candidateRow} data-testid="question-candidate">
    <div className={questionStyles.candidateNumber}>{String(index).padStart(2, "0")}</div>
    <div className={questionStyles.candidateBody}>
      <div className={questionStyles.candidateHeading}>
        <h3>{candidate.query_text}</h3><Status value={candidate.workflow_status} />
      </div>
      <div className={questionStyles.candidateMeta}>
        <span>{candidate.dimension_key}</span>
        <span>第 {candidate.turn_index} 轮</span>
        <span>{dedupLabel(candidate.dedup_status)}</span>
        {candidate.nearest_similarity === null ? null
          : <span>最近相似度 {(candidate.nearest_similarity * 100).toFixed(1)}%</span>}
      </div>
      <div className={questionStyles.sources} aria-label="引用的知识来源">
        <strong>知识来源</strong>
        {candidate.fact_source_ids.length
          ? candidate.fact_source_ids.map((id) => <span key={id} title={id}>
            {factLabels.get(id) || `事实 ${id.slice(0, 8)}`}
          </span>)
          : <span>本条未引用知识事实</span>}
        {candidate.entity_source_ids.map((id) => <span key={id} title={id}>
          实体 {id.slice(0, 8)}
        </span>)}
      </div>
      <TechnicalInfo label="技术信息">
        <span>语义指纹 {candidate.semantic_fingerprint}</span>
        <code>{candidate.query_text_hash}</code>
        <code>{candidate.id}</code>
      </TechnicalInfo>
    </div>
    {candidate.workflow_status === "pending_review" ? <div className={questionStyles.reviewActions}>
      {canApprove ? <ReviewDecision
        campaignId={campaignId}
        candidateId={candidate.id}
        decision="approved"
        label="批准"
        projectId={projectId}
      /> : null}
      <ReviewDecision
        campaignId={campaignId}
        candidateId={candidate.id}
        decision="rejected"
        label="拒绝"
        projectId={projectId}
      />
    </div> : null}
  </article>;
}

function ReviewDecision({ campaignId, candidateId, decision, label, projectId }: {
  campaignId: string;
  candidateId: string;
  decision: "approved" | "rejected";
  label: string;
  projectId: string;
}) {
  return <ActionForm
    action={reviewQuestionCandidate}
    danger={decision === "rejected"}
    pendingLabel="正在提交..."
    refreshOnSuccess
    submitLabel={label}
  >
    <HiddenProject projectId={projectId} />
    <input name="campaign_id" type="hidden" value={campaignId} />
    <input name="candidate_id" type="hidden" value={candidateId} />
    <input name="decision" type="hidden" value={decision} />
  </ActionForm>;
}

function QuestionSetsStep({
  approvedCandidates,
  campaignId,
  campaignName,
  data,
  projectId,
  selectedJob
}: {
  approvedCandidates: KnowledgeQuestionCandidateView[];
  campaignId: string;
  campaignName: string;
  data: QuestionSetWorkspaceData;
  projectId: string;
  selectedJob?: KnowledgeQuestionGenerationView;
}) {
  return <section className={questionStyles.stepPanel} aria-labelledby="sets-title">
    <StepHeading
      description="把批准的问题保存为不可变版本，再批准、冻结并绑定到监测方案。"
      title="问题清单"
      titleId="sets-title"
    >
      <span className={questionStyles.countPill}>{data.questionSets.data.length} 个版本</span>
    </StepHeading>

    <section className={questionStyles.createSetSection} aria-labelledby="create-set-title">
      <div><h3 id="create-set-title">创建问题清单</h3>
        <p>默认包含本次已批准的问题；取消勾选即可排除。</p></div>
      {approvedCandidates.length && selectedJob ? <ActionForm
        action={createQuestionSet}
        pendingLabel="正在创建..."
        refreshOnSuccess
        submitLabel="创建问题清单草稿"
      >
        <HiddenProject projectId={projectId} />
        <input name="campaign_id" type="hidden" value={campaignId} />
        <input name="generation_job_id" type="hidden" value={selectedJob.job_id} />
        <label>清单名称<input name="name" required
          defaultValue={`${campaignName} 问题清单`} /></label>
        <fieldset className={questionStyles.candidatePicker}>
          <legend>纳入的问题</legend>
          {approvedCandidates.map((item) => <label key={item.id}>
            <input defaultChecked name="candidate_ids" type="checkbox" value={item.id} />
            <span>{item.query_text}</span>
          </label>)}
        </fieldset>
      </ActionForm> : <Empty>先在“审核候选”中批准至少一条问题。</Empty>}
    </section>

    <section className={questionStyles.setVersions} aria-labelledby="set-versions-title">
      <div className={questionStyles.subheading}>
        <h3 id="set-versions-title">已有版本</h3><span>{data.questionSets.data.length} 个</span>
      </div>
      <ResourceBlock resource={data.questionSets}>{(sets) => sets.length
        ? <div className={questionStyles.setList}>{sets.map((set) => <QuestionSetRow
          data={data}
          key={set.id}
          projectId={projectId}
          set={set}
        />)}</div>
        : <Empty>尚未创建问题清单。</Empty>}
      </ResourceBlock>
    </section>
  </section>;
}

function QuestionSetRow({ data, projectId, set }: {
  data: QuestionSetWorkspaceData;
  projectId: string;
  set: KnowledgeQuestionSetView;
}) {
  const campaignId = data.selection.campaignId || "";
  const draftProtocols = data.protocols.data.filter(
    (protocol) => protocol.status === "draft" && !protocol.question_set_id
  );
  const boundProtocols = data.protocols.data.filter((protocol) => protocol.question_set_id === set.id);
  return <article className={questionStyles.setRow} data-testid="question-set">
    <header>
      <div><strong>{set.name}</strong><span>版本 {set.version_number}</span></div>
      <Status value={set.status} />
    </header>
    <dl className={questionStyles.setMetrics}>
      <div><dt>问题</dt><dd>{set.items.length}</dd></div>
      <div><dt>维度覆盖</dt><dd>{set.covered_dimension_count}/{set.dimension_count}</dd></div>
      <div><dt>覆盖率</dt><dd>{percent(set.coverage_ratio)}</dd></div>
      <div><dt>可能重复</dt><dd>{set.possible_duplicate_count}</dd></div>
    </dl>
    <details className={questionStyles.setQuestions}>
      <summary>查看问题与来源</summary>
      <div className={questionStyles.setQuestionList}>{set.items.map((item) => <div key={item.id}>
        <span>{item.ordinal}</span>
        <div><strong>{item.query_text_snapshot}</strong>
          <small>{item.dimension_key} · 来源 <ShortId value={item.source_lineage_hash} /></small></div>
      </div>)}</div>
    </details>
    <div className={questionStyles.setActions}>
      {set.status === "draft" ? <ActionForm
        action={transitionQuestionSet}
        refreshOnSuccess
        submitLabel="批准问题清单"
      >
        <HiddenProject projectId={projectId} />
        <input name="campaign_id" type="hidden" value={campaignId} />
        <input name="question_set_id" type="hidden" value={set.id} />
        <input name="command" type="hidden" value="approve" />
      </ActionForm> : null}
      {set.status === "approved" ? <ActionForm
        action={transitionQuestionSet}
        refreshOnSuccess
        submitLabel="冻结问题清单"
      >
        <HiddenProject projectId={projectId} />
        <input name="campaign_id" type="hidden" value={campaignId} />
        <input name="question_set_id" type="hidden" value={set.id} />
        <input name="command" type="hidden" value="freeze" />
      </ActionForm> : null}
    </div>
    {set.status === "frozen" && set.content_hash ? <div className={questionStyles.frozenActions}>
      {draftProtocols.length ? <ActionForm
        action={bindQuestionSetToProtocol}
        refreshOnSuccess
        submitLabel="绑定监测方案"
      >
        <HiddenProject projectId={projectId} />
        <input name="campaign_id" type="hidden" value={campaignId} />
        <input name="question_set_id" type="hidden" value={set.id} />
        <input name="confirmed_content_hash" type="hidden" value={set.content_hash} />
        <label>草稿监测方案<select name="protocol_id" required defaultValue="">
          <option value="" disabled>选择监测方案</option>
          {draftProtocols.map((protocol) => <option key={protocol.id} value={protocol.id}>
            {protocol.name}
          </option>)}
        </select></label>
      </ActionForm> : null}
      {boundProtocols.map((protocol) => <div className={questionStyles.boundProtocol} key={protocol.id}>
        <span>已绑定：<strong>{protocol.name}</strong></span><Status value={protocol.status} />
      </div>)}
      <a className={questionStyles.simulationLink} href={internalSimulationHref(
        projectId,
        campaignId,
        set.id
      )}>前往 GEO 运行内部仿真</a>
      <TechnicalInfo label="冻结身份">
        <code>{set.id}</code><code>{set.content_hash}</code>
      </TechnicalInfo>
    </div> : null}
  </article>;
}

function StepHeading({ children, description, title, titleId }: {
  children?: ReactNode;
  description: string;
  title: string;
  titleId: string;
}) {
  return <header className={questionStyles.stepHeading}>
    <div><h2 id={titleId}>{title}</h2><p>{description}</p></div>{children}
  </header>;
}

function internalSimulationHref(projectId: string, campaignId: string, questionSetId: string): string {
  const params = new URLSearchParams({
    tab: "geo",
    geo_section: "placement",
    placement_stage: "simulation",
    campaign_id: campaignId,
    question_set_id: questionSetId
  });
  return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
}

function dedupLabel(value: KnowledgeQuestionCandidateView["dedup_status"]): string {
  if (value === "possible_duplicate") return "可能重复";
  if (value === "exact_duplicate") return "完全重复，不能批准";
  return "语义独立";
}

function percent(value: number): string {
  return `${(value * 100).toFixed(value === 0 || value === 1 ? 0 : 1)}%`;
}

function actualModelLabel(job: KnowledgeQuestionGenerationView): string {
  if (!job.execution_backend || !job.actual_model) return "实际模型待执行";
  const backend = job.execution_backend === "dify"
    ? "Dify"
    : job.execution_backend === "hybrid"
      ? "固定基准 + Dify"
      : job.execution_backend === "deterministic"
        ? "固定覆盖配置"
        : "原生 Gateway";
  return `${backend} · ${job.actual_model}`;
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    month: "2-digit",
    day: "2-digit"
  }).format(parsed);
}
