# Five-minute demonstration script

This walkthrough uses the same containers, model artifact, and safe sample exercised by
the browser release gate.

## Before the recording

1. Start from a clean checkout with the trusted `ids-rf-v1.0.0` directory available.
2. Run `cp .env.example .env` and set `IDS_MODEL_HOST_DIR` only when the artifact is
   outside `models/ids-rf-v1/`.
3. Run `docker compose up --build --detach --wait`.
4. Open <http://localhost:8080> and confirm the page reports
   `Model ready: ids-rf-v1.0.0`.

## Talk track

1. **Set the boundary.** “This analyzes bounded CICFlowMeter feature batches. It does
   not capture packets, discover arbitrary attacks, or block traffic.”
2. **Run the known-safe demo.** Select **Review included sample**. Explain that its six
   feature vectors use invented row IDs and contain no addresses, ports, timestamps,
   source labels, or capture identifiers.
3. **Read the summary.** Confirm six valid rows, one benign row, five suspicious rows,
   four high-priority rows, and no validation error.
4. **Explain one result.** Find `demo-03` and open its details. Version
   `ids-rf-v1.0.0` assigns a `99.15%` malicious probability, a `92.13%` conditional
   `PORT_SCAN` family confidence, a combined displayed confidence of `91.35%`, and
   `HIGH` risk. This means the row crossed the frozen `0.015` malicious threshold and
   most resembled the model's port-scan training examples. It is not a causal
   explanation or proof that the source performed a scan.
5. **Triage.** Filter the verdict to **Suspicious** and point out that attack-family,
   risk, and confidence controls narrow the current view without rescoring the file.
6. **Export.** Choose **Export view**. The downloaded CSV contains the five visible
   suspicious rows plus request, model, prediction, confidence, risk, and warning
   fields. Spreadsheet-triggering cells are escaped.
7. **Close honestly.** Show the model version and state the main limitation:
   CIC-IDS2017 is a controlled 2017 lab dataset, `INFILTRATION` recall was `0.375` on
   only eight final-test examples, and `RARE_OTHER` had no final-test support.

## API alternative

The identical sample can be submitted without the UI:

```bash
curl --fail --silent \
  -F "file=@frontend/public/samples/ids-demo-mixed.csv;type=text/csv" \
  http://localhost:8000/api/v1/predictions/file | python3 -m json.tool
```

## Finish

Reset the page, then run `docker compose down --remove-orphans`. There is no upload
database or server-side result history to remove; stopping the stateless stack and
closing the browser discards the in-memory demo state. Run `make clean` to remove local
build and test output.
