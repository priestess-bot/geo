ALTER TABLE synthetic_lab_command_receipts
DROP CONSTRAINT synthetic_lab_command_receipts_operation_check;
ALTER TABLE synthetic_lab_command_receipts
ADD CONSTRAINT synthetic_lab_command_receipts_operation_check
CHECK (operation IN (
    'create_authorization', 'reassess_authorization', 'decide_authorization',
    'expire_authorization',
    'revoke_authorization', 'admit_collection', 'claim_collection',
    'create_style_source', 'create_style_profile',
    'create_review_suite', 'create_review_case',
    'import_samples', 'freeze_profile', 'submit_profile', 'freeze_suite',
    'enqueue_generation', 'enqueue_revision', 'enqueue_corpus',
    'enqueue_experiment', 'claim_job', 'enqueue_execution', 'cancel_job',
    'finalize_result', 'finalize_experiment'
));

-- Serialize Style Profile parent admission with Dify binding activation. The
-- Python repository takes the same lock; this trigger covers every SQL writer.
CREATE FUNCTION geo_lock_style_profile_parent_admission() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.kind = 'style.profile.build' THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'dify-binding:' || NEW.project_id::text || chr(58) ||
            'synthetic_lab.style_profile', 0
        ));
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_lock_style_profile_parent_admission() FROM PUBLIC;
CREATE TRIGGER style_profile_parent_admission_lock
BEFORE INSERT ON durable_jobs
FOR EACH ROW EXECUTE FUNCTION geo_lock_style_profile_parent_admission();

CREATE FUNCTION geo_synthetic_style_profile_result_hash(p_payload jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    model_calls jsonb;
    workflow_calls jsonb;
    hash_value jsonb;
BEGIN
    SELECT coalesce(
        jsonb_agg(to_jsonb(item.value #>> '{$uuid}') ORDER BY item.ordinality),
        '[]'::jsonb
    ) INTO model_calls
    FROM jsonb_array_elements(
        coalesce(p_payload #> '{fields,model_call_ids,$tuple}', '[]'::jsonb)
    ) WITH ORDINALITY AS item(value, ordinality);
    SELECT coalesce(
        jsonb_agg(to_jsonb(item.value #>> '{$uuid}') ORDER BY item.ordinality),
        '[]'::jsonb
    ) INTO workflow_calls
    FROM jsonb_array_elements(
        coalesce(p_payload #> '{fields,workflow_attempt_ids,$tuple}', '[]'::jsonb)
    ) WITH ORDINALITY AS item(value, ordinality);
    hash_value := jsonb_build_object(
        'project_id', p_payload #>> '{fields,project_id,$uuid}',
        'profile_version_id', p_payload #>> '{fields,profile_version_id,$uuid}',
        'profile_hash', p_payload #>> '{fields,profile_hash}',
        'artifact_hash', p_payload #>> '{fields,artifact_hash}',
        'model_call_ids', model_calls,
        'profile_summary', p_payload #>> '{fields,profile_summary}'
    );
    IF jsonb_array_length(workflow_calls) > 0 THEN
        hash_value := hash_value || jsonb_build_object(
            'workflow_attempt_ids', workflow_calls
        );
    END IF;
    RETURN encode(digest(
        convert_to(geo_jsonb_canonical_text(hash_value), 'UTF8'), 'sha256'
    ), 'hex');
END;
$$;
REVOKE ALL ON FUNCTION geo_synthetic_style_profile_result_hash(jsonb) FROM PUBLIC;

CREATE FUNCTION geo_synthetic_style_profile_summary_json(p_summary text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
DECLARE
    parsed jsonb;
BEGIN
    parsed := p_summary::jsonb;
    IF jsonb_typeof(parsed) <> 'object' THEN
        RETURN NULL;
    END IF;
    RETURN parsed;
EXCEPTION WHEN invalid_text_representation THEN
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION geo_synthetic_style_profile_summary_json(text) FROM PUBLIC;

-- Prove that the parent result is the output of its one frozen Style Profile
-- child. This is intentionally shared by result insertion, migration backfill,
-- and review binding so no legacy or alternate SQL writer can skip lineage.
CREATE FUNCTION geo_synthetic_style_profile_result_matches_child(
    p_project_id uuid, p_parent_job_id uuid, p_payload jsonb
) RETURNS boolean
LANGUAGE sql STABLE STRICT PARALLEL RESTRICTED
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
    WITH expected AS (
        SELECT
            coalesce(
                p_payload #> '{fields,model_call_ids,$tuple}', '[]'::jsonb
            ) AS model_calls,
            coalesce(
                p_payload #> '{fields,workflow_attempt_ids,$tuple}', '[]'::jsonb
            ) AS workflow_calls,
            p_payload #>> '{fields,artifact_hash}' AS artifact_hash,
            p_payload #>> '{fields,profile_summary}' AS profile_summary,
            geo_synthetic_style_profile_summary_json(
                p_payload #>> '{fields,profile_summary}'
            ) AS summary_json
    ), build_children AS (
        SELECT child.*, durable.status AS durable_status,
               durable.result_ref AS durable_result_ref
        FROM synthetic_lab_model_call_children child
        JOIN durable_jobs durable
          ON durable.id = child.child_job_id
         AND durable.project_id = child.project_id
        WHERE child.project_id = p_project_id
          AND child.parent_job_id = p_parent_job_id
          AND child.parent_job_kind = 'style.profile.build'
          AND child.step_key =
              'style-profile' || chr(58) || 'build' || chr(58) || 'v1'
          AND child.prompt_program_kind = 'style_profile'
          AND child.prompt_purpose = 'synthetic_lab.style_profile'
    )
    SELECT
        (SELECT count(*) FROM build_children) = 1
        AND expected.summary_json IS NOT NULL
        -- Synthetic writes profile_summary as its canonical, ASCII-safe JSON.
        -- Hashing those exact bytes therefore proves the reviewed text is the
        -- same output represented by artifact_hash, including non-ASCII data.
        AND expected.artifact_hash = encode(digest(
            convert_to(expected.profile_summary, 'UTF8'), 'sha256'
        ), 'hex')
        AND (
            EXISTS (
                SELECT 1
                FROM build_children child
                JOIN model_gateway_call_attempts attempt
                  ON attempt.project_id = child.project_id
                 AND attempt.job_id = child.child_job_id
                JOIN model_gateway_terminal_events terminal
                  ON terminal.project_id = attempt.project_id
                 AND terminal.job_id = attempt.job_id
                 AND terminal.attempt_id = attempt.id
                WHERE child.execution_backend = 'model_gateway'
                  AND child.durable_status = 'succeeded'
                  AND child.durable_result_ref =
                      'model-gateway://attempt/' || attempt.id::text
                  AND terminal.status = 'succeeded'
                  AND terminal.output_hash = expected.artifact_hash
                  AND CASE WHEN jsonb_typeof(expected.model_calls) = 'array'
                           THEN jsonb_array_length(expected.model_calls)
                           ELSE -1 END = 1
                  AND expected.model_calls #>> '{0,$uuid}' =
                      terminal.gateway_call_log_id::text
                  AND CASE WHEN jsonb_typeof(expected.workflow_calls) = 'array'
                           THEN jsonb_array_length(expected.workflow_calls)
                           ELSE -1 END = 0
            )
            OR EXISTS (
                SELECT 1
                FROM build_children child
                JOIN dify_workflow_execution_attempts attempt
                  ON attempt.project_id = child.project_id
                 AND attempt.job_id = child.child_job_id
                 AND attempt.release_id = child.workflow_release_id
                JOIN dify_workflow_execution_results result
                  ON result.project_id = attempt.project_id
                 AND result.job_id = attempt.job_id
                 AND result.attempt_id = attempt.id
                JOIN dify_workflow_releases release
                  ON release.project_id = child.project_id
                 AND release.id = child.workflow_release_id
                 AND release.release_hash = child.workflow_release_hash
                JOIN dify_workflow_release_snapshot_pins pin
                  ON pin.project_id = attempt.project_id
                 AND pin.release_id = attempt.release_id
                 AND pin.published_snapshot_id = attempt.published_snapshot_id
                WHERE child.execution_backend = 'dify'
                  AND child.durable_status = 'succeeded'
                  AND child.durable_result_ref =
                      'dify-workflow://attempt/' || attempt.id::text
                  AND attempt.execution_kind = 'business'
                  AND attempt.status = 'succeeded'
                  AND release.purpose = 'synthetic_lab.style_profile'
                  AND release.prompt_release_id = child.prompt_release_id
                  AND release.prompt_release_hash = child.prompt_release_hash
                  AND result.configured_model = child.configured_model
                  AND result.output = expected.summary_json
                  AND result.response_hash = attempt.output_hash
                  AND result.response_hash = encode(digest(
                      convert_to(geo_dify_canonical_text(result.output), 'UTF8'),
                      'sha256'
                  ), 'hex')
                  AND CASE WHEN jsonb_typeof(expected.model_calls) = 'array'
                           THEN jsonb_array_length(expected.model_calls)
                           ELSE -1 END = 0
                  AND CASE WHEN jsonb_typeof(expected.workflow_calls) = 'array'
                           THEN jsonb_array_length(expected.workflow_calls)
                           ELSE -1 END = 1
                  AND expected.workflow_calls #>> '{0,$uuid}' = attempt.id::text
            )
        )
    FROM expected;
$$;
REVOKE ALL ON FUNCTION geo_synthetic_style_profile_result_matches_child(
    uuid, uuid, jsonb
) FROM PUBLIC;

CREATE FUNCTION geo_assert_synthetic_style_profile_result_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    model_calls jsonb;
    workflow_calls jsonb;
    profile_summary text;
BEGIN
    IF NEW.result_type <>
       'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildOutput' THEN
        RETURN NEW;
    END IF;
    model_calls := coalesce(
        NEW.result_payload #> '{fields,model_call_ids,$tuple}', '[]'::jsonb
    );
    workflow_calls := coalesce(
        NEW.result_payload #> '{fields,workflow_attempt_ids,$tuple}', '[]'::jsonb
    );
    profile_summary := NEW.result_payload #>> '{fields,profile_summary}';
    IF NEW.result_payload ->> '$type' <> NEW.result_type
       OR NEW.result_payload_hash <> encode(digest(
            convert_to(geo_jsonb_canonical_text(NEW.result_payload), 'UTF8'), 'sha256'
       ), 'hex')
       OR NEW.result_payload #>> '{fields,project_id,$uuid}' <> NEW.project_id::text
       OR NEW.result_payload #>> '{fields,profile_version_id,$uuid}'
            <> NEW.profile_version_id::text
       OR NEW.result_payload #>> '{fields,profile_hash}' <> NEW.profile_hash
       OR coalesce(NEW.result_payload #>> '{fields,artifact_hash}', '')
            !~ '^[0-9a-f]{64}$'
       OR profile_summary IS NULL OR btrim(profile_summary) = ''
       OR char_length(profile_summary) > 16000
       OR jsonb_typeof(model_calls) <> 'array'
       OR jsonb_typeof(workflow_calls) <> 'array'
       OR jsonb_array_length(model_calls) + jsonb_array_length(workflow_calls) <> 1
       OR NEW.result_hash <>
            geo_synthetic_style_profile_result_hash(NEW.result_payload)
       OR NOT geo_synthetic_style_profile_result_matches_child(
            NEW.project_id, NEW.job_id, NEW.result_payload
       ) THEN
        RAISE EXCEPTION 'Style Profile result changed its frozen build identity or bounded output'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_assert_synthetic_style_profile_result_identity() FROM PUBLIC;
CREATE TRIGGER synthetic_style_profile_result_identity_guard
BEFORE INSERT ON synthetic_lab_execution_results
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_style_profile_result_identity();

-- A Style Profile build consumes a draft Profile by design. Every other
-- terminal result still requires a frozen Profile exactly as before.
CREATE OR REPLACE FUNCTION geo_assert_synthetic_lab_terminal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE metadata synthetic_lab_job_metadata%ROWTYPE;
DECLARE current_authorization synthetic_lab_authorization_versions%ROWTYPE;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR UPDATE;
    SELECT * INTO STRICT metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    IF metadata.domain_job_kind <> NEW.job_kind
       OR durable.status NOT IN ('running', 'finalizing')
       OR durable.cancel_requested_at IS NOT NULL
       OR durable.lease_token IS DISTINCT FROM NEW.lease_token
       OR durable.fencing_generation <> NEW.fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= NEW.occurred_at THEN
        RAISE EXCEPTION 'Synthetic Lab terminal writer lost Job lease or fencing ownership'
            USING ERRCODE = '40001';
    END IF;
    IF (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
        NEW.profile_version_id, NEW.profile_hash,
        NEW.prompt_release_id, NEW.prompt_release_hash)
       IS DISTINCT FROM
       (metadata.fact_snapshot_id, metadata.fact_snapshot_hash,
        metadata.profile_version_id, metadata.profile_hash,
        metadata.prompt_release_id, metadata.prompt_release_hash)
       OR coalesce(metadata.facts_current_approved, true) IS NOT TRUE
       OR (coalesce(metadata.profile_frozen, true) IS NOT TRUE
           AND metadata.domain_job_kind <> 'style_profile_build')
       OR coalesce(metadata.prompt_frozen, true) IS NOT TRUE THEN
        RAISE EXCEPTION 'Synthetic Lab terminal runtime lineage is stale'
            USING ERRCODE = '40001';
    END IF;
    IF metadata.authorization_id IS NOT NULL THEN
        SELECT * INTO current_authorization
        FROM synthetic_lab_authorization_versions
        WHERE project_id = metadata.project_id
          AND channel = metadata.authorization_channel
          AND adapter_release = metadata.authorization_adapter_release
        ORDER BY version_number DESC LIMIT 1;
        IF NOT FOUND OR current_authorization.id <> metadata.authorization_id
           OR current_authorization.record_hash <> metadata.authorization_hash
           OR current_authorization.state <> 'approved'
           OR current_authorization.expires_at <= NEW.occurred_at
           OR NOT metadata.authorization_purpose = ANY(current_authorization.allowed_purposes) THEN
            RAISE EXCEPTION 'Synthetic Lab terminal authorization is stale or inactive'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TABLE synthetic_lab_style_profile_build_bindings (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    profile_version_id uuid NOT NULL,
    profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
    verification_status text NOT NULL DEFAULT 'verified' CHECK (
        verification_status IN ('verified', 'legacy_unverified')
    ),
    binding_source text NOT NULL DEFAULT 'runtime_review' CHECK (
        binding_source IN ('migration_backfill', 'migration_legacy', 'runtime_review')
    ),
    rebuild_required boolean NOT NULL DEFAULT false,
    execution_job_id uuid,
    execution_result_id uuid,
    result_hash text CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
    result_payload_hash text CHECK (
        result_payload_hash IS NULL OR result_payload_hash ~ '^[0-9a-f]{64}$'
    ),
    artifact_hash text CHECK (
        artifact_hash IS NULL OR artifact_hash ~ '^[0-9a-f]{64}$'
    ),
    bound_by uuid NOT NULL REFERENCES identities(id),
    bound_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, profile_version_id),
    UNIQUE (project_id, execution_result_id),
    FOREIGN KEY (execution_job_id, project_id)
        REFERENCES synthetic_lab_execution_tasks(job_id, project_id),
    FOREIGN KEY (execution_result_id, project_id)
        REFERENCES synthetic_lab_execution_results(id, project_id),
    CONSTRAINT synthetic_lab_style_profile_build_binding_shape CHECK (
        (verification_status = 'verified' AND NOT rebuild_required
            AND binding_source IN ('migration_backfill', 'runtime_review')
            AND execution_job_id IS NOT NULL AND execution_result_id IS NOT NULL
            AND result_hash IS NOT NULL AND result_payload_hash IS NOT NULL
            AND artifact_hash IS NOT NULL)
        OR (verification_status = 'legacy_unverified' AND rebuild_required
            AND binding_source = 'migration_legacy'
            AND execution_job_id IS NULL AND execution_result_id IS NULL
            AND result_hash IS NULL AND result_payload_hash IS NULL
            AND artifact_hash IS NULL)
    )
);

-- Preserve already-reviewed Profiles by selecting the same latest successful
-- exact build result that the pre-binding reader exposed. A historical Profile
-- without that proof remains visible but is explicitly rebuild-required; no
-- result identity or model lineage is invented during migration.
WITH current_profiles AS (
    SELECT DISTINCT ON (aggregate.project_id, aggregate.resource_id)
           aggregate.project_id,
           aggregate.resource_id AS profile_version_id,
           aggregate.payload #>> '{fields,profile_hash}' AS profile_hash,
           aggregate.payload #>> '{fields,status,value}' AS status
    FROM synthetic_lab_aggregate_versions aggregate
    WHERE aggregate.kind = 'style_profile'
    ORDER BY aggregate.project_id, aggregate.resource_id, aggregate.version DESC
), submitters AS (
    SELECT DISTINCT ON (aggregate.project_id, aggregate.resource_id)
           aggregate.project_id,
           aggregate.resource_id AS profile_version_id,
           aggregate.submitted_by
    FROM synthetic_lab_aggregate_versions aggregate
    WHERE aggregate.kind = 'style_profile'
      AND aggregate.payload #>> '{fields,status,value}' <> 'draft'
    ORDER BY aggregate.project_id, aggregate.resource_id, aggregate.version
), candidates AS (
    SELECT profile.project_id, profile.profile_version_id, profile.profile_hash,
           result.job_id AS execution_job_id, result.id AS execution_result_id,
           result.result_hash, result.result_payload_hash,
           result.result_payload #>> '{fields,artifact_hash}' AS artifact_hash,
           submitter.submitted_by AS bound_by,
           row_number() OVER (
               PARTITION BY profile.project_id, profile.profile_version_id
               ORDER BY result.created_at DESC, result.id DESC
           ) AS candidate_number
    FROM current_profiles profile
    JOIN submitters submitter
      ON submitter.project_id = profile.project_id
     AND submitter.profile_version_id = profile.profile_version_id
    JOIN synthetic_lab_job_metadata metadata
      ON metadata.project_id = profile.project_id
     AND metadata.domain_job_kind = 'style_profile_build'
     AND metadata.profile_version_id = profile.profile_version_id
     AND metadata.profile_hash = profile.profile_hash
    JOIN synthetic_lab_execution_results result
      ON result.project_id = metadata.project_id
     AND result.job_id = metadata.job_id
    JOIN durable_jobs job
      ON job.project_id = result.project_id AND job.id = result.job_id
    WHERE profile.status <> 'draft'
      AND job.status = 'succeeded'
      AND result.result_type =
          'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildOutput'
      AND result.result_payload_hash = encode(digest(
          convert_to(geo_jsonb_canonical_text(result.result_payload), 'UTF8'), 'sha256'
      ), 'hex')
      AND result.result_hash =
          geo_synthetic_style_profile_result_hash(result.result_payload)
      AND result.result_payload #>> '{fields,project_id,$uuid}' = profile.project_id::text
      AND result.result_payload #>> '{fields,profile_version_id,$uuid}'
          = profile.profile_version_id::text
      AND result.result_payload #>> '{fields,profile_hash}' = profile.profile_hash
      AND btrim(coalesce(result.result_payload #>> '{fields,profile_summary}', '')) <> ''
      AND char_length(result.result_payload #>> '{fields,profile_summary}') <= 16000
      AND geo_synthetic_style_profile_result_matches_child(
          result.project_id, result.job_id, result.result_payload
      )
)
INSERT INTO synthetic_lab_style_profile_build_bindings(
    project_id, profile_version_id, profile_hash, execution_job_id,
    execution_result_id, result_hash, result_payload_hash, artifact_hash, bound_by,
    verification_status, binding_source, rebuild_required
)
SELECT project_id, profile_version_id, profile_hash, execution_job_id,
       execution_result_id, result_hash, result_payload_hash, artifact_hash, bound_by,
       'verified', 'migration_backfill', false
FROM candidates WHERE candidate_number = 1;

WITH current_profiles AS (
    SELECT DISTINCT ON (aggregate.project_id, aggregate.resource_id)
           aggregate.project_id,
           aggregate.resource_id AS profile_version_id,
           aggregate.payload #>> '{fields,profile_hash}' AS profile_hash,
           aggregate.payload #>> '{fields,status,value}' AS status
    FROM synthetic_lab_aggregate_versions aggregate
    WHERE aggregate.kind = 'style_profile'
    ORDER BY aggregate.project_id, aggregate.resource_id, aggregate.version DESC
), submitters AS (
    SELECT DISTINCT ON (aggregate.project_id, aggregate.resource_id)
           aggregate.project_id,
           aggregate.resource_id AS profile_version_id,
           aggregate.submitted_by
    FROM synthetic_lab_aggregate_versions aggregate
    WHERE aggregate.kind = 'style_profile'
      AND aggregate.payload #>> '{fields,status,value}' <> 'draft'
    ORDER BY aggregate.project_id, aggregate.resource_id, aggregate.version
)
INSERT INTO synthetic_lab_style_profile_build_bindings(
    project_id, profile_version_id, profile_hash, bound_by,
    verification_status, binding_source, rebuild_required
)
SELECT profile.project_id, profile.profile_version_id, profile.profile_hash,
       submitter.submitted_by, 'legacy_unverified', 'migration_legacy', true
FROM current_profiles profile
JOIN submitters submitter
  ON submitter.project_id = profile.project_id
 AND submitter.profile_version_id = profile.profile_version_id
LEFT JOIN synthetic_lab_style_profile_build_bindings binding
  ON binding.project_id = profile.project_id
 AND binding.profile_version_id = profile.profile_version_id
WHERE profile.status <> 'draft' AND binding.profile_version_id IS NULL;

CREATE FUNCTION geo_assert_style_profile_build_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE profile_record record;
DECLARE result_record record;
BEGIN
    IF NEW.verification_status <> 'verified'
       OR NEW.binding_source <> 'runtime_review'
       OR NEW.rebuild_required THEN
        RAISE EXCEPTION 'new Style Profile review requires one runtime-verified build result'
            USING ERRCODE = '23514';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        NEW.project_id::text || chr(58) || 'style_profile' || chr(58) ||
        NEW.profile_version_id::text, 0
    ));
    SELECT aggregate.payload INTO STRICT profile_record
    FROM synthetic_lab_aggregate_versions aggregate
    WHERE aggregate.project_id = NEW.project_id
      AND aggregate.kind = 'style_profile'
      AND aggregate.resource_id = NEW.profile_version_id
    ORDER BY aggregate.version DESC LIMIT 1;
    SELECT result.job_id, result.result_type, result.result_payload,
           result.result_payload_hash, result.result_hash,
           metadata.domain_job_kind,
           metadata.profile_version_id AS metadata_profile_version_id,
           metadata.profile_hash AS metadata_profile_hash,
           job.status AS job_status,
           job.result_ref AS job_result_ref
    INTO STRICT result_record
    FROM synthetic_lab_execution_results result
    JOIN synthetic_lab_job_metadata metadata
      ON metadata.project_id = result.project_id AND metadata.job_id = result.job_id
    JOIN durable_jobs job
      ON job.project_id = result.project_id AND job.id = result.job_id
    WHERE result.project_id = NEW.project_id AND result.id = NEW.execution_result_id;
    IF profile_record.payload ->> '$type' <>
           'geo_core.synthetic_lab.domain.StyleProfileVersion'
       OR profile_record.payload #>> '{fields,id,$uuid}' <> NEW.profile_version_id::text
       OR profile_record.payload #>> '{fields,project_id,$uuid}' <> NEW.project_id::text
       OR profile_record.payload #>> '{fields,profile_hash}' <> NEW.profile_hash
       OR profile_record.payload #>> '{fields,status,value}' <> 'draft'
       OR result_record.job_id <> NEW.execution_job_id
       OR result_record.domain_job_kind <> 'style_profile_build'
       OR result_record.metadata_profile_version_id <> NEW.profile_version_id
       OR result_record.metadata_profile_hash <> NEW.profile_hash
       OR result_record.job_status <> 'succeeded'
       OR result_record.job_result_ref <>
            'synthetic://result/' || result_record.result_hash
       OR result_record.result_type <>
            'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildOutput'
       OR result_record.result_hash <> NEW.result_hash
       OR result_record.result_payload_hash <> NEW.result_payload_hash
       OR result_record.result_payload_hash <> encode(digest(
            convert_to(geo_jsonb_canonical_text(result_record.result_payload), 'UTF8'), 'sha256'
       ), 'hex')
       OR result_record.result_hash <>
            geo_synthetic_style_profile_result_hash(result_record.result_payload)
       OR result_record.result_payload #>> '{fields,project_id,$uuid}'
            <> NEW.project_id::text
       OR result_record.result_payload #>> '{fields,profile_version_id,$uuid}'
            <> NEW.profile_version_id::text
       OR result_record.result_payload #>> '{fields,profile_hash}' <> NEW.profile_hash
       OR result_record.result_payload #>> '{fields,artifact_hash}' <> NEW.artifact_hash
       OR btrim(coalesce(
            result_record.result_payload #>> '{fields,profile_summary}', ''
       )) = ''
       OR char_length(result_record.result_payload #>> '{fields,profile_summary}') > 16000
       OR NOT geo_synthetic_style_profile_result_matches_child(
            NEW.project_id, NEW.execution_job_id, result_record.result_payload
       ) THEN
        RAISE EXCEPTION 'Style Profile review binding does not match its exact canonical build result'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION geo_assert_style_profile_build_binding() FROM PUBLIC;
CREATE TRIGGER style_profile_build_binding_guard
BEFORE INSERT ON synthetic_lab_style_profile_build_bindings
FOR EACH ROW EXECUTE FUNCTION geo_assert_style_profile_build_binding();

CREATE FUNCTION geo_reject_style_profile_build_binding_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Style Profile build result binding is immutable'
        USING ERRCODE = '55000';
END;
$$;
REVOKE ALL ON FUNCTION geo_reject_style_profile_build_binding_change() FROM PUBLIC;
CREATE TRIGGER style_profile_build_binding_immutable
BEFORE UPDATE OR DELETE ON synthetic_lab_style_profile_build_bindings
FOR EACH ROW EXECUTE FUNCTION geo_reject_style_profile_build_binding_change();

ALTER TABLE synthetic_lab_style_profile_build_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE synthetic_lab_style_profile_build_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON synthetic_lab_style_profile_build_bindings
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
REVOKE ALL ON synthetic_lab_style_profile_build_bindings
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON synthetic_lab_style_profile_build_bindings TO geo_app;
GRANT SELECT ON synthetic_lab_style_profile_build_bindings TO geo_worker;

DROP VIEW synthetic_lab_model_call_child_status;
CREATE VIEW synthetic_lab_model_call_child_status
WITH (security_barrier = true, security_invoker = true) AS
SELECT child.project_id, child.child_job_id, child.parent_job_id,
       child.parent_job_kind, child.parent_task_input_hash, child.step_key,
       child.step_key_hash, child.model_job_version, child.prompt_binding_id,
       child.prompt_binding_version, child.prompt_frozen_state_id,
       child.prompt_state_version, child.prompt_release_id,
       child.prompt_release_version, child.prompt_release_hash,
       child.prompt_program_kind, child.prompt_purpose, child.admitted_by,
       child.prompt_bundle_hash, child.structured_input_hash,
       child.portable_output_schema_hash, child.application_output_schema_hash,
       child.runtime_manifest_id, child.runtime_manifest_hash,
       child.runtime_option_id, child.runtime_option_hash,
       child.configured_model AS frozen_configured_model,
       child.execution_backend, child.backend_lineage_source,
       child.workflow_release_id,
       child.workflow_release_hash, child.task_artifact_uri,
       child.task_artifact_hash, child.child_input_hash,
       durable.status AS durable_status,
       CASE WHEN durable.status = 'succeeded' THEN 'succeeded'
            WHEN durable.status = 'cancelled' THEN 'cancelled'
            WHEN durable.error_code IN ('model_unknown_outcome', 'dify_unknown_outcome')
                THEN 'unknown_outcome'
            WHEN durable.status IN ('failed', 'dead_lettered') THEN 'failed'
            WHEN durable.status IN ('running', 'finalizing') THEN 'running'
            ELSE 'queued' END AS status,
       durable.attempt_count AS durable_attempt_count,
       durable.fencing_generation AS durable_fencing_generation,
       durable.cancel_requested_at,
       coalesce(
           durable.error_code,
           CASE WHEN child.execution_backend = 'dify'
                THEN dify.error_code ELSE native.error_code END
       ) AS failure_code,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.attempt_id END AS model_attempt_id,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.attempt_number END AS model_attempt_number,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.terminal_status END AS model_terminal_status,
       CASE WHEN child.execution_backend = 'model_gateway'
            THEN native.gateway_call_log_id END AS gateway_call_log_id,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_id END AS workflow_attempt_id,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_number END AS workflow_attempt_number,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.attempt_status END AS workflow_attempt_status,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.output_hash ELSE native.output_hash END AS output_hash,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.response_hash ELSE native.response_hash END AS response_hash,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.configured_model ELSE native.configured_model
            END AS model_configured_model,
       CASE WHEN child.execution_backend = 'dify'
            THEN dify.provider_reported_model ELSE native.provider_reported_model
            END AS model_reported_model,
       CASE WHEN child.execution_backend = 'dify' THEN dify.output END AS dify_output,
       CASE WHEN child.execution_backend = 'dify' THEN dify.release_id END
            AS dify_release_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.release_hash END
            AS dify_release_hash,
       CASE WHEN child.execution_backend = 'dify' THEN dify.prompt_release_id END
            AS dify_prompt_release_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.prompt_release_hash END
            AS dify_prompt_release_hash,
       CASE WHEN child.execution_backend = 'dify' THEN dify.purpose END
            AS dify_purpose,
       CASE WHEN child.execution_backend = 'dify' THEN dify.published_snapshot_id END
            AS published_snapshot_id,
       CASE WHEN child.execution_backend = 'dify' THEN dify.snapshot_hash END
            AS published_snapshot_hash,
       child.created_at
FROM synthetic_lab_model_call_children child
JOIN durable_jobs durable
  ON durable.id = child.child_job_id AND durable.project_id = child.project_id
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id, attempt.attempt_number,
           terminal.status AS terminal_status, terminal.error_code,
           terminal.gateway_call_log_id, terminal.output_hash,
           terminal.response_hash, terminal.configured_model,
           terminal.provider_reported_model
    FROM model_gateway_call_attempts attempt
    LEFT JOIN model_gateway_terminal_events terminal
      ON terminal.attempt_id = attempt.id AND terminal.project_id = attempt.project_id
     AND terminal.job_id = attempt.job_id
    WHERE child.execution_backend = 'model_gateway'
      AND attempt.project_id = child.project_id
      AND attempt.job_id = child.child_job_id
      AND (durable.status <> 'succeeded' OR durable.result_ref =
           'model-gateway://attempt/' || attempt.id::text)
    ORDER BY attempt.attempt_number DESC LIMIT 1
) native ON true
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id, attempt.attempt_number,
           attempt.status AS attempt_status, attempt.error_code,
           result.output, result.response_hash AS output_hash,
           result.response_hash, result.configured_model,
           result.provider_reported_model, release.id AS release_id,
           release.release_hash, release.prompt_release_id,
           release.prompt_release_hash, release.purpose,
           attempt.published_snapshot_id, snapshot.snapshot_hash
    FROM dify_workflow_execution_attempts attempt
    JOIN dify_workflow_releases release
      ON release.id = attempt.release_id AND release.project_id = attempt.project_id
     AND release.release_hash = child.workflow_release_hash
    LEFT JOIN dify_workflow_execution_results result
      ON result.attempt_id = attempt.id AND result.project_id = attempt.project_id
     AND result.job_id = attempt.job_id
    LEFT JOIN dify_workflow_published_snapshots snapshot
      ON snapshot.id = attempt.published_snapshot_id
     AND snapshot.project_id = attempt.project_id
     AND snapshot.release_id = attempt.release_id
    WHERE child.execution_backend = 'dify'
      AND attempt.project_id = child.project_id
      AND attempt.job_id = child.child_job_id
      AND attempt.release_id = child.workflow_release_id
      AND (durable.status <> 'succeeded' OR durable.result_ref =
           'dify-workflow://attempt/' || attempt.id::text)
    ORDER BY attempt.attempt_number DESC LIMIT 1
) dify ON true;
REVOKE ALL ON synthetic_lab_model_call_child_status
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON synthetic_lab_model_call_child_status TO geo_app, geo_worker;
COMMENT ON VIEW synthetic_lab_model_call_child_status IS
    'Admin/worker status projection over the frozen backend and exact terminal attempt named by Durable Job result_ref; lineage source remains explicit.';
