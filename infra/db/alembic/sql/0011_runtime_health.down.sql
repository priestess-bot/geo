REVOKE ALL ON FUNCTION geo_worker_runtime_findings(
    text, text, integer, integer, integer, integer, integer, integer
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION geo_worker_record_runtime_heartbeat(text, text, text, text, text)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

DROP FUNCTION IF EXISTS geo_worker_runtime_findings(
    text, text, integer, integer, integer, integer, integer, integer
);
DROP FUNCTION IF EXISTS geo_worker_record_runtime_heartbeat(text, text, text, text, text);
DROP TABLE IF EXISTS runtime_service_heartbeats;
DROP INDEX IF EXISTS durable_jobs_runtime_terminal_idx;
