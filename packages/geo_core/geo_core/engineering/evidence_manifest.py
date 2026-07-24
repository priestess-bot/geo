"""Fail-closed evidence contracts for roadmap work-package acceptance."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CLAUSE_IDS = tuple(f"DOR-{index:02d}" for index in range(1, 7)) + tuple(
    f"DOD-{index:02d}" for index in range(1, 8)
)


class EvidenceManifestError(ValueError):
    """Raised when roadmap evidence cannot support the claimed state."""


class WorkPackageType(StrEnum):
    GOVERNANCE_CONTROL = "governance_control"
    CONTRACT_MIGRATION = "contract_migration"
    RUNTIME_FEATURE = "runtime_feature"
    EXTERNAL_INTEGRATION = "external_integration"
    VERIFICATION_RELEASE = "verification_release"


class CheckStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class Applicability(StrEnum):
    REQUIRED = "required"
    NOT_APPLICABLE = "not_applicable"


class ClauseOutcome(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class CapabilityFlags:
    changes_database: bool = False
    changes_api: bool = False
    has_customer_surface: bool = False
    handles_sensitive_data: bool = False
    has_runtime_operation: bool = False
    calls_external_service: bool = False
    requires_live_evidence: bool = False


@dataclass(frozen=True)
class EvidenceReference:
    uri: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.uri.strip():
            raise EvidenceManifestError("evidence URI must not be empty")
        if not _SHA256.fullmatch(self.sha256):
            raise EvidenceManifestError("evidence sha256 must be 64 lowercase hex characters")


@dataclass(frozen=True)
class NotApplicableDecision:
    reason: str
    type_or_flag_basis: str
    decided_by: str
    independent_verifier: str
    decided_at: datetime
    evidence: EvidenceReference

    def __post_init__(self) -> None:
        required = (
            self.reason,
            self.type_or_flag_basis,
            self.decided_by,
            self.independent_verifier,
        )
        if any(not value.strip() for value in required):
            raise EvidenceManifestError("not-applicable decisions require a reason and actors")
        if self.reason.strip().lower() in {"n/a", "na", "not applicable", "not_applicable"}:
            raise EvidenceManifestError("not-applicable reason must be specific")
        _require_aware(self.decided_at, "N/A decision time")


@dataclass(frozen=True)
class ClauseAssessment:
    clause_id: str
    applicability: Applicability
    outcome: ClauseOutcome
    evidence: tuple[EvidenceReference, ...] = ()
    not_applicable: NotApplicableDecision | None = None

    def __post_init__(self) -> None:
        if self.clause_id not in _CLAUSE_IDS:
            raise EvidenceManifestError(f"unknown DoR/DoD clause: {self.clause_id}")
        if self.applicability == Applicability.REQUIRED:
            if self.not_applicable is not None:
                raise EvidenceManifestError("required clauses cannot have an N/A decision")
            if self.outcome == ClauseOutcome.PASSED and not self.evidence:
                raise EvidenceManifestError("passed required clauses need readable evidence")
        else:
            if self.outcome != ClauseOutcome.PASSED:
                raise EvidenceManifestError("an approved N/A decision has a passed outcome")
            if self.evidence or self.not_applicable is None:
                raise EvidenceManifestError("N/A clauses require exactly the decision evidence")


@dataclass(frozen=True)
class EvidenceScope:
    environment: str
    project_id: str | None = None
    campaign_id: str | None = None
    account_reference: str | None = None
    connection_scope: str | None = None

    def __post_init__(self) -> None:
        if not self.environment.strip():
            raise EvidenceManifestError("evidence environment fingerprint is required")


@dataclass(frozen=True)
class WorkPackageEvidence:
    check_id: str
    work_package_type: WorkPackageType
    capabilities: CapabilityFlags
    status: CheckStatus
    owner: str
    verifier: str
    started_at: datetime
    ended_at: datetime | None
    scope: EvidenceScope
    clauses: tuple[ClauseAssessment, ...]
    git_commits: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]
    migration_revisions: tuple[str, ...] = ()
    openapi_contracts: tuple[str, ...] = ()
    adapter_releases: tuple[str, ...] = ()
    test_run_ids: tuple[str, ...] = ()
    live_run_ids: tuple[str, ...] = ()
    result: str | None = None
    deviation: str | None = None

    def __post_init__(self) -> None:
        if not self.check_id.strip() or not self.owner.strip() or not self.verifier.strip():
            raise EvidenceManifestError("check identity, owner, and verifier are required")
        if self.owner == self.verifier:
            raise EvidenceManifestError("work-package owner cannot verify their own evidence")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise EvidenceManifestError("work-package end time cannot precede its start time")
        _require_aware(self.started_at, "work-package start time")
        if self.ended_at is not None:
            _require_aware(self.ended_at, "work-package end time")
        clause_ids = tuple(item.clause_id for item in self.clauses)
        if len(clause_ids) != len(set(clause_ids)):
            raise EvidenceManifestError("DoR/DoD clauses must not be duplicated")
        if set(clause_ids) != set(_CLAUSE_IDS):
            missing = sorted(set(_CLAUSE_IDS).difference(clause_ids))
            extra = sorted(set(clause_ids).difference(_CLAUSE_IDS))
            raise EvidenceManifestError(f"clause applicability is incomplete: missing={missing}, extra={extra}")
        for clause in self.clauses:
            decision = clause.not_applicable
            if decision is None:
                continue
            if self.owner in {decision.decided_by, decision.independent_verifier}:
                raise EvidenceManifestError("work-package owner cannot approve an N/A decision")
            if decision.decided_by == decision.independent_verifier:
                raise EvidenceManifestError("N/A decision and independent verification must be separate")
        _validate_capability_minimums(self)
        if self.status == CheckStatus.ACCEPTED:
            self._validate_accepted()

    def _validate_accepted(self) -> None:
        if self.ended_at is None or not self.result or not self.git_commits or not self.evidence:
            raise EvidenceManifestError(
                "accepted work packages require an end time, result, commit, and evidence"
            )
        pending = [
            item.clause_id
            for item in self.clauses
            if item.applicability == Applicability.REQUIRED
            and item.outcome != ClauseOutcome.PASSED
        ]
        if pending:
            raise EvidenceManifestError(f"accepted work package has unpassed clauses: {pending}")
        if self.capabilities.changes_database and not self.migration_revisions:
            raise EvidenceManifestError("database changes require migration revision evidence")
        if self.capabilities.changes_api and not self.openapi_contracts:
            raise EvidenceManifestError("API changes require OpenAPI contract evidence")
        if self.capabilities.requires_live_evidence and not self.live_run_ids:
            raise EvidenceManifestError("live-evidence work packages require live run IDs")


@dataclass(frozen=True)
class RoadmapEvidenceManifest:
    schema_version: str
    roadmap_id: str
    stage: str
    environment_fingerprint: str
    generated_at: datetime
    git_commit: str
    included_workstreams: tuple[str, ...]
    excluded_workstreams: tuple[str, ...]
    checks: tuple[WorkPackageEvidence, ...]
    manifest_hash: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.schema_version,
            self.roadmap_id,
            self.stage,
            self.environment_fingerprint,
            self.git_commit,
        )
        if any(not value.strip() for value in required):
            raise EvidenceManifestError("manifest identity and environment fields are required")
        _require_aware(self.generated_at, "manifest generation time")
        if not self.included_workstreams or set(self.included_workstreams) & set(
            self.excluded_workstreams
        ):
            raise EvidenceManifestError("workstream scope must be explicit and disjoint")
        check_ids = tuple(item.check_id for item in self.checks)
        if len(check_ids) != len(set(check_ids)):
            raise EvidenceManifestError("manifest check IDs must be unique")
        if self.manifest_hash is not None and self.manifest_hash != self.calculate_hash():
            raise EvidenceManifestError("manifest hash does not match canonical content")

    def calculate_hash(self) -> str:
        payload = asdict(self)
        payload.pop("manifest_hash", None)
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def with_hash(self) -> "RoadmapEvidenceManifest":
        return replace(self, manifest_hash=self.calculate_hash())


_DEFAULT_REQUIRED: Mapping[WorkPackageType, frozenset[str]] = {
    WorkPackageType.GOVERNANCE_CONTROL: frozenset({"DOR-01", "DOR-05", "DOD-07"}),
    WorkPackageType.CONTRACT_MIGRATION: frozenset(
        {"DOR-01", "DOR-02", "DOR-05", "DOD-01", "DOD-02", "DOD-07"}
    ),
    WorkPackageType.RUNTIME_FEATURE: frozenset(
        {
            "DOR-01",
            "DOR-02",
            "DOR-03",
            "DOR-05",
            "DOD-01",
            "DOD-02",
            "DOD-05",
            "DOD-07",
        }
    ),
    WorkPackageType.EXTERNAL_INTEGRATION: frozenset(
        {
            "DOR-01",
            "DOR-02",
            "DOR-03",
            "DOR-05",
            "DOR-06",
            "DOD-01",
            "DOD-02",
            "DOD-05",
            "DOD-07",
        }
    ),
    WorkPackageType.VERIFICATION_RELEASE: frozenset(
        {"DOR-01", "DOR-03", "DOR-05", "DOD-02", "DOD-07"}
    ),
}


def minimum_required_clauses(
    work_package_type: WorkPackageType, capabilities: CapabilityFlags
) -> frozenset[str]:
    """Resolve matrix requirements that cannot be waived by an N/A decision."""

    required = set(_DEFAULT_REQUIRED[work_package_type])
    if capabilities.changes_database or capabilities.changes_api:
        required.add("DOR-04")
    if capabilities.handles_sensitive_data:
        required.add("DOR-06")
    if capabilities.changes_database:
        required.add("DOD-03")
    if capabilities.changes_api or capabilities.has_customer_surface:
        required.add("DOD-04")
    if capabilities.has_runtime_operation:
        required.add("DOD-05")
    if capabilities.requires_live_evidence:
        required.add("DOD-06")
    return frozenset(required)


def _validate_capability_minimums(item: WorkPackageEvidence) -> None:
    assessments = {assessment.clause_id: assessment for assessment in item.clauses}
    waived = sorted(
        clause_id
        for clause_id in minimum_required_clauses(item.work_package_type, item.capabilities)
        if assessments[clause_id].applicability != Applicability.REQUIRED
    )
    if waived:
        raise EvidenceManifestError(
            f"type/capability-required clauses cannot be marked N/A: {waived}"
        )


def _canonical_json(value: object) -> str:
    return json.dumps(value, default=_json_default, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"cannot encode evidence value: {type(value).__name__}")


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EvidenceManifestError(f"{label} must include a timezone")


CLAUSE_IDS = _CLAUSE_IDS
