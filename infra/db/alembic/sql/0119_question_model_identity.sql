ALTER TABLE knowledge_question_generation_results
ADD COLUMN execution_backend text,
ADD COLUMN actual_model text,
ADD CONSTRAINT knowledge_question_results_model_identity_check CHECK (
    (execution_backend IS NULL AND actual_model IS NULL)
    OR (
        execution_backend IN ('dify', 'native')
        AND actual_model IS NOT NULL
        AND btrim(actual_model) <> ''
    )
);

-- Result rows are append-only. Temporarily remove only their immutable-row
-- trigger while reconstructing the sanitized model identity from immutable
-- Dify or native call evidence. The migration transaction restores it atomically.
DROP TRIGGER knowledge_question_results_immutable
ON knowledge_question_generation_results;

WITH latest_dify AS (
    SELECT DISTINCT ON (attempt.project_id, attempt.job_id)
           attempt.project_id,
           attempt.job_id,
           COALESCE(
               NULLIF(btrim(result.provider_reported_model), ''),
               result.configured_model
           ) AS actual_model
    FROM dify_workflow_execution_attempts attempt
    JOIN dify_workflow_execution_results result
      ON result.attempt_id = attempt.id
     AND result.project_id = attempt.project_id
     AND result.job_id = attempt.job_id
    WHERE attempt.execution_kind = 'business'
      AND attempt.status = 'succeeded'
    ORDER BY attempt.project_id, attempt.job_id, attempt.attempt_number DESC
)
UPDATE knowledge_question_generation_results generation
SET execution_backend = 'dify',
    actual_model = latest.actual_model
FROM latest_dify latest
WHERE generation.project_id = latest.project_id
  AND generation.job_id = latest.job_id;

WITH latest_native AS (
    SELECT DISTINCT ON (call.project_id, call.job_id)
           call.project_id,
           call.job_id,
           COALESCE(
               NULLIF(btrim(call.provider_reported_model), ''),
               call.configured_model
           ) AS actual_model
    FROM model_call_logs call
    WHERE call.status = 'succeeded'
    ORDER BY call.project_id, call.job_id, call.call_number DESC
)
UPDATE knowledge_question_generation_results generation
SET execution_backend = 'native',
    actual_model = latest.actual_model
FROM latest_native latest
WHERE generation.project_id = latest.project_id
  AND generation.job_id = latest.job_id
  AND generation.execution_backend IS NULL;

CREATE TRIGGER knowledge_question_results_immutable
BEFORE UPDATE OR DELETE ON knowledge_question_generation_results
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

COMMENT ON COLUMN knowledge_question_generation_results.execution_backend IS
'Sanitized execution backend actually used by every batch in this completed generation.';
COMMENT ON COLUMN knowledge_question_generation_results.actual_model IS
'Provider-reported model, falling back to the execution-time configured model.';
