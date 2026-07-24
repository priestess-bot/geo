"""Authoritative Suite input catalog used by the Workflow C memory adapter."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from uuid import UUID

from geo_api.workflow_c_sampling_contracts import CreateSamplingSuiteRequest
from geo_core.sampling import (
    CaptureMethod,
    LocationControl,
    ProviderSamplingExecutionInput,
    SamplingConflict,
    SamplingNotFound,
    SamplingQuestion,
    SamplingSourceStratum,
)


@dataclass(frozen=True)
class ResolvedSamplingSuiteInputs:
    option_key: str
    display_name: str
    question_set_id: UUID
    question_set_version: str
    question_set_hash: str
    questions: tuple[SamplingQuestion, ...]
    adapter_release_id: UUID
    adapter_release_hash: str
    model_release_id: UUID
    model_release_hash: str
    route_policy_id: UUID
    route_policy_hash: str
    runtime_manifest_id: UUID
    runtime_manifest_hash: str
    runtime_option_id: UUID
    runtime_option_hash: str
    admission_policy_id: UUID
    admission_policy_hash: str
    source_stratum: SamplingSourceStratum
    provider_execution_input: ProviderSamplingExecutionInput | None = None


class WorkflowCSamplingInputCatalog:
    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[tuple[object, ...], ResolvedSamplingSuiteInputs] = {}

    def install(
        self,
        *,
        project_id: UUID,
        admission_policy_id: UUID,
        admission_policy_hash: str,
        resolved: ResolvedSamplingSuiteInputs,
    ) -> None:
        if (
            resolved.source_stratum.capture_method is CaptureMethod.MANUAL_UI
            and resolved.source_stratum.location_control is not LocationControl.NOT_CONTROLLED
        ):
            raise SamplingConflict(
                "manual_ui Suite inputs cannot claim controlled geography"
            )
        if (
            resolved.admission_policy_id != admission_policy_id
            or resolved.admission_policy_hash != admission_policy_hash
        ):
            raise SamplingConflict("Suite catalog admission selector is inconsistent")
        key = _key_from_values(
            project_id=project_id,
            resolved=resolved,
        )
        with self._lock:
            existing = self._items.get(key)
            if existing is not None and existing != resolved:
                raise SamplingConflict("Suite selector catalog entry changed in place")
            self._items[key] = resolved

    def resolve(
        self,
        *,
        project_id: UUID,
        selector: CreateSamplingSuiteRequest,
    ) -> ResolvedSamplingSuiteInputs:
        key = (project_id, selector.suite_input_option_key)
        with self._lock:
            resolved = self._items.get(key)
        if resolved is None:
            raise SamplingNotFound("approved Sampling Suite selector combination does not exist")
        return resolved

    def list(self, *, project_id: UUID) -> tuple[ResolvedSamplingSuiteInputs, ...]:
        with self._lock:
            values = tuple(
                item for key, item in self._items.items() if key[0] == project_id
            )
        return tuple(sorted(values, key=lambda item: (item.display_name, item.option_key)))


def _key_from_values(
    *,
    project_id: UUID,
    resolved: ResolvedSamplingSuiteInputs,
) -> tuple[object, ...]:
    return (project_id, resolved.option_key)
