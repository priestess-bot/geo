import { type NextRequest, NextResponse } from "next/server";

import { apiBase } from "../../../runtime";

export async function POST(request: NextRequest) {
  const sessionToken = request.cookies.get("GENO_RUNTIME_SESSION")?.value || "";
  const csrfToken = request.cookies.get("GENO_CSRF_TOKEN")?.value || "";
  if (sessionToken && csrfToken) {
    await fetch(new URL("/v1/auth/logout", apiBase()), {
      method: "POST",
      headers: {
        "X-GENO-Session-Token": sessionToken,
        "X-GENO-CSRF-Token": csrfToken,
        Cookie: `GENO_CSRF_TOKEN=${encodeURIComponent(csrfToken)}`
      },
      cache: "no-store"
    }).catch(() => undefined);
  }
  const response = NextResponse.redirect(new URL("/login", request.url), 303);
  response.cookies.delete("GENO_RUNTIME_SESSION");
  response.cookies.delete("GENO_CSRF_TOKEN");
  return response;
}
