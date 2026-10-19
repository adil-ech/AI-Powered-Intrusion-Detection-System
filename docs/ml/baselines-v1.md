# Baselines and evaluation harness (`baselines-v1`)

Phase 4 establishes honest minimum performance before any production model is selected. Every model uses the same metric functions, the same frozen `features-v1` schema, and the same grouped validation rows.

## Reproduce the baseline report

Generate the local baseline artifact, machine-readable report, human-readable report, and calibration chart with:

```bash
make gate-4
```

Generated outputs are intentionally ignored by Git:

- `models/baselines/baselines-v1.joblib`
- `reports/generated/baselines/baselines-v1.json`
- `reports/generated/baselines/baselines-v1.md`
- `reports/generated/baselines/calibration.svg`

The command verifies all processed-split hashes before training. The model artifact is reloaded immediately, and its probabilities must match the in-memory models within `1e-12`.

## Models

- `binary_dummy_prior` always emits the malicious prevalence learned from training data.
- `binary_logistic_sgd` is a logistic-regression baseline implemented with `SGDClassifier(loss="log_loss")`. A streaming `StandardScaler` is fitted first, then one deterministic, unshuffled epoch is trained in 8,192-row batches with class weights derived from training support.
- `attack_family_prior` emits the malicious-training category distribution and predicts its majority category.

The frozen baseline threshold is `0.5`; it is not tuned. The seed is `42`. These values and all estimator parameters live in `configs/baselines-v1.json`.

## Reported metrics

Binary validation results include malicious precision, recall, F1, PR AUC, ROC AUC, false-positive rate, false-negative rate, a stable `[benign, malicious]` confusion matrix, Brier score, log loss, reliability buckets, and class support. Accuracy is included only as a secondary diagnostic.

Attack-family results include macro F1 over observed validation categories, macro F1 over every contract category, weighted F1, per-class precision/recall/F1/support, the contract-ordered confusion matrix, multiclass Brier score, log loss, and confidence reliability buckets. Absent classes remain in the report with zero support instead of disappearing.

Training time, inference time, throughput, serialized artifact size, SHA-256, runtime versions, and serialization parity are recorded.

## Final-test boundary

The headline split in Phase 4 is **validation**. The final-test file hash is verified for integrity, but its rows are not passed to any model and no final-test prediction or metric is generated. Reports label final test as **SEALED — NOT EVALUATED**.

Phase 5 may compare candidate models and the preregistered destination-port variant using validation only. Final-test scoring occurs once, after the model, feature variant, calibration method, and threshold are frozen.
