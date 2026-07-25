"""Shared fixtures for the independently mounted workflow C API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from uuid import UUID, uuid5

from geo_api.app_factory import create_api_app
from geo_api.workflow_c_sampling_contracts import (
    AdmissionPolicyDecisionRequest,
    AdmissionPolicySubmitRequest,
    CreateAdmissionPolicyRequest,
)
from geo_api.workflow_c_sampling_catalog import ResolvedSamplingSuiteInputs
from geo_api.workflow_c_sampling_policy_runtime import SamplingAdmissionRuntimeOption
from geo_api.workflow_c_sampling_runtime import SAMPLING_API_NAMESPACE
from geo_api.workflow_c_runtime import WorkflowCApi, memory_workflow_c_api
from geo_core.access.models import AccessForbidden, AccessPrincipal, MembershipRecord
from geo_core.sampling import CaptureMethod, SamplingQuestion, SamplingSourceStratum


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("20000000-0000-0000-0000-000000000002")
POLICY_ID = uuid5(
    SAMPLING_API_NAMESPACE,
    f"{PROJECT_ID}:admission-policy:provider-policy:one",
)
MANUAL_POLICY_ID = uuid5(
    SAMPLING_API_NAMESPACE,
    f"{PROJECT_ID}:admission-policy:manual-policy:one",
)
QUESTION_SET_ID = UUID("50000000-0000-0000-0000-000000000005")
ADAPTER_RELEASE_ID = UUID("50000000-0000-4000-8000-000000000006")
MODEL_RELEASE_ID = UUID("50000000-0000-4000-8000-000000000007")
ROUTE_POLICY_ID = UUID("50000000-0000-4000-8000-000000000008")
RUNTIME_MANIFEST_ID = UUID("50000000-0000-4000-8000-000000000009")
RUNTIME_OPTION_ID = UUID("50000000-0000-4000-8000-000000000010")
_OPTION_KEYS: dict[UUID, str] = {}
_RUNTIME_OPTION_KEYS: dict[str, str] = {}


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **values: int) -> datetime:
        self.value += timedelta(**values)
        return self.value


class PrincipalServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self.principal = principal

    def require_project_role(
        self,
        authentication: object,
        *,
        project_id: UUID,
        allowed_roles: frozenset[str],
    ) -> AccessPrincipal:
        del authentication
        roles = {
            membership.role
            for membership in self.principal.memberships
            if membership.project_id == project_id
        }
        if not roles.intersection(allowed_roles):
            raise AccessForbidden("project membership does not allow this operation")
        return self.principal


def principal(role: str = "admin", *, project_id: UUID = PROJECT_ID) -> AccessPrincipal:
    return AccessPrincipal(
        identity_id=UUID("40000000-0000-0000-0000-000000000004"),
        actor_id=f"workflow-c-{role}",
        tenant_id=TENANT_ID,
        memberships=(MembershipRecord(project_id, TENANT_ID, role),),
        auth_method="test",
    )


def internal_app(
    *, role: str = "admin"
) -> tuple[object, WorkflowCApi, MutableClock, PrincipalServices]:
    clock = MutableClock()
    api = memory_workflow_c_api(clock=clock)
    services = PrincipalServices(principal(role))
    app = create_api_app(surface="internal", services=services, workflow_c_api=api)
    return app, api, clock, services


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def provider_suite_payload(
    *,
    capture_method: str = "provider_api",
    admission_policy_id: UUID | None = None,
    suite_input_option_key: str | None = None,
) -> dict[str, object]:
    policy_id = admission_policy_id or (
        MANUAL_POLICY_ID if capture_method == "manual_ui" else POLICY_ID
    )
    return {
        "suite_input_option_key": suite_input_option_key
        or _OPTION_KEYS.get(policy_id, "missing-suite-input-option"),
        "repetitions": 10,
        "statistics_method_version": "sampling-statistics-v1",
        "max_planned_tasks": 10,
        "max_daily_tasks": 10,
        "minimum_request_interval_seconds": 2,
        "max_concurrency": 2,
    }


def provider_admission_policy_payload(
    *,
    capture_method: str = "provider_api",
) -> dict[str, object]:
    return {
        "runtime_authorization_option_key": _RUNTIME_OPTION_KEYS.get(
            capture_method,
            "missing-runtime-authorization-option",
        ),
        "purpose": "geo_measurement",
        "valid_until": (NOW + timedelta(days=30)).isoformat(),
        "quota_remaining": 10,
        "daily_task_limit": 10,
        "minimum_request_interval_seconds": 2,
        "max_concurrency": 2,
    }


def install_provider_policy(api: WorkflowCApi) -> None:
    install_admission_runtime_option(api)
    created = api.sampling.create_admission_policy(
        project_id=PROJECT_ID,
        actor_id="policy-maker",
        idempotency_key="provider-policy:one",
        payload=CreateAdmissionPolicyRequest.model_validate(
            provider_admission_policy_payload()
        ),
    )
    submitted = api.sampling.submit_admission_policy(
        project_id=PROJECT_ID,
        policy_id=created.record.id,
        actor_id="policy-maker",
        idempotency_key="provider-policy:submit",
        payload=AdmissionPolicySubmitRequest(expected_version=created.record.aggregate_version),
    )
    approved = api.sampling.decide_admission_policy(
        project_id=PROJECT_ID,
        policy_id=created.record.id,
        actor_id="policy-checker",
        idempotency_key="provider-policy:approve",
        payload=AdmissionPolicyDecisionRequest(
            expected_version=submitted.record.aggregate_version,
            reason="Provider API terms and operating limits reviewed.",
        ),
        approved=True,
    )
    assert approved.record.id == POLICY_ID
    install_suite_inputs(api, approved.record.id, approved.record.definition_hash)


def install_manual_policy(
    api: WorkflowCApi,
    *,
    source_platform: str = "openai",
    source_surface: str = "web_search",
    adapter_release: str = "openai-web-search@2026-07-23",
) -> None:
    install_admission_runtime_option(
        api,
        capture_method=CaptureMethod.MANUAL_UI,
        platform=source_platform,
        adapter_release=adapter_release,
    )
    created = api.sampling.create_admission_policy(
        project_id=PROJECT_ID,
        actor_id="policy-maker",
        idempotency_key="manual-policy:one",
        payload=CreateAdmissionPolicyRequest.model_validate(
            provider_admission_policy_payload(capture_method="manual_ui")
        ),
    )
    submitted = api.sampling.submit_admission_policy(
        project_id=PROJECT_ID,
        policy_id=created.record.id,
        actor_id="policy-maker",
        idempotency_key="manual-policy:submit",
        payload=AdmissionPolicySubmitRequest(expected_version=created.record.aggregate_version),
    )
    approved = api.sampling.decide_admission_policy(
        project_id=PROJECT_ID,
        policy_id=created.record.id,
        actor_id="policy-checker",
        idempotency_key="manual-policy:approve",
        payload=AdmissionPolicyDecisionRequest(
            expected_version=submitted.record.aggregate_version,
            reason="Manual evidence workflow and operating limits reviewed.",
        ),
        approved=True,
    )
    assert approved.record.id == MANUAL_POLICY_ID
    install_suite_inputs(
        api,
        approved.record.id,
        approved.record.definition_hash,
        capture_method=CaptureMethod.MANUAL_UI,
        platform=source_platform,
        surface=source_surface,
        adapter_release=adapter_release,
    )


def install_admission_runtime_option(
    api: WorkflowCApi,
    *,
    capture_method: CaptureMethod = CaptureMethod.PROVIDER_API,
    platform: str = "openai",
    adapter_release: str = "openai-web-search@2026-07-23",
) -> str:
    option_key = f"runtime-option-{capture_method.value}"
    _RUNTIME_OPTION_KEYS[capture_method.value] = option_key
    api.sampling.policies.install_runtime_option(
        project_id=PROJECT_ID,
        option=SamplingAdmissionRuntimeOption(
            option_key=option_key,
            display_name=(
                "OpenAI manual evidence authorization"
                if capture_method is CaptureMethod.MANUAL_UI
                else "OpenAI Web Search API authorization"
            ),
            platform=platform,
            capture_method=capture_method,
            adapter_release=adapter_release,
            location_control=(
                "not_controlled"
                if capture_method is CaptureMethod.MANUAL_UI
                else "country"
            ),
            location_evidence_hash=digest(
                "location-evidence:manual-not-controlled"
                if capture_method is CaptureMethod.MANUAL_UI
                else "location-evidence:au-country"
            ),
            authorization_reference="authorization:provider-api:42",
            allowed_purposes=("geo_measurement",),
        ),
    )
    return option_key


def install_suite_inputs(
    api: WorkflowCApi,
    policy_id: UUID,
    policy_hash: str,
    *,
    capture_method: CaptureMethod = CaptureMethod.PROVIDER_API,
    platform: str = "openai",
    surface: str = "web_search",
    adapter_release: str = "openai-web-search@2026-07-23",
) -> None:
    manual = capture_method is CaptureMethod.MANUAL_UI
    option_key = f"suite-option-{uuid5(SAMPLING_API_NAMESPACE, str(policy_id))}"
    _OPTION_KEYS[policy_id] = option_key
    api.sampling.install_suite_inputs(
        project_id=PROJECT_ID,
        resolved=ResolvedSamplingSuiteInputs(
            option_key=option_key,
            display_name=(
                "OpenAI manual UI / en-AU"
                if manual
                else "OpenAI Web Search API / en-AU"
            ),
            question_set_id=QUESTION_SET_ID,
            question_set_version="question-set-v1",
            question_set_hash=digest("question-set"),
            questions=(SamplingQuestion("q-1", "v1", digest("question-1")),),
            adapter_release_id=ADAPTER_RELEASE_ID,
            adapter_release_hash=digest("adapter-release"),
            model_release_id=MODEL_RELEASE_ID,
            model_release_hash=digest("model-release"),
            route_policy_id=ROUTE_POLICY_ID,
            route_policy_hash=digest(f"route-policy:{capture_method.value}"),
            runtime_manifest_id=RUNTIME_MANIFEST_ID,
            runtime_manifest_hash=digest("runtime-manifest"),
            runtime_option_id=RUNTIME_OPTION_ID,
            runtime_option_hash=digest(f"runtime-option:{capture_method.value}"),
            admission_policy_id=policy_id,
            admission_policy_hash=policy_hash,
            source_stratum=SamplingSourceStratum(
                platform=platform,
                surface=surface,
                configured_model="gpt-5-mini",
                reported_model="gpt-5-mini-2026-07-01",
                capture_method=capture_method,
                adapter_release=adapter_release,
                locale="en-AU",
                region="not_controlled" if manual else "AU",
                language="en",
                search_mode="enabled",
                account_cohort="manual-au-account" if manual else "not_applicable",
                egress_policy_category=(
                    "operator-verified-manual" if manual else "not_applicable"
                ),
                location_control="not_controlled" if manual else "country",
                location_evidence_hash=digest(
                    "location-evidence:manual-not-controlled"
                    if manual
                    else "location-evidence:au-country"
                ),
                requested_country=None if manual else "AU",
                requested_region=None,
                requested_locale="en-AU",
                requested_language="en",
                effective_country=None if manual else "AU",
                effective_region=None,
                effective_locale=None,
                effective_language=None,
            ),
        ),
    )
