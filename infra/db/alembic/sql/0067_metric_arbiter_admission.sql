-- A batch may enqueue exactly one Arbiter, and only after every frozen Judge
-- result has a durable, hash-bound projection and those results disagree.  The
-- encrypted Arbiter task deliberately remains opaque to PostgreSQL; its public
-- Job spec is the same minimal, immutable wake/reference shape as a Judge.
CREATE FUNCTION geo_admit_workflow_c_metric_arbiter_child(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_parent_input_hash text,
    p_batch_id uuid,
    p_child jsonb
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE parent_job durable_jobs%ROWTYPE;
DECLARE parent_spec workflow_c_job_specs%ROWTYPE;
DECLARE batch workflow_c_metric_judge_batches%ROWTYPE;
DECLARE child_job_id uuid;
DECLARE child_candidate_id uuid;
DECLARE child_runtime_selection_id uuid;
DECLARE child_runtime_manifest_id uuid;
DECLARE child_runtime_option_id uuid;
DECLARE child_prompt_binding_id uuid;
DECLARE child_prompt_state_id uuid;
DECLARE child_prompt_release_id uuid;
DECLARE child_spec jsonb;
DECLARE child_spec_hash text;
DECLARE child_task_hash text;
DECLARE judge_count integer;
DECLARE judge_output_count integer;
DECLARE judge_projection_count integer;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_parent_job_id IS NULL OR p_lease_token IS NULL OR p_batch_id IS NULL
       OR p_fencing_generation < 1
       OR p_parent_input_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_child) <> 'object'
       OR NOT geo_workflow_c_json_has_exact_keys(p_child, ARRAY[
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
       OR NOT geo_workflow_c_json_is_uuid(p_child->'id')
       OR NOT geo_workflow_c_json_is_uuid(p_child->'candidate_id')
       OR NOT geo_workflow_c_json_is_positive_integer(p_child->'ordinal')
       OR p_child->>'ordinal' <> '1'
       OR jsonb_typeof(p_child->'evaluator_id') <> 'string'
       OR btrim(p_child->>'evaluator_id') = ''
       OR NOT geo_workflow_c_json_is_uuid(p_child->'runtime_selection_id')
       OR NOT geo_workflow_c_json_is_uuid(p_child->'runtime_manifest_id')
       OR NOT geo_workflow_c_json_is_sha256(p_child->'runtime_manifest_hash')
       OR NOT geo_workflow_c_json_is_uuid(p_child->'runtime_option_id')
       OR NOT geo_workflow_c_json_is_sha256(p_child->'runtime_option_hash')
       OR NOT geo_workflow_c_json_is_uuid(p_child->'prompt_binding_id')
       OR NOT geo_workflow_c_json_is_positive_integer(p_child->'prompt_binding_version')
       OR NOT geo_workflow_c_json_is_uuid(p_child->'prompt_frozen_state_id')
       OR NOT geo_workflow_c_json_is_positive_integer(p_child->'prompt_state_version')
       OR NOT geo_workflow_c_json_is_uuid(p_child->'prompt_release_id')
       OR NOT geo_workflow_c_json_is_positive_integer(p_child->'prompt_release_version')
       OR NOT geo_workflow_c_json_is_sha256(p_child->'prompt_release_hash')
       OR jsonb_typeof(p_child->'prompt_purpose') <> 'string'
       OR btrim(p_child->>'prompt_purpose') = ''
       OR NOT geo_workflow_c_json_is_sha256(p_child->'prompt_bundle_hash')
       OR NOT geo_workflow_c_json_is_sha256(p_child->'portable_output_schema_hash')
       OR NOT geo_workflow_c_json_is_sha256(p_child->'application_output_schema_hash')
       OR jsonb_typeof(p_child->'task_ciphertext') <> 'string'
       OR jsonb_typeof(p_child->'task_data_nonce') <> 'string'
       OR jsonb_typeof(p_child->'task_wrapped_data_key') <> 'string'
       OR jsonb_typeof(p_child->'task_wrap_nonce') <> 'string'
       OR NOT geo_workflow_c_json_is_positive_integer(p_child->'task_master_key_version')
       OR p_child->>'task_algorithm' <> 'AES-256-GCM'
       OR NOT geo_workflow_c_json_is_sha256(p_child->'task_hash')
       OR NOT geo_workflow_c_json_is_sha256(p_child->'spec_hash')
       OR jsonb_typeof(p_child->'spec_payload') <> 'object'
       OR NOT geo_workflow_c_job_spec_payload_is_safe(p_child->'spec_payload') THEN
        RAISE EXCEPTION 'Workflow C Metric arbiter admission input is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO parent_job
      FROM durable_jobs
     WHERE project_id = p_project_id AND id = p_parent_job_id
     FOR SHARE;
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
        RAISE EXCEPTION 'Workflow C Metric arbiter parent lease or frozen input was fenced'
            USING ERRCODE = '40001';
    END IF;

    -- This lock serializes the last Judge completion and Arbiter admission.
    SELECT * INTO batch
      FROM workflow_c_metric_judge_batches
     WHERE project_id = p_project_id AND id = p_batch_id
     FOR UPDATE;
    IF batch.id IS NULL OR batch.parent_job_id <> p_parent_job_id
       OR batch.parent_input_hash <> p_parent_input_hash
       OR batch.status <> 'running'
       OR batch.arbiter_child_job_id IS NOT NULL
       OR EXISTS (
            SELECT 1
              FROM workflow_c_metric_model_children AS existing
             WHERE existing.project_id = p_project_id
               AND existing.batch_id = p_batch_id
               AND existing.role = 'arbiter'
       ) THEN
        RAISE EXCEPTION 'Workflow C Metric arbiter batch is not admissible'
            USING ERRCODE = '40001';
    END IF;

    SELECT count(*), count(DISTINCT judge.output_hash), count(projection.child_job_id)
      INTO judge_count, judge_output_count, judge_projection_count
      FROM workflow_c_metric_model_children AS judge
      LEFT JOIN workflow_c_metric_child_output_projections AS projection
        ON projection.project_id = judge.project_id
       AND projection.child_job_id = judge.child_job_id
       AND projection.output_hash = judge.output_hash
     WHERE judge.project_id = p_project_id
       AND judge.batch_id = p_batch_id
       AND judge.role = 'metric_judge'
       AND judge.status = 'succeeded'
       AND judge.output_hash IS NOT NULL;
    IF judge_count < 2 OR judge_output_count < 2
       OR judge_projection_count <> judge_count
       OR EXISTS (
            SELECT 1
              FROM workflow_c_metric_model_children AS judge
             WHERE judge.project_id = p_project_id
               AND judge.batch_id = p_batch_id
               AND judge.role = 'metric_judge'
               AND (judge.status <> 'succeeded' OR judge.output_hash IS NULL)
       ) THEN
        RAISE EXCEPTION 'Workflow C Metric arbiter Judge evidence is incomplete or agrees'
            USING ERRCODE = '40001';
    END IF;

    child_job_id := (p_child->>'id')::uuid;
    child_candidate_id := (p_child->>'candidate_id')::uuid;
    child_runtime_selection_id := (p_child->>'runtime_selection_id')::uuid;
    child_runtime_manifest_id := (p_child->>'runtime_manifest_id')::uuid;
    child_runtime_option_id := (p_child->>'runtime_option_id')::uuid;
    child_prompt_binding_id := (p_child->>'prompt_binding_id')::uuid;
    child_prompt_state_id := (p_child->>'prompt_frozen_state_id')::uuid;
    child_prompt_release_id := (p_child->>'prompt_release_id')::uuid;
    child_spec := p_child->'spec_payload';
    child_spec_hash := p_child->>'spec_hash';
    child_task_hash := p_child->>'task_hash';
    IF child_runtime_selection_id <> child_runtime_option_id
       OR NOT EXISTS (
            SELECT 1
              FROM model_gateway_runtime_options AS runtime_option
              JOIN model_gateway_runtime_manifests AS runtime_manifest
                ON runtime_manifest.project_id = runtime_option.project_id
               AND runtime_manifest.id = runtime_option.manifest_id
             WHERE runtime_option.project_id = p_project_id
               AND runtime_option.id = child_runtime_option_id
               AND runtime_option.manifest_id = child_runtime_manifest_id
               AND runtime_option.option_hash = p_child->>'runtime_option_hash'
               AND runtime_manifest.manifest_hash = p_child->>'runtime_manifest_hash'
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
               AND binding.binding_version = (p_child->>'prompt_binding_version')::integer
               AND binding.frozen_state_id = child_prompt_state_id
               AND binding.release_id = child_prompt_release_id
               AND binding.release_hash = p_child->>'prompt_release_hash'
               AND binding.release_version = (p_child->>'prompt_release_version')::integer
               AND binding.purpose = p_child->>'prompt_purpose'
               AND prompt_state.release_id = child_prompt_release_id
               AND prompt_state.release_hash = p_child->>'prompt_release_hash'
               AND prompt_state.version = (p_child->>'prompt_state_version')::integer
               AND prompt_state.status = 'frozen'
               AND prompt_release.release_hash = p_child->>'prompt_release_hash'
       )
       OR NOT EXISTS (
            SELECT 1
              FROM workflow_c_artifact_master_key_versions AS master_key
             WHERE master_key.master_key_version = (p_child->>'task_master_key_version')::integer
               AND master_key.status IN ('encrypt_decrypt', 'decrypt_only')
       )
       OR child_spec->'schema_version' <> '1'::jsonb
       OR child_spec->>'kind' <> 'workflow_c.metric_arbiter'
       OR NOT geo_workflow_c_json_has_exact_keys(
            child_spec->'metric_model_child', ARRAY[
                'child_job_id', 'parent_job_id', 'batch_id', 'role',
                'parent_input_hash', 'task_hash'
            ]
       )
       OR child_spec->'metric_model_child'->>'child_job_id' <> child_job_id::text
       OR child_spec->'metric_model_child'->>'parent_job_id' <> p_parent_job_id::text
       OR child_spec->'metric_model_child'->>'batch_id' <> p_batch_id::text
       OR child_spec->'metric_model_child'->>'role' <> 'arbiter'
       OR child_spec->'metric_model_child'->>'parent_input_hash' <> p_parent_input_hash
       OR child_spec->'metric_model_child'->>'task_hash' <> child_task_hash
       OR encode(digest(convert_to(geo_jsonb_canonical_text(child_spec), 'UTF8'), 'sha256'), 'hex')
          <> child_spec_hash THEN
        RAISE EXCEPTION 'Workflow C Metric arbiter immutable lineage is invalid'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO durable_jobs(
        id, project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, parent_job_id, replay_nonce, created_at, updated_at
    ) VALUES (
        child_job_id, p_project_id, 'workflow_c.metric_arbiter', 'queued', 5,
        child_task_hash, 'metric-arbiter:' || p_batch_id::text,
        3, clock_timestamp(), p_parent_job_id, 0, clock_timestamp(), clock_timestamp()
    );
    INSERT INTO workflow_c_job_specs(
        project_id, job_id, kind, spec_hash, spec_payload, created_at
    ) VALUES (
        p_project_id, child_job_id, 'workflow_c.metric_arbiter', child_spec_hash,
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
        p_project_id, p_parent_job_id, child_job_id, p_batch_id, 'arbiter', 1,
        p_child->>'evaluator_id', child_candidate_id, p_parent_input_hash,
        child_runtime_selection_id, child_runtime_manifest_id,
        p_child->>'runtime_manifest_hash', child_runtime_option_id,
        p_child->>'runtime_option_hash', child_prompt_binding_id,
        (p_child->>'prompt_binding_version')::integer, child_prompt_state_id,
        (p_child->>'prompt_state_version')::integer, child_prompt_release_id,
        (p_child->>'prompt_release_version')::integer,
        p_child->>'prompt_release_hash', p_child->>'prompt_purpose',
        p_child->>'prompt_bundle_hash', p_child->>'portable_output_schema_hash',
        p_child->>'application_output_schema_hash',
        decode(p_child->>'task_ciphertext', 'base64'),
        decode(p_child->>'task_data_nonce', 'base64'),
        decode(p_child->>'task_wrapped_data_key', 'base64'),
        decode(p_child->>'task_wrap_nonce', 'base64'),
        (p_child->>'task_master_key_version')::integer,
        p_child->>'task_algorithm', child_task_hash, 'queued', clock_timestamp()
    );
    UPDATE workflow_c_metric_judge_batches
       SET arbiter_child_job_id = child_job_id,
           aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1
     WHERE project_id = p_project_id AND id = p_batch_id
       AND status = 'running' AND arbiter_child_job_id IS NULL;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C Metric arbiter batch changed during admission'
            USING ERRCODE = '40001';
    END IF;
    INSERT INTO broker_outbox(
        project_id, job_id, topic, payload, idempotency_key, available_at
    ) VALUES (
        p_project_id, child_job_id, 'workflow_c.metric_arbiter',
        jsonb_build_object('job_id', child_job_id::text, 'project_id', p_project_id::text),
        'wake:workflow_c.metric_arbiter:' || child_job_id::text, clock_timestamp()
    );
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    ) VALUES (
        p_project_id, child_job_id, 'job_enqueued', 'workflow-c-metric-parent', 0,
        jsonb_build_object(
            'parent_job_id', p_parent_job_id::text,
            'batch_id', p_batch_id::text,
            'candidate_id', child_candidate_id::text,
            'task_hash', child_task_hash
        ), clock_timestamp()
    );
    RETURN child_job_id;
END;
$$;

REVOKE ALL ON FUNCTION geo_admit_workflow_c_metric_arbiter_child(
    uuid, uuid, uuid, integer, text, uuid, jsonb
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_admit_workflow_c_metric_arbiter_child(
    uuid, uuid, uuid, integer, text, uuid, jsonb
) TO geo_worker;

COMMENT ON FUNCTION geo_admit_workflow_c_metric_arbiter_child(
    uuid, uuid, uuid, integer, text, uuid, jsonb
) IS 'Atomically creates the one encrypted Metric Arbiter after complete, disagreeing Judge projections.';
