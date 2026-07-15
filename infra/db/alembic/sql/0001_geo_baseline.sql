-- Fresh GEO baseline. This file is intentionally native PostgreSQL SQL.
-- It is not an in-place upgrade from either legacy migration tree.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'geo_app') THEN
        CREATE ROLE geo_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'geo_worker') THEN
        CREATE ROLE geo_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'geo_readonly') THEN
        CREATE ROLE geo_readonly NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END;
$$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE FUNCTION geo_current_project_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT NULLIF(current_setting('geo.project_id', true), '')::uuid
$$;

CREATE FUNCTION geo_current_identity_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT NULLIF(current_setting('geo.identity_id', true), '')::uuid
$$;

CREATE FUNCTION geo_current_tenant_id() RETURNS uuid
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT NULLIF(current_setting('geo.tenant_id', true), '')::uuid
$$;

CREATE FUNCTION geo_current_project_ids() RETURNS uuid[]
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT COALESCE(array_agg(project_id), ARRAY[]::uuid[])
    FROM (
        SELECT value::uuid AS project_id
        FROM jsonb_array_elements_text(
            COALESCE(
                NULLIF(current_setting('geo.project_ids', true), '')::jsonb,
                '[]'::jsonb
            )
        ) AS project_ids(value)
    ) AS scoped_projects
$$;

CREATE FUNCTION geo_reject_immutable_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION USING MESSAGE = TG_TABLE_NAME || ' rows are immutable', ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_protect_package_version_content() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.package_id, NEW.project_id, NEW.version_number, NEW.base_version_id,
        NEW.content_json, NEW.rendered_text, NEW.content_hash, NEW.edited_by,
        NEW.edit_reason, NEW.prompt_bundle_id)
       IS DISTINCT FROM
       (OLD.package_id, OLD.project_id, OLD.version_number, OLD.base_version_id,
        OLD.content_json, OLD.rendered_text, OLD.content_hash, OLD.edited_by,
        OLD.edit_reason, OLD.prompt_bundle_id) THEN
        RAISE EXCEPTION 'placement package version content and lineage are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_protect_evidence_pack_attempt() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'evidence pack attempts are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'building' THEN
        IF OLD.status IN ('ready', 'needs_evidence', 'blocked') AND NEW.status = 'superseded'
           AND NEW.superseded_by_attempt_id IS NOT NULL AND NEW.superseded_at IS NOT NULL
           AND (NEW.id, NEW.project_id, NEW.brief_version_id, NEW.attempt_number,
                NEW.failure_reason, NEW.pack_hash, NEW.created_at, NEW.completed_at)
               IS NOT DISTINCT FROM
               (OLD.id, OLD.project_id, OLD.brief_version_id, OLD.attempt_number,
                OLD.failure_reason, OLD.pack_hash, OLD.created_at, OLD.completed_at) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'terminal evidence pack attempts are immutable; create a new attempt'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.status = 'superseded' THEN
        RAISE EXCEPTION 'a building evidence pack cannot be superseded'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'ready' THEN
        IF NOT EXISTS (
            SELECT 1 FROM evidence_pack_items i
            WHERE i.pack_attempt_id = NEW.id AND i.project_id = NEW.project_id
        ) OR EXISTS (
            SELECT 1
            FROM evidence_pack_items i
            JOIN evidence_items e ON e.id = i.evidence_item_id AND e.project_id = i.project_id
            WHERE i.pack_attempt_id = NEW.id AND i.project_id = NEW.project_id
              AND (e.usage_rights IN ('unknown', 'restricted')
                   OR e.confidentiality = 'restricted')
        ) THEN
            RAISE EXCEPTION 'ready evidence packs require at least one eligible evidence item'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (btrim(name) <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'archived')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issuer text NOT NULL,
    subject text NOT NULL,
    email text,
    display_name text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (issuer, subject)
);

CREATE TABLE projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, tenant_id)
);

CREATE TABLE project_memberships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    identity_id uuid NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('owner', 'admin', 'analyst', 'viewer', 'customer')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (project_id, identity_id)
);

CREATE INDEX project_memberships_identity_scope_idx
ON project_memberships (identity_id, tenant_id, status, project_id);

CREATE TABLE customer_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id uuid NOT NULL REFERENCES identities(id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_seen_at timestamptz,
    CHECK (
        (status = 'active' AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL)
    )
);

CREATE INDEX customer_sessions_active_expiry_idx
ON customer_sessions (expires_at)
WHERE status = 'active';

CREATE TABLE product_entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_type text NOT NULL CHECK (entity_type IN ('brand', 'product', 'competitor', 'market')),
    canonical_name text NOT NULL CHECK (btrim(canonical_name) <> ''),
    canonical_url text,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(attributes) = 'object'),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, canonical_name)
);

CREATE TABLE market_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    market_code text NOT NULL CHECK (market_code ~ '^[A-Z]{2}$'),
    locale text NOT NULL CHECK (btrim(locale) <> ''),
    timezone text NOT NULL CHECK (btrim(timezone) <> ''),
    rules jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(rules) = 'object'),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, market_code, locale)
);

CREATE TABLE monitoring_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    market_profile_id uuid NOT NULL,
    query_text text NOT NULL CHECK (btrim(query_text) <> ''),
    query_kind text NOT NULL CHECK (query_kind IN ('recommendation', 'comparison', 'research', 'support')),
    locale text NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (market_profile_id, project_id) REFERENCES market_profiles(id, project_id),
    UNIQUE (id, project_id)
);

CREATE TABLE evidence_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    item_type text NOT NULL CHECK (item_type IN (
        'approved_fact', 'chunk', 'citation', 'report_extract', 'source_asset',
        'consumer_experience'
    )),
    source_id uuid NOT NULL,
    subject_entity_id uuid,
    subject_role text NOT NULL CHECK (subject_role IN (
        'primary_brand', 'competitor', 'market', 'product', 'neutral'
    )),
    locator jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(locator) = 'object'),
    snapshot_text text,
    snapshot_uri text,
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    source_revision_kind text NOT NULL CHECK (source_revision_kind IN (
        'row_version', 'content_hash', 'report_version'
    )),
    source_revision_value text NOT NULL CHECK (btrim(source_revision_value) <> ''),
    usage_rights text NOT NULL CHECK (usage_rights IN (
        'owned', 'licensed', 'public_reference', 'authorised_experience', 'restricted', 'unknown'
    )),
    confidentiality text NOT NULL DEFAULT 'internal' CHECK (confidentiality IN (
        'public', 'internal', 'confidential', 'restricted'
    )),
    public_disclosure_allowed boolean NOT NULL DEFAULT false,
    public_source_url text,
    public_source_title text,
    citation_label text,
    quotation_allowed boolean NOT NULL DEFAULT false,
    attribution_required boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (subject_entity_id, project_id) REFERENCES product_entities(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (project_id, item_type, source_id, source_revision_kind, source_revision_value),
    CHECK (num_nonnulls(snapshot_text, snapshot_uri) >= 1),
    CHECK (snapshot_text IS NULL OR btrim(snapshot_text) <> ''),
    CHECK (snapshot_uri IS NULL OR btrim(snapshot_uri) <> ''),
    CHECK (item_type <> 'consumer_experience' OR usage_rights = 'authorised_experience'),
    CHECK (NOT public_disclosure_allowed OR public_source_url IS NOT NULL)
);

COMMENT ON COLUMN evidence_items.snapshot_text IS
    'A consumer_experience is a real consumer usage description; provider/time/product subfields are intentionally not mandatory.';

CREATE TABLE geo_campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    market_profile_id uuid NOT NULL,
    primary_product_entity_id uuid NOT NULL,
    name text NOT NULL CHECK (btrim(name) <> ''),
    objective text NOT NULL DEFAULT 'recommendation_influence',
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'paused', 'completed', 'archived')),
    created_by uuid REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (market_profile_id, project_id) REFERENCES market_profiles(id, project_id),
    FOREIGN KEY (primary_product_entity_id, project_id) REFERENCES product_entities(id, project_id),
    UNIQUE (id, project_id)
);

CREATE TABLE campaign_entities (
    campaign_id uuid NOT NULL,
    project_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    entity_role text NOT NULL CHECK (entity_role IN ('primary_brand', 'competitor', 'market', 'product')),
    PRIMARY KEY (campaign_id, entity_id),
    FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id, project_id) REFERENCES product_entities(id, project_id)
);

CREATE TABLE campaign_monitoring_queries (
    campaign_id uuid NOT NULL,
    project_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    PRIMARY KEY (campaign_id, monitoring_query_id),
    FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (monitoring_query_id, project_id) REFERENCES monitoring_queries(id, project_id)
);

CREATE TABLE publication_destinations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    publication_channel text NOT NULL CHECK (publication_channel IN (
        'owned_site', 'productreview', 'youtube', 'reddit', 'amazon', 'ozbargain',
        'tiktok', 'instagram', 'quora', 'other'
    )),
    destination_account_id text,
    destination_key text NOT NULL CHECK (btrim(destination_key) <> ''),
    canonical_url text,
    operation_mode text NOT NULL DEFAULT 'manual' CHECK (operation_mode IN ('manual', 'assisted', 'api')),
    policy_status text NOT NULL DEFAULT 'unreviewed' CHECK (policy_status IN (
        'unreviewed', 'approved', 'restricted', 'prohibited'
    )),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, publication_channel, destination_key)
);

CREATE TABLE placement_opportunities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    destination_id uuid NOT NULL,
    opportunity_ref text NOT NULL CHECK (btrim(opportunity_ref) <> ''),
    rationale text NOT NULL CHECK (btrim(rationale) <> ''),
    status text NOT NULL DEFAULT 'identified' CHECK (status IN (
        'identified', 'qualified', 'briefing', 'in_progress', 'blocked', 'completed', 'cancelled'
    )),
    blocked_reason text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (destination_id, project_id) REFERENCES publication_destinations(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (project_id, opportunity_ref),
    CHECK ((status = 'blocked') = (blocked_reason IS NOT NULL))
);

CREATE TABLE placement_briefs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    opportunity_id uuid NOT NULL,
    primary_brand_entity_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (opportunity_id, project_id) REFERENCES placement_opportunities(id, project_id),
    FOREIGN KEY (primary_brand_entity_id, project_id) REFERENCES product_entities(id, project_id),
    UNIQUE (id, project_id)
);

CREATE TABLE placement_brief_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    brief_id uuid NOT NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    base_version_id uuid,
    goals jsonb NOT NULL CHECK (jsonb_typeof(goals) = 'object'),
    constraints jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(constraints) = 'object'),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    created_by uuid REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (brief_id, project_id) REFERENCES placement_briefs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (base_version_id, project_id) REFERENCES placement_brief_versions(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (brief_id, version_number)
);

CREATE TABLE placement_brief_subject_entities (
    brief_version_id uuid NOT NULL,
    project_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    subject_scope text NOT NULL CHECK (subject_scope IN ('compared', 'allowed')),
    PRIMARY KEY (brief_version_id, entity_id, subject_scope),
    FOREIGN KEY (brief_version_id, project_id)
        REFERENCES placement_brief_versions(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id, project_id) REFERENCES product_entities(id, project_id)
);

CREATE TABLE evidence_pack_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    brief_version_id uuid NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    status text NOT NULL DEFAULT 'building' CHECK (status IN (
        'building', 'ready', 'needs_evidence', 'blocked', 'superseded'
    )),
    failure_reason text,
    pack_hash text,
    superseded_by_attempt_id uuid,
    superseded_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    FOREIGN KEY (brief_version_id, project_id) REFERENCES placement_brief_versions(id, project_id),
    FOREIGN KEY (superseded_by_attempt_id, project_id)
        REFERENCES evidence_pack_attempts(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (brief_version_id, attempt_number),
    CHECK (pack_hash IS NULL OR pack_hash ~ '^[0-9a-f]{64}$'),
    CHECK (status <> 'ready' OR pack_hash IS NOT NULL),
    CHECK (status NOT IN ('needs_evidence', 'blocked') OR failure_reason IS NOT NULL),
    CHECK ((status = 'superseded') = (superseded_by_attempt_id IS NOT NULL)),
    CHECK ((status = 'superseded') = (superseded_at IS NOT NULL))
);

CREATE TABLE evidence_pack_items (
    pack_attempt_id uuid NOT NULL,
    project_id uuid NOT NULL,
    evidence_item_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (pack_attempt_id, evidence_item_id),
    FOREIGN KEY (pack_attempt_id, project_id) REFERENCES evidence_pack_attempts(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_item_id, project_id) REFERENCES evidence_items(id, project_id),
    UNIQUE (pack_attempt_id, ordinal)
);

CREATE TABLE prompt_skills (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    skill_key text NOT NULL CHECK (btrim(skill_key) <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, skill_key)
);

CREATE TABLE prompt_skill_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    skill_id uuid NOT NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    source_text text NOT NULL CHECK (btrim(source_text) <> ''),
    source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
    created_by uuid REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (skill_id, project_id) REFERENCES prompt_skills(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (skill_id, version_number)
);

CREATE TABLE generation_template_releases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    skill_version_id uuid NOT NULL,
    release_number integer NOT NULL CHECK (release_number > 0),
    system_template text NOT NULL CHECK (btrim(system_template) <> ''),
    user_template text NOT NULL CHECK (btrim(user_template) <> ''),
    variable_schema jsonb NOT NULL CHECK (jsonb_typeof(variable_schema) = 'object'),
    output_schema jsonb NOT NULL CHECK (jsonb_typeof(output_schema) = 'object'),
    compiler_version text NOT NULL CHECK (btrim(compiler_version) <> ''),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (skill_version_id, project_id) REFERENCES prompt_skill_versions(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (skill_version_id, release_number)
);

CREATE TABLE prompt_bundles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    brief_version_id uuid NOT NULL,
    evidence_pack_attempt_id uuid NOT NULL,
    template_release_id uuid NOT NULL,
    input_snapshot jsonb NOT NULL CHECK (jsonb_typeof(input_snapshot) = 'object'),
    storage_uri text NOT NULL CHECK (left(storage_uri, 16) = 'content-prompts/'),
    bundle_hash text NOT NULL CHECK (bundle_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (brief_version_id, project_id) REFERENCES placement_brief_versions(id, project_id),
    FOREIGN KEY (evidence_pack_attempt_id, project_id) REFERENCES evidence_pack_attempts(id, project_id),
    FOREIGN KEY (template_release_id, project_id) REFERENCES generation_template_releases(id, project_id),
    UNIQUE (id, project_id)
);

CREATE TABLE placement_packages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    opportunity_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    archived_at timestamptz,
    FOREIGN KEY (opportunity_id, project_id) REFERENCES placement_opportunities(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (opportunity_id)
);

CREATE TABLE placement_package_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    package_id uuid NOT NULL,
    prompt_bundle_id uuid NOT NULL,
    version_number integer NOT NULL CHECK (version_number > 0),
    base_version_id uuid,
    workflow_status text NOT NULL DEFAULT 'generated' CHECK (workflow_status IN (
        'generated', 'qa_running', 'pending_human_review', 'approved', 'needs_revision',
        'rejected', 'blocked', 'archived', 'superseded'
    )),
    content_json jsonb NOT NULL CHECK (jsonb_typeof(content_json) = 'object'),
    rendered_text text NOT NULL CHECK (btrim(rendered_text) <> ''),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    edited_by uuid REFERENCES identities(id),
    edit_reason text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (package_id, project_id) REFERENCES placement_packages(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_bundle_id, project_id) REFERENCES prompt_bundles(id, project_id),
    FOREIGN KEY (base_version_id, project_id) REFERENCES placement_package_versions(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (package_id, version_number),
    CHECK ((base_version_id IS NULL) = (version_number = 1)),
    CHECK (version_number = 1 OR (edited_by IS NOT NULL AND edit_reason IS NOT NULL))
);

COMMENT ON COLUMN placement_package_versions.workflow_status IS
    'Export and delivery are projections/events and never enter the asset version workflow state.';

CREATE TABLE placement_claims (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    package_version_id uuid NOT NULL,
    claim_text text NOT NULL CHECK (btrim(claim_text) <> ''),
    claim_kind text NOT NULL CHECK (claim_kind IN ('factual', 'comparative', 'experience', 'non_factual')),
    support_status text NOT NULL DEFAULT 'unreviewed' CHECK (support_status IN (
        'unreviewed', 'supported', 'unsupported', 'conflict', 'not_required'
    )),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (package_version_id, project_id) REFERENCES placement_package_versions(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (package_version_id, claim_text)
);

CREATE TABLE placement_claim_evidence (
    claim_id uuid NOT NULL,
    project_id uuid NOT NULL,
    evidence_item_id uuid NOT NULL,
    support_classification text NOT NULL CHECK (support_classification IN ('supports', 'conflicts', 'context')),
    PRIMARY KEY (claim_id, evidence_item_id),
    FOREIGN KEY (claim_id, project_id) REFERENCES placement_claims(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_item_id, project_id) REFERENCES evidence_items(id, project_id)
);

CREATE TABLE placement_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    package_version_id uuid NOT NULL,
    submitted_for_review_by uuid NOT NULL REFERENCES identities(id),
    reviewer_id uuid NOT NULL REFERENCES identities(id),
    decision text NOT NULL CHECK (decision IN ('approved', 'needs_revision', 'rejected', 'blocked')),
    claim_inventory_complete boolean NOT NULL,
    extracted_claim_support_confirmed boolean NOT NULL,
    score numeric(5,2) CHECK (score BETWEEN 0 AND 100),
    notes text,
    reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (package_version_id, project_id) REFERENCES placement_package_versions(id, project_id),
    UNIQUE (id, project_id),
    CHECK (submitted_for_review_by <> reviewer_id),
    CHECK (decision <> 'approved' OR (claim_inventory_complete AND extracted_claim_support_confirmed))
);

CREATE FUNCTION geo_assert_package_version_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.workflow_status = 'approved' AND OLD.workflow_status <> 'approved' THEN
        IF NOT EXISTS (
            SELECT 1 FROM placement_reviews r
            WHERE r.package_version_id = NEW.id AND r.project_id = NEW.project_id
              AND r.decision = 'approved' AND r.claim_inventory_complete
              AND r.extracted_claim_support_confirmed
        ) OR EXISTS (
            SELECT 1 FROM placement_claims c
            WHERE c.package_version_id = NEW.id AND c.project_id = NEW.project_id
              AND c.claim_kind <> 'non_factual' AND c.support_status <> 'supported'
        ) THEN
            RAISE EXCEPTION 'approval requires complete claim inventory and supported factual claims'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER placement_package_approval_guard
BEFORE UPDATE ON placement_package_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_package_version_approval();

CREATE TABLE publication_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    package_version_id uuid NOT NULL,
    destination_id uuid NOT NULL,
    publication_attempt integer NOT NULL DEFAULT 1 CHECK (publication_attempt > 0),
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    status text NOT NULL DEFAULT 'requested' CHECK (status IN (
        'requested', 'scheduled', 'publishing', 'retrying', 'published', 'failed', 'blocked', 'cancelled'
    )),
    requested_by uuid NOT NULL REFERENCES identities(id),
    requested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (package_version_id, project_id) REFERENCES placement_package_versions(id, project_id),
    FOREIGN KEY (destination_id, project_id) REFERENCES publication_destinations(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (project_id, idempotency_key),
    UNIQUE (project_id, package_version_id, destination_id, publication_attempt)
);

COMMENT ON TABLE publication_requests IS
    'Created only by an explicit publication command. Export and delivery MUST NOT create this row.';

CREATE FUNCTION geo_assert_publication_package_approved() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM placement_package_versions v
        WHERE v.id = NEW.package_version_id AND v.project_id = NEW.project_id
          AND v.workflow_status = 'approved'
    ) THEN
        RAISE EXCEPTION 'publication requires the exact approved package version'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER publication_requires_approved_version
BEFORE INSERT ON publication_requests
FOR EACH ROW EXECUTE FUNCTION geo_assert_publication_package_approved();

CREATE TABLE publication_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    publication_request_id uuid NOT NULL,
    submitted_url text,
    provider_submission_id text,
    status text NOT NULL DEFAULT 'awaiting_url' CHECK (status IN (
        'awaiting_url', 'submitted', 'verifying', 'verified', 'failed', 'blocked'
    )),
    submitted_at timestamptz,
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (publication_request_id, project_id) REFERENCES publication_requests(id, project_id),
    UNIQUE (id, project_id),
    CHECK (status = 'awaiting_url' OR submitted_url IS NOT NULL)
);

CREATE TABLE placement_measurements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    submission_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    measured_at timestamptz NOT NULL,
    citation_present boolean NOT NULL,
    recommendation_position integer CHECK (recommendation_position > 0),
    result_snapshot_uri text NOT NULL CHECK (btrim(result_snapshot_uri) <> ''),
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metrics) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (submission_id, project_id) REFERENCES publication_submissions(id, project_id),
    FOREIGN KEY (monitoring_query_id, project_id) REFERENCES monitoring_queries(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (submission_id, monitoring_query_id, measured_at)
);

CREATE TABLE durable_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (btrim(kind) <> ''),
    status text NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'running', 'finalizing', 'retry_wait', 'succeeded', 'failed',
        'dead_lettered', 'cancelled'
    )),
    priority integer NOT NULL DEFAULT 0,
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
    next_run_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    fencing_generation bigint NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
    cancel_requested_at timestamptz,
    error_code text,
    error_detail jsonb,
    result_ref text,
    parent_job_id uuid,
    replay_nonce integer NOT NULL DEFAULT 0 CHECK (replay_nonce >= 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    FOREIGN KEY (parent_job_id, project_id) REFERENCES durable_jobs(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (project_id, kind, idempotency_key, replay_nonce),
    CHECK (
        (status IN ('running', 'finalizing') AND lease_owner IS NOT NULL
            AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR (status NOT IN ('running', 'finalizing') AND lease_owner IS NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL)
    )
);

CREATE INDEX durable_jobs_claim_idx
ON durable_jobs (priority DESC, next_run_at, created_at)
WHERE status IN ('queued', 'retry_wait');

CREATE INDEX durable_jobs_reclaim_idx
ON durable_jobs (lease_expires_at)
WHERE status IN ('running', 'finalizing');

CREATE INDEX durable_jobs_project_activity_idx
ON durable_jobs (project_id, updated_at DESC, id DESC);

CREATE TABLE collection_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    provider_keys text[] NOT NULL,
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    UNIQUE (job_id, project_id)
);

CREATE TABLE collection_job_queries (
    job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    PRIMARY KEY (job_id, monitoring_query_id),
    FOREIGN KEY (job_id, project_id) REFERENCES collection_job_specs(job_id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (monitoring_query_id, project_id) REFERENCES monitoring_queries(id, project_id)
);

CREATE TABLE evidence_pack_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    brief_version_id uuid NOT NULL,
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (brief_version_id, project_id) REFERENCES placement_brief_versions(id, project_id)
);

CREATE TABLE generation_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    prompt_bundle_id uuid NOT NULL,
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    model_call_budget integer NOT NULL CHECK (model_call_budget > 0),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_bundle_id, project_id) REFERENCES prompt_bundles(id, project_id)
);

CREATE TABLE verification_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    submission_id uuid NOT NULL,
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (submission_id, project_id) REFERENCES publication_submissions(id, project_id)
);

CREATE TABLE measurement_job_specs (
    job_id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    submission_id uuid NOT NULL,
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (submission_id, project_id) REFERENCES publication_submissions(id, project_id),
    UNIQUE (job_id, project_id)
);

CREATE TABLE measurement_job_queries (
    job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    PRIMARY KEY (job_id, monitoring_query_id),
    FOREIGN KEY (job_id, project_id) REFERENCES measurement_job_specs(job_id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (monitoring_query_id, project_id) REFERENCES monitoring_queries(id, project_id)
);

CREATE FUNCTION geo_assert_domain_job_kind() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM durable_jobs j
        WHERE j.id = NEW.job_id AND j.project_id = NEW.project_id AND j.kind = TG_ARGV[0]
    ) THEN
        RAISE EXCEPTION 'domain job spec does not match durable job kind'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER collection_job_spec_kind
BEFORE INSERT OR UPDATE ON collection_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('collection.run');
CREATE TRIGGER evidence_pack_job_spec_kind
BEFORE INSERT OR UPDATE ON evidence_pack_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('evidence_pack.build');
CREATE TRIGGER generation_job_spec_kind
BEFORE INSERT OR UPDATE ON generation_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('placement.generate');
CREATE TRIGGER verification_job_spec_kind
BEFORE INSERT OR UPDATE ON verification_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('publication.verify');
CREATE TRIGGER measurement_job_spec_kind
BEFORE INSERT OR UPDATE ON measurement_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_assert_domain_job_kind('placement.measure');

COMMENT ON TABLE durable_jobs IS
    'PostgreSQL is authoritative. Queue messages are wakeups; workers claim with SKIP LOCKED and fence every mutation.';
COMMENT ON COLUMN durable_jobs.attempt_count IS
    'One total provider-call budget must include retries, schema repair and fallback.';

CREATE TABLE broker_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    topic text NOT NULL CHECK (btrim(topic) <> ''),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    idempotency_key text NOT NULL,
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (project_id, idempotency_key)
);

CREATE TABLE artifact_finalize_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    pending_uri text NOT NULL CHECK (btrim(pending_uri) <> ''),
    final_uri text NOT NULL CHECK (btrim(final_uri) <> ''),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'finalizing', 'finalized', 'failed')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    finalized_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (job_id, project_id) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (job_id, final_uri)
);

-- The baseline vector contract is BGE-M3 at 1024 dimensions and cosine distance.
CREATE TABLE evidence_embeddings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    evidence_item_id uuid NOT NULL,
    model_key text NOT NULL CHECK (btrim(model_key) <> ''),
    embedding vector(1024) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (evidence_item_id, project_id) REFERENCES evidence_items(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (evidence_item_id, model_key)
);

CREATE INDEX evidence_embeddings_hnsw_cosine_idx
ON evidence_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX evidence_embeddings_project_model_idx
ON evidence_embeddings (project_id, model_key);

CREATE TRIGGER placement_brief_versions_immutable
BEFORE UPDATE OR DELETE ON placement_brief_versions
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER evidence_items_immutable
BEFORE UPDATE OR DELETE ON evidence_items
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER evidence_pack_items_immutable
BEFORE UPDATE OR DELETE ON evidence_pack_items
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER evidence_pack_attempt_terminal_immutable
BEFORE UPDATE OR DELETE ON evidence_pack_attempts
FOR EACH ROW EXECUTE FUNCTION geo_protect_evidence_pack_attempt();
CREATE TRIGGER placement_brief_subject_entities_immutable
BEFORE UPDATE OR DELETE ON placement_brief_subject_entities
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_skill_versions_immutable
BEFORE UPDATE OR DELETE ON prompt_skill_versions
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER generation_template_releases_immutable
BEFORE UPDATE OR DELETE ON generation_template_releases
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_bundles_immutable
BEFORE UPDATE OR DELETE ON prompt_bundles
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER placement_package_content_immutable
BEFORE UPDATE ON placement_package_versions
FOR EACH ROW EXECUTE FUNCTION geo_protect_package_version_content();
CREATE TRIGGER placement_package_versions_no_delete
BEFORE DELETE ON placement_package_versions
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER placement_claims_immutable
BEFORE UPDATE OR DELETE ON placement_claims
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER placement_claim_evidence_immutable
BEFORE UPDATE OR DELETE ON placement_claim_evidence
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER placement_reviews_immutable
BEFORE UPDATE OR DELETE ON placement_reviews
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

-- Every project-owned table is both RLS-enabled and project constrained by its foreign keys.
DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'projects', 'project_memberships', 'product_entities', 'market_profiles',
        'monitoring_queries', 'evidence_items', 'geo_campaigns', 'campaign_entities',
        'campaign_monitoring_queries', 'publication_destinations', 'placement_opportunities',
        'placement_briefs', 'placement_brief_versions', 'placement_brief_subject_entities',
        'evidence_pack_attempts', 'evidence_pack_items', 'prompt_skills', 'prompt_skill_versions',
        'generation_template_releases', 'prompt_bundles', 'placement_packages',
        'placement_package_versions', 'placement_claims', 'placement_claim_evidence',
        'placement_reviews', 'publication_requests', 'publication_submissions',
        'placement_measurements', 'durable_jobs', 'collection_job_specs', 'collection_job_queries',
        'evidence_pack_job_specs', 'generation_job_specs', 'verification_job_specs',
        'measurement_job_specs', 'measurement_job_queries', 'broker_outbox', 'artifact_finalize_outbox',
        'evidence_embeddings'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        IF table_name = 'projects' THEN
            EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
                || ' USING (id = ANY(geo_current_project_ids()))'
                || ' WITH CHECK (id = ANY(geo_current_project_ids()))';
        ELSIF table_name = 'project_memberships' THEN
            EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
                || ' USING (identity_id = geo_current_identity_id()'
                || ' AND tenant_id = geo_current_tenant_id())'
                || ' WITH CHECK (identity_id = geo_current_identity_id()'
                || ' AND tenant_id = geo_current_tenant_id())';
        ELSE
            EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
                || ' USING (project_id = ANY(geo_current_project_ids()))'
                || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
        END IF;
    END LOOP;
END;
$$;

GRANT USAGE ON SCHEMA public TO geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO geo_app, geo_worker;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO geo_readonly;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO geo_app, geo_worker;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO geo_app, geo_worker, geo_readonly;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO geo_app, geo_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO geo_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO geo_app, geo_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO geo_app, geo_worker, geo_readonly;
