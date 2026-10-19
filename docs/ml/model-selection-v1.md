# Model selection and artifact freeze (`ids-rf-v1.0.0`)

Phase 5 selects the two-stage Random Forest that the API will serve. It keeps tuning, calibration, operating-threshold selection, feature-variant choice, and final evaluation in separate, auditable steps.

## Validation partitions

The frozen Phase 3 validation groups are divided deterministically into three complete-group folds:

- `validation_tuning` ranks two binary and two attack-family Random Forest configurations;
- `validation_calibration` fits binary Platt calibration, fits attack-family temperature scaling, and selects the malicious threshold under the `0.03` false-positive-rate ceiling;
- `validation_selection_holdout` decides between the no-port and destination-port feature variants and applies all acceptance checks.

No source-window group crosses these partitions. The sole `INFILTRATION` validation row is assigned to calibration, so tuning and selection reports retain explicit zero support for that category instead of manufacturing evidence.

## Destination-port diagnostic

`make port-variant` replays the raw pipeline and appends `destination_port` only after reproducing the exact Phase 3 deduplication decisions. It checks each emitted base feature row and target against the frozen compressed split, so both feature variants contain identical rows in identical order.

The preregistered policy keeps the default no-port schema unless the port variant improves observed attack-family macro F1 by at least `0.01`, does not reduce binary F1 by more than `0.005`, and does not reduce any supported family recall by more than `0.05`. The port experiment produced no family macro-F1 gain, so its CIC lab-layout leakage risk was not justified.

## Reproduce selection safely

Run selection without final-test predictions:

```bash
make model-selection-report
```

The command verifies final-test file hashes but does not pass final-test rows to a model. It writes ignored evidence under `reports/generated/model-selection/`.

The committed `configs/model-selection-v1.json` freezes:

- feature variant: `without_destination_port`;
- binary candidate: `rf-binary-compact`;
- attack-family candidate: `rf-family-deep`;
- calibration: binary Platt sigmoid and attack-family temperature scaling; and
- threshold objective: maximize malicious recall while false-positive rate remains at most `0.03`.

## Finalization boundary

`make gate-5` checks the frozen contract, runs the Phase 5 tests, and then calls `make finalize-model`. The first successful finalization evaluates the final test and writes exactly one ignored artifact directory at `models/ids-rf-v1/`. Later runs verify that artifact's manifest and recreate reports from saved metrics; they do not reopen final-test rows for predictions.

The artifact contains:

```text
models/ids-rf-v1/
├── pipeline.joblib
├── metadata.json
├── feature-schema.json
├── label-taxonomy.json
├── metrics.json
└── manifest.json
```

Every file except the manifest has a SHA-256 and byte count in `manifest.json`. Loading fails before deserialization if an integrity, version, schema, or required-feature check disagrees.

## Input and prediction guarantees

The inference bundle accepts columns in any order and reorders them to the frozen 63-feature schema. Duplicate, missing, extra, non-finite, or width-mismatched inputs fail clearly. Batch and one-row paths use the same code, probabilities must remain finite and normalized in `[0, 1]`, and serialized predictions must match in-memory predictions within `1e-12`.
