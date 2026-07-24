DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM secret_audit_events)
       OR EXISTS (SELECT 1 FROM secret_command_receipts)
       OR EXISTS (SELECT 1 FROM secret_versions)
       OR EXISTS (SELECT 1 FROM secret_references)
       OR EXISTS (SELECT 1 FROM secret_master_key_versions) THEN
        RAISE EXCEPTION 'cannot downgrade: Secret Store data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER secret_audit_events_immutable ON secret_audit_events;
DROP TRIGGER secret_audit_events_lineage_guard ON secret_audit_events;
DROP TABLE secret_audit_events;
DROP TRIGGER secret_command_receipts_immutable ON secret_command_receipts;
DROP TRIGGER secret_command_receipts_outcome_guard ON secret_command_receipts;
DROP TABLE secret_command_receipts;
ALTER TABLE secret_references DROP CONSTRAINT secret_references_current_fkey;
DROP TRIGGER secret_versions_current_guard ON secret_versions;
DROP TRIGGER secret_versions_rewrap_audit_guard ON secret_versions;
DROP TRIGGER secret_versions_change_guard ON secret_versions;
DROP TRIGGER secret_versions_insert_guard ON secret_versions;
DROP TABLE secret_versions;
DROP TRIGGER secret_references_current_guard ON secret_references;
DROP TRIGGER secret_references_change_guard ON secret_references;
DROP TABLE secret_references;
DROP TRIGGER secret_master_key_versions_change_guard ON secret_master_key_versions;
DROP TABLE secret_master_key_versions;
DROP FUNCTION geo_assert_secret_audit_lineage();
DROP FUNCTION geo_assert_secret_command_outcome();
DROP FUNCTION geo_assert_secret_current_version();
DROP FUNCTION geo_assert_secret_version_change();
DROP FUNCTION geo_assert_secret_rewrap_audit();
DROP FUNCTION geo_assert_secret_version_insert();
DROP FUNCTION geo_assert_secret_reference_change();
DROP FUNCTION geo_assert_secret_master_key_change();
DROP FUNCTION geo_retire_secret_master_key_version(integer, timestamptz);
DROP FUNCTION geo_sync_secret_master_key_version(
    integer, text, text, bytea, bytea, timestamptz
);
