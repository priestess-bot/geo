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
                   AND NEW.dedup_status = 'exact_duplicate') THEN
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
