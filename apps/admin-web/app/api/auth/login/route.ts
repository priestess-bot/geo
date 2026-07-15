import { adminOidcRedirect } from "@geo/auth/admin-oidc";

export function GET(): Response {
  return adminOidcRedirect({
    targetUrl: process.env.GEO_ADMIN_OIDC_LOGIN_URL,
    allowedOrigins: process.env.GEO_ADMIN_OIDC_ALLOWED_ORIGINS,
    unavailableDetail: "Admin OIDC login is not configured."
  });
}

export const POST = GET;
