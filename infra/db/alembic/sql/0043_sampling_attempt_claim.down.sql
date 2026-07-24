DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM workflow_c_sampling_attempts
        WHERE status = 'running'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade Sampling Attempt claim control while Attempts are running'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER workflow_c_provider_sampling_claimed ON durable_jobs;
REVOKE ALL ON FUNCTION geo_mark_workflow_c_provider_sampling_claimed()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_mark_workflow_c_provider_sampling_claimed();

CREATE OR REPLACE FUNCTION geo_require_workflow_c_sampling_job_fence(
    p_project_id uuid,
    p_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_spec_hash text,
    p_expected_kind text,
    p_run_id uuid,
    p_task_id uuid,
    p_attempt_id uuid,
    p_expected_task_version integer,
    p_expected_attempt_version integer
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE stored_spec workflow_c_job_specs%ROWTYPE;
DECLARE durable durable_jobs%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL OR p_lease_token IS NULL
       OR p_fencing_generation < 1 OR p_spec_hash !~ '^[0-9a-f]{64}$'
       OR p_expected_kind NOT IN ('sampling.provider_execute', 'sampling.manual_import')
       OR p_run_id IS NULL OR p_task_id IS NULL OR p_attempt_id IS NULL
       OR p_expected_task_version < 1 OR p_expected_attempt_version < 1 THEN
        RAISE EXCEPTION 'invalid or out-of-scope Workflow C Sampling worker fence'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO stored_spec
    FROM workflow_c_job_specs
    WHERE project_id = p_project_id AND job_id = p_job_id
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C Sampling Job spec does not exist'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO durable
    FROM durable_jobs
    WHERE project_id = p_project_id AND id = p_job_id
    FOR SHARE;
    IF NOT FOUND
       OR stored_spec.kind <> p_expected_kind OR durable.kind <> p_expected_kind
       OR stored_spec.spec_hash <> p_spec_hash OR durable.input_hash <> p_spec_hash
       OR durable.status <> 'running' OR durable.lease_token IS DISTINCT FROM p_lease_token
       OR durable.fencing_generation <> p_fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= clock_timestamp()
       OR durable.cancel_requested_at IS NOT NULL
       OR stored_spec.spec_payload->>'run_id' <> p_run_id::text
       OR stored_spec.spec_payload->>'task_id' <> p_task_id::text
       OR stored_spec.spec_payload->>'attempt_id' <> p_attempt_id::text
       OR (stored_spec.spec_payload->>'task_version')::integer <> p_expected_task_version
       OR (stored_spec.spec_payload->>'attempt_version')::integer <> p_expected_attempt_version THEN
        RAISE EXCEPTION 'Workflow C Sampling worker lease, spec, or version was fenced'
            USING ERRCODE = '40001';
    END IF;
    RETURN stored_spec.spec_payload;
END;
$$;
