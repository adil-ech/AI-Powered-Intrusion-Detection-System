# Safe samples

Only small synthetic or explicitly sanitized demo inputs may be committed here. No sample should contain real or sensitive network identifiers.

The browser demo uses [`../../frontend/public/samples/ids-demo-mixed.csv`](../../frontend/public/samples/ids-demo-mixed.csv). Its six rows contain only the frozen model's numeric features and invented `demo-*` row IDs. The feature vectors were selected deterministically from the training split—not the final test split—to exercise benign, DoS/DDoS, port-scan, brute-force, web-attack, and botnet results. Labels, source files, ports, addresses, timestamps, and capture identifiers are not included. This sample is an integration fixture, not evaluation evidence.
