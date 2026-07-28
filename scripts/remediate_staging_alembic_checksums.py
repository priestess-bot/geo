"""Repair the one reviewed staging Alembic checksum-ledger drift, once.

The command is read-only unless ``--apply`` is present.  Apply consumes an exact
dry-run receipt, an authenticated committed backup and a matching isolated
restore receipt.  A pending receipt is durably reserved before database work so
an unknown commit can be reconciled without issuing the three-row update twice.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.db.alembic.checksums import sql_hashes  # noqa: E402
from scripts.backup_envelope import (  # noqa: E402
    BackupSecurityError,
    canonical_json,
    load_backup_keyring,
    read_canonical_json,
)
from scripts.backup_manifest import MANIFEST_SCHEMA, verify_backup_set  # noqa: E402
from scripts.write_backup_restore_receipt import (  # noqa: E402
    validate_restore_receipt,
)


SQL_DIRECTORY = ROOT / "infra/db/alembic/sql"
TARGET_REVISION = "0095_synthetic_dify_closed_loop"
REMEDIATED_REVISIONS = (
    "0093_dify_workflow_runtime",
    "0094_dify_published_snapshot",
    TARGET_REVISION,
)
EXPECTED_DATABASE_NAME = "geo"
EXPECTED_DATABASE_USER = "geo_installer"
EXPECTED_ENVIRONMENT = "staging"
RECEIPT_SCHEMA = "geo-staging-alembic-checksum-remediation-v2"
DATABASE_LEDGER_SCHEMA = "geo-database-alembic-checksum-ledger-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SYSTEM_IDENTIFIER = re.compile(r"^[0-9]{1,20}$")


@dataclass(frozen=True)
class HashPair:
    upgrade: str
    downgrade: str


# Exact source values observed in the one affected staging deployment.
OLD_HASH_ALLOWLIST: Mapping[str, HashPair] = {
    "0093_dify_workflow_runtime": HashPair(
        upgrade="76b6909d3a86f4d0aa119a8b8b457683f94cb6c5f6177900b3c1acea1a09e240",
        downgrade="8e54b465e9fe650b9659d3757d07f43e6b1de4a42fbf2671d71d6f3afb2759f1",
    ),
    "0094_dify_published_snapshot": HashPair(
        upgrade="73af1323adcfdf5c86b1316f4318dea7b97e426087c65c99821d4865c3482abf",
        downgrade="cfa648fc410336d5ca30c08b565c55769e3371259b0f747fb69239892b538b94",
    ),
    TARGET_REVISION: HashPair(
        upgrade="e089ab8e7774819374084df640133b2e28c9382030f4f5683c56b0ef25ff7d7a",
        downgrade="1e6f4eaf97e8cbbb2eb9f520af5a2061b8bce4d3b2684ddbd3f4cb6cc30c7f16",
    ),
}

# Exact reviewed destination values.  A later legitimate migration edit must
# update this allowlist through review; this tool never blesses an arbitrary
# dirty working tree.
DESTINATION_HASH_ALLOWLIST: Mapping[str, HashPair] = {
    "0093_dify_workflow_runtime": HashPair(
        upgrade="ebe3a49d8a501c7de910c948a25cb69fdc27b6375e5322bd381f0532fe92d8b0",
        downgrade="8e54b465e9fe650b9659d3757d07f43e6b1de4a42fbf2671d71d6f3afb2759f1",
    ),
    "0094_dify_published_snapshot": HashPair(
        upgrade="34527cfcec467e20216bfafef14b9de607d05894ccc83f81735cfcfd9eb55899",
        downgrade="c5c650655040a1707f05149ed11ff8d9e69f1610f05a4875b31384ff2d3943b6",
    ),
    TARGET_REVISION: HashPair(
        upgrade="d545736f445ef00fd431ea29b0bdf838626c14c60e4803a015dd917af9194924",
        downgrade="3ded719602ecf427ff7992ff82bbe76b193ad2c22263ef9d674e903f9e6680c0",
    ),
}

SOURCE_FILES = tuple(
    sorted(
        [
            f"infra/db/alembic/sql/{revision}.sql"
            for revision in REMEDIATED_REVISIONS
        ]
        + [
            f"infra/db/alembic/sql/{revision}.down.sql"
            for revision in REMEDIATED_REVISIONS
        ]
        + [
            f"infra/db/alembic/versions/{revision}.py"
            for revision in REMEDIATED_REVISIONS
        ]
        + ["infra/db/alembic/checksums.py"]
    )
)

TARGET_RELATIONS = (
    "dify_workflow_bindings",
    "dify_workflow_execution_attempts",
    "dify_workflow_execution_results",
    "dify_workflow_published_snapshots",
    "dify_workflow_releases",
    "synthetic_lab_model_call_child_status",
)
TARGET_FUNCTIONS = (
    "geo_assert_dify_attempt_transition",
    "geo_assert_dify_binding_append",
    "geo_assert_dify_result_insert",
    "geo_assert_synthetic_model_call_child_job_change",
    "geo_reject_dify_attempt_delete",
    "geo_reject_dify_runtime_mutation",
    "geo_reject_dify_snapshot_mutation",
)
RUNTIME_ROLES = ("geo_app", "geo_readonly", "geo_worker")

# Filled from a clean pgvector/pg16 database upgraded to canonical 0095 and
# independently compared with the target's read-only probe.
EXPECTED_SCHEMA_FINGERPRINT_SHA256 = (
    "78500c5709b0871b47300777f1cce41e36823574c12bc15344b64ccd598f3bb2"
)


class ChecksumRemediationError(RuntimeError):
    """The checksum repair is not safe to execute."""


@dataclass(frozen=True)
class TargetScope:
    environment: str
    database_name: str
    database_user: str
    system_identifier: str
    project_ids: tuple[str, ...]

    @property
    def public_identity(self) -> dict[str, object]:
        return {
            "database_name": self.database_name,
            "database_user": self.database_user,
            "environment": self.environment,
            "project_ids": list(self.project_ids),
            "system_identifier_sha256": hashlib.sha256(
                self.system_identifier.encode("ascii")
            ).hexdigest(),
        }


@dataclass(frozen=True)
class DatabaseIdentity:
    database_name: str
    database_user: str
    system_identifier: str
    project_ids: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class DatabaseSnapshot:
    identity: DatabaseIdentity
    heads: tuple[str, ...]
    ledger: Mapping[str, HashPair]
    schema: Mapping[str, object]


@dataclass(frozen=True)
class SourceState:
    files: tuple[tuple[str, str], ...]
    files_sha256: str
    canonical_ledger_sha256: str

    def as_receipt(self) -> dict[str, object]:
        return {
            "canonical_ledger_sha256": self.canonical_ledger_sha256,
            "files": [
                {"path": path, "sha256": digest} for path, digest in self.files
            ],
            "files_sha256": self.files_sha256,
        }


@dataclass(frozen=True)
class BackupEvidence:
    backup_id: str
    committed_sha256: str
    manifest_sha256: str
    restore_receipt_sha256: str
    repository_ledger_sha256: str
    database_ledger: Mapping[str, HashPair]
    database_ledger_sha256: str
    scope: TargetScope

    def as_receipt(self) -> dict[str, object]:
        return {
            "backup_id": self.backup_id,
            "committed_sha256": self.committed_sha256,
            "database_ledger_sha256": self.database_ledger_sha256,
            "manifest_sha256": self.manifest_sha256,
            "repository_ledger_sha256": self.repository_ledger_sha256,
            "restore_receipt_sha256": self.restore_receipt_sha256,
        }


@dataclass(frozen=True)
class ReceiptReservation:
    path: Path
    intent: Mapping[str, object]
    resumed: bool

    def finalize(self, receipt: Mapping[str, object]) -> None:
        parent = self.path.parent
        temporary = parent / f".{self.path.name}.{os.getpid()}.committed"
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as output:
                descriptor = None
                output.write(canonical_json(receipt) + b"\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            _fsync_directory(parent)
        except OSError as error:
            if descriptor is not None:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise ChecksumRemediationError(
                "committed receipt could not be finalized; the pending receipt was retained"
            ) from error


def repository_hashes(
    *, root: Path = ROOT, sql_directory: Path = SQL_DIRECTORY
) -> dict[str, HashPair]:
    configuration = Config(str(root / "alembic.ini"))
    configuration.set_main_option("script_location", str(root / "infra/db/alembic"))
    script = ScriptDirectory.from_config(configuration)
    revision_id: str | None = TARGET_REVISION
    revisions: list[str] = []
    while revision_id is not None:
        cursor = script.get_revision(revision_id)
        if cursor is None:
            raise ChecksumRemediationError(
                "target Alembic lineage references an absent revision"
            )
        revisions.append(cursor.revision)
        parents = tuple(value for value in cursor._normalized_down_revisions if value)
        if len(parents) > 1:
            raise ChecksumRemediationError("target Alembic lineage is not linear")
        revision_id = parents[0] if parents else None
    result: dict[str, HashPair] = {}
    for revision in reversed(revisions):
        upgrade, downgrade = sql_hashes(sql_directory, revision)
        result[revision] = HashPair(upgrade=upgrade, downgrade=downgrade)
    if any(revision not in result for revision in REMEDIATED_REVISIONS):
        raise ChecksumRemediationError("remediation revisions are outside the target lineage")
    for revision, expected in DESTINATION_HASH_ALLOWLIST.items():
        if result[revision] != expected:
            raise ChecksumRemediationError(
                f"reviewed destination hash pair changed for {revision}"
            )
    return result


def source_state(canonical: Mapping[str, HashPair]) -> SourceState:
    files: list[tuple[str, str]] = []
    for relative in SOURCE_FILES:
        files.append((relative, _regular_file_sha256(ROOT / relative)))
    serialized = [{"path": path, "sha256": digest} for path, digest in files]
    return SourceState(
        files=tuple(files),
        files_sha256=_json_sha256(serialized),
        canonical_ledger_sha256=_ledger_sha256(canonical),
    )


def validate_snapshot(
    snapshot: DatabaseSnapshot,
    *,
    canonical: Mapping[str, HashPair],
    target: TargetScope,
    expect_canonical_ledger: bool = False,
) -> None:
    _validate_database_identity(snapshot.identity, target)
    if snapshot.heads != (TARGET_REVISION,):
        raise ChecksumRemediationError(
            f"database must have the single Alembic head {TARGET_REVISION}"
        )
    if set(snapshot.ledger) != set(canonical):
        raise ChecksumRemediationError(
            "checksum ledger does not exactly match the applied 0095 lineage"
        )
    for revision, expected in canonical.items():
        actual = snapshot.ledger[revision]
        if expect_canonical_ledger:
            required = expected
        elif revision in OLD_HASH_ALLOWLIST:
            required = OLD_HASH_ALLOWLIST[revision]
        else:
            required = expected
        if actual != required:
            label = "canonical post-repair" if expect_canonical_ledger else "approved pre-repair"
            raise ChecksumRemediationError(
                f"revision {revision} is not the {label} hash pair"
            )
    schema_digest = _json_sha256(snapshot.schema)
    if schema_digest != EXPECTED_SCHEMA_FINGERPRINT_SHA256:
        raise ChecksumRemediationError(
            "complete Dify 0095 schema fingerprint is not canonical "
            f"(observed {schema_digest})"
        )


def _validate_database_identity(identity: DatabaseIdentity, target: TargetScope) -> None:
    if (
        identity.database_name != target.database_name
        or identity.database_user != target.database_user
        or identity.system_identifier != target.system_identifier
        or identity.project_ids != target.project_ids
    ):
        raise ChecksumRemediationError(
            "database identity does not match the out-of-band staging scope"
        )


def _inspect_snapshot(connection: psycopg.Connection[Any]) -> DatabaseSnapshot:
    identity_row = connection.execute(
        """SELECT current_database(), current_user, system_identifier::text
           FROM pg_control_system()"""
    ).fetchone()
    if identity_row is None:
        raise ChecksumRemediationError("database identity is unavailable")
    project_ids = tuple(
        str(row[0])
        for row in connection.execute("SELECT id::text FROM projects ORDER BY id").fetchall()
    )
    identity_payload = [
        str(identity_row[0]),
        str(identity_row[1]),
        str(identity_row[2]),
        list(project_ids),
    ]
    identity = DatabaseIdentity(
        database_name=str(identity_row[0]),
        database_user=str(identity_row[1]),
        system_identifier=str(identity_row[2]),
        project_ids=project_ids,
        fingerprint=_json_sha256(identity_payload),
    )
    heads = tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT version_num FROM public.alembic_version ORDER BY version_num"
        ).fetchall()
    )
    ledger = {
        str(row[0]): HashPair(upgrade=str(row[1]), downgrade=str(row[2]))
        for row in connection.execute(
            """SELECT revision, upgrade_sha256, downgrade_sha256
               FROM public.alembic_sql_checksum_ledger ORDER BY revision"""
        ).fetchall()
    }
    return DatabaseSnapshot(
        identity=identity,
        heads=heads,
        ledger=ledger,
        schema=_inspect_schema(connection),
    )


def _inspect_schema(connection: psycopg.Connection[Any]) -> dict[str, object]:
    relation_names = list(TARGET_RELATIONS)
    function_names = list(TARGET_FUNCTIONS)
    relations = [
        {
            "comment": row[7],
            "force_rls": bool(row[4]),
            "kind": str(row[1]),
            "name": str(row[0]),
            "options": list(row[5]) if row[5] is not None else [],
            "owner": str(row[2]),
            "rls": bool(row[3]),
            "view_definition": row[6],
        }
        for row in connection.execute(
            """SELECT relation.relname, relation.relkind::text,
                      pg_get_userbyid(relation.relowner), relation.relrowsecurity,
                      relation.relforcerowsecurity, relation.reloptions,
                      CASE WHEN relation.relkind = 'v'
                           THEN pg_get_viewdef(relation.oid, false) ELSE NULL END,
                      obj_description(relation.oid, 'pg_class')
               FROM pg_class AS relation
               WHERE relation.relnamespace = 'public'::regnamespace
                 AND relation.relname = ANY(%s)
               ORDER BY relation.relname""",
            (relation_names,),
        ).fetchall()
    ]
    columns = [
        {
            "acl": str(row[10]) if row[10] is not None else None,
            "collation": row[9],
            "default": row[6],
            "generated": str(row[8]),
            "identity": str(row[7]),
            "name": str(row[2]),
            "not_null": bool(row[4]),
            "number": int(row[1]),
            "relation": str(row[0]),
            "type": str(row[3]),
            "type_storage": str(row[5]),
        }
        for row in connection.execute(
            """SELECT relation.relname, attribute.attnum, attribute.attname,
                      format_type(attribute.atttypid, attribute.atttypmod),
                      attribute.attnotnull, attribute.attstorage::text,
                      pg_get_expr(default_value.adbin, default_value.adrelid, false),
                      attribute.attidentity::text, attribute.attgenerated::text,
                      CASE WHEN attribute.attcollation = 0 THEN NULL
                           ELSE attribute.attcollation::regcollation::text END,
                      attribute.attacl
               FROM pg_attribute AS attribute
               JOIN pg_class AS relation ON relation.oid = attribute.attrelid
               LEFT JOIN pg_attrdef AS default_value
                 ON default_value.adrelid = attribute.attrelid
                AND default_value.adnum = attribute.attnum
               WHERE relation.relnamespace = 'public'::regnamespace
                 AND relation.relname = ANY(%s)
                 AND attribute.attnum > 0 AND NOT attribute.attisdropped
               ORDER BY relation.relname, attribute.attnum""",
            (relation_names,),
        ).fetchall()
    ]
    constraints = [
        {
            "deferred": bool(row[5]),
            "deferrable": bool(row[4]),
            "definition": str(row[3]),
            "name": str(row[1]),
            "relation": str(row[0]),
            "type": str(row[2]),
            "validated": bool(row[6]),
        }
        for row in connection.execute(
            """SELECT relation.relname, constraint_value.conname,
                      constraint_value.contype::text,
                      pg_get_constraintdef(constraint_value.oid, false),
                      constraint_value.condeferrable, constraint_value.condeferred,
                      constraint_value.convalidated
               FROM pg_constraint AS constraint_value
               JOIN pg_class AS relation ON relation.oid = constraint_value.conrelid
               WHERE relation.relnamespace = 'public'::regnamespace
                 AND relation.relname = ANY(%s)
               ORDER BY relation.relname, constraint_value.conname""",
            (relation_names,),
        ).fetchall()
    ]
    indexes = [
        {
            "definition": str(row[2]),
            "name": str(row[1]),
            "primary": bool(row[4]),
            "ready": bool(row[6]),
            "relation": str(row[0]),
            "unique": bool(row[3]),
            "valid": bool(row[5]),
        }
        for row in connection.execute(
            """SELECT relation.relname, index_relation.relname,
                      pg_get_indexdef(index_value.indexrelid, 0, false),
                      index_value.indisunique, index_value.indisprimary,
                      index_value.indisvalid, index_value.indisready
               FROM pg_index AS index_value
               JOIN pg_class AS relation ON relation.oid = index_value.indrelid
               JOIN pg_class AS index_relation ON index_relation.oid = index_value.indexrelid
               WHERE relation.relnamespace = 'public'::regnamespace
                 AND relation.relname = ANY(%s)
               ORDER BY relation.relname, index_relation.relname""",
            (relation_names,),
        ).fetchall()
    ]
    policies = [
        {
            "check": row[6],
            "command": str(row[3]),
            "name": str(row[1]),
            "permissive": bool(row[2]),
            "relation": str(row[0]),
            "roles": list(row[4]),
            "using": row[5],
        }
        for row in connection.execute(
            """SELECT relation.relname, policy.polname, policy.polpermissive,
                      policy.polcmd::text,
                      ARRAY(SELECT pg_get_userbyid(role_id)
                            FROM unnest(policy.polroles) AS role_id ORDER BY 1),
                      pg_get_expr(policy.polqual, policy.polrelid, false),
                      pg_get_expr(policy.polwithcheck, policy.polrelid, false)
               FROM pg_policy AS policy
               JOIN pg_class AS relation ON relation.oid = policy.polrelid
               WHERE relation.relnamespace = 'public'::regnamespace
                 AND relation.relname = ANY(%s)
               ORDER BY relation.relname, policy.polname""",
            (relation_names,),
        ).fetchall()
    ]
    relation_acl = [
        {
            "grantable": bool(row[4]),
            "grantee": str(row[2]),
            "grantor": str(row[1]),
            "privilege": str(row[3]),
            "relation": str(row[0]),
        }
        for row in connection.execute(
            """SELECT relation.relname, pg_get_userbyid(acl.grantor),
                      CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                           ELSE pg_get_userbyid(acl.grantee) END,
                      acl.privilege_type, acl.is_grantable
               FROM pg_class AS relation
               CROSS JOIN LATERAL aclexplode(
                   coalesce(relation.relacl, acldefault('r', relation.relowner))
               ) AS acl
               WHERE relation.relnamespace = 'public'::regnamespace
                 AND relation.relname = ANY(%s)
               ORDER BY relation.relname, 3, 4, 2""",
            (relation_names,),
        ).fetchall()
    ]
    triggers = [
        {
            "definition": str(row[2]),
            "enabled": str(row[3]),
            "name": str(row[1]),
            "relation": str(row[0]),
        }
        for row in connection.execute(
            """SELECT relation.relname, trigger_value.tgname,
                      pg_get_triggerdef(trigger_value.oid, false),
                      trigger_value.tgenabled::text
               FROM pg_trigger AS trigger_value
               JOIN pg_class AS relation ON relation.oid = trigger_value.tgrelid
               WHERE relation.relnamespace = 'public'::regnamespace
                 AND relation.relname = ANY(%s) AND NOT trigger_value.tgisinternal
               ORDER BY relation.relname, trigger_value.tgname""",
            (relation_names,),
        ).fetchall()
    ]
    functions = [
        {
            "config": list(row[10]) if row[10] is not None else [],
            "definition": str(row[3]),
            "identity_arguments": str(row[2]),
            "leakproof": bool(row[8]),
            "name": str(row[0]),
            "owner": str(row[1]),
            "parallel": str(row[7]),
            "security_definer": bool(row[5]),
            "strict": bool(row[9]),
            "volatility": str(row[6]),
        }
        for row in connection.execute(
            """SELECT function_value.proname,
                      pg_get_userbyid(function_value.proowner),
                      pg_get_function_identity_arguments(function_value.oid),
                      pg_get_functiondef(function_value.oid),
                      function_value.oid, function_value.prosecdef,
                      function_value.provolatile::text, function_value.proparallel::text,
                      function_value.proleakproof, function_value.proisstrict,
                      function_value.proconfig
               FROM pg_proc AS function_value
               WHERE function_value.pronamespace = 'public'::regnamespace
                 AND function_value.proname = ANY(%s)
               ORDER BY function_value.proname,
                        pg_get_function_identity_arguments(function_value.oid)""",
            (function_names,),
        ).fetchall()
    ]
    function_acl = [
        {
            "function": str(row[0]),
            "grantable": bool(row[5]),
            "grantee": str(row[3]),
            "grantor": str(row[2]),
            "identity_arguments": str(row[1]),
            "privilege": str(row[4]),
        }
        for row in connection.execute(
            """SELECT function_value.proname,
                      pg_get_function_identity_arguments(function_value.oid),
                      pg_get_userbyid(acl.grantor),
                      CASE WHEN acl.grantee = 0 THEN 'PUBLIC'
                           ELSE pg_get_userbyid(acl.grantee) END,
                      acl.privilege_type, acl.is_grantable
               FROM pg_proc AS function_value
               CROSS JOIN LATERAL aclexplode(
                   coalesce(function_value.proacl, acldefault('f', function_value.proowner))
               ) AS acl
               WHERE function_value.pronamespace = 'public'::regnamespace
                 AND function_value.proname = ANY(%s)
               ORDER BY function_value.proname, 2, 4, 5, 3""",
            (function_names,),
        ).fetchall()
    ]
    roles = [
        {
            "bypass_rls": bool(row[7]),
            "can_login": bool(row[2]),
            "create_db": bool(row[4]),
            "create_role": bool(row[3]),
            "inherit": bool(row[6]),
            "name": str(row[0]),
            "replication": bool(row[5]),
            "superuser": bool(row[1]),
        }
        for row in connection.execute(
            """SELECT rolname, rolsuper, rolcanlogin, rolcreaterole, rolcreatedb,
                      rolreplication, rolinherit, rolbypassrls
               FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname""",
            (list(RUNTIME_ROLES),),
        ).fetchall()
    ]
    upward_memberships = [
        {
            "depth": int(row[2]),
            "member": str(row[0]),
            "parent_role": str(row[1]),
        }
        for row in connection.execute(
            """WITH RECURSIVE role_tree(root_role, member_oid, parent_oid, depth) AS (
                   SELECT child.rolname, membership.member, membership.roleid, 1
                   FROM pg_auth_members AS membership
                   JOIN pg_roles AS child ON child.oid = membership.member
                   WHERE child.rolname = ANY(%s)
                   UNION ALL
                   SELECT role_tree.root_role, membership.member,
                          membership.roleid, role_tree.depth + 1
                   FROM role_tree
                   JOIN pg_auth_members AS membership
                     ON membership.member = role_tree.parent_oid
                   WHERE role_tree.depth < 16
               )
               SELECT root_role, parent.rolname, depth
               FROM role_tree JOIN pg_roles AS parent ON parent.oid = parent_oid
               ORDER BY root_role, depth, parent.rolname""",
            (list(RUNTIME_ROLES),),
        ).fetchall()
    ]
    return {
        "columns": columns,
        "constraints": constraints,
        "function_acl": function_acl,
        "functions": functions,
        "indexes": indexes,
        "policies": policies,
        "relation_acl": relation_acl,
        "relations": relations,
        "roles": roles,
        "triggers": triggers,
        "upward_role_memberships": upward_memberships,
    }


def _apply_updates(
    connection: psycopg.Connection[Any], *, canonical: Mapping[str, HashPair]
) -> int:
    values: list[str] = []
    parameters: list[str] = []
    for revision in REMEDIATED_REVISIONS:
        old = OLD_HASH_ALLOWLIST[revision]
        new = canonical[revision]
        values.append("(%s, %s, %s, %s, %s)")
        parameters.extend(
            [revision, old.upgrade, old.downgrade, new.upgrade, new.downgrade]
        )
    cursor = connection.execute(
        f"""UPDATE public.alembic_sql_checksum_ledger AS ledger
            SET upgrade_sha256 = candidate.new_upgrade,
                downgrade_sha256 = candidate.new_downgrade,
                recorded_at = clock_timestamp()
            FROM (VALUES {', '.join(values)}) AS candidate(
                revision, old_upgrade, old_downgrade, new_upgrade, new_downgrade
            )
            WHERE ledger.revision = candidate.revision
              AND ledger.upgrade_sha256 = candidate.old_upgrade
              AND ledger.downgrade_sha256 = candidate.old_downgrade
            RETURNING ledger.revision""",
        parameters,
    )
    updated = tuple(str(row[0]) for row in cursor.fetchall())
    if set(updated) != set(REMEDIATED_REVISIONS) or len(updated) != len(
        REMEDIATED_REVISIONS
    ):
        raise ChecksumRemediationError(
            "checksum repair did not update exactly the three allowlisted rows"
        )
    return len(updated)


def execute_remediation(
    connection: psycopg.Connection[Any],
    *,
    canonical: Mapping[str, HashPair],
    source: SourceState,
    backup: BackupEvidence,
    target: TargetScope,
    apply: bool,
    dry_run_receipt: Mapping[str, object] | None,
    allow_canonical_recovery: bool,
) -> dict[str, object]:
    updated_rows = 0
    recovered = False
    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout = '10s'")
        connection.execute("SET LOCAL statement_timeout = '30s'")
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('geo.schema.migration', 0))"
        )
        connection.execute("LOCK TABLE public.alembic_version IN ACCESS EXCLUSIVE MODE")
        connection.execute(
            "LOCK TABLE public.alembic_sql_checksum_ledger IN ACCESS EXCLUSIVE MODE"
        )
        connection.execute(
            """LOCK TABLE public.dify_workflow_releases,
                              public.dify_workflow_bindings,
                              public.dify_workflow_published_snapshots,
                              public.dify_workflow_execution_attempts,
                              public.dify_workflow_execution_results,
                              public.synthetic_lab_model_call_child_status
               IN ACCESS EXCLUSIVE MODE"""
        )
        snapshot = _inspect_snapshot(connection)
        if apply and snapshot.ledger == canonical:
            if not allow_canonical_recovery:
                raise ChecksumRemediationError(
                    "ledger is already canonical and no matching pending receipt exists"
                )
            validate_snapshot(
                snapshot,
                canonical=canonical,
                target=target,
                expect_canonical_ledger=True,
            )
            recovered = True
            updated_rows = len(REMEDIATED_REVISIONS)
        else:
            validate_snapshot(snapshot, canonical=canonical, target=target)
            if snapshot.ledger != backup.database_ledger:
                raise ChecksumRemediationError(
                    "authenticated backup database ledger does not match the target"
                )
            if apply:
                updated_rows = _apply_updates(connection, canonical=canonical)
                post = _inspect_snapshot(connection)
                validate_snapshot(
                    post,
                    canonical=canonical,
                    target=target,
                    expect_canonical_ledger=True,
                )

        current_plan = _frozen_plan(snapshot, source=source, backup=backup, target=target)
        frozen_plan: Mapping[str, object] = current_plan
        if apply:
            assert dry_run_receipt is not None
            expected_plan = dry_run_receipt.get("frozen_plan")
            expected_plan_hash = dry_run_receipt.get("frozen_plan_sha256")
            if recovered and isinstance(expected_plan, Mapping):
                for key in expected_plan:
                    if key != "ledger_before_sha256" and expected_plan[key] != current_plan.get(key):
                        raise ChecksumRemediationError(
                            "recovered target no longer matches the dry-run plan"
                        )
                frozen_plan = expected_plan
            if expected_plan != frozen_plan or expected_plan_hash != _json_sha256(frozen_plan):
                raise ChecksumRemediationError(
                    "current source, backup, schema or target does not match dry-run receipt"
                )
            receipt = _build_apply_receipt(
                dry_run_receipt=dry_run_receipt,
                frozen_plan=frozen_plan,
                recovered=recovered,
                updated_rows=updated_rows,
                canonical=canonical,
            )
        else:
            receipt = _build_dry_run_receipt(
                frozen_plan=frozen_plan,
                canonical=canonical,
            )
    return receipt


def _frozen_plan(
    snapshot: DatabaseSnapshot,
    *,
    source: SourceState,
    backup: BackupEvidence,
    target: TargetScope,
) -> dict[str, object]:
    return {
        "backup": backup.as_receipt(),
        "database_fingerprint": snapshot.identity.fingerprint,
        "ledger_before_sha256": _ledger_sha256(snapshot.ledger),
        "schema_contract_sha256": _json_sha256(snapshot.schema),
        "source": source.as_receipt(),
        "target": target.public_identity,
        "transitions": _transitions(),
    }


def _build_dry_run_receipt(
    *, frozen_plan: Mapping[str, object], canonical: Mapping[str, HashPair]
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "canonical_ledger_sha256": _ledger_sha256(canonical),
        "frozen_plan": dict(frozen_plan),
        "frozen_plan_sha256": _json_sha256(frozen_plan),
        "mode": "dry_run",
        "schema_version": RECEIPT_SCHEMA,
        "state": "committed",
        "updated_rows": 0,
        "verified_at": _utc_now(),
    }
    receipt["receipt_sha256"] = _json_sha256(receipt)
    return receipt


def _build_apply_receipt(
    *,
    dry_run_receipt: Mapping[str, object],
    frozen_plan: Mapping[str, object],
    recovered: bool,
    updated_rows: int,
    canonical: Mapping[str, HashPair],
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "canonical_ledger_sha256": _ledger_sha256(canonical),
        "dry_run_receipt_sha256": dry_run_receipt["receipt_sha256"],
        "frozen_plan_sha256": _json_sha256(frozen_plan),
        "mode": "applied",
        "recovered_after_unknown_commit": recovered,
        "schema_version": RECEIPT_SCHEMA,
        "state": "committed",
        "updated_rows": updated_rows,
        "verified_at": _utc_now(),
    }
    receipt["receipt_sha256"] = _json_sha256(receipt)
    return receipt


def _transitions() -> list[dict[str, str]]:
    return [
        {
            "new_downgrade_sha256": DESTINATION_HASH_ALLOWLIST[revision].downgrade,
            "new_upgrade_sha256": DESTINATION_HASH_ALLOWLIST[revision].upgrade,
            "old_downgrade_sha256": OLD_HASH_ALLOWLIST[revision].downgrade,
            "old_upgrade_sha256": OLD_HASH_ALLOWLIST[revision].upgrade,
            "revision": revision,
        }
        for revision in REMEDIATED_REVISIONS
    ]


def load_backup_evidence(
    *,
    backup_directory: Path,
    keyring_path: Path,
    restore_receipt_path: Path,
    canonical: Mapping[str, HashPair],
    target: TargetScope,
) -> BackupEvidence:
    try:
        keyring = load_backup_keyring(keyring_path)
        manifest = verify_backup_set(backup_directory, keyring=keyring)
    except BackupSecurityError as error:
        raise ChecksumRemediationError(
            "authenticated committed backup verification failed"
        ) from error
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ChecksumRemediationError(
            "backup manifest lacks the required source database identity"
        )
    source = _mapping(manifest.get("source"), "backup source")
    postgres = _mapping(source.get("postgres"), "backup postgres source")
    manifest_scope = TargetScope(
        environment=_string(postgres.get("environment"), "backup environment"),
        database_name=_string(postgres.get("database_name"), "backup database name"),
        database_user=_string(postgres.get("database_user"), "backup database user"),
        system_identifier=_string(
            postgres.get("system_identifier"), "backup system identifier"
        ),
        project_ids=_project_ids(postgres.get("project_ids")),
    )
    if manifest_scope != target:
        raise ChecksumRemediationError(
            "authenticated backup identity does not match out-of-band staging scope"
        )
    if postgres.get("migration_revision") != TARGET_REVISION:
        raise ChecksumRemediationError("backup is not from the required 0095 head")

    repository_ledger = _mapping(
        postgres.get("alembic_sql_checksum_ledger"), "backup repository ledger"
    )
    repository_pairs = _pairs_from_repository_ledger(repository_ledger)
    if repository_pairs != canonical:
        raise ChecksumRemediationError(
            "backup repository ledger is not the reviewed destination lineage"
        )
    database_ledger_value = _mapping(
        postgres.get("database_checksum_ledger"), "backup database ledger"
    )
    database_pairs = _pairs_from_database_ledger(database_ledger_value)
    expected_pre = dict(canonical)
    expected_pre.update(OLD_HASH_ALLOWLIST)
    if database_pairs != expected_pre:
        raise ChecksumRemediationError(
            "backup database ledger is not the exact approved pre-repair state"
        )

    manifest_sha256 = _regular_file_sha256(backup_directory / "manifest.json")
    try:
        validate_restore_receipt(
            restore_receipt_path,
            expected_backup_id=_string(manifest.get("backup_id"), "backup ID"),
            expected_manifest_sha256=manifest_sha256,
            expected_migration_revision=TARGET_REVISION,
            expected_ledger_sha256=_string(
                repository_ledger.get("ledger_sha256"), "repository ledger digest"
            ),
            expected_database_ledger_sha256=_string(
                database_ledger_value.get("ledger_sha256"),
                "database ledger digest",
            ),
            expected_project_count=len(target.project_ids),
        )
    except BackupSecurityError as error:
        raise ChecksumRemediationError(
            "isolated restore receipt does not match the committed backup"
        ) from error
    return BackupEvidence(
        backup_id=_string(manifest.get("backup_id"), "backup ID"),
        committed_sha256=_regular_file_sha256(backup_directory / "COMMITTED"),
        manifest_sha256=manifest_sha256,
        restore_receipt_sha256=_regular_file_sha256(restore_receipt_path),
        repository_ledger_sha256=_string(
            repository_ledger.get("ledger_sha256"), "repository ledger digest"
        ),
        database_ledger=database_pairs,
        database_ledger_sha256=_string(
            database_ledger_value.get("ledger_sha256"), "database ledger digest"
        ),
        scope=manifest_scope,
    )


def _pairs_from_repository_ledger(value: Mapping[str, object]) -> dict[str, HashPair]:
    if value.get("head_revision") != TARGET_REVISION:
        raise ChecksumRemediationError("backup repository ledger head is invalid")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise ChecksumRemediationError("backup repository ledger entries are invalid")
    result: dict[str, HashPair] = {}
    for entry in entries:
        item = _mapping(entry, "backup repository ledger entry")
        revision = _string(item.get("revision"), "backup revision")
        result[revision] = HashPair(
            upgrade=_digest(item.get("upgrade_sha256"), "backup upgrade checksum"),
            downgrade=_digest(item.get("downgrade_sha256"), "backup downgrade checksum"),
        )
    return result


def _pairs_from_database_ledger(value: Mapping[str, object]) -> dict[str, HashPair]:
    if (
        value.get("schema_version") != DATABASE_LEDGER_SCHEMA
        or value.get("head_revision") != TARGET_REVISION
    ):
        raise ChecksumRemediationError("backup database ledger contract is invalid")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise ChecksumRemediationError("backup database ledger entries are invalid")
    result: dict[str, HashPair] = {}
    for entry in entries:
        item = _mapping(entry, "backup database ledger entry")
        revision = _string(item.get("revision"), "backup database revision")
        if revision in result:
            raise ChecksumRemediationError("backup database ledger has duplicate revisions")
        result[revision] = HashPair(
            upgrade=_digest(item.get("upgrade_sha256"), "backup database upgrade checksum"),
            downgrade=_digest(
                item.get("downgrade_sha256"), "backup database downgrade checksum"
            ),
        )
    payload = {
        "entries": [
            {
                "downgrade_sha256": pair.downgrade,
                "revision": revision,
                "upgrade_sha256": pair.upgrade,
            }
            for revision, pair in result.items()
        ],
        "head_revision": TARGET_REVISION,
    }
    if value.get("ledger_sha256") != _json_sha256(payload):
        raise ChecksumRemediationError("backup database ledger digest is invalid")
    return result


def _load_dry_run_receipt(path: Path) -> dict[str, object]:
    try:
        receipt = read_canonical_json(path, label="checksum remediation dry-run receipt")
    except BackupSecurityError as error:
        raise ChecksumRemediationError("dry-run receipt is not canonical and private") from error
    expected = {
        "canonical_ledger_sha256",
        "frozen_plan",
        "frozen_plan_sha256",
        "mode",
        "receipt_sha256",
        "schema_version",
        "state",
        "updated_rows",
        "verified_at",
    }
    supplied_hash = receipt.get("receipt_sha256")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if (
        set(receipt) != expected
        or receipt.get("schema_version") != RECEIPT_SCHEMA
        or receipt.get("state") != "committed"
        or receipt.get("mode") != "dry_run"
        or receipt.get("updated_rows") != 0
        or supplied_hash != _json_sha256(body)
        or receipt.get("frozen_plan_sha256") != _json_sha256(receipt.get("frozen_plan"))
    ):
        raise ChecksumRemediationError("dry-run receipt integrity check failed")
    return receipt


def _pending_intent(
    *,
    apply: bool,
    source: SourceState,
    backup: BackupEvidence,
    target: TargetScope,
    dry_run_receipt: Mapping[str, object] | None,
) -> dict[str, object]:
    intent: dict[str, object] = {
        "backup": backup.as_receipt(),
        "mode": "apply" if apply else "dry_run",
        "schema_version": RECEIPT_SCHEMA,
        "source": source.as_receipt(),
        "state": "pending",
        "target": target.public_identity,
    }
    if dry_run_receipt is not None:
        intent["dry_run_receipt_sha256"] = dry_run_receipt["receipt_sha256"]
        intent["frozen_plan_sha256"] = dry_run_receipt["frozen_plan_sha256"]
    intent["pending_receipt_sha256"] = _json_sha256(intent)
    return intent


def reserve_receipt(path: Path, intent: Mapping[str, object]) -> ReceiptReservation:
    _ensure_receipt_parent(path.parent)
    if path.exists() or path.is_symlink():
        try:
            existing = read_canonical_json(path, label="pending remediation receipt")
        except BackupSecurityError as error:
            raise ChecksumRemediationError(
                "receipt path exists but is not a valid pending receipt"
            ) from error
        if existing != intent:
            raise ChecksumRemediationError(
                "receipt path already contains a different or committed receipt"
            )
        return ReceiptReservation(path=path, intent=intent, resumed=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_json(intent) + b"\n")
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(path.parent)
    except OSError as error:
        raise ChecksumRemediationError("pending receipt could not be reserved") from error
    return ReceiptReservation(path=path, intent=intent, resumed=False)


def _ensure_receipt_parent(path: Path) -> None:
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        metadata = path.lstat()
    except OSError as error:
        raise ChecksumRemediationError("receipt directory is unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise ChecksumRemediationError(
            "receipt directory must be owned by the operator and not group/world writable"
        )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_database_url(path: Path) -> str:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}
            or metadata.st_uid not in {0, os.geteuid()}
        ):
            raise ChecksumRemediationError(
                "database URL file must be an owned regular file with mode 0400 or 0600"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "r", encoding="utf-8") as source:
            opened = os.fstat(source.fileno())
            if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                raise ChecksumRemediationError("database URL file changed while opening")
            value = source.read(16 * 1024 + 1).strip()
    except OSError as error:
        raise ChecksumRemediationError("database URL file cannot be read") from error
    if len(value) > 16 * 1024:
        raise ChecksumRemediationError("database URL file is too large")
    if value.startswith("postgresql+psycopg://"):
        value = "postgresql://" + value.removeprefix("postgresql+psycopg://")
    if not value.startswith(("postgresql://", "postgres://")):
        raise ChecksumRemediationError("database URL file is not a PostgreSQL URL")
    return value


def _target_scope(arguments: argparse.Namespace) -> TargetScope:
    project_ids = _project_ids(arguments.expected_project_id)
    if (
        arguments.expected_environment != EXPECTED_ENVIRONMENT
        or arguments.expected_database_name != EXPECTED_DATABASE_NAME
        or arguments.expected_database_user != EXPECTED_DATABASE_USER
        or not isinstance(arguments.expected_system_identifier, str)
        or _SYSTEM_IDENTIFIER.fullmatch(arguments.expected_system_identifier) is None
        or not project_ids
    ):
        raise ChecksumRemediationError(
            "explicit out-of-band staging database identity is invalid"
        )
    return TargetScope(
        environment=arguments.expected_environment,
        database_name=arguments.expected_database_name,
        database_user=arguments.expected_database_user,
        system_identifier=arguments.expected_system_identifier,
        project_ids=project_ids,
    )


def _project_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ChecksumRemediationError("project identities are invalid")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ChecksumRemediationError("project identity is invalid")
        try:
            canonical = str(UUID(item))
        except ValueError:
            raise ChecksumRemediationError("project identity is invalid") from None
        if canonical != item:
            raise ChecksumRemediationError("project identity is not canonical")
        normalized.append(canonical)
    if normalized != sorted(set(normalized)):
        raise ChecksumRemediationError("project identities must be unique and sorted")
    return tuple(normalized)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ChecksumRemediationError(f"{label} is invalid")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ChecksumRemediationError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ChecksumRemediationError(f"{label} is invalid")
    return value


def _ledger_sha256(ledger: Mapping[str, HashPair]) -> str:
    return _json_sha256(
        [
            {
                "downgrade_sha256": pair.downgrade,
                "revision": revision,
                "upgrade_sha256": pair.upgrade,
            }
            for revision, pair in ledger.items()
        ]
    )


def _json_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _regular_file_sha256(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < 1:
            raise OSError
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if (opened.st_dev, opened.st_ino, opened.st_size) != (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
            ):
                raise OSError
            digest = hashlib.file_digest(source, "sha256")
    except OSError as error:
        raise ChecksumRemediationError("required evidence file cannot be read safely") from error
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--backup-keyring-file", type=Path, required=True)
    parser.add_argument("--restore-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-environment", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--expected-database-user", required=True)
    parser.add_argument("--expected-system-identifier", required=True)
    parser.add_argument("--expected-project-id", action="append", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the exact dry-run plan; without this flag the database is read-only",
    )
    parser.add_argument("--dry-run-receipt", type=Path)
    return parser


def _validate_arguments(arguments: argparse.Namespace) -> None:
    if arguments.apply and arguments.dry_run_receipt is None:
        raise ChecksumRemediationError("--apply requires --dry-run-receipt")
    if not arguments.apply and arguments.dry_run_receipt is not None:
        raise ChecksumRemediationError("--dry-run-receipt is accepted only with --apply")
    if arguments.dry_run_receipt is not None and (
        arguments.dry_run_receipt.absolute() == arguments.receipt.absolute()
    ):
        raise ChecksumRemediationError("apply receipt must differ from dry-run receipt")


def main(argv: Sequence[str] | None = None) -> int:
    reservation: ReceiptReservation | None = None
    try:
        arguments = build_parser().parse_args(argv)
        _validate_arguments(arguments)
        target = _target_scope(arguments)
        canonical = repository_hashes()
        source = source_state(canonical)
        backup = load_backup_evidence(
            backup_directory=arguments.backup_dir,
            keyring_path=arguments.backup_keyring_file,
            restore_receipt_path=arguments.restore_receipt,
            canonical=canonical,
            target=target,
        )
        dry_run_receipt = (
            _load_dry_run_receipt(arguments.dry_run_receipt)
            if arguments.dry_run_receipt is not None
            else None
        )
        intent = _pending_intent(
            apply=arguments.apply,
            source=source,
            backup=backup,
            target=target,
            dry_run_receipt=dry_run_receipt,
        )
        reservation = reserve_receipt(arguments.receipt, intent)
        database_url = _load_database_url(arguments.database_url_file)
        with psycopg.connect(database_url, autocommit=True) as connection:
            receipt = execute_remediation(
                connection,
                canonical=canonical,
                source=source,
                backup=backup,
                target=target,
                apply=arguments.apply,
                dry_run_receipt=dry_run_receipt,
                allow_canonical_recovery=arguments.apply and reservation.resumed,
            )
        reservation.finalize(receipt)
        print(canonical_json(receipt).decode("ascii"))
        return 0
    except (ChecksumRemediationError, BackupSecurityError) as error:
        print(f"checksum remediation refused: {error}", file=sys.stderr)
        return 2
    except psycopg.Error as error:
        sqlstate = error.sqlstate or "unavailable"
        suffix = ""
        if reservation is not None:
            suffix = "; matching pending receipt retained for reconciliation"
        print(
            "checksum remediation database operation failed "
            f"(SQLSTATE {sqlstate}){suffix}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
