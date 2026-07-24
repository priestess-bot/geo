REVOKE EXECUTE ON FUNCTION geo_read_workflow_c_metric_parent_judges(
    uuid, uuid, uuid, integer, text, uuid
) FROM geo_worker;
DROP FUNCTION geo_read_workflow_c_metric_parent_judges(
    uuid, uuid, uuid, integer, text, uuid
);

REVOKE EXECUTE ON FUNCTION geo_read_workflow_c_metric_parent_batches(
    uuid, uuid, uuid, integer, text
) FROM geo_worker;
DROP FUNCTION geo_read_workflow_c_metric_parent_batches(
    uuid, uuid, uuid, integer, text
);
