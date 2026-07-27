#!/usr/bin/env python3
"""Encrypt Dify app keys and register all four GEO Workflow releases."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.project_scope import set_project_scope
from geo_core.secrets import SecretNotFound, SecretValue, SecretVersionHandle
from geo_core.secrets.postgres import build_secret_store_api
from geo_core.workflow_runtime import PostgresWorkflowRuntimeCatalog


SECRET_PURPOSE = "workflow_runtime.dify"


class EnrollmentError(RuntimeError):
    """A Dify-to-GEO enrollment failure with an operator action."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--prepared-by", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--state-file", type=Path, default=Path(".runtime/geo-dify-state.json"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("infra/dify/workflows/manifest.json")
    )
    parser.add_argument("--master-keyring-file", type=Path, required=True)
    parser.add_argument("--request-hash-key-file", type=Path, required=True)
    parser.add_argument("--database-url-env", default="GEO_DATABASE_URL")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        project_id = _uuid(args.project_id, "project")
        tenant_id = _uuid(args.tenant_id, "tenant")
        preparer_id = _uuid(args.prepared_by, "preparer")
        approver_id = _uuid(args.approved_by, "approver")
        if preparer_id == approver_id:
            raise EnrollmentError("preparer and approver must be distinct identities")
        database_url = _required_env(args.database_url_env)
        state_file = args.state_file.resolve()
        state = _private_state(state_file)
        manifest_path = args.manifest.resolve()
        manifest = _manifest(manifest_path)
        result = enroll_workflows(
            database_url=database_url,
            project_id=project_id,
            tenant_id=tenant_id,
            preparer_id=preparer_id,
            approver_id=approver_id,
            state=state,
            state_file=state_file,
            manifest=manifest,
            manifest_dir=manifest_path.parent,
            master_keyring_file=args.master_keyring_file.resolve(),
            request_hash_key_file=args.request_hash_key_file.resolve(),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (EnrollmentError, OSError, ValueError, psycopg.Error) as exc:
        print(f"Dify enrollment failed: {exc}", file=sys.stderr)
        return 1


def enroll_workflows(
    *,
    database_url: str,
    project_id: UUID,
    tenant_id: UUID,
    preparer_id: UUID,
    approver_id: UUID,
    state: dict[str, Any],
    state_file: Path,
    manifest: Mapping[str, Any],
    manifest_dir: Path,
    master_keyring_file: Path,
    request_hash_key_file: Path,
) -> Mapping[str, object]:
    preparer = _principal(preparer_id, project_id, tenant_id, "dify-enrollment-preparer")
    approver = _principal(approver_id, project_id, tenant_id, "dify-enrollment-approver")
    secret_api = build_secret_store_api(
        database_url=database_url,
        master_keyring_path=master_keyring_file,
        request_hash_key_path=request_hash_key_file,
    )
    if secret_api is None:
        raise EnrollmentError("Secret Store keyring configuration is unavailable")
    workflows = state.get("workflows")
    if not isinstance(workflows, dict):
        raise EnrollmentError("Dify state has no workflows object; run configure first")
    catalog = PostgresWorkflowRuntimeCatalog(database_url)
    registered: list[Mapping[str, str | int]] = []
    for manifest_item in _manifest_rows(manifest):
        purpose = manifest_item["purpose"]
        item = workflows.get(purpose)
        if not isinstance(item, dict):
            raise EnrollmentError(f"Dify state is missing configured Workflow {purpose}")
        token = _required_string(item.get("api_token"), f"{purpose} API token")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        handle = _active_secret(
            api=secret_api,
            project_id=project_id,
            purpose=purpose,
            token=token,
            token_hash=token_hash,
            enrollment=item.get("geo_secret"),
            preparer=preparer,
            approver=approver,
        )
        item["geo_secret"] = {
            "reference_id": str(handle.reference_id),
            "version": handle.version,
            "token_hash": token_hash,
        }
        _write_private_json(state_file, state)
        prompt_program_id, prompt_release_id = _current_prompt_binding(
            database_url=database_url, project_id=project_id, purpose=purpose
        )
        dsl_path = (manifest_dir / manifest_item["file"]).resolve()
        body = dsl_path.read_bytes()
        dsl_hash = hashlib.sha256(body).hexdigest()
        if dsl_hash != manifest_item["sha256"] or item.get("dsl_hash") != dsl_hash:
            raise EnrollmentError(f"{purpose} DSL identity differs between Git and Dify state")
        release_id = catalog.register_release(
            project_id=project_id,
            purpose=purpose,
            prompt_program_id=prompt_program_id,
            prompt_release_id=prompt_release_id,
            dify_app_id=_required_string(item.get("app_id"), f"{purpose} app ID"),
            dify_workflow_id=_required_string(
                item.get("workflow_id"), f"{purpose} Workflow ID"
            ),
            dsl_hash=dsl_hash,
            configured_model=_required_string(
                manifest_item.get("configured_model"), f"{purpose} model"
            ),
            model_provider=_required_string(
                manifest_item.get("model_provider"), f"{purpose} model provider"
            ),
            api_secret_handle=handle,
            created_by=preparer_id,
        )
        item["geo_release_id"] = str(release_id)
        _write_private_json(state_file, state)
        registered.append(
            {
                "purpose": purpose,
                "release_id": str(release_id),
                "secret_reference_id": str(handle.reference_id),
                "secret_version": handle.version,
            }
        )
    return {"status": "registered", "project_id": str(project_id), "items": registered}


def _active_secret(
    *,
    api: Any,
    project_id: UUID,
    purpose: str,
    token: str,
    token_hash: str,
    enrollment: object,
    preparer: AccessPrincipal,
    approver: AccessPrincipal,
) -> SecretVersionHandle:
    reference_id = uuid5(NAMESPACE_URL, f"geo:{project_id}:dify:{purpose}")
    try:
        reference = api.get_reference(
            preparer, project_id=project_id, reference_id=reference_id
        )
    except SecretNotFound:
        created = api.create(
            preparer,
            project_id=project_id,
            reference_id=reference_id,
            purpose=SECRET_PURPOSE,
            value=SecretValue(token),
            expected_version=0,
            idempotency_key=f"dify:{purpose}:secret:create:v1",
        )
        verified = api.verify(
            preparer,
            project_id=project_id,
            reference_id=reference_id,
            version=created.version,
            expected_version=created.aggregate_version,
            idempotency_key=f"dify:{purpose}:secret:verify:v1",
        )
        activated = api.activate(
            approver,
            project_id=project_id,
            reference_id=reference_id,
            version=created.version,
            expected_version=verified.aggregate_version,
            idempotency_key=f"dify:{purpose}:secret:activate:v1",
        )
        return SecretVersionHandle(
            reference_id=reference_id,
            project_id=project_id,
            purpose=SECRET_PURPOSE,
            version=activated.version,
        )
    if reference.purpose != SECRET_PURPOSE:
        raise EnrollmentError(f"{purpose} deterministic Secret reference has another purpose")
    recorded = enrollment if isinstance(enrollment, Mapping) else {}
    if (
        reference.status == "active"
        and recorded.get("reference_id") == str(reference_id)
        and recorded.get("version") == reference.current_version
        and recorded.get("token_hash") == token_hash
        and reference.current_version is not None
    ):
        return SecretVersionHandle(
            reference_id=reference_id,
            project_id=project_id,
            purpose=SECRET_PURPOSE,
            version=reference.current_version,
        )
    if reference.status == "pending":
        verified = api.verify(
            preparer,
            project_id=project_id,
            reference_id=reference_id,
            version=reference.latest_version,
            expected_version=reference.aggregate_version,
            idempotency_key=f"dify:{purpose}:secret:recovery:verify:v{reference.latest_version}",
        )
        activated = api.activate(
            approver,
            project_id=project_id,
            reference_id=reference_id,
            version=reference.latest_version,
            expected_version=verified.aggregate_version,
            idempotency_key=f"dify:{purpose}:secret:recovery:activate:v{reference.latest_version}",
        )
        return SecretVersionHandle(
            reference_id=reference_id,
            project_id=project_id,
            purpose=SECRET_PURPOSE,
            version=activated.version,
        )
    if reference.status != "active" or not recorded:
        raise EnrollmentError(
            f"{purpose} Secret already exists but cannot be matched to the local Dify state"
        )
    staged = api.stage_rotation(
        preparer,
        project_id=project_id,
        reference_id=reference_id,
        value=SecretValue(token),
        expected_version=reference.aggregate_version,
        idempotency_key=f"dify:{purpose}:secret:rotate:{token_hash}",
    )
    verified = api.verify(
        preparer,
        project_id=project_id,
        reference_id=reference_id,
        version=staged.version,
        expected_version=staged.aggregate_version,
        idempotency_key=f"dify:{purpose}:secret:rotate-verify:{token_hash}",
    )
    activated = api.activate(
        approver,
        project_id=project_id,
        reference_id=reference_id,
        version=staged.version,
        expected_version=verified.aggregate_version,
        idempotency_key=f"dify:{purpose}:secret:rotate-activate:{token_hash}",
    )
    return SecretVersionHandle(
        reference_id=reference_id,
        project_id=project_id,
        purpose=SECRET_PURPOSE,
        version=activated.version,
    )


def _current_prompt_binding(
    *, database_url: str, project_id: UUID, purpose: str
) -> tuple[UUID, UUID]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        set_project_scope(connection, project_id)
        row = connection.execute(
            """SELECT program_id, release_id
               FROM prompt_program_bindings
               WHERE project_id = %s AND purpose = %s
               ORDER BY binding_version DESC LIMIT 1""",
            (project_id, purpose),
        ).fetchone()
        connection.rollback()
    if row is None:
        raise EnrollmentError(
            f"{purpose} has no frozen Prompt binding; run and publish its fixed suite first"
        )
    return row["program_id"], row["release_id"]


def _principal(
    identity_id: UUID, project_id: UUID, tenant_id: UUID, auth_method: str
) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "owner"),),
        auth_method=auth_method,
    )


def _private_state(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise EnrollmentError(f"private Dify state file is missing: {path}")
    if path.stat().st_mode & 0o077:
        raise EnrollmentError(f"private Dify state file has unsafe permissions: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EnrollmentError("private Dify state must be a JSON object")
    return value


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    body = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise EnrollmentError("Dify manifest must be a JSON object")
    return value


def _manifest_rows(manifest: Mapping[str, Any]) -> tuple[Mapping[str, str], ...]:
    rows = manifest.get("workflows")
    if not isinstance(rows, list) or len(rows) != 4:
        raise EnrollmentError("Dify manifest must contain exactly four workflows")
    values: list[Mapping[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise EnrollmentError("Dify manifest Workflow entry is invalid")
        values.append({str(key): str(value) for key, value in row.items()})
    return tuple(values)


def _uuid(value: str, label: str) -> UUID:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError(f"{label} ID must be a UUID") from exc
    if parsed.int == 0:
        raise ValueError(f"{label} ID cannot be zero")
    return parsed


def _required_string(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise EnrollmentError(f"{label} is required")
    return result


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise EnrollmentError(f"{name} is required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
