"""Verify independent non-B artifact domains inside an exported backup snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import traceback
from typing import Never

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from geo_core.object_store import RetrievedObject, S3CompatibleObjectStore, parse_s3_uri
from geo_core.object_store_config import build_object_store_from_prefix
from geo_core.recommendations.artifact_keyring_postgres import (
    verify_recommendation_artifact_restore,
)
from geo_core.recommendations.generation_artifacts import (
    EncryptedRecommendationTaskArtifactStore,
    RecommendationTaskObjectStore,
)
from geo_core.sampling.manual_artifact_storage import WorkflowCManualArtifactObjectStore
from geo_core.workflow_c_artifacts.postgres import (
    verify_workflow_c_artifact_restore,
)
from geo_core.secrets import EnvelopeCipher, load_master_keyring_from_docker_secret
from geo_core.restored_object_reader import (
    VerifiedRestoredObjectReader,
    VerifiedRestoredObjectReaders,
)
from geo_core.synthetic_lab.artifact_keyring import load_synthetic_artifact_keyring
from geo_core.synthetic_lab.artifact_keyring_postgres import (
    verify_synthetic_artifact_recovery,
)
from geo_worker.config import secret_setting


PROBE_SCHEMA = "geo-non-b-artifact-backup-source-v1"
_SNAPSHOT = re.compile(r"^[0-9A-Fa-f-]+$")
_RECOMMENDATION_BUCKET = "geo-restricted-recommendation-artifacts"
_WORKFLOW_C_BUCKET = "geo-restricted-workflow-c-artifacts"
_SYNTHETIC_RAW_BUCKET = "geo-synthetic-style-raw"
_SYNTHETIC_DERIVED_BUCKET = "geo-synthetic-style-derived"


class _ReadOnlyVerifiedObjectStore:
    def __init__(self, reader: VerifiedRestoredObjectReader) -> None:
        self._reader = reader

    def get_s3_uri(
        self, *, uri: str, expected_hash: str | None = None
    ) -> RetrievedObject:
        if expected_hash is None:
            raise RuntimeError("backup source object checksum is required")
        content = self._reader(uri, expected_hash)
        bucket, key = parse_s3_uri(uri)
        return RetrievedObject(
            content=content,
            bucket=bucket,
            key=key,
            content_type="application/octet-stream",
            content_hash=hashlib.sha256(content).hexdigest(),
            etag=None,
        )

    def uri_for_key(self, key: str) -> Never:
        del key
        raise RuntimeError("backup source object adapter is read-only")

    def put_object(self, **kwargs: object) -> Never:
        del kwargs
        raise RuntimeError("backup source object adapter is read-only")

    def delete_s3_uri(self, *, uri: str) -> Never:
        del uri
        raise RuntimeError("backup source object adapter is read-only")


def run_source_probe(
    *,
    snapshot_id: str | None,
    object_root: Path | None = None,
    recommendation_object_root: Path | None = None,
    workflow_c_object_root: Path | None = None,
    synthetic_raw_object_root: Path | None = None,
    synthetic_derived_object_root: Path | None = None,
) -> dict[str, object]:
    if snapshot_id is not None and _SNAPSHOT.fullmatch(snapshot_id) is None:
        raise RuntimeError("backup snapshot identity is invalid")
    offline_roots = (
        object_root,
        recommendation_object_root,
        workflow_c_object_root,
        synthetic_raw_object_root,
        synthetic_derived_object_root,
    )
    if any(root is None for root in offline_roots) and any(
        root is not None for root in offline_roots
    ):
        raise RuntimeError("all offline backup object roots must be configured")
    database_url = secret_setting("GEO_DATABASE_URL")
    recommendation_cipher = EnvelopeCipher(
        load_master_keyring_from_docker_secret(
            _required_path("GEO_RECOMMENDATION_ARTIFACT_KEYRING_FILE")
        )
    )
    workflow_c_cipher = EnvelopeCipher(
        load_master_keyring_from_docker_secret(
            _required_path("GEO_WORKFLOW_C_ARTIFACT_KEYRING_FILE")
        )
    )
    synthetic_keyring = load_synthetic_artifact_keyring(
        _required_path("GEO_SYNTHETIC_ARTIFACT_KEYRING_FILE")
    )
    recommendation_objects: RecommendationTaskObjectStore
    workflow_c_store: WorkflowCManualArtifactObjectStore
    if object_root is None:
        recommendation_objects = _recommendation_object_store()
        workflow_c_store = _workflow_c_object_store()
        synthetic_reader = _synthetic_store_reader(
            build_object_store_from_prefix("GEO_SYNTHETIC_STYLE_RAW_OBJECT_STORE"),
            build_object_store_from_prefix("GEO_SYNTHETIC_STYLE_DERIVED_OBJECT_STORE"),
        )
    else:
        assert recommendation_object_root is not None
        assert workflow_c_object_root is not None
        assert synthetic_raw_object_root is not None
        assert synthetic_derived_object_root is not None
        recommendation_objects = _ReadOnlyVerifiedObjectStore(
            VerifiedRestoredObjectReader(
                root=recommendation_object_root,
                bucket=_RECOMMENDATION_BUCKET,
            )
        )
        workflow_c_store = _ReadOnlyVerifiedObjectStore(
            VerifiedRestoredObjectReader(
                root=workflow_c_object_root,
                bucket=_WORKFLOW_C_BUCKET,
            )
        )
        synthetic_reader = VerifiedRestoredObjectReaders(
            {
                _SYNTHETIC_RAW_BUCKET: VerifiedRestoredObjectReader(
                    root=synthetic_raw_object_root,
                    bucket=_SYNTHETIC_RAW_BUCKET,
                ),
                _SYNTHETIC_DERIVED_BUCKET: VerifiedRestoredObjectReader(
                    root=synthetic_derived_object_root,
                    bucket=_SYNTHETIC_DERIVED_BUCKET,
                ),
            }
        )
    recommendation_store = EncryptedRecommendationTaskArtifactStore(
        object_store=recommendation_objects,
        cipher=recommendation_cipher,
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if snapshot_id is not None:
            connection.execute(
                sql.SQL("SET TRANSACTION SNAPSHOT {}").format(sql.Literal(snapshot_id))
            )
        recommendation = verify_recommendation_artifact_restore(
            connection=connection,
            cipher=recommendation_cipher,
            artifacts=recommendation_store,
        )
        workflow_c = verify_workflow_c_artifact_restore(
            connection=connection,
            cipher=workflow_c_cipher,
            object_store=workflow_c_store,
        )

    def synthetic_connection() -> object:
        synthetic = psycopg.connect(database_url)
        synthetic.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if snapshot_id is not None:
            synthetic.execute(
                sql.SQL("SET TRANSACTION SNAPSHOT {}").format(sql.Literal(snapshot_id))
            )
        return synthetic

    synthetic = verify_synthetic_artifact_recovery(
        synthetic_connection,
        synthetic_keyring,
        object_reader=synthetic_reader,
    )
    return {
        "recommendation_artifacts": {
            "artifact_lineage_count": recommendation.artifact_lineage_count,
            "master_key_version_count": len(
                recommendation.verified_master_key_versions
            ),
            "representative_probe_target_count": (
                1 if recommendation.artifact_lineage_count else 0
            ),
            "source_verification_receipt_hash": (
                recommendation.verification_receipt_hash
            ),
        },
        "schema_version": PROBE_SCHEMA,
        "synthetic_artifacts": {
            "active_dek_count": synthetic.active_dek_count,
            "master_key_version_count": len(synthetic.verified_master_key_versions),
            "nondeleted_artifact_count": synthetic.nondeleted_artifact_count,
            "restricted_representative_verified": (
                synthetic.restricted_representative_verified
            ),
            "tier_key_artifact_count": synthetic.tier_key_artifact_count,
            "tier_representative_verified": synthetic.tier_representative_verified,
        },
        "workflow_c_artifacts": {
            "active_dek_count": workflow_c.active_dek_count,
            "master_key_version_count": len(workflow_c.verified_master_key_versions),
            "recoverable_artifact_count": workflow_c.recoverable_artifact_count,
            "representative_probe_target_count": (
                1 if workflow_c.recoverable_artifact_count else 0
            ),
            "source_verification_receipt_hash": workflow_c.verification_receipt_hash,
        },
    }


def _workflow_c_object_store() -> S3CompatibleObjectStore:
    bucket = os.getenv(
        "GEO_WORKFLOW_C_ARTIFACT_READER_BUCKET", _WORKFLOW_C_BUCKET
    ).strip()
    if bucket != _WORKFLOW_C_BUCKET:
        raise RuntimeError("Workflow C source probe bucket is invalid")
    return S3CompatibleObjectStore(
        endpoint=_required("GEO_WORKFLOW_C_ARTIFACT_READER_ENDPOINT"),
        bucket=bucket,
        access_key=secret_setting("GEO_WORKFLOW_C_ARTIFACT_READER_ACCESS_KEY"),
        secret_key=secret_setting("GEO_WORKFLOW_C_ARTIFACT_READER_SECRET_KEY"),
        region=os.getenv(
            "GEO_WORKFLOW_C_ARTIFACT_READER_REGION", "us-east-1"
        ).strip()
        or "us-east-1",
        auto_create_bucket=False,
    )


def _recommendation_object_store() -> S3CompatibleObjectStore:
    bucket = os.getenv(
        "GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE_BUCKET", _RECOMMENDATION_BUCKET
    ).strip()
    if bucket != _RECOMMENDATION_BUCKET:
        raise RuntimeError("Recommendation source probe bucket is invalid")
    return build_object_store_from_prefix("GEO_RECOMMENDATION_ARTIFACT_OBJECT_STORE")


def _synthetic_store_reader(
    raw: S3CompatibleObjectStore,
    derived: S3CompatibleObjectStore,
):
    if raw.bucket != _SYNTHETIC_RAW_BUCKET or derived.bucket != _SYNTHETIC_DERIVED_BUCKET:
        raise RuntimeError("Synthetic source probe bucket identity is invalid")
    stores = {raw.bucket: raw, derived.bucket: derived}

    def read(uri: str, expected_hash: str) -> bytes:
        bucket, _key = parse_s3_uri(uri)
        store = stores.get(bucket)
        if store is None:
            raise RuntimeError("Synthetic source probe URI is outside its backup buckets")
        return store.get_s3_uri(uri=uri, expected_hash=expected_hash).content

    return read


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _required_path(name: str) -> Path:
    return Path(_required(name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot")
    source.add_argument("--isolated-development-source", action="store_true")
    parser.add_argument("--object-root", type=Path)
    parser.add_argument("--recommendation-object-root", type=Path)
    parser.add_argument("--workflow-c-object-root", type=Path)
    parser.add_argument("--synthetic-raw-object-root", type=Path)
    parser.add_argument("--synthetic-derived-object-root", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run_source_probe(
            snapshot_id=None if args.isolated_development_source else args.snapshot,
            object_root=args.object_root,
            recommendation_object_root=args.recommendation_object_root,
            workflow_c_object_root=args.workflow_c_object_root,
            synthetic_raw_object_root=args.synthetic_raw_object_root,
            synthetic_derived_object_root=args.synthetic_derived_object_root,
        )
    except Exception as error:
        print("artifact backup source probe failed", file=sys.stderr)
        if os.getenv("GEO_RESTORE_GATE_DEBUG") == "1":
            sqlstate = getattr(error, "sqlstate", None)
            frames = traceback.extract_tb(error.__traceback__)[-2:]
            locations = ",".join(
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                for frame in frames
            )
            print(
                "artifact backup source probe debug: "
                f"error={type(error).__name__} sqlstate={sqlstate or '-'} "
                f"locations={locations or '-'}",
                file=sys.stderr,
            )
        return 2
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
