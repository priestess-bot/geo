from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from geno_core.models import AuditEvent


AUTH_AUDIT_EVENT_TYPES = frozenset(
    {
        "auth.login",
        "auth.logout",
        "auth.session_created",
        "auth.session_expired",
        "auth.denied",
        "authz.denied",
        "invitation.created",
        "invitation.redeemed",
        "invitation.failed",
        "system_actor.used",
    }
)
AUTH_AUDIT_FORBIDDEN_REF_KEYS = frozenset(
    {
        "token",
        "tokens",
        "raw_token",
        "raw_tokens",
        "invite_token",
        "invite_tokens",
        "session_token",
        "session_tokens",
        "password",
        "passwords",
        "secret",
        "secrets",
    }
)


def canonical_json(payload: Any) -> str:
    if is_dataclass(payload):
        payload = asdict(payload)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def hash_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def build_audit_event(
    *,
    event_type: str,
    project_id: str,
    actor_type: str,
    actor_id: str,
    target_type: str,
    target_id: str,
    before: Any | None = None,
    after: Any | None = None,
    input_refs: dict[str, list[str]] | None = None,
    output_refs: dict[str, list[str]] | None = None,
    method_version: str | None = None,
    reason: str | None = None,
) -> AuditEvent:
    return AuditEvent(
        id=str(uuid4()),
        event_type=event_type,
        project_id=project_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        before_hash=hash_payload(before) if before is not None else None,
        after_hash=hash_payload(after) if after is not None else None,
        input_refs=input_refs or {},
        output_refs=output_refs or {},
        method_version=method_version,
        reason=reason,
        created_at=datetime.now(UTC),
    )


def build_auth_audit_event(
    *,
    event_type: str,
    actor_type: str,
    actor_id: str,
    target_type: str,
    target_id: str,
    project_id: str = "",
    before: Any | None = None,
    after: Any | None = None,
    input_refs: dict[str, list[str]] | None = None,
    output_refs: dict[str, list[str]] | None = None,
    method_version: str = "auth_audit_v1",
    reason: str | None = None,
) -> AuditEvent:
    if event_type not in AUTH_AUDIT_EVENT_TYPES:
        raise ValueError(f"unknown auth audit event_type: {event_type}")
    for refs in (input_refs or {}, output_refs or {}):
        forbidden = sorted(set(refs) & AUTH_AUDIT_FORBIDDEN_REF_KEYS)
        if forbidden:
            raise ValueError(f"auth audit refs must not include raw secret fields: {', '.join(forbidden)}")
    return build_audit_event(
        event_type=event_type,
        project_id=project_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
        input_refs=input_refs,
        output_refs=output_refs,
        method_version=method_version,
        reason=reason,
    )
