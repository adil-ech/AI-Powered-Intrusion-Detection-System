# Phase 4 checkpoint

- Status: PASS
- Date: 2026-10-19
- Tested implementation commit: `dc2e921` (`Establish the baseline evaluation harness`)
- Dataset: frozen Phase 3 CIC-IDS2017 processed split
- Feature schema: `features-v1`, 63 ordered `float64` features
- Feature schema SHA-256: `35471c9144bcfe174a4d20e4122d3a673267cb5a7594b1283ae47224aa926152`
- Split manifest SHA-256: `045d97e9680d83cce2d408d8f7d1b70e5dbb1ea9609245b896422313289d12ed`
- Baseline artifact SHA-256: `6b10727cd1da6b395feb4dceaf6bbfa5307ebc9164961db8e1dc808a637d7822`
- Environment: macOS; Python 3.12.14 through uv 0.12.21; NumPy 2.5.4; scikit-learn 1.9.1; joblib 1.6.0
- CI evidence: pending checkpoint push
- Decision: Phase 4 is complete; Phase 5 may begin.

## Commands run

```bash
make baseline-report
make baseline-report  # deterministic replay
cmp /private/tmp/ids-baseline-before.joblib models/baselines/baselines-v1.joblib
cmp /private/tmp/ids-calibration-before.svg reports/generated/baselines/calibration.svg
make format-check
make lint
make typecheck
make test
make build
docker compose config --quiet
make gate-4
python3 -B -m json.tool reports/generated/baselines/baselines-v1.json
xmllint --noout reports/generated/baselines/calibration.svg
make clean
```

Every command exited successfully. The replayed artifact and calibration SVG matched byte for byte. The replayed JSON report matched after excluding wall-clock training and inference measurements.

## Automated test result

- Phase 0 contract regression validator: PASS
- Phase 2 data-contract regression validator: PASS
- Phase 3 preprocessing regression validator: PASS
- Phase 4 baseline repository validator: PASS
- Phase 4 evaluation tests: 5 passed, 0 failed, 0 skipped
- Complete ML test suite: 16 passed, 0 failed, 0 skipped
- FastAPI tests: 2 passed, 0 failed, 0 skipped
- React tests: 2 passed, 0 failed, 0 skipped
- Python and frontend formatting: PASS
- Python and frontend linting: PASS
- Python and TypeScript type checking: PASS
- Production frontend build: PASS
- Compose configuration validation: PASS
- Known-value metric calculations: PASS
- Stable confusion-matrix ordering: PASS
- Absent-class and zero-division behavior: PASS
- Same-seed training reproducibility: PASS
- Serialized prediction parity at tolerance `1e-12`: PASS for all three baselines
- Validation/final-test report boundary: PASS
- Full-data baseline replay: PASS

## Full-validation baseline result

Both binary baselines were evaluated on the same 267,926 validation rows at the frozen threshold `0.5`. The validation set contains 216,789 benign and 51,137 malicious rows.

| Binary baseline | Precision | Recall | F1 | PR AUC | ROC AUC | FPR | FNR | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| training-prior dummy | 0.0000 | 0.0000 | 0.0000 | 0.1909 | 0.5000 | 0.0000 | 1.0000 | 0.8091 |
| logistic SGD | 0.9425 | 0.7229 | 0.8183 | 0.9115 | 0.9472 | 0.0104 | 0.2771 | 0.9387 |

The dummy confusion matrix is `[[216789, 0], [51137, 0]]`. The logistic confusion matrix is `[[214534, 2255], [14168, 36969]]`, ordered as `[benign, malicious]`. Logistic Brier score is `0.05330` and log loss is `0.31453`; the dummy Brier score is `0.15608` and log loss is `0.49349`.

The attack-family training-prior baseline was evaluated only on the 51,137 malicious validation rows. It predicts the training-majority `DOS_DDOS` class:

- observed-class macro F1: `0.1641`
- all-contract-class macro F1: `0.1407`
- weighted F1: `0.9554`
- accuracy: `0.9701`
- multiclass Brier score: `0.05923`
- multiclass log loss: `0.18613`

| Attack family | Validation support | F1 |
|---|---:|---:|
| `DOS_DDOS` | 49,609 | 0.9848 |
| `PORT_SCAN` | 359 | 0.0000 |
| `BRUTE_FORCE` | 437 | 0.0000 |
| `WEB_ATTACK` | 461 | 0.0000 |
| `BOTNET` | 270 | 0.0000 |
| `INFILTRATION` | 1 | 0.0000 |
| `RARE_OTHER` | 0 | 0.0000 |

The 4,355-byte joblib artifact stores the scaler and three deterministic baselines. A representative full-data run took about 44 seconds to fit and report on this machine; measured timing and throughput remain in the generated report rather than being treated as deterministic values.

## Manual checks performed

- Confirmed every model uses the shared evaluation functions and frozen grouped validation rows.
- Confirmed the logistic and dummy baselines report the same support, split name, threshold, and label order.
- Reviewed false positives, false negatives, calibration metrics, confusion matrices, and per-class support instead of accepting accuracy alone.
- Confirmed absent `RARE_OTHER` validation support remains explicit instead of disappearing from attack-family metrics.
- Confirmed weighted attack-family F1 is misleading for the majority-only predictor; macro and per-class results remain prominent.
- Confirmed the final-test file is integrity-checked by hash but never passed to a model for predictions.
- Reloaded the serialized artifact and confirmed all probability outputs match their in-memory versions within `1e-12` on 8,192 validation rows.
- Replayed training and confirmed the model artifact and calibration SVG are byte-identical.
- Validated the generated JSON and SVG syntax before removing generated reports and test/build caches.

## Evidence files

- `configs/baselines-v1.json`
- `docs/ml/baselines-v1.md`
- `ml/src/ids_ml/evaluation/config.py`
- `ml/src/ids_ml/evaluation/data.py`
- `ml/src/ids_ml/evaluation/metrics.py`
- `ml/src/ids_ml/evaluation/models.py`
- `ml/src/ids_ml/evaluation/report.py`
- `ml/tests/test_evaluation.py`
- `scripts/validate_phase4.py`

The generated JSON, Markdown, and calibration reports, caches, build output, and temporary replay copies were removed after recording these results. The ignored baseline artifact remains local because Phase 5 needs the reference model for candidate comparison.

## Known limitations

- Logistic recall is `0.7229`, below the Phase 5 target of `0.90`; this is a reference baseline, not the selected detector.
- Logistic false-negative rate is `0.2771`, so it is not yet suitable as the production operating point.
- The attack-family prior baseline recognizes only the majority class despite its high weighted F1 and accuracy.
- `INFILTRATION` has one validation row and `RARE_OTHER` has none, so their held-out family performance cannot be estimated honestly here.
- The logistic baseline uses one deterministic streaming SGD epoch for bounded-memory reproducibility, not exhaustive optimizer convergence or hyperparameter tuning.
- The preregistered destination-port feature comparison remains a validation-only Phase 5 selection experiment.
- Final-test status is **SEALED — NOT EVALUATED**; no Phase 4 result was selected using final-test performance.
- CI exercises the harness on a safe synthetic fixture and cannot train against the ignored local CIC-IDS2017 dataset.
