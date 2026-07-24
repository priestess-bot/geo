-- An absent active Job cannot be row-locked. Serialize lookup/create/wake by
-- Project so concurrent periodic seeders cannot allocate duplicate first Jobs.
CREATE OR REPLACE FUNCTION geo_schedule_workflow_c_artifact_maintenance(
    p_project_id uuid,
    p_now timestamptz
) RETURNS TABLE (job_id uuid, outbox_id uuid, inserted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE active_job durable_jobs%ROWTYPE;
DECLARE scheduled_job_id uuid;
DECLARE scheduled_outbox_id uuid;
DECLARE input_hash text;
BEGIN
    IF p_project_id IS NULL OR p_now IS NULL THEN
        RAISE EXCEPTION 'Workflow C artifact maintenance schedule input is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-artifact-maintenance:' || p_project_id::text, 0
    ));
    SELECT * INTO active_job
    FROM durable_jobs
    WHERE project_id = p_project_id AND kind = 'workflow_c.artifact_maintenance'
      AND idempotency_key = 'workflow-c-artifact-maintenance:v1'
      AND status IN ('queued', 'running', 'finalizing', 'retry_wait')
    ORDER BY created_at DESC LIMIT 1 FOR UPDATE;
    IF FOUND THEN
        IF active_job.status IN ('queued', 'retry_wait') THEN
            UPDATE durable_jobs
            SET next_run_at = LEAST(next_run_at, p_now), updated_at = p_now
            WHERE id = active_job.id AND project_id = p_project_id;
        END IF;
        INSERT INTO broker_outbox(
            id, project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            gen_random_uuid(), p_project_id, active_job.id,
            'workflow_c.artifact_maintenance',
            jsonb_build_object('job_id', active_job.id::text,
                'project_id', p_project_id::text),
            'workflow-c-artifact-maintenance:wake:' || active_job.id::text, p_now
        ) ON CONFLICT (project_id, idempotency_key) DO NOTHING
        RETURNING id INTO scheduled_outbox_id;
        IF scheduled_outbox_id IS NULL THEN
            SELECT id INTO scheduled_outbox_id FROM broker_outbox
            WHERE project_id = p_project_id
              AND idempotency_key = 'workflow-c-artifact-maintenance:wake:'
                    || active_job.id::text;
        END IF;
        RETURN QUERY SELECT active_job.id, scheduled_outbox_id, false;
        RETURN;
    END IF;
    scheduled_job_id := gen_random_uuid();
    input_hash := encode(digest(convert_to(
        'workflow_c.artifact_maintenance:v1:' || p_project_id::text,
        'UTF8'), 'sha256'), 'hex');
    INSERT INTO durable_jobs(
        id, project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, replay_nonce, created_at, updated_at
    ) VALUES (
        scheduled_job_id, p_project_id, 'workflow_c.artifact_maintenance',
        'queued', 5, input_hash, 'workflow-c-artifact-maintenance:v1', 10, p_now,
        coalesce((SELECT max(replay_nonce) + 1 FROM durable_jobs
                  WHERE project_id = p_project_id
                    AND kind = 'workflow_c.artifact_maintenance'
                    AND idempotency_key = 'workflow-c-artifact-maintenance:v1'), 0),
        p_now, p_now
    );
    INSERT INTO broker_outbox(
        id, project_id, job_id, topic, payload, idempotency_key, available_at
    ) VALUES (
        gen_random_uuid(), p_project_id, scheduled_job_id,
        'workflow_c.artifact_maintenance',
        jsonb_build_object('job_id', scheduled_job_id::text,
            'project_id', p_project_id::text),
        'workflow-c-artifact-maintenance:wake:' || scheduled_job_id::text, p_now
    ) RETURNING id INTO scheduled_outbox_id;
    RETURN QUERY SELECT scheduled_job_id, scheduled_outbox_id, true;
END;
$$;
