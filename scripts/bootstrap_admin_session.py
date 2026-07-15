from __future__ import annotations

import argparse
import json
import os
import sys

from geo_core.models import RuntimeProjectSessionScope, RuntimeSessionInput
from geo_core.rbac import normalize_role, permissions_for_role, portal_capabilities_for_roles
from geo_core.repository import PostgresEvidenceRepository


def _database_url(value: str | None) -> str:
    url = (value or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise ValueError("DATABASE_URL or --database-url is required")
    return url


def _load_bootstrap_scope(
    connection: object,
    *,
    actor_id: str,
    tenant_id: str | None,
    project_ids: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[RuntimeProjectSessionScope, ...]]:
    normalized_actor = actor_id.strip().lower()
    requested_project_ids = tuple(dict.fromkeys(value.strip() for value in project_ids if value.strip()))
    with connection.cursor() as cursor:
        if requested_project_ids:
            cursor.execute(
                """
                SELECT id::text AS project_id, tenant_id::text AS tenant_id
                FROM projects
                WHERE id::text = ANY(%s) AND status <> 'archived'
                ORDER BY id
                """,
                (list(requested_project_ids),),
            )
            project_rows = list(cursor.fetchall() or ())
            found_project_ids = {str(row["project_id"]) for row in project_rows}
            missing_project_ids = sorted(set(requested_project_ids) - found_project_ids)
            if missing_project_ids:
                raise ValueError(f"unknown or archived project ids: {', '.join(missing_project_ids)}")
        else:
            cursor.execute(
                """
                SELECT DISTINCT project_row.id::text AS project_id,
                                project_row.tenant_id::text AS tenant_id
                FROM projects project_row
                LEFT JOIN project_members member_row
                  ON member_row.project_id = project_row.id
                 AND member_row.status = 'active'
                 AND lower(btrim(member_row.user_id)) = %s
                LEFT JOIN tenant_members tenant_member_row
                  ON tenant_member_row.tenant_id = project_row.tenant_id
                 AND tenant_member_row.status = 'active'
                 AND lower(btrim(tenant_member_row.user_id)) = %s
                 AND lower(btrim(tenant_member_row.role)) IN ('super_admin', 'tenant_admin')
                WHERE project_row.status <> 'archived'
                  AND (%s IS NULL OR project_row.tenant_id::text = %s)
                  AND (
                    member_row.id IS NOT NULL
                    OR tenant_member_row.id IS NOT NULL
                    OR %s IS NOT NULL
                  )
                ORDER BY project_row.id
                """,
                (normalized_actor, normalized_actor, tenant_id, tenant_id, tenant_id),
            )
            project_rows = list(cursor.fetchall() or ())

        tenant_ids = {str(row["tenant_id"]) for row in project_rows if row.get("tenant_id")}
        if tenant_id:
            tenant_ids.add(tenant_id.strip())
        if len(tenant_ids) > 1:
            raise ValueError("bootstrap session projects must belong to exactly one tenant")
        resolved_tenant_id = next(iter(tenant_ids), "")
        if not resolved_tenant_id:
            cursor.execute(
                """
                SELECT tenant_id::text AS tenant_id
                FROM tenant_members
                WHERE lower(btrim(user_id)) = %s
                  AND status = 'active'
                  AND lower(btrim(role)) IN ('super_admin', 'tenant_admin')
                ORDER BY updated_at DESC, created_at DESC, tenant_id
                LIMIT 1
                """,
                (normalized_actor,),
            )
            tenant_row = cursor.fetchone()
            if tenant_row:
                resolved_tenant_id = str(tenant_row["tenant_id"])
        if not resolved_tenant_id:
            raise ValueError("--tenant-id or at least one resolvable project is required for Session v2 bootstrap")

        cursor.execute(
            """
            SELECT role
            FROM tenant_members
            WHERE tenant_id::text = %s
              AND lower(btrim(user_id)) = %s
              AND status = 'active'
            ORDER BY role
            """,
            (resolved_tenant_id, normalized_actor),
        )
        tenant_roles = tuple(
            dict.fromkeys(normalize_role(str(row["role"])) for row in (cursor.fetchall() or ()) if row.get("role"))
        )
        project_ids_for_lookup = [str(row["project_id"]) for row in project_rows]
        project_member_roles: dict[str, str] = {}
        if project_ids_for_lookup:
            cursor.execute(
                """
                SELECT project_id::text AS project_id, role
                FROM project_members
                WHERE project_id::text = ANY(%s)
                  AND lower(btrim(user_id)) = %s
                  AND status = 'active'
                ORDER BY project_id, updated_at DESC, created_at DESC
                """,
                (project_ids_for_lookup, normalized_actor),
            )
            for row in cursor.fetchall() or ():
                project_member_roles.setdefault(str(row["project_id"]), normalize_role(str(row["role"])))

    scopes: list[RuntimeProjectSessionScope] = []
    for row in project_rows:
        project_id = str(row["project_id"])
        role = project_member_roles.get(project_id, "project_owner")
        role_tuple = (role,)
        scopes.append(
            RuntimeProjectSessionScope(
                project_id=project_id,
                roles=role_tuple,
                permissions=tuple(sorted(permissions_for_role(role))),
                portal_capabilities=tuple(sorted(portal_capabilities_for_roles(role_tuple))),
                scope_sources=("direct_member" if project_id in project_member_roles else "tenant_role",),
            )
        )
    return resolved_tenant_id, tenant_roles, tuple(scopes)


def bootstrap_admin_session(
    *,
    database_url: str,
    actor_id: str,
    tenant_id: str | None,
    project_ids: tuple[str, ...],
) -> dict[str, object]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required; run this command in the API container") from exc

    normalized_actor = actor_id.strip().lower()
    if not normalized_actor or "@" not in normalized_actor:
        raise ValueError("--actor-id must be an administrator email address")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        resolved_tenant_id, tenant_roles, project_scopes = _load_bootstrap_scope(
            connection,
            actor_id=normalized_actor,
            tenant_id=tenant_id.strip() if tenant_id else None,
            project_ids=project_ids,
        )
        roles = tuple(
            dict.fromkeys(
                (
                    *tenant_roles,
                    *(role for scope in project_scopes for role in scope.roles),
                )
            )
        )
        permissions = tuple(
            sorted({permission for scope in project_scopes for permission in scope.permissions})
        )
        repository = PostgresEvidenceRepository(connection)
        repository.set_runtime_project_access_context(
            actor_id=normalized_actor,
            project_id=project_scopes[0].project_id if project_scopes else None,
        )
        session = repository.create_runtime_session(
            RuntimeSessionInput(
                actor_id=normalized_actor,
                tenant_id=resolved_tenant_id,
                project_ids=tuple(scope.project_id for scope in project_scopes),
                roles=roles,
                permissions=permissions,
                tenant_roles=tenant_roles,
                project_scopes=project_scopes,
                scope_version="runtime_session_scope_v2",
                authz_policy_version="auth_surface_policy_v1",
                ttl_seconds=7 * 24 * 60 * 60,
                issued_by="bootstrap_admin_session_cli",
                metadata={"source": "bootstrap_admin_session_cli"},
                reason="initial_admin_session_bootstrap",
            )
        )
    if not session.raw_session_token:
        raise RuntimeError("bootstrap session token was not generated")
    return {
        "status": "pass",
        "actor_id": normalized_actor,
        "tenant_id": resolved_tenant_id,
        "project_ids": [scope.project_id for scope in project_scopes],
        "scope_version": "runtime_session_scope_v2",
        "expires_at": session.session.get("expires_at"),
        "session_token": session.raw_session_token,
        "notice": "This raw session token is shown once. Enter it on the Admin Web login page and then discard it.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first Admin Web server-side session.")
    parser.add_argument("--database-url")
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--tenant-id")
    parser.add_argument("--project-id", action="append", default=[])
    args = parser.parse_args()
    try:
        payload = bootstrap_admin_session(
            database_url=_database_url(args.database_url),
            actor_id=args.actor_id,
            tenant_id=args.tenant_id,
            project_ids=tuple(dict.fromkeys(value.strip() for value in args.project_id if value.strip())),
        )
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
