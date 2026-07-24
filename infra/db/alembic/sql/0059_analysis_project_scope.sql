-- Analytical hashes freeze calculation inputs; they are not global tenant
-- identities.  Retain content hashes for lineage while scoping every persisted
-- projection and child result by its owning Project.

ALTER TABLE workflow_c_semantic_metric_results
    ADD COLUMN project_id uuid;

UPDATE workflow_c_semantic_metric_results AS result
   SET project_id = snapshot.project_id
  FROM workflow_c_semantic_metric_snapshots AS snapshot
 WHERE snapshot.snapshot_hash = result.snapshot_hash;

ALTER TABLE workflow_c_semantic_metric_results
    ALTER COLUMN project_id SET NOT NULL,
    DROP CONSTRAINT workflow_c_semantic_metric_results_snapshot_hash_fkey,
    DROP CONSTRAINT workflow_c_semantic_metric_results_pkey;

ALTER TABLE workflow_c_semantic_metric_snapshots
    DROP CONSTRAINT workflow_c_semantic_metric_snapshots_pkey,
    ADD CONSTRAINT workflow_c_semantic_metric_snapshots_pkey
        PRIMARY KEY (project_id, snapshot_hash);

ALTER TABLE workflow_c_semantic_metric_results
    ADD CONSTRAINT workflow_c_semantic_metric_results_pkey
        PRIMARY KEY (project_id, snapshot_hash, metric_key),
    ADD CONSTRAINT workflow_c_semantic_metric_results_snapshot_project_fkey
        FOREIGN KEY (snapshot_hash, project_id)
        REFERENCES workflow_c_semantic_metric_snapshots(snapshot_hash, project_id)
        ON DELETE CASCADE;

DROP POLICY project_scope ON workflow_c_semantic_metric_results;
CREATE POLICY project_scope ON workflow_c_semantic_metric_results
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE workflow_c_comparison_results
    ADD COLUMN project_id uuid;

UPDATE workflow_c_comparison_results AS result
   SET project_id = family.project_id
  FROM workflow_c_comparison_families AS family
 WHERE family.family_hash = result.family_hash;

ALTER TABLE workflow_c_comparison_results
    ALTER COLUMN project_id SET NOT NULL,
    DROP CONSTRAINT workflow_c_comparison_results_family_hash_fkey,
    DROP CONSTRAINT workflow_c_comparison_results_pkey;

ALTER TABLE workflow_c_comparison_families
    DROP CONSTRAINT workflow_c_comparison_families_pkey,
    ADD CONSTRAINT workflow_c_comparison_families_pkey
        PRIMARY KEY (project_id, family_hash);

ALTER TABLE workflow_c_comparison_results
    ADD CONSTRAINT workflow_c_comparison_results_pkey
        PRIMARY KEY (project_id, family_hash, comparison_id),
    ADD CONSTRAINT workflow_c_comparison_results_family_project_fkey
        FOREIGN KEY (family_hash, project_id)
        REFERENCES workflow_c_comparison_families(family_hash, project_id)
        ON DELETE CASCADE;

DROP POLICY project_scope ON workflow_c_comparison_results;
CREATE POLICY project_scope ON workflow_c_comparison_results
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE workflow_c_drift_reports
    DROP CONSTRAINT workflow_c_drift_reports_pkey,
    ADD CONSTRAINT workflow_c_drift_reports_pkey
        PRIMARY KEY (project_id, report_hash);

-- 0032's resolver is SECURITY DEFINER with row security disabled.  Its old
-- hash-only comparison join would therefore cross-join equal hashes from two
-- Projects.  Preserve the mature resolver for all other evidence kinds and
-- put the new Project-qualified comparison branch in a small audited wrapper.
ALTER FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    RENAME TO geo_resolve_recommendation_evidence_pre_0059;
REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence_pre_0059(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;

CREATE FUNCTION geo_resolve_recommendation_evidence(
    p_project_id uuid,
    p_kind text,
    p_resource_id text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE resolved jsonb;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RETURN NULL;
    END IF;
    IF p_kind <> 'metric_comparison' THEN
        RETURN geo_resolve_recommendation_evidence_pre_0059(
            p_project_id, p_kind, p_resource_id
        );
    END IF;
    SELECT jsonb_build_object(
        'kind', 'metric_comparison', 'project_id', family.project_id::text,
        'resource_id', family.family_hash || ':' || result.comparison_id,
        'version', family.family_hash, 'sha256', family.family_hash,
        'locator', jsonb_build_object(
            'comparison_family_hash', family.family_hash,
            'comparison_id', result.comparison_id
        ),
        'valid', family.status = 'complete',
        'observation_resource_ids', coalesce(result.payload->'observation_resource_ids', '[]'::jsonb),
        'method_version', family.bootstrap_method,
        'method_sha256', family.protocol_hash,
        'sufficient_evidence', result.conclusion <> 'insufficient_evidence',
        'summary', NULL
    ) INTO resolved
    FROM workflow_c_comparison_results AS result
    JOIN workflow_c_comparison_families AS family
      ON family.project_id = result.project_id
     AND family.family_hash = result.family_hash
    WHERE family.project_id = p_project_id
      AND (family.family_hash || ':' || result.comparison_id) = p_resource_id;
    RETURN resolved;
END;
$$;

REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    TO geo_app, geo_worker;
