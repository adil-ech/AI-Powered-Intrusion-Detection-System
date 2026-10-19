# Phase 6 checkpoint

- Status: PASS
- Date: 2026-10-19
- Tested implementation commit: `e64603d` (`Serve the frozen model through the API`)
- Model version: `ids-rf-v1.0.0`
- API version: `1.0.0`, base prefix `/api/v1`
- Feature schema: `features-v1`, 63 ordered numeric features
- Environment: macOS; Python 3.12.14 through uv 0.12.21; FastAPI 0.146.0; Pydantic 2.14.1; Docker Desktop with Compose
- CI evidence: pending checkpoint push
- Decision: Phase 6 is complete; Phase 7 may begin.

## Commands run

```bash
uv lock
uv sync --frozen --dev
uv run ruff format backend
uv run ruff check backend ml scripts
uv run mypy
uv run pytest backend/tests
make gate-6
make format-check
make lint
make typecheck
make test
make build
docker compose config --quiet
make gate-6  # committed implementation replay
make clean
```

Every final command exited successfully. `make gate-6` built both images, mounted the ignored model artifact read-only, waited for model readiness, downloaded the live template, uploaded it to the real CSV endpoint, verified one complete prediction, and stopped the stack cleanly.

## Automated test result

- Phase 0–6 repository and contract validators: PASS
- ML tests: 23 passed, 0 failed, 0 skipped
- API tests: 18 passed, 0 failed, 0 skipped
- React tests: 2 passed, 0 failed, 0 skipped
- Python and frontend formatting: PASS
- Python and frontend linting: PASS
- Python and TypeScript type checking: PASS
- Backend import and production frontend build: PASS
- Compose configuration: PASS
- Docker API readiness, frontend health, template download, and real-artifact CSV inference: PASS
- Real-artifact JSON/CSV prediction parity: PASS
- Committed response-example shape checks: PASS
- Loaded-artifact OpenAPI example with all 63 features: PASS
- Empty input, wrong media type, malformed multipart, unsupported encoding, duplicate headers, missing columns, excessive columns, excessive rows, excessive bytes, invalid numeric values, infinities, all-invalid batches, and duplicate row IDs: PASS
- Partial-success row isolation and extra-column warnings: PASS
- Model-unavailable liveness/readiness distinction: PASS
- Inference-failure traceback and internal-message suppression: PASS
- Privacy-safe structured access logging: PASS
- Configured CORS allowlist behavior: PASS
- Lifespan shutdown clears the loaded service: PASS

## Implemented contract

The service now provides:

- `GET /health` — process liveness independent of model state;
- `GET /ready` — `200` only after manifest, byte-count, hash, version, schema, feature-order, and threshold checks pass;
- `GET /api/v1/model` — authoritative model, schema, category, and threshold metadata;
- `GET /api/v1/input-template` — a 63-feature CSV with an identified synthetic example;
- `POST /api/v1/predictions` — up to 1,000 strict JSON records; and
- `POST /api/v1/predictions/file` — UTF-8 CSV up to 10 MiB, 10,000 data rows, and 120 columns.

Column order is flexible and names use the frozen canonicalization rule. Missing required columns never reach the model. Strings, booleans, blanks, NaN, and infinities are not coerced into valid features. A mixed batch scores only valid rows and returns field names—not rejected values—for invalid rows. All-invalid input returns `NO_VALID_ROWS`.

Predictions apply the artifact's calibrated malicious threshold (`0.015`), conditional family probabilities, low-confidence threshold (`0.65`), and high-risk threshold (`0.85`). Suspicious prediction confidence is the joint malicious and family probability. Benign confidence is one minus malicious probability.

Every response receives an opaque request ID. Prediction and error bodies repeat it. Logs contain request ID, method, path, status, and stable error code only; tests confirm row IDs and feature names/values are absent. Uploads are processed without application-level persistence.

## Manual checks performed

- Opened the live Swagger UI in Google Chrome and reviewed the rendered API title/version, all six endpoints, request media types, generated schemas, and documented `400`, `413`, `415`, `422`, `500`, and `503` responses.
- Confirmed `/docs` and `/openapi.json` loaded without an application error and the file endpoint rendered a required `multipart/form-data` file control with clear UTF-8 guidance.
- Confirmed the generated input template has one header, one `synthetic-example` row, 63 model features, and version/schema response headers.
- Reviewed representative error bodies to confirm a user can act on the stable code, message, affected field names, and request ID without server-log access.
- Confirmed a real template upload and prediction manually through the Gate 6 Docker smoke output.
- Attempted the same attachment through the visible Swagger file chooser. Chrome's ChatGPT extension refused local-file attachment because its optional “Allow access to file URLs” permission is disabled. That browser security setting was left unchanged; this is an automation-environment limitation, while the identical multipart upload passed through the live container and API integration tests.

## Evidence files

- `backend/app/config.py`
- `backend/app/errors.py`
- `backend/app/inference.py`
- `backend/app/main.py`
- `backend/app/schemas.py`
- `backend/tests/test_api.py`
- `docs/api-contract.md`
- `docs/api-inference-v1.md`
- `scripts/validate_phase6.py`
- `scripts/smoke.sh`
- `backend/Dockerfile`
- `docker-compose.yml`
- `.github/workflows/ci.yml`

The model bundle remains intentionally ignored. CI uses the deterministic in-memory service fixture for the complete validation matrix and skips only the real-bundle parity test when the local artifact is absent. The local Gate 6 run exercised the actual frozen artifact in both the test process and Docker.

## Known limitations

- Inputs are extracted CIC-IDS2017-compatible flow features, not packet captures or live traffic.
- Requests are synchronous and bounded; queueing, background jobs, and production performance targets belong to later phases.
- Authentication, rate limiting, dependency scanning, and broader abuse hardening are Phase 9 work.
- The model inherits the dataset, class-support, and generalization limitations in `docs/model-card.md`, especially low-support `INFILTRATION` and absent `RARE_OTHER` validation evidence.
- The production artifact is intentionally excluded from Git, so a clean checkout must create or securely mount it before `/ready` can pass.
- The visible Swagger attachment could not be automated without expanding a Chrome extension's local-file permission; no application defect was observed, and equivalent live multipart uploads passed.
