-- Both metric child terminal RPCs use RETURNS TABLE(aggregate_version ...),
-- which makes an unqualified aggregate_version reference ambiguous in PL/pgSQL.
-- Recompile the existing hardened definitions with the target table explicitly
-- qualified; retain every prior fence, RLS and privilege clause verbatim.
DO $$
DECLARE function_definition text;
BEGIN
    SELECT pg_get_functiondef(
        'geo_complete_workflow_c_metric_child(uuid,uuid,uuid,integer,text,text,uuid,text,uuid,text)'::regprocedure
    ) INTO function_definition;
    IF position('aggregate_version = aggregate_version + 1' IN function_definition) = 0 THEN
        RAISE EXCEPTION 'metric completion RPC does not match the expected 0032 definition';
    END IF;
    EXECUTE replace(
        function_definition,
        'aggregate_version = aggregate_version + 1',
        'aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1'
    );

    SELECT pg_get_functiondef(
        'geo_fail_workflow_c_metric_child(uuid,uuid,uuid,integer,text,text,text)'::regprocedure
    ) INTO function_definition;
    IF position('aggregate_version = aggregate_version + 1' IN function_definition) = 0 THEN
        RAISE EXCEPTION 'metric failure RPC does not match the expected 0032 definition';
    END IF;
    EXECUTE replace(
        function_definition,
        'aggregate_version = aggregate_version + 1',
        'aggregate_version = workflow_c_metric_judge_batches.aggregate_version + 1'
    );
END;
$$;
