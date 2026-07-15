#!/bin/sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
env_file="${1:-$repo_root/infra/production.env}"
backup_file="${2:-}"
compose_file="$repo_root/infra/compose.prod.yml"

if [ ! -f "$env_file" ]; then
  echo "restore smoke error: production env file not found: $env_file" >&2
  exit 2
fi
if [ -z "$backup_file" ] || [ ! -f "$backup_file" ]; then
  echo "usage: $0 [production.env] POSTGRES_BACKUP.sql.gz" >&2
  exit 2
fi

cleanup() {
  docker compose --env-file "$env_file" -f "$compose_file" --profile restore-smoke \
    rm -sf restore-smoke-postgres >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker compose --env-file "$env_file" -f "$compose_file" --profile restore-smoke \
  up -d --wait restore-smoke-postgres
gunzip -c "$backup_file" | docker compose --env-file "$env_file" -f "$compose_file" \
  exec -T restore-smoke-postgres sh -c \
  'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" psql -v ON_ERROR_STOP=1 -U geo_restore -d geo_restore_smoke'
docker compose --env-file "$env_file" -f "$compose_file" exec -T restore-smoke-postgres \
  sh -c 'PGPASSWORD="$(cat /run/secrets/restore_smoke_password)" psql -At -U geo_restore -d geo_restore_smoke -c "SELECT count(*) > 0 FROM pg_catalog.pg_tables"' \
  | grep -qx t

echo "restore smoke passed: $backup_file"
