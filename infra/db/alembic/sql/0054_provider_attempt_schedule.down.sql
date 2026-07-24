DROP FUNCTION IF EXISTS geo_schedule_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz, timestamptz
);

GRANT EXECUTE ON FUNCTION geo_enqueue_workflow_c_provider_sampling_attempt(
    uuid, uuid, text, text, uuid, uuid, integer, text, jsonb, text, timestamptz
) TO geo_app;
