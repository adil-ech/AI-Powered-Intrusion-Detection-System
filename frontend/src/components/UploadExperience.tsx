import { useEffect, useState } from "react";

import type { ModelMetadata } from "../types/api";

export type ModelConnection =
  | { status: "checking" }
  | { status: "ready"; model: ModelMetadata }
  | { status: "unavailable"; message: string };

interface UploadExperienceProps {
  connection: ModelConnection;
  onDownloadTemplate: () => Promise<void>;
  onFile: (file: File) => void;
  onRetryConnection: () => void;
  onReviewSample: () => void;
}

const DECISIONS = [
  {
    id: "schema",
    title: "Match the schema.",
    body: "Headers are checked against the 63-field features-v1 contract. Invalid rows stay separate from predictions.",
  },
  {
    id: "binary",
    title: "Score suspicion first.",
    body: "The calibrated binary model applies the frozen 0.015 threshold before an attack family can be assigned.",
  },
  {
    id: "family",
    title: "Name the family.",
    body: "Suspicious rows receive one of seven families, joint confidence, and an analyst-priority band.",
  },
] as const;

type DecisionId = (typeof DECISIONS)[number]["id"];

const LIMITS = [
  {
    question: "What does low confidence mean?",
    answer:
      "A score below 0.65 is still a model prediction, not an unknown-attack category. It needs human review.",
  },
  {
    question: "Does this replace a SIEM?",
    answer:
      "No. This is an educational batch-analysis demo, not packet capture, automatic blocking, or a production SIEM replacement.",
  },
  {
    question: "Which fields are excluded?",
    answer:
      "Direct identifiers, timestamps, source port, and destination port are deliberately excluded from the model contract.",
  },
  {
    question: "How representative is the model?",
    answer:
      "CIC-IDS2017 is a controlled 2017 lab dataset. Strong in-dataset results do not promise performance on current operational traffic.",
  },
  {
    question: "Where does an upload go?",
    answer:
      "The API processes uploads in memory without retaining row values or writing the CSV to application storage.",
  },
] as const;

function DecisionFragment({ active }: { active: DecisionId }) {
  if (active === "schema") {
    return (
      <div className="decision-fragment" key={active} data-ui>
        <div className="fragment-heading">
          <span>Schema check</span>
          <strong className="fragment-state is-good">Matched</strong>
        </div>
        <div className="schema-count">
          <strong>63</strong>
          <span>of 63 required fields</span>
        </div>
        <div className="field-sample" aria-label="Matched feature examples">
          <span>flow_duration</span>
          <span>total_fwd_packets</span>
          <span>packet_length_variance</span>
        </div>
      </div>
    );
  }

  if (active === "binary") {
    return (
      <div className="decision-fragment" key={active} data-ui>
        <div className="fragment-heading">
          <span>Binary gate</span>
          <strong className="fragment-state is-alert">Suspicious</strong>
        </div>
        <div className="probability-readout">
          <strong>99.3%</strong>
          <span>malicious probability</span>
        </div>
        <div
          className="threshold-track"
          aria-label="99.3 percent versus 1.5 percent threshold"
        >
          <span className="threshold-fill" />
          <span className="threshold-marker">threshold 1.5%</span>
        </div>
      </div>
    );
  }

  return (
    <div className="decision-fragment" key={active} data-ui>
      <div className="fragment-heading">
        <span>Family classifier</span>
        <strong className="fragment-state is-alert">High priority</strong>
      </div>
      <div className="family-result">
        <div>
          <strong>DoS / DDoS</strong>
          <span>96.8% joint confidence</span>
        </div>
        <div
          className="family-bar"
          aria-label="DoS or DDoS 97.4 percent conditional confidence"
        >
          <span />
        </div>
      </div>
      <div className="family-alternatives">
        <span>Port scan 1.4%</span>
        <span>Botnet 0.8%</span>
      </div>
    </div>
  );
}

export function UploadExperience({
  connection,
  onDownloadTemplate,
  onFile,
  onRetryConnection,
  onReviewSample,
}: UploadExperienceProps) {
  const [activeDecision, setActiveDecision] = useState<DecisionId>("schema");
  const [activeLimit, setActiveLimit] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [isDownloadingTemplate, setIsDownloadingTemplate] = useState(false);
  const modelReady = connection.status === "ready";

  useEffect(() => {
    const elements = Array.from(
      document.querySelectorAll<HTMLElement>("[data-reveal]"),
    );
    if (!("IntersectionObserver" in window)) {
      elements.forEach((element) => element.classList.add("is-in"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            observer.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.1 },
    );
    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const statements = Array.from(
      document.querySelectorAll<HTMLElement>("[data-decision]"),
    );
    if (!("IntersectionObserver" in window)) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const activeEntry = entries.find((entry) => entry.isIntersecting);
        const decision = activeEntry?.target.getAttribute("data-decision");
        if (decision && DECISIONS.some((item) => item.id === decision)) {
          setActiveDecision(decision as DecisionId);
        }
      },
      { rootMargin: "-38% 0px -38% 0px", threshold: 0 },
    );
    statements.forEach((statement) => observer.observe(statement));
    return () => observer.disconnect();
  }, []);

  const acceptFile = (file?: File) => {
    if (file && modelReady) {
      onFile(file);
    }
  };

  return (
    <div className="entry-page">
      <header className="entry-header wrap">
        <a className="wordmark" href="#top" aria-label="Flow review home">
          Flow review
        </a>
        <nav aria-label="Page navigation">
          <a className="text-link" href="#decision-path">
            Model
          </a>
          <a className="text-link" href="#limits">
            Limits
          </a>
        </nav>
      </header>

      <main id="top">
        <section className="entry-hero wrap" aria-labelledby="entry-title">
          <div className="entry-column">
            <h1
              aria-label="Find the flows worth reviewing"
              id="entry-title"
              className="entry-title"
            >
              <span className="line-mask">
                <span>Find the flows</span>
              </span>
              <span className="line-mask">
                <span>worth reviewing</span>
              </span>
            </h1>
            <p className="entry-lead" data-rise>
              Upload CICFlowMeter CSV features and inspect row-level categories,
              confidence, and analyst-priority bands before deciding what
              deserves attention.
            </p>

            <div
              className={`upload-fragment${isDragging ? " is-dragging" : ""}`}
              data-ui
              data-rise
              onDragEnter={(event) => {
                event.preventDefault();
                setIsDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                if (
                  !event.currentTarget.contains(event.relatedTarget as Node)
                ) {
                  setIsDragging(false);
                }
              }}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragging(false);
                acceptFile(event.dataTransfer.files[0]);
              }}
            >
              <div className="upload-copy">
                <strong>Choose a network-flow CSV</strong>
                <span>or drop one into this panel</span>
              </div>
              <input
                aria-label="Traffic CSV"
                aria-describedby="file-rules service-note"
                accept=".csv,text/csv,application/csv"
                disabled={!modelReady}
                id="traffic-file"
                name="traffic-file"
                onChange={(event) => acceptFile(event.target.files?.[0])}
                type="file"
              />
              <div className="upload-actions">
                <button
                  className="button button-primary"
                  disabled={!modelReady}
                  type="button"
                  onClick={() =>
                    document.getElementById("traffic-file")?.click()
                  }
                >
                  Choose CSV
                </button>
                <button
                  className="text-button"
                  disabled={!modelReady}
                  type="button"
                  onClick={onReviewSample}
                >
                  Review sample
                </button>
              </div>
              <p id="file-rules" className="fragment-note">
                CSV only. Up to 10&nbsp;MiB, 10,000 rows, and 120 columns.
              </p>
            </div>

            <div className="entry-practical" data-rise>
              <button
                className="text-button"
                disabled={!modelReady || isDownloadingTemplate}
                type="button"
                onClick={() => {
                  setIsDownloadingTemplate(true);
                  void onDownloadTemplate().finally(() =>
                    setIsDownloadingTemplate(false),
                  );
                }}
              >
                {isDownloadingTemplate
                  ? "Downloading template…"
                  : "Download model template"}
              </button>
              <p>Uploads are processed in memory and are not retained.</p>
            </div>
            <div
              id="service-note"
              className="service-disclosure service-status"
              data-rise
              role="status"
            >
              {connection.status === "checking" ? (
                <span>Checking model readiness…</span>
              ) : null}
              {connection.status === "ready" ? (
                <span>
                  Model ready: {connection.model.model_version} ·{" "}
                  {connection.model.feature_schema_version} ·{" "}
                  {connection.model.required_features.length} fields
                </span>
              ) : null}
              {connection.status === "unavailable" ? (
                <>
                  <span>{connection.message}</span>
                  <button
                    className="text-button"
                    onClick={onRetryConnection}
                    type="button"
                  >
                    Retry connection
                  </button>
                </>
              ) : null}
            </div>
          </div>
        </section>

        <section
          className="decision-section wrap"
          id="decision-path"
          aria-labelledby="decision-title"
        >
          <div className="decision-copy">
            <h2 id="decision-title" data-reveal>
              One visible decision path
            </h2>
            {DECISIONS.map((decision) => (
              <button
                aria-pressed={activeDecision === decision.id}
                className="decision-statement"
                data-decision={decision.id}
                data-reveal
                key={decision.id}
                onClick={() => setActiveDecision(decision.id)}
                onFocus={() => setActiveDecision(decision.id)}
                type="button"
              >
                <strong>{decision.title}</strong>
                <span>{decision.body}</span>
              </button>
            ))}
          </div>
          <div className="decision-stage" aria-live="polite" data-reveal>
            <DecisionFragment active={activeDecision} />
          </div>
        </section>

        <section className="contract-field" aria-labelledby="contract-title">
          <div className="wrap contract-layout">
            <h2 id="contract-title" data-reveal>
              The output contract
            </h2>
            <div className="contract-board" data-reveal data-ui>
              <div className="contract-mark is-wide">
                <strong>63</strong>
                <span>required flow features</span>
              </div>
              <div className="contract-mark">
                <strong>8</strong>
                <span>output categories</span>
              </div>
              <div className="contract-mark">
                <strong>0.015</strong>
                <span>malicious threshold</span>
              </div>
              <div className="contract-mark">
                <strong>10,000</strong>
                <span>CSV rows per request</span>
              </div>
              <div className="contract-mark">
                <strong>120</strong>
                <span>columns per request</span>
              </div>
              <div className="contract-mark is-wide">
                <strong>
                  {connection.status === "ready"
                    ? connection.model.model_version
                    : "Awaiting API"}
                </strong>
                <span>active artifact version</span>
              </div>
            </div>
          </div>
        </section>

        <section
          className="review-proof wrap"
          aria-labelledby="review-proof-title"
        >
          <h2 id="review-proof-title" data-reveal>
            From score to review
          </h2>
          <div className="review-slices">
            <div className="row-slice" data-reveal data-ui>
              <div className="slice-heading">
                <span>flow-002</span>
                <strong className="fragment-state is-alert">Suspicious</strong>
              </div>
              <strong className="slice-category">DoS / DDoS</strong>
              <dl>
                <div>
                  <dt>Malicious</dt>
                  <dd>99.3%</dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>96.8%</dd>
                </div>
                <div>
                  <dt>Priority</dt>
                  <dd>High</dd>
                </div>
              </dl>
            </div>
            <div className="validation-slice" data-reveal data-ui>
              <div className="slice-heading">
                <span>edge-09</span>
                <strong className="fragment-state is-alert">Rejected</strong>
              </div>
              <strong>Invalid feature value</strong>
              <span>flow_duration</span>
              <p>Excluded before inference</p>
            </div>
            <div className="export-slice" data-reveal data-ui>
              <div className="slice-heading">
                <span>Export view</span>
                <strong className="fragment-state is-good">Ready</strong>
              </div>
              <strong>2 filtered rows</strong>
              <p>
                Predictions plus request, model, schema, status, and warnings.
              </p>
              <span>flow-review-mixed.csv</span>
            </div>
          </div>
        </section>

        <section
          className="limits-section wrap"
          id="limits"
          aria-labelledby="limits-title"
        >
          <div className="limit-questions">
            <h2 id="limits-title" data-reveal>
              What the score cannot say
            </h2>
            {LIMITS.map((limit, index) => (
              <button
                aria-pressed={activeLimit === index}
                className="limit-question"
                data-reveal
                key={limit.question}
                onClick={() => setActiveLimit(index)}
                onFocus={() => setActiveLimit(index)}
                type="button"
              >
                <span className="question-marker" aria-hidden="true" />
                {limit.question}
              </button>
            ))}
          </div>
          <div className="limit-answer" aria-live="polite" data-reveal>
            <p>{LIMITS[activeLimit].answer}</p>
            {activeLimit === 3 ? (
              <p className="answer-note">
                Infiltration has limited held-out evidence. Rare Other has no
                held-out support estimate.
              </p>
            ) : null}
          </div>
        </section>

        <section className="scenario-section" aria-labelledby="service-title">
          <div className="wrap scenario-layout" data-reveal>
            <div>
              <h2 id="service-title">One live model boundary</h2>
              <p>
                Readiness, templates, uploads, and predictions resolve through
                API-v1 against the same integrity-checked artifact.
              </p>
            </div>
            <div className="scenario-list" data-ui>
              <div className="scenario-row">
                <strong>Readiness</strong>
                <span>
                  {connection.status === "ready" ? "Ready" : "Not ready"}
                </span>
              </div>
              <div className="scenario-row">
                <strong>Artifact</strong>
                <span>
                  {connection.status === "ready"
                    ? connection.model.model_version
                    : "Unavailable"}
                </span>
              </div>
              <div className="scenario-row">
                <strong>Schema</strong>
                <span>
                  {connection.status === "ready"
                    ? connection.model.feature_schema_version
                    : "Unavailable"}
                </span>
              </div>
            </div>
          </div>
        </section>

        <section
          className="closing-section wrap"
          aria-labelledby="closing-title"
          data-reveal
        >
          <div>
            <h2 id="closing-title">Put a traffic batch under review</h2>
            <p>
              Start with a model-compatible CSV or send the safe six-row sample
              through the live inference service.
            </p>
          </div>
          <button
            className="button button-primary"
            disabled={!modelReady}
            type="button"
            onClick={() => document.getElementById("traffic-file")?.click()}
          >
            Choose CSV
          </button>
        </section>
      </main>

      <footer className="entry-footer wrap">
        <strong>Flow review</strong>
        <p>Educational intrusion-detection demo using CIC-IDS2017.</p>
        <a className="text-link" href="#top">
          Back to upload
        </a>
      </footer>
    </div>
  );
}
