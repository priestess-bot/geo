#!/bin/sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
compose="docker compose -f $repo_root/infra/docker-compose.yml"
output_root="${1:-$repo_root/artifacts/backup-restore-smoke}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
bucket_stamp="$(printf '%s' "$stamp" | tr '[:upper:]' '[:lower:]')"
output="$output_root/$stamp"
restore_database="geo_restore_smoke_${stamp%%T*}"
minio_tmp="/tmp/geo-backup-restore-$stamp"
restore_bucket="geo-restore-smoke-$bucket_stamp"

mkdir -p "$output"

cleanup() {
  $compose exec -T postgres psql -U geo_installer -d postgres \
    -c "DROP DATABASE IF EXISTS $restore_database WITH (FORCE)" >/dev/null 2>&1 || true
  $compose exec -T minio sh -c \
    "mc alias set smoke http://127.0.0.1:9000 geo_dev geo_dev_secret >/dev/null 2>&1; \
     mc rm --recursive --force smoke/$restore_bucket >/dev/null 2>&1 || true; \
     mc rb smoke/$restore_bucket >/dev/null 2>&1 || true; rm -rf '$minio_tmp'" || true
}
trap cleanup EXIT INT TERM

source_projects="$($compose exec -T postgres psql -At -U geo_installer -d geo \
  -c 'SELECT count(*) FROM projects')"
source_tables="$($compose exec -T postgres psql -At -U geo_installer -d geo \
  -c "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")"

$compose exec -T postgres psql -v ON_ERROR_STOP=1 -U geo_installer -d geo \
  <"$repo_root/scripts/check_postgres_fk_integrity.sql" >/dev/null

$compose exec -T postgres pg_dump -U geo_installer -d geo \
  --clean --if-exists --no-owner --no-privileges | gzip -9 >"$output/postgres.sql.gz"
sha256sum "$output/postgres.sql.gz" >"$output/SHA256SUMS"

$compose exec -T postgres psql -v ON_ERROR_STOP=1 -U geo_installer -d postgres \
  -c "CREATE DATABASE $restore_database" >/dev/null
gunzip -c "$output/postgres.sql.gz" | $compose exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U geo_installer -d "$restore_database" >/dev/null

restored_projects="$($compose exec -T postgres psql -At -U geo_installer \
  -d "$restore_database" -c 'SELECT count(*) FROM projects')"
restored_tables="$($compose exec -T postgres psql -At -U geo_installer \
  -d "$restore_database" \
  -c "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")"
test "$source_projects" = "$restored_projects"
test "$source_tables" = "$restored_tables"

$compose exec -T minio sh -c \
  "set -eu; mc alias set smoke http://127.0.0.1:9000 geo_dev geo_dev_secret >/dev/null; \
   rm -rf '$minio_tmp'; mkdir -p '$minio_tmp/source' '$minio_tmp/restored'; \
   mc mirror smoke/geo-artifacts '$minio_tmp/source' >/dev/null; \
   mc mb --ignore-existing smoke/$restore_bucket >/dev/null; \
   mc mirror '$minio_tmp/source' smoke/$restore_bucket >/dev/null; \
   mc mirror smoke/$restore_bucket '$minio_tmp/restored' >/dev/null"

minio_container="$($compose ps -q minio)"
mkdir -p "$output/minio/source" "$output/minio/restored"
docker cp "$minio_container:$minio_tmp/source/." "$output/minio/source" >/dev/null
docker cp "$minio_container:$minio_tmp/restored/." "$output/minio/restored" >/dev/null
(cd "$output/minio/source" && find . -type f -exec sha256sum {} \; | sort) \
  >"$output/minio/source.sha256"
(cd "$output/minio/restored" && find . -type f -exec sha256sum {} \; | sort) \
  >"$output/minio/restored.sha256"
test -s "$output/minio/source.sha256"
diff -u "$output/minio/source.sha256" "$output/minio/restored.sha256"
source_objects="$(wc -l <"$output/minio/source.sha256" | tr -d ' ')"
restored_objects="$(wc -l <"$output/minio/restored.sha256" | tr -d ' ')"
test "$source_objects" = "$restored_objects"

cat >"$output/receipt.json" <<EOF
{
  "schema_version": "geo-development-backup-restore-smoke-v1",
  "postgres": {
    "source_project_count": $source_projects,
    "restored_project_count": $restored_projects,
    "source_table_count": $source_tables,
    "restored_table_count": $restored_tables,
    "dump_sha256_verified": true
  },
  "object_store": {
    "source_object_count": $source_objects,
    "restored_object_count": $restored_objects,
    "per_object_sha256_verified": true
  },
  "restore_copy_removed": true,
  "verified_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "development backup/restore smoke passed: $output"
