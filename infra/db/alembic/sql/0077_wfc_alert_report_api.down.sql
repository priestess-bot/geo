REVOKE ALL ON FUNCTION geo_transition_workflow_c_alert_rule(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_create_workflow_c_alert_rule(
    uuid, uuid, text, integer, text, jsonb, text, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;

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
    IF strpos(function_definition, safe_expression) = 0 THEN
        RAISE EXCEPTION 'Expected patched alert notification idempotency expression was not found';
    END IF;
    IF strpos(function_definition, safe_wake_expression) = 0 THEN
        RAISE EXCEPTION 'Expected patched alert notification wake expression was not found';
    END IF;
    function_definition := replace(
        function_definition, safe_expression, unsafe_expression
    );
    EXECUTE replace(
        function_definition, safe_wake_expression, unsafe_wake_expression
    );
END;
$migration$;

ALTER FUNCTION geo_complete_workflow_c_alert_evaluation(
    uuid, uuid, uuid, integer, uuid, uuid, integer, uuid, text, text, text,
    text, boolean, jsonb, timestamptz, uuid, text, jsonb, jsonb
) RESET plpgsql.variable_conflict;

DROP FUNCTION geo_transition_workflow_c_alert_rule(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
);
DROP FUNCTION geo_create_workflow_c_alert_rule(
    uuid, uuid, text, integer, text, jsonb, text, text, text, timestamptz
);

DROP TRIGGER workflow_c_alert_rule_receipts_immutable
ON workflow_c_alert_rule_command_receipts;
DROP TRIGGER workflow_c_alert_rule_change_guard
ON workflow_c_alert_rule_versions;
DROP FUNCTION geo_assert_workflow_c_alert_rule_change();
DROP FUNCTION geo_workflow_c_alert_rule_payload_is_valid(jsonb);
DROP TABLE workflow_c_alert_rule_command_receipts;

CREATE OR REPLACE FUNCTION geo_assert_workflow_c_report_snapshot_version_append()
RETURNS trigger
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
    IF NEW.status = 'approved' AND NOT EXISTS (
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
    RETURN NEW;
END;
$$;

ALTER TABLE workflow_c_alert_rule_versions
DROP CONSTRAINT workflow_c_alert_rule_versions_lifecycle_check;
UPDATE workflow_c_alert_rule_versions
SET approved_by = NULL, approved_at = NULL
WHERE status = 'retired';
ALTER TABLE workflow_c_alert_rule_versions
ADD CHECK ((status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL));
ALTER TABLE workflow_c_alert_rule_versions
DROP COLUMN decision_reason,
DROP COLUMN retired_at,
DROP COLUMN retired_by,
DROP COLUMN aggregate_version;

GRANT INSERT ON workflow_c_alert_rule_versions TO geo_app;
