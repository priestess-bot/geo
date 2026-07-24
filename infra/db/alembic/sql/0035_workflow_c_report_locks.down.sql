-- Restore the 0032 trigger implementation when rolling back this permission
-- compatibility fix.
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
      AND version = NEW.version - 1
    FOR SHARE;
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
    RETURN NEW;
END;
$$;
