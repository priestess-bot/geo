DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_sampling_manual_imports)
       OR EXISTS (
           SELECT 1 FROM workflow_c_command_ledger
            WHERE command_scope IN (
                'sampling.manual_import.submit', 'sampling.manual_import.review'
            )
       ) THEN
        RAISE EXCEPTION 'cannot downgrade Manual Sampling import control after evidence exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION geo_review_workflow_c_manual_sampling_evidence(
    uuid, uuid, text, text, integer, text, text, boolean, timestamptz, text, jsonb, text
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_review_workflow_c_manual_sampling_evidence(
    uuid, uuid, text, text, integer, text, text, boolean, timestamptz, text, jsonb, text
);

REVOKE ALL ON FUNCTION geo_submit_workflow_c_manual_sampling_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_submit_workflow_c_manual_sampling_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz
);

ALTER TABLE workflow_c_sampling_manual_imports
    DROP CONSTRAINT workflow_c_sampling_manual_imports_review_reason_check;
ALTER TABLE workflow_c_sampling_manual_imports
    DROP COLUMN review_reason;
ALTER TABLE workflow_c_sampling_manual_imports
    ADD CONSTRAINT workflow_c_sampling_manual_imports_attempt_id_project_id_fkey
    FOREIGN KEY (attempt_id, project_id)
    REFERENCES workflow_c_sampling_attempts(id, project_id) ON DELETE CASCADE;

GRANT INSERT ON workflow_c_sampling_manual_imports TO geo_app;
