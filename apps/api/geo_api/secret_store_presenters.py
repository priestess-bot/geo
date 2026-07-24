"""Customer-proof presenters for Secret Store metadata only."""

from __future__ import annotations

from typing import cast

from geo_api.secret_store_contracts import (
    SecretAuditEventPage,
    SecretAuditEventResponse,
    SecretReferencePage,
    SecretReferenceResponse,
    SecretStatusValue,
    SecretVersionResponse,
)
from geo_api.secret_store_runtime import (
    SecretAuditPageRead,
    SecretAuditRead,
    SecretReferencePageRead,
    SecretReferenceRead,
    SecretVersionRead,
)


def version_response(item: SecretVersionRead) -> SecretVersionResponse:
    return SecretVersionResponse(
        reference_id=item.reference_id,
        version=item.version,
        status=cast(SecretStatusValue, item.status),
        aggregate_version=item.aggregate_version,
        master_key_version=item.master_key_version,
        fingerprint=item.fingerprint,
        created_at=item.created_at,
        verified_at=item.verified_at,
        activated_at=item.activated_at,
        revoked_at=item.revoked_at,
        replayed=item.replayed,
    )


def reference_response(item: SecretReferenceRead) -> SecretReferenceResponse:
    return SecretReferenceResponse(
        reference_id=item.reference_id,
        purpose=item.purpose,
        status=item.status,
        aggregate_version=item.aggregate_version,
        current_version=item.current_version,
        latest_version=item.latest_version,
        master_key_version=item.master_key_version,
        fingerprint=item.fingerprint,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def reference_page_response(item: SecretReferencePageRead) -> SecretReferencePage:
    return SecretReferencePage(
        items=[reference_response(value) for value in item.items],
        total=item.total,
        limit=item.limit,
        offset=item.offset,
    )


def audit_response(item: SecretAuditRead) -> SecretAuditEventResponse:
    return SecretAuditEventResponse(
        reference_id=item.reference_id,
        version=item.version,
        action=item.action,
        master_key_version=item.master_key_version,
        fingerprint=item.fingerprint,
        occurred_at=item.occurred_at,
    )


def audit_page_response(item: SecretAuditPageRead) -> SecretAuditEventPage:
    return SecretAuditEventPage(
        items=[audit_response(value) for value in item.items],
        total=item.total,
        limit=item.limit,
        offset=item.offset,
    )
