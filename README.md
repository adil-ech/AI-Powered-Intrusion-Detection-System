# AI-Powered Intrusion Detection System

A full-stack machine-learning project that classifies network-flow records as benign or suspicious and categorizes supported attacks. Its audited CIC-IDS2017 pipeline, calibrated Random Forest artifact, and versioned FastAPI service are implemented through Phase 6.

## Current capabilities

- FastAPI service with liveness, readiness, metadata, input-template, JSON prediction, and CSV upload endpoints.
- React and TypeScript status screen connected to the API.
- Python and frontend formatting, linting, typing, and test commands.
- Docker Compose development/demo stack.
- Versioned product, data, model, and API contracts.
- Streaming CIC-IDS2017 audit, global deduplication, grouped splits, and train-fitted preprocessing.
- Validation-only dummy and streaming logistic baselines with explicit class, error-rate, and calibration metrics.
- Group-aware Random Forest selection, deterministic calibration, and integrity-checked artifact packaging.
- Strict batch validation, partial-success row errors, correlation IDs, privacy-safe logs, and environment-scoped CORS.

The API verifies every file in `models/ids-rf-v1/` at startup. `/health` remains a process-liveness check; `/ready` returns `200` only after the model is integrity-checked and compatible.

## Dataset audit

Phase 2 uses the eight machine-learning CSV files from CIC-IDS2017. Follow the verified acquisition, citation, checksum, and extraction procedure in [the dataset guide](docs/data/cic-ids2017.md). Raw data and generated reports stay local and are ignored by Git.

After extracting the archive:

```bash
make data-manifest RETRIEVED_AT=YYYY-MM-DD
make audit-data
```

The audit streams the full dataset, verifies every file checksum, inventories labels and schemas, and measures missing, non-finite, constant, and duplicate data without loading all rows into memory.

Build and verify the grouped train, validation, and untouched final-test inputs with:

```bash
make gate-3
```

See [the frozen preprocessing contract](docs/data/preprocessing-v1.md) for grouping, leakage controls, feature schema, and rare-class limitations.

Train and evaluate the reproducible validation baselines with:

```bash
make gate-4
```

The [baseline guide](docs/ml/baselines-v1.md) documents the metrics and the sealed final-test boundary.

Tune the Random Forest candidates without opening final-test predictions with:

```bash
make model-selection-report
```

After the selection in `configs/model-selection-v1.json` is frozen, `make gate-5` creates or verifies the single versioned MVP artifact. See the [model-selection guide](docs/ml/model-selection-v1.md) and [model card](docs/model-card.md).

## Prerequisites

Choose either:

- Docker with Docker Compose; or
- Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 24 LTS, and npm.

## Local development

```bash
cp .env.example .env
make setup
make test
make build
```

Run the API:

```bash
PYTHONPATH=ml/src uv run uvicorn backend.app.main:app --reload
```

Run the frontend in another terminal:

```bash
npm --prefix frontend run dev
```

The development frontend is available at <http://localhost:5173> and proxies health calls to <http://localhost:8000>.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

- Application: <http://localhost:8080>
- API documentation: <http://localhost:8000/docs>
- API liveness: <http://localhost:8000/health>
- Model readiness: <http://localhost:8000/ready>
- Input template: <http://localhost:8000/api/v1/input-template>

Stop the stack with:

```bash
docker compose down --remove-orphans
```

## Quality commands

```bash
make format-check
make lint
make typecheck
make test
make build
docker compose config --quiet
make smoke
make gate-6
make clean
```

`make smoke` creates response files in a temporary directory, always removes that directory, and shuts down its Compose services before exiting.

`make gate-6` validates the API contract, runs all backend tests, checks Compose, starts the full stack with the real ignored artifact, uploads the generated template, and verifies a prediction before shutting the stack down.

## Project contracts

- [Project plan](PROJECT_PLAN.md)
- [Gated implementation workflow](IMPLEMENTATION_WORKFLOW.md)
- [API contract](docs/api-contract.md)
- [Architecture decisions](docs/decisions/README.md)
- [Phase checkpoints](reports/checkpoints/)

## Data and models

The full CIC-IDS2017 dataset and generated model artifacts are intentionally excluded from Git. See [data/README.md](data/README.md) and [models/README.md](models/README.md) before adding local files.

## License

MIT. See [LICENSE](LICENSE).
