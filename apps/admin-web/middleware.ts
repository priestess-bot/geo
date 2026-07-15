import { type NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  if (hasInvitationTokenKey(request.nextUrl.searchParams)) {
    const login = new URL("/login", request.url);
    copySafeInvitationId(request.nextUrl.searchParams, login.searchParams);
    return withNoReferrer(NextResponse.redirect(login, 303));
  }
  if ((process.env.GEO_RUNTIME_AUTH_MODE || "header") !== "session") {
    return withNoReferrer(NextResponse.next());
  }
  if (request.nextUrl.pathname === "/login") {
    return withNoReferrer(NextResponse.next());
  }
  if (request.cookies.get("GEO_RUNTIME_SESSION")?.value) {
    return withNoReferrer(NextResponse.next());
  }
  const login = new URL("/login", request.url);
  return withNoReferrer(NextResponse.redirect(login, 303));
}

function hasInvitationTokenKey(search: URLSearchParams): boolean {
  return Array.from(search.keys()).some((key) => key.toLowerCase() === "invite_token");
}

function copySafeInvitationId(source: URLSearchParams, target: URLSearchParams): void {
  const invitationId = (source.get("invitation_id") || "").trim();
  if (invitationId && invitationId.length <= 80) {
    target.set("invitation_id", invitationId);
  }
}

function withNoReferrer<T extends NextResponse>(response: T): T {
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}

export const config = {
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"]
};
