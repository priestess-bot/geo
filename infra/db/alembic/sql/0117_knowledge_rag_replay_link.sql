ALTER TABLE knowledge_rag_job_specs
ADD COLUMN replayed_from_job_id uuid;

ALTER TABLE knowledge_rag_job_specs
DROP CONSTRAINT knowledge_rag_job_specs_run_document_key;

CREATE UNIQUE INDEX knowledge_rag_job_specs_root_run_document_key
ON knowledge_rag_job_specs(pipeline_run_id, document_id)
WHERE replayed_from_job_id IS NULL;

CREATE INDEX knowledge_rag_job_specs_replay_source_idx
ON knowledge_rag_job_specs(project_id, replayed_from_job_id)
WHERE replayed_from_job_id IS NOT NULL;

ALTER TABLE knowledge_rag_job_specs
ADD CONSTRAINT knowledge_rag_job_specs_replay_source_fkey
FOREIGN KEY (replayed_from_job_id, project_id)
REFERENCES durable_jobs(id, project_id);

ALTER TABLE knowledge_rag_job_specs
ADD CONSTRAINT knowledge_rag_job_specs_replay_not_self_check
CHECK (replayed_from_job_id IS NULL OR replayed_from_job_id <> job_id);
