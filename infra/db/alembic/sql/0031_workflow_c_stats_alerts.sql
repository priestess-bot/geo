CREATE TABLE workflow_c_sampling_admission_policies (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    revision integer NOT NULL CHECK (revision > 0),
    supersedes_policy_id uuid,
    status text NOT NULL CHECK (status IN ('draft', 'approved', 'retired')),
    effective_authorization_state text NOT NULL CHECK (
        effective_authorization_state IN (
            'not_assessed', 'approved', 'assessed_no_basis', 'expired', 'revoked'
        )
    ),
    definition_hash text NOT NULL CHECK (definition_hash ~ '^[0-9a-f]{64}$'),
    policy_version text NOT NULL CHECK (btrim(policy_version) <> ''),
    valid_until timestamptz NOT NULL,
    quota_remaining integer NOT NULL CHECK (quota_remaining >= 0),
    daily_task_limit integer NOT NULL CHECK (daily_task_limit > 0),
    minimum_request_interval_seconds integer NOT NULL CHECK (
        minimum_request_interval_seconds >= 0
    ),
    max_concurrency integer NOT NULL CHECK (max_concurrency > 0),
    next_allowed_at timestamptz,
    aggregate_version integer NOT NULL CHECK (aggregate_version > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, revision),
    FOREIGN KEY (supersedes_policy_id, project_id)
        REFERENCES workflow_c_sampling_admission_policies(id, project_id),
    CHECK (created_at <= updated_at AND created_at < valid_until),
    CHECK ((revision = 1) = (supersedes_policy_id IS NULL))
);

CREATE TABLE workflow_c_sampling_admission_usage (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    policy_id uuid NOT NULL,
    window_start timestamptz NOT NULL,
    reserved_count integer NOT NULL DEFAULT 0 CHECK (reserved_count >= 0),
    consumed_count integer NOT NULL DEFAULT 0 CHECK (consumed_count >= 0),
    released_count integer NOT NULL DEFAULT 0 CHECK (released_count >= 0),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, policy_id, window_start),
    FOREIGN KEY (policy_id, project_id)
        REFERENCES workflow_c_sampling_admission_policies(id, project_id),
    CHECK (released_count <= reserved_count)
);

CREATE TABLE workflow_c_sampling_suites (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    suite_hash text NOT NULL CHECK (suite_hash ~ '^[0-9a-f]{64}$'),
    admission_policy_id uuid NOT NULL,
    admission_policy_hash text NOT NULL CHECK (
        admission_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    source_stratum_hash text NOT NULL CHECK (source_stratum_hash ~ '^[0-9a-f]{64}$'),
    capture_method text NOT NULL CHECK (capture_method IN (
        'provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui'
    )),
    planned_task_count integer NOT NULL CHECK (planned_task_count > 0),
    minimum_valid_repeats integer NOT NULL CHECK (minimum_valid_repeats >= 3),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    frozen_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, suite_hash),
    FOREIGN KEY (admission_policy_id, project_id)
        REFERENCES workflow_c_sampling_admission_policies(id, project_id)
);

CREATE TABLE workflow_c_sampling_runs (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    suite_id uuid NOT NULL,
    suite_hash text NOT NULL CHECK (suite_hash ~ '^[0-9a-f]{64}$'),
    admission_policy_id uuid NOT NULL,
    admission_policy_hash text NOT NULL CHECK (
        admission_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    admission_grant_hash text NOT NULL CHECK (admission_grant_hash ~ '^[0-9a-f]{64}$'),
    purpose text NOT NULL CHECK (btrim(purpose) <> ''),
    status text NOT NULL CHECK (status IN (
        'planned', 'running', 'cancel_requested', 'completed', 'cancelled', 'failed'
    )),
    reserved_task_count integer NOT NULL CHECK (reserved_task_count >= 0),
    admitted_not_before timestamptz NOT NULL,
    authorization_valid_until timestamptz NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    FOREIGN KEY (suite_id, project_id)
        REFERENCES workflow_c_sampling_suites(id, project_id),
    FOREIGN KEY (admission_policy_id, project_id)
        REFERENCES workflow_c_sampling_admission_policies(id, project_id),
    CHECK (admitted_not_before <= authorization_valid_until)
);

CREATE TABLE workflow_c_sampling_tasks (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid NOT NULL,
    suite_id uuid NOT NULL,
    task_key text NOT NULL CHECK (task_key ~ '^[0-9a-f]{64}$'),
    source_stratum_hash text NOT NULL CHECK (source_stratum_hash ~ '^[0-9a-f]{64}$'),
    capture_method text NOT NULL CHECK (capture_method IN (
        'provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui'
    )),
    question_id text NOT NULL CHECK (btrim(question_id) <> ''),
    question_version text NOT NULL CHECK (btrim(question_version) <> ''),
    repetition integer NOT NULL CHECK (repetition > 0),
    status text NOT NULL CHECK (status IN (
        'planned', 'queued', 'running', 'finalizing', 'retry_ready',
        'succeeded', 'failed', 'cancel_requested', 'cancelled'
    )),
    version integer NOT NULL CHECK (version > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, run_id, task_key),
    FOREIGN KEY (run_id, project_id)
        REFERENCES workflow_c_sampling_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (suite_id, project_id)
        REFERENCES workflow_c_sampling_suites(id, project_id),
    CHECK (created_at <= updated_at)
);

CREATE TABLE workflow_c_sampling_attempts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid NOT NULL,
    task_id uuid NOT NULL,
    task_key text NOT NULL CHECK (task_key ~ '^[0-9a-f]{64}$'),
    durable_job_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    status text NOT NULL CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled'
    )),
    authorization_checked_at timestamptz NOT NULL,
    actual_location_json jsonb CHECK (
        actual_location_json IS NULL OR jsonb_typeof(actual_location_json) = 'object'
    ),
    actual_location_hash text CHECK (
        actual_location_hash IS NULL OR actual_location_hash ~ '^[0-9a-f]{64}$'
    ),
    actual_location_control text GENERATED ALWAYS AS (
        actual_location_json->>'location_control'
    ) STORED,
    actual_location_evidence_hash text GENERATED ALWAYS AS (
        actual_location_json->>'location_evidence_hash'
    ) STORED,
    actual_requested_country text GENERATED ALWAYS AS (
        actual_location_json->>'requested_country'
    ) STORED,
    actual_requested_region text GENERATED ALWAYS AS (
        actual_location_json->>'requested_region'
    ) STORED,
    actual_requested_locale text GENERATED ALWAYS AS (
        actual_location_json->>'requested_locale'
    ) STORED,
    actual_requested_language text GENERATED ALWAYS AS (
        actual_location_json->>'requested_language'
    ) STORED,
    actual_effective_country text GENERATED ALWAYS AS (
        actual_location_json->>'effective_country'
    ) STORED,
    actual_effective_region text GENERATED ALWAYS AS (
        actual_location_json->>'effective_region'
    ) STORED,
    actual_effective_locale text GENERATED ALWAYS AS (
        actual_location_json->>'effective_locale'
    ) STORED,
    actual_effective_language text GENERATED ALWAYS AS (
        actual_location_json->>'effective_language'
    ) STORED,
    provider_attempt_id uuid,
    provider_response_hash text CHECK (
        provider_response_hash IS NULL OR provider_response_hash ~ '^[0-9a-f]{64}$'
    ),
    output_hash text CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    version integer NOT NULL CHECK (version > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, task_id, ordinal),
    UNIQUE (durable_job_id, project_id),
    FOREIGN KEY (run_id, project_id)
        REFERENCES workflow_c_sampling_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, project_id)
        REFERENCES workflow_c_sampling_tasks(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (durable_job_id, project_id)
        REFERENCES durable_jobs(id, project_id),
    CHECK ((actual_location_json IS NULL) = (actual_location_hash IS NULL)),
    CHECK (
        actual_location_control IS NULL OR actual_location_control IN (
            'country', 'market_language', 'language_only', 'not_controlled'
        )
    ),
    CHECK (
        actual_location_evidence_hash IS NULL
        OR actual_location_evidence_hash ~ '^[0-9a-f]{64}$'
    ),
    CHECK (created_at <= updated_at)
);

CREATE TABLE workflow_c_sampling_observations (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid NOT NULL,
    task_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    task_key text NOT NULL CHECK (task_key ~ '^[0-9a-f]{64}$'),
    source_stratum_hash text NOT NULL CHECK (source_stratum_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('complete', 'ineligible')),
    observation_hash text NOT NULL CHECK (observation_hash ~ '^[0-9a-f]{64}$'),
    actual_location_json jsonb NOT NULL CHECK (
        jsonb_typeof(actual_location_json) = 'object'
    ),
    actual_location_control text GENERATED ALWAYS AS (
        actual_location_json->>'location_control'
    ) STORED,
    actual_location_evidence_hash text GENERATED ALWAYS AS (
        actual_location_json->>'location_evidence_hash'
    ) STORED,
    actual_requested_country text GENERATED ALWAYS AS (
        actual_location_json->>'requested_country'
    ) STORED,
    actual_requested_region text GENERATED ALWAYS AS (
        actual_location_json->>'requested_region'
    ) STORED,
    actual_requested_locale text GENERATED ALWAYS AS (
        actual_location_json->>'requested_locale'
    ) STORED,
    actual_requested_language text GENERATED ALWAYS AS (
        actual_location_json->>'requested_language'
    ) STORED,
    actual_effective_country text GENERATED ALWAYS AS (
        actual_location_json->>'effective_country'
    ) STORED,
    actual_effective_region text GENERATED ALWAYS AS (
        actual_location_json->>'effective_region'
    ) STORED,
    actual_effective_locale text GENERATED ALWAYS AS (
        actual_location_json->>'effective_locale'
    ) STORED,
    actual_effective_language text GENERATED ALWAYS AS (
        actual_location_json->>'effective_language'
    ) STORED,
    evidence_json jsonb NOT NULL CHECK (jsonb_typeof(evidence_json) = 'object'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    observed_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, task_id),
    UNIQUE (project_id, attempt_id),
    FOREIGN KEY (run_id, project_id)
        REFERENCES workflow_c_sampling_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, project_id)
        REFERENCES workflow_c_sampling_tasks(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (attempt_id, project_id)
        REFERENCES workflow_c_sampling_attempts(id, project_id) ON DELETE CASCADE,
    CHECK (actual_location_control IN (
        'country', 'market_language', 'language_only', 'not_controlled'
    )),
    CHECK (actual_location_evidence_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE workflow_c_sampling_manual_imports (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid NOT NULL,
    task_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    artifact_manifest_id uuid NOT NULL,
    artifact_manifest_hash text NOT NULL CHECK (
        artifact_manifest_hash ~ '^[0-9a-f]{64}$'
    ),
    artifact_content_hash text NOT NULL CHECK (
        artifact_content_hash ~ '^[0-9a-f]{64}$'
    ),
    governance_policy_hash text NOT NULL CHECK (
        governance_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    capture_session_id uuid NOT NULL,
    status text NOT NULL CHECK (status IN (
        'submitted', 'approved', 'rejected', 'committed'
    )),
    submitted_by text NOT NULL CHECK (btrim(submitted_by) <> ''),
    reviewed_by text,
    aggregate_version integer NOT NULL CHECK (aggregate_version > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    submitted_at timestamptz NOT NULL,
    reviewed_at timestamptz,
    committed_at timestamptz,
    UNIQUE (id, project_id),
    UNIQUE (project_id, attempt_id),
    FOREIGN KEY (run_id, project_id)
        REFERENCES workflow_c_sampling_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, project_id)
        REFERENCES workflow_c_sampling_tasks(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (attempt_id, project_id)
        REFERENCES workflow_c_sampling_attempts(id, project_id) ON DELETE CASCADE,
    CHECK (
        (status = 'submitted' AND reviewed_by IS NULL AND reviewed_at IS NULL
            AND committed_at IS NULL)
        OR (status IN ('approved', 'rejected') AND reviewed_by IS NOT NULL
            AND reviewed_at IS NOT NULL AND committed_at IS NULL)
        OR (status = 'committed' AND reviewed_by IS NOT NULL
            AND reviewed_at IS NOT NULL AND committed_at IS NOT NULL)
    ),
    CHECK (reviewed_by IS NULL OR reviewed_by <> submitted_by)
);

CREATE TABLE workflow_c_command_ledger (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    command_scope text NOT NULL CHECK (btrim(command_scope) <> ''),
    aggregate_id uuid NOT NULL,
    idempotency_key_hash text NOT NULL CHECK (
        idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
    result_type text NOT NULL CHECK (btrim(result_type) <> ''),
    result_id uuid NOT NULL,
    result_version integer NOT NULL CHECK (result_version > 0),
    result_payload jsonb NOT NULL CHECK (jsonb_typeof(result_payload) = 'object'),
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, command_scope, aggregate_id, idempotency_key_hash)
);

CREATE TABLE workflow_c_semantic_metric_snapshots (
    snapshot_hash text PRIMARY KEY CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid NOT NULL,
    input_set_hash text NOT NULL CHECK (input_set_hash ~ '^[0-9a-f]{64}$'),
    metric_suite_hash text NOT NULL CHECK (metric_suite_hash ~ '^[0-9a-f]{64}$'),
    source_stratum_hash text NOT NULL CHECK (source_stratum_hash ~ '^[0-9a-f]{64}$'),
    capture_method text NOT NULL CHECK (capture_method IN (
        'provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui'
    )),
    evidence_status text NOT NULL CHECK (
        evidence_status IN ('complete', 'insufficient_evidence')
    ),
    warning_ratio numeric(9, 8) NOT NULL CHECK (warning_ratio BETWEEN 0 AND 1),
    test_only boolean NOT NULL DEFAULT false,
    synthetic boolean NOT NULL DEFAULT false,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    computed_at timestamptz NOT NULL,
    approved_at timestamptz,
    UNIQUE (snapshot_hash, project_id),
    FOREIGN KEY (run_id, project_id)
        REFERENCES workflow_c_sampling_runs(id, project_id) ON DELETE CASCADE,
    CHECK (approved_at IS NULL OR approved_at >= computed_at),
    CHECK (approved_at IS NULL OR (NOT test_only AND NOT synthetic))
);

CREATE TABLE workflow_c_semantic_metric_results (
    snapshot_hash text NOT NULL,
    metric_key text NOT NULL CHECK (btrim(metric_key) <> ''),
    metric_version text NOT NULL CHECK (btrim(metric_version) <> ''),
    status text NOT NULL CHECK (status IN (
        'complete', 'invalid', 'insufficient_evidence'
    )),
    estimate numeric,
    interval_json jsonb CHECK (
        interval_json IS NULL OR jsonb_typeof(interval_json) = 'object'
    ),
    denominator integer NOT NULL CHECK (denominator >= 0),
    valid_count integer NOT NULL CHECK (valid_count >= 0),
    invalid_count integer NOT NULL CHECK (invalid_count >= 0),
    missing_count integer NOT NULL CHECK (missing_count >= 0),
    judge_version_hash text CHECK (
        judge_version_hash IS NULL OR judge_version_hash ~ '^[0-9a-f]{64}$'
    ),
    rule_versions_hash text NOT NULL CHECK (rule_versions_hash ~ '^[0-9a-f]{64}$'),
    evidence_locators_json jsonb NOT NULL CHECK (
        jsonb_typeof(evidence_locators_json) = 'array'
    ),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (snapshot_hash, metric_key),
    FOREIGN KEY (snapshot_hash)
        REFERENCES workflow_c_semantic_metric_snapshots(snapshot_hash) ON DELETE CASCADE,
    CHECK (valid_count + invalid_count + missing_count = denominator),
    CHECK ((status = 'complete') = (estimate IS NOT NULL))
);

CREATE TABLE workflow_c_metric_judge_batches (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_job_id uuid NOT NULL,
    run_id uuid NOT NULL,
    observation_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal > 0),
    planned_batch_count integer NOT NULL CHECK (planned_batch_count > 0),
    plans_hash text NOT NULL CHECK (plans_hash ~ '^[0-9a-f]{64}$'),
    parent_input_hash text NOT NULL CHECK (parent_input_hash ~ '^[0-9a-f]{64}$'),
    input_set_hash text NOT NULL CHECK (input_set_hash ~ '^[0-9a-f]{64}$'),
    metric_suite_hash text NOT NULL CHECK (metric_suite_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN (
        'queued', 'running', 'completed', 'failed', 'cancelled'
    )),
    selected_candidate_id uuid,
    selected_output_hash text CHECK (
        selected_output_hash IS NULL OR selected_output_hash ~ '^[0-9a-f]{64}$'
    ),
    arbiter_child_job_id uuid,
    aggregate_version integer NOT NULL CHECK (aggregate_version > 0),
    created_at timestamptz NOT NULL,
    completed_at timestamptz,
    UNIQUE (id, project_id),
    -- A semantic-metrics parent can process many observations.  The replay
    -- identity is therefore one batch per parent/observation, not one batch
    -- per parent Job.
    UNIQUE (project_id, parent_job_id, observation_id, ordinal),
    FOREIGN KEY (parent_job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, project_id)
        REFERENCES workflow_c_sampling_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (observation_id, project_id)
        REFERENCES workflow_c_sampling_observations(id, project_id),
    CHECK ((status = 'completed') = (
        selected_candidate_id IS NOT NULL AND selected_output_hash IS NOT NULL
            AND completed_at IS NOT NULL
    )),
    CHECK (status NOT IN ('failed', 'cancelled') OR completed_at IS NOT NULL)
);

CREATE TABLE workflow_c_metric_model_children (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parent_job_id uuid NOT NULL,
    child_job_id uuid NOT NULL,
    batch_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('metric_judge', 'arbiter')),
    ordinal integer NOT NULL CHECK (ordinal > 0),
    evaluator_id text NOT NULL CHECK (btrim(evaluator_id) <> ''),
    candidate_id uuid NOT NULL,
    parent_input_hash text NOT NULL CHECK (parent_input_hash ~ '^[0-9a-f]{64}$'),
    runtime_selection_id uuid NOT NULL,
    runtime_manifest_id uuid NOT NULL,
    runtime_manifest_hash text NOT NULL CHECK (runtime_manifest_hash ~ '^[0-9a-f]{64}$'),
    runtime_option_id uuid NOT NULL,
    runtime_option_hash text NOT NULL CHECK (runtime_option_hash ~ '^[0-9a-f]{64}$'),
    prompt_binding_id uuid NOT NULL,
    prompt_binding_version integer NOT NULL CHECK (prompt_binding_version > 0),
    prompt_frozen_state_id uuid NOT NULL,
    prompt_state_version integer NOT NULL CHECK (prompt_state_version > 0),
    prompt_release_id uuid NOT NULL,
    prompt_release_version integer NOT NULL CHECK (prompt_release_version > 0),
    prompt_release_hash text NOT NULL CHECK (prompt_release_hash ~ '^[0-9a-f]{64}$'),
    prompt_purpose text NOT NULL CHECK (btrim(prompt_purpose) <> ''),
    prompt_bundle_hash text NOT NULL CHECK (prompt_bundle_hash ~ '^[0-9a-f]{64}$'),
    portable_output_schema_hash text NOT NULL CHECK (
        portable_output_schema_hash ~ '^[0-9a-f]{64}$'
    ),
    application_output_schema_hash text NOT NULL CHECK (
        application_output_schema_hash ~ '^[0-9a-f]{64}$'
    ),
    task_ciphertext bytea NOT NULL CHECK (octet_length(task_ciphertext) > 0),
    task_data_nonce bytea NOT NULL CHECK (octet_length(task_data_nonce) = 12),
    task_wrapped_data_key bytea NOT NULL CHECK (octet_length(task_wrapped_data_key) > 0),
    task_wrap_nonce bytea NOT NULL CHECK (octet_length(task_wrap_nonce) = 12),
    task_master_key_version integer NOT NULL CHECK (task_master_key_version > 0),
    task_algorithm text NOT NULL CHECK (task_algorithm = 'AES-256-GCM'),
    task_hash text NOT NULL CHECK (task_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled'
    )),
    model_attempt_id uuid,
    output_hash text CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
    error_code text CHECK (
        error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_.:-]{0,99}$'
    ),
    created_at timestamptz NOT NULL,
    completed_at timestamptz,
    PRIMARY KEY (project_id, child_job_id),
    UNIQUE (child_job_id, project_id),
    -- Ordinals are local to a metric batch.  Keeping parent_job_id here would
    -- make the second observation of a parent collide with the first.
    UNIQUE (project_id, batch_id, role, ordinal),
    FOREIGN KEY (parent_job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (child_job_id, project_id)
        REFERENCES durable_jobs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (batch_id, project_id)
        REFERENCES workflow_c_metric_judge_batches(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (prompt_binding_id, project_id)
        REFERENCES prompt_program_bindings(id, project_id),
    FOREIGN KEY (prompt_release_id, project_id, prompt_release_hash)
        REFERENCES prompt_program_releases(id, project_id, release_hash),
    FOREIGN KEY (prompt_frozen_state_id, project_id, prompt_release_id,
                 prompt_release_hash, prompt_state_version)
        REFERENCES prompt_program_release_states(
            id, project_id, release_id, release_hash, version
        ),
    FOREIGN KEY (runtime_manifest_id, project_id, runtime_manifest_hash)
        REFERENCES model_gateway_runtime_manifests(id, project_id, manifest_hash),
    FOREIGN KEY (runtime_option_id, project_id, runtime_manifest_id, runtime_option_hash)
        REFERENCES model_gateway_runtime_options(id, project_id, manifest_id, option_hash),
    CHECK ((status IN ('succeeded', 'failed', 'cancelled')) = (completed_at IS NOT NULL)),
    CHECK ((status = 'succeeded') = (model_attempt_id IS NOT NULL AND output_hash IS NOT NULL)),
    CHECK (status <> 'failed' OR error_code IS NOT NULL),
    CHECK (runtime_selection_id = runtime_option_id)
);

CREATE TABLE workflow_c_comparison_families (
    family_hash text PRIMARY KEY CHECK (family_hash ~ '^[0-9a-f]{64}$'),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    protocol_hash text NOT NULL CHECK (protocol_hash ~ '^[0-9a-f]{64}$'),
    power_plan_hash text NOT NULL CHECK (power_plan_hash ~ '^[0-9a-f]{64}$'),
    bootstrap_method text NOT NULL CHECK (btrim(bootstrap_method) <> ''),
    bootstrap_iterations integer NOT NULL CHECK (bootstrap_iterations >= 100),
    correction_method text NOT NULL CHECK (btrim(correction_method) <> ''),
    simultaneous_interval_method text NOT NULL CHECK (
        btrim(simultaneous_interval_method) <> ''
    ),
    status text NOT NULL CHECK (status IN ('complete', 'insufficient_evidence')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    computed_at timestamptz NOT NULL,
    UNIQUE (family_hash, project_id)
);

CREATE TABLE workflow_c_comparison_results (
    family_hash text NOT NULL,
    comparison_id text NOT NULL CHECK (btrim(comparison_id) <> ''),
    stratum_hash text NOT NULL CHECK (stratum_hash ~ '^[0-9a-f]{64}$'),
    sampling_source_stratum_hash text NOT NULL CHECK (
        sampling_source_stratum_hash ~ '^[0-9a-f]{64}$'
    ),
    conclusion text NOT NULL CHECK (conclusion IN (
        'win', 'equivalent', 'loss', 'inconclusive', 'insufficient_evidence'
    )),
    adjusted_p_value numeric NOT NULL CHECK (adjusted_p_value BETWEEN 0 AND 1),
    interval_json jsonb NOT NULL CHECK (jsonb_typeof(interval_json) = 'object'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (family_hash, comparison_id),
    FOREIGN KEY (family_hash)
        REFERENCES workflow_c_comparison_families(family_hash) ON DELETE CASCADE
);

CREATE TABLE workflow_c_drift_reports (
    report_hash text PRIMARY KEY CHECK (report_hash ~ '^[0-9a-f]{64}$'),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_snapshot_hash text NOT NULL CHECK (
        source_snapshot_hash ~ '^[0-9a-f]{64}$'
    ),
    target_snapshot_hash text NOT NULL CHECK (
        target_snapshot_hash ~ '^[0-9a-f]{64}$'
    ),
    status text NOT NULL CHECK (status IN ('complete', 'insufficient_evidence')),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    computed_at timestamptz NOT NULL,
    UNIQUE (report_hash, project_id),
    CHECK (source_snapshot_hash <> target_snapshot_hash)
);

CREATE TABLE workflow_c_monitoring_report_snapshots (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    monitoring_report_id uuid NOT NULL,
    monitoring_report_hash text NOT NULL CHECK (
        monitoring_report_hash ~ '^[0-9a-f]{64}$'
    ),
    semantic_snapshot_hash text NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN (
        'provider_api', 'proxy_grounded_api', 'manual_ui', 'automated_ui'
    )),
    approved_safe_payload jsonb NOT NULL CHECK (
        jsonb_typeof(approved_safe_payload) = 'object'
        AND NOT approved_safe_payload ?| ARRAY[
            'raw_body', 'raw_response', 'credential', 'secret',
            'artifact_uri', 'debug', 'model_reasoning'
        ]
    ),
    snapshot_hash text NOT NULL CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    approved_by uuid NOT NULL REFERENCES identities(id),
    approved_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, project_id),
    UNIQUE (project_id, monitoring_report_id, semantic_snapshot_hash),
    UNIQUE (project_id, snapshot_hash),
    FOREIGN KEY (monitoring_report_id, project_id)
        REFERENCES monitoring_reports(id, project_id),
    FOREIGN KEY (semantic_snapshot_hash, project_id)
        REFERENCES workflow_c_semantic_metric_snapshots(snapshot_hash, project_id),
    FOREIGN KEY (campaign_id, project_id)
        REFERENCES geo_campaigns(id, project_id),
    CHECK (approved_at <= created_at + interval '5 minutes')
);

CREATE TABLE workflow_c_alert_rule_versions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rule_key text NOT NULL CHECK (rule_key ~ '^[a-z][a-z0-9_.:-]{0,199}$'),
    version integer NOT NULL CHECK (version > 0),
    status text NOT NULL CHECK (status IN ('draft', 'approved', 'retired')),
    rule_hash text NOT NULL CHECK (rule_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND payload->>'kind' IN (
            'threshold', 'baseline_delta', 'negative_question',
            'completion_freshness', 'model_drift', 'source_drift',
            'connector_failure'
        )
    ),
    created_by text NOT NULL CHECK (btrim(created_by) <> ''),
    created_at timestamptz NOT NULL,
    approved_by text,
    approved_at timestamptz,
    UNIQUE (id, project_id),
    UNIQUE (project_id, rule_key, version),
    UNIQUE (project_id, rule_hash),
    CHECK ((status = 'approved') = (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
    CHECK (approved_by IS NULL OR approved_by <> created_by)
);

CREATE TABLE workflow_c_alert_schedules (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rule_version_id uuid NOT NULL,
    snapshot_selector_hash text NOT NULL CHECK (
        snapshot_selector_hash ~ '^[0-9a-f]{64}$'
    ),
    status text NOT NULL CHECK (status IN ('active', 'paused', 'retired')),
    next_run_at timestamptz NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    fencing_generation integer NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, rule_version_id, snapshot_selector_hash),
    FOREIGN KEY (rule_version_id, project_id)
        REFERENCES workflow_c_alert_rule_versions(id, project_id),
    CHECK (created_at <= updated_at),
    CHECK (
        (lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)
        OR (btrim(lease_owner) <> '' AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL)
    )
);

CREATE TABLE workflow_c_alerts (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    rule_version_id uuid NOT NULL,
    trigger_snapshot_hash text NOT NULL CHECK (
        trigger_snapshot_hash ~ '^[0-9a-f]{64}$'
    ),
    dedupe_key text NOT NULL CHECK (dedupe_key ~ '^alert:[0-9a-f]{64}$'),
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    status text NOT NULL CHECK (
        status IN ('open', 'acknowledged', 'suppressed', 'resolved')
    ),
    version integer NOT NULL CHECK (version > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    opened_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    resolved_at timestamptz,
    UNIQUE (id, project_id),
    FOREIGN KEY (rule_version_id, project_id)
        REFERENCES workflow_c_alert_rule_versions(id, project_id),
    CHECK ((status = 'resolved') = (resolved_at IS NOT NULL)),
    CHECK (opened_at <= updated_at)
);

CREATE UNIQUE INDEX workflow_c_alerts_one_active_dedupe
ON workflow_c_alerts(project_id, dedupe_key)
WHERE status <> 'resolved';

CREATE TABLE workflow_c_alert_dispositions (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    alert_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN (
        'acknowledged', 'suppressed', 'unsuppressed', 'resolved'
    )),
    command_key text NOT NULL CHECK (
        command_key ~ '^[a-z][a-z0-9_.:-]{0,199}$'
    ),
    from_status text NOT NULL CHECK (
        from_status IN ('open', 'acknowledged', 'suppressed', 'resolved')
    ),
    to_status text NOT NULL CHECK (
        to_status IN ('open', 'acknowledged', 'suppressed', 'resolved')
    ),
    resulting_version integer NOT NULL CHECK (resulting_version > 1),
    actor_id text NOT NULL CHECK (btrim(actor_id) <> ''),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    suppressed_until timestamptz,
    command_hash text NOT NULL CHECK (command_hash ~ '^[0-9a-f]{64}$'),
    occurred_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, alert_id, command_key),
    UNIQUE (project_id, alert_id, command_hash),
    FOREIGN KEY (alert_id, project_id)
        REFERENCES workflow_c_alerts(id, project_id) ON DELETE CASCADE,
    CHECK ((kind = 'suppressed') = (suppressed_until IS NOT NULL)),
    CHECK (
        (kind = 'acknowledged' AND from_status = 'open' AND to_status = 'acknowledged')
        OR (kind = 'suppressed' AND from_status IN ('open', 'acknowledged')
            AND to_status = 'suppressed')
        OR (kind = 'unsuppressed' AND from_status = 'suppressed' AND to_status = 'open')
        OR (kind = 'resolved' AND from_status IN ('open', 'acknowledged', 'suppressed')
            AND to_status = 'resolved')
    ),
    CHECK (suppressed_until IS NULL OR suppressed_until > occurred_at)
);

CREATE TABLE workflow_c_alert_notifications (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    alert_id uuid NOT NULL,
    alert_version integer NOT NULL CHECK (alert_version > 0),
    channel text NOT NULL CHECK (channel IN ('admin_inbox', 'smtp', 'webhook')),
    topic text NOT NULL CHECK (btrim(topic) <> ''),
    idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
    status text NOT NULL CHECK (status IN (
        'pending', 'leased', 'retry_wait', 'delivered', 'dead_lettered'
    )),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (
        jsonb_typeof(payload) = 'object'
        AND payload ? 'summary'
        AND jsonb_typeof(payload->'summary') = 'object'
        AND NOT payload ?| ARRAY[
            'credential', 'secret', 'raw_body', 'raw_response',
            'artifact_uri', 'debug', 'model_reasoning'
        ]
    ),
    safe_summary text NOT NULL CHECK (
        btrim(safe_summary) <> '' AND length(safe_summary) <= 1000
    ),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    fencing_generation integer NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
    next_attempt_at timestamptz NOT NULL,
    delivered_at timestamptz,
    last_error_code text CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_.:-]{0,99}$'
    ),
    created_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, idempotency_key),
    UNIQUE (project_id, alert_id, channel, payload_hash),
    FOREIGN KEY (alert_id, project_id)
        REFERENCES workflow_c_alerts(id, project_id) ON DELETE CASCADE,
    CHECK ((status = 'delivered') = (delivered_at IS NOT NULL)),
    CHECK (status <> 'retry_wait' OR last_error_code IS NOT NULL),
    CHECK (
        (status = 'leased' AND btrim(lease_owner) <> '' AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL)
        OR (status <> 'leased' AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL)
    )
);

CREATE TABLE workflow_c_artifact_master_key_versions (
    master_key_version integer PRIMARY KEY CHECK (master_key_version > 0),
    status text NOT NULL CHECK (
        status IN ('encrypt_decrypt', 'decrypt_only', 'retired')
    ),
    algorithm text NOT NULL CHECK (algorithm = 'AES-256-GCM'),
    canary_nonce bytea NOT NULL CHECK (octet_length(canary_nonce) = 12),
    canary_ciphertext bytea NOT NULL CHECK (octet_length(canary_ciphertext) > 16),
    created_at timestamptz NOT NULL,
    retired_at timestamptz,
    CHECK ((status = 'retired') = (retired_at IS NOT NULL)),
    CHECK (retired_at IS NULL OR retired_at >= created_at)
);

CREATE UNIQUE INDEX workflow_c_artifact_one_encrypt_key
ON workflow_c_artifact_master_key_versions(status)
WHERE status = 'encrypt_decrypt';

CREATE TABLE workflow_c_artifact_deks (
    key_ref uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    ciphertext bytea,
    data_nonce bytea,
    wrapped_data_key bytea,
    wrap_nonce bytea,
    master_key_version integer NOT NULL,
    algorithm text NOT NULL CHECK (algorithm = 'AES-256-GCM'),
    status text NOT NULL CHECK (status IN ('active', 'destroyed')),
    created_at timestamptz NOT NULL,
    destroyed_at timestamptz,
    UNIQUE (key_ref, project_id, artifact_id),
    UNIQUE (project_id, artifact_id),
    FOREIGN KEY (master_key_version)
        REFERENCES workflow_c_artifact_master_key_versions(master_key_version),
    CHECK (key_ref = artifact_id),
    CHECK (
        (status = 'active' AND ciphertext IS NOT NULL
            AND octet_length(ciphertext) > 0
            AND data_nonce IS NOT NULL AND octet_length(data_nonce) = 12
            AND wrapped_data_key IS NOT NULL AND octet_length(wrapped_data_key) > 0
            AND wrap_nonce IS NOT NULL AND octet_length(wrap_nonce) = 12
            AND destroyed_at IS NULL)
        OR (status = 'destroyed' AND ciphertext IS NULL AND data_nonce IS NULL
            AND wrapped_data_key IS NULL AND wrap_nonce IS NULL
            AND destroyed_at IS NOT NULL)
    )
);

ALTER TABLE workflow_c_metric_model_children
ADD CONSTRAINT workflow_c_metric_model_children_master_key_fkey
FOREIGN KEY (task_master_key_version)
REFERENCES workflow_c_artifact_master_key_versions(master_key_version);

CREATE TABLE workflow_c_manual_artifacts (
    artifact_id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id uuid NOT NULL,
    task_id uuid NOT NULL,
    capture_session_id uuid NOT NULL,
    evidence_kind text NOT NULL CHECK (btrim(evidence_kind) <> ''),
    source_content_type text NOT NULL CHECK (btrim(source_content_type) <> ''),
    persisted_content_type text NOT NULL CHECK (btrim(persisted_content_type) <> ''),
    source_content_hash text NOT NULL CHECK (source_content_hash ~ '^[0-9a-f]{64}$'),
    redacted_content_hash text NOT NULL CHECK (
        redacted_content_hash ~ '^[0-9a-f]{64}$'
    ),
    object_uri text,
    object_hash text NOT NULL CHECK (object_hash ~ '^[0-9a-f]{64}$'),
    manifest_uri text,
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    governance_policy_hash text NOT NULL CHECK (
        governance_policy_hash ~ '^[0-9a-f]{64}$'
    ),
    redactor_version_hash text NOT NULL CHECK (
        redactor_version_hash ~ '^[0-9a-f]{64}$'
    ),
    scanner_version_hash text NOT NULL CHECK (
        scanner_version_hash ~ '^[0-9a-f]{64}$'
    ),
    pii_finding_count integer NOT NULL CHECK (pii_finding_count >= 0),
    secret_finding_count integer NOT NULL CHECK (secret_finding_count >= 0),
    redaction_assurance text NOT NULL CHECK (
        redaction_assurance IN ('automated_pass', 'human_verified')
    ),
    classification text NOT NULL CHECK (
        classification = 'restricted_manual_evidence'
    ),
    audience text NOT NULL CHECK (audience = 'admin_only'),
    export_allowed boolean NOT NULL CHECK (NOT export_allowed),
    raw_retained boolean NOT NULL CHECK (NOT raw_retained),
    retention_days integer NOT NULL CHECK (retention_days BETWEEN 1 AND 365),
    expires_at timestamptz NOT NULL,
    legal_hold boolean NOT NULL DEFAULT false,
    status text NOT NULL CHECK (
        status IN ('staged', 'active', 'delete_pending', 'crypto_erased', 'tombstoned')
    ),
    key_ref uuid,
    encryption_algorithm text NOT NULL CHECK (encryption_algorithm = 'AES-256-GCM'),
    stored_byte_size bigint NOT NULL CHECK (stored_byte_size > 0),
    created_at timestamptz NOT NULL,
    activated_at timestamptz,
    tombstoned_at timestamptz,
    tombstone_reason text,
    UNIQUE (artifact_id, project_id),
    FOREIGN KEY (run_id, project_id)
        REFERENCES workflow_c_sampling_runs(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (task_id, project_id)
        REFERENCES workflow_c_sampling_tasks(id, project_id) ON DELETE CASCADE,
    FOREIGN KEY (key_ref, project_id, artifact_id)
        REFERENCES workflow_c_artifact_deks(key_ref, project_id, artifact_id),
    CHECK (expires_at = created_at + make_interval(days => retention_days)),
    CHECK (
        (status IN ('staged', 'active', 'delete_pending', 'crypto_erased')
            AND object_uri ~ '^s3://[^/]+/.+'
            AND manifest_uri ~ '^s3://[^/]+/.+'
            AND key_ref IS NOT NULL AND tombstoned_at IS NULL
            AND tombstone_reason IS NULL)
        OR (status = 'tombstoned' AND object_uri IS NULL
            AND manifest_uri IS NULL AND key_ref IS NULL
            AND tombstoned_at IS NOT NULL AND btrim(tombstone_reason) <> '')
    ),
    CHECK (
        (status = 'staged' AND activated_at IS NULL)
        OR (status = 'active' AND activated_at IS NOT NULL)
        OR status IN ('delete_pending', 'crypto_erased')
        OR status = 'tombstoned'
    )
);

ALTER TABLE workflow_c_sampling_manual_imports
ADD CONSTRAINT workflow_c_sampling_manual_imports_artifact_fkey
FOREIGN KEY (artifact_manifest_id, project_id)
REFERENCES workflow_c_manual_artifacts(artifact_id, project_id);

CREATE TABLE workflow_c_artifact_deletion_queue (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    key_ref uuid NOT NULL,
    payload_uri text NOT NULL CHECK (payload_uri ~ '^s3://[^/]+/.+'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    manifest_uri text NOT NULL CHECK (manifest_uri ~ '^s3://[^/]+/.+'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    reason text NOT NULL CHECK (reason IN (
        'staged_timeout', 'expiry', 'write_failed', 'operator_delete'
    )),
    status text NOT NULL CHECK (
        status IN ('pending', 'running', 'retry_wait', 'completed')
    ),
    lease_owner text,
    lease_token uuid,
    fencing_generation integer NOT NULL DEFAULT 0 CHECK (fencing_generation >= 0),
    lease_expires_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at timestamptz NOT NULL,
    object_deleted boolean NOT NULL DEFAULT false,
    key_destroyed boolean NOT NULL DEFAULT false,
    last_error_code text CHECK (
        last_error_code IS NULL OR last_error_code ~ '^[a-z][a-z0-9_+.-]{0,199}$'
    ),
    created_at timestamptz NOT NULL,
    completed_at timestamptz,
    UNIQUE (id, project_id),
    UNIQUE (project_id, artifact_id),
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES workflow_c_manual_artifacts(artifact_id, project_id),
    CHECK (
        (status IN ('pending', 'retry_wait') AND lease_owner IS NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NULL)
        OR (status = 'running' AND btrim(lease_owner) <> ''
            AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL
            AND completed_at IS NULL)
        OR (status = 'completed' AND lease_owner IS NULL
            AND lease_token IS NULL AND lease_expires_at IS NULL
            AND completed_at IS NOT NULL AND object_deleted AND key_destroyed)
    )
);

CREATE INDEX workflow_c_artifact_deletion_claim_idx
ON workflow_c_artifact_deletion_queue(status, next_attempt_at, lease_expires_at, id);

CREATE TABLE workflow_c_artifact_hold_requests (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    action text NOT NULL CHECK (action IN ('apply', 'release')),
    status text NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'expired')),
    requested_by text NOT NULL CHECK (btrim(requested_by) <> ''),
    requested_at timestamptz NOT NULL,
    request_reason text NOT NULL CHECK (btrim(request_reason) <> ''),
    decided_by text,
    decided_at timestamptz,
    decision_reason text,
    expected_artifact_status text NOT NULL CHECK (expected_artifact_status = 'active'),
    aggregate_version integer NOT NULL CHECK (aggregate_version > 0),
    UNIQUE (id, project_id),
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES workflow_c_manual_artifacts(artifact_id, project_id),
    CHECK (
        (status = 'pending' AND decided_by IS NULL AND decided_at IS NULL
            AND decision_reason IS NULL AND aggregate_version = 1)
        OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_at IS NOT NULL
            AND btrim(decision_reason) <> '' AND aggregate_version = 2)
    ),
    CHECK (decided_by IS NULL OR decided_by <> requested_by)
);

CREATE UNIQUE INDEX workflow_c_artifact_hold_one_pending
ON workflow_c_artifact_hold_requests(project_id, artifact_id)
WHERE status = 'pending';

CREATE TABLE workflow_c_artifact_lifecycle_events (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'staged', 'activated', 'delete_enqueued', 'deletion_claimed',
        'deletion_retry', 'crypto_erased', 'deleted',
        'hold_requested', 'hold_applied', 'hold_released',
        'hold_rejected', 'hold_expired'
    )),
    actor_id text NOT NULL CHECK (btrim(actor_id) <> ''),
    reason text NOT NULL CHECK (btrim(reason) <> ''),
    event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
    occurred_at timestamptz NOT NULL,
    UNIQUE (id, project_id),
    UNIQUE (project_id, artifact_id, event_hash),
    FOREIGN KEY (artifact_id, project_id)
        REFERENCES workflow_c_manual_artifacts(artifact_id, project_id)
);

CREATE FUNCTION geo_assert_workflow_c_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Workflow C accepted evidence is immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_versioned_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE mutable_columns text[] := TG_ARGV;
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Workflow C aggregate history cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - mutable_columns;
    new_fixed := to_jsonb(NEW) - mutable_columns;
    IF old_fixed <> new_fixed THEN
        RAISE EXCEPTION 'Workflow C aggregate immutable identity changed'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.version <> OLD.version + 1 THEN
        RAISE EXCEPTION 'Workflow C aggregate version CAS is not contiguous'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_append_workflow_c_artifact_event(
    p_project_id uuid,
    p_artifact_id uuid,
    p_event_type text,
    p_actor_id text,
    p_reason text,
    p_occurred_at timestamptz
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE event_id uuid := gen_random_uuid();
DECLARE event_digest text;
BEGIN
    event_digest := encode(digest(convert_to(geo_jsonb_canonical_text(
        jsonb_build_object(
            'project_id', p_project_id::text,
            'artifact_id', p_artifact_id::text,
            'event_type', p_event_type,
            'actor_id', p_actor_id,
            'reason', p_reason,
            'occurred_at', p_occurred_at
        )
    ), 'UTF8'), 'sha256'), 'hex');
    INSERT INTO workflow_c_artifact_lifecycle_events(
        id, project_id, artifact_id, event_type, actor_id, reason,
        event_hash, occurred_at
    ) VALUES (
        event_id, p_project_id, p_artifact_id, p_event_type, p_actor_id,
        p_reason, event_digest, p_occurred_at
    );
    RETURN event_id;
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_artifact_dek_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Workflow C artifact DEK history cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF (OLD.key_ref, OLD.project_id, OLD.artifact_id, OLD.master_key_version,
        OLD.algorithm, OLD.created_at)
       IS DISTINCT FROM
       (NEW.key_ref, NEW.project_id, NEW.artifact_id, NEW.master_key_version,
        NEW.algorithm, NEW.created_at)
       OR OLD.status <> 'active' OR NEW.status <> 'destroyed'
       OR NEW.ciphertext IS NOT NULL OR NEW.data_nonce IS NOT NULL
       OR NEW.wrapped_data_key IS NOT NULL OR NEW.wrap_nonce IS NOT NULL
       OR NEW.destroyed_at IS NULL THEN
        RAISE EXCEPTION 'Workflow C artifact DEK transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_manual_artifact_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'staged' OR NEW.legal_hold
           OR NOT EXISTS (
                SELECT 1 FROM workflow_c_artifact_deks AS dek
                WHERE dek.key_ref = NEW.key_ref
                  AND dek.project_id = NEW.project_id
                  AND dek.artifact_id = NEW.artifact_id
                  AND dek.status = 'active'
           ) THEN
            RAISE EXCEPTION 'Workflow C manual artifact must begin as a staged encrypted record'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Workflow C manual artifact lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'status', 'legal_hold', 'activated_at', 'object_uri', 'manifest_uri',
        'key_ref', 'tombstoned_at', 'tombstone_reason'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'status', 'legal_hold', 'activated_at', 'object_uri', 'manifest_uri',
        'key_ref', 'tombstoned_at', 'tombstone_reason'
    ];
    IF old_fixed <> new_fixed THEN
        RAISE EXCEPTION 'Workflow C manual artifact immutable lineage changed'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'staged' AND NEW.status = 'active'
       AND NEW.activated_at IS NOT NULL AND NOT NEW.legal_hold THEN
        PERFORM geo_append_workflow_c_artifact_event(
            NEW.project_id, NEW.artifact_id, 'activated',
            'workflow_c.artifact_writer', 'stage_committed', NEW.activated_at
        );
    ELSIF OLD.status IN ('staged', 'active') AND NEW.status = 'delete_pending'
       AND NEW.object_uri = OLD.object_uri AND NEW.manifest_uri = OLD.manifest_uri
       AND NEW.key_ref = OLD.key_ref AND NEW.legal_hold = OLD.legal_hold THEN
        NULL;
    ELSIF OLD.status = 'delete_pending' AND NEW.status = 'crypto_erased'
       AND NEW.object_uri = OLD.object_uri AND NEW.manifest_uri = OLD.manifest_uri
       AND NEW.key_ref = OLD.key_ref AND NEW.legal_hold = OLD.legal_hold THEN
        NULL;
    ELSIF OLD.status = 'crypto_erased' AND NEW.status = 'tombstoned'
       AND NEW.object_uri IS NULL AND NEW.manifest_uri IS NULL
       AND NEW.key_ref IS NULL AND NEW.tombstoned_at IS NOT NULL
       AND NEW.legal_hold = OLD.legal_hold THEN
        NULL;
    ELSIF OLD.status = 'active' AND NEW.status = 'active'
       AND NEW.legal_hold <> OLD.legal_hold THEN
        NULL;
    ELSE
        RAISE EXCEPTION 'Workflow C manual artifact lifecycle transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_deletion_queue_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Workflow C deletion queue history cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'status', 'lease_owner', 'lease_token', 'fencing_generation',
        'lease_expires_at', 'attempt_count', 'next_attempt_at',
        'object_deleted', 'key_destroyed', 'last_error_code', 'completed_at'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'status', 'lease_owner', 'lease_token', 'fencing_generation',
        'lease_expires_at', 'attempt_count', 'next_attempt_at',
        'object_deleted', 'key_destroyed', 'last_error_code', 'completed_at'
    ];
    IF old_fixed <> new_fixed THEN
        RAISE EXCEPTION 'Workflow C deletion queue immutable lineage changed'
            USING ERRCODE = '23514';
    END IF;
    IF (OLD.object_deleted AND NOT NEW.object_deleted)
       OR (OLD.key_destroyed AND NOT NEW.key_destroyed) THEN
        RAISE EXCEPTION 'Workflow C deletion evidence cannot regress'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'running' AND NEW.status = 'running' THEN
        IF NEW.fencing_generation <> OLD.fencing_generation
           OR NEW.attempt_count <> OLD.attempt_count
           OR NEW.lease_token IS DISTINCT FROM OLD.lease_token
           OR NEW.lease_owner IS DISTINCT FROM OLD.lease_owner
           OR NEW.lease_expires_at IS DISTINCT FROM OLD.lease_expires_at
           OR (NEW.key_destroyed AND NOT OLD.key_destroyed) IS NOT TRUE
           OR NEW.object_deleted <> OLD.object_deleted THEN
            RAISE EXCEPTION 'Workflow C crypto-erasure transition is invalid'
                USING ERRCODE = '40001';
        END IF;
    ELSIF NEW.status = 'running' THEN
        IF OLD.status NOT IN ('pending', 'retry_wait', 'running')
           OR NEW.fencing_generation <> OLD.fencing_generation + 1
           OR NEW.attempt_count <> OLD.attempt_count + 1
           OR NEW.lease_token IS NULL OR btrim(NEW.lease_owner) = ''
           OR NEW.lease_expires_at IS NULL THEN
            RAISE EXCEPTION 'Workflow C deletion lease transition is invalid'
                USING ERRCODE = '40001';
        END IF;
    ELSIF OLD.status = 'running' AND NEW.status IN ('retry_wait', 'completed') THEN
        IF NEW.fencing_generation <> OLD.fencing_generation
           OR NEW.attempt_count <> OLD.attempt_count
           OR NEW.lease_owner IS NOT NULL OR NEW.lease_token IS NOT NULL
           OR NEW.lease_expires_at IS NOT NULL THEN
            RAISE EXCEPTION 'Workflow C deletion outcome lost its fence'
                USING ERRCODE = '40001';
        END IF;
    ELSE
        RAISE EXCEPTION 'Workflow C deletion queue transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_record_workflow_c_artifact_insert_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM geo_append_workflow_c_artifact_event(
        NEW.project_id, NEW.artifact_id, 'staged',
        'workflow_c.artifact_writer', 'encrypted_stage', NEW.created_at
    );
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_enqueue_workflow_c_artifact_write_failure(
    p_project_id uuid,
    p_artifact_id uuid
) RETURNS TABLE (artifact_id uuid, queue_id uuid, status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE queued workflow_c_artifact_deletion_queue%ROWTYPE;
DECLARE queued_at timestamptz := clock_timestamp();
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Workflow C artifact is outside caller Project scope'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO STRICT artifact
    FROM workflow_c_manual_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
    FOR UPDATE;
    SELECT * INTO queued
    FROM workflow_c_artifact_deletion_queue
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id;
    IF FOUND THEN
        RETURN QUERY SELECT artifact.artifact_id, queued.id, queued.status;
        RETURN;
    END IF;
    IF artifact.status <> 'staged' THEN
        RAISE EXCEPTION 'Workflow C write failure target is not staged'
            USING ERRCODE = '23514';
    END IF;
    UPDATE workflow_c_manual_artifacts
    SET status = 'delete_pending'
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id;
    INSERT INTO workflow_c_artifact_deletion_queue(
        id, project_id, artifact_id, key_ref, payload_uri, payload_hash,
        manifest_uri, manifest_hash, reason, status, next_attempt_at, created_at
    ) VALUES (
        gen_random_uuid(), p_project_id, p_artifact_id, artifact.key_ref,
        artifact.object_uri, artifact.object_hash, artifact.manifest_uri,
        artifact.manifest_hash, 'write_failed', 'pending', queued_at, queued_at
    ) RETURNING * INTO queued;
    PERFORM geo_append_workflow_c_artifact_event(
        p_project_id, p_artifact_id, 'delete_enqueued',
        'workflow_c.artifact_writer', 'write_failed', queued_at
    );
    RETURN QUERY SELECT p_artifact_id, queued.id, queued.status;
END;
$$;

CREATE FUNCTION geo_enqueue_workflow_c_artifact_maintenance(
    p_now timestamptz,
    p_staged_grace_seconds integer
) RETURNS TABLE (staged_timeout_count bigint, expiry_count bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE item workflow_c_manual_artifacts%ROWTYPE;
DECLARE staged_count bigint := 0;
DECLARE expired_count bigint := 0;
DECLARE deletion_reason text;
BEGIN
    IF p_now IS NULL OR p_staged_grace_seconds < 60
       OR p_staged_grace_seconds > 86400 THEN
        RAISE EXCEPTION 'invalid Workflow C artifact maintenance input'
            USING ERRCODE = '22023';
    END IF;
    FOR item IN
        SELECT artifact.*
        FROM workflow_c_manual_artifacts AS artifact
        WHERE (
            (artifact.status = 'staged'
                AND artifact.created_at <= p_now
                    - make_interval(secs => p_staged_grace_seconds))
            OR (artifact.status = 'active' AND NOT artifact.legal_hold
                AND artifact.expires_at <= p_now)
        )
          AND NOT EXISTS (
              SELECT 1 FROM workflow_c_artifact_deletion_queue AS queued
              WHERE queued.project_id = artifact.project_id
                AND queued.artifact_id = artifact.artifact_id
          )
        ORDER BY artifact.created_at, artifact.artifact_id
        FOR UPDATE SKIP LOCKED
    LOOP
        deletion_reason := CASE item.status
            WHEN 'staged' THEN 'staged_timeout' ELSE 'expiry' END;
        UPDATE workflow_c_manual_artifacts
        SET status = 'delete_pending'
        WHERE project_id = item.project_id AND artifact_id = item.artifact_id;
        INSERT INTO workflow_c_artifact_deletion_queue(
            id, project_id, artifact_id, key_ref, payload_uri, payload_hash,
            manifest_uri, manifest_hash, reason, status, next_attempt_at, created_at
        ) VALUES (
            gen_random_uuid(), item.project_id, item.artifact_id, item.key_ref,
            item.object_uri, item.object_hash, item.manifest_uri,
            item.manifest_hash, deletion_reason, 'pending', p_now, p_now
        );
        PERFORM geo_append_workflow_c_artifact_event(
            item.project_id, item.artifact_id, 'delete_enqueued',
            'workflow_c.artifact_maintenance', deletion_reason, p_now
        );
        IF deletion_reason = 'staged_timeout' THEN
            staged_count := staged_count + 1;
        ELSE
            expired_count := expired_count + 1;
        END IF;
    END LOOP;
    RETURN QUERY SELECT staged_count, expired_count;
END;
$$;

CREATE FUNCTION geo_claim_workflow_c_artifact_deletion(
    p_worker_id text,
    p_now timestamptz,
    p_lease_seconds integer
) RETURNS TABLE (
    queue_id uuid,
    project_id uuid,
    artifact_id uuid,
    key_ref uuid,
    payload_uri text,
    payload_hash text,
    manifest_uri text,
    manifest_hash text,
    reason text,
    lease_token uuid,
    fencing_generation integer,
    attempt_count integer,
    object_deleted boolean,
    key_destroyed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate_id uuid;
DECLARE claimed workflow_c_artifact_deletion_queue%ROWTYPE;
BEGIN
    IF btrim(coalesce(p_worker_id, '')) = '' OR length(p_worker_id) > 200
       OR p_now IS NULL OR p_lease_seconds < 30 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'invalid Workflow C artifact deletion claim input'
            USING ERRCODE = '22023';
    END IF;
    SELECT queued.id INTO candidate_id
    FROM workflow_c_artifact_deletion_queue AS queued
    WHERE (
        (queued.status IN ('pending', 'retry_wait')
            AND queued.next_attempt_at <= p_now)
        OR (queued.status = 'running' AND queued.lease_expires_at <= p_now)
    )
    ORDER BY queued.next_attempt_at, queued.id
    LIMIT 1
    FOR UPDATE SKIP LOCKED;
    IF candidate_id IS NULL THEN
        RETURN;
    END IF;
    UPDATE workflow_c_artifact_deletion_queue AS queued
    SET status = 'running', lease_owner = p_worker_id,
        lease_token = gen_random_uuid(),
        lease_expires_at = p_now + make_interval(secs => p_lease_seconds),
        fencing_generation = queued.fencing_generation + 1,
        attempt_count = queued.attempt_count + 1,
        last_error_code = NULL
    WHERE queued.id = candidate_id
    RETURNING queued.* INTO claimed;
    PERFORM geo_append_workflow_c_artifact_event(
        claimed.project_id, claimed.artifact_id, 'deletion_claimed',
        p_worker_id, claimed.reason, p_now
    );
    RETURN QUERY SELECT claimed.id, claimed.project_id, claimed.artifact_id,
        claimed.key_ref, claimed.payload_uri, claimed.payload_hash,
        claimed.manifest_uri, claimed.manifest_hash, claimed.reason,
        claimed.lease_token, claimed.fencing_generation, claimed.attempt_count,
        claimed.object_deleted, claimed.key_destroyed;
END;
$$;

CREATE FUNCTION geo_crypto_erase_workflow_c_artifact_deletion(
    p_queue_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_erased_at timestamptz
) RETURNS TABLE (queue_id uuid, key_destroyed boolean, newly_destroyed boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE queued workflow_c_artifact_deletion_queue%ROWTYPE;
DECLARE dek workflow_c_artifact_deks%ROWTYPE;
BEGIN
    SELECT * INTO STRICT queued
    FROM workflow_c_artifact_deletion_queue
    WHERE id = p_queue_id
    FOR UPDATE;
    IF queued.status <> 'running'
       OR queued.lease_token IS DISTINCT FROM p_lease_token
       OR queued.fencing_generation <> p_fencing_generation
       OR queued.lease_expires_at IS NULL OR queued.lease_expires_at <= p_erased_at THEN
        RAISE EXCEPTION 'Workflow C artifact crypto-erasure lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF queued.key_destroyed THEN
        RETURN QUERY SELECT queued.id, true, false;
        RETURN;
    END IF;
    SELECT * INTO STRICT dek
    FROM workflow_c_artifact_deks
    WHERE key_ref = queued.key_ref AND project_id = queued.project_id
      AND artifact_id = queued.artifact_id
    FOR UPDATE;
    IF dek.status <> 'active' THEN
        RAISE EXCEPTION 'Workflow C artifact DEK is not active at crypto-erasure'
            USING ERRCODE = '40001';
    END IF;
    UPDATE workflow_c_artifact_deks
    SET ciphertext = NULL, data_nonce = NULL, wrapped_data_key = NULL,
        wrap_nonce = NULL, status = 'destroyed', destroyed_at = p_erased_at
    WHERE key_ref = queued.key_ref AND project_id = queued.project_id
      AND artifact_id = queued.artifact_id;
    UPDATE workflow_c_artifact_deletion_queue
    SET key_destroyed = true
    WHERE id = p_queue_id;
    UPDATE workflow_c_manual_artifacts
    SET status = 'crypto_erased'
    WHERE artifact_id = queued.artifact_id AND project_id = queued.project_id
      AND status = 'delete_pending';
    PERFORM geo_append_workflow_c_artifact_event(
        queued.project_id, queued.artifact_id, 'crypto_erased',
        'workflow_c.artifact_maintenance', 'dek_destroyed', p_erased_at
    );
    RETURN QUERY SELECT queued.id, true, true;
END;
$$;

CREATE FUNCTION geo_record_workflow_c_artifact_deletion_attempt(
    p_queue_id uuid,
    p_lease_token uuid,
    p_fencing_generation integer,
    p_object_deleted boolean,
    p_key_destroyed boolean,
    p_error_code text,
    p_attempted_at timestamptz,
    p_retry_not_before timestamptz
) RETURNS TABLE (queue_id uuid, status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE queued workflow_c_artifact_deletion_queue%ROWTYPE;
DECLARE next_status text;
BEGIN
    SELECT * INTO STRICT queued
    FROM workflow_c_artifact_deletion_queue
    WHERE id = p_queue_id
    FOR UPDATE;
    IF queued.status IN ('completed', 'retry_wait')
       AND queued.fencing_generation = p_fencing_generation
       AND queued.object_deleted = p_object_deleted
       AND queued.key_destroyed = p_key_destroyed
       AND queued.last_error_code IS NOT DISTINCT FROM p_error_code
       AND (
           (queued.status = 'completed' AND p_retry_not_before IS NULL)
           OR (queued.status = 'retry_wait'
               AND queued.next_attempt_at IS NOT DISTINCT FROM p_retry_not_before)
       ) THEN
        RETURN QUERY SELECT queued.id, queued.status;
        RETURN;
    END IF;
    IF queued.status <> 'running'
       OR queued.lease_token IS DISTINCT FROM p_lease_token
       OR queued.fencing_generation <> p_fencing_generation
       OR queued.lease_expires_at IS NULL
       OR queued.lease_expires_at <= p_attempted_at THEN
        RAISE EXCEPTION 'Workflow C artifact deletion lease was fenced'
            USING ERRCODE = '40001';
    END IF;
    IF NOT queued.key_destroyed OR NOT p_key_destroyed
       OR (queued.object_deleted AND NOT p_object_deleted) THEN
        RAISE EXCEPTION 'Workflow C artifact deletion evidence cannot regress'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM workflow_c_artifact_deks AS dek
        WHERE dek.project_id = queued.project_id
          AND dek.key_ref = queued.key_ref AND dek.status = 'destroyed'
    ) THEN
        RAISE EXCEPTION 'Workflow C artifact cannot claim crypto-erasure before DEK destruction'
            USING ERRCODE = '23514';
    END IF;
    next_status := CASE WHEN p_object_deleted AND p_key_destroyed
        THEN 'completed' ELSE 'retry_wait' END;
    IF (next_status = 'completed' AND (
            p_error_code IS NOT NULL OR p_retry_not_before IS NOT NULL))
       OR (next_status = 'retry_wait' AND (
            btrim(coalesce(p_error_code, '')) = ''
            OR p_retry_not_before IS NULL
            OR p_retry_not_before <= p_attempted_at)) THEN
        RAISE EXCEPTION 'Workflow C artifact deletion outcome is incomplete'
            USING ERRCODE = '22023';
    END IF;
    IF next_status = 'completed' THEN
        UPDATE workflow_c_manual_artifacts
        SET status = 'tombstoned', object_uri = NULL, manifest_uri = NULL,
            key_ref = NULL, tombstoned_at = p_attempted_at,
            tombstone_reason = queued.reason
        WHERE project_id = queued.project_id
          AND artifact_id = queued.artifact_id
          AND status = 'crypto_erased';
    END IF;
    UPDATE workflow_c_artifact_deletion_queue AS item
    SET status = next_status, lease_owner = NULL, lease_token = NULL,
        lease_expires_at = NULL, object_deleted = p_object_deleted,
        key_destroyed = p_key_destroyed, last_error_code = p_error_code,
        next_attempt_at = coalesce(p_retry_not_before, p_attempted_at),
        completed_at = CASE WHEN next_status = 'completed'
            THEN p_attempted_at ELSE NULL END
    WHERE item.id = p_queue_id
    RETURNING item.* INTO queued;
    PERFORM geo_append_workflow_c_artifact_event(
        queued.project_id, queued.artifact_id,
        CASE WHEN next_status = 'completed' THEN 'deleted' ELSE 'deletion_retry' END,
        coalesce(queued.lease_owner, 'workflow_c.artifact_maintenance'),
        coalesce(p_error_code, queued.reason), p_attempted_at
    );
    RETURN QUERY SELECT queued.id, queued.status;
END;
$$;

-- The queue alone cannot discover a first expiry.  These scheduling commands
-- create one project-fenced Durable Job and an outbox wake, then coalesce
-- subsequent write-failure and periodic-seed requests onto that active Job.
CREATE FUNCTION geo_schedule_workflow_c_artifact_maintenance(
    p_project_id uuid,
    p_now timestamptz
) RETURNS TABLE (job_id uuid, outbox_id uuid, inserted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE active_job durable_jobs%ROWTYPE;
DECLARE scheduled_job_id uuid;
DECLARE scheduled_outbox_id uuid;
DECLARE input_hash text;
BEGIN
    IF p_project_id IS NULL OR p_now IS NULL THEN
        RAISE EXCEPTION 'Workflow C artifact maintenance schedule input is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO active_job
    FROM durable_jobs
    WHERE project_id = p_project_id AND kind = 'workflow_c.artifact_maintenance'
      AND idempotency_key = 'workflow-c-artifact-maintenance:v1'
      AND status IN ('queued', 'running', 'finalizing', 'retry_wait')
    ORDER BY created_at DESC LIMIT 1 FOR UPDATE;
    IF FOUND THEN
        IF active_job.status IN ('queued', 'retry_wait') THEN
            UPDATE durable_jobs
            SET next_run_at = LEAST(next_run_at, p_now), updated_at = p_now
            WHERE id = active_job.id AND project_id = p_project_id;
        END IF;
        INSERT INTO broker_outbox(
            id, project_id, job_id, topic, payload, idempotency_key, available_at
        ) VALUES (
            gen_random_uuid(), p_project_id, active_job.id,
            'workflow_c.artifact_maintenance',
            jsonb_build_object('job_id', active_job.id::text,
                'project_id', p_project_id::text),
            'workflow-c-artifact-maintenance:wake:' || active_job.id::text, p_now
        ) ON CONFLICT (project_id, idempotency_key) DO NOTHING
        RETURNING id INTO scheduled_outbox_id;
        IF scheduled_outbox_id IS NULL THEN
            SELECT id INTO scheduled_outbox_id FROM broker_outbox
            WHERE project_id = p_project_id
              AND idempotency_key = 'workflow-c-artifact-maintenance:wake:'
                    || active_job.id::text;
        END IF;
        RETURN QUERY SELECT active_job.id, scheduled_outbox_id, false;
        RETURN;
    END IF;
    scheduled_job_id := gen_random_uuid();
    input_hash := encode(digest(convert_to(
        'workflow_c.artifact_maintenance:v1:' || p_project_id::text,
        'UTF8'), 'sha256'), 'hex');
    INSERT INTO durable_jobs(
        id, project_id, kind, status, priority, input_hash, idempotency_key,
        max_attempts, next_run_at, replay_nonce, created_at, updated_at
    ) VALUES (
        scheduled_job_id, p_project_id, 'workflow_c.artifact_maintenance',
        'queued', 5, input_hash, 'workflow-c-artifact-maintenance:v1', 10, p_now,
        coalesce((SELECT max(replay_nonce) + 1 FROM durable_jobs
                  WHERE project_id = p_project_id
                    AND kind = 'workflow_c.artifact_maintenance'
                    AND idempotency_key = 'workflow-c-artifact-maintenance:v1'), 0),
        p_now, p_now
    );
    INSERT INTO broker_outbox(
        id, project_id, job_id, topic, payload, idempotency_key, available_at
    ) VALUES (
        gen_random_uuid(), p_project_id, scheduled_job_id,
        'workflow_c.artifact_maintenance',
        jsonb_build_object('job_id', scheduled_job_id::text,
            'project_id', p_project_id::text),
        'workflow-c-artifact-maintenance:wake:' || scheduled_job_id::text, p_now
    ) RETURNING id INTO scheduled_outbox_id;
    RETURN QUERY SELECT scheduled_job_id, scheduled_outbox_id, true;
END;
$$;

CREATE FUNCTION geo_seed_workflow_c_artifact_maintenance(
    p_now timestamptz,
    p_staged_grace_seconds integer,
    p_limit integer
) RETURNS TABLE (project_id uuid, job_id uuid, outbox_id uuid, inserted boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate record;
BEGIN
    IF p_now IS NULL OR p_staged_grace_seconds NOT BETWEEN 60 AND 86400
       OR p_limit NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'Workflow C artifact maintenance seed input is invalid'
            USING ERRCODE = '22023';
    END IF;
    FOR candidate IN
        SELECT due.project_id
        FROM (
            SELECT artifact.project_id, min(artifact.created_at) AS due_at
            FROM workflow_c_manual_artifacts AS artifact
            WHERE (artifact.status = 'staged'
                   AND artifact.created_at <= p_now
                       - make_interval(secs => p_staged_grace_seconds))
               OR (artifact.status = 'active' AND NOT artifact.legal_hold
                   AND artifact.expires_at <= p_now)
            GROUP BY artifact.project_id
            UNION
            SELECT queued.project_id, min(queued.next_attempt_at) AS due_at
            FROM workflow_c_artifact_deletion_queue AS queued
            WHERE (queued.status IN ('pending', 'retry_wait')
                   AND queued.next_attempt_at <= p_now)
               OR (queued.status = 'running' AND queued.lease_expires_at <= p_now)
            GROUP BY queued.project_id
        ) AS due
        ORDER BY due.due_at, due.project_id
        LIMIT p_limit
    LOOP
        -- Materialize due artifacts for this Project before creating the wake.
        -- The maintenance worker claims only this Job's Project queue and must
        -- never be responsible for discovering another Project's first expiry.
        PERFORM set_config('geo.project_id', candidate.project_id::text, true);
        PERFORM set_config(
            'geo.project_ids', jsonb_build_array(candidate.project_id::text)::text, true
        );
        PERFORM * FROM geo_enqueue_workflow_c_artifact_maintenance(
            candidate.project_id, p_now, p_staged_grace_seconds
        );
        RETURN QUERY
        SELECT candidate.project_id, scheduled.job_id, scheduled.outbox_id, scheduled.inserted
        FROM geo_schedule_workflow_c_artifact_maintenance(candidate.project_id, p_now)
            AS scheduled;
    END LOOP;
END;
$$;

CREATE FUNCTION geo_enqueue_workflow_c_artifact_maintenance(
    p_project_id uuid,
    p_now timestamptz,
    p_staged_grace_seconds integer
) RETURNS TABLE (staged_timeout_count bigint, expiry_count bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE item workflow_c_manual_artifacts%ROWTYPE;
DECLARE staged_count bigint := 0;
DECLARE expired_count bigint := 0;
DECLARE deletion_reason text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Workflow C artifact maintenance is outside caller Project scope'
            USING ERRCODE = '42501';
    END IF;
    FOR item IN
        SELECT artifact.*
        FROM workflow_c_manual_artifacts AS artifact
        WHERE artifact.project_id = p_project_id
          AND ((artifact.status = 'staged'
                AND artifact.created_at <= p_now
                    - make_interval(secs => p_staged_grace_seconds))
               OR (artifact.status = 'active' AND NOT artifact.legal_hold
                   AND artifact.expires_at <= p_now))
          AND NOT EXISTS (
              SELECT 1 FROM workflow_c_artifact_deletion_queue AS queued
              WHERE queued.project_id = artifact.project_id
                AND queued.artifact_id = artifact.artifact_id
          )
        ORDER BY artifact.created_at, artifact.artifact_id
        FOR UPDATE SKIP LOCKED
    LOOP
        deletion_reason := CASE item.status
            WHEN 'staged' THEN 'staged_timeout' ELSE 'expiry' END;
        UPDATE workflow_c_manual_artifacts
        SET status = 'delete_pending'
        WHERE project_id = item.project_id AND artifact_id = item.artifact_id;
        INSERT INTO workflow_c_artifact_deletion_queue(
            id, project_id, artifact_id, key_ref, payload_uri, payload_hash,
            manifest_uri, manifest_hash, reason, status, next_attempt_at, created_at
        ) VALUES (
            gen_random_uuid(), item.project_id, item.artifact_id, item.key_ref,
            item.object_uri, item.object_hash, item.manifest_uri, item.manifest_hash,
            deletion_reason, 'pending', p_now, p_now
        );
        PERFORM geo_append_workflow_c_artifact_event(
            item.project_id, item.artifact_id, 'delete_enqueued',
            'workflow_c.artifact_maintenance', deletion_reason, p_now
        );
        IF deletion_reason = 'staged_timeout' THEN
            staged_count := staged_count + 1;
        ELSE
            expired_count := expired_count + 1;
        END IF;
    END LOOP;
    RETURN QUERY SELECT staged_count, expired_count;
END;
$$;

CREATE FUNCTION geo_claim_workflow_c_artifact_deletion(
    p_project_id uuid,
    p_worker_id text,
    p_now timestamptz,
    p_lease_seconds integer
) RETURNS TABLE (
    queue_id uuid,
    project_id uuid,
    artifact_id uuid,
    key_ref uuid,
    payload_uri text,
    payload_hash text,
    manifest_uri text,
    manifest_hash text,
    reason text,
    lease_token uuid,
    fencing_generation integer,
    attempt_count integer,
    object_deleted boolean,
    key_destroyed boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE candidate_id uuid;
DECLARE claimed workflow_c_artifact_deletion_queue%ROWTYPE;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR btrim(coalesce(p_worker_id, '')) = '' OR length(p_worker_id) > 200
       OR p_now IS NULL OR p_lease_seconds < 30 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'invalid Workflow C project-scoped deletion claim input'
            USING ERRCODE = '22023';
    END IF;
    SELECT queued.id INTO candidate_id
    FROM workflow_c_artifact_deletion_queue AS queued
    WHERE queued.project_id = p_project_id AND (
        (queued.status IN ('pending', 'retry_wait') AND queued.next_attempt_at <= p_now)
        OR (queued.status = 'running' AND queued.lease_expires_at <= p_now)
    )
    ORDER BY queued.next_attempt_at, queued.id
    LIMIT 1 FOR UPDATE SKIP LOCKED;
    IF candidate_id IS NULL THEN
        RETURN;
    END IF;
    UPDATE workflow_c_artifact_deletion_queue AS queued
    SET status = 'running', lease_owner = p_worker_id, lease_token = gen_random_uuid(),
        lease_expires_at = p_now + make_interval(secs => p_lease_seconds),
        fencing_generation = queued.fencing_generation + 1,
        attempt_count = queued.attempt_count + 1, last_error_code = NULL
    WHERE queued.id = candidate_id AND queued.project_id = p_project_id
    RETURNING queued.* INTO claimed;
    PERFORM geo_append_workflow_c_artifact_event(
        claimed.project_id, claimed.artifact_id, 'deletion_claimed',
        p_worker_id, claimed.reason, p_now
    );
    RETURN QUERY SELECT claimed.id, claimed.project_id, claimed.artifact_id,
        claimed.key_ref, claimed.payload_uri, claimed.payload_hash,
        claimed.manifest_uri, claimed.manifest_hash, claimed.reason,
        claimed.lease_token, claimed.fencing_generation, claimed.attempt_count,
        claimed.object_deleted, claimed.key_destroyed;
END;
$$;

CREATE OR REPLACE FUNCTION geo_enqueue_workflow_c_artifact_write_failure(
    p_project_id uuid,
    p_artifact_id uuid
) RETURNS TABLE (artifact_id uuid, queue_id uuid, status text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE queued workflow_c_artifact_deletion_queue%ROWTYPE;
DECLARE queued_at timestamptz := clock_timestamp();
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids()) THEN
        RAISE EXCEPTION 'Workflow C artifact is outside caller Project scope'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO STRICT artifact FROM workflow_c_manual_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id FOR UPDATE;
    SELECT * INTO queued FROM workflow_c_artifact_deletion_queue
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id;
    IF NOT FOUND THEN
        IF artifact.status <> 'staged' THEN
            RAISE EXCEPTION 'Workflow C write failure target is not staged'
                USING ERRCODE = '23514';
        END IF;
        UPDATE workflow_c_manual_artifacts SET status = 'delete_pending'
        WHERE project_id = p_project_id AND artifact_id = p_artifact_id;
        INSERT INTO workflow_c_artifact_deletion_queue(
            id, project_id, artifact_id, key_ref, payload_uri, payload_hash,
            manifest_uri, manifest_hash, reason, status, next_attempt_at, created_at
        ) VALUES (
            gen_random_uuid(), p_project_id, p_artifact_id, artifact.key_ref,
            artifact.object_uri, artifact.object_hash, artifact.manifest_uri,
            artifact.manifest_hash, 'write_failed', 'pending', queued_at, queued_at
        ) RETURNING * INTO queued;
        PERFORM geo_append_workflow_c_artifact_event(
            p_project_id, p_artifact_id, 'delete_enqueued',
            'workflow_c.artifact_writer', 'write_failed', queued_at
        );
    END IF;
    -- The scheduler call is in this same transaction: a committed failure
    -- record always has an eventual worker wakeup.
    PERFORM 1 FROM geo_schedule_workflow_c_artifact_maintenance(p_project_id, queued_at);
    RETURN QUERY SELECT p_artifact_id, queued.id, queued.status;
END;
$$;

CREATE FUNCTION geo_request_workflow_c_artifact_hold(
    p_project_id uuid,
    p_artifact_id uuid,
    p_request_id uuid,
    p_action text,
    p_actor_id text,
    p_reason text,
    p_requested_at timestamptz
) RETURNS SETOF workflow_c_artifact_hold_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE existing workflow_c_artifact_hold_requests%ROWTYPE;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR p_action NOT IN ('apply', 'release')
       OR btrim(coalesce(p_actor_id, '')) = ''
       OR btrim(coalesce(p_reason, '')) = '' OR p_requested_at IS NULL THEN
        RAISE EXCEPTION 'invalid Workflow C artifact hold request'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO existing
    FROM workflow_c_artifact_hold_requests
    WHERE project_id = p_project_id AND id = p_request_id;
    IF FOUND THEN
        IF (existing.artifact_id, existing.action, existing.requested_by,
            existing.request_reason, existing.requested_at)
           IS DISTINCT FROM
           (p_artifact_id, p_action, p_actor_id, p_reason, p_requested_at) THEN
            RAISE EXCEPTION 'Workflow C artifact hold request idempotency changed'
                USING ERRCODE = '40001';
        END IF;
        RETURN NEXT existing;
        RETURN;
    END IF;
    SELECT * INTO STRICT artifact
    FROM workflow_c_manual_artifacts
    WHERE project_id = p_project_id AND artifact_id = p_artifact_id
    FOR UPDATE;
    IF artifact.status <> 'active' OR artifact.expires_at <= p_requested_at
       OR (p_action = 'apply' AND artifact.legal_hold)
       OR (p_action = 'release' AND NOT artifact.legal_hold) THEN
        RAISE EXCEPTION 'Workflow C artifact hold target state is invalid'
            USING ERRCODE = '23514';
    END IF;
    INSERT INTO workflow_c_artifact_hold_requests(
        id, project_id, artifact_id, action, status, requested_by,
        requested_at, request_reason, expected_artifact_status, aggregate_version
    ) VALUES (
        p_request_id, p_project_id, p_artifact_id, p_action, 'pending',
        p_actor_id, p_requested_at, p_reason, 'active', 1
    ) RETURNING * INTO existing;
    PERFORM geo_append_workflow_c_artifact_event(
        p_project_id, p_artifact_id, 'hold_requested',
        p_actor_id, p_reason, p_requested_at
    );
    RETURN NEXT existing;
END;
$$;

CREATE FUNCTION geo_decide_workflow_c_artifact_hold(
    p_project_id uuid,
    p_request_id uuid,
    p_expected_version integer,
    p_actor_id text,
    p_approved boolean,
    p_reason text,
    p_decided_at timestamptz
) RETURNS SETOF workflow_c_artifact_hold_requests
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
DECLARE request_record workflow_c_artifact_hold_requests%ROWTYPE;
DECLARE artifact workflow_c_manual_artifacts%ROWTYPE;
DECLARE event_kind text;
BEGIN
    IF NOT p_project_id = ANY(geo_current_project_ids())
       OR btrim(coalesce(p_actor_id, '')) = ''
       OR btrim(coalesce(p_reason, '')) = '' OR p_decided_at IS NULL THEN
        RAISE EXCEPTION 'invalid Workflow C artifact hold decision'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO STRICT request_record
    FROM workflow_c_artifact_hold_requests
    WHERE project_id = p_project_id AND id = p_request_id
    FOR UPDATE;
    IF request_record.status <> 'pending'
       OR request_record.aggregate_version <> p_expected_version
       OR p_expected_version <> 1
       OR request_record.requested_by = p_actor_id
       OR p_decided_at < request_record.requested_at THEN
        RAISE EXCEPTION 'Workflow C artifact hold decision lost maker-checker or version CAS'
            USING ERRCODE = '40001';
    END IF;
    SELECT * INTO STRICT artifact
    FROM workflow_c_manual_artifacts
    WHERE project_id = p_project_id
      AND artifact_id = request_record.artifact_id
    FOR UPDATE;
    IF artifact.status <> request_record.expected_artifact_status
       OR (request_record.action = 'apply' AND artifact.legal_hold)
       OR (request_record.action = 'release' AND NOT artifact.legal_hold) THEN
        RAISE EXCEPTION 'Workflow C artifact hold target became stale'
            USING ERRCODE = '40001';
    END IF;
    IF p_approved THEN
        UPDATE workflow_c_manual_artifacts
        SET legal_hold = (request_record.action = 'apply')
        WHERE project_id = p_project_id AND artifact_id = request_record.artifact_id;
        event_kind := CASE request_record.action
            WHEN 'apply' THEN 'hold_applied' ELSE 'hold_released' END;
    ELSE
        event_kind := 'hold_rejected';
    END IF;
    UPDATE workflow_c_artifact_hold_requests
    SET status = CASE WHEN p_approved THEN 'approved' ELSE 'rejected' END,
        decided_by = p_actor_id, decided_at = p_decided_at,
        decision_reason = p_reason, aggregate_version = 2
    WHERE project_id = p_project_id AND id = p_request_id
    RETURNING * INTO request_record;
    PERFORM geo_append_workflow_c_artifact_event(
        p_project_id, request_record.artifact_id, event_kind,
        p_actor_id, p_reason, p_decided_at
    );
    RETURN NEXT request_record;
END;
$$;

-- The artifact rows are deliberately not mutable application state.  These
-- guards leave only the fenced maintenance transitions exposed by the
-- SECURITY DEFINER functions above.  In particular, a retry cannot put a
-- destroyed DEK back into service and a tombstone cannot regain an object URI.
CREATE FUNCTION geo_assert_workflow_c_artifact_key_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Workflow C artifact key history cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.master_key_version <> NEW.master_key_version
       OR OLD.algorithm <> NEW.algorithm
       OR OLD.canary_nonce <> NEW.canary_nonce
       OR OLD.canary_ciphertext <> NEW.canary_ciphertext
       OR OLD.created_at <> NEW.created_at
       OR OLD.retired_at IS NOT NULL
       OR (OLD.status = 'encrypt_decrypt' AND NEW.status NOT IN ('encrypt_decrypt', 'decrypt_only'))
       OR (OLD.status = 'decrypt_only' AND NEW.status NOT IN ('decrypt_only', 'retired'))
       OR (NEW.status = 'retired' AND NEW.retired_at IS NULL) THEN
        RAISE EXCEPTION 'Workflow C artifact key transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_lifecycle_event_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Workflow C artifact lifecycle events are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_assert_workflow_c_metric_child_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE old_fixed jsonb;
DECLARE new_fixed jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Workflow C metric child lineage cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    old_fixed := to_jsonb(OLD) - ARRAY[
        'status', 'model_attempt_id', 'output_hash', 'error_code', 'completed_at'
    ];
    new_fixed := to_jsonb(NEW) - ARRAY[
        'status', 'model_attempt_id', 'output_hash', 'error_code', 'completed_at'
    ];
    IF old_fixed <> new_fixed
       OR OLD.status NOT IN ('queued', 'running')
       OR (NEW.status = 'succeeded' AND (
            NEW.model_attempt_id IS NULL OR NEW.output_hash IS NULL
            OR NEW.completed_at IS NULL))
       OR (NEW.status = 'failed' AND (
            NEW.error_code IS NULL OR NEW.completed_at IS NULL))
       OR (NEW.status = 'cancelled' AND NEW.completed_at IS NULL) THEN
        RAISE EXCEPTION 'Workflow C metric child terminal transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER workflow_c_artifact_key_change_guard
BEFORE UPDATE OR DELETE ON workflow_c_artifact_master_key_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_artifact_key_change();
CREATE TRIGGER workflow_c_artifact_dek_change_guard
BEFORE UPDATE OR DELETE ON workflow_c_artifact_deks
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_artifact_dek_change();
CREATE TRIGGER workflow_c_manual_artifact_change_guard
BEFORE INSERT OR UPDATE OR DELETE ON workflow_c_manual_artifacts
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_manual_artifact_change();
CREATE TRIGGER workflow_c_manual_artifact_insert_event
AFTER INSERT ON workflow_c_manual_artifacts
FOR EACH ROW EXECUTE FUNCTION geo_record_workflow_c_artifact_insert_event();
CREATE TRIGGER workflow_c_artifact_deletion_queue_change_guard
BEFORE UPDATE OR DELETE ON workflow_c_artifact_deletion_queue
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_deletion_queue_change();
CREATE TRIGGER workflow_c_artifact_lifecycle_events_immutable
BEFORE UPDATE OR DELETE ON workflow_c_artifact_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_lifecycle_event_immutable();
CREATE TRIGGER workflow_c_metric_model_children_change_guard
BEFORE UPDATE OR DELETE ON workflow_c_metric_model_children
FOR EACH ROW EXECUTE FUNCTION geo_assert_workflow_c_metric_child_change();

-- Every project-owned projection is constrained even when a forgotten query
-- bypasses its application repository.  Key canaries are global by design and
-- are instead inaccessible to the application roles below.
DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'workflow_c_sampling_admission_policies',
        'workflow_c_sampling_admission_usage',
        'workflow_c_sampling_suites', 'workflow_c_sampling_runs',
        'workflow_c_sampling_tasks', 'workflow_c_sampling_attempts',
        'workflow_c_sampling_observations', 'workflow_c_sampling_manual_imports',
        'workflow_c_command_ledger', 'workflow_c_semantic_metric_snapshots',
        'workflow_c_metric_judge_batches', 'workflow_c_metric_model_children',
        'workflow_c_comparison_families', 'workflow_c_drift_reports',
        'workflow_c_monitoring_report_snapshots', 'workflow_c_alert_rule_versions',
        'workflow_c_alert_schedules', 'workflow_c_alerts',
        'workflow_c_alert_dispositions', 'workflow_c_alert_notifications',
        'workflow_c_artifact_deks', 'workflow_c_manual_artifacts',
        'workflow_c_artifact_deletion_queue', 'workflow_c_artifact_hold_requests',
        'workflow_c_artifact_lifecycle_events'
    ] LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' ENABLE ROW LEVEL SECURITY';
        EXECUTE 'ALTER TABLE ' || quote_ident(table_name) || ' FORCE ROW LEVEL SECURITY';
        EXECUTE 'CREATE POLICY project_scope ON ' || quote_ident(table_name)
            || ' USING (project_id = ANY(geo_current_project_ids()))'
            || ' WITH CHECK (project_id = ANY(geo_current_project_ids()))';
    END LOOP;
END;
$$;

ALTER TABLE workflow_c_semantic_metric_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_semantic_metric_results FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_semantic_metric_results
USING (EXISTS (
    SELECT 1 FROM workflow_c_semantic_metric_snapshots AS snapshot
    WHERE snapshot.snapshot_hash = workflow_c_semantic_metric_results.snapshot_hash
      AND snapshot.project_id = ANY(geo_current_project_ids())
)) WITH CHECK (EXISTS (
    SELECT 1 FROM workflow_c_semantic_metric_snapshots AS snapshot
    WHERE snapshot.snapshot_hash = workflow_c_semantic_metric_results.snapshot_hash
      AND snapshot.project_id = ANY(geo_current_project_ids())
));
ALTER TABLE workflow_c_comparison_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_c_comparison_results FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON workflow_c_comparison_results
USING (EXISTS (
    SELECT 1 FROM workflow_c_comparison_families AS family
    WHERE family.family_hash = workflow_c_comparison_results.family_hash
      AND family.project_id = ANY(geo_current_project_ids())
)) WITH CHECK (EXISTS (
    SELECT 1 FROM workflow_c_comparison_families AS family
    WHERE family.family_hash = workflow_c_comparison_results.family_hash
      AND family.project_id = ANY(geo_current_project_ids())
));

REVOKE ALL ON
    workflow_c_sampling_admission_policies, workflow_c_sampling_admission_usage,
    workflow_c_sampling_suites, workflow_c_sampling_runs, workflow_c_sampling_tasks,
    workflow_c_sampling_attempts, workflow_c_sampling_observations,
    workflow_c_sampling_manual_imports, workflow_c_command_ledger,
    workflow_c_semantic_metric_snapshots, workflow_c_semantic_metric_results,
    workflow_c_metric_judge_batches, workflow_c_metric_model_children,
    workflow_c_comparison_families, workflow_c_comparison_results,
    workflow_c_drift_reports, workflow_c_monitoring_report_snapshots,
    workflow_c_alert_rule_versions, workflow_c_alert_schedules, workflow_c_alerts,
    workflow_c_alert_dispositions, workflow_c_alert_notifications,
    workflow_c_artifact_master_key_versions, workflow_c_artifact_deks,
    workflow_c_manual_artifacts, workflow_c_artifact_deletion_queue,
    workflow_c_artifact_hold_requests, workflow_c_artifact_lifecycle_events
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

GRANT SELECT, INSERT ON
    workflow_c_sampling_admission_policies, workflow_c_sampling_admission_usage,
    workflow_c_sampling_suites, workflow_c_sampling_runs, workflow_c_sampling_tasks,
    workflow_c_sampling_attempts, workflow_c_sampling_observations,
    workflow_c_sampling_manual_imports, workflow_c_command_ledger,
    workflow_c_semantic_metric_snapshots, workflow_c_semantic_metric_results,
    workflow_c_metric_judge_batches, workflow_c_metric_model_children,
    workflow_c_comparison_families, workflow_c_comparison_results,
    workflow_c_drift_reports, workflow_c_monitoring_report_snapshots,
    workflow_c_alert_rule_versions, workflow_c_alert_schedules, workflow_c_alerts,
    workflow_c_alert_dispositions, workflow_c_alert_notifications,
    workflow_c_artifact_deks, workflow_c_manual_artifacts,
    workflow_c_artifact_hold_requests, workflow_c_artifact_lifecycle_events
TO geo_app;
GRANT SELECT ON
    workflow_c_sampling_admission_policies, workflow_c_sampling_admission_usage,
    workflow_c_sampling_suites, workflow_c_sampling_runs, workflow_c_sampling_tasks,
    workflow_c_sampling_attempts, workflow_c_sampling_observations,
    workflow_c_sampling_manual_imports, workflow_c_command_ledger,
    workflow_c_semantic_metric_snapshots, workflow_c_semantic_metric_results,
    workflow_c_metric_judge_batches, workflow_c_metric_model_children,
    workflow_c_comparison_families, workflow_c_comparison_results,
    workflow_c_drift_reports, workflow_c_monitoring_report_snapshots,
    workflow_c_alert_rule_versions, workflow_c_alert_schedules, workflow_c_alerts,
    workflow_c_alert_dispositions, workflow_c_alert_notifications,
    workflow_c_artifact_master_key_versions, workflow_c_artifact_deks,
    workflow_c_manual_artifacts, workflow_c_artifact_deletion_queue,
    workflow_c_artifact_hold_requests, workflow_c_artifact_lifecycle_events
TO geo_worker;

REVOKE ALL ON FUNCTION
    geo_assert_workflow_c_immutable(), geo_assert_workflow_c_versioned_change(),
    geo_append_workflow_c_artifact_event(uuid, uuid, text, text, text, timestamptz),
    geo_assert_workflow_c_artifact_key_change(),
    geo_assert_workflow_c_artifact_dek_change(),
    geo_assert_workflow_c_manual_artifact_change(),
    geo_assert_workflow_c_deletion_queue_change(),
    geo_record_workflow_c_artifact_insert_event(),
    geo_enqueue_workflow_c_artifact_write_failure(uuid, uuid),
    geo_enqueue_workflow_c_artifact_maintenance(timestamptz, integer),
    geo_claim_workflow_c_artifact_deletion(text, timestamptz, integer),
    geo_record_workflow_c_artifact_deletion_attempt(
        uuid, uuid, integer, boolean, boolean, text, timestamptz, timestamptz
    ),
    geo_request_workflow_c_artifact_hold(
        uuid, uuid, uuid, text, text, text, timestamptz
    ),
    geo_decide_workflow_c_artifact_hold(
        uuid, uuid, integer, text, boolean, text, timestamptz
    ),
    geo_assert_workflow_c_lifecycle_event_immutable(),
    geo_assert_workflow_c_metric_child_change()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

GRANT EXECUTE ON FUNCTION
    geo_request_workflow_c_artifact_hold(
        uuid, uuid, uuid, text, text, text, timestamptz
    ),
    geo_decide_workflow_c_artifact_hold(
        uuid, uuid, integer, text, boolean, text, timestamptz
    ) TO geo_app;
GRANT EXECUTE ON FUNCTION
    geo_enqueue_workflow_c_artifact_write_failure(uuid, uuid),
    geo_enqueue_workflow_c_artifact_maintenance(timestamptz, integer),
    geo_claim_workflow_c_artifact_deletion(text, timestamptz, integer),
    geo_record_workflow_c_artifact_deletion_attempt(
        uuid, uuid, integer, boolean, boolean, text, timestamptz, timestamptz
    ) TO geo_worker;

-- Replace the legacy global maintenance entry points with project-fenced
-- operations.  Only the periodic seeder may enumerate projects.
REVOKE ALL ON FUNCTION
    geo_enqueue_workflow_c_artifact_maintenance(timestamptz, integer),
    geo_claim_workflow_c_artifact_deletion(text, timestamptz, integer)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON FUNCTION
    geo_schedule_workflow_c_artifact_maintenance(uuid, timestamptz),
    geo_seed_workflow_c_artifact_maintenance(timestamptz, integer, integer),
    geo_enqueue_workflow_c_artifact_maintenance(uuid, timestamptz, integer),
    geo_claim_workflow_c_artifact_deletion(uuid, text, timestamptz, integer),
    geo_crypto_erase_workflow_c_artifact_deletion(uuid, uuid, integer, timestamptz)
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_schedule_workflow_c_artifact_maintenance(uuid, timestamptz),
    geo_seed_workflow_c_artifact_maintenance(timestamptz, integer, integer),
    geo_enqueue_workflow_c_artifact_maintenance(uuid, timestamptz, integer),
    geo_claim_workflow_c_artifact_deletion(uuid, text, timestamptz, integer),
    geo_crypto_erase_workflow_c_artifact_deletion(uuid, uuid, integer, timestamptz)
TO geo_worker;

ALTER TABLE runtime_service_heartbeats
DROP CONSTRAINT runtime_service_heartbeats_service_type_check;
ALTER TABLE runtime_service_heartbeats
ADD CONSTRAINT runtime_service_heartbeats_service_type_check CHECK (
    service_type IN (
        'task_worker', 'outbox_relay', 'style_browser_worker',
        'workflow_c_maintenance_worker', 'workflow_c_maintenance_scheduler'
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
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Workflow C heartbeat contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
    function_definition := pg_get_functiondef(
        'geo_worker_runtime_findings(text,text,integer,integer,integer,integer,integer,integer)'
            ::regprocedure
    );
    replacement := replace(
        function_definition,
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'')',
        'p_service_type NOT IN (''task_worker'', ''outbox_relay'', ''style_browser_worker'', ''synthetic_artifact_maintenance_worker'', ''workflow_c_maintenance_worker'', ''workflow_c_maintenance_scheduler'')'
    );
    IF replacement = function_definition THEN
        RAISE EXCEPTION 'Workflow C runtime findings contract changed'
            USING ERRCODE = '55000';
    END IF;
    EXECUTE replacement;
END;
$$;

COMMENT ON TABLE workflow_c_manual_artifacts IS
    'Admin-only redacted Workflow C evidence. Payloads are encrypted object-store data, never database text.';
COMMENT ON TABLE workflow_c_artifact_deletion_queue IS
    'Fenced, retryable Workflow C artifact deletion; DEK destruction precedes object deletion.';
COMMENT ON COLUMN workflow_c_metric_model_children.portable_output_schema_hash IS
    'Provider-portable structured-output Schema hash frozen before the metric child is admitted.';
COMMENT ON COLUMN workflow_c_metric_model_children.application_output_schema_hash IS
    'Full application validation Schema hash frozen independently from the provider contract.';
