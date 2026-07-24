CREATE TABLE synthetic_lab_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    operation text NOT NULL CHECK (operation IN (
        'create_authorization', 'reassess_authorization', 'decide_authorization',
        'expire_authorization',
        'revoke_authorization', 'admit_collection', 'claim_collection',
        'create_style_source', 'create_style_profile',
        'create_review_suite', 'create_review_case',
        'import_samples', 'freeze_profile', 'freeze_suite', 'enqueue_generation',
        'enqueue_revision', 'enqueue_corpus', 'enqueue_experiment', 'claim_job',
        'enqueue_execution', 'cancel_job', 'finalize_result', 'finalize_experiment'
    )),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    result_type text NOT NULL CHECK (
        result_type ~ '^geo_core\.(synthetic_lab|jobs)\.[A-Za-z0-9_.]+$'
    ),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    result_payload_hash text NOT NULL CHECK (result_payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, idempotency_key_hash)
);

CREATE TABLE synthetic_lab_aggregate_versions (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_]{0,62}$'),
    resource_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    submitted_by uuid NOT NULL REFERENCES identities(id),
    payload_type text NOT NULL CHECK (
        payload_type ~ '^geo_core\.synthetic_lab\.[A-Za-z0-9_.]+$'
    ),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, kind, resource_id, version),
    UNIQUE (project_id, kind, resource_id, payload_hash, version)
);

CREATE TABLE synthetic_lab_authorization_versions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    channel text NOT NULL CHECK (channel IN (
        'owned_site', 'amazon', 'youtube', 'tiktok', 'instagram',
        'productreview', 'reddit', 'ozbargain', 'quora'
    )),
    adapter_release text NOT NULL CHECK (btrim(adapter_release) <> ''),
    version_number integer NOT NULL CHECK (version_number > 0),
    previous_version_id uuid,
    state text NOT NULL CHECK (state IN (
        'not_assessed', 'approved', 'assessed_no_basis', 'expired', 'revoked'
    )),
    evidence_reference_hash text CHECK (
        evidence_reference_hash IS NULL OR evidence_reference_hash ~ '^[0-9a-f]{64}$'
    ),
    decided_by uuid REFERENCES identities(id),
    decided_at timestamptz,
    allowed_purposes text[] NOT NULL DEFAULT ARRAY[]::text[],
    max_requests_per_period integer CHECK (
        max_requests_per_period IS NULL OR max_requests_per_period > 0
    ),
    period_seconds integer CHECK (period_seconds IS NULL OR period_seconds > 0),
    max_concurrency integer CHECK (max_concurrency IS NULL OR max_concurrency > 0),
    expires_at timestamptz,
    decision_reason text,
    record_hash text NOT NULL CHECK (record_hash ~ '^[0-9a-f]{64}$'),
    submitted_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (id, project_id, channel, adapter_release),
    UNIQUE (id, project_id, channel, adapter_release, version_number, record_hash),
    UNIQUE (project_id, channel, adapter_release, version_number),
    UNIQUE (project_id, channel, adapter_release, record_hash),
    UNIQUE (previous_version_id, project_id, channel, adapter_release),
    FOREIGN KEY (
        previous_version_id, project_id, channel, adapter_release
    ) REFERENCES synthetic_lab_authorization_versions(
        id, project_id, channel, adapter_release
    ),
    CONSTRAINT synthetic_lab_authorization_shape CHECK (
        (state = 'not_assessed'
            AND ((version_number = 1 AND previous_version_id IS NULL)
                OR (version_number > 1 AND previous_version_id IS NOT NULL))
            AND evidence_reference_hash IS NULL AND decided_by IS NULL
            AND decided_at IS NULL AND cardinality(allowed_purposes) = 0
            AND max_requests_per_period IS NULL AND period_seconds IS NULL
            AND max_concurrency IS NULL AND expires_at IS NULL
            AND decision_reason IS NULL)
        OR (state = 'assessed_no_basis'
            AND version_number > 1 AND previous_version_id IS NOT NULL
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL
            AND cardinality(allowed_purposes) = 0
            AND max_requests_per_period IS NULL AND period_seconds IS NULL
            AND max_concurrency IS NULL AND expires_at IS NULL
            AND decision_reason IS NOT NULL AND btrim(decision_reason) <> '')
        OR (state IN ('approved', 'expired', 'revoked')
            AND version_number > 1 AND previous_version_id IS NOT NULL
            AND evidence_reference_hash IS NOT NULL
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL
            AND cardinality(allowed_purposes) > 0
            AND max_requests_per_period IS NOT NULL AND period_seconds IS NOT NULL
            AND max_concurrency IS NOT NULL AND expires_at IS NOT NULL
            AND decision_reason IS NOT NULL AND btrim(decision_reason) <> '')
    ),
    CONSTRAINT synthetic_lab_authorization_time_shape CHECK (
        state <> 'approved' OR expires_at > decided_at
    )
);

CREATE TABLE synthetic_lab_manual_import_previews (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    style_source_revision_id uuid NOT NULL,
    source_revision_number integer NOT NULL CHECK (source_revision_number > 0),
    channel text NOT NULL CHECK (channel IN (
        'owned_site', 'amazon', 'youtube', 'tiktok', 'instagram',
        'productreview', 'reddit', 'ozbargain', 'quora'
    )),
    locale text NOT NULL CHECK (locale = 'en-AU'),
    filename text NOT NULL CHECK (
        btrim(filename) <> '' AND length(filename) <= 255
        AND filename NOT IN ('.', '..')
        AND position('/' IN filename) = 0 AND position(chr(92) IN filename) = 0
    ),
    import_format text NOT NULL CHECK (import_format IN ('text', 'csv', 'jsonl')),
    default_source_rights text NOT NULL CHECK (default_source_rights IN (
        'owned', 'licensed', 'public_reference', 'authorized_manual_capture'
    )),
    rights_evidence_hash text NOT NULL CHECK (rights_evidence_hash ~ '^[0-9a-f]{64}$'),
    submitted_by uuid NOT NULL REFERENCES identities(id),
    submitted_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    upload_artifact_id uuid NOT NULL,
    upload_object_uri text NOT NULL CHECK (
        upload_object_uri ~ '^s3://[^/@[:space:]]+/synthetic-lab/manual-import/temporary_upload/.+'
        AND upload_object_uri !~ '://[^/]*@'
    ),
    upload_object_hash text NOT NULL CHECK (upload_object_hash ~ '^[0-9a-f]{64}$'),
    upload_plaintext_hash text NOT NULL CHECK (upload_plaintext_hash ~ '^[0-9a-f]{64}$'),
    upload_key_version text NOT NULL CHECK (upload_key_version ~ '^[1-9][0-9]{0,9}$'),
    upload_algorithm text NOT NULL CHECK (
        upload_algorithm = 'AES-256-GCM/HKDF-project-artifact/v1'
    ),
    upload_media_type text NOT NULL CHECK (
        upload_media_type = 'application/vnd.geo.synthetic-manual-import+encrypted'
    ),
    upload_byte_size bigint NOT NULL CHECK (upload_byte_size > 0),
    schema_release text NOT NULL CHECK (btrim(schema_release) <> ''),
    parser_release text NOT NULL CHECK (btrim(parser_release) <> ''),
    scanner_release text NOT NULL CHECK (btrim(scanner_release) <> ''),
    anonymizer_release text NOT NULL CHECK (btrim(anonymizer_release) <> ''),
    row_count integer NOT NULL CHECK (row_count > 0),
    selectable_count integer NOT NULL CHECK (selectable_count >= 0),
    blocked_count integer NOT NULL CHECK (blocked_count >= 0),
    preview_manifest_hash text NOT NULL CHECK (preview_manifest_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, upload_artifact_id),
    UNIQUE (project_id, upload_object_uri),
    CHECK (expires_at > submitted_at),
    CHECK (row_count = selectable_count + blocked_count)
);

CREATE TABLE synthetic_lab_manual_import_preview_states (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    preview_id uuid NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    previous_state_id uuid,
    status text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    actor_id uuid NOT NULL REFERENCES identities(id),
    occurred_at timestamptz NOT NULL,
    selected_row_numbers integer[] NOT NULL DEFAULT ARRAY[]::integer[],
    selection_hash text CHECK (selection_hash IS NULL OR selection_hash ~ '^[0-9a-f]{64}$'),
    au_english_verified boolean NOT NULL DEFAULT false,
    anonymization_verified boolean NOT NULL DEFAULT false,
    final_manifest_id uuid,
    reason_hash text CHECK (reason_hash IS NULL OR reason_hash ~ '^[0-9a-f]{64}$'),
    idempotency_key_hash text CHECK (
        idempotency_key_hash IS NULL OR idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    request_hash text CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$'),
    state_hash text NOT NULL CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (id, project_id, preview_id),
    UNIQUE (id, project_id, preview_id, version, status),
    UNIQUE (project_id, preview_id, version),
    FOREIGN KEY (preview_id, project_id)
        REFERENCES synthetic_lab_manual_import_previews(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (previous_state_id, project_id, preview_id)
        REFERENCES synthetic_lab_manual_import_preview_states(id, project_id, preview_id),
    CHECK ((idempotency_key_hash IS NULL) = (request_hash IS NULL)),
    CONSTRAINT synthetic_lab_manual_import_preview_states_shape CHECK (
        (status = 'pending' AND version = 1 AND previous_state_id IS NULL
            AND cardinality(selected_row_numbers) = 0 AND selection_hash IS NULL
            AND NOT au_english_verified AND NOT anonymization_verified
            AND final_manifest_id IS NULL AND reason_hash IS NULL
            AND idempotency_key_hash IS NULL)
        OR (status = 'approved' AND version = 2 AND previous_state_id IS NOT NULL
            AND cardinality(selected_row_numbers) > 0 AND selection_hash IS NOT NULL
            AND au_english_verified AND anonymization_verified
            AND final_manifest_id IS NOT NULL AND reason_hash IS NULL
            AND idempotency_key_hash IS NOT NULL)
        OR (status IN ('rejected', 'expired') AND version = 2
            AND previous_state_id IS NOT NULL
            AND cardinality(selected_row_numbers) = 0 AND selection_hash IS NULL
            AND NOT au_english_verified AND NOT anonymization_verified
            AND final_manifest_id IS NULL AND reason_hash IS NOT NULL
            AND idempotency_key_hash IS NOT NULL)
    )
);

CREATE UNIQUE INDEX synthetic_lab_manual_import_preview_states_idempotency
ON synthetic_lab_manual_import_preview_states(project_id, idempotency_key_hash)
WHERE idempotency_key_hash IS NOT NULL;

CREATE TABLE synthetic_lab_manual_import_manifests (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    preview_id uuid NOT NULL,
    request_id uuid NOT NULL,
    channel text NOT NULL CHECK (channel IN (
        'owned_site', 'amazon', 'youtube', 'tiktok', 'instagram',
        'productreview', 'reddit', 'ozbargain', 'quora'
    )),
    locale text NOT NULL CHECK (locale = 'en-AU'),
    imported_by uuid NOT NULL REFERENCES identities(id),
    imported_at timestamptz NOT NULL,
    schema_release text NOT NULL CHECK (btrim(schema_release) <> ''),
    row_count integer NOT NULL CHECK (row_count > 0),
    accepted_count integer NOT NULL CHECK (accepted_count >= 0),
    rejected_count integer NOT NULL CHECK (rejected_count >= 0),
    duplicate_row_count integer NOT NULL CHECK (duplicate_row_count >= 0),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, request_id),
    UNIQUE (id, project_id),
    UNIQUE (id, project_id, preview_id),
    UNIQUE (project_id, preview_id),
    UNIQUE (id, project_id, request_id, channel, locale),
    FOREIGN KEY (preview_id, project_id)
        REFERENCES synthetic_lab_manual_import_previews(id, project_id),
    CHECK (accepted_count + rejected_count = row_count),
    CHECK (duplicate_row_count <= row_count)
);

ALTER TABLE synthetic_lab_manual_import_preview_states
ADD CONSTRAINT synthetic_lab_manual_import_preview_states_manifest_fkey
FOREIGN KEY (final_manifest_id, project_id, preview_id)
REFERENCES synthetic_lab_manual_import_manifests(id, project_id, preview_id)
DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE synthetic_lab_manual_import_row_errors (
    project_id uuid NOT NULL,
    manifest_id uuid NOT NULL,
    row_number integer NOT NULL CHECK (row_number > 0),
    code text NOT NULL CHECK (btrim(code) <> ''),
    message text NOT NULL CHECK (btrim(message) <> ''),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (project_id, manifest_id, row_number, code),
    FOREIGN KEY (manifest_id, project_id)
        REFERENCES synthetic_lab_manual_import_manifests(id, project_id) ON DELETE CASCADE
);

CREATE TABLE synthetic_lab_imported_samples (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    manifest_id uuid NOT NULL,
    request_id uuid NOT NULL,
    row_number integer NOT NULL CHECK (row_number > 0),
    channel text NOT NULL,
    locale text NOT NULL CHECK (locale = 'en-AU'),
    style_source_revision_id uuid NOT NULL,
    source_revision_number integer NOT NULL CHECK (source_revision_number > 0),
    collection_run_id uuid NOT NULL,
    normalized_text_hash text NOT NULL CHECK (normalized_text_hash ~ '^[0-9a-f]{64}$'),
    source_locator_hash text NOT NULL CHECK (source_locator_hash ~ '^[0-9a-f]{64}$'),
    source_artifact_hash text NOT NULL CHECK (source_artifact_hash ~ '^[0-9a-f]{64}$'),
    source_rights text NOT NULL CHECK (source_rights IN (
        'owned', 'licensed', 'public_reference', 'authorized_manual_capture'
    )),
    rights_evidence_hash text NOT NULL CHECK (rights_evidence_hash ~ '^[0-9a-f]{64}$'),
    language_reviewer_id uuid NOT NULL REFERENCES identities(id),
    language_reviewed_at timestamptz NOT NULL,
    short_example_eligible boolean NOT NULL,
    short_example_exclusion_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, normalized_text_hash),
    UNIQUE (project_id, manifest_id, row_number),
    FOREIGN KEY (manifest_id, project_id, request_id, channel, locale)
        REFERENCES synthetic_lab_manual_import_manifests(
            id, project_id, request_id, channel, locale
        ) ON DELETE CASCADE,
    CHECK (short_example_eligible <> (cardinality(short_example_exclusion_codes) > 0))
);

CREATE TABLE synthetic_lab_artifact_governance_decisions (
    artifact_id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    captured_at timestamptz NOT NULL,
    classification text NOT NULL CHECK (classification IN (
        'public_raw', 'restricted_authenticated_raw', 'derived_anonymized',
        'secret_bearing_rejected'
    )),
    persisted_content_hash text NOT NULL CHECK (
        persisted_content_hash ~ '^[0-9a-f]{64}$'
    ),
    persistence_allowed boolean NOT NULL,
    storage_tier text NOT NULL CHECK (storage_tier IN (
        'none', 'encrypted_raw', 'restricted_independent_dek', 'derived_project'
    )),
    independent_dek_required boolean NOT NULL,
    allowed_audiences text[] NOT NULL DEFAULT ARRAY[]::text[],
    ttl_days integer CHECK (ttl_days IS NULL OR ttl_days >= 0),
    expires_at timestamptz,
    destroy_temporary_payload boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (artifact_id, project_id),
    CHECK (NOT allowed_audiences && ARRAY['customer','general_export','recommendation']::text[]),
    CHECK (
        (classification = 'secret_bearing_rejected' AND NOT persistence_allowed
            AND storage_tier = 'none' AND cardinality(allowed_audiences) = 0
            AND ttl_days = 0 AND expires_at IS NULL AND destroy_temporary_payload)
        OR (classification = 'public_raw' AND persistence_allowed
            AND storage_tier = 'encrypted_raw' AND NOT independent_dek_required)
        OR (classification = 'restricted_authenticated_raw' AND persistence_allowed
            AND storage_tier = 'restricted_independent_dek' AND independent_dek_required)
        OR (classification = 'derived_anonymized' AND persistence_allowed
            AND storage_tier = 'derived_project' AND NOT independent_dek_required)
    ),
    CHECK (NOT persistence_allowed OR cardinality(allowed_audiences) > 0),
    CHECK (expires_at IS NULL OR ttl_days IS NOT NULL),
    CHECK (expires_at IS NULL OR expires_at = captured_at + make_interval(days => ttl_days))
);

CREATE TABLE synthetic_lab_job_metadata (
    job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    metadata_version integer NOT NULL CHECK (metadata_version > 0),
    domain_job_kind text NOT NULL CHECK (domain_job_kind IN (
        'style_collection', 'candidate_generation', 'candidate_revision',
        'corpus_finalize', 'offline_experiment', 'style_profile_build',
        'model_call_child'
    )),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    fact_snapshot_id uuid,
    fact_snapshot_hash text CHECK (
        fact_snapshot_hash IS NULL OR fact_snapshot_hash ~ '^[0-9a-f]{64}$'
    ),
    profile_version_id uuid,
    profile_hash text CHECK (profile_hash IS NULL OR profile_hash ~ '^[0-9a-f]{64}$'),
    prompt_release_id uuid,
    prompt_release_hash text CHECK (
        prompt_release_hash IS NULL OR prompt_release_hash ~ '^[0-9a-f]{64}$'
    ),
    facts_current_approved boolean,
    profile_frozen boolean,
    prompt_frozen boolean,
    authorization_id uuid,
    authorization_channel text,
    authorization_adapter_release text,
    authorization_version integer,
    authorization_hash text CHECK (
        authorization_hash IS NULL OR authorization_hash ~ '^[0-9a-f]{64}$'
    ),
    authorization_purpose text,
    authorization_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, job_id),
    UNIQUE (job_id, project_id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (
        authorization_id, project_id, authorization_channel,
        authorization_adapter_release, authorization_version, authorization_hash
    ) REFERENCES synthetic_lab_authorization_versions(
        id, project_id, channel, adapter_release, version_number, record_hash
    ),
    CONSTRAINT synthetic_lab_job_runtime_shape CHECK (
        (fact_snapshot_id IS NULL AND fact_snapshot_hash IS NULL
            AND profile_version_id IS NULL AND profile_hash IS NULL
            AND prompt_release_id IS NULL AND prompt_release_hash IS NULL
            AND facts_current_approved IS NULL AND profile_frozen IS NULL
            AND prompt_frozen IS NULL)
        OR (fact_snapshot_id IS NOT NULL AND fact_snapshot_hash IS NOT NULL
            AND profile_version_id IS NOT NULL AND profile_hash IS NOT NULL
            AND prompt_release_id IS NOT NULL AND prompt_release_hash IS NOT NULL
            AND facts_current_approved AND profile_frozen AND prompt_frozen)
    ),
    CONSTRAINT synthetic_lab_job_authorization_shape CHECK (
        (authorization_id IS NULL AND authorization_channel IS NULL
            AND authorization_adapter_release IS NULL AND authorization_version IS NULL
            AND authorization_hash IS NULL AND authorization_purpose IS NULL
            AND authorization_expires_at IS NULL)
        OR (authorization_id IS NOT NULL AND authorization_channel IS NOT NULL
            AND authorization_adapter_release IS NOT NULL AND authorization_version > 0
            AND authorization_hash IS NOT NULL AND authorization_purpose IS NOT NULL
            AND btrim(authorization_purpose) <> '' AND authorization_expires_at IS NOT NULL)
    )
);

CREATE TABLE synthetic_lab_outbox_messages (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type ~ '^synthetic\.[a-z0-9_.]+\.queued$'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    FOREIGN KEY (id, project_id) REFERENCES broker_outbox(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (job_id, project_id)
        REFERENCES synthetic_lab_job_metadata(job_id, project_id) ON DELETE CASCADE
);

CREATE TABLE synthetic_lab_model_call_children (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    child_job_id uuid NOT NULL,
    parent_job_id uuid NOT NULL,
    parent_job_kind text NOT NULL CHECK (parent_job_kind IN (
        'style.profile.build', 'review.case.run', 'offline_experiment.run'
    )),
    parent_task_input_hash text NOT NULL CHECK (
        parent_task_input_hash ~ '^[0-9a-f]{64}$'
    ),
    parent_lease_token uuid NOT NULL,
    parent_fencing_generation bigint NOT NULL CHECK (parent_fencing_generation > 0),
    step_key text NOT NULL CHECK (
        step_key ~ '^[a-z0-9][a-z0-9._:-]{0,199}$'
    ),
    step_key_hash text NOT NULL CHECK (step_key_hash ~ '^[0-9a-f]{64}$'),
    model_job_version integer NOT NULL CHECK (model_job_version > 0),
    fact_snapshot_id uuid NOT NULL,
    fact_snapshot_hash text NOT NULL CHECK (fact_snapshot_hash ~ '^[0-9a-f]{64}$'),
    profile_version_id uuid NOT NULL,
    profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
    runtime_prompt_release_id uuid NOT NULL,
    runtime_prompt_release_hash text NOT NULL CHECK (
        runtime_prompt_release_hash ~ '^[0-9a-f]{64}$'
    ),
    prompt_binding_id uuid NOT NULL,
    prompt_binding_version integer NOT NULL CHECK (prompt_binding_version > 0),
    prompt_frozen_state_id uuid NOT NULL,
    prompt_state_version integer NOT NULL CHECK (prompt_state_version > 0),
    prompt_release_id uuid NOT NULL,
    prompt_release_version integer NOT NULL CHECK (prompt_release_version > 0),
    prompt_release_hash text NOT NULL CHECK (
        prompt_release_hash ~ '^[0-9a-f]{64}$'
    ),
    prompt_program_kind text NOT NULL CHECK (prompt_program_kind IN (
        'generation', 'claim_extraction', 'conflict_check', 'revision',
        'style_judge', 'arbiter', 'metric_judge', 'recommendation',
        'reference_translation', 'style_profile', 'offline_answer'
    )),
    prompt_purpose text NOT NULL CHECK (btrim(prompt_purpose) <> ''),
    admitted_by uuid NOT NULL REFERENCES identities(id),
    prompt_model_policy_hash text NOT NULL CHECK (
        prompt_model_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    provider text NOT NULL CHECK (btrim(provider) <> ''),
    adapter_release_id text NOT NULL CHECK (btrim(adapter_release_id) <> ''),
    adapter_release_hash text NOT NULL CHECK (
        adapter_release_hash ~ '^[0-9a-f]{64}$'
    ),
    model_release_id text NOT NULL CHECK (btrim(model_release_id) <> ''),
    model_release_hash text NOT NULL CHECK (
        model_release_hash ~ '^[0-9a-f]{64}$'
    ),
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    runtime_manifest_id uuid NOT NULL,
    runtime_manifest_hash text NOT NULL CHECK (
        runtime_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    runtime_option_id uuid NOT NULL,
    runtime_option_hash text NOT NULL CHECK (
        runtime_option_hash ~ '^[0-9a-f]{64}$'
    ),
    search_mode text,
    prompt_bundle_hash text NOT NULL CHECK (prompt_bundle_hash ~ '^[0-9a-f]{64}$'),
    structured_input_hash text NOT NULL CHECK (
        structured_input_hash ~ '^[0-9a-f]{64}$'
    ),
    portable_output_schema_hash text NOT NULL CHECK (
        portable_output_schema_hash ~ '^[0-9a-f]{64}$'
    ),
    application_output_schema_hash text NOT NULL CHECK (
        application_output_schema_hash ~ '^[0-9a-f]{64}$'
    ),
    task_artifact_uri text NOT NULL CHECK (task_artifact_uri ~ '^s3://[^/]+/.+'),
    task_artifact_hash text NOT NULL CHECK (task_artifact_hash ~ '^[0-9a-f]{64}$'),
    deterministic_seed numeric(20,0) CHECK (
        deterministic_seed IS NULL
        OR (deterministic_seed >= 0 AND deterministic_seed < 18446744073709551616)
    ),
    max_output_tokens integer NOT NULL CHECK (
        max_output_tokens > 0 AND max_output_tokens <= 131072
    ),
    child_input_hash text NOT NULL CHECK (child_input_hash ~ '^[0-9a-f]{64}$'),
    outbox_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, child_job_id),
    UNIQUE (child_job_id, project_id),
    UNIQUE (project_id, parent_job_id, step_key_hash),
    UNIQUE (outbox_id, project_id),
    FOREIGN KEY (child_job_id, project_id)
        REFERENCES synthetic_lab_job_metadata(job_id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (outbox_id, project_id)
        REFERENCES synthetic_lab_outbox_messages(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (
        prompt_binding_id, project_id, prompt_purpose, prompt_binding_version
    ) REFERENCES prompt_program_bindings(id, project_id, purpose, binding_version),
    FOREIGN KEY (
        prompt_release_id, project_id, prompt_release_hash
    ) REFERENCES prompt_program_releases(id, project_id, release_hash),
    FOREIGN KEY (
        runtime_prompt_release_id, project_id, runtime_prompt_release_hash
    ) REFERENCES prompt_program_releases(id, project_id, release_hash),
    FOREIGN KEY (
        prompt_frozen_state_id, project_id, prompt_release_id,
        prompt_release_hash, prompt_state_version
    ) REFERENCES prompt_program_release_states(
        id, project_id, release_id, release_hash, version
    ),
    FOREIGN KEY (
        runtime_manifest_id, project_id, runtime_manifest_hash
    ) REFERENCES model_gateway_runtime_manifests(id, project_id, manifest_hash),
    FOREIGN KEY (
        runtime_option_id, project_id, runtime_manifest_id, runtime_option_hash
    ) REFERENCES model_gateway_runtime_options(
        id, project_id, manifest_id, option_hash
    ),
    CHECK (child_job_id <> parent_job_id)
);

CREATE TABLE synthetic_lab_style_collection_tasks (
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    style_source_revision_id uuid NOT NULL,
    source_revision_number integer NOT NULL CHECK (source_revision_number > 0),
    channel text NOT NULL CHECK (channel IN (
        'owned_site', 'amazon', 'youtube', 'tiktok', 'instagram',
        'productreview', 'reddit', 'ozbargain', 'quora'
    )),
    locale text NOT NULL CHECK (locale = 'en-AU'),
    access_mode text NOT NULL CHECK (access_mode IN ('public', 'authenticated')),
    source_url text NOT NULL CHECK (
        source_url ~ '^https://[^/?#@]+(?:/[^?#]*)?$'
    ),
    source_locator_hash text NOT NULL CHECK (source_locator_hash ~ '^[0-9a-f]{64}$'),
    adapter_release text NOT NULL CHECK (btrim(adapter_release) <> ''),
    authorization_id uuid NOT NULL,
    authorization_version integer NOT NULL CHECK (authorization_version > 0),
    authorization_hash text NOT NULL CHECK (authorization_hash ~ '^[0-9a-f]{64}$'),
    authorization_purpose text NOT NULL CHECK (btrim(authorization_purpose) <> ''),
    authorization_expires_at timestamptz NOT NULL,
    login_secret_reference_id uuid,
    login_secret_version integer CHECK (login_secret_version > 0),
    login_secret_handle_hash text CHECK (
        login_secret_handle_hash IS NULL OR login_secret_handle_hash ~ '^[0-9a-f]{64}$'
    ),
    allowed_redirect_hosts text[] NOT NULL CHECK (cardinality(allowed_redirect_hosts) > 0),
    robots_user_agent text NOT NULL CHECK (btrim(robots_user_agent) <> ''),
    raw_artifact_id uuid NOT NULL,
    derived_artifact_id uuid NOT NULL,
    tmpfs_mount_path text NOT NULL CHECK (
        tmpfs_mount_path LIKE '/dev/shm/%' OR tmpfs_mount_path LIKE '/run/%'
            OR tmpfs_mount_path LIKE '/tmp/%'
    ),
    tmpfs_maximum_bytes bigint NOT NULL CHECK (tmpfs_maximum_bytes > 0),
    maximum_redirects integer NOT NULL CHECK (maximum_redirects >= 0),
    task_input_hash text NOT NULL CHECK (task_input_hash ~ '^[0-9a-f]{64}$'),
    task_type text NOT NULL CHECK (
        task_type = 'geo_core.synthetic_lab.collection_execution_contracts.StyleCollectionTask'
    ),
    task_payload jsonb NOT NULL CHECK (jsonb_typeof(task_payload) = 'object'),
    task_payload_hash text NOT NULL CHECK (task_payload_hash ~ '^[0-9a-f]{64}$'),
    staged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, job_id),
    UNIQUE (job_id, project_id),
    UNIQUE (project_id, collection_run_id),
    UNIQUE (project_id, raw_artifact_id),
    UNIQUE (project_id, derived_artifact_id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES synthetic_lab_job_metadata(job_id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (
        authorization_id, project_id, channel, adapter_release,
        authorization_version, authorization_hash
    ) REFERENCES synthetic_lab_authorization_versions(
        id, project_id, channel, adapter_release, version_number, record_hash
    ),
    FOREIGN KEY (login_secret_reference_id, login_secret_version)
        REFERENCES secret_versions(reference_id, version),
    CONSTRAINT synthetic_lab_style_collection_tasks_secret_shape CHECK (
        (access_mode = 'public' AND login_secret_reference_id IS NULL
            AND login_secret_version IS NULL AND login_secret_handle_hash IS NULL)
        OR (access_mode = 'authenticated' AND login_secret_reference_id IS NOT NULL
            AND login_secret_version IS NOT NULL AND login_secret_handle_hash IS NOT NULL)
    ),
    CHECK (raw_artifact_id <> derived_artifact_id)
);

CREATE TABLE synthetic_lab_artifact_master_key_versions (
    master_key_version text PRIMARY KEY CHECK (
        master_key_version ~ '^[1-9][0-9]{0,9}$'
    ),
    algorithm text NOT NULL CHECK (algorithm = 'AES-256-GCM'),
    status text NOT NULL CHECK (
        status IN ('encrypt_decrypt', 'decrypt_only', 'retired')
    ),
    canary_nonce bytea NOT NULL CHECK (octet_length(canary_nonce) = 12),
    canary_ciphertext bytea NOT NULL CHECK (octet_length(canary_ciphertext) >= 17),
    created_at timestamptz NOT NULL,
    activated_at timestamptz NOT NULL,
    retired_at timestamptz,
    CONSTRAINT synthetic_lab_artifact_master_key_versions_state_shape CHECK (
        (status IN ('encrypt_decrypt', 'decrypt_only') AND retired_at IS NULL)
        OR (status = 'retired' AND retired_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX synthetic_lab_artifact_master_key_versions_active_key
ON synthetic_lab_artifact_master_key_versions ((status))
WHERE status = 'encrypt_decrypt';

ALTER TABLE synthetic_lab_manual_import_previews
ADD CONSTRAINT synthetic_lab_manual_import_previews_key_version_fkey
FOREIGN KEY (upload_key_version)
REFERENCES synthetic_lab_artifact_master_key_versions(master_key_version);

CREATE TABLE synthetic_lab_imported_sample_artifacts (
    project_id uuid NOT NULL,
    sample_id uuid NOT NULL,
    object_uri text NOT NULL CHECK (
        object_uri ~ '^s3://[^/@[:space:]]+/synthetic-lab/manual-import/anonymized_sample/.+'
        AND object_uri !~ '://[^/]*@'
    ),
    object_hash text NOT NULL CHECK (object_hash ~ '^[0-9a-f]{64}$'),
    plaintext_hash text NOT NULL CHECK (plaintext_hash ~ '^[0-9a-f]{64}$'),
    key_version text NOT NULL REFERENCES synthetic_lab_artifact_master_key_versions(
        master_key_version
    ),
    algorithm text NOT NULL CHECK (
        algorithm = 'AES-256-GCM/HKDF-project-artifact/v1'
    ),
    media_type text NOT NULL CHECK (
        media_type = 'application/vnd.geo.synthetic-manual-import+encrypted'
    ),
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, sample_id),
    UNIQUE (project_id, object_uri),
    FOREIGN KEY (sample_id, project_id)
        REFERENCES synthetic_lab_imported_samples(id, project_id) ON DELETE CASCADE
);

CREATE TABLE synthetic_lab_manual_import_cleanup_outbox (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    preview_id uuid NOT NULL,
    terminal_state_id uuid NOT NULL,
    terminal_version integer NOT NULL CHECK (terminal_version = 2),
    terminal_status text NOT NULL CHECK (
        terminal_status IN ('approved', 'rejected', 'expired')
    ),
    upload_artifact_id uuid NOT NULL,
    object_uri text NOT NULL CHECK (
        object_uri ~ '^s3://[^/@[:space:]]+/synthetic-lab/manual-import/temporary_upload/.+'
        AND object_uri !~ '://[^/]*@'
    ),
    object_hash text NOT NULL CHECK (object_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('pending', 'leased', 'failed', 'completed')),
    next_attempt_at timestamptz NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    fencing_generation bigint NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
    last_error_code text CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_]{0,62}$'
    ),
    created_at timestamptz NOT NULL,
    completed_at timestamptz,
    UNIQUE (id, project_id),
    UNIQUE (project_id, preview_id),
    FOREIGN KEY (preview_id, project_id)
        REFERENCES synthetic_lab_manual_import_previews(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (
        terminal_state_id, project_id, preview_id, terminal_version, terminal_status
    ) REFERENCES synthetic_lab_manual_import_preview_states(
        id, project_id, preview_id, version, status
    ),
    CONSTRAINT synthetic_lab_manual_import_cleanup_outbox_shape CHECK (
        (status IN ('pending', 'failed') AND lease_owner IS NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NULL)
        OR (status = 'leased' AND lease_owner IS NOT NULL
            AND btrim(lease_owner) <> '' AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND completed_at IS NULL)
        OR (status = 'completed' AND lease_owner IS NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NOT NULL)
    )
);

CREATE TABLE synthetic_lab_manual_import_cleanup_receipts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cleanup_outbox_id uuid NOT NULL,
    preview_id uuid NOT NULL,
    upload_artifact_id uuid NOT NULL,
    object_hash text NOT NULL CHECK (object_hash ~ '^[0-9a-f]{64}$'),
    deletion_receipt_hash text NOT NULL CHECK (deletion_receipt_hash ~ '^[0-9a-f]{64}$'),
    deleted_at timestamptz NOT NULL,
    object_deleted boolean NOT NULL CHECK (object_deleted),
    recoverable_body_retained boolean NOT NULL CHECK (NOT recoverable_body_retained),
    UNIQUE (id, project_id),
    UNIQUE (project_id, cleanup_outbox_id),
    UNIQUE (project_id, preview_id),
    FOREIGN KEY (cleanup_outbox_id, project_id)
        REFERENCES synthetic_lab_manual_import_cleanup_outbox(id, project_id),
    FOREIGN KEY (preview_id, project_id)
        REFERENCES synthetic_lab_manual_import_previews(id, project_id)
);

CREATE TABLE synthetic_lab_raw_artifacts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    job_id uuid NOT NULL,
    generation_lease_token uuid NOT NULL,
    fencing_generation bigint NOT NULL CHECK (fencing_generation > 0),
    artifact_form text NOT NULL CHECK (artifact_form IN ('raw', 'derived')),
    classification text NOT NULL CHECK (classification IN (
        'public_raw', 'restricted_authenticated_raw', 'derived_anonymized'
    )),
    storage_tier text NOT NULL CHECK (storage_tier IN (
        'encrypted_raw', 'restricted_independent_dek', 'derived_project'
    )),
    persisted_content_hash text NOT NULL CHECK (
        persisted_content_hash ~ '^[0-9a-f]{64}$'
    ),
    stored_object_hash text NOT NULL CHECK (stored_object_hash ~ '^[0-9a-f]{64}$'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    manifest_uri text CHECK (manifest_uri IS NULL OR manifest_uri ~ '^s3://[^/]+/.+'),
    payload_uri text CHECK (payload_uri IS NULL OR payload_uri ~ '^s3://[^/]+/.+'),
    media_type text NOT NULL CHECK (btrim(media_type) <> ''),
    byte_size bigint NOT NULL CHECK (byte_size > 0),
    record_count integer NOT NULL CHECK (record_count >= 0),
    source_identity_hash text NOT NULL CHECK (source_identity_hash ~ '^[0-9a-f]{64}$'),
    producer_release text NOT NULL CHECK (btrim(producer_release) <> ''),
    encryption_algorithm text NOT NULL CHECK (encryption_algorithm IN (
        'AES-256-GCM/independent-DEK/v1',
        'AES-256-GCM/project-tier-key/v1'
    )),
    artifact_key_ref text,
    tier_key_version text,
    captured_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    ttl_days integer CHECK (ttl_days IS NULL OR ttl_days > 0),
    expires_at timestamptz,
    allowed_audiences text[] NOT NULL CHECK (cardinality(allowed_audiences) > 0),
    lifecycle_state text NOT NULL CHECK (lifecycle_state IN (
        'persisted', 'winning', 'orphaned', 'deletion_pending', 'deleted'
    )),
    winning_result_id uuid,
    winning_at timestamptz,
    orphaned_at timestamptz,
    orphan_reason_code text CHECK (
        orphan_reason_code IS NULL OR orphan_reason_code ~ '^[a-z][a-z0-9_]{0,62}$'
    ),
    deletion_pending_at timestamptz,
    deleted_at timestamptz,
    record_version integer NOT NULL DEFAULT 1 CHECK (record_version > 0),
    PRIMARY KEY (project_id, artifact_id, fencing_generation),
    UNIQUE (artifact_id, project_id, fencing_generation),
    UNIQUE (project_id, job_id, generation_lease_token, fencing_generation, artifact_form),
    UNIQUE (project_id, manifest_hash),
    FOREIGN KEY (job_id, project_id)
        REFERENCES synthetic_lab_job_metadata(job_id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES synthetic_lab_artifact_governance_decisions(artifact_id, project_id),
    CONSTRAINT synthetic_lab_raw_artifacts_key_shape CHECK (
        (lifecycle_state <> 'deleted' AND storage_tier = 'restricted_independent_dek'
            AND artifact_key_ref IS NOT NULL AND tier_key_version IS NULL)
        OR (lifecycle_state <> 'deleted' AND storage_tier <> 'restricted_independent_dek'
            AND artifact_key_ref IS NULL AND tier_key_version IS NOT NULL)
        OR (lifecycle_state = 'deleted'
            AND artifact_key_ref IS NULL AND tier_key_version IS NULL)
    ),
    CONSTRAINT synthetic_lab_raw_artifacts_expiry_shape CHECK (
        (ttl_days IS NULL AND expires_at IS NULL)
        OR (ttl_days IS NOT NULL
            AND expires_at = captured_at + make_interval(days => ttl_days))
    ),
    CONSTRAINT synthetic_lab_raw_artifacts_status_shape CHECK (
        (lifecycle_state = 'persisted'
            AND manifest_uri IS NOT NULL AND payload_uri IS NOT NULL
            AND winning_result_id IS NULL AND winning_at IS NULL
            AND orphaned_at IS NULL AND orphan_reason_code IS NULL
            AND deletion_pending_at IS NULL AND deleted_at IS NULL)
        OR (lifecycle_state = 'winning'
            AND manifest_uri IS NOT NULL AND payload_uri IS NOT NULL
            AND winning_result_id IS NOT NULL AND winning_at IS NOT NULL
            AND orphaned_at IS NULL AND orphan_reason_code IS NULL
            AND deletion_pending_at IS NULL AND deleted_at IS NULL)
        OR (lifecycle_state = 'orphaned'
            AND manifest_uri IS NOT NULL AND payload_uri IS NOT NULL
            AND winning_result_id IS NULL AND winning_at IS NULL
            AND orphaned_at IS NOT NULL AND orphan_reason_code IS NOT NULL
            AND deletion_pending_at IS NULL AND deleted_at IS NULL)
        OR (lifecycle_state = 'deletion_pending' AND manifest_uri IS NOT NULL
            AND payload_uri IS NOT NULL AND deletion_pending_at IS NOT NULL
            AND deleted_at IS NULL)
        OR (lifecycle_state = 'deleted' AND manifest_uri IS NULL AND payload_uri IS NULL
            AND deletion_pending_at IS NOT NULL AND deleted_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX synthetic_lab_raw_artifacts_one_winner
ON synthetic_lab_raw_artifacts(project_id, artifact_id)
WHERE lifecycle_state = 'winning';

CREATE TABLE synthetic_lab_artifact_deks (
    key_ref text PRIMARY KEY CHECK (btrim(key_ref) <> ''),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    fencing_generation bigint NOT NULL CHECK (fencing_generation > 0),
    wrapped_dek bytea,
    wrap_nonce bytea,
    master_key_version text NOT NULL REFERENCES synthetic_lab_artifact_master_key_versions(
        master_key_version
    ),
    algorithm text NOT NULL CHECK (
        algorithm = 'AES-256-GCM/synthetic-artifact-KEK/v1'
    ),
    status text NOT NULL CHECK (status IN ('active', 'destroyed')),
    created_at timestamptz NOT NULL,
    destroyed_at timestamptz,
    UNIQUE (key_ref, project_id, artifact_id, fencing_generation),
    UNIQUE (project_id, artifact_id, fencing_generation),
    FOREIGN KEY (artifact_id, project_id, fencing_generation)
        REFERENCES synthetic_lab_raw_artifacts(artifact_id, project_id, fencing_generation)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT synthetic_lab_artifact_deks_state_shape CHECK (
        (status = 'active' AND octet_length(wrapped_dek) = 48
            AND octet_length(wrap_nonce) = 12
            AND destroyed_at IS NULL)
        OR (status = 'destroyed' AND wrapped_dek IS NULL AND wrap_nonce IS NULL
            AND destroyed_at IS NOT NULL)
    )
);

ALTER TABLE synthetic_lab_raw_artifacts
ADD CONSTRAINT synthetic_lab_raw_artifacts_dek_fkey FOREIGN KEY (
    artifact_key_ref, project_id, artifact_id, fencing_generation
) REFERENCES synthetic_lab_artifact_deks(
    key_ref, project_id, artifact_id, fencing_generation
)
DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE synthetic_lab_artifact_legal_holds (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    artifact_generation bigint NOT NULL CHECK (artifact_generation > 0),
    first_approver_id uuid NOT NULL REFERENCES identities(id),
    second_approver_id uuid NOT NULL REFERENCES identities(id),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    approved_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    hold_hash text NOT NULL CHECK (hold_hash ~ '^[0-9a-f]{64}$'),
    UNIQUE (id, project_id),
    UNIQUE (project_id, artifact_id, artifact_generation, hold_hash),
    FOREIGN KEY (artifact_id, project_id, artifact_generation)
        REFERENCES synthetic_lab_raw_artifacts(
            artifact_id, project_id, fencing_generation
        ),
    CHECK (first_approver_id <> second_approver_id),
    CHECK (approved_at < expires_at AND expires_at <= approved_at + interval '90 days')
);

CREATE TABLE synthetic_lab_artifact_deletion_outbox (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    artifact_generation bigint NOT NULL CHECK (artifact_generation > 0),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    reason text NOT NULL CHECK (reason IN ('orphaned', 'retention_expired', 'manual')),
    status text NOT NULL CHECK (status IN ('pending', 'leased', 'failed', 'completed')),
    next_attempt_at timestamptz NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    fencing_generation bigint NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
    last_error_code text CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_]{0,62}$'
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (id, project_id),
    FOREIGN KEY (artifact_id, project_id, artifact_generation)
        REFERENCES synthetic_lab_raw_artifacts(
            artifact_id, project_id, fencing_generation
        ) ON DELETE CASCADE,
    CONSTRAINT synthetic_lab_artifact_deletion_outbox_shape CHECK (
        (status IN ('pending', 'failed') AND lease_owner IS NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NULL)
        OR (status = 'leased' AND lease_owner IS NOT NULL
            AND btrim(lease_owner) <> '' AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND completed_at IS NULL)
        OR (status = 'completed' AND lease_owner IS NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX synthetic_lab_artifact_deletion_one_active
ON synthetic_lab_artifact_deletion_outbox(project_id, artifact_id, artifact_generation)
WHERE status IN ('pending', 'leased', 'failed');

CREATE TABLE synthetic_lab_artifact_tombstones (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    artifact_generation bigint NOT NULL CHECK (artifact_generation > 0),
    original_content_hash text NOT NULL CHECK (original_content_hash ~ '^[0-9a-f]{64}$'),
    classification text NOT NULL CHECK (classification IN (
        'public_raw', 'restricted_authenticated_raw', 'derived_anonymized'
    )),
    tombstone_hash text NOT NULL CHECK (tombstone_hash ~ '^[0-9a-f]{64}$'),
    deletion_receipt_hash text NOT NULL CHECK (
        deletion_receipt_hash ~ '^[0-9a-f]{64}$'
    ),
    deleted_at timestamptz NOT NULL,
    object_deleted boolean NOT NULL CHECK (object_deleted),
    artifact_dek_destroyed boolean NOT NULL CHECK (artifact_dek_destroyed),
    recoverable_body_retained boolean NOT NULL CHECK (NOT recoverable_body_retained),
    UNIQUE (id, project_id),
    UNIQUE (project_id, artifact_id, artifact_generation),
    FOREIGN KEY (artifact_id, project_id, artifact_generation)
        REFERENCES synthetic_lab_raw_artifacts(
            artifact_id, project_id, fencing_generation
        )
);

CREATE TABLE synthetic_lab_style_collection_results (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('captured', 'access_blocked')),
    final_url_hash text NOT NULL CHECK (final_url_hash ~ '^[0-9a-f]{64}$'),
    navigation_chain_hash text NOT NULL CHECK (navigation_chain_hash ~ '^[0-9a-f]{64}$'),
    raw_manifest_hash text CHECK (
        raw_manifest_hash IS NULL OR raw_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    derived_manifest_hash text CHECK (
        derived_manifest_hash IS NULL OR derived_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    derived_content_hash text CHECK (
        derived_content_hash IS NULL OR derived_content_hash ~ '^[0-9a-f]{64}$'
    ),
    extracted_record_count integer NOT NULL CHECK (extracted_record_count >= 0),
    block_reason text CHECK (block_reason IS NULL OR block_reason IN (
        'captcha', 'access_denied', 'rate_limited', 'login_failed',
        'robots_denied', 'redirect_denied', 'authorization_stale'
    )),
    result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    result_type text NOT NULL CHECK (
        result_type = 'geo_core.synthetic_lab.collection_execution_contracts.StyleCollectionOutput'
    ),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    result_payload_hash text NOT NULL CHECK (result_payload_hash ~ '^[0-9a-f]{64}$'),
    lease_token uuid NOT NULL,
    fencing_generation bigint NOT NULL CHECK (fencing_generation > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, job_id),
    UNIQUE (project_id, collection_run_id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES synthetic_lab_style_collection_tasks(job_id, project_id),
    CONSTRAINT synthetic_lab_style_collection_results_shape CHECK (
        (outcome = 'captured' AND derived_manifest_hash IS NOT NULL
            AND derived_content_hash IS NOT NULL AND extracted_record_count > 0
            AND block_reason IS NULL)
        OR (outcome = 'access_blocked' AND raw_manifest_hash IS NULL
            AND derived_manifest_hash IS NULL AND derived_content_hash IS NULL
            AND extracted_record_count = 0 AND block_reason IS NOT NULL)
    )
);

ALTER TABLE synthetic_lab_raw_artifacts
ADD CONSTRAINT synthetic_lab_raw_artifacts_winner_fkey FOREIGN KEY (
    winning_result_id, project_id
) REFERENCES synthetic_lab_style_collection_results(id, project_id)
DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE synthetic_lab_execution_tasks (
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    requested_by uuid NOT NULL REFERENCES identities(id),
    execution_kind text NOT NULL CHECK (execution_kind IN (
        'style.profile.build', 'review.case.run', 'offline_experiment.run'
    )),
    expected_job_input_hash text NOT NULL CHECK (
        expected_job_input_hash ~ '^[0-9a-f]{64}$'
    ),
    task_input_hash text NOT NULL CHECK (task_input_hash ~ '^[0-9a-f]{64}$'),
    task_type text NOT NULL CHECK (task_type IN (
        'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask',
        'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunTask',
        'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask'
    )),
    task_payload jsonb NOT NULL CHECK (jsonb_typeof(task_payload) = 'object'),
    task_payload_hash text NOT NULL CHECK (task_payload_hash ~ '^[0-9a-f]{64}$'),
    staged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, job_id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES synthetic_lab_job_metadata(job_id, project_id) ON DELETE CASCADE
);

ALTER TABLE synthetic_lab_model_call_children
ADD CONSTRAINT synthetic_lab_model_call_children_parent_task_fkey
FOREIGN KEY (project_id, parent_job_id)
REFERENCES synthetic_lab_execution_tasks(project_id, job_id) ON DELETE CASCADE;

CREATE TABLE synthetic_lab_execution_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    result_type text NOT NULL CHECK (result_type IN (
        'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildOutput',
        'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunOutput',
        'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunOutput'
    )),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    result_payload_hash text NOT NULL CHECK (result_payload_hash ~ '^[0-9a-f]{64}$'),
    result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    lease_token uuid NOT NULL,
    fencing_generation bigint NOT NULL CHECK (fencing_generation > 0),
    fact_snapshot_id uuid NOT NULL,
    fact_snapshot_hash text NOT NULL CHECK (fact_snapshot_hash ~ '^[0-9a-f]{64}$'),
    profile_version_id uuid NOT NULL,
    profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
    prompt_release_id uuid NOT NULL,
    prompt_release_hash text NOT NULL CHECK (prompt_release_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, job_id),
    UNIQUE (id, project_id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES synthetic_lab_execution_tasks(job_id, project_id) ON DELETE CASCADE
);

CREATE TABLE synthetic_lab_terminal_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    job_kind text NOT NULL CHECK (btrim(job_kind) <> ''),
    result_type text NOT NULL CHECK (
        result_type ~ '^geo_core\.synthetic_lab\.[A-Za-z0-9_.]+$'
    ),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
    lease_token uuid NOT NULL,
    fencing_generation bigint NOT NULL CHECK (fencing_generation > 0),
    fact_snapshot_id uuid,
    fact_snapshot_hash text,
    profile_version_id uuid,
    profile_hash text,
    prompt_release_id uuid,
    prompt_release_hash text,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (project_id, job_id),
    UNIQUE (id, project_id),
    FOREIGN KEY (job_id, project_id)
        REFERENCES synthetic_lab_job_metadata(job_id, project_id) ON DELETE CASCADE,
    CHECK (
        (fact_snapshot_id IS NULL AND fact_snapshot_hash IS NULL
            AND profile_version_id IS NULL AND profile_hash IS NULL
            AND prompt_release_id IS NULL AND prompt_release_hash IS NULL)
        OR (fact_snapshot_id IS NOT NULL AND fact_snapshot_hash ~ '^[0-9a-f]{64}$'
            AND profile_version_id IS NOT NULL AND profile_hash ~ '^[0-9a-f]{64}$'
            AND prompt_release_id IS NOT NULL AND prompt_release_hash ~ '^[0-9a-f]{64}$')
    )
);

CREATE FUNCTION geo_synthetic_secret_handle_hash(
    reference_id uuid, project_id uuid, purpose text, version integer
) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT encode(
        digest(
            convert_to(
                '{"secret_project_id":"' || project_id::text
                || '","secret_purpose":' || to_json(purpose)::text
                || ',"secret_reference_id":"' || reference_id::text
                || '","secret_version":' || version::text || '}',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
$$;

CREATE FUNCTION geo_assert_synthetic_artifact_master_key_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Synthetic artifact master key versions are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.master_key_version, OLD.algorithm, OLD.canary_nonce,
        OLD.canary_ciphertext, OLD.created_at, OLD.activated_at)
       IS DISTINCT FROM
       (NEW.master_key_version, NEW.algorithm, NEW.canary_nonce,
        NEW.canary_ciphertext, NEW.created_at, NEW.activated_at)
       OR NOT (
           (OLD.status = 'encrypt_decrypt' AND NEW.status = 'decrypt_only'
                AND NEW.retired_at IS NULL)
           OR (OLD.status = 'decrypt_only' AND NEW.status = 'retired'
                AND NEW.retired_at IS NOT NULL)
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact master key transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'retired' AND EXISTS (
        SELECT 1 FROM synthetic_lab_artifact_deks
        WHERE master_key_version = NEW.master_key_version AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'Synthetic artifact master key still wraps an active DEK'
            USING ERRCODE = '23503';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_sync_synthetic_artifact_master_key_version(
    requested_version text,
    requested_status text,
    requested_algorithm text,
    requested_nonce bytea,
    requested_ciphertext bytea,
    requested_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing synthetic_lab_artifact_master_key_versions%ROWTYPE;
DECLARE latest_version bigint;
BEGIN
    IF requested_version IS NULL OR requested_version !~ '^[1-9][0-9]{0,9}$'
       OR requested_status NOT IN ('encrypt_decrypt', 'decrypt_only')
       OR requested_algorithm <> 'AES-256-GCM'
       OR octet_length(requested_nonce) <> 12
       OR octet_length(requested_ciphertext) < 17
       OR requested_at IS NULL THEN
        RAISE EXCEPTION 'Synthetic artifact master key registration is invalid'
            USING ERRCODE = '22023';
    END IF;
    LOCK TABLE synthetic_lab_artifact_master_key_versions IN SHARE ROW EXCLUSIVE MODE;
    SELECT * INTO existing
    FROM synthetic_lab_artifact_master_key_versions
    WHERE master_key_version = requested_version;
    IF FOUND THEN
        IF (existing.status, existing.algorithm, existing.canary_nonce,
            existing.canary_ciphertext)
           IS DISTINCT FROM
           (requested_status, requested_algorithm, requested_nonce,
            requested_ciphertext) THEN
            RAISE EXCEPTION 'Synthetic artifact master key canary conflicts with storage'
                USING ERRCODE = '23514';
        END IF;
        RETURN;
    END IF;
    SELECT max(master_key_version::bigint) INTO latest_version
    FROM synthetic_lab_artifact_master_key_versions;
    IF requested_version::bigint <= coalesce(latest_version, 0) THEN
        RAISE EXCEPTION 'Synthetic artifact master key versions must increase'
            USING ERRCODE = '23514';
    END IF;
    IF requested_status = 'decrypt_only' AND EXISTS (
        SELECT 1 FROM synthetic_lab_artifact_master_key_versions
        WHERE status = 'encrypt_decrypt'
    ) THEN
        RAISE EXCEPTION 'Historical Synthetic artifact keys must precede the active key'
            USING ERRCODE = '23514';
    END IF;
    IF requested_status = 'encrypt_decrypt' THEN
        UPDATE synthetic_lab_artifact_master_key_versions
        SET status = 'decrypt_only'
        WHERE status = 'encrypt_decrypt';
    END IF;
    INSERT INTO synthetic_lab_artifact_master_key_versions(
        master_key_version, algorithm, status, canary_nonce,
        canary_ciphertext, created_at, activated_at
    ) VALUES (
        requested_version, requested_algorithm, requested_status,
        requested_nonce, requested_ciphertext, requested_at, requested_at
    );
END;
$$;

CREATE FUNCTION geo_retire_synthetic_artifact_master_key_version(
    requested_version text, requested_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    UPDATE synthetic_lab_artifact_master_key_versions
    SET status = 'retired', retired_at = requested_at
    WHERE master_key_version = requested_version AND status = 'decrypt_only';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Synthetic artifact master key is not decrypt-only'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_style_collection_task() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE metadata synthetic_lab_job_metadata%ROWTYPE;
DECLARE authorization_record synthetic_lab_authorization_versions%ROWTYPE;
DECLARE current_authorization synthetic_lab_authorization_versions%ROWTYPE;
DECLARE login_secret record;
DECLARE source_host text;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR UPDATE;
    SELECT * INTO STRICT metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT authorization_record FROM synthetic_lab_authorization_versions
    WHERE id = NEW.authorization_id AND project_id = NEW.project_id
      AND channel = NEW.channel AND adapter_release = NEW.adapter_release
      AND version_number = NEW.authorization_version
      AND record_hash = NEW.authorization_hash;
    SELECT * INTO current_authorization
    FROM synthetic_lab_authorization_versions
    WHERE project_id = NEW.project_id AND channel = NEW.channel
      AND adapter_release = NEW.adapter_release
    ORDER BY version_number DESC LIMIT 1;
    IF durable.kind <> 'style.collect' OR durable.status <> 'queued'
       OR durable.input_hash <> NEW.task_input_hash
       OR metadata.domain_job_kind <> 'style_collection'
       OR (metadata.authorization_id, metadata.authorization_version,
           metadata.authorization_hash, metadata.authorization_channel,
           metadata.authorization_adapter_release, metadata.authorization_purpose,
           metadata.authorization_expires_at)
          IS DISTINCT FROM
          (NEW.authorization_id, NEW.authorization_version,
           NEW.authorization_hash, NEW.channel, NEW.adapter_release,
           NEW.authorization_purpose, NEW.authorization_expires_at) THEN
        RAISE EXCEPTION 'Style Collection task does not match its queued admission'
            USING ERRCODE = '23514';
    END IF;
    IF current_authorization.id IS DISTINCT FROM authorization_record.id
       OR authorization_record.state <> 'approved'
       OR authorization_record.expires_at <= NEW.staged_at
       OR NEW.authorization_expires_at <> authorization_record.expires_at
       OR NOT NEW.authorization_purpose = ANY(authorization_record.allowed_purposes) THEN
        RAISE EXCEPTION 'Style Collection task authorization is stale or inactive'
            USING ERRCODE = '42501';
    END IF;
    source_host := lower(split_part(regexp_replace(NEW.source_url, '^https://', ''), '/', 1));
    IF NOT EXISTS (
        SELECT 1 FROM unnest(NEW.allowed_redirect_hosts) AS host
        WHERE lower(btrim(host)) = source_host
    ) OR cardinality(NEW.allowed_redirect_hosts) <> (
        SELECT count(DISTINCT lower(btrim(host)))
        FROM unnest(NEW.allowed_redirect_hosts) AS host
        WHERE btrim(host) <> ''
    ) THEN
        RAISE EXCEPTION 'Style Collection redirect hosts are incomplete or duplicated'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.access_mode = 'authenticated' THEN
        SELECT version.project_id, version.purpose, version.status,
               reference.current_version
        INTO STRICT login_secret
        FROM secret_versions AS version
        JOIN secret_references AS reference
          ON reference.id = version.reference_id
         AND reference.project_id = version.project_id
         AND reference.purpose = version.purpose
        WHERE version.reference_id = NEW.login_secret_reference_id
          AND version.version = NEW.login_secret_version;
        IF login_secret.project_id <> NEW.project_id
           OR login_secret.purpose <> 'style_collection_login.' || NEW.channel
           OR login_secret.status <> 'active'
           OR login_secret.current_version <> NEW.login_secret_version
           OR NEW.login_secret_handle_hash <> geo_synthetic_secret_handle_hash(
                NEW.login_secret_reference_id, NEW.project_id,
                login_secret.purpose, NEW.login_secret_version
           ) THEN
            RAISE EXCEPTION 'Style Collection requires the current active login Secret handle'
                USING ERRCODE = '42501';
        END IF;
    END IF;
    IF NEW.task_payload_hash <> encode(
        digest(convert_to(geo_jsonb_canonical_text(NEW.task_payload), 'UTF8'), 'sha256'),
        'hex'
    ) OR NEW.task_payload ->> '$type' <> NEW.task_type
       OR NEW.task_payload #>> '{fields,project_id,$uuid}' <> NEW.project_id::text
       OR NEW.task_payload #>> '{fields,job_id,$uuid}' <> NEW.job_id::text
       OR NEW.task_payload #>> '{fields,collection_run_id,$uuid}' <> NEW.collection_run_id::text
       OR NEW.task_payload #>> '{fields,style_source_revision_id,$uuid}'
            <> NEW.style_source_revision_id::text
       OR NEW.task_payload #>> '{fields,source_url}' <> NEW.source_url
       OR NEW.task_payload #>> '{fields,source_locator_hash}' <> NEW.source_locator_hash
       OR NEW.task_payload #>> '{fields,adapter_release}' <> NEW.adapter_release
       OR NEW.task_payload #>> '{fields,raw_artifact_id,$uuid}' <> NEW.raw_artifact_id::text
       OR NEW.task_payload #>> '{fields,derived_artifact_id,$uuid}'
            <> NEW.derived_artifact_id::text THEN
        RAISE EXCEPTION 'Style Collection task encoded payload changed normalized lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_raw_artifact_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE task synthetic_lab_style_collection_tasks%ROWTYPE;
DECLARE decision synthetic_lab_artifact_governance_decisions%ROWTYPE;
DECLARE expected_form text;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR UPDATE;
    SELECT * INTO STRICT task FROM synthetic_lab_style_collection_tasks
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT decision FROM synthetic_lab_artifact_governance_decisions
    WHERE artifact_id = NEW.artifact_id AND project_id = NEW.project_id;
    expected_form := CASE NEW.artifact_id
        WHEN task.raw_artifact_id THEN 'raw'
        WHEN task.derived_artifact_id THEN 'derived'
        ELSE NULL
    END;
    IF durable.status NOT IN ('running', 'finalizing')
       OR durable.cancel_requested_at IS NOT NULL
       OR durable.lease_token IS DISTINCT FROM NEW.generation_lease_token
       OR durable.fencing_generation <> NEW.fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= NEW.created_at
       OR expected_form IS NULL OR expected_form <> NEW.artifact_form
       OR NEW.lifecycle_state <> 'persisted' OR NEW.record_version <> 1 THEN
        RAISE EXCEPTION 'Synthetic artifact writer lost lease/fence or task ownership'
            USING ERRCODE = '40001';
    END IF;
    IF NOT decision.persistence_allowed
       OR (NEW.classification, NEW.storage_tier, NEW.persisted_content_hash,
           NEW.captured_at, NEW.ttl_days, NEW.expires_at, NEW.allowed_audiences)
          IS DISTINCT FROM
          (decision.classification, decision.storage_tier,
           decision.persisted_content_hash, decision.captured_at,
           decision.ttl_days, decision.expires_at, decision.allowed_audiences) THEN
        RAISE EXCEPTION 'Synthetic artifact contradicts its governance decision'
            USING ERRCODE = '23514';
    END IF;
    IF cardinality(NEW.allowed_audiences) <> (
        SELECT count(DISTINCT audience) FROM unnest(NEW.allowed_audiences) AS audience
    ) THEN
        RAISE EXCEPTION 'Synthetic artifact audience contains duplicates'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_artifact_dek_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status <> 'active' OR NEW.destroyed_at IS NOT NULL
       OR NOT EXISTS (
            SELECT 1 FROM synthetic_lab_artifact_master_key_versions AS key_version
            WHERE key_version.master_key_version = NEW.master_key_version
              AND key_version.status IN ('encrypt_decrypt', 'decrypt_only')
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact DEK requires a usable master key version'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_artifact_dek_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE artifact synthetic_lab_raw_artifacts%ROWTYPE;
BEGIN
    SELECT * INTO STRICT artifact FROM synthetic_lab_raw_artifacts
    WHERE project_id = NEW.project_id AND artifact_id = NEW.artifact_id
      AND fencing_generation = NEW.fencing_generation;
    IF artifact.storage_tier <> 'restricted_independent_dek'
       OR artifact.artifact_key_ref <> NEW.key_ref
       OR artifact.lifecycle_state = 'deleted' AND NEW.status <> 'destroyed'
       OR artifact.lifecycle_state <> 'deleted' AND NEW.status <> 'active' THEN
        RAISE EXCEPTION 'Synthetic artifact and independent DEK lifecycle diverged'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_raw_artifact_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Synthetic artifact metadata cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.record_version <> OLD.record_version + 1
       OR (NEW.project_id, NEW.artifact_id, NEW.job_id,
           NEW.generation_lease_token, NEW.fencing_generation, NEW.artifact_form,
           NEW.classification, NEW.storage_tier, NEW.persisted_content_hash,
           NEW.stored_object_hash, NEW.manifest_hash, NEW.media_type,
           NEW.byte_size, NEW.record_count, NEW.source_identity_hash,
           NEW.producer_release, NEW.encryption_algorithm, NEW.captured_at,
           NEW.created_at, NEW.ttl_days, NEW.expires_at, NEW.allowed_audiences)
          IS DISTINCT FROM
          (OLD.project_id, OLD.artifact_id, OLD.job_id,
           OLD.generation_lease_token, OLD.fencing_generation, OLD.artifact_form,
           OLD.classification, OLD.storage_tier, OLD.persisted_content_hash,
           OLD.stored_object_hash, OLD.manifest_hash, OLD.media_type,
           OLD.byte_size, OLD.record_count, OLD.source_identity_hash,
           OLD.producer_release, OLD.encryption_algorithm, OLD.captured_at,
           OLD.created_at, OLD.ttl_days, OLD.expires_at, OLD.allowed_audiences)
       OR NOT (
            (OLD.lifecycle_state = 'persisted'
                AND NEW.lifecycle_state IN ('winning', 'orphaned'))
            OR (OLD.lifecycle_state IN ('winning', 'orphaned')
                AND NEW.lifecycle_state = 'deletion_pending')
            OR (OLD.lifecycle_state = 'deletion_pending'
                AND NEW.lifecycle_state = 'deleted')
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact lifecycle transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.lifecycle_state <> 'deleted' AND (
        NEW.manifest_uri, NEW.payload_uri, NEW.artifact_key_ref, NEW.tier_key_version
    ) IS DISTINCT FROM (
        OLD.manifest_uri, OLD.payload_uri, OLD.artifact_key_ref, OLD.tier_key_version
    ) THEN
        RAISE EXCEPTION 'Synthetic artifact storage references are immutable before deletion'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_artifact_dek_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Synthetic artifact DEK envelopes cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.key_ref, OLD.project_id, OLD.artifact_id, OLD.fencing_generation,
        OLD.master_key_version, OLD.algorithm, OLD.created_at)
       IS DISTINCT FROM
       (NEW.key_ref, NEW.project_id, NEW.artifact_id, NEW.fencing_generation,
        NEW.master_key_version, NEW.algorithm, NEW.created_at)
       OR OLD.status <> 'active' OR NEW.status <> 'destroyed'
       OR NEW.wrapped_dek IS NOT NULL OR NEW.wrap_nonce IS NOT NULL
       OR NEW.destroyed_at IS NULL THEN
        RAISE EXCEPTION 'Synthetic artifact DEK transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_artifact_outbox_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Synthetic artifact deletion records cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.id, OLD.project_id, OLD.artifact_id, OLD.artifact_generation,
        OLD.manifest_hash, OLD.reason, OLD.created_at)
       IS DISTINCT FROM
       (NEW.id, NEW.project_id, NEW.artifact_id, NEW.artifact_generation,
        NEW.manifest_hash, NEW.reason, NEW.created_at)
       OR NOT (
            (OLD.status IN ('pending', 'failed') AND NEW.status = 'leased'
                AND NEW.attempt_count = OLD.attempt_count + 1
                AND NEW.fencing_generation = OLD.fencing_generation + 1)
            OR (OLD.status = 'leased' AND OLD.lease_expires_at <= clock_timestamp()
                AND NEW.status = 'leased'
                AND NEW.attempt_count = OLD.attempt_count + 1
                AND NEW.fencing_generation = OLD.fencing_generation + 1)
            OR (OLD.status = 'leased' AND NEW.status IN ('failed', 'completed')
                AND NEW.attempt_count = OLD.attempt_count
                AND NEW.fencing_generation = OLD.fencing_generation)
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact deletion transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_style_collection_result() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE task synthetic_lab_style_collection_tasks%ROWTYPE;
DECLARE authorization_record synthetic_lab_authorization_versions%ROWTYPE;
DECLARE current_authorization synthetic_lab_authorization_versions%ROWTYPE;
DECLARE login_secret record;
DECLARE promoted integer;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR UPDATE;
    SELECT * INTO STRICT task FROM synthetic_lab_style_collection_tasks
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'synthetic-auth:' || NEW.project_id::text || ':' || task.channel
            || ':' || task.adapter_release, 0
    ));
    SELECT * INTO STRICT authorization_record FROM synthetic_lab_authorization_versions
    WHERE id = task.authorization_id AND project_id = NEW.project_id
      AND channel = task.channel AND adapter_release = task.adapter_release
      AND version_number = task.authorization_version
      AND record_hash = task.authorization_hash;
    SELECT * INTO current_authorization
    FROM synthetic_lab_authorization_versions
    WHERE project_id = NEW.project_id AND channel = task.channel
      AND adapter_release = task.adapter_release
    ORDER BY version_number DESC LIMIT 1;
    IF durable.status NOT IN ('running', 'finalizing')
       OR durable.cancel_requested_at IS NOT NULL
       OR durable.lease_token IS DISTINCT FROM NEW.lease_token
       OR durable.fencing_generation <> NEW.fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= NEW.created_at
       OR task.collection_run_id <> NEW.collection_run_id
       OR current_authorization.id IS DISTINCT FROM authorization_record.id
       OR authorization_record.state <> 'approved'
       OR authorization_record.expires_at <= NEW.created_at
       OR NOT task.authorization_purpose = ANY(authorization_record.allowed_purposes) THEN
        RAISE EXCEPTION 'Style Collection result lost lease, fence, or authorization'
            USING ERRCODE = '40001';
    END IF;
    IF task.access_mode = 'authenticated' THEN
        SELECT project_id, purpose, status INTO STRICT login_secret
        FROM secret_versions
        WHERE reference_id = task.login_secret_reference_id
          AND version = task.login_secret_version;
        IF login_secret.project_id <> NEW.project_id
           OR login_secret.purpose <> 'style_collection_login.' || task.channel
           OR login_secret.status NOT IN ('active', 'superseded')
           OR task.login_secret_handle_hash <> geo_synthetic_secret_handle_hash(
                task.login_secret_reference_id, NEW.project_id,
                login_secret.purpose, task.login_secret_version
           ) THEN
            RAISE EXCEPTION 'Style Collection login Secret is revoked or unavailable'
                USING ERRCODE = '42501';
        END IF;
    END IF;
    IF NEW.result_payload_hash <> encode(
        digest(convert_to(geo_jsonb_canonical_text(NEW.result_payload), 'UTF8'), 'sha256'),
        'hex'
    ) OR NEW.result_payload ->> '$type' <> NEW.result_type
       OR NEW.result_payload #>> '{fields,project_id,$uuid}' <> NEW.project_id::text
       OR NEW.result_payload #>> '{fields,collection_run_id,$uuid}'
            <> NEW.collection_run_id::text THEN
        RAISE EXCEPTION 'Style Collection encoded result changed normalized lineage'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.outcome = 'captured' THEN
        UPDATE synthetic_lab_raw_artifacts
        SET lifecycle_state = 'winning', winning_result_id = NEW.id,
            winning_at = NEW.created_at, record_version = record_version + 1
        WHERE project_id = NEW.project_id AND job_id = NEW.job_id
          AND generation_lease_token = NEW.lease_token
          AND fencing_generation = NEW.fencing_generation
          AND lifecycle_state = 'persisted' AND artifact_form = 'derived'
          AND artifact_id = task.derived_artifact_id
          AND manifest_hash = NEW.derived_manifest_hash
          AND persisted_content_hash = NEW.derived_content_hash;
        GET DIAGNOSTICS promoted = ROW_COUNT;
        IF promoted <> 1 THEN
            RAISE EXCEPTION 'Style Collection result lacks its exact derived artifact generation'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.raw_manifest_hash IS NOT NULL THEN
            UPDATE synthetic_lab_raw_artifacts
            SET lifecycle_state = 'winning', winning_result_id = NEW.id,
                winning_at = NEW.created_at, record_version = record_version + 1
            WHERE project_id = NEW.project_id AND job_id = NEW.job_id
              AND generation_lease_token = NEW.lease_token
              AND fencing_generation = NEW.fencing_generation
              AND lifecycle_state = 'persisted' AND artifact_form = 'raw'
              AND artifact_id = task.raw_artifact_id
              AND manifest_hash = NEW.raw_manifest_hash;
            GET DIAGNOSTICS promoted = ROW_COUNT;
            IF promoted <> 1 THEN
                RAISE EXCEPTION 'Style Collection result lacks its exact raw artifact generation'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        UPDATE synthetic_lab_raw_artifacts
        SET lifecycle_state = 'orphaned', orphaned_at = NEW.created_at,
            orphan_reason_code = 'unselected_attempt_artifact',
            record_version = record_version + 1
        WHERE project_id = NEW.project_id AND job_id = NEW.job_id
          AND generation_lease_token = NEW.lease_token
          AND fencing_generation = NEW.fencing_generation
          AND lifecycle_state = 'persisted';
        INSERT INTO synthetic_lab_artifact_deletion_outbox(
            id, project_id, artifact_id, artifact_generation, manifest_hash,
            reason, status, next_attempt_at
        )
        SELECT gen_random_uuid(), artifact.project_id, artifact.artifact_id,
               artifact.fencing_generation, artifact.manifest_hash,
               'orphaned', 'pending', NEW.created_at
        FROM synthetic_lab_raw_artifacts AS artifact
        WHERE artifact.project_id = NEW.project_id AND artifact.job_id = NEW.job_id
          AND artifact.generation_lease_token = NEW.lease_token
          AND artifact.fencing_generation = NEW.fencing_generation
          AND artifact.lifecycle_state = 'orphaned'
          AND artifact.orphan_reason_code = 'unselected_attempt_artifact'
        ON CONFLICT (project_id, artifact_id, artifact_generation)
            WHERE status IN ('pending', 'leased', 'failed') DO NOTHING;
    ELSIF EXISTS (
        SELECT 1 FROM synthetic_lab_raw_artifacts
        WHERE project_id = NEW.project_id AND job_id = NEW.job_id
          AND generation_lease_token = NEW.lease_token
          AND fencing_generation = NEW.fencing_generation
          AND lifecycle_state = 'persisted'
    ) THEN
        RAISE EXCEPTION 'Blocked Style Collection cannot retain persisted attempt artifacts'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_style_collection_result_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id;
    IF durable.status <> 'succeeded'
       OR durable.result_ref IS DISTINCT FROM
            'synthetic://style-collection/' || NEW.result_hash THEN
        RAISE EXCEPTION 'Style Collection result lacks matching Durable Job completion'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_mark_synthetic_artifact_attempt_orphaned(
    p_project_id uuid,
    p_job_id uuid,
    p_artifact_generation bigint,
    p_reason_code text
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE changed integer;
BEGIN
    IF p_artifact_generation < 1
       OR p_reason_code !~ '^[a-z][a-z0-9_]{0,62}$' THEN
        RAISE EXCEPTION 'invalid Synthetic artifact orphan input'
            USING ERRCODE = '22023';
    END IF;
    WITH orphaned AS (
        UPDATE synthetic_lab_raw_artifacts
        SET lifecycle_state = 'orphaned', orphaned_at = clock_timestamp(),
            orphan_reason_code = p_reason_code,
            record_version = record_version + 1
        WHERE project_id = p_project_id AND job_id = p_job_id
          AND fencing_generation = p_artifact_generation
          AND lifecycle_state = 'persisted'
        RETURNING *
    ), queued AS (
        INSERT INTO synthetic_lab_artifact_deletion_outbox(
            id, project_id, artifact_id, artifact_generation, manifest_hash,
            reason, status, next_attempt_at
        )
        SELECT gen_random_uuid(), project_id, artifact_id, fencing_generation,
               manifest_hash, 'orphaned', 'pending', clock_timestamp()
        FROM orphaned
        ON CONFLICT (project_id, artifact_id, artifact_generation)
            WHERE status IN ('pending', 'leased', 'failed') DO NOTHING
        RETURNING 1
    )
    SELECT count(*) INTO changed FROM orphaned;
    RETURN changed;
END;
$$;

CREATE FUNCTION geo_stage_synthetic_artifact_expiry(
    p_now timestamptz,
    p_limit integer
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE artifact record;
DECLARE changed integer := 0;
BEGIN
    IF p_now IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'invalid Synthetic artifact expiry sweep input'
            USING ERRCODE = '22023';
    END IF;
    FOR artifact IN
        SELECT candidate.* FROM synthetic_lab_raw_artifacts AS candidate
        WHERE candidate.lifecycle_state IN ('winning', 'orphaned')
          AND candidate.expires_at IS NOT NULL AND candidate.expires_at <= p_now
          AND NOT EXISTS (
              SELECT 1 FROM synthetic_lab_artifact_legal_holds AS hold
              WHERE hold.project_id = candidate.project_id
                AND hold.artifact_id = candidate.artifact_id
                AND hold.artifact_generation = candidate.fencing_generation
                AND hold.approved_at <= p_now AND hold.expires_at > p_now
          )
        ORDER BY candidate.expires_at, candidate.project_id,
                 candidate.artifact_id, candidate.fencing_generation
        FOR UPDATE SKIP LOCKED
        LIMIT p_limit
    LOOP
        UPDATE synthetic_lab_raw_artifacts
        SET lifecycle_state = 'deletion_pending', deletion_pending_at = p_now,
            record_version = record_version + 1
        WHERE project_id = artifact.project_id AND artifact_id = artifact.artifact_id
          AND fencing_generation = artifact.fencing_generation;
        INSERT INTO synthetic_lab_artifact_deletion_outbox(
            id, project_id, artifact_id, artifact_generation, manifest_hash,
            reason, status, next_attempt_at
        ) VALUES (
            gen_random_uuid(), artifact.project_id, artifact.artifact_id,
            artifact.fencing_generation, artifact.manifest_hash,
            'retention_expired', 'pending', p_now
        ) ON CONFLICT (project_id, artifact_id, artifact_generation)
            WHERE status IN ('pending', 'leased', 'failed') DO NOTHING;
        changed := changed + 1;
    END LOOP;
    RETURN changed;
END;
$$;

CREATE FUNCTION geo_claim_synthetic_artifact_deletions(
    p_worker_id text,
    p_batch_size integer,
    p_lease_seconds integer
) RETURNS TABLE (
    outbox_id uuid,
    project_id uuid,
    artifact_id uuid,
    artifact_generation bigint,
    manifest_hash text,
    payload_uri text,
    manifest_uri text,
    storage_tier text,
    artifact_key_ref text,
    tier_key_version text,
    persisted_content_hash text,
    lease_token uuid,
    deletion_fencing_generation bigint,
    lease_expires_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF btrim(coalesce(p_worker_id, '')) = '' OR octet_length(p_worker_id) > 240
       OR p_batch_size NOT BETWEEN 1 AND 100
       OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'invalid Synthetic artifact deletion claim input'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH candidates AS (
        SELECT item.id
        FROM synthetic_lab_artifact_deletion_outbox AS item
        JOIN synthetic_lab_raw_artifacts AS artifact
          ON artifact.project_id = item.project_id
         AND artifact.artifact_id = item.artifact_id
         AND artifact.fencing_generation = item.artifact_generation
        WHERE (
            (
                item.status IN ('pending', 'failed')
                AND item.next_attempt_at <= clock_timestamp()
            ) OR (
                item.status = 'leased' AND item.lease_expires_at <= clock_timestamp()
            )
          )
          AND artifact.lifecycle_state IN ('orphaned', 'deletion_pending')
          AND NOT EXISTS (
              SELECT 1 FROM synthetic_lab_artifact_legal_holds AS hold
              WHERE hold.project_id = artifact.project_id
                AND hold.artifact_id = artifact.artifact_id
                AND hold.artifact_generation = artifact.fencing_generation
                AND hold.approved_at <= clock_timestamp()
                AND hold.expires_at > clock_timestamp()
          )
        ORDER BY item.next_attempt_at, item.id
        FOR UPDATE OF item SKIP LOCKED
        LIMIT p_batch_size
    ), claimed AS (
        UPDATE synthetic_lab_artifact_deletion_outbox AS item
        SET status = 'leased', lease_owner = p_worker_id,
            lease_token = gen_random_uuid(),
            lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
            attempt_count = item.attempt_count + 1,
            fencing_generation = item.fencing_generation + 1,
            last_error_code = NULL
        FROM candidates
        WHERE item.id = candidates.id
        RETURNING item.*
    ), prepared AS (
        UPDATE synthetic_lab_raw_artifacts AS artifact
        SET lifecycle_state = 'deletion_pending',
            deletion_pending_at = clock_timestamp(),
            record_version = artifact.record_version + 1
        FROM claimed
        WHERE artifact.project_id = claimed.project_id
          AND artifact.artifact_id = claimed.artifact_id
          AND artifact.fencing_generation = claimed.artifact_generation
          AND artifact.lifecycle_state = 'orphaned'
        RETURNING artifact.project_id, artifact.artifact_id,
                  artifact.fencing_generation
    )
    SELECT claimed.id, claimed.project_id, claimed.artifact_id,
           claimed.artifact_generation, claimed.manifest_hash,
           artifact.payload_uri, artifact.manifest_uri, artifact.storage_tier,
           artifact.artifact_key_ref, artifact.tier_key_version,
           artifact.persisted_content_hash, claimed.lease_token,
           claimed.fencing_generation, claimed.lease_expires_at
    FROM claimed
    JOIN synthetic_lab_raw_artifacts AS artifact
      ON artifact.project_id = claimed.project_id
     AND artifact.artifact_id = claimed.artifact_id
     AND artifact.fencing_generation = claimed.artifact_generation
    LEFT JOIN prepared
      ON prepared.project_id = claimed.project_id
     AND prepared.artifact_id = claimed.artifact_id
     AND prepared.fencing_generation = claimed.artifact_generation
    ORDER BY claimed.next_attempt_at, claimed.id;
END;
$$;

CREATE FUNCTION geo_complete_synthetic_artifact_deletion(
    p_project_id uuid,
    p_artifact_id uuid,
    p_artifact_generation bigint,
    p_lease_token uuid,
    p_tombstone_hash text,
    p_deleted_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE item synthetic_lab_artifact_deletion_outbox%ROWTYPE;
DECLARE artifact synthetic_lab_raw_artifacts%ROWTYPE;
DECLARE destroyed_deks integer;
DECLARE receipt_hash text;
BEGIN
    IF p_artifact_generation < 1 OR p_lease_token IS NULL
       OR p_tombstone_hash !~ '^[0-9a-f]{64}$' OR p_deleted_at IS NULL THEN
        RAISE EXCEPTION 'invalid Synthetic artifact deletion completion input'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT item
    FROM synthetic_lab_artifact_deletion_outbox
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND artifact_generation = p_artifact_generation
      AND status = 'leased' FOR UPDATE;
    SELECT * INTO STRICT artifact
    FROM synthetic_lab_raw_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND fencing_generation = p_artifact_generation FOR UPDATE;
    IF item.lease_token <> p_lease_token
       OR item.lease_expires_at <= clock_timestamp()
       OR item.manifest_hash <> artifact.manifest_hash
       OR artifact.lifecycle_state NOT IN ('orphaned', 'deletion_pending')
       OR EXISTS (
            SELECT 1 FROM synthetic_lab_artifact_legal_holds AS hold
            WHERE hold.project_id = p_project_id AND hold.artifact_id = p_artifact_id
              AND hold.artifact_generation = p_artifact_generation
              AND hold.approved_at <= p_deleted_at AND hold.expires_at > p_deleted_at
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact deletion lease was fenced or held'
            USING ERRCODE = '40001';
    END IF;
    UPDATE synthetic_lab_artifact_deks
    SET status = 'destroyed', wrapped_dek = NULL, wrap_nonce = NULL,
        destroyed_at = p_deleted_at
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND fencing_generation = p_artifact_generation AND status = 'active';
    GET DIAGNOSTICS destroyed_deks = ROW_COUNT;
    IF (artifact.storage_tier = 'restricted_independent_dek' AND destroyed_deks <> 1)
       OR (artifact.storage_tier <> 'restricted_independent_dek' AND destroyed_deks <> 0) THEN
        RAISE EXCEPTION 'Synthetic artifact DEK destruction did not match storage tier'
            USING ERRCODE = '23514';
    END IF;
    receipt_hash := encode(digest(convert_to(
        p_project_id::text || ':' || p_artifact_id::text || ':'
        || p_artifact_generation::text || ':' || p_tombstone_hash || ':'
        || p_deleted_at::text, 'UTF8'), 'sha256'), 'hex');
    INSERT INTO synthetic_lab_artifact_tombstones(
        id, project_id, artifact_id, artifact_generation,
        original_content_hash, classification, tombstone_hash,
        deletion_receipt_hash, deleted_at, object_deleted,
        artifact_dek_destroyed, recoverable_body_retained
    ) VALUES (
        gen_random_uuid(), p_project_id, p_artifact_id, p_artifact_generation,
        artifact.persisted_content_hash, artifact.classification, p_tombstone_hash,
        receipt_hash, p_deleted_at, true, true, false
    );
    UPDATE synthetic_lab_raw_artifacts
    SET lifecycle_state = 'deleted', manifest_uri = NULL, payload_uri = NULL,
        artifact_key_ref = NULL, tier_key_version = NULL,
        deletion_pending_at = coalesce(deletion_pending_at, p_deleted_at),
        deleted_at = p_deleted_at, record_version = record_version + 1
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND fencing_generation = p_artifact_generation;
    UPDATE synthetic_lab_artifact_deletion_outbox
    SET status = 'completed', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, last_error_code = NULL,
        completed_at = p_deleted_at
    WHERE id = item.id;
END;
$$;

CREATE FUNCTION geo_fail_synthetic_artifact_deletion(
    p_project_id uuid,
    p_artifact_id uuid,
    p_artifact_generation bigint,
    p_lease_token uuid,
    p_error_code text,
    p_next_attempt_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF p_artifact_generation < 1
       OR p_error_code !~ '^[a-z][a-z0-9_]{0,62}$'
       OR p_next_attempt_at IS NULL OR p_next_attempt_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'invalid Synthetic artifact deletion failure input'
            USING ERRCODE = '22023';
    END IF;
    UPDATE synthetic_lab_artifact_deletion_outbox
    SET status = 'failed', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, last_error_code = p_error_code,
        next_attempt_at = p_next_attempt_at
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND artifact_generation = p_artifact_generation
      AND status = 'leased' AND lease_token = p_lease_token
      AND lease_expires_at > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Synthetic artifact deletion failure lease was fenced'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

-- A remote delete is not an atomic operation.  Preserve the manifest/object
-- locations after the per-artifact DEK has been erased so a later lease can
-- finish deleting both objects without ever making the bytes readable again.
ALTER TABLE synthetic_lab_raw_artifacts
DROP CONSTRAINT synthetic_lab_raw_artifacts_lifecycle_state_check;
ALTER TABLE synthetic_lab_raw_artifacts
ADD CONSTRAINT synthetic_lab_raw_artifacts_lifecycle_state_check CHECK (
    lifecycle_state IN (
        'persisted', 'winning', 'orphaned', 'deletion_pending',
        'object_delete_pending', 'deleted'
    )
);
ALTER TABLE synthetic_lab_raw_artifacts
DROP CONSTRAINT synthetic_lab_raw_artifacts_status_shape;
ALTER TABLE synthetic_lab_raw_artifacts
ADD CONSTRAINT synthetic_lab_raw_artifacts_status_shape CHECK (
    (lifecycle_state = 'persisted'
        AND manifest_uri IS NOT NULL AND payload_uri IS NOT NULL
        AND winning_result_id IS NULL AND winning_at IS NULL
        AND orphaned_at IS NULL AND orphan_reason_code IS NULL
        AND deletion_pending_at IS NULL AND deleted_at IS NULL)
    OR (lifecycle_state = 'winning'
        AND manifest_uri IS NOT NULL AND payload_uri IS NOT NULL
        AND winning_result_id IS NOT NULL AND winning_at IS NOT NULL
        AND orphaned_at IS NULL AND orphan_reason_code IS NULL
        AND deletion_pending_at IS NULL AND deleted_at IS NULL)
    OR (lifecycle_state = 'orphaned'
        AND manifest_uri IS NOT NULL AND payload_uri IS NOT NULL
        AND winning_result_id IS NULL AND winning_at IS NULL
        AND orphaned_at IS NOT NULL AND orphan_reason_code IS NOT NULL
        AND deletion_pending_at IS NULL AND deleted_at IS NULL)
    OR (lifecycle_state IN ('deletion_pending', 'object_delete_pending')
        AND manifest_uri IS NOT NULL AND payload_uri IS NOT NULL
        AND deletion_pending_at IS NOT NULL AND deleted_at IS NULL)
    OR (lifecycle_state = 'deleted'
        AND manifest_uri IS NULL AND payload_uri IS NULL
        AND deletion_pending_at IS NOT NULL AND deleted_at IS NOT NULL)
);

CREATE TABLE synthetic_lab_artifact_crypto_erasures (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    artifact_generation bigint NOT NULL CHECK (artifact_generation > 0),
    deletion_outbox_id uuid NOT NULL,
    deletion_fencing_generation bigint NOT NULL CHECK (deletion_fencing_generation > 0),
    independent_dek_destroyed boolean NOT NULL,
    receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
    erased_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, artifact_id, artifact_generation),
    UNIQUE (project_id, deletion_outbox_id, deletion_fencing_generation),
    FOREIGN KEY (artifact_id, project_id, artifact_generation)
        REFERENCES synthetic_lab_raw_artifacts(artifact_id, project_id, fencing_generation),
    FOREIGN KEY (deletion_outbox_id, project_id)
        REFERENCES synthetic_lab_artifact_deletion_outbox(id, project_id)
);

ALTER TABLE synthetic_lab_artifact_tombstones
DROP CONSTRAINT synthetic_lab_artifact_tombstones_artifact_dek_destroyed_check;
ALTER TABLE synthetic_lab_artifact_tombstones
ADD CONSTRAINT synthetic_lab_artifact_tombstones_artifact_dek_destroyed_check CHECK (
    artifact_dek_destroyed IS NOT NULL
);

CREATE OR REPLACE FUNCTION geo_assert_synthetic_artifact_dek_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE artifact synthetic_lab_raw_artifacts%ROWTYPE;
BEGIN
    SELECT * INTO STRICT artifact FROM synthetic_lab_raw_artifacts
    WHERE project_id = NEW.project_id AND artifact_id = NEW.artifact_id
      AND fencing_generation = NEW.fencing_generation;
    IF artifact.storage_tier <> 'restricted_independent_dek'
       OR artifact.artifact_key_ref <> NEW.key_ref
       OR (artifact.lifecycle_state IN ('object_delete_pending', 'deleted')
           AND NEW.status <> 'destroyed')
       OR (artifact.lifecycle_state NOT IN ('object_delete_pending', 'deleted')
           AND NEW.status <> 'active') THEN
        RAISE EXCEPTION 'Synthetic artifact and independent DEK lifecycle diverged'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION geo_assert_synthetic_raw_artifact_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Synthetic artifact metadata cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.record_version <> OLD.record_version + 1
       OR (NEW.project_id, NEW.artifact_id, NEW.job_id,
           NEW.generation_lease_token, NEW.fencing_generation, NEW.artifact_form,
           NEW.classification, NEW.storage_tier, NEW.persisted_content_hash,
           NEW.stored_object_hash, NEW.manifest_hash, NEW.media_type,
           NEW.byte_size, NEW.record_count, NEW.source_identity_hash,
           NEW.producer_release, NEW.encryption_algorithm, NEW.captured_at,
           NEW.created_at, NEW.ttl_days, NEW.expires_at, NEW.allowed_audiences)
          IS DISTINCT FROM
          (OLD.project_id, OLD.artifact_id, OLD.job_id,
           OLD.generation_lease_token, OLD.fencing_generation, OLD.artifact_form,
           OLD.classification, OLD.storage_tier, OLD.persisted_content_hash,
           OLD.stored_object_hash, OLD.manifest_hash, OLD.media_type,
           OLD.byte_size, OLD.record_count, OLD.source_identity_hash,
           OLD.producer_release, OLD.encryption_algorithm, OLD.captured_at,
           OLD.created_at, OLD.ttl_days, OLD.expires_at, OLD.allowed_audiences)
       OR NOT (
            (OLD.lifecycle_state = 'persisted'
                AND NEW.lifecycle_state IN ('winning', 'orphaned'))
            OR (OLD.lifecycle_state IN ('winning', 'orphaned')
                AND NEW.lifecycle_state = 'deletion_pending')
            OR (OLD.lifecycle_state = 'deletion_pending'
                AND NEW.lifecycle_state = 'object_delete_pending')
            OR (OLD.lifecycle_state = 'object_delete_pending'
                AND NEW.lifecycle_state = 'deleted')
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact lifecycle transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.lifecycle_state <> 'deleted' AND (
        NEW.manifest_uri, NEW.payload_uri, NEW.artifact_key_ref, NEW.tier_key_version
    ) IS DISTINCT FROM (
        OLD.manifest_uri, OLD.payload_uri, OLD.artifact_key_ref, OLD.tier_key_version
    ) THEN
        RAISE EXCEPTION 'Synthetic artifact storage references are immutable before deletion'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_stage_due_synthetic_artifact_expirations(
    p_now timestamptz,
    p_limit integer
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    RETURN geo_stage_synthetic_artifact_expiry(p_now, p_limit);
END;
$$;

CREATE FUNCTION geo_claim_synthetic_artifact_deletions(
    p_worker_id text,
    p_now timestamptz,
    p_batch_size integer,
    p_lease_seconds integer
) RETURNS TABLE (
    outbox_id uuid,
    project_id uuid,
    artifact_id uuid,
    artifact_generation bigint,
    lease_token uuid,
    deletion_fencing_generation bigint,
    lease_expires_at timestamptz,
    payload_uri text,
    manifest_uri text,
    storage_tier text,
    content_hash text,
    manifest_hash text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF p_now IS NULL OR btrim(coalesce(p_worker_id, '')) = ''
       OR octet_length(p_worker_id) > 240 OR p_batch_size NOT BETWEEN 1 AND 100
       OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'invalid Synthetic artifact deletion claim input'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH candidates AS (
        SELECT item.id
        FROM synthetic_lab_artifact_deletion_outbox AS item
        JOIN synthetic_lab_raw_artifacts AS artifact
          ON artifact.project_id = item.project_id
         AND artifact.artifact_id = item.artifact_id
         AND artifact.fencing_generation = item.artifact_generation
        WHERE ((item.status IN ('pending', 'failed') AND item.next_attempt_at <= p_now)
               OR (item.status = 'leased' AND item.lease_expires_at <= p_now))
          AND artifact.lifecycle_state IN ('deletion_pending', 'object_delete_pending')
          AND (
              artifact.lifecycle_state = 'object_delete_pending'
              OR NOT EXISTS (
                  SELECT 1 FROM synthetic_lab_artifact_legal_holds AS hold
                  WHERE hold.project_id = artifact.project_id
                    AND hold.artifact_id = artifact.artifact_id
                    AND hold.artifact_generation = artifact.fencing_generation
                    AND hold.approved_at <= p_now AND hold.expires_at > p_now
              )
          )
        ORDER BY item.next_attempt_at, item.id
        FOR UPDATE OF item SKIP LOCKED
        LIMIT p_batch_size
    ), claimed AS (
        UPDATE synthetic_lab_artifact_deletion_outbox AS item
        SET status = 'leased', lease_owner = p_worker_id,
            lease_token = gen_random_uuid(),
            lease_expires_at = p_now + make_interval(secs => p_lease_seconds),
            attempt_count = item.attempt_count + 1,
            fencing_generation = item.fencing_generation + 1,
            last_error_code = NULL
        FROM candidates WHERE item.id = candidates.id
        RETURNING item.*
    )
    SELECT claimed.id, claimed.project_id, claimed.artifact_id,
           claimed.artifact_generation, claimed.lease_token,
           claimed.fencing_generation, claimed.lease_expires_at,
           artifact.payload_uri, artifact.manifest_uri, artifact.storage_tier,
           artifact.persisted_content_hash, claimed.manifest_hash
    FROM claimed
    JOIN synthetic_lab_raw_artifacts AS artifact
      ON artifact.project_id = claimed.project_id
     AND artifact.artifact_id = claimed.artifact_id
     AND artifact.fencing_generation = claimed.artifact_generation
    ORDER BY claimed.next_attempt_at, claimed.id;
END;
$$;

CREATE FUNCTION geo_crypto_erase_and_tombstone_synthetic_artifact(
    p_outbox_id uuid,
    p_project_id uuid,
    p_artifact_id uuid,
    p_fencing_generation bigint,
    p_lease_token uuid,
    p_receipt_hash text,
    p_now timestamptz
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE item synthetic_lab_artifact_deletion_outbox%ROWTYPE;
DECLARE artifact synthetic_lab_raw_artifacts%ROWTYPE;
DECLARE changed integer;
DECLARE independent_dek_destroyed boolean := false;
BEGIN
    IF p_outbox_id IS NULL OR p_fencing_generation < 1 OR p_lease_token IS NULL
       OR p_receipt_hash !~ '^[0-9a-f]{64}$' OR p_now IS NULL THEN
        RAISE EXCEPTION 'invalid Synthetic artifact crypto-erasure input'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT item FROM synthetic_lab_artifact_deletion_outbox
    WHERE id = p_outbox_id AND project_id = p_project_id AND artifact_id = p_artifact_id
      AND artifact_generation = p_fencing_generation FOR UPDATE;
    SELECT * INTO STRICT artifact FROM synthetic_lab_raw_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND fencing_generation = p_fencing_generation FOR UPDATE;
    IF item.status <> 'leased' OR item.lease_token IS DISTINCT FROM p_lease_token
       OR item.lease_expires_at IS NULL OR item.lease_expires_at <= p_now THEN
        RAISE EXCEPTION 'Synthetic artifact crypto-erasure lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF artifact.lifecycle_state = 'object_delete_pending' THEN
        IF NOT EXISTS (
            SELECT 1 FROM synthetic_lab_artifact_crypto_erasures
            WHERE project_id = p_project_id AND artifact_id = p_artifact_id
              AND artifact_generation = p_fencing_generation
        ) THEN
            RAISE EXCEPTION 'Synthetic artifact crypto-erasure receipt is missing'
                USING ERRCODE = '23514';
        END IF;
        RETURN false;
    END IF;
    IF artifact.lifecycle_state <> 'deletion_pending'
       OR EXISTS (
           SELECT 1 FROM synthetic_lab_artifact_legal_holds AS hold
           WHERE hold.project_id = p_project_id AND hold.artifact_id = p_artifact_id
             AND hold.artifact_generation = p_fencing_generation
             AND hold.approved_at <= p_now AND hold.expires_at > p_now
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact cannot be crypto-erased in its current policy state'
            USING ERRCODE = '23514';
    END IF;
    IF artifact.storage_tier = 'restricted_independent_dek' THEN
        UPDATE synthetic_lab_artifact_deks
        SET status = 'destroyed', wrapped_dek = NULL, wrap_nonce = NULL, destroyed_at = p_now
        WHERE project_id = p_project_id AND artifact_id = p_artifact_id
          AND fencing_generation = p_fencing_generation AND status = 'active';
        GET DIAGNOSTICS changed = ROW_COUNT;
        IF changed <> 1 THEN
            RAISE EXCEPTION 'Synthetic artifact independent DEK was already unavailable'
                USING ERRCODE = '40001';
        END IF;
        independent_dek_destroyed := true;
    ELSIF EXISTS (
        SELECT 1 FROM synthetic_lab_artifact_deks
        WHERE project_id = p_project_id AND artifact_id = p_artifact_id
          AND fencing_generation = p_fencing_generation
    ) THEN
        RAISE EXCEPTION 'Synthetic project-tier artifact unexpectedly has an independent DEK'
            USING ERRCODE = '23514';
    END IF;
    INSERT INTO synthetic_lab_artifact_crypto_erasures(
        id, project_id, artifact_id, artifact_generation, deletion_outbox_id,
        deletion_fencing_generation, independent_dek_destroyed, receipt_hash, erased_at
    ) VALUES (
        gen_random_uuid(), p_project_id, p_artifact_id, p_fencing_generation, item.id,
        item.fencing_generation, independent_dek_destroyed, p_receipt_hash, p_now
    );
    UPDATE synthetic_lab_raw_artifacts
    SET lifecycle_state = 'object_delete_pending', record_version = record_version + 1
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND fencing_generation = p_fencing_generation;
    RETURN true;
END;
$$;

CREATE FUNCTION geo_complete_synthetic_artifact_object_deletion(
    p_outbox_id uuid,
    p_project_id uuid,
    p_artifact_id uuid,
    p_fencing_generation bigint,
    p_lease_token uuid,
    p_receipt_hash text,
    p_now timestamptz
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE item synthetic_lab_artifact_deletion_outbox%ROWTYPE;
DECLARE artifact synthetic_lab_raw_artifacts%ROWTYPE;
DECLARE crypto synthetic_lab_artifact_crypto_erasures%ROWTYPE;
BEGIN
    IF p_outbox_id IS NULL OR p_fencing_generation < 1 OR p_lease_token IS NULL
       OR p_receipt_hash !~ '^[0-9a-f]{64}$' OR p_now IS NULL THEN
        RAISE EXCEPTION 'invalid Synthetic artifact object deletion input'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT item FROM synthetic_lab_artifact_deletion_outbox
    WHERE id = p_outbox_id AND project_id = p_project_id AND artifact_id = p_artifact_id
      AND artifact_generation = p_fencing_generation FOR UPDATE;
    IF item.status = 'completed' THEN
        RETURN true;
    END IF;
    SELECT * INTO STRICT artifact FROM synthetic_lab_raw_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND fencing_generation = p_fencing_generation FOR UPDATE;
    SELECT * INTO STRICT crypto FROM synthetic_lab_artifact_crypto_erasures
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND artifact_generation = p_fencing_generation;
    IF item.status <> 'leased' OR item.lease_token IS DISTINCT FROM p_lease_token
       OR item.lease_expires_at IS NULL OR item.lease_expires_at <= p_now
       OR artifact.lifecycle_state <> 'object_delete_pending' THEN
        RAISE EXCEPTION 'Synthetic artifact object deletion lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    INSERT INTO synthetic_lab_artifact_tombstones(
        id, project_id, artifact_id, artifact_generation, original_content_hash,
        classification, tombstone_hash, deletion_receipt_hash, deleted_at,
        object_deleted, artifact_dek_destroyed, recoverable_body_retained
    ) VALUES (
        gen_random_uuid(), p_project_id, p_artifact_id, p_fencing_generation,
        artifact.persisted_content_hash, artifact.classification, p_receipt_hash,
        encode(digest(convert_to(crypto.receipt_hash || ':' || p_receipt_hash, 'UTF8'), 'sha256'), 'hex'),
        p_now, true, crypto.independent_dek_destroyed, false
    );
    UPDATE synthetic_lab_raw_artifacts
    SET lifecycle_state = 'deleted', manifest_uri = NULL, payload_uri = NULL,
        artifact_key_ref = NULL, tier_key_version = NULL, deleted_at = p_now,
        record_version = record_version + 1
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
      AND fencing_generation = p_fencing_generation;
    UPDATE synthetic_lab_artifact_deletion_outbox
    SET status = 'completed', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, last_error_code = NULL, completed_at = p_now
    WHERE id = item.id;
    RETURN true;
END;
$$;

CREATE FUNCTION geo_fail_synthetic_artifact_object_deletion(
    p_outbox_id uuid,
    p_project_id uuid,
    p_artifact_id uuid,
    p_fencing_generation bigint,
    p_lease_token uuid,
    p_error_code text,
    p_next_attempt_at timestamptz
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE item synthetic_lab_artifact_deletion_outbox%ROWTYPE;
BEGIN
    IF p_outbox_id IS NULL OR p_fencing_generation < 1 OR p_lease_token IS NULL
       OR p_error_code !~ '^[a-z][a-z0-9_]{0,62}$' OR p_next_attempt_at IS NULL
       OR p_next_attempt_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'invalid Synthetic artifact object deletion failure input'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT item FROM synthetic_lab_artifact_deletion_outbox
    WHERE id = p_outbox_id AND project_id = p_project_id AND artifact_id = p_artifact_id
      AND artifact_generation = p_fencing_generation FOR UPDATE;
    IF item.status <> 'leased' OR item.lease_token IS DISTINCT FROM p_lease_token
       OR item.lease_expires_at IS NULL OR item.lease_expires_at <= clock_timestamp()
       OR NOT EXISTS (
           SELECT 1 FROM synthetic_lab_raw_artifacts
           WHERE project_id = p_project_id AND artifact_id = p_artifact_id
             AND fencing_generation = p_fencing_generation
             AND lifecycle_state = 'object_delete_pending'
       ) OR NOT EXISTS (
           SELECT 1 FROM synthetic_lab_artifact_crypto_erasures
           WHERE project_id = p_project_id AND artifact_id = p_artifact_id
             AND artifact_generation = p_fencing_generation
       ) THEN
        RAISE EXCEPTION 'Synthetic artifact object deletion failure lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    UPDATE synthetic_lab_artifact_deletion_outbox
    SET status = 'failed', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, last_error_code = p_error_code,
        next_attempt_at = p_next_attempt_at
    WHERE id = item.id;
    RETURN true;
END;
$$;

CREATE FUNCTION geo_enqueue_synthetic_artifact_maintenance(
    p_now timestamptz
) RETURNS TABLE (project_id uuid, job_id uuid, replayed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate record;
DECLARE active_job durable_jobs%ROWTYPE;
DECLARE scheduled_id uuid;
DECLARE input_hash text;
BEGIN
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'Synthetic artifact maintenance time is required'
            USING ERRCODE = '22023';
    END IF;
    FOR candidate IN
        SELECT DISTINCT artifact.project_id
        FROM synthetic_lab_raw_artifacts AS artifact
        WHERE (artifact.lifecycle_state IN ('winning', 'orphaned')
               AND artifact.expires_at IS NOT NULL AND artifact.expires_at <= p_now)
           OR artifact.lifecycle_state IN ('deletion_pending', 'object_delete_pending')
    LOOP
        SELECT * INTO active_job FROM durable_jobs AS existing_job
        WHERE existing_job.project_id = candidate.project_id
          AND existing_job.kind = 'synthetic_lab.artifact_maintenance'
          AND existing_job.idempotency_key = 'synthetic-artifact-maintenance:v1'
          AND existing_job.status IN ('queued', 'running', 'finalizing', 'retry_wait')
        ORDER BY existing_job.created_at DESC LIMIT 1 FOR UPDATE;
        IF FOUND THEN
            IF active_job.status IN ('queued', 'retry_wait') THEN
                UPDATE durable_jobs AS wake_job
                SET next_run_at = LEAST(wake_job.next_run_at, p_now),
                    updated_at = p_now
                WHERE wake_job.id = active_job.id;
                INSERT INTO broker_outbox(
                    id, project_id, job_id, topic, payload, idempotency_key, available_at
                ) VALUES (
                    gen_random_uuid(), candidate.project_id, active_job.id,
                    'synthetic_lab.artifact_maintenance',
                    jsonb_build_object('job_id', active_job.id::text,
                        'project_id', candidate.project_id::text),
                    'synthetic-artifact-maintenance:wake:' || active_job.id::text,
                    p_now
                ) ON CONFLICT (project_id, idempotency_key) DO NOTHING;
            END IF;
            project_id := candidate.project_id;
            job_id := active_job.id;
            replayed := true;
            RETURN NEXT;
            CONTINUE;
        END IF;
        input_hash := encode(digest(convert_to(
            'synthetic_lab.artifact_maintenance:v1:' || candidate.project_id::text,
            'UTF8'), 'sha256'), 'hex');
        scheduled_id := gen_random_uuid();
        INSERT INTO durable_jobs(
            id, project_id, kind, status, priority, input_hash, idempotency_key,
            max_attempts, next_run_at, replay_nonce, created_at, updated_at
        ) VALUES (
            scheduled_id, candidate.project_id, 'synthetic_lab.artifact_maintenance',
            'queued', 5, input_hash, 'synthetic-artifact-maintenance:v1', 10, p_now,
            coalesce((SELECT max(prior_job.replay_nonce) + 1 FROM durable_jobs AS prior_job
                      WHERE prior_job.project_id = candidate.project_id
                        AND prior_job.kind = 'synthetic_lab.artifact_maintenance'
                        AND prior_job.idempotency_key = 'synthetic-artifact-maintenance:v1'), 0),
            p_now, p_now
        );
        INSERT INTO broker_outbox(
            id, project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            gen_random_uuid(), candidate.project_id, scheduled_id,
            'synthetic_lab.artifact_maintenance',
            jsonb_build_object('job_id', scheduled_id::text,
                'project_id', candidate.project_id::text),
            'synthetic-artifact-maintenance:wake:' || scheduled_id::text, p_now
        );
        project_id := candidate.project_id;
        job_id := scheduled_id;
        replayed := false;
        RETURN NEXT;
    END LOOP;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_aggregate_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE current_version integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        NEW.project_id::text || ':' || NEW.kind || ':' || NEW.resource_id::text, 0
    ));
    SELECT max(version) INTO current_version
    FROM synthetic_lab_aggregate_versions
    WHERE project_id = NEW.project_id AND kind = NEW.kind AND resource_id = NEW.resource_id;
    IF NEW.version <> coalesce(current_version, 0) + 1 THEN
        RAISE EXCEPTION 'Synthetic Lab aggregate CAS failed' USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_authorization_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE previous synthetic_lab_authorization_versions%ROWTYPE;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        NEW.project_id::text || ':' || NEW.channel || ':' || NEW.adapter_release, 0
    ));
    SELECT * INTO previous
    FROM synthetic_lab_authorization_versions
    WHERE project_id = NEW.project_id AND channel = NEW.channel
      AND adapter_release = NEW.adapter_release
    ORDER BY version_number DESC LIMIT 1;
    IF NOT FOUND THEN
        IF NEW.version_number <> 1 OR NEW.previous_version_id IS NOT NULL
           OR NEW.state <> 'not_assessed' THEN
            RAISE EXCEPTION 'Synthetic Lab authorization must start not_assessed at version 1'
                USING ERRCODE = '40001';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.version_number <> previous.version_number + 1
       OR NEW.previous_version_id IS DISTINCT FROM previous.id
       OR (NEW.state <> 'not_assessed'
           AND NEW.submitted_by IS DISTINCT FROM previous.submitted_by) THEN
        RAISE EXCEPTION 'Synthetic Lab authorization CAS or submitter lineage failed'
            USING ERRCODE = '40001';
    END IF;
    IF NOT (
        (previous.state = 'not_assessed' AND NEW.state IN ('approved', 'assessed_no_basis'))
        OR (previous.state = 'approved' AND NEW.state IN ('expired', 'revoked'))
        OR (previous.state IN ('assessed_no_basis', 'expired', 'revoked')
            AND NEW.state = 'not_assessed')
        OR (previous.state = 'approved' AND previous.expires_at <= NEW.created_at
            AND NEW.state = 'not_assessed')
    ) THEN
        RAISE EXCEPTION 'invalid Synthetic Lab authorization transition'
            USING ERRCODE = '23514';
    END IF;
    IF previous.state = 'not_assessed'
       AND NEW.state IN ('approved', 'assessed_no_basis')
       AND NEW.decided_by = previous.submitted_by THEN
        RAISE EXCEPTION 'Synthetic Lab authorization maker-checker separation failed'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.state IN ('expired', 'revoked') AND (
        NEW.evidence_reference_hash, NEW.allowed_purposes,
        NEW.max_requests_per_period, NEW.period_seconds,
        NEW.max_concurrency, NEW.expires_at
    ) IS DISTINCT FROM (
        previous.evidence_reference_hash, previous.allowed_purposes,
        previous.max_requests_per_period, previous.period_seconds,
        previous.max_concurrency, previous.expires_at
    ) THEN
        RAISE EXCEPTION 'expired/revoked authorization changed approved grant lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_imported_sample() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM synthetic_lab_artifact_governance_decisions AS decision
        WHERE decision.project_id = NEW.project_id
          AND decision.persisted_content_hash = NEW.source_artifact_hash
          AND decision.persistence_allowed
          AND decision.classification = 'derived_anonymized'
          AND 'model_generation' = ANY(decision.allowed_audiences)
    ) THEN
        RAISE EXCEPTION 'accepted Style Sample lacks governed derived artifact lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_import_manifest() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE scoped_project uuid;
DECLARE scoped_manifest uuid;
DECLARE manifest synthetic_lab_manual_import_manifests%ROWTYPE;
DECLARE accepted integer;
DECLARE rejected integer;
DECLARE duplicate_rows integer;
BEGIN
    scoped_project := NEW.project_id;
    scoped_manifest := coalesce(
        (to_jsonb(NEW) ->> 'manifest_id')::uuid,
        (to_jsonb(NEW) ->> 'id')::uuid
    );
    SELECT * INTO STRICT manifest
    FROM synthetic_lab_manual_import_manifests
    WHERE project_id = scoped_project AND id = scoped_manifest;
    SELECT count(*) INTO accepted
    FROM synthetic_lab_imported_samples
    WHERE project_id = scoped_project AND manifest_id = scoped_manifest;
    SELECT count(DISTINCT row_number) INTO rejected
    FROM synthetic_lab_manual_import_row_errors
    WHERE project_id = scoped_project AND manifest_id = scoped_manifest;
    SELECT count(DISTINCT row_number) INTO duplicate_rows
    FROM synthetic_lab_manual_import_row_errors
    WHERE project_id = scoped_project AND manifest_id = scoped_manifest
      AND code LIKE 'duplicate_%';
    IF accepted <> manifest.accepted_count
       OR rejected <> manifest.rejected_count
       OR duplicate_rows <> manifest.duplicate_row_count THEN
        RAISE EXCEPTION 'manual import children do not match immutable manifest counts'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_manual_import_preview_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE source_record record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Synthetic manual import previews are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.submitted_at > clock_timestamp() + interval '5 minutes'
       OR NEW.created_at > clock_timestamp() + interval '5 minutes'
       OR position(
            '/synthetic-lab/manual-import/temporary_upload/'
            || NEW.project_id::text || '/' || NEW.upload_artifact_id::text || '/'
            IN NEW.upload_object_uri
       ) = 0
       OR NOT EXISTS (
            SELECT 1 FROM project_memberships
            WHERE project_id = NEW.project_id AND identity_id = NEW.submitted_by
              AND status = 'active' AND role IN ('owner', 'admin', 'analyst')
       ) THEN
        RAISE EXCEPTION 'Synthetic manual import preview identity is invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT payload INTO STRICT source_record
    FROM synthetic_lab_aggregate_versions
    WHERE project_id = NEW.project_id AND kind = 'style_source'
      AND resource_id = NEW.style_source_revision_id
      AND version = NEW.source_revision_number;
    IF source_record.payload ->> 'channel' <> NEW.channel
       OR source_record.payload ->> 'locale' <> NEW.locale
       OR source_record.payload ->> 'access_mode' <> 'manual_import' THEN
        RAISE EXCEPTION 'Synthetic manual import preview differs from its Style Source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_manual_import_preview_state() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE preview synthetic_lab_manual_import_previews%ROWTYPE;
DECLARE previous synthetic_lab_manual_import_preview_states%ROWTYPE;
DECLARE distinct_rows integer;
BEGIN
    SELECT * INTO STRICT preview
    FROM synthetic_lab_manual_import_previews
    WHERE project_id = NEW.project_id AND id = NEW.preview_id;
    SELECT count(DISTINCT value) INTO distinct_rows
    FROM unnest(NEW.selected_row_numbers) AS value;
    IF EXISTS (
        SELECT 1 FROM unnest(NEW.selected_row_numbers) AS value WHERE value < 1
    ) OR distinct_rows <> cardinality(NEW.selected_row_numbers) THEN
        RAISE EXCEPTION 'Synthetic manual import selection is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NEW.status = 'pending' THEN
        IF NEW.actor_id <> preview.submitted_by
           OR NEW.occurred_at <> preview.submitted_at THEN
            RAISE EXCEPTION 'Synthetic manual import initial state differs from its preview'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT previous
    FROM synthetic_lab_manual_import_preview_states
    WHERE project_id = NEW.project_id AND id = NEW.previous_state_id
      AND preview_id = NEW.preview_id;
    IF previous.status <> 'pending' OR previous.version <> 1
       OR NEW.version <> previous.version + 1
       OR NEW.occurred_at < previous.occurred_at
       OR NEW.occurred_at > clock_timestamp() + interval '5 minutes'
       OR (NEW.status IN ('approved', 'rejected')
           AND NEW.occurred_at >= preview.expires_at)
       OR (NEW.status = 'expired' AND NEW.occurred_at < preview.expires_at)
       OR NOT EXISTS (
            SELECT 1 FROM project_memberships
            WHERE project_id = NEW.project_id AND identity_id = NEW.actor_id
              AND status = 'active'
              AND role IN ('owner', 'admin', 'analyst')
       ) THEN
        RAISE EXCEPTION 'Synthetic manual import preview transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'approved' AND (
        NEW.actor_id = preview.submitted_by
        OR NOT EXISTS (
            SELECT 1 FROM project_memberships
            WHERE project_id = NEW.project_id AND identity_id = NEW.actor_id
              AND status = 'active' AND role IN ('owner', 'admin')
        )
    ) THEN
        RAISE EXCEPTION 'Synthetic manual import maker-checker separation failed'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_create_synthetic_manual_import_preview(
    p_project_id uuid,
    p_preview_id uuid,
    p_style_source_revision_id uuid,
    p_source_revision_number integer,
    p_channel text,
    p_locale text,
    p_filename text,
    p_import_format text,
    p_default_source_rights text,
    p_rights_evidence_hash text,
    p_submitted_by uuid,
    p_submitted_at timestamptz,
    p_expires_at timestamptz,
    p_upload_artifact_id uuid,
    p_upload_object_uri text,
    p_upload_object_hash text,
    p_upload_plaintext_hash text,
    p_upload_key_version text,
    p_upload_algorithm text,
    p_upload_media_type text,
    p_upload_byte_size bigint,
    p_schema_release text,
    p_parser_release text,
    p_scanner_release text,
    p_anonymizer_release text,
    p_row_count integer,
    p_selectable_count integer,
    p_blocked_count integer,
    p_preview_manifest_hash text
) RETURNS TABLE (
    preview_id uuid,
    state_id uuid,
    version integer,
    status text,
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing synthetic_lab_manual_import_previews%ROWTYPE;
DECLARE pending synthetic_lab_manual_import_preview_states%ROWTYPE;
DECLARE generated_state_id uuid := gen_random_uuid();
DECLARE generated_state_hash text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Synthetic manual import preview Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_preview_id IS NULL OR p_style_source_revision_id IS NULL
       OR p_upload_artifact_id IS NULL OR p_submitted_by IS NULL
       OR p_submitted_at IS NULL OR p_expires_at IS NULL
       OR p_preview_manifest_hash !~ '^[0-9a-f]{64}$'
       OR p_upload_object_hash !~ '^[0-9a-f]{64}$'
       OR p_upload_plaintext_hash !~ '^[0-9a-f]{64}$'
       OR p_rights_evidence_hash !~ '^[0-9a-f]{64}$'
       OR p_row_count < 1 OR p_selectable_count < 0 OR p_blocked_count < 0
       OR p_row_count <> p_selectable_count + p_blocked_count THEN
        RAISE EXCEPTION 'invalid Synthetic manual import preview input'
            USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'synthetic-manual-import-preview:' || p_project_id::text
        || ':' || p_preview_id::text, 0
    ));
    SELECT * INTO existing
    FROM synthetic_lab_manual_import_previews AS preview
    WHERE preview.project_id = p_project_id AND preview.id = p_preview_id;
    IF FOUND THEN
        IF (existing.style_source_revision_id, existing.source_revision_number,
            existing.channel, existing.locale, existing.filename,
            existing.import_format, existing.default_source_rights,
            existing.rights_evidence_hash, existing.submitted_by,
            existing.submitted_at, existing.expires_at, existing.upload_artifact_id,
            existing.upload_object_uri, existing.upload_object_hash,
            existing.upload_plaintext_hash, existing.upload_key_version,
            existing.upload_algorithm, existing.upload_media_type,
            existing.upload_byte_size, existing.schema_release,
            existing.parser_release, existing.scanner_release,
            existing.anonymizer_release, existing.row_count,
            existing.selectable_count, existing.blocked_count,
            existing.preview_manifest_hash)
           IS DISTINCT FROM
           (p_style_source_revision_id, p_source_revision_number,
            p_channel, p_locale, p_filename, p_import_format,
            p_default_source_rights, p_rights_evidence_hash, p_submitted_by,
            p_submitted_at, p_expires_at, p_upload_artifact_id,
            p_upload_object_uri, p_upload_object_hash, p_upload_plaintext_hash,
            p_upload_key_version, p_upload_algorithm, p_upload_media_type,
            p_upload_byte_size, p_schema_release, p_parser_release,
            p_scanner_release, p_anonymizer_release, p_row_count,
            p_selectable_count, p_blocked_count, p_preview_manifest_hash) THEN
            RAISE EXCEPTION 'Synthetic manual import preview identity already has different content'
                USING ERRCODE = '23505';
        END IF;
        SELECT * INTO STRICT pending
        FROM synthetic_lab_manual_import_preview_states AS state
        WHERE state.project_id = p_project_id AND state.preview_id = p_preview_id
        ORDER BY state.version DESC LIMIT 1;
        RETURN QUERY SELECT p_preview_id, pending.id, pending.version,
                            pending.status, true;
        RETURN;
    END IF;
    generated_state_hash := encode(digest(convert_to(
        geo_jsonb_canonical_text(jsonb_build_object(
            'schema_version', 1, 'preview_id', p_preview_id,
            'project_id', p_project_id, 'version', 1, 'status', 'pending',
            'actor_id', p_submitted_by, 'occurred_at', p_submitted_at
        )), 'UTF8'
    ), 'sha256'), 'hex');
    INSERT INTO synthetic_lab_manual_import_previews(
        id, project_id, style_source_revision_id, source_revision_number,
        channel, locale, filename, import_format, default_source_rights,
        rights_evidence_hash, submitted_by, submitted_at, expires_at,
        upload_artifact_id, upload_object_uri, upload_object_hash,
        upload_plaintext_hash, upload_key_version, upload_algorithm,
        upload_media_type, upload_byte_size, schema_release, parser_release,
        scanner_release, anonymizer_release, row_count, selectable_count,
        blocked_count, preview_manifest_hash, created_at
    ) VALUES (
        p_preview_id, p_project_id, p_style_source_revision_id,
        p_source_revision_number, p_channel, p_locale, p_filename,
        p_import_format, p_default_source_rights, p_rights_evidence_hash,
        p_submitted_by, p_submitted_at, p_expires_at, p_upload_artifact_id,
        p_upload_object_uri, p_upload_object_hash, p_upload_plaintext_hash,
        p_upload_key_version, p_upload_algorithm, p_upload_media_type,
        p_upload_byte_size, p_schema_release, p_parser_release,
        p_scanner_release, p_anonymizer_release, p_row_count,
        p_selectable_count, p_blocked_count, p_preview_manifest_hash,
        p_submitted_at
    );
    INSERT INTO synthetic_lab_manual_import_preview_states(
        id, project_id, preview_id, version, previous_state_id, status,
        actor_id, occurred_at, selected_row_numbers, selection_hash,
        au_english_verified, anonymization_verified, final_manifest_id,
        reason_hash, idempotency_key_hash, request_hash, state_hash, created_at
    ) VALUES (
        generated_state_id, p_project_id, p_preview_id, 1, NULL, 'pending',
        p_submitted_by, p_submitted_at, ARRAY[]::integer[], NULL,
        false, false, NULL, NULL, NULL, NULL, generated_state_hash, p_submitted_at
    );
    RETURN QUERY SELECT p_preview_id, generated_state_id, 1, 'pending'::text, false;
END;
$$;

CREATE FUNCTION geo_finalize_synthetic_manual_import_preview(
    p_project_id uuid,
    p_preview_id uuid,
    p_expected_version integer,
    p_actor_id uuid,
    p_decision text,
    p_occurred_at timestamptz,
    p_selected_row_numbers integer[],
    p_au_english_verified boolean,
    p_anonymization_verified boolean,
    p_final_manifest_id uuid,
    p_reason_hash text,
    p_idempotency_key_hash text,
    p_request_hash text
) RETURNS TABLE (
    state_id uuid,
    version integer,
    status text,
    final_manifest_id uuid,
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE preview synthetic_lab_manual_import_previews%ROWTYPE;
DECLARE current_state synthetic_lab_manual_import_preview_states%ROWTYPE;
DECLARE replay_state synthetic_lab_manual_import_preview_states%ROWTYPE;
DECLARE generated_state_id uuid := gen_random_uuid();
DECLARE generated_state_hash text;
DECLARE generated_selection_hash text;
DECLARE generated_cleanup_id uuid := gen_random_uuid();
DECLARE normalized_rows integer[];
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Synthetic manual import finalization Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_preview_id IS NULL OR p_actor_id IS NULL OR p_expected_version < 1
       OR p_decision NOT IN ('approved', 'rejected', 'expired')
       OR p_occurred_at IS NULL
       OR p_idempotency_key_hash !~ '^[0-9a-f]{64}$'
       OR p_request_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid Synthetic manual import finalization input'
            USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'synthetic-manual-import-preview:' || p_project_id::text
        || ':' || p_preview_id::text, 0
    ));
    SELECT * INTO replay_state
    FROM synthetic_lab_manual_import_preview_states AS state
    WHERE state.project_id = p_project_id
      AND state.idempotency_key_hash = p_idempotency_key_hash;
    IF FOUND THEN
        IF replay_state.preview_id <> p_preview_id
           OR replay_state.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'Synthetic manual import finalization idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT replay_state.id, replay_state.version,
                            replay_state.status, replay_state.final_manifest_id, true;
        RETURN;
    END IF;
    SELECT * INTO STRICT preview
    FROM synthetic_lab_manual_import_previews AS item
    WHERE item.project_id = p_project_id AND item.id = p_preview_id
    FOR UPDATE;
    SELECT * INTO STRICT current_state
    FROM synthetic_lab_manual_import_preview_states AS state
    WHERE state.project_id = p_project_id AND state.preview_id = p_preview_id
    ORDER BY state.version DESC LIMIT 1 FOR UPDATE;
    IF current_state.status <> 'pending'
       OR current_state.version <> p_expected_version THEN
        RAISE EXCEPTION 'Synthetic manual import preview version changed'
            USING ERRCODE = '40001';
    END IF;
    SELECT coalesce(array_agg(value ORDER BY value), ARRAY[]::integer[])
    INTO normalized_rows
    FROM unnest(coalesce(p_selected_row_numbers, ARRAY[]::integer[])) AS value;
    IF normalized_rows IS DISTINCT FROM coalesce(
        p_selected_row_numbers, ARRAY[]::integer[]
    ) OR EXISTS (SELECT 1 FROM unnest(normalized_rows) AS value WHERE value < 1)
       OR cardinality(normalized_rows) <> (
            SELECT count(DISTINCT value) FROM unnest(normalized_rows) AS value
       ) THEN
        RAISE EXCEPTION 'Synthetic manual import selected rows are invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_decision = 'approved' THEN
        IF cardinality(normalized_rows) < 1
           OR NOT p_au_english_verified OR NOT p_anonymization_verified
           OR p_final_manifest_id IS NULL OR p_reason_hash IS NOT NULL THEN
            RAISE EXCEPTION 'Synthetic manual import approval shape is invalid'
                USING ERRCODE = '22023';
        END IF;
        generated_selection_hash := encode(digest(convert_to(
            geo_jsonb_canonical_text(to_jsonb(normalized_rows)), 'UTF8'
        ), 'sha256'), 'hex');
    ELSE
        IF cardinality(normalized_rows) <> 0 OR p_au_english_verified
           OR p_anonymization_verified OR p_final_manifest_id IS NOT NULL
           OR p_reason_hash !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'Synthetic manual import rejection/expiry shape is invalid'
                USING ERRCODE = '22023';
        END IF;
    END IF;
    generated_state_hash := encode(digest(convert_to(
        geo_jsonb_canonical_text(jsonb_build_object(
            'schema_version', 1, 'preview_id', p_preview_id,
            'project_id', p_project_id, 'version', p_expected_version + 1,
            'status', p_decision, 'actor_id', p_actor_id,
            'occurred_at', p_occurred_at, 'selected_row_numbers', normalized_rows,
            'selection_hash', generated_selection_hash,
            'au_english_verified', p_au_english_verified,
            'anonymization_verified', p_anonymization_verified,
            'final_manifest_id', p_final_manifest_id, 'reason_hash', p_reason_hash,
            'idempotency_key_hash', p_idempotency_key_hash,
            'request_hash', p_request_hash
        )), 'UTF8'
    ), 'sha256'), 'hex');
    INSERT INTO synthetic_lab_manual_import_preview_states(
        id, project_id, preview_id, version, previous_state_id, status,
        actor_id, occurred_at, selected_row_numbers, selection_hash,
        au_english_verified, anonymization_verified, final_manifest_id,
        reason_hash, idempotency_key_hash, request_hash, state_hash, created_at
    ) VALUES (
        generated_state_id, p_project_id, p_preview_id,
        p_expected_version + 1, current_state.id, p_decision,
        p_actor_id, p_occurred_at, normalized_rows, generated_selection_hash,
        p_au_english_verified, p_anonymization_verified, p_final_manifest_id,
        p_reason_hash, p_idempotency_key_hash, p_request_hash,
        generated_state_hash, p_occurred_at
    );
    INSERT INTO synthetic_lab_manual_import_cleanup_outbox(
        id, project_id, preview_id, terminal_state_id, terminal_version,
        terminal_status, upload_artifact_id, object_uri, object_hash,
        status, next_attempt_at, attempt_count, fencing_generation, created_at
    ) VALUES (
        generated_cleanup_id, p_project_id, p_preview_id, generated_state_id,
        p_expected_version + 1, p_decision, preview.upload_artifact_id,
        preview.upload_object_uri, preview.upload_object_hash,
        'pending', p_occurred_at, 0, 0, p_occurred_at
    );
    RETURN QUERY SELECT generated_state_id, p_expected_version + 1,
                        p_decision, p_final_manifest_id, false;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_manual_import_terminal_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE scoped_project uuid;
DECLARE scoped_preview uuid;
DECLARE terminal_state synthetic_lab_manual_import_preview_states%ROWTYPE;
DECLARE manifest synthetic_lab_manual_import_manifests%ROWTYPE;
DECLARE accepted_rows integer[];
DECLARE artifact_count integer;
BEGIN
    scoped_project := NEW.project_id;
    IF TG_TABLE_NAME = 'synthetic_lab_manual_import_preview_states' THEN
        scoped_preview := NEW.preview_id;
    ELSIF TG_TABLE_NAME = 'synthetic_lab_manual_import_manifests' THEN
        scoped_preview := NEW.preview_id;
    ELSIF TG_TABLE_NAME = 'synthetic_lab_imported_samples' THEN
        SELECT preview_id INTO STRICT scoped_preview
        FROM synthetic_lab_manual_import_manifests
        WHERE project_id = NEW.project_id AND id = NEW.manifest_id;
    ELSE
        SELECT manifest.preview_id INTO STRICT scoped_preview
        FROM synthetic_lab_imported_samples AS sample
        JOIN synthetic_lab_manual_import_manifests AS manifest
          ON manifest.id = sample.manifest_id AND manifest.project_id = sample.project_id
        WHERE sample.project_id = NEW.project_id AND sample.id = NEW.sample_id;
    END IF;
    SELECT * INTO terminal_state
    FROM synthetic_lab_manual_import_preview_states
    WHERE project_id = scoped_project AND preview_id = scoped_preview
      AND status IN ('approved', 'rejected', 'expired')
    ORDER BY version DESC LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    IF terminal_state.status = 'approved' THEN
        SELECT * INTO STRICT manifest
        FROM synthetic_lab_manual_import_manifests
        WHERE project_id = scoped_project AND id = terminal_state.final_manifest_id
          AND preview_id = scoped_preview;
        SELECT coalesce(array_agg(row_number ORDER BY row_number), ARRAY[]::integer[])
        INTO accepted_rows
        FROM synthetic_lab_imported_samples
        WHERE project_id = scoped_project AND manifest_id = manifest.id;
        SELECT count(*) INTO artifact_count
        FROM synthetic_lab_imported_sample_artifacts AS artifact
        JOIN synthetic_lab_imported_samples AS sample
          ON sample.project_id = artifact.project_id AND sample.id = artifact.sample_id
        WHERE sample.project_id = scoped_project AND sample.manifest_id = manifest.id
          AND artifact.plaintext_hash = sample.normalized_text_hash;
        IF manifest.imported_by <> terminal_state.actor_id
           OR manifest.imported_at <> terminal_state.occurred_at
           OR manifest.row_count <> cardinality(terminal_state.selected_row_numbers)
           OR manifest.accepted_count <> manifest.row_count
           OR manifest.rejected_count <> 0 OR manifest.duplicate_row_count <> 0
           OR accepted_rows IS DISTINCT FROM terminal_state.selected_row_numbers
           OR artifact_count <> manifest.accepted_count THEN
            RAISE EXCEPTION 'approved manual import lacks exact samples and encrypted artifacts'
                USING ERRCODE = '23514';
        END IF;
    ELSIF EXISTS (
        SELECT 1 FROM synthetic_lab_manual_import_manifests
        WHERE project_id = scoped_project AND preview_id = scoped_preview
    ) THEN
        RAISE EXCEPTION 'rejected/expired manual import cannot retain a final manifest'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM synthetic_lab_manual_import_cleanup_outbox AS cleanup
        JOIN synthetic_lab_manual_import_previews AS preview
          ON preview.id = cleanup.preview_id AND preview.project_id = cleanup.project_id
        WHERE cleanup.project_id = scoped_project AND cleanup.preview_id = scoped_preview
          AND cleanup.terminal_state_id = terminal_state.id
          AND cleanup.terminal_version = terminal_state.version
          AND cleanup.terminal_status = terminal_state.status
          AND cleanup.upload_artifact_id = preview.upload_artifact_id
          AND cleanup.object_uri = preview.upload_object_uri
          AND cleanup.object_hash = preview.upload_object_hash
    ) THEN
        RAISE EXCEPTION 'terminal manual import lacks exact temporary-object cleanup lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_manual_import_cleanup_outbox_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Synthetic manual import cleanup records cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.id, OLD.project_id, OLD.preview_id, OLD.terminal_state_id,
        OLD.terminal_version, OLD.terminal_status, OLD.upload_artifact_id,
        OLD.object_uri, OLD.object_hash, OLD.created_at)
       IS DISTINCT FROM
       (NEW.id, NEW.project_id, NEW.preview_id, NEW.terminal_state_id,
        NEW.terminal_version, NEW.terminal_status, NEW.upload_artifact_id,
        NEW.object_uri, NEW.object_hash, NEW.created_at)
       OR NOT (
            (OLD.status IN ('pending', 'failed') AND NEW.status = 'leased'
                AND NEW.attempt_count = OLD.attempt_count + 1
                AND NEW.fencing_generation = OLD.fencing_generation + 1
                AND NEW.lease_owner IS NOT NULL AND NEW.lease_token IS NOT NULL
                AND NEW.lease_expires_at IS NOT NULL
                AND NEW.completed_at IS NULL)
            OR (OLD.status = 'leased' AND NEW.status = 'completed'
                AND NEW.attempt_count = OLD.attempt_count
                AND NEW.fencing_generation = OLD.fencing_generation
                AND NEW.lease_owner IS NULL AND NEW.lease_token IS NULL
                AND NEW.lease_expires_at IS NULL AND NEW.completed_at IS NOT NULL)
            OR (OLD.status = 'leased' AND NEW.status = 'failed'
                AND NEW.attempt_count = OLD.attempt_count
                AND NEW.fencing_generation = OLD.fencing_generation
                AND NEW.lease_owner IS NULL AND NEW.lease_token IS NULL
                AND NEW.lease_expires_at IS NULL AND NEW.completed_at IS NULL
                AND NEW.last_error_code IS NOT NULL)
       ) THEN
        RAISE EXCEPTION 'Synthetic manual import cleanup transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_manual_import_cleanup_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE cleanup synthetic_lab_manual_import_cleanup_outbox%ROWTYPE;
BEGIN
    SELECT * INTO STRICT cleanup
    FROM synthetic_lab_manual_import_cleanup_outbox
    WHERE project_id = NEW.project_id AND id = NEW.cleanup_outbox_id
    FOR UPDATE;
    IF cleanup.status <> 'leased'
       OR cleanup.preview_id <> NEW.preview_id
       OR cleanup.upload_artifact_id <> NEW.upload_artifact_id
       OR cleanup.object_hash <> NEW.object_hash
       OR cleanup.lease_expires_at IS NULL
       OR cleanup.lease_expires_at <= NEW.deleted_at THEN
        RAISE EXCEPTION 'Synthetic manual import cleanup receipt lost exact lease lineage'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_claim_synthetic_manual_import_cleanups(
    p_lease_owner text,
    p_limit integer,
    p_lease_seconds integer
) RETURNS TABLE (
    cleanup_outbox_id uuid,
    project_id uuid,
    preview_id uuid,
    upload_artifact_id uuid,
    object_uri text,
    object_hash text,
    lease_token uuid,
    fencing_generation bigint,
    lease_expires_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF btrim(coalesce(p_lease_owner, '')) = '' OR p_limit < 1 OR p_limit > 100
       OR p_lease_seconds < 1 OR p_lease_seconds > 900 THEN
        RAISE EXCEPTION 'invalid Synthetic manual import cleanup claim input'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH candidates AS (
        SELECT item.id
        FROM synthetic_lab_manual_import_cleanup_outbox AS item
        WHERE item.status IN ('pending', 'failed')
          AND item.next_attempt_at <= clock_timestamp()
          AND item.project_id = ANY(geo_current_project_ids())
        ORDER BY item.next_attempt_at, item.id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    ), claimed AS (
        UPDATE synthetic_lab_manual_import_cleanup_outbox AS item
        SET status = 'leased', lease_owner = p_lease_owner,
            lease_token = gen_random_uuid(),
            lease_expires_at = clock_timestamp()
                + make_interval(secs => p_lease_seconds),
            attempt_count = item.attempt_count + 1,
            fencing_generation = item.fencing_generation + 1,
            last_error_code = NULL
        FROM candidates
        WHERE item.id = candidates.id
        RETURNING item.*
    )
    SELECT claimed.id, claimed.project_id, claimed.preview_id,
           claimed.upload_artifact_id, claimed.object_uri, claimed.object_hash,
           claimed.lease_token, claimed.fencing_generation, claimed.lease_expires_at
    FROM claimed;
END;
$$;

CREATE FUNCTION geo_complete_synthetic_manual_import_cleanup(
    p_project_id uuid,
    p_cleanup_outbox_id uuid,
    p_expected_fencing_generation bigint,
    p_lease_token uuid,
    p_receipt_id uuid,
    p_deletion_receipt_hash text,
    p_deleted_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE cleanup synthetic_lab_manual_import_cleanup_outbox%ROWTYPE;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR p_deletion_receipt_hash !~ '^[0-9a-f]{64}$'
       OR p_deleted_at IS NULL THEN
        RAISE EXCEPTION 'invalid Synthetic manual import cleanup completion input'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT cleanup
    FROM synthetic_lab_manual_import_cleanup_outbox
    WHERE project_id = p_project_id AND id = p_cleanup_outbox_id
    FOR UPDATE;
    IF cleanup.status <> 'leased'
       OR cleanup.fencing_generation <> p_expected_fencing_generation
       OR cleanup.lease_token IS DISTINCT FROM p_lease_token
       OR cleanup.lease_expires_at IS NULL
       OR cleanup.lease_expires_at <= p_deleted_at THEN
        RAISE EXCEPTION 'Synthetic manual import cleanup lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    INSERT INTO synthetic_lab_manual_import_cleanup_receipts(
        id, project_id, cleanup_outbox_id, preview_id, upload_artifact_id,
        object_hash, deletion_receipt_hash, deleted_at, object_deleted,
        recoverable_body_retained
    ) VALUES (
        p_receipt_id, p_project_id, cleanup.id, cleanup.preview_id,
        cleanup.upload_artifact_id, cleanup.object_hash,
        p_deletion_receipt_hash, p_deleted_at, true, false
    );
    UPDATE synthetic_lab_manual_import_cleanup_outbox
    SET status = 'completed', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, completed_at = p_deleted_at,
        last_error_code = NULL
    WHERE project_id = p_project_id AND id = p_cleanup_outbox_id;
END;
$$;

CREATE FUNCTION geo_fail_synthetic_manual_import_cleanup(
    p_project_id uuid,
    p_cleanup_outbox_id uuid,
    p_expected_fencing_generation bigint,
    p_lease_token uuid,
    p_error_code text,
    p_next_attempt_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE cleanup synthetic_lab_manual_import_cleanup_outbox%ROWTYPE;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR p_error_code !~ '^[a-z][a-z0-9_]{0,62}$'
       OR p_next_attempt_at IS NULL THEN
        RAISE EXCEPTION 'invalid Synthetic manual import cleanup failure input'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT cleanup
    FROM synthetic_lab_manual_import_cleanup_outbox
    WHERE project_id = p_project_id AND id = p_cleanup_outbox_id
    FOR UPDATE;
    IF cleanup.status <> 'leased'
       OR cleanup.fencing_generation <> p_expected_fencing_generation
       OR cleanup.lease_token IS DISTINCT FROM p_lease_token
       OR cleanup.lease_expires_at IS NULL
       OR cleanup.lease_expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'Synthetic manual import cleanup failure lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    UPDATE synthetic_lab_manual_import_cleanup_outbox
    SET status = 'failed', lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, last_error_code = p_error_code,
        next_attempt_at = p_next_attempt_at
    WHERE project_id = p_project_id AND id = p_cleanup_outbox_id;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_job_metadata() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE item record;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id;
    IF durable.kind <> (CASE NEW.domain_job_kind
        WHEN 'style_collection' THEN 'style.collect'
        WHEN 'candidate_generation' THEN 'review.case.run'
        WHEN 'candidate_revision' THEN 'candidate.revise'
        WHEN 'corpus_finalize' THEN 'corpus.finalize'
        WHEN 'offline_experiment' THEN 'offline_experiment.run'
        WHEN 'style_profile_build' THEN 'style.profile.build'
        WHEN 'model_call_child' THEN 'synthetic.model.call'
    END) THEN
        RAISE EXCEPTION 'Synthetic Lab domain Job kind does not match canonical Durable Job kind'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.payload = '{}'::jsonb THEN
        RAISE EXCEPTION 'Synthetic Lab Job payload cannot be empty' USING ERRCODE = '23514';
    END IF;
    FOR item IN SELECT key, value FROM jsonb_each(NEW.payload) LOOP
        IF item.key !~ '_(id|ids|hash|hashes)$'
           OR jsonb_typeof(item.value) NOT IN ('string', 'array') THEN
            RAISE EXCEPTION 'Synthetic Lab Job payload may contain only ID/hash fields'
                USING ERRCODE = '23514';
        END IF;
        IF jsonb_typeof(item.value) = 'array' AND (
            jsonb_array_length(item.value) = 0
            OR EXISTS (SELECT 1 FROM jsonb_array_elements(item.value) value
                       WHERE jsonb_typeof(value) <> 'string')
        ) THEN
            RAISE EXCEPTION 'Synthetic Lab Job identifier arrays must contain strings'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.metadata_version <> OLD.metadata_version + 1
           OR (NEW.job_id, NEW.project_id, NEW.domain_job_kind,
               NEW.payload, NEW.payload_hash,
               NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
               NEW.profile_version_id, NEW.profile_hash,
               NEW.prompt_release_id, NEW.prompt_release_hash,
               NEW.facts_current_approved, NEW.profile_frozen, NEW.prompt_frozen,
               NEW.authorization_id, NEW.authorization_channel,
               NEW.authorization_adapter_release, NEW.authorization_version,
               NEW.authorization_hash, NEW.authorization_purpose,
               NEW.authorization_expires_at)
              IS DISTINCT FROM
              (OLD.job_id, OLD.project_id, OLD.domain_job_kind,
               OLD.payload, OLD.payload_hash,
               OLD.fact_snapshot_id, OLD.fact_snapshot_hash,
               OLD.profile_version_id, OLD.profile_hash,
               OLD.prompt_release_id, OLD.prompt_release_hash,
               OLD.facts_current_approved, OLD.profile_frozen, OLD.prompt_frozen,
               OLD.authorization_id, OLD.authorization_channel,
               OLD.authorization_adapter_release, OLD.authorization_version,
               OLD.authorization_hash, OLD.authorization_purpose,
               OLD.authorization_expires_at) THEN
            RAISE EXCEPTION 'Synthetic Lab Job metadata CAS or frozen lineage failed'
                USING ERRCODE = '40001';
        END IF;
        NEW.updated_at := clock_timestamp();
    ELSIF NEW.metadata_version <> 1 THEN
        RAISE EXCEPTION 'Synthetic Lab Job metadata must start at version 1'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_outbox() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE broker broker_outbox%ROWTYPE;
BEGIN
    SELECT * INTO STRICT broker FROM broker_outbox
    WHERE id = NEW.id AND project_id = NEW.project_id;
    IF broker.job_id <> NEW.job_id OR broker.topic <> NEW.event_type
       OR broker.payload <> jsonb_build_object(
            'project_id', NEW.project_id::text,
            'job_id', NEW.job_id::text,
            'event_type', NEW.event_type,
            'payload_hash', NEW.payload_hash
       ) THEN
        RAISE EXCEPTION 'Synthetic Lab outbox lineage does not match Broker Outbox'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_model_call_child() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_job durable_jobs%ROWTYPE;
    child_job durable_jobs%ROWTYPE;
    parent_metadata synthetic_lab_job_metadata%ROWTYPE;
    child_metadata synthetic_lab_job_metadata%ROWTYPE;
    parent_task synthetic_lab_execution_tasks%ROWTYPE;
    child_outbox synthetic_lab_outbox_messages%ROWTYPE;
    prompt_binding prompt_program_bindings%ROWTYPE;
    prompt_release prompt_program_releases%ROWTYPE;
    prompt_state prompt_program_release_states%ROWTYPE;
    runtime_manifest model_gateway_runtime_manifests%ROWTYPE;
    runtime_option model_gateway_runtime_options%ROWTYPE;
    model_release model_gateway_model_releases%ROWTYPE;
    expected_payload jsonb;
    expected_payload_hash text;
BEGIN
    SELECT * INTO STRICT parent_job FROM durable_jobs
    WHERE id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_job FROM durable_jobs
    WHERE id = NEW.child_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT parent_metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.child_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT parent_task FROM synthetic_lab_execution_tasks
    WHERE job_id = NEW.parent_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT child_outbox FROM synthetic_lab_outbox_messages
    WHERE id = NEW.outbox_id AND project_id = NEW.project_id;

    expected_payload := jsonb_build_object(
        'parent_job_id', NEW.parent_job_id::text,
        'step_key_hash', NEW.step_key_hash,
        'task_artifact_hash', NEW.task_artifact_hash
    );
    expected_payload_hash := encode(digest(
        convert_to(geo_jsonb_canonical_text(expected_payload), 'UTF8'), 'sha256'
    ), 'hex');
    IF NEW.step_key_hash <> encode(digest(convert_to(NEW.step_key, 'UTF8'), 'sha256'), 'hex')
       OR parent_job.kind <> NEW.parent_job_kind
       OR parent_job.status NOT IN ('running', 'finalizing')
       OR parent_job.cancel_requested_at IS NOT NULL
       OR parent_job.lease_token IS DISTINCT FROM NEW.parent_lease_token
       OR parent_job.fencing_generation <> NEW.parent_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= NEW.created_at
       OR parent_task.task_input_hash <> NEW.parent_task_input_hash
       OR child_job.kind <> 'synthetic.model.call'
       OR child_job.status <> 'queued'
       OR child_job.attempt_count <> 0
       OR child_job.fencing_generation <> 0
       OR child_job.input_hash <> NEW.child_input_hash
       OR child_job.parent_job_id IS DISTINCT FROM NEW.parent_job_id
       OR child_job.campaign_id IS DISTINCT FROM parent_job.campaign_id
       OR child_metadata.domain_job_kind <> 'model_call_child'
       OR child_metadata.payload <> expected_payload
       OR child_metadata.payload_hash <> expected_payload_hash
       OR child_outbox.job_id <> NEW.child_job_id
       OR child_outbox.event_type <> 'synthetic.model.call.queued'
       OR child_outbox.payload_hash <> NEW.child_input_hash THEN
        RAISE EXCEPTION 'Synthetic model child does not match parent lease, Job, or Outbox lineage'
            USING ERRCODE = '40001';
    END IF;
    IF (parent_metadata.fact_snapshot_id, parent_metadata.fact_snapshot_hash,
        parent_metadata.profile_version_id, parent_metadata.profile_hash,
        parent_metadata.prompt_release_id, parent_metadata.prompt_release_hash)
       IS DISTINCT FROM
       (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
        NEW.profile_version_id, NEW.profile_hash,
        NEW.runtime_prompt_release_id, NEW.runtime_prompt_release_hash)
       OR NOT coalesce(parent_metadata.facts_current_approved, false)
       OR NOT coalesce(parent_metadata.profile_frozen, false)
       OR NOT coalesce(parent_metadata.prompt_frozen, false)
       OR (child_metadata.fact_snapshot_id, child_metadata.fact_snapshot_hash,
           child_metadata.profile_version_id, child_metadata.profile_hash,
           child_metadata.prompt_release_id, child_metadata.prompt_release_hash,
           child_metadata.facts_current_approved, child_metadata.profile_frozen,
           child_metadata.prompt_frozen)
          IS DISTINCT FROM
          (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
           NEW.profile_version_id, NEW.profile_hash,
           NEW.runtime_prompt_release_id, NEW.runtime_prompt_release_hash,
           true, true, true) THEN
        RAISE EXCEPTION 'Synthetic model child changed frozen parent runtime lineage'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO STRICT prompt_binding FROM prompt_program_bindings
    WHERE id = NEW.prompt_binding_id AND project_id = NEW.project_id
      AND purpose = NEW.prompt_purpose
      AND binding_version = NEW.prompt_binding_version;
    SELECT * INTO STRICT prompt_release FROM prompt_program_releases
    WHERE id = NEW.prompt_release_id AND project_id = NEW.project_id
      AND release_hash = NEW.prompt_release_hash;
    SELECT * INTO STRICT prompt_state FROM prompt_program_release_states
    WHERE id = NEW.prompt_frozen_state_id AND project_id = NEW.project_id
      AND release_id = NEW.prompt_release_id
      AND release_hash = NEW.prompt_release_hash
      AND version = NEW.prompt_state_version;
    IF prompt_binding.release_id <> NEW.prompt_release_id
       OR prompt_binding.release_version <> NEW.prompt_release_version
       OR prompt_binding.release_hash <> NEW.prompt_release_hash
       OR prompt_binding.frozen_state_id <> NEW.prompt_frozen_state_id
       OR prompt_release.version <> NEW.prompt_release_version
       OR prompt_release.program_kind <> NEW.prompt_program_kind
       OR prompt_release.purpose <> NEW.prompt_purpose
       OR prompt_release.model_policy_hash <> NEW.prompt_model_policy_hash
       OR prompt_release.output_schema_hash <> NEW.portable_output_schema_hash
       OR prompt_release.application_output_schema_hash
            <> NEW.application_output_schema_hash
       OR prompt_state.status <> 'frozen'
       OR EXISTS (
            SELECT 1 FROM prompt_program_bindings AS newer
            WHERE newer.project_id = NEW.project_id
              AND newer.purpose = NEW.prompt_purpose
              AND newer.binding_version > NEW.prompt_binding_version
       ) THEN
        RAISE EXCEPTION 'Synthetic model child requires the exact current frozen Prompt binding'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO STRICT runtime_manifest FROM model_gateway_runtime_manifests
    WHERE id = NEW.runtime_manifest_id AND project_id = NEW.project_id
      AND manifest_hash = NEW.runtime_manifest_hash
    FOR SHARE;
    SELECT * INTO STRICT runtime_option FROM model_gateway_runtime_options
    WHERE id = NEW.runtime_option_id AND project_id = NEW.project_id
      AND manifest_id = NEW.runtime_manifest_id
      AND option_hash = NEW.runtime_option_hash;
    SELECT * INTO STRICT model_release FROM model_gateway_model_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND model_release_id = NEW.model_release_id
      AND release_hash = NEW.model_release_hash;
    IF runtime_manifest.status <> 'approved'
       OR runtime_option.provider <> NEW.provider
       OR runtime_option.adapter_release_id <> NEW.adapter_release_id
       OR runtime_option.adapter_release_hash <> NEW.adapter_release_hash
       OR runtime_option.model_release_id <> NEW.model_release_id
       OR runtime_option.model_release_hash <> NEW.model_release_hash
       OR NEW.prompt_purpose <> ALL(runtime_option.allowed_purposes)
       OR NOT runtime_option.allowed_search_modes @> jsonb_build_array(NEW.search_mode)
       OR model_release.configured_model <> NEW.configured_model
       OR model_release.state <> 'approved' THEN
        RAISE EXCEPTION 'Synthetic model child differs from the approved runtime option'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_enqueue_synthetic_model_call_child(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_parent_lease_token uuid,
    p_parent_fencing_generation bigint,
    p_child_job_id uuid,
    p_parent_job_kind text,
    p_parent_task_input_hash text,
    p_step_key text,
    p_model_job_version integer,
    p_fact_snapshot_id uuid,
    p_fact_snapshot_hash text,
    p_profile_version_id uuid,
    p_profile_hash text,
    p_runtime_prompt_release_id uuid,
    p_runtime_prompt_release_hash text,
    p_prompt_binding_id uuid,
    p_prompt_binding_version integer,
    p_prompt_frozen_state_id uuid,
    p_prompt_frozen_state_version integer,
    p_prompt_release_id uuid,
    p_prompt_release_version integer,
    p_prompt_release_hash text,
    p_prompt_program_kind text,
    p_prompt_purpose text,
    p_admitted_by uuid,
    p_prompt_model_policy_hash text,
    p_provider text,
    p_adapter_release_id text,
    p_adapter_release_hash text,
    p_model_release_id text,
    p_model_release_hash text,
    p_configured_model text,
    p_runtime_manifest_id uuid,
    p_runtime_manifest_hash text,
    p_runtime_option_id uuid,
    p_runtime_option_hash text,
    p_search_mode text,
    p_prompt_bundle_hash text,
    p_structured_input_hash text,
    p_portable_output_schema_hash text,
    p_application_output_schema_hash text,
    p_task_artifact_uri text,
    p_task_artifact_hash text,
    p_deterministic_seed numeric,
    p_max_output_tokens integer,
    p_child_input_hash text
) RETURNS TABLE (
    child_job_id uuid,
    outbox_id uuid,
    durable_status text,
    replayed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    existing synthetic_lab_model_call_children%ROWTYPE;
    parent_job durable_jobs%ROWTYPE;
    prompt_state_version integer;
    generated_outbox_id uuid := gen_random_uuid();
    step_hash text;
    metadata_payload jsonb;
    metadata_payload_hash text;
    queued_at timestamptz := clock_timestamp();
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Synthetic model child Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    step_hash := encode(digest(convert_to(p_step_key, 'UTF8'), 'sha256'), 'hex');
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'synthetic-model-child:' || p_project_id::text || ':'
        || p_parent_job_id::text || ':' || step_hash, 0
    ));
    SELECT child.* INTO existing
    FROM synthetic_lab_model_call_children AS child
    WHERE child.project_id = p_project_id
      AND (child.child_job_id = p_child_job_id
           OR (child.parent_job_id = p_parent_job_id
               AND child.step_key_hash = step_hash))
    LIMIT 1
    FOR SHARE;
    IF FOUND THEN
        IF (existing.child_job_id, existing.parent_job_id,
            existing.parent_job_kind, existing.parent_task_input_hash,
            existing.step_key, existing.model_job_version,
            existing.fact_snapshot_id, existing.fact_snapshot_hash,
            existing.profile_version_id, existing.profile_hash,
            existing.runtime_prompt_release_id, existing.runtime_prompt_release_hash,
            existing.prompt_binding_id, existing.prompt_binding_version,
            existing.prompt_frozen_state_id, existing.prompt_state_version,
            existing.prompt_release_id,
            existing.prompt_release_version, existing.prompt_release_hash,
            existing.prompt_program_kind, existing.prompt_purpose, existing.admitted_by,
            existing.prompt_model_policy_hash, existing.provider,
            existing.adapter_release_id, existing.adapter_release_hash,
            existing.model_release_id, existing.model_release_hash,
            existing.configured_model, existing.runtime_manifest_id,
            existing.runtime_manifest_hash, existing.runtime_option_id,
            existing.runtime_option_hash, existing.search_mode,
            existing.prompt_bundle_hash, existing.structured_input_hash,
            existing.portable_output_schema_hash,
            existing.application_output_schema_hash, existing.task_artifact_uri,
            existing.task_artifact_hash, existing.deterministic_seed,
            existing.max_output_tokens, existing.child_input_hash)
           IS DISTINCT FROM
           (p_child_job_id, p_parent_job_id,
            p_parent_job_kind, p_parent_task_input_hash,
            p_step_key, p_model_job_version,
            p_fact_snapshot_id, p_fact_snapshot_hash,
            p_profile_version_id, p_profile_hash,
            p_runtime_prompt_release_id, p_runtime_prompt_release_hash,
            p_prompt_binding_id, p_prompt_binding_version,
            p_prompt_frozen_state_id, p_prompt_frozen_state_version,
            p_prompt_release_id,
            p_prompt_release_version, p_prompt_release_hash,
            p_prompt_program_kind, p_prompt_purpose, p_admitted_by,
            p_prompt_model_policy_hash, p_provider,
            p_adapter_release_id, p_adapter_release_hash,
            p_model_release_id, p_model_release_hash,
            p_configured_model, p_runtime_manifest_id,
            p_runtime_manifest_hash, p_runtime_option_id,
            p_runtime_option_hash, p_search_mode,
            p_prompt_bundle_hash, p_structured_input_hash,
            p_portable_output_schema_hash, p_application_output_schema_hash,
            p_task_artifact_uri,
            p_task_artifact_hash, p_deterministic_seed,
            p_max_output_tokens, p_child_input_hash) THEN
            RAISE EXCEPTION 'Synthetic model child idempotency identity changed'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY
        SELECT existing.child_job_id, existing.outbox_id, job.status, true
        FROM durable_jobs AS job
        WHERE job.id = existing.child_job_id AND job.project_id = p_project_id;
        RETURN;
    END IF;

    SELECT * INTO STRICT parent_job FROM durable_jobs
    WHERE id = p_parent_job_id AND project_id = p_project_id
    FOR SHARE;
    IF parent_job.kind <> p_parent_job_kind
       OR parent_job.status NOT IN ('running', 'finalizing')
       OR parent_job.cancel_requested_at IS NOT NULL
       OR parent_job.lease_token IS DISTINCT FROM p_parent_lease_token
       OR parent_job.fencing_generation <> p_parent_fencing_generation
       OR parent_job.lease_expires_at IS NULL
       OR parent_job.lease_expires_at <= queued_at THEN
        RAISE EXCEPTION 'Synthetic model child enqueue lost the parent lease or fence'
            USING ERRCODE = '40001';
    END IF;
    SELECT state.version INTO STRICT prompt_state_version
    FROM prompt_program_release_states AS state
    WHERE state.id = p_prompt_frozen_state_id
      AND state.project_id = p_project_id
      AND state.release_id = p_prompt_release_id
      AND state.release_hash = p_prompt_release_hash
      AND state.status = 'frozen'
      AND state.version = p_prompt_frozen_state_version;

    INSERT INTO durable_jobs(
        id, project_id, kind, status, priority, input_hash, idempotency_key,
        attempt_count, max_attempts, next_run_at, fencing_generation,
        parent_job_id, replay_nonce, campaign_id, created_at, updated_at
    ) VALUES (
        p_child_job_id, p_project_id, 'synthetic.model.call', 'queued',
        parent_job.priority, p_child_input_hash,
        'synthetic-model:' || p_parent_job_id::text || ':' || step_hash,
        0, 3, queued_at, 0, p_parent_job_id, 0, parent_job.campaign_id,
        queued_at, queued_at
    );
    metadata_payload := jsonb_build_object(
        'parent_job_id', p_parent_job_id::text,
        'step_key_hash', step_hash,
        'task_artifact_hash', p_task_artifact_hash
    );
    metadata_payload_hash := encode(digest(
        convert_to(geo_jsonb_canonical_text(metadata_payload), 'UTF8'), 'sha256'
    ), 'hex');
    INSERT INTO synthetic_lab_job_metadata(
        job_id, project_id, metadata_version, domain_job_kind,
        payload, payload_hash, fact_snapshot_id, fact_snapshot_hash,
        profile_version_id, profile_hash, prompt_release_id,
        prompt_release_hash, facts_current_approved, profile_frozen,
        prompt_frozen, created_at, updated_at
    ) VALUES (
        p_child_job_id, p_project_id, 1, 'model_call_child',
        metadata_payload, metadata_payload_hash, p_fact_snapshot_id,
        p_fact_snapshot_hash, p_profile_version_id, p_profile_hash,
        p_runtime_prompt_release_id, p_runtime_prompt_release_hash,
        true, true, true, queued_at, queued_at
    );
    INSERT INTO broker_outbox(
        id, project_id, job_id, topic, payload, idempotency_key,
        available_at, created_at
    ) VALUES (
        generated_outbox_id, p_project_id, p_child_job_id,
        'synthetic.model.call.queued',
        jsonb_build_object(
            'project_id', p_project_id::text,
            'job_id', p_child_job_id::text,
            'event_type', 'synthetic.model.call.queued',
            'payload_hash', p_child_input_hash
        ),
        'synthetic:' || generated_outbox_id::text, queued_at, queued_at
    );
    INSERT INTO synthetic_lab_outbox_messages(
        id, project_id, job_id, event_type, payload_hash, created_at
    ) VALUES (
        generated_outbox_id, p_project_id, p_child_job_id,
        'synthetic.model.call.queued', p_child_input_hash, queued_at
    );
    INSERT INTO synthetic_lab_model_call_children(
        project_id, child_job_id, parent_job_id, parent_job_kind,
        parent_task_input_hash, parent_lease_token, parent_fencing_generation,
        step_key, step_key_hash, model_job_version,
        fact_snapshot_id, fact_snapshot_hash, profile_version_id, profile_hash,
        runtime_prompt_release_id, runtime_prompt_release_hash,
        prompt_binding_id, prompt_binding_version, prompt_frozen_state_id,
        prompt_state_version, prompt_release_id, prompt_release_version,
        prompt_release_hash, prompt_program_kind, prompt_purpose, admitted_by,
        prompt_model_policy_hash, provider, adapter_release_id,
        adapter_release_hash, model_release_id, model_release_hash,
        configured_model, runtime_manifest_id, runtime_manifest_hash,
        runtime_option_id, runtime_option_hash, search_mode,
        prompt_bundle_hash, structured_input_hash, portable_output_schema_hash,
        application_output_schema_hash,
        task_artifact_uri, task_artifact_hash, deterministic_seed,
        max_output_tokens, child_input_hash, outbox_id, created_at
    ) VALUES (
        p_project_id, p_child_job_id, p_parent_job_id, p_parent_job_kind,
        p_parent_task_input_hash, p_parent_lease_token, p_parent_fencing_generation,
        p_step_key, step_hash, p_model_job_version,
        p_fact_snapshot_id, p_fact_snapshot_hash, p_profile_version_id, p_profile_hash,
        p_runtime_prompt_release_id, p_runtime_prompt_release_hash,
        p_prompt_binding_id, p_prompt_binding_version, p_prompt_frozen_state_id,
        prompt_state_version, p_prompt_release_id, p_prompt_release_version,
        p_prompt_release_hash, p_prompt_program_kind, p_prompt_purpose, p_admitted_by,
        p_prompt_model_policy_hash, p_provider, p_adapter_release_id,
        p_adapter_release_hash, p_model_release_id, p_model_release_hash,
        p_configured_model, p_runtime_manifest_id, p_runtime_manifest_hash,
        p_runtime_option_id, p_runtime_option_hash, p_search_mode,
        p_prompt_bundle_hash, p_structured_input_hash, p_portable_output_schema_hash,
        p_application_output_schema_hash,
        p_task_artifact_uri, p_task_artifact_hash, p_deterministic_seed,
        p_max_output_tokens, p_child_input_hash, generated_outbox_id, queued_at
    );
    INSERT INTO durable_job_events(
        project_id, job_id, event_type, worker_id, fencing_generation, details, created_at
    ) VALUES (
        p_project_id, p_child_job_id, 'job_enqueued',
        'synthetic-child-enqueue', 0,
        jsonb_build_object(
            'parent_job_id', p_parent_job_id::text,
            'step_key_hash', step_hash,
            'child_input_hash', p_child_input_hash
        ), queued_at
    );
    RETURN QUERY SELECT p_child_job_id, generated_outbox_id, 'queued'::text, false;
END;
$$;

CREATE FUNCTION geo_block_synthetic_unstarted_model_call_children(
    p_project_id uuid,
    p_parent_job_id uuid,
    p_reason_code text
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE blocked_count integer;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Synthetic child cancellation Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_reason_code !~ '^[a-z][a-z0-9_.:-]{0,99}$' THEN
        RAISE EXCEPTION 'Synthetic child cancellation reason is invalid'
            USING ERRCODE = '22023';
    END IF;
    WITH cancelled AS (
        UPDATE durable_jobs AS child
        SET status = 'cancelled',
            cancel_requested_at = coalesce(child.cancel_requested_at, clock_timestamp()),
            error_code = 'synthetic_parent_blocked',
            error_detail = jsonb_build_object(
                'parent_job_id', p_parent_job_id::text,
                'reason_code', p_reason_code
            ),
            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
            heartbeat_at = NULL, completed_at = clock_timestamp(),
            updated_at = clock_timestamp()
        FROM synthetic_lab_model_call_children AS link
        WHERE link.project_id = p_project_id
          AND link.parent_job_id = p_parent_job_id
          AND child.id = link.child_job_id
          AND child.project_id = link.project_id
          AND child.attempt_count = 0
          AND child.status IN ('queued', 'retry_wait')
        RETURNING child.id, child.project_id, child.fencing_generation
    ), logged AS (
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details
        )
        SELECT cancelled.project_id, cancelled.id, 'job_cancelled',
               'synthetic-parent-guard', cancelled.fencing_generation,
               jsonb_build_object(
                   'parent_job_id', p_parent_job_id::text,
                   'reason_code', p_reason_code,
                   'unstarted', true
               )
        FROM cancelled
        RETURNING id
    )
    SELECT count(*)::integer INTO blocked_count FROM logged;
    RETURN blocked_count;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_model_call_child_job_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    link synthetic_lab_model_call_children%ROWTYPE;
    parent_job durable_jobs%ROWTYPE;
    successful_attempt uuid;
BEGIN
    IF OLD.kind <> 'synthetic.model.call' AND NEW.kind <> 'synthetic.model.call' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT link FROM synthetic_lab_model_call_children
    WHERE child_job_id = OLD.id AND project_id = OLD.project_id;
    IF (NEW.id, NEW.project_id, NEW.kind, NEW.input_hash,
        NEW.idempotency_key, NEW.parent_job_id, NEW.replay_nonce,
        NEW.campaign_id, NEW.max_attempts)
       IS DISTINCT FROM
       (OLD.id, OLD.project_id, OLD.kind, OLD.input_hash,
        OLD.idempotency_key, OLD.parent_job_id, OLD.replay_nonce,
        OLD.campaign_id, OLD.max_attempts) THEN
        RAISE EXCEPTION 'Synthetic model child immutable Durable Job identity changed'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.attempt_count = 0 AND NEW.status = 'running' THEN
        IF NEW.attempt_count <> 1 THEN
            RAISE EXCEPTION 'Synthetic model child first claim has an invalid attempt counter'
                USING ERRCODE = '40001';
        END IF;
        SELECT * INTO STRICT parent_job FROM durable_jobs
        WHERE id = link.parent_job_id AND project_id = link.project_id
        FOR SHARE;
        IF parent_job.cancel_requested_at IS NOT NULL
           OR NOT (
                (parent_job.status IN ('running', 'finalizing')
                    AND parent_job.lease_expires_at > clock_timestamp())
                OR (parent_job.status = 'retry_wait'
                    AND parent_job.error_code = 'synthetic_child_pending')
           ) THEN
            RAISE EXCEPTION 'Synthetic model child cannot start after its parent was blocked'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    IF NEW.status = 'succeeded' AND OLD.status IS DISTINCT FROM 'succeeded' THEN
        SELECT attempt.id INTO successful_attempt
        FROM model_gateway_call_attempts AS attempt
        JOIN model_gateway_terminal_events AS terminal
          ON terminal.attempt_id = attempt.id
         AND terminal.project_id = attempt.project_id
         AND terminal.job_id = attempt.job_id
        WHERE attempt.project_id = NEW.project_id
          AND attempt.job_id = NEW.id
          AND terminal.status = 'succeeded'
        ORDER BY attempt.attempt_number DESC
        LIMIT 1;
        IF successful_attempt IS NULL
           OR NEW.result_ref IS DISTINCT FROM
              'model-gateway://attempt/' || successful_attempt::text THEN
            RAISE EXCEPTION 'Synthetic model child success lacks a governed Model Gateway result'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_propagate_synthetic_parent_job_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE reason_code text;
BEGIN
    IF NEW.cancel_requested_at IS NOT NULL
       AND OLD.cancel_requested_at IS NULL THEN
        reason_code := 'parent_cancel_requested';
    ELSIF NEW.status IN ('succeeded', 'failed', 'dead_lettered', 'cancelled')
       AND OLD.status IS DISTINCT FROM NEW.status THEN
        reason_code := 'parent_status_' || NEW.status;
    ELSE
        RETURN NEW;
    END IF;
    PERFORM geo_block_synthetic_unstarted_model_call_children(
        NEW.project_id, NEW.id, reason_code
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_wake_synthetic_parent_after_child_terminal() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    link synthetic_lab_model_call_children%ROWTYPE;
    parent_kind text;
    parent_fence bigint;
    wakeup_id uuid := gen_random_uuid();
BEGIN
    IF NEW.kind <> 'synthetic.model.call'
       OR NEW.status NOT IN ('succeeded', 'failed', 'dead_lettered', 'cancelled')
       OR OLD.status = NEW.status THEN
        RETURN NEW;
    END IF;
    SELECT * INTO STRICT link FROM synthetic_lab_model_call_children
    WHERE child_job_id = NEW.id AND project_id = NEW.project_id;
    UPDATE durable_jobs AS parent
    SET next_run_at = LEAST(parent.next_run_at, clock_timestamp()),
        updated_at = clock_timestamp()
    WHERE parent.id = link.parent_job_id
      AND parent.project_id = link.project_id
      AND parent.status = 'retry_wait'
      AND parent.error_code = 'synthetic_child_pending'
      AND parent.cancel_requested_at IS NULL
    RETURNING parent.kind, parent.fencing_generation
    INTO parent_kind, parent_fence;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
    INSERT INTO broker_outbox(
        id, project_id, job_id, topic, payload, idempotency_key, available_at
    ) VALUES (
        wakeup_id, link.project_id, link.parent_job_id, parent_kind,
        jsonb_build_object(
            'job_id', link.parent_job_id::text,
            'project_id', link.project_id::text
        ),
        'synthetic-child-terminal:' || NEW.id::text || ':' || NEW.status,
        clock_timestamp()
    ) ON CONFLICT (project_id, idempotency_key) DO NOTHING;
    IF FOUND THEN
        INSERT INTO durable_job_events(
            project_id, job_id, event_type, worker_id, fencing_generation, details
        ) VALUES (
            link.project_id, link.parent_job_id, 'child_terminal_wakeup_staged',
            'synthetic-child-terminal', parent_fence,
            jsonb_build_object(
                'child_job_id', NEW.id::text,
                'child_status', NEW.status
            )
        );
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_execution_task() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE metadata synthetic_lab_job_metadata%ROWTYPE;
DECLARE expected_kind text;
DECLARE expected_domain_kind text;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    expected_kind := CASE NEW.task_type
        WHEN 'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask'
            THEN 'style.profile.build'
        WHEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunTask'
            THEN 'review.case.run'
        WHEN 'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask'
            THEN 'offline_experiment.run'
    END;
    expected_domain_kind := CASE NEW.task_type
        WHEN 'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask'
            THEN 'style_profile_build'
        WHEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunTask'
            THEN 'candidate_generation'
        WHEN 'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask'
            THEN 'offline_experiment'
    END;
    IF NEW.execution_kind <> expected_kind OR durable.kind <> expected_kind
       OR metadata.domain_job_kind <> expected_domain_kind
       OR durable.input_hash <> NEW.expected_job_input_hash
       OR durable.status <> 'queued' THEN
        RAISE EXCEPTION 'Synthetic execution task does not match its queued Durable Job'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_execution_result() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
DECLARE metadata synthetic_lab_job_metadata%ROWTYPE;
DECLARE task synthetic_lab_execution_tasks%ROWTYPE;
DECLARE expected_result_type text;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id FOR UPDATE;
    SELECT * INTO STRICT metadata FROM synthetic_lab_job_metadata
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT task FROM synthetic_lab_execution_tasks
    WHERE job_id = NEW.job_id AND project_id = NEW.project_id;
    expected_result_type := CASE task.task_type
        WHEN 'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildTask'
            THEN 'geo_core.synthetic_lab.execution_contracts.StyleProfileBuildOutput'
        WHEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunTask'
            THEN 'geo_core.synthetic_lab.execution_contracts.ReviewCaseRunOutput'
        WHEN 'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunTask'
            THEN 'geo_core.synthetic_lab.execution_contracts.OfflineExperimentRunOutput'
    END;
    IF NEW.result_type <> expected_result_type
       OR durable.status NOT IN ('running', 'finalizing')
       OR durable.cancel_requested_at IS NOT NULL
       OR durable.lease_token IS DISTINCT FROM NEW.lease_token
       OR durable.fencing_generation <> NEW.fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at <= NEW.created_at
       OR (NEW.fact_snapshot_id, NEW.fact_snapshot_hash,
           NEW.profile_version_id, NEW.profile_hash,
           NEW.prompt_release_id, NEW.prompt_release_hash)
          IS DISTINCT FROM
          (metadata.fact_snapshot_id, metadata.fact_snapshot_hash,
           metadata.profile_version_id, metadata.profile_hash,
           metadata.prompt_release_id, metadata.prompt_release_hash) THEN
        RAISE EXCEPTION 'Synthetic execution result lost lease, fence, or frozen runtime lineage'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_execution_result_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id;
    IF durable.status <> 'succeeded'
       OR durable.result_ref IS DISTINCT FROM 'synthetic://result/' || NEW.result_hash
       OR NOT EXISTS (
            SELECT 1 FROM synthetic_lab_terminal_results terminal
            WHERE terminal.project_id = NEW.project_id AND terminal.job_id = NEW.job_id
              AND terminal.result_hash = NEW.result_hash
       ) THEN
        RAISE EXCEPTION 'Synthetic execution result lacks matching Job and domain terminal'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_synthetic_lab_terminal() RETURNS trigger
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
       OR coalesce(metadata.profile_frozen, true) IS NOT TRUE
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

CREATE FUNCTION geo_assert_synthetic_lab_terminal_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE durable durable_jobs%ROWTYPE;
BEGIN
    SELECT * INTO STRICT durable FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id;
    IF durable.status <> 'succeeded'
       OR durable.result_ref IS DISTINCT FROM 'synthetic://result/' || NEW.result_hash THEN
        RAISE EXCEPTION 'Synthetic Lab terminal result lacks matching Durable Job completion'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER synthetic_lab_aggregate_append_guard
BEFORE INSERT ON synthetic_lab_aggregate_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_aggregate_append();
CREATE TRIGGER synthetic_lab_authorization_append_guard
BEFORE INSERT ON synthetic_lab_authorization_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_authorization_append();
CREATE TRIGGER synthetic_lab_manual_import_preview_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON synthetic_lab_manual_import_previews
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_manual_import_preview_change();
CREATE TRIGGER synthetic_lab_manual_import_preview_state_guard
BEFORE INSERT ON synthetic_lab_manual_import_preview_states
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_manual_import_preview_state();
CREATE TRIGGER synthetic_lab_imported_sample_guard
BEFORE INSERT ON synthetic_lab_imported_samples
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_imported_sample();
CREATE TRIGGER synthetic_lab_job_metadata_guard
BEFORE INSERT OR UPDATE ON synthetic_lab_job_metadata
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_job_metadata();
CREATE TRIGGER synthetic_lab_outbox_guard
BEFORE INSERT ON synthetic_lab_outbox_messages
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_outbox();
CREATE TRIGGER synthetic_lab_model_call_child_guard
BEFORE INSERT ON synthetic_lab_model_call_children
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_model_call_child();
CREATE TRIGGER synthetic_model_call_child_job_change_guard
BEFORE UPDATE ON durable_jobs
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_model_call_child_job_change();
CREATE TRIGGER synthetic_parent_job_change_propagation
AFTER UPDATE OF status, cancel_requested_at ON durable_jobs
FOR EACH ROW EXECUTE FUNCTION geo_propagate_synthetic_parent_job_change();
CREATE TRIGGER synthetic_model_call_child_terminal_wakeup
AFTER UPDATE OF status ON durable_jobs
FOR EACH ROW EXECUTE FUNCTION geo_wake_synthetic_parent_after_child_terminal();
CREATE TRIGGER synthetic_lab_style_collection_task_guard
BEFORE INSERT ON synthetic_lab_style_collection_tasks
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_style_collection_task();
CREATE TRIGGER synthetic_lab_artifact_master_key_change_guard
BEFORE UPDATE OR DELETE ON synthetic_lab_artifact_master_key_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_artifact_master_key_change();
CREATE TRIGGER synthetic_lab_raw_artifact_insert_guard
BEFORE INSERT ON synthetic_lab_raw_artifacts
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_raw_artifact_insert();
CREATE TRIGGER synthetic_lab_raw_artifact_change_guard
BEFORE UPDATE OR DELETE ON synthetic_lab_raw_artifacts
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_raw_artifact_change();
CREATE TRIGGER synthetic_lab_artifact_dek_insert_guard
BEFORE INSERT ON synthetic_lab_artifact_deks
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_artifact_dek_insert();
CREATE TRIGGER synthetic_lab_artifact_dek_change_guard
BEFORE UPDATE OR DELETE ON synthetic_lab_artifact_deks
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_artifact_dek_change();
CREATE CONSTRAINT TRIGGER synthetic_lab_artifact_dek_consistency_guard
AFTER INSERT OR UPDATE ON synthetic_lab_artifact_deks
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_artifact_dek_consistency();
CREATE TRIGGER synthetic_lab_artifact_deletion_outbox_change_guard
BEFORE UPDATE OR DELETE ON synthetic_lab_artifact_deletion_outbox
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_artifact_outbox_change();
CREATE TRIGGER synthetic_lab_manual_import_cleanup_outbox_change_guard
BEFORE UPDATE OR DELETE ON synthetic_lab_manual_import_cleanup_outbox
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_manual_import_cleanup_outbox_change();
CREATE TRIGGER synthetic_lab_manual_import_cleanup_receipt_guard
BEFORE INSERT ON synthetic_lab_manual_import_cleanup_receipts
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_manual_import_cleanup_receipt();
CREATE TRIGGER synthetic_lab_style_collection_result_guard
BEFORE INSERT ON synthetic_lab_style_collection_results
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_style_collection_result();
CREATE CONSTRAINT TRIGGER synthetic_lab_style_collection_result_consistency_guard
AFTER INSERT ON synthetic_lab_style_collection_results
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_style_collection_result_consistency();
CREATE TRIGGER synthetic_lab_execution_task_guard
BEFORE INSERT ON synthetic_lab_execution_tasks
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_execution_task();
CREATE TRIGGER synthetic_lab_execution_result_guard
BEFORE INSERT ON synthetic_lab_execution_results
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_execution_result();
CREATE TRIGGER synthetic_lab_terminal_guard
BEFORE INSERT ON synthetic_lab_terminal_results
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_terminal();
CREATE CONSTRAINT TRIGGER synthetic_lab_terminal_consistency_guard
AFTER INSERT ON synthetic_lab_terminal_results
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_terminal_consistency();
CREATE CONSTRAINT TRIGGER synthetic_lab_execution_result_consistency_guard
AFTER INSERT ON synthetic_lab_execution_results
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_execution_result_consistency();
CREATE CONSTRAINT TRIGGER synthetic_lab_import_manifest_consistency_guard
AFTER INSERT ON synthetic_lab_manual_import_manifests
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_import_manifest();
CREATE CONSTRAINT TRIGGER synthetic_lab_import_error_consistency_guard
AFTER INSERT ON synthetic_lab_manual_import_row_errors
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_import_manifest();
CREATE CONSTRAINT TRIGGER synthetic_lab_import_sample_consistency_guard
AFTER INSERT ON synthetic_lab_imported_samples
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_lab_import_manifest();
CREATE CONSTRAINT TRIGGER synthetic_lab_manual_import_state_consistency_guard
AFTER INSERT ON synthetic_lab_manual_import_preview_states
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_manual_import_terminal_consistency();
CREATE CONSTRAINT TRIGGER synthetic_lab_manual_import_manifest_terminal_guard
AFTER INSERT ON synthetic_lab_manual_import_manifests
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_manual_import_terminal_consistency();
CREATE CONSTRAINT TRIGGER synthetic_lab_manual_import_sample_terminal_guard
AFTER INSERT ON synthetic_lab_imported_samples
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_manual_import_terminal_consistency();
CREATE CONSTRAINT TRIGGER synthetic_lab_manual_import_sample_artifact_terminal_guard
AFTER INSERT ON synthetic_lab_imported_sample_artifacts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_synthetic_manual_import_terminal_consistency();

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'synthetic_lab_command_receipts', 'synthetic_lab_aggregate_versions',
        'synthetic_lab_authorization_versions',
        'synthetic_lab_manual_import_preview_states',
        'synthetic_lab_manual_import_manifests',
        'synthetic_lab_manual_import_row_errors', 'synthetic_lab_imported_samples',
        'synthetic_lab_imported_sample_artifacts',
        'synthetic_lab_manual_import_cleanup_receipts',
        'synthetic_lab_artifact_governance_decisions', 'synthetic_lab_job_metadata',
        'synthetic_lab_outbox_messages', 'synthetic_lab_model_call_children',
        'synthetic_lab_style_collection_tasks',
        'synthetic_lab_artifact_legal_holds', 'synthetic_lab_artifact_tombstones',
        'synthetic_lab_style_collection_results', 'synthetic_lab_execution_tasks',
        'synthetic_lab_execution_results', 'synthetic_lab_terminal_results'
    ] LOOP
        EXECUTE 'CREATE TRIGGER ' || quote_ident(table_name || '_immutable')
            || ' BEFORE UPDATE OR DELETE ON ' || quote_ident(table_name)
            || ' FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change()';
    END LOOP;
END;
$$;
DROP TRIGGER synthetic_lab_job_metadata_immutable ON synthetic_lab_job_metadata;
CREATE TRIGGER synthetic_lab_job_metadata_no_delete
BEFORE DELETE ON synthetic_lab_job_metadata
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX synthetic_lab_aggregate_current_idx
ON synthetic_lab_aggregate_versions(project_id, kind, resource_id, version DESC);
CREATE INDEX synthetic_lab_authorization_current_idx
ON synthetic_lab_authorization_versions(project_id, channel, adapter_release, version_number DESC);
CREATE INDEX synthetic_lab_authorization_decided_by_idx
ON synthetic_lab_authorization_versions(decided_by) WHERE decided_by IS NOT NULL;
CREATE INDEX synthetic_lab_import_manifest_actor_idx
ON synthetic_lab_manual_import_manifests(imported_by);
CREATE INDEX synthetic_lab_import_error_manifest_idx
ON synthetic_lab_manual_import_row_errors(project_id, manifest_id, row_number);
CREATE INDEX synthetic_lab_imported_samples_manifest_idx
ON synthetic_lab_imported_samples(project_id, manifest_id, row_number);
CREATE INDEX synthetic_lab_imported_samples_reviewer_idx
ON synthetic_lab_imported_samples(language_reviewer_id);
CREATE INDEX synthetic_lab_manual_import_previews_project_created_idx
ON synthetic_lab_manual_import_previews(project_id, created_at DESC, id);
CREATE INDEX synthetic_lab_manual_import_preview_states_current_idx
ON synthetic_lab_manual_import_preview_states(project_id, preview_id, version DESC);
CREATE INDEX synthetic_lab_imported_sample_artifacts_key_version_idx
ON synthetic_lab_imported_sample_artifacts(key_version, project_id, created_at);
CREATE INDEX synthetic_lab_manual_import_cleanup_claim_idx
ON synthetic_lab_manual_import_cleanup_outbox(
    status, next_attempt_at, lease_expires_at, id
);
CREATE INDEX synthetic_lab_manual_import_cleanup_receipts_preview_idx
ON synthetic_lab_manual_import_cleanup_receipts(project_id, preview_id, deleted_at DESC);
CREATE INDEX synthetic_lab_job_runtime_idx
ON synthetic_lab_job_metadata(project_id, prompt_release_id, profile_version_id);
CREATE INDEX synthetic_lab_outbox_job_idx
ON synthetic_lab_outbox_messages(project_id, job_id);
CREATE INDEX synthetic_lab_model_children_parent_idx
ON synthetic_lab_model_call_children(project_id, parent_job_id, created_at, child_job_id);
CREATE INDEX synthetic_lab_model_children_prompt_idx
ON synthetic_lab_model_call_children(
    prompt_binding_id, project_id, prompt_purpose, prompt_binding_version
);
CREATE INDEX synthetic_lab_model_children_runtime_idx
ON synthetic_lab_model_call_children(
    runtime_option_id, project_id, runtime_manifest_id, runtime_option_hash
);
CREATE INDEX synthetic_lab_model_children_artifact_idx
ON synthetic_lab_model_call_children(project_id, task_artifact_hash);
CREATE INDEX synthetic_lab_style_collection_tasks_authorization_idx
ON synthetic_lab_style_collection_tasks(
    project_id, authorization_id, authorization_version, authorization_hash
);
CREATE INDEX synthetic_lab_raw_artifacts_job_generation_idx
ON synthetic_lab_raw_artifacts(
    project_id, job_id, fencing_generation, lifecycle_state, artifact_form
);
CREATE INDEX synthetic_lab_raw_artifacts_expiry_idx
ON synthetic_lab_raw_artifacts(lifecycle_state, expires_at, project_id)
WHERE expires_at IS NOT NULL AND lifecycle_state IN ('winning', 'orphaned');
CREATE INDEX synthetic_lab_artifact_deks_restore_idx
ON synthetic_lab_artifact_deks(master_key_version, status, project_id, created_at);
CREATE INDEX synthetic_lab_artifact_legal_holds_active_idx
ON synthetic_lab_artifact_legal_holds(
    project_id, artifact_id, artifact_generation, approved_at, expires_at
);
CREATE INDEX synthetic_lab_artifact_deletion_claim_idx
ON synthetic_lab_artifact_deletion_outbox(status, next_attempt_at, lease_expires_at, id);
CREATE INDEX synthetic_lab_execution_task_kind_idx
ON synthetic_lab_execution_tasks(project_id, execution_kind, staged_at);

CREATE VIEW synthetic_lab_manual_import_preview_current
WITH (security_barrier = true, security_invoker = true)
AS
SELECT preview.*,
       state.id AS state_id,
       state.version,
       state.status,
       state.actor_id AS state_actor_id,
       state.occurred_at AS state_occurred_at,
       state.selected_row_numbers,
       state.selection_hash,
       state.au_english_verified,
       state.anonymization_verified,
       state.final_manifest_id,
       state.reason_hash,
       state.state_hash
FROM synthetic_lab_manual_import_previews AS preview
JOIN LATERAL (
    SELECT value.*
    FROM synthetic_lab_manual_import_preview_states AS value
    WHERE value.project_id = preview.project_id AND value.preview_id = preview.id
    ORDER BY value.version DESC
    LIMIT 1
) AS state ON true;

CREATE VIEW synthetic_lab_model_call_child_status
WITH (security_barrier = true, security_invoker = true)
AS
SELECT child.project_id,
       child.child_job_id,
       child.parent_job_id,
       child.parent_job_kind,
       child.parent_task_input_hash,
       child.step_key,
       child.step_key_hash,
       child.model_job_version,
       child.prompt_binding_id,
       child.prompt_binding_version,
       child.prompt_frozen_state_id,
       child.prompt_state_version,
       child.prompt_release_id,
       child.prompt_release_version,
       child.prompt_release_hash,
       child.prompt_program_kind,
       child.prompt_purpose,
       child.admitted_by,
       child.prompt_bundle_hash,
       child.structured_input_hash,
       child.portable_output_schema_hash,
       child.application_output_schema_hash,
       child.runtime_manifest_id,
       child.runtime_manifest_hash,
       child.runtime_option_id,
       child.runtime_option_hash,
       child.configured_model AS frozen_configured_model,
       child.task_artifact_uri,
       child.task_artifact_hash,
       child.child_input_hash,
       durable.status AS durable_status,
       CASE
           WHEN durable.status = 'succeeded' THEN 'succeeded'
           WHEN durable.status = 'cancelled' THEN 'cancelled'
           WHEN durable.error_code = 'model_unknown_outcome' THEN 'unknown_outcome'
           WHEN durable.status IN ('failed', 'dead_lettered') THEN 'failed'
           WHEN durable.status IN ('running', 'finalizing') THEN 'running'
           ELSE 'queued'
       END AS status,
       durable.attempt_count AS durable_attempt_count,
       durable.fencing_generation AS durable_fencing_generation,
       durable.cancel_requested_at,
       coalesce(durable.error_code, latest.error_code) AS failure_code,
       latest.attempt_id AS model_attempt_id,
       latest.attempt_number AS model_attempt_number,
       latest.terminal_status AS model_terminal_status,
       latest.gateway_call_log_id,
       latest.output_hash,
       latest.response_hash,
       latest.configured_model AS model_configured_model,
       latest.provider_reported_model AS model_reported_model,
       child.created_at
FROM synthetic_lab_model_call_children AS child
JOIN durable_jobs AS durable
  ON durable.id = child.child_job_id AND durable.project_id = child.project_id
LEFT JOIN LATERAL (
    SELECT attempt.id AS attempt_id,
           attempt.attempt_number,
           terminal.status AS terminal_status,
           terminal.error_code,
           terminal.gateway_call_log_id,
           terminal.output_hash,
           terminal.response_hash,
           terminal.configured_model,
           terminal.provider_reported_model
    FROM model_gateway_call_attempts AS attempt
    LEFT JOIN model_gateway_terminal_events AS terminal
      ON terminal.attempt_id = attempt.id
     AND terminal.project_id = attempt.project_id
     AND terminal.job_id = attempt.job_id
    WHERE attempt.project_id = child.project_id
      AND attempt.job_id = child.child_job_id
    ORDER BY attempt.attempt_number DESC
    LIMIT 1
) AS latest ON true;

DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'synthetic_lab_command_receipts', 'synthetic_lab_aggregate_versions',
        'synthetic_lab_authorization_versions',
        'synthetic_lab_manual_import_previews',
        'synthetic_lab_manual_import_preview_states',
        'synthetic_lab_manual_import_manifests',
        'synthetic_lab_manual_import_row_errors', 'synthetic_lab_imported_samples',
        'synthetic_lab_imported_sample_artifacts',
        'synthetic_lab_manual_import_cleanup_outbox',
        'synthetic_lab_manual_import_cleanup_receipts',
        'synthetic_lab_artifact_governance_decisions', 'synthetic_lab_job_metadata',
        'synthetic_lab_outbox_messages', 'synthetic_lab_model_call_children',
        'synthetic_lab_style_collection_tasks',
        'synthetic_lab_raw_artifacts', 'synthetic_lab_artifact_deks',
        'synthetic_lab_artifact_legal_holds',
        'synthetic_lab_artifact_deletion_outbox',
        'synthetic_lab_artifact_crypto_erasures',
        'synthetic_lab_artifact_tombstones',
        'synthetic_lab_style_collection_results', 'synthetic_lab_execution_tasks',
        'synthetic_lab_execution_results', 'synthetic_lab_terminal_results'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

REVOKE ALL ON
    synthetic_lab_command_receipts, synthetic_lab_aggregate_versions,
    synthetic_lab_authorization_versions, synthetic_lab_manual_import_previews,
    synthetic_lab_manual_import_preview_states,
    synthetic_lab_manual_import_manifests,
    synthetic_lab_manual_import_row_errors, synthetic_lab_imported_samples,
    synthetic_lab_imported_sample_artifacts,
    synthetic_lab_manual_import_cleanup_outbox,
    synthetic_lab_manual_import_cleanup_receipts,
    synthetic_lab_artifact_governance_decisions, synthetic_lab_job_metadata,
    synthetic_lab_outbox_messages, synthetic_lab_model_call_children,
    synthetic_lab_style_collection_tasks,
    synthetic_lab_artifact_master_key_versions, synthetic_lab_raw_artifacts,
    synthetic_lab_artifact_deks, synthetic_lab_artifact_legal_holds,
    synthetic_lab_artifact_deletion_outbox, synthetic_lab_artifact_crypto_erasures,
    synthetic_lab_artifact_tombstones,
    synthetic_lab_style_collection_results, synthetic_lab_execution_tasks,
    synthetic_lab_execution_results, synthetic_lab_terminal_results
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON
    synthetic_lab_manual_import_preview_current,
    synthetic_lab_model_call_child_status
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

GRANT SELECT, INSERT ON
    synthetic_lab_command_receipts, synthetic_lab_aggregate_versions,
    synthetic_lab_authorization_versions, synthetic_lab_manual_import_manifests,
    synthetic_lab_manual_import_row_errors, synthetic_lab_imported_samples,
    synthetic_lab_imported_sample_artifacts,
    synthetic_lab_artifact_governance_decisions, synthetic_lab_outbox_messages,
    synthetic_lab_style_collection_tasks, synthetic_lab_artifact_legal_holds,
    synthetic_lab_execution_tasks
TO geo_app;
GRANT SELECT ON
    synthetic_lab_command_receipts, synthetic_lab_aggregate_versions,
    synthetic_lab_authorization_versions, synthetic_lab_manual_import_previews,
    synthetic_lab_manual_import_preview_states,
    synthetic_lab_manual_import_manifests,
    synthetic_lab_manual_import_row_errors, synthetic_lab_imported_samples,
    synthetic_lab_imported_sample_artifacts,
    synthetic_lab_manual_import_cleanup_outbox,
    synthetic_lab_manual_import_cleanup_receipts,
    synthetic_lab_artifact_governance_decisions, synthetic_lab_job_metadata,
    synthetic_lab_outbox_messages, synthetic_lab_model_call_children,
    synthetic_lab_style_collection_tasks,
    synthetic_lab_raw_artifacts, synthetic_lab_artifact_legal_holds,
    synthetic_lab_artifact_crypto_erasures, synthetic_lab_artifact_tombstones,
    synthetic_lab_style_collection_results,
    synthetic_lab_execution_tasks,
    synthetic_lab_execution_results, synthetic_lab_terminal_results
TO geo_app, geo_worker;
GRANT SELECT ON
    synthetic_lab_manual_import_preview_current,
    synthetic_lab_model_call_child_status
TO geo_app, geo_worker;
GRANT SELECT ON
    synthetic_lab_artifact_master_key_versions, synthetic_lab_artifact_deks,
    synthetic_lab_artifact_deletion_outbox,
    synthetic_lab_artifact_crypto_erasures,
    synthetic_lab_manual_import_cleanup_outbox
TO geo_worker;
GRANT INSERT ON
    synthetic_lab_command_receipts, synthetic_lab_aggregate_versions,
    synthetic_lab_artifact_governance_decisions, synthetic_lab_raw_artifacts,
    synthetic_lab_artifact_deks, synthetic_lab_style_collection_results,
    synthetic_lab_execution_results, synthetic_lab_terminal_results
TO geo_worker;
GRANT INSERT ON synthetic_lab_job_metadata TO geo_app;
GRANT UPDATE (metadata_version, updated_at) ON synthetic_lab_job_metadata TO geo_app, geo_worker;

REVOKE ALL ON FUNCTION
    geo_synthetic_secret_handle_hash(uuid, uuid, text, integer),
    geo_assert_synthetic_artifact_master_key_change(),
    geo_sync_synthetic_artifact_master_key_version(text, text, text, bytea, bytea, timestamptz),
    geo_retire_synthetic_artifact_master_key_version(text, timestamptz),
    geo_assert_synthetic_style_collection_task(),
    geo_assert_synthetic_raw_artifact_insert(),
    geo_assert_synthetic_raw_artifact_change(),
    geo_assert_synthetic_artifact_dek_insert(),
    geo_assert_synthetic_artifact_dek_consistency(),
    geo_assert_synthetic_artifact_dek_change(),
    geo_assert_synthetic_artifact_outbox_change(),
    geo_assert_synthetic_style_collection_result(),
    geo_assert_synthetic_style_collection_result_consistency(),
    geo_mark_synthetic_artifact_attempt_orphaned(uuid, uuid, bigint, text),
    geo_stage_synthetic_artifact_expiry(timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(text, integer, integer),
    geo_complete_synthetic_artifact_deletion(uuid, uuid, bigint, uuid, text, timestamptz),
    geo_fail_synthetic_artifact_deletion(uuid, uuid, bigint, uuid, text, timestamptz),
    geo_assert_synthetic_lab_aggregate_append(),
    geo_assert_synthetic_lab_authorization_append(),
    geo_assert_synthetic_manual_import_preview_change(),
    geo_assert_synthetic_manual_import_preview_state(),
    geo_assert_synthetic_lab_imported_sample(),
    geo_assert_synthetic_lab_import_manifest(),
    geo_assert_synthetic_manual_import_terminal_consistency(),
    geo_assert_synthetic_manual_import_cleanup_outbox_change(),
    geo_assert_synthetic_manual_import_cleanup_receipt(),
    geo_create_synthetic_manual_import_preview(
        uuid, uuid, uuid, integer, text, text, text, text, text, text,
        uuid, timestamptz, timestamptz, uuid, text, text, text, text,
        text, text, bigint, text, text, text, text, integer, integer,
        integer, text
    ),
    geo_finalize_synthetic_manual_import_preview(
        uuid, uuid, integer, uuid, text, timestamptz, integer[], boolean,
        boolean, uuid, text, text, text
    ),
    geo_claim_synthetic_manual_import_cleanups(text, integer, integer),
    geo_complete_synthetic_manual_import_cleanup(
        uuid, uuid, bigint, uuid, uuid, text, timestamptz
    ),
    geo_fail_synthetic_manual_import_cleanup(
        uuid, uuid, bigint, uuid, text, timestamptz
    ),
    geo_assert_synthetic_lab_job_metadata(),
    geo_assert_synthetic_lab_outbox(),
    geo_assert_synthetic_model_call_child(),
    geo_assert_synthetic_model_call_child_job_change(),
    geo_propagate_synthetic_parent_job_change(),
    geo_wake_synthetic_parent_after_child_terminal(),
    geo_block_synthetic_unstarted_model_call_children(uuid, uuid, text),
    geo_assert_synthetic_lab_execution_task(),
    geo_assert_synthetic_lab_execution_result(),
    geo_assert_synthetic_lab_execution_result_consistency(),
    geo_assert_synthetic_lab_terminal(),
    geo_assert_synthetic_lab_terminal_consistency()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_synthetic_secret_handle_hash(uuid, uuid, text, integer),
    geo_assert_synthetic_artifact_master_key_change(),
    geo_assert_synthetic_style_collection_task(),
    geo_assert_synthetic_raw_artifact_insert(),
    geo_assert_synthetic_raw_artifact_change(),
    geo_assert_synthetic_artifact_dek_insert(),
    geo_assert_synthetic_artifact_dek_consistency(),
    geo_assert_synthetic_artifact_dek_change(),
    geo_assert_synthetic_artifact_outbox_change(),
    geo_assert_synthetic_style_collection_result(),
    geo_assert_synthetic_style_collection_result_consistency(),
    geo_assert_synthetic_lab_aggregate_append(),
    geo_assert_synthetic_lab_authorization_append(),
    geo_assert_synthetic_manual_import_preview_change(),
    geo_assert_synthetic_manual_import_preview_state(),
    geo_assert_synthetic_lab_imported_sample(),
    geo_assert_synthetic_lab_import_manifest(),
    geo_assert_synthetic_manual_import_terminal_consistency(),
    geo_assert_synthetic_manual_import_cleanup_outbox_change(),
    geo_assert_synthetic_manual_import_cleanup_receipt(),
    geo_assert_synthetic_lab_job_metadata(),
    geo_assert_synthetic_lab_outbox(),
    geo_assert_synthetic_model_call_child(),
    geo_assert_synthetic_model_call_child_job_change(),
    geo_propagate_synthetic_parent_job_change(),
    geo_wake_synthetic_parent_after_child_terminal(),
    geo_assert_synthetic_lab_execution_task(),
    geo_assert_synthetic_lab_execution_result(),
    geo_assert_synthetic_lab_execution_result_consistency(),
    geo_assert_synthetic_lab_terminal(),
    geo_assert_synthetic_lab_terminal_consistency()
TO geo_app, geo_worker;

GRANT EXECUTE ON FUNCTION
    geo_create_synthetic_manual_import_preview(
        uuid, uuid, uuid, integer, text, text, text, text, text, text,
        uuid, timestamptz, timestamptz, uuid, text, text, text, text,
        text, text, bigint, text, text, text, text, integer, integer,
        integer, text
    ),
    geo_finalize_synthetic_manual_import_preview(
        uuid, uuid, integer, uuid, text, timestamptz, integer[], boolean,
        boolean, uuid, text, text, text
    )
TO geo_app;

REVOKE ALL ON FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_enqueue_synthetic_model_call_child(
    uuid, uuid, uuid, bigint, uuid, text, text, text, integer,
    uuid, text, uuid, text, uuid, text, uuid, integer, uuid,
    integer, uuid, integer, text, text, text, uuid, text, text, text,
    text, text, text, text, uuid, text, uuid, text, text, text,
    text, text, text, text, text, numeric, integer, text
) TO geo_worker;
GRANT EXECUTE ON FUNCTION geo_block_synthetic_unstarted_model_call_children(
    uuid, uuid, text
) TO geo_app, geo_worker;

GRANT EXECUTE ON FUNCTION
    geo_sync_synthetic_artifact_master_key_version(text, text, text, bytea, bytea, timestamptz),
    geo_retire_synthetic_artifact_master_key_version(text, timestamptz),
    geo_mark_synthetic_artifact_attempt_orphaned(uuid, uuid, bigint, text),
    geo_stage_synthetic_artifact_expiry(timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(text, integer, integer),
    geo_complete_synthetic_artifact_deletion(uuid, uuid, bigint, uuid, text, timestamptz),
    geo_fail_synthetic_artifact_deletion(uuid, uuid, bigint, uuid, text, timestamptz)
TO geo_worker;

REVOKE ALL ON FUNCTION
    geo_stage_due_synthetic_artifact_expirations(timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(text, timestamptz, integer, integer),
    geo_crypto_erase_and_tombstone_synthetic_artifact(
        uuid, uuid, uuid, bigint, uuid, text, timestamptz
    ),
    geo_complete_synthetic_artifact_object_deletion(
        uuid, uuid, uuid, bigint, uuid, text, timestamptz
    ),
    geo_fail_synthetic_artifact_object_deletion(
        uuid, uuid, uuid, bigint, uuid, text, timestamptz
    ),
    geo_enqueue_synthetic_artifact_maintenance(timestamptz)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_stage_due_synthetic_artifact_expirations(timestamptz, integer),
    geo_claim_synthetic_artifact_deletions(text, timestamptz, integer, integer),
    geo_crypto_erase_and_tombstone_synthetic_artifact(
        uuid, uuid, uuid, bigint, uuid, text, timestamptz
    ),
    geo_complete_synthetic_artifact_object_deletion(
        uuid, uuid, uuid, bigint, uuid, text, timestamptz
    ),
    geo_fail_synthetic_artifact_object_deletion(
        uuid, uuid, uuid, bigint, uuid, text, timestamptz
    ),
    geo_enqueue_synthetic_artifact_maintenance(timestamptz)
TO geo_worker;

GRANT EXECUTE ON FUNCTION
    geo_claim_synthetic_manual_import_cleanups(text, integer, integer),
    geo_complete_synthetic_manual_import_cleanup(
        uuid, uuid, bigint, uuid, uuid, text, timestamptz
    ),
    geo_fail_synthetic_manual_import_cleanup(
        uuid, uuid, bigint, uuid, text, timestamptz
    )
TO geo_worker;

ALTER TABLE runtime_service_heartbeats
DROP CONSTRAINT runtime_service_heartbeats_service_type_check;
ALTER TABLE runtime_service_heartbeats
ADD CONSTRAINT runtime_service_heartbeats_service_type_check CHECK (
    service_type IN (
        'task_worker', 'outbox_relay', 'style_browser_worker',
        'synthetic_artifact_maintenance_worker'
    )
);

DO $$
DECLARE function_definition text;
DECLARE replacement text;
BEGIN
    function_definition := pg_get_functiondef(
        'geo_worker_record_runtime_heartbeat(text,text,text,text,text)'::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'runtime heartbeat function validation contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;

    function_definition := pg_get_functiondef(
        'geo_worker_runtime_findings(text,text,integer,integer,integer,integer,integer,integer)'
            ::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'runtime findings function validation contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
END;
$$;

COMMENT ON TABLE synthetic_lab_artifact_governance_decisions IS
    'Hash-only pre-persistence decisions. Raw bodies, credentials and login state are forbidden.';
COMMENT ON TABLE synthetic_lab_job_metadata IS
    'Identifier/hash-only Synthetic Lab lineage attached one-to-one to the shared Durable Job.';
COMMENT ON TABLE synthetic_lab_model_call_children IS
    'Immutable one-Prompt-per-child Durable Job lineage. Request bodies live only in governed object artifacts.';
COMMENT ON COLUMN synthetic_lab_model_call_children.portable_output_schema_hash IS
    'Exact Provider-portable structured-output Schema hash frozen before child admission.';
COMMENT ON COLUMN synthetic_lab_model_call_children.application_output_schema_hash IS
    'Exact full application validation Schema hash frozen independently from the Provider Schema.';
COMMENT ON VIEW synthetic_lab_model_call_child_status IS
    'Admin/worker status projection over child Durable Jobs and governed Model Gateway terminals.';
