#!/usr/bin/env bash
set -euo pipefail

readonly DIFY_TAG="1.16.0"
readonly DIFY_COMMIT="5c6372d2f76d240265b92fd27c16bc772ffcb107"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly RUNTIME_ROOT="${GEO_DIFY_RUNTIME_ROOT:-${REPO_ROOT}/.runtime/dify-1.16.0}"
readonly DIFY_DOCKER_DIR="${RUNTIME_ROOT}/docker"
readonly DIFY_ENV_FILE="${DIFY_DOCKER_DIR}/.env"
readonly DIFY_OVERRIDE="${REPO_ROOT}/infra/dify/docker-compose.dify.yml"

usage() {
  echo "usage: $0 prepare|up|down|status"
}

set_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${DIFY_ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${DIFY_ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${value}" >>"${DIFY_ENV_FILE}"
  fi
}

random_hex() {
  openssl rand -hex "$1"
}

random_base64url_32() {
  openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n'
}

repair_agent_secret() {
  local value
  value="$(sed -n 's/^DIFY_AGENT_SERVER_SECRET_KEY=//p' "${DIFY_ENV_FILE}")"
  if [[ ! "${value}" =~ ^[A-Za-z0-9_-]{43}$ ]]; then
    set_env DIFY_AGENT_SERVER_SECRET_KEY "$(random_base64url_32)"
  fi
}

repair_redis_urls() {
  local password
  password="$(sed -n 's/^REDIS_PASSWORD=//p' "${DIFY_ENV_FILE}")"
  if [[ -z "${password}" ]]; then
    echo "Dify REDIS_PASSWORD is missing." >&2
    exit 2
  fi
  set_env CELERY_BROKER_URL "redis://:${password}@redis:6379/1"
}

prepare() {
  if [[ ! -d "${RUNTIME_ROOT}/.git" ]]; then
    mkdir -p "$(dirname "${RUNTIME_ROOT}")"
    git clone --depth 1 --branch "${DIFY_TAG}" \
      https://github.com/langgenius/dify.git "${RUNTIME_ROOT}"
  fi
  local actual_commit
  actual_commit="$(git -C "${RUNTIME_ROOT}" rev-parse HEAD)"
  if [[ "${actual_commit}" != "${DIFY_COMMIT}" ]]; then
    echo "Dify source mismatch: expected ${DIFY_COMMIT}, got ${actual_commit}." >&2
    echo "Move the existing runtime directory aside, then rerun prepare." >&2
    exit 2
  fi
  if [[ ! -f "${DIFY_ENV_FILE}" ]]; then
    cp "${DIFY_DOCKER_DIR}/.env.example" "${DIFY_ENV_FILE}"
    set_env SECRET_KEY "$(random_hex 32)"
    set_env DB_PASSWORD "$(random_hex 24)"
    set_env REDIS_PASSWORD "$(random_hex 24)"
    set_env SANDBOX_API_KEY "$(random_hex 24)"
    set_env PLUGIN_DIFY_INNER_API_KEY "$(random_hex 32)"
    set_env DIFY_AGENT_SERVER_SECRET_KEY "$(random_base64url_32)"
    set_env EXPOSE_NGINX_PORT "${GEO_DIFY_HOST_PORT:-15000}"
    set_env GEO_DIFY_BIND_HOST "${GEO_DIFY_BIND_HOST:-127.0.0.1}"
    set_env COMPOSE_PROFILES "postgresql,weaviate"
    chmod 600 "${DIFY_ENV_FILE}"
  fi
  if [[ -n "${GEO_DIFY_BIND_HOST:-}" ]]; then
    set_env GEO_DIFY_BIND_HOST "${GEO_DIFY_BIND_HOST}"
  fi
  if [[ -n "${GEO_DIFY_HOST_PORT:-}" ]]; then
    set_env EXPOSE_NGINX_PORT "${GEO_DIFY_HOST_PORT}"
  fi
  repair_agent_secret
  repair_redis_urls
  docker network inspect geo-dify-runtime >/dev/null 2>&1 \
    || docker network create geo-dify-runtime >/dev/null
  echo "Dify ${DIFY_TAG} runtime prepared at ${RUNTIME_ROOT}."
}

compose() {
  docker compose \
    --project-name geo-dify \
    --env-file "${DIFY_ENV_FILE}" \
    -f "${DIFY_DOCKER_DIR}/docker-compose.yaml" \
    -f "${DIFY_OVERRIDE}" \
    "$@"
}

command="${1:-}"
case "${command}" in
  prepare)
    prepare
    ;;
  up)
    prepare
    compose up -d
    compose restart nginx >/dev/null
    echo "Dify console is listening on ${GEO_DIFY_BIND_HOST:-127.0.0.1}:${GEO_DIFY_HOST_PORT:-15000}."
    echo "Open it from the persistent '打开 Dify 工作流' action in Admin."
    ;;
  down)
    [[ -f "${DIFY_ENV_FILE}" ]] || { echo "Dify runtime is not prepared." >&2; exit 2; }
    compose down
    ;;
  status)
    [[ -f "${DIFY_ENV_FILE}" ]] || { echo "Dify runtime is not prepared." >&2; exit 2; }
    compose ps
    ;;
  *)
    usage
    exit 2
    ;;
esac
