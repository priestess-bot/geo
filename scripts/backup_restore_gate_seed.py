"""Create isolated, recoverable data for the authenticated restore Gate."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import traceback

import psycopg

ROOT = Path(__file__).resolve().parents[1]
for source_root in (ROOT, ROOT / "apps" / "api"):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from geo_core.object_store import S3CompatibleObjectStore  # noqa: E402
from geo_core.synthetic_lab.artifact_keyring import (  # noqa: E402
    load_synthetic_artifact_keyring,
)
from scripts.backup_envelope import canonical_json  # noqa: E402
from scripts.backup_restore_gate_seed_common import (  # noqa: E402
    IDS,
    KEYRING_FILES,
    RestoreGateSeedError,
    create_keyrings,
    current_head,
    migrate,
    principal,
    require_secure_directory,
    seed_project,
)
from scripts.backup_restore_gate_seed_provider import (  # noqa: E402
    seed_provider_artifacts,
)
from scripts.backup_restore_gate_seed_recommendation import (  # noqa: E402
    seed_recommendation_artifacts,
)
from scripts.backup_restore_gate_seed_secret_prompt import (  # noqa: E402
    seed_prompt,
    seed_recommendation_prompt,
    seed_secrets,
)
from scripts.backup_restore_gate_seed_synthetic import (  # noqa: E402
    seed_synthetic_artifacts,
)
from scripts.backup_restore_gate_seed_workflow_c import (  # noqa: E402
    seed_workflow_c_artifacts,
)


def seed(
    *,
    database_url: str,
    expected_head: str,
    object_store: S3CompatibleObjectStore,
    recommendation_object_store: S3CompatibleObjectStore,
    workflow_c_object_store: S3CompatibleObjectStore,
    synthetic_raw_object_store: S3CompatibleObjectStore,
    synthetic_derived_object_store: S3CompatibleObjectStore,
    keyring_directory: Path,
) -> dict[str, object]:
    if (
        len(
            {
                object_store.bucket,
                recommendation_object_store.bucket,
                workflow_c_object_store.bucket,
                synthetic_raw_object_store.bucket,
                synthetic_derived_object_store.bucket,
            }
        )
        != 5
    ):
        raise RestoreGateSeedError("all restore Gate artifact stores must use distinct buckets")
    if expected_head != current_head():
        raise RestoreGateSeedError("Alembic head changed before restore Gate seeding")
    migrate(database_url)
    seed_project(database_url)
    owner = principal(IDS.owner)
    reviewer = principal(IDS.reviewer)
    provider_secret = seed_secrets(
        database_url=database_url,
        keyring_directory=keyring_directory,
        owner=owner,
        reviewer=reviewer,
    )
    prompt, output_schema = seed_prompt(
        database_url=database_url,
        owner=owner,
        reviewer=reviewer,
    )
    recommendation_prompt, recommendation_output_schema = seed_recommendation_prompt(
        database_url=database_url,
        owner=owner,
        reviewer=reviewer,
    )
    provider = seed_provider_artifacts(
        database_url=database_url,
        object_store=object_store,
        provider_keyring=keyring_directory / KEYRING_FILES["provider"],
        provider_secret=provider_secret,
        prompt=prompt,
        output_schema=output_schema,
    )
    synthetic = seed_synthetic_artifacts(
        database_url=database_url,
        raw_object_store=synthetic_raw_object_store,
        derived_object_store=synthetic_derived_object_store,
        keyring=load_synthetic_artifact_keyring(keyring_directory / KEYRING_FILES["synthetic"]),
    )
    recommendation = seed_recommendation_artifacts(
        database_url=database_url,
        object_store=recommendation_object_store,
        keyring_path=keyring_directory / KEYRING_FILES["recommendation"],
        prompt_binding=recommendation_prompt,
        output_schema=recommendation_output_schema,
    )
    workflow_c = seed_workflow_c_artifacts(
        database_url=database_url,
        object_store=workflow_c_object_store,
        keyring_path=keyring_directory / KEYRING_FILES["workflow_c"],
    )
    with psycopg.connect(database_url) as connection:
        migrated_head = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        if migrated_head is None or migrated_head[0] != expected_head:
            raise RestoreGateSeedError("seed database does not match the frozen Alembic head")
        counts = connection.execute(
            """SELECT
                   (SELECT count(*) FROM secret_master_key_versions WHERE status <> 'retired'),
                   (SELECT count(DISTINCT master_key_version) FROM secret_versions),
                   (SELECT count(*) FROM model_gateway_artifact_master_key_versions
                    WHERE status <> 'retired'),
                   (SELECT count(*) FROM synthetic_lab_artifact_master_key_versions
                    WHERE status <> 'retired')"""
        ).fetchone()
    if counts != (2, 2, 2, 2):
        raise RestoreGateSeedError("seed key-version coverage is incomplete")
    return {
        "alembic_head": expected_head,
        "key_version_counts": {
            "provider": counts[2],
            "secret_referenced": counts[1],
            "secret_store": counts[0],
            "synthetic": counts[3],
        },
        "project_id": str(IDS.project),
        "provider_artifacts": provider,
        "recommendation_artifacts": recommendation,
        "secret_runtime_canary": {
            "idempotency_key": "restore-gate-frozen-handle-resolve-v1",
            "project_id": str(provider_secret.project_id),
            "purpose": provider_secret.purpose,
            "reference_id": str(provider_secret.reference_id),
            "service_identity_id": str(IDS.restore_probe_service),
            "version": provider_secret.version,
        },
        "schema_version": "geo-authenticated-restore-gate-seed-v1",
        "synthetic_artifacts": synthetic,
        "workflow_c_artifacts": workflow_c,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("head", help="Print the single current Alembic head")
    keys = subparsers.add_parser("create-keyrings", help="Create isolated Gate keyrings")
    keys.add_argument("--directory", type=Path, required=True)
    seed_parser = subparsers.add_parser("seed", help="Migrate and seed an isolated database")
    seed_parser.add_argument("--database-url", required=True)
    seed_parser.add_argument("--expected-head", required=True)
    seed_parser.add_argument("--object-store-endpoint", required=True)
    seed_parser.add_argument("--object-store-bucket", required=True)
    seed_parser.add_argument("--recommendation-object-store-bucket", required=True)
    seed_parser.add_argument("--workflow-c-object-store-bucket", required=True)
    seed_parser.add_argument("--synthetic-raw-object-store-bucket", required=True)
    seed_parser.add_argument("--synthetic-derived-object-store-bucket", required=True)
    seed_parser.add_argument("--keyring-directory", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "head":
            print(current_head())
            return 0
        if args.command == "create-keyrings":
            create_keyrings(args.directory)
            return 0
        keyring_directory: Path = args.keyring_directory
        require_secure_directory(keyring_directory)
        result = seed(
            database_url=args.database_url,
            expected_head=args.expected_head,
            object_store=S3CompatibleObjectStore(
                endpoint=args.object_store_endpoint,
                bucket=args.object_store_bucket,
                access_key="geo_dev",
                secret_key="geo_dev_secret",
                auto_create_bucket=True,
            ),
            recommendation_object_store=S3CompatibleObjectStore(
                endpoint=args.object_store_endpoint,
                bucket=args.recommendation_object_store_bucket,
                access_key="geo_dev",
                secret_key="geo_dev_secret",
                auto_create_bucket=True,
            ),
            workflow_c_object_store=S3CompatibleObjectStore(
                endpoint=args.object_store_endpoint,
                bucket=args.workflow_c_object_store_bucket,
                access_key="geo_dev",
                secret_key="geo_dev_secret",
                auto_create_bucket=True,
            ),
            synthetic_raw_object_store=S3CompatibleObjectStore(
                endpoint=args.object_store_endpoint,
                bucket=args.synthetic_raw_object_store_bucket,
                access_key="geo_dev",
                secret_key="geo_dev_secret",
                auto_create_bucket=True,
            ),
            synthetic_derived_object_store=S3CompatibleObjectStore(
                endpoint=args.object_store_endpoint,
                bucket=args.synthetic_derived_object_store_bucket,
                access_key="geo_dev",
                secret_key="geo_dev_secret",
                auto_create_bucket=True,
            ),
            keyring_directory=keyring_directory,
        )
    except Exception as error:
        # The normal Gate log intentionally suppresses exception text: seed
        # paths handle decrypted Secrets.  An explicit local debug switch can
        # reveal only PostgreSQL's public SQLSTATE/constraint identity.
        suffix = ""
        if os.environ.get("GEO_RESTORE_GATE_DEBUG") == "1":
            diagnostic = getattr(error, "diag", None)
            sqlstate = getattr(error, "sqlstate", None)
            constraint = getattr(diagnostic, "constraint_name", None)
            frames = traceback.extract_tb(error.__traceback__)
            locations = ",".join(
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames[-8:]
            )
            suffix = (
                f" sqlstate={sqlstate or '-'} constraint={constraint or '-'}"
                f" frames={locations or '-'}"
            )
        print(
            f"restore Gate seed error: {error.__class__.__name__}{suffix}",
            file=sys.stderr,
        )
        return 2
    print(canonical_json(result).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
