"""Internal Admin routes for consumer-surface Browser Capture configuration."""

from __future__ import annotations

import json
from typing import Annotated, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, Header, Request, status

from geo_api.browser_capture_contracts import (
    BrowserCaptureInventoryResponse,
    BrowserCaptureAttemptResponse,
    AustralianEgressSetupResponse,
    BrowserCaptureBootstrapResponse,
    BrowserEgressTestResponse,
    BrowserCaptureReadinessResponse,
    BrowserProfileResponse,
    BrowserSessionSetupResponse,
    BrowserSamplingOptionResponse,
    BootstrapBrowserCaptureRequest,
    ConfigureAustralianEgressRequest,
    ConfigureBrowserSessionRequest,
    CreateBrowserProfileRequest,
    CreateEgressEndpointRequest,
    CreateSurfaceReleaseRequest,
    EnqueueBrowserCaptureAttemptRequest,
    EgressEndpointResponse,
    RegisterBrowserSamplingOptionRequest,
    RegisterBrowserSuiteInputRequest,
    SetEgressEndpointStatusRequest,
    SurfaceReleaseResponse,
)
from geo_api.catalog_routes import _principal
from geo_api.connector_routes import _require_admin
from geo_api.foundation_services import FoundationServiceUnavailable
from geo_api.problems import ApiProblem
from geo_api.stable_routes import PROBLEM_RESPONSES
from geo_api.workflow_c_runtime import WorkflowCApi
from geo_api.workflow_c_sampling_catalog import ResolvedSamplingSuiteInputs
from geo_api.workflow_c_sampling_contracts import SamplingSuiteInputOptionResponse
from geo_api.secret_store_runtime import SecretStoreApi
from geo_core.browser_capture import BrowserCaptureAttemptAdmissionService, BrowserCaptureError
from geo_core.browser_capture.admin import BrowserCaptureAdminService
from geo_core.browser_capture.session_state import validate_browser_storage_state
from geo_core.connectors.contracts import canonical_hash
from geo_core.secrets import SecretStoreError, SecretValue
from geo_core.sampling import (
    CaptureMethod,
    LocationControl,
    SamplingConflict,
    SamplingQuestion,
    SamplingSourceStratum,
)


AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key")]
_BROWSER_EGRESS_SECRET_NAMESPACE = UUID("6a603035-688c-5b05-b660-58a3d364a40b")
_BROWSER_SESSION_SECRET_NAMESPACE = UUID("4dc5c7af-34f9-5f85-a798-9f88db96a253")

def browser_capture_router() -> APIRouter:
    router = APIRouter(
        prefix="/v1/projects/{project_id}/browser-capture",
        tags=["browser capture"],
        responses=PROBLEM_RESPONSES,
    )

    @router.post(
        "/bootstrap",
        response_model=BrowserCaptureBootstrapResponse,
        operation_id="bootstrapBuiltinBrowserCapture",
    )
    def bootstrap_builtin_browser_capture(
        project_id: UUID,
        payload: BootstrapBrowserCaptureRequest,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BrowserCaptureBootstrapResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return BrowserCaptureBootstrapResponse.model_validate(
            _call(
                lambda: _service(request).bootstrap_builtin_surfaces(
                    project_id=project_id,
                    actor_id=principal.identity_id,
                    surfaces=payload.surfaces,
                )
            )
        )

    @router.get(
        "/readiness",
        response_model=BrowserCaptureReadinessResponse,
        operation_id="getBrowserCaptureReadiness",
    )
    def browser_capture_readiness(
        project_id: UUID,
        request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BrowserCaptureReadinessResponse:
        _require_admin(_principal(request, authorization), project_id)
        return BrowserCaptureReadinessResponse.model_validate(
            _call(lambda: _service(request).readiness(project_id=project_id))
        )

    @router.post(
        "/egress-setup",
        response_model=AustralianEgressSetupResponse,
        operation_id="configureAustralianBrowserEgress",
    )
    def configure_australian_egress(
        project_id: UUID,
        payload: ConfigureAustralianEgressRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> AustralianEgressSetupResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        key = idempotency_key.strip()
        if len(key) < 8 or len(key) > 240:
            raise ApiProblem(
                status=422,
                title="Invalid Idempotency Key",
                detail="AU proxy setup needs an Idempotency-Key between 8 and 240 characters.",
                type_uri="urn:geo:problem:browser-egress-idempotency",
            )
        reference_id = uuid5(
            _BROWSER_EGRESS_SECRET_NAMESPACE, f"{project_id}:{key}:credential"
        )
        try:
            created = _secret_api(request).create(
                principal,
                project_id=project_id,
                reference_id=reference_id,
                purpose="browser_egress.au",
                value=SecretValue(
                    json.dumps(
                        {
                            "username_template": payload.username_template,
                            "password": payload.password.get_secret_value(),
                            "lease_ttl_seconds": payload.lease_ttl_seconds,
                        },
                        ensure_ascii=True,
                        separators=(",", ":"),
                    )
                ),
                expected_version=0,
                idempotency_key=f"{key}:secret-create",
            )
            verified = _secret_api(request).verify(
                principal,
                project_id=project_id,
                reference_id=reference_id,
                version=created.version,
                expected_version=created.aggregate_version,
                idempotency_key=f"{key}:secret-verify",
            )
            activated = _secret_api(request).activate(
                principal,
                project_id=project_id,
                reference_id=reference_id,
                version=created.version,
                expected_version=verified.aggregate_version,
                idempotency_key=f"{key}:secret-activate",
            )
        except SecretStoreError as error:
            raise ApiProblem(
                status=409,
                title="AU Proxy Secret Setup Failed",
                detail=str(error),
                type_uri="urn:geo:problem:browser-egress-secret",
            ) from error
        endpoint = _call(
            lambda: _service(request).install_egress_endpoint(
                project_id=project_id,
                actor_id=principal.identity_id,
                name=payload.name,
                protocol=payload.protocol,
                endpoint_host=payload.endpoint_host,
                endpoint_port=payload.endpoint_port,
                secret_reference_id=reference_id,
                secret_purpose="browser_egress.au",
                secret_version=activated.version,
                expected_region=payload.expected_region,
                network_type=payload.network_type,
                egress_policy_version="au-consumer-sticky-v1",
                egress_cohort_key=f"au-{payload.network_type}-consumer",
            )
        )
        return AustralianEgressSetupResponse.model_validate(
            {
                "endpoint": endpoint,
                "secret_reference_id": reference_id,
                "secret_version": activated.version,
                "egress_test_required": True,
            }
        )

    @router.post(
        "/session-profile-setup",
        response_model=BrowserSessionSetupResponse,
        operation_id="configureBrowserSessionProfile",
    )
    def configure_browser_session_profile(
        project_id: UUID,
        payload: ConfigureBrowserSessionRequest,
        request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> BrowserSessionSetupResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        key = idempotency_key.strip()
        if len(key) < 8 or len(key) > 240:
            raise ApiProblem(
                status=422,
                title="Invalid Idempotency Key",
                detail="Browser session setup needs an Idempotency-Key between 8 and 240 characters.",
                type_uri="urn:geo:problem:browser-session-idempotency",
            )
        try:
            raw_state = json.loads(payload.storage_state_json.get_secret_value())
            storage_state = validate_browser_storage_state(raw_state)
        except (json.JSONDecodeError, BrowserCaptureError) as error:
            raise ApiProblem(
                status=422,
                title="Invalid Browser Session",
                detail=str(error),
                type_uri="urn:geo:problem:browser-session-invalid",
            ) from error
        reference_id = uuid5(
            _BROWSER_SESSION_SECRET_NAMESPACE, f"{project_id}:{key}:storage-state"
        )
        try:
            created = _secret_api(request).create(
                principal,
                project_id=project_id,
                reference_id=reference_id,
                purpose="browser_session.storage_state",
                value=SecretValue(
                    json.dumps(storage_state, ensure_ascii=True, separators=(",", ":"))
                ),
                expected_version=0,
                idempotency_key=f"{key}:secret-create",
            )
            verified = _secret_api(request).verify(
                principal,
                project_id=project_id,
                reference_id=reference_id,
                version=created.version,
                expected_version=created.aggregate_version,
                idempotency_key=f"{key}:secret-verify",
            )
            activated = _secret_api(request).activate(
                principal,
                project_id=project_id,
                reference_id=reference_id,
                version=created.version,
                expected_version=verified.aggregate_version,
                idempotency_key=f"{key}:secret-activate",
            )
        except SecretStoreError as error:
            raise ApiProblem(
                status=409,
                title="Browser Session Secret Setup Failed",
                detail=str(error),
                type_uri="urn:geo:problem:browser-session-secret",
            ) from error
        profile = _call(
            lambda: _service(request).install_session_profile(
                project_id=project_id,
                actor_id=principal.identity_id,
                storage_secret_reference_id=reference_id,
                storage_secret_version=activated.version,
            )
        )
        return BrowserSessionSetupResponse.model_validate(
            {
                "profile": profile,
                "secret_reference_id": reference_id,
                "secret_version": activated.version,
            }
        )

    @router.get("", response_model=BrowserCaptureInventoryResponse)
    def inventory(
        project_id: UUID, request: Request, authorization: AuthorizationHeader = None
    ) -> BrowserCaptureInventoryResponse:
        _require_admin(_principal(request, authorization), project_id)
        return BrowserCaptureInventoryResponse.model_validate(
            _call(lambda: _service(request).inventory(project_id=project_id))
        )

    @router.post(
        "/surface-releases", response_model=SurfaceReleaseResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_surface_release(
        project_id: UUID, payload: CreateSurfaceReleaseRequest, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SurfaceReleaseResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return SurfaceReleaseResponse.model_validate(_call(
            lambda: _service(request).create_surface_release(
                project_id=project_id, actor_id=principal.identity_id,
                **payload.model_dump(),
            )
        ))

    @router.post("/surface-releases/{release_id}/approve", response_model=SurfaceReleaseResponse)
    def approve_surface_release(
        project_id: UUID, release_id: UUID, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SurfaceReleaseResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return SurfaceReleaseResponse.model_validate(_call(
            lambda: _service(request).approve_surface_release(
                project_id=project_id, release_id=release_id,
                reviewer_id=principal.identity_id,
            )
        ))

    @router.post(
        "/surface-releases/{release_id}/retire", response_model=SurfaceReleaseResponse
    )
    def retire_surface_release(
        project_id: UUID, release_id: UUID, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SurfaceReleaseResponse:
        _require_admin(_principal(request, authorization), project_id)
        return SurfaceReleaseResponse.model_validate(_call(
            lambda: _service(request).retire_surface_release(
                project_id=project_id, release_id=release_id,
            )
        ))

    @router.post(
        "/egress-endpoints", response_model=EgressEndpointResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_egress_endpoint(
        project_id: UUID, payload: CreateEgressEndpointRequest, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> EgressEndpointResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return EgressEndpointResponse.model_validate(_call(
            lambda: _service(request).create_egress_endpoint(
                project_id=project_id, actor_id=principal.identity_id,
                **payload.model_dump(),
            )
        ))

    @router.post("/egress-endpoints/{endpoint_id}/approve", response_model=EgressEndpointResponse)
    def approve_egress_endpoint(
        project_id: UUID, endpoint_id: UUID, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> EgressEndpointResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return EgressEndpointResponse.model_validate(_call(
            lambda: _service(request).approve_egress_endpoint(
                project_id=project_id, endpoint_id=endpoint_id,
                reviewer_id=principal.identity_id,
            )
        ))

    @router.post(
        "/egress-endpoints/{endpoint_id}/status", response_model=EgressEndpointResponse
    )
    def set_egress_endpoint_status(
        project_id: UUID, endpoint_id: UUID, payload: SetEgressEndpointStatusRequest,
        request: Request, authorization: AuthorizationHeader = None,
    ) -> EgressEndpointResponse:
        _require_admin(_principal(request, authorization), project_id)
        return EgressEndpointResponse.model_validate(_call(
            lambda: _service(request).set_egress_endpoint_status(
                project_id=project_id, endpoint_id=endpoint_id, status=payload.status,
            )
        ))

    @router.post(
        "/egress-endpoints/{endpoint_id}/tests",
        response_model=BrowserEgressTestResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def test_egress_endpoint(
        project_id: UUID, endpoint_id: UUID, request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> BrowserEgressTestResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return BrowserEgressTestResponse.model_validate(_call(
            lambda: _service(request).test_egress_endpoint(
                project_id=project_id, actor_id=principal.identity_id,
                endpoint_id=endpoint_id, idempotency_key=idempotency_key,
            )
        ))

    @router.post(
        "/profiles", response_model=BrowserProfileResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_profile(
        project_id: UUID, payload: CreateBrowserProfileRequest, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BrowserProfileResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return BrowserProfileResponse.model_validate(_call(
            lambda: _service(request).create_profile(
                project_id=project_id, actor_id=principal.identity_id,
                **payload.model_dump(),
            )
        ))

    @router.post("/profiles/{profile_id}/approve", response_model=BrowserProfileResponse)
    def approve_profile(
        project_id: UUID, profile_id: UUID, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BrowserProfileResponse:
        principal = _require_admin(_principal(request, authorization), project_id)
        return BrowserProfileResponse.model_validate(_call(
            lambda: _service(request).approve_profile(
                project_id=project_id, profile_id=profile_id,
                reviewer_id=principal.identity_id,
            )
        ))

    @router.post(
        "/sampling-options",
        response_model=BrowserSamplingOptionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="registerBrowserSamplingRuntimeOption",
    )
    def register_sampling_runtime_option(
        project_id: UUID, payload: RegisterBrowserSamplingOptionRequest, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> BrowserSamplingOptionResponse:
        _require_admin(_principal(request, authorization), project_id)
        return BrowserSamplingOptionResponse.model_validate(_call(
            lambda: _service(request).register_sampling_runtime_option(
                project_id=project_id, **payload.model_dump()
            )
        ))

    @router.post(
        "/sampling-suite-inputs",
        response_model=SamplingSuiteInputOptionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="registerBrowserSamplingSuiteInput",
    )
    def register_sampling_suite_input(
        project_id: UUID, payload: RegisterBrowserSuiteInputRequest, request: Request,
        authorization: AuthorizationHeader = None,
    ) -> SamplingSuiteInputOptionResponse:
        _require_admin(_principal(request, authorization), project_id)
        material = _call(lambda: _service(request).sampling_input_material(
            project_id=project_id,
            question_set_id=payload.question_set_id,
            admission_policy_id=payload.admission_policy_id,
            surface_release_id=payload.surface_release_id,
            egress_endpoint_id=payload.egress_endpoint_id,
            profile_version_id=payload.profile_version_id,
        ))
        source = SamplingSourceStratum(
            platform=str(material["surface"]["platform"]),
            surface=str(material["surface"]["surface"]),
            configured_model="not_applicable",
            reported_model="not_applicable",
            capture_method=CaptureMethod.AUTOMATED_UI,
            adapter_release=str(material["option"]["adapter_release"]),
            locale="en-AU", region="AU", language="en", search_mode="enabled",
            account_cohort=str(material["profile"]["account_cohort"]),
            egress_policy_category=(
                f"{material['endpoint']['network_type']}:"
                f"{material['endpoint']['egress_policy_version']}:"
                f"{material['endpoint']['egress_cohort_key']}"
            ),
            location_control=LocationControl.COUNTRY,
            location_evidence_hash=str(material["option"]["location_evidence_hash"]),
            requested_country="AU", requested_region=None, requested_locale="en-AU",
            requested_language="en", effective_country="AU", effective_region=None,
            effective_locale=None, effective_language=None,
        )
        question_version = f"v{material['question_set']['version_number']}"
        questions = tuple(
            SamplingQuestion(str(item["id"]), question_version, str(item["query_text_hash"]))
            for item in material["questions"]
        )
        endpoint_hash = canonical_hash({
            key: material["endpoint"][key]
            for key in (
                "id", "network_type", "sticky_mode", "egress_policy_version",
                "egress_cohort_key", "expected_country", "expected_region",
            )
        })
        resolved = ResolvedSamplingSuiteInputs(
            option_key=payload.option_key,
            display_name=payload.display_name,
            question_set_id=payload.question_set_id,
            question_set_version=question_version,
            question_set_hash=str(material["question_set"]["content_hash"]),
            questions=questions,
            adapter_release_id=payload.surface_release_id,
            adapter_release_hash=str(material["surface"]["release_hash"]),
            model_release_id=payload.profile_version_id,
            model_release_hash=str(material["profile"]["profile_hash"]),
            route_policy_id=payload.egress_endpoint_id,
            route_policy_hash=endpoint_hash,
            runtime_manifest_id=payload.surface_release_id,
            runtime_manifest_hash=str(material["surface"]["release_hash"]),
            runtime_option_id=payload.profile_version_id,
            runtime_option_hash=str(material["profile"]["profile_hash"]),
            admission_policy_id=payload.admission_policy_id,
            admission_policy_hash=str(material["policy"]["definition_hash"]),
            source_stratum=source,
        )
        try:
            _workflow_api(request).sampling.install_suite_inputs(
                project_id=project_id, resolved=resolved
            )
        except SamplingConflict as error:
            raise ApiProblem(
                status=409, title="Browser Sampling Input Conflict", detail=str(error),
                type_uri="urn:geo:problem:browser-sampling-input-conflict",
            ) from error
        return SamplingSuiteInputOptionResponse.model_validate({
            "option_key": resolved.option_key,
            "display_name": resolved.display_name,
            "question_set_id": resolved.question_set_id,
            "question_set_version": resolved.question_set_version,
            "question_set_hash": resolved.question_set_hash,
            "question_count": len(questions),
            "question_set_item_ids": [question.question_id for question in questions],
            "adapter_release_id": resolved.adapter_release_id,
            "adapter_release_hash": resolved.adapter_release_hash,
            "model_release_id": resolved.model_release_id,
            "model_release_hash": resolved.model_release_hash,
            "route_policy_id": resolved.route_policy_id,
            "route_policy_hash": resolved.route_policy_hash,
            "runtime_manifest_id": resolved.runtime_manifest_id,
            "runtime_manifest_hash": resolved.runtime_manifest_hash,
            "runtime_option_id": resolved.runtime_option_id,
            "runtime_option_hash": resolved.runtime_option_hash,
            "admission_policy_id": resolved.admission_policy_id,
            "admission_policy_hash": resolved.admission_policy_hash,
            "source_stratum": {
                **source.canonical_value(), "stratum_hash": source.stratum_hash,
            },
        })

    @router.post(
        "/runs/{run_id}/tasks/{task_id}/attempts",
        response_model=BrowserCaptureAttemptResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id="enqueueBrowserCaptureAttempt",
    )
    def enqueue_capture_attempt(
        project_id: UUID, run_id: UUID, task_id: UUID,
        payload: EnqueueBrowserCaptureAttemptRequest, request: Request,
        idempotency_key: IdempotencyHeader,
        authorization: AuthorizationHeader = None,
    ) -> BrowserCaptureAttemptResponse:
        _require_admin(_principal(request, authorization), project_id)
        return BrowserCaptureAttemptResponse.model_validate(_call(
            lambda: _attempt_service(request).enqueue(
                project_id=project_id, run_id=run_id, task_id=task_id,
                idempotency_key=idempotency_key, **payload.model_dump(),
            )
        ))

    return router


def _service(request: Request) -> BrowserCaptureAdminService:
    service = getattr(request.app.state, "browser_capture_admin_service", None)
    if not isinstance(service, BrowserCaptureAdminService):
        raise FoundationServiceUnavailable("Browser Capture persistence is unavailable.")
    return service


def _workflow_api(request: Request) -> WorkflowCApi:
    api = getattr(request.app.state, "workflow_c_api", None)
    if not isinstance(api, WorkflowCApi):
        raise FoundationServiceUnavailable("Workflow C Sampling persistence is unavailable.")
    return api


def _attempt_service(request: Request) -> BrowserCaptureAttemptAdmissionService:
    service = getattr(request.app.state, "browser_capture_attempt_service", None)
    if not isinstance(service, BrowserCaptureAttemptAdmissionService):
        raise FoundationServiceUnavailable("Browser Capture admission is unavailable.")
    return service


def _secret_api(request: Request) -> SecretStoreApi:
    application = getattr(request.app.state, "secret_store_application", None)
    if application is None:
        raise FoundationServiceUnavailable("Secret Store persistence is unavailable.")
    return cast(SecretStoreApi, application)


def _call(operation):
    try:
        return operation()
    except BrowserCaptureError as error:
        raise ApiProblem(
            status=409,
            title="Browser Capture State Conflict",
            detail=str(error),
            type_uri="urn:geo:problem:browser-capture-conflict",
        ) from error


__all__ = ["browser_capture_router"]
