export const ATTACK_CATEGORIES = [
  "BENIGN",
  "DOS_DDOS",
  "PORT_SCAN",
  "BRUTE_FORCE",
  "WEB_ATTACK",
  "BOTNET",
  "INFILTRATION",
  "RARE_OTHER",
] as const;

export type AttackCategory = (typeof ATTACK_CATEGORIES)[number];
export type ConfidenceStatus = "OK" | "LOW_CONFIDENCE";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

export interface ReadinessResponse {
  status: "ready";
  model_version: string;
}

export interface ModelMetadata {
  model_name: string;
  model_version: string;
  artifact_status: "READY";
  training_dataset: string;
  feature_schema_version: string;
  feature_schema_hash: string;
  required_features: string[];
  attack_categories: AttackCategory[];
  thresholds: {
    malicious: number;
    low_confidence: number;
    high_risk: number;
  };
  created_at: string;
}

export interface ResponseModelIdentity {
  name: string;
  version: string;
  feature_schema_version: string;
}

export interface PredictionSummary {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  benign_rows: number;
  suspicious_rows: number;
  high_risk_rows: number;
  category_counts: Partial<Record<AttackCategory, number>>;
}

export interface Prediction {
  row_id: string;
  is_suspicious: boolean;
  predicted_category: AttackCategory;
  malicious_probability: number;
  category_confidence: number | null;
  confidence: number;
  confidence_status: ConfidenceStatus;
  risk_level: RiskLevel;
  warnings: string[];
}

export interface RowError {
  row_id: string;
  code: string;
  message: string;
  fields: string[];
}

export interface BatchPredictionResponse {
  request_id: string;
  status: "COMPLETE" | "PARTIAL_SUCCESS";
  model: ResponseModelIdentity;
  summary: PredictionSummary;
  predictions: Prediction[];
  row_errors: RowError[];
  warnings: string[];
}

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id: string;
  };
}
