# API contract v1

- Status: Accepted for Phase 0
- Base prefix: `/api/v1`
- Transport: JSON over HTTP, except CSV upload/template endpoints
- Machine-readable examples: [`../contracts/api-v1/`](../contracts/api-v1/)

## General rules

- JSON uses UTF-8 and snake-case property names.
- Timestamps use UTC RFC 3339 strings.
- Probabilities are finite numbers in `[0, 1]`.
- Request IDs are opaque strings and appear in success and error responses.
- Every response also returns its request ID in the `X-Request-ID` header.
- The API never returns Python tracebacks or uploaded rows inside an error.
- The active model metadata is authoritative for required features and thresholds.

## Health endpoints

### `GET /health`

Process liveness. It returns `200` when the process can serve HTTP even if the model is not ready.

```json
{
  "status": "ok"
}
```

### `GET /ready`

Readiness. It returns `200` only when the artifact has passed integrity and compatibility checks; otherwise it returns `503`.

```json
{
  "status": "ready",
  "model_version": "0.1.0-example"
}
```

## Model metadata

### `GET /api/v1/model`

Returns the artifact identity, required input schema, categories, and thresholds. See [`model-response.example.json`](../contracts/api-v1/model-response.example.json).

The example contains a deliberately shortened synthetic `required_features` array. Production metadata contains the complete ordered feature list generated from the artifact.

Required fields:

| Field | Type | Meaning |
|---|---|---|
| `model_name` | string | Stable model family name |
| `model_version` | string | Immutable artifact version |
| `artifact_status` | `READY` | Integrity-checked artifact state |
| `training_dataset` | string | Dataset identity |
| `feature_schema_version` | string | Version of canonical feature contract |
| `feature_schema_hash` | string | Hash of ordered names and types |
| `required_features` | string array | Complete ordered required input fields |
| `attack_categories` | string array | Supported output categories |
| `thresholds` | object | Malicious, low-confidence, and high-risk thresholds |
| `created_at` | timestamp | Artifact creation time |

## Input template

### `GET /api/v1/input-template`

Returns `text/csv` with a `row_id` column, the active model's required headers, and one clearly marked `synthetic-example` row built from the artifact's finite imputation values. The response includes the model version, schema version, and schema hash as headers.

## JSON predictions

### `POST /api/v1/predictions`

Maximum: 1,000 records.

```json
{
  "records": [
    {
      "row_id": "client-row-1",
      "features": {
        "flow_duration": 1200,
        "total_fwd_packets": 8,
        "total_backward_packets": 6
      }
    }
  ]
}
```

`row_id` is optional but must be unique within the request when supplied. If omitted, the server assigns a one-based string identifier.

JSON feature names use the same canonicalization as CSV headers. Values must be JSON numbers; strings, booleans, nulls, NaN, and infinities are invalid and are never coerced.

## CSV predictions

### `POST /api/v1/predictions/file`

- Content type: `multipart/form-data` with one `file` part.
- File type: UTF-8 comma-separated CSV.
- Maximum size: 10 MiB.
- Maximum data rows: 10,000.
- Maximum columns: 120.
- Required column order is flexible; names are canonicalized.
- An optional `row_id` column is preserved; otherwise one-based IDs are assigned.
- Extra columns are ignored and reported as warnings.

Structural failures reject the request. Row-level value failures are reported in `row_errors`; valid rows are still scored. If every row is invalid, the request returns `422`.

## Batch prediction response

See [`prediction-response.example.json`](../contracts/api-v1/prediction-response.example.json).

Top-level fields:

| Field | Type | Meaning |
|---|---|---|
| `request_id` | string | Correlation identifier |
| `status` | `COMPLETE` or `PARTIAL_SUCCESS` | Whether all rows were valid |
| `model` | object | Name, version, and feature-schema version used |
| `summary` | object | Aggregate valid/invalid and category counts |
| `predictions` | array | One entry for every valid row |
| `row_errors` | array | One entry for every invalid row |
| `warnings` | string array | Request-level nonfatal notices |

User-visible prediction fields:

| Field | Type | Meaning |
|---|---|---|
| `row_id` | string | Client ID or generated one-based row ID |
| `is_suspicious` | boolean | Whether binary probability crosses the artifact threshold |
| `predicted_category` | category enum | `BENIGN` or predicted attack family |
| `malicious_probability` | number | Calibrated binary probability |
| `category_confidence` | number or null | Conditional attack-family probability; null for benign |
| `confidence` | number | Benign probability or joint suspicious-category confidence |
| `confidence_status` | `OK` or `LOW_CONFIDENCE` | Comparison with artifact threshold |
| `risk_level` | `LOW`, `MEDIUM`, or `HIGH` | Analyst-priority band, not attack severity |
| `warnings` | string array | Row-specific nonfatal notices |

Category enum:

- `BENIGN`
- `DOS_DDOS`
- `PORT_SCAN`
- `BRUTE_FORCE`
- `WEB_ATTACK`
- `BOTNET`
- `INFILTRATION`
- `RARE_OTHER`

Confidence is not certainty. The MVP has no `UNKNOWN` category and makes no novel-attack claim. Scores below the artifact's low-confidence threshold remain predictions but are marked `LOW_CONFIDENCE`.

Risk rules:

- `BENIGN` is always `LOW`.
- Suspicious confidence below `0.65` is `LOW`.
- Suspicious confidence from `0.65` to below `0.85` is `MEDIUM`.
- Suspicious confidence at or above `0.85` is `HIGH`.
- Artifact metadata may replace the numeric cutoffs after validation-only calibration analysis.

## Row errors

```json
{
  "row_id": "8",
  "code": "INVALID_FEATURE_VALUE",
  "message": "One or more feature values are invalid.",
  "fields": ["flow_duration"]
}
```

The API does not echo rejected values.

## Error envelope

```json
{
  "error": {
    "code": "MISSING_REQUIRED_COLUMNS",
    "message": "The uploaded CSV is missing required columns.",
    "details": {
      "columns": ["flow_duration"]
    },
    "request_id": "req_example_02"
  }
}
```

| HTTP status | Use |
|---|---|
| `400` | Malformed request or CSV structure |
| `413` | File or row limit exceeded |
| `415` | Unsupported media type or encoding |
| `422` | Valid structure but unusable schema or no valid rows |
| `500` | Unexpected internal failure with safe message |
| `503` | Model unavailable or incompatible |

Stable v1 error codes include:

- `EMPTY_INPUT`
- `INVALID_CSV`
- `DUPLICATE_COLUMNS`
- `MISSING_REQUIRED_COLUMNS`
- `TOO_MANY_COLUMNS`
- `TOO_MANY_ROWS`
- `FILE_TOO_LARGE`
- `UNSUPPORTED_MEDIA_TYPE`
- `UNSUPPORTED_ENCODING`
- `INVALID_FEATURE_VALUE`
- `NO_VALID_ROWS`
- `MODEL_UNAVAILABLE`
- `INFERENCE_FAILED`
- `INVALID_REQUEST`
- `DUPLICATE_ROW_ID`

Errors expose field or column names when useful, but never rejected cell values, uploaded rows, internal exception messages, or tracebacks.

## Compatibility

- Additive response fields may be introduced within v1.
- Existing fields do not change meaning within v1.
- Removing or renaming a field requires `/api/v2`.
- A new model may remain on API v1 when it satisfies the same response contract; clients discover its feature schema through the model endpoint.
