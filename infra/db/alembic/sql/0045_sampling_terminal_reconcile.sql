-- The Provider Worker normally writes the Sampling aggregate and the Durable
-- Job in one fenced transaction.  This trigger closes the exceptional path in
-- which the shared dispatcher terminalizes an unexpected Worker exception or
-- exhausts a retry after the Worker has already lost that opportunity.

CREATE FUNCTION geo_reconcile_workflow_c_provider_sampling_durable_status()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE safe_error_code text;
BEGIN
    IF NEW.kind <> 'sampling.provider_execute'
       OR NEW.status NOT IN ('retry_wait', 'failed', 'dead_lettered') THEN
        RETURN NEW;
    END IF;
    SELECT * INTO attempt_row
      FROM workflow_c_sampling_attempts
     WHERE project_id = NEW.project_id AND durable_job_id = NEW.id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Provider Sampling Durable Job has no Attempt aggregate'
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
    IF task_row.id IS NULL OR run_row.id IS NULL
       OR task_row.run_id <> run_row.id OR attempt_row.task_id <> task_row.id THEN
        RAISE EXCEPTION 'Provider Sampling Durable Job aggregate lineage is invalid'
            USING ERRCODE = '40001';
    END IF;
    safe_error_code := CASE
        WHEN NEW.error_code ~ '^[a-z][a-z0-9_.:-]{0,99}$' THEN NEW.error_code
        ELSE 'worker_unhandled'
    END;

    IF NEW.status = 'retry_wait' THEN
        -- A normal retry has already transitioned the aggregate through the
        -- fenced failure RPC.  Only repair an exception that bypassed it.
        IF attempt_row.status = 'running' THEN
            UPDATE workflow_c_sampling_attempts
               SET status = 'queued', error_code = safe_error_code,
                   version = version + 1, updated_at = clock_timestamp()
             WHERE project_id = NEW.project_id AND id = attempt_row.id
               AND version = attempt_row.version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Provider Sampling retry Attempt was fenced'
                    USING ERRCODE = '40001';
            END IF;
        END IF;
        IF task_row.status IN ('running', 'finalizing') THEN
            UPDATE workflow_c_sampling_tasks
               SET status = 'retry_ready', version = version + 1,
                   updated_at = clock_timestamp()
             WHERE project_id = NEW.project_id AND id = task_row.id
               AND version = task_row.version;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Provider Sampling retry Task was fenced'
                    USING ERRCODE = '40001';
            END IF;
        END IF;
        RETURN NEW;
    END IF;

    -- A terminal Durable failure cannot leave a Sampling denominator member
    -- marked executable.  Known fenced failure writes are already terminal,
    -- so these updates are idempotent for the normal path.
    IF attempt_row.status NOT IN ('succeeded', 'failed', 'cancelled') THEN
        UPDATE workflow_c_sampling_attempts
           SET status = 'failed', error_code = safe_error_code,
               version = version + 1, updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = attempt_row.id
           AND version = attempt_row.version;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Provider Sampling terminal Attempt was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    IF task_row.status NOT IN ('succeeded', 'failed', 'cancelled') THEN
        UPDATE workflow_c_sampling_tasks
           SET status = 'failed', version = version + 1,
               updated_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = task_row.id
           AND version = task_row.version;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Provider Sampling terminal Task was fenced'
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
           SET status = CASE WHEN run_row.status = 'cancel_requested'
                             THEN 'cancelled' ELSE 'failed' END,
               version = version + 1
         WHERE project_id = NEW.project_id AND id = run_row.id
           AND version = run_row.version;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER workflow_c_provider_sampling_durable_status
AFTER UPDATE OF status ON durable_jobs
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION geo_reconcile_workflow_c_provider_sampling_durable_status();

REVOKE ALL ON FUNCTION geo_reconcile_workflow_c_provider_sampling_durable_status()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
