-- Schema v2 B2 Knowledge boundary.
-- This baseline intentionally stops at governed Approved Knowledge. It must not
-- create prompt, brief, evidence-pack, generation, asset, or content objects.

CREATE TABLE knowledge_pipeline_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    run_kind text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    idempotency_key text NOT NULL,
    requested_by text NOT NULL,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_runs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_runs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_runs_idempotency_unique UNIQUE (project_id, idempotency_key),
    CONSTRAINT knowledge_runs_kind_canonical CHECK (
        run_kind IN ('ingest', 'reparse', 'rechunk', 'reembed', 'fact_refresh')
    ),
    CONSTRAINT knowledge_runs_status_canonical CHECK (
        status IN ('draft', 'queued', 'running', 'waiting_review',
                   'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT knowledge_runs_text_nonempty CHECK (
        btrim(idempotency_key) <> '' AND btrim(requested_by) <> ''
    ),
    CONSTRAINT knowledge_runs_time_order CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (completed_at IS NULL OR completed_at >= coalesce(started_at, created_at))
    )
);

CREATE TABLE knowledge_pipeline_stages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    stage_key text NOT NULL,
    ordinal integer NOT NULL,
    status text NOT NULL DEFAULT 'not_started',
    retry_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_stages_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_stages_run_project_fkey
        FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_stages_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_stages_run_key_unique UNIQUE (pipeline_run_id, stage_key),
    CONSTRAINT knowledge_stages_run_ordinal_unique UNIQUE (pipeline_run_id, ordinal),
    CONSTRAINT knowledge_stages_key_canonical CHECK (
        stage_key IN ('import', 'crawl', 'parse', 'chunk', 'embed', 'fact_extract',
                      'fact_review', 'quality_summary')
    ),
    CONSTRAINT knowledge_stages_status_canonical CHECK (
        status IN ('not_started', 'queued', 'running', 'waiting_review',
                   'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT knowledge_stages_counts_valid CHECK (ordinal >= 0 AND retry_count >= 0)
);

CREATE TABLE knowledge_import_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    target_source_asset_id uuid NOT NULL,
    source_mode text NOT NULL,
    source_url text,
    source_text_hash text,
    upload_evidence_asset_id uuid NOT NULL,
    source_label text NOT NULL,
    authority_grade text NOT NULL DEFAULT 'D',
    usage_rights_status text NOT NULL DEFAULT 'unknown',
    authorization_basis text,
    authorised_by text,
    authorised_at timestamptz,
    confidentiality text NOT NULL DEFAULT 'internal',
    consent_status text NOT NULL DEFAULT 'unknown',
    consent_expires_at timestamptz,
    external_model_use_allowed boolean NOT NULL DEFAULT false,
    public_adaptation_allowed boolean NOT NULL DEFAULT false,
    customer_visible boolean NOT NULL DEFAULT false,
    public_disclosure_allowed boolean NOT NULL DEFAULT false,
    public_source_url text,
    public_source_title text,
    citation_label text,
    quotation_allowed boolean NOT NULL DEFAULT false,
    attribution_required boolean NOT NULL DEFAULT false,
    claim_risk text NOT NULL DEFAULT 'high',
    policy_version text NOT NULL,
    governance_hash text NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_until timestamptz,
    requested_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_import_sources_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_import_sources_run_project_fkey
        FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_import_sources_artifact_project_fkey
        FOREIGN KEY (upload_evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_import_sources_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_import_sources_target_nonzero CHECK (
        target_source_asset_id <> '00000000-0000-0000-0000-000000000000'::uuid
    ),
    CONSTRAINT knowledge_import_sources_mode_canonical CHECK (
        source_mode IN ('file', 'url', 'site', 'text', 'csv')
    ),
    CONSTRAINT knowledge_import_sources_typed CHECK (
        (source_mode IN ('file', 'csv')
            AND source_url IS NULL AND source_text_hash IS NULL)
        OR (source_mode IN ('url', 'site') AND source_url IS NOT NULL
            AND btrim(source_url) <> ''
            AND source_text_hash IS NULL)
        OR (source_mode = 'text' AND source_text_hash IS NOT NULL
            AND source_text_hash ~ '^[0-9a-f]{64}$'
            AND source_url IS NULL)
    ),
    CONSTRAINT knowledge_import_sources_text_nonempty CHECK (
        btrim(source_label) <> '' AND btrim(requested_by) <> ''
        AND btrim(policy_version) <> '' AND governance_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT knowledge_import_sources_governance_canonical CHECK (
        authority_grade IN ('A','B','C','D')
        AND usage_rights_status IN (
            'public_reuse','customer_authorised','quotation_only','internal_only','unknown')
        AND confidentiality IN ('public','internal','confidential','restricted')
        AND consent_status IN ('not_required','granted','unknown','withdrawn')
        AND claim_risk IN ('low','medium','high','prohibited')
    ),
    CONSTRAINT knowledge_import_sources_rights_coherent CHECK (
        (NOT public_adaptation_allowed OR usage_rights_status IN
            ('public_reuse','customer_authorised'))
        AND (NOT quotation_allowed OR usage_rights_status IN
            ('public_reuse','customer_authorised','quotation_only'))
        AND (NOT customer_visible OR public_disclosure_allowed)
        AND (
            (usage_rights_status = 'unknown' AND authorization_basis IS NULL
                AND authorised_by IS NULL AND authorised_at IS NULL)
            OR (usage_rights_status <> 'unknown' AND authorization_basis IS NOT NULL
                AND btrim(authorization_basis) <> '' AND authorised_by IS NOT NULL
                AND btrim(authorised_by) <> '' AND authorised_at IS NOT NULL)
        )
    ),
    CONSTRAINT knowledge_import_sources_public_coherent CHECK (
        (NOT public_disclosure_allowed AND public_source_url IS NULL
            AND public_source_title IS NULL AND citation_label IS NULL
            AND NOT quotation_allowed AND NOT attribution_required)
        OR (public_disclosure_allowed AND public_source_url IS NOT NULL
            AND btrim(public_source_url) <> '' AND public_source_title IS NOT NULL
            AND btrim(public_source_title) <> ''
            AND (citation_label IS NULL OR btrim(citation_label) <> ''))
    ),
    CONSTRAINT knowledge_import_sources_validity CHECK (
        (valid_until IS NULL OR valid_until > valid_from)
        AND (consent_expires_at IS NULL
            OR (authorised_at IS NOT NULL AND consent_expires_at > authorised_at))
    )
);

CREATE TABLE knowledge_import_source_subjects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, import_source_id uuid NOT NULL,
    subject_entity_id uuid, subject_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_import_subjects_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_import_subjects_source_project_fkey
        FOREIGN KEY (import_source_id, project_id)
        REFERENCES knowledge_import_sources(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_import_subjects_entity_project_fkey
        FOREIGN KEY (subject_entity_id, project_id)
        REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_import_subjects_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_import_subjects_pair_unique
        UNIQUE NULLS NOT DISTINCT (import_source_id, subject_entity_id, subject_role),
    CONSTRAINT knowledge_import_subjects_role_canonical CHECK (
        subject_role IN ('primary_brand','competitor','product','market','neutral')),
    CONSTRAINT knowledge_import_subjects_entity_coherent CHECK (
        (subject_role = 'neutral' AND subject_entity_id IS NULL)
        OR (subject_role <> 'neutral' AND subject_entity_id IS NOT NULL))
);

CREATE TABLE knowledge_import_source_channels (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, import_source_id uuid NOT NULL,
    publication_channel text NOT NULL, allowed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_import_channels_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_import_channels_source_project_fkey
        FOREIGN KEY (import_source_id, project_id)
        REFERENCES knowledge_import_sources(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_import_channels_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_import_channels_pair_unique
        UNIQUE (import_source_id, publication_channel),
    CONSTRAINT knowledge_import_channels_name_nonempty CHECK (
        btrim(publication_channel) <> '')
);

CREATE TABLE knowledge_pipeline_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    pipeline_run_id uuid NOT NULL,
    pipeline_stage_id uuid NOT NULL,
    import_source_id uuid,
    job_type text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    input_hash text NOT NULL,
    parent_job_id uuid,
    replay_nonce integer NOT NULL DEFAULT 0,
    priority integer NOT NULL DEFAULT 0,
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    cancel_requested_at timestamptz,
    cancel_requested_by text,
    cancel_reason text,
    finalizing_result_hash text,
    result_hash text,
    last_error_code text,
    last_error_message text,
    started_at timestamptz,
    completed_at timestamptz,
    completed_by text,
    requested_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_jobs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_jobs_run_project_fkey
        FOREIGN KEY (pipeline_run_id, project_id)
        REFERENCES knowledge_pipeline_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_jobs_stage_project_fkey
        FOREIGN KEY (pipeline_stage_id, project_id)
        REFERENCES knowledge_pipeline_stages(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_jobs_source_project_fkey
        FOREIGN KEY (import_source_id, project_id)
        REFERENCES knowledge_import_sources(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_jobs_parent_project_fkey
        FOREIGN KEY (parent_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_jobs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_jobs_idempotency_unique UNIQUE (project_id, idempotency_key),
    CONSTRAINT knowledge_jobs_parent_replay_unique
        UNIQUE (project_id, parent_job_id, replay_nonce),
    CONSTRAINT knowledge_jobs_type_canonical CHECK (
        job_type IN ('import', 'crawl', 'parse', 'chunk', 'embed', 'fact_extract')
    ),
    CONSTRAINT knowledge_jobs_status_canonical CHECK (
        status IN ('queued', 'running', 'finalizing', 'succeeded', 'failed',
                   'cancelled', 'dead_lettered')
    ),
    CONSTRAINT knowledge_jobs_source_coherent CHECK (
        (job_type IN ('import', 'crawl') AND import_source_id IS NOT NULL)
        OR (job_type NOT IN ('import', 'crawl') AND import_source_id IS NULL)
    ),
    CONSTRAINT knowledge_jobs_stage_coherent CHECK (pipeline_stage_id IS NOT NULL),
    CONSTRAINT knowledge_jobs_hashes_sha256 CHECK (
        request_hash ~ '^[0-9a-f]{64}$' AND input_hash ~ '^[0-9a-f]{64}$'
        AND (finalizing_result_hash IS NULL OR finalizing_result_hash ~ '^[0-9a-f]{64}$')
        AND (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$')
    ),
    CONSTRAINT knowledge_jobs_replay_lineage CHECK (
        (parent_job_id IS NULL AND replay_nonce = 0)
        OR (parent_job_id IS NOT NULL AND parent_job_id <> id AND replay_nonce > 0)
    ),
    CONSTRAINT knowledge_jobs_attempts_valid CHECK (
        attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts
        AND (status <> 'queued' OR attempt_count < max_attempts)
        AND (status NOT IN ('running', 'finalizing') OR attempt_count > 0)
    ),
    CONSTRAINT knowledge_jobs_cancel_coherent CHECK (
        (cancel_requested_at IS NULL AND cancel_requested_by IS NULL AND cancel_reason IS NULL)
        OR (cancel_requested_at IS NOT NULL AND cancel_requested_by IS NOT NULL
            AND btrim(cancel_requested_by) <> '' AND cancel_reason IS NOT NULL
            AND btrim(cancel_reason) <> '')
    ),
    CONSTRAINT knowledge_jobs_error_pair CHECK (
        (last_error_code IS NULL AND last_error_message IS NULL)
        OR (last_error_code IS NOT NULL AND btrim(last_error_code) <> ''
            AND last_error_message IS NOT NULL AND btrim(last_error_message) <> '')
    ),
    CONSTRAINT knowledge_jobs_lease_lifecycle CHECK (
        (status = 'queued' AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NULL AND completed_by IS NULL
            AND finalizing_result_hash IS NULL AND result_hash IS NULL
            AND cancel_requested_at IS NULL)
        OR (status IN ('running', 'finalizing') AND lease_owner IS NOT NULL
            AND btrim(lease_owner) <> '' AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL
            AND started_at IS NOT NULL AND completed_at IS NULL AND completed_by IS NULL
            AND (status = 'running' OR finalizing_result_hash IS NOT NULL))
        OR (status = 'succeeded' AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> '' AND result_hash IS NOT NULL
            AND result_hash = finalizing_result_hash AND cancel_requested_at IS NULL)
        OR (status IN ('failed', 'dead_lettered') AND lease_owner IS NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> '' AND result_hash IS NULL
            AND finalizing_result_hash IS NULL AND cancel_requested_at IS NULL)
        OR (status = 'cancelled' AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> '' AND result_hash IS NULL
            AND cancel_requested_at IS NOT NULL)
    ),
    CONSTRAINT knowledge_jobs_text_nonempty CHECK (
        btrim(idempotency_key) <> '' AND btrim(requested_by) <> ''
    ),
    CONSTRAINT knowledge_jobs_time_order CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (completed_at IS NULL OR completed_at >= coalesce(started_at, created_at))
    )
);

CREATE TABLE knowledge_pipeline_job_dependencies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    depends_on_job_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_job_deps_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_job_deps_job_project_fkey
        FOREIGN KEY (job_id, project_id) REFERENCES knowledge_pipeline_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_job_deps_parent_project_fkey
        FOREIGN KEY (depends_on_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_job_deps_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_job_deps_pair_unique UNIQUE (job_id, depends_on_job_id),
    CONSTRAINT knowledge_job_deps_not_self CHECK (job_id <> depends_on_job_id)
);

CREATE TABLE knowledge_job_artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL,
    evidence_asset_id uuid NOT NULL, artifact_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_job_artifacts_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_job_artifacts_job_project_fkey
        FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_job_artifacts_asset_project_fkey
        FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_job_artifacts_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_job_artifacts_pair_unique
        UNIQUE (knowledge_job_id, evidence_asset_id, artifact_role),
    CONSTRAINT knowledge_job_artifacts_job_role_unique
        UNIQUE (knowledge_job_id, artifact_role),
    CONSTRAINT knowledge_job_artifacts_role_nonempty CHECK (btrim(artifact_role) <> '')
);

CREATE TABLE knowledge_source_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    asset_kind text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    title text NOT NULL,
    current_revision_id uuid,
    current_governance_version_id uuid,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_assets_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_assets_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_assets_kind_canonical CHECK (
        asset_kind IN ('file', 'web_page', 'pasted_text', 'csv', 'report_extract')
    ),
    CONSTRAINT knowledge_assets_status_canonical CHECK (
        status IN ('active', 'disabled', 'archived')
    ),
    CONSTRAINT knowledge_assets_text_nonempty CHECK (
        btrim(title) <> '' AND btrim(created_by) <> ''
    )
);

CREATE TABLE knowledge_source_asset_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    knowledge_job_id uuid NOT NULL,
    source_asset_id uuid NOT NULL,
    revision_number integer NOT NULL,
    source_content_hash text NOT NULL,
    source_uri text,
    canonical_source_url text,
    mime_type text NOT NULL,
    byte_size bigint NOT NULL,
    status text NOT NULL DEFAULT 'active',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_revisions_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_revisions_job_project_fkey
        FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_revisions_asset_project_fkey
        FOREIGN KEY (source_asset_id, project_id)
        REFERENCES knowledge_source_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_revisions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_revisions_id_asset_project_unique
        UNIQUE (id, source_asset_id, project_id),
    CONSTRAINT knowledge_revisions_asset_number_unique
        UNIQUE (source_asset_id, revision_number),
    CONSTRAINT knowledge_revisions_job_unique UNIQUE (knowledge_job_id),
    CONSTRAINT knowledge_revisions_asset_hash_unique
        UNIQUE (source_asset_id, source_content_hash),
    CONSTRAINT knowledge_revisions_hash_sha256 CHECK (
        source_content_hash ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT knowledge_revisions_values_valid CHECK (
        revision_number > 0 AND byte_size >= 0 AND btrim(mime_type) <> ''
        AND btrim(created_by) <> ''
        AND (source_uri IS NULL OR btrim(source_uri) <> '')
        AND (canonical_source_url IS NULL OR btrim(canonical_source_url) <> '')
    ),
    CONSTRAINT knowledge_revisions_status_canonical CHECK (
        status IN ('active', 'superseded', 'withdrawn')
    )
);

CREATE TABLE knowledge_source_governance_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_asset_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    governance_version integer NOT NULL,
    authority_grade text NOT NULL DEFAULT 'D',
    authority_rank smallint GENERATED ALWAYS AS (
        CASE authority_grade WHEN 'A' THEN 4 WHEN 'B' THEN 3
             WHEN 'C' THEN 2 WHEN 'D' THEN 1 END
    ) STORED,
    usage_rights_status text NOT NULL DEFAULT 'unknown',
    authorization_basis text,
    authorised_by text,
    authorised_at timestamptz,
    confidentiality text NOT NULL DEFAULT 'internal',
    consent_status text NOT NULL DEFAULT 'unknown',
    consent_expires_at timestamptz,
    external_model_use_allowed boolean NOT NULL DEFAULT false,
    public_adaptation_allowed boolean NOT NULL DEFAULT false,
    customer_visible boolean NOT NULL DEFAULT false,
    public_disclosure_allowed boolean NOT NULL DEFAULT false,
    public_source_url text,
    public_source_title text,
    citation_label text,
    quotation_allowed boolean NOT NULL DEFAULT false,
    attribution_required boolean NOT NULL DEFAULT false,
    claim_risk text NOT NULL DEFAULT 'high',
    policy_version text NOT NULL,
    governance_hash text NOT NULL,
    valid_from timestamptz NOT NULL DEFAULT clock_timestamp(),
    valid_until timestamptz,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_governance_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_governance_asset_project_fkey
        FOREIGN KEY (source_asset_id, project_id)
        REFERENCES knowledge_source_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_governance_revision_project_fkey
        FOREIGN KEY (source_revision_id, source_asset_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, source_asset_id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_governance_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_governance_asset_version_unique
        UNIQUE (source_asset_id, governance_version),
    CONSTRAINT knowledge_governance_grade_canonical CHECK (
        authority_grade IN ('A', 'B', 'C', 'D')
    ),
    CONSTRAINT knowledge_governance_rights_canonical CHECK (
        usage_rights_status IN (
            'public_reuse', 'customer_authorised', 'quotation_only',
            'internal_only', 'unknown'
        )
    ),
    CONSTRAINT knowledge_governance_confidentiality_canonical CHECK (
        confidentiality IN ('public', 'internal', 'confidential', 'restricted')
    ),
    CONSTRAINT knowledge_governance_consent_canonical CHECK (
        consent_status IN ('not_required', 'granted', 'unknown', 'withdrawn')
    ),
    CONSTRAINT knowledge_governance_rights_coherent CHECK (
        (usage_rights_status = 'unknown' AND authorization_basis IS NULL
            AND authorised_by IS NULL AND authorised_at IS NULL)
        OR (usage_rights_status <> 'unknown' AND authorization_basis IS NOT NULL
            AND btrim(authorization_basis) <> '' AND authorised_by IS NOT NULL
            AND btrim(authorised_by) <> '' AND authorised_at IS NOT NULL)
    ),
    CONSTRAINT knowledge_governance_public_coherent CHECK (
        (NOT public_disclosure_allowed AND public_source_url IS NULL
            AND public_source_title IS NULL AND citation_label IS NULL
            AND NOT quotation_allowed AND NOT attribution_required)
        OR (public_disclosure_allowed AND public_source_url IS NOT NULL
            AND btrim(public_source_url) <> '' AND public_source_title IS NOT NULL
            AND btrim(public_source_title) <> ''
            AND (citation_label IS NULL OR btrim(citation_label) <> ''))
    ),
    CONSTRAINT knowledge_governance_adaptation_coherent CHECK (
        (NOT public_adaptation_allowed OR usage_rights_status IN
            ('public_reuse', 'customer_authorised'))
        AND (NOT quotation_allowed OR usage_rights_status IN
            ('public_reuse', 'customer_authorised', 'quotation_only'))
        AND (NOT customer_visible OR public_disclosure_allowed)
    ),
    CONSTRAINT knowledge_governance_consent_expiry CHECK (
        (consent_status = 'granted' AND consent_expires_at IS NULL
            OR consent_expires_at > authorised_at)
        OR (consent_status <> 'granted' AND consent_expires_at IS NULL)
    ),
    CONSTRAINT knowledge_governance_validity CHECK (
        valid_until IS NULL OR valid_until > valid_from
    ),
    CONSTRAINT knowledge_governance_values_valid CHECK (
        governance_version > 0 AND btrim(created_by) <> ''
        AND claim_risk IN ('low', 'medium', 'high', 'prohibited')
        AND btrim(policy_version) <> '' AND governance_hash ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE knowledge_source_governance_channels (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    governance_version_id uuid NOT NULL,
    publication_channel text NOT NULL,
    allowed boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_gov_channels_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_gov_channels_version_project_fkey
        FOREIGN KEY (governance_version_id, project_id)
        REFERENCES knowledge_source_governance_versions(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_gov_channels_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_gov_channels_pair_unique
        UNIQUE (governance_version_id, publication_channel),
    CONSTRAINT knowledge_gov_channels_name_nonempty CHECK (
        btrim(publication_channel) <> ''
    )
);

ALTER TABLE knowledge_source_assets
    ADD CONSTRAINT knowledge_assets_current_revision_project_fkey
        FOREIGN KEY (current_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT knowledge_assets_current_governance_project_fkey
        FOREIGN KEY (current_governance_version_id, project_id)
        REFERENCES knowledge_source_governance_versions(id, project_id)
        DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT knowledge_assets_current_pair CHECK (
        (current_revision_id IS NULL) = (current_governance_version_id IS NULL)
    );

CREATE TABLE knowledge_source_channels (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    channel_kind text NOT NULL,
    channel_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_channels_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_channels_revision_project_fkey
        FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_channels_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_channels_revision_key_unique
        UNIQUE (source_revision_id, channel_kind, channel_key),
    CONSTRAINT knowledge_channels_kind_canonical CHECK (
        channel_kind IN ('upload', 'website', 'internal', 'partner', 'public_report')
    ),
    CONSTRAINT knowledge_channels_key_nonempty CHECK (btrim(channel_key) <> '')
);

CREATE TABLE knowledge_source_subjects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    subject_entity_id uuid,
    subject_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_subjects_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_subjects_revision_project_fkey
        FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_subjects_entity_project_fkey
        FOREIGN KEY (subject_entity_id, project_id)
        REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_subjects_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_subjects_revision_entity_unique
        UNIQUE NULLS NOT DISTINCT (source_revision_id, subject_entity_id, subject_role),
    CONSTRAINT knowledge_subjects_role_canonical CHECK (
        subject_role IN ('primary_brand', 'competitor', 'product', 'market', 'neutral')
    ),
    CONSTRAINT knowledge_subjects_entity_coherent CHECK (
        (subject_role = 'neutral' AND subject_entity_id IS NULL)
        OR (subject_role <> 'neutral' AND subject_entity_id IS NOT NULL)
    )
);

CREATE TABLE knowledge_source_revision_artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    evidence_asset_id uuid NOT NULL,
    artifact_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_revision_artifacts_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_revision_artifacts_revision_project_fkey
        FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_revision_artifacts_asset_project_fkey
        FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_revision_artifacts_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_revision_artifacts_role_unique
        UNIQUE (source_revision_id, evidence_asset_id, artifact_role),
    CONSTRAINT knowledge_revision_artifacts_revision_role_unique
        UNIQUE (source_revision_id, artifact_role),
    CONSTRAINT knowledge_revision_artifacts_role_canonical CHECK (
        artifact_role IN (
            'source_snapshot', 'original', 'normalized',
            'crawl_snapshot', 'extracted_text'
        )
    )
);

CREATE TABLE knowledge_parser_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    knowledge_job_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    parser_engine text NOT NULL,
    parser_version text NOT NULL,
    status text NOT NULL DEFAULT 'succeeded',
    result_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_parser_runs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_parser_runs_job_project_fkey
        FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_parser_runs_revision_project_fkey
        FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_parser_runs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_parser_runs_id_revision_project_unique
        UNIQUE (id, source_revision_id, project_id),
    CONSTRAINT knowledge_parser_runs_job_unique UNIQUE (knowledge_job_id),
    CONSTRAINT knowledge_parser_runs_status_canonical CHECK (status = 'succeeded'),
    CONSTRAINT knowledge_parser_runs_values_valid CHECK (
        btrim(parser_engine) <> '' AND btrim(parser_version) <> ''
        AND result_hash ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE knowledge_parser_artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    parser_run_id uuid NOT NULL,
    evidence_asset_id uuid NOT NULL,
    artifact_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_parser_artifacts_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_parser_artifacts_run_project_fkey
        FOREIGN KEY (parser_run_id, project_id)
        REFERENCES knowledge_parser_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_parser_artifacts_asset_project_fkey
        FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_parser_artifacts_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_parser_artifacts_role_unique UNIQUE (parser_run_id, artifact_role),
    CONSTRAINT knowledge_parser_artifacts_role_canonical CHECK (
        artifact_role IN ('parser_json', 'markdown', 'log', 'layout')
    )
);

CREATE TABLE knowledge_blocks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, parser_run_id uuid NOT NULL,
    source_revision_id uuid NOT NULL, page_number integer,
    block_index integer NOT NULL, block_kind text NOT NULL,
    text_content text NOT NULL, content_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_blocks_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_blocks_parser_project_fkey
        FOREIGN KEY (parser_run_id, source_revision_id, project_id)
        REFERENCES knowledge_parser_runs(id, source_revision_id, project_id)
        ON DELETE CASCADE,
    CONSTRAINT knowledge_blocks_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_blocks_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_blocks_run_index_unique UNIQUE (parser_run_id, block_index),
    CONSTRAINT knowledge_blocks_values_valid CHECK (
        block_index >= 0 AND (page_number IS NULL OR page_number > 0)
        AND block_kind IN ('heading','paragraph','list','code','caption','footer','header')
        AND btrim(text_content) <> '' AND content_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE knowledge_tables (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, parser_run_id uuid NOT NULL,
    source_revision_id uuid NOT NULL, page_number integer,
    table_index integer NOT NULL, caption text, table_data jsonb NOT NULL,
    content_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_tables_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_tables_parser_project_fkey
        FOREIGN KEY (parser_run_id, source_revision_id, project_id)
        REFERENCES knowledge_parser_runs(id, source_revision_id, project_id)
        ON DELETE CASCADE,
    CONSTRAINT knowledge_tables_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_tables_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_tables_run_index_unique UNIQUE (parser_run_id, table_index),
    CONSTRAINT knowledge_tables_values_valid CHECK (
        table_index >= 0 AND (page_number IS NULL OR page_number > 0)
        AND jsonb_typeof(table_data) IN ('object','array')
        AND content_hash ~ '^[0-9a-f]{64}$'
        AND (caption IS NULL OR btrim(caption) <> ''))
);

CREATE TABLE knowledge_ocr_spans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, parser_run_id uuid NOT NULL,
    source_revision_id uuid NOT NULL, page_number integer NOT NULL,
    span_index integer NOT NULL, text_content text NOT NULL,
    confidence numeric(7,6) NOT NULL, locator jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_ocr_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_ocr_parser_project_fkey
        FOREIGN KEY (parser_run_id, source_revision_id, project_id)
        REFERENCES knowledge_parser_runs(id, source_revision_id, project_id)
        ON DELETE CASCADE,
    CONSTRAINT knowledge_ocr_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_ocr_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_ocr_run_index_unique UNIQUE (parser_run_id, page_number, span_index),
    CONSTRAINT knowledge_ocr_values_valid CHECK (
        page_number > 0 AND span_index >= 0 AND btrim(text_content) <> ''
        AND confidence BETWEEN 0 AND 1 AND jsonb_typeof(locator) = 'object')
);

CREATE TABLE knowledge_pages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, parser_run_id uuid NOT NULL,
    source_revision_id uuid NOT NULL, page_number integer NOT NULL,
    text_hash text NOT NULL, image_evidence_asset_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_pages_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_pages_parser_project_fkey
        FOREIGN KEY (parser_run_id, source_revision_id, project_id)
        REFERENCES knowledge_parser_runs(id, source_revision_id, project_id)
        ON DELETE CASCADE,
    CONSTRAINT knowledge_pages_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_pages_artifact_project_fkey
        FOREIGN KEY (image_evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_pages_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_pages_run_number_unique UNIQUE (parser_run_id, page_number),
    CONSTRAINT knowledge_pages_values_valid CHECK (
        page_number > 0 AND text_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE knowledge_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL,
    source_revision_id uuid NOT NULL, chunk_index integer NOT NULL,
    chunk_kind text NOT NULL, text_content text NOT NULL, token_count integer NOT NULL,
    content_hash text NOT NULL, locale text NOT NULL, status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_chunks_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunks_job_project_fkey FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunks_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunks_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_chunks_job_index_unique UNIQUE (knowledge_job_id, chunk_index),
    CONSTRAINT knowledge_chunks_hash_unique UNIQUE (source_revision_id, content_hash),
    CONSTRAINT knowledge_chunks_values_valid CHECK (
        chunk_index >= 0 AND token_count > 0 AND chunk_kind IN ('text','table','mixed')
        AND btrim(text_content) <> '' AND content_hash ~ '^[0-9a-f]{64}$'
        AND btrim(locale) <> '' AND status IN ('active','superseded','withdrawn'))
);

CREATE TABLE knowledge_chunk_blocks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, chunk_id uuid NOT NULL, block_id uuid NOT NULL,
    ordinal integer NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_chunk_blocks_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_blocks_chunk_project_fkey FOREIGN KEY (chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_blocks_block_project_fkey FOREIGN KEY (block_id, project_id)
        REFERENCES knowledge_blocks(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunk_blocks_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_chunk_blocks_pair_unique UNIQUE (chunk_id, block_id),
    CONSTRAINT knowledge_chunk_blocks_ordinal_unique UNIQUE (chunk_id, ordinal),
    CONSTRAINT knowledge_chunk_blocks_ordinal_valid CHECK (ordinal >= 0)
);

CREATE TABLE knowledge_chunk_tables (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, chunk_id uuid NOT NULL, table_id uuid NOT NULL,
    ordinal integer NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_chunk_tables_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_tables_chunk_project_fkey FOREIGN KEY (chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_tables_table_project_fkey FOREIGN KEY (table_id, project_id)
        REFERENCES knowledge_tables(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunk_tables_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_chunk_tables_pair_unique UNIQUE (chunk_id, table_id),
    CONSTRAINT knowledge_chunk_tables_ordinal_unique UNIQUE (chunk_id, ordinal),
    CONSTRAINT knowledge_chunk_tables_ordinal_valid CHECK (ordinal >= 0)
);

CREATE TABLE knowledge_chunk_subjects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, chunk_id uuid NOT NULL,
    subject_entity_id uuid, subject_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_chunk_subjects_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_subjects_chunk_project_fkey FOREIGN KEY (chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_subjects_entity_project_fkey FOREIGN KEY (subject_entity_id, project_id)
        REFERENCES product_entities(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunk_subjects_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_chunk_subjects_pair_unique
        UNIQUE NULLS NOT DISTINCT (chunk_id, subject_entity_id, subject_role),
    CONSTRAINT knowledge_chunk_subjects_role_canonical CHECK (
        subject_role IN ('primary_brand','competitor','product','market','neutral')),
    CONSTRAINT knowledge_chunk_subjects_entity_coherent CHECK (
        (subject_role = 'neutral' AND subject_entity_id IS NULL)
        OR (subject_role <> 'neutral' AND subject_entity_id IS NOT NULL))
);

CREATE TABLE knowledge_chunk_embeddings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL, chunk_id uuid NOT NULL,
    model_key text NOT NULL, model_version text NOT NULL, vector_store_key text NOT NULL,
    vector_point_id text NOT NULL, embedding_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_embeddings_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_embeddings_job_project_fkey FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_embeddings_chunk_project_fkey FOREIGN KEY (chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_embeddings_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_embeddings_model_unique UNIQUE (chunk_id, model_key, model_version),
    CONSTRAINT knowledge_embeddings_point_unique UNIQUE (project_id, vector_store_key, vector_point_id),
    CONSTRAINT knowledge_embeddings_values_valid CHECK (
        btrim(model_key) <> '' AND btrim(model_version) <> ''
        AND btrim(vector_store_key) <> '' AND btrim(vector_point_id) <> ''
        AND embedding_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE knowledge_chunk_job_inputs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL,
    source_revision_id uuid NOT NULL, parser_run_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_chunk_inputs_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_inputs_job_project_fkey FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_inputs_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunk_inputs_parser_project_fkey FOREIGN KEY (parser_run_id, project_id)
        REFERENCES knowledge_parser_runs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunk_inputs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_chunk_inputs_pair_unique UNIQUE (knowledge_job_id, source_revision_id),
    CONSTRAINT knowledge_chunk_inputs_parser_required CHECK (parser_run_id IS NOT NULL)
);

CREATE TABLE knowledge_parse_job_inputs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL,
    source_revision_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_parse_inputs_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_parse_inputs_job_project_fkey FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_parse_inputs_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_parse_inputs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_parse_inputs_job_unique UNIQUE (knowledge_job_id)
);

CREATE TABLE knowledge_chunk_set_job_inputs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL,
    chunk_id uuid NOT NULL, governance_version_id uuid NOT NULL,
    input_kind text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_chunk_set_inputs_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_set_inputs_job_project_fkey FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_chunk_set_inputs_chunk_project_fkey FOREIGN KEY (chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunk_set_inputs_governance_project_fkey
        FOREIGN KEY (governance_version_id, project_id)
        REFERENCES knowledge_source_governance_versions(id, project_id)
        ON DELETE RESTRICT,
    CONSTRAINT knowledge_chunk_set_inputs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_chunk_set_inputs_pair_unique UNIQUE (knowledge_job_id, chunk_id),
    CONSTRAINT knowledge_chunk_set_inputs_kind CHECK (input_kind IN ('embed','fact_extract'))
);

CREATE TABLE knowledge_job_input_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    knowledge_job_id uuid NOT NULL,
    snapshot jsonb NOT NULL,
    snapshot_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_input_snapshots_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_input_snapshots_job_project_fkey
        FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT knowledge_input_snapshots_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_input_snapshots_job_unique UNIQUE (knowledge_job_id),
    CONSTRAINT knowledge_input_snapshots_contract CHECK (
        jsonb_typeof(snapshot) = 'object'
        AND snapshot_hash ~ '^[0-9a-f]{64}$'
        AND snapshot_hash = encode(digest(snapshot::text, 'sha256'), 'hex')
    )
);

CREATE TABLE knowledge_fact_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL,
    subject_entity_id uuid, subject_role text NOT NULL,
    fact_type text NOT NULL, statement text NOT NULL, locale text NOT NULL,
    confidence numeric(7,6) NOT NULL, status text NOT NULL DEFAULT 'pending_review',
    submitted_for_review_by text NOT NULL, reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_candidates_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_candidates_job_project_fkey FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_candidates_entity_project_fkey FOREIGN KEY (subject_entity_id, project_id)
        REFERENCES product_entities(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_candidates_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_candidates_status_canonical CHECK (
        status IN ('pending_review','approved','rejected')),
    CONSTRAINT knowledge_candidates_role_canonical CHECK (
        subject_role IN ('primary_brand','competitor','product','market','neutral')),
    CONSTRAINT knowledge_candidates_entity_coherent CHECK (
        (subject_role = 'neutral' AND subject_entity_id IS NULL)
        OR (subject_role <> 'neutral' AND subject_entity_id IS NOT NULL)),
    CONSTRAINT knowledge_candidates_values_valid CHECK (
        btrim(fact_type) <> '' AND btrim(statement) <> '' AND btrim(locale) <> ''
        AND confidence BETWEEN 0 AND 1 AND btrim(submitted_for_review_by) <> ''),
    CONSTRAINT knowledge_candidates_review_time CHECK (
        (status = 'pending_review' AND reviewed_at IS NULL)
        OR (status IN ('approved','rejected') AND reviewed_at IS NOT NULL))
);

CREATE TABLE knowledge_fact_candidate_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, fact_candidate_id uuid NOT NULL,
    chunk_id uuid, block_id uuid, table_id uuid, source_revision_id uuid,
    locator jsonb NOT NULL DEFAULT '{}'::jsonb, source_snapshot_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_candidate_sources_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_candidate_sources_candidate_project_fkey FOREIGN KEY (fact_candidate_id, project_id)
        REFERENCES knowledge_fact_candidates(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_candidate_sources_chunk_project_fkey FOREIGN KEY (chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_candidate_sources_block_project_fkey FOREIGN KEY (block_id, project_id)
        REFERENCES knowledge_blocks(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_candidate_sources_table_project_fkey FOREIGN KEY (table_id, project_id)
        REFERENCES knowledge_tables(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_candidate_sources_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_candidate_sources_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_candidate_sources_typed CHECK (
        num_nonnulls(chunk_id, block_id, table_id, source_revision_id) = 1),
    CONSTRAINT knowledge_candidate_sources_hash CHECK (
        source_snapshot_hash ~ '^[0-9a-f]{64}$' AND jsonb_typeof(locator) = 'object')
);

CREATE TABLE knowledge_fact_candidate_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, fact_candidate_id uuid NOT NULL,
    decision text NOT NULL, reviewer_id text NOT NULL, review_notes text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_candidate_reviews_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_candidate_reviews_candidate_project_fkey FOREIGN KEY (fact_candidate_id, project_id)
        REFERENCES knowledge_fact_candidates(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_candidate_reviews_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_candidate_reviews_candidate_unique UNIQUE (fact_candidate_id),
    CONSTRAINT knowledge_candidate_reviews_decision CHECK (decision IN ('approved','rejected')),
    CONSTRAINT knowledge_candidate_reviews_values CHECK (
        btrim(reviewer_id) <> '' AND (review_notes IS NULL OR btrim(review_notes) <> ''))
);

CREATE TABLE knowledge_facts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, subject_entity_id uuid,
    subject_role text NOT NULL, fact_type text NOT NULL,
    status text NOT NULL DEFAULT 'active', current_version_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_facts_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_facts_entity_project_fkey FOREIGN KEY (subject_entity_id, project_id)
        REFERENCES product_entities(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_facts_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_facts_role_canonical CHECK (
        subject_role IN ('primary_brand','competitor','product','market','neutral')),
    CONSTRAINT knowledge_facts_entity_coherent CHECK (
        (subject_role = 'neutral' AND subject_entity_id IS NULL)
        OR (subject_role <> 'neutral' AND subject_entity_id IS NOT NULL)),
    CONSTRAINT knowledge_facts_values_valid CHECK (
        btrim(fact_type) <> '' AND status IN ('active','superseded','withdrawn'))
);

CREATE TABLE knowledge_fact_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, fact_id uuid NOT NULL, version_number integer NOT NULL,
    base_version_id uuid, base_statement_hash text,
    source_candidate_id uuid NOT NULL, statement text NOT NULL, locale text NOT NULL,
    statement_hash text NOT NULL, authority_grade text NOT NULL,
    valid_from timestamptz NOT NULL, valid_until timestamptz,
    customer_visible boolean NOT NULL DEFAULT false,
    public_disclosure_allowed boolean NOT NULL DEFAULT false,
    public_source_url text, public_source_title text, citation_label text,
    quotation_allowed boolean NOT NULL DEFAULT false,
    attribution_required boolean NOT NULL DEFAULT false,
    approved_by text NOT NULL, approved_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_fact_versions_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_fact_versions_fact_project_fkey FOREIGN KEY (fact_id, project_id)
        REFERENCES knowledge_facts(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_fact_versions_candidate_project_fkey FOREIGN KEY (source_candidate_id, project_id)
        REFERENCES knowledge_fact_candidates(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_fact_versions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_fact_versions_fact_number_unique UNIQUE (fact_id, version_number),
    CONSTRAINT knowledge_fact_versions_candidate_unique UNIQUE (source_candidate_id),
    CONSTRAINT knowledge_fact_versions_base_project_fkey
        FOREIGN KEY (base_version_id, project_id)
        REFERENCES knowledge_fact_versions(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT knowledge_fact_versions_values_valid CHECK (
        version_number > 0 AND btrim(statement) <> '' AND btrim(locale) <> ''
        AND statement_hash ~ '^[0-9a-f]{64}$' AND authority_grade IN ('A','B','C','D')
        AND ((version_number = 1 AND base_version_id IS NULL
                AND base_statement_hash IS NULL)
             OR (version_number > 1 AND base_version_id IS NOT NULL
                AND base_statement_hash ~ '^[0-9a-f]{64}$'))
        AND btrim(approved_by) <> '' AND approved_at >= valid_from
        AND (valid_until IS NULL OR valid_until > valid_from)),
    CONSTRAINT knowledge_fact_versions_public_coherent CHECK (
        (NOT public_disclosure_allowed AND public_source_url IS NULL
            AND public_source_title IS NULL AND citation_label IS NULL
            AND NOT quotation_allowed AND NOT attribution_required)
        OR (public_disclosure_allowed AND public_source_url IS NOT NULL
            AND btrim(public_source_url) <> '' AND public_source_title IS NOT NULL
            AND btrim(public_source_title) <> ''
            AND (citation_label IS NULL OR btrim(citation_label) <> '')))
);

ALTER TABLE knowledge_facts ADD CONSTRAINT knowledge_facts_current_version_project_fkey
    FOREIGN KEY (current_version_id, project_id)
    REFERENCES knowledge_fact_versions(id, project_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE knowledge_fact_version_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, fact_version_id uuid NOT NULL,
    governance_version_id uuid NOT NULL,
    chunk_id uuid, block_id uuid, table_id uuid, source_revision_id uuid,
    locator jsonb NOT NULL DEFAULT '{}'::jsonb, source_snapshot_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_fact_sources_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_fact_sources_version_project_fkey FOREIGN KEY (fact_version_id, project_id)
        REFERENCES knowledge_fact_versions(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_fact_sources_governance_project_fkey
        FOREIGN KEY (governance_version_id, project_id)
        REFERENCES knowledge_source_governance_versions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_fact_sources_chunk_project_fkey FOREIGN KEY (chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_fact_sources_block_project_fkey FOREIGN KEY (block_id, project_id)
        REFERENCES knowledge_blocks(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_fact_sources_table_project_fkey FOREIGN KEY (table_id, project_id)
        REFERENCES knowledge_tables(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_fact_sources_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_fact_sources_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_fact_sources_typed CHECK (
        num_nonnulls(chunk_id, block_id, table_id, source_revision_id) = 1),
    CONSTRAINT knowledge_fact_sources_hash CHECK (
        source_snapshot_hash ~ '^[0-9a-f]{64}$' AND jsonb_typeof(locator) = 'object')
);

CREATE TABLE knowledge_quality_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, definition_key text NOT NULL, version integer NOT NULL,
    job_type text NOT NULL,
    target_kind text NOT NULL, severity_on_failure text NOT NULL,
    rule_contract jsonb NOT NULL, policy_class text NOT NULL,
    required boolean NOT NULL DEFAULT true, active boolean NOT NULL DEFAULT true,
    created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_quality_defs_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_quality_defs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_quality_defs_key_version_unique UNIQUE (project_id, definition_key, version),
    CONSTRAINT knowledge_quality_defs_values CHECK (
        btrim(definition_key) <> '' AND version > 0
        AND job_type IN ('import','crawl','parse','chunk','embed','fact_extract')
        AND target_kind IN ('source_revision','parser_run','chunk','fact_candidate')
        AND severity_on_failure IN ('info','warning','high','critical','hard_block')
        AND policy_class IN ('quality','traceability','rights','security','classification')
        AND required
        AND (policy_class NOT IN ('traceability','rights','security','classification')
             OR severity_on_failure = 'hard_block')
        AND jsonb_typeof(rule_contract) = 'object' AND btrim(created_by) <> '')
);

CREATE TABLE knowledge_job_quality_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL,
    quality_definition_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_job_quality_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_job_quality_job_project_fkey FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_job_quality_definition_project_fkey
        FOREIGN KEY (quality_definition_id, project_id)
        REFERENCES knowledge_quality_definitions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_job_quality_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_job_quality_pair_unique
        UNIQUE (knowledge_job_id, quality_definition_id)
);

CREATE TABLE knowledge_quality_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, knowledge_job_id uuid NOT NULL,
    quality_definition_id uuid NOT NULL, target_kind text NOT NULL,
    source_revision_id uuid, parser_run_id uuid, chunk_id uuid,
    fact_candidate_id uuid,
    status text NOT NULL, result_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_quality_runs_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_quality_runs_job_project_fkey FOREIGN KEY (knowledge_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_quality_runs_definition_project_fkey FOREIGN KEY (quality_definition_id, project_id)
        REFERENCES knowledge_quality_definitions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_quality_runs_revision_project_fkey FOREIGN KEY (source_revision_id, project_id)
        REFERENCES knowledge_source_asset_revisions(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_quality_runs_parser_project_fkey FOREIGN KEY (parser_run_id, project_id)
        REFERENCES knowledge_parser_runs(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_quality_runs_chunk_project_fkey FOREIGN KEY (chunk_id, project_id)
        REFERENCES knowledge_chunks(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_quality_runs_candidate_project_fkey FOREIGN KEY (fact_candidate_id, project_id)
        REFERENCES knowledge_fact_candidates(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_quality_runs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_quality_runs_job_definition_target_unique
        UNIQUE NULLS NOT DISTINCT (
            knowledge_job_id, quality_definition_id, source_revision_id,
            parser_run_id, chunk_id, fact_candidate_id
        ),
    CONSTRAINT knowledge_quality_runs_typed_target CHECK (
        num_nonnulls(source_revision_id, parser_run_id, chunk_id, fact_candidate_id) = 1
        AND ((target_kind='source_revision' AND source_revision_id IS NOT NULL)
          OR (target_kind='parser_run' AND parser_run_id IS NOT NULL)
          OR (target_kind='chunk' AND chunk_id IS NOT NULL)
          OR (target_kind='fact_candidate' AND fact_candidate_id IS NOT NULL))),
    CONSTRAINT knowledge_quality_runs_values CHECK (
        status IN ('passed','failed') AND result_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE knowledge_quality_findings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, quality_run_id uuid NOT NULL,
    finding_code text NOT NULL, severity text NOT NULL, message text NOT NULL,
    finding_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_quality_findings_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_quality_findings_run_project_fkey FOREIGN KEY (quality_run_id, project_id)
        REFERENCES knowledge_quality_runs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_quality_findings_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_quality_findings_run_hash_unique UNIQUE (quality_run_id, finding_hash),
    CONSTRAINT knowledge_quality_findings_values CHECK (
        btrim(finding_code) <> '' AND severity IN ('info','warning','high','critical','hard_block')
        AND btrim(message) <> '' AND finding_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE knowledge_risk_acceptances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
    project_id uuid NOT NULL, quality_finding_id uuid NOT NULL,
    accepted_by text NOT NULL, acceptance_reason text NOT NULL,
    accepted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT knowledge_risk_acceptances_project_tenant_fkey FOREIGN KEY (project_id, tenant_id)
        REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    CONSTRAINT knowledge_risk_acceptances_finding_project_fkey FOREIGN KEY (quality_finding_id, project_id)
        REFERENCES knowledge_quality_findings(id, project_id) ON DELETE RESTRICT,
    CONSTRAINT knowledge_risk_acceptances_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT knowledge_risk_acceptances_finding_unique UNIQUE (quality_finding_id),
    CONSTRAINT knowledge_risk_acceptances_values CHECK (
        btrim(accepted_by) <> '' AND btrim(acceptance_reason) <> '')
);

-- Extend the shared wake-up outbox with a typed Knowledge job reference. The
-- outbox is not the business state machine; knowledge_pipeline_jobs remains
-- authoritative and both rows are created by one PostgreSQL transaction.
ALTER TABLE durable_job_dispatch_outbox
    ADD COLUMN knowledge_pipeline_job_id uuid;

ALTER TABLE durable_job_dispatch_outbox
    ADD CONSTRAINT durable_dispatch_knowledge_project_fkey
        FOREIGN KEY (knowledge_pipeline_job_id, project_id)
        REFERENCES knowledge_pipeline_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE;

ALTER TABLE durable_job_dispatch_outbox
    DROP CONSTRAINT durable_dispatch_kind_canonical,
    DROP CONSTRAINT durable_dispatch_job_discriminator;

ALTER TABLE durable_job_dispatch_outbox
    ADD CONSTRAINT durable_dispatch_kind_canonical CHECK (
        job_kind IN (
            'collection', 'visibility_score', 'retest',
            'knowledge_import', 'knowledge_crawl', 'knowledge_parse',
            'knowledge_chunk', 'knowledge_embed', 'knowledge_fact_extract'
        )
    ),
    ADD CONSTRAINT durable_dispatch_job_discriminator CHECK (
        (job_kind = 'collection' AND collection_job_id = job_id
            AND visibility_score_run_id IS NULL AND retest_run_id IS NULL
            AND knowledge_pipeline_job_id IS NULL)
        OR (job_kind = 'visibility_score' AND visibility_score_run_id = job_id
            AND collection_job_id IS NULL AND retest_run_id IS NULL
            AND knowledge_pipeline_job_id IS NULL)
        OR (job_kind = 'retest' AND retest_run_id = job_id
            AND collection_job_id IS NULL AND visibility_score_run_id IS NULL
            AND knowledge_pipeline_job_id IS NULL)
        OR (job_kind IN (
                'knowledge_import', 'knowledge_crawl', 'knowledge_parse',
                'knowledge_chunk', 'knowledge_embed', 'knowledge_fact_extract'
            ) AND knowledge_pipeline_job_id = job_id
            AND collection_job_id IS NULL AND visibility_score_run_id IS NULL
            AND retest_run_id IS NULL)
    );

CREATE OR REPLACE FUNCTION geno_v2_enqueue_durable_job_dispatch()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $enqueue_durable_dispatch$
DECLARE
    canonical_kind text;
    canonical_payload_hash text;
    canonical_idempotency text;
    canonical_replay_nonce integer;
BEGIN
    canonical_kind := CASE TG_TABLE_NAME
        WHEN 'collection_jobs' THEN 'collection'
        WHEN 'visibility_score_runs' THEN 'visibility_score'
        WHEN 'retest_runs' THEN 'retest'
        WHEN 'knowledge_pipeline_jobs' THEN 'knowledge_' || NEW.job_type
        ELSE NULL
    END;
    IF canonical_kind IS NULL THEN
        RAISE EXCEPTION 'unsupported durable job dispatch source'
            USING ERRCODE = '23514';
    END IF;
    canonical_idempotency := NEW.idempotency_key;
    canonical_replay_nonce := NEW.replay_nonce;
    canonical_payload_hash := encode(
        public.digest(
            jsonb_build_object(
                'job_kind', canonical_kind,
                'job_id', NEW.id,
                'project_id', NEW.project_id,
                'idempotency_key', canonical_idempotency,
                'replay_nonce', canonical_replay_nonce
            )::text,
            'sha256'
        ),
        'hex'
    );
    INSERT INTO public.durable_job_dispatch_outbox (
        tenant_id, project_id, job_kind, job_id,
        collection_job_id, visibility_score_run_id, retest_run_id,
        knowledge_pipeline_job_id, payload_hash
    ) VALUES (
        NEW.tenant_id, NEW.project_id, canonical_kind, NEW.id,
        CASE WHEN canonical_kind = 'collection' THEN NEW.id ELSE NULL END,
        CASE WHEN canonical_kind = 'visibility_score' THEN NEW.id ELSE NULL END,
        CASE WHEN canonical_kind = 'retest' THEN NEW.id ELSE NULL END,
        CASE WHEN canonical_kind LIKE 'knowledge_%' THEN NEW.id ELSE NULL END,
        canonical_payload_hash
    );
    RETURN NEW;
END;
$enqueue_durable_dispatch$;

CREATE TRIGGER knowledge_jobs_enqueue_dispatch
AFTER INSERT ON knowledge_pipeline_jobs
FOR EACH ROW EXECUTE FUNCTION geno_v2_enqueue_durable_job_dispatch();

CREATE FUNCTION geno_v2_reject_knowledge_immutable_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $reject_knowledge_immutable$
BEGIN
    RAISE EXCEPTION '% rows are immutable after insert', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$reject_knowledge_immutable$;

CREATE FUNCTION geno_v2_guard_knowledge_asset_head()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard_knowledge_asset_head$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.asset_kind IS DISTINCT FROM OLD.asset_kind
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'source asset identity is immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.current_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.knowledge_source_asset_revisions AS revision
        WHERE revision.id = NEW.current_revision_id
          AND revision.project_id = NEW.project_id
          AND revision.source_asset_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'current source revision does not belong to source asset'
            USING ERRCODE = '23503';
    END IF;
    IF NEW.current_governance_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.knowledge_source_governance_versions AS governance
        WHERE governance.id = NEW.current_governance_version_id
          AND governance.project_id = NEW.project_id
          AND governance.source_asset_id = NEW.id
          AND governance.source_revision_id = NEW.current_revision_id
    ) THEN
        RAISE EXCEPTION 'current governance does not govern current source revision'
            USING ERRCODE = '23503';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
        (OLD.status = 'active' AND NEW.status IN ('disabled','archived'))
        OR (OLD.status = 'disabled' AND NEW.status = 'archived')
        OR (OLD.status = 'disabled' AND NEW.status = 'active'
            AND NEW.current_governance_version_id IS DISTINCT FROM
                OLD.current_governance_version_id)
    ) THEN
        RAISE EXCEPTION 'source asset status transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_knowledge_asset_head$;

CREATE FUNCTION geno_v2_guard_candidate_transition()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_candidate_transition$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.knowledge_job_id IS DISTINCT FROM OLD.knowledge_job_id
       OR NEW.subject_entity_id IS DISTINCT FROM OLD.subject_entity_id
       OR NEW.subject_role IS DISTINCT FROM OLD.subject_role
       OR NEW.fact_type IS DISTINCT FROM OLD.fact_type
       OR NEW.statement IS DISTINCT FROM OLD.statement
       OR NEW.locale IS DISTINCT FROM OLD.locale
       OR NEW.confidence IS DISTINCT FROM OLD.confidence
       OR NEW.submitted_for_review_by IS DISTINCT FROM OLD.submitted_for_review_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR OLD.status <> 'pending_review'
       OR NEW.status NOT IN ('approved', 'rejected')
       OR NEW.reviewed_at IS NULL THEN
        RAISE EXCEPTION 'fact candidate allows one pending-to-terminal review transition'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_candidate_transition$;

CREATE FUNCTION geno_v2_guard_fact_head()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard_fact_head$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.subject_entity_id IS DISTINCT FROM OLD.subject_entity_id
       OR NEW.subject_role IS DISTINCT FROM OLD.subject_role
       OR NEW.fact_type IS DISTINCT FROM OLD.fact_type
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'fact identity is immutable' USING ERRCODE = '55000';
    END IF;
    IF NEW.current_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.knowledge_fact_versions AS version_row
        WHERE version_row.id = NEW.current_version_id
          AND version_row.project_id = NEW.project_id
          AND version_row.fact_id = NEW.id
    ) THEN
        RAISE EXCEPTION 'current fact version does not belong to fact'
            USING ERRCODE = '23503';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status
       AND NOT (OLD.status = 'active' AND NEW.status IN ('superseded','withdrawn')) THEN
        RAISE EXCEPTION 'fact status transition is invalid' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_fact_head$;

CREATE TRIGGER knowledge_asset_head_guard BEFORE UPDATE ON knowledge_source_assets
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_knowledge_asset_head();
CREATE TRIGGER knowledge_asset_head_delete BEFORE DELETE ON knowledge_source_assets
FOR EACH ROW EXECUTE FUNCTION geno_v2_reject_knowledge_immutable_update();
CREATE TRIGGER knowledge_candidate_guard BEFORE UPDATE ON knowledge_fact_candidates
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_candidate_transition();
CREATE TRIGGER knowledge_candidate_delete BEFORE DELETE ON knowledge_fact_candidates
FOR EACH ROW EXECUTE FUNCTION geno_v2_reject_knowledge_immutable_update();
CREATE TRIGGER knowledge_fact_head_guard BEFORE UPDATE ON knowledge_facts
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_fact_head();
CREATE TRIGGER knowledge_fact_head_delete BEFORE DELETE ON knowledge_facts
FOR EACH ROW EXECUTE FUNCTION geno_v2_reject_knowledge_immutable_update();

DO $knowledge_immutable_triggers$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'knowledge_source_asset_revisions', 'knowledge_source_governance_versions',
        'knowledge_source_channels', 'knowledge_source_subjects',
        'knowledge_source_revision_artifacts', 'knowledge_parser_runs',
        'knowledge_parser_artifacts', 'knowledge_blocks', 'knowledge_tables',
        'knowledge_ocr_spans', 'knowledge_pages', 'knowledge_chunks',
        'knowledge_chunk_blocks', 'knowledge_chunk_tables',
        'knowledge_chunk_subjects', 'knowledge_chunk_embeddings',
        'knowledge_fact_candidate_sources', 'knowledge_fact_candidate_reviews',
        'knowledge_fact_versions', 'knowledge_fact_version_sources',
        'knowledge_quality_runs', 'knowledge_quality_findings',
        'knowledge_risk_acceptances'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.geno_v2_reject_knowledge_immutable_update()',
            table_name || '_immutable', table_name
        );
    END LOOP;
END;
$knowledge_immutable_triggers$;

CREATE FUNCTION geno_v2_require_finalized_knowledge_artifact()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $require_finalized_knowledge_artifact$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.evidence_assets AS asset
        WHERE asset.id = NEW.evidence_asset_id
          AND asset.project_id = NEW.project_id
          AND asset.tenant_id = NEW.tenant_id
          AND asset.artifact_status IN ('pending', 'finalized')
    ) THEN
        RAISE EXCEPTION 'knowledge artifact must be a pending or finalized project artifact'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$require_finalized_knowledge_artifact$;

CREATE TRIGGER knowledge_revision_artifact_guard
BEFORE INSERT ON knowledge_source_revision_artifacts
FOR EACH ROW EXECUTE FUNCTION geno_v2_require_finalized_knowledge_artifact();
CREATE TRIGGER knowledge_parser_artifact_guard
BEFORE INSERT ON knowledge_parser_artifacts
FOR EACH ROW EXECUTE FUNCTION geno_v2_require_finalized_knowledge_artifact();

CREATE FUNCTION geno_v2_require_finalized_parser_input()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $require_finalized_parser_input$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.knowledge_parser_artifacts AS link
        JOIN public.evidence_assets AS asset
          ON asset.id = link.evidence_asset_id AND asset.project_id = link.project_id
        WHERE link.parser_run_id = NEW.parser_run_id
          AND link.project_id = NEW.project_id
          AND asset.artifact_status <> 'finalized'
    ) THEN
        RAISE EXCEPTION 'chunk input parser artifacts are not finalized'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$require_finalized_parser_input$;

CREATE TRIGGER knowledge_chunk_input_finalize_guard
BEFORE INSERT ON knowledge_chunk_job_inputs
FOR EACH ROW EXECUTE FUNCTION geno_v2_require_finalized_parser_input();

CREATE FUNCTION geno_v2_validate_knowledge_subject()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_knowledge_subject$
DECLARE entity_kind text;
BEGIN
    IF NEW.subject_role = 'neutral' THEN
        IF NEW.subject_entity_id IS NOT NULL THEN
            RAISE EXCEPTION 'neutral subjects cannot reference an entity'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT entity.entity_kind INTO entity_kind
    FROM public.product_entities AS entity
    WHERE entity.id = NEW.subject_entity_id
      AND entity.project_id = NEW.project_id
      AND entity.status = 'active';
    IF NOT FOUND OR NOT (
        (NEW.subject_role = 'primary_brand' AND entity_kind IN ('brand','organization'))
        OR (NEW.subject_role = 'competitor'
            AND entity_kind IN ('competitor','brand','organization'))
        OR (NEW.subject_role = 'product' AND entity_kind = 'product')
        OR (NEW.subject_role = 'market' AND entity_kind IN ('market','category'))
    ) THEN
        RAISE EXCEPTION 'subject role does not match an active project entity kind'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$validate_knowledge_subject$;

CREATE CONSTRAINT TRIGGER knowledge_source_subject_entity_kind
AFTER INSERT ON knowledge_source_subjects DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_subject();
CREATE CONSTRAINT TRIGGER knowledge_chunk_subject_entity_kind
AFTER INSERT ON knowledge_chunk_subjects DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_subject();
CREATE CONSTRAINT TRIGGER knowledge_candidate_subject_entity_kind
AFTER INSERT ON knowledge_fact_candidates DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_subject();
CREATE CONSTRAINT TRIGGER knowledge_fact_subject_entity_kind
AFTER INSERT ON knowledge_facts DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_subject();

CREATE FUNCTION geno_v2_validate_knowledge_job_result_type()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_knowledge_job_result_type$
DECLARE actual_type text;
BEGIN
    SELECT job.job_type INTO actual_type
    FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = NEW.knowledge_job_id AND job.project_id = NEW.project_id;
    IF NOT FOUND OR actual_type <> TG_ARGV[0] THEN
        RAISE EXCEPTION '% output requires a % knowledge job', TG_TABLE_NAME, TG_ARGV[0]
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$validate_knowledge_job_result_type$;

CREATE CONSTRAINT TRIGGER knowledge_revision_job_type
AFTER INSERT ON knowledge_source_asset_revisions DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_job_result_type('import_or_crawl');

CREATE FUNCTION geno_v2_validate_knowledge_revision_job_type()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_knowledge_revision_job_type$
DECLARE actual_type text;
BEGIN
    SELECT job.job_type INTO actual_type FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = NEW.knowledge_job_id AND job.project_id = NEW.project_id;
    IF actual_type NOT IN ('import','crawl') THEN
        RAISE EXCEPTION 'source revisions require an import or crawl knowledge job'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$validate_knowledge_revision_job_type$;

DROP TRIGGER knowledge_revision_job_type ON knowledge_source_asset_revisions;
CREATE CONSTRAINT TRIGGER knowledge_revision_job_type
AFTER INSERT ON knowledge_source_asset_revisions DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_revision_job_type();
CREATE CONSTRAINT TRIGGER knowledge_parser_job_type
AFTER INSERT ON knowledge_parser_runs DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_job_result_type('parse');
CREATE CONSTRAINT TRIGGER knowledge_chunk_job_type
AFTER INSERT ON knowledge_chunks DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_job_result_type('chunk');
CREATE CONSTRAINT TRIGGER knowledge_chunk_input_job_type
AFTER INSERT ON knowledge_chunk_job_inputs DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_job_result_type('chunk');
CREATE CONSTRAINT TRIGGER knowledge_embedding_job_type
AFTER INSERT ON knowledge_chunk_embeddings DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_job_result_type('embed');
CREATE CONSTRAINT TRIGGER knowledge_candidate_job_type
AFTER INSERT ON knowledge_fact_candidates DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_job_result_type('fact_extract');

CREATE FUNCTION geno_v2_validate_knowledge_job_stage()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_knowledge_job_stage$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.knowledge_pipeline_stages AS stage
        WHERE stage.id = NEW.pipeline_stage_id
          AND stage.project_id = NEW.project_id
          AND stage.pipeline_run_id = NEW.pipeline_run_id
          AND stage.stage_key = NEW.job_type
    ) THEN
        RAISE EXCEPTION 'knowledge job type must match its run stage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$validate_knowledge_job_stage$;

CREATE CONSTRAINT TRIGGER knowledge_job_stage_contract
AFTER INSERT ON knowledge_pipeline_jobs DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_job_stage();

CREATE FUNCTION geno_v2_knowledge_job_inputs_ready(p_job_id uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $knowledge_job_inputs_ready$
DECLARE job_row public.knowledge_pipeline_jobs%ROWTYPE;
BEGIN
    SELECT * INTO job_row
    FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = p_job_id;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.knowledge_job_input_snapshots AS input_snapshot
        WHERE input_snapshot.knowledge_job_id = job_row.id
          AND input_snapshot.project_id = job_row.project_id
          AND input_snapshot.snapshot_hash = job_row.input_hash
    ) THEN
        RETURN false;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.knowledge_pipeline_job_dependencies AS dependency
        LEFT JOIN public.knowledge_pipeline_jobs AS upstream
          ON upstream.id = dependency.depends_on_job_id
         AND upstream.project_id = dependency.project_id
        WHERE dependency.job_id = job_row.id
          AND dependency.project_id = job_row.project_id
          AND (upstream.id IS NULL OR upstream.status <> 'succeeded')
    ) THEN
        RETURN false;
    END IF;
    IF job_row.job_type IN ('import','crawl') THEN
        RETURN EXISTS (
            SELECT 1
            FROM public.knowledge_import_sources AS source_input
            JOIN public.evidence_assets AS artifact
              ON artifact.id = source_input.upload_evidence_asset_id
             AND artifact.project_id = source_input.project_id
            WHERE source_input.id = job_row.import_source_id
              AND source_input.project_id = job_row.project_id
              AND artifact.artifact_status = 'finalized'
        );
    ELSIF job_row.job_type = 'parse' THEN
        RETURN (
            SELECT count(*) = 1 AND bool_and(
                revision.status = 'active'
                AND source_asset.status = 'active'
                AND source_asset.current_revision_id = revision.id
                AND producer.status = 'succeeded'
                AND NOT EXISTS (
                    SELECT 1
                    FROM public.knowledge_job_artifacts AS link
                    JOIN public.evidence_assets AS artifact
                      ON artifact.id = link.evidence_asset_id
                     AND artifact.project_id = link.project_id
                    WHERE link.knowledge_job_id = producer.id
                      AND link.project_id = producer.project_id
                      AND artifact.artifact_status <> 'finalized'
                )
                AND EXISTS (
                    SELECT 1
                    FROM public.knowledge_source_revision_artifacts AS link
                    JOIN public.evidence_assets AS artifact
                      ON artifact.id = link.evidence_asset_id
                     AND artifact.project_id = link.project_id
                    WHERE link.source_revision_id = revision.id
                      AND link.project_id = revision.project_id
                      AND artifact.artifact_status = 'finalized'
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM public.knowledge_source_revision_artifacts AS link
                    JOIN public.evidence_assets AS artifact
                      ON artifact.id = link.evidence_asset_id
                     AND artifact.project_id = link.project_id
                    WHERE link.source_revision_id = revision.id
                      AND link.project_id = revision.project_id
                      AND artifact.artifact_status <> 'finalized'
                )
            )
            FROM public.knowledge_parse_job_inputs AS input_row
            JOIN public.knowledge_source_asset_revisions AS revision
              ON revision.id = input_row.source_revision_id
             AND revision.project_id = input_row.project_id
            JOIN public.knowledge_source_assets AS source_asset
              ON source_asset.id = revision.source_asset_id
             AND source_asset.project_id = revision.project_id
            JOIN public.knowledge_pipeline_jobs AS producer
              ON producer.id = revision.knowledge_job_id
             AND producer.project_id = revision.project_id
            WHERE input_row.knowledge_job_id = job_row.id
              AND input_row.project_id = job_row.project_id
        );
    ELSIF job_row.job_type = 'chunk' THEN
        RETURN (
            SELECT count(*) = 1 AND bool_and(
                parser_run.status = 'succeeded'
                AND parser_run.source_revision_id = input_row.source_revision_id
                AND producer.status = 'succeeded'
                AND revision.status = 'active'
                AND source_asset.status = 'active'
                AND source_asset.current_revision_id = revision.id
                AND EXISTS (
                    SELECT 1 FROM public.knowledge_parser_artifacts AS link
                    JOIN public.evidence_assets AS artifact
                      ON artifact.id = link.evidence_asset_id
                     AND artifact.project_id = link.project_id
                    WHERE link.parser_run_id = parser_run.id
                      AND link.project_id = parser_run.project_id
                      AND artifact.artifact_status = 'finalized'
                )
                AND NOT EXISTS (
                    SELECT 1 FROM public.knowledge_parser_artifacts AS link
                    JOIN public.evidence_assets AS artifact
                      ON artifact.id = link.evidence_asset_id
                     AND artifact.project_id = link.project_id
                    WHERE link.parser_run_id = parser_run.id
                      AND link.project_id = parser_run.project_id
                      AND artifact.artifact_status <> 'finalized'
                )
            )
            FROM public.knowledge_chunk_job_inputs AS input_row
            JOIN public.knowledge_parser_runs AS parser_run
              ON parser_run.id = input_row.parser_run_id
             AND parser_run.source_revision_id = input_row.source_revision_id
             AND parser_run.project_id = input_row.project_id
            JOIN public.knowledge_pipeline_jobs AS producer
              ON producer.id = parser_run.knowledge_job_id
             AND producer.project_id = parser_run.project_id
            JOIN public.knowledge_source_asset_revisions AS revision
              ON revision.id = input_row.source_revision_id
             AND revision.project_id = input_row.project_id
            JOIN public.knowledge_source_assets AS source_asset
              ON source_asset.id = revision.source_asset_id
             AND source_asset.project_id = revision.project_id
            WHERE input_row.knowledge_job_id = job_row.id
              AND input_row.project_id = job_row.project_id
        );
    ELSE
        RETURN EXISTS (
            SELECT 1 FROM public.knowledge_chunk_set_job_inputs AS input_row
            WHERE input_row.knowledge_job_id = job_row.id
              AND input_row.project_id = job_row.project_id
              AND input_row.input_kind = job_row.job_type
        ) AND NOT EXISTS (
            SELECT 1
            FROM public.knowledge_chunk_set_job_inputs AS input_row
            LEFT JOIN public.knowledge_chunks AS chunk_row
              ON chunk_row.id = input_row.chunk_id
             AND chunk_row.project_id = input_row.project_id
            LEFT JOIN public.knowledge_pipeline_jobs AS producer
              ON producer.id = chunk_row.knowledge_job_id
             AND producer.project_id = chunk_row.project_id
            LEFT JOIN public.knowledge_source_asset_revisions AS revision
              ON revision.id = chunk_row.source_revision_id
             AND revision.project_id = chunk_row.project_id
            LEFT JOIN public.knowledge_source_assets AS source_asset
              ON source_asset.id = revision.source_asset_id
             AND source_asset.project_id = revision.project_id
            LEFT JOIN public.knowledge_source_governance_versions AS governance
              ON governance.id = input_row.governance_version_id
             AND governance.source_revision_id = revision.id
             AND governance.project_id = source_asset.project_id
            WHERE input_row.knowledge_job_id = job_row.id
              AND input_row.project_id = job_row.project_id
              AND (
                  chunk_row.id IS NULL OR chunk_row.status <> 'active'
                  OR producer.status <> 'succeeded'
                  OR revision.status <> 'active' OR source_asset.status <> 'active'
                  OR source_asset.current_revision_id <> revision.id
                  OR source_asset.current_governance_version_id <> governance.id
                  OR governance.id IS NULL OR NOT governance.external_model_use_allowed
                  OR governance.confidentiality = 'restricted'
                  OR governance.consent_status NOT IN ('not_required','granted')
                  OR (governance.consent_expires_at IS NOT NULL
                      AND governance.consent_expires_at <= statement_timestamp())
                  OR governance.valid_from > statement_timestamp()
                  OR (governance.valid_until IS NOT NULL
                      AND governance.valid_until <= statement_timestamp())
                  OR EXISTS (
                      SELECT 1 FROM public.knowledge_job_artifacts AS link
                      JOIN public.evidence_assets AS artifact
                        ON artifact.id = link.evidence_asset_id
                       AND artifact.project_id = link.project_id
                      WHERE link.knowledge_job_id = producer.id
                        AND link.project_id = producer.project_id
                        AND artifact.artifact_status <> 'finalized'
                  )
              )
        );
    END IF;
END;
$knowledge_job_inputs_ready$;

CREATE FUNCTION geno_v2_require_ready_knowledge_job_inputs()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $require_ready_knowledge_job_inputs$
BEGIN
    IF NOT public.geno_v2_knowledge_job_inputs_ready(NEW.knowledge_job_id) THEN
        RAISE EXCEPTION 'knowledge job upstream inputs are not succeeded and finalized'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$require_ready_knowledge_job_inputs$;

CREATE FUNCTION geno_v2_read_knowledge_job_input(
    p_job_id uuid, p_worker_id text, p_lease_token uuid
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $read_knowledge_job_input$
DECLARE job_row public.knowledge_pipeline_jobs%ROWTYPE; result_snapshot jsonb;
BEGIN
    SELECT * INTO job_row
    FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = p_job_id;
    IF NOT FOUND OR job_row.status NOT IN ('running','finalizing')
       OR job_row.cancel_requested_at IS NOT NULL
       OR job_row.lease_owner <> btrim(p_worker_id)
       OR job_row.lease_token <> p_lease_token
       OR job_row.lease_expires_at <= statement_timestamp() THEN
        RAISE EXCEPTION 'knowledge job input lease is lost' USING ERRCODE = '55000';
    END IF;
    SELECT input_snapshot.snapshot INTO result_snapshot
    FROM public.knowledge_job_input_snapshots AS input_snapshot
    WHERE input_snapshot.knowledge_job_id = job_row.id
      AND input_snapshot.project_id = job_row.project_id
      AND input_snapshot.snapshot_hash = job_row.input_hash;
    IF NOT FOUND OR NOT public.geno_v2_knowledge_job_inputs_ready(job_row.id) THEN
        RAISE EXCEPTION 'knowledge job input snapshot is missing or no longer eligible'
            USING ERRCODE = '55000';
    END IF;
    RETURN jsonb_build_object(
        'job_id', job_row.id,
        'project_id', job_row.project_id,
        'job_type', job_row.job_type,
        'input_hash', job_row.input_hash,
        'attempt_count', job_row.attempt_count,
        'snapshot', result_snapshot
    );
END;
$read_knowledge_job_input$;

CREATE CONSTRAINT TRIGGER knowledge_parse_input_ready
AFTER INSERT ON knowledge_parse_job_inputs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_require_ready_knowledge_job_inputs();
CREATE CONSTRAINT TRIGGER knowledge_chunk_input_ready
AFTER INSERT ON knowledge_chunk_job_inputs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_require_ready_knowledge_job_inputs();
CREATE CONSTRAINT TRIGGER knowledge_chunk_set_input_ready
AFTER INSERT ON knowledge_chunk_set_job_inputs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_require_ready_knowledge_job_inputs();

CREATE FUNCTION geno_v2_persist_knowledge_job_result(
    p_job knowledge_pipeline_jobs,
    p_result jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $persist_knowledge_result$
DECLARE
    item jsonb;
    source_row jsonb;
    parser_row jsonb;
    locked_source public.knowledge_import_sources%ROWTYPE;
    output_artifact public.evidence_assets%ROWTYPE;
    resolved_artifact_id uuid;
    requested_artifact_id uuid;
    artifact_resolution jsonb := '{}'::jsonb;
    next_revision_number integer;
    next_governance_version integer;
    actor_id text := p_job.lease_owner;
BEGIN
    IF jsonb_typeof(p_result) <> 'object' THEN
        RAISE EXCEPTION 'knowledge result must be a JSON object' USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(coalesce(p_result->'artifacts', '[]'::jsonb)) = 0 THEN
        RAISE EXCEPTION 'knowledge jobs require an attempt-scoped output artifact'
            USING ERRCODE = '22023';
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'artifacts', '[]'::jsonb))
    LOOP
        requested_artifact_id := (item->>'id')::uuid;
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(jsonb_build_array(
                p_job.project_id::text, item->>'content_hash', item->>'asset_type'
            )::text, 1)
        );
        SELECT * INTO output_artifact
        FROM public.evidence_assets AS artifact
        WHERE artifact.project_id = p_job.project_id
          AND artifact.content_hash = item->>'content_hash'
          AND artifact.asset_type = item->>'asset_type';
        IF FOUND THEN
            IF output_artifact.artifact_status = 'failed' THEN
                RAISE EXCEPTION 'failed content-addressed knowledge artifact cannot be reused'
                    USING ERRCODE = '55000';
            END IF;
            IF output_artifact.tenant_id <> p_job.tenant_id
               OR output_artifact.size_bytes <> (item->>'size_bytes')::bigint
               OR output_artifact.content_type <> item->>'content_type'
               OR output_artifact.access_policy <> 'knowledge-internal'
               OR output_artifact.retention_policy <> 'knowledge-source-v2'
               OR output_artifact.source_kind <> 'knowledge_' || p_job.job_type THEN
                RAISE EXCEPTION 'content-addressed knowledge artifact metadata conflicts'
                    USING ERRCODE = '23514';
            END IF;
            IF output_artifact.artifact_status = 'pending' AND NOT EXISTS (
                SELECT 1 FROM public.artifact_finalize_outbox AS outbox_row
                WHERE outbox_row.evidence_asset_id = output_artifact.id
                  AND outbox_row.project_id = output_artifact.project_id
                  AND outbox_row.expected_content_hash = output_artifact.content_hash
                  AND outbox_row.status IN ('queued','running')
            ) THEN
                RAISE EXCEPTION 'pending content-addressed artifact has no active finalizer'
                    USING ERRCODE = '55000';
            END IF;
            resolved_artifact_id := output_artifact.id;
        ELSE
            resolved_artifact_id := requested_artifact_id;
            INSERT INTO public.evidence_assets (
                id, tenant_id, project_id, asset_type, storage_uri, storage_key,
                content_hash, size_bytes, content_type, access_policy,
                retention_policy, source_kind, artifact_status, created_by
            ) VALUES (
                resolved_artifact_id, p_job.tenant_id, p_job.project_id,
                item->>'asset_type', item->>'storage_uri', item->>'storage_key',
                item->>'content_hash', (item->>'size_bytes')::bigint,
                item->>'content_type', 'knowledge-internal', 'knowledge-source-v2',
                'knowledge_' || p_job.job_type, 'pending', actor_id
            );
            INSERT INTO public.artifact_finalize_outbox (
                id, tenant_id, project_id, evidence_asset_id, expected_content_hash
            ) VALUES (
                (item->>'outbox_id')::uuid, p_job.tenant_id, p_job.project_id,
                resolved_artifact_id, item->>'content_hash'
            );
        END IF;
        artifact_resolution := jsonb_set(
            artifact_resolution, ARRAY[requested_artifact_id::text],
            to_jsonb(resolved_artifact_id::text), true
        );
        INSERT INTO public.knowledge_job_artifacts (
            id, tenant_id, project_id, knowledge_job_id,
            evidence_asset_id, artifact_role
        ) VALUES (
            (item->>'job_artifact_id')::uuid, p_job.tenant_id, p_job.project_id,
            p_job.id, resolved_artifact_id, item->>'artifact_role'
        );
    END LOOP;
    IF NOT EXISTS (
        SELECT 1 FROM public.knowledge_job_artifacts AS artifact
        WHERE artifact.knowledge_job_id = p_job.id
          AND artifact.project_id = p_job.project_id
          AND artifact.artifact_role = CASE p_job.job_type
              WHEN 'import' THEN 'source_snapshot'
              WHEN 'crawl' THEN 'source_snapshot'
              WHEN 'parse' THEN 'parser_output'
              WHEN 'chunk' THEN 'chunk_manifest'
              WHEN 'embed' THEN 'embedding_manifest'
              WHEN 'fact_extract' THEN 'raw_model_output' END
    ) THEN
        RAISE EXCEPTION 'knowledge result is missing its required output artifact role'
            USING ERRCODE = '22023';
    END IF;

    IF p_job.job_type IN ('import', 'crawl') THEN
        source_row := p_result->'source_asset';
        IF source_row IS NULL OR jsonb_typeof(source_row) <> 'object' THEN
            RAISE EXCEPTION '% result requires source_asset', p_job.job_type
                USING ERRCODE = '22023';
        END IF;
        SELECT * INTO locked_source
        FROM public.knowledge_import_sources AS source_input
        WHERE source_input.id = p_job.import_source_id
          AND source_input.project_id = p_job.project_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'knowledge import source snapshot is missing'
                USING ERRCODE = '23503';
        END IF;
        IF (source_row->>'id')::uuid <> locked_source.target_source_asset_id THEN
            RAISE EXCEPTION 'source result asset is outside the frozen target input'
                USING ERRCODE = '23514';
        END IF;
        SELECT artifact.* INTO output_artifact
        FROM public.knowledge_job_artifacts AS link
        JOIN public.evidence_assets AS artifact
          ON artifact.id = link.evidence_asset_id
         AND artifact.project_id = link.project_id
        WHERE link.knowledge_job_id = p_job.id
          AND link.project_id = p_job.project_id
          AND link.artifact_role = 'source_snapshot';
        IF NOT FOUND THEN
            RAISE EXCEPTION 'source snapshot output artifact is missing'
                USING ERRCODE = '23503';
        END IF;
        INSERT INTO public.knowledge_source_assets (
            id, tenant_id, project_id, asset_kind, status, title, created_by
        ) VALUES (
            locked_source.target_source_asset_id, p_job.tenant_id, p_job.project_id,
            CASE locked_source.source_mode
                WHEN 'file' THEN 'file' WHEN 'csv' THEN 'csv'
                WHEN 'url' THEN 'web_page' WHEN 'site' THEN 'web_page'
                ELSE 'pasted_text' END,
            'active', locked_source.source_label, actor_id
        ) ON CONFLICT (id) DO NOTHING;
        PERFORM 1 FROM public.knowledge_source_assets AS source_asset
        WHERE source_asset.id = locked_source.target_source_asset_id
          AND source_asset.project_id = p_job.project_id
          AND source_asset.status = 'active'
        FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'source target is unavailable or belongs to another project'
                USING ERRCODE = '23503';
        END IF;
        SELECT coalesce(max(revision.revision_number), 0) + 1
        INTO next_revision_number
        FROM public.knowledge_source_asset_revisions AS revision
        WHERE revision.source_asset_id = locked_source.target_source_asset_id
          AND revision.project_id = p_job.project_id;
        SELECT coalesce(max(governance.governance_version), 0) + 1
        INTO next_governance_version
        FROM public.knowledge_source_governance_versions AS governance
        WHERE governance.source_asset_id = locked_source.target_source_asset_id
          AND governance.project_id = p_job.project_id;
        INSERT INTO public.knowledge_source_asset_revisions (
            id, tenant_id, project_id, knowledge_job_id, source_asset_id, revision_number,
            source_content_hash, source_uri, canonical_source_url, mime_type,
            byte_size, status, created_by
        ) VALUES (
            (source_row->>'revision_id')::uuid, p_job.tenant_id, p_job.project_id,
            p_job.id, locked_source.target_source_asset_id, next_revision_number,
            output_artifact.content_hash, output_artifact.storage_uri,
            locked_source.source_url, output_artifact.content_type,
            output_artifact.size_bytes, 'active', actor_id
        );
        INSERT INTO public.knowledge_source_governance_versions (
            id, tenant_id, project_id, source_asset_id, source_revision_id,
            governance_version, authority_grade, usage_rights_status,
            authorization_basis, authorised_by, authorised_at,
            confidentiality, consent_status, consent_expires_at,
            external_model_use_allowed,
            public_adaptation_allowed, customer_visible, public_disclosure_allowed,
            public_source_url, public_source_title, citation_label,
            quotation_allowed, attribution_required, claim_risk, policy_version,
            governance_hash, valid_from, valid_until, created_by
        ) VALUES (
            (source_row->>'governance_id')::uuid, p_job.tenant_id, p_job.project_id,
            locked_source.target_source_asset_id, (source_row->>'revision_id')::uuid,
            next_governance_version,
            locked_source.authority_grade, locked_source.usage_rights_status,
            locked_source.authorization_basis, locked_source.authorised_by,
            locked_source.authorised_at, locked_source.confidentiality,
            locked_source.consent_status, locked_source.consent_expires_at,
            locked_source.external_model_use_allowed,
            locked_source.public_adaptation_allowed, locked_source.customer_visible,
            locked_source.public_disclosure_allowed, locked_source.public_source_url,
            locked_source.public_source_title, locked_source.citation_label,
            locked_source.quotation_allowed, locked_source.attribution_required,
            locked_source.claim_risk, locked_source.policy_version,
            locked_source.governance_hash, locked_source.valid_from,
            locked_source.valid_until, actor_id
        );
        UPDATE public.knowledge_source_assets
        SET current_revision_id = (source_row->>'revision_id')::uuid,
            current_governance_version_id = (source_row->>'governance_id')::uuid,
            updated_at = statement_timestamp()
        WHERE id = locked_source.target_source_asset_id AND project_id = p_job.project_id;

        INSERT INTO public.knowledge_source_channels (
            id, tenant_id, project_id, source_revision_id, channel_kind, channel_key
        ) VALUES (
            gen_random_uuid(), p_job.tenant_id, p_job.project_id,
            (source_row->>'revision_id')::uuid,
            CASE locked_source.source_mode
                WHEN 'url' THEN 'website' WHEN 'site' THEN 'website'
                WHEN 'file' THEN 'upload' WHEN 'csv' THEN 'upload' ELSE 'internal' END,
            coalesce(locked_source.source_url, locked_source.source_label)
        );
        FOR item IN
            SELECT jsonb_build_object(
                'id', gen_random_uuid(),
                'publication_channel', locked_channel.publication_channel,
                'allowed', locked_channel.allowed
            )
            FROM public.knowledge_import_source_channels AS locked_channel
            WHERE locked_channel.import_source_id = locked_source.id
              AND locked_channel.project_id = locked_source.project_id
        LOOP
            INSERT INTO public.knowledge_source_governance_channels (
                id, tenant_id, project_id, governance_version_id,
                publication_channel, allowed
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (source_row->>'governance_id')::uuid,
                item->>'publication_channel',
                coalesce((item->>'allowed')::boolean, false)
            );
        END LOOP;
        FOR item IN
            SELECT jsonb_build_object(
                'id', gen_random_uuid(),
                'subject_entity_id', locked_subject.subject_entity_id,
                'subject_role', locked_subject.subject_role
            )
            FROM public.knowledge_import_source_subjects AS locked_subject
            WHERE locked_subject.import_source_id = locked_source.id
              AND locked_subject.project_id = locked_source.project_id
        LOOP
            INSERT INTO public.knowledge_source_subjects (
                id, tenant_id, project_id, source_revision_id,
                subject_entity_id, subject_role
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (source_row->>'revision_id')::uuid,
                (item->>'subject_entity_id')::uuid, item->>'subject_role'
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'source_artifact_links', '[]'::jsonb))
        LOOP
            requested_artifact_id := (item->>'evidence_asset_id')::uuid;
            resolved_artifact_id := (artifact_resolution->>requested_artifact_id::text)::uuid;
            IF resolved_artifact_id IS NULL THEN
                RAISE EXCEPTION 'source artifact request was not declared by this job'
                    USING ERRCODE = '23514';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.knowledge_job_artifacts AS job_artifact
                WHERE job_artifact.knowledge_job_id = p_job.id
                  AND job_artifact.project_id = p_job.project_id
                  AND job_artifact.evidence_asset_id = resolved_artifact_id
            ) THEN
                RAISE EXCEPTION 'source artifact is not an output of this knowledge job'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_source_revision_artifacts (
                id, tenant_id, project_id, source_revision_id,
                evidence_asset_id, artifact_role
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (source_row->>'revision_id')::uuid,
                resolved_artifact_id, item->>'artifact_role'
            );
        END LOOP;
        IF (
            SELECT count(*)
            FROM public.knowledge_source_revision_artifacts AS link
            WHERE link.source_revision_id = (source_row->>'revision_id')::uuid
              AND link.project_id = p_job.project_id
              AND link.evidence_asset_id = output_artifact.id
        ) <> 1 THEN
            RAISE EXCEPTION 'source snapshot must be linked exactly once to its source revision'
                USING ERRCODE = '23514';
        END IF;
    ELSIF p_job.job_type = 'parse' THEN
        parser_row := p_result->'parser_run';
        IF parser_row IS NULL OR jsonb_typeof(parser_row) <> 'object' THEN
            RAISE EXCEPTION 'parse result requires parser_run' USING ERRCODE = '22023';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.knowledge_parse_job_inputs AS input_row
            WHERE input_row.knowledge_job_id = p_job.id
              AND input_row.project_id = p_job.project_id
              AND input_row.source_revision_id = (parser_row->>'source_revision_id')::uuid
        ) THEN
            RAISE EXCEPTION 'parser source revision is outside the frozen job input'
                USING ERRCODE = '23514';
        END IF;
        INSERT INTO public.knowledge_parser_runs (
            id, tenant_id, project_id, knowledge_job_id, source_revision_id,
            parser_engine, parser_version, status, result_hash
        ) VALUES (
            (parser_row->>'id')::uuid, p_job.tenant_id, p_job.project_id, p_job.id,
            (parser_row->>'source_revision_id')::uuid, parser_row->>'parser_engine',
            parser_row->>'parser_version', 'succeeded', parser_row->>'result_hash'
        );
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'parser_artifact_links', '[]'::jsonb))
        LOOP
            requested_artifact_id := (item->>'evidence_asset_id')::uuid;
            resolved_artifact_id := (artifact_resolution->>requested_artifact_id::text)::uuid;
            IF resolved_artifact_id IS NULL THEN
                RAISE EXCEPTION 'parser artifact request was not declared by this job'
                    USING ERRCODE = '23514';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM public.knowledge_job_artifacts AS job_artifact
                WHERE job_artifact.knowledge_job_id = p_job.id
                  AND job_artifact.project_id = p_job.project_id
                  AND job_artifact.evidence_asset_id = resolved_artifact_id
            ) THEN
                RAISE EXCEPTION 'parser artifact is not an output of this knowledge job'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_parser_artifacts (
                id, tenant_id, project_id, parser_run_id, evidence_asset_id, artifact_role
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (parser_row->>'id')::uuid, resolved_artifact_id,
                item->>'artifact_role'
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'blocks', '[]'::jsonb))
        LOOP
            INSERT INTO public.knowledge_blocks (
                id, tenant_id, project_id, parser_run_id, source_revision_id,
                page_number, block_index, block_kind, text_content, content_hash
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (parser_row->>'id')::uuid, (parser_row->>'source_revision_id')::uuid,
                (item->>'page_number')::integer, (item->>'block_index')::integer,
                item->>'block_kind', item->>'text_content', item->>'content_hash'
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'tables', '[]'::jsonb))
        LOOP
            INSERT INTO public.knowledge_tables (
                id, tenant_id, project_id, parser_run_id, source_revision_id,
                page_number, table_index, caption, table_data, content_hash
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (parser_row->>'id')::uuid, (parser_row->>'source_revision_id')::uuid,
                (item->>'page_number')::integer, (item->>'table_index')::integer,
                nullif(item->>'caption',''), item->'table_data', item->>'content_hash'
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'ocr_spans', '[]'::jsonb))
        LOOP
            INSERT INTO public.knowledge_ocr_spans (
                id, tenant_id, project_id, parser_run_id, source_revision_id,
                page_number, span_index, text_content, confidence, locator
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (parser_row->>'id')::uuid, (parser_row->>'source_revision_id')::uuid,
                (item->>'page_number')::integer, (item->>'span_index')::integer,
                item->>'text_content', (item->>'confidence')::numeric, item->'locator'
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'pages', '[]'::jsonb))
        LOOP
            IF item->>'image_evidence_asset_id' IS NOT NULL THEN
                requested_artifact_id := (item->>'image_evidence_asset_id')::uuid;
                resolved_artifact_id :=
                    (artifact_resolution->>requested_artifact_id::text)::uuid;
            ELSE
                resolved_artifact_id := NULL;
            END IF;
            IF item->>'image_evidence_asset_id' IS NOT NULL
               AND (resolved_artifact_id IS NULL OR NOT EXISTS (
                SELECT 1 FROM public.knowledge_job_artifacts AS job_artifact
                WHERE job_artifact.knowledge_job_id = p_job.id
                  AND job_artifact.project_id = p_job.project_id
                  AND job_artifact.evidence_asset_id =
                      resolved_artifact_id
            )) THEN
                RAISE EXCEPTION 'page image is not an output of this knowledge job'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_pages (
                id, tenant_id, project_id, parser_run_id, source_revision_id,
                page_number, text_hash, image_evidence_asset_id
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (parser_row->>'id')::uuid, (parser_row->>'source_revision_id')::uuid,
                (item->>'page_number')::integer, item->>'text_hash',
                resolved_artifact_id
            );
        END LOOP;
    ELSIF p_job.job_type = 'chunk' THEN
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'chunks', '[]'::jsonb))
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM public.knowledge_chunk_job_inputs AS input_row
                WHERE input_row.knowledge_job_id = p_job.id
                  AND input_row.project_id = p_job.project_id
                  AND input_row.source_revision_id = (item->>'source_revision_id')::uuid
            ) THEN
                RAISE EXCEPTION 'chunk output source revision is outside the frozen job input'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_chunks (
                id, tenant_id, project_id, knowledge_job_id, source_revision_id,
                chunk_index, chunk_kind, text_content, token_count,
                content_hash, locale, status
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id, p_job.id,
                (item->>'source_revision_id')::uuid, (item->>'chunk_index')::integer,
                item->>'chunk_kind', item->>'text_content',
                (item->>'token_count')::integer, item->>'content_hash',
                item->>'locale', 'active'
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'chunk_blocks', '[]'::jsonb))
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM public.knowledge_chunks AS chunk_row
                JOIN public.knowledge_blocks AS block_row
                  ON block_row.source_revision_id = chunk_row.source_revision_id
                 AND block_row.project_id = chunk_row.project_id
                JOIN public.knowledge_chunk_job_inputs AS input_row
                  ON input_row.parser_run_id = block_row.parser_run_id
                 AND input_row.source_revision_id = block_row.source_revision_id
                 AND input_row.project_id = block_row.project_id
                WHERE input_row.knowledge_job_id = p_job.id
                  AND input_row.project_id = p_job.project_id
                  AND chunk_row.id = (item->>'chunk_id')::uuid
                  AND chunk_row.knowledge_job_id = p_job.id
                  AND block_row.id = (item->>'block_id')::uuid
            ) THEN
                RAISE EXCEPTION 'chunk block is outside the frozen parser input'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_chunk_blocks (
                id, tenant_id, project_id, chunk_id, block_id, ordinal
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (item->>'chunk_id')::uuid, (item->>'block_id')::uuid,
                (item->>'ordinal')::integer
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'chunk_tables', '[]'::jsonb))
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM public.knowledge_chunks AS chunk_row
                JOIN public.knowledge_tables AS table_row
                  ON table_row.source_revision_id = chunk_row.source_revision_id
                 AND table_row.project_id = chunk_row.project_id
                JOIN public.knowledge_chunk_job_inputs AS input_row
                  ON input_row.parser_run_id = table_row.parser_run_id
                 AND input_row.source_revision_id = table_row.source_revision_id
                 AND input_row.project_id = table_row.project_id
                WHERE input_row.knowledge_job_id = p_job.id
                  AND input_row.project_id = p_job.project_id
                  AND chunk_row.id = (item->>'chunk_id')::uuid
                  AND chunk_row.knowledge_job_id = p_job.id
                  AND table_row.id = (item->>'table_id')::uuid
            ) THEN
                RAISE EXCEPTION 'chunk table is outside the frozen parser input'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_chunk_tables (
                id, tenant_id, project_id, chunk_id, table_id, ordinal
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (item->>'chunk_id')::uuid, (item->>'table_id')::uuid,
                (item->>'ordinal')::integer
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'chunk_subjects', '[]'::jsonb))
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM public.knowledge_chunks AS chunk_row
                WHERE chunk_row.id = (item->>'chunk_id')::uuid
                  AND chunk_row.project_id = p_job.project_id
                  AND chunk_row.knowledge_job_id = p_job.id
            ) THEN
                RAISE EXCEPTION 'chunk subject parent is outside the current job output'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_chunk_subjects (
                id, tenant_id, project_id, chunk_id, subject_entity_id, subject_role
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (item->>'chunk_id')::uuid, (item->>'subject_entity_id')::uuid,
                item->>'subject_role'
            );
        END LOOP;
    ELSIF p_job.job_type = 'embed' THEN
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'embeddings', '[]'::jsonb))
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM public.knowledge_chunk_set_job_inputs AS input_row
                WHERE input_row.knowledge_job_id = p_job.id
                  AND input_row.project_id = p_job.project_id
                  AND input_row.input_kind = 'embed'
                  AND input_row.chunk_id = (item->>'chunk_id')::uuid
            ) THEN
                RAISE EXCEPTION 'embedding chunk is outside the frozen job input'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_chunk_embeddings (
                id, tenant_id, project_id, knowledge_job_id, chunk_id,
                model_key, model_version, vector_store_key, vector_point_id, embedding_hash
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id, p_job.id,
                (item->>'chunk_id')::uuid, item->>'model_key', item->>'model_version',
                item->>'vector_store_key', item->>'vector_point_id', item->>'embedding_hash'
            );
        END LOOP;
    ELSIF p_job.job_type = 'fact_extract' THEN
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'fact_candidates', '[]'::jsonb))
        LOOP
            INSERT INTO public.knowledge_fact_candidates (
                id, tenant_id, project_id, knowledge_job_id, subject_entity_id,
                subject_role, fact_type, statement, locale, confidence,
                status, submitted_for_review_by
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id, p_job.id,
                (item->>'subject_entity_id')::uuid, item->>'subject_role',
                item->>'fact_type', item->>'statement', item->>'locale',
                (item->>'confidence')::numeric, 'pending_review', actor_id
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'candidate_sources', '[]'::jsonb))
        LOOP
            IF item->>'chunk_id' IS NULL OR NOT EXISTS (
                SELECT 1 FROM public.knowledge_chunk_set_job_inputs AS input_row
                JOIN public.knowledge_chunks AS chunk_row
                  ON chunk_row.id = input_row.chunk_id
                 AND chunk_row.project_id = input_row.project_id
                JOIN public.knowledge_fact_candidates AS candidate
                  ON candidate.id = (item->>'fact_candidate_id')::uuid
                 AND candidate.project_id = input_row.project_id
                WHERE input_row.knowledge_job_id = p_job.id
                  AND input_row.project_id = p_job.project_id
                  AND input_row.input_kind = 'fact_extract'
                  AND input_row.chunk_id = (item->>'chunk_id')::uuid
                  AND candidate.knowledge_job_id = p_job.id
                  AND candidate.status = 'pending_review'
                  AND item->>'source_snapshot_hash' = chunk_row.content_hash
            ) THEN
                RAISE EXCEPTION 'fact source must be an authenticated frozen input chunk of the current candidate'
                    USING ERRCODE = '23514';
            END IF;
            INSERT INTO public.knowledge_fact_candidate_sources (
                id, tenant_id, project_id, fact_candidate_id, chunk_id,
                block_id, table_id, source_revision_id, locator, source_snapshot_hash
            ) VALUES (
                (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
                (item->>'fact_candidate_id')::uuid, (item->>'chunk_id')::uuid,
                (item->>'block_id')::uuid, (item->>'table_id')::uuid,
                (item->>'source_revision_id')::uuid,
                coalesce(item->'locator', '{}'::jsonb), item->>'source_snapshot_hash'
            );
        END LOOP;
    ELSE
        RAISE EXCEPTION 'unsupported knowledge job result type'
            USING ERRCODE = '22023';
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'quality_runs', '[]'::jsonb))
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM public.knowledge_job_quality_definitions AS frozen
            JOIN public.knowledge_quality_definitions AS definition
              ON definition.id = frozen.quality_definition_id
             AND definition.project_id = frozen.project_id
            WHERE frozen.knowledge_job_id = p_job.id
              AND frozen.project_id = p_job.project_id
              AND frozen.quality_definition_id = (item->>'quality_definition_id')::uuid
              AND definition.job_type = p_job.job_type
              AND definition.target_kind = item->>'target_kind'
        ) THEN
            RAISE EXCEPTION 'quality definition is outside the frozen job input'
                USING ERRCODE = '23514';
        END IF;
        IF NOT (
            (item->>'target_kind' = 'source_revision' AND EXISTS (
                SELECT 1 FROM public.knowledge_source_asset_revisions AS revision
                WHERE revision.id = (item->>'source_revision_id')::uuid
                  AND revision.project_id = p_job.project_id
                  AND (revision.knowledge_job_id = p_job.id OR EXISTS (
                      SELECT 1 FROM public.knowledge_parse_job_inputs AS input_row
                      WHERE input_row.knowledge_job_id = p_job.id
                        AND input_row.project_id = p_job.project_id
                        AND input_row.source_revision_id = revision.id))))
            OR (item->>'target_kind' = 'parser_run' AND EXISTS (
                SELECT 1 FROM public.knowledge_parser_runs AS parser_run
                WHERE parser_run.id = (item->>'parser_run_id')::uuid
                  AND parser_run.project_id = p_job.project_id
                  AND (parser_run.knowledge_job_id = p_job.id OR EXISTS (
                      SELECT 1 FROM public.knowledge_chunk_job_inputs AS input_row
                      WHERE input_row.knowledge_job_id = p_job.id
                        AND input_row.project_id = p_job.project_id
                        AND input_row.parser_run_id = parser_run.id))))
            OR (item->>'target_kind' = 'chunk' AND EXISTS (
                SELECT 1 FROM public.knowledge_chunks AS chunk_row
                WHERE chunk_row.id = (item->>'chunk_id')::uuid
                  AND chunk_row.project_id = p_job.project_id
                  AND (chunk_row.knowledge_job_id = p_job.id OR EXISTS (
                      SELECT 1 FROM public.knowledge_chunk_set_job_inputs AS input_row
                      WHERE input_row.knowledge_job_id = p_job.id
                        AND input_row.project_id = p_job.project_id
                        AND input_row.chunk_id = chunk_row.id))))
            OR (item->>'target_kind' = 'fact_candidate' AND EXISTS (
                SELECT 1 FROM public.knowledge_fact_candidates AS candidate
                WHERE candidate.id = (item->>'fact_candidate_id')::uuid
                  AND candidate.project_id = p_job.project_id
                  AND candidate.knowledge_job_id = p_job.id))
        ) THEN
            RAISE EXCEPTION 'quality target is outside the frozen job input or output'
                USING ERRCODE = '23514';
        END IF;
        INSERT INTO public.knowledge_quality_runs (
            id, tenant_id, project_id, knowledge_job_id, quality_definition_id,
            target_kind, source_revision_id, parser_run_id, chunk_id,
            fact_candidate_id, status, result_hash
        ) VALUES (
            (item->>'id')::uuid, p_job.tenant_id, p_job.project_id, p_job.id,
            (item->>'quality_definition_id')::uuid, item->>'target_kind',
            (item->>'source_revision_id')::uuid, (item->>'parser_run_id')::uuid,
            (item->>'chunk_id')::uuid, (item->>'fact_candidate_id')::uuid,
            item->>'status', item->>'result_hash'
        );
    END LOOP;
    FOR item IN SELECT value FROM jsonb_array_elements(coalesce(p_result->'quality_findings', '[]'::jsonb))
    LOOP
        INSERT INTO public.knowledge_quality_findings (
            id, tenant_id, project_id, quality_run_id, finding_code,
            severity, message, finding_hash
        )
        SELECT (item->>'id')::uuid, p_job.tenant_id, p_job.project_id,
               quality_run.id, item->>'finding_code',
               definition.severity_on_failure, item->>'message', item->>'finding_hash'
        FROM public.knowledge_quality_runs AS quality_run
        JOIN public.knowledge_quality_definitions AS definition
          ON definition.id = quality_run.quality_definition_id
         AND definition.project_id = quality_run.project_id
        WHERE quality_run.id = (item->>'quality_run_id')::uuid
          AND quality_run.knowledge_job_id = p_job.id
          AND quality_run.project_id = p_job.project_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'quality finding parent is outside the current job output'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT 1 FROM public.knowledge_quality_runs AS quality_run
        WHERE quality_run.knowledge_job_id = p_job.id
          AND quality_run.project_id = p_job.project_id
          AND (
              (quality_run.status = 'passed' AND EXISTS (
                  SELECT 1 FROM public.knowledge_quality_findings AS finding
                  WHERE finding.quality_run_id = quality_run.id
                    AND finding.project_id = quality_run.project_id
              ))
              OR (quality_run.status = 'failed' AND NOT EXISTS (
                  SELECT 1 FROM public.knowledge_quality_findings AS finding
                  WHERE finding.quality_run_id = quality_run.id
                    AND finding.project_id = quality_run.project_id
              ))
          )
    ) THEN
        RAISE EXCEPTION 'passed quality runs must have no findings and failed runs require findings'
            USING ERRCODE = '23514';
    END IF;
END;
$persist_knowledge_result$;

CREATE FUNCTION geno_v2_claim_knowledge_job(
    p_worker_id text,
    p_lease_seconds integer,
    p_project_id uuid DEFAULT NULL,
    p_job_type text DEFAULT NULL
)
RETURNS SETOF knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $claim_knowledge_job$
DECLARE affected_run_id uuid;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = ''
       OR p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600
       OR (p_job_type IS NOT NULL AND p_job_type NOT IN
            ('import','crawl','parse','chunk','embed','fact_extract')) THEN
        RAISE EXCEPTION 'knowledge claim arguments are invalid' USING ERRCODE = '22023';
    END IF;

    UPDATE public.knowledge_pipeline_jobs AS job
    SET status = 'failed', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, heartbeat_at = NULL,
        finalizing_result_hash = NULL,
        completed_at = statement_timestamp(), completed_by = 'artifact-finalizer',
        last_error_code = 'artifact_finalize_failed',
        last_error_message = 'required knowledge artifact failed finalization',
        updated_at = statement_timestamp()
    WHERE job.status IN ('queued','finalizing')
      AND (p_project_id IS NULL OR job.project_id = p_project_id)
      AND (p_job_type IS NULL OR job.job_type = p_job_type)
      AND (
          EXISTS (
              SELECT 1 FROM public.knowledge_job_artifacts AS link
              JOIN public.evidence_assets AS artifact
                ON artifact.id = link.evidence_asset_id
               AND artifact.project_id = link.project_id
              WHERE link.knowledge_job_id = job.id
                AND link.project_id = job.project_id
                AND artifact.artifact_status = 'failed'
          )
          OR EXISTS (
              SELECT 1 FROM public.knowledge_import_sources AS source_input
              JOIN public.evidence_assets AS artifact
                ON artifact.id = source_input.upload_evidence_asset_id
               AND artifact.project_id = source_input.project_id
              WHERE source_input.id = job.import_source_id
                AND source_input.project_id = job.project_id
                AND artifact.artifact_status = 'failed'
          )
      );
    FOR affected_run_id IN
        SELECT DISTINCT job.pipeline_run_id
        FROM public.knowledge_pipeline_jobs AS job
        WHERE job.completed_by = 'artifact-finalizer'
          AND job.status = 'failed'
          AND (p_project_id IS NULL OR job.project_id = p_project_id)
          AND (p_job_type IS NULL OR job.job_type = p_job_type)
    LOOP
        PERFORM public.geno_v2_refresh_knowledge_pipeline_state(affected_run_id);
    END LOOP;

    UPDATE public.knowledge_pipeline_jobs AS job
    SET status = 'cancelled', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, heartbeat_at = NULL,
        finalizing_result_hash = NULL,
        completed_at = statement_timestamp(), completed_by = 'lease-recovery',
        updated_at = statement_timestamp()
    WHERE job.status IN ('running','finalizing')
      AND job.lease_expires_at <= statement_timestamp()
      AND job.cancel_requested_at IS NOT NULL
      AND (p_project_id IS NULL OR job.project_id = p_project_id)
      AND (p_job_type IS NULL OR job.job_type = p_job_type);

    UPDATE public.knowledge_pipeline_jobs AS job
    SET status = 'dead_lettered', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = 'lease-recovery',
        last_error_code = 'attempts_exhausted',
        last_error_message = 'running lease expired after model-call attempt budget',
        updated_at = statement_timestamp()
    WHERE job.status = 'running' AND job.lease_expires_at <= statement_timestamp()
      AND job.attempt_count >= job.max_attempts
      AND job.cancel_requested_at IS NULL
      AND (p_project_id IS NULL OR job.project_id = p_project_id)
      AND (p_job_type IS NULL OR job.job_type = p_job_type);

    RETURN QUERY
    WITH candidate AS (
        SELECT job.id, job.status AS prior_status
        FROM public.knowledge_pipeline_jobs AS job
        WHERE (
            (job.status = 'queued' AND job.next_attempt_at <= statement_timestamp())
            OR (job.status = 'running' AND job.lease_expires_at <= statement_timestamp()
                AND job.attempt_count < job.max_attempts)
            OR (job.status = 'finalizing' AND job.lease_expires_at <= statement_timestamp())
        )
          AND job.cancel_requested_at IS NULL
          AND public.geno_v2_knowledge_job_inputs_ready(job.id)
          AND (
              job.import_source_id IS NULL OR EXISTS (
                  SELECT 1 FROM public.knowledge_import_sources AS source_input
                  JOIN public.evidence_assets AS input_artifact
                    ON input_artifact.id = source_input.upload_evidence_asset_id
                   AND input_artifact.project_id = source_input.project_id
                  WHERE source_input.id = job.import_source_id
                    AND source_input.project_id = job.project_id
                    AND input_artifact.artifact_status = 'finalized'
              )
          )
          AND (p_project_id IS NULL OR job.project_id = p_project_id)
          AND (p_job_type IS NULL OR job.job_type = p_job_type)
          AND NOT EXISTS (
              SELECT 1 FROM public.knowledge_pipeline_job_dependencies AS dependency
              JOIN public.knowledge_pipeline_jobs AS upstream
                ON upstream.id = dependency.depends_on_job_id
               AND upstream.project_id = dependency.project_id
              WHERE dependency.job_id = job.id
                AND dependency.project_id = job.project_id
                AND upstream.status <> 'succeeded'
          )
        ORDER BY (job.status = 'finalizing') DESC, job.priority DESC,
                 job.next_attempt_at, job.created_at, job.id
        FOR UPDATE OF job SKIP LOCKED
        LIMIT 1
    )
    UPDATE public.knowledge_pipeline_jobs AS claimed
    SET status = CASE WHEN candidate.prior_status = 'finalizing'
                      THEN 'finalizing' ELSE 'running' END,
        attempt_count = claimed.attempt_count
            + CASE WHEN candidate.prior_status = 'finalizing' THEN 0 ELSE 1 END,
        lease_owner = btrim(p_worker_id), lease_token = gen_random_uuid(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        heartbeat_at = statement_timestamp(),
        started_at = coalesce(claimed.started_at, statement_timestamp()),
        last_error_code = NULL, last_error_message = NULL,
        updated_at = statement_timestamp()
    FROM candidate
    WHERE claimed.id = candidate.id
    RETURNING claimed.*;
END;
$claim_knowledge_job$;

CREATE FUNCTION geno_v2_heartbeat_knowledge_job(
    p_job_id uuid, p_worker_id text, p_lease_token uuid, p_lease_seconds integer
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $heartbeat_knowledge_job$
DECLARE result_row public.knowledge_pipeline_jobs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'knowledge heartbeat arguments are invalid' USING ERRCODE = '22023';
    END IF;
    UPDATE public.knowledge_pipeline_jobs AS job
    SET lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        heartbeat_at = statement_timestamp(), updated_at = statement_timestamp()
    WHERE job.id = p_job_id AND job.status IN ('running','finalizing')
      AND job.cancel_requested_at IS NULL
      AND job.lease_owner = btrim(p_worker_id) AND job.lease_token = p_lease_token
      AND job.lease_expires_at > statement_timestamp()
    RETURNING job.* INTO result_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'knowledge job lease is lost or cancellation is pending'
            USING ERRCODE = '55000';
    END IF;
    RETURN result_row;
END;
$heartbeat_knowledge_job$;

CREATE FUNCTION geno_v2_begin_finalizing_knowledge_job(
    p_job_id uuid, p_worker_id text, p_lease_token uuid,
    p_result_hash text, p_result jsonb
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $begin_finalizing_knowledge_job$
DECLARE target_row public.knowledge_pipeline_jobs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_result_hash IS NULL OR p_result_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_result) <> 'object' THEN
        RAISE EXCEPTION 'knowledge finalizing arguments are invalid' USING ERRCODE = '22023';
    END IF;
    IF p_result_hash <> encode(public.digest(p_result::text, 'sha256'), 'hex') THEN
        RAISE EXCEPTION 'knowledge result hash does not match canonical payload'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO target_row FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = p_job_id FOR UPDATE;
    IF FOUND AND target_row.status = 'finalizing'
       AND target_row.cancel_requested_at IS NULL
       AND target_row.lease_owner = btrim(p_worker_id)
       AND target_row.lease_token = p_lease_token
       AND target_row.lease_expires_at > statement_timestamp() THEN
        IF target_row.finalizing_result_hash = p_result_hash THEN
            RETURN target_row;
        END IF;
        RAISE EXCEPTION 'knowledge finalizing result hash conflicts with frozen result'
            USING ERRCODE = '23505';
    END IF;
    IF FOUND AND target_row.status = 'succeeded'
       AND target_row.completed_by = btrim(p_worker_id)
       AND target_row.result_hash = p_result_hash THEN
        RETURN target_row;
    END IF;
    IF NOT FOUND OR target_row.status <> 'running'
       OR target_row.cancel_requested_at IS NOT NULL
       OR target_row.lease_owner <> btrim(p_worker_id)
       OR target_row.lease_token <> p_lease_token
       OR target_row.lease_expires_at <= statement_timestamp() THEN
        RAISE EXCEPTION 'knowledge job lease is lost' USING ERRCODE = '55000';
    END IF;
    PERFORM public.geno_v2_persist_knowledge_job_result(target_row, p_result);
    UPDATE public.knowledge_pipeline_jobs AS job
    SET status = 'finalizing', finalizing_result_hash = p_result_hash,
        updated_at = statement_timestamp()
    WHERE job.id = p_job_id RETURNING job.* INTO target_row;
    RETURN target_row;
END;
$begin_finalizing_knowledge_job$;

CREATE FUNCTION geno_v2_knowledge_quality_certificate_complete(p_job_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $knowledge_quality_certificate_complete$
    WITH target_job AS (
        SELECT job.id, job.project_id
        FROM public.knowledge_pipeline_jobs AS job
        WHERE job.id = p_job_id
    ), frozen AS (
        SELECT link.knowledge_job_id, link.project_id,
               definition.id AS definition_id, definition.target_kind
        FROM public.knowledge_job_quality_definitions AS link
        JOIN public.knowledge_quality_definitions AS definition
          ON definition.id = link.quality_definition_id
         AND definition.project_id = link.project_id
        JOIN target_job
          ON target_job.id = link.knowledge_job_id
         AND target_job.project_id = link.project_id
        WHERE definition.required
    ), expected_targets AS (
        SELECT frozen.definition_id, frozen.project_id,
               revision.id AS target_id, 'source_revision'::text AS target_kind
        FROM frozen
        JOIN public.knowledge_source_asset_revisions AS revision
          ON revision.project_id = frozen.project_id
        WHERE frozen.target_kind = 'source_revision'
          AND (
              revision.knowledge_job_id = frozen.knowledge_job_id
              OR EXISTS (
                  SELECT 1 FROM public.knowledge_parse_job_inputs AS input_row
                  WHERE input_row.knowledge_job_id = frozen.knowledge_job_id
                    AND input_row.project_id = frozen.project_id
                    AND input_row.source_revision_id = revision.id
              )
          )
        UNION ALL
        SELECT frozen.definition_id, frozen.project_id,
               parser_run.id, 'parser_run'::text
        FROM frozen
        JOIN public.knowledge_parser_runs AS parser_run
          ON parser_run.project_id = frozen.project_id
        WHERE frozen.target_kind = 'parser_run'
          AND (
              parser_run.knowledge_job_id = frozen.knowledge_job_id
              OR EXISTS (
                  SELECT 1 FROM public.knowledge_chunk_job_inputs AS input_row
                  WHERE input_row.knowledge_job_id = frozen.knowledge_job_id
                    AND input_row.project_id = frozen.project_id
                    AND input_row.parser_run_id = parser_run.id
              )
          )
        UNION ALL
        SELECT frozen.definition_id, frozen.project_id,
               chunk_row.id, 'chunk'::text
        FROM frozen
        JOIN public.knowledge_chunks AS chunk_row
          ON chunk_row.project_id = frozen.project_id
        WHERE frozen.target_kind = 'chunk'
          AND (
              chunk_row.knowledge_job_id = frozen.knowledge_job_id
              OR EXISTS (
                  SELECT 1 FROM public.knowledge_chunk_set_job_inputs AS input_row
                  WHERE input_row.knowledge_job_id = frozen.knowledge_job_id
                    AND input_row.project_id = frozen.project_id
                    AND input_row.chunk_id = chunk_row.id
              )
          )
        UNION ALL
        SELECT frozen.definition_id, frozen.project_id,
               candidate.id, 'fact_candidate'::text
        FROM frozen
        JOIN public.knowledge_fact_candidates AS candidate
          ON candidate.knowledge_job_id = frozen.knowledge_job_id
         AND candidate.project_id = frozen.project_id
        WHERE frozen.target_kind = 'fact_candidate'
    )
    SELECT EXISTS (SELECT 1 FROM frozen)
       AND NOT EXISTS (
           SELECT 1 FROM frozen AS required_definition
           WHERE NOT EXISTS (
               SELECT 1 FROM expected_targets AS expected
               WHERE expected.definition_id = required_definition.definition_id
                 AND expected.project_id = required_definition.project_id
           )
       )
       AND NOT EXISTS (
           SELECT 1
           FROM expected_targets AS expected
           WHERE NOT EXISTS (
               SELECT 1 FROM public.knowledge_quality_runs AS quality_run
               WHERE quality_run.knowledge_job_id = p_job_id
                 AND quality_run.project_id = expected.project_id
                 AND quality_run.quality_definition_id = expected.definition_id
                 AND quality_run.target_kind = expected.target_kind
                 AND coalesce(
                     quality_run.source_revision_id, quality_run.parser_run_id,
                     quality_run.chunk_id, quality_run.fact_candidate_id
                 ) = expected.target_id
           )
       )
       AND NOT EXISTS (
           SELECT 1
           FROM public.knowledge_quality_runs AS quality_run
           JOIN target_job
             ON target_job.id = quality_run.knowledge_job_id
            AND target_job.project_id = quality_run.project_id
           WHERE (quality_run.status = 'passed' AND EXISTS (
                     SELECT 1 FROM public.knowledge_quality_findings AS finding
                     WHERE finding.quality_run_id = quality_run.id
                       AND finding.project_id = quality_run.project_id
                 ))
              OR (quality_run.status = 'failed' AND (
                     NOT EXISTS (
                         SELECT 1 FROM public.knowledge_quality_findings AS finding
                         WHERE finding.quality_run_id = quality_run.id
                           AND finding.project_id = quality_run.project_id
                     )
                     OR EXISTS (
                         SELECT 1 FROM public.knowledge_quality_findings AS finding
                         LEFT JOIN public.knowledge_risk_acceptances AS acceptance
                           ON acceptance.quality_finding_id = finding.id
                          AND acceptance.project_id = finding.project_id
                         WHERE finding.quality_run_id = quality_run.id
                           AND finding.project_id = quality_run.project_id
                           AND (finding.severity = 'hard_block' OR acceptance.id IS NULL)
                     )
                 ))
       );
$knowledge_quality_certificate_complete$;

CREATE FUNCTION geno_v2_refresh_knowledge_pipeline_state(p_pipeline_run_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $refresh_knowledge_pipeline_state$
BEGIN
    UPDATE public.knowledge_pipeline_stages AS stage
    SET status = CASE
            WHEN EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_stage_id = stage.id
                  AND job.project_id = stage.project_id
                  AND job.status IN ('failed','dead_lettered')
            ) THEN 'failed'
            WHEN EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_stage_id = stage.id
                  AND job.project_id = stage.project_id
                  AND job.status = 'cancelled'
            ) AND NOT EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_stage_id = stage.id
                  AND job.project_id = stage.project_id
                  AND job.status <> 'cancelled'
            ) THEN 'cancelled'
            WHEN EXISTS (
                SELECT 1 FROM public.knowledge_fact_candidates AS candidate
                JOIN public.knowledge_pipeline_jobs AS job
                  ON job.id = candidate.knowledge_job_id
                 AND job.project_id = candidate.project_id
                WHERE job.pipeline_stage_id = stage.id
                  AND job.project_id = stage.project_id
                  AND job.status = 'succeeded'
                  AND candidate.status = 'pending_review'
            ) THEN 'waiting_review'
            WHEN EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_stage_id = stage.id
                  AND job.project_id = stage.project_id
            ) AND NOT EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_stage_id = stage.id
                  AND job.project_id = stage.project_id
                  AND job.status <> 'succeeded'
            ) THEN 'succeeded'
            WHEN EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_stage_id = stage.id
                  AND job.project_id = stage.project_id
                  AND job.status IN ('running','finalizing')
            ) THEN 'running'
            ELSE 'queued'
        END,
        updated_at = statement_timestamp()
    WHERE stage.pipeline_run_id = p_pipeline_run_id;

    UPDATE public.knowledge_pipeline_runs AS run
    SET status = CASE
            WHEN EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_run_id = run.id
                  AND job.project_id = run.project_id
                  AND job.status IN ('failed','dead_lettered')
            ) THEN 'failed'
            WHEN EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_stages AS stage
                WHERE stage.pipeline_run_id = run.id
                  AND stage.project_id = run.project_id
                  AND stage.status = 'waiting_review'
            ) THEN 'waiting_review'
            WHEN EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_run_id = run.id
                  AND job.project_id = run.project_id
            ) AND NOT EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_stages AS stage
                WHERE stage.pipeline_run_id = run.id
                  AND stage.project_id = run.project_id
                  AND stage.status <> 'succeeded'
            ) THEN 'succeeded'
            WHEN NOT EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_run_id = run.id
                  AND job.project_id = run.project_id
                  AND job.status <> 'cancelled'
            ) THEN 'cancelled'
            ELSE 'running'
        END,
        started_at = CASE
            WHEN run.started_at IS NULL AND EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_jobs AS job
                WHERE job.pipeline_run_id = run.id
                  AND job.project_id = run.project_id
                  AND job.started_at IS NOT NULL
            ) THEN statement_timestamp() ELSE run.started_at END,
        completed_at = CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM public.knowledge_pipeline_stages AS stage
                WHERE stage.pipeline_run_id = run.id
                  AND stage.project_id = run.project_id
                  AND stage.status NOT IN ('succeeded','failed','cancelled')
            ) THEN coalesce(run.completed_at, statement_timestamp())
            ELSE NULL END,
        updated_at = statement_timestamp()
    WHERE run.id = p_pipeline_run_id;
END;
$refresh_knowledge_pipeline_state$;

CREATE FUNCTION geno_v2_complete_knowledge_job(
    p_job_id uuid, p_worker_id text, p_lease_token uuid
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $complete_knowledge_job$
DECLARE target_row public.knowledge_pipeline_jobs%ROWTYPE;
BEGIN
    SELECT * INTO target_row FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = p_job_id FOR UPDATE;
    IF NOT FOUND OR target_row.status <> 'finalizing'
       OR target_row.cancel_requested_at IS NOT NULL
       OR target_row.lease_owner <> btrim(p_worker_id)
       OR target_row.lease_token <> p_lease_token
       OR target_row.lease_expires_at <= statement_timestamp() THEN
        RAISE EXCEPTION 'knowledge finalizing lease is lost' USING ERRCODE = '55000';
    END IF;
    IF target_row.finalizing_result_hash IS NULL
       OR target_row.finalizing_result_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'result hash does not match the frozen finalizing hash'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.knowledge_job_artifacts AS job_artifact
        JOIN public.evidence_assets AS artifact
          ON artifact.id = job_artifact.evidence_asset_id
         AND artifact.project_id = job_artifact.project_id
        WHERE job_artifact.knowledge_job_id = target_row.id
          AND job_artifact.project_id = target_row.project_id
          AND artifact.artifact_status <> 'finalized'
    ) OR EXISTS (
        SELECT 1 FROM public.knowledge_source_revision_artifacts AS link
        JOIN public.knowledge_source_asset_revisions AS revision
          ON revision.id = link.source_revision_id AND revision.project_id = link.project_id
        JOIN public.knowledge_source_assets AS source_asset
          ON source_asset.id = revision.source_asset_id AND source_asset.project_id = revision.project_id
        JOIN public.evidence_assets AS artifact
          ON artifact.id = link.evidence_asset_id AND artifact.project_id = link.project_id
        WHERE revision.knowledge_job_id = target_row.id
          AND source_asset.project_id = target_row.project_id
          AND artifact.artifact_status <> 'finalized'
    ) OR EXISTS (
        SELECT 1 FROM public.knowledge_parser_artifacts AS link
        JOIN public.knowledge_parser_runs AS parser_run
          ON parser_run.id = link.parser_run_id AND parser_run.project_id = link.project_id
        JOIN public.evidence_assets AS artifact
          ON artifact.id = link.evidence_asset_id AND artifact.project_id = link.project_id
        WHERE parser_run.knowledge_job_id = target_row.id
          AND parser_run.project_id = target_row.project_id
          AND artifact.artifact_status <> 'finalized'
    ) OR EXISTS (
        SELECT 1 FROM public.knowledge_pages AS page_row
        JOIN public.knowledge_parser_runs AS parser_run
          ON parser_run.id = page_row.parser_run_id AND parser_run.project_id = page_row.project_id
        JOIN public.evidence_assets AS artifact
          ON artifact.id = page_row.image_evidence_asset_id AND artifact.project_id = page_row.project_id
        WHERE parser_run.knowledge_job_id = target_row.id
          AND page_row.project_id = target_row.project_id
          AND artifact.artifact_status <> 'finalized'
    ) THEN
        RAISE EXCEPTION 'knowledge job artifacts are not finalized' USING ERRCODE = '55000';
    END IF;
    IF NOT public.geno_v2_knowledge_quality_certificate_complete(target_row.id) THEN
        RAISE EXCEPTION 'required knowledge quality gates are incomplete or blocked'
            USING ERRCODE = '55000';
    END IF;
    UPDATE public.knowledge_pipeline_jobs AS job
    SET status = 'succeeded', result_hash = job.finalizing_result_hash,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL, completed_at = statement_timestamp(),
        completed_by = btrim(p_worker_id), updated_at = statement_timestamp()
    WHERE job.id = target_row.id RETURNING job.* INTO target_row;
    PERFORM public.geno_v2_refresh_knowledge_pipeline_state(target_row.pipeline_run_id);
    RETURN target_row;
END;
$complete_knowledge_job$;

CREATE FUNCTION geno_v2_fail_knowledge_job(
    p_job_id uuid, p_worker_id text, p_lease_token uuid,
    p_error_code text, p_error_message text, p_retryable boolean,
    p_retry_delay_seconds integer DEFAULT 0
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fail_knowledge_job$
DECLARE target_row public.knowledge_pipeline_jobs%ROWTYPE;
BEGIN
    IF p_error_code IS NULL OR btrim(p_error_code) = ''
       OR p_error_message IS NULL OR btrim(p_error_message) = ''
       OR p_retryable IS NULL OR p_retry_delay_seconds < 0
       OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'knowledge failure arguments are invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO target_row FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = p_job_id FOR UPDATE;
    IF NOT FOUND OR target_row.status NOT IN ('running','finalizing')
       OR target_row.lease_owner <> btrim(p_worker_id)
       OR target_row.lease_token <> p_lease_token
       OR target_row.lease_expires_at <= statement_timestamp() THEN
        RAISE EXCEPTION 'knowledge job lease is lost' USING ERRCODE = '55000';
    END IF;
    IF target_row.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'knowledge job cancellation must be acknowledged, not failed'
            USING ERRCODE = '55000';
    END IF;
    IF target_row.status = 'finalizing' AND p_retryable THEN
        RAISE EXCEPTION 'finalizing failures must use artifact retry or terminal failure'
            USING ERRCODE = '55000';
    END IF;
    UPDATE public.knowledge_pipeline_jobs AS job
    SET status = CASE
            WHEN p_retryable AND job.attempt_count < job.max_attempts THEN 'queued'
            WHEN job.attempt_count >= job.max_attempts THEN 'dead_lettered'
            ELSE 'failed' END,
        next_attempt_at = CASE WHEN p_retryable AND job.attempt_count < job.max_attempts
            THEN statement_timestamp() + make_interval(secs => p_retry_delay_seconds)
            ELSE job.next_attempt_at END,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL, finalizing_result_hash = NULL,
        last_error_code = btrim(p_error_code),
        last_error_message = btrim(p_error_message),
        completed_at = CASE WHEN p_retryable AND job.attempt_count < job.max_attempts
                            THEN NULL ELSE statement_timestamp() END,
        completed_by = CASE WHEN p_retryable AND job.attempt_count < job.max_attempts
                            THEN NULL ELSE btrim(p_worker_id) END,
        updated_at = statement_timestamp()
    WHERE job.id = p_job_id RETURNING job.* INTO target_row;
    PERFORM public.geno_v2_refresh_knowledge_pipeline_state(target_row.pipeline_run_id);
    RETURN target_row;
END;
$fail_knowledge_job$;

CREATE FUNCTION geno_v2_ack_knowledge_job_cancel(
    p_job_id uuid, p_worker_id text, p_lease_token uuid
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $ack_knowledge_cancel$
DECLARE target_row public.knowledge_pipeline_jobs%ROWTYPE;
BEGIN
    UPDATE public.knowledge_pipeline_jobs AS job
    SET status = 'cancelled', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, heartbeat_at = NULL,
        finalizing_result_hash = NULL, completed_at = statement_timestamp(),
        completed_by = btrim(p_worker_id), updated_at = statement_timestamp()
    WHERE job.id = p_job_id AND job.status IN ('running','finalizing')
      AND job.cancel_requested_at IS NOT NULL
      AND job.lease_owner = btrim(p_worker_id) AND job.lease_token = p_lease_token
      AND job.lease_expires_at > statement_timestamp()
    RETURNING job.* INTO target_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'knowledge cancellation lease is lost' USING ERRCODE = '55000';
    END IF;
    PERFORM public.geno_v2_refresh_knowledge_pipeline_state(target_row.pipeline_run_id);
    RETURN target_row;
END;
$ack_knowledge_cancel$;

CREATE FUNCTION geno_v2_create_knowledge_quality_definition(
    p_definition_id uuid, p_project_id uuid, p_definition_key text,
    p_version integer, p_job_type text, p_target_kind text,
    p_severity_on_failure text, p_rule_contract jsonb
)
RETURNS knowledge_quality_definitions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $create_knowledge_quality_definition$
DECLARE tenant_scope uuid; actor_id text;
    result_row public.knowledge_quality_definitions%ROWTYPE;
BEGIN
    SELECT project.tenant_id INTO tenant_scope FROM public.projects AS project
    WHERE project.id = p_project_id AND project.status <> 'archived';
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        p_project_id, tenant_scope, 'system.admin'
    ) THEN
        RAISE EXCEPTION 'knowledge project is not accessible' USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geno_v2_resolve_session_context() AS context;
    INSERT INTO public.knowledge_quality_definitions (
        id, tenant_id, project_id, definition_key, version, job_type,
        target_kind, severity_on_failure, rule_contract, policy_class,
        required, active, created_by
    ) VALUES (
        p_definition_id, tenant_scope, p_project_id, btrim(p_definition_key),
        p_version, p_job_type, p_target_kind, p_severity_on_failure,
        p_rule_contract, p_rule_contract->>'policy_class', true, true, actor_id
    ) RETURNING * INTO result_row;
    RETURN result_row;
END;
$create_knowledge_quality_definition$;

CREATE FUNCTION geno_v2_create_knowledge_governance_version(
    p_source_asset_id uuid, p_governance_version_id uuid,
    p_expected_current_governance_id uuid, p_governance jsonb,
    p_reason text
)
RETURNS knowledge_source_governance_versions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $create_knowledge_governance_version$
DECLARE
    source_asset public.knowledge_source_assets%ROWTYPE;
    current_governance public.knowledge_source_governance_versions%ROWTYPE;
    result_row public.knowledge_source_governance_versions%ROWTYPE;
    tenant_scope uuid; actor_id text; item jsonb;
    next_version integer; governance_time timestamptz := statement_timestamp();
    canonical_governance jsonb; governance_hash text;
BEGIN
    IF p_governance_version_id IS NULL OR p_expected_current_governance_id IS NULL
       OR jsonb_typeof(p_governance) <> 'object'
       OR p_reason IS NULL OR btrim(p_reason) = ''
       OR p_governance::text ~* '"(password|passwd|secret|token|api_key|api-key|authorization|credential|private_key)"[[:space:]]*:' THEN
        RAISE EXCEPTION 'knowledge governance command arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO source_asset
    FROM public.knowledge_source_assets AS asset
    WHERE asset.id = p_source_asset_id
    FOR UPDATE;
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        source_asset.project_id, source_asset.tenant_id, 'knowledge.review'
    ) THEN
        RAISE EXCEPTION 'knowledge source is not accessible' USING ERRCODE = '42501';
    END IF;
    IF source_asset.current_governance_version_id <> p_expected_current_governance_id
       OR source_asset.current_revision_id IS NULL THEN
        RAISE EXCEPTION 'knowledge governance head changed' USING ERRCODE = '40001';
    END IF;
    IF source_asset.status = 'archived' THEN
        RAISE EXCEPTION 'archived knowledge source is terminal and cannot be reactivated'
            USING ERRCODE = '55000';
    END IF;
    SELECT * INTO current_governance
    FROM public.knowledge_source_governance_versions AS governance
    WHERE governance.id = source_asset.current_governance_version_id
      AND governance.project_id = source_asset.project_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'knowledge governance head is missing' USING ERRCODE = '23503';
    END IF;
    SELECT context.actor_id, context.tenant_id INTO actor_id, tenant_scope
    FROM public.geno_v2_resolve_session_context() AS context;
    IF actor_id = (
        SELECT source_input.requested_by
        FROM public.knowledge_source_asset_revisions AS revision
        JOIN public.knowledge_pipeline_jobs AS job
          ON job.id = revision.knowledge_job_id AND job.project_id = revision.project_id
        JOIN public.knowledge_import_sources AS source_input
          ON source_input.id = job.import_source_id AND source_input.project_id = job.project_id
        WHERE revision.id = source_asset.current_revision_id
          AND revision.project_id = source_asset.project_id
    ) THEN
        RAISE EXCEPTION 'source submitter cannot approve its governance version'
            USING ERRCODE = '42501';
    END IF;
    next_version := current_governance.governance_version + 1;
    canonical_governance := jsonb_build_object(
        'source_asset_id', source_asset.id,
        'source_revision_id', source_asset.current_revision_id,
        'governance_version', next_version,
        'authority_grade', coalesce(p_governance->>'authority_grade','D'),
        'usage_rights_status', coalesce(p_governance->>'usage_rights_status','unknown'),
        'authorization_basis', CASE
            WHEN coalesce(p_governance->>'usage_rights_status','unknown') = 'unknown'
            THEN NULL ELSE nullif(p_governance->>'authorization_basis','') END,
        'authorised_by', CASE
            WHEN coalesce(p_governance->>'usage_rights_status','unknown') = 'unknown'
            THEN NULL ELSE actor_id END,
        'authorised_at', CASE
            WHEN coalesce(p_governance->>'usage_rights_status','unknown') = 'unknown'
            THEN NULL ELSE governance_time END,
        'confidentiality', coalesce(p_governance->>'confidentiality','internal'),
        'consent_status', coalesce(p_governance->>'consent_status','unknown'),
        'consent_expires_at', p_governance->>'consent_expires_at',
        'external_model_use_allowed', coalesce((p_governance->>'external_model_use_allowed')::boolean,false),
        'public_adaptation_allowed', coalesce((p_governance->>'public_adaptation_allowed')::boolean,false),
        'customer_visible', coalesce((p_governance->>'customer_visible')::boolean,false),
        'public_disclosure_allowed', coalesce((p_governance->>'public_disclosure_allowed')::boolean,false),
        'public_source_url', p_governance->>'public_source_url',
        'public_source_title', p_governance->>'public_source_title',
        'citation_label', p_governance->>'citation_label',
        'quotation_allowed', coalesce((p_governance->>'quotation_allowed')::boolean,false),
        'attribution_required', coalesce((p_governance->>'attribution_required')::boolean,false),
        'claim_risk', coalesce(p_governance->>'claim_risk','high'),
        'policy_version', p_governance->>'policy_version',
        'valid_from', coalesce((p_governance->>'valid_from')::timestamptz, governance_time),
        'valid_until', p_governance->>'valid_until',
        'allowed_channels', coalesce(p_governance->'allowed_channels','[]'::jsonb),
        'reason', btrim(p_reason)
    );
    governance_hash := encode(public.digest(canonical_governance::text, 'sha256'), 'hex');
    INSERT INTO public.knowledge_source_governance_versions (
        id, tenant_id, project_id, source_asset_id, source_revision_id,
        governance_version, authority_grade, usage_rights_status,
        authorization_basis, authorised_by, authorised_at,
        confidentiality, consent_status, consent_expires_at,
        external_model_use_allowed, public_adaptation_allowed,
        customer_visible, public_disclosure_allowed, public_source_url,
        public_source_title, citation_label, quotation_allowed,
        attribution_required, claim_risk, policy_version, governance_hash,
        valid_from, valid_until, created_by
    ) VALUES (
        p_governance_version_id, source_asset.tenant_id, source_asset.project_id,
        source_asset.id, source_asset.current_revision_id, next_version,
        canonical_governance->>'authority_grade',
        canonical_governance->>'usage_rights_status',
        canonical_governance->>'authorization_basis',
        canonical_governance->>'authorised_by',
        (canonical_governance->>'authorised_at')::timestamptz,
        canonical_governance->>'confidentiality',
        canonical_governance->>'consent_status',
        (canonical_governance->>'consent_expires_at')::timestamptz,
        (canonical_governance->>'external_model_use_allowed')::boolean,
        (canonical_governance->>'public_adaptation_allowed')::boolean,
        (canonical_governance->>'customer_visible')::boolean,
        (canonical_governance->>'public_disclosure_allowed')::boolean,
        canonical_governance->>'public_source_url',
        canonical_governance->>'public_source_title',
        canonical_governance->>'citation_label',
        (canonical_governance->>'quotation_allowed')::boolean,
        (canonical_governance->>'attribution_required')::boolean,
        canonical_governance->>'claim_risk', canonical_governance->>'policy_version',
        governance_hash, (canonical_governance->>'valid_from')::timestamptz,
        (canonical_governance->>'valid_until')::timestamptz, actor_id
    ) RETURNING * INTO result_row;
    FOR item IN
        SELECT value FROM jsonb_array_elements(canonical_governance->'allowed_channels')
    LOOP
        INSERT INTO public.knowledge_source_governance_channels (
            tenant_id, project_id, governance_version_id,
            publication_channel, allowed
        ) VALUES (
            source_asset.tenant_id, source_asset.project_id,
            result_row.id, item->>'publication_channel',
            coalesce((item->>'allowed')::boolean,false)
        );
    END LOOP;
    UPDATE public.knowledge_source_assets AS asset
    SET current_governance_version_id = result_row.id,
        status = 'active', updated_at = statement_timestamp()
    WHERE asset.id = source_asset.id AND asset.project_id = source_asset.project_id;
    INSERT INTO public.audit_events (
        tenant_id, project_id, event_type, actor_type, actor_id,
        target_type, target_id, before_hash, after_hash, input_refs, method_version
    ) VALUES (
        source_asset.tenant_id, source_asset.project_id,
        'knowledge_source.governance_version_created', 'user', actor_id,
        'knowledge_source_asset', source_asset.id::text,
        current_governance.governance_hash, result_row.governance_hash,
        jsonb_build_object('reason', btrim(p_reason),
                           'governance_version_id', result_row.id),
        'knowledge_governance_command_v2'
    );
    RETURN result_row;
END;
$create_knowledge_governance_version$;

CREATE FUNCTION geno_v2_set_knowledge_source_status(
    p_source_asset_id uuid, p_status text, p_reason text
)
RETURNS knowledge_source_assets
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $set_knowledge_source_status$
DECLARE source_asset public.knowledge_source_assets%ROWTYPE; actor_id text;
BEGIN
    IF p_status NOT IN ('disabled','archived')
       OR p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'knowledge source status arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO source_asset FROM public.knowledge_source_assets AS asset
    WHERE asset.id = p_source_asset_id FOR UPDATE;
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        source_asset.project_id, source_asset.tenant_id, 'knowledge.review'
    ) THEN
        RAISE EXCEPTION 'knowledge source is not accessible' USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geno_v2_resolve_session_context() AS context;
    UPDATE public.knowledge_source_assets AS asset
    SET status = p_status, updated_at = statement_timestamp()
    WHERE asset.id = source_asset.id RETURNING asset.* INTO source_asset;
    INSERT INTO public.audit_events (
        tenant_id, project_id, event_type, actor_type, actor_id,
        target_type, target_id, input_refs, method_version
    ) VALUES (
        source_asset.tenant_id, source_asset.project_id,
        'knowledge_source.status_changed', 'user', actor_id,
        'knowledge_source_asset', source_asset.id::text,
        jsonb_build_object('status', p_status, 'reason', btrim(p_reason)),
        'knowledge_governance_command_v2'
    );
    RETURN source_asset;
END;
$set_knowledge_source_status$;

CREATE FUNCTION geno_v2_withdraw_knowledge_fact(
    p_fact_id uuid, p_reason text
)
RETURNS knowledge_facts
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $withdraw_knowledge_fact$
DECLARE fact_row public.knowledge_facts%ROWTYPE; actor_id text;
BEGIN
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'knowledge fact withdrawal reason is required'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO fact_row FROM public.knowledge_facts AS fact
    WHERE fact.id = p_fact_id FOR UPDATE;
    IF NOT FOUND OR fact_row.status <> 'active'
       OR NOT public.geno_v2_session_has_project_permission(
           fact_row.project_id, fact_row.tenant_id, 'knowledge.review'
       ) THEN
        RAISE EXCEPTION 'knowledge fact is not withdrawable' USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geno_v2_resolve_session_context() AS context;
    UPDATE public.knowledge_facts AS fact
    SET status = 'withdrawn', updated_at = statement_timestamp()
    WHERE fact.id = fact_row.id RETURNING fact.* INTO fact_row;
    INSERT INTO public.audit_events (
        tenant_id, project_id, event_type, actor_type, actor_id,
        target_type, target_id, input_refs, method_version
    ) VALUES (
        fact_row.tenant_id, fact_row.project_id,
        'knowledge_fact.withdrawn', 'user', actor_id,
        'knowledge_fact', fact_row.id::text,
        jsonb_build_object('reason', btrim(p_reason)),
        'knowledge_fact_command_v2'
    );
    RETURN fact_row;
END;
$withdraw_knowledge_fact$;

CREATE FUNCTION geno_v2_create_knowledge_job(
    p_job_id uuid, p_project_id uuid, p_pipeline_run_id uuid,
    p_pipeline_stage_id uuid, p_import_source_id uuid,
    p_job_type text, p_idempotency_key text, p_input_snapshot jsonb,
    p_depends_on_job_id uuid DEFAULT NULL
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $create_knowledge_job$
DECLARE
    tenant_scope uuid;
    actor_id text;
    authorised_time timestamptz := statement_timestamp();
    computed_request_hash text;
    computed_input_hash text;
    computed_governance_hash text;
    source_input jsonb;
    artifact_input jsonb;
    item jsonb;
    quality_definition_ids jsonb;
    frozen_governance_version_ids jsonb := '[]'::jsonb;
    canonical_input_snapshot jsonb;
    result_row public.knowledge_pipeline_jobs%ROWTYPE;
    stage_ordinal integer;
BEGIN
    IF p_job_id IS NULL OR p_pipeline_run_id IS NULL OR p_pipeline_stage_id IS NULL
       OR p_job_type NOT IN ('import','crawl','parse','chunk','embed','fact_extract')
       OR p_idempotency_key IS NULL OR btrim(p_idempotency_key) = ''
       OR jsonb_typeof(p_input_snapshot) <> 'object'
       OR p_input_snapshot ? 'quality_definition_ids' THEN
        RAISE EXCEPTION 'knowledge job creation arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_input_snapshot::text ~* '"(password|passwd|secret|token|api_key|api-key|authorization|credential|private_key)"[[:space:]]*:' THEN
        RAISE EXCEPTION 'knowledge job input contains a forbidden credential-like key'
            USING ERRCODE = '22023';
    END IF;
    IF (p_job_type IN ('import','crawl')
            AND p_input_snapshot - ARRAY['run_kind','source']::text[] <> '{}'::jsonb)
       OR (p_job_type = 'parse'
            AND p_input_snapshot - ARRAY[
                'run_kind','source_revision_id','parser_profile_ref'
            ]::text[] <> '{}'::jsonb)
       OR (p_job_type = 'chunk'
            AND p_input_snapshot - ARRAY[
                'run_kind','source_revision_id','parser_run_id','chunking_profile_ref'
            ]::text[] <> '{}'::jsonb)
       OR (p_job_type = 'embed'
            AND p_input_snapshot - ARRAY[
                'run_kind','chunk_ids','embedding_profile_ref','provider_capability_ref'
            ]::text[] <> '{}'::jsonb)
       OR (p_job_type = 'fact_extract'
            AND p_input_snapshot - ARRAY[
                'run_kind','chunk_ids','fact_extraction_profile_ref',
                'provider_capability_ref','model_policy_ref'
            ]::text[] <> '{}'::jsonb) THEN
        RAISE EXCEPTION 'knowledge job input contains unsupported top-level fields'
            USING ERRCODE = '22023';
    END IF;
    IF (p_job_type = 'parse'
            AND nullif(btrim(p_input_snapshot->>'parser_profile_ref'),'') IS NULL)
       OR (p_job_type = 'chunk'
            AND nullif(btrim(p_input_snapshot->>'chunking_profile_ref'),'') IS NULL)
       OR (p_job_type = 'embed' AND (
            jsonb_typeof(p_input_snapshot->'chunk_ids') <> 'array'
            OR jsonb_array_length(p_input_snapshot->'chunk_ids') = 0
            OR
            nullif(btrim(p_input_snapshot->>'embedding_profile_ref'),'') IS NULL
            OR nullif(btrim(p_input_snapshot->>'provider_capability_ref'),'') IS NULL))
       OR (p_job_type = 'fact_extract' AND (
            jsonb_typeof(p_input_snapshot->'chunk_ids') <> 'array'
            OR jsonb_array_length(p_input_snapshot->'chunk_ids') = 0
            OR
            nullif(btrim(p_input_snapshot->>'fact_extraction_profile_ref'),'') IS NULL
            OR nullif(btrim(p_input_snapshot->>'provider_capability_ref'),'') IS NULL
            OR nullif(btrim(p_input_snapshot->>'model_policy_ref'),'') IS NULL)) THEN
        RAISE EXCEPTION 'knowledge job requires opaque parser, model, and provider policy references'
            USING ERRCODE = '22023';
    END IF;
    SELECT project.tenant_id INTO tenant_scope FROM public.projects AS project
    WHERE project.id = p_project_id AND project.status <> 'archived';
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        p_project_id, tenant_scope, 'knowledge.import'
    ) THEN
        RAISE EXCEPTION 'knowledge project is not accessible' USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geno_v2_resolve_session_context() AS context;
    computed_request_hash := encode(public.digest(p_input_snapshot::text, 'sha256'), 'hex');
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            jsonb_build_array(p_project_id::text, btrim(p_idempotency_key))::text,
            0
        )
    );
    SELECT * INTO result_row FROM public.knowledge_pipeline_jobs AS existing
    WHERE existing.project_id = p_project_id
      AND existing.idempotency_key = btrim(p_idempotency_key)
    FOR UPDATE;
    IF FOUND THEN
        IF result_row.id = p_job_id
           AND result_row.pipeline_run_id = p_pipeline_run_id
           AND result_row.pipeline_stage_id = p_pipeline_stage_id
           AND result_row.import_source_id IS NOT DISTINCT FROM p_import_source_id
           AND result_row.job_type = p_job_type
           AND result_row.request_hash = computed_request_hash
           AND result_row.requested_by = actor_id
           AND (
               (p_depends_on_job_id IS NULL AND NOT EXISTS (
                   SELECT 1 FROM public.knowledge_pipeline_job_dependencies AS dependency
                   WHERE dependency.job_id = result_row.id
                     AND dependency.project_id = result_row.project_id
               ))
               OR (p_depends_on_job_id IS NOT NULL AND (
                   SELECT count(*) = 1
                          AND bool_and(dependency.depends_on_job_id = p_depends_on_job_id)
                   FROM public.knowledge_pipeline_job_dependencies AS dependency
                   WHERE dependency.job_id = result_row.id
                     AND dependency.project_id = result_row.project_id
               ))
           ) THEN
            RETURN result_row;
        END IF;
        RAISE EXCEPTION 'knowledge job idempotency conflict' USING ERRCODE = '23505';
    END IF;
    stage_ordinal := CASE p_job_type WHEN 'import' THEN 10 WHEN 'crawl' THEN 20
        WHEN 'parse' THEN 30 WHEN 'chunk' THEN 40 WHEN 'embed' THEN 50 ELSE 60 END;

    IF p_job_type IN ('import','crawl') THEN
        source_input := p_input_snapshot->'source';
        artifact_input := source_input->'artifact';
        IF p_import_source_id IS NULL OR jsonb_typeof(source_input) <> 'object'
           OR jsonb_typeof(artifact_input) <> 'object'
           OR source_input->>'source_asset_id' IS NULL
           OR jsonb_array_length(coalesce(source_input->'subjects','[]'::jsonb)) = 0 THEN
            RAISE EXCEPTION 'import and crawl jobs require a frozen source, target asset, artifact, and subject'
                USING ERRCODE = '22023';
        END IF;
        artifact_input := jsonb_build_object(
            'id', artifact_input->>'id',
            'outbox_id', artifact_input->>'outbox_id',
            'storage_uri', artifact_input->>'storage_uri',
            'storage_key', artifact_input->>'storage_key',
            'content_hash', artifact_input->>'content_hash',
            'size_bytes', artifact_input->>'size_bytes',
            'content_type', artifact_input->>'content_type'
        );
        source_input := jsonb_build_object(
            'source_asset_id', source_input->>'source_asset_id',
            'source_mode', source_input->>'source_mode',
            'source_url', source_input->>'source_url',
            'source_text_hash', source_input->>'source_text_hash',
            'source_label', source_input->>'source_label',
            'artifact', artifact_input,
            'authority_grade', source_input->>'authority_grade',
            'usage_rights_status', source_input->>'usage_rights_status',
            'authorization_basis', source_input->>'authorization_basis',
            'confidentiality', source_input->>'confidentiality',
            'consent_status', source_input->>'consent_status',
            'consent_expires_at', source_input->>'consent_expires_at',
            'external_model_use_allowed', source_input->>'external_model_use_allowed',
            'public_adaptation_allowed', source_input->>'public_adaptation_allowed',
            'customer_visible', source_input->>'customer_visible',
            'public_disclosure_allowed', source_input->>'public_disclosure_allowed',
            'public_source_url', source_input->>'public_source_url',
            'public_source_title', source_input->>'public_source_title',
            'citation_label', source_input->>'citation_label',
            'quotation_allowed', source_input->>'quotation_allowed',
            'attribution_required', source_input->>'attribution_required',
            'claim_risk', source_input->>'claim_risk',
            'policy_version', source_input->>'policy_version',
            'valid_from', source_input->>'valid_from',
            'valid_until', source_input->>'valid_until',
            'subjects', source_input->'subjects',
            'allowed_channels', source_input->'allowed_channels'
        );
        IF source_input->>'source_mode' IN ('file','csv','text') THEN
            source_input := source_input || jsonb_build_object(
                'usage_rights_status', 'customer_authorised',
                'authorization_basis', 'project_upload_attestation_v1',
                'policy_version', 'project_upload_policy_v1',
                'external_model_use_allowed', true,
                'public_adaptation_allowed', true,
                'customer_visible', false,
                'public_disclosure_allowed', false,
                'public_source_url', NULL,
                'public_source_title', NULL,
                'citation_label', NULL,
                'quotation_allowed', false,
                'attribution_required', false
            );
        ELSE
            source_input := source_input || jsonb_build_object(
                'usage_rights_status', 'unknown',
                'authorization_basis', NULL,
                'policy_version', 'unclassified_source_policy_v1',
                'external_model_use_allowed', false,
                'public_adaptation_allowed', false,
                'customer_visible', false,
                'public_disclosure_allowed', false,
                'public_source_url', NULL,
                'public_source_title', NULL,
                'citation_label', NULL,
                'quotation_allowed', false,
                'attribution_required', false
            );
        END IF;
    ELSIF p_import_source_id IS NOT NULL THEN
        RAISE EXCEPTION 'only import and crawl jobs may reference an import source'
            USING ERRCODE = '22023';
    END IF;

    SELECT jsonb_agg(definition.id ORDER BY definition.definition_key)
    INTO quality_definition_ids
    FROM (
        SELECT DISTINCT ON (candidate.definition_key)
               candidate.id, candidate.definition_key
        FROM public.knowledge_quality_definitions AS candidate
        WHERE candidate.project_id = p_project_id
          AND candidate.job_type = p_job_type
          AND candidate.required AND candidate.active
        ORDER BY candidate.definition_key, candidate.version DESC, candidate.id
    ) AS definition;
    IF jsonb_array_length(coalesce(quality_definition_ids, '[]'::jsonb)) = 0 THEN
        RAISE EXCEPTION 'system required quality release is missing for knowledge job type'
            USING ERRCODE = '55000';
    END IF;
    IF p_job_type IN ('embed','fact_extract') THEN
        SELECT jsonb_agg(source_asset.current_governance_version_id ORDER BY chunk_row.id)
        INTO frozen_governance_version_ids
        FROM jsonb_array_elements_text(p_input_snapshot->'chunk_ids') AS requested(chunk_id)
        JOIN public.knowledge_chunks AS chunk_row
          ON chunk_row.id = requested.chunk_id::uuid
         AND chunk_row.project_id = p_project_id
        JOIN public.knowledge_source_asset_revisions AS revision
          ON revision.id = chunk_row.source_revision_id
         AND revision.project_id = chunk_row.project_id
        JOIN public.knowledge_source_assets AS source_asset
          ON source_asset.id = revision.source_asset_id
         AND source_asset.project_id = revision.project_id;
        IF jsonb_array_length(coalesce(frozen_governance_version_ids,'[]'::jsonb))
           <> jsonb_array_length(p_input_snapshot->'chunk_ids') THEN
            RAISE EXCEPTION 'knowledge chunk input governance cannot be frozen'
                USING ERRCODE = '23503';
        END IF;
    END IF;
    canonical_input_snapshot := jsonb_build_object(
        'job_type', p_job_type,
        'pipeline_run_id', p_pipeline_run_id,
        'pipeline_stage_id', p_pipeline_stage_id,
        'import_source_id', p_import_source_id,
        'depends_on_job_id', p_depends_on_job_id,
        'request', CASE WHEN p_job_type IN ('import','crawl')
            THEN jsonb_set(p_input_snapshot, '{source}', source_input, false)
            ELSE p_input_snapshot END,
        'required_quality_definition_ids', quality_definition_ids,
        'governance_version_ids', frozen_governance_version_ids
    );
    computed_input_hash := encode(
        public.digest(canonical_input_snapshot::text, 'sha256'), 'hex'
    );

    INSERT INTO public.knowledge_pipeline_runs (
        id, tenant_id, project_id, run_kind, status,
        idempotency_key, requested_by
    ) VALUES (
        p_pipeline_run_id, tenant_scope, p_project_id,
        coalesce(nullif(p_input_snapshot->>'run_kind',''), 'ingest'),
        'queued', 'knowledge-run:' || p_pipeline_run_id::text, actor_id
    ) ON CONFLICT (id) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1 FROM public.knowledge_pipeline_runs AS run
        WHERE run.id = p_pipeline_run_id AND run.project_id = p_project_id
    ) THEN
        RAISE EXCEPTION 'knowledge pipeline run belongs to another project'
            USING ERRCODE = '23503';
    END IF;
    INSERT INTO public.knowledge_pipeline_stages (
        id, tenant_id, project_id, pipeline_run_id,
        stage_key, ordinal, status
    ) VALUES (
        p_pipeline_stage_id, tenant_scope, p_project_id, p_pipeline_run_id,
        p_job_type, stage_ordinal, 'queued'
    ) ON CONFLICT (pipeline_run_id, stage_key) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1 FROM public.knowledge_pipeline_stages AS stage
        WHERE stage.id = p_pipeline_stage_id AND stage.project_id = p_project_id
          AND stage.pipeline_run_id = p_pipeline_run_id AND stage.stage_key = p_job_type
    ) THEN
        RAISE EXCEPTION 'knowledge stage identity conflicts with the requested job'
            USING ERRCODE = '23505';
    END IF;

    IF p_job_type IN ('import','crawl') THEN
        computed_governance_hash := encode(public.digest(jsonb_build_object(
            'authority_grade', coalesce(source_input->>'authority_grade','D'),
            'usage_rights_status', coalesce(source_input->>'usage_rights_status','unknown'),
            'authorization_basis', CASE
                WHEN coalesce(source_input->>'usage_rights_status','unknown') = 'unknown'
                THEN NULL ELSE source_input->>'authorization_basis' END,
            'authorised_by', CASE
                WHEN coalesce(source_input->>'usage_rights_status','unknown') = 'unknown'
                THEN NULL ELSE actor_id END,
            'authorised_at', CASE
                WHEN coalesce(source_input->>'usage_rights_status','unknown') = 'unknown'
                THEN NULL ELSE authorised_time END,
            'confidentiality', coalesce(source_input->>'confidentiality','internal'),
            'consent_status', coalesce(source_input->>'consent_status','unknown'),
            'consent_expires_at', source_input->>'consent_expires_at',
            'external_model_use_allowed', coalesce((source_input->>'external_model_use_allowed')::boolean,false),
            'public_adaptation_allowed', coalesce((source_input->>'public_adaptation_allowed')::boolean,false),
            'customer_visible', coalesce((source_input->>'customer_visible')::boolean,false),
            'public_disclosure_allowed', coalesce((source_input->>'public_disclosure_allowed')::boolean,false),
            'public_source_url', source_input->>'public_source_url',
            'public_source_title', source_input->>'public_source_title',
            'citation_label', source_input->>'citation_label',
            'quotation_allowed', coalesce((source_input->>'quotation_allowed')::boolean,false),
            'attribution_required', coalesce((source_input->>'attribution_required')::boolean,false),
            'claim_risk', coalesce(source_input->>'claim_risk','high'),
            'policy_version', source_input->>'policy_version',
            'valid_from', coalesce(source_input->>'valid_from', authorised_time::text),
            'valid_until', source_input->>'valid_until',
            'subjects', source_input->'subjects',
            'allowed_channels', source_input->'allowed_channels'
        )::text, 'sha256'), 'hex');
        INSERT INTO public.evidence_assets (
            id, tenant_id, project_id, asset_type, storage_uri, storage_key,
            content_hash, size_bytes, content_type, access_policy,
            retention_policy, source_kind, artifact_status, created_by
        ) VALUES (
            (artifact_input->>'id')::uuid, tenant_scope, p_project_id,
            'knowledge_import_snapshot', artifact_input->>'storage_uri',
            artifact_input->>'storage_key', artifact_input->>'content_hash',
            (artifact_input->>'size_bytes')::bigint, artifact_input->>'content_type',
            'knowledge-internal', 'knowledge-source-v2', 'knowledge_import_input',
            'pending', actor_id
        );
        INSERT INTO public.artifact_finalize_outbox (
            id, tenant_id, project_id, evidence_asset_id, expected_content_hash
        ) VALUES (
            (artifact_input->>'outbox_id')::uuid, tenant_scope, p_project_id,
            (artifact_input->>'id')::uuid, artifact_input->>'content_hash'
        );
        INSERT INTO public.knowledge_import_sources (
            id, tenant_id, project_id, pipeline_run_id, target_source_asset_id,
            source_mode,
            source_url, source_text_hash, upload_evidence_asset_id, source_label,
            authority_grade, usage_rights_status, authorization_basis,
            authorised_by, authorised_at, confidentiality, consent_status,
            consent_expires_at, external_model_use_allowed, public_adaptation_allowed,
            customer_visible, public_disclosure_allowed, public_source_url,
            public_source_title, citation_label, quotation_allowed,
            attribution_required, claim_risk, policy_version, governance_hash,
            valid_from, valid_until, requested_by
        ) VALUES (
            p_import_source_id, tenant_scope, p_project_id, p_pipeline_run_id,
            (source_input->>'source_asset_id')::uuid,
            source_input->>'source_mode', nullif(source_input->>'source_url',''),
            nullif(source_input->>'source_text_hash',''),
            (artifact_input->>'id')::uuid, source_input->>'source_label',
            coalesce(source_input->>'authority_grade','D'),
            coalesce(source_input->>'usage_rights_status','unknown'),
            CASE WHEN coalesce(source_input->>'usage_rights_status','unknown') = 'unknown'
                 THEN NULL ELSE nullif(source_input->>'authorization_basis','') END,
            CASE WHEN coalesce(source_input->>'usage_rights_status','unknown') = 'unknown'
                 THEN NULL ELSE actor_id END,
            CASE WHEN coalesce(source_input->>'usage_rights_status','unknown') = 'unknown'
                 THEN NULL ELSE authorised_time END,
            coalesce(source_input->>'confidentiality','internal'),
            coalesce(source_input->>'consent_status','unknown'),
            (source_input->>'consent_expires_at')::timestamptz,
            coalesce((source_input->>'external_model_use_allowed')::boolean,false),
            coalesce((source_input->>'public_adaptation_allowed')::boolean,false),
            coalesce((source_input->>'customer_visible')::boolean,false),
            coalesce((source_input->>'public_disclosure_allowed')::boolean,false),
            nullif(source_input->>'public_source_url',''),
            nullif(source_input->>'public_source_title',''),
            nullif(source_input->>'citation_label',''),
            coalesce((source_input->>'quotation_allowed')::boolean,false),
            coalesce((source_input->>'attribution_required')::boolean,false),
            coalesce(source_input->>'claim_risk','high'), source_input->>'policy_version',
            computed_governance_hash,
            coalesce((source_input->>'valid_from')::timestamptz, authorised_time),
            (source_input->>'valid_until')::timestamptz, actor_id
        );
        FOR item IN SELECT value FROM jsonb_array_elements(source_input->'subjects') LOOP
            INSERT INTO public.knowledge_import_source_subjects (
                id, tenant_id, project_id, import_source_id,
                subject_entity_id, subject_role
            ) VALUES (
                coalesce((item->>'id')::uuid, gen_random_uuid()), tenant_scope,
                p_project_id, p_import_source_id,
                (item->>'subject_entity_id')::uuid, item->>'subject_role'
            );
        END LOOP;
        FOR item IN SELECT value FROM jsonb_array_elements(coalesce(source_input->'allowed_channels','[]'::jsonb)) LOOP
            INSERT INTO public.knowledge_import_source_channels (
                id, tenant_id, project_id, import_source_id,
                publication_channel, allowed
            ) VALUES (
                coalesce((item->>'id')::uuid, gen_random_uuid()), tenant_scope,
                p_project_id, p_import_source_id,
                item->>'publication_channel', coalesce((item->>'allowed')::boolean,false)
            );
        END LOOP;
    END IF;

    INSERT INTO public.knowledge_pipeline_jobs (
        id, tenant_id, project_id, pipeline_run_id, pipeline_stage_id,
        import_source_id, job_type, idempotency_key, request_hash, input_hash,
        requested_by
    ) VALUES (
        p_job_id, tenant_scope, p_project_id, p_pipeline_run_id,
        p_pipeline_stage_id, p_import_source_id, p_job_type,
        btrim(p_idempotency_key), computed_request_hash, computed_input_hash, actor_id
    ) RETURNING * INTO result_row;

    IF p_depends_on_job_id IS NOT NULL THEN
        INSERT INTO public.knowledge_pipeline_job_dependencies (
            tenant_id, project_id, job_id, depends_on_job_id
        ) VALUES (tenant_scope, p_project_id, p_job_id, p_depends_on_job_id);
    END IF;
    IF p_job_type = 'parse' THEN
        INSERT INTO public.knowledge_parse_job_inputs (
            tenant_id, project_id, knowledge_job_id, source_revision_id
        ) VALUES (
            tenant_scope, p_project_id, p_job_id,
            (p_input_snapshot->>'source_revision_id')::uuid
        );
    ELSIF p_job_type = 'chunk' THEN
        INSERT INTO public.knowledge_chunk_job_inputs (
            tenant_id, project_id, knowledge_job_id, source_revision_id, parser_run_id
        ) VALUES (
            tenant_scope, p_project_id, p_job_id,
            (p_input_snapshot->>'source_revision_id')::uuid,
            (p_input_snapshot->>'parser_run_id')::uuid
        );
    ELSIF p_job_type IN ('embed','fact_extract') THEN
        IF jsonb_array_length(coalesce(p_input_snapshot->'chunk_ids','[]'::jsonb)) = 0 THEN
            RAISE EXCEPTION 'embed and fact extraction require exact input chunks'
                USING ERRCODE = '22023';
        END IF;
        FOR item IN SELECT value FROM jsonb_array_elements(p_input_snapshot->'chunk_ids') LOOP
            INSERT INTO public.knowledge_chunk_set_job_inputs (
                tenant_id, project_id, knowledge_job_id, chunk_id,
                governance_version_id, input_kind
            )
            SELECT tenant_scope, p_project_id, p_job_id, chunk_row.id,
                   source_asset.current_governance_version_id, p_job_type
            FROM public.knowledge_chunks AS chunk_row
            JOIN public.knowledge_source_asset_revisions AS revision
              ON revision.id = chunk_row.source_revision_id
             AND revision.project_id = chunk_row.project_id
            JOIN public.knowledge_source_assets AS source_asset
              ON source_asset.id = revision.source_asset_id
             AND source_asset.project_id = revision.project_id
            WHERE chunk_row.id = (item #>> '{}')::uuid
              AND chunk_row.project_id = p_project_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'knowledge chunk input is missing from the project'
                    USING ERRCODE = '23503';
            END IF;
        END LOOP;
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(quality_definition_ids) LOOP
        INSERT INTO public.knowledge_job_quality_definitions (
            tenant_id, project_id, knowledge_job_id, quality_definition_id
        )
        SELECT tenant_scope, p_project_id, p_job_id, definition.id
        FROM public.knowledge_quality_definitions AS definition
        WHERE definition.id = (item #>> '{}')::uuid
          AND definition.project_id = p_project_id
          AND definition.job_type = p_job_type
          AND definition.required AND definition.active;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'quality definition is missing, inactive, or wrong for job type'
                USING ERRCODE = '23503';
        END IF;
    END LOOP;
    INSERT INTO public.knowledge_job_input_snapshots (
        tenant_id, project_id, knowledge_job_id, snapshot, snapshot_hash
    ) VALUES (
        tenant_scope, p_project_id, p_job_id,
        canonical_input_snapshot, computed_input_hash
    );
    INSERT INTO public.audit_events (
        tenant_id, project_id, event_type, actor_type, actor_id,
        target_type, target_id, after_hash, input_refs, method_version
    ) VALUES (
        tenant_scope, p_project_id, 'knowledge_job.created', 'user', actor_id,
        'knowledge_pipeline_job', p_job_id::text, computed_input_hash,
        jsonb_build_object('pipeline_run_id', p_pipeline_run_id,
                           'job_type', p_job_type),
        'knowledge_job_command_v2'
    );
    RETURN result_row;
END;
$create_knowledge_job$;

CREATE FUNCTION geno_v2_request_knowledge_job_cancel(
    p_job_id uuid, p_reason text
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $request_knowledge_cancel$
DECLARE target_row public.knowledge_pipeline_jobs%ROWTYPE; actor_id text;
BEGIN
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'knowledge cancel reason must be nonempty' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO target_row FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = p_job_id FOR UPDATE;
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        target_row.project_id, target_row.tenant_id, 'knowledge.import'
    ) THEN
        RAISE EXCEPTION 'knowledge job is not accessible' USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geno_v2_resolve_session_context() AS context;
    IF target_row.status = 'queued' THEN
        UPDATE public.knowledge_pipeline_jobs AS job
        SET status = 'cancelled', cancel_requested_at = statement_timestamp(),
            cancel_requested_by = actor_id, cancel_reason = btrim(p_reason),
            completed_at = statement_timestamp(), completed_by = actor_id,
            updated_at = statement_timestamp()
        WHERE job.id = p_job_id RETURNING job.* INTO target_row;
    ELSIF target_row.status IN ('running','finalizing') THEN
        IF target_row.cancel_requested_at IS NULL THEN
            UPDATE public.knowledge_pipeline_jobs AS job
            SET cancel_requested_at = statement_timestamp(),
                cancel_requested_by = actor_id, cancel_reason = btrim(p_reason),
                updated_at = statement_timestamp()
            WHERE job.id = p_job_id RETURNING job.* INTO target_row;
        END IF;
    ELSIF target_row.status <> 'cancelled' THEN
        RAISE EXCEPTION 'only active knowledge jobs can be cancelled'
            USING ERRCODE = '55000';
    END IF;
    PERFORM public.geno_v2_refresh_knowledge_pipeline_state(target_row.pipeline_run_id);
    RETURN target_row;
END;
$request_knowledge_cancel$;

CREATE FUNCTION geno_v2_replay_knowledge_job(
    p_source_job_id uuid, p_new_job_id uuid, p_idempotency_key text
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $replay_knowledge_job$
DECLARE source_row public.knowledge_pipeline_jobs%ROWTYPE;
    child_row public.knowledge_pipeline_jobs%ROWTYPE;
    actor_id text; next_nonce integer;
BEGIN
    IF p_new_job_id IS NULL OR p_idempotency_key IS NULL
       OR btrim(p_idempotency_key) = '' THEN
        RAISE EXCEPTION 'knowledge replay arguments are invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO source_row FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = p_source_job_id FOR UPDATE;
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        source_row.project_id, source_row.tenant_id, 'knowledge.import'
    ) THEN
        RAISE EXCEPTION 'knowledge job is not accessible' USING ERRCODE = '42501';
    END IF;
    IF source_row.status NOT IN ('failed','cancelled','dead_lettered') THEN
        RAISE EXCEPTION 'only unsuccessful terminal knowledge jobs can be replayed'
            USING ERRCODE = '55000';
    END IF;
    next_nonce := source_row.replay_nonce + 1;
    SELECT * INTO child_row FROM public.knowledge_pipeline_jobs AS existing
    WHERE existing.project_id = source_row.project_id
      AND existing.parent_job_id = source_row.id
      AND existing.replay_nonce = next_nonce;
    IF FOUND THEN
        IF child_row.id = p_new_job_id
           AND child_row.idempotency_key = btrim(p_idempotency_key) THEN
            RETURN child_row;
        END IF;
        RAISE EXCEPTION 'knowledge replay idempotency conflict' USING ERRCODE = '23505';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geno_v2_resolve_session_context() AS context;
    BEGIN
        INSERT INTO public.knowledge_pipeline_jobs (
            id, tenant_id, project_id, pipeline_run_id, pipeline_stage_id,
            import_source_id, job_type, idempotency_key, request_hash, input_hash,
            parent_job_id, replay_nonce, priority, max_attempts,
            next_attempt_at, requested_by
        ) VALUES (
            p_new_job_id, source_row.tenant_id, source_row.project_id,
            source_row.pipeline_run_id, source_row.pipeline_stage_id,
            source_row.import_source_id, source_row.job_type,
            btrim(p_idempotency_key), source_row.request_hash, source_row.input_hash,
            source_row.id, next_nonce, source_row.priority,
            source_row.max_attempts, statement_timestamp(), actor_id
        ) RETURNING * INTO child_row;
    EXCEPTION WHEN unique_violation THEN
        SELECT * INTO child_row FROM public.knowledge_pipeline_jobs AS existing
        WHERE existing.project_id = source_row.project_id
          AND existing.parent_job_id = source_row.id
          AND existing.replay_nonce = next_nonce FOR UPDATE;
        IF FOUND AND child_row.id = p_new_job_id
           AND child_row.idempotency_key = btrim(p_idempotency_key) THEN
            RETURN child_row;
        END IF;
        RAISE EXCEPTION 'knowledge replay idempotency conflict' USING ERRCODE = '23505';
    END;
    INSERT INTO public.knowledge_pipeline_job_dependencies (
        tenant_id, project_id, job_id, depends_on_job_id
    ) SELECT source_row.tenant_id, source_row.project_id, child_row.id,
             dependency.depends_on_job_id
      FROM public.knowledge_pipeline_job_dependencies AS dependency
      WHERE dependency.job_id = source_row.id
        AND dependency.project_id = source_row.project_id;
    INSERT INTO public.knowledge_parse_job_inputs (
        tenant_id, project_id, knowledge_job_id, source_revision_id
    ) SELECT source_row.tenant_id, source_row.project_id, child_row.id,
             input_row.source_revision_id
      FROM public.knowledge_parse_job_inputs AS input_row
      WHERE input_row.knowledge_job_id = source_row.id
        AND input_row.project_id = source_row.project_id;
    INSERT INTO public.knowledge_chunk_job_inputs (
        tenant_id, project_id, knowledge_job_id, source_revision_id, parser_run_id
    ) SELECT source_row.tenant_id, source_row.project_id, child_row.id,
             input_row.source_revision_id, input_row.parser_run_id
      FROM public.knowledge_chunk_job_inputs AS input_row
      WHERE input_row.knowledge_job_id = source_row.id
        AND input_row.project_id = source_row.project_id;
    INSERT INTO public.knowledge_chunk_set_job_inputs (
        tenant_id, project_id, knowledge_job_id, chunk_id,
        governance_version_id, input_kind
    ) SELECT source_row.tenant_id, source_row.project_id, child_row.id,
             input_row.chunk_id, input_row.governance_version_id,
             input_row.input_kind
      FROM public.knowledge_chunk_set_job_inputs AS input_row
      WHERE input_row.knowledge_job_id = source_row.id
        AND input_row.project_id = source_row.project_id;
    INSERT INTO public.knowledge_job_quality_definitions (
        tenant_id, project_id, knowledge_job_id, quality_definition_id
    ) SELECT source_row.tenant_id, source_row.project_id, child_row.id,
             frozen.quality_definition_id
      FROM public.knowledge_job_quality_definitions AS frozen
      WHERE frozen.knowledge_job_id = source_row.id
        AND frozen.project_id = source_row.project_id;
    INSERT INTO public.knowledge_job_input_snapshots (
        tenant_id, project_id, knowledge_job_id, snapshot, snapshot_hash
    )
    SELECT source_row.tenant_id, source_row.project_id, child_row.id,
           input_snapshot.snapshot, input_snapshot.snapshot_hash
    FROM public.knowledge_job_input_snapshots AS input_snapshot
    WHERE input_snapshot.knowledge_job_id = source_row.id
      AND input_snapshot.project_id = source_row.project_id;
    RETURN child_row;
END;
$replay_knowledge_job$;

CREATE FUNCTION geno_v2_retry_knowledge_pipeline_stage(
    p_pipeline_stage_id uuid, p_new_job_id uuid, p_idempotency_key text
)
RETURNS knowledge_pipeline_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $retry_knowledge_stage$
DECLARE source_job_id uuid; result_row public.knowledge_pipeline_jobs%ROWTYPE;
BEGIN
    SELECT job.id INTO source_job_id
    FROM public.knowledge_pipeline_jobs AS job
    WHERE job.pipeline_stage_id = p_pipeline_stage_id
      AND job.status IN ('failed','cancelled','dead_lettered')
    ORDER BY job.created_at DESC, job.id DESC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'knowledge stage has no retryable terminal job'
            USING ERRCODE = '55000';
    END IF;
    result_row := public.geno_v2_replay_knowledge_job(
        source_job_id, p_new_job_id, p_idempotency_key
    );
    UPDATE public.knowledge_pipeline_stages AS stage
    SET status = 'queued', retry_count = retry_count + 1,
        updated_at = statement_timestamp()
    WHERE stage.id = p_pipeline_stage_id;
    RETURN result_row;
END;
$retry_knowledge_stage$;

CREATE FUNCTION geno_v2_guard_knowledge_risk_acceptance()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard_knowledge_risk_acceptance$
DECLARE finding_row public.knowledge_quality_findings%ROWTYPE;
BEGIN
    SELECT * INTO finding_row FROM public.knowledge_quality_findings AS finding
    WHERE finding.id = NEW.quality_finding_id
      AND finding.project_id = NEW.project_id;
    IF NOT FOUND OR finding_row.severity = 'hard_block'
       OR finding_row.finding_code ~* '^(rights|security|confidentiality|unauthorised_pii|classification_policy_violation|unredacted_restricted_data)' THEN
        RAISE EXCEPTION 'hard, rights, classification, or security findings cannot be accepted'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_knowledge_risk_acceptance$;

CREATE TRIGGER knowledge_risk_acceptance_guard
BEFORE INSERT ON knowledge_risk_acceptances
FOR EACH ROW EXECUTE FUNCTION geno_v2_guard_knowledge_risk_acceptance();

CREATE FUNCTION geno_v2_accept_knowledge_risk(
    p_acceptance_id uuid, p_finding_id uuid, p_reason text
)
RETURNS knowledge_risk_acceptances
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $accept_knowledge_risk$
DECLARE finding_row public.knowledge_quality_findings%ROWTYPE;
    actor_id text; result_row public.knowledge_risk_acceptances%ROWTYPE;
BEGIN
    SELECT * INTO finding_row FROM public.knowledge_quality_findings AS finding
    WHERE finding.id = p_finding_id;
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        finding_row.project_id, finding_row.tenant_id, 'knowledge.review'
    ) THEN
        RAISE EXCEPTION 'knowledge finding is not accessible' USING ERRCODE = '42501';
    END IF;
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'risk acceptance reason must be nonempty' USING ERRCODE = '22023';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geno_v2_resolve_session_context() AS context;
    INSERT INTO public.knowledge_risk_acceptances (
        id, tenant_id, project_id, quality_finding_id,
        accepted_by, acceptance_reason
    ) VALUES (
        p_acceptance_id, finding_row.tenant_id, finding_row.project_id,
        finding_row.id, actor_id, btrim(p_reason)
    ) RETURNING * INTO result_row;
    RETURN result_row;
END;
$accept_knowledge_risk$;

CREATE FUNCTION geno_v2_validate_candidate_review_consistency()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_candidate_review_consistency$
DECLARE candidate_id uuid; candidate_project uuid;
    candidate_row public.knowledge_fact_candidates%ROWTYPE;
    review_row public.knowledge_fact_candidate_reviews%ROWTYPE;
BEGIN
    IF TG_TABLE_NAME = 'knowledge_fact_candidates' THEN
        candidate_id := NEW.id;
    ELSE
        candidate_id := NEW.fact_candidate_id;
    END IF;
    candidate_project := NEW.project_id;
    SELECT * INTO candidate_row FROM public.knowledge_fact_candidates AS candidate
    WHERE candidate.id = candidate_id AND candidate.project_id = candidate_project;
    SELECT * INTO review_row FROM public.knowledge_fact_candidate_reviews AS review
    WHERE review.fact_candidate_id = candidate_id AND review.project_id = candidate_project;
    IF candidate_row.status = 'pending_review' THEN
        IF FOUND THEN
            RAISE EXCEPTION 'pending candidate cannot have a terminal review'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NOT FOUND OR review_row.decision <> candidate_row.status
       OR review_row.reviewer_id = candidate_row.submitted_for_review_by
       OR candidate_row.reviewed_at <> review_row.created_at THEN
        RAISE EXCEPTION 'candidate terminal state and review record are inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$validate_candidate_review_consistency$;

CREATE FUNCTION geno_v2_validate_fact_source_governance_lineage()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_fact_source_governance_lineage$
DECLARE resolved_revision_id uuid; authoritative_hash text;
    candidate_job_id uuid; candidate_status text;
BEGIN
    SELECT coalesce(NEW.source_revision_id, chunk_row.source_revision_id,
                    block_row.source_revision_id, table_row.source_revision_id),
           coalesce(revision_row.source_content_hash, chunk_row.content_hash,
                    block_row.content_hash, table_row.content_hash)
    INTO resolved_revision_id, authoritative_hash
    FROM (SELECT 1) AS singleton
    LEFT JOIN public.knowledge_chunks AS chunk_row
      ON chunk_row.id = NEW.chunk_id AND chunk_row.project_id = NEW.project_id
    LEFT JOIN public.knowledge_blocks AS block_row
      ON block_row.id = NEW.block_id AND block_row.project_id = NEW.project_id
    LEFT JOIN public.knowledge_tables AS table_row
      ON table_row.id = NEW.table_id AND table_row.project_id = NEW.project_id
    LEFT JOIN public.knowledge_source_asset_revisions AS revision_row
      ON revision_row.id = NEW.source_revision_id
     AND revision_row.project_id = NEW.project_id;
    IF resolved_revision_id IS NULL OR authoritative_hash IS NULL
       OR NEW.source_snapshot_hash <> authoritative_hash THEN
        RAISE EXCEPTION 'fact source snapshot hash does not match its exact source'
            USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'knowledge_fact_candidate_sources' THEN
        SELECT candidate.knowledge_job_id, candidate.status
        INTO candidate_job_id, candidate_status
        FROM public.knowledge_fact_candidates AS candidate
        WHERE candidate.id = NEW.fact_candidate_id
          AND candidate.project_id = NEW.project_id;
        IF NOT FOUND OR candidate_status <> 'pending_review' THEN
            RAISE EXCEPTION 'fact candidate source parent is missing or terminal'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM public.knowledge_chunk_set_job_inputs AS frozen
            WHERE frozen.knowledge_job_id = candidate_job_id
              AND frozen.project_id = NEW.project_id
              AND frozen.input_kind = 'fact_extract'
              AND frozen.chunk_id = NEW.chunk_id
        ) THEN
            RAISE EXCEPTION 'fact candidate source is outside its producer input or terminal'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.knowledge_source_governance_versions AS governance
        WHERE governance.id = NEW.governance_version_id
          AND governance.project_id = NEW.project_id
          AND governance.source_revision_id = resolved_revision_id
    ) THEN
        RAISE EXCEPTION 'fact source governance does not govern its exact source revision'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$validate_fact_source_governance_lineage$;

CREATE CONSTRAINT TRIGGER knowledge_fact_source_governance_lineage
AFTER INSERT ON knowledge_fact_version_sources DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_fact_source_governance_lineage();
CREATE CONSTRAINT TRIGGER knowledge_candidate_source_exact_lineage
AFTER INSERT ON knowledge_fact_candidate_sources DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_fact_source_governance_lineage();

CREATE CONSTRAINT TRIGGER knowledge_candidate_review_consistency
AFTER UPDATE ON knowledge_fact_candidates DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_candidate_review_consistency();
CREATE CONSTRAINT TRIGGER knowledge_review_candidate_consistency
AFTER INSERT ON knowledge_fact_candidate_reviews DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_candidate_review_consistency();

CREATE FUNCTION geno_v2_review_knowledge_fact_candidate(
    p_candidate_id uuid, p_review_id uuid, p_fact_id uuid,
    p_fact_version_id uuid, p_decision text, p_notes text DEFAULT NULL,
    p_expected_current_version_id uuid DEFAULT NULL,
    p_base_statement_hash text DEFAULT NULL
)
RETURNS knowledge_fact_candidates
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $review_knowledge_candidate$
DECLARE
    candidate_row public.knowledge_fact_candidates%ROWTYPE;
    producer_row public.knowledge_pipeline_jobs%ROWTYPE;
    fact_row public.knowledge_facts%ROWTYPE;
    base_version_row public.knowledge_fact_versions%ROWTYPE;
    actor_id text;
    review_time timestamptz := statement_timestamp();
    source_count integer;
    min_authority_rank integer;
    all_customer_visible boolean;
    all_public boolean;
    all_quotation boolean;
    any_attribution boolean;
    snapshot_valid_from timestamptz;
    snapshot_valid_until timestamptz;
    snapshot_url text;
    snapshot_title text;
    snapshot_label text;
    snapshot_grade text;
    public_url_count integer;
    public_title_count integer;
    next_fact_version integer;
    fact_public boolean;
BEGIN
    IF p_decision NOT IN ('approved','rejected')
       OR (p_decision = 'approved' AND (p_fact_id IS NULL OR p_fact_version_id IS NULL))
       OR ((p_expected_current_version_id IS NULL) <>
           (p_base_statement_hash IS NULL))
       OR (p_decision = 'rejected' AND (
           p_fact_id IS NOT NULL OR p_fact_version_id IS NOT NULL
           OR p_expected_current_version_id IS NOT NULL
           OR p_base_statement_hash IS NOT NULL)) THEN
        RAISE EXCEPTION 'knowledge review arguments are invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO candidate_row FROM public.knowledge_fact_candidates AS candidate
    WHERE candidate.id = p_candidate_id FOR UPDATE;
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        candidate_row.project_id, candidate_row.tenant_id, 'knowledge.review'
    ) THEN
        RAISE EXCEPTION 'knowledge candidate is not accessible' USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geno_v2_resolve_session_context() AS context;
    IF candidate_row.status <> 'pending_review' THEN
        IF EXISTS (
            SELECT 1 FROM public.knowledge_fact_candidate_reviews AS review
            WHERE review.fact_candidate_id = candidate_row.id
              AND review.project_id = candidate_row.project_id
              AND review.id = p_review_id AND review.decision = p_decision
              AND review.reviewer_id = actor_id
              AND (
                  (p_decision = 'rejected' AND p_fact_id IS NULL
                      AND p_fact_version_id IS NULL)
                  OR (p_decision = 'approved' AND EXISTS (
                      SELECT 1 FROM public.knowledge_fact_versions AS existing_version
                      WHERE existing_version.id = p_fact_version_id
                        AND existing_version.fact_id = p_fact_id
                        AND existing_version.source_candidate_id = candidate_row.id
                        AND existing_version.project_id = candidate_row.project_id
                        AND existing_version.base_version_id IS NOT DISTINCT FROM
                            p_expected_current_version_id
                        AND existing_version.base_statement_hash IS NOT DISTINCT FROM
                            p_base_statement_hash
                  ))
              )
        ) THEN
            RETURN candidate_row;
        END IF;
        RAISE EXCEPTION 'knowledge review idempotency conflict' USING ERRCODE = '23505';
    END IF;
    IF actor_id = candidate_row.submitted_for_review_by THEN
        RAISE EXCEPTION 'candidate submitter cannot approve or reject the candidate'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO producer_row
    FROM public.knowledge_pipeline_jobs AS job
    WHERE job.id = candidate_row.knowledge_job_id
      AND job.project_id = candidate_row.project_id
    FOR SHARE;
    IF NOT FOUND OR producer_row.job_type <> 'fact_extract'
       OR producer_row.status <> 'succeeded'
       OR NOT public.geno_v2_knowledge_quality_certificate_complete(producer_row.id)
       OR NOT EXISTS (
           SELECT 1
           FROM public.knowledge_job_artifacts AS link
           JOIN public.evidence_assets AS artifact
             ON artifact.id = link.evidence_asset_id
            AND artifact.project_id = link.project_id
           WHERE link.knowledge_job_id = producer_row.id
             AND link.project_id = producer_row.project_id
             AND link.artifact_role = 'raw_model_output'
             AND artifact.artifact_status = 'finalized'
       ) THEN
        RAISE EXCEPTION 'candidate producer is not succeeded with a finalized quality certificate'
            USING ERRCODE = '55000';
    END IF;

    IF p_decision = 'approved' THEN
        PERFORM 1
        FROM public.knowledge_fact_candidate_sources AS source
        JOIN public.knowledge_chunks AS chunk_row
          ON chunk_row.id = source.chunk_id AND chunk_row.project_id = source.project_id
        JOIN public.knowledge_source_asset_revisions AS revision
          ON revision.id = chunk_row.source_revision_id
         AND revision.project_id = chunk_row.project_id
        JOIN public.knowledge_source_assets AS source_asset
          ON source_asset.id = revision.source_asset_id
         AND source_asset.project_id = revision.project_id
        WHERE source.fact_candidate_id = candidate_row.id
          AND source.project_id = candidate_row.project_id
        ORDER BY source_asset.id
        FOR SHARE OF source_asset;
        WITH resolved_sources AS (
            SELECT source.id, source.locator, source.source_snapshot_hash,
                   source.chunk_id, source.block_id, source.table_id,
                   source.source_revision_id,
                   coalesce(source.source_revision_id, chunk_row.source_revision_id,
                            block_row.source_revision_id, table_row.source_revision_id)
                       AS resolved_revision_id
            FROM public.knowledge_fact_candidate_sources AS source
            LEFT JOIN public.knowledge_chunks AS chunk_row
              ON chunk_row.id = source.chunk_id AND chunk_row.project_id = source.project_id
            LEFT JOIN public.knowledge_blocks AS block_row
              ON block_row.id = source.block_id AND block_row.project_id = source.project_id
            LEFT JOIN public.knowledge_tables AS table_row
              ON table_row.id = source.table_id AND table_row.project_id = source.project_id
            WHERE source.fact_candidate_id = candidate_row.id
              AND source.project_id = candidate_row.project_id
        ), governed AS (
            SELECT resolved.*, governance.id AS governance_id,
                   governance.project_id AS governance_project_id,
                   governance.authority_rank, governance.customer_visible,
                   governance.public_disclosure_allowed,
                   governance.quotation_allowed, governance.attribution_required,
                   governance.valid_from, governance.valid_until,
                   governance.public_source_url, governance.public_source_title,
                   governance.citation_label, governance.usage_rights_status,
                   governance.confidentiality, governance.consent_status,
                   governance.consent_expires_at,
                   governance.external_model_use_allowed,
                   governance.public_adaptation_allowed, governance.claim_risk
            FROM resolved_sources AS resolved
            JOIN public.knowledge_source_asset_revisions AS revision
              ON revision.id = resolved.resolved_revision_id
             AND revision.project_id = candidate_row.project_id
            JOIN public.knowledge_source_assets AS source_asset
              ON source_asset.id = revision.source_asset_id
             AND source_asset.project_id = revision.project_id
             AND source_asset.current_revision_id = revision.id
             AND source_asset.status = 'active'
            JOIN public.knowledge_source_governance_versions AS governance
              ON governance.id = source_asset.current_governance_version_id
             AND governance.project_id = source_asset.project_id
             AND governance.source_revision_id = revision.id
            WHERE revision.status = 'active'
        )
        SELECT count(*), min(authority_rank), bool_and(customer_visible),
               bool_and(public_disclosure_allowed), bool_and(quotation_allowed),
               bool_or(attribution_required), max(valid_from), min(valid_until),
               min(public_source_url), min(public_source_title), min(citation_label),
               count(DISTINCT public_source_url), count(DISTINCT public_source_title)
        INTO source_count, min_authority_rank, all_customer_visible,
             all_public, all_quotation, any_attribution,
             snapshot_valid_from, snapshot_valid_until,
             snapshot_url, snapshot_title, snapshot_label,
             public_url_count, public_title_count
        FROM governed
        WHERE authority_rank >= 2
          AND usage_rights_status IN ('public_reuse','customer_authorised')
          AND confidentiality IN ('public','internal')
          AND consent_status IN ('not_required','granted')
          AND (consent_expires_at IS NULL OR consent_expires_at > review_time)
          AND external_model_use_allowed AND public_adaptation_allowed
          AND claim_risk <> 'prohibited'
          AND valid_from <= review_time
          AND (valid_until IS NULL OR valid_until > review_time)
          AND EXISTS (
              SELECT 1 FROM public.knowledge_source_governance_channels AS channel
              WHERE channel.governance_version_id = governed.governance_id
                AND channel.project_id = governed.governance_project_id AND channel.allowed
          );
        IF source_count = 0 OR source_count <> (
            SELECT count(*) FROM public.knowledge_fact_candidate_sources AS source
            WHERE source.fact_candidate_id = candidate_row.id
              AND source.project_id = candidate_row.project_id
        ) THEN
            RAISE EXCEPTION 'candidate evidence is missing or governance-ineligible'
                USING ERRCODE = '55000';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM public.knowledge_fact_candidate_sources AS source
            LEFT JOIN public.knowledge_chunks AS chunk_row
              ON chunk_row.id = source.chunk_id AND chunk_row.project_id = source.project_id
            LEFT JOIN public.knowledge_blocks AS block_row
              ON block_row.id = source.block_id AND block_row.project_id = source.project_id
            LEFT JOIN public.knowledge_tables AS table_row
              ON table_row.id = source.table_id AND table_row.project_id = source.project_id
            JOIN public.knowledge_source_asset_revisions AS revision
              ON revision.id = coalesce(source.source_revision_id, chunk_row.source_revision_id,
                                        block_row.source_revision_id, table_row.source_revision_id)
             AND revision.project_id = source.project_id
            WHERE source.fact_candidate_id = candidate_row.id
              AND source.project_id = candidate_row.project_id
              AND (
                  NOT EXISTS (
                      SELECT 1 FROM public.knowledge_source_revision_artifacts AS link
                      WHERE link.source_revision_id = revision.id
                        AND link.project_id = revision.project_id
                  )
                  OR EXISTS (
                      SELECT 1 FROM public.knowledge_source_revision_artifacts AS link
                      JOIN public.evidence_assets AS artifact
                        ON artifact.id = link.evidence_asset_id
                       AND artifact.project_id = link.project_id
                      WHERE link.source_revision_id = revision.id
                        AND link.project_id = revision.project_id
                        AND artifact.artifact_status <> 'finalized'
                  )
                  OR NOT EXISTS (
                      SELECT 1 FROM public.knowledge_source_subjects AS subject
                      WHERE subject.source_revision_id = revision.id
                        AND subject.project_id = revision.project_id
                        AND subject.subject_role = candidate_row.subject_role
                        AND subject.subject_entity_id IS NOT DISTINCT FROM
                            candidate_row.subject_entity_id
                  )
              )
        ) THEN
            RAISE EXCEPTION 'candidate source artifacts or subject binding are invalid'
                USING ERRCODE = '55000';
        END IF;

        snapshot_grade := CASE min_authority_rank WHEN 4 THEN 'A' WHEN 3 THEN 'B'
                                              WHEN 2 THEN 'C' ELSE 'D' END;
        fact_public := coalesce(all_public, false)
            AND public_url_count = 1 AND public_title_count = 1;
        SELECT * INTO STRICT producer_row
        FROM public.knowledge_pipeline_jobs AS job
        WHERE job.id = candidate_row.knowledge_job_id
          AND job.project_id = candidate_row.project_id;
        SELECT * INTO fact_row FROM public.knowledge_facts AS fact
        WHERE fact.id = p_fact_id FOR UPDATE;
        IF FOUND THEN
            IF fact_row.project_id <> candidate_row.project_id
               OR fact_row.subject_entity_id IS DISTINCT FROM candidate_row.subject_entity_id
               OR fact_row.subject_role <> candidate_row.subject_role
               OR fact_row.fact_type <> candidate_row.fact_type
               OR fact_row.status <> 'active'
               OR p_expected_current_version_id IS NULL
               OR p_base_statement_hash IS NULL
               OR fact_row.current_version_id <> p_expected_current_version_id THEN
                RAISE EXCEPTION 'fact target or expected base version is incompatible'
                    USING ERRCODE = '40001';
            END IF;
            SELECT * INTO base_version_row
            FROM public.knowledge_fact_versions AS version_row
            WHERE version_row.id = fact_row.current_version_id
              AND version_row.project_id = fact_row.project_id
              AND version_row.statement_hash = p_base_statement_hash;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'fact base content hash changed'
                    USING ERRCODE = '40001';
            END IF;
        ELSE
            IF p_expected_current_version_id IS NOT NULL
               OR p_base_statement_hash IS NOT NULL THEN
                RAISE EXCEPTION 'new fact cannot specify an existing base version'
                    USING ERRCODE = '22023';
            END IF;
            INSERT INTO public.knowledge_facts (
                id, tenant_id, project_id, subject_entity_id, subject_role,
                fact_type, status
            ) VALUES (
                p_fact_id, candidate_row.tenant_id, candidate_row.project_id,
                candidate_row.subject_entity_id, candidate_row.subject_role,
                candidate_row.fact_type, 'active'
            ) RETURNING * INTO fact_row;
        END IF;
        SELECT coalesce(max(version_row.version_number), 0) + 1
        INTO next_fact_version
        FROM public.knowledge_fact_versions AS version_row
        WHERE version_row.fact_id = p_fact_id
          AND version_row.project_id = candidate_row.project_id;
        INSERT INTO public.knowledge_fact_versions (
            id, tenant_id, project_id, fact_id, version_number,
            base_version_id, base_statement_hash,
            source_candidate_id, statement, locale, statement_hash,
            authority_grade, valid_from, valid_until, customer_visible,
            public_disclosure_allowed, public_source_url, public_source_title,
            citation_label, quotation_allowed, attribution_required,
            approved_by, approved_at
        ) VALUES (
            p_fact_version_id, candidate_row.tenant_id, candidate_row.project_id,
            p_fact_id, next_fact_version,
            CASE WHEN next_fact_version > 1 THEN p_expected_current_version_id ELSE NULL END,
            CASE WHEN next_fact_version > 1 THEN p_base_statement_hash ELSE NULL END,
            candidate_row.id, candidate_row.statement,
            candidate_row.locale,
            encode(public.digest(candidate_row.statement, 'sha256'), 'hex'),
            snapshot_grade, snapshot_valid_from, snapshot_valid_until,
            coalesce(all_customer_visible,false), fact_public,
            CASE WHEN fact_public THEN snapshot_url ELSE NULL END,
            CASE WHEN fact_public THEN snapshot_title ELSE NULL END,
            CASE WHEN fact_public THEN snapshot_label ELSE NULL END,
            CASE WHEN fact_public THEN coalesce(all_quotation,false) ELSE false END,
            CASE WHEN fact_public THEN coalesce(any_attribution,false) ELSE false END,
            actor_id, review_time
        );
        INSERT INTO public.knowledge_fact_version_sources (
            tenant_id, project_id, fact_version_id, governance_version_id,
            chunk_id, block_id, table_id, source_revision_id,
            locator, source_snapshot_hash
        ) SELECT candidate_row.tenant_id, candidate_row.project_id,
                 p_fact_version_id, source_asset.current_governance_version_id,
                 source.chunk_id, source.block_id, source.table_id, source.source_revision_id,
                 source.locator, source.source_snapshot_hash
          FROM public.knowledge_fact_candidate_sources AS source
          LEFT JOIN public.knowledge_chunks AS chunk_row
            ON chunk_row.id = source.chunk_id AND chunk_row.project_id = source.project_id
          LEFT JOIN public.knowledge_blocks AS block_row
            ON block_row.id = source.block_id AND block_row.project_id = source.project_id
          LEFT JOIN public.knowledge_tables AS table_row
            ON table_row.id = source.table_id AND table_row.project_id = source.project_id
          JOIN public.knowledge_source_asset_revisions AS revision
            ON revision.id = coalesce(source.source_revision_id, chunk_row.source_revision_id,
                                      block_row.source_revision_id, table_row.source_revision_id)
           AND revision.project_id = source.project_id
          JOIN public.knowledge_source_assets AS source_asset
            ON source_asset.id = revision.source_asset_id
           AND source_asset.project_id = revision.project_id
          WHERE source.fact_candidate_id = candidate_row.id
            AND source.project_id = candidate_row.project_id;
        UPDATE public.knowledge_facts AS fact
        SET current_version_id = p_fact_version_id,
            updated_at = statement_timestamp()
        WHERE fact.id = p_fact_id AND fact.project_id = candidate_row.project_id;
    END IF;

    INSERT INTO public.knowledge_fact_candidate_reviews (
        id, tenant_id, project_id, fact_candidate_id,
        decision, reviewer_id, review_notes, created_at
    ) VALUES (
        p_review_id, candidate_row.tenant_id, candidate_row.project_id,
        candidate_row.id, p_decision, actor_id, nullif(btrim(p_notes), ''), review_time
    );
    UPDATE public.knowledge_fact_candidates AS candidate
    SET status = p_decision, reviewed_at = review_time,
        updated_at = statement_timestamp()
    WHERE candidate.id = candidate_row.id
    RETURNING candidate.* INTO candidate_row;
    PERFORM public.geno_v2_refresh_knowledge_pipeline_state(producer_row.pipeline_run_id);
    RETURN candidate_row;
END;
$review_knowledge_candidate$;

CREATE FUNCTION geno_v2_read_approved_knowledge(
    p_project_id uuid, p_publication_channel text DEFAULT NULL
)
RETURNS TABLE (
    fact_id uuid, fact_version_id uuid, subject_entity_id uuid,
    subject_role text, fact_type text, statement text, locale text,
    authority_grade text, valid_from timestamptz, valid_until timestamptz,
    customer_visible boolean, public_disclosure_allowed boolean,
    public_source_url text, public_source_title text, citation_label text,
    quotation_allowed boolean, attribution_required boolean
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $read_approved_knowledge$
DECLARE tenant_scope uuid; internal_consumer boolean;
BEGIN
    SELECT project.tenant_id INTO tenant_scope FROM public.projects AS project
    WHERE project.id = p_project_id AND project.status <> 'archived';
    IF NOT FOUND OR NOT public.geno_v2_session_has_project_permission(
        p_project_id, tenant_scope, 'knowledge.read_approved'
    ) THEN
        RAISE EXCEPTION 'approved knowledge is not accessible' USING ERRCODE = '42501';
    END IF;
    internal_consumer := public.geno_v2_session_has_project_permission(
        p_project_id, tenant_scope, 'knowledge.read'
    ) OR public.geno_v2_session_has_project_permission(
        p_project_id, tenant_scope, 'content.generate'
    );
    IF NOT internal_consumer
       AND (p_publication_channel IS NULL OR btrim(p_publication_channel) = '') THEN
        RAISE EXCEPTION 'customer approved knowledge requires a publication channel'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    SELECT fact.id, version_row.id, fact.subject_entity_id, fact.subject_role,
           fact.fact_type, version_row.statement, version_row.locale,
           CASE source_state.minimum_authority_rank
               WHEN 4 THEN 'A' WHEN 3 THEN 'B' WHEN 2 THEN 'C' ELSE 'D' END,
           source_state.current_valid_from, source_state.current_valid_until,
           source_state.all_customer_visible,
           source_state.safe_public_disclosure,
           CASE WHEN source_state.safe_public_disclosure
                THEN source_state.public_source_url ELSE NULL END,
           CASE WHEN source_state.safe_public_disclosure
                THEN source_state.public_source_title ELSE NULL END,
           CASE WHEN source_state.safe_public_disclosure
                THEN source_state.citation_label ELSE NULL END,
           CASE WHEN source_state.safe_public_disclosure
                THEN source_state.all_quotation_allowed ELSE false END,
           CASE WHEN source_state.safe_public_disclosure
                THEN source_state.any_attribution_required ELSE false END
    FROM public.knowledge_facts AS fact
    JOIN public.knowledge_fact_versions AS version_row
      ON version_row.id = fact.current_version_id
     AND version_row.project_id = fact.project_id
    JOIN LATERAL (
        SELECT count(*) AS source_count,
               min(current_governance.authority_rank) AS minimum_authority_rank,
               max(current_governance.valid_from) AS current_valid_from,
               min(current_governance.valid_until) AS current_valid_until,
               bool_and(current_governance.customer_visible) AS all_customer_visible,
               bool_and(current_governance.public_disclosure_allowed)
                 AND count(DISTINCT current_governance.public_source_url) = 1
                 AND count(DISTINCT current_governance.public_source_title) = 1
                 AND count(DISTINCT current_governance.citation_label) <= 1
                   AS safe_public_disclosure,
               min(current_governance.public_source_url) AS public_source_url,
               min(current_governance.public_source_title) AS public_source_title,
               min(current_governance.citation_label) AS citation_label,
               bool_and(current_governance.quotation_allowed)
                   AS all_quotation_allowed,
               bool_or(current_governance.attribution_required)
                   AS any_attribution_required,
               bool_and(
                   source_asset.status = 'active'
                   AND source_asset.current_revision_id = revision.id
                   AND revision.status = 'active'
                   AND revision_producer.status = 'succeeded'
                   AND snapshot_governance.source_revision_id = revision.id
                   AND current_governance.source_revision_id = revision.id
                   AND current_governance.authority_rank >= 2
                   AND current_governance.usage_rights_status IN
                       ('public_reuse','customer_authorised')
                   AND current_governance.confidentiality IN ('public','internal')
                   AND current_governance.consent_status IN ('not_required','granted')
                   AND (current_governance.consent_expires_at IS NULL
                        OR current_governance.consent_expires_at > statement_timestamp())
                   AND current_governance.external_model_use_allowed
                   AND current_governance.public_adaptation_allowed
                   AND current_governance.claim_risk <> 'prohibited'
                   AND current_governance.valid_from <= statement_timestamp()
                   AND (current_governance.valid_until IS NULL
                        OR current_governance.valid_until > statement_timestamp())
                   AND EXISTS (
                       SELECT 1
                       FROM public.knowledge_source_revision_artifacts AS link
                       JOIN public.evidence_assets AS artifact
                         ON artifact.id = link.evidence_asset_id
                        AND artifact.project_id = link.project_id
                       WHERE link.source_revision_id = revision.id
                         AND link.project_id = revision.project_id
                         AND artifact.artifact_status = 'finalized'
                   )
                   AND NOT EXISTS (
                       SELECT 1
                       FROM public.knowledge_source_revision_artifacts AS link
                       JOIN public.evidence_assets AS artifact
                         ON artifact.id = link.evidence_asset_id
                        AND artifact.project_id = link.project_id
                       WHERE link.source_revision_id = revision.id
                         AND link.project_id = revision.project_id
                         AND artifact.artifact_status <> 'finalized'
                   )
                   AND EXISTS (
                       SELECT 1
                       FROM public.knowledge_source_governance_channels AS channel
                       WHERE channel.governance_version_id = current_governance.id
                         AND channel.project_id = current_governance.project_id
                         AND channel.allowed
                         AND (p_publication_channel IS NULL
                              OR channel.publication_channel = p_publication_channel)
                   )
               ) AS all_currently_eligible
        FROM public.knowledge_fact_version_sources AS version_source
        LEFT JOIN public.knowledge_chunks AS chunk_row
          ON chunk_row.id = version_source.chunk_id
         AND chunk_row.project_id = version_source.project_id
        LEFT JOIN public.knowledge_blocks AS block_row
          ON block_row.id = version_source.block_id
         AND block_row.project_id = version_source.project_id
        LEFT JOIN public.knowledge_tables AS table_row
          ON table_row.id = version_source.table_id
         AND table_row.project_id = version_source.project_id
        JOIN public.knowledge_source_asset_revisions AS revision
          ON revision.id = coalesce(version_source.source_revision_id,
                                    chunk_row.source_revision_id,
                                    block_row.source_revision_id,
                                    table_row.source_revision_id)
         AND revision.project_id = version_source.project_id
        JOIN public.knowledge_pipeline_jobs AS revision_producer
          ON revision_producer.id = revision.knowledge_job_id
         AND revision_producer.project_id = revision.project_id
        JOIN public.knowledge_source_assets AS source_asset
          ON source_asset.id = revision.source_asset_id
         AND source_asset.project_id = revision.project_id
        JOIN public.knowledge_source_governance_versions AS snapshot_governance
          ON snapshot_governance.id = version_source.governance_version_id
         AND snapshot_governance.project_id = version_source.project_id
        JOIN public.knowledge_source_governance_versions AS current_governance
          ON current_governance.id = source_asset.current_governance_version_id
         AND current_governance.project_id = source_asset.project_id
        WHERE version_source.fact_version_id = version_row.id
          AND version_source.project_id = version_row.project_id
    ) AS source_state ON source_state.source_count > 0
                         AND source_state.all_currently_eligible
    WHERE fact.project_id = p_project_id AND fact.tenant_id = tenant_scope
      AND fact.status = 'active' AND version_row.valid_from <= statement_timestamp()
      AND (version_row.valid_until IS NULL OR version_row.valid_until > statement_timestamp())
      AND (internal_consumer OR (
          source_state.all_customer_visible
          AND source_state.safe_public_disclosure
      ));
END;
$read_approved_knowledge$;

CREATE FUNCTION geno_v2_validate_chunk_set_input_kind()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_chunk_set_input_kind$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.knowledge_pipeline_jobs AS job
        WHERE job.id = NEW.knowledge_job_id AND job.project_id = NEW.project_id
          AND job.job_type = NEW.input_kind
    ) THEN
        RAISE EXCEPTION 'chunk-set input kind must match its knowledge job'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$validate_chunk_set_input_kind$;

CREATE FUNCTION geno_v2_validate_job_quality_definition()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $validate_job_quality_definition$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.knowledge_pipeline_jobs AS job
        JOIN public.knowledge_quality_definitions AS definition
          ON definition.id = NEW.quality_definition_id
         AND definition.project_id = NEW.project_id
        WHERE job.id = NEW.knowledge_job_id AND job.project_id = NEW.project_id
          AND definition.job_type = job.job_type AND definition.active
    ) THEN
        RAISE EXCEPTION 'frozen quality definition does not match the knowledge job'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$validate_job_quality_definition$;

CREATE CONSTRAINT TRIGGER knowledge_import_subject_entity_kind
AFTER INSERT ON knowledge_import_source_subjects DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_subject();
CREATE CONSTRAINT TRIGGER knowledge_parse_input_job_type
AFTER INSERT ON knowledge_parse_job_inputs DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_knowledge_job_result_type('parse');
CREATE CONSTRAINT TRIGGER knowledge_chunk_set_input_job_type
AFTER INSERT ON knowledge_chunk_set_job_inputs DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_chunk_set_input_kind();
CREATE CONSTRAINT TRIGGER knowledge_job_quality_definition_type
AFTER INSERT ON knowledge_job_quality_definitions DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION geno_v2_validate_job_quality_definition();

DO $knowledge_more_immutable_triggers$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'knowledge_import_sources', 'knowledge_import_source_subjects',
        'knowledge_import_source_channels', 'knowledge_pipeline_job_dependencies',
        'knowledge_job_artifacts', 'knowledge_chunk_job_inputs',
        'knowledge_parse_job_inputs', 'knowledge_chunk_set_job_inputs',
        'knowledge_job_input_snapshots',
        'knowledge_quality_definitions', 'knowledge_job_quality_definitions',
        'knowledge_source_governance_channels'
    ] LOOP
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.geno_v2_reject_knowledge_immutable_update()',
            table_name || '_immutable', table_name
        );
    END LOOP;
END;
$knowledge_more_immutable_triggers$;

CREATE INDEX knowledge_jobs_claim_idx
    ON knowledge_pipeline_jobs (priority DESC, next_attempt_at, created_at, id)
    WHERE status IN ('queued','running','finalizing');
CREATE INDEX knowledge_jobs_expired_lease_idx
    ON knowledge_pipeline_jobs (lease_expires_at, id)
    WHERE status IN ('running','finalizing');
CREATE INDEX knowledge_jobs_run_stage_idx
    ON knowledge_pipeline_jobs (pipeline_run_id, pipeline_stage_id, created_at, id);
CREATE INDEX knowledge_revisions_asset_idx
    ON knowledge_source_asset_revisions (source_asset_id, revision_number DESC);
CREATE INDEX knowledge_chunks_revision_idx
    ON knowledge_chunks (source_revision_id, status, chunk_index);
CREATE INDEX knowledge_candidates_review_idx
    ON knowledge_fact_candidates (project_id, status, created_at, id);
CREATE INDEX knowledge_facts_subject_idx
    ON knowledge_facts (project_id, subject_role, subject_entity_id, status);

DO $knowledge_rls$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'knowledge_pipeline_runs', 'knowledge_pipeline_stages',
        'knowledge_import_sources', 'knowledge_import_source_subjects',
        'knowledge_import_source_channels', 'knowledge_pipeline_jobs',
        'knowledge_pipeline_job_dependencies', 'knowledge_job_artifacts',
        'knowledge_source_assets', 'knowledge_source_asset_revisions',
        'knowledge_source_governance_versions',
        'knowledge_source_governance_channels', 'knowledge_source_channels',
        'knowledge_source_subjects', 'knowledge_source_revision_artifacts',
        'knowledge_parser_runs', 'knowledge_parser_artifacts',
        'knowledge_blocks', 'knowledge_tables', 'knowledge_ocr_spans',
        'knowledge_pages', 'knowledge_chunks', 'knowledge_chunk_blocks',
        'knowledge_chunk_tables', 'knowledge_chunk_subjects',
        'knowledge_chunk_embeddings', 'knowledge_chunk_job_inputs',
        'knowledge_parse_job_inputs', 'knowledge_chunk_set_job_inputs',
        'knowledge_job_input_snapshots',
        'knowledge_fact_candidates', 'knowledge_fact_candidate_sources',
        'knowledge_fact_candidate_reviews', 'knowledge_facts',
        'knowledge_fact_versions', 'knowledge_fact_version_sources',
        'knowledge_quality_definitions', 'knowledge_job_quality_definitions',
        'knowledge_quality_runs', 'knowledge_quality_findings',
        'knowledge_risk_acceptances'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR SELECT TO geno_v2_runtime '
            'USING (public.geno_v2_session_has_project_permission('
            'project_id, tenant_id, ''knowledge.read''))',
            table_name || '_runtime_internal_read', table_name
        );
    END LOOP;
END;
$knowledge_rls$;

ALTER FUNCTION geno_v2_persist_knowledge_job_result(knowledge_pipeline_jobs, jsonb)
    OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_claim_knowledge_job(text, integer, uuid, text)
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_heartbeat_knowledge_job(uuid, text, uuid, integer)
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_begin_finalizing_knowledge_job(uuid, text, uuid, text, jsonb)
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_complete_knowledge_job(uuid, text, uuid)
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_fail_knowledge_job(uuid, text, uuid, text, text, boolean, integer)
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_ack_knowledge_job_cancel(uuid, text, uuid)
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_knowledge_job_inputs_ready(uuid) OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_require_ready_knowledge_job_inputs()
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_read_knowledge_job_input(uuid, text, uuid)
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_knowledge_quality_certificate_complete(uuid)
    OWNER TO geno_v2_job_owner;
ALTER FUNCTION geno_v2_refresh_knowledge_pipeline_state(uuid)
    OWNER TO geno_v2_job_owner;

ALTER FUNCTION geno_v2_create_knowledge_quality_definition(
    uuid, uuid, text, integer, text, text, text, jsonb
) OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_create_knowledge_governance_version(
    uuid, uuid, uuid, jsonb, text
) OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_set_knowledge_source_status(uuid, text, text)
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_withdraw_knowledge_fact(uuid, text)
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_create_knowledge_job(
    uuid, uuid, uuid, uuid, uuid, text, text, jsonb, uuid
) OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_request_knowledge_job_cancel(uuid, text)
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_replay_knowledge_job(uuid, uuid, text)
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_retry_knowledge_pipeline_stage(uuid, uuid, text)
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_accept_knowledge_risk(uuid, uuid, text)
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_review_knowledge_fact_candidate(
    uuid, uuid, uuid, uuid, text, text, uuid, text
) OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_read_approved_knowledge(uuid, text) OWNER TO geno_v2_authz_owner;

ALTER FUNCTION geno_v2_guard_knowledge_asset_head() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_reject_knowledge_immutable_update()
    OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_reject_knowledge_immutable_update() SECURITY DEFINER;
ALTER FUNCTION geno_v2_guard_candidate_transition()
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_guard_candidate_transition() SECURITY DEFINER;
ALTER FUNCTION geno_v2_guard_fact_head() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_require_finalized_knowledge_artifact() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_require_finalized_parser_input() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_validate_knowledge_subject() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_validate_knowledge_job_result_type() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_validate_knowledge_revision_job_type() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_validate_knowledge_job_stage()
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_validate_chunk_set_input_kind() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_validate_job_quality_definition() OWNER TO geno_v2_result_owner;
ALTER FUNCTION geno_v2_guard_knowledge_risk_acceptance()
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_validate_candidate_review_consistency()
    OWNER TO geno_v2_job_command_owner;
ALTER FUNCTION geno_v2_validate_fact_source_governance_lineage()
    OWNER TO geno_v2_result_owner;

DO $knowledge_revoke_function_public$
DECLARE function_row record;
BEGIN
    FOR function_row IN
        SELECT procedure.oid::regprocedure AS signature
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'public'
          AND procedure.proname = ANY(ARRAY[
              'geno_v2_persist_knowledge_job_result',
              'geno_v2_claim_knowledge_job', 'geno_v2_heartbeat_knowledge_job',
              'geno_v2_begin_finalizing_knowledge_job', 'geno_v2_complete_knowledge_job',
              'geno_v2_fail_knowledge_job', 'geno_v2_ack_knowledge_job_cancel',
              'geno_v2_read_knowledge_job_input',
              'geno_v2_knowledge_quality_certificate_complete',
              'geno_v2_refresh_knowledge_pipeline_state',
              'geno_v2_create_knowledge_quality_definition',
              'geno_v2_create_knowledge_governance_version',
              'geno_v2_set_knowledge_source_status',
              'geno_v2_withdraw_knowledge_fact',
              'geno_v2_create_knowledge_job', 'geno_v2_request_knowledge_job_cancel',
              'geno_v2_replay_knowledge_job', 'geno_v2_retry_knowledge_pipeline_stage',
              'geno_v2_accept_knowledge_risk',
              'geno_v2_review_knowledge_fact_candidate',
              'geno_v2_read_approved_knowledge',
              'geno_v2_reject_knowledge_immutable_update',
              'geno_v2_guard_knowledge_asset_head',
              'geno_v2_guard_candidate_transition', 'geno_v2_guard_fact_head',
              'geno_v2_require_finalized_knowledge_artifact',
              'geno_v2_require_finalized_parser_input',
              'geno_v2_validate_knowledge_subject',
              'geno_v2_validate_knowledge_job_result_type',
              'geno_v2_validate_knowledge_revision_job_type',
              'geno_v2_validate_knowledge_job_stage',
              'geno_v2_knowledge_job_inputs_ready',
              'geno_v2_require_ready_knowledge_job_inputs',
              'geno_v2_guard_knowledge_risk_acceptance',
              'geno_v2_validate_candidate_review_consistency',
              'geno_v2_validate_fact_source_governance_lineage',
              'geno_v2_validate_chunk_set_input_kind',
              'geno_v2_validate_job_quality_definition'
          ])
    LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', function_row.signature);
    END LOOP;
END;
$knowledge_revoke_function_public$;

REVOKE ALL ON
    knowledge_pipeline_runs, knowledge_pipeline_stages,
    knowledge_import_sources, knowledge_import_source_subjects,
    knowledge_import_source_channels, knowledge_pipeline_jobs,
    knowledge_pipeline_job_dependencies, knowledge_job_artifacts,
    knowledge_source_assets, knowledge_source_asset_revisions,
    knowledge_source_governance_versions, knowledge_source_governance_channels,
    knowledge_source_channels, knowledge_source_subjects,
    knowledge_source_revision_artifacts, knowledge_parser_runs,
    knowledge_parser_artifacts, knowledge_blocks, knowledge_tables,
    knowledge_ocr_spans, knowledge_pages, knowledge_chunks,
    knowledge_chunk_blocks, knowledge_chunk_tables, knowledge_chunk_subjects,
    knowledge_chunk_embeddings, knowledge_chunk_job_inputs,
    knowledge_parse_job_inputs, knowledge_chunk_set_job_inputs,
    knowledge_job_input_snapshots,
    knowledge_fact_candidates, knowledge_fact_candidate_sources,
    knowledge_fact_candidate_reviews, knowledge_facts, knowledge_fact_versions,
    knowledge_fact_version_sources, knowledge_quality_definitions,
    knowledge_job_quality_definitions, knowledge_quality_runs,
    knowledge_quality_findings, knowledge_risk_acceptances
FROM PUBLIC, geno_v2_runtime, geno_v2_worker;

GRANT SELECT ON
    knowledge_pipeline_jobs, knowledge_import_sources,
    knowledge_import_source_subjects, knowledge_import_source_channels,
    knowledge_job_artifacts, knowledge_source_assets,
    knowledge_source_asset_revisions, knowledge_source_governance_versions,
    knowledge_source_revision_artifacts, knowledge_parser_runs,
    knowledge_parser_artifacts, knowledge_blocks, knowledge_tables,
    knowledge_pages, knowledge_chunks, knowledge_chunk_job_inputs,
    knowledge_parse_job_inputs, knowledge_chunk_set_job_inputs,
    knowledge_job_input_snapshots,
    knowledge_fact_candidates, knowledge_fact_versions,
    knowledge_job_quality_definitions,
    knowledge_quality_definitions, knowledge_quality_runs,
    knowledge_quality_findings, evidence_assets, product_entities
TO geno_v2_result_owner;

GRANT SELECT ON
    knowledge_pipeline_jobs, knowledge_pipeline_job_dependencies,
    knowledge_pipeline_stages, knowledge_pipeline_runs,
    knowledge_import_sources, knowledge_job_artifacts,
    knowledge_source_assets, knowledge_source_asset_revisions,
    knowledge_source_governance_versions, knowledge_source_revision_artifacts,
    knowledge_parser_runs, knowledge_parser_artifacts, knowledge_pages,
    knowledge_chunks, knowledge_chunk_set_job_inputs,
    knowledge_chunk_job_inputs, knowledge_parse_job_inputs,
    knowledge_job_input_snapshots,
    knowledge_job_quality_definitions, knowledge_quality_runs,
    knowledge_quality_definitions, knowledge_quality_findings,
    knowledge_risk_acceptances, knowledge_fact_candidates,
    evidence_assets
TO geno_v2_job_owner;

GRANT SELECT ON
    projects, knowledge_pipeline_runs, knowledge_pipeline_stages,
    knowledge_pipeline_jobs, knowledge_pipeline_job_dependencies,
    knowledge_job_artifacts,
    knowledge_import_sources, knowledge_import_source_subjects,
    knowledge_import_source_channels, knowledge_chunk_job_inputs,
    knowledge_parse_job_inputs, knowledge_chunk_set_job_inputs,
    knowledge_job_input_snapshots,
    knowledge_quality_definitions, knowledge_job_quality_definitions,
    knowledge_quality_runs, knowledge_quality_findings,
    knowledge_risk_acceptances, knowledge_fact_candidates,
    knowledge_fact_candidate_sources, knowledge_fact_candidate_reviews,
    knowledge_facts, knowledge_fact_versions, knowledge_fact_version_sources,
    knowledge_chunks, knowledge_blocks, knowledge_tables,
    knowledge_source_assets, knowledge_source_asset_revisions,
    knowledge_source_governance_versions, knowledge_source_governance_channels,
    knowledge_source_revision_artifacts, knowledge_source_subjects,
    evidence_assets
TO geno_v2_job_command_owner;

GRANT INSERT ON
    knowledge_job_artifacts, knowledge_source_assets,
    knowledge_source_asset_revisions, knowledge_source_governance_versions,
    knowledge_source_governance_channels, knowledge_source_channels,
    knowledge_source_subjects, knowledge_source_revision_artifacts,
    knowledge_parser_runs, knowledge_parser_artifacts, knowledge_blocks,
    knowledge_tables, knowledge_ocr_spans, knowledge_pages, knowledge_chunks,
    knowledge_chunk_blocks, knowledge_chunk_tables, knowledge_chunk_subjects,
    knowledge_chunk_embeddings, knowledge_fact_candidates,
    knowledge_fact_candidate_sources, knowledge_quality_runs,
    knowledge_quality_findings
TO geno_v2_result_owner;
GRANT UPDATE ON knowledge_source_assets TO geno_v2_result_owner;

GRANT SELECT, UPDATE ON
    knowledge_pipeline_jobs, knowledge_pipeline_stages, knowledge_pipeline_runs
TO geno_v2_job_owner;

GRANT INSERT ON
    knowledge_pipeline_runs, knowledge_pipeline_stages,
    knowledge_import_sources, knowledge_import_source_subjects,
    knowledge_import_source_channels, knowledge_pipeline_jobs,
    knowledge_pipeline_job_dependencies, knowledge_chunk_job_inputs,
    knowledge_parse_job_inputs, knowledge_chunk_set_job_inputs,
    knowledge_job_input_snapshots,
    knowledge_quality_definitions, knowledge_job_quality_definitions,
    knowledge_source_governance_versions,
    knowledge_source_governance_channels,
    knowledge_risk_acceptances, knowledge_fact_candidate_reviews,
    knowledge_facts, knowledge_fact_versions, knowledge_fact_version_sources,
    evidence_assets, artifact_finalize_outbox, audit_events
TO geno_v2_job_command_owner;
GRANT UPDATE ON
    knowledge_pipeline_runs, knowledge_pipeline_stages,
    knowledge_pipeline_jobs, knowledge_source_assets,
    knowledge_fact_candidates, knowledge_facts
TO geno_v2_job_command_owner;

GRANT SELECT ON knowledge_facts, knowledge_fact_versions,
    knowledge_fact_version_sources, knowledge_chunks, knowledge_blocks,
    knowledge_tables, knowledge_source_asset_revisions,
    knowledge_source_assets, knowledge_source_governance_versions,
    knowledge_source_governance_channels, knowledge_source_revision_artifacts,
    knowledge_pipeline_jobs, evidence_assets
TO geno_v2_authz_owner;

GRANT EXECUTE ON FUNCTION digest(text, text)
    TO geno_v2_job_owner, geno_v2_job_command_owner;

GRANT EXECUTE ON FUNCTION geno_v2_persist_knowledge_job_result(
    knowledge_pipeline_jobs, jsonb
) TO geno_v2_job_owner;
GRANT EXECUTE ON FUNCTION geno_v2_claim_knowledge_job(text, integer, uuid, text)
    TO geno_v2_worker;
GRANT EXECUTE ON FUNCTION geno_v2_heartbeat_knowledge_job(uuid, text, uuid, integer)
    TO geno_v2_worker;
GRANT EXECUTE ON FUNCTION geno_v2_begin_finalizing_knowledge_job(
    uuid, text, uuid, text, jsonb
) TO geno_v2_worker;
GRANT EXECUTE ON FUNCTION geno_v2_complete_knowledge_job(uuid, text, uuid)
    TO geno_v2_worker;
GRANT EXECUTE ON FUNCTION geno_v2_fail_knowledge_job(
    uuid, text, uuid, text, text, boolean, integer
) TO geno_v2_worker;
GRANT EXECUTE ON FUNCTION geno_v2_ack_knowledge_job_cancel(uuid, text, uuid)
    TO geno_v2_worker;
GRANT EXECUTE ON FUNCTION geno_v2_read_knowledge_job_input(uuid, text, uuid)
    TO geno_v2_worker;
GRANT EXECUTE ON FUNCTION geno_v2_knowledge_quality_certificate_complete(uuid)
    TO geno_v2_job_command_owner;
GRANT EXECUTE ON FUNCTION geno_v2_refresh_knowledge_pipeline_state(uuid)
    TO geno_v2_job_command_owner;

GRANT EXECUTE ON FUNCTION geno_v2_create_knowledge_quality_definition(
    uuid, uuid, text, integer, text, text, text, jsonb
) TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_create_knowledge_governance_version(
    uuid, uuid, uuid, jsonb, text
) TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_set_knowledge_source_status(uuid, text, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_withdraw_knowledge_fact(uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_create_knowledge_job(
    uuid, uuid, uuid, uuid, uuid, text, text, jsonb, uuid
) TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_request_knowledge_job_cancel(uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_replay_knowledge_job(uuid, uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_retry_knowledge_pipeline_stage(uuid, uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_accept_knowledge_risk(uuid, uuid, text)
    TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_review_knowledge_fact_candidate(
    uuid, uuid, uuid, uuid, text, text, uuid, text
) TO geno_v2_runtime;
GRANT EXECUTE ON FUNCTION geno_v2_read_approved_knowledge(uuid, text)
    TO geno_v2_runtime;

DO $verify_knowledge_function_boundary$
DECLARE
    procedure_row record;
    expected_owner text;
    expected_names text[] := ARRAY[
        'geno_v2_enqueue_durable_job_dispatch',
        'geno_v2_reject_knowledge_immutable_update',
        'geno_v2_guard_knowledge_asset_head',
        'geno_v2_guard_candidate_transition', 'geno_v2_guard_fact_head',
        'geno_v2_require_finalized_knowledge_artifact',
        'geno_v2_require_finalized_parser_input',
        'geno_v2_validate_knowledge_subject',
        'geno_v2_validate_knowledge_job_result_type',
        'geno_v2_validate_knowledge_revision_job_type',
        'geno_v2_validate_knowledge_job_stage',
        'geno_v2_knowledge_job_inputs_ready',
        'geno_v2_require_ready_knowledge_job_inputs',
        'geno_v2_read_knowledge_job_input',
        'geno_v2_persist_knowledge_job_result',
        'geno_v2_claim_knowledge_job', 'geno_v2_heartbeat_knowledge_job',
        'geno_v2_begin_finalizing_knowledge_job',
        'geno_v2_knowledge_quality_certificate_complete',
        'geno_v2_refresh_knowledge_pipeline_state',
        'geno_v2_complete_knowledge_job', 'geno_v2_fail_knowledge_job',
        'geno_v2_ack_knowledge_job_cancel',
        'geno_v2_create_knowledge_quality_definition',
        'geno_v2_create_knowledge_governance_version',
        'geno_v2_set_knowledge_source_status',
        'geno_v2_withdraw_knowledge_fact',
        'geno_v2_create_knowledge_job',
        'geno_v2_request_knowledge_job_cancel',
        'geno_v2_replay_knowledge_job',
        'geno_v2_retry_knowledge_pipeline_stage',
        'geno_v2_guard_knowledge_risk_acceptance',
        'geno_v2_accept_knowledge_risk',
        'geno_v2_validate_candidate_review_consistency',
        'geno_v2_validate_fact_source_governance_lineage',
        'geno_v2_review_knowledge_fact_candidate',
        'geno_v2_read_approved_knowledge',
        'geno_v2_validate_chunk_set_input_kind',
        'geno_v2_validate_job_quality_definition'
    ];
    runtime_entrypoints text[] := ARRAY[
        'geno_v2_create_knowledge_quality_definition',
        'geno_v2_create_knowledge_governance_version',
        'geno_v2_set_knowledge_source_status',
        'geno_v2_withdraw_knowledge_fact',
        'geno_v2_create_knowledge_job',
        'geno_v2_request_knowledge_job_cancel',
        'geno_v2_replay_knowledge_job',
        'geno_v2_retry_knowledge_pipeline_stage',
        'geno_v2_accept_knowledge_risk',
        'geno_v2_review_knowledge_fact_candidate',
        'geno_v2_read_approved_knowledge'
    ];
    worker_entrypoints text[] := ARRAY[
        'geno_v2_claim_knowledge_job', 'geno_v2_heartbeat_knowledge_job',
        'geno_v2_begin_finalizing_knowledge_job',
        'geno_v2_complete_knowledge_job', 'geno_v2_fail_knowledge_job',
        'geno_v2_ack_knowledge_job_cancel',
        'geno_v2_read_knowledge_job_input'
    ];
BEGIN
    IF (
        SELECT count(*) FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'public'
          AND procedure.proname = ANY(expected_names)
    ) <> cardinality(expected_names) THEN
        RAISE EXCEPTION 'Schema v2 Knowledge function signature set drifted';
    END IF;
    FOR procedure_row IN
        SELECT procedure.*, owner_role.rolname AS owner_name
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = procedure.proowner
        WHERE namespace.nspname = 'public'
          AND procedure.proname = ANY(expected_names)
    LOOP
        expected_owner := CASE
            WHEN procedure_row.proname = 'geno_v2_read_approved_knowledge'
                THEN 'geno_v2_authz_owner'
            WHEN procedure_row.proname = ANY(ARRAY[
                'geno_v2_claim_knowledge_job', 'geno_v2_heartbeat_knowledge_job',
                'geno_v2_begin_finalizing_knowledge_job',
                'geno_v2_knowledge_quality_certificate_complete',
                'geno_v2_refresh_knowledge_pipeline_state',
                'geno_v2_complete_knowledge_job', 'geno_v2_fail_knowledge_job',
                'geno_v2_ack_knowledge_job_cancel',
                'geno_v2_knowledge_job_inputs_ready',
                'geno_v2_require_ready_knowledge_job_inputs',
                'geno_v2_read_knowledge_job_input'
            ]) THEN 'geno_v2_job_owner'
            WHEN procedure_row.proname = ANY(ARRAY[
                'geno_v2_persist_knowledge_job_result',
                'geno_v2_reject_knowledge_immutable_update',
                'geno_v2_guard_knowledge_asset_head', 'geno_v2_guard_fact_head',
                'geno_v2_require_finalized_knowledge_artifact',
                'geno_v2_require_finalized_parser_input',
                'geno_v2_validate_knowledge_subject',
                'geno_v2_validate_knowledge_job_result_type',
                'geno_v2_validate_knowledge_revision_job_type',
                'geno_v2_validate_chunk_set_input_kind',
                'geno_v2_validate_job_quality_definition',
                'geno_v2_validate_fact_source_governance_lineage'
            ]) THEN 'geno_v2_result_owner'
            ELSE 'geno_v2_job_command_owner'
        END;
        IF procedure_row.owner_name <> expected_owner
           OR NOT procedure_row.prosecdef
           OR procedure_row.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[] THEN
            RAISE EXCEPTION 'Knowledge function % owner/security/search_path drifted',
                procedure_row.oid::regprocedure;
        END IF;
        IF has_function_privilege(
            'geno_v2_runtime', procedure_row.oid, 'EXECUTE'
        ) IS DISTINCT FROM (procedure_row.proname = ANY(runtime_entrypoints))
           OR has_function_privilege(
               'geno_v2_worker', procedure_row.oid, 'EXECUTE'
           ) IS DISTINCT FROM (procedure_row.proname = ANY(worker_entrypoints)) THEN
            RAISE EXCEPTION 'Knowledge function % runtime/worker ACL drifted',
                procedure_row.oid::regprocedure;
        END IF;
        IF EXISTS (
            SELECT 1
            FROM aclexplode(coalesce(
                procedure_row.proacl,
                acldefault('f', procedure_row.proowner)
            )) AS acl
            LEFT JOIN pg_catalog.pg_roles AS grantee_role
              ON grantee_role.oid = acl.grantee
            WHERE acl.privilege_type = 'EXECUTE'
              AND acl.grantee <> procedure_row.proowner
              AND NOT (
                  grantee_role.rolname = 'geno_v2_runtime'
                  AND procedure_row.proname = ANY(runtime_entrypoints)
              )
              AND NOT (
                  grantee_role.rolname = 'geno_v2_worker'
                  AND procedure_row.proname = ANY(worker_entrypoints)
              )
              AND NOT (
                  grantee_role.rolname = 'geno_v2_job_owner'
                  AND procedure_row.proname = 'geno_v2_persist_knowledge_job_result'
              )
              AND NOT (
                  grantee_role.rolname = 'geno_v2_job_command_owner'
                  AND procedure_row.proname = ANY(ARRAY[
                      'geno_v2_knowledge_quality_certificate_complete',
                      'geno_v2_refresh_knowledge_pipeline_state'
                  ])
              )
        ) THEN
            RAISE EXCEPTION 'Knowledge function % has an unexpected EXECUTE grantee',
                procedure_row.oid::regprocedure;
        END IF;
    END LOOP;
END;
$verify_knowledge_function_boundary$;

DO $verify_knowledge_owner_role_isolation$
DECLARE owner_role_names text[] := ARRAY[
    'geno_v2_job_owner', 'geno_v2_result_owner',
    'geno_v2_job_command_owner', 'geno_v2_authz_owner'
];
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles AS role_row
        WHERE role_row.rolname = ANY(owner_role_names)
          AND (role_row.rolcanlogin OR role_row.rolsuper
               OR role_row.rolcreaterole OR role_row.rolcreatedb)
    ) OR (
        SELECT count(*) FROM pg_catalog.pg_roles AS role_row
        WHERE role_row.rolname = ANY(owner_role_names)
    ) <> cardinality(owner_role_names) THEN
        RAISE EXCEPTION 'Schema v2 Knowledge owner role attributes drifted';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        WHERE granted_role.rolname = ANY(owner_role_names)
           OR member_role.rolname = ANY(owner_role_names)
    ) THEN
        RAISE EXCEPTION 'Schema v2 job roles must have no role memberships';
    END IF;
END;
$verify_knowledge_owner_role_isolation$;

DO $verify_knowledge_security_boundary$
DECLARE table_name text; privilege_name text;
    domain_tables text[] := ARRAY[
        'knowledge_pipeline_runs', 'knowledge_pipeline_stages',
        'knowledge_import_sources', 'knowledge_import_source_subjects',
        'knowledge_import_source_channels', 'knowledge_pipeline_jobs',
        'knowledge_pipeline_job_dependencies', 'knowledge_job_artifacts',
        'knowledge_source_assets', 'knowledge_source_asset_revisions',
        'knowledge_source_governance_versions',
        'knowledge_source_governance_channels', 'knowledge_source_channels',
        'knowledge_source_subjects', 'knowledge_source_revision_artifacts',
        'knowledge_parser_runs', 'knowledge_parser_artifacts',
        'knowledge_blocks', 'knowledge_tables', 'knowledge_ocr_spans',
        'knowledge_pages', 'knowledge_chunks', 'knowledge_chunk_blocks',
        'knowledge_chunk_tables', 'knowledge_chunk_subjects',
        'knowledge_chunk_embeddings', 'knowledge_chunk_job_inputs',
        'knowledge_parse_job_inputs', 'knowledge_chunk_set_job_inputs',
        'knowledge_job_input_snapshots',
        'knowledge_fact_candidates', 'knowledge_fact_candidate_sources',
        'knowledge_fact_candidate_reviews', 'knowledge_facts',
        'knowledge_fact_versions', 'knowledge_fact_version_sources',
        'knowledge_quality_definitions', 'knowledge_job_quality_definitions',
        'knowledge_quality_runs', 'knowledge_quality_findings',
        'knowledge_risk_acceptances'
    ];
BEGIN
    FOREACH table_name IN ARRAY domain_tables LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public' AND relation.relname = table_name
              AND relation.relrowsecurity AND relation.relforcerowsecurity
        ) THEN
            RAISE EXCEPTION 'knowledge table % is missing FORCE RLS', table_name;
        END IF;
        FOREACH privilege_name IN ARRAY ARRAY['SELECT','INSERT','UPDATE','DELETE'] LOOP
            IF has_table_privilege(
                'geno_v2_runtime', format('public.%I', table_name), privilege_name
            ) OR has_table_privilege(
                'geno_v2_worker', format('public.%I', table_name), privilege_name
            ) THEN
                RAISE EXCEPTION 'runtime or worker has forbidden % on %', privilege_name, table_name;
            END IF;
        END LOOP;
    END LOOP;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        CROSS JOIN LATERAL aclexplode(
            coalesce(procedure.proacl, acldefault('f', procedure.proowner))
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND procedure.proname LIKE 'geno_v2_%knowledge%'
          AND acl.grantee = 0 AND acl.privilege_type = 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'PUBLIC can execute a Schema v2 Knowledge function';
    END IF;
END;
$verify_knowledge_security_boundary$;

DO $verify_knowledge_exact_owner_acls$
DECLARE
    table_name text;
    role_name text;
    privilege_name text;
    expected boolean;
    domain_tables text[] := ARRAY[
        'knowledge_pipeline_runs', 'knowledge_pipeline_stages',
        'knowledge_import_sources', 'knowledge_import_source_subjects',
        'knowledge_import_source_channels', 'knowledge_pipeline_jobs',
        'knowledge_pipeline_job_dependencies', 'knowledge_job_artifacts',
        'knowledge_source_assets', 'knowledge_source_asset_revisions',
        'knowledge_source_governance_versions',
        'knowledge_source_governance_channels', 'knowledge_source_channels',
        'knowledge_source_subjects', 'knowledge_source_revision_artifacts',
        'knowledge_parser_runs', 'knowledge_parser_artifacts',
        'knowledge_blocks', 'knowledge_tables', 'knowledge_ocr_spans',
        'knowledge_pages', 'knowledge_chunks', 'knowledge_chunk_blocks',
        'knowledge_chunk_tables', 'knowledge_chunk_subjects',
        'knowledge_chunk_embeddings', 'knowledge_chunk_job_inputs',
        'knowledge_parse_job_inputs', 'knowledge_chunk_set_job_inputs',
        'knowledge_job_input_snapshots',
        'knowledge_fact_candidates', 'knowledge_fact_candidate_sources',
        'knowledge_fact_candidate_reviews', 'knowledge_facts',
        'knowledge_fact_versions', 'knowledge_fact_version_sources',
        'knowledge_quality_definitions', 'knowledge_job_quality_definitions',
        'knowledge_quality_runs', 'knowledge_quality_findings',
        'knowledge_risk_acceptances'
    ];
    result_select text[] := ARRAY[
        'knowledge_pipeline_jobs', 'knowledge_import_sources',
        'knowledge_import_source_subjects', 'knowledge_import_source_channels',
        'knowledge_job_artifacts', 'knowledge_source_assets',
        'knowledge_source_asset_revisions', 'knowledge_source_governance_versions',
        'knowledge_source_revision_artifacts', 'knowledge_parser_runs',
        'knowledge_parser_artifacts', 'knowledge_blocks', 'knowledge_tables',
        'knowledge_pages', 'knowledge_chunks', 'knowledge_chunk_job_inputs',
        'knowledge_parse_job_inputs', 'knowledge_chunk_set_job_inputs',
        'knowledge_job_input_snapshots',
        'knowledge_fact_candidates', 'knowledge_fact_versions',
        'knowledge_job_quality_definitions', 'knowledge_quality_definitions',
        'knowledge_quality_runs', 'knowledge_quality_findings'
    ];
    result_insert text[] := ARRAY[
        'knowledge_job_artifacts', 'knowledge_source_assets',
        'knowledge_source_asset_revisions', 'knowledge_source_governance_versions',
        'knowledge_source_governance_channels', 'knowledge_source_channels',
        'knowledge_source_subjects', 'knowledge_source_revision_artifacts',
        'knowledge_parser_runs', 'knowledge_parser_artifacts',
        'knowledge_blocks', 'knowledge_tables', 'knowledge_ocr_spans',
        'knowledge_pages', 'knowledge_chunks', 'knowledge_chunk_blocks',
        'knowledge_chunk_tables', 'knowledge_chunk_subjects',
        'knowledge_chunk_embeddings', 'knowledge_fact_candidates',
        'knowledge_fact_candidate_sources', 'knowledge_quality_runs',
        'knowledge_quality_findings'
    ];
    job_select text[] := ARRAY[
        'knowledge_pipeline_jobs', 'knowledge_pipeline_job_dependencies',
        'knowledge_pipeline_stages', 'knowledge_pipeline_runs',
        'knowledge_import_sources', 'knowledge_job_artifacts',
        'knowledge_source_assets', 'knowledge_source_asset_revisions',
        'knowledge_source_governance_versions',
        'knowledge_source_revision_artifacts', 'knowledge_parser_runs',
        'knowledge_parser_artifacts', 'knowledge_pages',
        'knowledge_chunks', 'knowledge_chunk_set_job_inputs',
        'knowledge_chunk_job_inputs', 'knowledge_parse_job_inputs',
        'knowledge_job_input_snapshots',
        'knowledge_job_quality_definitions', 'knowledge_quality_definitions',
        'knowledge_quality_runs', 'knowledge_quality_findings',
        'knowledge_risk_acceptances', 'knowledge_fact_candidates'
    ];
    command_select text[] := ARRAY[
        'knowledge_pipeline_runs', 'knowledge_pipeline_stages',
        'knowledge_pipeline_jobs', 'knowledge_pipeline_job_dependencies',
        'knowledge_job_artifacts',
        'knowledge_import_sources', 'knowledge_import_source_subjects',
        'knowledge_import_source_channels', 'knowledge_chunk_job_inputs',
        'knowledge_parse_job_inputs', 'knowledge_chunk_set_job_inputs',
        'knowledge_job_input_snapshots',
        'knowledge_quality_definitions', 'knowledge_job_quality_definitions',
        'knowledge_source_governance_versions',
        'knowledge_source_governance_channels',
        'knowledge_quality_runs', 'knowledge_quality_findings',
        'knowledge_risk_acceptances', 'knowledge_fact_candidates',
        'knowledge_fact_candidate_sources', 'knowledge_fact_candidate_reviews',
        'knowledge_facts', 'knowledge_fact_versions',
        'knowledge_fact_version_sources', 'knowledge_chunks',
        'knowledge_blocks', 'knowledge_tables', 'knowledge_source_assets',
        'knowledge_source_asset_revisions',
        'knowledge_source_governance_versions',
        'knowledge_source_governance_channels',
        'knowledge_source_revision_artifacts', 'knowledge_source_subjects'
    ];
    command_insert text[] := ARRAY[
        'knowledge_pipeline_runs', 'knowledge_pipeline_stages',
        'knowledge_import_sources', 'knowledge_import_source_subjects',
        'knowledge_import_source_channels', 'knowledge_pipeline_jobs',
        'knowledge_pipeline_job_dependencies', 'knowledge_chunk_job_inputs',
        'knowledge_parse_job_inputs', 'knowledge_chunk_set_job_inputs',
        'knowledge_job_input_snapshots',
        'knowledge_quality_definitions', 'knowledge_job_quality_definitions',
        'knowledge_source_governance_versions',
        'knowledge_source_governance_channels',
        'knowledge_risk_acceptances', 'knowledge_fact_candidate_reviews',
        'knowledge_facts', 'knowledge_fact_versions',
        'knowledge_fact_version_sources'
    ];
BEGIN
    FOREACH table_name IN ARRAY domain_tables LOOP
        FOREACH role_name IN ARRAY ARRAY[
            'geno_v2_job_owner', 'geno_v2_result_owner', 'geno_v2_job_command_owner'
        ] LOOP
            FOREACH privilege_name IN ARRAY ARRAY['SELECT','INSERT','UPDATE','DELETE'] LOOP
                expected := CASE
                    WHEN role_name = 'geno_v2_result_owner' AND privilege_name = 'SELECT'
                        THEN table_name = ANY(result_select)
                    WHEN role_name = 'geno_v2_result_owner' AND privilege_name = 'INSERT'
                        THEN table_name = ANY(result_insert)
                    WHEN role_name = 'geno_v2_result_owner' AND privilege_name = 'UPDATE'
                        THEN table_name = 'knowledge_source_assets'
                    WHEN role_name = 'geno_v2_job_owner' AND privilege_name = 'SELECT'
                        THEN table_name = ANY(job_select)
                    WHEN role_name = 'geno_v2_job_owner' AND privilege_name = 'UPDATE'
                        THEN table_name = ANY(ARRAY[
                            'knowledge_pipeline_jobs', 'knowledge_pipeline_stages',
                            'knowledge_pipeline_runs'
                        ])
                    WHEN role_name = 'geno_v2_job_command_owner' AND privilege_name = 'SELECT'
                        THEN table_name = ANY(command_select)
                    WHEN role_name = 'geno_v2_job_command_owner' AND privilege_name = 'INSERT'
                        THEN table_name = ANY(command_insert)
                    WHEN role_name = 'geno_v2_job_command_owner' AND privilege_name = 'UPDATE'
                        THEN table_name = ANY(ARRAY[
                            'knowledge_pipeline_runs', 'knowledge_pipeline_stages',
                            'knowledge_pipeline_jobs', 'knowledge_source_assets',
                            'knowledge_fact_candidates',
                            'knowledge_facts'
                        ])
                    ELSE false
                END;
                IF has_table_privilege(
                    role_name, format('public.%I', table_name), privilege_name
                ) IS DISTINCT FROM expected THEN
                    RAISE EXCEPTION 'unexpected % % privilege on %',
                        role_name, privilege_name, table_name;
                END IF;
            END LOOP;
        END LOOP;
    END LOOP;
END;
$verify_knowledge_exact_owner_acls$;

COMMENT ON TABLE knowledge_pipeline_jobs IS
    'Unified Knowledge durable queue. Expired running work may re-execute; expired finalizing work only resumes finalize.';
COMMENT ON TABLE knowledge_source_governance_versions IS
    'Immutable source governance snapshot. Authority ordering is A(4) > B(3) > C(2) > D(1).';
COMMENT ON FUNCTION geno_v2_read_approved_knowledge(uuid, text) IS
    'Safe Approved Knowledge projection; never returns source URI, locator, or internal governance metadata.';
