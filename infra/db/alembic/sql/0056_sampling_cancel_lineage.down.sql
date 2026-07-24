REVOKE ALL ON FUNCTION geo_cancel_workflow_c_sampling_run_v2(
    uuid, uuid, text, text, timestamptz
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_cancel_workflow_c_sampling_run_v2(
    uuid, uuid, text, text, timestamptz
);
