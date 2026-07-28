-- Recommendation type is selected deterministically before model execution.
-- Extend the existing producer-owned resolver with the exact statistical
-- conclusion and current alert state needed by that admission decision.

ALTER FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    RENAME TO geo_resolve_recommendation_evidence_pre_0100;
REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence_pre_0100(uuid, text, text)
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
    comparison_conclusion text;
    selected_rule_kind text;
    selected_rule_severity text;
    selected_trigger_status text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RETURN NULL;
    END IF;

    resolved := geo_resolve_recommendation_evidence_pre_0100(
        p_project_id, p_kind, p_resource_id
    );
    IF resolved IS NULL THEN
        RETURN NULL;
    END IF;

    IF p_kind = 'metric_comparison' THEN
        SELECT result.conclusion
          INTO comparison_conclusion
          FROM workflow_c_comparison_results AS result
          JOIN workflow_c_comparison_families AS family
            ON family.project_id = result.project_id
           AND family.family_hash = result.family_hash
         WHERE result.project_id = p_project_id
           AND result.family_hash || ':' || result.comparison_id = p_resource_id;
        IF comparison_conclusion IS NULL THEN
            RETURN NULL;
        END IF;
        RETURN resolved || jsonb_build_object(
            'conclusion', comparison_conclusion,
            'sufficient_evidence',
                comparison_conclusion <> 'insufficient_evidence'
        );
    END IF;

    IF p_kind = 'rule' THEN
        SELECT rule.payload->>'kind', rule.payload->>'severity'
          INTO selected_rule_kind, selected_rule_severity
          FROM workflow_c_alert_rule_versions AS rule
         WHERE rule.project_id = p_project_id
           AND rule.id::text = p_resource_id
           AND rule.status = 'approved';
        IF selected_rule_kind IS NULL OR selected_rule_kind NOT IN (
               'threshold', 'baseline_delta', 'negative_question',
               'completion_freshness', 'model_drift', 'source_drift',
               'connector_failure'
           ) OR selected_rule_severity IS NULL
           OR selected_rule_severity NOT IN ('info', 'warning', 'critical') THEN
            RETURN NULL;
        END IF;
        IF EXISTS (
            SELECT 1
              FROM workflow_c_alerts AS alert
             WHERE alert.project_id = p_project_id
               AND alert.rule_version_id::text = p_resource_id
               AND alert.severity <> selected_rule_severity
        ) THEN
            RETURN NULL;
        END IF;
        SELECT coalesce((
            SELECT alert.status
              FROM workflow_c_alerts AS alert
             WHERE alert.project_id = p_project_id
               AND alert.rule_version_id::text = p_resource_id
             ORDER BY CASE alert.status
                          WHEN 'open' THEN 1
                          WHEN 'acknowledged' THEN 2
                          WHEN 'suppressed' THEN 3
                          WHEN 'resolved' THEN 4
                          ELSE 5
                      END,
                      alert.updated_at DESC,
                      alert.id DESC
             LIMIT 1
        ), 'not_triggered') INTO selected_trigger_status;
        RETURN resolved || jsonb_build_object(
            'rule_kind', selected_rule_kind,
            'severity', selected_rule_severity,
            'trigger_status', selected_trigger_status
        );
    END IF;

    RETURN resolved;
END;
$$;

REVOKE ALL ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_resolve_recommendation_evidence(uuid, text, text)
    TO geo_app, geo_worker;
