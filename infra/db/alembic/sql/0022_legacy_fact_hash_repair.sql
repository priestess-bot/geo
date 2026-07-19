LOCK TABLE
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
    invalid_hash_count bigint;
    referenced_count bigint;
    duplicate_target_count bigint;
BEGIN
    SELECT count(*)
    INTO invalid_hash_count
    FROM knowledge_fact_candidates AS fact
    WHERE fact.extractor_release = 'legacy-sentence-v1'
      AND fact.rag_revision_id IS NULL
      AND fact.statement_hash <> encode(
          digest(convert_to(fact.statement, 'UTF8'), 'sha256'),
          'hex'
      )
      AND (
          octet_length(convert_to(fact.statement, 'UTF8'))
              <> char_length(fact.statement)
          OR fact.statement_hash <> encode(
              digest(
                  convert_to(
                      translate(
                          fact.statement,
                          'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                          'abcdefghijklmnopqrstuvwxyz'
                      ),
                      'UTF8'
                  ),
                  'sha256'
              ),
              'hex'
          )
      );

    WITH repair_targets AS (
        SELECT fact.id
        FROM knowledge_fact_candidates AS fact
        WHERE fact.extractor_release = 'legacy-sentence-v1'
          AND fact.rag_revision_id IS NULL
          AND octet_length(convert_to(fact.statement, 'UTF8'))
              = char_length(fact.statement)
          AND fact.statement_hash = encode(
              digest(
                  convert_to(
                      translate(
                          fact.statement,
                          'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                          'abcdefghijklmnopqrstuvwxyz'
                      ),
                      'UTF8'
                  ),
                  'sha256'
              ),
              'hex'
          )
          AND fact.statement_hash <> encode(
              digest(convert_to(fact.statement, 'UTF8'), 'sha256'),
              'hex'
          )
    )
    SELECT count(*)
    INTO referenced_count
    FROM repair_targets AS target
    WHERE EXISTS (
        SELECT 1
        FROM knowledge_fact_evidence_lineages AS lineage
        WHERE lineage.knowledge_fact_id = target.id
    )
       OR EXISTS (
        SELECT 1
        FROM knowledge_fact_candidate_sources AS source
        WHERE source.fact_candidate_id = target.id
    )
       OR EXISTS (
        SELECT 1
        FROM knowledge_question_generation_fact_inputs AS input
        WHERE input.fact_candidate_id = target.id
    )
       OR EXISTS (
        SELECT 1
        FROM knowledge_question_candidate_fact_sources AS source
        WHERE source.fact_candidate_id = target.id
    )
       OR EXISTS (
        SELECT 1
        FROM evidence_items AS evidence
        WHERE evidence.item_type = 'approved_fact'
          AND evidence.source_id = target.id
    )
       OR EXISTS (
        SELECT 1
        FROM prompt_simulations AS simulation
        WHERE simulation.input_snapshot #> '{question_binding,source_fact_ids}'
              @> to_jsonb(ARRAY[target.id::text])
           OR simulation.input_snapshot #> '{brief,geo_test_question,source_fact_ids}'
              @> to_jsonb(ARRAY[target.id::text])
    )
       OR EXISTS (
        SELECT 1
        FROM prompt_simulation_results AS result
        WHERE result.artifact_manifest #> '{question_binding,source_fact_ids}'
              @> to_jsonb(ARRAY[target.id::text])
    );

    WITH repair_targets AS (
        SELECT
            fact.id,
            fact.pipeline_run_id,
            encode(
                digest(convert_to(fact.statement, 'UTF8'), 'sha256'),
                'hex'
            ) AS repaired_statement_hash
        FROM knowledge_fact_candidates AS fact
        WHERE fact.extractor_release = 'legacy-sentence-v1'
          AND fact.rag_revision_id IS NULL
          AND octet_length(convert_to(fact.statement, 'UTF8'))
              = char_length(fact.statement)
          AND fact.statement_hash = encode(
              digest(
                  convert_to(
                      translate(
                          fact.statement,
                          'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                          'abcdefghijklmnopqrstuvwxyz'
                      ),
                      'UTF8'
                  ),
                  'sha256'
              ),
              'hex'
          )
          AND fact.statement_hash <> encode(
              digest(convert_to(fact.statement, 'UTF8'), 'sha256'),
              'hex'
          )
    )
    SELECT count(*)
    INTO duplicate_target_count
    FROM repair_targets AS target
    WHERE EXISTS (
        SELECT 1
        FROM knowledge_fact_candidates AS other
        WHERE other.id <> target.id
          AND other.pipeline_run_id = target.pipeline_run_id
          AND other.rag_revision_id IS NULL
          AND other.statement_hash = target.repaired_statement_hash
    );

    IF invalid_hash_count <> 0
       OR referenced_count <> 0
       OR duplicate_target_count <> 0 THEN
        RAISE EXCEPTION
            'cannot repair legacy Fact hashes: invalid_hash=%%, referenced=%%, duplicate_target=%%',
            invalid_hash_count, referenced_count, duplicate_target_count
            USING ERRCODE = '55000';
    END IF;
END;
$$;

CREATE TABLE knowledge_legacy_fact_hash_repairs (
    fact_candidate_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    source_id uuid NOT NULL,
    document_id uuid NOT NULL,
    chunk_id uuid NOT NULL,
    previous_statement_hash text NOT NULL
        CHECK (previous_statement_hash ~ '^[0-9a-f]{64}$'),
    repaired_statement_hash text NOT NULL
        CHECK (repaired_statement_hash ~ '^[0-9a-f]{64}$'),
    repair_contract_version text NOT NULL
        DEFAULT 'legacy-ascii-lower-sha256-to-exact-v1'
        CHECK (
            repair_contract_version = 'legacy-ascii-lower-sha256-to-exact-v1'
        ),
    repaired_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_legacy_fact_hash_repairs_changed_check CHECK (
        previous_statement_hash <> repaired_statement_hash
    )
);

INSERT INTO knowledge_legacy_fact_hash_repairs (
    fact_candidate_id, project_id, pipeline_run_id, source_id, document_id,
    chunk_id, previous_statement_hash, repaired_statement_hash
)
SELECT
    fact.id,
    fact.project_id,
    fact.pipeline_run_id,
    fact.source_id,
    fact.document_id,
    fact.chunk_id,
    fact.statement_hash,
    encode(digest(convert_to(fact.statement, 'UTF8'), 'sha256'), 'hex')
FROM knowledge_fact_candidates AS fact
WHERE fact.extractor_release = 'legacy-sentence-v1'
  AND fact.rag_revision_id IS NULL
  AND octet_length(convert_to(fact.statement, 'UTF8'))
      = char_length(fact.statement)
  AND fact.statement_hash = encode(
      digest(
          convert_to(
              translate(
                  fact.statement,
                  'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                  'abcdefghijklmnopqrstuvwxyz'
              ),
              'UTF8'
          ),
          'sha256'
      ),
      'hex'
  )
  AND fact.statement_hash <> encode(
      digest(convert_to(fact.statement, 'UTF8'), 'sha256'),
      'hex'
  );

SET LOCAL session_replication_role = 'replica';

UPDATE knowledge_fact_candidates AS fact
SET statement_hash = repair.repaired_statement_hash
FROM knowledge_legacy_fact_hash_repairs AS repair
WHERE fact.id = repair.fact_candidate_id
  AND fact.project_id = repair.project_id
  AND fact.pipeline_run_id = repair.pipeline_run_id
  AND fact.source_id = repair.source_id
  AND fact.document_id = repair.document_id
  AND fact.chunk_id = repair.chunk_id
  AND fact.statement_hash = repair.previous_statement_hash;

SET LOCAL session_replication_role = 'origin';

ALTER TABLE knowledge_legacy_fact_hash_repairs
    ADD CONSTRAINT knowledge_legacy_fact_hash_repairs_fact_fkey FOREIGN KEY (
        fact_candidate_id, project_id, pipeline_run_id, source_id,
        document_id, chunk_id, repaired_statement_hash
    ) REFERENCES knowledge_fact_candidates(
        id, project_id, pipeline_run_id, source_id, document_id, chunk_id,
        statement_hash
    ) DEFERRABLE INITIALLY DEFERRED;

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
           OR fact.statement_hash <> repair.repaired_statement_hash
    ) THEN
        RAISE EXCEPTION 'legacy Fact hash repair did not update every audited row'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

CREATE TRIGGER knowledge_legacy_fact_hash_repairs_immutable
BEFORE UPDATE OR DELETE ON knowledge_legacy_fact_hash_repairs
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

ALTER TABLE knowledge_legacy_fact_hash_repairs ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_legacy_fact_hash_repairs FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON knowledge_legacy_fact_hash_repairs
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON knowledge_legacy_fact_hash_repairs
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON knowledge_legacy_fact_hash_repairs
TO geo_app, geo_worker, geo_readonly;
