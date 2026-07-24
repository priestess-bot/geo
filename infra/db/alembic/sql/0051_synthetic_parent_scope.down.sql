CREATE OR REPLACE FUNCTION geo_block_synthetic_unstarted_model_call_children(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_reason_code text
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE blocked_count integer;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Synthetic child cancellation Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_reason_code !~ '^[a-z][a-z0-9_.:-]{0,99}$' THEN
        RAISE EXCEPTION 'Synthetic child cancellation reason is invalid'
            USING ERRCODE = '22023';
    END IF;
    WITH cancelled AS (
        UPDATE durable_jobs AS child
        SET status = 'cancelled',
            cancel_requested_at = coalesce(child.cancel_requested_at, clock_timestamp()),
            error_code = 'synthetic_parent_blocked',
            error_detail = jsonb_build_object(
                'parent_job_id', p_parent_job_id::text,
                'reason_code', p_reason_code
            ),
            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
            heartbeat_at = NULL, completed_at = clock_timestamp(),
            updated_at = clock_timestamp()
        FROM synthetic_lab_model_call_children AS link
        WHERE link.project_id = p_project_id
          AND link.parent_job_id = p_parent_job_id
          AND child.id = link.child_job_id
          AND child.project_id = link.project_id
          AND child.attempt_count = 0
          AND child.status IN ('queued', 'retry_wait')
        RETURNING child.id, child.project_id, child.fencing_generation
    ), logged AS (
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details
        )
        SELECT cancelled.project_id, cancelled.id, 'job_cancelled',
               'synthetic-parent-guard', cancelled.fencing_generation,
               jsonb_build_object(
                   'parent_job_id', p_parent_job_id::text,
                   'reason_code', p_reason_code,
                   'unstarted', true
               )
        FROM cancelled
        RETURNING id
    )
    SELECT count(*)::integer INTO blocked_count FROM logged;
    RETURN blocked_count;
END;
$$;
