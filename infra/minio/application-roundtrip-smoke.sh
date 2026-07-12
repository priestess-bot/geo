#!/bin/sh
set -eu

export MC_CONFIG_DIR="${MC_CONFIG_DIR:-/tmp/geno-application-roundtrip-mc}"
trap 'rm -rf "$MC_CONFIG_DIR" /tmp/geno-application-roundtrip' EXIT
mkdir -p /tmp/geno-application-roundtrip "${OBJECT_STORE_RECEIPT_DIR:-/receipts}"

access_key="$(cat "${OBJECT_STORE_ACCESS_KEY_FILE:-/run/secrets/object_store_application_access_key}")"
secret_key="$(cat "${OBJECT_STORE_SECRET_KEY_FILE:-/run/secrets/object_store_application_secret_key}")"
endpoint="${OBJECT_STORE_ENDPOINT:-http://minio:9000}"
bucket="${OBJECT_STORE_BUCKET:-geno-reports}"
run_id="${OBJECT_STORE_SMOKE_RUN_ID:?set OBJECT_STORE_SMOKE_RUN_ID}"

until mc alias set application "$endpoint" "$access_key" "$secret_key" >/dev/null 2>&1; do
  sleep 1
done

fingerprint_file=/tmp/geno-application-roundtrip/access-key
printf '%s' "$access_key" > "$fingerprint_file"
set -- $(sha256sum "$fingerprint_file")
credential_fingerprint="$1"
receipt="${OBJECT_STORE_RECEIPT_DIR:-/receipts}/shared-identity-roundtrip.json"
payload=/tmp/geno-application-roundtrip/shared-identity.txt
restored=/tmp/geno-application-roundtrip/shared-identity-restored.txt
key="production-readiness/$run_id/shared-identity.txt"
printf 'geno shared application identity policy run=%s\n' "$run_id" > "$payload"
set -- $(sha256sum "$payload")
source_hash="$1"
mc cp "$payload" "application/$bucket/$key" >/dev/null
mc stat "application/$bucket/$key" >/dev/null
mc cp "application/$bucket/$key" "$restored" >/dev/null
set -- $(sha256sum "$restored")
restored_hash="$1"
test "$source_hash" = "$restored_hash"

verified_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{"schema_version":"production-object-store-shared-identity-roundtrip-v1","verification_scope":"shared_identity_policy_only","credential_fingerprint":"%s","status":"pass","sha256":"%s","execution_path":"minio-mc-file-secret","verified_at":"%s"}\n' "$credential_fingerprint" "$restored_hash" "$verified_at" > "$receipt"
echo "Shared application identity roundtrip passed: receipt=$receipt"
