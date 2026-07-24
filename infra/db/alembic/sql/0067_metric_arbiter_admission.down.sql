REVOKE EXECUTE ON FUNCTION geo_admit_workflow_c_metric_arbiter_child(
    uuid, uuid, uuid, integer, text, uuid, jsonb
) FROM geo_worker;
DROP FUNCTION geo_admit_workflow_c_metric_arbiter_child(
    uuid, uuid, uuid, integer, text, uuid, jsonb
);
