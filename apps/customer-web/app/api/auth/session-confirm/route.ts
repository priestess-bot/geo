import { randomUUID } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";

import {
  isRuntimeAuthMeResponse,
  parseAuthError,
  type AuthErrorEnvelope,
  type RuntimeAuthMeResponse
} from "../../../_auth/contracts";
import {
  clearRecoveryCookie,
  inspectSessionDeliveryRecovery,
  readJsonResponse,
  recoveryCookieName,
  validateRecoveryConfiguration
} from "../../../_auth/recovery";
import { apiBase } from "../../../runtime";

const SURFACE = "customer" as const;

export async function POST(request: NextRequest) {
  const sessionToken = request.cookies.get("GEO_RUNTIME_SESSION")?.value || "";
  const csrfToken = request.cookies.get("GEO_CSRF_TOKEN")?.value || "";
  if (!sessionToken || !csrfToken) {
    return errorResponse({
      code: "auth_session_delivery_invalid",
      detail: "Complete session and CSRF cookies are required before confirmation.",
      correlation_id: randomUUID()
    }, 409);
  }
  const recoveryCookie = request.cookies.get(recoveryCookieName(SURFACE))?.value;
  if (!recoveryCookie) {
    return noPendingDelivery("not_pending");
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
  const recovery = inspectSessionDeliveryRecovery(recoveryCookie, SURFACE, sessionToken);
  if (recovery.status === "prepared") {
    return noPendingDelivery("delivery_not_received");
  }
  if (recovery.status !== "delivered") {
    return errorResponse({
      code: "auth_session_delivery_invalid",
      detail: "The current session does not match the pending recovered delivery.",
      correlation_id: randomUUID()
    }, 409);
  }

  let upstream: Response;
  try {
    upstream = await fetch(new URL("/v1/auth/me", apiBase()), {
      headers: {
        "X-GEO-Session-Token": sessionToken,
        ...(csrfToken ? { "X-GEO-CSRF-Token": csrfToken } : {}),
        Cookie: [
          `GEO_RUNTIME_SESSION=${encodeURIComponent(sessionToken)}`,
          ...(csrfToken ? [`GEO_CSRF_TOKEN=${encodeURIComponent(csrfToken)}`] : [])
        ].join("; ")
      },
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
      parseAuthError(payload, "auth_request_failed", "Session confirmation failed.", randomUUID()),
      upstream.status
    );
  }
  if (!isRuntimeAuthMeResponse(payload)) {
    return errorResponse({
      code: "auth_session_delivery_invalid",
      detail: "The authentication service returned an invalid session scope.",
      correlation_id: randomUUID()
    }, 502);
  }

  const response = NextResponse.json<RuntimeAuthMeResponse>(payload, {
    headers: { "Cache-Control": "no-store" }
  });
  clearRecoveryCookie(response, SURFACE);
  return response;
}

function errorResponse(error: AuthErrorEnvelope, status: number) {
  return NextResponse.json(error, { status, headers: { "Cache-Control": "no-store" } });
}

function noPendingDelivery(status: "not_pending" | "delivery_not_received") {
  return NextResponse.json({ status }, { status: 202, headers: { "Cache-Control": "no-store" } });
}
