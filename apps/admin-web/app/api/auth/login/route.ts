import { randomUUID } from "node:crypto";
import { type NextRequest, NextResponse } from "next/server";

import { apiBase } from "../../../runtime";

const ADMIN_ROLES = new Set(["owner", "admin", "super_admin", "tenant_admin"]);

function redirectWithError(request: NextRequest, message: string) {
  const url = new URL("/login", request.url);
  url.searchParams.set("error", message);
  return NextResponse.redirect(url, 303);
}

function upstreamCookies(headers: Headers): string[] {
  const enhanced = headers as Headers & { getSetCookie?: () => string[] };
  const values = enhanced.getSetCookie?.() || [];
  if (values.length) {
    return values;
  }
  const combined = headers.get("set-cookie");
  return combined ? combined.split(/,(?=\s*GENO_)/).map((value) => value.trim()) : [];
}

function hasAdminRole(payload: Record<string, unknown>): boolean {
  const session = payload.session && typeof payload.session === "object" ? payload.session as Record<string, unknown> : {};
  const auth = payload.auth && typeof payload.auth === "object" ? payload.auth as Record<string, unknown> : {};
  const roles = Array.isArray(session.roles) ? session.roles : Array.isArray(auth.roles) ? auth.roles : [];
  return roles.some((role) => ADMIN_ROLES.has(String(role).toLowerCase()));
}

export async function POST(request: NextRequest) {
  const form = await request.formData();
  const invitationId = String(form.get("invitation_id") || "").trim();
  const inviteToken = String(form.get("invite_token") || "").trim();
  const sessionToken = String(form.get("session_token") || "").trim();
  let payload: Record<string, unknown> = {};
  let setCookies: string[] = [];

  if (sessionToken) {
    const upstream = await fetch(new URL("/v1/auth/me", apiBase()), {
      headers: { "X-GENO-Session-Token": sessionToken },
      cache: "no-store"
    });
    payload = upstream.ok ? await upstream.json() as Record<string, unknown> : {};
    if (!upstream.ok || !hasAdminRole(payload)) {
      return redirectWithError(request, "Session 无效，或当前用户没有管理权限。");
    }
  } else {
    if (!invitationId || !inviteToken) {
      return redirectWithError(request, "请同时填写邀请 ID 和一次性邀请 token。");
    }
    const upstream = await fetch(new URL("/v1/auth/invitations/redeem", apiBase()), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ invitation_id: invitationId, invite_token: inviteToken, reason: "admin_web_login" }),
      cache: "no-store"
    });
    payload = upstream.headers.get("content-type")?.includes("application/json")
      ? await upstream.json() as Record<string, unknown>
      : {};
    if (!upstream.ok) {
      return redirectWithError(request, String(payload.detail || "邀请无法兑换。"));
    }
    if (!hasAdminRole(payload)) {
      return redirectWithError(request, "该邀请没有管理权限，请使用 owner/admin 邀请。");
    }
    setCookies = upstreamCookies(upstream.headers);
  }

  const response = NextResponse.redirect(new URL("/projects", request.url), 303);
  if (sessionToken) {
    const secure = process.env.GENO_RUNTIME_SESSION_COOKIE_SECURE === "1";
    response.cookies.set("GENO_RUNTIME_SESSION", sessionToken, {
      httpOnly: true,
      secure,
      sameSite: "lax",
      maxAge: 7 * 24 * 60 * 60,
      path: "/"
    });
    response.cookies.set("GENO_CSRF_TOKEN", randomUUID(), {
      httpOnly: false,
      secure,
      sameSite: "lax",
      maxAge: 7 * 24 * 60 * 60,
      path: "/"
    });
  } else {
    for (const cookie of setCookies) {
      response.headers.append("set-cookie", cookie);
    }
  }
  return response;
}
