DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM synthetic_lab_model_call_children child
        WHERE child.execution_backend = 'dify'
          AND (
              child.backend_lineage_source NOT IN (
                  'migration_backfill_verified',
                  'migration_backfill_historical_mismatch'
              )
              OR NOT EXISTS (
                  SELECT 1
                  FROM dify_workflow_execution_attempts attempt
                  JOIN dify_workflow_releases release
                    ON release.id = attempt.release_id
                   AND release.project_id = attempt.project_id
                  WHERE attempt.project_id = child.project_id
                    AND attempt.job_id = child.child_job_id
                    AND attempt.execution_kind = 'business'
                    AND attempt.release_id = child.workflow_release_id
                    AND release.release_hash = child.workflow_release_hash
              )
          )
    ) THEN
        RAISE EXCEPTION 'cannot downgrade while post-0098 Synthetic child Dify lineage exists or legacy attempt evidence is missing';
    END IF;
END;
$$;

DROP VIEW synthetic_lab_model_call_child_status;

DROP TRIGGER synthetic_lab_model_call_backend_immutable
ON synthetic_lab_model_call_children;
DROP FUNCTION geo_reject_synthetic_child_backend_change();
DROP TRIGGER synthetic_lab_model_call_backend_guard
ON synthetic_lab_model_call_children;
DROP FUNCTION geo_assert_synthetic_child_execution_backend();

DROP FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, text, uuid, text, uuid, text, uuid, text,
    text, text, text, text, text, text, text, numeric, integer, text
);
DROP FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
);
ALTER FUNCTION geo_enqueue_synthetic_model_call_child_v1(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) RENAME TO geo_enqueue_synthetic_model_call_child;
REVOKE ALL ON FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) TO geo_worker;

CREATE OR REPLACE FUNCTION geo_assert_synthetic_model_call_child_job_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    link synthetic_lab_model_call_children%ROWTYPE;
    parent_job durable_jobs%ROWTYPE;
    successful_attempt uuid;
BEGIN
    IF OLD.kind <> 'synthetic.model.call' AND NEW.kind <> 'synthetic.model.call' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT link FROM synthetic_lab_model_call_children
    WHERE child_job_id = OLD.id AND project_id = OLD.project_id;
    IF (NEW.id, NEW.project_id, NEW.kind, NEW.input_hash,
        NEW.idempotency_key, NEW.parent_job_id, NEW.replay_nonce,
        NEW.campaign_id, NEW.max_attempts)
       IS DISTINCT FROM
       (OLD.id, OLD.project_id, OLD.kind, OLD.input_hash,
        OLD.idempotency_key, OLD.parent_job_id, OLD.replay_nonce,
        OLD.campaign_id, OLD.max_attempts) THEN
        RAISE EXCEPTION 'Synthetic model child immutable Durable Job identity changed'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.attempt_count = 0 AND NEW.status = 'running' THEN
        IF NEW.attempt_count <> 1 THEN
            RAISE EXCEPTION 'Synthetic model child first claim has an invalid attempt counter'
                USING ERRCODE = '40001';
        END IF;
        SELECT * INTO STRICT parent_job FROM durable_jobs
        WHERE id = link.parent_job_id AND project_id = link.project_id FOR SHARE;
        IF parent_job.cancel_requested_at IS NOT NULL
           OR NOT ((parent_job.status IN ('running', 'finalizing')
                    AND parent_job.lease_expires_at > clock_timestamp())
                OR (parent_job.status = 'retry_wait'
                    AND parent_job.error_code = 'synthetic_child_pending')) THEN
            RAISE EXCEPTION 'Synthetic model child cannot start after its parent was blocked'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    IF NEW.status = 'succeeded' AND OLD.status IS DISTINCT FROM 'succeeded' THEN
        IF NEW.result_ref LIKE 'model-gateway://attempt/%' THEN
            SELECT attempt.id INTO successful_attempt
            FROM model_gateway_call_attempts attempt
            JOIN model_gateway_terminal_events terminal
              ON terminal.attempt_id = attempt.id AND terminal.project_id = attempt.project_id
             AND terminal.job_id = attempt.job_id
            WHERE attempt.project_id = NEW.project_id AND attempt.job_id = NEW.id
              AND terminal.status = 'succeeded'
            ORDER BY attempt.attempt_number DESC LIMIT 1;
        ELSIF NEW.result_ref LIKE 'dify-workflow://attempt/%' THEN
            SELECT attempt.id INTO successful_attempt
            FROM dify_workflow_execution_attempts attempt
            JOIN dify_workflow_execution_results result
              ON result.attempt_id = attempt.id AND result.project_id = attempt.project_id
             AND result.job_id = attempt.job_id
            WHERE attempt.project_id = NEW.project_id AND attempt.job_id = NEW.id
              AND attempt.execution_kind = 'business' AND attempt.status = 'succeeded'
            ORDER BY attempt.attempt_number DESC LIMIT 1;
        END IF;
        IF successful_attempt IS NULL OR NEW.result_ref IS DISTINCT FROM
           (CASE WHEN NEW.result_ref LIKE 'dify-workflow://attempt/%'
                THEN 'dify-workflow://attempt/' || successful_attempt::text
                ELSE 'model-gateway://attempt/' || successful_attempt::text END) THEN
            RAISE EXCEPTION 'Synthetic model child success lacks a governed result'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_synthetic_model_call_child() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_job durable_jobs%ROWTYPE;
    child_job durable_jobs%ROWTYPE;
    parent_metadata synthetic_lab_job_metadata%ROWTYPE;
    child_metadata synthetic_lab_job_metadata%ROWTYPE;
    parent_task synthetic_lab_execution_tasks%ROWTYPE;
    child_outbox synthetic_lab_outbox_messages%ROWTYPE;
    prompt_binding prompt_program_bindings%ROWTYPE;
    prompt_release prompt_program_releases%ROWTYPE;
    prompt_state prompt_program_release_states%ROWTYPE;
    runtime_manifest model_gateway_runtime_manifests%ROWTYPE;
    runtime_option model_gateway_runtime_options%ROWTYPE;
    model_release model_gateway_model_releases%ROWTYPE;
    expected_payload jsonb;
    expected_payload_hash text;
BEGIN
    SELECT * INTO STRICT parent_job FROM durable_jobs
    WHERE id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_job FROM durable_jobs
    WHERE id = NEW.child_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT parent_metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.child_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT parent_task FROM synthetic_lab_execution_tasks
    WHERE job_id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_outbox FROM synthetic_lab_outbox_messages
    WHERE id = NEW.outbox_id AND project_id = NEW.project_id;

    expected_payload := jsonb_build_object(
        'parent_job_id', NEW.parent_job_id::text,
        'step_key_hash', NEW.step_key_hash,
        'task_artifact_hash', NEW.task_artifact_hash
    );
    expected_payload_hash := encode(digest(
        convert_to(geo_jsonb_canonical_text(expected_payload), 'UTF8'), 'sha256'
    ), 'hex');
    IF NEW.step_key_hash <> encode(digest(convert_to(NEW.step_key, 'UTF8'), 'sha256'), 'hex')
       OR parent_job.kind <> NEW.parent_job_kind
       OR parent_job.status NOT IN ('running', 'finalizing')
       OR parent_job.cancel_requested_at IS NOT NULL
       OR parent_job.lease_token IS DISTINCT FROM NEW.parent_lease_token
       OR parent_job.fencing_generation <> NEW.parent_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= NEW.created_at
       OR parent_task.task_input_hash <> NEW.parent_task_input_hash
       OR child_job.kind <> 'synthetic.model.call'
       OR child_job.status <> 'queued'
       OR child_job.attempt_count <> 0
       OR child_job.fencing_generation <> 0
       OR child_job.input_hash <> NEW.child_input_hash
       OR child_job.parent_job_id IS DISTINCT FROM NEW.parent_job_id
       OR child_job.campaign_id IS DISTINCT FROM parent_job.campaign_id
       OR child_metadata.domain_job_kind <> 'model_call_child'
       OR child_metadata.payload <> expected_payload
       OR child_metadata.payload_hash <> expected_payload_hash
       OR child_outbox.job_id <> NEW.child_job_id
       OR child_outbox.event_type <> 'synthetic.model.call.queued'
       OR child_outbox.payload_hash <> NEW.child_input_hash THEN
        RAISE EXCEPTION 'Synthetic model child does not match parent lease, Job, or Outbox lineage'
            USING ERRCODE = '40001';
    END IF;
    IF (parent_metadata.fact_snapshot_id, parent_metadata.fact_snapshot_hash,
        parent_metadata.profile_version_id, parent_metadata.profile_hash,
        parent_metadata.prompt_release_id, parent_metadata.prompt_release_hash)
       IS DISTINCT FROM
       (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
        NEW.profile_version_id, NEW.profile_hash,
        NEW.runtime_prompt_release_id, NEW.runtime_prompt_release_hash)
       OR NOT coalesce(parent_metadata.facts_current_approved, false)
       OR NOT coalesce(parent_metadata.profile_frozen, false)
       OR NOT coalesce(parent_metadata.prompt_frozen, false)
       OR (child_metadata.fact_snapshot_id, child_metadata.fact_snapshot_hash,
           child_metadata.profile_version_id, child_metadata.profile_hash,
           child_metadata.prompt_release_id, child_metadata.prompt_release_hash,
           child_metadata.facts_current_approved, child_metadata.profile_frozen,
           child_metadata.prompt_frozen)
          IS DISTINCT FROM
          (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
           NEW.profile_version_id, NEW.profile_hash,
           NEW.runtime_prompt_release_id, NEW.runtime_prompt_release_hash,
           true, true, true) THEN
        RAISE EXCEPTION 'Synthetic model child changed frozen parent runtime lineage'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO STRICT prompt_binding FROM prompt_program_bindings
    WHERE id = NEW.prompt_binding_id AND project_id = NEW.project_id
      AND purpose = NEW.prompt_purpose
      AND binding_version = NEW.prompt_binding_version;
    SELECT * INTO STRICT prompt_release FROM prompt_program_releases
    WHERE id = NEW.prompt_release_id AND project_id = NEW.project_id
      AND release_hash = NEW.prompt_release_hash;
    SELECT * INTO STRICT prompt_state FROM prompt_program_release_states
    WHERE id = NEW.prompt_frozen_state_id AND project_id = NEW.project_id
      AND release_id = NEW.prompt_release_id
      AND release_hash = NEW.prompt_release_hash
      AND version = NEW.prompt_state_version;
    IF prompt_binding.release_id <> NEW.prompt_release_id
       OR prompt_binding.release_version <> NEW.prompt_release_version
       OR prompt_binding.release_hash <> NEW.prompt_release_hash
       OR prompt_binding.frozen_state_id <> NEW.prompt_frozen_state_id
       OR prompt_release.version <> NEW.prompt_release_version
       OR prompt_release.program_kind <> NEW.prompt_program_kind
       OR prompt_release.purpose <> NEW.prompt_purpose
       OR prompt_release.model_policy_hash <> NEW.prompt_model_policy_hash
       OR prompt_release.output_schema_hash <> NEW.portable_output_schema_hash
       OR prompt_release.application_output_schema_hash
            <> NEW.application_output_schema_hash
       OR prompt_state.status <> 'frozen'
       OR EXISTS (
            SELECT 1 FROM prompt_program_bindings AS newer
            WHERE newer.project_id = NEW.project_id
              AND newer.purpose = NEW.prompt_purpose
              AND newer.binding_version > NEW.prompt_binding_version
       ) THEN
        RAISE EXCEPTION 'Synthetic model child requires the exact current frozen Prompt binding'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO STRICT runtime_manifest FROM model_gateway_runtime_manifests
    WHERE id = NEW.runtime_manifest_id AND project_id = NEW.project_id
      AND manifest_hash = NEW.runtime_manifest_hash
    FOR SHARE;
    SELECT * INTO STRICT runtime_option FROM model_gateway_runtime_options
    WHERE id = NEW.runtime_option_id AND project_id = NEW.project_id
      AND manifest_id = NEW.runtime_manifest_id
      AND option_hash = NEW.runtime_option_hash;
    SELECT * INTO STRICT model_release FROM model_gateway_model_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND model_release_id = NEW.model_release_id
      AND release_hash = NEW.model_release_hash;
    IF runtime_manifest.status <> 'approved'
       OR runtime_option.provider <> NEW.provider
       OR runtime_option.adapter_release_id <> NEW.adapter_release_id
       OR runtime_option.adapter_release_hash <> NEW.adapter_release_hash
       OR runtime_option.model_release_id <> NEW.model_release_id
       OR runtime_option.model_release_hash <> NEW.model_release_hash
       OR NEW.prompt_purpose <> ALL(runtime_option.allowed_purposes)
       OR NOT runtime_option.allowed_search_modes @> jsonb_build_array(NEW.search_mode)
       OR model_release.configured_model <> NEW.configured_model
       OR model_release.state <> 'approved' THEN
        RAISE EXCEPTION 'Synthetic model child differs from the approved runtime option'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE synthetic_lab_model_call_children
DROP CONSTRAINT synthetic_lab_model_call_children_workflow_release_fkey,
DROP CONSTRAINT synthetic_lab_model_call_children_lineage_source_check,
DROP CONSTRAINT synthetic_lab_model_call_children_backend_shape_check,
DROP COLUMN backend_lineage_source,
DROP COLUMN workflow_release_hash,
DROP COLUMN workflow_release_id,
DROP COLUMN execution_backend;

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
       child.task_artifact_uri, child.task_artifact_hash, child.child_input_hash,
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
       coalesce(durable.error_code, native.error_code, dify.error_code) AS failure_code,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%' THEN 'dify'
            ELSE 'model_gateway' END AS execution_backend,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.attempt_id ELSE native.attempt_id END AS model_attempt_id,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.attempt_id ELSE native.gateway_call_log_id END AS gateway_call_log_id,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.output_hash ELSE native.output_hash END AS output_hash,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.output_hash ELSE native.response_hash END AS response_hash,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.configured_model ELSE native.configured_model
            END AS model_configured_model,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.provider_reported_model ELSE native.provider_reported_model
            END AS model_reported_model,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.output END AS dify_output,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.release_id END AS dify_release_id,
       CASE WHEN durable.result_ref LIKE 'dify-workflow://%'
            THEN dify.release_hash END AS dify_release_hash,
       child.created_at
FROM synthetic_lab_model_call_children child
JOIN durable_jobs durable
  ON durable.id = child.child_job_id AND durable.project_id = child.project_id
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id, terminal.error_code,
           terminal.gateway_call_log_id, terminal.output_hash, terminal.response_hash,
           terminal.configured_model, terminal.provider_reported_model
    FROM model_gateway_call_attempts attempt
    LEFT JOIN model_gateway_terminal_events terminal
      ON terminal.attempt_id = attempt.id AND terminal.project_id = attempt.project_id
     AND terminal.job_id = attempt.job_id
    WHERE attempt.project_id = child.project_id AND attempt.job_id = child.child_job_id
    ORDER BY attempt.attempt_number DESC LIMIT 1
) native ON true
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id, attempt.error_code, result.output,
           result.response_hash AS output_hash, result.configured_model,
           result.provider_reported_model, release.id AS release_id,
           release.release_hash
    FROM dify_workflow_execution_attempts attempt
    JOIN dify_workflow_releases release
      ON release.id = attempt.release_id AND release.project_id = attempt.project_id
    LEFT JOIN dify_workflow_execution_results result
      ON result.attempt_id = attempt.id AND result.project_id = attempt.project_id
    WHERE attempt.project_id = child.project_id AND attempt.job_id = child.child_job_id
    ORDER BY attempt.attempt_number DESC LIMIT 1
) dify ON true;
REVOKE ALL ON synthetic_lab_model_call_child_status
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON synthetic_lab_model_call_child_status TO geo_app, geo_worker;
