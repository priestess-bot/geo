import { type NextRequest, NextResponse } from "next/server";

import { apiBase } from "../../../runtime";

function upstreamCookies(headers: Headers): string[] {
  const enhanced = headers as Headers & { getSetCookie?: () => string[] };
  const values = enhanced.getSetCookie?.() || [];
  if (values.length) {
    return values;
  }
  const combined = headers.get("set-cookie");
  return combined ? combined.split(/,(?=\s*GENO_)/).map((value) => value.trim()) : [];
}

function redirectWithError(request: NextRequest, message: string) {
  const url = new URL("/", request.url);
  url.searchParams.set("error", message);
  return NextResponse.redirect(url, 303);
}

export async function POST(request: NextRequest) {
  const form = await request.formData();
  const invitationId = String(form.get("invitation_id") || "").trim();
  const inviteToken = String(form.get("invite_token") || "").trim();
  if (!invitationId || !inviteToken) {
    return redirectWithError(request, "请同时填写邀请 ID 和一次性邀请 token。");
  }
  const upstream = await fetch(new URL("/v1/auth/invitations/redeem", apiBase()), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ invitation_id: invitationId, invite_token: inviteToken, reason: "customer_web_login" }),
    cache: "no-store"
  });
  const payload = upstream.headers.get("content-type")?.includes("application/json")
    ? await upstream.json() as Record<string, unknown>
    : {};
  if (!upstream.ok) {
    return redirectWithError(request, String(payload.detail || "邀请无法兑换。"));
  }
  const response = NextResponse.redirect(new URL("/", request.url), 303);
  for (const cookie of upstreamCookies(upstream.headers)) {
    response.headers.append("set-cookie", cookie);
  }
  return response;
}
