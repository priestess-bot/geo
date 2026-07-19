CREATE OR REPLACE FUNCTION geo_assert_new_durable_job_campaign() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_campaign_id uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        NEW.id, NEW.project_id, NEW.kind, NEW.campaign_id, NEW.parent_job_id
    ) IS DISTINCT FROM (
        OLD.id, OLD.project_id, OLD.kind, OLD.campaign_id, OLD.parent_job_id
    ) THEN
        RAISE EXCEPTION 'durable job identity and Campaign ancestry are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.kind IN (
        'evidence_pack.build', 'placement.generate', 'publication.verify',
        'placement.measure', 'prompt_simulation.generate', 'artifact.finalize'
    ) AND NEW.campaign_id IS NULL THEN
        RAISE EXCEPTION 'Placement jobs require an explicit Campaign context'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.parent_job_id IS NOT NULL THEN
        SELECT campaign_id INTO parent_campaign_id FROM durable_jobs
        WHERE id = NEW.parent_job_id AND project_id = NEW.project_id;
        IF parent_campaign_id IS DISTINCT FROM NEW.campaign_id THEN
            RAISE EXCEPTION 'replayed jobs must preserve source Campaign context'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION geo_require_durable_job_campaign_spec() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    valid_context boolean := false;
BEGIN
    IF NEW.kind = 'evidence_pack.build' THEN
        SELECT EXISTS(SELECT 1 FROM evidence_pack_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'placement.generate' THEN
        SELECT EXISTS(SELECT 1 FROM generation_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'publication.verify' THEN
        SELECT EXISTS(SELECT 1 FROM verification_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'placement.measure' THEN
        SELECT EXISTS(SELECT 1 FROM measurement_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'prompt_simulation.generate' THEN
        SELECT EXISTS(SELECT 1 FROM prompt_simulation_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'artifact.finalize' THEN
        SELECT EXISTS(SELECT 1 FROM artifact_finalize_outbox
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSE
        RETURN NULL;
    END IF;
    IF NOT valid_context THEN
        RAISE EXCEPTION 'Placement job is missing its exact Campaign-scoped specification'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_artifact_campaign_context() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.campaign_id IS NULL OR NEW.opportunity_id IS NULL OR NEW.destination_id IS NULL THEN
        RAISE EXCEPTION 'new placement artifacts require exact Campaign ancestry'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.resource_kind = 'prompt_bundle' AND NOT EXISTS (
        SELECT 1 FROM prompt_bundles WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'Prompt Bundle artifact context mismatch' USING ERRCODE = '23514';
    ELSIF NEW.resource_kind = 'package_export' AND NOT EXISTS (
        SELECT 1 FROM placement_export_receipts WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'Package export artifact context mismatch' USING ERRCODE = '23514';
    ELSIF NEW.resource_kind = 'prompt_simulation' AND NOT EXISTS (
        SELECT 1 FROM prompt_simulations WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
          AND binding_contract_version = 'opportunity-binding-v2'
    ) THEN
        RAISE EXCEPTION 'Prompt simulation artifact context mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
