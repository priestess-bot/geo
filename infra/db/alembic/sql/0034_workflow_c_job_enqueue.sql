-- Workflow C producers submit immutable commands through one project-scoped
-- entry point.  The application role must not need SELECT or direct INSERT on
-- the command table merely to replay an idempotent request.
--
-- 0032 deliberately recurses through JSON values to reject credential-like
-- keys, but it omitted the scalar CASE branch.  Real command payloads contain
-- strings, numbers, booleans, and nulls, all of which are safe leaves after
-- their parent keys have been checked.
CREATE OR REPLACE FUNCTION geo_workflow_c_job_spec_payload_is_safe(p_value jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
DECLARE child_key text;
DECLARE child_value jsonb;
BEGIN
    CASE jsonb_typeof(p_value)
        WHEN 'object' THEN
            FOR child_key, child_value IN SELECT key, value FROM jsonb_each(p_value)
            LOOP
                IF lower(child_key) = ANY (ARRAY[
                    'secret', 'secret_value', 'credential', 'credential_value',
                    'password', 'token', 'proxy_password', 'authorization'
                ]) OR NOT geo_workflow_c_job_spec_payload_is_safe(child_value) THEN
                    RETURN false;
                END IF;
            END LOOP;
        WHEN 'array' THEN
            FOR child_value IN SELECT value FROM jsonb_array_elements(p_value)
            LOOP
                IF NOT geo_workflow_c_job_spec_payload_is_safe(child_value) THEN
                    RETURN false;
                END IF;
            END LOOP;
        ELSE
            NULL;
    END CASE;
    RETURN true;
END;
$$;

CREATE FUNCTION geo_enqueue_workflow_c_job_spec(
    p_project_id uuid,
    p_kind text,
    p_spec_hash text,
    p_spec_payload jsonb,
    p_idempotency_key text,
    p_max_attempts integer
) RETURNS TABLE (job_id uuid, input_hash text, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE stored_spec workflow_c_job_specs%ROWTYPE;
DECLARE stored_outbox broker_outbox%ROWTYPE;
DECLARE outbox_key text;
DECLARE expected_wakeup jsonb;
DECLARE was_replayed boolean := false;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR btrim(coalesce(p_kind, '')) = ''
       OR p_kind NOT IN (
           'sampling.provider_execute', 'sampling.manual_import',
           'workflow_c.analysis.semantic_metrics', 'workflow_c.metric_judge',
           'workflow_c.metric_arbiter', 'workflow_c.analysis.comparison',
           'workflow_c.analysis.drift', 'workflow_c.alert.schedule',
           'workflow_c.alert.evaluate', 'workflow_c.alert.notify'
       )
       OR p_spec_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_spec_payload) <> 'object'
       OR p_spec_payload->'schema_version' <> '1'::jsonb
       OR p_spec_payload->>'kind' <> p_kind
       OR NOT geo_workflow_c_job_spec_payload_is_safe(p_spec_payload)
       OR NOT geo_workflow_c_sampling_job_spec_is_valid(p_kind, p_spec_payload)
       OR encode(digest(convert_to(geo_jsonb_canonical_text(p_spec_payload), 'UTF8'), 'sha256'), 'hex')
          <> p_spec_hash
       OR btrim(coalesce(p_idempotency_key, '')) = ''
       OR length(p_idempotency_key) > 500
       OR p_max_attempts IS NULL OR p_max_attempts < 1 THEN
        RAISE EXCEPTION 'Workflow C Job enqueue input is invalid'
            USING ERRCODE = '22023';
    END IF;

    outbox_key := 'wake:' || p_kind || ':' || p_idempotency_key;
    SELECT * INTO durable
    FROM durable_jobs
    WHERE project_id = p_project_id AND kind = p_kind
      AND idempotency_key = p_idempotency_key AND replay_nonce = 0
    FOR SHARE;

    IF FOUND THEN
        was_replayed := true;
        IF durable.input_hash <> p_spec_hash OR durable.max_attempts <> p_max_attempts THEN
            RAISE EXCEPTION 'Workflow C Job idempotency key was reused with different input'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO stored_spec
        FROM workflow_c_job_specs AS spec
        WHERE spec.project_id = p_project_id AND spec.job_id = durable.id
        FOR SHARE;
        IF stored_spec.job_id IS NULL OR stored_spec.kind <> p_kind
           OR stored_spec.spec_hash <> p_spec_hash
           OR stored_spec.spec_payload IS DISTINCT FROM p_spec_payload THEN
            RAISE EXCEPTION 'Workflow C immutable Job spec differs from idempotent replay'
                USING ERRCODE = '23505';
        END IF;
    ELSE
        INSERT INTO durable_jobs(
            project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, replay_nonce, created_at, updated_at
        ) VALUES (
            p_project_id, p_kind, 'queued', 0, p_spec_hash, p_idempotency_key,
            p_max_attempts, clock_timestamp(), 0, clock_timestamp(), clock_timestamp()
        ) RETURNING * INTO durable;

        INSERT INTO workflow_c_job_specs(
            project_id, job_id, kind, spec_hash, spec_payload, created_at
        ) VALUES (
            p_project_id, durable.id, p_kind, p_spec_hash, p_spec_payload, clock_timestamp()
        );

        INSERT INTO broker_outbox(
            project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            p_project_id, durable.id, p_kind,
            jsonb_build_object('job_id', durable.id::text, 'project_id', p_project_id::text),
            outbox_key, clock_timestamp()
        );
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
        ) VALUES (
            p_project_id, durable.id, 'job_enqueued', 'workflow-c-producer', 0,
            jsonb_build_object('spec_hash', p_spec_hash, 'idempotency_key', p_idempotency_key),
            clock_timestamp()
        );
    END IF;

    expected_wakeup := jsonb_build_object(
        'job_id', durable.id::text,
        'project_id', p_project_id::text
    );
    SELECT * INTO stored_outbox
    FROM broker_outbox
    WHERE project_id = p_project_id AND idempotency_key = outbox_key
    FOR SHARE;
    IF stored_outbox.id IS NULL OR stored_outbox.job_id <> durable.id
       OR stored_outbox.topic <> p_kind
       OR stored_outbox.payload IS DISTINCT FROM expected_wakeup THEN
        RAISE EXCEPTION 'Workflow C Job wakeup differs from immutable command'
            USING ERRCODE = '23505';
    END IF;

    RETURN QUERY SELECT durable.id, durable.input_hash, was_replayed;
END;
$$;

-- The generic tables retain legacy application privileges for other bounded
-- workflows.  Workflow C's spec table is intentionally narrower: producer
-- calls use the procedure above, and Workers only read frozen specs.
REVOKE INSERT ON workflow_c_job_specs FROM geo_app, geo_worker;
REVOKE ALL ON FUNCTION geo_enqueue_workflow_c_job_spec(
    uuid, text, text, jsonb, text, integer
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_workflow_c_job_spec(
    uuid, text, text, jsonb, text, integer
) TO geo_app;

COMMENT ON FUNCTION geo_enqueue_workflow_c_job_spec(uuid, text, text, jsonb, text, integer) IS
    'Atomically persists a validated Workflow C Durable Job, immutable spec, wakeup, and enqueue event.';
