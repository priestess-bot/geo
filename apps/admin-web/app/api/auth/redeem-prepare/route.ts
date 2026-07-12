import { randomUUID } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";

import {
  AUTHZ_POLICY_VERSION,
  isInvitationPreflightResponse,
  parseAuthError,
  type AuthErrorEnvelope,
  type RedeemPrepareResponse
} from "../../../_auth/contracts";
import {
  createRedemptionRecovery,
  invitationRequest,
  isCompleteInvitationRequest,
  readJsonResponse,
  readRedemptionRecovery,
  recoveryCookieName,
  setRecoveryCookie,
  validateRecoveryConfiguration
} from "../../../_auth/recovery";
import { apiBase } from "../../../runtime";

const SURFACE = "admin" as const;

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => undefined) as {
    invitation_id?: unknown;
    invite_token?: unknown;
  } | undefined;
  const redeemRequest = invitationRequest(
    typeof body?.invitation_id === "string" ? body.invitation_id : "",
    typeof body?.invite_token === "string" ? body.invite_token : "",
    SURFACE
  );
  if (!isCompleteInvitationRequest(redeemRequest)) {
    return errorResponse({
      code: "auth_invalid_request",
      detail: "Invitation ID and one-time token are required.",
      correlation_id: randomUUID()
    }, 400);
  }
  try {
    validateRecoveryConfiguration();
  } catch {
    return errorResponse({
      code: "auth_recovery_unavailable",
      detail: "Secure login recovery is unavailable.",
      correlation_id: randomUUID()
    }, 503);
  }

  const existingRecovery = readRedemptionRecovery(
    request.cookies.get(recoveryCookieName(SURFACE))?.value,
    redeemRequest
  );
  if (existingRecovery) {
    return NextResponse.json<RedeemPrepareResponse>({
      prepared: true,
      compatibility: "compatible",
      requested_surface: SURFACE,
      recommended_surface: SURFACE,
      policy_version: AUTHZ_POLICY_VERSION,
      correlation_id: randomUUID()
    }, { headers: { "Cache-Control": "no-store" } });
  }

  let upstream: Response;
  try {
    upstream = await fetch(new URL("/v1/auth/invitations/preflight", apiBase()), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(redeemRequest),
      cache: "no-store"
    });
  } catch {
    return errorResponse({
      code: "auth_upstream_unavailable",
      detail: "The authentication service is temporarily unavailable.",
      correlation_id: randomUUID()
    }, 502);
  }

  const payload = await readJsonResponse(upstream);
  if (!upstream.ok) {
    return errorResponse(
      parseAuthError(payload, "auth_request_failed", "Invitation preflight failed.", randomUUID()),
      upstream.status
    );
  }
  if (!isInvitationPreflightResponse(payload)) {
    return errorResponse({
      code: "auth_request_failed",
      detail: "The authentication service returned an invalid preflight response.",
      correlation_id: randomUUID()
    }, 502);
  }
  if (
    payload.requested_surface !== SURFACE
    || (payload.compatibility === "compatible" && payload.recommended_surface !== SURFACE)
    || (payload.compatibility === "surface_mismatch" && payload.recommended_surface === SURFACE)
  ) {
    return errorResponse({
      code: "auth_request_failed",
      detail: "The authentication service returned an inconsistent surface decision.",
      correlation_id: payload.correlation_id
    }, 502);
  }
  if (payload.compatibility !== "compatible") {
    if (payload.compatibility === "surface_mismatch") {
      return errorResponse({
        code: "invitation_surface_mismatch",
        detail: "This invitation cannot open the requested surface.",
        correlation_id: payload.correlation_id,
        recommended_surface: payload.recommended_surface,
        invitation_consumed: false
      }, 409);
    }
    return errorResponse({
      code: payload.compatibility === "policy_stale" ? "invitation_policy_stale" : "invitation_invalid",
      detail: "This invitation cannot be used.",
      correlation_id: payload.correlation_id
    }, 409);
  }

  try {
    const recovery = createRedemptionRecovery(redeemRequest);
    const response = NextResponse.json<RedeemPrepareResponse>({
      prepared: true,
      compatibility: "compatible",
      requested_surface: SURFACE,
      recommended_surface: payload.recommended_surface,
      policy_version: AUTHZ_POLICY_VERSION,
      correlation_id: payload.correlation_id
    }, { headers: { "Cache-Control": "no-store" } });
    setRecoveryCookie(response, SURFACE, recovery.cookieValue);
    return response;
  } catch {
    return errorResponse({
      code: "auth_recovery_unavailable",
      detail: "Secure login recovery is unavailable.",
      correlation_id: payload.correlation_id
    }, 503);
  }
}

function errorResponse(error: AuthErrorEnvelope, status: number) {
  return NextResponse.json(error, { status, headers: { "Cache-Control": "no-store" } });
}
