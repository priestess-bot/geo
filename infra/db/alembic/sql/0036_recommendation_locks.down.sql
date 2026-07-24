-- Restore the 0032 trigger implementation when rolling back this permission
-- compatibility fix.
CREATE OR REPLACE FUNCTION geo_assert_recommendation_workflow_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE previous recommendation_workflow_versions%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Recommendation workflow history is append-only'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO previous FROM recommendation_workflow_versions
    WHERE project_id = NEW.project_id AND recommendation_id = NEW.recommendation_id
    ORDER BY version DESC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        IF NEW.version <> 1 OR NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Recommendation must start as draft version one'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.version <> previous.version + 1
       OR NEW.created_by <> previous.created_by
       OR NEW.created_at <> previous.created_at THEN
        RAISE EXCEPTION 'Recommendation version lineage is not contiguous'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE recommendation_workflow_versions
    DROP CONSTRAINT recommendation_workflow_versions_draft_type_check,
    ADD CONSTRAINT recommendation_workflow_versions_check1 CHECK (
        (recommendation_type IN ('no_change', 'insufficient_evidence')
            AND proposed_draft_kind IS NULL)
        OR recommendation_type NOT IN ('no_change', 'insufficient_evidence')
    );
