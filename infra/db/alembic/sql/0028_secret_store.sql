CREATE TABLE secret_master_key_versions (
    master_key_version integer PRIMARY KEY CHECK (master_key_version > 0),
    algorithm text NOT NULL CHECK (algorithm = 'AES-256-GCM'),
    status text NOT NULL CHECK (
        status IN ('encrypt_decrypt', 'decrypt_only', 'retired')
    ),
    canary_nonce bytea NOT NULL CHECK (octet_length(canary_nonce) = 12),
    canary_ciphertext bytea NOT NULL CHECK (octet_length(canary_ciphertext) >= 17),
    created_at timestamptz NOT NULL,
    activated_at timestamptz NOT NULL,
    retired_at timestamptz,
    CONSTRAINT secret_master_key_versions_status_shape CHECK (
        (status IN ('encrypt_decrypt', 'decrypt_only') AND retired_at IS NULL)
        OR (status = 'retired' AND retired_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX secret_master_key_versions_active_key
ON secret_master_key_versions ((status))
WHERE status = 'encrypt_decrypt';

CREATE TABLE secret_references (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    purpose text NOT NULL CHECK (purpose ~ '^[a-z][a-z0-9_.-]{0,127}$'),
    aggregate_version integer NOT NULL CHECK (aggregate_version > 0),
    current_version integer CHECK (current_version > 0),
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT secret_references_time_order CHECK (updated_at >= created_at),
    CONSTRAINT secret_references_scope_key UNIQUE (id, project_id, purpose),
    CONSTRAINT secret_references_current_key UNIQUE (
        id, project_id, purpose, current_version
    )
);

CREATE TABLE secret_versions (
    reference_id uuid NOT NULL,
    project_id uuid NOT NULL,
    purpose text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) >= 17),
    data_nonce bytea NOT NULL CHECK (octet_length(data_nonce) = 12),
    wrapped_data_key bytea NOT NULL CHECK (octet_length(wrapped_data_key) = 48),
    wrap_nonce bytea NOT NULL CHECK (octet_length(wrap_nonce) = 12),
    master_key_version integer NOT NULL REFERENCES secret_master_key_versions(
        master_key_version
    ),
    algorithm text NOT NULL CHECK (algorithm = 'AES-256-GCM'),
    created_at timestamptz NOT NULL,
    status text NOT NULL CHECK (
        status IN ('pending', 'active', 'superseded', 'revoked')
    ),
    created_by uuid NOT NULL REFERENCES identities(id),
    verified_by uuid REFERENCES identities(id),
    verified_at timestamptz,
    activated_by uuid REFERENCES identities(id),
    activated_at timestamptz,
    revoked_by uuid REFERENCES identities(id),
    revoked_at timestamptz,
    PRIMARY KEY (reference_id, version),
    CONSTRAINT secret_versions_scope_key UNIQUE (
        reference_id, project_id, purpose, version
    ),
    CONSTRAINT secret_versions_reference_fkey FOREIGN KEY (
        reference_id, project_id, purpose
    ) REFERENCES secret_references(id, project_id, purpose) ON DELETE CASCADE,
    CONSTRAINT secret_versions_verification_pair CHECK (
        (verified_by IS NULL) = (verified_at IS NULL)
    ),
    CONSTRAINT secret_versions_activation_pair CHECK (
        (activated_by IS NULL) = (activated_at IS NULL)
    ),
    CONSTRAINT secret_versions_revocation_pair CHECK (
        (revoked_by IS NULL) = (revoked_at IS NULL)
    ),
    CONSTRAINT secret_versions_creator_approval_separation CHECK (
        activated_by IS NULL OR activated_by <> created_by
    ),
    CONSTRAINT secret_versions_status_shape CHECK (
        (status = 'pending' AND activated_at IS NULL AND revoked_at IS NULL)
        OR (status IN ('active', 'superseded')
            AND verified_at IS NOT NULL AND activated_at IS NOT NULL
            AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX secret_versions_one_active
ON secret_versions(reference_id)
WHERE status = 'active';
CREATE UNIQUE INDEX secret_versions_one_pending
ON secret_versions(reference_id)
WHERE status = 'pending';

ALTER TABLE secret_references
ADD CONSTRAINT secret_references_current_fkey FOREIGN KEY (
    id, project_id, purpose, current_version
) REFERENCES secret_versions(reference_id, project_id, purpose, version)
DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE secret_command_receipts (
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    idempotency_key_hash text NOT NULL CHECK (
        idempotency_key_hash ~ '^[0-9a-f]{64}$'
    ),
    operation text NOT NULL CHECK (
        operation IN (
            'create', 'verify', 'rotate_stage', 'activate', 'revoke', 'resolve', 'rewrap'
        )
    ),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    reference_id uuid NOT NULL,
    purpose text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    aggregate_version integer NOT NULL CHECK (aggregate_version > 0),
    status text NOT NULL CHECK (
        status IN ('pending', 'active', 'superseded', 'revoked')
    ),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, idempotency_key_hash),
    CONSTRAINT secret_command_receipts_version_fkey FOREIGN KEY (
        reference_id, project_id, purpose, version
    ) REFERENCES secret_versions(reference_id, project_id, purpose, version)
);

CREATE TABLE secret_audit_events (
    id uuid PRIMARY KEY,
    reference_id uuid NOT NULL,
    project_id uuid NOT NULL,
    purpose text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    action text NOT NULL CHECK (action IN (
        'reference_created', 'version_staged', 'version_verified',
        'version_activated', 'version_resolved', 'version_revoked',
        'version_rewrapped'
    )),
    actor_id uuid NOT NULL REFERENCES identities(id),
    occurred_at timestamptz NOT NULL,
    master_key_version integer NOT NULL REFERENCES secret_master_key_versions(
        master_key_version
    ),
    envelope_fingerprint text NOT NULL CHECK (
        envelope_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT secret_audit_events_version_fkey FOREIGN KEY (
        reference_id, project_id, purpose, version
    ) REFERENCES secret_versions(reference_id, project_id, purpose, version),
    CONSTRAINT secret_audit_events_project_key UNIQUE (id, project_id)
);

CREATE FUNCTION geo_assert_secret_master_key_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Secret Store master key versions are immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.master_key_version <> NEW.master_key_version
       OR OLD.algorithm <> NEW.algorithm
       OR OLD.canary_nonce <> NEW.canary_nonce
       OR OLD.canary_ciphertext <> NEW.canary_ciphertext
       OR OLD.created_at <> NEW.created_at
       OR OLD.activated_at <> NEW.activated_at
       OR NOT (
           (OLD.status = 'encrypt_decrypt' AND NEW.status = 'decrypt_only'
                AND NEW.retired_at IS NULL)
           OR (OLD.status = 'decrypt_only' AND NEW.status = 'retired'
                AND NEW.retired_at IS NOT NULL)
       ) THEN
        RAISE EXCEPTION 'Secret Store master key transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'retired' AND EXISTS (
        SELECT 1 FROM secret_versions
        WHERE master_key_version = NEW.master_key_version
    ) THEN
        RAISE EXCEPTION 'Secret Store master key is still referenced by ciphertext'
            USING ERRCODE = '23503';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_sync_secret_master_key_version(
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
AS $$
DECLARE
    existing record;
    latest_version integer;
BEGIN
    LOCK TABLE secret_master_key_versions IN SHARE ROW EXCLUSIVE MODE;
    SELECT * INTO existing
    FROM secret_master_key_versions
    WHERE master_key_version = requested_version;
    IF FOUND THEN
        IF existing.algorithm <> requested_algorithm
           OR existing.canary_nonce <> requested_nonce
           OR existing.canary_ciphertext <> requested_ciphertext
           OR existing.status <> requested_status THEN
            RAISE EXCEPTION 'Secret Store master key canary or status conflicts with storage'
                USING ERRCODE = '23514';
        END IF;
        RETURN;
    END IF;
    IF requested_status NOT IN ('encrypt_decrypt', 'decrypt_only')
       OR requested_algorithm <> 'AES-256-GCM' THEN
        RAISE EXCEPTION 'Secret Store master key registration is invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT max(master_key_version) INTO latest_version
    FROM secret_master_key_versions;
    IF requested_version <= coalesce(latest_version, 0) THEN
        RAISE EXCEPTION 'Secret Store master key versions must increase'
            USING ERRCODE = '23514';
    END IF;
    IF requested_status = 'decrypt_only' AND EXISTS (
        SELECT 1 FROM secret_master_key_versions
        WHERE status = 'encrypt_decrypt'
    ) THEN
        RAISE EXCEPTION 'Historical Secret Store keys must precede the active key'
            USING ERRCODE = '23514';
    END IF;
    IF requested_status = 'encrypt_decrypt' THEN
        UPDATE secret_master_key_versions
        SET status = 'decrypt_only'
        WHERE status = 'encrypt_decrypt';
    END IF;
    INSERT INTO secret_master_key_versions(
        master_key_version, algorithm, status, canary_nonce,
        canary_ciphertext, created_at, activated_at
    ) VALUES (
        requested_version, requested_algorithm, requested_status, requested_nonce,
        requested_ciphertext, requested_at, requested_at
    );
END;
$$;

CREATE FUNCTION geo_retire_secret_master_key_version(
    requested_version integer,
    requested_at timestamptz
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    UPDATE secret_master_key_versions
    SET status = 'retired', retired_at = requested_at
    WHERE master_key_version = requested_version
      AND status = 'decrypt_only';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Secret Store master key is not eligible for retirement'
            USING ERRCODE = '23514';
    END IF;
END;
$$;

CREATE FUNCTION geo_assert_secret_reference_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Secret Store references are immutable history'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.id <> NEW.id OR OLD.project_id <> NEW.project_id
       OR OLD.purpose <> NEW.purpose OR OLD.created_by <> NEW.created_by
       OR OLD.created_at <> NEW.created_at
       OR NEW.aggregate_version <> OLD.aggregate_version + 1
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'Secret Store reference CAS transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_secret_version_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    latest_version integer;
    key_status text;
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended('secret-version:' || NEW.project_id || ':' || NEW.reference_id, 0)
    );
    SELECT max(version) INTO latest_version
    FROM secret_versions
    WHERE reference_id = NEW.reference_id AND project_id = NEW.project_id;
    IF NEW.version <> coalesce(latest_version, 0) + 1
       OR NEW.status <> 'pending'
       OR NEW.verified_at IS NOT NULL OR NEW.activated_at IS NOT NULL
       OR NEW.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'Secret Store version append is invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT status INTO STRICT key_status
    FROM secret_master_key_versions
    WHERE master_key_version = NEW.master_key_version;
    IF key_status <> 'encrypt_decrypt' THEN
        RAISE EXCEPTION 'Secret Store encryption key is not active'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_secret_version_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    old_key_status text;
    new_key_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Secret Store versions are immutable history'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.reference_id <> NEW.reference_id OR OLD.project_id <> NEW.project_id
       OR OLD.purpose <> NEW.purpose OR OLD.version <> NEW.version
       OR OLD.algorithm <> NEW.algorithm OR OLD.created_at <> NEW.created_at
       OR OLD.created_by <> NEW.created_by THEN
        RAISE EXCEPTION 'Secret Store encrypted version identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF OLD.master_key_version <> NEW.master_key_version THEN
        SELECT status INTO STRICT old_key_status
        FROM secret_master_key_versions
        WHERE master_key_version = OLD.master_key_version;
        SELECT status INTO STRICT new_key_status
        FROM secret_master_key_versions
        WHERE master_key_version = NEW.master_key_version;
        IF OLD.ciphertext <> NEW.ciphertext OR OLD.data_nonce <> NEW.data_nonce
           OR OLD.status <> NEW.status
           OR OLD.verified_by IS DISTINCT FROM NEW.verified_by
           OR OLD.verified_at IS DISTINCT FROM NEW.verified_at
           OR OLD.activated_by IS DISTINCT FROM NEW.activated_by
           OR OLD.activated_at IS DISTINCT FROM NEW.activated_at
           OR OLD.revoked_by IS DISTINCT FROM NEW.revoked_by
           OR OLD.revoked_at IS DISTINCT FROM NEW.revoked_at
           OR OLD.wrapped_data_key = NEW.wrapped_data_key
           OR OLD.wrap_nonce = NEW.wrap_nonce
           OR old_key_status <> 'decrypt_only'
           OR new_key_status <> 'encrypt_decrypt'
           OR NEW.master_key_version <= OLD.master_key_version THEN
            RAISE EXCEPTION 'Secret Store rewrap transition is invalid'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.ciphertext <> NEW.ciphertext OR OLD.data_nonce <> NEW.data_nonce
       OR OLD.wrapped_data_key <> NEW.wrapped_data_key
       OR OLD.wrap_nonce <> NEW.wrap_nonce THEN
        RAISE EXCEPTION 'Secret Store encrypted content is immutable'
            USING ERRCODE = '55000';
    END IF;
    IF NOT (
        (OLD.status = 'pending' AND NEW.status = 'pending'
            AND OLD.verified_by IS NULL AND OLD.verified_at IS NULL
            AND NEW.verified_by IS NOT NULL AND NEW.verified_at IS NOT NULL
            AND OLD.activated_by IS NULL AND NEW.activated_by IS NULL
            AND OLD.activated_at IS NULL AND NEW.activated_at IS NULL
            AND OLD.revoked_by IS NULL AND NEW.revoked_by IS NULL
            AND OLD.revoked_at IS NULL AND NEW.revoked_at IS NULL)
        OR (OLD.status = 'pending' AND NEW.status = 'active'
            AND OLD.verified_by IS NOT NULL AND OLD.verified_at IS NOT NULL
            AND NEW.verified_by = OLD.verified_by
            AND NEW.verified_at = OLD.verified_at
            AND OLD.activated_by IS NULL AND OLD.activated_at IS NULL
            AND NEW.activated_by IS NOT NULL AND NEW.activated_at IS NOT NULL
            AND NEW.revoked_by IS NULL AND NEW.revoked_at IS NULL)
        OR (OLD.status = 'active' AND NEW.status = 'superseded'
            AND NEW.verified_by = OLD.verified_by
            AND NEW.verified_at = OLD.verified_at
            AND NEW.activated_by = OLD.activated_by
            AND NEW.activated_at = OLD.activated_at
            AND NEW.revoked_by IS NULL AND NEW.revoked_at IS NULL)
        OR (OLD.status IN ('pending', 'active', 'superseded')
            AND NEW.status = 'revoked'
            AND NEW.verified_by IS NOT DISTINCT FROM OLD.verified_by
            AND NEW.verified_at IS NOT DISTINCT FROM OLD.verified_at
            AND NEW.activated_by IS NOT DISTINCT FROM OLD.activated_by
            AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
            AND OLD.revoked_by IS NULL AND OLD.revoked_at IS NULL
            AND NEW.revoked_by IS NOT NULL AND NEW.revoked_at IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'Secret Store version lifecycle transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_secret_rewrap_audit() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.master_key_version = NEW.master_key_version THEN
        RETURN NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM secret_audit_events audit
        JOIN secret_command_receipts receipt
          ON receipt.reference_id = audit.reference_id
         AND receipt.project_id = audit.project_id
         AND receipt.purpose = audit.purpose
         AND receipt.version = audit.version
         AND receipt.recorded_at = audit.occurred_at
        WHERE audit.reference_id = NEW.reference_id
          AND audit.project_id = NEW.project_id
          AND audit.purpose = NEW.purpose
          AND audit.version = NEW.version
          AND audit.action = 'version_rewrapped'
          AND audit.master_key_version = NEW.master_key_version
          AND receipt.operation = 'rewrap'
          AND receipt.status = NEW.status
    ) THEN
        RAISE EXCEPTION 'Secret Store rewrap requires matching receipt and audit lineage'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_secret_current_version() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_reference uuid;
    target_project uuid;
    current_value integer;
    active_versions integer[];
BEGIN
    IF TG_TABLE_NAME = 'secret_references' THEN
        target_reference := NEW.id;
    ELSE
        target_reference := NEW.reference_id;
    END IF;
    target_project := NEW.project_id;
    SELECT current_version INTO current_value
    FROM secret_references
    WHERE id = target_reference AND project_id = target_project;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;
    SELECT coalesce(array_agg(version ORDER BY version), ARRAY[]::integer[])
    INTO active_versions
    FROM secret_versions
    WHERE reference_id = target_reference AND project_id = target_project
      AND status = 'active';
    IF (current_value IS NULL AND cardinality(active_versions) <> 0)
       OR (current_value IS NOT NULL AND active_versions <> ARRAY[current_value]) THEN
        RAISE EXCEPTION 'Secret Store current version does not match active version'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION geo_assert_secret_command_outcome() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    persisted_status text;
    persisted_aggregate integer;
BEGIN
    SELECT status INTO STRICT persisted_status
    FROM secret_versions
    WHERE reference_id = NEW.reference_id AND project_id = NEW.project_id
      AND purpose = NEW.purpose AND version = NEW.version;
    SELECT aggregate_version INTO STRICT persisted_aggregate
    FROM secret_references
    WHERE id = NEW.reference_id AND project_id = NEW.project_id
      AND purpose = NEW.purpose;
    IF persisted_status <> NEW.status OR persisted_aggregate <> NEW.aggregate_version THEN
        RAISE EXCEPTION 'Secret Store command outcome is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION geo_assert_secret_audit_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    persisted_key_version integer;
BEGIN
    SELECT master_key_version INTO STRICT persisted_key_version
    FROM secret_versions
    WHERE reference_id = NEW.reference_id AND project_id = NEW.project_id
      AND purpose = NEW.purpose AND version = NEW.version;
    IF persisted_key_version <> NEW.master_key_version THEN
        RAISE EXCEPTION 'Secret Store audit key lineage is inconsistent'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER secret_master_key_versions_change_guard
BEFORE UPDATE OR DELETE ON secret_master_key_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_master_key_change();
CREATE TRIGGER secret_references_change_guard
BEFORE UPDATE OR DELETE ON secret_references
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_reference_change();
CREATE TRIGGER secret_versions_insert_guard
BEFORE INSERT ON secret_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_version_insert();
CREATE TRIGGER secret_versions_change_guard
BEFORE UPDATE OR DELETE ON secret_versions
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_version_change();
CREATE CONSTRAINT TRIGGER secret_versions_rewrap_audit_guard
AFTER UPDATE ON secret_versions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_rewrap_audit();
CREATE CONSTRAINT TRIGGER secret_references_current_guard
AFTER INSERT OR UPDATE ON secret_references
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_current_version();
CREATE CONSTRAINT TRIGGER secret_versions_current_guard
AFTER INSERT OR UPDATE ON secret_versions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_current_version();
CREATE TRIGGER secret_command_receipts_outcome_guard
BEFORE INSERT ON secret_command_receipts
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_command_outcome();
CREATE TRIGGER secret_command_receipts_immutable
BEFORE UPDATE OR DELETE ON secret_command_receipts
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();
CREATE TRIGGER secret_audit_events_lineage_guard
BEFORE INSERT ON secret_audit_events
FOR EACH ROW EXECUTE FUNCTION geo_assert_secret_audit_lineage();
CREATE TRIGGER secret_audit_events_immutable
BEFORE UPDATE OR DELETE ON secret_audit_events
FOR EACH ROW EXECUTE FUNCTION geo_reject_immutable_change();

CREATE INDEX secret_references_project_created_idx
ON secret_references(project_id, created_at DESC, id);
CREATE INDEX secret_references_created_by_idx ON secret_references(created_by);
CREATE INDEX secret_versions_scope_fkey_idx
ON secret_versions(reference_id, project_id, purpose);
CREATE INDEX secret_versions_project_key_idx
ON secret_versions(project_id, reference_id, version DESC);
CREATE INDEX secret_versions_created_by_idx ON secret_versions(created_by);
CREATE INDEX secret_versions_verified_by_idx ON secret_versions(verified_by)
WHERE verified_by IS NOT NULL;
CREATE INDEX secret_versions_activated_by_idx ON secret_versions(activated_by)
WHERE activated_by IS NOT NULL;
CREATE INDEX secret_versions_revoked_by_idx ON secret_versions(revoked_by)
WHERE revoked_by IS NOT NULL;
CREATE INDEX secret_versions_master_key_idx ON secret_versions(master_key_version);
CREATE INDEX secret_command_receipts_version_fkey_idx
ON secret_command_receipts(reference_id, project_id, purpose, version);
CREATE INDEX secret_audit_events_project_time_idx
ON secret_audit_events(project_id, occurred_at DESC, id);
CREATE INDEX secret_audit_events_version_fkey_idx
ON secret_audit_events(reference_id, project_id, purpose, version);
CREATE INDEX secret_audit_events_actor_idx ON secret_audit_events(actor_id);
CREATE INDEX secret_audit_events_master_key_idx
ON secret_audit_events(master_key_version);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'secret_references', 'secret_versions',
        'secret_command_receipts', 'secret_audit_events'
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
    secret_master_key_versions, secret_references, secret_versions,
    secret_command_receipts, secret_audit_events
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT SELECT ON
    secret_master_key_versions, secret_references, secret_versions,
    secret_command_receipts, secret_audit_events
TO geo_app;
GRANT INSERT, UPDATE ON secret_references, secret_versions TO geo_app;
GRANT INSERT ON secret_command_receipts, secret_audit_events TO geo_app;
GRANT SELECT ON
    secret_master_key_versions, secret_references, secret_versions,
    secret_command_receipts, secret_audit_events
TO geo_worker;
GRANT INSERT ON secret_command_receipts, secret_audit_events TO geo_worker;

REVOKE ALL ON FUNCTION
    geo_sync_secret_master_key_version(integer, text, text, bytea, bytea, timestamptz),
    geo_retire_secret_master_key_version(integer, timestamptz),
    geo_assert_secret_master_key_change(),
    geo_assert_secret_reference_change(),
    geo_assert_secret_version_insert(),
    geo_assert_secret_version_change(),
    geo_assert_secret_rewrap_audit(),
    geo_assert_secret_current_version(),
    geo_assert_secret_command_outcome(),
    geo_assert_secret_audit_lineage()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION
    geo_sync_secret_master_key_version(integer, text, text, bytea, bytea, timestamptz),
    geo_retire_secret_master_key_version(integer, timestamptz),
    geo_assert_secret_master_key_change(),
    geo_assert_secret_reference_change(),
    geo_assert_secret_version_insert(),
    geo_assert_secret_version_change(),
    geo_assert_secret_rewrap_audit(),
    geo_assert_secret_current_version(),
    geo_assert_secret_command_outcome(),
    geo_assert_secret_audit_lineage()
TO geo_app;

GRANT EXECUTE ON FUNCTION
    geo_assert_secret_version_insert(),
    geo_assert_secret_current_version(),
    geo_assert_secret_command_outcome(),
    geo_assert_secret_audit_lineage()
TO geo_worker;
