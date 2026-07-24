DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_sampling_suite_input_options)
       OR EXISTS (
           SELECT 1 FROM workflow_c_command_ledger
            WHERE command_scope IN ('sampling.suite_input.register', 'sampling.suite.create')
       ) THEN
        RAISE EXCEPTION 'cannot downgrade Sampling Suite control after Suite data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    geo_register_workflow_c_sampling_suite_input(
        uuid, uuid, text, text, text, text, jsonb, timestamptz
    ),
    geo_create_workflow_c_sampling_suite(
        uuid, uuid, text, text, uuid, text, text, jsonb, timestamptz
    ) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_register_workflow_c_sampling_suite_input(
    uuid, uuid, text, text, text, text, jsonb, timestamptz
);
DROP FUNCTION geo_create_workflow_c_sampling_suite(
    uuid, uuid, text, text, uuid, text, text, jsonb, timestamptz
);
DROP FUNCTION geo_jsonb_sampling_canonical_text(jsonb);

DROP POLICY project_scope ON workflow_c_sampling_suite_input_options;
DROP TABLE workflow_c_sampling_suite_input_options;

GRANT SELECT, INSERT ON workflow_c_sampling_suites TO geo_app;
