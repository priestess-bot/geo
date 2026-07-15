import type { ProjectInvitationListResponse } from "@geo/types/auth";

import { runtimeRequest } from "../../runtime";

type InvitationPage = {
  total_count: number;
  records: Array<Record<string, unknown>>;
  limit: number;
  offset: number;
};

export async function loadProjectInvitations(projectId: string): Promise<InvitationPage> {
  const response = await runtimeRequest<ProjectInvitationListResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/invitations`,
    { query: { limit: 100, offset: 0 } }
  );
  if (!response.ok) {
    return { total_count: 0, records: [], limit: 100, offset: 0 };
  }
  return {
    total_count: response.data.total,
    records: response.data.items.map((invitation) => ({ invitation })),
    limit: response.data.limit,
    offset: response.data.offset
  };
}
