# Preprocessing and split contract (`features-v1`)

Phase 3 turns the verified CIC-IDS2017 machine-learning CSVs into deterministic, model-ready inputs. The implementation is streaming and uses temporary SQLite indexes for global deduplication, so it does not load the full dataset into memory.

## Reproduce the outputs

After completing the dataset acquisition and manifest steps in [the dataset guide](cic-ids2017.md), run:

```bash
make gate-3
```

The full local gate verifies the committed contracts and unit tests, then writes ignored generated artifacts to:

- `data/processed/phase3/train.csv.gz`
- `data/processed/phase3/validation.csv.gz`
- `data/processed/phase3/final_test.csv.gz`
- `data/processed/phase3/preprocessing-state.json`
- `data/processed/phase3/split-manifest.json`
- `reports/generated/preprocessing.json`
- `reports/generated/preprocessing.md`

The compressed CSVs contain the ordered features followed by `category` and `is_malicious`. Gzip timestamps are fixed, JSON keys are stable, and identical inputs/configuration produce byte-identical outputs.

## Deterministic grouping and splitting

The frozen seed is `42`, with a 70%/15%/15% hash allocation for train, validation, and final-test. A group is a contiguous window of 4096 source rows anchored by capture date and source file. The complete group is assigned by a seeded SHA-256 hash.

Whole-file or whole-day holdouts are not suitable for the first attack-family model: CIC-IDS2017 schedules several families in only one capture, which would leave those classes absent from training. Contiguous source windows preserve local traffic neighborhoods and day/source provenance while allowing supported classes to appear in development holdouts. Direct flow identifiers and timestamps are absent from the machine-learning archive, so a stronger host/session group cannot be reconstructed honestly.

Exact candidate feature/category duplicates are removed globally before any training-only statistic is fitted. The projected final feature/category rows are deduplicated again, and any equality introduced by imputation is removed before writing. No row digest or group can appear in more than one output split.

## Training-only transforms

Only training groups determine:

- constant feature removal;
- exact duplicate-column removal; and
- finite-value arithmetic means used for imputation.

Missing values and positive or negative infinity become missing before transformation. Validation and final-test values are parsed and transformed with the saved state but never contribute to feature selection or imputer fitting.

The frozen contract contains 63 ordered `float64` features. Its schema hash is:

```text
35471c9144bcfe174a4d20e4122d3a673267cb5a7594b1283ae47224aa926152
```

Both port fields are excluded from `features-v1`. In particular, `destination_port` can strongly encode the CIC lab's service layout. A validation-only with-port diagnostic remains preregistered for Phase 4; final-test data cannot be used to make that choice.

## Rare categories and evaluation limits

The taxonomy remains `labels-v1`; Heartbleed maps to `RARE_OTHER`. Its 11 records occupy one contiguous group, which is kept intact in training. Therefore validation and final-test have zero `RARE_OTHER` support. The project will not report standalone held-out performance for this category, and it will never move those records across group boundaries merely to manufacture a metric.

`INFILTRATION` also has very low support, so all per-class results must include support. A stratified random-row split may be generated later only as a leakage diagnostic and never as the headline evaluation.
