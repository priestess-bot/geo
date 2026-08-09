import type {
  KnowledgeQuestionCandidateView,
  KnowledgeQuestionGenerationView,
  KnowledgeQuestionSetView
} from "@geo/types/geo";
import type { ReactNode } from "react";

import { QuestionJobWatcher } from "../../../features/workflow-c/QuestionJobWatcher";
import { QuestionCoverageReview } from "../../../features/workflow-c/QuestionCoverageReview";
import type { QuestionWorkspaceData } from "../../../features/workflow-c/questionWorkspaceData";
import { questionWorkspaceHref } from "../../../features/workflow-c/questionWorkspaceLinks";
import layoutStyles from "../../../features/workflow-c/QuestionWorkspace.module.css";
import layoutResponsiveStyles from "../../../features/workflow-c/QuestionWorkspaceResponsive.module.css";
import reviewStyles from "../../../features/workflow-c/QuestionReviewWorkspace.module.css";
import reviewResponsiveStyles from "../../../features/workflow-c/QuestionReviewResponsive.module.css";
import { mergeCssModules } from "../../../features/workflow-c/cssModules";
import { ActionForm } from "./ActionForm";
import {
  bindQuestionSetToProtocol,
  createQuestionSet,
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

type QuestionSetWorkspaceData = QuestionWorkspaceData;

const questionStyles = mergeCssModules(
  layoutStyles,
  layoutResponsiveStyles,
  reviewStyles,
  reviewResponsiveStyles
);

export function ReviewStep({
  approvedCandidates,
  campaignId,
  campaignName,
  candidates,
  embedded,
  factLabels,
  latestFrozenSet,
  projectId,
  selectedJob
}: {
  approvedCandidates: KnowledgeQuestionCandidateView[];
  campaignId: string;
  campaignName: string;
  candidates: KnowledgeQuestionCandidateView[];
  embedded: boolean;
  factLabels: ReadonlyMap<string, string>;
  latestFrozenSet?: KnowledgeQuestionSetView;
  projectId: string;
  selectedJob?: KnowledgeQuestionGenerationView;
}) {
  if (selectedJob?.generation_mode === "coverage_pack") {
    return <section className={questionStyles.stepPanel} aria-labelledby="review-title">
      <StepHeading
        description="搜索、编辑并修正问题；生成时参考的知识条目会逐题显示。确认后一次形成冻结清单。"
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
        predecessor={latestFrozenSet ? {
          id: latestFrozenSet.id,
          seriesId: latestFrozenSet.series_id
        } : undefined}
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

export function QuestionSetsStep({
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
