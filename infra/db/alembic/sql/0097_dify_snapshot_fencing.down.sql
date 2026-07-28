DO $$
BEGIN
    IF EXISTS (
            SELECT 1 FROM dify_workflow_release_snapshot_pins
            WHERE pin_source <> 'migration_backfill'
       )
       OR EXISTS (SELECT 1 FROM dify_workflow_attempt_reconciliations)
       OR EXISTS (
            SELECT 1 FROM dify_workflow_execution_attempts
            WHERE error_classification = 'unknown_outcome'
       ) THEN
        RAISE EXCEPTION 'cannot downgrade while Dify snapshot pins or unresolved outcome evidence exists';
    END IF;
END;
$$;

DROP TRIGGER dify_workflow_binding_snapshot_pin_guard ON dify_workflow_bindings;
DROP FUNCTION geo_require_dify_release_snapshot_pin_for_binding();

-- Restore the 0096 guard before removing the snapshot-pin relation referenced
-- by the 0097 body.
CREATE OR REPLACE FUNCTION geo_assert_recommendation_model_task_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Recommendation model task lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF (NEW.role = 'primary' AND NEW.prompt_purpose <> 'recommendations.recommendation')
           OR (NEW.role = 'arbiter' AND NEW.prompt_purpose <> 'synthetic_lab.arbiter')
           OR NEW.runtime_selection_id <> NEW.runtime_option_id
           OR NEW.task_artifact_expires_at <= NEW.created_at
           OR NEW.task_artifact_status <> 'uploading'
           OR (NEW.role = 'arbiter' AND NEW.execution_backend <> 'model_gateway')
           OR (NEW.execution_backend = 'dify' AND NOT EXISTS (
                SELECT 1 FROM dify_workflow_releases release
                WHERE release.id = NEW.workflow_release_id
                  AND release.project_id = NEW.project_id
                  AND release.release_hash = NEW.workflow_release_hash
                  AND release.purpose = NEW.prompt_purpose
                  AND release.prompt_release_id = NEW.prompt_release_id
                  AND release.prompt_release_hash = NEW.prompt_release_hash
                  AND release.configured_model = NEW.configured_model
           )) THEN
            RAISE EXCEPTION 'Recommendation model task frozen lineage is invalid'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'task_artifact_uri', 'task_artifact_manifest_hash',
        'task_artifact_payload_uri', 'task_artifact_content_hash',
        'task_artifact_byte_size', 'task_artifact_status', 'task_payload_hash'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'task_artifact_uri', 'task_artifact_manifest_hash',
        'task_artifact_payload_uri', 'task_artifact_content_hash',
        'task_artifact_byte_size', 'task_artifact_status', 'task_payload_hash'
    ];
    IF old_fixed <> new_fixed THEN
        RAISE EXCEPTION 'Recommendation model task frozen lineage is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.task_artifact_status = 'uploading' AND NEW.task_artifact_status = 'active'
       OR OLD.task_artifact_status = 'active' AND NEW.task_artifact_status = 'deletion_pending'
       OR OLD.task_artifact_status = 'deletion_pending' AND NEW.task_artifact_status = 'crypto_erased'
       OR OLD.task_artifact_status = 'crypto_erased' AND NEW.task_artifact_status = 'deleted' THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Recommendation model task artifact lifecycle transition is invalid'
        USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER dify_legacy_recommendation_native_parents_immutable
ON dify_legacy_recommendation_native_parents;
DROP TABLE dify_legacy_recommendation_native_parents;

DROP FUNCTION geo_bind_dify_resubmission(uuid, uuid, uuid, uuid, text);
DROP FUNCTION geo_dify_recovery_parent_fingerprint(uuid, uuid);
DROP FUNCTION geo_issue_dify_resubmission_token(
    uuid, uuid, uuid, text, text, text, text
);
DROP TRIGGER dify_workflow_reconciliation_consumptions_immutable
ON dify_workflow_reconciliation_consumptions;
DROP TABLE dify_workflow_reconciliation_consumptions;
DROP TRIGGER dify_workflow_attempt_reconciliations_immutable
ON dify_workflow_attempt_reconciliations;
DROP FUNCTION geo_reject_dify_attempt_reconciliation_change();
DROP TABLE dify_workflow_attempt_reconciliations;

DROP FUNCTION geo_finish_dify_business_attempt(
    uuid, uuid, uuid, bigint, uuid, jsonb
);
DROP FUNCTION geo_finish_dify_canary_attempt(uuid, uuid, jsonb);
DROP FUNCTION geo_dify_canonical_text(jsonb);

DROP TRIGGER dify_workflow_release_snapshot_pins_immutable
ON dify_workflow_release_snapshot_pins;
DROP TRIGGER dify_workflow_release_snapshot_pin_guard
ON dify_workflow_release_snapshot_pins;
DROP FUNCTION geo_assert_dify_release_snapshot_pin();
DROP TABLE dify_workflow_release_snapshot_pins;

GRANT UPDATE ON dify_workflow_execution_attempts TO geo_worker;
GRANT INSERT ON dify_workflow_execution_results TO geo_worker;

ALTER TABLE dify_workflow_execution_attempts
DROP CONSTRAINT dify_workflow_execution_attempts_error_classification_check;
ALTER TABLE dify_workflow_execution_attempts
ADD CONSTRAINT dify_workflow_execution_attempts_error_classification_check CHECK (
    error_classification IS NULL OR error_classification IN (
        'retryable', 'authentication', 'configuration', 'contract',
        'provider', 'cancelled'
    )
);
