import { adminOidcRedirect } from "@geo/auth/admin-oidc";

export function POST(): Response {
  return adminOidcRedirect({
    targetUrl: process.env.GEO_ADMIN_OIDC_LOGOUT_URL,
    allowedOrigins: process.env.GEO_ADMIN_OIDC_ALLOWED_ORIGINS,
    unavailableDetail: "Admin OIDC logout is not configured."
  });
}
