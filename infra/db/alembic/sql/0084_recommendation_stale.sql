-- Preserve retired Facts as resolvable immutable evidence.  Their validity
-- flags change, which lets an approved Recommendation persist a stale
-- transition instead of failing resolution before the transition is stored.

ALTER FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    RENAME TO geo_resolve_recommendation_evidence_pre_0084;
REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence_pre_0084(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;

CREATE FUNCTION geo_resolve_recommendation_evidence(
    p_project_id uuid,
    p_kind text,
    p_resource_id text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE resolved jsonb;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RETURN NULL;
    END IF;

    IF p_kind = 'fact' THEN
        SELECT jsonb_build_object(
            'kind', 'fact',
            'project_id', fact.project_id::text,
            'resource_id', fact.id::text,
            'version', fact.statement_hash,
            'sha256', fact.statement_hash,
            'locator', jsonb_build_object('knowledge_fact_id', fact.id::text),
            'valid', fact.status = 'approved' AND fact.lifecycle_status = 'active',
            'approved', fact.status = 'approved',
            'retired', fact.lifecycle_status <> 'active',
            'summary', fact.statement,
            'summary_hash', encode(
                digest(convert_to(fact.statement, 'UTF8'), 'sha256'), 'hex'
            )
        ) INTO resolved
        FROM knowledge_fact_candidates AS fact
        WHERE fact.project_id = p_project_id
          AND fact.id::text = p_resource_id;
        RETURN resolved;
    END IF;

    RETURN geo_resolve_recommendation_evidence_pre_0084(
        p_project_id, p_kind, p_resource_id
    );
END;
$$;

REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    TO geo_app, geo_worker;

-- Only drafts that have not crossed the execution boundary may be blocked.
-- Started drafts keep their execution identity and must be handled by the
-- downstream workflow's own cancellation or compensation contract.
CREATE OR REPLACE FUNCTION geo_block_recommendation_drafts_on_stale() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF NEW.status IN ('stale', 'expired') THEN
        UPDATE recommendation_drafts
        SET status = CASE NEW.status
                WHEN 'stale' THEN 'blocked_source_stale'
                ELSE 'blocked_source_expired' END,
            blocked_at = NEW.updated_at,
            blocked_reason = NEW.status,
            draft_payload = draft_payload,
            draft_payload_hash = draft_payload_hash
        WHERE project_id = NEW.project_id
          AND recommendation_id = NEW.recommendation_id
          AND status = 'draft';
        UPDATE recommendation_outbox_messages
        SET status = 'cancelled',
            cancelled_at = NEW.updated_at,
            cancellation_reason = NEW.status
        WHERE project_id = NEW.project_id
          AND recommendation_id = NEW.recommendation_id
          AND status = 'pending';
    END IF;
    RETURN NULL;
END;
$$;
