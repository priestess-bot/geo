#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

repo_root="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
output_root="${1:-$repo_root/artifacts/backup-restore-smoke-authenticated}"
tmpfs_root="${GEO_DEVELOPMENT_RESTORE_TMPFS_ROOT:-/dev/shm}"
if [[ ! -d "$tmpfs_root" || -L "$tmpfs_root" \
  || "$(stat -f -c '%T' -- "$tmpfs_root")" != "tmpfs" ]]; then
  echo "restore Gate error: isolated key and plaintext staging must be tmpfs" >&2
  exit 2
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
nonce="$(uv run python -c 'import secrets; print(secrets.token_hex(5))')"
compose_project="geo-restore-gate-${nonce}"
# This gate must never share the developer stack's named volumes or fixed host
# ports.  A fresh Compose project makes the five canonical source buckets safe
# to create and lets the script prove cleanup without inspecting user data.
export GEO_POSTGRES_HOST_PORT="127.0.0.1:0"
export GEO_MINIO_HOST_PORT="127.0.0.1:0"
export GEO_MINIO_CONSOLE_HOST_PORT="127.0.0.1:0"
compose=(
  docker compose --project-name "$compose_project"
  -f "$repo_root/infra/docker-compose.yml"
)
source_database="geo_restore_gate_${stamp//[^[:alnum:]]/_}_${nonce}"
source_database="${source_database,,}"
source_bucket="geo-artifacts"
recommendation_source_bucket="geo-restricted-recommendation-artifacts"
workflow_c_source_bucket="geo-restricted-workflow-c-artifacts"
synthetic_raw_source_bucket="geo-synthetic-style-raw"
synthetic_derived_source_bucket="geo-synthetic-style-derived"
keyring_root="$(mktemp -d "$tmpfs_root/geo-restore-gate-keys.XXXXXXXX")"
chmod 0700 "$keyring_root"
seed_receipt="$keyring_root/seed-receipt.json"
smoke_log="$keyring_root/smoke.log"
source_database_created=0
source_buckets_created=0
compose_started=0
cleanup_complete=0

cleanup() {
  if [[ "$source_database_created" == "1" ]]; then
    "${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 \
      -U geo_installer -d postgres \
      -c "DROP DATABASE IF EXISTS $source_database WITH (FORCE)" \
      >/dev/null 2>&1 || true
  fi
  if [[ "$source_buckets_created" == "1" ]]; then
    "${compose[@]}" exec -T \
      -e "GATE_BUCKETS=$source_bucket $recommendation_source_bucket $workflow_c_source_bucket $synthetic_raw_source_bucket $synthetic_derived_source_bucket" \
      minio sh -ceu \
      'mc alias set gate http://127.0.0.1:9000 geo_dev geo_dev_secret >/dev/null 2>&1; for bucket in $GATE_BUCKETS; do mc rm --recursive --force "gate/$bucket" >/dev/null 2>&1 || true; mc rb "gate/$bucket" >/dev/null 2>&1 || true; done' \
      >/dev/null 2>&1 || true
  fi
  if [[ "$compose_started" == "1" ]]; then
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf -- "$keyring_root"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"${compose[@]}" up -d --wait postgres minio >/dev/null
compose_started=1
head_revision="$(uv run python scripts/backup_restore_gate_seed.py head)"
if [[ ! "$head_revision" =~ ^[0-9]{4}_[a-z0-9_]+$ ]]; then
  echo "restore Gate error: Alembic head is invalid" >&2
  exit 2
fi
postgres_endpoint="$("${compose[@]}" port postgres 5432 | tail -n 1)"
minio_endpoint="$("${compose[@]}" port minio 9000 | tail -n 1)"
postgres_port="${postgres_endpoint##*:}"
minio_port="${minio_endpoint##*:}"
if [[ ! "$postgres_port" =~ ^[0-9]{1,5}$ || ! "$minio_port" =~ ^[0-9]{1,5}$ ]]; then
  echo "restore Gate error: development infrastructure ports are unavailable" >&2
  exit 2
fi

"${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 \
  -U geo_installer -d postgres -c "CREATE DATABASE $source_database" >/dev/null
source_database_created=1
uv run python scripts/backup_restore_gate_seed.py create-keyrings \
  --directory "$keyring_root"
database_url="postgresql://geo_installer:geo_installer_dev@127.0.0.1:$postgres_port/$source_database"
"${compose[@]}" exec -T \
  -e "GATE_BUCKETS=$source_bucket $recommendation_source_bucket $workflow_c_source_bucket $synthetic_raw_source_bucket $synthetic_derived_source_bucket" \
  minio sh -ceu \
  'mc alias set gate http://127.0.0.1:9000 geo_dev geo_dev_secret >/dev/null; for bucket in $GATE_BUCKETS; do if mc stat "gate/$bucket" >/dev/null 2>&1; then echo "restore Gate error: isolated source bucket already exists: $bucket" >&2; exit 60; fi; done'
source_buckets_created=1
"${compose[@]}" exec -T \
  -e "GATE_BUCKETS=$source_bucket $recommendation_source_bucket $workflow_c_source_bucket $synthetic_raw_source_bucket $synthetic_derived_source_bucket" \
  minio sh -ceu \
  'mc alias set gate http://127.0.0.1:9000 geo_dev geo_dev_secret >/dev/null; for bucket in $GATE_BUCKETS; do mc mb "gate/$bucket" >/dev/null; done'
uv run python scripts/backup_restore_gate_seed.py seed \
  --database-url "$database_url" \
  --expected-head "$head_revision" \
  --object-store-endpoint "http://127.0.0.1:$minio_port" \
  --object-store-bucket "$source_bucket" \
  --recommendation-object-store-bucket "$recommendation_source_bucket" \
  --workflow-c-object-store-bucket "$workflow_c_source_bucket" \
  --synthetic-raw-object-store-bucket "$synthetic_raw_source_bucket" \
  --synthetic-derived-object-store-bucket "$synthetic_derived_source_bucket" \
  --keyring-directory "$keyring_root" >"$seed_receipt"
chmod 0600 "$seed_receipt"
uv run python - "$seed_receipt" "$head_revision" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="ascii"))
assert payload["schema_version"] == "geo-authenticated-restore-gate-seed-v1"
assert payload["alembic_head"] == sys.argv[2]
assert payload["key_version_counts"] == {
    "provider": 2,
    "secret_referenced": 2,
    "secret_store": 2,
    "synthetic": 2,
}
assert payload["provider_artifacts"] == {
    "active_dek_count": 2,
    "committed_artifact_count": 2,
}
assert payload["synthetic_artifacts"] == {
    "active_dek_count": 1,
    "nondeleted_artifact_count": 2,
    "tier_key_artifact_count": 1,
}
assert payload["recommendation_artifacts"] == {
    "active_master_key_version": 2,
    "artifact_lineage_count": 1,
    "master_key_version_count": 2,
    "representative_artifact_verified": True,
}
assert payload["workflow_c_artifacts"] == {
    "active_dek_count": 1,
    "master_key_version_count": 2,
    "recoverable_artifact_count": 1,
    "representative_artifact_verified": True,
}
canary = payload["secret_runtime_canary"]
assert set(canary) == {
    "idempotency_key", "project_id", "purpose", "reference_id",
    "service_identity_id", "version",
}
assert canary["purpose"] == "model_provider.openai"
assert canary["version"] == 1
PY

mapfile -t secret_runtime_canary < <(uv run python - "$seed_receipt" <<'PY'
import json
from pathlib import Path
import sys

canary = json.loads(Path(sys.argv[1]).read_text(encoding="ascii"))["secret_runtime_canary"]
for field in (
    "service_identity_id", "reference_id", "project_id", "purpose", "version",
    "idempotency_key",
):
    print(canary[field])
PY
)
if [[ "${#secret_runtime_canary[@]}" != "6" ]]; then
  echo "restore Gate error: frozen Secret Store runtime canary is unavailable" >&2
  exit 2
fi

if [[ -L "$output_root" ]]; then
  echo "restore Gate error: smoke output root cannot be a symlink" >&2
  exit 2
fi
install -d -m 0700 "$output_root"
output_root="$(realpath -e -- "$output_root")"
GEO_DEVELOPMENT_BACKUP_SOURCE_DATABASE="$source_database" \
GEO_DEVELOPMENT_BACKUP_SOURCE_BUCKET="$source_bucket" \
GEO_DEVELOPMENT_RECOMMENDATION_BACKUP_SOURCE_BUCKET="$recommendation_source_bucket" \
GEO_DEVELOPMENT_WORKFLOW_C_BACKUP_SOURCE_BUCKET="$workflow_c_source_bucket" \
GEO_DEVELOPMENT_SYNTHETIC_RAW_BACKUP_SOURCE_BUCKET="$synthetic_raw_source_bucket" \
GEO_DEVELOPMENT_SYNTHETIC_DERIVED_BACKUP_SOURCE_BUCKET="$synthetic_derived_source_bucket" \
GEO_DEVELOPMENT_SECRET_STORE_MASTER_KEYRING_FILE="$keyring_root/secret-store-keyring.json" \
GEO_DEVELOPMENT_SECRET_STORE_REQUEST_HASH_KEY_FILE="$keyring_root/secret-request-hash-key" \
GEO_DEVELOPMENT_PROVIDER_ARTIFACT_KEYRING_FILE="$keyring_root/provider-artifact-keyring.json" \
GEO_DEVELOPMENT_SYNTHETIC_ARTIFACT_KEYRING_FILE="$keyring_root/synthetic-artifact-keyring.json" \
GEO_DEVELOPMENT_RECOMMENDATION_ARTIFACT_KEYRING_FILE="$keyring_root/recommendation-artifact-keyring.json" \
GEO_DEVELOPMENT_WORKFLOW_C_ARTIFACT_KEYRING_FILE="$keyring_root/workflow-c-artifact-keyring.json" \
GEO_DEVELOPMENT_RESTORE_SECRET_SERVICE_IDENTITY_ID="${secret_runtime_canary[0]}" \
GEO_DEVELOPMENT_RESTORE_SECRET_REFERENCE_ID="${secret_runtime_canary[1]}" \
GEO_DEVELOPMENT_RESTORE_SECRET_PROJECT_ID="${secret_runtime_canary[2]}" \
GEO_DEVELOPMENT_RESTORE_SECRET_PURPOSE="${secret_runtime_canary[3]}" \
GEO_DEVELOPMENT_RESTORE_SECRET_VERSION="${secret_runtime_canary[4]}" \
GEO_DEVELOPMENT_RESTORE_SECRET_IDEMPOTENCY_KEY="${secret_runtime_canary[5]}" \
GEO_DEVELOPMENT_RESTORE_TMPFS_ROOT="$tmpfs_root" \
GEO_DEVELOPMENT_RESTORE_COMPOSE_PROJECT="$compose_project" \
  scripts/backup_restore_development_smoke.sh "$output_root" | tee "$smoke_log"
smoke_output="$(sed -n 's/^development authenticated backup\/restore smoke passed: //p' "$smoke_log")"
if [[ -z "$smoke_output" || -L "$smoke_output" || ! -d "$smoke_output" ]]; then
  echo "restore Gate error: smoke evidence directory is unavailable" >&2
  exit 2
fi
smoke_output="$(realpath -e -- "$smoke_output")"
case "$smoke_output" in
  "$output_root"/*) ;;
  *) echo "restore Gate error: smoke evidence escaped its output root" >&2; exit 2 ;;
esac
uv run python scripts/scan_backup_plaintext_artifacts.py "$smoke_output" >/dev/null
if rg -a -F -e 'RESTORE-GATE-SECRET-V1-DO-NOT-PERSIST-4171' \
  -e 'RESTORE-GATE-SECRET-V2-DO-NOT-PERSIST-6283' \
  -e 'RESTORE-GATE-PROVIDER-SECRET-DO-NOT-PERSIST-9347' "$smoke_output" >/dev/null; then
  echo "restore Gate error: plaintext Secret marker reached persistent evidence" >&2
  exit 2
fi
uv run python - "$smoke_output/receipt.json" "$head_revision" <<'PY'
import json
from pathlib import Path
import sys

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="ascii"))
assert receipt["schema_version"] == "geo-development-backup-restore-smoke-v6"
assert receipt["encrypted_bundle"] is True
assert receipt["ephemeral_backup_key_destroyed"] is True
assert receipt["restore_copy_removed"] is True
assert all(receipt["negative_key_tests"].values())
restored = receipt["production_equivalent_restore_receipt"]
assert restored["schema_version"] == "geo-production-backup-restore-v6"
assert restored["postgres"]["migration_revision"] == sys.argv[2]
assert restored["secret_store"]["verified_key_versions"] == [1, 2]
assert restored["secret_store"]["representative_secret_count"] == 2
assert restored["provider_artifacts"]["verified_master_key_versions"] == [1, 2]
assert restored["provider_artifacts"]["representative_artifact_verified"] is True
assert restored["synthetic_artifacts"]["verified_master_key_versions"] == ["1", "2"]
assert restored["synthetic_artifacts"]["restricted_representative_verified"] is True
assert restored["synthetic_artifacts"]["tier_representative_verified"] is True
assert restored["recommendation_artifacts"]["verified_master_key_versions"] == [1, 2]
assert restored["recommendation_artifacts"]["artifact_lineage_count"] == 1
assert restored["recommendation_artifacts"]["representative_artifact_verified"] is True
assert restored["workflow_c_artifacts"]["verified_master_key_versions"] == [1, 2]
assert restored["workflow_c_artifacts"]["active_dek_count"] == 1
assert restored["workflow_c_artifacts"]["recoverable_artifact_count"] == 1
assert restored["workflow_c_artifacts"]["representative_artifact_verified"] is True
PY

"${compose[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 \
  -U geo_installer -d postgres \
  -c "DROP DATABASE $source_database WITH (FORCE)" >/dev/null
source_database_created=0
database_remaining="$("${compose[@]}" exec -T postgres psql -X -At \
  -U geo_installer -d postgres \
  -c "SELECT count(*) FROM pg_database WHERE datname = '$source_database'")"
[[ "$database_remaining" == "0" ]]
"${compose[@]}" exec -T \
  -e "GATE_BUCKETS=$source_bucket $recommendation_source_bucket $workflow_c_source_bucket $synthetic_raw_source_bucket $synthetic_derived_source_bucket" \
  minio sh -ceu \
  'mc alias set gate http://127.0.0.1:9000 geo_dev geo_dev_secret >/dev/null; for bucket in $GATE_BUCKETS; do mc rm --recursive --force "gate/$bucket" >/dev/null; mc rb "gate/$bucket" >/dev/null; if mc stat "gate/$bucket" >/dev/null 2>&1; then exit 70; fi; done'
source_buckets_created=0
"${compose[@]}" down --volumes --remove-orphans >/dev/null
compose_started=0
rm -rf -- "$keyring_root"
[[ ! -e "$keyring_root" ]]
cleanup_complete=1

echo "authenticated restore Gate passed: head=$head_revision evidence=$smoke_output cleanup=$cleanup_complete"
