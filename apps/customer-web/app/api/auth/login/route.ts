import { randomUUID } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";

import { parseAuthError, type AuthErrorEnvelope } from "../../../_auth/contracts";
import {
  hasCompleteSessionDelivery,
  invitationRequest,
  isCompleteInvitationRequest,
  markRedemptionRecoveryDelivered,
  readJsonResponse,
  readRedemptionRecovery,
  recoveryCookieName,
  safeRetryAfter,
  sessionTokenFromDelivery,
  setRecoveryCookie,
  upstreamSetCookies,
  validateRecoveryConfiguration
} from "../../../_auth/recovery";
import { apiBase } from "../../../runtime";

const SURFACE = "customer" as const;
const LANDING = "/";

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

  const recovery = readRedemptionRecovery(
    request.cookies.get(recoveryCookieName(SURFACE))?.value,
    redeemRequest
  );
  if (!recovery) {
    return errorResponse({
      code: "redeem_prepare_required",
      detail: "Prepare this invitation before redeeming it.",
      correlation_id: randomUUID()
    }, 428);
  }

  let upstream: Response;
  try {
    upstream = await fetch(new URL("/v1/auth/invitations/redeem", apiBase()), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": recovery.key
      },
      body: JSON.stringify(redeemRequest),
      cache: "no-store"
    });
  } catch {
    return errorResponse({
      code: "auth_upstream_unavailable",
      detail: "The authentication service is temporarily unavailable. Retry this login to recover the same session.",
      correlation_id: randomUUID()
    }, 502);
  }

  const payload = await readJsonResponse(upstream);
  if (!upstream.ok) {
    return errorResponse(
      parseAuthError(payload, "auth_request_failed", "Invitation redemption failed.", randomUUID()),
      upstream.status,
      upstream.status === 429 ? safeRetryAfter(upstream.headers.get("retry-after")) : undefined
    );
  }
  const sessionCookies = upstreamSetCookies(upstream.headers);
  if (!hasCompleteSessionDelivery(sessionCookies)) {
    return errorResponse({
      code: "auth_session_delivery_invalid",
      detail: "The authentication service did not return a complete session delivery.",
      correlation_id: randomUUID()
    }, 502);
  }
  const deliveredSessionToken = sessionTokenFromDelivery(sessionCookies);
  if (!deliveredSessionToken) {
    return errorResponse({
      code: "auth_session_delivery_invalid",
      detail: "The authentication service returned an invalid session Cookie.",
      correlation_id: randomUUID()
    }, 502);
  }
  let deliveredRecovery: ReturnType<typeof markRedemptionRecoveryDelivered>;
  try {
    deliveredRecovery = markRedemptionRecoveryDelivered(recovery, deliveredSessionToken);
  } catch {
    return errorResponse({
      code: "auth_session_delivery_invalid",
      detail: "The authentication service changed the recovered session delivery.",
      correlation_id: randomUUID()
    }, 502);
  }

  const response = NextResponse.redirect(new URL(LANDING, request.url), 303);
  response.headers.set("Cache-Control", "no-store");
  setRecoveryCookie(
    response,
    SURFACE,
    deliveredRecovery.cookieValue,
    deliveredRecovery.payload.expires_at - Math.floor(Date.now() / 1000)
  );
  for (const cookie of sessionCookies) {
    response.headers.append("set-cookie", cookie);
  }
  return response;
}

function errorResponse(error: AuthErrorEnvelope, status: number, retryAfter?: string) {
  return NextResponse.json(error, {
    status,
    headers: { "Cache-Control": "no-store", ...(retryAfter ? { "Retry-After": retryAfter } : {}) }
  });
}
