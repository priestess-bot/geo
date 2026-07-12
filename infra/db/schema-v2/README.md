# Schema v2 baseline

This directory is the source of truth for fresh `geno_v2` database installs.
It is intentionally isolated from `infra/db/migrations/up`, which remains the
Schema v1 migration chain until the v2 cutover is approved.

The database name is fixed to `geno_v2` in both the manifest and the isolated
Compose stack. `SCHEMA_V2_POSTGRES_DB` and a separately supplied Compose
`SCHEMA_V2_DATABASE_URL` are deliberately unsupported: the runner rejects any
other database identity. Compose derives the installer and verifier URLs from
the same required `SCHEMA_V2_POSTGRES_USER` and URL-safe
`SCHEMA_V2_POSTGRES_PASSWORD` values used to initialize PostgreSQL. Make targets
generate a strong disposable local password when callers do not provide one.

`manifest.json` orders every executable SQL file and pins its SHA-256 digest.
The baseline hash is SHA-256 over the following UTF-8 record for each baseline
file, in manifest order:

```text
<relative-path>\0<file-sha256>\n
```

The installer refuses checksum drift before opening a database connection. It
then acquires the session-level advisory lock `geno:schema-v2:install` with a
bounded deadline while it installs or verifies the ledger. Each SQL file and
its ledger row are committed in the same transaction.

During pre-cutover development, changing the baseline requires deleting the
disposable `geno_v2` volume and performing a fresh install. After the baseline
is released, never edit a listed baseline file; add an ordered file under
`migrations/` and list it in `migration_files` instead.
