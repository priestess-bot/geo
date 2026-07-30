REVOKE ALL ON FUNCTION geo_register_browser_sampling_runtime_option(
    uuid, uuid, uuid, uuid, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_register_browser_sampling_runtime_option(
    uuid, uuid, uuid, uuid, timestamptz
);
