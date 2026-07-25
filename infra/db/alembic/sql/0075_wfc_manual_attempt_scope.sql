-- The Provider execution-input trigger introduced in 0053 ran for every
-- queued Sampling Attempt. Manual evidence approval creates its Attempt before
-- its manual Job spec in one SECURITY DEFINER transaction, so the Provider
-- trigger incorrectly rejected the valid manual path. Resolve the immutable
-- Suite first and apply Provider-only checks only to Provider capture methods.

CREATE OR REPLACE FUNCTION geo_verify_workflow_c_provider_execution_attempt()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE suite_row workflow_c_sampling_suites%ROWTYPE;
DECLARE execution_row workflow_c_sampling_provider_execution_inputs%ROWTYPE;
DECLARE spec jsonb;
DECLARE question_matches integer;
BEGIN
    IF NEW.status <> 'queued' THEN
        RETURN NEW;
    END IF;

    SELECT * INTO suite_row
      FROM workflow_c_sampling_suites
     WHERE project_id = NEW.project_id
       AND id = (
           SELECT suite_id
             FROM workflow_c_sampling_runs
            WHERE project_id = NEW.project_id AND id = NEW.run_id
       )
     FOR SHARE;
    IF suite_row.id IS NULL THEN
        RAISE EXCEPTION 'Sampling Attempt has no frozen Suite'
            USING ERRCODE = '23514';
    END IF;
    IF suite_row.capture_method NOT IN ('provider_api', 'proxy_grounded_api') THEN
        RETURN NEW;
    END IF;

    SELECT spec_payload INTO spec
      FROM workflow_c_job_specs
     WHERE project_id = NEW.project_id
       AND job_id = NEW.durable_job_id
       AND kind = 'sampling.provider_execute'
     FOR SHARE;
    IF spec IS NULL THEN
        RAISE EXCEPTION 'Provider Sampling Attempt has no frozen Job spec'
            USING ERRCODE = '23514';
    END IF;
    IF suite_row.provider_execution_input_option_id IS NULL
       OR suite_row.provider_execution_input_hash IS NULL THEN
        RAISE EXCEPTION 'Provider Sampling Attempt Suite has no frozen execution input'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO execution_row
      FROM workflow_c_sampling_provider_execution_inputs
     WHERE project_id = NEW.project_id
       AND suite_input_option_id = suite_row.provider_execution_input_option_id
       AND execution_input_hash = suite_row.provider_execution_input_hash
       AND status IN ('approved', 'retired')
     FOR SHARE;
    IF execution_row.project_id IS NULL
       OR spec->>'runtime_selection_id' <> execution_row.payload->>'runtime_selection_id'
       OR spec->'prompt' <> execution_row.payload->'prompt'
       OR spec->>'search_mode' <> suite_row.payload->'suite'->'source_stratum'->>'search_mode'
       OR spec->>'deadline_at' IS DISTINCT FROM execution_row.payload->>'deadline_at' THEN
        RAISE EXCEPTION 'Provider Sampling Attempt differs from its frozen execution input'
            USING ERRCODE = '23514';
    END IF;
    SELECT count(*) INTO question_matches
      FROM jsonb_array_elements(execution_row.payload->'questions') AS question(value)
     WHERE question.value->>'question_id' = (
               SELECT question_id FROM workflow_c_sampling_tasks
                WHERE project_id = NEW.project_id AND id = NEW.task_id
           )
       AND question.value->>'question_version' = (
               SELECT question_version FROM workflow_c_sampling_tasks
                WHERE project_id = NEW.project_id AND id = NEW.task_id
           )
       AND question.value->>'text_hash' = spec->'question'->>'sha256'
       AND question.value->>'text' = spec->'question'->>'text';
    IF question_matches <> 1 THEN
        RAISE EXCEPTION 'Provider Sampling Attempt question differs from frozen execution input'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION geo_verify_workflow_c_provider_execution_attempt()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

COMMENT ON FUNCTION geo_verify_workflow_c_provider_execution_attempt() IS
'Validates queued Provider Attempts against their frozen execution input; non-Provider capture methods use their own admission contracts.';

-- The original claim projection also selected only provider_execute Jobs.
-- Manual Jobs use the same Attempt/Task aggregates and fenced completion RPC,
-- so they must enter running under the same durable lease transition.
CREATE OR REPLACE FUNCTION geo_mark_workflow_c_provider_sampling_claimed()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
BEGIN
    IF NEW.kind NOT IN ('sampling.provider_execute', 'sampling.manual_import')
       OR NEW.status <> 'running' THEN
        RETURN NEW;
    END IF;

    SELECT * INTO attempt_row
      FROM workflow_c_sampling_attempts
     WHERE project_id = NEW.project_id AND durable_job_id = NEW.id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C Sampling durable Job has no Attempt aggregate'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO task_row
      FROM workflow_c_sampling_tasks
     WHERE project_id = NEW.project_id AND id = attempt_row.task_id
     FOR UPDATE;
    IF NOT FOUND OR task_row.run_id <> attempt_row.run_id
       OR (NEW.kind = 'sampling.manual_import' AND task_row.capture_method <> 'manual_ui')
       OR (
           NEW.kind = 'sampling.provider_execute'
           AND task_row.capture_method NOT IN ('provider_api', 'proxy_grounded_api')
       ) THEN
        RAISE EXCEPTION 'Workflow C Sampling Attempt has no matching Task aggregate'
            USING ERRCODE = '40001';
    END IF;

    IF attempt_row.status = 'running' AND task_row.status = 'running' THEN
        RETURN NEW;
    END IF;
    IF attempt_row.status <> 'queued'
       OR task_row.status NOT IN ('queued', 'retry_ready') THEN
        RAISE EXCEPTION 'Workflow C Sampling Attempt cannot enter running from its current state'
            USING ERRCODE = '40001';
    END IF;

    UPDATE workflow_c_sampling_attempts
       SET status = 'running', version = version + 1, updated_at = clock_timestamp()
     WHERE project_id = NEW.project_id AND id = attempt_row.id
       AND version = attempt_row.version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C Sampling Attempt claim version was fenced'
            USING ERRCODE = '40001';
    END IF;
    UPDATE workflow_c_sampling_tasks
       SET status = 'running', version = version + 1, updated_at = clock_timestamp()
     WHERE project_id = NEW.project_id AND id = task_row.id
       AND version = task_row.version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C Sampling Task claim version was fenced'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION geo_mark_workflow_c_provider_sampling_claimed()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

COMMENT ON FUNCTION geo_mark_workflow_c_provider_sampling_claimed() IS
'Projects a Provider or approved manual Sampling durable lease into its matching Attempt and Task aggregates.';
