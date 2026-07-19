CREATE OR REPLACE FUNCTION geo_is_exact_legacy_simulation_generation_job(
    candidate_job_id uuid, scope_project_id uuid
) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1
        FROM durable_jobs AS job
        JOIN prompt_simulation_job_specs AS spec
          ON spec.job_id = job.id AND spec.project_id = job.project_id
         AND spec.campaign_id IS NOT DISTINCT FROM job.campaign_id
        JOIN prompt_simulations AS simulation
          ON simulation.id = spec.simulation_id
         AND simulation.project_id = spec.project_id
         AND simulation.campaign_id IS NOT DISTINCT FROM spec.campaign_id
         AND simulation.opportunity_id IS NOT DISTINCT FROM spec.opportunity_id
        WHERE job.id = candidate_job_id AND job.project_id = scope_project_id
          AND job.kind = 'prompt_simulation.generate' AND job.campaign_id IS NULL
          AND job.input_hash = simulation.input_hash
          AND spec.campaign_id IS NULL AND spec.opportunity_id IS NULL
          AND simulation.binding_contract_version = 'legacy-v1'
          AND simulation.campaign_id IS NULL
          AND simulation.opportunity_id IS NULL
          AND simulation.binding_id IS NULL
          AND simulation.binding_version IS NULL
    )
$$;

CREATE OR REPLACE FUNCTION geo_is_exact_legacy_simulation_artifact_job(
    candidate_job_id uuid, scope_project_id uuid
) RETURNS boolean
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE related AS (
        SELECT job.id, ARRAY[job.id] AS path, 0 AS depth
        FROM durable_jobs AS job
        WHERE job.id = candidate_job_id AND job.project_id = scope_project_id
          AND job.kind = 'artifact.finalize' AND job.campaign_id IS NULL
          AND (
              job.parent_job_id IS NULL
              OR geo_is_exact_legacy_simulation_generation_job(
                  job.parent_job_id, job.project_id
              )
              OR EXISTS (
                  SELECT 1 FROM job_replay_requests AS own_replay
                  WHERE own_replay.project_id = job.project_id
                    AND own_replay.source_job_id = job.parent_job_id
                    AND own_replay.replay_job_id = job.id
              )
          )
        UNION ALL
        SELECT peer.id, current.path || peer.id, current.depth + 1
        FROM related AS current
        JOIN job_replay_requests AS replay
          ON replay.project_id = scope_project_id
         AND (replay.source_job_id = current.id OR replay.replay_job_id = current.id)
        JOIN durable_jobs AS replay_job
          ON replay_job.id = replay.replay_job_id
         AND replay_job.project_id = replay.project_id
         AND replay_job.parent_job_id = replay.source_job_id
         AND replay_job.kind = 'artifact.finalize'
         AND replay_job.campaign_id IS NULL
        JOIN durable_jobs AS peer
          ON peer.id = CASE
               WHEN replay.source_job_id = current.id THEN replay.replay_job_id
               ELSE replay.source_job_id
             END
         AND peer.project_id = replay.project_id
         AND peer.kind = 'artifact.finalize'
         AND peer.campaign_id IS NULL
        WHERE current.depth < 64 AND NOT peer.id = ANY(current.path)
    )
    SELECT EXISTS (
        SELECT 1
        FROM durable_jobs AS job
        JOIN related AS owner ON true
        JOIN artifact_finalize_outbox AS artifact
          ON artifact.job_id = owner.id AND artifact.project_id = job.project_id
        JOIN prompt_simulation_results AS result
          ON result.simulation_id = artifact.resource_id
         AND result.project_id = artifact.project_id
        WHERE job.id = candidate_job_id AND job.project_id = scope_project_id
          AND job.kind = 'artifact.finalize' AND job.campaign_id IS NULL
          AND artifact.resource_kind = 'prompt_simulation'
          AND artifact.campaign_id IS NULL
          AND artifact.opportunity_id IS NULL
          AND artifact.destination_id IS NULL
          AND artifact.content_hash = result.manifest_hash
          AND artifact.storage_key = result.storage_key
          AND result.lineage_contract_version = 'legacy-v1'
          AND result.campaign_id IS NULL AND result.opportunity_id IS NULL
          AND geo_is_exact_legacy_simulation_generation_job(
              result.generated_by_job_id, result.project_id
          )
    )
$$;

CREATE OR REPLACE FUNCTION geo_assert_new_durable_job_campaign() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_campaign_id uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        NEW.id, NEW.project_id, NEW.kind, NEW.campaign_id, NEW.parent_job_id
    ) IS DISTINCT FROM (
        OLD.id, OLD.project_id, OLD.kind, OLD.campaign_id, OLD.parent_job_id
    ) THEN
        RAISE EXCEPTION 'durable job identity and Campaign ancestry are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.kind IN (
        'evidence_pack.build', 'placement.generate', 'publication.verify',
        'placement.measure', 'prompt_simulation.generate', 'artifact.finalize'
    ) AND NEW.campaign_id IS NULL AND NOT (
        NEW.kind = 'artifact.finalize'
        AND (
            (TG_OP = 'UPDATE' AND geo_is_exact_legacy_simulation_artifact_job(
                NEW.id, NEW.project_id
            ))
            OR (TG_OP = 'INSERT' AND NEW.parent_job_id IS NOT NULL AND (
                geo_is_exact_legacy_simulation_generation_job(
                    NEW.parent_job_id, NEW.project_id
                )
                OR geo_is_exact_legacy_simulation_artifact_job(
                    NEW.parent_job_id, NEW.project_id
                )
            ))
        )
    ) THEN
        RAISE EXCEPTION 'Placement jobs require an explicit Campaign context'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.parent_job_id IS NOT NULL THEN
        SELECT campaign_id INTO parent_campaign_id FROM durable_jobs
        WHERE id = NEW.parent_job_id AND project_id = NEW.project_id;
        IF parent_campaign_id IS DISTINCT FROM NEW.campaign_id THEN
            RAISE EXCEPTION 'replayed jobs must preserve source Campaign context'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_require_durable_job_campaign_spec() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    valid_context boolean := false;
BEGIN
    IF NEW.kind = 'evidence_pack.build' THEN
        SELECT EXISTS(SELECT 1 FROM evidence_pack_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'placement.generate' THEN
        SELECT EXISTS(SELECT 1 FROM generation_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'publication.verify' THEN
        SELECT EXISTS(SELECT 1 FROM verification_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'placement.measure' THEN
        SELECT EXISTS(SELECT 1 FROM measurement_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'prompt_simulation.generate' THEN
        SELECT EXISTS(
            SELECT 1
            FROM prompt_simulation_job_specs AS spec
            JOIN prompt_simulations AS simulation
              ON simulation.id = spec.simulation_id
             AND simulation.project_id = spec.project_id
             AND simulation.campaign_id IS NOT DISTINCT FROM spec.campaign_id
             AND simulation.opportunity_id IS NOT DISTINCT FROM spec.opportunity_id
            WHERE spec.job_id = NEW.id
              AND spec.project_id = NEW.project_id
              AND spec.campaign_id IS NOT DISTINCT FROM NEW.campaign_id
              AND (
                  (NEW.campaign_id IS NULL
                      AND spec.opportunity_id IS NULL
                      AND simulation.binding_contract_version = 'legacy-v1'
                      AND simulation.campaign_id IS NULL
                      AND simulation.opportunity_id IS NULL
                      AND simulation.binding_id IS NULL
                      AND simulation.binding_version IS NULL)
                  OR (NEW.campaign_id IS NOT NULL
                      AND spec.opportunity_id IS NOT NULL
                      AND simulation.binding_contract_version = 'opportunity-binding-v2'
                      AND simulation.campaign_id IS NOT NULL
                      AND simulation.opportunity_id IS NOT NULL
                      AND simulation.binding_id IS NOT NULL
                      AND simulation.binding_version IS NOT NULL)
              )
        ) INTO valid_context;
    ELSIF NEW.kind = 'artifact.finalize' THEN
        IF NEW.campaign_id IS NOT NULL THEN
            SELECT EXISTS(
                SELECT 1 FROM artifact_finalize_outbox AS artifact
                WHERE artifact.job_id = NEW.id
                  AND artifact.project_id = NEW.project_id
                  AND artifact.campaign_id IS NOT DISTINCT FROM NEW.campaign_id
            ) INTO valid_context;
        ELSE
            SELECT geo_is_exact_legacy_simulation_artifact_job(
                NEW.id, NEW.project_id
            ) INTO valid_context;
        END IF;
    ELSE
        RETURN NULL;
    END IF;
    IF NOT valid_context THEN
        RAISE EXCEPTION 'Placement job is missing its exact Campaign-scoped specification'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_artifact_campaign_context() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.campaign_id IS NULL
       AND NEW.opportunity_id IS NULL
       AND NEW.destination_id IS NULL THEN
        IF NEW.resource_kind <> 'prompt_simulation' OR NOT EXISTS (
            SELECT 1
            FROM durable_jobs AS artifact_job
            JOIN prompt_simulation_results AS result
              ON result.simulation_id = NEW.resource_id
             AND result.project_id = artifact_job.project_id
            WHERE artifact_job.id = NEW.job_id
              AND artifact_job.project_id = NEW.project_id
              AND artifact_job.kind = 'artifact.finalize'
              AND artifact_job.campaign_id IS NULL
              AND NEW.content_hash = result.manifest_hash
              AND NEW.storage_key = result.storage_key
              AND result.lineage_contract_version = 'legacy-v1'
              AND result.campaign_id IS NULL
              AND result.opportunity_id IS NULL
              AND (
                  geo_is_exact_legacy_simulation_artifact_job(
                      artifact_job.id, artifact_job.project_id
                  )
                  OR (
                      artifact_job.parent_job_id = result.generated_by_job_id
                      AND geo_is_exact_legacy_simulation_generation_job(
                          result.generated_by_job_id, result.project_id
                      )
                  )
              )
        ) THEN
            RAISE EXCEPTION 'legacy Prompt Simulation artifact ancestry is not exact'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.campaign_id IS NULL OR NEW.opportunity_id IS NULL OR NEW.destination_id IS NULL THEN
        RAISE EXCEPTION 'new placement artifacts require exact Campaign ancestry'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.resource_kind = 'prompt_bundle' AND NOT EXISTS (
        SELECT 1 FROM prompt_bundles WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'Prompt Bundle artifact context mismatch' USING ERRCODE = '23514';
    ELSIF NEW.resource_kind = 'package_export' AND NOT EXISTS (
        SELECT 1 FROM placement_export_receipts WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'Package export artifact context mismatch' USING ERRCODE = '23514';
    ELSIF NEW.resource_kind = 'prompt_simulation' AND NOT EXISTS (
        SELECT 1 FROM prompt_simulations WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
          AND binding_contract_version = 'opportunity-binding-v2'
    ) THEN
        RAISE EXCEPTION 'Prompt simulation artifact context mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
