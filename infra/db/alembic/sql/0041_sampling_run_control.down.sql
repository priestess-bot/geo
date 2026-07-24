DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_sampling_runs)
       OR EXISTS (
           SELECT 1 FROM workflow_c_command_ledger
            WHERE command_scope = 'sampling.run.create'
       ) THEN
        RAISE EXCEPTION 'cannot downgrade Sampling Run reservation control after Run data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION geo_create_workflow_c_sampling_run(
    uuid, uuid, text, text, uuid, text, text, text, text, text, text,
    timestamptz, timestamptz, jsonb, jsonb, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_create_workflow_c_sampling_run(
    uuid, uuid, text, text, uuid, text, text, text, text, text, text,
    timestamptz, timestamptz, jsonb, jsonb, timestamptz
);

DROP INDEX workflow_c_sampling_runs_policy_reservation_idx;
ALTER TABLE workflow_c_sampling_runs
    DROP CONSTRAINT workflow_c_sampling_runs_reservation_balance_check,
    DROP COLUMN released_task_count,
    DROP COLUMN consumed_task_count;

GRANT SELECT, INSERT ON workflow_c_sampling_runs, workflow_c_sampling_tasks TO geo_app;
