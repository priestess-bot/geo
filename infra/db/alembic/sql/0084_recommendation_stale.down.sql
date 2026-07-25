DROP FUNCTION geo_resolve_recommendation_evidence(uuid, text, text);
ALTER FUNCTION geo_resolve_recommendation_evidence_pre_0084(uuid, text, text)
    RENAME TO geo_resolve_recommendation_evidence;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    TO geo_app, geo_worker;

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
          AND status IN ('draft', 'started');
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
