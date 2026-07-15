import { type NextRequest, NextResponse } from "next/server";

import { apiBase } from "../../../runtime";
import { clearRecoveryCookie } from "../../../_auth/recovery";

export async function POST(request: NextRequest) {
  const sessionToken = request.cookies.get("GEO_RUNTIME_SESSION")?.value || "";
  const csrfToken = request.cookies.get("GEO_CSRF_TOKEN")?.value || "";
  if (sessionToken && csrfToken) {
    await fetch(new URL("/v1/auth/logout", apiBase()), {
      method: "POST",
      headers: {
        "X-GEO-Session-Token": sessionToken,
        "X-GEO-CSRF-Token": csrfToken,
        Cookie: `GEO_CSRF_TOKEN=${encodeURIComponent(csrfToken)}`
      },
      cache: "no-store"
    }).catch(() => undefined);
  }
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.delete("GEO_RUNTIME_SESSION");
  response.cookies.delete("GEO_CSRF_TOKEN");
  clearRecoveryCookie(response, "admin");
  return response;
}
