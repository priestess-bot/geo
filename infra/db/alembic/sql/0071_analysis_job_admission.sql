-- Comparison and drift are non-model Workflow C jobs.  They may use the
-- generic atomic Job/spec producer only after both sides of its boundary have
-- checked the frozen payload: this database envelope prevents direct app-role
-- calls from creating opaque commands, while Python reconstructs the complete
-- statistical contracts before the call.
CREATE FUNCTION geo_workflow_c_analysis_nonempty_text_is_valid(p_value jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT jsonb_typeof(p_value) = 'string'
       AND length(btrim(p_value #>> '{}')) BETWEEN 1 AND 500
$$;

CREATE FUNCTION geo_workflow_c_analysis_decimal_is_valid(p_value jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT jsonb_typeof(p_value) = 'string'
       AND p_value #>> '{}' ~ '^-?(0|[1-9][0-9]*)(\.[0-9]+)?$'
$$;

CREATE FUNCTION geo_workflow_c_analysis_stratum_is_valid(p_value jsonb)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT geo_workflow_c_json_has_exact_keys(p_value, ARRAY[
            'provider', 'reported_model', 'capture_method', 'locale', 'region',
            'source_composition_hash', 'sampling_source_stratum_hash', 'question_cluster'
       ])
       AND geo_workflow_c_analysis_nonempty_text_is_valid(p_value->'provider')
       AND geo_workflow_c_analysis_nonempty_text_is_valid(p_value->'reported_model')
       AND geo_workflow_c_analysis_nonempty_text_is_valid(p_value->'capture_method')
       AND geo_workflow_c_analysis_nonempty_text_is_valid(p_value->'locale')
       AND geo_workflow_c_analysis_nonempty_text_is_valid(p_value->'region')
       AND geo_workflow_c_json_is_sha256(p_value->'source_composition_hash')
       AND geo_workflow_c_json_is_sha256(p_value->'sampling_source_stratum_hash')
       AND geo_workflow_c_analysis_nonempty_text_is_valid(p_value->'question_cluster')
$$;

CREATE FUNCTION geo_workflow_c_analysis_job_spec_is_valid(
    p_kind text,
    p_payload jsonb
) RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
DECLARE input_value jsonb;
DECLARE protocol jsonb;
DECLARE pair_value jsonb;
DECLARE observation jsonb;
BEGIN
    IF p_kind NOT IN ('workflow_c.analysis.comparison', 'workflow_c.analysis.drift') THEN
        RETURN true;
    END IF;
    IF NOT geo_workflow_c_json_has_exact_keys(p_payload, ARRAY[
            'schema_version', 'kind', CASE
                WHEN p_kind = 'workflow_c.analysis.comparison' THEN 'comparison'
                ELSE 'drift'
            END
       ]) THEN
        RETURN false;
    END IF;

    IF p_kind = 'workflow_c.analysis.comparison' THEN
        IF NOT geo_workflow_c_json_has_exact_keys(p_payload->'comparison', ARRAY['inputs'])
           OR jsonb_typeof(p_payload->'comparison'->'inputs') <> 'array'
           OR jsonb_array_length(p_payload->'comparison'->'inputs') < 1 THEN
            RETURN false;
        END IF;
        FOR input_value IN SELECT value FROM jsonb_array_elements(p_payload->'comparison'->'inputs')
        LOOP
            IF NOT geo_workflow_c_json_has_exact_keys(input_value, ARRAY[
                    'protocol', 'sampling_source_stratum_hash', 'planned_pair_count', 'pairs'
               ])
               OR NOT geo_workflow_c_json_is_sha256(input_value->'sampling_source_stratum_hash')
               OR NOT geo_workflow_c_json_is_positive_integer(input_value->'planned_pair_count')
               OR jsonb_typeof(input_value->'pairs') <> 'array'
               OR jsonb_array_length(input_value->'pairs') < 1 THEN
                RETURN false;
            END IF;
            protocol := input_value->'protocol';
            IF NOT geo_workflow_c_json_has_exact_keys(protocol, ARRAY[
                    'protocol_hash', 'question_set_hash', 'baseline_version', 'candidate_version',
                    'metric_key', 'metric_method_version', 'comparison_id', 'family', 'stratum',
                    'alpha', 'delta', 'target_power', 'precision', 'min_pairs', 'power_plan_hash',
                    'a_priori_design_power', 'power_method_version', 'minimum_completion_ratio',
                    'bootstrap_iterations', 'bootstrap_method', 'correction_method',
                    'simultaneous_interval_method'
               ])
               OR NOT geo_workflow_c_json_is_sha256(protocol->'protocol_hash')
               OR NOT geo_workflow_c_json_is_sha256(protocol->'question_set_hash')
               OR NOT geo_workflow_c_json_is_sha256(protocol->'power_plan_hash')
               OR NOT geo_workflow_c_analysis_stratum_is_valid(protocol->'stratum')
               OR NOT geo_workflow_c_analysis_decimal_is_valid(protocol->'alpha')
               OR NOT geo_workflow_c_analysis_decimal_is_valid(protocol->'delta')
               OR NOT geo_workflow_c_analysis_decimal_is_valid(protocol->'target_power')
               OR NOT geo_workflow_c_analysis_decimal_is_valid(protocol->'precision')
               OR NOT geo_workflow_c_analysis_decimal_is_valid(protocol->'a_priori_design_power')
               OR NOT geo_workflow_c_analysis_decimal_is_valid(protocol->'minimum_completion_ratio')
               OR NOT geo_workflow_c_json_is_positive_integer(protocol->'min_pairs')
               OR NOT geo_workflow_c_json_is_positive_integer(protocol->'bootstrap_iterations') THEN
                RETURN false;
            END IF;
            IF EXISTS (
                SELECT 1 FROM unnest(ARRAY[
                    'baseline_version', 'candidate_version', 'metric_key', 'metric_method_version',
                    'comparison_id', 'family', 'power_method_version', 'bootstrap_method',
                    'correction_method', 'simultaneous_interval_method'
                ]) AS required(key)
                WHERE NOT geo_workflow_c_analysis_nonempty_text_is_valid(protocol->required.key)
            ) THEN
                RETURN false;
            END IF;
            FOR pair_value IN SELECT value FROM jsonb_array_elements(input_value->'pairs')
            LOOP
                IF NOT geo_workflow_c_json_has_exact_keys(pair_value, ARRAY[
                        'pair_id', 'question_id', 'question_cluster', 'stratum_hash',
                        'sampling_source_stratum_hash', 'capture_method', 'baseline', 'candidate'
                   ])
                   OR NOT geo_workflow_c_analysis_nonempty_text_is_valid(pair_value->'pair_id')
                   OR NOT geo_workflow_c_analysis_nonempty_text_is_valid(pair_value->'question_id')
                   OR NOT geo_workflow_c_analysis_nonempty_text_is_valid(pair_value->'question_cluster')
                   OR NOT geo_workflow_c_json_is_sha256(pair_value->'stratum_hash')
                   OR NOT geo_workflow_c_json_is_sha256(pair_value->'sampling_source_stratum_hash')
                   OR NOT geo_workflow_c_analysis_nonempty_text_is_valid(pair_value->'capture_method')
                   OR NOT geo_workflow_c_analysis_decimal_is_valid(pair_value->'baseline')
                   OR NOT geo_workflow_c_analysis_decimal_is_valid(pair_value->'candidate') THEN
                    RETURN false;
                END IF;
            END LOOP;
        END LOOP;
        RETURN true;
    END IF;

    IF NOT geo_workflow_c_json_has_exact_keys(p_payload->'drift', ARRAY[
            'source_snapshot_hash', 'target_snapshot_hash', 'baseline', 'current'
       ])
       OR NOT geo_workflow_c_json_is_sha256(p_payload->'drift'->'source_snapshot_hash')
       OR NOT geo_workflow_c_json_is_sha256(p_payload->'drift'->'target_snapshot_hash')
       OR p_payload->'drift'->>'source_snapshot_hash' = p_payload->'drift'->>'target_snapshot_hash'
       OR jsonb_typeof(p_payload->'drift'->'baseline') <> 'array'
       OR jsonb_typeof(p_payload->'drift'->'current') <> 'array'
       OR jsonb_array_length(p_payload->'drift'->'baseline') < 1
       OR jsonb_array_length(p_payload->'drift'->'current') < 1 THEN
        RETURN false;
    END IF;
    FOR observation IN
        SELECT value FROM jsonb_array_elements(p_payload->'drift'->'baseline')
        UNION ALL
        SELECT value FROM jsonb_array_elements(p_payload->'drift'->'current')
    LOOP
        IF NOT geo_workflow_c_json_has_exact_keys(observation, ARRAY[
                'observation_id', 'stratum', 'effect'
           ])
           OR NOT geo_workflow_c_analysis_nonempty_text_is_valid(observation->'observation_id')
           OR NOT geo_workflow_c_analysis_stratum_is_valid(observation->'stratum')
           OR NOT geo_workflow_c_analysis_decimal_is_valid(observation->'effect') THEN
            RETURN false;
        END IF;
    END LOOP;
    RETURN true;
END;
$$;

-- The predecessor function checked sampling commands only.  The replacement
-- intentionally keeps all durable/outbox/idempotency behavior byte-for-byte
-- equivalent, adding just the analytical schema gate before it can write.
CREATE OR REPLACE FUNCTION geo_enqueue_workflow_c_job_spec(
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
       OR NOT geo_workflow_c_analysis_job_spec_is_valid(p_kind, p_spec_payload)
       OR encode(
            digest(
                convert_to(
                    CASE
                        WHEN p_kind IN (
                            'workflow_c.analysis.comparison',
                            'workflow_c.analysis.drift'
                        ) THEN geo_workflow_c_python_canonical_text(p_spec_payload)
                        ELSE geo_jsonb_canonical_text(p_spec_payload)
                    END,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
          ) <> p_spec_hash
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

REVOKE ALL ON FUNCTION geo_workflow_c_analysis_job_spec_is_valid(text, jsonb)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_workflow_c_analysis_stratum_is_valid(jsonb)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_workflow_c_analysis_decimal_is_valid(jsonb)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_workflow_c_analysis_nonempty_text_is_valid(jsonb)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

COMMENT ON FUNCTION geo_workflow_c_analysis_job_spec_is_valid(text, jsonb) IS
    'Validates the secret-free structural envelope for comparison and drift durable job specs.';
