# Data workspace

Large and sensitive data is not committed to Git.

- `raw/`: original downloaded dataset files; never modified in place.
- `interim/`: deterministic intermediate data and audit outputs.
- `processed/`: model-ready outputs and split manifests.
- `samples/`: small synthetic or sanitized inputs safe for tests and demos.

The CIC-IDS2017 download and checksum procedure will be implemented in Phase 2.

