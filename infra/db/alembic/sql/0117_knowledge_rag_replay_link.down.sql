DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM knowledge_rag_job_specs WHERE replayed_from_job_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: Knowledge RAG replay lineage exists'
            USING ERRCODE = '55000';
    END IF;
END $$;

ALTER TABLE knowledge_rag_job_specs
DROP CONSTRAINT knowledge_rag_job_specs_replay_not_self_check;
ALTER TABLE knowledge_rag_job_specs
DROP CONSTRAINT knowledge_rag_job_specs_replay_source_fkey;
DROP INDEX knowledge_rag_job_specs_replay_source_idx;
DROP INDEX knowledge_rag_job_specs_root_run_document_key;
ALTER TABLE knowledge_rag_job_specs DROP COLUMN replayed_from_job_id;
ALTER TABLE knowledge_rag_job_specs
ADD CONSTRAINT knowledge_rag_job_specs_run_document_key
UNIQUE (pipeline_run_id, document_id);
