-- Restore the pre-0063 RPC definition and writer boundary.
REVOKE EXECUTE ON FUNCTION geo_enqueue_workflow_c_artifact_write_failure(uuid, uuid)
FROM geo_app;

CREATE OR REPLACE FUNCTION geo_enqueue_workflow_c_artifact_write_failure(
    p_project_id uuid,
    p_artifact_id uuid
) RETURNS TABLE (artifact_id uuid, queue_id uuid, status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE queued workflow_c_artifact_deletion_queue%ROWTYPE;
DECLARE queued_at timestamptz := clock_timestamp();
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Workflow C artifact is outside caller Project scope'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO STRICT artifact FROM workflow_c_manual_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id FOR UPDATE;
    SELECT * INTO queued FROM workflow_c_artifact_deletion_queue
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id;
    IF NOT FOUND THEN
        IF artifact.status <> 'staged' THEN
            RAISE EXCEPTION 'Workflow C write failure target is not staged'
                USING ERRCODE = '23514';
        END IF;
        UPDATE workflow_c_manual_artifacts SET status = 'delete_pending'
        WHERE project_id = p_project_id AND artifact_id = p_artifact_id;
        INSERT INTO workflow_c_artifact_deletion_queue(
            id, project_id, artifact_id, key_ref, payload_uri, payload_hash,
            manifest_uri, manifest_hash, reason, status, next_attempt_at, created_at
        ) VALUES (
            gen_random_uuid(), p_project_id, p_artifact_id, artifact.key_ref,
            artifact.object_uri, artifact.object_hash, artifact.manifest_uri,
            artifact.manifest_hash, 'write_failed', 'pending', queued_at, queued_at
        ) RETURNING * INTO queued;
        PERFORM geo_append_workflow_c_artifact_event(
            p_project_id, p_artifact_id, 'delete_enqueued',
            'workflow_c.artifact_writer', 'write_failed', queued_at
        );
    END IF;
    PERFORM 1 FROM geo_schedule_workflow_c_artifact_maintenance(p_project_id, queued_at);
    RETURN QUERY SELECT p_artifact_id, queued.id, queued.status;
END;
$$;
