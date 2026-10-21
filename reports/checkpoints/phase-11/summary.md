# Phase 11 checkpoint

- **Status:** PASS
- **Date:** 2026-10-21
- **Release candidate:** `0.1.0`
- **Commit tested:** `3ea8064b37ef257818de832f6c7603b97ef7194c`
- **Environment:** macOS 26.2 (Darwin 25.2.0, arm64); uv 0.12.21 with
  Python 3.12.14; Node 25.2.1; npm 11.6.2; Docker client/server 29.8.2;
  Playwright Chromium.
- **Decision:** The MVP is a release candidate. Later feature work starts a new gated
  cycle; it must not modify this verified candidate without retesting.

## Commands and results

| Command | Result |
|---|---|
| `make gate-11` | PASS from the exact clean commit above; it ran every command in the final release gate without a skip |
| `make format-check` | PASS; 57 Python files and the frontend matched their configured formatters |
| `make lint` | PASS; every Phase 0–11 repository validator, Ruff, and ESLint passed |
| `make typecheck` | PASS; mypy checked 51 source files and TypeScript passed |
| `make test` | PASS; 23 ML, 48 backend, and 44 frontend tests passed |
| `make build` | PASS; the API imported and the production frontend bundle built |
| `make security` | PASS; hostile-input/export tests, dependency audits, secret scans, image policy, and runtime-user checks passed |
| `make smoke` | PASS; both Compose services became healthy and served the expected model, prediction, frontend, and security-header paths |
| `make test-e2e` | PASS; the real browser completed upload, review, detail, filtering, export, invalid-input, outage, and recovery checks |
| `make release-check` | PASS; documentation, previous checkpoints, Compose, clean Git state, repository boundaries, and exact model identity passed |
| `make performance` | PASS from a temporary clean `git archive` of the exact release commit with a no-cache build, benchmark, concurrency test, restart, and cleanup |

## Automated evidence

- Full suite: 115 tests passed with no failure or skip.
- Production bundle: 607-byte HTML, 27,645-byte CSS, 259,628-byte JavaScript, and
  26,588-byte local font; 314,468 bytes total for first-page assets.
- Clean archive: build 24.878s, startup 11.859s, restart 11.156s, one-row median
  0.031049s / p95 0.037580s, and 10,000-row median 0.464415s / p95 0.778788s.
- Concurrency: eight requests through four workers preserved every row ID and produced
  eight distinct request IDs.
- Resources: API peak 240.70 MiB under its 512 MiB benchmark budget and 768 MiB
  container limit; frontend peak 8.51 MiB under its 128 MiB limit.
- Images: API 514.00 MiB under 600 MiB; frontend 87.55 MiB under 100 MiB. Configured
  users remained `app` and `101:101`.
- Artifact: `ids-rf-v1.0.0` manifest SHA-256
  `dfa7678b89009aa03af89957dde958af20af6f969decdd295ba7209eaa6c3601`;
  every declared file hash and size matched.

## Security evidence

- `uv audit --frozen`: 43 locked packages, no known vulnerability or adverse status.
- `npm audit --audit-level=high --package-lock-only`: 0 vulnerabilities.
- Gitleaks 8.30.1: 25 commits / 1.23 MB and the 1.64 MB working tree scanned with no
  detected leak.
- Trivy 0.76.0 frontend scan: 0 high or critical findings.
- Trivy 0.76.0 API scan: 0 critical findings. Its 44 high occurrences map to the same
  eight explicit, unfixed, unexpired base-image exceptions documented in Phase 9; no
  fixable or unknown high finding was accepted.
- Both images passed non-root identity checks and retain read-only roots, dropped
  capabilities, `no-new-privileges`, bounded temporary storage, and CPU/memory/PID
  limits.

## Manual release journey

- Reviewed the README from a first-time evaluator's perspective: project boundary,
  prerequisites, trusted external model requirement, Docker quick start, expected demo
  outcome, shutdown, API examples, metrics, browser support, troubleshooting, license,
  and next documentation links are all visible.
- The exact candidate was rebuilt from a temporary clean Git archive using only the
  committed `.env.example` and explicit read-only trusted artifact path.
- The browser loaded the bundled six-row sample through the live API and showed one
  benign and five suspicious results with the expected six categories.
- `demo-03` was checked against the documented explanation: 99.15% malicious
  probability, 92.13% conditional `PORT_SCAN` confidence, 91.35% combined confidence,
  `HIGH` risk, model `ids-rf-v1.0.0`, and the stated non-causal limitation.
- Filtering to suspicious traffic produced five visible rows; export produced one
  header plus those five enriched rows with model and warning fields.
- Error and recovery states were exercised, services stopped cleanly, no project
  container remained, and no upload database or server-side history exists.
- Architecture diagrams and approved desktop, mobile, invalid-input, recovery, and
  row-detail screenshots were reviewed for agreement with the verified application.

## Release documentation

- [`../../../README.md`](../../../README.md)
- [`../../../CHANGELOG.md`](../../../CHANGELOG.md)
- [`../../../THIRD_PARTY_NOTICES.md`](../../../THIRD_PARTY_NOTICES.md)
- [`../../../docs/architecture.md`](../../../docs/architecture.md)
- [`../../../docs/demo-script.md`](../../../docs/demo-script.md)
- [`../../../docs/model-card.md`](../../../docs/model-card.md)
- [`../../../docs/release-checklist.md`](../../../docs/release-checklist.md)
- [`../phase-10/performance-report.md`](../phase-10/performance-report.md)
- [`../phase-09/security-report.md`](../phase-09/security-report.md)

Generated benchmark JSON, build output, browser traces, scanner results, caches, and
temporary checkout contents were transient evidence and were removed after review.

## Known limitations

- This is a single-host educational batch demo, not a live packet sensor, autonomous
  blocker, production IDS, or SIEM replacement.
- Internet-facing use still requires authentication, authorization, TLS termination,
  upstream rate/connection limits, monitoring, and an operational response process.
- The trusted `joblib` artifact remains external to Git; manifest integrity does not
  make an artifact from an untrusted source safe to deserialize.
- Metrics are from a controlled 2017 dataset. `INFILTRATION` recall is 0.375 on only
  eight final-test examples, `RARE_OTHER` has no final-test support, and novel or
  contemporary attack performance is unknown.
- The release browser gate certifies Chromium. Firefox and Safari are not release-
  certified.
- Performance and image results describe the recorded arm64 reference host, not a
  universal service-level guarantee.
- The eight accepted Debian base-image advisory exceptions expire on 2026-11-20 and
  require a refreshed Gate 9 review before that deadline.
