REVOKE EXECUTE ON FUNCTION geo_persist_workflow_c_semantic_metric_snapshot(
    uuid, uuid, uuid, integer, text, uuid, text, text, text, text,
    text, numeric, boolean, boolean, jsonb, timestamptz, jsonb
) FROM geo_worker;
DROP FUNCTION geo_persist_workflow_c_semantic_metric_snapshot(
    uuid, uuid, uuid, integer, text, uuid, text, text, text, text,
    text, numeric, boolean, boolean, jsonb, timestamptz, jsonb
);
