import { redirect } from "next/navigation";

import { WorkflowCWorkspace } from "../features/workflow-c/WorkflowCWorkspace";
import { loadWorkflowCWorkspace } from "../features/workflow-c/workflowCData";

type SearchParams = { [key: string]: string | string[] | undefined };

export default async function WorkflowCPage({
  params,
  searchParams
}: {
  params: Promise<{ project_id: string }>;
  searchParams?: Promise<SearchParams>;
}) {
  const [{ project_id: projectId }, query] = await Promise.all([
    params,
    searchParams || Promise.resolve({})
  ]);
  const data = await loadWorkflowCWorkspace(projectId, query);
  if (data.alerts.problem?.status === 401) redirect("/login");
  return <WorkflowCWorkspace data={data} projectId={projectId} />;
}
