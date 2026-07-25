-- Alert rules are governance records. Only scoped commands may create a draft
-- or move it through independent approval and retirement.

ALTER TABLE workflow_c_alert_rule_versions
ADD COLUMN aggregate_version integer NOT NULL DEFAULT 1 CHECK (aggregate_version > 0),
ADD COLUMN retired_by text,
ADD COLUMN retired_at timestamptz,
ADD COLUMN decision_reason text;

UPDATE workflow_c_alert_rule_versions
SET aggregate_version = CASE status WHEN 'draft' THEN 1 WHEN 'approved' THEN 2 ELSE 3 END,
    decision_reason = CASE
        WHEN status = 'draft' THEN NULL ELSE 'legacy_release_imported_before_0077' END,
    approved_by = CASE
        WHEN status = 'retired' THEN created_by || '-legacy-approval'
        ELSE approved_by END,
    approved_at = CASE
        WHEN status = 'retired' THEN created_at ELSE approved_at END,
    retired_by = CASE WHEN status = 'retired' THEN created_by ELSE NULL END,
    retired_at = CASE WHEN status = 'retired' THEN created_at ELSE NULL END;

DO $$
DECLARE constraint_name text;
BEGIN
    SELECT conname INTO constraint_name
      FROM pg_constraint
     WHERE conrelid = 'workflow_c_alert_rule_versions'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%status = ''approved''%approved_by IS NOT NULL%';
    IF constraint_name IS NULL THEN
        RAISE EXCEPTION 'legacy alert-rule lifecycle constraint was not found';
    END IF;
    EXECUTE format(
        'ALTER TABLE workflow_c_alert_rule_versions DROP CONSTRAINT %I',
        constraint_name
    );
END;
$$;

ALTER TABLE workflow_c_alert_rule_versions
ADD CONSTRAINT workflow_c_alert_rule_versions_lifecycle_check CHECK (
    (status = 'draft'
        AND approved_by IS NULL AND approved_at IS NULL
        AND retired_by IS NULL AND retired_at IS NULL AND decision_reason IS NULL)
    OR (status = 'approved'
        AND approved_by IS NOT NULL AND approved_at IS NOT NULL
        AND approved_by <> created_by
        AND retired_by IS NULL AND retired_at IS NULL
        AND btrim(coalesce(decision_reason, '')) <> '')
    OR (status = 'retired'
        AND approved_by IS NOT NULL AND approved_at IS NOT NULL
        AND approved_by <> created_by
        AND retired_by IS NOT NULL AND retired_at IS NOT NULL
        AND btrim(coalesce(decision_reason, '')) <> '')
);

CREATE TABLE workflow_c_alert_rule_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rule_id uuid NOT NULL,
    command_scope text NOT NULL CHECK (
        command_scope IN ('create', 'approve', 'retire')
    ),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    result_status text NOT NULL CHECK (result_status IN ('draft', 'approved', 'retired')),
    result_aggregate_version integer NOT NULL CHECK (result_aggregate_version > 0),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, rule_id, command_scope, idempotency_key_hash),
    FOREIGN KEY (rule_id, project_id)
        REFERENCES workflow_c_alert_rule_versions(id, project_id)
);

CREATE FUNCTION geo_workflow_c_alert_rule_payload_is_valid(p_payload jsonb)
RETURNS boolean
LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public AS $$
DECLARE kind text := p_payload->>'kind';
DECLARE parameters jsonb := p_payload->'parameters';
BEGIN
    IF NOT geo_workflow_c_json_has_exact_keys(
            p_payload, ARRAY['kind', 'severity', 'parameters']
       )
       OR kind NOT IN (
            'threshold', 'baseline_delta', 'negative_question',
            'completion_freshness', 'model_drift', 'source_drift'
       )
       OR p_payload->>'severity' NOT IN ('info', 'warning', 'critical')
       OR jsonb_typeof(parameters) <> 'object' THEN
        RETURN false;
    END IF;
    IF kind = 'threshold' THEN
        RETURN geo_workflow_c_json_has_exact_keys(parameters, ARRAY[
                   'schema_version', 'metric_key', 'operator', 'threshold'
               ])
           AND parameters->>'schema_version' = 'alert-rule-threshold-v1'
           AND geo_workflow_c_analysis_nonempty_text_is_valid(parameters->'metric_key')
           AND parameters->>'operator' IN ('lt', 'lte', 'gt', 'gte')
           AND geo_workflow_c_analysis_decimal_is_valid(parameters->'threshold');
    ELSIF kind = 'baseline_delta' THEN
        RETURN geo_workflow_c_json_has_exact_keys(parameters, ARRAY[
                   'schema_version', 'metric_key', 'direction', 'minimum_delta'
               ])
           AND parameters->>'schema_version' = 'alert-rule-baseline-delta-v1'
           AND geo_workflow_c_analysis_nonempty_text_is_valid(parameters->'metric_key')
           AND parameters->>'direction' IN ('decrease', 'increase', 'absolute')
           AND geo_workflow_c_analysis_decimal_is_valid(parameters->'minimum_delta')
           AND (parameters->>'minimum_delta')::numeric > 0;
    ELSIF kind = 'negative_question' THEN
        RETURN geo_workflow_c_json_has_exact_keys(parameters, ARRAY[
                   'schema_version', 'metric_key', 'maximum_delta',
                   'require_interval_below_zero'
               ])
           AND parameters->>'schema_version' = 'alert-rule-negative-question-v1'
           AND geo_workflow_c_analysis_nonempty_text_is_valid(parameters->'metric_key')
           AND geo_workflow_c_analysis_decimal_is_valid(parameters->'maximum_delta')
           AND (parameters->>'maximum_delta')::numeric < 0
           AND jsonb_typeof(parameters->'require_interval_below_zero') = 'boolean';
    ELSIF kind = 'completion_freshness' THEN
        RETURN geo_workflow_c_json_has_exact_keys(parameters, ARRAY[
                   'schema_version', 'minimum_completion_ratio', 'maximum_age_seconds'
               ])
           AND parameters->>'schema_version' = 'alert-rule-completion-freshness-v1'
           AND geo_workflow_c_analysis_decimal_is_valid(
                parameters->'minimum_completion_ratio'
           )
           AND (parameters->>'minimum_completion_ratio')::numeric BETWEEN 0 AND 1
           AND geo_workflow_c_json_is_positive_integer(parameters->'maximum_age_seconds');
    ELSIF kind = 'model_drift' THEN
        RETURN geo_workflow_c_json_has_exact_keys(parameters, ARRAY[
                   'schema_version', 'minimum_changed_models'
               ])
           AND parameters->>'schema_version' = 'alert-rule-model-drift-v1'
           AND geo_workflow_c_json_is_positive_integer(parameters->'minimum_changed_models');
    END IF;
    RETURN geo_workflow_c_json_has_exact_keys(parameters, ARRAY[
               'schema_version', 'minimum_changed_compositions'
           ])
       AND parameters->>'schema_version' = 'alert-rule-source-drift-v1'
       AND geo_workflow_c_json_is_positive_integer(parameters->'minimum_changed_compositions');
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_alert_rule_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Workflow C alert-rule history cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' OR NEW.aggregate_version <> 1
           OR NEW.approved_by IS NOT NULL OR NEW.approved_at IS NOT NULL
           OR NEW.retired_by IS NOT NULL OR NEW.retired_at IS NOT NULL
           OR NEW.decision_reason IS NOT NULL
           OR NOT geo_workflow_c_alert_rule_payload_is_valid(NEW.payload) THEN
            RAISE EXCEPTION 'Workflow C alert rule must begin as a valid draft'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF ROW(NEW.id, NEW.project_id, NEW.rule_key, NEW.version, NEW.rule_hash,
           NEW.payload, NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.project_id, OLD.rule_key, OLD.version, OLD.rule_hash,
           OLD.payload, OLD.created_by, OLD.created_at)
       OR NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
        RAISE EXCEPTION 'Workflow C alert-rule definition or version changed'
            USING ERRCODE = '40001';
    END IF;
    IF OLD.status = 'draft' AND NEW.status = 'approved'
       AND NEW.approved_by IS NOT NULL AND NEW.approved_by <> NEW.created_by
       AND NEW.approved_at IS NOT NULL AND NEW.retired_by IS NULL
       AND NEW.retired_at IS NULL AND NEW.decision_reason IS NOT NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'approved' AND NEW.status = 'retired'
       AND NEW.approved_by = OLD.approved_by AND NEW.approved_at = OLD.approved_at
       AND NEW.retired_by IS NOT NULL AND NEW.retired_at IS NOT NULL
       AND NEW.decision_reason IS NOT NULL THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Workflow C alert-rule lifecycle transition is invalid'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER workflow_c_alert_rule_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON workflow_c_alert_rule_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_alert_rule_change();

CREATE TRIGGER workflow_c_alert_rule_receipts_immutable
BEFORE UPDATE OR DELETE ON workflow_c_alert_rule_command_receipts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE FUNCTION geo_create_workflow_c_alert_rule(
    p_project_id uuid, p_rule_id uuid, p_rule_key text, p_version integer,
    p_rule_hash text, p_payload jsonb, p_created_by text,
    p_idempotency_key_hash text, p_input_hash text, p_occurred_at timestamptz
) RETURNS SETOF workflow_c_alert_rule_versions
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE existing workflow_c_alert_rule_command_receipts%ROWTYPE;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_rule_id IS NULL OR p_rule_key !~ '^[a-z][a-z0-9_.:-]{0,199}$'
       OR p_version IS NULL OR p_version < 1
       OR p_rule_hash !~ '^[0-9a-f]{64}$'
       OR NOT geo_workflow_c_alert_rule_payload_is_valid(p_payload)
       OR btrim(coalesce(p_created_by, '')) = ''
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_occurred_at IS NULL THEN
        RAISE EXCEPTION 'Workflow C alert-rule create input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM workflow_c_alert_rule_command_receipts
     WHERE project_id = p_project_id AND rule_id = p_rule_id
       AND command_scope = 'create' AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash THEN
            RAISE EXCEPTION 'Workflow C alert-rule Idempotency-Key changed input'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT * FROM workflow_c_alert_rule_versions
         WHERE project_id = p_project_id AND id = p_rule_id;
        RETURN;
    END IF;
    INSERT INTO workflow_c_alert_rule_versions(
        id, project_id, rule_key, version, status, rule_hash, payload,
        created_by, created_at, aggregate_version
    ) VALUES (
        p_rule_id, p_project_id, p_rule_key, p_version, 'draft', p_rule_hash,
        p_payload, p_created_by, p_occurred_at, 1
    );
    INSERT INTO workflow_c_alert_rule_command_receipts(
        project_id, rule_id, command_scope, idempotency_key_hash, input_hash,
        result_status, result_aggregate_version, created_at
    ) VALUES (
        p_project_id, p_rule_id, 'create', p_idempotency_key_hash,
        p_input_hash, 'draft', 1, p_occurred_at
    );
    RETURN QUERY SELECT * FROM workflow_c_alert_rule_versions
     WHERE project_id = p_project_id AND id = p_rule_id;
END;
$$;

CREATE FUNCTION geo_transition_workflow_c_alert_rule(
    p_project_id uuid, p_rule_id uuid, p_expected_aggregate_version integer,
    p_target_status text, p_actor_id text, p_reason text,
    p_idempotency_key_hash text, p_input_hash text, p_occurred_at timestamptz
) RETURNS SETOF workflow_c_alert_rule_versions
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE current_row workflow_c_alert_rule_versions%ROWTYPE;
DECLARE existing workflow_c_alert_rule_command_receipts%ROWTYPE;
DECLARE command_name text;
BEGIN
    command_name := CASE p_target_status
        WHEN 'approved' THEN 'approve' WHEN 'retired' THEN 'retire' ELSE NULL END;
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_rule_id IS NULL OR p_expected_aggregate_version IS NULL
       OR p_expected_aggregate_version < 1 OR command_name IS NULL
       OR btrim(coalesce(p_actor_id, '')) = '' OR btrim(coalesce(p_reason, '')) = ''
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_occurred_at IS NULL THEN
        RAISE EXCEPTION 'Workflow C alert-rule transition input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing FROM workflow_c_alert_rule_command_receipts
     WHERE project_id = p_project_id AND rule_id = p_rule_id
       AND command_scope = command_name AND idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF existing.input_hash <> p_input_hash THEN
            RAISE EXCEPTION 'Workflow C alert-rule Idempotency-Key changed input'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT * FROM workflow_c_alert_rule_versions
         WHERE project_id = p_project_id AND id = p_rule_id;
        RETURN;
    END IF;
    SELECT * INTO current_row FROM workflow_c_alert_rule_versions
     WHERE project_id = p_project_id AND id = p_rule_id FOR UPDATE;
    IF current_row.id IS NULL OR current_row.aggregate_version <> p_expected_aggregate_version THEN
        RAISE EXCEPTION 'Workflow C alert-rule optimistic version check failed'
            USING ERRCODE = '40001';
    END IF;
    UPDATE workflow_c_alert_rule_versions SET
        status = p_target_status,
        approved_by = CASE WHEN p_target_status = 'approved' THEN p_actor_id ELSE approved_by END,
        approved_at = CASE WHEN p_target_status = 'approved' THEN p_occurred_at ELSE approved_at END,
        retired_by = CASE WHEN p_target_status = 'retired' THEN p_actor_id ELSE retired_by END,
        retired_at = CASE WHEN p_target_status = 'retired' THEN p_occurred_at ELSE retired_at END,
        decision_reason = p_reason,
        aggregate_version = aggregate_version + 1
     WHERE project_id = p_project_id AND id = p_rule_id;
    INSERT INTO workflow_c_alert_rule_command_receipts(
        project_id, rule_id, command_scope, idempotency_key_hash, input_hash,
        result_status, result_aggregate_version, created_at
    ) SELECT p_project_id, p_rule_id, command_name, p_idempotency_key_hash,
             p_input_hash, status, aggregate_version, p_occurred_at
        FROM workflow_c_alert_rule_versions
       WHERE project_id = p_project_id AND id = p_rule_id;
    RETURN QUERY SELECT * FROM workflow_c_alert_rule_versions
     WHERE project_id = p_project_id AND id = p_rule_id;
END;
$$;

-- Report publication is also maker-checker. Source eligibility remains
-- revalidated at the exact approved version append.
CREATE OR REPLACE FUNCTION geo_assert_workflow_c_report_snapshot_version_append()
RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE predecessor workflow_c_report_snapshot_versions%ROWTYPE;
DECLARE draft_actor uuid;
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
       AND version = NEW.version - 1;
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
    IF NEW.status = 'approved' THEN
        SELECT actor_id INTO STRICT draft_actor
          FROM workflow_c_report_snapshot_versions
         WHERE project_id = NEW.project_id AND report_id = NEW.report_id AND version = 1;
        IF NEW.actor_id = draft_actor THEN
            RAISE EXCEPTION 'Workflow C report maker cannot approve the same report'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM monitoring_reports AS report
              JOIN workflow_c_semantic_metric_snapshots AS metric
                ON metric.project_id = report.project_id
               AND metric.snapshot_hash = NEW.semantic_snapshot_hash
             WHERE report.project_id = NEW.project_id
               AND report.campaign_id = NEW.campaign_id
               AND report.id = NEW.monitoring_report_id
               AND report.report_hash = NEW.monitoring_report_hash
               AND metric.evidence_status = 'complete'
               AND metric.approved_at IS NOT NULL
               AND NOT metric.test_only AND NOT metric.synthetic
               AND metric.capture_method = NEW.source_kind
        ) THEN
            RAISE EXCEPTION 'Workflow C approved report source is not Customer eligible'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE workflow_c_alert_rule_command_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_alert_rule_command_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_alert_rule_command_receipts
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE INSERT, UPDATE, DELETE ON workflow_c_alert_rule_versions FROM geo_app, geo_worker;
REVOKE ALL ON workflow_c_alert_rule_command_receipts FROM PUBLIC, geo_app, geo_worker;
GRANT SELECT ON workflow_c_alert_rule_command_receipts TO geo_worker;

REVOKE ALL ON FUNCTION geo_create_workflow_c_alert_rule(
    uuid, uuid, text, integer, text, jsonb, text, text, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_transition_workflow_c_alert_rule(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_create_workflow_c_alert_rule(
    uuid, uuid, text, integer, text, jsonb, text, text, text, timestamptz
) TO geo_app;
GRANT EXECUTE ON FUNCTION geo_transition_workflow_c_alert_rule(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
) TO geo_app;

-- The completion function returns an `evaluation_hash` column and also reads the
-- identically named persisted column.  Resolve PL/pgSQL conflicts in favour of
-- table columns so replay lookup remains deterministic on every supported PG16
-- installation, including functions compiled before this migration.
ALTER FUNCTION geo_complete_workflow_c_alert_evaluation(
    uuid, uuid, uuid, integer, uuid, uuid, integer, uuid, text, text, text,
    text, boolean, jsonb, timestamptz, uuid, text, jsonb, jsonb
) SET plpgsql.variable_conflict = 'use_column';

DO $migration$
DECLARE
    function_definition text;
    unsafe_expression constant text :=
        '''workflow-c-alert-notify:'' || item->>''idempotency_key''';
    safe_expression constant text :=
        '''workflow-c-alert-notify:'' || (item->>''idempotency_key'')';
    unsafe_wake_expression constant text :=
        '''wake:workflow_c.alert.notify:'' || item->>''notify_job_id''';
    safe_wake_expression constant text :=
        '''wake:workflow_c.alert.notify:'' || (item->>''notify_job_id'')';
BEGIN
    SELECT pg_get_functiondef(
        'geo_complete_workflow_c_alert_evaluation(uuid,uuid,uuid,integer,uuid,uuid,integer,uuid,text,text,text,text,boolean,jsonb,timestamptz,uuid,text,jsonb,jsonb)'::regprocedure
    ) INTO STRICT function_definition;
    IF strpos(function_definition, unsafe_expression) = 0 THEN
        RAISE EXCEPTION 'Expected alert notification idempotency expression was not found';
    END IF;
    IF strpos(function_definition, unsafe_wake_expression) = 0 THEN
        RAISE EXCEPTION 'Expected alert notification wake expression was not found';
    END IF;
    function_definition := replace(
        function_definition, unsafe_expression, safe_expression
    );
    EXECUTE replace(
        function_definition, unsafe_wake_expression, safe_wake_expression
    );
END;
$migration$;
