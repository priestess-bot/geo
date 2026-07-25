-- Recommendation evidence must resolve to the producer-owned immutable
-- lineage that actually fed Workflow C.  The prior resolver used vocabulary
-- that the Python domain rejected and trusted a result payload field that no
-- comparison producer writes.

ALTER FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    RENAME TO geo_resolve_recommendation_evidence_pre_0082;
REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence_pre_0082(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;

CREATE FUNCTION geo_resolve_recommendation_evidence(
    p_project_id uuid,
    p_kind text,
    p_resource_id text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE resolved jsonb;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RETURN NULL;
    END IF;

    IF p_kind = 'observation' THEN
        SELECT jsonb_build_object(
            'kind', 'observation',
            'project_id', observation.project_id::text,
            'resource_id', observation.id::text,
            'version', observation.observation_hash,
            'sha256', observation.observation_hash,
            'locator', jsonb_build_object(
                'sampling_observation_id', observation.id::text,
                'sampling_task_id', task.id::text,
                'sampling_run_id', observation.run_id::text
            ),
            'valid', observation.status = 'complete',
            'capture_method', task.capture_method,
            'evidence_class', 'real_observation',
            'question_resource_id', task.question_id,
            'surface_resource_id', task.source_stratum_hash,
            'eligible', observation.status = 'complete',
            'summary', NULL
        ) INTO resolved
        FROM workflow_c_sampling_observations AS observation
        JOIN workflow_c_sampling_tasks AS task
          ON task.project_id = observation.project_id
         AND task.id = observation.task_id
         AND task.run_id = observation.run_id
         AND task.source_stratum_hash = observation.source_stratum_hash
        WHERE observation.project_id = p_project_id
          AND observation.id::text = p_resource_id;
        RETURN resolved;
    END IF;

    IF p_kind = 'metric_comparison' THEN
        WITH comparison_lineage AS (
            SELECT family.project_id,
                   family.family_hash,
                   family.status AS family_status,
                   family.bootstrap_method,
                   family.protocol_hash,
                   result.comparison_id,
                   result.conclusion,
                   comparison_spec.spec_payload,
                   comparison_input.value->'protocol'->'stratum'->>'question_cluster'
                       AS question_cluster,
                   comparison_spec.spec_payload->'admission'->>'source_snapshot_hash'
                       AS source_snapshot_hash,
                   comparison_spec.spec_payload->'admission'->>'target_snapshot_hash'
                       AS target_snapshot_hash
              FROM workflow_c_comparison_results AS result
              JOIN workflow_c_comparison_families AS family
                ON family.project_id = result.project_id
               AND family.family_hash = result.family_hash
              JOIN LATERAL (
                    SELECT spec.spec_payload
                      FROM durable_jobs AS job
                      JOIN workflow_c_job_specs AS spec
                        ON spec.project_id = job.project_id
                       AND spec.job_id = job.id
                       AND spec.kind = job.kind
                       AND spec.spec_hash = job.input_hash
                     WHERE job.project_id = family.project_id
                       AND job.kind = 'workflow_c.analysis.comparison'
                       AND job.status = 'succeeded'
                       AND job.result_ref =
                           'workflow-c-comparison:' || family.family_hash
                       AND jsonb_typeof(spec.spec_payload->'admission') = 'object'
                       AND jsonb_typeof(
                           spec.spec_payload->'comparison'->'inputs'
                       ) = 'array'
                     ORDER BY job.updated_at DESC, job.id DESC
                     LIMIT 1
              ) AS comparison_spec ON true
              JOIN LATERAL jsonb_array_elements(
                    comparison_spec.spec_payload->'comparison'->'inputs'
              ) AS comparison_input(value)
                ON comparison_input.value->'protocol'->>'comparison_id'
                   = result.comparison_id
             WHERE family.project_id = p_project_id
               AND family.family_hash || ':' || result.comparison_id = p_resource_id
        ), observation_membership AS (
            SELECT lineage.project_id,
                   lineage.family_hash,
                   lineage.comparison_id,
                   jsonb_agg(
                       DISTINCT manifest_item.observation_id::text
                       ORDER BY manifest_item.observation_id::text
                   ) AS observation_resource_ids
              FROM comparison_lineage AS lineage
              CROSS JOIN LATERAL unnest(ARRAY[
                    lineage.source_snapshot_hash,
                    lineage.target_snapshot_hash
              ]) AS selected_snapshot(snapshot_hash)
              JOIN workflow_c_semantic_metric_snapshots AS snapshot
                ON snapshot.project_id = lineage.project_id
               AND snapshot.snapshot_hash = selected_snapshot.snapshot_hash
              JOIN durable_jobs AS semantic_job
                ON semantic_job.project_id = snapshot.project_id
               AND semantic_job.kind = 'workflow_c.analysis.semantic_metrics'
               AND semantic_job.status = 'succeeded'
               AND semantic_job.result_ref =
                   'workflow-c-semantic-metrics:' || snapshot.snapshot_hash
              JOIN workflow_c_job_specs AS semantic_spec
                ON semantic_spec.project_id = semantic_job.project_id
               AND semantic_spec.job_id = semantic_job.id
               AND semantic_spec.kind = semantic_job.kind
               AND semantic_spec.spec_hash = semantic_job.input_hash
               AND semantic_spec.spec_payload->'schema_version' = '2'::jsonb
               AND jsonb_typeof(semantic_spec.spec_payload->'semantic_metrics') = 'object'
              JOIN workflow_c_analysis_input_manifests AS manifest
                ON manifest.project_id = semantic_spec.project_id
               AND manifest.id = (
                    semantic_spec.spec_payload->'semantic_metrics'->>'manifest_id'
               )::uuid
               AND manifest.manifest_hash =
                    semantic_spec.spec_payload->'semantic_metrics'->>'manifest_hash'
               AND manifest.sampling_run_id = snapshot.run_id
               AND manifest.source_stratum_hash = snapshot.source_stratum_hash
               AND manifest.capture_method = snapshot.capture_method
              JOIN workflow_c_analysis_input_manifest_items AS manifest_item
                ON manifest_item.project_id = manifest.project_id
               AND manifest_item.manifest_id = manifest.id
               AND manifest_item.question_cluster = lineage.question_cluster
               AND manifest_item.observation_status = 'complete'
               AND manifest_item.observation_id IS NOT NULL
              JOIN workflow_c_sampling_observations AS observation
                ON observation.project_id = manifest_item.project_id
               AND observation.id = manifest_item.observation_id
               AND observation.observation_hash = manifest_item.observation_hash
               AND observation.status = 'complete'
             GROUP BY lineage.project_id, lineage.family_hash, lineage.comparison_id
        )
        SELECT jsonb_build_object(
            'kind', 'metric_comparison',
            'project_id', lineage.project_id::text,
            'resource_id', lineage.family_hash || ':' || lineage.comparison_id,
            'version', lineage.family_hash,
            'sha256', lineage.family_hash,
            'locator', jsonb_build_object(
                'comparison_family_hash', lineage.family_hash,
                'comparison_id', lineage.comparison_id
            ),
            'valid', lineage.family_status = 'complete',
            'observation_resource_ids', membership.observation_resource_ids,
            'method_version', lineage.bootstrap_method,
            'method_sha256', lineage.protocol_hash,
            'sufficient_evidence', lineage.family_status = 'complete'
                AND lineage.conclusion IN ('win', 'equivalent', 'loss'),
            'summary', NULL
        ) INTO resolved
        FROM comparison_lineage AS lineage
        JOIN observation_membership AS membership
          ON membership.project_id = lineage.project_id
         AND membership.family_hash = lineage.family_hash
         AND membership.comparison_id = lineage.comparison_id;
        RETURN resolved;
    END IF;

    RETURN geo_resolve_recommendation_evidence_pre_0082(
        p_project_id, p_kind, p_resource_id
    );
END;
$$;

REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    TO geo_app, geo_worker;
