# MVP release checklist

Release candidate: `0.1.0`

Checkpoint date: 2026-10-21

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

- [ ] `make format-check`
- [ ] `make lint`
- [ ] `make typecheck`
- [ ] `make test`
- [ ] `make build`
- [ ] `make security`
- [ ] `make smoke`
- [ ] `make test-e2e`
- [ ] `make release-check`
- [ ] Manual README journey, sample explanation, filtered export, shutdown, and
  first-time-evaluator review

Do not tag or describe the project as a release candidate until every final item passes.
Any code, model, contract, dependency, or runtime change after the tested commit requires
the affected gate and all downstream release checks to be rerun.
