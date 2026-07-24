-- A Sampling Run reserves its immutable denominator before any external work
-- exists.  Consumption and release are deliberately separate fields: only an
-- Attempt creation can consume a reservation, and cancellation can release
-- only the remainder.  This migration owns the Run/Task creation boundary.

ALTER TABLE workflow_c_sampling_runs
    ADD COLUMN consumed_task_count integer NOT NULL DEFAULT 0
        CHECK (consumed_task_count >= 0),
    ADD COLUMN released_task_count integer NOT NULL DEFAULT 0
        CHECK (released_task_count >= 0),
    ADD CONSTRAINT workflow_c_sampling_runs_reservation_balance_check
        CHECK (consumed_task_count + released_task_count <= reserved_task_count);

CREATE INDEX workflow_c_sampling_runs_policy_reservation_idx
    ON workflow_c_sampling_runs(project_id, admission_policy_id)
    WHERE reserved_task_count > 0;

CREATE FUNCTION geo_create_workflow_c_sampling_run(
    p_project_id uuid,
    p_run_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_suite_id uuid,
    p_suite_hash text,
    p_admission_policy_hash text,
    p_admission_grant_hash text,
    p_purpose text,
    p_authorization_reference text,
    p_admission_policy_version text,
    p_admitted_not_before timestamptz,
    p_authorization_valid_until timestamptz,
    p_run_payload jsonb,
    p_tasks_payload jsonb,
    p_created_at timestamptz
) RETURNS SETOF workflow_c_sampling_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE suite_row workflow_c_sampling_suites%ROWTYPE;
DECLARE policy workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE task_value jsonb;
DECLARE suite_value jsonb;
DECLARE expected_count integer;
DECLARE task_count integer;
DECLARE active_reservation integer;
DECLARE usage_start timestamptz;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Sampling Run is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_run_id IS NULL OR p_suite_id IS NULL
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_suite_hash !~ '^[0-9a-f]{64}$'
       OR p_admission_policy_hash !~ '^[0-9a-f]{64}$'
       OR p_admission_grant_hash !~ '^[0-9a-f]{64}$'
       OR btrim(coalesce(p_purpose, '')) = ''
       OR btrim(coalesce(p_authorization_reference, '')) = ''
       OR btrim(coalesce(p_admission_policy_version, '')) = ''
       OR p_admitted_not_before IS NULL
       OR p_authorization_valid_until IS NULL
       OR p_created_at IS NULL
       OR jsonb_typeof(p_run_payload) <> 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(p_run_payload)) <> 4
       OR p_run_payload->'schema_version' <> '1'::jsonb
       OR jsonb_typeof(p_run_payload->'planned_task_keys') <> 'array'
       OR p_run_payload->>'authorization_reference' <> p_authorization_reference
       OR p_run_payload->>'admission_policy_version' <> p_admission_policy_version
       OR jsonb_typeof(p_tasks_payload) <> 'array'
       OR jsonb_array_length(p_tasks_payload) = 0 THEN
        RAISE EXCEPTION 'Sampling Run create command is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-sampling-run:' || p_project_id::text || ':'
            || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.run.create'
       AND aggregate_id = p_run_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_run_id THEN
            RAISE EXCEPTION 'Sampling Run idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT * FROM workflow_c_sampling_runs
         WHERE project_id = p_project_id AND id = p_run_id;
        RETURN;
    END IF;

    SELECT * INTO suite_row
      FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id
       AND id = p_suite_id
       AND suite_hash = p_suite_hash
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling Run references an unknown frozen Suite'
            USING ERRCODE = '23514';
    END IF;
    IF jsonb_typeof(suite_row.payload) <> 'object'
       OR suite_row.payload->'schema_version' <> '1'::jsonb
       OR jsonb_typeof(suite_row.payload->'suite') <> 'object' THEN
        RAISE EXCEPTION 'Sampling Run requires a controlled frozen Suite payload'
            USING ERRCODE = '23514';
    END IF;
    suite_value := suite_row.payload->'suite';

    -- Locking the policy serializes quota admission across concurrent Runs.
    SELECT * INTO policy
      FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id
       AND id = suite_row.admission_policy_id
       AND definition_hash = suite_row.admission_policy_hash
     FOR UPDATE;
    IF NOT FOUND
       OR policy.status <> 'approved'
       OR policy.effective_authorization_state <> 'approved'
       OR p_created_at >= policy.valid_until
       OR p_authorization_valid_until <> policy.valid_until
       OR p_admitted_not_before < policy.next_allowed_at
       OR p_admitted_not_before >= policy.valid_until
       OR p_admission_policy_version <> policy.policy_version
       OR p_authorization_reference <> policy.authorization_reference
       OR NOT (policy.authorized_purposes @> jsonb_build_array(p_purpose)) THEN
        RAISE EXCEPTION 'Sampling Run authorization is not current or does not cover its purpose'
            USING ERRCODE = '23514';
    END IF;

    expected_count := suite_row.planned_task_count;
    task_count := jsonb_array_length(p_tasks_payload);
    IF task_count <> expected_count
       OR jsonb_array_length(p_run_payload->'planned_task_keys') <> expected_count
       OR (SELECT count(DISTINCT item #>> '{}')
             FROM jsonb_array_elements(p_run_payload->'planned_task_keys') AS item)
          <> expected_count
       OR EXISTS (
            SELECT 1
              FROM jsonb_array_elements(p_run_payload->'planned_task_keys') AS item
             WHERE item #>> '{}' !~ '^[0-9a-f]{64}$'
       ) THEN
        RAISE EXCEPTION 'Sampling Run planned denominator is invalid'
            USING ERRCODE = '23514';
    END IF;

    FOR task_value IN SELECT value FROM jsonb_array_elements(p_tasks_payload)
    LOOP
        IF jsonb_typeof(task_value) <> 'object'
           OR (SELECT count(*) FROM jsonb_object_keys(task_value)) <> 7
           OR task_value->>'task_key' !~ '^[0-9a-f]{64}$'
           OR task_value->>'source_stratum_hash' <> suite_row.source_stratum_hash
           OR task_value->>'capture_method' <> suite_row.capture_method
           OR btrim(coalesce(task_value->>'question_id', '')) = ''
           OR btrim(coalesce(task_value->>'question_version', '')) = ''
           OR task_value->>'repetition' !~ '^[1-9][0-9]*$'
           OR NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(p_run_payload->'planned_task_keys') AS key_value
                 WHERE key_value #>> '{}' = task_value->>'task_key'
           )
           OR NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(suite_value->'questions') AS question
                 WHERE question->>'question_id' = task_value->>'question_id'
                   AND question->>'question_version' = task_value->>'question_version'
           ) THEN
            RAISE EXCEPTION 'Sampling Run Task is outside the frozen denominator'
                USING ERRCODE = '23514';
        END IF;
        BEGIN
            PERFORM (task_value->>'id')::uuid;
        EXCEPTION WHEN invalid_text_representation THEN
            RAISE EXCEPTION 'Sampling Run Task id is invalid' USING ERRCODE = '22023';
        END;
    END LOOP;
    IF (SELECT count(DISTINCT item->>'task_key')
          FROM jsonb_array_elements(p_tasks_payload) AS item) <> expected_count
       OR (SELECT count(DISTINCT item->>'id')
             FROM jsonb_array_elements(p_tasks_payload) AS item) <> expected_count
       OR EXISTS (
            SELECT question->>'question_id', question->>'question_version', repetition
              FROM jsonb_array_elements(suite_value->'questions') AS question
              CROSS JOIN generate_series(1, (suite_value->>'repetitions')::integer) AS repetition
            EXCEPT
            SELECT item->>'question_id', item->>'question_version', (item->>'repetition')::integer
              FROM jsonb_array_elements(p_tasks_payload) AS item
       )
       OR EXISTS (
            SELECT item->>'question_id', item->>'question_version', (item->>'repetition')::integer
              FROM jsonb_array_elements(p_tasks_payload) AS item
            EXCEPT
            SELECT question->>'question_id', question->>'question_version', repetition
              FROM jsonb_array_elements(suite_value->'questions') AS question
              CROSS JOIN generate_series(1, (suite_value->>'repetitions')::integer) AS repetition
       ) THEN
        RAISE EXCEPTION 'Sampling Run Tasks do not exactly materialize the frozen Suite'
            USING ERRCODE = '23514';
    END IF;

    SELECT coalesce(sum(reserved_task_count - consumed_task_count - released_task_count), 0)
      INTO active_reservation
      FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND admission_policy_id = policy.id;
    IF active_reservation + expected_count > policy.quota_remaining THEN
        RAISE EXCEPTION 'Sampling policy quota cannot cover all active Run reservations'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO workflow_c_sampling_runs(
        id, project_id, suite_id, suite_hash, admission_policy_id,
        admission_policy_hash, admission_grant_hash, purpose, status,
        reserved_task_count, consumed_task_count, released_task_count,
        admitted_not_before, authorization_valid_until, version, payload, created_at
    ) VALUES (
        p_run_id, p_project_id, suite_row.id, suite_row.suite_hash, policy.id,
        p_admission_policy_hash, p_admission_grant_hash, p_purpose, 'planned',
        expected_count, 0, 0, p_admitted_not_before, p_authorization_valid_until,
        1, p_run_payload, p_created_at
    );
    INSERT INTO workflow_c_sampling_tasks(
        id, project_id, run_id, suite_id, task_key, source_stratum_hash,
        capture_method, question_id, question_version, repetition, status,
        version, payload, created_at, updated_at
    )
    SELECT (item->>'id')::uuid, p_project_id, p_run_id, suite_row.id,
           item->>'task_key', suite_row.source_stratum_hash, suite_row.capture_method,
           item->>'question_id', item->>'question_version', (item->>'repetition')::integer,
           'planned', 1, jsonb_build_object('schema_version', 1), p_created_at, p_created_at
      FROM jsonb_array_elements(p_tasks_payload) AS item;

    usage_start := date_trunc('day', p_created_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    INSERT INTO workflow_c_sampling_admission_usage(
        project_id, policy_id, window_start, reserved_count, consumed_count,
        released_count, version, updated_at
    ) VALUES (
        p_project_id, policy.id, usage_start, expected_count, 0, 0, 1, p_created_at
    ) ON CONFLICT (project_id, policy_id, window_start) DO UPDATE
        SET reserved_count = workflow_c_sampling_admission_usage.reserved_count + EXCLUDED.reserved_count,
            version = workflow_c_sampling_admission_usage.version + 1,
            updated_at = GREATEST(workflow_c_sampling_admission_usage.updated_at, EXCLUDED.updated_at);
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.run.create', p_run_id, p_idempotency_key_hash,
        p_input_hash, 'sampling_run', p_run_id, 1,
        jsonb_build_object('run_id', p_run_id), p_created_at
    );
    RETURN QUERY
    SELECT * FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id;
END;
$$;

REVOKE INSERT, UPDATE, DELETE ON workflow_c_sampling_runs,
    workflow_c_sampling_tasks FROM geo_app;
GRANT SELECT ON workflow_c_sampling_runs, workflow_c_sampling_tasks TO geo_app;

REVOKE ALL ON FUNCTION geo_create_workflow_c_sampling_run(
    uuid, uuid, text, text, uuid, text, text, text, text, text, text,
    timestamptz, timestamptz, jsonb, jsonb, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_create_workflow_c_sampling_run(
    uuid, uuid, text, text, uuid, text, text, text, text, text, text,
    timestamptz, timestamptz, jsonb, jsonb, timestamptz
) TO geo_app;

COMMENT ON FUNCTION geo_create_workflow_c_sampling_run(
    uuid, uuid, text, text, uuid, text, text, text, text, text, text,
    timestamptz, timestamptz, jsonb, jsonb, timestamptz
) IS 'Atomically reserves a Workflow C Sampling Run denominator and materializes its complete Task inventory.';
