CREATE FUNCTION geo_enqueue_ready_browser_capture_attempts(
    p_project_id uuid,
    p_run_id uuid,
    p_surface_release_id uuid,
    p_egress_endpoint_id uuid,
    p_profile_version_id uuid,
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
DECLARE surface_row browser_surface_releases%ROWTYPE;
DECLARE endpoint_row browser_egress_endpoints%ROWTYPE;
DECLARE profile_row browser_profile_versions%ROWTYPE;
DECLARE task_row record;
DECLARE item jsonb;
DECLARE result_row record;
DECLARE question_hash_value text;
DECLARE spec jsonb;
DECLARE spec_hash_value text;
DECLARE planned_task_count integer;
DECLARE selected_count integer := 0;
DECLARE effective_limit integer;
DECLARE scheduled_at timestamptz;
DECLARE result_items jsonb := '[]'::jsonb;
DECLARE result_payload jsonb;
BEGIN
    IF p_project_id IS NULL OR p_run_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Browser Capture bulk command is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_requested_not_before IS NULL
       OR p_authorization_checked_at IS NULL
       OR p_requested_not_before < p_authorization_checked_at
       OR p_max_tasks < 1 OR p_max_tasks > 100000
       OR jsonb_typeof(p_items) <> 'array'
       OR jsonb_array_length(p_items) > p_max_tasks THEN
        RAISE EXCEPTION 'Browser Capture bulk command is invalid' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_items) AS candidate(value)
         WHERE jsonb_typeof(candidate.value) <> 'object'
            OR (SELECT count(*) FROM jsonb_object_keys(candidate.value)) <> 4
            OR NOT candidate.value ? 'task_id'
            OR NOT candidate.value ? 'attempt_id'
            OR NOT candidate.value ? 'expected_task_version'
            OR NOT candidate.value ? 'idempotency_key_hash'
            OR candidate.value->>'task_id'
                !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            OR candidate.value->>'attempt_id'
                !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            OR candidate.value->>'expected_task_version' !~ '^[1-9][0-9]*$'
            OR candidate.value->>'idempotency_key_hash' !~ '^[0-9a-f]{64}$'
    ) THEN
        RAISE EXCEPTION 'Browser Capture bulk item is invalid' USING ERRCODE = '22023';
    END IF;
    IF (SELECT count(DISTINCT candidate.value->>'task_id')
          FROM jsonb_array_elements(p_items) AS candidate(value))
       <> jsonb_array_length(p_items)
       OR (SELECT count(DISTINCT candidate.value->>'attempt_id')
             FROM jsonb_array_elements(p_items) AS candidate(value))
          <> jsonb_array_length(p_items) THEN
        RAISE EXCEPTION 'Browser Capture bulk items are duplicated' USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'browser-capture-bulk:' || p_project_id::text || ':' || p_run_id::text || ':'
            || p_idempotency_key_hash, 0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.browser_attempt.bulk_enqueue'
       AND aggregate_id = p_run_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_run_id THEN
            RAISE EXCEPTION 'Browser Capture bulk idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN jsonb_set(existing.result_payload, '{replayed}', 'true'::jsonb, false);
    END IF;

    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    SELECT * INTO suite_row FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id AND id = run_row.suite_id FOR SHARE;
    SELECT * INTO policy_row FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = run_row.admission_policy_id FOR SHARE;
    SELECT * INTO surface_row FROM browser_surface_releases
     WHERE project_id = p_project_id AND id = p_surface_release_id FOR SHARE;
    SELECT * INTO endpoint_row FROM browser_egress_endpoints
     WHERE project_id = p_project_id AND id = p_egress_endpoint_id FOR SHARE;
    SELECT * INTO profile_row FROM browser_profile_versions
     WHERE project_id = p_project_id AND id = p_profile_version_id FOR SHARE;
    IF run_row.id IS NULL OR suite_row.id IS NULL OR policy_row.id IS NULL
       OR surface_row.id IS NULL OR endpoint_row.id IS NULL OR profile_row.id IS NULL
       OR run_row.status NOT IN ('planned', 'running')
       OR suite_row.capture_method <> 'automated_ui'
       OR suite_row.suite_hash <> run_row.suite_hash
       OR suite_row.payload->'suite'->>'adapter_release_id' <> surface_row.id::text
       OR suite_row.payload->'suite'->>'route_policy_id' <> endpoint_row.id::text
       OR suite_row.payload->'suite'->>'model_release_id' <> profile_row.id::text
       OR policy_row.status <> 'approved'
       OR policy_row.effective_authorization_state <> 'approved'
       OR p_authorization_checked_at < run_row.admitted_not_before
       OR p_authorization_checked_at >= run_row.authorization_valid_until
       OR p_authorization_checked_at >= policy_row.valid_until
       OR p_requested_not_before >= run_row.authorization_valid_until
       OR surface_row.status <> 'approved'
       OR surface_row.authorization_status <> 'approved'
       OR surface_row.authorization_valid_until <= p_authorization_checked_at
       OR endpoint_row.status <> 'approved'
       OR endpoint_row.expected_country <> 'AU'
       OR endpoint_row.network_type NOT IN ('residential', 'mobile')
       OR profile_row.status <> 'approved'
       OR NOT EXISTS (
            SELECT 1 FROM secret_versions secret
             WHERE secret.reference_id = endpoint_row.secret_reference_id
               AND secret.project_id = p_project_id
               AND secret.purpose = endpoint_row.secret_purpose
               AND secret.version = endpoint_row.secret_version
               AND secret.status = 'active'
       )
       OR NOT EXISTS (
            SELECT 1 FROM browser_egress_tests test
             WHERE test.project_id = p_project_id
               AND test.endpoint_id = endpoint_row.id
               AND test.status = 'succeeded' AND test.eligible
       ) THEN
        RAISE EXCEPTION 'Browser Capture bulk readiness or frozen lineage is stale'
            USING ERRCODE = '23514';
    END IF;

    SELECT count(*) INTO planned_task_count FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND run_id = p_run_id;
    effective_limit := LEAST(
        p_max_tasks,
        (suite_row.payload->'suite'->>'max_daily_tasks')::integer
    );
    FOR task_row IN
        SELECT id, task_key, version, question_id
          FROM workflow_c_sampling_tasks
         WHERE project_id = p_project_id AND run_id = p_run_id AND status = 'planned'
         ORDER BY task_key
         LIMIT effective_limit
         FOR UPDATE
    LOOP
        selected_count := selected_count + 1;
        item := p_items -> (selected_count - 1);
        IF item->>'task_id' <> task_row.id::text
           OR (item->>'expected_task_version')::integer <> task_row.version THEN
            RAISE EXCEPTION 'Browser Capture bulk items differ from the ready Task slice'
                USING ERRCODE = '40001';
        END IF;
        scheduled_at := p_requested_not_before + make_interval(
            secs => (selected_count - 1)::double precision
                * (suite_row.payload->'suite'->>'minimum_request_interval_seconds')::integer
        );
        IF scheduled_at >= run_row.authorization_valid_until THEN
            RAISE EXCEPTION 'Browser Capture bulk schedule exceeds authorization validity'
                USING ERRCODE = '23514';
        END IF;
        SELECT query_text_hash INTO question_hash_value
          FROM knowledge_question_set_items
         WHERE project_id = p_project_id
           AND question_set_id::text = suite_row.payload->'suite'->>'question_set_id'
           AND id::text = task_row.question_id;
        IF question_hash_value IS NULL THEN
            RAISE EXCEPTION 'Browser Capture bulk question differs from frozen Suite'
                USING ERRCODE = '23514';
        END IF;
        spec := jsonb_build_object(
            'schema_version', 1, 'kind', 'browser.capture', 'run_id', p_run_id,
            'task_id', task_row.id, 'attempt_id', (item->>'attempt_id')::uuid,
            'task_version', task_row.version + 1, 'attempt_version', 1,
            'surface_release_id', surface_row.id,
            'egress_endpoint_id', endpoint_row.id,
            'profile_version_id', profile_row.id,
            'question_hash', question_hash_value
        );
        spec_hash_value := encode(digest(convert_to(
            geo_jsonb_sampling_canonical_text(spec), 'UTF8'), 'sha256'), 'hex');
        SELECT * INTO result_row FROM geo_enqueue_browser_capture_attempt(
            p_project_id, (item->>'attempt_id')::uuid, p_run_id, task_row.id,
            task_row.version, surface_row.id, endpoint_row.id, profile_row.id,
            item->>'idempotency_key_hash', spec_hash_value, scheduled_at,
            p_authorization_checked_at
        );
        result_items := result_items || jsonb_build_array(jsonb_build_object(
            'attempt_id', result_row.attempt_id,
            'durable_job_id', result_row.durable_job_id,
            'scheduled_at', scheduled_at
        ));
    END LOOP;
    IF selected_count <> jsonb_array_length(p_items) THEN
        RAISE EXCEPTION 'Browser Capture bulk items differ from the ready Task slice'
            USING ERRCODE = '40001';
    END IF;
    IF run_row.consumed_task_count + selected_count > run_row.reserved_task_count THEN
        RAISE EXCEPTION 'Browser Capture bulk tasks exceed the Run reservation'
            USING ERRCODE = '23514';
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
        p_project_id, 'sampling.browser_attempt.bulk_enqueue', p_run_id,
        p_idempotency_key_hash, p_input_hash, 'sampling_browser_bulk_attempt', p_run_id,
        (SELECT version FROM workflow_c_sampling_runs
          WHERE project_id = p_project_id AND id = p_run_id),
        result_payload, p_authorization_checked_at
    );
    RETURN result_payload;
END;
$$;

REVOKE ALL ON FUNCTION geo_enqueue_ready_browser_capture_attempts(
    uuid, uuid, uuid, uuid, uuid, text, text, timestamptz, timestamptz, integer, jsonb
) FROM PUBLIC, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_ready_browser_capture_attempts(
    uuid, uuid, uuid, uuid, uuid, text, text, timestamptz, timestamptz, integer, jsonb
) TO geo_app;
