# ADR 0003: Model training, evaluation, and release policy

- Status: Accepted
- Date: 2026-10-18
- Primary dataset: CIC-IDS2017

## Decision

The supervised MVP uses two stages:

1. A calibrated binary classifier decides whether a row is benign or suspicious.
2. A calibrated attack-family classifier categorizes rows that cross the malicious threshold.

Random Forest is the first production candidate. Dummy and logistic-regression models are mandatory baselines. XGBoost may be selected only when it provides a meaningful validation improvement that justifies its additional dependency and artifact cost. Isolation Forest is a later research path and does not provide attack categories in the MVP.

## Split policy

- Deduplicate before splitting.
- Use capture/source groups, preferably capture day plus source file, to prevent related flows from crossing splits.
- Maintain training, validation, and untouched final-test manifests.
- Use validation data for hyperparameters, feature decisions, probability calibration, and threshold selection.
- Use the final-test split once after the complete pipeline and taxonomy are frozen.
- A stratified random row split may appear only as a leakage diagnostic, never as the headline result.
- If a class cannot be represented honestly under the group split, revise the taxonomy before final evaluation.

## Metrics

Binary reports must include:

- malicious-class precision, recall, and F1;
- precision-recall AUC;
- ROC AUC as a secondary metric;
- false-positive and false-negative rates;
- confusion matrix;
- selected malicious threshold; and
- class support.

Attack-family reports must include:

- macro F1;
- weighted F1;
- per-class precision, recall, F1, and support;
- confusion matrix; and
- optional top-2 accuracy when it adds diagnostic value.

Confidence reports must include:

- Brier score or log loss;
- calibration/reliability plot; and
- observed accuracy per displayed confidence bucket.

## Model-selection targets

These are pre-final-test engineering targets:

- The selected binary detector must beat the dummy and logistic baselines on the primary group-aware holdout.
- Malicious recall target: at least `0.90`.
- False-positive-rate target: at most `0.03` at the selected threshold.
- Attack-family macro-F1 target: at least `0.75` across retained supported classes.
- No metric is published without split name, threshold where relevant, and support.

If a target proves incompatible with an honest group split, the project returns to the taxonomy or scope decision. It does not lower the target after inspecting final-test predictions.

## Confidence and risk fields

- `malicious_probability` is the calibrated binary probability.
- `category_confidence` is the calibrated conditional probability of the chosen attack family and is `null` for `BENIGN`.
- For `BENIGN`, `confidence = 1 - malicious_probability`.
- For a suspicious prediction, `confidence = malicious_probability * category_confidence`.
- `confidence_status` is `LOW_CONFIDENCE` when `confidence` is below the artifact's `low_confidence_threshold`; otherwise it is `OK`.
- Initial low-confidence threshold: `0.65`, subject to validation-only calibration analysis before artifact freeze.
- `risk_level` is an analyst-priority indicator, not attack severity: `LOW` below `0.65`, `MEDIUM` from `0.65` to below `0.85`, and `HIGH` at or above `0.85`. A `BENIGN` prediction is always `LOW`.

All thresholds are saved in model metadata and exposed by the model endpoint.

## Artifact bundle

The versioned model directory contains:

```text
model-version/
├── pipeline.joblib
├── metadata.json
├── feature-schema.json
├── label-taxonomy.json
├── metrics.json
└── manifest.json
```

`manifest.json` contains SHA-256 hashes for every other artifact file. The API loads only trusted artifacts packaged with or mounted read-only into the service. Uploaded serialized models are never accepted.

Required metadata includes:

- model and schema versions;
- training dataset and source-manifest hash;
- split-manifest hash;
- ordered required features and feature-schema hash;
- label taxonomy;
- thresholds;
- calibration method;
- training timestamp;
- library versions; and
- final-test metrics with support.

## Reproducibility

- Fix and record random seeds.
- Lock dependencies.
- Record training commands and reference hardware.
- Test prediction parity before and after serialization.
- Model-regression tests use the frozen sample and tolerances, not the full dataset in ordinary CI.

