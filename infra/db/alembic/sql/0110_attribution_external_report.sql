ALTER TABLE external_data_snapshots
    ADD COLUMN attribution_snapshot_id uuid;

ALTER TABLE external_data_snapshots
    ADD CONSTRAINT external_data_snapshots_attribution_fkey
    FOREIGN KEY (attribution_snapshot_id, project_id)
    REFERENCES attribution_snapshots(id, project_id);

ALTER TABLE external_data_snapshots
    DROP CONSTRAINT external_data_snapshots_source_kind_check;
ALTER TABLE external_data_snapshots
    ADD CONSTRAINT external_data_snapshots_source_kind_check CHECK (source_kind IN (
        'gsc_connector', 'ga4_connector',
        'google_official_report', 'bing_official_report',
        'attribution_snapshot'
    ));

ALTER TABLE external_data_snapshots
    DROP CONSTRAINT external_data_snapshots_check1;
ALTER TABLE external_data_snapshots
    ADD CONSTRAINT external_data_snapshots_source_shape CHECK (
        (source_kind IN ('gsc_connector', 'ga4_connector')
         AND connection_id IS NOT NULL AND scope_id IS NOT NULL
         AND sync_run_id IS NOT NULL AND projection_batch_id IS NOT NULL
         AND official_report_import_id IS NULL AND attribution_snapshot_id IS NULL)
        OR
        (source_kind IN ('google_official_report', 'bing_official_report')
         AND connection_id IS NULL AND scope_id IS NULL
         AND sync_run_id IS NULL AND projection_batch_id IS NULL
         AND official_report_import_id IS NOT NULL AND attribution_snapshot_id IS NULL)
        OR
        (source_kind = 'attribution_snapshot'
         AND connection_id IS NULL AND scope_id IS NULL
         AND sync_run_id IS NULL AND projection_batch_id IS NULL
         AND official_report_import_id IS NULL AND attribution_snapshot_id IS NOT NULL)
    );

CREATE INDEX external_data_snapshots_attribution_idx
ON external_data_snapshots(project_id, attribution_snapshot_id)
WHERE attribution_snapshot_id IS NOT NULL;
