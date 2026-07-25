-- Comparison and drift method choices are governed releases. Callers select
-- approved versions; they never submit paired observations or drift cohorts.

CREATE TABLE workflow_c_statistical_protocol_versions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_kind text NOT NULL CHECK (
        protocol_kind IN ('comparison_plan', 'drift_protocol')
    ),
    series_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    supersedes_protocol_id uuid,
    status text NOT NULL CHECK (status IN ('draft', 'in_review', 'approved', 'retired')),
    definition_hash text NOT NULL CHECK (definition_hash ~ '^[0-9a-f]{64}$'),
    definition jsonb NOT NULL CHECK (
        jsonb_typeof(definition) = 'object'
        AND definition->'schema_version' = '1'::jsonb
        AND definition->>'kind' = protocol_kind
    ),
    created_by text NOT NULL CHECK (btrim(created_by) <> ''),
    submitted_by text,
    submitted_at timestamptz,
    approved_by text,
    approved_at timestamptz,
    retired_by text,
    retired_at timestamptz,
    decision_reason text,
    aggregate_version integer NOT NULL DEFAULT 1 CHECK (aggregate_version > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, protocol_kind, definition_hash),
    UNIQUE (project_id, protocol_kind, series_id, version),
    FOREIGN KEY (supersedes_protocol_id, project_id)
        REFERENCES workflow_c_statistical_protocol_versions(id, project_id),
    CHECK ((version = 1) = (supersedes_protocol_id IS NULL)),
    CHECK (created_at <= updated_at),
    CHECK (
        (status = 'draft'
            AND submitted_by IS NULL AND submitted_at IS NULL
            AND approved_by IS NULL AND approved_at IS NULL
            AND retired_by IS NULL AND retired_at IS NULL AND decision_reason IS NULL)
        OR (status = 'in_review'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND approved_by IS NULL AND approved_at IS NULL
            AND retired_by IS NULL AND retired_at IS NULL AND decision_reason IS NULL)
        OR (status = 'approved'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND retired_by IS NULL AND retired_at IS NULL
            AND decision_reason IS NOT NULL)
        OR (status = 'retired'
            AND submitted_by IS NOT NULL AND submitted_at IS NOT NULL
            AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND retired_by IS NOT NULL AND retired_at IS NOT NULL
            AND decision_reason IS NOT NULL)
    )
);

CREATE TABLE workflow_c_statistical_protocol_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_id uuid NOT NULL,
    command_scope text NOT NULL CHECK (
        command_scope IN ('create', 'submit', 'approve', 'retire')
    ),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    result_status text NOT NULL CHECK (
        result_status IN ('draft', 'in_review', 'approved', 'retired')
    ),
    result_aggregate_version integer NOT NULL CHECK (result_aggregate_version > 0),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, protocol_id, command_scope, idempotency_key_hash),
    FOREIGN KEY (protocol_id, project_id)
        REFERENCES workflow_c_statistical_protocol_versions(id, project_id)
);

CREATE FUNCTION geo_workflow_c_statistical_protocol_definition_is_valid(
    p_kind text, p_definition jsonb
) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public AS $$
DECLARE item jsonb;
DECLARE seen text[] := ARRAY[]::text[];
BEGIN
    IF p_kind = 'comparison_plan' THEN
        IF NOT geo_workflow_c_json_has_exact_keys(p_definition, ARRAY[
                'schema_version', 'kind', 'family', 'metric_key',
                'metric_method_version', 'question_clusters', 'alpha', 'delta',
                'target_power', 'precision', 'min_pairs', 'power_plan_hash',
                'a_priori_design_power', 'power_method_version',
                'minimum_completion_ratio', 'bootstrap_iterations',
                'bootstrap_method', 'correction_method',
                'simultaneous_interval_method'
           ])
           OR p_definition->'schema_version' <> '1'::jsonb
           OR p_definition->>'kind' <> p_kind
           OR NOT geo_workflow_c_analysis_nonempty_text_is_valid(p_definition->'family')
           OR p_definition->>'metric_key' <> 'question_performance'
           OR p_definition->>'metric_method_version' <> 'semantic-question-performance-v1'
           OR jsonb_typeof(p_definition->'question_clusters') <> 'array'
           OR jsonb_array_length(p_definition->'question_clusters') < 1
           OR NOT geo_workflow_c_analysis_decimal_is_valid(p_definition->'alpha')
           OR NOT geo_workflow_c_analysis_decimal_is_valid(p_definition->'delta')
           OR NOT geo_workflow_c_analysis_decimal_is_valid(p_definition->'target_power')
           OR NOT geo_workflow_c_analysis_decimal_is_valid(p_definition->'precision')
           OR NOT geo_workflow_c_analysis_decimal_is_valid(
                p_definition->'a_priori_design_power'
           )
           OR NOT geo_workflow_c_analysis_decimal_is_valid(
                p_definition->'minimum_completion_ratio'
           )
           OR NOT geo_workflow_c_json_is_positive_integer(p_definition->'min_pairs')
           OR NOT geo_workflow_c_json_is_positive_integer(
                p_definition->'bootstrap_iterations'
           )
           OR NOT geo_workflow_c_json_is_sha256(p_definition->'power_plan_hash')
           OR p_definition->>'power_method_version' <> 'a-priori-design-power-v1'
           OR p_definition->>'bootstrap_method' <> 'paired-bootstrap-percentile-v1'
           OR p_definition->>'correction_method' <> 'holm-v1'
           OR p_definition->>'simultaneous_interval_method'
              <> 'paired-bootstrap-percentile-bonferroni-family-v1' THEN
            RETURN false;
        END IF;
        IF (p_definition->>'alpha')::numeric <= 0
           OR (p_definition->>'alpha')::numeric >= 1
           OR (p_definition->>'delta')::numeric < 0
           OR (p_definition->>'target_power')::numeric < 0.80
           OR (p_definition->>'target_power')::numeric > 1
           OR (p_definition->>'precision')::numeric <= 0
           OR (p_definition->>'a_priori_design_power')::numeric < 0
           OR (p_definition->>'a_priori_design_power')::numeric > 1
           OR (p_definition->>'minimum_completion_ratio')::numeric < 0.80
           OR (p_definition->>'minimum_completion_ratio')::numeric > 1
           OR (p_definition->>'bootstrap_iterations')::integer < 100 THEN
            RETURN false;
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(p_definition->'question_clusters')
        LOOP
            IF NOT geo_workflow_c_analysis_nonempty_text_is_valid(item)
               OR (item #>> '{}') = ANY(seen) THEN
                RETURN false;
            END IF;
            seen := array_append(seen, item #>> '{}');
        END LOOP;
        RETURN true;
    END IF;
    IF p_kind = 'drift_protocol' THEN
        RETURN geo_workflow_c_json_has_exact_keys(p_definition, ARRAY[
                   'schema_version', 'kind', 'method_version', 'effect_metric',
                   'minimum_question_count'
               ])
           AND p_definition->'schema_version' = '1'::jsonb
           AND p_definition->>'kind' = p_kind
           AND p_definition->>'method_version' = 'strict-stratum-drift-v1'
           AND p_definition->>'effect_metric' = 'question_performance'
           AND geo_workflow_c_json_is_positive_integer(
                p_definition->'minimum_question_count'
           );
    END IF;
    RETURN false;
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_statistical_protocol_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE predecessor workflow_c_statistical_protocol_versions%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Statistical Protocol history cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' OR NEW.aggregate_version <> 1
           OR NEW.created_at <> NEW.updated_at
           OR NOT geo_workflow_c_statistical_protocol_definition_is_valid(
                NEW.protocol_kind, NEW.definition
           ) THEN
            RAISE EXCEPTION 'Statistical Protocol must begin as a valid draft'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.version = 1 THEN
            IF NEW.series_id <> NEW.id OR NEW.supersedes_protocol_id IS NOT NULL THEN
                RAISE EXCEPTION 'Statistical Protocol initial series identity is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            SELECT * INTO predecessor FROM workflow_c_statistical_protocol_versions
             WHERE project_id = NEW.project_id AND id = NEW.supersedes_protocol_id;
            IF predecessor.id IS NULL
               OR predecessor.protocol_kind <> NEW.protocol_kind
               OR predecessor.series_id <> NEW.series_id
               OR predecessor.version + 1 <> NEW.version
               OR predecessor.status NOT IN ('approved', 'retired') THEN
                RAISE EXCEPTION 'Statistical Protocol predecessor is invalid'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(NEW.id, NEW.project_id, NEW.protocol_kind, NEW.series_id, NEW.version,
           NEW.supersedes_protocol_id, NEW.definition_hash, NEW.definition,
           NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.project_id, OLD.protocol_kind, OLD.series_id, OLD.version,
           OLD.supersedes_protocol_id, OLD.definition_hash, OLD.definition,
           OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'Statistical Protocol definition is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.aggregate_version <> OLD.aggregate_version + 1
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'Statistical Protocol aggregate version is stale'
            USING ERRCODE = '40001';
    END IF;
    IF OLD.status = 'draft' AND NEW.status = 'in_review'
       AND NEW.submitted_by IS NOT NULL AND NEW.submitted_at IS NOT NULL
       AND NEW.approved_by IS NULL AND NEW.approved_at IS NULL
       AND NEW.retired_by IS NULL AND NEW.retired_at IS NULL
       AND NEW.decision_reason IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'in_review' AND NEW.status = 'approved'
       AND NEW.submitted_by = OLD.submitted_by AND NEW.submitted_at = OLD.submitted_at
       AND NEW.approved_by IS NOT NULL AND NEW.approved_by <> NEW.created_by
       AND NEW.approved_at IS NOT NULL AND NEW.decision_reason IS NOT NULL
       AND NEW.retired_by IS NULL AND NEW.retired_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'approved' AND NEW.status = 'retired'
       AND NEW.submitted_by = OLD.submitted_by AND NEW.submitted_at = OLD.submitted_at
       AND NEW.approved_by = OLD.approved_by AND NEW.approved_at = OLD.approved_at
       AND NEW.retired_by IS NOT NULL AND NEW.retired_at IS NOT NULL
       AND NEW.decision_reason IS NOT NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Statistical Protocol lifecycle transition is invalid'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER workflow_c_statistical_protocol_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON workflow_c_statistical_protocol_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_statistical_protocol_change();

CREATE TRIGGER workflow_c_statistical_protocol_receipts_immutable
BEFORE UPDATE OR DELETE ON workflow_c_statistical_protocol_command_receipts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE FUNCTION geo_create_workflow_c_statistical_protocol(
    p_project_id uuid, p_protocol_id uuid, p_protocol_kind text,
    p_series_id uuid, p_version integer, p_supersedes_protocol_id uuid,
    p_definition_hash text, p_definition jsonb, p_created_by text,
    p_idempotency_key_hash text, p_input_hash text, p_occurred_at timestamptz
) RETURNS SETOF workflow_c_statistical_protocol_versions
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE existing workflow_c_statistical_protocol_command_receipts%ROWTYPE;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_protocol_id IS NULL OR p_series_id IS NULL OR p_version IS NULL OR p_version < 1
       OR p_protocol_kind NOT IN ('comparison_plan', 'drift_protocol')
       OR p_definition_hash !~ '^[0-9a-f]{64}$'
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$'
       OR btrim(coalesce(p_created_by, '')) = '' OR p_occurred_at IS NULL
       OR NOT geo_workflow_c_statistical_protocol_definition_is_valid(
            p_protocol_kind, p_definition
       )
       OR encode(digest(convert_to(
            geo_workflow_c_python_canonical_text(p_definition), 'UTF8'
          ), 'sha256'), 'hex') <> p_definition_hash THEN
        RAISE EXCEPTION 'Statistical Protocol create input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM workflow_c_statistical_protocol_command_receipts
     WHERE project_id = p_project_id AND protocol_id = p_protocol_id
       AND command_scope = 'create' AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash THEN
            RAISE EXCEPTION 'Statistical Protocol Idempotency-Key changed input'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT * FROM workflow_c_statistical_protocol_versions
         WHERE project_id = p_project_id AND id = p_protocol_id;
        RETURN;
    END IF;
    INSERT INTO workflow_c_statistical_protocol_versions(
        id, project_id, protocol_kind, series_id, version,
        supersedes_protocol_id, status, definition_hash, definition,
        created_by, created_at, updated_at
    ) VALUES (
        p_protocol_id, p_project_id, p_protocol_kind, p_series_id, p_version,
        p_supersedes_protocol_id, 'draft', p_definition_hash, p_definition,
        p_created_by, p_occurred_at, p_occurred_at
    );
    INSERT INTO workflow_c_statistical_protocol_command_receipts(
        project_id, protocol_id, command_scope, idempotency_key_hash, input_hash,
        result_status, result_aggregate_version, created_at
    ) VALUES (
        p_project_id, p_protocol_id, 'create', p_idempotency_key_hash,
        p_input_hash, 'draft', 1, p_occurred_at
    );
    RETURN QUERY SELECT * FROM workflow_c_statistical_protocol_versions
     WHERE project_id = p_project_id AND id = p_protocol_id;
END;
$$;

CREATE FUNCTION geo_transition_workflow_c_statistical_protocol(
    p_project_id uuid, p_protocol_id uuid, p_expected_aggregate_version integer,
    p_target_status text, p_actor_id text, p_reason text,
    p_idempotency_key_hash text, p_input_hash text, p_occurred_at timestamptz
) RETURNS SETOF workflow_c_statistical_protocol_versions
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE current_row workflow_c_statistical_protocol_versions%ROWTYPE;
DECLARE existing workflow_c_statistical_protocol_command_receipts%ROWTYPE;
DECLARE command_name text;
BEGIN
    command_name := CASE p_target_status
        WHEN 'in_review' THEN 'submit' WHEN 'approved' THEN 'approve'
        WHEN 'retired' THEN 'retire' ELSE NULL END;
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_protocol_id IS NULL OR p_expected_aggregate_version IS NULL
       OR p_expected_aggregate_version < 1 OR command_name IS NULL
       OR btrim(coalesce(p_actor_id, '')) = ''
       OR (p_target_status IN ('approved', 'retired')
           AND btrim(coalesce(p_reason, '')) = '')
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_occurred_at IS NULL THEN
        RAISE EXCEPTION 'Statistical Protocol transition input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM workflow_c_statistical_protocol_command_receipts
     WHERE project_id = p_project_id AND protocol_id = p_protocol_id
       AND command_scope = command_name AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash THEN
            RAISE EXCEPTION 'Statistical Protocol Idempotency-Key changed input'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT * FROM workflow_c_statistical_protocol_versions
         WHERE project_id = p_project_id AND id = p_protocol_id;
        RETURN;
    END IF;
    SELECT * INTO current_row FROM workflow_c_statistical_protocol_versions
     WHERE project_id = p_project_id AND id = p_protocol_id FOR UPDATE;
    IF current_row.id IS NULL
       OR current_row.aggregate_version <> p_expected_aggregate_version THEN
        RAISE EXCEPTION 'Statistical Protocol optimistic version check failed'
            USING ERRCODE = '40001';
    END IF;
    UPDATE workflow_c_statistical_protocol_versions SET
        status = p_target_status,
        submitted_by = CASE WHEN p_target_status = 'in_review' THEN p_actor_id ELSE submitted_by END,
        submitted_at = CASE WHEN p_target_status = 'in_review' THEN p_occurred_at ELSE submitted_at END,
        approved_by = CASE WHEN p_target_status = 'approved' THEN p_actor_id ELSE approved_by END,
        approved_at = CASE WHEN p_target_status = 'approved' THEN p_occurred_at ELSE approved_at END,
        retired_by = CASE WHEN p_target_status = 'retired' THEN p_actor_id ELSE retired_by END,
        retired_at = CASE WHEN p_target_status = 'retired' THEN p_occurred_at ELSE retired_at END,
        decision_reason = CASE WHEN p_target_status IN ('approved', 'retired')
                               THEN p_reason ELSE decision_reason END,
        aggregate_version = aggregate_version + 1,
        updated_at = p_occurred_at
     WHERE project_id = p_project_id AND id = p_protocol_id;
    INSERT INTO workflow_c_statistical_protocol_command_receipts(
        project_id, protocol_id, command_scope, idempotency_key_hash, input_hash,
        result_status, result_aggregate_version, created_at
    ) SELECT p_project_id, p_protocol_id, command_name, p_idempotency_key_hash,
             p_input_hash, status, aggregate_version, p_occurred_at
        FROM workflow_c_statistical_protocol_versions
       WHERE project_id = p_project_id AND id = p_protocol_id;
    RETURN QUERY SELECT * FROM workflow_c_statistical_protocol_versions
     WHERE project_id = p_project_id AND id = p_protocol_id;
END;
$$;

-- 0071 correctly validates all frozen comparison fields, but mistakenly
-- rejects an empty valid-pair set. Empty pairs are necessary to represent a
-- frozen planned denominator that resolves to insufficient evidence.
ALTER FUNCTION geo_workflow_c_analysis_job_spec_is_valid(text, jsonb)
RENAME TO geo_workflow_c_analysis_job_spec_v1_is_valid;

CREATE FUNCTION geo_workflow_c_analysis_job_spec_is_valid(
    p_kind text, p_payload jsonb
) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public AS $$
DECLARE transformed jsonb;
DECLARE admission jsonb;
BEGIN
    IF geo_workflow_c_analysis_job_spec_v1_is_valid(p_kind, p_payload) THEN
        RETURN true;
    END IF;
    IF p_kind IN ('workflow_c.analysis.comparison', 'workflow_c.analysis.drift')
       AND geo_workflow_c_json_has_exact_keys(p_payload, ARRAY[
            'schema_version', 'kind', 'admission',
            CASE WHEN p_kind = 'workflow_c.analysis.comparison'
                 THEN 'comparison' ELSE 'drift' END
       ]) THEN
        admission := p_payload->'admission';
        IF NOT geo_workflow_c_json_has_exact_keys(admission, ARRAY[
                'protocol_kind', 'protocol_id', 'protocol_hash',
                'source_snapshot_hash', 'target_snapshot_hash', 'requested_by'
           ])
           OR admission->>'protocol_kind' <> (CASE
                WHEN p_kind = 'workflow_c.analysis.comparison'
                THEN 'comparison_plan' ELSE 'drift_protocol' END)
           OR NOT geo_workflow_c_json_is_uuid(admission->'protocol_id')
           OR NOT geo_workflow_c_json_is_sha256(admission->'protocol_hash')
           OR NOT geo_workflow_c_json_is_sha256(admission->'source_snapshot_hash')
           OR NOT geo_workflow_c_json_is_sha256(admission->'target_snapshot_hash')
           OR admission->>'source_snapshot_hash' = admission->>'target_snapshot_hash'
           OR NOT geo_workflow_c_analysis_nonempty_text_is_valid(
                admission->'requested_by'
           ) THEN
            RETURN false;
        END IF;
        transformed := p_payload - 'admission';
        IF geo_workflow_c_analysis_job_spec_v1_is_valid(p_kind, transformed) THEN
            RETURN true;
        END IF;
    ELSE
        transformed := p_payload;
    END IF;
    IF p_kind <> 'workflow_c.analysis.comparison'
       OR NOT geo_workflow_c_json_has_exact_keys(
            transformed, ARRAY['schema_version', 'kind', 'comparison']
       )
       OR NOT geo_workflow_c_json_has_exact_keys(
            transformed->'comparison', ARRAY['inputs']
       )
       OR jsonb_typeof(transformed->'comparison'->'inputs') <> 'array'
       OR jsonb_array_length(transformed->'comparison'->'inputs') < 1 THEN
        RETURN false;
    END IF;
    SELECT jsonb_set(
               transformed,
               '{comparison,inputs}',
               jsonb_agg(
                   CASE
                       WHEN jsonb_typeof(value->'pairs') = 'array'
                            AND jsonb_array_length(value->'pairs') = 0
                       THEN jsonb_set(value, '{pairs}', jsonb_build_array(
                           jsonb_build_object(
                               'pair_id', 'validation-placeholder',
                               'question_id', 'validation-placeholder',
                               'question_cluster', value->'protocol'->'stratum'->'question_cluster',
                               'stratum_hash', encode(digest(convert_to(
                                   geo_workflow_c_python_canonical_text(
                                       value->'protocol'->'stratum'
                                   ), 'UTF8'
                               ), 'sha256'), 'hex'),
                               'sampling_source_stratum_hash',
                                   value->'sampling_source_stratum_hash',
                               'capture_method',
                                   value->'protocol'->'stratum'->'capture_method',
                               'baseline', '0', 'candidate', '0'
                           )
                       ))
                       ELSE value
                   END ORDER BY ordinal
               )
           ) INTO transformed
      FROM jsonb_array_elements(transformed->'comparison'->'inputs')
           WITH ORDINALITY AS input(value, ordinal);
    RETURN geo_workflow_c_analysis_job_spec_v1_is_valid(p_kind, transformed);
END;
$$;

-- Governed drift reports retain the approved Drift Protocol hash.  Keep the
-- 0070 function for already queued legacy specs and use this stricter v2
-- entry point only when the immutable admission envelope is present.
CREATE FUNCTION geo_persist_workflow_c_drift_report_v2(
    p_project_id uuid,
    p_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_report_hash text,
    p_protocol_hash text,
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
       OR p_job_id IS NULL OR p_lease_token IS NULL
       OR p_fencing_generation IS NULL OR p_fencing_generation < 1
       OR p_report_hash IS NULL OR p_report_hash !~ '^[0-9a-f]{64}$'
       OR p_protocol_hash IS NULL OR p_protocol_hash !~ '^[0-9a-f]{64}$'
       OR p_source_snapshot_hash IS NULL
       OR p_source_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_target_snapshot_hash IS NULL
       OR p_target_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_source_snapshot_hash = p_target_snapshot_hash
       OR p_report_payload IS NULL OR jsonb_typeof(p_report_payload) <> 'object'
       OR p_computed_at IS NULL THEN
        RAISE EXCEPTION 'Workflow C governed drift persistence input is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NOT geo_workflow_c_json_has_exact_keys(p_report_payload, ARRAY[
            'model_drift', 'source_drift', 'effect_drift',
            'unmatched_baseline_strata', 'unmatched_current_strata',
            'baseline_input_hash', 'current_input_hash', 'protocol_hash',
            'method_version'
       ])
       OR jsonb_typeof(p_report_payload->'model_drift') <> 'array'
       OR jsonb_typeof(p_report_payload->'source_drift') <> 'array'
       OR jsonb_typeof(p_report_payload->'effect_drift') <> 'array'
       OR jsonb_typeof(p_report_payload->'unmatched_baseline_strata') <> 'array'
       OR jsonb_typeof(p_report_payload->'unmatched_current_strata') <> 'array'
       OR p_report_payload->>'baseline_input_hash' !~ '^[0-9a-f]{64}$'
       OR p_report_payload->>'current_input_hash' !~ '^[0-9a-f]{64}$'
       OR p_report_payload->>'protocol_hash' IS DISTINCT FROM p_protocol_hash
       OR jsonb_typeof(p_report_payload->'method_version') <> 'string'
       OR btrim(p_report_payload->>'method_version') = ''
       OR encode(digest(convert_to(
            geo_workflow_c_python_canonical_text(p_report_payload), 'UTF8'
          ), 'sha256'), 'hex') <> p_report_hash THEN
        RAISE EXCEPTION 'Workflow C governed drift report hash or lineage is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT durable.* INTO parent_job
      FROM durable_jobs AS durable
     WHERE durable.project_id = p_project_id AND durable.id = p_job_id
     FOR SHARE;
    SELECT spec.* INTO parent_spec
      FROM workflow_c_job_specs AS spec
     WHERE spec.project_id = p_project_id AND spec.job_id = p_job_id
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
       OR parent_job.cancel_requested_at IS NOT NULL
       OR parent_spec.spec_payload->'admission'->>'protocol_kind' <> 'drift_protocol'
       OR parent_spec.spec_payload->'admission'->>'protocol_hash'
          IS DISTINCT FROM p_protocol_hash
       OR parent_spec.spec_payload->'admission'->>'source_snapshot_hash'
          IS DISTINCT FROM p_source_snapshot_hash
       OR parent_spec.spec_payload->'admission'->>'target_snapshot_hash'
          IS DISTINCT FROM p_target_snapshot_hash THEN
        RAISE EXCEPTION 'Workflow C governed drift parent admission was fenced'
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
        RAISE EXCEPTION 'Workflow C governed drift report hash collides with other input'
            USING ERRCODE = '23505';
    END IF;
END;
$$;

ALTER TABLE workflow_c_statistical_protocol_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_statistical_protocol_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_statistical_protocol_versions
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE workflow_c_statistical_protocol_command_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_statistical_protocol_command_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_statistical_protocol_command_receipts
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON workflow_c_statistical_protocol_versions,
    workflow_c_statistical_protocol_command_receipts FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON workflow_c_statistical_protocol_versions,
    workflow_c_statistical_protocol_command_receipts FROM geo_app, geo_worker;
GRANT SELECT ON workflow_c_statistical_protocol_versions TO geo_app, geo_worker;
GRANT SELECT ON workflow_c_statistical_protocol_command_receipts TO geo_worker;

REVOKE ALL ON FUNCTION geo_create_workflow_c_statistical_protocol(
    uuid, uuid, text, uuid, integer, uuid, text, jsonb, text, text, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_transition_workflow_c_statistical_protocol(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_create_workflow_c_statistical_protocol(
    uuid, uuid, text, uuid, integer, uuid, text, jsonb, text, text, text, timestamptz
) TO geo_app;
GRANT EXECUTE ON FUNCTION geo_transition_workflow_c_statistical_protocol(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
) TO geo_app;
REVOKE ALL ON FUNCTION geo_persist_workflow_c_drift_report_v2(
    uuid, uuid, uuid, integer, text, text, text, text, jsonb, timestamptz
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_persist_workflow_c_drift_report_v2(
    uuid, uuid, uuid, integer, text, text, text, text, jsonb, timestamptz
) TO geo_worker;
