import { describe, expect, it } from "vitest";

import { FIXTURE_RESPONSES } from "./api-v1";
import { calculateSummary } from "../lib/analytics";

describe("API-v1 fixtures", () => {
  it.each(Object.entries(FIXTURE_RESPONSES))(
    "%s summary is derived from its prediction and error rows",
    (_name, fixture) => {
      expect(
        calculateSummary(fixture.predictions, fixture.row_errors.length),
      ).toEqual(fixture.summary);
      expect(fixture.summary.valid_rows).toBe(fixture.predictions.length);
      expect(fixture.summary.invalid_rows).toBe(fixture.row_errors.length);
      expect(fixture.summary.total_rows).toBe(
        fixture.summary.valid_rows + fixture.summary.invalid_rows,
      );
    },
  );

  it("covers success, low confidence, partial validation, and empty output", () => {
    expect(FIXTURE_RESPONSES.normal.summary.suspicious_rows).toBe(0);
    expect(
      FIXTURE_RESPONSES.mixed.predictions.some(
        (row) => row.confidence_status === "LOW_CONFIDENCE",
      ),
    ).toBe(true);
    expect(FIXTURE_RESPONSES.edge.status).toBe("PARTIAL_SUCCESS");
    expect(FIXTURE_RESPONSES.edge.row_errors).toHaveLength(3);
    expect(FIXTURE_RESPONSES.empty.predictions).toHaveLength(0);
  });
});
