import { redirect } from "next/navigation";

import { loadCatalog } from "./catalogData";
import { normalizeWorkbenchTab } from "./features/project-workbench/tabs";
import { WorkbenchShell } from "./features/project-workbench/WorkbenchShell";
import { loadProjectInvitations } from "./invitationData";
import { loadProjectMembers } from "./memberData";
import { loadGeoWorkspace } from "./geo/features/geo/data";

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
  const [catalog, invitations, members] = await Promise.all([
    loadCatalog(projectId),
    loadProjectInvitations(projectId),
    loadProjectMembers(projectId)
  ]);
  if (catalog.project.problem?.status === 401) redirect("/login");
  const geoData = activeTab === "geo" ? await loadGeoWorkspace(projectId, query) : null;
  return <WorkbenchShell
    activeTab={activeTab}
    catalog={catalog}
    geoData={geoData}
    invitations={invitations}
    members={members}
    projectId={projectId}
  />;
}

function queryValue(params: SearchParams, key: string): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}
