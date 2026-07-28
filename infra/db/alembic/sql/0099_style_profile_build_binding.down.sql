DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM synthetic_lab_style_profile_build_bindings
        WHERE binding_source = 'runtime_review'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade while post-migration Style Profile reviews exist'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

ALTER TABLE synthetic_lab_command_receipts
DROP CONSTRAINT synthetic_lab_command_receipts_operation_check;
ALTER TABLE synthetic_lab_command_receipts
ADD CONSTRAINT synthetic_lab_command_receipts_operation_check
CHECK (operation IN (
    'create_authorization', 'reassess_authorization', 'decide_authorization',
    'expire_authorization',
    'revoke_authorization', 'admit_collection', 'claim_collection',
    'create_style_source', 'create_style_profile',
    'create_review_suite', 'create_review_case',
    'import_samples', 'freeze_profile', 'freeze_suite', 'enqueue_generation',
    'enqueue_revision', 'enqueue_corpus', 'enqueue_experiment', 'claim_job',
    'enqueue_execution', 'cancel_job', 'finalize_result', 'finalize_experiment'
));

DROP VIEW synthetic_lab_model_call_child_status;
CREATE VIEW synthetic_lab_model_call_child_status
WITH (security_barrier = true, security_invoker = true) AS
SELECT child.project_id, child.child_job_id, child.parent_job_id,
       child.parent_job_kind, child.parent_task_input_hash, child.step_key,
       child.step_key_hash, child.model_job_version, child.prompt_binding_id,
       child.prompt_binding_version, child.prompt_frozen_state_id,
       child.prompt_state_version, child.prompt_release_id,
       child.prompt_release_version, child.prompt_release_hash,
       child.prompt_program_kind, child.prompt_purpose, child.admitted_by,
       child.prompt_bundle_hash, child.structured_input_hash,
       child.portable_output_schema_hash, child.application_output_schema_hash,
       child.runtime_manifest_id, child.runtime_manifest_hash,
       child.runtime_option_id, child.runtime_option_hash,
       child.configured_model AS frozen_configured_model,
       child.execution_backend, child.backend_lineage_source,
       child.workflow_release_id,
       child.workflow_release_hash, child.task_artifact_uri,
       child.task_artifact_hash, child.child_input_hash,
       durable.status AS durable_status,
       CASE WHEN durable.status = 'succeeded' THEN 'succeeded'
            WHEN durable.status = 'cancelled' THEN 'cancelled'
            WHEN durable.error_code IN ('model_unknown_outcome', 'dify_unknown_outcome')
                THEN 'unknown_outcome'
            WHEN durable.status IN ('failed', 'dead_lettered') THEN 'failed'
            WHEN durable.status IN ('running', 'finalizing') THEN 'running'
            ELSE 'queued' END AS status,
       durable.attempt_count AS durable_attempt_count,
       durable.fencing_generation AS durable_fencing_generation,
       durable.cancel_requested_at,
       coalesce(
           durable.error_code,
           CASE WHEN child.execution_backend = 'dify'
                THEN dify.error_code ELSE native.error_code END
       ) AS failure_code,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.attempt_id END AS model_attempt_id,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.attempt_number END AS model_attempt_number,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.terminal_status END AS model_terminal_status,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.gateway_call_log_id END AS gateway_call_log_id,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_id END AS workflow_attempt_id,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_number END AS workflow_attempt_number,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_status END AS workflow_attempt_status,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.output_hash ELSE native.output_hash END AS output_hash,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.response_hash ELSE native.response_hash END AS response_hash,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.configured_model ELSE native.configured_model
            END AS model_configured_model,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.provider_reported_model ELSE native.provider_reported_model
            END AS model_reported_model,
       CASE WHEN child.execution_backend = 'dify' THEN dify.output END AS dify_output,
       CASE WHEN child.execution_backend = 'dify' THEN dify.release_id END
            AS dify_release_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.release_hash END
            AS dify_release_hash,
       CASE WHEN child.execution_backend = 'dify' THEN dify.prompt_release_id END
            AS dify_prompt_release_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.prompt_release_hash END
            AS dify_prompt_release_hash,
       CASE WHEN child.execution_backend = 'dify' THEN dify.purpose END
            AS dify_purpose,
       CASE WHEN child.execution_backend = 'dify' THEN dify.published_snapshot_id END
            AS published_snapshot_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.snapshot_hash END
            AS published_snapshot_hash,
       child.created_at
FROM synthetic_lab_model_call_children child
JOIN durable_jobs durable
  ON durable.id = child.child_job_id AND durable.project_id = child.project_id
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id, attempt.attempt_number,
           terminal.status AS terminal_status, terminal.error_code,
           terminal.gateway_call_log_id, terminal.output_hash,
           terminal.response_hash, terminal.configured_model,
           terminal.provider_reported_model
    FROM model_gateway_call_attempts attempt
    LEFT JOIN model_gateway_terminal_events terminal
      ON terminal.attempt_id = attempt.id AND terminal.project_id = attempt.project_id
     AND terminal.job_id = attempt.job_id
    WHERE child.execution_backend = 'model_gateway'
      AND attempt.project_id = child.project_id
      AND attempt.job_id = child.child_job_id
    ORDER BY attempt.attempt_number DESC LIMIT 1
) native ON true
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id, attempt.attempt_number,
           attempt.status AS attempt_status, attempt.error_code,
           result.output, result.response_hash AS output_hash,
           result.response_hash, result.configured_model,
           result.provider_reported_model, release.id AS release_id,
           release.release_hash, release.prompt_release_id,
           release.prompt_release_hash, release.purpose,
           attempt.published_snapshot_id, snapshot.snapshot_hash
    FROM dify_workflow_execution_attempts attempt
    JOIN dify_workflow_releases release
      ON release.id = attempt.release_id AND release.project_id = attempt.project_id
     AND release.release_hash = child.workflow_release_hash
    LEFT JOIN dify_workflow_execution_results result
      ON result.attempt_id = attempt.id AND result.project_id = attempt.project_id
     AND result.job_id = attempt.job_id
    LEFT JOIN dify_workflow_published_snapshots snapshot
      ON snapshot.id = attempt.published_snapshot_id
     AND snapshot.project_id = attempt.project_id
     AND snapshot.release_id = attempt.release_id
    WHERE child.execution_backend = 'dify'
      AND attempt.project_id = child.project_id
      AND attempt.job_id = child.child_job_id
      AND attempt.release_id = child.workflow_release_id
    ORDER BY attempt.attempt_number DESC LIMIT 1
) dify ON true;
REVOKE ALL ON synthetic_lab_model_call_child_status
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON synthetic_lab_model_call_child_status TO geo_app, geo_worker;
COMMENT ON VIEW synthetic_lab_model_call_child_status IS
    'Admin/worker status projection over the frozen native or exact pinned Dify child backend; lineage source distinguishes historical backfill from runtime admission and backend-specific IDs are never aliased.';

DROP TRIGGER style_profile_build_binding_immutable
ON synthetic_lab_style_profile_build_bindings;
DROP FUNCTION geo_reject_style_profile_build_binding_change();
DROP TRIGGER style_profile_build_binding_guard
ON synthetic_lab_style_profile_build_bindings;
DROP FUNCTION geo_assert_style_profile_build_binding();
DROP TABLE synthetic_lab_style_profile_build_bindings;

CREATE OR REPLACE FUNCTION geo_assert_synthetic_lab_terminal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE metadata synthetic_lab_job_metadata%ROWTYPE;
DECLARE current_authorization synthetic_lab_authorization_versions%ROWTYPE;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR UPDATE;
    SELECT * INTO STRICT metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    IF metadata.domain_job_kind <> NEW.job_kind
       OR durable.status NOT IN ('running', 'finalizing')
       OR durable.cancel_requested_at IS NOT NULL
       OR durable.lease_token IS DISTINCT FROM NEW.lease_token
       OR durable.fencing_generation <> NEW.fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= NEW.occurred_at THEN
        RAISE EXCEPTION 'Synthetic Lab terminal writer lost Job lease or fencing ownership'
            USING ERRCODE = '40001';
    END IF;
    IF (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
        NEW.profile_version_id, NEW.profile_hash,
        NEW.prompt_release_id, NEW.prompt_release_hash)
       IS DISTINCT FROM
       (metadata.fact_snapshot_id, metadata.fact_snapshot_hash,
        metadata.profile_version_id, metadata.profile_hash,
        metadata.prompt_release_id, metadata.prompt_release_hash)
       OR coalesce(metadata.facts_current_approved, true) IS NOT TRUE
       OR coalesce(metadata.profile_frozen, true) IS NOT TRUE
       OR coalesce(metadata.prompt_frozen, true) IS NOT TRUE THEN
        RAISE EXCEPTION 'Synthetic Lab terminal runtime lineage is stale'
            USING ERRCODE = '40001';
    END IF;
    IF metadata.authorization_id IS NOT NULL THEN
        SELECT * INTO current_authorization
        FROM synthetic_lab_authorization_versions
        WHERE project_id = metadata.project_id
          AND channel = metadata.authorization_channel
          AND adapter_release = metadata.authorization_adapter_release
        ORDER BY version_number DESC LIMIT 1;
        IF NOT FOUND OR current_authorization.id <> metadata.authorization_id
           OR current_authorization.record_hash <> metadata.authorization_hash
           OR current_authorization.state <> 'approved'
           OR current_authorization.expires_at <= NEW.occurred_at
           OR NOT metadata.authorization_purpose = ANY(current_authorization.allowed_purposes) THEN
            RAISE EXCEPTION 'Synthetic Lab terminal authorization is stale or inactive'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER synthetic_style_profile_result_identity_guard
ON synthetic_lab_execution_results;
DROP FUNCTION geo_assert_synthetic_style_profile_result_identity();
DROP FUNCTION geo_synthetic_style_profile_result_matches_child(uuid, uuid, jsonb);
DROP FUNCTION geo_synthetic_style_profile_summary_json(text);
DROP FUNCTION geo_synthetic_style_profile_result_hash(jsonb);

DROP TRIGGER style_profile_parent_admission_lock ON durable_jobs;
DROP FUNCTION geo_lock_style_profile_parent_admission();
