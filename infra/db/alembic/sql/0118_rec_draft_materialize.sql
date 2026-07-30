-- A successful generation result is already an immutable, fenced Worker
-- output. Materialize its draft projection in the same transaction so that
-- operators can review it through the normal Recommendation lifecycle. The
-- worker receives EXECUTE only: it still cannot write lifecycle rows, approve
-- a Recommendation, or create a downstream draft directly.

ALTER TABLE recommendation_evidence_bindings
    DROP CONSTRAINT recommendation_evidence_bindings_evidence_kind_check,
    ADD CONSTRAINT recommendation_evidence_bindings_evidence_kind_check CHECK (
        evidence_kind IN (
            'observation', 'metric_comparison', 'fact', 'rule', 'prompt_release',
            'model_call', 'content', 'question', 'surface', 'attribution'
        )
    );

CREATE FUNCTION geo_materialize_recommendation_generation_draft(
    p_project_id uuid,
    p_job_id uuid,
    p_lease_token uuid,
    p_fencing_generation bigint
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    parent_job durable_jobs%ROWTYPE;
    generation_spec recommendation_generation_specs%ROWTYPE;
    generation_result recommendation_generation_results%ROWTYPE;
    workflow_value jsonb;
    recommendation_value jsonb;
    evidence_value jsonb;
    references_value jsonb;
    materialization_value jsonb;
    bindings_value jsonb;
    binding_value jsonb;
    reference_value jsonb;
    input_version_value jsonb;
    existing_workflow recommendation_workflow_versions%ROWTYPE;
    existing_binding recommendation_evidence_bindings%ROWTYPE;
    expected_input_kind text;
    ordinal_value integer;
    created_at_value timestamptz;
    updated_at_value timestamptz;
    valid_until_value timestamptz;
BEGIN
    IF p_project_id IS NULL
       OR NOT p_project_id = ANY(geo_current_project_ids())
       OR p_job_id IS NULL
       OR p_lease_token IS NULL
       OR p_fencing_generation IS NULL
       OR p_fencing_generation < 1 THEN
        RAISE EXCEPTION 'Recommendation draft materialization scope is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT item.* INTO parent_job
      FROM durable_jobs AS item
     WHERE item.project_id = p_project_id AND item.id = p_job_id
     FOR UPDATE;
    SELECT item.* INTO generation_spec
      FROM recommendation_generation_specs AS item
     WHERE item.project_id = p_project_id AND item.job_id = p_job_id
     FOR SHARE;
    SELECT item.* INTO generation_result
      FROM recommendation_generation_results AS item
     WHERE item.project_id = p_project_id AND item.job_id = p_job_id
     FOR SHARE;

    IF parent_job.id IS NULL
       OR generation_spec.job_id IS NULL
       OR generation_result.job_id IS NULL
       OR parent_job.kind <> 'recommendation.generate'
       OR parent_job.input_hash <> generation_spec.input_hash
       OR parent_job.status NOT IN ('running', 'finalizing')
       OR parent_job.lease_token IS DISTINCT FROM p_lease_token
       OR parent_job.fencing_generation <> p_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= clock_timestamp()
       OR parent_job.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Recommendation generation lease or frozen input was fenced'
            USING ERRCODE = '40001';
    END IF;

    IF generation_result.result_hash !~ '^[0-9a-f]{64}$'
       OR NOT geo_workflow_c_json_has_exact_keys(
            generation_result.result_payload,
            ARRAY[
                'contract_version', 'workflow', 'materialization',
                'model_call_ids', 'workflow_attempt_ids', 'insufficient_reasons'
            ]
       )
       OR generation_result.result_payload->>'contract_version'
            <> 'recommendation-generation-result-v3'
       OR jsonb_typeof(generation_result.result_payload->'model_call_ids') <> 'array'
       OR jsonb_typeof(generation_result.result_payload->'workflow_attempt_ids') <> 'array'
       OR jsonb_typeof(generation_result.result_payload->'insufficient_reasons') <> 'array' THEN
        RAISE EXCEPTION 'Recommendation generation result is not materializable v3'
            USING ERRCODE = '22023';
    END IF;

    workflow_value := generation_result.result_payload->'workflow';
    materialization_value := generation_result.result_payload->'materialization';
    IF NOT geo_workflow_c_json_has_exact_keys(
            workflow_value, ARRAY['recommendation', 'drafts']
       )
       OR jsonb_typeof(workflow_value->'drafts') <> 'array'
       OR jsonb_array_length(workflow_value->'drafts') <> 0
       OR NOT geo_workflow_c_json_has_exact_keys(
            materialization_value,
            ARRAY[
                'workflow_payload_hash', 'evidence_graph_hash',
                'input_fingerprint', 'evidence_bindings'
            ]
       )
       OR materialization_value->>'workflow_payload_hash' !~ '^[0-9a-f]{64}$'
       OR materialization_value->>'evidence_graph_hash' !~ '^[0-9a-f]{64}$'
       OR materialization_value->>'input_fingerprint' !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(materialization_value->'evidence_bindings') <> 'array' THEN
        RAISE EXCEPTION 'Recommendation generation materialization manifest is invalid'
            USING ERRCODE = '22023';
    END IF;

    recommendation_value := workflow_value->'recommendation';
    IF NOT geo_workflow_c_json_has_exact_keys(
            recommendation_value,
            ARRAY[
                'id', 'project_id', 'recommendation_type', 'evidence',
                'proposed_draft_kind', 'valid_until', 'created_by', 'created_at',
                'updated_at', 'status', 'version', 'approval', 'transitions'
            ]
       )
       OR NOT geo_workflow_c_json_is_uuid(recommendation_value->'id')
       OR NOT geo_workflow_c_json_is_uuid(recommendation_value->'project_id')
       OR NOT geo_workflow_c_json_is_uuid(recommendation_value->'created_by')
       OR (recommendation_value->>'id')::uuid <> generation_result.recommendation_id
       OR (recommendation_value->>'project_id')::uuid <> p_project_id
       OR (recommendation_value->>'created_by')::uuid <> generation_spec.created_by
       OR recommendation_value->>'status' <> 'draft'
       OR recommendation_value->'version' <> '1'::jsonb
       OR recommendation_value->'approval' <> 'null'::jsonb
       OR jsonb_typeof(recommendation_value->'transitions') <> 'array'
       OR jsonb_array_length(recommendation_value->'transitions') <> 0
       OR recommendation_value->>'recommendation_type' NOT IN (
            'hard_blocker', 'gap', 'experiment', 'optional', 'no_change',
            'insufficient_evidence'
       )
       OR jsonb_typeof(recommendation_value->'proposed_draft_kind')
            NOT IN ('string', 'null')
       OR (
            jsonb_typeof(recommendation_value->'proposed_draft_kind') = 'string'
            AND recommendation_value->>'proposed_draft_kind' NOT IN (
                'experiment_plan', 'question_set', 'content_brief', 'sampling_plan'
            )
       )
       OR NOT geo_workflow_c_json_is_rfc3339(recommendation_value->'valid_until')
       OR NOT geo_workflow_c_json_is_rfc3339(recommendation_value->'created_at')
       OR NOT geo_workflow_c_json_is_rfc3339(recommendation_value->'updated_at') THEN
        RAISE EXCEPTION 'Generated Recommendation may only materialize as draft version one'
            USING ERRCODE = '22023';
    END IF;

    created_at_value := (recommendation_value->>'created_at')::timestamptz;
    updated_at_value := (recommendation_value->>'updated_at')::timestamptz;
    valid_until_value := (recommendation_value->>'valid_until')::timestamptz;
    IF created_at_value <> updated_at_value
       OR valid_until_value <> generation_spec.valid_until
       OR valid_until_value <= created_at_value THEN
        RAISE EXCEPTION 'Generated Recommendation timestamps differ from the frozen spec'
            USING ERRCODE = '22023';
    END IF;

    evidence_value := recommendation_value->'evidence';
    IF NOT geo_workflow_c_json_has_exact_keys(
            evidence_value,
            ARRAY['contract_version', 'scope', 'decision', 'references']
       )
       OR evidence_value->>'contract_version' NOT IN (
            'geo-recommendation-evidence-v1', 'geo-recommendation-evidence-v2'
       )
       OR jsonb_typeof(evidence_value->'scope') <> 'object'
       OR NOT geo_workflow_c_json_is_uuid(evidence_value->'scope'->'project_id')
       OR (evidence_value->'scope'->>'project_id')::uuid <> p_project_id
       OR jsonb_typeof(evidence_value->'decision') <> 'object'
       OR jsonb_typeof(evidence_value->'references') <> 'array' THEN
        RAISE EXCEPTION 'Generated Recommendation evidence graph is invalid'
            USING ERRCODE = '22023';
    END IF;

    references_value := evidence_value->'references';
    bindings_value := materialization_value->'evidence_bindings';
    IF jsonb_array_length(references_value) <> jsonb_array_length(bindings_value) THEN
        RAISE EXCEPTION 'Recommendation materialization does not cover every evidence reference'
            USING ERRCODE = '22023';
    END IF;

    -- Lock the deterministic Recommendation identity before checking or
    -- creating version one. Replay is accepted only when every immutable row
    -- is byte-for-byte equivalent to the stored generation result.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            p_project_id::text || ':' || generation_result.recommendation_id::text,
            0
        )
    );

    INSERT INTO recommendation_workflow_versions(
        project_id, recommendation_id, version, status,
        recommendation_type, proposed_draft_kind, evidence_graph_hash,
        input_fingerprint, valid_until, created_by, created_at, updated_at,
        workflow_payload, workflow_payload_hash
    ) VALUES (
        p_project_id,
        generation_result.recommendation_id,
        1,
        'draft',
        recommendation_value->>'recommendation_type',
        recommendation_value->>'proposed_draft_kind',
        materialization_value->>'evidence_graph_hash',
        materialization_value->>'input_fingerprint',
        valid_until_value,
        generation_spec.created_by,
        created_at_value,
        updated_at_value,
        workflow_value,
        materialization_value->>'workflow_payload_hash'
    ) ON CONFLICT (project_id, recommendation_id, version) DO NOTHING;
    SELECT item.* INTO existing_workflow
      FROM recommendation_workflow_versions AS item
     WHERE item.project_id = p_project_id
       AND item.recommendation_id = generation_result.recommendation_id
       AND item.version = 1
     FOR SHARE;
    IF existing_workflow.recommendation_id IS NULL
       OR existing_workflow.status <> 'draft'
       OR existing_workflow.recommendation_type
            <> recommendation_value->>'recommendation_type'
       OR existing_workflow.proposed_draft_kind
            IS DISTINCT FROM recommendation_value->>'proposed_draft_kind'
       OR existing_workflow.evidence_graph_hash
            <> materialization_value->>'evidence_graph_hash'
       OR existing_workflow.input_fingerprint
            <> materialization_value->>'input_fingerprint'
       OR existing_workflow.valid_until <> valid_until_value
       OR existing_workflow.created_by <> generation_spec.created_by
       OR existing_workflow.created_at <> created_at_value
       OR existing_workflow.updated_at <> updated_at_value
       OR existing_workflow.workflow_payload IS DISTINCT FROM workflow_value
       OR existing_workflow.workflow_payload_hash
            <> materialization_value->>'workflow_payload_hash' THEN
        RAISE EXCEPTION 'Recommendation generated draft replay changed immutable data'
            USING ERRCODE = '23505';
    END IF;

    FOR binding_value IN
        SELECT item.value
          FROM jsonb_array_elements(bindings_value) AS item(value)
         ORDER BY (item.value->>'ordinal')::integer
    LOOP
        IF NOT geo_workflow_c_json_has_exact_keys(
                binding_value,
                ARRAY[
                    'ordinal', 'evidence_kind', 'resource_id', 'resource_version',
                    'resource_hash', 'locator', 'input_versions'
                ]
           )
           OR jsonb_typeof(binding_value->'ordinal') <> 'number'
           OR binding_value->>'ordinal' !~ '^(0|[1-9][0-9]*)$'
           OR jsonb_typeof(binding_value->'evidence_kind') <> 'string'
           OR binding_value->>'evidence_kind' NOT IN (
                'observation', 'metric_comparison', 'fact', 'rule',
                'prompt_release', 'model_call', 'content', 'question',
                'surface', 'attribution'
           )
           OR jsonb_typeof(binding_value->'resource_id') <> 'string'
           OR btrim(binding_value->>'resource_id') = ''
           OR jsonb_typeof(binding_value->'resource_version') <> 'string'
           OR btrim(binding_value->>'resource_version') = ''
           OR jsonb_typeof(binding_value->'resource_hash') <> 'string'
           OR binding_value->>'resource_hash' !~ '^[0-9a-f]{64}$'
           OR jsonb_typeof(binding_value->'locator') <> 'object'
           OR binding_value->'locator' = '{}'::jsonb
           OR jsonb_typeof(binding_value->'input_versions') <> 'array'
           OR jsonb_array_length(binding_value->'input_versions') < 1
           OR jsonb_array_length(binding_value->'input_versions') > 2 THEN
            RAISE EXCEPTION 'Recommendation evidence materialization binding is invalid'
                USING ERRCODE = '22023';
        END IF;

        ordinal_value := (binding_value->>'ordinal')::integer;
        IF ordinal_value >= jsonb_array_length(references_value) THEN
            RAISE EXCEPTION 'Recommendation evidence materialization ordinal is out of range'
                USING ERRCODE = '22023';
        END IF;
        reference_value := references_value->ordinal_value;
        IF reference_value->>'kind' <> binding_value->>'evidence_kind'
           OR reference_value->>'project_id' <> p_project_id::text
           OR reference_value->>'resource_id' <> binding_value->>'resource_id'
           OR reference_value->>'version' <> binding_value->>'resource_version'
           OR reference_value->>'sha256' <> binding_value->>'resource_hash'
           OR reference_value->'locator' IS DISTINCT FROM binding_value->'locator' THEN
            RAISE EXCEPTION 'Recommendation evidence binding differs from generated evidence'
                USING ERRCODE = '22023';
        END IF;

        expected_input_kind := CASE binding_value->>'evidence_kind'
            WHEN 'observation' THEN 'observation'
            WHEN 'metric_comparison' THEN 'comparison'
            WHEN 'fact' THEN 'fact'
            WHEN 'rule' THEN 'rule_version'
            WHEN 'prompt_release' THEN 'prompt_release'
            WHEN 'model_call' THEN 'model_call'
            WHEN 'content' THEN 'content_version'
            WHEN 'question' THEN 'question_version'
            WHEN 'surface' THEN 'surface_release'
            WHEN 'attribution' THEN 'attribution_availability'
        END;
        IF NOT EXISTS (
            SELECT 1
              FROM jsonb_array_elements(binding_value->'input_versions') AS item(value)
             WHERE item.value->>'kind' = expected_input_kind
               AND item.value->>'resource_id' = binding_value->>'resource_id'
               AND item.value->>'version' = binding_value->>'resource_version'
               AND item.value->>'sha256' = binding_value->>'resource_hash'
        ) THEN
            RAISE EXCEPTION 'Recommendation evidence binding lacks its source input version'
                USING ERRCODE = '22023';
        END IF;
        FOR input_version_value IN
            SELECT item.value
              FROM jsonb_array_elements(binding_value->'input_versions') AS item(value)
        LOOP
            IF NOT geo_workflow_c_json_has_exact_keys(
                    input_version_value,
                    ARRAY['kind', 'resource_id', 'version', 'sha256']
               )
               OR jsonb_typeof(input_version_value->'kind') <> 'string'
               OR input_version_value->>'kind' NOT IN (
                    'observation', 'comparison', 'fact', 'rule_version',
                    'prompt_release', 'model_call', 'method_version',
                    'content_version', 'question_version', 'surface_release',
                    'attribution_availability'
               )
               OR jsonb_typeof(input_version_value->'resource_id') <> 'string'
               OR btrim(input_version_value->>'resource_id') = ''
               OR jsonb_typeof(input_version_value->'version') <> 'string'
               OR btrim(input_version_value->>'version') = ''
               OR jsonb_typeof(input_version_value->'sha256') <> 'string'
               OR input_version_value->>'sha256' !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Recommendation materialized input version is invalid'
                    USING ERRCODE = '22023';
            END IF;
        END LOOP;

        INSERT INTO recommendation_evidence_bindings(
            project_id, recommendation_id, recommendation_version,
            ordinal, evidence_kind, resource_id, resource_version,
            resource_hash, locator, input_versions
        ) VALUES (
            p_project_id,
            generation_result.recommendation_id,
            1,
            ordinal_value,
            binding_value->>'evidence_kind',
            binding_value->>'resource_id',
            binding_value->>'resource_version',
            binding_value->>'resource_hash',
            binding_value->'locator',
            binding_value->'input_versions'
        ) ON CONFLICT (
            project_id, recommendation_id, recommendation_version, ordinal
        ) DO NOTHING;

        SELECT item.* INTO existing_binding
          FROM recommendation_evidence_bindings AS item
         WHERE item.project_id = p_project_id
           AND item.recommendation_id = generation_result.recommendation_id
           AND item.recommendation_version = 1
           AND item.ordinal = ordinal_value
         FOR SHARE;
        IF existing_binding.recommendation_id IS NULL
           OR existing_binding.evidence_kind <> binding_value->>'evidence_kind'
           OR existing_binding.resource_id <> binding_value->>'resource_id'
           OR existing_binding.resource_version <> binding_value->>'resource_version'
           OR existing_binding.resource_hash <> binding_value->>'resource_hash'
           OR existing_binding.locator IS DISTINCT FROM binding_value->'locator'
           OR existing_binding.input_versions
                IS DISTINCT FROM binding_value->'input_versions' THEN
            RAISE EXCEPTION 'Recommendation evidence binding replay changed immutable data'
                USING ERRCODE = '23505';
        END IF;
    END LOOP;

    IF (
        SELECT count(*)
          FROM recommendation_evidence_bindings AS item
         WHERE item.project_id = p_project_id
           AND item.recommendation_id = generation_result.recommendation_id
           AND item.recommendation_version = 1
    ) <> jsonb_array_length(bindings_value) THEN
        RAISE EXCEPTION 'Recommendation generated draft has unexpected evidence bindings'
            USING ERRCODE = '23505';
    END IF;

    RETURN true;
END;
$$;

REVOKE ALL ON FUNCTION geo_materialize_recommendation_generation_draft(
    uuid, uuid, uuid, bigint
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_materialize_recommendation_generation_draft(
    uuid, uuid, uuid, bigint
) TO geo_worker;
