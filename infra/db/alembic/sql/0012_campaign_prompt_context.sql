-- Freeze immutable Release identity without adding mutable lifecycle columns to it.
ALTER TABLE generation_template_releases
    ADD CONSTRAINT generation_template_releases_exact_identity_key
    UNIQUE (id, project_id, skill_version_id, release_number, release_hash);

CREATE TABLE generation_template_release_states (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    template_release_id uuid NOT NULL,
    skill_version_id uuid NOT NULL,
    release_number integer NOT NULL CHECK (release_number > 0),
    release_hash text NOT NULL CHECK (release_hash ~ '^[0-9a-f]{64}$'),
    state_version bigint NOT NULL CHECK (state_version > 0),
    previous_state_id uuid,
    status text NOT NULL CHECK (status IN ('draft', 'approved', 'revoked')),
    changed_by uuid REFERENCES identities(id),
    change_reason text,
    idempotency_key text CHECK (
        idempotency_key IS NULL OR (
            btrim(idempotency_key) <> '' AND length(idempotency_key) <= 256
        )
    ),
    command_hash text CHECK (
        command_hash IS NULL OR command_hash ~ '^[0-9a-f]{64}$'
    ),
    is_legacy_backfill boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (
        template_release_id, project_id, skill_version_id, release_number, release_hash
    ) REFERENCES generation_template_releases (
        id, project_id, skill_version_id, release_number, release_hash
    ),
    FOREIGN KEY (previous_state_id, project_id, template_release_id)
        REFERENCES generation_template_release_states(id, project_id, template_release_id),
    UNIQUE (id, project_id, template_release_id),
    UNIQUE (template_release_id, state_version),
    UNIQUE (previous_state_id),
    CHECK ((state_version = 1) = (previous_state_id IS NULL)),
    CHECK (status <> 'revoked' OR (
        changed_by IS NOT NULL AND btrim(COALESCE(change_reason, '')) <> ''
    )),
    CHECK (changed_by IS NOT NULL OR (
        is_legacy_backfill AND state_version = 1 AND status = 'approved'
    )),
    CHECK ((idempotency_key IS NULL) = (command_hash IS NULL)),
    CHECK (state_version = 1 OR idempotency_key IS NOT NULL),
    CHECK (NOT is_legacy_backfill OR (
        state_version = 1 AND previous_state_id IS NULL AND status = 'approved'
    ))
);

INSERT INTO generation_template_release_states (
    project_id, template_release_id, skill_version_id, release_number, release_hash,
    state_version, status, changed_by, is_legacy_backfill, created_at
)
SELECT release.project_id, release.id, release.skill_version_id, release.release_number,
       release.release_hash, 1, 'approved', version.created_by, true, release.created_at
FROM generation_template_releases AS release
JOIN prompt_skill_versions AS version
  ON version.id = release.skill_version_id AND version.project_id = release.project_id;

CREATE INDEX generation_template_release_states_current_idx
ON generation_template_release_states (
    project_id, template_release_id, state_version DESC, id DESC
);
CREATE INDEX generation_template_release_states_status_idx
ON generation_template_release_states (project_id, status, created_at DESC);
CREATE UNIQUE INDEX generation_template_release_states_idempotency_key
ON generation_template_release_states (project_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE VIEW current_generation_template_release_states
WITH (security_invoker = true) AS
SELECT DISTINCT ON (project_id, template_release_id)
       id, project_id, template_release_id, skill_version_id, release_number,
       release_hash, state_version, previous_state_id, status, changed_by,
       change_reason, idempotency_key, command_hash, is_legacy_backfill, created_at
FROM generation_template_release_states
ORDER BY project_id, template_release_id, state_version DESC, id DESC;

CREATE FUNCTION geo_assert_release_state_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_state record;
BEGIN
    PERFORM 1 FROM generation_template_releases AS release
    WHERE release.id = NEW.template_release_id AND release.project_id = NEW.project_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'template release does not exist in this project'
            USING ERRCODE = '23503';
    END IF;

    SELECT state.* INTO current_state
    FROM generation_template_release_states AS state
    WHERE state.template_release_id = NEW.template_release_id
      AND state.project_id = NEW.project_id
    ORDER BY state.state_version DESC, state.id DESC LIMIT 1;

    IF NOT FOUND THEN
        IF NEW.state_version <> 1 OR NEW.previous_state_id IS NOT NULL
           OR NEW.status <> 'draft' OR NEW.changed_by IS NULL
           OR NEW.is_legacy_backfill THEN
            RAISE EXCEPTION 'a new release lifecycle must start at draft version 1'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.previous_state_id IS DISTINCT FROM current_state.id
       OR NEW.state_version <> current_state.state_version + 1 THEN
        RAISE EXCEPTION 'release state must append to the current version'
            USING ERRCODE = '40001';
    END IF;
    IF NOT (
        (current_state.status = 'draft' AND NEW.status = 'approved')
        OR (current_state.status = 'approved' AND NEW.status = 'revoked')
    ) THEN
        RAISE EXCEPTION 'invalid release state transition' USING ERRCODE = '23514';
    END IF;
    IF NEW.changed_by IS NULL OR NEW.is_legacy_backfill THEN
        RAISE EXCEPTION 'release state transitions require an actor'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_protect_append_only_release_state() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'template release states are append-only' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER generation_template_release_state_append_guard
BEFORE INSERT ON generation_template_release_states
FOR EACH ROW EXECUTE FUNCTION geo_assert_release_state_append();
CREATE TRIGGER generation_template_release_states_immutable
BEFORE UPDATE OR DELETE ON generation_template_release_states
FOR EACH ROW EXECUTE FUNCTION geo_protect_append_only_release_state();

CREATE FUNCTION geo_require_release_initial_state() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM generation_template_release_states AS state
        WHERE state.template_release_id = NEW.id AND state.project_id = NEW.project_id
          AND state.state_version = 1
    ) THEN
        RAISE EXCEPTION 'new template releases require a lifecycle state in the same transaction'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER generation_template_release_requires_state
AFTER INSERT ON generation_template_releases
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_release_initial_state();

-- Opportunity membership is the only Campaign-to-Destination ownership relation.
ALTER TABLE placement_opportunities
    ADD CONSTRAINT placement_opportunities_exact_context_key
    UNIQUE (id, project_id, campaign_id, destination_id);

ALTER TABLE campaign_monitoring_queries
    ADD CONSTRAINT campaign_monitoring_queries_exact_context_key
    UNIQUE (campaign_id, monitoring_query_id, project_id);

CREATE TABLE opportunity_prompt_release_bindings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    campaign_id uuid NOT NULL,
    opportunity_id uuid NOT NULL,
    destination_id uuid NOT NULL,
    binding_version integer NOT NULL CHECK (binding_version > 0),
    previous_binding_id uuid,
    binding_state text NOT NULL CHECK (binding_state IN ('unbound', 'bound')),
    template_release_id uuid,
    skill_version_id uuid,
    release_number integer,
    release_hash text CHECK (release_hash IS NULL OR release_hash ~ '^[0-9a-f]{64}$'),
    changed_by uuid REFERENCES identities(id),
    change_reason text,
    idempotency_key text CHECK (
        idempotency_key IS NULL OR (
            btrim(idempotency_key) <> '' AND length(idempotency_key) <= 256
        )
    ),
    command_hash text CHECK (
        command_hash IS NULL OR command_hash ~ '^[0-9a-f]{64}$'
    ),
    is_legacy_backfill boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (opportunity_id, project_id, campaign_id, destination_id)
        REFERENCES placement_opportunities(id, project_id, campaign_id, destination_id)
        ON DELETE CASCADE,
    FOREIGN KEY (
        template_release_id, project_id, skill_version_id, release_number, release_hash
    ) REFERENCES generation_template_releases (
        id, project_id, skill_version_id, release_number, release_hash
    ),
    FOREIGN KEY (
        previous_binding_id, project_id, campaign_id, opportunity_id, destination_id
    ) REFERENCES opportunity_prompt_release_bindings (
        id, project_id, campaign_id, opportunity_id, destination_id
    ),
    UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id),
    UNIQUE (opportunity_id, binding_version),
    UNIQUE (previous_binding_id),
    UNIQUE (
        id, project_id, campaign_id, opportunity_id, destination_id, binding_version,
        template_release_id, skill_version_id, release_number, release_hash
    ),
    CHECK ((binding_version = 1) = (previous_binding_id IS NULL)),
    CHECK (
        (binding_state = 'bound' AND num_nonnulls(
            template_release_id, skill_version_id, release_number, release_hash
        ) = 4)
        OR (binding_state = 'unbound' AND num_nonnulls(
            template_release_id, skill_version_id, release_number, release_hash
        ) = 0)
    ),
    CHECK (changed_by IS NOT NULL OR (
        is_legacy_backfill AND binding_version = 1 AND binding_state = 'unbound'
    )),
    CHECK ((idempotency_key IS NULL) = (command_hash IS NULL)),
    CHECK (binding_version = 1 OR idempotency_key IS NOT NULL),
    CHECK (NOT is_legacy_backfill OR (
        binding_version = 1 AND binding_state = 'unbound'
    ))
);

INSERT INTO opportunity_prompt_release_bindings (
    project_id, campaign_id, opportunity_id, destination_id, binding_version,
    binding_state, changed_by, change_reason, is_legacy_backfill, created_at
)
SELECT opportunity.project_id, opportunity.campaign_id, opportunity.id,
       opportunity.destination_id, 1, 'unbound', campaign.created_by,
       'legacy opportunity migrated explicitly unbound', true, opportunity.created_at
FROM placement_opportunities AS opportunity
JOIN geo_campaigns AS campaign
  ON campaign.id = opportunity.campaign_id AND campaign.project_id = opportunity.project_id;

CREATE INDEX opportunity_prompt_bindings_current_idx
ON opportunity_prompt_release_bindings (
    project_id, campaign_id, opportunity_id, binding_version DESC, id DESC
);
CREATE INDEX opportunity_prompt_bindings_release_idx
ON opportunity_prompt_release_bindings (project_id, template_release_id, created_at DESC)
WHERE binding_state = 'bound';
CREATE UNIQUE INDEX opportunity_prompt_bindings_idempotency_key
ON opportunity_prompt_release_bindings (project_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE VIEW current_opportunity_prompt_release_bindings
WITH (security_invoker = true) AS
SELECT DISTINCT ON (project_id, campaign_id, opportunity_id)
       id, project_id, campaign_id, opportunity_id, destination_id,
       binding_version, previous_binding_id, binding_state, template_release_id,
       skill_version_id, release_number, release_hash, changed_by, change_reason,
       idempotency_key, command_hash, is_legacy_backfill, created_at
FROM opportunity_prompt_release_bindings
ORDER BY project_id, campaign_id, opportunity_id, binding_version DESC, id DESC;

CREATE FUNCTION geo_assert_opportunity_prompt_binding_append() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    current_binding record;
BEGIN
    PERFORM 1 FROM placement_opportunities AS opportunity
    WHERE opportunity.id = NEW.opportunity_id AND opportunity.project_id = NEW.project_id
      AND opportunity.campaign_id = NEW.campaign_id
      AND opportunity.destination_id = NEW.destination_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'prompt binding does not match its Opportunity context'
            USING ERRCODE = '23514';
    END IF;

    SELECT binding.* INTO current_binding
    FROM opportunity_prompt_release_bindings AS binding
    WHERE binding.opportunity_id = NEW.opportunity_id
      AND binding.project_id = NEW.project_id
      AND binding.campaign_id = NEW.campaign_id
    ORDER BY binding.binding_version DESC, binding.id DESC LIMIT 1;

    IF NOT FOUND THEN
        IF NEW.binding_version <> 1 OR NEW.previous_binding_id IS NOT NULL
           OR NEW.changed_by IS NULL OR NEW.is_legacy_backfill THEN
            RAISE EXCEPTION 'new Opportunity binding history must start at version 1'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.previous_binding_id IS DISTINCT FROM current_binding.id
          OR NEW.binding_version <> current_binding.binding_version + 1 THEN
        RAISE EXCEPTION 'prompt binding must append to the current version'
            USING ERRCODE = '40001';
    END IF;

    IF NEW.changed_by IS NULL OR NEW.is_legacy_backfill THEN
        RAISE EXCEPTION 'prompt binding changes require an actor'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.binding_state = 'bound' AND NOT EXISTS (
        SELECT 1 FROM current_generation_template_release_states AS state
        WHERE state.template_release_id = NEW.template_release_id
          AND state.project_id = NEW.project_id
          AND state.skill_version_id = NEW.skill_version_id
          AND state.release_number = NEW.release_number
          AND state.release_hash = NEW.release_hash
          AND state.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'Opportunity bindings require a currently approved Prompt Release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_protect_opportunity_prompt_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Opportunity Prompt bindings are append-only' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER opportunity_prompt_binding_append_guard
BEFORE INSERT ON opportunity_prompt_release_bindings
FOR EACH ROW EXECUTE FUNCTION geo_assert_opportunity_prompt_binding_append();
CREATE TRIGGER opportunity_prompt_release_bindings_immutable
BEFORE UPDATE OR DELETE ON opportunity_prompt_release_bindings
FOR EACH ROW EXECUTE FUNCTION geo_protect_opportunity_prompt_binding();

CREATE FUNCTION geo_require_opportunity_initial_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM opportunity_prompt_release_bindings AS binding
        WHERE binding.opportunity_id = NEW.id AND binding.project_id = NEW.project_id
          AND binding.campaign_id = NEW.campaign_id AND binding.destination_id = NEW.destination_id
          AND binding.binding_version = 1
    ) THEN
        RAISE EXCEPTION 'new Opportunities require an explicit binding state'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER placement_opportunity_requires_initial_binding
AFTER INSERT ON placement_opportunities
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_opportunity_initial_binding();

-- Temporarily remove immutable guards only for deterministic ancestry backfill.
DROP TRIGGER placement_brief_versions_immutable ON placement_brief_versions;
DROP TRIGGER evidence_pack_attempt_terminal_immutable ON evidence_pack_attempts;
DROP TRIGGER prompt_bundles_immutable ON prompt_bundles;
DROP TRIGGER placement_export_receipts_immutable ON placement_export_receipts;
DROP TRIGGER prompt_simulation_scope_guard ON prompt_simulations;
DROP TRIGGER prompt_simulations_immutable ON prompt_simulations;
DROP TRIGGER prompt_simulation_results_immutable ON prompt_simulation_results;

ALTER TABLE placement_briefs
    ADD COLUMN campaign_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE placement_briefs AS brief
SET campaign_id = opportunity.campaign_id,
    destination_id = opportunity.destination_id
FROM placement_opportunities AS opportunity
WHERE opportunity.id = brief.opportunity_id AND opportunity.project_id = brief.project_id;
ALTER TABLE placement_briefs
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT placement_briefs_exact_opportunity_fkey
        FOREIGN KEY (opportunity_id, project_id, campaign_id, destination_id)
        REFERENCES placement_opportunities(id, project_id, campaign_id, destination_id),
    ADD CONSTRAINT placement_briefs_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id);

ALTER TABLE placement_brief_versions
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE placement_brief_versions AS version
SET campaign_id = brief.campaign_id,
    opportunity_id = brief.opportunity_id,
    destination_id = brief.destination_id
FROM placement_briefs AS brief
WHERE brief.id = version.brief_id AND brief.project_id = version.project_id;
ALTER TABLE placement_brief_versions
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT placement_brief_versions_exact_brief_fkey
        FOREIGN KEY (brief_id, project_id, campaign_id, opportunity_id, destination_id)
        REFERENCES placement_briefs(id, project_id, campaign_id, opportunity_id, destination_id),
    ADD CONSTRAINT placement_brief_versions_exact_lineage_key
        UNIQUE (
            id, project_id, campaign_id, opportunity_id, destination_id, brief_id
        ),
    ADD CONSTRAINT placement_brief_versions_exact_base_fkey
        FOREIGN KEY (
            base_version_id, project_id, campaign_id, opportunity_id,
            destination_id, brief_id
        ) REFERENCES placement_brief_versions(
            id, project_id, campaign_id, opportunity_id, destination_id, brief_id
        ),
    ADD CONSTRAINT placement_brief_versions_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id);

ALTER TABLE evidence_pack_attempts
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE evidence_pack_attempts AS attempt
SET campaign_id = version.campaign_id,
    opportunity_id = version.opportunity_id,
    destination_id = version.destination_id
FROM placement_brief_versions AS version
WHERE version.id = attempt.brief_version_id AND version.project_id = attempt.project_id;
ALTER TABLE evidence_pack_attempts
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT evidence_pack_attempts_exact_brief_version_fkey
        FOREIGN KEY (brief_version_id, project_id, campaign_id, opportunity_id, destination_id)
        REFERENCES placement_brief_versions(
            id, project_id, campaign_id, opportunity_id, destination_id
        ),
    ADD CONSTRAINT evidence_pack_attempts_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id),
    ADD CONSTRAINT evidence_pack_attempts_exact_brief_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, brief_version_id),
    ADD CONSTRAINT evidence_pack_attempts_exact_bundle_context_key
        UNIQUE (
            id, project_id, campaign_id, opportunity_id, destination_id,
            brief_version_id
        ),
    ADD CONSTRAINT evidence_pack_attempts_exact_superseded_by_fkey
        FOREIGN KEY (
            superseded_by_attempt_id, project_id, campaign_id, opportunity_id,
            destination_id, brief_version_id
        ) REFERENCES evidence_pack_attempts(
            id, project_id, campaign_id, opportunity_id, destination_id,
            brief_version_id
        ),
    ADD CONSTRAINT evidence_pack_attempts_job_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id);

ALTER TABLE prompt_bundles
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid,
    ADD COLUMN binding_id uuid,
    ADD COLUMN binding_version integer,
    ADD COLUMN template_skill_version_id uuid,
    ADD COLUMN template_release_number integer,
    ADD COLUMN template_release_hash text,
    ADD COLUMN idempotency_key text,
    ADD COLUMN command_hash text,
    ADD COLUMN binding_contract_version text NOT NULL DEFAULT 'legacy-v1';
UPDATE prompt_bundles AS bundle
SET campaign_id = version.campaign_id,
    opportunity_id = version.opportunity_id,
    destination_id = version.destination_id,
    template_skill_version_id = release.skill_version_id,
    template_release_number = release.release_number,
    template_release_hash = release.release_hash
FROM placement_brief_versions AS version,
     generation_template_releases AS release
WHERE version.id = bundle.brief_version_id AND version.project_id = bundle.project_id
  AND release.id = bundle.template_release_id AND release.project_id = bundle.project_id;
ALTER TABLE prompt_bundles
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ALTER COLUMN template_skill_version_id SET NOT NULL,
    ALTER COLUMN template_release_number SET NOT NULL,
    ALTER COLUMN template_release_hash SET NOT NULL,
    ALTER COLUMN binding_contract_version SET DEFAULT 'opportunity-binding-v2',
    ADD CONSTRAINT prompt_bundles_binding_contract_check CHECK (
        (binding_contract_version = 'legacy-v1'
            AND binding_id IS NULL AND binding_version IS NULL)
        OR (binding_contract_version = 'opportunity-binding-v2'
            AND binding_id IS NOT NULL AND binding_version IS NOT NULL)
    ),
    ADD CONSTRAINT prompt_bundles_binding_contract_version_check CHECK (
        binding_contract_version IN ('legacy-v1', 'opportunity-binding-v2')
    ),
    ADD CONSTRAINT prompt_bundles_template_release_hash_check
        CHECK (template_release_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT prompt_bundles_idempotency_key_check CHECK (
        idempotency_key IS NULL OR (
            btrim(idempotency_key) <> '' AND length(idempotency_key) <= 256
        )
    ),
    ADD CONSTRAINT prompt_bundles_command_hash_check CHECK (
        command_hash IS NULL OR command_hash ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT prompt_bundles_idempotency_pair_check CHECK (
        (idempotency_key IS NULL) = (command_hash IS NULL)
    ),
    ADD CONSTRAINT prompt_bundles_v2_idempotency_check CHECK (
        binding_contract_version = 'legacy-v1' OR idempotency_key IS NOT NULL
    ),
    ADD CONSTRAINT prompt_bundles_exact_brief_version_fkey
        FOREIGN KEY (brief_version_id, project_id, campaign_id, opportunity_id, destination_id)
        REFERENCES placement_brief_versions(
            id, project_id, campaign_id, opportunity_id, destination_id
        ),
    ADD CONSTRAINT prompt_bundles_exact_evidence_attempt_fkey
        FOREIGN KEY (
            evidence_pack_attempt_id, project_id, campaign_id, opportunity_id,
            destination_id, brief_version_id
        ) REFERENCES evidence_pack_attempts(
            id, project_id, campaign_id, opportunity_id, destination_id,
            brief_version_id
        ),
    ADD CONSTRAINT prompt_bundles_exact_release_fkey
        FOREIGN KEY (
            template_release_id, project_id, template_skill_version_id,
            template_release_number, template_release_hash
        ) REFERENCES generation_template_releases(
            id, project_id, skill_version_id, release_number, release_hash
        ),
    ADD CONSTRAINT prompt_bundles_exact_binding_fkey
        FOREIGN KEY (
            binding_id, project_id, campaign_id, opportunity_id, destination_id,
            binding_version, template_release_id, template_skill_version_id,
            template_release_number, template_release_hash
        ) REFERENCES opportunity_prompt_release_bindings(
            id, project_id, campaign_id, opportunity_id, destination_id,
            binding_version, template_release_id, skill_version_id,
            release_number, release_hash
        ),
    ADD CONSTRAINT prompt_bundles_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id),
    ADD CONSTRAINT prompt_bundles_job_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id);

CREATE FUNCTION geo_assert_prompt_bundle_binding() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.binding_contract_version <> 'opportunity-binding-v2' THEN
        RAISE EXCEPTION 'new Prompt Bundles require an Opportunity binding'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM current_opportunity_prompt_release_bindings AS binding
        JOIN current_generation_template_release_states AS state
          ON state.template_release_id = binding.template_release_id
         AND state.project_id = binding.project_id
        WHERE binding.id = NEW.binding_id AND binding.project_id = NEW.project_id
          AND binding.campaign_id = NEW.campaign_id
          AND binding.opportunity_id = NEW.opportunity_id
          AND binding.destination_id = NEW.destination_id
          AND binding.binding_version = NEW.binding_version
          AND binding.binding_state = 'bound'
          AND binding.template_release_id = NEW.template_release_id
          AND binding.skill_version_id = NEW.template_skill_version_id
          AND binding.release_number = NEW.template_release_number
          AND binding.release_hash = NEW.template_release_hash
          AND state.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'Prompt Bundle binding is stale, unbound, or not approved'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM evidence_pack_attempts AS attempt
        WHERE attempt.id = NEW.evidence_pack_attempt_id
          AND attempt.project_id = NEW.project_id
          AND attempt.campaign_id = NEW.campaign_id
          AND attempt.opportunity_id = NEW.opportunity_id
          AND attempt.destination_id = NEW.destination_id
          AND attempt.status = 'ready'
    ) THEN
        RAISE EXCEPTION 'Prompt Bundle requires ready Evidence in the same Campaign context'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER prompt_bundle_binding_guard
BEFORE INSERT ON prompt_bundles
FOR EACH ROW EXECUTE FUNCTION geo_assert_prompt_bundle_binding();

CREATE UNIQUE INDEX prompt_bundles_idempotency_key
ON prompt_bundles (project_id, idempotency_key)
WHERE idempotency_key IS NOT NULL;

ALTER TABLE placement_packages
    ADD COLUMN campaign_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE placement_packages AS package
SET campaign_id = opportunity.campaign_id,
    destination_id = opportunity.destination_id
FROM placement_opportunities AS opportunity
WHERE opportunity.id = package.opportunity_id AND opportunity.project_id = package.project_id;
ALTER TABLE placement_packages
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT placement_packages_exact_opportunity_fkey
        FOREIGN KEY (opportunity_id, project_id, campaign_id, destination_id)
        REFERENCES placement_opportunities(id, project_id, campaign_id, destination_id),
    ADD CONSTRAINT placement_packages_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id);

ALTER TABLE placement_package_versions
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE placement_package_versions AS version
SET campaign_id = package.campaign_id,
    opportunity_id = package.opportunity_id,
    destination_id = package.destination_id
FROM placement_packages AS package
WHERE package.id = version.package_id AND package.project_id = version.project_id;
ALTER TABLE placement_package_versions
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT placement_package_versions_exact_package_fkey
        FOREIGN KEY (package_id, project_id, campaign_id, opportunity_id, destination_id)
        REFERENCES placement_packages(id, project_id, campaign_id, opportunity_id, destination_id),
    ADD CONSTRAINT placement_package_versions_exact_bundle_fkey
        FOREIGN KEY (
            prompt_bundle_id, project_id, campaign_id, opportunity_id, destination_id
        ) REFERENCES prompt_bundles(
            id, project_id, campaign_id, opportunity_id, destination_id
        ),
    ADD CONSTRAINT placement_package_versions_exact_lineage_key
        UNIQUE (
            id, project_id, campaign_id, opportunity_id, destination_id, package_id
        ),
    ADD CONSTRAINT placement_package_versions_exact_base_fkey
        FOREIGN KEY (
            base_version_id, project_id, campaign_id, opportunity_id,
            destination_id, package_id
        ) REFERENCES placement_package_versions(
            id, project_id, campaign_id, opportunity_id, destination_id, package_id
        ),
    ADD CONSTRAINT placement_package_versions_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id);

ALTER TABLE placement_export_receipts
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE placement_export_receipts AS receipt
SET campaign_id = version.campaign_id,
    opportunity_id = version.opportunity_id,
    destination_id = version.destination_id
FROM placement_package_versions AS version
WHERE version.id = receipt.package_version_id AND version.project_id = receipt.project_id;
ALTER TABLE placement_export_receipts
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT placement_export_receipts_exact_version_fkey
        FOREIGN KEY (
            package_version_id, project_id, campaign_id, opportunity_id, destination_id
        ) REFERENCES placement_package_versions(
            id, project_id, campaign_id, opportunity_id, destination_id
        );

ALTER TABLE publication_requests
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid;
UPDATE publication_requests AS request
SET campaign_id = version.campaign_id,
    opportunity_id = version.opportunity_id
FROM placement_package_versions AS version
WHERE version.id = request.package_version_id AND version.project_id = request.project_id
  AND version.destination_id = request.destination_id;
ALTER TABLE publication_requests
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ADD CONSTRAINT publication_requests_exact_package_version_fkey
        FOREIGN KEY (
            package_version_id, project_id, campaign_id, opportunity_id, destination_id
        ) REFERENCES placement_package_versions(
            id, project_id, campaign_id, opportunity_id, destination_id
        ),
    ADD CONSTRAINT publication_requests_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id);

ALTER TABLE publication_submissions
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE publication_submissions AS submission
SET campaign_id = request.campaign_id,
    opportunity_id = request.opportunity_id,
    destination_id = request.destination_id
FROM publication_requests AS request
WHERE request.id = submission.publication_request_id
  AND request.project_id = submission.project_id;
ALTER TABLE publication_submissions
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT publication_submissions_exact_request_fkey
        FOREIGN KEY (
            publication_request_id, project_id, campaign_id, opportunity_id, destination_id
        ) REFERENCES publication_requests(
            id, project_id, campaign_id, opportunity_id, destination_id
        ),
    ADD CONSTRAINT publication_submissions_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id, destination_id),
    ADD CONSTRAINT publication_submissions_job_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id);

ALTER TABLE placement_measurements
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE placement_measurements AS measurement
SET campaign_id = submission.campaign_id,
    opportunity_id = submission.opportunity_id,
    destination_id = submission.destination_id
FROM publication_submissions AS submission
WHERE submission.id = measurement.submission_id
  AND submission.project_id = measurement.project_id;
ALTER TABLE placement_measurements
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT placement_measurements_exact_submission_fkey
        FOREIGN KEY (
            submission_id, project_id, campaign_id, opportunity_id, destination_id
        ) REFERENCES publication_submissions(
            id, project_id, campaign_id, opportunity_id, destination_id
        ),
    ADD CONSTRAINT placement_measurements_exact_campaign_query_fkey
        FOREIGN KEY (campaign_id, monitoring_query_id, project_id)
        REFERENCES campaign_monitoring_queries(
            campaign_id, monitoring_query_id, project_id
        );

ALTER TABLE measurement_collection_tasks
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE measurement_collection_tasks AS task
SET campaign_id = submission.campaign_id,
    opportunity_id = submission.opportunity_id,
    destination_id = submission.destination_id
FROM publication_submissions AS submission
WHERE submission.id = task.submission_id AND submission.project_id = task.project_id;
ALTER TABLE measurement_collection_tasks
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ALTER COLUMN destination_id SET NOT NULL,
    ADD CONSTRAINT measurement_collection_tasks_exact_submission_fkey
        FOREIGN KEY (
            submission_id, project_id, campaign_id, opportunity_id, destination_id
        ) REFERENCES publication_submissions(
            id, project_id, campaign_id, opportunity_id, destination_id
        ),
    ADD CONSTRAINT measurement_collection_tasks_exact_protocol_fkey
        FOREIGN KEY (protocol_id, campaign_id, project_id)
        REFERENCES monitoring_protocols(id, campaign_id, project_id);

-- Legacy simulations cannot be assigned to an Opportunity without guessing.
ALTER TABLE prompt_simulations
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN binding_id uuid,
    ADD COLUMN binding_version integer,
    ADD COLUMN template_skill_version_id uuid,
    ADD COLUMN template_release_number integer,
    ADD COLUMN template_release_hash text,
    ADD COLUMN binding_contract_version text NOT NULL DEFAULT 'legacy-v1';
UPDATE prompt_simulations AS simulation
SET template_skill_version_id = release.skill_version_id,
    template_release_number = release.release_number,
    template_release_hash = release.release_hash
FROM generation_template_releases AS release
WHERE release.id = simulation.template_release_id
  AND release.project_id = simulation.project_id;
ALTER TABLE prompt_simulations
    ALTER COLUMN template_skill_version_id SET NOT NULL,
    ALTER COLUMN template_release_number SET NOT NULL,
    ALTER COLUMN template_release_hash SET NOT NULL,
    ALTER COLUMN binding_contract_version SET DEFAULT 'opportunity-binding-v2',
    ADD CONSTRAINT prompt_simulations_binding_contract_version_check CHECK (
        binding_contract_version IN ('legacy-v1', 'opportunity-binding-v2')
    ),
    ADD CONSTRAINT prompt_simulations_binding_contract_check CHECK (
        (binding_contract_version = 'legacy-v1' AND campaign_id IS NULL
            AND opportunity_id IS NULL AND binding_id IS NULL AND binding_version IS NULL)
        OR (binding_contract_version = 'opportunity-binding-v2' AND campaign_id IS NOT NULL
            AND opportunity_id IS NOT NULL AND binding_id IS NOT NULL
            AND binding_version IS NOT NULL)
    ),
    ADD CONSTRAINT prompt_simulations_template_release_hash_check
        CHECK (template_release_hash ~ '^[0-9a-f]{64}$'),
    ADD CONSTRAINT prompt_simulations_exact_opportunity_fkey
        FOREIGN KEY (opportunity_id, project_id, campaign_id, destination_id)
        REFERENCES placement_opportunities(id, project_id, campaign_id, destination_id),
    ADD CONSTRAINT prompt_simulations_exact_release_fkey
        FOREIGN KEY (
            template_release_id, project_id, template_skill_version_id,
            template_release_number, template_release_hash
        ) REFERENCES generation_template_releases(
            id, project_id, skill_version_id, release_number, release_hash
        ),
    ADD CONSTRAINT prompt_simulations_exact_binding_fkey
        FOREIGN KEY (
            binding_id, project_id, campaign_id, opportunity_id, destination_id,
            binding_version, template_release_id, template_skill_version_id,
            template_release_number, template_release_hash
        ) REFERENCES opportunity_prompt_release_bindings(
            id, project_id, campaign_id, opportunity_id, destination_id,
            binding_version, template_release_id, skill_version_id,
            release_number, release_hash
        ),
    ADD CONSTRAINT prompt_simulations_exact_context_key
        UNIQUE (id, project_id, campaign_id, opportunity_id);

CREATE OR REPLACE FUNCTION geo_assert_prompt_simulation_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM product_entities AS entity
        WHERE entity.id = NEW.primary_brand_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'brand' AND entity.status = 'active'
    ) OR NOT EXISTS (
        SELECT 1 FROM product_entities AS entity
        WHERE entity.id = NEW.product_entity_id
          AND entity.project_id = NEW.project_id
          AND entity.entity_type = 'product' AND entity.status = 'active'
    ) THEN
        RAISE EXCEPTION 'prompt simulation subjects must be active brand and product entities'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.destination_policy_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM destination_policy_versions AS policy
        WHERE policy.id = NEW.destination_policy_version_id
          AND policy.project_id = NEW.project_id
          AND policy.destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'prompt simulation policy does not belong to its destination'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.binding_contract_version <> 'opportunity-binding-v2' THEN
        RAISE EXCEPTION 'new prompt simulations require an Opportunity binding'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM current_opportunity_prompt_release_bindings AS binding
        JOIN current_generation_template_release_states AS state
          ON state.template_release_id = binding.template_release_id
         AND state.project_id = binding.project_id
        WHERE binding.id = NEW.binding_id AND binding.project_id = NEW.project_id
          AND binding.campaign_id = NEW.campaign_id
          AND binding.opportunity_id = NEW.opportunity_id
          AND binding.destination_id = NEW.destination_id
          AND binding.binding_version = NEW.binding_version
          AND binding.binding_state = 'bound'
          AND binding.template_release_id = NEW.template_release_id
          AND binding.skill_version_id = NEW.template_skill_version_id
          AND binding.release_number = NEW.template_release_number
          AND binding.release_hash = NEW.template_release_hash
          AND state.status = 'approved'
    ) THEN
        RAISE EXCEPTION 'prompt simulation binding is stale, unbound, or not approved'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE prompt_simulation_results
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN lineage_contract_version text NOT NULL DEFAULT 'legacy-v1';
UPDATE prompt_simulation_results AS result
SET campaign_id = simulation.campaign_id,
    opportunity_id = simulation.opportunity_id
FROM prompt_simulations AS simulation
WHERE simulation.id = result.simulation_id
  AND simulation.project_id = result.project_id;
ALTER TABLE prompt_simulation_results
    ALTER COLUMN lineage_contract_version SET DEFAULT 'opportunity-binding-v2',
    ADD CONSTRAINT prompt_simulation_results_lineage_contract_check CHECK (
        (lineage_contract_version = 'legacy-v1'
            AND campaign_id IS NULL AND opportunity_id IS NULL)
        OR (lineage_contract_version = 'opportunity-binding-v2'
            AND campaign_id IS NOT NULL AND opportunity_id IS NOT NULL)
    ),
    ADD CONSTRAINT prompt_simulation_results_exact_simulation_fkey
        FOREIGN KEY (simulation_id, project_id, campaign_id, opportunity_id)
        REFERENCES prompt_simulations(id, project_id, campaign_id, opportunity_id);

-- Durable jobs keep nullable Campaign context for non-Placement work only.
ALTER TABLE durable_jobs ADD COLUMN campaign_id uuid;
ALTER TABLE durable_jobs
    ADD CONSTRAINT durable_jobs_campaign_fkey
        FOREIGN KEY (campaign_id, project_id) REFERENCES geo_campaigns(id, project_id),
    ADD CONSTRAINT durable_jobs_exact_campaign_key UNIQUE (id, project_id, campaign_id);

UPDATE durable_jobs AS job SET campaign_id = attempt.campaign_id
FROM evidence_pack_job_specs AS spec
JOIN evidence_pack_attempts AS attempt
  ON attempt.id = spec.evidence_pack_attempt_id AND attempt.project_id = spec.project_id
WHERE job.id = spec.job_id AND job.project_id = spec.project_id;
UPDATE durable_jobs AS job SET campaign_id = bundle.campaign_id
FROM generation_job_specs AS spec
JOIN prompt_bundles AS bundle
  ON bundle.id = spec.prompt_bundle_id AND bundle.project_id = spec.project_id
WHERE job.id = spec.job_id AND job.project_id = spec.project_id;
UPDATE durable_jobs AS job SET campaign_id = submission.campaign_id
FROM verification_job_specs AS spec
JOIN publication_submissions AS submission
  ON submission.id = spec.submission_id AND submission.project_id = spec.project_id
WHERE job.id = spec.job_id AND job.project_id = spec.project_id;
UPDATE durable_jobs AS job SET campaign_id = submission.campaign_id
FROM measurement_job_specs AS spec
JOIN publication_submissions AS submission
  ON submission.id = spec.submission_id AND submission.project_id = spec.project_id
WHERE job.id = spec.job_id AND job.project_id = spec.project_id;

ALTER TABLE evidence_pack_job_specs
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid;
UPDATE evidence_pack_job_specs AS spec
SET campaign_id = attempt.campaign_id, opportunity_id = attempt.opportunity_id
FROM evidence_pack_attempts AS attempt
WHERE attempt.id = spec.evidence_pack_attempt_id AND attempt.project_id = spec.project_id;
ALTER TABLE evidence_pack_job_specs
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ADD CONSTRAINT evidence_pack_job_specs_exact_job_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id) ON DELETE CASCADE,
    ADD CONSTRAINT evidence_pack_job_specs_exact_attempt_fkey
        FOREIGN KEY (
            evidence_pack_attempt_id, project_id, campaign_id, opportunity_id,
            brief_version_id
        ) REFERENCES evidence_pack_attempts(
            id, project_id, campaign_id, opportunity_id, brief_version_id
        );

ALTER TABLE generation_job_specs
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid;
UPDATE generation_job_specs AS spec
SET campaign_id = bundle.campaign_id, opportunity_id = bundle.opportunity_id
FROM prompt_bundles AS bundle
WHERE bundle.id = spec.prompt_bundle_id AND bundle.project_id = spec.project_id;
ALTER TABLE generation_job_specs
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ADD CONSTRAINT generation_job_specs_exact_job_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id) ON DELETE CASCADE,
    ADD CONSTRAINT generation_job_specs_exact_bundle_fkey
        FOREIGN KEY (prompt_bundle_id, project_id, campaign_id, opportunity_id)
        REFERENCES prompt_bundles(id, project_id, campaign_id, opportunity_id),
    ADD CONSTRAINT generation_job_specs_exact_generation_key
        UNIQUE (
            job_id, project_id, campaign_id, opportunity_id, prompt_bundle_id
        );

ALTER TABLE verification_job_specs
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid;
UPDATE verification_job_specs AS spec
SET campaign_id = submission.campaign_id, opportunity_id = submission.opportunity_id
FROM publication_submissions AS submission
WHERE submission.id = spec.submission_id AND submission.project_id = spec.project_id;
ALTER TABLE verification_job_specs
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ADD CONSTRAINT verification_job_specs_exact_job_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id) ON DELETE CASCADE,
    ADD CONSTRAINT verification_job_specs_exact_submission_fkey
        FOREIGN KEY (submission_id, project_id, campaign_id, opportunity_id)
        REFERENCES publication_submissions(id, project_id, campaign_id, opportunity_id);

ALTER TABLE measurement_job_specs
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid;
UPDATE measurement_job_specs AS spec
SET campaign_id = submission.campaign_id, opportunity_id = submission.opportunity_id
FROM publication_submissions AS submission
WHERE submission.id = spec.submission_id AND submission.project_id = spec.project_id;
ALTER TABLE measurement_job_specs
    ALTER COLUMN campaign_id SET NOT NULL,
    ALTER COLUMN opportunity_id SET NOT NULL,
    ADD CONSTRAINT measurement_job_specs_exact_job_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id) ON DELETE CASCADE,
    ADD CONSTRAINT measurement_job_specs_exact_submission_fkey
        FOREIGN KEY (submission_id, project_id, campaign_id, opportunity_id)
        REFERENCES publication_submissions(id, project_id, campaign_id, opportunity_id),
    ADD CONSTRAINT measurement_job_specs_exact_protocol_fkey
        FOREIGN KEY (protocol_id, campaign_id, project_id)
        REFERENCES monitoring_protocols(id, campaign_id, project_id),
    ADD CONSTRAINT measurement_job_specs_exact_collection_key
        UNIQUE (
            job_id, project_id, campaign_id, opportunity_id, submission_id,
            protocol_id
        );

ALTER TABLE prompt_simulation_job_specs
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD CONSTRAINT prompt_simulation_job_specs_campaign_pair_check
        CHECK ((campaign_id IS NULL) = (opportunity_id IS NULL)),
    ADD CONSTRAINT prompt_simulation_job_specs_exact_job_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id) ON DELETE CASCADE,
    ADD CONSTRAINT prompt_simulation_job_specs_exact_simulation_fkey
        FOREIGN KEY (simulation_id, project_id, campaign_id, opportunity_id)
        REFERENCES prompt_simulations(id, project_id, campaign_id, opportunity_id),
    ADD CONSTRAINT prompt_simulation_job_specs_exact_result_key
        UNIQUE (
            job_id, project_id, campaign_id, opportunity_id, simulation_id
        );

ALTER TABLE prompt_simulation_results
    ADD CONSTRAINT prompt_simulation_results_exact_job_spec_fkey
        FOREIGN KEY (
            generated_by_job_id, project_id, campaign_id, opportunity_id,
            simulation_id
        ) REFERENCES prompt_simulation_job_specs(
            job_id, project_id, campaign_id, opportunity_id, simulation_id
        );

CREATE FUNCTION geo_assert_new_prompt_simulation_result() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.lineage_contract_version = 'opportunity-binding-v2' THEN
        RETURN NEW;
    END IF;
    IF NEW.lineage_contract_version = 'legacy-v1' AND EXISTS (
        SELECT 1
        FROM prompt_simulations AS simulation
        JOIN prompt_simulation_job_specs AS spec
          ON spec.simulation_id = simulation.id
         AND spec.project_id = simulation.project_id
        WHERE simulation.id = NEW.simulation_id
          AND simulation.project_id = NEW.project_id
          AND spec.job_id = NEW.generated_by_job_id
          AND simulation.binding_contract_version = 'legacy-v1'
          AND simulation.campaign_id IS NULL
          AND simulation.opportunity_id IS NULL
          AND spec.campaign_id IS NULL
          AND spec.opportunity_id IS NULL
    ) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'prompt simulation result lineage is not exact'
        USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER prompt_simulation_results_new_contract_guard
BEFORE INSERT ON prompt_simulation_results
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_prompt_simulation_result();

ALTER TABLE artifact_finalize_outbox
    ADD COLUMN campaign_id uuid,
    ADD COLUMN opportunity_id uuid,
    ADD COLUMN destination_id uuid;
UPDATE artifact_finalize_outbox AS artifact
SET campaign_id = bundle.campaign_id,
    opportunity_id = bundle.opportunity_id,
    destination_id = bundle.destination_id
FROM prompt_bundles AS bundle
WHERE artifact.resource_kind = 'prompt_bundle'
  AND artifact.resource_id = bundle.id AND artifact.project_id = bundle.project_id;
UPDATE artifact_finalize_outbox AS artifact
SET campaign_id = receipt.campaign_id,
    opportunity_id = receipt.opportunity_id,
    destination_id = receipt.destination_id
FROM placement_export_receipts AS receipt
WHERE artifact.resource_kind = 'package_export'
  AND artifact.resource_id = receipt.id AND artifact.project_id = receipt.project_id;
UPDATE durable_jobs AS job SET campaign_id = artifact.campaign_id
FROM artifact_finalize_outbox AS artifact
WHERE job.id = artifact.job_id AND job.project_id = artifact.project_id
  AND artifact.campaign_id IS NOT NULL;
ALTER TABLE artifact_finalize_outbox
    ADD CONSTRAINT artifact_finalize_outbox_exact_job_fkey
        FOREIGN KEY (job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id) ON DELETE CASCADE;

ALTER TABLE durable_jobs
    ADD CONSTRAINT durable_jobs_exact_parent_campaign_fkey
        FOREIGN KEY (parent_job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id);
ALTER TABLE placement_package_versions
    ADD CONSTRAINT placement_package_versions_exact_generated_job_fkey
        FOREIGN KEY (generated_by_job_id, project_id, campaign_id)
        REFERENCES durable_jobs(id, project_id, campaign_id),
    ADD CONSTRAINT placement_package_versions_exact_generation_spec_fkey
        FOREIGN KEY (
            generated_by_job_id, project_id, campaign_id, opportunity_id,
            prompt_bundle_id
        ) REFERENCES generation_job_specs(
            job_id, project_id, campaign_id, opportunity_id, prompt_bundle_id
        );
ALTER TABLE measurement_collection_tasks
    ADD CONSTRAINT measurement_collection_tasks_exact_job_spec_fkey
        FOREIGN KEY (
            job_id, project_id, campaign_id, opportunity_id, submission_id,
            protocol_id
        ) REFERENCES measurement_job_specs(
            job_id, project_id, campaign_id, opportunity_id, submission_id,
            protocol_id
        );

CREATE FUNCTION geo_is_exact_legacy_simulation_generation_job(
    candidate_job_id uuid, scope_project_id uuid
) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1
        FROM durable_jobs AS job
        JOIN prompt_simulation_job_specs AS spec
          ON spec.job_id = job.id AND spec.project_id = job.project_id
         AND spec.campaign_id IS NOT DISTINCT FROM job.campaign_id
        JOIN prompt_simulations AS simulation
          ON simulation.id = spec.simulation_id
         AND simulation.project_id = spec.project_id
         AND simulation.campaign_id IS NOT DISTINCT FROM spec.campaign_id
         AND simulation.opportunity_id IS NOT DISTINCT FROM spec.opportunity_id
        WHERE job.id = candidate_job_id AND job.project_id = scope_project_id
          AND job.kind = 'prompt_simulation.generate' AND job.campaign_id IS NULL
          AND job.input_hash = simulation.input_hash
          AND spec.campaign_id IS NULL AND spec.opportunity_id IS NULL
          AND simulation.binding_contract_version = 'legacy-v1'
          AND simulation.campaign_id IS NULL
          AND simulation.opportunity_id IS NULL
          AND simulation.binding_id IS NULL
          AND simulation.binding_version IS NULL
    )
$$;

CREATE FUNCTION geo_is_exact_legacy_simulation_artifact_job(
    candidate_job_id uuid, scope_project_id uuid
) RETURNS boolean
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE related AS (
        SELECT job.id, ARRAY[job.id] AS path, 0 AS depth
        FROM durable_jobs AS job
        WHERE job.id = candidate_job_id AND job.project_id = scope_project_id
          AND job.kind = 'artifact.finalize' AND job.campaign_id IS NULL
          AND (
              job.parent_job_id IS NULL
              OR geo_is_exact_legacy_simulation_generation_job(
                  job.parent_job_id, job.project_id
              )
              OR EXISTS (
                  SELECT 1 FROM job_replay_requests AS own_replay
                  WHERE own_replay.project_id = job.project_id
                    AND own_replay.source_job_id = job.parent_job_id
                    AND own_replay.replay_job_id = job.id
              )
          )
        UNION ALL
        SELECT peer.id, current.path || peer.id, current.depth + 1
        FROM related AS current
        JOIN job_replay_requests AS replay
          ON replay.project_id = scope_project_id
         AND (replay.source_job_id = current.id OR replay.replay_job_id = current.id)
        JOIN durable_jobs AS replay_job
          ON replay_job.id = replay.replay_job_id
         AND replay_job.project_id = replay.project_id
         AND replay_job.parent_job_id = replay.source_job_id
         AND replay_job.kind = 'artifact.finalize'
         AND replay_job.campaign_id IS NULL
        JOIN durable_jobs AS peer
          ON peer.id = CASE
               WHEN replay.source_job_id = current.id THEN replay.replay_job_id
               ELSE replay.source_job_id
             END
         AND peer.project_id = replay.project_id
         AND peer.kind = 'artifact.finalize'
         AND peer.campaign_id IS NULL
        WHERE current.depth < 64 AND NOT peer.id = ANY(current.path)
    )
    SELECT EXISTS (
        SELECT 1
        FROM durable_jobs AS job
        JOIN related AS owner ON true
        JOIN artifact_finalize_outbox AS artifact
          ON artifact.job_id = owner.id AND artifact.project_id = job.project_id
        JOIN prompt_simulation_results AS result
          ON result.simulation_id = artifact.resource_id
         AND result.project_id = artifact.project_id
        WHERE job.id = candidate_job_id AND job.project_id = scope_project_id
          AND job.kind = 'artifact.finalize' AND job.campaign_id IS NULL
          AND artifact.resource_kind = 'prompt_simulation'
          AND artifact.campaign_id IS NULL
          AND artifact.opportunity_id IS NULL
          AND artifact.destination_id IS NULL
          AND artifact.content_hash = result.manifest_hash
          AND artifact.storage_key = result.storage_key
          AND result.lineage_contract_version = 'legacy-v1'
          AND result.campaign_id IS NULL AND result.opportunity_id IS NULL
          AND geo_is_exact_legacy_simulation_generation_job(
              result.generated_by_job_id, result.project_id
          )
    )
$$;

CREATE FUNCTION geo_assert_new_durable_job_campaign() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    parent_campaign_id uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        NEW.id, NEW.project_id, NEW.kind, NEW.campaign_id, NEW.parent_job_id
    ) IS DISTINCT FROM (
        OLD.id, OLD.project_id, OLD.kind, OLD.campaign_id, OLD.parent_job_id
    ) THEN
        RAISE EXCEPTION 'durable job identity and Campaign ancestry are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.kind IN (
        'evidence_pack.build', 'placement.generate', 'publication.verify',
        'placement.measure', 'prompt_simulation.generate', 'artifact.finalize'
    ) AND NEW.campaign_id IS NULL THEN
        RAISE EXCEPTION 'Placement jobs require an explicit Campaign context'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.parent_job_id IS NOT NULL THEN
        SELECT campaign_id INTO parent_campaign_id FROM durable_jobs
        WHERE id = NEW.parent_job_id AND project_id = NEW.project_id;
        IF parent_campaign_id IS DISTINCT FROM NEW.campaign_id THEN
            RAISE EXCEPTION 'replayed jobs must preserve source Campaign context'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_require_durable_job_campaign_spec() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    valid_context boolean := false;
BEGIN
    IF NEW.kind = 'evidence_pack.build' THEN
        SELECT EXISTS(SELECT 1 FROM evidence_pack_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'placement.generate' THEN
        SELECT EXISTS(SELECT 1 FROM generation_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'publication.verify' THEN
        SELECT EXISTS(SELECT 1 FROM verification_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'placement.measure' THEN
        SELECT EXISTS(SELECT 1 FROM measurement_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'prompt_simulation.generate' THEN
        SELECT EXISTS(SELECT 1 FROM prompt_simulation_job_specs
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSIF NEW.kind = 'artifact.finalize' THEN
        SELECT EXISTS(SELECT 1 FROM artifact_finalize_outbox
          WHERE job_id = NEW.id AND project_id = NEW.project_id
            AND campaign_id = NEW.campaign_id) INTO valid_context;
    ELSE
        RETURN NULL;
    END IF;
    IF NOT valid_context THEN
        RAISE EXCEPTION 'Placement job is missing its exact Campaign-scoped specification'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER durable_job_campaign_guard
BEFORE INSERT OR UPDATE OF id, project_id, campaign_id, kind, parent_job_id ON durable_jobs
FOR EACH ROW EXECUTE FUNCTION geo_assert_new_durable_job_campaign();
CREATE CONSTRAINT TRIGGER durable_job_campaign_spec_guard
AFTER INSERT ON durable_jobs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_durable_job_campaign_spec();

CREATE FUNCTION geo_assert_artifact_campaign_context() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.campaign_id IS NULL OR NEW.opportunity_id IS NULL OR NEW.destination_id IS NULL THEN
        RAISE EXCEPTION 'new placement artifacts require exact Campaign ancestry'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.resource_kind = 'prompt_bundle' AND NOT EXISTS (
        SELECT 1 FROM prompt_bundles WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'Prompt Bundle artifact context mismatch' USING ERRCODE = '23514';
    ELSIF NEW.resource_kind = 'package_export' AND NOT EXISTS (
        SELECT 1 FROM placement_export_receipts WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
    ) THEN
        RAISE EXCEPTION 'Package export artifact context mismatch' USING ERRCODE = '23514';
    ELSIF NEW.resource_kind = 'prompt_simulation' AND NOT EXISTS (
        SELECT 1 FROM prompt_simulations WHERE id = NEW.resource_id
          AND project_id = NEW.project_id AND campaign_id = NEW.campaign_id
          AND opportunity_id = NEW.opportunity_id AND destination_id = NEW.destination_id
          AND binding_contract_version = 'opportunity-binding-v2'
    ) THEN
        RAISE EXCEPTION 'Prompt simulation artifact context mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER artifact_finalize_campaign_guard
BEFORE INSERT OR UPDATE OF
    job_id, project_id, resource_kind, resource_id, campaign_id,
    opportunity_id, destination_id
ON artifact_finalize_outbox
FOR EACH ROW EXECUTE FUNCTION geo_assert_artifact_campaign_context();

CREATE FUNCTION geo_reject_placement_job_spec_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Placement job specifications are immutable'
        USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_require_job_deleted_with_spec() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM durable_jobs AS job
        WHERE job.id = OLD.job_id AND job.project_id = OLD.project_id
    ) THEN
        RAISE EXCEPTION 'delete the durable job instead of its Placement specification'
            USING ERRCODE = '55000';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_protect_artifact_finalize_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (
        NEW.project_id, NEW.resource_kind, NEW.resource_id, NEW.campaign_id,
        NEW.opportunity_id, NEW.destination_id, NEW.pending_uri, NEW.storage_key,
        NEW.content_hash
    ) IS DISTINCT FROM (
        OLD.project_id, OLD.resource_kind, OLD.resource_id, OLD.campaign_id,
        OLD.opportunity_id, OLD.destination_id, OLD.pending_uri, OLD.storage_key,
        OLD.content_hash
    ) THEN
        RAISE EXCEPTION 'artifact finalization resource ancestry is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.job_id IS DISTINCT FROM OLD.job_id AND NOT (
        OLD.status = 'failed' AND NEW.status = 'pending'
        AND EXISTS (
            SELECT 1 FROM durable_jobs AS replay
            WHERE replay.id = NEW.job_id AND replay.project_id = NEW.project_id
              AND replay.parent_job_id = OLD.job_id
              AND replay.kind = 'artifact.finalize'
              AND replay.campaign_id IS NOT DISTINCT FROM NEW.campaign_id
        )
    ) THEN
        RAISE EXCEPTION 'artifact finalization job may only move to an exact replay'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER evidence_pack_job_specs_immutable
BEFORE UPDATE ON evidence_pack_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_reject_placement_job_spec_update();
CREATE CONSTRAINT TRIGGER evidence_pack_job_specs_delete_guard
AFTER DELETE ON evidence_pack_job_specs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();
CREATE TRIGGER generation_job_specs_immutable
BEFORE UPDATE ON generation_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_reject_placement_job_spec_update();
CREATE CONSTRAINT TRIGGER generation_job_specs_delete_guard
AFTER DELETE ON generation_job_specs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();
CREATE TRIGGER verification_job_specs_immutable
BEFORE UPDATE ON verification_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_reject_placement_job_spec_update();
CREATE CONSTRAINT TRIGGER verification_job_specs_delete_guard
AFTER DELETE ON verification_job_specs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();
CREATE TRIGGER measurement_job_specs_immutable
BEFORE UPDATE ON measurement_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_reject_placement_job_spec_update();
CREATE CONSTRAINT TRIGGER measurement_job_specs_delete_guard
AFTER DELETE ON measurement_job_specs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();
CREATE TRIGGER prompt_simulation_job_specs_immutable
BEFORE UPDATE ON prompt_simulation_job_specs
FOR EACH ROW EXECUTE FUNCTION geo_reject_placement_job_spec_update();
CREATE CONSTRAINT TRIGGER prompt_simulation_job_specs_delete_guard
AFTER DELETE ON prompt_simulation_job_specs DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();
CREATE TRIGGER artifact_finalize_outbox_identity_immutable
BEFORE UPDATE OF
    job_id, project_id, resource_kind, resource_id, campaign_id,
    opportunity_id, destination_id, pending_uri, storage_key, content_hash
ON artifact_finalize_outbox
FOR EACH ROW EXECUTE FUNCTION geo_protect_artifact_finalize_identity();
CREATE CONSTRAINT TRIGGER artifact_finalize_outbox_delete_guard
AFTER DELETE ON artifact_finalize_outbox DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_require_job_deleted_with_spec();

CREATE FUNCTION geo_reject_campaign_lineage_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    column_name text;
BEGIN
    FOREACH column_name IN ARRAY TG_ARGV LOOP
        IF to_jsonb(NEW) -> column_name IS DISTINCT FROM to_jsonb(OLD) -> column_name THEN
            RAISE EXCEPTION 'Campaign ancestry is immutable; create a new version or event'
                USING ERRCODE = '55000';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;

CREATE TRIGGER placement_opportunities_campaign_lineage_immutable
BEFORE UPDATE OF id, project_id, campaign_id, destination_id
ON placement_opportunities
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'campaign_id', 'destination_id'
);
CREATE TRIGGER placement_briefs_campaign_lineage_immutable
BEFORE UPDATE OF id, project_id, opportunity_id, campaign_id, destination_id
ON placement_briefs
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'opportunity_id', 'campaign_id', 'destination_id'
);
CREATE TRIGGER evidence_pack_attempts_campaign_lineage_immutable
BEFORE UPDATE OF
    id, project_id, brief_version_id, campaign_id, opportunity_id, destination_id
ON evidence_pack_attempts
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'brief_version_id', 'campaign_id', 'opportunity_id',
    'destination_id'
);
CREATE TRIGGER placement_packages_campaign_lineage_immutable
BEFORE UPDATE OF id, project_id, opportunity_id, campaign_id, destination_id
ON placement_packages
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'opportunity_id', 'campaign_id', 'destination_id'
);
CREATE TRIGGER placement_package_versions_campaign_lineage_immutable
BEFORE UPDATE OF
    id, project_id, package_id, prompt_bundle_id, campaign_id, opportunity_id,
    destination_id, base_version_id, generated_by_job_id
ON placement_package_versions
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'package_id', 'prompt_bundle_id', 'campaign_id',
    'opportunity_id', 'destination_id', 'base_version_id', 'generated_by_job_id'
);
CREATE TRIGGER publication_requests_campaign_lineage_immutable
BEFORE UPDATE OF
    id, project_id, package_version_id, destination_id, campaign_id, opportunity_id
ON publication_requests
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'package_version_id', 'destination_id', 'campaign_id',
    'opportunity_id'
);
CREATE TRIGGER publication_submissions_campaign_lineage_immutable
BEFORE UPDATE OF
    id, project_id, publication_request_id, campaign_id, opportunity_id, destination_id
ON publication_submissions
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'publication_request_id', 'campaign_id',
    'opportunity_id', 'destination_id'
);
CREATE TRIGGER placement_measurements_campaign_lineage_immutable
BEFORE UPDATE OF
    id, project_id, submission_id, monitoring_query_id, campaign_id,
    opportunity_id, destination_id
ON placement_measurements
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'submission_id', 'monitoring_query_id', 'campaign_id',
    'opportunity_id', 'destination_id'
);
CREATE TRIGGER measurement_collection_tasks_campaign_lineage_immutable
BEFORE UPDATE OF
    id, project_id, job_id, submission_id, protocol_id, campaign_id,
    opportunity_id, destination_id
ON measurement_collection_tasks
FOR EACH ROW EXECUTE FUNCTION geo_reject_campaign_lineage_update(
    'id', 'project_id', 'job_id', 'submission_id', 'protocol_id', 'campaign_id',
    'opportunity_id', 'destination_id'
);

-- Restore immutable guards after migration-owned backfill.
CREATE TRIGGER placement_brief_versions_immutable
BEFORE UPDATE OR DELETE ON placement_brief_versions
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER evidence_pack_attempt_terminal_immutable
BEFORE UPDATE OR DELETE ON evidence_pack_attempts
FOR EACH ROW EXECUTE FUNCTION geo_protect_evidence_pack_attempt();
CREATE TRIGGER prompt_bundles_immutable
BEFORE UPDATE OR DELETE ON prompt_bundles
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER placement_export_receipts_immutable
BEFORE UPDATE OR DELETE ON placement_export_receipts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_simulation_scope_guard
BEFORE INSERT OR UPDATE ON prompt_simulations
FOR EACH ROW EXECUTE FUNCTION geo_assert_prompt_simulation_scope();
CREATE TRIGGER prompt_simulations_immutable
BEFORE UPDATE OR DELETE ON prompt_simulations
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER prompt_simulation_results_immutable
BEFORE UPDATE OR DELETE ON prompt_simulation_results
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

-- Query and FK-supporting indexes for the new ancestry columns.
CREATE INDEX placement_briefs_campaign_idx
ON placement_briefs (project_id, campaign_id, opportunity_id);
CREATE INDEX placement_briefs_opportunity_fk_idx
ON placement_briefs (opportunity_id, project_id, campaign_id, destination_id);
CREATE INDEX placement_brief_versions_campaign_idx
ON placement_brief_versions (project_id, campaign_id, opportunity_id, created_at DESC);
CREATE INDEX placement_brief_versions_brief_fk_idx
ON placement_brief_versions (
    brief_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX placement_brief_versions_base_fk_idx
ON placement_brief_versions (
    base_version_id, project_id, campaign_id, opportunity_id, destination_id, brief_id
) WHERE base_version_id IS NOT NULL;
CREATE INDEX evidence_pack_attempts_campaign_idx
ON evidence_pack_attempts (project_id, campaign_id, opportunity_id, created_at DESC);
CREATE INDEX evidence_pack_attempts_brief_version_fk_idx
ON evidence_pack_attempts (
    brief_version_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX evidence_pack_attempts_superseded_fk_idx
ON evidence_pack_attempts (
    superseded_by_attempt_id, project_id, campaign_id, opportunity_id,
    destination_id, brief_version_id
) WHERE superseded_by_attempt_id IS NOT NULL;
CREATE INDEX prompt_bundles_campaign_idx
ON prompt_bundles (project_id, campaign_id, opportunity_id, created_at DESC);
CREATE INDEX prompt_bundles_brief_version_fk_idx
ON prompt_bundles (
    brief_version_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX prompt_bundles_evidence_attempt_fk_idx
ON prompt_bundles (
    evidence_pack_attempt_id, project_id, campaign_id, opportunity_id,
    destination_id, brief_version_id
);
CREATE INDEX prompt_bundles_release_fk_idx
ON prompt_bundles (
    template_release_id, project_id, template_skill_version_id,
    template_release_number, template_release_hash
);
CREATE INDEX prompt_bundles_binding_fk_idx
ON prompt_bundles (
    binding_id, project_id, campaign_id, opportunity_id, destination_id,
    binding_version, template_release_id, template_skill_version_id,
    template_release_number, template_release_hash
) WHERE binding_id IS NOT NULL;
CREATE INDEX placement_packages_campaign_idx
ON placement_packages (project_id, campaign_id, opportunity_id);
CREATE INDEX placement_packages_opportunity_fk_idx
ON placement_packages (opportunity_id, project_id, campaign_id, destination_id);
CREATE INDEX placement_package_versions_campaign_idx
ON placement_package_versions (project_id, campaign_id, opportunity_id, created_at DESC);
CREATE INDEX placement_package_versions_package_fk_idx
ON placement_package_versions (
    package_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX placement_package_versions_bundle_fk_idx
ON placement_package_versions (
    prompt_bundle_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX placement_package_versions_generated_job_fk_idx
ON placement_package_versions (generated_by_job_id, project_id, campaign_id)
WHERE generated_by_job_id IS NOT NULL;
CREATE INDEX placement_package_versions_generation_spec_fk_idx
ON placement_package_versions (
    generated_by_job_id, project_id, campaign_id, opportunity_id, prompt_bundle_id
) WHERE generated_by_job_id IS NOT NULL;
CREATE INDEX placement_package_versions_base_fk_idx
ON placement_package_versions (
    base_version_id, project_id, campaign_id, opportunity_id, destination_id, package_id
) WHERE base_version_id IS NOT NULL;
CREATE INDEX publication_requests_campaign_idx
ON publication_requests (project_id, campaign_id, opportunity_id, requested_at DESC);
CREATE INDEX publication_requests_package_version_fk_idx
ON publication_requests (
    package_version_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX publication_submissions_campaign_idx
ON publication_submissions (project_id, campaign_id, opportunity_id, created_at DESC);
CREATE INDEX publication_submissions_request_fk_idx
ON publication_submissions (
    publication_request_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX placement_measurements_campaign_idx
ON placement_measurements (project_id, campaign_id, opportunity_id, measured_at DESC);
CREATE INDEX placement_measurements_submission_fk_idx
ON placement_measurements (
    submission_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX placement_measurements_campaign_query_idx
ON placement_measurements (project_id, campaign_id, monitoring_query_id, measured_at DESC);
CREATE INDEX placement_measurements_campaign_query_fk_idx
ON placement_measurements (campaign_id, monitoring_query_id, project_id);
CREATE INDEX measurement_collection_tasks_campaign_idx
ON measurement_collection_tasks (project_id, campaign_id, opportunity_id, scheduled_for);
CREATE INDEX measurement_collection_tasks_submission_fk_idx
ON measurement_collection_tasks (
    submission_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX measurement_collection_tasks_protocol_fk_idx
ON measurement_collection_tasks (protocol_id, campaign_id, project_id);
CREATE INDEX measurement_collection_tasks_job_spec_fk_idx
ON measurement_collection_tasks (
    job_id, project_id, campaign_id, opportunity_id, submission_id, protocol_id
);
CREATE INDEX durable_jobs_campaign_activity_idx
ON durable_jobs (project_id, campaign_id, updated_at DESC, id DESC)
WHERE campaign_id IS NOT NULL;
CREATE INDEX durable_jobs_campaign_fk_idx
ON durable_jobs (campaign_id, project_id)
WHERE campaign_id IS NOT NULL;
CREATE INDEX durable_jobs_parent_campaign_fk_idx
ON durable_jobs (parent_job_id, project_id, campaign_id)
WHERE parent_job_id IS NOT NULL;
CREATE INDEX evidence_pack_job_specs_campaign_idx
ON evidence_pack_job_specs (project_id, campaign_id, opportunity_id, job_id);
CREATE INDEX evidence_pack_job_specs_job_fk_idx
ON evidence_pack_job_specs (job_id, project_id, campaign_id);
CREATE INDEX evidence_pack_job_specs_attempt_fk_idx
ON evidence_pack_job_specs (
    evidence_pack_attempt_id, project_id, campaign_id, opportunity_id,
    brief_version_id
);
CREATE INDEX generation_job_specs_campaign_idx
ON generation_job_specs (project_id, campaign_id, opportunity_id, job_id);
CREATE INDEX generation_job_specs_job_fk_idx
ON generation_job_specs (job_id, project_id, campaign_id);
CREATE INDEX generation_job_specs_bundle_fk_idx
ON generation_job_specs (prompt_bundle_id, project_id, campaign_id, opportunity_id);
CREATE INDEX verification_job_specs_campaign_idx
ON verification_job_specs (project_id, campaign_id, opportunity_id, job_id);
CREATE INDEX verification_job_specs_job_fk_idx
ON verification_job_specs (job_id, project_id, campaign_id);
CREATE INDEX verification_job_specs_submission_fk_idx
ON verification_job_specs (submission_id, project_id, campaign_id, opportunity_id);
CREATE INDEX measurement_job_specs_campaign_idx
ON measurement_job_specs (project_id, campaign_id, opportunity_id, job_id);
CREATE INDEX measurement_job_specs_job_fk_idx
ON measurement_job_specs (job_id, project_id, campaign_id);
CREATE INDEX measurement_job_specs_submission_fk_idx
ON measurement_job_specs (submission_id, project_id, campaign_id, opportunity_id);
CREATE INDEX measurement_job_specs_protocol_fk_idx
ON measurement_job_specs (protocol_id, campaign_id, project_id);
CREATE INDEX prompt_simulation_job_specs_campaign_idx
ON prompt_simulation_job_specs (project_id, campaign_id, opportunity_id, job_id);
CREATE INDEX prompt_simulation_job_specs_job_fk_idx
ON prompt_simulation_job_specs (job_id, project_id, campaign_id);
CREATE INDEX prompt_simulation_job_specs_simulation_fk_idx
ON prompt_simulation_job_specs (simulation_id, project_id, campaign_id, opportunity_id);
CREATE INDEX prompt_simulation_results_simulation_fk_idx
ON prompt_simulation_results (simulation_id, project_id, campaign_id, opportunity_id);
CREATE INDEX prompt_simulation_results_job_spec_fk_idx
ON prompt_simulation_results (
    generated_by_job_id, project_id, campaign_id, opportunity_id, simulation_id
);
CREATE INDEX artifact_finalize_outbox_campaign_idx
ON artifact_finalize_outbox (project_id, campaign_id, opportunity_id, created_at DESC)
WHERE campaign_id IS NOT NULL;
CREATE INDEX artifact_finalize_outbox_job_campaign_fk_idx
ON artifact_finalize_outbox (job_id, project_id, campaign_id);
CREATE INDEX prompt_simulations_opportunity_fk_idx
ON prompt_simulations (opportunity_id, project_id, campaign_id, destination_id)
WHERE opportunity_id IS NOT NULL;
CREATE INDEX prompt_simulations_release_fk_idx
ON prompt_simulations (
    template_release_id, project_id, template_skill_version_id,
    template_release_number, template_release_hash
);
CREATE INDEX prompt_simulations_binding_fk_idx
ON prompt_simulations (
    binding_id, project_id, campaign_id, opportunity_id, destination_id,
    binding_version, template_release_id, template_skill_version_id,
    template_release_number, template_release_hash
) WHERE binding_id IS NOT NULL;
CREATE INDEX placement_export_receipts_version_fk_idx
ON placement_export_receipts (
    package_version_id, project_id, campaign_id, opportunity_id, destination_id
);
CREATE INDEX generation_template_release_states_release_fk_idx
ON generation_template_release_states (
    template_release_id, project_id, skill_version_id, release_number, release_hash
);
CREATE INDEX generation_template_release_states_previous_fk_idx
ON generation_template_release_states (
    previous_state_id, project_id, template_release_id
) WHERE previous_state_id IS NOT NULL;
CREATE INDEX generation_template_release_states_actor_fk_idx
ON generation_template_release_states (changed_by)
WHERE changed_by IS NOT NULL;
CREATE INDEX opportunity_prompt_bindings_opportunity_fk_idx
ON opportunity_prompt_release_bindings (
    opportunity_id, project_id, campaign_id, destination_id
);
CREATE INDEX opportunity_prompt_bindings_release_fk_idx
ON opportunity_prompt_release_bindings (
    template_release_id, project_id, skill_version_id, release_number, release_hash
) WHERE template_release_id IS NOT NULL;
CREATE INDEX opportunity_prompt_bindings_previous_fk_idx
ON opportunity_prompt_release_bindings (
    previous_binding_id, project_id, campaign_id, opportunity_id, destination_id
) WHERE previous_binding_id IS NOT NULL;
CREATE INDEX opportunity_prompt_bindings_actor_fk_idx
ON opportunity_prompt_release_bindings (changed_by)
WHERE changed_by IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM durable_jobs AS job
        WHERE job.kind IN (
            'evidence_pack.build', 'placement.generate', 'publication.verify',
            'placement.measure'
        )
          AND (
              job.campaign_id IS NULL
              OR (job.kind = 'evidence_pack.build' AND NOT EXISTS (
                  SELECT 1 FROM evidence_pack_job_specs AS spec
                  WHERE spec.job_id = job.id AND spec.project_id = job.project_id
                    AND spec.campaign_id = job.campaign_id
              ))
              OR (job.kind = 'placement.generate' AND NOT EXISTS (
                  SELECT 1 FROM generation_job_specs AS spec
                  WHERE spec.job_id = job.id AND spec.project_id = job.project_id
                    AND spec.campaign_id = job.campaign_id
              ))
              OR (job.kind = 'publication.verify' AND NOT EXISTS (
                  SELECT 1 FROM verification_job_specs AS spec
                  WHERE spec.job_id = job.id AND spec.project_id = job.project_id
                    AND spec.campaign_id = job.campaign_id
              ))
              OR (job.kind = 'placement.measure' AND NOT EXISTS (
                  SELECT 1 FROM measurement_job_specs AS spec
                  WHERE spec.job_id = job.id AND spec.project_id = job.project_id
                    AND spec.campaign_id = job.campaign_id
              ))
          )
    ) OR EXISTS (
        SELECT 1 FROM durable_jobs AS job
        WHERE job.kind = 'prompt_simulation.generate'
          AND NOT EXISTS (
              SELECT 1
              FROM prompt_simulation_job_specs AS spec
              JOIN prompt_simulations AS simulation
                ON simulation.id = spec.simulation_id
               AND simulation.project_id = spec.project_id
              WHERE spec.job_id = job.id AND spec.project_id = job.project_id
                AND spec.campaign_id IS NOT DISTINCT FROM job.campaign_id
                AND (
                    (job.campaign_id IS NULL
                        AND spec.opportunity_id IS NULL
                        AND simulation.binding_contract_version = 'legacy-v1')
                    OR (job.campaign_id IS NOT NULL
                        AND spec.opportunity_id IS NOT NULL
                        AND simulation.binding_contract_version = 'opportunity-binding-v2')
                )
          )
    ) OR EXISTS (
        SELECT 1 FROM durable_jobs AS job
        WHERE job.kind = 'artifact.finalize'
          AND NOT (
              (job.campaign_id IS NULL
                  AND geo_is_exact_legacy_simulation_artifact_job(job.id, job.project_id))
              OR (job.campaign_id IS NOT NULL AND EXISTS (
                  SELECT 1 FROM artifact_finalize_outbox AS artifact
                  WHERE artifact.job_id = job.id AND artifact.project_id = job.project_id
                    AND artifact.campaign_id = job.campaign_id
              ))
          )
    ) THEN
        RAISE EXCEPTION 'legacy Placement jobs contain incomplete Campaign specifications'
            USING ERRCODE = '23514';
    END IF;
END $$;

ALTER TABLE generation_template_release_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_template_release_states FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON generation_template_release_states
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));
ALTER TABLE opportunity_prompt_release_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE opportunity_prompt_release_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON opportunity_prompt_release_bindings
    USING (project_id = ANY(geo_current_project_ids()))
    WITH CHECK (project_id = ANY(geo_current_project_ids()));

REVOKE ALL ON generation_template_release_states,
    opportunity_prompt_release_bindings
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
REVOKE ALL ON current_generation_template_release_states,
    current_opportunity_prompt_release_bindings
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT, INSERT ON generation_template_release_states,
    opportunity_prompt_release_bindings TO geo_app;
GRANT SELECT ON generation_template_release_states,
    opportunity_prompt_release_bindings TO geo_worker, geo_readonly;
GRANT SELECT ON current_generation_template_release_states,
    current_opportunity_prompt_release_bindings TO geo_app, geo_worker, geo_readonly;

REVOKE ALL ON FUNCTION geo_assert_release_state_append(),
    geo_protect_append_only_release_state(), geo_require_release_initial_state(),
    geo_assert_opportunity_prompt_binding_append(),
    geo_protect_opportunity_prompt_binding(), geo_require_opportunity_initial_binding(),
    geo_assert_prompt_bundle_binding(), geo_assert_new_durable_job_campaign(),
    geo_require_durable_job_campaign_spec(), geo_assert_artifact_campaign_context(),
    geo_is_exact_legacy_simulation_generation_job(uuid, uuid),
    geo_is_exact_legacy_simulation_artifact_job(uuid, uuid),
    geo_reject_placement_job_spec_update(), geo_require_job_deleted_with_spec(),
    geo_protect_artifact_finalize_identity(),
    geo_reject_campaign_lineage_update(), geo_assert_new_prompt_simulation_result()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_assert_release_state_append(),
    geo_protect_append_only_release_state(), geo_require_release_initial_state(),
    geo_assert_opportunity_prompt_binding_append(),
    geo_protect_opportunity_prompt_binding(), geo_require_opportunity_initial_binding(),
    geo_assert_prompt_bundle_binding(), geo_assert_new_durable_job_campaign(),
    geo_require_durable_job_campaign_spec(), geo_assert_artifact_campaign_context(),
    geo_is_exact_legacy_simulation_generation_job(uuid, uuid),
    geo_is_exact_legacy_simulation_artifact_job(uuid, uuid),
    geo_reject_placement_job_spec_update(), geo_require_job_deleted_with_spec(),
    geo_protect_artifact_finalize_identity(),
    geo_reject_campaign_lineage_update(), geo_assert_new_prompt_simulation_result()
TO geo_app, geo_worker;
