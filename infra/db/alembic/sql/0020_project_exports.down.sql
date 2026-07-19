DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM project_export_specs)
       OR EXISTS (SELECT 1 FROM project_export_artifacts)
       OR EXISTS (
            SELECT 1 FROM durable_jobs WHERE kind = 'project.export'
       ) THEN
        RAISE EXCEPTION 'cannot downgrade: project export jobs or artifacts exist'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS project_export_artifacts_immutable
ON project_export_artifacts;
DROP TRIGGER IF EXISTS project_export_artifact_contract_guard
ON project_export_artifacts;
DROP TRIGGER IF EXISTS project_export_specs_delete_guard
ON project_export_specs;
DROP TRIGGER IF EXISTS project_export_specs_immutable
ON project_export_specs;
DROP TRIGGER IF EXISTS project_export_spec_contract_guard
ON project_export_specs;
DROP TRIGGER IF EXISTS project_export_spec_kind
ON project_export_specs;
DROP FUNCTION IF EXISTS geo_assert_project_export_artifact();
DROP FUNCTION IF EXISTS geo_assert_project_export_spec();
DROP TABLE project_export_artifacts;
DROP TABLE project_export_specs;
