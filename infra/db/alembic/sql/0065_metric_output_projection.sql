-- The provider artifact is retained under its own provider policy, but a
-- completed Metric child must leave a small, schema-validated projection that
-- lets its parent reconstruct metrics without rereading raw model output. The
-- projection deliberately lives outside the frozen child lineage row: a
-- historical child may refer to a retired prompt binding and PostgreSQL would
-- re-check that unrelated foreign key on any UPDATE of the child row.
CREATE TABLE workflow_c_metric_child_output_projections (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    child_job_id uuid NOT NULL,
    output_hash text NOT NULL CHECK (output_hash ~ '^[0-9a-f]{64}$'),
    output_projection jsonb NOT NULL CHECK (jsonb_typeof(output_projection) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, child_job_id),
    FOREIGN KEY (project_id, child_job_id)
        REFERENCES workflow_c_metric_model_children(project_id, child_job_id)
        ON DELETE CASCADE
);

CREATE FUNCTION geo_assert_workflow_c_metric_child_output_projection_change()
RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Workflow C metric child output projection is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER workflow_c_metric_child_output_projections_change_guard
BEFORE UPDATE OR DELETE ON workflow_c_metric_child_output_projections
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_metric_child_output_projection_change();

ALTER TABLE workflow_c_metric_child_output_projections ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_metric_child_output_projections FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_metric_child_output_projections
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON workflow_c_metric_child_output_projections
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON workflow_c_metric_child_output_projections TO geo_worker;

-- The old ten-argument entry point remains for a rolling deployment. Its
-- completion rows deliberately have no projection record and are unusable by
-- a parent projection reader until replayed by a current worker. The eleven-
-- argument entry point is the only one used by the current Worker and atomically
-- records the validated, hash-bound projection.
CREATE FUNCTION geo_complete_workflow_c_metric_child(
    p_project_id uuid,
    p_child_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_parent_input_hash text,
    p_role text,
    p_model_attempt_id uuid,
    p_output_hash text,
    p_selected_candidate_id uuid,
    p_selected_output_hash text,
    p_output_projection jsonb
) RETURNS TABLE (
    child_status text,
    batch_status text,
    batch_id uuid,
    aggregate_version integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE completed record;
BEGIN
    IF p_output_projection IS NULL
       OR jsonb_typeof(p_output_projection) <> 'object'
       OR encode(digest(convert_to(geo_jsonb_canonical_text(p_output_projection), 'UTF8'), 'sha256'), 'hex')
            <> p_output_hash THEN
        RAISE EXCEPTION 'Workflow C metric output projection does not match its hash'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO completed
    FROM geo_complete_workflow_c_metric_child(
        p_project_id, p_child_job_id, p_lease_token, p_fencing_generation,
        p_parent_input_hash, p_role, p_model_attempt_id, p_output_hash,
        p_selected_candidate_id, p_selected_output_hash
    );

    INSERT INTO workflow_c_metric_child_output_projections (
        project_id, child_job_id, output_hash, output_projection, recorded_at
    )
    SELECT p_project_id, p_child_job_id, p_output_hash, p_output_projection,
           clock_timestamp()
    FROM workflow_c_metric_model_children
    WHERE project_id = p_project_id
      AND child_job_id = p_child_job_id
      AND status = 'succeeded'
      AND output_hash = p_output_hash
    ON CONFLICT (project_id, child_job_id) DO NOTHING;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Workflow C metric child output projection was fenced'
            USING ERRCODE = '40001';
    END IF;

    RETURN QUERY
    SELECT completed.child_status, completed.batch_status,
           completed.batch_id, completed.aggregate_version;
END;
$$;

REVOKE ALL ON FUNCTION geo_complete_workflow_c_metric_child(
    uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text, jsonb
) FROM PUBLIC, geo_app, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_complete_workflow_c_metric_child(
    uuid, uuid, uuid, integer, text, text, uuid, text, uuid, text, jsonb
) TO geo_worker;

COMMENT ON TABLE workflow_c_metric_child_output_projections IS
    'Validated minimal Metric Judge or Arbiter result; excludes raw model response.';
