-- Restore the fenced 0061 completion RPC from version-controlled source.
CREATE OR REPLACE FUNCTION geo_complete_workflow_c_metric_child(
    p_project_id uuid,
    p_child_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_parent_input_hash text,
    p_role text,
    p_model_attempt_id uuid,
    p_output_hash text,
    p_selected_candidate_id uuid,
    p_selected_output_hash text
) RETURNS TABLE (
    child_status text,
    batch_status text,
    batch_id uuid,
    aggregate_version integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE child workflow_c_metric_model_children%ROWTYPE;
DECLARE batch workflow_c_metric_judge_batches%ROWTYPE;
DECLARE job durable_jobs%ROWTYPE;
DECLARE expected_kind text;
DECLARE judge_count integer;
DECLARE judge_output_count integer;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_child_job_id IS NULL OR p_lease_token IS NULL OR p_fencing_generation < 1
       OR p_parent_input_hash !~ '^[0-9a-f]{64}$'
       OR p_role NOT IN ('metric_judge', 'arbiter')
       OR p_model_attempt_id IS NULL OR p_output_hash !~ '^[0-9a-f]{64}$'
       OR (p_role = 'metric_judge' AND (
           p_selected_candidate_id IS NOT NULL OR p_selected_output_hash IS NOT NULL
       ))
       OR (p_role = 'arbiter' AND (
           p_selected_candidate_id IS NULL OR p_selected_output_hash !~ '^[0-9a-f]{64}$'
       )) THEN
        RAISE EXCEPTION 'Workflow C metric child completion input is invalid'
            USING ERRCODE = '22023';
    END IF;
    expected_kind := CASE p_role
        WHEN 'metric_judge' THEN 'workflow_c.metric_judge'
        ELSE 'workflow_c.metric_arbiter'
    END;
    SELECT * INTO child FROM workflow_c_metric_model_children
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id FOR UPDATE;
    SELECT * INTO job FROM durable_jobs
    WHERE project_id = p_project_id AND id = p_child_job_id FOR SHARE;
    IF child.child_job_id IS NULL OR job.id IS NULL
       OR child.role <> p_role OR child.parent_input_hash <> p_parent_input_hash
       OR child.status NOT IN ('queued', 'running')
       OR job.kind <> expected_kind OR job.input_hash <> child.task_hash
       OR job.status <> 'running' OR job.lease_token IS DISTINCT FROM p_lease_token
       OR job.fencing_generation <> p_fencing_generation
       OR job.lease_expires_at IS NULL OR job.lease_expires_at <= clock_timestamp()
       OR job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C metric child completion was fenced'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO batch FROM workflow_c_metric_judge_batches
    WHERE project_id = p_project_id AND id = child.batch_id FOR UPDATE;
    IF batch.id IS NULL OR batch.parent_job_id <> child.parent_job_id
       OR batch.parent_input_hash <> p_parent_input_hash
       OR batch.status NOT IN ('queued', 'running') THEN
        RAISE EXCEPTION 'Workflow C metric batch completion was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF p_role = 'arbiter' THEN
        SELECT count(*), count(DISTINCT output_hash)
        INTO judge_count, judge_output_count
        FROM workflow_c_metric_model_children
        WHERE project_id = p_project_id AND batch_id = child.batch_id
          AND role = 'metric_judge' AND status = 'succeeded' AND output_hash IS NOT NULL;
        IF judge_count < 2 OR judge_output_count < 2
           OR EXISTS (
               SELECT 1 FROM workflow_c_metric_model_children AS judge
               WHERE judge.project_id = p_project_id AND judge.batch_id = child.batch_id
                 AND judge.role = 'metric_judge'
                 AND (judge.status <> 'succeeded' OR judge.output_hash IS NULL)
           )
           OR NOT EXISTS (
               SELECT 1 FROM workflow_c_metric_model_children AS judge
               WHERE judge.project_id = p_project_id AND judge.batch_id = child.batch_id
                 AND judge.role = 'metric_judge'
                 AND judge.candidate_id = p_selected_candidate_id
                 AND judge.output_hash = p_selected_output_hash
                 AND judge.status = 'succeeded'
           ) THEN
            RAISE EXCEPTION 'Workflow C metric arbiter candidates are incomplete or inconsistent'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    UPDATE workflow_c_metric_model_children
    SET status = 'succeeded', model_attempt_id = p_model_attempt_id,
        output_hash = p_output_hash, error_code = NULL, completed_at = clock_timestamp()
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id
      AND status IN ('queued', 'running');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C metric child state changed during completion'
            USING ERRCODE = '40001';
    END IF;
    IF p_role = 'arbiter' THEN
        UPDATE workflow_c_metric_judge_batches
        SET status = 'completed', selected_candidate_id = p_selected_candidate_id,
            selected_output_hash = p_selected_output_hash,
            aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1,
            completed_at = clock_timestamp()
        WHERE project_id = p_project_id AND id = child.batch_id
          AND status IN ('queued', 'running');
    ELSE
        UPDATE workflow_c_metric_judge_batches
        SET status = 'running',
            aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1
        WHERE project_id = p_project_id AND id = child.batch_id
          AND status IN ('queued', 'running');
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C metric batch state changed during completion'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO child FROM workflow_c_metric_model_children
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id;
    SELECT * INTO batch FROM workflow_c_metric_judge_batches
    WHERE project_id = p_project_id AND id = child.batch_id;
    RETURN QUERY SELECT child.status, batch.status, batch.id, batch.aggregate_version;
END;
$$;
