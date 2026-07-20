from __future__ import annotations

import hashlib
from typing import Any, Mapping
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from geo_core.model_gateway import (
    ModelCallBudget,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelPolicy,
)
from geo_core.placements.url_verifier import PublicUrlVerifier, UrlVerificationResult
from tests.integration.placement_worker_support import FakeVerifier


class UnexpectedGateway:
    provider = "unexpected"

    def generate(
        self,
        request: ModelGatewayRequest,
        *,
        policy: ModelPolicy,
        budget: ModelCallBudget,
    ) -> ModelGatewayResult:
        del request, policy, budget
        raise AssertionError("legacy Prompt Bundle must be rejected before provider I/O")


class CountingVerifier(PublicUrlVerifier):
    def __init__(self) -> None:
        self.calls = 0
        self._delegate = FakeVerifier()

    def verify(self, url: str, **expected: object) -> UrlVerificationResult:
        self.calls += 1
        return self._delegate.verify(url, **expected)


def insert_approved_legacy_version(
    connection: psycopg.Connection[Any],
    *,
    fixture: Mapping[str, Any],
    reviewer_id: UUID,
    package_id: UUID,
    bundle_id: UUID,
    version_id: UUID,
    version_number: int,
    base_version_id: UUID | None,
    content: Mapping[str, object],
) -> None:
    submission_id = uuid4()
    connection.execute(
        """INSERT INTO placement_package_versions
             (id, project_id, package_id, prompt_bundle_id, version_number,
              base_version_id, content_json, rendered_text, content_hash,
              edited_by, edit_reason)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   'legacy approved immutable content')""",
        (
            version_id,
            fixture["project"],
            package_id,
            bundle_id,
            version_number,
            base_version_id,
            Jsonb(dict(content)),
            "A documented product review published for verification.",
            hashlib.sha256(repr(sorted(content.items())).encode()).hexdigest(),
            fixture["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO placement_claims
             (project_id, package_version_id, claim_text, claim_kind, support_status)
           VALUES (%s, %s, %s, 'non_factual', 'not_required')""",
        (fixture["project"], version_id, f"Legacy editorial copy {version_number}"),
    )
    connection.execute(
        """INSERT INTO placement_review_submissions
             (id, project_id, package_version_id, submitted_by)
           VALUES (%s, %s, %s, %s)""",
        (submission_id, fixture["project"], version_id, fixture["owner"]),
    )
    connection.execute(
        """INSERT INTO placement_reviews
             (project_id, package_version_id, submitted_for_review_by, reviewer_id,
              decision, claim_inventory_complete, extracted_claim_support_confirmed,
              score, notes)
           VALUES (%s, %s, %s, %s, 'approved', true, true, 100,
                   'legacy approval retained for upgrade testing')""",
        (fixture["project"], version_id, fixture["owner"], reviewer_id),
    )
    connection.execute(
        """UPDATE placement_package_versions SET workflow_status = 'approved'
           WHERE id = %s AND project_id = %s""",
        (version_id, fixture["project"]),
    )


def seed_legacy_generation_jobs(
    connection: psycopg.Connection[Any],
    fixture: Mapping[str, Any],
    bundle: Mapping[str, UUID],
) -> dict[str, UUID]:
    jobs = {"queued": uuid4(), "expired_running": uuid4()}
    for label, job_id in jobs.items():
        insert_legacy_job(
            connection,
            job_id=job_id,
            project_id=fixture["project"],
            kind="placement.generate",
            label=f"legacy-generation-{label}",
            running=label == "expired_running",
        )
        connection.execute(
            """INSERT INTO generation_job_specs
                 (job_id, project_id, prompt_bundle_id, configured_model,
                  model_call_budget, requested_by)
               VALUES (%s, %s, %s, 'deepseek-v4-flash', 1, %s)""",
            (job_id, fixture["project"], bundle["bundle_id"], fixture["owner"]),
        )
        if label == "expired_running":
            connection.execute(
                """INSERT INTO model_call_logs
                     (project_id, job_id, call_number, status, request_hash,
                      prompt_bundle_hash, provider, configured_model)
                   VALUES (%s, %s, 1, 'reserved', %s, %s,
                           'retired-provider', 'retired-model')""",
                (fixture["project"], job_id, "9" * 64, "8" * 64),
            )
    connection.commit()
    return jobs


def insert_legacy_job(
    connection: psycopg.Connection[Any],
    *,
    job_id: UUID,
    project_id: UUID,
    kind: str,
    label: str,
    running: bool,
) -> None:
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key,
              attempt_count, lease_owner, lease_token, lease_expires_at,
              heartbeat_at, fencing_generation, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                   CASE WHEN %s THEN clock_timestamp() - interval '10 minutes' END,
                   CASE WHEN %s THEN clock_timestamp() - interval '12 minutes' END,
                   %s, clock_timestamp() - interval '15 minutes')""",
        (
            job_id,
            project_id,
            kind,
            "running" if running else "queued",
            hashlib.sha256(label.encode()).hexdigest(),
            label,
            1 if running else 0,
            "retired-worker" if running else None,
            uuid4() if running else None,
            running,
            running,
            1 if running else 0,
        ),
    )


def seed_existing_replay_result(
    database_url: str,
    *,
    project_id: UUID,
    source_job_id: UUID,
    actor_id: UUID,
    idempotency_key: str,
) -> UUID:
    replay_job_id = uuid4()
    with psycopg.connect(database_url) as connection:
        source = connection.execute(
            """SELECT campaign_id, kind, priority, input_hash, idempotency_key,
                      max_attempts, replay_nonce
               FROM durable_jobs WHERE id = %s AND project_id = %s""",
            (source_job_id, project_id),
        ).fetchone()
        assert source is not None
        campaign_id, kind, priority, input_hash, source_key, max_attempts, replay_nonce = source
        connection.execute(
            """INSERT INTO durable_jobs
                 (id, project_id, campaign_id, kind, priority, input_hash,
                  idempotency_key, max_attempts, parent_job_id, replay_nonce)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                replay_job_id,
                project_id,
                campaign_id,
                kind,
                priority,
                input_hash,
                source_key,
                max_attempts,
                source_job_id,
                replay_nonce + 1,
            ),
        )
        if kind == "placement.generate":
            connection.execute(
                """INSERT INTO generation_job_specs
                     (job_id, project_id, campaign_id, opportunity_id, prompt_bundle_id,
                      configured_model, model_call_budget, requested_by)
                   SELECT %s, project_id, campaign_id, opportunity_id, prompt_bundle_id,
                          configured_model, model_call_budget, requested_by
                   FROM generation_job_specs WHERE job_id = %s AND project_id = %s""",
                (replay_job_id, source_job_id, project_id),
            )
        else:
            assert kind == "publication.verify"
            connection.execute(
                """INSERT INTO verification_job_specs
                     (job_id, project_id, campaign_id, opportunity_id, submission_id)
                   SELECT %s, project_id, campaign_id, opportunity_id, submission_id
                   FROM verification_job_specs WHERE job_id = %s AND project_id = %s""",
                (replay_job_id, source_job_id, project_id),
            )
        connection.execute(
            """INSERT INTO job_replay_requests
                 (project_id, source_job_id, replay_job_id, idempotency_key, requested_by)
               VALUES (%s, %s, %s, %s, %s)""",
            (project_id, source_job_id, replay_job_id, idempotency_key, actor_id),
        )
        connection.commit()
    return replay_job_id


def set_publication_request_status(database_url: str, request_id: UUID, status: str) -> None:
    with psycopg.connect(database_url) as connection:
        connection.execute(
            "UPDATE publication_requests SET status = %s WHERE id = %s",
            (status, request_id),
        )
        connection.commit()


def bundle_snapshot(connection: psycopg.Connection[Any], bundle_id: UUID) -> tuple[Any, ...]:
    row = connection.execute(
        "SELECT input_snapshot, bundle_hash FROM prompt_bundles WHERE id = %s",
        (bundle_id,),
    ).fetchone()
    assert row is not None
    return row


def package_snapshot(connection: psycopg.Connection[Any], version_id: UUID) -> tuple[Any, ...]:
    row = connection.execute(
        """SELECT content_json, rendered_text, content_hash, workflow_status,
                  prompt_bundle_id
           FROM placement_package_versions WHERE id = %s""",
        (version_id,),
    ).fetchone()
    assert row is not None
    return row
