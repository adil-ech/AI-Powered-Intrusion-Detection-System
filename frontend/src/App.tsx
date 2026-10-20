import { useEffect, useRef, useState } from "react";

import { ResultsDashboard } from "./components/ResultsDashboard";
import { UploadExperience } from "./components/UploadExperience";
import {
  FIXTURE_ERRORS,
  FIXTURE_RESPONSES,
  loadFixture,
} from "./fixtures/api-v1";
import type {
  ApiErrorEnvelope,
  BatchPredictionResponse,
  FixtureScenario,
} from "./types/api";

type AppState =
  | { kind: "idle" }
  | { kind: "loading"; scenario: FixtureScenario; sourceName?: string }
  | {
      kind: "result";
      scenario: FixtureScenario;
      response: BatchPredictionResponse;
      sourceName?: string;
      initialRowId?: string;
    }
  | { kind: "error"; scenario?: FixtureScenario; error: ApiErrorEnvelope };

const RESPONSE_SCENARIOS = ["normal", "mixed", "edge", "empty"] as const;
const ERROR_SCENARIOS = ["invalid", "failure"] as const;

function initialState(): AppState {
  const params = new URLSearchParams(window.location.search);
  const fixture = params.get("fixture");
  const initialRowId = params.get("row") ?? undefined;

  if (fixture === "loading") {
    return { kind: "loading", scenario: "mixed" };
  }
  if (RESPONSE_SCENARIOS.some((scenario) => scenario === fixture)) {
    const scenario = fixture as (typeof RESPONSE_SCENARIOS)[number];
    return {
      kind: "result",
      scenario,
      response: structuredClone(FIXTURE_RESPONSES[scenario]),
      initialRowId,
    };
  }
  if (ERROR_SCENARIOS.some((scenario) => scenario === fixture)) {
    const scenario = fixture as (typeof ERROR_SCENARIOS)[number];
    return {
      kind: "error",
      scenario,
      error: structuredClone(FIXTURE_ERRORS[scenario]),
    };
  }
  return { kind: "idle" };
}

function LoadingView({ onCancel }: { onCancel: () => void }) {
  return (
    <main className="state-page loading-page" aria-labelledby="loading-title">
      <div className="state-column">
        <span className="wordmark">Flow review</span>
        <div className="loading-sequence" aria-hidden="true">
          <span className="is-complete">Schema</span>
          <span className="is-active">Binary gate</span>
          <span>Attack family</span>
        </div>
        <h1 id="loading-title">Preparing the review</h1>
        <p role="status">
          Checking the input contract and loading a versioned fixture response.
        </p>
        <button
          className="button button-neutral"
          onClick={onCancel}
          type="button"
        >
          Cancel
        </button>
      </div>
    </main>
  );
}

function ErrorView({
  envelope,
  onReset,
  onReviewSample,
}: {
  envelope: ApiErrorEnvelope;
  onReset: () => void;
  onReviewSample: () => void;
}) {
  const missingColumns = Array.isArray(envelope.error.details?.columns)
    ? (envelope.error.details.columns as string[])
    : [];
  return (
    <main className="state-page error-page" aria-labelledby="error-title">
      <div className="state-column">
        <button
          className="wordmark wordmark-button"
          onClick={onReset}
          type="button"
        >
          Flow review
        </button>
        <h1 id="error-title">This batch could not be reviewed</h1>
        <p>{envelope.error.message}</p>
        <span className="error-code">{envelope.error.code}</span>
        {missingColumns.length > 0 ? (
          <div className="missing-columns" role="note">
            <strong>Missing fields</strong>
            <p>{missingColumns.join(", ")}</p>
          </div>
        ) : null}
        <p className="request-reference">
          Request reference: {envelope.error.request_id}
        </p>
        <div className="state-actions">
          <button
            className="button button-primary"
            onClick={onReset}
            type="button"
          >
            Choose another CSV
          </button>
          <button
            className="text-button"
            onClick={onReviewSample}
            type="button"
          >
            Review sample
          </button>
        </div>
      </div>
    </main>
  );
}

function localError(code: string, message: string): ApiErrorEnvelope {
  return {
    error: {
      code,
      message,
      request_id: "local_file_check",
    },
  };
}

export default function App() {
  const [state, setState] = useState<AppState>(initialState);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [],
  );

  const reset = () => {
    controllerRef.current?.abort();
    setState({ kind: "idle" });
    window.scrollTo({ top: 0, behavior: "auto" });
  };

  const analyze = async (scenario: FixtureScenario, sourceName?: string) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ kind: "loading", scenario, sourceName });

    try {
      const response = await loadFixture(scenario, controller.signal);
      setState({ kind: "result", scenario, response, sourceName });
      window.scrollTo({ top: 0, behavior: "auto" });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }
      setState({
        kind: "error",
        scenario,
        error:
          typeof error === "object" && error !== null && "error" in error
            ? (error as ApiErrorEnvelope)
            : localError(
                "FIXTURE_LOAD_FAILED",
                "The preview response could not be loaded.",
              ),
      });
    }
  };

  const handleFile = (file: File) => {
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setState({
        kind: "error",
        error: localError(
          "UNSUPPORTED_FILE_TYPE",
          "Choose a CSV file with a .csv extension.",
        ),
      });
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setState({
        kind: "error",
        error: localError("FILE_TOO_LARGE", "CSV files may not exceed 10 MiB."),
      });
      return;
    }
    void analyze("mixed", file.name);
  };

  if (state.kind === "loading") {
    return <LoadingView onCancel={reset} />;
  }
  if (state.kind === "error") {
    return (
      <ErrorView
        envelope={state.error}
        onReset={reset}
        onReviewSample={() => void analyze("mixed")}
      />
    );
  }
  if (state.kind === "result") {
    return (
      <ResultsDashboard
        initialRowId={state.initialRowId}
        onReset={reset}
        response={state.response}
        scenario={state.scenario}
        sourceName={state.sourceName}
      />
    );
  }

  return (
    <UploadExperience
      onFile={handleFile}
      onScenario={(scenario) => void analyze(scenario)}
    />
  );
}
