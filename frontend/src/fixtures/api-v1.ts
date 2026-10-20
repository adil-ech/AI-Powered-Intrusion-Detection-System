import type {
  ApiErrorEnvelope,
  AttackCategory,
  BatchPredictionResponse,
  FixtureScenario,
  Prediction,
  PredictionSummary,
  RiskLevel,
  RowError,
} from "../types/api";

const MODEL = {
  name: "cicids2017-two-stage",
  version: "ids-rf-v1.0.0",
  feature_schema_version: "features-v1",
} as const;

function prediction(
  rowId: string,
  category: AttackCategory,
  maliciousProbability: number,
  confidence: number,
  riskLevel: RiskLevel,
  categoryConfidence: number | null = null,
): Prediction {
  const lowConfidence = confidence < 0.65;
  return {
    row_id: rowId,
    is_suspicious: category !== "BENIGN",
    predicted_category: category,
    malicious_probability: maliciousProbability,
    category_confidence: categoryConfidence,
    confidence,
    confidence_status: lowConfidence ? "LOW_CONFIDENCE" : "OK",
    risk_level: riskLevel,
    warnings: lowConfidence
      ? ["Prediction confidence is below the model threshold."]
      : [],
  };
}

function summarize(
  predictions: Prediction[],
  rowErrors: RowError[] = [],
): PredictionSummary {
  const categoryCounts: PredictionSummary["category_counts"] = {};
  for (const row of predictions) {
    categoryCounts[row.predicted_category] =
      (categoryCounts[row.predicted_category] ?? 0) + 1;
  }

  const suspicious = predictions.filter((row) => row.is_suspicious);
  return {
    total_rows: predictions.length + rowErrors.length,
    valid_rows: predictions.length,
    invalid_rows: rowErrors.length,
    benign_rows: predictions.length - suspicious.length,
    suspicious_rows: suspicious.length,
    high_risk_rows: suspicious.filter((row) => row.risk_level === "HIGH")
      .length,
    category_counts: categoryCounts,
  };
}

function response(
  requestId: string,
  predictions: Prediction[],
  rowErrors: RowError[] = [],
  warnings: string[] = [],
): BatchPredictionResponse {
  return {
    request_id: requestId,
    status: rowErrors.length > 0 ? "PARTIAL_SUCCESS" : "COMPLETE",
    model: MODEL,
    summary: summarize(predictions, rowErrors),
    predictions,
    row_errors: rowErrors,
    warnings,
  };
}

const normalRows = [
  prediction("flow-001", "BENIGN", 0.002, 0.998, "LOW"),
  prediction("flow-002", "BENIGN", 0.004, 0.996, "LOW"),
  prediction("flow-003", "BENIGN", 0.001, 0.999, "LOW"),
  prediction("flow-004", "BENIGN", 0.008, 0.992, "LOW"),
  prediction("flow-005", "BENIGN", 0.006, 0.994, "LOW"),
  prediction("flow-006", "BENIGN", 0.003, 0.997, "LOW"),
  prediction("flow-007", "BENIGN", 0.01, 0.99, "LOW"),
  prediction("flow-008", "BENIGN", 0.005, 0.995, "LOW"),
];

const mixedRows = [
  prediction("flow-001", "BENIGN", 0.002, 0.998, "LOW"),
  prediction("flow-002", "DOS_DDOS", 0.993, 0.9675, "HIGH", 0.9743),
  prediction("flow-003", "PORT_SCAN", 0.961, 0.8745, "HIGH", 0.91),
  prediction("flow-004", "BRUTE_FORCE", 0.894, 0.8135, "MEDIUM", 0.91),
  prediction("flow-005", "WEB_ATTACK", 0.782, 0.6647, "MEDIUM", 0.85),
  prediction("flow-006", "BOTNET", 0.73, 0.5767, "LOW", 0.79),
  prediction("flow-007", "BENIGN", 0.01, 0.99, "LOW"),
  prediction("flow-008", "INFILTRATION", 0.66, 0.4686, "LOW", 0.71),
  prediction("flow-009", "BENIGN", 0.006, 0.994, "LOW"),
  prediction("flow-010", "DOS_DDOS", 0.94, 0.8836, "HIGH", 0.94),
  prediction("flow-011", "PORT_SCAN", 0.72, 0.6624, "MEDIUM", 0.92),
  prediction("flow-012", "WEB_ATTACK", 0.45, 0.396, "LOW", 0.88),
  prediction("flow-013", "BRUTE_FORCE", 0.87, 0.7134, "MEDIUM", 0.82),
  prediction("flow-014", "BENIGN", 0.014, 0.986, "LOW"),
];

const edgeRows = [
  prediction(
    '=WEBSERVICE("https://invalid.example")',
    "RARE_OTHER",
    0.62,
    0.434,
    "LOW",
    0.7,
  ),
  prediction("+edge-02", "INFILTRATION", 0.97, 0.5238, "LOW", 0.54),
  prediction("@edge-03", "DOS_DDOS", 0.99, 0.9801, "HIGH", 0.99),
  prediction("-edge-04", "BENIGN", 0.0149, 0.9851, "LOW"),
  prediction("edge-05", "PORT_SCAN", 0.85, 0.714, "MEDIUM", 0.84),
  prediction("edge-06", "BOTNET", 0.52, 0.3536, "LOW", 0.68),
  prediction("edge-07", "WEB_ATTACK", 0.91, 0.8463, "MEDIUM", 0.93),
  prediction("edge-08", "BRUTE_FORCE", 0.995, 0.9154, "HIGH", 0.92),
];

const edgeErrors: RowError[] = [
  {
    row_id: "edge-09",
    code: "INVALID_FEATURE_VALUE",
    message: "One or more feature values are invalid.",
    fields: ["flow_duration"],
  },
  {
    row_id: "edge-10",
    code: "MISSING_FEATURE_VALUE",
    message: "One or more required feature values are missing.",
    fields: ["flow_packets_s", "flow_bytes_s"],
  },
  {
    row_id: "edge-11",
    code: "NON_FINITE_FEATURE_VALUE",
    message: "One or more feature values are not finite.",
    fields: ["packet_length_variance"],
  },
];

export const FIXTURE_RESPONSES = {
  normal: response("req_fixture_normal", normalRows),
  mixed: response("req_fixture_mixed", mixedRows),
  edge: response("req_fixture_edge", edgeRows, edgeErrors, [
    "Three rows were rejected before inference.",
    "Five predictions are below the model confidence threshold.",
  ]),
  empty: response("req_fixture_empty", []),
} satisfies Record<
  Exclude<FixtureScenario, "invalid" | "failure">,
  BatchPredictionResponse
>;

export const FIXTURE_ERRORS = {
  invalid: {
    error: {
      code: "MISSING_REQUIRED_COLUMNS",
      message: "The uploaded CSV is missing required columns.",
      details: {
        columns: ["flow_duration", "total_fwd_packets"],
      },
      request_id: "req_fixture_invalid",
    },
  },
  failure: {
    error: {
      code: "MODEL_UNAVAILABLE",
      message: "The model is not ready to score this request.",
      request_id: "req_fixture_failure",
    },
  },
} satisfies Record<"invalid" | "failure", ApiErrorEnvelope>;

export function getFixture(scenario: FixtureScenario): BatchPredictionResponse {
  if (scenario === "invalid" || scenario === "failure") {
    throw structuredClone(FIXTURE_ERRORS[scenario]);
  }
  return structuredClone(FIXTURE_RESPONSES[scenario]);
}

export function loadFixture(
  scenario: FixtureScenario,
  signal?: AbortSignal,
  delay = 420,
): Promise<BatchPredictionResponse> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      if (signal?.aborted) {
        reject(new DOMException("The request was aborted.", "AbortError"));
        return;
      }

      try {
        resolve(getFixture(scenario));
      } catch (error) {
        reject(error);
      }
    }, delay);

    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timeout);
        reject(new DOMException("The request was aborted.", "AbortError"));
      },
      { once: true },
    );
  });
}
