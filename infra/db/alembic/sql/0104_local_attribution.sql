CREATE TABLE attribution_policies (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version integer NOT NULL CHECK (version > 0),
    last_click_days integer NOT NULL CHECK (last_click_days BETWEEN 1 AND 365),
    assisted_days integer NOT NULL CHECK (assisted_days BETWEEN last_click_days AND 730),
    direct_rule text NOT NULL CHECK (direct_rule = 'only_without_eligible_touch'),
    eligible_touch_types text[] NOT NULL CHECK (cardinality(eligible_touch_types) > 0),
    policy_hash text NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('active', 'retired')),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    retired_at timestamptz,
    UNIQUE (id, project_id),
    UNIQUE (project_id, version),
    UNIQUE (project_id, policy_hash),
    CHECK ((status = 'retired') = (retired_at IS NOT NULL))
);

CREATE UNIQUE INDEX attribution_policies_one_active
ON attribution_policies(project_id) WHERE status = 'active';

CREATE TABLE attribution_collectors (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    write_key_hash text NOT NULL CHECK (write_key_hash ~ '^[0-9a-f]{64}$'),
    allowed_origins text[] NOT NULL CHECK (cardinality(allowed_origins) > 0),
    event_schema_version text NOT NULL CHECK (btrim(event_schema_version) <> ''),
    sdk_release text NOT NULL CHECK (btrim(sdk_release) <> ''),
    consent_mode text NOT NULL CHECK (consent_mode = 'explicit'),
    status text NOT NULL CHECK (status IN ('active', 'disabled')),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    disabled_at timestamptz,
    UNIQUE (id, project_id),
    UNIQUE (project_id, name),
    CHECK ((status = 'disabled') = (disabled_at IS NOT NULL))
);

CREATE TABLE attribution_trace_links (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    token_hash text NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    campaign_id uuid NOT NULL,
    question_set_id uuid,
    package_version_id uuid,
    content_asset_key text NOT NULL CHECK (btrim(content_asset_key) <> ''),
    verified_url text NOT NULL CHECK (verified_url ~ '^https://'),
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    created_by uuid NOT NULL REFERENCES identities(id),
    UNIQUE (id, project_id),
    UNIQUE (project_id, token_hash),
    FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id),
    FOREIGN KEY (package_version_id, project_id)
        REFERENCES placement_package_versions(id, project_id),
    CHECK (expires_at > issued_at)
);

CREATE TABLE attribution_sessions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    collector_id uuid NOT NULL,
    client_session_id uuid NOT NULL,
    started_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    consent_schema_version text NOT NULL CHECK (btrim(consent_schema_version) <> ''),
    event_schema_version text NOT NULL CHECK (btrim(event_schema_version) <> ''),
    sdk_release text NOT NULL CHECK (btrim(sdk_release) <> ''),
    source_type text NOT NULL CHECK (source_type = 'first_party_browser'),
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    UNIQUE (id, project_id),
    UNIQUE (project_id, collector_id, client_session_id),
    FOREIGN KEY (collector_id, project_id) REFERENCES attribution_collectors(id, project_id),
    CHECK (last_seen_at >= started_at)
);

CREATE TABLE attribution_touches (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id uuid NOT NULL,
    source_event_id text NOT NULL CHECK (btrim(source_event_id) <> ''),
    touch_type text NOT NULL CHECK (touch_type IN ('page_view', 'click', 'direct')),
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    trace_link_id uuid,
    utm jsonb NOT NULL CHECK (jsonb_typeof(utm) = 'object'),
    source_type text NOT NULL CHECK (source_type = 'first_party_browser'),
    schema_version text NOT NULL CHECK (btrim(schema_version) <> ''),
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    UNIQUE (id, project_id),
    UNIQUE (project_id, source_event_id),
    FOREIGN KEY (session_id, project_id) REFERENCES attribution_sessions(id, project_id),
    FOREIGN KEY (trace_link_id, project_id) REFERENCES attribution_trace_links(id, project_id),
    CHECK (touch_type = 'direct' OR trace_link_id IS NOT NULL)
);

CREATE TABLE attribution_exposures (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    source_event_id text NOT NULL CHECK (btrim(source_event_id) <> ''),
    occurred_at timestamptz NOT NULL,
    source_kind text NOT NULL CHECK (btrim(source_kind) <> ''),
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    UNIQUE (id, project_id),
    UNIQUE (project_id, source_event_id),
    FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id)
);

CREATE TABLE attribution_imports (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    template_schema_version text NOT NULL CHECK (btrim(template_schema_version) <> ''),
    file_hash text NOT NULL CHECK (file_hash ~ '^[0-9a-f]{64}$'),
    row_count integer NOT NULL CHECK (row_count >= 0),
    accepted_count integer NOT NULL CHECK (accepted_count >= 0),
    rejected_count integer NOT NULL CHECK (rejected_count >= 0),
    requested_by uuid NOT NULL REFERENCES identities(id),
    requested_at timestamptz NOT NULL,
    result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
    UNIQUE (id, project_id),
    UNIQUE (project_id, file_hash),
    CHECK (row_count = accepted_count + rejected_count)
);

CREATE TABLE attribution_leads (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_id uuid NOT NULL,
    source_event_id text NOT NULL CHECK (btrim(source_event_id) <> ''),
    local_business_id text NOT NULL CHECK (btrim(local_business_id) <> ''),
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('admin', 'file_import')),
    schema_version text NOT NULL CHECK (btrim(schema_version) <> ''),
    import_id uuid,
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    UNIQUE (id, project_id), UNIQUE (project_id, source_event_id),
    UNIQUE (project_id, local_business_id),
    FOREIGN KEY (session_id, project_id) REFERENCES attribution_sessions(id, project_id),
    FOREIGN KEY (import_id, project_id) REFERENCES attribution_imports(id, project_id)
);

CREATE TABLE attribution_stages (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL,
    source_event_id text NOT NULL CHECK (btrim(source_event_id) <> ''),
    stage text NOT NULL CHECK (btrim(stage) <> ''),
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('admin', 'file_import')),
    schema_version text NOT NULL CHECK (btrim(schema_version) <> ''),
    import_id uuid,
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    UNIQUE (id, project_id), UNIQUE (project_id, source_event_id),
    FOREIGN KEY (lead_id, project_id) REFERENCES attribution_leads(id, project_id),
    FOREIGN KEY (import_id, project_id) REFERENCES attribution_imports(id, project_id)
);

CREATE TABLE attribution_conversions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL,
    source_event_id text NOT NULL CHECK (btrim(source_event_id) <> ''),
    conversion_kind text NOT NULL CHECK (btrim(conversion_kind) <> ''),
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('admin', 'file_import')),
    schema_version text NOT NULL CHECK (btrim(schema_version) <> ''),
    import_id uuid,
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    UNIQUE (id, project_id), UNIQUE (project_id, source_event_id),
    FOREIGN KEY (lead_id, project_id) REFERENCES attribution_leads(id, project_id),
    FOREIGN KEY (import_id, project_id) REFERENCES attribution_imports(id, project_id)
);

CREATE TABLE attribution_deals (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    conversion_id uuid NOT NULL,
    source_event_id text NOT NULL CHECK (btrim(source_event_id) <> ''),
    local_business_id text NOT NULL CHECK (btrim(local_business_id) <> ''),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    amount numeric(18,2) NOT NULL CHECK (amount >= 0),
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('admin', 'file_import')),
    schema_version text NOT NULL CHECK (btrim(schema_version) <> ''),
    import_id uuid,
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    UNIQUE (id, project_id), UNIQUE (project_id, source_event_id),
    UNIQUE (project_id, local_business_id),
    FOREIGN KEY (conversion_id, project_id)
        REFERENCES attribution_conversions(id, project_id),
    FOREIGN KEY (import_id, project_id) REFERENCES attribution_imports(id, project_id)
);

CREATE TABLE attribution_revenues (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    deal_id uuid NOT NULL,
    source_event_id text NOT NULL CHECK (btrim(source_event_id) <> ''),
    revenue_kind text NOT NULL CHECK (revenue_kind IN ('booked', 'recognized')),
    currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    amount numeric(18,2) NOT NULL CHECK (amount >= 0),
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('admin', 'file_import')),
    schema_version text NOT NULL CHECK (btrim(schema_version) <> ''),
    import_id uuid,
    lineage jsonb NOT NULL CHECK (jsonb_typeof(lineage) = 'object'),
    UNIQUE (id, project_id), UNIQUE (project_id, source_event_id),
    FOREIGN KEY (deal_id, project_id) REFERENCES attribution_deals(id, project_id),
    FOREIGN KEY (import_id, project_id) REFERENCES attribution_imports(id, project_id)
);

CREATE TABLE attribution_snapshots (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    policy_id uuid NOT NULL,
    cutoff_at timestamptz NOT NULL,
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
    result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    UNIQUE (id, project_id), UNIQUE (project_id, input_hash),
    FOREIGN KEY (policy_id, project_id) REFERENCES attribution_policies(id, project_id)
);

CREATE FUNCTION geo_attribution_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'Attribution evidence is immutable' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER attribution_trace_links_immutable BEFORE UPDATE OR DELETE ON attribution_trace_links
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();
CREATE TRIGGER attribution_touches_immutable BEFORE UPDATE OR DELETE ON attribution_touches
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();
CREATE TRIGGER attribution_exposures_immutable BEFORE UPDATE OR DELETE ON attribution_exposures
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();
CREATE TRIGGER attribution_leads_immutable BEFORE UPDATE OR DELETE ON attribution_leads
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();
CREATE TRIGGER attribution_stages_immutable BEFORE UPDATE OR DELETE ON attribution_stages
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();
CREATE TRIGGER attribution_conversions_immutable BEFORE UPDATE OR DELETE ON attribution_conversions
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();
CREATE TRIGGER attribution_deals_immutable BEFORE UPDATE OR DELETE ON attribution_deals
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();
CREATE TRIGGER attribution_revenues_immutable BEFORE UPDATE OR DELETE ON attribution_revenues
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();
CREATE TRIGGER attribution_snapshots_immutable BEFORE UPDATE OR DELETE ON attribution_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_attribution_immutable();

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'attribution_policies','attribution_collectors','attribution_trace_links',
    'attribution_sessions','attribution_touches','attribution_exposures',
    'attribution_imports','attribution_leads','attribution_stages',
    'attribution_conversions','attribution_deals','attribution_revenues',
    'attribution_snapshots'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY project_scope ON %I USING (project_id = ANY(geo_current_project_ids())) WITH CHECK (project_id = ANY(geo_current_project_ids()))',
      table_name
    );
    EXECUTE format('REVOKE ALL ON %I FROM PUBLIC, geo_app, geo_worker, geo_readonly', table_name);
    EXECUTE format('GRANT SELECT, INSERT ON %I TO geo_app', table_name);
    EXECUTE format('GRANT SELECT ON %I TO geo_worker, geo_readonly', table_name);
  END LOOP;
END $$;

GRANT UPDATE (last_seen_at) ON attribution_sessions TO geo_app;
GRANT UPDATE (status, retired_at) ON attribution_policies TO geo_app;
GRANT UPDATE (status, disabled_at) ON attribution_collectors TO geo_app;
