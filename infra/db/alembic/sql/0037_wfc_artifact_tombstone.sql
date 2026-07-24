-- ``status`` is an output-column variable of this RETURNS TABLE function.
-- Qualify the artifact column so a successful remote delete can always append
-- its fenced tombstone instead of failing with PL/pgSQL ambiguity.
CREATE OR REPLACE FUNCTION geo_record_workflow_c_artifact_deletion_attempt(
    p_queue_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_object_deleted boolean,
    p_key_destroyed boolean,
    p_error_code text,
    p_attempted_at timestamptz,
    p_retry_not_before timestamptz
) RETURNS TABLE (queue_id uuid, status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE queued workflow_c_artifact_deletion_queue%ROWTYPE;
DECLARE next_status text;
BEGIN
    SELECT * INTO STRICT queued
    FROM workflow_c_artifact_deletion_queue
    WHERE id = p_queue_id
    FOR UPDATE;
    IF queued.status IN ('completed', 'retry_wait')
       AND queued.fencing_generation = p_fencing_generation
       AND queued.object_deleted = p_object_deleted
       AND queued.key_destroyed = p_key_destroyed
       AND queued.last_error_code IS NOT DISTINCT FROM p_error_code
       AND (
           (queued.status = 'completed' AND p_retry_not_before IS NULL)
           OR (queued.status = 'retry_wait'
               AND queued.next_attempt_at IS NOT DISTINCT FROM p_retry_not_before)
       ) THEN
        RETURN QUERY SELECT queued.id, queued.status;
        RETURN;
    END IF;
    IF queued.status <> 'running'
       OR queued.lease_token IS DISTINCT FROM p_lease_token
       OR queued.fencing_generation <> p_fencing_generation
       OR queued.lease_expires_at IS NULL
       OR queued.lease_expires_at <= p_attempted_at THEN
        RAISE EXCEPTION 'Workflow C artifact deletion lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF NOT queued.key_destroyed OR NOT p_key_destroyed
       OR (queued.object_deleted AND NOT p_object_deleted) THEN
        RAISE EXCEPTION 'Workflow C artifact deletion evidence cannot regress'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM workflow_c_artifact_deks AS dek
        WHERE dek.project_id = queued.project_id
          AND dek.key_ref = queued.key_ref AND dek.status = 'destroyed'
    ) THEN
        RAISE EXCEPTION 'Workflow C artifact cannot claim crypto-erasure before DEK destruction'
            USING ERRCODE = '23514';
    END IF;
    next_status := CASE WHEN p_object_deleted AND p_key_destroyed
        THEN 'completed' ELSE 'retry_wait' END;
    IF (next_status = 'completed' AND (
            p_error_code IS NOT NULL OR p_retry_not_before IS NOT NULL))
       OR (next_status = 'retry_wait' AND (
            btrim(coalesce(p_error_code, '')) = ''
            OR p_retry_not_before IS NULL
            OR p_retry_not_before <= p_attempted_at)) THEN
        RAISE EXCEPTION 'Workflow C artifact deletion outcome is incomplete'
            USING ERRCODE = '22023';
    END IF;
    IF next_status = 'completed' THEN
        UPDATE workflow_c_manual_artifacts AS artifact
        SET status = 'tombstoned', object_uri = NULL, manifest_uri = NULL,
            key_ref = NULL, tombstoned_at = p_attempted_at,
            tombstone_reason = queued.reason
        WHERE artifact.project_id = queued.project_id
          AND artifact.artifact_id = queued.artifact_id
          AND artifact.status = 'crypto_erased';
    END IF;
    UPDATE workflow_c_artifact_deletion_queue AS item
    SET status = next_status, lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, object_deleted = p_object_deleted,
        key_destroyed = p_key_destroyed, last_error_code = p_error_code,
        next_attempt_at = coalesce(p_retry_not_before, p_attempted_at),
        completed_at = CASE WHEN next_status = 'completed'
            THEN p_attempted_at ELSE NULL END
    WHERE item.id = p_queue_id
    RETURNING item.* INTO queued;
    PERFORM geo_append_workflow_c_artifact_event(
        queued.project_id, queued.artifact_id,
        CASE WHEN next_status = 'completed' THEN 'deleted' ELSE 'deletion_retry' END,
        coalesce(queued.lease_owner, 'workflow_c.artifact_maintenance'),
        coalesce(p_error_code, queued.reason), p_attempted_at
    );
    RETURN QUERY SELECT queued.id, queued.status;
END;
$$;
