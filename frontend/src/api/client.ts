import { ATTACK_CATEGORIES } from "../types/api";
import type {
  ApiErrorEnvelope,
  BatchPredictionResponse,
  ModelMetadata,
  Prediction,
  ReadinessResponse,
  RowError,
} from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const REQUEST_TIMEOUT_MS = 30_000;
const UPLOAD_TIMEOUT_MS = 120_000;
export const DEMO_SAMPLE_URL = "/samples/ids-demo-mixed.csv";

type JsonRecord = Record<string, unknown>;

export class ApiClientError extends Error {
  readonly envelope: ApiErrorEnvelope;
  readonly status: number | null;

  constructor(envelope: ApiErrorEnvelope, status: number | null = null) {
    super(envelope.error.message);
    this.name = "ApiClientError";
    this.envelope = envelope;
    this.status = status;
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) && value.every((item) => typeof item === "string")
  );
}

function isFiniteProbability(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1
  );
}

function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!isRecord(value) || !isRecord(value.error)) {
    return false;
  }
  const error = value.error;
  return (
    typeof error.code === "string" &&
    typeof error.message === "string" &&
    typeof error.request_id === "string" &&
    (error.details === undefined || isRecord(error.details))
  );
}

function isReadinessResponse(value: unknown): value is ReadinessResponse {
  return (
    isRecord(value) &&
    value.status === "ready" &&
    typeof value.model_version === "string"
  );
}

function isModelMetadata(value: unknown): value is ModelMetadata {
  if (!isRecord(value) || !isRecord(value.thresholds)) {
    return false;
  }
  return (
    typeof value.model_name === "string" &&
    typeof value.model_version === "string" &&
    value.artifact_status === "READY" &&
    typeof value.training_dataset === "string" &&
    typeof value.feature_schema_version === "string" &&
    typeof value.feature_schema_hash === "string" &&
    isStringArray(value.required_features) &&
    Array.isArray(value.attack_categories) &&
    value.attack_categories.every(
      (category) =>
        typeof category === "string" &&
        ATTACK_CATEGORIES.includes(
          category as (typeof ATTACK_CATEGORIES)[number],
        ),
    ) &&
    isFiniteProbability(value.thresholds.malicious) &&
    isFiniteProbability(value.thresholds.low_confidence) &&
    isFiniteProbability(value.thresholds.high_risk) &&
    typeof value.created_at === "string"
  );
}

function isPrediction(value: unknown): value is Prediction {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.row_id === "string" &&
    typeof value.is_suspicious === "boolean" &&
    typeof value.predicted_category === "string" &&
    ATTACK_CATEGORIES.includes(
      value.predicted_category as (typeof ATTACK_CATEGORIES)[number],
    ) &&
    isFiniteProbability(value.malicious_probability) &&
    (value.category_confidence === null ||
      isFiniteProbability(value.category_confidence)) &&
    isFiniteProbability(value.confidence) &&
    (value.confidence_status === "OK" ||
      value.confidence_status === "LOW_CONFIDENCE") &&
    (value.risk_level === "LOW" ||
      value.risk_level === "MEDIUM" ||
      value.risk_level === "HIGH") &&
    isStringArray(value.warnings)
  );
}

function isRowError(value: unknown): value is RowError {
  return (
    isRecord(value) &&
    typeof value.row_id === "string" &&
    typeof value.code === "string" &&
    typeof value.message === "string" &&
    isStringArray(value.fields)
  );
}

function isBatchPredictionResponse(
  value: unknown,
): value is BatchPredictionResponse {
  if (!isRecord(value) || !isRecord(value.model) || !isRecord(value.summary)) {
    return false;
  }
  const model = value.model;
  const summary = value.summary;
  return (
    typeof value.request_id === "string" &&
    (value.status === "COMPLETE" || value.status === "PARTIAL_SUCCESS") &&
    typeof model.name === "string" &&
    typeof model.version === "string" &&
    typeof model.feature_schema_version === "string" &&
    Object.values(summary).every(
      (item) => typeof item === "number" || isRecord(item),
    ) &&
    typeof summary.total_rows === "number" &&
    typeof summary.valid_rows === "number" &&
    typeof summary.invalid_rows === "number" &&
    typeof summary.benign_rows === "number" &&
    typeof summary.suspicious_rows === "number" &&
    typeof summary.high_risk_rows === "number" &&
    isRecord(summary.category_counts) &&
    Array.isArray(value.predictions) &&
    value.predictions.every(isPrediction) &&
    Array.isArray(value.row_errors) &&
    value.row_errors.every(isRowError) &&
    isStringArray(value.warnings)
  );
}

function localEnvelope(code: string, message: string): ApiErrorEnvelope {
  return {
    error: {
      code,
      message,
      request_id: "client_transport",
    },
  };
}

function requestSignal(signal: AbortSignal | undefined, timeoutMs: number) {
  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort(signal?.reason);
  if (signal?.aborted) {
    abortFromCaller();
  } else {
    signal?.addEventListener("abort", abortFromCaller, { once: true });
  }
  const timeout = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    cleanup: () => {
      window.clearTimeout(timeout);
      signal?.removeEventListener("abort", abortFromCaller);
    },
  };
}

async function parseError(response: Response): Promise<ApiClientError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (isApiErrorEnvelope(body)) {
    return new ApiClientError(body, response.status);
  }
  return new ApiClientError(
    localEnvelope(
      `HTTP_${response.status}`,
      response.status >= 500
        ? "The model service is temporarily unavailable."
        : `The request was rejected with status ${response.status}.`,
    ),
    response.status,
  );
}

async function request(
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
  timeoutMs = REQUEST_TIMEOUT_MS,
  baseUrl = API_BASE_URL,
): Promise<Response> {
  const linked = requestSignal(signal, timeoutMs);
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      signal: linked.signal,
    });
    if (!response.ok) {
      throw await parseError(response);
    }
    return response;
  } catch (error) {
    if (error instanceof ApiClientError) {
      throw error;
    }
    if (signal?.aborted) {
      throw new DOMException("The request was aborted.", "AbortError");
    }
    if (linked.timedOut()) {
      throw new ApiClientError(
        localEnvelope(
          "REQUEST_TIMEOUT",
          "The model service did not respond before the request timed out.",
        ),
      );
    }
    throw new ApiClientError(
      localEnvelope(
        "NETWORK_UNAVAILABLE",
        "The model service could not be reached. Check the connection and try again.",
      ),
    );
  } finally {
    linked.cleanup();
  }
}

async function jsonResponse(
  response: Response,
  guard: (value: unknown) => boolean,
): Promise<unknown> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiClientError(
      localEnvelope(
        "INVALID_RESPONSE",
        "The model service returned a response that could not be read.",
      ),
    );
  }
  if (!guard(body)) {
    throw new ApiClientError(
      localEnvelope(
        "INVALID_RESPONSE",
        "The model service response did not match API-v1.",
      ),
    );
  }
  return body;
}

export async function fetchReadiness(
  signal?: AbortSignal,
): Promise<ReadinessResponse> {
  const response = await request(
    "/ready",
    { headers: { Accept: "application/json" } },
    signal,
  );
  return (await jsonResponse(
    response,
    isReadinessResponse,
  )) as ReadinessResponse;
}

export async function fetchModelMetadata(
  signal?: AbortSignal,
): Promise<ModelMetadata> {
  const response = await request(
    "/api/v1/model",
    { headers: { Accept: "application/json" } },
    signal,
  );
  return (await jsonResponse(response, isModelMetadata)) as ModelMetadata;
}

export async function uploadTrafficCsv(
  file: File,
  signal?: AbortSignal,
): Promise<BatchPredictionResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await request(
    "/api/v1/predictions/file",
    { method: "POST", body: form, headers: { Accept: "application/json" } },
    signal,
    UPLOAD_TIMEOUT_MS,
  );
  return (await jsonResponse(
    response,
    isBatchPredictionResponse,
  )) as BatchPredictionResponse;
}

function filenameFrom(response: Response, fallback: string): string {
  const disposition = response.headers.get("content-disposition") ?? "";
  return /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? fallback;
}

export async function fetchInputTemplate(
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  const response = await request(
    "/api/v1/input-template",
    { headers: { Accept: "text/csv" } },
    signal,
  );
  return {
    blob: await response.blob(),
    filename: filenameFrom(response, "ids-input-template.csv"),
  };
}

export async function fetchDemoSample(signal?: AbortSignal): Promise<File> {
  const response = await request(
    DEMO_SAMPLE_URL,
    { headers: { Accept: "text/csv" } },
    signal,
    REQUEST_TIMEOUT_MS,
    "",
  );
  return new File([await response.blob()], "ids-demo-mixed.csv", {
    type: "text/csv",
  });
}
