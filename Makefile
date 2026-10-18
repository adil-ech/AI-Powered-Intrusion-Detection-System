.DEFAULT_GOAL := help

UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
export UV_CACHE_DIR

.PHONY: help setup format format-check lint typecheck test test-ml test-api test-web build smoke clean data-manifest audit-data preprocess-data gate-2 gate-3

help:
	@echo "Available targets:"
	@echo "  setup         Install locked Python and frontend dependencies"
	@echo "  format        Format Python and frontend source"
	@echo "  format-check  Check formatting without changing files"
	@echo "  lint          Run contract, Python, and frontend linters"
	@echo "  typecheck     Run Python and TypeScript type checks"
	@echo "  test          Run ML, API, and frontend tests"
	@echo "  build         Validate the API import and build the frontend"
	@echo "  smoke         Build and test the Docker Compose stack"
	@echo "  data-manifest Record local raw-data checksums (requires RETRIEVED_AT=YYYY-MM-DD)"
	@echo "  audit-data    Audit the complete local CIC-IDS2017 CSV dataset"
	@echo "  preprocess-data  Build deterministic model-ready train/validation/test inputs"
	@echo "  gate-2        Run Phase 2 checks, including the complete local data audit"
	@echo "  gate-3        Run Phase 3 checks, including complete preprocessing"
	@echo "  clean         Remove generated test and build output"

setup:
	uv sync --frozen --dev
	npm --prefix frontend ci

format:
	uv run ruff format backend ml scripts
	uv run ruff check --fix backend ml scripts
	npm --prefix frontend run format

format-check:
	uv run ruff format --check backend ml scripts
	npm --prefix frontend run format:check

lint:
	python3 -B scripts/validate_phase0.py
	python3 -B scripts/validate_phase2.py
	python3 -B scripts/validate_phase3.py
	uv run ruff check backend ml scripts
	npm --prefix frontend run lint

typecheck:
	uv run mypy
	npm --prefix frontend run typecheck

test-ml:
	uv run pytest ml/tests

test-api:
	uv run pytest backend/tests

test-web:
	npm --prefix frontend test

test: test-ml test-api test-web

build:
	uv run python -c "from backend.app.main import app; assert app.title"
	npm --prefix frontend run build

smoke:
	bash scripts/smoke.sh

data-manifest:
	@test -n "$(RETRIEVED_AT)" || (echo "Set RETRIEVED_AT=YYYY-MM-DD to the archive retrieval date"; exit 2)
	PYTHONPATH=ml/src uv run python -m ids_ml.data.cli manifest --raw-dir data/raw/cic-ids2017/MachineLearningCVE --catalog data/source_catalog.json --retrieved-at "$(RETRIEVED_AT)" --output data/raw/cic-ids2017/manifest.json

audit-data:
	PYTHONPATH=ml/src uv run python -m ids_ml.data.cli audit --raw-dir data/raw/cic-ids2017/MachineLearningCVE --catalog data/source_catalog.json --manifest data/raw/cic-ids2017/manifest.json --labels contracts/labels-v1.json --json-output reports/generated/data-audit.json --markdown-output reports/generated/data-audit.md

gate-2:
	python3 -B scripts/validate_phase2.py
	uv run pytest ml/tests/test_data_audit.py
	$(MAKE) audit-data

preprocess-data:
	PYTHONPATH=ml/src uv run python -m ids_ml.data.cli preprocess --raw-dir data/raw/cic-ids2017/MachineLearningCVE --catalog data/source_catalog.json --manifest data/raw/cic-ids2017/manifest.json --labels contracts/labels-v1.json --config configs/preprocessing-v1.json --output-dir data/processed/phase3 --feature-contract contracts/features-v1.json --json-output reports/generated/preprocessing.json --markdown-output reports/generated/preprocessing.md

gate-3:
	python3 -B scripts/validate_phase3.py
	uv run pytest ml/tests/test_preprocessing.py
	$(MAKE) preprocess-data

clean:
	rm -rf .cache .pytest_cache .ruff_cache .mypy_cache htmlcov frontend/dist frontend/coverage reports/generated test-results playwright-report .playwright-mcp .taste-skill
	find backend ml scripts -type d -name __pycache__ -prune -exec rm -rf {} +
	find backend ml scripts -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
