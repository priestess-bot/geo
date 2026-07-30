REVOKE ALL ON FUNCTION geo_enqueue_browser_capture_attempt(
    uuid, uuid, uuid, uuid, integer, uuid, uuid, uuid, text, text,
    timestamptz, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_enqueue_browser_capture_attempt(
    uuid, uuid, uuid, uuid, integer, uuid, uuid, uuid, text, text,
    timestamptz, timestamptz
);
DROP TABLE browser_capture_job_specs;
