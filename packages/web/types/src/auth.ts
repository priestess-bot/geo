export const INVITATION_SURFACES = ["admin", "customer"] as const;
export type InvitationSurface = (typeof INVITATION_SURFACES)[number];

export type CanonicalInvitationRole = "analyst" | "viewer" | "customer";

export interface ProjectInvitationSummary {
  id: string;
  project_id: string;
  email: string;
  role: CanonicalInvitationRole;
  target_surface: "customer";
  token_hint: string;
  status: "pending" | "redeemed" | "revoked" | "expired";
  expires_at: string;
  created_at: string;
}

export interface ProjectInvitationListResponse {
  items: ProjectInvitationSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface CreatedProjectInvitationResponse {
  invitation: ProjectInvitationSummary;
  invite_token: string;
  replayed: boolean;
}

export interface InvitationRequest {
  invitation_id: string;
  invite_token: string;
  requested_surface: InvitationSurface;
}

export type InvitationPreflightResponse =
  | {
      compatibility: "compatible";
      requested_surface: "customer";
      recommended_surface: "customer";
      invitation_role: CanonicalInvitationRole;
    }
  | {
      compatibility: "surface_mismatch";
      requested_surface: "admin";
      recommended_surface: "customer";
      invitation_role: CanonicalInvitationRole;
    }
  | {
      compatibility: "invalid";
      requested_surface: InvitationSurface;
      recommended_surface: null;
      invitation_role: null;
    };

export interface AuthIdentity {
  actor_id: string;
  tenant_id: string;
  project_ids: string[];
  roles: string[];
}

export interface InvitationRedeemResponse {
  recovery_status: "created" | "replayed";
  session: AuthIdentity;
  expires_at: string;
}

export interface RedeemPrepareResponse {
  prepared: true;
  compatibility: "compatible";
  requested_surface: "customer";
  recommended_surface: "customer";
  invitation_role: CanonicalInvitationRole;
}

export type AuthBffErrorCode =
  | "invitation_invalid"
  | "invitation_surface_mismatch"
  | "invitation_conflict"
  | "invitation_consumed"
  | "idempotency_conflict"
  | "csrf_rejected"
  | "auth_invalid_request"
  | "auth_request_failed"
  | "auth_upstream_unavailable";

export interface AuthErrorEnvelope {
  code: AuthBffErrorCode;
  detail: string;
  correlation_id: string;
  recommended_surface?: InvitationSurface;
  invitation_consumed?: false;
}

export function isInvitationSurface(value: unknown): value is InvitationSurface {
  return value === "admin" || value === "customer";
}

export function isInvitationPreflightResponse(
  value: unknown
): value is InvitationPreflightResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Record<string, unknown>;
  const role = isCanonicalInvitationRole(candidate.invitation_role);
  if (candidate.compatibility === "compatible") {
    return candidate.requested_surface === "customer"
      && candidate.recommended_surface === "customer"
      && role;
  }
  if (candidate.compatibility === "surface_mismatch") {
    return candidate.requested_surface === "admin"
      && candidate.recommended_surface === "customer"
      && role;
  }
  return candidate.compatibility === "invalid"
    && isInvitationSurface(candidate.requested_surface)
    && candidate.recommended_surface === null
    && candidate.invitation_role === null;
}

export function isAuthIdentity(value: unknown): value is AuthIdentity {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Partial<AuthIdentity>;
  return (
    nonEmpty(candidate.actor_id)
    && nonEmpty(candidate.tenant_id)
    && Array.isArray(candidate.project_ids)
    && candidate.project_ids.every(nonEmpty)
    && new Set(candidate.project_ids).size === candidate.project_ids.length
    && Array.isArray(candidate.roles)
    && candidate.roles.every(nonEmpty)
  );
}

export function parseAuthError(
  value: unknown,
  fallbackCode: AuthBffErrorCode,
  fallbackDetail: string,
  correlationId = ""
): AuthErrorEnvelope {
  const candidate = value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
  const explicitCode = typeof candidate.code === "string" ? candidate.code : "";
  const typeCode = typeof candidate.type === "string"
    ? candidate.type.split(":").at(-1)?.replaceAll("-", "_") || ""
    : "";
  const allowed = new Set<AuthBffErrorCode>([
    "invitation_invalid",
    "invitation_surface_mismatch",
    "invitation_conflict",
    "invitation_consumed",
    "idempotency_conflict",
    "csrf_rejected",
    "auth_invalid_request",
    "auth_request_failed",
    "auth_upstream_unavailable"
  ]);
  const rawCode = explicitCode || typeCode;
  const code = allowed.has(rawCode as AuthBffErrorCode)
    ? rawCode as AuthBffErrorCode
    : fallbackCode;
  const recommended = isInvitationSurface(candidate.recommended_surface)
    ? candidate.recommended_surface
    : undefined;
  return {
    code,
    detail: nonEmpty(candidate.detail) ? candidate.detail : fallbackDetail,
    correlation_id: nonEmpty(candidate.correlation_id)
      ? candidate.correlation_id
      : nonEmpty(candidate.request_id)
        ? candidate.request_id
        : correlationId,
    ...(recommended ? { recommended_surface: recommended } : {})
  };
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isCanonicalInvitationRole(value: unknown): value is CanonicalInvitationRole {
  return value === "analyst" || value === "viewer" || value === "customer";
}
