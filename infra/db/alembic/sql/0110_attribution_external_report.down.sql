DELETE FROM external_data_approvals approval
USING external_data_reports report, external_data_snapshots snapshot
WHERE approval.report_id = report.id AND approval.project_id = report.project_id
  AND report.snapshot_id = snapshot.id AND report.project_id = snapshot.project_id
  AND snapshot.source_kind = 'attribution_snapshot';
DELETE FROM external_data_reports report
USING external_data_snapshots snapshot
WHERE report.snapshot_id = snapshot.id AND report.project_id = snapshot.project_id
  AND snapshot.source_kind = 'attribution_snapshot';
ALTER TABLE external_data_snapshots DISABLE TRIGGER external_data_snapshots_immutable;
DELETE FROM external_data_snapshots WHERE source_kind = 'attribution_snapshot';
ALTER TABLE external_data_snapshots ENABLE TRIGGER external_data_snapshots_immutable;

DROP INDEX external_data_snapshots_attribution_idx;
ALTER TABLE external_data_snapshots DROP CONSTRAINT external_data_snapshots_source_shape;
ALTER TABLE external_data_snapshots DROP CONSTRAINT external_data_snapshots_attribution_fkey;
ALTER TABLE external_data_snapshots DROP CONSTRAINT external_data_snapshots_source_kind_check;
ALTER TABLE external_data_snapshots ADD CONSTRAINT external_data_snapshots_source_kind_check
CHECK (source_kind IN (
    'gsc_connector', 'ga4_connector',
    'google_official_report', 'bing_official_report'
));
ALTER TABLE external_data_snapshots ADD CONSTRAINT external_data_snapshots_check1 CHECK (
    (source_kind IN ('gsc_connector', 'ga4_connector')
     AND connection_id IS NOT NULL AND scope_id IS NOT NULL
     AND sync_run_id IS NOT NULL AND projection_batch_id IS NOT NULL
     AND official_report_import_id IS NULL)
    OR
    (source_kind IN ('google_official_report', 'bing_official_report')
     AND connection_id IS NULL AND scope_id IS NULL
     AND sync_run_id IS NULL AND projection_batch_id IS NULL
     AND official_report_import_id IS NOT NULL)
);
ALTER TABLE external_data_snapshots DROP COLUMN attribution_snapshot_id;
