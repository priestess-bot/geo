import { type NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  if ((process.env.GENO_RUNTIME_AUTH_MODE || "header") !== "session") {
    return NextResponse.next();
  }
  if (request.cookies.get("GENO_RUNTIME_SESSION")?.value) {
    return NextResponse.next();
  }
  const login = new URL("/login", request.url);
  login.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!login|api/auth|_next/static|_next/image|favicon.ico).*)"]
};
