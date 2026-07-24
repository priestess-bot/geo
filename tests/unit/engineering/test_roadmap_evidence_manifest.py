from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from geo_core.engineering.evidence_manifest import (
    CLAUSE_IDS,
    Applicability,
    CapabilityFlags,
    CheckStatus,
    ClauseAssessment,
    ClauseOutcome,
    EvidenceManifestError,
    EvidenceReference,
    EvidenceScope,
    NotApplicableDecision,
    RoadmapEvidenceManifest,
    WorkPackageEvidence,
    WorkPackageType,
    minimum_required_clauses,
)


NOW = datetime(2026, 7, 23, tzinfo=UTC)
EVIDENCE = EvidenceReference("minio://roadmap-evidence/check.json", "a" * 64)


def _decision(clause_id: str) -> NotApplicableDecision:
    return NotApplicableDecision(
        reason=f"{clause_id} does not apply because this pure domain package changes no runtime surface",
        type_or_flag_basis="runtime_feature with all conditional capability flags false",
        decided_by="architecture-owner",
        independent_verifier="independent-verifier",
        decided_at=NOW,
        evidence=EVIDENCE,
    )


def _clauses(
    work_package_type: WorkPackageType,
    capabilities: CapabilityFlags,
) -> tuple[ClauseAssessment, ...]:
    required = minimum_required_clauses(work_package_type, capabilities)
    return tuple(
        ClauseAssessment(
            clause_id=clause_id,
            applicability=(
                Applicability.REQUIRED
                if clause_id in required
                else Applicability.NOT_APPLICABLE
            ),
            outcome=ClauseOutcome.PASSED,
            evidence=(EVIDENCE,) if clause_id in required else (),
            not_applicable=None if clause_id in required else _decision(clause_id),
        )
        for clause_id in CLAUSE_IDS
    )


def _work_package(
    *,
    status: CheckStatus = CheckStatus.ACCEPTED,
    capabilities: CapabilityFlags = CapabilityFlags(),
) -> WorkPackageEvidence:
    package_type = WorkPackageType.RUNTIME_FEATURE
    return WorkPackageEvidence(
        check_id="M1-PROMPT-01",
        work_package_type=package_type,
        capabilities=capabilities,
        status=status,
        owner="prompt-owner",
        verifier="release-verifier",
        started_at=NOW,
        ended_at=NOW if status == CheckStatus.ACCEPTED else None,
        scope=EvidenceScope(environment="unit-test", project_id="project-fixture"),
        clauses=_clauses(package_type, capabilities),
        git_commits=("1" * 40,),
        test_run_ids=("pytest-prompt-program",),
        evidence=(EVIDENCE,),
        result="accepted" if status == CheckStatus.ACCEPTED else None,
    )


def test_manifest_hash_is_deterministic_and_covers_explicit_non_b_scope() -> None:
    manifest = RoadmapEvidenceManifest(
        schema_version="roadmap-evidence-v1",
        roadmap_id="GEO-next-phase-six-month-roadmap-2026-07-21",
        stage="M1",
        environment_fingerprint="unit-test:python-3.12",
        generated_at=NOW,
        git_commit="1" * 40,
        included_workstreams=("A", "C", "D"),
        excluded_workstreams=("B",),
        checks=(_work_package(),),
    )

    frozen = manifest.with_hash()

    assert frozen.manifest_hash == manifest.calculate_hash()
    assert frozen.calculate_hash() == manifest.calculate_hash()


def test_capability_required_clause_cannot_be_waived() -> None:
    capabilities = CapabilityFlags(changes_database=True)
    clauses = list(_clauses(WorkPackageType.RUNTIME_FEATURE, capabilities))
    index = next(i for i, clause in enumerate(clauses) if clause.clause_id == "DOD-03")
    clauses[index] = ClauseAssessment(
        clause_id="DOD-03",
        applicability=Applicability.NOT_APPLICABLE,
        outcome=ClauseOutcome.PASSED,
        not_applicable=_decision("DOD-03"),
    )

    with pytest.raises(EvidenceManifestError, match="cannot be marked N/A"):
        replace(
            _work_package(status=CheckStatus.IN_PROGRESS, capabilities=capabilities),
            clauses=tuple(clauses),
        )


def test_accepted_package_requires_all_required_clauses_to_pass() -> None:
    package = _work_package(status=CheckStatus.IN_PROGRESS)
    clauses = list(package.clauses)
    index = next(i for i, clause in enumerate(clauses) if clause.clause_id == "DOR-01")
    clauses[index] = replace(clauses[index], outcome=ClauseOutcome.PENDING, evidence=())

    with pytest.raises(EvidenceManifestError, match="unpassed clauses"):
        replace(
            package,
            status=CheckStatus.ACCEPTED,
            ended_at=NOW,
            result="accepted",
            clauses=tuple(clauses),
        )


def test_owner_cannot_approve_not_applicable_decision() -> None:
    package = _work_package(status=CheckStatus.IN_PROGRESS)
    clauses = list(package.clauses)
    index = next(
        i
        for i, clause in enumerate(clauses)
        if clause.applicability == Applicability.NOT_APPLICABLE
    )
    decision = replace(clauses[index].not_applicable, decided_by=package.owner)
    clauses[index] = replace(clauses[index], not_applicable=decision)

    with pytest.raises(EvidenceManifestError, match="owner cannot approve"):
        replace(package, clauses=tuple(clauses))


def test_database_and_api_acceptance_require_versioned_mappings() -> None:
    capabilities = CapabilityFlags(changes_database=True, changes_api=True)

    with pytest.raises(EvidenceManifestError, match="migration revision"):
        _work_package(capabilities=capabilities)

    package = replace(
        _work_package(status=CheckStatus.IN_PROGRESS, capabilities=capabilities),
        status=CheckStatus.ACCEPTED,
        ended_at=NOW,
        result="accepted",
        migration_revisions=("0027_prompt_program",),
        openapi_contracts=("internal.openapi.json#/prompt-programs",),
    )
    assert package.status == CheckStatus.ACCEPTED
