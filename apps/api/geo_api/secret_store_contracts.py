"""Strict, write-only-secret contracts for the Internal Secret Store API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


SecretStatusValue = Literal["pending", "active", "superseded", "revoked"]


class SecretPurposeKey(StrEnum):
    MODEL_PROVIDER_OPENAI = "model_provider.openai"
    MODEL_PROVIDER_DEEPSEEK = "model_provider.deepseek"
    MODEL_PROVIDER_KIMI = "model_provider.kimi"
    MODEL_PROVIDER_GEMINI = "model_provider.gemini"
    MODEL_PROVIDER_PERPLEXITY = "model_provider.perplexity"
    MODEL_PROVIDER_MICROSOFT = "model_provider.microsoft"
    BROWSER_EGRESS_LOKIPROXY = "browser_egress.lokiproxy"
    LEGACY_BROWSER_EGRESS_AU = "browser_egress.au"
    BROWSER_SESSION_STORAGE_STATE = "browser_session.storage_state"
    AUSTRALIA_EGRESS_PROXY = "egress.proxy.australia"
    STYLE_PRODUCTREVIEW = "style_collection_login.productreview"
    STYLE_REDDIT = "style_collection_login.reddit"
    STYLE_QUORA = "style_collection_login.quora"
    STYLE_YOUTUBE = "style_collection_login.youtube"
    STYLE_TIKTOK = "style_collection_login.tiktok"
    STYLE_INSTAGRAM = "style_collection_login.instagram"
    STYLE_FACEBOOK = "style_collection_login.facebook"
    STYLE_LINKEDIN = "style_collection_login.linkedin"
    STYLE_X = "style_collection_login.x"
    LEGACY_PROVIDER_OPENAI = "provider.openai"
    LEGACY_PROVIDER_DEEPSEEK = "provider.deepseek"
    LEGACY_PROVIDER_KIMI = "provider.kimi"
    LEGACY_PROVIDER_GEMINI = "provider.gemini"
    LEGACY_PROVIDER_PERPLEXITY = "provider.perplexity"
    LEGACY_PROVIDER_MICROSOFT = "provider.microsoft"
    LEGACY_EGRESS_PROXY = "egress.proxy"


class SecretStoreContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSecretRequest(SecretStoreContract):
    reference_id: UUID | None = None
    purpose: SecretPurposeKey
    secret_value: SecretStr = Field(json_schema_extra={"writeOnly": True})
    expected_version: int = Field(ge=0)


class StageSecretRotationRequest(SecretStoreContract):
    secret_value: SecretStr = Field(json_schema_extra={"writeOnly": True})
    expected_version: int = Field(ge=1)


class SecretVersionTransitionRequest(SecretStoreContract):
    expected_version: int = Field(ge=1)


class SecretVersionResponse(SecretStoreContract):
    reference_id: UUID
    version: int = Field(ge=1)
    status: SecretStatusValue
    aggregate_version: int = Field(ge=1)
    master_key_version: int = Field(ge=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    verified_at: datetime | None = None
    activated_at: datetime | None = None
    revoked_at: datetime | None = None
    replayed: bool


class SecretReferenceResponse(SecretStoreContract):
    reference_id: UUID
    purpose: str
    status: str
    aggregate_version: int = Field(ge=1)
    current_version: int | None = Field(default=None, ge=1)
    latest_version: int = Field(ge=1)
    master_key_version: int = Field(ge=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    updated_at: datetime


class SecretReferencePage(SecretStoreContract):
    items: list[SecretReferenceResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class SecretAuditEventResponse(SecretStoreContract):
    reference_id: UUID
    version: int = Field(ge=1)
    action: str
    master_key_version: int = Field(ge=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    occurred_at: datetime


class SecretAuditEventPage(SecretStoreContract):
    items: list[SecretAuditEventResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
