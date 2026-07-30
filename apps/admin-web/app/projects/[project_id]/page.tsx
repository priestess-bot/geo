import { redirect } from "next/navigation";

import { loadCatalog } from "./catalogData";
import { normalizeWorkbenchTab } from "./features/project-workbench/tabs";
import { WorkbenchShell } from "./features/project-workbench/WorkbenchShell";
import { loadProjectInvitations } from "./invitationData";
import { loadProjectMembers } from "./memberData";
import { loadGeoWorkspace } from "./geo/features/geo/data";
import { loadKnowledgeWorkspace } from "./knowledgeData";
import { loadPromptWorkspace } from "./features/prompt-programs/promptProgramData";
import { loadRecommendationWorkspace } from "./features/recommendations/recommendationData";
import { loadSecretWorkspace } from "./features/secret-store/secretStoreData";
import { loadSyntheticLabWorkspace } from "./features/synthetic-lab/syntheticLabData";
import { loadWorkflowCWorkspace } from "./features/workflow-c/workflowCData";
import { loadExternalOperations } from "./features/external-operations/externalOperationsData";

// Project workspaces contain per-request identity and membership state.
export const dynamic = "force-dynamic";
export const revalidate = 0;

type SearchParams = { [key: string]: string | string[] | undefined };

export default async function ProjectDetailPage({
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
  const activeTab = normalizeWorkbenchTab(queryValue(query, "tab"));
  const [catalog, invitations, members, geoData, knowledgeData, promptData, secretData, syntheticData, recommendationData, workflowCData, externalOperationsData] = await Promise.all([
    loadCatalog(projectId),
    loadProjectInvitations(projectId),
    loadProjectMembers(projectId),
    activeTab === "geo" ? loadGeoWorkspace(projectId, query) : Promise.resolve(null),
    activeTab === "knowledge" ? loadKnowledgeWorkspace(projectId, query) : Promise.resolve(null),
    activeTab === "prompts" ? loadPromptWorkspace(projectId, query) : Promise.resolve(null),
    activeTab === "secrets" ? loadSecretWorkspace(projectId, query) : Promise.resolve(null),
    activeTab === "synthetic-lab" ? loadSyntheticLabWorkspace(projectId, query) : Promise.resolve(null),
    activeTab === "recommendations" ? loadRecommendationWorkspace(projectId, query) : Promise.resolve(null),
    activeTab === "measurement" ? loadWorkflowCWorkspace(projectId, query) : Promise.resolve(null),
    activeTab === "external-data" ? loadExternalOperations(projectId) : Promise.resolve(null)
  ]);
  if (catalog.project.problem?.status === 401) redirect("/login");
  if (workflowCData?.alerts.problem?.status === 401) redirect("/login");
  if (geoData?.canonicalHref) redirect(geoData.canonicalHref);
  return <WorkbenchShell
    activeTab={activeTab}
    catalog={catalog}
    geoData={geoData}
    invitations={invitations}
    knowledgeData={knowledgeData}
    members={members}
    promptData={promptData}
    recommendationData={recommendationData}
    secretData={secretData}
    syntheticData={syntheticData}
    workflowCData={workflowCData}
    externalOperationsData={externalOperationsData}
    projectId={projectId}
  />;
}

function queryValue(params: SearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}
