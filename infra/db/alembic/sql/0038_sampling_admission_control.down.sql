DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM workflow_c_sampling_admission_policies
         WHERE status NOT IN ('draft', 'approved')
    ) THEN
        RAISE EXCEPTION 'cannot downgrade sampling admission control with new lifecycle states'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION
    geo_create_workflow_c_sampling_admission_policy(
        uuid, uuid, text, text, uuid, text, text, text, text, text, text, text,
        text, jsonb, timestamptz, integer, integer, integer, integer, text,
        timestamptz, jsonb
    ),
    geo_transition_workflow_c_sampling_admission_policy(
        uuid, uuid, integer, text, text, text, text, text, timestamptz
    )
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_transition_workflow_c_sampling_admission_policy(
    uuid, uuid, integer, text, text, text, text, text, timestamptz
);
DROP FUNCTION geo_create_workflow_c_sampling_admission_policy(
    uuid, uuid, text, text, uuid, text, text, text, text, text, text, text,
    text, jsonb, timestamptz, integer, integer, integer, integer, text,
    timestamptz, jsonb
);
DROP TRIGGER workflow_c_sampling_admission_change_guard
ON workflow_c_sampling_admission_policies;
DROP FUNCTION geo_assert_workflow_c_sampling_admission_change();

DROP POLICY project_scope ON workflow_c_sampling_runtime_options;
ALTER TABLE workflow_c_sampling_runtime_options DISABLE ROW LEVEL SECURITY;
DROP TABLE workflow_c_sampling_runtime_options;

ALTER TABLE workflow_c_sampling_admission_policies
    DROP CONSTRAINT workflow_c_sampling_admission_policies_lifecycle_check,
    DROP CONSTRAINT workflow_c_sampling_admission_policies_location_evidence_hash_check,
    DROP CONSTRAINT workflow_c_sampling_admission_policies_location_control_check,
    DROP CONSTRAINT workflow_c_sampling_admission_policies_capture_method_check,
    DROP CONSTRAINT workflow_c_sampling_admission_policies_purposes_check,
    DROP CONSTRAINT workflow_c_sampling_admission_policies_status_check,
    ADD CONSTRAINT workflow_c_sampling_admission_policies_status_check CHECK (
        status IN ('draft', 'approved', 'retired')
    ),
    DROP COLUMN revocation_reason,
    DROP COLUMN revoked_at,
    DROP COLUMN revoked_by,
    DROP COLUMN decision_reason,
    DROP COLUMN decided_at,
    DROP COLUMN decided_by,
    DROP COLUMN submitted_at,
    DROP COLUMN submitted_by,
    DROP COLUMN authorized_purposes,
    DROP COLUMN created_by,
    DROP COLUMN authorization_reference,
    DROP COLUMN location_evidence_hash,
    DROP COLUMN location_control,
    DROP COLUMN adapter_release,
    DROP COLUMN capture_method,
    DROP COLUMN platform;

REVOKE ALL ON workflow_c_sampling_admission_policies, workflow_c_command_ledger
FROM geo_app;
GRANT SELECT, INSERT ON workflow_c_sampling_admission_policies, workflow_c_command_ledger
TO geo_app;
