.DEFAULT_GOAL := help

UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
export UV_CACHE_DIR
PYTHONPATH ?= $(CURDIR)/ml/src
export PYTHONPATH

.PHONY: help setup format format-check lint typecheck test test-ml test-api test-web test-e2e build smoke clean data-manifest audit-data preprocess-data baseline-report port-variant model-selection-report finalize-model gate-2 gate-3 gate-4 gate-5 gate-6 gate-7 gate-8 ensure-baseline

help:
	@echo "Available targets:"
	@echo "  setup         Install locked Python and frontend dependencies"
	@echo "  format        Format Python and frontend source"
	@echo "  format-check  Check formatting without changing files"
	@echo "  lint          Run contract, Python, and frontend linters"
	@echo "  typecheck     Run Python and TypeScript type checks"
	@echo "  test          Run ML, API, and frontend tests"
	@echo "  test-e2e      Run the real upload-to-export browser journey"
	@echo "  build         Validate the API import and build the frontend"
	@echo "  smoke         Build and test the Docker Compose stack"
	@echo "  data-manifest Record local raw-data checksums (requires RETRIEVED_AT=YYYY-MM-DD)"
	@echo "  audit-data    Audit the complete local CIC-IDS2017 CSV dataset"
	@echo "  preprocess-data  Build deterministic model-ready train/validation/test inputs"
	@echo "  baseline-report  Train and evaluate Phase 4 baselines on validation data"
	@echo "  port-variant  Build the same-row destination-port diagnostic"
	@echo "  model-selection-report  Tune/calibrate/select without opening final test"
	@echo "  finalize-model  Freeze the selected artifact and evaluate final test once"
	@echo "  gate-2        Run Phase 2 checks, including the complete local data audit"
	@echo "  gate-3        Run Phase 3 checks, including complete preprocessing"
	@echo "  gate-4        Run Phase 4 checks, including the complete baseline report"
	@echo "  gate-5        Run Phase 5 checks and verify/finalize the selected artifact"
	@echo "  gate-6        Run the API contract tests and container smoke test"
	@echo "  gate-7        Run the fixture frontend contract and quality checks"
	@echo "  gate-8        Run full tests, builds, smoke, and browser integration"
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
	python3 -B scripts/validate_phase4.py
	python3 -B scripts/validate_phase5.py
	python3 -B scripts/validate_phase6.py
	python3 -B scripts/validate_phase7.py
	python3 -B scripts/validate_phase8.py
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

test-e2e:
	bash scripts/e2e.sh

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

baseline-report:
	PYTHONPATH=ml/src uv run python -m ids_ml.evaluation.cli --processed-dir data/processed/phase3 --config configs/baselines-v1.json --feature-contract contracts/features-v1.json --labels contracts/labels-v1.json --split-manifest data/processed/phase3/split-manifest.json --model-output models/baselines/baselines-v1.joblib --json-output reports/generated/baselines/baselines-v1.json --markdown-output reports/generated/baselines/baselines-v1.md --calibration-svg reports/generated/baselines/calibration.svg

gate-4:
	python3 -B scripts/validate_phase4.py
	uv run pytest ml/tests/test_evaluation.py
	$(MAKE) baseline-report

ensure-baseline:
	@test -f models/baselines/baselines-v1.joblib || $(MAKE) baseline-report

port-variant:
	PYTHONPATH=ml/src uv run python -m ids_ml.modeling.port_cli --raw-dir data/raw/cic-ids2017/MachineLearningCVE --catalog data/source_catalog.json --labels contracts/labels-v1.json --preprocessing-config configs/preprocessing-v1.json --base-processed-dir data/processed/phase3 --base-feature-contract contracts/features-v1.json --output-dir data/processed/phase5-with-port --report reports/generated/model-selection/port-variant.json

model-selection-report: ensure-baseline port-variant
	PYTHONPATH=ml/src uv run python -m ids_ml.modeling.cli --base-processed-dir data/processed/phase3 --port-processed-dir data/processed/phase5-with-port --feature-contract contracts/features-v1.json --labels contracts/labels-v1.json --baseline-artifact models/baselines/baselines-v1.joblib --config configs/model-selection-v1.json --artifact-dir models/ids-rf-v1 --json-output reports/generated/model-selection/model-selection-v1.json --markdown-output reports/generated/model-selection/model-selection-v1.md --calibration-svg reports/generated/model-selection/calibration.svg --selection-only

finalize-model: ensure-baseline port-variant
	PYTHONPATH=ml/src uv run python -m ids_ml.modeling.cli --base-processed-dir data/processed/phase3 --port-processed-dir data/processed/phase5-with-port --feature-contract contracts/features-v1.json --labels contracts/labels-v1.json --baseline-artifact models/baselines/baselines-v1.joblib --config configs/model-selection-v1.json --artifact-dir models/ids-rf-v1 --json-output reports/generated/model-selection/model-selection-v1.json --markdown-output reports/generated/model-selection/model-selection-v1.md --calibration-svg reports/generated/model-selection/calibration.svg --finalize

gate-5:
	python3 -B scripts/validate_phase5.py
	uv run pytest ml/tests/test_modeling.py
	$(MAKE) finalize-model

gate-6:
	python3 -B scripts/validate_phase6.py
	$(MAKE) test-api
	docker compose config --quiet
	$(MAKE) smoke

gate-7:
	python3 -B scripts/validate_phase7.py
	npm --prefix frontend run format:check
	npm --prefix frontend run typecheck
	npm --prefix frontend run lint
	npm --prefix frontend test
	npm --prefix frontend run build

gate-8:
	python3 -B scripts/validate_phase8.py
	$(MAKE) test
	$(MAKE) build
	$(MAKE) smoke
	$(MAKE) test-e2e

clean:
	rm -rf .cache .pytest_cache .ruff_cache .mypy_cache htmlcov frontend/dist frontend/coverage frontend/node_modules/.tmp reports/generated test-results playwright-report .playwright-mcp .taste-skill
	find backend ml scripts -type d -name __pycache__ -prune -exec rm -rf {} +
	find backend ml scripts -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
