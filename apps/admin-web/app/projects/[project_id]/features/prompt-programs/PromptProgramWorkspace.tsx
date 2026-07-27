import { DifyWorkflowBoard } from "./DifyWorkflowBoard";
import type { PromptWorkspaceData } from "./promptProgramTypes";

export function PromptProgramWorkspace({
  data,
  projectId
}: {
  actorIdentityId: string;
  currentRole: import("../../memberTypes").ManagedMemberRole | null;
  data: PromptWorkspaceData;
  projectId: string;
}) {
  return (
    <DifyWorkflowBoard
      page={data.workflowRuntimes}
      problem={data.workflowRuntimesProblem}
      projectId={projectId}
    />
  );
}
