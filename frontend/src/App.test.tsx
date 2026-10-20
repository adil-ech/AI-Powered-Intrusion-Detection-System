import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "./api/client";
import App from "./App";
import { ResultsDashboard } from "./components/ResultsDashboard";
import {
  FIXTURE_ERRORS,
  FIXTURE_MODEL_METADATA,
  FIXTURE_RESPONSES,
} from "./fixtures/api-v1";

const clientMocks = vi.hoisted(() => ({
  fetchReadiness: vi.fn(),
  fetchModelMetadata: vi.fn(),
  uploadTrafficCsv: vi.fn(),
  fetchDemoSample: vi.fn(),
  fetchInputTemplate: vi.fn(),
}));

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
  return { ...actual, ...clientMocks };
});

function readyClient() {
  clientMocks.fetchReadiness.mockResolvedValue({
    status: "ready",
    model_version: FIXTURE_MODEL_METADATA.model_version,
  });
  clientMocks.fetchModelMetadata.mockResolvedValue(FIXTURE_MODEL_METADATA);
  clientMocks.uploadTrafficCsv.mockResolvedValue(FIXTURE_RESPONSES.mixed);
  clientMocks.fetchDemoSample.mockResolvedValue(
    new File(["safe sample"], "ids-demo-mixed.csv", { type: "text/csv" }),
  );
  clientMocks.fetchInputTemplate.mockResolvedValue({
    blob: new Blob(["row_id,flow_duration\n"], { type: "text/csv" }),
    filename: "ids-input-template.csv",
  });
}

async function waitForReady() {
  expect(
    await screen.findByText(/Model ready: ids-rf-v1\.0\.0/),
  ).toBeInTheDocument();
}

describe("App live API states", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    readyClient();
  });

  it("shows model readiness on the complete upload entry", async () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Find the flows worth reviewing" }),
    ).toBeInTheDocument();
    await waitForReady();
    expect(screen.getByLabelText("Traffic CSV")).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Download model template" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("heading", { name: "What the score cannot say" }),
    ).toBeInTheDocument();
  });

  it("downloads the template from the active API", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();

    await user.click(
      screen.getByRole("button", { name: "Download model template" }),
    );

    expect(clientMocks.fetchInputTemplate).toHaveBeenCalledOnce();
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
  });

  it("moves through loading into live results from the safe sample", async () => {
    const user = userEvent.setup();
    let finishUpload: (() => void) | undefined;
    clientMocks.uploadTrafficCsv.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishUpload = () => resolve(FIXTURE_RESPONSES.mixed);
        }),
    );
    render(<App />);
    await waitForReady();

    await user.click(screen.getByRole("button", { name: "Review sample" }));
    expect(
      screen.getByRole("heading", { name: "Preparing the review" }),
    ).toBeInTheDocument();

    act(() => finishUpload?.());
    expect(
      await screen.findByRole("heading", { name: "Traffic review" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Live model")).toBeInTheDocument();
    expect(
      screen.getByText(/Uploaded as ids-demo-mixed\.csv/i),
    ).toBeInTheDocument();
    expect(clientMocks.uploadTrafficCsv).toHaveBeenCalledOnce();
  });

  it("keeps the original upload filename beside the real response", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();

    const file = new File(["row_id,flow_duration\nflow-a,4\n"], "flows.csv", {
      type: "text/csv",
    });
    await user.upload(screen.getByLabelText("Traffic CSV"), file);

    expect(
      await screen.findByText(/Uploaded as flows\.csv/i),
    ).toBeInTheDocument();
    expect(clientMocks.uploadTrafficCsv).toHaveBeenCalledWith(
      file,
      expect.any(AbortSignal),
    );
  });

  it("opens the native upload control from the keyboard", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitForReady();

    const input = screen.getByLabelText("Traffic CSV");
    const openPicker = vi.spyOn(input, "click");
    const button = screen.getAllByRole("button", { name: "Choose CSV" })[0];
    button.focus();
    await user.keyboard("{Enter}");

    expect(openPicker).toHaveBeenCalledOnce();
  });

  it("rejects a non-CSV file before any network upload", async () => {
    const user = userEvent.setup({ applyAccept: false });
    render(<App />);
    await waitForReady();

    await user.upload(
      screen.getByLabelText("Traffic CSV"),
      new File(["not csv"], "capture.txt", { type: "text/plain" }),
    );

    expect(screen.getByText("UNSUPPORTED_FILE_TYPE")).toBeInTheDocument();
    expect(clientMocks.uploadTrafficCsv).not.toHaveBeenCalled();
  });

  it("renders partial validation and rejected-row evidence from the API", async () => {
    const user = userEvent.setup();
    clientMocks.uploadTrafficCsv.mockResolvedValueOnce(FIXTURE_RESPONSES.edge);
    render(<App />);
    await waitForReady();

    await user.click(screen.getByRole("button", { name: "Review sample" }));

    expect(
      await screen.findByRole("heading", { name: "Partial validation" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Rejected rows" }),
    ).toBeInTheDocument();
    expect(screen.getByText("edge-09")).toBeInTheDocument();
  });

  it("renders an honest empty response", async () => {
    const user = userEvent.setup();
    clientMocks.uploadTrafficCsv.mockResolvedValueOnce(FIXTURE_RESPONSES.empty);
    render(<App />);
    await waitForReady();

    await user.click(screen.getByRole("button", { name: "Review sample" }));

    expect(
      await screen.findByRole("heading", { name: "No rows match this view" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export view" })).toBeDisabled();
  });

  it("renders structured API validation without echoing row values", async () => {
    const user = userEvent.setup();
    clientMocks.uploadTrafficCsv.mockRejectedValueOnce(
      new ApiClientError(FIXTURE_ERRORS.invalid, 422),
    );
    render(<App />);
    await waitForReady();

    await user.click(screen.getByRole("button", { name: "Review sample" }));

    expect(
      await screen.findByText("MISSING_REQUIRED_COLUMNS"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("flow_duration, total_fwd_packets"),
    ).toBeInTheDocument();
    expect(screen.getByText(/req_fixture_invalid/)).toBeInTheDocument();
  });

  it("reports unavailable readiness and retries the connection", async () => {
    const user = userEvent.setup();
    clientMocks.fetchReadiness.mockRejectedValueOnce(
      new ApiClientError(FIXTURE_ERRORS.failure, 503),
    );
    render(<App />);

    expect(
      await screen.findByText("The model is not ready to score this request."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Traffic CSV")).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Retry connection" }));
    await waitForReady();
    expect(clientMocks.fetchReadiness).toHaveBeenCalledTimes(2);
  });

  it("cancels an in-flight upload from the keyboard", async () => {
    const user = userEvent.setup();
    clientMocks.uploadTrafficCsv.mockImplementation(
      (_file: File, signal: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    render(<App />);
    await waitForReady();
    await user.click(screen.getByRole("button", { name: "Review sample" }));

    const cancel = screen.getByRole("button", { name: "Cancel" });
    cancel.focus();
    await user.keyboard("{Enter}");

    expect(
      screen.getByRole("heading", { name: "Find the flows worth reviewing" }),
    ).toBeInTheDocument();
  });

  it("prevents duplicate submissions while an upload is in flight", async () => {
    let finishUpload: (() => void) | undefined;
    clientMocks.uploadTrafficCsv.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishUpload = () => resolve(FIXTURE_RESPONSES.mixed);
        }),
    );
    render(<App />);
    await waitForReady();

    const reviewSample = screen.getByRole("button", { name: "Review sample" });
    fireEvent.click(reviewSample);
    fireEvent.click(reviewSample);

    expect(clientMocks.fetchDemoSample).toHaveBeenCalledOnce();
    await waitFor(() =>
      expect(clientMocks.uploadTrafficCsv).toHaveBeenCalledOnce(),
    );

    act(() => finishUpload?.());
    expect(
      await screen.findByRole("heading", { name: "Traffic review" }),
    ).toBeInTheDocument();
  });
});

function renderResults(initialRowId?: string) {
  return render(
    <ResultsDashboard
      initialRowId={initialRowId}
      model={FIXTURE_MODEL_METADATA}
      onReset={vi.fn()}
      response={FIXTURE_RESPONSES.mixed}
      sourceName="ids-demo-mixed.csv"
    />,
  );
}

describe("results interactions", () => {
  it("matches the response summary", () => {
    renderResults();

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

  it("filters suspicious rows and clears the view", async () => {
    const user = userEvent.setup();
    renderResults();

    await user.selectOptions(screen.getByLabelText("Verdict"), "SUSPICIOUS");
    expect(screen.getByText("Showing 1–5 of 10")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Category"), "DOS_DDOS");
    expect(screen.getByText("Showing 1–2 of 2")).toBeInTheDocument();
    expect(screen.getAllByText("DoS / DDoS").length).toBeGreaterThanOrEqual(2);

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("Showing 1–5 of 14")).toBeInTheDocument();
  });

  it("sorts, paginates, and keeps controls keyboard accessible", async () => {
    const user = userEvent.setup();
    renderResults();

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
    renderResults("flow-002");

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
    renderResults();

    await user.type(screen.getByLabelText("Find row"), "does-not-exist");
    expect(
      screen.getByRole("heading", { name: "No rows match this view" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Showing 0–0 of 0")).toBeInTheDocument();
  });
});
