DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM workflow_c_job_specs
         WHERE kind = 'workflow_c.analysis.semantic_metrics'
           AND spec_payload->'schema_version' = '2'::jsonb
    ) THEN
        RAISE EXCEPTION 'cannot downgrade semantic Job v2 after admitted work exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP FUNCTION geo_enqueue_workflow_c_semantic_metric_job_v2(
    uuid, uuid, text, uuid, integer, text, uuid, text, text, text, text,
    text, timestamptz, jsonb, text, jsonb, text, integer
);

ALTER TABLE workflow_c_job_specs
DROP CONSTRAINT workflow_c_job_specs_check;

ALTER TABLE workflow_c_job_specs
ADD CONSTRAINT workflow_c_job_specs_check CHECK (
    jsonb_typeof(spec_payload) = 'object'
    AND spec_payload->'schema_version' = '1'::jsonb
    AND spec_payload->>'kind' = kind
    AND geo_workflow_c_job_spec_payload_is_safe(spec_payload)
);
