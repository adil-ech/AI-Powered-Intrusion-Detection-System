# Phase 7 frontend art direction

## Audience and argument

The reader is a security analyst or reviewer who already understands network flows and needs to see whether the model exposes enough evidence to support triage.

This is a browser workspace for reviewing row-level predictions from the frozen CIC-IDS2017 two-stage Random Forest. After the first screen, the reader should believe that the workflow makes its contract and uncertainty visible instead of presenting an unexplained alert score.

The page argument is:

1. A CICFlowMeter-compatible CSV becomes a reviewable row-level result. Proof: the upload control and a working mixed-traffic fixture.
2. Every suspicious category follows the same visible path. Proof: interface fragments for schema validation, the calibrated binary gate, and conditional family classification.
3. The output is usable for triage rather than just demonstration. Proof: exact fixture-backed counts, distributions, filters, sorting, pagination, row detail, and enriched export.
4. The limits remain beside the result. Proof: low-confidence language, validation errors, model identity, privacy copy, and the documented CIC-IDS2017 limitations.

The primary action is **Choose CSV**. The secondary action is **Review sample**.

## Subject inventory

- The model accepts exactly 63 ordered `features-v1` flow fields.
- Direct identifiers, timestamps, source port, and destination port are excluded.
- A calibrated binary Random Forest applies the frozen malicious threshold of `0.015`.
- A second Random Forest assigns one of seven attack families only after the binary gate is crossed.
- `BENIGN` plus seven attack families form the eight-category response contract.
- Joint suspicious confidence, not family confidence alone, determines the displayed confidence and priority.
- Confidence below `0.65` remains a prediction but is marked for review; the model does not claim an unknown-attack category.
- CSV requests allow 10 MiB, 10,000 data rows, and 120 columns.
- Invalid rows remain visible as row errors and are not counted as predictions.
- The frozen artifact is `ids-rf-v1.0.0`, trained on CIC-IDS2017.
- `INFILTRATION` has weak held-out support and `RARE_OTHER` has none.
- Uploads are processed in memory and are not retained or logged by the application.

## Dealt direction

- Skill: `design-taste-frontend`
- Direction: **The product performs**
- Seed: `216573512`
- Sector and tone: `dev-tool`, technical
- Redraws: none
- Typeface: Jost, weights 400, 500, and 700
- Palette: Three stones (`#eeecea`, `#e4e1dd`, `#333231`, `#6b6763`, `#5c6b54`, `#cdc3b6`)
- Composition: restrained upload entry on one alignment, followed by real HTML fragments that demonstrate validation, scoring, and review. The results workspace switches to an information-dense analyst layout.
- Signature motion: the active three-stage classifier fragment crossfades as its explanation changes. Other motion is limited to ordered entrances, control feedback, and short state transitions, with a reduced-motion alternative.
- Imagery: the product interface is the subject. No unrelated cyber stock photography, fake browser frame, device mockup, or decorative dashboard is used.

The direction’s proof-logo board, email-form call to action, and tiled local-time footer are omitted because the project has no supplied logos, mailing-list action, office, or local-time claim. Keeping them would add invented proof or furniture text. The true output contract, model limits, and upload action carry those positions in the argument.

## Page idea and live thing

On this page, the model’s 63-feature contract becomes a visible chain from CSV row to binary gate to attack family.

The live thing is the fixture-backed review workflow: a visitor can load a versioned mixed-traffic response, isolate rows with the same filters intended for live analysis, open the evidence for a row, and export the selected result set.

## Copy deck

### Upload entry

- Product name: **Flow review**
- Headline: **Find the flows worth reviewing**
- Supporting line: **Upload CICFlowMeter CSV features and inspect row-level categories, confidence, and analyst-priority bands before deciding what deserves attention.**
- Primary action: **Choose CSV**
- Secondary action: **Review sample**
- Input facts: **CSV only. Up to 10 MiB, 10,000 rows, and 120 columns.**
- Privacy: **Uploads are processed in memory and are not retained by the application.**
- Fixture disclosure: **This preview uses versioned local responses. Live model calls are connected at the next implementation gate.**

### Decision path

- Heading: **One visible decision path**
- Validate: **Match the schema.** Headers are checked against the 63-field `features-v1` contract. Invalid rows stay separate from predictions.
- Detect: **Score suspicion first.** The calibrated binary model applies the frozen `0.015` threshold before an attack family can be assigned.
- Classify: **Name the family.** Suspicious rows receive one of seven families, joint confidence, and an analyst-priority band.

### Limits

- Heading: **What the score cannot say**
- Low confidence: A score below `0.65` is still a model prediction, not an unknown-attack category. It needs human review.
- Operational scope: The project is an educational batch-analysis demo, not packet capture, automatic blocking, or a SIEM replacement.
- Dataset scope: CIC-IDS2017 is a controlled 2017 lab dataset. Strong in-dataset results do not promise performance on current operational traffic.
- Rare categories: `INFILTRATION` has limited held-out evidence. `RARE_OTHER` has no held-out support estimate.
- Excluded fields: Direct identifiers, timestamps, source port, and destination port are deliberately excluded from the model contract.

### Results workspace

- Title: **Traffic review**
- Summary labels: **Rows received**, **Valid**, **Suspicious**, **High priority**, and **Needs review**
- Table empty message: **No rows match this view.**
- Row detail warning: **Confidence is not certainty. Confirm important findings with source traffic and other security evidence.**
- Export action: **Export view**
- Return action: **New analysis**

## Fixture and content disclosure

Phase 7 intentionally uses sample content rather than live inference. The versioned fixtures cover normal traffic, mixed traffic, invalid input, partial validation with low-confidence rows, empty output, and service failure. They use invented row identifiers only; the model identity, thresholds, category names, limits, and feature-contract facts come from the repository’s frozen contracts and model card.

No external photographs, videos, logos, testimonials, user counts, or performance claims are used, so there are no asset credits.
