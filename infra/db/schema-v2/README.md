# Schema v2 baseline

This directory is the source of truth for fresh `geno_v2` database installs.
It is intentionally isolated from `infra/db/migrations/up`, which remains the
Schema v1 migration chain until the v2 cutover is approved.

`manifest.json` orders every executable SQL file and pins its SHA-256 digest.
The baseline hash is SHA-256 over the following UTF-8 record for each baseline
file, in manifest order:

```text
<relative-path>\0<file-sha256>\n
```

The installer refuses checksum drift before opening a database connection. It
then holds the session-level advisory lock `geno:schema-v2:install` while it
installs or verifies the ledger. Each SQL file and its ledger row are committed
in the same transaction.

During pre-cutover development, changing the baseline requires deleting the
disposable `geno_v2` volume and performing a fresh install. After the baseline
is released, never edit a listed baseline file; add an ordered file under
`migrations/` and list it in `migration_files` instead.
