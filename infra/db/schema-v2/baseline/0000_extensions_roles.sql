-- Schema v2 bootstrap metadata. Product-domain tables are added by later B1/B2
-- slices; this file must stay independent from the Schema v1 migration chain.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE app_schema_metadata (
    schema_generation smallint PRIMARY KEY,
    baseline_version text NOT NULL,
    baseline_hash text NOT NULL,
    minimum_app_version text NOT NULL,
    installed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT app_schema_metadata_generation_v2 CHECK (schema_generation = 2),
    CONSTRAINT app_schema_metadata_baseline_version_nonempty
        CHECK (btrim(baseline_version) <> ''),
    CONSTRAINT app_schema_metadata_baseline_hash_sha256
        CHECK (baseline_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT app_schema_metadata_minimum_app_version_nonempty
        CHECK (btrim(minimum_app_version) <> '')
);

CREATE TABLE schema_migration_ledger (
    migration_id text PRIMARY KEY,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    app_commit text NOT NULL,
    CONSTRAINT schema_migration_ledger_id_scoped
        CHECK (migration_id ~ '^(baseline|migrations)/[0-9]{4}_[a-z0-9_]+\.sql$'),
    CONSTRAINT schema_migration_ledger_checksum_sha256
        CHECK (checksum ~ '^[0-9a-f]{64}$'),
    CONSTRAINT schema_migration_ledger_app_commit_nonempty
        CHECK (btrim(app_commit) <> '')
);

CREATE FUNCTION geno_schema_v2_reject_ledger_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'schema_migration_ledger rows are immutable';
END;
$$;

CREATE TRIGGER schema_migration_ledger_immutable
BEFORE UPDATE OR DELETE ON schema_migration_ledger
FOR EACH ROW
EXECUTE FUNCTION geno_schema_v2_reject_ledger_mutation();

COMMENT ON TABLE app_schema_metadata IS
    'Single-row compatibility contract for the independently installed Schema v2 database.';
COMMENT ON TABLE schema_migration_ledger IS
    'Immutable checksum ledger for ordered Schema v2 baseline and migration files.';
