-- 0052 keeps previously-created Provider Suites readable while adding their
-- execution binding.  New Provider Suites and every Provider Attempt must,
-- however, have one exact immutable binding.  Enforce this at both write
-- boundaries so a direct RPC caller cannot bypass the API composer.

CREATE FUNCTION geo_require_workflow_c_sampling_provider_execution_input()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF NEW.capture_method IN ('provider_api', 'proxy_grounded_api')
       AND (
            NEW.provider_execution_input_option_id IS NULL
            OR NEW.provider_execution_input_hash IS NULL
       ) THEN
        RAISE EXCEPTION 'Provider Sampling Suite has no frozen execution input'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

-- PostgreSQL runs same-timing row triggers alphabetically.  ``bind`` runs
-- before ``require``, allowing the 0052 binder to populate the immutable FK.
CREATE TRIGGER workflow_c_sampling_suite_require_provider_execution_input
BEFORE INSERT ON workflow_c_sampling_suites
FOR EACH ROW EXECUTE FUNCTION geo_require_workflow_c_sampling_provider_execution_input();

CREATE FUNCTION geo_verify_workflow_c_provider_execution_attempt()
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
    SELECT * INTO suite_row
      FROM workflow_c_sampling_suites
     WHERE project_id = NEW.project_id
       AND id = (
           SELECT suite_id
             FROM workflow_c_sampling_runs
            WHERE project_id = NEW.project_id AND id = NEW.run_id
       )
     FOR SHARE;
    IF suite_row.id IS NULL
       OR suite_row.capture_method NOT IN ('provider_api', 'proxy_grounded_api')
       OR suite_row.provider_execution_input_option_id IS NULL
       OR suite_row.provider_execution_input_hash IS NULL THEN
        RAISE EXCEPTION 'Provider Sampling Attempt Suite has no frozen execution input'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO execution_row
      FROM workflow_c_sampling_provider_execution_inputs
     WHERE project_id = NEW.project_id
       AND suite_input_option_id = suite_row.provider_execution_input_option_id
       AND execution_input_hash = suite_row.provider_execution_input_hash
       AND status = 'approved'
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

CREATE TRIGGER workflow_c_sampling_attempt_verify_provider_execution_input
BEFORE INSERT ON workflow_c_sampling_attempts
FOR EACH ROW EXECUTE FUNCTION geo_verify_workflow_c_provider_execution_attempt();

REVOKE ALL ON FUNCTION geo_require_workflow_c_sampling_provider_execution_input()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_verify_workflow_c_provider_execution_attempt()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
