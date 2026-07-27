import { NextResponse } from "next/server";

export function middleware(): NextResponse {
  const response = NextResponse.next();
  response.headers.set("Referrer-Policy", "same-origin");
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]
};
