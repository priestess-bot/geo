CREATE TABLE browser_surface_releases (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    platform text NOT NULL CHECK (platform IN ('google', 'bing')),
    surface text NOT NULL CHECK (surface IN (
        'google_ai_overviews', 'google_ai_mode', 'bing_copilot'
    )),
    release_version text NOT NULL CHECK (btrim(release_version) <> ''),
    entry_url_template text NOT NULL CHECK (entry_url_template ~ '^https://'),
    allowed_hosts text[] NOT NULL CHECK (cardinality(allowed_hosts) > 0),
    selectors jsonb NOT NULL CHECK (jsonb_typeof(selectors) = 'object'),
    block_detectors jsonb NOT NULL CHECK (jsonb_typeof(block_detectors) = 'object'),
    parser_release text NOT NULL CHECK (btrim(parser_release) <> ''),
    browser_release text NOT NULL CHECK (btrim(browser_release) <> ''),
    authorization_track text NOT NULL CHECK (authorization_track IN ('A', 'B')),
    authorization_status text NOT NULL CHECK (authorization_status IN (
        'not_assessed', 'approved', 'restricted', 'prohibited', 'expired', 'revoked'
    )),
    authorization_reference text,
    authorization_valid_until timestamptz,
    terms_version text NOT NULL CHECK (btrim(terms_version) <> ''),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('draft', 'approved', 'retired')),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    approved_by uuid REFERENCES identities(id),
    approved_at timestamptz,
    UNIQUE (id, project_id),
    UNIQUE (project_id, surface, release_version),
    UNIQUE (project_id, release_hash),
    CHECK (
      (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
      OR (status IN ('approved', 'retired') AND approved_by IS NOT NULL
          AND approved_at IS NOT NULL AND approved_by <> created_by)
    ),
    CHECK (
      status <> 'approved'
      OR (authorization_status = 'approved' AND authorization_reference IS NOT NULL
          AND authorization_valid_until > approved_at)
    )
);

CREATE TABLE browser_egress_endpoints (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    protocol text NOT NULL CHECK (protocol IN ('http', 'https', 'socks5')),
    endpoint_host text NOT NULL CHECK (btrim(endpoint_host) <> ''),
    endpoint_port integer NOT NULL CHECK (endpoint_port BETWEEN 1 AND 65535),
    secret_reference_id uuid NOT NULL,
    secret_purpose text NOT NULL CHECK (secret_purpose LIKE 'browser_egress.%'),
    secret_version integer NOT NULL CHECK (secret_version > 0),
    expected_country text NOT NULL CHECK (expected_country = 'AU'),
    expected_region text,
    network_type text NOT NULL CHECK (network_type IN (
        'residential', 'mobile', 'datacenter', 'unknown'
    )),
    sticky_mode text NOT NULL CHECK (sticky_mode IN (
        'provider_lease', 'credential_session', 'trusted_connection_log'
    )),
    egress_policy_version text NOT NULL CHECK (btrim(egress_policy_version) <> ''),
    egress_cohort_key text NOT NULL CHECK (btrim(egress_cohort_key) <> ''),
    status text NOT NULL CHECK (status IN ('draft', 'approved', 'disabled', 'revoked')),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    approved_by uuid REFERENCES identities(id),
    approved_at timestamptz,
    disabled_at timestamptz,
    UNIQUE (id, project_id), UNIQUE (project_id, name),
    FOREIGN KEY (secret_reference_id, project_id, secret_purpose, secret_version)
      REFERENCES secret_versions(reference_id, project_id, purpose, version),
    CHECK (
      (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
      OR (status IN ('approved', 'disabled', 'revoked') AND approved_by IS NOT NULL
          AND approved_at IS NOT NULL AND approved_by <> created_by)
    )
);

CREATE TABLE browser_profile_versions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version text NOT NULL CHECK (btrim(version) <> ''),
    browser_release text NOT NULL CHECK (btrim(browser_release) <> ''),
    device_class text NOT NULL CHECK (device_class IN ('desktop', 'mobile')),
    viewport jsonb NOT NULL CHECK (jsonb_typeof(viewport) = 'object'),
    locale text NOT NULL CHECK (locale = 'en-AU'),
    timezone text NOT NULL CHECK (timezone LIKE 'Australia/%'),
    geolocation jsonb CHECK (geolocation IS NULL OR jsonb_typeof(geolocation) = 'object'),
    location_permission boolean NOT NULL,
    safe_search text NOT NULL CHECK (safe_search IN ('on', 'off', 'moderate')),
    account_cohort text NOT NULL CHECK (account_cohort IN (
        'clean_anonymous', 'managed_test_account'
    )),
    storage_secret_reference_id uuid,
    storage_secret_purpose text,
    storage_secret_version integer,
    profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('draft', 'approved', 'retired')),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    approved_by uuid REFERENCES identities(id),
    approved_at timestamptz,
    UNIQUE (id, project_id), UNIQUE (project_id, version), UNIQUE (project_id, profile_hash),
    FOREIGN KEY (
      storage_secret_reference_id, project_id, storage_secret_purpose, storage_secret_version
    ) REFERENCES secret_versions(reference_id, project_id, purpose, version),
    CHECK ((account_cohort = 'clean_anonymous') = (storage_secret_reference_id IS NULL)),
    CHECK (
      (status = 'draft' AND approved_by IS NULL AND approved_at IS NULL)
      OR (status IN ('approved', 'retired') AND approved_by IS NOT NULL
          AND approved_at IS NOT NULL AND approved_by <> created_by)
    )
);

CREATE TABLE browser_capture_sessions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sampling_attempt_id uuid NOT NULL,
    surface_release_id uuid NOT NULL,
    egress_endpoint_id uuid NOT NULL,
    profile_version_id uuid NOT NULL,
    sticky_lease_id text NOT NULL CHECK (btrim(sticky_lease_id) <> ''),
    sticky_lease_hash text NOT NULL CHECK (sticky_lease_hash ~ '^[0-9a-f]{64}$'),
    lease_started_at timestamptz NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    session_hash text NOT NULL CHECK (session_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('running', 'completed', 'blocked', 'orphaned')),
    started_at timestamptz NOT NULL,
    closed_at timestamptz,
    UNIQUE (id, project_id), UNIQUE (project_id, sampling_attempt_id),
    FOREIGN KEY (sampling_attempt_id, project_id)
      REFERENCES workflow_c_sampling_attempts(id, project_id),
    FOREIGN KEY (surface_release_id, project_id)
      REFERENCES browser_surface_releases(id, project_id),
    FOREIGN KEY (egress_endpoint_id, project_id)
      REFERENCES browser_egress_endpoints(id, project_id),
    FOREIGN KEY (profile_version_id, project_id)
      REFERENCES browser_profile_versions(id, project_id),
    CHECK (lease_expires_at > lease_started_at),
    CHECK ((status = 'running') = (closed_at IS NULL))
);

CREATE TABLE browser_egress_verifications (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    capture_session_id uuid NOT NULL,
    sampling_attempt_id uuid NOT NULL,
    pre_observations jsonb NOT NULL CHECK (jsonb_typeof(pre_observations) = 'array'),
    post_observations jsonb NOT NULL CHECK (jsonb_typeof(post_observations) = 'array'),
    observed_ip_hash text NOT NULL CHECK (observed_ip_hash ~ '^[0-9a-f]{64}$'),
    observed_asn text NOT NULL CHECK (btrim(observed_asn) <> ''),
    observed_country text NOT NULL,
    observed_region text,
    network_type text NOT NULL CHECK (network_type IN (
        'residential', 'mobile', 'datacenter', 'unknown'
    )),
    connection_log_reference text,
    connection_log_hash text CHECK (
        connection_log_hash IS NULL OR connection_log_hash ~ '^[0-9a-f]{64}$'
    ),
    verification_hash text NOT NULL CHECK (verification_hash ~ '^[0-9a-f]{64}$'),
    outcome text NOT NULL CHECK (outcome IN (
        'au_consumer_representative', 'au_geo_verified', 'geo_mismatch',
        'geo_unverified', 'egress_changed'
    )),
    eligible boolean NOT NULL,
    verified_at timestamptz NOT NULL,
    UNIQUE (id, project_id), UNIQUE (project_id, sampling_attempt_id),
    FOREIGN KEY (capture_session_id, project_id)
      REFERENCES browser_capture_sessions(id, project_id),
    FOREIGN KEY (sampling_attempt_id, project_id)
      REFERENCES workflow_c_sampling_attempts(id, project_id),
    CHECK (eligible = (outcome = 'au_consumer_representative')),
    CHECK ((connection_log_reference IS NULL) = (connection_log_hash IS NULL))
);

CREATE TABLE browser_page_artifact_bundles (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    capture_session_id uuid NOT NULL,
    sampling_attempt_id uuid NOT NULL,
    egress_verification_id uuid NOT NULL,
    manifest_uri text NOT NULL CHECK (manifest_uri LIKE 'minio://%' OR manifest_uri LIKE 's3://%'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    screenshot_hash text NOT NULL CHECK (screenshot_hash ~ '^[0-9a-f]{64}$'),
    dom_hash text NOT NULL CHECK (dom_hash ~ '^[0-9a-f]{64}$'),
    har_hash text NOT NULL CHECK (har_hash ~ '^[0-9a-f]{64}$'),
    final_url text NOT NULL CHECK (final_url ~ '^https://'),
    final_url_hash text NOT NULL CHECK (final_url_hash ~ '^[0-9a-f]{64}$'),
    page_location_signal jsonb NOT NULL CHECK (jsonb_typeof(page_location_signal) = 'object'),
    encryption_key_reference text NOT NULL CHECK (btrim(encryption_key_reference) <> ''),
    retention_until timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (id, project_id), UNIQUE (project_id, sampling_attempt_id),
    FOREIGN KEY (capture_session_id, project_id)
      REFERENCES browser_capture_sessions(id, project_id),
    FOREIGN KEY (sampling_attempt_id, project_id)
      REFERENCES workflow_c_sampling_attempts(id, project_id),
    FOREIGN KEY (egress_verification_id, project_id)
      REFERENCES browser_egress_verifications(id, project_id)
);

CREATE TABLE browser_parsed_observations (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sampling_attempt_id uuid NOT NULL,
    surface_release_id uuid NOT NULL,
    artifact_bundle_id uuid NOT NULL,
    egress_verification_id uuid NOT NULL,
    result_class text NOT NULL CHECK (result_class IN (
        'captured', 'surface_not_present', 'consent_required', 'login_required',
        'access_blocked', 'geo_mismatch', 'geo_unverified', 'egress_changed',
        'parser_failed', 'timeout'
    )),
    answer_text text,
    citations jsonb NOT NULL CHECK (jsonb_typeof(citations) = 'array'),
    evidence_locators jsonb NOT NULL CHECK (jsonb_typeof(evidence_locators) = 'object'),
    parser_release text NOT NULL CHECK (btrim(parser_release) <> ''),
    observation_hash text NOT NULL CHECK (observation_hash ~ '^[0-9a-f]{64}$'),
    eligible boolean NOT NULL,
    observed_at timestamptz NOT NULL,
    UNIQUE (id, project_id), UNIQUE (project_id, sampling_attempt_id),
    FOREIGN KEY (sampling_attempt_id, project_id)
      REFERENCES workflow_c_sampling_attempts(id, project_id),
    FOREIGN KEY (surface_release_id, project_id)
      REFERENCES browser_surface_releases(id, project_id),
    FOREIGN KEY (artifact_bundle_id, project_id)
      REFERENCES browser_page_artifact_bundles(id, project_id),
    FOREIGN KEY (egress_verification_id, project_id)
      REFERENCES browser_egress_verifications(id, project_id),
    CHECK (
      (result_class = 'captured' AND answer_text IS NOT NULL AND eligible)
      OR (result_class = 'surface_not_present' AND answer_text IS NULL AND eligible)
      OR (result_class NOT IN ('captured', 'surface_not_present')
          AND answer_text IS NULL AND NOT eligible)
    )
);

CREATE FUNCTION geo_browser_evidence_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
  RAISE EXCEPTION 'Browser Capture evidence is immutable' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER browser_egress_verifications_immutable BEFORE UPDATE OR DELETE
ON browser_egress_verifications FOR EACH ROW EXECUTE FUNCTION geo_browser_evidence_immutable();
CREATE TRIGGER browser_page_artifacts_immutable BEFORE UPDATE OR DELETE
ON browser_page_artifact_bundles FOR EACH ROW EXECUTE FUNCTION geo_browser_evidence_immutable();
CREATE TRIGGER browser_parsed_observations_immutable BEFORE UPDATE OR DELETE
ON browser_parsed_observations FOR EACH ROW EXECUTE FUNCTION geo_browser_evidence_immutable();

DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'browser_surface_releases','browser_egress_endpoints','browser_profile_versions',
    'browser_capture_sessions','browser_egress_verifications',
    'browser_page_artifact_bundles','browser_parsed_observations'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY project_scope ON %I USING (project_id = ANY(geo_current_project_ids())) WITH CHECK (project_id = ANY(geo_current_project_ids()))',
      table_name
    );
    EXECUTE format('REVOKE ALL ON %I FROM PUBLIC, geo_app, geo_worker, geo_readonly', table_name);
    EXECUTE format('GRANT SELECT ON %I TO geo_app', table_name);
    EXECUTE format('GRANT SELECT ON %I TO geo_worker, geo_readonly', table_name);
  END LOOP;
END $$;

GRANT INSERT ON browser_surface_releases, browser_egress_endpoints,
  browser_profile_versions TO geo_app;
GRANT INSERT ON browser_capture_sessions, browser_egress_verifications,
  browser_page_artifact_bundles, browser_parsed_observations TO geo_worker;
GRANT UPDATE (status, closed_at) ON browser_capture_sessions TO geo_worker;
GRANT UPDATE (status, approved_by, approved_at) ON browser_surface_releases,
  browser_egress_endpoints, browser_profile_versions TO geo_app;
GRANT UPDATE (disabled_at) ON browser_egress_endpoints TO geo_app;
