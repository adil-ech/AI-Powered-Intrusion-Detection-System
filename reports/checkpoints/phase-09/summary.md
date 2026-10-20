# Phase 9 checkpoint

- **Status:** PASS
- **Date:** 2026-10-20
- **Commit tested:** `859cbe8741b4bea1b97db8dfd40dd18adfcf7250`
- **Environment:** macOS 26.2 (Darwin 25.2.0, arm64); uv 0.12.21 with
  Python 3.12.14; Node 25.2.1; npm 11.6.2; Docker client/server 29.8.2.
- **Decision:** Proceed to Phase 10. Phase 10 has not started.

## Commands and results

| Command | Result |
|---|---|
| `make gate-8` | PASS after the CSP regression fix; the complete downstream integration gate was rerun |
| `make gate-9` | PASS from the exact clean commit recorded above |
| `make format-check lint typecheck` | PASS; 50 Python files formatted, all repository validators and linters passed, mypy checked 44 source files, and TypeScript passed |
| Taste source lint | PASS; 0 failures and 0 warnings |
| Taste browser inspector at 1440, 768, and 390 px | PASS; 0 failures, 3 defended content advisories, and all generated screenshots manually reviewed |

The first Phase 9 integration attempt exposed an inline bootstrap script blocked by the
new Content Security Policy. Because that invalidated the Phase 8 browser contract, the
implementation returned to Phase 8, removed the inline script, reran the complete Gate
8 successfully, and only then reran Gate 9. Browser console output was clean afterward.

## Automated evidence

- Security subset: 24 hostile-input/API tests and 9 CSV/export tests passed.
- Full suite: 23 ML tests, 42 backend tests, and 44 frontend tests passed (109 total,
  no failures or skips).
- Browser integration: one real-model upload, review, export, validation, and recovery
  journey passed.
- Production build: 0.87 kB HTML, 27.51 kB CSS (5.89 kB gzip), and 259.62 kB
  JavaScript (79.02 kB gzip).
- Docker smoke: both hardened services built, became healthy, served the expected API
  and frontend paths, and stopped cleanly.

## Security evidence

- `uv audit --frozen`: 43 locked packages, no known vulnerabilities or adverse project
  statuses.
- `npm audit --audit-level=high --package-lock-only`: 0 vulnerabilities.
- Gitleaks 8.30.1: 21 commits / 1.14 MB and the 1.54 MB working tree scanned with no
  detected leak.
- Trivy 0.76.0 frontend scan: 0 high or critical findings.
- Trivy 0.76.0 API scan: 0 critical findings. All 44 high occurrences map to eight
  exact, currently unfixed Debian advisories with documented compensating controls and
  a 2026-11-20 review deadline. The policy fails on critical, fixable high, unknown,
  incomplete, malformed, or expired exceptions.
- Runtime identities: API effective UID 100; frontend effective UID 101. Both use
  read-only roots, all capabilities dropped, `no-new-privileges`, and bounded temporary
  filesystems.
- Upload contents and caller-selected request IDs were absent from normal logs;
  path-like filenames, archives/model files, oversized streams without Content-Length,
  malformed CSV, non-finite values, and untrusted artifact layouts were rejected.

## Manual checks

- Reviewed the complete landing/upload page at desktop, tablet, and mobile widths.
  There was no clipping, overlap, unreadable type, or broken responsive flow.
- Confirmed the three visual advisories are intentional: the product is an
  interface-led security tool rather than a photographic story, and muted ink is
  reserved for secondary notes while primary content uses stronger contrast.
- Confirmed the restrictive CSP allows the application to load and complete its live
  workflow without an inline-script exception.
- Confirmed scanner containers use read-only repository/image-archive inputs and never
  receive the Docker socket.

## Evidence files

- [`security-report.md`](security-report.md)
- [`../../../docs/security-privacy.md`](../../../docs/security-privacy.md)
- [`../../../backend/tests/test_security.py`](../../../backend/tests/test_security.py)
- [`../../../configs/security-exceptions.json`](../../../configs/security-exceptions.json)

The visual inspector screenshots, scanner JSON, image archives, build output, caches,
and test traces were transient verification artifacts and were removed after review.

## Known limitations

- This remains an unauthenticated, single-operator educational demo. A public deployment
  still requires TLS, authentication, authorization, upstream rate/connection limits,
  and container CPU/memory quotas.
- `joblib` artifacts remain trusted deployment inputs; integrity validation does not
  replace artifact provenance.
- Eight base-image advisories have no available fixed package at this checkpoint. Their
  narrow exceptions expire on 2026-11-20 and must not be renewed when a fixed base is
  available.
- A timed-out native inference call cannot be forcibly interrupted inside Python; the
  result is discarded, while process isolation and resource quotas remain deployment
  responsibilities.
- CIC-IDS2017 model limitations, drift, evasion, and low-support families still require
  analyst review and prohibit autonomous blocking decisions.
