"""Strict PostgreSQL row mappings for Synthetic Lab persistence."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any
from uuid import UUID

from geo_core.jobs.lifecycle import DomainJobSpec, DurableJob, JobStatus
from geo_core.synthetic_lab.authorization import AuthorizationBinding, AuthorizationRecord
from geo_core.synthetic_lab.ports import (
    AuthorizationEnvelope,
    RuntimeInputSnapshot,
    SyntheticCommandIdentity,
    SyntheticCommandOperation,
    SyntheticCommandRecord,
    SyntheticJob,
    VersionedAggregate,
)
from geo_core.synthetic_lab.postgres_codec import decode_object, payload_hash


Row = Mapping[str, Any]

DOMAIN_TO_DURABLE_KIND = {
    "style_collection": "style.collect",
    "candidate_generation": "review.case.run",
    "candidate_revision": "candidate.revise",
    "corpus_finalize": "corpus.finalize",
    "offline_experiment": "offline_experiment.run",
    "style_profile_build": "style.profile.build",
}
DURABLE_TO_DOMAIN_KIND = {value: key for key, value in DOMAIN_TO_DURABLE_KIND.items()}


def command_from_row(row: Row) -> SyntheticCommandRecord:
    _verify_payload_hash(row, "result_payload", "result_payload_hash")
    return SyntheticCommandRecord(
        identity=SyntheticCommandIdentity(
            project_id=row["project_id"],
            idempotency_key_hash=row["idempotency_key_hash"],
            operation=SyntheticCommandOperation(row["operation"]),
            request_hash=row["request_hash"],
        ),
        result=decode_object(row["result_type"], row["result_payload"]),
    )


def aggregate_from_row(row: Row) -> VersionedAggregate:
    _verify_payload_hash(row, "payload", "payload_hash")
    return VersionedAggregate(
        project_id=row["project_id"],
        kind=row["kind"],
        resource_id=row["resource_id"],
        version=row["version"],
        submitted_by=row["submitted_by"],
        payload=decode_object(row["payload_type"], row["payload"]),
    )


def authorization_from_row(row: Row) -> AuthorizationEnvelope:
    return AuthorizationEnvelope(
        record=AuthorizationRecord(
            id=row["id"],
            project_id=row["project_id"],
            channel=row["channel"],
            adapter_release=row["adapter_release"],
            version_number=row["version_number"],
            previous_version_id=row["previous_version_id"],
            state=row["state"],
            evidence_reference_hash=row["evidence_reference_hash"],
            decided_by=row["decided_by"],
            decided_at=row["decided_at"],
            allowed_purposes=tuple(row["allowed_purposes"]),
            max_requests_per_period=row["max_requests_per_period"],
            period_seconds=row["period_seconds"],
            max_concurrency=row["max_concurrency"],
            expires_at=row["expires_at"],
            decision_reason=row["decision_reason"],
            record_hash=row["record_hash"],
        ),
        submitted_by=row["submitted_by"],
    )


def job_from_row(row: Row) -> SyntheticJob:
    domain_kind = row["domain_job_kind"]
    if DOMAIN_TO_DURABLE_KIND.get(domain_kind) != row["durable_kind"]:
        raise ValueError("stored Synthetic Lab Job kind compatibility mapping is invalid")
    payload = _job_payload_from_json(row["payload"])
    runtime = None
    if row["fact_snapshot_id"] is not None:
        runtime = RuntimeInputSnapshot(
            project_id=row["project_id"],
            fact_snapshot_id=row["fact_snapshot_id"],
            fact_snapshot_hash=row["fact_snapshot_hash"],
            profile_version_id=row["profile_version_id"],
            profile_hash=row["profile_hash"],
            prompt_release_id=row["prompt_release_id"],
            prompt_release_hash=row["prompt_release_hash"],
            facts_current_approved=row["facts_current_approved"],
            profile_frozen=row["profile_frozen"],
            prompt_frozen=row["prompt_frozen"],
        )
    authorization = None
    if row["authorization_id"] is not None:
        authorization = AuthorizationBinding(
            authorization_id=row["authorization_id"],
            project_id=row["project_id"],
            channel=row["authorization_channel"],
            adapter_release=row["authorization_adapter_release"],
            version_number=row["authorization_version"],
            authorization_hash=row["authorization_hash"],
            purpose=row["authorization_purpose"],
            expires_at=row["authorization_expires_at"],
        )
    return SyntheticJob(
        durable=DurableJob(
            id=row["job_id"],
            project_id=row["project_id"],
            spec=DomainJobSpec(kind=domain_kind, payload=MappingProxyType(payload)),
            input_hash=row["input_hash"],
            idempotency_key=row["idempotency_key"],
            status=JobStatus(row["status"]),
            priority=row["priority"],
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            next_run_at=row["next_run_at"],
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            heartbeat_at=row["heartbeat_at"],
            fencing_generation=row["fencing_generation"],
            cancel_requested_at=row["cancel_requested_at"],
            parent_job_id=row["parent_job_id"],
            replay_nonce=row["replay_nonce"],
            result_ref=row["result_ref"],
            error_code=row["error_code"],
        ),
        runtime_inputs=runtime,
        authorization_binding=authorization,
        version=row["metadata_version"],
    )


def job_payload_to_json(payload: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, tuple):
            result[key] = [str(item) for item in value]
        else:
            result[key] = str(value)
    return result


def _job_payload_from_json(payload: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in payload.items():
        if key.endswith("_id"):
            result[key] = UUID(str(value))
        elif key.endswith("_ids"):
            if not isinstance(value, list):
                raise ValueError("stored Synthetic Lab ID list is invalid")
            result[key] = tuple(UUID(str(item)) for item in value)
        elif key.endswith("_hash"):
            result[key] = str(value)
        elif key.endswith("_hashes"):
            if not isinstance(value, list):
                raise ValueError("stored Synthetic Lab hash list is invalid")
            result[key] = tuple(str(item) for item in value)
        else:
            raise ValueError("stored Synthetic Lab Job payload key is invalid")
    return result


def _verify_payload_hash(row: Row, payload_key: str, hash_key: str) -> None:
    if payload_hash(row[payload_key]) != row[hash_key]:
        raise ValueError("stored Synthetic Lab JSON payload hash is invalid")


__all__ = [
    "DOMAIN_TO_DURABLE_KIND",
    "DURABLE_TO_DOMAIN_KIND",
    "aggregate_from_row",
    "authorization_from_row",
    "command_from_row",
    "job_from_row",
    "job_payload_to_json",
]
