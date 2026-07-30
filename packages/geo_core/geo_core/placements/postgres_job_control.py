"""Project-scoped durable job controls and immutable replay lineage."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from geo_core.placements.domain import JobReference, PlacementRuleViolation
from geo_core.placements.errors import PlacementContractMigrationRequired
from geo_core.placements.postgres_legacy_job_scope import is_exact_legacy_simulation_job
from geo_core.placements.publication_verification_reconciliation import (
    reconcile_terminal_publication_verification_in_transaction,
)


def _row(cursor: Any) -> dict[str, Any] | None:
    value = cursor.fetchone()
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return dict(zip((item.name for item in cursor.description), value, strict=True))


def _replay_result(
    db: Any, *, project_id: UUID, source_job_id: UUID, idempotency_key: str
) -> dict[str, Any] | None:
    return _row(
        db.execute(
            """SELECT j.id, j.project_id, j.campaign_id, j.kind, j.status
               FROM job_replay_requests r JOIN durable_jobs j
                 ON j.id = r.replay_job_id AND j.project_id = r.project_id
               WHERE r.project_id = %s AND r.source_job_id = %s
                 AND r.idempotency_key = %s""",
            (project_id, source_job_id, idempotency_key),
        )
    )


class PostgresJobControlMixin:
    _db: Any

    def is_legacy_project_job(self, *, project_id: UUID, job_id: UUID) -> bool:
        return is_exact_legacy_simulation_job(self._db, project_id=project_id, job_id=job_id)

    def get_job_reference(self, *, project_id: UUID, job_id: UUID) -> JobReference | None:
        job = _row(
            self._db.execute(
                """SELECT id, project_id, campaign_id, kind, status FROM durable_jobs
                   WHERE id = %s AND project_id = %s""",
                (job_id, project_id),
            )
        )
        return JobReference(**job) if job is not None else None

    def get_legacy_project_replay_result(
        self, *, project_id: UUID, source_job_id: UUID, idempotency_key: str
    ) -> JobReference | None:
        existing = _replay_result(
            self._db,
            project_id=project_id,
            source_job_id=source_job_id,
            idempotency_key=idempotency_key,
        )
        if existing is None or not is_exact_legacy_simulation_job(
            self._db, project_id=project_id, job_id=existing["id"]
        ):
            return None
        return JobReference(**existing)

    def is_legacy_project_replay_source(self, *, project_id: UUID, source_job_id: UUID) -> bool:
        if is_exact_legacy_simulation_job(self._db, project_id=project_id, job_id=source_job_id):
            return True
        project_job = self._db.execute(
            """SELECT EXISTS (
                 SELECT 1 FROM durable_jobs
                 WHERE id = %s AND project_id = %s AND campaign_id IS NULL
                   AND kind = 'knowledge.rag.extract'
               )""",
            (source_job_id, project_id),
        ).fetchone()
        if project_job and project_job[0]:
            return True
        row = self._db.execute(
            """SELECT EXISTS (
                 SELECT 1
                 FROM job_replay_requests AS replay
                 JOIN durable_jobs AS target
                   ON target.id = replay.replay_job_id
                  AND target.project_id = replay.project_id
                 WHERE replay.project_id = %s AND replay.source_job_id = %s
                   AND target.campaign_id IS NULL
                   AND CASE target.kind
                     WHEN 'prompt_simulation.generate' THEN
                       geo_is_exact_legacy_simulation_generation_job(
                         target.id, target.project_id
                       )
                     WHEN 'artifact.finalize' THEN
                       geo_is_exact_legacy_simulation_artifact_job(
                         target.id, target.project_id
                       )
                     WHEN 'knowledge.rag.extract' THEN true
                     ELSE false
                   END
               )""",
            (project_id, source_job_id),
        ).fetchone()
        return bool(row and row[0])

    def cancel_job(self, *, project_id: UUID, job_id: UUID, actor_id: UUID) -> JobReference:
        job = _row(
            self._db.execute(
                """SELECT id, project_id, campaign_id, kind, status FROM durable_jobs
                   WHERE id = %s AND project_id = %s FOR UPDATE""",
                (job_id, project_id),
            )
        )
        if job is None:
            raise PlacementRuleViolation("job does not exist")
        if job["status"] in {"succeeded", "failed", "dead_lettered", "cancelled"}:
            if job["kind"] == "publication.verify":
                reconcile_terminal_publication_verification_in_transaction(
                    self._db, job_id=job_id, project_id=project_id
                )
            return JobReference(**job)
        if job["status"] in {"queued", "retry_wait"}:
            job["status"] = "cancelled"
            self._db.execute(
                """UPDATE durable_jobs SET status = 'cancelled',
                     cancel_requested_at = clock_timestamp(), completed_at = clock_timestamp(),
                     updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s""",
                (job_id, project_id),
            )
            if job["kind"] == "publication.verify":
                reconcile_terminal_publication_verification_in_transaction(
                    self._db, job_id=job_id, project_id=project_id
                )
        elif job["status"] in {"running", "finalizing"}:
            self._db.execute(
                """UPDATE durable_jobs SET cancel_requested_at = clock_timestamp(),
                     updated_at = clock_timestamp() WHERE id = %s AND project_id = %s""",
                (job_id, project_id),
            )
        self._event(project_id, job_id, "cancel_requested", actor_id, {})
        return JobReference(**job)

    def retry_job_now(
        self,
        *,
        project_id: UUID,
        job_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> JobReference:
        previous = _row(
            self._db.execute(
                """SELECT j.id, j.project_id, j.campaign_id, j.kind, j.status
                   FROM job_retry_requests r JOIN durable_jobs j
                     ON j.id = r.job_id AND j.project_id = r.project_id
                   WHERE r.project_id = %s AND r.job_id = %s
                     AND r.idempotency_key = %s""",
                (project_id, job_id, idempotency_key),
            )
        )
        if previous:
            return JobReference(**previous)
        job = _row(
            self._db.execute(
                """UPDATE durable_jobs SET next_run_at = clock_timestamp(),
                     updated_at = clock_timestamp()
                   WHERE id = %s AND project_id = %s AND status = 'retry_wait'
                   RETURNING id, project_id, campaign_id, kind, status""",
                (job_id, project_id),
            )
        )
        if job is None:
            raise PlacementRuleViolation("only retry_wait jobs can be expedited")
        self._db.execute(
            """INSERT INTO job_retry_requests
                 (project_id, job_id, idempotency_key, requested_by)
               VALUES (%s, %s, %s, %s)""",
            (project_id, job_id, idempotency_key, actor_id),
        )
        self._db.execute(
            """INSERT INTO broker_outbox
                 (project_id, job_id, topic, payload, idempotency_key)
               VALUES (%s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (project_id, idempotency_key) DO NOTHING""",
            (
                project_id,
                job_id,
                job["kind"],
                json.dumps({"job_id": str(job_id), "project_id": str(project_id)}),
                f"retry-now:{idempotency_key}",
            ),
        )
        self._event(project_id, job_id, "retry_expedited", actor_id, {})
        return JobReference(**job)

    def replay_job(
        self,
        *,
        project_id: UUID,
        source_job_id: UUID,
        actor_id: UUID,
        idempotency_key: str,
    ) -> JobReference:
        existing = _replay_result(
            self._db,
            project_id=project_id,
            source_job_id=source_job_id,
            idempotency_key=idempotency_key,
        )
        if existing:
            return JobReference(**existing)
        source = _row(
            self._db.execute(
                """SELECT id, project_id, campaign_id, kind, status, priority, input_hash,
                          idempotency_key, max_attempts
                   FROM durable_jobs WHERE id = %s AND project_id = %s FOR UPDATE""",
                (source_job_id, project_id),
            )
        )
        existing = _replay_result(
            self._db,
            project_id=project_id,
            source_job_id=source_job_id,
            idempotency_key=idempotency_key,
        )
        if existing:
            return JobReference(**existing)
        if source is None or source["status"] not in {
            "succeeded",
            "failed",
            "dead_lettered",
            "cancelled",
        }:
            raise PlacementRuleViolation("only terminal jobs can be replayed")
        if source["kind"] not in {
            "evidence_pack.build",
            "placement.generate",
            "prompt_simulation.generate",
            "publication.verify",
            "artifact.finalize",
            "knowledge.rag.extract",
        }:
            raise PlacementRuleViolation("this job kind cannot be replayed")
        self._require_current_replay_contract(
            kind=source["kind"], project_id=project_id, source_job_id=source_job_id
        )
        replay_nonce = int(
            self._db.execute(
                """SELECT COALESCE(MAX(replay_nonce), 0) + 1 FROM durable_jobs
                   WHERE project_id = %s AND kind = %s AND idempotency_key = %s""",
                (project_id, source["kind"], source["idempotency_key"]),
            ).fetchone()[0]
        )
        replay_id = uuid5(NAMESPACE_URL, f"geo-job-replay:{source_job_id}:{idempotency_key}")
        self._db.execute(
            """INSERT INTO durable_jobs
                 (id, project_id, campaign_id, kind, priority, input_hash, idempotency_key,
                  max_attempts, parent_job_id, replay_nonce)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                replay_id,
                project_id,
                source["campaign_id"],
                source["kind"],
                source["priority"],
                source["input_hash"],
                source["idempotency_key"],
                source["max_attempts"],
                source_job_id,
                replay_nonce,
            ),
        )
        self._db.execute(
            """INSERT INTO job_replay_requests
                 (project_id, source_job_id, replay_job_id, idempotency_key, requested_by)
               VALUES (%s, %s, %s, %s, %s)""",
            (project_id, source_job_id, replay_id, idempotency_key, actor_id),
        )
        self._clone_spec(source["kind"], project_id, source_job_id, replay_id)
        broker_payload = {
            "job_id": str(replay_id),
            "project_id": str(project_id),
        }
        if source["campaign_id"] is not None:
            broker_payload["campaign_id"] = str(source["campaign_id"])
        self._db.execute(
            """INSERT INTO broker_outbox
                 (project_id, job_id, topic, payload, idempotency_key)
               VALUES (%s, %s, %s, %s::jsonb, %s)""",
            (
                project_id,
                replay_id,
                source["kind"],
                json.dumps(broker_payload),
                f"replay:{replay_id}",
            ),
        )
        self._event(
            project_id, replay_id, "job_replayed", actor_id, {"parent_job_id": str(source_job_id)}
        )
        return JobReference(replay_id, project_id, source["kind"], "queued", source["campaign_id"])

    def list_job_events(
        self, *, project_id: UUID, job_id: UUID
    ) -> tuple[Mapping[str, object], ...]:
        cursor = self._db.execute(
            """SELECT id, project_id, job_id, event_type, worker_id,
                      fencing_generation, details, created_at
               FROM durable_job_events WHERE project_id = %s AND job_id = %s
               ORDER BY created_at""",
            (project_id, job_id),
        )
        names = [item.name for item in cursor.description]
        return tuple(dict(zip(names, value, strict=True)) for value in cursor.fetchall())

    def _clone_spec(self, kind: str, project_id: UUID, source: UUID, target: UUID) -> None:
        if kind == "knowledge.rag.extract":
            changed = self._db.execute(
                """INSERT INTO knowledge_rag_job_specs
                     (job_id, project_id, pipeline_run_id, source_id, document_id,
                      configured_model, model_call_budget, adapter_release,
                      selection_manifest_hash, requested_by, replayed_from_job_id)
                   SELECT %s, project_id, pipeline_run_id, source_id, document_id,
                          configured_model, model_call_budget, adapter_release,
                          selection_manifest_hash, requested_by, %s
                   FROM knowledge_rag_job_specs
                   WHERE job_id = %s AND project_id = %s""",
                (target, source, source, project_id),
            ).rowcount
            if changed != 1:
                raise PlacementRuleViolation(
                    "Knowledge RAG replay did not clone exactly one frozen spec"
                )
            return
        contracts = {
            "evidence_pack.build": (
                "evidence_pack_job_specs",
                "campaign_id, opportunity_id, brief_version_id, evidence_pack_attempt_id",
            ),
            "placement.generate": (
                "generation_job_specs",
                "campaign_id, opportunity_id, prompt_bundle_id, configured_model, "
                "model_call_budget, requested_by",
            ),
            "prompt_simulation.generate": (
                "prompt_simulation_job_specs",
                "campaign_id, opportunity_id, simulation_id, configured_model, "
                "model_call_budget, requested_by",
            ),
            "publication.verify": (
                "verification_job_specs",
                "campaign_id, opportunity_id, submission_id",
            ),
        }
        if kind == "artifact.finalize":
            changed = self._db.execute(
                """UPDATE artifact_finalize_outbox
                   SET job_id = %s, status = 'pending', final_uri = NULL,
                       finalized_at = NULL, last_error = NULL
                   WHERE job_id = %s AND project_id = %s
                     AND status = 'failed'""",
                (target, source, project_id),
            ).rowcount
            if changed != 1:
                raise PlacementRuleViolation("artifact replay requires one failed artifact spec")
            return
        table, columns = contracts[kind]
        extra = ""
        if kind == "evidence_pack.build":
            extra = (
                " AND EXISTS (SELECT 1 FROM evidence_pack_attempts a "
                "WHERE a.id = evidence_pack_job_specs.evidence_pack_attempt_id "
                "AND a.project_id = evidence_pack_job_specs.project_id "
                "AND a.status = 'building')"
            )
        changed = self._db.execute(
            f"""INSERT INTO {table} (job_id, project_id, {columns})
                SELECT %s, project_id, {columns} FROM {table}
                WHERE job_id = %s AND project_id = %s{extra}""",  # nosec B608 - closed map.
            (target, source, project_id),
        ).rowcount
        if changed != 1:
            raise PlacementRuleViolation("job replay did not clone exactly one domain spec")

    def _require_current_replay_contract(
        self, *, kind: str, project_id: UUID, source_job_id: UUID
    ) -> None:
        if kind == "artifact.finalize":
            exact_legacy = is_exact_legacy_simulation_job(
                self._db, project_id=project_id, job_id=source_job_id
            )
            campaign = _row(
                self._db.execute(
                    """SELECT campaign_id FROM durable_jobs
                       WHERE id = %s AND project_id = %s""",
                    (source_job_id, project_id),
                )
            )
            if not exact_legacy and (campaign is None or campaign["campaign_id"] is None):
                raise PlacementContractMigrationRequired(
                    "artifact replay cannot prove current or exact legacy lineage",
                    error_code="artifact_replay_lineage_rebuild_required",
                    operator_action=(
                        "Rebuild the artifact from a current Opportunity-bound resource; "
                        "keep the unverified artifact and job history."
                    ),
                )
            return
        if kind == "prompt_simulation.generate":
            if is_exact_legacy_simulation_job(
                self._db, project_id=project_id, job_id=source_job_id
            ):
                raise PlacementContractMigrationRequired(
                    "legacy Prompt Simulation generation cannot create new replay work",
                    error_code="legacy_prompt_simulation_replay_rebuild_required",
                    operator_action=(
                        "Create a new Opportunity-bound Prompt Simulation and enqueue its "
                        "current job; keep the legacy simulation and job history."
                    ),
                )
            contract = _row(
                self._db.execute(
                    """SELECT simulation.binding_contract_version
                       FROM prompt_simulation_job_specs AS spec
                       JOIN prompt_simulations AS simulation
                         ON simulation.id = spec.simulation_id
                        AND simulation.project_id = spec.project_id
                        AND simulation.campaign_id = spec.campaign_id
                        AND simulation.opportunity_id = spec.opportunity_id
                       WHERE spec.job_id = %s AND spec.project_id = %s""",
                    (source_job_id, project_id),
                )
            )
            if contract is None or contract["binding_contract_version"] != (
                "opportunity-binding-v2"
            ):
                raise PlacementContractMigrationRequired(
                    "Prompt Simulation replay requires current Opportunity lineage",
                    error_code="legacy_prompt_simulation_replay_rebuild_required",
                    operator_action=(
                        "Create a new Opportunity-bound Prompt Simulation and enqueue its "
                        "current job; keep the unverified job lineage."
                    ),
                )
            return
        if kind == "placement.generate":
            contract = _row(
                self._db.execute(
                    """SELECT bundle.binding_contract_version
                       FROM generation_job_specs spec
                       JOIN prompt_bundles bundle
                         ON bundle.id = spec.prompt_bundle_id
                        AND bundle.project_id = spec.project_id
                        AND bundle.campaign_id = spec.campaign_id
                        AND bundle.opportunity_id = spec.opportunity_id
                       WHERE spec.job_id = %s AND spec.project_id = %s""",
                    (source_job_id, project_id),
                )
            )
            if contract is None or contract["binding_contract_version"] != (
                "opportunity-binding-v2"
            ):
                raise PlacementContractMigrationRequired(
                    "legacy generation jobs cannot create new replay work",
                    error_code="legacy_generation_replay_rebuild_required",
                    operator_action=(
                        "Create and finalize a new Opportunity-bound Prompt Bundle, then "
                        "enqueue a new placement.generate job; keep the legacy job history."
                    ),
                )
            return
        if kind != "publication.verify":
            return
        contract = _row(
            self._db.execute(
                """SELECT bundle.binding_contract_version
                   FROM verification_job_specs spec
                   JOIN publication_submissions submission
                     ON submission.id = spec.submission_id
                    AND submission.project_id = spec.project_id
                    AND submission.campaign_id = spec.campaign_id
                    AND submission.opportunity_id = spec.opportunity_id
                   JOIN publication_requests request
                     ON request.id = submission.publication_request_id
                    AND request.project_id = submission.project_id
                    AND request.campaign_id = submission.campaign_id
                    AND request.opportunity_id = submission.opportunity_id
                   JOIN placement_package_versions version
                     ON version.id = request.package_version_id
                    AND version.project_id = request.project_id
                    AND version.campaign_id = request.campaign_id
                    AND version.opportunity_id = request.opportunity_id
                   JOIN prompt_bundles bundle
                     ON bundle.id = version.prompt_bundle_id
                    AND bundle.project_id = version.project_id
                    AND bundle.campaign_id = version.campaign_id
                    AND bundle.opportunity_id = version.opportunity_id
                   WHERE spec.job_id = %s AND spec.project_id = %s""",
                (source_job_id, project_id),
            )
        )
        if contract is None or contract["binding_contract_version"] != ("opportunity-binding-v2"):
            raise PlacementContractMigrationRequired(
                "legacy publication verification jobs cannot create new replay work",
                error_code="legacy_publication_replay_rebuild_required",
                operator_action=(
                    "Rebuild and reapprove a Package Version from a current "
                    "Opportunity-bound Prompt Bundle, then submit and verify a new URL; "
                    "keep the legacy verification history."
                ),
            )

    def _event(
        self,
        project_id: UUID,
        job_id: UUID,
        event_type: str,
        actor_id: UUID,
        details: Mapping[str, object],
    ) -> None:
        self._db.execute(
            """INSERT INTO durable_job_events
                 (project_id, job_id, event_type, worker_id, details)
               VALUES (%s, %s, %s, %s, %s::jsonb)""",
            (project_id, job_id, event_type, f"api:{actor_id}", json.dumps(dict(details))),
        )
