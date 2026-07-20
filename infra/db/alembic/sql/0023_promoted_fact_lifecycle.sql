CREATE OR REPLACE FUNCTION geo_protect_promoted_knowledge_fact() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM knowledge_fact_evidence_lineages AS lineage
        WHERE lineage.project_id = OLD.project_id
          AND lineage.knowledge_fact_id = OLD.id
    ) THEN
        IF TG_OP = 'UPDATE'
           AND OLD.lifecycle_status = 'active'
           AND NEW.lifecycle_status IN ('superseded', 'withdrawn')
           AND (to_jsonb(NEW) - ARRAY['lifecycle_status', 'updated_at']) =
               (to_jsonb(OLD) - ARRAY['lifecycle_status', 'updated_at']) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION
            'promoted knowledge Facts only allow active lifecycle retirement'
            USING ERRCODE = '55000';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;
