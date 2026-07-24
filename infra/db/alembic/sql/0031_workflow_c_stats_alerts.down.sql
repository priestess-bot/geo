-- Workflow C is append-only operational evidence.  A downgrade is permitted
-- only before the first row is admitted; otherwise it would discard audit,
-- sampling, alert, or crypto-erasure lineage.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_sampling_admission_policies)
       OR EXISTS (SELECT 1 FROM workflow_c_sampling_admission_usage)
       OR EXISTS (SELECT 1 FROM workflow_c_sampling_suites)
       OR EXISTS (SELECT 1 FROM workflow_c_sampling_runs)
       OR EXISTS (SELECT 1 FROM workflow_c_sampling_tasks)
       OR EXISTS (SELECT 1 FROM workflow_c_sampling_attempts)
       OR EXISTS (SELECT 1 FROM workflow_c_sampling_observations)
       OR EXISTS (SELECT 1 FROM workflow_c_sampling_manual_imports)
       OR EXISTS (SELECT 1 FROM workflow_c_command_ledger)
       OR EXISTS (SELECT 1 FROM workflow_c_semantic_metric_snapshots)
       OR EXISTS (SELECT 1 FROM workflow_c_semantic_metric_results)
       OR EXISTS (SELECT 1 FROM workflow_c_metric_judge_batches)
       OR EXISTS (SELECT 1 FROM workflow_c_metric_model_children)
       OR EXISTS (SELECT 1 FROM workflow_c_comparison_families)
       OR EXISTS (SELECT 1 FROM workflow_c_comparison_results)
       OR EXISTS (SELECT 1 FROM workflow_c_drift_reports)
       OR EXISTS (SELECT 1 FROM workflow_c_monitoring_report_snapshots)
       OR EXISTS (SELECT 1 FROM workflow_c_alert_rule_versions)
       OR EXISTS (SELECT 1 FROM workflow_c_alert_schedules)
       OR EXISTS (SELECT 1 FROM workflow_c_alerts)
       OR EXISTS (SELECT 1 FROM workflow_c_alert_dispositions)
       OR EXISTS (SELECT 1 FROM workflow_c_alert_notifications)
       OR EXISTS (SELECT 1 FROM workflow_c_artifact_master_key_versions)
       OR EXISTS (SELECT 1 FROM workflow_c_artifact_deks)
       OR EXISTS (SELECT 1 FROM workflow_c_manual_artifacts)
       OR EXISTS (SELECT 1 FROM workflow_c_artifact_deletion_queue)
       OR EXISTS (SELECT 1 FROM workflow_c_artifact_hold_requests)
       OR EXISTS (SELECT 1 FROM workflow_c_artifact_lifecycle_events) THEN
        RAISE EXCEPTION 'cannot downgrade: Workflow C data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DO $$
DECLARE function_definition text;
DECLARE replacement text;
BEGIN
    function_definition := pg_get_functiondef(
        'geo_worker_record_runtime_heartbeat(text,text,text,text,text)'::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Workflow C heartbeat downgrade contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
    function_definition := pg_get_functiondef(
        'geo_worker_runtime_findings(text,text,integer,integer,integer,integer,integer,integer)'
            ::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Workflow C runtime findings downgrade contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
END;
$$;

ALTER TABLE runtime_service_heartbeats
DROP CONSTRAINT runtime_service_heartbeats_service_type_check;
ALTER TABLE runtime_service_heartbeats
ADD CONSTRAINT runtime_service_heartbeats_service_type_check CHECK (
    service_type IN (
        'task_worker', 'outbox_relay', 'style_browser_worker',
        'synthetic_artifact_maintenance_worker'
    )
);

DROP TRIGGER workflow_c_metric_model_children_change_guard
ON workflow_c_metric_model_children;
DROP TRIGGER workflow_c_artifact_lifecycle_events_immutable
ON workflow_c_artifact_lifecycle_events;
DROP TRIGGER workflow_c_artifact_deletion_queue_change_guard
ON workflow_c_artifact_deletion_queue;
DROP TRIGGER workflow_c_manual_artifact_insert_event
ON workflow_c_manual_artifacts;
DROP TRIGGER workflow_c_manual_artifact_change_guard
ON workflow_c_manual_artifacts;
DROP TRIGGER workflow_c_artifact_dek_change_guard ON workflow_c_artifact_deks;
DROP TRIGGER workflow_c_artifact_key_change_guard
ON workflow_c_artifact_master_key_versions;

DROP FUNCTION geo_decide_workflow_c_artifact_hold(
    uuid, uuid, integer, text, boolean, text, timestamptz
);
DROP FUNCTION geo_request_workflow_c_artifact_hold(
    uuid, uuid, uuid, text, text, text, timestamptz
);
DROP FUNCTION geo_record_workflow_c_artifact_deletion_attempt(
    uuid, uuid, integer, boolean, boolean, text, timestamptz, timestamptz
);
DROP FUNCTION geo_crypto_erase_workflow_c_artifact_deletion(uuid, uuid, integer, timestamptz);
DROP FUNCTION geo_claim_workflow_c_artifact_deletion(uuid, text, timestamptz, integer);
DROP FUNCTION geo_enqueue_workflow_c_artifact_maintenance(uuid, timestamptz, integer);
DROP FUNCTION geo_seed_workflow_c_artifact_maintenance(timestamptz, integer, integer);
DROP FUNCTION geo_schedule_workflow_c_artifact_maintenance(uuid, timestamptz);
DROP FUNCTION geo_claim_workflow_c_artifact_deletion(text, timestamptz, integer);
DROP FUNCTION geo_enqueue_workflow_c_artifact_maintenance(timestamptz, integer);
DROP FUNCTION geo_enqueue_workflow_c_artifact_write_failure(uuid, uuid);
DROP FUNCTION geo_record_workflow_c_artifact_insert_event();
DROP FUNCTION geo_assert_workflow_c_deletion_queue_change();
DROP FUNCTION geo_assert_workflow_c_manual_artifact_change();
DROP FUNCTION geo_assert_workflow_c_artifact_dek_change();
DROP FUNCTION geo_assert_workflow_c_artifact_key_change();
DROP FUNCTION geo_assert_workflow_c_lifecycle_event_immutable();
DROP FUNCTION geo_assert_workflow_c_metric_child_change();
DROP FUNCTION geo_append_workflow_c_artifact_event(
    uuid, uuid, text, text, text, timestamptz
);
DROP FUNCTION geo_assert_workflow_c_versioned_change();
DROP FUNCTION geo_assert_workflow_c_immutable();

ALTER TABLE workflow_c_sampling_manual_imports
DROP CONSTRAINT workflow_c_sampling_manual_imports_artifact_fkey;
ALTER TABLE workflow_c_metric_model_children
DROP CONSTRAINT workflow_c_metric_model_children_master_key_fkey;

DROP TABLE workflow_c_alert_notifications;
DROP TABLE workflow_c_alert_dispositions;
DROP TABLE workflow_c_alerts;
DROP TABLE workflow_c_alert_schedules;
DROP TABLE workflow_c_alert_rule_versions;
DROP TABLE workflow_c_monitoring_report_snapshots;
DROP TABLE workflow_c_comparison_results;
DROP TABLE workflow_c_comparison_families;
DROP TABLE workflow_c_drift_reports;
DROP TABLE workflow_c_metric_model_children;
DROP TABLE workflow_c_metric_judge_batches;
DROP TABLE workflow_c_semantic_metric_results;
DROP TABLE workflow_c_semantic_metric_snapshots;
DROP TABLE workflow_c_command_ledger;
DROP TABLE workflow_c_sampling_manual_imports;
DROP TABLE workflow_c_artifact_lifecycle_events;
DROP TABLE workflow_c_artifact_hold_requests;
DROP TABLE workflow_c_artifact_deletion_queue;
DROP TABLE workflow_c_manual_artifacts;
DROP TABLE workflow_c_artifact_deks;
DROP TABLE workflow_c_artifact_master_key_versions;
DROP TABLE workflow_c_sampling_observations;
DROP TABLE workflow_c_sampling_attempts;
DROP TABLE workflow_c_sampling_tasks;
DROP TABLE workflow_c_sampling_runs;
DROP TABLE workflow_c_sampling_suites;
DROP TABLE workflow_c_sampling_admission_usage;
DROP TABLE workflow_c_sampling_admission_policies;
