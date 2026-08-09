#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly MANIFEST="${REPO_ROOT}/infra/geo-stack-manifest.json"

STACK_PROJECT="${GEO_STACK_PROJECT:-geo}"
STACK_MODE="${GEO_STACK_MODE:-internal}"
case "${STACK_MODE}" in
  internal)
    STACK_ENV_FILE="${GEO_STACK_ENV_FILE:-${REPO_ROOT}/infra/geo-stack.env}"
    COMPOSE_FILES=(
      "${REPO_ROOT}/infra/docker-compose.yml"
      "${REPO_ROOT}/infra/compose.staging-operator.yml"
      "${REPO_ROOT}/infra/dify/compose.geo-runtime.yml"
    )
    PROFILES=(workers connectors browser-capture)
    ;;
  production)
    STACK_ENV_FILE="${GEO_STACK_ENV_FILE:-${REPO_ROOT}/infra/production.env}"
    COMPOSE_FILES=(
      "${REPO_ROOT}/infra/compose.prod.yml"
      "${REPO_ROOT}/infra/compose.style-collection.yml"
      "${REPO_ROOT}/infra/compose.connector.yml"
      "${REPO_ROOT}/infra/compose.browser-capture.yml"
      "${REPO_ROOT}/infra/dify/compose.production-runtime.yml"
    )
    PROFILES=()
    ;;
  *)
    echo "geo-stack error: GEO_STACK_MODE must be internal or production" >&2
    exit 2
    ;;
esac
DIFY_SCRIPT="${GEO_DIFY_SCRIPT:-${REPO_ROOT}/scripts/bootstrap_dify_runtime.sh}"

usage() {
  cat <<'EOF'
usage: scripts/geo-stack.sh <command> [options]

Commands:
  config       Validate the canonical Compose bundle.
  up           Start the canonical GEO + Dify stack for GEO_STACK_MODE.
  down         Stop the stack; add --volumes to remove canonical GEO volumes.
  status       Show GEO and Dify service status.
  logs         Follow GEO service logs (pass service names after --).
  doctor       Check the canonical project, ports, health and legacy projects.
  release-info Write a non-secret Git/Compose/image release receipt.
  cleanup-legacy
              Stop manifest-listed legacy GEO projects. Add --delete-volumes
              only after a verified migration package exists.
  export       Delegate to scripts/geo_migrate.py export.
  import       Delegate to scripts/geo_migrate.py import.
  verify       Decrypt and validate a migration package without restoring it.
EOF
}

require_tools() {
  command -v docker >/dev/null || { echo "geo-stack error: docker is required" >&2; exit 2; }
  command -v python3 >/dev/null || { echo "geo-stack error: python3 is required" >&2; exit 2; }
  docker compose version >/dev/null 2>&1 || {
    echo "geo-stack error: Docker Compose v2 is required" >&2
    exit 2
  }
}

manifest_legacy_projects() {
  python3 - "${MANIFEST}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
projects = payload.get("legacy_projects")
if not isinstance(projects, list) or not all(isinstance(item, str) and item for item in projects):
    raise SystemExit("geo-stack error: manifest legacy_projects is invalid")
print(*projects, sep="\n")
PY
}

run_dify() {
  require_env
  local serialized
  serialized="$(python3 - "${STACK_ENV_FILE}" <<'PY'
import pathlib
import re
import sys

assignment = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
for raw_line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#"):
        continue
    match = assignment.fullmatch(line)
    if match is None or not match.group(1).startswith("GEO_DIFY_"):
        continue
    value = match.group(2).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    print(f"{match.group(1)}={value}")
PY
)" || { echo "geo-stack error: failed to read Dify settings from ${STACK_ENV_FILE}" >&2; exit 2; }
  local -a dify_environment=()
  if [[ -n "${serialized}" ]]; then
    mapfile -t dify_environment <<<"${serialized}"
  fi
  env "${dify_environment[@]}" "${DIFY_SCRIPT}" "$@"
}

require_env() {
  [[ -f "${STACK_ENV_FILE}" ]] || {
    echo "geo-stack error: env file is missing: ${STACK_ENV_FILE}" >&2
    if [[ "${STACK_MODE}" == "production" ]]; then
      echo "copy infra/production.env.example, then configure reviewed OIDC, image digests and Secret files" >&2
    else
      echo "copy infra/geo-stack.env.example and set absolute secret paths" >&2
    fi
    exit 2
  }
}

run_compose() {
  local -a command=(docker compose --project-name "${STACK_PROJECT}" --env-file "${STACK_ENV_FILE}")
  local compose_file
  for compose_file in "${COMPOSE_FILES[@]}"; do
    command+=(-f "${compose_file}")
  done
  command+=("${@}")
  "${command[@]}"
}

run_with_profiles() {
  local -a command=()
  local profile
  for profile in "${PROFILES[@]}"; do
    command+=(--profile "${profile}")
  done
  command+=("${@}")
  run_compose "${command[@]}"
}

production_preflight() {
  [[ "${STACK_MODE}" != "production" ]] || \
    uv run python "${REPO_ROOT}/scripts/production_preflight.py" --env-file "${STACK_ENV_FILE}"
}

release_info() {
  require_env
  local output="${REPO_ROOT}/.runtime/geo-release-receipt.json"
  local require_running=0
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --output)
        [[ -n "${2:-}" ]] || { echo "geo-stack error: --output requires a path" >&2; exit 2; }
        output="$2"
        shift
        ;;
      --require-running) require_running=1 ;;
      *) echo "geo-stack error: unsupported release-info option: $1" >&2; exit 2 ;;
    esac
    shift
  done
  local -a command=(uv run python "${REPO_ROOT}/scripts/geo_release_receipt.py"
    --repo-root "${REPO_ROOT}"
    --mode "${STACK_MODE}"
    --project "${STACK_PROJECT}"
    --dify-project "geo-dify"
    --env-file "${STACK_ENV_FILE}"
    --output "${output}")
  local compose_file
  for compose_file in "${COMPOSE_FILES[@]}"; do
    command+=(--compose-file "${compose_file}")
  done
  [[ "${require_running}" == 1 ]] && command+=(--require-running)
  "${command[@]}"
}

ensure_dify_network() {
  docker network inspect geo-dify-runtime >/dev/null 2>&1 || docker network create geo-dify-runtime >/dev/null
}

canonical_config() {
  require_env
  production_preflight
  run_with_profiles config -q
}

canonical_up() {
  canonical_config
  ensure_dify_network
  run_dify up
  run_with_profiles up -d --build
  run_compose ps
}

canonical_down() {
  require_env
  local remove_volumes=""
  if [[ "${1:-}" == "--volumes" ]]; then
    remove_volumes="-v"
  elif [[ -n "${1:-}" ]]; then
    echo "geo-stack error: unsupported down option: $1" >&2
    exit 2
  fi
  run_with_profiles down --remove-orphans ${remove_volumes:+$remove_volumes}
  run_dify down
}

canonical_status() {
  require_env
  run_compose ps
  run_dify status
}

canonical_logs() {
  require_env
  if [[ "${1:-}" == "--" ]]; then shift; fi
  if [[ "$#" -eq 0 ]]; then
    run_compose logs --tail=100 -f
  else
    run_compose logs --tail=100 -f "$@"
  fi
}

doctor() {
  require_env
  canonical_config
  local bad=0
  local project
  local legacy_projects_output
  legacy_projects_output="$(manifest_legacy_projects)" || exit 2
  while IFS= read -r project; do
    [[ -n "$project" && "$project" != "${STACK_PROJECT}" ]] || continue
    if docker ps --filter "label=com.docker.compose.project=${project}" --format '{{.ID}}' | grep -q .; then
      echo "legacy runtime detected: ${project}" >&2
      bad=1
    fi
  done <<<"${legacy_projects_output}"
  echo "canonical project: ${STACK_PROJECT}"
  echo "stack mode: ${STACK_MODE}"
  echo "env file: ${STACK_ENV_FILE}"
  run_compose ps --status running
  if run_compose exec -T internal-api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read()" \
    >/dev/null 2>&1; then
    echo "internal api health: ok"
  else
    echo "internal api health: unavailable" >&2
    bad=1
  fi
  local dify_port="${GEO_DIFY_HOST_PORT:-15000}"
  if curl --silent --show-error --max-time 5 -o /dev/null \
    -w '%{http_code}' "http://127.0.0.1:${dify_port}/console/api/setup" | grep -qx '200'; then
    echo "dify setup endpoint: ok"
  else
    echo "dify setup endpoint: unavailable" >&2
    bad=1
  fi
  local dify_root_status
  dify_root_status="$(curl --silent --show-error --max-time 5 -o /dev/null \
    -w '%{http_code}' "http://127.0.0.1:${dify_port}/")" || dify_root_status="000"
  if [[ "$dify_root_status" =~ ^(200|301|302|307|308)$ ]]; then
    echo "dify web endpoint: ok (${dify_root_status})"
  else
    echo "dify web endpoint: unavailable (${dify_root_status})" >&2
    bad=1
  fi
  return "$bad"
}

cleanup_legacy() {
  require_env
  local delete_volumes=0
  local confirmed=0
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --delete-volumes) delete_volumes=1 ;;
      --confirm) confirmed=1 ;;
      *) echo "geo-stack error: unsupported cleanup option: $1" >&2; exit 2 ;;
    esac
    shift
  done
  [[ "$confirmed" == 1 ]] || {
    echo "cleanup requires --confirm; no containers or volumes were changed" >&2
    exit 2
  }
  if [[ "$delete_volumes" == 1 ]]; then
    [[ -n "${GEO_MIGRATION_PACKAGE:-}" && -e "${GEO_MIGRATION_PACKAGE}" ]] || {
      echo "cleanup error: GEO_MIGRATION_PACKAGE must point to a migration package before deleting volumes" >&2
      exit 2
    }
    [[ -n "${GEO_MIGRATION_KEY_FILE:-${GEO_SYNC_PASSPHRASE_FILE:-}}" ]] || {
      echo "cleanup error: GEO_MIGRATION_KEY_FILE (or GEO_SYNC_PASSPHRASE_FILE) is required for full encrypted-package verification" >&2
      exit 2
    }
    local migration_package_path="${GEO_MIGRATION_PACKAGE}"
    local migration_package_dir
    if [[ -f "${migration_package_path}" ]]; then
      [[ "$(basename -- "${migration_package_path}")" == "manifest.json" ]] || {
        echo "cleanup error: GEO_MIGRATION_PACKAGE must be a package directory or its manifest.json" >&2
        exit 2
      }
      migration_package_dir="$(CDPATH= cd -- "$(dirname -- "${migration_package_path}")" && pwd)"
    elif [[ -d "${migration_package_path}" && -f "${migration_package_path}/manifest.json" ]]; then
      migration_package_dir="$(CDPATH= cd -- "${migration_package_path}" && pwd)"
    else
      echo "cleanup error: GEO_MIGRATION_PACKAGE has no manifest.json" >&2
      exit 2
    fi
    command -v uv >/dev/null || {
      echo "cleanup error: uv is required to run the full geo_migrate verification" >&2
      exit 2
    }
    uv run python "${REPO_ROOT}/scripts/geo_migrate.py" verify \
      --repo-root "${REPO_ROOT}" \
      --package "${migration_package_dir}" \
      --encryption-key-file "${GEO_MIGRATION_KEY_FILE:-${GEO_SYNC_PASSPHRASE_FILE}}" \
      --require-current-schema \
      --write-receipt
    python3 - "${migration_package_dir}" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

CURRENT_SCHEMA = "geo-runtime-migration-v2"
RECEIPT_SCHEMA = "geo-runtime-migration-verification-receipt-v1"
package = Path(sys.argv[1]).resolve()
manifest_path = package / "manifest.json"
receipt_path = package / "verification-receipt.json"

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"cleanup error: verification receipt is unreadable: {error}") from error
if manifest.get("schema_version") != CURRENT_SCHEMA or manifest.get("status") != "verified-export":
    raise SystemExit("cleanup error: package is not a current verified GEO runtime export")
payload = manifest.get("payload")
identity = manifest.get("identity_bindings")
if not isinstance(payload, dict) or not isinstance(identity, dict):
    raise SystemExit("cleanup error: package has no payload or identity binding contract")
if receipt.get("schema_version") != RECEIPT_SCHEMA or receipt.get("status") != "verified-package":
    raise SystemExit("cleanup error: verification receipt is not a verified-package receipt")
if receipt.get("current_schema") != CURRENT_SCHEMA or receipt.get("migration_schema") != manifest.get("schema_version"):
    raise SystemExit("cleanup error: verification receipt is not bound to the current migration schema")
if receipt.get("manifest_sha256") != sha256(manifest_path):
    raise SystemExit("cleanup error: verification receipt does not match manifest hash")
if receipt.get("payload_sha256") != payload.get("sha256"):
    raise SystemExit("cleanup error: verification receipt does not match encrypted payload hash")
identity_hash = hashlib.sha256(canonical(identity)).hexdigest()
if receipt.get("identity_bindings_sha256") != identity_hash:
    raise SystemExit("cleanup error: verification receipt does not match identity bindings")
print("cleanup verification receipt: current schema, encrypted payload hash, and identity bindings verified")
PY
  fi
  local project
  local legacy_projects_output
  legacy_projects_output="$(manifest_legacy_projects)" || exit 2
  while IFS= read -r project; do
    [[ -n "$project" && "$project" != "${STACK_PROJECT}" ]] || continue
    local -a running_ids=()
    local -a container_ids=()
    local -a network_ids=()
    local -a volume_names=()
    mapfile -t running_ids < <(docker ps -q --filter "label=com.docker.compose.project=${project}")
    mapfile -t container_ids < <(docker ps -aq --filter "label=com.docker.compose.project=${project}")
    ((${#running_ids[@]} == 0)) || docker stop "${running_ids[@]}" >/dev/null
    ((${#container_ids[@]} == 0)) || docker rm "${container_ids[@]}" >/dev/null
    mapfile -t network_ids < <(docker network ls -q --filter "label=com.docker.compose.project=${project}")
    ((${#network_ids[@]} == 0)) || docker network rm "${network_ids[@]}" >/dev/null
    if [[ "$delete_volumes" == 1 ]]; then
      mapfile -t volume_names < <(docker volume ls -q --filter "label=com.docker.compose.project=${project}")
      ((${#volume_names[@]} == 0)) || docker volume rm "${volume_names[@]}" >/dev/null
    fi
    if docker ps -aq --filter "label=com.docker.compose.project=${project}" | grep -q .; then
      echo "cleanup error: containers remain for ${project}" >&2
      exit 1
    fi
  done <<<"${legacy_projects_output}"
  local result="legacy GEO runtimes stopped"
  if [[ "$delete_volumes" == 1 ]]; then
    result+=" and volumes removed"
  fi
  echo "$result"
}

delegate_migration() {
  local command="$1"
  shift
  if [[ "$command" == "import" ]]; then
    require_env
    ensure_dify_network
    run_dify up
    # Keep the application image available for the post-restore Secret Store
    # canary; its dependencies still gate on migration and MinIO bootstrap.
    run_with_profiles up -d postgres minio valkey internal-api
  fi
  local identity_env_option=()
  if [[ "$command" == "export" ]]; then
    identity_env_option=(--source-env-file "${STACK_ENV_FILE}")
  elif [[ "$command" == "import" ]]; then
    identity_env_option=(--target-env-file "${STACK_ENV_FILE}")
  fi
  exec uv run python "${REPO_ROOT}/scripts/geo_migrate.py" "$command" \
    --repo-root "${REPO_ROOT}" "${identity_env_option[@]}" "$@"
}

main() {
  require_tools
  local command="${1:-}"
  shift || true
  case "$command" in
    config) canonical_config ;;
    up) canonical_up ;;
    down) canonical_down "$@" ;;
    status) canonical_status ;;
    logs) canonical_logs "$@" ;;
    doctor) doctor ;;
    release-info) release_info "$@" ;;
    cleanup-legacy) cleanup_legacy "$@" ;;
    export|import|verify) delegate_migration "$command" "$@" ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

main "$@"
