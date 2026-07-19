CREATE OR REPLACE FUNCTION geo_question_candidate_sources_current(target_candidate_id uuid)
RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT
        EXISTS (
            SELECT 1 FROM knowledge_question_candidate_fact_sources AS source
            WHERE source.candidate_id = target_candidate_id
        )
        AND NOT EXISTS (
            SELECT 1
            FROM knowledge_question_candidate_fact_sources AS source
            JOIN knowledge_question_generation_fact_inputs AS input
              ON input.job_id = source.generated_by_job_id
             AND input.project_id = source.project_id
             AND input.campaign_id = source.campaign_id
             AND input.fact_candidate_id = source.fact_candidate_id
            LEFT JOIN knowledge_fact_candidates AS fact
              ON fact.id = input.fact_candidate_id
             AND fact.project_id = input.project_id
             AND fact.pipeline_run_id = input.pipeline_run_id
             AND fact.source_id = input.source_id
             AND fact.document_id = input.document_id
             AND fact.chunk_id = input.chunk_id
            WHERE source.candidate_id = target_candidate_id
              AND (
                  fact.id IS NULL OR fact.status <> 'approved'
                  OR fact.lifecycle_status <> 'active'
                  OR fact.rag_revision_id IS DISTINCT FROM input.rag_revision_id
                  OR fact.statement IS DISTINCT FROM input.statement_snapshot
                  OR fact.statement_hash IS DISTINCT FROM input.statement_hash
                  OR fact.source_locator IS DISTINCT FROM input.source_locator
                  OR fact.extractor_release IS DISTINCT FROM input.extractor_release
              )
        )
        AND NOT EXISTS (
            SELECT 1
            FROM knowledge_question_candidate_entity_sources AS source
            JOIN knowledge_question_generation_entity_inputs AS input
              ON input.job_id = source.generated_by_job_id
             AND input.project_id = source.project_id
             AND input.campaign_id = source.campaign_id
             AND input.graph_entity_id = source.graph_entity_id
            LEFT JOIN knowledge_graph_entities AS graph
              ON graph.id = input.graph_entity_id
             AND graph.project_id = input.project_id
            WHERE source.candidate_id = target_candidate_id
              AND (
                  graph.id IS NULL OR graph.status <> 'current'
                  OR graph.entity_type IS DISTINCT FROM input.entity_type_snapshot
                  OR graph.canonical_name IS DISTINCT FROM input.canonical_name_snapshot
                  OR graph.name_hash IS DISTINCT FROM input.name_hash
                  OR NOT EXISTS (
                      SELECT 1 FROM knowledge_graph_entity_sources AS lineage
                      WHERE lineage.graph_entity_id = graph.id
                        AND lineage.project_id = graph.project_id
                        AND lineage.lifecycle_status = 'active'
                  )
              )
        )
$$;
