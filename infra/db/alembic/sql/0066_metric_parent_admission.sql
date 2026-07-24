-- Metric children use an encrypted task as their executable input. The normal
-- Workflow C spec is a secret-free wake/reference and therefore has its own
-- canonical hash. Preserve the original immutable-spec behavior for every
-- other kind, but bind metric child references to their encrypted task hash.
CREATE OR REPLACE FUNCTION geo_assert_workflow_c_job_spec_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE metric_child jsonb;
DECLARE expected_role text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Workflow C Job spec is immutable'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR SHARE;
    IF durable.kind <> NEW.kind OR durable.status <> 'queued' THEN
        RAISE EXCEPTION 'Workflow C Job spec does not match its queued Durable Job'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.kind NOT IN ('workflow_c.metric_judge', 'workflow_c.metric_arbiter') THEN
        IF durable.input_hash <> NEW.spec_hash THEN
            RAISE EXCEPTION 'Workflow C Job spec does not match its queued Durable Job'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    expected_role := CASE NEW.kind
        WHEN 'workflow_c.metric_judge' THEN 'metric_judge'
        WHEN 'workflow_c.metric_arbiter' THEN 'arbiter'
    END;
    metric_child := NEW.spec_payload->'metric_model_child';
    IF NOT geo_workflow_c_json_has_exact_keys(
            NEW.spec_payload, ARRAY['schema_version', 'kind', 'metric_model_child']
       )
       OR NEW.spec_payload->'schema_version' <> '1'::jsonb
       OR NEW.spec_payload->>'kind' <> NEW.kind
       OR NOT geo_workflow_c_json_has_exact_keys(metric_child, ARRAY[
            'child_job_id', 'parent_job_id', 'batch_id', 'role',
            'parent_input_hash', 'task_hash'
       ])
       OR NOT geo_workflow_c_json_is_uuid(metric_child->'child_job_id')
       OR NOT geo_workflow_c_json_is_uuid(metric_child->'parent_job_id')
       OR NOT geo_workflow_c_json_is_uuid(metric_child->'batch_id')
       OR metric_child->>'child_job_id' <> NEW.job_id::text
       OR metric_child->>'role' <> expected_role
       OR NOT geo_workflow_c_json_is_sha256(metric_child->'parent_input_hash')
       OR NOT geo_workflow_c_json_is_sha256(metric_child->'task_hash')
       OR metric_child->>'task_hash' <> durable.input_hash
       OR NOT geo_workflow_c_job_spec_payload_is_safe(NEW.spec_payload)
       OR encode(digest(convert_to(geo_jsonb_canonical_text(NEW.spec_payload), 'UTF8'), 'sha256'), 'hex')
          <> NEW.spec_hash THEN
        RAISE EXCEPTION 'Workflow C Metric Job spec does not match its encrypted Durable task'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

-- Metric Judge children use an encrypted task as their executable input. The
-- normal Workflow C spec remains a secret-free wake/reference and therefore
-- has its own canonical hash; the child's Durable input_hash is the encrypted
-- task plaintext hash.  This procedure is the only writer which may create
-- that paired lineage, its parent-bound batch, and its wakeup messages.
CREATE FUNCTION geo_admit_workflow_c_metric_judge_batches(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_parent_input_hash text,
    p_batches jsonb
) RETURNS TABLE (batch_id uuid, child_count integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE parent_job durable_jobs%ROWTYPE;
DECLARE parent_spec workflow_c_job_specs%ROWTYPE;
DECLARE batch_value jsonb;
DECLARE child_value jsonb;
DECLARE result_batch_id uuid;
DECLARE batch_run_id uuid;
DECLARE batch_observation_id uuid;
DECLARE child_job_id uuid;
DECLARE child_candidate_id uuid;
DECLARE child_runtime_selection_id uuid;
DECLARE child_runtime_manifest_id uuid;
DECLARE child_runtime_option_id uuid;
DECLARE child_prompt_binding_id uuid;
DECLARE child_prompt_state_id uuid;
DECLARE child_prompt_release_id uuid;
DECLARE current_child_count integer;
DECLARE seen_evaluators text[];
DECLARE seen_child_ids uuid[];
DECLARE child_spec jsonb;
DECLARE child_spec_hash text;
DECLARE child_task_hash text;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_parent_job_id IS NULL OR p_lease_token IS NULL
       OR p_fencing_generation < 1
       OR p_parent_input_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_batches) <> 'array'
       OR jsonb_array_length(p_batches) < 1 THEN
        RAISE EXCEPTION 'Workflow C Metric parent admission input is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO parent_job
    FROM durable_jobs
    WHERE project_id = p_project_id AND id = p_parent_job_id
    FOR UPDATE;
    SELECT * INTO parent_spec
    FROM workflow_c_job_specs
    WHERE project_id = p_project_id AND job_id = p_parent_job_id
    FOR SHARE;
    IF parent_job.id IS NULL OR parent_spec.job_id IS NULL
       OR parent_job.kind <> 'workflow_c.analysis.semantic_metrics'
       OR parent_spec.kind <> parent_job.kind
       OR parent_job.input_hash <> p_parent_input_hash
       OR parent_spec.spec_hash <> p_parent_input_hash
       OR parent_job.status <> 'running'
       OR parent_job.lease_token IS DISTINCT FROM p_lease_token
       OR parent_job.fencing_generation <> p_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= clock_timestamp()
       OR parent_job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C Metric parent lease or frozen input was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF EXISTS (
        SELECT 1 FROM workflow_c_metric_judge_batches
        WHERE project_id = p_project_id AND parent_job_id = p_parent_job_id
    ) THEN
        RAISE EXCEPTION 'Workflow C Metric parent batches were already admitted'
            USING ERRCODE = '23505';
    END IF;

    FOR batch_value IN SELECT value FROM jsonb_array_elements(p_batches)
    LOOP
        IF NOT geo_workflow_c_json_has_exact_keys(batch_value, ARRAY[
            'id', 'run_id', 'observation_id', 'ordinal', 'planned_batch_count',
            'plans_hash', 'input_set_hash', 'metric_suite_hash', 'children'
        ])
           OR NOT geo_workflow_c_json_is_uuid(batch_value->'id')
           OR NOT geo_workflow_c_json_is_uuid(batch_value->'run_id')
           OR NOT geo_workflow_c_json_is_uuid(batch_value->'observation_id')
           OR NOT geo_workflow_c_json_is_positive_integer(batch_value->'ordinal')
           OR NOT geo_workflow_c_json_is_positive_integer(batch_value->'planned_batch_count')
           OR NOT geo_workflow_c_json_is_sha256(batch_value->'plans_hash')
           OR NOT geo_workflow_c_json_is_sha256(batch_value->'input_set_hash')
           OR NOT geo_workflow_c_json_is_sha256(batch_value->'metric_suite_hash')
           OR jsonb_typeof(batch_value->'children') <> 'array'
           OR jsonb_array_length(batch_value->'children') < 2
           OR (batch_value->>'planned_batch_count')::integer <> jsonb_array_length(p_batches) THEN
            RAISE EXCEPTION 'Workflow C Metric batch admission input is invalid'
                USING ERRCODE = '22023';
        END IF;
        result_batch_id := (batch_value->>'id')::uuid;
        batch_run_id := (batch_value->>'run_id')::uuid;
        batch_observation_id := (batch_value->>'observation_id')::uuid;
        current_child_count := 0;
        seen_evaluators := ARRAY[]::text[];
        seen_child_ids := ARRAY[]::uuid[];

        INSERT INTO workflow_c_metric_judge_batches(
            id, project_id, parent_job_id, run_id, observation_id, ordinal,
            planned_batch_count, plans_hash, parent_input_hash, input_set_hash,
            metric_suite_hash, status, aggregate_version, created_at
        ) VALUES (
            result_batch_id, p_project_id, p_parent_job_id, batch_run_id,
            batch_observation_id, (batch_value->>'ordinal')::integer,
            (batch_value->>'planned_batch_count')::integer,
            batch_value->>'plans_hash', p_parent_input_hash,
            batch_value->>'input_set_hash', batch_value->>'metric_suite_hash',
            'queued', 1, clock_timestamp()
        );

        FOR child_value IN SELECT value FROM jsonb_array_elements(batch_value->'children')
        LOOP
            IF NOT geo_workflow_c_json_has_exact_keys(child_value, ARRAY[
                'id', 'candidate_id', 'ordinal', 'evaluator_id',
                'runtime_selection_id', 'runtime_manifest_id', 'runtime_manifest_hash',
                'runtime_option_id', 'runtime_option_hash', 'prompt_binding_id',
                'prompt_binding_version', 'prompt_frozen_state_id', 'prompt_state_version',
                'prompt_release_id', 'prompt_release_version', 'prompt_release_hash',
                'prompt_purpose', 'prompt_bundle_hash', 'portable_output_schema_hash',
                'application_output_schema_hash', 'task_ciphertext', 'task_data_nonce',
                'task_wrapped_data_key', 'task_wrap_nonce', 'task_master_key_version',
                'task_algorithm', 'task_hash', 'spec_hash', 'spec_payload'
            ])
               OR NOT geo_workflow_c_json_is_uuid(child_value->'id')
               OR NOT geo_workflow_c_json_is_uuid(child_value->'candidate_id')
               OR NOT geo_workflow_c_json_is_positive_integer(child_value->'ordinal')
               OR jsonb_typeof(child_value->'evaluator_id') <> 'string'
               OR btrim(child_value->>'evaluator_id') = ''
               OR NOT geo_workflow_c_json_is_uuid(child_value->'runtime_selection_id')
               OR NOT geo_workflow_c_json_is_uuid(child_value->'runtime_manifest_id')
               OR NOT geo_workflow_c_json_is_sha256(child_value->'runtime_manifest_hash')
               OR NOT geo_workflow_c_json_is_uuid(child_value->'runtime_option_id')
               OR NOT geo_workflow_c_json_is_sha256(child_value->'runtime_option_hash')
               OR NOT geo_workflow_c_json_is_uuid(child_value->'prompt_binding_id')
               OR NOT geo_workflow_c_json_is_positive_integer(child_value->'prompt_binding_version')
               OR NOT geo_workflow_c_json_is_uuid(child_value->'prompt_frozen_state_id')
               OR NOT geo_workflow_c_json_is_positive_integer(child_value->'prompt_state_version')
               OR NOT geo_workflow_c_json_is_uuid(child_value->'prompt_release_id')
               OR NOT geo_workflow_c_json_is_positive_integer(child_value->'prompt_release_version')
               OR NOT geo_workflow_c_json_is_sha256(child_value->'prompt_release_hash')
               OR jsonb_typeof(child_value->'prompt_purpose') <> 'string'
               OR btrim(child_value->>'prompt_purpose') = ''
               OR NOT geo_workflow_c_json_is_sha256(child_value->'prompt_bundle_hash')
               OR NOT geo_workflow_c_json_is_sha256(child_value->'portable_output_schema_hash')
               OR NOT geo_workflow_c_json_is_sha256(child_value->'application_output_schema_hash')
               OR jsonb_typeof(child_value->'task_ciphertext') <> 'string'
               OR jsonb_typeof(child_value->'task_data_nonce') <> 'string'
               OR jsonb_typeof(child_value->'task_wrapped_data_key') <> 'string'
               OR jsonb_typeof(child_value->'task_wrap_nonce') <> 'string'
               OR NOT geo_workflow_c_json_is_positive_integer(child_value->'task_master_key_version')
               OR child_value->>'task_algorithm' <> 'AES-256-GCM'
               OR NOT geo_workflow_c_json_is_sha256(child_value->'task_hash')
               OR NOT geo_workflow_c_json_is_sha256(child_value->'spec_hash')
               OR jsonb_typeof(child_value->'spec_payload') <> 'object'
               OR NOT geo_workflow_c_job_spec_payload_is_safe(child_value->'spec_payload') THEN
                RAISE EXCEPTION 'Workflow C Metric child admission input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            child_job_id := (child_value->>'id')::uuid;
            child_candidate_id := (child_value->>'candidate_id')::uuid;
            child_runtime_selection_id := (child_value->>'runtime_selection_id')::uuid;
            child_runtime_manifest_id := (child_value->>'runtime_manifest_id')::uuid;
            child_runtime_option_id := (child_value->>'runtime_option_id')::uuid;
            child_prompt_binding_id := (child_value->>'prompt_binding_id')::uuid;
            child_prompt_state_id := (child_value->>'prompt_frozen_state_id')::uuid;
            child_prompt_release_id := (child_value->>'prompt_release_id')::uuid;
            child_spec := child_value->'spec_payload';
            child_spec_hash := child_value->>'spec_hash';
            child_task_hash := child_value->>'task_hash';
            IF child_runtime_selection_id <> child_runtime_option_id
               OR child_job_id = ANY(seen_child_ids)
               OR child_value->>'evaluator_id' = ANY(seen_evaluators)
               OR NOT EXISTS (
                    SELECT 1
                    FROM model_gateway_runtime_options AS runtime_option
                    JOIN model_gateway_runtime_manifests AS runtime_manifest
                      ON runtime_manifest.project_id = runtime_option.project_id
                     AND runtime_manifest.id = runtime_option.manifest_id
                    WHERE runtime_option.project_id = p_project_id
                      AND runtime_option.id = child_runtime_option_id
                      AND runtime_option.manifest_id = child_runtime_manifest_id
                      AND runtime_option.option_hash = child_value->>'runtime_option_hash'
                      AND runtime_manifest.manifest_hash = child_value->>'runtime_manifest_hash'
                      AND runtime_manifest.status = 'approved'
               )
               OR NOT EXISTS (
                    SELECT 1
                    FROM prompt_program_bindings AS binding
                    JOIN prompt_program_release_states AS prompt_state
                      ON prompt_state.project_id = binding.project_id
                     AND prompt_state.id = binding.frozen_state_id
                    JOIN prompt_program_releases AS prompt_release
                      ON prompt_release.project_id = binding.project_id
                     AND prompt_release.id = binding.release_id
                    WHERE binding.project_id = p_project_id
                      AND binding.id = child_prompt_binding_id
                      AND binding.binding_version = (child_value->>'prompt_binding_version')::integer
                      AND binding.frozen_state_id = child_prompt_state_id
                      AND binding.release_id = child_prompt_release_id
                      AND binding.release_hash = child_value->>'prompt_release_hash'
                      AND binding.release_version = (child_value->>'prompt_release_version')::integer
                      AND binding.purpose = child_value->>'prompt_purpose'
                      AND prompt_state.release_id = child_prompt_release_id
                      AND prompt_state.release_hash = child_value->>'prompt_release_hash'
                      AND prompt_state.version = (child_value->>'prompt_state_version')::integer
                      AND prompt_state.status = 'frozen'
                      AND prompt_release.release_hash = child_value->>'prompt_release_hash'
               )
               OR NOT EXISTS (
                    SELECT 1
                    FROM workflow_c_artifact_master_key_versions AS master_key
                    WHERE master_key.master_key_version
                              = (child_value->>'task_master_key_version')::integer
                      AND master_key.status IN ('encrypt_decrypt', 'decrypt_only')
               )
               OR child_spec->'schema_version' <> '1'::jsonb
               OR child_spec->>'kind' <> 'workflow_c.metric_judge'
               OR NOT geo_workflow_c_json_has_exact_keys(
                    child_spec->'metric_model_child', ARRAY[
                        'child_job_id', 'parent_job_id', 'batch_id', 'role',
                        'parent_input_hash', 'task_hash'
                    ]
               )
               OR child_spec->'metric_model_child'->>'child_job_id' <> child_job_id::text
               OR child_spec->'metric_model_child'->>'parent_job_id' <> p_parent_job_id::text
               OR child_spec->'metric_model_child'->>'batch_id' <> result_batch_id::text
               OR child_spec->'metric_model_child'->>'role' <> 'metric_judge'
               OR child_spec->'metric_model_child'->>'parent_input_hash' <> p_parent_input_hash
               OR child_spec->'metric_model_child'->>'task_hash' <> child_task_hash
               OR encode(digest(convert_to(geo_jsonb_canonical_text(child_spec), 'UTF8'), 'sha256'), 'hex')
                  <> child_spec_hash THEN
                RAISE EXCEPTION 'Workflow C Metric child immutable lineage is invalid'
                    USING ERRCODE = '22023';
            END IF;

            INSERT INTO durable_jobs(
                id, project_id, kind, status, priority, input_hash, idempotency_key,
                max_attempts, next_run_at, parent_job_id, replay_nonce, created_at, updated_at
            ) VALUES (
                child_job_id, p_project_id, 'workflow_c.metric_judge', 'queued', 5,
                child_task_hash,
                'metric-judge:' || result_batch_id::text || ':' || child_candidate_id::text,
                3, clock_timestamp(), p_parent_job_id, 0, clock_timestamp(), clock_timestamp()
            );
            INSERT INTO workflow_c_job_specs(
                project_id, job_id, kind, spec_hash, spec_payload, created_at
            ) VALUES (
                p_project_id, child_job_id, 'workflow_c.metric_judge', child_spec_hash,
                child_spec, clock_timestamp()
            );
            INSERT INTO workflow_c_metric_model_children(
                project_id, parent_job_id, child_job_id, batch_id, role, ordinal,
                evaluator_id, candidate_id, parent_input_hash, runtime_selection_id,
                runtime_manifest_id, runtime_manifest_hash, runtime_option_id,
                runtime_option_hash, prompt_binding_id, prompt_binding_version,
                prompt_frozen_state_id, prompt_state_version, prompt_release_id,
                prompt_release_version, prompt_release_hash, prompt_purpose,
                prompt_bundle_hash, portable_output_schema_hash,
                application_output_schema_hash, task_ciphertext, task_data_nonce,
                task_wrapped_data_key, task_wrap_nonce, task_master_key_version,
                task_algorithm, task_hash, status, created_at
            ) VALUES (
                p_project_id, p_parent_job_id, child_job_id, result_batch_id,
                'metric_judge', (child_value->>'ordinal')::integer,
                child_value->>'evaluator_id', child_candidate_id, p_parent_input_hash,
                child_runtime_selection_id, child_runtime_manifest_id,
                child_value->>'runtime_manifest_hash', child_runtime_option_id,
                child_value->>'runtime_option_hash', child_prompt_binding_id,
                (child_value->>'prompt_binding_version')::integer, child_prompt_state_id,
                (child_value->>'prompt_state_version')::integer, child_prompt_release_id,
                (child_value->>'prompt_release_version')::integer,
                child_value->>'prompt_release_hash', child_value->>'prompt_purpose',
                child_value->>'prompt_bundle_hash', child_value->>'portable_output_schema_hash',
                child_value->>'application_output_schema_hash',
                decode(child_value->>'task_ciphertext', 'base64'),
                decode(child_value->>'task_data_nonce', 'base64'),
                decode(child_value->>'task_wrapped_data_key', 'base64'),
                decode(child_value->>'task_wrap_nonce', 'base64'),
                (child_value->>'task_master_key_version')::integer,
                child_value->>'task_algorithm', child_task_hash, 'queued', clock_timestamp()
            );
            INSERT INTO broker_outbox(
                project_id, job_id, topic, payload, idempotency_key, available_at
            ) VALUES (
                p_project_id, child_job_id, 'workflow_c.metric_judge',
                jsonb_build_object('job_id', child_job_id::text, 'project_id', p_project_id::text),
                'wake:workflow_c.metric_judge:' || child_job_id::text, clock_timestamp()
            );
            INSERT INTO durable_job_events(
                project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
            ) VALUES (
                p_project_id, child_job_id, 'job_enqueued', 'workflow-c-metric-parent', 0,
                jsonb_build_object(
                    'parent_job_id', p_parent_job_id::text,
                    'batch_id', result_batch_id::text,
                    'candidate_id', child_candidate_id::text,
                    'task_hash', child_task_hash
                ), clock_timestamp()
            );
            seen_evaluators := array_append(seen_evaluators, child_value->>'evaluator_id');
            seen_child_ids := array_append(seen_child_ids, child_job_id);
            current_child_count := current_child_count + 1;
        END LOOP;
        RETURN QUERY SELECT result_batch_id AS batch_id, current_child_count AS child_count;
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION geo_admit_workflow_c_metric_judge_batches(
    uuid, uuid, uuid, integer, text, jsonb
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_admit_workflow_c_metric_judge_batches(
    uuid, uuid, uuid, integer, text, jsonb
) TO geo_worker;

COMMENT ON FUNCTION geo_admit_workflow_c_metric_judge_batches(
    uuid, uuid, uuid, integer, text, jsonb
) IS 'Atomically creates encrypted Metric Judge child jobs, immutable references, batches and wakeups from one fenced semantic-metrics parent.';
