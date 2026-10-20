# Phase 8 checkpoint

- **Status:** PASS
- **Date:** 2026-10-20
- **Commit tested:** `eb201e643545abf4208503c10e861d4c9a8638bf`
- **Environment:** macOS Darwin 25.2.0 arm64; uv 0.12.21 with project Python
  3.12.14; Node 25.2.1; npm 11.6.2; Playwright Chromium and the installed
  `design-taste-frontend` browser inspector.
- **Decision:** proceed to Phase 9.

## Commands run

| Command | Exit | Result |
|---|---:|---|
| `make gate-8` | 0 | Phase validator, ML/API/frontend tests, production build, Docker smoke test, and live browser workflow passed |
| `make format-check lint typecheck` | 0 | Ruff/Prettier formatting, all phase validators, Ruff, ESLint, mypy, and TypeScript passed |
| `node /Users/levi7r/.codex/skills/design-taste-frontend/scripts/lint.mjs frontend/src frontend/index.html` | 0 | Source review completed with 0 failures and 0 warnings |
| `inspect.mjs ... --widths 1440,768,390` | 0 | Responsive screenshots and browser metrics captured with 0 failures |
| `docker compose logs --no-color` | 0 | No unexpected application, proxy, or browser-visible service error was found |

The final `make gate-8` replay was run from the commit named above. It produced a
259.62 kB JavaScript bundle (79.02 kB gzip), a 27.51 kB stylesheet (5.89 kB gzip),
and a 0.94 kB HTML entry. The Compose cleanup trap removed the test containers after
the run.

## Automated test result

- ML: **23 passed**, 0 failed, 0 skipped.
- API: **18 passed**, 0 failed, 0 skipped.
- Frontend: **44 passed**, 0 failed, 0 skipped.
- Total unit, component, API, and ML tests: **85 passed**, 0 failed, 0 skipped.
- Live Playwright integration: **1 passed**, covering the complete real-model journey
  and API restart/recovery.
- Three axe-core WCAG A/AA component checks continue to cover the upload entry,
  analyst dashboard, and error state; no serious or critical violation was reported.
- TypeScript and mypy reported no errors. ESLint and Ruff reported no findings.
- Prettier and Ruff formatting checks passed.
- The Phase 8 validator confirms that production uses the typed live API adapter,
  exposes model readiness and version metadata, retains timeout/cancellation and
  duplicate-submit protections, includes the safe sample, and keeps the E2E evidence
  refresh explicit.

## End-to-end checkpoint

All ten Gate 8 scenarios passed against the clean Docker stack and real serialized
model:

1. The proxy, API, and frontend became healthy from clean containers.
2. The upload page displayed model readiness and consistent model metadata.
3. The server-generated 63-feature input template downloaded successfully.
4. The safe mixed sample uploaded through the live API.
5. The UI reported 6 valid rows, 5 suspicious rows, the expected attack families,
   confidence values, and model version.
6. The suspicious-only view contained five rows and its row-detail dialog opened.
7. Export produced the enriched selected-view CSV with the expected header and five
   data rows.
8. Invalid-schema input produced actionable field-contract feedback.
9. Over-limit input was rejected safely before inference.
10. While the API was stopped, the UI reported temporary unavailability; after the
    restart it recovered and completed a new analysis.

No fixture transport or fixture-only response field remains in the production path.
The frontend, API, model, training-data, and feature-contract versions shown to the
user match the live API response. Browser and service logs contained no unexpected
errors.

## Visual and responsive review

- The installed taste workflow was reapplied to the public upload surface after live
  transport was connected. The final weighted review score is **8.4**.
- The source linter reported 0 failures and 0 warnings. The browser inspector reported
  0 failures at 1440, 768, and 390 pixels.
- Final upload and real-results captures have zero unintended horizontal overflow,
  console errors, broken images, or unloaded fonts on desktop, tablet, and mobile.
- Three advisory inspector warnings are documented and defended in the integration
  review: secondary grey copy, the absence of misleading stock photography, and the
  absence of fabricated process footage.
- The dense analyst dashboard preserves responsive information density rather than
  adopting landing-page composition patterns.

## Evidence files

- [`integration-review.md`](integration-review.md)
- [`taste-final/report.json`](taste-final/report.json)
- [`taste-final/desktop-fold.jpg`](taste-final/desktop-fold.jpg)
- [`taste-final/tablet-fold.jpg`](taste-final/tablet-fold.jpg)
- [`taste-final/mobile-fold.jpg`](taste-final/mobile-fold.jpg)
- [`browser/live-results-desktop.png`](browser/live-results-desktop.png)
- [`browser/live-results-tablet.png`](browser/live-results-tablet.png)
- [`browser/live-results-mobile.png`](browser/live-results-mobile.png)
- [`browser/live-row-detail-desktop.png`](browser/live-row-detail-desktop.png)
- [`browser/invalid-schema-desktop.png`](browser/invalid-schema-desktop.png)
- [`browser/recovered-results-desktop.png`](browser/recovered-results-desktop.png)

## Known limitations

- CIC-IDS2017 is a dated benchmark. The committed sample demonstrates integration
  behavior and is not evidence of current-world detection quality or generalization.
- Jost is requested from Google Fonts and has a system sans-serif fallback. Packaging
  external assets for offline deployment remains part of the later deployment gate.
- The browser E2E suite intentionally refreshes committed checkpoint screenshots only
  when `E2E_EVIDENCE_DIR` is set; routine runs use ignored `test-results` output.
- No unresolved severity-high issue remains within Phase 8 scope.
