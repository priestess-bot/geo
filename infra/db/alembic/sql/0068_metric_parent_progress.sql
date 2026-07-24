-- A Metric parent must never rely on inherited table privileges.  The Worker
-- login is deliberately NOINHERIT, so these two narrowly-scoped readers prove
-- the fenced parent lease before exposing only its own batch progression and
-- hash-bound Judge projections.
CREATE FUNCTION geo_read_workflow_c_metric_parent_batches(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_parent_input_hash text
) RETURNS TABLE (
    id uuid,
    observation_id uuid,
    ordinal integer,
    planned_batch_count integer,
    plans_hash text,
    parent_input_hash text,
    input_set_hash text,
    metric_suite_hash text,
    status text,
    selected_candidate_id uuid,
    selected_output_hash text,
    arbiter_child_job_id uuid,
    arbiter_child_status text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE parent_job durable_jobs%ROWTYPE;
DECLARE parent_spec workflow_c_job_specs%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_parent_job_id IS NULL
       OR p_lease_token IS NULL
       OR p_fencing_generation IS NULL
       OR p_fencing_generation < 1
       OR p_parent_input_hash IS NULL
       OR p_parent_input_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Workflow C Metric parent progress input is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT parent_durable.* INTO parent_job
      FROM durable_jobs AS parent_durable
     WHERE parent_durable.project_id = p_project_id
       AND parent_durable.id = p_parent_job_id
     FOR SHARE;
    SELECT parent_spec_row.* INTO parent_spec
      FROM workflow_c_job_specs AS parent_spec_row
     WHERE parent_spec_row.project_id = p_project_id
       AND parent_spec_row.job_id = p_parent_job_id
     FOR SHARE;
    IF parent_job.id IS NULL OR parent_spec.job_id IS NULL
       OR parent_job.kind <> 'workflow_c.analysis.semantic_metrics'
       OR parent_spec.kind <> parent_job.kind
       OR parent_job.input_hash <> p_parent_input_hash
       OR parent_spec.spec_hash <> p_parent_input_hash
       OR parent_job.status <> 'running'
       OR parent_job.lease_token IS DISTINCT FROM p_lease_token
       OR parent_job.fencing_generation <> p_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= clock_timestamp()
       OR parent_job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C Metric parent lease or frozen input was fenced'
            USING ERRCODE = '40001';
    END IF;

    RETURN QUERY
    SELECT batch.id, batch.observation_id, batch.ordinal, batch.planned_batch_count,
           batch.plans_hash, batch.parent_input_hash, batch.input_set_hash,
           batch.metric_suite_hash, batch.status, batch.selected_candidate_id,
           batch.selected_output_hash, batch.arbiter_child_job_id,
           (
               SELECT arbiter.status
                 FROM workflow_c_metric_model_children AS arbiter
                WHERE arbiter.project_id = batch.project_id
                  AND arbiter.parent_job_id = p_parent_job_id
                  AND arbiter.batch_id = batch.id
                  AND arbiter.child_job_id = batch.arbiter_child_job_id
                  AND arbiter.role = 'arbiter'
           ) AS arbiter_child_status
      FROM workflow_c_metric_judge_batches AS batch
     WHERE batch.project_id = p_project_id
       AND batch.parent_job_id = p_parent_job_id
       AND batch.parent_input_hash = p_parent_input_hash
     ORDER BY batch.observation_id, batch.ordinal;
END;
$$;

CREATE FUNCTION geo_read_workflow_c_metric_parent_judges(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_parent_input_hash text,
    p_batch_id uuid
) RETURNS TABLE (
    candidate_id uuid,
    evaluator_id text,
    status text,
    output_hash text,
    projection_hash text,
    output_projection jsonb
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE parent_job durable_jobs%ROWTYPE;
DECLARE parent_spec workflow_c_job_specs%ROWTYPE;
DECLARE batch workflow_c_metric_judge_batches%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_parent_job_id IS NULL
       OR p_lease_token IS NULL
       OR p_fencing_generation IS NULL
       OR p_fencing_generation < 1
       OR p_parent_input_hash IS NULL
       OR p_parent_input_hash !~ '^[0-9a-f]{64}$'
       OR p_batch_id IS NULL THEN
        RAISE EXCEPTION 'Workflow C Metric parent Judge read input is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT parent_durable.* INTO parent_job
      FROM durable_jobs AS parent_durable
     WHERE parent_durable.project_id = p_project_id
       AND parent_durable.id = p_parent_job_id
     FOR SHARE;
    SELECT parent_spec_row.* INTO parent_spec
      FROM workflow_c_job_specs AS parent_spec_row
     WHERE parent_spec_row.project_id = p_project_id
       AND parent_spec_row.job_id = p_parent_job_id
     FOR SHARE;
    IF parent_job.id IS NULL OR parent_spec.job_id IS NULL
       OR parent_job.kind <> 'workflow_c.analysis.semantic_metrics'
       OR parent_spec.kind <> parent_job.kind
       OR parent_job.input_hash <> p_parent_input_hash
       OR parent_spec.spec_hash <> p_parent_input_hash
       OR parent_job.status <> 'running'
       OR parent_job.lease_token IS DISTINCT FROM p_lease_token
       OR parent_job.fencing_generation <> p_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= clock_timestamp()
       OR parent_job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C Metric parent lease or frozen input was fenced'
            USING ERRCODE = '40001';
    END IF;

    SELECT batch_row.* INTO batch
      FROM workflow_c_metric_judge_batches AS batch_row
     WHERE batch_row.project_id = p_project_id AND batch_row.id = p_batch_id;
    IF batch.id IS NULL OR batch.parent_job_id <> p_parent_job_id
       OR batch.parent_input_hash <> p_parent_input_hash THEN
        RAISE EXCEPTION 'Workflow C Metric parent batch lineage was fenced'
            USING ERRCODE = '40001';
    END IF;

    RETURN QUERY
    SELECT child.candidate_id, child.evaluator_id, child.status, child.output_hash,
           projection.output_hash AS projection_hash, projection.output_projection
      FROM workflow_c_metric_model_children AS child
      LEFT JOIN workflow_c_metric_child_output_projections AS projection
        ON projection.project_id = child.project_id
       AND projection.child_job_id = child.child_job_id
       AND projection.output_hash = child.output_hash
     WHERE child.project_id = p_project_id
       AND child.parent_job_id = p_parent_job_id
       AND child.batch_id = p_batch_id
       AND child.role = 'metric_judge'
     ORDER BY child.evaluator_id, child.candidate_id;
END;
$$;

REVOKE ALL ON FUNCTION geo_read_workflow_c_metric_parent_batches(
    uuid, uuid, uuid, integer, text
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_read_workflow_c_metric_parent_batches(
    uuid, uuid, uuid, integer, text
) TO geo_worker;

REVOKE ALL ON FUNCTION geo_read_workflow_c_metric_parent_judges(
    uuid, uuid, uuid, integer, text, uuid
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_read_workflow_c_metric_parent_judges(
    uuid, uuid, uuid, integer, text, uuid
) TO geo_worker;

COMMENT ON FUNCTION geo_read_workflow_c_metric_parent_batches(
    uuid, uuid, uuid, integer, text
) IS 'Worker-only fenced Metric-parent batch progress; excludes encrypted tasks and raw model output.';
COMMENT ON FUNCTION geo_read_workflow_c_metric_parent_judges(
    uuid, uuid, uuid, integer, text, uuid
) IS 'Worker-only fenced Metric-parent Judge projections; excludes encrypted tasks and raw model output.';
