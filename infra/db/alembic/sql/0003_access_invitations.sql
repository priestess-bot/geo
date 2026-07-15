CREATE FUNCTION geo_current_invitation_token_hash() RETURNS text
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT NULLIF(current_setting('geo.invitation_token_hash', true), '')
$$;

CREATE FUNCTION geo_can_manage_project_memberships(
    target_project_id uuid,
    target_tenant_id uuid
) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
    SELECT target_tenant_id = public.geo_current_tenant_id()
       AND EXISTS (
           SELECT 1
           FROM public.project_memberships AS manager
           WHERE manager.project_id = target_project_id
             AND manager.tenant_id = target_tenant_id
             AND manager.identity_id = public.geo_current_identity_id()
             AND manager.status = 'active'
             AND manager.role IN ('owner', 'admin')
       )
$$;

REVOKE ALL ON FUNCTION geo_can_manage_project_memberships(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION geo_can_manage_project_memberships(uuid, uuid)
FROM geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_can_manage_project_memberships(uuid, uuid) TO geo_app;

DROP POLICY project_scope ON project_memberships;
CREATE POLICY project_scope ON project_memberships
USING (
    tenant_id = geo_current_tenant_id()
    AND (
        identity_id = geo_current_identity_id()
        OR geo_can_manage_project_memberships(project_id, tenant_id)
    )
)
WITH CHECK (
    tenant_id = geo_current_tenant_id()
    AND (
        identity_id = geo_current_identity_id()
        OR geo_can_manage_project_memberships(project_id, tenant_id)
    )
);

ALTER TABLE customer_sessions
    ADD COLUMN csrf_token_hash text CHECK (csrf_token_hash ~ '^[0-9a-f]{64}$'),
    ADD COLUMN surface text NOT NULL DEFAULT 'customer' CHECK (surface = 'customer');

CREATE TABLE project_invitations (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    email text NOT NULL CHECK (email = lower(btrim(email)) AND position('@' IN email) > 1),
    role text NOT NULL CHECK (role IN ('analyst', 'viewer', 'customer')),
    target_surface text NOT NULL CHECK (target_surface = 'customer'),
    token_hash text NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    token_hint text NOT NULL CHECK (char_length(token_hint) BETWEEN 4 AND 12),
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'redeemed', 'revoked', 'expired')
    ),
    expires_at timestamptz NOT NULL,
    created_by uuid NOT NULL REFERENCES identities(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    redeemed_by uuid REFERENCES identities(id),
    redeemed_at timestamptz,
    revoked_by uuid REFERENCES identities(id),
    revoked_at timestamptz,
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    UNIQUE (id, project_id),
    UNIQUE (project_id, idempotency_key_hash),
    CHECK (
        (status = 'pending' AND redeemed_by IS NULL AND redeemed_at IS NULL
            AND revoked_by IS NULL AND revoked_at IS NULL)
        OR (status = 'redeemed' AND redeemed_by IS NOT NULL AND redeemed_at IS NOT NULL
            AND revoked_by IS NULL AND revoked_at IS NULL)
        OR (status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL
            AND redeemed_by IS NULL AND redeemed_at IS NULL)
        OR (status = 'expired' AND redeemed_by IS NULL AND redeemed_at IS NULL
            AND revoked_by IS NULL AND revoked_at IS NULL)
    )
);

CREATE INDEX project_invitations_project_activity_idx
ON project_invitations (project_id, created_at DESC, id DESC);

CREATE INDEX project_invitations_pending_expiry_idx
ON project_invitations (expires_at)
WHERE status = 'pending';

CREATE TABLE invitation_redemptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invitation_id uuid NOT NULL,
    project_id uuid NOT NULL,
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    identity_id uuid NOT NULL REFERENCES identities(id),
    session_id uuid NOT NULL REFERENCES customer_sessions(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (invitation_id, project_id)
        REFERENCES project_invitations(id, project_id) ON DELETE CASCADE,
    UNIQUE (invitation_id, idempotency_key_hash)
);

CREATE TABLE membership_commands (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    actor_identity_id uuid NOT NULL REFERENCES identities(id),
    command_type text NOT NULL CHECK (
        command_type IN ('add', 'revoke', 'change_role', 'reactivate')
    ),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^[0-9a-f]{64}$'),
    request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    membership_id uuid NOT NULL,
    result_snapshot jsonb NOT NULL CHECK (jsonb_typeof(result_snapshot) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id) ON DELETE CASCADE,
    FOREIGN KEY (membership_id, project_id)
        REFERENCES project_memberships(id, project_id) ON DELETE CASCADE,
    UNIQUE (project_id, idempotency_key_hash)
);

CREATE TABLE access_audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    project_id uuid,
    actor_identity_id uuid REFERENCES identities(id),
    event_type text NOT NULL CHECK (event_type IN (
        'invitation.created', 'invitation.preflight_failed', 'invitation.redeemed',
        'invitation.revoked', 'invitation.expired', 'session.created', 'session.revoked',
        'session.csrf_rejected', 'tenant.bootstrap', 'member.added', 'member.revoked',
        'member.role_changed', 'member.reactivated'
    )),
    subject_type text NOT NULL CHECK (
        subject_type IN ('invitation', 'session', 'project', 'membership')
    ),
    subject_id uuid NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
);

CREATE INDEX access_audit_events_project_created_idx
ON access_audit_events (project_id, created_at DESC, id DESC);

CREATE FUNCTION geo_reject_access_audit_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'access audit events are append-only' USING ERRCODE = '55000';
END;
$$;

CREATE FUNCTION geo_protect_bootstrap_audit_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    installer_allowed boolean;
BEGIN
    IF NEW.event_type <> 'tenant.bootstrap' THEN
        RETURN NEW;
    END IF;
    SELECT current_user = session_user
           AND current_user = pg_get_userbyid(database_owner.datdba)
           AND (role.rolsuper OR role.rolbypassrls)
           AND current_user NOT IN ('geo_app', 'geo_worker')
           AND NOT EXISTS (
               SELECT 1 FROM pg_auth_members AS membership
               JOIN pg_roles AS granted ON granted.oid = membership.roleid
               JOIN pg_roles AS member ON member.oid = membership.member
               WHERE member.rolname = current_user
                 AND granted.rolname IN ('geo_app', 'geo_worker')
           )
    INTO installer_allowed
    FROM pg_database AS database_owner
    JOIN pg_roles AS role ON role.rolname = current_user
    WHERE database_owner.datname = current_database();
    IF NOT COALESCE(installer_allowed, false) THEN
        RAISE EXCEPTION 'tenant bootstrap audit requires the installer role'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER access_audit_events_bootstrap_installer_only
BEFORE INSERT ON access_audit_events
FOR EACH ROW EXECUTE FUNCTION geo_protect_bootstrap_audit_insert();

CREATE TRIGGER access_audit_events_append_only
BEFORE UPDATE OR DELETE ON access_audit_events
FOR EACH ROW EXECUTE FUNCTION geo_reject_access_audit_change();

ALTER TABLE project_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_invitations FORCE ROW LEVEL SECURITY;
CREATE POLICY project_or_invitation_token_scope ON project_invitations
USING (
    project_id = ANY(geo_current_project_ids())
    OR token_hash = geo_current_invitation_token_hash()
)
WITH CHECK (
    project_id = ANY(geo_current_project_ids())
    OR token_hash = geo_current_invitation_token_hash()
);

ALTER TABLE invitation_redemptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitation_redemptions FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON invitation_redemptions
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE membership_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE membership_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON membership_commands
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));

ALTER TABLE access_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY project_scope ON access_audit_events
USING (project_id = ANY(geo_current_project_ids()))
WITH CHECK (project_id = ANY(geo_current_project_ids()));
