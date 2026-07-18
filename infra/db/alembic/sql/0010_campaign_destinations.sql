ALTER TABLE placement_opportunities
DROP CONSTRAINT placement_opportunities_project_id_opportunity_ref_key;

UPDATE placement_opportunities
SET opportunity_ref = 'campaign:' || campaign_id::text || ':destination:' || destination_id::text;

ALTER TABLE placement_opportunities
ADD CONSTRAINT placement_opportunities_project_campaign_destination_key
UNIQUE (project_id, campaign_id, destination_id);

ALTER TABLE placement_opportunities
ADD CONSTRAINT placement_opportunities_project_opportunity_ref_key
UNIQUE (project_id, opportunity_ref);
