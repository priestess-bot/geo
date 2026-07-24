-- Provider Sampling attempts need question text, prompt lineage and runtime
-- selection that are frozen by the server before enqueue.  Keep this data in
-- a separate immutable registry so existing v1 Suite inputs remain readable
-- but cannot silently become executable.

CREATE TABLE workflow_c_sampling_provider_execution_inputs (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    suite_input_option_id uuid NOT NULL,
    suite_input_option_hash text NOT NULL CHECK (
        suite_input_option_hash ~ '^[0-9a-f]{64}$'
    ),
    execution_input_hash text NOT NULL CHECK (
        execution_input_hash ~ '^[0-9a-f]{64}$'
    ),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    status text NOT NULL CHECK (status IN ('approved', 'retired')),
    frozen_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, suite_input_option_id),
    UNIQUE (project_id, execution_input_hash),
    UNIQUE (project_id, suite_input_option_id, execution_input_hash),
    FOREIGN KEY (suite_input_option_id, project_id)
        REFERENCES workflow_c_sampling_suite_input_options(id, project_id)
        ON DELETE CASCADE
);

ALTER TABLE workflow_c_sampling_provider_execution_inputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_sampling_provider_execution_inputs FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_sampling_provider_execution_inputs
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE workflow_c_sampling_suites
    ADD COLUMN provider_execution_input_option_id uuid,
    ADD COLUMN provider_execution_input_hash text CHECK (
        provider_execution_input_hash IS NULL
        OR provider_execution_input_hash ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT workflow_c_sampling_suites_provider_execution_input_pair_check
        CHECK (
            (provider_execution_input_option_id IS NULL
             AND provider_execution_input_hash IS NULL)
            OR
            (provider_execution_input_option_id IS NOT NULL
             AND provider_execution_input_hash IS NOT NULL)
        ),
    ADD CONSTRAINT workflow_c_sampling_suites_provider_execution_input_fkey
        FOREIGN KEY (
            project_id,
            provider_execution_input_option_id,
            provider_execution_input_hash
        ) REFERENCES workflow_c_sampling_provider_execution_inputs(
            project_id,
            suite_input_option_id,
            execution_input_hash
        );

CREATE FUNCTION geo_register_workflow_c_provider_execution_input(
    p_project_id uuid,
    p_suite_input_option_id uuid,
    p_suite_input_option_hash text,
    p_execution_input_hash text,
    p_idempotency_key_hash text,
    p_command_hash text,
    p_payload jsonb,
    p_frozen_at timestamptz
) RETURNS SETOF workflow_c_sampling_provider_execution_inputs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing workflow_c_command_ledger%ROWTYPE;
DECLARE option_row workflow_c_sampling_suite_input_options%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Provider execution input is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_suite_input_option_id IS NULL
       OR p_suite_input_option_hash !~ '^[0-9a-f]{64}$'
       OR p_execution_input_hash !~ '^[0-9a-f]{64}$'
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_command_hash !~ '^[0-9a-f]{64}$'
       OR p_frozen_at IS NULL
       OR jsonb_typeof(p_payload) <> 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(p_payload)) <> 5
       OR p_payload->'schema_version' <> '1'::jsonb
       OR jsonb_typeof(p_payload->'questions') <> 'array'
       OR jsonb_array_length(p_payload->'questions') = 0
       OR jsonb_typeof(p_payload->'prompt') <> 'object'
       OR (SELECT count(*) FROM jsonb_object_keys(p_payload->'prompt')) <> 15
       OR p_payload->>'runtime_selection_id'
            !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
       OR (
           p_payload->'deadline_at' <> 'null'::jsonb
           AND jsonb_typeof(p_payload->'deadline_at') <> 'string'
       ) THEN
        RAISE EXCEPTION 'Provider execution input command is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF encode(
        digest(convert_to(geo_jsonb_sampling_canonical_text(p_payload), 'UTF8'), 'sha256'),
        'hex'
    ) <> p_execution_input_hash THEN
        RAISE EXCEPTION 'Provider execution input hash does not match its payload'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM jsonb_array_elements(p_payload->'questions') AS candidate(value)
         WHERE jsonb_typeof(candidate.value) <> 'object'
            OR (SELECT count(*) FROM jsonb_object_keys(candidate.value)) <> 4
            OR candidate.value->>'question_id' IS NULL
            OR candidate.value->>'question_version' IS NULL
            OR candidate.value->>'text_hash' !~ '^[0-9a-f]{64}$'
            OR jsonb_typeof(candidate.value->'text') <> 'string'
            OR btrim(candidate.value->>'text') = ''
            OR char_length(candidate.value->>'text') > 4000
            OR encode(
                digest(convert_to(candidate.value->>'text', 'UTF8'), 'sha256'), 'hex'
            ) <> candidate.value->>'text_hash'
    ) THEN
        RAISE EXCEPTION 'Provider execution input question is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO option_row
      FROM workflow_c_sampling_suite_input_options
     WHERE project_id = p_project_id
       AND id = p_suite_input_option_id
       AND option_hash = p_suite_input_option_hash
       AND status = 'approved'
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Provider execution input references an unavailable Suite input'
            USING ERRCODE = '23514';
    END IF;
    IF option_row.payload->'source_stratum'->>'capture_method'
       NOT IN ('provider_api', 'proxy_grounded_api') THEN
        RAISE EXCEPTION 'Provider execution input requires an automated Sampling source'
            USING ERRCODE = '23514';
    END IF;
    IF jsonb_array_length(option_row.payload->'questions')
       <> jsonb_array_length(p_payload->'questions')
       OR EXISTS (
           SELECT 1
             FROM jsonb_array_elements(option_row.payload->'questions') AS expected(value)
             LEFT JOIN jsonb_array_elements(p_payload->'questions') AS candidate(value)
               ON candidate.value->>'question_id' = expected.value->>'question_id'
              AND candidate.value->>'question_version' = expected.value->>'question_version'
            WHERE candidate.value IS NULL
               OR candidate.value->>'text_hash' <> expected.value->>'text_hash'
       ) THEN
        RAISE EXCEPTION 'Provider execution input questions differ from the frozen Suite input'
            USING ERRCODE = '23514';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-provider-execution-input:' || p_project_id::text || ':'
            || p_idempotency_key_hash,
        0
    ));
    SELECT * INTO existing
      FROM workflow_c_command_ledger
     WHERE project_id = p_project_id
       AND command_scope = 'sampling.provider_execution_input.register'
       AND aggregate_id = p_suite_input_option_id
       AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_command_hash
           OR existing.result_id <> p_suite_input_option_id THEN
            RAISE EXCEPTION 'Provider execution input idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT * FROM workflow_c_sampling_provider_execution_inputs
         WHERE project_id = p_project_id
           AND suite_input_option_id = p_suite_input_option_id;
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_c_sampling_provider_execution_inputs
         WHERE project_id = p_project_id
           AND suite_input_option_id = p_suite_input_option_id
           AND execution_input_hash <> p_execution_input_hash
    ) THEN
        RAISE EXCEPTION 'Provider execution input is immutable once registered'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO workflow_c_sampling_provider_execution_inputs(
        project_id, suite_input_option_id, suite_input_option_hash,
        execution_input_hash, payload, status, frozen_at
    ) VALUES (
        p_project_id, p_suite_input_option_id, p_suite_input_option_hash,
        p_execution_input_hash, p_payload, 'approved', p_frozen_at
    ) ON CONFLICT (project_id, suite_input_option_id) DO NOTHING;
    INSERT INTO workflow_c_command_ledger(
        project_id, command_scope, aggregate_id, idempotency_key_hash, input_hash,
        result_type, result_id, result_version, result_payload, created_at
    ) VALUES (
        p_project_id, 'sampling.provider_execution_input.register',
        p_suite_input_option_id, p_idempotency_key_hash, p_command_hash,
        'sampling_provider_execution_input', p_suite_input_option_id, 1,
        jsonb_build_object(
            'suite_input_option_id', p_suite_input_option_id,
            'execution_input_hash', p_execution_input_hash
        ), p_frozen_at
    );
    RETURN QUERY
    SELECT * FROM workflow_c_sampling_provider_execution_inputs
     WHERE project_id = p_project_id
       AND suite_input_option_id = p_suite_input_option_id;
END;
$$;

CREATE FUNCTION geo_bind_workflow_c_sampling_provider_execution_input()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate_count integer;
DECLARE candidate_option_id uuid;
DECLARE candidate_hash text;
BEGIN
    IF NEW.capture_method NOT IN ('provider_api', 'proxy_grounded_api') THEN
        RETURN NEW;
    END IF;
    SELECT count(*),
           (array_agg(execution.suite_input_option_id ORDER BY execution.suite_input_option_id))[1],
           (array_agg(execution.execution_input_hash ORDER BY execution.suite_input_option_id))[1]
      INTO candidate_count, candidate_option_id, candidate_hash
      FROM workflow_c_sampling_provider_execution_inputs AS execution
      JOIN workflow_c_sampling_suite_input_options AS option_row
        ON option_row.project_id = execution.project_id
       AND option_row.id = execution.suite_input_option_id
       AND option_row.option_hash = execution.suite_input_option_hash
     WHERE execution.project_id = NEW.project_id
       AND execution.status = 'approved'
       AND option_row.status = 'approved'
       AND option_row.admission_policy_id = NEW.admission_policy_id
       AND option_row.admission_policy_hash = NEW.admission_policy_hash
       AND option_row.payload->'questions' = NEW.payload->'suite'->'questions'
       AND option_row.payload->'source_stratum' = NEW.payload->'suite'->'source_stratum'
       AND option_row.payload->>'question_set_id'
            = NEW.payload->'suite'->>'question_set_id'
       AND option_row.payload->>'question_set_version'
            = NEW.payload->'suite'->>'question_set_version'
       AND option_row.payload->>'question_set_hash'
            = NEW.payload->'suite'->>'question_set_hash'
       AND option_row.payload->>'adapter_release_id'
            = NEW.payload->'suite'->>'adapter_release_id'
       AND option_row.payload->>'adapter_release_hash'
            = NEW.payload->'suite'->>'adapter_release_hash'
       AND option_row.payload->>'model_release_id'
            = NEW.payload->'suite'->>'model_release_id'
       AND option_row.payload->>'model_release_hash'
            = NEW.payload->'suite'->>'model_release_hash'
       AND option_row.payload->>'route_policy_id'
            = NEW.payload->'suite'->>'route_policy_id'
       AND option_row.payload->>'route_policy_hash'
            = NEW.payload->'suite'->>'route_policy_hash'
       AND option_row.payload->>'runtime_manifest_id'
            = NEW.payload->'suite'->>'runtime_manifest_id'
       AND option_row.payload->>'runtime_manifest_hash'
            = NEW.payload->'suite'->>'runtime_manifest_hash'
       AND option_row.payload->>'runtime_option_id'
            = NEW.payload->'suite'->>'runtime_option_id'
       AND option_row.payload->>'runtime_option_hash'
            = NEW.payload->'suite'->>'runtime_option_hash';
    IF candidate_count > 1 THEN
        RAISE EXCEPTION 'Sampling Suite provider execution input is ambiguous'
            USING ERRCODE = '23514';
    END IF;
    IF candidate_count = 1 THEN
        NEW.provider_execution_input_option_id := candidate_option_id;
        NEW.provider_execution_input_hash := candidate_hash;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER workflow_c_sampling_suite_bind_provider_execution_input
BEFORE INSERT ON workflow_c_sampling_suites
FOR EACH ROW EXECUTE FUNCTION geo_bind_workflow_c_sampling_provider_execution_input();

REVOKE ALL ON workflow_c_sampling_provider_execution_inputs
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON workflow_c_sampling_provider_execution_inputs TO geo_app;
REVOKE ALL ON FUNCTION geo_register_workflow_c_provider_execution_input(
    uuid, uuid, text, text, text, text, jsonb, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_register_workflow_c_provider_execution_input(
    uuid, uuid, text, text, text, text, jsonb, timestamptz
) TO geo_app;

COMMENT ON FUNCTION geo_register_workflow_c_provider_execution_input(
    uuid, uuid, text, text, text, text, jsonb, timestamptz
) IS 'Registers one immutable, server-resolved Provider Sampling execution input.';
