CREATE TABLE browser_capture_job_specs (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    run_id uuid NOT NULL,
    task_id uuid NOT NULL,
    surface_release_id uuid NOT NULL,
    egress_endpoint_id uuid NOT NULL,
    profile_version_id uuid NOT NULL,
    question_text text NOT NULL CHECK (btrim(question_text) <> ''),
    question_hash text NOT NULL CHECK (question_hash ~ '^[0-9a-f]{64}$'),
    spec_hash text NOT NULL CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    spec_payload jsonb NOT NULL CHECK (jsonb_typeof(spec_payload) = 'object'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, job_id),
    UNIQUE (project_id, attempt_id),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id),
    FOREIGN KEY (attempt_id, project_id)
      REFERENCES workflow_c_sampling_attempts(id, project_id),
    FOREIGN KEY (surface_release_id, project_id)
      REFERENCES browser_surface_releases(id, project_id),
    FOREIGN KEY (egress_endpoint_id, project_id)
      REFERENCES browser_egress_endpoints(id, project_id),
    FOREIGN KEY (profile_version_id, project_id)
      REFERENCES browser_profile_versions(id, project_id)
);

ALTER TABLE browser_capture_job_specs ENABLE ROW LEVEL SECURITY;
ALTER TABLE browser_capture_job_specs FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON browser_capture_job_specs
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
REVOKE ALL ON browser_capture_job_specs FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON browser_capture_job_specs TO geo_app, geo_worker, geo_readonly;

CREATE FUNCTION geo_enqueue_browser_capture_attempt(
    p_project_id uuid,
    p_attempt_id uuid,
    p_run_id uuid,
    p_task_id uuid,
    p_expected_task_version integer,
    p_surface_release_id uuid,
    p_egress_endpoint_id uuid,
    p_profile_version_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_requested_not_before timestamptz,
    p_authorization_checked_at timestamptz
) RETURNS TABLE (
    attempt_id uuid, durable_job_id uuid, task_version integer,
    attempt_version integer, run_version integer, replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE suite_row workflow_c_sampling_suites%ROWTYPE;
DECLARE policy workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE surface browser_surface_releases%ROWTYPE;
DECLARE endpoint browser_egress_endpoints%ROWTYPE;
DECLARE profile browser_profile_versions%ROWTYPE;
DECLARE durable durable_jobs%ROWTYPE;
DECLARE stored workflow_c_sampling_attempts%ROWTYPE;
DECLARE question_text_value text;
DECLARE question_hash_value text;
DECLARE spec jsonb;
DECLARE spec_hash_value text;
DECLARE usage_start timestamptz;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_attempt_id IS NULL OR p_run_id IS NULL OR p_task_id IS NULL
       OR p_expected_task_version < 1
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_requested_not_before IS NULL OR p_authorization_checked_at IS NULL
       OR p_requested_not_before < p_authorization_checked_at THEN
        RAISE EXCEPTION 'Browser Capture Attempt command is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'browser-capture-attempt:' || p_project_id::text || ':' || p_idempotency_key_hash, 0
    ));
    SELECT * INTO stored FROM workflow_c_sampling_attempts
     WHERE project_id = p_project_id AND id = p_attempt_id;
    IF FOUND THEN
        SELECT * INTO durable FROM durable_jobs
         WHERE project_id = p_project_id AND id = stored.durable_job_id;
        IF durable.input_hash <> p_input_hash OR durable.kind <> 'browser.capture' THEN
            RAISE EXCEPTION 'Browser Capture Attempt idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT stored.id, stored.durable_job_id,
            (SELECT version FROM workflow_c_sampling_tasks
              WHERE project_id = p_project_id AND id = stored.task_id),
            stored.version,
            (SELECT version FROM workflow_c_sampling_runs
              WHERE project_id = p_project_id AND id = stored.run_id), true;
        RETURN;
    END IF;

    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND id = p_task_id FOR UPDATE;
    SELECT * INTO suite_row FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id AND id = run_row.suite_id FOR SHARE;
    SELECT * INTO policy FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = run_row.admission_policy_id FOR UPDATE;
    SELECT * INTO surface FROM browser_surface_releases
     WHERE project_id = p_project_id AND id = p_surface_release_id FOR SHARE;
    SELECT * INTO endpoint FROM browser_egress_endpoints
     WHERE project_id = p_project_id AND id = p_egress_endpoint_id FOR SHARE;
    SELECT * INTO profile FROM browser_profile_versions
     WHERE project_id = p_project_id AND id = p_profile_version_id FOR SHARE;
    IF run_row.id IS NULL OR task_row.id IS NULL OR suite_row.id IS NULL OR policy.id IS NULL
       OR surface.id IS NULL OR endpoint.id IS NULL OR profile.id IS NULL
       OR task_row.run_id <> run_row.id OR task_row.suite_id <> suite_row.id
       OR task_row.status <> 'planned' OR task_row.version <> p_expected_task_version
       OR task_row.capture_method <> 'automated_ui' OR suite_row.capture_method <> 'automated_ui'
       OR run_row.status NOT IN ('planned', 'running')
       OR p_authorization_checked_at < run_row.admitted_not_before
       OR p_authorization_checked_at >= run_row.authorization_valid_until
       OR policy.status <> 'approved' OR policy.effective_authorization_state <> 'approved'
       OR p_authorization_checked_at >= policy.valid_until
       OR surface.status <> 'approved' OR surface.authorization_status <> 'approved'
       OR surface.authorization_valid_until <= p_authorization_checked_at
       OR endpoint.status <> 'approved' OR endpoint.expected_country <> 'AU'
       OR endpoint.network_type NOT IN ('residential', 'mobile')
       OR profile.status <> 'approved'
       OR suite_row.payload->'suite'->>'adapter_release_id' <> surface.id::text
       OR suite_row.payload->'suite'->>'model_release_id' <> profile.id::text
       OR suite_row.payload->'suite'->>'route_policy_id' <> endpoint.id::text
       OR NOT EXISTS (
            SELECT 1 FROM secret_versions secret
             WHERE secret.reference_id = endpoint.secret_reference_id
               AND secret.project_id = p_project_id AND secret.purpose = endpoint.secret_purpose
               AND secret.version = endpoint.secret_version AND secret.status = 'active'
       ) THEN
        RAISE EXCEPTION 'Browser Capture authorization or frozen lineage is stale'
            USING ERRCODE = '23514';
    END IF;
    SELECT item.query_text_snapshot, item.query_text_hash
      INTO question_text_value, question_hash_value
      FROM knowledge_question_set_items item
     WHERE item.project_id = p_project_id
       AND item.question_set_id::text = suite_row.payload->'suite'->>'question_set_id'
       AND item.id::text = task_row.question_id;
    IF question_text_value IS NULL OR question_hash_value IS NULL THEN
        RAISE EXCEPTION 'Browser Capture question differs from frozen Suite'
            USING ERRCODE = '23514';
    END IF;
    spec := jsonb_build_object(
        'schema_version', 1, 'kind', 'browser.capture',
        'run_id', p_run_id, 'task_id', p_task_id, 'attempt_id', p_attempt_id,
        'task_version', p_expected_task_version + 1, 'attempt_version', 1,
        'surface_release_id', surface.id, 'egress_endpoint_id', endpoint.id,
        'profile_version_id', profile.id, 'question_hash', question_hash_value
    );
    spec_hash_value := encode(digest(convert_to(
        geo_jsonb_sampling_canonical_text(spec), 'UTF8'), 'sha256'), 'hex');
    IF p_input_hash <> spec_hash_value THEN
        RAISE EXCEPTION 'Browser Capture input hash differs from server-frozen spec'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO durable_jobs(
        project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, replay_nonce, created_at, updated_at
    ) VALUES (
        p_project_id, 'browser.capture', 'queued', 0, spec_hash_value,
        'browser.capture:' || p_attempt_id::text, 3, p_requested_not_before,
        0, p_authorization_checked_at, p_authorization_checked_at
    ) RETURNING * INTO durable;
    INSERT INTO workflow_c_sampling_attempts(
        id, project_id, run_id, task_id, task_key, durable_job_id, ordinal,
        status, authorization_checked_at, version, payload, created_at, updated_at
    ) VALUES (
        p_attempt_id, p_project_id, p_run_id, p_task_id, task_row.task_key, durable.id,
        1, 'queued', p_authorization_checked_at, 1,
        jsonb_build_object('schema_version', 1, 'capture_method', 'automated_ui'),
        p_authorization_checked_at, p_authorization_checked_at
    );
    INSERT INTO browser_capture_job_specs(
        project_id, job_id, attempt_id, run_id, task_id, surface_release_id,
        egress_endpoint_id, profile_version_id, question_text, question_hash,
        spec_hash, spec_payload, created_at
    ) VALUES (
        p_project_id, durable.id, p_attempt_id, p_run_id, p_task_id, surface.id,
        endpoint.id, profile.id, question_text_value, question_hash_value,
        spec_hash_value, spec, p_authorization_checked_at
    );
    INSERT INTO broker_outbox(
        project_id, job_id, topic, payload, idempotency_key, available_at
    ) VALUES (
        p_project_id, durable.id, 'browser.capture',
        jsonb_build_object('job_id', durable.id::text, 'project_id', p_project_id::text),
        'wake:browser.capture:' || p_attempt_id::text, p_requested_not_before
    );
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    ) VALUES (
        p_project_id, durable.id, 'job_enqueued', 'browser-capture-producer', 0,
        jsonb_build_object('attempt_id', p_attempt_id), p_authorization_checked_at
    );
    UPDATE workflow_c_sampling_tasks SET status = 'queued', version = version + 1,
        updated_at = p_authorization_checked_at
     WHERE project_id = p_project_id AND id = p_task_id AND version = p_expected_task_version;
    UPDATE workflow_c_sampling_runs SET status = 'running',
        consumed_task_count = consumed_task_count + 1, version = version + 1
     WHERE project_id = p_project_id AND id = p_run_id;
    usage_start := date_trunc('day', p_authorization_checked_at AT TIME ZONE 'UTC')
        AT TIME ZONE 'UTC';
    INSERT INTO workflow_c_sampling_admission_usage(
        project_id, policy_id, window_start, reserved_count, consumed_count,
        released_count, version, updated_at
    ) VALUES (p_project_id, policy.id, usage_start, 1, 1, 0, 1, p_authorization_checked_at)
    ON CONFLICT (project_id, policy_id, window_start) DO UPDATE
       SET consumed_count = workflow_c_sampling_admission_usage.consumed_count + 1,
           version = workflow_c_sampling_admission_usage.version + 1,
           updated_at = p_authorization_checked_at;
    RETURN QUERY SELECT p_attempt_id, durable.id, p_expected_task_version + 1,
        1, (SELECT version FROM workflow_c_sampling_runs
             WHERE project_id = p_project_id AND id = p_run_id), false;
END;
$$;

REVOKE ALL ON FUNCTION geo_enqueue_browser_capture_attempt(
    uuid, uuid, uuid, uuid, integer, uuid, uuid, uuid, text, text,
    timestamptz, timestamptz
) FROM PUBLIC, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_browser_capture_attempt(
    uuid, uuid, uuid, uuid, integer, uuid, uuid, uuid, text, text,
    timestamptz, timestamptz
) TO geo_app;
