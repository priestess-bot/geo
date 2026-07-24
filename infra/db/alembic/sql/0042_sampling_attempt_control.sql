-- The first Provider Attempt is the only point at which a Run reservation is
-- consumed.  The complete external-work command is then submitted through the
-- existing 0034 producer in this same transaction.

CREATE FUNCTION geo_enqueue_workflow_c_provider_sampling_attempt(
    p_project_id uuid,
    p_attempt_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_run_id uuid,
    p_task_id uuid,
    p_expected_task_version integer,
    p_spec_hash text,
    p_spec_payload jsonb,
    p_job_idempotency_key text,
    p_authorization_checked_at timestamptz
) RETURNS TABLE (
    attempt_id uuid,
    durable_job_id uuid,
    task_version integer,
    attempt_version integer,
    run_version integer,
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE suite_row workflow_c_sampling_suites%ROWTYPE;
DECLARE policy workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE durable_record record;
DECLARE stored_attempt workflow_c_sampling_attempts%ROWTYPE;
DECLARE usage_row workflow_c_sampling_admission_usage%ROWTYPE;
DECLARE usage_start timestamptz;
DECLARE question_hash text;
DECLARE usage_exists boolean;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Sampling Attempt is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_attempt_id IS NULL OR p_run_id IS NULL OR p_task_id IS NULL
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_spec_hash !~ '^[0-9a-f]{64}$'
       OR p_expected_task_version < 1
       OR btrim(coalesce(p_job_idempotency_key, '')) = ''
       OR length(p_job_idempotency_key) > 500
       OR p_authorization_checked_at IS NULL
       OR jsonb_typeof(p_spec_payload) <> 'object'
       OR p_spec_payload->>'kind' <> 'sampling.provider_execute'
       OR NOT geo_workflow_c_sampling_job_spec_is_valid(
            'sampling.provider_execute', p_spec_payload
       ) THEN
        RAISE EXCEPTION 'Provider Sampling Attempt command is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_spec_payload->>'run_id' <> p_run_id::text
       OR p_spec_payload->>'task_id' <> p_task_id::text
       OR p_spec_payload->>'attempt_id' <> p_attempt_id::text
       OR (p_spec_payload->>'task_version')::integer <> p_expected_task_version + 1
       OR (p_spec_payload->>'attempt_version')::integer <> 1 THEN
        RAISE EXCEPTION 'Provider Sampling Attempt spec does not match its version fence'
            USING ERRCODE = '23514';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-provider-attempt:' || p_project_id::text || ':'
            || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.provider_attempt.enqueue'
       AND aggregate_id = p_attempt_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_attempt_id THEN
            RAISE EXCEPTION 'Provider Sampling Attempt idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO stored_attempt FROM workflow_c_sampling_attempts
         WHERE project_id = p_project_id AND id = p_attempt_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Provider Sampling Attempt replay is missing its durable record'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT stored_attempt.id, stored_attempt.durable_job_id,
            (SELECT version FROM workflow_c_sampling_tasks
              WHERE project_id = p_project_id AND id = stored_attempt.task_id),
            stored_attempt.version,
            (SELECT version FROM workflow_c_sampling_runs
              WHERE project_id = p_project_id AND id = stored_attempt.run_id),
            true;
        RETURN;
    END IF;

    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND id = p_task_id FOR UPDATE;
    IF run_row.id IS NULL OR task_row.id IS NULL
       OR task_row.run_id <> p_run_id
       OR task_row.suite_id <> run_row.suite_id
       OR task_row.version <> p_expected_task_version
       OR task_row.status <> 'planned'
       OR run_row.status NOT IN ('planned', 'running')
       OR run_row.consumed_task_count + run_row.released_task_count
          >= run_row.reserved_task_count
       OR p_authorization_checked_at < run_row.admitted_not_before
       OR p_authorization_checked_at >= run_row.authorization_valid_until THEN
        RAISE EXCEPTION 'Provider Sampling Attempt Run or Task is not admissible'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO suite_row FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id AND id = run_row.suite_id FOR SHARE;
    SELECT * INTO policy FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = run_row.admission_policy_id FOR UPDATE;
    IF suite_row.id IS NULL OR policy.id IS NULL
       OR suite_row.suite_hash <> run_row.suite_hash
       OR suite_row.admission_policy_id <> policy.id
       OR suite_row.admission_policy_hash <> policy.definition_hash
       OR policy.status <> 'approved'
       OR policy.effective_authorization_state <> 'approved'
       OR policy.policy_version <> run_row.payload->>'admission_policy_version'
       OR policy.authorization_reference <> run_row.payload->>'authorization_reference'
       OR p_authorization_checked_at >= policy.valid_until
       OR suite_row.capture_method NOT IN ('provider_api', 'proxy_grounded_api')
       OR task_row.capture_method <> suite_row.capture_method
       OR task_row.source_stratum_hash <> suite_row.source_stratum_hash
       OR p_spec_payload->'prompt'->>'purpose' <> run_row.purpose THEN
        RAISE EXCEPTION 'Provider Sampling Attempt authorization or frozen lineage is stale'
            USING ERRCODE = '23514';
    END IF;
    SELECT question->>'text_hash' INTO question_hash
      FROM jsonb_array_elements(suite_row.payload->'suite'->'questions') AS question
     WHERE question->>'question_id' = task_row.question_id
       AND question->>'question_version' = task_row.question_version;
    IF question_hash IS NULL
       OR p_spec_payload->'question'->>'sha256' <> question_hash THEN
        RAISE EXCEPTION 'Provider Sampling Attempt question differs from the frozen Suite'
            USING ERRCODE = '23514';
    END IF;

    usage_start := date_trunc(
        'day', p_authorization_checked_at AT TIME ZONE 'UTC'
    ) AT TIME ZONE 'UTC';
    SELECT * INTO usage_row FROM workflow_c_sampling_admission_usage
     WHERE project_id = p_project_id AND policy_id = policy.id
       AND window_start = usage_start FOR UPDATE;
    usage_exists := FOUND;
    IF usage_exists AND usage_row.consumed_count + 1 > policy.daily_task_limit THEN
        RAISE EXCEPTION 'Sampling policy daily task limit is exhausted'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO durable_record FROM geo_enqueue_workflow_c_job_spec(
        p_project_id,
        'sampling.provider_execute',
        p_spec_hash,
        p_spec_payload,
        p_job_idempotency_key,
        3
    );
    INSERT INTO workflow_c_sampling_attempts(
        id, project_id, run_id, task_id, task_key, durable_job_id, ordinal,
        status, authorization_checked_at, version, payload, created_at, updated_at
    ) VALUES (
        p_attempt_id, p_project_id, p_run_id, p_task_id, task_row.task_key,
        durable_record.job_id, 1, 'queued', p_authorization_checked_at,
        1, jsonb_build_object('schema_version', 1), p_authorization_checked_at,
        p_authorization_checked_at
    );
    UPDATE workflow_c_sampling_tasks
       SET status = 'queued', version = version + 1, updated_at = p_authorization_checked_at
     WHERE project_id = p_project_id AND id = p_task_id
       AND version = p_expected_task_version;
    UPDATE workflow_c_sampling_runs
       SET status = 'running', consumed_task_count = consumed_task_count + 1,
           version = version + 1
     WHERE project_id = p_project_id AND id = p_run_id;
    IF usage_exists THEN
        UPDATE workflow_c_sampling_admission_usage
           SET consumed_count = consumed_count + 1, version = version + 1,
               updated_at = GREATEST(updated_at, p_authorization_checked_at)
         WHERE project_id = p_project_id AND policy_id = policy.id
           AND window_start = usage_start;
    ELSE
        INSERT INTO workflow_c_sampling_admission_usage(
            project_id, policy_id, window_start, reserved_count, consumed_count,
            released_count, version, updated_at
        ) VALUES (
            p_project_id, policy.id, usage_start, 1, 1, 0, 1,
            p_authorization_checked_at
        );
    END IF;
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.provider_attempt.enqueue', p_attempt_id,
        p_idempotency_key_hash, p_input_hash, 'sampling_attempt', p_attempt_id,
        1, jsonb_build_object('attempt_id', p_attempt_id, 'durable_job_id', durable_record.job_id),
        p_authorization_checked_at
    );
    RETURN QUERY SELECT p_attempt_id, durable_record.job_id,
        p_expected_task_version + 1, 1,
        (SELECT version FROM workflow_c_sampling_runs
          WHERE project_id = p_project_id AND id = p_run_id),
        false;
END;
$$;

REVOKE INSERT, UPDATE, DELETE ON workflow_c_sampling_attempts FROM geo_app;
GRANT SELECT ON workflow_c_sampling_attempts TO geo_app;

REVOKE ALL ON FUNCTION geo_enqueue_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz
) TO geo_app;
