import {
  type CSSProperties,
  type KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  RISK_ORDER,
  attackDistribution,
  confidenceDistribution,
  formatCategory,
  formatPercent,
} from "../lib/analytics";
import { buildEnrichedCsv, downloadTextFile } from "../lib/csv";
import { ATTACK_CATEGORIES } from "../types/api";
import type {
  AttackCategory,
  BatchPredictionResponse,
  ModelMetadata,
  Prediction,
  RiskLevel,
} from "../types/api";

interface ResultsDashboardProps {
  model: ModelMetadata;
  response: BatchPredictionResponse;
  sourceName?: string;
  initialRowId?: string;
  onReset: () => void;
}

type SortKey = "row_id" | "predicted_category" | "confidence" | "risk_level";
type SortDirection = "ascending" | "descending";

interface SortState {
  key: SortKey;
  direction: SortDirection;
}

const PAGE_SIZE = 5;

const CONTROL_KEYS: SortKey[] = [
  "row_id",
  "predicted_category",
  "confidence",
  "risk_level",
];

function compareRows(
  left: Prediction,
  right: Prediction,
  key: SortKey,
): number {
  if (key === "confidence") {
    return left.confidence - right.confidence;
  }
  if (key === "risk_level") {
    return RISK_ORDER[left.risk_level] - RISK_ORDER[right.risk_level];
  }
  return left[key].localeCompare(right[key]);
}

function BarList<T extends string>({
  data,
  emptyText,
}: {
  data: { label: T; count: number; percentage: number }[];
  emptyText: string;
}) {
  if (data.length === 0 || data.every((item) => item.count === 0)) {
    return <p className="chart-empty">{emptyText}</p>;
  }

  const maximum = Math.max(...data.map((item) => item.count), 1);
  return (
    <ul className="bar-list">
      {data.map((item) => (
        <li key={item.label}>
          <div className="bar-label">
            <span>
              {ATTACK_CATEGORIES.includes(item.label as AttackCategory)
                ? formatCategory(item.label as AttackCategory)
                : item.label}
            </span>
            <strong>
              {item.count} <span>({item.percentage.toFixed(0)}%)</span>
            </strong>
          </div>
          <div className="bar-track" aria-hidden="true">
            <span
              className="bar-fill"
              style={
                {
                  "--bar-size": `${Math.max((item.count / maximum) * 100, 3)}%`,
                } as CSSProperties
              }
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

function SortButton({
  children,
  column,
  sort,
  onSort,
}: {
  children: React.ReactNode;
  column: SortKey;
  sort: SortState;
  onSort: (column: SortKey) => void;
}) {
  const active = sort.key === column;
  return (
    <button
      aria-label={`Sort by ${String(children)}${active ? `, currently ${sort.direction}` : ""}`}
      className="sort-button"
      onClick={() => onSort(column)}
      type="button"
    >
      {children}
      <span aria-hidden="true">
        {active ? (sort.direction === "ascending" ? "↑" : "↓") : "↕"}
      </span>
    </button>
  );
}

function RowDetailDialog({
  row,
  onClose,
  returnFocus,
}: {
  row: Prediction;
  onClose: () => void;
  returnFocus: HTMLElement | null;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.focus();
    return () => returnFocus?.focus();
  }, [returnFocus]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }
    const controls = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (!controls || controls.length === 0) {
      event.preventDefault();
      return;
    }
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      className="dialog-backdrop"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) {
          onClose();
        }
      }}
    >
      <div
        aria-labelledby="row-detail-title"
        aria-modal="true"
        className="row-dialog"
        onKeyDown={handleKeyDown}
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        <div className="dialog-header">
          <div>
            <p>Row evidence</p>
            <h2 id="row-detail-title">{row.row_id}</h2>
          </div>
          <button
            className="button button-neutral"
            onClick={onClose}
            type="button"
          >
            Close
          </button>
        </div>

        <div className="detail-verdict">
          <span
            className={`verdict-mark ${row.is_suspicious ? "is-alert" : "is-benign"}`}
            aria-hidden="true"
          />
          <div>
            <strong>{row.is_suspicious ? "Suspicious" : "Benign"}</strong>
            <span>{formatCategory(row.predicted_category)}</span>
          </div>
          <strong className={`risk-text risk-${row.risk_level.toLowerCase()}`}>
            {row.risk_level.toLowerCase()} priority
          </strong>
        </div>

        <dl className="detail-values">
          <div>
            <dt>Malicious probability</dt>
            <dd>{formatPercent(row.malicious_probability, 2)}</dd>
          </div>
          <div>
            <dt>Family confidence</dt>
            <dd>
              {row.category_confidence === null
                ? "Not applicable"
                : formatPercent(row.category_confidence, 2)}
            </dd>
          </div>
          <div>
            <dt>Joint confidence</dt>
            <dd>{formatPercent(row.confidence, 2)}</dd>
          </div>
          <div>
            <dt>Confidence status</dt>
            <dd>
              {row.confidence_status === "OK"
                ? "Above threshold"
                : "Needs review"}
            </dd>
          </div>
        </dl>

        {row.warnings.length > 0 ? (
          <div className="detail-warning" role="note">
            <strong>Review note</strong>
            {row.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        ) : null}

        <p className="confidence-caveat">
          Confidence is not certainty. Confirm important findings with source
          traffic and other security evidence.
        </p>
      </div>
    </div>
  );
}

export function ResultsDashboard({
  model,
  response,
  sourceName,
  initialRowId,
  onReset,
}: ResultsDashboardProps) {
  const [category, setCategory] = useState<AttackCategory | "ALL">("ALL");
  const [risk, setRisk] = useState<RiskLevel | "ALL">("ALL");
  const [confidence, setConfidence] = useState<"ALL" | "LOW_CONFIDENCE">("ALL");
  const [verdict, setVerdict] = useState<"ALL" | "SUSPICIOUS" | "BENIGN">(
    "ALL",
  );
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState>({
    key: "risk_level",
    direction: "descending",
  });
  const [page, setPage] = useState(1);
  const [selectedRow, setSelectedRow] = useState<Prediction | null>(() =>
    initialRowId
      ? (response.predictions.find((row) => row.row_id === initialRowId) ??
        null)
      : null,
  );
  const [returnFocus, setReturnFocus] = useState<HTMLElement | null>(null);

  const filteredRows = useMemo(() => {
    const rows = response.predictions.filter((row) => {
      const categoryMatches =
        category === "ALL" || row.predicted_category === category;
      const riskMatches = risk === "ALL" || row.risk_level === risk;
      const confidenceMatches =
        confidence === "ALL" || row.confidence_status === confidence;
      const verdictMatches =
        verdict === "ALL" ||
        (verdict === "SUSPICIOUS" ? row.is_suspicious : !row.is_suspicious);
      const queryMatches = row.row_id
        .toLowerCase()
        .includes(query.trim().toLowerCase());
      return (
        categoryMatches &&
        riskMatches &&
        confidenceMatches &&
        verdictMatches &&
        queryMatches
      );
    });
    return [...rows].sort((left, right) => {
      const order = compareRows(left, right, sort.key);
      return sort.direction === "ascending" ? order : -order;
    });
  }, [category, confidence, query, response.predictions, risk, sort, verdict]);

  const pageCount = Math.max(Math.ceil(filteredRows.length / PAGE_SIZE), 1);
  const safePage = Math.min(page, pageCount);
  const visibleRows = filteredRows.slice(
    (safePage - 1) * PAGE_SIZE,
    safePage * PAGE_SIZE,
  );

  const lowConfidenceCount = response.predictions.filter(
    (row) => row.confidence_status === "LOW_CONFIDENCE",
  ).length;

  const changeFilter = (update: () => void) => {
    update();
    setPage(1);
  };

  const changeSort = (key: SortKey) => {
    if (!CONTROL_KEYS.includes(key)) {
      return;
    }
    setSort((current) => ({
      key,
      direction:
        current.key === key && current.direction === "descending"
          ? "ascending"
          : "descending",
    }));
    setPage(1);
  };

  const exportRows = () => {
    const source = (sourceName ?? "results")
      .replace(/\.csv$/i, "")
      .replace(/[^a-z0-9_-]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .toLowerCase();
    downloadTextFile(
      buildEnrichedCsv(response, filteredRows),
      `flow-review-${source || "results"}.csv`,
      "text/csv;charset=utf-8",
    );
  };

  return (
    <div className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <button
            className="wordmark wordmark-button"
            onClick={onReset}
            type="button"
          >
            Flow review
          </button>
          <span className="mode-label">Live model</span>
        </div>
        <div className="dashboard-actions">
          <button
            className="button button-neutral"
            onClick={onReset}
            type="button"
          >
            New analysis
          </button>
          <button
            className="button button-primary"
            disabled={filteredRows.length === 0}
            onClick={exportRows}
            type="button"
          >
            Export view
          </button>
        </div>
      </header>

      <main className="dashboard-main">
        <section className="dashboard-intro" aria-labelledby="dashboard-title">
          <div>
            <h1 id="dashboard-title">Traffic review</h1>
            <p>
              {sourceName ? `Uploaded as ${sourceName}. ` : ""}
              Scored by API-v1 using the active model.
            </p>
          </div>
          <dl className="request-meta">
            <div>
              <dt>Request</dt>
              <dd>{response.request_id}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd>{response.model.version}</dd>
            </div>
            <div>
              <dt>Schema</dt>
              <dd>{response.model.feature_schema_version}</dd>
            </div>
          </dl>
        </section>

        {response.status === "PARTIAL_SUCCESS" ? (
          <section
            className="validation-banner"
            aria-labelledby="validation-title"
          >
            <div>
              <h2 id="validation-title">Partial validation</h2>
              <p>
                {response.summary.invalid_rows} rows were rejected before
                inference. Valid predictions remain available below.
              </p>
            </div>
            <a className="text-link" href="#row-errors">
              Review row errors
            </a>
          </section>
        ) : null}

        <section className="summary-board" aria-label="Analysis summary">
          <div>
            <span>Rows received</span>
            <strong>{response.summary.total_rows}</strong>
          </div>
          <div>
            <span>Valid</span>
            <strong>{response.summary.valid_rows}</strong>
          </div>
          <div>
            <span>Suspicious</span>
            <strong>{response.summary.suspicious_rows}</strong>
          </div>
          <div>
            <span>High priority</span>
            <strong>{response.summary.high_risk_rows}</strong>
          </div>
          <div>
            <span>Needs review</span>
            <strong>{lowConfidenceCount}</strong>
          </div>
        </section>

        <section
          className="distribution-grid"
          aria-label="Prediction distributions"
        >
          <article className="chart-panel">
            <div className="panel-heading">
              <div>
                <h2>Attack distribution</h2>
                <p>Valid rows by predicted category</p>
              </div>
              <strong>{response.summary.valid_rows}</strong>
            </div>
            <BarList
              data={attackDistribution(response)}
              emptyText="No categories were returned for this batch."
            />
          </article>
          <article className="chart-panel">
            <div className="panel-heading">
              <div>
                <h2>Confidence distribution</h2>
                <p>Joint confidence used for review status</p>
              </div>
              <strong>{lowConfidenceCount}</strong>
            </div>
            <BarList
              data={confidenceDistribution(response.predictions)}
              emptyText="No confidence values were returned for this batch."
            />
          </article>
        </section>

        <section className="results-panel" aria-labelledby="results-title">
          <div className="results-heading">
            <div>
              <h2 id="results-title">Prediction rows</h2>
              <p>
                Showing{" "}
                {filteredRows.length === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1}
                –{Math.min(safePage * PAGE_SIZE, filteredRows.length)} of{" "}
                {filteredRows.length}
              </p>
            </div>
            <button
              className="text-button"
              onClick={() => {
                setCategory("ALL");
                setRisk("ALL");
                setConfidence("ALL");
                setVerdict("ALL");
                setQuery("");
                setPage(1);
              }}
              type="button"
            >
              Clear filters
            </button>
          </div>

          <form
            className="filter-bar"
            onSubmit={(event) => event.preventDefault()}
          >
            <label>
              <span>Find row</span>
              <input
                onChange={(event) =>
                  changeFilter(() => setQuery(event.target.value))
                }
                placeholder="Row ID"
                type="search"
                value={query}
              />
            </label>
            <label>
              <span>Verdict</span>
              <select
                onChange={(event) =>
                  changeFilter(() =>
                    setVerdict(
                      event.target.value as "ALL" | "SUSPICIOUS" | "BENIGN",
                    ),
                  )
                }
                value={verdict}
              >
                <option value="ALL">All verdicts</option>
                <option value="SUSPICIOUS">Suspicious</option>
                <option value="BENIGN">Benign</option>
              </select>
            </label>
            <label>
              <span>Category</span>
              <select
                onChange={(event) =>
                  changeFilter(() =>
                    setCategory(event.target.value as AttackCategory | "ALL"),
                  )
                }
                value={category}
              >
                <option value="ALL">All categories</option>
                {ATTACK_CATEGORIES.map((item) => (
                  <option key={item} value={item}>
                    {formatCategory(item)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Priority</span>
              <select
                onChange={(event) =>
                  changeFilter(() =>
                    setRisk(event.target.value as RiskLevel | "ALL"),
                  )
                }
                value={risk}
              >
                <option value="ALL">All priorities</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>
            </label>
            <label>
              <span>Confidence</span>
              <select
                onChange={(event) =>
                  changeFilter(() =>
                    setConfidence(
                      event.target.value as "ALL" | "LOW_CONFIDENCE",
                    ),
                  )
                }
                value={confidence}
              >
                <option value="ALL">All confidence</option>
                <option value="LOW_CONFIDENCE">Needs review</option>
              </select>
            </label>
          </form>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th
                    aria-sort={sort.key === "row_id" ? sort.direction : "none"}
                  >
                    <SortButton column="row_id" onSort={changeSort} sort={sort}>
                      Row
                    </SortButton>
                  </th>
                  <th>Verdict</th>
                  <th
                    aria-sort={
                      sort.key === "predicted_category"
                        ? sort.direction
                        : "none"
                    }
                  >
                    <SortButton
                      column="predicted_category"
                      onSort={changeSort}
                      sort={sort}
                    >
                      Category
                    </SortButton>
                  </th>
                  <th
                    aria-sort={
                      sort.key === "confidence" ? sort.direction : "none"
                    }
                  >
                    <SortButton
                      column="confidence"
                      onSort={changeSort}
                      sort={sort}
                    >
                      Confidence
                    </SortButton>
                  </th>
                  <th
                    aria-sort={
                      sort.key === "risk_level" ? sort.direction : "none"
                    }
                  >
                    <SortButton
                      column="risk_level"
                      onSort={changeSort}
                      sort={sort}
                    >
                      Priority
                    </SortButton>
                  </th>
                  <th>
                    <span className="visually-hidden">Row actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.row_id}>
                    <td data-label="Row">
                      <strong>{row.row_id}</strong>
                    </td>
                    <td data-label="Verdict">
                      <span className="verdict-cell">
                        <span
                          className={`verdict-mark ${row.is_suspicious ? "is-alert" : "is-benign"}`}
                          aria-hidden="true"
                        />
                        {row.is_suspicious ? "Suspicious" : "Benign"}
                      </span>
                    </td>
                    <td data-label="Category">
                      {formatCategory(row.predicted_category)}
                    </td>
                    <td data-label="Confidence">
                      <span>{formatPercent(row.confidence)}</span>
                      {row.confidence_status === "LOW_CONFIDENCE" ? (
                        <strong className="review-text">Needs review</strong>
                      ) : null}
                    </td>
                    <td data-label="Priority">
                      <strong
                        className={`risk-text risk-${row.risk_level.toLowerCase()}`}
                      >
                        {row.risk_level.charAt(0) +
                          row.risk_level.slice(1).toLowerCase()}
                      </strong>
                    </td>
                    <td>
                      <button
                        aria-haspopup="dialog"
                        className="row-action"
                        onClick={(event) => {
                          setReturnFocus(event.currentTarget);
                          setSelectedRow(row);
                        }}
                        type="button"
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visibleRows.length === 0 ? (
              <div className="table-empty">
                <h3>No rows match this view</h3>
                <p>Clear the filters or upload another traffic batch.</p>
              </div>
            ) : null}
          </div>

          <nav className="pagination" aria-label="Prediction pages">
            <button
              className="button button-neutral"
              disabled={safePage === 1}
              onClick={() => setPage((current) => Math.max(current - 1, 1))}
              type="button"
            >
              Previous
            </button>
            <span>
              Page {safePage} of {pageCount}
            </span>
            <button
              className="button button-neutral"
              disabled={safePage === pageCount}
              onClick={() =>
                setPage((current) => Math.min(current + 1, pageCount))
              }
              type="button"
            >
              Next
            </button>
          </nav>
        </section>

        {response.row_errors.length > 0 ? (
          <section
            className="row-errors"
            id="row-errors"
            aria-labelledby="row-errors-title"
          >
            <div>
              <h2 id="row-errors-title">Rejected rows</h2>
              <p>
                Rejected values are not echoed or included in prediction totals.
              </p>
            </div>
            <ul>
              {response.row_errors.map((error) => (
                <li key={error.row_id}>
                  <strong>{error.row_id}</strong>
                  <span>{error.message}</span>
                  <span>{error.fields.join(", ")}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="model-note" aria-labelledby="model-note-title">
          <div>
            <h2 id="model-note-title">Read the result with its limits</h2>
            <p>
              Risk is an analyst-priority band, not attack severity. Low
              confidence does not mean unknown attack, and every important
              finding needs corroboration.
            </p>
          </div>
          <dl>
            <div>
              <dt>Training data</dt>
              <dd>{model.training_dataset}</dd>
            </div>
            <div>
              <dt>Malicious threshold</dt>
              <dd>{model.thresholds.malicious}</dd>
            </div>
            <div>
              <dt>Low-confidence threshold</dt>
              <dd>{model.thresholds.low_confidence}</dd>
            </div>
            <div>
              <dt>Retention</dt>
              <dd>None at application level</dd>
            </div>
          </dl>
        </section>
      </main>

      <footer className="dashboard-footer">
        <span>Live API-v1 analysis</span>
        <span>{response.model.name}</span>
        <span>Uploads are processed in memory.</span>
      </footer>

      {selectedRow ? (
        <RowDetailDialog
          onClose={() => setSelectedRow(null)}
          returnFocus={returnFocus}
          row={selectedRow}
        />
      ) : null}
    </div>
  );
}
