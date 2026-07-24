-- Recommendation workflow, Prompt-task, and deletion records are audit
-- lineage.  Never drop the schema after an actual decision or artifact exists.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM service_identities)
       OR EXISTS (SELECT 1 FROM workflow_c_job_specs)
       OR EXISTS (SELECT 1 FROM workflow_c_report_snapshot_versions)
       OR EXISTS (SELECT 1 FROM workflow_c_alert_evaluations)
       OR EXISTS (SELECT 1 FROM workflow_c_admin_inbox_notifications)
       OR EXISTS (
           SELECT 1
           FROM workflow_c_sampling_attempts
           WHERE error_code IS NOT NULL
       )
       OR EXISTS (SELECT 1 FROM recommendation_workflow_versions)
       OR EXISTS (SELECT 1 FROM recommendation_evidence_bindings)
       OR EXISTS (SELECT 1 FROM recommendation_approvals)
       OR EXISTS (SELECT 1 FROM recommendation_reviews)
       OR EXISTS (SELECT 1 FROM recommendation_command_receipts)
       OR EXISTS (SELECT 1 FROM recommendation_drafts)
       OR EXISTS (SELECT 1 FROM recommendation_outbox_messages)
       OR EXISTS (SELECT 1 FROM recommendation_generation_specs)
       OR EXISTS (SELECT 1 FROM recommendation_generation_results)
       OR EXISTS (SELECT 1 FROM recommendation_generation_command_receipts)
       OR EXISTS (SELECT 1 FROM recommendation_model_tasks)
       OR EXISTS (SELECT 1 FROM recommendation_model_call_lineage)
       OR EXISTS (SELECT 1 FROM recommendation_artifact_master_key_versions)
       OR EXISTS (SELECT 1 FROM recommendation_artifact_deletion_intents) THEN
        RAISE EXCEPTION 'cannot downgrade: Recommendation data exists'
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
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'', ''recommendation_artifact_maintenance_worker'', ''recommendation_artifact_maintenance_scheduler'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Recommendation maintenance heartbeat downgrade contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
    function_definition := pg_get_functiondef(
        'geo_worker_runtime_findings(text,text,integer,integer,integer,integer,integer,integer)'
            ::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'', ''recommendation_artifact_maintenance_worker'', ''recommendation_artifact_maintenance_scheduler'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Recommendation maintenance findings downgrade contract changed'
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
        'synthetic_artifact_maintenance_worker',
        'workflow_c_maintenance_worker', 'workflow_c_maintenance_scheduler'
    )
);

ALTER TABLE workflow_c_alert_notifications
DROP CONSTRAINT workflow_c_alert_notifications_channel_check;
UPDATE workflow_c_alert_notifications
SET channel = CASE channel
    WHEN 'local_smtp' THEN 'smtp'
    WHEN 'internal_webhook' THEN 'webhook'
    ELSE channel
END
WHERE channel IN ('local_smtp', 'internal_webhook');
ALTER TABLE workflow_c_alert_notifications
ADD CONSTRAINT workflow_c_alert_notifications_channel_check CHECK (
    channel IN ('admin_inbox', 'smtp', 'webhook')
);
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM workflow_c_alert_notifications
        WHERE last_attempt_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION
            'cannot downgrade: alert attempt provenance exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;
ALTER TABLE workflow_c_alert_notifications
DROP CONSTRAINT workflow_c_alert_notifications_retry_after_attempt_check,
DROP CONSTRAINT workflow_c_alert_notifications_terminal_attempt_check,
DROP CONSTRAINT workflow_c_alert_notifications_pending_attempt_check,
DROP COLUMN last_attempt_at;
REVOKE UPDATE ON workflow_c_alert_notifications FROM geo_worker;

ALTER TABLE workflow_c_alert_rule_versions
DROP CONSTRAINT workflow_c_alert_rule_versions_payload_check;
ALTER TABLE workflow_c_alert_rule_versions
ADD CONSTRAINT workflow_c_alert_rule_versions_payload_check CHECK (
    jsonb_typeof(payload) = 'object'
    AND payload->>'kind' IN (
        'threshold', 'baseline_delta', 'negative_question',
        'completion_freshness', 'model_drift', 'source_drift', 'connector_failure'
    )
);

DROP TRIGGER workflow_c_job_spec_immutable_guard ON workflow_c_job_specs;
DROP TRIGGER workflow_c_report_snapshot_version_append_guard
ON workflow_c_report_snapshot_versions;
DROP TRIGGER workflow_c_alert_evaluation_immutable_guard
ON workflow_c_alert_evaluations;
DROP TRIGGER workflow_c_admin_inbox_notification_immutable_guard
ON workflow_c_admin_inbox_notifications;
DROP TRIGGER recommendation_artifact_deletion_change_guard
ON recommendation_artifact_deletion_intents;
DROP TRIGGER recommendation_artifact_key_change_guard
ON recommendation_artifact_master_key_versions;
DROP TRIGGER recommendation_model_lineage_change_guard
ON recommendation_model_call_lineage;
DROP TRIGGER recommendation_model_task_change_guard ON recommendation_model_tasks;
DROP TRIGGER recommendation_drafts_block_on_stale ON recommendation_workflow_versions;
DROP TRIGGER recommendation_draft_change_guard ON recommendation_drafts;
DROP TRIGGER recommendation_approval_guard ON recommendation_approvals;
DROP TRIGGER recommendation_workflow_append_guard ON recommendation_workflow_versions;

REVOKE ALL ON FUNCTION
    geo_stage_due_synthetic_artifact_expirations(uuid, timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(uuid, text, timestamptz, integer, integer)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_claim_synthetic_artifact_deletions(
    uuid, text, timestamptz, integer, integer
);
DROP FUNCTION geo_stage_due_synthetic_artifact_expirations(uuid, timestamptz, integer);
GRANT EXECUTE ON FUNCTION
    geo_stage_synthetic_artifact_expiry(timestamptz, integer),
    geo_stage_due_synthetic_artifact_expirations(timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(text, integer, integer),
    geo_claim_synthetic_artifact_deletions(text, timestamptz, integer, integer)
TO geo_worker;

DROP FUNCTION geo_retry_recommendation_artifact_deletion(uuid, uuid, integer, text, timestamptz);
DROP FUNCTION geo_mark_recommendation_artifact_deleted(uuid, uuid, integer, text, timestamptz);
DROP FUNCTION geo_mark_recommendation_artifact_crypto_erased(uuid, uuid, integer, text, timestamptz);
DROP FUNCTION geo_claim_recommendation_artifact_deletion(text, timestamptz, integer, integer);
DROP FUNCTION geo_claim_recommendation_artifact_deletion(text, timestamptz, integer);
DROP FUNCTION geo_claim_recommendation_artifact_deletion(
    uuid, text, timestamptz, integer, integer
);
DROP FUNCTION geo_schedule_recommendation_artifact_maintenance(timestamptz);
DROP FUNCTION geo_enqueue_recommendation_artifact_maintenance(uuid, timestamptz);
DROP FUNCTION geo_enqueue_recommendation_artifact_maintenance(timestamptz);
DROP FUNCTION geo_enqueue_recommendation_artifact_deletion(
    uuid, uuid, uuid, text, text, text, text, text, timestamptz, timestamptz
);
DROP FUNCTION geo_resolve_recommendation_evidence(uuid, text, text);
DROP FUNCTION geo_activate_recommendation_model_task(
    uuid, uuid, uuid, bigint, uuid, text, text, text, text, text, bigint, timestamptz
);
DROP FUNCTION geo_reserve_recommendation_model_task(
    uuid, uuid, uuid, bigint, uuid, text, text, uuid, uuid, text,
    uuid, text, uuid, integer, uuid, integer, uuid, integer,
    text, text, text, text, text, text, text,
    text, text, text, text, text, text, text,
    timestamptz, uuid, timestamptz
);
DROP FUNCTION geo_cancel_recommendation_generation(uuid, uuid, integer, text, text, timestamptz);
DROP FUNCTION geo_enqueue_recommendation_generation(
    uuid, uuid, jsonb, text, text, text, timestamptz, uuid, timestamptz, integer
);
DROP FUNCTION geo_assert_recommendation_generation_lease(uuid, uuid, uuid, bigint, timestamptz);
DROP FUNCTION geo_assert_recommendation_artifact_deletion_change();
DROP FUNCTION geo_assert_recommendation_artifact_key_change();
DROP FUNCTION geo_assert_recommendation_model_lineage_change();
DROP FUNCTION geo_assert_recommendation_model_task_change();
DROP FUNCTION geo_block_recommendation_drafts_on_stale();
DROP FUNCTION geo_assert_recommendation_draft_change();
DROP FUNCTION geo_assert_recommendation_approval();
DROP FUNCTION geo_assert_recommendation_workflow_append();
DROP FUNCTION geo_require_active_service_identity(uuid, text);
DROP FUNCTION geo_provision_service_identity(uuid, text, timestamptz);

DROP FUNCTION geo_complete_workflow_c_alert_evaluation(
    uuid, uuid, uuid, integer, uuid, uuid, integer, uuid, text, text, text,
    text, boolean, jsonb, timestamptz, uuid, text, jsonb, jsonb
);
DROP FUNCTION geo_enqueue_workflow_c_alert_evaluation(
    uuid, uuid, uuid, integer, uuid, integer, timestamptz, uuid, text, jsonb,
    text, uuid, text, jsonb, text, timestamptz
);
DROP FUNCTION geo_require_workflow_c_job_lease(uuid, uuid, uuid, integer, text);
DROP FUNCTION geo_fail_workflow_c_metric_child(
    uuid, uuid, uuid, integer, text, text, text
);
DROP FUNCTION geo_complete_workflow_c_metric_child(
    uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text
);
DROP FUNCTION geo_record_workflow_c_sampling_failure(
    uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer, text, boolean, timestamptz
);
DROP FUNCTION geo_commit_workflow_c_manual_sampling(
    uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer,
    uuid, uuid, text, text, text, uuid, uuid, text, text, jsonb, jsonb, text, jsonb, timestamptz
);
DROP FUNCTION geo_commit_workflow_c_provider_sampling(
    uuid, uuid, uuid, integer, text, uuid, uuid, uuid, integer, integer,
    uuid, text, text, jsonb, jsonb, text, jsonb, uuid, text, text, timestamptz
);
DROP FUNCTION geo_validate_workflow_c_sampling_observation_input(
    uuid, text, text, jsonb, jsonb, text, jsonb, timestamptz
);
DROP FUNCTION geo_require_workflow_c_sampling_job_fence(
    uuid, uuid, uuid, integer, text, text, uuid, uuid, uuid, integer, integer
);
DROP FUNCTION geo_assert_workflow_c_alert_evaluation_immutable();
DROP FUNCTION geo_assert_workflow_c_admin_inbox_notification_immutable();
DROP FUNCTION geo_assert_workflow_c_report_snapshot_version_append();

DROP TABLE recommendation_artifact_deletion_intents;
DROP TABLE recommendation_artifact_master_key_versions;
DROP TABLE recommendation_model_call_lineage;
DROP TABLE recommendation_model_tasks;
DROP TABLE recommendation_generation_results;
DROP TABLE recommendation_generation_command_receipts;
DROP TABLE recommendation_generation_specs;
DROP TABLE recommendation_outbox_messages;
DROP TABLE recommendation_drafts;
DROP TABLE recommendation_command_receipts;
DROP TABLE recommendation_reviews;
DROP TABLE recommendation_approvals;
DROP TABLE recommendation_evidence_bindings;
DROP TABLE recommendation_workflow_versions;
DROP TABLE workflow_c_admin_inbox_notifications;
DROP TABLE workflow_c_alert_evaluations;
DROP TABLE workflow_c_report_snapshot_versions;
ALTER TABLE workflow_c_sampling_attempts DROP COLUMN error_code;
DROP TABLE workflow_c_job_specs;
DROP FUNCTION geo_workflow_c_sampling_job_spec_is_valid(text, jsonb);
DROP FUNCTION geo_workflow_c_json_is_rfc3339(jsonb);
DROP FUNCTION geo_workflow_c_json_is_positive_integer(jsonb);
DROP FUNCTION geo_workflow_c_json_is_sha256(jsonb);
DROP FUNCTION geo_workflow_c_json_is_uuid(jsonb);
DROP FUNCTION geo_workflow_c_json_has_exact_keys(jsonb, text[]);
DROP FUNCTION geo_assert_workflow_c_job_spec_immutable();
DROP FUNCTION geo_workflow_c_job_spec_payload_is_safe(jsonb);
DROP TABLE service_identities;
