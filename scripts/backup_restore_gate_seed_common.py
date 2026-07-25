"""Shared identities, keyrings, and database setup for restore Gate seeding."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg

from geo_core.access.models import AccessPrincipal, MembershipRecord
from scripts.backup_envelope import atomic_write, canonical_json


ROOT = Path(__file__).resolve().parents[1]
KEYRING_FILES = {
    "provider": "provider-artifact-keyring.json",
    "recommendation": "recommendation-artifact-keyring.json",
    "request_hash": "secret-request-hash-key",
    "secret_full": "secret-store-keyring.json",
    "secret_v1": "secret-store-keyring-v1.json",
    "synthetic": "synthetic-artifact-keyring.json",
    "workflow_c": "workflow-c-artifact-keyring.json",
}
SECRET_MARKERS = (
    "RESTORE-GATE-SECRET-V1-DO-NOT-PERSIST-4171",
    "RESTORE-GATE-SECRET-V2-DO-NOT-PERSIST-6283",
    "RESTORE-GATE-PROVIDER-SECRET-DO-NOT-PERSIST-9347",
)


class RestoreGateSeedError(RuntimeError):
    """The isolated Gate fixture could not be prepared safely."""


@dataclass(frozen=True)
class GateSeedIds:
    tenant: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:tenant")
    project: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:project")
    owner: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:owner")
    reviewer: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:reviewer")
    restore_probe_service: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:restore-probe-service")
    owner_membership: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:owner-membership")
    reviewer_membership: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:reviewer-membership")
    secret_v1: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:secret-v1")
    secret_v2: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:secret-v2")
    provider_secret: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:provider-secret")
    prompt_test_set: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:prompt-test-set")
    recommendation_prompt_test_set: UUID = uuid5(
        NAMESPACE_URL, "geo-restore-gate:recommendation-prompt-test-set"
    )
    policy: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:model-policy")
    runtime_manifest: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:runtime-manifest")
    provider_job: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:provider-job")
    provider_lease: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:provider-lease")
    recommendation_parent_job: UUID = uuid5(
        NAMESPACE_URL, "geo-restore-gate:recommendation-parent-job"
    )
    recommendation_parent_lease: UUID = uuid5(
        NAMESPACE_URL, "geo-restore-gate:recommendation-parent-lease"
    )
    recommendation_child_job: UUID = uuid5(
        NAMESPACE_URL, "geo-restore-gate:recommendation-child-job"
    )
    synthetic_job: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:synthetic-job")
    synthetic_restricted: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:synthetic-restricted")
    synthetic_tier: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:synthetic-tier")
    workflow_c_policy: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:workflow-c-policy")
    workflow_c_suite: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:workflow-c-suite")
    workflow_c_run: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:workflow-c-run")
    workflow_c_task: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:workflow-c-task")
    workflow_c_artifact: UUID = uuid5(NAMESPACE_URL, "geo-restore-gate:workflow-c-artifact")
    workflow_c_capture_session: UUID = uuid5(
        NAMESPACE_URL, "geo-restore-gate:workflow-c-capture-session"
    )


IDS = GateSeedIds()


def current_head() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RestoreGateSeedError("restore Gate requires exactly one Alembic head")
    return heads[0]


def create_keyrings(directory: Path) -> None:
    require_secure_directory(directory)
    material = [os.urandom(32) for _ in range(11)]
    if len(set(material)) != len(material):
        raise RestoreGateSeedError("restore Gate key domains are not independent")
    (
        secret_v1,
        secret_v2,
        provider_v1,
        provider_v2,
        recommendation_v1,
        recommendation_v2,
        synthetic_v1,
        synthetic_v2,
        workflow_c_v1,
        workflow_c_v2,
        request,
    ) = material
    _write_json(
        directory / KEYRING_FILES["secret_v1"],
        _application_keyring({1: secret_v1}, active_version=1),
    )
    _write_json(
        directory / KEYRING_FILES["secret_full"],
        _application_keyring({1: secret_v1, 2: secret_v2}, active_version=2),
    )
    _write_json(
        directory / KEYRING_FILES["provider"],
        _application_keyring({1: provider_v1, 2: provider_v2}, active_version=2),
    )
    _write_json(
        directory / KEYRING_FILES["recommendation"],
        _application_keyring({1: recommendation_v1, 2: recommendation_v2}, active_version=2),
    )
    _write_json(
        directory / KEYRING_FILES["synthetic"],
        {
            "active_version": "2",
            "keys": {"1": _b64(synthetic_v1), "2": _b64(synthetic_v2)},
            "schema_version": 1,
        },
    )
    _write_json(
        directory / KEYRING_FILES["workflow_c"],
        _application_keyring({1: workflow_c_v1, 2: workflow_c_v2}, active_version=2),
    )
    atomic_write(
        directory / KEYRING_FILES["request_hash"],
        _b64(request).encode("ascii"),
    )


def migrate(database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["geo_database_url_override"] = database_url
    alembic_command.upgrade(config, "head")


def seed_project(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "INSERT INTO tenants(id, name) VALUES (%s, 'Authenticated restore Gate')",
            (IDS.tenant,),
        )
        service = connection.execute(
            "SELECT geo_provision_service_identity(%s, %s, %s)",
            (IDS.restore_probe_service, "restore_probe", datetime.now(UTC)),
        ).fetchone()
        if service is None or service[0] != IDS.restore_probe_service:
            raise RestoreGateSeedError("restore probe service identity was not provisioned")
        connection.execute(
            """INSERT INTO identities(id, issuer, subject, display_name)
               VALUES (%s, 'restore-gate', %s, %s),
                      (%s, 'restore-gate', %s, %s)""",
            (
                IDS.owner,
                "owner",
                "Restore Gate owner",
                IDS.reviewer,
                "reviewer",
                "Restore Gate reviewer",
            ),
        )
        connection.execute(
            """INSERT INTO projects(id, tenant_id, name)
               VALUES (%s, %s, 'Authenticated restore Gate')""",
            (IDS.project, IDS.tenant),
        )
        connection.execute(
            """INSERT INTO project_memberships(
                   id, tenant_id, project_id, identity_id, role
               ) VALUES (%s, %s, %s, %s, %s),
                        (%s, %s, %s, %s, %s)""",
            (
                IDS.owner_membership,
                IDS.tenant,
                IDS.project,
                IDS.owner,
                "owner",
                IDS.reviewer_membership,
                IDS.tenant,
                IDS.project,
                IDS.reviewer,
                "admin",
            ),
        )


def principal(identity_id: UUID) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=IDS.tenant,
        memberships=(MembershipRecord(IDS.project, IDS.tenant, "admin"),),
        auth_method="restore_gate",
    )


def require_secure_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise RestoreGateSeedError("keyring directory is unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or path.is_symlink()
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.geteuid()
    ):
        raise RestoreGateSeedError("keyring directory security is invalid")


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _application_keyring(keys: dict[int, bytes], *, active_version: int) -> object:
    return {
        "active_version": active_version,
        "format": "geo-master-keyring-v1",
        "keys": {str(version): _b64(value) for version, value in sorted(keys.items())},
    }


def _write_json(path: Path, value: object) -> None:
    atomic_write(path, canonical_json(value) + b"\n")


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


__all__ = [
    "create_keyrings",
    "current_head",
    "IDS",
    "KEYRING_FILES",
    "migrate",
    "principal",
    "require_secure_directory",
    "RestoreGateSeedError",
    "SECRET_MARKERS",
    "seed_project",
    "stable_hash",
]
