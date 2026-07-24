DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM runtime_service_heartbeats WHERE service_type = 'style_browser_worker')
       OR EXISTS (SELECT 1 FROM synthetic_lab_terminal_results)
       OR EXISTS (SELECT 1 FROM synthetic_lab_execution_results)
       OR EXISTS (SELECT 1 FROM synthetic_lab_execution_tasks)
       OR EXISTS (SELECT 1 FROM synthetic_lab_style_collection_results)
       OR EXISTS (SELECT 1 FROM synthetic_lab_artifact_tombstones)
       OR EXISTS (SELECT 1 FROM synthetic_lab_artifact_crypto_erasures)
       OR EXISTS (SELECT 1 FROM synthetic_lab_artifact_deletion_outbox)
       OR EXISTS (SELECT 1 FROM synthetic_lab_artifact_legal_holds)
       OR EXISTS (SELECT 1 FROM synthetic_lab_artifact_deks)
       OR EXISTS (SELECT 1 FROM synthetic_lab_raw_artifacts)
       OR EXISTS (SELECT 1 FROM synthetic_lab_manual_import_cleanup_receipts)
       OR EXISTS (SELECT 1 FROM synthetic_lab_manual_import_cleanup_outbox)
       OR EXISTS (SELECT 1 FROM synthetic_lab_imported_sample_artifacts)
       OR EXISTS (SELECT 1 FROM synthetic_lab_manual_import_preview_states)
       OR EXISTS (SELECT 1 FROM synthetic_lab_manual_import_previews)
       OR EXISTS (SELECT 1 FROM synthetic_lab_artifact_master_key_versions)
       OR EXISTS (SELECT 1 FROM synthetic_lab_style_collection_tasks)
       OR EXISTS (SELECT 1 FROM synthetic_lab_model_call_children)
       OR EXISTS (SELECT 1 FROM synthetic_lab_outbox_messages)
       OR EXISTS (SELECT 1 FROM synthetic_lab_job_metadata)
       OR EXISTS (SELECT 1 FROM synthetic_lab_artifact_governance_decisions)
       OR EXISTS (SELECT 1 FROM synthetic_lab_imported_samples)
       OR EXISTS (SELECT 1 FROM synthetic_lab_manual_import_row_errors)
       OR EXISTS (SELECT 1 FROM synthetic_lab_manual_import_manifests)
       OR EXISTS (SELECT 1 FROM synthetic_lab_authorization_versions)
       OR EXISTS (SELECT 1 FROM synthetic_lab_aggregate_versions)
       OR EXISTS (SELECT 1 FROM synthetic_lab_command_receipts) THEN
        RAISE EXCEPTION 'cannot downgrade: Synthetic Lab data exists (including runtime evidence)'
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
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Synthetic artifact maintenance heartbeat downgrade contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
    function_definition := pg_get_functiondef(
        'geo_worker_runtime_findings(text,text,integer,integer,integer,integer,integer,integer)'
            ::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Synthetic artifact maintenance findings downgrade contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
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
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'runtime heartbeat downgrade contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;

    function_definition := pg_get_functiondef(
        'geo_worker_runtime_findings(text,text,integer,integer,integer,integer,integer,integer)'
            ::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'runtime findings downgrade contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
END;
$$;

ALTER TABLE runtime_service_heartbeats
DROP CONSTRAINT runtime_service_heartbeats_service_type_check;
ALTER TABLE runtime_service_heartbeats
ADD CONSTRAINT runtime_service_heartbeats_service_type_check CHECK (
    service_type IN ('task_worker', 'outbox_relay')
);

DROP TRIGGER synthetic_lab_model_call_child_guard
ON synthetic_lab_model_call_children;
DROP TRIGGER synthetic_model_call_child_job_change_guard ON durable_jobs;
DROP TRIGGER synthetic_parent_job_change_propagation ON durable_jobs;
DROP TRIGGER synthetic_model_call_child_terminal_wakeup ON durable_jobs;
DROP VIEW synthetic_lab_manual_import_preview_current;
DROP VIEW synthetic_lab_model_call_child_status;
DROP FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
);
DROP FUNCTION geo_propagate_synthetic_parent_job_change();
DROP FUNCTION geo_wake_synthetic_parent_after_child_terminal();
DROP FUNCTION geo_assert_synthetic_model_call_child_job_change();
DROP FUNCTION geo_block_synthetic_unstarted_model_call_children(uuid, uuid, text);
DROP FUNCTION geo_assert_synthetic_model_call_child();
DROP TABLE synthetic_lab_model_call_children;

ALTER TABLE synthetic_lab_raw_artifacts
DROP CONSTRAINT synthetic_lab_raw_artifacts_winner_fkey;
ALTER TABLE synthetic_lab_raw_artifacts
DROP CONSTRAINT synthetic_lab_raw_artifacts_dek_fkey;

DROP TABLE synthetic_lab_artifact_tombstones;
DROP TABLE synthetic_lab_artifact_crypto_erasures;
DROP TABLE synthetic_lab_artifact_deletion_outbox;
DROP TABLE synthetic_lab_artifact_legal_holds;
DROP TABLE synthetic_lab_artifact_deks;
DROP TABLE synthetic_lab_raw_artifacts;
DROP TABLE synthetic_lab_manual_import_cleanup_receipts;
DROP TABLE synthetic_lab_manual_import_cleanup_outbox;
DROP TABLE synthetic_lab_imported_sample_artifacts;
DROP TABLE synthetic_lab_manual_import_preview_states;
DROP TABLE synthetic_lab_imported_samples;
DROP TABLE synthetic_lab_manual_import_row_errors;
DROP TABLE synthetic_lab_manual_import_manifests;
DROP TABLE synthetic_lab_manual_import_previews;
DROP TABLE synthetic_lab_artifact_master_key_versions;
DROP TABLE synthetic_lab_style_collection_results;
DROP TABLE synthetic_lab_style_collection_tasks;
DROP TABLE synthetic_lab_terminal_results;
DROP TABLE synthetic_lab_execution_results;
DROP TABLE synthetic_lab_execution_tasks;
DROP TABLE synthetic_lab_outbox_messages;
DROP TABLE synthetic_lab_job_metadata;
DROP TABLE synthetic_lab_artifact_governance_decisions;
DROP TABLE synthetic_lab_authorization_versions;
DROP TABLE synthetic_lab_aggregate_versions;
DROP TABLE synthetic_lab_command_receipts;

DROP FUNCTION geo_fail_synthetic_artifact_deletion(
    uuid, uuid, bigint, uuid, text, timestamptz
);
DROP FUNCTION geo_enqueue_synthetic_artifact_maintenance(timestamptz);
DROP FUNCTION geo_fail_synthetic_artifact_object_deletion(
    uuid, uuid, uuid, bigint, uuid, text, timestamptz
);
DROP FUNCTION geo_complete_synthetic_artifact_object_deletion(
    uuid, uuid, uuid, bigint, uuid, text, timestamptz
);
DROP FUNCTION geo_crypto_erase_and_tombstone_synthetic_artifact(
    uuid, uuid, uuid, bigint, uuid, text, timestamptz
);
DROP FUNCTION geo_claim_synthetic_artifact_deletions(text, timestamptz, integer, integer);
DROP FUNCTION geo_stage_due_synthetic_artifact_expirations(timestamptz, integer);
DROP FUNCTION geo_complete_synthetic_artifact_deletion(
    uuid, uuid, bigint, uuid, text, timestamptz
);
DROP FUNCTION geo_claim_synthetic_artifact_deletions(text, integer, integer);
DROP FUNCTION geo_stage_synthetic_artifact_expiry(timestamptz, integer);
DROP FUNCTION geo_mark_synthetic_artifact_attempt_orphaned(uuid, uuid, bigint, text);
DROP FUNCTION geo_assert_synthetic_style_collection_result_consistency();
DROP FUNCTION geo_assert_synthetic_style_collection_result();
DROP FUNCTION geo_assert_synthetic_artifact_outbox_change();
DROP FUNCTION geo_assert_synthetic_artifact_dek_change();
DROP FUNCTION geo_assert_synthetic_raw_artifact_change();
DROP FUNCTION geo_assert_synthetic_artifact_dek_consistency();
DROP FUNCTION geo_assert_synthetic_artifact_dek_insert();
DROP FUNCTION geo_assert_synthetic_raw_artifact_insert();
DROP FUNCTION geo_assert_synthetic_style_collection_task();
DROP FUNCTION geo_retire_synthetic_artifact_master_key_version(text, timestamptz);
DROP FUNCTION geo_sync_synthetic_artifact_master_key_version(
    text, text, text, bytea, bytea, timestamptz
);
DROP FUNCTION geo_assert_synthetic_artifact_master_key_change();
DROP FUNCTION geo_synthetic_secret_handle_hash(uuid, uuid, text, integer);
DROP FUNCTION geo_assert_synthetic_lab_terminal_consistency();
DROP FUNCTION geo_assert_synthetic_lab_terminal();
DROP FUNCTION geo_assert_synthetic_lab_execution_result_consistency();
DROP FUNCTION geo_assert_synthetic_lab_execution_result();
DROP FUNCTION geo_assert_synthetic_lab_execution_task();
DROP FUNCTION geo_assert_synthetic_lab_outbox();
DROP FUNCTION geo_assert_synthetic_lab_job_metadata();
DROP FUNCTION geo_assert_synthetic_lab_import_manifest();
DROP FUNCTION geo_assert_synthetic_lab_imported_sample();
DROP FUNCTION geo_fail_synthetic_manual_import_cleanup(
    uuid, uuid, bigint, uuid, text, timestamptz
);
DROP FUNCTION geo_complete_synthetic_manual_import_cleanup(
    uuid, uuid, bigint, uuid, uuid, text, timestamptz
);
DROP FUNCTION geo_claim_synthetic_manual_import_cleanups(text, integer, integer);
DROP FUNCTION geo_assert_synthetic_manual_import_cleanup_receipt();
DROP FUNCTION geo_assert_synthetic_manual_import_cleanup_outbox_change();
DROP FUNCTION geo_assert_synthetic_manual_import_terminal_consistency();
DROP FUNCTION geo_finalize_synthetic_manual_import_preview(
    uuid, uuid, integer, uuid, text, timestamptz, integer[], boolean,
    boolean, uuid, text, text, text
);
DROP FUNCTION geo_create_synthetic_manual_import_preview(
    uuid, uuid, uuid, integer, text, text, text, text, text, text,
    uuid, timestamptz, timestamptz, uuid, text, text, text, text,
    text, text, bigint, text, text, text, text, integer, integer,
    integer, text
);
DROP FUNCTION geo_assert_synthetic_manual_import_preview_state();
DROP FUNCTION geo_assert_synthetic_manual_import_preview_change();
DROP FUNCTION geo_assert_synthetic_lab_authorization_append();
DROP FUNCTION geo_assert_synthetic_lab_aggregate_append();
