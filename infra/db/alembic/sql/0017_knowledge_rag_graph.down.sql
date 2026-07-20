DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM durable_jobs WHERE kind = 'knowledge.rag.extract')
       OR EXISTS (SELECT 1 FROM knowledge_rag_job_specs)
       OR EXISTS (SELECT 1 FROM knowledge_rag_revisions)
       OR EXISTS (SELECT 1 FROM knowledge_fact_candidate_sources)
       OR EXISTS (SELECT 1 FROM knowledge_entity_candidates)
       OR EXISTS (SELECT 1 FROM knowledge_entity_candidate_sources)
       OR EXISTS (SELECT 1 FROM knowledge_relation_candidates)
       OR EXISTS (SELECT 1 FROM knowledge_rag_validation_findings)
       OR EXISTS (SELECT 1 FROM knowledge_graph_entities)
       OR EXISTS (SELECT 1 FROM knowledge_graph_entity_sources)
       OR EXISTS (SELECT 1 FROM knowledge_graph_relations)
       OR EXISTS (SELECT 1 FROM knowledge_graph_relation_sources)
       OR EXISTS (
           SELECT 1 FROM knowledge_sources
           WHERE id <> logical_source_id OR supersedes_source_id IS NOT NULL
       )
       OR EXISTS (
           SELECT 1 FROM knowledge_fact_candidates
           WHERE rag_revision_id IS NOT NULL
              OR extractor_release <> 'legacy-sentence-v1'
              OR source_locator IS NOT NULL
              OR lifecycle_status <> 'active'
       ) THEN
        RAISE EXCEPTION 'cannot downgrade: Knowledge RAG or source revision data exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER evidence_items_active_fact_guard ON evidence_items;
DROP TRIGGER knowledge_fact_candidate_contract_guard ON knowledge_fact_candidates;
DROP TRIGGER knowledge_rag_revisions_lifecycle_guard ON knowledge_rag_revisions;
DROP TRIGGER knowledge_source_revision_guard ON knowledge_sources;

DROP TRIGGER knowledge_entity_candidates_approval_check ON knowledge_entity_candidates;
DROP TRIGGER knowledge_relation_candidates_approval_check ON knowledge_relation_candidates;
DROP TRIGGER knowledge_graph_entity_sources_context_check ON knowledge_graph_entity_sources;
DROP TRIGGER knowledge_graph_relation_sources_context_check ON knowledge_graph_relation_sources;
DROP TRIGGER knowledge_graph_entities_source_check ON knowledge_graph_entities;
DROP TRIGGER knowledge_graph_relations_source_check ON knowledge_graph_relations;
DROP TRIGGER knowledge_entity_candidates_contract_guard ON knowledge_entity_candidates;
DROP TRIGGER knowledge_relation_candidates_contract_guard ON knowledge_relation_candidates;
DROP TRIGGER knowledge_graph_entities_contract_guard ON knowledge_graph_entities;
DROP TRIGGER knowledge_graph_relations_contract_guard ON knowledge_graph_relations;
DROP TRIGGER knowledge_graph_entity_sources_contract_guard ON knowledge_graph_entity_sources;
DROP TRIGGER knowledge_graph_relation_sources_contract_guard ON knowledge_graph_relation_sources;

DROP FUNCTION geo_assert_current_graph_relation_has_source();
DROP FUNCTION geo_assert_current_graph_entity_has_source();
DROP FUNCTION geo_assert_knowledge_relation_graph_source();
DROP FUNCTION geo_assert_knowledge_relation_approval();
DROP FUNCTION geo_assert_knowledge_entity_graph_source();
DROP FUNCTION geo_assert_knowledge_entity_approval();
DROP FUNCTION geo_protect_knowledge_graph_source();
DROP FUNCTION geo_protect_knowledge_graph_relation();
DROP FUNCTION geo_protect_knowledge_graph_entity();
DROP FUNCTION geo_protect_knowledge_graph_candidate();
DROP FUNCTION geo_require_active_fact_for_evidence();
DROP FUNCTION geo_protect_knowledge_fact_candidate();
DROP FUNCTION geo_protect_knowledge_rag_revision();
DROP FUNCTION geo_protect_knowledge_source_revision();

ALTER TABLE knowledge_relation_candidates
    DROP CONSTRAINT knowledge_relation_candidates_graph_fkey;
ALTER TABLE knowledge_entity_candidates
    DROP CONSTRAINT knowledge_entity_candidates_graph_fkey;

DROP TABLE knowledge_graph_relation_sources;
DROP TABLE knowledge_graph_relations;
DROP TABLE knowledge_graph_entity_sources;
DROP TABLE knowledge_graph_entities;
DROP TABLE knowledge_rag_validation_findings;
DROP TABLE knowledge_relation_candidates;
DROP TABLE knowledge_entity_candidate_sources;
DROP TABLE knowledge_entity_candidates;
DROP TABLE knowledge_fact_candidate_sources;

DROP INDEX knowledge_facts_rag_revision_idx;
DROP INDEX knowledge_facts_legacy_statement_key;
ALTER TABLE knowledge_fact_candidates
    DROP CONSTRAINT knowledge_facts_candidate_revision_context_key,
    DROP CONSTRAINT knowledge_facts_candidate_context_key,
    DROP CONSTRAINT knowledge_facts_rag_identity_key,
    DROP CONSTRAINT knowledge_facts_rag_revision_fkey,
    DROP CONSTRAINT knowledge_facts_review_shape_check,
    DROP CONSTRAINT knowledge_facts_extractor_contract_check,
    DROP CONSTRAINT knowledge_facts_lifecycle_status_check,
    DROP COLUMN lifecycle_status,
    DROP COLUMN source_locator,
    DROP COLUMN extractor_release,
    DROP COLUMN rag_revision_id,
    ADD CONSTRAINT knowledge_fact_candidates_pipeline_run_id_statement_hash_key
        UNIQUE (pipeline_run_id, statement_hash);

DROP TABLE knowledge_rag_revisions;
DROP TABLE knowledge_rag_job_specs;

DROP INDEX knowledge_sources_supersedes_fk_idx;
DROP INDEX knowledge_sources_logical_lifecycle_idx;
ALTER TABLE knowledge_sources
    DROP CONSTRAINT knowledge_sources_revision_shape_check,
    DROP CONSTRAINT knowledge_sources_single_successor_key,
    DROP CONSTRAINT knowledge_sources_supersedes_fkey,
    DROP CONSTRAINT knowledge_sources_logical_root_fkey,
    DROP CONSTRAINT knowledge_sources_exact_logical_key,
    DROP COLUMN supersedes_source_id,
    DROP COLUMN logical_source_id;
