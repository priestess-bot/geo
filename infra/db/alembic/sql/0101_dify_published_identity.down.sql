DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM dify_workflow_releases
        WHERE registered_identity_source = 'runtime_enrollment'
    ) THEN
        RAISE EXCEPTION 'cannot downgrade 0101: runtime-enrolled Dify Releases would lose published graph identity'
            USING ERRCODE = '55000',
                  HINT = 'Keep 0101 installed or remove the runtime-enrolled Releases through an audited replacement migration.';
    END IF;
END;
$$;

DROP TRIGGER dify_workflow_snapshot_registered_identity_guard
ON dify_workflow_published_snapshots;
DROP FUNCTION geo_assert_dify_snapshot_registered_identity();
DROP TRIGGER dify_workflow_release_registered_identity_guard
ON dify_workflow_releases;
DROP FUNCTION geo_require_dify_release_registered_identity();

ALTER TABLE dify_workflow_releases
DROP CONSTRAINT dify_workflow_releases_registered_identity_shape,
DROP COLUMN registered_workflow_hash,
DROP COLUMN registered_snapshot_hash,
DROP COLUMN registered_identity_source;
