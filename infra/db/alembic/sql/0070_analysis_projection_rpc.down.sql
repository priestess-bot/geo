REVOKE EXECUTE ON FUNCTION geo_persist_workflow_c_comparison_family(
    uuid, uuid, uuid, integer, text, text, text, text, integer, text, text,
    text, jsonb, timestamptz, jsonb
) FROM geo_worker;
REVOKE EXECUTE ON FUNCTION geo_persist_workflow_c_drift_report(
    uuid, uuid, uuid, integer, text, text, text, jsonb, timestamptz
) FROM geo_worker;

DROP FUNCTION geo_persist_workflow_c_comparison_family(
    uuid, uuid, uuid, integer, text, text, text, text, integer, text, text,
    text, jsonb, timestamptz, jsonb
);
DROP FUNCTION geo_persist_workflow_c_drift_report(
    uuid, uuid, uuid, integer, text, text, text, jsonb, timestamptz
);
DROP FUNCTION geo_workflow_c_python_canonical_text(jsonb);
