import axe from "axe-core";
import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";

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
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("reports no serious violations on the upload entry", async () => {
    const { container } = render(<App />);
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("reports no serious violations on the analyst dashboard", async () => {
    window.history.replaceState({}, "", "/?fixture=edge");
    const { container } = render(<App />);
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("reports no serious violations on the error state", async () => {
    window.history.replaceState({}, "", "/?fixture=invalid");
    const { container } = render(<App />);
    expect(await seriousViolations(container)).toEqual([]);
  });
});
