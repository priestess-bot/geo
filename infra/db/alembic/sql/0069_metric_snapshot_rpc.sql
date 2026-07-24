-- Semantic metric projections are immutable evidence.  Worker sessions retain
-- read-only access for verification, but every write must prove the frozen
-- parent specification and its currently valid fenced lease.
CREATE FUNCTION geo_persist_workflow_c_semantic_metric_snapshot(
    p_project_id uuid,
    p_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_snapshot_hash text,
    p_run_id uuid,
    p_input_set_hash text,
    p_metric_suite_hash text,
    p_source_stratum_hash text,
    p_capture_method text,
    p_evidence_status text,
    p_warning_ratio numeric,
    p_test_only boolean,
    p_synthetic boolean,
    p_snapshot_payload jsonb,
    p_computed_at timestamptz,
    p_results jsonb
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE parent_job durable_jobs%ROWTYPE;
DECLARE parent_spec workflow_c_job_specs%ROWTYPE;
DECLARE existing_snapshot workflow_c_semantic_metric_snapshots%ROWTYPE;
DECLARE existing_result workflow_c_semantic_metric_results%ROWTYPE;
DECLARE result_value jsonb;
DECLARE expected_estimate numeric;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL
       OR p_lease_token IS NULL
       OR p_fencing_generation IS NULL
       OR p_fencing_generation < 1
       OR p_snapshot_hash IS NULL
       OR p_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_run_id IS NULL
       OR p_input_set_hash IS NULL
       OR p_input_set_hash !~ '^[0-9a-f]{64}$'
       OR p_metric_suite_hash IS NULL
       OR p_metric_suite_hash !~ '^[0-9a-f]{64}$'
       OR p_source_stratum_hash IS NULL
       OR p_source_stratum_hash !~ '^[0-9a-f]{64}$'
       OR p_capture_method NOT IN (
            'provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui'
       )
       OR p_evidence_status NOT IN ('complete', 'insufficient_evidence')
       OR p_warning_ratio IS NULL
       OR p_warning_ratio = 'NaN'::numeric
       OR p_warning_ratio < 0
       OR p_warning_ratio > 1
       OR p_test_only IS NULL
       OR p_synthetic IS NULL
       OR p_snapshot_payload IS NULL
       OR jsonb_typeof(p_snapshot_payload) <> 'object'
       OR p_computed_at IS NULL
       OR p_results IS NULL
       OR jsonb_typeof(p_results) <> 'array'
       OR jsonb_array_length(p_results) < 1 THEN
        RAISE EXCEPTION 'Workflow C semantic metric persistence input is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF NOT geo_workflow_c_json_has_exact_keys(p_snapshot_payload, ARRAY[
            'input_set_hash', 'suite_hash', 'stratum_hash', 'results', 'performance', 'computed_at'
       ])
       OR p_snapshot_payload->>'input_set_hash' <> p_input_set_hash
       OR p_snapshot_payload->>'suite_hash' <> p_metric_suite_hash
       OR jsonb_typeof(p_snapshot_payload->'results') <> 'array'
       OR jsonb_array_length(p_snapshot_payload->'results') < 1
       OR jsonb_typeof(p_snapshot_payload->'performance') <> 'object'
       OR jsonb_typeof(p_snapshot_payload->'computed_at') <> 'string'
       OR encode(
            digest(
                convert_to(geo_jsonb_canonical_text(p_snapshot_payload - 'computed_at'), 'UTF8'),
                'sha256'
            ),
            'hex'
       ) <> p_snapshot_hash THEN
        RAISE EXCEPTION 'Workflow C semantic metric snapshot does not match its immutable hash'
            USING ERRCODE = '22023';
    END IF;

    IF (p_snapshot_payload->>'computed_at')::timestamptz IS DISTINCT FROM p_computed_at THEN
        RAISE EXCEPTION 'Workflow C semantic metric snapshot computation time is inconsistent'
            USING ERRCODE = '22023';
    END IF;

    IF (
        SELECT count(*)
          FROM jsonb_array_elements(p_results) AS result_rows(value)
    ) <> (
        SELECT count(DISTINCT result_rows.value->>'metric_key')
          FROM jsonb_array_elements(p_results) AS result_rows(value)
    ) THEN
        RAISE EXCEPTION 'Workflow C semantic metric results have duplicate metric keys'
            USING ERRCODE = '22023';
    END IF;

    FOR result_value IN SELECT value FROM jsonb_array_elements(p_results)
    LOOP
        IF NOT geo_workflow_c_json_has_exact_keys(result_value, ARRAY[
                'metric_key', 'metric_version', 'status', 'estimate', 'interval_json',
                'denominator', 'valid_count', 'invalid_count', 'missing_count',
                'judge_version_hash', 'rule_versions_hash', 'evidence_locators_json', 'payload'
           ])
           OR jsonb_typeof(result_value->'metric_key') <> 'string'
           OR btrim(result_value->>'metric_key') = ''
           OR jsonb_typeof(result_value->'metric_version') <> 'string'
           OR btrim(result_value->>'metric_version') = ''
           OR result_value->>'status' NOT IN ('complete', 'invalid', 'insufficient_evidence')
           OR jsonb_typeof(result_value->'interval_json') <> 'object'
           OR jsonb_typeof(result_value->'evidence_locators_json') <> 'array'
           OR jsonb_typeof(result_value->'payload') <> 'object'
           OR jsonb_typeof(result_value->'denominator') <> 'number'
           OR jsonb_typeof(result_value->'valid_count') <> 'number'
           OR jsonb_typeof(result_value->'invalid_count') <> 'number'
           OR jsonb_typeof(result_value->'missing_count') <> 'number'
           OR result_value->>'denominator' !~ '^(0|[1-9][0-9]*)$'
           OR result_value->>'valid_count' !~ '^(0|[1-9][0-9]*)$'
           OR result_value->>'invalid_count' !~ '^(0|[1-9][0-9]*)$'
           OR result_value->>'missing_count' !~ '^(0|[1-9][0-9]*)$'
           OR (result_value->>'valid_count')::integer
              + (result_value->>'invalid_count')::integer
              + (result_value->>'missing_count')::integer
              <> (result_value->>'denominator')::integer
           OR jsonb_typeof(result_value->'rule_versions_hash') <> 'string'
           OR result_value->>'rule_versions_hash' !~ '^[0-9a-f]{64}$'
           OR jsonb_typeof(result_value->'judge_version_hash') NOT IN ('string', 'null')
           OR (
                jsonb_typeof(result_value->'judge_version_hash') = 'string'
                AND result_value->>'judge_version_hash' !~ '^[0-9a-f]{64}$'
           )
           OR (
                result_value->>'status' = 'complete'
                AND jsonb_typeof(result_value->'estimate') <> 'string'
           )
           OR (
                result_value->>'status' <> 'complete'
                AND jsonb_typeof(result_value->'estimate') <> 'null'
           )
           OR result_value->'payload'->>'metric_key' IS DISTINCT FROM result_value->>'metric_key'
           OR result_value->'payload'->>'metric_version' IS DISTINCT FROM result_value->>'metric_version'
           OR result_value->'payload'->>'status' IS DISTINCT FROM result_value->>'status'
           OR result_value->'payload'->'interval' IS DISTINCT FROM result_value->'interval_json'
           OR result_value->'payload'->'evidence_locators'
              IS DISTINCT FROM result_value->'evidence_locators_json'
           OR result_value->'payload'->>'input_set_hash' IS DISTINCT FROM p_input_set_hash
           OR result_value->'payload'->>'rule_versions_hash'
              IS DISTINCT FROM result_value->>'rule_versions_hash'
           OR result_value->'payload'->>'judge_version_hash'
              IS DISTINCT FROM result_value->>'judge_version_hash' THEN
            RAISE EXCEPTION 'Workflow C semantic metric result input is invalid'
                USING ERRCODE = '22023';
        END IF;
    END LOOP;

    IF p_snapshot_payload->'results' IS DISTINCT FROM (
        SELECT jsonb_agg(result_rows.value->'payload' ORDER BY result_rows.value->>'metric_key')
          FROM jsonb_array_elements(p_results) AS result_rows(value)
    ) THEN
        RAISE EXCEPTION 'Workflow C semantic metric snapshot results do not match result rows'
            USING ERRCODE = '22023';
    END IF;

    SELECT parent_durable.* INTO parent_job
      FROM durable_jobs AS parent_durable
     WHERE parent_durable.project_id = p_project_id
       AND parent_durable.id = p_job_id
     FOR SHARE;
    SELECT parent_spec_row.* INTO parent_spec
      FROM workflow_c_job_specs AS parent_spec_row
     WHERE parent_spec_row.project_id = p_project_id
       AND parent_spec_row.job_id = p_job_id
     FOR SHARE;
    IF parent_job.id IS NULL OR parent_spec.job_id IS NULL
       OR parent_job.kind <> 'workflow_c.analysis.semantic_metrics'
       OR parent_spec.kind <> parent_job.kind
       OR parent_job.input_hash <> parent_spec.spec_hash
       OR parent_job.status <> 'running'
       OR parent_job.lease_token IS DISTINCT FROM p_lease_token
       OR parent_job.fencing_generation <> p_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= clock_timestamp()
       OR parent_job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C semantic metric parent lease or frozen input was fenced'
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO workflow_c_semantic_metric_snapshots(
        snapshot_hash, project_id, run_id, input_set_hash, metric_suite_hash,
        source_stratum_hash, capture_method, evidence_status, warning_ratio,
        test_only, synthetic, payload, computed_at
    ) VALUES (
        p_snapshot_hash, p_project_id, p_run_id, p_input_set_hash, p_metric_suite_hash,
        p_source_stratum_hash, p_capture_method, p_evidence_status, p_warning_ratio,
        p_test_only, p_synthetic, p_snapshot_payload, p_computed_at
    ) ON CONFLICT (project_id, snapshot_hash) DO NOTHING;

    SELECT snapshot.* INTO existing_snapshot
      FROM workflow_c_semantic_metric_snapshots AS snapshot
     WHERE snapshot.project_id = p_project_id
       AND snapshot.snapshot_hash = p_snapshot_hash
     FOR SHARE;
    IF existing_snapshot.snapshot_hash IS NULL
       OR existing_snapshot.run_id IS DISTINCT FROM p_run_id
       OR existing_snapshot.input_set_hash IS DISTINCT FROM p_input_set_hash
       OR existing_snapshot.metric_suite_hash IS DISTINCT FROM p_metric_suite_hash
       OR existing_snapshot.source_stratum_hash IS DISTINCT FROM p_source_stratum_hash
       OR existing_snapshot.capture_method IS DISTINCT FROM p_capture_method
       OR existing_snapshot.evidence_status IS DISTINCT FROM p_evidence_status
       OR existing_snapshot.warning_ratio IS DISTINCT FROM p_warning_ratio
       OR existing_snapshot.test_only IS DISTINCT FROM p_test_only
       OR existing_snapshot.synthetic IS DISTINCT FROM p_synthetic
       OR existing_snapshot.payload IS DISTINCT FROM p_snapshot_payload
       OR existing_snapshot.computed_at IS DISTINCT FROM p_computed_at THEN
        RAISE EXCEPTION 'Workflow C semantic metric snapshot hash collides with other input'
            USING ERRCODE = '23505';
    END IF;

    FOR result_value IN SELECT value FROM jsonb_array_elements(p_results)
    LOOP
        expected_estimate := CASE
            WHEN result_value->>'status' = 'complete'
                THEN (result_value->>'estimate')::numeric
            ELSE NULL
        END;
        INSERT INTO workflow_c_semantic_metric_results(
            project_id, snapshot_hash, metric_key, metric_version, status, estimate,
            interval_json, denominator, valid_count, invalid_count, missing_count,
            judge_version_hash, rule_versions_hash, evidence_locators_json, payload
        ) VALUES (
            p_project_id, p_snapshot_hash, result_value->>'metric_key',
            result_value->>'metric_version', result_value->>'status', expected_estimate,
            result_value->'interval_json', (result_value->>'denominator')::integer,
            (result_value->>'valid_count')::integer, (result_value->>'invalid_count')::integer,
            (result_value->>'missing_count')::integer, result_value->>'judge_version_hash',
            result_value->>'rule_versions_hash', result_value->'evidence_locators_json',
            result_value->'payload'
        ) ON CONFLICT (project_id, snapshot_hash, metric_key) DO NOTHING;

        SELECT metric_result.* INTO existing_result
          FROM workflow_c_semantic_metric_results AS metric_result
         WHERE metric_result.project_id = p_project_id
           AND metric_result.snapshot_hash = p_snapshot_hash
           AND metric_result.metric_key = result_value->>'metric_key'
         FOR SHARE;
        IF existing_result.metric_key IS NULL
           OR existing_result.metric_version IS DISTINCT FROM result_value->>'metric_version'
           OR existing_result.status IS DISTINCT FROM result_value->>'status'
           OR existing_result.estimate IS DISTINCT FROM expected_estimate
           OR existing_result.interval_json IS DISTINCT FROM result_value->'interval_json'
           OR existing_result.denominator IS DISTINCT FROM (result_value->>'denominator')::integer
           OR existing_result.valid_count IS DISTINCT FROM (result_value->>'valid_count')::integer
           OR existing_result.invalid_count IS DISTINCT FROM (result_value->>'invalid_count')::integer
           OR existing_result.missing_count IS DISTINCT FROM (result_value->>'missing_count')::integer
           OR existing_result.judge_version_hash
              IS DISTINCT FROM result_value->>'judge_version_hash'
           OR existing_result.rule_versions_hash
              IS DISTINCT FROM result_value->>'rule_versions_hash'
           OR existing_result.evidence_locators_json
              IS DISTINCT FROM result_value->'evidence_locators_json'
           OR existing_result.payload IS DISTINCT FROM result_value->'payload' THEN
            RAISE EXCEPTION 'Workflow C semantic metric result hash collides with other input'
                USING ERRCODE = '23505';
        END IF;
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION geo_persist_workflow_c_semantic_metric_snapshot(
    uuid, uuid, uuid, integer, text, uuid, text, text, text, text,
    text, numeric, boolean, boolean, jsonb, timestamptz, jsonb
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_persist_workflow_c_semantic_metric_snapshot(
    uuid, uuid, uuid, integer, text, uuid, text, text, text, text,
    text, numeric, boolean, boolean, jsonb, timestamptz, jsonb
) TO geo_worker;

REVOKE INSERT, UPDATE, DELETE ON workflow_c_semantic_metric_snapshots,
    workflow_c_semantic_metric_results FROM geo_worker;

COMMENT ON FUNCTION geo_persist_workflow_c_semantic_metric_snapshot(
    uuid, uuid, uuid, integer, text, uuid, text, text, text, text,
    text, numeric, boolean, boolean, jsonb, timestamptz, jsonb
) IS 'Worker-only fenced persistence of immutable semantic metric snapshots and result projections.';
