from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Request

from geno_core.models import RuntimeHttpAccessLogInput
from geno_core.runtime import build_object_store_from_env, build_repository_from_env, close_repository_connection


def sha256_text(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value).hexdigest()


def extract_project_id_from_request(request: Request) -> str | None:
    query_project_id = request.query_params.get("project_id")
    normalized_query_project_id = _normalized_uuid(query_project_id)
    if normalized_query_project_id:
        return normalized_query_project_id
    path = request.url.path
    match = re.search(r"/projects/runtime/([^/?]+)", path)
    if match:
        return _normalized_uuid(match.group(1))
    return None


def _normalized_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(UUID(value.strip()))
    except ValueError:
        return None


def actor_id_from_request(
    request: Request,
    *,
    actor_header: str,
    jwt_actor_id: str | None = None,
) -> str | None:
    if jwt_actor_id:
        return jwt_actor_id
    actor_id = request.headers.get(actor_header)
    return actor_id.strip() if actor_id else None


def persist_runtime_http_access_log(
    *,
    request: Request,
    request_id: str,
    route_path: str,
    status_code: int,
    duration_seconds: float,
    request_body: bytes,
    response_body: bytes,
    response_headers: Mapping[str, str],
    response_media_type: str | None,
    actor_header: str,
    jwt_actor_id: str | None = None,
    error_type: str | None = None,
    repository_builder: Callable[[], Any] = build_repository_from_env,
    object_store_builder: Callable[[], Any] = build_object_store_from_env,
    close_repository: Callable[[Any], None] = close_repository_connection,
) -> None:
    request_headers_json = json.dumps(
        _redacted_headers(request.headers),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    response_headers_json = json.dumps(
        _redacted_headers(response_headers),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    request_body_uri = _archive_runtime_http_artifact(
        request_id=request_id,
        artifact_name="request-body.bin",
        content=request_body,
        content_type=request.headers.get("content-type") or "application/octet-stream",
        object_store_builder=object_store_builder,
    )
    response_body_uri = _archive_runtime_http_artifact(
        request_id=request_id,
        artifact_name="response-body.bin",
        content=response_body,
        content_type=response_media_type or "application/octet-stream",
        object_store_builder=object_store_builder,
    )
    request_headers_uri = _archive_runtime_http_artifact(
        request_id=request_id,
        artifact_name="request-headers.json",
        content=request_headers_json,
        content_type="application/json",
        object_store_builder=object_store_builder,
    )
    response_headers_uri = _archive_runtime_http_artifact(
        request_id=request_id,
        artifact_name="response-headers.json",
        content=response_headers_json,
        content_type="application/json",
        object_store_builder=object_store_builder,
    )
    archive_uris = (request_body_uri, response_body_uri, request_headers_uri, response_headers_uri)
    capture_status = "archived" if all(archive_uris) else "metadata_only"
    repository = repository_builder()
    try:
        repository.save_runtime_http_access_log(
            RuntimeHttpAccessLogInput(
                request_id=request_id,
                project_id=extract_project_id_from_request(request),
                actor_id=actor_id_from_request(
                    request,
                    actor_header=actor_header,
                    jwt_actor_id=jwt_actor_id,
                ),
                method=request.method,
                path=request.url.path,
                route=route_path,
                query_hash=sha256_text(str(request.url.query)),
                request_headers_hash=sha256_bytes(request_headers_json),
                request_body_hash=sha256_bytes(request_body),
                request_body_size=len(request_body),
                request_body_uri=request_body_uri,
                request_headers_uri=request_headers_uri,
                response_headers_hash=sha256_bytes(response_headers_json),
                response_body_hash=sha256_bytes(response_body),
                response_body_size=len(response_body),
                response_body_uri=response_body_uri,
                response_headers_uri=response_headers_uri,
                status_code=status_code,
                duration_ms=round(duration_seconds * 1000, 3),
                client_host_hash=sha256_text(request.client.host if request.client else None),
                user_agent_hash=sha256_text(request.headers.get("user-agent")),
                error_type=error_type,
                capture_status=capture_status,
                metadata={"log_version": "runtime_http_access_log_v1"},
            )
        )
    finally:
        close_repository(repository)


def _redacted_headers(headers: Mapping[str, str]) -> dict[str, str]:
    sensitive_names = {"authorization", "cookie", "set-cookie", "x-api-key", "x-geno-actor-id"}
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        lower_key = key.lower()
        redacted[key] = "[redacted]" if lower_key in sensitive_names or "token" in lower_key or "secret" in lower_key else value
    return redacted


def _archive_runtime_http_artifact(
    *,
    request_id: str,
    artifact_name: str,
    content: bytes | str,
    content_type: str,
    object_store_builder: Callable[[], Any],
) -> str | None:
    try:
        store = object_store_builder()
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", artifact_name).strip("-") or "artifact"
        created_date = datetime.utcnow().strftime("%Y/%m/%d")
        stored = store.put_object(
            key=f"runtime-http-access-logs/{created_date}/{request_id}/{safe_name}",
            content=content,
            content_type=content_type,
        )
        return stored.uri
    except Exception:
        return None
