# Phase 10 checkpoint

- **Status:** PASS
- **Date:** 2026-10-21
- **Commit tested:** `2c479678f14297599c6b5130d1a2226f80ed485d`
- **Environment:** macOS 26.2 (Darwin 25.2.0, arm64); uv 0.12.21 with
  Python 3.12.14; Node 25.2.1; npm 11.6.2; Docker client/server 29.8.2.
- **Decision:** Proceed to Phase 11. Phase 11 has not started.

## Commands and results

| Command | Result |
|---|---|
| `make format-check lint typecheck test` | PASS before the implementation commit; 55 Python files formatted, all repository validators and linters passed, mypy checked 49 source files, TypeScript passed, and 115 tests passed |
| `make build` | PASS; the API imported and the production frontend bundle built |
| `make gate-6` | PASS from the exact implementation commit; the modified model-mount contract and every downstream API/Docker check were replayed |
| `make gate-7` | PASS from the exact implementation commit; formatting, types, lint, 44 frontend tests, and production build passed |
| `make gate-8` | PASS from the exact implementation commit; all tests, builds, smoke checks, and real-browser integration passed |
| `make gate-9` | PASS from the exact implementation commit; security, full tests, smoke, and browser integration passed |
| `make gate-10` | PASS from the exact implementation commit; Gate 9 replayed and the clean-archive no-cache performance gate passed |
| Taste source lint and browser inspector | PASS; 0 failures, 0 source warnings, and the same 3 defended content advisories at 1440, 768, and 390 px |

Changing the model mount to a configurable host path touched a Phase 6 deployment
contract. In accordance with the workflow, validation returned to Gate 6 and replayed
Gates 6, 7, 8, 9, and 10 in order. No downstream regression remained.

## Automated evidence

- Full suite: 23 ML tests, 48 backend tests, and 44 frontend tests passed (115 total,
  no failures or skips).
- Browser integration: one real-model upload, review, export, validation, and recovery
  journey passed repeatedly during the downstream gate replay.
- Clean checkout: a temporary archive of the exact tested commit rebuilt both images
  with `--no-cache --pull`, using only `.env.example` plus the explicit trusted model
  path; startup, inference, concurrency, restart, and frontend smoke checks passed.
- Performance: clean build 25.737s; startup 12.128s; restart 11.114s; one-row median
  0.026774s and p95 0.029196s; 10,000-row median 0.465052s and p95 0.905242s.
- Resources: API peak 228.60 MiB and frontend peak 12.05 MiB; configured CPU, memory,
  and PID limits were present and positive.
- Sizes: API image 514.01 MiB, frontend image 87.55 MiB, first-page assets 307.10 KiB,
  10,000-row request 7,891,039 bytes, and response 2,400,399 bytes. Every declared
  budget passed.
- Reproducibility: model file hashes matched manifest
  `dfa7678b89009aa03af89957dde958af20af6f969decdd295ba7209eaa6c3601`;
  duplicate artifact writes were byte-identical; lockfiles and Docker base digests were
  enforced.

## Security and visual evidence

- `uv audit --frozen`: 43 locked packages, no known vulnerability or adverse status.
- `npm audit --audit-level=high --package-lock-only`: 0 vulnerabilities.
- Gitleaks 8.30.1: 23 commits / 1.19 MB and the 1.64 MB working tree scanned with no
  detected leak.
- Trivy 0.76.0 frontend scan: 0 high or critical findings.
- Trivy 0.76.0 API scan: 0 critical findings. The 44 high occurrences remained covered
  by the same eight exact, unfixed, time-bounded base-image exceptions; there was no
  fixable or unknown high finding.
- API and frontend images ran as non-root with read-only roots, dropped capabilities,
  `no-new-privileges`, and bounded temporary filesystems.
- Jost was moved from Google Fonts to a reviewed local WOFF2 asset. Source inspection
  found no third-party entry-asset URL, and the browser inspector confirmed Jost was
  used at desktop, tablet, and mobile widths without layout, clipping, overlap, or
  readability regressions.
- The three taste advisories remain intentional: this is an interface-led security
  product without photographic or video storytelling, and muted ink is restricted to
  secondary notes while primary content uses stronger contrast.

## Evidence files

- [`performance-report.md`](performance-report.md)
- [`../../../docs/deployment-performance.md`](../../../docs/deployment-performance.md)
- [`../../../scripts/benchmark_phase10.py`](../../../scripts/benchmark_phase10.py)
- [`../../../scripts/verify_clean_checkout.py`](../../../scripts/verify_clean_checkout.py)
- [`../../../backend/tests/test_phase10.py`](../../../backend/tests/test_phase10.py)
- [`../phase-09/security-report.md`](../phase-09/security-report.md)

The generated benchmark JSON, caches, browser inspector output, screenshots, build
output, and test traces were transient verification artifacts and were removed after
their results were reviewed and recorded.

## Known limitations

- Compose remains a single-host demonstration topology, not a high-availability or
  horizontally scalable deployment.
- A public deployment still requires an authenticated, authorized, TLS-terminating,
  rate-limiting gateway; these controls are intentionally outside the demo stack.
- The trained `joblib` directory is a trusted, external deployment input. The path and
  integrity contract are documented and verified, but provenance still depends on the
  channel used to deliver that artifact.
- Image and timing measurements are specific to the recorded arm64 reference machine;
  another architecture or host must rerun Gate 10 before treating the budgets as
  evidence for that environment.
- The API image is 514.01 MiB. It passes the 600 MiB budget but remains dominated by
  the numerical Python runtime and is not optimized for constrained edge deployment.
- The eight accepted Debian base-image advisories expire on 2026-11-20. Gate 9 must be
  rerun against refreshed base images and advisory data before that deadline.
- CIC-IDS2017 limitations, drift, evasion, and low-support attack families still
  require analyst review and prohibit autonomous blocking decisions.
