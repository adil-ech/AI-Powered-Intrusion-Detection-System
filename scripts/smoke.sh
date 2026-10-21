#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary_directory="$(mktemp -d)"
compose=(docker compose --project-directory "${project_root}" --env-file "${project_root}/.env.example")

cleanup() {
  "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${temporary_directory}"
}

trap cleanup EXIT

"${compose[@]}" up --build --detach --wait

curl --fail --silent --show-error \
  --noproxy '*' \
  "http://127.0.0.1:${API_PORT:-8000}/health" \
  --output "${temporary_directory}/api-health.json"

curl --fail --silent --show-error \
  --noproxy '*' \
  "http://127.0.0.1:${API_PORT:-8000}/ready" \
  --output "${temporary_directory}/api-ready.json"

curl --fail --silent --show-error \
  --noproxy '*' \
  "http://127.0.0.1:${API_PORT:-8000}/api/v1/model" \
  --output "${temporary_directory}/api-model.json"

curl --fail --silent --show-error \
  --noproxy '*' \
  "http://127.0.0.1:${API_PORT:-8000}/api/v1/input-template" \
  --output "${temporary_directory}/input-template.csv"

curl --fail --silent --show-error \
  --noproxy '*' \
  --form "file=@${temporary_directory}/input-template.csv;type=text/csv" \
  "http://127.0.0.1:${API_PORT:-8000}/api/v1/predictions/file" \
  --output "${temporary_directory}/api-prediction.json"

curl --fail --silent --show-error \
  --noproxy '*' \
  "http://127.0.0.1:${FRONTEND_PORT:-8080}/" \
  --output "${temporary_directory}/frontend.html"

python3 -B - "${temporary_directory}" <<'PY'
from __future__ import annotations

import json
import pathlib
import sys
from html.parser import HTMLParser


class RootElementParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found_root = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div" and ("id", "root") in attrs:
            self.found_root = True

temporary_directory = pathlib.Path(sys.argv[1])
health = json.loads((temporary_directory / "api-health.json").read_text(encoding="utf-8"))
ready = json.loads((temporary_directory / "api-ready.json").read_text(encoding="utf-8"))
model = json.loads((temporary_directory / "api-model.json").read_text(encoding="utf-8"))
prediction = json.loads(
    (temporary_directory / "api-prediction.json").read_text(encoding="utf-8")
)
frontend = (temporary_directory / "frontend.html").read_text(encoding="utf-8")
parser = RootElementParser()
parser.feed(frontend)

if health != {"status": "ok"}:
    raise SystemExit(f"unexpected health response: {health}")
if ready != {"status": "ready", "model_version": "ids-rf-v1.0.0"}:
    raise SystemExit(f"unexpected readiness response: {ready}")
if model.get("artifact_status") != "READY" or len(model.get("required_features", [])) != 63:
    raise SystemExit(f"unexpected model metadata: {model}")
if prediction.get("status") != "COMPLETE" or prediction.get("summary", {}).get("valid_rows") != 1:
    raise SystemExit(f"unexpected prediction response: {prediction}")
if not parser.found_root:
    raise SystemExit("frontend response does not contain the React root")

print("Docker smoke test passed")
PY
