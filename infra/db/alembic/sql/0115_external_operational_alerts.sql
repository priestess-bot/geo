ALTER FUNCTION geo_workflow_c_alert_rule_payload_is_valid(jsonb)
RENAME TO geo_workflow_c_alert_rule_payload_is_valid_v1;

CREATE FUNCTION geo_workflow_c_alert_rule_payload_is_valid(p_payload jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE STRICT
SET search_path = pg_catalog, public AS $$
    SELECT CASE WHEN p_payload->>'kind' = 'external_health' THEN
        geo_workflow_c_json_has_exact_keys(p_payload, ARRAY['kind', 'severity', 'parameters'])
        AND p_payload->>'severity' IN ('info', 'warning', 'critical')
        AND geo_workflow_c_json_has_exact_keys(
            p_payload->'parameters', ARRAY['schema_version', 'minimum_severity']
        )
        AND p_payload->'parameters'->>'schema_version' = 'alert-rule-external-health-v1'
        AND p_payload->'parameters'->>'minimum_severity' IN ('info', 'warning', 'critical')
    ELSE geo_workflow_c_alert_rule_payload_is_valid_v1(p_payload) END
$$;

ALTER TABLE workflow_c_alert_rule_versions
DROP CONSTRAINT workflow_c_alert_rule_versions_payload_check;
ALTER TABLE workflow_c_alert_rule_versions
ADD CONSTRAINT workflow_c_alert_rule_versions_payload_check CHECK (
    jsonb_typeof(payload) = 'object'
    AND payload->>'kind' IN (
        'threshold', 'baseline_delta', 'negative_question',
        'completion_freshness', 'model_drift', 'source_drift',
        'connector_failure', 'external_health'
    )
);

CREATE TABLE external_operational_alert_inputs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_kind text NOT NULL CHECK (source_kind IN (
        'connector_error', 'connector_freshness', 'browser_surface_drift'
    )),
    source_id uuid NOT NULL,
    source_version integer NOT NULL CHECK (source_version > 0),
    signal_kind text NOT NULL CHECK (signal_kind IN (
        'connector_auth', 'connector_schema', 'connector_quota',
        'connector_rate', 'connector_failure', 'connector_freshness',
        'surface_parser', 'browser_build'
    )),
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    reason_code text NOT NULL CHECK (reason_code ~ '^[a-z][a-z0-9_.:-]{0,99}$'),
    action_path text NOT NULL CHECK (action_path LIKE '/projects/%'),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND NOT payload ?| ARRAY[
            'credential', 'secret', 'token', 'raw_body', 'raw_response',
            'artifact_uri', 'debug', 'model_reasoning'
        ]
    ),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, source_kind, source_id, signal_kind),
    UNIQUE (project_id, input_hash)
);

CREATE INDEX external_operational_alert_inputs_recent_idx
ON external_operational_alert_inputs(project_id, observed_at DESC, id DESC);

CREATE FUNCTION geo_insert_external_operational_alert_input(
    p_project_id uuid, p_source_kind text, p_source_id uuid,
    p_source_version integer, p_signal_kind text, p_severity text,
    p_reason_code text, p_action_path text, p_payload jsonb,
    p_observed_at timestamptz
) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE canonical jsonb;
DECLARE calculated_hash text;
BEGIN
    canonical := jsonb_build_object(
        'schema_version', 'alert-input-external-health-v1',
        'source_kind', p_source_kind, 'source_id', p_source_id::text,
        'source_version', p_source_version, 'signal_kind', p_signal_kind,
        'severity', p_severity, 'reason_code', p_reason_code,
        'action_path', p_action_path, 'payload', p_payload,
        'observed_at', to_char(p_observed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
    );
    calculated_hash := encode(digest(convert_to(
        geo_workflow_c_python_canonical_text(canonical), 'UTF8'
    ), 'sha256'), 'hex');
    INSERT INTO external_operational_alert_inputs(
        project_id, source_kind, source_id, source_version, signal_kind,
        severity, reason_code, action_path, payload, input_hash, observed_at
    ) VALUES (
        p_project_id, p_source_kind, p_source_id, p_source_version, p_signal_kind,
        p_severity, p_reason_code, p_action_path, p_payload, calculated_hash, p_observed_at
    ) ON CONFLICT (project_id, source_kind, source_id, signal_kind) DO NOTHING;
    RETURN calculated_hash;
END;
$$;

CREATE FUNCTION geo_project_connector_error_alert_input()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE run_version integer;
DECLARE signal text;
DECLARE level text;
BEGIN
    SELECT version INTO run_version FROM connector_sync_runs
     WHERE project_id = NEW.project_id AND id = NEW.sync_run_id;
    signal := CASE NEW.error_class
        WHEN 'auth' THEN 'connector_auth' WHEN 'revoked' THEN 'connector_auth'
        WHEN 'schema' THEN 'connector_schema' WHEN 'quota' THEN 'connector_quota'
        WHEN 'rate' THEN 'connector_rate' ELSE 'connector_failure' END;
    level := CASE WHEN NEW.error_class IN ('auth', 'revoked', 'schema', 'permanent')
                  THEN 'critical' ELSE 'warning' END;
    PERFORM geo_insert_external_operational_alert_input(
        NEW.project_id, 'connector_error', NEW.id, run_version, signal, level,
        NEW.error_code,
        '/projects/' || NEW.project_id::text || '/external-data?section=connectors&run=' || NEW.sync_run_id::text,
        jsonb_build_object(
            'sync_run_id', NEW.sync_run_id::text, 'error_class', NEW.error_class,
            'error_code', NEW.error_code, 'retryable', NEW.retryable,
            'operator_action', NEW.operator_action
        ), NEW.occurred_at
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_project_connector_freshness_alert_input()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
DECLARE run_version integer;
BEGIN
    IF NEW.status <> 'stale' THEN RETURN NEW; END IF;
    SELECT version INTO run_version FROM connector_sync_runs
     WHERE project_id = NEW.project_id AND id = NEW.sync_run_id;
    PERFORM geo_insert_external_operational_alert_input(
        NEW.project_id, 'connector_freshness', NEW.id, run_version,
        'connector_freshness', 'warning', 'connector_data_stale',
        '/projects/' || NEW.project_id::text || '/external-data?section=connectors&run=' || NEW.sync_run_id::text,
        jsonb_build_object(
            'sync_run_id', NEW.sync_run_id::text, 'connection_id', NEW.connection_id::text,
            'scope_id', NEW.scope_id::text, 'lag_seconds', NEW.lag_seconds,
            'reason', NEW.reason
        ), NEW.observed_at
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_project_browser_drift_alert_input()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public SET row_security = off AS $$
BEGIN
    PERFORM geo_insert_external_operational_alert_input(
        NEW.project_id, 'browser_surface_drift', NEW.id, 1,
        CASE NEW.drift_kind WHEN 'selector_parser' THEN 'surface_parser' ELSE 'browser_build' END,
        CASE WHEN NEW.release_suspended THEN 'critical' ELSE 'warning' END,
        CASE NEW.drift_kind WHEN 'selector_parser' THEN 'surface_parser_drift'
                            ELSE 'browser_build_drift' END,
        '/projects/' || NEW.project_id::text || '/external-data?section=browser&release=' || NEW.surface_release_id::text,
        jsonb_build_object(
            'surface_release_id', NEW.surface_release_id::text,
            'drift_kind', NEW.drift_kind, 'expected_value', NEW.expected_value,
            'observed_value', NEW.observed_value,
            'release_suspended', NEW.release_suspended
        ), NEW.detected_at
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER connector_error_alert_input
AFTER INSERT ON connector_errors FOR EACH ROW
EXECUTE FUNCTION geo_project_connector_error_alert_input();
CREATE TRIGGER connector_freshness_alert_input
AFTER INSERT ON connector_freshness FOR EACH ROW
EXECUTE FUNCTION geo_project_connector_freshness_alert_input();
CREATE TRIGGER browser_drift_alert_input
AFTER INSERT ON browser_surface_drift_events FOR EACH ROW
EXECUTE FUNCTION geo_project_browser_drift_alert_input();

CREATE TRIGGER external_operational_alert_inputs_immutable
BEFORE UPDATE OR DELETE ON external_operational_alert_inputs
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
ALTER TABLE external_operational_alert_inputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_operational_alert_inputs FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON external_operational_alert_inputs
USING (project_id = ANY(geo_current_project_ids()));
GRANT SELECT ON external_operational_alert_inputs TO geo_app, geo_worker;
REVOKE ALL ON FUNCTION geo_insert_external_operational_alert_input(
    uuid,text,uuid,integer,text,text,text,text,jsonb,timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_project_connector_error_alert_input(),
    geo_project_connector_freshness_alert_input(),
    geo_project_browser_drift_alert_input()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
