-- A retired Provider execution input may not be selected for a new Suite.
-- Existing Suites retain their immutable foreign-key binding so they can be
-- reproduced and audited; their Attempt trigger still verifies every field
-- against the unchanged registry payload.  Retirement is therefore a
-- one-way, version-fenced lifecycle transition rather than a payload edit.

ALTER TABLE workflow_c_sampling_provider_execution_inputs
    ADD COLUMN aggregate_version integer NOT NULL DEFAULT 1 CHECK (aggregate_version > 0),
    ADD COLUMN retired_at timestamptz,
    ADD COLUMN retired_by text,
    ADD COLUMN retirement_reason text,
    ADD CONSTRAINT workflow_c_provider_execution_input_retirement_lifecycle_check
    CHECK (
        (status = 'approved'
         AND retired_at IS NULL
         AND retired_by IS NULL
         AND retirement_reason IS NULL)
        OR
        (status = 'retired'
         AND retired_at IS NOT NULL
         AND btrim(retired_by) <> ''
         AND retirement_reason IN (
             'authorization_expired',
             'configuration_error',
             'policy_withdrawn',
             'provider_decommissioned',
             'safety_review',
             'superseded'
         ))
    );

CREATE FUNCTION geo_retire_workflow_c_provider_execution_input(
    p_project_id uuid,
    p_suite_input_option_id uuid,
    p_execution_input_hash text,
    p_expected_version integer,
    p_actor_id text,
    p_reason text,
    p_idempotency_key_hash text,
    p_command_hash text,
    p_retired_at timestamptz
) RETURNS SETOF workflow_c_sampling_provider_execution_inputs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE execution_row workflow_c_sampling_provider_execution_inputs%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR p_suite_input_option_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Provider execution input is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_execution_input_hash IS NULL
       OR p_execution_input_hash !~ '^[0-9a-f]{64}$'
       OR p_expected_version IS NULL
       OR p_expected_version < 1
       OR p_idempotency_key_hash IS NULL
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_command_hash IS NULL
       OR p_command_hash !~ '^[0-9a-f]{64}$'
       OR p_retired_at IS NULL
       OR p_actor_id IS NULL
       OR btrim(p_actor_id) = ''
       OR char_length(p_actor_id) > 200
       OR p_reason IS NULL
       OR btrim(p_reason) = ''
       OR char_length(p_reason) > 64
       OR p_reason NOT IN (
           'authorization_expired',
           'configuration_error',
           'policy_withdrawn',
           'provider_decommissioned',
           'safety_review',
           'superseded'
       ) THEN
        RAISE EXCEPTION 'Provider execution input retirement command is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-provider-execution-input-retire:' || p_project_id::text || ':'
            || p_suite_input_option_id::text || ':' || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.provider_execution_input.retire'
       AND aggregate_id = p_suite_input_option_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_command_hash
           OR existing.result_id <> p_suite_input_option_id
           OR existing.result_type <> 'sampling_provider_execution_input'
           OR jsonb_typeof(existing.result_payload) <> 'object'
           OR existing.result_payload->>'schema_version' <> '1'
           OR existing.result_payload->>'execution_input_hash' <> p_execution_input_hash
           OR existing.result_payload->>'status' <> 'retired' THEN
            RAISE EXCEPTION 'Provider execution input retirement idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT * FROM workflow_c_sampling_provider_execution_inputs
         WHERE project_id = p_project_id
           AND suite_input_option_id = p_suite_input_option_id
           AND execution_input_hash = p_execution_input_hash
           AND status = 'retired';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Provider execution input retirement replay is missing durable result'
                USING ERRCODE = '40001';
        END IF;
        RETURN;
    END IF;

    SELECT * INTO execution_row
      FROM workflow_c_sampling_provider_execution_inputs
     WHERE project_id = p_project_id
       AND suite_input_option_id = p_suite_input_option_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Provider execution input does not exist'
            USING ERRCODE = 'P0002';
    END IF;
    IF execution_row.execution_input_hash <> p_execution_input_hash THEN
        RAISE EXCEPTION 'Provider execution input hash is stale'
            USING ERRCODE = '40001';
    END IF;
    IF execution_row.aggregate_version <> p_expected_version THEN
        RAISE EXCEPTION 'Provider execution input version is stale'
            USING ERRCODE = '40001';
    END IF;
    IF execution_row.status <> 'approved' THEN
        RAISE EXCEPTION 'Provider execution input is already retired'
            USING ERRCODE = '23514';
    END IF;

    UPDATE workflow_c_sampling_provider_execution_inputs
       SET status = 'retired',
           aggregate_version = aggregate_version + 1,
           retired_at = p_retired_at,
           retired_by = btrim(p_actor_id),
           retirement_reason = btrim(p_reason)
     WHERE project_id = p_project_id
       AND suite_input_option_id = p_suite_input_option_id
       AND execution_input_hash = p_execution_input_hash
       AND aggregate_version = p_expected_version
       AND status = 'approved'
     RETURNING * INTO execution_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Provider execution input retirement changed concurrently'
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.provider_execution_input.retire', p_suite_input_option_id,
        p_idempotency_key_hash, p_command_hash, 'sampling_provider_execution_input',
        p_suite_input_option_id, execution_row.aggregate_version,
        jsonb_build_object(
            'schema_version', 1,
            'suite_input_option_id', p_suite_input_option_id,
            'execution_input_hash', p_execution_input_hash,
            'status', 'retired',
            'aggregate_version', execution_row.aggregate_version
        ),
        p_retired_at
    );
    RETURN QUERY
    SELECT * FROM workflow_c_sampling_provider_execution_inputs
     WHERE project_id = p_project_id
       AND suite_input_option_id = p_suite_input_option_id
       AND execution_input_hash = p_execution_input_hash;
END;
$$;

-- A retired input remains valid only for a Suite which already has its exact
-- immutable FK binding.  New Suite binding stays restricted to `approved` in
-- the 0052 binder, so retirement never admits a new consumer.
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

REVOKE ALL ON FUNCTION geo_retire_workflow_c_provider_execution_input(
    uuid, uuid, text, integer, text, text, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_retire_workflow_c_provider_execution_input(
    uuid, uuid, text, integer, text, text, text, text, timestamptz
) TO geo_app;

COMMENT ON FUNCTION geo_retire_workflow_c_provider_execution_input(
    uuid, uuid, text, integer, text, text, text, text, timestamptz
) IS 'One-way optimistic retirement. Existing frozen Suites remain verifiable; the Suite binder admits only approved inputs.';
