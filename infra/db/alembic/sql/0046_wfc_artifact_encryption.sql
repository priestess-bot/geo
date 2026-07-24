-- The payload envelope has always been an independently generated AES-256-GCM
-- DEK.  Preserve the legacy generic label while allowing the explicit v1
-- envelope identity emitted by the governed writer and recorded in its manifest.
ALTER TABLE workflow_c_manual_artifacts
    DROP CONSTRAINT workflow_c_manual_artifacts_encryption_algorithm_check;

ALTER TABLE workflow_c_manual_artifacts
    ADD CONSTRAINT workflow_c_manual_artifacts_encryption_algorithm_check
    CHECK (encryption_algorithm IN (
        'AES-256-GCM',
        'AES-256-GCM/independent-DEK/v1'
    ));

-- Preserve historical labels while accepting the two explicit governance
-- assurances emitted by the current structured and screenshot paths.
ALTER TABLE workflow_c_manual_artifacts
    DROP CONSTRAINT workflow_c_manual_artifacts_redaction_assurance_check;

ALTER TABLE workflow_c_manual_artifacts
    ADD CONSTRAINT workflow_c_manual_artifacts_redaction_assurance_check
    CHECK (redaction_assurance IN (
        'automated_pass',
        'human_verified',
        'automatic_structured_redaction',
        'operator_attested_pre_redacted_pending_dual_review'
    ));

-- The App role may stage an artifact but must not invoke the audit helper
-- directly.  The insert trigger is the constrained authority: it receives only
-- the inserted row and appends the immutable staged event under its owner.
CREATE OR REPLACE FUNCTION geo_record_workflow_c_artifact_insert_event() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    PERFORM geo_append_workflow_c_artifact_event(
        NEW.project_id, NEW.artifact_id, 'staged',
        'workflow_c.artifact_writer', 'encrypted_stage', NEW.created_at
    );
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_activate_workflow_c_manual_artifact(
    p_project_id uuid,
    p_artifact_id uuid
) RETURNS TABLE (artifact_id uuid, status text, activated_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
BEGIN
    IF p_project_id IS NULL OR p_artifact_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Workflow C manual artifact activation is outside caller Project scope'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO STRICT artifact
      FROM workflow_c_manual_artifacts AS current_artifact
     WHERE current_artifact.project_id = p_project_id
       AND current_artifact.artifact_id = p_artifact_id
     FOR UPDATE;
    IF artifact.status = 'active' THEN
        RETURN QUERY SELECT artifact.artifact_id, artifact.status, artifact.activated_at;
        RETURN;
    END IF;
    IF artifact.status <> 'staged' OR artifact.expires_at <= clock_timestamp()
       OR artifact.key_ref IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM workflow_c_artifact_deks AS dek
            WHERE dek.project_id = artifact.project_id
              AND dek.artifact_id = artifact.artifact_id
              AND dek.key_ref = artifact.key_ref AND dek.status = 'active'
       ) THEN
        RAISE EXCEPTION 'Workflow C manual artifact stage cannot be activated'
            USING ERRCODE = '23514';
    END IF;
    UPDATE workflow_c_manual_artifacts AS current_artifact
       SET status = 'active', activated_at = clock_timestamp()
     WHERE current_artifact.project_id = artifact.project_id
       AND current_artifact.artifact_id = artifact.artifact_id;
    SELECT * INTO STRICT artifact
      FROM workflow_c_manual_artifacts AS current_artifact
     WHERE current_artifact.project_id = p_project_id
       AND current_artifact.artifact_id = p_artifact_id;
    RETURN QUERY SELECT artifact.artifact_id, artifact.status, artifact.activated_at;
END;
$$;

REVOKE ALL ON FUNCTION geo_activate_workflow_c_manual_artifact(uuid, uuid)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_activate_workflow_c_manual_artifact(uuid, uuid) TO geo_app;
