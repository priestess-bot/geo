-- Do not silently make independently encrypted lineage unrepresentable before
-- returning to the historical one-value constraint.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM workflow_c_manual_artifacts
         WHERE encryption_algorithm = 'AES-256-GCM/independent-DEK/v1'
            OR redaction_assurance IN (
                'automatic_structured_redaction',
                'operator_attested_pre_redacted_pending_dual_review'
            )
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: current Workflow C artifact lineage exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

ALTER TABLE workflow_c_manual_artifacts
    DROP CONSTRAINT workflow_c_manual_artifacts_encryption_algorithm_check;

ALTER TABLE workflow_c_manual_artifacts
    ADD CONSTRAINT workflow_c_manual_artifacts_encryption_algorithm_check
    CHECK (encryption_algorithm = 'AES-256-GCM');

ALTER TABLE workflow_c_manual_artifacts
    DROP CONSTRAINT workflow_c_manual_artifacts_redaction_assurance_check;

ALTER TABLE workflow_c_manual_artifacts
    ADD CONSTRAINT workflow_c_manual_artifacts_redaction_assurance_check
    CHECK (redaction_assurance IN ('automated_pass', 'human_verified'));

CREATE OR REPLACE FUNCTION geo_record_workflow_c_artifact_insert_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM geo_append_workflow_c_artifact_event(
        NEW.project_id, NEW.artifact_id, 'staged',
        'workflow_c.artifact_writer', 'encrypted_stage', NEW.created_at
    );
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION geo_activate_workflow_c_manual_artifact(uuid, uuid)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_activate_workflow_c_manual_artifact(uuid, uuid);
