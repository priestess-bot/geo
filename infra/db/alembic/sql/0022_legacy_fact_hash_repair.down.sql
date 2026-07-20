LOCK TABLE
    knowledge_legacy_fact_hash_repairs,
    knowledge_fact_candidates,
    knowledge_fact_evidence_lineages,
    knowledge_fact_candidate_sources,
    knowledge_question_generation_fact_inputs,
    knowledge_question_candidate_fact_sources,
    evidence_items,
    prompt_simulations,
    prompt_simulation_results
IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    changed_count bigint;
    referenced_count bigint;
    duplicate_target_count bigint;
BEGIN
    SELECT count(*)
    INTO changed_count
    FROM knowledge_legacy_fact_hash_repairs AS repair
    LEFT JOIN knowledge_fact_candidates AS fact
      ON fact.id = repair.fact_candidate_id
     AND fact.project_id = repair.project_id
     AND fact.pipeline_run_id = repair.pipeline_run_id
     AND fact.source_id = repair.source_id
     AND fact.document_id = repair.document_id
     AND fact.chunk_id = repair.chunk_id
    WHERE fact.id IS NULL
       OR fact.statement_hash <> repair.repaired_statement_hash;

    SELECT count(*)
    INTO referenced_count
    FROM knowledge_legacy_fact_hash_repairs AS repair
    WHERE EXISTS (
        SELECT 1
        FROM knowledge_fact_evidence_lineages AS lineage
        WHERE lineage.knowledge_fact_id = repair.fact_candidate_id
    )
       OR EXISTS (
        SELECT 1
        FROM knowledge_fact_candidate_sources AS source
        WHERE source.fact_candidate_id = repair.fact_candidate_id
    )
       OR EXISTS (
        SELECT 1
        FROM knowledge_question_generation_fact_inputs AS input
        WHERE input.fact_candidate_id = repair.fact_candidate_id
    )
       OR EXISTS (
        SELECT 1
        FROM knowledge_question_candidate_fact_sources AS source
        WHERE source.fact_candidate_id = repair.fact_candidate_id
    )
       OR EXISTS (
        SELECT 1
        FROM evidence_items AS evidence
        WHERE evidence.item_type = 'approved_fact'
          AND evidence.source_id = repair.fact_candidate_id
    )
       OR EXISTS (
        SELECT 1
        FROM prompt_simulations AS simulation
        WHERE simulation.input_snapshot #> '{question_binding,source_fact_ids}'
              @> to_jsonb(ARRAY[repair.fact_candidate_id::text])
           OR simulation.input_snapshot #> '{brief,geo_test_question,source_fact_ids}'
              @> to_jsonb(ARRAY[repair.fact_candidate_id::text])
    )
       OR EXISTS (
        SELECT 1
        FROM prompt_simulation_results AS result
        WHERE result.artifact_manifest #> '{question_binding,source_fact_ids}'
              @> to_jsonb(ARRAY[repair.fact_candidate_id::text])
    );

    SELECT count(*)
    INTO duplicate_target_count
    FROM knowledge_legacy_fact_hash_repairs AS repair
    WHERE EXISTS (
        SELECT 1
        FROM knowledge_fact_candidates AS other
        WHERE other.id <> repair.fact_candidate_id
          AND other.pipeline_run_id = repair.pipeline_run_id
          AND other.rag_revision_id IS NULL
          AND other.statement_hash = repair.previous_statement_hash
    );

    IF changed_count <> 0
       OR referenced_count <> 0
       OR duplicate_target_count <> 0 THEN
        RAISE EXCEPTION
            'cannot revert legacy Fact hash repair: changed=%%, referenced=%%, duplicate_target=%%',
            changed_count, referenced_count, duplicate_target_count
            USING ERRCODE = '55000';
    END IF;
END;
$$;

ALTER TABLE knowledge_legacy_fact_hash_repairs
    DROP CONSTRAINT knowledge_legacy_fact_hash_repairs_fact_fkey;

SET LOCAL session_replication_role = 'replica';

UPDATE knowledge_fact_candidates AS fact
SET statement_hash = repair.previous_statement_hash
FROM knowledge_legacy_fact_hash_repairs AS repair
WHERE fact.id = repair.fact_candidate_id
  AND fact.project_id = repair.project_id
  AND fact.pipeline_run_id = repair.pipeline_run_id
  AND fact.source_id = repair.source_id
  AND fact.document_id = repair.document_id
  AND fact.chunk_id = repair.chunk_id
  AND fact.statement_hash = repair.repaired_statement_hash;

SET LOCAL session_replication_role = 'origin';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM knowledge_legacy_fact_hash_repairs AS repair
        LEFT JOIN knowledge_fact_candidates AS fact
          ON fact.id = repair.fact_candidate_id
         AND fact.project_id = repair.project_id
         AND fact.pipeline_run_id = repair.pipeline_run_id
         AND fact.source_id = repair.source_id
         AND fact.document_id = repair.document_id
         AND fact.chunk_id = repair.chunk_id
        WHERE fact.id IS NULL
           OR fact.statement_hash <> repair.previous_statement_hash
    ) THEN
        RAISE EXCEPTION 'legacy Fact hash repair downgrade did not restore every audited row'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER knowledge_legacy_fact_hash_repairs_immutable
ON knowledge_legacy_fact_hash_repairs;
DROP TABLE knowledge_legacy_fact_hash_repairs;
