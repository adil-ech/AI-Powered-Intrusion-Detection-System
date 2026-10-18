.DEFAULT_GOAL := help

UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
export UV_CACHE_DIR

.PHONY: help setup format format-check lint typecheck test test-ml test-api test-web build smoke clean

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

clean:
	rm -rf .cache .pytest_cache .ruff_cache .mypy_cache htmlcov frontend/dist frontend/coverage test-results playwright-report .playwright-mcp .taste-skill
	find backend ml scripts -type d -name __pycache__ -prune -exec rm -rf {} +
	find backend ml scripts -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
