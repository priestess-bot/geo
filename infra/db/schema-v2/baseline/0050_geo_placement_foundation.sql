-- Schema v2 GEO recommendation influence and placement foundation.
-- A discovered or observed domain is never implicitly a publication destination.

CREATE TABLE publisher_catalog (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_domain text NOT NULL,
    publisher_type text NOT NULL,
    default_operation_mode text NOT NULL DEFAULT 'manual_submission',
    rules_url text,
    policy_status text NOT NULL DEFAULT 'unreviewed',
    policy_checked_at timestamptz,
    policy_checked_by text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT publisher_catalog_domain_unique UNIQUE (canonical_domain),
    CONSTRAINT publisher_catalog_domain_nonempty CHECK (
        canonical_domain = lower(btrim(canonical_domain)) AND canonical_domain <> ''
    ),
    CONSTRAINT publisher_catalog_type_canonical CHECK (publisher_type IN (
        'owned_site', 'marketplace', 'video_platform', 'social_platform',
        'editorial_media', 'review_platform', 'community', 'knowledge_base',
        'competitor_site', 'other'
    )),
    CONSTRAINT publisher_catalog_mode_canonical CHECK (
        default_operation_mode IN ('observed_only', 'manual_submission')
    ),
    CONSTRAINT publisher_catalog_policy_canonical CHECK (
        policy_status IN ('unreviewed', 'approved', 'restricted', 'prohibited')
    ),
    CONSTRAINT publisher_catalog_policy_review_coherent CHECK (
        (policy_status = 'unreviewed' AND policy_checked_at IS NULL AND policy_checked_by IS NULL)
        OR (policy_status <> 'unreviewed' AND policy_checked_at IS NOT NULL
            AND policy_checked_by IS NOT NULL AND btrim(policy_checked_by) <> '')
    ),
    CONSTRAINT publisher_catalog_time_order CHECK (updated_at >= created_at)
);

CREATE TABLE geo_campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    primary_product_entity_id uuid NOT NULL,
    name text NOT NULL,
    market_code text NOT NULL,
    external_locale text NOT NULL DEFAULT 'en-AU',
    status text NOT NULL DEFAULT 'draft',
    objective text NOT NULL DEFAULT 'recommendation_influence',
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT geo_campaigns_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT geo_campaigns_product_project_fkey FOREIGN KEY (primary_product_entity_id, project_id)
        REFERENCES product_entities(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT geo_campaigns_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT geo_campaigns_product_market_unique UNIQUE (project_id, primary_product_entity_id, market_code),
    CONSTRAINT geo_campaigns_name_nonempty CHECK (btrim(name) <> ''),
    CONSTRAINT geo_campaigns_market_locale_valid CHECK (btrim(market_code) <> '' AND external_locale = 'en-AU'),
    CONSTRAINT geo_campaigns_status_canonical CHECK (status IN ('draft', 'active', 'paused', 'archived')),
    CONSTRAINT geo_campaigns_objective_canonical CHECK (objective = 'recommendation_influence'),
    CONSTRAINT geo_campaigns_actors_nonempty CHECK (btrim(created_by) <> '' AND btrim(updated_by) <> ''),
    CONSTRAINT geo_campaigns_time_order CHECK (updated_at >= created_at)
);

CREATE TABLE geo_campaign_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'suggested',
    suggested_by text NOT NULL,
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT geo_campaign_queries_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT geo_campaign_queries_campaign_project_fkey FOREIGN KEY (campaign_id, project_id)
        REFERENCES geo_campaigns(id, project_id) ON DELETE CASCADE,
    CONSTRAINT geo_campaign_queries_query_project_fkey FOREIGN KEY (monitoring_query_id, project_id)
        REFERENCES monitoring_queries(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT geo_campaign_queries_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT geo_campaign_queries_campaign_query_unique UNIQUE (campaign_id, monitoring_query_id),
    CONSTRAINT geo_campaign_queries_status_canonical CHECK (status IN ('suggested', 'approved', 'rejected', 'retired')),
    CONSTRAINT geo_campaign_queries_approval_coherent CHECK (
        (status = 'approved' AND approved_by IS NOT NULL AND btrim(approved_by) <> '' AND approved_at IS NOT NULL)
        OR (status <> 'approved' AND approved_by IS NULL AND approved_at IS NULL)
    ),
    CONSTRAINT geo_campaign_queries_actor_nonempty CHECK (btrim(suggested_by) <> '')
);

CREATE TABLE project_destinations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    publisher_id uuid NOT NULL,
    destination_name text NOT NULL,
    destination_url text NOT NULL,
    ownership_kind text NOT NULL,
    operation_mode text NOT NULL DEFAULT 'observed_only',
    task_type text NOT NULL,
    public_disclosure_required boolean NOT NULL DEFAULT true,
    qualification_status text NOT NULL DEFAULT 'candidate',
    policy_snapshot_hash text NOT NULL,
    policy_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    qualified_by text,
    qualified_at timestamptz,
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT project_destinations_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT project_destinations_publisher_fkey FOREIGN KEY (publisher_id)
        REFERENCES publisher_catalog(id) ON DELETE RESTRICT,
    CONSTRAINT project_destinations_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT project_destinations_url_unique UNIQUE (project_id, destination_url),
    CONSTRAINT project_destinations_name_url_nonempty CHECK (btrim(destination_name) <> '' AND btrim(destination_url) <> ''),
    CONSTRAINT project_destinations_ownership_canonical CHECK (ownership_kind IN (
        'owned', 'marketplace_authorized', 'third_party_editorial',
        'review_platform_business', 'community_official', 'deal_platform',
        'knowledge_contributor', 'observed_external'
    )),
    CONSTRAINT project_destinations_mode_canonical CHECK (operation_mode IN ('observed_only', 'manual_submission')),
    CONSTRAINT project_destinations_observation_only CHECK (
        operation_mode <> 'manual_submission' OR ownership_kind <> 'observed_external'
    ),
    CONSTRAINT project_destinations_task_type_canonical CHECK (task_type IN (
        'owned_content', 'marketplace_listing', 'creator_outreach',
        'editorial_submission', 'business_profile',
        'official_community_participation', 'deal_submission', 'expert_answer'
    )),
    CONSTRAINT project_destinations_qualification_canonical CHECK (qualification_status IN ('candidate', 'approved', 'rejected', 'suspended')),
    CONSTRAINT project_destinations_submission_requires_approval CHECK (
        operation_mode <> 'manual_submission' OR qualification_status = 'approved'
    ),
    CONSTRAINT project_destinations_policy_valid CHECK (
        policy_snapshot_hash ~ '^[0-9a-f]{64}$' AND jsonb_typeof(policy_snapshot) = 'object'
    ),
    CONSTRAINT project_destinations_qualification_coherent CHECK (
        (qualification_status = 'approved' AND qualified_by IS NOT NULL AND btrim(qualified_by) <> '' AND qualified_at IS NOT NULL)
        OR (qualification_status <> 'approved' AND qualified_by IS NULL AND qualified_at IS NULL)
    ),
    CONSTRAINT project_destinations_actors_nonempty CHECK (btrim(created_by) <> '' AND btrim(updated_by) <> ''),
    CONSTRAINT project_destinations_time_order CHECK (updated_at >= created_at)
);

CREATE TABLE placement_opportunities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    destination_id uuid NOT NULL,
    monitoring_query_id uuid,
    source_gap_id uuid,
    action_recommendation_id uuid,
    answer_citation_id uuid,
    title text NOT NULL,
    rationale text NOT NULL,
    priority text NOT NULL DEFAULT 'medium',
    status text NOT NULL DEFAULT 'discovered',
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT placement_opportunities_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT placement_opportunities_campaign_project_fkey FOREIGN KEY (campaign_id, project_id)
        REFERENCES geo_campaigns(id, project_id) ON DELETE CASCADE,
    CONSTRAINT placement_opportunities_destination_project_fkey FOREIGN KEY (destination_id, project_id)
        REFERENCES project_destinations(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_opportunities_query_project_fkey FOREIGN KEY (monitoring_query_id, project_id)
        REFERENCES monitoring_queries(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_opportunities_gap_project_fkey FOREIGN KEY (source_gap_id, project_id)
        REFERENCES source_gaps(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_opportunities_action_project_fkey FOREIGN KEY (action_recommendation_id, project_id)
        REFERENCES action_recommendations(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_opportunities_citation_project_fkey FOREIGN KEY (answer_citation_id, project_id)
        REFERENCES answer_citations(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT placement_opportunities_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT placement_opportunities_origin_present CHECK (
        num_nonnulls(source_gap_id, action_recommendation_id, answer_citation_id) <= 1
    ),
    CONSTRAINT placement_opportunities_text_nonempty CHECK (btrim(title) <> '' AND btrim(rationale) <> ''),
    CONSTRAINT placement_opportunities_priority_canonical CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT placement_opportunities_status_canonical CHECK (status IN (
        'discovered', 'qualified', 'package_requested', 'ready_to_submit', 'submitted',
        'accepted', 'declined', 'published', 'verified', 'measured', 'dismissed'
    )),
    CONSTRAINT placement_opportunities_actors_nonempty CHECK (btrim(created_by) <> '' AND btrim(updated_by) <> ''),
    CONSTRAINT placement_opportunities_time_order CHECK (updated_at >= created_at)
);

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'geo_campaigns', 'geo_campaign_queries', 'project_destinations',
        'placement_opportunities'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
    END LOOP;
END;
$$;

REVOKE ALL ON publisher_catalog, geo_campaigns, geo_campaign_queries,
    project_destinations, placement_opportunities FROM PUBLIC, geo_v2_runtime, geo_v2_worker;

CREATE INDEX geo_campaign_queries_campaign_status_idx
    ON geo_campaign_queries (campaign_id, status, created_at DESC);
CREATE INDEX project_destinations_project_mode_idx
    ON project_destinations (project_id, operation_mode, qualification_status, updated_at DESC);
CREATE INDEX placement_opportunities_campaign_status_idx
    ON placement_opportunities (campaign_id, status, priority, updated_at DESC);
