import assert from "node:assert/strict";
import test from "node:test";

import {
  logoutSession,
  prepareInvitation,
  redeemInvitation
} from "../packages/web/auth/src/bff.ts";
import {
  adminOidcRedirect,
  trustedOidcUrl
} from "../packages/web/auth/src/admin-oidc.ts";

const credential = {
  invitation_id: "10000000-0000-4000-8000-000000000001",
  invite_token: "one-time-token-with-at-least-thirty-two-characters"
};

test("wrong portal preflight never consumes a customer invitation", async () => {
  const calls = [];
  await withFetch(async (input, init) => {
    calls.push({ input: input.toString(), init });
    return Response.json({
      compatibility: "surface_mismatch",
      requested_surface: "admin",
      recommended_surface: "customer",
      invitation_role: "viewer"
    });
  }, async () => {
    const response = await prepareInvitation(request(credential), {
      apiBase: "https://internal-api.example.test",
      surface: "admin"
    });
    assert.equal(response.status, 409);
    assert.equal((await response.json()).recommended_surface, "customer");
  });
  assert.equal(calls.length, 1);
  assert.match(calls[0].input, /\/v1\/auth\/invitations\/preflight$/);
});

test("customer redemption preflights then forwards only complete session cookies", async () => {
  const calls = [];
  await withFetch(async (input, init) => {
    calls.push({ input: input.toString(), init });
    if (calls.length === 1) {
      return Response.json({
        compatibility: "compatible",
        requested_surface: "customer",
        recommended_surface: "customer",
        invitation_role: "analyst"
      });
    }
    const headers = new Headers();
    headers.append(
      "Set-Cookie",
      "GEO_CUSTOMER_SESSION=session-value; Path=/; HttpOnly; SameSite=lax"
    );
    headers.append("Set-Cookie", "GEO_CSRF_TOKEN=csrf-value; Path=/; SameSite=lax");
    return Response.json(
      {
        recovery_status: "created",
        session: {
          actor_id: "actor",
          tenant_id: "tenant",
          project_ids: ["project"],
          roles: ["analyst"]
        },
        expires_at: "2030-01-01T00:00:00Z"
      },
      { status: 201, headers }
    );
  }, async () => {
    const response = await redeemInvitation(request(credential), {
      apiBase: "https://customer-api.example.test",
      landingPath: "/",
      surface: "customer"
    });
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("location"), "https://portal.example.test/");
    const delivered = response.headers.getSetCookie();
    assert.equal(delivered.length, 2);
    assert.match(delivered[0], /^GEO_CUSTOMER_SESSION=/);
    assert.match(delivered[1], /^GEO_CSRF_TOKEN=/);
  });
  assert.match(calls[0].input, /\/preflight$/);
  assert.match(calls[1].input, /\/redeem$/);
  assert.match(calls[1].init.headers["Idempotency-Key"], /^geo-redeem-[a-f0-9]{64}$/);
});

test("logout proves CSRF and clears browser cookies when the API is unavailable", async () => {
  const calls = [];
  await withFetch(async (input, init) => {
    calls.push({ input: input.toString(), init });
    throw new Error("offline");
  }, async () => {
    const response = await logoutSession(
      new Request("https://portal.example.test/api/auth/logout", {
        method: "POST",
        headers: {
          Cookie: "GEO_CUSTOMER_SESSION=session-value; GEO_CSRF_TOKEN=csrf-value"
        }
      }),
      {
        apiBase: "https://customer-api.example.test",
        landingPath: "/",
        surface: "customer"
      }
    );
    assert.equal(response.status, 303);
    const cleared = response.headers.getSetCookie();
    assert.ok(cleared.some((cookie) => cookie.startsWith("GEO_CUSTOMER_SESSION=;")));
    assert.ok(cleared.some((cookie) => cookie.startsWith("GEO_CSRF_TOKEN=;")));
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.headers.Cookie.includes("GEO_CUSTOMER_SESSION"), true);
  assert.equal(calls[0].init.headers["X-GEO-CSRF-Token"], "csrf-value");
});

test("admin OIDC redirect fails closed and accepts only an allowlisted HTTPS origin", () => {
  assert.equal(
    adminOidcRedirect({ unavailableDetail: "OIDC unavailable" }).status,
    503
  );
  assert.throws(() => trustedOidcUrl(
    "http://identity.example.test/login",
    "http://identity.example.test"
  ));
  assert.throws(() => trustedOidcUrl(
    "https://evil.example.test/login",
    "https://identity.example.test"
  ));
  const response = adminOidcRedirect({
    targetUrl: "https://identity.example.test/oauth2/start?provider=geo",
    allowedOrigins: "https://identity.example.test",
    unavailableDetail: "OIDC unavailable"
  });
  assert.equal(response.status, 303);
  assert.equal(
    response.headers.get("location"),
    "https://identity.example.test/oauth2/start?provider=geo"
  );
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
});

function request(body) {
  return new Request("https://portal.example.test/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

async function withFetch(fetcher, operation) {
  const original = globalThis.fetch;
  globalThis.fetch = fetcher;
  try {
    await operation();
  } finally {
    globalThis.fetch = original;
  }
}
