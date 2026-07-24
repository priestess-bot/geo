DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_sampling_attempts)
       OR EXISTS (
           SELECT 1 FROM workflow_c_command_ledger
            WHERE command_scope = 'sampling.provider_attempt.enqueue'
       ) THEN
        RAISE EXCEPTION 'cannot downgrade Sampling Attempt control after Attempt data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION geo_enqueue_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_enqueue_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz
);

GRANT SELECT, INSERT ON workflow_c_sampling_attempts TO geo_app;
