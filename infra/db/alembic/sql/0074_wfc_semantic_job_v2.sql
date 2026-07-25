-- Semantic v2 specs carry only an immutable manifest pointer. Raw answer bytes
-- stay in independently encrypted Provider/manual artifact stores and can be
-- materialized only by a currently fenced Worker.

ALTER TABLE workflow_c_job_specs
DROP CONSTRAINT workflow_c_job_specs_check;

ALTER TABLE workflow_c_job_specs
ADD CONSTRAINT workflow_c_job_specs_check CHECK (
    jsonb_typeof(spec_payload) = 'object'
    AND spec_payload->>'kind' = kind
    AND geo_workflow_c_job_spec_payload_is_safe(spec_payload)
    AND (
        spec_payload->'schema_version' = '1'::jsonb
        OR (
            kind = 'workflow_c.analysis.semantic_metrics'
            AND spec_payload->'schema_version' = '2'::jsonb
        )
    )
);

CREATE FUNCTION geo_enqueue_workflow_c_semantic_metric_job_v2(
    p_project_id uuid,
    p_manifest_id uuid,
    p_manifest_hash text,
    p_sampling_run_id uuid,
    p_sampling_run_version integer,
    p_sampling_suite_hash text,
    p_metric_protocol_id uuid,
    p_metric_protocol_hash text,
    p_baseline_snapshot_hash text,
    p_source_stratum_hash text,
    p_capture_method text,
    p_frozen_by text,
    p_frozen_at timestamptz,
    p_manifest_payload jsonb,
    p_spec_hash text,
    p_spec_payload jsonb,
    p_job_idempotency_key text,
    p_max_attempts integer
) RETURNS TABLE (
    job_id uuid,
    input_hash text,
    manifest_id uuid,
    manifest_hash text,
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE protocol_row workflow_c_metric_protocol_versions%ROWTYPE;
DECLARE run_row workflow_c_sampling_runs%ROWTYPE;
DECLARE suite_row workflow_c_sampling_suites%ROWTYPE;
DECLARE task_row workflow_c_sampling_tasks%ROWTYPE;
DECLARE observation_row workflow_c_sampling_observations%ROWTYPE;
DECLARE attempt_row workflow_c_sampling_attempts%ROWTYPE;
DECLARE source_job durable_jobs%ROWTYPE;
DECLARE manual_row workflow_c_sampling_manual_imports%ROWTYPE;
DECLARE existing_manifest workflow_c_analysis_input_manifests%ROWTYPE;
DECLARE durable durable_jobs%ROWTYPE;
DECLARE stored_spec workflow_c_job_specs%ROWTYPE;
DECLARE stored_outbox broker_outbox%ROWTYPE;
DECLARE item jsonb;
DECLARE item_count integer;
DECLARE observed_count integer;
DECLARE item_ordinal integer;
DECLARE artifact_kind text;
DECLARE outbox_key text;
DECLARE expected_wakeup jsonb;
DECLARE was_replayed boolean := false;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Semantic analysis is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_manifest_id IS NULL OR p_sampling_run_id IS NULL OR p_metric_protocol_id IS NULL
       OR p_manifest_hash !~ '^[0-9a-f]{64}$'
       OR p_sampling_suite_hash !~ '^[0-9a-f]{64}$'
       OR p_metric_protocol_hash !~ '^[0-9a-f]{64}$'
       OR p_source_stratum_hash !~ '^[0-9a-f]{64}$'
       OR (p_baseline_snapshot_hash IS NOT NULL
           AND p_baseline_snapshot_hash !~ '^[0-9a-f]{64}$')
       OR p_sampling_run_version < 1
       OR p_capture_method NOT IN (
            'provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui'
       )
       OR btrim(coalesce(p_frozen_by, '')) = '' OR length(p_frozen_by) > 500
       OR p_frozen_at IS NULL
       OR p_spec_hash !~ '^[0-9a-f]{64}$'
       OR btrim(coalesce(p_job_idempotency_key, '')) = ''
       OR length(p_job_idempotency_key) > 500
       OR p_max_attempts IS NULL OR p_max_attempts < 1 THEN
        RAISE EXCEPTION 'Semantic analysis admission input is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NOT geo_workflow_c_json_has_exact_keys(p_manifest_payload, ARRAY[
            'schema_version', 'project_id', 'sampling_run_id', 'sampling_run_version',
            'sampling_suite_hash', 'metric_protocol_id', 'metric_protocol_hash',
            'fact_snapshot_id', 'fact_snapshot_hash', 'prompt_release_id',
            'prompt_release_hash', 'corpus_version_id', 'corpus_version_hash',
            'baseline_snapshot_hash', 'source_stratum_hash', 'capture_method',
            'stratum', 'items'
       ])
       OR p_manifest_payload->'schema_version' <> '1'::jsonb
       OR p_manifest_payload->>'project_id' <> p_project_id::text
       OR p_manifest_payload->>'sampling_run_id' <> p_sampling_run_id::text
       OR (p_manifest_payload->>'sampling_run_version')::integer
            <> p_sampling_run_version
       OR p_manifest_payload->>'sampling_suite_hash' <> p_sampling_suite_hash
       OR p_manifest_payload->>'metric_protocol_id' <> p_metric_protocol_id::text
       OR p_manifest_payload->>'metric_protocol_hash' <> p_metric_protocol_hash
       OR p_manifest_payload->>'baseline_snapshot_hash'
            IS DISTINCT FROM p_baseline_snapshot_hash
       OR p_manifest_payload->>'source_stratum_hash' <> p_source_stratum_hash
       OR p_manifest_payload->>'capture_method' <> p_capture_method
       OR jsonb_typeof(p_manifest_payload->'items') <> 'array'
       OR jsonb_array_length(p_manifest_payload->'items') < 1
       OR jsonb_typeof(p_manifest_payload->'stratum') <> 'object'
       OR p_manifest_payload->'stratum'->>'sampling_source_stratum_hash'
            <> p_source_stratum_hash
       OR p_manifest_payload->'stratum'->>'capture_method' <> p_capture_method
       OR p_manifest_payload->'stratum'->>'question_cluster' <> 'all'
       OR encode(digest(convert_to(
            geo_workflow_c_python_canonical_text(p_manifest_payload), 'UTF8'
          ), 'sha256'), 'hex') <> p_manifest_hash THEN
        RAISE EXCEPTION 'Semantic analysis manifest is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NOT geo_workflow_c_json_has_exact_keys(p_spec_payload, ARRAY[
            'schema_version', 'kind', 'semantic_metrics'
       ])
       OR p_spec_payload->'schema_version' <> '2'::jsonb
       OR p_spec_payload->>'kind' <> 'workflow_c.analysis.semantic_metrics'
       OR NOT geo_workflow_c_json_has_exact_keys(
            p_spec_payload->'semantic_metrics', ARRAY['manifest_id', 'manifest_hash']
       )
       OR p_spec_payload->'semantic_metrics'->>'manifest_id' <> p_manifest_id::text
       OR p_spec_payload->'semantic_metrics'->>'manifest_hash' <> p_manifest_hash
       OR NOT geo_workflow_c_job_spec_payload_is_safe(p_spec_payload)
       OR encode(digest(convert_to(
            geo_workflow_c_python_canonical_text(p_spec_payload), 'UTF8'
          ), 'sha256'), 'hex') <> p_spec_hash THEN
        RAISE EXCEPTION 'Semantic analysis Job spec is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'workflow-c-semantic-v2:' || p_project_id::text || ':' || p_job_idempotency_key,
        0
    ));
    SELECT * INTO protocol_row FROM workflow_c_metric_protocol_versions
     WHERE project_id = p_project_id AND id = p_metric_protocol_id FOR SHARE;
    SELECT * INTO run_row FROM workflow_c_sampling_runs
     WHERE project_id = p_project_id AND id = p_sampling_run_id FOR SHARE;
    SELECT * INTO suite_row FROM workflow_c_sampling_suites
     WHERE project_id = p_project_id AND id = run_row.suite_id FOR SHARE;
    IF protocol_row.id IS NULL OR protocol_row.status <> 'approved'
       OR protocol_row.protocol_hash <> p_metric_protocol_hash
       OR run_row.id IS NULL OR run_row.status <> 'completed'
       OR run_row.version <> p_sampling_run_version
       OR run_row.suite_hash <> p_sampling_suite_hash
       OR suite_row.id IS NULL OR suite_row.suite_hash <> p_sampling_suite_hash
       OR suite_row.source_stratum_hash <> p_source_stratum_hash
       OR suite_row.capture_method <> p_capture_method
       OR p_manifest_payload->>'fact_snapshot_id'
            <> protocol_row.definition->>'fact_snapshot_id'
       OR p_manifest_payload->>'fact_snapshot_hash'
            <> protocol_row.definition->>'fact_snapshot_hash'
       OR p_manifest_payload->>'prompt_release_id'
            <> protocol_row.definition->>'prompt_release_id'
       OR p_manifest_payload->>'prompt_release_hash'
            <> protocol_row.definition->>'prompt_release_hash'
       OR p_manifest_payload->>'corpus_version_id'
            <> protocol_row.definition->>'corpus_version_id'
       OR p_manifest_payload->>'corpus_version_hash'
            <> protocol_row.definition->>'corpus_version_hash'
       OR p_baseline_snapshot_hash IS DISTINCT FROM (CASE
            WHEN jsonb_array_length(protocol_row.definition->'baseline_question_scores') = 0
                THEN NULL
            ELSE encode(digest(convert_to(
                geo_workflow_c_python_canonical_text(
                    protocol_row.definition->'baseline_question_scores'
                ), 'UTF8'
            ), 'sha256'), 'hex')
          END)
       OR p_manifest_payload->'stratum'->>'provider'
            <> suite_row.payload->'suite'->'source_stratum'->>'platform'
       OR p_manifest_payload->'stratum'->>'reported_model'
            <> suite_row.payload->'suite'->'source_stratum'->>'reported_model'
       OR p_manifest_payload->'stratum'->>'locale'
            <> suite_row.payload->'suite'->'source_stratum'->>'locale'
       OR p_manifest_payload->'stratum'->>'region'
            <> suite_row.payload->'suite'->'source_stratum'->>'region'
       OR p_manifest_payload->'stratum'->>'source_composition_hash'
            <> p_sampling_suite_hash THEN
        RAISE EXCEPTION 'Semantic analysis approved protocol or Sampling Run is stale'
            USING ERRCODE = '40001';
    END IF;

    item_count := jsonb_array_length(p_manifest_payload->'items');
    SELECT count(*) INTO observed_count FROM workflow_c_sampling_tasks
     WHERE project_id = p_project_id AND run_id = p_sampling_run_id;
    IF item_count <> observed_count OR item_count <> run_row.reserved_task_count
       OR item_count <> suite_row.planned_task_count THEN
        RAISE EXCEPTION 'Semantic analysis planned denominator changed'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO existing_manifest FROM workflow_c_analysis_input_manifests
     WHERE project_id = p_project_id AND id = p_manifest_id FOR SHARE;
    IF FOUND AND (
        existing_manifest.manifest_hash <> p_manifest_hash
        OR existing_manifest.payload IS DISTINCT FROM p_manifest_payload
    ) THEN
        RAISE EXCEPTION 'Semantic analysis manifest idempotency identity conflicts'
            USING ERRCODE = '23505';
    END IF;

    IF NOT FOUND THEN
        FOR item IN SELECT value FROM jsonb_array_elements(p_manifest_payload->'items')
        LOOP
            IF NOT geo_workflow_c_json_has_exact_keys(item, ARRAY[
                    'ordinal', 'task_id', 'task_key', 'question_id',
                    'question_version', 'question_cluster', 'repetition',
                    'observation_id', 'observation_hash', 'observation_status',
                    'attempt_id', 'source_job_id', 'provider_model_attempt_id',
                    'output_hash', 'artifact_kind', 'artifact_id',
                    'artifact_manifest_hash', 'artifact_content_hash',
                    'actual_location_hash', 'item_hash'
               ])
               OR NOT geo_workflow_c_json_is_positive_integer(item->'ordinal')
               OR NOT geo_workflow_c_json_is_positive_integer(item->'repetition')
               OR NOT geo_workflow_c_json_is_sha256(item->'task_key')
               OR NOT geo_workflow_c_json_is_sha256(item->'observation_hash')
               OR NOT geo_workflow_c_json_is_sha256(item->'actual_location_hash')
               OR NOT geo_workflow_c_json_is_sha256(item->'item_hash')
               OR encode(digest(convert_to(
                    geo_workflow_c_python_canonical_text(item - 'item_hash'), 'UTF8'
                  ), 'sha256'), 'hex') <> item->>'item_hash' THEN
                RAISE EXCEPTION 'Semantic analysis manifest item is invalid'
                    USING ERRCODE = '22023';
            END IF;
            item_ordinal := (item->>'ordinal')::integer;
            artifact_kind := item->>'artifact_kind';
            SELECT * INTO task_row FROM workflow_c_sampling_tasks
             WHERE project_id = p_project_id AND id = (item->>'task_id')::uuid
             FOR SHARE;
            SELECT * INTO observation_row FROM workflow_c_sampling_observations
             WHERE project_id = p_project_id AND id = (item->>'observation_id')::uuid
             FOR SHARE;
            SELECT * INTO attempt_row FROM workflow_c_sampling_attempts
             WHERE project_id = p_project_id AND id = (item->>'attempt_id')::uuid
             FOR SHARE;
            SELECT * INTO source_job FROM durable_jobs
             WHERE project_id = p_project_id AND id = (item->>'source_job_id')::uuid
             FOR SHARE;
            IF task_row.id IS NULL OR task_row.run_id <> p_sampling_run_id
               OR task_row.status <> 'succeeded'
               OR task_row.task_key <> item->>'task_key'
               OR task_row.source_stratum_hash <> p_source_stratum_hash
               OR task_row.capture_method <> p_capture_method
               OR task_row.question_id <> item->>'question_id'
               OR task_row.question_version <> item->>'question_version'
               OR task_row.repetition <> (item->>'repetition')::integer
               OR protocol_row.definition->'question_clusters'->>task_row.question_id
                    <> item->>'question_cluster'
               OR observation_row.id IS NULL OR observation_row.run_id <> p_sampling_run_id
               OR observation_row.task_id <> task_row.id
               OR observation_row.observation_hash <> item->>'observation_hash'
               OR observation_row.status <> item->>'observation_status'
               OR observation_row.actual_location_evidence_hash IS NULL
               OR attempt_row.id IS NULL OR attempt_row.id <> observation_row.attempt_id
               OR attempt_row.task_id <> task_row.id OR attempt_row.status <> 'succeeded'
               OR attempt_row.actual_location_hash <> item->>'actual_location_hash'
               OR source_job.id IS NULL OR source_job.id <> attempt_row.durable_job_id
               OR source_job.status <> 'succeeded' THEN
                RAISE EXCEPTION 'Semantic analysis manifest item lineage changed'
                    USING ERRCODE = '40001';
            END IF;

            IF p_capture_method IN ('provider_api', 'proxy_grounded_api') THEN
                IF artifact_kind <> 'provider'
                   OR (item->>'provider_model_attempt_id')::uuid
                        <> attempt_row.provider_attempt_id
                   OR item->>'output_hash' <> attempt_row.output_hash
                   OR item->>'artifact_manifest_hash'
                        <> observation_row.evidence_json->'derived_artifact'->>'manifest_hash'
                   OR item->>'artifact_content_hash'
                        <> observation_row.evidence_json->'derived_artifact'->>'content_hash'
                   OR observation_row.evidence_json->>'storage_decision' <> 'allowed'
                   OR observation_row.evidence_json->>'usage_audience' <> 'internal_worker'
                   OR NOT EXISTS (
                        SELECT 1
                          FROM model_gateway_artifact_bundles AS bundle
                          JOIN model_gateway_artifacts AS artifact
                            ON artifact.project_id = bundle.project_id
                           AND artifact.bundle_id = bundle.id
                           AND artifact.kind = 'derived'
                         WHERE bundle.project_id = p_project_id
                           AND bundle.job_id = source_job.id
                           AND bundle.attempt_id = attempt_row.provider_attempt_id
                           AND bundle.status = 'committed'
                           AND bundle.storage_decision = 'allowed'
                           AND bundle.audience = 'internal_worker'
                           AND artifact.manifest_hash = item->>'artifact_manifest_hash'
                           AND artifact.content_hash = item->>'artifact_content_hash'
                           AND artifact.expires_at > p_frozen_at
                   ) THEN
                    RAISE EXCEPTION 'Semantic Provider artifact is not recoverable'
                        USING ERRCODE = '40001';
                END IF;
            ELSIF p_capture_method = 'manual_ui' THEN
                SELECT * INTO manual_row FROM workflow_c_sampling_manual_imports
                 WHERE project_id = p_project_id AND attempt_id = attempt_row.id FOR SHARE;
                IF artifact_kind <> 'manual' OR manual_row.id IS NULL
                   OR manual_row.status <> 'committed'
                   OR (item->>'artifact_id')::uuid <> manual_row.artifact_manifest_id
                   OR item->>'artifact_manifest_hash' <> manual_row.artifact_manifest_hash
                   OR item->>'artifact_content_hash' <> manual_row.artifact_content_hash
                   OR NOT EXISTS (
                        SELECT 1 FROM workflow_c_manual_artifacts AS artifact
                         WHERE artifact.project_id = p_project_id
                           AND artifact.artifact_id = manual_row.artifact_manifest_id
                           AND artifact.run_id = p_sampling_run_id
                           AND artifact.task_id = task_row.id
                           AND artifact.status = 'active'
                           AND artifact.manifest_hash = manual_row.artifact_manifest_hash
                           AND artifact.redacted_content_hash = manual_row.artifact_content_hash
                           AND artifact.expires_at > p_frozen_at
                   ) THEN
                    RAISE EXCEPTION 'Semantic manual artifact is not recoverable'
                        USING ERRCODE = '40001';
                END IF;
            ELSE
                RAISE EXCEPTION 'Automated UI manifests require the excluded Board B admission'
                    USING ERRCODE = '0A000';
            END IF;
        END LOOP;

        INSERT INTO workflow_c_analysis_input_manifests(
            id, project_id, manifest_hash, sampling_run_id, sampling_run_version,
            sampling_suite_hash, metric_protocol_id, metric_protocol_hash,
            fact_snapshot_id, fact_snapshot_hash, prompt_release_id,
            prompt_release_hash, corpus_version_id, corpus_version_hash,
            baseline_snapshot_hash, source_stratum_hash, capture_method,
            planned_slot_count, observation_count, payload, frozen_by, frozen_at
        ) VALUES (
            p_manifest_id, p_project_id, p_manifest_hash, p_sampling_run_id,
            p_sampling_run_version, p_sampling_suite_hash, p_metric_protocol_id,
            p_metric_protocol_hash,
            (p_manifest_payload->>'fact_snapshot_id')::uuid,
            p_manifest_payload->>'fact_snapshot_hash',
            (p_manifest_payload->>'prompt_release_id')::uuid,
            p_manifest_payload->>'prompt_release_hash',
            (p_manifest_payload->>'corpus_version_id')::uuid,
            p_manifest_payload->>'corpus_version_hash', p_baseline_snapshot_hash,
            p_source_stratum_hash, p_capture_method, item_count, item_count,
            p_manifest_payload, btrim(p_frozen_by), p_frozen_at
        );
        INSERT INTO workflow_c_analysis_input_manifest_items(
            manifest_id, project_id, ordinal, task_id, task_key, question_id,
            question_version, question_cluster, repetition, observation_id,
            observation_hash, observation_status, attempt_id, source_job_id,
            provider_model_attempt_id, output_hash, artifact_kind, artifact_id,
            artifact_manifest_hash, artifact_content_hash, actual_location_hash,
            item_hash, payload
        )
        SELECT p_manifest_id, p_project_id, (value->>'ordinal')::integer,
            (value->>'task_id')::uuid, value->>'task_key', value->>'question_id',
            value->>'question_version', value->>'question_cluster',
            (value->>'repetition')::integer, (value->>'observation_id')::uuid,
            value->>'observation_hash', value->>'observation_status',
            (value->>'attempt_id')::uuid, (value->>'source_job_id')::uuid,
            CASE WHEN value->>'provider_model_attempt_id' IS NULL THEN NULL
                 ELSE (value->>'provider_model_attempt_id')::uuid END,
            value->>'output_hash', value->>'artifact_kind',
            CASE WHEN value->>'artifact_id' IS NULL THEN NULL
                 ELSE (value->>'artifact_id')::uuid END,
            value->>'artifact_manifest_hash', value->>'artifact_content_hash',
            value->>'actual_location_hash', value->>'item_hash', value
          FROM jsonb_array_elements(p_manifest_payload->'items');
    ELSE
        IF (SELECT count(*) FROM workflow_c_analysis_input_manifest_items AS stored_item
             WHERE stored_item.project_id = p_project_id
               AND stored_item.manifest_id = p_manifest_id) <> item_count
           OR EXISTS (
                SELECT 1 FROM jsonb_array_elements(p_manifest_payload->'items') expected
                 LEFT JOIN workflow_c_analysis_input_manifest_items stored
                   ON stored.project_id = p_project_id
                  AND stored.manifest_id = p_manifest_id
                  AND stored.ordinal = (expected->>'ordinal')::integer
                WHERE stored.payload IS DISTINCT FROM expected
           ) THEN
            RAISE EXCEPTION 'Semantic analysis manifest replay differs from stored items'
                USING ERRCODE = '23505';
        END IF;
    END IF;

    outbox_key := 'wake:workflow_c.analysis.semantic_metrics:' || p_job_idempotency_key;
    SELECT * INTO durable FROM durable_jobs
     WHERE project_id = p_project_id
       AND kind = 'workflow_c.analysis.semantic_metrics'
       AND idempotency_key = p_job_idempotency_key AND replay_nonce = 0
     FOR SHARE;
    IF FOUND THEN
        was_replayed := true;
        IF durable.input_hash <> p_spec_hash OR durable.max_attempts <> p_max_attempts THEN
            RAISE EXCEPTION 'Semantic analysis Job Idempotency-Key conflicts'
                USING ERRCODE = '23505';
        END IF;
        SELECT spec.* INTO stored_spec FROM workflow_c_job_specs AS spec
         WHERE spec.project_id = p_project_id AND spec.job_id = durable.id FOR SHARE;
        IF stored_spec.job_id IS NULL OR stored_spec.kind <> durable.kind
           OR stored_spec.spec_hash <> p_spec_hash
           OR stored_spec.spec_payload IS DISTINCT FROM p_spec_payload THEN
            RAISE EXCEPTION 'Semantic analysis immutable Job spec conflicts'
                USING ERRCODE = '23505';
        END IF;
    ELSE
        INSERT INTO durable_jobs(
            project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, replay_nonce, created_at, updated_at
        ) VALUES (
            p_project_id, 'workflow_c.analysis.semantic_metrics', 'queued', 0,
            p_spec_hash, p_job_idempotency_key, p_max_attempts,
            p_frozen_at, 0, p_frozen_at, p_frozen_at
        ) RETURNING * INTO durable;
        INSERT INTO workflow_c_job_specs(
            project_id, job_id, kind, spec_hash, spec_payload, created_at
        ) VALUES (
            p_project_id, durable.id, durable.kind, p_spec_hash,
            p_spec_payload, p_frozen_at
        );
        INSERT INTO broker_outbox(
            project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            p_project_id, durable.id, durable.kind,
            jsonb_build_object('job_id', durable.id::text, 'project_id', p_project_id::text),
            outbox_key, p_frozen_at
        );
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation,
            details, created_at
        ) VALUES (
            p_project_id, durable.id, 'job_enqueued', 'workflow-c-semantic-producer', 0,
            jsonb_build_object(
                'spec_hash', p_spec_hash, 'manifest_id', p_manifest_id::text,
                'manifest_hash', p_manifest_hash, 'idempotency_key', p_job_idempotency_key
            ), p_frozen_at
        );
    END IF;
    expected_wakeup := jsonb_build_object(
        'job_id', durable.id::text, 'project_id', p_project_id::text
    );
    SELECT * INTO stored_outbox FROM broker_outbox
     WHERE project_id = p_project_id AND idempotency_key = outbox_key FOR SHARE;
    IF stored_outbox.id IS NULL OR stored_outbox.job_id <> durable.id
       OR stored_outbox.topic <> durable.kind
       OR stored_outbox.payload IS DISTINCT FROM expected_wakeup THEN
        RAISE EXCEPTION 'Semantic analysis Job wakeup conflicts'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT durable.id, durable.input_hash, p_manifest_id,
        p_manifest_hash, was_replayed;
END;
$$;

REVOKE ALL ON FUNCTION geo_enqueue_workflow_c_semantic_metric_job_v2(
    uuid, uuid, text, uuid, integer, text, uuid, text, text, text, text,
    text, timestamptz, jsonb, text, jsonb, text, integer
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_workflow_c_semantic_metric_job_v2(
    uuid, uuid, text, uuid, integer, text, uuid, text, text, text, text,
    text, timestamptz, jsonb, text, jsonb, text, integer
) TO geo_app;

COMMENT ON FUNCTION geo_enqueue_workflow_c_semantic_metric_job_v2(
    uuid, uuid, text, uuid, integer, text, uuid, text, text, text, text,
    text, timestamptz, jsonb, text, jsonb, text, integer
) IS 'Atomically freezes exact Sampling evidence membership and enqueues a secret-free semantic v2 Job.';
