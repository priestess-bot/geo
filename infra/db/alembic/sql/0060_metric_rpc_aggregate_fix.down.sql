-- Restore the exact predecessor function source when rolling back this
-- compilation-only fix. The current qualified form is asserted first so an
-- unrelated function edit cannot be silently overwritten.
DO $$
DECLARE function_definition text;
BEGIN
    SELECT pg_get_functiondef(
        'geo_complete_workflow_c_metric_child(uuid,uuid,uuid,integer,text,text,uuid,text,uuid,text)'::regprocedure
    ) INTO function_definition;
    IF position(
        'aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1'
        IN function_definition
    ) = 0 THEN
        RAISE EXCEPTION 'metric completion RPC does not match the expected 0060 definition';
    END IF;
    EXECUTE replace(
        function_definition,
        'aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1',
        'aggregate_version = aggregate_version + 1'
    );

    SELECT pg_get_functiondef(
        'geo_fail_workflow_c_metric_child(uuid,uuid,uuid,integer,text,text,text)'::regprocedure
    ) INTO function_definition;
    IF position(
        'aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1'
        IN function_definition
    ) = 0 THEN
        RAISE EXCEPTION 'metric failure RPC does not match the expected 0060 definition';
    END IF;
    EXECUTE replace(
        function_definition,
        'aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1',
        'aggregate_version = aggregate_version + 1'
    );
END;
$$;
