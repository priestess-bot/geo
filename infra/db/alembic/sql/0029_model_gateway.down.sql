DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM model_gateway_artifact_tombstones)
       OR EXISTS (SELECT 1 FROM model_gateway_artifact_deletion_outbox)
       OR EXISTS (SELECT 1 FROM model_gateway_artifacts)
       OR EXISTS (SELECT 1 FROM model_gateway_artifact_deks)
       OR EXISTS (SELECT 1 FROM model_gateway_artifact_master_key_versions)
       OR EXISTS (SELECT 1 FROM model_gateway_artifact_bundles)
       OR EXISTS (SELECT 1 FROM model_gateway_artifact_recovery_receipts)
       OR EXISTS (SELECT 1 FROM model_gateway_reconciliation_commands)
       OR EXISTS (SELECT 1 FROM model_gateway_terminal_events)
       OR EXISTS (SELECT 1 FROM model_gateway_call_attempts)
       OR EXISTS (SELECT 1 FROM model_gateway_job_admissions)
       OR EXISTS (SELECT 1 FROM model_gateway_runtime_options)
       OR EXISTS (SELECT 1 FROM model_gateway_runtime_manifests)
       OR EXISTS (SELECT 1 FROM model_gateway_project_policy_versions)
       OR EXISTS (SELECT 1 FROM model_gateway_model_releases)
       OR EXISTS (SELECT 1 FROM model_gateway_adapter_releases) THEN
        RAISE EXCEPTION 'cannot downgrade: Model Gateway data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER model_gateway_artifact_tombstones_immutable
ON model_gateway_artifact_tombstones;
DROP TABLE model_gateway_artifact_tombstones;
DROP TRIGGER model_gateway_artifact_deletion_outbox_change_guard
ON model_gateway_artifact_deletion_outbox;
DROP TABLE model_gateway_artifact_deletion_outbox;
DROP TRIGGER model_gateway_artifacts_update_guard ON model_gateway_artifacts;
DROP TRIGGER model_gateway_artifacts_insert_guard ON model_gateway_artifacts;
DROP TABLE model_gateway_artifacts;
DROP TRIGGER model_gateway_artifact_deks_change_guard ON model_gateway_artifact_deks;
DROP TABLE model_gateway_artifact_deks;
DROP TRIGGER model_gateway_artifact_master_key_change_guard
ON model_gateway_artifact_master_key_versions;
DROP TABLE model_gateway_artifact_master_key_versions;
DROP TRIGGER model_gateway_artifact_bundles_change_guard
ON model_gateway_artifact_bundles;
DROP TRIGGER model_gateway_artifact_bundles_insert_guard
ON model_gateway_artifact_bundles;
DROP TABLE model_gateway_artifact_bundles;

DROP TRIGGER model_gateway_artifact_recovery_receipts_consistency_guard
ON model_gateway_artifact_recovery_receipts;
DROP TRIGGER model_gateway_artifact_recovery_receipts_immutable
ON model_gateway_artifact_recovery_receipts;
DROP TRIGGER model_gateway_artifact_recovery_receipts_insert_guard
ON model_gateway_artifact_recovery_receipts;
DROP TABLE model_gateway_artifact_recovery_receipts;

DROP TRIGGER model_gateway_reconciliation_commands_immutable
ON model_gateway_reconciliation_commands;
DROP TRIGGER model_gateway_reconciliation_commands_insert_guard
ON model_gateway_reconciliation_commands;
DROP TABLE model_gateway_reconciliation_commands;

DROP TRIGGER model_gateway_terminal_events_consistency_guard
ON model_gateway_terminal_events;
DROP TRIGGER model_gateway_terminal_events_immutable
ON model_gateway_terminal_events;
DROP TRIGGER model_gateway_terminal_events_insert_guard
ON model_gateway_terminal_events;
DROP TABLE model_gateway_terminal_events;

DROP TRIGGER model_gateway_call_attempts_consistency_guard
ON model_gateway_call_attempts;
DROP TRIGGER model_gateway_call_attempts_immutable
ON model_gateway_call_attempts;
DROP TRIGGER model_gateway_call_attempts_insert_guard
ON model_gateway_call_attempts;
DROP TABLE model_gateway_call_attempts;

DROP TRIGGER model_gateway_job_admissions_consistency_guard
ON model_gateway_job_admissions;
DROP TRIGGER model_gateway_job_admissions_budget_guard
ON model_gateway_job_admissions;
DROP TRIGGER model_gateway_job_admissions_insert_guard
ON model_gateway_job_admissions;
DROP TABLE model_gateway_job_admissions;

DROP TRIGGER model_gateway_runtime_options_consistency_guard
ON model_gateway_runtime_options;
DROP TRIGGER model_gateway_runtime_options_immutable
ON model_gateway_runtime_options;
DROP TRIGGER model_gateway_runtime_options_insert_guard
ON model_gateway_runtime_options;
DROP TABLE model_gateway_runtime_options;

DROP TRIGGER model_gateway_runtime_manifests_consistency_guard
ON model_gateway_runtime_manifests;
DROP TRIGGER model_gateway_runtime_manifests_change_guard
ON model_gateway_runtime_manifests;
DROP TABLE model_gateway_runtime_manifests;

DROP TRIGGER model_gateway_project_policy_versions_immutable
ON model_gateway_project_policy_versions;
DROP TRIGGER model_gateway_project_policy_versions_append_guard
ON model_gateway_project_policy_versions;
DROP TABLE model_gateway_project_policy_versions;

DROP TRIGGER model_gateway_model_releases_immutable
ON model_gateway_model_releases;
DROP TRIGGER model_gateway_model_releases_insert_guard
ON model_gateway_model_releases;
DROP TABLE model_gateway_model_releases;

DROP TRIGGER model_gateway_adapter_releases_immutable
ON model_gateway_adapter_releases;
DROP TRIGGER model_gateway_adapter_releases_insert_guard
ON model_gateway_adapter_releases;
DROP TABLE model_gateway_adapter_releases;

DROP FUNCTION geo_assert_model_gateway_budget_consistency();
DROP FUNCTION geo_retire_model_gateway_artifact_master_key_version(integer, timestamptz);
DROP FUNCTION geo_sync_model_gateway_artifact_master_key_version(
    integer, text, text, bytea, bytea, timestamptz
);
DROP FUNCTION geo_assert_model_gateway_artifact_master_key_change();
DROP FUNCTION geo_assert_model_gateway_artifact_recovery_consistency();
DROP FUNCTION geo_assert_model_gateway_artifact_recovery_receipt();
DROP FUNCTION geo_assert_model_gateway_reconciliation_command();
DROP FUNCTION geo_fail_model_gateway_artifact_deletion(uuid, uuid, uuid, bigint, text, integer);
DROP FUNCTION geo_complete_model_gateway_artifact_deletion(uuid, uuid, uuid, bigint, text);
DROP FUNCTION geo_claim_model_gateway_artifact_deletions(integer, integer);
DROP FUNCTION geo_stage_model_gateway_artifact_expiry(timestamptz, integer);
DROP FUNCTION geo_destroy_model_gateway_unstaged_artifact_deks(timestamptz, integer);
DROP FUNCTION geo_assert_model_gateway_artifact_tombstone_immutable();
DROP FUNCTION geo_assert_model_gateway_artifact_outbox_change();
DROP FUNCTION geo_assert_model_gateway_artifact_immutable();
DROP FUNCTION geo_assert_model_gateway_artifact_insert();
DROP FUNCTION geo_assert_model_gateway_artifact_dek_change();
DROP FUNCTION geo_assert_model_gateway_artifact_bundle_change();
DROP FUNCTION geo_assert_model_gateway_artifact_bundle_insert();
DROP FUNCTION geo_assert_model_gateway_terminal_immutable();
DROP FUNCTION geo_assert_model_gateway_terminal_insert();
DROP FUNCTION geo_assert_model_gateway_attempt_immutable();
DROP FUNCTION geo_assert_model_gateway_attempt_insert();
DROP FUNCTION geo_refresh_model_gateway_job_admission_lease(
    uuid, uuid, integer, uuid, bigint, timestamptz
);
DROP FUNCTION geo_assert_model_gateway_job_budget_change();
DROP FUNCTION geo_assert_model_gateway_job_admission_insert();
DROP FUNCTION geo_resolve_model_gateway_runtime_option(uuid, uuid, text, text);
DROP FUNCTION geo_retire_model_gateway_runtime_manifest(uuid, uuid, uuid, timestamptz);
DROP FUNCTION geo_add_model_gateway_runtime_option(
    uuid, uuid, uuid, text, text, text, text, text, uuid,
    text, text, text, text, text, text, text[], jsonb, text, timestamptz
);
DROP FUNCTION geo_register_model_gateway_runtime_manifest(
    uuid, uuid, text, integer, uuid, text, text, integer,
    uuid, timestamptz, uuid, timestamptz, text, text
);
DROP FUNCTION geo_assert_model_gateway_runtime_manifest_consistency();
DROP FUNCTION geo_assert_model_gateway_runtime_option();
DROP FUNCTION geo_assert_model_gateway_runtime_manifest_change();
DROP FUNCTION geo_assert_model_gateway_policy_append();
DROP FUNCTION geo_assert_model_gateway_model_release();
DROP FUNCTION geo_assert_model_gateway_adapter_release();
DROP FUNCTION geo_model_gateway_secret_handle_hash(uuid, uuid, text, integer);
DROP FUNCTION geo_assert_model_gateway_text_array(text[], text);
