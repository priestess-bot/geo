from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from geo_core.object_store import ObjectStoreError, S3CompatibleObjectStore
from geo_core.runtime import RuntimePersistenceError, build_object_store_from_env
from scripts.verify_production_object_store import (
    APPLICATION_CONSUMERS,
    BASE_COMPOSE,
    PRODUCTION_COMPOSE,
    ProductionObjectStoreVerificationError,
    _config_only_env,
    build_full_artifact,
    load_merged_compose,
    validate_backup_receipt,
    validate_consumer_receipt,
    validate_encryption_receipt,
    validate_snapshot_receipt,
    verify_merged_compose,
)


ROOT = Path(__file__).resolve().parents[1]


class ProductionObjectStoreClientTests(unittest.TestCase):
    def test_production_put_uses_head_bucket_and_never_put_bucket(self) -> None:
        requests: list[tuple[str, str, bytes]] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append((method, url, body))
            if method == "HEAD" and url.endswith("/geo-reports"):
                return 200, {}, b""
            if method == "PUT" and url.endswith("/ready/object.txt"):
                return 200, {"ETag": '"ready"'}, b""
            return 404, {}, b"missing"

        store = S3CompatibleObjectStore(
            endpoint="http://minio:9000",
            bucket="geo-reports",
            access_key="application-user",
            secret_key="application-secret",
            auto_create_bucket=False,
            requester=requester,
        )
        stored = store.put_object(
            key="ready/object.txt",
            content=b"ready",
            content_type="text/plain",
        )

        self.assertEqual(stored.content_hash, hashlib.sha256(b"ready").hexdigest())
        self.assertEqual([request[0] for request in requests], ["HEAD", "PUT"])
        self.assertFalse(
            any(method == "PUT" and url.endswith("/geo-reports") for method, url, _ in requests)
        )

    def test_failed_head_bucket_prevents_object_upload(self) -> None:
        requests: list[str] = []

        def requester(
            method: str,
            url: str,
            headers: object,
            body: bytes,
        ) -> tuple[int, dict[str, str], bytes]:
            requests.append(method)
            return 403, {}, b"denied"

        store = S3CompatibleObjectStore(
            endpoint="http://minio:9000",
            bucket="geo-reports",
            access_key="application-user",
            secret_key="application-secret",
            auto_create_bucket=False,
            requester=requester,
        )
        with self.assertRaisesRegex(ObjectStoreError, "readiness HEAD failed"):
            store.put_object(key="blocked.txt", content=b"blocked", content_type="text/plain")
        self.assertEqual(requests, ["HEAD"])

    def test_builder_reads_file_secrets_and_strict_false_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            access_path = Path(directory) / "access"
            secret_path = Path(directory) / "secret"
            access_path.write_text("application-user\n", encoding="utf-8")
            secret_path.write_text("application-secret\n", encoding="utf-8")
            store = build_object_store_from_env(
                {
                    "OBJECT_STORE_ENDPOINT": "http://minio:9000",
                    "OBJECT_STORE_BUCKET": "geo-reports",
                    "OBJECT_STORE_ACCESS_KEY_FILE": str(access_path),
                    "OBJECT_STORE_SECRET_KEY_FILE": str(secret_path),
                    "OBJECT_STORE_AUTO_CREATE_BUCKET": "false",
                }
            )

        self.assertEqual(store.access_key, "application-user")
        self.assertEqual(store.secret_key, "application-secret")
        self.assertFalse(store.auto_create_bucket)

    def test_builder_rejects_ambiguous_secret_and_invalid_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            access_path = Path(directory) / "access"
            access_path.write_text("file-user\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimePersistenceError, "cannot both be configured"):
                build_object_store_from_env(
                    {
                        "OBJECT_STORE_ENDPOINT": "http://minio:9000",
                        "OBJECT_STORE_ACCESS_KEY": "direct-user",
                        "OBJECT_STORE_ACCESS_KEY_FILE": str(access_path),
                        "OBJECT_STORE_SECRET_KEY": "secret",
                    }
                )
        with self.assertRaisesRegex(RuntimePersistenceError, "must be one of"):
            build_object_store_from_env(
                {
                    "OBJECT_STORE_ENDPOINT": "http://minio:9000",
                    "OBJECT_STORE_ACCESS_KEY": "application-user",
                    "OBJECT_STORE_SECRET_KEY": "application-secret",
                    "OBJECT_STORE_AUTO_CREATE_BUCKET": "sometimes",
                }
            )


class ProductionObjectStoreComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_merged_compose(config_only=True)

    def test_all_profiles_merged_compose_contract(self) -> None:
        checks = verify_merged_compose(self.config)
        names = {check["name"] for check in checks}
        self.assertIn("consumer_inventory_exact", names)
        self.assertIn("consumer_caller_inventory_exact", names)
        self.assertIn("root_identity_visibility", names)
        self.assertIn("no_development_object_store_credentials", names)
        self.assertIn("external_encrypted_volume_contract", names)

    def test_consumer_inventory_is_exact_and_non_consumers_have_no_secret(self) -> None:
        services = self.config["services"]
        mounted_application = {
            name
            for name, service in services.items()
            if {item.get("source") for item in service.get("secrets", []) if isinstance(item, dict)}
            & {"object_store_application_access_key", "object_store_application_secret_key"}
        }
        self.assertEqual(mounted_application, set(APPLICATION_CONSUMERS) | {"minio-bootstrap"})
        for name in (
            "admin-web",
            "customer-web",
            "dashboard-web",
            "knowledge-embedding-api",
            "report-pdf-renderer",
            "task-recovery-dispatcher",
            "notification-delivery-worker",
        ):
            environment = services[name].get("environment", {})
            self.assertFalse(
                any(key.startswith("OBJECT_STORE_") and "KEY" in key for key in environment)
            )

    def test_missing_required_secret_file_variable_fails_compose_preflight(self) -> None:
        env = _config_only_env()
        env.pop("GEO_OBJECT_STORE_BACKUP_SECRET_KEY_SECRET_FILE")
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--profile",
                "*",
                "-f",
                str(BASE_COMPOSE),
                "-f",
                str(PRODUCTION_COMPOSE),
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GEO_OBJECT_STORE_BACKUP_SECRET_KEY_SECRET_FILE", result.stderr)

    def test_backup_smoke_does_not_create_bucket_or_delete_source(self) -> None:
        smoke = (ROOT / "infra/minio/backup-restore-smoke.sh").read_text(encoding="utf-8")
        bootstrap = (ROOT / "infra/minio/bootstrap.sh").read_text(encoding="utf-8")
        self.assertNotIn("mc mb --ignore-existing", smoke)
        self.assertNotIn('mc rm "backup/$source_bucket/', smoke)
        self.assertIn("mc mb --ignore-existing", bootstrap)
        self.assertIn("formal_backup_delete_denied", smoke)
        self.assertIn("cross_run_delete_denied", smoke)

    def test_policy_only_receipt_is_explicitly_shared_identity(self) -> None:
        smoke = (ROOT / "infra/minio/application-roundtrip-smoke.sh").read_text(encoding="utf-8")
        self.assertIn("production-object-store-shared-identity-roundtrip-v1", smoke)
        self.assertIn("shared_identity_policy_only", smoke)
        self.assertNotIn("consumer_roundtrips", smoke)
        for service_name in APPLICATION_CONSUMERS:
            self.assertNotIn(service_name, smoke)


class ProductionObjectStoreReceiptTests(unittest.TestCase):
    def test_full_verifier_rejects_shared_identity_receipt(self) -> None:
        shared_receipt = {
            "schema_version": "production-object-store-shared-identity-roundtrip-v1",
            "verification_scope": "shared_identity_policy_only",
            "credential_fingerprint": "a" * 64,
            "consumer_roundtrips": {},
            "verified_at": "2026-07-12T08:00:00Z",
        }
        with self.assertRaisesRegex(ProductionObjectStoreVerificationError, "shared-identity"):
            validate_consumer_receipt(shared_receipt)

    def test_encryption_and_snapshot_receipts_are_behavioral(self) -> None:
        encryption = {
            "volume_id": "vol-encrypted-1",
            "provider": "test-platform",
            "encryption_enabled": True,
            "key_alias": "alias/geo-minio-production",
            "policy_version": "encrypted-volume-v1",
            "rotation_owner": "security-platform",
            "recovery_owner": "platform-oncall",
            "verified_at": "2026-07-12T08:00:00Z",
        }
        snapshot = {
            "snapshot_id": "snap-1",
            "source_volume_id": "vol-encrypted-1",
            "new_node_id": "node-restore-2",
            "new_volume_id": "vol-restored-2",
            "restored_object_hash": "a" * 64,
            "verified_at": "2026-07-12T08:30:00Z",
        }
        validate_encryption_receipt(encryption)
        validate_snapshot_receipt(snapshot)

        encryption["encryption_enabled"] = False
        with self.assertRaisesRegex(ProductionObjectStoreVerificationError, "must be true"):
            validate_encryption_receipt(encryption)
        snapshot["new_volume_id"] = snapshot["source_volume_id"]
        with self.assertRaisesRegex(ProductionObjectStoreVerificationError, "new volume"):
            validate_snapshot_receipt(snapshot)

    def test_backup_receipt_requires_equal_hashes_and_all_negative_checks(self) -> None:
        receipt = {
            "schema_version": "production-object-store-backup-restore-v1",
            "source_sha256": "b" * 64,
            "backup_sha256": "b" * 64,
            "formal_backup_sha256": "b" * 64,
            "restored_sha256": "b" * 64,
            "formal_backup_put_list_get": True,
            "negative_checks": {
                "create_bucket_denied": True,
                "source_write_denied": True,
                "formal_backup_delete_denied": True,
                "cross_run_delete_denied": True,
                "restore_cross_run_write_denied": True,
            },
            "source_object_deleted": False,
            "smoke_cleanup_completed": True,
            "verified_at": "2026-07-12T08:00:00Z",
        }
        validate_backup_receipt(receipt)
        receipt["restored_sha256"] = "c" * 64
        with self.assertRaisesRegex(ProductionObjectStoreVerificationError, "hash mismatch"):
            validate_backup_receipt(receipt)

    def test_full_artifact_contains_only_fingerprint_and_receipt_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret_values = {
                "minio_root_user": "root-production-user",
                "minio_root_password": "root-production-password",
                "object_store_application_access_key": "application-production-user",
                "object_store_application_secret_key": "application-production-password",
                "object_store_backup_access_key": "backup-production-user",
                "object_store_backup_secret_key": "backup-production-password",
                "object_store_restore_access_key": "restore-production-user",
                "object_store_restore_secret_key": "restore-production-password",
                "object_store_retention_access_key": "retention-production-user",
                "object_store_retention_secret_key": "retention-production-password",
            }
            env = _config_only_env()
            variable_names = {
                "minio_root_user": "GEO_MINIO_ROOT_USER_SECRET_FILE",
                "minio_root_password": "GEO_MINIO_ROOT_PASSWORD_SECRET_FILE",
                "object_store_application_access_key": "GEO_OBJECT_STORE_APPLICATION_ACCESS_KEY_SECRET_FILE",
                "object_store_application_secret_key": "GEO_OBJECT_STORE_APPLICATION_SECRET_KEY_SECRET_FILE",
                "object_store_backup_access_key": "GEO_OBJECT_STORE_BACKUP_ACCESS_KEY_SECRET_FILE",
                "object_store_backup_secret_key": "GEO_OBJECT_STORE_BACKUP_SECRET_KEY_SECRET_FILE",
                "object_store_restore_access_key": "GEO_OBJECT_STORE_RESTORE_ACCESS_KEY_SECRET_FILE",
                "object_store_restore_secret_key": "GEO_OBJECT_STORE_RESTORE_SECRET_KEY_SECRET_FILE",
                "object_store_retention_access_key": "GEO_OBJECT_STORE_RETENTION_ACCESS_KEY_SECRET_FILE",
                "object_store_retention_secret_key": "GEO_OBJECT_STORE_RETENTION_SECRET_KEY_SECRET_FILE",
            }
            for name, value in secret_values.items():
                path = root / name
                path.write_text(value, encoding="utf-8")
                path.chmod(0o600)
                env[variable_names[name]] = str(path)

            application_fingerprint = hashlib.sha256(
                secret_values["object_store_application_access_key"].encode()
            ).hexdigest()
            receipt_payloads = {
                "bootstrap": {
                    "schema_version": "production-object-store-bootstrap-v1",
                    "policy_version": "geo-object-store-policy-v1",
                    "reports_bucket": "geo-reports",
                    "backup_bucket": "geo-backups",
                    "policy_hashes": {
                        "application": "1" * 64,
                        "backup": "2" * 64,
                        "restore": "3" * 64,
                        "retention": "4" * 64,
                    },
                    "application_readiness_sha256": "5" * 64,
                    "application_delete_denied": True,
                    "application_create_bucket_denied": True,
                    "application_cross_bucket_denied": True,
                    "application_admin_denied": True,
                    "verified_at": "2026-07-12T08:00:00Z",
                },
                "backup_restore": {
                    "schema_version": "production-object-store-backup-restore-v1",
                    "source_sha256": "6" * 64,
                    "backup_sha256": "6" * 64,
                    "formal_backup_sha256": "6" * 64,
                    "restored_sha256": "6" * 64,
                    "formal_backup_put_list_get": True,
                    "negative_checks": {
                        "create_bucket_denied": True,
                        "source_write_denied": True,
                        "formal_backup_delete_denied": True,
                        "cross_run_delete_denied": True,
                        "restore_cross_run_write_denied": True,
                    },
                    "source_object_deleted": False,
                    "smoke_cleanup_completed": True,
                    "verified_at": "2026-07-12T08:10:00Z",
                },
                "consumer_roundtrip": {
                    "schema_version": "production-object-store-consumer-roundtrip-v1",
                    "verification_scope": "compose_service_native_builder",
                    "credential_fingerprint": application_fingerprint,
                    "consumer_roundtrips": {
                        name: {
                            "status": "pass",
                            "service_name": name,
                            "container_id": f"container-{index}",
                            "sha256": "7" * 64,
                            "credential_fingerprint": application_fingerprint,
                            "execution_path": "geo_core.runtime.build_object_store_from_env",
                            "credential_source": "OBJECT_STORE_ACCESS_KEY_FILE",
                            "auto_create_bucket": False,
                        }
                        for index, name in enumerate(APPLICATION_CONSUMERS)
                    },
                    "verified_at": "2026-07-12T08:20:00Z",
                },
                "ephemeral_cleanup": {
                    "schema_version": "production-object-store-ephemeral-cleanup-v1",
                    "restore_principal_revoked": True,
                    "retention_principal_revoked": True,
                    "verified_at": "2026-07-12T08:25:00Z",
                },
                "encryption_volume": {
                    "volume_id": "volume-1",
                    "provider": "test-platform",
                    "encryption_enabled": True,
                    "key_alias": "alias/geo",
                    "policy_version": "encrypted-volume-v1",
                    "rotation_owner": "security-platform",
                    "recovery_owner": "platform-oncall",
                    "verified_at": "2026-07-12T08:30:00Z",
                },
                "snapshot_restore": {
                    "snapshot_id": "snapshot-1",
                    "source_volume_id": "volume-1",
                    "new_node_id": "node-2",
                    "new_volume_id": "volume-2",
                    "restored_object_hash": "8" * 64,
                    "verified_at": "2026-07-12T08:40:00Z",
                },
            }
            paths: dict[str, Path] = {}
            for name, payload in receipt_payloads.items():
                path = root / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths[name] = path

            args = argparse.Namespace(
                bootstrap_receipt=str(paths["bootstrap"]),
                backup_restore_receipt=str(paths["backup_restore"]),
                consumer_roundtrip_receipt=str(paths["consumer_roundtrip"]),
                ephemeral_cleanup_receipt=str(paths["ephemeral_cleanup"]),
                encryption_volume_receipt=str(paths["encryption_volume"]),
                snapshot_restore_receipt=str(paths["snapshot_restore"]),
                started_at="2026-07-12T08:00:00Z",
                run_id="unit-test-run",
                environment="test",
            )
            with patch.dict(os.environ, env, clear=True):
                config = load_merged_compose(config_only=False)
                artifact = build_full_artifact(args, config, verify_merged_compose(config))

        serialized = json.dumps(artifact, sort_keys=True)
        self.assertEqual(artifact["secret_leak_count"], 0)
        self.assertEqual(artifact["credential_fingerprint"], application_fingerprint)
        self.assertTrue(all(value not in serialized for value in secret_values.values()))


if __name__ == "__main__":
    unittest.main()
