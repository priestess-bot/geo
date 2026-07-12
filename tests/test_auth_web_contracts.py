from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "apps/admin-web/app"
CUSTOMER = ROOT / "apps/customer-web/app"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class AuthWebContractTests(unittest.TestCase):
    def test_admin_and_customer_auth_contracts_are_byte_identical(self) -> None:
        admin = (ADMIN / "_auth/contracts.ts").read_bytes()
        customer = (CUSTOMER / "_auth/contracts.ts").read_bytes()
        self.assertEqual(hashlib.sha256(admin).hexdigest(), hashlib.sha256(customer).hexdigest())
        self.assertEqual(admin, customer)

    def test_admin_and_customer_recovery_contracts_are_byte_identical(self) -> None:
        admin = (ADMIN / "_auth/recovery.ts").read_bytes()
        customer = (CUSTOMER / "_auth/recovery.ts").read_bytes()
        self.assertEqual(hashlib.sha256(admin).hexdigest(), hashlib.sha256(customer).hexdigest())
        self.assertEqual(admin, customer)

    def test_preflight_contract_is_nullable_and_discriminated(self) -> None:
        contract = source(ADMIN / "_auth/contracts.ts")
        self.assertIn('compatibility: "compatible"', contract)
        self.assertIn('compatibility: "surface_mismatch"', contract)
        self.assertIn('compatibility: "policy_stale"', contract)
        self.assertIn('compatibility: "invalid"', contract)
        self.assertIn("recommended_surface: null", contract)
        self.assertIn("invitation_role: CanonicalInvitationRole | null", contract)
        self.assertIn("candidate.recommended_surface === null", contract)
        self.assertIn("candidate.invitation_role === null", contract)

    def test_recovery_secret_sources_and_secure_cookie_boolean_fail_closed(self) -> None:
        recovery = source(ADMIN / "_auth/recovery.ts")
        self.assertIn("GENO_AUTH_RECOVERY_COOKIE_SECRET_FILE", recovery)
        self.assertIn("readFileSync(secretFile", recovery)
        self.assertIn("directSecret && secretFile", recovery)
        self.assertIn("must use exactly one source", recovery)
        self.assertIn('["1", "true", "yes", "on"]', recovery)
        self.assertIn('["0", "false", "no", "off"]', recovery)
        self.assertIn('process.env.NODE_ENV === "production"', recovery)
        self.assertIn("secure recovery cookies cannot be disabled in production", recovery)
        self.assertIn("must be a strict boolean", recovery)

    def test_recovery_configuration_behavior_matches_in_both_apps(self) -> None:
        node_script = r"""
const recovery = require(process.argv[1]);
const secretFile = process.argv[2];
function clear() {
  delete process.env.GENO_AUTH_RECOVERY_COOKIE_SECRET;
  delete process.env.GENO_AUTH_RECOVERY_COOKIE_SECRET_FILE;
  delete process.env.GENO_RUNTIME_SESSION_COOKIE_SECURE;
  process.env.NODE_ENV = "development";
}
function mustThrow(label, expected) {
  try {
    recovery.validateRecoveryConfiguration();
  } catch (error) {
    if (String(error).includes(expected)) return;
    throw new Error(`${label}: unexpected error ${String(error)}`);
  }
  throw new Error(`${label}: expected rejection`);
}
clear();
process.env.GENO_AUTH_RECOVERY_COOKIE_SECRET_FILE = secretFile;
process.env.GENO_RUNTIME_SESSION_COOKIE_SECURE = "true";
if (recovery.validateRecoveryConfiguration().secureCookies !== true) throw new Error("_FILE failed");
const adminRequest = { invitation_id: "invite-a", invite_token: "token-a", requested_surface: "admin" };
const adminFirst = recovery.createRedemptionRecovery(adminRequest, 1700000000000);
const adminSecond = recovery.createRedemptionRecovery(adminRequest, 1700000000000);
if (adminFirst.cookieValue === adminSecond.cookieValue) throw new Error("recovery encryption IV was reused");
if (adminFirst.payload.key !== adminSecond.payload.key) throw new Error("same request did not get stable key");
if (adminFirst.payload.phase !== "prepared") throw new Error("initial phase was not prepared");
const customerSameInput = recovery.createRedemptionRecovery(
  { ...adminRequest, requested_surface: "customer" },
  1700000000000
);
if (customerSameInput.payload.key === adminFirst.payload.key) throw new Error("surface did not bind key");
const differentToken = recovery.createRedemptionRecovery(
  { ...adminRequest, invite_token: "token-b" },
  1700000000000
);
if (differentToken.payload.key === adminFirst.payload.key) throw new Error("token did not bind key");
const differentId = recovery.createRedemptionRecovery(
  { ...adminRequest, invitation_id: "invite-b" },
  1700000000000
);
if (differentId.payload.key === adminFirst.payload.key) throw new Error("invitation id did not bind key");
if (adminFirst.payload.key.includes("token-a") || adminFirst.payload.key.includes("invite-a")) {
  throw new Error("idempotency key disclosed request input");
}
const delivered = recovery.markRedemptionRecoveryDelivered(adminFirst.payload, "session-new");
if (delivered.payload.phase !== "delivered") throw new Error("delivery phase was not frozen");
if (recovery.inspectSessionDeliveryRecovery(adminFirst.cookieValue, "admin", "session-old", 1700000000000).status !== "prepared") {
  throw new Error("prepared recovery accepted an old session");
}
if (recovery.inspectSessionDeliveryRecovery(delivered.cookieValue, "admin", "session-new", 1700000000000).status !== "delivered") {
  throw new Error("delivered recovery did not match its session");
}
if (recovery.inspectSessionDeliveryRecovery(delivered.cookieValue, "admin", "session-old", 1700000000000).status !== "session_mismatch") {
  throw new Error("delivered recovery accepted a different session");
}
if (recovery.safeRetryAfter("999999") !== "3600" || recovery.safeRetryAfter("date") !== undefined) {
  throw new Error("Retry-After sanitizer failed");
}
process.env.GENO_AUTH_RECOVERY_COOKIE_SECRET = "direct-secret-0123456789-0123456789";
mustThrow("dual source", "exactly one source");
clear();
process.env.GENO_AUTH_RECOVERY_COOKIE_SECRET = "direct-secret-0123456789-0123456789";
process.env.GENO_RUNTIME_SESSION_COOKIE_SECURE = "sometimes";
mustThrow("invalid boolean", "strict boolean");
process.env.GENO_RUNTIME_SESSION_COOKIE_SECURE = "false";
process.env.NODE_ENV = "production";
mustThrow("production insecure", "cannot be disabled in production");
delete process.env.GENO_RUNTIME_SESSION_COOKIE_SECURE;
if (recovery.validateRecoveryConfiguration().secureCookies !== true) throw new Error("production default failed");
"""
        with tempfile.TemporaryDirectory(prefix="auth-web-recovery-test-") as temp:
            temp_path = Path(temp)
            secret_file = temp_path / "recovery-secret"
            secret_file.write_text("file-secret-0123456789-0123456789-abcdef\n", encoding="utf-8")
            for app_name in ("admin-web", "customer-web"):
                app = ROOT / "apps" / app_name
                output = temp_path / app_name
                subprocess.run(
                    [
                        str(app / "node_modules/.bin/tsc"),
                        str(app / "app/_auth/recovery.ts"),
                        "--outDir",
                        str(output),
                        "--module",
                        "commonjs",
                        "--moduleResolution",
                        "node",
                        "--target",
                        "ES2022",
                        "--esModuleInterop",
                        "--skipLibCheck",
                    ],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["node", "-e", node_script, str(output / "recovery.js"), str(secret_file)],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )

    def test_counterpart_portal_urls_fail_closed_in_production(self) -> None:
        admin = (ADMIN / "_auth/portalUrl.ts").read_bytes()
        customer = (CUSTOMER / "_auth/portalUrl.ts").read_bytes()
        self.assertEqual(admin, customer)
        node_script = r"""
const portal = require(process.argv[1]);
function resolve(overrides = {}) {
  return portal.resolveCounterpartPortalUrl({
    configuredValue: "https://portal.example.test/",
    developmentFallback: "http://localhost:3000/",
    environmentName: "CUSTOMER_WEB_BASE_URL",
    nodeEnv: "production",
    ...overrides
  });
}
function mustThrow(label, expected, options) {
  try { resolve(options); } catch (error) {
    if (String(error).includes(expected)) return;
    throw new Error(`${label}: unexpected error ${String(error)}`);
  }
  throw new Error(`${label}: expected rejection`);
}
if (resolve() !== "https://portal.example.test/") throw new Error("production HTTPS failed");
mustThrow("missing production URL", "required in production", { configuredValue: undefined });
mustThrow("public production URL", "required in production", {
  configuredValue: undefined, publicDevelopmentValue: "https://public.example.test/"
});
mustThrow("production HTTP", "must use HTTPS", { configuredValue: "http://portal.example.test/" });
mustThrow("userinfo", "must not contain userinfo", { configuredValue: "https://user:pass@portal.example.test/" });
mustThrow("remote development HTTP", "must use HTTPS", {
  configuredValue: "http://portal.example.test/", nodeEnv: "development"
});
if (!resolve({ configuredValue: undefined, nodeEnv: "development" }).startsWith("http://localhost:3000/")) {
  throw new Error("local development fallback failed");
}
"""
        with tempfile.TemporaryDirectory(prefix="auth-web-portal-url-test-") as temp:
            temp_path = Path(temp)
            for app_name in ("admin-web", "customer-web"):
                app = ROOT / "apps" / app_name
                output = temp_path / app_name
                subprocess.run(
                    [
                        str(app / "node_modules/.bin/tsc"),
                        str(app / "app/_auth/portalUrl.ts"),
                        "--outDir",
                        str(output),
                        "--module",
                        "commonjs",
                        "--moduleResolution",
                        "node",
                        "--target",
                        "ES2022",
                        "--skipLibCheck",
                    ],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["node", "-e", node_script, str(output / "portalUrl.js")],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )

    def test_login_routes_require_bound_recovery_before_upstream_mutation(self) -> None:
        for app in (ADMIN, CUSTOMER):
            login = source(app / "api/auth/login/route.ts")
            recovery_read = login.index("readRedemptionRecovery(")
            upstream_redeem = login.index('new URL("/v1/auth/invitations/redeem"')
            self.assertLess(recovery_read, upstream_redeem)
            self.assertIn('code: "redeem_prepare_required"', login)
            self.assertIn('"Idempotency-Key": recovery.key', login)
            self.assertNotIn("accepted_by", login)
            self.assertNotIn("ADMIN_ROLES", login)
            self.assertNotIn("hasAdminRole", login)

    def test_prepare_reuses_matching_recovery_before_preflight(self) -> None:
        for app in (ADMIN, CUSTOMER):
            prepare = source(app / "api/auth/redeem-prepare/route.ts")
            recovery_read = prepare.index("readRedemptionRecovery(")
            preflight = prepare.index('new URL("/v1/auth/invitations/preflight"')
            self.assertLess(recovery_read, preflight)
            self.assertIn("if (existingRecovery)", prepare)

    def test_login_routes_forward_complete_delivery_and_use_fixed_303(self) -> None:
        admin = source(ADMIN / "api/auth/login/route.ts")
        customer = source(CUSTOMER / "api/auth/login/route.ts")
        for login in (admin, customer):
            self.assertIn("hasCompleteSessionDelivery(sessionCookies)", login)
            self.assertIn('response.headers.append("set-cookie", cookie)', login)
            self.assertLess(
                login.index("setRecoveryCookie(\n    response"),
                login.index('response.headers.append("set-cookie", cookie)')
            )
            self.assertIn("NextResponse.redirect", login)
            self.assertIn(", 303)", login)
        self.assertIn('const LANDING = "/projects"', admin)
        self.assertIn('const LANDING = "/"', customer)

    def test_session_confirmation_only_clears_recovery_after_auth_me_success(self) -> None:
        for app in (ADMIN, CUSTOMER):
            confirm = source(app / "api/auth/session-confirm/route.ts")
            self.assertIn('new URL("/v1/auth/me"', confirm)
            self.assertIn("if (!sessionToken || !csrfToken)", confirm)
            self.assertIn('code: "auth_session_delivery_invalid"', confirm)
            self.assertIn("isRuntimeAuthMeResponse(payload)", confirm)
            self.assertIn("inspectSessionDeliveryRecovery", confirm)
            self.assertIn('recovery.status === "prepared"', confirm)
            self.assertNotIn('request.headers.get("cookie")', confirm)
            self.assertIn("GENO_RUNTIME_SESSION=", confirm)
            self.assertIn("GENO_CSRF_TOKEN=", confirm)
            clear_index = confirm.index("clearRecoveryCookie(response")
            success_index = confirm.index("isRuntimeAuthMeResponse(payload)")
            self.assertGreater(clear_index, success_index)

    def test_project_lists_use_server_surface_projection(self) -> None:
        admin_list = source(ADMIN / "projects/page.tsx")
        admin_detail = source(ADMIN / "projects/[project_id]/page.tsx")
        customer_runtime = source(CUSTOMER / "runtime.ts")
        self.assertIn('surface: "admin"', admin_list)
        self.assertIn('surface: "admin"', admin_detail)
        self.assertIn('surface: "customer"', customer_runtime)
        self.assertIn("SURFACE_PROJECT_PAGE_SIZE = 200", customer_runtime)
        self.assertIn("MAX_AUTHORIZED_PROJECTS = 5000", customer_runtime)
        self.assertIn("while (expectedTotal === null || records.length < expectedTotal)", customer_runtime)
        self.assertIn("offset = records.length", customer_runtime)
        self.assertIn("expectedTotal !== totalCount", customer_runtime)
        self.assertIn("projectIds.has(recordProjectId)", customer_runtime)
        self.assertIn("PROJECT_PAGE_SIZE = 50", admin_list)
        self.assertIn('query.set("offset"', admin_list)
        self.assertIn('aria-label="项目分页"', admin_list)
        self.assertNotIn("project_ids?.filter", customer_runtime)
        self.assertIn("includeCsrfProof: false", customer_runtime)

    def test_raw_invitation_token_is_not_moved_to_url_or_browser_storage(self) -> None:
        paths = [
            ADMIN / "_auth/InvitationLoginForm.tsx",
            ADMIN / "api/auth/login/route.ts",
            ADMIN / "runtime.ts",
            CUSTOMER / "_auth/InvitationLoginForm.tsx",
            CUSTOMER / "api/auth/login/route.ts",
            CUSTOMER / "page.tsx",
        ]
        combined = "\n".join(source(path) for path in paths)
        self.assertNotIn('searchParams.set("invite_token"', combined)
        self.assertNotIn("localStorage", combined)
        self.assertNotIn("sessionStorage", combined)
        self.assertNotIn("params.invite_token", combined)
        self.assertIn("preparedBody", combined)
        for middleware in (
            ROOT / "apps/admin-web/middleware.ts",
            ROOT / "apps/customer-web/middleware.ts",
        ):
            middleware_source = source(middleware)
            self.assertIn("hasInvitationTokenKey", middleware_source)
            self.assertIn('Referrer-Policy", "no-referrer"', middleware_source)
            self.assertNotIn('get("invite_token")', middleware_source)

    def test_errors_preserve_code_detail_correlation_and_recommended_surface(self) -> None:
        contract = source(ADMIN / "_auth/contracts.ts")
        form = source(ADMIN / "_auth/InvitationLoginForm.tsx")
        for field in ("code", "detail", "correlation_id", "recommended_surface"):
            self.assertIn(field, contract)
        self.assertIn("error.correlation_id", form)
        self.assertIn("error?.recommended_surface", form)
        self.assertIn('url.searchParams.set("invitation_id"', form)
        self.assertIn('url.searchParams.delete("invite_token"', form)
        self.assertIn("auth_preflight_rate_limited", contract)
        for app in (ADMIN, CUSTOMER):
            for route in ("api/auth/redeem-prepare/route.ts", "api/auth/login/route.ts"):
                route_source = source(app / route)
                self.assertIn("safeRetryAfter", route_source)
                self.assertIn('"Retry-After"', route_source)

    def test_admin_project_detail_distinguishes_auth_and_resource_failures(self) -> None:
        detail = source(ADMIN / "projects/[project_id]/page.tsx")
        self.assertIn("ProjectLoadResult", detail)
        self.assertIn("projectResult.status === 401", detail)
        self.assertIn('redirect("/login")', detail)
        self.assertIn("projectResult.status === 403", detail)
        self.assertIn("projectResult.status === 404", detail)
        self.assertIn("项目服务暂时不可用", detail)

    def test_auth_me_validator_checks_nested_scope_and_exact_project_projection(self) -> None:
        contract = source(ADMIN / "_auth/contracts.ts")
        self.assertIn("isRuntimeProjectScope", contract)
        self.assertIn("candidate.roles.every(isCanonicalInvitationRole)", contract)
        self.assertIn("candidate.portal_capabilities.every(isPortalCapability)", contract)
        self.assertIn("candidate.scope_sources.every(isRuntimeScopeSource)", contract)
        self.assertIn("new Set(scopeIds).size === scopeIds.length", contract)
        self.assertIn("scopeIds.every((projectId) => projectIds.includes(projectId))", contract)


if __name__ == "__main__":
    unittest.main()
