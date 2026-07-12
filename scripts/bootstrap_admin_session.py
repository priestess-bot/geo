from __future__ import annotations

import argparse
import json
import os
import sys

from geno_core.models import RuntimeSessionInput
from geno_core.rbac import permissions_for_role
from geno_core.repository import PostgresEvidenceRepository


def _database_url(value: str | None) -> str:
    url = (value or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise ValueError("DATABASE_URL or --database-url is required")
    return url


def bootstrap_admin_session(*, database_url: str, actor_id: str, project_ids: tuple[str, ...]) -> dict[str, object]:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required; run this command in the API container") from exc

    normalized_actor = actor_id.strip().lower()
    if not normalized_actor or "@" not in normalized_actor:
        raise ValueError("--actor-id must be an administrator email address")
    roles = ("super_admin", "admin", "owner")
    with psycopg.connect(database_url) as connection:
        repository = PostgresEvidenceRepository(connection)
        repository.set_runtime_project_access_context(
            actor_id=normalized_actor,
            project_id=project_ids[0] if project_ids else None,
        )
        session = repository.create_runtime_session(
            RuntimeSessionInput(
                actor_id=normalized_actor,
                project_ids=project_ids,
                roles=roles,
                permissions=tuple(sorted(permissions_for_role("super_admin"))),
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
        "project_ids": list(project_ids),
        "expires_at": session.session.get("expires_at"),
        "session_token": session.raw_session_token,
        "notice": "This raw session token is shown once. Enter it on the Admin Web login page and then discard it.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first Admin Web server-side session.")
    parser.add_argument("--database-url")
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--project-id", action="append", default=[])
    args = parser.parse_args()
    try:
        payload = bootstrap_admin_session(
            database_url=_database_url(args.database_url),
            actor_id=args.actor_id,
            project_ids=tuple(dict.fromkeys(value.strip() for value in args.project_id if value.strip())),
        )
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
