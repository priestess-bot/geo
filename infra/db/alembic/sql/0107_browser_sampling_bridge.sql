CREATE FUNCTION geo_register_browser_sampling_runtime_option(
    p_project_id uuid,
    p_surface_release_id uuid,
    p_egress_endpoint_id uuid,
    p_profile_version_id uuid,
    p_frozen_at timestamptz
) RETURNS SETOF workflow_c_sampling_runtime_options
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE surface browser_surface_releases%ROWTYPE;
DECLARE endpoint browser_egress_endpoints%ROWTYPE;
DECLARE profile browser_profile_versions%ROWTYPE;
DECLARE option_key_value text;
DECLARE adapter_release_value text;
DECLARE location_hash text;
DECLARE option_hash_value text;
BEGIN
    IF p_project_id IS NULL OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_frozen_at IS NULL THEN
        RAISE EXCEPTION 'Browser Sampling option is outside the current Project scope'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO surface FROM browser_surface_releases
     WHERE project_id = p_project_id AND id = p_surface_release_id
       AND status = 'approved' AND authorization_status = 'approved'
       AND authorization_valid_until > p_frozen_at FOR SHARE;
    SELECT * INTO endpoint FROM browser_egress_endpoints
     WHERE project_id = p_project_id AND id = p_egress_endpoint_id
       AND status = 'approved' AND expected_country = 'AU'
       AND network_type IN ('residential', 'mobile') FOR SHARE;
    SELECT * INTO profile FROM browser_profile_versions
     WHERE project_id = p_project_id AND id = p_profile_version_id
       AND status = 'approved' FOR SHARE;
    IF surface.id IS NULL OR endpoint.id IS NULL OR profile.id IS NULL THEN
        RAISE EXCEPTION 'Approved current Surface, consumer Egress, and Profile are required'
            USING ERRCODE = '23514';
    END IF;
    IF profile.browser_release NOT LIKE surface.browser_release || '%' THEN
        RAISE EXCEPTION 'Browser Profile release differs from Surface Release'
            USING ERRCODE = '23514';
    END IF;

    option_key_value := 'browser:' || surface.id::text || ':' || profile.id::text
        || ':' || endpoint.id::text;
    adapter_release_value := 'browser:' || surface.release_hash || ':profile:'
        || profile.profile_hash || ':egress:' || endpoint.id::text || ':'
        || endpoint.egress_policy_version || ':' || endpoint.egress_cohort_key;
    location_hash := encode(digest(convert_to(
        endpoint.expected_country || ':' || coalesce(endpoint.expected_region, '') || ':'
        || endpoint.network_type || ':' || endpoint.egress_policy_version || ':'
        || endpoint.egress_cohort_key, 'UTF8'), 'sha256'), 'hex');
    option_hash_value := encode(digest(convert_to(
        option_key_value || ':' || adapter_release_value || ':' || location_hash || ':'
        || surface.authorization_reference, 'UTF8'), 'sha256'), 'hex');

    INSERT INTO workflow_c_sampling_runtime_options(
        project_id, option_key, option_hash, display_name, platform, capture_method,
        adapter_release, location_control, location_evidence_hash,
        authorization_reference, allowed_purposes, status, frozen_at
    ) VALUES (
        p_project_id, option_key_value, option_hash_value,
        surface.surface || ' / ' || profile.version || ' / ' || endpoint.name,
        surface.platform, 'automated_ui', adapter_release_value, 'country', location_hash,
        surface.authorization_reference, '["geo_measurement"]'::jsonb, 'approved', p_frozen_at
    ) ON CONFLICT (project_id, option_key) DO NOTHING;

    IF NOT EXISTS (
        SELECT 1 FROM workflow_c_sampling_runtime_options
         WHERE project_id = p_project_id AND option_key = option_key_value
           AND option_hash = option_hash_value AND status = 'approved'
    ) THEN
        RAISE EXCEPTION 'Browser Sampling option identity changed in place'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT * FROM workflow_c_sampling_runtime_options
     WHERE project_id = p_project_id AND option_key = option_key_value;
END;
$$;

REVOKE ALL ON FUNCTION geo_register_browser_sampling_runtime_option(
    uuid, uuid, uuid, uuid, timestamptz
) FROM PUBLIC, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_register_browser_sampling_runtime_option(
    uuid, uuid, uuid, uuid, timestamptz
) TO geo_app;
