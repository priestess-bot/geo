#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
readonly MANIFEST="${REPO_ROOT}/infra/geo-stack-manifest.json"

STACK_PROJECT="${GEO_STACK_PROJECT:-geo}"
STACK_ENV_FILE="${GEO_STACK_ENV_FILE:-${REPO_ROOT}/infra/geo-stack.env}"
DIFY_SCRIPT="${GEO_DIFY_SCRIPT:-${REPO_ROOT}/scripts/bootstrap_dify_runtime.sh}"
PROFILES=(workers connectors browser-capture)

usage() {
  cat <<'EOF'
usage: scripts/geo-stack.sh <command> [options]

Commands:
  config       Validate the canonical Compose bundle.
  up           Start the canonical internal GEO + Dify stack.
  down         Stop the stack; add --volumes to remove canonical GEO volumes.
  status       Show GEO and Dify service status.
  logs         Follow GEO service logs (pass service names after --).
  doctor       Check the canonical project, ports, health and legacy projects.
  cleanup-legacy
              Stop geo-development/geo-advinsys-staging. Add --delete-volumes
              only after a verified migration package exists.
  export       Delegate to scripts/geo_migrate.py export.
  import       Delegate to scripts/geo_migrate.py import.
  verify       Decrypt and validate a migration package without restoring it.
EOF
}

require_tools() {
  command -v docker >/dev/null || { echo "geo-stack error: docker is required" >&2; exit 2; }
  docker compose version >/dev/null 2>&1 || {
    echo "geo-stack error: Docker Compose v2 is required" >&2
    exit 2
  }
}

require_env() {
  [[ -f "${STACK_ENV_FILE}" ]] || {
    echo "geo-stack error: env file is missing: ${STACK_ENV_FILE}" >&2
    echo "copy infra/geo-stack.env.example and set absolute secret paths" >&2
    exit 2
  }
}

compose_args() {
  printf '%s\0' docker compose
  printf '%s\0' --project-name "${STACK_PROJECT}"
  printf '%s\0' --env-file "${STACK_ENV_FILE}"
  printf '%s\0' -f "${REPO_ROOT}/infra/docker-compose.yml"
  printf '%s\0' -f "${REPO_ROOT}/infra/compose.staging-operator.yml"
  printf '%s\0' -f "${REPO_ROOT}/infra/dify/compose.geo-runtime.yml"
}

run_compose() {
  local -a command=(docker compose --project-name "${STACK_PROJECT}" --env-file "${STACK_ENV_FILE}"
    -f "${REPO_ROOT}/infra/docker-compose.yml"
    -f "${REPO_ROOT}/infra/compose.staging-operator.yml"
    -f "${REPO_ROOT}/infra/dify/compose.geo-runtime.yml")
  command+=("${@}")
  "${command[@]}"
}

run_with_profiles() {
  local -a command=(--profile "${PROFILES[0]}" --profile "${PROFILES[1]}" --profile "${PROFILES[2]}")
  command+=("${@}")
  run_compose "${command[@]}"
}

ensure_dify_network() {
  docker network inspect geo-dify-runtime >/dev/null 2>&1 || docker network create geo-dify-runtime >/dev/null
}

canonical_config() {
  require_env
  run_with_profiles config -q
}

canonical_up() {
  require_env
  ensure_dify_network
  "${DIFY_SCRIPT}" up
  run_with_profiles up -d
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
  "${DIFY_SCRIPT}" down
}

canonical_status() {
  require_env
  run_compose ps
  "${DIFY_SCRIPT}" status
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
  if docker compose --project-name geo-development -f "${REPO_ROOT}/infra/docker-compose.yml" ps -q 2>/dev/null | grep -q .; then
    echo "legacy runtime detected: geo-development" >&2
    bad=1
  fi
  if docker compose --project-name geo-advinsys-staging -f "${REPO_ROOT}/infra/docker-compose.yml" ps -q 2>/dev/null | grep -q .; then
    echo "legacy runtime detected: geo-advinsys-staging" >&2
    bad=1
  fi
  echo "canonical project: ${STACK_PROJECT}"
  echo "env file: ${STACK_ENV_FILE}"
  run_compose ps --status running
  if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:"${GEO_INTERNAL_API_HOST_PORT:-18000}"/health >/dev/null 2>&1; then
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
      echo "cleanup error: GEO_MIGRATION_PACKAGE must point to a verified package before deleting volumes" >&2
      exit 2
    }
    python3 - "${GEO_MIGRATION_PACKAGE}" <<'PY'
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    raise SystemExit(f"cleanup error: migration manifest is unreadable: {path}") from error
if payload.get("schema_version") != "geo-runtime-migration-v1" or payload.get("status") != "verified-export":
    raise SystemExit("cleanup error: migration manifest is not a verified GEO runtime export")
PY
  fi
  local -a legacy=(geo-development geo-advinsys-staging)
  local project
  for project in "${legacy[@]}"; do
    local args=(docker compose --project-name "$project" -f "${REPO_ROOT}/infra/docker-compose.yml" down --remove-orphans)
    [[ "$delete_volumes" == 1 ]] && args+=(--volumes)
    "${args[@]}" || true
  done
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
    "${DIFY_SCRIPT}" up
    # Keep the application image available for the post-restore Secret Store
    # canary; its dependencies still gate on migration and MinIO bootstrap.
    run_with_profiles up -d postgres minio valkey internal-api
  fi
  exec uv run python "${REPO_ROOT}/scripts/geo_migrate.py" "$command" \
    --repo-root "${REPO_ROOT}" "$@"
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
    cleanup-legacy) cleanup_legacy "$@" ;;
    export|import|verify) delegate_migration "$command" "$@" ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

main "$@"
