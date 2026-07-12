#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from geno_core.auth import AuthContractError, AuthSessionV2Repository, InvitationSurface
from geno_core.auth_delivery import AuthDeliveryKeyring
from geno_core.repository import PostgresEvidenceRepository


def main() -> int:
    owner_url = os.getenv("AUTH_E2E_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not owner_url:
        owner_url = "postgresql://geno:geno@localhost:55433/geno"
    app_url = os.getenv(
        "AUTH_E2E_APP_DATABASE_URL",
        "postgresql://geno_runtime_app:geno_runtime_app@localhost:55433/geno",
    )
    keyring = AuthDeliveryKeyring.from_env()
    tenant_id = str(uuid4())
    project_id = str(uuid4())
    invitation_id = str(uuid4())
    actor_id = f"auth-e2e-{uuid4()}@example.com"
    invite_token = f"invite-{uuid4()}"
    idempotency_key = f"redeem-{uuid4()}"

    with psycopg.connect(owner_url, row_factory=dict_row) as owner, owner.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants(id, name, slug) VALUES (%s, 'Auth E2E', %s)",
            (tenant_id, f"auth-e2e-{tenant_id[:8]}"),
        )
        cursor.execute(
            """
            INSERT INTO projects(
              id, tenant_id, name, market_code, industry_code,
              target_brand, category, prompt_version, status
            )
            VALUES (%s, %s, 'Auth E2E', 'AU', 'auth_e2e', 'Auth E2E', 'Auth', 'auth-e2e-v1', 'active')
            """,
            (project_id, tenant_id),
        )
        cursor.execute(
            """
            INSERT INTO project_member_invitations(
              id, project_id, tenant_id, email, role, status, invite_token_hash,
              invited_by, expires_at, audience, allowed_surfaces, policy_version
            )
            VALUES (%s, %s, %s, %s, 'viewer', 'pending', %s,
                    'auth-e2e', %s, 'customer', ARRAY['customer'], 'auth_surface_policy_v1')
            """,
            (
                invitation_id,
                project_id,
                tenant_id,
                actor_id,
                hashlib.sha256(invite_token.encode("utf-8")).hexdigest(),
                datetime.now(UTC) + timedelta(hours=1),
            ),
        )

    with psycopg.connect(app_url, row_factory=dict_row) as app_connection:
        auth = AuthSessionV2Repository(app_connection, keyring=keyring, cookie_secure=False)
        try:
            auth.redeem(
                invitation_id=invitation_id,
                invite_token=invite_token,
                requested_surface=InvitationSurface.ADMIN,
                idempotency_key=f"mismatch-{uuid4()}",
            )
        except AuthContractError as exc:
            if exc.code != "invitation_surface_mismatch":
                raise
        else:
            raise RuntimeError("viewer invitation unexpectedly redeemed for admin")

        created = auth.redeem(
            invitation_id=invitation_id,
            invite_token=invite_token,
            requested_surface=InvitationSurface.CUSTOMER,
            idempotency_key=idempotency_key,
        )
        replayed = auth.redeem(
            invitation_id=invitation_id,
            invite_token=invite_token,
            requested_surface=InvitationSurface.CUSTOMER,
            idempotency_key=idempotency_key,
        )
        if created.cookie_delivery.cookie_headers != replayed.cookie_delivery.cookie_headers:
            raise RuntimeError("replayed Cookie delivery changed")
        raw_session_token = created.cookie_delivery.cookie_headers[0].split(";", 1)[0].split("=", 1)[1]
        session = PostgresEvidenceRepository(app_connection).validate_runtime_session(raw_session_token)
        if session.session.get("scope_version") != "runtime_session_scope_v2":
            raise RuntimeError("redeemed Session is not scope-v2")
        auth.confirm_delivery(
            session_id=str(session.session["id"]),
            actor_id=actor_id,
            tenant_id=tenant_id,
        )

    with psycopg.connect(owner_url, row_factory=dict_row) as owner, owner.cursor() as cursor:
        cursor.execute(
            """
            SELECT delivery_confirmed_at IS NOT NULL AS confirmed,
                   delivery_ciphertext IS NULL AS ciphertext_erased,
                   replay_count
            FROM auth_invitation_redemption_attempts WHERE id = %s
            """,
            (created.correlation_id,),
        )
        ledger = cursor.fetchone()
    if ledger != {"confirmed": True, "ciphertext_erased": True, "replay_count": 1}:
        raise RuntimeError(f"unexpected redemption ledger state: {ledger}")
    print(
        json.dumps(
            {
                "status": "passed",
                "tenant_id": tenant_id,
                "project_id": project_id,
                "invitation_id": invitation_id,
                "session_id": str(session.session["id"]),
                "redemption_attempt_id": created.correlation_id,
                "stable_replay": True,
                **ledger,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
