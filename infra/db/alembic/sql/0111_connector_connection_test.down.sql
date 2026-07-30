DROP TRIGGER connector_connection_test_status_reconcile ON durable_jobs;
DROP FUNCTION geo_reconcile_connector_connection_test_status();
DROP FUNCTION geo_enqueue_connector_connection_test(
    uuid, uuid, uuid, integer, uuid, timestamptz
);
DROP TABLE connector_connection_test_specs;
DROP TABLE connector_connection_tests;
