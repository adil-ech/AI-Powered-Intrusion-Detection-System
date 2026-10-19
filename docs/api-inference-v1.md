# Inference API v1

Phase 6 serves the frozen `ids-rf-v1.0.0` artifact through FastAPI. The service loads only the local `models/ids-rf-v1/` bundle, verifies every manifest hash and cross-file identity, and refuses inference when that verification fails.

## Run locally

The ignored artifact created by `make gate-5` must be present first.

```bash
PYTHONPATH=ml/src uv run uvicorn backend.app.main:app --reload
```

The service exposes:

- `GET /health` for process liveness;
- `GET /ready` for verified-model readiness;
- `GET /api/v1/model` for authoritative features, labels, versions, and thresholds;
- `GET /api/v1/input-template` for a UTF-8 CSV with all 63 features and one clearly identified synthetic row;
- `POST /api/v1/predictions` for up to 1,000 JSON records; and
- `POST /api/v1/predictions/file` for UTF-8 CSV uploads up to 10 MiB, 10,000 rows, and 120 columns.

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`. Its JSON request example is generated from the loaded artifact rather than a copied feature list. Download the input template and submit it to the file endpoint to perform a safe end-to-end sample prediction.

## Validation behavior

Headers are Unicode-normalized, trimmed, converted to lower snake case, and then checked for collisions. Column order is flexible. Every required feature must be present. A CSV `row_id` column is optional; otherwise one-based IDs are generated. Extra feature columns are ignored and named in a request warning.

Every scored value must be a finite number. JSON strings and booleans are not coerced to numbers. CSV blanks, nonnumeric values, NaN, and positive or negative infinity make that row invalid. Valid rows in the same request are still scored and the response becomes `PARTIAL_SUCCESS`. When no row is usable, the service returns `NO_VALID_ROWS` with field names but never rejected values.

## Runtime configuration

| Variable | Default | Purpose |
|---|---|---|
| `IDS_MODEL_DIR` | `models/ids-rf-v1` | Verified artifact directory |
| `IDS_CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | Comma-separated browser origin allowlist |

Docker Compose mounts the artifact read-only at `/app/models/ids-rf-v1`. Its API health check uses `/ready`, so a running process with a missing or incompatible model is not marked healthy.

## Privacy and failure handling

Every response carries an `X-Request-ID`; prediction and error bodies repeat that ID. Access logs contain only the request ID, method, path, status, and stable error code. Uploaded rows, rejected values, and tracebacks are not logged or returned. The MVP processes requests in memory and does not retain uploads.

Run the complete checkpoint with:

```bash
make gate-6
```

The gate runs repository validation, unit and integration tests, Compose validation, and a real-container template upload/prediction smoke test. Backend tests also use a small deterministic in-memory fixture so CI exercises validation when the intentionally ignored production artifact is absent; the local gate separately verifies JSON/CSV parity against the real frozen artifact.
