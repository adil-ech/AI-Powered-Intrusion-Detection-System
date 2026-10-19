# Phase 5 checkpoint

- Status: PASS
- Date: 2026-10-19
- Tested implementation commit: `4255bec` (`Document the frozen model results`)
- Selection-freeze commit: `585b327` (`Freeze the Random Forest model selection`)
- Model version: `ids-rf-v1.0.0`
- Selected feature schema: `features-v1`, 63 ordered `float64` features without `destination_port`
- Feature schema SHA-256: `35471c9144bcfe174a4d20e4122d3a673267cb5a7594b1283ae47224aa926152`
- Split manifest SHA-256: `045d97e9680d83cce2d408d8f7d1b70e5dbb1ea9609245b896422313289d12ed`
- Artifact manifest SHA-256: `dfa7678b89009aa03af89957dde958af20af6f969decdd295ba7209eaa6c3601`
- Pipeline SHA-256: `66cb3e864d11f75338555ffbfc66b12d0dca63ed8f4403ac71a2e1261b20a6ef`
- Environment: macOS; Python 3.12.14 through uv 0.12.21; NumPy 2.5.4; scikit-learn 1.9.1; joblib 1.6.0
- CI evidence: pending checkpoint push
- Decision: Phase 5 is complete; Phase 6 may begin.

## Commands run

```bash
make port-variant
make model-selection-report
python3 -B scripts/validate_phase5.py
uv run mypy ml/src/ids_ml/modeling
uv run pytest ml/tests/test_modeling.py
make gate-5  # first run: one-time final-test evaluation and artifact creation
make gate-5  # replay: artifact verification only; final-test predictions not reopened
make format-check
make lint
make typecheck
make test
make build
docker compose config --quiet
make gate-5  # full-regression verification-only run
```

Every command exited successfully. The first successful finalization evaluated final-test predictions once after the complete selection was committed. Both later Gate 5 runs loaded and verified saved artifact metrics and reported `final_test_reopened_for_predictions: false`.

## Automated test result

- Phase 0 contract regression validator: PASS
- Phase 2 data-contract regression validator: PASS
- Phase 3 preprocessing regression validator: PASS
- Phase 4 baseline regression validator: PASS
- Phase 5 selection/artifact validator: PASS
- Phase 5 modeling tests: 7 passed, 0 failed, 0 skipped
- Complete ML test suite: 23 passed, 0 failed, 0 skipped
- FastAPI tests: 2 passed, 0 failed, 0 skipped
- React tests: 2 passed, 0 failed, 0 skipped
- Python and frontend formatting: PASS
- Python and frontend linting: PASS
- Python and TypeScript type checking: PASS
- Production frontend build: PASS
- Compose configuration validation: PASS
- Source-group partition isolation: PASS
- Absent-family calibration-column handling: PASS
- Threshold false-positive constraint: PASS
- Destination-port selection policy: PASS
- Same-seed forest reproducibility within `1e-12`: PASS
- Artifact hash, byte-count, version, schema, and feature-order verification: PASS
- Shuffled-column reordering: PASS
- Missing/extra/duplicate/non-finite feature rejection: PASS
- Batch/one-row probability parity: PASS
- Finalization-before-freeze rejection: PASS
- Actual artifact serialization parity on 8,192 rows: PASS

## Validation-only model selection

The 85 frozen validation groups were divided without overlap:

| Partition | Rows | Groups | Purpose |
|---|---:|---:|---|
| tuning | 88,349 | 28 | rank Random Forest hyperparameters |
| calibration | 88,754 | 30 | fit calibration and select malicious threshold |
| selection holdout | 90,823 | 27 | compare feature variants and apply acceptance checks |

The sole validation `INFILTRATION` row was assigned to calibration. Tuning and selection keep zero support explicit for that family.

Selected estimators:

- binary: `rf-binary-compact` — 40 trees, depth 20, minimum leaf 2, square-root features, 30% bootstrap sample;
- attack family: `rf-family-deep` — 80 trees, depth 26, minimum leaf 1, square-root features, 80% bootstrap sample;
- class weighting: balanced per bootstrap sample;
- binary calibration: Platt sigmoid;
- family calibration: temperature scaling, selected temperature `0.3625`;
- malicious threshold: `0.015`, selected on calibration by maximizing recall under FPR `<= 0.03`.

### Selection-holdout result

| Metric | No port | With destination port |
|---|---:|---:|
| Binary precision | 0.960600 | 0.980944 |
| Binary recall | 1.000000 | 0.999941 |
| Binary F1 | 0.979904 | 0.990351 |
| Binary PR AUC | 0.999902 | 0.999954 |
| False-positive rate | 0.009507 | 0.004503 |
| Observed-family macro F1 | 0.998202 | 0.998202 |

The same-row port replay used schema SHA-256 `1121b20afd3efc014b080a5bd684f232c1c176a417ac8d4b814242dc0f94ad3a`. It changed no base row, target, or grouping. Because it produced zero family macro-F1 gain, it did not meet the preregistered `0.01` improvement required to justify the CIC lab-layout leakage risk. The no-port variant remained selected.

The selected model passed every selection-holdout criterion:

- binary F1 exceeded the same-row dummy (`0.000000`) and logistic (`0.805942`) baselines;
- malicious recall `1.000000` exceeded `0.90`;
- false-positive rate `0.009507` remained below `0.03`;
- observed-family macro F1 `0.998202` exceeded `0.75` and the family-prior baseline `0.196862`.

## One-time final-test result

The committed selection was recomputed and matched the freeze before final-test materialization. The final split contains 414,325 rows: 362,219 benign and 52,106 malicious.

| Binary metric | Result |
|---|---:|
| Precision | 0.939113 |
| Recall | 0.999616 |
| F1 | 0.968420 |
| PR AUC | 0.999797 |
| ROC AUC | 0.999948 |
| False-positive rate | 0.009323 |
| False-negative rate | 0.000384 |
| Brier score | 0.001075 |
| Log loss | 0.004161 |

The confusion matrix, ordered `[benign, malicious]`, is `[[358842, 3377], [20, 52086]]`.

| Attack family | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| `DOS_DDOS` | 0.999430 | 0.999980 | 0.999705 | 49,079 |
| `PORT_SCAN` | 0.994118 | 0.946779 | 0.969871 | 357 |
| `BRUTE_FORCE` | 0.999528 | 0.997643 | 0.998584 | 2,121 |
| `WEB_ATTACK` | 0.996700 | 0.996700 | 0.996700 | 303 |
| `BOTNET` | 1.000000 | 0.995798 | 0.997895 | 238 |
| `INFILTRATION` | 1.000000 | 0.375000 | 0.545455 | 8 |
| `RARE_OTHER` | 0.000000 | 0.000000 | 0.000000 | 0 |

- Observed-family macro F1: `0.918035`
- All-contract-family macro F1: `0.786887`
- Weighted family F1: `0.999359`
- Family log loss: `0.007885`
- Family multiclass Brier score: `0.001095`
- Measured combined inference: 0.635 seconds, approximately 652,779 rows/second on this machine

## Artifact result

The ignored `models/ids-rf-v1/` bundle totals 2,919,202 bytes:

| File | Bytes | SHA-256 |
|---|---:|---|
| `pipeline.joblib` | 2,796,373 | `66cb3e864d11f75338555ffbfc66b12d0dca63ed8f4403ac71a2e1261b20a6ef` |
| `metadata.json` | 11,547 | `669115e5d14ae0b058dac9c91f2b3519baed66f6830a4115face6dae7b2752b3` |
| `feature-schema.json` | 11,324 | `22a19441ec83cea3c4304fbefb6327f21ecf0925623b57b041a51eb2bbc39f25` |
| `label-taxonomy.json` | 1,234 | `328aef052a2e0bb3e11a250e5347f492ab031a27b70d9a18247e5a1347930620` |
| `metrics.json` | 97,941 | `361a5367caed5a5f742ccc422a0a906ed66681c312eae63a005071bb8a9f67f0` |
| `manifest.json` | 783 | manifest hash shown above |

## Manual checks performed

- Reviewed the tuning result before freezing candidate IDs and the no-port feature variant.
- Confirmed the destination-port diagnostic preserved identical rows, labels, group assignments, and base feature values.
- Confirmed the final-test file contributed no predictions, metrics, threshold, calibration, feature, or hyperparameter decision before the freeze commit.
- Reviewed selection and final false-positive/false-negative counts rather than accepting accuracy alone.
- Reviewed per-class support and retained zero-support `RARE_OTHER` explicitly.
- Loaded the actual artifact and confirmed shuffled columns reorder to identical probabilities.
- Compared batch predictions with 16 one-row calls on the actual artifact.
- Confirmed actual artifact binary/family probabilities are finite, bounded, and family-normalized.
- Confirmed actual artifact missing-column input fails clearly.
- Parsed generated JSON and validated calibration SVG XML.
- Re-ran Gate 5 twice after finalization and confirmed both paths verified the saved artifact without final-test prediction access.

## Evidence files

- `configs/model-selection-v1.json`
- `docs/ml/model-selection-v1.md`
- `docs/model-card.md`
- `ml/src/ids_ml/modeling/artifact.py`
- `ml/src/ids_ml/modeling/config.py`
- `ml/src/ids_ml/modeling/data.py`
- `ml/src/ids_ml/modeling/models.py`
- `ml/src/ids_ml/modeling/pipeline.py`
- `ml/src/ids_ml/modeling/port_variant.py`
- `ml/tests/test_modeling.py`
- `scripts/validate_phase5.py`

Generated reports, the same-row port data, baseline artifact, and selected model artifact are intentionally ignored by Git. `make clean` removes transient reports, caches, and build/test output while retaining the intended local processed data and versioned model bundles needed by Phase 6.

## Known limitations

- The final split is derived from the same CIC-IDS2017 environment; this is not cross-dataset or real-network validation.
- Source-window grouping is an approximation because the archive omits host/session identifiers.
- The family classifier recalled only 3 of 8 final `INFILTRATION` rows. This low-support family remains unsuitable for a strong standalone claim.
- `RARE_OTHER` has no validation or final-test support, so no held-out performance estimate exists.
- The low malicious threshold is specific to the calibrated model and frozen data contract; it must not be transferred to another model or dataset.
- Destination port improved binary results but was rejected because it did not improve family macro F1 enough to offset known lab-layout leakage risk.
- Strong CIC-IDS2017 results may reflect dataset artifacts and should not be presented as production IDS performance.
- CI exercises selection and artifact behavior on safe synthetic fixtures; it cannot rebuild the ignored 2.83-million-row local dataset or selected artifact.
