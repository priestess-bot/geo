from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from alembic import command
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
import psycopg
from psycopg.types.json import Jsonb
import pytest

from geo_api.app_factory import create_api_app
from geo_api.placement_simulation_contracts import PromptSimulationView
from geo_core.access.models import AccessPrincipal, MembershipRecord
from geo_core.jobs.postgres import PostgresDurableJobStore
from geo_core.placements.application import PlacementApplication
from geo_core.placements.artifact_worker import PlacementArtifactRepository
from geo_core.placements.domain import canonical_hash, canonical_json_bytes
from geo_core.placements.postgres_uow import placement_uow_factory
from geo_core.placements.simulation_worker import PromptSimulationHandler
from geo_core.placements.worker_composition import (
    ArtifactFinalizeHandler,
    PlacementWorkerDispatcher,
)
from geo_core.placements.worker_repository import PlacementWorkerRepository
from tests.integration.placement_worker_support import FakeGateway, MemoryArtifactStore
from tests.integration.legacy_prompt_simulation_artifact_support import (
    seed_legacy_artifact_replay,
    seed_parentless_legacy_artifact,
)
from tests.integration.test_batch2_migrations_postgres import (
    _seed_legacy_fixture,
    _temporary_database,
)


pytestmark = pytest.mark.integration


class _AccessServices:
    def __init__(self, principal: AccessPrincipal) -> None:
        self._principal = principal

    def authenticate(self, authentication: object) -> AccessPrincipal:
        del authentication
        return self._principal


def test_legacy_prompt_simulations_remain_readable_and_inflight_jobs_resume() -> None:
    with _temporary_database() as (database_url, configuration):
        command.upgrade(configuration, "0010_campaign_destinations")
        with psycopg.connect(database_url) as connection:
            fixture = _seed_legacy_fixture(connection)
            legacy = _seed_legacy_prompt_simulations(connection, fixture)

        command.upgrade(configuration, "head")
        expected_head = ScriptDirectory.from_config(configuration).get_current_head()
        assert expected_head == "0026_legacy_simulation"
        with psycopg.connect(database_url) as connection:
            for function_name in (
                "geo_is_exact_legacy_simulation_generation_job(uuid,uuid)",
                "geo_is_exact_legacy_simulation_artifact_job(uuid,uuid)",
            ):
                assert connection.execute(
                    """SELECT has_function_privilege('geo_app', %s, 'EXECUTE'),
                              has_function_privilege('geo_worker', %s, 'EXECUTE'),
                              has_function_privilege('geo_readonly', %s, 'EXECUTE')""",
                    (function_name, function_name, function_name),
                ).fetchone() == (True, True, False)

        artifact_store = MemoryArtifactStore()
        artifact_store.fail_next = False
        artifact_store.objects[legacy["completed_storage_key"]] = legacy["completed_content"]
        application = PlacementApplication(
            placement_uow_factory(lambda: psycopg.connect(database_url)),
            artifact_reader=artifact_store,
        )
        project_id = fixture["project"]
        principal = AccessPrincipal(
            identity_id=fixture["owner"],
            actor_id=str(fixture["owner"]),
            tenant_id=fixture["tenant"],
            memberships=(MembershipRecord(project_id, fixture["tenant"], "owner"),),
            auth_method="test",
        )
        api = create_api_app(
            surface="internal",
            services=_AccessServices(principal),  # type: ignore[arg-type]
            placement_services=application,
        )

        retry_job_id = legacy["inflight_jobs"][0][1]
        cancel_job_id = legacy["cancel_job"]
        artifact_replay = legacy["artifact_replay"]
        unrelated_job_id = uuid4()
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """UPDATE durable_jobs SET status = 'retry_wait',
                          next_run_at = clock_timestamp() + interval '1 hour'
                   WHERE id = %s AND project_id = %s""",
                (retry_job_id, project_id),
            )
            connection.execute(
                """INSERT INTO durable_jobs
                     (id, project_id, kind, input_hash, idempotency_key)
                   VALUES (%s, %s, 'engineering.sync', %s, %s)""",
                (unrelated_job_id, project_id, "e" * 64, f"unrelated-{unrelated_job_id}"),
            )
            connection.commit()

        job_base = f"/v1/projects/{project_id}/geo/jobs"
        with TestClient(api) as client:
            viewed = client.get(f"{job_base}/{retry_job_id}")
            assert viewed.status_code == 200, viewed.text
            assert viewed.json()["campaign_id"] is None
            assert client.get(f"{job_base}/{unrelated_job_id}").status_code == 404
            assert client.post(f"{job_base}/{unrelated_job_id}/cancel").status_code == 404
            for readable_job_id in (
                legacy["completed_artifact_job"],
                artifact_replay["source_job_id"],
                artifact_replay["replay_job_id"],
            ):
                readable = client.get(f"{job_base}/{readable_job_id}")
                assert readable.status_code == 200, readable.text
                assert readable.json()["campaign_id"] is None
            retried = client.post(
                f"{job_base}/{retry_job_id}/retry-now",
                headers={"Idempotency-Key": "legacy-simulation-retry-now"},
            )
            assert retried.status_code == 200, retried.text
            assert retried.json()["campaign_id"] is None
            cancelled = client.post(f"{job_base}/{cancel_job_id}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "cancelled"
            events = client.get(f"{job_base}/{retry_job_id}/events")
            assert events.status_code == 200, events.text
            assert {item["event_type"] for item in events.json()} >= {"retry_expedited"}
            rejected = client.post(
                f"{job_base}/{cancel_job_id}/replays",
                headers={"Idempotency-Key": "legacy-simulation-replay-new"},
            )
            assert rejected.status_code == 422, rejected.text
            assert "legacy Prompt Simulation" in rejected.json()["detail"]
            existing_artifact_replay = client.post(
                f"{job_base}/{artifact_replay['source_job_id']}/replays",
                headers={"Idempotency-Key": artifact_replay["idempotency_key"]},
            )
            assert existing_artifact_replay.status_code == 201, existing_artifact_replay.text
            assert existing_artifact_replay.json()["id"] == str(artifact_replay["replay_job_id"])

        old_style_list = application.list_prompt_simulations(project_id=project_id)
        assert {item.id for item in old_style_list} == set(legacy["simulation_ids"])
        assert (
            application.list_prompt_simulations(
                project_id=project_id,
                campaign_id=fixture["campaign"],
            )
            == ()
        )

        completed = application.get_prompt_simulation(
            project_id=project_id,
            simulation_id=legacy["completed_simulation"],
        )
        assert completed is not None
        assert completed.campaign_id is None
        assert completed.opportunity_id is None
        assert completed.prompt_release_binding_id is None
        assert completed.prompt_release_binding_version is None
        assert completed.artifact_status == "finalized"
        PromptSimulationView.model_validate(completed)
        downloaded = application.download_prompt_simulation_artifact(
            project_id=project_id,
            simulation_id=completed.id,
        )
        assert downloaded.content == legacy["completed_content"]
        assert downloaded.content_hash == legacy["completed_manifest_hash"]

        store = PostgresDurableJobStore(lambda: psycopg.connect(database_url))
        repository = PlacementWorkerRepository(store)
        generation_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "prompt_simulation.generate": PromptSimulationHandler(
                    store=store,
                    repository=repository,
                    gateway=FakeGateway(legacy["evidence"]),
                    lease_for=timedelta(seconds=30),
                )
            },
            worker_id="legacy-simulation-upgrade",
            lease_for=timedelta(seconds=30),
        )
        artifact_dispatcher = PlacementWorkerDispatcher(
            store=store,
            handlers={
                "artifact.finalize": ArtifactFinalizeHandler(
                    store=store,
                    repository=PlacementArtifactRepository(store),
                    object_store=artifact_store,
                )
            },
            worker_id="legacy-simulation-artifact",
            lease_for=timedelta(seconds=30),
        )

        parentless_artifact_job = legacy["parentless_artifact_job"]
        assert (
            artifact_dispatcher.process(job_id=parentless_artifact_job, project_id=project_id)[
                "status"
            ]
            == "finalized"
        )
        assert (
            application.get_job_reference(
                project_id=project_id,
                campaign_id=None,
                job_id=parentless_artifact_job,
            ).campaign_id
            is None
        )

        historical_replay_id = artifact_replay["replay_job_id"]
        assert (
            artifact_dispatcher.process(job_id=historical_replay_id, project_id=project_id)[
                "status"
            ]
            == "finalized"
        )
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """UPDATE artifact_finalize_outbox
                   SET status = 'failed', final_uri = NULL, finalized_at = NULL,
                       last_error = 'post-upgrade replay fixture'
                   WHERE job_id = %s AND project_id = %s""",
                (historical_replay_id, project_id),
            )
            connection.execute(
                """UPDATE durable_jobs SET status = 'failed',
                          error_code = 'artifact_fixture_failure'
                   WHERE id = %s AND project_id = %s""",
                (historical_replay_id, project_id),
            )
            connection.commit()
        replay_url = f"{job_base}/{historical_replay_id}/replays"
        replay_headers = {"Idempotency-Key": "legacy-artifact-post-upgrade-replay"}
        with TestClient(api) as client:
            created_replay = client.post(replay_url, headers=replay_headers)
            repeated_replay = client.post(replay_url, headers=replay_headers)
        assert created_replay.status_code == 201, created_replay.text
        assert repeated_replay.status_code == 201, repeated_replay.text
        assert created_replay.json()["id"] == repeated_replay.json()["id"]
        assert created_replay.json()["campaign_id"] is None
        post_upgrade_replay_id = UUID(created_replay.json()["id"])
        with psycopg.connect(database_url) as connection:
            payload = connection.execute(
                "SELECT payload FROM broker_outbox WHERE job_id = %s AND project_id = %s",
                (post_upgrade_replay_id, project_id),
            ).fetchone()[0]
        assert "campaign_id" not in payload
        assert (
            artifact_dispatcher.process(job_id=post_upgrade_replay_id, project_id=project_id)[
                "status"
            ]
            == "finalized"
        )
        with TestClient(api) as client:
            for readable_job_id in (
                artifact_replay["source_job_id"],
                historical_replay_id,
                post_upgrade_replay_id,
            ):
                assert client.get(f"{job_base}/{readable_job_id}").status_code == 200
                assert client.get(f"{job_base}/{readable_job_id}/events").status_code == 200
        bare_replay_id = uuid4()
        with pytest.raises(psycopg.errors.CheckViolation):
            with psycopg.connect(database_url) as connection:
                with connection.transaction():
                    connection.execute(
                        """INSERT INTO durable_jobs
                             (id, project_id, kind, input_hash, idempotency_key,
                              parent_job_id)
                           VALUES (%s, %s, 'artifact.finalize', %s, %s, %s)""",
                        (
                            bare_replay_id,
                            project_id,
                            "f" * 64,
                            f"bare-legacy-artifact-{bare_replay_id}",
                            post_upgrade_replay_id,
                        ),
                    )

        for simulation_id, job_id in legacy["inflight_jobs"]:
            generated = generation_dispatcher.process(
                job_id=job_id,
                project_id=project_id,
            )
            assert generated["status"] == "succeeded", _job_error(database_url, job_id)
            artifact_job_id = UUID(str(generated["artifact_job_id"]))
            finalized = artifact_dispatcher.process(
                job_id=artifact_job_id,
                project_id=project_id,
            )
            assert finalized["status"] == "finalized"
            assert (
                application.get_job_reference(
                    project_id=project_id,
                    campaign_id=None,
                    job_id=artifact_job_id,
                ).campaign_id
                is None
            )
            detail = application.get_prompt_simulation(
                project_id=project_id,
                simulation_id=simulation_id,
            )
            assert detail is not None
            assert detail.generation_status == "succeeded"
            assert detail.artifact_status == "finalized"
            assert detail.artifact_manifest is not None
            assert detail.artifact_manifest["schema"] == ("geo-prompt-simulation-result-v2")
            assert "campaign_id" not in detail.artifact_manifest
            application.download_prompt_simulation_artifact(
                project_id=project_id,
                simulation_id=simulation_id,
            )

        with psycopg.connect(database_url) as connection:
            resumed = connection.execute(
                """SELECT result.simulation_id, result.lineage_contract_version,
                          result.campaign_id, result.opportunity_id,
                          artifact.campaign_id, artifact.opportunity_id,
                          artifact.destination_id, job.parent_job_id
                   FROM prompt_simulation_results AS result
                   JOIN artifact_finalize_outbox AS artifact
                     ON artifact.project_id = result.project_id
                    AND artifact.resource_kind = 'prompt_simulation'
                    AND artifact.resource_id = result.simulation_id
                   JOIN durable_jobs AS job
                     ON job.id = artifact.job_id AND job.project_id = artifact.project_id
                   WHERE result.simulation_id = ANY(%s)
                   ORDER BY result.simulation_id""",
                ([simulation_id for simulation_id, _ in legacy["inflight_jobs"]],),
            ).fetchall()
            assert len(resumed) == 2
            parent_jobs = {job_id for _, job_id in legacy["inflight_jobs"]}
            assert all(
                row[1:7] == ("legacy-v1", None, None, None, None, None) and row[7] in parent_jobs
                for row in resumed
            )
            _assert_new_legacy_simulation_is_rejected(connection, fixture, legacy)

        command.downgrade(configuration, "0025_monitoring_source_guard")
        with psycopg.connect(database_url) as connection:
            assert connection.execute(
                """SELECT to_regprocedure(
                         'geo_is_exact_legacy_simulation_generation_job(uuid,uuid)'
                       ) IS NOT NULL,
                       to_regprocedure(
                         'geo_is_exact_legacy_simulation_artifact_job(uuid,uuid)'
                       ) IS NOT NULL"""
            ).fetchone() == (True, True)
        command.upgrade(configuration, "head")


def _seed_legacy_prompt_simulations(
    connection: psycopg.Connection[Any], fixture: dict[str, Any]
) -> dict[str, Any]:
    brand_id = uuid4()
    evidence_id = uuid4()
    source_id = uuid4()
    skill_id, skill_version_id, release_id = uuid4(), uuid4(), uuid4()
    release_hash = canonical_hash("legacy-simulation-release")
    connection.execute(
        """INSERT INTO product_entities
             (id, project_id, entity_type, canonical_name)
           VALUES (%s, %s, 'brand', 'Legacy simulation brand')""",
        (brand_id, fixture["project"]),
    )
    connection.execute(
        """INSERT INTO prompt_skills(id, project_id, skill_key)
           VALUES (%s, %s, 'legacy-simulation')""",
        (skill_id, fixture["project"]),
    )
    connection.execute(
        """INSERT INTO prompt_skill_versions
             (id, project_id, skill_id, version_number, source_text,
              source_hash, created_by)
           VALUES (%s, %s, %s, 1, 'Legacy simulation prompt', %s, %s)""",
        (
            skill_version_id,
            fixture["project"],
            skill_id,
            canonical_hash("Legacy simulation prompt"),
            fixture["owner"],
        ),
    )
    connection.execute(
        """INSERT INTO generation_template_releases
             (id, project_id, skill_version_id, release_number, system_template,
              user_template, variable_schema, output_schema, compiler_version,
              release_hash)
           VALUES (%s, %s, %s, 1, 'System', 'User', '{}'::jsonb, %s,
                   'legacy-simulation-compiler', %s)""",
        (
            release_id,
            fixture["project"],
            skill_version_id,
            Jsonb(
                {
                    "type": "object",
                    "required": [
                        "content_json",
                        "rendered_text",
                        "claims",
                        "internal_evidence_refs",
                        "public_citation_refs",
                    ],
                }
            ),
            release_hash,
        ),
    )
    fixture["skill_version"] = skill_version_id
    fixture["release"] = release_id
    fixture["release_hash"] = release_hash
    connection.execute(
        """INSERT INTO content_task_prompt_releases
             (project_id, task_key, template_release_id, selected_by)
           VALUES (%s, 'owned_site', %s, %s)""",
        (fixture["project"], fixture["release"], fixture["owner"]),
    )
    evidence_text = "A documented legacy product experience remains available."
    connection.execute(
        """INSERT INTO evidence_items
             (id, project_id, item_type, source_id, subject_entity_id, subject_role,
              snapshot_text, snapshot_hash, source_revision_kind,
              source_revision_value, usage_rights, confidentiality,
              public_disclosure_allowed, public_source_url, public_source_title)
           VALUES (%s, %s, 'citation', %s, %s, 'product', %s, %s,
                   'content_hash', 'legacy-simulation-v1', 'owned', 'public', true,
                   'https://public.example/legacy-simulation', 'Legacy source')""",
        (
            evidence_id,
            fixture["project"],
            source_id,
            fixture["product"],
            evidence_text,
            canonical_hash(evidence_text),
        ),
    )

    simulation_ids = [uuid4() for _ in range(6)]
    generation_job_ids = [uuid4() for _ in range(6)]
    snapshots: dict[UUID, dict[str, object]] = {}
    for simulation_id in simulation_ids:
        snapshot = _legacy_input_snapshot(
            simulation_id=simulation_id,
            fixture=fixture,
            evidence_id=evidence_id,
        )
        snapshots[simulation_id] = snapshot
        connection.execute(
            """INSERT INTO prompt_simulations
                 (id, project_id, destination_id, template_release_id,
                  primary_brand_entity_id, product_entity_id, requested_by,
                  input_snapshot, input_hash)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                simulation_id,
                fixture["project"],
                fixture["destination"],
                fixture["release"],
                brand_id,
                fixture["product"],
                fixture["owner"],
                Jsonb(snapshot),
                canonical_hash(snapshot),
            ),
        )
        connection.execute(
            """INSERT INTO prompt_simulation_evidence
                 (simulation_id, project_id, evidence_item_id, ordinal)
               VALUES (%s, %s, %s, 0)""",
            (simulation_id, fixture["project"], evidence_id),
        )

    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key,
              completed_at)
           VALUES (%s, %s, 'prompt_simulation.generate', 'succeeded', %s,
                   'legacy-simulation-completed', clock_timestamp())""",
        (
            generation_job_ids[0],
            fixture["project"],
            canonical_hash(snapshots[simulation_ids[0]]),
        ),
    )
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key, completed_at)
           VALUES (%s, %s, 'prompt_simulation.generate', 'succeeded', %s,
                   'legacy-simulation-parentless-artifact-root', clock_timestamp())""",
        (
            generation_job_ids[5],
            fixture["project"],
            canonical_hash(snapshots[simulation_ids[5]]),
        ),
    )
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key, completed_at)
           VALUES (%s, %s, 'prompt_simulation.generate', 'succeeded', %s,
                   'legacy-simulation-artifact-root', clock_timestamp())""",
        (
            generation_job_ids[4],
            fixture["project"],
            canonical_hash(snapshots[simulation_ids[4]]),
        ),
    )
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, input_hash, idempotency_key)
           VALUES (%s, %s, 'prompt_simulation.generate', %s,
                   'legacy-simulation-cancel')""",
        (
            generation_job_ids[3],
            fixture["project"],
            canonical_hash(snapshots[simulation_ids[3]]),
        ),
    )
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, input_hash, idempotency_key)
           VALUES (%s, %s, 'prompt_simulation.generate', %s,
                   'legacy-simulation-queued')""",
        (
            generation_job_ids[1],
            fixture["project"],
            canonical_hash(snapshots[simulation_ids[1]]),
        ),
    )
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key,
              attempt_count, lease_owner, lease_token, lease_expires_at,
              fencing_generation)
           VALUES (%s, %s, 'prompt_simulation.generate', 'running', %s,
                   'legacy-simulation-running', 1, 'retired-worker', %s,
                   clock_timestamp() - interval '1 hour', 1)""",
        (
            generation_job_ids[2],
            fixture["project"],
            canonical_hash(snapshots[simulation_ids[2]]),
            uuid4(),
        ),
    )
    for simulation_id, job_id in zip(simulation_ids, generation_job_ids, strict=True):
        connection.execute(
            """INSERT INTO prompt_simulation_job_specs
                 (job_id, project_id, simulation_id, configured_model,
                  model_call_budget, requested_by)
               VALUES (%s, %s, %s, 'deepseek-v4-flash', 1, %s)""",
            (job_id, fixture["project"], simulation_id, fixture["owner"]),
        )

    completed_manifest: dict[str, object] = {
        "schema": "geo-prompt-simulation-result-v2",
        "simulation_id": str(simulation_ids[0]),
        "project_id": str(fixture["project"]),
        "test_only": True,
        "publication_eligible": False,
        "authenticity_mode": "brand_authored",
        "input_hash": canonical_hash(snapshots[simulation_ids[0]]),
        "output_hash": "a" * 64,
        "model_call": {"provider_request_id": "legacy-completed"},
        "output": {"rendered_text": "Legacy completed preview"},
    }
    completed_manifest_hash = canonical_hash(completed_manifest)
    completed_storage_key = (
        f"content-simulations/{fixture['project']}/{simulation_ids[0]}/"
        f"simulation-{completed_manifest_hash}.json"
    )
    connection.execute(
        """INSERT INTO prompt_simulation_results
             (simulation_id, project_id, generated_by_job_id, artifact_manifest,
              output_hash, manifest_hash, model_response_hash, storage_key)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            simulation_ids[0],
            fixture["project"],
            generation_job_ids[0],
            Jsonb(completed_manifest),
            "a" * 64,
            completed_manifest_hash,
            "b" * 64,
            completed_storage_key,
        ),
    )
    artifact_job_id = uuid4()
    connection.execute(
        """INSERT INTO durable_jobs
             (id, project_id, kind, status, input_hash, idempotency_key, completed_at)
           VALUES (%s, %s, 'artifact.finalize', 'succeeded', %s,
                   'legacy-simulation-artifact', clock_timestamp())""",
        (
            artifact_job_id,
            fixture["project"],
            canonical_hash(
                {
                    "resource_kind": "prompt_simulation",
                    "resource_id": str(simulation_ids[0]),
                    "manifest_hash": completed_manifest_hash,
                }
            ),
        ),
    )
    connection.execute(
        """INSERT INTO artifact_finalize_outbox
             (project_id, job_id, resource_kind, resource_id, pending_uri,
              storage_key, final_uri, content_hash, status, finalized_at)
           VALUES (%s, %s, 'prompt_simulation', %s, %s, %s, %s, %s,
                   'finalized', clock_timestamp())""",
        (
            fixture["project"],
            artifact_job_id,
            simulation_ids[0],
            ("postgres://prompt_simulation_results/" f"{simulation_ids[0]}/artifact_manifest"),
            completed_storage_key,
            f"s3://geo-artifacts/{completed_storage_key}",
            completed_manifest_hash,
        ),
    )
    artifact_replay = seed_legacy_artifact_replay(
        connection,
        fixture=fixture,
        simulation_id=simulation_ids[4],
        generation_job_id=generation_job_ids[4],
        snapshot=snapshots[simulation_ids[4]],
    )
    parentless_artifact_job = seed_parentless_legacy_artifact(
        connection,
        fixture=fixture,
        simulation_id=simulation_ids[5],
        generation_job_id=generation_job_ids[5],
        snapshot=snapshots[simulation_ids[5]],
    )
    connection.commit()
    return {
        "evidence": evidence_id,
        "brand": brand_id,
        "simulation_ids": tuple(simulation_ids),
        "completed_simulation": simulation_ids[0],
        "completed_storage_key": completed_storage_key,
        "completed_manifest_hash": completed_manifest_hash,
        "completed_content": canonical_json_bytes(completed_manifest),
        "completed_artifact_job": artifact_job_id,
        "inflight_jobs": (
            (simulation_ids[1], generation_job_ids[1]),
            (simulation_ids[2], generation_job_ids[2]),
        ),
        "cancel_job": generation_job_ids[3],
        "artifact_replay": artifact_replay,
        "parentless_artifact_job": parentless_artifact_job,
    }


def _legacy_input_snapshot(
    *, simulation_id: UUID, fixture: dict[str, Any], evidence_id: UUID
) -> dict[str, object]:
    return {
        "schema": "geo-prompt-simulation-input-v2",
        "simulation_id": str(simulation_id),
        "project_id": str(fixture["project"]),
        "test_only": True,
        "publication_eligible": False,
        "authenticity_mode": "brand_authored",
        "template_release": {
            "id": str(fixture["release"]),
            "release_hash": fixture["release_hash"],
            "compiler_version": "legacy-simulation-compiler",
        },
        "destination": {"publication_channel": "owned_site"},
        "brief": {"goals": {"deliverable": "legacy preview"}},
        "evidence_items": [{"id": str(evidence_id)}],
        "client_variables": {},
        "system_prompt": "Use the frozen legacy prompt.",
        "rendered_prompt": "Generate the legacy internal preview.",
        "model_policy_hash": "c" * 64,
        "configured_model": "deepseek-v4-flash",
        "model_call_budget": 1,
    }


def _assert_new_legacy_simulation_is_rejected(
    connection: psycopg.Connection[Any],
    fixture: dict[str, Any],
    legacy: dict[str, Any],
) -> None:
    simulation_id = uuid4()
    snapshot = _legacy_input_snapshot(
        simulation_id=simulation_id,
        fixture=fixture,
        evidence_id=legacy["evidence"],
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        with connection.transaction():
            connection.execute(
                """INSERT INTO prompt_simulations
                     (id, project_id, destination_id, template_release_id,
                      template_skill_version_id, template_release_number,
                      template_release_hash, primary_brand_entity_id,
                      product_entity_id, requested_by, input_snapshot, input_hash,
                      binding_contract_version)
                   VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, %s, %s, %s,
                           'legacy-v1')""",
                (
                    simulation_id,
                    fixture["project"],
                    fixture["destination"],
                    fixture["release"],
                    fixture["skill_version"],
                    fixture["release_hash"],
                    legacy["brand"],
                    fixture["product"],
                    fixture["owner"],
                    Jsonb(snapshot),
                    canonical_hash(snapshot),
                ),
            )


def _job_error(database_url: str, job_id: UUID) -> tuple[object, ...] | None:
    with psycopg.connect(database_url) as connection:
        return connection.execute(
            """SELECT status, error_code, error_detail
               FROM durable_jobs WHERE id = %s""",
            (job_id,),
        ).fetchone()
