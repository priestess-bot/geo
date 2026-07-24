-- Workflow C Sampling must freeze its Suite input selector before a Run can
-- reserve a denominator.  The API role may only register immutable inputs and
-- create a Suite via the fenced routines below; it cannot insert or mutate
-- either source table directly.

-- `geo_jsonb_canonical_text()` predates this contract and orders object keys
-- under the database collation.  Sampling hashes must also agree with Python's
-- deterministic Unicode codepoint ordering, so this new helper pins `C`.
CREATE FUNCTION geo_jsonb_sampling_canonical_text(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
SET search_path = pg_catalog, public
AS $$
    SELECT CASE jsonb_typeof(value)
        WHEN 'object' THEN coalesce((
            SELECT '{' || string_agg(
                to_jsonb(item.key)::text || ':' || geo_jsonb_sampling_canonical_text(item.value),
                ',' ORDER BY item.key COLLATE "C"
            ) || '}'
            FROM jsonb_each(value) AS item
        ), '{}')
        WHEN 'array' THEN coalesce((
            SELECT '[' || string_agg(
                geo_jsonb_sampling_canonical_text(item.value), ',' ORDER BY item.ordinality
            ) || ']'
            FROM jsonb_array_elements(value) WITH ORDINALITY AS item(value, ordinality)
        ), '[]')
        ELSE value::text
    END
$$;

CREATE TABLE workflow_c_sampling_suite_input_options (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    option_key text NOT NULL CHECK (btrim(option_key) <> ''),
    option_hash text NOT NULL CHECK (option_hash ~ '^[0-9a-f]{64}$'),
    display_name text NOT NULL CHECK (btrim(display_name) <> ''),
    admission_policy_id uuid NOT NULL,
    admission_policy_hash text NOT NULL CHECK (
        admission_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    status text NOT NULL CHECK (status IN ('approved', 'retired')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    frozen_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, option_key),
    UNIQUE (project_id, option_hash),
    FOREIGN KEY (admission_policy_id, project_id)
        REFERENCES workflow_c_sampling_admission_policies(id, project_id)
);

ALTER TABLE workflow_c_sampling_suite_input_options ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_sampling_suite_input_options FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_sampling_suite_input_options
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

CREATE FUNCTION geo_register_workflow_c_sampling_suite_input(
    p_project_id uuid,
    p_option_id uuid,
    p_option_key text,
    p_option_hash text,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_payload jsonb,
    p_frozen_at timestamptz
) RETURNS SETOF workflow_c_sampling_suite_input_options
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE policy workflow_c_sampling_admission_policies%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Sampling Suite input is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_option_id IS NULL
       OR btrim(coalesce(p_option_key, '')) = ''
       OR p_option_hash !~ '^[0-9a-f]{64}$'
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_frozen_at IS NULL
       OR jsonb_typeof(p_payload) <> 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(p_payload)) <> 20
       OR p_payload->'schema_version' <> '1'::jsonb
       OR p_payload->>'option_key' <> p_option_key
       OR jsonb_typeof(p_payload->'questions') <> 'array'
       OR jsonb_array_length(p_payload->'questions') = 0
       OR jsonb_typeof(p_payload->'source_stratum') <> 'object'
       OR btrim(coalesce(p_payload->>'display_name', '')) = ''
       OR btrim(coalesce(p_payload->>'admission_policy_id', '')) = ''
       OR p_payload->>'admission_policy_hash' !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Sampling Suite input command is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF encode(
        digest(convert_to(geo_jsonb_sampling_canonical_text(p_payload), 'UTF8'), 'sha256'),
        'hex'
    ) <> p_option_hash THEN
        RAISE EXCEPTION 'Sampling Suite input hash does not match its payload'
            USING ERRCODE = '23514';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-sampling-suite-input:' || p_project_id::text || ':'
            || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.suite_input.register'
       AND aggregate_id = p_option_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash
           OR existing.result_id <> p_option_id THEN
            RAISE EXCEPTION 'Sampling Suite input idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT * FROM workflow_c_sampling_suite_input_options
         WHERE project_id = p_project_id AND id = p_option_id;
        RETURN;
    END IF;

    SELECT * INTO policy
      FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id
       AND id::text = p_payload->>'admission_policy_id'
       AND definition_hash = p_payload->>'admission_policy_hash'
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling Suite input references an unknown admission policy'
            USING ERRCODE = '23514';
    END IF;
    IF policy.platform <> p_payload->'source_stratum'->>'platform'
       OR policy.capture_method <> p_payload->'source_stratum'->>'capture_method'
       OR policy.adapter_release <> p_payload->'source_stratum'->>'adapter_release'
       OR policy.location_control <> p_payload->'source_stratum'->>'location_control'
       OR policy.location_evidence_hash
          <> p_payload->'source_stratum'->>'location_evidence_hash' THEN
        RAISE EXCEPTION 'Sampling Suite input target differs from admission policy'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO workflow_c_sampling_suite_input_options(
        id, project_id, option_key, option_hash, display_name,
        admission_policy_id, admission_policy_hash, status, payload, frozen_at
    ) VALUES (
        p_option_id, p_project_id, p_option_key, p_option_hash,
        p_payload->>'display_name', policy.id, policy.definition_hash,
        'approved', p_payload, p_frozen_at
    );
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.suite_input.register', p_option_id,
        p_idempotency_key_hash, p_input_hash, 'sampling_suite_input', p_option_id,
        1, jsonb_build_object('option_id', p_option_id), p_frozen_at
    );
    RETURN QUERY
    SELECT * FROM workflow_c_sampling_suite_input_options
     WHERE project_id = p_project_id AND id = p_option_id;
END;
$$;

CREATE FUNCTION geo_create_workflow_c_sampling_suite(
    p_project_id uuid,
    p_suite_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_option_id uuid,
    p_option_hash text,
    p_suite_hash text,
    p_payload jsonb,
    p_frozen_at timestamptz
) RETURNS SETOF workflow_c_sampling_suites
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE option_row workflow_c_sampling_suite_input_options%ROWTYPE;
DECLARE policy workflow_c_sampling_admission_policies%ROWTYPE;
DECLARE suite_value jsonb;
DECLARE source_value jsonb;
DECLARE field_name text;
DECLARE planned_count integer;
DECLARE repetitions integer;
DECLARE minimum_valid integer;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Sampling Suite is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_suite_id IS NULL OR p_option_id IS NULL
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_option_hash !~ '^[0-9a-f]{64}$'
       OR p_suite_hash !~ '^[0-9a-f]{64}$'
       OR p_frozen_at IS NULL
       OR jsonb_typeof(p_payload) <> 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(p_payload)) <> 4
       OR p_payload->'schema_version' <> '1'::jsonb
       OR jsonb_typeof(p_payload->'suite') <> 'object'
       OR btrim(coalesce(p_payload->>'frozen_by', '')) = '' THEN
        RAISE EXCEPTION 'Sampling Suite create command is invalid'
            USING ERRCODE = '22023';
    END IF;
    suite_value := p_payload->'suite';
    source_value := suite_value->'source_stratum';
    IF jsonb_typeof(source_value) <> 'object'
       OR jsonb_typeof(suite_value->'questions') <> 'array'
       OR jsonb_array_length(suite_value->'questions') = 0
       OR suite_value->>'project_id' <> p_project_id::text
       OR encode(
           digest(convert_to(geo_jsonb_sampling_canonical_text(suite_value), 'UTF8'), 'sha256'),
           'hex'
       ) <> p_suite_hash THEN
        RAISE EXCEPTION 'Sampling Suite frozen payload is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-sampling-suite:' || p_project_id::text || ':'
            || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.suite.create'
       AND aggregate_id = p_suite_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash OR existing.result_id <> p_suite_id THEN
            RAISE EXCEPTION 'Sampling Suite create idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT * FROM workflow_c_sampling_suites
         WHERE project_id = p_project_id AND id = p_suite_id;
        RETURN;
    END IF;

    SELECT * INTO option_row
      FROM workflow_c_sampling_suite_input_options
     WHERE project_id = p_project_id AND id = p_option_id
       AND option_hash = p_option_hash AND status = 'approved'
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling Suite input option is unavailable'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO policy
      FROM workflow_c_sampling_admission_policies
     WHERE project_id = p_project_id AND id = option_row.admission_policy_id
       AND definition_hash = option_row.admission_policy_hash
       AND status = 'approved' AND p_frozen_at < valid_until
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Sampling Suite admission is not currently approved'
            USING ERRCODE = '23514';
    END IF;

    FOREACH field_name IN ARRAY ARRAY[
        'question_set_id', 'question_set_version', 'question_set_hash',
        'adapter_release_id', 'adapter_release_hash',
        'model_release_id', 'model_release_hash',
        'route_policy_id', 'route_policy_hash',
        'runtime_manifest_id', 'runtime_manifest_hash',
        'runtime_option_id', 'runtime_option_hash',
        'admission_policy_id', 'admission_policy_hash'
    ] LOOP
        IF suite_value->>field_name IS DISTINCT FROM option_row.payload->>field_name THEN
            RAISE EXCEPTION 'Sampling Suite selector differs from its frozen input option'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF suite_value->'questions' IS DISTINCT FROM option_row.payload->'questions'
       OR source_value IS DISTINCT FROM option_row.payload->'source_stratum'
       OR policy.platform <> source_value->>'platform'
       OR policy.capture_method <> source_value->>'capture_method'
       OR policy.adapter_release <> source_value->>'adapter_release'
       OR policy.location_control <> source_value->>'location_control'
       OR policy.location_evidence_hash <> source_value->>'location_evidence_hash' THEN
        RAISE EXCEPTION 'Sampling Suite source lineage differs from authorization'
            USING ERRCODE = '23514';
    END IF;

    BEGIN
        repetitions := (suite_value->>'repetitions')::integer;
        planned_count := jsonb_array_length(suite_value->'questions') * repetitions;
        minimum_valid := (suite_value->>'minimum_valid_repeats')::integer;
        IF repetitions < 1 OR minimum_valid <> GREATEST(3, (4 * repetitions + 4) / 5)
           OR (source_value->>'capture_method' IN ('provider_api', 'proxy_grounded_api')
               AND repetitions <> 10)
           OR (source_value->>'capture_method' = 'manual_ui' AND repetitions < 3)
           OR (suite_value->>'max_planned_tasks')::integer < planned_count
           OR (suite_value->>'max_daily_tasks')::integer < 1
           OR (suite_value->>'max_daily_tasks')::integer > policy.daily_task_limit
           OR (suite_value->>'minimum_request_interval_seconds')::integer
              < policy.minimum_request_interval_seconds
           OR (suite_value->>'max_concurrency')::integer > policy.max_concurrency
           OR planned_count > policy.quota_remaining THEN
            RAISE EXCEPTION 'Sampling Suite denominator or throughput exceeds authorization'
                USING ERRCODE = '23514';
        END IF;
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'Sampling Suite numeric input is invalid' USING ERRCODE = '22023';
    END;

    INSERT INTO workflow_c_sampling_suites(
        id, project_id, suite_hash, admission_policy_id, admission_policy_hash,
        source_stratum_hash, capture_method, planned_task_count,
        minimum_valid_repeats, payload, frozen_at
    ) VALUES (
        p_suite_id, p_project_id, p_suite_hash, policy.id, policy.definition_hash,
        encode(
            digest(convert_to(geo_jsonb_sampling_canonical_text(source_value), 'UTF8'), 'sha256'),
            'hex'
        ),
        source_value->>'capture_method', planned_count, minimum_valid,
        p_payload, p_frozen_at
    );
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.suite.create', p_suite_id,
        p_idempotency_key_hash, p_input_hash, 'sampling_suite', p_suite_id,
        1, jsonb_build_object('suite_id', p_suite_id), p_frozen_at
    );
    RETURN QUERY
    SELECT * FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id AND id = p_suite_id;
END;
$$;

REVOKE ALL ON workflow_c_sampling_suite_input_options,
    workflow_c_sampling_suites FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON workflow_c_sampling_suite_input_options,
    workflow_c_sampling_suites TO geo_app, geo_worker;

REVOKE ALL ON FUNCTION
    geo_register_workflow_c_sampling_suite_input(
        uuid, uuid, text, text, text, text, jsonb, timestamptz
    ),
    geo_create_workflow_c_sampling_suite(
        uuid, uuid, text, text, uuid, text, text, jsonb, timestamptz
    ) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_register_workflow_c_sampling_suite_input(
        uuid, uuid, text, text, text, text, jsonb, timestamptz
    ),
    geo_create_workflow_c_sampling_suite(
        uuid, uuid, text, text, uuid, text, text, jsonb, timestamptz
    ) TO geo_app;

COMMENT ON FUNCTION geo_create_workflow_c_sampling_suite(
    uuid, uuid, text, text, uuid, text, text, jsonb, timestamptz
) IS 'Fences immutable Workflow C Sampling Suite creation to an approved frozen input option.';
