-- A reviewed revision supersedes the original possible-duplicate admission result.
-- The application deterministically re-checks the latest effective text and only
-- admits a revised candidate when it is unique. Original candidate evidence remains
-- immutable and continues to count when no revision exists.

CREATE OR REPLACE FUNCTION geo_assert_question_set_inventory() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_set_id uuid;
    question_set_record record;
    item_total integer;
    actual_dimension_count integer;
    actual_covered_count integer;
    actual_duplicate_count integer;
BEGIN
    target_set_id := COALESCE(
        (to_jsonb(NEW) ->> 'question_set_id')::uuid,
        (to_jsonb(NEW) ->> 'id')::uuid
    );
    SELECT * INTO question_set_record
    FROM knowledge_question_sets WHERE id = target_set_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT count(*) INTO actual_dimension_count
    FROM knowledge_question_dimensions
    WHERE job_id = question_set_record.generated_by_job_id;
    SELECT count(*), count(DISTINCT item.dimension_key),
           count(*) FILTER (
               WHERE candidate.dedup_status = 'possible_duplicate'
                 AND NOT EXISTS (
                     SELECT 1
                     FROM knowledge_question_candidate_revisions AS revision
                     WHERE revision.candidate_id = candidate.id
                       AND revision.project_id = candidate.project_id
                       AND revision.campaign_id = candidate.campaign_id
                 )
           )
    INTO item_total, actual_covered_count, actual_duplicate_count
    FROM knowledge_question_set_items AS item
    JOIN knowledge_question_candidates AS candidate
      ON candidate.id = item.question_candidate_id
    WHERE item.question_set_id = target_set_id;
    IF item_total = 0 OR actual_dimension_count = 0
       OR question_set_record.dimension_count <> actual_dimension_count
       OR question_set_record.covered_dimension_count <> actual_covered_count
       OR question_set_record.possible_duplicate_count <> actual_duplicate_count
       OR question_set_record.coverage_ratio <> round(
            actual_covered_count::numeric / actual_dimension_count, 4
       )
       OR question_set_record.duplicate_ratio <> round(
            actual_duplicate_count::numeric / item_total, 4
       ) THEN
        RAISE EXCEPTION 'QuestionSet measurements differ from immutable item inventory'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
