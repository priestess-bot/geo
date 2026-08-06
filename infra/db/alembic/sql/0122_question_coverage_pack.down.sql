DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM knowledge_question_generation_specs
        WHERE generation_mode = 'coverage_pack'
    ) OR EXISTS (
        SELECT 1 FROM knowledge_question_generation_batches
    ) OR EXISTS (
        SELECT 1 FROM knowledge_question_candidate_revisions
    ) THEN
        RAISE EXCEPTION
            'cannot downgrade: question coverage pack, checkpoint, or revision data exists';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION geo_protect_question_candidate() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    duplicate_threshold numeric(5,4);
    dimension_turn integer;
    parent_dimension text;
    nearest_normalized_text_hash text;
    parent_turn integer;
    parent_dimension_key text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Question candidates cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF to_jsonb(NEW) - ARRAY[
            'workflow_status', 'reviewed_by', 'review_notes', 'reviewed_at', 'updated_at'
        ] IS DISTINCT FROM to_jsonb(OLD) - ARRAY[
            'workflow_status', 'reviewed_by', 'review_notes', 'reviewed_at', 'updated_at'
        ] THEN
            RAISE EXCEPTION 'Question candidate identity and dedup evidence are immutable'
                USING ERRCODE = '55000';
        END IF;
        IF OLD.workflow_status IS DISTINCT FROM NEW.workflow_status THEN
            IF OLD.workflow_status <> 'pending_review'
               OR NEW.workflow_status NOT IN ('approved', 'rejected')
               OR (NEW.workflow_status = 'approved'
                   AND NEW.dedup_status = 'exact_duplicate')
               OR (NEW.workflow_status = 'approved'
                   AND NEW.dedup_status = 'possible_duplicate'
                   AND btrim(COALESCE(NEW.review_notes, '')) = '') THEN
                RAISE EXCEPTION 'invalid Question candidate review transition'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF (NEW.reviewed_by, NEW.review_notes, NEW.reviewed_at)
              IS DISTINCT FROM (OLD.reviewed_by, OLD.review_notes, OLD.reviewed_at) THEN
            RAISE EXCEPTION 'Question candidate review metadata is immutable after decision'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;

    SELECT spec.semantic_duplicate_threshold, dimension.turn_index,
           dimension.parent_dimension_key
    INTO duplicate_threshold, dimension_turn, parent_dimension
    FROM knowledge_question_generation_specs AS spec
    JOIN knowledge_question_dimensions AS dimension
      ON dimension.job_id = spec.job_id
     AND dimension.project_id = spec.project_id
     AND dimension.campaign_id = spec.campaign_id
    WHERE spec.job_id = NEW.generated_by_job_id
      AND spec.project_id = NEW.project_id
      AND spec.campaign_id = NEW.campaign_id
      AND dimension.dimension_key = NEW.dimension_key
      AND spec.embedding_model_key = NEW.embedding_model_key;
    IF duplicate_threshold IS NULL OR dimension_turn <> NEW.turn_index
       OR NEW.query_text_hash <> encode(
            digest(convert_to(NEW.query_text, 'UTF8'), 'sha256'), 'hex'
       ) THEN
        RAISE EXCEPTION 'Question candidate differs from its generation dimension or text hash'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.parent_candidate_id IS NOT NULL THEN
        SELECT candidate.turn_index, candidate.dimension_key
        INTO parent_turn, parent_dimension_key
        FROM knowledge_question_candidates AS candidate
        WHERE candidate.id = NEW.parent_candidate_id
          AND candidate.generated_by_job_id = NEW.generated_by_job_id
          AND candidate.project_id = NEW.project_id
          AND candidate.campaign_id = NEW.campaign_id;
        IF NOT FOUND OR parent_turn >= NEW.turn_index
           OR parent_dimension_key IS DISTINCT FROM parent_dimension THEN
            RAISE EXCEPTION 'multi-turn Question candidate parent is outside its dimension chain'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.nearest_candidate_id IS NOT NULL THEN
        SELECT candidate.normalized_text_hash
        INTO nearest_normalized_text_hash
        FROM knowledge_question_candidates AS candidate
        WHERE candidate.id = NEW.nearest_candidate_id
          AND candidate.generated_by_job_id = NEW.generated_by_job_id
          AND candidate.project_id = NEW.project_id
          AND candidate.campaign_id = NEW.campaign_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'nearest Question candidate is outside the generation job'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF (NEW.dedup_status = 'unique' AND NEW.nearest_similarity IS NOT NULL
            AND NEW.nearest_similarity >= duplicate_threshold)
       OR (NEW.dedup_status = 'possible_duplicate' AND (
            NEW.nearest_similarity IS NULL
            OR NEW.nearest_similarity < duplicate_threshold
       ))
       OR (NEW.dedup_status = 'exact_duplicate' AND (
            NEW.nearest_candidate_id IS NULL
            OR NEW.nearest_similarity IS DISTINCT FROM 1.0000
            OR nearest_normalized_text_hash IS DISTINCT FROM NEW.normalized_text_hash
       )) THEN
        RAISE EXCEPTION 'Question candidate dedup result differs from its frozen threshold'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_question_set_item() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM knowledge_question_sets AS question_set
        JOIN knowledge_question_candidates AS candidate
          ON candidate.id = NEW.question_candidate_id
         AND candidate.generated_by_job_id = NEW.generated_by_job_id
         AND candidate.project_id = NEW.project_id
         AND candidate.campaign_id = NEW.campaign_id
        JOIN knowledge_question_dimensions AS dimension
          ON dimension.job_id = candidate.generated_by_job_id
         AND dimension.project_id = candidate.project_id
         AND dimension.campaign_id = candidate.campaign_id
         AND dimension.dimension_key = candidate.dimension_key
        WHERE question_set.id = NEW.question_set_id
          AND question_set.project_id = NEW.project_id
          AND question_set.campaign_id = NEW.campaign_id
          AND question_set.generated_by_job_id = NEW.generated_by_job_id
          AND question_set.status = 'draft'
          AND candidate.workflow_status = 'approved'
          AND candidate.dimension_key = NEW.dimension_key
          AND candidate.query_text = NEW.query_text_snapshot
          AND candidate.query_text_hash = NEW.query_text_hash
          AND candidate.normalized_text_hash = NEW.normalized_text_hash
          AND dimension.query_kind = NEW.query_kind_snapshot
          AND geo_question_candidate_source_lineage_hash(candidate.id)
                = NEW.source_lineage_hash
          AND geo_question_candidate_sources_current(candidate.id)
    ) THEN
        RAISE EXCEPTION 'QuestionSet item differs from its approved sourced candidate snapshot'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP INDEX knowledge_question_dimensions_coverage_idx;
DROP INDEX knowledge_question_candidate_revisions_latest_idx;
DROP INDEX knowledge_question_batches_progress_idx;

DROP TABLE knowledge_question_candidate_revisions;
DROP TABLE knowledge_question_generation_batches;

ALTER TABLE knowledge_question_generation_results
DROP CONSTRAINT knowledge_question_results_model_identity_check,
ADD CONSTRAINT knowledge_question_results_model_identity_check CHECK (
    (execution_backend IS NULL AND actual_model IS NULL)
    OR (
        execution_backend IN ('dify', 'native')
        AND actual_model IS NOT NULL
        AND btrim(actual_model) <> ''
    )
);

ALTER TABLE knowledge_question_set_items
DROP COLUMN funnel_snapshot,
DROP COLUMN topic_cluster_snapshot,
DROP COLUMN coverage_role_snapshot,
DROP COLUMN brand_scope_snapshot;

ALTER TABLE knowledge_question_dimensions
DROP CONSTRAINT knowledge_question_dimensions_coverage_shape_check,
DROP COLUMN planned_query_hash,
DROP COLUMN planned_query_text,
DROP COLUMN topic_cluster,
DROP COLUMN coverage_role;

ALTER TABLE knowledge_question_generation_specs
DROP CONSTRAINT knowledge_question_specs_product_fkey,
DROP CONSTRAINT knowledge_question_specs_coverage_shape_check,
DROP COLUMN product_name_snapshot,
DROP COLUMN product_category,
DROP COLUMN product_entity_id,
DROP COLUMN target_count,
DROP COLUMN coverage_profile_hash,
DROP COLUMN coverage_profile,
DROP COLUMN generation_mode;
