-- Recommendation records are an evidence-bound decision log.  They are not a
-- CRM, a publishing queue, or a source of truth for the producer domains.
CREATE TABLE service_identities (
    identity_id uuid PRIMARY KEY REFERENCES identities(id) ON DELETE RESTRICT,
    service_name text NOT NULL UNIQUE CHECK (
        service_name ~ '^[a-z][a-z0-9_.-]{2,99}$'
    ),
    status text NOT NULL CHECK (status IN ('active', 'disabled')),
    created_at timestamptz NOT NULL
);

CREATE FUNCTION geo_provision_service_identity(
    p_identity_id uuid,
    p_service_name text,
    p_created_at timestamptz
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing service_identities%ROWTYPE;
BEGIN
    IF p_identity_id IS NULL OR p_service_name !~ '^[a-z][a-z0-9_.-]{2,99}$'
       OR p_created_at IS NULL THEN
        RAISE EXCEPTION 'service identity provisioning input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM service_identities
    WHERE identity_id = p_identity_id OR service_name = p_service_name
    LIMIT 1 FOR SHARE;
    IF FOUND THEN
        IF existing.identity_id <> p_identity_id OR existing.service_name <> p_service_name THEN
            RAISE EXCEPTION 'service identity name or ID is already bound'
                USING ERRCODE = '40001';
        END IF;
        RETURN existing.identity_id;
    END IF;
    INSERT INTO identities(id, issuer, subject, display_name, status, created_at)
    VALUES (p_identity_id, 'geo.service', p_service_name, p_service_name, 'active', p_created_at)
    ON CONFLICT (id) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1 FROM identities
        WHERE id = p_identity_id AND issuer = 'geo.service'
          AND subject = p_service_name AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'service identity does not match its required non-login identity record'
            USING ERRCODE = '23514';
    END IF;
    INSERT INTO service_identities(identity_id, service_name, status, created_at)
    VALUES (p_identity_id, p_service_name, 'active', p_created_at);
    RETURN p_identity_id;
END;
$$;

CREATE FUNCTION geo_require_active_service_identity(
    p_identity_id uuid,
    p_service_name text
) RETURNS boolean
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM service_identities AS service
        JOIN identities AS identity ON identity.id = service.identity_id
        WHERE service.identity_id = p_identity_id
          AND service.service_name = p_service_name
          AND service.status = 'active' AND identity.status = 'active'
          AND identity.issuer = 'geo.service' AND identity.subject = p_service_name
    )
$$;

-- Workflow C handlers read an immutable domain spec that is bound one-to-one
-- to the shared Durable Job.  Secret references are admissible; secret values
-- and raw transport credentials are not.
CREATE FUNCTION geo_workflow_c_job_spec_payload_is_safe(p_value jsonb)
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
    END CASE;
    RETURN true;
END;
$$;

CREATE FUNCTION geo_workflow_c_json_has_exact_keys(
    p_value jsonb,
    p_keys text[]
) RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT jsonb_typeof(p_value) = 'object'
       AND NOT EXISTS (
           SELECT 1
           FROM unnest(p_keys) AS required(key)
           WHERE NOT (p_value ? required.key)
       )
       AND NOT EXISTS (
           SELECT 1
           FROM jsonb_object_keys(p_value) AS actual(key)
           WHERE NOT (actual.key = ANY(p_keys))
       )
$$;

CREATE FUNCTION geo_workflow_c_json_is_uuid(p_value jsonb) RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT jsonb_typeof(p_value) = 'string'
       AND p_value #>> '{}' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
$$;

CREATE FUNCTION geo_workflow_c_json_is_sha256(p_value jsonb) RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT jsonb_typeof(p_value) = 'string'
       AND p_value #>> '{}' ~ '^[0-9a-f]{64}$'
$$;

CREATE FUNCTION geo_workflow_c_json_is_positive_integer(p_value jsonb) RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT jsonb_typeof(p_value) = 'number'
       AND p_value #>> '{}' ~ '^[1-9][0-9]*$'
$$;

CREATE FUNCTION geo_workflow_c_json_is_rfc3339(p_value jsonb) RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT jsonb_typeof(p_value) = 'string'
       AND p_value #>> '{}' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$'
$$;

CREATE FUNCTION geo_workflow_c_sampling_job_spec_is_valid(
    p_kind text,
    p_payload jsonb
) RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
DECLARE prompt jsonb;
BEGIN
    IF p_kind NOT IN ('sampling.provider_execute', 'sampling.manual_import') THEN
        RETURN true;
    END IF;
    IF p_kind = 'sampling.provider_execute' THEN
        IF NOT geo_workflow_c_json_has_exact_keys(p_payload, ARRAY[
            'schema_version', 'kind', 'run_id', 'task_id', 'attempt_id',
            'task_version', 'attempt_version', 'question', 'runtime_selection_id',
            'admitted_by', 'admitted_at', 'prompt', 'search_mode', 'deadline_at'
        ])
           OR NOT geo_workflow_c_json_has_exact_keys(p_payload->'question', ARRAY['text', 'sha256'])
           OR jsonb_typeof(p_payload->'question'->'text') <> 'string'
           OR length(p_payload->'question'->>'text') NOT BETWEEN 1 AND 4000
           OR NOT geo_workflow_c_json_is_sha256(p_payload->'question'->'sha256')
           OR NOT geo_workflow_c_json_is_uuid(p_payload->'run_id')
           OR NOT geo_workflow_c_json_is_uuid(p_payload->'task_id')
           OR NOT geo_workflow_c_json_is_uuid(p_payload->'attempt_id')
           OR NOT geo_workflow_c_json_is_uuid(p_payload->'runtime_selection_id')
           OR NOT geo_workflow_c_json_is_uuid(p_payload->'admitted_by')
           OR NOT geo_workflow_c_json_is_positive_integer(p_payload->'task_version')
           OR NOT geo_workflow_c_json_is_positive_integer(p_payload->'attempt_version')
           OR NOT geo_workflow_c_json_is_rfc3339(p_payload->'admitted_at')
           OR jsonb_typeof(p_payload->'search_mode') NOT IN ('string', 'null')
           OR jsonb_typeof(p_payload->'deadline_at') NOT IN ('string', 'null')
           OR (jsonb_typeof(p_payload->'deadline_at') = 'string'
               AND NOT geo_workflow_c_json_is_rfc3339(p_payload->'deadline_at')) THEN
            RETURN false;
        END IF;
        prompt := p_payload->'prompt';
        RETURN geo_workflow_c_json_has_exact_keys(prompt, ARRAY[
            'binding_id', 'state_id', 'state_version', 'release_id', 'release_hash',
            'purpose', 'bundle_hash', 'system_message', 'answer_field',
            'output_schema', 'application_output_schema', 'temperature',
            'max_output_tokens', 'seed', 'tool_mode'
        ])
           AND geo_workflow_c_json_is_uuid(prompt->'binding_id')
           AND geo_workflow_c_json_is_uuid(prompt->'state_id')
           AND geo_workflow_c_json_is_positive_integer(prompt->'state_version')
           AND geo_workflow_c_json_is_uuid(prompt->'release_id')
           AND geo_workflow_c_json_is_sha256(prompt->'release_hash')
           AND geo_workflow_c_json_is_sha256(prompt->'bundle_hash')
           AND jsonb_typeof(prompt->'purpose') = 'string'
           AND jsonb_typeof(prompt->'system_message') = 'string'
           AND jsonb_typeof(prompt->'answer_field') = 'string'
           AND jsonb_typeof(prompt->'output_schema') = 'object'
           AND jsonb_typeof(prompt->'application_output_schema') = 'object'
           AND jsonb_typeof(prompt->'temperature') = 'number'
           AND geo_workflow_c_json_is_positive_integer(prompt->'max_output_tokens')
           AND jsonb_typeof(prompt->'seed') IN ('number', 'null')
           AND (jsonb_typeof(prompt->'seed') = 'null'
               OR prompt->>'seed' ~ '^-?[0-9]+$')
           AND jsonb_typeof(prompt->'tool_mode') IN ('string', 'null');
    END IF;
    RETURN geo_workflow_c_json_has_exact_keys(p_payload, ARRAY[
        'schema_version', 'kind', 'manual_import_id', 'run_id', 'task_id',
        'attempt_id', 'artifact_manifest_id', 'capture_session_id',
        'artifact_manifest_hash', 'artifact_content_hash', 'governance_policy_hash',
        'task_version', 'attempt_version'
    ])
       AND geo_workflow_c_json_is_uuid(p_payload->'manual_import_id')
       AND geo_workflow_c_json_is_uuid(p_payload->'run_id')
       AND geo_workflow_c_json_is_uuid(p_payload->'task_id')
       AND geo_workflow_c_json_is_uuid(p_payload->'attempt_id')
       AND geo_workflow_c_json_is_uuid(p_payload->'artifact_manifest_id')
       AND geo_workflow_c_json_is_uuid(p_payload->'capture_session_id')
       AND geo_workflow_c_json_is_sha256(p_payload->'artifact_manifest_hash')
       AND geo_workflow_c_json_is_sha256(p_payload->'artifact_content_hash')
       AND geo_workflow_c_json_is_sha256(p_payload->'governance_policy_hash')
       AND geo_workflow_c_json_is_positive_integer(p_payload->'task_version')
       AND geo_workflow_c_json_is_positive_integer(p_payload->'attempt_version');
END;
$$;

CREATE TABLE workflow_c_job_specs (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN (
        'sampling.provider_execute', 'sampling.manual_import',
        'workflow_c.analysis.semantic_metrics', 'workflow_c.metric_judge',
        'workflow_c.metric_arbiter', 'workflow_c.analysis.comparison',
        'workflow_c.analysis.drift', 'workflow_c.alert.schedule',
        'workflow_c.alert.evaluate', 'workflow_c.alert.notify'
    )),
    spec_hash text NOT NULL CHECK (spec_hash ~ '^[0-9a-f]{64}$'),
    spec_payload jsonb NOT NULL CHECK (
        jsonb_typeof(spec_payload) = 'object'
        AND spec_payload -> 'schema_version' = '1'::jsonb
        AND spec_payload ->> 'kind' = kind
        AND geo_workflow_c_job_spec_payload_is_safe(spec_payload)
    ),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, job_id),
    UNIQUE (job_id, project_id),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id)
        ON DELETE CASCADE
);

ALTER TABLE workflow_c_job_specs
ADD CONSTRAINT workflow_c_job_specs_sampling_payload_shape CHECK (
    geo_workflow_c_sampling_job_spec_is_valid(kind, spec_payload)
);

ALTER TABLE workflow_c_sampling_attempts
ADD COLUMN error_code text CHECK (
    error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_.:-]{0,99}$'
);

CREATE FUNCTION geo_require_workflow_c_sampling_job_fence(
    p_project_id uuid,
    p_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_spec_hash text,
    p_expected_kind text,
    p_run_id uuid,
    p_task_id uuid,
    p_attempt_id uuid,
    p_expected_task_version integer,
    p_expected_attempt_version integer
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE stored_spec workflow_c_job_specs%ROWTYPE;
DECLARE durable durable_jobs%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL OR p_lease_token IS NULL
       OR p_fencing_generation < 1 OR p_spec_hash !~ '^[0-9a-f]{64}$'
       OR p_expected_kind NOT IN ('sampling.provider_execute', 'sampling.manual_import')
       OR p_run_id IS NULL OR p_task_id IS NULL OR p_attempt_id IS NULL
       OR p_expected_task_version < 1 OR p_expected_attempt_version < 1 THEN
        RAISE EXCEPTION 'invalid or out-of-scope Workflow C Sampling worker fence'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO stored_spec
    FROM workflow_c_job_specs
    WHERE project_id = p_project_id AND job_id = p_job_id
    FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C Sampling Job spec does not exist'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO durable
    FROM durable_jobs
    WHERE project_id = p_project_id AND id = p_job_id
    FOR SHARE;
    IF NOT FOUND
       OR stored_spec.kind <> p_expected_kind OR durable.kind <> p_expected_kind
       OR stored_spec.spec_hash <> p_spec_hash OR durable.input_hash <> p_spec_hash
       OR durable.status <> 'running' OR durable.lease_token IS DISTINCT FROM p_lease_token
       OR durable.fencing_generation <> p_fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= clock_timestamp()
       OR durable.cancel_requested_at IS NOT NULL
       OR stored_spec.spec_payload->>'run_id' <> p_run_id::text
       OR stored_spec.spec_payload->>'task_id' <> p_task_id::text
       OR stored_spec.spec_payload->>'attempt_id' <> p_attempt_id::text
       OR (stored_spec.spec_payload->>'task_version')::integer <> p_expected_task_version
       OR (stored_spec.spec_payload->>'attempt_version')::integer <> p_expected_attempt_version THEN
        RAISE EXCEPTION 'Workflow C Sampling worker lease, spec, or version was fenced'
            USING ERRCODE = '40001';
    END IF;
    RETURN stored_spec.spec_payload;
END;
$$;

CREATE FUNCTION geo_validate_workflow_c_sampling_observation_input(
    p_observation_id uuid,
    p_observation_hash text,
    p_evidence_status text,
    p_ineligible_reasons jsonb,
    p_actual_location jsonb,
    p_actual_location_hash text,
    p_evidence jsonb,
    p_observed_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF p_observation_id IS NULL OR p_observation_hash !~ '^[0-9a-f]{64}$'
       OR p_evidence_status NOT IN ('complete', 'ineligible')
       OR jsonb_typeof(p_ineligible_reasons) <> 'array'
       OR jsonb_typeof(p_actual_location) <> 'object'
       OR p_actual_location_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_evidence) <> 'object'
       OR NOT geo_workflow_c_job_spec_payload_is_safe(p_evidence)
       OR p_observed_at IS NULL
       OR p_actual_location->>'location_control' NOT IN (
           'country', 'market_language', 'language_only', 'not_controlled'
       )
       OR p_actual_location->>'location_evidence_hash' !~ '^[0-9a-f]{64}$'
       OR encode(digest(convert_to(geo_jsonb_canonical_text(p_actual_location), 'UTF8'), 'sha256'), 'hex')
          <> p_actual_location_hash
       OR EXISTS (
           SELECT 1 FROM jsonb_array_elements_text(p_ineligible_reasons) AS reason(value)
           WHERE btrim(reason.value) = '' OR length(reason.value) > 200
       )
       OR (p_evidence_status = 'complete' AND jsonb_array_length(p_ineligible_reasons) <> 0)
       OR (p_evidence_status = 'ineligible' AND jsonb_array_length(p_ineligible_reasons) = 0) THEN
        RAISE EXCEPTION 'Workflow C Sampling Observation input is invalid'
            USING ERRCODE = '22023';
    END IF;
END;
$$;

CREATE FUNCTION geo_commit_workflow_c_provider_sampling(
    p_project_id uuid, p_job_id uuid, p_lease_token uuid,
    p_fencing_generation integer, p_spec_hash text, p_run_id uuid, p_task_id uuid,
    p_attempt_id uuid, p_expected_task_version integer, p_expected_attempt_version integer,
    p_observation_id uuid, p_observation_hash text, p_evidence_status text,
    p_ineligible_reasons jsonb, p_actual_location jsonb, p_actual_location_hash text,
    p_evidence jsonb, p_provider_attempt_id uuid, p_provider_response_hash text,
    p_output_hash text, p_observed_at timestamptz
) RETURNS TABLE (
    observation_id uuid, task_version integer, attempt_version integer,
    run_version integer, run_status text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE spec_payload jsonb;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
DECLARE existing workflow_c_sampling_observations%ROWTYPE;
BEGIN
    PERFORM geo_validate_workflow_c_sampling_observation_input(
        p_observation_id, p_observation_hash, p_evidence_status, p_ineligible_reasons,
        p_actual_location, p_actual_location_hash, p_evidence, p_observed_at
    );
    IF p_provider_attempt_id IS NULL OR p_provider_response_hash !~ '^[0-9a-f]{64}$'
       OR p_output_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Workflow C provider Sampling result lineage is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM workflow_c_sampling_observations
    WHERE project_id = p_project_id AND task_id = p_task_id FOR SHARE;
    IF FOUND THEN
        IF existing.id <> p_observation_id OR existing.attempt_id <> p_attempt_id
           OR existing.observation_hash <> p_observation_hash THEN
            RAISE EXCEPTION 'Workflow C Sampling Task already has different Observation evidence'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO task_row FROM workflow_c_sampling_tasks
        WHERE project_id = p_project_id AND id = p_task_id;
        SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
        WHERE project_id = p_project_id AND id = p_attempt_id;
        SELECT * INTO run_row FROM workflow_c_sampling_runs
        WHERE project_id = p_project_id AND id = p_run_id;
        RETURN QUERY SELECT existing.id, task_row.version, attempt_row.version,
            run_row.version, run_row.status;
        RETURN;
    END IF;
    spec_payload := geo_require_workflow_c_sampling_job_fence(
        p_project_id, p_job_id, p_lease_token, p_fencing_generation, p_spec_hash,
        'sampling.provider_execute', p_run_id, p_task_id, p_attempt_id,
        p_expected_task_version, p_expected_attempt_version
    );
    SELECT * INTO run_row FROM workflow_c_sampling_runs
    WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
    WHERE project_id = p_project_id AND id = p_task_id FOR UPDATE;
    SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
    WHERE project_id = p_project_id AND id = p_attempt_id FOR UPDATE;
    IF run_row.id IS NULL OR task_row.id IS NULL OR attempt_row.id IS NULL
       OR run_row.status <> 'running'
       OR task_row.run_id <> p_run_id OR task_row.version <> p_expected_task_version
       OR task_row.capture_method NOT IN ('provider_api', 'proxy_grounded_api')
       OR task_row.status NOT IN ('running', 'finalizing')
       OR attempt_row.run_id <> p_run_id OR attempt_row.task_id <> p_task_id
       OR attempt_row.durable_job_id <> p_job_id OR attempt_row.version <> p_expected_attempt_version
       OR attempt_row.status <> 'running' THEN
        RAISE EXCEPTION 'Workflow C provider Sampling aggregate was fenced'
            USING ERRCODE = '40001';
    END IF;
    INSERT INTO workflow_c_sampling_observations(
        id, project_id, run_id, task_id, attempt_id, task_key, source_stratum_hash,
        status, observation_hash, actual_location_json, evidence_json, payload, observed_at
    ) VALUES (
        p_observation_id, p_project_id, p_run_id, p_task_id, p_attempt_id,
        task_row.task_key, task_row.source_stratum_hash, p_evidence_status,
        p_observation_hash, p_actual_location, p_evidence,
        jsonb_build_object('evidence_status', p_evidence_status,
            'ineligible_reasons', p_ineligible_reasons,
            'provider_attempt_id', p_provider_attempt_id::text,
            'provider_response_hash', p_provider_response_hash, 'output_hash', p_output_hash),
        p_observed_at
    );
    UPDATE workflow_c_sampling_attempts
    SET status = 'succeeded', provider_attempt_id = p_provider_attempt_id,
        provider_response_hash = p_provider_response_hash, output_hash = p_output_hash,
        actual_location_json = p_actual_location, actual_location_hash = p_actual_location_hash,
        error_code = NULL, version = version + 1, updated_at = p_observed_at
    WHERE project_id = p_project_id AND id = p_attempt_id AND version = p_expected_attempt_version;
    UPDATE workflow_c_sampling_tasks
    SET status = 'succeeded', version = version + 1, updated_at = p_observed_at
    WHERE project_id = p_project_id AND id = p_task_id AND version = p_expected_task_version;
    IF NOT EXISTS (
        SELECT 1 FROM workflow_c_sampling_tasks
        WHERE project_id = p_project_id AND run_id = p_run_id AND status <> 'succeeded'
    ) THEN
        UPDATE workflow_c_sampling_runs SET status = 'completed', version = version + 1
        WHERE project_id = p_project_id AND id = p_run_id AND status = 'running';
    END IF;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
    WHERE project_id = p_project_id AND id = p_task_id;
    SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
    WHERE project_id = p_project_id AND id = p_attempt_id;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
    WHERE project_id = p_project_id AND id = p_run_id;
    RETURN QUERY SELECT p_observation_id, task_row.version, attempt_row.version,
        run_row.version, run_row.status;
END;
$$;

CREATE FUNCTION geo_commit_workflow_c_manual_sampling(
    p_project_id uuid, p_job_id uuid, p_lease_token uuid,
    p_fencing_generation integer, p_spec_hash text, p_run_id uuid, p_task_id uuid,
    p_attempt_id uuid, p_expected_task_version integer, p_expected_attempt_version integer,
    p_manual_import_id uuid, p_artifact_manifest_id uuid, p_artifact_manifest_hash text,
    p_artifact_content_hash text, p_governance_policy_hash text, p_capture_session_id uuid,
    p_observation_id uuid, p_observation_hash text, p_evidence_status text,
    p_ineligible_reasons jsonb, p_actual_location jsonb, p_actual_location_hash text,
    p_evidence jsonb, p_observed_at timestamptz
) RETURNS TABLE (
    observation_id uuid, task_version integer, attempt_version integer,
    manual_import_version integer, run_version integer, run_status text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE spec_payload jsonb;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
DECLARE import_row workflow_c_sampling_manual_imports%ROWTYPE;
DECLARE artifact_row workflow_c_manual_artifacts%ROWTYPE;
DECLARE existing workflow_c_sampling_observations%ROWTYPE;
BEGIN
    PERFORM geo_validate_workflow_c_sampling_observation_input(
        p_observation_id, p_observation_hash, p_evidence_status, p_ineligible_reasons,
        p_actual_location, p_actual_location_hash, p_evidence, p_observed_at
    );
    IF p_manual_import_id IS NULL OR p_artifact_manifest_id IS NULL
       OR p_capture_session_id IS NULL OR p_artifact_manifest_hash !~ '^[0-9a-f]{64}$'
       OR p_artifact_content_hash !~ '^[0-9a-f]{64}$'
       OR p_governance_policy_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Workflow C manual Sampling result lineage is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM workflow_c_sampling_observations
    WHERE project_id = p_project_id AND task_id = p_task_id FOR SHARE;
    IF FOUND THEN
        IF existing.id <> p_observation_id OR existing.attempt_id <> p_attempt_id
           OR existing.observation_hash <> p_observation_hash THEN
            RAISE EXCEPTION 'Workflow C Sampling Task already has different Observation evidence'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO task_row FROM workflow_c_sampling_tasks
        WHERE project_id = p_project_id AND id = p_task_id;
        SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
        WHERE project_id = p_project_id AND id = p_attempt_id;
        SELECT * INTO import_row FROM workflow_c_sampling_manual_imports
        WHERE project_id = p_project_id AND id = p_manual_import_id;
        SELECT * INTO run_row FROM workflow_c_sampling_runs
        WHERE project_id = p_project_id AND id = p_run_id;
        RETURN QUERY SELECT existing.id, task_row.version, attempt_row.version,
            import_row.aggregate_version, run_row.version, run_row.status;
        RETURN;
    END IF;
    spec_payload := geo_require_workflow_c_sampling_job_fence(
        p_project_id, p_job_id, p_lease_token, p_fencing_generation, p_spec_hash,
        'sampling.manual_import', p_run_id, p_task_id, p_attempt_id,
        p_expected_task_version, p_expected_attempt_version
    );
    IF spec_payload->>'manual_import_id' <> p_manual_import_id::text
       OR spec_payload->>'artifact_manifest_id' <> p_artifact_manifest_id::text
       OR spec_payload->>'artifact_manifest_hash' <> p_artifact_manifest_hash
       OR spec_payload->>'artifact_content_hash' <> p_artifact_content_hash
       OR spec_payload->>'governance_policy_hash' <> p_governance_policy_hash
       OR spec_payload->>'capture_session_id' <> p_capture_session_id::text THEN
        RAISE EXCEPTION 'Workflow C manual Sampling result differs from its frozen Job spec'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
    WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
    WHERE project_id = p_project_id AND id = p_task_id FOR UPDATE;
    SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
    WHERE project_id = p_project_id AND id = p_attempt_id FOR UPDATE;
    SELECT * INTO import_row FROM workflow_c_sampling_manual_imports
    WHERE project_id = p_project_id AND id = p_manual_import_id FOR UPDATE;
    SELECT * INTO artifact_row FROM workflow_c_manual_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_manifest_id FOR SHARE;
    IF run_row.id IS NULL OR task_row.id IS NULL OR attempt_row.id IS NULL
       OR import_row.id IS NULL OR artifact_row.artifact_id IS NULL
       OR run_row.status <> 'running' OR task_row.run_id <> p_run_id
       OR task_row.version <> p_expected_task_version OR task_row.capture_method <> 'manual_ui'
       OR task_row.status NOT IN ('running', 'finalizing')
       OR attempt_row.run_id <> p_run_id OR attempt_row.task_id <> p_task_id
       OR attempt_row.durable_job_id <> p_job_id OR attempt_row.version <> p_expected_attempt_version
       OR attempt_row.status <> 'running' OR import_row.status <> 'approved'
       OR import_row.run_id <> p_run_id OR import_row.task_id <> p_task_id
       OR import_row.attempt_id <> p_attempt_id
       OR import_row.artifact_manifest_id <> p_artifact_manifest_id
       OR import_row.artifact_manifest_hash <> p_artifact_manifest_hash
       OR import_row.artifact_content_hash <> p_artifact_content_hash
       OR import_row.governance_policy_hash <> p_governance_policy_hash
       OR import_row.capture_session_id <> p_capture_session_id
       OR artifact_row.status <> 'active' OR artifact_row.legal_hold
       OR artifact_row.expires_at <= clock_timestamp()
       OR artifact_row.run_id <> p_run_id OR artifact_row.task_id <> p_task_id
       OR artifact_row.capture_session_id <> p_capture_session_id
       OR artifact_row.manifest_hash <> p_artifact_manifest_hash
       OR artifact_row.redacted_content_hash <> p_artifact_content_hash
       OR artifact_row.governance_policy_hash <> p_governance_policy_hash THEN
        RAISE EXCEPTION 'Workflow C manual Sampling aggregate, approval, or artifact was fenced'
            USING ERRCODE = '40001';
    END IF;
    INSERT INTO workflow_c_sampling_observations(
        id, project_id, run_id, task_id, attempt_id, task_key, source_stratum_hash,
        status, observation_hash, actual_location_json, evidence_json, payload, observed_at
    ) VALUES (
        p_observation_id, p_project_id, p_run_id, p_task_id, p_attempt_id,
        task_row.task_key, task_row.source_stratum_hash, p_evidence_status,
        p_observation_hash, p_actual_location, p_evidence,
        jsonb_build_object('evidence_status', p_evidence_status,
            'ineligible_reasons', p_ineligible_reasons,
            'manual_import_id', p_manual_import_id::text,
            'artifact_manifest_id', p_artifact_manifest_id::text,
            'artifact_manifest_hash', p_artifact_manifest_hash,
            'artifact_content_hash', p_artifact_content_hash,
            'governance_policy_hash', p_governance_policy_hash,
            'capture_session_id', p_capture_session_id::text),
        p_observed_at
    );
    UPDATE workflow_c_sampling_attempts
    SET status = 'succeeded', actual_location_json = p_actual_location,
        actual_location_hash = p_actual_location_hash, error_code = NULL,
        version = version + 1, updated_at = p_observed_at
    WHERE project_id = p_project_id AND id = p_attempt_id AND version = p_expected_attempt_version;
    UPDATE workflow_c_sampling_tasks
    SET status = 'succeeded', version = version + 1, updated_at = p_observed_at
    WHERE project_id = p_project_id AND id = p_task_id AND version = p_expected_task_version;
    UPDATE workflow_c_sampling_manual_imports
    SET status = 'committed', aggregate_version = aggregate_version + 1,
        committed_at = p_observed_at
    WHERE project_id = p_project_id AND id = p_manual_import_id
      AND aggregate_version = import_row.aggregate_version;
    IF NOT EXISTS (
        SELECT 1 FROM workflow_c_sampling_tasks
        WHERE project_id = p_project_id AND run_id = p_run_id AND status <> 'succeeded'
    ) THEN
        UPDATE workflow_c_sampling_runs SET status = 'completed', version = version + 1
        WHERE project_id = p_project_id AND id = p_run_id AND status = 'running';
    END IF;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
    WHERE project_id = p_project_id AND id = p_task_id;
    SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
    WHERE project_id = p_project_id AND id = p_attempt_id;
    SELECT * INTO import_row FROM workflow_c_sampling_manual_imports
    WHERE project_id = p_project_id AND id = p_manual_import_id;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
    WHERE project_id = p_project_id AND id = p_run_id;
    RETURN QUERY SELECT p_observation_id, task_row.version, attempt_row.version,
        import_row.aggregate_version, run_row.version, run_row.status;
END;
$$;

CREATE FUNCTION geo_record_workflow_c_sampling_failure(
    p_project_id uuid, p_job_id uuid, p_lease_token uuid,
    p_fencing_generation integer, p_spec_hash text, p_run_id uuid, p_task_id uuid,
    p_attempt_id uuid, p_expected_task_version integer, p_expected_attempt_version integer,
    p_error_code text, p_retryable boolean, p_occurred_at timestamptz
) RETURNS TABLE (
    task_version integer, attempt_version integer, run_version integer, run_status text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE spec_payload jsonb;
DECLARE spec_kind text;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
BEGIN
    IF p_error_code !~ '^[a-z][a-z0-9_.:-]{0,99}$' OR p_occurred_at IS NULL THEN
        RAISE EXCEPTION 'Workflow C Sampling failure input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT kind INTO spec_kind FROM workflow_c_job_specs
    WHERE project_id = p_project_id AND job_id = p_job_id;
    IF NOT FOUND OR spec_kind NOT IN ('sampling.provider_execute', 'sampling.manual_import') THEN
        RAISE EXCEPTION 'Workflow C Sampling Job kind is unsupported'
            USING ERRCODE = '22023';
    END IF;
    spec_payload := geo_require_workflow_c_sampling_job_fence(
        p_project_id, p_job_id, p_lease_token, p_fencing_generation, p_spec_hash,
        spec_kind, p_run_id, p_task_id, p_attempt_id,
        p_expected_task_version, p_expected_attempt_version
    );
    SELECT * INTO run_row FROM workflow_c_sampling_runs
    WHERE project_id = p_project_id AND id = p_run_id FOR UPDATE;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
    WHERE project_id = p_project_id AND id = p_task_id FOR UPDATE;
    SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
    WHERE project_id = p_project_id AND id = p_attempt_id FOR UPDATE;
    IF run_row.id IS NULL OR task_row.id IS NULL OR attempt_row.id IS NULL
       OR run_row.status <> 'running' OR task_row.run_id <> p_run_id
       OR task_row.version <> p_expected_task_version
       OR task_row.status NOT IN ('running', 'finalizing')
       OR attempt_row.run_id <> p_run_id OR attempt_row.task_id <> p_task_id
       OR attempt_row.durable_job_id <> p_job_id OR attempt_row.version <> p_expected_attempt_version
       OR attempt_row.status <> 'running' THEN
        RAISE EXCEPTION 'Workflow C Sampling failure aggregate was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF p_retryable THEN
        UPDATE workflow_c_sampling_attempts
        SET status = 'queued', error_code = p_error_code, version = version + 1,
            updated_at = p_occurred_at
        WHERE project_id = p_project_id AND id = p_attempt_id
          AND version = p_expected_attempt_version;
        UPDATE workflow_c_sampling_tasks
        SET status = 'retry_ready', version = version + 1, updated_at = p_occurred_at
        WHERE project_id = p_project_id AND id = p_task_id
          AND version = p_expected_task_version;
    ELSE
        UPDATE workflow_c_sampling_attempts
        SET status = 'failed', error_code = p_error_code, version = version + 1,
            updated_at = p_occurred_at
        WHERE project_id = p_project_id AND id = p_attempt_id
          AND version = p_expected_attempt_version;
        UPDATE workflow_c_sampling_tasks
        SET status = 'failed', version = version + 1, updated_at = p_occurred_at
        WHERE project_id = p_project_id AND id = p_task_id
          AND version = p_expected_task_version;
        IF NOT EXISTS (
            SELECT 1 FROM workflow_c_sampling_tasks
            WHERE project_id = p_project_id AND run_id = p_run_id
              AND status NOT IN ('succeeded', 'failed', 'cancelled')
        ) THEN
            UPDATE workflow_c_sampling_runs SET status = 'failed', version = version + 1
            WHERE project_id = p_project_id AND id = p_run_id AND status = 'running';
        END IF;
    END IF;
    SELECT * INTO task_row FROM workflow_c_sampling_tasks
    WHERE project_id = p_project_id AND id = p_task_id;
    SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
    WHERE project_id = p_project_id AND id = p_attempt_id;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
    WHERE project_id = p_project_id AND id = p_run_id;
    RETURN QUERY SELECT task_row.version, attempt_row.version, run_row.version, run_row.status;
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_job_spec_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Workflow C Job spec is immutable'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR SHARE;
    IF durable.kind <> NEW.kind OR durable.input_hash <> NEW.spec_hash
       OR durable.status <> 'queued' THEN
        RAISE EXCEPTION 'Workflow C Job spec does not match its queued Durable Job'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE workflow_c_report_snapshot_versions (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    report_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    status text NOT NULL CHECK (status IN (
        'draft', 'in_review', 'approved', 'stale', 'superseded', 'revoked'
    )),
    campaign_id uuid NOT NULL,
    monitoring_report_id uuid NOT NULL,
    monitoring_report_hash text NOT NULL CHECK (monitoring_report_hash ~ '^[0-9a-f]{64}$'),
    semantic_snapshot_hash text NOT NULL CHECK (semantic_snapshot_hash ~ '^[0-9a-f]{64}$'),
    source_kind text NOT NULL CHECK (source_kind IN (
        'provider_api', 'proxy_grounded_api', 'automated_ui'
    )),
    approved_safe_payload jsonb NOT NULL CHECK (
        jsonb_typeof(approved_safe_payload) = 'object'
        AND NOT approved_safe_payload ?| ARRAY[
            'raw_body', 'raw_response', 'credential', 'secret', 'token',
            'artifact_uri', 'debug', 'model_reasoning', 'actor_debug'
        ]
    ),
    approved_safe_payload_hash text NOT NULL CHECK (
        approved_safe_payload_hash ~ '^[0-9a-f]{64}$'
    ),
    version_hash text NOT NULL CHECK (version_hash ~ '^[0-9a-f]{64}$'),
    actor_id uuid NOT NULL REFERENCES identities(id),
    reason text,
    occurred_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, report_id, version),
    UNIQUE (version_hash),
    UNIQUE (report_id, project_id, version),
    FOREIGN KEY (campaign_id, project_id)
        REFERENCES geo_campaigns(id, project_id),
    FOREIGN KEY (monitoring_report_id, project_id)
        REFERENCES monitoring_reports(id, project_id),
    FOREIGN KEY (semantic_snapshot_hash, project_id)
        REFERENCES workflow_c_semantic_metric_snapshots(snapshot_hash, project_id),
    CHECK (version <> 1 OR status = 'draft'),
    CHECK (
        (status IN ('stale', 'superseded', 'revoked')
            AND btrim(coalesce(reason, '')) <> '')
        OR (status NOT IN ('stale', 'superseded', 'revoked') AND reason IS NULL)
    )
);

CREATE FUNCTION geo_assert_workflow_c_report_snapshot_version_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE predecessor workflow_c_report_snapshot_versions%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Workflow C report snapshot versions are append-only'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.version = 1 THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Workflow C report snapshot version one must be draft'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT predecessor
    FROM workflow_c_report_snapshot_versions
    WHERE project_id = NEW.project_id AND report_id = NEW.report_id
      AND version = NEW.version - 1
    FOR SHARE;
    IF (NEW.campaign_id, NEW.monitoring_report_id, NEW.monitoring_report_hash,
        NEW.semantic_snapshot_hash, NEW.source_kind, NEW.approved_safe_payload,
        NEW.approved_safe_payload_hash)
       IS DISTINCT FROM
       (predecessor.campaign_id, predecessor.monitoring_report_id,
        predecessor.monitoring_report_hash, predecessor.semantic_snapshot_hash,
        predecessor.source_kind, predecessor.approved_safe_payload,
        predecessor.approved_safe_payload_hash)
       OR NOT (
           (predecessor.status = 'draft' AND NEW.status = 'in_review')
        OR (predecessor.status = 'in_review' AND NEW.status IN ('approved', 'revoked'))
        OR (predecessor.status = 'approved' AND NEW.status IN ('stale', 'superseded', 'revoked'))
       ) THEN
        RAISE EXCEPTION 'Workflow C report snapshot status or immutable lineage transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE workflow_c_alert_evaluations (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    schedule_id uuid NOT NULL,
    schedule_version integer NOT NULL CHECK (schedule_version > 0),
    rule_version_id uuid NOT NULL,
    rule_hash text NOT NULL CHECK (rule_hash ~ '^[0-9a-f]{64}$'),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    evaluation_hash text NOT NULL CHECK (evaluation_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('matched', 'not_matched')),
    matched boolean NOT NULL,
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND payload->>'schema_version' = 'workflow-c-alert-evaluation-v1'
        AND payload ?& ARRAY[
            'evaluator_version', 'rule', 'scope', 'input_hash', 'matched',
            'reason_codes', 'evidence', 'trigger_snapshot', 'evaluation_hash', 'evaluated_at',
            'rule_kind', 'rule_hash', 'parameter_schema_version',
            'input_schema_version', 'trigger_snapshot_hash'
        ]
        AND jsonb_typeof(payload->'rule') = 'object'
        AND jsonb_typeof(payload->'scope') = 'object'
        AND jsonb_typeof(payload->'reason_codes') = 'array'
        AND jsonb_typeof(payload->'evidence') = 'array'
        AND jsonb_typeof(payload->'trigger_snapshot') IN ('object', 'null')
        AND NOT payload ?| ARRAY[
            'raw_body', 'raw_response', 'credential', 'secret', 'token',
            'artifact_uri', 'debug', 'model_reasoning'
        ]
    ),
    evaluated_at timestamptz NOT NULL,
    UNIQUE (project_id, job_id),
    UNIQUE (project_id, evaluation_hash),
    UNIQUE (evaluation_hash),
    FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (schedule_id, project_id)
        REFERENCES workflow_c_alert_schedules(id, project_id) ON DELETE RESTRICT,
    FOREIGN KEY (rule_version_id, project_id)
        REFERENCES workflow_c_alert_rule_versions(id, project_id) ON DELETE RESTRICT,
    CHECK ((status = 'matched') = matched)
);

-- Rule kind admission must not exceed the evaluator/API vocabulary.  Keeping
-- this tightening in 0032 preserves the checksum of the prior release while
-- failing closed if an unsupported legacy draft is still present.
ALTER TABLE workflow_c_alert_rule_versions
DROP CONSTRAINT workflow_c_alert_rule_versions_payload_check;
ALTER TABLE workflow_c_alert_rule_versions
ADD CONSTRAINT workflow_c_alert_rule_versions_payload_check CHECK (
    jsonb_typeof(payload) = 'object'
    AND payload->>'kind' IN (
        'threshold', 'baseline_delta', 'negative_question',
        'completion_freshness', 'model_drift', 'source_drift'
    )
);

CREATE TABLE workflow_c_admin_inbox_notifications (
    command_id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND payload ? 'summary'
        AND jsonb_typeof(payload->'summary') = 'object'
        AND NOT payload ?| ARRAY[
            'credential', 'secret', 'token', 'raw_body', 'raw_response',
            'artifact_uri', 'debug', 'model_reasoning'
        ]
    ),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    UNIQUE (command_id, project_id),
    UNIQUE (project_id, idempotency_key)
);

CREATE FUNCTION geo_assert_workflow_c_admin_inbox_notification_immutable()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Workflow C Admin inbox notifications are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_alert_evaluation_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Workflow C alert evaluations are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_require_workflow_c_job_lease(
    p_project_id uuid,
    p_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_expected_kind text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE stored_spec workflow_c_job_specs%ROWTYPE;
DECLARE durable durable_jobs%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL OR p_lease_token IS NULL OR p_fencing_generation < 1
       OR p_expected_kind NOT IN ('workflow_c.alert.schedule', 'workflow_c.alert.evaluate') THEN
        RAISE EXCEPTION 'invalid or out-of-scope Workflow C Job lease'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO stored_spec FROM workflow_c_job_specs
    WHERE project_id = p_project_id AND job_id = p_job_id FOR SHARE;
    SELECT * INTO durable FROM durable_jobs
    WHERE project_id = p_project_id AND id = p_job_id FOR SHARE;
    IF stored_spec.job_id IS NULL OR durable.id IS NULL
       OR stored_spec.kind <> p_expected_kind OR durable.kind <> p_expected_kind
       OR stored_spec.spec_hash <> durable.input_hash OR durable.status <> 'running'
       OR durable.lease_token IS DISTINCT FROM p_lease_token
       OR durable.fencing_generation <> p_fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= clock_timestamp()
       OR durable.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C Job lease or frozen spec was fenced'
            USING ERRCODE = '40001';
    END IF;
    RETURN stored_spec.spec_payload;
END;
$$;

CREATE FUNCTION geo_enqueue_workflow_c_alert_evaluation(
    p_job_id uuid, p_project_id uuid, p_lease_token uuid,
    p_fencing_generation integer, p_schedule_id uuid, p_expected_schedule_version integer,
    p_scheduled_for timestamptz, p_evaluate_job_id uuid, p_evaluate_spec_hash text,
    p_evaluate_spec_payload jsonb, p_evaluate_idempotency_key text,
    p_successor_job_id uuid, p_successor_spec_hash text, p_successor_spec_payload jsonb,
    p_successor_idempotency_key text, p_next_run_at timestamptz
) RETURNS TABLE (status text, evaluation_job_id uuid, successor_job_id uuid)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE parent_spec jsonb;
DECLARE schedule_row workflow_c_alert_schedules%ROWTYPE;
DECLARE rule_row workflow_c_alert_rule_versions%ROWTYPE;
DECLARE existing durable_jobs%ROWTYPE;
DECLARE stored_spec workflow_c_job_specs%ROWTYPE;
DECLARE evaluation_exists boolean := false;
DECLARE successor_exists boolean := false;
BEGIN
    parent_spec := geo_require_workflow_c_job_lease(
        p_project_id, p_job_id, p_lease_token, p_fencing_generation, 'workflow_c.alert.schedule'
    );
    IF p_schedule_id IS NULL OR p_expected_schedule_version < 1 OR p_scheduled_for IS NULL
       OR p_evaluate_job_id IS NULL OR p_successor_job_id IS NULL
       OR p_evaluate_spec_hash !~ '^[0-9a-f]{64}$'
       OR p_successor_spec_hash !~ '^[0-9a-f]{64}$'
       OR btrim(coalesce(p_evaluate_idempotency_key, '')) = ''
       OR btrim(coalesce(p_successor_idempotency_key, '')) = ''
       OR jsonb_typeof(p_evaluate_spec_payload) <> 'object'
       OR jsonb_typeof(p_successor_spec_payload) <> 'object'
       OR NOT geo_workflow_c_job_spec_payload_is_safe(p_evaluate_spec_payload)
       OR NOT geo_workflow_c_job_spec_payload_is_safe(p_successor_spec_payload)
       OR p_evaluate_spec_payload->'schema_version' <> '1'::jsonb
       OR p_evaluate_spec_payload->>'kind' <> 'workflow_c.alert.evaluate'
       OR p_evaluate_spec_payload->>'schedule_id' <> p_schedule_id::text
       OR (p_evaluate_spec_payload->>'schedule_version')::integer <> p_expected_schedule_version
       OR p_successor_spec_payload->'schema_version' <> '1'::jsonb
       OR p_successor_spec_payload->>'kind' <> 'workflow_c.alert.schedule'
       OR p_successor_spec_payload->>'schedule_id' <> p_schedule_id::text
       OR (p_successor_spec_payload->>'schedule_version')::integer <> p_expected_schedule_version
       OR (p_successor_spec_payload->>'scheduled_for')::timestamptz <> p_next_run_at
       OR encode(digest(convert_to(geo_jsonb_canonical_text(p_evaluate_spec_payload), 'UTF8'), 'sha256'), 'hex')
          <> p_evaluate_spec_hash
       OR encode(digest(convert_to(geo_jsonb_canonical_text(p_successor_spec_payload), 'UTF8'), 'sha256'), 'hex')
          <> p_successor_spec_hash
       OR p_next_run_at IS NULL OR p_next_run_at <= p_scheduled_for THEN
        RAISE EXCEPTION 'Workflow C alert evaluation enqueue input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO schedule_row FROM workflow_c_alert_schedules
    WHERE project_id = p_project_id AND id = p_schedule_id FOR UPDATE;
    SELECT * INTO rule_row FROM workflow_c_alert_rule_versions
    WHERE project_id = p_project_id AND id = schedule_row.rule_version_id FOR SHARE;
    IF schedule_row.id IS NULL OR rule_row.id IS NULL OR schedule_row.status <> 'active'
       OR schedule_row.version <> p_expected_schedule_version
       OR schedule_row.next_run_at <> p_scheduled_for OR rule_row.status <> 'approved'
       OR parent_spec->>'schedule_id' <> p_schedule_id::text
       OR (parent_spec->>'schedule_version')::integer <> p_expected_schedule_version
       OR (parent_spec->>'scheduled_for')::timestamptz <> p_scheduled_for THEN
        RAISE EXCEPTION 'Workflow C alert schedule was fenced or is not due'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO existing FROM durable_jobs
    WHERE project_id = p_project_id
      AND (id = p_evaluate_job_id OR (
          kind = 'workflow_c.alert.evaluate'
          AND idempotency_key = p_evaluate_idempotency_key AND replay_nonce = 0
      )) FOR SHARE;
    IF FOUND THEN
        IF existing.id <> p_evaluate_job_id
           OR existing.kind <> 'workflow_c.alert.evaluate'
           OR existing.input_hash <> p_evaluate_spec_hash
           OR existing.idempotency_key <> p_evaluate_idempotency_key THEN
            RAISE EXCEPTION 'Workflow C alert evaluation idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO stored_spec FROM workflow_c_job_specs
        WHERE project_id = p_project_id AND job_id = p_evaluate_job_id FOR SHARE;
        IF stored_spec.job_id IS NULL OR stored_spec.kind <> existing.kind
           OR stored_spec.spec_hash <> p_evaluate_spec_hash
           OR stored_spec.spec_payload IS DISTINCT FROM p_evaluate_spec_payload THEN
            RAISE EXCEPTION 'Workflow C alert evaluation immutable Job spec differs'
                USING ERRCODE = '23505';
        END IF;
        evaluation_exists := true;
    END IF;
    IF NOT evaluation_exists THEN
        INSERT INTO durable_jobs(
            id, project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, parent_job_id, replay_nonce, created_at, updated_at
        ) VALUES (
            p_evaluate_job_id, p_project_id, 'workflow_c.alert.evaluate', 'queued', 5,
            p_evaluate_spec_hash, p_evaluate_idempotency_key, 3, clock_timestamp(),
            p_job_id, 0, clock_timestamp(), clock_timestamp()
        );
        INSERT INTO workflow_c_job_specs(
            project_id, job_id, kind, spec_hash, spec_payload, created_at
        ) VALUES (
            p_project_id, p_evaluate_job_id, 'workflow_c.alert.evaluate',
            p_evaluate_spec_hash, p_evaluate_spec_payload, clock_timestamp()
        );
        INSERT INTO broker_outbox(
            id, project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            gen_random_uuid(), p_project_id, p_evaluate_job_id, 'workflow_c.alert.evaluate',
            jsonb_build_object('job_id', p_evaluate_job_id::text, 'project_id', p_project_id::text),
            'wake:workflow_c.alert.evaluate:' || p_evaluate_job_id::text, clock_timestamp()
        );
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
        ) VALUES (
            p_project_id, p_evaluate_job_id, 'job_enqueued', 'workflow-c-alert-schedule', 0,
            jsonb_build_object('parent_job_id', p_job_id::text), clock_timestamp()
        );
    END IF;
    SELECT * INTO existing FROM durable_jobs
    WHERE project_id = p_project_id
      AND (id = p_successor_job_id OR (
          kind = 'workflow_c.alert.schedule'
          AND idempotency_key = p_successor_idempotency_key AND replay_nonce = 0
      )) FOR SHARE;
    IF FOUND THEN
        IF existing.id <> p_successor_job_id
           OR existing.kind <> 'workflow_c.alert.schedule'
           OR existing.input_hash <> p_successor_spec_hash
           OR existing.idempotency_key <> p_successor_idempotency_key THEN
            RAISE EXCEPTION 'Workflow C alert successor idempotency key was reused'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO stored_spec FROM workflow_c_job_specs
        WHERE project_id = p_project_id AND job_id = p_successor_job_id FOR SHARE;
        IF stored_spec.job_id IS NULL OR stored_spec.kind <> existing.kind
           OR stored_spec.spec_hash <> p_successor_spec_hash
           OR stored_spec.spec_payload IS DISTINCT FROM p_successor_spec_payload THEN
            RAISE EXCEPTION 'Workflow C alert successor immutable Job spec differs'
                USING ERRCODE = '23505';
        END IF;
        successor_exists := true;
    END IF;
    IF NOT successor_exists THEN
        INSERT INTO durable_jobs(
            id, project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, parent_job_id, replay_nonce, created_at, updated_at
        ) VALUES (
            p_successor_job_id, p_project_id, 'workflow_c.alert.schedule', 'queued', 5,
            p_successor_spec_hash, p_successor_idempotency_key, 3, p_next_run_at,
            p_job_id, 0, clock_timestamp(), clock_timestamp()
        );
        INSERT INTO workflow_c_job_specs(
            project_id, job_id, kind, spec_hash, spec_payload, created_at
        ) VALUES (
            p_project_id, p_successor_job_id, 'workflow_c.alert.schedule',
            p_successor_spec_hash, p_successor_spec_payload, clock_timestamp()
        );
        INSERT INTO broker_outbox(
            id, project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            gen_random_uuid(), p_project_id, p_successor_job_id, 'workflow_c.alert.schedule',
            jsonb_build_object('job_id', p_successor_job_id::text, 'project_id', p_project_id::text),
            'wake:workflow_c.alert.schedule:' || p_successor_job_id::text, p_next_run_at
        );
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
        ) VALUES (
            p_project_id, p_successor_job_id, 'job_enqueued', 'workflow-c-alert-schedule', 0,
            jsonb_build_object('parent_job_id', p_job_id::text), clock_timestamp()
        );
    END IF;
    UPDATE workflow_c_alert_schedules
    SET next_run_at = p_next_run_at, updated_at = clock_timestamp()
    WHERE project_id = p_project_id AND id = p_schedule_id
      AND version = p_expected_schedule_version AND next_run_at = p_scheduled_for;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C alert schedule changed during enqueue'
            USING ERRCODE = '40001';
    END IF;
    UPDATE durable_jobs
    SET status = 'succeeded', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, completed_at = clock_timestamp(), updated_at = clock_timestamp(),
        result_ref = 'workflow-c-alert-evaluation:' || p_evaluate_job_id::text,
        error_code = NULL, error_detail = NULL
    WHERE project_id = p_project_id AND id = p_job_id AND status = 'running'
      AND lease_token = p_lease_token AND fencing_generation = p_fencing_generation
      AND lease_expires_at > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C alert schedule Job was fenced during enqueue'
            USING ERRCODE = '40001';
    END IF;
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    ) VALUES (
        p_project_id, p_job_id, 'job_succeeded', 'workflow-c-alert-schedule',
        p_fencing_generation,
        jsonb_build_object('evaluation_job_id', p_evaluate_job_id::text,
                           'successor_job_id', p_successor_job_id::text),
        clock_timestamp()
    );
    RETURN QUERY SELECT 'scheduled', p_evaluate_job_id, p_successor_job_id;
END;
$$;

CREATE FUNCTION geo_complete_workflow_c_alert_evaluation(
    p_job_id uuid, p_project_id uuid, p_lease_token uuid,
    p_fencing_generation integer, p_evaluation_id uuid, p_schedule_id uuid,
    p_schedule_version integer, p_rule_version_id uuid, p_rule_hash text,
    p_input_hash text, p_evaluation_hash text, p_status text, p_matched boolean,
    p_evaluation_payload jsonb, p_evaluated_at timestamptz, p_alert_id uuid,
    p_alert_dedupe_key text, p_alert_payload jsonb, p_notification_payload jsonb
) RETURNS TABLE (status text, evaluation_hash text, notification_count integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE frozen_spec jsonb;
DECLARE schedule_row workflow_c_alert_schedules%ROWTYPE;
DECLARE rule_row workflow_c_alert_rule_versions%ROWTYPE;
DECLARE evaluation_row workflow_c_alert_evaluations%ROWTYPE;
DECLARE alert_row workflow_c_alerts%ROWTYPE;
DECLARE notification_row workflow_c_alert_notifications%ROWTYPE;
DECLARE notify_job durable_jobs%ROWTYPE;
DECLARE item jsonb;
DECLARE row_count integer := 0;
DECLARE alert_created boolean := false;
DECLARE effective_alert_id uuid;
BEGIN
    frozen_spec := geo_require_workflow_c_job_lease(
        p_project_id, p_job_id, p_lease_token, p_fencing_generation,
        'workflow_c.alert.evaluate'
    );
    IF p_evaluation_id IS NULL OR p_schedule_id IS NULL OR p_schedule_version < 1
       OR p_rule_version_id IS NULL OR p_rule_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_evaluation_hash !~ '^[0-9a-f]{64}$'
       OR p_status NOT IN ('matched', 'not_matched') OR p_matched IS NULL
       OR (p_status = 'matched') <> p_matched OR p_evaluated_at IS NULL
       OR jsonb_typeof(p_evaluation_payload) <> 'object'
       OR NOT geo_workflow_c_json_has_exact_keys(p_evaluation_payload, ARRAY[
           'schema_version', 'evaluator_version', 'rule', 'scope', 'input_hash',
           'matched', 'reason_codes', 'evidence', 'trigger_snapshot',
           'evaluation_hash', 'evaluated_at', 'schedule', 'rule_kind', 'rule_hash',
           'parameter_schema_version', 'input_schema_version', 'trigger_snapshot_hash'
       ])
       OR p_evaluation_payload->>'schema_version' <> 'workflow-c-alert-evaluation-v1'
       OR p_evaluation_payload->>'input_hash' <> p_input_hash
       OR p_evaluation_payload->>'evaluation_hash' <> p_evaluation_hash
       OR (p_evaluation_payload->>'matched')::boolean IS DISTINCT FROM p_matched
       OR p_evaluation_payload->'rule'->>'id' <> p_rule_version_id::text
       OR p_evaluation_payload->'rule'->>'rule_hash' <> p_rule_hash
       OR p_evaluation_payload->'schedule'->>'id' <> p_schedule_id::text
       OR (p_evaluation_payload->'schedule'->>'version')::integer <> p_schedule_version
       OR jsonb_typeof(p_evaluation_payload->'reason_codes') <> 'array'
       OR jsonb_typeof(p_evaluation_payload->'evidence') <> 'array'
       OR jsonb_typeof(p_evaluation_payload->'trigger_snapshot') NOT IN ('object', 'null')
       OR (p_evaluation_payload->>'evaluated_at')::timestamptz <> p_evaluated_at
       OR NOT geo_workflow_c_job_spec_payload_is_safe(p_evaluation_payload) THEN
        RAISE EXCEPTION 'Workflow C alert evaluation completion input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO schedule_row FROM workflow_c_alert_schedules
    WHERE project_id = p_project_id AND id = p_schedule_id FOR SHARE;
    SELECT * INTO rule_row FROM workflow_c_alert_rule_versions
    WHERE project_id = p_project_id AND id = p_rule_version_id FOR SHARE;
    IF schedule_row.id IS NULL OR rule_row.id IS NULL
       OR schedule_row.version <> p_schedule_version
       OR schedule_row.rule_version_id <> p_rule_version_id
       OR rule_row.rule_hash <> p_rule_hash OR rule_row.status <> 'approved'
       OR frozen_spec->>'schedule_id' <> p_schedule_id::text
       OR (frozen_spec->>'schedule_version')::integer <> p_schedule_version
       OR frozen_spec->'rule'->>'id' <> p_rule_version_id::text
       OR frozen_spec->'rule'->>'rule_hash' <> p_rule_hash THEN
        RAISE EXCEPTION 'Workflow C alert evaluation scope or frozen rule was fenced'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO evaluation_row FROM workflow_c_alert_evaluations
    WHERE project_id = p_project_id
      AND (job_id = p_job_id OR evaluation_hash = p_evaluation_hash) FOR SHARE;
    IF FOUND THEN
        IF evaluation_row.id <> p_evaluation_id OR evaluation_row.job_id <> p_job_id
           OR evaluation_row.schedule_id <> p_schedule_id
           OR evaluation_row.schedule_version <> p_schedule_version
           OR evaluation_row.rule_version_id <> p_rule_version_id
           OR evaluation_row.rule_hash <> p_rule_hash
           OR evaluation_row.input_hash <> p_input_hash
           OR evaluation_row.evaluation_hash <> p_evaluation_hash
           OR evaluation_row.status <> p_status OR evaluation_row.matched IS DISTINCT FROM p_matched
           OR evaluation_row.payload IS DISTINCT FROM p_evaluation_payload
           OR evaluation_row.evaluated_at <> p_evaluated_at THEN
            RAISE EXCEPTION 'Workflow C alert evaluation immutable result differs'
                USING ERRCODE = '23505';
        END IF;
        UPDATE durable_jobs
        SET status = 'succeeded', lease_owner = NULL, lease_token = NULL,
            lease_expires_at = NULL, completed_at = p_evaluated_at, updated_at = p_evaluated_at,
            result_ref = 'workflow-c-alert-evaluation:' || p_evaluation_id::text,
            error_code = NULL,
            error_detail = jsonb_build_object(
                'evaluation_id', p_evaluation_id::text,
                'evaluation_hash', p_evaluation_hash,
                'status', p_status,
                'replayed', true
            )
        WHERE project_id = p_project_id AND id = p_job_id AND status = 'running'
          AND lease_token = p_lease_token AND fencing_generation = p_fencing_generation
          AND lease_expires_at > clock_timestamp();
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Workflow C alert evaluation replay Job was fenced'
                USING ERRCODE = '40001';
        END IF;
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
        ) VALUES (
            p_project_id, p_job_id, 'job_succeeded', 'workflow-c-alert-evaluate',
            p_fencing_generation,
            jsonb_build_object('evaluation_id', p_evaluation_id::text,
                               'evaluation_hash', p_evaluation_hash,
                               'status', p_status, 'replayed', true),
            p_evaluated_at
        );
        RETURN QUERY SELECT evaluation_row.status, evaluation_row.evaluation_hash, 0;
        RETURN;
    END IF;
    INSERT INTO workflow_c_alert_evaluations(
        id, project_id, job_id, schedule_id, schedule_version, rule_version_id,
        rule_hash, input_hash, evaluation_hash, status, matched, payload, evaluated_at
    ) VALUES (
        p_evaluation_id, p_project_id, p_job_id, p_schedule_id, p_schedule_version,
        p_rule_version_id, p_rule_hash, p_input_hash, p_evaluation_hash, p_status,
        p_matched, p_evaluation_payload, p_evaluated_at
    );
    IF p_status = 'not_matched' THEN
        IF p_alert_id IS NOT NULL OR p_alert_dedupe_key IS NOT NULL
           OR p_alert_payload IS NOT NULL OR p_notification_payload IS DISTINCT FROM '[]'::jsonb THEN
            RAISE EXCEPTION 'Workflow C non-match cannot open an alert or notification'
                USING ERRCODE = '22023';
        END IF;
    ELSE
        IF p_alert_id IS NULL OR p_alert_dedupe_key !~ '^alert:[0-9a-f]{64}$'
           OR jsonb_typeof(p_alert_payload) <> 'object'
           OR NOT geo_workflow_c_json_has_exact_keys(p_alert_payload, ARRAY[
               'schema_version', 'rule', 'scope', 'trigger_snapshot', 'evidence'
           ])
           OR p_alert_payload->>'schema_version' <> 'workflow-c-alert-v1'
           OR p_alert_payload->'rule'->>'id' <> p_rule_version_id::text
           OR p_alert_payload->'rule'->>'rule_hash' <> p_rule_hash
           OR p_alert_payload->'rule'->>'severity' NOT IN ('info', 'warning', 'critical')
           OR p_alert_payload->'scope'->>'project_id' <> p_project_id::text
           OR jsonb_typeof(p_alert_payload->'trigger_snapshot') <> 'object'
           OR p_alert_payload->'trigger_snapshot'->>'snapshot_hash' !~ '^[0-9a-f]{64}$'
           OR p_evaluation_payload->'trigger_snapshot'->>'snapshot_hash'
              <> p_alert_payload->'trigger_snapshot'->>'snapshot_hash'
           OR jsonb_typeof(p_alert_payload->'evidence') <> 'array'
           OR jsonb_typeof(p_notification_payload) <> 'array'
           OR NOT geo_workflow_c_job_spec_payload_is_safe(p_alert_payload)
           OR NOT geo_workflow_c_job_spec_payload_is_safe(p_notification_payload) THEN
            RAISE EXCEPTION 'Workflow C matched alert completion input is invalid'
                USING ERRCODE = '22023';
        END IF;
        SELECT * INTO alert_row FROM workflow_c_alerts
        WHERE project_id = p_project_id AND dedupe_key = p_alert_dedupe_key
          AND status <> 'resolved' FOR SHARE;
        IF FOUND THEN
            IF alert_row.rule_version_id <> p_rule_version_id
               OR alert_row.dedupe_key <> p_alert_dedupe_key THEN
                RAISE EXCEPTION 'Workflow C active alert dedupe collision differs'
                    USING ERRCODE = '23505';
            END IF;
            effective_alert_id := alert_row.id;
        ELSE
            INSERT INTO workflow_c_alerts(
                id, project_id, rule_version_id, trigger_snapshot_hash, dedupe_key,
                severity, status, version, payload, opened_at, updated_at
            ) VALUES (
                p_alert_id, p_project_id, p_rule_version_id,
                p_alert_payload->'trigger_snapshot'->>'snapshot_hash', p_alert_dedupe_key,
                p_alert_payload->'rule'->>'severity', 'open', 1, p_alert_payload,
                p_evaluated_at, p_evaluated_at
            ) ON CONFLICT (project_id, dedupe_key) WHERE status <> 'resolved' DO NOTHING;
            SELECT * INTO alert_row FROM workflow_c_alerts
            WHERE project_id = p_project_id AND dedupe_key = p_alert_dedupe_key
              AND status <> 'resolved' FOR SHARE;
            IF alert_row.id IS NULL OR alert_row.rule_version_id <> p_rule_version_id THEN
                RAISE EXCEPTION 'Workflow C alert creation was fenced'
                    USING ERRCODE = '40001';
            END IF;
            effective_alert_id := alert_row.id;
            alert_created := effective_alert_id = p_alert_id;
        END IF;
        IF alert_created THEN
            IF jsonb_array_length(p_notification_payload) <> 3
               OR (SELECT count(DISTINCT value->>'channel')
                   FROM jsonb_array_elements(p_notification_payload) AS value) <> 3 THEN
                RAISE EXCEPTION 'Workflow C opened alert requires one notification per channel'
                    USING ERRCODE = '22023';
            END IF;
            FOR item IN SELECT value FROM jsonb_array_elements(p_notification_payload)
            LOOP
                IF NOT geo_workflow_c_json_has_exact_keys(item, ARRAY[
                    'id', 'alert_id', 'alert_version', 'channel', 'topic',
                    'idempotency_key', 'payload_hash', 'payload', 'safe_summary',
                    'created_at', 'notify_job_id', 'notify_spec_hash', 'notify_spec_payload'
                ])
                   OR NOT geo_workflow_c_json_is_uuid(item->'id')
                   OR item->>'alert_id' <> effective_alert_id::text
                   OR (item->>'alert_version')::integer <> 1
                   OR item->>'channel' NOT IN ('admin_inbox', 'local_smtp', 'internal_webhook')
                   OR btrim(coalesce(item->>'topic', '')) = ''
                   OR btrim(coalesce(item->>'idempotency_key', '')) = ''
                   OR NOT geo_workflow_c_json_is_sha256(item->'payload_hash')
                   OR NOT geo_workflow_c_json_has_exact_keys(item->'payload', ARRAY['summary'])
                   OR jsonb_typeof(item->'payload'->'summary') <> 'object'
                   OR btrim(coalesce(item->>'safe_summary', '')) = ''
                   OR length(item->>'safe_summary') > 1000
                   OR NOT geo_workflow_c_json_is_rfc3339(item->'created_at')
                   OR (item->>'created_at')::timestamptz <> p_evaluated_at
                   OR NOT geo_workflow_c_json_is_uuid(item->'notify_job_id')
                   OR NOT geo_workflow_c_json_is_sha256(item->'notify_spec_hash')
                   OR NOT geo_workflow_c_json_has_exact_keys(item->'notify_spec_payload', ARRAY[
                       'schema_version', 'kind', 'notification_id'
                   ])
                   OR item->'notify_spec_payload'->'schema_version' <> '1'::jsonb
                   OR item->'notify_spec_payload'->>'kind' <> 'workflow_c.alert.notify'
                   OR item->'notify_spec_payload'->>'notification_id' <> item->>'id'
                   OR encode(digest(convert_to(
                       geo_jsonb_canonical_text(item->'notify_spec_payload'), 'UTF8'
                   ), 'sha256'), 'hex') <> item->>'notify_spec_hash'
                   OR NOT geo_workflow_c_job_spec_payload_is_safe(item) THEN
                    RAISE EXCEPTION 'Workflow C alert notification payload is invalid'
                        USING ERRCODE = '22023';
                END IF;
                SELECT * INTO notification_row FROM workflow_c_alert_notifications
                WHERE project_id = p_project_id
                  AND (id = (item->>'id')::uuid
                       OR idempotency_key = item->>'idempotency_key') FOR SHARE;
                IF FOUND THEN
                    RAISE EXCEPTION 'Workflow C alert notification already exists'
                        USING ERRCODE = '23505';
                END IF;
                INSERT INTO workflow_c_alert_notifications(
                    id, project_id, alert_id, alert_version, channel, topic, idempotency_key,
                    status, payload_hash, payload, safe_summary, attempt_count,
                    next_attempt_at, created_at
                ) VALUES (
                    (item->>'id')::uuid, p_project_id, effective_alert_id, 1,
                    item->>'channel', item->>'topic', item->>'idempotency_key',
                    'pending', item->>'payload_hash', item->'payload', item->>'safe_summary',
                    0, p_evaluated_at, p_evaluated_at
                );
                SELECT * INTO notify_job FROM durable_jobs
                WHERE project_id = p_project_id AND (
                    id = (item->>'notify_job_id')::uuid OR (
                        kind = 'workflow_c.alert.notify'
                        AND idempotency_key = 'workflow-c-alert-notify:' || item->>'idempotency_key'
                        AND replay_nonce = 0
                    )
                ) FOR SHARE;
                IF FOUND THEN
                    RAISE EXCEPTION 'Workflow C alert notification Job already exists'
                        USING ERRCODE = '23505';
                END IF;
                INSERT INTO durable_jobs(
                    id, project_id, kind, status, priority, input_hash, idempotency_key,
                    max_attempts, next_run_at, parent_job_id, replay_nonce, created_at, updated_at
                ) VALUES (
                    (item->>'notify_job_id')::uuid, p_project_id, 'workflow_c.alert.notify',
                    'queued', 5, item->>'notify_spec_hash',
                    'workflow-c-alert-notify:' || item->>'idempotency_key', 3,
                    p_evaluated_at, p_job_id, 0, p_evaluated_at, p_evaluated_at
                );
                INSERT INTO workflow_c_job_specs(
                    project_id, job_id, kind, spec_hash, spec_payload, created_at
                ) VALUES (
                    p_project_id, (item->>'notify_job_id')::uuid, 'workflow_c.alert.notify',
                    item->>'notify_spec_hash', item->'notify_spec_payload', p_evaluated_at
                );
                INSERT INTO broker_outbox(
                    id, project_id, job_id, topic, payload, idempotency_key, available_at
                ) VALUES (
                    gen_random_uuid(), p_project_id, (item->>'notify_job_id')::uuid,
                    'workflow_c.alert.notify',
                    jsonb_build_object('job_id', item->>'notify_job_id',
                                       'project_id', p_project_id::text),
                    'wake:workflow_c.alert.notify:' || item->>'notify_job_id', p_evaluated_at
                );
                INSERT INTO durable_job_events(
                    project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
                ) VALUES (
                    p_project_id, (item->>'notify_job_id')::uuid, 'job_enqueued',
                    'workflow-c-alert-evaluate', 0,
                    jsonb_build_object('alert_id', effective_alert_id::text), p_evaluated_at
                );
                row_count := row_count + 1;
            END LOOP;
        END IF;
    END IF;
    UPDATE durable_jobs
    SET status = 'succeeded', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, completed_at = p_evaluated_at, updated_at = p_evaluated_at,
        result_ref = 'workflow-c-alert-evaluation:' || p_evaluation_id::text,
        error_code = NULL,
        error_detail = jsonb_build_object(
            'evaluation_id', p_evaluation_id::text,
            'evaluation_hash', p_evaluation_hash,
            'status', p_status,
            'alert_id', effective_alert_id::text
        )
    WHERE project_id = p_project_id AND id = p_job_id AND status = 'running'
      AND lease_token = p_lease_token AND fencing_generation = p_fencing_generation
      AND lease_expires_at > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C alert evaluation Job was fenced during completion'
            USING ERRCODE = '40001';
    END IF;
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    ) VALUES (
        p_project_id, p_job_id, 'job_succeeded', 'workflow-c-alert-evaluate',
        p_fencing_generation,
        jsonb_build_object('evaluation_id', p_evaluation_id::text,
                           'evaluation_hash', p_evaluation_hash, 'status', p_status,
                           'alert_id', effective_alert_id::text),
        p_evaluated_at
    );
    RETURN QUERY SELECT p_status, p_evaluation_hash, row_count;
END;
$$;

CREATE FUNCTION geo_complete_workflow_c_metric_child(
    p_project_id uuid,
    p_child_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_parent_input_hash text,
    p_role text,
    p_model_attempt_id uuid,
    p_output_hash text,
    p_selected_candidate_id uuid,
    p_selected_output_hash text
) RETURNS TABLE (
    child_status text,
    batch_status text,
    batch_id uuid,
    aggregate_version integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE child workflow_c_metric_model_children%ROWTYPE;
DECLARE batch workflow_c_metric_judge_batches%ROWTYPE;
DECLARE job durable_jobs%ROWTYPE;
DECLARE expected_kind text;
DECLARE judge_count integer;
DECLARE judge_output_count integer;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_child_job_id IS NULL OR p_lease_token IS NULL OR p_fencing_generation < 1
       OR p_parent_input_hash !~ '^[0-9a-f]{64}$'
       OR p_role NOT IN ('metric_judge', 'arbiter')
       OR p_model_attempt_id IS NULL OR p_output_hash !~ '^[0-9a-f]{64}$'
       OR (p_role = 'metric_judge' AND (
           p_selected_candidate_id IS NOT NULL OR p_selected_output_hash IS NOT NULL
       ))
       OR (p_role = 'arbiter' AND (
           p_selected_candidate_id IS NULL OR p_selected_output_hash !~ '^[0-9a-f]{64}$'
       )) THEN
        RAISE EXCEPTION 'Workflow C metric child completion input is invalid'
            USING ERRCODE = '22023';
    END IF;
    expected_kind := CASE p_role
        WHEN 'metric_judge' THEN 'workflow_c.metric_judge'
        ELSE 'workflow_c.metric_arbiter'
    END;
    SELECT * INTO child FROM workflow_c_metric_model_children
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id FOR UPDATE;
    SELECT * INTO job FROM durable_jobs
    WHERE project_id = p_project_id AND id = p_child_job_id FOR SHARE;
    IF child.child_job_id IS NULL OR job.id IS NULL
       OR child.role <> p_role OR child.parent_input_hash <> p_parent_input_hash
       OR child.status NOT IN ('queued', 'running')
       OR job.kind <> expected_kind OR job.input_hash <> child.task_hash
       OR job.status <> 'running' OR job.lease_token IS DISTINCT FROM p_lease_token
       OR job.fencing_generation <> p_fencing_generation
       OR job.lease_expires_at IS NULL OR job.lease_expires_at <= clock_timestamp()
       OR job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C metric child completion was fenced'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO batch FROM workflow_c_metric_judge_batches
    WHERE project_id = p_project_id AND id = child.batch_id FOR UPDATE;
    IF batch.id IS NULL OR batch.parent_job_id <> child.parent_job_id
       OR batch.parent_input_hash <> p_parent_input_hash
       OR batch.status NOT IN ('queued', 'running') THEN
        RAISE EXCEPTION 'Workflow C metric batch completion was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF p_role = 'arbiter' THEN
        SELECT count(*), count(DISTINCT output_hash)
        INTO judge_count, judge_output_count
        FROM workflow_c_metric_model_children
        WHERE project_id = p_project_id AND batch_id = child.batch_id
          AND role = 'metric_judge' AND status = 'succeeded' AND output_hash IS NOT NULL;
        IF judge_count < 2 OR judge_output_count < 2
           OR EXISTS (
               SELECT 1 FROM workflow_c_metric_model_children AS judge
               WHERE judge.project_id = p_project_id AND judge.batch_id = child.batch_id
                 AND judge.role = 'metric_judge'
                 AND (judge.status <> 'succeeded' OR judge.output_hash IS NULL)
           )
           OR NOT EXISTS (
               SELECT 1 FROM workflow_c_metric_model_children AS judge
               WHERE judge.project_id = p_project_id AND judge.batch_id = child.batch_id
                 AND judge.role = 'metric_judge'
                 AND judge.candidate_id = p_selected_candidate_id
                 AND judge.output_hash = p_selected_output_hash
                 AND judge.status = 'succeeded'
           ) THEN
            RAISE EXCEPTION 'Workflow C metric arbiter candidates are incomplete or inconsistent'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    UPDATE workflow_c_metric_model_children
    SET status = 'succeeded', model_attempt_id = p_model_attempt_id,
        output_hash = p_output_hash, error_code = NULL, completed_at = clock_timestamp()
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id
      AND status IN ('queued', 'running');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C metric child state changed during completion'
            USING ERRCODE = '40001';
    END IF;
    IF p_role = 'arbiter' THEN
        UPDATE workflow_c_metric_judge_batches
        SET status = 'completed', selected_candidate_id = p_selected_candidate_id,
            selected_output_hash = p_selected_output_hash,
            aggregate_version = aggregate_version + 1, completed_at = clock_timestamp()
        WHERE project_id = p_project_id AND id = child.batch_id
          AND status IN ('queued', 'running');
    ELSE
        UPDATE workflow_c_metric_judge_batches
        SET status = 'running', aggregate_version = aggregate_version + 1
        WHERE project_id = p_project_id AND id = child.batch_id
          AND status IN ('queued', 'running');
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C metric batch state changed during completion'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO child FROM workflow_c_metric_model_children
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id;
    SELECT * INTO batch FROM workflow_c_metric_judge_batches
    WHERE project_id = p_project_id AND id = child.batch_id;
    RETURN QUERY SELECT child.status, batch.status, batch.id, batch.aggregate_version;
END;
$$;

CREATE FUNCTION geo_fail_workflow_c_metric_child(
    p_project_id uuid,
    p_child_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_parent_input_hash text,
    p_role text,
    p_error_code text
) RETURNS TABLE (
    child_status text,
    batch_status text,
    batch_id uuid,
    aggregate_version integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE child workflow_c_metric_model_children%ROWTYPE;
DECLARE batch workflow_c_metric_judge_batches%ROWTYPE;
DECLARE job durable_jobs%ROWTYPE;
DECLARE expected_kind text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_child_job_id IS NULL OR p_lease_token IS NULL OR p_fencing_generation < 1
       OR p_parent_input_hash !~ '^[0-9a-f]{64}$'
       OR p_role NOT IN ('metric_judge', 'arbiter')
       OR p_error_code !~ '^[a-z][a-z0-9_.:-]{0,99}$' THEN
        RAISE EXCEPTION 'Workflow C metric child failure input is invalid'
            USING ERRCODE = '22023';
    END IF;
    expected_kind := CASE p_role
        WHEN 'metric_judge' THEN 'workflow_c.metric_judge'
        ELSE 'workflow_c.metric_arbiter'
    END;
    SELECT * INTO child FROM workflow_c_metric_model_children
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id FOR UPDATE;
    SELECT * INTO job FROM durable_jobs
    WHERE project_id = p_project_id AND id = p_child_job_id FOR SHARE;
    IF child.child_job_id IS NULL OR job.id IS NULL
       OR child.role <> p_role OR child.parent_input_hash <> p_parent_input_hash
       OR child.status NOT IN ('queued', 'running')
       OR job.kind <> expected_kind OR job.input_hash <> child.task_hash
       OR job.status <> 'running' OR job.lease_token IS DISTINCT FROM p_lease_token
       OR job.fencing_generation <> p_fencing_generation
       OR job.lease_expires_at IS NULL OR job.lease_expires_at <= clock_timestamp()
       OR job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C metric child failure was fenced'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO batch FROM workflow_c_metric_judge_batches
    WHERE project_id = p_project_id AND id = child.batch_id FOR UPDATE;
    IF batch.id IS NULL OR batch.parent_job_id <> child.parent_job_id
       OR batch.parent_input_hash <> p_parent_input_hash
       OR batch.status NOT IN ('queued', 'running') THEN
        RAISE EXCEPTION 'Workflow C metric batch failure was fenced'
            USING ERRCODE = '40001';
    END IF;
    UPDATE workflow_c_metric_model_children
    SET status = 'failed', error_code = p_error_code, completed_at = clock_timestamp()
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id
      AND status IN ('queued', 'running');
    UPDATE workflow_c_metric_judge_batches
    SET status = 'failed', aggregate_version = aggregate_version + 1,
        completed_at = clock_timestamp()
    WHERE project_id = p_project_id AND id = child.batch_id
      AND status IN ('queued', 'running');
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C metric batch state changed during failure'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO child FROM workflow_c_metric_model_children
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id;
    SELECT * INTO batch FROM workflow_c_metric_judge_batches
    WHERE project_id = p_project_id AND id = child.batch_id;
    RETURN QUERY SELECT child.status, batch.status, batch.id, batch.aggregate_version;
END;
$$;

-- The original maintenance RPCs were global despite the scheduler creating a
-- separate Durable Job per Project.  New overloads require the caller's
-- transaction-local Project scope; legacy global entry points are revoked at
-- the bottom of this migration and restored only on downgrade.
CREATE FUNCTION geo_stage_due_synthetic_artifact_expirations(
    p_project_id uuid,
    p_now timestamptz,
    p_limit integer
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate record;
DECLARE changed integer := 0;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_now IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'invalid or out-of-scope Synthetic artifact expiry sweep input'
            USING ERRCODE = '22023';
    END IF;
    FOR candidate IN
        SELECT artifact.*
        FROM synthetic_lab_raw_artifacts AS artifact
        WHERE artifact.project_id = p_project_id
          AND artifact.lifecycle_state IN ('winning', 'orphaned')
          AND artifact.expires_at IS NOT NULL AND artifact.expires_at <= p_now
          AND NOT EXISTS (
              SELECT 1
              FROM synthetic_lab_artifact_legal_holds AS hold
              WHERE hold.project_id = artifact.project_id
                AND hold.artifact_id = artifact.artifact_id
                AND hold.artifact_generation = artifact.fencing_generation
                AND hold.approved_at <= p_now AND hold.expires_at > p_now
          )
        ORDER BY artifact.expires_at, artifact.artifact_id, artifact.fencing_generation
        FOR UPDATE SKIP LOCKED
        LIMIT p_limit
    LOOP
        UPDATE synthetic_lab_raw_artifacts AS target
        SET lifecycle_state = 'deletion_pending', deletion_pending_at = p_now,
            record_version = target.record_version + 1
        WHERE target.project_id = candidate.project_id
          AND target.artifact_id = candidate.artifact_id
          AND target.fencing_generation = candidate.fencing_generation;
        INSERT INTO synthetic_lab_artifact_deletion_outbox(
            id, project_id, artifact_id, artifact_generation, manifest_hash,
            reason, status, next_attempt_at
        ) VALUES (
            gen_random_uuid(), candidate.project_id, candidate.artifact_id,
            candidate.fencing_generation, candidate.manifest_hash,
            'retention_expired', 'pending', p_now
        ) ON CONFLICT (project_id, artifact_id, artifact_generation)
            WHERE status IN ('pending', 'leased', 'failed') DO NOTHING;
        changed := changed + 1;
    END LOOP;
    RETURN changed;
END;
$$;

CREATE FUNCTION geo_claim_synthetic_artifact_deletions(
    p_project_id uuid,
    p_worker_id text,
    p_now timestamptz,
    p_batch_size integer,
    p_lease_seconds integer
) RETURNS TABLE (
    outbox_id uuid,
    project_id uuid,
    artifact_id uuid,
    artifact_generation bigint,
    lease_token uuid,
    deletion_fencing_generation bigint,
    lease_expires_at timestamptz,
    payload_uri text,
    manifest_uri text,
    storage_tier text,
    content_hash text,
    manifest_hash text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_now IS NULL OR btrim(coalesce(p_worker_id, '')) = ''
       OR octet_length(p_worker_id) > 240 OR p_batch_size NOT BETWEEN 1 AND 100
       OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'invalid or out-of-scope Synthetic artifact deletion claim input'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH candidates AS (
        SELECT item.id
        FROM synthetic_lab_artifact_deletion_outbox AS item
        JOIN synthetic_lab_raw_artifacts AS artifact
          ON artifact.project_id = item.project_id
         AND artifact.artifact_id = item.artifact_id
         AND artifact.fencing_generation = item.artifact_generation
        WHERE item.project_id = p_project_id
          AND ((item.status IN ('pending', 'failed') AND item.next_attempt_at <= p_now)
               OR (item.status = 'leased' AND item.lease_expires_at <= p_now))
          AND artifact.lifecycle_state IN ('deletion_pending', 'object_delete_pending')
          AND (
              artifact.lifecycle_state = 'object_delete_pending'
              OR NOT EXISTS (
                  SELECT 1
                  FROM synthetic_lab_artifact_legal_holds AS hold
                  WHERE hold.project_id = artifact.project_id
                    AND hold.artifact_id = artifact.artifact_id
                    AND hold.artifact_generation = artifact.fencing_generation
                    AND hold.approved_at <= p_now AND hold.expires_at > p_now
              )
          )
        ORDER BY item.next_attempt_at, item.id
        FOR UPDATE OF item SKIP LOCKED
        LIMIT p_batch_size
    ), claimed AS (
        UPDATE synthetic_lab_artifact_deletion_outbox AS item
        SET status = 'leased', lease_owner = p_worker_id,
            lease_token = gen_random_uuid(),
            lease_expires_at = p_now + make_interval(secs => p_lease_seconds),
            attempt_count = item.attempt_count + 1,
            fencing_generation = item.fencing_generation + 1,
            last_error_code = NULL
        FROM candidates
        WHERE item.id = candidates.id
        RETURNING item.*
    )
    SELECT claimed.id, claimed.project_id, claimed.artifact_id,
           claimed.artifact_generation, claimed.lease_token,
           claimed.fencing_generation, claimed.lease_expires_at,
           artifact.payload_uri, artifact.manifest_uri, artifact.storage_tier,
           artifact.persisted_content_hash, claimed.manifest_hash
    FROM claimed
    JOIN synthetic_lab_raw_artifacts AS artifact
      ON artifact.project_id = claimed.project_id
     AND artifact.artifact_id = claimed.artifact_id
     AND artifact.fencing_generation = claimed.artifact_generation
    ORDER BY claimed.next_attempt_at, claimed.id;
END;
$$;

-- The initial Workflow C migration used transport labels instead of the
-- frozen domain/API channel vocabulary.  Existing rows are translated while
-- the old constraint is absent under this transaction-level table lock.
ALTER TABLE workflow_c_alert_notifications
DROP CONSTRAINT workflow_c_alert_notifications_channel_check;
UPDATE workflow_c_alert_notifications
SET channel = CASE channel
    WHEN 'smtp' THEN 'local_smtp'
    WHEN 'webhook' THEN 'internal_webhook'
    ELSE channel
END
WHERE channel IN ('smtp', 'webhook');
ALTER TABLE workflow_c_alert_notifications
ADD CONSTRAINT workflow_c_alert_notifications_channel_check CHECK (
    channel IN ('admin_inbox', 'local_smtp', 'internal_webhook')
);

-- A retry schedule without the preceding attempt time is not auditable.  We
-- refuse to invent timestamps for pre-0032 terminal/retry notifications.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM workflow_c_alert_notifications
        WHERE status <> 'pending'
    ) THEN
        RAISE EXCEPTION
            'cannot add alert attempt provenance: reconcile non-pending notification rows first'
            USING ERRCODE = '55000';
    END IF;
END;
$$;
ALTER TABLE workflow_c_alert_notifications
ADD COLUMN last_attempt_at timestamptz,
ADD CONSTRAINT workflow_c_alert_notifications_pending_attempt_check CHECK (
    status <> 'pending' OR (attempt_count = 0 AND last_attempt_at IS NULL)
),
ADD CONSTRAINT workflow_c_alert_notifications_terminal_attempt_check CHECK (
    status NOT IN ('retry_wait', 'dead_lettered', 'delivered')
    OR (attempt_count >= 1 AND last_attempt_at IS NOT NULL)
),
ADD CONSTRAINT workflow_c_alert_notifications_retry_after_attempt_check CHECK (
    status <> 'retry_wait' OR next_attempt_at > last_attempt_at
);
GRANT UPDATE (
    status, attempt_count, last_attempt_at, next_attempt_at,
    lease_owner, lease_token, lease_expires_at, fencing_generation,
    delivered_at, last_error_code
) ON workflow_c_alert_notifications TO geo_worker;

CREATE TABLE recommendation_workflow_versions (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    recommendation_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    status text NOT NULL CHECK (status IN (
        'draft', 'in_review', 'approved', 'rejected', 'stale', 'expired'
    )),
    recommendation_type text NOT NULL CHECK (recommendation_type IN (
        'hard_blocker', 'gap', 'experiment', 'optional', 'no_change',
        'insufficient_evidence'
    )),
    proposed_draft_kind text CHECK (proposed_draft_kind IN (
        'experiment_plan', 'question_set', 'content_brief', 'sampling_plan'
    )),
    evidence_graph_hash text NOT NULL CHECK (evidence_graph_hash ~ '^[0-9a-f]{64}$'),
    input_fingerprint text NOT NULL CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    valid_until timestamptz NOT NULL,
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    workflow_payload jsonb NOT NULL CHECK (jsonb_typeof(workflow_payload) = 'object'),
    workflow_payload_hash text NOT NULL CHECK (
        workflow_payload_hash ~ '^[0-9a-f]{64}$'
    ),
    PRIMARY KEY (project_id, recommendation_id, version),
    UNIQUE (recommendation_id, project_id, version),
    CHECK (created_at <= updated_at),
    CHECK (
        (recommendation_type IN ('no_change', 'insufficient_evidence')
            AND proposed_draft_kind IS NULL)
        OR recommendation_type NOT IN ('no_change', 'insufficient_evidence')
    )
);

CREATE TABLE recommendation_evidence_bindings (
    project_id uuid NOT NULL,
    recommendation_id uuid NOT NULL,
    recommendation_version integer NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    evidence_kind text NOT NULL CHECK (evidence_kind IN (
        'observation', 'metric_comparison', 'fact', 'rule', 'prompt_release',
        'model_call', 'content', 'question', 'surface'
    )),
    resource_id text NOT NULL CHECK (btrim(resource_id) <> ''),
    resource_version text NOT NULL CHECK (btrim(resource_version) <> ''),
    resource_hash text NOT NULL CHECK (resource_hash ~ '^[0-9a-f]{64}$'),
    locator jsonb NOT NULL CHECK (jsonb_typeof(locator) = 'object'),
    input_versions jsonb NOT NULL CHECK (jsonb_typeof(input_versions) = 'array'),
    PRIMARY KEY (project_id, recommendation_id, recommendation_version, ordinal),
    FOREIGN KEY (project_id, recommendation_id, recommendation_version)
        REFERENCES recommendation_workflow_versions(project_id, recommendation_id, version)
        ON DELETE CASCADE
);

CREATE TABLE recommendation_approvals (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    recommendation_id uuid NOT NULL,
    recommendation_version integer NOT NULL,
    approved_by uuid NOT NULL REFERENCES identities(id),
    approved_at timestamptz NOT NULL,
    frozen_input_versions jsonb NOT NULL CHECK (jsonb_typeof(frozen_input_versions) = 'array'),
    frozen_input_fingerprint text NOT NULL CHECK (
        frozen_input_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    frozen_evidence_graph_hash text NOT NULL CHECK (
        frozen_evidence_graph_hash ~ '^[0-9a-f]{64}$'
    ),
    valid_until timestamptz NOT NULL,
    UNIQUE (project_id, recommendation_id, recommendation_version),
    UNIQUE (id, project_id, recommendation_id, recommendation_version),
    FOREIGN KEY (project_id, recommendation_id, recommendation_version)
        REFERENCES recommendation_workflow_versions(project_id, recommendation_id, version)
        ON DELETE CASCADE,
    CHECK (valid_until > approved_at)
);

CREATE TABLE recommendation_reviews (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    recommendation_id uuid NOT NULL,
    recommendation_version integer NOT NULL,
    evidence_graph_hash text NOT NULL CHECK (evidence_graph_hash ~ '^[0-9a-f]{64}$'),
    reviewed_by uuid NOT NULL REFERENCES identities(id),
    notes text NOT NULL CHECK (btrim(notes) <> ''),
    reviewed_at timestamptz NOT NULL,
    UNIQUE (project_id, recommendation_id, recommendation_version, reviewed_by),
    FOREIGN KEY (project_id, recommendation_id, recommendation_version)
        REFERENCES recommendation_workflow_versions(project_id, recommendation_id, version)
        ON DELETE CASCADE
);

CREATE TABLE recommendation_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    operation text NOT NULL CHECK (operation IN (
        'create', 'submit', 'review', 'approve', 'reject', 'reconcile_stale',
        'expire', 'prepare_draft_action'
    )),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    result_kind text NOT NULL CHECK (btrim(result_kind) <> ''),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    result_payload_hash text NOT NULL CHECK (result_payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, idempotency_key_hash)
);

CREATE TABLE recommendation_drafts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    recommendation_id uuid NOT NULL,
    recommendation_version integer NOT NULL,
    approval_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN (
        'experiment_plan', 'question_set', 'content_brief', 'sampling_plan'
    )),
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    frozen_input_fingerprint text NOT NULL CHECK (
        frozen_input_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    frozen_evidence_graph_hash text NOT NULL CHECK (
        frozen_evidence_graph_hash ~ '^[0-9a-f]{64}$'
    ),
    source_valid_until timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN (
        'draft', 'started', 'blocked_source_stale', 'blocked_source_expired'
    )),
    draft_payload jsonb NOT NULL CHECK (jsonb_typeof(draft_payload) = 'object'),
    draft_payload_hash text NOT NULL CHECK (draft_payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    blocked_at timestamptz,
    blocked_reason text,
    UNIQUE (id, project_id),
    UNIQUE (project_id, recommendation_id, recommendation_version, kind),
    UNIQUE (project_id, idempotency_key),
    FOREIGN KEY (approval_id, project_id, recommendation_id, recommendation_version)
        REFERENCES recommendation_approvals(id, project_id, recommendation_id, recommendation_version)
        ON DELETE CASCADE,
    CHECK (
        (status IN ('draft', 'started') AND blocked_at IS NULL AND blocked_reason IS NULL)
        OR (status IN ('blocked_source_stale', 'blocked_source_expired')
            AND blocked_at IS NOT NULL AND btrim(blocked_reason) <> '')
    )
);

CREATE TABLE recommendation_outbox_messages (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    recommendation_id uuid NOT NULL,
    recommendation_version integer NOT NULL,
    message_type text NOT NULL CHECK (btrim(message_type) <> ''),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('pending', 'delivered', 'cancelled')),
    delivered_at timestamptz,
    cancelled_at timestamptz,
    cancellation_reason text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, recommendation_id, recommendation_version, message_type, payload_hash),
    FOREIGN KEY (project_id, recommendation_id, recommendation_version)
        REFERENCES recommendation_workflow_versions(project_id, recommendation_id, version)
        ON DELETE CASCADE,
    CHECK ((status = 'delivered') = (delivered_at IS NOT NULL)),
    CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL)),
    CHECK (cancelled_at IS NULL OR btrim(cancellation_reason) <> '')
);

CREATE TABLE recommendation_generation_specs (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    api_version integer NOT NULL CHECK (api_version > 0),
    spec_payload jsonb NOT NULL CHECK (jsonb_typeof(spec_payload) = 'object'),
    spec_payload_hash text NOT NULL CHECK (spec_payload_hash ~ '^[0-9a-f]{64}$'),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    valid_until timestamptz NOT NULL,
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, job_id),
    UNIQUE (job_id, project_id),
    UNIQUE (project_id, idempotency_key_hash),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id)
        ON DELETE CASCADE
);

CREATE TABLE recommendation_generation_results (
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    recommendation_id uuid NOT NULL,
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, job_id),
    UNIQUE (project_id, recommendation_id),
    FOREIGN KEY (job_id, project_id) REFERENCES recommendation_generation_specs(job_id, project_id)
        ON DELETE CASCADE
);

CREATE TABLE recommendation_generation_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    operation text NOT NULL CHECK (operation IN ('enqueue', 'cancel')),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    result_payload_hash text NOT NULL CHECK (result_payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, idempotency_key_hash)
);

CREATE TABLE recommendation_model_tasks (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_job_id uuid NOT NULL,
    child_job_id uuid NOT NULL,
    parent_input_hash text NOT NULL CHECK (parent_input_hash ~ '^[0-9a-f]{64}$'),
    role text NOT NULL CHECK (role IN ('primary', 'arbiter')),
    runtime_selection_id uuid NOT NULL,
    runtime_manifest_id uuid NOT NULL,
    runtime_manifest_hash text NOT NULL CHECK (runtime_manifest_hash ~ '^[0-9a-f]{64}$'),
    runtime_option_id uuid NOT NULL,
    runtime_option_hash text NOT NULL CHECK (runtime_option_hash ~ '^[0-9a-f]{64}$'),
    prompt_binding_id uuid NOT NULL,
    prompt_binding_version integer NOT NULL CHECK (prompt_binding_version > 0),
    prompt_frozen_state_id uuid NOT NULL,
    prompt_state_version integer NOT NULL CHECK (prompt_state_version > 0),
    prompt_release_id uuid NOT NULL,
    prompt_release_version integer NOT NULL CHECK (prompt_release_version > 0),
    prompt_release_hash text NOT NULL CHECK (prompt_release_hash ~ '^[0-9a-f]{64}$'),
    prompt_purpose text NOT NULL CHECK (btrim(prompt_purpose) <> ''),
    provider text NOT NULL CHECK (btrim(provider) <> ''),
    adapter_release_id text NOT NULL CHECK (btrim(adapter_release_id) <> ''),
    adapter_release_hash text NOT NULL CHECK (adapter_release_hash ~ '^[0-9a-f]{64}$'),
    model_release_id text NOT NULL CHECK (btrim(model_release_id) <> ''),
    model_release_hash text NOT NULL CHECK (model_release_hash ~ '^[0-9a-f]{64}$'),
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    capture_method text NOT NULL CHECK (capture_method IN ('provider_api', 'proxy_grounded_api')),
    search_mode text,
    prompt_bundle_hash text NOT NULL CHECK (prompt_bundle_hash ~ '^[0-9a-f]{64}$'),
    structured_input_hash text NOT NULL CHECK (structured_input_hash ~ '^[0-9a-f]{64}$'),
    output_schema_hash text NOT NULL CHECK (output_schema_hash ~ '^[0-9a-f]{64}$'),
    application_output_schema_hash text NOT NULL CHECK (
        application_output_schema_hash ~ '^[0-9a-f]{64}$'
    ),
    task_artifact_uri text CHECK (task_artifact_uri ~ '^s3://[^/]+/.+'),
    task_artifact_manifest_hash text CHECK (
        task_artifact_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    task_artifact_payload_uri text CHECK (
        task_artifact_payload_uri ~ '^s3://[^/]+/.+'
    ),
    task_artifact_content_hash text CHECK (
        task_artifact_content_hash ~ '^[0-9a-f]{64}$'
    ),
    task_artifact_byte_size bigint CHECK (task_artifact_byte_size > 0),
    task_artifact_expires_at timestamptz NOT NULL,
    task_artifact_status text NOT NULL CHECK (task_artifact_status IN (
        'uploading', 'active', 'deletion_pending', 'crypto_erased', 'deleted'
    )),
    task_payload_hash text CHECK (task_payload_hash ~ '^[0-9a-f]{64}$'),
    admitted_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, child_job_id),
    UNIQUE (child_job_id, project_id),
    UNIQUE (project_id, parent_job_id, role),
    FOREIGN KEY (parent_job_id, project_id) REFERENCES durable_jobs(id, project_id)
        ON DELETE CASCADE,
    FOREIGN KEY (prompt_release_id, project_id, prompt_release_hash)
        REFERENCES prompt_program_releases(id, project_id, release_hash),
    FOREIGN KEY (runtime_manifest_id, project_id, runtime_manifest_hash)
        REFERENCES model_gateway_runtime_manifests(id, project_id, manifest_hash),
    FOREIGN KEY (runtime_option_id, project_id, runtime_manifest_id, runtime_option_hash)
        REFERENCES model_gateway_runtime_options(id, project_id, manifest_id, option_hash),
    CHECK (
        (task_artifact_status = 'uploading'
            AND task_artifact_uri IS NULL AND task_artifact_manifest_hash IS NULL
            AND task_artifact_payload_uri IS NULL AND task_artifact_content_hash IS NULL
            AND task_artifact_byte_size IS NULL AND task_payload_hash IS NULL)
        OR (task_artifact_status IN ('active', 'deletion_pending', 'crypto_erased', 'deleted')
            AND task_artifact_uri IS NOT NULL AND task_artifact_manifest_hash IS NOT NULL
            AND task_artifact_payload_uri IS NOT NULL AND task_artifact_content_hash IS NOT NULL
            AND task_artifact_byte_size IS NOT NULL AND task_payload_hash IS NOT NULL)
    )
);

CREATE TABLE recommendation_model_call_lineage (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_job_id uuid NOT NULL,
    child_job_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('primary', 'arbiter')),
    model_attempt_id uuid,
    model_call_log_id uuid,
    response_hash text,
    output_hash text,
    artifact_uri text,
    artifact_manifest_hash text,
    artifact_content_hash text,
    derived_artifact_uri text,
    derived_artifact_manifest_hash text,
    derived_artifact_content_hash text,
    task_artifact_status text NOT NULL CHECK (task_artifact_status IN (
        'uploading', 'active', 'deletion_pending', 'crypto_erased', 'deleted'
    )),
    task_artifact_expires_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN (
        'queued', 'running', 'retry_wait', 'succeeded', 'failed', 'dead_lettered', 'cancelled'
    )),
    error_code text,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, child_job_id),
    UNIQUE (project_id, parent_job_id, role),
    FOREIGN KEY (project_id, child_job_id)
        REFERENCES recommendation_model_tasks(project_id, child_job_id) ON DELETE CASCADE,
    CHECK ((status = 'succeeded') = (
        model_attempt_id IS NOT NULL AND model_call_log_id IS NOT NULL
        AND response_hash ~ '^[0-9a-f]{64}$' AND output_hash ~ '^[0-9a-f]{64}$'
        AND derived_artifact_uri ~ '^s3://[^/]+/.+'
        AND derived_artifact_manifest_hash ~ '^[0-9a-f]{64}$'
        AND derived_artifact_content_hash ~ '^[0-9a-f]{64}$'
    )),
    CHECK (status NOT IN ('failed', 'dead_lettered', 'cancelled') OR btrim(error_code) <> ''),
    CHECK (created_at <= updated_at)
);

CREATE TABLE recommendation_artifact_master_key_versions (
    master_key_version integer PRIMARY KEY CHECK (master_key_version > 0),
    status text NOT NULL CHECK (status IN ('encrypt_decrypt', 'decrypt_only', 'retired')),
    algorithm text NOT NULL CHECK (algorithm = 'AES-256-GCM'),
    canary_nonce bytea NOT NULL CHECK (octet_length(canary_nonce) = 12),
    canary_ciphertext bytea NOT NULL CHECK (octet_length(canary_ciphertext) > 16),
    created_at timestamptz NOT NULL,
    retired_at timestamptz,
    CHECK ((status = 'retired') = (retired_at IS NOT NULL)),
    CHECK (retired_at IS NULL OR retired_at >= created_at)
);
CREATE UNIQUE INDEX recommendation_artifact_one_encrypt_key
ON recommendation_artifact_master_key_versions(status)
WHERE status = 'encrypt_decrypt';

CREATE TABLE recommendation_artifact_deletion_intents (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_job_id uuid NOT NULL,
    child_job_id uuid NOT NULL,
    manifest_uri text NOT NULL CHECK (manifest_uri ~ '^s3://[^/]+/.+'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    payload_uri text NOT NULL CHECK (payload_uri ~ '^s3://[^/]+/.+'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz NOT NULL,
    phase text NOT NULL CHECK (phase IN ('deletion_pending', 'crypto_erased', 'deleted')),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    fencing_generation integer NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at timestamptz NOT NULL,
    crypto_erase_receipt_hash text,
    deleted_receipt_hash text,
    last_error_code text,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (project_id, child_job_id),
    FOREIGN KEY (project_id, child_job_id)
        REFERENCES recommendation_model_tasks(project_id, child_job_id) ON DELETE CASCADE,
    CHECK ((lease_token IS NULL) = (lease_owner IS NULL)),
    CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL)),
    CHECK (crypto_erase_receipt_hash IS NULL OR crypto_erase_receipt_hash ~ '^[0-9a-f]{64}$'),
    CHECK (deleted_receipt_hash IS NULL OR deleted_receipt_hash ~ '^[0-9a-f]{64}$'),
    CHECK (
        (phase = 'deletion_pending' AND crypto_erase_receipt_hash IS NULL
            AND deleted_receipt_hash IS NULL AND deleted_at IS NULL)
        OR (phase = 'crypto_erased' AND crypto_erase_receipt_hash IS NOT NULL
            AND deleted_receipt_hash IS NULL AND deleted_at IS NULL)
        OR (phase = 'deleted' AND crypto_erase_receipt_hash IS NOT NULL
            AND deleted_receipt_hash IS NOT NULL AND deleted_at IS NOT NULL)
    ),
    CHECK (created_at <= updated_at)
);
CREATE INDEX recommendation_artifact_deletion_claim_idx
ON recommendation_artifact_deletion_intents(phase, next_attempt_at, lease_expires_at, id)
WHERE phase IN ('deletion_pending', 'crypto_erased');

CREATE FUNCTION geo_assert_recommendation_workflow_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE previous recommendation_workflow_versions%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Recommendation workflow history is append-only'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO previous FROM recommendation_workflow_versions
    WHERE project_id = NEW.project_id AND recommendation_id = NEW.recommendation_id
    ORDER BY version DESC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        IF NEW.version <> 1 OR NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Recommendation must start as draft version one'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.version <> previous.version + 1
       OR NEW.created_by <> previous.created_by
       OR NEW.created_at <> previous.created_at THEN
        RAISE EXCEPTION 'Recommendation version lineage is not contiguous'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_recommendation_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE workflow recommendation_workflow_versions%ROWTYPE;
BEGIN
    SELECT * INTO STRICT workflow FROM recommendation_workflow_versions
    WHERE project_id = NEW.project_id AND recommendation_id = NEW.recommendation_id
      AND version = NEW.recommendation_version;
    IF workflow.status <> 'approved'
       OR workflow.created_by = NEW.approved_by
       OR workflow.evidence_graph_hash <> NEW.frozen_evidence_graph_hash
       OR workflow.input_fingerprint <> NEW.frozen_input_fingerprint
       OR NEW.approved_at < workflow.updated_at THEN
        RAISE EXCEPTION 'Recommendation approval violates maker-checker or frozen evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_recommendation_draft_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (
            SELECT 1 FROM recommendation_approvals AS approval
            WHERE approval.id = NEW.approval_id AND approval.project_id = NEW.project_id
              AND approval.recommendation_id = NEW.recommendation_id
              AND approval.recommendation_version = NEW.recommendation_version
              AND approval.frozen_input_fingerprint = NEW.frozen_input_fingerprint
              AND approval.frozen_evidence_graph_hash = NEW.frozen_evidence_graph_hash
              AND approval.valid_until = NEW.source_valid_until
        ) THEN
            RAISE EXCEPTION 'Recommendation draft requires an exact approved source'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation draft lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.project_id, OLD.recommendation_id, OLD.recommendation_version,
        OLD.approval_id, OLD.kind, OLD.idempotency_key, OLD.frozen_input_fingerprint,
        OLD.frozen_evidence_graph_hash, OLD.source_valid_until, OLD.created_at)
       IS DISTINCT FROM
       (NEW.project_id, NEW.recommendation_id, NEW.recommendation_version,
        NEW.approval_id, NEW.kind, NEW.idempotency_key, NEW.frozen_input_fingerprint,
        NEW.frozen_evidence_graph_hash, NEW.source_valid_until, NEW.created_at)
       OR OLD.status NOT IN ('draft', 'started')
       OR NEW.status NOT IN ('started', 'blocked_source_stale', 'blocked_source_expired') THEN
        RAISE EXCEPTION 'Recommendation draft lifecycle transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_block_recommendation_drafts_on_stale() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF NEW.status IN ('stale', 'expired') THEN
        UPDATE recommendation_drafts
        SET status = CASE NEW.status
                WHEN 'stale' THEN 'blocked_source_stale'
                ELSE 'blocked_source_expired' END,
            blocked_at = NEW.updated_at,
            blocked_reason = NEW.status,
            draft_payload = draft_payload,
            draft_payload_hash = draft_payload_hash
        WHERE project_id = NEW.project_id AND recommendation_id = NEW.recommendation_id
          AND status IN ('draft', 'started');
        UPDATE recommendation_outbox_messages
        SET status = 'cancelled', cancelled_at = NEW.updated_at,
            cancellation_reason = NEW.status
        WHERE project_id = NEW.project_id AND recommendation_id = NEW.recommendation_id
          AND status = 'pending';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_recommendation_model_task_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation model task lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF (NEW.role = 'primary' AND NEW.prompt_purpose <> 'recommendations.recommendation')
           OR (NEW.role = 'arbiter' AND NEW.prompt_purpose <> 'synthetic_lab.arbiter')
           OR NEW.runtime_selection_id <> NEW.runtime_option_id
           OR NEW.task_artifact_expires_at <= NEW.created_at
           OR NEW.task_artifact_status <> 'uploading' THEN
            RAISE EXCEPTION 'Recommendation model task frozen lineage is invalid'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'task_artifact_uri', 'task_artifact_manifest_hash',
        'task_artifact_payload_uri', 'task_artifact_content_hash',
        'task_artifact_byte_size', 'task_artifact_status', 'task_payload_hash'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'task_artifact_uri', 'task_artifact_manifest_hash',
        'task_artifact_payload_uri', 'task_artifact_content_hash',
        'task_artifact_byte_size', 'task_artifact_status', 'task_payload_hash'
    ];
    IF old_fixed <> new_fixed THEN
        RAISE EXCEPTION 'Recommendation model task frozen lineage is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.task_artifact_status = 'uploading'
       AND NEW.task_artifact_status = 'active' THEN
        RETURN NEW;
    END IF;
    IF OLD.task_artifact_status = 'active'
       AND NEW.task_artifact_status = 'deletion_pending' THEN
        RETURN NEW;
    END IF;
    IF OLD.task_artifact_status = 'deletion_pending'
       AND NEW.task_artifact_status = 'crypto_erased' THEN
        RETURN NEW;
    END IF;
    IF OLD.task_artifact_status = 'crypto_erased'
       AND NEW.task_artifact_status = 'deleted' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Recommendation model task artifact lifecycle transition is invalid'
        USING ERRCODE = '23514';
END;
$$;

CREATE FUNCTION geo_assert_recommendation_model_lineage_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'queued' OR NEW.task_artifact_status <> 'active'
           OR NOT EXISTS (
                SELECT 1 FROM recommendation_model_tasks AS task
                WHERE task.project_id = NEW.project_id
                  AND task.child_job_id = NEW.child_job_id
                  AND task.parent_job_id = NEW.parent_job_id
                  AND task.role = NEW.role
                  AND task.task_artifact_status = 'active'
           ) THEN
            RAISE EXCEPTION 'Recommendation model lineage requires an active task artifact'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation model result lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'model_attempt_id', 'model_call_log_id', 'response_hash', 'output_hash',
        'artifact_uri', 'artifact_manifest_hash', 'artifact_content_hash',
        'derived_artifact_uri', 'derived_artifact_manifest_hash',
        'derived_artifact_content_hash', 'task_artifact_status', 'status',
        'error_code', 'updated_at'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'model_attempt_id', 'model_call_log_id', 'response_hash', 'output_hash',
        'artifact_uri', 'artifact_manifest_hash', 'artifact_content_hash',
        'derived_artifact_uri', 'derived_artifact_manifest_hash',
        'derived_artifact_content_hash', 'task_artifact_status', 'status',
        'error_code', 'updated_at'
    ];
    IF old_fixed <> new_fixed OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'Recommendation model result immutable lineage changed'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_recommendation_artifact_key_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       OR OLD.master_key_version <> NEW.master_key_version
       OR OLD.algorithm <> NEW.algorithm
       OR OLD.canary_nonce <> NEW.canary_nonce
       OR OLD.canary_ciphertext <> NEW.canary_ciphertext
       OR OLD.created_at <> NEW.created_at
       OR OLD.retired_at IS NOT NULL
       OR (OLD.status = 'encrypt_decrypt' AND NEW.status NOT IN ('encrypt_decrypt', 'decrypt_only'))
       OR (OLD.status = 'decrypt_only' AND NEW.status NOT IN ('decrypt_only', 'retired')) THEN
        RAISE EXCEPTION 'Recommendation artifact key lifecycle is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_recommendation_artifact_deletion_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation artifact deletion lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'phase', 'lease_owner', 'lease_token', 'lease_expires_at',
        'fencing_generation', 'attempt_count', 'next_attempt_at',
        'crypto_erase_receipt_hash', 'deleted_receipt_hash', 'last_error_code',
        'deleted_at', 'updated_at'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'phase', 'lease_owner', 'lease_token', 'lease_expires_at',
        'fencing_generation', 'attempt_count', 'next_attempt_at',
        'crypto_erase_receipt_hash', 'deleted_receipt_hash', 'last_error_code',
        'deleted_at', 'updated_at'
    ];
    IF old_fixed <> new_fixed
       OR NEW.fencing_generation < OLD.fencing_generation
       OR NEW.attempt_count < OLD.attempt_count
       OR NEW.updated_at < OLD.updated_at
       OR (OLD.phase = 'crypto_erased' AND NEW.phase = 'deletion_pending')
       OR OLD.phase = 'deleted' THEN
        RAISE EXCEPTION 'Recommendation artifact deletion transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_enqueue_recommendation_artifact_deletion(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_child_job_id uuid,
    p_manifest_uri text,
    p_manifest_hash text,
    p_payload_uri text,
    p_payload_hash text,
    p_content_hash text,
    p_expires_at timestamptz,
    p_created_at timestamptz
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE intent recommendation_artifact_deletion_intents%ROWTYPE;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR p_expires_at IS NULL OR p_created_at IS NULL OR p_expires_at > p_created_at THEN
        RAISE EXCEPTION 'Recommendation artifact deletion input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO intent FROM recommendation_artifact_deletion_intents
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id;
    IF FOUND THEN
        IF (intent.parent_job_id, intent.manifest_uri, intent.manifest_hash,
            intent.payload_uri, intent.payload_hash, intent.content_hash, intent.expires_at)
           IS DISTINCT FROM
           (p_parent_job_id, p_manifest_uri, p_manifest_hash, p_payload_uri,
            p_payload_hash, p_content_hash, p_expires_at) THEN
            RAISE EXCEPTION 'Recommendation artifact deletion replay changed identity'
                USING ERRCODE = '40001';
        END IF;
        RETURN intent.id;
    END IF;
    INSERT INTO recommendation_artifact_deletion_intents(
        id, project_id, parent_job_id, child_job_id, manifest_uri, manifest_hash,
        payload_uri, payload_hash, content_hash, expires_at, phase, next_attempt_at,
        created_at, updated_at
    ) VALUES (
        gen_random_uuid(), p_project_id, p_parent_job_id, p_child_job_id,
        p_manifest_uri, p_manifest_hash, p_payload_uri, p_payload_hash,
        p_content_hash, p_expires_at, 'deletion_pending', p_created_at,
        p_created_at, p_created_at
    ) RETURNING * INTO intent;
    UPDATE recommendation_model_tasks
    SET task_artifact_status = 'deletion_pending'
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id
      AND task_artifact_status = 'active';
    UPDATE recommendation_model_call_lineage
    SET task_artifact_status = 'deletion_pending', updated_at = p_created_at
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id
      AND task_artifact_status IN ('staged', 'active');
    RETURN intent.id;
END;
$$;

CREATE FUNCTION geo_enqueue_recommendation_artifact_maintenance(
    p_now timestamptz
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE inserted_count bigint;
BEGIN
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'Recommendation artifact maintenance time is required'
            USING ERRCODE = '22023';
    END IF;
    WITH due AS (
        SELECT task.*
        FROM recommendation_model_tasks AS task
        WHERE task.task_artifact_status = 'active'
          AND task.task_artifact_expires_at <= p_now
        FOR UPDATE SKIP LOCKED
    ), inserted AS (
        INSERT INTO recommendation_artifact_deletion_intents(
            id, project_id, parent_job_id, child_job_id, manifest_uri, manifest_hash,
            payload_uri, payload_hash, content_hash, expires_at, phase,
            next_attempt_at, created_at, updated_at
        )
        SELECT gen_random_uuid(), due.project_id, due.parent_job_id, due.child_job_id,
               due.task_artifact_uri, due.task_artifact_manifest_hash,
               due.task_artifact_payload_uri, due.task_payload_hash,
               due.task_artifact_content_hash, due.task_artifact_expires_at,
               'deletion_pending', p_now, p_now, p_now
        FROM due
        ON CONFLICT (project_id, child_job_id) DO NOTHING
        RETURNING project_id, child_job_id
    )
    UPDATE recommendation_model_tasks AS task
    SET task_artifact_status = 'deletion_pending'
    FROM inserted
    WHERE task.project_id = inserted.project_id
      AND task.child_job_id = inserted.child_job_id;
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    UPDATE recommendation_model_call_lineage AS lineage
    SET task_artifact_status = 'deletion_pending', updated_at = p_now
    FROM recommendation_artifact_deletion_intents AS intent
    WHERE lineage.project_id = intent.project_id
      AND lineage.child_job_id = intent.child_job_id
      AND intent.phase = 'deletion_pending'
      AND lineage.task_artifact_status = 'active';
    RETURN inserted_count;
END;
$$;

CREATE FUNCTION geo_enqueue_recommendation_artifact_maintenance(
    p_project_id uuid,
    p_now timestamptz
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE inserted_count bigint;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) OR p_now IS NULL THEN
        RAISE EXCEPTION 'Recommendation project artifact maintenance input is invalid'
            USING ERRCODE = '22023';
    END IF;
    WITH due AS (
        SELECT task.*
        FROM recommendation_model_tasks AS task
        WHERE task.project_id = p_project_id
          AND task.task_artifact_status = 'active'
          AND task.task_artifact_expires_at <= p_now
        FOR UPDATE SKIP LOCKED
    ), inserted AS (
        INSERT INTO recommendation_artifact_deletion_intents(
            id, project_id, parent_job_id, child_job_id, manifest_uri, manifest_hash,
            payload_uri, payload_hash, content_hash, expires_at, phase,
            next_attempt_at, created_at, updated_at
        )
        SELECT gen_random_uuid(), due.project_id, due.parent_job_id, due.child_job_id,
               due.task_artifact_uri, due.task_artifact_manifest_hash,
               due.task_artifact_payload_uri, due.task_payload_hash,
               due.task_artifact_content_hash, due.task_artifact_expires_at,
               'deletion_pending', p_now, p_now, p_now
        FROM due
        ON CONFLICT (project_id, child_job_id) DO NOTHING
        RETURNING project_id, child_job_id
    )
    UPDATE recommendation_model_tasks AS task
    SET task_artifact_status = 'deletion_pending'
    FROM inserted
    WHERE task.project_id = inserted.project_id
      AND task.child_job_id = inserted.child_job_id;
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    UPDATE recommendation_model_call_lineage AS lineage
    SET task_artifact_status = 'deletion_pending', updated_at = p_now
    FROM recommendation_artifact_deletion_intents AS intent
    WHERE lineage.project_id = p_project_id
      AND lineage.project_id = intent.project_id
      AND lineage.child_job_id = intent.child_job_id
      AND intent.phase = 'deletion_pending'
      AND lineage.task_artifact_status = 'active';
    RETURN inserted_count;
END;
$$;

CREATE FUNCTION geo_schedule_recommendation_artifact_maintenance(
    p_now timestamptz
) RETURNS TABLE (project_id uuid, job_id uuid, outbox_id uuid, inserted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate record;
DECLARE active_job durable_jobs%ROWTYPE;
DECLARE scheduled_job_id uuid;
DECLARE scheduled_outbox_id uuid;
DECLARE input_hash text;
BEGIN
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'Recommendation artifact maintenance schedule time is required'
            USING ERRCODE = '22023';
    END IF;
    -- Stage every due active task first. The scheduler is the only global
    -- operation; individual Job workers remain project-fenced below.
    PERFORM geo_enqueue_recommendation_artifact_maintenance(p_now);
    FOR candidate IN
        SELECT DISTINCT intent.project_id
        FROM recommendation_artifact_deletion_intents AS intent
        WHERE intent.phase IN ('deletion_pending', 'crypto_erased')
          AND intent.next_attempt_at <= p_now
          AND (intent.lease_expires_at IS NULL OR intent.lease_expires_at <= p_now)
        ORDER BY intent.project_id
    LOOP
        SELECT * INTO active_job FROM durable_jobs
        WHERE project_id = candidate.project_id
          AND kind = 'recommendation.artifact_maintenance'
          AND idempotency_key = 'recommendation-artifact-maintenance:v1'
          AND status IN ('queued', 'running', 'finalizing', 'retry_wait')
        ORDER BY created_at DESC LIMIT 1 FOR UPDATE;
        IF FOUND THEN
            IF active_job.status IN ('queued', 'retry_wait') THEN
                UPDATE durable_jobs SET next_run_at = LEAST(next_run_at, p_now),
                    updated_at = p_now
                WHERE id = active_job.id AND project_id = candidate.project_id;
            END IF;
            INSERT INTO broker_outbox(
                id, project_id, job_id, topic, payload, idempotency_key, available_at
            ) VALUES (
                gen_random_uuid(), candidate.project_id, active_job.id,
                'recommendation.artifact_maintenance',
                jsonb_build_object('job_id', active_job.id::text,
                    'project_id', candidate.project_id::text),
                'recommendation-artifact-maintenance:wake:' || active_job.id::text,
                p_now
            ) ON CONFLICT (project_id, idempotency_key) DO NOTHING
            RETURNING id INTO scheduled_outbox_id;
            IF scheduled_outbox_id IS NULL THEN
                SELECT id INTO scheduled_outbox_id FROM broker_outbox
                WHERE project_id = candidate.project_id
                  AND idempotency_key = 'recommendation-artifact-maintenance:wake:'
                        || active_job.id::text;
            END IF;
            RETURN QUERY SELECT candidate.project_id, active_job.id, scheduled_outbox_id, false;
            CONTINUE;
        END IF;
        scheduled_job_id := gen_random_uuid();
        input_hash := encode(digest(convert_to(
            'recommendation.artifact_maintenance:v1:' || candidate.project_id::text,
            'UTF8'), 'sha256'), 'hex');
        INSERT INTO durable_jobs(
            id, project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, replay_nonce, created_at, updated_at
        ) VALUES (
            scheduled_job_id, candidate.project_id, 'recommendation.artifact_maintenance',
            'queued', 5, input_hash, 'recommendation-artifact-maintenance:v1', 10, p_now,
            coalesce((SELECT max(replay_nonce) + 1 FROM durable_jobs
                      WHERE project_id = candidate.project_id
                        AND kind = 'recommendation.artifact_maintenance'
                        AND idempotency_key = 'recommendation-artifact-maintenance:v1'), 0),
            p_now, p_now
        );
        INSERT INTO broker_outbox(
            id, project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            gen_random_uuid(), candidate.project_id, scheduled_job_id,
            'recommendation.artifact_maintenance',
            jsonb_build_object('job_id', scheduled_job_id::text,
                'project_id', candidate.project_id::text),
            'recommendation-artifact-maintenance:wake:' || scheduled_job_id::text,
            p_now
        ) RETURNING id INTO scheduled_outbox_id;
        RETURN QUERY SELECT candidate.project_id, scheduled_job_id, scheduled_outbox_id, true;
    END LOOP;
END;
$$;

CREATE FUNCTION geo_assert_recommendation_generation_lease(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_parent_lease_token uuid,
    p_parent_fence bigint,
    p_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE parent_job durable_jobs%ROWTYPE;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Recommendation generation is outside caller Project scope'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO STRICT parent_job
    FROM durable_jobs
    WHERE id = p_parent_job_id AND project_id = p_project_id
    FOR SHARE;
    IF parent_job.kind <> 'recommendation.generate'
       OR parent_job.status NOT IN ('running', 'finalizing')
       OR parent_job.cancel_requested_at IS NOT NULL
       OR parent_job.lease_token IS DISTINCT FROM p_parent_lease_token
       OR parent_job.fencing_generation <> p_parent_fence
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= p_at THEN
        RAISE EXCEPTION 'Recommendation generation lease or fence was lost'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE FUNCTION geo_enqueue_recommendation_generation(
    p_project_id uuid,
    p_job_id uuid,
    p_spec_payload jsonb,
    p_spec_hash text,
    p_input_hash text,
    p_idempotency_hash text,
    p_valid_until timestamptz,
    p_created_by uuid,
    p_created_at timestamptz,
    p_max_attempts integer
) RETURNS TABLE (job_id uuid, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing recommendation_generation_specs%ROWTYPE;
DECLARE result_payload jsonb;
DECLARE result_hash text;
DECLARE outbox_id uuid := gen_random_uuid();
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR p_spec_payload IS NULL OR jsonb_typeof(p_spec_payload) <> 'object'
       OR p_spec_hash !~ '^[0-9a-f]{64}$' OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR p_idempotency_hash !~ '^[0-9a-f]{64}$'
       OR p_valid_until <= p_created_at OR p_max_attempts NOT BETWEEN 1 AND 20
       OR encode(digest(convert_to(geo_jsonb_canonical_text(p_spec_payload), 'UTF8'), 'sha256'), 'hex')
            <> p_spec_hash THEN
        RAISE EXCEPTION 'Recommendation generation enqueue input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing
    FROM recommendation_generation_specs
    WHERE project_id = p_project_id AND idempotency_key_hash = p_idempotency_hash
    FOR SHARE;
    IF FOUND THEN
        IF (existing.job_id, existing.spec_payload_hash, existing.input_hash,
            existing.valid_until, existing.created_by, existing.api_version)
           IS DISTINCT FROM
           (p_job_id, p_spec_hash, p_input_hash, p_valid_until, p_created_by, 1) THEN
            RAISE EXCEPTION 'Recommendation generation idempotency replay changed request'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT existing.job_id, true;
        RETURN;
    END IF;
    INSERT INTO durable_jobs(
        id, project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, fencing_generation, replay_nonce, created_at, updated_at
    ) VALUES (
        p_job_id, p_project_id, 'recommendation.generate', 'queued', 0, p_input_hash,
        'recommendation-generation:' || p_idempotency_hash, p_max_attempts,
        p_created_at, 0, 0, p_created_at, p_created_at
    );
    INSERT INTO recommendation_generation_specs(
        project_id, job_id, api_version, spec_payload, spec_payload_hash, input_hash,
        idempotency_key_hash, valid_until, created_by, created_at
    ) VALUES (
        p_project_id, p_job_id, 1, p_spec_payload, p_spec_hash, p_input_hash,
        p_idempotency_hash, p_valid_until, p_created_by, p_created_at
    );
    INSERT INTO broker_outbox(
        id, project_id, job_id, topic, payload, idempotency_key, available_at, created_at
    ) VALUES (
        outbox_id, p_project_id, p_job_id, 'recommendation.generate.queued',
        jsonb_build_object('project_id', p_project_id::text, 'job_id', p_job_id::text,
                           'event_type', 'recommendation.generate.queued',
                           'payload_hash', p_input_hash),
        'recommendation-generation:' || p_idempotency_hash, p_created_at, p_created_at
    );
    result_payload := jsonb_build_object('job_id', p_job_id::text, 'replayed', false);
    result_hash := encode(digest(convert_to(geo_jsonb_canonical_text(result_payload), 'UTF8'), 'sha256'), 'hex');
    INSERT INTO recommendation_generation_command_receipts(
        project_id, idempotency_key_hash, operation, request_hash, result_payload,
        result_payload_hash, created_at
    ) VALUES (
        p_project_id, p_idempotency_hash, 'enqueue', p_spec_hash, result_payload,
        result_hash, p_created_at
    );
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    ) VALUES (
        p_project_id, p_job_id, 'job_enqueued', 'recommendation-generation-enqueue', 0,
        jsonb_build_object('input_hash', p_input_hash), p_created_at
    );
    RETURN QUERY SELECT p_job_id, false;
END;
$$;

CREATE FUNCTION geo_cancel_recommendation_generation(
    p_project_id uuid,
    p_job_id uuid,
    p_expected_version integer,
    p_idempotency_hash text,
    p_request_hash text,
    p_cancelled_at timestamptz
) RETURNS TABLE (job_id uuid, durable_status text, cancel_requested boolean, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE job durable_jobs%ROWTYPE;
DECLARE spec recommendation_generation_specs%ROWTYPE;
DECLARE existing recommendation_generation_command_receipts%ROWTYPE;
DECLARE result_payload jsonb;
DECLARE result_hash text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR p_expected_version < 1
       OR p_idempotency_hash !~ '^[0-9a-f]{64}$'
       OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_cancelled_at IS NULL THEN
        RAISE EXCEPTION 'Recommendation generation cancellation input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing
    FROM recommendation_generation_command_receipts
    WHERE project_id = p_project_id AND idempotency_key_hash = p_idempotency_hash
    FOR SHARE;
    IF FOUND THEN
        IF existing.operation <> 'cancel' OR existing.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'Recommendation cancellation idempotency replay changed request'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT (existing.result_payload->>'job_id')::uuid,
            existing.result_payload->>'durable_status',
            (existing.result_payload->>'cancel_requested')::boolean, true;
        RETURN;
    END IF;
    SELECT * INTO STRICT spec
    FROM recommendation_generation_specs
    WHERE project_id = p_project_id AND job_id = p_job_id
    FOR SHARE;
    IF spec.api_version <> p_expected_version THEN
        RAISE EXCEPTION 'Recommendation generation cancellation version changed'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO STRICT job
    FROM durable_jobs WHERE project_id = p_project_id AND id = p_job_id
    FOR UPDATE;
    IF job.status = 'queued' THEN
        UPDATE durable_jobs
        SET status = 'cancelled', cancel_requested_at = p_cancelled_at,
            completed_at = p_cancelled_at, updated_at = p_cancelled_at
        WHERE project_id = p_project_id AND id = p_job_id;
    ELSIF job.status IN ('running', 'finalizing') THEN
        UPDATE durable_jobs
        SET cancel_requested_at = coalesce(cancel_requested_at, p_cancelled_at),
            updated_at = p_cancelled_at
        WHERE project_id = p_project_id AND id = p_job_id;
    END IF;
    SELECT * INTO STRICT job
    FROM durable_jobs WHERE project_id = p_project_id AND id = p_job_id;
    result_payload := jsonb_build_object(
        'job_id', p_job_id::text, 'durable_status', job.status,
        'cancel_requested', job.cancel_requested_at IS NOT NULL
    );
    result_hash := encode(digest(convert_to(geo_jsonb_canonical_text(result_payload), 'UTF8'), 'sha256'), 'hex');
    INSERT INTO recommendation_generation_command_receipts(
        project_id, idempotency_key_hash, operation, request_hash, result_payload,
        result_payload_hash, created_at
    ) VALUES (
        p_project_id, p_idempotency_hash, 'cancel', p_request_hash, result_payload,
        result_hash, p_cancelled_at
    );
    RETURN QUERY SELECT p_job_id, job.status,
        job.cancel_requested_at IS NOT NULL, false;
END;
$$;

CREATE FUNCTION geo_reserve_recommendation_model_task(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_parent_lease_token uuid,
    p_parent_fence bigint,
    p_child_job_id uuid,
    p_parent_input_hash text,
    p_role text,
    p_runtime_selection_id uuid,
    p_runtime_manifest_id uuid,
    p_runtime_manifest_hash text,
    p_runtime_option_id uuid,
    p_runtime_option_hash text,
    p_prompt_binding_id uuid,
    p_prompt_binding_version integer,
    p_prompt_frozen_state_id uuid,
    p_prompt_state_version integer,
    p_prompt_release_id uuid,
    p_prompt_release_version integer,
    p_prompt_release_hash text,
    p_prompt_purpose text,
    p_provider text,
    p_adapter_release_id text,
    p_adapter_release_hash text,
    p_model_release_id text,
    p_model_release_hash text,
    p_configured_model text,
    p_capture_method text,
    p_search_mode text,
    p_prompt_bundle_hash text,
    p_structured_input_hash text,
    p_output_schema_hash text,
    p_application_output_schema_hash text,
    p_artifact_expires_at timestamptz,
    p_admitted_by uuid,
    p_created_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing recommendation_model_tasks%ROWTYPE;
BEGIN
    PERFORM geo_assert_recommendation_generation_lease(
        p_project_id, p_parent_job_id, p_parent_lease_token, p_parent_fence, p_created_at
    );
    IF p_artifact_expires_at IS NULL OR p_created_at IS NULL
       OR p_artifact_expires_at <= p_created_at THEN
        RAISE EXCEPTION 'Recommendation model task artifact expiry is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing
    FROM recommendation_model_tasks
    WHERE project_id = p_project_id
      AND (child_job_id = p_child_job_id
           OR (parent_job_id = p_parent_job_id AND role = p_role))
    LIMIT 1
    FOR SHARE;
    IF FOUND THEN
        IF (existing.parent_job_id, existing.child_job_id, existing.parent_input_hash,
            existing.role, existing.runtime_selection_id, existing.runtime_manifest_id,
            existing.runtime_manifest_hash, existing.runtime_option_id,
            existing.runtime_option_hash, existing.prompt_binding_id,
            existing.prompt_binding_version, existing.prompt_frozen_state_id,
            existing.prompt_state_version, existing.prompt_release_id,
            existing.prompt_release_version, existing.prompt_release_hash,
            existing.prompt_purpose, existing.provider, existing.adapter_release_id,
            existing.adapter_release_hash, existing.model_release_id,
            existing.model_release_hash, existing.configured_model, existing.capture_method,
            existing.search_mode, existing.prompt_bundle_hash, existing.structured_input_hash,
            existing.output_schema_hash, existing.application_output_schema_hash,
            existing.task_artifact_expires_at, existing.admitted_by)
           IS DISTINCT FROM
           (p_parent_job_id, p_child_job_id, p_parent_input_hash, p_role,
            p_runtime_selection_id, p_runtime_manifest_id, p_runtime_manifest_hash,
            p_runtime_option_id, p_runtime_option_hash, p_prompt_binding_id,
            p_prompt_binding_version, p_prompt_frozen_state_id, p_prompt_state_version,
            p_prompt_release_id, p_prompt_release_version, p_prompt_release_hash,
            p_prompt_purpose, p_provider, p_adapter_release_id, p_adapter_release_hash,
            p_model_release_id, p_model_release_hash, p_configured_model,
            p_capture_method, p_search_mode, p_prompt_bundle_hash,
            p_structured_input_hash, p_output_schema_hash,
            p_application_output_schema_hash, p_artifact_expires_at, p_admitted_by) THEN
            RAISE EXCEPTION 'Recommendation model task reservation replay changed identity'
                USING ERRCODE = '40001';
        END IF;
        RETURN;
    END IF;
    INSERT INTO recommendation_model_tasks(
        project_id, parent_job_id, child_job_id, parent_input_hash, role,
        runtime_selection_id, runtime_manifest_id, runtime_manifest_hash,
        runtime_option_id, runtime_option_hash, prompt_binding_id,
        prompt_binding_version, prompt_frozen_state_id, prompt_state_version,
        prompt_release_id, prompt_release_version, prompt_release_hash,
        prompt_purpose, provider, adapter_release_id, adapter_release_hash,
        model_release_id, model_release_hash, configured_model, capture_method,
        search_mode, prompt_bundle_hash, structured_input_hash, output_schema_hash,
        application_output_schema_hash, task_artifact_expires_at,
        task_artifact_status, admitted_by, created_at
    ) VALUES (
        p_project_id, p_parent_job_id, p_child_job_id, p_parent_input_hash, p_role,
        p_runtime_selection_id, p_runtime_manifest_id, p_runtime_manifest_hash,
        p_runtime_option_id, p_runtime_option_hash, p_prompt_binding_id,
        p_prompt_binding_version, p_prompt_frozen_state_id, p_prompt_state_version,
        p_prompt_release_id, p_prompt_release_version, p_prompt_release_hash,
        p_prompt_purpose, p_provider, p_adapter_release_id, p_adapter_release_hash,
        p_model_release_id, p_model_release_hash, p_configured_model, p_capture_method,
        p_search_mode, p_prompt_bundle_hash, p_structured_input_hash, p_output_schema_hash,
        p_application_output_schema_hash, p_artifact_expires_at,
        'uploading', p_admitted_by, p_created_at
    );
END;
$$;

CREATE FUNCTION geo_activate_recommendation_model_task(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_parent_lease_token uuid,
    p_parent_fence bigint,
    p_child_job_id uuid,
    p_artifact_uri text,
    p_artifact_manifest_hash text,
    p_artifact_payload_uri text,
    p_artifact_payload_hash text,
    p_artifact_content_hash text,
    p_artifact_byte_size bigint,
    p_activated_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE task recommendation_model_tasks%ROWTYPE;
DECLARE parent_job durable_jobs%ROWTYPE;
DECLARE outbox_id uuid := gen_random_uuid();
DECLARE child_kind text;
DECLARE child_topic text;
DECLARE child_key text;
BEGIN
    PERFORM geo_assert_recommendation_generation_lease(
        p_project_id, p_parent_job_id, p_parent_lease_token, p_parent_fence, p_activated_at
    );
    SELECT * INTO STRICT task
    FROM recommendation_model_tasks
    WHERE project_id = p_project_id AND parent_job_id = p_parent_job_id
      AND child_job_id = p_child_job_id
    FOR UPDATE;
    IF task.task_artifact_status = 'active' THEN
        IF (task.task_artifact_uri, task.task_artifact_manifest_hash,
            task.task_artifact_payload_uri, task.task_payload_hash,
            task.task_artifact_content_hash, task.task_artifact_byte_size)
           IS DISTINCT FROM
           (p_artifact_uri, p_artifact_manifest_hash, p_artifact_payload_uri,
            p_artifact_payload_hash, p_artifact_content_hash, p_artifact_byte_size) THEN
            RAISE EXCEPTION 'Recommendation task activation replay changed artifact identity'
                USING ERRCODE = '40001';
        END IF;
        RETURN;
    END IF;
    IF task.task_artifact_status <> 'uploading' THEN
        RAISE EXCEPTION 'Recommendation task is not awaiting artifact activation'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO STRICT parent_job
    FROM durable_jobs WHERE id = p_parent_job_id AND project_id = p_project_id;
    child_kind := CASE task.role
        WHEN 'primary' THEN 'recommendation.model.primary'
        WHEN 'arbiter' THEN 'recommendation.model.arbiter'
    END;
    child_topic := child_kind;
    child_key := 'recommendation-model:' || p_parent_job_id::text || ':' || task.role;
    INSERT INTO durable_jobs(
        id, project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, fencing_generation, parent_job_id, replay_nonce,
        campaign_id, created_at, updated_at
    ) VALUES (
        p_child_job_id, p_project_id, child_kind, 'queued', parent_job.priority,
        task.structured_input_hash, child_key, 3, p_activated_at, 0,
        p_parent_job_id, 0, parent_job.campaign_id, p_activated_at, p_activated_at
    ) ON CONFLICT (id) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1 FROM durable_jobs
        WHERE id = p_child_job_id AND project_id = p_project_id
          AND kind = child_kind AND parent_job_id = p_parent_job_id
          AND input_hash = task.structured_input_hash AND idempotency_key = child_key
    ) THEN
        RAISE EXCEPTION 'Recommendation task child durable Job identity changed'
            USING ERRCODE = '40001';
    END IF;
    UPDATE recommendation_model_tasks
    SET task_artifact_uri = p_artifact_uri,
        task_artifact_manifest_hash = p_artifact_manifest_hash,
        task_artifact_payload_uri = p_artifact_payload_uri,
        task_payload_hash = p_artifact_payload_hash,
        task_artifact_content_hash = p_artifact_content_hash,
        task_artifact_byte_size = p_artifact_byte_size,
        task_artifact_status = 'active'
    WHERE project_id = p_project_id AND child_job_id = p_child_job_id;
    INSERT INTO recommendation_model_call_lineage(
        project_id, parent_job_id, child_job_id, role, task_artifact_status,
        task_artifact_expires_at, status, created_at, updated_at
    ) VALUES (
        p_project_id, p_parent_job_id, p_child_job_id, task.role, 'active',
        task.task_artifact_expires_at, 'queued', p_activated_at, p_activated_at
    ) ON CONFLICT (project_id, child_job_id) DO NOTHING;
    INSERT INTO broker_outbox(
        id, project_id, job_id, topic, payload, idempotency_key, available_at, created_at
    ) VALUES (
        outbox_id, p_project_id, p_child_job_id, child_topic,
        jsonb_build_object('project_id', p_project_id::text, 'job_id', p_child_job_id::text,
                           'event_type', child_topic, 'payload_hash', task.structured_input_hash),
        child_key, p_activated_at, p_activated_at
    ) ON CONFLICT (project_id, idempotency_key) DO NOTHING;
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    ) VALUES (
        p_project_id, p_child_job_id, 'job_enqueued', 'recommendation-task-activate', 0,
        jsonb_build_object('parent_job_id', p_parent_job_id::text, 'role', task.role),
        p_activated_at
    );
END;
$$;

CREATE FUNCTION geo_claim_recommendation_artifact_deletion(
    p_worker_id text,
    p_now timestamptz,
    p_lease_seconds integer,
    p_limit integer
) RETURNS SETOF recommendation_artifact_deletion_intents
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF btrim(coalesce(p_worker_id, '')) = '' OR p_now IS NULL
       OR p_lease_seconds NOT BETWEEN 30 AND 3600 OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'Recommendation artifact deletion claim input is invalid'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH claimed AS (
        SELECT id FROM recommendation_artifact_deletion_intents
        WHERE phase IN ('deletion_pending', 'crypto_erased')
          AND next_attempt_at <= p_now
          AND (lease_expires_at IS NULL OR lease_expires_at <= p_now)
        ORDER BY next_attempt_at, id
        LIMIT p_limit FOR UPDATE SKIP LOCKED
    )
    UPDATE recommendation_artifact_deletion_intents AS item
    SET lease_owner = p_worker_id, lease_token = gen_random_uuid(),
        lease_expires_at = p_now + make_interval(secs => p_lease_seconds),
        fencing_generation = item.fencing_generation + 1,
        attempt_count = item.attempt_count + 1, last_error_code = NULL,
        updated_at = p_now
    FROM claimed WHERE item.id = claimed.id
    RETURNING item.*;
END;
$$;

CREATE FUNCTION geo_claim_recommendation_artifact_deletion(
    p_project_id uuid,
    p_worker_id text,
    p_now timestamptz,
    p_lease_seconds integer,
    p_limit integer
) RETURNS SETOF recommendation_artifact_deletion_intents
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR btrim(coalesce(p_worker_id, '')) = '' OR p_now IS NULL
       OR p_lease_seconds NOT BETWEEN 30 AND 3600 OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'Recommendation project artifact deletion claim input is invalid'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH claimed AS (
        SELECT id FROM recommendation_artifact_deletion_intents
        WHERE project_id = p_project_id
          AND phase IN ('deletion_pending', 'crypto_erased')
          AND next_attempt_at <= p_now
          AND (lease_expires_at IS NULL OR lease_expires_at <= p_now)
        ORDER BY next_attempt_at, id
        LIMIT p_limit FOR UPDATE SKIP LOCKED
    )
    UPDATE recommendation_artifact_deletion_intents AS item
    SET lease_owner = p_worker_id, lease_token = gen_random_uuid(),
        lease_expires_at = p_now + make_interval(secs => p_lease_seconds),
        fencing_generation = item.fencing_generation + 1,
        attempt_count = item.attempt_count + 1, last_error_code = NULL,
        updated_at = p_now
    FROM claimed WHERE item.id = claimed.id
    RETURNING item.*;
END;
$$;

CREATE FUNCTION geo_claim_recommendation_artifact_deletion(
    p_worker_id text,
    p_now timestamptz,
    p_lease_seconds integer
) RETURNS SETOF recommendation_artifact_deletion_intents
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
    SELECT *
    FROM geo_claim_recommendation_artifact_deletion(
        p_worker_id, p_now, p_lease_seconds, 1
    )
$$;

CREATE FUNCTION geo_mark_recommendation_artifact_crypto_erased(
    p_intent_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_receipt_hash text,
    p_erased_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE intent recommendation_artifact_deletion_intents%ROWTYPE;
BEGIN
    SELECT * INTO STRICT intent FROM recommendation_artifact_deletion_intents
    WHERE id = p_intent_id FOR UPDATE;
    IF intent.phase <> 'deletion_pending' OR intent.lease_token IS DISTINCT FROM p_lease_token
       OR intent.fencing_generation <> p_fencing_generation
       OR intent.lease_expires_at <= p_erased_at OR p_receipt_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Recommendation artifact crypto-erasure lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    UPDATE recommendation_artifact_deletion_intents
    SET phase = 'crypto_erased', crypto_erase_receipt_hash = p_receipt_hash,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        next_attempt_at = p_erased_at, updated_at = p_erased_at
    WHERE id = p_intent_id;
    UPDATE recommendation_model_tasks
    SET task_artifact_status = 'crypto_erased'
    WHERE project_id = intent.project_id AND child_job_id = intent.child_job_id;
    UPDATE recommendation_model_call_lineage
    SET task_artifact_status = 'crypto_erased', updated_at = p_erased_at
    WHERE project_id = intent.project_id AND child_job_id = intent.child_job_id;
END;
$$;

CREATE FUNCTION geo_mark_recommendation_artifact_deleted(
    p_intent_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_receipt_hash text,
    p_deleted_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE intent recommendation_artifact_deletion_intents%ROWTYPE;
BEGIN
    SELECT * INTO STRICT intent FROM recommendation_artifact_deletion_intents
    WHERE id = p_intent_id FOR UPDATE;
    IF intent.phase <> 'crypto_erased' OR intent.lease_token IS DISTINCT FROM p_lease_token
       OR intent.fencing_generation <> p_fencing_generation
       OR intent.lease_expires_at <= p_deleted_at OR p_receipt_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Recommendation artifact deletion lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    UPDATE recommendation_artifact_deletion_intents
    SET phase = 'deleted', deleted_receipt_hash = p_receipt_hash,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        deleted_at = p_deleted_at, updated_at = p_deleted_at
    WHERE id = p_intent_id;
    UPDATE recommendation_model_tasks
    SET task_artifact_status = 'deleted'
    WHERE project_id = intent.project_id AND child_job_id = intent.child_job_id;
    UPDATE recommendation_model_call_lineage
    SET task_artifact_status = 'deleted', updated_at = p_deleted_at
    WHERE project_id = intent.project_id AND child_job_id = intent.child_job_id;
END;
$$;

CREATE FUNCTION geo_retry_recommendation_artifact_deletion(
    p_intent_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_error_code text,
    p_retry_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE intent recommendation_artifact_deletion_intents%ROWTYPE;
BEGIN
    SELECT * INTO STRICT intent FROM recommendation_artifact_deletion_intents
    WHERE id = p_intent_id FOR UPDATE;
    IF intent.phase = 'deleted' OR intent.lease_token IS DISTINCT FROM p_lease_token
       OR intent.fencing_generation <> p_fencing_generation
       OR intent.lease_expires_at <= p_retry_at
       OR btrim(coalesce(p_error_code, '')) = '' OR p_retry_at <= intent.updated_at THEN
        RAISE EXCEPTION 'Recommendation artifact retry lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    UPDATE recommendation_artifact_deletion_intents
    SET lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        last_error_code = p_error_code, next_attempt_at = p_retry_at,
        updated_at = p_retry_at
    WHERE id = p_intent_id;
END;
$$;

-- Evidence is resolved against producer-owned tables at the point of action;
-- Recommendation rows merely retain the resulting immutable identity.
CREATE FUNCTION geo_resolve_recommendation_evidence(
    p_project_id uuid,
    p_kind text,
    p_resource_id text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE resolved jsonb;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RETURN NULL;
    END IF;
    CASE p_kind
    WHEN 'fact' THEN
        SELECT jsonb_build_object(
            'kind', 'fact', 'project_id', fact.project_id::text,
            'resource_id', fact.id::text, 'version', fact.statement_hash,
            'sha256', fact.statement_hash,
            'locator', jsonb_build_object('knowledge_fact_id', fact.id::text),
            'valid', fact.status = 'approved', 'approved', fact.status = 'approved',
            'retired', false, 'summary', fact.statement,
            'summary_hash', encode(digest(convert_to(fact.statement, 'UTF8'), 'sha256'), 'hex')
        ) INTO resolved
        FROM knowledge_fact_candidates AS fact
        WHERE fact.project_id = p_project_id AND fact.id::text = p_resource_id
          AND fact.status = 'approved';
    WHEN 'observation' THEN
        SELECT jsonb_build_object(
            'kind', 'observation', 'project_id', observation.project_id::text,
            'resource_id', observation.id::text, 'version', observation.observation_hash,
            'sha256', observation.observation_hash,
            'locator', jsonb_build_object('sampling_observation_id', observation.id::text),
            'valid', observation.status = 'complete',
            'capture_method', task.capture_method,
            'evidence_class', CASE WHEN observation.status = 'complete' THEN 'real' ELSE 'ineligible' END,
            'question_resource_id', task.question_id,
            'surface_resource_id', task.capture_method,
            'eligible', observation.status = 'complete',
            'summary', NULL
        ) INTO resolved
        FROM workflow_c_sampling_observations AS observation
        JOIN workflow_c_sampling_tasks AS task
          ON task.id = observation.task_id AND task.project_id = observation.project_id
        WHERE observation.project_id = p_project_id
          AND observation.id::text = p_resource_id;
    WHEN 'prompt_release' THEN
        SELECT jsonb_build_object(
            'kind', 'prompt_release', 'project_id', release.project_id::text,
            'resource_id', release.id::text, 'version', release.release_hash,
            'sha256', release.release_hash,
            'locator', jsonb_build_object('prompt_release_id', release.id::text),
            'valid', state.status = 'frozen', 'approved', state.status = 'frozen',
            'frozen', state.status = 'frozen', 'summary', NULL
        ) INTO resolved
        FROM prompt_program_releases AS release
        JOIN LATERAL (
            SELECT value.* FROM prompt_program_release_states AS value
            WHERE value.project_id = release.project_id AND value.release_id = release.id
              AND value.release_hash = release.release_hash
            ORDER BY value.version DESC LIMIT 1
        ) AS state ON true
        WHERE release.project_id = p_project_id AND release.id::text = p_resource_id;
    WHEN 'metric_comparison' THEN
        SELECT jsonb_build_object(
            'kind', 'metric_comparison', 'project_id', family.project_id::text,
            'resource_id', family.family_hash || ':' || result.comparison_id,
            'version', family.family_hash, 'sha256', family.family_hash,
            'locator', jsonb_build_object(
                'comparison_family_hash', family.family_hash,
                'comparison_id', result.comparison_id
            ),
            'valid', family.status = 'complete',
            'observation_resource_ids', coalesce(result.payload->'observation_resource_ids', '[]'::jsonb),
            'method_version', family.bootstrap_method,
            'method_sha256', family.protocol_hash,
            'sufficient_evidence', result.conclusion <> 'insufficient_evidence',
            'summary', NULL
        ) INTO resolved
        FROM workflow_c_comparison_results AS result
        JOIN workflow_c_comparison_families AS family
          ON family.family_hash = result.family_hash
        WHERE family.project_id = p_project_id
          AND (family.family_hash || ':' || result.comparison_id) = p_resource_id;
    WHEN 'rule' THEN
        SELECT jsonb_build_object(
            'kind', 'rule', 'project_id', rule.project_id::text,
            'resource_id', rule.id::text, 'version', rule.rule_hash,
            'sha256', rule.rule_hash,
            'locator', jsonb_build_object('alert_rule_version_id', rule.id::text),
            'valid', rule.status = 'approved', 'active', rule.status = 'approved',
            'summary', NULL
        ) INTO resolved
        FROM workflow_c_alert_rule_versions AS rule
        WHERE rule.project_id = p_project_id AND rule.id::text = p_resource_id;
    WHEN 'content' THEN
        SELECT jsonb_build_object(
            'kind', 'content', 'project_id', package.project_id::text,
            'resource_id', package.id::text, 'version', package.content_hash,
            'sha256', package.content_hash,
            'locator', jsonb_build_object('placement_package_version_id', package.id::text),
            'valid', package.workflow_status = 'approved',
            'current', package.workflow_status = 'approved', 'summary', NULL
        ) INTO resolved
        FROM placement_package_versions AS package
        WHERE package.project_id = p_project_id AND package.id::text = p_resource_id;
    WHEN 'question' THEN
        SELECT jsonb_build_object(
            'kind', 'question', 'project_id', item.project_id::text,
            'resource_id', item.id::text, 'version', question_set.content_hash,
            'sha256', item.query_text_hash,
            'locator', jsonb_build_object(
                'question_set_id', question_set.id::text,
                'question_set_item_id', item.id::text
            ),
            'valid', question_set.status = 'frozen',
            'active', question_set.status = 'frozen', 'summary', NULL
        ) INTO resolved
        FROM knowledge_question_set_items AS item
        JOIN knowledge_question_sets AS question_set
          ON question_set.id = item.question_set_id
         AND question_set.project_id = item.project_id
         AND question_set.campaign_id = item.campaign_id
        WHERE item.project_id = p_project_id AND item.id::text = p_resource_id;
    WHEN 'surface' THEN
        SELECT jsonb_build_object(
            'kind', 'surface', 'project_id', suite.project_id::text,
            'resource_id', suite.source_stratum_hash, 'version', suite.suite_hash,
            'sha256', suite.source_stratum_hash,
            'locator', jsonb_build_object('sampling_suite_id', suite.id::text),
            'valid', true, 'active', true, 'summary', NULL
        ) INTO resolved
        FROM workflow_c_sampling_suites AS suite
        WHERE suite.project_id = p_project_id
          AND suite.source_stratum_hash = p_resource_id
        ORDER BY suite.frozen_at DESC LIMIT 1;
    WHEN 'model_call' THEN
        SELECT jsonb_build_object(
            'kind', 'model_call', 'project_id', attempt.project_id::text,
            'resource_id', attempt.id::text, 'version', terminal.response_hash,
            'sha256', terminal.response_hash,
            'locator', jsonb_build_object(
                'model_gateway_attempt_id', attempt.id::text,
                'terminal_event_id', terminal.id::text
            ),
            'valid', terminal.status = 'succeeded',
            'prompt_release_resource_id', attempt.prompt_release_id::text,
            'model_identity', attempt.provider || ':' || attempt.adapter_release_id
                || ':' || attempt.model_release_id,
            'succeeded', terminal.status = 'succeeded', 'summary', NULL
        ) INTO resolved
        FROM model_gateway_call_attempts AS attempt
        JOIN model_gateway_terminal_events AS terminal
          ON terminal.project_id = attempt.project_id
         AND terminal.job_id = attempt.job_id AND terminal.attempt_id = attempt.id
        WHERE attempt.project_id = p_project_id AND attempt.id::text = p_resource_id;
    WHEN 'attribution' THEN
        RETURN jsonb_build_object(
            'kind', 'attribution',
            'project_id', p_project_id::text,
            'resource_id', p_resource_id,
            'version', 'connector-attribution-policy-v1',
            'sha256', encode(digest(convert_to(
                'connector_attribution_excluded_from_this_phase:'
                    || p_project_id::text || ':' || p_resource_id,
                'UTF8'
            ), 'sha256'), 'hex'),
            'locator', jsonb_build_object(
                'policy', 'connector_attribution_excluded_from_this_phase',
                'project_id', p_project_id::text,
                'requested_resource_id', p_resource_id
            ),
            'valid', false,
            'active', false,
            'available', false,
            'reason', 'connector_attribution_excluded_from_this_phase',
            'summary', NULL
        );
    ELSE
        RETURN NULL;
    END CASE;
    RETURN resolved;
END;
$$;

CREATE TRIGGER workflow_c_job_spec_immutable_guard
BEFORE INSERT OR UPDATE OR DELETE ON workflow_c_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_job_spec_immutable();
CREATE TRIGGER workflow_c_report_snapshot_version_append_guard
BEFORE INSERT OR UPDATE OR DELETE ON workflow_c_report_snapshot_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_report_snapshot_version_append();
CREATE TRIGGER workflow_c_alert_evaluation_immutable_guard
BEFORE UPDATE OR DELETE ON workflow_c_alert_evaluations
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_alert_evaluation_immutable();
CREATE TRIGGER workflow_c_admin_inbox_notification_immutable_guard
BEFORE UPDATE OR DELETE ON workflow_c_admin_inbox_notifications
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_admin_inbox_notification_immutable();
CREATE TRIGGER recommendation_workflow_append_guard
BEFORE INSERT OR UPDATE OR DELETE ON recommendation_workflow_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_recommendation_workflow_append();
CREATE TRIGGER recommendation_approval_guard
BEFORE INSERT OR UPDATE OR DELETE ON recommendation_approvals
FOR EACH ROW EXECUTE FUNCTION geo_assert_recommendation_approval();
CREATE TRIGGER recommendation_draft_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON recommendation_drafts
FOR EACH ROW EXECUTE FUNCTION geo_assert_recommendation_draft_change();
CREATE TRIGGER recommendation_drafts_block_on_stale
AFTER INSERT ON recommendation_workflow_versions
FOR EACH ROW EXECUTE FUNCTION geo_block_recommendation_drafts_on_stale();
CREATE TRIGGER recommendation_model_task_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON recommendation_model_tasks
FOR EACH ROW EXECUTE FUNCTION geo_assert_recommendation_model_task_change();
CREATE TRIGGER recommendation_model_lineage_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON recommendation_model_call_lineage
FOR EACH ROW EXECUTE FUNCTION geo_assert_recommendation_model_lineage_change();
CREATE TRIGGER recommendation_artifact_key_change_guard
BEFORE UPDATE OR DELETE ON recommendation_artifact_master_key_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_recommendation_artifact_key_change();
CREATE TRIGGER recommendation_artifact_deletion_change_guard
BEFORE UPDATE OR DELETE ON recommendation_artifact_deletion_intents
FOR EACH ROW EXECUTE FUNCTION geo_assert_recommendation_artifact_deletion_change();

CREATE INDEX recommendation_workflow_current_idx
ON recommendation_workflow_versions(project_id, recommendation_id, version DESC);
CREATE INDEX recommendation_evidence_bindings_resource_idx
ON recommendation_evidence_bindings(project_id, evidence_kind, resource_id);
CREATE INDEX recommendation_drafts_source_idx
ON recommendation_drafts(project_id, recommendation_id, status);
CREATE INDEX recommendation_generation_specs_validity_idx
ON recommendation_generation_specs(project_id, valid_until, created_at);
CREATE INDEX recommendation_model_tasks_parent_idx
ON recommendation_model_tasks(project_id, parent_job_id, role);
CREATE INDEX recommendation_model_lineage_parent_idx
ON recommendation_model_call_lineage(project_id, parent_job_id, role);

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'workflow_c_job_specs',
        'workflow_c_report_snapshot_versions', 'workflow_c_alert_evaluations',
        'workflow_c_admin_inbox_notifications',
        'recommendation_workflow_versions', 'recommendation_evidence_bindings',
        'recommendation_approvals', 'recommendation_reviews',
        'recommendation_command_receipts', 'recommendation_drafts',
        'recommendation_outbox_messages', 'recommendation_generation_specs',
        'recommendation_generation_results', 'recommendation_generation_command_receipts',
        'recommendation_model_tasks',
        'recommendation_model_call_lineage',
        'recommendation_artifact_deletion_intents'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

REVOKE ALL ON
    service_identities, workflow_c_job_specs,
    workflow_c_report_snapshot_versions, workflow_c_alert_evaluations,
    workflow_c_admin_inbox_notifications,
    recommendation_workflow_versions, recommendation_evidence_bindings,
    recommendation_approvals, recommendation_reviews, recommendation_command_receipts,
    recommendation_drafts, recommendation_outbox_messages,
    recommendation_generation_specs, recommendation_generation_results,
    recommendation_generation_command_receipts,
    recommendation_model_tasks, recommendation_model_call_lineage,
    recommendation_artifact_master_key_versions,
    recommendation_artifact_deletion_intents
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON
    recommendation_workflow_versions, recommendation_evidence_bindings,
    recommendation_approvals, recommendation_reviews, recommendation_command_receipts,
    recommendation_drafts, recommendation_outbox_messages,
    recommendation_generation_specs, recommendation_generation_results,
    recommendation_generation_command_receipts
TO geo_app;
GRANT UPDATE (status, blocked_at, blocked_reason, draft_payload, draft_payload_hash)
ON recommendation_drafts TO geo_app;
GRANT UPDATE (status, delivered_at, cancelled_at, cancellation_reason)
ON recommendation_outbox_messages TO geo_app;
GRANT SELECT ON
    recommendation_workflow_versions, recommendation_evidence_bindings,
    recommendation_approvals, recommendation_reviews, recommendation_command_receipts,
    recommendation_drafts, recommendation_outbox_messages,
    recommendation_generation_specs, recommendation_generation_results,
    recommendation_generation_command_receipts,
    recommendation_model_tasks, recommendation_model_call_lineage,
    recommendation_artifact_master_key_versions,
    recommendation_artifact_deletion_intents
TO geo_app, geo_worker;
GRANT SELECT ON workflow_c_job_specs TO geo_worker;
GRANT INSERT ON workflow_c_job_specs TO geo_app, geo_worker;
GRANT SELECT, INSERT ON workflow_c_report_snapshot_versions TO geo_app;
GRANT SELECT ON workflow_c_alert_evaluations TO geo_app;
GRANT SELECT ON workflow_c_admin_inbox_notifications TO geo_app;
GRANT SELECT, INSERT ON workflow_c_admin_inbox_notifications TO geo_worker;
GRANT SELECT ON workflow_c_report_snapshot_versions, workflow_c_alert_evaluations TO geo_worker;
GRANT INSERT ON recommendation_model_tasks, recommendation_model_call_lineage,
    recommendation_artifact_deletion_intents TO geo_worker;
GRANT UPDATE (
    model_attempt_id, model_call_log_id, response_hash, output_hash,
    artifact_uri, artifact_manifest_hash, artifact_content_hash,
    derived_artifact_uri, derived_artifact_manifest_hash,
    derived_artifact_content_hash, task_artifact_status, status, error_code, updated_at
) ON recommendation_model_call_lineage TO geo_worker;
GRANT UPDATE (
    phase, lease_owner, lease_token, lease_expires_at, fencing_generation,
    attempt_count, next_attempt_at, crypto_erase_receipt_hash,
    deleted_receipt_hash, last_error_code, deleted_at, updated_at
) ON recommendation_artifact_deletion_intents TO geo_worker;
GRANT UPDATE (status) ON recommendation_artifact_master_key_versions TO geo_worker;

REVOKE ALL ON FUNCTION
    geo_provision_service_identity(uuid, text, timestamptz),
    geo_require_active_service_identity(uuid, text),
    geo_workflow_c_job_spec_payload_is_safe(jsonb),
    geo_assert_workflow_c_job_spec_immutable(),
    geo_assert_recommendation_workflow_append(),
    geo_assert_recommendation_approval(),
    geo_assert_recommendation_draft_change(),
    geo_block_recommendation_drafts_on_stale(),
    geo_assert_recommendation_model_task_change(),
    geo_assert_recommendation_model_lineage_change(),
    geo_assert_recommendation_artifact_key_change(),
    geo_assert_recommendation_artifact_deletion_change(),
    geo_enqueue_recommendation_artifact_deletion(
        uuid, uuid, uuid, text, text, text, text, text, timestamptz, timestamptz
    ),
    geo_claim_recommendation_artifact_deletion(text, timestamptz, integer, integer),
    geo_mark_recommendation_artifact_crypto_erased(
        uuid, uuid, integer, text, timestamptz
    ),
    geo_mark_recommendation_artifact_deleted(uuid, uuid, integer, text, timestamptz),
    geo_retry_recommendation_artifact_deletion(uuid, uuid, integer, text, timestamptz),
    geo_resolve_recommendation_evidence(uuid, text, text)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
TO geo_app, geo_worker;
GRANT EXECUTE ON FUNCTION geo_require_active_service_identity(uuid, text)
TO geo_worker;
GRANT EXECUTE ON FUNCTION
    geo_enqueue_recommendation_artifact_deletion(
        uuid, uuid, uuid, text, text, text, text, text, timestamptz, timestamptz
    ),
    geo_claim_recommendation_artifact_deletion(text, timestamptz, integer, integer),
    geo_mark_recommendation_artifact_crypto_erased(
        uuid, uuid, integer, text, timestamptz
    ),
    geo_mark_recommendation_artifact_deleted(uuid, uuid, integer, text, timestamptz),
    geo_retry_recommendation_artifact_deletion(uuid, uuid, integer, text, timestamptz)
TO geo_worker;

-- Sampling and alert state changes are fenced at the database boundary.  The
-- worker receives only their narrow commit/enqueue procedures; validation,
-- trigger, and lease helpers remain implementation details.
REVOKE ALL ON FUNCTION
    geo_workflow_c_json_has_exact_keys(jsonb, text[]),
    geo_workflow_c_json_is_uuid(jsonb),
    geo_workflow_c_json_is_sha256(jsonb),
    geo_workflow_c_json_is_positive_integer(jsonb),
    geo_workflow_c_json_is_rfc3339(jsonb),
    geo_workflow_c_sampling_job_spec_is_valid(text, jsonb),
    geo_require_workflow_c_sampling_job_fence(
        uuid, uuid, uuid, integer, text, text, uuid, uuid, uuid, integer, integer
    ),
    geo_validate_workflow_c_sampling_observation_input(
        uuid, text, text, jsonb, jsonb, text, jsonb, timestamptz
    ),
    geo_commit_workflow_c_provider_sampling(
        uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer,
        uuid, text, text, jsonb, jsonb, text, jsonb, uuid, text, text, timestamptz
    ),
    geo_commit_workflow_c_manual_sampling(
        uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer,
        uuid, uuid, text, text, text, uuid, uuid, text, text, jsonb, jsonb, text, jsonb, timestamptz
    ),
    geo_record_workflow_c_sampling_failure(
        uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer,
        text, boolean, timestamptz
    ),
    geo_complete_workflow_c_metric_child(
        uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text
    ),
    geo_fail_workflow_c_metric_child(
        uuid, uuid, uuid, integer, text, text, text
    ),
    geo_assert_workflow_c_report_snapshot_version_append(),
    geo_assert_workflow_c_alert_evaluation_immutable(),
    geo_assert_workflow_c_admin_inbox_notification_immutable(),
    geo_require_workflow_c_job_lease(uuid, uuid, uuid, integer, text),
    geo_enqueue_workflow_c_alert_evaluation(
        uuid, uuid, uuid, integer, uuid, integer, timestamptz, uuid, text, jsonb,
        text, uuid, text, jsonb, text, timestamptz
    ),
    geo_complete_workflow_c_alert_evaluation(
        uuid, uuid, uuid, integer, uuid, uuid, integer, uuid, text, text, text,
        text, boolean, jsonb, timestamptz, uuid, text, jsonb, jsonb
    )
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_commit_workflow_c_provider_sampling(
        uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer,
        uuid, text, text, jsonb, jsonb, text, jsonb, uuid, text, text, timestamptz
    ),
    geo_commit_workflow_c_manual_sampling(
        uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer,
        uuid, uuid, text, text, text, uuid, uuid, text, text, jsonb, jsonb, text, jsonb, timestamptz
    ),
    geo_record_workflow_c_sampling_failure(
        uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer,
        text, boolean, timestamptz
    ),
    geo_complete_workflow_c_metric_child(
        uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text
    ),
    geo_fail_workflow_c_metric_child(
        uuid, uuid, uuid, integer, text, text, text
    ),
    geo_enqueue_workflow_c_alert_evaluation(
        uuid, uuid, uuid, integer, uuid, integer, timestamptz, uuid, text, jsonb,
        text, uuid, text, jsonb, text, timestamptz
    ),
    geo_complete_workflow_c_alert_evaluation(
        uuid, uuid, uuid, integer, uuid, uuid, integer, uuid, text, text, text,
        text, boolean, jsonb, timestamptz, uuid, text, jsonb, jsonb
    )
TO geo_worker;

COMMENT ON TABLE recommendation_workflow_versions IS
    'Append-only, evidence-bound Recommendation state. Approval creates drafts only; it never publishes or executes work.';
COMMENT ON TABLE recommendation_artifact_deletion_intents IS
    'Fenced deletion lifecycle for encrypted Recommendation Prompt task artifacts. Manifest crypto-erasure always precedes ciphertext deletion.';
COMMENT ON COLUMN recommendation_model_tasks.output_schema_hash IS
    'Provider-portable structured-output Schema hash; application_output_schema_hash is independently frozen for local validation.';

-- Every SECURITY DEFINER entry point is default-denied.  The three-argument
-- claim overload exists for the single-lease maintenance adapter and must not
-- silently inherit PUBLIC EXECUTE.
REVOKE ALL ON FUNCTION
    geo_provision_service_identity(uuid, text, timestamptz),
    geo_require_active_service_identity(uuid, text),
    geo_assert_recommendation_generation_lease(uuid, uuid, uuid, bigint, timestamptz),
    geo_enqueue_recommendation_generation(
        uuid, uuid, jsonb, text, text, text, timestamptz, uuid, timestamptz, integer
    ),
    geo_cancel_recommendation_generation(uuid, uuid, integer, text, text, timestamptz),
    geo_reserve_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, uuid, uuid, text,
        uuid, text, uuid, integer, uuid, integer, uuid, integer,
        text, text, text, text, text, text, text,
        text, text, text, text, text, text, text,
        timestamptz, uuid, timestamptz
    ),
    geo_activate_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, bigint, timestamptz
    ),
    geo_enqueue_recommendation_artifact_maintenance(timestamptz),
    geo_claim_recommendation_artifact_deletion(text, timestamptz, integer)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_enqueue_recommendation_generation(
        uuid, uuid, jsonb, text, text, text, timestamptz, uuid, timestamptz, integer
    ),
    geo_cancel_recommendation_generation(uuid, uuid, integer, text, text, timestamptz)
TO geo_app;
GRANT EXECUTE ON FUNCTION
    geo_reserve_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, uuid, uuid, text,
        uuid, text, uuid, integer, uuid, integer, uuid, integer,
        text, text, text, text, text, text, text,
        text, text, text, text, text, text, text,
        timestamptz, uuid, timestamptz
    ),
    geo_activate_recommendation_model_task(
        uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, bigint, timestamptz
    ),
    geo_enqueue_recommendation_artifact_maintenance(timestamptz),
    geo_claim_recommendation_artifact_deletion(text, timestamptz, integer),
    geo_require_active_service_identity(uuid, text)
TO geo_worker;

-- Global scheduling is restricted to the worker control plane. A Job worker
-- receives a single Project and must use the project-scoped overloads below.
REVOKE ALL ON FUNCTION
    geo_provision_service_identity(uuid, text, timestamptz),
    geo_enqueue_recommendation_artifact_maintenance(timestamptz),
    geo_claim_recommendation_artifact_deletion(text, timestamptz, integer),
    geo_claim_recommendation_artifact_deletion(text, timestamptz, integer, integer),
    geo_enqueue_recommendation_artifact_maintenance(uuid, timestamptz),
    geo_schedule_recommendation_artifact_maintenance(timestamptz),
    geo_claim_recommendation_artifact_deletion(uuid, text, timestamptz, integer, integer)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_enqueue_recommendation_artifact_maintenance(uuid, timestamptz),
    geo_schedule_recommendation_artifact_maintenance(timestamptz),
    geo_claim_recommendation_artifact_deletion(uuid, text, timestamptz, integer, integer)
TO geo_worker;

-- The synthetic maintenance scheduler emits one Job per Project.  Old global
-- stage/claim overloads are deliberately unavailable at this head so a
-- worker cannot process another Job's Project by accident.
REVOKE ALL ON FUNCTION
    geo_stage_synthetic_artifact_expiry(timestamptz, integer),
    geo_stage_due_synthetic_artifact_expirations(timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(text, integer, integer),
    geo_claim_synthetic_artifact_deletions(text, timestamptz, integer, integer),
    geo_stage_due_synthetic_artifact_expirations(uuid, timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(uuid, text, timestamptz, integer, integer)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_stage_due_synthetic_artifact_expirations(uuid, timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(uuid, text, timestamptz, integer, integer)
TO geo_worker;

ALTER TABLE runtime_service_heartbeats
DROP CONSTRAINT runtime_service_heartbeats_service_type_check;
ALTER TABLE runtime_service_heartbeats
ADD CONSTRAINT runtime_service_heartbeats_service_type_check CHECK (
    service_type IN (
        'task_worker', 'outbox_relay', 'style_browser_worker',
        'synthetic_artifact_maintenance_worker',
        'workflow_c_maintenance_worker', 'workflow_c_maintenance_scheduler',
        'recommendation_artifact_maintenance_worker',
        'recommendation_artifact_maintenance_scheduler'
    )
);
DO $$
DECLARE function_definition text;
DECLARE replacement text;
BEGIN
    function_definition := pg_get_functiondef(
        'geo_worker_record_runtime_heartbeat(text,text,text,text,text)'::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'', ''recommendation_artifact_maintenance_worker'', ''recommendation_artifact_maintenance_scheduler'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Recommendation maintenance heartbeat contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
    function_definition := pg_get_functiondef(
        'geo_worker_runtime_findings(text,text,integer,integer,integer,integer,integer,integer)'
            ::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'', ''recommendation_artifact_maintenance_worker'', ''recommendation_artifact_maintenance_scheduler'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Recommendation maintenance findings contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
END;
$$;
