-- Restore the pre-0049 scheduler implementation on rollback.
CREATE OR REPLACE FUNCTION geo_enqueue_synthetic_artifact_maintenance(
    p_now timestamptz
) RETURNS TABLE (project_id uuid, job_id uuid, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate record;
DECLARE active_job durable_jobs%ROWTYPE;
DECLARE scheduled_id uuid;
DECLARE input_hash text;
BEGIN
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'Synthetic artifact maintenance time is required'
            USING ERRCODE = '22023';
    END IF;
    FOR candidate IN
        SELECT DISTINCT artifact.project_id
        FROM synthetic_lab_raw_artifacts AS artifact
        WHERE (artifact.lifecycle_state IN ('winning', 'orphaned')
               AND artifact.expires_at IS NOT NULL AND artifact.expires_at <= p_now)
           OR artifact.lifecycle_state IN ('deletion_pending', 'object_delete_pending')
    LOOP
        SELECT * INTO active_job FROM durable_jobs AS existing_job
        WHERE existing_job.project_id = candidate.project_id
          AND existing_job.kind = 'synthetic_lab.artifact_maintenance'
          AND existing_job.idempotency_key = 'synthetic-artifact-maintenance:v1'
          AND existing_job.status IN ('queued', 'running', 'finalizing', 'retry_wait')
        ORDER BY existing_job.created_at DESC LIMIT 1 FOR UPDATE;
        IF FOUND THEN
            IF active_job.status IN ('queued', 'retry_wait') THEN
                UPDATE durable_jobs AS wake_job
                SET next_run_at = LEAST(wake_job.next_run_at, p_now),
                    updated_at = p_now
                WHERE wake_job.id = active_job.id;
                INSERT INTO broker_outbox(
                    id, project_id, job_id, topic, payload, idempotency_key, available_at
                ) VALUES (
                    gen_random_uuid(), candidate.project_id, active_job.id,
                    'synthetic_lab.artifact_maintenance',
                    jsonb_build_object('job_id', active_job.id::text,
                        'project_id', candidate.project_id::text),
                    'synthetic-artifact-maintenance:wake:' || active_job.id::text,
                    p_now
                ) ON CONFLICT ON CONSTRAINT broker_outbox_project_id_idempotency_key_key
                    DO NOTHING;
            END IF;
            project_id := candidate.project_id;
            job_id := active_job.id;
            replayed := true;
            RETURN NEXT;
            CONTINUE;
        END IF;
        input_hash := encode(digest(convert_to(
            'synthetic_lab.artifact_maintenance:v1:' || candidate.project_id::text,
            'UTF8'), 'sha256'), 'hex');
        scheduled_id := gen_random_uuid();
        INSERT INTO durable_jobs(
            id, project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, replay_nonce, created_at, updated_at
        ) VALUES (
            scheduled_id, candidate.project_id, 'synthetic_lab.artifact_maintenance',
            'queued', 5, input_hash, 'synthetic-artifact-maintenance:v1', 10, p_now,
            coalesce((SELECT max(prior_job.replay_nonce) + 1 FROM durable_jobs AS prior_job
                      WHERE prior_job.project_id = candidate.project_id
                        AND prior_job.kind = 'synthetic_lab.artifact_maintenance'
                        AND prior_job.idempotency_key = 'synthetic-artifact-maintenance:v1'), 0),
            p_now, p_now
        );
        INSERT INTO broker_outbox(
            id, project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            gen_random_uuid(), candidate.project_id, scheduled_id,
            'synthetic_lab.artifact_maintenance',
            jsonb_build_object('job_id', scheduled_id::text,
                'project_id', candidate.project_id::text),
            'synthetic-artifact-maintenance:wake:' || scheduled_id::text, p_now
        );
        project_id := candidate.project_id;
        job_id := scheduled_id;
        replayed := false;
        RETURN NEXT;
    END LOOP;
END;
$$;
