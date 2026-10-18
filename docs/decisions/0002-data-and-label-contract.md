# ADR 0002: Data, features, and attack labels

- Status: Accepted
- Date: 2026-10-18
- Dataset: CIC-IDS2017 machine-learning CSV files
- Contract version: `labels-v1`

## Context

CIC-IDS2017 contains labeled flow records collected across multiple days. Raw labels are more granular than the categories the MVP can support honestly, and identifier-like fields can leak the laboratory setup into a model.

Official dataset documentation: <https://www.unb.ca/cic/datasets/ids-2017.html>

## Label normalization

Before lookup, source labels are normalized deterministically:

1. Decode as Unicode and trim surrounding whitespace.
2. Convert to uppercase.
3. Replace every run of non-alphanumeric characters with `_`.
4. Remove leading and trailing underscores.

Examples:

- `Web Attack – Brute Force` becomes `WEB_ATTACK_BRUTE_FORCE`.
- `DoS slowloris` becomes `DOS_SLOWLORIS`.
- `FTP-Patator` becomes `FTP_PATATOR`.

An unrecognized training label is an error. It must not be silently assigned to `RARE_OTHER`.

## Frozen MVP taxonomy

| Product category | Normalized CIC-IDS2017 source labels | Binary target |
|---|---|---|
| `BENIGN` | `BENIGN` | benign |
| `DOS_DDOS` | `DDOS`, `DOS_GOLDENEYE`, `DOS_HULK`, `DOS_SLOWHTTPTEST`, `DOS_SLOWLORIS` | malicious |
| `PORT_SCAN` | `PORTSCAN` | malicious |
| `BRUTE_FORCE` | `FTP_PATATOR`, `SSH_PATATOR` | malicious |
| `WEB_ATTACK` | `WEB_ATTACK_BRUTE_FORCE`, `WEB_ATTACK_SQL_INJECTION`, `WEB_ATTACK_XSS` | malicious |
| `BOTNET` | `BOT` | malicious |
| `INFILTRATION` | `INFILTRATION` | malicious |
| `RARE_OTHER` | `HEARTBLEED` | malicious |

The machine-readable source of truth is [`../../contracts/labels-v1.json`](../../contracts/labels-v1.json).

## Feature contract

The API does not hardcode a manually copied feature list. The active model artifact is authoritative and exposes an ordered `required_features` array and `feature_schema_hash` through `GET /api/v1/model`.

The derivation rule for the first artifact is fixed now:

1. Start with numeric feature columns consistently available across the selected CIC-IDS2017 machine-learning CSV files.
2. Normalize names to lower snake case with a versioned alias table.
3. Exclude target and direct identifiers: `label`, `flow_id`, `source_ip`, `destination_ip`, and `timestamp`.
4. Exclude `source_port` if present.
5. Exclude port features from the default model. A preregistered validation experiment may retain `destination_port` only if it improves group/day holdout performance without introducing unacceptable leakage. The chosen result is frozen before baseline comparison and increments the feature schema version.
6. Remove constants and exact duplicate columns using training data only.
7. Preserve the resulting ordered list in the artifact; inference reorders input by name and never by upload position.

The exact ordered names are derived during the audited preprocessing phase because source-file headers must be inspected rather than guessed. This is a fact-discovery step, not an open API decision: all clients already consume the artifact's `required_features` list.

## Input rules

- Feature values must parse as finite real numbers.
- Empty strings and recognized missing-value markers are accepted as missing only for features whose saved preprocessing pipeline includes imputation.
- Positive and negative infinity are never accepted at inference.
- Required columns may appear in any order.
- Missing required columns reject the request.
- Duplicate column names reject the request after canonical normalization.
- Extra columns are ignored and listed in response warnings.
- `Label` is never required for inference and is ignored with a warning if supplied.
- A maximum of 120 total input columns is enforced.

## Training-data rules

- Exact duplicates are removed before splitting.
- Source file/capture day is retained as split provenance but never used as a model feature.
- Imputation, feature filtering, class weighting, calibration, and thresholds are fit without final-test data.
- Split membership and feature schema are deterministic for the same source manifest and seed.
- Every reported class metric includes sample support.

## Prediction semantics

The binary target is `is_malicious = category != BENIGN`.

At inference:

1. The calibrated binary model produces `malicious_probability`.
2. If that probability is below the artifact's `malicious_threshold`, the predicted category is `BENIGN`.
3. Otherwise, the attack-family model produces a conditional category and `category_confidence`.
4. The MVP does not claim unknown-attack detection. Low confidence is a warning, not an `UNKNOWN` category.

## Consequences

- Frontend and backend can remain schema-driven across future model versions.
- The first exact feature manifest is frozen in Phase 3 and carried by the Phase 5 artifact.
- A model trained with a different feature set must have a new schema version and hash.
- Heartbleed remains visible without claiming a reliable standalone classifier for an extremely rare class.

