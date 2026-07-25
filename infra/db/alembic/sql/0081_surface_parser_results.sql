CREATE TABLE workflow_c_surface_parse_results (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    manual_import_id uuid NOT NULL,
    parser_release_id uuid NOT NULL,
    parser_release_hash text NOT NULL CHECK (
        parser_release_hash ~ '^[0-9a-f]{64}$'
    ),
    surface text NOT NULL CHECK (surface IN (
        'google_ai_overviews', 'google_ai_mode', 'bing_copilot'
    )),
    outcome text NOT NULL CHECK (outcome IN (
        'captured', 'surface_not_present', 'consent_required',
        'login_required', 'access_blocked', 'geo_mismatch',
        'egress_changed', 'parser_failed', 'timeout'
    )),
    summary jsonb NOT NULL CHECK (jsonb_typeof(summary) = 'object'),
    summary_hash text NOT NULL CHECK (summary_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, manual_import_id),
    FOREIGN KEY (manual_import_id, project_id)
        REFERENCES workflow_c_sampling_manual_imports(id, project_id)
        ON DELETE CASCADE
);

CREATE INDEX workflow_c_surface_parse_release_outcome_idx
ON workflow_c_surface_parse_results(project_id, parser_release_id, outcome);

CREATE FUNCTION geo_assert_workflow_c_surface_parse_immutable()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    RAISE EXCEPTION 'Workflow C surface parse results are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER workflow_c_surface_parse_immutable_guard
BEFORE UPDATE OR DELETE ON workflow_c_surface_parse_results
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_surface_parse_immutable();

ALTER TABLE workflow_c_surface_parse_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_surface_parse_results FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_surface_parse_results
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON workflow_c_surface_parse_results
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON workflow_c_surface_parse_results TO geo_app, geo_worker;

CREATE FUNCTION geo_submit_workflow_c_surface_parsed_evidence(
    p_project_id uuid,
    p_import_id uuid,
    p_attempt_id uuid,
    p_idempotency_key_hash text,
    p_input_hash text,
    p_run_id uuid,
    p_task_id uuid,
    p_expected_task_version integer,
    p_artifact_manifest_id uuid,
    p_artifact_manifest_hash text,
    p_artifact_content_hash text,
    p_governance_policy_hash text,
    p_capture_session_id uuid,
    p_payload jsonb,
    p_submitted_by text,
    p_submitted_at timestamptz,
    p_surface_parse jsonb
) RETURNS TABLE (import_id uuid, aggregate_version integer, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE submitted record;
DECLARE stored workflow_c_surface_parse_results%ROWTYPE;
DECLARE block_reason text;
DECLARE answer_hash text;
DECLARE answer_count integer;
DECLARE citation_count integer;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR NOT geo_workflow_c_json_has_exact_keys(p_surface_parse, ARRAY[
           'schema_version', 'parser_release_id', 'parser_release_hash',
           'platform', 'surface', 'capture_kind', 'outcome', 'block_reason',
           'content_eligible', 'automated_capture', 'live_capture_eligible',
           'answer_text_hash', 'answer_character_count', 'citation_count',
           'citation_set_hash', 'locator_set_hash', 'parser_result_hash',
           'summary_hash'
       ])
       OR p_surface_parse->>'schema_version' <> 'surface-parse-summary-v1'
       OR NOT geo_workflow_c_json_is_uuid(p_surface_parse->'parser_release_id')
       OR NOT geo_workflow_c_json_is_sha256(p_surface_parse->'parser_release_hash')
       OR btrim(coalesce(p_surface_parse->>'platform', '')) = ''
       OR length(p_surface_parse->>'platform') > 200
       OR p_surface_parse->>'surface' NOT IN (
           'google_ai_overviews', 'google_ai_mode', 'bing_copilot'
       )
       OR p_surface_parse->>'capture_kind' <> 'manual_ui'
       OR p_surface_parse->>'outcome' NOT IN (
           'captured', 'surface_not_present', 'consent_required',
           'login_required', 'access_blocked', 'geo_mismatch',
           'egress_changed', 'parser_failed', 'timeout'
       )
       OR jsonb_typeof(p_surface_parse->'content_eligible') <> 'boolean'
       OR p_surface_parse->'automated_capture' <> 'false'::jsonb
       OR p_surface_parse->'live_capture_eligible' <> 'false'::jsonb
       OR jsonb_typeof(p_surface_parse->'answer_text_hash') NOT IN ('string', 'null')
       OR (jsonb_typeof(p_surface_parse->'answer_text_hash') = 'string'
           AND NOT geo_workflow_c_json_is_sha256(p_surface_parse->'answer_text_hash'))
       OR jsonb_typeof(p_surface_parse->'answer_character_count') <> 'number'
       OR p_surface_parse->>'answer_character_count' !~ '^[0-9]+$'
       OR jsonb_typeof(p_surface_parse->'citation_count') <> 'number'
       OR p_surface_parse->>'citation_count' !~ '^[0-9]+$'
       OR NOT geo_workflow_c_json_is_sha256(p_surface_parse->'citation_set_hash')
       OR NOT geo_workflow_c_json_is_sha256(p_surface_parse->'locator_set_hash')
       OR NOT geo_workflow_c_json_is_sha256(p_surface_parse->'parser_result_hash')
       OR NOT geo_workflow_c_json_is_sha256(p_surface_parse->'summary_hash')
       OR encode(digest(convert_to(
           geo_jsonb_canonical_text(p_surface_parse - 'summary_hash'), 'UTF8'
       ), 'sha256'), 'hex') <> p_surface_parse->>'summary_hash' THEN
        RAISE EXCEPTION 'Manual surface parse summary is invalid'
            USING ERRCODE = '22023';
    END IF;

    block_reason := p_surface_parse->>'block_reason';
    answer_hash := p_surface_parse->>'answer_text_hash';
    answer_count := (p_surface_parse->>'answer_character_count')::integer;
    citation_count := (p_surface_parse->>'citation_count')::integer;
    IF (block_reason IS NOT NULL AND block_reason NOT IN (
            'consent', 'login', 'captcha', 'rate_limit', 'ban',
            'geo_mismatch', 'egress_changed', 'timeout', 'selector_drift',
            'page_incomplete', 'invalid_artifact', 'wrong_surface'
        ))
       OR (p_surface_parse->>'outcome' = 'captured' AND (
            block_reason IS NOT NULL OR answer_hash IS NULL OR answer_count < 1
            OR p_surface_parse->'content_eligible' <> 'true'::jsonb
       ))
       OR (p_surface_parse->>'outcome' = 'surface_not_present' AND (
            block_reason IS NOT NULL OR answer_hash IS NOT NULL OR answer_count <> 0
            OR citation_count <> 0
            OR p_surface_parse->'content_eligible' <> 'true'::jsonb
       ))
       OR (p_surface_parse->>'outcome' NOT IN ('captured', 'surface_not_present') AND (
            block_reason IS NULL OR answer_hash IS NOT NULL OR answer_count <> 0
            OR citation_count <> 0
            OR p_surface_parse->'content_eligible' <> 'false'::jsonb
       )) THEN
        RAISE EXCEPTION 'Manual surface parse eligibility is inconsistent'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO submitted
      FROM geo_submit_workflow_c_manual_sampling_evidence(
          p_project_id, p_import_id, p_attempt_id, p_idempotency_key_hash,
          p_input_hash, p_run_id, p_task_id, p_expected_task_version,
          p_artifact_manifest_id, p_artifact_manifest_hash,
          p_artifact_content_hash, p_governance_policy_hash,
          p_capture_session_id, p_payload, p_submitted_by, p_submitted_at
      );
    INSERT INTO workflow_c_surface_parse_results(
        project_id, manual_import_id, parser_release_id, parser_release_hash,
        surface, outcome, summary, summary_hash, created_at
    ) VALUES (
        p_project_id, p_import_id,
        (p_surface_parse->>'parser_release_id')::uuid,
        p_surface_parse->>'parser_release_hash', p_surface_parse->>'surface',
        p_surface_parse->>'outcome', p_surface_parse,
        p_surface_parse->>'summary_hash', p_submitted_at
    ) ON CONFLICT (project_id, manual_import_id) DO NOTHING;
    SELECT * INTO stored
      FROM workflow_c_surface_parse_results
     WHERE project_id = p_project_id AND manual_import_id = p_import_id;
    IF stored.summary_hash <> p_surface_parse->>'summary_hash'
       OR stored.summary <> p_surface_parse THEN
        RAISE EXCEPTION 'Manual surface parse idempotency conflict'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT submitted.import_id, submitted.aggregate_version, submitted.replayed;
END;
$$;

REVOKE ALL ON FUNCTION geo_submit_workflow_c_surface_parsed_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz, jsonb
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_submit_workflow_c_surface_parsed_evidence(
    uuid, uuid, uuid, text, text, uuid, uuid, integer, uuid, text, text, text,
    uuid, jsonb, text, timestamptz, jsonb
) TO geo_app;
