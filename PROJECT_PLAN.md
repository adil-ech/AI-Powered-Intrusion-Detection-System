# AI-Powered Intrusion Detection System — Project Plan

## 1. Expanded project description

The AI-Powered Intrusion Detection System is a full-stack machine-learning application that analyzes network-flow records and estimates whether each flow is benign or malicious. For suspicious traffic, it predicts an attack family, reports a calibrated confidence score, assigns a risk level, and presents the results in an analyst-friendly dashboard.

The project covers the complete ML lifecycle:

- ingesting and validating labeled network-flow data;
- cleaning data and preventing train/test leakage;
- training, evaluating, and versioning classification models;
- serving predictions through a FastAPI backend;
- uploading traffic-feature CSV files through a React interface;
- reviewing, filtering, visualizing, and exporting prediction results; and
- running the application reproducibly with Docker.

The initial product is a **batch network-flow analyzer**, not a packet sniffer or automated firewall. This keeps the first version achievable while still demonstrating cybersecurity knowledge, data engineering, machine learning, API design, frontend development, and deployment.

## 2. Product goals

### Primary goals

1. Classify each uploaded flow as benign or suspicious.
2. Categorize suspicious flows into supported attack families.
3. Show calibrated confidence rather than an unqualified raw probability.
4. Make false positives, class-level recall, and dataset limitations visible.
5. Provide a reproducible path from raw dataset to deployed application.
6. Let a reviewer run the complete demo with one Docker Compose command.

### MVP non-goals

- Capturing packets directly from a live network interface.
- Automatically blocking hosts or changing firewall rules.
- Claiming detection of attacks not represented by the training data.
- Acting as a production SIEM, IDS, or replacement for tools such as Suricata.
- Training directly from uploaded user files in the web application.
- Accepting raw PCAP files in the first release.

These are possible later extensions after the batch feature-based workflow is reliable.

## 3. Intended users and main workflow

The MVP is aimed at a security analyst, student, or technical reviewer.

1. The user opens the dashboard and downloads an example input template if needed.
2. The user uploads a CSV containing network-flow features.
3. The backend validates the schema and reports missing, extra, or invalid columns.
4. The trained model scores all valid rows.
5. The dashboard shows totals, suspicious-flow rate, attack distribution, confidence distribution, and a sortable result table.
6. The user filters suspicious traffic, inspects individual records, and exports the enriched results as CSV.

## 4. Recommended dataset strategy

### MVP dataset: CIC-IDS2017

Use the machine-learning CSV files from CIC-IDS2017 for the first version. The official dataset contains labeled bidirectional flow data, attack traffic recorded across several days, and more than 80 CICFlowMeter-derived features. It covers benign traffic and several attack types, including brute force, DoS/DDoS, web attacks, botnet activity, infiltration, port scanning, and Heartbleed.

Official source: <https://www.unb.ca/cic/datasets/ids-2017.html>

### Alternative validation dataset

UNSW-NB15 is useful as a later robustness experiment because it uses a different feature set and attack taxonomy. It should not be silently mixed with CIC-IDS2017; a separate feature adapter and separately trained model would be required.

Official source: <https://research.unsw.edu.au/projects/unsw-nb15-dataset>

### Label design

Keep the original labels in cleaned training data, then map them to a smaller, supportable product taxonomy:

- `BENIGN`
- `DOS_DDOS`
- `PORT_SCAN`
- `BRUTE_FORCE`
- `WEB_ATTACK`
- `BOTNET`
- `INFILTRATION`
- `RARE_OTHER`

The exact mapping must live in a version-controlled configuration file. Classes with too few examples should be grouped or marked unsupported instead of reporting misleading metrics.

### Leakage and data-quality rules

- Normalize column names and label spelling before any analysis.
- Replace positive and negative infinity with missing values.
- Remove exact duplicate rows and document how many were removed.
- Inspect constant and near-constant columns.
- Treat identifiers such as Flow ID, source/destination IP, and timestamps as leakage risks; exclude them from the default model.
- Evaluate destination/source ports carefully. They may be useful, but can also memorize the lab setup. Compare results with and without them.
- Do not use a purely random row split as the headline result. Prefer a group-aware or day-aware holdout so near-identical flows from the same capture do not appear in both training and test data.
- Fit imputers, feature selection, encoders, calibration, and thresholds using training/validation data only.
- Preserve a final untouched test set for the published metrics.

## 5. Machine-learning design

### Recommended two-stage prediction flow

```text
validated flow features
          |
          v
binary detector: benign vs malicious
          |
          +---- benign ----> BENIGN + confidence
          |
          +---- malicious -> attack-family classifier
                                |
                                v
                     category + confidence + risk
```

This structure makes the operational decision explicit and allows the malicious threshold to be tuned for the desired false-positive/false-negative tradeoff. It also avoids letting the large benign class dominate a single multiclass objective.

### Model candidates

1. **Dummy baseline** — establishes the minimum expected performance.
2. **Logistic regression baseline** — provides a simple, interpretable reference.
3. **Random Forest** — recommended first production candidate; robust, understandable, and available in scikit-learn.
4. **XGBoost** — compare against Random Forest after the pipeline is stable.
5. **Isolation Forest** — optional research track trained on benign data; useful as an anomaly score, not as a reliable attack-category classifier.

Do not choose the final model from accuracy alone. Compare the candidates on the untouched holdout using the metrics below, inference cost, artifact size, and probability calibration.

### Preprocessing pipeline

1. Validate required columns and numeric types.
2. Convert non-finite values to missing values.
3. Impute missing numeric values using training-set statistics.
4. Remove excluded identifiers and unsupported fields.
5. Optionally clip extreme values using bounds learned from training data.
6. Apply scaling only to models that need it.
7. Train with class weights or carefully designed sampling on training data only.
8. Calibrate probabilities on a separate validation split.
9. Save preprocessing and model objects as one versioned inference pipeline.

### Evaluation metrics

For benign vs. malicious detection:

- precision, recall, and F1 for the malicious class;
- precision-recall AUC;
- ROC AUC as a secondary metric;
- false-positive rate;
- false-negative rate; and
- confusion matrix at the selected operating threshold.

For attack-family classification:

- macro F1;
- weighted F1;
- per-class precision and recall;
- per-class support;
- confusion matrix; and
- top-2 accuracy where useful.

For confidence quality:

- reliability/calibration plot;
- Brier score or log loss; and
- coverage at the configured low-confidence threshold.

### Initial acceptance targets

These are engineering targets, not claims that should be published before measurement:

- outperform the dummy and logistic baselines on the held-out group/day split;
- malicious recall of at least 0.90, subject to a documented false-positive rate;
- false-positive rate at or below 0.03 on the held-out split;
- macro F1 of at least 0.75 for attack families retained in the supported taxonomy;
- no class metric reported without its sample count; and
- probabilities calibrated well enough that confidence buckets approximately match observed correctness.

If a target is missed, document the result and revise the scope or taxonomy rather than tuning on the final test set.

## 6. Application architecture

```text
                         training workflow
CIC-IDS2017 CSVs -> cleaning -> feature pipeline -> evaluation report
                                                -> versioned model artifact
                                                           |
                                                           v
React dashboard -> FastAPI REST API -> schema validation -> inference service
       ^                  |                                  |
       |                  +-> model metadata                 v
       +---- results, summaries, filters, export <---- predictions
```

### Components

- **Training package:** dataset preparation, exploratory reports, model training, calibration, evaluation, and artifact creation.
- **FastAPI service:** validation, inference, result formatting, model metadata, limits, and health checks.
- **React application:** file upload, validation feedback, summary visualizations, filters, row details, and CSV export.
- **Artifact store for MVP:** a local, read-only model directory mounted into the API container.
- **Docker Compose:** starts the API and web application together.

Avoid a database in the first version unless persistent history becomes a requirement. Keeping upload results in the browser or returning them directly from the API makes the demo smaller and reduces privacy concerns.

## 7. API contract

Use a versioned prefix such as `/api/v1`.

### `GET /health`

Returns service health and whether a model is loaded.

### `GET /api/v1/model`

Returns model name, model version, supported feature schema, attack taxonomy, training dataset, decision threshold, and creation timestamp.

### `GET /api/v1/input-template`

Downloads a header-only CSV or a small safe example file.

### `POST /api/v1/predictions`

Accepts one or more JSON feature records for integration testing and programmatic use.

### `POST /api/v1/predictions/file`

Accepts a CSV upload up to a configured size/row limit and returns:

- row identifier;
- `is_suspicious`;
- predicted attack category;
- calibrated confidence;
- malicious probability;
- risk level;
- validation warnings; and
- aggregate counts.

For the MVP, use synchronous processing with a conservative row limit. Introduce background jobs only when real files exceed the acceptable request time.

### Error behavior

Use consistent structured errors for unsupported file type, oversized file, missing columns, duplicate columns, invalid numeric values, no valid rows, model unavailable, and internal inference failure. Never return a Python traceback to the client.

## 8. Frontend requirements

### Main screen

- Short description of what the model can and cannot detect.
- Drag-and-drop CSV upload with browse button.
- Input-template download link.
- File name, size, row count, and validation state.
- Clear loading, success, empty, and failure states.

### Results dashboard

- Total analyzed flows.
- Benign and suspicious counts and percentages.
- High-risk count.
- Attack-family distribution chart.
- Confidence distribution chart.
- Sortable, filterable, paginated results table.
- Filters for suspicious status, category, risk, and minimum confidence.
- Row-detail view showing input values and prediction output.
- Export of the enriched result set.
- Model/version information visible from the UI.

### Confidence presentation

- Label scores below the configured threshold as `LOW_CONFIDENCE`.
- Do not present confidence as certainty.
- Display a short explanation that confidence reflects the model and its training distribution.
- Keep “unknown attack” separate from a low-confidence known-category prediction if an unknown-detection feature is added later.

## 9. Security and privacy requirements

Because this is a security product, basic application security is part of the demo quality:

- accept CSV only in the MVP and verify content, not just the extension;
- enforce file-size, row-count, column-count, and processing-time limits;
- process uploads in memory or delete temporary files immediately after use;
- never log full uploaded traffic rows by default;
- escape values displayed in the UI;
- neutralize spreadsheet formula prefixes when exporting user-controlled cells;
- restrict CORS to the configured frontend origin;
- use trusted, packaged model artifacts only—never unpickle uploaded models;
- run containers as non-root users;
- pin production dependencies and scan them in CI; and
- document that network metadata may be sensitive.

## 10. Proposed repository structure

```text
AI-Powered-Intrusion-Detection-System/
├── README.md
├── PROJECT_PLAN.md
├── LICENSE
├── .env.example
├── .gitignore
├── docker-compose.yml
├── data/
│   ├── README.md
│   ├── raw/                 # gitignored
│   ├── interim/             # gitignored
│   ├── processed/           # gitignored or small samples only
│   └── samples/             # safe demo inputs
├── models/                  # artifacts normally gitignored
├── ml/
│   ├── configs/
│   │   ├── features.yaml
│   │   └── labels.yaml
│   ├── src/ids_ml/
│   │   ├── data.py
│   │   ├── features.py
│   │   ├── labels.py
│   │   ├── train.py
│   │   ├── evaluate.py
│   │   └── artifacts.py
│   ├── notebooks/
│   └── tests/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── main.py
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── pages/
│   │   └── types/
│   ├── tests/
│   └── Dockerfile
├── docs/
│   ├── architecture.md
│   ├── model-card.md
│   └── api-examples.md
└── .github/workflows/
    └── ci.yml
```

## 11. Implementation roadmap

The estimates assume one developer working part-time. A focused full-time build can compress the schedule.

Execution is controlled by the phase gates in [`IMPLEMENTATION_WORKFLOW.md`](IMPLEMENTATION_WORKFLOW.md). A phase must pass its automated tests, manual checks, and recorded checkpoint before work begins on the next phase.

### Phase 0 — Project foundation (1–2 days)

Tasks:

- Create the repository structure and Python/Node project configuration.
- Add linting, formatting, tests, environment examples, and pre-commit hooks.
- Create Dockerfiles and a minimal Docker Compose setup.
- Write the initial README with setup commands and scope limitations.

Deliverable: empty but runnable frontend/backend skeleton with health check.

### Phase 1 — Data audit and preparation (4–6 days)

Tasks:

- Download the CIC-IDS2017 machine-learning CSVs outside Git.
- Generate a data-quality report: shape, labels, missing/non-finite values, duplicates, constants, and class balance.
- Implement deterministic column normalization and label mapping.
- Decide the supported feature set and document excluded leakage-prone fields.
- Build group/day-aware train, validation, and test manifests.
- Produce a small synthetic or sanitized sample CSV for tests and the demo.

Deliverable: repeatable preprocessing command plus a versioned data report and split manifest.

### Phase 2 — Modeling and evaluation (5–7 days)

Tasks:

- Train dummy and logistic-regression baselines.
- Train a class-weighted Random Forest binary detector.
- Train the attack-family classifier on malicious training rows.
- Compare XGBoost if it improves holdout performance enough to justify the dependency.
- Tune the binary operating threshold on validation data.
- Calibrate probabilities.
- Evaluate once on the untouched test split.
- Generate metrics, confusion matrices, calibration plots, and feature-importance reports.
- Save the complete inference pipeline and machine-readable metadata.
- Write a model card covering data, metrics, limitations, and ethical/security considerations.

Deliverable: versioned model artifact with an evaluation report and model card.

### Phase 3 — FastAPI backend (3–5 days)

Tasks:

- Load and verify the artifact at startup.
- Implement health and model-metadata endpoints.
- Implement feature-schema validation.
- Implement JSON and CSV batch prediction endpoints.
- Add request limits and structured error responses.
- Return aggregate statistics and row-level results.
- Add unit and integration tests, including malformed files.
- Add generated OpenAPI examples.

Deliverable: tested inference API runnable locally and in Docker.

### Phase 4 — React dashboard (4–6 days)

Tasks:

- Load and follow the installed `design-taste-frontend` skill before frontend design or implementation, applying its full workflow to public-facing/entry surfaces and respecting its dashboard scope limitation.
- Build the upload and validation flow.
- Add summary cards and attack/confidence charts.
- Add the filterable results table and row-detail view.
- Add enriched CSV export.
- Add model-information and limitation panels.
- Add responsive styling, accessibility labels, and error states.
- Add component tests and one end-to-end upload test.

Deliverable: complete browser demo connected to the API.

### Phase 5 — Integration and deployment (3–4 days)

Tasks:

- Finalize non-root production containers.
- Wire services with Docker Compose and environment variables.
- Add CI for Python and frontend linting, tests, and builds.
- Benchmark upload size and inference latency on a documented machine.
- Run dependency and container scans.
- Test the setup from a clean clone.

Deliverable: one-command local deployment and passing CI.

### Phase 6 — Portfolio polish (2–3 days)

Tasks:

- Add screenshots or a short demo recording.
- Add architecture and data-flow diagrams.
- Add reproducible commands and example API calls.
- Explain measured model performance honestly.
- Document limitations, likely dataset drift, and the roadmap.

Deliverable: portfolio-ready repository and demo.

## 12. Prioritized backlog

### Must have

- Reproducible CIC-IDS2017 cleaning and split pipeline.
- Binary and attack-family models.
- Calibrated confidence and configurable malicious threshold.
- Saved feature schema and model metadata.
- CSV upload and strict validation.
- Results dashboard, filtering, and export.
- API/backend/frontend tests.
- Docker Compose and setup documentation.
- Model card and visible limitations.

### Should have

- Random Forest versus XGBoost comparison.
- Global feature-importance view.
- Downloadable input template.
- CI dependency scanning.
- Performance benchmark.
- Accessibility and responsive UI pass.

### Could have

- Isolation Forest anomaly score beside supervised predictions.
- Per-row explanations using a carefully benchmarked method.
- Async job queue for very large uploads.
- Prediction history with a database.
- Authentication and analyst roles.
- Raw PCAP-to-flow conversion using a separate, sandboxed worker.
- Live flow ingestion from Zeek, Suricata, or CICFlowMeter.
- Drift monitoring and scheduled retraining.

## 13. Test strategy

### Data and ML tests

- Column normalization is deterministic.
- Original labels map to the expected attack family.
- Train, validation, and test groups do not overlap.
- No preprocessing step is fitted on test data.
- Training with a fixed seed produces equivalent metrics within tolerance.
- Saved and reloaded pipelines return equivalent predictions.
- A model regression test fails if critical holdout metrics drop beyond tolerance.

### Backend tests

- Valid JSON and CSV inputs return the documented schema.
- Missing, extra, duplicate, non-numeric, infinite, and empty inputs are handled.
- File and row limits are enforced.
- Model-unavailable errors are safe and clear.
- Exported fields cannot inject spreadsheet formulas.

### Frontend tests

- Upload states and API errors are visible.
- Summary values match mocked result rows.
- Filters and sorting behave correctly.
- Export contains the filtered or full result set as specified.
- Keyboard navigation and labels work for core actions.

### End-to-end test

Start the Docker Compose stack, upload a fixed sample file, verify the expected summary and at least one row, export the results, and verify health/model metadata.

## 14. Definition of done for the MVP

The MVP is complete when:

1. A clean clone starts with documented commands and `docker compose up --build`.
2. The repository includes a safe sample file and input template, but not the full dataset.
3. The training pipeline can recreate the published artifact from documented dataset inputs.
4. The model is evaluated on a non-random group/day-aware holdout.
5. Every reported metric includes the split, threshold, and class support.
6. The API validates input and returns predictions with calibrated confidence.
7. The React UI uploads, summarizes, filters, inspects, and exports results.
8. Automated data, backend, frontend, and end-to-end tests pass.
9. The model card clearly states that results from a benchmark dataset do not prove production-network performance.
10. No upload is retained or logged by default.

## 15. Main risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Random split leakage | Unrealistically high scores | Use day/group-aware holdout and deduplicate before splitting |
| Severe class imbalance | Rare attacks are ignored | Use class-level metrics, weights, grouping, and support thresholds |
| Lab-specific identifiers | Model memorizes the capture environment | Exclude identifiers and compare port/no-port models |
| Uncalibrated probabilities | Misleading confidence display | Use validation-only calibration and reliability plots |
| Schema mismatch in uploads | Failed or incorrect inference | Package the exact schema and return actionable validation errors |
| Dataset-to-real-world drift | Poor production performance | State limitations, collect representative data, and add drift monitoring later |
| Oversized or malicious uploads | Resource exhaustion or injection | Enforce limits, parse defensively, avoid persistence, sanitize exports |
| Too much MVP scope | Incomplete demo | Keep live capture, blocking, auth, history, and PCAP ingestion post-MVP |

## 16. First implementation sequence

Start with this order to reduce rework:

1. Scaffold repository, tests, and Docker health-check application.
2. Implement and test canonical feature names and label taxonomy.
3. Build the data audit before training any model.
4. Freeze the data split manifest.
5. Establish baselines, then train the Random Forest two-stage pipeline.
6. Calibrate, evaluate, and freeze an artifact plus metadata.
7. Define API schemas from the frozen artifact.
8. Build batch inference and error handling.
9. Build the dashboard against fixture responses, then connect the real API.
10. Add integration tests, clean-clone verification, and portfolio documentation.

This sequence makes the feature schema and inference contract the boundary between ML, backend, and frontend work.
