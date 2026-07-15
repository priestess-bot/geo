import type {
  CreatedProjectInvitationResponse,
  ProjectInvitationListResponse,
  ProjectInvitationSummary
} from "@geo/types/auth";

import type { ProjectLoadProblem } from "../projectTypes";

export type InvitationLoadResult = Readonly<{
  page: ProjectInvitationListResponse;
  problem?: ProjectLoadProblem;
}>;

export type InvitationActionState = Readonly<{
  kind: "idle" | "success" | "error";
  message?: string;
  status?: number;
  correlationId?: string;
  rawInviteToken?: string;
  invitationId?: string;
}>;

export const initialInvitationActionState: InvitationActionState = { kind: "idle" };

export function isInvitationListResponse(value: unknown): value is ProjectInvitationListResponse {
  if (!record(value)) return false;
  return Array.isArray(value.items)
    && value.items.every(isInvitationSummary)
    && nonNegativeInteger(value.total)
    && positiveInteger(value.limit)
    && nonNegativeInteger(value.offset);
}

export function isCreatedInvitationResponse(
  value: unknown
): value is CreatedProjectInvitationResponse {
  return record(value)
    && isInvitationSummary(value.invitation)
    && nonEmpty(value.invite_token)
    && typeof value.replayed === "boolean";
}

function isInvitationSummary(value: unknown): value is ProjectInvitationSummary {
  if (!record(value)) return false;
  return [
    value.id,
    value.project_id,
    value.email,
    value.role,
    value.target_surface,
    value.token_hint,
    value.status,
    value.expires_at,
    value.created_at
  ].every(nonEmpty)
    && value.target_surface === "customer"
    && (value.role === "analyst" || value.role === "viewer" || value.role === "customer")
    && (value.status === "pending" || value.status === "redeemed" || value.status === "revoked" || value.status === "expired");
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}
