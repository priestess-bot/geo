import type { QuestionStep } from "./questionWorkspaceData";

export function questionWorkspaceHref({
  campaignId,
  embedded,
  projectId,
  questionGenerationJobId,
  step
}: {
  campaignId?: string;
  embedded: boolean;
  projectId: string;
  questionGenerationJobId?: string;
  step: QuestionStep;
}): string {
  const params = new URLSearchParams({
    workflow_view: "questions",
    question_step: step
  });
  if (campaignId) params.set("campaign_id", campaignId);
  if (questionGenerationJobId) {
    params.set("question_generation_job_id", questionGenerationJobId);
  }
  if (embedded) {
    params.set("tab", "measurement");
    return `/projects/${encodeURIComponent(projectId)}?${params.toString()}`;
  }
  return `/projects/${encodeURIComponent(projectId)}/workflow-c?${params.toString()}`;
}
