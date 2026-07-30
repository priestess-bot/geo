DROP TRIGGER connector_durable_status_reconcile ON durable_jobs;
REVOKE ALL ON FUNCTION geo_reconcile_connector_durable_status()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_reconcile_connector_durable_status();
