import { ATTACK_CATEGORIES } from "../types/api";
import type {
  AttackCategory,
  BatchPredictionResponse,
  Prediction,
  PredictionSummary,
  RiskLevel,
} from "../types/api";

export type ConfidenceBucket = "Below 65%" | "65–84%" | "85–100%";

export interface DistributionDatum<T extends string> {
  label: T;
  count: number;
  percentage: number;
}

export function calculateSummary(
  predictions: Prediction[],
  invalidRows: number,
): PredictionSummary {
  const categoryCounts: Partial<Record<AttackCategory, number>> = {};
  for (const row of predictions) {
    categoryCounts[row.predicted_category] =
      (categoryCounts[row.predicted_category] ?? 0) + 1;
  }

  const suspicious = predictions.filter((row) => row.is_suspicious);
  return {
    total_rows: predictions.length + invalidRows,
    valid_rows: predictions.length,
    invalid_rows: invalidRows,
    benign_rows: predictions.length - suspicious.length,
    suspicious_rows: suspicious.length,
    high_risk_rows: suspicious.filter((row) => row.risk_level === "HIGH")
      .length,
    category_counts: categoryCounts,
  };
}

export function attackDistribution(
  response: BatchPredictionResponse,
): DistributionDatum<AttackCategory>[] {
  const total = Math.max(response.summary.valid_rows, 1);
  return ATTACK_CATEGORIES.map((label) => ({
    label,
    count: response.summary.category_counts[label] ?? 0,
    percentage: ((response.summary.category_counts[label] ?? 0) / total) * 100,
  })).filter((datum) => datum.count > 0);
}

export function confidenceDistribution(
  predictions: Prediction[],
): DistributionDatum<ConfidenceBucket>[] {
  const buckets: Record<ConfidenceBucket, number> = {
    "Below 65%": 0,
    "65–84%": 0,
    "85–100%": 0,
  };

  for (const row of predictions) {
    if (row.confidence < 0.65) {
      buckets["Below 65%"] += 1;
    } else if (row.confidence < 0.85) {
      buckets["65–84%"] += 1;
    } else {
      buckets["85–100%"] += 1;
    }
  }

  const total = Math.max(predictions.length, 1);
  return (Object.entries(buckets) as [ConfidenceBucket, number][]).map(
    ([label, count]) => ({
      label,
      count,
      percentage: (count / total) * 100,
    }),
  );
}

export const RISK_ORDER: Record<RiskLevel, number> = {
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
};

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatCategory(category: AttackCategory): string {
  const labels: Record<AttackCategory, string> = {
    BENIGN: "Benign",
    DOS_DDOS: "DoS / DDoS",
    PORT_SCAN: "Port scan",
    BRUTE_FORCE: "Brute force",
    WEB_ATTACK: "Web attack",
    BOTNET: "Botnet",
    INFILTRATION: "Infiltration",
    RARE_OTHER: "Rare other",
  };
  return labels[category];
}
