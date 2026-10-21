# Changelog

All notable project changes are documented here. The format follows Keep a Changelog,
and the project uses semantic versioning for release identifiers.

## [Unreleased]

- No changes yet.

## [0.1.0] - 2026-10-21

### Added

- Reproducible CIC-IDS2017 acquisition, audit, deduplication, grouped splitting, and
  train-fitted preprocessing workflows.
- Validation baselines and a calibrated two-stage Random Forest with an integrity-
  checked, versioned artifact.
- Versioned FastAPI JSON and CSV inference with bounded partial-success validation,
  readiness, metadata, safe errors, and privacy-safe request logging.
- React upload, sample, summary, filter, row-detail, and formula-safe export workflow.
- Digest-pinned, non-root, read-only Docker services with explicit resources, health
  checks, offline assets, and same-origin proxying.
- Automated formatting, linting, typing, unit, integration, browser, dependency,
  secret, image, runtime, performance, concurrency, restart, and clean-build gates.
- Architecture, model card, security, deployment, demo, troubleshooting, license, and
  release documentation with committed checkpoint evidence.

### Security

- Added strict upload limits, finite-number validation, untrusted-artifact rejection,
  response security headers, environment-scoped CORS, spreadsheet-injection escaping,
  and time-bounded policy exceptions for unfixed base-image advisories.

### Known limitations

- This release is an educational single-host batch demo, not a production IDS or SIEM.
- The model is trained only on CIC-IDS2017 and does not claim contemporary-network or
  novel-attack generalization.
- Authentication, authorization, TLS termination, and upstream rate limiting are
  required before any untrusted-network exposure.
