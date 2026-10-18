# CIC-IDS2017 acquisition and audit

## Source and permitted use

The project uses the eight machine-learning CSV files in `MachineLearningCSV.zip` from the [official University of New Brunswick CIC-IDS2017 page](https://www.unb.ca/cic/datasets/ids-2017.html). The publisher describes five capture days from July 3 through July 7, 2017 and requires users and redistributors to cite the dataset and its research paper.

Required citation:

> Iman Sharafaldin, Arash Habibi Lashkari, and Ali A. Ghorbani, “Toward Generating a New Intrusion Detection Dataset and Intrusion Traffic Characterization,” 4th International Conference on Information Systems Security and Privacy (ICISSP), Portugal, 2018.

The [CIC dataset FAQ](https://www.unb.ca/cic/datasets/index.html) states that CIC datasets may be redistributed, republished, and mirrored when the dataset and listed research paper are cited.

## Download procedure

1. Open the official CIC-IDS2017 page and select **Download this dataset**.
2. Complete the publisher's short reporting form. CIC states that the form does not require a password.
3. Download `MachineLearningCSV.zip`, not the much larger PCAP collection or `GeneratedLabelledFlows.zip`.
4. Save the archive as `data/raw/cic-ids2017/MachineLearningCSV.zip`.
5. Confirm the archive identity before extraction. The original archive used for this project has:

   ```text
   bytes: 235102953
   md5: 4f83860afbf29cac8163854095bf6cf7
   sha256: c3f26274b36c837ccf28ffd2dbf4582941c30b3ee70a635c6e5b2f87c4727928
   ```

6. Extract without renaming or modifying the files:

   ```bash
   unzip data/raw/cic-ids2017/MachineLearningCSV.zip -d data/raw/cic-ids2017
   ```

The publisher form returned a server error on 2026-10-18. For reproducibility, the local archive was obtained from the public `bencorn/CICIDS2017` Hugging Face mirror pinned to revision `811c007f08d693a8a8b4226c197c138391806ce6`. Its content SHA-256 and the independently published original-archive MD5 both match the values above. The official publisher remains the authoritative source and citation.

## Integrity manifest

Generate the local manifest once, using the date the archive was retrieved:

```bash
make data-manifest RETRIEVED_AT=2026-10-18
```

This writes `data/raw/cic-ids2017/manifest.json`. It records every extracted CSV path, byte size, SHA-256, capture identity, source URL, and retrieval date. The manifest stays next to the ignored raw data so replacing a source file does not silently update the version-controlled project.

Do not regenerate the manifest to make a checksum failure disappear. Investigate the source archive first.

## Complete audit

Run the full audit with one command:

```bash
make audit-data
```

The command verifies the manifest before scanning rows and writes deterministic reports to:

- `reports/generated/data-audit.json`
- `reports/generated/data-audit.md`

The reports inventory source files, capture days, normalized columns, labels, class balance, missing and invalid numeric values, positive and negative infinity, exact duplicate rows, constant columns, duplicate source columns, and leakage-prone fields. Both reports are generated artifacts and are intentionally ignored by Git.

`make gate-2` runs the Phase 2 repository checks, synthetic-fixture tests, and the complete local audit. It exits nonzero when any capture file is missing, a checksum changes, an unknown label appears, or source schemas differ unexpectedly.

## Phase 3 treatment plan

- Replace positive and negative infinity with missing values before fitting.
- Deduplicate exact rows before assigning any split.
- Fit missing-value handling on training data only.
- Exclude direct identifiers and `source_port`; keep capture identity only as split provenance.
- Exclude `destination_port` from the default model and evaluate it only in the preregistered validation experiment.
- Remove constants and the repeated `fwd_header_length` column using training data only.
- Fail on an unrecognized source label instead of assigning it to another category.
- Resolve schema differences before preprocessing; never align columns by position.
