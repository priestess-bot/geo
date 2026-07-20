CREATE OR REPLACE FUNCTION geo_protect_promoted_knowledge_fact() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM knowledge_fact_evidence_lineages AS lineage
        WHERE lineage.project_id = OLD.project_id
          AND lineage.knowledge_fact_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'promoted knowledge Facts are immutable' USING ERRCODE = '55000';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;
