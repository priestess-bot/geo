import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
  timingSafeEqual
} from "node:crypto";
import { readFileSync } from "node:fs";
import type { NextResponse } from "next/server";

import type { InvitationRequest, InvitationSurface } from "./contracts";

const RECOVERY_VERSION = 1 as const;
const RECOVERY_TTL_SECONDS = 10 * 60;
const RECOVERY_AAD = Buffer.from("geno-auth-recovery:v1", "utf8");
const COOKIE_NAMES: Record<InvitationSurface, string> = {
  admin: "GENO_ADMIN_REDEEM_RECOVERY",
  customer: "GENO_CUSTOMER_REDEEM_RECOVERY"
};

export interface RedemptionRecoveryPayload {
  version: typeof RECOVERY_VERSION;
  key: string;
  requested_surface: InvitationSurface;
  token_fingerprint: string;
  request_hash: string;
  issued_at: number;
  expires_at: number;
}

type UntrustedRecoveryPayload = {
  version?: unknown;
  key?: unknown;
  requested_surface?: unknown;
  token_fingerprint?: unknown;
  request_hash?: unknown;
  issued_at?: unknown;
  expires_at?: unknown;
};

export function recoveryCookieName(surface: InvitationSurface): string {
  return COOKIE_NAMES[surface];
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
  const payload: RedemptionRecoveryPayload = {
    version: RECOVERY_VERSION,
    key: randomBytes(32).toString("base64url"),
    requested_surface: request.requested_surface,
    token_fingerprint: tokenFingerprint(request.invite_token),
    request_hash: requestHash(request),
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
      || payload.expires_at <= nowSeconds
      || payload.issued_at > nowSeconds + 30
      || payload.expires_at - payload.issued_at !== RECOVERY_TTL_SECONDS
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

export function setRecoveryCookie(
  response: NextResponse,
  surface: InvitationSurface,
  value: string
): void {
  response.cookies.set(recoveryCookieName(surface), value, {
    httpOnly: true,
    secure: secureCookiesEnabled(),
    sameSite: "lax",
    path: "/",
    maxAge: RECOVERY_TTL_SECONDS
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
    cookies.some((cookie) => /^GENO_RUNTIME_SESSION=/i.test(cookie))
    && cookies.some((cookie) => /^GENO_CSRF_TOKEN=/i.test(cookie))
  );
}

export function validateRecoveryConfiguration(): { secureCookies: boolean } {
  recoverySecret();
  return { secureCookies: secureCookiesEnabled() };
}

function recoverySecret(): string {
  const directSecret = process.env.GENO_AUTH_RECOVERY_COOKIE_SECRET || "";
  const secretFile = (process.env.GENO_AUTH_RECOVERY_COOKIE_SECRET_FILE || "").trim();
  if (directSecret && secretFile) {
    throw new Error("recovery secret must use exactly one source");
  }
  const secret = secretFile ? readFileSync(secretFile, "utf8").trimEnd() : directSecret;
  if (Buffer.byteLength(secret, "utf8") < 32) {
    throw new Error("GENO_AUTH_RECOVERY_COOKIE_SECRET must contain at least 32 bytes");
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
    || (candidate.requested_surface !== "admin" && candidate.requested_surface !== "customer")
    || typeof candidate.key !== "string"
    || candidate.key.length < 32
    || typeof candidate.token_fingerprint !== "string"
    || typeof candidate.request_hash !== "string"
    || typeof candidate.issued_at !== "number"
    || !Number.isInteger(candidate.issued_at)
    || typeof candidate.expires_at !== "number"
    || !Number.isInteger(candidate.expires_at)
  ) {
    throw new Error("invalid recovery payload fields");
  }
  return candidate as RedemptionRecoveryPayload;
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
  const configured = process.env.GENO_RUNTIME_SESSION_COOKIE_SECURE;
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
  throw new Error("GENO_RUNTIME_SESSION_COOKIE_SECURE must be a strict boolean");
}
