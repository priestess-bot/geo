-- A bulk enqueue is one command, not a best-effort loop of first-attempt
-- commands.  The function locks the Run and selected Tasks in stable task-key
-- order, validates the exact ready slice, then delegates each item to 0054 in
-- the same transaction.  A later quota/version/authorization failure rolls
-- back all prior item admissions and Job inserts.

CREATE FUNCTION geo_enqueue_ready_workflow_c_provider_sampling_attempts(
    p_project_id uuid,
    p_run_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_requested_not_before timestamptz,
    p_authorization_checked_at timestamptz,
    p_max_tasks integer,
    p_items jsonb
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE suite_row workflow_c_sampling_suites%ROWTYPE;
DECLARE policy_row workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE task_row record;
DECLARE item jsonb;
DECLARE result_row record;
DECLARE planned_task_count integer;
DECLARE selected_count integer := 0;
DECLARE effective_limit integer;
DECLARE scheduled_at timestamptz;
DECLARE durable_scheduled_at timestamptz;
DECLARE result_items jsonb := '[]'::jsonb;
DECLARE result_payload jsonb;
BEGIN
    IF p_project_id IS NULL
       OR p_run_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'bulk Sampling command is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_requested_not_before IS NULL
       OR p_authorization_checked_at IS NULL
       OR p_max_tasks < 1
       OR p_max_tasks > 100000
       OR jsonb_typeof(p_items) <> 'array'
       OR jsonb_array_length(p_items) > p_max_tasks THEN
        RAISE EXCEPTION 'bulk Sampling command is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(p_items) AS candidate(value)
         WHERE jsonb_typeof(candidate.value) <> 'object'
            OR (SELECT count(*) FROM jsonb_object_keys(candidate.value)) <> 6
            OR NOT candidate.value ? 'task_id'
            OR NOT candidate.value ? 'attempt_id'
            OR NOT candidate.value ? 'expected_task_version'
            OR NOT candidate.value ? 'spec_hash'
            OR NOT candidate.value ? 'spec_payload'
            OR NOT candidate.value ? 'job_idempotency_key'
            OR candidate.value->>'task_id'
                !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            OR candidate.value->>'attempt_id'
                !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            OR candidate.value->>'expected_task_version' !~ '^[1-9][0-9]*$'
            OR candidate.value->>'spec_hash' !~ '^[0-9a-f]{64}$'
            OR jsonb_typeof(candidate.value->'spec_payload') <> 'object'
            OR jsonb_typeof(candidate.value->'job_idempotency_key') <> 'string'
            OR btrim(candidate.value->>'job_idempotency_key') = ''
            OR char_length(candidate.value->>'job_idempotency_key') > 500
    ) THEN
        RAISE EXCEPTION 'bulk Sampling item is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF (SELECT count(DISTINCT candidate.value->>'task_id')
          FROM jsonb_array_elements(p_items) AS candidate(value))
       <> jsonb_array_length(p_items)
       OR (SELECT count(DISTINCT candidate.value->>'attempt_id')
             FROM jsonb_array_elements(p_items) AS candidate(value))
          <> jsonb_array_length(p_items) THEN
        RAISE EXCEPTION 'bulk Sampling items are duplicated'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-provider-bulk-attempt:' || p_project_id::text || ':'
            || p_run_id::text || ':' || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.provider_attempt.bulk_enqueue'
       AND aggregate_id = p_run_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_run_id THEN
            RAISE EXCEPTION 'bulk Sampling idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        IF jsonb_typeof(existing.result_payload) <> 'object'
           OR existing.result_payload->>'schema_version' <> '1'
           OR existing.result_payload->>'run_id' <> p_run_id::text THEN
            RAISE EXCEPTION 'bulk Sampling replay is missing its durable result'
                USING ERRCODE = '40001';
        END IF;
        RETURN jsonb_set(existing.result_payload, '{replayed}', 'true'::jsonb, false);
    END IF;

    SELECT * INTO run_row
      FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id
     FOR UPDATE;
    IF run_row.id IS NULL THEN
        RAISE EXCEPTION 'Sampling Run does not exist' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO suite_row
      FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id AND id = run_row.suite_id
     FOR SHARE;
    SELECT * INTO policy_row
      FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = run_row.admission_policy_id
     FOR SHARE;
    IF suite_row.id IS NULL
       OR policy_row.id IS NULL
       OR run_row.status NOT IN ('planned', 'running')
       OR run_row.consumed_task_count + run_row.released_task_count
          > run_row.reserved_task_count
       OR p_authorization_checked_at < run_row.admitted_not_before
       OR p_authorization_checked_at >= run_row.authorization_valid_until
       OR p_requested_not_before >= run_row.authorization_valid_until
       OR suite_row.suite_hash <> run_row.suite_hash
       OR suite_row.admission_policy_id <> policy_row.id
       OR suite_row.admission_policy_hash <> policy_row.definition_hash
       OR suite_row.capture_method NOT IN ('provider_api', 'proxy_grounded_api')
       OR policy_row.status <> 'approved'
       OR policy_row.effective_authorization_state <> 'approved'
       OR policy_row.policy_version <> run_row.payload->>'admission_policy_version'
       OR policy_row.authorization_reference <> run_row.payload->>'authorization_reference'
       OR p_authorization_checked_at >= policy_row.valid_until THEN
        RAISE EXCEPTION 'Provider Sampling bulk authorization or frozen lineage is stale'
            USING ERRCODE = '23514';
    END IF;

    SELECT count(*) INTO planned_task_count
      FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND run_id = p_run_id;
    effective_limit := LEAST(
        p_max_tasks,
        (suite_row.payload->'suite'->>'max_daily_tasks')::integer
    );
    FOR task_row IN
        SELECT id, task_key, version
          FROM workflow_c_sampling_tasks
         WHERE project_id = p_project_id
           AND run_id = p_run_id
           AND status = 'planned'
         ORDER BY task_key
         LIMIT effective_limit
         FOR UPDATE
    LOOP
        selected_count := selected_count + 1;
        item := p_items -> (selected_count - 1);
        IF item->>'task_id' <> task_row.id::text
           OR (item->>'expected_task_version')::integer <> task_row.version THEN
            RAISE EXCEPTION 'bulk Sampling items differ from the ready Task slice'
                USING ERRCODE = '40001';
        END IF;
        scheduled_at := GREATEST(p_requested_not_before, run_row.admitted_not_before)
            + make_interval(
                secs => (selected_count - 1)::double precision
                    * (suite_row.payload->'suite'->>'minimum_request_interval_seconds')::integer
            );
        SELECT * INTO result_row
          FROM geo_schedule_workflow_c_provider_sampling_attempt(
              p_project_id,
              (item->>'attempt_id')::uuid,
              encode(digest(convert_to(
                  geo_jsonb_sampling_canonical_text(
                      jsonb_build_object('idempotency_key_hash', p_idempotency_key_hash,
                                         'task_id', item->>'task_id')
                  ),
                  'UTF8'
              ), 'sha256'), 'hex'),
              encode(digest(convert_to(
                  geo_jsonb_sampling_canonical_text(jsonb_build_object(
                      'operation', 'bulk_enqueue_item',
                      'run_id', p_run_id,
                      'task_id', item->>'task_id',
                      'attempt_id', item->>'attempt_id',
                      'expected_task_version', item->>'expected_task_version',
                      'requested_not_before', scheduled_at,
                      'spec_hash', item->>'spec_hash'
                  )),
                  'UTF8'
              ), 'sha256'), 'hex'),
              p_run_id,
              (item->>'task_id')::uuid,
              (item->>'expected_task_version')::integer,
              item->>'spec_hash',
              item->'spec_payload',
              item->>'job_idempotency_key',
              p_authorization_checked_at,
              scheduled_at
          );
        SELECT next_run_at INTO durable_scheduled_at
          FROM durable_jobs
         WHERE project_id = p_project_id AND id = result_row.durable_job_id
         FOR SHARE;
        IF durable_scheduled_at IS NULL THEN
            RAISE EXCEPTION 'bulk Sampling Attempt has no durable schedule'
                USING ERRCODE = '40001';
        END IF;
        result_items := result_items || jsonb_build_array(jsonb_build_object(
            'attempt_id', result_row.attempt_id,
            'durable_job_id', result_row.durable_job_id,
            'task_version', result_row.task_version,
            'attempt_version', result_row.attempt_version,
            'run_version', result_row.run_version,
            'scheduled_at', durable_scheduled_at
        ));
    END LOOP;
    IF selected_count <> jsonb_array_length(p_items) THEN
        RAISE EXCEPTION 'bulk Sampling items differ from the ready Task slice'
            USING ERRCODE = '40001';
    END IF;

    result_payload := jsonb_build_object(
        'schema_version', 1,
        'run_id', p_run_id,
        'planned_task_count', planned_task_count,
        'enqueued_count', selected_count,
        'skipped_count', planned_task_count - selected_count,
        'attempts', result_items,
        'replayed', false
    );
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.provider_attempt.bulk_enqueue', p_run_id,
        p_idempotency_key_hash, p_input_hash, 'sampling_provider_bulk_attempt', p_run_id,
        (SELECT version FROM workflow_c_sampling_runs
          WHERE project_id = p_project_id AND id = p_run_id),
        result_payload, p_authorization_checked_at
    );
    RETURN result_payload;
END;
$$;

REVOKE ALL ON FUNCTION geo_enqueue_ready_workflow_c_provider_sampling_attempts(
    uuid, uuid, text, text, timestamptz, timestamptz, integer, jsonb
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_ready_workflow_c_provider_sampling_attempts(
    uuid, uuid, text, text, timestamptz, timestamptz, integer, jsonb
) TO geo_app;

COMMENT ON FUNCTION geo_enqueue_ready_workflow_c_provider_sampling_attempts(
    uuid, uuid, text, text, timestamptz, timestamptz, integer, jsonb
) IS 'Atomically enqueues the exact ready Provider Sampling Task slice in task-key order, preserving schedule and durable replay.';
