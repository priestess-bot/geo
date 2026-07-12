export const INVITATION_SURFACES = ["admin", "customer"] as const;
export type InvitationSurface = (typeof INVITATION_SURFACES)[number];

export const INVITATION_SURFACE_COMPATIBILITIES = [
  "compatible",
  "surface_mismatch",
  "policy_stale",
  "invalid"
] as const;
export type InvitationSurfaceCompatibility = (typeof INVITATION_SURFACE_COMPATIBILITIES)[number];

export const INVITATION_REDEEM_RECOVERY_STATUSES = [
  "created",
  "replayed",
  "confirmed",
  "recovery_expired",
  "replay_limit_exceeded"
] as const;
export type InvitationRedeemRecoveryStatus = (typeof INVITATION_REDEEM_RECOVERY_STATUSES)[number];

export const RUNTIME_SESSION_SCOPE_VERSION = "runtime_session_scope_v2" as const;
export type RuntimeSessionScopeVersion = typeof RUNTIME_SESSION_SCOPE_VERSION;

export const AUTHZ_POLICY_VERSION = "auth_surface_policy_v1" as const;
export type AuthzPolicyVersion = typeof AUTHZ_POLICY_VERSION;

export type CanonicalInvitationRole =
  | "super_admin"
  | "tenant_admin"
  | "project_owner"
  | "owner"
  | "admin"
  | "analyst"
  | "reviewer"
  | "knowledge_architect"
  | "content_operator"
  | "client_viewer"
  | "viewer";

export type RuntimeScopeSource = "direct_member" | "tenant_role";

export type StableAuthErrorCode =
  | "invitation_invalid"
  | "invitation_surface_mismatch"
  | "invitation_policy_stale"
  | "idempotency_key_reused"
  | "invitation_already_consumed"
  | "redeem_recovery_expired"
  | "redeem_replay_limit_exceeded"
  | "redeem_prepare_required"
  | "auth_writes_temporarily_disabled";

export type AuthBffErrorCode =
  | StableAuthErrorCode
  | "auth_invalid_request"
  | "auth_recovery_unavailable"
  | "auth_request_failed"
  | "auth_session_delivery_invalid"
  | "auth_upstream_unavailable";

export interface InvitationRequest {
  invitation_id: string;
  invite_token: string;
  requested_surface: InvitationSurface;
}

interface InvitationPreflightBase {
  requested_surface: InvitationSurface;
  policy_version: AuthzPolicyVersion;
  correlation_id: string;
}

export interface CompatibleInvitationPreflightResponse extends InvitationPreflightBase {
  compatibility: "compatible";
  recommended_surface: InvitationSurface;
  invitation_role: CanonicalInvitationRole;
}

export interface SurfaceMismatchInvitationPreflightResponse extends InvitationPreflightBase {
  compatibility: "surface_mismatch";
  recommended_surface: InvitationSurface;
  invitation_role: CanonicalInvitationRole | null;
}

export interface PolicyStaleInvitationPreflightResponse extends InvitationPreflightBase {
  compatibility: "policy_stale";
  recommended_surface: null;
  invitation_role: CanonicalInvitationRole | null;
}

export interface InvalidInvitationPreflightResponse extends InvitationPreflightBase {
  compatibility: "invalid";
  recommended_surface: null;
  invitation_role: null;
}

export type InvitationPreflightResponse =
  | CompatibleInvitationPreflightResponse
  | SurfaceMismatchInvitationPreflightResponse
  | PolicyStaleInvitationPreflightResponse
  | InvalidInvitationPreflightResponse;

export interface InvitationRedeemResponse {
  recovery_status: InvitationRedeemRecoveryStatus;
  session: RuntimeSessionScopeV2;
  correlation_id: string;
}

export interface AuthErrorEnvelope {
  code: AuthBffErrorCode;
  detail: string;
  correlation_id: string;
  recommended_surface?: InvitationSurface;
  invitation_consumed?: false;
}

export interface RuntimeProjectSessionScope {
  project_id: string;
  roles: CanonicalInvitationRole[];
  permissions: string[];
  portal_capabilities: Array<"portal.admin.access" | "portal.customer.access">;
  scope_sources: RuntimeScopeSource[];
}

export interface RuntimeSessionScopeV2 {
  scope_version: RuntimeSessionScopeVersion;
  authz_policy_version: AuthzPolicyVersion;
  actor_id: string;
  tenant_id: string;
  tenant_roles: CanonicalInvitationRole[];
  project_scopes: RuntimeProjectSessionScope[];
  project_ids: string[];
}

export interface RuntimeAuthMeResponse {
  auth?: RuntimeSessionScopeV2;
  session?: RuntimeSessionScopeV2;
}

export interface RedeemPrepareResponse {
  prepared: true;
  compatibility: "compatible";
  requested_surface: InvitationSurface;
  recommended_surface: InvitationSurface;
  policy_version: AuthzPolicyVersion;
  correlation_id: string;
}

type UnknownErrorEnvelope = {
  code?: unknown;
  detail?: unknown;
  correlation_id?: unknown;
  recommended_surface?: unknown;
  invitation_consumed?: unknown;
};

const STABLE_AUTH_ERRORS = new Set<string>([
  "invitation_invalid",
  "invitation_surface_mismatch",
  "invitation_policy_stale",
  "idempotency_key_reused",
  "invitation_already_consumed",
  "redeem_recovery_expired",
  "redeem_replay_limit_exceeded",
  "redeem_prepare_required",
  "auth_writes_temporarily_disabled",
  "auth_invalid_request",
  "auth_recovery_unavailable",
  "auth_request_failed",
  "auth_session_delivery_invalid",
  "auth_upstream_unavailable"
]);

export function isInvitationSurface(value: unknown): value is InvitationSurface {
  return value === "admin" || value === "customer";
}

function isCanonicalInvitationRole(value: unknown): value is CanonicalInvitationRole {
  return typeof value === "string" && [
    "super_admin",
    "tenant_admin",
    "project_owner",
    "owner",
    "admin",
    "analyst",
    "reviewer",
    "knowledge_architect",
    "content_operator",
    "client_viewer",
    "viewer"
  ].includes(value);
}

function isPortalCapability(value: unknown): value is RuntimeProjectSessionScope["portal_capabilities"][number] {
  return value === "portal.admin.access" || value === "portal.customer.access";
}

function isRuntimeScopeSource(value: unknown): value is RuntimeScopeSource {
  return value === "direct_member" || value === "tenant_role";
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isRuntimeProjectScope(value: unknown): value is RuntimeProjectSessionScope {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as {
    project_id?: unknown;
    roles?: unknown;
    permissions?: unknown;
    portal_capabilities?: unknown;
    scope_sources?: unknown;
  };
  return (
    isNonEmptyString(candidate.project_id)
    && Array.isArray(candidate.roles)
    && candidate.roles.every(isCanonicalInvitationRole)
    && Array.isArray(candidate.permissions)
    && candidate.permissions.every(isNonEmptyString)
    && Array.isArray(candidate.portal_capabilities)
    && candidate.portal_capabilities.every(isPortalCapability)
    && Array.isArray(candidate.scope_sources)
    && candidate.scope_sources.length > 0
    && candidate.scope_sources.every(isRuntimeScopeSource)
  );
}

export function isInvitationPreflightResponse(value: unknown): value is InvitationPreflightResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as {
    compatibility?: unknown;
    requested_surface?: unknown;
    recommended_surface?: unknown;
    invitation_role?: unknown;
    policy_version?: unknown;
    correlation_id?: unknown;
  };
  return (
    INVITATION_SURFACE_COMPATIBILITIES.includes(candidate.compatibility as InvitationSurfaceCompatibility)
    && isInvitationSurface(candidate.requested_surface)
    && candidate.policy_version === AUTHZ_POLICY_VERSION
    && typeof candidate.correlation_id === "string"
    && (
      (candidate.compatibility === "compatible"
        && isInvitationSurface(candidate.recommended_surface)
        && isCanonicalInvitationRole(candidate.invitation_role))
      || (candidate.compatibility === "surface_mismatch"
        && isInvitationSurface(candidate.recommended_surface)
        && (candidate.invitation_role === null || isCanonicalInvitationRole(candidate.invitation_role)))
      || (candidate.compatibility === "policy_stale"
        && candidate.recommended_surface === null
        && (candidate.invitation_role === null || isCanonicalInvitationRole(candidate.invitation_role)))
      || (candidate.compatibility === "invalid"
        && candidate.recommended_surface === null
        && candidate.invitation_role === null)
    )
  );
}

export function isRuntimeAuthMeResponse(value: unknown): value is RuntimeAuthMeResponse {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const envelope = value as { auth?: unknown; session?: unknown };
  const scope = envelope.auth ?? envelope.session;
  if (!scope || typeof scope !== "object" || Array.isArray(scope)) {
    return false;
  }
  const candidate = scope as {
    scope_version?: unknown;
    authz_policy_version?: unknown;
    actor_id?: unknown;
    tenant_id?: unknown;
    tenant_roles?: unknown;
    project_scopes?: unknown;
    project_ids?: unknown;
  };
  if (!(
    candidate.scope_version === RUNTIME_SESSION_SCOPE_VERSION
    && candidate.authz_policy_version === AUTHZ_POLICY_VERSION
    && isNonEmptyString(candidate.actor_id)
    && isNonEmptyString(candidate.tenant_id)
    && Array.isArray(candidate.tenant_roles)
    && candidate.tenant_roles.every(isCanonicalInvitationRole)
    && Array.isArray(candidate.project_scopes)
    && candidate.project_scopes.every(isRuntimeProjectScope)
    && Array.isArray(candidate.project_ids)
    && candidate.project_ids.every(isNonEmptyString)
  )) {
    return false;
  }
  const scopeIds = candidate.project_scopes.map((projectScope) => projectScope.project_id);
  const projectIds = candidate.project_ids as string[];
  return (
    new Set(scopeIds).size === scopeIds.length
    && new Set(projectIds).size === projectIds.length
    && scopeIds.length === projectIds.length
    && scopeIds.every((projectId) => projectIds.includes(projectId))
  );
}

export function parseAuthError(
  value: unknown,
  fallbackCode: AuthBffErrorCode,
  fallbackDetail: string,
  correlationId = ""
): AuthErrorEnvelope {
  const candidate: UnknownErrorEnvelope = value && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownErrorEnvelope
    : {};
  const rawCode = typeof candidate.code === "string" ? candidate.code : fallbackCode;
  const code = STABLE_AUTH_ERRORS.has(rawCode) ? rawCode as AuthBffErrorCode : fallbackCode;
  const recommendedSurface = isInvitationSurface(candidate.recommended_surface)
    ? candidate.recommended_surface
    : undefined;
  return {
    code,
    detail: typeof candidate.detail === "string" && candidate.detail.trim()
      ? candidate.detail
      : fallbackDetail,
    correlation_id: typeof candidate.correlation_id === "string"
      ? candidate.correlation_id
      : correlationId,
    ...(recommendedSurface ? { recommended_surface: recommendedSurface } : {}),
    ...(candidate.invitation_consumed === false ? { invitation_consumed: false as const } : {})
  };
}
