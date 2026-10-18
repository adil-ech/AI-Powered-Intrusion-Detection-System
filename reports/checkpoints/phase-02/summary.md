# Phase 2 checkpoint

- Status: PASS
- Date: 2026-10-18
- Tested implementation commit: `64ceea7` (`Add a reproducible CIC-IDS2017 audit pipeline`)
- Dataset: CIC-IDS2017 `MachineLearningCSV.zip`
- Archive SHA-256: `c3f26274b36c837ccf28ffd2dbf4582941c30b3ee70a635c6e5b2f87c4727928`
- Local manifest SHA-256: `736a62b381b9f7a1e254768527581a3b1da76d59e1c5fd2ccefe9537a98c5c3b`
- Environment: macOS; Python 3.12.14 through uv 0.12.21; streaming standard-library CSV audit with a temporary SQLite duplicate index
- CI evidence: GitHub Actions `CI` run 39155019956 completed successfully for commit `300b2cd`
- Decision: Phase 2 is complete; Phase 3 may begin.

## Commands run

```bash
make data-manifest RETRIEVED_AT=2026-10-18
make gate-2
make format-check
make lint
make typecheck
make test
make build
docker compose config --quiet
make clean
```

## Automated test result

- Phase 0 contract regression validator: PASS
- Phase 2 repository validator: PASS
- Phase 2 audit tests: 6 passed, 0 failed, 0 skipped
- Complete ML test suite: 7 passed, 0 failed, 0 skipped
- FastAPI tests: 2 passed, 0 failed, 0 skipped
- React tests: 2 passed, 0 failed, 0 skipped
- Python and frontend formatting: PASS
- Python and frontend linting: PASS
- Python and TypeScript type checking: PASS
- Production frontend build: PASS
- Compose configuration validation: PASS
- Complete dataset audit: PASS
- Expected source coverage: 8 of 8 files
- Local manifest verification: PASS
- Normalized schema variants: 1
- Unknown labels: 0
- Invalid numeric cells: 0
- Raw dataset files tracked by Git: 0
- Deterministic report generation: PASS on the committed synthetic fixture

## Full-dataset audit findings

- Rows: 2,830,743
- Normalized columns: 79
- Source labels: 15
- Exact duplicate rows across the dataset: 308,381
- Missing cells: 1,358, all in `flow_bytes_s`
- Positive infinity values: 4,376 (`flow_bytes_s`: 1,509; `flow_packets_s`: 2,867)
- Negative infinity values: 0
- Dataset-wide constant columns: 8
- Repeated source header: `fwd_header_length` at zero-based indexes 34 and 55; values were exact duplicates in every source file
- Majority class: `BENIGN`, 2,273,097 rows (80.3004%)
- Rarest class: `HEARTBLEED`, 11 rows (0.0004%)
- Majority-to-minority row ratio: 206,645.2 to 1

## Manual checks performed

- Confirmed the downloaded archive byte size, SHA-256, and independently published MD5 before extraction.
- Confirmed the archive contains the eight expected machine-learning CSV files and no unexpected source CSV.
- Reviewed all 15 label counts and their file provenance against the frozen `labels-v1` taxonomy.
- Reviewed rare classes: `HEARTBLEED` has 11 rows, `WEB_ATTACK_SQL_INJECTION` has 21, and `INFILTRATION` has 36.
- Reviewed duplicate, missing, positive-infinity, negative-infinity, and invalid-numeric counts.
- Confirmed every file normalizes to the same 79-column schema.
- Confirmed the repeated `Fwd Header Length` columns are exact value duplicates across every file.
- Reviewed leakage candidates. The machine-learning archive omits direct identifiers; `destination_port` remains and is restricted to the preregistered Phase 3 validation experiment.
- Confirmed the official citation and redistribution conditions are recorded in the dataset guide.
- Confirmed the Phase 3 treatment plan covers every observed data-quality issue.

## Evidence files

- `docs/data/cic-ids2017.md`
- `data/source_catalog.json`
- `data/samples/cic_ids2017_synthetic.csv`
- `ml/src/ids_ml/data/audit.py`
- `ml/src/ids_ml/data/catalog.py`
- `ml/src/ids_ml/data/manifest.py`
- `ml/src/ids_ml/data/schema.py`
- `ml/tests/test_data_audit.py`
- `scripts/validate_phase2.py`

The raw archive, extracted CSV files, local checksum manifest, and generated JSON/Markdown audit reports are intentionally ignored by Git. `make clean` removed generated reports, caches, build output, and temporary test artifacts after the results above were recorded.

## Known limitations

- The publisher's download form returned a server error on 2026-10-18. The archive was obtained from a public mirror pinned to revision `811c007f08d693a8a8b4226c197c138391806ce6`; both the mirror's SHA-256 and the independently published original-archive MD5 matched.
- CI validates the catalog, safe fixture, deterministic audit behavior, and raw-data Git boundary. It does not download or scan the 224 MB archive; the complete audit is a local gate backed by the recorded manifest and hashes.
- CIC-IDS2017 is a controlled 2017 lab dataset. Its extreme class imbalance and environment-specific services limit claims about real-world or previously unseen attacks.
- Dataset cleaning is deliberately deferred to Phase 3. Phase 2 records defects without modifying source files.
