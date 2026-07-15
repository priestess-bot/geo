-- GEO runtime commands. Runtime writes are capability checked and never table grants.

CREATE FUNCTION geo_v2_create_geo_campaign(
    p_project_id uuid, p_product_entity_id uuid, p_name text, p_market_code text
) RETURNS geo_campaigns
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE context_row record; result_row public.geo_campaigns%ROWTYPE;
BEGIN
    SELECT * INTO context_row FROM public.geo_v2_resolve_session_context();
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        p_project_id, context_row.tenant_id, 'geo.campaign.manage'
    ) THEN RAISE EXCEPTION 'geo campaign permission denied' USING ERRCODE = '42501'; END IF;
    INSERT INTO public.geo_campaigns(
        tenant_id, project_id, primary_product_entity_id, name, market_code, created_by, updated_by
    ) VALUES (
        context_row.tenant_id, p_project_id, p_product_entity_id, btrim(p_name), btrim(p_market_code),
        context_row.actor_id, context_row.actor_id
    ) RETURNING * INTO result_row;
    RETURN result_row;
END;
$$;

CREATE FUNCTION geo_v2_create_project_destination(
    p_project_id uuid, p_publisher_id uuid, p_name text, p_url text,
    p_ownership_kind text, p_task_type text, p_policy_snapshot jsonb
) RETURNS project_destinations
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE context_row record; result_row public.project_destinations%ROWTYPE; policy_hash text;
BEGIN
    SELECT * INTO context_row FROM public.geo_v2_resolve_session_context();
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        p_project_id, context_row.tenant_id, 'geo.destination.manage'
    ) THEN RAISE EXCEPTION 'geo destination permission denied' USING ERRCODE = '42501'; END IF;
    IF jsonb_typeof(p_policy_snapshot) <> 'object' THEN
        RAISE EXCEPTION 'destination policy snapshot must be an object' USING ERRCODE = '22023';
    END IF;
    policy_hash := encode(public.digest(p_policy_snapshot::text, 'sha256'), 'hex');
    INSERT INTO public.project_destinations(
        tenant_id, project_id, publisher_id, destination_name, destination_url,
        ownership_kind, operation_mode, task_type, qualification_status,
        policy_snapshot_hash, policy_snapshot, created_by, updated_by
    ) VALUES (
        context_row.tenant_id, p_project_id, p_publisher_id, btrim(p_name), btrim(p_url),
        p_ownership_kind, 'manual_submission', p_task_type, 'candidate',
        policy_hash, p_policy_snapshot, context_row.actor_id, context_row.actor_id
    ) RETURNING * INTO result_row;
    RETURN result_row;
END;
$$;

CREATE FUNCTION geo_v2_qualify_project_destination(p_destination_id uuid, p_project_id uuid)
RETURNS project_destinations
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE context_row record; result_row public.project_destinations%ROWTYPE;
BEGIN
    SELECT * INTO context_row FROM public.geo_v2_resolve_session_context();
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        p_project_id, context_row.tenant_id, 'geo.destination.manage'
    ) THEN RAISE EXCEPTION 'geo destination permission denied' USING ERRCODE = '42501'; END IF;
    UPDATE public.project_destinations SET qualification_status = 'approved',
        qualified_by = context_row.actor_id, qualified_at = statement_timestamp(),
        updated_by = context_row.actor_id, updated_at = statement_timestamp()
    WHERE id = p_destination_id AND project_id = p_project_id
    RETURNING * INTO result_row;
    IF NOT FOUND THEN RAISE EXCEPTION 'geo destination not found' USING ERRCODE = 'NO_DATA_FOUND'; END IF;
    RETURN result_row;
END;
$$;

CREATE FUNCTION geo_v2_create_placement_opportunity(
    p_project_id uuid, p_campaign_id uuid, p_destination_id uuid, p_query_id uuid,
    p_title text, p_rationale text, p_priority text DEFAULT 'medium'
) RETURNS placement_opportunities
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE context_row record; result_row public.placement_opportunities%ROWTYPE;
BEGIN
    SELECT * INTO context_row FROM public.geo_v2_resolve_session_context();
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        p_project_id, context_row.tenant_id, 'geo.opportunity.manage'
    ) THEN RAISE EXCEPTION 'geo opportunity permission denied' USING ERRCODE = '42501'; END IF;
    INSERT INTO public.placement_opportunities(
        tenant_id, project_id, campaign_id, destination_id, monitoring_query_id,
        title, rationale, priority, created_by, updated_by
    ) VALUES (
        context_row.tenant_id, p_project_id, p_campaign_id, p_destination_id, p_query_id,
        btrim(p_title), btrim(p_rationale), p_priority, context_row.actor_id, context_row.actor_id
    ) RETURNING * INTO result_row;
    RETURN result_row;
END;
$$;

CREATE FUNCTION geo_v2_read_geo_campaigns(p_project_id uuid)
RETURNS TABLE(id uuid, primary_product_entity_id uuid, name text, market_code text, status text, created_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT campaign.id, campaign.primary_product_entity_id, campaign.name,
           campaign.market_code, campaign.status, campaign.created_at
    FROM public.geo_campaigns AS campaign
    WHERE campaign.project_id = p_project_id
      AND EXISTS (
        SELECT 1 FROM public.geo_v2_resolve_session_context() AS context_row
        WHERE public.geo_v2_session_has_project_permission(
            p_project_id, context_row.tenant_id, 'geo.measurement.read'
        )
      )
    ORDER BY campaign.created_at DESC, campaign.id;
$$;

ALTER FUNCTION geo_v2_create_geo_campaign(uuid, uuid, text, text) OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_create_project_destination(uuid, uuid, text, text, text, text, jsonb) OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_qualify_project_destination(uuid, uuid) OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_create_placement_opportunity(uuid, uuid, uuid, uuid, text, text, text) OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_read_geo_campaigns(uuid) OWNER TO geo_v2_authz_owner;
REVOKE ALL ON FUNCTION geo_v2_create_geo_campaign(uuid, uuid, text, text),
    geo_v2_create_project_destination(uuid, uuid, text, text, text, text, jsonb),
    geo_v2_qualify_project_destination(uuid, uuid),
    geo_v2_create_placement_opportunity(uuid, uuid, uuid, uuid, text, text, text),
    geo_v2_read_geo_campaigns(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION geo_v2_create_geo_campaign(uuid, uuid, text, text),
    geo_v2_create_project_destination(uuid, uuid, text, text, text, text, jsonb),
    geo_v2_qualify_project_destination(uuid, uuid),
    geo_v2_create_placement_opportunity(uuid, uuid, uuid, uuid, text, text, text),
    geo_v2_read_geo_campaigns(uuid) TO geo_v2_runtime;
