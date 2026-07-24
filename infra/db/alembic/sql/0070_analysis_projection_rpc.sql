-- Comparison and drift projections are immutable Worker outputs.  Direct
-- table writes bypass the lease/fence contract, so only these definer RPCs
-- may write them on behalf of geo_worker.
--
-- Statistical domain hashes use Python's ``json.dumps(sort_keys=True)``.
-- The historical SQL helper orders text with the database collation, which is
-- not necessarily Python's code-point order (for example ``a_`` vs ``ad``).
-- Keep the legacy helper unchanged for old identities and use this exact,
-- C-collated form only for new RPC verification.
CREATE FUNCTION geo_workflow_c_python_canonical_text(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
SET search_path = pg_catalog, public
AS $$
    SELECT CASE jsonb_typeof(value)
        WHEN 'object' THEN coalesce((
            SELECT '{' || string_agg(
                to_jsonb(item.key)::text || ':' || geo_workflow_c_python_canonical_text(item.value),
                ',' ORDER BY item.key COLLATE "C"
            ) || '}'
            FROM jsonb_each(value) AS item
        ), '{}')
        WHEN 'array' THEN coalesce((
            SELECT '[' || string_agg(
                geo_workflow_c_python_canonical_text(item.value), ',' ORDER BY item.ordinality
            ) || ']'
            FROM jsonb_array_elements(value) WITH ORDINALITY AS item(value, ordinality)
        ), '[]')
        ELSE value::text
    END
$$;

CREATE FUNCTION geo_persist_workflow_c_comparison_family(
    p_project_id uuid,
    p_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_family_hash text,
    p_protocol_hash text,
    p_power_plan_hash text,
    p_bootstrap_method text,
    p_bootstrap_iterations integer,
    p_correction_method text,
    p_simultaneous_interval_method text,
    p_status text,
    p_family_payload jsonb,
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
DECLARE existing_family workflow_c_comparison_families%ROWTYPE;
DECLARE existing_result workflow_c_comparison_results%ROWTYPE;
DECLARE result_value jsonb;
DECLARE expected_adjusted_p_value numeric;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL
       OR p_lease_token IS NULL
       OR p_fencing_generation IS NULL
       OR p_fencing_generation < 1
       OR p_family_hash IS NULL OR p_family_hash !~ '^[0-9a-f]{64}$'
       OR p_protocol_hash IS NULL OR p_protocol_hash !~ '^[0-9a-f]{64}$'
       OR p_power_plan_hash IS NULL OR p_power_plan_hash !~ '^[0-9a-f]{64}$'
       OR p_bootstrap_method IS NULL OR btrim(p_bootstrap_method) = ''
       OR p_bootstrap_iterations IS NULL OR p_bootstrap_iterations < 100
       OR p_correction_method IS NULL OR btrim(p_correction_method) = ''
       OR p_simultaneous_interval_method IS NULL OR btrim(p_simultaneous_interval_method) = ''
       OR p_status NOT IN ('complete', 'insufficient_evidence')
       OR p_family_payload IS NULL OR jsonb_typeof(p_family_payload) <> 'object'
       OR p_computed_at IS NULL
       OR p_results IS NULL OR jsonb_typeof(p_results) <> 'array'
       OR jsonb_array_length(p_results) < 1 THEN
        RAISE EXCEPTION 'Workflow C comparison persistence input is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF NOT geo_workflow_c_json_has_exact_keys(p_family_payload, ARRAY[
            'family', 'alpha', 'correction_method', 'results'
       ])
       OR jsonb_typeof(p_family_payload->'family') <> 'string'
       OR btrim(p_family_payload->>'family') = ''
       OR jsonb_typeof(p_family_payload->'alpha') <> 'string'
       OR jsonb_typeof(p_family_payload->'correction_method') <> 'string'
       OR p_family_payload->>'correction_method' <> p_correction_method
       OR jsonb_typeof(p_family_payload->'results') <> 'array'
       OR jsonb_array_length(p_family_payload->'results') < 1 THEN
        RAISE EXCEPTION 'Workflow C comparison family input is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF encode(
            digest(
                convert_to(geo_workflow_c_python_canonical_text(p_family_payload), 'UTF8'),
                'sha256'
            ),
            'hex'
       ) <> p_family_hash THEN
        RAISE EXCEPTION 'Workflow C comparison family immutable hash mismatch: expected %, actual %',
            p_family_hash,
            encode(
                digest(
                    convert_to(geo_workflow_c_python_canonical_text(p_family_payload), 'UTF8'),
                    'sha256'
                ),
                'hex'
            ) USING ERRCODE = '22023';
    END IF;

    IF (
        SELECT count(*) FROM jsonb_array_elements(p_results) AS result_rows(value)
    ) <> (
        SELECT count(DISTINCT result_rows.value->>'comparison_id')
          FROM jsonb_array_elements(p_results) AS result_rows(value)
    ) THEN
        RAISE EXCEPTION 'Workflow C comparison results have duplicate identities'
            USING ERRCODE = '22023';
    END IF;

    FOR result_value IN SELECT value FROM jsonb_array_elements(p_results)
    LOOP
        IF NOT geo_workflow_c_json_has_exact_keys(result_value, ARRAY[
                'comparison_id', 'stratum_hash', 'sampling_source_stratum_hash',
                'conclusion', 'adjusted_p_value', 'interval_json', 'payload'
           ])
           OR jsonb_typeof(result_value->'comparison_id') <> 'string'
           OR btrim(result_value->>'comparison_id') = ''
           OR result_value->>'stratum_hash' !~ '^[0-9a-f]{64}$'
           OR result_value->>'sampling_source_stratum_hash' !~ '^[0-9a-f]{64}$'
           OR result_value->>'conclusion' NOT IN (
                'win', 'equivalent', 'loss', 'inconclusive', 'insufficient_evidence'
           )
           OR jsonb_typeof(result_value->'adjusted_p_value') <> 'string'
           OR result_value->>'adjusted_p_value' !~ '^(0|1|0\.[0-9]+)$'
           OR jsonb_typeof(result_value->'interval_json') <> 'object'
           OR jsonb_typeof(result_value->'payload') <> 'object'
           OR result_value->'payload'->>'comparison_id'
              IS DISTINCT FROM result_value->>'comparison_id'
           OR result_value->'payload'->>'stratum_hash'
              IS DISTINCT FROM result_value->>'stratum_hash'
           OR result_value->'payload'->>'conclusion'
              IS DISTINCT FROM result_value->>'conclusion'
           OR result_value->'payload'->>'adjusted_p_value'
              IS DISTINCT FROM result_value->>'adjusted_p_value'
           OR result_value->'payload'->'adjusted_interval'
              IS DISTINCT FROM result_value->'interval_json'
           OR result_value->'payload'->>'power_plan_hash' IS DISTINCT FROM p_power_plan_hash
           OR result_value->'payload'->>'bootstrap_iterations'
              IS DISTINCT FROM p_bootstrap_iterations::text THEN
            RAISE EXCEPTION 'Workflow C comparison result input is invalid'
                USING ERRCODE = '22023';
        END IF;
    END LOOP;

    IF p_family_payload->'results' IS DISTINCT FROM (
        SELECT jsonb_agg(result_rows.value->'payload' ORDER BY result_rows.value->>'comparison_id')
          FROM jsonb_array_elements(p_results) AS result_rows(value)
    )
       OR p_status <> (CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(p_results) AS result_rows(value)
                 WHERE result_rows.value->>'conclusion' <> 'insufficient_evidence'
            ) THEN 'insufficient_evidence'
            ELSE 'complete'
       END) THEN
        RAISE EXCEPTION 'Workflow C comparison family result rows are inconsistent'
            USING ERRCODE = '22023';
    END IF;

    SELECT parent_durable.* INTO parent_job
      FROM durable_jobs AS parent_durable
     WHERE parent_durable.project_id = p_project_id AND parent_durable.id = p_job_id
     FOR SHARE;
    SELECT parent_spec_row.* INTO parent_spec
      FROM workflow_c_job_specs AS parent_spec_row
     WHERE parent_spec_row.project_id = p_project_id AND parent_spec_row.job_id = p_job_id
     FOR SHARE;
    IF parent_job.id IS NULL OR parent_spec.job_id IS NULL
       OR parent_job.kind <> 'workflow_c.analysis.comparison'
       OR parent_spec.kind <> parent_job.kind
       OR parent_job.input_hash <> parent_spec.spec_hash
       OR parent_job.status <> 'running'
       OR parent_job.lease_token IS DISTINCT FROM p_lease_token
       OR parent_job.fencing_generation <> p_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= clock_timestamp()
       OR parent_job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C comparison parent lease or frozen input was fenced'
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO workflow_c_comparison_families(
        family_hash, project_id, protocol_hash, power_plan_hash, bootstrap_method,
        bootstrap_iterations, correction_method, simultaneous_interval_method,
        status, payload, computed_at
    ) VALUES (
        p_family_hash, p_project_id, p_protocol_hash, p_power_plan_hash, p_bootstrap_method,
        p_bootstrap_iterations, p_correction_method, p_simultaneous_interval_method,
        p_status, p_family_payload, p_computed_at
    ) ON CONFLICT (project_id, family_hash) DO NOTHING;

    SELECT family.* INTO existing_family
      FROM workflow_c_comparison_families AS family
     WHERE family.project_id = p_project_id AND family.family_hash = p_family_hash
     FOR SHARE;
    IF existing_family.family_hash IS NULL
       OR existing_family.protocol_hash IS DISTINCT FROM p_protocol_hash
       OR existing_family.power_plan_hash IS DISTINCT FROM p_power_plan_hash
       OR existing_family.bootstrap_method IS DISTINCT FROM p_bootstrap_method
       OR existing_family.bootstrap_iterations IS DISTINCT FROM p_bootstrap_iterations
       OR existing_family.correction_method IS DISTINCT FROM p_correction_method
       OR existing_family.simultaneous_interval_method IS DISTINCT FROM p_simultaneous_interval_method
       OR existing_family.status IS DISTINCT FROM p_status
       OR existing_family.payload IS DISTINCT FROM p_family_payload
       OR existing_family.computed_at IS DISTINCT FROM p_computed_at THEN
        RAISE EXCEPTION 'Workflow C comparison family hash collides with other input'
            USING ERRCODE = '23505';
    END IF;

    FOR result_value IN SELECT value FROM jsonb_array_elements(p_results)
    LOOP
        expected_adjusted_p_value := (result_value->>'adjusted_p_value')::numeric;
        INSERT INTO workflow_c_comparison_results(
            project_id, family_hash, comparison_id, stratum_hash,
            sampling_source_stratum_hash, conclusion, adjusted_p_value, interval_json, payload
        ) VALUES (
            p_project_id, p_family_hash, result_value->>'comparison_id',
            result_value->>'stratum_hash', result_value->>'sampling_source_stratum_hash',
            result_value->>'conclusion', expected_adjusted_p_value,
            result_value->'interval_json', result_value->'payload'
        ) ON CONFLICT (project_id, family_hash, comparison_id) DO NOTHING;

        SELECT result.* INTO existing_result
          FROM workflow_c_comparison_results AS result
         WHERE result.project_id = p_project_id
           AND result.family_hash = p_family_hash
           AND result.comparison_id = result_value->>'comparison_id'
         FOR SHARE;
        IF existing_result.comparison_id IS NULL
           OR existing_result.stratum_hash IS DISTINCT FROM result_value->>'stratum_hash'
           OR existing_result.sampling_source_stratum_hash
              IS DISTINCT FROM result_value->>'sampling_source_stratum_hash'
           OR existing_result.conclusion IS DISTINCT FROM result_value->>'conclusion'
           OR existing_result.adjusted_p_value IS DISTINCT FROM expected_adjusted_p_value
           OR existing_result.interval_json IS DISTINCT FROM result_value->'interval_json'
           OR existing_result.payload IS DISTINCT FROM result_value->'payload' THEN
            RAISE EXCEPTION 'Workflow C comparison result hash collides with other input'
                USING ERRCODE = '23505';
        END IF;
    END LOOP;
END;
$$;

CREATE FUNCTION geo_persist_workflow_c_drift_report(
    p_project_id uuid,
    p_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_report_hash text,
    p_source_snapshot_hash text,
    p_target_snapshot_hash text,
    p_report_payload jsonb,
    p_computed_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE parent_job durable_jobs%ROWTYPE;
DECLARE parent_spec workflow_c_job_specs%ROWTYPE;
DECLARE existing_report workflow_c_drift_reports%ROWTYPE;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL
       OR p_lease_token IS NULL
       OR p_fencing_generation IS NULL OR p_fencing_generation < 1
       OR p_report_hash IS NULL OR p_report_hash !~ '^[0-9a-f]{64}$'
       OR p_source_snapshot_hash IS NULL OR p_source_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_target_snapshot_hash IS NULL OR p_target_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_source_snapshot_hash = p_target_snapshot_hash
       OR p_report_payload IS NULL OR jsonb_typeof(p_report_payload) <> 'object'
       OR p_computed_at IS NULL THEN
        RAISE EXCEPTION 'Workflow C drift persistence input is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF NOT geo_workflow_c_json_has_exact_keys(p_report_payload, ARRAY[
            'model_drift', 'source_drift', 'effect_drift',
            'unmatched_baseline_strata', 'unmatched_current_strata',
            'baseline_input_hash', 'current_input_hash', 'method_version'
       ])
       OR jsonb_typeof(p_report_payload->'model_drift') <> 'array'
       OR jsonb_typeof(p_report_payload->'source_drift') <> 'array'
       OR jsonb_typeof(p_report_payload->'effect_drift') <> 'array'
       OR jsonb_typeof(p_report_payload->'unmatched_baseline_strata') <> 'array'
       OR jsonb_typeof(p_report_payload->'unmatched_current_strata') <> 'array'
       OR p_report_payload->>'baseline_input_hash' !~ '^[0-9a-f]{64}$'
       OR p_report_payload->>'current_input_hash' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_report_payload->'method_version') <> 'string'
       OR btrim(p_report_payload->>'method_version') = ''
       OR encode(
            digest(
                convert_to(geo_workflow_c_python_canonical_text(p_report_payload), 'UTF8'),
                'sha256'
            ),
            'hex'
       ) <> p_report_hash THEN
        RAISE EXCEPTION 'Workflow C drift report does not match its immutable hash'
            USING ERRCODE = '22023';
    END IF;

    SELECT parent_durable.* INTO parent_job
      FROM durable_jobs AS parent_durable
     WHERE parent_durable.project_id = p_project_id AND parent_durable.id = p_job_id
     FOR SHARE;
    SELECT parent_spec_row.* INTO parent_spec
      FROM workflow_c_job_specs AS parent_spec_row
     WHERE parent_spec_row.project_id = p_project_id AND parent_spec_row.job_id = p_job_id
     FOR SHARE;
    IF parent_job.id IS NULL OR parent_spec.job_id IS NULL
       OR parent_job.kind <> 'workflow_c.analysis.drift'
       OR parent_spec.kind <> parent_job.kind
       OR parent_job.input_hash <> parent_spec.spec_hash
       OR parent_job.status <> 'running'
       OR parent_job.lease_token IS DISTINCT FROM p_lease_token
       OR parent_job.fencing_generation <> p_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= clock_timestamp()
       OR parent_job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Workflow C drift parent lease or frozen input was fenced'
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO workflow_c_drift_reports(
        report_hash, project_id, source_snapshot_hash, target_snapshot_hash,
        status, payload, computed_at
    ) VALUES (
        p_report_hash, p_project_id, p_source_snapshot_hash, p_target_snapshot_hash,
        'complete', p_report_payload, p_computed_at
    ) ON CONFLICT (project_id, report_hash) DO NOTHING;

    SELECT report.* INTO existing_report
      FROM workflow_c_drift_reports AS report
     WHERE report.project_id = p_project_id AND report.report_hash = p_report_hash
     FOR SHARE;
    IF existing_report.report_hash IS NULL
       OR existing_report.source_snapshot_hash IS DISTINCT FROM p_source_snapshot_hash
       OR existing_report.target_snapshot_hash IS DISTINCT FROM p_target_snapshot_hash
       OR existing_report.status <> 'complete'
       OR existing_report.payload IS DISTINCT FROM p_report_payload
       OR existing_report.computed_at IS DISTINCT FROM p_computed_at THEN
        RAISE EXCEPTION 'Workflow C drift report hash collides with other input'
            USING ERRCODE = '23505';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION geo_persist_workflow_c_comparison_family(
    uuid, uuid, uuid, integer, text, text, text, text, integer, text, text,
    text, jsonb, timestamptz, jsonb
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_persist_workflow_c_comparison_family(
    uuid, uuid, uuid, integer, text, text, text, text, integer, text, text,
    text, jsonb, timestamptz, jsonb
) TO geo_worker;

REVOKE ALL ON FUNCTION geo_persist_workflow_c_drift_report(
    uuid, uuid, uuid, integer, text, text, text, jsonb, timestamptz
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_persist_workflow_c_drift_report(
    uuid, uuid, uuid, integer, text, text, text, jsonb, timestamptz
) TO geo_worker;

REVOKE INSERT, UPDATE, DELETE ON workflow_c_comparison_families,
    workflow_c_comparison_results, workflow_c_drift_reports FROM geo_worker;
REVOKE ALL ON FUNCTION geo_workflow_c_python_canonical_text(jsonb)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;

COMMENT ON FUNCTION geo_persist_workflow_c_comparison_family(
    uuid, uuid, uuid, integer, text, text, text, text, integer, text, text,
    text, jsonb, timestamptz, jsonb
) IS 'Worker-only fenced persistence of immutable comparison family projections.';
COMMENT ON FUNCTION geo_persist_workflow_c_drift_report(
    uuid, uuid, uuid, integer, text, text, text, jsonb, timestamptz
) IS 'Worker-only fenced persistence of immutable drift reports.';
