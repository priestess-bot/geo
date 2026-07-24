"""Shared validation helpers for Synthetic Lab PostgreSQL API mixins."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.access.models import AccessPrincipal
from geo_core.synthetic_lab.ports import (
    LabPrincipal,
    LabRole,
    SyntheticLabPermissionDenied,
)


def domain_principal(principal: AccessPrincipal, project_id: UUID) -> LabPrincipal:
    roles = {
        membership.role
        for membership in principal.memberships
        if membership.project_id == project_id
    }
    if not roles:
        raise SyntheticLabPermissionDenied("Synthetic Lab Project membership is unavailable")
    mapped: set[LabRole] = set()
    if roles.intersection({"owner", "admin", "operator", "analyst"}):
        mapped.add(LabRole.OPERATOR)
    if roles.intersection({"owner", "admin"}):
        mapped.add(LabRole.APPROVER)
    if roles.intersection({"owner", "admin", "analyst"}):
        mapped.add(LabRole.REVIEWER)
    return LabPrincipal(project_id=project_id, actor_id=principal.identity_id, roles=frozenset(mapped))


def payload(values: dict[str, object]) -> dict[str, Any]:
    value = values["payload"]
    if not hasattr(value, "model_dump"):
        raise TypeError("Synthetic API payload is not validated")
    return value.model_dump(mode="python")


def project(values: dict[str, object]) -> UUID:
    return uuid_value(values["project_id"])


def uuid_value(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError("Synthetic API identity is invalid")
    return value


def int_value(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("Synthetic API integer is invalid")
    return value


def stable_id(project_id: UUID, idempotency_key: object, namespace: str) -> UUID:
    digest = hashlib.sha256(str(idempotency_key).encode()).hexdigest()
    return uuid5(NAMESPACE_URL, f"geo:{project_id}:{namespace}:{digest}")


__all__ = ["domain_principal", "int_value", "payload", "project", "stable_id", "uuid_value"]
