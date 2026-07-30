DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM browser_surface_drift_events) THEN
        RAISE EXCEPTION 'cannot downgrade: Browser Surface drift evidence exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP FUNCTION geo_suspend_browser_surface_for_runtime_drift(uuid, uuid, uuid, text, timestamptz);
DROP TRIGGER browser_parser_drift_detect ON browser_parsed_observations;
DROP FUNCTION geo_detect_browser_parser_drift();
DROP TABLE browser_surface_drift_events;
ALTER TABLE browser_surface_releases DROP CONSTRAINT browser_surface_releases_suspension_check;
ALTER TABLE browser_surface_releases DROP COLUMN suspension_reason, DROP COLUMN suspended_at;
ALTER TABLE browser_surface_releases DROP CONSTRAINT browser_surface_releases_lifecycle_check;
ALTER TABLE browser_surface_releases DROP CONSTRAINT browser_surface_releases_status_check;
ALTER TABLE browser_surface_releases ADD CONSTRAINT browser_surface_releases_status_check
CHECK (status IN ('draft', 'approved', 'retired'));
ALTER TABLE browser_surface_releases
ADD CONSTRAINT browser_surface_releases_check CHECK (
    (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
    OR (status IN ('approved', 'retired') AND approved_by IS NOT NULL
        AND approved_at IS NOT NULL AND approved_by <> created_by)
);
