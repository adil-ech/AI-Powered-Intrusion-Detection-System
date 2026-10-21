# Third-party notices

This repository's original source is MIT licensed. It depends on third-party software
whose own licenses continue to apply. Lockfiles are the authoritative version inventory;
this file summarizes direct dependencies and redistributed assets for the `0.1.0` MVP
release candidate.

## Runtime libraries

| Component | License |
|---|---|
| FastAPI | MIT |
| joblib | BSD-3-Clause |
| NumPy | BSD-3-Clause and bundled component licenses recorded by its distribution |
| python-multipart | Apache-2.0 |
| scikit-learn | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| React and React DOM | MIT |

The full transitive Python and npm dependency versions are pinned in `uv.lock` and
`frontend/package-lock.json`. Their installed distributions contain the complete
license texts and notices.

## Development and verification tools

Playwright and TypeScript are Apache-2.0 licensed. Vite, Vitest, ESLint, and Prettier
are MIT licensed. Docker base images contain Debian or Alpine packages governed by
their respective package licenses; the image package inventory is reviewed by the
security gate.

## Jost font

The frontend redistributes the Jost Latin WOFF2 font under the SIL Open Font License
1.1. Its complete license is stored at
[`frontend/public/fonts/OFL.txt`](frontend/public/fonts/OFL.txt). The release asset's
SHA-256 is `235d8f8964bfdf105fc0c3e4c77b5e70f31bee1dad611d59318b5f2a5cb64d90`.

## CIC-IDS2017

The raw CIC-IDS2017 archive is not redistributed in this repository. The bundled
six-row feature sample is sanitized demonstration input derived from training-split
feature vectors and contains no labels or network identifiers. Dataset attribution,
the required paper citation, official source, retrieval history, and source hashes are
recorded in [`docs/data/cic-ids2017.md`](docs/data/cic-ids2017.md).
