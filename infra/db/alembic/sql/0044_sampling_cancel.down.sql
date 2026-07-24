DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM workflow_c_command_ledger
         WHERE command_scope IN ('sampling.attempt.cancel', 'sampling.run.cancel')
    ) THEN
        RAISE EXCEPTION 'cannot downgrade Sampling cancellation control after cancellation commands exist'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER workflow_c_provider_sampling_cancelled ON durable_jobs;
REVOKE ALL ON FUNCTION geo_mark_workflow_c_provider_sampling_cancelled()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_mark_workflow_c_provider_sampling_cancelled();

REVOKE ALL ON FUNCTION geo_cancel_workflow_c_sampling_attempt(
    uuid, uuid, integer, integer, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_cancel_workflow_c_sampling_attempt(
    uuid, uuid, integer, integer, text, text, timestamptz
);
REVOKE ALL ON FUNCTION geo_cancel_workflow_c_sampling_run(
    uuid, uuid, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_cancel_workflow_c_sampling_run(
    uuid, uuid, text, text, timestamptz
);
