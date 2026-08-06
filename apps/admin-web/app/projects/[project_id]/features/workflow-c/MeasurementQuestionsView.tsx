import { QuestionSetWorkspace } from "../../geo/features/geo/QuestionSetWorkspace";
import { FailureNotice } from "../../geo/features/geo/common";
import { QuestionCampaignSwitcher } from "./QuestionCampaignSwitcher";
import type { QuestionStep, QuestionWorkspaceData } from "./questionWorkspaceData";
import { questionWorkspaceHref } from "./questionWorkspaceLinks";
import type { WorkflowCWorkspaceData } from "./workflowCTypes";
import styles from "./WorkflowC.module.css";
import questionStyles from "./MeasurementQuestionsView.module.css";

const STEP_COPY: ReadonlyArray<Readonly<{
  key: QuestionStep;
  label: string;
}>> = [
  { key: "generate", label: "生成问题" },
  { key: "review", label: "审核候选" },
  { key: "sets", label: "问题清单" }
];

export function MeasurementQuestionsView({
  data,
  projectId
}: {
  data: WorkflowCWorkspaceData;
  projectId: string;
}) {
  const workspace = data.questionWorkspace;
  if (!workspace) {
    return <div className={styles.emptyState}>
      <strong>测试问题数据尚未加载</strong>
      <span>重新打开“测试问题”视图后重试。</span>
    </div>;
  }
  const selectedCampaign = workspace.campaigns.data.find(
    (item) => item.id === workspace.selection.campaignId
  );
  const candidates = workspace.questionCandidates.data;
  const pendingCount = candidates.filter(
    (item) => item.workflow_status === "pending_review"
  ).length;
  const approvedCount = candidates.filter(
    (item) => item.workflow_status === "approved"
  ).length;
  const activeStep = resolveStep(workspace);
  const contextCopy = [
    `${pendingCount} 条待审核`,
    workspace.questionSets.data.length
      ? `${workspace.questionSets.data.length} 个问题清单`
      : "尚未形成问题清单"
  ];

  return <div className={questionStyles.page}>
    <header className={questionStyles.pageToolbar}>
      <div className={questionStyles.pageTitle}>
        <h1>测试问题</h1>
        <p><strong>仅限内部测试</strong><span aria-hidden="true"> · </span>
          {contextCopy.join(" · ")}</p>
      </div>
      {workspace.campaigns.failure
        ? <FailureNotice failure={workspace.campaigns.failure} />
        : workspace.campaigns.data.length
          ? <div className={questionStyles.campaignControl}>
            <QuestionCampaignSwitcher
              campaigns={workspace.campaigns.data}
              embedded={data.selection.embedded}
              projectId={projectId}
              selectedCampaignId={workspace.selection.campaignId}
            />
          </div>
          : null}
      <a className={questionStyles.primaryAction} href={questionWorkspaceHref({
        campaignId: workspace.selection.campaignId,
        embedded: data.selection.embedded,
        projectId,
        step: "generate"
      })}>生成新问题</a>
    </header>

    {!workspace.campaigns.data.length ? <div className={styles.emptyState}>
      <strong>还没有可用活动</strong>
      <span>先在 GEO 投放中建立产品活动，再回来生成测试问题。</span>
    </div> : null}

    {workspace.selection.campaignId ? <>
      <nav className={questionStyles.steps} aria-label="测试问题流程">
        {STEP_COPY.map((step, index) => {
          const state = stepState(step.key, activeStep, workspace, approvedCount);
          return <a
            aria-current={activeStep === step.key ? "step" : undefined}
            className={`${questionStyles.step} ${questionStyles[state]}`}
            href={questionWorkspaceHref({
              campaignId: workspace.selection.campaignId,
              embedded: data.selection.embedded,
              projectId,
              questionGenerationJobId: step.key === "generate"
                ? undefined
                : workspace.selection.questionGenerationJobId,
              step: step.key
            })}
            key={step.key}
          >
            <span className={questionStyles.stepNumber}>{state === "done" ? "✓" : index + 1}</span>
            <span><strong>{step.label}</strong><small>{stepDescription(step.key, workspace)}</small></span>
          </a>;
        })}
      </nav>
      <QuestionSetWorkspace
        activeStep={activeStep}
        campaignName={selectedCampaign?.name || "当前活动"}
        data={workspace}
        embedded={data.selection.embedded}
        projectId={projectId}
      />
    </> : <div className={styles.emptyState}>
      <strong>请选择一个测量活动</strong>
      <span>选择后即可生成、审核并形成问题清单。</span>
    </div>}
  </div>;
}

function resolveStep(workspace: QuestionWorkspaceData): QuestionStep {
  if (workspace.selection.questionStep) return workspace.selection.questionStep;
  const candidates = workspace.questionCandidates.data;
  if (candidates.some((item) => item.workflow_status === "pending_review")) return "review";
  if (workspace.questionSets.data.length
    || candidates.some((item) => item.workflow_status === "approved")) return "sets";
  return "generate";
}

function stepState(
  step: QuestionStep,
  active: QuestionStep,
  workspace: QuestionWorkspaceData,
  approvedCount: number
): "active" | "done" | "idle" {
  if (step === active) return "active";
  if (step === "generate" && workspace.questionGenerations.data.length) return "done";
  if (step === "review" && approvedCount) return "done";
  if (step === "sets" && workspace.questionSets.data.length) return "done";
  return "idle";
}

function stepDescription(step: QuestionStep, workspace: QuestionWorkspaceData): string {
  const candidates = workspace.questionCandidates.data;
  if (step === "generate") {
    const count = workspace.questionGenerations.data.length;
    return count ? `${count} 个任务` : "尚未生成";
  }
  if (step === "review") {
    const pending = candidates.filter((item) => item.workflow_status === "pending_review").length;
    return pending ? `${pending} 条等待处理` : "没有待审核项";
  }
  const count = workspace.questionSets.data.length;
  return count ? `${count} 个版本` : "尚未创建";
}
