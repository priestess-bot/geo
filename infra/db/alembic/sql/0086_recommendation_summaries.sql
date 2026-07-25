-- Recommendation generation receives bounded server-owned summaries rather
-- than client text.  Observation summaries use the text-free surface parser
-- projection, while Comparison and Rule summaries use immutable producer
-- projections.  Raw captured answers never cross this resolver.

ALTER FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    RENAME TO geo_resolve_recommendation_evidence_pre_0086;
REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence_pre_0086(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;

CREATE FUNCTION geo_resolve_recommendation_evidence(
    p_project_id uuid,
    p_kind text,
    p_resource_id text
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    resolved jsonb;
    evidence_summary text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RETURN NULL;
    END IF;

    resolved := geo_resolve_recommendation_evidence_pre_0086(
        p_project_id, p_kind, p_resource_id
    );
    IF resolved IS NULL THEN
        RETURN NULL;
    END IF;

    IF p_kind = 'observation' THEN
        SELECT left(format(
            'Observation %s is %s via %s for question %s on source stratum %s; '
                || 'text-free surface parse: %s',
            observation.id::text,
            observation.status,
            task.capture_method,
            task.question_id,
            task.source_stratum_hash,
            coalesce(observation.evidence_json->'surface_parse', '{}'::jsonb)::text
        ), 4000)
        INTO evidence_summary
        FROM workflow_c_sampling_observations AS observation
        JOIN workflow_c_sampling_tasks AS task
          ON task.project_id = observation.project_id
         AND task.id = observation.task_id
         AND task.run_id = observation.run_id
         AND task.source_stratum_hash = observation.source_stratum_hash
        WHERE observation.project_id = p_project_id
          AND observation.id::text = p_resource_id;
    ELSIF p_kind = 'metric_comparison' THEN
        SELECT left(format(
            'Metric comparison %s used %s under protocol %s and concluded %s; '
                || 'frozen statistical result: %s',
            family.family_hash || ':' || result.comparison_id,
            family.bootstrap_method,
            family.protocol_hash,
            result.conclusion,
            result.payload::text
        ), 4000)
        INTO evidence_summary
        FROM workflow_c_comparison_results AS result
        JOIN workflow_c_comparison_families AS family
          ON family.project_id = result.project_id
         AND family.family_hash = result.family_hash
        WHERE family.project_id = p_project_id
          AND family.family_hash || ':' || result.comparison_id = p_resource_id;
    ELSIF p_kind = 'rule' THEN
        SELECT left(format(
            'Alert rule %s version %s is %s; frozen definition: %s',
            rule.rule_key,
            rule.version,
            rule.status,
            rule.payload::text
        ), 4000)
        INTO evidence_summary
        FROM workflow_c_alert_rule_versions AS rule
        WHERE rule.project_id = p_project_id
          AND rule.id::text = p_resource_id;
    END IF;

    IF evidence_summary IS NOT NULL THEN
        resolved := resolved || jsonb_build_object(
            'summary', evidence_summary,
            'summary_hash', encode(
                digest(convert_to(evidence_summary, 'UTF8'), 'sha256'), 'hex'
            )
        );
    END IF;
    RETURN resolved;
END;
$$;

REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    TO geo_app, geo_worker;
