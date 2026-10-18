#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary_directory="$(mktemp -d)"

cleanup() {
  docker compose --project-directory "${project_root}" down --remove-orphans >/dev/null 2>&1 || true
  rm -rf "${temporary_directory}"
}

trap cleanup EXIT

docker compose --project-directory "${project_root}" up --build --detach --wait

curl --fail --silent --show-error \
  --noproxy '*' \
  "http://127.0.0.1:${API_PORT:-8000}/health" \
  --output "${temporary_directory}/api-health.json"

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
frontend = (temporary_directory / "frontend.html").read_text(encoding="utf-8")
parser = RootElementParser()
parser.feed(frontend)

if health != {"status": "ok"}:
    raise SystemExit(f"unexpected health response: {health}")
if not parser.found_root:
    raise SystemExit("frontend response does not contain the React root")

print("Docker smoke test passed")
PY
