#!/usr/bin/env python3
"""Validate Phase 0 documents and machine-readable contracts."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "PROJECT_PLAN.md",
    "IMPLEMENTATION_WORKFLOW.md",
    "docs/decisions/0001-mvp-scope.md",
    "docs/decisions/0002-data-and-label-contract.md",
    "docs/decisions/0003-model-evaluation.md",
    "docs/api-contract.md",
    "contracts/labels-v1.json",
    "contracts/api-v1/model-response.example.json",
    "contracts/api-v1/prediction-response.example.json",
)

CATEGORIES = (
    "BENIGN",
    "DOS_DDOS",
    "PORT_SCAN",
    "BRUTE_FORCE",
    "WEB_ATTACK",
    "BOTNET",
    "INFILTRATION",
    "RARE_OTHER",
)

PREDICTION_FIELDS = {
    "row_id",
    "is_suspicious",
    "predicted_category",
    "malicious_probability",
    "category_confidence",
    "confidence",
    "confidence_status",
    "risk_level",
    "warnings",
}

TOP_LEVEL_RESPONSE_FIELDS = {
    "request_id",
    "status",
    "model",
    "summary",
    "predictions",
    "row_errors",
    "warnings",
}

MODEL_RESPONSE_FIELDS = {
    "model_name",
    "model_version",
    "artifact_status",
    "training_dataset",
    "feature_schema_version",
    "feature_schema_hash",
    "required_features",
    "attack_categories",
    "thresholds",
    "created_at",
}

MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_required_files(errors: list[str]) -> None:
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            fail(errors, f"missing required file: {relative}")


def iter_markdown_files() -> Iterable[Path]:
    for path in ROOT.rglob("*.md"):
        if ".git" not in path.parts:
            yield path


def validate_markdown_links(errors: list[str]) -> None:
    for path in iter_markdown_files():
        text = path.read_text(encoding="utf-8")
        for target in MARKDOWN_LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#", "/")):
                continue
            clean_target = target.split("#", 1)[0]
            if not clean_target:
                continue
            resolved = (path.parent / clean_target).resolve()
            if not resolved.exists():
                fail(
                    errors,
                    f"broken relative link in {path.relative_to(ROOT)}: {target}",
                )


def validate_mermaid(errors: list[str]) -> None:
    allowed_starts = ("flowchart ", "graph ", "sequenceDiagram", "stateDiagram")
    for path in iter_markdown_files():
        text = path.read_text(encoding="utf-8")
        if text.count("```mermaid") != len(MERMAID_BLOCK.findall(text)):
            fail(errors, f"unclosed Mermaid fence in {path.relative_to(ROOT)}")
            continue
        for index, block in enumerate(MERMAID_BLOCK.findall(text), start=1):
            stripped = block.strip()
            if not stripped.startswith(allowed_starts):
                fail(
                    errors,
                    f"unsupported Mermaid diagram start in {path.relative_to(ROOT)} block {index}",
                )
            for opening, closing in (("[", "]"), ("{", "}"), ("(", ")")):
                if stripped.count(opening) != stripped.count(closing):
                    fail(
                        errors,
                        f"unbalanced {opening}{closing} in {path.relative_to(ROOT)} block {index}",
                    )


def validate_labels(errors: list[str]) -> None:
    path = ROOT / "contracts/labels-v1.json"
    data = load_json(path)
    categories = data.get("categories")
    if not isinstance(categories, list):
        fail(errors, "labels-v1 categories must be a list")
        return

    names = [item.get("name") for item in categories if isinstance(item, dict)]
    if tuple(names) != CATEGORIES:
        fail(errors, f"label categories differ from frozen order: {names}")

    seen_labels: dict[str, str] = {}
    for item in categories:
        if not isinstance(item, dict):
            fail(errors, "each label category must be an object")
            continue
        name = item.get("name")
        target = item.get("binary_target")
        expected_target = "benign" if name == "BENIGN" else "malicious"
        if target != expected_target:
            fail(errors, f"{name} has invalid binary target: {target}")
        source_labels = item.get("source_labels")
        if not isinstance(source_labels, list) or not source_labels:
            fail(errors, f"{name} must map at least one source label")
            continue
        for source_label in source_labels:
            if source_label in seen_labels:
                fail(
                    errors,
                    f"source label {source_label} maps to both {seen_labels[source_label]} and {name}",
                )
            seen_labels[source_label] = str(name)

    if len(seen_labels) != 15:
        fail(errors, f"expected 15 normalized CIC-IDS2017 labels, found {len(seen_labels)}")


def is_probability(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0 <= float(value) <= 1
    )


def validate_prediction_example(errors: list[str]) -> None:
    data = load_json(ROOT / "contracts/api-v1/prediction-response.example.json")
    if set(data) != TOP_LEVEL_RESPONSE_FIELDS:
        fail(errors, f"prediction response top-level fields differ: {sorted(data)}")
    if data.get("status") not in {"COMPLETE", "PARTIAL_SUCCESS"}:
        fail(errors, "prediction response has invalid status")

    predictions = data.get("predictions")
    if not isinstance(predictions, list) or not predictions:
        fail(errors, "prediction example must contain predictions")
        return

    for index, prediction in enumerate(predictions):
        if set(prediction) != PREDICTION_FIELDS:
            fail(errors, f"prediction {index} fields differ: {sorted(prediction)}")
            continue
        category = prediction["predicted_category"]
        if category not in CATEGORIES:
            fail(errors, f"prediction {index} has unsupported category {category}")
        for field in ("malicious_probability", "confidence"):
            if not is_probability(prediction[field]):
                fail(errors, f"prediction {index} {field} is not a probability")

        suspicious = prediction["is_suspicious"]
        malicious_probability = float(prediction["malicious_probability"])
        confidence = float(prediction["confidence"])
        category_confidence = prediction["category_confidence"]

        if suspicious:
            if category == "BENIGN":
                fail(errors, f"prediction {index} is suspicious but BENIGN")
            if not is_probability(category_confidence):
                fail(errors, f"prediction {index} lacks valid category confidence")
            elif not math.isclose(
                confidence,
                malicious_probability * float(category_confidence),
                abs_tol=1e-6,
            ):
                fail(errors, f"prediction {index} joint confidence is inconsistent")
        else:
            if category != "BENIGN":
                fail(errors, f"prediction {index} is benign but category is {category}")
            if category_confidence is not None:
                fail(errors, f"prediction {index} benign category confidence must be null")
            if not math.isclose(confidence, 1 - malicious_probability, abs_tol=1e-6):
                fail(errors, f"prediction {index} benign confidence is inconsistent")

        if prediction["confidence_status"] not in {"OK", "LOW_CONFIDENCE"}:
            fail(errors, f"prediction {index} has invalid confidence status")
        if prediction["risk_level"] not in {"LOW", "MEDIUM", "HIGH"}:
            fail(errors, f"prediction {index} has invalid risk level")

    summary = data.get("summary", {})
    total_rows = summary.get("total_rows")
    valid_rows = summary.get("valid_rows")
    invalid_rows = summary.get("invalid_rows")
    if total_rows != valid_rows + invalid_rows:
        fail(errors, "prediction summary total does not equal valid plus invalid rows")
    if valid_rows != len(predictions):
        fail(errors, "prediction summary valid row count differs from predictions")
    if summary.get("benign_rows") != sum(
        prediction["predicted_category"] == "BENIGN" for prediction in predictions
    ):
        fail(errors, "prediction summary benign count is inconsistent")
    if summary.get("suspicious_rows") != sum(
        prediction["is_suspicious"] for prediction in predictions
    ):
        fail(errors, "prediction summary suspicious count is inconsistent")

    expected_counts: dict[str, int] = {}
    for prediction in predictions:
        category = prediction["predicted_category"]
        expected_counts[category] = expected_counts.get(category, 0) + 1
    if summary.get("category_counts") != expected_counts:
        fail(errors, "prediction summary category counts are inconsistent")


def validate_model_example(errors: list[str]) -> None:
    data = load_json(ROOT / "contracts/api-v1/model-response.example.json")
    if set(data) != MODEL_RESPONSE_FIELDS:
        fail(errors, f"model response fields differ: {sorted(data)}")
    if tuple(data.get("attack_categories", ())) != CATEGORIES:
        fail(errors, "model example attack categories differ from frozen taxonomy")
    features = data.get("required_features")
    if not isinstance(features, list) or not features or len(features) != len(set(features)):
        fail(errors, "model example required features must be nonempty and unique")
    thresholds = data.get("thresholds", {})
    for name in ("malicious", "low_confidence", "high_risk"):
        if not is_probability(thresholds.get(name)):
            fail(errors, f"model example threshold {name} is invalid")


def validate_document_consistency(errors: list[str]) -> None:
    paths = (
        ROOT / "PROJECT_PLAN.md",
        ROOT / "docs/decisions/0002-data-and-label-contract.md",
        ROOT / "docs/api-contract.md",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for category in CATEGORIES:
            if f"`{category}`" not in text and category not in text:
                fail(errors, f"{path.relative_to(ROOT)} does not mention {category}")

    api_text = (ROOT / "docs/api-contract.md").read_text(encoding="utf-8")
    for field in PREDICTION_FIELDS:
        if f"`{field}`" not in api_text:
            fail(errors, f"API contract does not define prediction field {field}")

    model_decision = (
        ROOT / "docs/decisions/0003-model-evaluation.md"
    ).read_text(encoding="utf-8")
    for phrase in (
        "untouched final-test",
        "selected malicious threshold",
        "class support",
        "LOW_CONFIDENCE",
    ):
        if phrase not in model_decision:
            fail(errors, f"model evaluation decision is missing required phrase: {phrase}")

    label_decision = (
        ROOT / "docs/decisions/0002-data-and-label-contract.md"
    ).read_text(encoding="utf-8")
    for phrase in ("unrecognized training label is an error", "not an `UNKNOWN` category"):
        if phrase not in label_decision:
            fail(errors, f"data decision is missing required behavior: {phrase}")

    scope_decision = (ROOT / "docs/decisions/0001-mvp-scope.md").read_text(
        encoding="utf-8"
    )
    for phrase in ("10 MiB", "10,000"):
        if phrase not in scope_decision or phrase not in api_text:
            fail(errors, f"scope and API contract do not both define: {phrase}")
    if "not stored or logged" not in scope_decision:
        fail(errors, "scope decision does not define upload-retention behavior")


def main() -> int:
    errors: list[str] = []
    validate_required_files(errors)
    if not errors:
        validate_markdown_links(errors)
        validate_mermaid(errors)
        validate_labels(errors)
        validate_prediction_example(errors)
        validate_model_example(errors)
        validate_document_consistency(errors)

    if errors:
        print("Phase 0 contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    markdown_count = sum(1 for _ in iter_markdown_files())
    print(
        "Phase 0 contract validation passed: "
        f"{len(REQUIRED_FILES)} required files, {markdown_count} Markdown files, "
        f"{len(CATEGORIES)} categories."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
