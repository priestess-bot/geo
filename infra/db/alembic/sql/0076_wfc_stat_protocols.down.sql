DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_statistical_protocol_versions) THEN
        RAISE EXCEPTION 'cannot downgrade governed Statistical Protocol state'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP FUNCTION geo_workflow_c_analysis_job_spec_is_valid(text, jsonb);
ALTER FUNCTION geo_workflow_c_analysis_job_spec_v1_is_valid(text, jsonb)
RENAME TO geo_workflow_c_analysis_job_spec_is_valid;

DROP FUNCTION geo_persist_workflow_c_drift_report_v2(
    uuid, uuid, uuid, integer, text, text, text, text, jsonb, timestamptz
);

DROP FUNCTION geo_transition_workflow_c_statistical_protocol(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
);
DROP FUNCTION geo_create_workflow_c_statistical_protocol(
    uuid, uuid, text, uuid, integer, uuid, text, jsonb, text, text, text, timestamptz
);
DROP TRIGGER workflow_c_statistical_protocol_receipts_immutable
ON workflow_c_statistical_protocol_command_receipts;
DROP TRIGGER workflow_c_statistical_protocol_change_guard
ON workflow_c_statistical_protocol_versions;
DROP FUNCTION geo_assert_workflow_c_statistical_protocol_change();
DROP FUNCTION geo_workflow_c_statistical_protocol_definition_is_valid(text, jsonb);
DROP TABLE workflow_c_statistical_protocol_command_receipts;
DROP TABLE workflow_c_statistical_protocol_versions;
