-- Fresh-install tenancy, project, authorization, and audit boundary for Schema v2.
-- This is a clean baseline: it contains no Schema v1 compatibility or data repair.

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE USAGE ON SCHEMA public FROM PUBLIC;

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'geno_v2_runtime') THEN
        CREATE ROLE geno_v2_runtime
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    ELSE
        ALTER ROLE geno_v2_runtime
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'geno_v2_authz_owner') THEN
        CREATE ROLE geno_v2_authz_owner
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION BYPASSRLS;
    ELSE
        ALTER ROLE geno_v2_authz_owner
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
            NOREPLICATION BYPASSRLS;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        WHERE membership.roleid = (
                SELECT oid FROM pg_catalog.pg_roles
                WHERE rolname = 'geno_v2_authz_owner'
            )
           OR membership.member = (
                SELECT oid FROM pg_catalog.pg_roles
                WHERE rolname = 'geno_v2_authz_owner'
            )
           OR membership.member = (
                SELECT oid FROM pg_catalog.pg_roles
                WHERE rolname = 'geno_v2_runtime'
            )
           OR membership.roleid = (
                SELECT oid FROM pg_catalog.pg_roles
                WHERE rolname = 'geno_v2_api_login'
            )
           OR (
                membership.roleid = (
                    SELECT oid FROM pg_catalog.pg_roles
                    WHERE rolname = 'geno_v2_runtime'
                )
                AND membership.member IS DISTINCT FROM (
                    SELECT oid FROM pg_catalog.pg_roles
                    WHERE rolname = 'geno_v2_api_login'
                )
           )
           OR (
                membership.member = (
                    SELECT oid FROM pg_catalog.pg_roles
                    WHERE rolname = 'geno_v2_api_login'
                )
                AND membership.roleid IS DISTINCT FROM (
                    SELECT oid FROM pg_catalog.pg_roles
                    WHERE rolname = 'geno_v2_runtime'
                )
           )
    ) THEN
        RAISE EXCEPTION
            'Schema v2 boundary roles contain an unauthorized role membership';
    END IF;
END
$roles$;

GRANT USAGE ON SCHEMA public TO geno_v2_authz_owner;

CREATE TABLE market_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    market_code text NOT NULL UNIQUE,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT market_profiles_market_code_canonical
        CHECK (market_code = btrim(market_code) AND market_code <> ''),
    CONSTRAINT market_profiles_payload_object
        CHECK (jsonb_typeof(payload) = 'object')
);

CREATE TABLE industry_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    market_code text NOT NULL,
    industry_code text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT industry_profiles_market_fkey
        FOREIGN KEY (market_code) REFERENCES market_profiles(market_code)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT industry_profiles_market_industry_unique
        UNIQUE (market_code, industry_code),
    CONSTRAINT industry_profiles_industry_code_canonical
        CHECK (industry_code = btrim(industry_code) AND industry_code <> ''),
    CONSTRAINT industry_profiles_payload_object
        CHECK (jsonb_typeof(payload) = 'object')
);

CREATE TABLE tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    slug text NOT NULL UNIQUE,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT tenants_id_tenant_unique UNIQUE (id),
    CONSTRAINT tenants_name_nonempty CHECK (btrim(name) <> ''),
    CONSTRAINT tenants_slug_canonical
        CHECK (slug = lower(btrim(slug)) AND slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    CONSTRAINT tenants_status_canonical CHECK (status IN ('active', 'disabled'))
);

CREATE TABLE projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    name text NOT NULL,
    market_code text NOT NULL,
    industry_code text NOT NULL,
    target_brand text NOT NULL,
    category text NOT NULL,
    prompt_version text NOT NULL,
    status text NOT NULL DEFAULT 'paused',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT projects_tenant_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT projects_industry_profile_fkey
        FOREIGN KEY (market_code, industry_code)
        REFERENCES industry_profiles(market_code, industry_code)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT projects_id_tenant_unique UNIQUE (id, tenant_id),
    CONSTRAINT projects_name_nonempty CHECK (btrim(name) <> ''),
    CONSTRAINT projects_target_brand_nonempty CHECK (btrim(target_brand) <> ''),
    CONSTRAINT projects_category_nonempty CHECK (btrim(category) <> ''),
    CONSTRAINT projects_prompt_version_nonempty CHECK (btrim(prompt_version) <> ''),
    CONSTRAINT projects_status_canonical CHECK (status IN ('active', 'paused', 'archived'))
);

CREATE TABLE tenant_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    user_id text NOT NULL,
    role text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    invited_by text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT tenant_members_tenant_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT tenant_members_id_tenant_unique UNIQUE (id, tenant_id),
    CONSTRAINT tenant_members_tenant_user_unique UNIQUE (tenant_id, user_id),
    CONSTRAINT tenant_members_user_id_canonical
        CHECK (user_id = lower(btrim(user_id)) AND user_id <> ''),
    CONSTRAINT tenant_members_role_canonical
        CHECK (role IN ('super_admin', 'tenant_admin')),
    CONSTRAINT tenant_members_status_canonical CHECK (status IN ('active', 'disabled')),
    CONSTRAINT tenant_members_invited_by_nonempty
        CHECK (invited_by IS NULL OR btrim(invited_by) <> '')
);

CREATE TABLE project_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    user_id text NOT NULL,
    role text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    invited_by text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT project_members_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT project_members_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT project_members_project_user_unique UNIQUE (project_id, user_id),
    CONSTRAINT project_members_user_id_canonical
        CHECK (user_id = lower(btrim(user_id)) AND user_id <> ''),
    CONSTRAINT project_members_role_canonical
        CHECK (role IN (
            'project_owner', 'analyst', 'reviewer', 'knowledge_architect',
            'content_operator', 'client_viewer'
        )),
    CONSTRAINT project_members_status_canonical CHECK (status IN ('active', 'disabled')),
    CONSTRAINT project_members_invited_by_nonempty
        CHECK (invited_by IS NULL OR btrim(invited_by) <> '')
);

CREATE FUNCTION geno_v2_permissions_for_role(canonical_role text)
RETURNS text[]
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog
AS $permissions$
    SELECT CASE canonical_role
        WHEN 'super_admin' THEN ARRAY[
            'tenant.create', 'tenant.read', 'tenant.update', 'tenant.disable',
            'member.invite', 'member.manage', 'project.create', 'project.read',
            'project.update', 'project.archive', 'prompt.import', 'connector.read',
            'connector.manage', 'connector.secret.manage', 'collection.run',
            'collection.read', 'evidence.read_summary', 'evidence.read_raw',
            'analysis.read', 'analysis.review', 'score.read', 'score.configure',
            'report.read', 'report.generate', 'report.approve', 'report.publish',
            'report.revoke', 'report.download', 'action.manage', 'action.read',
            'retest.run', 'retest.read', 'knowledge.read', 'knowledge.import',
            'knowledge.review', 'knowledge.read_approved', 'content.read',
            'content.update', 'content.generate', 'content.review',
            'distribution.read', 'distribution.create', 'distribution.update',
            'audit.read', 'cost.read', 'system.admin',
            'geo.campaign.manage', 'geo.query.approve', 'geo.observation.import',
            'geo.destination.manage', 'geo.opportunity.manage', 'geo.package.create',
            'geo.package.approve', 'geo.submission.record', 'geo.verification.run',
            'geo.measurement.read'
        ]::text[]
        WHEN 'tenant_admin' THEN ARRAY[
            'tenant.read', 'tenant.update', 'member.invite', 'member.manage',
            'project.create', 'project.read', 'project.update', 'report.read',
            'audit.read', 'cost.read'
        ]::text[]
        WHEN 'project_owner' THEN ARRAY[
            'project.read', 'project.update', 'project.archive', 'member.invite',
            'member.manage', 'prompt.import', 'connector.read', 'connector.manage',
            'connector.secret.manage', 'collection.run', 'collection.read',
            'evidence.read_summary', 'analysis.read', 'analysis.review', 'score.read',
            'score.configure', 'report.read', 'report.generate', 'report.publish',
            'report.revoke', 'report.download', 'action.manage', 'action.read',
            'retest.run', 'retest.read', 'geo.campaign.manage', 'geo.query.approve',
            'geo.observation.import', 'geo.destination.manage', 'geo.opportunity.manage',
            'geo.package.create', 'geo.package.approve', 'geo.submission.record',
            'geo.verification.run', 'geo.measurement.read'
        ]::text[]
        WHEN 'analyst' THEN ARRAY[
            'project.read', 'prompt.import', 'collection.run', 'collection.read',
            'evidence.read_summary', 'evidence.read_raw', 'analysis.read',
            'analysis.review', 'score.read', 'report.read', 'report.generate',
            'action.manage', 'action.read', 'geo.observation.import',
            'geo.opportunity.manage', 'geo.measurement.read'
        ]::text[]
        WHEN 'reviewer' THEN ARRAY[
            'project.read', 'evidence.read_summary', 'analysis.read',
            'analysis.review', 'score.read', 'report.read', 'report.approve',
            'report.revoke', 'content.review', 'geo.package.approve',
            'geo.measurement.read'
        ]::text[]
        WHEN 'knowledge_architect' THEN ARRAY[
            'project.read', 'knowledge.read', 'knowledge.import', 'knowledge.review',
            'knowledge.read_approved', 'content.read'
        ]::text[]
        WHEN 'content_operator' THEN ARRAY[
            'project.read', 'knowledge.read_approved', 'content.read',
            'content.generate', 'content.update', 'distribution.read',
            'distribution.create', 'distribution.update', 'geo.package.create',
            'geo.submission.record', 'geo.verification.run', 'geo.measurement.read'
        ]::text[]
        WHEN 'client_viewer' THEN ARRAY[
            'project.read', 'score.read', 'report.read', 'report.download',
            'action.read', 'retest.read', 'knowledge.read_approved',
            'geo.measurement.read'
        ]::text[]
        ELSE ARRAY[]::text[]
    END;
$permissions$;

CREATE FUNCTION geno_v2_role_has_permission(
    canonical_role text,
    required_permission text
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog
AS $permission_check$
    SELECT required_permission = ANY(public.geno_v2_permissions_for_role(canonical_role));
$permission_check$;

CREATE TABLE runtime_project_access_grants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL,
    project_id uuid NOT NULL,
    actor_id text NOT NULL,
    source_type text NOT NULL,
    source_id uuid NOT NULL,
    canonical_role text NOT NULL,
    permission_set_version text NOT NULL DEFAULT 'authz_permissions_v2',
    permissions text[] NOT NULL,
    status text NOT NULL DEFAULT 'active',
    granted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT runtime_grants_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT runtime_grants_source_tenant_fkey
        FOREIGN KEY (source_id, tenant_id) REFERENCES tenant_members(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT runtime_grants_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT runtime_grants_source_unique
        UNIQUE (tenant_id, project_id, actor_id, source_type, source_id),
    CONSTRAINT runtime_grants_actor_id_canonical
        CHECK (actor_id = lower(btrim(actor_id)) AND actor_id <> ''),
    CONSTRAINT runtime_grants_source_type_canonical CHECK (source_type = 'tenant_role'),
    CONSTRAINT runtime_grants_role_canonical
        CHECK (canonical_role IN ('super_admin', 'tenant_admin')),
    CONSTRAINT runtime_grants_permission_version_canonical
        CHECK (permission_set_version = 'authz_permissions_v2'),
    CONSTRAINT runtime_grants_permissions_canonical
        CHECK (permissions = geno_v2_permissions_for_role(canonical_role)),
    CONSTRAINT runtime_grants_status_canonical CHECK (status = 'active')
);

CREATE TABLE audit_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid,
    project_id uuid,
    event_type text NOT NULL,
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    target_type text NOT NULL,
    target_id text NOT NULL,
    before_hash text,
    after_hash text,
    input_refs jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_refs jsonb NOT NULL DEFAULT '{}'::jsonb,
    method_version text,
    reason text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT audit_events_tenant_fkey
        FOREIGN KEY (tenant_id) REFERENCES tenants(id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT audit_events_project_tenant_fkey
        FOREIGN KEY (project_id, tenant_id) REFERENCES projects(id, tenant_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT audit_events_id_project_unique UNIQUE (id, project_id),
    CONSTRAINT audit_events_scope_pair
        CHECK (project_id IS NULL OR tenant_id IS NOT NULL),
    CONSTRAINT audit_events_event_type_nonempty CHECK (btrim(event_type) <> ''),
    CONSTRAINT audit_events_actor_type_canonical
        CHECK (actor_type IN ('user', 'system', 'worker', 'service')),
    CONSTRAINT audit_events_actor_id_nonempty CHECK (btrim(actor_id) <> ''),
    CONSTRAINT audit_events_target_type_nonempty CHECK (btrim(target_type) <> ''),
    CONSTRAINT audit_events_target_id_nonempty CHECK (btrim(target_id) <> ''),
    CONSTRAINT audit_events_before_hash_sha256
        CHECK (before_hash IS NULL OR before_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT audit_events_after_hash_sha256
        CHECK (after_hash IS NULL OR after_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT audit_events_input_refs_object CHECK (jsonb_typeof(input_refs) = 'object'),
    CONSTRAINT audit_events_output_refs_object CHECK (jsonb_typeof(output_refs) = 'object'),
    CONSTRAINT audit_events_method_version_nonempty
        CHECK (method_version IS NULL OR btrim(method_version) <> '')
);

CREATE INDEX industry_profiles_market_idx
    ON industry_profiles (market_code, industry_code);
CREATE INDEX projects_tenant_status_idx ON projects (tenant_id, status, id);
CREATE INDEX projects_profile_idx ON projects (market_code, industry_code, status);
CREATE INDEX tenant_members_actor_status_idx
    ON tenant_members (user_id, status, tenant_id);
CREATE INDEX project_members_actor_status_idx
    ON project_members (user_id, status, tenant_id, project_id);
CREATE INDEX project_members_project_status_idx
    ON project_members (project_id, status, user_id);
CREATE INDEX runtime_grants_actor_project_idx
    ON runtime_project_access_grants (actor_id, tenant_id, status, project_id);
CREATE INDEX runtime_grants_project_idx
    ON runtime_project_access_grants (project_id, tenant_id, status);
CREATE INDEX audit_events_project_created_idx
    ON audit_events (project_id, created_at DESC) WHERE project_id IS NOT NULL;
CREATE INDEX audit_events_tenant_created_idx
    ON audit_events (tenant_id, created_at DESC)
    WHERE tenant_id IS NOT NULL AND project_id IS NULL;
CREATE INDEX audit_events_global_actor_created_idx
    ON audit_events (actor_id, created_at DESC)
    WHERE tenant_id IS NULL AND project_id IS NULL;

CREATE FUNCTION geno_v2_sync_tenant_member_project_grants()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $sync_tenant_member$
BEGIN
    DELETE FROM public.runtime_project_access_grants
    WHERE source_type = 'tenant_role'
      AND source_id = coalesce(NEW.id, OLD.id);

    IF TG_OP <> 'DELETE'
       AND NEW.status = 'active'
       AND NEW.role IN ('super_admin', 'tenant_admin') THEN
        INSERT INTO public.runtime_project_access_grants (
            tenant_id, project_id, actor_id, source_type, source_id,
            canonical_role, permission_set_version, permissions, status
        )
        SELECT
            NEW.tenant_id,
            project_row.id,
            NEW.user_id,
            'tenant_role',
            NEW.id,
            NEW.role,
            'authz_permissions_v2',
            public.geno_v2_permissions_for_role(NEW.role),
            'active'
        FROM public.projects AS project_row
        JOIN public.tenants AS tenant_row ON tenant_row.id = project_row.tenant_id
        WHERE project_row.tenant_id = NEW.tenant_id
          AND tenant_row.status = 'active'
          AND project_row.status <> 'archived';
    END IF;
    RETURN coalesce(NEW, OLD);
END;
$sync_tenant_member$;

CREATE FUNCTION geno_v2_sync_project_tenant_grants()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $sync_project$
BEGIN
    DELETE FROM public.runtime_project_access_grants
    WHERE project_id = coalesce(NEW.id, OLD.id)
      AND source_type = 'tenant_role';

    IF TG_OP <> 'DELETE'
       AND NEW.status <> 'archived'
       AND EXISTS (
            SELECT 1
            FROM public.tenants AS tenant_row
            WHERE tenant_row.id = NEW.tenant_id
              AND tenant_row.status = 'active'
       ) THEN
        INSERT INTO public.runtime_project_access_grants (
            tenant_id, project_id, actor_id, source_type, source_id,
            canonical_role, permission_set_version, permissions, status
        )
        SELECT
            NEW.tenant_id,
            NEW.id,
            member.user_id,
            'tenant_role',
            member.id,
            member.role,
            'authz_permissions_v2',
            public.geno_v2_permissions_for_role(member.role),
            'active'
        FROM public.tenant_members AS member
        WHERE member.tenant_id = NEW.tenant_id
          AND member.status = 'active'
          AND member.role IN ('super_admin', 'tenant_admin');
    END IF;
    RETURN coalesce(NEW, OLD);
END;
$sync_project$;

CREATE FUNCTION geno_v2_sync_tenant_status_grants()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $sync_tenant_status$
BEGIN
    DELETE FROM public.runtime_project_access_grants
    WHERE tenant_id = NEW.id
      AND source_type = 'tenant_role';

    IF NEW.status = 'active' THEN
        INSERT INTO public.runtime_project_access_grants (
            tenant_id, project_id, actor_id, source_type, source_id,
            canonical_role, permission_set_version, permissions, status
        )
        SELECT
            NEW.id,
            project_row.id,
            member.user_id,
            'tenant_role',
            member.id,
            member.role,
            'authz_permissions_v2',
            public.geno_v2_permissions_for_role(member.role),
            'active'
        FROM public.projects AS project_row
        JOIN public.tenant_members AS member
          ON member.tenant_id = project_row.tenant_id
        WHERE project_row.tenant_id = NEW.id
          AND project_row.status <> 'archived'
          AND member.status = 'active'
          AND member.role IN ('super_admin', 'tenant_admin');
    END IF;
    RETURN NEW;
END;
$sync_tenant_status$;

CREATE FUNCTION geno_v2_reject_audit_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $audit_immutable$
BEGIN
    RAISE EXCEPTION 'audit_events rows are immutable' USING ERRCODE = '55000';
END;
$audit_immutable$;

ALTER FUNCTION geno_v2_permissions_for_role(text) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_role_has_permission(text, text) OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_sync_tenant_member_project_grants()
    OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_sync_project_tenant_grants() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_sync_tenant_status_grants() OWNER TO geno_v2_authz_owner;
ALTER FUNCTION geno_v2_reject_audit_event_mutation() OWNER TO geno_v2_authz_owner;

GRANT SELECT ON tenants, projects, tenant_members, runtime_project_access_grants
    TO geno_v2_authz_owner;
GRANT INSERT, DELETE ON runtime_project_access_grants TO geno_v2_authz_owner;

CREATE TRIGGER tenant_members_sync_project_grants
AFTER INSERT OR UPDATE OF tenant_id, user_id, role, status OR DELETE ON tenant_members
FOR EACH ROW EXECUTE FUNCTION geno_v2_sync_tenant_member_project_grants();

CREATE TRIGGER projects_sync_tenant_grants
AFTER INSERT OR UPDATE OF tenant_id, status OR DELETE ON projects
FOR EACH ROW EXECUTE FUNCTION geno_v2_sync_project_tenant_grants();

CREATE TRIGGER tenants_sync_status_grants
AFTER UPDATE OF status ON tenants
FOR EACH ROW EXECUTE FUNCTION geno_v2_sync_tenant_status_grants();

CREATE TRIGGER audit_events_immutable
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION geno_v2_reject_audit_event_mutation();

ALTER TABLE market_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE industry_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE industry_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;
ALTER TABLE tenant_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_members FORCE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members FORCE ROW LEVEL SECURITY;
ALTER TABLE runtime_project_access_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_project_access_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

COMMENT ON ROLE geno_v2_runtime IS
    'NOLOGIN sealed role with no access until session-backed RLS is installed by 0011.';
COMMENT ON ROLE geno_v2_authz_owner IS
    'NOLOGIN owner for narrowly scoped projection-maintenance trigger functions.';
COMMENT ON TABLE runtime_project_access_grants IS
    'Derived active project grants for canonical tenant roles; only sync triggers may write.';
COMMENT ON TABLE projects IS
    'Runtime access intentionally remains sealed until 0011 verifies a secret session token.';
COMMENT ON TABLE audit_events IS
    'Immutable global, tenant, or project audit records; runtime access is deferred to 0011.';
