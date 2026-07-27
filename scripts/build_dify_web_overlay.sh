#!/usr/bin/env bash
set -euo pipefail

readonly DIFY_COMMIT="5c6372d2f76d240265b92fd27c16bc772ffcb107"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly RUNTIME_ROOT="${GEO_DIFY_RUNTIME_ROOT:-${REPO_ROOT}/.runtime/dify-1.16.0}"
readonly PATCH_FILE="${REPO_ROOT}/infra/dify/patches/dify-1.16.0-geo-run-input-picker.patch"
readonly DOCKERFILE="${REPO_ROOT}/infra/dify/Dockerfile.web-overlay"
readonly IMAGE="${GEO_DIFY_WEB_IMAGE:-geo-dify-web:1.16.0-geo}"

if [[ ! -d "${RUNTIME_ROOT}/.git" ]]; then
  echo "Dify runtime source is missing; run ./scripts/bootstrap_dify_runtime.sh prepare first." >&2
  exit 2
fi
if [[ "$(git -C "${RUNTIME_ROOT}" rev-parse HEAD)" != "${DIFY_COMMIT}" ]]; then
  echo "Dify runtime source is not pinned to ${DIFY_COMMIT}." >&2
  exit 2
fi
if [[ ! -f "${PATCH_FILE}" || ! -f "${DOCKERFILE}" ]]; then
  echo "Dify Web overlay patch or Dockerfile is missing." >&2
  exit 2
fi

overlay_sha="$(sha256sum "${PATCH_FILE}" | awk '{print $1}')"
current_sha="$(docker image inspect "${IMAGE}" --format '{{ index .Config.Labels "io.geo.dify.web-overlay-sha" }}' 2>/dev/null || true)"
if [[ "${1:-}" != "--force" && "${current_sha}" == "${overlay_sha}" ]]; then
  echo "Dify Web overlay image ${IMAGE} already matches ${overlay_sha}."
  exit 0
fi

build_root="$(mktemp -d "${TMPDIR:-/tmp}/geo-dify-web-overlay.XXXXXX")"
cleanup() {
  rm -rf "${build_root}"
}
trap cleanup EXIT

git clone --quiet --no-checkout "${RUNTIME_ROOT}" "${build_root}/dify"
git -C "${build_root}/dify" checkout --quiet --detach "${DIFY_COMMIT}"
git -C "${build_root}/dify" apply --check "${PATCH_FILE}"
git -C "${build_root}/dify" apply "${PATCH_FILE}"

docker build \
  --network "${GEO_DIFY_BUILD_NETWORK:-default}" \
  --build-arg "COMMIT_SHA=${DIFY_COMMIT}" \
  --build-arg "GEO_OVERLAY_SHA=${overlay_sha}" \
  --file "${DOCKERFILE}" \
  --tag "${IMAGE}" \
  "${build_root}/dify"

echo "Built ${IMAGE} from Dify ${DIFY_COMMIT} with overlay ${overlay_sha}."
