CREATE OR REPLACE FUNCTION geo_assert_package_version_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.workflow_status = 'approved' AND OLD.workflow_status <> 'approved' THEN
        IF NOT EXISTS (
            SELECT 1 FROM placement_reviews r
            WHERE r.package_version_id = NEW.id AND r.project_id = NEW.project_id
              AND r.decision = 'approved' AND r.claim_inventory_complete
              AND r.extracted_claim_support_confirmed AND r.score >= 85
        ) OR NOT EXISTS (
            SELECT 1 FROM placement_claims c
            WHERE c.package_version_id = NEW.id AND c.project_id = NEW.project_id
        ) OR EXISTS (
            SELECT 1 FROM placement_claims c
            WHERE c.package_version_id = NEW.id AND c.project_id = NEW.project_id
              AND c.claim_kind <> 'non_factual' AND c.support_status <> 'supported'
        ) THEN
            RAISE EXCEPTION 'approval requires a non-empty complete claim inventory and supported factual claims'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
