import { describe, expect, it } from "vitest";

import { FIXTURE_RESPONSES } from "../fixtures/api-v1";
import {
  REQUIRED_FEATURES,
  buildEnrichedCsv,
  neutralizeSpreadsheetFormula,
} from "./csv";

describe("CSV output", () => {
  it("keeps the template aligned with the 63-field contract", () => {
    expect(REQUIRED_FEATURES).toHaveLength(63);
    expect(REQUIRED_FEATURES[0]).toBe("flow_duration");
    expect(REQUIRED_FEATURES.at(-1)).toBe("idle_min");
    expect(REQUIRED_FEATURES).not.toContain("destination_port");
  });

  it.each(["=SUM(1,2)", "+cmd", "-3+4", "@name", "\tformula", "\rformula"])(
    "neutralizes spreadsheet formula prefix %s",
    (value) => {
      expect(neutralizeSpreadsheetFormula(value)).toBe(`'${value}`);
    },
  );

  it("exports enriched metadata and neutralizes untrusted row IDs", () => {
    const csv = buildEnrichedCsv(FIXTURE_RESPONSES.edge);
    const lines = csv.trimEnd().split("\n");

    expect(lines).toHaveLength(FIXTURE_RESPONSES.edge.predictions.length + 1);
    expect(lines[0]).toBe(
      "row_id,is_suspicious,predicted_category,malicious_probability,category_confidence,confidence,confidence_status,risk_level,warnings,request_id,model_name,model_version,feature_schema_version,analysis_status",
    );
    expect(csv).toContain("'=WEBSERVICE(");
    expect(csv).toContain("'+edge-02");
    expect(csv).toContain("'@edge-03");
    expect(csv).toContain("'-edge-04");
    expect(csv).toContain("req_fixture_edge");
    expect(csv).toContain("ids-rf-v1.0.0");
  });

  it("exports the selected view rather than hidden rows", () => {
    const selected = FIXTURE_RESPONSES.mixed.predictions.filter(
      (row) => row.predicted_category === "DOS_DDOS",
    );
    const csv = buildEnrichedCsv(FIXTURE_RESPONSES.mixed, selected);

    expect(csv.trimEnd().split("\n")).toHaveLength(3);
    expect(csv).toContain("flow-002");
    expect(csv).toContain("flow-010");
    expect(csv).not.toContain("flow-003");
  });
});
