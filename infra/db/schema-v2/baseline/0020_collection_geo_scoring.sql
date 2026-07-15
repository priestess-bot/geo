-- Schema v2 B2 collection, GEO analysis, scoring, action, and retest baseline.
-- Fresh-install only: no Schema v1 compatibility or data migration is provided.
-- Monitoring queries describe stable observation targets. They are not prompt
-- templates and must never be used as a prompt-rule source of truth.

DO $job_roles$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'geo_v2_worker',
        'geo_v2_job_owner',
        'geo_v2_result_owner',
        'geo_v2_job_command_owner',
        'geo_v2_worker_login'
    ]
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = role_name
        ) THEN
            EXECUTE format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOINHERIT NOREPLICATION NOBYPASSRLS',
                role_name
            );
        ELSE
            EXECUTE format(
                'ALTER ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOINHERIT NOREPLICATION NOBYPASSRLS',
                role_name
            );
        END IF;
    END LOOP;
    ALTER ROLE geo_v2_job_owner BYPASSRLS;
    ALTER ROLE geo_v2_result_owner BYPASSRLS;
    ALTER ROLE geo_v2_job_command_owner BYPASSRLS;
    ALTER ROLE geo_v2_worker_login PASSWORD NULL;
    ALTER ROLE geo_v2_worker_login RESET ALL;
    ALTER ROLE geo_v2_worker_login IN DATABASE geo_v2 RESET ALL;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        WHERE (
                granted_role.rolname = ANY(ARRAY[
                'geo_v2_worker', 'geo_v2_job_owner',
                'geo_v2_result_owner', 'geo_v2_job_command_owner',
                'geo_v2_worker_login'
                ])
                OR member_role.rolname = ANY(ARRAY[
                'geo_v2_worker', 'geo_v2_job_owner',
                'geo_v2_result_owner', 'geo_v2_job_command_owner',
                'geo_v2_worker_login'
                ])
              )
          AND NOT (
                granted_role.rolname = 'geo_v2_worker'
                AND member_role.rolname = 'geo_v2_worker_login'
                AND NOT membership.admin_option
                AND NOT membership.inherit_option
                AND membership.set_option
          )
    ) THEN
        RAISE EXCEPTION 'Schema v2 job roles must have no role memberships';
    END IF;
END;
$job_roles$;

GRANT geo_v2_worker TO geo_v2_worker_login
    WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;
GRANT CONNECT ON DATABASE geo_v2 TO geo_v2_worker_login;

GRANT USAGE ON SCHEMA public TO geo_v2_worker;
GRANT USAGE ON SCHEMA public TO geo_v2_job_owner;
GRANT USAGE ON SCHEMA public TO geo_v2_result_owner;
GRANT USAGE ON SCHEMA public TO geo_v2_job_command_owner;

CREATE TABLE product_entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    entity_kind text NOT NULL,
    canonical_name text NOT NULL,
    parent_entity_id uuid,
    canonical_url text,
    status text NOT NULL DEFAULT 'active',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT product_entities_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT product_entities_parent_project_fkey
        FOREIGN KEY (parent_entity_id, project_id)
        REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT product_entities_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT product_entities_kind_canonical CHECK (entity_kind IN (
        'brand', 'organization', 'product', 'competitor', 'market', 'category'
    )),
    CONSTRAINT product_entities_name_nonempty CHECK (btrim(canonical_name) <> ''),
    CONSTRAINT product_entities_parent_not_self
        CHECK (parent_entity_id IS NULL OR parent_entity_id <> id),
    CONSTRAINT product_entities_url_nonempty
        CHECK (canonical_url IS NULL OR btrim(canonical_url) <> ''),
    CONSTRAINT product_entities_status_canonical
        CHECK (status IN ('active', 'inactive', 'archived')),
    CONSTRAINT product_entities_metadata_object CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT product_entities_actors_nonempty
        CHECK (btrim(created_by) <> '' AND btrim(updated_by) <> ''),
    CONSTRAINT product_entities_update_order CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX product_entities_canonical_name_unique
    ON product_entities (project_id, entity_kind, lower(btrim(canonical_name)));

CREATE TABLE product_entity_aliases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    alias text NOT NULL,
    alias_type text NOT NULL,
    language_code text NOT NULL,
    source_type text NOT NULL,
    confidence numeric(6,5) NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    reviewed_by text,
    reviewed_at timestamptz,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT product_entity_aliases_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT product_entity_aliases_entity_project_fkey
        FOREIGN KEY (entity_id, project_id) REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT product_entity_aliases_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT product_entity_aliases_type_canonical CHECK (alias_type IN (
        'official', 'trade_name', 'product_name', 'common', 'acronym', 'misspelling'
    )),
    CONSTRAINT product_entity_aliases_language_nonempty
        CHECK (btrim(language_code) <> ''),
    CONSTRAINT product_entity_aliases_source_canonical
        CHECK (source_type IN ('manual', 'observed', 'imported')),
    CONSTRAINT product_entity_aliases_confidence_range
        CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT product_entity_aliases_status_canonical
        CHECK (status IN ('pending', 'approved', 'rejected')),
    CONSTRAINT product_entity_aliases_review_coherent CHECK (
        (status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL)
        OR (status IN ('approved', 'rejected')
            AND reviewed_by IS NOT NULL AND btrim(reviewed_by) <> ''
            AND reviewed_at IS NOT NULL)
    ),
    CONSTRAINT product_entity_aliases_alias_nonempty CHECK (btrim(alias) <> ''),
    CONSTRAINT product_entity_aliases_created_by_nonempty CHECK (btrim(created_by) <> ''),
    CONSTRAINT product_entity_aliases_update_order CHECK (updated_at >= created_at)
);

CREATE UNIQUE INDEX product_entity_aliases_value_unique
    ON product_entity_aliases (
        project_id, entity_id, alias_type, language_code, lower(btrim(alias))
    );

CREATE TABLE monitoring_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    query_text text NOT NULL,
    query_hash text NOT NULL,
    observation_objective text NOT NULL,
    intent_type text NOT NULL,
    market_code text NOT NULL,
    city text,
    language_code text NOT NULL,
    device_class text NOT NULL,
    query_version integer NOT NULL DEFAULT 1,
    priority integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'active',
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT monitoring_queries_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT monitoring_queries_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT monitoring_queries_text_nonempty CHECK (btrim(query_text) <> ''),
    CONSTRAINT monitoring_queries_hash_sha256 CHECK (query_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT monitoring_queries_objective_canonical CHECK (
        observation_objective IN (
            'discovery', 'comparison', 'recommendation', 'validation',
            'reputation', 'source_discovery'
        )
    ),
    CONSTRAINT monitoring_queries_intent_canonical CHECK (
        intent_type IN ('informational', 'commercial', 'navigational', 'transactional')
    ),
    CONSTRAINT monitoring_queries_locale_nonempty CHECK (
        btrim(market_code) <> '' AND btrim(language_code) <> ''
        AND (city IS NULL OR btrim(city) <> '')
    ),
    CONSTRAINT monitoring_queries_device_canonical
        CHECK (device_class IN ('desktop', 'mobile', 'tablet', 'unspecified')),
    CONSTRAINT monitoring_queries_version_positive CHECK (query_version > 0),
    CONSTRAINT monitoring_queries_priority_range CHECK (priority BETWEEN -1000 AND 1000),
    CONSTRAINT monitoring_queries_status_canonical
        CHECK (status IN ('active', 'paused', 'archived')),
    CONSTRAINT monitoring_queries_actors_nonempty
        CHECK (btrim(created_by) <> '' AND btrim(updated_by) <> ''),
    CONSTRAINT monitoring_queries_update_order CHECK (updated_at >= created_at),
    CONSTRAINT monitoring_queries_project_hash_version_unique
        UNIQUE (project_id, query_hash, query_version)
);

CREATE TABLE monitoring_query_entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    subject_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT monitoring_query_entities_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT monitoring_query_entities_query_project_fkey
        FOREIGN KEY (monitoring_query_id, project_id)
        REFERENCES monitoring_queries(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT monitoring_query_entities_entity_project_fkey
        FOREIGN KEY (entity_id, project_id) REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT monitoring_query_entities_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT monitoring_query_entities_role_canonical CHECK (subject_role IN (
        'primary_subject', 'compared_subject', 'allowed_subject', 'mentioned_subject'
    )),
    CONSTRAINT monitoring_query_entities_relation_unique
        UNIQUE (project_id, monitoring_query_id, entity_id, subject_role)
);

CREATE TABLE collection_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'created',
    idempotency_key text NOT NULL,
    requested_by text NOT NULL,
    collection_method_version text NOT NULL,
    methodology_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    expected_job_count integer NOT NULL DEFAULT 0,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT collection_runs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_runs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT collection_runs_status_canonical CHECK (status IN (
        'created', 'queued', 'running', 'succeeded', 'partial_succeeded',
        'failed', 'cancelled'
    )),
    CONSTRAINT collection_runs_idempotency_nonempty CHECK (btrim(idempotency_key) <> ''),
    CONSTRAINT collection_runs_requested_by_nonempty CHECK (btrim(requested_by) <> ''),
    CONSTRAINT collection_runs_method_nonempty
        CHECK (btrim(collection_method_version) <> ''),
    CONSTRAINT collection_runs_methodology_object
        CHECK (jsonb_typeof(methodology_snapshot) = 'object'),
    CONSTRAINT collection_runs_job_count_nonnegative CHECK (expected_job_count >= 0),
    CONSTRAINT collection_runs_time_order CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (completed_at IS NULL OR (
            started_at IS NOT NULL AND completed_at >= started_at
        ))
    ),
    CONSTRAINT collection_runs_project_idempotency_unique
        UNIQUE (project_id, idempotency_key)
);

CREATE TABLE collection_run_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    ordinal integer NOT NULL,
    sample_size integer NOT NULL,
    query_text_snapshot text NOT NULL,
    query_hash_snapshot text NOT NULL,
    market_code_snapshot text NOT NULL,
    city_snapshot text,
    language_code_snapshot text NOT NULL,
    device_class_snapshot text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT collection_run_queries_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_run_queries_run_project_fkey
        FOREIGN KEY (collection_run_id, project_id)
        REFERENCES collection_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_run_queries_query_project_fkey
        FOREIGN KEY (monitoring_query_id, project_id)
        REFERENCES monitoring_queries(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT collection_run_queries_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT collection_run_queries_ordinal_nonnegative CHECK (ordinal >= 0),
    CONSTRAINT collection_run_queries_sample_size_positive CHECK (sample_size > 0),
    CONSTRAINT collection_run_queries_text_nonempty CHECK (btrim(query_text_snapshot) <> ''),
    CONSTRAINT collection_run_queries_hash_sha256
        CHECK (query_hash_snapshot ~ '^[0-9a-f]{64}$'),
    CONSTRAINT collection_run_queries_locale_nonempty CHECK (
        btrim(market_code_snapshot) <> '' AND btrim(language_code_snapshot) <> ''
        AND (city_snapshot IS NULL OR btrim(city_snapshot) <> '')
    ),
    CONSTRAINT collection_run_queries_device_canonical CHECK (
        device_class_snapshot IN ('desktop', 'mobile', 'tablet', 'unspecified')
    ),
    CONSTRAINT collection_run_queries_run_query_project_unique
        UNIQUE (collection_run_id, monitoring_query_id, project_id),
    CONSTRAINT collection_run_queries_run_ordinal_unique
        UNIQUE (collection_run_id, ordinal)
);

CREATE TABLE collection_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    platform text NOT NULL,
    surface text NOT NULL,
    access_method text NOT NULL,
    sample_index integer NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    idempotency_key text NOT NULL,
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
    started_at timestamptz,
    completed_at timestamptz,
    completed_by text,
    cancel_requested_at timestamptz,
    cancel_requested_by text,
    cancel_reason text,
    last_error_code text,
    last_error_message text,
    result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT collection_jobs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_jobs_run_query_project_fkey
        FOREIGN KEY (collection_run_id, monitoring_query_id, project_id)
        REFERENCES collection_run_queries(collection_run_id, monitoring_query_id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_jobs_parent_project_fkey
        FOREIGN KEY (parent_job_id, project_id)
        REFERENCES collection_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT collection_jobs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT collection_jobs_id_run_query_project_unique
        UNIQUE (id, collection_run_id, monitoring_query_id, project_id),
    CONSTRAINT collection_jobs_target_nonempty CHECK (
        btrim(platform) <> '' AND btrim(surface) <> '' AND btrim(access_method) <> ''
    ),
    CONSTRAINT collection_jobs_sample_index_positive CHECK (sample_index > 0),
    CONSTRAINT collection_jobs_status_canonical CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled', 'dead_lettered'
    )),
    CONSTRAINT collection_jobs_idempotency_nonempty CHECK (btrim(idempotency_key) <> ''),
    CONSTRAINT collection_jobs_replay_lineage CHECK (
        (parent_job_id IS NULL AND replay_nonce = 0)
        OR (parent_job_id IS NOT NULL AND parent_job_id <> id AND replay_nonce > 0)
    ),
    CONSTRAINT collection_jobs_priority_range CHECK (priority BETWEEN -1000 AND 1000),
    CONSTRAINT collection_jobs_attempts_valid CHECK (
        attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts
        AND (status <> 'queued' OR attempt_count < max_attempts)
        AND (status <> 'running' OR attempt_count > 0)
    ),
    CONSTRAINT collection_jobs_result_summary_object
        CHECK (jsonb_typeof(result_summary) = 'object'),
    CONSTRAINT collection_jobs_error_pair CHECK (
        (last_error_code IS NULL AND last_error_message IS NULL)
        OR (last_error_code IS NOT NULL AND last_error_message IS NOT NULL
            AND btrim(last_error_code) <> '' AND btrim(last_error_message) <> '')
    ),
    CONSTRAINT collection_jobs_cancel_request_coherent CHECK (
        (cancel_requested_at IS NULL AND cancel_requested_by IS NULL AND cancel_reason IS NULL)
        OR (cancel_requested_at IS NOT NULL AND cancel_requested_by IS NOT NULL
            AND btrim(cancel_requested_by) <> '' AND cancel_reason IS NOT NULL
            AND btrim(cancel_reason) <> '')
    ),
    CONSTRAINT collection_jobs_lease_lifecycle CHECK (
        (status = 'queued'
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NULL AND completed_by IS NULL
            AND cancel_requested_at IS NULL)
        OR (status = 'running'
            AND lease_owner IS NOT NULL AND btrim(lease_owner) <> ''
            AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL
            AND started_at IS NOT NULL AND completed_at IS NULL AND completed_by IS NULL)
        OR (status IN ('succeeded', 'failed', 'dead_lettered')
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> '' AND cancel_requested_at IS NULL)
        OR (status = 'cancelled'
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> '' AND cancel_requested_at IS NOT NULL)
    ),
    CONSTRAINT collection_jobs_time_order CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (completed_at IS NULL OR completed_at >= coalesce(started_at, created_at))
    ),
    CONSTRAINT collection_jobs_project_idempotency_unique
        UNIQUE (project_id, idempotency_key),
    CONSTRAINT collection_jobs_parent_replay_unique
        UNIQUE (project_id, parent_job_id, replay_nonce),
    CONSTRAINT collection_jobs_sample_unique
        UNIQUE (
            collection_run_id, monitoring_query_id, platform, surface,
            access_method, sample_index, replay_nonce
        )
);

CREATE TABLE collection_run_summaries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    queued_count integer NOT NULL DEFAULT 0,
    running_count integer NOT NULL DEFAULT 0,
    succeeded_count integer NOT NULL DEFAULT 0,
    failed_count integer NOT NULL DEFAULT 0,
    cancelled_count integer NOT NULL DEFAULT 0,
    dead_lettered_count integer NOT NULL DEFAULT 0,
    answer_present_count integer NOT NULL DEFAULT 0,
    citation_count integer NOT NULL DEFAULT 0,
    total_cost_usd numeric(18,8) NOT NULL DEFAULT 0,
    total_duration_ms bigint NOT NULL DEFAULT 0,
    summary_version integer NOT NULL DEFAULT 1,
    computed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT collection_run_summaries_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_run_summaries_run_project_fkey
        FOREIGN KEY (collection_run_id, project_id)
        REFERENCES collection_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_run_summaries_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT collection_run_summaries_run_unique UNIQUE (collection_run_id),
    CONSTRAINT collection_run_summaries_counts_nonnegative CHECK (
        queued_count >= 0 AND running_count >= 0 AND succeeded_count >= 0
        AND failed_count >= 0 AND cancelled_count >= 0 AND dead_lettered_count >= 0
        AND answer_present_count >= 0 AND citation_count >= 0
    ),
    CONSTRAINT collection_run_summaries_cost_duration_nonnegative
        CHECK (total_cost_usd >= 0 AND total_duration_ms >= 0),
    CONSTRAINT collection_run_summaries_version_positive CHECK (summary_version > 0),
    CONSTRAINT collection_run_summaries_update_order CHECK (updated_at >= computed_at)
);

CREATE TABLE answer_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collection_job_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    status text NOT NULL,
    answer_present boolean NOT NULL,
    surface_triggered boolean NOT NULL,
    platform text NOT NULL,
    surface text NOT NULL,
    access_method text NOT NULL,
    sample_index integer NOT NULL,
    provider_request_id text,
    configured_model text,
    provider_reported_model text,
    collector_version text NOT NULL,
    collected_at timestamptz NOT NULL,
    duration_ms bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT answer_runs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT answer_runs_job_scope_fkey
        FOREIGN KEY (
            collection_job_id, collection_run_id, monitoring_query_id, project_id
        ) REFERENCES collection_jobs(
            id, collection_run_id, monitoring_query_id, project_id
        ) ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT answer_runs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT answer_runs_id_job_project_unique
        UNIQUE (id, collection_job_id, project_id),
    CONSTRAINT answer_runs_job_unique UNIQUE (collection_job_id),
    CONSTRAINT answer_runs_status_canonical
        CHECK (status IN ('succeeded', 'failed', 'manual_review')),
    CONSTRAINT answer_runs_target_nonempty CHECK (
        btrim(platform) <> '' AND btrim(surface) <> '' AND btrim(access_method) <> ''
        AND btrim(collector_version) <> ''
    ),
    CONSTRAINT answer_runs_sample_index_positive CHECK (sample_index > 0),
    CONSTRAINT answer_runs_optional_values_nonempty CHECK (
        (provider_request_id IS NULL OR btrim(provider_request_id) <> '')
        AND (configured_model IS NULL OR btrim(configured_model) <> '')
        AND (provider_reported_model IS NULL OR btrim(provider_reported_model) <> '')
    ),
    CONSTRAINT answer_runs_duration_nonnegative CHECK (duration_ms >= 0),
    CONSTRAINT answer_runs_created_after_collection CHECK (created_at >= collected_at)
);

CREATE TABLE raw_answers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    answer_run_id uuid NOT NULL,
    answer_text text NOT NULL,
    raw_payload_hash text NOT NULL,
    content_type text NOT NULL,
    data_classification text NOT NULL,
    retention_policy text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT raw_answers_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT raw_answers_run_project_fkey
        FOREIGN KEY (answer_run_id, project_id) REFERENCES answer_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT raw_answers_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT raw_answers_id_run_project_unique UNIQUE (id, answer_run_id, project_id),
    CONSTRAINT raw_answers_run_unique UNIQUE (answer_run_id),
    CONSTRAINT raw_answers_payload_hash_sha256
        CHECK (raw_payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT raw_answers_content_type_nonempty CHECK (btrim(content_type) <> ''),
    CONSTRAINT raw_answers_classification_canonical CHECK (
        data_classification IN ('public', 'internal', 'confidential', 'restricted')
    ),
    CONSTRAINT raw_answers_retention_nonempty CHECK (btrim(retention_policy) <> '')
);

CREATE TABLE answer_citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    answer_run_id uuid NOT NULL,
    raw_answer_id uuid NOT NULL,
    citation_position integer NOT NULL,
    source_url text NOT NULL,
    normalized_url_hash text NOT NULL,
    source_domain text NOT NULL,
    source_title text,
    source_snippet text,
    source_type text NOT NULL,
    public_disclosure_allowed boolean NOT NULL DEFAULT false,
    quotation_allowed boolean NOT NULL DEFAULT false,
    attribution_required boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT answer_citations_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT answer_citations_raw_run_project_fkey
        FOREIGN KEY (raw_answer_id, answer_run_id, project_id)
        REFERENCES raw_answers(id, answer_run_id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT answer_citations_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT answer_citations_position_nonnegative CHECK (citation_position >= 0),
    CONSTRAINT answer_citations_url_domain_nonempty
        CHECK (btrim(source_url) <> '' AND btrim(source_domain) <> ''),
    CONSTRAINT answer_citations_url_hash_sha256
        CHECK (normalized_url_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT answer_citations_optional_text_nonempty CHECK (
        (source_title IS NULL OR btrim(source_title) <> '')
        AND (source_snippet IS NULL OR btrim(source_snippet) <> '')
        AND btrim(source_type) <> ''
    ),
    CONSTRAINT answer_citations_answer_position_unique
        UNIQUE (answer_run_id, citation_position)
);

CREATE TABLE evidence_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    asset_type text NOT NULL,
    storage_uri text NOT NULL,
    storage_key text NOT NULL,
    content_hash text NOT NULL,
    size_bytes bigint NOT NULL,
    content_type text NOT NULL,
    access_policy text NOT NULL,
    retention_policy text NOT NULL,
    source_kind text NOT NULL,
    artifact_status text NOT NULL DEFAULT 'pending',
    finalized_at timestamptz,
    finalized_by text,
    failure_reason text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT evidence_assets_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT evidence_assets_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT evidence_assets_type_nonempty CHECK (btrim(asset_type) <> ''),
    CONSTRAINT evidence_assets_location_nonempty
        CHECK (btrim(storage_uri) <> '' AND btrim(storage_key) <> ''),
    CONSTRAINT evidence_assets_content_hash_sha256
        CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT evidence_assets_size_nonnegative CHECK (size_bytes >= 0),
    CONSTRAINT evidence_assets_metadata_nonempty CHECK (
        btrim(content_type) <> '' AND btrim(access_policy) <> ''
        AND btrim(retention_policy) <> '' AND btrim(source_kind) <> ''
        AND btrim(created_by) <> ''
    ),
    CONSTRAINT evidence_assets_status_canonical
        CHECK (artifact_status IN ('pending', 'finalized', 'failed')),
    CONSTRAINT evidence_assets_finalize_coherent CHECK (
        (artifact_status = 'pending' AND finalized_at IS NULL
            AND finalized_by IS NULL AND failure_reason IS NULL)
        OR (artifact_status = 'finalized' AND finalized_at IS NOT NULL
            AND finalized_by IS NOT NULL AND btrim(finalized_by) <> ''
            AND failure_reason IS NULL)
        OR (artifact_status = 'failed' AND finalized_at IS NULL
            AND finalized_by IS NULL AND failure_reason IS NOT NULL
            AND btrim(failure_reason) <> '')
    ),
    CONSTRAINT evidence_assets_storage_key_unique UNIQUE (project_id, storage_key),
    CONSTRAINT evidence_assets_content_unique UNIQUE (project_id, content_hash, asset_type)
);

CREATE TABLE artifact_finalize_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    evidence_asset_id uuid NOT NULL,
    expected_content_hash text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    completed_by text,
    last_error_code text,
    last_error_message text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT artifact_outbox_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT artifact_outbox_asset_project_fkey
        FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT artifact_outbox_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT artifact_outbox_asset_unique UNIQUE (evidence_asset_id),
    CONSTRAINT artifact_outbox_hash_sha256
        CHECK (expected_content_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT artifact_outbox_status_canonical CHECK (
        status IN ('queued', 'running', 'succeeded', 'failed', 'dead_lettered')
    ),
    CONSTRAINT artifact_outbox_attempts_valid CHECK (
        attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts
        AND (status <> 'queued' OR attempt_count < max_attempts)
        AND (status <> 'running' OR attempt_count > 0)
    ),
    CONSTRAINT artifact_outbox_error_pair CHECK (
        (last_error_code IS NULL AND last_error_message IS NULL)
        OR (last_error_code IS NOT NULL AND btrim(last_error_code) <> ''
            AND last_error_message IS NOT NULL AND btrim(last_error_message) <> '')
    ),
    CONSTRAINT artifact_outbox_lease_lifecycle CHECK (
        (status = 'queued' AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NULL AND completed_by IS NULL)
        OR (status = 'running' AND lease_owner IS NOT NULL
            AND btrim(lease_owner) <> '' AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL
            AND started_at IS NOT NULL AND completed_at IS NULL AND completed_by IS NULL)
        OR (status IN ('succeeded', 'failed', 'dead_lettered')
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> '')
    ),
    CONSTRAINT artifact_outbox_time_order CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (completed_at IS NULL OR completed_at >= coalesce(started_at, created_at))
    )
);

CREATE TABLE raw_answer_evidence_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    raw_answer_id uuid NOT NULL,
    evidence_asset_id uuid NOT NULL,
    evidence_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT raw_answer_evidence_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT raw_answer_evidence_answer_project_fkey
        FOREIGN KEY (raw_answer_id, project_id) REFERENCES raw_answers(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT raw_answer_evidence_asset_project_fkey
        FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT raw_answer_evidence_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT raw_answer_evidence_role_canonical
        CHECK (evidence_role IN ('raw_payload', 'screenshot', 'transcript', 'manual_proof')),
    CONSTRAINT raw_answer_evidence_relation_unique
        UNIQUE (raw_answer_id, evidence_asset_id, evidence_role)
);

CREATE TABLE answer_citation_evidence_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    answer_citation_id uuid NOT NULL,
    evidence_asset_id uuid NOT NULL,
    evidence_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT citation_evidence_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT citation_evidence_citation_project_fkey
        FOREIGN KEY (answer_citation_id, project_id)
        REFERENCES answer_citations(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT citation_evidence_asset_project_fkey
        FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT citation_evidence_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT citation_evidence_role_canonical
        CHECK (evidence_role IN ('page_capture', 'snippet_capture', 'source_archive')),
    CONSTRAINT citation_evidence_relation_unique
        UNIQUE (answer_citation_id, evidence_asset_id, evidence_role)
);

CREATE TABLE answer_analyses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    answer_run_id uuid NOT NULL,
    analysis_version text NOT NULL,
    analyzer_kind text NOT NULL,
    trigger_detected boolean NOT NULL,
    mention_detected boolean NOT NULL,
    recommendation_detected boolean NOT NULL,
    citation_detected boolean NOT NULL,
    sentiment_score numeric(7,6),
    confidence numeric(7,6) NOT NULL,
    claim_inventory_complete boolean NOT NULL DEFAULT false,
    claim_inventory_reviewed_by text,
    claim_inventory_reviewed_at timestamptz,
    analysis_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    analysis_hash text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT answer_analyses_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT answer_analyses_run_project_fkey
        FOREIGN KEY (answer_run_id, project_id) REFERENCES answer_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT answer_analyses_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT answer_analyses_version_kind_nonempty
        CHECK (btrim(analysis_version) <> '' AND btrim(analyzer_kind) <> ''),
    CONSTRAINT answer_analyses_sentiment_range
        CHECK (sentiment_score IS NULL OR sentiment_score BETWEEN -1 AND 1),
    CONSTRAINT answer_analyses_confidence_range CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT answer_analyses_claim_inventory_review_coherent CHECK (
        (claim_inventory_complete
            AND claim_inventory_reviewed_by IS NOT NULL
            AND btrim(claim_inventory_reviewed_by) <> ''
            AND claim_inventory_reviewed_at IS NOT NULL)
        OR (NOT claim_inventory_complete
            AND claim_inventory_reviewed_by IS NULL
            AND claim_inventory_reviewed_at IS NULL)
    ),
    CONSTRAINT answer_analyses_payload_object CHECK (jsonb_typeof(analysis_payload) = 'object'),
    CONSTRAINT answer_analyses_hash_sha256 CHECK (analysis_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT answer_analyses_created_by_nonempty CHECK (btrim(created_by) <> ''),
    CONSTRAINT answer_analyses_run_version_unique
        UNIQUE (answer_run_id, analysis_version)
);

CREATE TABLE answer_analysis_entity_mentions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    answer_analysis_id uuid NOT NULL,
    entity_id uuid NOT NULL,
    mention_role text NOT NULL,
    mention_count integer NOT NULL,
    first_position integer,
    confidence numeric(7,6) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT analysis_mentions_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT analysis_mentions_analysis_project_fkey
        FOREIGN KEY (answer_analysis_id, project_id)
        REFERENCES answer_analyses(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT analysis_mentions_entity_project_fkey
        FOREIGN KEY (entity_id, project_id) REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT analysis_mentions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT analysis_mentions_role_canonical CHECK (
        mention_role IN ('primary_brand', 'competitor', 'product', 'market', 'neutral')
    ),
    CONSTRAINT analysis_mentions_count_positive CHECK (mention_count > 0),
    CONSTRAINT analysis_mentions_position_nonnegative
        CHECK (first_position IS NULL OR first_position >= 0),
    CONSTRAINT analysis_mentions_confidence_range CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT analysis_mentions_relation_unique
        UNIQUE (answer_analysis_id, entity_id, mention_role)
);

CREATE TABLE answer_analysis_evidence_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    answer_analysis_id uuid NOT NULL,
    evidence_asset_id uuid NOT NULL,
    evidence_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT analysis_evidence_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT analysis_evidence_analysis_project_fkey
        FOREIGN KEY (answer_analysis_id, project_id)
        REFERENCES answer_analyses(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT analysis_evidence_asset_project_fkey
        FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT analysis_evidence_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT analysis_evidence_role_nonempty CHECK (btrim(evidence_role) <> ''),
    CONSTRAINT analysis_evidence_relation_unique
        UNIQUE (answer_analysis_id, evidence_asset_id, evidence_role)
);

CREATE TABLE collection_costs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collection_job_id uuid NOT NULL,
    answer_run_id uuid,
    provider text NOT NULL,
    configured_model text,
    currency text NOT NULL DEFAULT 'USD',
    prompt_tokens integer,
    completion_tokens integer,
    provider_cost numeric(18,8) NOT NULL DEFAULT 0,
    vendor_cost numeric(18,8) NOT NULL DEFAULT 0,
    compute_cost numeric(18,8) NOT NULL DEFAULT 0,
    total_cost numeric(18,8) NOT NULL,
    cost_method text NOT NULL,
    duration_ms bigint NOT NULL DEFAULT 0,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT collection_costs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_costs_job_project_fkey
        FOREIGN KEY (collection_job_id, project_id)
        REFERENCES collection_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT collection_costs_run_job_project_fkey
        FOREIGN KEY (answer_run_id, collection_job_id, project_id)
        REFERENCES answer_runs(id, collection_job_id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT collection_costs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT collection_costs_provider_nonempty CHECK (btrim(provider) <> ''),
    CONSTRAINT collection_costs_model_nonempty
        CHECK (configured_model IS NULL OR btrim(configured_model) <> ''),
    CONSTRAINT collection_costs_currency_canonical CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT collection_costs_tokens_nonnegative CHECK (
        (prompt_tokens IS NULL OR prompt_tokens >= 0)
        AND (completion_tokens IS NULL OR completion_tokens >= 0)
    ),
    CONSTRAINT collection_costs_amounts_nonnegative CHECK (
        provider_cost >= 0 AND vendor_cost >= 0 AND compute_cost >= 0
        AND total_cost >= 0
    ),
    CONSTRAINT collection_costs_total_exact
        CHECK (total_cost = provider_cost + vendor_cost + compute_cost),
    CONSTRAINT collection_costs_method_canonical
        CHECK (cost_method IN ('provider_reported', 'estimated', 'contract', 'manual')),
    CONSTRAINT collection_costs_duration_nonnegative CHECK (duration_ms >= 0)
);

CREATE TABLE model_call_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collection_job_id uuid,
    answer_analysis_id uuid,
    purpose text NOT NULL,
    provider text NOT NULL,
    provider_request_id text,
    configured_model text NOT NULL,
    provider_reported_model text,
    prompt_template_release text NOT NULL,
    request_hash text NOT NULL,
    response_hash text,
    prompt_tokens integer,
    completion_tokens integer,
    cost_usd numeric(18,8),
    latency_ms bigint NOT NULL DEFAULT 0,
    finish_reason text,
    status text NOT NULL,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT model_call_logs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT model_call_logs_job_project_fkey
        FOREIGN KEY (collection_job_id, project_id)
        REFERENCES collection_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT model_call_logs_analysis_project_fkey
        FOREIGN KEY (answer_analysis_id, project_id)
        REFERENCES answer_analyses(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT model_call_logs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT model_call_logs_context_required
        CHECK (collection_job_id IS NOT NULL OR answer_analysis_id IS NOT NULL),
    CONSTRAINT model_call_logs_identity_nonempty CHECK (
        btrim(purpose) <> '' AND btrim(provider) <> ''
        AND btrim(configured_model) <> '' AND btrim(prompt_template_release) <> ''
    ),
    CONSTRAINT model_call_logs_optional_identity_nonempty CHECK (
        (provider_request_id IS NULL OR btrim(provider_request_id) <> '')
        AND (provider_reported_model IS NULL OR btrim(provider_reported_model) <> '')
        AND (finish_reason IS NULL OR btrim(finish_reason) <> '')
        AND (error_code IS NULL OR btrim(error_code) <> '')
    ),
    CONSTRAINT model_call_logs_request_hash_sha256 CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT model_call_logs_response_hash_sha256
        CHECK (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT model_call_logs_usage_nonnegative CHECK (
        (prompt_tokens IS NULL OR prompt_tokens >= 0)
        AND (completion_tokens IS NULL OR completion_tokens >= 0)
        AND (cost_usd IS NULL OR cost_usd >= 0)
        AND latency_ms >= 0
    ),
    CONSTRAINT model_call_logs_status_canonical
        CHECK (status IN ('succeeded', 'failed', 'rate_limited', 'cancelled')),
    CONSTRAINT model_call_logs_result_coherent CHECK (
        (status = 'succeeded' AND response_hash IS NOT NULL AND error_code IS NULL)
        OR (status <> 'succeeded' AND error_code IS NOT NULL)
    )
);

CREATE TABLE visibility_weight_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    profile_name text NOT NULL,
    profile_version integer NOT NULL,
    formula_version text NOT NULL,
    normalization_method text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    notes text,
    created_by text NOT NULL,
    activated_by text,
    activated_at timestamptz,
    retired_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT visibility_weight_profiles_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT visibility_weight_profiles_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT visibility_weight_profiles_name_nonempty CHECK (btrim(profile_name) <> ''),
    CONSTRAINT visibility_weight_profiles_version_positive CHECK (profile_version > 0),
    CONSTRAINT visibility_weight_profiles_formula_nonempty
        CHECK (btrim(formula_version) <> ''),
    CONSTRAINT visibility_weight_profiles_normalization_canonical CHECK (
        normalization_method IN ('weighted_mean', 'weighted_sum', 'bounded_linear')
    ),
    CONSTRAINT visibility_weight_profiles_status_canonical
        CHECK (status IN ('draft', 'active', 'retired')),
    CONSTRAINT visibility_weight_profiles_notes_nonempty
        CHECK (notes IS NULL OR btrim(notes) <> ''),
    CONSTRAINT visibility_weight_profiles_created_by_nonempty CHECK (btrim(created_by) <> ''),
    CONSTRAINT visibility_weight_profiles_lifecycle CHECK (
        (status = 'draft' AND activated_by IS NULL AND activated_at IS NULL
            AND retired_at IS NULL)
        OR (status = 'active' AND activated_by IS NOT NULL
            AND btrim(activated_by) <> '' AND activated_at IS NOT NULL
            AND retired_at IS NULL)
        OR (status = 'retired' AND activated_by IS NOT NULL
            AND btrim(activated_by) <> '' AND activated_at IS NOT NULL
            AND retired_at IS NOT NULL AND retired_at >= activated_at)
    ),
    CONSTRAINT visibility_weight_profiles_update_order CHECK (updated_at >= created_at),
    CONSTRAINT visibility_weight_profiles_project_version_unique
        UNIQUE (project_id, profile_name, profile_version)
);

CREATE TABLE visibility_weight_profile_components (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    weight_profile_id uuid NOT NULL,
    metric_name text NOT NULL,
    dimension_type text NOT NULL,
    dimension_key text NOT NULL,
    weight numeric(12,8) NOT NULL,
    minimum_sample_count integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT weight_components_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT weight_components_profile_project_fkey
        FOREIGN KEY (weight_profile_id, project_id)
        REFERENCES visibility_weight_profiles(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT weight_components_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT weight_components_metric_canonical CHECK (metric_name IN (
        'trigger_rate', 'mention_rate', 'recommendation_rate',
        'citation_rate', 'sentiment_score'
    )),
    CONSTRAINT weight_components_dimension_canonical CHECK (
        dimension_type IN ('global', 'platform', 'city', 'intent', 'entity')
    ),
    CONSTRAINT weight_components_dimension_key_nonempty CHECK (btrim(dimension_key) <> ''),
    CONSTRAINT weight_components_weight_range CHECK (weight >= 0 AND weight <= 1),
    CONSTRAINT weight_components_sample_positive CHECK (minimum_sample_count > 0),
    CONSTRAINT weight_components_update_order CHECK (updated_at >= created_at),
    CONSTRAINT weight_components_profile_metric_dimension_unique
        UNIQUE (weight_profile_id, metric_name, dimension_type, dimension_key)
);

CREATE TABLE visibility_score_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    weight_profile_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    parent_job_id uuid,
    replay_nonce integer NOT NULL DEFAULT 0,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    priority integer NOT NULL DEFAULT 0,
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    completed_by text,
    cancel_requested_at timestamptz,
    cancel_requested_by text,
    cancel_reason text,
    last_error_code text,
    last_error_message text,
    result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    requested_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT visibility_score_runs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT visibility_score_runs_collection_project_fkey
        FOREIGN KEY (collection_run_id, project_id)
        REFERENCES collection_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT visibility_score_runs_profile_project_fkey
        FOREIGN KEY (weight_profile_id, project_id)
        REFERENCES visibility_weight_profiles(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT visibility_score_runs_parent_project_fkey
        FOREIGN KEY (parent_job_id, project_id)
        REFERENCES visibility_score_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT visibility_score_runs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT visibility_score_runs_idempotency_nonempty CHECK (btrim(idempotency_key) <> ''),
    CONSTRAINT visibility_score_runs_replay_lineage CHECK (
        (parent_job_id IS NULL AND replay_nonce = 0)
        OR (parent_job_id IS NOT NULL AND parent_job_id <> id AND replay_nonce > 0)
    ),
    CONSTRAINT visibility_score_runs_window_order CHECK (window_end > window_start),
    CONSTRAINT visibility_score_runs_status_canonical CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled', 'dead_lettered'
    )),
    CONSTRAINT visibility_score_runs_priority_range CHECK (priority BETWEEN -1000 AND 1000),
    CONSTRAINT visibility_score_runs_attempts_valid CHECK (
        attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts
        AND (status <> 'queued' OR attempt_count < max_attempts)
        AND (status <> 'running' OR attempt_count > 0)
    ),
    CONSTRAINT visibility_score_runs_result_object
        CHECK (jsonb_typeof(result_summary) = 'object'),
    CONSTRAINT visibility_score_runs_error_pair CHECK (
        (last_error_code IS NULL AND last_error_message IS NULL)
        OR (last_error_code IS NOT NULL AND last_error_message IS NOT NULL
            AND btrim(last_error_code) <> '' AND btrim(last_error_message) <> '')
    ),
    CONSTRAINT visibility_score_runs_cancel_request_coherent CHECK (
        (cancel_requested_at IS NULL AND cancel_requested_by IS NULL AND cancel_reason IS NULL)
        OR (cancel_requested_at IS NOT NULL AND cancel_requested_by IS NOT NULL
            AND btrim(cancel_requested_by) <> '' AND cancel_reason IS NOT NULL
            AND btrim(cancel_reason) <> '')
    ),
    CONSTRAINT visibility_score_runs_lease_lifecycle CHECK (
        (status = 'queued'
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NULL AND completed_by IS NULL
            AND cancel_requested_at IS NULL)
        OR (status = 'running'
            AND lease_owner IS NOT NULL AND btrim(lease_owner) <> ''
            AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL
            AND started_at IS NOT NULL AND completed_at IS NULL AND completed_by IS NULL)
        OR (status IN ('succeeded', 'failed', 'dead_lettered')
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> '' AND cancel_requested_at IS NULL)
        OR (status = 'cancelled'
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> '' AND cancel_requested_at IS NOT NULL)
    ),
    CONSTRAINT visibility_score_runs_actor_nonempty CHECK (btrim(requested_by) <> ''),
    CONSTRAINT visibility_score_runs_time_order CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (completed_at IS NULL OR completed_at >= coalesce(started_at, created_at))
    ),
    CONSTRAINT visibility_score_runs_project_idempotency_unique
        UNIQUE (project_id, idempotency_key),
    CONSTRAINT visibility_score_runs_parent_replay_unique
        UNIQUE (project_id, parent_job_id, replay_nonce)
);

CREATE TABLE visibility_score_run_analyses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    visibility_score_run_id uuid NOT NULL,
    answer_analysis_id uuid NOT NULL,
    inclusion_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT score_run_analyses_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT score_run_analyses_run_project_fkey
        FOREIGN KEY (visibility_score_run_id, project_id)
        REFERENCES visibility_score_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT score_run_analyses_analysis_project_fkey
        FOREIGN KEY (answer_analysis_id, project_id)
        REFERENCES answer_analyses(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT score_run_analyses_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT score_run_analyses_role_canonical
        CHECK (inclusion_role IN ('included', 'excluded_quality', 'excluded_scope')),
    CONSTRAINT score_run_analyses_relation_unique
        UNIQUE (visibility_score_run_id, answer_analysis_id)
);

CREATE TABLE visibility_score_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    visibility_score_run_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    weight_profile_id uuid NOT NULL,
    formula_version text NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    total_score numeric(12,8) NOT NULL,
    trigger_rate numeric(12,8) NOT NULL,
    mention_rate numeric(12,8) NOT NULL,
    recommendation_rate numeric(12,8) NOT NULL,
    citation_rate numeric(12,8) NOT NULL,
    sample_count integer NOT NULL,
    excluded_sample_count integer NOT NULL DEFAULT 0,
    limitations text NOT NULL DEFAULT '',
    snapshot_hash text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT visibility_snapshots_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT visibility_snapshots_run_project_fkey
        FOREIGN KEY (visibility_score_run_id, project_id)
        REFERENCES visibility_score_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT visibility_snapshots_collection_project_fkey
        FOREIGN KEY (collection_run_id, project_id)
        REFERENCES collection_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT visibility_snapshots_profile_project_fkey
        FOREIGN KEY (weight_profile_id, project_id)
        REFERENCES visibility_weight_profiles(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT visibility_snapshots_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT visibility_snapshots_run_unique UNIQUE (visibility_score_run_id),
    CONSTRAINT visibility_snapshots_formula_nonempty CHECK (btrim(formula_version) <> ''),
    CONSTRAINT visibility_snapshots_window_order CHECK (window_end > window_start),
    CONSTRAINT visibility_snapshots_score_range CHECK (
        total_score BETWEEN 0 AND 100
        AND trigger_rate BETWEEN 0 AND 1
        AND mention_rate BETWEEN 0 AND 1
        AND recommendation_rate BETWEEN 0 AND 1
        AND citation_rate BETWEEN 0 AND 1
    ),
    CONSTRAINT visibility_snapshots_counts_nonnegative
        CHECK (sample_count >= 0 AND excluded_sample_count >= 0),
    CONSTRAINT visibility_snapshots_hash_sha256
        CHECK (snapshot_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT visibility_snapshots_created_by_nonempty CHECK (btrim(created_by) <> '')
);

CREATE TABLE visibility_score_dimensions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    visibility_score_snapshot_id uuid NOT NULL,
    dimension_type text NOT NULL,
    dimension_key text NOT NULL,
    dimension_score numeric(12,8) NOT NULL,
    trigger_rate numeric(12,8),
    mention_rate numeric(12,8),
    recommendation_rate numeric(12,8),
    citation_rate numeric(12,8),
    sample_count integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT visibility_dimensions_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT visibility_dimensions_snapshot_project_fkey
        FOREIGN KEY (visibility_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT visibility_dimensions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT visibility_dimensions_type_canonical
        CHECK (dimension_type IN ('platform', 'city', 'intent', 'entity')),
    CONSTRAINT visibility_dimensions_key_nonempty CHECK (btrim(dimension_key) <> ''),
    CONSTRAINT visibility_dimensions_score_range CHECK (
        dimension_score BETWEEN 0 AND 100
        AND (trigger_rate IS NULL OR trigger_rate BETWEEN 0 AND 1)
        AND (mention_rate IS NULL OR mention_rate BETWEEN 0 AND 1)
        AND (recommendation_rate IS NULL OR recommendation_rate BETWEEN 0 AND 1)
        AND (citation_rate IS NULL OR citation_rate BETWEEN 0 AND 1)
    ),
    CONSTRAINT visibility_dimensions_sample_nonnegative CHECK (sample_count >= 0),
    CONSTRAINT visibility_dimensions_snapshot_dimension_unique
        UNIQUE (visibility_score_snapshot_id, dimension_type, dimension_key)
);

CREATE TABLE score_contributions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    visibility_score_snapshot_id uuid NOT NULL,
    answer_analysis_id uuid NOT NULL,
    metric_name text NOT NULL,
    dimension_type text NOT NULL,
    dimension_key text NOT NULL,
    weight numeric(12,8) NOT NULL,
    raw_value numeric(18,10) NOT NULL,
    normalized_value numeric(18,10) NOT NULL,
    contribution numeric(18,10) NOT NULL,
    positive_evidence text NOT NULL DEFAULT '',
    negative_evidence text NOT NULL DEFAULT '',
    explanation text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT score_contributions_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT score_contributions_snapshot_project_fkey
        FOREIGN KEY (visibility_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT score_contributions_analysis_project_fkey
        FOREIGN KEY (answer_analysis_id, project_id)
        REFERENCES answer_analyses(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT score_contributions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT score_contributions_metric_canonical CHECK (metric_name IN (
        'trigger_rate', 'mention_rate', 'recommendation_rate',
        'citation_rate', 'sentiment_score'
    )),
    CONSTRAINT score_contributions_dimension_canonical CHECK (
        dimension_type IN ('global', 'platform', 'city', 'intent', 'entity')
    ),
    CONSTRAINT score_contributions_dimension_key_nonempty CHECK (btrim(dimension_key) <> ''),
    CONSTRAINT score_contributions_weight_range CHECK (weight >= 0 AND weight <= 1),
    CONSTRAINT score_contributions_normalized_range
        CHECK (normalized_value >= 0 AND normalized_value <= 1),
    CONSTRAINT score_contributions_explanation_nonempty CHECK (btrim(explanation) <> ''),
    CONSTRAINT score_contributions_trace_unique UNIQUE (
        visibility_score_snapshot_id, answer_analysis_id,
        metric_name, dimension_type, dimension_key
    )
);

CREATE TABLE score_contribution_evidence_assets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    score_contribution_id uuid NOT NULL,
    evidence_asset_id uuid NOT NULL,
    evidence_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT contribution_evidence_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT contribution_evidence_contribution_project_fkey
        FOREIGN KEY (score_contribution_id, project_id)
        REFERENCES score_contributions(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT contribution_evidence_asset_project_fkey
        FOREIGN KEY (evidence_asset_id, project_id)
        REFERENCES evidence_assets(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT contribution_evidence_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT contribution_evidence_role_nonempty CHECK (btrim(evidence_role) <> ''),
    CONSTRAINT contribution_evidence_relation_unique
        UNIQUE (score_contribution_id, evidence_asset_id, evidence_role)
);

CREATE TABLE source_graphs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    collection_run_id uuid NOT NULL,
    visibility_score_snapshot_id uuid,
    graph_version text NOT NULL,
    graph_hash text NOT NULL,
    status text NOT NULL DEFAULT 'ready',
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_graphs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_graphs_collection_project_fkey
        FOREIGN KEY (collection_run_id, project_id)
        REFERENCES collection_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT source_graphs_snapshot_project_fkey
        FOREIGN KEY (visibility_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT source_graphs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT source_graphs_version_nonempty CHECK (btrim(graph_version) <> ''),
    CONSTRAINT source_graphs_hash_sha256 CHECK (graph_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT source_graphs_status_canonical CHECK (status IN ('building', 'ready', 'failed')),
    CONSTRAINT source_graphs_created_by_nonempty CHECK (btrim(created_by) <> ''),
    CONSTRAINT source_graphs_collection_version_unique
        UNIQUE (collection_run_id, graph_version)
);

CREATE TABLE source_nodes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_graph_id uuid NOT NULL,
    entity_id uuid,
    source_url text NOT NULL,
    normalized_url_hash text NOT NULL,
    source_domain text NOT NULL,
    source_type text NOT NULL,
    source_title text,
    citation_count integer NOT NULL DEFAULT 0,
    authority_score numeric(12,8),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_nodes_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_nodes_graph_project_fkey
        FOREIGN KEY (source_graph_id, project_id) REFERENCES source_graphs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_nodes_entity_project_fkey
        FOREIGN KEY (entity_id, project_id) REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT source_nodes_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT source_nodes_id_graph_project_unique
        UNIQUE (id, source_graph_id, project_id),
    CONSTRAINT source_nodes_url_domain_nonempty
        CHECK (btrim(source_url) <> '' AND btrim(source_domain) <> ''),
    CONSTRAINT source_nodes_url_hash_sha256 CHECK (normalized_url_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT source_nodes_type_nonempty CHECK (btrim(source_type) <> ''),
    CONSTRAINT source_nodes_title_nonempty
        CHECK (source_title IS NULL OR btrim(source_title) <> ''),
    CONSTRAINT source_nodes_citations_nonnegative CHECK (citation_count >= 0),
    CONSTRAINT source_nodes_authority_range
        CHECK (authority_score IS NULL OR authority_score BETWEEN 0 AND 1),
    CONSTRAINT source_nodes_graph_url_unique UNIQUE (source_graph_id, normalized_url_hash)
);

CREATE TABLE source_graph_edges (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_graph_id uuid NOT NULL,
    from_source_node_id uuid NOT NULL,
    to_source_node_id uuid NOT NULL,
    relation_type text NOT NULL,
    weight numeric(12,8) NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_edges_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_edges_from_graph_project_fkey
        FOREIGN KEY (from_source_node_id, source_graph_id, project_id)
        REFERENCES source_nodes(id, source_graph_id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_edges_to_graph_project_fkey
        FOREIGN KEY (to_source_node_id, source_graph_id, project_id)
        REFERENCES source_nodes(id, source_graph_id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_edges_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT source_edges_not_self CHECK (from_source_node_id <> to_source_node_id),
    CONSTRAINT source_edges_relation_nonempty CHECK (btrim(relation_type) <> ''),
    CONSTRAINT source_edges_weight_range CHECK (weight >= 0 AND weight <= 1),
    CONSTRAINT source_edges_relation_unique UNIQUE (
        source_graph_id, from_source_node_id, to_source_node_id, relation_type
    )
);

CREATE TABLE source_node_citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_node_id uuid NOT NULL,
    answer_citation_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_node_citations_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_node_citations_node_project_fkey
        FOREIGN KEY (source_node_id, project_id) REFERENCES source_nodes(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_node_citations_citation_project_fkey
        FOREIGN KEY (answer_citation_id, project_id)
        REFERENCES answer_citations(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT source_node_citations_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT source_node_citations_relation_unique
        UNIQUE (source_node_id, answer_citation_id)
);

CREATE TABLE source_gaps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_graph_id uuid NOT NULL,
    visibility_score_snapshot_id uuid,
    entity_id uuid,
    gap_type text NOT NULL,
    source_type text NOT NULL,
    severity text NOT NULL,
    observed_count integer NOT NULL DEFAULT 0,
    expected_count integer NOT NULL DEFAULT 0,
    expected_weight numeric(12,8) NOT NULL DEFAULT 0,
    recommendation text NOT NULL,
    status text NOT NULL DEFAULT 'open',
    detected_by text NOT NULL,
    resolved_by text,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_gaps_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_gaps_graph_project_fkey
        FOREIGN KEY (source_graph_id, project_id) REFERENCES source_graphs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_gaps_snapshot_project_fkey
        FOREIGN KEY (visibility_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT source_gaps_entity_project_fkey
        FOREIGN KEY (entity_id, project_id) REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT source_gaps_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT source_gaps_types_nonempty
        CHECK (btrim(gap_type) <> '' AND btrim(source_type) <> ''),
    CONSTRAINT source_gaps_severity_canonical
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT source_gaps_counts_nonnegative
        CHECK (observed_count >= 0 AND expected_count >= 0 AND expected_weight >= 0),
    CONSTRAINT source_gaps_recommendation_nonempty CHECK (btrim(recommendation) <> ''),
    CONSTRAINT source_gaps_status_canonical
        CHECK (status IN ('open', 'triaged', 'in_progress', 'resolved', 'dismissed')),
    CONSTRAINT source_gaps_actors_nonempty CHECK (
        btrim(detected_by) <> '' AND (resolved_by IS NULL OR btrim(resolved_by) <> '')
    ),
    CONSTRAINT source_gaps_resolution_coherent CHECK (
        (status IN ('resolved', 'dismissed') AND resolved_by IS NOT NULL
            AND btrim(resolved_by) <> ''
            AND resolved_at IS NOT NULL)
        OR (status NOT IN ('resolved', 'dismissed') AND resolved_by IS NULL
            AND resolved_at IS NULL)
    ),
    CONSTRAINT source_gaps_time_order CHECK (
        updated_at >= created_at AND (resolved_at IS NULL OR resolved_at >= created_at)
    ),
    CONSTRAINT source_gaps_graph_scope_unique
        UNIQUE (source_graph_id, gap_type, source_type, entity_id)
);

CREATE TABLE source_gap_citations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_gap_id uuid NOT NULL,
    answer_citation_id uuid NOT NULL,
    evidence_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_gap_citations_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_gap_citations_gap_project_fkey
        FOREIGN KEY (source_gap_id, project_id) REFERENCES source_gaps(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_gap_citations_citation_project_fkey
        FOREIGN KEY (answer_citation_id, project_id)
        REFERENCES answer_citations(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT source_gap_citations_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT source_gap_citations_role_nonempty CHECK (btrim(evidence_role) <> ''),
    CONSTRAINT source_gap_citations_relation_unique
        UNIQUE (source_gap_id, answer_citation_id, evidence_role)
);

CREATE TABLE source_gap_score_contributions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    source_gap_id uuid NOT NULL,
    score_contribution_id uuid NOT NULL,
    evidence_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_gap_contributions_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_gap_contributions_gap_project_fkey
        FOREIGN KEY (source_gap_id, project_id) REFERENCES source_gaps(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT source_gap_contributions_contribution_project_fkey
        FOREIGN KEY (score_contribution_id, project_id)
        REFERENCES score_contributions(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT source_gap_contributions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT source_gap_contributions_role_nonempty CHECK (btrim(evidence_role) <> ''),
    CONSTRAINT source_gap_contributions_relation_unique
        UNIQUE (source_gap_id, score_contribution_id, evidence_role)
);

CREATE TABLE competitor_benchmarks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    visibility_score_snapshot_id uuid NOT NULL,
    primary_entity_id uuid NOT NULL,
    compared_entity_id uuid NOT NULL,
    metric_scope text NOT NULL,
    metric_name text NOT NULL,
    primary_value numeric(18,10) NOT NULL,
    compared_value numeric(18,10) NOT NULL,
    value_delta numeric(18,10) NOT NULL,
    sample_count integer NOT NULL,
    benchmark_hash text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT competitor_benchmarks_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT competitor_benchmarks_snapshot_project_fkey
        FOREIGN KEY (visibility_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT competitor_benchmarks_primary_entity_project_fkey
        FOREIGN KEY (primary_entity_id, project_id)
        REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT competitor_benchmarks_compared_entity_project_fkey
        FOREIGN KEY (compared_entity_id, project_id)
        REFERENCES product_entities(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT competitor_benchmarks_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT competitor_benchmarks_entities_distinct
        CHECK (primary_entity_id <> compared_entity_id),
    CONSTRAINT competitor_benchmarks_metric_nonempty
        CHECK (btrim(metric_scope) <> '' AND btrim(metric_name) <> ''),
    CONSTRAINT competitor_benchmarks_delta_exact
        CHECK (value_delta = compared_value - primary_value),
    CONSTRAINT competitor_benchmarks_sample_nonnegative CHECK (sample_count >= 0),
    CONSTRAINT competitor_benchmarks_hash_sha256 CHECK (benchmark_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT competitor_benchmarks_created_by_nonempty CHECK (btrim(created_by) <> ''),
    CONSTRAINT competitor_benchmarks_metric_unique UNIQUE (
        visibility_score_snapshot_id, primary_entity_id, compared_entity_id,
        metric_scope, metric_name
    )
);

CREATE TABLE competitor_benchmark_contributions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    competitor_benchmark_id uuid NOT NULL,
    score_contribution_id uuid NOT NULL,
    comparison_role text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT benchmark_contributions_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT benchmark_contributions_benchmark_project_fkey
        FOREIGN KEY (competitor_benchmark_id, project_id)
        REFERENCES competitor_benchmarks(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT benchmark_contributions_score_project_fkey
        FOREIGN KEY (score_contribution_id, project_id)
        REFERENCES score_contributions(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT benchmark_contributions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT benchmark_contributions_role_canonical
        CHECK (comparison_role IN ('primary', 'compared', 'shared')),
    CONSTRAINT benchmark_contributions_relation_unique
        UNIQUE (competitor_benchmark_id, score_contribution_id, comparison_role)
);

CREATE TABLE action_recommendations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    title text NOT NULL,
    description text NOT NULL,
    action_type text NOT NULL,
    priority text NOT NULL,
    status text NOT NULL DEFAULT 'open',
    owner_id text,
    customer_visible boolean NOT NULL DEFAULT false,
    revision integer NOT NULL DEFAULT 1,
    next_check_at timestamptz,
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT action_recommendations_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_recommendations_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT action_recommendations_title_description_nonempty
        CHECK (btrim(title) <> '' AND btrim(description) <> ''),
    CONSTRAINT action_recommendations_type_nonempty CHECK (btrim(action_type) <> ''),
    CONSTRAINT action_recommendations_priority_canonical
        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT action_recommendations_status_canonical CHECK (status IN (
        'open', 'planned', 'in_progress', 'completed', 'dismissed', 'cancelled'
    )),
    CONSTRAINT action_recommendations_owner_nonempty
        CHECK (owner_id IS NULL OR btrim(owner_id) <> ''),
    CONSTRAINT action_recommendations_revision_positive CHECK (revision > 0),
    CONSTRAINT action_recommendations_actors_nonempty
        CHECK (btrim(created_by) <> '' AND btrim(updated_by) <> ''),
    CONSTRAINT action_recommendations_update_order CHECK (updated_at >= created_at)
);

CREATE TABLE action_source_gaps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    action_recommendation_id uuid NOT NULL,
    source_gap_id uuid NOT NULL,
    relation_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT action_source_gaps_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_source_gaps_action_project_fkey
        FOREIGN KEY (action_recommendation_id, project_id)
        REFERENCES action_recommendations(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_source_gaps_gap_project_fkey
        FOREIGN KEY (source_gap_id, project_id) REFERENCES source_gaps(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT action_source_gaps_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT action_source_gaps_relation_canonical
        CHECK (relation_type IN ('addresses', 'mitigates', 'monitors')),
    CONSTRAINT action_source_gaps_relation_unique
        UNIQUE (action_recommendation_id, source_gap_id, relation_type)
);

CREATE TABLE action_score_contributions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    action_recommendation_id uuid NOT NULL,
    score_contribution_id uuid NOT NULL,
    relation_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT action_score_contributions_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_score_contributions_action_project_fkey
        FOREIGN KEY (action_recommendation_id, project_id)
        REFERENCES action_recommendations(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_score_contributions_score_project_fkey
        FOREIGN KEY (score_contribution_id, project_id)
        REFERENCES score_contributions(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT action_score_contributions_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT action_score_contributions_relation_canonical
        CHECK (relation_type IN ('improves', 'protects', 'investigates')),
    CONSTRAINT action_score_contributions_relation_unique
        UNIQUE (action_recommendation_id, score_contribution_id, relation_type)
);

CREATE TABLE action_competitor_benchmarks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    action_recommendation_id uuid NOT NULL,
    competitor_benchmark_id uuid NOT NULL,
    relation_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT action_benchmarks_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_benchmarks_action_project_fkey
        FOREIGN KEY (action_recommendation_id, project_id)
        REFERENCES action_recommendations(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_benchmarks_benchmark_project_fkey
        FOREIGN KEY (competitor_benchmark_id, project_id)
        REFERENCES competitor_benchmarks(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT action_benchmarks_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT action_benchmarks_relation_canonical
        CHECK (relation_type IN ('closes_gap', 'maintains_lead', 'validates')),
    CONSTRAINT action_benchmarks_relation_unique
        UNIQUE (action_recommendation_id, competitor_benchmark_id, relation_type)
);

CREATE TABLE action_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    action_recommendation_id uuid NOT NULL,
    title text NOT NULL,
    status text NOT NULL DEFAULT 'todo',
    owner_id text,
    due_at timestamptz,
    completed_at timestamptz,
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT action_tasks_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_tasks_action_project_fkey
        FOREIGN KEY (action_recommendation_id, project_id)
        REFERENCES action_recommendations(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT action_tasks_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT action_tasks_title_nonempty CHECK (btrim(title) <> ''),
    CONSTRAINT action_tasks_status_canonical
        CHECK (status IN ('todo', 'in_progress', 'blocked', 'completed', 'cancelled')),
    CONSTRAINT action_tasks_owner_nonempty
        CHECK (owner_id IS NULL OR btrim(owner_id) <> ''),
    CONSTRAINT action_tasks_completion_coherent CHECK (
        (status = 'completed' AND completed_at IS NOT NULL)
        OR (status <> 'completed' AND completed_at IS NULL)
    ),
    CONSTRAINT action_tasks_actors_nonempty
        CHECK (btrim(created_by) <> '' AND btrim(updated_by) <> ''),
    CONSTRAINT action_tasks_time_order CHECK (
        updated_at >= created_at AND (completed_at IS NULL OR completed_at >= created_at)
    )
);

CREATE TABLE retest_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    action_recommendation_id uuid,
    baseline_score_snapshot_id uuid NOT NULL,
    output_score_snapshot_id uuid,
    idempotency_key text NOT NULL,
    parent_job_id uuid,
    replay_nonce integer NOT NULL DEFAULT 0,
    scheduled_for timestamptz NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    priority integer NOT NULL DEFAULT 0,
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    completed_by text,
    cancel_requested_at timestamptz,
    cancel_requested_by text,
    cancel_reason text,
    last_error_code text,
    last_error_message text,
    result_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    requested_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT retest_runs_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT retest_runs_action_project_fkey
        FOREIGN KEY (action_recommendation_id, project_id)
        REFERENCES action_recommendations(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT retest_runs_baseline_snapshot_project_fkey
        FOREIGN KEY (baseline_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT retest_runs_output_snapshot_project_fkey
        FOREIGN KEY (output_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT retest_runs_parent_project_fkey
        FOREIGN KEY (parent_job_id, project_id) REFERENCES retest_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT retest_runs_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT retest_runs_idempotency_nonempty CHECK (btrim(idempotency_key) <> ''),
    CONSTRAINT retest_runs_replay_lineage CHECK (
        (parent_job_id IS NULL AND replay_nonce = 0)
        OR (parent_job_id IS NOT NULL AND parent_job_id <> id AND replay_nonce > 0)
    ),
    CONSTRAINT retest_runs_window_order CHECK (window_end > window_start),
    CONSTRAINT retest_runs_status_canonical CHECK (status IN (
        'queued', 'running', 'succeeded', 'failed', 'cancelled', 'dead_lettered'
    )),
    CONSTRAINT retest_runs_priority_range CHECK (priority BETWEEN -1000 AND 1000),
    CONSTRAINT retest_runs_attempts_valid CHECK (
        attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts
        AND (status <> 'queued' OR attempt_count < max_attempts)
        AND (status <> 'running' OR attempt_count > 0)
    ),
    CONSTRAINT retest_runs_result_object CHECK (jsonb_typeof(result_summary) = 'object'),
    CONSTRAINT retest_runs_error_pair CHECK (
        (last_error_code IS NULL AND last_error_message IS NULL)
        OR (last_error_code IS NOT NULL AND last_error_message IS NOT NULL
            AND btrim(last_error_code) <> '' AND btrim(last_error_message) <> '')
    ),
    CONSTRAINT retest_runs_cancel_request_coherent CHECK (
        (cancel_requested_at IS NULL AND cancel_requested_by IS NULL AND cancel_reason IS NULL)
        OR (cancel_requested_at IS NOT NULL AND cancel_requested_by IS NOT NULL
            AND btrim(cancel_requested_by) <> '' AND cancel_reason IS NOT NULL
            AND btrim(cancel_reason) <> '')
    ),
    CONSTRAINT retest_runs_lease_lifecycle CHECK (
        (status = 'queued'
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NULL AND completed_by IS NULL
            AND output_score_snapshot_id IS NULL AND cancel_requested_at IS NULL)
        OR (status = 'running'
            AND lease_owner IS NOT NULL AND btrim(lease_owner) <> ''
            AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL
            AND started_at IS NOT NULL AND completed_at IS NULL AND completed_by IS NULL
            AND output_score_snapshot_id IS NULL)
        OR (status = 'succeeded'
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> ''
            AND output_score_snapshot_id IS NOT NULL
            AND output_score_snapshot_id <> baseline_score_snapshot_id
            AND cancel_requested_at IS NULL)
        OR (status IN ('failed', 'dead_lettered')
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> ''
            AND output_score_snapshot_id IS NULL AND cancel_requested_at IS NULL)
        OR (status = 'cancelled'
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND completed_at IS NOT NULL AND completed_by IS NOT NULL
            AND btrim(completed_by) <> ''
            AND output_score_snapshot_id IS NULL AND cancel_requested_at IS NOT NULL)
    ),
    CONSTRAINT retest_runs_requested_by_nonempty CHECK (btrim(requested_by) <> ''),
    CONSTRAINT retest_runs_time_order CHECK (
        updated_at >= created_at
        AND (started_at IS NULL OR started_at >= created_at)
        AND (completed_at IS NULL OR completed_at >= coalesce(started_at, created_at))
    ),
    CONSTRAINT retest_runs_project_idempotency_unique UNIQUE (project_id, idempotency_key),
    CONSTRAINT retest_runs_parent_replay_unique
        UNIQUE (project_id, parent_job_id, replay_nonce)
);

-- A wake-up projection only. Business lifecycle, cancellation, and replay remain
-- authoritative in the three durable job tables above.
CREATE TABLE durable_job_dispatch_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    job_kind text NOT NULL,
    job_id uuid NOT NULL,
    collection_job_id uuid,
    visibility_score_run_id uuid,
    retest_run_id uuid,
    payload_hash text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempt_count integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 5,
    next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_owner text,
    lease_token uuid,
    lease_expires_at timestamptz,
    heartbeat_at timestamptz,
    dispatched_at timestamptz,
    dispatched_by text,
    last_error_code text,
    last_error_message text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT durable_dispatch_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT durable_dispatch_collection_project_fkey
        FOREIGN KEY (collection_job_id, project_id)
        REFERENCES collection_jobs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT durable_dispatch_score_project_fkey
        FOREIGN KEY (visibility_score_run_id, project_id)
        REFERENCES visibility_score_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT durable_dispatch_retest_project_fkey
        FOREIGN KEY (retest_run_id, project_id)
        REFERENCES retest_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT durable_dispatch_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT durable_dispatch_job_unique UNIQUE (job_kind, job_id),
    CONSTRAINT durable_dispatch_kind_canonical CHECK (
        job_kind IN ('collection', 'visibility_score', 'retest')
    ),
    CONSTRAINT durable_dispatch_job_discriminator CHECK (
        (job_kind = 'collection' AND collection_job_id = job_id
            AND visibility_score_run_id IS NULL AND retest_run_id IS NULL)
        OR (job_kind = 'visibility_score' AND visibility_score_run_id = job_id
            AND collection_job_id IS NULL AND retest_run_id IS NULL)
        OR (job_kind = 'retest' AND retest_run_id = job_id
            AND collection_job_id IS NULL AND visibility_score_run_id IS NULL)
    ),
    CONSTRAINT durable_dispatch_payload_hash_sha256
        CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT durable_dispatch_status_canonical CHECK (
        status IN ('pending', 'dispatching', 'dispatched', 'dead_letter')
    ),
    CONSTRAINT durable_dispatch_attempts_valid CHECK (
        attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts
        AND (status <> 'pending' OR attempt_count < max_attempts)
        AND (status <> 'dispatching' OR attempt_count > 0)
    ),
    CONSTRAINT durable_dispatch_error_pair CHECK (
        (last_error_code IS NULL AND last_error_message IS NULL)
        OR (last_error_code IS NOT NULL AND last_error_message IS NOT NULL
            AND btrim(last_error_code) <> '' AND btrim(last_error_message) <> '')
    ),
    CONSTRAINT durable_dispatch_lease_lifecycle CHECK (
        (status = 'pending'
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND dispatched_at IS NULL AND dispatched_by IS NULL)
        OR (status = 'dispatching'
            AND lease_owner IS NOT NULL AND btrim(lease_owner) <> ''
            AND lease_token IS NOT NULL
            AND lease_expires_at IS NOT NULL AND heartbeat_at IS NOT NULL
            AND dispatched_at IS NULL AND dispatched_by IS NULL)
        OR (status IN ('dispatched', 'dead_letter')
            AND lease_owner IS NULL AND lease_token IS NULL
            AND lease_expires_at IS NULL AND heartbeat_at IS NULL
            AND dispatched_at IS NOT NULL AND dispatched_by IS NOT NULL
            AND btrim(dispatched_by) <> '')
    ),
    CONSTRAINT durable_dispatch_time_order CHECK (
        updated_at >= created_at
        AND (dispatched_at IS NULL OR dispatched_at >= created_at)
    )
);

CREATE TABLE retest_run_queries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    retest_run_id uuid NOT NULL,
    monitoring_query_id uuid NOT NULL,
    ordinal integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT retest_run_queries_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT retest_run_queries_run_project_fkey
        FOREIGN KEY (retest_run_id, project_id) REFERENCES retest_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT retest_run_queries_query_project_fkey
        FOREIGN KEY (monitoring_query_id, project_id)
        REFERENCES monitoring_queries(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT retest_run_queries_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT retest_run_queries_ordinal_nonnegative CHECK (ordinal >= 0),
    CONSTRAINT retest_run_queries_query_unique UNIQUE (retest_run_id, monitoring_query_id),
    CONSTRAINT retest_run_queries_ordinal_unique UNIQUE (retest_run_id, ordinal)
);

CREATE TABLE retest_comparisons (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    retest_run_id uuid NOT NULL,
    baseline_score_snapshot_id uuid NOT NULL,
    retest_score_snapshot_id uuid NOT NULL,
    baseline_score numeric(12,8) NOT NULL,
    retest_score numeric(12,8) NOT NULL,
    score_delta numeric(12,8) NOT NULL,
    trend text NOT NULL,
    comparison_hash text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT retest_comparisons_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT retest_comparisons_run_project_fkey
        FOREIGN KEY (retest_run_id, project_id) REFERENCES retest_runs(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT retest_comparisons_baseline_project_fkey
        FOREIGN KEY (baseline_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT retest_comparisons_retest_project_fkey
        FOREIGN KEY (retest_score_snapshot_id, project_id)
        REFERENCES visibility_score_snapshots(id, project_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT retest_comparisons_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT retest_comparisons_run_unique UNIQUE (retest_run_id),
    CONSTRAINT retest_comparisons_snapshots_distinct
        CHECK (baseline_score_snapshot_id <> retest_score_snapshot_id),
    CONSTRAINT retest_comparisons_score_range
        CHECK (baseline_score BETWEEN 0 AND 100 AND retest_score BETWEEN 0 AND 100),
    CONSTRAINT retest_comparisons_delta_exact CHECK (score_delta = retest_score - baseline_score),
    CONSTRAINT retest_comparisons_trend_canonical
        CHECK (trend IN ('improved', 'unchanged', 'declined')),
    CONSTRAINT retest_comparisons_hash_sha256
        CHECK (comparison_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT retest_comparisons_created_by_nonempty CHECK (btrim(created_by) <> '')
);

CREATE TABLE review_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    target_type text NOT NULL,
    answer_analysis_id uuid,
    source_gap_id uuid,
    action_recommendation_id uuid,
    retest_comparison_id uuid,
    status text NOT NULL DEFAULT 'assigned',
    priority text NOT NULL DEFAULT 'normal',
    assigned_to text NOT NULL,
    assigned_by text NOT NULL,
    submitted_for_review_by text NOT NULL,
    reviewer_id text,
    decision text,
    review_notes text,
    due_at timestamptz,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT review_assignments_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT review_assignments_analysis_project_fkey
        FOREIGN KEY (answer_analysis_id, project_id)
        REFERENCES answer_analyses(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT review_assignments_gap_project_fkey
        FOREIGN KEY (source_gap_id, project_id) REFERENCES source_gaps(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT review_assignments_action_project_fkey
        FOREIGN KEY (action_recommendation_id, project_id)
        REFERENCES action_recommendations(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT review_assignments_retest_project_fkey
        FOREIGN KEY (retest_comparison_id, project_id)
        REFERENCES retest_comparisons(id, project_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT review_assignments_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT review_assignments_typed_target CHECK (
        num_nonnulls(
            answer_analysis_id, source_gap_id,
            action_recommendation_id, retest_comparison_id
        ) = 1
        AND (
            (target_type = 'answer_analysis' AND answer_analysis_id IS NOT NULL)
            OR (target_type = 'source_gap' AND source_gap_id IS NOT NULL)
            OR (target_type = 'action_recommendation' AND action_recommendation_id IS NOT NULL)
            OR (target_type = 'retest_comparison' AND retest_comparison_id IS NOT NULL)
        )
    ),
    CONSTRAINT review_assignments_status_canonical CHECK (
        status IN ('assigned', 'in_review', 'approved', 'rejected', 'cancelled')
    ),
    CONSTRAINT review_assignments_priority_canonical
        CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    CONSTRAINT review_assignments_actors_nonempty CHECK (
        btrim(assigned_to) <> '' AND btrim(assigned_by) <> ''
        AND btrim(submitted_for_review_by) <> ''
        AND (reviewer_id IS NULL OR btrim(reviewer_id) <> '')
    ),
    CONSTRAINT review_assignments_maker_checker CHECK (
        reviewer_id IS NULL OR reviewer_id <> submitted_for_review_by
    ),
    CONSTRAINT review_assignments_decision_coherent CHECK (
        (status IN ('approved', 'rejected')
            AND reviewer_id IS NOT NULL AND decision = status AND reviewed_at IS NOT NULL)
        OR (status NOT IN ('approved', 'rejected')
            AND decision IS NULL AND reviewed_at IS NULL)
    ),
    CONSTRAINT review_assignments_notes_nonempty
        CHECK (review_notes IS NULL OR btrim(review_notes) <> ''),
    CONSTRAINT review_assignments_time_order CHECK (
        updated_at >= created_at AND (reviewed_at IS NULL OR reviewed_at >= created_at)
    )
);

CREATE FUNCTION geo_v2_reject_immutable_domain_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $immutable_domain_update$
BEGIN
    RAISE EXCEPTION '% rows are immutable after insert', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$immutable_domain_update$;

CREATE FUNCTION geo_v2_guard_evidence_asset_finalize()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $guard_evidence_finalize$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.project_id IS DISTINCT FROM OLD.project_id
       OR NEW.asset_type IS DISTINCT FROM OLD.asset_type
       OR NEW.storage_uri IS DISTINCT FROM OLD.storage_uri
       OR NEW.storage_key IS DISTINCT FROM OLD.storage_key
       OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
       OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
       OR NEW.content_type IS DISTINCT FROM OLD.content_type
       OR NEW.access_policy IS DISTINCT FROM OLD.access_policy
       OR NEW.retention_policy IS DISTINCT FROM OLD.retention_policy
       OR NEW.source_kind IS DISTINCT FROM OLD.source_kind
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR OLD.artifact_status <> 'pending'
       OR NEW.artifact_status NOT IN ('finalized', 'failed') THEN
        RAISE EXCEPTION 'evidence asset update is not an allowed finalize transition'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_evidence_finalize$;

CREATE FUNCTION geo_v2_guard_used_weight_profile_update()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard_weight_profile$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.visibility_score_runs AS score_run
        WHERE score_run.weight_profile_id = OLD.id
          AND score_run.project_id = OLD.project_id
    ) THEN
        RAISE EXCEPTION 'a weight profile referenced by a score run is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_weight_profile$;

CREATE FUNCTION geo_v2_guard_used_weight_component_update()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard_weight_component$
DECLARE
    profile_ref record;
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM 1 FROM public.visibility_weight_profiles AS profile
        WHERE profile.id = NEW.weight_profile_id
          AND profile.project_id = NEW.project_id
        FOR UPDATE;
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM 1 FROM public.visibility_weight_profiles AS profile
        WHERE profile.id = OLD.weight_profile_id
          AND profile.project_id = OLD.project_id
        FOR UPDATE;
    ELSE
        FOR profile_ref IN
            SELECT DISTINCT candidate.profile_id, candidate.project_id
            FROM (VALUES
                (OLD.weight_profile_id, OLD.project_id),
                (NEW.weight_profile_id, NEW.project_id)
            ) AS candidate(profile_id, project_id)
            ORDER BY candidate.project_id, candidate.profile_id
        LOOP
            PERFORM 1 FROM public.visibility_weight_profiles AS profile
            WHERE profile.id = profile_ref.profile_id
              AND profile.project_id = profile_ref.project_id
            FOR UPDATE;
        END LOOP;
    END IF;
    IF TG_OP = 'INSERT' AND EXISTS (
        SELECT 1 FROM public.visibility_score_runs AS score_run
        WHERE score_run.weight_profile_id = NEW.weight_profile_id
          AND score_run.project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'components cannot be added to a weight profile referenced by a score run'
            USING ERRCODE = '55000';
    ELSIF TG_OP = 'DELETE' AND EXISTS (
        SELECT 1 FROM public.visibility_score_runs AS score_run
        WHERE score_run.weight_profile_id = OLD.weight_profile_id
          AND score_run.project_id = OLD.project_id
    ) THEN
        RAISE EXCEPTION 'components of a weight profile referenced by a score run are immutable'
            USING ERRCODE = '55000';
    ELSIF TG_OP = 'UPDATE' AND EXISTS (
        SELECT 1 FROM public.visibility_score_runs AS score_run
        WHERE (score_run.weight_profile_id = OLD.weight_profile_id
                AND score_run.project_id = OLD.project_id)
           OR (score_run.weight_profile_id = NEW.weight_profile_id
                AND score_run.project_id = NEW.project_id)
    ) THEN
        RAISE EXCEPTION 'components cannot move from or into a referenced weight profile'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$guard_weight_component$;

CREATE FUNCTION geo_v2_guard_score_run_profile()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $guard_score_run_profile$
DECLARE
    profile_status text;
BEGIN
    SELECT profile.status INTO profile_status
    FROM public.visibility_weight_profiles AS profile
    WHERE profile.id = NEW.weight_profile_id
      AND profile.project_id = NEW.project_id
    FOR UPDATE;
    IF NOT FOUND OR (NEW.parent_job_id IS NULL AND profile_status <> 'active') THEN
        RAISE EXCEPTION 'new score runs require an active locked weight profile'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$guard_score_run_profile$;

CREATE FUNCTION geo_v2_require_finalized_score_evidence()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $require_finalized_score_evidence$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.evidence_assets AS asset
        WHERE asset.id = NEW.evidence_asset_id
          AND asset.project_id = NEW.project_id
          AND asset.tenant_id = NEW.tenant_id
          AND asset.artifact_status = 'finalized'
    ) THEN
        RAISE EXCEPTION 'score evidence must reference a finalized artifact'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$require_finalized_score_evidence$;

CREATE FUNCTION geo_v2_enqueue_durable_job_dispatch()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $enqueue_durable_dispatch$
DECLARE
    canonical_kind text;
    canonical_payload_hash text;
BEGIN
    canonical_kind := CASE TG_TABLE_NAME
        WHEN 'collection_jobs' THEN 'collection'
        WHEN 'visibility_score_runs' THEN 'visibility_score'
        WHEN 'retest_runs' THEN 'retest'
        ELSE NULL
    END;
    IF canonical_kind IS NULL THEN
        RAISE EXCEPTION 'unsupported durable job dispatch source'
            USING ERRCODE = '23514';
    END IF;
    canonical_payload_hash := encode(
        public.digest(
            jsonb_build_object(
                'job_kind', canonical_kind,
                'job_id', NEW.id,
                'project_id', NEW.project_id,
                'idempotency_key', NEW.idempotency_key,
                'replay_nonce', NEW.replay_nonce
            )::text,
            'sha256'
        ),
        'hex'
    );
    INSERT INTO public.durable_job_dispatch_outbox (
        tenant_id, project_id, job_kind, job_id,
        collection_job_id, visibility_score_run_id, retest_run_id,
        payload_hash
    ) VALUES (
        NEW.tenant_id,
        NEW.project_id,
        canonical_kind,
        NEW.id,
        CASE WHEN canonical_kind = 'collection' THEN NEW.id ELSE NULL END,
        CASE WHEN canonical_kind = 'visibility_score' THEN NEW.id ELSE NULL END,
        CASE WHEN canonical_kind = 'retest' THEN NEW.id ELSE NULL END,
        canonical_payload_hash
    );
    RETURN NEW;
END;
$enqueue_durable_dispatch$;

CREATE FUNCTION geo_v2_claim_durable_job_dispatch(
    p_worker_id text,
    p_lease_seconds integer,
    p_project_id uuid DEFAULT NULL,
    p_dispatch_id uuid DEFAULT NULL
)
RETURNS SETOF durable_job_dispatch_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $claim_durable_dispatch$
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = ''
       OR p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'durable dispatch claim arguments are invalid'
            USING ERRCODE = '22023';
    END IF;

    UPDATE public.durable_job_dispatch_outbox AS exhausted
    SET status = 'dead_letter',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        dispatched_at = statement_timestamp(), dispatched_by = 'lease-recovery',
        last_error_code = 'attempts_exhausted',
        last_error_message = 'dispatch lease expired after its attempt budget',
        updated_at = statement_timestamp()
    WHERE exhausted.status = 'dispatching'
      AND exhausted.lease_expires_at <= statement_timestamp()
      AND exhausted.attempt_count >= exhausted.max_attempts
      AND (p_project_id IS NULL OR exhausted.project_id = p_project_id)
      AND (p_dispatch_id IS NULL OR exhausted.id = p_dispatch_id);

    RETURN QUERY
    WITH candidate AS (
        SELECT dispatch_row.id
        FROM public.durable_job_dispatch_outbox AS dispatch_row
        WHERE (
                (dispatch_row.status = 'pending'
                    AND dispatch_row.next_attempt_at <= statement_timestamp())
                OR (dispatch_row.status = 'dispatching'
                    AND dispatch_row.lease_expires_at <= statement_timestamp())
              )
          AND dispatch_row.attempt_count < dispatch_row.max_attempts
          AND (p_project_id IS NULL OR dispatch_row.project_id = p_project_id)
          AND (p_dispatch_id IS NULL OR dispatch_row.id = p_dispatch_id)
        ORDER BY dispatch_row.next_attempt_at, dispatch_row.created_at, dispatch_row.id
        FOR UPDATE OF dispatch_row SKIP LOCKED
        LIMIT 1
    )
    UPDATE public.durable_job_dispatch_outbox AS claimed
    SET status = 'dispatching',
        attempt_count = claimed.attempt_count + 1,
        lease_owner = btrim(p_worker_id),
        lease_token = gen_random_uuid(),
        lease_expires_at = statement_timestamp()
            + make_interval(secs => p_lease_seconds),
        heartbeat_at = statement_timestamp(),
        last_error_code = NULL, last_error_message = NULL,
        updated_at = statement_timestamp()
    FROM candidate
    WHERE claimed.id = candidate.id
    RETURNING claimed.*;
END;
$claim_durable_dispatch$;

CREATE FUNCTION geo_v2_heartbeat_durable_job_dispatch(
    p_dispatch_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_lease_seconds integer
)
RETURNS durable_job_dispatch_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $heartbeat_durable_dispatch$
DECLARE
    heartbeat_row public.durable_job_dispatch_outbox%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'durable dispatch heartbeat arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    UPDATE public.durable_job_dispatch_outbox AS dispatch_row
    SET lease_expires_at = statement_timestamp()
            + make_interval(secs => p_lease_seconds),
        heartbeat_at = statement_timestamp(),
        updated_at = statement_timestamp()
    WHERE dispatch_row.id = p_dispatch_id
      AND dispatch_row.status = 'dispatching'
      AND dispatch_row.lease_owner = btrim(p_worker_id)
      AND dispatch_row.lease_token = p_lease_token
      AND dispatch_row.lease_expires_at > statement_timestamp()
    RETURNING dispatch_row.* INTO heartbeat_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'durable dispatch lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN heartbeat_row;
END;
$heartbeat_durable_dispatch$;

CREATE FUNCTION geo_v2_complete_durable_job_dispatch(
    p_dispatch_id uuid,
    p_worker_id text,
    p_lease_token uuid
)
RETURNS durable_job_dispatch_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $complete_durable_dispatch$
DECLARE
    completed_row public.durable_job_dispatch_outbox%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL THEN
        RAISE EXCEPTION 'durable dispatch completion arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    UPDATE public.durable_job_dispatch_outbox AS dispatch_row
    SET status = 'dispatched',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        dispatched_at = statement_timestamp(), dispatched_by = btrim(p_worker_id),
        last_error_code = NULL, last_error_message = NULL,
        updated_at = statement_timestamp()
    WHERE dispatch_row.id = p_dispatch_id
      AND dispatch_row.status = 'dispatching'
      AND dispatch_row.lease_owner = btrim(p_worker_id)
      AND dispatch_row.lease_token = p_lease_token
      AND dispatch_row.lease_expires_at > statement_timestamp()
    RETURNING dispatch_row.* INTO completed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'durable dispatch lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN completed_row;
END;
$complete_durable_dispatch$;

CREATE FUNCTION geo_v2_fail_durable_job_dispatch(
    p_dispatch_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_error_code text,
    p_error_message text,
    p_retryable boolean,
    p_retry_delay_seconds integer DEFAULT 0
)
RETURNS durable_job_dispatch_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fail_durable_dispatch$
DECLARE
    failed_row public.durable_job_dispatch_outbox%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_error_code IS NULL OR btrim(p_error_code) = ''
       OR p_error_message IS NULL OR btrim(p_error_message) = ''
       OR p_retryable IS NULL OR p_retry_delay_seconds IS NULL
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'durable dispatch failure arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    UPDATE public.durable_job_dispatch_outbox AS dispatch_row
    SET status = CASE
            WHEN p_retryable AND dispatch_row.attempt_count < dispatch_row.max_attempts
                THEN 'pending'
            ELSE 'dead_letter'
        END,
        next_attempt_at = CASE
            WHEN p_retryable AND dispatch_row.attempt_count < dispatch_row.max_attempts
                THEN statement_timestamp() + make_interval(secs => p_retry_delay_seconds)
            ELSE dispatch_row.next_attempt_at
        END,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        dispatched_at = CASE
            WHEN p_retryable AND dispatch_row.attempt_count < dispatch_row.max_attempts
                THEN NULL
            ELSE statement_timestamp()
        END,
        dispatched_by = CASE
            WHEN p_retryable AND dispatch_row.attempt_count < dispatch_row.max_attempts
                THEN NULL
            ELSE btrim(p_worker_id)
        END,
        last_error_code = btrim(p_error_code),
        last_error_message = btrim(p_error_message),
        updated_at = statement_timestamp()
    WHERE dispatch_row.id = p_dispatch_id
      AND dispatch_row.status = 'dispatching'
      AND dispatch_row.lease_owner = btrim(p_worker_id)
      AND dispatch_row.lease_token = p_lease_token
      AND dispatch_row.lease_expires_at > statement_timestamp()
    RETURNING dispatch_row.* INTO failed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'durable dispatch lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN failed_row;
END;
$fail_durable_dispatch$;

CREATE FUNCTION geo_v2_claim_artifact_finalize(
    p_worker_id text,
    p_lease_seconds integer,
    p_project_id uuid DEFAULT NULL
)
RETURNS SETOF artifact_finalize_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $claim_artifact_finalize$
DECLARE
    exhausted record;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = ''
       OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'artifact finalize claim arguments are invalid'
            USING ERRCODE = '22023';
    END IF;

    FOR exhausted IN
        UPDATE public.artifact_finalize_outbox AS outbox_row
        SET status = 'dead_lettered',
            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
            heartbeat_at = NULL, completed_at = statement_timestamp(),
            completed_by = 'lease-recovery',
            last_error_code = 'lease_expired_attempts_exhausted',
            last_error_message = 'artifact finalize lease exhausted its attempt budget',
            updated_at = statement_timestamp()
        WHERE outbox_row.status = 'running'
          AND outbox_row.lease_expires_at <= statement_timestamp()
          AND outbox_row.attempt_count >= outbox_row.max_attempts
          AND (p_project_id IS NULL OR outbox_row.project_id = p_project_id)
        RETURNING outbox_row.evidence_asset_id, outbox_row.project_id
    LOOP
        UPDATE public.evidence_assets AS asset_row
        SET artifact_status = 'failed',
            failure_reason = 'artifact finalize attempts exhausted'
        WHERE asset_row.id = exhausted.evidence_asset_id
          AND asset_row.project_id = exhausted.project_id
          AND asset_row.artifact_status = 'pending';
    END LOOP;

    RETURN QUERY
    WITH candidate AS (
        SELECT outbox_row.id
        FROM public.artifact_finalize_outbox AS outbox_row
        WHERE (
                (outbox_row.status = 'queued'
                    AND outbox_row.next_attempt_at <= statement_timestamp())
                OR (outbox_row.status = 'running'
                    AND outbox_row.lease_expires_at <= statement_timestamp())
              )
          AND outbox_row.attempt_count < outbox_row.max_attempts
          AND (p_project_id IS NULL OR outbox_row.project_id = p_project_id)
        ORDER BY
            CASE WHEN outbox_row.status = 'running' THEN 0 ELSE 1 END,
            coalesce(outbox_row.lease_expires_at, outbox_row.next_attempt_at),
            outbox_row.created_at, outbox_row.id
        FOR UPDATE OF outbox_row SKIP LOCKED
        LIMIT 1
    )
    UPDATE public.artifact_finalize_outbox AS claimed
    SET status = 'running',
        attempt_count = claimed.attempt_count + 1,
        lease_owner = btrim(p_worker_id),
        lease_token = gen_random_uuid(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        heartbeat_at = statement_timestamp(),
        started_at = coalesce(claimed.started_at, statement_timestamp()),
        completed_at = NULL, completed_by = NULL,
        updated_at = statement_timestamp()
    FROM candidate
    WHERE claimed.id = candidate.id
    RETURNING claimed.*;
END;
$claim_artifact_finalize$;

CREATE FUNCTION geo_v2_heartbeat_artifact_finalize(
    p_outbox_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_lease_seconds integer
)
RETURNS artifact_finalize_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $heartbeat_artifact_finalize$
DECLARE
    heartbeat_row public.artifact_finalize_outbox%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'artifact finalize heartbeat arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    UPDATE public.artifact_finalize_outbox AS outbox_row
    SET heartbeat_at = statement_timestamp(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        updated_at = statement_timestamp()
    WHERE outbox_row.id = p_outbox_id
      AND outbox_row.status = 'running'
      AND outbox_row.lease_owner = btrim(p_worker_id)
      AND outbox_row.lease_token = p_lease_token
      AND outbox_row.lease_expires_at > statement_timestamp()
    RETURNING outbox_row.* INTO heartbeat_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'artifact finalize lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN heartbeat_row;
END;
$heartbeat_artifact_finalize$;

CREATE FUNCTION geo_v2_complete_artifact_finalize(
    p_outbox_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_observed_content_hash text
)
RETURNS artifact_finalize_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $complete_artifact_finalize$
DECLARE
    locked_row public.artifact_finalize_outbox%ROWTYPE;
    completed_row public.artifact_finalize_outbox%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_observed_content_hash IS NULL
       OR p_observed_content_hash !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'artifact finalize completion arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO locked_row
    FROM public.artifact_finalize_outbox AS candidate
    WHERE candidate.id = p_outbox_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'artifact finalize record is unavailable'
            USING ERRCODE = '55000';
    END IF;
    IF locked_row.status = 'succeeded' THEN
        IF locked_row.expected_content_hash = p_observed_content_hash
           AND EXISTS (
                SELECT 1 FROM public.evidence_assets AS asset_row
                WHERE asset_row.id = locked_row.evidence_asset_id
                  AND asset_row.project_id = locked_row.project_id
                  AND asset_row.artifact_status = 'finalized'
                  AND asset_row.content_hash = p_observed_content_hash
           ) THEN
            RETURN locked_row;
        END IF;
        RAISE EXCEPTION 'completed artifact finalize hash is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    IF locked_row.status <> 'running'
       OR locked_row.lease_owner <> btrim(p_worker_id)
       OR locked_row.lease_token <> p_lease_token
       OR locked_row.lease_expires_at <= statement_timestamp() THEN
        RAISE EXCEPTION 'artifact finalize lease is lost' USING ERRCODE = '55000';
    END IF;
    IF locked_row.expected_content_hash <> p_observed_content_hash THEN
        RAISE EXCEPTION 'artifact content hash does not match the pending record'
            USING ERRCODE = '22000';
    END IF;

    UPDATE public.evidence_assets AS asset_row
    SET artifact_status = 'finalized',
        finalized_at = statement_timestamp(),
        finalized_by = btrim(p_worker_id),
        failure_reason = NULL
    WHERE asset_row.id = locked_row.evidence_asset_id
      AND asset_row.project_id = locked_row.project_id
      AND asset_row.artifact_status = 'pending'
      AND asset_row.content_hash = p_observed_content_hash;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'pending evidence asset does not match finalize request'
            USING ERRCODE = '55000';
    END IF;

    UPDATE public.artifact_finalize_outbox AS outbox_row
    SET status = 'succeeded',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL, completed_at = statement_timestamp(),
        completed_by = btrim(p_worker_id), last_error_code = NULL,
        last_error_message = NULL, updated_at = statement_timestamp()
    WHERE outbox_row.id = locked_row.id
      AND outbox_row.status = 'running'
      AND outbox_row.lease_owner = btrim(p_worker_id)
      AND outbox_row.lease_token = p_lease_token
    RETURNING outbox_row.* INTO completed_row;
    RETURN completed_row;
END;
$complete_artifact_finalize$;

CREATE FUNCTION geo_v2_fail_artifact_finalize(
    p_outbox_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_error_code text,
    p_error_message text,
    p_retryable boolean,
    p_retry_delay_seconds integer DEFAULT 0
)
RETURNS artifact_finalize_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fail_artifact_finalize$
DECLARE
    failed_row public.artifact_finalize_outbox%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_error_code IS NULL OR btrim(p_error_code) = ''
       OR p_error_message IS NULL OR btrim(p_error_message) = ''
       OR p_retryable IS NULL OR p_retry_delay_seconds < 0
       OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'artifact finalize failure arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    UPDATE public.artifact_finalize_outbox AS outbox_row
    SET status = CASE
            WHEN p_retryable AND outbox_row.attempt_count < outbox_row.max_attempts
                THEN 'queued'
            WHEN p_retryable THEN 'dead_lettered'
            ELSE 'failed'
        END,
        next_attempt_at = CASE
            WHEN p_retryable AND outbox_row.attempt_count < outbox_row.max_attempts
                THEN statement_timestamp() + make_interval(secs => p_retry_delay_seconds)
            ELSE outbox_row.next_attempt_at
        END,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = CASE
            WHEN p_retryable AND outbox_row.attempt_count < outbox_row.max_attempts
                THEN NULL ELSE statement_timestamp()
        END,
        completed_by = CASE
            WHEN p_retryable AND outbox_row.attempt_count < outbox_row.max_attempts
                THEN NULL ELSE btrim(p_worker_id)
        END,
        last_error_code = btrim(p_error_code),
        last_error_message = btrim(p_error_message),
        updated_at = statement_timestamp()
    WHERE outbox_row.id = p_outbox_id
      AND outbox_row.status = 'running'
      AND outbox_row.lease_owner = btrim(p_worker_id)
      AND outbox_row.lease_token = p_lease_token
      AND outbox_row.lease_expires_at > statement_timestamp()
    RETURNING outbox_row.* INTO failed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'artifact finalize lease is lost' USING ERRCODE = '55000';
    END IF;
    IF failed_row.status IN ('failed', 'dead_lettered') THEN
        UPDATE public.evidence_assets AS asset_row
        SET artifact_status = 'failed', failure_reason = btrim(p_error_message)
        WHERE asset_row.id = failed_row.evidence_asset_id
          AND asset_row.project_id = failed_row.project_id
          AND asset_row.artifact_status = 'pending';
    END IF;
    RETURN failed_row;
END;
$fail_artifact_finalize$;

CREATE FUNCTION geo_v2_refresh_collection_run_summary(
    p_collection_run_id uuid,
    p_project_id uuid
)
RETURNS collection_run_summaries
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $refresh_collection_summary$
DECLARE
    run_row public.collection_runs%ROWTYPE;
    summary_row public.collection_run_summaries%ROWTYPE;
    total_count integer;
    queued_count integer;
    running_count integer;
    succeeded_count integer;
    failed_count integer;
    cancelled_count integer;
    dead_lettered_count integer;
    terminal_count integer;
    first_started_at timestamptz;
BEGIN
    SELECT * INTO run_row
    FROM public.collection_runs AS candidate
    WHERE candidate.id = p_collection_run_id
      AND candidate.project_id = p_project_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'collection run summary scope is invalid'
            USING ERRCODE = '23503';
    END IF;

    SELECT
        count(*)::integer,
        count(*) FILTER (WHERE status = 'queued')::integer,
        count(*) FILTER (WHERE status = 'running')::integer,
        count(*) FILTER (WHERE status = 'succeeded')::integer,
        count(*) FILTER (WHERE status = 'failed')::integer,
        count(*) FILTER (WHERE status = 'cancelled')::integer,
        count(*) FILTER (WHERE status = 'dead_lettered')::integer,
        min(started_at)
    INTO total_count, queued_count, running_count, succeeded_count,
         failed_count, cancelled_count, dead_lettered_count, first_started_at
    FROM public.collection_jobs
    WHERE collection_run_id = run_row.id
      AND project_id = run_row.project_id;
    terminal_count := succeeded_count + failed_count + cancelled_count
        + dead_lettered_count;

    INSERT INTO public.collection_run_summaries (
        id, tenant_id, project_id, collection_run_id,
        queued_count, running_count, succeeded_count, failed_count,
        cancelled_count, dead_lettered_count, answer_present_count,
        citation_count, total_cost_usd, total_duration_ms,
        summary_version, computed_at, updated_at
    ) VALUES (
        gen_random_uuid(), run_row.tenant_id, run_row.project_id, run_row.id,
        queued_count, running_count, succeeded_count, failed_count,
        cancelled_count, dead_lettered_count,
        (SELECT count(*)::integer FROM public.answer_runs AS answer_row
         WHERE answer_row.collection_run_id = run_row.id
           AND answer_row.project_id = run_row.project_id
           AND answer_row.answer_present),
        (SELECT count(*)::integer
         FROM public.answer_citations AS citation_row
         JOIN public.answer_runs AS answer_row
           ON answer_row.id = citation_row.answer_run_id
          AND answer_row.project_id = citation_row.project_id
         WHERE answer_row.collection_run_id = run_row.id
           AND answer_row.project_id = run_row.project_id),
        coalesce((
            SELECT sum(cost_row.total_cost)
            FROM public.collection_costs AS cost_row
            JOIN public.collection_jobs AS job_row
              ON job_row.id = cost_row.collection_job_id
             AND job_row.project_id = cost_row.project_id
            WHERE job_row.collection_run_id = run_row.id
              AND job_row.project_id = run_row.project_id
        ), 0),
        coalesce((
            SELECT sum(answer_row.duration_ms)
            FROM public.answer_runs AS answer_row
            WHERE answer_row.collection_run_id = run_row.id
              AND answer_row.project_id = run_row.project_id
        ), 0),
        1, statement_timestamp(), statement_timestamp()
    )
    ON CONFLICT (collection_run_id) DO UPDATE
    SET queued_count = EXCLUDED.queued_count,
        running_count = EXCLUDED.running_count,
        succeeded_count = EXCLUDED.succeeded_count,
        failed_count = EXCLUDED.failed_count,
        cancelled_count = EXCLUDED.cancelled_count,
        dead_lettered_count = EXCLUDED.dead_lettered_count,
        answer_present_count = EXCLUDED.answer_present_count,
        citation_count = EXCLUDED.citation_count,
        total_cost_usd = EXCLUDED.total_cost_usd,
        total_duration_ms = EXCLUDED.total_duration_ms,
        summary_version = public.collection_run_summaries.summary_version + 1,
        computed_at = EXCLUDED.computed_at,
        updated_at = EXCLUDED.updated_at
    RETURNING * INTO summary_row;

    UPDATE public.collection_runs AS target
    SET status = CASE
            WHEN total_count = 0 THEN target.status
            WHEN terminal_count = total_count AND succeeded_count = total_count
                THEN 'succeeded'
            WHEN terminal_count = total_count AND succeeded_count > 0
                THEN 'partial_succeeded'
            WHEN terminal_count = total_count AND cancelled_count = total_count
                THEN 'cancelled'
            WHEN terminal_count = total_count THEN 'failed'
            WHEN running_count > 0 THEN 'running'
            ELSE 'queued'
        END,
        started_at = CASE
            WHEN total_count > 0 AND terminal_count = total_count
                THEN coalesce(
                    target.started_at,
                    greatest(coalesce(first_started_at, target.created_at), target.created_at)
                )
            ELSE coalesce(
                target.started_at,
                greatest(first_started_at, target.created_at)
            )
        END,
        completed_at = CASE
            WHEN total_count > 0 AND terminal_count = total_count
                THEN statement_timestamp()
            ELSE NULL
        END,
        updated_at = statement_timestamp()
    WHERE target.id = run_row.id
      AND target.project_id = run_row.project_id;

    RETURN summary_row;
END;
$refresh_collection_summary$;

-- Claim functions lock only during their calling transaction. Callers MUST
-- commit immediately after claim and MUST NOT hold that transaction open while
-- invoking an external provider. Completion is a new fenced transaction.
CREATE FUNCTION geo_v2_claim_collection_job(
    p_worker_id text,
    p_lease_seconds integer,
    p_project_id uuid DEFAULT NULL
)
RETURNS SETOF collection_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $claim_collection_job$
DECLARE
    recovered record;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'worker_id must be nonempty' USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease_seconds must be between 5 and 3600'
            USING ERRCODE = '22023';
    END IF;

    FOR recovered IN
        UPDATE public.collection_jobs AS cancelled
        SET status = 'cancelled',
            lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
            heartbeat_at = NULL,
            completed_at = statement_timestamp(), completed_by = 'lease-recovery',
            updated_at = statement_timestamp()
        WHERE cancelled.status = 'running'
          AND cancelled.cancel_requested_at IS NOT NULL
          AND cancelled.lease_expires_at <= statement_timestamp()
          AND (p_project_id IS NULL OR cancelled.project_id = p_project_id)
        RETURNING cancelled.collection_run_id, cancelled.project_id
    LOOP
        PERFORM public.geo_v2_refresh_collection_run_summary(
            recovered.collection_run_id, recovered.project_id
        );
    END LOOP;

    FOR recovered IN
        UPDATE public.collection_jobs AS exhausted
        SET status = 'dead_lettered',
            lease_owner = NULL,
            lease_token = NULL,
            lease_expires_at = NULL,
            heartbeat_at = NULL,
            completed_at = statement_timestamp(),
            completed_by = 'lease-recovery',
            last_error_code = 'lease_expired_attempts_exhausted',
            last_error_message = 'expired lease reached the configured attempt budget',
            updated_at = statement_timestamp()
        WHERE exhausted.status = 'running'
          AND exhausted.cancel_requested_at IS NULL
          AND exhausted.lease_expires_at <= statement_timestamp()
          AND exhausted.attempt_count >= exhausted.max_attempts
          AND (p_project_id IS NULL OR exhausted.project_id = p_project_id)
        RETURNING exhausted.collection_run_id, exhausted.project_id
    LOOP
        PERFORM public.geo_v2_refresh_collection_run_summary(
            recovered.collection_run_id, recovered.project_id
        );
    END LOOP;

    RETURN QUERY
    WITH candidate AS (
        SELECT job_row.id, job_row.status AS claimed_from
        FROM public.collection_jobs AS job_row
        WHERE (
                (job_row.status = 'queued'
                    AND job_row.next_attempt_at <= statement_timestamp()
                    AND job_row.cancel_requested_at IS NULL)
                OR (job_row.status = 'running'
                    AND job_row.lease_expires_at <= statement_timestamp()
                    AND job_row.cancel_requested_at IS NULL)
              )
          AND job_row.attempt_count < job_row.max_attempts
          AND (p_project_id IS NULL OR job_row.project_id = p_project_id)
        ORDER BY
            CASE WHEN job_row.status = 'running' THEN 0 ELSE 1 END,
            job_row.priority DESC,
            coalesce(job_row.lease_expires_at, job_row.next_attempt_at),
            job_row.created_at,
            job_row.id
        FOR UPDATE OF job_row SKIP LOCKED
        LIMIT 1
    )
    UPDATE public.collection_jobs AS claimed
    SET status = 'running',
        attempt_count = claimed.attempt_count + 1,
        lease_owner = btrim(p_worker_id),
        lease_token = gen_random_uuid(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        heartbeat_at = statement_timestamp(),
        started_at = coalesce(claimed.started_at, statement_timestamp()),
        completed_at = NULL,
        completed_by = NULL,
        updated_at = statement_timestamp()
    FROM candidate
    WHERE claimed.id = candidate.id
    RETURNING claimed.*;
END;
$claim_collection_job$;

CREATE FUNCTION geo_v2_heartbeat_collection_job(
    p_job_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_lease_seconds integer
)
RETURNS collection_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $heartbeat_collection_job$
DECLARE
    heartbeat_row public.collection_jobs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = ''
       OR p_lease_token IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'heartbeat lease arguments are invalid' USING ERRCODE = '22023';
    END IF;
    UPDATE public.collection_jobs AS job_row
    SET heartbeat_at = statement_timestamp(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        updated_at = statement_timestamp()
    WHERE job_row.id = p_job_id
      AND job_row.status = 'running'
      AND job_row.lease_owner = btrim(p_worker_id)
      AND job_row.lease_token = p_lease_token
      AND job_row.lease_expires_at > statement_timestamp()
      AND job_row.cancel_requested_at IS NULL
    RETURNING job_row.* INTO heartbeat_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'collection job lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN heartbeat_row;
END;
$heartbeat_collection_job$;

CREATE FUNCTION geo_v2_persist_collection_result(
    p_job collection_jobs,
    p_result_payload jsonb
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $persist_collection_result$
DECLARE
    job_row public.collection_jobs%ROWTYPE := p_job;
    citation_item jsonb;
    evidence_item record;
    link_item record;
    mention_item record;
    cost_item record;
    call_item record;
    analysis_item jsonb;
    answer_run_id uuid;
    raw_answer_id uuid;
    analysis_id uuid;
    allowed_keys text[] := ARRAY[
        'answer_run_id', 'raw_answer_id', 'status', 'answer_present',
        'surface_triggered', 'provider_request_id', 'configured_model',
        'provider_reported_model', 'collector_version', 'collected_at',
        'duration_ms', 'answer_text', 'raw_payload_hash', 'content_type',
        'data_classification', 'retention_policy', 'citations',
        'evidence_assets', 'raw_answer_evidence_assets',
        'citation_evidence_assets', 'analysis', 'collection_costs',
        'model_call_logs'
    ];
    citation_keys text[] := ARRAY[
        'id', 'position', 'source_url', 'normalized_url_hash', 'source_domain',
        'source_title', 'source_snippet', 'source_type',
        'public_disclosure_allowed', 'quotation_allowed', 'attribution_required'
    ];
BEGIN
    IF job_row.id IS NULL OR job_row.status <> 'running'
       OR job_row.cancel_requested_at IS NOT NULL
       OR p_result_payload IS NULL OR jsonb_typeof(p_result_payload) <> 'object'
       OR NOT p_result_payload ?& allowed_keys
       OR p_result_payload - allowed_keys <> '{}'::jsonb
       OR jsonb_typeof(p_result_payload->'citations') <> 'array'
       OR jsonb_typeof(p_result_payload->'evidence_assets') <> 'array'
       OR jsonb_typeof(p_result_payload->'raw_answer_evidence_assets') <> 'array'
       OR jsonb_typeof(p_result_payload->'citation_evidence_assets') <> 'array'
       OR jsonb_typeof(p_result_payload->'analysis') <> 'object'
       OR jsonb_typeof(p_result_payload->'collection_costs') <> 'array'
       OR jsonb_typeof(p_result_payload->'model_call_logs') <> 'array' THEN
        RAISE EXCEPTION 'collection result payload shape is invalid'
            USING ERRCODE = '22023';
    END IF;

    answer_run_id := (p_result_payload->>'answer_run_id')::uuid;
    raw_answer_id := (p_result_payload->>'raw_answer_id')::uuid;
    INSERT INTO public.answer_runs (
        id, tenant_id, project_id, collection_job_id, collection_run_id,
        monitoring_query_id, status, answer_present, surface_triggered,
        platform, surface, access_method, sample_index, provider_request_id,
        configured_model, provider_reported_model, collector_version,
        collected_at, duration_ms
    ) VALUES (
        answer_run_id, job_row.tenant_id, job_row.project_id, job_row.id,
        job_row.collection_run_id, job_row.monitoring_query_id,
        p_result_payload->>'status',
        (p_result_payload->>'answer_present')::boolean,
        (p_result_payload->>'surface_triggered')::boolean,
        job_row.platform, job_row.surface, job_row.access_method, job_row.sample_index,
        p_result_payload->>'provider_request_id',
        p_result_payload->>'configured_model',
        p_result_payload->>'provider_reported_model',
        p_result_payload->>'collector_version',
        (p_result_payload->>'collected_at')::timestamptz,
        (p_result_payload->>'duration_ms')::bigint
    );

    INSERT INTO public.raw_answers (
        id, tenant_id, project_id, answer_run_id, answer_text,
        raw_payload_hash, content_type, data_classification, retention_policy
    ) VALUES (
        raw_answer_id, job_row.tenant_id, job_row.project_id, answer_run_id,
        p_result_payload->>'answer_text', p_result_payload->>'raw_payload_hash',
        p_result_payload->>'content_type',
        p_result_payload->>'data_classification', p_result_payload->>'retention_policy'
    );

    FOR citation_item IN
        SELECT item.value FROM jsonb_array_elements(
            p_result_payload->'citations'
        ) AS item(value)
    LOOP
        IF jsonb_typeof(citation_item) <> 'object'
           OR NOT citation_item ?& citation_keys
           OR citation_item - citation_keys <> '{}'::jsonb THEN
            RAISE EXCEPTION 'collection citation payload shape is invalid'
                USING ERRCODE = '22023';
        END IF;
        INSERT INTO public.answer_citations (
            id, tenant_id, project_id, answer_run_id, raw_answer_id,
            citation_position, source_url, normalized_url_hash, source_domain,
            source_title, source_snippet, source_type,
            public_disclosure_allowed, quotation_allowed, attribution_required
        ) VALUES (
            (citation_item->>'id')::uuid,
            job_row.tenant_id,
            job_row.project_id,
            answer_run_id,
            raw_answer_id,
            (citation_item->>'position')::integer,
            citation_item->>'source_url',
            citation_item->>'normalized_url_hash',
            citation_item->>'source_domain',
            citation_item->>'source_title',
            citation_item->>'source_snippet',
            citation_item->>'source_type',
            (citation_item->>'public_disclosure_allowed')::boolean,
            (citation_item->>'quotation_allowed')::boolean,
            (citation_item->>'attribution_required')::boolean
        );
    END LOOP;

    FOR evidence_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'evidence_assets') AS item(
            id uuid,
            finalize_outbox_id uuid,
            asset_type text,
            storage_uri text,
            storage_key text,
            content_hash text,
            size_bytes bigint,
            content_type text,
            access_policy text,
            retention_policy text,
            source_kind text,
            created_by text
        )
    LOOP
        INSERT INTO public.evidence_assets (
            id, tenant_id, project_id, asset_type, storage_uri, storage_key,
            content_hash, size_bytes, content_type, access_policy,
            retention_policy, source_kind, artifact_status, created_by
        ) VALUES (
            evidence_item.id, job_row.tenant_id, job_row.project_id,
            evidence_item.asset_type, evidence_item.storage_uri,
            evidence_item.storage_key, evidence_item.content_hash,
            evidence_item.size_bytes, evidence_item.content_type,
            evidence_item.access_policy, evidence_item.retention_policy,
            evidence_item.source_kind, 'pending', evidence_item.created_by
        );
        INSERT INTO public.artifact_finalize_outbox (
            id, tenant_id, project_id, evidence_asset_id, expected_content_hash
        ) VALUES (
            evidence_item.finalize_outbox_id, job_row.tenant_id, job_row.project_id,
            evidence_item.id, evidence_item.content_hash
        );
    END LOOP;

    FOR link_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'raw_answer_evidence_assets'
        ) AS item(id uuid, evidence_asset_id uuid, evidence_role text)
    LOOP
        INSERT INTO public.raw_answer_evidence_assets (
            id, tenant_id, project_id, raw_answer_id,
            evidence_asset_id, evidence_role
        ) VALUES (
            link_item.id, job_row.tenant_id, job_row.project_id, raw_answer_id,
            link_item.evidence_asset_id, link_item.evidence_role
        );
    END LOOP;

    FOR link_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'citation_evidence_assets'
        ) AS item(
            id uuid,
            answer_citation_id uuid,
            evidence_asset_id uuid,
            evidence_role text
        )
    LOOP
        INSERT INTO public.answer_citation_evidence_assets (
            id, tenant_id, project_id, answer_citation_id,
            evidence_asset_id, evidence_role
        ) VALUES (
            link_item.id, job_row.tenant_id, job_row.project_id,
            link_item.answer_citation_id, link_item.evidence_asset_id,
            link_item.evidence_role
        );
    END LOOP;

    analysis_item := p_result_payload->'analysis';
    IF NOT analysis_item ?& ARRAY[
            'id', 'analysis_version', 'analyzer_kind', 'trigger_detected',
            'mention_detected', 'recommendation_detected', 'citation_detected',
            'sentiment_score', 'confidence', 'claim_inventory_complete',
            'claim_inventory_reviewed_by', 'claim_inventory_reviewed_at',
            'analysis_payload', 'analysis_hash', 'created_by',
            'entity_mentions', 'evidence_assets'
        ]
       OR analysis_item - ARRAY[
            'id', 'analysis_version', 'analyzer_kind', 'trigger_detected',
            'mention_detected', 'recommendation_detected', 'citation_detected',
            'sentiment_score', 'confidence', 'claim_inventory_complete',
            'claim_inventory_reviewed_by', 'claim_inventory_reviewed_at',
            'analysis_payload', 'analysis_hash', 'created_by',
            'entity_mentions', 'evidence_assets'
        ] <> '{}'::jsonb
       OR jsonb_typeof(analysis_item->'analysis_payload') <> 'object'
       OR jsonb_typeof(analysis_item->'entity_mentions') <> 'array'
       OR jsonb_typeof(analysis_item->'evidence_assets') <> 'array' THEN
        RAISE EXCEPTION 'answer analysis payload shape is invalid'
            USING ERRCODE = '22023';
    END IF;
    analysis_id := (analysis_item->>'id')::uuid;
    INSERT INTO public.answer_analyses (
        id, tenant_id, project_id, answer_run_id, analysis_version,
        analyzer_kind, trigger_detected, mention_detected,
        recommendation_detected, citation_detected, sentiment_score,
        confidence, claim_inventory_complete, claim_inventory_reviewed_by,
        claim_inventory_reviewed_at, analysis_payload, analysis_hash, created_by
    ) VALUES (
        analysis_id, job_row.tenant_id, job_row.project_id, answer_run_id,
        analysis_item->>'analysis_version', analysis_item->>'analyzer_kind',
        (analysis_item->>'trigger_detected')::boolean,
        (analysis_item->>'mention_detected')::boolean,
        (analysis_item->>'recommendation_detected')::boolean,
        (analysis_item->>'citation_detected')::boolean,
        (analysis_item->>'sentiment_score')::numeric,
        (analysis_item->>'confidence')::numeric,
        (analysis_item->>'claim_inventory_complete')::boolean,
        analysis_item->>'claim_inventory_reviewed_by',
        (analysis_item->>'claim_inventory_reviewed_at')::timestamptz,
        analysis_item->'analysis_payload', analysis_item->>'analysis_hash',
        analysis_item->>'created_by'
    );

    FOR mention_item IN
        SELECT * FROM jsonb_to_recordset(analysis_item->'entity_mentions') AS item(
            id uuid,
            entity_id uuid,
            mention_role text,
            mention_count integer,
            first_position integer,
            confidence numeric
        )
    LOOP
        INSERT INTO public.answer_analysis_entity_mentions (
            id, tenant_id, project_id, answer_analysis_id, entity_id,
            mention_role, mention_count, first_position, confidence
        ) VALUES (
            mention_item.id, job_row.tenant_id, job_row.project_id, analysis_id,
            mention_item.entity_id, mention_item.mention_role,
            mention_item.mention_count, mention_item.first_position,
            mention_item.confidence
        );
    END LOOP;

    FOR link_item IN
        SELECT * FROM jsonb_to_recordset(analysis_item->'evidence_assets') AS item(
            id uuid,
            evidence_asset_id uuid,
            evidence_role text
        )
    LOOP
        INSERT INTO public.answer_analysis_evidence_assets (
            id, tenant_id, project_id, answer_analysis_id,
            evidence_asset_id, evidence_role
        ) VALUES (
            link_item.id, job_row.tenant_id, job_row.project_id, analysis_id,
            link_item.evidence_asset_id, link_item.evidence_role
        );
    END LOOP;

    FOR cost_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'collection_costs') AS item(
            id uuid,
            provider text,
            configured_model text,
            currency text,
            prompt_tokens integer,
            completion_tokens integer,
            provider_cost numeric,
            vendor_cost numeric,
            compute_cost numeric,
            total_cost numeric,
            cost_method text,
            duration_ms bigint,
            recorded_at timestamptz
        )
    LOOP
        INSERT INTO public.collection_costs (
            id, tenant_id, project_id, collection_job_id, answer_run_id,
            provider, configured_model, currency, prompt_tokens,
            completion_tokens, provider_cost, vendor_cost, compute_cost,
            total_cost, cost_method, duration_ms, recorded_at
        ) VALUES (
            cost_item.id, job_row.tenant_id, job_row.project_id, job_row.id,
            answer_run_id, cost_item.provider, cost_item.configured_model,
            cost_item.currency, cost_item.prompt_tokens,
            cost_item.completion_tokens, cost_item.provider_cost,
            cost_item.vendor_cost, cost_item.compute_cost, cost_item.total_cost,
            cost_item.cost_method, cost_item.duration_ms, cost_item.recorded_at
        );
    END LOOP;

    FOR call_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'model_call_logs') AS item(
            id uuid,
            answer_analysis_id uuid,
            purpose text,
            provider text,
            provider_request_id text,
            configured_model text,
            provider_reported_model text,
            prompt_template_release text,
            request_hash text,
            response_hash text,
            prompt_tokens integer,
            completion_tokens integer,
            cost_usd numeric,
            latency_ms bigint,
            finish_reason text,
            status text,
            error_code text
        )
    LOOP
        IF call_item.answer_analysis_id IS NOT NULL
           AND call_item.answer_analysis_id <> analysis_id THEN
            RAISE EXCEPTION 'model call analysis scope does not match collection result'
                USING ERRCODE = '23514';
        END IF;
        INSERT INTO public.model_call_logs (
            id, tenant_id, project_id, collection_job_id, answer_analysis_id,
            purpose, provider, provider_request_id, configured_model,
            provider_reported_model, prompt_template_release, request_hash,
            response_hash, prompt_tokens, completion_tokens, cost_usd,
            latency_ms, finish_reason, status, error_code
        ) VALUES (
            call_item.id, job_row.tenant_id, job_row.project_id, job_row.id,
            call_item.answer_analysis_id, call_item.purpose, call_item.provider,
            call_item.provider_request_id, call_item.configured_model,
            call_item.provider_reported_model, call_item.prompt_template_release,
            call_item.request_hash, call_item.response_hash,
            call_item.prompt_tokens, call_item.completion_tokens,
            call_item.cost_usd, call_item.latency_ms, call_item.finish_reason,
            call_item.status, call_item.error_code
        );
    END LOOP;
    RETURN answer_run_id;
EXCEPTION
    WHEN invalid_text_representation OR datetime_field_overflow THEN
        RAISE EXCEPTION 'collection result payload contains an invalid typed value'
            USING ERRCODE = '22023';
END;
$persist_collection_result$;

CREATE FUNCTION geo_v2_complete_collection_job(
    p_job_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_result_payload jsonb
)
RETURNS collection_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $complete_collection_job$
DECLARE
    locked_job public.collection_jobs%ROWTYPE;
    completed_row public.collection_jobs%ROWTYPE;
    answer_run_id uuid;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_result_payload IS NULL OR jsonb_typeof(p_result_payload) <> 'object' THEN
        RAISE EXCEPTION 'completion arguments are invalid' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO locked_job
    FROM public.collection_jobs AS candidate
    WHERE candidate.id = p_job_id
      AND candidate.status = 'running'
      AND candidate.lease_owner = btrim(p_worker_id)
      AND candidate.lease_token = p_lease_token
      AND candidate.lease_expires_at > statement_timestamp()
      AND candidate.cancel_requested_at IS NULL
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'collection job lease is lost or cancellation is pending'
            USING ERRCODE = '55000';
    END IF;

    answer_run_id := public.geo_v2_persist_collection_result(
        locked_job, p_result_payload
    );
    UPDATE public.collection_jobs AS job_row
    SET status = 'succeeded',
        lease_owner = NULL,
        lease_token = NULL,
        lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(),
        completed_by = btrim(p_worker_id),
        last_error_code = NULL,
        last_error_message = NULL,
        result_summary = jsonb_build_object('answer_run_id', answer_run_id),
        updated_at = statement_timestamp()
    WHERE job_row.id = p_job_id
      AND job_row.status = 'running'
      AND job_row.lease_owner = btrim(p_worker_id)
      AND job_row.lease_token = p_lease_token
      AND job_row.lease_expires_at > statement_timestamp()
      AND job_row.cancel_requested_at IS NULL
      AND EXISTS (
            SELECT 1 FROM public.answer_runs AS answer_row
            WHERE answer_row.collection_job_id = job_row.id
              AND answer_row.project_id = job_row.project_id
      )
    RETURNING job_row.* INTO completed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'collection job finalization lost its fenced lease'
            USING ERRCODE = '55000';
    END IF;
    PERFORM public.geo_v2_refresh_collection_run_summary(
        completed_row.collection_run_id, completed_row.project_id
    );
    RETURN completed_row;
END;
$complete_collection_job$;

CREATE FUNCTION geo_v2_fail_collection_job(
    p_job_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_error_code text,
    p_error_message text,
    p_retryable boolean,
    p_retry_delay_seconds integer DEFAULT 0
)
RETURNS collection_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fail_collection_job$
DECLARE
    failed_row public.collection_jobs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_error_code IS NULL OR btrim(p_error_code) = ''
       OR p_error_message IS NULL OR btrim(p_error_message) = ''
       OR p_retryable IS NULL
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'failure arguments are invalid' USING ERRCODE = '22023';
    END IF;
    UPDATE public.collection_jobs AS job_row
    SET status = CASE
            WHEN p_retryable AND job_row.attempt_count < job_row.max_attempts THEN 'queued'
            WHEN p_retryable THEN 'dead_lettered'
            ELSE 'failed'
        END,
        next_attempt_at = CASE
            WHEN p_retryable AND job_row.attempt_count < job_row.max_attempts
                THEN statement_timestamp() + make_interval(secs => p_retry_delay_seconds)
            ELSE job_row.next_attempt_at
        END,
        lease_owner = NULL,
        lease_token = NULL,
        lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = CASE
            WHEN p_retryable AND job_row.attempt_count < job_row.max_attempts THEN NULL
            ELSE statement_timestamp()
        END,
        completed_by = CASE
            WHEN p_retryable AND job_row.attempt_count < job_row.max_attempts THEN NULL
            ELSE btrim(p_worker_id)
        END,
        last_error_code = btrim(p_error_code),
        last_error_message = btrim(p_error_message),
        updated_at = statement_timestamp()
    WHERE job_row.id = p_job_id
      AND job_row.status = 'running'
      AND job_row.lease_owner = btrim(p_worker_id)
      AND job_row.lease_token = p_lease_token
      AND job_row.lease_expires_at > statement_timestamp()
      AND job_row.cancel_requested_at IS NULL
    RETURNING job_row.* INTO failed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'collection job lease is lost' USING ERRCODE = '55000';
    END IF;
    IF failed_row.status IN ('failed', 'dead_lettered') THEN
        PERFORM public.geo_v2_refresh_collection_run_summary(
            failed_row.collection_run_id, failed_row.project_id
        );
    END IF;
    RETURN failed_row;
END;
$fail_collection_job$;

CREATE FUNCTION geo_v2_record_job_command_audit(
    p_tenant_id uuid,
    p_project_id uuid,
    p_event_type text,
    p_target_type text,
    p_target_id uuid,
    p_actor_type text,
    p_actor_id text,
    p_reason text,
    p_input_refs jsonb DEFAULT '{}'::jsonb,
    p_output_refs jsonb DEFAULT '{}'::jsonb
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $record_job_command_audit$
BEGIN
    IF p_event_type IS NULL OR btrim(p_event_type) = ''
       OR p_target_type IS NULL OR btrim(p_target_type) = ''
       OR p_actor_type NOT IN ('user', 'system', 'worker', 'service')
       OR p_actor_id IS NULL OR btrim(p_actor_id) = ''
       OR p_input_refs IS NULL OR jsonb_typeof(p_input_refs) <> 'object'
       OR p_output_refs IS NULL OR jsonb_typeof(p_output_refs) <> 'object' THEN
        RAISE EXCEPTION 'job audit arguments are invalid' USING ERRCODE = '22023';
    END IF;
    INSERT INTO public.audit_events (
        id, tenant_id, project_id, event_type, actor_type, actor_id,
        target_type, target_id, input_refs, output_refs, method_version, reason
    ) VALUES (
        gen_random_uuid(), p_tenant_id, p_project_id, p_event_type,
        p_actor_type, btrim(p_actor_id), p_target_type, p_target_id::text,
        p_input_refs, p_output_refs, 'durable_job_v2', p_reason
    );
END;
$record_job_command_audit$;

CREATE FUNCTION geo_v2_ack_collection_job_cancel(
    p_job_id uuid,
    p_worker_id text,
    p_lease_token uuid
)
RETURNS collection_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $ack_collection_cancel$
DECLARE
    cancelled_row public.collection_jobs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL THEN
        RAISE EXCEPTION 'cancel acknowledgement arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    UPDATE public.collection_jobs AS job_row
    SET status = 'cancelled',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = btrim(p_worker_id),
        updated_at = statement_timestamp()
    WHERE job_row.id = p_job_id
      AND job_row.status = 'running'
      AND job_row.cancel_requested_at IS NOT NULL
      AND job_row.lease_owner = btrim(p_worker_id)
      AND job_row.lease_token = p_lease_token
      AND job_row.lease_expires_at > statement_timestamp()
    RETURNING job_row.* INTO cancelled_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'collection job cancellation lease is lost'
            USING ERRCODE = '55000';
    END IF;
    PERFORM public.geo_v2_record_job_command_audit(
        cancelled_row.tenant_id, cancelled_row.project_id,
        'collection_job.cancelled', 'collection_job', cancelled_row.id,
        'worker', p_worker_id, cancelled_row.cancel_reason,
        jsonb_build_object('attempt_count', cancelled_row.attempt_count), '{}'::jsonb
    );
    PERFORM public.geo_v2_refresh_collection_run_summary(
        cancelled_row.collection_run_id, cancelled_row.project_id
    );
    RETURN cancelled_row;
END;
$ack_collection_cancel$;

CREATE FUNCTION geo_v2_request_collection_job_cancel(
    p_job_id uuid,
    p_reason text
)
RETURNS collection_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $request_collection_cancel$
DECLARE
    target_row public.collection_jobs%ROWTYPE;
    actor_id text;
    event_type text;
BEGIN
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'cancel reason must be nonempty' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO target_row
    FROM public.collection_jobs AS job_row
    WHERE job_row.id = p_job_id
    FOR UPDATE;
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        target_row.project_id, target_row.tenant_id, 'collection.run'
    ) THEN
        RAISE EXCEPTION 'collection job is not accessible' USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geo_v2_resolve_session_context() AS context;

    IF target_row.status = 'queued' THEN
        UPDATE public.collection_jobs AS job_row
        SET status = 'cancelled',
            cancel_requested_at = statement_timestamp(),
            cancel_requested_by = actor_id,
            cancel_reason = btrim(p_reason),
            completed_at = statement_timestamp(),
            completed_by = actor_id,
            updated_at = statement_timestamp()
        WHERE job_row.id = p_job_id
        RETURNING job_row.* INTO target_row;
        event_type := 'collection_job.cancelled';
    ELSIF target_row.status = 'running' THEN
        IF target_row.cancel_requested_at IS NULL THEN
            UPDATE public.collection_jobs AS job_row
            SET cancel_requested_at = statement_timestamp(),
                cancel_requested_by = actor_id,
                cancel_reason = btrim(p_reason),
                updated_at = statement_timestamp()
            WHERE job_row.id = p_job_id
            RETURNING job_row.* INTO target_row;
            event_type := 'collection_job.cancel_requested';
        END IF;
    ELSIF target_row.status <> 'cancelled' THEN
        RAISE EXCEPTION 'only queued or running collection jobs can be cancelled'
            USING ERRCODE = '55000';
    END IF;

    IF event_type IS NOT NULL THEN
        PERFORM public.geo_v2_record_job_command_audit(
            target_row.tenant_id, target_row.project_id, event_type,
            'collection_job', target_row.id, 'user', actor_id, p_reason
        );
        IF target_row.status = 'cancelled' THEN
            PERFORM public.geo_v2_refresh_collection_run_summary(
                target_row.collection_run_id, target_row.project_id
            );
        END IF;
    END IF;
    RETURN target_row;
END;
$request_collection_cancel$;

CREATE FUNCTION geo_v2_replay_collection_job(
    p_source_job_id uuid,
    p_new_job_id uuid,
    p_idempotency_key text
)
RETURNS collection_jobs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $replay_collection_job$
DECLARE
    source_row public.collection_jobs%ROWTYPE;
    child_row public.collection_jobs%ROWTYPE;
    actor_id text;
    next_nonce integer;
BEGIN
    IF p_new_job_id IS NULL OR p_idempotency_key IS NULL
       OR btrim(p_idempotency_key) = '' THEN
        RAISE EXCEPTION 'replay arguments are invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO source_row
    FROM public.collection_jobs AS job_row
    WHERE job_row.id = p_source_job_id
    FOR UPDATE;
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        source_row.project_id, source_row.tenant_id, 'collection.run'
    ) THEN
        RAISE EXCEPTION 'collection job is not accessible' USING ERRCODE = '42501';
    END IF;
    IF source_row.status NOT IN ('failed', 'cancelled', 'dead_lettered') THEN
        RAISE EXCEPTION 'only terminal unsuccessful collection jobs can be replayed'
            USING ERRCODE = '55000';
    END IF;
    next_nonce := source_row.replay_nonce + 1;
    SELECT * INTO child_row
    FROM public.collection_jobs AS existing
    WHERE existing.project_id = source_row.project_id
      AND existing.parent_job_id = source_row.id
      AND existing.replay_nonce = next_nonce;
    IF FOUND THEN
        IF child_row.id = p_new_job_id
           AND child_row.idempotency_key = btrim(p_idempotency_key) THEN
            RETURN child_row;
        END IF;
        RAISE EXCEPTION 'collection replay idempotency conflict' USING ERRCODE = '23505';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geo_v2_resolve_session_context() AS context;
    BEGIN
        INSERT INTO public.collection_jobs (
            id, tenant_id, project_id, collection_run_id, monitoring_query_id,
            platform, surface, access_method, sample_index, idempotency_key,
            parent_job_id, replay_nonce, priority, max_attempts, next_attempt_at
        ) VALUES (
            p_new_job_id, source_row.tenant_id, source_row.project_id,
            source_row.collection_run_id, source_row.monitoring_query_id,
            source_row.platform, source_row.surface, source_row.access_method,
            source_row.sample_index, btrim(p_idempotency_key), source_row.id,
            next_nonce, source_row.priority, source_row.max_attempts,
            statement_timestamp()
        ) RETURNING * INTO child_row;
    EXCEPTION WHEN unique_violation THEN
        SELECT * INTO child_row
        FROM public.collection_jobs AS existing
        WHERE existing.project_id = source_row.project_id
          AND existing.parent_job_id = source_row.id
          AND existing.replay_nonce = next_nonce
        FOR UPDATE;
        IF FOUND AND child_row.id = p_new_job_id
           AND child_row.idempotency_key = btrim(p_idempotency_key) THEN
            RETURN child_row;
        END IF;
        RAISE EXCEPTION 'collection replay idempotency conflict'
            USING ERRCODE = '23505';
    END;
    PERFORM public.geo_v2_record_job_command_audit(
        child_row.tenant_id, child_row.project_id, 'collection_job.replayed',
        'collection_job', child_row.id, 'user', actor_id,
        'operator replay',
        jsonb_build_object('source_job_id', source_row.id),
        jsonb_build_object('replay_nonce', next_nonce)
    );
    PERFORM public.geo_v2_refresh_collection_run_summary(
        child_row.collection_run_id, child_row.project_id
    );
    RETURN child_row;
END;
$replay_collection_job$;

CREATE FUNCTION geo_v2_claim_visibility_score_run(
    p_worker_id text,
    p_lease_seconds integer,
    p_project_id uuid DEFAULT NULL
)
RETURNS SETOF visibility_score_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $claim_visibility_score_run$
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'worker_id must be nonempty' USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease_seconds must be between 5 and 3600'
            USING ERRCODE = '22023';
    END IF;

    UPDATE public.visibility_score_runs AS cancelled
    SET status = 'cancelled',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = 'lease-recovery',
        updated_at = statement_timestamp()
    WHERE cancelled.status = 'running'
      AND cancelled.cancel_requested_at IS NOT NULL
      AND cancelled.lease_expires_at <= statement_timestamp()
      AND (p_project_id IS NULL OR cancelled.project_id = p_project_id);

    UPDATE public.visibility_score_runs AS exhausted
    SET status = 'dead_lettered',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = 'lease-recovery',
        last_error_code = 'lease_expired_attempts_exhausted',
        last_error_message = 'expired lease reached the configured attempt budget',
        updated_at = statement_timestamp()
    WHERE exhausted.status = 'running'
      AND exhausted.cancel_requested_at IS NULL
      AND exhausted.lease_expires_at <= statement_timestamp()
      AND exhausted.attempt_count >= exhausted.max_attempts
      AND (p_project_id IS NULL OR exhausted.project_id = p_project_id);

    RETURN QUERY
    WITH candidate AS (
        SELECT run_row.id
        FROM public.visibility_score_runs AS run_row
        WHERE (
                (run_row.status = 'queued'
                    AND run_row.next_attempt_at <= statement_timestamp()
                    AND run_row.cancel_requested_at IS NULL)
                OR (run_row.status = 'running'
                    AND run_row.lease_expires_at <= statement_timestamp()
                    AND run_row.cancel_requested_at IS NULL)
              )
          AND run_row.attempt_count < run_row.max_attempts
          AND (p_project_id IS NULL OR run_row.project_id = p_project_id)
        ORDER BY
            CASE WHEN run_row.status = 'running' THEN 0 ELSE 1 END,
            run_row.priority DESC,
            coalesce(run_row.lease_expires_at, run_row.next_attempt_at),
            run_row.created_at,
            run_row.id
        FOR UPDATE OF run_row SKIP LOCKED
        LIMIT 1
    )
    UPDATE public.visibility_score_runs AS claimed
    SET status = 'running',
        attempt_count = claimed.attempt_count + 1,
        lease_owner = btrim(p_worker_id),
        lease_token = gen_random_uuid(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        heartbeat_at = statement_timestamp(),
        started_at = coalesce(claimed.started_at, statement_timestamp()),
        completed_at = NULL, completed_by = NULL,
        updated_at = statement_timestamp()
    FROM candidate
    WHERE claimed.id = candidate.id
    RETURNING claimed.*;
END;
$claim_visibility_score_run$;

CREATE FUNCTION geo_v2_heartbeat_visibility_score_run(
    p_run_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_lease_seconds integer
)
RETURNS visibility_score_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $heartbeat_visibility_score_run$
DECLARE
    heartbeat_row public.visibility_score_runs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = ''
       OR p_lease_token IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'heartbeat lease arguments are invalid' USING ERRCODE = '22023';
    END IF;
    UPDATE public.visibility_score_runs AS run_row
    SET heartbeat_at = statement_timestamp(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        updated_at = statement_timestamp()
    WHERE run_row.id = p_run_id
      AND run_row.status = 'running'
      AND run_row.lease_owner = btrim(p_worker_id)
      AND run_row.lease_token = p_lease_token
      AND run_row.lease_expires_at > statement_timestamp()
      AND run_row.cancel_requested_at IS NULL
    RETURNING run_row.* INTO heartbeat_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'visibility score run lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN heartbeat_row;
END;
$heartbeat_visibility_score_run$;

CREATE FUNCTION geo_v2_persist_visibility_score_result(
    p_score_run visibility_score_runs,
    p_formula_version text,
    p_result_payload jsonb
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $persist_visibility_score_result$
DECLARE
    score_run public.visibility_score_runs%ROWTYPE := p_score_run;
    snapshot_id uuid;
    expected_formula_version text;
    result_item record;
    allowed_keys text[] := ARRAY[
        'snapshot_id', 'formula_version', 'window_start', 'window_end',
        'total_score', 'trigger_rate', 'mention_rate', 'recommendation_rate',
        'citation_rate', 'sample_count', 'excluded_sample_count', 'limitations',
        'snapshot_hash', 'created_by', 'run_analyses', 'dimensions',
        'contributions', 'contribution_evidence_assets', 'source_graphs',
        'source_nodes', 'source_graph_edges', 'source_node_citations',
        'source_gaps', 'source_gap_citations', 'source_gap_contributions',
        'competitor_benchmarks', 'benchmark_contributions', 'actions',
        'action_source_gaps', 'action_score_contributions',
        'action_benchmarks', 'action_tasks'
    ];
BEGIN
    IF score_run.id IS NULL OR score_run.status <> 'running'
       OR score_run.cancel_requested_at IS NOT NULL
       OR p_result_payload IS NULL OR jsonb_typeof(p_result_payload) <> 'object'
       OR NOT p_result_payload ?& allowed_keys
       OR p_result_payload - allowed_keys <> '{}'::jsonb
       OR EXISTS (
            SELECT 1 FROM unnest(ARRAY[
                'run_analyses', 'dimensions', 'contributions',
                'contribution_evidence_assets', 'source_graphs', 'source_nodes',
                'source_graph_edges', 'source_node_citations', 'source_gaps',
                'source_gap_citations', 'source_gap_contributions',
                'competitor_benchmarks', 'benchmark_contributions', 'actions',
                'action_source_gaps', 'action_score_contributions',
                'action_benchmarks', 'action_tasks'
            ]) AS array_key
            WHERE jsonb_typeof(p_result_payload->array_key) <> 'array'
       ) THEN
        RAISE EXCEPTION 'visibility score result payload shape is invalid'
            USING ERRCODE = '22023';
    END IF;
    expected_formula_version := p_formula_version;
    IF expected_formula_version IS NULL OR btrim(expected_formula_version) = ''
       OR p_result_payload->>'formula_version' <> expected_formula_version
       OR (p_result_payload->>'window_start')::timestamptz
            IS DISTINCT FROM score_run.window_start
       OR (p_result_payload->>'window_end')::timestamptz
            IS DISTINCT FROM score_run.window_end THEN
        RAISE EXCEPTION 'visibility score result does not match its locked input snapshot'
            USING ERRCODE = '23514';
    END IF;
    snapshot_id := (p_result_payload->>'snapshot_id')::uuid;
    INSERT INTO public.visibility_score_snapshots (
        id, tenant_id, project_id, visibility_score_run_id, collection_run_id,
        weight_profile_id,
        formula_version, window_start, window_end, total_score, trigger_rate,
        mention_rate, recommendation_rate, citation_rate, sample_count,
        excluded_sample_count, limitations, snapshot_hash, created_by
    ) VALUES (
        snapshot_id, score_run.tenant_id, score_run.project_id, score_run.id,
        score_run.collection_run_id, score_run.weight_profile_id, expected_formula_version,
        score_run.window_start, score_run.window_end,
        (p_result_payload->>'total_score')::numeric,
        (p_result_payload->>'trigger_rate')::numeric,
        (p_result_payload->>'mention_rate')::numeric,
        (p_result_payload->>'recommendation_rate')::numeric,
        (p_result_payload->>'citation_rate')::numeric,
        (p_result_payload->>'sample_count')::integer,
        (p_result_payload->>'excluded_sample_count')::integer,
        p_result_payload->>'limitations',
        p_result_payload->>'snapshot_hash',
        p_result_payload->>'created_by'
    );

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'run_analyses') AS item(
            id uuid,
            answer_analysis_id uuid,
            inclusion_role text
        )
    LOOP
        INSERT INTO public.visibility_score_run_analyses (
            id, tenant_id, project_id, visibility_score_run_id,
            answer_analysis_id, inclusion_role
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            score_run.id, result_item.answer_analysis_id,
            result_item.inclusion_role
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'dimensions') AS item(
            id uuid,
            dimension_type text,
            dimension_key text,
            dimension_score numeric,
            trigger_rate numeric,
            mention_rate numeric,
            recommendation_rate numeric,
            citation_rate numeric,
            sample_count integer
        )
    LOOP
        INSERT INTO public.visibility_score_dimensions (
            id, tenant_id, project_id, visibility_score_snapshot_id,
            dimension_type, dimension_key, dimension_score, trigger_rate,
            mention_rate, recommendation_rate, citation_rate, sample_count
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            snapshot_id, result_item.dimension_type, result_item.dimension_key,
            result_item.dimension_score, result_item.trigger_rate,
            result_item.mention_rate, result_item.recommendation_rate,
            result_item.citation_rate, result_item.sample_count
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'contributions') AS item(
            id uuid,
            answer_analysis_id uuid,
            metric_name text,
            dimension_type text,
            dimension_key text,
            weight numeric,
            raw_value numeric,
            normalized_value numeric,
            contribution numeric,
            positive_evidence text,
            negative_evidence text,
            explanation text
        )
    LOOP
        INSERT INTO public.score_contributions (
            id, tenant_id, project_id, visibility_score_snapshot_id,
            answer_analysis_id, metric_name, dimension_type, dimension_key,
            weight, raw_value, normalized_value, contribution,
            positive_evidence, negative_evidence, explanation
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            snapshot_id, result_item.answer_analysis_id, result_item.metric_name,
            result_item.dimension_type, result_item.dimension_key,
            result_item.weight, result_item.raw_value,
            result_item.normalized_value, result_item.contribution,
            result_item.positive_evidence, result_item.negative_evidence,
            result_item.explanation
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'contribution_evidence_assets'
        ) AS item(
            id uuid,
            score_contribution_id uuid,
            evidence_asset_id uuid,
            evidence_role text
        )
    LOOP
        INSERT INTO public.score_contribution_evidence_assets (
            id, tenant_id, project_id, score_contribution_id,
            evidence_asset_id, evidence_role
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.score_contribution_id, result_item.evidence_asset_id,
            result_item.evidence_role
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'source_graphs') AS item(
            id uuid,
            graph_version text,
            graph_hash text,
            status text,
            created_by text
        )
    LOOP
        INSERT INTO public.source_graphs (
            id, tenant_id, project_id, collection_run_id,
            visibility_score_snapshot_id, graph_version, graph_hash,
            status, created_by
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            score_run.collection_run_id, snapshot_id, result_item.graph_version,
            result_item.graph_hash, result_item.status, result_item.created_by
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'source_nodes') AS item(
            id uuid,
            source_graph_id uuid,
            entity_id uuid,
            source_url text,
            normalized_url_hash text,
            source_domain text,
            source_type text,
            source_title text,
            citation_count integer,
            authority_score numeric
        )
    LOOP
        INSERT INTO public.source_nodes (
            id, tenant_id, project_id, source_graph_id, entity_id,
            source_url, normalized_url_hash, source_domain, source_type,
            source_title, citation_count, authority_score
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.source_graph_id, result_item.entity_id,
            result_item.source_url, result_item.normalized_url_hash,
            result_item.source_domain, result_item.source_type,
            result_item.source_title, result_item.citation_count,
            result_item.authority_score
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'source_graph_edges') AS item(
            id uuid,
            source_graph_id uuid,
            from_source_node_id uuid,
            to_source_node_id uuid,
            relation_type text,
            weight numeric
        )
    LOOP
        INSERT INTO public.source_graph_edges (
            id, tenant_id, project_id, source_graph_id,
            from_source_node_id, to_source_node_id, relation_type, weight
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.source_graph_id, result_item.from_source_node_id,
            result_item.to_source_node_id, result_item.relation_type,
            result_item.weight
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'source_node_citations'
        ) AS item(id uuid, source_node_id uuid, answer_citation_id uuid)
    LOOP
        INSERT INTO public.source_node_citations (
            id, tenant_id, project_id, source_node_id, answer_citation_id
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.source_node_id, result_item.answer_citation_id
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'source_gaps') AS item(
            id uuid,
            source_graph_id uuid,
            entity_id uuid,
            gap_type text,
            source_type text,
            severity text,
            observed_count integer,
            expected_count integer,
            expected_weight numeric,
            recommendation text,
            status text,
            detected_by text,
            resolved_by text,
            resolved_at timestamptz
        )
    LOOP
        INSERT INTO public.source_gaps (
            id, tenant_id, project_id, source_graph_id,
            visibility_score_snapshot_id, entity_id, gap_type, source_type,
            severity, observed_count, expected_count, expected_weight,
            recommendation, status, detected_by, resolved_by, resolved_at
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.source_graph_id, snapshot_id, result_item.entity_id,
            result_item.gap_type, result_item.source_type, result_item.severity,
            result_item.observed_count, result_item.expected_count,
            result_item.expected_weight, result_item.recommendation,
            result_item.status, result_item.detected_by,
            result_item.resolved_by, result_item.resolved_at
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'source_gap_citations'
        ) AS item(
            id uuid,
            source_gap_id uuid,
            answer_citation_id uuid,
            evidence_role text
        )
    LOOP
        INSERT INTO public.source_gap_citations (
            id, tenant_id, project_id, source_gap_id,
            answer_citation_id, evidence_role
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.source_gap_id, result_item.answer_citation_id,
            result_item.evidence_role
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'source_gap_contributions'
        ) AS item(
            id uuid,
            source_gap_id uuid,
            score_contribution_id uuid,
            evidence_role text
        )
    LOOP
        INSERT INTO public.source_gap_score_contributions (
            id, tenant_id, project_id, source_gap_id,
            score_contribution_id, evidence_role
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.source_gap_id, result_item.score_contribution_id,
            result_item.evidence_role
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'competitor_benchmarks'
        ) AS item(
            id uuid,
            primary_entity_id uuid,
            compared_entity_id uuid,
            metric_scope text,
            metric_name text,
            primary_value numeric,
            compared_value numeric,
            value_delta numeric,
            sample_count integer,
            benchmark_hash text,
            created_by text
        )
    LOOP
        INSERT INTO public.competitor_benchmarks (
            id, tenant_id, project_id, visibility_score_snapshot_id,
            primary_entity_id, compared_entity_id, metric_scope, metric_name,
            primary_value, compared_value, value_delta, sample_count,
            benchmark_hash, created_by
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            snapshot_id, result_item.primary_entity_id,
            result_item.compared_entity_id, result_item.metric_scope,
            result_item.metric_name, result_item.primary_value,
            result_item.compared_value, result_item.value_delta,
            result_item.sample_count, result_item.benchmark_hash,
            result_item.created_by
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'benchmark_contributions'
        ) AS item(
            id uuid,
            competitor_benchmark_id uuid,
            score_contribution_id uuid,
            comparison_role text
        )
    LOOP
        INSERT INTO public.competitor_benchmark_contributions (
            id, tenant_id, project_id, competitor_benchmark_id,
            score_contribution_id, comparison_role
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.competitor_benchmark_id,
            result_item.score_contribution_id, result_item.comparison_role
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'actions') AS item(
            id uuid,
            title text,
            description text,
            action_type text,
            priority text,
            status text,
            owner_id text,
            customer_visible boolean,
            revision integer,
            next_check_at timestamptz,
            created_by text,
            updated_by text
        )
    LOOP
        INSERT INTO public.action_recommendations (
            id, tenant_id, project_id, title, description, action_type,
            priority, status, owner_id, customer_visible, revision,
            next_check_at, created_by, updated_by
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.title, result_item.description, result_item.action_type,
            result_item.priority, result_item.status, result_item.owner_id,
            result_item.customer_visible, result_item.revision,
            result_item.next_check_at, result_item.created_by,
            result_item.updated_by
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'action_source_gaps'
        ) AS item(
            id uuid,
            action_recommendation_id uuid,
            source_gap_id uuid,
            relation_type text
        )
    LOOP
        INSERT INTO public.action_source_gaps (
            id, tenant_id, project_id, action_recommendation_id,
            source_gap_id, relation_type
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.action_recommendation_id, result_item.source_gap_id,
            result_item.relation_type
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'action_score_contributions'
        ) AS item(
            id uuid,
            action_recommendation_id uuid,
            score_contribution_id uuid,
            relation_type text
        )
    LOOP
        INSERT INTO public.action_score_contributions (
            id, tenant_id, project_id, action_recommendation_id,
            score_contribution_id, relation_type
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.action_recommendation_id,
            result_item.score_contribution_id, result_item.relation_type
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(
            p_result_payload->'action_benchmarks'
        ) AS item(
            id uuid,
            action_recommendation_id uuid,
            competitor_benchmark_id uuid,
            relation_type text
        )
    LOOP
        INSERT INTO public.action_competitor_benchmarks (
            id, tenant_id, project_id, action_recommendation_id,
            competitor_benchmark_id, relation_type
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.action_recommendation_id,
            result_item.competitor_benchmark_id, result_item.relation_type
        );
    END LOOP;

    FOR result_item IN
        SELECT * FROM jsonb_to_recordset(p_result_payload->'action_tasks') AS item(
            id uuid,
            action_recommendation_id uuid,
            title text,
            status text,
            owner_id text,
            due_at timestamptz,
            completed_at timestamptz,
            created_by text,
            updated_by text
        )
    LOOP
        INSERT INTO public.action_tasks (
            id, tenant_id, project_id, action_recommendation_id, title,
            status, owner_id, due_at, completed_at, created_by, updated_by
        ) VALUES (
            result_item.id, score_run.tenant_id, score_run.project_id,
            result_item.action_recommendation_id, result_item.title,
            result_item.status, result_item.owner_id, result_item.due_at,
            result_item.completed_at, result_item.created_by,
            result_item.updated_by
        );
    END LOOP;
    RETURN snapshot_id;
EXCEPTION
    WHEN invalid_text_representation OR datetime_field_overflow THEN
        RAISE EXCEPTION 'visibility score payload contains an invalid typed value'
            USING ERRCODE = '22023';
END;
$persist_visibility_score_result$;

CREATE FUNCTION geo_v2_complete_visibility_score_run(
    p_run_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_result_payload jsonb
)
RETURNS visibility_score_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $complete_visibility_score_run$
DECLARE
    locked_run public.visibility_score_runs%ROWTYPE;
    completed_row public.visibility_score_runs%ROWTYPE;
    snapshot_id uuid;
    formula_version text;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_result_payload IS NULL OR jsonb_typeof(p_result_payload) <> 'object' THEN
        RAISE EXCEPTION 'completion arguments are invalid' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO locked_run
    FROM public.visibility_score_runs AS candidate
    WHERE candidate.id = p_run_id
      AND candidate.status = 'running'
      AND candidate.lease_owner = btrim(p_worker_id)
      AND candidate.lease_token = p_lease_token
      AND candidate.lease_expires_at > statement_timestamp()
      AND candidate.cancel_requested_at IS NULL
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'visibility score run lease is lost or cancellation is pending'
            USING ERRCODE = '55000';
    END IF;
    SELECT profile.formula_version INTO formula_version
    FROM public.visibility_weight_profiles AS profile
    WHERE profile.id = locked_run.weight_profile_id
      AND profile.project_id = locked_run.project_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'visibility score profile is unavailable'
            USING ERRCODE = '55000';
    END IF;

    snapshot_id := public.geo_v2_persist_visibility_score_result(
        locked_run, formula_version, p_result_payload
    );
    UPDATE public.visibility_score_runs AS run_row
    SET status = 'succeeded',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = btrim(p_worker_id),
        last_error_code = NULL, last_error_message = NULL,
        result_summary = jsonb_build_object('snapshot_id', snapshot_id),
        updated_at = statement_timestamp()
    WHERE run_row.id = p_run_id
      AND run_row.status = 'running'
      AND run_row.lease_owner = btrim(p_worker_id)
      AND run_row.lease_token = p_lease_token
      AND run_row.lease_expires_at > statement_timestamp()
      AND run_row.cancel_requested_at IS NULL
      AND run_row.cancel_requested_at IS NULL
      AND EXISTS (
            SELECT 1 FROM public.visibility_score_snapshots AS snapshot_row
            WHERE snapshot_row.visibility_score_run_id = run_row.id
              AND snapshot_row.project_id = run_row.project_id
      )
    RETURNING run_row.* INTO completed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'visibility score finalization lost its fenced lease'
            USING ERRCODE = '55000';
    END IF;
    RETURN completed_row;
END;
$complete_visibility_score_run$;

CREATE FUNCTION geo_v2_fail_visibility_score_run(
    p_run_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_error_code text,
    p_error_message text,
    p_retryable boolean,
    p_retry_delay_seconds integer DEFAULT 0
)
RETURNS visibility_score_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fail_visibility_score_run$
DECLARE
    failed_row public.visibility_score_runs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_error_code IS NULL OR btrim(p_error_code) = ''
       OR p_error_message IS NULL OR btrim(p_error_message) = ''
       OR p_retryable IS NULL
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'failure arguments are invalid' USING ERRCODE = '22023';
    END IF;
    UPDATE public.visibility_score_runs AS run_row
    SET status = CASE
            WHEN p_retryable AND run_row.attempt_count < run_row.max_attempts THEN 'queued'
            WHEN p_retryable THEN 'dead_lettered'
            ELSE 'failed'
        END,
        next_attempt_at = CASE
            WHEN p_retryable AND run_row.attempt_count < run_row.max_attempts
                THEN statement_timestamp() + make_interval(secs => p_retry_delay_seconds)
            ELSE run_row.next_attempt_at
        END,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = CASE
            WHEN p_retryable AND run_row.attempt_count < run_row.max_attempts THEN NULL
            ELSE statement_timestamp()
        END,
        completed_by = CASE
            WHEN p_retryable AND run_row.attempt_count < run_row.max_attempts THEN NULL
            ELSE btrim(p_worker_id)
        END,
        last_error_code = btrim(p_error_code),
        last_error_message = btrim(p_error_message),
        updated_at = statement_timestamp()
    WHERE run_row.id = p_run_id
      AND run_row.status = 'running'
      AND run_row.lease_owner = btrim(p_worker_id)
      AND run_row.lease_token = p_lease_token
      AND run_row.lease_expires_at > statement_timestamp()
      AND run_row.cancel_requested_at IS NULL
    RETURNING run_row.* INTO failed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'visibility score run lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN failed_row;
END;
$fail_visibility_score_run$;

CREATE FUNCTION geo_v2_ack_visibility_score_run_cancel(
    p_run_id uuid,
    p_worker_id text,
    p_lease_token uuid
)
RETURNS visibility_score_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $ack_score_cancel$
DECLARE
    cancelled_row public.visibility_score_runs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL THEN
        RAISE EXCEPTION 'cancel acknowledgement arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    UPDATE public.visibility_score_runs AS run_row
    SET status = 'cancelled',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = btrim(p_worker_id),
        updated_at = statement_timestamp()
    WHERE run_row.id = p_run_id
      AND run_row.status = 'running'
      AND run_row.cancel_requested_at IS NOT NULL
      AND run_row.lease_owner = btrim(p_worker_id)
      AND run_row.lease_token = p_lease_token
      AND run_row.lease_expires_at > statement_timestamp()
    RETURNING run_row.* INTO cancelled_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'visibility score cancellation lease is lost'
            USING ERRCODE = '55000';
    END IF;
    PERFORM public.geo_v2_record_job_command_audit(
        cancelled_row.tenant_id, cancelled_row.project_id,
        'visibility_score_run.cancelled', 'visibility_score_run', cancelled_row.id,
        'worker', p_worker_id, cancelled_row.cancel_reason,
        jsonb_build_object('attempt_count', cancelled_row.attempt_count), '{}'::jsonb
    );
    RETURN cancelled_row;
END;
$ack_score_cancel$;

CREATE FUNCTION geo_v2_request_visibility_score_run_cancel(
    p_run_id uuid,
    p_reason text
)
RETURNS visibility_score_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $request_score_cancel$
DECLARE
    target_row public.visibility_score_runs%ROWTYPE;
    actor_id text;
    event_type text;
BEGIN
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'cancel reason must be nonempty' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO target_row
    FROM public.visibility_score_runs AS run_row
    WHERE run_row.id = p_run_id
    FOR UPDATE;
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        target_row.project_id, target_row.tenant_id, 'score.configure'
    ) THEN
        RAISE EXCEPTION 'visibility score run is not accessible'
            USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geo_v2_resolve_session_context() AS context;
    IF target_row.status = 'queued' THEN
        UPDATE public.visibility_score_runs AS run_row
        SET status = 'cancelled',
            cancel_requested_at = statement_timestamp(),
            cancel_requested_by = actor_id,
            cancel_reason = btrim(p_reason),
            completed_at = statement_timestamp(), completed_by = actor_id,
            updated_at = statement_timestamp()
        WHERE run_row.id = p_run_id
        RETURNING run_row.* INTO target_row;
        event_type := 'visibility_score_run.cancelled';
    ELSIF target_row.status = 'running' THEN
        IF target_row.cancel_requested_at IS NULL THEN
            UPDATE public.visibility_score_runs AS run_row
            SET cancel_requested_at = statement_timestamp(),
                cancel_requested_by = actor_id,
                cancel_reason = btrim(p_reason),
                updated_at = statement_timestamp()
            WHERE run_row.id = p_run_id
            RETURNING run_row.* INTO target_row;
            event_type := 'visibility_score_run.cancel_requested';
        END IF;
    ELSIF target_row.status <> 'cancelled' THEN
        RAISE EXCEPTION 'only queued or running score runs can be cancelled'
            USING ERRCODE = '55000';
    END IF;
    IF event_type IS NOT NULL THEN
        PERFORM public.geo_v2_record_job_command_audit(
            target_row.tenant_id, target_row.project_id, event_type,
            'visibility_score_run', target_row.id, 'user', actor_id, p_reason
        );
    END IF;
    RETURN target_row;
END;
$request_score_cancel$;

CREATE FUNCTION geo_v2_replay_visibility_score_run(
    p_source_run_id uuid,
    p_new_run_id uuid,
    p_idempotency_key text
)
RETURNS visibility_score_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $replay_score_run$
DECLARE
    source_row public.visibility_score_runs%ROWTYPE;
    child_row public.visibility_score_runs%ROWTYPE;
    actor_id text;
    next_nonce integer;
BEGIN
    IF p_new_run_id IS NULL OR p_idempotency_key IS NULL
       OR btrim(p_idempotency_key) = '' THEN
        RAISE EXCEPTION 'replay arguments are invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO source_row
    FROM public.visibility_score_runs AS run_row
    WHERE run_row.id = p_source_run_id
    FOR UPDATE;
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        source_row.project_id, source_row.tenant_id, 'score.configure'
    ) THEN
        RAISE EXCEPTION 'visibility score run is not accessible'
            USING ERRCODE = '42501';
    END IF;
    IF source_row.status NOT IN ('failed', 'cancelled', 'dead_lettered') THEN
        RAISE EXCEPTION 'only terminal unsuccessful score runs can be replayed'
            USING ERRCODE = '55000';
    END IF;
    next_nonce := source_row.replay_nonce + 1;
    SELECT * INTO child_row
    FROM public.visibility_score_runs AS existing
    WHERE existing.project_id = source_row.project_id
      AND existing.parent_job_id = source_row.id
      AND existing.replay_nonce = next_nonce;
    IF FOUND THEN
        IF child_row.id = p_new_run_id
           AND child_row.idempotency_key = btrim(p_idempotency_key) THEN
            RETURN child_row;
        END IF;
        RAISE EXCEPTION 'visibility score replay idempotency conflict'
            USING ERRCODE = '23505';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geo_v2_resolve_session_context() AS context;
    BEGIN
        INSERT INTO public.visibility_score_runs (
            id, tenant_id, project_id, collection_run_id, weight_profile_id,
            idempotency_key, parent_job_id, replay_nonce, window_start, window_end,
            priority, max_attempts, next_attempt_at, requested_by
        ) VALUES (
            p_new_run_id, source_row.tenant_id, source_row.project_id,
            source_row.collection_run_id, source_row.weight_profile_id,
            btrim(p_idempotency_key), source_row.id, next_nonce,
            source_row.window_start, source_row.window_end, source_row.priority,
            source_row.max_attempts, statement_timestamp(), actor_id
        ) RETURNING * INTO child_row;
    EXCEPTION WHEN unique_violation THEN
        SELECT * INTO child_row
        FROM public.visibility_score_runs AS existing
        WHERE existing.project_id = source_row.project_id
          AND existing.parent_job_id = source_row.id
          AND existing.replay_nonce = next_nonce
        FOR UPDATE;
        IF FOUND AND child_row.id = p_new_run_id
           AND child_row.idempotency_key = btrim(p_idempotency_key) THEN
            RETURN child_row;
        END IF;
        RAISE EXCEPTION 'visibility score replay idempotency conflict'
            USING ERRCODE = '23505';
    END;
    PERFORM public.geo_v2_record_job_command_audit(
        child_row.tenant_id, child_row.project_id, 'visibility_score_run.replayed',
        'visibility_score_run', child_row.id, 'user', actor_id,
        'operator replay',
        jsonb_build_object('source_run_id', source_row.id),
        jsonb_build_object('replay_nonce', next_nonce)
    );
    RETURN child_row;
END;
$replay_score_run$;

CREATE FUNCTION geo_v2_claim_retest_run(
    p_worker_id text,
    p_lease_seconds integer,
    p_project_id uuid DEFAULT NULL
)
RETURNS SETOF retest_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $claim_retest_run$
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' THEN
        RAISE EXCEPTION 'worker_id must be nonempty' USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease_seconds must be between 5 and 3600'
            USING ERRCODE = '22023';
    END IF;

    UPDATE public.retest_runs AS cancelled
    SET status = 'cancelled',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = 'lease-recovery',
        updated_at = statement_timestamp()
    WHERE cancelled.status = 'running'
      AND cancelled.cancel_requested_at IS NOT NULL
      AND cancelled.lease_expires_at <= statement_timestamp()
      AND (p_project_id IS NULL OR cancelled.project_id = p_project_id);

    UPDATE public.retest_runs AS exhausted
    SET status = 'dead_lettered',
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = 'lease-recovery',
        last_error_code = 'lease_expired_attempts_exhausted',
        last_error_message = 'expired lease reached the configured attempt budget',
        updated_at = statement_timestamp()
    WHERE exhausted.status = 'running'
      AND exhausted.cancel_requested_at IS NULL
      AND exhausted.lease_expires_at <= statement_timestamp()
      AND exhausted.attempt_count >= exhausted.max_attempts
      AND (p_project_id IS NULL OR exhausted.project_id = p_project_id);

    RETURN QUERY
    WITH candidate AS (
        SELECT run_row.id
        FROM public.retest_runs AS run_row
        WHERE (
                (run_row.status = 'queued'
                    AND run_row.next_attempt_at <= statement_timestamp()
                    AND run_row.scheduled_for <= statement_timestamp()
                    AND run_row.cancel_requested_at IS NULL)
                OR (run_row.status = 'running'
                    AND run_row.lease_expires_at <= statement_timestamp()
                    AND run_row.cancel_requested_at IS NULL)
              )
          AND run_row.attempt_count < run_row.max_attempts
          AND (p_project_id IS NULL OR run_row.project_id = p_project_id)
          AND EXISTS (
                SELECT 1 FROM public.retest_run_queries AS requested_query
                WHERE requested_query.retest_run_id = run_row.id
                  AND requested_query.project_id = run_row.project_id
          )
        ORDER BY
            CASE WHEN run_row.status = 'running' THEN 0 ELSE 1 END,
            run_row.priority DESC,
            coalesce(run_row.lease_expires_at, run_row.next_attempt_at),
            run_row.created_at,
            run_row.id
        FOR UPDATE OF run_row SKIP LOCKED
        LIMIT 1
    )
    UPDATE public.retest_runs AS claimed
    SET status = 'running',
        attempt_count = claimed.attempt_count + 1,
        lease_owner = btrim(p_worker_id),
        lease_token = gen_random_uuid(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        heartbeat_at = statement_timestamp(),
        started_at = coalesce(claimed.started_at, statement_timestamp()),
        completed_at = NULL, completed_by = NULL,
        updated_at = statement_timestamp()
    FROM candidate
    WHERE claimed.id = candidate.id
    RETURNING claimed.*;
END;
$claim_retest_run$;

CREATE FUNCTION geo_v2_heartbeat_retest_run(
    p_run_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_lease_seconds integer
)
RETURNS retest_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $heartbeat_retest_run$
DECLARE
    heartbeat_row public.retest_runs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = ''
       OR p_lease_token IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'heartbeat lease arguments are invalid' USING ERRCODE = '22023';
    END IF;
    UPDATE public.retest_runs AS run_row
    SET heartbeat_at = statement_timestamp(),
        lease_expires_at = statement_timestamp() + make_interval(secs => p_lease_seconds),
        updated_at = statement_timestamp()
    WHERE run_row.id = p_run_id
      AND run_row.status = 'running'
      AND run_row.lease_owner = btrim(p_worker_id)
      AND run_row.lease_token = p_lease_token
      AND run_row.lease_expires_at > statement_timestamp()
      AND run_row.cancel_requested_at IS NULL
    RETURNING run_row.* INTO heartbeat_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'retest run lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN heartbeat_row;
END;
$heartbeat_retest_run$;

CREATE FUNCTION geo_v2_persist_retest_result(
    p_retest_run retest_runs,
    p_output_score_snapshot_id uuid,
    p_result_payload jsonb
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $persist_retest_result$
DECLARE
    retest_run public.retest_runs%ROWTYPE := p_retest_run;
    comparison_id uuid;
    baseline_score numeric;
    output_score numeric;
    baseline_profile_id uuid;
    output_profile_id uuid;
    baseline_formula_version text;
    output_formula_version text;
    output_window_start timestamptz;
    output_window_end timestamptz;
    baseline_collection_run_id uuid;
    output_collection_run_id uuid;
    score_delta numeric;
    derived_trend text;
    allowed_keys text[] := ARRAY[
        'comparison_id', 'comparison_hash', 'created_by'
    ];
BEGIN
    IF retest_run.id IS NULL OR retest_run.status <> 'running'
       OR retest_run.cancel_requested_at IS NOT NULL
       OR retest_run.baseline_score_snapshot_id = p_output_score_snapshot_id
       OR p_result_payload IS NULL OR jsonb_typeof(p_result_payload) <> 'object'
       OR NOT p_result_payload ?& allowed_keys
       OR p_result_payload - allowed_keys <> '{}'::jsonb THEN
        RAISE EXCEPTION 'retest result payload shape is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT baseline.total_score, baseline.weight_profile_id,
           baseline.formula_version, baseline.collection_run_id
    INTO baseline_score, baseline_profile_id,
         baseline_formula_version, baseline_collection_run_id
    FROM public.visibility_score_snapshots AS baseline
    WHERE baseline.id = retest_run.baseline_score_snapshot_id
      AND baseline.project_id = retest_run.project_id;
    SELECT output.total_score, output.weight_profile_id,
           output.formula_version, output.window_start, output.window_end,
           output.collection_run_id
    INTO output_score, output_profile_id, output_formula_version,
         output_window_start, output_window_end, output_collection_run_id
    FROM public.visibility_score_snapshots AS output
    WHERE output.id = p_output_score_snapshot_id
      AND output.project_id = retest_run.project_id;
    IF baseline_score IS NULL OR output_score IS NULL
       OR baseline_profile_id <> output_profile_id
       OR baseline_formula_version <> output_formula_version
       OR output_window_start IS DISTINCT FROM retest_run.window_start
       OR output_window_end IS DISTINCT FROM retest_run.window_end
       OR NOT EXISTS (
            SELECT 1 FROM public.retest_run_queries AS requested_query
            WHERE requested_query.retest_run_id = retest_run.id
              AND requested_query.project_id = retest_run.project_id
       )
       OR EXISTS (
            (SELECT baseline_query.monitoring_query_id
             FROM public.collection_run_queries AS baseline_query
             WHERE baseline_query.collection_run_id = baseline_collection_run_id
               AND baseline_query.project_id = retest_run.project_id
             EXCEPT
             SELECT requested_query.monitoring_query_id
             FROM public.retest_run_queries AS requested_query
             WHERE requested_query.retest_run_id = retest_run.id
               AND requested_query.project_id = retest_run.project_id)
            UNION ALL
            (SELECT requested_query.monitoring_query_id
             FROM public.retest_run_queries AS requested_query
             WHERE requested_query.retest_run_id = retest_run.id
               AND requested_query.project_id = retest_run.project_id
             EXCEPT
             SELECT baseline_query.monitoring_query_id
             FROM public.collection_run_queries AS baseline_query
             WHERE baseline_query.collection_run_id = baseline_collection_run_id
               AND baseline_query.project_id = retest_run.project_id)
            UNION ALL
            (SELECT output_query.monitoring_query_id
             FROM public.collection_run_queries AS output_query
             WHERE output_query.collection_run_id = output_collection_run_id
               AND output_query.project_id = retest_run.project_id
             EXCEPT
             SELECT requested_query.monitoring_query_id
             FROM public.retest_run_queries AS requested_query
             WHERE requested_query.retest_run_id = retest_run.id
               AND requested_query.project_id = retest_run.project_id)
            UNION ALL
            (SELECT requested_query.monitoring_query_id
             FROM public.retest_run_queries AS requested_query
             WHERE requested_query.retest_run_id = retest_run.id
               AND requested_query.project_id = retest_run.project_id
             EXCEPT
             SELECT output_query.monitoring_query_id
             FROM public.collection_run_queries AS output_query
             WHERE output_query.collection_run_id = output_collection_run_id
               AND output_query.project_id = retest_run.project_id)
       ) THEN
        RAISE EXCEPTION 'retest result does not match baseline, profile, window, or query scope'
            USING ERRCODE = '23514';
    END IF;
    score_delta := output_score - baseline_score;
    derived_trend := CASE
        WHEN score_delta > 0 THEN 'improved'
        WHEN score_delta < 0 THEN 'declined'
        ELSE 'unchanged'
    END;
    comparison_id := (p_result_payload->>'comparison_id')::uuid;
    INSERT INTO public.retest_comparisons (
        id, tenant_id, project_id, retest_run_id,
        baseline_score_snapshot_id, retest_score_snapshot_id,
        baseline_score, retest_score, score_delta, trend,
        comparison_hash, created_by
    ) VALUES (
        comparison_id, retest_run.tenant_id, retest_run.project_id, retest_run.id,
        retest_run.baseline_score_snapshot_id, p_output_score_snapshot_id,
        baseline_score, output_score, score_delta, derived_trend,
        p_result_payload->>'comparison_hash',
        p_result_payload->>'created_by'
    );
    RETURN comparison_id;
EXCEPTION
    WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'retest payload contains an invalid typed value'
            USING ERRCODE = '22023';
END;
$persist_retest_result$;

CREATE FUNCTION geo_v2_complete_retest_run(
    p_run_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_output_score_snapshot_id uuid,
    p_result_payload jsonb
)
RETURNS retest_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $complete_retest_run$
DECLARE
    locked_run public.retest_runs%ROWTYPE;
    completed_row public.retest_runs%ROWTYPE;
    comparison_id uuid;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_output_score_snapshot_id IS NULL
       OR p_result_payload IS NULL OR jsonb_typeof(p_result_payload) <> 'object' THEN
        RAISE EXCEPTION 'completion arguments are invalid' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO locked_run
    FROM public.retest_runs AS candidate
    WHERE candidate.id = p_run_id
      AND candidate.status = 'running'
      AND candidate.lease_owner = btrim(p_worker_id)
      AND candidate.lease_token = p_lease_token
      AND candidate.lease_expires_at > statement_timestamp()
      AND candidate.cancel_requested_at IS NULL
      AND candidate.baseline_score_snapshot_id <> p_output_score_snapshot_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'retest run lease is lost or cancellation is pending'
            USING ERRCODE = '55000';
    END IF;

    comparison_id := public.geo_v2_persist_retest_result(
        locked_run, p_output_score_snapshot_id, p_result_payload
    );
    UPDATE public.retest_runs AS run_row
    SET status = 'succeeded',
        output_score_snapshot_id = p_output_score_snapshot_id,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = btrim(p_worker_id),
        last_error_code = NULL, last_error_message = NULL,
        result_summary = jsonb_build_object('comparison_id', comparison_id),
        updated_at = statement_timestamp()
    WHERE run_row.id = p_run_id
      AND run_row.status = 'running'
      AND run_row.lease_owner = btrim(p_worker_id)
      AND run_row.lease_token = p_lease_token
      AND run_row.lease_expires_at > statement_timestamp()
      AND run_row.baseline_score_snapshot_id <> p_output_score_snapshot_id
      AND run_row.cancel_requested_at IS NULL
      AND EXISTS (
            SELECT 1 FROM public.retest_comparisons AS comparison_row
            WHERE comparison_row.retest_run_id = run_row.id
              AND comparison_row.project_id = run_row.project_id
              AND comparison_row.baseline_score_snapshot_id
                    = run_row.baseline_score_snapshot_id
              AND comparison_row.retest_score_snapshot_id = p_output_score_snapshot_id
      )
    RETURNING run_row.* INTO completed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'retest finalization lost its fenced lease'
            USING ERRCODE = '55000';
    END IF;
    RETURN completed_row;
END;
$complete_retest_run$;

CREATE FUNCTION geo_v2_fail_retest_run(
    p_run_id uuid,
    p_worker_id text,
    p_lease_token uuid,
    p_error_code text,
    p_error_message text,
    p_retryable boolean,
    p_retry_delay_seconds integer DEFAULT 0
)
RETURNS retest_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $fail_retest_run$
DECLARE
    failed_row public.retest_runs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL
       OR p_error_code IS NULL OR btrim(p_error_code) = ''
       OR p_error_message IS NULL OR btrim(p_error_message) = ''
       OR p_retryable IS NULL
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'failure arguments are invalid' USING ERRCODE = '22023';
    END IF;
    UPDATE public.retest_runs AS run_row
    SET status = CASE
            WHEN p_retryable AND run_row.attempt_count < run_row.max_attempts THEN 'queued'
            WHEN p_retryable THEN 'dead_lettered'
            ELSE 'failed'
        END,
        next_attempt_at = CASE
            WHEN p_retryable AND run_row.attempt_count < run_row.max_attempts
                THEN statement_timestamp() + make_interval(secs => p_retry_delay_seconds)
            ELSE run_row.next_attempt_at
        END,
        output_score_snapshot_id = NULL,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = CASE
            WHEN p_retryable AND run_row.attempt_count < run_row.max_attempts THEN NULL
            ELSE statement_timestamp()
        END,
        completed_by = CASE
            WHEN p_retryable AND run_row.attempt_count < run_row.max_attempts THEN NULL
            ELSE btrim(p_worker_id)
        END,
        last_error_code = btrim(p_error_code),
        last_error_message = btrim(p_error_message),
        updated_at = statement_timestamp()
    WHERE run_row.id = p_run_id
      AND run_row.status = 'running'
      AND run_row.lease_owner = btrim(p_worker_id)
      AND run_row.lease_token = p_lease_token
      AND run_row.lease_expires_at > statement_timestamp()
      AND run_row.cancel_requested_at IS NULL
    RETURNING run_row.* INTO failed_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'retest run lease is lost' USING ERRCODE = '55000';
    END IF;
    RETURN failed_row;
END;
$fail_retest_run$;

CREATE FUNCTION geo_v2_ack_retest_run_cancel(
    p_run_id uuid,
    p_worker_id text,
    p_lease_token uuid
)
RETURNS retest_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $ack_retest_cancel$
DECLARE
    cancelled_row public.retest_runs%ROWTYPE;
BEGIN
    IF p_worker_id IS NULL OR btrim(p_worker_id) = '' OR p_lease_token IS NULL THEN
        RAISE EXCEPTION 'cancel acknowledgement arguments are invalid'
            USING ERRCODE = '22023';
    END IF;
    UPDATE public.retest_runs AS run_row
    SET status = 'cancelled',
        output_score_snapshot_id = NULL,
        lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
        heartbeat_at = NULL,
        completed_at = statement_timestamp(), completed_by = btrim(p_worker_id),
        updated_at = statement_timestamp()
    WHERE run_row.id = p_run_id
      AND run_row.status = 'running'
      AND run_row.cancel_requested_at IS NOT NULL
      AND run_row.lease_owner = btrim(p_worker_id)
      AND run_row.lease_token = p_lease_token
      AND run_row.lease_expires_at > statement_timestamp()
    RETURNING run_row.* INTO cancelled_row;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'retest cancellation lease is lost' USING ERRCODE = '55000';
    END IF;
    PERFORM public.geo_v2_record_job_command_audit(
        cancelled_row.tenant_id, cancelled_row.project_id,
        'retest_run.cancelled', 'retest_run', cancelled_row.id,
        'worker', p_worker_id, cancelled_row.cancel_reason,
        jsonb_build_object('attempt_count', cancelled_row.attempt_count), '{}'::jsonb
    );
    RETURN cancelled_row;
END;
$ack_retest_cancel$;

CREATE FUNCTION geo_v2_request_retest_run_cancel(
    p_run_id uuid,
    p_reason text
)
RETURNS retest_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $request_retest_cancel$
DECLARE
    target_row public.retest_runs%ROWTYPE;
    actor_id text;
    event_type text;
BEGIN
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'cancel reason must be nonempty' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO target_row
    FROM public.retest_runs AS run_row
    WHERE run_row.id = p_run_id
    FOR UPDATE;
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        target_row.project_id, target_row.tenant_id, 'retest.run'
    ) THEN
        RAISE EXCEPTION 'retest run is not accessible' USING ERRCODE = '42501';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geo_v2_resolve_session_context() AS context;
    IF target_row.status = 'queued' THEN
        UPDATE public.retest_runs AS run_row
        SET status = 'cancelled',
            cancel_requested_at = statement_timestamp(),
            cancel_requested_by = actor_id,
            cancel_reason = btrim(p_reason),
            completed_at = statement_timestamp(), completed_by = actor_id,
            updated_at = statement_timestamp()
        WHERE run_row.id = p_run_id
        RETURNING run_row.* INTO target_row;
        event_type := 'retest_run.cancelled';
    ELSIF target_row.status = 'running' THEN
        IF target_row.cancel_requested_at IS NULL THEN
            UPDATE public.retest_runs AS run_row
            SET cancel_requested_at = statement_timestamp(),
                cancel_requested_by = actor_id,
                cancel_reason = btrim(p_reason),
                updated_at = statement_timestamp()
            WHERE run_row.id = p_run_id
            RETURNING run_row.* INTO target_row;
            event_type := 'retest_run.cancel_requested';
        END IF;
    ELSIF target_row.status <> 'cancelled' THEN
        RAISE EXCEPTION 'only queued or running retest runs can be cancelled'
            USING ERRCODE = '55000';
    END IF;
    IF event_type IS NOT NULL THEN
        PERFORM public.geo_v2_record_job_command_audit(
            target_row.tenant_id, target_row.project_id, event_type,
            'retest_run', target_row.id, 'user', actor_id, p_reason
        );
    END IF;
    RETURN target_row;
END;
$request_retest_cancel$;

CREATE FUNCTION geo_v2_replay_retest_run(
    p_source_run_id uuid,
    p_new_run_id uuid,
    p_idempotency_key text
)
RETURNS retest_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $replay_retest_run$
DECLARE
    source_row public.retest_runs%ROWTYPE;
    child_row public.retest_runs%ROWTYPE;
    actor_id text;
    next_nonce integer;
BEGIN
    IF p_new_run_id IS NULL OR p_idempotency_key IS NULL
       OR btrim(p_idempotency_key) = '' THEN
        RAISE EXCEPTION 'replay arguments are invalid' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO source_row
    FROM public.retest_runs AS run_row
    WHERE run_row.id = p_source_run_id
    FOR UPDATE;
    IF NOT FOUND OR NOT public.geo_v2_session_has_project_permission(
        source_row.project_id, source_row.tenant_id, 'retest.run'
    ) THEN
        RAISE EXCEPTION 'retest run is not accessible' USING ERRCODE = '42501';
    END IF;
    IF source_row.status NOT IN ('failed', 'cancelled', 'dead_lettered') THEN
        RAISE EXCEPTION 'only terminal unsuccessful retest runs can be replayed'
            USING ERRCODE = '55000';
    END IF;
    next_nonce := source_row.replay_nonce + 1;
    SELECT * INTO child_row
    FROM public.retest_runs AS existing
    WHERE existing.project_id = source_row.project_id
      AND existing.parent_job_id = source_row.id
      AND existing.replay_nonce = next_nonce;
    IF FOUND THEN
        IF child_row.id = p_new_run_id
           AND child_row.idempotency_key = btrim(p_idempotency_key) THEN
            RETURN child_row;
        END IF;
        RAISE EXCEPTION 'retest replay idempotency conflict' USING ERRCODE = '23505';
    END IF;
    SELECT context.actor_id INTO actor_id
    FROM public.geo_v2_resolve_session_context() AS context;
    BEGIN
        INSERT INTO public.retest_runs (
            id, tenant_id, project_id, action_recommendation_id,
            baseline_score_snapshot_id, idempotency_key, parent_job_id, replay_nonce,
            scheduled_for, window_start, window_end, priority, max_attempts,
            next_attempt_at, requested_by
        ) VALUES (
            p_new_run_id, source_row.tenant_id, source_row.project_id,
            source_row.action_recommendation_id, source_row.baseline_score_snapshot_id,
            btrim(p_idempotency_key), source_row.id, next_nonce,
            statement_timestamp(), source_row.window_start, source_row.window_end,
            source_row.priority, source_row.max_attempts,
            statement_timestamp(), actor_id
        ) RETURNING * INTO child_row;
    EXCEPTION WHEN unique_violation THEN
        SELECT * INTO child_row
        FROM public.retest_runs AS existing
        WHERE existing.project_id = source_row.project_id
          AND existing.parent_job_id = source_row.id
          AND existing.replay_nonce = next_nonce
        FOR UPDATE;
        IF FOUND AND child_row.id = p_new_run_id
           AND child_row.idempotency_key = btrim(p_idempotency_key) THEN
            RETURN child_row;
        END IF;
        RAISE EXCEPTION 'retest replay idempotency conflict'
            USING ERRCODE = '23505';
    END;
    INSERT INTO public.retest_run_queries (
        tenant_id, project_id, retest_run_id, monitoring_query_id, ordinal
    )
    SELECT source_row.tenant_id, source_row.project_id, child_row.id,
           query_row.monitoring_query_id, query_row.ordinal
    FROM public.retest_run_queries AS query_row
    WHERE query_row.retest_run_id = source_row.id;
    PERFORM public.geo_v2_record_job_command_audit(
        child_row.tenant_id, child_row.project_id, 'retest_run.replayed',
        'retest_run', child_row.id, 'user', actor_id, 'operator replay',
        jsonb_build_object('source_run_id', source_row.id),
        jsonb_build_object('replay_nonce', next_nonce)
    );
    RETURN child_row;
END;
$replay_retest_run$;

CREATE TRIGGER visibility_weight_profiles_guard_used_update
BEFORE UPDATE ON visibility_weight_profiles
FOR EACH ROW EXECUTE FUNCTION geo_v2_guard_used_weight_profile_update();

CREATE TRIGGER collection_jobs_enqueue_dispatch
AFTER INSERT ON collection_jobs
FOR EACH ROW EXECUTE FUNCTION geo_v2_enqueue_durable_job_dispatch();

CREATE TRIGGER visibility_score_runs_enqueue_dispatch
AFTER INSERT ON visibility_score_runs
FOR EACH ROW EXECUTE FUNCTION geo_v2_enqueue_durable_job_dispatch();

CREATE TRIGGER retest_runs_enqueue_dispatch
AFTER INSERT ON retest_runs
FOR EACH ROW EXECUTE FUNCTION geo_v2_enqueue_durable_job_dispatch();

CREATE TRIGGER visibility_score_runs_guard_profile
BEFORE INSERT ON visibility_score_runs
FOR EACH ROW EXECUTE FUNCTION geo_v2_guard_score_run_profile();

CREATE TRIGGER visibility_weight_components_guard_used_update
BEFORE INSERT OR UPDATE OR DELETE ON visibility_weight_profile_components
FOR EACH ROW EXECUTE FUNCTION geo_v2_guard_used_weight_component_update();

CREATE TRIGGER raw_answers_immutable_update
BEFORE UPDATE ON raw_answers
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER answer_citations_immutable_update
BEFORE UPDATE ON answer_citations
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER evidence_assets_finalize_update
BEFORE UPDATE ON evidence_assets
FOR EACH ROW EXECUTE FUNCTION geo_v2_guard_evidence_asset_finalize();
CREATE TRIGGER answer_analyses_immutable_update
BEFORE UPDATE ON answer_analyses
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER collection_costs_immutable_update
BEFORE UPDATE ON collection_costs
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER model_call_logs_immutable_update
BEFORE UPDATE ON model_call_logs
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER visibility_score_snapshots_immutable_update
BEFORE UPDATE ON visibility_score_snapshots
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER visibility_score_dimensions_immutable_update
BEFORE UPDATE ON visibility_score_dimensions
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER score_contributions_immutable_update
BEFORE UPDATE ON score_contributions
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER score_contribution_evidence_require_finalized
BEFORE INSERT ON score_contribution_evidence_assets
FOR EACH ROW EXECUTE FUNCTION geo_v2_require_finalized_score_evidence();
CREATE TRIGGER source_graphs_immutable_update
BEFORE UPDATE ON source_graphs
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER source_nodes_immutable_update
BEFORE UPDATE ON source_nodes
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER source_graph_edges_immutable_update
BEFORE UPDATE ON source_graph_edges
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER competitor_benchmarks_immutable_update
BEFORE UPDATE ON competitor_benchmarks
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();
CREATE TRIGGER retest_comparisons_immutable_update
BEFORE UPDATE ON retest_comparisons
FOR EACH ROW EXECUTE FUNCTION geo_v2_reject_immutable_domain_update();

CREATE INDEX product_entities_project_status_idx
    ON product_entities (project_id, status, entity_kind);
CREATE INDEX product_entity_aliases_entity_status_idx
    ON product_entity_aliases (entity_id, status, alias_type);
CREATE INDEX monitoring_queries_project_status_priority_idx
    ON monitoring_queries (project_id, status, priority DESC, id);
CREATE INDEX monitoring_query_entities_entity_idx
    ON monitoring_query_entities (entity_id, monitoring_query_id);
CREATE INDEX collection_runs_project_status_created_idx
    ON collection_runs (project_id, status, created_at DESC);
CREATE INDEX collection_run_queries_query_idx
    ON collection_run_queries (monitoring_query_id, collection_run_id);
CREATE INDEX collection_jobs_fresh_claim_idx
    ON collection_jobs (priority DESC, next_attempt_at, created_at, id)
    WHERE status = 'queued';
CREATE INDEX collection_jobs_expired_claim_idx
    ON collection_jobs (lease_expires_at, priority DESC, created_at, id)
    WHERE status = 'running';
CREATE INDEX collection_jobs_run_status_idx
    ON collection_jobs (collection_run_id, status, monitoring_query_id);
CREATE INDEX answer_runs_run_query_idx
    ON answer_runs (collection_run_id, monitoring_query_id, collected_at DESC);
CREATE INDEX raw_answers_project_created_idx
    ON raw_answers (project_id, created_at DESC);
CREATE INDEX answer_citations_answer_position_idx
    ON answer_citations (answer_run_id, citation_position);
CREATE INDEX answer_citations_domain_idx
    ON answer_citations (project_id, source_domain, created_at DESC);
CREATE INDEX evidence_assets_project_type_idx
    ON evidence_assets (project_id, asset_type, created_at DESC);
CREATE INDEX artifact_finalize_outbox_fresh_claim_idx
    ON artifact_finalize_outbox (next_attempt_at, created_at, id)
    WHERE status = 'queued';
CREATE INDEX artifact_finalize_outbox_expired_claim_idx
    ON artifact_finalize_outbox (lease_expires_at, created_at, id)
    WHERE status = 'running';
CREATE INDEX answer_analyses_project_created_idx
    ON answer_analyses (project_id, created_at DESC);
CREATE INDEX analysis_mentions_entity_idx
    ON answer_analysis_entity_mentions (entity_id, mention_role, answer_analysis_id);
CREATE INDEX collection_costs_project_recorded_idx
    ON collection_costs (project_id, recorded_at DESC);
CREATE INDEX model_call_logs_project_purpose_idx
    ON model_call_logs (project_id, purpose, created_at DESC);
CREATE INDEX visibility_weight_profiles_project_status_idx
    ON visibility_weight_profiles (project_id, status, profile_name, profile_version DESC);
CREATE INDEX visibility_score_runs_fresh_claim_idx
    ON visibility_score_runs (priority DESC, next_attempt_at, created_at, id)
    WHERE status = 'queued';
CREATE INDEX visibility_score_runs_expired_claim_idx
    ON visibility_score_runs (lease_expires_at, priority DESC, created_at, id)
    WHERE status = 'running';
CREATE INDEX visibility_snapshots_project_created_idx
    ON visibility_score_snapshots (project_id, created_at DESC);
CREATE INDEX score_contributions_snapshot_metric_idx
    ON score_contributions (visibility_score_snapshot_id, metric_name, dimension_type);
CREATE INDEX source_graphs_project_created_idx
    ON source_graphs (project_id, created_at DESC);
CREATE INDEX source_nodes_project_domain_idx
    ON source_nodes (project_id, source_domain, source_type);
CREATE INDEX source_gaps_project_status_severity_idx
    ON source_gaps (project_id, status, severity, created_at DESC);
CREATE INDEX competitor_benchmarks_project_snapshot_idx
    ON competitor_benchmarks (project_id, visibility_score_snapshot_id, metric_name);
CREATE INDEX action_recommendations_project_status_priority_idx
    ON action_recommendations (project_id, status, priority, updated_at DESC);
CREATE INDEX action_tasks_action_status_idx
    ON action_tasks (action_recommendation_id, status, due_at);
CREATE INDEX retest_runs_fresh_claim_idx
    ON retest_runs (priority DESC, scheduled_for, next_attempt_at, created_at, id)
    WHERE status = 'queued';
CREATE INDEX retest_runs_expired_claim_idx
    ON retest_runs (lease_expires_at, priority DESC, created_at, id)
    WHERE status = 'running';
CREATE INDEX durable_dispatch_fresh_claim_idx
    ON durable_job_dispatch_outbox (next_attempt_at, created_at, id)
    WHERE status = 'pending';
CREATE INDEX durable_dispatch_expired_claim_idx
    ON durable_job_dispatch_outbox (lease_expires_at, created_at, id)
    WHERE status = 'dispatching';
CREATE INDEX review_assignments_project_queue_idx
    ON review_assignments (project_id, status, priority, due_at, created_at);

ALTER FUNCTION geo_v2_reject_immutable_domain_update()
    OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_guard_evidence_asset_finalize()
    OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_guard_used_weight_profile_update()
    OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_guard_used_weight_component_update()
    OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_guard_score_run_profile()
    OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_require_finalized_score_evidence()
    OWNER TO geo_v2_authz_owner;
ALTER FUNCTION geo_v2_enqueue_durable_job_dispatch()
    OWNER TO geo_v2_job_command_owner;
ALTER FUNCTION geo_v2_claim_durable_job_dispatch(text, integer, uuid, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_heartbeat_durable_job_dispatch(uuid, text, uuid, integer)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_complete_durable_job_dispatch(uuid, text, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_fail_durable_job_dispatch(
    uuid, text, uuid, text, text, boolean, integer
) OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_refresh_collection_run_summary(uuid, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_claim_artifact_finalize(text, integer, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_heartbeat_artifact_finalize(uuid, text, uuid, integer)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_complete_artifact_finalize(uuid, text, uuid, text)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_fail_artifact_finalize(
    uuid, text, uuid, text, text, boolean, integer
) OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_claim_collection_job(text, integer, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_heartbeat_collection_job(uuid, text, uuid, integer)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_complete_collection_job(uuid, text, uuid, jsonb)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_fail_collection_job(uuid, text, uuid, text, text, boolean, integer)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_ack_collection_job_cancel(uuid, text, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_claim_visibility_score_run(text, integer, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_heartbeat_visibility_score_run(uuid, text, uuid, integer)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_complete_visibility_score_run(uuid, text, uuid, jsonb)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_fail_visibility_score_run(
    uuid, text, uuid, text, text, boolean, integer
) OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_ack_visibility_score_run_cancel(uuid, text, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_claim_retest_run(text, integer, uuid)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_heartbeat_retest_run(uuid, text, uuid, integer)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_complete_retest_run(uuid, text, uuid, uuid, jsonb)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_fail_retest_run(uuid, text, uuid, text, text, boolean, integer)
    OWNER TO geo_v2_job_owner;
ALTER FUNCTION geo_v2_ack_retest_run_cancel(uuid, text, uuid)
    OWNER TO geo_v2_job_owner;

ALTER FUNCTION geo_v2_persist_collection_result(collection_jobs, jsonb)
    OWNER TO geo_v2_result_owner;
ALTER FUNCTION geo_v2_persist_visibility_score_result(
    visibility_score_runs, text, jsonb
)
    OWNER TO geo_v2_result_owner;
ALTER FUNCTION geo_v2_persist_retest_result(retest_runs, uuid, jsonb)
    OWNER TO geo_v2_result_owner;

ALTER FUNCTION geo_v2_record_job_command_audit(
    uuid, uuid, text, text, uuid, text, text, text, jsonb, jsonb
) OWNER TO geo_v2_job_command_owner;
ALTER FUNCTION geo_v2_request_collection_job_cancel(uuid, text)
    OWNER TO geo_v2_job_command_owner;
ALTER FUNCTION geo_v2_replay_collection_job(uuid, uuid, text)
    OWNER TO geo_v2_job_command_owner;
ALTER FUNCTION geo_v2_request_visibility_score_run_cancel(uuid, text)
    OWNER TO geo_v2_job_command_owner;
ALTER FUNCTION geo_v2_replay_visibility_score_run(uuid, uuid, text)
    OWNER TO geo_v2_job_command_owner;
ALTER FUNCTION geo_v2_request_retest_run_cancel(uuid, text)
    OWNER TO geo_v2_job_command_owner;
ALTER FUNCTION geo_v2_replay_retest_run(uuid, uuid, text)
    OWNER TO geo_v2_job_command_owner;

GRANT SELECT ON visibility_score_runs, evidence_assets TO geo_v2_authz_owner;
GRANT SELECT, UPDATE ON visibility_weight_profiles
    TO geo_v2_authz_owner;

DO $enable_project_rls$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'product_entities', 'product_entity_aliases',
        'monitoring_queries', 'monitoring_query_entities',
        'collection_runs', 'collection_run_queries', 'collection_jobs',
        'collection_run_summaries', 'answer_runs', 'raw_answers',
        'answer_citations', 'evidence_assets', 'artifact_finalize_outbox',
        'raw_answer_evidence_assets',
        'answer_citation_evidence_assets', 'answer_analyses',
        'answer_analysis_entity_mentions', 'answer_analysis_evidence_assets',
        'collection_costs', 'model_call_logs', 'visibility_weight_profiles',
        'visibility_weight_profile_components', 'visibility_score_runs',
        'visibility_score_run_analyses', 'visibility_score_snapshots',
        'visibility_score_dimensions', 'score_contributions',
        'score_contribution_evidence_assets', 'source_graphs', 'source_nodes',
        'source_graph_edges', 'source_node_citations', 'source_gaps',
        'source_gap_citations', 'source_gap_score_contributions',
        'competitor_benchmarks', 'competitor_benchmark_contributions',
        'action_recommendations', 'action_source_gaps',
        'action_score_contributions', 'action_competitor_benchmarks',
        'action_tasks', 'retest_runs', 'durable_job_dispatch_outbox',
        'retest_run_queries',
        'retest_comparisons', 'review_assignments'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
    END LOOP;
END;
$enable_project_rls$;

DO $create_project_read_policies$
DECLARE
    policy_spec record;
BEGIN
    FOR policy_spec IN
        SELECT * FROM (VALUES
            ('product_entities', 'project.read'),
            ('product_entity_aliases', 'project.read'),
            ('monitoring_queries', 'collection.read'),
            ('monitoring_query_entities', 'collection.read'),
            ('collection_runs', 'collection.read'),
            ('collection_run_queries', 'collection.read'),
            ('collection_jobs', 'collection.read'),
            ('collection_run_summaries', 'collection.read'),
            ('answer_runs', 'collection.read'),
            ('raw_answers', 'evidence.read_raw'),
            ('answer_citations', 'evidence.read_summary'),
            ('evidence_assets', 'evidence.read_raw'),
            ('raw_answer_evidence_assets', 'evidence.read_raw'),
            ('answer_citation_evidence_assets', 'evidence.read_raw'),
            ('answer_analyses', 'analysis.read'),
            ('answer_analysis_entity_mentions', 'analysis.read'),
            ('answer_analysis_evidence_assets', 'evidence.read_raw'),
            ('collection_costs', 'cost.read'),
            ('model_call_logs', 'cost.read'),
            ('visibility_weight_profiles', 'score.read'),
            ('visibility_weight_profile_components', 'score.read'),
            ('visibility_score_runs', 'score.read'),
            ('visibility_score_run_analyses', 'score.read'),
            ('visibility_score_snapshots', 'score.read'),
            ('visibility_score_dimensions', 'score.read'),
            ('score_contributions', 'score.read'),
            ('score_contribution_evidence_assets', 'score.read'),
            ('source_graphs', 'analysis.read'),
            ('source_nodes', 'analysis.read'),
            ('source_graph_edges', 'analysis.read'),
            ('source_node_citations', 'analysis.read'),
            ('source_gaps', 'analysis.read'),
            ('source_gap_citations', 'analysis.read'),
            ('source_gap_score_contributions', 'analysis.read'),
            ('competitor_benchmarks', 'analysis.read'),
            ('competitor_benchmark_contributions', 'analysis.read'),
            ('action_recommendations', 'action.read'),
            ('action_source_gaps', 'action.read'),
            ('action_score_contributions', 'action.read'),
            ('action_competitor_benchmarks', 'action.read'),
            ('action_tasks', 'action.read'),
            ('retest_runs', 'retest.read'),
            ('retest_run_queries', 'retest.read'),
            ('retest_comparisons', 'retest.read'),
            ('review_assignments', 'analysis.review')
        ) AS policy_map(table_name, permission_name)
    LOOP
        IF policy_spec.table_name = 'evidence_assets' THEN
            EXECUTE format(
                'CREATE POLICY %I ON %I FOR SELECT TO geo_v2_runtime '
                'USING (artifact_status = ''finalized'' AND '
                'public.geo_v2_session_has_project_permission('
                'project_id, tenant_id, %L))',
                policy_spec.table_name || '_session_select',
                policy_spec.table_name,
                policy_spec.permission_name
            );
        ELSE
            EXECUTE format(
                'CREATE POLICY %I ON %I FOR SELECT TO geo_v2_runtime '
                'USING (public.geo_v2_session_has_project_permission('
                'project_id, tenant_id, %L))',
                policy_spec.table_name || '_session_select',
                policy_spec.table_name,
                policy_spec.permission_name
            );
        END IF;
    END LOOP;
END;
$create_project_read_policies$;

DO $create_project_write_policies$
DECLARE
    policy_spec record;
BEGIN
    FOR policy_spec IN
        SELECT * FROM (VALUES
            ('product_entities', 'project.update', true),
            ('product_entity_aliases', 'project.update', true),
            ('monitoring_queries', 'collection.run', true),
            ('monitoring_query_entities', 'collection.run', true),
            ('collection_runs', 'collection.run', true),
            ('collection_run_queries', 'collection.run', false),
            ('collection_jobs', 'collection.run', false),
            ('collection_run_summaries', 'collection.run', true),
            ('answer_runs', 'collection.run', false),
            ('raw_answers', 'collection.run', false),
            ('answer_citations', 'collection.run', false),
            ('evidence_assets', 'collection.run', false),
            ('raw_answer_evidence_assets', 'collection.run', false),
            ('answer_citation_evidence_assets', 'collection.run', false),
            ('answer_analyses', 'collection.run', false),
            ('answer_analysis_entity_mentions', 'collection.run', false),
            ('answer_analysis_evidence_assets', 'collection.run', false),
            ('collection_costs', 'collection.run', false),
            ('model_call_logs', 'collection.run', false),
            ('visibility_weight_profiles', 'score.configure', true),
            ('visibility_weight_profile_components', 'score.configure', true),
            ('visibility_score_runs', 'score.configure', false),
            ('visibility_score_run_analyses', 'score.configure', false),
            ('visibility_score_snapshots', 'score.configure', false),
            ('visibility_score_dimensions', 'score.configure', false),
            ('score_contributions', 'score.configure', false),
            ('score_contribution_evidence_assets', 'score.configure', false),
            ('source_graphs', 'analysis.review', false),
            ('source_nodes', 'analysis.review', false),
            ('source_graph_edges', 'analysis.review', false),
            ('source_node_citations', 'analysis.review', false),
            ('source_gaps', 'analysis.review', true),
            ('source_gap_citations', 'analysis.review', false),
            ('source_gap_score_contributions', 'analysis.review', false),
            ('competitor_benchmarks', 'analysis.review', false),
            ('competitor_benchmark_contributions', 'analysis.review', false),
            ('action_recommendations', 'action.manage', true),
            ('action_source_gaps', 'action.manage', false),
            ('action_score_contributions', 'action.manage', false),
            ('action_competitor_benchmarks', 'action.manage', false),
            ('action_tasks', 'action.manage', true),
            ('retest_runs', 'retest.run', false),
            ('retest_run_queries', 'retest.run', false),
            ('retest_comparisons', 'retest.run', false),
            ('review_assignments', 'analysis.review', true)
        ) AS policy_map(table_name, permission_name, mutable)
    LOOP
        EXECUTE format(
            'CREATE POLICY %I ON %I FOR INSERT TO geo_v2_runtime '
            'WITH CHECK (public.geo_v2_session_has_project_permission('
            'project_id, tenant_id, %L))',
            policy_spec.table_name || '_session_insert',
            policy_spec.table_name,
            policy_spec.permission_name
        );
        IF policy_spec.mutable THEN
            EXECUTE format(
                'CREATE POLICY %I ON %I FOR UPDATE TO geo_v2_runtime '
                'USING (public.geo_v2_session_has_project_permission('
                'project_id, tenant_id, %L)) '
                'WITH CHECK (public.geo_v2_session_has_project_permission('
                'project_id, tenant_id, %L))',
                policy_spec.table_name || '_session_update',
                policy_spec.table_name,
                policy_spec.permission_name,
                policy_spec.permission_name
            );
        END IF;
    END LOOP;
END;
$create_project_write_policies$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM
    geo_v2_worker, geo_v2_job_owner, geo_v2_result_owner,
    geo_v2_job_command_owner;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM
    geo_v2_worker, geo_v2_job_owner, geo_v2_result_owner,
    geo_v2_job_command_owner;

GRANT SELECT, UPDATE ON collection_jobs, visibility_score_runs, retest_runs,
    durable_job_dispatch_outbox, artifact_finalize_outbox, evidence_assets
    TO geo_v2_job_owner;
GRANT SELECT, UPDATE ON collection_runs TO geo_v2_job_owner;
GRANT SELECT, INSERT, UPDATE ON collection_run_summaries TO geo_v2_job_owner;
GRANT SELECT ON answer_runs, answer_citations, collection_costs,
    visibility_weight_profiles, visibility_score_snapshots,
    retest_run_queries, retest_comparisons
    TO geo_v2_job_owner;

GRANT SELECT ON visibility_score_snapshots, collection_run_queries,
    retest_run_queries
    TO geo_v2_result_owner;
GRANT INSERT ON answer_runs, raw_answers, answer_citations, evidence_assets,
    artifact_finalize_outbox, raw_answer_evidence_assets,
    answer_citation_evidence_assets, answer_analyses,
    answer_analysis_entity_mentions, answer_analysis_evidence_assets,
    collection_costs, model_call_logs, visibility_score_run_analyses,
    visibility_score_snapshots, visibility_score_dimensions,
    score_contributions, score_contribution_evidence_assets,
    source_graphs, source_nodes, source_graph_edges, source_node_citations,
    source_gaps, source_gap_citations, source_gap_score_contributions,
    competitor_benchmarks, competitor_benchmark_contributions,
    action_recommendations, action_source_gaps, action_score_contributions,
    action_competitor_benchmarks, action_tasks, retest_comparisons
    TO geo_v2_result_owner;

GRANT SELECT, INSERT, UPDATE ON collection_jobs, visibility_score_runs, retest_runs
    TO geo_v2_job_command_owner;
GRANT INSERT ON durable_job_dispatch_outbox TO geo_v2_job_command_owner;
GRANT SELECT, INSERT ON retest_run_queries TO geo_v2_job_command_owner;
GRANT INSERT ON audit_events TO geo_v2_job_command_owner;
GRANT EXECUTE ON FUNCTION geo_v2_resolve_session_context()
    TO geo_v2_job_command_owner;
GRANT EXECUTE ON FUNCTION geo_v2_session_has_project_permission(uuid, uuid, text)
    TO geo_v2_job_command_owner;
GRANT EXECUTE ON FUNCTION digest(text, text) TO geo_v2_job_command_owner;

GRANT SELECT ON
    product_entities, product_entity_aliases,
    monitoring_queries, monitoring_query_entities,
    collection_runs, collection_run_queries, collection_jobs,
    collection_run_summaries, answer_runs, raw_answers, answer_citations,
    evidence_assets, raw_answer_evidence_assets, answer_citation_evidence_assets,
    answer_analyses, answer_analysis_entity_mentions,
    answer_analysis_evidence_assets, collection_costs, model_call_logs,
    visibility_weight_profiles, visibility_weight_profile_components,
    visibility_score_runs,
    visibility_score_snapshots, visibility_score_dimensions,
    score_contributions, score_contribution_evidence_assets,
    source_graphs, source_nodes, source_graph_edges, source_node_citations,
    source_gaps, source_gap_citations, source_gap_score_contributions,
    competitor_benchmarks, competitor_benchmark_contributions,
    action_recommendations, action_source_gaps, action_score_contributions,
    action_competitor_benchmarks, action_tasks, retest_runs,
    retest_run_queries, retest_comparisons, review_assignments
TO geo_v2_runtime;

GRANT INSERT ON
    product_entities, product_entity_aliases,
    monitoring_queries, monitoring_query_entities,
    collection_runs, collection_run_queries, collection_jobs,
    visibility_weight_profiles, visibility_weight_profile_components,
    visibility_score_runs, visibility_score_run_analyses,
    action_recommendations, action_source_gaps, action_score_contributions,
    action_competitor_benchmarks, action_tasks,
    retest_runs, retest_run_queries, review_assignments
TO geo_v2_runtime;

GRANT UPDATE ON
    product_entities, product_entity_aliases,
    monitoring_queries, monitoring_query_entities,
    collection_runs,
    visibility_weight_profiles, visibility_weight_profile_components,
    source_gaps, action_recommendations, action_tasks, review_assignments
TO geo_v2_runtime;

GRANT EXECUTE ON FUNCTION geo_v2_claim_collection_job(text, integer, uuid)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_claim_durable_job_dispatch(text, integer, uuid, uuid)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_heartbeat_durable_job_dispatch(
    uuid, text, uuid, integer
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_complete_durable_job_dispatch(uuid, text, uuid)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_fail_durable_job_dispatch(
    uuid, text, uuid, text, text, boolean, integer
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_claim_artifact_finalize(text, integer, uuid)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_heartbeat_artifact_finalize(
    uuid, text, uuid, integer
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_complete_artifact_finalize(uuid, text, uuid, text)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_fail_artifact_finalize(
    uuid, text, uuid, text, text, boolean, integer
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_heartbeat_collection_job(uuid, text, uuid, integer)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_complete_collection_job(uuid, text, uuid, jsonb)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_fail_collection_job(
    uuid, text, uuid, text, text, boolean, integer
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_ack_collection_job_cancel(uuid, text, uuid)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_claim_visibility_score_run(text, integer, uuid)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_heartbeat_visibility_score_run(
    uuid, text, uuid, integer
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_complete_visibility_score_run(
    uuid, text, uuid, jsonb
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_fail_visibility_score_run(
    uuid, text, uuid, text, text, boolean, integer
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_ack_visibility_score_run_cancel(uuid, text, uuid)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_claim_retest_run(text, integer, uuid)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_heartbeat_retest_run(uuid, text, uuid, integer)
    TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_complete_retest_run(
    uuid, text, uuid, uuid, jsonb
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_fail_retest_run(
    uuid, text, uuid, text, text, boolean, integer
) TO geo_v2_worker;
GRANT EXECUTE ON FUNCTION geo_v2_ack_retest_run_cancel(uuid, text, uuid)
    TO geo_v2_worker;

GRANT EXECUTE ON FUNCTION geo_v2_persist_collection_result(collection_jobs, jsonb)
    TO geo_v2_job_owner;
GRANT EXECUTE ON FUNCTION geo_v2_persist_visibility_score_result(
    visibility_score_runs, text, jsonb
) TO geo_v2_job_owner;
GRANT EXECUTE ON FUNCTION geo_v2_persist_retest_result(
    retest_runs, uuid, jsonb
) TO geo_v2_job_owner;
GRANT EXECUTE ON FUNCTION geo_v2_record_job_command_audit(
    uuid, uuid, text, text, uuid, text, text, text, jsonb, jsonb
) TO geo_v2_job_owner, geo_v2_job_command_owner;
GRANT EXECUTE ON FUNCTION geo_v2_refresh_collection_run_summary(uuid, uuid)
    TO geo_v2_job_owner, geo_v2_job_command_owner;

GRANT EXECUTE ON FUNCTION geo_v2_request_collection_job_cancel(uuid, text)
    TO geo_v2_runtime;
GRANT EXECUTE ON FUNCTION geo_v2_replay_collection_job(uuid, uuid, text)
    TO geo_v2_runtime;
GRANT EXECUTE ON FUNCTION geo_v2_request_visibility_score_run_cancel(uuid, text)
    TO geo_v2_runtime;
GRANT EXECUTE ON FUNCTION geo_v2_replay_visibility_score_run(uuid, uuid, text)
    TO geo_v2_runtime;
GRANT EXECUTE ON FUNCTION geo_v2_request_retest_run_cancel(uuid, text)
    TO geo_v2_runtime;
GRANT EXECUTE ON FUNCTION geo_v2_replay_retest_run(uuid, uuid, text)
    TO geo_v2_runtime;

DO $verify_job_security_boundary$
DECLARE
    worker_functions text[] := ARRAY[
        'geo_v2_claim_durable_job_dispatch',
        'geo_v2_heartbeat_durable_job_dispatch',
        'geo_v2_complete_durable_job_dispatch',
        'geo_v2_fail_durable_job_dispatch',
        'geo_v2_claim_artifact_finalize',
        'geo_v2_heartbeat_artifact_finalize',
        'geo_v2_complete_artifact_finalize',
        'geo_v2_fail_artifact_finalize',
        'geo_v2_claim_collection_job',
        'geo_v2_heartbeat_collection_job',
        'geo_v2_complete_collection_job',
        'geo_v2_fail_collection_job',
        'geo_v2_ack_collection_job_cancel',
        'geo_v2_claim_visibility_score_run',
        'geo_v2_heartbeat_visibility_score_run',
        'geo_v2_complete_visibility_score_run',
        'geo_v2_fail_visibility_score_run',
        'geo_v2_ack_visibility_score_run_cancel',
        'geo_v2_claim_retest_run',
        'geo_v2_heartbeat_retest_run',
        'geo_v2_complete_retest_run',
        'geo_v2_fail_retest_run',
        'geo_v2_ack_retest_run_cancel'
    ];
    persist_functions text[] := ARRAY[
        'geo_v2_persist_collection_result',
        'geo_v2_persist_visibility_score_result',
        'geo_v2_persist_retest_result'
    ];
    operator_functions text[] := ARRAY[
        'geo_v2_request_collection_job_cancel',
        'geo_v2_replay_collection_job',
        'geo_v2_request_visibility_score_run_cancel',
        'geo_v2_replay_visibility_score_run',
        'geo_v2_request_retest_run_cancel',
        'geo_v2_replay_retest_run'
    ];
    internal_functions text[] := ARRAY[
        'geo_v2_refresh_collection_run_summary',
        'geo_v2_enqueue_durable_job_dispatch'
    ];
    domain_tables text[] := ARRAY[
        'product_entities', 'product_entity_aliases',
        'monitoring_queries', 'monitoring_query_entities',
        'collection_runs', 'collection_run_queries', 'collection_jobs',
        'durable_job_dispatch_outbox',
        'collection_run_summaries', 'answer_runs', 'raw_answers',
        'answer_citations', 'evidence_assets', 'artifact_finalize_outbox',
        'raw_answer_evidence_assets',
        'answer_citation_evidence_assets', 'answer_analyses',
        'answer_analysis_entity_mentions', 'answer_analysis_evidence_assets',
        'collection_costs', 'model_call_logs', 'visibility_weight_profiles',
        'visibility_weight_profile_components', 'visibility_score_runs',
        'visibility_score_run_analyses', 'visibility_score_snapshots',
        'visibility_score_dimensions', 'score_contributions',
        'score_contribution_evidence_assets', 'source_graphs', 'source_nodes',
        'source_graph_edges', 'source_node_citations', 'source_gaps',
        'source_gap_citations', 'source_gap_score_contributions',
        'competitor_benchmarks', 'competitor_benchmark_contributions',
        'action_recommendations', 'action_source_gaps',
        'action_score_contributions', 'action_competitor_benchmarks',
        'action_tasks', 'retest_runs', 'retest_run_queries',
        'retest_comparisons', 'review_assignments'
    ];
    result_tables text[] := ARRAY[
        'answer_runs', 'raw_answers', 'answer_citations', 'evidence_assets',
        'artifact_finalize_outbox', 'raw_answer_evidence_assets',
        'answer_citation_evidence_assets', 'answer_analyses',
        'answer_analysis_entity_mentions', 'answer_analysis_evidence_assets',
        'collection_costs', 'model_call_logs', 'visibility_score_run_analyses',
        'visibility_score_snapshots', 'visibility_score_dimensions',
        'score_contributions', 'score_contribution_evidence_assets',
        'source_graphs', 'source_nodes', 'source_graph_edges',
        'source_node_citations', 'source_gaps', 'source_gap_citations',
        'source_gap_score_contributions', 'competitor_benchmarks',
        'competitor_benchmark_contributions', 'action_recommendations',
        'action_source_gaps', 'action_score_contributions',
        'action_competitor_benchmarks', 'action_tasks', 'retest_comparisons'
    ];
    table_name text;
    privilege_name text;
BEGIN
    IF (
        SELECT count(*)
        FROM pg_catalog.pg_roles
        WHERE rolname = ANY(ARRAY[
            'geo_v2_worker', 'geo_v2_job_owner',
            'geo_v2_result_owner', 'geo_v2_job_command_owner',
            'geo_v2_worker_login'
        ])
          AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
          AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication
          AND rolbypassrls = (rolname = ANY(ARRAY[
                'geo_v2_job_owner', 'geo_v2_result_owner',
                'geo_v2_job_command_owner'
              ]))
    ) <> 5 THEN
        RAISE EXCEPTION 'Schema v2 job role attributes are not sealed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_authid
        WHERE rolname = 'geo_v2_worker_login' AND rolpassword IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = 'geo_v2_worker_login' AND rolconfig IS NOT NULL
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_db_role_setting AS setting
        JOIN pg_catalog.pg_roles AS role_row ON role_row.oid = setting.setrole
        WHERE role_row.rolname = 'geo_v2_worker_login'
    ) THEN
        RAISE EXCEPTION 'Schema v2 worker login placeholder is not sealed';
    END IF;
    IF (
        SELECT count(*)
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
        WHERE granted_role.rolname = ANY(ARRAY[
                'geo_v2_worker', 'geo_v2_job_owner',
                'geo_v2_result_owner', 'geo_v2_job_command_owner',
                'geo_v2_worker_login'
              ])
           OR member_role.rolname = ANY(ARRAY[
                'geo_v2_worker', 'geo_v2_job_owner',
                'geo_v2_result_owner', 'geo_v2_job_command_owner',
                'geo_v2_worker_login'
              ])
    ) <> 1 OR NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
        WHERE granted_role.rolname = 'geo_v2_worker'
          AND member_role.rolname = 'geo_v2_worker_login'
          AND NOT membership.admin_option
          AND NOT membership.inherit_option
          AND membership.set_option
    ) THEN
        RAISE EXCEPTION 'Schema v2 job roles gained a forbidden membership';
    END IF;

    IF (
        SELECT count(*)
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = procedure.proowner
        WHERE namespace.nspname = 'public'
          AND procedure.proname = ANY(worker_functions)
          AND owner_role.rolname = 'geo_v2_job_owner'
          AND procedure.prosecdef
          AND procedure.proconfig = ARRAY['search_path=pg_catalog']::text[]
    ) <> cardinality(worker_functions) THEN
        RAISE EXCEPTION 'worker job functions have an invalid owner or execution context';
    END IF;
    IF (
        SELECT count(*)
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = procedure.proowner
        WHERE namespace.nspname = 'public'
          AND procedure.proname = ANY(persist_functions)
          AND owner_role.rolname = 'geo_v2_result_owner'
          AND procedure.prosecdef
          AND procedure.proconfig = ARRAY['search_path=pg_catalog']::text[]
    ) <> cardinality(persist_functions) THEN
        RAISE EXCEPTION 'private result functions have an invalid owner or execution context';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = procedure.proowner
        WHERE namespace.nspname = 'public'
          AND procedure.proname = 'geo_v2_enqueue_durable_job_dispatch'
          AND owner_role.rolname = 'geo_v2_job_command_owner'
          AND procedure.prosecdef
          AND procedure.proconfig = ARRAY['search_path=pg_catalog']::text[]
    ) THEN
        RAISE EXCEPTION 'durable dispatch enqueue trigger has an invalid execution context';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        CROSS JOIN LATERAL aclexplode(
            coalesce(procedure.proacl, acldefault('f', procedure.proowner))
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND procedure.proname = ANY(
                worker_functions || persist_functions || operator_functions
                || internal_functions
          )
          AND acl.grantee = 0
          AND acl.privilege_type = 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'PUBLIC can execute a Schema v2 job boundary function';
    END IF;

    IF (
        SELECT count(*)
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'public'
          AND procedure.proname = ANY(worker_functions)
          AND has_function_privilege('geo_v2_worker', procedure.oid, 'EXECUTE')
    ) <> cardinality(worker_functions)
       OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'public'
              AND procedure.proname = ANY(
                    worker_functions || persist_functions || internal_functions
              )
              AND has_function_privilege('geo_v2_runtime', procedure.oid, 'EXECUTE')
       )
       OR EXISTS (
            SELECT 1
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'public'
              AND procedure.proname = ANY(persist_functions || operator_functions)
              AND has_function_privilege('geo_v2_worker', procedure.oid, 'EXECUTE')
       )
       OR has_function_privilege(
            'geo_v2_worker', 'geo_v2_resolve_session_context()', 'EXECUTE'
       ) THEN
        RAISE EXCEPTION 'Schema v2 worker/runtime function ACLs are over-broad';
    END IF;
    IF (
        SELECT count(*)
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = 'public'
          AND procedure.proname = ANY(operator_functions)
          AND has_function_privilege('geo_v2_runtime', procedure.oid, 'EXECUTE')
    ) <> cardinality(operator_functions) THEN
        RAISE EXCEPTION 'runtime operator command ACLs are incomplete';
    END IF;

    FOREACH table_name IN ARRAY domain_tables LOOP
        FOREACH privilege_name IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
            IF has_table_privilege(
                'geo_v2_worker', format('public.%I', table_name), privilege_name
            ) THEN
                RAISE EXCEPTION 'worker has forbidden % on %', privilege_name, table_name;
            END IF;
        END LOOP;
    END LOOP;
    FOREACH table_name IN ARRAY result_tables LOOP
        IF NOT has_table_privilege(
            'geo_v2_result_owner', format('public.%I', table_name), 'INSERT'
        ) OR has_table_privilege(
            'geo_v2_result_owner', format('public.%I', table_name), 'UPDATE'
        ) OR has_table_privilege(
            'geo_v2_result_owner', format('public.%I', table_name), 'DELETE'
        ) THEN
            RAISE EXCEPTION 'result owner writer ACL is not exact for %', table_name;
        END IF;
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY[
        'answer_runs', 'raw_answers', 'answer_citations',
        'visibility_score_snapshots', 'retest_comparisons'
    ] LOOP
        FOREACH privilege_name IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE'] LOOP
            IF has_table_privilege(
                'geo_v2_runtime', format('public.%I', table_name), privilege_name
            ) THEN
                RAISE EXCEPTION 'runtime has forbidden result-table DML';
            END IF;
        END LOOP;
    END LOOP;
    FOREACH table_name IN ARRAY ARRAY[
        'artifact_finalize_outbox', 'durable_job_dispatch_outbox', 'collection_jobs',
        'visibility_score_runs', 'retest_runs'
    ] LOOP
        IF NOT has_table_privilege(
            'geo_v2_job_owner', format('public.%I', table_name), 'SELECT'
        ) OR NOT has_table_privilege(
            'geo_v2_job_owner', format('public.%I', table_name), 'UPDATE'
        ) OR has_table_privilege(
            'geo_v2_job_owner', format('public.%I', table_name), 'INSERT'
        ) OR has_table_privilege(
            'geo_v2_job_owner', format('public.%I', table_name), 'DELETE'
        ) THEN
            RAISE EXCEPTION 'job owner queue ACL is not exact for %', table_name;
        END IF;
    END LOOP;
    IF NOT has_table_privilege(
        'geo_v2_job_command_owner',
        'public.durable_job_dispatch_outbox',
        'INSERT'
    ) OR has_table_privilege(
        'geo_v2_job_command_owner',
        'public.durable_job_dispatch_outbox',
        'UPDATE'
    ) OR has_table_privilege(
        'geo_v2_job_command_owner',
        'public.durable_job_dispatch_outbox',
        'DELETE'
    ) THEN
        RAISE EXCEPTION 'durable dispatch enqueue writer ACL is not exact';
    END IF;
    FOREACH privilege_name IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
        IF has_table_privilege(
            'geo_v2_runtime',
            'public.durable_job_dispatch_outbox',
            privilege_name
        ) THEN
            RAISE EXCEPTION 'runtime has forbidden durable dispatch outbox DML';
        END IF;
    END LOOP;
END;
$verify_job_security_boundary$;

COMMENT ON TABLE product_entities IS
    'Unified project-scoped brand, organization, product, competitor, market, and category subjects.';
COMMENT ON TABLE monitoring_queries IS
    'Stable GEO observation targets; never a prompt-template or writing-rule source of truth.';
COMMENT ON TABLE collection_jobs IS
    'Durable collection queue; claim/reclaim is atomic and owner plus lease_token fences every mutation.';
COMMENT ON TABLE visibility_score_runs IS
    'Durable scoring queue whose successful result is one immutable visibility score snapshot.';
COMMENT ON TABLE retest_runs IS
    'Durable same-scope retest queue linked to exact baseline and output score snapshots.';
COMMENT ON FUNCTION geo_v2_claim_collection_job(text, integer, uuid) IS
    'Claim or reclaim one job. Commit the claim transaction before any external provider call.';
COMMENT ON FUNCTION geo_v2_claim_visibility_score_run(text, integer, uuid) IS
    'Claim or reclaim one score run. Commit before performing scoring work outside PostgreSQL.';
COMMENT ON FUNCTION geo_v2_claim_retest_run(text, integer, uuid) IS
    'Claim or reclaim one retest. Commit before any external collection or model call.';
