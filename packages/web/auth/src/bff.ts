import { AuthApiClient } from "@geo/api-client/auth";
import {
  isInvitationPreflightResponse,
  parseAuthError,
  type InvitationRequest,
  type InvitationSurface
} from "@geo/types/auth";

import {
  GEO_CSRF_COOKIE,
  GEO_CSRF_HEADER,
  GEO_SESSION_COOKIE
} from "./index";

export async function prepareInvitation(
  request: Request,
  options: BffOptions
): Promise<Response> {
  const payload = await invitationRequest(request, options.surface);
  if (!payload) return authError("auth_invalid_request", "Invitation credentials are required.", 400);
  const upstream = await call(() => new AuthApiClient(options.apiBase).preflight(payload));
  if (!upstream) return unavailable();
  const body = await json(upstream);
  if (!upstream.ok) return mirror(upstream, body);
  if (!isInvitationPreflightResponse(body)) {
    return authError("auth_request_failed", "Authentication returned an invalid response.", 502);
  }
  if (body.requested_surface !== options.surface) {
    return authError("auth_request_failed", "Authentication returned an inconsistent portal decision.", 502);
  }
  if (body.compatibility !== "compatible") {
    return authError(
      body.compatibility === "surface_mismatch"
        ? "invitation_surface_mismatch"
        : "invitation_invalid",
      body.compatibility === "surface_mismatch"
        ? "This invitation belongs to the Customer portal."
        : "This invitation is invalid.",
      409,
      body.recommended_surface || undefined
    );
  }
  return Response.json({ prepared: true, ...body }, { headers: noStoreHeaders() });
}

export async function redeemInvitation(
  request: Request,
  options: BffOptions & { landingPath: string }
): Promise<Response> {
  const payload = await invitationRequest(request, options.surface);
  if (!payload) return authError("auth_invalid_request", "Invitation credentials are required.", 400);
  const client = new AuthApiClient(options.apiBase);
  const preflight = await call(() => client.preflight(payload));
  if (!preflight) return unavailable();
  const preflightBody = await json(preflight);
  if (!preflight.ok) return mirror(preflight, preflightBody);
  if (!isInvitationPreflightResponse(preflightBody)) {
    return authError("auth_request_failed", "Authentication returned an invalid response.", 502);
  }
  if (preflightBody.requested_surface !== options.surface) {
    return authError("auth_request_failed", "Authentication returned an inconsistent portal decision.", 502);
  }
  if (preflightBody.compatibility !== "compatible") {
    const recommended = preflightBody.recommended_surface || undefined;
    return authError(
      recommended ? "invitation_surface_mismatch" : "invitation_invalid",
      recommended ? "This invitation belongs to the Customer portal." : "This invitation is invalid.",
      recommended ? 409 : 400,
      recommended
    );
  }
  const idempotencyKey = await redeemIdempotencyKey(payload);
  const redeemed = await call(() => client.redeem(payload, idempotencyKey));
  if (!redeemed) return unavailable();
  const body = await json(redeemed);
  if (!redeemed.ok) return mirror(redeemed, body);
  const sessionCookies = validatedSessionCookies(redeemed.headers);
  if (!sessionCookies) {
    return authError(
      "auth_request_failed",
      "Authentication did not return a complete secure session.",
      502
    );
  }
  const headers = noStoreHeaders();
  for (const cookie of sessionCookies) headers.append("Set-Cookie", cookie);
  headers.set("Location", new URL(options.landingPath, request.url).toString());
  return new Response(null, { status: 303, headers });
}

export async function logoutSession(
  request: Request,
  options: BffOptions & { landingPath: string }
): Promise<Response> {
  const cookie = request.headers.get("cookie") || "";
  const csrf = cookieValue(cookie, GEO_CSRF_COOKIE);
  const upstream = csrf
    ? await call(() => new AuthApiClient(options.apiBase).logout(cookie, csrf))
    : undefined;
  const headers = noStoreHeaders();
  if (upstream) {
    for (const value of setCookies(upstream.headers)) headers.append("Set-Cookie", value);
  }
  headers.append("Set-Cookie", expiredCookie(GEO_SESSION_COOKIE, true));
  headers.append("Set-Cookie", expiredCookie(GEO_CSRF_COOKIE, false));
  headers.set("Location", new URL(options.landingPath, request.url).toString());
  return new Response(null, { status: 303, headers });
}

type BffOptions = Readonly<{ apiBase: string; surface: InvitationSurface }>;

async function invitationRequest(
  request: Request,
  surface: InvitationSurface
): Promise<InvitationRequest | null> {
  const body = await request.json().catch(() => undefined) as Record<string, unknown> | undefined;
  const invitationId = typeof body?.invitation_id === "string" ? body.invitation_id.trim() : "";
  const inviteToken = typeof body?.invite_token === "string" ? body.invite_token.trim() : "";
  return invitationId && inviteToken
    ? { invitation_id: invitationId, invite_token: inviteToken, requested_surface: surface }
    : null;
}

async function redeemIdempotencyKey(payload: InvitationRequest): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `geo-redeem-${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function setCookies(headers: Headers): string[] {
  const enhanced = headers as Headers & { getSetCookie?: () => string[] };
  return enhanced.getSetCookie?.() || (headers.get("set-cookie") ? [headers.get("set-cookie") as string] : []);
}

function validatedSessionCookies(headers: Headers): string[] | null {
  const cookies = setCookies(headers);
  const session = cookies.find((cookie) => cookie.startsWith(`${GEO_SESSION_COOKIE}=`));
  const csrf = cookies.find((cookie) => cookie.startsWith(`${GEO_CSRF_COOKIE}=`));
  if (!session || !csrf) return null;
  const normalizedSession = session.toLowerCase();
  const normalizedCsrf = csrf.toLowerCase();
  if (
    !normalizedSession.includes("httponly")
    || !normalizedSession.includes("samesite=lax")
    || !normalizedSession.includes("path=/")
    || normalizedCsrf.includes("httponly")
    || !normalizedCsrf.includes("samesite=lax")
    || !normalizedCsrf.includes("path=/")
  ) return null;
  return [session, csrf];
}

function expiredCookie(name: string, httpOnly: boolean): string {
  return `${name}=; Path=/; Max-Age=0; SameSite=Lax${httpOnly ? "; HttpOnly" : ""}`;
}

function cookieValue(cookie: string, name: string): string {
  const entry = cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith(`${name}=`));
  return entry ? decodeURIComponent(entry.slice(name.length + 1)) : "";
}

async function call(operation: () => Promise<Response>): Promise<Response | undefined> {
  try { return await operation(); } catch { return undefined; }
}

async function json(response: Response): Promise<unknown> {
  return response.json().catch(() => undefined);
}

function mirror(response: Response, body: unknown): Response {
  const parsed = parseAuthError(body, "auth_request_failed", "Authentication request failed.");
  return Response.json(parsed, { status: response.status, headers: noStoreHeaders() });
}

function unavailable(): Response {
  return authError("auth_upstream_unavailable", "Authentication is temporarily unavailable.", 503);
}

function authError(
  code: Parameters<typeof parseAuthError>[1],
  detail: string,
  status: number,
  recommended_surface?: InvitationSurface
): Response {
  return Response.json(
    { code, detail, correlation_id: "", ...(recommended_surface ? { recommended_surface } : {}) },
    { status, headers: noStoreHeaders() }
  );
}

function noStoreHeaders(): Headers {
  return new Headers({ "Cache-Control": "no-store", "Referrer-Policy": "no-referrer" });
}

export { GEO_CSRF_HEADER };
