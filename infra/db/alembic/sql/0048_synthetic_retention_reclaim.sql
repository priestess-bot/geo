-- The project-scoped claim RPC admits an already leased deletion only after
-- its supplied scheduler time has passed the stored expiry.  The previous
-- trigger repeated that condition against clock_timestamp(), which rejects a
-- deterministic reclaim before wall-clock time reaches the supplied time.
-- Guard the transition structurally instead: only the scoped claim RPC can
-- update this table, and it must rotate the token/fence and extend the lease.
CREATE OR REPLACE FUNCTION geo_assert_synthetic_artifact_outbox_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Synthetic artifact deletion records cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.id, OLD.project_id, OLD.artifact_id, OLD.artifact_generation,
        OLD.manifest_hash, OLD.reason, OLD.created_at)
       IS DISTINCT FROM
       (NEW.id, NEW.project_id, NEW.artifact_id, NEW.artifact_generation,
        NEW.manifest_hash, NEW.reason, NEW.created_at)
       OR NOT (
            (OLD.status IN ('pending', 'failed') AND NEW.status = 'leased'
                AND NEW.attempt_count = OLD.attempt_count + 1
                AND NEW.fencing_generation = OLD.fencing_generation + 1)
            OR (OLD.status = 'leased' AND NEW.status = 'leased'
                AND NEW.attempt_count = OLD.attempt_count + 1
                AND NEW.fencing_generation = OLD.fencing_generation + 1
                AND NEW.lease_token IS DISTINCT FROM OLD.lease_token
                AND NEW.lease_token IS NOT NULL
                AND btrim(coalesce(NEW.lease_owner, '')) <> ''
                AND NEW.lease_expires_at > OLD.lease_expires_at
                AND NEW.last_error_code IS NULL)
            OR (OLD.status = 'leased' AND NEW.status IN ('failed', 'completed')
                AND NEW.attempt_count = OLD.attempt_count
                AND NEW.fencing_generation = OLD.fencing_generation)
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact deletion transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;
