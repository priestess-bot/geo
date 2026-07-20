from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "apps/admin-web"
CUSTOMER = ROOT / "apps/customer-web"
AUTH = ROOT / "packages/web/auth/src"
AUTH_TYPES = ROOT / "packages/web/types/src/auth.ts"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class AuthWebContractTests(unittest.TestCase):
    def test_shared_bff_behavior_against_mock_api(self) -> None:
        subprocess.run(
            [
                "node",
                "--test",
                "--experimental-strip-types",
                "--import",
                "./tests/register_typescript_resolver.mjs",
                "tests/auth_bff_contract.test.mjs",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_customer_portal_uses_the_shared_auth_bff(self) -> None:
        routes = {
            CUSTOMER / "app/api/auth/redeem-prepare/route.ts": "prepareInvitation",
            CUSTOMER / "app/api/auth/login/route.ts": "redeemInvitation",
            CUSTOMER / "app/api/auth/logout/route.ts": "logoutSession",
        }
        for path, handler in routes.items():
            route = source(path)
            self.assertIn(f'import {{ {handler} }} from "@geo/auth/bff"', route)
            self.assertNotIn("fetch(", route)
            self.assertLessEqual(len(route.splitlines()), 14)

    def test_admin_uses_fixed_oidc_redirect_not_customer_invitation(self) -> None:
        login = source(ADMIN / "app/api/auth/login/route.ts")
        page = source(ADMIN / "app/login/page.tsx")
        middleware = source(ADMIN / "middleware.ts")
        self.assertIn("adminOidcRedirect", login)
        self.assertIn("GEO_ADMIN_OIDC_LOGIN_URL", login)
        self.assertIn("GEO_ADMIN_OIDC_ALLOWED_ORIGINS", login)
        self.assertNotIn("redeemInvitation", login)
        self.assertNotIn("InvitationLoginForm", page)
        self.assertNotIn("invite_token", middleware)
        self.assertFalse((ADMIN / "app/api/auth/redeem-prepare/route.ts").exists())
        production_env = source(ROOT / "infra/production.env.example")
        runbook = source(ROOT / "docs/operations/production-runbook.md")
        self.assertIn("/oauth2/start", production_env)
        self.assertNotIn("GEO_ADMIN_OIDC_LOGIN_URL=https://identity.example.com", production_env)
        self.assertIn("Authorization Code +", runbook)
        self.assertIn("PKCE", runbook)

    def test_obsolete_recovery_delivery_flow_is_removed(self) -> None:
        obsolete = (
            "app/_auth/recovery.ts",
            "app/_auth/SessionDeliveryConfirm.tsx",
            "app/api/auth/session-confirm/route.ts",
        )
        for app in (ADMIN, CUSTOMER):
            for relative in obsolete:
                self.assertFalse((app / relative).exists(), relative)
        combined = "\n".join(
            source(path)
            for app in (ADMIN, CUSTOMER)
            for path in (app / "app/api/auth").glob("*/route.ts")
        )
        self.assertNotIn("GEO_AUTH_RECOVERY", combined)
        self.assertNotIn("SessionDelivery", combined)

    def test_preflight_is_discriminated_and_nullable(self) -> None:
        contract = source(AUTH_TYPES)
        for decision in ("compatible", "surface_mismatch", "invalid"):
            self.assertIn(f'compatibility: "{decision}"', contract)
        self.assertIn("recommended_surface: null", contract)
        self.assertIn("invitation_role: null", contract)
        self.assertIn("isInvitationPreflightResponse", contract)

    def test_shared_bff_preflights_before_consuming_invitation(self) -> None:
        bff = source(AUTH / "bff.ts")
        redeem = bff.index("export async function redeemInvitation")
        logout = bff.index("export async function logoutSession")
        section = bff[redeem:logout]
        self.assertLess(section.index("client.preflight(payload)"), section.index("client.redeem("))
        self.assertIn('preflightBody.compatibility !== "compatible"', section)
        self.assertIn("redeemIdempotencyKey(payload)", section)
        self.assertNotIn("invite_token", section.split('headers.set("Location"')[1])

    def test_bff_accepts_only_complete_cookie_delivery(self) -> None:
        bff = source(AUTH / "bff.ts")
        self.assertIn("validatedSessionCookies(redeemed.headers)", bff)
        self.assertIn('normalizedSession.includes("httponly")', bff)
        self.assertIn('normalizedSession.includes("samesite=lax")', bff)
        self.assertIn('normalizedCsrf.includes("httponly")', bff)
        self.assertIn('headers.append("Set-Cookie", expiredCookie(GEO_SESSION_COOKIE, true))', bff)
        self.assertIn("new AuthApiClient(options.apiBase).logout(cookie, csrf)", bff)

    def test_customer_forwards_cookie_auth_and_uses_stable_access_contracts(self) -> None:
        runtime = source(CUSTOMER / "app/runtime.ts")
        self.assertIn("Cookie:", runtime)
        self.assertIn("encodeURIComponent(sessionToken)", runtime)
        self.assertIn("new CustomerApiClient(apiBase()", runtime)
        self.assertIn("client.currentIdentity()", runtime)
        self.assertIn("client.listProjects(PROJECT_PAGE_SIZE, offset)", runtime)
        self.assertNotIn('/v1/projects/runtime", {\n      query', runtime)
        self.assertNotIn("X-GEO-Session-Token", runtime)
        self.assertNotIn("X-GEO-Actor-Id", runtime)
        self.assertNotIn("GEO_SESSION_HEADER", runtime)
        self.assertNotIn("GEO_ACTOR_HEADER", runtime)
        self.assertNotIn("GEO_RUNTIME_AUTH_MODE", runtime)

    def test_admin_invitation_ui_uses_stable_management_contract(self) -> None:
        create_project = source(ADMIN / "app/projects/new/actions.ts")
        invitation_sources = "\n".join(
            source(path)
            for path in (
                ADMIN / "app/projects/[project_id]/invitationActions.ts",
                ADMIN / "app/projects/[project_id]/invitationData.ts",
                ADMIN / "app/projects/[project_id]/InvitationManagementPanel.tsx",
            )
        )
        self.assertIn("/invitations`;", invitation_sources)
        self.assertIn("/revoke`", invitation_sources)
        self.assertIn("idempotencyKey", invitation_sources)
        self.assertNotIn("/v1/project-member-invitations/runtime", invitation_sources)
        self.assertNotIn("invitations", create_project)
        self.assertNotIn("create_customer_invitation", create_project)

    def test_admin_uses_oidc_bearer_or_explicit_development_identity(self) -> None:
        runtime = source(ADMIN / "app/runtime.ts")
        middleware = source(ADMIN / "middleware.ts")
        self.assertIn('(await headers()).get("authorization")', runtime)
        self.assertIn('process.env.GEO_AUTH_MODE === "development"', runtime)
        self.assertIn('"X-GEO-Tenant-ID"', runtime)
        self.assertNotIn("GEO_SESSION_COOKIE", runtime)
        self.assertNotIn("GEO_RUNTIME_AUTH_MODE", middleware)

    def test_raw_invitation_token_never_moves_to_url_or_browser_storage(self) -> None:
        paths = (
            CUSTOMER / "app/_auth/InvitationLoginForm.tsx",
            ADMIN / "middleware.ts",
            CUSTOMER / "middleware.ts",
        )
        combined = "\n".join(source(path) for path in paths)
        self.assertNotIn('searchParams.set("invite_token"', combined)
        self.assertNotIn("localStorage", combined)
        self.assertNotIn("sessionStorage", combined)
        customer_middleware = source(CUSTOMER / "middleware.ts")
        self.assertIn("hasInvitationTokenKey", customer_middleware)
        self.assertIn('Referrer-Policy", "no-referrer"', customer_middleware)
        self.assertNotIn('get("invite_token")', customer_middleware)
        self.assertNotIn("hasInvitationTokenKey", source(ADMIN / "middleware.ts"))


if __name__ == "__main__":
    unittest.main()
