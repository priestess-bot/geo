REVOKE EXECUTE ON FUNCTION geo_complete_workflow_c_metric_child(
    uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text, jsonb
) FROM geo_worker;
DROP FUNCTION geo_complete_workflow_c_metric_child(
    uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text, jsonb
);

DROP TRIGGER workflow_c_metric_child_output_projections_change_guard
ON workflow_c_metric_child_output_projections;
DROP FUNCTION geo_assert_workflow_c_metric_child_output_projection_change();
DROP TABLE workflow_c_metric_child_output_projections;
