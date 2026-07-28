"""Blocking Dify Workflow API adapter with durable GEO lineage."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Callable, Mapping
from uuid import UUID

import httpx

from geo_core.jobs.postgres import WorkerLease
from geo_core.model_gateway.contracts import StructuredOutputValidationError
from geo_core.model_gateway.schema_validation import validate_structured_output
from geo_core.secrets import SecretStoreError, SecretValue

from .contracts import (
    WorkflowExecutionRequest,
    WorkflowExecutionResult,
    WorkflowRuntimeRelease,
    canonical_json_hash,
    canonical_json_value,
)
from .errors import (
    RetryableWorkflowExecutionError,
    UnknownWorkflowOutcomeError,
    WorkflowAuthenticationError,
    WorkflowConfigurationError,
    WorkflowContractError,
    WorkflowExecutionError,
)
from .published import (
    DifyPublishedWorkflowReader,
    PublishedWorkflowSnapshot,
    PublishedWorkflowSnapshotPin,
)
from .dify_response import parse_result, response_lineage
from .dify_ports import CredentialResolver, WorkflowRuntimeRepository
from .dify_transport import (
    classified_error,
    http_error,
    safe_error_detail,
    validated_base_url,
)


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
        self._base_url = validated_base_url(base_url)
        self._timeout = timeout_seconds
        self._client = client
        self._published_reader = published_reader
        self._require_active = require_active

    def execute_optional(
        self,
        lease: WorkerLease,
        request: WorkflowExecutionRequest,
        *,
        validate_output: Callable[[Mapping[str, object]], None] | None = None,
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
        return self._execute(
            release=release,
            request=request,
            lease=lease,
            validate_output=validate_output,
        )

    def execute_frozen(
        self,
        lease: WorkerLease,
        request: WorkflowExecutionRequest,
        *,
        release_id: UUID,
        release_hash: str,
        validate_output: Callable[[Mapping[str, object]], None] | None = None,
    ) -> WorkflowExecutionResult:
        if lease.project_id != request.project_id:
            raise WorkflowContractError("frozen workflow request crossed its Job project boundary")
        release = self._repository.get_release(
            project_id=request.project_id,
            release_id=release_id,
        )
        if (
            release.release_hash != release_hash
            or release.project_id != request.project_id
            or release.purpose != request.purpose
        ):
            raise WorkflowConfigurationError(
                "frozen Dify Workflow Release lineage changed",
                code="dify_frozen_release_mismatch",
            )
        return self._execute(
            release=release,
            request=request,
            lease=lease,
            validate_output=validate_output,
        )

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
        pin = self._repository.load_published_snapshot_pin(release=release)
        if pin is None and lease is not None:
            raise WorkflowConfigurationError(
                "Dify Workflow Release has no successful canary snapshot pin; run the "
                "canary before business execution",
                code="dify_release_snapshot_not_pinned",
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
        payload = {
            "inputs": inputs,
            "response_mode": "blocking",
            "user": (
                f"geo-job:{lease.job_id}" if lease is not None else f"geo-canary:{release.id}"
            ),
        }
        snapshot: PublishedWorkflowSnapshot | None = None
        published_snapshot_id: UUID | None = None
        if pin is None:
            snapshot = self._read_published_snapshot(release)
            self._validate_published_snapshot(release, snapshot)
            published_snapshot_id = self._repository.record_published_snapshot(
                release=release, snapshot=snapshot
            )
            expected_workflow_id = snapshot.workflow_id
            expected_snapshot_hash = snapshot.snapshot_hash
        else:
            expected_workflow_id = pin.workflow_id
            expected_snapshot_hash = pin.snapshot_hash
        request_hash = canonical_json_hash(
            {
                "runtime_release_hash": release.release_hash,
                "workflow_id": expected_workflow_id,
                "published_snapshot_hash": expected_snapshot_hash,
                "payload": payload,
            }
        )
        if lease is not None:
            assert pin is not None
            replay = self._repository.load_successful_business_result(
                lease,
                release=release,
                context_hash=request.context_hash,
                request_hash=request_hash,
            )
            if replay is not None:
                if (
                    replay.published_snapshot_id != pin.published_snapshot_id
                    or replay.published_snapshot_hash != pin.snapshot_hash
                ):
                    self._assert_legacy_migration_replay(
                        release=release,
                        replay=replay,
                        pin=pin,
                        payload=payload,
                    )
                if validate_output is not None:
                    validate_output(replay.output)
                return replay
            unresolved_attempt_id = self._repository.find_unresolved_business_attempt(
                lease,
                release=release,
                context_hash=request.context_hash,
                request_hash=request_hash,
            )
            if unresolved_attempt_id is not None:
                raise UnknownWorkflowOutcomeError(
                    "A prior Dify attempt for this exact GEO Job and request is still "
                    "unresolved. The old Job must never submit this workflow again. Inspect "
                    f"Dify history, reconcile GEO attempt {unresolved_attempt_id}, then submit "
                    "a new parent Job with a new replay identity if the operator authorizes it.",
                    code="dify_unknown_outcome",
                )
        if snapshot is None:
            snapshot = self._read_published_snapshot(release)
            self._validate_published_snapshot(release, snapshot)
            published_snapshot_id = self._repository.record_published_snapshot(
                release=release, snapshot=snapshot
            )
            assert pin is not None
            self._assert_snapshot_pin(release, snapshot, pin)
        assert published_snapshot_id is not None
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
        reported_workflow_id: str | None = None
        status_code: int | None = None
        try:
            token = self._resolve_token(release)
            body, status_code = self._post(release, payload, token)
            lineage = response_lineage(body)
            parsed_result = parse_result(
                body,
                release=release,
                expected_workflow_id=expected_workflow_id,
                attempt_id=attempt_id,
            )
            reported_workflow_id = lineage["reported_workflow_id"]
            if reported_workflow_id is None:  # Kept inside attempt failure recording.
                raise WorkflowConfigurationError(
                    "Dify succeeded without reporting the exact published workflow identity",
                    code="dify_workflow_identity_missing",
                )
            result = replace(
                parsed_result,
                published_snapshot_id=published_snapshot_id,
                published_snapshot_hash=snapshot.snapshot_hash,
                published_workflow_id=reported_workflow_id,
                request_hash=request_hash,
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
            error = classified_error(raw_error)
            values: Mapping[str, object] = {
                "status": "failed",
                "dify_task_id": (
                    result.dify_task_id if result is not None else lineage["dify_task_id"]
                ),
                "dify_run_id": (
                    result.dify_run_id if result is not None else lineage["dify_run_id"]
                ),
                "reported_workflow_id": lineage["reported_workflow_id"],
                "http_status": status_code or getattr(error, "http_status", None),
                "error_classification": error.classification,
                "error_code": error.code,
                "error_message": str(error),
                "retryable": error.retryable,
            }
            self._finish(lease, release.project_id, attempt_id, values)
            raise error from raw_error if error is not raw_error else None
        assert result is not None and status_code is not None and reported_workflow_id is not None
        self._finish(
            lease,
            release.project_id,
            attempt_id,
            {
                "status": "succeeded",
                "dify_task_id": result.dify_task_id,
                "dify_run_id": result.dify_run_id,
                "reported_workflow_id": reported_workflow_id,
                "output_hash": result.response_hash,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_steps": result.total_steps,
                "elapsed_seconds": (
                    str(result.elapsed_seconds) if result.elapsed_seconds is not None else None
                ),
                "http_status": status_code,
                "output": result.output,
                "response_hash": result.response_hash,
                "configured_model": result.configured_model,
                "provider_reported_model": result.provider_reported_model,
            },
        )
        return result

    def _read_published_snapshot(
        self, release: WorkflowRuntimeRelease
    ) -> PublishedWorkflowSnapshot:
        if self._published_reader is None:
            raise WorkflowConfigurationError(
                "Dify published workflow verification is required for execution",
                code="dify_published_reader_required",
            )
        return self._published_reader.read(
            purpose=release.purpose,
            app_id=release.dify_app_id,
        )

    @staticmethod
    def _validate_published_snapshot(
        release: WorkflowRuntimeRelease,
        snapshot: PublishedWorkflowSnapshot,
    ) -> None:
        if snapshot.purpose != release.purpose or snapshot.app_id != release.dify_app_id:
            raise WorkflowConfigurationError(
                "published Dify graph does not match its Workflow Release",
                code="dify_snapshot_release_mismatch",
            )
        if (
            snapshot.workflow_hash != release.registered_workflow_hash
            or snapshot.snapshot_hash != release.registered_snapshot_hash
        ):
            raise WorkflowConfigurationError(
                "published Dify graph differs from this registered GEO Workflow Release; "
                "verify the console state and enroll a new release before canary",
                code="dify_registered_published_identity_changed",
            )
        if not snapshot.prompt_nodes:
            raise WorkflowConfigurationError(
                "published Dify graph has no LLM node to verify",
                code="dify_published_model_missing",
            )
        for node in snapshot.prompt_nodes:
            if (
                str(node.get("model_provider") or "").strip() != release.model_provider
                or str(node.get("model_name") or "").strip() != release.configured_model
            ):
                raise WorkflowConfigurationError(
                    "published Dify graph changed its frozen model provider or model name; "
                    "register and canary a new GEO Workflow Release",
                    code="dify_published_model_mismatch",
                )

    @staticmethod
    def _assert_snapshot_pin(
        release: WorkflowRuntimeRelease,
        snapshot: PublishedWorkflowSnapshot,
        pin: PublishedWorkflowSnapshotPin,
    ) -> None:
        if pin.project_id != release.project_id or pin.release_id != release.id:
            raise WorkflowConfigurationError(
                "Dify snapshot pin crossed its Workflow Release boundary",
                code="dify_snapshot_pin_scope_mismatch",
            )
        if (
            snapshot.workflow_id != pin.workflow_id
            or snapshot.workflow_hash != pin.workflow_hash
            or snapshot.snapshot_hash != pin.snapshot_hash
        ):
            raise WorkflowConfigurationError(
                "published Dify graph changed after this GEO Workflow Release was canaried; "
                "register and canary a new release before executing it",
                code="dify_published_graph_changed",
            )

    @staticmethod
    def _assert_legacy_migration_replay(
        *,
        release: WorkflowRuntimeRelease,
        replay: WorkflowExecutionResult,
        pin: PublishedWorkflowSnapshotPin,
        payload: Mapping[str, object],
    ) -> None:
        if (
            pin.pin_source != "migration_backfill"
            or replay.published_snapshot_id is None
            or replay.published_snapshot_hash is None
            or replay.published_workflow_id is None
            or replay.request_hash is None
            or replay.configured_model != release.configured_model
        ):
            raise WorkflowConfigurationError(
                "stored Dify result does not match its Workflow Release snapshot pin",
                code="dify_replay_snapshot_mismatch",
            )
        expected_request_hash = canonical_json_hash(
            {
                "runtime_release_hash": release.release_hash,
                "workflow_id": replay.published_workflow_id,
                "published_snapshot_hash": replay.published_snapshot_hash,
                "payload": payload,
            }
        )
        if replay.request_hash != expected_request_hash:
            raise WorkflowConfigurationError(
                "legacy Dify result request lineage does not match this frozen Job",
                code="dify_legacy_replay_request_mismatch",
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
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
            raise RetryableWorkflowExecutionError(
                "Dify connection was not established; retry the same GEO Job",
                code="dify_transport_unavailable",
            ) from exc
        except (
            httpx.ReadTimeout,
            httpx.ReadError,
            httpx.WriteTimeout,
            httpx.WriteError,
            httpx.TransportError,
        ) as exc:
            raise UnknownWorkflowOutcomeError(
                "Dify may have accepted this request, but GEO did not receive a definitive "
                "response. Do not retry automatically; reconcile the Dify workflow run and "
                "this GEO attempt before deciding whether to retry.",
                code="dify_unknown_outcome",
            ) from exc
        finally:
            if close:
                client.close()
        if response.status_code >= 400:
            raise http_error(response.status_code, safe_error_detail(response))
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
