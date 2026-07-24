DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_alert_dispositions) THEN
        RAISE EXCEPTION 'cannot downgrade alert control after dispositions exist'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION geo_transition_workflow_c_alert(
    uuid, uuid, integer, text, text, jsonb, text, text, text, timestamptz,
    timestamptz, jsonb
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_transition_workflow_c_alert(
    uuid, uuid, integer, text, text, jsonb, text, text, text, timestamptz,
    timestamptz, jsonb
);

GRANT SELECT, INSERT ON
    workflow_c_alerts, workflow_c_alert_dispositions, workflow_c_alert_notifications
TO geo_app;
