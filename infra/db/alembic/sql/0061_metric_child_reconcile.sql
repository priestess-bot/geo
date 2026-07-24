-- Metric child Workers normally terminalize their aggregate and Durable Job in
-- one fenced transaction.  This reconciliation trigger covers the exceptional
-- path in which the shared dispatcher retries, dead-letters, or cancels a Job
-- after a handler has lost its opportunity to use the Worker-only child RPC.

CREATE FUNCTION geo_reconcile_workflow_c_metric_child_durable_status()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE child workflow_c_metric_model_children%ROWTYPE;
DECLARE batch workflow_c_metric_judge_batches%ROWTYPE;
DECLARE safe_error_code text;
DECLARE child_terminal_status text;
BEGIN
    IF NEW.kind NOT IN ('workflow_c.metric_judge', 'workflow_c.metric_arbiter')
       OR NEW.status NOT IN ('retry_wait', 'failed', 'dead_lettered', 'cancelled') THEN
        RETURN NEW;
    END IF;

    SELECT * INTO child
      FROM workflow_c_metric_model_children
     WHERE project_id = NEW.project_id AND child_job_id = NEW.id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Metric Durable Job has no child aggregate'
            USING ERRCODE = '40001';
    END IF;
    IF (NEW.kind = 'workflow_c.metric_judge' AND child.role <> 'metric_judge')
       OR (NEW.kind = 'workflow_c.metric_arbiter' AND child.role <> 'arbiter') THEN
        RAISE EXCEPTION 'Metric Durable Job kind differs from child role'
            USING ERRCODE = '40001';
    END IF;

    -- Every terminal transition of a batch, including nested sibling
    -- cancellations below, serializes on one stable Project/batch key.
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-metric-batch:' || NEW.project_id::text || ':' || child.batch_id::text,
        0
    ));
    SELECT * INTO batch
      FROM workflow_c_metric_judge_batches
     WHERE project_id = NEW.project_id AND id = child.batch_id
     FOR UPDATE;
    IF NOT FOUND OR batch.parent_job_id <> child.parent_job_id
       OR batch.parent_input_hash <> child.parent_input_hash THEN
        RAISE EXCEPTION 'Metric Durable Job child lineage is invalid'
            USING ERRCODE = '40001';
    END IF;

    safe_error_code := CASE
        WHEN NEW.status = 'cancelled' THEN 'cancelled'
        WHEN NEW.error_code ~ '^[a-z][a-z0-9_.:-]{0,99}$' THEN NEW.error_code
        ELSE 'worker_unhandled'
    END;

    IF NEW.status = 'retry_wait' THEN
        -- The normal retry path may already have moved the child back to
        -- queued.  Repair only the exceptional state where it remains running.
        IF child.status = 'running' THEN
            UPDATE workflow_c_metric_model_children
               SET status = 'queued', error_code = safe_error_code
             WHERE project_id = NEW.project_id AND child_job_id = NEW.id
               AND status = 'running';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Metric retry child was fenced'
                    USING ERRCODE = '40001';
            END IF;
        ELSIF child.status NOT IN ('queued', 'running') THEN
            RAISE EXCEPTION 'Metric retry Durable Job conflicts with terminal child'
                USING ERRCODE = '40001';
        END IF;
        IF batch.status NOT IN ('queued', 'running') THEN
            RAISE EXCEPTION 'Metric retry Durable Job has terminal batch'
                USING ERRCODE = '40001';
        END IF;
        RETURN NEW;
    END IF;

    IF child.status = 'succeeded' THEN
        RAISE EXCEPTION 'Metric terminal Durable Job conflicts with succeeded child'
            USING ERRCODE = '40001';
    END IF;
    child_terminal_status := CASE
        WHEN NEW.status = 'cancelled' THEN 'cancelled'
        ELSE 'failed'
    END;
    IF child.status IN ('queued', 'running') THEN
        UPDATE workflow_c_metric_model_children
           SET status = child_terminal_status,
               error_code = CASE WHEN child_terminal_status = 'failed'
                                 THEN safe_error_code ELSE 'cancelled' END,
               completed_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND child_job_id = NEW.id
           AND status IN ('queued', 'running');
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Metric terminal child was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;

    -- A single non-successful child makes its frozen batch unusable.  Preserve
    -- an earlier failure when a later sibling is merely cancelled as cleanup.
    IF batch.status IN ('queued', 'running') THEN
        UPDATE workflow_c_metric_judge_batches
           SET status = child_terminal_status,
               aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1,
               completed_at = clock_timestamp()
         WHERE project_id = NEW.project_id AND id = batch.id
           AND status IN ('queued', 'running');
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Metric terminal batch was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;

    -- Queued siblings cannot perform a paid call after the batch is terminal.
    -- Their own status trigger marks their child rows cancelled.  Running
    -- siblings receive a cooperative cancellation request and are finalized by
    -- the shared Worker through the same trigger.
    WITH cancelled AS (
        UPDATE durable_jobs AS sibling_job
           SET status = 'cancelled', error_code = 'cancelled',
               cancel_requested_at = coalesce(sibling_job.cancel_requested_at, clock_timestamp()),
               lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
               heartbeat_at = NULL, completed_at = clock_timestamp(), updated_at = clock_timestamp()
          FROM workflow_c_metric_model_children AS sibling_child
         WHERE sibling_child.project_id = NEW.project_id
           AND sibling_child.batch_id = child.batch_id
           AND sibling_child.child_job_id <> NEW.id
           AND sibling_job.project_id = sibling_child.project_id
           AND sibling_job.id = sibling_child.child_job_id
           AND sibling_job.status IN ('queued', 'retry_wait')
        RETURNING sibling_job.project_id, sibling_job.id, sibling_job.fencing_generation
    )
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    )
    SELECT project_id, id, 'job_cancelled', 'workflow-c-metric-reconcile', fencing_generation,
           jsonb_build_object('batch_id', child.batch_id::text, 'cause_job_id', NEW.id::text),
           clock_timestamp()
      FROM cancelled;

    UPDATE durable_jobs AS sibling_job
       SET cancel_requested_at = coalesce(sibling_job.cancel_requested_at, clock_timestamp()),
           updated_at = clock_timestamp()
      FROM workflow_c_metric_model_children AS sibling_child
     WHERE sibling_child.project_id = NEW.project_id
       AND sibling_child.batch_id = child.batch_id
       AND sibling_child.child_job_id <> NEW.id
       AND sibling_job.project_id = sibling_child.project_id
       AND sibling_job.id = sibling_child.child_job_id
       AND sibling_job.status IN ('running', 'finalizing');
    RETURN NEW;
END;
$$;

CREATE TRIGGER workflow_c_metric_child_durable_status
AFTER UPDATE OF status ON durable_jobs
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION geo_reconcile_workflow_c_metric_child_durable_status();

REVOKE ALL ON FUNCTION geo_reconcile_workflow_c_metric_child_durable_status()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
