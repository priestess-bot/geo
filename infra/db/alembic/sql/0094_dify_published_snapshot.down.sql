CREATE OR REPLACE FUNCTION geo_assert_dify_attempt_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'running' OR NEW.status NOT IN ('succeeded', 'failed')
       OR NEW.id <> OLD.id OR NEW.project_id <> OLD.project_id
       OR NEW.release_id <> OLD.release_id OR NEW.job_id IS DISTINCT FROM OLD.job_id
       OR NEW.execution_kind <> OLD.execution_kind
       OR NEW.attempt_number <> OLD.attempt_number
       OR NEW.fencing_generation IS DISTINCT FROM OLD.fencing_generation
       OR NEW.context_hash <> OLD.context_hash OR NEW.request_hash <> OLD.request_hash
       OR NEW.started_at <> OLD.started_at THEN
        RAISE EXCEPTION 'Dify attempt permits only one running-to-terminal transition'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

DROP INDEX IF EXISTS dify_workflow_attempts_snapshot_idx;
ALTER TABLE dify_workflow_execution_attempts
DROP CONSTRAINT IF EXISTS dify_workflow_attempts_snapshot_fkey;
ALTER TABLE dify_workflow_execution_attempts
DROP COLUMN IF EXISTS published_snapshot_id;

DROP TRIGGER IF EXISTS dify_published_snapshots_immutable
ON dify_workflow_published_snapshots;
DROP FUNCTION IF EXISTS geo_reject_dify_snapshot_mutation();
DROP TABLE IF EXISTS dify_workflow_published_snapshots;
