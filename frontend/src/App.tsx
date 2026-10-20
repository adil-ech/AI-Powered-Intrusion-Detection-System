import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiClientError,
  fetchDemoSample,
  fetchInputTemplate,
  fetchModelMetadata,
  fetchReadiness,
  uploadTrafficCsv,
} from "./api/client";
import { ResultsDashboard } from "./components/ResultsDashboard";
import {
  UploadExperience,
  type ModelConnection,
} from "./components/UploadExperience";
import { downloadBlobFile } from "./lib/csv";
import type {
  ApiErrorEnvelope,
  BatchPredictionResponse,
  ModelMetadata,
} from "./types/api";

type AppState =
  | { kind: "idle" }
  | { kind: "loading"; sourceName: string }
  | {
      kind: "result";
      response: BatchPredictionResponse;
      sourceName: string;
      model: ModelMetadata;
    }
  | { kind: "error"; error: ApiErrorEnvelope };

export function LoadingView({ onCancel }: { onCancel: () => void }) {
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
          Sending the CSV to API-v1 and waiting for the active model response.
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

export function ErrorView({
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
  const visibleColumns = missingColumns.slice(0, 8);
  const remainingColumns = missingColumns.length - visibleColumns.length;
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
        {visibleColumns.length > 0 ? (
          <div className="missing-columns" role="note">
            <strong>Missing fields</strong>
            <p>
              {visibleColumns.join(", ")}
              {remainingColumns > 0
                ? `, and ${remainingColumns} more required fields`
                : ""}
            </p>
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

function localError(
  code: string,
  message: string,
  requestId = "client_validation",
): ApiErrorEnvelope {
  return {
    error: {
      code,
      message,
      request_id: requestId,
    },
  };
}

function errorEnvelope(error: unknown): ApiErrorEnvelope {
  if (error instanceof ApiClientError) {
    return error.envelope;
  }
  return localError(
    "CLIENT_REQUEST_FAILED",
    "The request could not be completed. Try again.",
    "client_transport",
  );
}

function modelMatches(
  response: BatchPredictionResponse,
  model: ModelMetadata,
): boolean {
  return (
    response.model.name === model.model_name &&
    response.model.version === model.model_version &&
    response.model.feature_schema_version === model.feature_schema_version
  );
}

export default function App() {
  const [state, setState] = useState<AppState>({ kind: "idle" });
  const [connection, setConnection] = useState<ModelConnection>({
    status: "checking",
  });
  const uploadControllerRef = useRef<AbortController | null>(null);
  const modelControllerRef = useRef<AbortController | null>(null);
  const templateControllerRef = useRef<AbortController | null>(null);
  const modelRef = useRef<ModelMetadata | null>(null);
  const submittingRef = useRef(false);

  const refreshModel = useCallback(async () => {
    modelControllerRef.current?.abort();
    const controller = new AbortController();
    modelControllerRef.current = controller;
    setConnection({ status: "checking" });
    try {
      const readiness = await fetchReadiness(controller.signal);
      const model = await fetchModelMetadata(controller.signal);
      if (readiness.model_version !== model.model_version) {
        throw new ApiClientError(
          localError(
            "MODEL_METADATA_MISMATCH",
            "Readiness and model metadata report different versions.",
            "client_readiness",
          ),
        );
      }
      modelRef.current = model;
      setConnection({ status: "ready", model });
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      modelRef.current = null;
      setConnection({
        status: "unavailable",
        message: errorEnvelope(error).error.message,
      });
    }
  }, []);

  useEffect(() => {
    const initialCheck = window.setTimeout(() => void refreshModel(), 0);
    return () => {
      window.clearTimeout(initialCheck);
      uploadControllerRef.current?.abort();
      modelControllerRef.current?.abort();
      templateControllerRef.current?.abort();
    };
  }, [refreshModel]);

  const reset = () => {
    uploadControllerRef.current?.abort();
    submittingRef.current = false;
    setState({ kind: "idle" });
    void refreshModel();
    window.scrollTo({ top: 0, behavior: "auto" });
  };

  const runAnalysis = async (
    sourceName: string,
    getFile: (signal: AbortSignal) => Promise<File>,
  ) => {
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    uploadControllerRef.current?.abort();
    const controller = new AbortController();
    uploadControllerRef.current = controller;
    setState({ kind: "loading", sourceName });

    try {
      const file = await getFile(controller.signal);
      const response = await uploadTrafficCsv(file, controller.signal);
      const model = modelRef.current;
      if (model === null || !modelMatches(response, model)) {
        throw new ApiClientError(
          localError(
            "MODEL_METADATA_MISMATCH",
            "The prediction response does not match the active model metadata.",
            response.request_id,
          ),
        );
      }
      setState({ kind: "result", response, sourceName, model });
      window.scrollTo({ top: 0, behavior: "auto" });
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      setState({ kind: "error", error: errorEnvelope(error) });
    } finally {
      if (uploadControllerRef.current === controller) {
        uploadControllerRef.current = null;
        submittingRef.current = false;
      }
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
    void runAnalysis(file.name, async () => file);
  };

  const reviewSample = () => {
    void runAnalysis("ids-demo-mixed.csv", fetchDemoSample);
  };

  const downloadTemplate = async () => {
    templateControllerRef.current?.abort();
    const controller = new AbortController();
    templateControllerRef.current = controller;
    try {
      const download = await fetchInputTemplate(controller.signal);
      downloadBlobFile(download.blob, download.filename);
    } catch (error) {
      if (!controller.signal.aborted) {
        setState({ kind: "error", error: errorEnvelope(error) });
      }
    } finally {
      if (templateControllerRef.current === controller) {
        templateControllerRef.current = null;
      }
    }
  };

  if (state.kind === "loading") {
    return (
      <LoadingView
        onCancel={() => {
          uploadControllerRef.current?.abort();
          submittingRef.current = false;
          setState({ kind: "idle" });
        }}
      />
    );
  }
  if (state.kind === "error") {
    return (
      <ErrorView
        envelope={state.error}
        onReset={reset}
        onReviewSample={reviewSample}
      />
    );
  }
  if (state.kind === "result") {
    return (
      <ResultsDashboard
        model={state.model}
        onReset={reset}
        response={state.response}
        sourceName={state.sourceName}
      />
    );
  }

  return (
    <UploadExperience
      connection={connection}
      onDownloadTemplate={downloadTemplate}
      onFile={handleFile}
      onRetryConnection={() => void refreshModel()}
      onReviewSample={reviewSample}
    />
  );
}
