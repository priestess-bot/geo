"""Worker-only PostgreSQL recovery of committed encrypted derived artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import psycopg

from geo_core.model_gateway.artifact_recovery import (
    ProviderArtifactRecoveryRequest,
    RecoveredProviderArtifact,
    RecoveredProviderArtifactBundle,
)
from geo_core.model_gateway.identity import canonical_json_hash
from geo_core.model_gateway.postgres_artifacts import decrypt_provider_artifact_dek
from geo_core.model_gateway.provider_adapters.artifacts import (
    ProviderArtifactError,
    ProviderArtifactObjectStore,
    decrypt_provider_artifact_payload,
    provider_artifact_associated_data,
)
from geo_core.model_gateway.schema_validation import validate_structured_output
from geo_core.project_scope import set_project_scope
from geo_core.secrets import EnvelopeCipher


class PostgresProviderArtifactRecovery:
    """Recover output only for an exact successful Attempt and current worker fence."""

    def __init__(
        self,
        *,
        connect: Callable[[], Any],
        cipher: EnvelopeCipher,
        object_store: ProviderArtifactObjectStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._connect = connect
        self._cipher = cipher
        self._object_store = object_store
        self._clock = clock

    def __repr__(self) -> str:
        return "PostgresProviderArtifactRecovery([REDACTED])"

    def recover_derived(
        self, request: ProviderArtifactRecoveryRequest
    ) -> RecoveredProviderArtifact:
        recovered_at = self._clock()
        if recovered_at.tzinfo is None or recovered_at.utcoffset() is None:
            raise ProviderArtifactError("Provider artifact recovery clock is invalid")
        row = self._load_artifact(request, recovered_at=recovered_at)
        output = self._decrypt_and_validate(request, row)
        receipt = self._record_receipt(
            request,
            row,
            recovered_at=recovered_at,
        )
        return RecoveredProviderArtifact(
            model_call_attempt_id=request.model_call_attempt_id,
            artifact_id=row["artifact_id"],
            manifest_hash=row["manifest_hash"],
            content_hash=row["content_hash"],
            output_hash=request.expected_output_hash,
            output=output,
            recovery_receipt_id=receipt["id"],
            recovery_receipt_hash=receipt["receipt_hash"],
            recovered_at=receipt["recovered_at"],
            bundle_lineage=RecoveredProviderArtifactBundle(
                raw_manifest_reference=row["raw_manifest_uri"],
                raw_manifest_hash=row["raw_manifest_hash"],
                raw_content_hash=row["raw_content_hash"],
                raw_byte_size=row["raw_content_byte_size"],
                derived_manifest_reference=row["manifest_uri"],
                derived_manifest_hash=row["manifest_hash"],
                derived_content_hash=row["content_hash"],
                derived_byte_size=row["content_byte_size"],
                data_policy_hash=row["data_policy_hash"],
                storage_decision=row["storage_decision"],
                cache_decision=row["cache_decision"],
                display_decision=row["display_decision"],
                redistribution_decision=row["redistribution_decision"],
                retention_days=row["retention_days"],
            ),
        )

    def _load_artifact(
        self,
        request: ProviderArtifactRecoveryRequest,
        *,
        recovered_at: datetime,
    ) -> Mapping[str, Any]:
        try:
            with self._connect() as connection:
                set_project_scope(connection, request.project_id)
                row = connection.execute(
                    """SELECT artifact.*, bundle.job_id, bundle.attempt_id,
                              bundle.provider, bundle.adapter_release_id,
                              bundle.adapter_release_hash,
                              bundle.data_policy_hash, bundle.storage_decision,
                              bundle.cache_decision, bundle.display_decision,
                              bundle.redistribution_decision, bundle.retention_days,
                              bundle.usage_purpose, bundle.audience,
                              bundle.status AS bundle_status,
                              raw.manifest_uri AS raw_manifest_uri,
                              raw.manifest_hash AS raw_manifest_hash,
                              raw.content_hash AS raw_content_hash,
                              raw.content_byte_size AS raw_content_byte_size,
                              attempt.output_schema_hash,
                              attempt.application_output_schema_hash,
                              terminal.output_hash AS terminal_output_hash,
                              source_job.parent_job_id AS source_parent_job_id,
                              dek.ciphertext, dek.data_nonce, dek.wrapped_data_key,
                              dek.wrap_nonce, dek.master_key_version, dek.algorithm,
                              dek.created_at, dek.status AS dek_status
                       FROM model_gateway_artifacts AS artifact
                       JOIN model_gateway_artifact_bundles AS bundle
                         ON bundle.id = artifact.bundle_id
                        AND bundle.project_id = artifact.project_id
                       JOIN model_gateway_artifact_deks AS dek
                         ON dek.key_ref = artifact.key_ref
                        AND dek.project_id = artifact.project_id
                        AND dek.artifact_id = artifact.artifact_id
                       JOIN model_gateway_artifacts AS raw
                         ON raw.bundle_id = artifact.bundle_id
                        AND raw.project_id = artifact.project_id
                        AND raw.kind = 'raw'
                       JOIN model_gateway_call_attempts AS attempt
                         ON attempt.id = bundle.attempt_id
                        AND attempt.project_id = bundle.project_id
                       JOIN model_gateway_terminal_events AS terminal
                         ON terminal.attempt_id = attempt.id
                        AND terminal.project_id = attempt.project_id
                       JOIN durable_jobs AS source_job
                         ON source_job.id = bundle.job_id
                        AND source_job.project_id = bundle.project_id
                       WHERE artifact.project_id = %s
                         AND artifact.kind = 'derived'
                         AND attempt.id = %s
                         AND terminal.status = 'succeeded'
                         AND terminal.output_hash = %s""",
                    (
                        request.project_id,
                        request.model_call_attempt_id,
                        request.expected_output_hash,
                    ),
                ).fetchone()
                analysis_authorized = False
                if row is not None:
                    _validate_current_fence(connection, request, recovered_at)
                    if (
                        request.source_model_job_id != request.recovery_job_id
                        and row["source_parent_job_id"] != request.recovery_job_id
                    ):
                        analysis_authorized = _analysis_recovery_authorized(
                            connection, request, row
                        )
        except psycopg.Error as exc:
            raise ProviderArtifactError(
                "Provider artifact recovery metadata is unavailable"
            ) from exc
        if row is None:
            raise ProviderArtifactError("Provider artifact recovery lineage is unavailable")
        mismatches = (
            row["job_id"] != request.source_model_job_id,
            (
                request.source_model_job_id != request.recovery_job_id
                and row["source_parent_job_id"] != request.recovery_job_id
                and not analysis_authorized
            ),
            row["attempt_id"] != request.model_call_attempt_id,
            row["bundle_status"] != "committed",
            row["storage_decision"] != "allowed",
            row["dek_status"] != "active",
            row["usage_purpose"] != request.purpose,
            row["audience"] != "internal_worker",
            row["output_schema_hash"] != request.output_schema_hash,
            row["application_output_schema_hash"]
            != request.application_output_schema_hash,
            row["terminal_output_hash"] != request.expected_output_hash,
            row["content_hash"] != request.expected_output_hash,
            row["expires_at"] is not None and row["expires_at"] <= recovered_at,
        )
        if any(mismatches):
            raise ProviderArtifactError("Provider artifact recovery lineage is inconsistent")
        return row

    def _decrypt_and_validate(
        self,
        request: ProviderArtifactRecoveryRequest,
        row: Mapping[str, Any],
    ) -> Mapping[str, object]:
        key_material = bytearray()
        plaintext = bytearray()
        try:
            manifest_object = self._object_store.get_s3_uri(
                uri=str(row["manifest_uri"]),
                expected_hash=str(row["manifest_hash"]),
            )
            payload_object = self._object_store.get_s3_uri(
                uri=str(row["payload_uri"]),
                expected_hash=str(row["payload_hash"]),
            )
            _validate_manifest(row, manifest_object.content)
            key_material = decrypt_provider_artifact_dek(self._cipher, row)
            plaintext = decrypt_provider_artifact_payload(
                encrypted_payload=payload_object.content,
                key_material=key_material,
                associated_data=provider_artifact_associated_data(
                    project_id=request.project_id,
                    provider=str(row["provider"]),
                    kind="derived",
                    content_hash=str(row["content_hash"]),
                    adapter_release_hash=str(row["adapter_release_hash"]),
                ),
            )
            if not hmac.compare_digest(
                hashlib.sha256(plaintext).hexdigest(), str(row["content_hash"])
            ):
                raise ProviderArtifactError("Provider artifact recovered content hash is invalid")
            decoded = json.loads(plaintext)
            if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
                raise ProviderArtifactError("Provider artifact recovered output is not an object")
            validate_structured_output(decoded, request.application_output_schema)
            if not hmac.compare_digest(canonical_json_hash(decoded), request.expected_output_hash):
                raise ProviderArtifactError("Provider artifact recovered output hash is invalid")
            return decoded
        except ProviderArtifactError:
            raise
        except Exception as exc:
            raise ProviderArtifactError("Provider artifact recovery validation failed") from exc
        finally:
            _wipe(key_material)
            _wipe(plaintext)

    def _record_receipt(
        self,
        request: ProviderArtifactRecoveryRequest,
        row: Mapping[str, Any],
        *,
        recovered_at: datetime,
    ) -> Mapping[str, Any]:
        receipt_id = uuid5(
            NAMESPACE_URL,
            ":".join(
                (
                    "geo-provider-artifact-recovery",
                    str(request.project_id),
                    str(request.source_model_job_id),
                    str(request.recovery_job_id),
                    str(request.model_call_attempt_id),
                    str(row["artifact_id"]),
                    request.purpose,
                )
            ),
        )
        try:
            with self._connect() as connection:
                set_project_scope(connection, request.project_id)
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"provider-artifact-recovery:{receipt_id}",),
                )
                existing = connection.execute(
                    """SELECT * FROM model_gateway_artifact_recovery_receipts
                       WHERE project_id = %s AND id = %s""",
                    (request.project_id, receipt_id),
                ).fetchone()
                if existing is not None:
                    _validate_existing_receipt(request, row, existing)
                    _validate_current_fence(connection, request, recovered_at)
                    return existing
                receipt_hash = canonical_json_hash(
                    {
                        "schema_version": 1,
                        "id": receipt_id,
                        "project_id": request.project_id,
                        "recovery_job_id": request.recovery_job_id,
                        "source_model_job_id": request.source_model_job_id,
                        "model_call_attempt_id": request.model_call_attempt_id,
                        "artifact_id": row["artifact_id"],
                        "manifest_hash": row["manifest_hash"],
                        "expected_output_hash": request.expected_output_hash,
                        "recovered_output_hash": request.expected_output_hash,
                        "purpose": request.purpose,
                        "audience": "internal_worker",
                        "lease_token": request.lease_token,
                        "fencing_generation": request.fencing_generation,
                        "recovered_at": recovered_at,
                    }
                )
                return connection.execute(
                    """INSERT INTO model_gateway_artifact_recovery_receipts(
                           id, project_id, source_model_job_id, recovery_job_id,
                           model_call_attempt_id,
                           artifact_id, manifest_hash, expected_output_hash,
                           recovered_output_hash, purpose, audience, lease_token,
                           fencing_generation, receipt_hash, recovered_at
                       ) VALUES (
                           %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, 'internal_worker', %s, %s, %s, %s
                       ) RETURNING *""",
                    (
                        receipt_id,
                        request.project_id,
                        request.source_model_job_id,
                        request.recovery_job_id,
                        request.model_call_attempt_id,
                        row["artifact_id"],
                        row["manifest_hash"],
                        request.expected_output_hash,
                        request.expected_output_hash,
                        request.purpose,
                        request.lease_token,
                        request.fencing_generation,
                        receipt_hash,
                        recovered_at,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise ProviderArtifactError(
                "Provider artifact recovery receipt could not be committed"
            ) from exc


def _validate_manifest(row: Mapping[str, Any], content: bytes) -> None:
    try:
        manifest = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderArtifactError("Provider artifact manifest is invalid") from exc
    expected = {
        "project_id": str(row["project_id"]),
        "artifact_id": str(row["artifact_id"]),
        "kind": "derived",
        "provider": row["provider"],
        "adapter_release_id": row["adapter_release_id"],
        "adapter_release_hash": row["adapter_release_hash"],
        "persisted_content_hash": row["content_hash"],
        "stored_object_hash": row["payload_hash"],
        "payload_uri": row["payload_uri"],
        "encryption_algorithm": row["encryption_algorithm"],
        "key_reference": str(row["key_ref"]),
        "usage_purpose": row["usage_purpose"],
        "usage_audience": row["audience"],
    }
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or any(manifest.get(key) != value for key, value in expected.items())
    ):
        raise ProviderArtifactError("Provider artifact manifest lineage is invalid")


def _validate_existing_receipt(
    request: ProviderArtifactRecoveryRequest,
    row: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    if (
        receipt["source_model_job_id"] != request.source_model_job_id
        or receipt["recovery_job_id"] != request.recovery_job_id
        or receipt["model_call_attempt_id"] != request.model_call_attempt_id
        or receipt["artifact_id"] != row["artifact_id"]
        or receipt["manifest_hash"] != row["manifest_hash"]
        or receipt["expected_output_hash"] != request.expected_output_hash
        or receipt["recovered_output_hash"] != request.expected_output_hash
        or receipt["purpose"] != request.purpose
        or receipt["audience"] != "internal_worker"
    ):
        raise ProviderArtifactError("Provider artifact recovery receipt identity conflicts")


def _validate_current_fence(
    connection: Any,
    request: ProviderArtifactRecoveryRequest,
    recovered_at: datetime,
) -> None:
    row = connection.execute(
        """SELECT status, lease_token, fencing_generation, lease_expires_at,
                  cancel_requested_at
           FROM durable_jobs WHERE project_id = %s AND id = %s FOR UPDATE""",
        (request.project_id, request.recovery_job_id),
    ).fetchone()
    if (
        row is None
        or row["status"] not in {"running", "finalizing"}
        or row["lease_token"] != request.lease_token
        or row["fencing_generation"] != request.fencing_generation
        or row["lease_expires_at"] is None
        or row["lease_expires_at"] <= recovered_at
        or row["cancel_requested_at"] is not None
    ):
        raise ProviderArtifactError("Provider artifact recovery lease is stale")


def _analysis_recovery_authorized(
    connection: Any,
    request: ProviderArtifactRecoveryRequest,
    artifact: Mapping[str, Any],
) -> bool:
    """Authorize only an exact immutable semantic-manifest membership.

    Sampling retries and parent/child model workflows retain their existing
    identity rule. Cross-Job recovery is admitted solely when the current
    semantic v2 Job points at a frozen manifest item that names every source
    and artifact hash being decrypted.
    """

    if request.source_model_job_id == request.recovery_job_id:
        return False
    row = connection.execute(
        """SELECT EXISTS (
               SELECT 1
                 FROM durable_jobs AS recovery
                 JOIN workflow_c_job_specs AS analysis_spec
                   ON analysis_spec.project_id = recovery.project_id
                  AND analysis_spec.job_id = recovery.id
                 JOIN workflow_c_analysis_input_manifests AS manifest
                   ON manifest.project_id = recovery.project_id
                  AND manifest.id =
                      (analysis_spec.spec_payload->'semantic_metrics'->>'manifest_id')::uuid
                 JOIN workflow_c_analysis_input_manifest_items AS member
                   ON member.project_id = manifest.project_id
                  AND member.manifest_id = manifest.id
                WHERE recovery.project_id = %s
                  AND recovery.id = %s
                  AND recovery.kind = 'workflow_c.analysis.semantic_metrics'
                  AND analysis_spec.kind = recovery.kind
                  AND analysis_spec.spec_payload->'schema_version' = '2'::jsonb
                  AND analysis_spec.spec_payload->>'kind' = recovery.kind
                  AND analysis_spec.spec_payload->'semantic_metrics'->>'manifest_hash'
                      = manifest.manifest_hash
                  AND member.artifact_kind = 'provider'
                  AND member.source_job_id = %s
                  AND member.provider_model_attempt_id = %s
                  AND member.output_hash = %s
                  AND member.artifact_manifest_hash = %s
                  AND member.artifact_content_hash = %s
           ) AS authorized""",
        (
            request.project_id,
            request.recovery_job_id,
            request.source_model_job_id,
            request.model_call_attempt_id,
            request.expected_output_hash,
            artifact["manifest_hash"],
            artifact["content_hash"],
        ),
    ).fetchone()
    return bool(row is not None and row["authorized"])


def _wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


__all__ = ["PostgresProviderArtifactRecovery"]
