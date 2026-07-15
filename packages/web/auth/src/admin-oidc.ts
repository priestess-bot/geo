export type AdminOidcRedirectOptions = Readonly<{
  targetUrl?: string;
  allowedOrigins?: string;
  unavailableDetail: string;
}>;

export function adminOidcRedirect(options: AdminOidcRedirectOptions): Response {
  let location: URL;
  try {
    location = trustedOidcUrl(options.targetUrl, options.allowedOrigins);
  } catch {
    return Response.json(
      {
        code: "admin_oidc_unavailable",
        detail: options.unavailableDetail,
        correlation_id: ""
      },
      { status: 503, headers: securityHeaders() }
    );
  }
  const headers = securityHeaders();
  headers.set("Location", location.toString());
  return new Response(null, { status: 303, headers });
}

export function trustedOidcUrl(rawUrl?: string, rawAllowedOrigins?: string): URL {
  const value = rawUrl?.trim() || "";
  const allowedOrigins = (rawAllowedOrigins || "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
  if (!value || allowedOrigins.length === 0) {
    throw new TypeError("The Admin OIDC redirect is not configured.");
  }
  const target = new URL(value);
  if (
    target.protocol !== "https:"
    || target.username
    || target.password
    || target.hash
    || !allowedOrigins.includes(target.origin)
  ) {
    throw new TypeError("The Admin OIDC redirect is not trusted.");
  }
  for (const origin of allowedOrigins) {
    const parsed = new URL(origin);
    if (parsed.protocol !== "https:" || parsed.origin !== origin.replace(/\/$/, "")) {
      throw new TypeError("The Admin OIDC allowlist contains an invalid origin.");
    }
  }
  return target;
}

function securityHeaders(): Headers {
  return new Headers({
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff"
  });
}
