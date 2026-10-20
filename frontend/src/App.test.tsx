import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function openFixture(fixture: string, row?: string) {
  const query = new URLSearchParams({ fixture });
  if (row) {
    query.set("row", row);
  }
  window.history.replaceState({}, "", `/?${query.toString()}`);
}

describe("App states", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("renders the complete upload entry without the live API", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Find the flows worth reviewing" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Traffic CSV")).toHaveAttribute(
      "accept",
      expect.stringContaining(".csv"),
    );
    expect(
      screen.getByRole("button", { name: "Download 63-field template" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/versioned local responses/i)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "What the score cannot say" }),
    ).toBeInTheDocument();
  });

  it("moves through loading into mixed results from the sample action", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Review sample" }));
    expect(
      screen.getByRole("heading", { name: "Preparing the review" }),
    ).toBeInTheDocument();

    expect(
      await screen.findByRole("heading", { name: "Traffic review" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/versioned mixed fixture/i)).toBeInTheDocument();
  });

  it("keeps the original filename separate from fixture output", async () => {
    const user = userEvent.setup();
    render(<App />);

    const file = new File(["row_id,flow_duration\nflow-a,4\n"], "flows.csv", {
      type: "text/csv",
    });
    await user.upload(screen.getByLabelText("Traffic CSV"), file);

    expect(
      await screen.findByText(/Uploaded as flows.csv/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/versioned mixed fixture/i)).toBeInTheDocument();
  });

  it("opens the native upload control from the keyboard", async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = screen.getByLabelText("Traffic CSV");
    const openPicker = vi.spyOn(input, "click");
    const button = screen.getAllByRole("button", { name: "Choose CSV" })[0];

    button.focus();
    await user.keyboard("{Enter}");

    expect(openPicker).toHaveBeenCalledOnce();
  });

  it("rejects a non-CSV file before fixture analysis", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<App />);

    await user.upload(
      screen.getByLabelText("Traffic CSV"),
      new File(["not csv"], "capture.txt", { type: "text/plain" }),
    );

    expect(
      screen.getByRole("heading", {
        name: "This batch could not be reviewed",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("UNSUPPORTED_FILE_TYPE")).toBeInTheDocument();
  });

  it("renders partial validation and rejected-row evidence", () => {
    openFixture("edge");
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Partial validation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Rejected rows" }),
    ).toBeInTheDocument();
    expect(screen.getByText("edge-09")).toBeInTheDocument();
    expect(screen.getAllByText("Needs review").length).toBeGreaterThan(0);
  });

  it("renders an honest empty result", () => {
    openFixture("empty");
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "No rows match this view" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No categories were returned for this batch."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export view" })).toBeDisabled();
  });

  it("renders invalid-input details without echoing row values", () => {
    openFixture("invalid");
    render(<App />);

    expect(screen.getByText("MISSING_REQUIRED_COLUMNS")).toBeInTheDocument();
    expect(
      screen.getByText("flow_duration, total_fwd_packets"),
    ).toBeInTheDocument();
    expect(screen.getByText(/req_fixture_invalid/)).toBeInTheDocument();
  });

  it("renders a safe service-failure state", () => {
    openFixture("failure");
    render(<App />);

    expect(screen.getByText("MODEL_UNAVAILABLE")).toBeInTheDocument();
    expect(
      screen.getByText("The model is not ready to score this request."),
    ).toBeInTheDocument();
    expect(screen.getByText(/req_fixture_failure/)).toBeInTheDocument();
  });

  it("can cancel the loading state with a keyboard-activated control", async () => {
    const user = userEvent.setup();
    openFixture("loading");
    render(<App />);

    const cancel = screen.getByRole("button", { name: "Cancel" });
    cancel.focus();
    await user.keyboard("{Enter}");
    expect(
      screen.getByRole("heading", { name: "Find the flows worth reviewing" }),
    ).toBeInTheDocument();
  });
});

describe("results interactions", () => {
  beforeEach(() => openFixture("mixed"));

  it("matches the mixed fixture summary", () => {
    render(<App />);

    const summary = screen.getByLabelText("Analysis summary");
    expect(
      within(summary).getByText("Rows received").nextElementSibling,
    ).toHaveTextContent("14");
    expect(
      within(summary).getByText("Suspicious").nextElementSibling,
    ).toHaveTextContent("10");
    expect(
      within(summary).getByText("High priority").nextElementSibling,
    ).toHaveTextContent("3");
    expect(
      within(summary).getByText("Needs review").nextElementSibling,
    ).toHaveTextContent("3");
  });

  it("filters rows and clears the view", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.selectOptions(screen.getByLabelText("Category"), "DOS_DDOS");
    expect(screen.getByText("Showing 1–2 of 2")).toBeInTheDocument();
    expect(screen.getAllByText("DoS / DDoS").length).toBeGreaterThanOrEqual(2);

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("Showing 1–5 of 14")).toBeInTheDocument();
  });

  it("sorts, paginates, and keeps controls keyboard accessible", async () => {
    const user = userEvent.setup();
    render(<App />);

    const sort = screen.getByRole("button", { name: /Sort by Confidence/ });
    sort.focus();
    await user.keyboard("{Enter}");
    expect(sort).toHaveAccessibleName(/currently descending/i);

    const next = screen.getByRole("button", { name: "Next" });
    await user.click(next);
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    expect(screen.getByText("Showing 6–10 of 14")).toBeInTheDocument();
  });

  it("opens row evidence, traps focus, closes on Escape, and restores focus", async () => {
    const user = userEvent.setup();
    openFixture("mixed", "flow-002");
    render(<App />);

    const dialog = screen.getByRole("dialog", { name: "flow-002" });
    expect(dialog).toHaveFocus();
    expect(within(dialog).getByText("96.75%")).toBeInTheDocument();

    await user.keyboard("{Tab}");
    const close = within(dialog).getByRole("button", { name: "Close" });
    expect(close).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    const firstDetails = screen.getAllByRole("button", { name: "Details" })[0];
    await user.click(firstDetails);
    await user.keyboard("{Escape}");
    expect(firstDetails).toHaveFocus();
  });

  it("searches by row ID and exposes an empty filter state", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.type(screen.getByLabelText("Find row"), "does-not-exist");
    expect(
      screen.getByRole("heading", { name: "No rows match this view" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Showing 0–0 of 0")).toBeInTheDocument();
  });
});
