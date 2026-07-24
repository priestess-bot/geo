-- The original Attempt RPC correctly fenced policy, Suite and Job lineage but
-- delegated next_run_at to the generic producer, which always used now.  This
-- wrapper makes requested-not-before durable and removes the unscheduled RPC
-- from the application role.

CREATE FUNCTION geo_schedule_workflow_c_provider_sampling_attempt(
    p_project_id uuid,
    p_attempt_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_run_id uuid,
    p_task_id uuid,
    p_expected_task_version integer,
    p_spec_hash text,
    p_spec_payload jsonb,
    p_job_idempotency_key text,
    p_authorization_checked_at timestamptz,
    p_requested_not_before timestamptz
) RETURNS TABLE (
    attempt_id uuid,
    durable_job_id uuid,
    task_version integer,
    attempt_version integer,
    run_version integer,
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE scheduled_at timestamptz;
DECLARE stored_next_run_at timestamptz;
DECLARE result_row record;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_requested_not_before IS NULL THEN
        RAISE EXCEPTION 'Provider Sampling Attempt schedule is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id FOR SHARE;
    IF run_row.id IS NULL
       OR p_requested_not_before >= run_row.authorization_valid_until THEN
        RAISE EXCEPTION 'Provider Sampling Attempt schedule is outside authorization'
            USING ERRCODE = '23514';
    END IF;
    scheduled_at := GREATEST(p_requested_not_before, run_row.admitted_not_before);
    SELECT * INTO result_row
      FROM geo_enqueue_workflow_c_provider_sampling_attempt(
          p_project_id, p_attempt_id, p_idempotency_key_hash, p_input_hash,
          p_run_id, p_task_id, p_expected_task_version, p_spec_hash,
          p_spec_payload, p_job_idempotency_key, p_authorization_checked_at
      );
    SELECT next_run_at INTO stored_next_run_at
      FROM durable_jobs
     WHERE project_id = p_project_id AND id = result_row.durable_job_id
     FOR UPDATE;
    IF stored_next_run_at IS NULL THEN
        RAISE EXCEPTION 'Provider Sampling Attempt has no durable schedule'
            USING ERRCODE = '40001';
    END IF;
    IF result_row.replayed THEN
        -- Immediate past requests intentionally retain the producer timestamp;
        -- deferred requests must replay the exact frozen execution time.
        IF scheduled_at > p_authorization_checked_at
           AND stored_next_run_at <> scheduled_at THEN
            RAISE EXCEPTION 'Provider Sampling Attempt idempotency schedule changed'
                USING ERRCODE = '23505';
        END IF;
    ELSIF scheduled_at > p_authorization_checked_at THEN
        UPDATE durable_jobs
           SET next_run_at = scheduled_at, updated_at = clock_timestamp()
         WHERE project_id = p_project_id AND id = result_row.durable_job_id
           AND status = 'queued';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Provider Sampling Attempt schedule was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    RETURN QUERY SELECT result_row.attempt_id, result_row.durable_job_id,
        result_row.task_version, result_row.attempt_version, result_row.run_version,
        result_row.replayed;
END;
$$;

REVOKE ALL ON FUNCTION geo_enqueue_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz
) FROM geo_app;
REVOKE ALL ON FUNCTION geo_schedule_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_schedule_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz, timestamptz
) TO geo_app;

COMMENT ON FUNCTION geo_schedule_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz, timestamptz
) IS 'Atomically admits a Provider Sampling Attempt and preserves its requested-not-before schedule.';
