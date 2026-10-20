import axe from "axe-core";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorView, LoadingView } from "./App";
import { ResultsDashboard } from "./components/ResultsDashboard";
import { UploadExperience } from "./components/UploadExperience";
import {
  FIXTURE_ERRORS,
  FIXTURE_MODEL_METADATA,
  FIXTURE_RESPONSES,
} from "./fixtures/api-v1";

async function seriousViolations(container: HTMLElement) {
  const result = await axe.run(container, {
    runOnly: {
      type: "tag",
      values: ["wcag2a", "wcag2aa"],
    },
  });
  return result.violations.filter(
    (violation) =>
      violation.impact === "serious" || violation.impact === "critical",
  );
}

describe("automated accessibility", () => {
  it("reports no serious violations on the live upload entry", async () => {
    const { container } = render(
      <UploadExperience
        connection={{ status: "ready", model: FIXTURE_MODEL_METADATA }}
        onDownloadTemplate={vi.fn()}
        onFile={vi.fn()}
        onRetryConnection={vi.fn()}
        onReviewSample={vi.fn()}
      />,
    );
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("reports no serious violations on the analyst dashboard", async () => {
    const { container } = render(
      <ResultsDashboard
        model={FIXTURE_MODEL_METADATA}
        onReset={vi.fn()}
        response={FIXTURE_RESPONSES.edge}
        sourceName="edge.csv"
      />,
    );
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("reports no serious violations on loading and error states", async () => {
    const loading = render(<LoadingView onCancel={vi.fn()} />);
    expect(await seriousViolations(loading.container)).toEqual([]);
    loading.unmount();

    const error = render(
      <ErrorView
        envelope={FIXTURE_ERRORS.invalid}
        onReset={vi.fn()}
        onReviewSample={vi.fn()}
      />,
    );
    expect(await seriousViolations(error.container)).toEqual([]);
  });
});
