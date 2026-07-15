-- Governed monitoring protocols keep monitoring_queries as the sole query source of truth.

ALTER TABLE geo_campaigns
    ADD CONSTRAINT geo_campaigns_id_market_project_key
    UNIQUE (id, market_profile_id, project_id);

CREATE TABLE monitoring_protocols (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    market_profile_id uuid NOT NULL,
    name text NOT NULL CHECK (btrim(name) <> ''),
    platform text NOT NULL CHECK (platform IN (
        'chatgpt_search', 'google_ai_overviews', 'google_search',
        'perplexity', 'gemini', 'other'
    )),
    locale text NOT NULL CHECK (btrim(locale) <> ''),
    device text NOT NULL CHECK (device IN ('desktop', 'mobile', 'tablet')),
    sample_size integer NOT NULL CHECK (sample_size BETWEEN 1 AND 1000),
    window_days integer NOT NULL CHECK (window_days BETWEEN 1 AND 365),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'frozen')),
    protocol_hash text CHECK (protocol_hash ~ '^[0-9a-f]{64}$'),
    created_by uuid NOT NULL REFERENCES identities(id),
    approved_by uuid REFERENCES identities(id),
    approved_at timestamptz,
    frozen_by uuid REFERENCES identities(id),
    frozen_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (campaign_id, market_profile_id, project_id)
        REFERENCES geo_campaigns(id, market_profile_id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (id, campaign_id, project_id),
    UNIQUE (project_id, name),
    CHECK (
        (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL
            AND frozen_by IS NULL AND frozen_at IS NULL AND protocol_hash IS NULL)
        OR (status = 'approved' AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND frozen_by IS NULL AND frozen_at IS NULL AND protocol_hash IS NULL)
        OR (status = 'frozen' AND approved_by IS NOT NULL AND approved_at IS NOT NULL
            AND frozen_by IS NOT NULL AND frozen_at IS NOT NULL AND protocol_hash IS NOT NULL)
    )
);

CREATE TABLE monitoring_query_suggestions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_id uuid NOT NULL,
    query_text text NOT NULL CHECK (btrim(query_text) <> ''),
    query_kind text NOT NULL CHECK (query_kind IN (
        'recommendation', 'comparison', 'research', 'support'
    )),
    rationale text NOT NULL CHECK (btrim(rationale) <> ''),
    status text NOT NULL DEFAULT 'suggested' CHECK (status IN (
        'suggested', 'approved', 'rejected'
    )),
    suggested_by uuid NOT NULL REFERENCES identities(id),
    decided_by uuid REFERENCES identities(id),
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (protocol_id, project_id)
        REFERENCES monitoring_protocols(id, project_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (protocol_id, id),
    UNIQUE (id, protocol_id, project_id),
    CHECK ((status = 'suggested') = (decided_by IS NULL AND decided_at IS NULL))
);

CREATE UNIQUE INDEX monitoring_query_suggestions_text_idx
ON monitoring_query_suggestions (protocol_id, lower(btrim(query_text)));

CREATE TABLE monitoring_protocol_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    suggestion_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    query_text_snapshot text NOT NULL CHECK (btrim(query_text_snapshot) <> ''),
    query_kind_snapshot text NOT NULL CHECK (query_kind_snapshot IN (
        'recommendation', 'comparison', 'research', 'support'
    )),
    locale_snapshot text NOT NULL CHECK (btrim(locale_snapshot) <> ''),
    approved_by uuid NOT NULL REFERENCES identities(id),
    approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (protocol_id, project_id)
        REFERENCES monitoring_protocols(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (monitoring_query_id, project_id)
        REFERENCES monitoring_queries(id, project_id),
    FOREIGN KEY (suggestion_id, protocol_id, project_id)
        REFERENCES monitoring_query_suggestions(id, protocol_id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (id, protocol_id, project_id),
    UNIQUE (protocol_id, monitoring_query_id),
    UNIQUE (protocol_id, suggestion_id),
    UNIQUE (protocol_id, ordinal),
    UNIQUE (protocol_id, monitoring_query_id, project_id)
);

CREATE TABLE monitoring_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    measurement_window text NOT NULL CHECK (measurement_window IN (
        'baseline', 't28', 't56', 't84', 'ad_hoc'
    )),
    sample_index integer NOT NULL CHECK (sample_index > 0),
    result_status text NOT NULL CHECK (result_status IN ('succeeded', 'failed')),
    eligible boolean NOT NULL,
    ineligible_reasons text[] NOT NULL DEFAULT ARRAY[]::text[],
    url_verification_status text NOT NULL CHECK (url_verification_status IN (
        'passed', 'failed', 'unknown'
    )),
    recommendation_present boolean NOT NULL DEFAULT false,
    primary_product_mentioned boolean NOT NULL DEFAULT false,
    competitor_mentioned boolean NOT NULL DEFAULT false,
    raw_answer text,
    raw_result jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(raw_result) = 'object'),
    raw_citations jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(raw_citations) = 'array'),
    artifact_uri text CHECK (artifact_uri IS NULL OR artifact_uri ~ '^s3://[^/]+/.+$'),
    artifact_hash text CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    provider_reported_model text,
    ui_surface text NOT NULL CHECK (btrim(ui_surface) <> ''),
    ui_metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(ui_metadata) = 'object'),
    confounding_factors text[] NOT NULL DEFAULT ARRAY[]::text[],
    observed_at timestamptz NOT NULL,
    imported_by uuid NOT NULL REFERENCES identities(id),
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (protocol_id, campaign_id, project_id)
        REFERENCES monitoring_protocols(id, campaign_id, project_id),
    FOREIGN KEY (protocol_id, monitoring_query_id, project_id)
        REFERENCES monitoring_protocol_queries(protocol_id, monitoring_query_id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (project_id, idempotency_key),
    UNIQUE (protocol_id, monitoring_query_id, measurement_window, sample_index),
    CHECK ((artifact_uri IS NULL) = (artifact_hash IS NULL)),
    CHECK (eligible OR cardinality(ineligible_reasons) > 0),
    CHECK (result_status = 'succeeded' OR NOT eligible)
);

CREATE TABLE monitoring_observation_citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    observation_id uuid NOT NULL,
    citation_index integer NOT NULL CHECK (citation_index >= 0),
    url text NOT NULL CHECK (url ~ '^https?://'),
    title text,
    destination_id uuid,
    submission_id uuid,
    verification_status text NOT NULL CHECK (verification_status IN (
        'passed', 'failed', 'unknown'
    )),
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (observation_id, project_id)
        REFERENCES monitoring_observations(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (destination_id, project_id)
        REFERENCES publication_destinations(id, project_id),
    FOREIGN KEY (submission_id, project_id)
        REFERENCES publication_submissions(id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (observation_id, citation_index),
    CHECK ((verification_status = 'passed') = (verified_at IS NOT NULL)),
    CHECK (submission_id IS NULL OR destination_id IS NOT NULL)
);

CREATE TABLE monitoring_metric_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    measurement_window text NOT NULL CHECK (measurement_window IN (
        'baseline', 't28', 't56', 't84', 'ad_hoc'
    )),
    expected_sample_count integer NOT NULL CHECK (expected_sample_count > 0),
    eligible_sample_count integer NOT NULL CHECK (
        eligible_sample_count >= 0 AND eligible_sample_count <= expected_sample_count
    ),
    recommendation_share numeric(9, 6) NOT NULL CHECK (recommendation_share BETWEEN 0 AND 1),
    product_mention_share numeric(9, 6) NOT NULL CHECK (product_mention_share BETWEEN 0 AND 1),
    placement_citation_share numeric(9, 6) NOT NULL CHECK (placement_citation_share BETWEEN 0 AND 1),
    qualified_destination_coverage numeric(9, 6) NOT NULL CHECK (qualified_destination_coverage BETWEEN 0 AND 1),
    verified_placement_coverage numeric(9, 6) NOT NULL CHECK (verified_placement_coverage BETWEEN 0 AND 1),
    competitive_delta numeric(9, 6) NOT NULL CHECK (competitive_delta BETWEEN -1 AND 1),
    status text NOT NULL CHECK (status IN ('complete', 'confounded')),
    confounded_reasons text[] NOT NULL DEFAULT ARRAY[]::text[],
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    method_version text NOT NULL CHECK (btrim(method_version) <> ''),
    computed_by uuid NOT NULL REFERENCES identities(id),
    computed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (protocol_id, campaign_id, project_id)
        REFERENCES monitoring_protocols(id, campaign_id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (id, protocol_id, campaign_id, project_id),
    UNIQUE (protocol_id, measurement_window, input_hash),
    CHECK ((status = 'confounded') = (cardinality(confounded_reasons) > 0))
);

CREATE TABLE monitoring_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_id uuid NOT NULL,
    campaign_id uuid NOT NULL,
    metric_snapshot_id uuid NOT NULL,
    title text NOT NULL CHECK (btrim(title) <> ''),
    body text NOT NULL CHECK (btrim(body) <> ''),
    methodology_statement text NOT NULL CHECK (
        methodology_statement = 'Observational monitoring only; results are non-causal and do not prove that a placement caused any change.'
    ),
    report_hash text NOT NULL CHECK (report_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
    generated_by uuid NOT NULL REFERENCES identities(id),
    generated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    approved_by uuid REFERENCES identities(id),
    approved_at timestamptz,
    FOREIGN KEY (protocol_id, campaign_id, project_id)
        REFERENCES monitoring_protocols(id, campaign_id, project_id),
    FOREIGN KEY (metric_snapshot_id, protocol_id, campaign_id, project_id)
        REFERENCES monitoring_metric_snapshots(id, protocol_id, campaign_id, project_id),
    UNIQUE (id, project_id),
    UNIQUE (project_id, report_hash),
    CHECK ((status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

CREATE FUNCTION geo_protect_monitoring_protocol() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'monitoring protocols cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF OLD.status = 'frozen' THEN
        RAISE EXCEPTION 'frozen monitoring protocols are immutable' USING ERRCODE = '55000';
    END IF;
    IF NOT ((OLD.status = 'draft' AND NEW.status IN ('draft', 'approved'))
            OR (OLD.status = 'approved' AND NEW.status IN ('approved', 'frozen'))) THEN
        RAISE EXCEPTION 'invalid monitoring protocol transition' USING ERRCODE = '23514';
    END IF;
    IF NEW.status IN ('approved', 'frozen') AND NOT EXISTS (
        SELECT 1 FROM monitoring_protocol_queries q
        WHERE q.protocol_id = NEW.id AND q.project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'approved monitoring protocols require an approved query'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_protect_monitoring_protocol_child() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_protocol_id uuid;
    target_project_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_protocol_id := OLD.protocol_id;
        target_project_id := OLD.project_id;
    ELSE
        target_protocol_id := NEW.protocol_id;
        target_project_id := NEW.project_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM monitoring_protocols p
        WHERE p.id = target_protocol_id AND p.project_id = target_project_id
          AND p.status = 'frozen'
    ) THEN
        RAISE EXCEPTION 'frozen monitoring protocol query inventory is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_monitoring_observation_slot() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    protocol_sample_size integer;
BEGIN
    SELECT sample_size INTO protocol_sample_size
    FROM monitoring_protocols
    WHERE id = NEW.protocol_id AND project_id = NEW.project_id AND status = 'frozen';
    IF protocol_sample_size IS NULL THEN
        RAISE EXCEPTION 'observations require a frozen monitoring protocol'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.sample_index > protocol_sample_size THEN
        RAISE EXCEPTION 'sample index exceeds the frozen protocol sample size'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_protect_monitoring_report() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' OR OLD.status = 'approved' THEN
        RAISE EXCEPTION 'approved monitoring reports are immutable' USING ERRCODE = '55000';
    END IF;
    IF (NEW.project_id, NEW.protocol_id, NEW.metric_snapshot_id, NEW.title, NEW.body,
        NEW.methodology_statement, NEW.report_hash, NEW.generated_by, NEW.generated_at)
       IS DISTINCT FROM
       (OLD.project_id, OLD.protocol_id, OLD.metric_snapshot_id, OLD.title, OLD.body,
        OLD.methodology_statement, OLD.report_hash, OLD.generated_by, OLD.generated_at) THEN
        RAISE EXCEPTION 'monitoring report content is immutable' USING ERRCODE = '55000';
    END IF;
    IF OLD.status <> 'draft' OR NEW.status <> 'approved' THEN
        RAISE EXCEPTION 'invalid monitoring report transition' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER monitoring_protocol_guard
BEFORE UPDATE OR DELETE ON monitoring_protocols
FOR EACH ROW EXECUTE FUNCTION geo_protect_monitoring_protocol();
CREATE TRIGGER monitoring_suggestion_protocol_guard
BEFORE INSERT OR UPDATE OR DELETE ON monitoring_query_suggestions
FOR EACH ROW EXECUTE FUNCTION geo_protect_monitoring_protocol_child();
CREATE TRIGGER monitoring_protocol_query_guard
BEFORE INSERT OR UPDATE OR DELETE ON monitoring_protocol_queries
FOR EACH ROW EXECUTE FUNCTION geo_protect_monitoring_protocol_child();
CREATE TRIGGER monitoring_observation_slot_guard
BEFORE INSERT ON monitoring_observations
FOR EACH ROW EXECUTE FUNCTION geo_assert_monitoring_observation_slot();
CREATE TRIGGER monitoring_observations_immutable
BEFORE UPDATE OR DELETE ON monitoring_observations
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER monitoring_observation_citations_immutable
BEFORE UPDATE OR DELETE ON monitoring_observation_citations
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER monitoring_metric_snapshots_immutable
BEFORE UPDATE OR DELETE ON monitoring_metric_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER monitoring_report_guard
BEFORE UPDATE OR DELETE ON monitoring_reports
FOR EACH ROW EXECUTE FUNCTION geo_protect_monitoring_report();

CREATE INDEX monitoring_protocols_project_status_idx
ON monitoring_protocols (project_id, status, created_at DESC);
CREATE INDEX monitoring_protocol_queries_protocol_idx
ON monitoring_protocol_queries (project_id, protocol_id, ordinal);
CREATE INDEX monitoring_observations_window_idx
ON monitoring_observations (project_id, protocol_id, measurement_window, created_at);
CREATE INDEX monitoring_observations_eligible_idx
ON monitoring_observations (project_id, protocol_id, measurement_window)
WHERE eligible AND result_status = 'succeeded' AND url_verification_status = 'passed';
CREATE INDEX monitoring_observation_citations_verified_idx
ON monitoring_observation_citations (project_id, destination_id, observation_id)
WHERE verification_status = 'passed';
CREATE INDEX monitoring_metric_snapshots_latest_idx
ON monitoring_metric_snapshots (project_id, protocol_id, measurement_window, computed_at DESC);
CREATE INDEX monitoring_reports_customer_idx
ON monitoring_reports (project_id, approved_at DESC)
WHERE status = 'approved';

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'monitoring_protocols', 'monitoring_query_suggestions',
        'monitoring_protocol_queries', 'monitoring_observations',
        'monitoring_observation_citations', 'monitoring_metric_snapshots',
        'monitoring_reports'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON monitoring_protocols,
    monitoring_query_suggestions, monitoring_protocol_queries,
    monitoring_observations, monitoring_observation_citations,
    monitoring_metric_snapshots, monitoring_reports TO geo_app, geo_worker;
GRANT SELECT ON monitoring_protocols, monitoring_query_suggestions,
    monitoring_protocol_queries, monitoring_observations,
    monitoring_observation_citations, monitoring_metric_snapshots,
    monitoring_reports TO geo_readonly;
GRANT EXECUTE ON FUNCTION geo_protect_monitoring_protocol(),
    geo_protect_monitoring_protocol_child(), geo_assert_monitoring_observation_slot(),
    geo_protect_monitoring_report() TO geo_app, geo_worker, geo_readonly;
