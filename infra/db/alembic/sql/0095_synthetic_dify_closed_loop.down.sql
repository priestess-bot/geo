DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM dify_workflow_execution_results) OR EXISTS (
        SELECT 1 FROM dify_workflow_releases WHERE purpose LIKE 'synthetic_lab.%'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade while Synthetic Dify releases or results exist';
    END IF;
END;
$$;

DROP VIEW synthetic_lab_model_call_child_status;
DROP TRIGGER dify_workflow_results_immutable ON dify_workflow_execution_results;
DROP TRIGGER dify_workflow_result_insert_guard ON dify_workflow_execution_results;
DROP FUNCTION geo_assert_dify_result_insert();
DROP TABLE dify_workflow_execution_results;

ALTER TABLE dify_workflow_published_snapshots
DROP CONSTRAINT dify_workflow_published_snapshots_purpose_check;
ALTER TABLE dify_workflow_published_snapshots
ADD CONSTRAINT dify_workflow_published_snapshots_purpose_check CHECK (purpose IN (
    'knowledge.question_generation', 'knowledge.rag_grounding',
    'placements.generation', 'placements.simulation'
));
ALTER TABLE dify_workflow_releases
DROP CONSTRAINT dify_workflow_releases_purpose_check;
ALTER TABLE dify_workflow_releases
ADD CONSTRAINT dify_workflow_releases_purpose_check CHECK (purpose IN (
    'knowledge.question_generation', 'knowledge.rag_grounding',
    'placements.generation', 'placements.simulation'
));

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
        WHERE id = link.parent_job_id AND project_id = link.project_id
        FOR SHARE;
        IF parent_job.cancel_requested_at IS NOT NULL
           OR NOT (
                (parent_job.status IN ('running', 'finalizing')
                    AND parent_job.lease_expires_at > clock_timestamp())
                OR (parent_job.status = 'retry_wait'
                    AND parent_job.error_code = 'synthetic_child_pending')
           ) THEN
            RAISE EXCEPTION 'Synthetic model child cannot start after its parent was blocked'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    IF NEW.status = 'succeeded' AND OLD.status IS DISTINCT FROM 'succeeded' THEN
        SELECT attempt.id INTO successful_attempt
        FROM model_gateway_call_attempts AS attempt
        JOIN model_gateway_terminal_events AS terminal
          ON terminal.attempt_id = attempt.id
         AND terminal.project_id = attempt.project_id
         AND terminal.job_id = attempt.job_id
        WHERE attempt.project_id = NEW.project_id
          AND attempt.job_id = NEW.id
          AND terminal.status = 'succeeded'
        ORDER BY attempt.attempt_number DESC
        LIMIT 1;
        IF successful_attempt IS NULL
           OR NEW.result_ref IS DISTINCT FROM
              'model-gateway://attempt/' || successful_attempt::text THEN
            RAISE EXCEPTION 'Synthetic model child success lacks a governed Model Gateway result'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

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
            WHEN durable.error_code = 'model_unknown_outcome' THEN 'unknown_outcome'
            WHEN durable.status IN ('failed', 'dead_lettered') THEN 'failed'
            WHEN durable.status IN ('running', 'finalizing') THEN 'running'
            ELSE 'queued' END AS status,
       durable.attempt_count AS durable_attempt_count,
       durable.fencing_generation AS durable_fencing_generation,
       durable.cancel_requested_at,
       coalesce(durable.error_code, latest.error_code) AS failure_code,
       latest.attempt_id AS model_attempt_id,
       latest.attempt_number AS model_attempt_number,
       latest.terminal_status AS model_terminal_status,
       latest.gateway_call_log_id, latest.output_hash, latest.response_hash,
       latest.configured_model AS model_configured_model,
       latest.provider_reported_model AS model_reported_model, child.created_at
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
    WHERE attempt.project_id = child.project_id AND attempt.job_id = child.child_job_id
    ORDER BY attempt.attempt_number DESC LIMIT 1
) latest ON true;
REVOKE ALL ON synthetic_lab_model_call_child_status
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON synthetic_lab_model_call_child_status TO geo_app, geo_worker;

COMMENT ON VIEW synthetic_lab_model_call_child_status IS
    'Admin/worker status projection over child Durable Jobs and governed Model Gateway terminals.';
