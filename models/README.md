# Model artifacts

Generated model bundles are ignored by Git. A model becomes an application dependency only after its manifest, schema, metrics, and integrity hashes pass Gate 5.

Gate 5 selected `ids-rf-v1.0.0`. Its local directory is `models/ids-rf-v1/`; the committed model card records the expected manifest and pipeline hashes. Phase 6 must load it through the integrity-checking artifact loader rather than deserializing an arbitrary uploaded model.
