#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary_directory="$(mktemp -d)"
trivy_image="aquasec/trivy:0.76.0"
gitleaks_image="ghcr.io/gitleaks/gitleaks:v8.30.1"

cleanup() {
  docker compose --project-directory "${project_root}" down --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${temporary_directory}"
}

trap cleanup EXIT

for command in docker git; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "Required security command is unavailable: ${command}" >&2
    exit 1
  }
done

docker pull "${gitleaks_image}" >/dev/null
history_scan="$(docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  --env GIT_CONFIG_COUNT=1 \
  --env GIT_CONFIG_KEY_0=safe.directory \
  --env GIT_CONFIG_VALUE_0=/repo \
  --mount "type=bind,src=${project_root},dst=/repo,readonly" \
  --workdir /repo \
  "${gitleaks_image}" detect --source=/repo --redact --no-banner --log-opts=--all 2>&1)"
printf '%s\n' "${history_scan}"
if [[ "${history_scan}" =~ (^|[[:space:]])0[[:space:]]commits[[:space:]]scanned\. ]]; then
  echo "Gitleaks did not scan repository history." >&2
  exit 1
fi
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=${project_root},dst=/repo,readonly" \
  --workdir /repo \
  "${gitleaks_image}" detect --source=/repo --no-git --redact --no-banner

docker compose --project-directory "${project_root}" build

api_image="ids-demo-api:local"
frontend_image="ids-demo-frontend:local"
if ! docker image inspect "${api_image}" "${frontend_image}" >/dev/null 2>&1; then
  echo "Security scan could not resolve the locally built image identifiers." >&2
  exit 1
fi

for image in "${api_image}" "${frontend_image}"; do
  configured_user="$(docker image inspect --format '{{.Config.User}}' "${image}")"
  if [[ -z "${configured_user}" || "${configured_user}" == "0" || "${configured_user}" == "root" ]]; then
    echo "Image ${image} does not declare a non-root runtime user." >&2
    exit 1
  fi
  runtime_uid="$(docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges --entrypoint id "${image}" -u)"
  if [[ "${runtime_uid}" == "0" ]]; then
    echo "Image ${image} starts as root." >&2
    exit 1
  fi
done

docker save --output "${temporary_directory}/api-image.tar" "${api_image}"
docker save --output "${temporary_directory}/frontend-image.tar" "${frontend_image}"
mkdir -p "${project_root}/.cache/trivy"
docker pull "${trivy_image}" >/dev/null

for image_name in api frontend; do
  archive="${image_name}-image.tar"
  docker run --rm \
    --mount "type=bind,src=${temporary_directory},dst=/scan" \
    --mount "type=bind,src=${project_root}/.cache/trivy,dst=/trivy-cache" \
    "${trivy_image}" image \
    --cache-dir /trivy-cache \
    --scanners vuln \
    --severity HIGH,CRITICAL \
    --format json \
    --output "/scan/${image_name}-vulnerabilities.json" \
    --input "/scan/${archive}"
  python3 -B "${project_root}/scripts/check_vulnerability_report.py" \
    --report "${temporary_directory}/${image_name}-vulnerabilities.json" \
    --exceptions "${project_root}/configs/security-exceptions.json" \
    --image "${image_name}"
done

echo "Security scan passed: secrets, runtime users, and the high/critical image policy are clear."
