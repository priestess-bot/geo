CREATE OR REPLACE FUNCTION geo_assert_workflow_c_job_spec_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Workflow C Job spec is immutable'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR SHARE;
    IF durable.kind <> NEW.kind OR durable.input_hash <> NEW.spec_hash
       OR durable.status <> 'queued' THEN
        RAISE EXCEPTION 'Workflow C Job spec does not match its queued Durable Job'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE EXECUTE ON FUNCTION geo_admit_workflow_c_metric_judge_batches(
    uuid, uuid, uuid, integer, text, jsonb
) FROM geo_worker;
DROP FUNCTION geo_admit_workflow_c_metric_judge_batches(
    uuid, uuid, uuid, integer, text, jsonb
);
