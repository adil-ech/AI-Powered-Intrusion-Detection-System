# Model card: CIC-IDS2017 two-stage Random Forest

- Model version: `ids-rf-v1.0.0`
- Status: frozen Gate 5 MVP candidate; one-time final-test evaluation complete
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

The final-test split was evaluated once after the complete selection was committed at `585b327`. It contains 414,325 rows: 362,219 benign and 52,106 malicious.

| Metric | Final-test result |
|---|---:|
| Malicious precision | 0.939113 |
| Malicious recall | 0.999616 |
| Malicious F1 | 0.968420 |
| PR AUC | 0.999797 |
| ROC AUC | 0.999948 |
| False-positive rate | 0.009323 |
| False-negative rate | 0.000384 |
| Binary Brier score | 0.001075 |
| Binary log loss | 0.004161 |
| Observed-family macro F1 | 0.918035 |
| All-contract-family macro F1 | 0.786887 |
| Family weighted F1 | 0.999359 |
| Family log loss | 0.007885 |

The binary confusion matrix, ordered `[benign, malicious]`, is `[[358842, 3377], [20, 52086]]`.

| Attack family | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| `DOS_DDOS` | 0.999430 | 0.999980 | 0.999705 | 49,079 |
| `PORT_SCAN` | 0.994118 | 0.946779 | 0.969871 | 357 |
| `BRUTE_FORCE` | 0.999528 | 0.997643 | 0.998584 | 2,121 |
| `WEB_ATTACK` | 0.996700 | 0.996700 | 0.996700 | 303 |
| `BOTNET` | 1.000000 | 0.995798 | 0.997895 | 238 |
| `INFILTRATION` | 1.000000 | 0.375000 | 0.545455 | 8 |
| `RARE_OTHER` | 0.000000 | 0.000000 | 0.000000 | 0 |

`INFILTRATION` remains the clearest limitation: six of eight final-test rows were missed by the family classifier. `RARE_OTHER` remains unmeasurable because it has no honest final-test support. These results do not change the already frozen selection.

## Artifact identity

- Artifact directory: `models/ids-rf-v1/`
- Artifact manifest SHA-256: `dfa7678b89009aa03af89957dde958af20af6f969decdd295ba7209eaa6c3601`
- Serialized pipeline SHA-256: `66cb3e864d11f75338555ffbfc66b12d0dca63ed8f4403ac71a2e1261b20a6ef`
- Serialized pipeline size: 2,796,373 bytes
- Feature schema SHA-256: `35471c9144bcfe174a4d20e4122d3a673267cb5a7594b1283ae47224aa926152`
- Created at: `2026-10-19T17:00:19.120335Z`

The artifact reloaded successfully and matched both binary and family probabilities within `1e-12` on 8,192 selection rows. Subsequent Gate 5 runs verify the saved hashes and metrics without reopening final-test rows for predictions.
