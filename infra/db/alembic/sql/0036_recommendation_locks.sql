-- Recommendation version rows are append-only and geo_app intentionally has
-- no UPDATE privilege.  The original trigger acquired FOR UPDATE merely to
-- read a predecessor, which therefore made every legitimate app insertion
-- fail.  Writers serialize one Recommendation with a transaction-scoped
-- advisory lock; this trigger keeps the predecessor and primary-key checks as
-- the database backstop for all callers.
CREATE OR REPLACE FUNCTION geo_assert_recommendation_workflow_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE previous recommendation_workflow_versions%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Recommendation workflow history is append-only'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.version = 1 THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Recommendation must start as draft version one'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT previous
    FROM recommendation_workflow_versions
    WHERE project_id = NEW.project_id AND recommendation_id = NEW.recommendation_id
      AND version = NEW.version - 1;
    IF NEW.created_by <> previous.created_by
       OR NEW.created_at <> previous.created_at THEN
        RAISE EXCEPTION 'Recommendation version lineage is not contiguous'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

-- The domain contract permits an insufficient-evidence Recommendation to make
-- only a Sampling Plan draft.  The original table check accidentally forbade
-- every draft for that type, so valid approved Recommendations could never be
-- persisted.  Keep no-change as the sole recommendation type without a draft.
ALTER TABLE recommendation_workflow_versions
    DROP CONSTRAINT recommendation_workflow_versions_check1,
    ADD CONSTRAINT recommendation_workflow_versions_draft_type_check CHECK (
        (recommendation_type = 'no_change' AND proposed_draft_kind IS NULL)
        OR (
            recommendation_type = 'insufficient_evidence'
            AND proposed_draft_kind = 'sampling_plan'
        )
        OR (
            recommendation_type NOT IN ('no_change', 'insufficient_evidence')
            AND proposed_draft_kind IS NOT NULL
        )
    );
