DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM workflow_c_report_command_receipts) THEN
        RAISE EXCEPTION 'cannot downgrade after Workflow C report command receipts exist'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER workflow_c_report_command_receipts_immutable
ON workflow_c_report_command_receipts;
DROP TABLE workflow_c_report_command_receipts;
