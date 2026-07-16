CREATE TABLE prompt_simulations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    destination_id uuid NOT NULL,
    destination_policy_version_id uuid,
    template_release_id uuid NOT NULL,
    primary_brand_entity_id uuid NOT NULL,
    product_entity_id uuid NOT NULL,
    requested_by uuid NOT NULL REFERENCES identities(id),
    input_snapshot jsonb NOT NULL CHECK (jsonb_typeof(input_snapshot) = 'object'),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    test_only boolean NOT NULL DEFAULT true CHECK (test_only),
    publication_eligible boolean NOT NULL DEFAULT false CHECK (NOT publication_eligible),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (destination_id, project_id)
        REFERENCES publication_destinations(id, project_id),
    FOREIGN KEY (destination_policy_version_id, project_id)
        REFERENCES destination_policy_versions(id, project_id),
    FOREIGN KEY (template_release_id, project_id)
        REFERENCES generation_template_releases(id, project_id),
    FOREIGN KEY (primary_brand_entity_id, project_id)
        REFERENCES product_entities(id, project_id),
    FOREIGN KEY (product_entity_id, project_id)
        REFERENCES product_entities(id, project_id),
    UNIQUE (id, project_id)
);

COMMENT ON TABLE prompt_simulations IS
    'Internal technical previews only. A simulation can never become a package, export or publication request.';

CREATE TABLE prompt_simulation_evidence (
    simulation_id uuid NOT NULL,
    project_id uuid NOT NULL,
    evidence_item_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (simulation_id, evidence_item_id),
    FOREIGN KEY (simulation_id, project_id)
        REFERENCES prompt_simulations(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_item_id, project_id)
        REFERENCES evidence_items(id, project_id),
    UNIQUE (simulation_id, ordinal)
);

CREATE TABLE prompt_simulation_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    simulation_id uuid NOT NULL,
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    model_call_budget integer NOT NULL CHECK (model_call_budget BETWEEN 1 AND 5),
    requested_by uuid NOT NULL REFERENCES identities(id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (simulation_id, project_id)
        REFERENCES prompt_simulations(id, project_id),
    UNIQUE (job_id, project_id)
);

CREATE TABLE prompt_simulation_results (
    simulation_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    generated_by_job_id uuid NOT NULL,
    artifact_manifest jsonb NOT NULL CHECK (jsonb_typeof(artifact_manifest) = 'object'),
    output_hash text NOT NULL CHECK (output_hash ~ '^[0-9a-f]{64}$'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    model_response_hash text NOT NULL CHECK (model_response_hash ~ '^[0-9a-f]{64}$'),
    storage_key text NOT NULL CHECK (left(storage_key, 20) = 'content-simulations/'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (simulation_id, project_id)
        REFERENCES prompt_simulations(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (generated_by_job_id, project_id)
        REFERENCES prompt_simulation_job_specs(job_id, project_id),
    UNIQUE (simulation_id, project_id)
);

CREATE FUNCTION geo_assert_prompt_simulation_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    destination_channel text;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM product_entities entity
        WHERE entity.id = NEW.primary_brand_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'brand' AND entity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'prompt simulation primary brand must reference an active brand'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM product_entities entity
        WHERE entity.id = NEW.product_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'product' AND entity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'prompt simulation product must reference an active product'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.destination_policy_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM destination_policy_versions policy
        WHERE policy.id = NEW.destination_policy_version_id
          AND policy.project_id = NEW.project_id
          AND policy.destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'prompt simulation policy does not belong to its destination'
            USING ERRCODE = '23514';
    END IF;
    SELECT destination.publication_channel INTO destination_channel
    FROM publication_destinations destination
    WHERE destination.id = NEW.destination_id
      AND destination.project_id = NEW.project_id;
    IF NOT EXISTS (
        SELECT 1 FROM content_task_prompt_releases binding
        WHERE binding.project_id = NEW.project_id
          AND binding.task_key = destination_channel
          AND binding.template_release_id = NEW.template_release_id
    ) THEN
        RAISE EXCEPTION 'prompt simulation release is not selected for its destination channel'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER prompt_simulation_scope_guard
BEFORE INSERT OR UPDATE ON prompt_simulations
FOR EACH ROW EXECUTE FUNCTION geo_assert_prompt_simulation_scope();

CREATE TRIGGER prompt_simulation_job_spec_kind
BEFORE INSERT OR UPDATE ON prompt_simulation_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('prompt_simulation.generate');

CREATE TRIGGER prompt_simulations_immutable
BEFORE UPDATE OR DELETE ON prompt_simulations
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_simulation_evidence_immutable
BEFORE UPDATE OR DELETE ON prompt_simulation_evidence
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_simulation_results_immutable
BEFORE UPDATE OR DELETE ON prompt_simulation_results
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

ALTER TABLE artifact_finalize_outbox
    DROP CONSTRAINT artifact_finalize_outbox_resource_kind_check,
    ADD CONSTRAINT artifact_finalize_outbox_resource_kind_check
        CHECK (resource_kind IN ('prompt_bundle', 'package_export', 'prompt_simulation'));

CREATE INDEX prompt_simulations_project_created_idx
ON prompt_simulations (project_id, created_at DESC, id DESC);
CREATE INDEX prompt_simulation_specs_simulation_idx
ON prompt_simulation_job_specs (project_id, simulation_id, job_id);

ALTER TABLE prompt_simulations ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_simulations FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON prompt_simulations
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE prompt_simulation_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_simulation_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON prompt_simulation_evidence
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE prompt_simulation_job_specs ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_simulation_job_specs FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON prompt_simulation_job_specs
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE prompt_simulation_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_simulation_results FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON prompt_simulation_results
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

GRANT SELECT, INSERT, UPDATE, DELETE ON
    prompt_simulations,
    prompt_simulation_evidence,
    prompt_simulation_job_specs,
    prompt_simulation_results
TO geo_app, geo_worker;
GRANT SELECT ON
    prompt_simulations,
    prompt_simulation_evidence,
    prompt_simulation_job_specs,
    prompt_simulation_results
TO geo_readonly;
GRANT EXECUTE ON FUNCTION geo_assert_prompt_simulation_scope()
TO geo_app, geo_worker, geo_readonly;
