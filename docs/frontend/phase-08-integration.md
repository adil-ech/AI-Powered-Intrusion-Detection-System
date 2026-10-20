# Phase 8 full-stack integration

Phase 8 replaces the Phase 7 preview transport with the versioned FastAPI service while preserving the reviewed interface states. The production application does not import fixture responses. Fixtures remain available only to component and accessibility tests.

## Runtime flow

1. The browser checks `/ready` and then loads `/api/v1/model`.
2. Upload and sample actions stay disabled until both endpoints agree on the active model version.
3. A selected CSV is sent as multipart form data to `/api/v1/predictions/file`.
4. The client validates the response shape and confirms its model name, model version, and feature-schema version match the metadata loaded before submission.
5. Results, partial row errors, filters, detail review, and enriched CSV export operate on that live response.

Metadata, readiness, and template calls time out after 30 seconds. Prediction uploads time out after 120 seconds. All calls support cancellation, and a submission lock prevents duplicate uploads. HTTP errors keep the API's safe error envelope; invalid or unreachable responses become explicit client-side codes without displaying submitted feature values.

## Development and container routing

The default is same-origin routing:

- Vite proxies `/health`, `/ready`, and `/api` to `VITE_API_PROXY_TARGET`, which defaults to `http://127.0.0.1:8000`.
- The production frontend image uses Nginx to proxy those paths to the Compose `api` service.
- `VITE_API_BASE_URL` may point a separately hosted frontend build at an API origin. Leave it empty for the default proxy configuration.

Copy `frontend/.env.example` to `frontend/.env.local` to override local frontend routing.

## Safe demo sample

`frontend/public/samples/ids-demo-mixed.csv` contains six sanitized feature vectors selected from the training split. It has invented row IDs, no labels, and no network identifiers, ports, timestamps, or capture identifiers. It is integration input rather than evaluation evidence.

Against `ids-rf-v1.0.0`, the checkpoint asserts six valid rows, five suspicious rows, four high-priority rows, and one result from each of `BENIGN`, `DOS_DDOS`, `PORT_SCAN`, `BRUTE_FORCE`, `WEB_ATTACK`, and `BOTNET`.

## Verification

Install the Chromium browser once if Playwright cannot find a local Chrome/Chromium executable:

```bash
npx --prefix frontend playwright install chromium
```

Then run:

```bash
make gate-8
```

The browser gate starts clean Compose containers, verifies readiness and the server-generated template, runs the safe mixed sample through the real model, checks review and export behavior, exercises invalid-schema and over-limit errors, restarts the API, and confirms recovery. Containers and Playwright scratch output are cleaned or isolated from committed checkpoint evidence.
