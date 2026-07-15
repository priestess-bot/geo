import { type NextRequest, NextResponse } from "next/server";
import {
  GEO_CSRF_COOKIE,
  GEO_CSRF_HEADER,
  GEO_SESSION_COOKIE,
  GEO_SESSION_HEADER
} from "@geo/auth";

import { apiBase } from "../../../runtime";
import { clearRecoveryCookie } from "../../../_auth/recovery";

export async function POST(request: NextRequest) {
  const sessionToken = request.cookies.get(GEO_SESSION_COOKIE)?.value || "";
  const csrfToken = request.cookies.get(GEO_CSRF_COOKIE)?.value || "";
  if (sessionToken && csrfToken) {
    await fetch(new URL("/v1/auth/logout", apiBase()), {
      method: "POST",
      headers: {
        [GEO_SESSION_HEADER]: sessionToken,
        [GEO_CSRF_HEADER]: csrfToken,
        Cookie: `${GEO_CSRF_COOKIE}=${encodeURIComponent(csrfToken)}`
      },
      cache: "no-store"
    }).catch(() => undefined);
  }
  const response = NextResponse.redirect(new URL("/", request.url), 303);
  response.cookies.delete(GEO_SESSION_COOKIE);
  response.cookies.delete(GEO_CSRF_COOKIE);
  clearRecoveryCookie(response, "customer");
  return response;
}
