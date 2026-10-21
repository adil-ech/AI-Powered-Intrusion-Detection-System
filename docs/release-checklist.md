# MVP release checklist

Release candidate: `0.1.0`

Checkpoint date: 2026-10-21
Tested commit: `3ea8064b37ef257818de832f6c7603b97ef7194c`
Result: `PASS`

## Scope and evidence

- [x] Phases 0–10 have committed `PASS` summaries.
- [x] Product, data, feature, label, model, API, and deployment boundaries agree.
- [x] Final-test metrics include split, support, error rates, and limitations.
- [x] Approved desktop, tablet, mobile, error, recovery, and detail screenshots exist.
- [x] The six-row sample contains no network identifier or source label.
- [x] Dataset citation, project license, font license, and third-party notices exist.

## Reproduction and security

- [x] Dependencies are locked and Docker bases are pinned by digest.
- [x] The model artifact path, trust requirement, manifest, and version are documented.
- [x] `.env.example` contains every required runtime setting.
- [x] Upload retention, logging, and export behavior are documented.
- [x] Non-production controls and required upstream protections are prominent.
- [x] Security exceptions remain explicit, unfixed, and unexpired through 2026-11-20.

## Final gate

The release owner must run the following from the exact clean candidate commit and
record its hash in the Phase 11 checkpoint:

- [x] `make format-check`
- [x] `make lint`
- [x] `make typecheck`
- [x] `make test`
- [x] `make build`
- [x] `make security`
- [x] `make smoke`
- [x] `make test-e2e`
- [x] `make release-check`
- [x] Manual README journey, sample explanation, filtered export, shutdown, and
  first-time-evaluator review

All final items passed on the exact commit above. No Git tag is created automatically.
Any code, model, contract, dependency, or runtime change after the tested commit requires
the affected gate and all downstream release checks to be rerun.
