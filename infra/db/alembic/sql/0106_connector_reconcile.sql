-- Keep the Connector Run truth model aligned even when the shared dispatcher,
-- rather than the Connector operation, owns a retry or terminal transition.

CREATE FUNCTION geo_reconcile_connector_durable_status()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE run connector_sync_runs%ROWTYPE;
DECLARE failure_class text;
DECLARE safe_error_code text;
DECLARE action text;
BEGIN
    IF NEW.kind <> 'connector.sync'
       OR NEW.status NOT IN ('retry_wait', 'failed', 'dead_lettered', 'cancelled') THEN
        RETURN NEW;
    END IF;

    SELECT * INTO run
      FROM connector_sync_runs
     WHERE project_id = NEW.project_id AND durable_job_id = NEW.id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Connector Durable Job has no Sync Run aggregate'
            USING ERRCODE = '40001';
    END IF;
    IF run.status = 'succeeded' THEN
        RAISE EXCEPTION 'Connector terminal Durable Job conflicts with succeeded Run'
            USING ERRCODE = '40001';
    END IF;

    safe_error_code := CASE
        WHEN NEW.error_code ~ '^[a-z][a-z0-9_.:-]{0,99}$' THEN NEW.error_code
        ELSE 'connector_sync_failed'
    END;
    failure_class := CASE
        WHEN lower(COALESCE(NEW.error_detail->>'classification', '')) ~
             '(revoked|permission|forbidden)' THEN 'revoked'
        WHEN lower(COALESCE(NEW.error_detail->>'classification', '')) ~
             '(credential|authentication|unauthorized)' THEN 'auth'
        WHEN lower(COALESCE(NEW.error_detail->>'classification', '')) ~ '(quota)' THEN 'quota'
        WHEN lower(COALESCE(NEW.error_detail->>'classification', '')) ~
             '(rate|throttl)' THEN 'rate'
        WHEN lower(COALESCE(NEW.error_detail->>'classification', '')) ~ '(schema)' THEN 'schema'
        WHEN NEW.status = 'retry_wait' THEN 'transient'
        ELSE 'permanent'
    END;
    action := CASE failure_class
        WHEN 'auth' THEN 'Verify the active Secret version and re-authorize the source.'
        WHEN 'quota' THEN 'Restore source quota or narrow the requested sync window.'
        WHEN 'rate' THEN 'Retry after the source rate-limit window resets.'
        WHEN 'schema' THEN 'Review and approve the detected source schema change.'
        WHEN 'revoked' THEN 'Restore source authorization before starting a new sync.'
        WHEN 'transient' THEN 'The durable job will retry automatically; inspect it if retries exhaust.'
        ELSE 'Inspect the sanitized error and start a new sync after correcting the source.'
    END;

    IF NEW.status <> 'cancelled' THEN
        INSERT INTO connector_errors(
            id, project_id, sync_run_id, error_class, error_code,
            operator_action, retryable, sanitized_details, occurred_at
        ) VALUES (
            gen_random_uuid(), NEW.project_id, run.id, failure_class, safe_error_code,
            action, NEW.status = 'retry_wait',
            jsonb_build_object(
                'classification', COALESCE(NEW.error_detail->>'classification', 'unknown'),
                'durable_status', NEW.status,
                'attempt_count', NEW.attempt_count
            ),
            clock_timestamp()
        );
    END IF;

    IF NEW.status = 'retry_wait' THEN
        IF run.status NOT IN ('queued', 'running') THEN
            RAISE EXCEPTION 'Connector retry conflicts with terminal Sync Run'
                USING ERRCODE = '40001';
        END IF;
        RETURN NEW;
    END IF;

    IF run.status IN ('queued', 'running') THEN
        UPDATE connector_sync_runs
           SET status = CASE WHEN NEW.status = 'cancelled' THEN 'cancelled' ELSE 'failed' END,
               version = version + 1,
               finished_at = clock_timestamp(),
               error_class = CASE WHEN NEW.status = 'cancelled' THEN NULL ELSE failure_class END
         WHERE project_id = NEW.project_id AND id = run.id
           AND version = run.version AND status IN ('queued', 'running');
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Connector terminal Sync Run was fenced'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER connector_durable_status_reconcile
AFTER UPDATE OF status ON durable_jobs
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION geo_reconcile_connector_durable_status();

REVOKE ALL ON FUNCTION geo_reconcile_connector_durable_status()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
