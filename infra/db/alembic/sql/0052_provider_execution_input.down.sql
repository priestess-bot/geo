DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_sampling_provider_execution_inputs)
       OR EXISTS (
           SELECT 1 FROM workflow_c_command_ledger
            WHERE command_scope = 'sampling.provider_execution_input.register'
       ) THEN
        RAISE EXCEPTION 'cannot downgrade Provider execution input while data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER workflow_c_sampling_suite_bind_provider_execution_input
    ON workflow_c_sampling_suites;
DROP FUNCTION geo_bind_workflow_c_sampling_provider_execution_input();
REVOKE ALL ON FUNCTION geo_register_workflow_c_provider_execution_input(
    uuid, uuid, text, text, text, text, jsonb, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_register_workflow_c_provider_execution_input(
    uuid, uuid, text, text, text, text, jsonb, timestamptz
);
ALTER TABLE workflow_c_sampling_suites
    DROP CONSTRAINT workflow_c_sampling_suites_provider_execution_input_fkey,
    DROP CONSTRAINT workflow_c_sampling_suites_provider_execution_input_pair_check,
    DROP COLUMN provider_execution_input_hash,
    DROP COLUMN provider_execution_input_option_id;
DROP POLICY project_scope ON workflow_c_sampling_provider_execution_inputs;
DROP TABLE workflow_c_sampling_provider_execution_inputs;
