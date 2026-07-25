DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_analysis_input_manifests)
       OR EXISTS (SELECT 1 FROM workflow_c_metric_protocol_versions) THEN
        RAISE EXCEPTION 'cannot downgrade Metric Protocols after governed analysis state exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP FUNCTION geo_transition_workflow_c_metric_protocol(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
);
DROP FUNCTION geo_create_workflow_c_metric_protocol(
    uuid, uuid, uuid, integer, uuid, text, jsonb, text, text, text, timestamptz
);
DROP TRIGGER workflow_c_analysis_manifest_items_immutable
ON workflow_c_analysis_input_manifest_items;
DROP TRIGGER workflow_c_analysis_manifests_immutable
ON workflow_c_analysis_input_manifests;
DROP TRIGGER workflow_c_metric_protocol_receipts_immutable
ON workflow_c_metric_protocol_command_receipts;
DROP TRIGGER workflow_c_metric_protocol_change_guard
ON workflow_c_metric_protocol_versions;
DROP FUNCTION geo_assert_workflow_c_metric_protocol_change();
DROP TABLE workflow_c_analysis_input_manifest_items;
DROP TABLE workflow_c_analysis_input_manifests;
DROP TABLE workflow_c_metric_protocol_command_receipts;
DROP TABLE workflow_c_metric_protocol_versions;
