-- The original cancellation RPC remains callable for compatibility.  This
-- wrapper takes the same transaction-scoped advisory lock, freezes the exact
-- active Attempt IDs before terminalization, and appends that immutable result
-- lineage to the existing command ledger entry.  Replays therefore never
-- infer affected Attempts from their current mutable state.

CREATE FUNCTION geo_cancel_workflow_c_sampling_run_v2(
    p_project_id uuid,
    p_run_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_cancelled_at timestamptz
) RETURNS TABLE (
    run_id uuid,
    run_status text,
    released_task_count integer,
    cancellation_requested_count integer,
    attempt_ids uuid[],
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE result_row record;
DECLARE targeted_attempt_ids uuid[] := ARRAY[]::uuid[];
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Sampling Run cancellation is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_run_id IS NULL OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_cancelled_at IS NULL THEN
        RAISE EXCEPTION 'Sampling Run cancellation command is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-sampling-run-cancel:' || p_project_id::text || ':'
            || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing FROM workflow_c_command_ledger
     WHERE project_id = p_project_id AND command_scope = 'sampling.run.cancel'
       AND aggregate_id = p_run_id AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_run_id THEN
            RAISE EXCEPTION 'Sampling Run cancellation idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        IF jsonb_typeof(existing.result_payload->'attempt_ids') <> 'array' THEN
            RAISE EXCEPTION 'Sampling Run cancellation replay lacks immutable Attempt lineage'
                USING ERRCODE = '55000';
        END IF;
        RETURN QUERY SELECT p_run_id,
            existing.result_payload->>'run_status',
            (existing.result_payload->>'released_task_count')::integer,
            (existing.result_payload->>'cancellation_requested_count')::integer,
            ARRAY(
                SELECT value::uuid
                  FROM jsonb_array_elements_text(existing.result_payload->'attempt_ids')
                 ORDER BY value::uuid
            ),
            true;
        RETURN;
    END IF;

    -- The compatible RPC locks the Run before it locks any Attempt.  Take the
    -- same lock order here so cancellation commands with different keys cannot
    -- deadlock while acting on one Run.
    PERFORM 1
      FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id
     FOR UPDATE;

    -- This locks the exact same active Provider Attempt/Task/Job rows that
    -- the compatible RPC will act on.  The lock is retained through its call.
    SELECT coalesce(array_agg(locked.attempt_id ORDER BY locked.attempt_id), ARRAY[]::uuid[])
      INTO targeted_attempt_ids
      FROM (
            SELECT attempt.id AS attempt_id
              FROM workflow_c_sampling_attempts AS attempt
              JOIN workflow_c_sampling_tasks AS task
                ON task.project_id = attempt.project_id AND task.id = attempt.task_id
              JOIN durable_jobs AS durable
                ON durable.project_id = attempt.project_id AND durable.id = attempt.durable_job_id
             WHERE attempt.project_id = p_project_id AND attempt.run_id = p_run_id
               AND attempt.status NOT IN ('succeeded', 'failed', 'cancelled')
               AND durable.status IN ('queued', 'retry_wait', 'running', 'finalizing')
             ORDER BY attempt.id
             FOR UPDATE OF attempt, task, durable
      ) AS locked;

    SELECT * INTO result_row
      FROM geo_cancel_workflow_c_sampling_run(
          p_project_id,
          p_run_id,
          p_idempotency_key_hash,
          p_input_hash,
          p_cancelled_at
      );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling Run cancellation did not return'
            USING ERRCODE = '40001';
    END IF;
    IF result_row.replayed THEN
        RAISE EXCEPTION 'Sampling Run cancellation wrapper observed an unexpected replay'
            USING ERRCODE = '40001';
    END IF;

    UPDATE workflow_c_command_ledger
       SET result_payload = result_payload || jsonb_build_object(
               'cancellation_result_schema_version', 2,
               'attempt_ids', to_jsonb(targeted_attempt_ids)
           )
     WHERE project_id = p_project_id AND command_scope = 'sampling.run.cancel'
       AND aggregate_id = p_run_id AND idempotency_key_hash = p_idempotency_key_hash
       AND input_hash = p_input_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling Run cancellation result ledger was fenced'
            USING ERRCODE = '40001';
    END IF;

    RETURN QUERY SELECT result_row.run_id, result_row.run_status,
        result_row.released_task_count, result_row.cancellation_requested_count,
        targeted_attempt_ids, false;
END;
$$;

REVOKE ALL ON FUNCTION geo_cancel_workflow_c_sampling_run_v2(
    uuid, uuid, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_cancel_workflow_c_sampling_run_v2(
    uuid, uuid, text, text, timestamptz
) TO geo_app;

COMMENT ON FUNCTION geo_cancel_workflow_c_sampling_run_v2(
    uuid, uuid, text, text, timestamptz
) IS 'Cancels a Sampling Run and persists exact Provider Attempt lineage for idempotent API replay.';
