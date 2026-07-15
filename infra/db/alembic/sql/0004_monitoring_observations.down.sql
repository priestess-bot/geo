DROP TABLE IF EXISTS monitoring_reports CASCADE;
DROP TABLE IF EXISTS monitoring_metric_snapshots CASCADE;
DROP TABLE IF EXISTS monitoring_observation_citations CASCADE;
DROP TABLE IF EXISTS monitoring_observations CASCADE;
DROP TABLE IF EXISTS monitoring_protocol_queries CASCADE;
DROP TABLE IF EXISTS monitoring_query_suggestions CASCADE;
DROP TABLE IF EXISTS monitoring_protocols CASCADE;
ALTER TABLE geo_campaigns
    DROP CONSTRAINT IF EXISTS geo_campaigns_id_market_project_key;
DROP FUNCTION IF EXISTS geo_protect_monitoring_report();
DROP FUNCTION IF EXISTS geo_assert_monitoring_observation_slot();
DROP FUNCTION IF EXISTS geo_protect_monitoring_protocol_child();
DROP FUNCTION IF EXISTS geo_protect_monitoring_protocol();
