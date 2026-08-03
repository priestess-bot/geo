#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SOURCE_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly DEFAULT_REPO_URL="https://github.com/priestess-bot/geo.git"

INSTALL_ROOT="${GEO_INSTALL_ROOT:-${SOURCE_ROOT}}"
REPO_URL="${GEO_REPO_URL:-${DEFAULT_REPO_URL}}"
RELEASE_REF="${GEO_RELEASE_REF:-main}"
SECRET_ROOT="${GEO_SECRET_ROOT:-${INSTALL_ROOT}/.secrets}"
ENV_FILE="${GEO_STACK_ENV_FILE:-${INSTALL_ROOT}/infra/geo-stack.env}"
DIFY_ROOT="${GEO_DIFY_RUNTIME_ROOT:-${INSTALL_ROOT}/.runtime/dify-1.16.0}"
STATE_FILE="${GEO_DIFY_STATE_HOST_FILE:-${INSTALL_ROOT}/.runtime/geo-dify-state.json}"
DEEPSEEK_KEY_FILE="${GEO_DEEPSEEK_API_KEY_FILE:-}"

fail() { echo "geo install error: $*" >&2; exit 2; }

require_tools() {
  command -v git >/dev/null || fail "git is required"
  command -v docker >/dev/null || fail "docker is required"
  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
  command -v python3 >/dev/null || fail "python3 is required to create isolated keyrings"
  command -v openssl >/dev/null || fail "openssl is required to create the internal alert certificate"
  command -v uv >/dev/null || fail "uv is required for Dify workflow enrollment"
}

prepare_repo() {
  if [[ "${INSTALL_ROOT}" != "${SOURCE_ROOT}" ]]; then
    if [[ -e "${INSTALL_ROOT}" && ! -d "${INSTALL_ROOT}/.git" ]]; then
      fail "install root exists but is not a Git checkout: ${INSTALL_ROOT}"
    fi
    if [[ ! -d "${INSTALL_ROOT}/.git" ]]; then
      mkdir -p "$(dirname -- "${INSTALL_ROOT}")"
      git clone --branch "${RELEASE_REF}" --depth 1 "${REPO_URL}" "${INSTALL_ROOT}"
    else
      git -C "${INSTALL_ROOT}" fetch --depth 1 origin "${RELEASE_REF}"
      git -C "${INSTALL_ROOT}" checkout --detach "FETCH_HEAD"
    fi
  fi
  [[ -f "${INSTALL_ROOT}/infra/geo-stack.env.example" ]] || fail "canonical stack files are missing from ${INSTALL_ROOT}"
  RELEASE_SHA="$(git -C "${INSTALL_ROOT}" rev-parse HEAD)"
  [[ "${RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ]] || fail "release commit is invalid"
}

write_keyring() {
  local destination="$1"; local synthetic="$2"
  python3 - "$destination" "$synthetic" <<'PY'
import base64, json, os, pathlib, stat, sys
destination = pathlib.Path(sys.argv[1])
synthetic = sys.argv[2] == "1"
destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
def encoded(): return base64.b64encode(os.urandom(32)).decode("ascii")
if synthetic:
    value = {"schema_version": 1, "active_version": "2", "keys": {"1": encoded(), "2": encoded()}}
else:
    value = {"active_version": 2, "format": "geo-master-keyring-v1", "keys": {"1": encoded(), "2": encoded()}}
temporary = destination.with_name(destination.name + ".tmp")
temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
os.replace(temporary, destination)
PY
}

write_secret() {
  local destination="$1"; local bytes="$2"
  if [[ ! -e "${destination}" ]]; then
    openssl rand -base64 "${bytes}" | tr -d '=\n' >"${destination}"
    chmod 0600 "${destination}"
  fi
}

prepare_secrets() {
  mkdir -p "${SECRET_ROOT}" "$(dirname -- "${STATE_FILE}")"
  chmod 0700 "${SECRET_ROOT}" "$(dirname -- "${STATE_FILE}")"
  write_keyring "${SECRET_ROOT}/secret-store-keyring.json" 0
  write_keyring "${SECRET_ROOT}/provider-artifact-keyring.json" 0
  write_keyring "${SECRET_ROOT}/recommendation-artifact-keyring.json" 0
  write_keyring "${SECRET_ROOT}/workflow-c-artifact-keyring.json" 0
  write_keyring "${SECRET_ROOT}/synthetic-artifact-keyring.json" 1
  write_secret "${SECRET_ROOT}/secret-request-hash-key" 32
  write_secret "${SECRET_ROOT}/connector-artifact-key" 32
  write_secret "${SECRET_ROOT}/browser-artifact-key" 32
  write_secret "${SECRET_ROOT}/recommendation-artifact-object-store-access-key" 18
  write_secret "${SECRET_ROOT}/recommendation-artifact-object-store-secret-key" 32
  write_secret "${SECRET_ROOT}/workflow-c-artifact-reader-access-key" 18
  write_secret "${SECRET_ROOT}/workflow-c-artifact-reader-secret-key" 32
  write_secret "${SECRET_ROOT}/alert-webhook-signing-secret" 32
  if [[ ! -f "${SECRET_ROOT}/alert-webhook-ca.pem" || ! -f "${SECRET_ROOT}/alert-webhook-tls-key.pem" ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
      -keyout "${SECRET_ROOT}/alert-webhook-tls-key.pem" \
      -out "${SECRET_ROOT}/alert-webhook-ca.pem" \
      -subj "/CN=geo-internal-alert-sink" >/dev/null 2>&1
    chmod 0600 "${SECRET_ROOT}/alert-webhook-ca.pem" "${SECRET_ROOT}/alert-webhook-tls-key.pem"
  fi
  [[ -n "${DEEPSEEK_KEY_FILE}" ]] || fail "set GEO_DEEPSEEK_API_KEY_FILE before installing"
  [[ -f "${DEEPSEEK_KEY_FILE}" ]] || fail "DeepSeek key file is missing: ${DEEPSEEK_KEY_FILE}"
  chmod 0600 "${DEEPSEEK_KEY_FILE}"
}

write_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${INSTALL_ROOT}/infra/geo-stack.env.example" "${ENV_FILE}"
  fi
  chmod 0600 "${ENV_FILE}"
  python3 - "${ENV_FILE}" "${RELEASE_SHA}" "${SECRET_ROOT}" "${STATE_FILE}" "${DEEPSEEK_KEY_FILE}" <<'PY'
from pathlib import Path
import sys
path, release, secret_root, state_file, deepseek = map(Path, sys.argv[1:])
values = {
    "GEO_RELEASE_COMMIT": release.name,
    "GEO_ADMIN_ACTOR_ID": "30000000-0000-4000-8000-000000000003",
    "GEO_ADMIN_TENANT_ID": "10000000-0000-4000-8000-000000000001",
    "GEO_MODEL_GATEWAY_WORKER_SERVICE_IDENTITY_ID": "40000000-0000-4000-8000-000000000006",
    "GEO_DIFY_STATE_HOST_FILE": str(state_file),
    "GEO_DEEPSEEK_API_KEY_FILE": str(deepseek),
}
for name in (
    "GEO_SECRET_STORE_MASTER_KEYRING_FILE", "GEO_STAGING_SECRET_STORE_MASTER_KEYRING_FILE",
    "GEO_STAGING_PROVIDER_ARTIFACT_KEYRING_FILE", "GEO_STAGING_RECOMMENDATION_ARTIFACT_KEYRING_FILE",
    "GEO_STAGING_WORKFLOW_C_ARTIFACT_KEYRING_FILE", "GEO_STAGING_SYNTHETIC_ARTIFACT_KEYRING_FILE",
):
    suffix = {
        "GEO_STAGING_PROVIDER_ARTIFACT_KEYRING_FILE": "provider-artifact-keyring.json",
        "GEO_STAGING_RECOMMENDATION_ARTIFACT_KEYRING_FILE": "recommendation-artifact-keyring.json",
        "GEO_STAGING_WORKFLOW_C_ARTIFACT_KEYRING_FILE": "workflow-c-artifact-keyring.json",
        "GEO_STAGING_SYNTHETIC_ARTIFACT_KEYRING_FILE": "synthetic-artifact-keyring.json",
    }.get(name, "secret-store-keyring.json")
    values[name] = str(secret_root / suffix)
for name, suffix in {
    "GEO_SECRET_STORE_REQUEST_HASH_KEY_FILE": "secret-request-hash-key",
    "GEO_STAGING_SECRET_STORE_REQUEST_HASH_KEY_FILE": "secret-request-hash-key",
    "GEO_CONNECTOR_ARTIFACT_KEY_FILE": "connector-artifact-key",
    "GEO_BROWSER_ARTIFACT_KEY_FILE": "browser-artifact-key",
    "GEO_STAGING_RECOMMENDATION_ARTIFACT_OBJECT_STORE_ACCESS_KEY_FILE": "recommendation-artifact-object-store-access-key",
    "GEO_STAGING_RECOMMENDATION_ARTIFACT_OBJECT_STORE_SECRET_KEY_FILE": "recommendation-artifact-object-store-secret-key",
    "GEO_STAGING_WORKFLOW_C_ARTIFACT_READER_ACCESS_KEY_FILE": "workflow-c-artifact-reader-access-key",
    "GEO_STAGING_WORKFLOW_C_ARTIFACT_READER_SECRET_KEY_FILE": "workflow-c-artifact-reader-secret-key",
    "GEO_STAGING_ALERT_WEBHOOK_SIGNING_SECRET_FILE": "alert-webhook-signing-secret",
    "GEO_STAGING_ALERT_WEBHOOK_CA_FILE": "alert-webhook-ca.pem",
    "GEO_STAGING_ALERT_WEBHOOK_TLS_KEY_FILE": "alert-webhook-tls-key.pem",
}.items():
    values[name] = str(secret_root / suffix)
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
output = []
for line in lines:
    key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else ""
    if key in values:
        output.append(f"{key}={values[key]}")
        seen.add(key)
    else:
        output.append(line)
for key, value in values.items():
    if key not in seen:
        output.append(f"{key}={value}")
path.write_text("\n".join(output) + "\n", encoding="utf-8")
PY
}

main() {
  require_tools
  prepare_repo
  prepare_secrets
  write_env
  export GEO_STACK_ENV_FILE="${ENV_FILE}"
  export GEO_DIFY_RUNTIME_ROOT="${DIFY_ROOT}"
  export GEO_DIFY_STATE_HOST_FILE="${STATE_FILE}"
  "${INSTALL_ROOT}/scripts/bootstrap_dify_runtime.sh" up
  uv run python "${INSTALL_ROOT}/scripts/configure_dify_runtime.py" \
    --base-url "http://127.0.0.1:${GEO_DIFY_HOST_PORT:-15000}" \
    --state-file "${STATE_FILE}" \
    --deepseek-api-key-file "${DEEPSEEK_KEY_FILE}" \
    --manifest "${INSTALL_ROOT}/infra/dify/workflows/manifest.json"
  "${INSTALL_ROOT}/scripts/geo-stack.sh" up
  "${INSTALL_ROOT}/scripts/geo-stack.sh" doctor
  echo "GEO installed at ${INSTALL_ROOT} (commit ${RELEASE_SHA})."
  echo "Admin: http://127.0.0.1:13001"
  echo "Customer: http://127.0.0.1:13000"
  echo "Dify: http://127.0.0.1:15000"
}

main "$@"
