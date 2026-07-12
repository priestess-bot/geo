import { type NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  if (hasInvitationTokenKey(request.nextUrl.searchParams)) {
    const landing = new URL("/", request.url);
    copySafeValue(request.nextUrl.searchParams, landing.searchParams, "invitation_id", 80);
    if (request.cookies.get("GENO_RUNTIME_SESSION")?.value) {
      copySafeProjectId(request.nextUrl.searchParams, landing.searchParams);
    }
    return withNoReferrer(NextResponse.redirect(landing, 303));
  }
  return withNoReferrer(NextResponse.next());
}

function hasInvitationTokenKey(search: URLSearchParams): boolean {
  return Array.from(search.keys()).some((key) => key.toLowerCase() === "invite_token");
}

function copySafeValue(
  source: URLSearchParams,
  target: URLSearchParams,
  key: "invitation_id",
  maxLength: number
): void {
  const value = (source.get(key) || "").trim();
  if (value && value.length <= maxLength) {
    target.set(key, value);
  }
}

function copySafeProjectId(source: URLSearchParams, target: URLSearchParams): void {
  const projectId = (source.get("project_id") || "").trim();
  if (/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(projectId)) {
    target.set("project_id", projectId);
  }
}

function withNoReferrer<T extends NextResponse>(response: T): T {
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

export const config = {
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"]
};
