-- A legacy hash-only schema cannot represent two Projects with the same
-- frozen analytical output.  Refuse downgrade only when that information
-- would be discarded; otherwise restore the exact 0058 table and resolver
-- contracts.
DO $$
BEGIN
    IF EXISTS (
        SELECT snapshot_hash
          FROM workflow_c_semantic_metric_snapshots
         GROUP BY snapshot_hash
        HAVING count(*) > 1
    ) OR EXISTS (
        SELECT family_hash
          FROM workflow_c_comparison_families
         GROUP BY family_hash
        HAVING count(*) > 1
    ) OR EXISTS (
        SELECT report_hash
          FROM workflow_c_drift_reports
         GROUP BY report_hash
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION
            'cannot downgrade: Project-scoped analytical hash identities exist';
    END IF;
END;
$$;

REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
DROP FUNCTION geo_resolve_recommendation_evidence(uuid, text, text);
ALTER FUNCTION geo_resolve_recommendation_evidence_pre_0059(uuid, text, text)
    RENAME TO geo_resolve_recommendation_evidence;
REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    TO geo_app, geo_worker;

DROP POLICY project_scope ON workflow_c_semantic_metric_results;
CREATE POLICY project_scope ON workflow_c_semantic_metric_results
USING (EXISTS (
    SELECT 1 FROM workflow_c_semantic_metric_snapshots AS snapshot
    WHERE snapshot.snapshot_hash = workflow_c_semantic_metric_results.snapshot_hash
      AND snapshot.project_id = ANY(geo_current_project_ids())
)) WITH CHECK (EXISTS (
    SELECT 1 FROM workflow_c_semantic_metric_snapshots AS snapshot
    WHERE snapshot.snapshot_hash = workflow_c_semantic_metric_results.snapshot_hash
      AND snapshot.project_id = ANY(geo_current_project_ids())
));

ALTER TABLE workflow_c_semantic_metric_results
    DROP CONSTRAINT workflow_c_semantic_metric_results_snapshot_project_fkey,
    DROP CONSTRAINT workflow_c_semantic_metric_results_pkey;
ALTER TABLE workflow_c_semantic_metric_snapshots
    DROP CONSTRAINT workflow_c_semantic_metric_snapshots_pkey,
    ADD CONSTRAINT workflow_c_semantic_metric_snapshots_pkey PRIMARY KEY (snapshot_hash);
ALTER TABLE workflow_c_semantic_metric_results
    ADD CONSTRAINT workflow_c_semantic_metric_results_pkey PRIMARY KEY (snapshot_hash, metric_key),
    ADD CONSTRAINT workflow_c_semantic_metric_results_snapshot_hash_fkey
        FOREIGN KEY (snapshot_hash)
        REFERENCES workflow_c_semantic_metric_snapshots(snapshot_hash) ON DELETE CASCADE,
    DROP COLUMN project_id;

DROP POLICY project_scope ON workflow_c_comparison_results;
CREATE POLICY project_scope ON workflow_c_comparison_results
USING (EXISTS (
    SELECT 1 FROM workflow_c_comparison_families AS family
    WHERE family.family_hash = workflow_c_comparison_results.family_hash
      AND family.project_id = ANY(geo_current_project_ids())
)) WITH CHECK (EXISTS (
    SELECT 1 FROM workflow_c_comparison_families AS family
    WHERE family.family_hash = workflow_c_comparison_results.family_hash
      AND family.project_id = ANY(geo_current_project_ids())
));

ALTER TABLE workflow_c_comparison_results
    DROP CONSTRAINT workflow_c_comparison_results_family_project_fkey,
    DROP CONSTRAINT workflow_c_comparison_results_pkey;
ALTER TABLE workflow_c_comparison_families
    DROP CONSTRAINT workflow_c_comparison_families_pkey,
    ADD CONSTRAINT workflow_c_comparison_families_pkey PRIMARY KEY (family_hash);
ALTER TABLE workflow_c_comparison_results
    ADD CONSTRAINT workflow_c_comparison_results_pkey PRIMARY KEY (family_hash, comparison_id),
    ADD CONSTRAINT workflow_c_comparison_results_family_hash_fkey
        FOREIGN KEY (family_hash)
        REFERENCES workflow_c_comparison_families(family_hash) ON DELETE CASCADE,
    DROP COLUMN project_id;

ALTER TABLE workflow_c_drift_reports
    DROP CONSTRAINT workflow_c_drift_reports_pkey,
    ADD CONSTRAINT workflow_c_drift_reports_pkey PRIMARY KEY (report_hash);
