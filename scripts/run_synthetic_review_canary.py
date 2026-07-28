#!/usr/bin/env python3
"""Enqueue one isolated Synthetic Review staging canary through the Durable Job path."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import os
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from geo_core.model_gateway.postgres_runtime_catalog import PostgresRuntimeCatalog
from geo_core.prompts.bootstrap_templates import bootstrap_template
from geo_core.prompts.program_contracts import ProgramKind
from geo_core.project_scope import set_project_scope
from geo_core.synthetic_lab.domain import StyleProfileStatus, StyleProfileVersion
from geo_core.synthetic_lab.execution_admission_support import _frozen_prompt
from geo_core.synthetic_lab.execution_application import SyntheticExecutionApplication
from geo_core.synthetic_lab.execution_contracts import (
    FrozenEvidence,
    ReviewCaseRunTask,
)
from geo_core.synthetic_lab.execution_gateway import PromptProgramExecutionResolver
from geo_core.synthetic_lab.ports import (
    LabPrincipal,
    LabRole,
    RuntimeInputSnapshot,
    VersionedAggregate,
)
from geo_core.synthetic_lab.postgres_execution_runtime import (
    PostgresRuntimePromptApplication,
    PostgresSyntheticRuntimeInputPort,
)
from geo_core.synthetic_lab.postgres_uow import PostgresSyntheticLabUnitOfWorkFactory
from geo_core.synthetic_lab.review_cases import (
    ReviewCase,
    ScenarioMode,
    review_case_content_hash,
)


REVIEW_KINDS = (
    ProgramKind.GENERATION,
    ProgramKind.CLAIM_EXTRACTION,
    ProgramKind.CONFLICT_CHECK,
    ProgramKind.REVISION,
    ProgramKind.STYLE_JUDGE,
    ProgramKind.ARBITER,
)
CANARY_RELEASE = "synthetic-review-dify-canary-v10-negative-path"


def main() -> int:
    args = _arguments()
    project_id = UUID(args.project_id)
    actor_id = UUID(args.actor_id)
    runtime_selection_id = UUID(args.runtime_selection_id)
    fact_snapshot_id = UUID(args.fact_snapshot_id)
    database_url = _required(os.getenv(args.database_url_env), args.database_url_env)

    def connect():
        return psycopg.connect(database_url, row_factory=dict_row)

    fact_hash = _fact_hash(connect, project_id, fact_snapshot_id)
    profile_version_id = _id(project_id, "profile-version")
    profile_hash = _hash(f"{CANARY_RELEASE}:profile")
    profile = StyleProfileVersion(
        id=profile_version_id,
        project_id=project_id,
        profile_id=_id(project_id, "profile"),
        version_number=1,
        channel="reddit",
        locale="en-AU",
        corpus_hash=_hash(f"{CANARY_RELEASE}:corpus"),
        profile_hash=profile_hash,
        prompt_release_id=_id(project_id, "profile-prompt"),
        prompt_release_hash=_hash(f"{CANARY_RELEASE}:profile-prompt"),
        approved_sample_count=200,
        status=StyleProfileStatus.FROZEN,
        reviewed_by=actor_id,
        reviewed_at=datetime(2026, 7, 27, tzinfo=UTC),
    )
    uow_factory = PostgresSyntheticLabUnitOfWorkFactory(connect)
    with uow_factory(project_id=project_id) as uow:
        existing = uow.aggregates.get(
            project_id=project_id,
            kind="style_profile",
            resource_id=profile.id,
        )
        if existing is None:
            uow.aggregates.stage(
                VersionedAggregate(
                    project_id=project_id,
                    kind="style_profile",
                    resource_id=profile.id,
                    version=1,
                    submitted_by=actor_id,
                    payload=profile,
                ),
                expected_version=0,
            )
            uow.commit()
        elif existing.payload != profile:
            raise SystemExit("staging canary Profile identity has different content")

    prompt_application = PostgresRuntimePromptApplication(connect)
    prompt_resolver = PromptProgramExecutionResolver(prompt_application)
    catalog = PostgresRuntimeCatalog(database_url)
    prompts = {}
    for kind in REVIEW_KINDS:
        purpose = bootstrap_template(kind).purpose
        runtime = prompt_application.resolve_runtime_binding(
            project_id=project_id,
            purpose=purpose,
        )
        selection = catalog.resolve_approved_runtime(
            project_id=project_id,
            runtime_selection_id=runtime_selection_id,
            required_purpose=purpose,
            search_mode=None,
        )
        prompts[kind] = _frozen_prompt(runtime, selection)

    case_values = {
        "case_key": "staging-dify-revision-canary-v1",
        "ordinal": 1,
        "mode": ScenarioMode.GUIDED,
        "channel": "reddit",
        "persona": "Australian small-business marketing manager",
        "use_case": "assess Advinsys GEO analytics and support availability",
        "subject": "Advinsys",
        "question_set_version_id": _id(project_id, "question-set"),
        "question_set_hash": _hash(f"{CANARY_RELEASE}:question-set"),
        "fact_snapshot_id": fact_snapshot_id,
        "fact_snapshot_hash": fact_hash,
        "profile_version_id": profile.id,
        "profile_hash": profile.profile_hash,
        "competitor_scenario": False,
        "expected_risks": ("explicit_conflict",),
        "creative_reference": (
            "Creative reference only: explore a claim of 24/7 support. "
            "The frozen evidence remains authoritative."
        ),
    }
    case = ReviewCase(
        id=_id(project_id, "case"),
        project_id=project_id,
        review_suite_version_id=_id(project_id, "suite-version"),
        review_suite_version_number=1,
        content_hash=review_case_content_hash(**case_values),
        **case_values,
    )
    generation = prompts[ProgramKind.GENERATION]
    runtime_inputs = RuntimeInputSnapshot(
        project_id=project_id,
        fact_snapshot_id=fact_snapshot_id,
        fact_snapshot_hash=fact_hash,
        profile_version_id=profile.id,
        profile_hash=profile.profile_hash,
        prompt_release_id=generation.release_id,
        prompt_release_hash=generation.release_hash,
        facts_current_approved=True,
        profile_frozen=True,
        prompt_frozen=True,
    )
    task = ReviewCaseRunTask(
        project_id=project_id,
        job_id=_id(project_id, "job"),
        model_job_version=1,
        requested_by=actor_id,
        review_run_id=_id(project_id, "review-run"),
        review_suite_hash=_hash(f"{CANARY_RELEASE}:suite"),
        case=case,
        subject_id=_id(project_id, "subject"),
        evidence=(
            FrozenEvidence(
                ref="canary-fact:support-hours",
                subject_id=str(_id(project_id, "subject")),
                summary=(
                    "Advinsys support is available on Australian business days from "
                    "09:00 to 17:00 AEST and is not available 24/7."
                ),
                fact_id=_id(project_id, "fact"),
                fact_hash=_hash("advinsys-support-business-hours-only-v1"),
            ),
        ),
        # This isolated negative-path profile is intentionally impossible so a
        # real Review Case must exercise revision and regeneration instead of
        # completing on the first valid candidate.
        style_profile_summary=(
            "Canary-only fault contract: the review text must contain exactly 40 words "
            "and exactly 41 words at the same time."
        ),
        style_pass_threshold=5.0,
        runtime_inputs=runtime_inputs,
        prompts=prompts,
    )
    receipt = SyntheticExecutionApplication(uow_factory).enqueue(
        principal=LabPrincipal(
            project_id=project_id,
            actor_id=actor_id,
            roles=frozenset({LabRole.OPERATOR}),
        ),
        task=task,
        outbox_id=_id(project_id, "outbox"),
        runtime_inputs=PostgresSyntheticRuntimeInputPort(connect),
        prompts=prompt_resolver,
        idempotency_key=CANARY_RELEASE,
    )
    print(f"job_id={receipt.result.id} replayed={str(receipt.replayed).lower()}")
    return 0


def _fact_hash(connect, project_id: UUID, fact_snapshot_id: UUID) -> str:
    with connect() as connection:
        set_project_scope(connection, project_id)
        row = connection.execute(
            """SELECT pack_hash FROM evidence_pack_attempts
               WHERE project_id = %s AND id = %s AND status = 'ready'""",
            (project_id, fact_snapshot_id),
        ).fetchone()
    if row is None or not row["pack_hash"]:
        raise SystemExit("--fact-snapshot-id must identify a ready evidence pack")
    return str(row["pack_hash"])


def _id(project_id: UUID, label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"geo:{project_id}:{CANARY_RELEASE}:{label}")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _required(value: str | None, name: str) -> str:
    normalized = (value or "").strip()
    if not normalized:
        raise SystemExit(f"{name} is required")
    return normalized


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--runtime-selection-id", required=True)
    parser.add_argument("--fact-snapshot-id", required=True)
    parser.add_argument("--database-url-env", default="GEO_DATABASE_URL")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
