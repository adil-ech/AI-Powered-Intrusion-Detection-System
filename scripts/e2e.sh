#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  docker compose --project-directory "${project_root}" down --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup EXIT

docker compose --project-directory "${project_root}" down --remove-orphans
docker compose --project-directory "${project_root}" up --build --detach --wait

E2E_BASE_URL="http://127.0.0.1:${FRONTEND_PORT:-8080}" \
  npm --prefix "${project_root}/frontend" run e2e
