DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_surface_parse_results) THEN
        RAISE EXCEPTION 'cannot downgrade consumer surface parser results after evidence exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION geo_submit_workflow_c_surface_parsed_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz, jsonb
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_submit_workflow_c_surface_parsed_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz, jsonb
);

DROP TRIGGER workflow_c_surface_parse_immutable_guard
ON workflow_c_surface_parse_results;
DROP FUNCTION geo_assert_workflow_c_surface_parse_immutable();
DROP TABLE workflow_c_surface_parse_results;
