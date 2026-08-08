DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM browser_surface_releases
         WHERE approved_by = created_by
    ) OR EXISTS (
        SELECT 1 FROM browser_profile_versions
         WHERE approved_by = created_by
    ) OR EXISTS (
        SELECT 1 FROM browser_egress_endpoints
         WHERE approved_by = created_by
    ) OR EXISTS (
        SELECT 1 FROM secret_versions
         WHERE activated_by = created_by
    ) THEN
        RAISE EXCEPTION 'cannot downgrade: one-owner Browser Capture configuration exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

ALTER TABLE secret_versions
DROP CONSTRAINT secret_versions_creator_approval_separation;
ALTER TABLE secret_versions
ADD CONSTRAINT secret_versions_creator_approval_separation CHECK (
    activated_by IS NULL OR activated_by <> created_by
);

ALTER TABLE browser_egress_endpoints
DROP CONSTRAINT browser_egress_endpoints_lifecycle_check;
ALTER TABLE browser_egress_endpoints
ADD CONSTRAINT browser_egress_endpoints_check CHECK (
    (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
    OR (status IN ('approved', 'disabled', 'revoked')
        AND approved_by IS NOT NULL AND approved_at IS NOT NULL
        AND approved_by <> created_by)
);

ALTER TABLE browser_profile_versions
DROP CONSTRAINT browser_profile_versions_lifecycle_check;
ALTER TABLE browser_profile_versions
ADD CONSTRAINT browser_profile_versions_check1 CHECK (
    (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
    OR (status IN ('approved', 'retired')
        AND approved_by IS NOT NULL AND approved_at IS NOT NULL
        AND approved_by <> created_by)
);

ALTER TABLE browser_surface_releases
DROP CONSTRAINT browser_surface_releases_lifecycle_check;
ALTER TABLE browser_surface_releases
ADD CONSTRAINT browser_surface_releases_lifecycle_check CHECK (
    (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
    OR (status IN ('approved', 'suspended', 'retired')
        AND approved_by IS NOT NULL AND approved_at IS NOT NULL
        AND approved_by <> created_by)
);
