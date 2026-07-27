#!/usr/bin/env python3
"""Import one mounted DeepSeek key into Secret Store and enable Prompt tests.

This is an operator bootstrap for the existing ``GEO_DEEPSEEK_API_KEY_FILE``.
It never serializes or prints the key.  The resulting runtime is deliberately
limited to ``prompt_release_test`` with non-search JSON responses.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg

from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.model_gateway.runtime_catalog import register_runtime_manifest
from geo_core.model_gateway.runtime_manifest import parse_runtime_manifest
from geo_core.object_store import S3CompatibleObjectStore
from geo_core.object_store_config import build_object_store
from geo_core.project_scope import set_project_scope
from geo_core.prompts.test_runtime_selector import (
    PROMPT_TEST_MODEL_PURPOSE,
    PROMPT_TEST_SEARCH_MODE,
)
from geo_core.secrets import SecretNotFound, SecretValue, SecretVersionHandle
from geo_core.secrets.postgres import build_secret_store_api


PROVIDER = "deepseek"
DEFAULT_MODEL = "deepseek-v4-flash"
ADAPTER_RELEASE_ID = "deepseek-chat-completions-v1"
_CAPABILITY_SOURCE = "https://api-docs.deepseek.com/api/create-chat-completion/"
_TERMS_SOURCE = (
    "https://cdn.deepseek.com/policies/en-US/"
    "deepseek-open-platform-terms-of-service.html"
)
_MAX_SOURCE_BYTES = 2_000_000


@dataclass(frozen=True)
class _PendingSecretState:
    created_by: UUID
    version: int
    verified_at: datetime | None


def main() -> int:
    args = _arguments()
    project_id = _uuid(args.project_id, "project")
    tenant_id = _uuid(args.tenant_id, "tenant")
    approver_id = _uuid(args.approved_by, "approver")
    preparer_id = _uuid(args.prepared_by, "preparer")
    if approver_id == preparer_id:
        raise SystemExit("--prepared-by and --approved-by must be distinct identities")
    database_url = _required_text(os.getenv(args.database_url_env), args.database_url_env)
    configured_model = args.configured_model.strip()
    if not configured_model:
        raise SystemExit("--configured-model cannot be empty")

    catalog = PostgresRuntimeCatalog(database_url)
    existing = catalog.list_approved_runtime_options(project_id=project_id)
    matching = [
        item
        for item in existing.items
        if item.provider == PROVIDER
        and item.configured_model == configured_model
        and PROMPT_TEST_MODEL_PURPOSE in item.allowed_purposes
        and PROMPT_TEST_SEARCH_MODE in item.allowed_search_modes
    ]
    if matching:
        _print_result(
            status="already_configured",
            project_id=project_id,
            configured_model=configured_model,
            selection_id=matching[0].selection_id,
            secret_reference_id=None,
        )
        return 0
    if existing.items:
        raise SystemExit(
            "the project already has an approved runtime manifest; "
            "replace it through the runtime change procedure before adding DeepSeek"
        )

    approver_principal = _operator_principal(
        identity_id=approver_id,
        project_id=project_id,
        tenant_id=tenant_id,
        auth_method="operator-bootstrap-approval",
    )
    # This is a local operator bootstrap, not a transport-level Admin API
    # request. The preparer is the registered worker identity that will use
    # the credential. Its distinct audit actor gives the first secret version
    # a real creator/approver split without inventing a second human account.
    preparer_principal = _operator_principal(
        identity_id=preparer_id,
        project_id=project_id,
        tenant_id=tenant_id,
        auth_method="operator-bootstrap-preparation",
    )
    secret_reference_id = uuid5(
        NAMESPACE_URL, f"geo:{project_id}:model-provider:{PROVIDER}"
    )
    secret_api = build_secret_store_api(
        database_url=database_url,
        master_keyring_path=args.master_keyring_file,
        request_hash_key_path=args.request_hash_key_file,
    )
    if secret_api is None:
        raise SystemExit("Secret Store keyring configuration is unavailable")
    handle = _active_secret_handle(
        api=secret_api,
        approver_principal=approver_principal,
        preparer_principal=preparer_principal,
        project_id=project_id,
        reference_id=secret_reference_id,
        api_key_file=Path(args.api_key_file),
        database_url=database_url,
    )

    object_store = _object_store()
    evidence = _store_evidence(
        object_store=object_store,
        project_id=project_id,
        configured_model=configured_model,
        prefix=args.evidence_prefix,
    )
    manifest = _manifest(
        project_id=project_id,
        prepared_by=preparer_id,
        approved_by=approver_id,
        provider_secret=handle,
        configured_model=configured_model,
        evidence=evidence,
    )
    handles = register_runtime_manifest(catalog, manifest)
    if handles != (handle,):
        raise SystemExit("runtime manifest did not retain the active DeepSeek secret handle")
    option = next(
        item
        for item in catalog.list_approved_runtime_options(project_id=project_id).items
        if item.provider == PROVIDER and item.configured_model == configured_model
    )
    _print_result(
        status="configured",
        project_id=project_id,
        configured_model=configured_model,
        selection_id=option.selection_id,
        secret_reference_id=handle.reference_id,
    )
    return 0


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument(
        "--prepared-by",
        default=os.getenv("GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID", ""),
    )
    parser.add_argument("--configured-model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-file", default="/run/secrets/deepseek_api_key")
    parser.add_argument(
        "--master-keyring-file",
        default=os.getenv("GEO_SECRET_STORE_MASTER_KEYRING_FILE", ""),
    )
    parser.add_argument(
        "--request-hash-key-file",
        default=os.getenv("GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE", ""),
    )
    parser.add_argument("--database-url-env", default="GEO_DATABASE_URL")
    parser.add_argument(
        "--evidence-prefix", default="model-gateway/deepseek-prompt-runtime-v1"
    )
    return parser.parse_args()


def _active_secret_handle(
    *,
    api: object,
    approver_principal: AccessPrincipal,
    preparer_principal: AccessPrincipal,
    project_id: UUID,
    reference_id: UUID,
    api_key_file: Path,
    database_url: str,
) -> SecretVersionHandle:
    try:
        reference = api.get_reference(  # type: ignore[attr-defined]
            approver_principal, project_id=project_id, reference_id=reference_id
        )
    except SecretNotFound:
        raw_key = _read_key(api_key_file)
        try:
            created = api.create(  # type: ignore[attr-defined]
                preparer_principal,
                project_id=project_id,
                reference_id=reference_id,
                purpose=f"model_provider.{PROVIDER}",
                value=SecretValue(raw_key),
                expected_version=0,
                idempotency_key=f"bootstrap-{PROVIDER}-secret-create-v1",
            )
        finally:
            del raw_key
        verified = api.verify(  # type: ignore[attr-defined]
            approver_principal,
            project_id=project_id,
            reference_id=reference_id,
            version=created.version,
            expected_version=created.aggregate_version,
            idempotency_key=f"bootstrap-{PROVIDER}-secret-verify-v1",
        )
        activated = api.activate(  # type: ignore[attr-defined]
            approver_principal,
            project_id=project_id,
            reference_id=reference_id,
            version=created.version,
            expected_version=verified.aggregate_version,
            idempotency_key=f"bootstrap-{PROVIDER}-secret-activate-v1",
        )
        return SecretVersionHandle(
            reference_id=reference_id,
            project_id=project_id,
            purpose=f"model_provider.{PROVIDER}",
            version=activated.version,
        )
    if reference.purpose != f"model_provider.{PROVIDER}":
        raise SystemExit("existing DeepSeek Secret reference has a different purpose")
    if reference.status == "active" and reference.current_version is not None:
        return SecretVersionHandle(
            reference_id=reference_id,
            project_id=project_id,
            purpose=f"model_provider.{PROVIDER}",
            version=reference.current_version,
        )
    if reference.status != "pending":
        raise SystemExit("existing DeepSeek Secret reference is not an active provider credential")

    # A previous interrupted bootstrap can leave a pending version. Resume it
    # instead of creating a second credential. The creator is read from the
    # encrypted-store metadata, never from the key file or a log.
    pending = _pending_secret_state(
        database_url=database_url,
        project_id=project_id,
        reference_id=reference_id,
    )
    if pending.verified_at is None:
        verified = api.verify(  # type: ignore[attr-defined]
            approver_principal,
            project_id=project_id,
            reference_id=reference_id,
            version=pending.version,
            expected_version=reference.aggregate_version,
            idempotency_key=f"bootstrap-{PROVIDER}-secret-recovery-verify-v1",
        )
        expected_version = verified.aggregate_version
    else:
        expected_version = reference.aggregate_version
    activator = (
        approver_principal
        if pending.created_by != approver_principal.identity_id
        else preparer_principal
    )
    activated = api.activate(  # type: ignore[attr-defined]
        activator,
        project_id=project_id,
        reference_id=reference_id,
        version=pending.version,
        expected_version=expected_version,
        idempotency_key=f"bootstrap-{PROVIDER}-secret-recovery-activate-v1",
    )
    return SecretVersionHandle(
        reference_id=reference_id,
        project_id=project_id,
        purpose=f"model_provider.{PROVIDER}",
        version=activated.version,
    )


def _operator_principal(
    *,
    identity_id: UUID,
    project_id: UUID,
    tenant_id: UUID,
    auth_method: str,
) -> AccessPrincipal:
    """Build the explicit actor assertion for this local operator command."""

    return AccessPrincipal(
        identity_id=identity_id,
        actor_id=str(identity_id),
        tenant_id=tenant_id,
        memberships=(MembershipRecord(project_id, tenant_id, "owner"),),
        auth_method=auth_method,
    )


def _pending_secret_state(
    *,
    database_url: str,
    project_id: UUID,
    reference_id: UUID,
) -> _PendingSecretState:
    try:
        with psycopg.connect(database_url) as connection:
            set_project_scope(connection, project_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT created_by, version, verified_at
                       FROM secret_versions
                       WHERE project_id = %s AND reference_id = %s
                         AND purpose = %s AND status = 'pending'
                       ORDER BY version DESC
                       LIMIT 1""",
                    (project_id, reference_id, f"model_provider.{PROVIDER}"),
                )
                row = cursor.fetchone()
    except psycopg.Error as exc:
        raise SystemExit("pending DeepSeek Secret state cannot be read") from exc
    if row is None:
        raise SystemExit("existing DeepSeek Secret has no pending version to resume")
    created_by, version, verified_at = row
    return _PendingSecretState(
        created_by=UUID(str(created_by)),
        version=int(version),
        verified_at=verified_at,
    )


def _store_evidence(
    *,
    object_store: S3CompatibleObjectStore,
    project_id: UUID,
    configured_model: str,
    prefix: str,
) -> Mapping[str, str]:
    normalized_prefix = prefix.strip().strip("/")
    if not normalized_prefix:
        raise SystemExit("--evidence-prefix cannot be empty")
    sources = {
        "capability": _source_fingerprint(_CAPABILITY_SOURCE),
        "terms": _source_fingerprint(_TERMS_SOURCE),
    }
    capability = {
        "schema_version": 1,
        "provider": PROVIDER,
        "configured_model": configured_model,
        "adapter_release_id": ADAPTER_RELEASE_ID,
        "source": sources["capability"],
        "capabilities": {
            "structured_output": True,
            "supports_tools": True,
            "supports_search": False,
            "supports_citations": False,
            "supports_seed": False,
            "supports_idempotency": False,
        },
    }
    terms = {
        "schema_version": 1,
        "provider": PROVIDER,
        "configured_model": configured_model,
        "source": sources["terms"],
        "local_data_policy": {
            "storage": "allowed",
            "cache": "prohibited",
            "display": "allowed",
            "redistribution": "prohibited",
            "retention_days": None,
        },
    }
    capability_stored = _store_json(
        object_store, f"{normalized_prefix}/{project_id}/capabilities.json", capability
    )
    terms_stored = _store_json(
        object_store, f"{normalized_prefix}/{project_id}/terms.json", terms
    )
    approval = {
        "schema_version": 1,
        "kind": "prompt_runtime_bootstrap",
        "project_id": str(project_id),
        "provider": PROVIDER,
        "configured_model": configured_model,
        "purpose": PROMPT_TEST_MODEL_PURPOSE,
        "search_mode": PROMPT_TEST_SEARCH_MODE,
        "capability_evidence": {
            "uri": capability_stored.uri,
            "sha256": capability_stored.content_hash,
        },
        "terms_evidence": {"uri": terms_stored.uri, "sha256": terms_stored.content_hash},
    }
    approval_stored = _store_json(
        object_store, f"{normalized_prefix}/{project_id}/approval.json", approval
    )
    return {
        "capability_reference": capability_stored.uri,
        "capability_sha256": capability_stored.content_hash,
        "terms_reference": terms_stored.uri,
        "terms_sha256": terms_stored.content_hash,
        "approval_reference": approval_stored.uri,
        "approval_sha256": approval_stored.content_hash,
    }


def _manifest(
    *,
    project_id: UUID,
    prepared_by: UUID,
    approved_by: UUID,
    provider_secret: SecretVersionHandle,
    configured_model: str,
    evidence: Mapping[str, str],
):
    model_release_id = f"{configured_model}-prompt-test-v1"
    policy_id = uuid5(
        NAMESPACE_URL,
        f"geo:{project_id}:model-policy:{PROVIDER}:{configured_model}:prompt-test-v1",
    )
    manifest_id = uuid5(
        NAMESPACE_URL,
        f"geo:{project_id}:runtime-manifest:{PROVIDER}:{configured_model}:prompt-test-v1",
    )
    now = datetime.now(UTC)
    return parse_runtime_manifest(
        {
            "schema_version": 2,
            "manifest_id": str(manifest_id),
            "project_id": str(project_id),
            "prepared_by": str(prepared_by),
            "prepared_at": now.isoformat(),
            "approved_by": str(approved_by),
            "approved_at": now.isoformat(),
            "approval_evidence_reference": evidence["approval_reference"],
            "approval_evidence_sha256": evidence["approval_sha256"],
            "provider_runtimes": [
                {
                    "provider": PROVIDER,
                    "adapter_release_id": ADAPTER_RELEASE_ID,
                    "allowed_purposes": [PROMPT_TEST_MODEL_PURPOSE],
                    "allowed_search_modes": [PROMPT_TEST_SEARCH_MODE],
                    "secret_reference_id": str(provider_secret.reference_id),
                    "expected_capture_method": "provider_api",
                    "interface_contract_version": "geo-model-gateway-v1",
                    "capability_evidence_reference": evidence["capability_reference"],
                    "capability_evidence_sha256": evidence["capability_sha256"],
                    "capabilities": {
                        "external_training_allowed": False,
                        "structured_output": True,
                        "data_retention_days": None,
                        "policy_reference": "deepseek-prompt-runtime-v1",
                        "supports_seed": False,
                        "supports_tools": True,
                        "supports_search": False,
                        "supports_citations": False,
                        "supports_idempotency": False,
                        "supports_structured_output_with_tools": False,
                    },
                    "data_policy": {
                        "storage": "allowed",
                        "cache": "prohibited",
                        "display": "allowed",
                        "redistribution": "prohibited",
                        "retention_days": None,
                        "terms_reference": evidence["terms_reference"],
                        "terms_sha256": evidence["terms_sha256"],
                    },
                    "microsoft": None,
                }
            ],
            "model_releases": [
                {
                    "provider": PROVIDER,
                    "adapter_release_id": ADAPTER_RELEASE_ID,
                    "model_release_id": model_release_id,
                    "configured_model": configured_model,
                    "reported_model_policy": "exact",
                    "allowed_reported_models": [configured_model],
                }
            ],
            "project_policy": {
                "policy_version_id": str(policy_id),
                "version": 1,
                "previous_version_id": None,
                "external_training_allowed": False,
                "structured_output_required": True,
                "allowed_providers": [PROVIDER],
                "allowed_adapter_release_ids": [ADAPTER_RELEASE_ID],
                "maximum_paid_calls": 5,
                "maximum_concurrent_calls": 1,
            },
        }
    )


def _source_fingerprint(url: str) -> Mapping[str, object]:
    request = Request(url, headers={"User-Agent": "GEO runtime bootstrap/1"})
    with urlopen(request, timeout=20) as response:  # nosec B310: fixed HTTPS evidence URL
        content = response.read(_MAX_SOURCE_BYTES + 1)
    if len(content) > _MAX_SOURCE_BYTES:
        raise SystemExit(f"provider evidence exceeds {_MAX_SOURCE_BYTES} bytes: {url}")
    return {
        "url": url,
        "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }


def _store_json(
    object_store: S3CompatibleObjectStore, key: str, document: Mapping[str, object]
):
    content = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return object_store.put_object(
        key=key,
        content=content,
        content_type="application/json",
        expected_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _read_key(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise SystemExit("DeepSeek API key file cannot be read") from exc
    if not value:
        raise SystemExit("DeepSeek API key file is empty")
    return value


def _object_store() -> S3CompatibleObjectStore:
    try:
        return build_object_store()
    except RuntimeError as exc:
        raise SystemExit("object store configuration is unavailable") from exc


def _uuid(value: str, label: str) -> UUID:
    try:
        identifier = UUID(value)
    except (AttributeError, ValueError) as exc:
        raise SystemExit(f"{label} ID must be a UUID") from exc
    if identifier.int == 0:
        raise SystemExit(f"{label} ID cannot be the nil UUID")
    return identifier


def _required_text(value: str | None, label: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise SystemExit(f"{label} is required")
    return normalized


def _print_result(
    *,
    status: str,
    project_id: UUID,
    configured_model: str,
    selection_id: UUID,
    secret_reference_id: UUID | None,
) -> None:
    print(
        json.dumps(
            {
                "status": status,
                "project_id": str(project_id),
                "provider": PROVIDER,
                "configured_model": configured_model,
                "runtime_selection_id": str(selection_id),
                "secret_reference_id": (
                    str(secret_reference_id) if secret_reference_id is not None else None
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
