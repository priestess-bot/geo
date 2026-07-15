export const managedMemberRoles = ["owner", "admin", "analyst"] as const;

export type ManagedMemberRole = (typeof managedMemberRoles)[number];
export type ProjectMemberStatus = "active" | "revoked";

export type ProjectMemberSummary = Readonly<{
  membership_id: string;
  project_id: string;
  identity_id: string;
  issuer: string;
  subject: string;
  email: string;
  display_name: string;
  role: ManagedMemberRole;
  status: ProjectMemberStatus;
  created_at: string;
}>;

export type ProjectMemberListResponse = Readonly<{
  items: ProjectMemberSummary[];
  total: number;
  limit: number;
  offset: number;
}>;

export type AddProjectMemberRequest = Readonly<{
  issuer: string;
  subject: string;
  email: string;
  display_name: string;
  role: ManagedMemberRole;
}>;

export type ChangeProjectMemberRoleRequest = Readonly<{
  role: ManagedMemberRole;
}>;

export type ProjectMemberMutationResponse = Readonly<{
  member: ProjectMemberSummary;
  replayed: boolean;
}>;

export type MemberLoadProblem = Readonly<{
  status?: number;
  detail: string;
  correlationId?: string;
}>;

export type MemberCommandKeys = Readonly<{
  add: string;
  byMembership: Readonly<Record<string, Readonly<{
    changeRole: string;
    reactivate: string;
    revoke: string;
  }>>>;
}>;

export type ProjectMemberLoadResult = Readonly<{
  page: ProjectMemberListResponse;
  actorId: string;
  currentRole: ManagedMemberRole | null;
  problem?: MemberLoadProblem;
  commandKeys: MemberCommandKeys;
}>;

export type MemberActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
}>;

export const initialMemberActionState: MemberActionState = { kind: "idle" };

export function isManagedMemberRole(value: unknown): value is ManagedMemberRole {
  return managedMemberRoles.some((role) => role === value);
}

export function isProjectMemberListResponse(value: unknown): value is ProjectMemberListResponse {
  if (!record(value)) return false;
  return Array.isArray(value.items)
    && value.items.every(isProjectMemberSummary)
    && nonNegativeInteger(value.total)
    && nonNegativeInteger(value.offset)
    && Number.isInteger(value.limit)
    && Number(value.limit) > 0;
}

export function isProjectMemberMutationResponse(
  value: unknown
): value is ProjectMemberMutationResponse {
  return record(value)
    && typeof value.replayed === "boolean"
    && isProjectMemberSummary(value.member);
}

function isProjectMemberSummary(value: unknown): value is ProjectMemberSummary {
  if (!record(value)) return false;
  return [
    value.membership_id,
    value.project_id,
    value.identity_id,
    value.issuer,
    value.subject,
    value.email,
    value.display_name,
    value.created_at
  ].every(nonEmptyString)
    && isManagedMemberRole(value.role)
    && (value.status === "active" || value.status === "revoked");
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}
