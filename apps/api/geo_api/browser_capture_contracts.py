"""Stable Admin transport contracts for consumer-surface Browser Capture."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator

from geo_api.contracts import StrictContract


AuthorizationTrack = Literal["A", "B"]
AuthorizationStatus = Literal[
    "not_assessed", "approved", "restricted", "prohibited", "expired", "revoked"
]


class SurfaceSelectorRequest(StrictContract):
    query_input: str = Field(min_length=1, max_length=1_000)
    page_complete: str = Field(min_length=1, max_length=1_000)
    surface_marker: str = Field(min_length=1, max_length=1_000)
    answer: str = Field(min_length=1, max_length=1_000)
    citations: str = Field(min_length=1, max_length=1_000)
    page_location: str = Field(min_length=1, max_length=1_000)
    ready_timeout_ms: int = Field(default=45_000, ge=1_000, le=180_000)


class CreateSurfaceReleaseRequest(StrictContract):
    platform: str = Field(min_length=1, max_length=80)
    surface: str = Field(min_length=1, max_length=120)
    release_version: str = Field(min_length=1, max_length=100)
    entry_url_template: str = Field(pattern=r"^https://", max_length=2_000)
    allowed_hosts: list[str] = Field(min_length=1, max_length=20)
    selectors: SurfaceSelectorRequest
    block_detectors: dict[str, str] = Field(default_factory=dict, max_length=5)
    parser_release: str = Field(min_length=1, max_length=100)
    browser_release: str = Field(min_length=1, max_length=100)
    authorization_track: AuthorizationTrack
    authorization_status: AuthorizationStatus
    authorization_reference: str | None = Field(default=None, max_length=1_000)
    authorization_valid_until: datetime | None = None
    terms_version: str = Field(min_length=1, max_length=200)

    @field_validator("block_detectors")
    @classmethod
    def validate_block_detectors(cls, value: dict[str, str]) -> dict[str, str]:
        supported = {"consent", "login", "captcha", "rate_limit", "ban"}
        unknown = sorted(set(value) - supported)
        if unknown:
            raise ValueError(f"unsupported block detector: {', '.join(unknown)}")
        if any(not selector.strip() or len(selector) > 1_000 for selector in value.values()):
            raise ValueError("block detector selectors must contain 1 to 1000 characters")
        return value


class SurfaceReleaseResponse(StrictContract):
    id: UUID
    project_id: UUID
    platform: str
    surface: str
    release_version: str
    entry_url_template: str
    allowed_hosts: list[str]
    selectors: dict[str, object]
    block_detectors: dict[str, object]
    parser_release: str
    browser_release: str
    authorization_track: str
    authorization_status: str
    authorization_reference: str | None = None
    authorization_valid_until: datetime | None = None
    terms_version: str
    release_hash: str
    status: str
    created_by: UUID
    created_at: datetime
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    suspended_at: datetime | None = None
    suspension_reason: str | None = None


class CreateEgressEndpointRequest(StrictContract):
    name: str = Field(min_length=1, max_length=200)
    protocol: Literal["http", "https", "socks5"]
    endpoint_host: str = Field(min_length=1, max_length=253)
    endpoint_port: int = Field(ge=1, le=65_535)
    secret_reference_id: UUID
    secret_purpose: str = Field(pattern=r"^browser_egress\.[a-z0-9_.-]+$", max_length=128)
    secret_version: int = Field(ge=1)
    expected_region: str | None = Field(default=None, max_length=120)
    network_type: Literal["residential", "mobile", "datacenter", "unknown"]
    sticky_mode: Literal["provider_lease", "credential_session", "trusted_connection_log"]
    egress_policy_version: str = Field(min_length=1, max_length=100)
    egress_cohort_key: str = Field(min_length=1, max_length=200)


class EgressEndpointResponse(StrictContract):
    id: UUID
    project_id: UUID
    name: str
    protocol: str
    endpoint_host: str
    endpoint_port: int
    secret_reference_id: UUID
    secret_purpose: str
    secret_version: int
    expected_country: Literal["AU"]
    expected_region: str | None = None
    network_type: str
    sticky_mode: str
    egress_policy_version: str
    egress_cohort_key: str
    status: str
    created_by: UUID
    created_at: datetime
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    disabled_at: datetime | None = None


class ConfigureAustralianEgressRequest(StrictContract):
    name: str = Field(default="澳洲消费者搜索出口", min_length=1, max_length=200)
    protocol: Literal["http", "https", "socks5"] = "https"
    endpoint_host: str = Field(min_length=1, max_length=253)
    endpoint_port: int = Field(ge=1, le=65_535)
    username_template: str = Field(min_length=3, max_length=1_000)
    password: SecretStr
    network_type: Literal["residential", "mobile"] = "residential"
    expected_region: str | None = Field(default=None, max_length=120)
    lease_ttl_seconds: int = Field(default=600, ge=60, le=3_600)

    @field_validator("username_template")
    @classmethod
    def validate_sticky_username(cls, value: str) -> str:
        if "{session_id}" not in value:
            raise ValueError("username_template must contain {session_id}")
        return value.strip()


class AustralianEgressSetupResponse(StrictContract):
    endpoint: EgressEndpointResponse
    secret_reference_id: UUID
    secret_version: int
    egress_test_required: Literal[True]


class ConfigureBrowserSessionRequest(StrictContract):
    storage_state_json: SecretStr

    @field_validator("storage_state_json")
    @classmethod
    def validate_storage_state_size(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value().encode("utf-8")) > 2_000_000:
            raise ValueError("storage_state_json exceeds 2 MB")
        return value


class BrowserSessionSetupResponse(StrictContract):
    profile: BrowserProfileResponse
    secret_reference_id: UUID
    secret_version: int


class SetEgressEndpointStatusRequest(StrictContract):
    status: Literal["approved", "disabled"]


class CreateBrowserProfileRequest(StrictContract):
    version: str = Field(min_length=1, max_length=100)
    browser_release: str = Field(min_length=1, max_length=100)
    device_class: Literal["desktop", "mobile"]
    viewport: dict[str, object]
    timezone: str = Field(default="Australia/Sydney", min_length=1, max_length=100)
    geolocation: dict[str, object] | None = None
    location_permission: bool = False
    safe_search: Literal["on", "moderate", "off"] = "moderate"
    account_cohort: Literal["clean_anonymous", "managed_test_account"] = "clean_anonymous"
    storage_secret_reference_id: UUID | None = None
    storage_secret_purpose: str | None = Field(default=None, max_length=128)
    storage_secret_version: int | None = Field(default=None, ge=1)


class BrowserProfileResponse(StrictContract):
    id: UUID
    project_id: UUID
    version: str
    browser_release: str
    device_class: str
    viewport: dict[str, object]
    locale: Literal["en-AU"]
    timezone: str
    geolocation: dict[str, object] | None = None
    location_permission: bool
    safe_search: str
    account_cohort: str
    storage_secret_reference_id: UUID | None = None
    storage_secret_purpose: str | None = None
    storage_secret_version: int | None = None
    profile_hash: str
    status: str
    created_by: UUID
    created_at: datetime
    approved_by: UUID | None = None
    approved_at: datetime | None = None


class BrowserCaptureInventoryResponse(StrictContract):
    surface_releases: list[SurfaceReleaseResponse]
    egress_endpoints: list[EgressEndpointResponse]
    profiles: list[BrowserProfileResponse]
    egress_tests: list[dict[str, object]]
    drift_events: list[dict[str, object]]
    tasks: list[dict[str, object]]
    sessions: list[dict[str, object]]


ConsumerSurfaceValue = Literal[
    "google_ai_overviews", "google_ai_mode", "bing_copilot"
]


class BootstrapBrowserCaptureRequest(StrictContract):
    surfaces: list[ConsumerSurfaceValue] = Field(min_length=1, max_length=3)
    terms_acknowledged: Literal[True]


class BrowserCaptureBootstrapResponse(StrictContract):
    surface_releases: list[SurfaceReleaseResponse]
    profile: BrowserProfileResponse


class BrowserCaptureReadinessItem(StrictContract):
    surface: ConsumerSurfaceValue
    state: Literal["blocked", "ready", "live_verified", "fidelity_accepted"]
    blocking_reasons: list[str]
    surface_release_id: UUID | None = None
    release_version: str | None = None
    profile_version_id: UUID | None = None
    egress_endpoint_id: UUID | None = None
    captured_count: int = Field(ge=0)


class BrowserCaptureReadinessResponse(StrictContract):
    items: list[BrowserCaptureReadinessItem]


class RegisterBrowserSamplingOptionRequest(StrictContract):
    surface_release_id: UUID
    egress_endpoint_id: UUID
    profile_version_id: UUID


class BrowserSamplingOptionResponse(StrictContract):
    option_key: str
    display_name: str
    platform: str
    capture_method: Literal["automated_ui"]
    adapter_release: str
    location_control: Literal["country"]
    location_evidence_hash: str
    authorization_reference: str
    allowed_purposes: list[str]


class RegisterBrowserSuiteInputRequest(RegisterBrowserSamplingOptionRequest):
    question_set_id: UUID
    admission_policy_id: UUID
    option_key: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)


class EnqueueBrowserCaptureAttemptRequest(RegisterBrowserSamplingOptionRequest):
    expected_task_version: int = Field(ge=1)
    requested_not_before: datetime


class BrowserCaptureAttemptResponse(StrictContract):
    attempt_id: UUID
    durable_job_id: UUID
    task_version: int
    attempt_version: int
    run_version: int
    replayed: bool


class BrowserEgressTestResponse(StrictContract):
    test_id: UUID
    job_id: UUID
    status: str
    replayed: bool


__all__ = [name for name in globals() if name.endswith(("Request", "Response"))]
