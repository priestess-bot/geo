-- Cancellation is a command boundary, not a direct aggregate write.  A Run
-- releases only Tasks that never consumed its frozen reservation.  Provider
-- Jobs that already consumed a reservation retain that consumption even when
-- they are cancelled before external execution begins.

CREATE FUNCTION geo_mark_workflow_c_provider_sampling_cancelled()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
BEGIN
    IF NEW.kind <> 'sampling.provider_execute' OR NEW.status <> 'cancelled' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO attempt_row
      FROM workflow_c_sampling_attempts
     WHERE project_id = NEW.project_id AND durable_job_id = NEW.id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'cancelled Provider Sampling Job has no Attempt aggregate'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO task_row
      FROM workflow_c_sampling_tasks
     WHERE project_id = NEW.project_id AND id = attempt_row.task_id
     FOR UPDATE;
    SELECT * INTO run_row
      FROM workflow_c_sampling_runs
     WHERE project_id = NEW.project_id AND id = attempt_row.run_id
     FOR UPDATE;
    IF task_row.id IS NULL OR run_row.id IS NULL OR task_row.run_id <> run_row.id THEN
        RAISE EXCEPTION 'cancelled Provider Sampling Attempt has invalid aggregate lineage'
            USING ERRCODE = '40001';
    END IF;
    IF attempt_row.status NOT IN ('succeeded', 'failed', 'cancelled') THEN
        UPDATE workflow_c_sampling_attempts
           SET status = 'cancelled', error_code = 'cancelled', version = version + 1,
               updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = attempt_row.id
           AND version = attempt_row.version;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Provider Sampling Attempt cancellation was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    IF task_row.status NOT IN ('succeeded', 'failed', 'cancelled') THEN
        UPDATE workflow_c_sampling_tasks
           SET status = 'cancelled', version = version + 1, updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = task_row.id
           AND version = task_row.version;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Provider Sampling Task cancellation was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    IF run_row.status IN ('planned', 'running', 'cancel_requested')
       AND NOT EXISTS (
            SELECT 1 FROM workflow_c_sampling_tasks
             WHERE project_id = NEW.project_id AND run_id = run_row.id
               AND status NOT IN ('succeeded', 'failed', 'cancelled')
       ) THEN
        UPDATE workflow_c_sampling_runs
           SET status = 'cancelled', version = version + 1
         WHERE project_id = NEW.project_id AND id = run_row.id
           AND version = run_row.version;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER workflow_c_provider_sampling_cancelled
AFTER UPDATE OF status ON durable_jobs
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION geo_mark_workflow_c_provider_sampling_cancelled();

CREATE FUNCTION geo_cancel_workflow_c_sampling_attempt(
    p_project_id uuid,
    p_attempt_id uuid,
    p_expected_task_version integer,
    p_expected_attempt_version integer,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_cancelled_at timestamptz
) RETURNS TABLE (
    run_id uuid,
    task_id uuid,
    attempt_id uuid,
    task_version integer,
    attempt_version integer,
    run_status text,
    cancellation_requested boolean,
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE durable_row durable_jobs%ROWTYPE;
DECLARE requested boolean := false;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Sampling Attempt cancellation is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_attempt_id IS NULL OR p_expected_task_version < 1
       OR p_expected_attempt_version < 1
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_cancelled_at IS NULL THEN
        RAISE EXCEPTION 'Sampling Attempt cancellation command is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-sampling-attempt-cancel:' || p_project_id::text || ':'
            || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.attempt.cancel'
       AND aggregate_id = p_attempt_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_attempt_id THEN
            RAISE EXCEPTION 'Sampling Attempt cancellation idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
         WHERE project_id = p_project_id AND id = p_attempt_id;
        SELECT * INTO task_row FROM workflow_c_sampling_tasks
         WHERE project_id = p_project_id AND id = attempt_row.task_id;
        SELECT * INTO run_row FROM workflow_c_sampling_runs
         WHERE project_id = p_project_id AND id = attempt_row.run_id;
        RETURN QUERY SELECT run_row.id, task_row.id, attempt_row.id,
            task_row.version, attempt_row.version, run_row.status, false, true;
        RETURN;
    END IF;
    SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
     WHERE project_id = p_project_id AND id = p_attempt_id FOR UPDATE;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND id = attempt_row.task_id FOR UPDATE;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = attempt_row.run_id FOR UPDATE;
    SELECT * INTO durable_row FROM durable_jobs
     WHERE project_id = p_project_id AND id = attempt_row.durable_job_id FOR UPDATE;
    IF attempt_row.id IS NULL OR task_row.id IS NULL OR run_row.id IS NULL OR durable_row.id IS NULL
       OR task_row.run_id <> run_row.id OR attempt_row.run_id <> run_row.id
       OR attempt_row.task_id <> task_row.id OR durable_row.kind <> 'sampling.provider_execute'
       OR task_row.version <> p_expected_task_version
       OR attempt_row.version <> p_expected_attempt_version THEN
        RAISE EXCEPTION 'Sampling Attempt cancellation was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF durable_row.status IN ('succeeded', 'failed', 'dead_lettered', 'cancelled')
       OR attempt_row.status IN ('succeeded', 'failed', 'cancelled') THEN
        RAISE EXCEPTION 'Sampling Attempt is already terminal'
            USING ERRCODE = '40001';
    END IF;
    IF durable_row.status IN ('queued', 'retry_wait') THEN
        UPDATE durable_jobs
           SET status = 'cancelled', error_code = 'cancelled',
               error_detail = jsonb_build_object('sampling_status', 'cancelled'),
               completed_at = p_cancelled_at, updated_at = p_cancelled_at
         WHERE project_id = p_project_id AND id = durable_row.id
           AND status = durable_row.status;
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
        ) VALUES (
            p_project_id, durable_row.id, 'job_cancelled', 'sampling-api',
            durable_row.fencing_generation, jsonb_build_object('reason', 'api_cancel'),
            p_cancelled_at
        );
    ELSIF durable_row.status IN ('running', 'finalizing') THEN
        UPDATE durable_jobs
           SET cancel_requested_at = coalesce(cancel_requested_at, p_cancelled_at),
               updated_at = p_cancelled_at
         WHERE project_id = p_project_id AND id = durable_row.id
           AND lease_token IS NOT NULL AND fencing_generation = durable_row.fencing_generation;
        UPDATE workflow_c_sampling_tasks
           SET status = 'cancel_requested', version = version + 1, updated_at = p_cancelled_at
         WHERE project_id = p_project_id AND id = task_row.id
           AND version = task_row.version AND status NOT IN ('succeeded', 'failed', 'cancelled');
        requested := true;
    ELSE
        RAISE EXCEPTION 'Sampling Attempt durable Job cannot be cancelled from its current state'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
     WHERE project_id = p_project_id AND id = p_attempt_id;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND id = attempt_row.task_id;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = attempt_row.run_id;
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.attempt.cancel', p_attempt_id, p_idempotency_key_hash,
        p_input_hash, 'sampling_attempt', p_attempt_id, attempt_row.version,
        jsonb_build_object('run_id', run_row.id::text, 'task_id', task_row.id::text,
            'attempt_id', attempt_row.id::text, 'cancellation_requested', requested),
        p_cancelled_at
    );
    RETURN QUERY SELECT run_row.id, task_row.id, attempt_row.id,
        task_row.version, attempt_row.version, run_row.status, requested, false;
END;
$$;

CREATE FUNCTION geo_cancel_workflow_c_sampling_run(
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
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE durable_row durable_jobs%ROWTYPE;
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE item record;
DECLARE released integer := 0;
DECLARE requested integer := 0;
DECLARE usage_start timestamptz;
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
        RETURN QUERY SELECT p_run_id,
            (existing.result_payload->>'run_status'),
            (existing.result_payload->>'released_task_count')::integer,
            (existing.result_payload->>'cancellation_requested_count')::integer,
            true;
        RETURN;
    END IF;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    IF NOT FOUND OR run_row.status IN ('completed', 'cancelled', 'failed') THEN
        RAISE EXCEPTION 'Sampling Run cannot be cancelled from its current state'
            USING ERRCODE = '40001';
    END IF;
    -- Mark the aggregate before terminalizing queued Jobs.  A later Worker
    -- confirmation can still turn this into terminal `cancelled` once every
    -- active Attempt has acknowledged the cancellation request.
    UPDATE workflow_c_sampling_runs
       SET status = 'cancel_requested', version = version + 1
     WHERE project_id = p_project_id AND id = p_run_id
       AND version = run_row.version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling Run cancellation was fenced'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;

    UPDATE workflow_c_sampling_tasks AS task
       SET status = 'cancelled', version = version + 1, updated_at = p_cancelled_at
     WHERE task.project_id = p_project_id AND task.run_id = p_run_id
       AND task.status = 'planned';
    GET DIAGNOSTICS released = ROW_COUNT;

    FOR item IN
        SELECT attempt.id AS attempt_id, task.id AS task_id, durable.id AS durable_id
          FROM workflow_c_sampling_attempts AS attempt
          JOIN workflow_c_sampling_tasks AS task
            ON task.project_id = attempt.project_id AND task.id = attempt.task_id
          JOIN durable_jobs AS durable
            ON durable.project_id = attempt.project_id AND durable.id = attempt.durable_job_id
         WHERE attempt.project_id = p_project_id AND attempt.run_id = p_run_id
           AND attempt.status NOT IN ('succeeded', 'failed', 'cancelled')
         ORDER BY attempt.id
         FOR UPDATE OF attempt, task, durable
    LOOP
        SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
         WHERE project_id = p_project_id AND id = item.attempt_id;
        SELECT * INTO task_row FROM workflow_c_sampling_tasks
         WHERE project_id = p_project_id AND id = item.task_id;
        SELECT * INTO durable_row FROM durable_jobs
         WHERE project_id = p_project_id AND id = item.durable_id;
        IF durable_row.status IN ('queued', 'retry_wait') THEN
            UPDATE durable_jobs
               SET status = 'cancelled', error_code = 'cancelled',
                   error_detail = jsonb_build_object('sampling_status', 'cancelled'),
                   completed_at = p_cancelled_at, updated_at = p_cancelled_at
             WHERE project_id = p_project_id AND id = durable_row.id
               AND status = durable_row.status;
            INSERT INTO durable_job_events(
                project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
            ) VALUES (
                p_project_id, durable_row.id, 'job_cancelled', 'sampling-api',
                durable_row.fencing_generation, jsonb_build_object('reason', 'run_cancel'),
                p_cancelled_at
            );
            requested := requested + 1;
        ELSIF durable_row.status IN ('running', 'finalizing') THEN
            UPDATE durable_jobs
               SET cancel_requested_at = coalesce(cancel_requested_at, p_cancelled_at),
                   updated_at = p_cancelled_at
             WHERE project_id = p_project_id AND id = durable_row.id
               AND lease_token IS NOT NULL AND fencing_generation = durable_row.fencing_generation;
            UPDATE workflow_c_sampling_tasks
               SET status = 'cancel_requested', version = version + 1, updated_at = p_cancelled_at
             WHERE project_id = p_project_id AND id = task_row.id
               AND version = task_row.version AND status NOT IN ('succeeded', 'failed', 'cancelled');
            requested := requested + 1;
        END IF;
    END LOOP;

    IF released > 0 THEN
        usage_start := date_trunc('day', run_row.created_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
        UPDATE workflow_c_sampling_admission_usage
           SET released_count = released_count + released,
               version = version + 1, updated_at = GREATEST(updated_at, p_cancelled_at)
         WHERE project_id = p_project_id AND policy_id = run_row.admission_policy_id
           AND window_start = usage_start
           AND released_count + released <= reserved_count;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Sampling Run cancellation usage release was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    UPDATE workflow_c_sampling_runs AS run
       SET released_task_count = run.released_task_count + released,
           status = CASE
                WHEN EXISTS (
                    SELECT 1 FROM workflow_c_sampling_tasks AS task
                     WHERE task.project_id = p_project_id AND task.run_id = p_run_id
                       AND task.status NOT IN ('succeeded', 'failed', 'cancelled')
                ) THEN 'cancel_requested'
                ELSE 'cancelled'
           END,
           version = run.version + 1
     WHERE run.project_id = p_project_id AND run.id = p_run_id
       AND run.version = run_row.version
       AND run.released_task_count + released + run.consumed_task_count
           <= run.reserved_task_count;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling Run cancellation was fenced'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id;
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.run.cancel', p_run_id, p_idempotency_key_hash,
        p_input_hash, 'sampling_run', p_run_id, run_row.version,
        jsonb_build_object('run_status', run_row.status,
            'released_task_count', released,
            'cancellation_requested_count', requested),
        p_cancelled_at
    );
    RETURN QUERY SELECT run_row.id, run_row.status, released, requested, false;
END;
$$;

REVOKE ALL ON FUNCTION geo_mark_workflow_c_provider_sampling_cancelled()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_cancel_workflow_c_sampling_attempt(
    uuid, uuid, integer, integer, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_cancel_workflow_c_sampling_run(
    uuid, uuid, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_cancel_workflow_c_sampling_attempt(
    uuid, uuid, integer, integer, text, text, timestamptz
) TO geo_app;
GRANT EXECUTE ON FUNCTION geo_cancel_workflow_c_sampling_run(
    uuid, uuid, text, text, timestamptz
) TO geo_app;
