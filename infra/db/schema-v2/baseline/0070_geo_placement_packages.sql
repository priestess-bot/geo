-- Immutable channel-specific briefs, evidence, prompt bundles, and placement packages.

CREATE TABLE placement_briefs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_opportunity_id uuid NOT NULL,
    current_version_id uuid,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_briefs_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_briefs_opportunity_project_fkey FOREIGN KEY (placement_opportunity_id, project_id)
        REFERENCES placement_opportunities(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_briefs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_briefs_opportunity_unique UNIQUE (placement_opportunity_id),
    CONSTRAINT placement_briefs_actor_nonempty CHECK (btrim(created_by) <> '')
);

CREATE TABLE placement_brief_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_brief_id uuid NOT NULL,
    version_number integer NOT NULL,
    destination_id uuid NOT NULL,
    task_type text NOT NULL,
    audience text NOT NULL,
    objective text NOT NULL,
    required_disclosure text,
    cta_url text,
    brief_json jsonb NOT NULL,
    brief_hash text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_brief_versions_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_brief_versions_brief_project_fkey FOREIGN KEY (placement_brief_id, project_id)
        REFERENCES placement_briefs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_brief_versions_destination_project_fkey FOREIGN KEY (destination_id, project_id)
        REFERENCES project_destinations(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_brief_versions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_brief_versions_number_unique UNIQUE (placement_brief_id, version_number),
    CONSTRAINT placement_brief_versions_task_canonical CHECK (task_type IN (
        'owned_content', 'marketplace_listing', 'creator_outreach',
        'editorial_submission', 'business_profile',
        'official_community_participation', 'deal_submission', 'expert_answer'
    )),
    CONSTRAINT placement_brief_versions_values_valid CHECK (
        version_number > 0 AND btrim(audience) <> '' AND btrim(objective) <> ''
        AND jsonb_typeof(brief_json) = 'object' AND brief_hash ~ '^[0-9a-f]{64}$'
        AND btrim(created_by) <> ''
    )
);
ALTER TABLE placement_briefs ADD CONSTRAINT placement_briefs_current_version_project_fkey
    FOREIGN KEY (current_version_id, project_id) REFERENCES placement_brief_versions(id, project_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE placement_evidence_packs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_brief_version_id uuid NOT NULL,
    attempt_number integer NOT NULL,
    status text NOT NULL,
    evidence_hash text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_evidence_packs_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_evidence_packs_brief_version_project_fkey FOREIGN KEY (placement_brief_version_id, project_id)
        REFERENCES placement_brief_versions(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_evidence_packs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_evidence_packs_attempt_unique UNIQUE (placement_brief_version_id, attempt_number),
    CONSTRAINT placement_evidence_packs_status_canonical CHECK (status IN ('ready', 'needs_evidence', 'blocked', 'superseded')),
    CONSTRAINT placement_evidence_packs_values_valid CHECK (
        attempt_number > 0 AND evidence_hash ~ '^[0-9a-f]{64}$' AND btrim(created_by) <> ''
    )
);

CREATE TABLE placement_evidence_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_evidence_pack_id uuid NOT NULL,
    knowledge_fact_version_id uuid,
    knowledge_chunk_id uuid,
    knowledge_source_asset_revision_id uuid,
    source_url text,
    source_text text NOT NULL,
    source_hash text NOT NULL,
    public_citation_allowed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_evidence_items_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_evidence_items_pack_project_fkey FOREIGN KEY (placement_evidence_pack_id, project_id)
        REFERENCES placement_evidence_packs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_evidence_items_fact_project_fkey FOREIGN KEY (knowledge_fact_version_id, project_id)
        REFERENCES knowledge_fact_versions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_evidence_items_chunk_project_fkey FOREIGN KEY (knowledge_chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_evidence_items_revision_project_fkey FOREIGN KEY (knowledge_source_asset_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_evidence_items_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_evidence_items_source_one_of CHECK (
        num_nonnulls(knowledge_fact_version_id, knowledge_chunk_id, knowledge_source_asset_revision_id) = 1
    ),
    CONSTRAINT placement_evidence_items_values_valid CHECK (
        btrim(source_text) <> '' AND source_hash ~ '^[0-9a-f]{64}$'
        AND (source_url IS NULL OR btrim(source_url) <> '')
    ),
    CONSTRAINT placement_evidence_items_pack_source_unique UNIQUE NULLS NOT DISTINCT (
        placement_evidence_pack_id, knowledge_fact_version_id, knowledge_chunk_id,
        knowledge_source_asset_revision_id
    )
);

CREATE TABLE geo_prompt_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    task_key text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT geo_prompt_definitions_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT geo_prompt_definitions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT geo_prompt_definitions_task_key_valid CHECK (task_key IN (
        'placement.owned.product_page', 'placement.owned.faq',
        'placement.marketplace.listing', 'placement.youtube.video_script',
        'placement.youtube.description', 'placement.tiktok.video_script',
        'placement.instagram.reel_caption', 'placement.productreview.business_response',
        'placement.reddit.disclosed_official_post', 'placement.ozbargain.deal_submission',
        'placement.quora.disclosed_expert_answer'
    )),
    CONSTRAINT geo_prompt_definitions_status_canonical CHECK (status IN ('active', 'archived')),
    CONSTRAINT geo_prompt_definitions_actor_nonempty CHECK (btrim(created_by) <> '')
);

CREATE TABLE geo_prompt_definition_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    prompt_definition_id uuid NOT NULL,
    version_number integer NOT NULL,
    system_template text NOT NULL,
    user_template text NOT NULL,
    variable_schema jsonb NOT NULL,
    output_schema jsonb NOT NULL,
    template_hash text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT geo_prompt_versions_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT geo_prompt_versions_definition_fkey FOREIGN KEY (prompt_definition_id, project_id)
        REFERENCES geo_prompt_definitions(id, project_id) ON DELETE CASCADE,
    CONSTRAINT geo_prompt_versions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT geo_prompt_versions_number_unique UNIQUE (prompt_definition_id, version_number),
    CONSTRAINT geo_prompt_versions_values_valid CHECK (
        version_number > 0 AND btrim(system_template) <> '' AND btrim(user_template) <> ''
        AND jsonb_typeof(variable_schema) = 'object' AND jsonb_typeof(output_schema) = 'object'
        AND template_hash ~ '^[0-9a-f]{64}$' AND btrim(created_by) <> ''
    )
);

CREATE TABLE geo_prompt_bundles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_brief_version_id uuid NOT NULL,
    placement_evidence_pack_id uuid NOT NULL,
    prompt_definition_version_id uuid NOT NULL,
    rendered_prompt_uri text NOT NULL,
    rendered_prompt_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT geo_prompt_bundles_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT geo_prompt_bundles_brief_project_fkey FOREIGN KEY (placement_brief_version_id, project_id)
        REFERENCES placement_brief_versions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT geo_prompt_bundles_pack_project_fkey FOREIGN KEY (placement_evidence_pack_id, project_id)
        REFERENCES placement_evidence_packs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT geo_prompt_bundles_prompt_version_fkey FOREIGN KEY (prompt_definition_version_id)
        REFERENCES geo_prompt_definition_versions(id) ON DELETE RESTRICT,
    CONSTRAINT geo_prompt_bundles_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT geo_prompt_bundles_values_valid CHECK (
        btrim(rendered_prompt_uri) <> '' AND rendered_prompt_hash ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE placement_packages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_opportunity_id uuid NOT NULL,
    placement_brief_version_id uuid NOT NULL,
    placement_evidence_pack_id uuid NOT NULL,
    prompt_bundle_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    content_json jsonb NOT NULL,
    rendered_text text NOT NULL,
    content_hash text NOT NULL,
    disclosure_text text,
    submitted_for_review_by text,
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_packages_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_packages_opportunity_project_fkey FOREIGN KEY (placement_opportunity_id, project_id)
        REFERENCES placement_opportunities(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_packages_brief_project_fkey FOREIGN KEY (placement_brief_version_id, project_id)
        REFERENCES placement_brief_versions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_packages_pack_project_fkey FOREIGN KEY (placement_evidence_pack_id, project_id)
        REFERENCES placement_evidence_packs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_packages_bundle_project_fkey FOREIGN KEY (prompt_bundle_id, project_id)
        REFERENCES geo_prompt_bundles(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_packages_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_packages_status_canonical CHECK (status IN ('draft', 'qa_running', 'pending_review', 'approved', 'needs_revision', 'blocked', 'superseded')),
    CONSTRAINT placement_packages_content_valid CHECK (
        jsonb_typeof(content_json) = 'object' AND btrim(rendered_text) <> ''
        AND content_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT placement_packages_review_coherent CHECK (
        (status = 'approved' AND submitted_for_review_by IS NOT NULL AND approved_by IS NOT NULL
            AND submitted_for_review_by <> approved_by AND approved_at IS NOT NULL)
        OR (status <> 'approved' AND approved_by IS NULL AND approved_at IS NULL)
    )
);

CREATE TABLE placement_package_claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    placement_package_id uuid NOT NULL,
    evidence_item_id uuid NOT NULL,
    claim_text text NOT NULL,
    support_status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_package_claims_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_package_claims_package_project_fkey FOREIGN KEY (placement_package_id, project_id)
        REFERENCES placement_packages(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_package_claims_evidence_project_fkey FOREIGN KEY (evidence_item_id, project_id)
        REFERENCES placement_evidence_items(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_package_claims_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_package_claims_values_valid CHECK (
        btrim(claim_text) <> '' AND support_status IN ('supported', 'unsupported', 'conflict')
    ),
    CONSTRAINT placement_package_claims_unique UNIQUE (placement_package_id, claim_text)
);

CREATE FUNCTION geo_v2_reject_geo_placement_immutable_update()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'geo placement traceability rows are immutable' USING ERRCODE = '55000';
END;
$$;

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'placement_briefs', 'placement_brief_versions', 'placement_evidence_packs',
        'placement_evidence_items', 'geo_prompt_definitions',
        'geo_prompt_definition_versions', 'geo_prompt_bundles',
        'placement_packages', 'placement_package_claims'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY[
        'placement_brief_versions', 'placement_evidence_packs',
        'placement_evidence_items', 'geo_prompt_definition_versions',
        'geo_prompt_bundles', 'placement_package_claims'
    ] LOOP
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.geo_v2_reject_geo_placement_immutable_update()', table_name || '_immutable', table_name);
    END LOOP;
END;
$$;

ALTER FUNCTION geo_v2_reject_geo_placement_immutable_update() OWNER TO geo_v2_result_owner;
REVOKE ALL ON placement_briefs, placement_brief_versions, placement_evidence_packs,
    placement_evidence_items, geo_prompt_definitions, geo_prompt_definition_versions,
    geo_prompt_bundles, placement_packages, placement_package_claims
    FROM PUBLIC, geo_v2_runtime, geo_v2_worker;
REVOKE ALL ON FUNCTION geo_v2_reject_geo_placement_immutable_update() FROM PUBLIC;
