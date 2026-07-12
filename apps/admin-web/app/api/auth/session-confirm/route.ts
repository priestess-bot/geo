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
  readJsonResponse,
  validateRecoveryConfiguration
} from "../../../_auth/recovery";
import { apiBase } from "../../../runtime";

const SURFACE = "admin" as const;

export async function POST(request: NextRequest) {
  const sessionToken = request.cookies.get("GENO_RUNTIME_SESSION")?.value || "";
  const csrfToken = request.cookies.get("GENO_CSRF_TOKEN")?.value || "";
  if (!sessionToken) {
    return errorResponse({
      code: "auth_request_failed",
      detail: "An authenticated session is required.",
      correlation_id: randomUUID()
    }, 401);
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

  let upstream: Response;
  try {
    upstream = await fetch(new URL("/v1/auth/me", apiBase()), {
      headers: {
        "X-GENO-Session-Token": sessionToken,
        ...(csrfToken ? { "X-GENO-CSRF-Token": csrfToken } : {}),
        Cookie: [
          `GENO_RUNTIME_SESSION=${encodeURIComponent(sessionToken)}`,
          ...(csrfToken ? [`GENO_CSRF_TOKEN=${encodeURIComponent(csrfToken)}`] : [])
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
