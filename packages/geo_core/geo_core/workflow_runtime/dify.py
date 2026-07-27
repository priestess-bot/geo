"""Blocking Dify Workflow API adapter with durable GEO lineage."""

from __future__ import annotations

import json
import re
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import StructuredOutputValidationError
from geo_core.model_gateway.schema_validation import validate_structured_output
from geo_core.secrets import SecretStoreError, SecretValue, SecretVersionHandle

from .contracts import (
    WorkflowExecutionRequest,
    WorkflowExecutionResult,
    WorkflowRuntimeRelease,
    canonical_json_hash,
    canonical_json_value,
)
from .errors import (
    RetryableWorkflowExecutionError,
    WorkflowAuthenticationError,
    WorkflowConfigurationError,
    WorkflowContractError,
    WorkflowExecutionError,
)
from .published import DifyPublishedWorkflowReader, PublishedWorkflowSnapshot
from .dify_response import parse_result, response_lineage


class CredentialResolver(Protocol):
    def resolve(self, handle: SecretVersionHandle) -> SecretValue: ...


class WorkflowRuntimeRepository(Protocol):
    def resolve_active(
        self, *, project_id: UUID, purpose: str
    ) -> WorkflowRuntimeRelease | None: ...

    def get_release(self, *, project_id: UUID, release_id: UUID) -> WorkflowRuntimeRelease: ...

    def begin_business_attempt(
        self,
        lease: WorkerLease,
        *,
        release: WorkflowRuntimeRelease,
        published_snapshot_id: UUID | None = None,
        context_hash: str,
        request_hash: str,
    ) -> UUID: ...
    def finish_business_attempt(
        self, lease: WorkerLease, *, attempt_id: UUID, values: Mapping[str, object]
    ) -> None: ...
    def begin_canary_attempt(
        self,
        *,
        release: WorkflowRuntimeRelease,
        published_snapshot_id: UUID | None = None,
        context_hash: str,
        request_hash: str,
    ) -> UUID: ...
    def finish_canary_attempt(
        self,
        *,
        project_id: UUID,
        attempt_id: UUID,
        values: Mapping[str, object],
    ) -> None: ...
    def record_published_snapshot(
        self,
        *,
        release: WorkflowRuntimeRelease,
        snapshot: PublishedWorkflowSnapshot,
    ) -> UUID: ...


class DifyWorkflowExecutor:
    """Execute an active Dify release or return ``None`` when none was activated.

    ``None`` is the sole native-runtime rollback signal. Once a Dify binding
    exists, every configuration, credential, network, provider or output error
    is surfaced and recorded; it never falls through to the native model path.
    """

    provider = "dify"

    def __init__(
        self,
        *,
        repository: WorkflowRuntimeRepository,
        credential_resolver: CredentialResolver,
        base_url: str,
        timeout_seconds: float = 180.0,
        client: httpx.Client | None = None,
        published_reader: DifyPublishedWorkflowReader | None = None,
        require_active: bool = False,
    ) -> None:
        self._repository = repository
        self._credentials = credential_resolver
        self._base_url = _base_url(base_url)
        self._timeout = timeout_seconds
        self._client = client
        self._published_reader = published_reader
        self._require_active = require_active

    def execute_optional(
        self, lease: WorkerLease, request: WorkflowExecutionRequest
    ) -> WorkflowExecutionResult | None:
        if lease.project_id != request.project_id:
            raise WorkflowContractError("workflow request crossed its Job project boundary")
        release = self._repository.resolve_active(
            project_id=request.project_id, purpose=request.purpose
        )
        if release is None:
            if self._require_active:
                raise WorkflowConfigurationError(
                    f"Dify has no active workflow for {request.purpose}",
                    code="dify_workflow_not_configured",
                )
            return None
        return self._execute(release=release, request=request, lease=lease)

    def execute_canary(
        self,
        *,
        project_id: UUID,
        release_id: UUID,
        request: WorkflowExecutionRequest,
        validate_output: Callable[[Mapping[str, object]], None],
    ) -> WorkflowExecutionResult:
        if request.project_id != project_id:
            raise WorkflowContractError("Dify canary request crossed its project boundary")
        release = self._repository.get_release(project_id=project_id, release_id=release_id)
        if release.purpose != request.purpose:
            raise WorkflowContractError("Dify canary purpose does not match its release")
        return self._execute(
            release=release,
            request=request,
            lease=None,
            validate_output=validate_output,
        )

    def _execute(
        self,
        *,
        release: WorkflowRuntimeRelease,
        request: WorkflowExecutionRequest,
        lease: WorkerLease | None,
        validate_output: Callable[[Mapping[str, object]], None] | None = None,
    ) -> WorkflowExecutionResult:
        self._validate_release_request(release, request)
        snapshot = self._read_published_snapshot(release)
        published_snapshot_id = (
            self._repository.record_published_snapshot(release=release, snapshot=snapshot)
            if snapshot is not None
            else None
        )
        expected_workflow_id = (
            snapshot.workflow_id if snapshot is not None else release.dify_workflow_id
        )
        context_json = json.dumps(
            canonical_json_value(request.context),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        inputs = {
            "geo_context_json": context_json,
            "geo_context_hash": request.context_hash,
            "geo_input_hash": request.input_hash,
            "geo_output_schema_json": json.dumps(
                canonical_json_value(request.output_schema),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "geo_purpose": request.purpose,
        }
        if snapshot is None:
            program_user_prompt = release.prompt_user_template.replace(
                "{{request_json}}", context_json
            )
            if re.search(r"{{\s*[a-zA-Z0-9_.-]+\s*}}", program_user_prompt):
                raise WorkflowConfigurationError(
                    "frozen Dify Prompt contains an unsupported unresolved slot",
                    code="dify_prompt_slot_unresolved",
                )
            inputs.update(
                {
                    "geo_prompt_system": "\n\n".join(
                        filter(
                            None,
                            map(
                                str.strip,
                                (release.prompt_system_template, request.system_prompt),
                            ),
                        )
                    ),
                    "geo_prompt_user": "\n\n".join(
                        filter(
                            None,
                            map(str.strip, (program_user_prompt, request.user_prompt)),
                        )
                    ),
                }
            )
        payload = {
            "inputs": inputs,
            "response_mode": "blocking",
            "user": (
                f"geo-job:{lease.job_id}" if lease is not None else f"geo-canary:{release.id}"
            ),
        }
        request_hash = canonical_json_hash(
            {
                "runtime_release_hash": release.release_hash,
                "workflow_id": expected_workflow_id,
                "published_snapshot_hash": (
                    snapshot.snapshot_hash if snapshot is not None else None
                ),
                "payload": payload,
            }
        )
        attempt_id = (
            self._repository.begin_business_attempt(
                lease,
                release=release,
                published_snapshot_id=published_snapshot_id,
                context_hash=request.context_hash,
                request_hash=request_hash,
            )
            if lease is not None
            else self._repository.begin_canary_attempt(
                release=release,
                published_snapshot_id=published_snapshot_id,
                context_hash=request.context_hash,
                request_hash=request_hash,
            )
        )
        result: WorkflowExecutionResult | None = None
        lineage: Mapping[str, str | None] = {
            "dify_task_id": None,
            "dify_run_id": None,
            "reported_workflow_id": None,
        }
        status_code: int | None = None
        try:
            token = self._resolve_token(release)
            body, status_code = self._post(release, payload, token)
            lineage = response_lineage(body)
            result = parse_result(
                body,
                release=release,
                expected_workflow_id=expected_workflow_id,
                attempt_id=attempt_id,
            )
            if (
                request.output_schema.get("x-geo-runtime-contract")
                != "application-validated-json-object-v1"
            ):
                try:
                    validate_structured_output(result.output, request.output_schema)
                except StructuredOutputValidationError as exc:
                    raise WorkflowContractError(
                        f"Dify output does not match the business schema: {exc}",
                        code="dify_business_schema_invalid",
                    ) from exc
            if validate_output is not None:
                validate_output(result.output)
        except Exception as raw_error:
            error = _classified_error(raw_error)
            values: Mapping[str, object] = {
                "status": "failed",
                "dify_task_id": (
                    result.dify_task_id if result is not None else lineage["dify_task_id"]
                ),
                "dify_run_id": (
                    result.dify_run_id if result is not None else lineage["dify_run_id"]
                ),
                "reported_workflow_id": (
                    expected_workflow_id if result is not None else lineage["reported_workflow_id"]
                ),
                "http_status": status_code or getattr(error, "http_status", None),
                "error_classification": error.classification,
                "error_code": error.code,
                "error_message": str(error),
                "retryable": error.retryable,
            }
            self._finish(lease, release.project_id, attempt_id, values)
            raise error from raw_error if error is not raw_error else None
        assert result is not None and status_code is not None
        self._finish(
            lease,
            release.project_id,
            attempt_id,
            {
                "status": "succeeded",
                "dify_task_id": result.dify_task_id,
                "dify_run_id": result.dify_run_id,
                "reported_workflow_id": expected_workflow_id,
                "output_hash": result.response_hash,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_steps": result.total_steps,
                "elapsed_seconds": result.elapsed_seconds,
                "http_status": status_code,
            },
        )
        return result

    def _read_published_snapshot(
        self, release: WorkflowRuntimeRelease
    ) -> PublishedWorkflowSnapshot | None:
        if self._published_reader is None:
            return None
        return self._published_reader.read(
            purpose=release.purpose,
            app_id=release.dify_app_id,
        )

    def _finish(
        self,
        lease: WorkerLease | None,
        project_id: UUID,
        attempt_id: UUID,
        values: Mapping[str, object],
    ) -> None:
        if lease is not None:
            self._repository.finish_business_attempt(lease, attempt_id=attempt_id, values=values)
        else:
            self._repository.finish_canary_attempt(
                project_id=project_id, attempt_id=attempt_id, values=values
            )

    def _resolve_token(self, release: WorkflowRuntimeRelease) -> str:
        try:
            secret = self._credentials.resolve(release.api_secret_handle)
            if not isinstance(secret, SecretValue):
                raise WorkflowAuthenticationError("Secret Store returned an invalid Dify key")
            return secret.reveal_text()
        except WorkflowExecutionError:
            raise
        except (SecretStoreError, ValueError) as exc:
            raise WorkflowAuthenticationError(
                "Dify API key could not be resolved from its frozen Secret Store version",
                code="dify_secret_resolution_failed",
            ) from exc

    def _post(
        self,
        release: WorkflowRuntimeRelease,
        payload: Mapping[str, object],
        token: str,
    ) -> tuple[Mapping[str, object], int]:
        endpoint = f"{self._base_url}/v1/workflows/run"
        client = self._client or httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=min(10.0, self._timeout)),
            trust_env=False,
        )
        close = self._client is None
        try:
            response = client.post(
                endpoint,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableWorkflowExecutionError(
                "Dify is unreachable or timed out; retry the same GEO Job",
                code="dify_transport_unavailable",
            ) from exc
        finally:
            if close:
                client.close()
        if response.status_code >= 400:
            raise _http_error(response.status_code, _safe_error_detail(response))
        try:
            body = response.json()
        except ValueError as exc:
            raise WorkflowContractError(
                "Dify returned non-JSON output", code="dify_response_not_json"
            ) from exc
        if not isinstance(body, Mapping):
            raise WorkflowContractError(
                "Dify response root is not an object", code="dify_response_shape_invalid"
            )
        return body, response.status_code

    @staticmethod
    def _validate_release_request(
        release: WorkflowRuntimeRelease, request: WorkflowExecutionRequest
    ) -> None:
        if release.project_id != request.project_id or release.purpose != request.purpose:
            raise WorkflowContractError("Dify release does not match the workflow request")
        if release.input_schema_hash != canonical_json_hash(release.input_schema):
            raise WorkflowConfigurationError(
                "Dify input schema hash no longer matches", code="dify_input_schema_changed"
            )
        if release.output_schema_hash != canonical_json_hash(release.output_schema):
            raise WorkflowConfigurationError(
                "Dify output schema hash no longer matches", code="dify_output_schema_changed"
            )
        dynamic_contract = (
            release.output_schema.get("x-geo-runtime-contract")
            == "application-validated-json-object-v1"
        )
        if not dynamic_contract and release.output_schema_hash != canonical_json_hash(
            request.output_schema
        ):
            raise WorkflowConfigurationError(
                "business output contract differs from the active Dify release",
                code="dify_business_schema_stale",
            )


def _classified_error(error: Exception) -> WorkflowExecutionError:
    if isinstance(error, WorkflowExecutionError):
        return error
    return WorkflowExecutionError(
        "Dify execution failed unexpectedly; inspect the workflow attempt",
        code=type(error).__name__,
    )


def _http_error(status: int, detail: str) -> WorkflowExecutionError:
    error: WorkflowExecutionError
    if status in {401, 403}:
        error = WorkflowAuthenticationError(
            "Dify rejected the configured API key", code="dify_auth_rejected"
        )
    elif status == 429 or status >= 500:
        error = RetryableWorkflowExecutionError(
            f"Dify returned HTTP {status}: {detail}", code="dify_http_retryable"
        )
    elif status == 404:
        error = WorkflowConfigurationError(
            "Dify workflow endpoint or app was not found", code="dify_workflow_not_found"
        )
    else:
        error = WorkflowContractError(
            f"Dify rejected the workflow input with HTTP {status}: {detail}",
            code="dify_request_rejected",
        )
    error.http_status = status  # type: ignore[attr-defined]
    return error


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        value = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(value, Mapping):
        return str(value.get("message") or value.get("code") or "request failed")[:500]
    return "request failed"


def _base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise WorkflowConfigurationError(
            "GEO_DIFY_API_URL must be one HTTP(S) origin without credentials or a path"
        )
    return normalized
