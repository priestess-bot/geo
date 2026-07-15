import { randomUUID } from "node:crypto";

import { isAuthIdentity, type AuthIdentity } from "@geo/types/auth";

import { runtimeRequest } from "../../runtime";
import type {
  MemberCommandKeys,
  MemberLoadProblem,
  ProjectMemberListResponse,
  ProjectMemberLoadResult,
  ProjectMemberSummary
} from "./memberTypes";
import { isProjectMemberListResponse } from "./memberTypes";

const emptyPage: ProjectMemberListResponse = {
  items: [],
  total: 0,
  limit: 100,
  offset: 0
};

export async function loadProjectMembers(projectId: string): Promise<ProjectMemberLoadResult> {
  const [members, identity] = await Promise.all([
    runtimeRequest<ProjectMemberListResponse>(
      `/v1/projects/${encodeURIComponent(projectId)}/members`,
      { query: { limit: 100, offset: 0 } }
    ),
    runtimeRequest<AuthIdentity>("/v1/auth/me")
  ]);
  const membersValid = members.ok && isProjectMemberListResponse(members.data);
  const identityValid = identity.ok && isAuthIdentity(identity.data);
  const page = membersValid ? members.data : emptyPage;
  const actorId = identityValid ? identity.data.actor_id : "";
  const current = page.items.find(
    (member) => member.status === "active" && member.subject === actorId
  );
  const problem = !members.ok
    ? loadProblem(members.status, members.error, members.problem.correlation_id)
    : !membersValid
      ? loadProblem(502, "成员接口返回了无法识别的响应。", members.response.correlationId)
    : !identity.ok
      ? loadProblem(identity.status, identity.error, identity.problem.correlation_id)
      : !identityValid
        ? loadProblem(502, "身份接口返回了无法识别的响应。", identity.response.correlationId)
      : current
        ? undefined
        : loadProblem(403, "当前 OIDC 主体没有此项目的有效成员关系。", undefined);
  return {
    page,
    actorId,
    currentRole: current?.role || null,
    ...(problem ? { problem } : {}),
    commandKeys: commandKeys(page.items)
  };
}

export function emptyProjectMembers(): ProjectMemberLoadResult {
  return {
    page: emptyPage,
    actorId: "",
    currentRole: null,
    commandKeys: commandKeys([])
  };
}

function commandKeys(members: ProjectMemberSummary[]): MemberCommandKeys {
  return {
    add: `admin-member-add-${randomUUID()}`,
    byMembership: Object.fromEntries(
      members.map((member) => [
        member.membership_id,
        {
          changeRole: `admin-member-role-${randomUUID()}`,
          reactivate: `admin-member-reactivate-${randomUUID()}`,
          revoke: `admin-member-revoke-${randomUUID()}`
        }
      ])
    )
  };
}

function loadProblem(
  status: number | undefined,
  detail: string,
  correlationId: string | undefined
): MemberLoadProblem {
  return {
    ...(status === undefined ? {} : { status }),
    detail,
    ...(correlationId ? { correlationId } : {})
  };
}
