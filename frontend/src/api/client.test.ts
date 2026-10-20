import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiClientError,
  DEMO_SAMPLE_URL,
  fetchDemoSample,
  fetchInputTemplate,
  fetchModelMetadata,
  fetchReadiness,
  uploadTrafficCsv,
} from "./client";
import {
  FIXTURE_ERRORS,
  FIXTURE_MODEL_METADATA,
  FIXTURE_RESPONSES,
} from "../fixtures/api-v1";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("API client", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("validates readiness and model metadata", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({
          status: "ready",
          model_version: FIXTURE_MODEL_METADATA.model_version,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(FIXTURE_MODEL_METADATA));

    await expect(fetchReadiness()).resolves.toEqual({
      status: "ready",
      model_version: "ids-rf-v1.0.0",
    });
    await expect(fetchModelMetadata()).resolves.toEqual(FIXTURE_MODEL_METADATA);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/ready",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("uploads a multipart CSV and validates the prediction envelope", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse(FIXTURE_RESPONSES.mixed));
    const file = new File(["row_id\ndemo-01\n"], "traffic.csv", {
      type: "text/csv",
    });

    await expect(uploadTrafficCsv(file)).resolves.toEqual(
      FIXTURE_RESPONSES.mixed,
    );

    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("file")).toBe(file);
    expect(new Headers(init?.headers).has("content-type")).toBe(false);
  });

  it("preserves structured API errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(FIXTURE_ERRORS.invalid, 422),
    );

    await expect(
      uploadTrafficCsv(new File(["bad"], "bad.csv", { type: "text/csv" })),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      status: 422,
      envelope: FIXTURE_ERRORS.invalid,
    });
  });

  it("maps unreadable success payloads to a safe client error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("not-json", { status: 200 }),
    );

    await expect(fetchModelMetadata()).rejects.toMatchObject({
      envelope: { error: { code: "INVALID_RESPONSE" } },
    });
  });

  it("maps a network failure without leaking the underlying exception", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(
      new TypeError("private network detail"),
    );

    await expect(fetchReadiness()).rejects.toMatchObject({
      envelope: { error: { code: "NETWORK_UNAVAILABLE" } },
    });
  });

  it("downloads the server template with its response filename", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("row_id,flow_duration\nsynthetic-example,0\n", {
        status: 200,
        headers: {
          "content-type": "text/csv",
          "content-disposition": 'attachment; filename="active-template.csv"',
        },
      }),
    );

    const download = await fetchInputTemplate();

    expect(download.filename).toBe("active-template.csv");
    expect(await download.blob.text()).toContain("synthetic-example");
  });

  it("loads the demo CSV from the frontend origin", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("row_id,flow_duration\ndemo-01,1\n", {
        status: 200,
        headers: { "content-type": "text/csv" },
      }),
    );

    const file = await fetchDemoSample();

    expect(fetchMock.mock.calls[0][0]).toBe(DEMO_SAMPLE_URL);
    expect(file.name).toBe("ids-demo-mixed.csv");
    expect(file.type).toBe("text/csv");
  });

  it("keeps caller cancellation distinct from service failures", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const controller = new AbortController();
    const request = fetchReadiness(controller.signal);
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });

  it("turns an internal deadline into a safe timeout error", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
        }),
    );

    const request = fetchReadiness();
    const timeoutExpectation = expect(request).rejects.toMatchObject({
      envelope: { error: { code: "REQUEST_TIMEOUT" } },
    });
    await vi.advanceTimersByTimeAsync(30_000);

    await timeoutExpectation;
  });

  it("uses the exported error class for typed handling", () => {
    const error = new ApiClientError(FIXTURE_ERRORS.failure, 503);
    expect(error.message).toBe(FIXTURE_ERRORS.failure.error.message);
    expect(error.status).toBe(503);
  });
});
