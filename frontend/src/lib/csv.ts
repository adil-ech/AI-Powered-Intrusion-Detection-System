import type { BatchPredictionResponse, Prediction } from "../types/api";

export const REQUIRED_FEATURES = [
  "flow_duration",
  "total_fwd_packets",
  "total_backward_packets",
  "total_length_of_fwd_packets",
  "total_length_of_bwd_packets",
  "fwd_packet_length_max",
  "fwd_packet_length_min",
  "fwd_packet_length_mean",
  "fwd_packet_length_std",
  "bwd_packet_length_max",
  "bwd_packet_length_min",
  "bwd_packet_length_mean",
  "bwd_packet_length_std",
  "flow_bytes_s",
  "flow_packets_s",
  "flow_iat_mean",
  "flow_iat_std",
  "flow_iat_max",
  "flow_iat_min",
  "fwd_iat_total",
  "fwd_iat_mean",
  "fwd_iat_std",
  "fwd_iat_max",
  "fwd_iat_min",
  "bwd_iat_total",
  "bwd_iat_mean",
  "bwd_iat_std",
  "bwd_iat_max",
  "bwd_iat_min",
  "fwd_psh_flags",
  "fwd_urg_flags",
  "fwd_header_length",
  "bwd_header_length",
  "fwd_packets_s",
  "bwd_packets_s",
  "min_packet_length",
  "max_packet_length",
  "packet_length_mean",
  "packet_length_std",
  "packet_length_variance",
  "fin_flag_count",
  "rst_flag_count",
  "psh_flag_count",
  "ack_flag_count",
  "urg_flag_count",
  "ece_flag_count",
  "down_up_ratio",
  "average_packet_size",
  "avg_bwd_segment_size",
  "subflow_fwd_bytes",
  "subflow_bwd_bytes",
  "init_win_bytes_forward",
  "init_win_bytes_backward",
  "act_data_pkt_fwd",
  "min_seg_size_forward",
  "active_mean",
  "active_std",
  "active_max",
  "active_min",
  "idle_mean",
  "idle_std",
  "idle_max",
  "idle_min",
] as const;

const EXPORT_HEADERS = [
  "row_id",
  "is_suspicious",
  "predicted_category",
  "malicious_probability",
  "category_confidence",
  "confidence",
  "confidence_status",
  "risk_level",
  "warnings",
  "request_id",
  "model_name",
  "model_version",
  "feature_schema_version",
  "analysis_status",
] as const;

export function neutralizeSpreadsheetFormula(value: string): string {
  return /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
}

function csvCell(value: string | number | boolean | null): string {
  const raw = neutralizeSpreadsheetFormula(value === null ? "" : String(value));
  return /[",\n\r]/.test(raw) ? `"${raw.replaceAll('"', '""')}"` : raw;
}

export function buildEnrichedCsv(
  response: BatchPredictionResponse,
  predictions: Prediction[] = response.predictions,
): string {
  const rows = predictions.map((row) => [
    row.row_id,
    row.is_suspicious,
    row.predicted_category,
    row.malicious_probability,
    row.category_confidence,
    row.confidence,
    row.confidence_status,
    row.risk_level,
    row.warnings.join(" | "),
    response.request_id,
    response.model.name,
    response.model.version,
    response.model.feature_schema_version,
    response.status,
  ]);

  return [EXPORT_HEADERS, ...rows]
    .map((row) => row.map(csvCell).join(","))
    .join("\n")
    .concat("\n");
}

export function downloadTextFile(
  contents: string,
  filename: string,
  mimeType: string,
): void {
  const blob = new Blob([contents], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function downloadTemplate(): void {
  const header = ["row_id", ...REQUIRED_FEATURES].join(",").concat("\n");
  downloadTextFile(header, "ids-input-template.csv", "text/csv;charset=utf-8");
}
