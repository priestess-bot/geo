DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM placement_opportunities
        GROUP BY project_id, destination_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: destinations are used by multiple campaigns';
    END IF;
END $$;

ALTER TABLE placement_opportunities
DROP CONSTRAINT placement_opportunities_project_opportunity_ref_key;

ALTER TABLE placement_opportunities
DROP CONSTRAINT placement_opportunities_project_campaign_destination_key;

UPDATE placement_opportunities
SET opportunity_ref = 'destination:' || destination_id::text;

ALTER TABLE placement_opportunities
ADD CONSTRAINT placement_opportunities_project_id_opportunity_ref_key
UNIQUE (project_id, opportunity_ref);
