# Phase 3 checkpoint

- Status: PASS
- Date: 2026-10-18
- Tested implementation commit: `e87c282` (`Build the leak-resistant preprocessing pipeline`)
- Dataset: CIC-IDS2017 `MachineLearningCSV.zip`
- Source manifest SHA-256: `736a62b381b9f7a1e254768527581a3b1da76d59e1c5fd2ccefe9537a98c5c3b`
- Feature schema: `features-v1`, 63 ordered `float64` features
- Feature schema SHA-256: `35471c9144bcfe174a4d20e4122d3a673267cb5a7594b1283ae47224aa926152`
- Split manifest SHA-256: `045d97e9680d83cce2d408d8f7d1b70e5dbb1ea9609245b896422313289d12ed`
- Preprocessing state SHA-256: `e08baee54660d75047e3011350133b39940acdf43d6c8db27c717384158b465b`
- Environment: macOS; Python 3.12.14 through uv 0.12.21; streaming standard-library CSV processing with temporary SQLite duplicate indexes
- CI evidence: GitHub Actions `CI` run 39170250931 completed successfully for commit `93b3133`
- Decision: Phase 3 is complete; Phase 4 may begin.

## Commands run

```bash
PYTHONPATH=ml/src uv run python -m ids_ml.data.cli preprocess ... --write-feature-contract reports/generated/features-v1.candidate.json
make preprocess-data
python3 -B scripts/validate_phase3.py
uv run pytest ml/tests/test_preprocessing.py
make format-check
make lint
make typecheck
make test
make build
docker compose config --quiet
make clean
```

The complete preprocessing pipeline was run once to derive the candidate contract with seed 42 and then run again against the frozen committed contract. Both runs produced the same feature, state, split, and compressed-output hashes.

## Automated test result

- Phase 0 contract regression validator: PASS
- Phase 2 data-contract regression validator: PASS
- Phase 3 repository validator: PASS
- Phase 3 preprocessing tests: 4 passed, 0 failed, 0 skipped
- Complete ML test suite: 11 passed, 0 failed, 0 skipped
- FastAPI tests: 2 passed, 0 failed, 0 skipped
- React tests: 2 passed, 0 failed, 0 skipped
- Python and frontend formatting: PASS
- Python and frontend linting: PASS
- Python and TypeScript type checking: PASS
- Production frontend build: PASS
- Compose configuration validation: PASS
- Full-data contract replay: PASS
- Unknown-label rejection: PASS
- Identical-seed byte determinism: PASS
- Final-test isolation test: PASS
- Output finite-value test: PASS
- Group overlap: 0
- Row-digest overlap: 0
- Duplicate feature/category rows across splits: 0
- Final-test rows used for fitting: 0

## Full-dataset preprocessing result

- Source rows: 2,830,743
- Candidate/projected duplicate rows removed: 596,780
- Model-ready rows: 2,233,963
- Candidate numeric features after policy exclusions: 77
- Frozen features: 63
- Training-only constants removed: 8
- Training-only exact duplicate columns removed: 6
- Source-window groups: 695
- Missing/non-finite replacements after deduplication: 799 in `flow_bytes_s` and 799 in `flow_packets_s`
- Imputation strategy: arithmetic mean fitted on training rows only

| Split | Rows | Groups | Output SHA-256 |
|---|---:|---:|---|
| train | 1,551,712 | 484 | `41a4e49528d710309388856262199474afec97d7fa24ebc9d49b0c60f0796bd2` |
| validation | 267,926 | 85 | `36a6819964181c0970a6127656553c801983adf691faeebb3037eabb717b516c` |
| final_test | 414,325 | 126 | `d52a8d75b7632e0b93e9770aa6de1202637a2be440780ed4e1374dcbb0cd5c18` |

### Category support

| Category | Train | Validation | Final test |
|---|---:|---:|---:|
| `BENIGN` | 1,318,450 | 216,789 | 362,219 |
| `DOS_DDOS` | 223,076 | 49,609 | 49,079 |
| `PORT_SCAN` | 1,242 | 359 | 357 |
| `BRUTE_FORCE` | 6,594 | 437 | 2,121 |
| `WEB_ATTACK` | 1,379 | 461 | 303 |
| `BOTNET` | 933 | 270 | 238 |
| `INFILTRATION` | 27 | 1 | 8 |
| `RARE_OTHER` | 11 | 0 | 0 |

## Manual checks performed

- Reviewed the source schedule and rejected whole-file/day holdouts because several attack families occur in only one capture.
- Reviewed and froze capture-day/source-anchored contiguous 4,096-row windows as the strongest reproducible group available after the machine-learning archive removed host/session identifiers.
- Changed the pre-freeze seed from 1701 to 42 after the first support review so the only intact `RARE_OTHER` group has training support; no model result or final-test prediction was inspected.
- Confirmed every observed category has training support and every category except `RARE_OTHER` has validation and final-test support.
- Kept all 11 Heartbleed/`RARE_OTHER` rows in one group instead of breaking the group to manufacture held-out support.
- Reviewed the with-port policy. `destination_port` remains excluded from `features-v1`; any with-port model is a preregistered validation-only Phase 5 selection experiment and cannot use final-test results for selection.
- Confirmed constants, duplicate-column fingerprints, and imputation means are learned only from training groups.
- Confirmed the compressed outputs have 65 columns in contract order: 63 features followed by `category` and `is_malicious`.
- Independently recomputed each compressed output SHA-256 and confirmed 695 unique group IDs in the split manifest.
- Confirmed the stratified random-row split was not used as a headline split; it remains a Phase 4 leakage diagnostic only.

## Evidence files

- `configs/preprocessing-v1.json`
- `contracts/features-v1.json`
- `docs/data/preprocessing-v1.md`
- `docs/decisions/0003-model-evaluation.md`
- `ml/src/ids_ml/data/labels.py`
- `ml/src/ids_ml/data/preprocess.py`
- `ml/tests/test_preprocessing.py`
- `scripts/validate_phase3.py`

The raw source, processed split CSVs, split manifest, fitted preprocessing state, generated reports, caches, and build output are intentionally ignored by Git. `make clean` removed transient reports, caches, and build/test output after the results above were recorded. The processed Phase 3 inputs remain local because they are the intended starting point for Phase 4.

## Known limitations

- Contiguous row windows are an approximation of related traffic, not true host/session groups. The source ML archive omits direct identifiers and timestamps, and a window boundary may separate related flows.
- `RARE_OTHER` has no honest validation or final-test support, so standalone held-out performance for that category cannot be reported.
- `INFILTRATION` support is extremely small in every split; every later metric must retain its support count.
- Excluding `destination_port` collapses many otherwise identical port-scan records. Phase 5 must evaluate the preregistered with-port variant on validation only before any schema revision.
- CI validates the same behavior on a safe synthetic fixture and verifies the frozen 63-feature contract. It does not download or preprocess the full 2.83-million-row dataset.
