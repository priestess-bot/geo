from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from geno_api.auth_context import (
    AuthContextError,
    auth_context_scope,
    build_anonymous_auth_context,
    build_system_auth_context,
    build_user_auth_context,
    hash_context_value,
)
import geno_api.main as api_main
from geno_api.main import build_runtime_auth_context


class AuthContextContractsTest(unittest.TestCase):
    def test_user_auth_context_normalizes_actor_and_hashes_request_metadata(self) -> None:
        context = build_user_auth_context(
            actor_id="  analyst@example.com  ",
            auth_method="header",
            tenant_id=" tenant-1 ",
            project_ids=[" project-1 ", "", "project-2"],
            roles=[" owner ", "analyst"],
            permissions=["report.read", " report.download "],
            session_id=" session-1 ",
            request_id=" request-1 ",
            client_host="203.0.113.10",
            user_agent="Mozilla/5.0",
        )

        self.assertEqual(context.actor_id, "analyst@example.com")
        self.assertEqual(context.actor_type, "user")
        self.assertEqual(context.tenant_id, "tenant-1")
        self.assertEqual(context.project_ids, ("project-1", "project-2"))
        self.assertEqual(context.roles, ("owner", "analyst"))
        self.assertEqual(context.permissions, ("report.read", "report.download"))
        self.assertEqual(context.session_id, "session-1")
        self.assertEqual(context.request_id, "request-1")
        self.assertEqual(context.ip_hash, hash_context_value("203.0.113.10"))
        self.assertEqual(context.user_agent_hash, hash_context_value("Mozilla/5.0"))
        self.assertTrue(context.is_authenticated)
        self.assertFalse(context.is_system_actor)

    def test_user_auth_context_rejects_body_supplied_actor_shape(self) -> None:
        with self.assertRaisesRegex(AuthContextError, "actor_id is required"):
            build_user_auth_context(actor_id=" ", auth_method="header")

        with self.assertRaisesRegex(AuthContextError, "requires header, jwt, jwks, or session"):
            build_user_auth_context(actor_id="user-1", auth_method="system")  # type: ignore[arg-type]

    def test_system_auth_context_requires_service_name_and_reason(self) -> None:
        context = build_system_auth_context(
            service_name="collector-worker",
            reason="scheduled_collection",
            tenant_id="tenant-1",
            project_ids=["project-1"],
            roles=["system"],
            permissions=["collection.run"],
            request_id="request-1",
        )

        self.assertEqual(context.actor_id, "system:collector-worker")
        self.assertEqual(context.actor_type, "system")
        self.assertEqual(context.auth_method, "system")
        self.assertEqual(context.reason, "scheduled_collection")
        self.assertTrue(context.is_system_actor)
        self.assertEqual(auth_context_scope(context)["project_ids"], ("project-1",))

        with self.assertRaisesRegex(AuthContextError, "service_name is required"):
            build_system_auth_context(service_name=" ", reason="scheduled_collection")
        with self.assertRaisesRegex(AuthContextError, "reason is required"):
            build_system_auth_context(service_name="collector-worker", reason=" ")

    def test_anonymous_context_has_no_scope_or_actor(self) -> None:
        context = build_anonymous_auth_context(auth_method="header", request_id="request-1")

        self.assertIsNone(context.actor_id)
        self.assertEqual(context.actor_type, "anonymous")
        self.assertEqual(context.project_ids, ())
        self.assertFalse(context.is_authenticated)

    def test_runtime_auth_context_uses_header_actor_when_access_control_enabled(self) -> None:
        with patch.dict(os.environ, {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}, clear=False):
            context = build_runtime_auth_context(" analyst-1 ")

        self.assertEqual(context.actor_id, "analyst-1")
        self.assertEqual(context.actor_type, "user")
        self.assertEqual(context.auth_method, "header")

    def test_runtime_auth_context_rejects_missing_header_actor_when_access_control_enabled(self) -> None:
        with patch.dict(os.environ, {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1"}, clear=False):
            with self.assertRaises(HTTPException) as raised:
                build_runtime_auth_context(None)

        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn("X-GENO-Actor-Id", raised.exception.detail)

    def test_runtime_auth_context_allows_anonymous_when_access_control_disabled(self) -> None:
        with patch.dict(os.environ, {"GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "0"}, clear=False):
            context = build_runtime_auth_context(None)

        self.assertIsNone(context.actor_id)
        self.assertEqual(context.actor_type, "anonymous")
        self.assertEqual(context.auth_method, "header")

    def test_runtime_auth_context_uses_verified_jwt_actor(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GENO_RUNTIME_PROJECT_ACCESS_CONTROL": "1",
                "GENO_RUNTIME_AUTH_MODE": "jwt",
                "GENO_RUNTIME_JWT_SECRET": "test-runtime-secret",
            },
            clear=False,
        ):
            token = api_main._RUNTIME_JWT_ACTOR_ID.set("jwt-owner")
            try:
                context = build_runtime_auth_context(None)
            finally:
                api_main._RUNTIME_JWT_ACTOR_ID.reset(token)

        self.assertEqual(context.actor_id, "jwt-owner")
        self.assertEqual(context.auth_method, "jwt")


if __name__ == "__main__":
    unittest.main()
