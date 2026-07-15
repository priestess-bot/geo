import type { ProjectInvitationListResponse } from "@geo/types/auth";

import { runtimeRequest } from "../../runtime";
import {
  isInvitationListResponse,
  type InvitationLoadResult
} from "./invitationTypes";

const emptyPage: ProjectInvitationListResponse = {
  items: [],
  total: 0,
  limit: 100,
  offset: 0
};

export async function loadProjectInvitations(projectId: string): Promise<InvitationLoadResult> {
  const response = await runtimeRequest<ProjectInvitationListResponse>(
    `/v1/projects/${encodeURIComponent(projectId)}/invitations`,
    { query: { limit: 100, offset: 0 } }
  );
  if (!response.ok) {
    return {
      page: emptyPage,
      problem: {
        ...(response.status === undefined ? {} : { status: response.status }),
        detail: response.error || "客户邀请加载失败。",
        ...(response.problem.correlation_id
          ? { correlationId: response.problem.correlation_id }
          : {})
      }
    };
  }
  if (!isInvitationListResponse(response.data)) {
    return {
      page: emptyPage,
      problem: {
        status: 502,
        detail: "客户邀请接口返回了无法识别的响应。",
        ...(response.response.correlationId
          ? { correlationId: response.response.correlationId }
          : {})
      }
    };
  }
  return { page: response.data };
}
