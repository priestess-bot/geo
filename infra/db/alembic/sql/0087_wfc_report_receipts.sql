CREATE TABLE workflow_c_report_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    report_id uuid NOT NULL,
    command_scope text NOT NULL CHECK (command_scope IN (
        'create', 'submit', 'approve', 'stale', 'supersede', 'revoke'
    )),
    idempotency_key_hash text NOT NULL CHECK (
        idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    result_version integer NOT NULL CHECK (result_version > 0),
    result_version_hash text NOT NULL CHECK (
        result_version_hash ~ '^[0-9a-f]{64}$'
    ),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, command_scope, idempotency_key_hash),
    FOREIGN KEY (project_id, report_id, result_version)
        REFERENCES workflow_c_report_snapshot_versions(project_id, report_id, version)
);

CREATE INDEX workflow_c_report_command_receipts_result_idx
ON workflow_c_report_command_receipts(project_id, report_id, result_version);

CREATE TRIGGER workflow_c_report_command_receipts_immutable
BEFORE UPDATE OR DELETE ON workflow_c_report_command_receipts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

ALTER TABLE workflow_c_report_command_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_report_command_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_report_command_receipts
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON workflow_c_report_command_receipts
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON workflow_c_report_command_receipts TO geo_app;
GRANT SELECT ON workflow_c_report_command_receipts TO geo_worker;
