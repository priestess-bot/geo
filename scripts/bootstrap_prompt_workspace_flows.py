#!/usr/bin/env python3
"""Add the four independently contracted Prompt flows to an existing Project.

Fresh Projects receive these drafts through the normal Prompt bootstrap catalog.
This command only fills the four new purposes for an already-initialised Project;
it never replaces a Release, changes a binding or invokes a model provider.
"""

from __future__ import annotations

import argparse
import json
import os
from uuid import UUID

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.prompts.bootstrap_catalog import default_prompt_bootstrap_specs
from geo_core.prompts.postgres import build_prompt_program_api
from geo_core.prompts.program import ProgramKind


WORKSPACE_FLOW_KINDS = frozenset(
    {
        ProgramKind.QUESTION_GENERATION,
        ProgramKind.RAG_GROUNDING,
        ProgramKind.PLACEMENT_GENERATION,
        ProgramKind.PLACEMENT_SIMULATION,
    }
)


def main() -> int:
    args = _arguments()
    project_id = _uuid(args.project_id, "project")
    tenant_id = _uuid(args.tenant_id, "tenant")
    owner_id = _uuid(args.owner_id, "owner")
    database_url = _required(os.getenv(args.database_url_env), args.database_url_env)
    principal = AccessPrincipal(
        identity_id=owner_id,
        actor_id=str(owner_id),
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "owner"),),
        auth_method="operator-workspace-flow-bootstrap",
    )
    api = build_prompt_program_api(database_url=database_url)
    existing = {
        item.purpose
        for item in api.list_programs(
            principal, project_id=project_id, limit=200, offset=0
        ).items
    }
    created: list[str] = []
    already_present: list[str] = []
    for spec in default_prompt_bootstrap_specs():
        if spec.program_kind not in WORKSPACE_FLOW_KINDS:
            continue
        if spec.purpose in existing:
            already_present.append(spec.purpose)
            continue
        api.create_program(
            principal,
            project_id=project_id,
            program_kind=spec.program_kind,
            purpose=spec.purpose,
            system_template=spec.system_template,
            user_template=spec.user_template,
            schemas=spec.schemas,
            model_policy=spec.model_policy,
            test_set_id=spec.test_set_id,
            test_set_version=1,
            test_set_hash=spec.test_set_hash,
            compiler_version=spec.compiler_version,
            expected_version=0,
            idempotency_key=(
                f"prompt-workspace-flow-bootstrap:v1:{project_id}:{spec.purpose}"
            ),
        )
        created.append(spec.purpose)
    print(
        json.dumps(
            {
                "project_id": str(project_id),
                "created": created,
                "already_present": already_present,
            },
            sort_keys=True,
        )
    )
    return 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--database-url-env", default="GEO_DATABASE_URL")
    return parser.parse_args()


def _uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise SystemExit(f"--{label}-id must be a UUID") from exc


def _required(value: str | None, name: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise SystemExit(f"{name} is required")
    return normalized


if __name__ == "__main__":
    raise SystemExit(main())
