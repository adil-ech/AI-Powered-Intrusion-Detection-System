# ADR 0001: MVP scope and platform

- Status: Accepted
- Date: 2026-10-18
- Owners: Project team

## Context

The first release must demonstrate a complete machine-learning product without implying that a benchmark-trained model is a production network defense. Live packet capture, prevention, and long-running job infrastructure would add operational risk before the data and inference contracts are proven.

## Decision

The MVP is a synchronous batch analyzer for network-flow feature records.

The primary journey is:

1. Open the React application.
2. Inspect model readiness and download an input template.
3. Upload a UTF-8 CSV containing flow features.
4. Receive schema feedback and predictions.
5. Review benign/suspicious totals, attack categories, confidence, and risk priority.
6. Filter individual rows and export enriched results.

The MVP does not:

- capture live traffic;
- accept PCAP files;
- block traffic or change firewall rules;
- retrain from user uploads;
- persist upload history;
- require authentication for the local portfolio demo;
- claim detection of novel attacks; or
- act as a production SIEM, IDS, or IPS.

## Request limits

- CSV uploads: at most 10 MiB and 10,000 data rows.
- JSON prediction requests: at most 1,000 records.
- CSV encoding: UTF-8, optionally with a UTF-8 BOM.
- CSV delimiter: comma.
- CSV structure: one header row followed by numeric feature rows.
- Synchronous processing only for the MVP.
- Maximum accepted column count: 120, including ignored extra columns.

Missing required columns, duplicate headers, unsupported encoding, empty input, or a structurally invalid CSV rejects the entire request. Row-level numeric validation errors produce a `PARTIAL_SUCCESS` response when at least one row remains valid.

## Privacy and retention

- Uploaded rows are not stored or logged by default.
- Processing should use memory where practical.
- Any temporary file must be deleted before request completion.
- Logs may contain request IDs, counts, timings, error codes, and model versions, but not complete flow rows.
- Export happens in the browser from returned results.

## Platform decisions

| Concern | Decision |
|---|---|
| ML and API runtime | Python 3.12 |
| Python dependency manager | `uv`, with a committed lockfile |
| ML libraries | scikit-learn first; XGBoost remains an optional measured candidate |
| API | FastAPI served by Uvicorn |
| Frontend runtime | Node.js 24 LTS for build and test |
| Frontend package manager | npm with a committed lockfile |
| Frontend framework | React, TypeScript, and Vite |
| Frontend tests | Vitest/component tests plus Playwright browser tests |
| Model artifact | Trusted, packaged joblib pipeline plus JSON metadata and SHA-256 manifest |
| Local deployment | Docker Compose with separate `api` and `frontend` services |
| Frontend serving | Static production build served by an unprivileged web server container |
| Database | None in the MVP |

Exact dependency versions are selected and locked in Phase 1. The major runtime choices are fixed here. Python 3.12 is used for the mature ML ecosystem and remains security-supported through October 2028. Node.js 24 is an LTS line supported through April 2028.

## Docker topology

```mermaid
flowchart LR
    Browser[Browser] --> Frontend[Frontend container]
    Frontend --> API[FastAPI container]
    API --> Model[Read-only model artifact]
```

- Only the frontend and API ports needed by the demo are published.
- The model is copied into the API image or mounted read-only.
- No database or queue is introduced until a persistence or asynchronous-processing requirement exists.
- Containers run as non-root users.

## Consequences

- The first release can be tested end to end with bounded resource use.
- Large files require a later asynchronous job design.
- The application cannot directly analyze packets; callers must supply compatible flow features.
- A future authenticated or hosted release requires a new threat model and persistence decision.

