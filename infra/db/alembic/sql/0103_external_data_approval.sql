CREATE TABLE external_data_snapshots (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN (
        'gsc_connector', 'ga4_connector',
        'google_official_report', 'bing_official_report'
    )),
    connection_id uuid,
    scope_id uuid,
    sync_run_id uuid,
    projection_batch_id uuid,
    official_report_import_id uuid,
    period_start date NOT NULL,
    period_end date NOT NULL,
    as_of timestamptz NOT NULL,
    freshness_status text NOT NULL CHECK (freshness_status IN ('fresh', 'stale', 'unknown')),
    schema_release text NOT NULL CHECK (btrim(schema_release) <> ''),
    adapter_release text NOT NULL CHECK (btrim(adapter_release) <> ''),
    row_count bigint NOT NULL CHECK (row_count >= 0),
    dataset_hash text NOT NULL CHECK (dataset_hash ~ '^[0-9a-f]{64}$'),
    customer_whitelist_version text NOT NULL CHECK (btrim(customer_whitelist_version) <> ''),
    customer_payload jsonb NOT NULL CHECK (jsonb_typeof(customer_payload) = 'object'),
    customer_payload_hash text NOT NULL CHECK (customer_payload_hash ~ '^[0-9a-f]{64}$'),
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'internal_only' CHECK (status = 'internal_only'),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, snapshot_hash),
    FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id),
    FOREIGN KEY (connection_id, project_id) REFERENCES connector_connections(id, project_id),
    FOREIGN KEY (scope_id, project_id) REFERENCES connector_scopes(id, project_id),
    FOREIGN KEY (sync_run_id, project_id) REFERENCES connector_sync_runs(id, project_id),
    FOREIGN KEY (projection_batch_id, project_id)
        REFERENCES connector_projection_batches(id, project_id),
    FOREIGN KEY (official_report_import_id, project_id, campaign_id)
        REFERENCES monitoring_official_report_imports(id, project_id, campaign_id),
    CHECK (period_end >= period_start),
    CHECK (
        (source_kind IN ('gsc_connector', 'ga4_connector')
         AND connection_id IS NOT NULL AND scope_id IS NOT NULL
         AND sync_run_id IS NOT NULL AND projection_batch_id IS NOT NULL
         AND official_report_import_id IS NULL)
        OR
        (source_kind IN ('google_official_report', 'bing_official_report')
         AND connection_id IS NULL AND scope_id IS NULL
         AND sync_run_id IS NULL AND projection_batch_id IS NULL
         AND official_report_import_id IS NOT NULL)
    )
);

CREATE TABLE external_data_reports (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    snapshot_id uuid NOT NULL,
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    partition_key text NOT NULL CHECK (btrim(partition_key) <> ''),
    title text NOT NULL CHECK (btrim(title) <> ''),
    summary text NOT NULL,
    approval_policy_version text NOT NULL CHECK (btrim(approval_policy_version) <> ''),
    approval_rubric_version text NOT NULL CHECK (btrim(approval_rubric_version) <> ''),
    customer_schema_version text NOT NULL CHECK (btrim(customer_schema_version) <> ''),
    status text NOT NULL CHECK (status IN (
        'draft', 'in_review', 'approved', 'rejected',
        'stale', 'superseded', 'revoked'
    )),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    submitted_at timestamptz,
    approved_by uuid REFERENCES identities(id),
    approved_at timestamptz,
    terminal_reason text,
    UNIQUE (id, project_id),
    UNIQUE (project_id, snapshot_id),
    FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id),
    FOREIGN KEY (snapshot_id, project_id) REFERENCES external_data_snapshots(id, project_id),
    CHECK (
        (status = 'draft' AND submitted_at IS NULL AND approved_by IS NULL AND approved_at IS NULL)
        OR (status IN ('in_review', 'rejected') AND submitted_at IS NOT NULL
            AND approved_by IS NULL AND approved_at IS NULL)
        OR (status IN ('approved', 'stale', 'superseded', 'revoked')
            AND submitted_at IS NOT NULL AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
    )
);

CREATE TABLE external_data_approvals (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    report_id uuid NOT NULL,
    snapshot_id uuid NOT NULL,
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    decision text NOT NULL CHECK (decision IN ('approved', 'rejected', 'stale', 'revoked')),
    actor_id uuid NOT NULL REFERENCES identities(id),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    review_evidence jsonb NOT NULL CHECK (jsonb_typeof(review_evidence) = 'object'),
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    decided_at timestamptz NOT NULL,
    UNIQUE (project_id, idempotency_key),
    FOREIGN KEY (report_id, project_id) REFERENCES external_data_reports(id, project_id),
    FOREIGN KEY (snapshot_id, project_id) REFERENCES external_data_snapshots(id, project_id)
);

CREATE FUNCTION geo_external_data_snapshot_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'External Data Snapshot is immutable' USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_invalidate_external_data_report(
    p_project_id uuid,
    p_report_id uuid,
    p_snapshot_hash text,
    p_decision text,
    p_actor_id uuid,
    p_reason text,
    p_evidence jsonb,
    p_idempotency_key text
) RETURNS external_data_reports
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE report external_data_reports%ROWTYPE;
DECLARE receipt external_data_approvals%ROWTYPE;
DECLARE now_at timestamptz := clock_timestamp();
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_report_id IS NULL OR p_actor_id IS NULL
       OR p_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_decision NOT IN ('stale', 'revoked')
       OR btrim(coalesce(p_reason, '')) = ''
       OR jsonb_typeof(p_evidence) <> 'object'
       OR btrim(coalesce(p_idempotency_key, '')) = '' THEN
        RAISE EXCEPTION 'External Data invalidation input is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO receipt FROM external_data_approvals
     WHERE project_id = p_project_id AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF receipt.report_id <> p_report_id OR receipt.snapshot_hash <> p_snapshot_hash
           OR receipt.decision <> p_decision OR receipt.actor_id <> p_actor_id THEN
            RAISE EXCEPTION 'External Data invalidation idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO report FROM external_data_reports
         WHERE project_id = p_project_id AND id = p_report_id;
        RETURN report;
    END IF;
    SELECT * INTO report FROM external_data_reports
     WHERE project_id = p_project_id AND id = p_report_id FOR UPDATE;
    IF NOT FOUND OR report.status <> 'approved'
       OR report.snapshot_hash <> p_snapshot_hash THEN
        RAISE EXCEPTION 'External Data report is not approved' USING ERRCODE = '40001';
    END IF;
    UPDATE external_data_reports
       SET status = p_decision, version = version + 1, terminal_reason = p_reason
     WHERE project_id = p_project_id AND id = p_report_id
     RETURNING * INTO report;
    INSERT INTO external_data_approvals(
        id, project_id, report_id, snapshot_id, snapshot_hash, decision,
        actor_id, reason, review_evidence, idempotency_key, decided_at
    ) VALUES (
        gen_random_uuid(), p_project_id, report.id, report.snapshot_id,
        report.snapshot_hash, p_decision, p_actor_id, p_reason,
        p_evidence, p_idempotency_key, now_at
    );
    RETURN report;
END;
$$;
CREATE TRIGGER external_data_snapshots_immutable
BEFORE UPDATE OR DELETE ON external_data_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_external_data_snapshot_immutable();

CREATE FUNCTION geo_external_data_approval_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'External Data Approval is append-only' USING ERRCODE = '55000';
END;
$$;
CREATE TRIGGER external_data_approvals_immutable
BEFORE UPDATE OR DELETE ON external_data_approvals
FOR EACH ROW EXECUTE FUNCTION geo_external_data_approval_immutable();

CREATE FUNCTION geo_decide_external_data_report(
    p_project_id uuid,
    p_report_id uuid,
    p_snapshot_hash text,
    p_decision text,
    p_actor_id uuid,
    p_reason text,
    p_review_evidence jsonb,
    p_idempotency_key text
) RETURNS external_data_reports
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE report external_data_reports%ROWTYPE;
DECLARE receipt external_data_approvals%ROWTYPE;
DECLARE now_at timestamptz := clock_timestamp();
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_report_id IS NULL OR p_actor_id IS NULL
       OR p_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_decision NOT IN ('approved', 'rejected')
       OR btrim(coalesce(p_reason, '')) = ''
       OR jsonb_typeof(p_review_evidence) <> 'object'
       OR btrim(coalesce(p_idempotency_key, '')) = '' THEN
        RAISE EXCEPTION 'External Data approval input is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO receipt FROM external_data_approvals
     WHERE project_id = p_project_id AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF receipt.report_id <> p_report_id OR receipt.snapshot_hash <> p_snapshot_hash
           OR receipt.decision <> p_decision OR receipt.actor_id <> p_actor_id THEN
            RAISE EXCEPTION 'External Data approval idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO report FROM external_data_reports
         WHERE project_id = p_project_id AND id = p_report_id;
        RETURN report;
    END IF;
    SELECT * INTO report FROM external_data_reports
     WHERE project_id = p_project_id AND id = p_report_id FOR UPDATE;
    IF NOT FOUND OR report.status <> 'in_review'
       OR report.snapshot_hash <> p_snapshot_hash THEN
        RAISE EXCEPTION 'External Data report is not reviewable' USING ERRCODE = '40001';
    END IF;
    IF report.created_by = p_actor_id THEN
        RAISE EXCEPTION 'External Data report creator cannot approve it'
            USING ERRCODE = '42501';
    END IF;
    IF p_decision = 'approved' THEN
        UPDATE external_data_reports
           SET status = 'superseded', version = version + 1,
               terminal_reason = 'new_approved_report'
         WHERE project_id = p_project_id AND campaign_id = report.campaign_id
           AND partition_key = report.partition_key AND status = 'approved'
           AND id <> report.id;
        UPDATE external_data_reports
           SET status = 'approved', version = version + 1,
               approved_by = p_actor_id, approved_at = now_at
         WHERE project_id = p_project_id AND id = report.id
         RETURNING * INTO report;
    ELSE
        UPDATE external_data_reports
           SET status = 'rejected', version = version + 1,
               terminal_reason = p_reason
         WHERE project_id = p_project_id AND id = report.id
         RETURNING * INTO report;
    END IF;
    INSERT INTO external_data_approvals(
        id, project_id, report_id, snapshot_id, snapshot_hash, decision,
        actor_id, reason, review_evidence, idempotency_key, decided_at
    ) VALUES (
        gen_random_uuid(), p_project_id, report.id, report.snapshot_id,
        report.snapshot_hash, p_decision, p_actor_id, p_reason,
        p_review_evidence, p_idempotency_key, now_at
    );
    RETURN report;
END;
$$;

CREATE VIEW external_data_customer_latest WITH (
    security_barrier = true,
    security_invoker = true
) AS
SELECT DISTINCT ON (project_id, campaign_id, partition_key)
       id, project_id, campaign_id, snapshot_id, partition_key, title, summary,
       customer_schema_version, approved_at
  FROM external_data_reports
 WHERE status = 'approved'
 ORDER BY project_id, campaign_id, partition_key, approved_at DESC, id DESC;

ALTER TABLE external_data_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_data_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON external_data_snapshots
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
ALTER TABLE external_data_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_data_reports FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON external_data_reports
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
ALTER TABLE external_data_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_data_approvals FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON external_data_approvals
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON external_data_snapshots, external_data_reports,
    external_data_approvals FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON external_data_snapshots, external_data_reports,
    external_data_approvals TO geo_app;
GRANT UPDATE (status, version, submitted_at, terminal_reason)
    ON external_data_reports TO geo_app;
GRANT SELECT ON external_data_snapshots, external_data_reports,
    external_data_approvals TO geo_worker, geo_readonly;
REVOKE ALL ON external_data_customer_latest FROM PUBLIC;
GRANT SELECT ON external_data_customer_latest TO geo_app, geo_readonly;
REVOKE ALL ON FUNCTION geo_decide_external_data_report(
    uuid, uuid, text, text, uuid, text, jsonb, text
) FROM PUBLIC, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_decide_external_data_report(
    uuid, uuid, text, text, uuid, text, jsonb, text
) TO geo_app;
REVOKE ALL ON FUNCTION geo_invalidate_external_data_report(
    uuid, uuid, text, text, uuid, text, jsonb, text
) FROM PUBLIC, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_invalidate_external_data_report(
    uuid, uuid, text, text, uuid, text, jsonb, text
) TO geo_app;
