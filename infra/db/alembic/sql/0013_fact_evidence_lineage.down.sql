DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM knowledge_fact_evidence_lineages
        WHERE lineage_contract_version = 'knowledge-fact-evidence-v1'
    ) OR EXISTS (
        SELECT 1 FROM evidence_items WHERE fact_lineage_status = 'verified'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: verified Fact Evidence lineage exists'
            USING ERRCODE = '55000';
    END IF;
END $$;

DROP TRIGGER IF EXISTS evidence_pack_items_fact_lineage_guard ON evidence_pack_items;
DROP FUNCTION IF EXISTS geo_assert_evidence_pack_item_lineage();

CREATE OR REPLACE FUNCTION geo_protect_evidence_pack_attempt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'evidence pack attempts are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'building' THEN
        IF OLD.status IN ('ready', 'needs_evidence', 'blocked') AND NEW.status = 'superseded'
           AND NEW.superseded_by_attempt_id IS NOT NULL AND NEW.superseded_at IS NOT NULL
           AND (NEW.id, NEW.project_id, NEW.brief_version_id, NEW.attempt_number,
                NEW.failure_reason, NEW.pack_hash, NEW.created_at, NEW.completed_at)
               IS NOT DISTINCT FROM
               (OLD.id, OLD.project_id, OLD.brief_version_id, OLD.attempt_number,
                OLD.failure_reason, OLD.pack_hash, OLD.created_at, OLD.completed_at) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'terminal evidence pack attempts are immutable; create a new attempt'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status = 'superseded' THEN
        RAISE EXCEPTION 'a building evidence pack cannot be superseded'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'ready' THEN
        IF NOT EXISTS (
            SELECT 1 FROM evidence_pack_items i
            WHERE i.pack_attempt_id = NEW.id AND i.project_id = NEW.project_id
        ) OR EXISTS (
            SELECT 1
            FROM evidence_pack_items i
            JOIN evidence_items e ON e.id = i.evidence_item_id AND e.project_id = i.project_id
            WHERE i.pack_attempt_id = NEW.id AND i.project_id = NEW.project_id
              AND (e.usage_rights IN ('unknown', 'restricted')
                   OR e.confidentiality = 'restricted')
        ) THEN
            RAISE EXCEPTION 'ready evidence packs require at least one eligible evidence item'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS evidence_items_require_fact_lineage ON evidence_items;
DROP TRIGGER IF EXISTS evidence_items_new_fact_contract ON evidence_items;
DROP TRIGGER IF EXISTS knowledge_facts_promoted_immutable ON knowledge_fact_candidates;
DROP TRIGGER IF EXISTS knowledge_fact_evidence_lineages_immutable
ON knowledge_fact_evidence_lineages;
DROP TRIGGER IF EXISTS knowledge_fact_evidence_lineage_insert_guard
ON knowledge_fact_evidence_lineages;
DROP FUNCTION IF EXISTS geo_require_approved_fact_evidence_lineage();
DROP FUNCTION IF EXISTS geo_assert_new_approved_fact_evidence();
DROP FUNCTION IF EXISTS geo_protect_promoted_knowledge_fact();
DROP FUNCTION IF EXISTS geo_protect_fact_evidence_lineage();
DROP FUNCTION IF EXISTS geo_assert_fact_evidence_lineage();

DROP TABLE knowledge_fact_evidence_lineages;

DROP TRIGGER evidence_items_immutable ON evidence_items;
ALTER TABLE evidence_items
    DROP CONSTRAINT evidence_items_exact_lineage_identity_key,
    DROP CONSTRAINT evidence_items_fact_lineage_type_check,
    DROP CONSTRAINT evidence_items_fact_lineage_status_check,
    DROP COLUMN fact_lineage_status;
CREATE TRIGGER evidence_items_immutable
BEFORE UPDATE OR DELETE ON evidence_items
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

DROP INDEX IF EXISTS knowledge_facts_exact_chunk_idx;
DROP INDEX IF EXISTS knowledge_facts_exact_document_idx;
DROP INDEX IF EXISTS knowledge_facts_exact_run_idx;
DROP INDEX IF EXISTS knowledge_chunks_exact_document_idx;
DROP INDEX IF EXISTS knowledge_chunks_exact_run_idx;
DROP INDEX IF EXISTS knowledge_documents_exact_run_idx;

ALTER TABLE knowledge_fact_candidates
    DROP CONSTRAINT knowledge_facts_exact_chunk_fkey,
    DROP CONSTRAINT knowledge_facts_exact_document_fkey,
    DROP CONSTRAINT knowledge_facts_exact_run_fkey,
    DROP CONSTRAINT knowledge_facts_exact_hash_key,
    DROP CONSTRAINT knowledge_facts_exact_context_key,
    DROP COLUMN document_id;
ALTER TABLE knowledge_chunks
    DROP CONSTRAINT knowledge_chunks_exact_document_fkey,
    DROP CONSTRAINT knowledge_chunks_exact_run_fkey,
    DROP CONSTRAINT knowledge_chunks_exact_hash_key,
    DROP CONSTRAINT knowledge_chunks_exact_context_key;
ALTER TABLE knowledge_documents
    DROP CONSTRAINT knowledge_documents_exact_run_fkey,
    DROP CONSTRAINT knowledge_documents_exact_hash_key,
    DROP CONSTRAINT knowledge_documents_exact_context_key;
ALTER TABLE knowledge_pipeline_runs
    DROP CONSTRAINT knowledge_pipeline_runs_exact_source_key;
ALTER TABLE knowledge_sources
    DROP CONSTRAINT knowledge_sources_exact_content_key;
