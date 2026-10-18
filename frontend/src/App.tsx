import { useCallback, useEffect, useState } from "react";

import { fetchHealth } from "./api/health";

type ServiceState = "checking" | "online" | "unavailable";

const STATUS_COPY: Record<ServiceState, string> = {
  checking: "Checking the API connection",
  online: "API foundation is online",
  unavailable: "API is currently unavailable",
};

export default function App() {
  const [serviceState, setServiceState] = useState<ServiceState>("checking");
  const [checkSequence, setCheckSequence] = useState(0);

  const retry = useCallback(() => {
    setServiceState("checking");
    setCheckSequence((current) => current + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    fetchHealth(controller.signal)
      .then(() => setServiceState("online"))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setServiceState("unavailable");
      });

    return () => controller.abort();
  }, [checkSequence]);

  return (
    <main>
      <section className="status-screen" aria-labelledby="page-title">
        <div className="status-copy">
          <h1 id="page-title">Intrusion detection workspace</h1>
          <p>
            The application foundation is ready. Dataset analysis and model
            inference will be added only after their implementation gates pass.
          </p>
        </div>

        <div className="service-status" aria-live="polite">
          <span
            className="status-marker"
            data-state={serviceState}
            aria-hidden="true"
          />
          <span>{STATUS_COPY[serviceState]}</span>
        </div>

        {serviceState === "unavailable" ? (
          <button type="button" onClick={retry}>
            Check again
          </button>
        ) : null}
      </section>
    </main>
  );
}
