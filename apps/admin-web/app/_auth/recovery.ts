import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createHmac,
  randomBytes,
  timingSafeEqual
} from "node:crypto";
import { readFileSync } from "node:fs";
import type { NextResponse } from "next/server";

import {
  GEO_CSRF_COOKIE,
  GEO_SESSION_COOKIE,
  recoveryCookieName as sharedRecoveryCookieName
} from "@geo/auth";
import type { InvitationRequest, InvitationSurface } from "@geo/types/auth";

const RECOVERY_VERSION = 1 as const;
const RECOVERY_TTL_SECONDS = 10 * 60;
const RECOVERY_AAD = Buffer.from("geo-auth-recovery:v1", "utf8");

export interface RedemptionRecoveryPayload {
  version: typeof RECOVERY_VERSION;
  phase: "prepared" | "delivered";
  key: string;
  requested_surface: InvitationSurface;
  token_fingerprint: string;
  request_hash: string;
  issued_at: number;
  expires_at: number;
  session_token_fingerprint?: string;
}

export type SessionDeliveryRecoveryCheck =
  | { status: "prepared"; payload: RedemptionRecoveryPayload }
  | { status: "delivered"; payload: RedemptionRecoveryPayload }
  | { status: "session_mismatch" }
  | { status: "invalid" };

type UntrustedRecoveryPayload = {
  version?: unknown;
  phase?: unknown;
  key?: unknown;
  requested_surface?: unknown;
  token_fingerprint?: unknown;
  request_hash?: unknown;
  issued_at?: unknown;
  expires_at?: unknown;
  session_token_fingerprint?: unknown;
};

export function recoveryCookieName(surface: InvitationSurface): string {
  return sharedRecoveryCookieName(surface);
}

export function invitationRequest(
  invitationId: string,
  inviteToken: string,
  requestedSurface: InvitationSurface
): InvitationRequest {
  return {
    invitation_id: invitationId.trim(),
    invite_token: inviteToken.trim(),
    requested_surface: requestedSurface
  };
}

export function isCompleteInvitationRequest(request: InvitationRequest): boolean {
  return Boolean(request.invitation_id && request.invite_token);
}

export function createRedemptionRecovery(request: InvitationRequest, now = Date.now()): {
  cookieValue: string;
  payload: RedemptionRecoveryPayload;
} {
  const issuedAt = Math.floor(now / 1000);
  const frozenRequestHash = requestHash(request);
  const payload: RedemptionRecoveryPayload = {
    version: RECOVERY_VERSION,
    phase: "prepared",
    key: stableIdempotencyKey(request.requested_surface, frozenRequestHash),
    requested_surface: request.requested_surface,
    token_fingerprint: tokenFingerprint(request.invite_token),
    request_hash: frozenRequestHash,
    issued_at: issuedAt,
    expires_at: issuedAt + RECOVERY_TTL_SECONDS
  };
  return { cookieValue: encryptPayload(payload), payload };
}

export function readRedemptionRecovery(
  cookieValue: string | undefined,
  request: InvitationRequest,
  now = Date.now()
): RedemptionRecoveryPayload | null {
  if (!cookieValue) {
    return null;
  }
  try {
    const payload = decryptPayload(cookieValue);
    const nowSeconds = Math.floor(now / 1000);
    if (
      payload.requested_surface !== request.requested_surface
      || !recoveryIsCurrent(payload, nowSeconds)
      || !safeEqual(payload.token_fingerprint, tokenFingerprint(request.invite_token))
      || !safeEqual(payload.request_hash, requestHash(request))
    ) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

export function markRedemptionRecoveryDelivered(
  payload: RedemptionRecoveryPayload,
  sessionToken: string
): { cookieValue: string; payload: RedemptionRecoveryPayload } {
  const sessionFingerprint = tokenFingerprint(sessionToken);
  if (
    payload.phase === "delivered"
    && payload.session_token_fingerprint
    && !safeEqual(payload.session_token_fingerprint, sessionFingerprint)
  ) {
    throw new Error("session delivery changed for the recovery attempt");
  }
  const delivered: RedemptionRecoveryPayload = {
    ...payload,
    phase: "delivered",
    session_token_fingerprint: sessionFingerprint
  };
  return { cookieValue: encryptPayload(delivered), payload: delivered };
}

export function inspectSessionDeliveryRecovery(
  cookieValue: string | undefined,
  surface: InvitationSurface,
  sessionToken: string,
  now = Date.now()
): SessionDeliveryRecoveryCheck {
  if (!cookieValue) {
    return { status: "invalid" };
  }
  try {
    const payload = decryptPayload(cookieValue);
    if (
      payload.requested_surface !== surface
      || !recoveryIsCurrent(payload, Math.floor(now / 1000))
    ) {
      return { status: "invalid" };
    }
    if (payload.phase === "prepared") {
      return { status: "prepared", payload };
    }
    if (
      !payload.session_token_fingerprint
      || !safeEqual(payload.session_token_fingerprint, tokenFingerprint(sessionToken))
    ) {
      return { status: "session_mismatch" };
    }
    return { status: "delivered", payload };
  } catch {
    return { status: "invalid" };
  }
}

export function setRecoveryCookie(
  response: NextResponse,
  surface: InvitationSurface,
  value: string,
  maxAge = RECOVERY_TTL_SECONDS
): void {
  response.cookies.set(recoveryCookieName(surface), value, {
    httpOnly: true,
    secure: secureCookiesEnabled(),
    sameSite: "lax",
    path: "/",
    maxAge: Math.max(0, Math.min(RECOVERY_TTL_SECONDS, Math.floor(maxAge)))
  });
}

export function clearRecoveryCookie(response: NextResponse, surface: InvitationSurface): void {
  response.cookies.set(recoveryCookieName(surface), "", {
    httpOnly: true,
    secure: secureCookiesEnabled(),
    sameSite: "lax",
    path: "/",
    maxAge: 0
  });
}

export async function readJsonResponse(response: Response): Promise<unknown> {
  if (!(response.headers.get("content-type") || "").includes("application/json")) {
    return undefined;
  }
  return response.json().catch(() => undefined);
}

export function safeRetryAfter(value: string | null, maxSeconds = 3600): string | undefined {
  const normalized = value?.trim() || "";
  if (!/^\d{1,9}$/.test(normalized)) {
    return undefined;
  }
  const seconds = Number(normalized);
  return String(Math.max(1, Math.min(maxSeconds, seconds)));
}

export function upstreamSetCookies(headers: Headers): string[] {
  const enhanced = headers as Headers & { getSetCookie?: () => string[] };
  const values = enhanced.getSetCookie?.();
  if (values?.length) {
    return values;
  }
  const combined = headers.get("set-cookie");
  return combined ? combined.split(/,(?=\s*[!#$%&'*+\-.^_`|~0-9A-Za-z]+=)/).map((value) => value.trim()) : [];
}

export function hasCompleteSessionDelivery(cookies: string[]): boolean {
  return (
    cookies.some((cookie) => cookieNameMatches(cookie, GEO_SESSION_COOKIE))
    && cookies.some((cookie) => cookieNameMatches(cookie, GEO_CSRF_COOKIE))
  );
}

export function sessionTokenFromDelivery(cookies: string[]): string | null {
  const header = cookies.find((cookie) => cookieNameMatches(cookie, GEO_SESSION_COOKIE));
  if (!header) {
    return null;
  }
  const pair = header.split(";", 1)[0];
  const separator = pair.indexOf("=");
  const value = separator >= 0 ? pair.slice(separator + 1) : "";
  return value && /^[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]+$/.test(value)
    ? value
    : null;
}

function cookieNameMatches(cookie: string, name: string): boolean {
  return cookie.toLowerCase().startsWith(`${name.toLowerCase()}=`);
}

export function validateRecoveryConfiguration(): { secureCookies: boolean } {
  recoverySecret();
  return { secureCookies: secureCookiesEnabled() };
}

function recoverySecret(): string {
  const directSecret = process.env.GEO_AUTH_RECOVERY_COOKIE_SECRET || "";
  const secretFile = (process.env.GEO_AUTH_RECOVERY_COOKIE_SECRET_FILE || "").trim();
  if (directSecret && secretFile) {
    throw new Error("recovery secret must use exactly one source");
  }
  const secret = secretFile ? readFileSync(secretFile, "utf8").trimEnd() : directSecret;
  if (Buffer.byteLength(secret, "utf8") < 32) {
    throw new Error("GEO_AUTH_RECOVERY_COOKIE_SECRET must contain at least 32 bytes");
  }
  return secret;
}

function encryptionKey(): Buffer {
  return createHash("sha256").update(recoverySecret(), "utf8").digest();
}

function encryptPayload(payload: RedemptionRecoveryPayload): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(), iv);
  cipher.setAAD(RECOVERY_AAD);
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(payload), "utf8"),
    cipher.final()
  ]);
  const tag = cipher.getAuthTag();
  return `v1.${iv.toString("base64url")}.${ciphertext.toString("base64url")}.${tag.toString("base64url")}`;
}

function decryptPayload(value: string): RedemptionRecoveryPayload {
  const [version, encodedIv, encodedCiphertext, encodedTag, extra] = value.split(".");
  if (version !== "v1" || !encodedIv || !encodedCiphertext || !encodedTag || extra !== undefined) {
    throw new Error("invalid recovery envelope");
  }
  const iv = Buffer.from(encodedIv, "base64url");
  const ciphertext = Buffer.from(encodedCiphertext, "base64url");
  const tag = Buffer.from(encodedTag, "base64url");
  if (iv.length !== 12 || tag.length !== 16 || !ciphertext.length) {
    throw new Error("invalid recovery envelope encoding");
  }
  const decipher = createDecipheriv("aes-256-gcm", encryptionKey(), iv);
  decipher.setAAD(RECOVERY_AAD);
  decipher.setAuthTag(tag);
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
  return validatePayload(JSON.parse(plaintext) as unknown);
}

function validatePayload(value: unknown): RedemptionRecoveryPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid recovery payload");
  }
  const candidate = value as UntrustedRecoveryPayload;
  if (
    candidate.version !== RECOVERY_VERSION
    || (candidate.phase !== "prepared" && candidate.phase !== "delivered")
    || (candidate.requested_surface !== "admin" && candidate.requested_surface !== "customer")
    || typeof candidate.key !== "string"
    || candidate.key.length < 32
    || typeof candidate.token_fingerprint !== "string"
    || typeof candidate.request_hash !== "string"
    || typeof candidate.issued_at !== "number"
    || !Number.isInteger(candidate.issued_at)
    || typeof candidate.expires_at !== "number"
    || !Number.isInteger(candidate.expires_at)
    || (candidate.phase === "prepared" && candidate.session_token_fingerprint !== undefined)
    || (candidate.phase === "delivered"
      && (typeof candidate.session_token_fingerprint !== "string"
        || !/^[a-f0-9]{64}$/.test(candidate.session_token_fingerprint)))
  ) {
    throw new Error("invalid recovery payload fields");
  }
  return candidate as RedemptionRecoveryPayload;
}

function stableIdempotencyKey(surface: InvitationSurface, frozenRequestHash: string): string {
  return createHmac("sha256", recoverySecret())
    .update(`geo-auth-idempotency:v${RECOVERY_VERSION}\0${surface}\0${frozenRequestHash}`, "utf8")
    .digest("base64url");
}

function recoveryIsCurrent(payload: RedemptionRecoveryPayload, nowSeconds: number): boolean {
  return (
    payload.expires_at > nowSeconds
    && payload.issued_at <= nowSeconds + 30
    && payload.expires_at - payload.issued_at === RECOVERY_TTL_SECONDS
  );
}

function tokenFingerprint(inviteToken: string): string {
  return createHash("sha256").update(inviteToken, "utf8").digest("hex");
}

function requestHash(request: InvitationRequest): string {
  const canonical = JSON.stringify({
    invitation_id: request.invitation_id,
    invite_token: request.invite_token,
    requested_surface: request.requested_surface
  });
  return createHash("sha256").update(canonical, "utf8").digest("hex");
}

function safeEqual(left: string, right: string): boolean {
  const leftBuffer = Buffer.from(left, "utf8");
  const rightBuffer = Buffer.from(right, "utf8");
  return leftBuffer.length === rightBuffer.length && timingSafeEqual(leftBuffer, rightBuffer);
}

function secureCookiesEnabled(): boolean {
  const configured = process.env.GEO_RUNTIME_SESSION_COOKIE_SECURE;
  if (configured === undefined || configured.trim() === "") {
    return process.env.NODE_ENV === "production";
  }
  const normalized = configured.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    if (process.env.NODE_ENV === "production") {
      throw new Error("secure recovery cookies cannot be disabled in production");
    }
    return false;
  }
  throw new Error("GEO_RUNTIME_SESSION_COOKIE_SECURE must be a strict boolean");
}
