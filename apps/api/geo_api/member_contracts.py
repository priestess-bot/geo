"""Stable internal contracts for OIDC project member governance."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator

from geo_api.contracts import StrictContract


ManagedMembershipRole = Literal["owner", "admin", "analyst"]


class AddProjectMemberRequest(StrictContract):
    issuer: str = Field(min_length=8, max_length=2048)
    subject: str = Field(min_length=1, max_length=512)
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    role: ManagedMembershipRole

    @field_validator("issuer")
    @classmethod
    def validate_issuer(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("issuer must be an HTTPS URL without userinfo, query, or fragment")
        return normalized

    @field_validator("subject", "display_name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not normalized.isprintable():
            raise ValueError("value must contain printable text")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain or domain.startswith("."):
            raise ValueError("email must be a valid normalized address")
        return normalized


class ProjectMemberSummary(StrictContract):
    membership_id: UUID
    project_id: UUID
    identity_id: UUID
    issuer: str
    subject: str
    email: str
    display_name: str
    role: ManagedMembershipRole
    status: Literal["active", "revoked"]
    created_at: datetime


class ProjectMemberListResponse(StrictContract):
    items: list[ProjectMemberSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class AddProjectMemberResponse(StrictContract):
    member: ProjectMemberSummary
    replayed: bool


class RevokeProjectMemberResponse(StrictContract):
    member: ProjectMemberSummary
    replayed: bool


class ChangeProjectMemberRoleRequest(StrictContract):
    role: ManagedMembershipRole


class ChangeProjectMemberResponse(StrictContract):
    member: ProjectMemberSummary
    replayed: bool
