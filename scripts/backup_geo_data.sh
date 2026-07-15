#!/bin/sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
env_file="${1:-$repo_root/infra/production.env}"
compose_file="$repo_root/infra/compose.prod.yml"

if [ ! -f "$env_file" ]; then
  echo "backup error: production env file not found: $env_file" >&2
  exit 2
fi

set -a
. "$env_file"
set +a
: "${GEO_BACKUP_ROOT:?set GEO_BACKUP_ROOT}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
daily_dir="$GEO_BACKUP_ROOT/daily/$stamp"
mkdir -p "$daily_dir"

docker compose --env-file "$env_file" -f "$compose_file" exec -T postgres \
  sh -c 'PGPASSWORD="$(cat /run/secrets/postgres_installer_password)" pg_dump -U geo_installer -d geo --clean --if-exists --no-owner --no-privileges' \
  | gzip -9 >"$daily_dir/postgres.sql.gz"

BACKUP_STAMP="$stamp" docker compose --env-file "$env_file" -f "$compose_file" \
  --profile backup run --rm backup-object-store

sha256sum "$daily_dir/postgres.sql.gz" >"$daily_dir/SHA256SUMS"

if [ "$(date -u +%u)" = "7" ]; then
  weekly_dir="$GEO_BACKUP_ROOT/weekly/$(date -u +%G-W%V)"
  mkdir -p "$(dirname "$weekly_dir")"
  rm -rf "$weekly_dir"
  cp -a "$daily_dir" "$weekly_dir"
fi

find "$GEO_BACKUP_ROOT/daily" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
find "$GEO_BACKUP_ROOT/weekly" -mindepth 1 -maxdepth 1 -type d -mtime +28 -exec rm -rf {} +

echo "backup complete: $daily_dir"
