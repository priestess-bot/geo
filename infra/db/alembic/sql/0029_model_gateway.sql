CREATE TABLE model_gateway_adapter_releases (
    provider text NOT NULL CHECK (provider ~ '^[a-z][a-z0-9_.-]{0,63}$'),
    adapter_release_id text NOT NULL CHECK (adapter_release_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$'),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    interface_contract_version text NOT NULL CHECK (btrim(interface_contract_version) <> ''),
    expected_capture_method text NOT NULL CHECK (
        expected_capture_method IN ('provider_api', 'proxy_grounded_api')
    ),
    external_training_allowed boolean NOT NULL,
    structured_output boolean NOT NULL,
    capability_data_retention_days integer CHECK (
        capability_data_retention_days IS NULL OR capability_data_retention_days >= 0
    ),
    capability_policy_reference text NOT NULL CHECK (btrim(capability_policy_reference) <> ''),
    supports_seed boolean NOT NULL,
    supports_tools boolean NOT NULL,
    supports_search boolean NOT NULL,
    supports_citations boolean NOT NULL,
    supports_idempotency boolean NOT NULL,
    supports_structured_output_with_tools boolean NOT NULL,
    capability_verification text NOT NULL CHECK (
        capability_verification IN ('verified', 'unverified')
    ),
    capability_evidence_reference text,
    capability_evidence_sha256 text CHECK (
        capability_evidence_sha256 IS NULL
        OR capability_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    data_storage_decision text NOT NULL CHECK (
        data_storage_decision IN ('allowed', 'prohibited', 'unverified')
    ),
    data_cache_decision text NOT NULL CHECK (
        data_cache_decision IN ('allowed', 'prohibited', 'unverified')
    ),
    data_display_decision text NOT NULL CHECK (
        data_display_decision IN ('allowed', 'prohibited', 'unverified')
    ),
    data_redistribution_decision text NOT NULL CHECK (
        data_redistribution_decision IN ('allowed', 'prohibited', 'unverified')
    ),
    data_policy_retention_days integer CHECK (
        data_policy_retention_days IS NULL OR data_policy_retention_days >= 0
    ),
    terms_reference text NOT NULL,
    terms_sha256 text CHECK (
        terms_sha256 IS NULL OR terms_sha256 ~ '^[0-9a-f]{64}$'
    ),
    data_policy_hash text NOT NULL CHECK (data_policy_hash ~ '^[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN ('draft', 'approved', 'retired')),
    registered_by uuid NOT NULL REFERENCES identities(id),
    registered_at timestamptz NOT NULL,
    PRIMARY KEY (provider, adapter_release_id),
    CONSTRAINT model_gateway_adapter_releases_exact_key UNIQUE (
        provider, adapter_release_id, release_hash
    ),
    CONSTRAINT model_gateway_adapter_releases_approved_shape CHECK (
        state <> 'approved'
        OR (
            capability_verification = 'verified'
            AND capability_evidence_reference IS NOT NULL
            AND capability_evidence_sha256 IS NOT NULL
            AND capability_evidence_reference ~ '^(https|minio|s3)://[^/@[:space:]]+(?::[0-9]+)?(?:/[^?#[:space:]]*)?$'
            AND capability_evidence_reference !~ '://[^/]*@'
            AND data_storage_decision <> 'unverified'
            AND data_cache_decision <> 'unverified'
            AND data_display_decision <> 'unverified'
            AND data_redistribution_decision <> 'unverified'
            AND terms_sha256 IS NOT NULL
            AND terms_reference ~ '^(https|minio|s3)://[^/@[:space:]]+(?::[0-9]+)?(?:/[^?#[:space:]]*)?$'
            AND terms_reference !~ '://[^/]*@'
        )
    ),
    CHECK ((capability_evidence_reference IS NULL) = (capability_evidence_sha256 IS NULL))
);

CREATE TABLE model_gateway_model_releases (
    provider text NOT NULL,
    adapter_release_id text NOT NULL,
    adapter_release_hash text NOT NULL CHECK (adapter_release_hash ~ '^[0-9a-f]{64}$'),
    model_release_id text NOT NULL CHECK (model_release_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$'),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    state text NOT NULL CHECK (state IN ('draft', 'approved', 'retired')),
    reported_model_policy text NOT NULL CHECK (
        reported_model_policy IN ('record_only', 'require_present', 'exact', 'allowlist')
    ),
    allowed_reported_models text[] NOT NULL DEFAULT ARRAY[]::text[],
    registered_by uuid NOT NULL REFERENCES identities(id),
    registered_at timestamptz NOT NULL,
    PRIMARY KEY (provider, adapter_release_id, model_release_id),
    CONSTRAINT model_gateway_model_releases_exact_key UNIQUE (
        provider, adapter_release_id, model_release_id, release_hash
    ),
    CONSTRAINT model_gateway_model_releases_adapter_fkey FOREIGN KEY (
        provider, adapter_release_id, adapter_release_hash
    ) REFERENCES model_gateway_adapter_releases(
        provider, adapter_release_id, release_hash
    ),
    CONSTRAINT model_gateway_model_releases_allowlist_shape CHECK (
        (reported_model_policy = 'allowlist' AND cardinality(allowed_reported_models) > 0)
        OR (reported_model_policy <> 'allowlist')
    )
);

CREATE TABLE model_gateway_project_policy_versions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version integer NOT NULL CHECK (version > 0),
    previous_version_id uuid,
    policy_hash text NOT NULL CHECK (policy_hash ~ '^[0-9a-f]{64}$'),
    allowed_providers text[] NOT NULL,
    allowed_adapter_release_ids text[] NOT NULL,
    external_training_allowed boolean NOT NULL,
    structured_output_required boolean NOT NULL,
    maximum_paid_calls_default integer NOT NULL CHECK (maximum_paid_calls_default > 0),
    maximum_concurrent_calls integer NOT NULL CHECK (maximum_concurrent_calls > 0),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    CONSTRAINT model_gateway_project_policy_versions_initial_shape CHECK (
        (version = 1 AND previous_version_id IS NULL)
        OR (version > 1 AND previous_version_id IS NOT NULL)
    ),
    CONSTRAINT model_gateway_project_policy_versions_allow_shape CHECK (
        cardinality(allowed_providers) > 0
        AND cardinality(allowed_adapter_release_ids) > 0
    ),
    CONSTRAINT model_gateway_project_policy_versions_project_key UNIQUE (id, project_id),
    CONSTRAINT model_gateway_project_policy_versions_exact_key UNIQUE (
        id, project_id, policy_hash
    ),
    CONSTRAINT model_gateway_project_policy_versions_version_key UNIQUE (
        project_id, version
    ),
    CONSTRAINT model_gateway_project_policy_versions_successor_key UNIQUE (
        previous_version_id, project_id
    ),
    CONSTRAINT model_gateway_project_policy_versions_previous_fkey FOREIGN KEY (
        previous_version_id, project_id
    ) REFERENCES model_gateway_project_policy_versions(id, project_id)
);

CREATE TABLE model_gateway_runtime_manifests (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    id uuid NOT NULL,
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    schema_version integer NOT NULL CHECK (schema_version = 2),
    status text NOT NULL CHECK (status IN ('approved', 'retired')),
    policy_version_id uuid NOT NULL,
    policy_version_hash text NOT NULL CHECK (policy_version_hash ~ '^[0-9a-f]{64}$'),
    source_artifact_hash text CHECK (
        source_artifact_hash IS NULL OR source_artifact_hash ~ '^[0-9a-f]{64}$'
    ),
    option_count integer NOT NULL CHECK (option_count > 0),
    prepared_by uuid NOT NULL REFERENCES identities(id),
    prepared_at timestamptz NOT NULL,
    approved_by uuid NOT NULL REFERENCES identities(id),
    approved_at timestamptz NOT NULL,
    approval_evidence_reference text NOT NULL CHECK (
        approval_evidence_reference ~ '^(https|minio|s3)://[^/@[:space:]]+(?::[0-9]+)?(?:/[^?#[:space:]]*)?$'
        AND approval_evidence_reference !~ '://[^/]*@'
    ),
    approval_evidence_sha256 text NOT NULL CHECK (
        approval_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    retired_by uuid REFERENCES identities(id),
    retired_at timestamptz,
    record_version integer NOT NULL DEFAULT 1 CHECK (record_version > 0),
    PRIMARY KEY (project_id, id),
    UNIQUE (id, project_id),
    UNIQUE (project_id, manifest_hash),
    UNIQUE (id, project_id, manifest_hash),
    FOREIGN KEY (policy_version_id, project_id, policy_version_hash)
        REFERENCES model_gateway_project_policy_versions(id, project_id, policy_hash),
    CONSTRAINT model_gateway_runtime_manifests_state_shape CHECK (
        (status = 'approved' AND retired_by IS NULL AND retired_at IS NULL)
        OR (status = 'retired' AND retired_by IS NOT NULL AND retired_at IS NOT NULL
            AND retired_at >= approved_at)
    ),
    CHECK (prepared_by <> approved_by),
    CHECK (prepared_at <= approved_at)
);

CREATE UNIQUE INDEX model_gateway_runtime_manifests_one_approved
ON model_gateway_runtime_manifests(project_id)
WHERE status = 'approved';

CREATE TABLE model_gateway_runtime_options (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    id uuid NOT NULL,
    manifest_id uuid NOT NULL,
    provider text NOT NULL,
    adapter_release_id text NOT NULL,
    adapter_release_hash text NOT NULL CHECK (adapter_release_hash ~ '^[0-9a-f]{64}$'),
    model_release_id text NOT NULL,
    model_release_hash text NOT NULL CHECK (model_release_hash ~ '^[0-9a-f]{64}$'),
    secret_reference_id uuid NOT NULL,
    secret_purpose text NOT NULL,
    microsoft_endpoint text,
    microsoft_agent_name text,
    microsoft_agent_version text,
    microsoft_market text,
    microsoft_language text,
    provider_config_hash text NOT NULL CHECK (provider_config_hash ~ '^[0-9a-f]{64}$'),
    allowed_purposes text[] NOT NULL CHECK (cardinality(allowed_purposes) > 0),
    allowed_search_modes jsonb NOT NULL CHECK (
        jsonb_typeof(allowed_search_modes) = 'array'
        AND jsonb_array_length(allowed_search_modes) > 0
    ),
    option_hash text NOT NULL CHECK (option_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (project_id, id),
    UNIQUE (id, project_id),
    UNIQUE (id, project_id, manifest_id, option_hash),
    UNIQUE (
        project_id, manifest_id, provider, adapter_release_id, model_release_id
    ),
    FOREIGN KEY (manifest_id, project_id)
        REFERENCES model_gateway_runtime_manifests(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (provider, adapter_release_id, adapter_release_hash)
        REFERENCES model_gateway_adapter_releases(
            provider, adapter_release_id, release_hash
        ),
    FOREIGN KEY (
        provider, adapter_release_id, model_release_id, model_release_hash
    ) REFERENCES model_gateway_model_releases(
        provider, adapter_release_id, model_release_id, release_hash
    ),
    FOREIGN KEY (secret_reference_id, project_id, secret_purpose)
        REFERENCES secret_references(id, project_id, purpose),
    CONSTRAINT model_gateway_runtime_options_secret_purpose CHECK (
        secret_purpose = 'model_provider.' || provider
    ),
    CONSTRAINT model_gateway_runtime_options_microsoft_shape CHECK (
        (provider = 'microsoft' AND microsoft_endpoint IS NOT NULL
            AND microsoft_agent_name IS NOT NULL
            AND microsoft_agent_version IS NOT NULL
            AND microsoft_market IS NOT NULL AND btrim(microsoft_market) <> ''
            AND microsoft_language IS NOT NULL AND btrim(microsoft_language) <> '')
        OR (provider <> 'microsoft' AND microsoft_endpoint IS NULL
            AND microsoft_agent_name IS NULL AND microsoft_agent_version IS NULL
            AND microsoft_market IS NULL AND microsoft_language IS NULL)
    )
);

CREATE TABLE model_gateway_job_admissions (
    job_id uuid NOT NULL,
    project_id uuid NOT NULL,
    job_kind text NOT NULL CHECK (btrim(job_kind) <> ''),
    job_version integer NOT NULL CHECK (job_version > 0),
    lease_token uuid NOT NULL,
    fencing_generation bigint NOT NULL CHECK (fencing_generation > 0),
    runtime_manifest_id uuid NOT NULL,
    runtime_manifest_hash text NOT NULL CHECK (runtime_manifest_hash ~ '^[0-9a-f]{64}$'),
    runtime_option_id uuid NOT NULL,
    runtime_option_hash text NOT NULL CHECK (runtime_option_hash ~ '^[0-9a-f]{64}$'),
    admission_mode text NOT NULL CHECK (
        admission_mode IN ('runtime_frozen', 'prompt_release_test')
    ),
    policy_version_id uuid NOT NULL,
    policy_version_hash text NOT NULL CHECK (policy_version_hash ~ '^[0-9a-f]{64}$'),
    purpose text NOT NULL CHECK (btrim(purpose) <> ''),
    usage_audience text NOT NULL CHECK (
        usage_audience IN ('internal_worker', 'admin', 'customer', 'export')
    ),
    provider text NOT NULL,
    adapter_release_id text NOT NULL,
    adapter_release_hash text NOT NULL CHECK (adapter_release_hash ~ '^[0-9a-f]{64}$'),
    model_release_id text NOT NULL,
    model_release_hash text NOT NULL CHECK (model_release_hash ~ '^[0-9a-f]{64}$'),
    provider_secret_reference_id uuid NOT NULL,
    provider_secret_version integer NOT NULL CHECK (provider_secret_version > 0),
    provider_secret_handle_hash text NOT NULL CHECK (
        provider_secret_handle_hash ~ '^[0-9a-f]{64}$'
    ),
    prompt_binding_id uuid,
    prompt_release_id uuid NOT NULL,
    prompt_release_hash text NOT NULL CHECK (prompt_release_hash ~ '^[0-9a-f]{64}$'),
    prompt_frozen_state_id uuid NOT NULL,
    prompt_state_version integer NOT NULL CHECK (prompt_state_version > 0),
    prompt_test_set_hash text CHECK (
        prompt_test_set_hash IS NULL OR prompt_test_set_hash ~ '^[0-9a-f]{64}$'
    ),
    prompt_bundle_hash text NOT NULL CHECK (prompt_bundle_hash ~ '^[0-9a-f]{64}$'),
    output_schema_hash text NOT NULL CHECK (output_schema_hash ~ '^[0-9a-f]{64}$'),
    application_output_schema_hash text NOT NULL CHECK (
        application_output_schema_hash ~ '^[0-9a-f]{64}$'
    ),
    raw_artifact_policy_hash text NOT NULL CHECK (
        raw_artifact_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    raw_artifact_storage_decision text NOT NULL CHECK (
        raw_artifact_storage_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_cache_decision text NOT NULL CHECK (
        raw_artifact_cache_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_display_decision text NOT NULL CHECK (
        raw_artifact_display_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_redistribution_decision text NOT NULL CHECK (
        raw_artifact_redistribution_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_retention_days integer CHECK (
        raw_artifact_retention_days IS NULL OR raw_artifact_retention_days >= 0
    ),
    maximum_paid_calls integer NOT NULL CHECK (maximum_paid_calls > 0),
    maximum_concurrent_calls integer NOT NULL CHECK (maximum_concurrent_calls > 0),
    paid_calls integer NOT NULL DEFAULT 0 CHECK (paid_calls >= 0),
    reserved_calls integer NOT NULL DEFAULT 0 CHECK (reserved_calls >= 0),
    budget_version integer NOT NULL DEFAULT 0 CHECK (budget_version >= 0),
    next_attempt_number integer NOT NULL DEFAULT 1 CHECK (next_attempt_number > 0),
    admitted_by uuid NOT NULL REFERENCES identities(id),
    admitted_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, job_id),
    CONSTRAINT model_gateway_job_admissions_scope_key UNIQUE (job_id, project_id),
    CONSTRAINT model_gateway_job_admissions_budget_shape CHECK (
        paid_calls + reserved_calls <= maximum_paid_calls
        AND reserved_calls <= maximum_concurrent_calls
    ),
    CONSTRAINT model_gateway_job_admissions_prompt_mode_shape CHECK (
        (admission_mode = 'runtime_frozen'
            AND prompt_binding_id IS NOT NULL AND prompt_test_set_hash IS NULL)
        OR (admission_mode = 'prompt_release_test'
            AND job_kind = 'prompt.test.execute' AND purpose = 'prompt_release_test'
            AND prompt_binding_id IS NULL AND prompt_test_set_hash IS NOT NULL)
    ),
    CONSTRAINT model_gateway_job_admissions_job_fkey FOREIGN KEY (
        job_id, project_id
    ) REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    CONSTRAINT model_gateway_job_admissions_runtime_manifest_fkey FOREIGN KEY (
        runtime_manifest_id, project_id, runtime_manifest_hash
    ) REFERENCES model_gateway_runtime_manifests(id, project_id, manifest_hash),
    CONSTRAINT model_gateway_job_admissions_runtime_option_fkey FOREIGN KEY (
        runtime_option_id, project_id, runtime_manifest_id, runtime_option_hash
    ) REFERENCES model_gateway_runtime_options(id, project_id, manifest_id, option_hash),
    CONSTRAINT model_gateway_job_admissions_policy_fkey FOREIGN KEY (
        policy_version_id, project_id, policy_version_hash
    ) REFERENCES model_gateway_project_policy_versions(id, project_id, policy_hash),
    CONSTRAINT model_gateway_job_admissions_adapter_fkey FOREIGN KEY (
        provider, adapter_release_id, adapter_release_hash
    ) REFERENCES model_gateway_adapter_releases(provider, adapter_release_id, release_hash),
    CONSTRAINT model_gateway_job_admissions_model_fkey FOREIGN KEY (
        provider, adapter_release_id, model_release_id, model_release_hash
    ) REFERENCES model_gateway_model_releases(
        provider, adapter_release_id, model_release_id, release_hash
    ),
    CONSTRAINT model_gateway_job_admissions_secret_fkey FOREIGN KEY (
        provider_secret_reference_id, provider_secret_version
    ) REFERENCES secret_versions(reference_id, version),
    CONSTRAINT model_gateway_job_admissions_binding_fkey FOREIGN KEY (
        prompt_binding_id, project_id
    ) REFERENCES prompt_program_bindings(id, project_id),
    CONSTRAINT model_gateway_job_admissions_release_fkey FOREIGN KEY (
        prompt_release_id, project_id, prompt_release_hash
    ) REFERENCES prompt_program_releases(id, project_id, release_hash),
    CONSTRAINT model_gateway_job_admissions_state_fkey FOREIGN KEY (
        prompt_frozen_state_id, project_id, prompt_release_id,
        prompt_release_hash, prompt_state_version
    ) REFERENCES prompt_program_release_states(
        id, project_id, release_id, release_hash, version
    )
);

CREATE TABLE model_gateway_call_attempts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    attempt_number integer NOT NULL CHECK (attempt_number > 0),
    expected_budget_version integer NOT NULL CHECK (expected_budget_version >= 0),
    job_version integer NOT NULL CHECK (job_version > 0),
    runtime_manifest_id uuid NOT NULL,
    runtime_manifest_hash text NOT NULL CHECK (runtime_manifest_hash ~ '^[0-9a-f]{64}$'),
    runtime_option_id uuid NOT NULL,
    runtime_option_hash text NOT NULL CHECK (runtime_option_hash ~ '^[0-9a-f]{64}$'),
    admission_mode text NOT NULL CHECK (
        admission_mode IN ('runtime_frozen', 'prompt_release_test')
    ),
    lease_token uuid NOT NULL,
    fencing_generation bigint NOT NULL CHECK (fencing_generation > 0),
    kind text NOT NULL CHECK (kind IN ('initial', 'retry', 'repair')),
    parent_attempt_id uuid,
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    policy_version_id uuid NOT NULL,
    policy_version_hash text NOT NULL CHECK (policy_version_hash ~ '^[0-9a-f]{64}$'),
    purpose text NOT NULL CHECK (btrim(purpose) <> ''),
    usage_audience text NOT NULL CHECK (
        usage_audience IN ('internal_worker', 'admin', 'customer', 'export')
    ),
    provider text NOT NULL,
    adapter_release_id text NOT NULL,
    adapter_release_hash text NOT NULL CHECK (adapter_release_hash ~ '^[0-9a-f]{64}$'),
    model_release_id text NOT NULL,
    model_release_hash text NOT NULL CHECK (model_release_hash ~ '^[0-9a-f]{64}$'),
    provider_secret_reference_id uuid NOT NULL,
    provider_secret_version integer NOT NULL CHECK (provider_secret_version > 0),
    provider_secret_handle_hash text NOT NULL CHECK (
        provider_secret_handle_hash ~ '^[0-9a-f]{64}$'
    ),
    prompt_binding_id uuid,
    prompt_release_id uuid NOT NULL,
    prompt_release_hash text NOT NULL CHECK (prompt_release_hash ~ '^[0-9a-f]{64}$'),
    prompt_state_id uuid NOT NULL,
    prompt_state_version integer NOT NULL CHECK (prompt_state_version > 0),
    prompt_test_set_hash text CHECK (
        prompt_test_set_hash IS NULL OR prompt_test_set_hash ~ '^[0-9a-f]{64}$'
    ),
    prompt_test_case_id uuid,
    prompt_test_case_hash text CHECK (
        prompt_test_case_hash IS NULL OR prompt_test_case_hash ~ '^[0-9a-f]{64}$'
    ),
    prompt_bundle_hash text NOT NULL CHECK (prompt_bundle_hash ~ '^[0-9a-f]{64}$'),
    output_schema_hash text NOT NULL CHECK (output_schema_hash ~ '^[0-9a-f]{64}$'),
    application_output_schema_hash text NOT NULL CHECK (
        application_output_schema_hash ~ '^[0-9a-f]{64}$'
    ),
    raw_artifact_policy_hash text NOT NULL CHECK (
        raw_artifact_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    raw_artifact_storage_decision text NOT NULL CHECK (
        raw_artifact_storage_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_cache_decision text NOT NULL CHECK (
        raw_artifact_cache_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_display_decision text NOT NULL CHECK (
        raw_artifact_display_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_redistribution_decision text NOT NULL CHECK (
        raw_artifact_redistribution_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_retention_days integer CHECK (
        raw_artifact_retention_days IS NULL OR raw_artifact_retention_days >= 0
    ),
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    search_mode text,
    requested_location_country text CHECK (
        requested_location_country IS NULL OR requested_location_country ~ '^[A-Z]{2}$'
    ),
    requested_location_region text CHECK (
        requested_location_region IS NULL
        OR requested_location_region ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'
    ),
    requested_location_locale text CHECK (
        requested_location_locale IS NULL
        OR requested_location_locale ~ '^[a-z]{2,3}(?:-[A-Z]{2})?$'
    ),
    requested_location_language text CHECK (
        requested_location_language IS NULL
        OR requested_location_language ~ '^[a-z]{2,3}$'
    ),
    expected_location_control text CHECK (
        expected_location_control IS NULL OR expected_location_control IN (
            'country', 'market_language', 'language_only', 'not_controlled'
        )
    ),
    expected_location_country text CHECK (
        expected_location_country IS NULL OR expected_location_country ~ '^[A-Z]{2}$'
    ),
    expected_location_region text CHECK (
        expected_location_region IS NULL
        OR expected_location_region ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'
    ),
    expected_location_locale text CHECK (
        expected_location_locale IS NULL
        OR expected_location_locale ~ '^[a-z]{2,3}(?:-[A-Z]{2})?$'
    ),
    expected_location_language text CHECK (
        expected_location_language IS NULL
        OR expected_location_language ~ '^[a-z]{2,3}$'
    ),
    expected_location_evidence_hash text CHECK (
        expected_location_evidence_hash IS NULL
        OR expected_location_evidence_hash ~ '^[0-9a-f]{64}$'
    ),
    capture_method text NOT NULL CHECK (
        capture_method IN ('provider_api', 'proxy_grounded_api')
    ),
    reserved_at timestamptz NOT NULL,
    CONSTRAINT model_gateway_call_attempts_scope_key UNIQUE (id, project_id, job_id),
    CONSTRAINT model_gateway_call_attempts_number_key UNIQUE (
        project_id, job_id, attempt_number
    ),
    CONSTRAINT model_gateway_call_attempts_idempotency_key UNIQUE (
        project_id, job_id, idempotency_key_hash
    ),
    CONSTRAINT model_gateway_call_attempts_parent_shape CHECK (
        (kind = 'initial' AND parent_attempt_id IS NULL)
        OR (kind IN ('retry', 'repair') AND parent_attempt_id IS NOT NULL)
    ),
    CONSTRAINT model_gateway_call_attempts_prompt_mode_shape CHECK (
        (admission_mode = 'runtime_frozen' AND prompt_binding_id IS NOT NULL
            AND prompt_test_set_hash IS NULL AND prompt_test_case_id IS NULL
            AND prompt_test_case_hash IS NULL)
        OR (admission_mode = 'prompt_release_test' AND prompt_binding_id IS NULL
            AND purpose = 'prompt_release_test' AND prompt_test_set_hash IS NOT NULL
            AND prompt_test_case_id IS NOT NULL
            AND prompt_test_case_id <> '00000000-0000-0000-0000-000000000000'::uuid
            AND prompt_test_case_hash IS NOT NULL)
    ),
    CONSTRAINT model_gateway_call_attempts_location_shape CHECK (
        (requested_location_country IS NULL AND requested_location_region IS NULL
            AND requested_location_locale IS NULL AND requested_location_language IS NULL
            AND expected_location_control IS NULL AND expected_location_country IS NULL
            AND expected_location_region IS NULL AND expected_location_locale IS NULL
            AND expected_location_language IS NULL
            AND expected_location_evidence_hash IS NULL)
        OR (requested_location_locale IS NOT NULL
            AND requested_location_language IS NOT NULL
            AND expected_location_control IS NOT NULL
            AND expected_location_evidence_hash IS NOT NULL
            AND (
                (expected_location_control = 'country'
                    AND expected_location_country IS NOT NULL
                    AND expected_location_region IS NULL
                    AND expected_location_locale IS NULL
                    AND expected_location_language IS NULL)
                OR (expected_location_control = 'market_language'
                    AND expected_location_country IS NULL
                    AND expected_location_region IS NULL
                    AND expected_location_locale IS NOT NULL
                    AND expected_location_language IS NOT NULL)
                OR (expected_location_control = 'language_only'
                    AND expected_location_country IS NULL
                    AND expected_location_region IS NULL
                    AND expected_location_locale IS NULL
                    AND expected_location_language IS NOT NULL)
                OR (expected_location_control = 'not_controlled'
                    AND expected_location_country IS NULL
                    AND expected_location_region IS NULL
                    AND expected_location_locale IS NULL
                    AND expected_location_language IS NULL)
            ))
    ),
    CONSTRAINT model_gateway_call_attempts_job_fkey FOREIGN KEY (
        job_id, project_id
    ) REFERENCES model_gateway_job_admissions(job_id, project_id) ON DELETE CASCADE,
    CONSTRAINT model_gateway_call_attempts_runtime_manifest_fkey FOREIGN KEY (
        runtime_manifest_id, project_id, runtime_manifest_hash
    ) REFERENCES model_gateway_runtime_manifests(id, project_id, manifest_hash),
    CONSTRAINT model_gateway_call_attempts_runtime_option_fkey FOREIGN KEY (
        runtime_option_id, project_id, runtime_manifest_id, runtime_option_hash
    ) REFERENCES model_gateway_runtime_options(id, project_id, manifest_id, option_hash),
    CONSTRAINT model_gateway_call_attempts_parent_fkey FOREIGN KEY (
        parent_attempt_id, project_id, job_id
    ) REFERENCES model_gateway_call_attempts(id, project_id, job_id),
    CONSTRAINT model_gateway_call_attempts_policy_fkey FOREIGN KEY (
        policy_version_id, project_id, policy_version_hash
    ) REFERENCES model_gateway_project_policy_versions(id, project_id, policy_hash),
    CONSTRAINT model_gateway_call_attempts_adapter_fkey FOREIGN KEY (
        provider, adapter_release_id, adapter_release_hash
    ) REFERENCES model_gateway_adapter_releases(provider, adapter_release_id, release_hash),
    CONSTRAINT model_gateway_call_attempts_model_fkey FOREIGN KEY (
        provider, adapter_release_id, model_release_id, model_release_hash
    ) REFERENCES model_gateway_model_releases(
        provider, adapter_release_id, model_release_id, release_hash
    ),
    CONSTRAINT model_gateway_call_attempts_secret_fkey FOREIGN KEY (
        provider_secret_reference_id, provider_secret_version
    ) REFERENCES secret_versions(reference_id, version),
    CONSTRAINT model_gateway_call_attempts_prompt_binding_fkey FOREIGN KEY (
        prompt_binding_id, project_id
    ) REFERENCES prompt_program_bindings(id, project_id),
    CONSTRAINT model_gateway_call_attempts_prompt_release_fkey FOREIGN KEY (
        prompt_release_id, project_id, prompt_release_hash
    ) REFERENCES prompt_program_releases(id, project_id, release_hash),
    CONSTRAINT model_gateway_call_attempts_prompt_state_fkey FOREIGN KEY (
        prompt_state_id, project_id, prompt_release_id,
        prompt_release_hash, prompt_state_version
    ) REFERENCES prompt_program_release_states(
        id, project_id, release_id, release_hash, version
    )
);

CREATE TABLE model_gateway_terminal_events (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL,
    job_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    expected_budget_version integer NOT NULL CHECK (expected_budget_version >= 0),
    status text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    occurred_at timestamptz NOT NULL,
    paid_call_count integer NOT NULL CHECK (paid_call_count IN (0, 1)),
    gateway_call_log_id uuid,
    configured_model text NOT NULL CHECK (btrim(configured_model) <> ''),
    provider_reported_model text,
    provider_request_id text,
    prompt_tokens integer CHECK (prompt_tokens IS NULL OR prompt_tokens >= 0),
    completion_tokens integer CHECK (completion_tokens IS NULL OR completion_tokens >= 0),
    cost_usd numeric(18,8) CHECK (cost_usd IS NULL OR cost_usd >= 0),
    finish_reason text,
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    output_hash text CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    response_hash text CHECK (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'),
    effective_location_control text CHECK (
        effective_location_control IS NULL OR effective_location_control IN (
            'country', 'market_language', 'language_only', 'not_controlled'
        )
    ),
    effective_location_country text CHECK (
        effective_location_country IS NULL OR effective_location_country ~ '^[A-Z]{2}$'
    ),
    effective_location_region text CHECK (
        effective_location_region IS NULL
        OR effective_location_region ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'
    ),
    effective_location_locale text CHECK (
        effective_location_locale IS NULL
        OR effective_location_locale ~ '^[a-z]{2,3}(?:-[A-Z]{2})?$'
    ),
    effective_location_language text CHECK (
        effective_location_language IS NULL
        OR effective_location_language ~ '^[a-z]{2,3}$'
    ),
    effective_location_evidence_hash text CHECK (
        effective_location_evidence_hash IS NULL
        OR effective_location_evidence_hash ~ '^[0-9a-f]{64}$'
    ),
    search_mode text,
    capture_method text NOT NULL CHECK (
        capture_method IN ('provider_api', 'proxy_grounded_api')
    ),
    citation_count integer NOT NULL CHECK (citation_count >= 0),
    citation_lineage_hash text NOT NULL CHECK (citation_lineage_hash ~ '^[0-9a-f]{64}$'),
    search_event_count integer NOT NULL CHECK (search_event_count >= 0),
    search_lineage_hash text NOT NULL CHECK (search_lineage_hash ~ '^[0-9a-f]{64}$'),
    usage_details_hash text NOT NULL CHECK (usage_details_hash ~ '^[0-9a-f]{64}$'),
    usage_purpose text NOT NULL CHECK (btrim(usage_purpose) <> ''),
    usage_audience text NOT NULL CHECK (
        usage_audience IN ('internal_worker', 'admin', 'customer', 'export')
    ),
    raw_artifact_reference_hash text CHECK (
        raw_artifact_reference_hash IS NULL OR raw_artifact_reference_hash ~ '^[0-9a-f]{64}$'
    ),
    raw_artifact_policy_hash text NOT NULL CHECK (
        raw_artifact_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    raw_artifact_storage_decision text NOT NULL CHECK (
        raw_artifact_storage_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_cache_decision text NOT NULL CHECK (
        raw_artifact_cache_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_display_decision text NOT NULL CHECK (
        raw_artifact_display_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_redistribution_decision text NOT NULL CHECK (
        raw_artifact_redistribution_decision IN ('allowed', 'prohibited')
    ),
    raw_artifact_retention_days integer CHECK (
        raw_artifact_retention_days IS NULL OR raw_artifact_retention_days >= 0
    ),
    error_classification text CHECK (
        error_classification IS NULL OR error_classification IN (
            'provider', 'application_structured_output',
            'application_result_contract', 'manual_reconciliation'
        )
    ),
    error_code text CHECK (
        error_code IS NULL OR error_code IN (
            'auth', 'quota', 'rate_limit', 'timeout', 'schema_invalid',
            'content_refusal', 'provider_unavailable', 'cancelled',
            'non_retryable_validation', 'configuration', 'policy', 'budget_exceeded'
        )
    ),
    error_retryable boolean,
    reconciled_by uuid REFERENCES identities(id),
    reconciliation_evidence_ref text,
    CONSTRAINT model_gateway_terminal_events_attempt_key UNIQUE (
        project_id, attempt_id
    ),
    CONSTRAINT model_gateway_terminal_events_scope_key UNIQUE (
        id, project_id, job_id
    ),
    CONSTRAINT model_gateway_terminal_events_attempt_fkey FOREIGN KEY (
        attempt_id, project_id, job_id
    ) REFERENCES model_gateway_call_attempts(id, project_id, job_id),
    CONSTRAINT model_gateway_terminal_events_status_shape CHECK (
        (status = 'succeeded'
            AND paid_call_count = 1
            AND output_hash IS NOT NULL AND response_hash IS NOT NULL
            AND (
                error_classification IS NULL
                OR error_classification = 'manual_reconciliation'
            )
            AND error_code IS NULL
            AND error_retryable IS NULL)
        OR (status = 'failed'
            AND error_classification IS NOT NULL AND error_code IS NOT NULL
            AND error_retryable IS NOT NULL)
    ),
    CONSTRAINT model_gateway_terminal_events_reconciliation_pair CHECK (
        (reconciled_by IS NULL) = (reconciliation_evidence_ref IS NULL)
    ),
    CONSTRAINT model_gateway_terminal_events_reconciliation_class CHECK (
        (reconciled_by IS NULL
            AND error_classification IS DISTINCT FROM 'manual_reconciliation')
        OR (reconciled_by IS NOT NULL
            AND error_classification = 'manual_reconciliation')
    ),
    CONSTRAINT model_gateway_terminal_events_failed_artifact_shape CHECK (
        status <> 'failed'
        OR (
            output_hash IS NULL AND response_hash IS NULL
            AND gateway_call_log_id IS NULL
        )
        OR (
            paid_call_count = 1
            AND error_classification IN (
                'application_structured_output',
                'application_result_contract',
                'manual_reconciliation'
            )
        )
    ),
    CONSTRAINT model_gateway_terminal_events_raw_storage_shape CHECK (
        raw_artifact_storage_decision = 'allowed'
        OR raw_artifact_reference_hash IS NULL
    ),
    CONSTRAINT model_gateway_terminal_events_location_shape CHECK (
        (effective_location_control IS NULL
            AND effective_location_country IS NULL
            AND effective_location_region IS NULL
            AND effective_location_locale IS NULL
            AND effective_location_language IS NULL
            AND effective_location_evidence_hash IS NULL)
        OR (effective_location_control IS NOT NULL
            AND effective_location_evidence_hash IS NOT NULL
            AND (
                (effective_location_control = 'country'
                    AND effective_location_country IS NOT NULL
                    AND effective_location_region IS NULL
                    AND effective_location_locale IS NULL
                    AND effective_location_language IS NULL)
                OR (effective_location_control = 'market_language'
                    AND effective_location_country IS NULL
                    AND effective_location_region IS NULL
                    AND effective_location_locale IS NOT NULL
                    AND effective_location_language IS NOT NULL)
                OR (effective_location_control = 'language_only'
                    AND effective_location_country IS NULL
                    AND effective_location_region IS NULL
                    AND effective_location_locale IS NULL
                    AND effective_location_language IS NOT NULL)
                OR (effective_location_control = 'not_controlled'
                    AND effective_location_country IS NULL
                    AND effective_location_region IS NULL
                    AND effective_location_locale IS NULL
                    AND effective_location_language IS NULL)
            ))
    )
);

ALTER TABLE model_gateway_call_attempts
ADD CONSTRAINT model_gateway_call_attempts_project_key UNIQUE (id, project_id);
ALTER TABLE model_gateway_terminal_events
ADD CONSTRAINT model_gateway_terminal_events_project_key UNIQUE (id, project_id);

CREATE TABLE model_gateway_reconciliation_commands (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    attempt_id uuid NOT NULL,
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    expected_budget_version integer NOT NULL CHECK (expected_budget_version >= 0),
    terminal_event_id uuid NOT NULL,
    reconciled_by uuid NOT NULL REFERENCES identities(id),
    recorded_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, idempotency_key_hash),
    UNIQUE (project_id, attempt_id),
    FOREIGN KEY (attempt_id, project_id)
        REFERENCES model_gateway_call_attempts(id, project_id),
    FOREIGN KEY (terminal_event_id, project_id)
        REFERENCES model_gateway_terminal_events(id, project_id)
);

CREATE TABLE model_gateway_artifact_recovery_receipts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_model_job_id uuid NOT NULL,
    recovery_job_id uuid NOT NULL,
    model_call_attempt_id uuid NOT NULL,
    artifact_id uuid NOT NULL,
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    expected_output_hash text NOT NULL CHECK (expected_output_hash ~ '^[0-9a-f]{64}$'),
    recovered_output_hash text NOT NULL CHECK (recovered_output_hash ~ '^[0-9a-f]{64}$'),
    purpose text NOT NULL CHECK (purpose ~ '^[a-z][a-z0-9_.-]{0,127}$'),
    audience text NOT NULL CHECK (audience = 'internal_worker'),
    lease_token uuid NOT NULL,
    fencing_generation bigint NOT NULL CHECK (fencing_generation > 0),
    receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
    recovered_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (
        project_id, source_model_job_id, recovery_job_id,
        model_call_attempt_id, artifact_id, purpose
    ),
    FOREIGN KEY (source_model_job_id, project_id)
        REFERENCES durable_jobs(id, project_id),
    FOREIGN KEY (recovery_job_id, project_id)
        REFERENCES durable_jobs(id, project_id),
    FOREIGN KEY (model_call_attempt_id, project_id)
        REFERENCES model_gateway_call_attempts(id, project_id),
    CHECK (expected_output_hash = recovered_output_hash)
);

CREATE TABLE model_gateway_artifact_master_key_versions (
    master_key_version integer PRIMARY KEY CHECK (master_key_version > 0),
    status text NOT NULL CHECK (
        status IN ('encrypt_decrypt', 'decrypt_only', 'retired')
    ),
    algorithm text NOT NULL CHECK (algorithm = 'AES-256-GCM'),
    canary_nonce bytea NOT NULL CHECK (octet_length(canary_nonce) = 12),
    canary_ciphertext bytea NOT NULL CHECK (octet_length(canary_ciphertext) >= 17),
    created_at timestamptz NOT NULL,
    retired_at timestamptz,
    CONSTRAINT model_gateway_artifact_master_key_versions_state_shape CHECK (
        (status IN ('encrypt_decrypt', 'decrypt_only') AND retired_at IS NULL)
        OR (status = 'retired' AND retired_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX model_gateway_artifact_master_key_versions_active_key
ON model_gateway_artifact_master_key_versions ((status))
WHERE status = 'encrypt_decrypt';

CREATE TABLE model_gateway_artifact_bundles (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id uuid NOT NULL,
    attempt_id uuid NOT NULL UNIQUE,
    provider text NOT NULL,
    adapter_release_id text NOT NULL,
    adapter_release_hash text NOT NULL CHECK (adapter_release_hash ~ '^[0-9a-f]{64}$'),
    data_policy_hash text NOT NULL CHECK (data_policy_hash ~ '^[0-9a-f]{64}$'),
    storage_decision text NOT NULL CHECK (storage_decision = 'allowed'),
    cache_decision text NOT NULL CHECK (cache_decision IN ('allowed', 'prohibited')),
    display_decision text NOT NULL CHECK (display_decision IN ('allowed', 'prohibited')),
    redistribution_decision text NOT NULL CHECK (
        redistribution_decision IN ('allowed', 'prohibited')
    ),
    usage_purpose text NOT NULL CHECK (btrim(usage_purpose) <> ''),
    audience text NOT NULL CHECK (
        audience IN ('internal_worker', 'admin', 'customer', 'export')
    ),
    retention_days integer CHECK (retention_days IS NULL OR retention_days >= 0),
    status text NOT NULL CHECK (status IN (
        'staged', 'committed', 'orphaned', 'deletion_pending', 'deleted'
    )),
    staged_at timestamptz NOT NULL,
    committed_at timestamptz,
    orphaned_at timestamptz,
    deletion_pending_at timestamptz,
    deleted_at timestamptz,
    expires_at timestamptz,
    terminal_event_id uuid,
    record_version integer NOT NULL DEFAULT 1 CHECK (record_version > 0),
    CONSTRAINT model_gateway_artifact_bundles_scope_key UNIQUE (id, project_id),
    CONSTRAINT model_gateway_artifact_bundles_attempt_key UNIQUE (
        attempt_id, project_id, job_id
    ),
    CONSTRAINT model_gateway_artifact_bundles_attempt_fkey FOREIGN KEY (
        attempt_id, project_id, job_id
    ) REFERENCES model_gateway_call_attempts(id, project_id, job_id) ON DELETE CASCADE,
    CONSTRAINT model_gateway_artifact_bundles_adapter_fkey FOREIGN KEY (
        provider, adapter_release_id, adapter_release_hash
    ) REFERENCES model_gateway_adapter_releases(provider, adapter_release_id, release_hash),
    CONSTRAINT model_gateway_artifact_bundles_terminal_fkey FOREIGN KEY (
        terminal_event_id, project_id, job_id
    ) REFERENCES model_gateway_terminal_events(id, project_id, job_id)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT model_gateway_artifact_bundles_time_shape CHECK (
        (status = 'staged' AND committed_at IS NULL AND orphaned_at IS NULL
            AND deletion_pending_at IS NULL AND deleted_at IS NULL
            AND terminal_event_id IS NULL)
        OR (status = 'committed' AND committed_at IS NOT NULL AND orphaned_at IS NULL
            AND deletion_pending_at IS NULL AND deleted_at IS NULL
            AND terminal_event_id IS NOT NULL)
        OR (status = 'orphaned' AND orphaned_at IS NOT NULL
            AND committed_at IS NULL AND deletion_pending_at IS NULL
            AND deleted_at IS NULL)
        OR (status = 'deletion_pending' AND deletion_pending_at IS NOT NULL
            AND deleted_at IS NULL)
        OR (status = 'deleted' AND deletion_pending_at IS NOT NULL
            AND deleted_at IS NOT NULL)
    ),
    CONSTRAINT model_gateway_artifact_bundles_expiry_shape CHECK (
        (retention_days IS NULL AND expires_at IS NULL)
        OR (retention_days IS NOT NULL
            AND expires_at = staged_at + make_interval(days => retention_days))
    )
);

CREATE TABLE model_gateway_artifact_deks (
    key_ref uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL UNIQUE,
    ciphertext bytea,
    data_nonce bytea,
    wrapped_data_key bytea,
    wrap_nonce bytea,
    master_key_version integer NOT NULL REFERENCES model_gateway_artifact_master_key_versions(
        master_key_version
    ),
    algorithm text NOT NULL CHECK (algorithm = 'AES-256-GCM'),
    status text NOT NULL CHECK (status IN ('active', 'destroyed')),
    created_at timestamptz NOT NULL,
    destroyed_at timestamptz,
    CONSTRAINT model_gateway_artifact_deks_scope_key UNIQUE (
        key_ref, project_id, artifact_id
    ),
    CONSTRAINT model_gateway_artifact_deks_identity_shape CHECK (
        key_ref = artifact_id
    ),
    CONSTRAINT model_gateway_artifact_deks_state_shape CHECK (
        (status = 'active' AND ciphertext IS NOT NULL
            AND octet_length(ciphertext) >= 17
            AND octet_length(data_nonce) = 12
            AND octet_length(wrapped_data_key) = 48
            AND octet_length(wrap_nonce) = 12
            AND destroyed_at IS NULL)
        OR (status = 'destroyed' AND ciphertext IS NULL AND data_nonce IS NULL
            AND wrapped_data_key IS NULL AND wrap_nonce IS NULL
            AND destroyed_at IS NOT NULL)
    )
);

CREATE TABLE model_gateway_artifacts (
    bundle_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('raw', 'derived')),
    project_id uuid NOT NULL,
    artifact_id uuid NOT NULL UNIQUE,
    manifest_uri text NOT NULL CHECK (manifest_uri ~ '^s3://[^/]+/.+'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    payload_uri text NOT NULL CHECK (payload_uri ~ '^s3://[^/]+/.+'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    content_byte_size bigint NOT NULL CHECK (content_byte_size > 0),
    stored_byte_size bigint NOT NULL CHECK (stored_byte_size > 0),
    classification text NOT NULL CHECK (btrim(classification) <> ''),
    encryption_algorithm text NOT NULL CHECK (
        encryption_algorithm = 'AES-256-GCM/independent-DEK/v1'
    ),
    key_ref uuid NOT NULL UNIQUE,
    expires_at timestamptz,
    PRIMARY KEY (bundle_id, kind),
    CONSTRAINT model_gateway_artifacts_scope_key UNIQUE (
        artifact_id, project_id, bundle_id, kind
    ),
    CONSTRAINT model_gateway_artifacts_bundle_fkey FOREIGN KEY (
        bundle_id, project_id
    ) REFERENCES model_gateway_artifact_bundles(id, project_id) ON DELETE CASCADE,
    CONSTRAINT model_gateway_artifacts_dek_fkey FOREIGN KEY (
        key_ref, project_id, artifact_id
    ) REFERENCES model_gateway_artifact_deks(key_ref, project_id, artifact_id)
);

CREATE TABLE model_gateway_artifact_deletion_outbox (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    bundle_id uuid NOT NULL,
    reason text NOT NULL CHECK (reason IN ('orphaned', 'retention_expired', 'manual')),
    status text NOT NULL CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    available_at timestamptz NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_token uuid,
    lease_expires_at timestamptz,
    fencing_generation bigint NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
    last_error_code text CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_]{0,62}$'
    ),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    CONSTRAINT model_gateway_artifact_deletion_outbox_scope_key UNIQUE (id, project_id),
    CONSTRAINT model_gateway_artifact_deletion_outbox_bundle_fkey FOREIGN KEY (
        bundle_id, project_id
    ) REFERENCES model_gateway_artifact_bundles(id, project_id) ON DELETE CASCADE,
    CONSTRAINT model_gateway_artifact_deletion_outbox_lease_shape CHECK (
        (status = 'pending' AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NULL)
        OR (status = 'processing' AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND completed_at IS NULL)
        OR (status = 'completed' AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NOT NULL)
        OR (status = 'failed' AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NULL AND last_error_code IS NOT NULL)
    )
);

CREATE UNIQUE INDEX model_gateway_artifact_deletion_one_active
ON model_gateway_artifact_deletion_outbox(bundle_id)
WHERE status IN ('pending', 'processing');

CREATE TABLE model_gateway_artifact_tombstones (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    bundle_id uuid NOT NULL UNIQUE,
    reason text NOT NULL CHECK (reason IN ('orphaned', 'retention_expired', 'manual')),
    raw_manifest_hash text NOT NULL CHECK (raw_manifest_hash ~ '^[0-9a-f]{64}$'),
    derived_manifest_hash text NOT NULL CHECK (
        derived_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    deletion_receipt_hash text NOT NULL CHECK (
        deletion_receipt_hash ~ '^[0-9a-f]{64}$'
    ),
    deleted_at timestamptz NOT NULL,
    CONSTRAINT model_gateway_artifact_tombstones_scope_key UNIQUE (id, project_id),
    CONSTRAINT model_gateway_artifact_tombstones_bundle_fkey FOREIGN KEY (
        bundle_id, project_id
    ) REFERENCES model_gateway_artifact_bundles(id, project_id)
);

CREATE FUNCTION geo_assert_model_gateway_text_array(
    values_to_check text[], field_name text
) RETURNS void
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    value text;
BEGIN
    IF cardinality(values_to_check) = 0 THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514', MESSAGE = field_name || ' cannot be empty';
    END IF;
    FOREACH value IN ARRAY values_to_check LOOP
        IF value IS NULL OR btrim(value) = '' THEN
            RAISE EXCEPTION USING
                ERRCODE = '23514', MESSAGE = field_name || ' contains an empty value';
        END IF;
    END LOOP;
    IF cardinality(values_to_check) <> (
        SELECT count(DISTINCT item) FROM unnest(values_to_check) AS item
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '23514', MESSAGE = field_name || ' contains duplicates';
    END IF;
END;
$$;

CREATE FUNCTION geo_model_gateway_secret_handle_hash(
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

CREATE FUNCTION geo_assert_model_gateway_runtime_manifest_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE active_memberships integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT count(*) INTO active_memberships
        FROM project_memberships
        WHERE project_id = NEW.project_id
          AND identity_id IN (NEW.prepared_by, NEW.approved_by)
          AND role IN ('owner', 'admin');
        IF active_memberships <> 2
           OR NEW.prepared_by = NEW.approved_by
           OR NEW.prepared_at > NEW.approved_at
           OR NEW.prepared_at > clock_timestamp() + interval '5 minutes'
           OR NEW.approved_at > clock_timestamp() + interval '5 minutes'
           OR NEW.status <> 'approved' OR NEW.record_version <> 1
           OR NEW.retired_by IS NOT NULL OR NEW.retired_at IS NOT NULL
           OR NEW.source_artifact_hash IS DISTINCT FROM NEW.manifest_hash THEN
            RAISE EXCEPTION 'Model Gateway runtime manifest approval governance is invalid'
                USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Model Gateway runtime manifests are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.project_id, OLD.id, OLD.manifest_hash, OLD.schema_version,
        OLD.policy_version_id, OLD.policy_version_hash, OLD.source_artifact_hash,
        OLD.option_count, OLD.prepared_by, OLD.prepared_at,
        OLD.approved_by, OLD.approved_at, OLD.approval_evidence_reference,
        OLD.approval_evidence_sha256)
       IS DISTINCT FROM
       (NEW.project_id, NEW.id, NEW.manifest_hash, NEW.schema_version,
        NEW.policy_version_id, NEW.policy_version_hash, NEW.source_artifact_hash,
        NEW.option_count, NEW.prepared_by, NEW.prepared_at,
        NEW.approved_by, NEW.approved_at, NEW.approval_evidence_reference,
        NEW.approval_evidence_sha256)
       OR OLD.status <> 'approved' OR NEW.status <> 'retired'
       OR NEW.retired_by IS NULL OR NEW.retired_at IS NULL
       OR NEW.retired_at > clock_timestamp() + interval '5 minutes'
       OR NOT EXISTS (
            SELECT 1 FROM project_memberships
            WHERE project_id = NEW.project_id AND identity_id = NEW.retired_by
              AND role IN ('owner', 'admin')
       )
       OR NEW.record_version <> OLD.record_version + 1 THEN
        RAISE EXCEPTION 'Model Gateway runtime manifest transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_runtime_option() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE manifest model_gateway_runtime_manifests%ROWTYPE;
DECLARE policy model_gateway_project_policy_versions%ROWTYPE;
DECLARE adapter model_gateway_adapter_releases%ROWTYPE;
DECLARE model model_gateway_model_releases%ROWTYPE;
DECLARE provider_secret record;
DECLARE expected_provider_config_hash text;
DECLARE expected_option_hash text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'model-runtime-manifest:' || NEW.project_id::text, 0
    ));
    SELECT * INTO STRICT manifest FROM model_gateway_runtime_manifests
    WHERE id = NEW.manifest_id AND project_id = NEW.project_id
    FOR SHARE;
    SELECT * INTO STRICT policy FROM model_gateway_project_policy_versions
    WHERE id = manifest.policy_version_id AND project_id = manifest.project_id
      AND policy_hash = manifest.policy_version_hash;
    SELECT * INTO STRICT adapter FROM model_gateway_adapter_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND release_hash = NEW.adapter_release_hash;
    SELECT * INTO STRICT model FROM model_gateway_model_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND model_release_id = NEW.model_release_id
      AND release_hash = NEW.model_release_hash;
    SELECT reference.current_version, version.status
    INTO STRICT provider_secret
    FROM secret_references AS reference
    JOIN secret_versions AS version
      ON version.reference_id = reference.id
     AND version.project_id = reference.project_id
     AND version.purpose = reference.purpose
     AND version.version = reference.current_version
    WHERE reference.id = NEW.secret_reference_id
      AND reference.project_id = NEW.project_id
      AND reference.purpose = NEW.secret_purpose;
    PERFORM geo_assert_model_gateway_text_array(
        NEW.allowed_purposes, 'runtime option allowed purposes'
    );
    IF manifest.status <> 'approved'
       OR NEW.provider <> ALL(policy.allowed_providers)
       OR NEW.adapter_release_id <> ALL(policy.allowed_adapter_release_ids)
       OR adapter.state <> 'approved' OR model.state <> 'approved'
       OR model.adapter_release_hash <> NEW.adapter_release_hash
       OR provider_secret.status <> 'active'
       OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(NEW.allowed_search_modes) AS mode
            WHERE jsonb_typeof(mode) NOT IN ('string', 'null')
               OR (jsonb_typeof(mode) = 'string' AND btrim(mode #>> '{}') = '')
       ) OR jsonb_array_length(NEW.allowed_search_modes) <> (
            SELECT count(DISTINCT geo_jsonb_canonical_text(mode))
            FROM jsonb_array_elements(NEW.allowed_search_modes) AS mode
       ) THEN
        RAISE EXCEPTION 'Model Gateway runtime option violates approved live dependencies'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.provider = 'microsoft' AND (
        NEW.microsoft_endpoint !~ '^https://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.services\.ai\.azure\.com(?::443)?(?:/[^?#]*)?$'
        OR btrim(NEW.microsoft_agent_name) = ''
        OR btrim(NEW.microsoft_agent_version) = ''
        OR btrim(NEW.microsoft_market) = ''
        OR btrim(NEW.microsoft_language) = ''
    ) THEN
        RAISE EXCEPTION 'Microsoft runtime option endpoint or Agent Reference is invalid'
            USING ERRCODE = '23514';
    END IF;
    expected_provider_config_hash := encode(digest(convert_to(
        geo_jsonb_canonical_text(jsonb_build_object(
            'capture_method', adapter.expected_capture_method,
            'microsoft_endpoint', NEW.microsoft_endpoint,
            'microsoft_agent_name', NEW.microsoft_agent_name,
            'microsoft_agent_version', NEW.microsoft_agent_version,
            'microsoft_market', NEW.microsoft_market,
            'microsoft_language', NEW.microsoft_language
        )), 'UTF8'
    ), 'sha256'), 'hex');
    expected_option_hash := encode(digest(convert_to(
        geo_jsonb_canonical_text(jsonb_build_object(
            'schema_version', 1,
            'manifest_id', NEW.manifest_id,
            'project_id', NEW.project_id,
            'provider', NEW.provider,
            'adapter_release_id', NEW.adapter_release_id,
            'adapter_release_hash', NEW.adapter_release_hash,
            'model_release_id', NEW.model_release_id,
            'model_release_hash', NEW.model_release_hash,
            'secret_reference_id', NEW.secret_reference_id,
            'provider_config_hash', NEW.provider_config_hash,
            'allowed_purposes', to_jsonb(NEW.allowed_purposes),
            'allowed_search_modes', NEW.allowed_search_modes
        )), 'UTF8'
    ), 'sha256'), 'hex');
    IF NEW.provider_config_hash <> expected_provider_config_hash
       OR NEW.option_hash <> expected_option_hash THEN
        RAISE EXCEPTION 'Model Gateway runtime option hashes differ from canonical content'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_runtime_manifest_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE manifest model_gateway_runtime_manifests%ROWTYPE;
DECLARE policy model_gateway_project_policy_versions%ROWTYPE;
DECLARE actual_options integer;
DECLARE actual_providers text[];
DECLARE actual_adapters text[];
BEGIN
    SELECT * INTO STRICT manifest FROM model_gateway_runtime_manifests
    WHERE id = coalesce((to_jsonb(NEW) ->> 'manifest_id')::uuid, NEW.id)
      AND project_id = NEW.project_id;
    IF manifest.status <> 'approved' THEN
        RETURN NULL;
    END IF;
    SELECT * INTO STRICT policy FROM model_gateway_project_policy_versions
    WHERE id = manifest.policy_version_id AND project_id = manifest.project_id
      AND policy_hash = manifest.policy_version_hash;
    SELECT count(*), array_agg(DISTINCT provider ORDER BY provider),
           array_agg(DISTINCT adapter_release_id ORDER BY adapter_release_id)
    INTO actual_options, actual_providers, actual_adapters
    FROM model_gateway_runtime_options
    WHERE project_id = manifest.project_id AND manifest_id = manifest.id;
    IF actual_options <> manifest.option_count
       OR NOT policy.allowed_providers <@ coalesce(actual_providers, ARRAY[]::text[])
       OR NOT coalesce(actual_providers, ARRAY[]::text[]) <@ policy.allowed_providers
       OR NOT policy.allowed_adapter_release_ids <@ coalesce(actual_adapters, ARRAY[]::text[])
       OR NOT coalesce(actual_adapters, ARRAY[]::text[]) <@ policy.allowed_adapter_release_ids THEN
        RAISE EXCEPTION 'Model Gateway runtime manifest options do not match frozen policy'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_register_model_gateway_runtime_manifest(
    p_id uuid,
    p_project_id uuid,
    p_manifest_hash text,
    p_schema_version integer,
    p_policy_version_id uuid,
    p_policy_version_hash text,
    p_source_artifact_hash text,
    p_option_count integer,
    p_prepared_by uuid,
    p_prepared_at timestamptz,
    p_approved_by uuid,
    p_approved_at timestamptz,
    p_approval_evidence_reference text,
    p_approval_evidence_sha256 text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing model_gateway_runtime_manifests%ROWTYPE;
BEGIN
    IF p_id IS NULL OR p_project_id IS NULL OR p_prepared_by IS NULL
       OR p_approved_by IS NULL OR p_prepared_by = p_approved_by
       OR p_manifest_hash !~ '^[0-9a-f]{64}$' OR p_schema_version <> 2
       OR p_policy_version_hash !~ '^[0-9a-f]{64}$'
       OR p_source_artifact_hash IS DISTINCT FROM p_manifest_hash
       OR p_option_count < 1 OR p_prepared_at IS NULL OR p_approved_at IS NULL
       OR p_prepared_at > p_approved_at
       OR p_approval_evidence_reference IS NULL
       OR p_approval_evidence_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid Model Gateway runtime manifest registration'
            USING ERRCODE = '22023';
    END IF;
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'runtime manifest Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'model-runtime-manifest:' || p_project_id::text, 0
    ));
    SELECT * INTO existing FROM model_gateway_runtime_manifests
    WHERE project_id = p_project_id AND id = p_id;
    IF FOUND THEN
        IF (existing.manifest_hash, existing.schema_version,
            existing.policy_version_id, existing.policy_version_hash,
            existing.source_artifact_hash, existing.option_count,
            existing.prepared_by, existing.prepared_at,
            existing.approved_by, existing.approved_at,
            existing.approval_evidence_reference,
            existing.approval_evidence_sha256, existing.status)
           IS DISTINCT FROM
           (p_manifest_hash, p_schema_version, p_policy_version_id,
            p_policy_version_hash, p_source_artifact_hash, p_option_count,
            p_prepared_by, p_prepared_at, p_approved_by, p_approved_at,
            p_approval_evidence_reference, p_approval_evidence_sha256,
            'approved'::text) THEN
            RAISE EXCEPTION 'runtime manifest identity already has different content'
                USING ERRCODE = '23505';
        END IF;
        RETURN;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM model_gateway_project_policy_versions
        WHERE id = p_policy_version_id AND project_id = p_project_id
          AND policy_hash = p_policy_version_hash
    ) THEN
        RAISE EXCEPTION 'runtime manifest exact project policy is unavailable'
            USING ERRCODE = '23503';
    END IF;
    UPDATE model_gateway_runtime_manifests
    SET status = 'retired', retired_by = p_approved_by,
        retired_at = p_approved_at, record_version = record_version + 1
    WHERE project_id = p_project_id AND status = 'approved';
    INSERT INTO model_gateway_runtime_manifests(
        project_id, id, manifest_hash, schema_version, status,
        policy_version_id, policy_version_hash, source_artifact_hash,
        option_count, prepared_by, prepared_at, approved_by, approved_at,
        approval_evidence_reference, approval_evidence_sha256
    ) VALUES (
        p_project_id, p_id, p_manifest_hash, p_schema_version, 'approved',
        p_policy_version_id, p_policy_version_hash, p_source_artifact_hash,
        p_option_count, p_prepared_by, p_prepared_at, p_approved_by, p_approved_at,
        p_approval_evidence_reference, p_approval_evidence_sha256
    );
END;
$$;

CREATE FUNCTION geo_add_model_gateway_runtime_option(
    p_id uuid,
    p_project_id uuid,
    p_manifest_id uuid,
    p_provider text,
    p_adapter_release_id text,
    p_adapter_release_hash text,
    p_model_release_id text,
    p_model_release_hash text,
    p_secret_reference_id uuid,
    p_microsoft_endpoint text,
    p_microsoft_agent_name text,
    p_microsoft_agent_version text,
    p_microsoft_market text,
    p_microsoft_language text,
    p_provider_config_hash text,
    p_allowed_purposes text[],
    p_allowed_search_modes jsonb,
    p_option_hash text,
    p_created_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE existing model_gateway_runtime_options%ROWTYPE;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'runtime option Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO existing FROM model_gateway_runtime_options
    WHERE project_id = p_project_id AND id = p_id;
    IF FOUND THEN
        IF (existing.manifest_id, existing.provider,
            existing.adapter_release_id, existing.adapter_release_hash,
            existing.model_release_id, existing.model_release_hash,
            existing.secret_reference_id, existing.microsoft_endpoint,
            existing.microsoft_agent_name, existing.microsoft_agent_version,
            existing.microsoft_market, existing.microsoft_language,
            existing.provider_config_hash, existing.allowed_purposes,
            existing.allowed_search_modes, existing.option_hash, existing.created_at)
           IS DISTINCT FROM
           (p_manifest_id, p_provider, p_adapter_release_id,
            p_adapter_release_hash, p_model_release_id, p_model_release_hash,
            p_secret_reference_id, p_microsoft_endpoint,
            p_microsoft_agent_name, p_microsoft_agent_version,
            p_microsoft_market, p_microsoft_language,
            p_provider_config_hash, p_allowed_purposes,
            p_allowed_search_modes, p_option_hash, p_created_at) THEN
            RAISE EXCEPTION 'runtime option identity already has different content'
                USING ERRCODE = '23505';
        END IF;
        RETURN;
    END IF;
    INSERT INTO model_gateway_runtime_options(
        project_id, id, manifest_id, provider,
        adapter_release_id, adapter_release_hash,
        model_release_id, model_release_hash,
        secret_reference_id, secret_purpose,
        microsoft_endpoint, microsoft_agent_name, microsoft_agent_version,
        microsoft_market, microsoft_language,
        provider_config_hash, allowed_purposes, allowed_search_modes,
        option_hash, created_at
    ) VALUES (
        p_project_id, p_id, p_manifest_id, p_provider,
        p_adapter_release_id, p_adapter_release_hash,
        p_model_release_id, p_model_release_hash,
        p_secret_reference_id, 'model_provider.' || p_provider,
        p_microsoft_endpoint, p_microsoft_agent_name, p_microsoft_agent_version,
        p_microsoft_market, p_microsoft_language,
        p_provider_config_hash, p_allowed_purposes, p_allowed_search_modes,
        p_option_hash, p_created_at
    );
END;
$$;

CREATE FUNCTION geo_retire_model_gateway_runtime_manifest(
    p_project_id uuid,
    p_manifest_id uuid,
    p_retired_by uuid,
    p_retired_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'runtime manifest Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'model-runtime-manifest:' || p_project_id::text, 0
    ));
    UPDATE model_gateway_runtime_manifests
    SET status = 'retired', retired_by = p_retired_by,
        retired_at = p_retired_at, record_version = record_version + 1
    WHERE project_id = p_project_id AND id = p_manifest_id AND status = 'approved';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'approved runtime manifest is unavailable'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE FUNCTION geo_resolve_model_gateway_runtime_option(
    p_project_id uuid,
    p_selection_id uuid,
    p_purpose text,
    p_search_mode text
) RETURNS TABLE (
    runtime_manifest_id uuid,
    runtime_manifest_hash text,
    runtime_option_id uuid,
    runtime_option_hash text,
    policy_version_id uuid,
    policy_version_hash text,
    provider text,
    adapter_release_id text,
    adapter_release_hash text,
    model_release_id text,
    model_release_hash text,
    configured_model text,
    secret_reference_id uuid,
    secret_version integer,
    microsoft_endpoint text,
    microsoft_agent_name text,
    microsoft_agent_version text,
    microsoft_market text,
    microsoft_language text,
    provider_config_hash text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'runtime selection Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    SELECT manifest.id, manifest.manifest_hash, option.id, option.option_hash,
           manifest.policy_version_id, manifest.policy_version_hash,
           option.provider, option.adapter_release_id, option.adapter_release_hash,
           option.model_release_id, option.model_release_hash, model.configured_model,
           option.secret_reference_id, secret.version,
           option.microsoft_endpoint, option.microsoft_agent_name,
           option.microsoft_agent_version, option.microsoft_market,
           option.microsoft_language, option.provider_config_hash
    FROM model_gateway_runtime_options AS option
    JOIN model_gateway_runtime_manifests AS manifest
      ON manifest.id = option.manifest_id AND manifest.project_id = option.project_id
    JOIN model_gateway_project_policy_versions AS policy
      ON policy.id = manifest.policy_version_id
     AND policy.project_id = manifest.project_id
     AND policy.policy_hash = manifest.policy_version_hash
    JOIN model_gateway_adapter_releases AS adapter
      ON adapter.provider = option.provider
     AND adapter.adapter_release_id = option.adapter_release_id
     AND adapter.release_hash = option.adapter_release_hash
    JOIN model_gateway_model_releases AS model
      ON model.provider = option.provider
     AND model.adapter_release_id = option.adapter_release_id
     AND model.model_release_id = option.model_release_id
     AND model.release_hash = option.model_release_hash
    JOIN secret_references AS reference
      ON reference.id = option.secret_reference_id
     AND reference.project_id = option.project_id
     AND reference.purpose = option.secret_purpose
    JOIN secret_versions AS secret
      ON secret.reference_id = reference.id
     AND secret.project_id = reference.project_id
     AND secret.purpose = reference.purpose
     AND secret.version = reference.current_version
    WHERE option.project_id = p_project_id AND option.id = p_selection_id
      AND manifest.status = 'approved' AND adapter.state = 'approved'
      AND model.state = 'approved' AND secret.status = 'active'
      AND p_purpose = ANY(option.allowed_purposes)
      AND option.allowed_search_modes @> jsonb_build_array(p_search_mode)
      AND option.provider = ANY(policy.allowed_providers)
      AND option.adapter_release_id = ANY(policy.allowed_adapter_release_ids);
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_reconciliation_command() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE attempt model_gateway_call_attempts%ROWTYPE;
DECLARE terminal model_gateway_terminal_events%ROWTYPE;
DECLARE admission model_gateway_job_admissions%ROWTYPE;
BEGIN
    SELECT * INTO STRICT attempt FROM model_gateway_call_attempts
    WHERE id = NEW.attempt_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT terminal FROM model_gateway_terminal_events
    WHERE id = NEW.terminal_event_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT admission FROM model_gateway_job_admissions
    WHERE project_id = NEW.project_id AND job_id = attempt.job_id;
    IF terminal.attempt_id <> NEW.attempt_id
       OR terminal.job_id <> attempt.job_id
       OR terminal.reconciled_by IS DISTINCT FROM NEW.reconciled_by
       OR terminal.error_classification <> 'manual_reconciliation'
       OR terminal.occurred_at > NEW.recorded_at
       OR terminal.expected_budget_version <> NEW.expected_budget_version
       OR admission.budget_version <> NEW.expected_budget_version + 1 THEN
        RAISE EXCEPTION 'Model Gateway reconciliation command lineage is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_recovery_receipt() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE attempt model_gateway_call_attempts%ROWTYPE;
DECLARE source_job durable_jobs%ROWTYPE;
DECLARE recovery_job durable_jobs%ROWTYPE;
DECLARE artifact record;
BEGIN
    SELECT * INTO STRICT attempt FROM model_gateway_call_attempts
    WHERE id = NEW.model_call_attempt_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT source_job FROM durable_jobs
    WHERE id = NEW.source_model_job_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT recovery_job FROM durable_jobs
    WHERE id = NEW.recovery_job_id AND project_id = NEW.project_id FOR UPDATE;
    SELECT stored.*, bundle.status AS bundle_status,
           bundle.attempt_id AS bundle_attempt_id,
           bundle.job_id AS bundle_job_id, dek.status AS dek_status
    INTO STRICT artifact
    FROM model_gateway_artifacts AS stored
    JOIN model_gateway_artifact_bundles AS bundle
      ON bundle.id = stored.bundle_id AND bundle.project_id = stored.project_id
    JOIN model_gateway_artifact_deks AS dek
      ON dek.key_ref = stored.key_ref AND dek.project_id = stored.project_id
     AND dek.artifact_id = stored.artifact_id
    WHERE stored.project_id = NEW.project_id
      AND stored.artifact_id = NEW.artifact_id AND stored.kind = 'derived';
    IF attempt.job_id <> NEW.source_model_job_id
       OR artifact.bundle_job_id <> NEW.source_model_job_id
       OR (NEW.source_model_job_id <> NEW.recovery_job_id
           AND source_job.parent_job_id IS DISTINCT FROM NEW.recovery_job_id)
       OR recovery_job.status NOT IN ('running', 'finalizing')
       OR recovery_job.cancel_requested_at IS NOT NULL
       OR recovery_job.lease_token IS DISTINCT FROM NEW.lease_token
       OR recovery_job.fencing_generation <> NEW.fencing_generation
       OR recovery_job.lease_expires_at IS NULL
       OR recovery_job.lease_expires_at <= NEW.recovered_at
       OR artifact.bundle_attempt_id <> NEW.model_call_attempt_id
       OR artifact.bundle_status NOT IN ('staged', 'committed')
       OR artifact.manifest_hash <> NEW.manifest_hash
       OR artifact.dek_status <> 'active' THEN
        RAISE EXCEPTION 'Provider artifact recovery receipt lost exact Job or artifact lineage'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_recovery_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM model_gateway_terminal_events AS terminal
        JOIN model_gateway_artifact_bundles AS bundle
          ON bundle.project_id = terminal.project_id
         AND bundle.attempt_id = terminal.attempt_id
        WHERE terminal.project_id = NEW.project_id
          AND terminal.attempt_id = NEW.model_call_attempt_id
          AND terminal.status = 'succeeded'
          AND terminal.output_hash = NEW.expected_output_hash
          AND bundle.status = 'committed'
    ) THEN
        RAISE EXCEPTION 'Provider artifact recovery receipt lacks committed terminal output'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_master_key_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Provider artifact master key versions are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.master_key_version, OLD.algorithm, OLD.canary_nonce,
        OLD.canary_ciphertext, OLD.created_at)
       IS DISTINCT FROM
       (NEW.master_key_version, NEW.algorithm, NEW.canary_nonce,
        NEW.canary_ciphertext, NEW.created_at)
       OR NOT (
           (OLD.status = 'encrypt_decrypt' AND NEW.status = 'decrypt_only'
                AND NEW.retired_at IS NULL)
           OR (OLD.status = 'decrypt_only' AND NEW.status = 'retired'
                AND NEW.retired_at IS NOT NULL)
       ) THEN
        RAISE EXCEPTION 'Provider artifact master key transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'retired' AND EXISTS (
        SELECT 1 FROM model_gateway_artifact_deks
        WHERE master_key_version = NEW.master_key_version AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'Provider artifact master key still wraps an active DEK'
            USING ERRCODE = '23503';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_sync_model_gateway_artifact_master_key_version(
    requested_version integer,
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
DECLARE existing model_gateway_artifact_master_key_versions%ROWTYPE;
DECLARE latest_version integer;
BEGIN
    IF requested_version IS NULL OR requested_version < 1
       OR requested_status NOT IN ('encrypt_decrypt', 'decrypt_only')
       OR requested_algorithm <> 'AES-256-GCM'
       OR octet_length(requested_nonce) <> 12
       OR octet_length(requested_ciphertext) < 17
       OR requested_at IS NULL THEN
        RAISE EXCEPTION 'Provider artifact master key registration is invalid'
            USING ERRCODE = '22023';
    END IF;
    LOCK TABLE model_gateway_artifact_master_key_versions IN SHARE ROW EXCLUSIVE MODE;
    SELECT * INTO existing FROM model_gateway_artifact_master_key_versions
    WHERE master_key_version = requested_version;
    IF FOUND THEN
        IF (existing.status, existing.algorithm, existing.canary_nonce,
            existing.canary_ciphertext)
           IS DISTINCT FROM
           (requested_status, requested_algorithm, requested_nonce,
            requested_ciphertext) THEN
            RAISE EXCEPTION 'Provider artifact master key canary conflicts with storage'
                USING ERRCODE = '23514';
        END IF;
        RETURN;
    END IF;
    SELECT max(master_key_version) INTO latest_version
    FROM model_gateway_artifact_master_key_versions;
    IF requested_version <= coalesce(latest_version, 0) THEN
        RAISE EXCEPTION 'Provider artifact master key versions must increase'
            USING ERRCODE = '23514';
    END IF;
    IF requested_status = 'decrypt_only' AND EXISTS (
        SELECT 1 FROM model_gateway_artifact_master_key_versions
        WHERE status = 'encrypt_decrypt'
    ) THEN
        RAISE EXCEPTION 'Historical Provider artifact keys must precede the active key'
            USING ERRCODE = '23514';
    END IF;
    IF requested_status = 'encrypt_decrypt' THEN
        UPDATE model_gateway_artifact_master_key_versions
        SET status = 'decrypt_only' WHERE status = 'encrypt_decrypt';
    END IF;
    INSERT INTO model_gateway_artifact_master_key_versions(
        master_key_version, status, algorithm, canary_nonce,
        canary_ciphertext, created_at
    ) VALUES (
        requested_version, requested_status, requested_algorithm,
        requested_nonce, requested_ciphertext, requested_at
    );
END;
$$;

CREATE FUNCTION geo_retire_model_gateway_artifact_master_key_version(
    requested_version integer,
    requested_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    UPDATE model_gateway_artifact_master_key_versions
    SET status = 'retired', retired_at = requested_at
    WHERE master_key_version = requested_version AND status = 'decrypt_only';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Provider artifact master key is not decrypt-only'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_bundle_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    attempt record;
    admission record;
BEGIN
    SELECT * INTO STRICT attempt
    FROM model_gateway_call_attempts
    WHERE id = NEW.attempt_id AND project_id = NEW.project_id AND job_id = NEW.job_id;
    SELECT * INTO STRICT admission
    FROM model_gateway_job_admissions
    WHERE project_id = NEW.project_id AND job_id = NEW.job_id;
    IF NEW.status <> 'staged' OR NEW.record_version <> 1
       OR EXISTS (
            SELECT 1 FROM model_gateway_terminal_events terminal
            WHERE terminal.project_id = NEW.project_id
              AND terminal.attempt_id = NEW.attempt_id
       )
       OR attempt.raw_artifact_storage_decision <> 'allowed'
       OR (NEW.provider, NEW.adapter_release_id, NEW.adapter_release_hash,
           NEW.data_policy_hash, NEW.storage_decision, NEW.cache_decision,
           NEW.display_decision, NEW.redistribution_decision,
           NEW.usage_purpose, NEW.audience, NEW.retention_days)
          IS DISTINCT FROM
          (attempt.provider, attempt.adapter_release_id, attempt.adapter_release_hash,
           attempt.raw_artifact_policy_hash, attempt.raw_artifact_storage_decision,
           attempt.raw_artifact_cache_decision, attempt.raw_artifact_display_decision,
           attempt.raw_artifact_redistribution_decision,
           attempt.purpose, attempt.usage_audience, attempt.raw_artifact_retention_days)
       OR admission.raw_artifact_storage_decision <> 'allowed' THEN
        RAISE EXCEPTION 'Model Gateway artifact bundle violates frozen Attempt policy'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_bundle_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       OR (OLD.id, OLD.project_id, OLD.job_id, OLD.attempt_id,
           OLD.provider, OLD.adapter_release_id, OLD.adapter_release_hash,
           OLD.data_policy_hash, OLD.storage_decision, OLD.cache_decision,
           OLD.display_decision, OLD.redistribution_decision,
           OLD.usage_purpose, OLD.audience, OLD.retention_days,
           OLD.staged_at, OLD.expires_at)
          IS DISTINCT FROM
          (NEW.id, NEW.project_id, NEW.job_id, NEW.attempt_id,
           NEW.provider, NEW.adapter_release_id, NEW.adapter_release_hash,
           NEW.data_policy_hash, NEW.storage_decision, NEW.cache_decision,
           NEW.display_decision, NEW.redistribution_decision,
           NEW.usage_purpose, NEW.audience, NEW.retention_days,
           NEW.staged_at, NEW.expires_at)
       OR NEW.record_version <> OLD.record_version + 1
       OR NOT (
            (OLD.status = 'staged' AND NEW.status = 'committed'
                AND NEW.committed_at IS NOT NULL AND NEW.terminal_event_id IS NOT NULL)
            OR (OLD.status = 'staged' AND NEW.status = 'orphaned'
                AND NEW.orphaned_at IS NOT NULL)
            OR (OLD.status IN ('committed', 'orphaned')
                AND NEW.status = 'deletion_pending'
                AND NEW.deletion_pending_at IS NOT NULL)
            OR (OLD.status IN ('deletion_pending', 'orphaned')
                AND NEW.status = 'deleted' AND NEW.deleted_at IS NOT NULL)
       ) THEN
        RAISE EXCEPTION 'Model Gateway artifact bundle transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_dek_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       OR OLD.status <> 'active' OR NEW.status <> 'destroyed'
       OR (OLD.key_ref, OLD.project_id, OLD.artifact_id, OLD.master_key_version,
           OLD.algorithm, OLD.created_at)
          IS DISTINCT FROM
          (NEW.key_ref, NEW.project_id, NEW.artifact_id, NEW.master_key_version,
           NEW.algorithm, NEW.created_at) THEN
        RAISE EXCEPTION 'Model Gateway artifact DEK transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE bundle record;
DECLARE dek record;
BEGIN
    SELECT * INTO STRICT bundle
    FROM model_gateway_artifact_bundles
    WHERE id = NEW.bundle_id AND project_id = NEW.project_id;
    SELECT * INTO STRICT dek
    FROM model_gateway_artifact_deks
    WHERE key_ref = NEW.key_ref AND project_id = NEW.project_id
      AND artifact_id = NEW.artifact_id;
    IF bundle.status <> 'staged' OR dek.status <> 'active'
       OR NEW.expires_at IS DISTINCT FROM bundle.expires_at THEN
        RAISE EXCEPTION 'Model Gateway artifact object violates staged bundle lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Model Gateway artifact object metadata is immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_tombstone_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Model Gateway artifact tombstones are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_artifact_outbox_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       OR (OLD.id, OLD.project_id, OLD.bundle_id, OLD.reason, OLD.created_at)
          IS DISTINCT FROM
          (NEW.id, NEW.project_id, NEW.bundle_id, NEW.reason, NEW.created_at)
       OR NOT (
            (OLD.status IN ('pending', 'processing') AND NEW.status = 'processing'
                AND NEW.attempt_count = OLD.attempt_count + 1
                AND NEW.fencing_generation = OLD.fencing_generation + 1)
            OR (OLD.status = 'processing' AND NEW.status IN ('pending', 'failed')
                AND NEW.attempt_count = OLD.attempt_count
                AND NEW.fencing_generation = OLD.fencing_generation)
            OR (OLD.status = 'processing' AND NEW.status = 'completed'
                AND NEW.attempt_count = OLD.attempt_count
                AND NEW.fencing_generation = OLD.fencing_generation)
       ) THEN
        RAISE EXCEPTION 'Model Gateway artifact deletion outbox transition is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_destroy_model_gateway_unstaged_artifact_deks(
    p_now timestamptz,
    p_grace_seconds integer
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE changed integer := 0;
DECLARE candidate record;
BEGIN
    IF p_now IS NULL OR p_grace_seconds NOT BETWEEN 1 AND 604800 THEN
        RAISE EXCEPTION 'invalid Model Gateway pre-stage DEK sweep input'
            USING ERRCODE = '22023';
    END IF;
    FOR candidate IN
        SELECT dek.key_ref
        FROM model_gateway_artifact_deks AS dek
        WHERE dek.status = 'active'
          AND dek.created_at <= p_now - make_interval(secs => p_grace_seconds)
          AND NOT EXISTS (
                SELECT 1 FROM model_gateway_artifacts AS artifact
                WHERE artifact.project_id = dek.project_id
                  AND artifact.key_ref = dek.key_ref
                  AND artifact.artifact_id = dek.artifact_id
          )
        ORDER BY dek.created_at, dek.key_ref
        FOR UPDATE OF dek SKIP LOCKED
    LOOP
        UPDATE model_gateway_artifact_deks AS dek
        SET status = 'destroyed', ciphertext = NULL, data_nonce = NULL,
            wrapped_data_key = NULL, wrap_nonce = NULL, destroyed_at = p_now
        WHERE dek.key_ref = candidate.key_ref
          AND dek.status = 'active'
          AND NOT EXISTS (
                SELECT 1 FROM model_gateway_artifacts AS artifact
                WHERE artifact.project_id = dek.project_id
                  AND artifact.key_ref = dek.key_ref
                  AND artifact.artifact_id = dek.artifact_id
          );
        IF FOUND THEN
            changed := changed + 1;
        END IF;
    END LOOP;
    RETURN changed;
END;
$$;

CREATE FUNCTION geo_stage_model_gateway_artifact_expiry(
    p_now timestamptz,
    p_staged_grace_seconds integer
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE changed integer := 0;
DECLARE bundle record;
BEGIN
    IF p_now IS NULL OR p_staged_grace_seconds NOT BETWEEN 1 AND 604800 THEN
        RAISE EXCEPTION 'invalid Model Gateway artifact expiry sweep input'
            USING ERRCODE = '22023';
    END IF;
    FOR bundle IN
        SELECT * FROM model_gateway_artifact_bundles
        WHERE (status = 'committed' AND expires_at IS NOT NULL AND expires_at <= p_now)
           OR (status = 'staged'
               AND staged_at <= p_now - make_interval(secs => p_staged_grace_seconds))
        FOR UPDATE SKIP LOCKED
    LOOP
        IF bundle.status = 'staged' THEN
            UPDATE model_gateway_artifact_bundles
            SET status = 'orphaned', orphaned_at = p_now,
                record_version = record_version + 1
            WHERE id = bundle.id;
        ELSE
            UPDATE model_gateway_artifact_bundles
            SET status = 'deletion_pending', deletion_pending_at = p_now,
                record_version = record_version + 1
            WHERE id = bundle.id;
        END IF;
        INSERT INTO model_gateway_artifact_deletion_outbox(
            id, project_id, bundle_id, reason, status, available_at
        ) VALUES (
            gen_random_uuid(), bundle.project_id, bundle.id,
            CASE WHEN bundle.status = 'staged' THEN 'orphaned' ELSE 'retention_expired' END,
            'pending', p_now
        ) ON CONFLICT (bundle_id) WHERE status IN ('pending', 'processing') DO NOTHING;
        changed := changed + 1;
    END LOOP;
    RETURN changed;
END;
$$;

CREATE FUNCTION geo_claim_model_gateway_artifact_deletions(
    p_limit integer,
    p_lease_seconds integer
) RETURNS TABLE (
    id uuid, project_id uuid, bundle_id uuid, reason text,
    lease_token uuid, fencing_generation bigint
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF p_limit NOT BETWEEN 1 AND 100 OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'invalid Model Gateway artifact deletion claim input'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    WITH candidates AS (
        SELECT item.id
        FROM model_gateway_artifact_deletion_outbox item
        WHERE (item.status = 'pending' AND item.available_at <= clock_timestamp())
           OR (item.status = 'processing' AND item.lease_expires_at <= clock_timestamp())
        ORDER BY item.available_at, item.id
        FOR UPDATE SKIP LOCKED
        LIMIT p_limit
    )
    UPDATE model_gateway_artifact_deletion_outbox item
    SET status = 'processing', lease_token = gen_random_uuid(),
        lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
        attempt_count = item.attempt_count + 1,
        fencing_generation = item.fencing_generation + 1,
        last_error_code = NULL
    FROM candidates
    WHERE item.id = candidates.id
    RETURNING item.id, item.project_id, item.bundle_id, item.reason,
              item.lease_token, item.fencing_generation;
END;
$$;

CREATE FUNCTION geo_complete_model_gateway_artifact_deletion(
    p_project_id uuid,
    p_outbox_id uuid,
    p_lease_token uuid,
    p_fencing_generation bigint,
    p_deletion_receipt_hash text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE item record;
DECLARE bundle record;
DECLARE raw_hash text;
DECLARE derived_hash text;
BEGIN
    IF p_deletion_receipt_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid Model Gateway deletion receipt hash'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT item
    FROM model_gateway_artifact_deletion_outbox
    WHERE id = p_outbox_id AND project_id = p_project_id FOR UPDATE;
    SELECT * INTO STRICT bundle FROM model_gateway_artifact_bundles
    WHERE id = item.bundle_id AND project_id = p_project_id FOR UPDATE;
    IF item.status <> 'processing' OR item.lease_token <> p_lease_token
       OR item.fencing_generation <> p_fencing_generation
       OR item.lease_expires_at <= clock_timestamp()
       OR bundle.status NOT IN ('deletion_pending', 'orphaned') THEN
        RAISE EXCEPTION 'Model Gateway artifact deletion lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    SELECT manifest_hash INTO STRICT raw_hash FROM model_gateway_artifacts
    WHERE bundle_id = bundle.id AND kind = 'raw';
    SELECT manifest_hash INTO STRICT derived_hash FROM model_gateway_artifacts
    WHERE bundle_id = bundle.id AND kind = 'derived';
    UPDATE model_gateway_artifact_deks dek
    SET status = 'destroyed', ciphertext = NULL, data_nonce = NULL,
        wrapped_data_key = NULL, wrap_nonce = NULL, destroyed_at = clock_timestamp()
    WHERE dek.project_id = p_project_id
      AND EXISTS (
          SELECT 1 FROM model_gateway_artifacts artifact
          WHERE artifact.bundle_id = bundle.id AND artifact.key_ref = dek.key_ref
      );
    DELETE FROM model_gateway_artifacts WHERE bundle_id = bundle.id;
    INSERT INTO model_gateway_artifact_tombstones(
        id, project_id, bundle_id, reason, raw_manifest_hash,
        derived_manifest_hash, deletion_receipt_hash, deleted_at
    ) VALUES (
        gen_random_uuid(), p_project_id, bundle.id, item.reason,
        raw_hash, derived_hash, p_deletion_receipt_hash, clock_timestamp()
    );
    UPDATE model_gateway_artifact_bundles
    SET status = 'deleted', deletion_pending_at = coalesce(
            deletion_pending_at, clock_timestamp()
        ), deleted_at = clock_timestamp(), record_version = record_version + 1
    WHERE id = bundle.id;
    UPDATE model_gateway_artifact_deletion_outbox
    SET status = 'completed', lease_token = NULL, lease_expires_at = NULL,
        completed_at = clock_timestamp()
    WHERE id = item.id;
END;
$$;

CREATE FUNCTION geo_fail_model_gateway_artifact_deletion(
    p_project_id uuid,
    p_outbox_id uuid,
    p_lease_token uuid,
    p_fencing_generation bigint,
    p_error_code text,
    p_retry_seconds integer
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE next_status text;
BEGIN
    IF p_error_code !~ '^[a-z][a-z0-9_]{0,62}$'
       OR p_retry_seconds NOT BETWEEN 1 AND 86400 THEN
        RAISE EXCEPTION 'invalid Model Gateway artifact deletion failure input'
            USING ERRCODE = '22023';
    END IF;
    SELECT CASE WHEN attempt_count >= 10 THEN 'failed' ELSE 'pending' END
    INTO STRICT next_status
    FROM model_gateway_artifact_deletion_outbox
    WHERE id = p_outbox_id AND project_id = p_project_id
      AND status = 'processing' AND lease_token = p_lease_token
      AND fencing_generation = p_fencing_generation
      AND lease_expires_at > clock_timestamp()
    FOR UPDATE;
    UPDATE model_gateway_artifact_deletion_outbox
    SET status = next_status, lease_token = NULL, lease_expires_at = NULL,
        last_error_code = p_error_code,
        available_at = clock_timestamp() + make_interval(secs => p_retry_seconds)
    WHERE id = p_outbox_id;
    RETURN next_status;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_adapter_release() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected_data_policy_hash text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Model Gateway Adapter Releases are immutable'
            USING ERRCODE = '55000';
    END IF;
    expected_data_policy_hash := encode(digest(convert_to(
        geo_jsonb_canonical_text(jsonb_build_object(
            'storage', NEW.data_storage_decision,
            'cache', NEW.data_cache_decision,
            'display', NEW.data_display_decision,
            'redistribution', NEW.data_redistribution_decision,
            'retention_days', NEW.data_policy_retention_days,
            'terms_reference', NEW.terms_reference,
            'terms_sha256', NEW.terms_sha256
        )), 'UTF8'
    ), 'sha256'), 'hex');
    IF NEW.data_policy_hash <> expected_data_policy_hash THEN
        RAISE EXCEPTION 'Model Gateway Adapter Release data-policy hash is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_model_release() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Model Gateway Model Releases are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF cardinality(NEW.allowed_reported_models) > 0 THEN
        PERFORM geo_assert_model_gateway_text_array(
            NEW.allowed_reported_models, 'allowed reported models'
        );
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_policy_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous_version integer;
BEGIN
    PERFORM geo_assert_model_gateway_text_array(NEW.allowed_providers, 'allowed providers');
    PERFORM geo_assert_model_gateway_text_array(
        NEW.allowed_adapter_release_ids, 'allowed Adapter Releases'
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended('model-project-policy:' || NEW.project_id, 0)
    );
    IF NEW.version = 1 THEN
        IF NEW.previous_version_id IS NOT NULL THEN
            RAISE EXCEPTION 'initial Model Gateway project policy cannot have a predecessor'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT version INTO STRICT previous_version
        FROM model_gateway_project_policy_versions
        WHERE id = NEW.previous_version_id AND project_id = NEW.project_id;
        IF NEW.version <> previous_version + 1 THEN
            RAISE EXCEPTION 'Model Gateway project policy versions must be contiguous'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_job_admission_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    durable record;
    policy record;
    runtime_manifest record;
    runtime_option record;
    adapter record;
    model record;
    provider_secret record;
    binding record;
    state_record record;
    release_record record;
BEGIN
    SELECT kind, status, lease_token, lease_expires_at,
           fencing_generation, cancel_requested_at
    INTO STRICT durable
    FROM durable_jobs
    WHERE id = NEW.job_id AND project_id = NEW.project_id;
    IF durable.kind <> NEW.job_kind
       OR durable.status <> 'running'
       OR durable.lease_token IS NULL
       OR durable.lease_token IS DISTINCT FROM NEW.lease_token
       OR durable.lease_expires_at IS NULL
       OR durable.lease_expires_at < NEW.admitted_at
       OR durable.fencing_generation <> NEW.fencing_generation
       OR durable.cancel_requested_at IS NOT NULL THEN
        RAISE EXCEPTION 'Model Gateway admission requires a matching active Durable Job'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO STRICT runtime_manifest
    FROM model_gateway_runtime_manifests
    WHERE id = NEW.runtime_manifest_id
      AND project_id = NEW.project_id
      AND manifest_hash = NEW.runtime_manifest_hash;
    SELECT * INTO STRICT runtime_option
    FROM model_gateway_runtime_options
    WHERE id = NEW.runtime_option_id
      AND project_id = NEW.project_id
      AND manifest_id = NEW.runtime_manifest_id
      AND option_hash = NEW.runtime_option_hash;
    IF runtime_manifest.status <> 'approved'
       OR runtime_manifest.policy_version_id <> NEW.policy_version_id
       OR runtime_manifest.policy_version_hash <> NEW.policy_version_hash
       OR runtime_option.provider <> NEW.provider
       OR runtime_option.adapter_release_id <> NEW.adapter_release_id
       OR runtime_option.adapter_release_hash <> NEW.adapter_release_hash
       OR runtime_option.model_release_id <> NEW.model_release_id
       OR runtime_option.model_release_hash <> NEW.model_release_hash
       OR runtime_option.secret_reference_id <> NEW.provider_secret_reference_id
       OR runtime_option.secret_purpose <> 'model_provider.' || NEW.provider
       OR NEW.purpose <> ALL(runtime_option.allowed_purposes) THEN
        RAISE EXCEPTION 'Model Gateway admission differs from the current approved runtime option'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO STRICT policy
    FROM model_gateway_project_policy_versions
    WHERE id = NEW.policy_version_id
      AND project_id = NEW.project_id
      AND policy_hash = NEW.policy_version_hash;
    IF NEW.provider <> ALL(policy.allowed_providers)
       OR NEW.adapter_release_id <> ALL(policy.allowed_adapter_release_ids)
       OR NEW.maximum_paid_calls > policy.maximum_paid_calls_default
       OR NEW.maximum_concurrent_calls > policy.maximum_concurrent_calls THEN
        RAISE EXCEPTION 'Model Gateway admission exceeds frozen project policy'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO STRICT adapter
    FROM model_gateway_adapter_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND release_hash = NEW.adapter_release_hash;
    IF adapter.state <> 'approved'
       OR (NOT policy.external_training_allowed AND adapter.external_training_allowed)
       OR (policy.structured_output_required AND NOT adapter.structured_output)
       OR NEW.raw_artifact_policy_hash <> adapter.data_policy_hash
       OR NEW.raw_artifact_storage_decision <> adapter.data_storage_decision
       OR NEW.raw_artifact_cache_decision <> adapter.data_cache_decision
       OR NEW.raw_artifact_display_decision <> adapter.data_display_decision
       OR NEW.raw_artifact_redistribution_decision <> adapter.data_redistribution_decision
       OR NEW.raw_artifact_retention_days IS DISTINCT FROM adapter.data_policy_retention_days THEN
        RAISE EXCEPTION 'Model Gateway Adapter Release violates frozen project policy'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO STRICT model
    FROM model_gateway_model_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND model_release_id = NEW.model_release_id
      AND release_hash = NEW.model_release_hash;
    IF model.state <> 'approved' OR model.adapter_release_hash <> NEW.adapter_release_hash THEN
        RAISE EXCEPTION 'Model Gateway Model Release is not approved for the exact Adapter Release'
            USING ERRCODE = '42501';
    END IF;

    SELECT version.status, version.project_id, version.purpose,
           reference.current_version
    INTO STRICT provider_secret
    FROM secret_versions AS version
    JOIN secret_references AS reference
      ON reference.id = version.reference_id
     AND reference.project_id = version.project_id
     AND reference.purpose = version.purpose
    WHERE version.reference_id = NEW.provider_secret_reference_id
      AND version.version = NEW.provider_secret_version;
    IF provider_secret.project_id <> NEW.project_id
       OR provider_secret.purpose <> 'model_provider.' || NEW.provider
       OR provider_secret.status <> 'active'
       OR provider_secret.current_version <> NEW.provider_secret_version
       OR NEW.provider_secret_handle_hash <> geo_model_gateway_secret_handle_hash(
            NEW.provider_secret_reference_id, NEW.project_id,
            provider_secret.purpose, NEW.provider_secret_version
       ) THEN
        RAISE EXCEPTION 'Model Gateway admission requires the current active Provider Secret handle'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO STRICT state_record
    FROM prompt_program_release_states
    WHERE id = NEW.prompt_frozen_state_id
      AND project_id = NEW.project_id
      AND release_id = NEW.prompt_release_id
      AND release_hash = NEW.prompt_release_hash
      AND version = NEW.prompt_state_version;
    SELECT * INTO STRICT release_record
    FROM prompt_program_releases
    WHERE id = NEW.prompt_release_id AND project_id = NEW.project_id
      AND release_hash = NEW.prompt_release_hash;
    IF NEW.output_schema_hash <> release_record.output_schema_hash
       OR NEW.application_output_schema_hash
            <> release_record.application_output_schema_hash THEN
        RAISE EXCEPTION 'Model Gateway admission Schema hashes differ from Prompt Release'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.admission_mode = 'runtime_frozen' THEN
        SELECT * INTO STRICT binding
        FROM prompt_program_bindings
        WHERE id = NEW.prompt_binding_id AND project_id = NEW.project_id;
        IF binding.purpose <> NEW.purpose
           OR binding.release_id <> NEW.prompt_release_id
           OR binding.release_hash <> NEW.prompt_release_hash
           OR binding.frozen_state_id <> NEW.prompt_frozen_state_id
           OR state_record.status <> 'frozen' THEN
            RAISE EXCEPTION 'Model Gateway admission requires the exact frozen Prompt binding'
                USING ERRCODE = '23514';
        END IF;
    ELSIF state_record.status <> 'draft'
       OR release_record.test_set_hash <> NEW.prompt_test_set_hash
       OR EXISTS (
            SELECT 1 FROM prompt_program_release_states newer
            WHERE newer.project_id = NEW.project_id
              AND newer.release_id = NEW.prompt_release_id
              AND newer.version > NEW.prompt_state_version
       ) THEN
        RAISE EXCEPTION 'Model Gateway Prompt test admission requires current draft lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_job_budget_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    durable record;
    latest record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Model Gateway Job admission history cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.job_id <> NEW.job_id OR OLD.project_id <> NEW.project_id
       OR OLD.job_kind <> NEW.job_kind
       OR OLD.runtime_manifest_id <> NEW.runtime_manifest_id
       OR OLD.runtime_manifest_hash <> NEW.runtime_manifest_hash
       OR OLD.runtime_option_id <> NEW.runtime_option_id
       OR OLD.runtime_option_hash <> NEW.runtime_option_hash
       OR OLD.admission_mode <> NEW.admission_mode
       OR OLD.policy_version_id <> NEW.policy_version_id
       OR OLD.policy_version_hash <> NEW.policy_version_hash
       OR OLD.purpose <> NEW.purpose OR OLD.usage_audience <> NEW.usage_audience
       OR OLD.provider <> NEW.provider
       OR OLD.adapter_release_id <> NEW.adapter_release_id
       OR OLD.adapter_release_hash <> NEW.adapter_release_hash
       OR OLD.model_release_id <> NEW.model_release_id
       OR OLD.model_release_hash <> NEW.model_release_hash
       OR OLD.provider_secret_reference_id <> NEW.provider_secret_reference_id
       OR OLD.provider_secret_version <> NEW.provider_secret_version
       OR OLD.provider_secret_handle_hash <> NEW.provider_secret_handle_hash
       OR OLD.prompt_binding_id <> NEW.prompt_binding_id
       OR OLD.prompt_release_id <> NEW.prompt_release_id
       OR OLD.prompt_release_hash <> NEW.prompt_release_hash
       OR OLD.prompt_frozen_state_id <> NEW.prompt_frozen_state_id
       OR OLD.prompt_state_version <> NEW.prompt_state_version
       OR OLD.prompt_test_set_hash IS DISTINCT FROM NEW.prompt_test_set_hash
       OR OLD.prompt_bundle_hash <> NEW.prompt_bundle_hash
       OR OLD.output_schema_hash <> NEW.output_schema_hash
       OR OLD.application_output_schema_hash <> NEW.application_output_schema_hash
       OR OLD.raw_artifact_policy_hash <> NEW.raw_artifact_policy_hash
       OR OLD.raw_artifact_storage_decision <> NEW.raw_artifact_storage_decision
       OR OLD.raw_artifact_cache_decision <> NEW.raw_artifact_cache_decision
       OR OLD.raw_artifact_display_decision <> NEW.raw_artifact_display_decision
       OR OLD.raw_artifact_redistribution_decision
            <> NEW.raw_artifact_redistribution_decision
       OR OLD.raw_artifact_retention_days IS DISTINCT FROM NEW.raw_artifact_retention_days
       OR OLD.maximum_paid_calls <> NEW.maximum_paid_calls
       OR OLD.maximum_concurrent_calls <> NEW.maximum_concurrent_calls
       OR OLD.admitted_by <> NEW.admitted_by OR OLD.admitted_at <> NEW.admitted_at
       THEN
        RAISE EXCEPTION 'Model Gateway Job budget CAS transition is invalid'
            USING ERRCODE = '40001';
    END IF;
    IF (NEW.job_version, NEW.lease_token, NEW.fencing_generation)
       IS DISTINCT FROM
       (OLD.job_version, OLD.lease_token, OLD.fencing_generation) THEN
        SELECT status, lease_token, lease_expires_at, fencing_generation,
               cancel_requested_at
        INTO STRICT durable
        FROM durable_jobs
        WHERE id = NEW.job_id AND project_id = NEW.project_id;
        SELECT attempt.id, terminal.status, terminal.error_retryable
        INTO STRICT latest
        FROM model_gateway_call_attempts AS attempt
        JOIN model_gateway_terminal_events AS terminal
          ON terminal.attempt_id = attempt.id
         AND terminal.project_id = attempt.project_id
         AND terminal.job_id = attempt.job_id
        WHERE attempt.project_id = NEW.project_id AND attempt.job_id = NEW.job_id
        ORDER BY attempt.attempt_number DESC
        LIMIT 1;
        IF NEW.job_version < OLD.job_version
           OR NEW.lease_token = OLD.lease_token
           OR NEW.fencing_generation <= OLD.fencing_generation
           OR durable.status <> 'running'
           OR durable.cancel_requested_at IS NOT NULL
           OR durable.lease_token IS DISTINCT FROM NEW.lease_token
           OR durable.fencing_generation <> NEW.fencing_generation
           OR durable.lease_expires_at IS NULL
           OR durable.lease_expires_at <= clock_timestamp()
           OR latest.status <> 'failed'
           OR latest.error_retryable IS NOT TRUE
           OR NEW.reserved_calls <> 0
           OR (NEW.paid_calls, NEW.reserved_calls, NEW.budget_version,
               NEW.next_attempt_number)
              IS DISTINCT FROM
              (OLD.paid_calls, OLD.reserved_calls, OLD.budget_version,
               OLD.next_attempt_number) THEN
            RAISE EXCEPTION 'Model Gateway Job lease refresh is invalid'
                USING ERRCODE = '40001';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.budget_version <> OLD.budget_version + 1
       OR NOT (
            (NEW.paid_calls = OLD.paid_calls
                AND NEW.reserved_calls = OLD.reserved_calls + 1
                AND NEW.next_attempt_number = OLD.next_attempt_number + 1)
            OR (NEW.paid_calls IN (OLD.paid_calls, OLD.paid_calls + 1)
                AND NEW.reserved_calls = OLD.reserved_calls - 1
                AND NEW.next_attempt_number = OLD.next_attempt_number)
       ) THEN
        RAISE EXCEPTION 'Model Gateway Job budget CAS transition is invalid'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_refresh_model_gateway_job_admission_lease(
    p_project_id uuid,
    p_job_id uuid,
    p_job_version integer,
    p_lease_token uuid,
    p_fencing_generation bigint,
    p_refreshed_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    admission model_gateway_job_admissions%ROWTYPE;
    durable record;
    latest record;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Model Gateway lease refresh Project is outside caller scope'
            USING ERRCODE = '42501';
    END IF;
    IF p_job_id IS NULL OR p_job_version < 1 OR p_lease_token IS NULL
       OR p_fencing_generation < 1 OR p_refreshed_at IS NULL
       OR p_refreshed_at > clock_timestamp() + interval '5 minutes' THEN
        RAISE EXCEPTION 'invalid Model Gateway lease refresh input'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT admission
    FROM model_gateway_job_admissions
    WHERE project_id = p_project_id AND job_id = p_job_id
    FOR UPDATE;
    SELECT status, lease_token, lease_expires_at, fencing_generation,
           cancel_requested_at
    INTO STRICT durable
    FROM durable_jobs
    WHERE project_id = p_project_id AND id = p_job_id;
    SELECT attempt.id, terminal.status, terminal.error_retryable
    INTO STRICT latest
    FROM model_gateway_call_attempts AS attempt
    JOIN model_gateway_terminal_events AS terminal
      ON terminal.attempt_id = attempt.id
     AND terminal.project_id = attempt.project_id
     AND terminal.job_id = attempt.job_id
    WHERE attempt.project_id = p_project_id AND attempt.job_id = p_job_id
    ORDER BY attempt.attempt_number DESC
    LIMIT 1;
    IF admission.reserved_calls <> 0
       OR p_job_version < admission.job_version
       OR p_lease_token = admission.lease_token
       OR p_fencing_generation <= admission.fencing_generation
       OR durable.status <> 'running'
       OR durable.cancel_requested_at IS NOT NULL
       OR durable.lease_token IS DISTINCT FROM p_lease_token
       OR durable.fencing_generation <> p_fencing_generation
       OR durable.lease_expires_at IS NULL
       OR durable.lease_expires_at <= p_refreshed_at
       OR latest.status <> 'failed'
       OR latest.error_retryable IS NOT TRUE THEN
        RAISE EXCEPTION 'Model Gateway lease refresh lost retry, lease, or fence eligibility'
            USING ERRCODE = '40001';
    END IF;
    UPDATE model_gateway_job_admissions
    SET job_version = p_job_version,
        lease_token = p_lease_token,
        fencing_generation = p_fencing_generation
    WHERE project_id = p_project_id AND job_id = p_job_id;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_attempt_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    admission record;
    durable record;
    runtime_option record;
    parent record;
    parent_terminal record;
    adapter record;
    model record;
    provider_secret record;
BEGIN
    SELECT * INTO STRICT admission
    FROM model_gateway_job_admissions
    WHERE project_id = NEW.project_id AND job_id = NEW.job_id
    FOR UPDATE;
    SELECT status, lease_token, lease_expires_at, fencing_generation, cancel_requested_at
    INTO STRICT durable
    FROM durable_jobs
    WHERE project_id = NEW.project_id AND id = NEW.job_id;
    IF admission.job_version <> NEW.job_version
       OR admission.lease_token IS DISTINCT FROM NEW.lease_token
       OR admission.fencing_generation <> NEW.fencing_generation
       OR admission.runtime_manifest_id <> NEW.runtime_manifest_id
       OR admission.runtime_manifest_hash <> NEW.runtime_manifest_hash
       OR admission.runtime_option_id <> NEW.runtime_option_id
       OR admission.runtime_option_hash <> NEW.runtime_option_hash
       OR admission.admission_mode <> NEW.admission_mode
       OR admission.budget_version <> NEW.expected_budget_version
       OR admission.next_attempt_number <> NEW.attempt_number
       OR durable.status <> 'running'
       OR durable.cancel_requested_at IS NOT NULL
       OR durable.lease_token IS DISTINCT FROM NEW.lease_token
       OR durable.fencing_generation <> NEW.fencing_generation
       OR durable.lease_expires_at IS NULL OR durable.lease_expires_at < NEW.reserved_at THEN
        RAISE EXCEPTION 'Model Gateway reservation lost Job, lease, fencing, or budget CAS'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO STRICT runtime_option
    FROM model_gateway_runtime_options
    WHERE id = NEW.runtime_option_id
      AND project_id = NEW.project_id
      AND manifest_id = NEW.runtime_manifest_id
      AND option_hash = NEW.runtime_option_hash;
    IF runtime_option.provider <> NEW.provider
       OR runtime_option.adapter_release_id <> NEW.adapter_release_id
       OR runtime_option.adapter_release_hash <> NEW.adapter_release_hash
       OR runtime_option.model_release_id <> NEW.model_release_id
       OR runtime_option.model_release_hash <> NEW.model_release_hash
       OR runtime_option.secret_reference_id <> NEW.provider_secret_reference_id
       OR NEW.purpose <> ALL(runtime_option.allowed_purposes)
       OR NOT runtime_option.allowed_search_modes @> jsonb_build_array(NEW.search_mode) THEN
        RAISE EXCEPTION 'Model Gateway Attempt differs from its frozen runtime option'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.provider = 'microsoft'
       AND NEW.expected_location_control = 'market_language'
       AND (NEW.expected_location_locale IS DISTINCT FROM runtime_option.microsoft_market
            OR NEW.expected_location_language IS DISTINCT FROM
               runtime_option.microsoft_language) THEN
        RAISE EXCEPTION 'Microsoft Attempt location differs from the frozen market/language option'
            USING ERRCODE = '23514';
    END IF;
    IF admission.paid_calls + admission.reserved_calls >= admission.maximum_paid_calls
       OR admission.reserved_calls >= admission.maximum_concurrent_calls THEN
        RAISE EXCEPTION 'Model Gateway paid-call or concurrency budget is exhausted'
            USING ERRCODE = '53000';
    END IF;
    IF admission.policy_version_id <> NEW.policy_version_id
       OR admission.policy_version_hash <> NEW.policy_version_hash
       OR admission.purpose <> NEW.purpose
       OR admission.usage_audience <> NEW.usage_audience
       OR admission.provider <> NEW.provider
       OR admission.adapter_release_id <> NEW.adapter_release_id
       OR admission.adapter_release_hash <> NEW.adapter_release_hash
       OR admission.model_release_id <> NEW.model_release_id
       OR admission.model_release_hash <> NEW.model_release_hash
       OR admission.provider_secret_reference_id <> NEW.provider_secret_reference_id
       OR admission.provider_secret_version <> NEW.provider_secret_version
       OR admission.provider_secret_handle_hash <> NEW.provider_secret_handle_hash
       OR admission.prompt_binding_id <> NEW.prompt_binding_id
       OR admission.prompt_release_id <> NEW.prompt_release_id
       OR admission.prompt_release_hash <> NEW.prompt_release_hash
       OR admission.prompt_frozen_state_id <> NEW.prompt_state_id
       OR admission.prompt_state_version <> NEW.prompt_state_version
       OR admission.prompt_test_set_hash IS DISTINCT FROM NEW.prompt_test_set_hash
       OR admission.prompt_bundle_hash <> NEW.prompt_bundle_hash
       OR admission.output_schema_hash <> NEW.output_schema_hash
       OR admission.application_output_schema_hash
            <> NEW.application_output_schema_hash
       OR admission.raw_artifact_policy_hash <> NEW.raw_artifact_policy_hash
       OR admission.raw_artifact_storage_decision <> NEW.raw_artifact_storage_decision
       OR admission.raw_artifact_cache_decision <> NEW.raw_artifact_cache_decision
       OR admission.raw_artifact_display_decision <> NEW.raw_artifact_display_decision
       OR admission.raw_artifact_redistribution_decision
            <> NEW.raw_artifact_redistribution_decision
       OR admission.raw_artifact_retention_days IS DISTINCT FROM NEW.raw_artifact_retention_days THEN
        RAISE EXCEPTION 'Model Gateway reservation lineage differs from Job admission'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.admission_mode = 'prompt_release_test' AND NOT EXISTS (
        SELECT 1 FROM prompt_program_test_run_tasks task
        WHERE task.project_id = NEW.project_id AND task.job_id = NEW.job_id
          AND task.release_id = NEW.prompt_release_id
          AND task.release_hash = NEW.prompt_release_hash
          AND task.expected_state_id = NEW.prompt_state_id
          AND task.expected_state_version = NEW.prompt_state_version
          AND task.test_set_hash = NEW.prompt_test_set_hash
    ) THEN
        RAISE EXCEPTION 'Model Gateway Prompt test Attempt lacks frozen test task lineage'
            USING ERRCODE = '23514';
    END IF;

    SELECT status, project_id, purpose INTO STRICT provider_secret
    FROM secret_versions
    WHERE reference_id = NEW.provider_secret_reference_id
      AND version = NEW.provider_secret_version;
    IF provider_secret.project_id <> NEW.project_id
       OR provider_secret.purpose <> 'model_provider.' || NEW.provider
       OR provider_secret.status NOT IN ('active', 'superseded')
       OR NEW.provider_secret_handle_hash <> geo_model_gateway_secret_handle_hash(
            NEW.provider_secret_reference_id, NEW.project_id,
            provider_secret.purpose, NEW.provider_secret_version
       ) THEN
        RAISE EXCEPTION 'Model Gateway Provider Secret handle is unavailable'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO STRICT adapter
    FROM model_gateway_adapter_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND release_hash = NEW.adapter_release_hash;
    SELECT * INTO STRICT model
    FROM model_gateway_model_releases
    WHERE provider = NEW.provider
      AND adapter_release_id = NEW.adapter_release_id
      AND model_release_id = NEW.model_release_id
      AND release_hash = NEW.model_release_hash;
    IF NEW.capture_method <> adapter.expected_capture_method
       OR NEW.configured_model <> model.configured_model
       OR (NEW.search_mode IS NOT NULL AND NEW.search_mode <> 'disabled'
            AND NOT adapter.supports_search) THEN
        RAISE EXCEPTION 'Model Gateway attempt violates exact capture, model, or search release'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.kind <> 'initial' THEN
        SELECT * INTO STRICT parent
        FROM model_gateway_call_attempts
        WHERE id = NEW.parent_attempt_id
          AND project_id = NEW.project_id AND job_id = NEW.job_id;
        SELECT * INTO STRICT parent_terminal
        FROM model_gateway_terminal_events
        WHERE attempt_id = NEW.parent_attempt_id AND project_id = NEW.project_id;
        IF parent_terminal.status <> 'failed'
           OR parent.runtime_manifest_id <> NEW.runtime_manifest_id
           OR parent.runtime_manifest_hash <> NEW.runtime_manifest_hash
           OR parent.runtime_option_id <> NEW.runtime_option_id
           OR parent.runtime_option_hash <> NEW.runtime_option_hash
           OR parent.provider <> NEW.provider
           OR parent.adapter_release_id <> NEW.adapter_release_id
           OR parent.adapter_release_hash <> NEW.adapter_release_hash
           OR parent.model_release_id <> NEW.model_release_id
           OR parent.model_release_hash <> NEW.model_release_hash
           OR parent.provider_secret_reference_id <> NEW.provider_secret_reference_id
           OR parent.provider_secret_version <> NEW.provider_secret_version
           OR parent.provider_secret_handle_hash <> NEW.provider_secret_handle_hash
           OR parent.admission_mode <> NEW.admission_mode
           OR parent.policy_version_id <> NEW.policy_version_id
           OR parent.policy_version_hash <> NEW.policy_version_hash
           OR parent.purpose <> NEW.purpose
           OR parent.usage_audience <> NEW.usage_audience
           OR parent.prompt_binding_id <> NEW.prompt_binding_id
           OR parent.prompt_release_id <> NEW.prompt_release_id
           OR parent.prompt_release_hash <> NEW.prompt_release_hash
           OR parent.prompt_state_id <> NEW.prompt_state_id
           OR parent.prompt_state_version <> NEW.prompt_state_version
           OR parent.prompt_test_set_hash IS DISTINCT FROM NEW.prompt_test_set_hash
           OR parent.prompt_test_case_id IS DISTINCT FROM NEW.prompt_test_case_id
           OR parent.prompt_test_case_hash IS DISTINCT FROM NEW.prompt_test_case_hash
           OR parent.prompt_bundle_hash <> NEW.prompt_bundle_hash
           OR parent.output_schema_hash <> NEW.output_schema_hash
           OR parent.application_output_schema_hash
                <> NEW.application_output_schema_hash
           OR parent.raw_artifact_policy_hash <> NEW.raw_artifact_policy_hash
           OR parent.raw_artifact_storage_decision <> NEW.raw_artifact_storage_decision
           OR parent.raw_artifact_cache_decision <> NEW.raw_artifact_cache_decision
           OR parent.raw_artifact_display_decision <> NEW.raw_artifact_display_decision
           OR parent.raw_artifact_redistribution_decision
                <> NEW.raw_artifact_redistribution_decision
           OR parent.raw_artifact_retention_days IS DISTINCT FROM NEW.raw_artifact_retention_days
           OR parent.configured_model <> NEW.configured_model
           OR parent.search_mode IS DISTINCT FROM NEW.search_mode
           OR parent.capture_method IS DISTINCT FROM NEW.capture_method
           OR parent.requested_location_country
                IS DISTINCT FROM NEW.requested_location_country
           OR parent.requested_location_region
                IS DISTINCT FROM NEW.requested_location_region
           OR parent.requested_location_locale
                IS DISTINCT FROM NEW.requested_location_locale
           OR parent.requested_location_language
                IS DISTINCT FROM NEW.requested_location_language
           OR parent.expected_location_control
                IS DISTINCT FROM NEW.expected_location_control
           OR parent.expected_location_country
                IS DISTINCT FROM NEW.expected_location_country
           OR parent.expected_location_region
                IS DISTINCT FROM NEW.expected_location_region
           OR parent.expected_location_locale
                IS DISTINCT FROM NEW.expected_location_locale
           OR parent.expected_location_language
                IS DISTINCT FROM NEW.expected_location_language
           OR parent.expected_location_evidence_hash
                IS DISTINCT FROM NEW.expected_location_evidence_hash
           OR (NEW.kind = 'retry' AND (
                parent_terminal.error_retryable IS NOT TRUE
                OR parent.input_hash <> NEW.input_hash
           ))
           OR (NEW.kind = 'repair' AND parent_terminal.error_code <> 'schema_invalid') THEN
            RAISE EXCEPTION 'Model Gateway retry/repair parent lineage is invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_attempt_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Model Gateway call attempts are append-only'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_terminal_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE
    attempt record;
    admission record;
    durable record;
    adapter record;
    model record;
    bundle record;
    raw_artifact record;
    bundle_found boolean;
    artifact_count integer;
BEGIN
    SELECT * INTO STRICT attempt
    FROM model_gateway_call_attempts
    WHERE id = NEW.attempt_id
      AND project_id = NEW.project_id AND job_id = NEW.job_id;
    SELECT * INTO STRICT admission
    FROM model_gateway_job_admissions
    WHERE project_id = NEW.project_id AND job_id = NEW.job_id
    FOR UPDATE;
    IF admission.budget_version <> NEW.expected_budget_version
       OR admission.reserved_calls < 1 THEN
        RAISE EXCEPTION 'Model Gateway terminal write lost budget CAS or reservation'
            USING ERRCODE = '40001';
    END IF;
    IF NEW.occurred_at < attempt.reserved_at
       OR NEW.input_hash <> attempt.input_hash
       OR NEW.configured_model <> attempt.configured_model
       OR NEW.search_mode IS DISTINCT FROM attempt.search_mode
       OR NEW.capture_method IS DISTINCT FROM attempt.capture_method THEN
        RAISE EXCEPTION 'Model Gateway terminal lineage differs from reservation'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'failed' AND (
        NEW.effective_location_control IS NOT NULL
        OR NEW.effective_location_country IS NOT NULL
        OR NEW.effective_location_region IS NOT NULL
        OR NEW.effective_location_locale IS NOT NULL
        OR NEW.effective_location_language IS NOT NULL
        OR NEW.effective_location_evidence_hash IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'failed Model Gateway terminal cannot claim effective location'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'succeeded' AND (
        (attempt.expected_location_control IS NULL AND (
            NEW.effective_location_control IS NOT NULL
            OR NEW.effective_location_country IS NOT NULL
            OR NEW.effective_location_region IS NOT NULL
            OR NEW.effective_location_locale IS NOT NULL
            OR NEW.effective_location_language IS NOT NULL
            OR NEW.effective_location_evidence_hash IS NOT NULL
        ))
        OR (attempt.expected_location_control IS NOT NULL AND (
            NEW.effective_location_control IS NULL
            OR NEW.effective_location_evidence_hash IS NULL
        ))
    ) THEN
        RAISE EXCEPTION 'Model Gateway success effective-location lineage is incomplete'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO STRICT adapter
    FROM model_gateway_adapter_releases
    WHERE provider = attempt.provider
      AND adapter_release_id = attempt.adapter_release_id
      AND release_hash = attempt.adapter_release_hash;
    IF NEW.raw_artifact_policy_hash <> adapter.data_policy_hash
       OR NEW.raw_artifact_storage_decision <> adapter.data_storage_decision
       OR NEW.raw_artifact_cache_decision <> adapter.data_cache_decision
       OR NEW.raw_artifact_display_decision <> adapter.data_display_decision
       OR NEW.raw_artifact_redistribution_decision <> adapter.data_redistribution_decision
       OR NEW.raw_artifact_retention_days IS DISTINCT FROM adapter.data_policy_retention_days
       OR NEW.raw_artifact_policy_hash <> attempt.raw_artifact_policy_hash
       OR NEW.raw_artifact_storage_decision <> attempt.raw_artifact_storage_decision
       OR NEW.raw_artifact_cache_decision <> attempt.raw_artifact_cache_decision
       OR NEW.raw_artifact_display_decision <> attempt.raw_artifact_display_decision
       OR NEW.raw_artifact_redistribution_decision
            <> attempt.raw_artifact_redistribution_decision
       OR NEW.usage_purpose <> attempt.purpose
       OR NEW.usage_audience <> attempt.usage_audience
       OR NEW.raw_artifact_retention_days IS DISTINCT FROM attempt.raw_artifact_retention_days THEN
        RAISE EXCEPTION 'Model Gateway raw artifact policy lineage is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO STRICT model
    FROM model_gateway_model_releases
    WHERE provider = attempt.provider
      AND adapter_release_id = attempt.adapter_release_id
      AND model_release_id = attempt.model_release_id
      AND release_hash = attempt.model_release_hash;
    IF (NEW.status = 'succeeded'
            AND model.reported_model_policy IN ('require_present', 'exact', 'allowlist')
            AND NEW.provider_reported_model IS NULL)
       OR (model.reported_model_policy = 'exact'
            AND NEW.provider_reported_model IS NOT NULL
            AND NEW.provider_reported_model <> model.configured_model)
       OR (model.reported_model_policy = 'allowlist'
            AND NEW.provider_reported_model IS NOT NULL
            AND NEW.provider_reported_model <> ALL(model.allowed_reported_models)) THEN
        RAISE EXCEPTION 'Model Gateway provider-reported model violates frozen Model Release'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.reconciled_by IS NULL THEN
        SELECT status, lease_token, lease_expires_at, fencing_generation, cancel_requested_at
        INTO STRICT durable
        FROM durable_jobs
        WHERE project_id = NEW.project_id AND id = NEW.job_id;
        IF durable.status NOT IN ('running', 'finalizing')
           OR durable.cancel_requested_at IS NOT NULL
           OR durable.lease_token IS DISTINCT FROM attempt.lease_token
           OR durable.fencing_generation <> attempt.fencing_generation
           OR durable.lease_expires_at IS NULL OR durable.lease_expires_at < NEW.occurred_at THEN
            RAISE EXCEPTION 'Model Gateway terminal writer lost Job lease or fencing ownership'
                USING ERRCODE = '40001';
        END IF;
    END IF;
    SELECT * INTO bundle
    FROM model_gateway_artifact_bundles
    WHERE project_id = NEW.project_id AND attempt_id = NEW.attempt_id;
    bundle_found := FOUND;
    IF attempt.raw_artifact_storage_decision = 'prohibited' THEN
        IF bundle_found OR NEW.raw_artifact_reference_hash IS NOT NULL THEN
            RAISE EXCEPTION 'Model Gateway prohibited storage cannot reference an artifact bundle'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'succeeded' THEN
        IF NOT bundle_found OR bundle.status <> 'staged' THEN
            RAISE EXCEPTION 'Model Gateway success requires a staged artifact bundle'
                USING ERRCODE = '23514';
        END IF;
        SELECT count(*) INTO artifact_count
        FROM model_gateway_artifacts artifact
        JOIN model_gateway_artifact_deks dek
          ON dek.key_ref = artifact.key_ref
         AND dek.project_id = artifact.project_id
         AND dek.artifact_id = artifact.artifact_id
        WHERE artifact.project_id = NEW.project_id
          AND artifact.bundle_id = bundle.id AND dek.status = 'active';
        SELECT * INTO raw_artifact FROM model_gateway_artifacts
        WHERE project_id = NEW.project_id AND bundle_id = bundle.id AND kind = 'raw';
        IF artifact_count <> 2 OR NOT FOUND
           OR NEW.raw_artifact_reference_hash IS NULL
           OR NEW.raw_artifact_reference_hash <> encode(
                digest(convert_to(raw_artifact.manifest_uri, 'UTF8'), 'sha256'), 'hex'
           ) THEN
            RAISE EXCEPTION 'Model Gateway success references incomplete unmanaged artifacts'
                USING ERRCODE = '23514';
        END IF;
        UPDATE model_gateway_artifact_bundles
        SET status = 'committed', committed_at = NEW.occurred_at,
            terminal_event_id = NEW.id, record_version = record_version + 1
        WHERE id = bundle.id;
    ELSIF bundle_found THEN
        IF bundle.status <> 'staged' THEN
            RAISE EXCEPTION 'Model Gateway failed Attempt artifact bundle is not staged'
                USING ERRCODE = '23514';
        END IF;
        UPDATE model_gateway_artifact_bundles
        SET status = 'orphaned', orphaned_at = NEW.occurred_at,
            terminal_event_id = NEW.id, record_version = record_version + 1
        WHERE id = bundle.id;
        INSERT INTO model_gateway_artifact_deletion_outbox(
            id, project_id, bundle_id, reason, status, available_at
        ) VALUES (
            gen_random_uuid(), NEW.project_id, bundle.id,
            'orphaned', 'pending', NEW.occurred_at
        );
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_terminal_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Model Gateway terminal events are append-only'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_assert_model_gateway_budget_consistency() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    scoped_project uuid;
    scoped_job uuid;
    admission record;
    attempt_count integer;
    terminal_count integer;
    paid_count integer;
BEGIN
    scoped_project := NEW.project_id;
    scoped_job := NEW.job_id;
    SELECT * INTO STRICT admission
    FROM model_gateway_job_admissions
    WHERE project_id = scoped_project AND job_id = scoped_job;
    SELECT count(*) INTO attempt_count
    FROM model_gateway_call_attempts
    WHERE project_id = scoped_project AND job_id = scoped_job;
    SELECT count(*), coalesce(sum(paid_call_count), 0)
    INTO terminal_count, paid_count
    FROM model_gateway_terminal_events
    WHERE project_id = scoped_project AND job_id = scoped_job;
    IF admission.paid_calls <> paid_count
       OR admission.reserved_calls <> attempt_count - terminal_count
       OR admission.next_attempt_number <> attempt_count + 1
       OR admission.budget_version <> attempt_count + terminal_count THEN
        RAISE EXCEPTION 'Model Gateway budget counters do not match append-only call history'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER model_gateway_adapter_releases_immutable
BEFORE UPDATE OR DELETE ON model_gateway_adapter_releases
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_adapter_release();
CREATE TRIGGER model_gateway_adapter_releases_insert_guard
BEFORE INSERT ON model_gateway_adapter_releases
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_adapter_release();
CREATE TRIGGER model_gateway_model_releases_insert_guard
BEFORE INSERT ON model_gateway_model_releases
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_model_release();
CREATE TRIGGER model_gateway_model_releases_immutable
BEFORE UPDATE OR DELETE ON model_gateway_model_releases
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_model_release();
CREATE TRIGGER model_gateway_project_policy_versions_append_guard
BEFORE INSERT ON model_gateway_project_policy_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_policy_append();
CREATE TRIGGER model_gateway_project_policy_versions_immutable
BEFORE UPDATE OR DELETE ON model_gateway_project_policy_versions
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER model_gateway_runtime_manifests_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON model_gateway_runtime_manifests
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_runtime_manifest_change();
CREATE TRIGGER model_gateway_runtime_options_insert_guard
BEFORE INSERT ON model_gateway_runtime_options
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_runtime_option();
CREATE TRIGGER model_gateway_runtime_options_immutable
BEFORE UPDATE OR DELETE ON model_gateway_runtime_options
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER model_gateway_job_admissions_insert_guard
BEFORE INSERT ON model_gateway_job_admissions
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_job_admission_insert();
CREATE TRIGGER model_gateway_job_admissions_budget_guard
BEFORE UPDATE OR DELETE ON model_gateway_job_admissions
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_job_budget_change();
CREATE TRIGGER model_gateway_call_attempts_insert_guard
BEFORE INSERT ON model_gateway_call_attempts
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_attempt_insert();
CREATE TRIGGER model_gateway_call_attempts_immutable
BEFORE UPDATE OR DELETE ON model_gateway_call_attempts
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_attempt_immutable();
CREATE TRIGGER model_gateway_terminal_events_insert_guard
BEFORE INSERT ON model_gateway_terminal_events
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_terminal_insert();
CREATE TRIGGER model_gateway_terminal_events_immutable
BEFORE UPDATE OR DELETE ON model_gateway_terminal_events
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_terminal_immutable();
CREATE TRIGGER model_gateway_reconciliation_commands_insert_guard
BEFORE INSERT ON model_gateway_reconciliation_commands
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_reconciliation_command();
CREATE TRIGGER model_gateway_reconciliation_commands_immutable
BEFORE UPDATE OR DELETE ON model_gateway_reconciliation_commands
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER model_gateway_artifact_recovery_receipts_insert_guard
BEFORE INSERT ON model_gateway_artifact_recovery_receipts
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_recovery_receipt();
CREATE TRIGGER model_gateway_artifact_recovery_receipts_immutable
BEFORE UPDATE OR DELETE ON model_gateway_artifact_recovery_receipts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE CONSTRAINT TRIGGER model_gateway_artifact_recovery_receipts_consistency_guard
AFTER INSERT ON model_gateway_artifact_recovery_receipts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_recovery_consistency();
CREATE TRIGGER model_gateway_artifact_master_key_change_guard
BEFORE UPDATE OR DELETE ON model_gateway_artifact_master_key_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_master_key_change();
CREATE TRIGGER model_gateway_artifact_bundles_insert_guard
BEFORE INSERT ON model_gateway_artifact_bundles
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_bundle_insert();
CREATE TRIGGER model_gateway_artifact_bundles_change_guard
BEFORE UPDATE OR DELETE ON model_gateway_artifact_bundles
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_bundle_change();
CREATE TRIGGER model_gateway_artifact_deks_change_guard
BEFORE UPDATE OR DELETE ON model_gateway_artifact_deks
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_dek_change();
CREATE TRIGGER model_gateway_artifacts_insert_guard
BEFORE INSERT ON model_gateway_artifacts
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_insert();
CREATE TRIGGER model_gateway_artifacts_update_guard
BEFORE UPDATE ON model_gateway_artifacts
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_immutable();
CREATE TRIGGER model_gateway_artifact_deletion_outbox_change_guard
BEFORE UPDATE OR DELETE ON model_gateway_artifact_deletion_outbox
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_outbox_change();
CREATE TRIGGER model_gateway_artifact_tombstones_immutable
BEFORE UPDATE OR DELETE ON model_gateway_artifact_tombstones
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_artifact_tombstone_immutable();

CREATE CONSTRAINT TRIGGER model_gateway_job_admissions_consistency_guard
AFTER INSERT OR UPDATE ON model_gateway_job_admissions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_budget_consistency();
CREATE CONSTRAINT TRIGGER model_gateway_runtime_manifests_consistency_guard
AFTER INSERT OR UPDATE ON model_gateway_runtime_manifests
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_runtime_manifest_consistency();
CREATE CONSTRAINT TRIGGER model_gateway_runtime_options_consistency_guard
AFTER INSERT ON model_gateway_runtime_options
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_runtime_manifest_consistency();
CREATE CONSTRAINT TRIGGER model_gateway_call_attempts_consistency_guard
AFTER INSERT ON model_gateway_call_attempts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_budget_consistency();
CREATE CONSTRAINT TRIGGER model_gateway_terminal_events_consistency_guard
AFTER INSERT ON model_gateway_terminal_events
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_model_gateway_budget_consistency();

CREATE INDEX model_gateway_adapter_releases_state_idx
ON model_gateway_adapter_releases(provider, state, registered_at DESC);
CREATE INDEX model_gateway_adapter_releases_registered_by_idx
ON model_gateway_adapter_releases(registered_by);
CREATE INDEX model_gateway_model_releases_adapter_fkey_idx
ON model_gateway_model_releases(provider, adapter_release_id, adapter_release_hash);
CREATE INDEX model_gateway_model_releases_state_idx
ON model_gateway_model_releases(provider, state, registered_at DESC);
CREATE INDEX model_gateway_model_releases_registered_by_idx
ON model_gateway_model_releases(registered_by);
CREATE INDEX model_gateway_project_policy_versions_project_idx
ON model_gateway_project_policy_versions(project_id, version DESC);
CREATE INDEX model_gateway_project_policy_versions_previous_fkey_idx
ON model_gateway_project_policy_versions(previous_version_id, project_id);
CREATE INDEX model_gateway_project_policy_versions_created_by_idx
ON model_gateway_project_policy_versions(created_by);
CREATE INDEX model_gateway_runtime_manifests_policy_fkey_idx
ON model_gateway_runtime_manifests(
    policy_version_id, project_id, policy_version_hash
);
CREATE INDEX model_gateway_runtime_manifests_approved_by_idx
ON model_gateway_runtime_manifests(approved_by);
CREATE INDEX model_gateway_runtime_manifests_prepared_by_idx
ON model_gateway_runtime_manifests(prepared_by);
CREATE INDEX model_gateway_runtime_manifests_retired_by_idx
ON model_gateway_runtime_manifests(retired_by) WHERE retired_by IS NOT NULL;
CREATE INDEX model_gateway_runtime_options_manifest_fkey_idx
ON model_gateway_runtime_options(manifest_id, project_id);
CREATE INDEX model_gateway_runtime_options_adapter_fkey_idx
ON model_gateway_runtime_options(
    provider, adapter_release_id, adapter_release_hash
);
CREATE INDEX model_gateway_runtime_options_model_fkey_idx
ON model_gateway_runtime_options(
    provider, adapter_release_id, model_release_id, model_release_hash
);
CREATE INDEX model_gateway_runtime_options_secret_fkey_idx
ON model_gateway_runtime_options(secret_reference_id, project_id, secret_purpose);
CREATE INDEX model_gateway_job_admissions_runtime_manifest_fkey_idx
ON model_gateway_job_admissions(
    runtime_manifest_id, project_id, runtime_manifest_hash
);
CREATE INDEX model_gateway_job_admissions_runtime_option_fkey_idx
ON model_gateway_job_admissions(
    runtime_option_id, project_id, runtime_manifest_id, runtime_option_hash
);
CREATE INDEX model_gateway_job_admissions_policy_fkey_idx
ON model_gateway_job_admissions(policy_version_id, project_id, policy_version_hash);
CREATE INDEX model_gateway_job_admissions_route_idx
ON model_gateway_job_admissions(
    provider, adapter_release_id, model_release_id, project_id
);
CREATE INDEX model_gateway_job_admissions_secret_fkey_idx
ON model_gateway_job_admissions(provider_secret_reference_id, provider_secret_version);
CREATE INDEX model_gateway_job_admissions_prompt_binding_fkey_idx
ON model_gateway_job_admissions(prompt_binding_id, project_id);
CREATE INDEX model_gateway_job_admissions_prompt_release_fkey_idx
ON model_gateway_job_admissions(prompt_release_id, project_id, prompt_release_hash);
CREATE INDEX model_gateway_job_admissions_prompt_state_fkey_idx
ON model_gateway_job_admissions(
    prompt_frozen_state_id, project_id, prompt_release_id,
    prompt_release_hash, prompt_state_version
);
CREATE INDEX model_gateway_job_admissions_admitted_by_idx
ON model_gateway_job_admissions(admitted_by);
CREATE INDEX model_gateway_call_attempts_job_idx
ON model_gateway_call_attempts(project_id, job_id, attempt_number DESC);
CREATE INDEX model_gateway_call_attempts_parent_fkey_idx
ON model_gateway_call_attempts(parent_attempt_id, project_id, job_id);
CREATE INDEX model_gateway_call_attempts_runtime_manifest_fkey_idx
ON model_gateway_call_attempts(
    runtime_manifest_id, project_id, runtime_manifest_hash
);
CREATE INDEX model_gateway_call_attempts_runtime_option_fkey_idx
ON model_gateway_call_attempts(
    runtime_option_id, project_id, runtime_manifest_id, runtime_option_hash
);
CREATE INDEX model_gateway_call_attempts_policy_fkey_idx
ON model_gateway_call_attempts(policy_version_id, project_id, policy_version_hash);
CREATE INDEX model_gateway_call_attempts_route_idx
ON model_gateway_call_attempts(provider, adapter_release_id, model_release_id);
CREATE INDEX model_gateway_call_attempts_secret_fkey_idx
ON model_gateway_call_attempts(provider_secret_reference_id, provider_secret_version);
CREATE INDEX model_gateway_call_attempts_prompt_binding_fkey_idx
ON model_gateway_call_attempts(prompt_binding_id, project_id);
CREATE INDEX model_gateway_call_attempts_prompt_release_fkey_idx
ON model_gateway_call_attempts(prompt_release_id, project_id, prompt_release_hash);
CREATE INDEX model_gateway_call_attempts_prompt_state_fkey_idx
ON model_gateway_call_attempts(
    prompt_state_id, project_id, prompt_release_id,
    prompt_release_hash, prompt_state_version
);
CREATE INDEX model_gateway_terminal_events_job_time_idx
ON model_gateway_terminal_events(project_id, job_id, occurred_at DESC);
CREATE INDEX model_gateway_terminal_events_attempt_fkey_idx
ON model_gateway_terminal_events(attempt_id, project_id, job_id);
CREATE INDEX model_gateway_terminal_events_reconciled_by_idx
ON model_gateway_terminal_events(reconciled_by) WHERE reconciled_by IS NOT NULL;
CREATE INDEX model_gateway_reconciliation_commands_recorded_idx
ON model_gateway_reconciliation_commands(project_id, recorded_at DESC, id);
CREATE INDEX model_gateway_reconciliation_commands_terminal_fkey_idx
ON model_gateway_reconciliation_commands(terminal_event_id, project_id);
CREATE INDEX model_gateway_artifact_recovery_receipts_attempt_idx
ON model_gateway_artifact_recovery_receipts(
    project_id, model_call_attempt_id, recovered_at DESC
);
CREATE INDEX model_gateway_artifact_recovery_receipts_job_fkey_idx
ON model_gateway_artifact_recovery_receipts(recovery_job_id, project_id);
CREATE INDEX model_gateway_artifact_recovery_receipts_source_job_fkey_idx
ON model_gateway_artifact_recovery_receipts(source_model_job_id, project_id);
CREATE INDEX model_gateway_artifact_bundles_attempt_fkey_idx
ON model_gateway_artifact_bundles(attempt_id, project_id, job_id);
CREATE INDEX model_gateway_artifact_bundles_expiry_idx
ON model_gateway_artifact_bundles(status, expires_at, staged_at)
WHERE status IN ('staged', 'committed');
CREATE INDEX model_gateway_artifact_deks_project_idx
ON model_gateway_artifact_deks(project_id, status, created_at);
CREATE INDEX model_gateway_artifact_deks_restore_idx
ON model_gateway_artifact_deks(master_key_version, status, project_id, created_at);
CREATE INDEX model_gateway_artifact_deks_unstaged_idx
ON model_gateway_artifact_deks(created_at, key_ref)
WHERE status = 'active';
CREATE INDEX model_gateway_artifacts_bundle_fkey_idx
ON model_gateway_artifacts(bundle_id, project_id);
CREATE INDEX model_gateway_artifact_deletion_ready_idx
ON model_gateway_artifact_deletion_outbox(status, available_at, lease_expires_at, id)
WHERE status IN ('pending', 'processing');
CREATE INDEX model_gateway_artifact_tombstones_project_idx
ON model_gateway_artifact_tombstones(project_id, deleted_at DESC);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'model_gateway_project_policy_versions',
        'model_gateway_runtime_manifests', 'model_gateway_runtime_options',
        'model_gateway_job_admissions',
        'model_gateway_call_attempts',
        'model_gateway_terminal_events',
        'model_gateway_reconciliation_commands',
        'model_gateway_artifact_recovery_receipts',
        'model_gateway_artifact_bundles', 'model_gateway_artifact_deks',
        'model_gateway_artifacts', 'model_gateway_artifact_deletion_outbox',
        'model_gateway_artifact_tombstones'
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
    model_gateway_adapter_releases, model_gateway_model_releases,
    model_gateway_project_policy_versions,
    model_gateway_runtime_manifests, model_gateway_runtime_options,
    model_gateway_job_admissions,
    model_gateway_call_attempts, model_gateway_terminal_events,
    model_gateway_reconciliation_commands,
    model_gateway_artifact_recovery_receipts,
    model_gateway_artifact_master_key_versions,
    model_gateway_artifact_bundles, model_gateway_artifact_deks,
    model_gateway_artifacts, model_gateway_artifact_deletion_outbox,
    model_gateway_artifact_tombstones
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

GRANT SELECT ON
    model_gateway_adapter_releases, model_gateway_model_releases,
    model_gateway_project_policy_versions,
    model_gateway_runtime_manifests, model_gateway_runtime_options,
    model_gateway_job_admissions,
    model_gateway_call_attempts, model_gateway_terminal_events,
    model_gateway_reconciliation_commands,
    model_gateway_artifact_bundles, model_gateway_artifact_deks,
    model_gateway_artifacts, model_gateway_artifact_deletion_outbox,
    model_gateway_artifact_tombstones
TO geo_app, geo_worker;
GRANT SELECT, INSERT ON model_gateway_artifact_recovery_receipts TO geo_worker;
GRANT SELECT ON model_gateway_artifact_master_key_versions TO geo_worker;
GRANT INSERT ON
    model_gateway_adapter_releases, model_gateway_model_releases,
    model_gateway_project_policy_versions, model_gateway_job_admissions
TO geo_app;
GRANT INSERT ON model_gateway_call_attempts, model_gateway_terminal_events,
    model_gateway_reconciliation_commands
TO geo_app, geo_worker;
GRANT INSERT ON
    model_gateway_artifact_bundles, model_gateway_artifact_deks,
    model_gateway_artifacts
TO geo_app, geo_worker;
GRANT UPDATE (paid_calls, reserved_calls, budget_version, next_attempt_number)
ON model_gateway_job_admissions TO geo_app, geo_worker;

REVOKE ALL ON FUNCTION
    geo_assert_model_gateway_text_array(text[], text),
    geo_model_gateway_secret_handle_hash(uuid, uuid, text, integer),
    geo_assert_model_gateway_adapter_release(),
    geo_assert_model_gateway_model_release(),
    geo_assert_model_gateway_policy_append(),
    geo_assert_model_gateway_runtime_manifest_change(),
    geo_assert_model_gateway_runtime_option(),
    geo_assert_model_gateway_runtime_manifest_consistency(),
    geo_register_model_gateway_runtime_manifest(uuid, uuid, text, integer, uuid, text, text, integer, uuid, timestamptz, uuid, timestamptz, text, text),
    geo_add_model_gateway_runtime_option(uuid, uuid, uuid, text, text, text, text, text, uuid, text, text, text, text, text, text, text[], jsonb, text, timestamptz),
    geo_retire_model_gateway_runtime_manifest(uuid, uuid, uuid, timestamptz),
    geo_resolve_model_gateway_runtime_option(uuid, uuid, text, text),
    geo_assert_model_gateway_job_admission_insert(),
    geo_assert_model_gateway_job_budget_change(),
    geo_refresh_model_gateway_job_admission_lease(uuid, uuid, integer, uuid, bigint, timestamptz),
    geo_assert_model_gateway_attempt_insert(),
    geo_assert_model_gateway_attempt_immutable(),
    geo_assert_model_gateway_terminal_insert(),
    geo_assert_model_gateway_terminal_immutable(),
    geo_assert_model_gateway_reconciliation_command(),
    geo_assert_model_gateway_artifact_recovery_receipt(),
    geo_assert_model_gateway_artifact_recovery_consistency(),
    geo_assert_model_gateway_artifact_master_key_change(),
    geo_sync_model_gateway_artifact_master_key_version(integer, text, text, bytea, bytea, timestamptz),
    geo_retire_model_gateway_artifact_master_key_version(integer, timestamptz),
    geo_assert_model_gateway_budget_consistency(),
    geo_assert_model_gateway_artifact_bundle_insert(),
    geo_assert_model_gateway_artifact_bundle_change(),
    geo_assert_model_gateway_artifact_dek_change(),
    geo_assert_model_gateway_artifact_insert(),
    geo_assert_model_gateway_artifact_immutable(),
    geo_assert_model_gateway_artifact_outbox_change(),
    geo_assert_model_gateway_artifact_tombstone_immutable(),
    geo_destroy_model_gateway_unstaged_artifact_deks(timestamptz, integer),
    geo_stage_model_gateway_artifact_expiry(timestamptz, integer),
    geo_claim_model_gateway_artifact_deletions(integer, integer),
    geo_complete_model_gateway_artifact_deletion(uuid, uuid, uuid, bigint, text),
    geo_fail_model_gateway_artifact_deletion(uuid, uuid, uuid, bigint, text, integer)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

GRANT EXECUTE ON FUNCTION
    geo_assert_model_gateway_text_array(text[], text),
    geo_model_gateway_secret_handle_hash(uuid, uuid, text, integer),
    geo_assert_model_gateway_adapter_release(),
    geo_assert_model_gateway_model_release(),
    geo_assert_model_gateway_policy_append(),
    geo_assert_model_gateway_runtime_manifest_change(),
    geo_assert_model_gateway_runtime_option(),
    geo_assert_model_gateway_runtime_manifest_consistency(),
    geo_assert_model_gateway_job_admission_insert(),
    geo_assert_model_gateway_job_budget_change(),
    geo_assert_model_gateway_attempt_insert(),
    geo_assert_model_gateway_attempt_immutable(),
    geo_assert_model_gateway_terminal_insert(),
    geo_assert_model_gateway_terminal_immutable(),
    geo_assert_model_gateway_reconciliation_command(),
    geo_assert_model_gateway_artifact_recovery_receipt(),
    geo_assert_model_gateway_artifact_recovery_consistency(),
    geo_assert_model_gateway_artifact_master_key_change(),
    geo_assert_model_gateway_budget_consistency(),
    geo_assert_model_gateway_artifact_bundle_insert(),
    geo_assert_model_gateway_artifact_bundle_change(),
    geo_assert_model_gateway_artifact_dek_change(),
    geo_assert_model_gateway_artifact_insert(),
    geo_assert_model_gateway_artifact_immutable(),
    geo_assert_model_gateway_artifact_outbox_change(),
    geo_assert_model_gateway_artifact_tombstone_immutable()
TO geo_app, geo_worker;
GRANT EXECUTE ON FUNCTION
    geo_register_model_gateway_runtime_manifest(uuid, uuid, text, integer, uuid, text, text, integer, uuid, timestamptz, uuid, timestamptz, text, text),
    geo_add_model_gateway_runtime_option(uuid, uuid, uuid, text, text, text, text, text, uuid, text, text, text, text, text, text, text[], jsonb, text, timestamptz),
    geo_retire_model_gateway_runtime_manifest(uuid, uuid, uuid, timestamptz)
TO geo_app;
GRANT EXECUTE ON FUNCTION
    geo_refresh_model_gateway_job_admission_lease(
        uuid, uuid, integer, uuid, bigint, timestamptz
    )
TO geo_app, geo_worker;
GRANT EXECUTE ON FUNCTION
    geo_resolve_model_gateway_runtime_option(uuid, uuid, text, text)
TO geo_app, geo_worker;
GRANT EXECUTE ON FUNCTION
    geo_sync_model_gateway_artifact_master_key_version(integer, text, text, bytea, bytea, timestamptz),
    geo_retire_model_gateway_artifact_master_key_version(integer, timestamptz),
    geo_destroy_model_gateway_unstaged_artifact_deks(timestamptz, integer),
    geo_stage_model_gateway_artifact_expiry(timestamptz, integer),
    geo_claim_model_gateway_artifact_deletions(integer, integer),
    geo_complete_model_gateway_artifact_deletion(uuid, uuid, uuid, bigint, text),
    geo_fail_model_gateway_artifact_deletion(uuid, uuid, uuid, bigint, text, integer)
TO geo_worker;

COMMENT ON COLUMN model_gateway_job_admissions.output_schema_hash IS
    'Provider-portable structured-output Schema hash; application_output_schema_hash is the separate full application validator identity.';
COMMENT ON COLUMN model_gateway_call_attempts.output_schema_hash IS
    'Provider-portable structured-output Schema hash; application_output_schema_hash is the separate full application validator identity.';
