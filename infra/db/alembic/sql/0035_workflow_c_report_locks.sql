-- Workflow C report lifecycle rows are append-only.  The predecessor lookup in
-- the original trigger used FOR SHARE, which requires UPDATE-like privilege from
-- the inserting App role.  Application writers serialize a report with an
-- xact-scoped advisory lock; the primary key and predecessor check remain the
-- database backstop for every caller.
CREATE OR REPLACE FUNCTION geo_assert_workflow_c_report_snapshot_version_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE predecessor workflow_c_report_snapshot_versions%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Workflow C report snapshot versions are append-only'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.version = 1 THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'Workflow C report snapshot version one must be draft'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT predecessor
    FROM workflow_c_report_snapshot_versions
    WHERE project_id = NEW.project_id AND report_id = NEW.report_id
      AND version = NEW.version - 1;
    IF (NEW.campaign_id, NEW.monitoring_report_id, NEW.monitoring_report_hash,
        NEW.semantic_snapshot_hash, NEW.source_kind, NEW.approved_safe_payload,
        NEW.approved_safe_payload_hash)
       IS DISTINCT FROM
       (predecessor.campaign_id, predecessor.monitoring_report_id,
        predecessor.monitoring_report_hash, predecessor.semantic_snapshot_hash,
        predecessor.source_kind, predecessor.approved_safe_payload,
        predecessor.approved_safe_payload_hash)
       OR NOT (
           (predecessor.status = 'draft' AND NEW.status = 'in_review')
        OR (predecessor.status = 'in_review' AND NEW.status IN ('approved', 'revoked'))
        OR (predecessor.status = 'approved' AND NEW.status IN ('stale', 'superseded', 'revoked'))
       ) THEN
        RAISE EXCEPTION 'Workflow C report snapshot status or immutable lineage transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'approved' AND NOT EXISTS (
        SELECT 1
        FROM monitoring_reports AS report
        JOIN workflow_c_semantic_metric_snapshots AS metric
          ON metric.project_id = report.project_id
         AND metric.snapshot_hash = NEW.semantic_snapshot_hash
        WHERE report.project_id = NEW.project_id
          AND report.campaign_id = NEW.campaign_id
          AND report.id = NEW.monitoring_report_id
          AND report.report_hash = NEW.monitoring_report_hash
          AND metric.evidence_status = 'complete'
          AND metric.approved_at IS NOT NULL
          AND NOT metric.test_only AND NOT metric.synthetic
          AND metric.capture_method = NEW.source_kind
    ) THEN
        RAISE EXCEPTION 'Workflow C approved report source is not Customer eligible'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
