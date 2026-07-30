ALTER TABLE runtime_service_heartbeats
DROP CONSTRAINT runtime_service_heartbeats_service_type_check;
ALTER TABLE runtime_service_heartbeats
ADD CONSTRAINT runtime_service_heartbeats_service_type_check CHECK (
    service_type IN (
        'task_worker', 'outbox_relay', 'style_browser_worker',
        'synthetic_artifact_maintenance_worker',
        'workflow_c_maintenance_worker', 'workflow_c_maintenance_scheduler',
        'recommendation_artifact_maintenance_worker',
        'recommendation_artifact_maintenance_scheduler',
        'connector_worker', 'browser_capture_worker'
    )
);

DO $$
DECLARE function_definition text;
DECLARE replacement text;
DECLARE old_contract text := 'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'', ''recommendation_artifact_maintenance_worker'', ''recommendation_artifact_maintenance_scheduler'')';
DECLARE new_contract text := 'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'', ''recommendation_artifact_maintenance_worker'', ''recommendation_artifact_maintenance_scheduler'', ''connector_worker'', ''browser_capture_worker'')';
BEGIN
    function_definition := pg_get_functiondef(
        'geo_worker_record_runtime_heartbeat(text,text,text,text,text)'::regprocedure
    );
    replacement := replace(function_definition, old_contract, new_contract);
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'External worker heartbeat contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;

    function_definition := pg_get_functiondef(
        'geo_worker_runtime_findings(text,text,integer,integer,integer,integer,integer,integer)'
            ::regprocedure
    );
    replacement := replace(function_definition, old_contract, new_contract);
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'External worker findings contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
END;
$$;
