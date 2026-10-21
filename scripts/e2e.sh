#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose --project-directory "${project_root}" --env-file "${project_root}/.env.example")

cleanup() {
  "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup EXIT

"${compose[@]}" down --remove-orphans
"${compose[@]}" up --build --detach --wait

E2E_BASE_URL="http://127.0.0.1:${FRONTEND_PORT:-8080}" \
  npm --prefix "${project_root}/frontend" run e2e
