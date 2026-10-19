# Model card: CIC-IDS2017 two-stage Random Forest

- Model version: `ids-rf-v1.0.0`
- Status: selected and frozen; final-test metrics pending the one-time Gate 5 finalization
- Intended use: batch classification of CICFlowMeter-compatible network-flow features for an educational intrusion-detection demo
- Out of scope: packet capture, automated blocking, novel-attack detection, production SIEM replacement, and claims of real-world generalization

## Model design

The artifact contains two class-weighted Random Forest classifiers. The binary forest predicts benign versus malicious traffic. Rows crossing the frozen malicious threshold are categorized by the attack-family forest. Binary probabilities use Platt calibration; family probabilities use one-temperature multiclass calibration.

The selected schema contains the 63 ordered `features-v1` fields and excludes host identifiers, timestamps, source port, and destination port. A same-row validation experiment added destination port, but it produced no attack-family macro-F1 gain and therefore did not clear the preregistered threshold for accepting its lab-layout leakage risk.

## Selection evidence

The selection holdout contains 90,823 rows from 27 source-window groups and was not used for hyperparameter fitting, calibration, or threshold selection.

At malicious threshold `0.015`, the frozen no-port candidate achieved:

- malicious precision: `0.960600`
- malicious recall: `1.000000`
- malicious F1: `0.979904`
- PR AUC: `0.999902`
- ROC AUC: `0.999977`
- false-positive rate: `0.009507`
- observed attack-family macro F1: `0.998202`

It beats the same-row dummy and logistic baselines and passes the preregistered recall, false-positive-rate, and family macro-F1 targets.

## Confidence and thresholds

- Malicious threshold: `0.015`, selected on `validation_calibration` under the `0.03` false-positive-rate ceiling
- Low-confidence threshold: `0.65`
- High-risk threshold: `0.85`
- Binary calibration: Platt sigmoid over the frozen forest score
- Attack-family calibration: deterministic temperature scaling over all contract columns

These scores describe behavior on CIC-IDS2017-derived grouped splits; they are not guarantees for a different network.

## Data and limitations

- Training and evaluation use CIC-IDS2017 machine-learning CSVs after global deduplication and train-fitted preprocessing.
- Contiguous 4,096-source-row windows approximate related traffic because the archive omits host/session identifiers.
- `INFILTRATION` has one validation row, assigned to calibration, and therefore no honest tuning or selection-holdout metric.
- `RARE_OTHER` has no validation or final-test support and cannot receive a held-out per-class estimate.
- CIC-IDS2017 is a controlled lab dataset from 2017. Strong in-dataset metrics can overstate performance on contemporary or operational traffic.
- Destination port remains excluded even though it improves binary F1, because it does not improve family macro F1 enough to justify memorizing the lab service layout.

## Final evaluation

The final-test split remains sealed until `configs/model-selection-v1.json`, this model design, calibration methods, feature variant, and threshold are committed and Gate 5 is run. This section will be updated from the immutable artifact metrics immediately after that one-time evaluation.
