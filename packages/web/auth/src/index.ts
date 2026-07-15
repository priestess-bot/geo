/** Browser cookie and upstream header names are defined once for both portal surfaces. */
export const GEO_SESSION_COOKIE = "GEO_RUNTIME_SESSION";
export const GEO_CSRF_COOKIE = "GEO_CSRF_TOKEN";
export const GEO_CSRF_HEADER = "X-GEO-CSRF-Token";
export const GEO_SESSION_HEADER = "X-GEO-Session-Token";
export const GEO_ACTOR_HEADER = "X-GEO-Actor-Id";
export const GEO_REQUEST_ID_HEADER = "X-GEO-Request-Id";

export type PortalSurface = "admin" | "customer";

export function recoveryCookieName(surface: PortalSurface): string {
  return surface === "admin" ? "GEO_ADMIN_REDEEM_RECOVERY" : "GEO_CUSTOMER_REDEEM_RECOVERY";
}
