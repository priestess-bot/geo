DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM external_operational_alert_inputs) THEN
        RAISE EXCEPTION 'cannot downgrade: external operational alert evidence exists'
            USING ERRCODE = '55000';
    END IF;
END $$;

DROP TRIGGER browser_drift_alert_input ON browser_surface_drift_events;
DROP TRIGGER connector_freshness_alert_input ON connector_freshness;
DROP TRIGGER connector_error_alert_input ON connector_errors;
DROP FUNCTION geo_project_browser_drift_alert_input();
DROP FUNCTION geo_project_connector_freshness_alert_input();
DROP FUNCTION geo_project_connector_error_alert_input();
DROP FUNCTION geo_insert_external_operational_alert_input(
    uuid,text,uuid,integer,text,text,text,text,jsonb,timestamptz
);
DROP TRIGGER external_operational_alert_inputs_immutable ON external_operational_alert_inputs;
DROP TABLE external_operational_alert_inputs;

ALTER TABLE workflow_c_alert_rule_versions
DROP CONSTRAINT workflow_c_alert_rule_versions_payload_check;
ALTER TABLE workflow_c_alert_rule_versions
ADD CONSTRAINT workflow_c_alert_rule_versions_payload_check CHECK (
    jsonb_typeof(payload) = 'object'
    AND payload->>'kind' IN (
        'threshold', 'baseline_delta', 'negative_question',
        'completion_freshness', 'model_drift', 'source_drift',
        'connector_failure'
    )
);
DROP FUNCTION geo_workflow_c_alert_rule_payload_is_valid(jsonb);
ALTER FUNCTION geo_workflow_c_alert_rule_payload_is_valid_v1(jsonb)
RENAME TO geo_workflow_c_alert_rule_payload_is_valid;
