"""Exact Style Profile build result selected for downstream review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from geo_core.synthetic_lab.domain import (
    SyntheticLabContractError,
    _require_hash,
    _require_uuid,
)
from geo_core.synthetic_lab.execution_contracts import StyleProfileBuildOutput


@dataclass(frozen=True, kw_only=True)
class StyleProfileBuildBinding:
    project_id: UUID
    profile_version_id: UUID
    profile_hash: str
    execution_job_id: UUID
    execution_result_id: UUID
    result_hash: str
    result_payload_hash: str
    artifact_hash: str
    bound_by: UUID

    def __post_init__(self) -> None:
        for uuid_value, label in (
            (self.project_id, "Profile build binding Project"),
            (self.profile_version_id, "Profile build binding Profile version"),
            (self.execution_job_id, "Profile build binding Job"),
            (self.execution_result_id, "Profile build binding result"),
            (self.bound_by, "Profile build binding actor"),
        ):
            _require_uuid(uuid_value, label)
        for hash_value, label in (
            (self.profile_hash, "Profile build binding Profile"),
            (self.result_hash, "Profile build binding result"),
            (self.result_payload_hash, "Profile build binding payload"),
            (self.artifact_hash, "Profile build binding artifact"),
        ):
            _require_hash(hash_value, label)


@dataclass(frozen=True, kw_only=True)
class StyleProfileBuildCandidate:
    binding: StyleProfileBuildBinding
    output: StyleProfileBuildOutput

    def __post_init__(self) -> None:
        selected = self.binding
        output = self.output
        if (
            output.project_id != selected.project_id
            or output.profile_version_id != selected.profile_version_id
            or output.profile_hash != selected.profile_hash
            or output.result_hash != selected.result_hash
            or output.artifact_hash != selected.artifact_hash
        ):
            raise SyntheticLabContractError(
                "Style Profile build candidate does not match its exact result binding"
            )


class StyleProfileBuildBindingRepository(Protocol):
    def get(
        self, *, project_id: UUID, profile_version_id: UUID
    ) -> StyleProfileBuildBinding | None: ...

    def stage(self, binding: StyleProfileBuildBinding) -> None: ...


__all__ = [
    "StyleProfileBuildBinding",
    "StyleProfileBuildBindingRepository",
    "StyleProfileBuildCandidate",
]
