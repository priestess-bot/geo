ALTER TABLE dify_workflow_releases
DROP CONSTRAINT dify_workflow_releases_purpose_check;
ALTER TABLE dify_workflow_releases
ADD CONSTRAINT dify_workflow_releases_purpose_check CHECK (purpose IN (
    'knowledge.question_generation', 'knowledge.rag_grounding',
    'placements.generation', 'placements.simulation',
    'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
    'synthetic_lab.conflict_check', 'synthetic_lab.revision'
));

ALTER TABLE dify_workflow_published_snapshots
DROP CONSTRAINT dify_workflow_published_snapshots_purpose_check;
ALTER TABLE dify_workflow_published_snapshots
ADD CONSTRAINT dify_workflow_published_snapshots_purpose_check CHECK (purpose IN (
    'knowledge.question_generation', 'knowledge.rag_grounding',
    'placements.generation', 'placements.simulation',
    'synthetic_lab.generation', 'synthetic_lab.claim_extraction',
    'synthetic_lab.conflict_check', 'synthetic_lab.revision'
));

CREATE TABLE dify_workflow_execution_results (
    attempt_id uuid PRIMARY KEY REFERENCES dify_workflow_execution_attempts(id),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    output jsonb NOT NULL CHECK (jsonb_typeof(output) = 'object'),
    response_hash text NOT NULL CHECK (response_hash ~ '^[0-9a-f]{64}$'),
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    provider_reported_model text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT dify_workflow_results_project_key UNIQUE (attempt_id, project_id),
    CONSTRAINT dify_workflow_results_job_fkey FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id)
);

CREATE FUNCTION geo_assert_dify_result_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM dify_workflow_execution_attempts attempt
        WHERE attempt.id = NEW.attempt_id AND attempt.project_id = NEW.project_id
          AND attempt.job_id = NEW.job_id AND attempt.execution_kind = 'business'
          AND attempt.status = 'running'
    ) THEN
        RAISE EXCEPTION 'Dify result requires its matching running business attempt'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER dify_workflow_result_insert_guard
BEFORE INSERT ON dify_workflow_execution_results
FOR EACH ROW EXECUTE FUNCTION geo_assert_dify_result_insert();
CREATE TRIGGER dify_workflow_results_immutable
BEFORE UPDATE OR DELETE ON dify_workflow_execution_results
FOR EACH ROW EXECUTE FUNCTION geo_reject_dify_runtime_mutation();

ALTER TABLE dify_workflow_execution_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE dify_workflow_execution_results FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON dify_workflow_execution_results
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
REVOKE ALL ON dify_workflow_execution_results FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON dify_workflow_execution_results TO geo_worker;

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
