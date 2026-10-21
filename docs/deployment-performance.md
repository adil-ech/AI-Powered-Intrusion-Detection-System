# Deployment, performance, and reproducibility

Phase 10 treats the application as a reproducible single-host demo deployment. The
containers are production builds, but the product still requires an authenticated,
TLS-terminating, rate-limiting gateway before exposure to untrusted networks.

## Reproducible inputs

- Python and npm dependencies install from `uv.lock` and `frontend/package-lock.json`
  with frozen/clean install commands.
- Every Docker base is pinned by both a readable release tag and a multi-platform
  manifest digest. Renovating a base means updating the digest, rerunning Gate 9, then
  rerunning Gate 10; a tag-only change is not accepted.
- The production Dockerfiles use separate build and runtime stages. The API runtime
  contains the locked virtual environment and application source, not uv or the test
  suite. The frontend runtime contains only Nginx configuration and built static files.
- Jost's Latin WOFF2 file is packaged under the SIL Open Font License at
  `frontend/public/fonts/`, so a running page has no third-party asset dependency. The
  reviewed font SHA-256 is
  `235d8f8964bfdf105fc0c3e4c77b5e70f31bee1dad611d59318b5f2a5cb64d90`.

The trained artifact remains intentionally outside Git. It is an integrity-checked
deployment input rather than source code. Produce it with `make finalize-model`, or
obtain the exact six-file `ids-rf-v1.0.0` directory through a trusted channel, verify
its `manifest.json`, and set `IDS_MODEL_HOST_DIR` to that directory. Compose mounts the
directory read-only at the documented in-container path.

## Configuration and resource envelope

Copy the complete example configuration before starting the stack:

```bash
cp .env.example .env
docker compose up --build --detach --wait
```

The checked defaults are:

| Service | CPU | Memory | PIDs | Temporary storage |
|---|---:|---:|---:|---:|
| API | 2 CPUs | 768 MiB | 256 | 16 MiB |
| Frontend | 0.5 CPU | 128 MiB | 128 | 16 MiB |

`API_CPU_LIMIT`, `API_MEMORY_LIMIT`, `FRONTEND_CPU_LIMIT`, and
`FRONTEND_MEMORY_LIMIT` can be adjusted for a named host. Request row, column, byte,
and processing-time limits remain independently configurable through the documented
`IDS_*` variables. Raising an application limit without re-running the benchmark does
not create a supported configuration.

Both services have readiness-aware health checks, run as non-root, use read-only root
filesystems, drop every Linux capability, set `no-new-privileges`, and receive bounded
temporary filesystems. Compose is the reference deployment topology, not a high-
availability design.

## Performance gate

Run from a clean committed checkout containing no untracked source files:

```bash
make performance
```

The command creates a temporary `git archive` of `HEAD`, builds both images there with
`--no-cache --pull`, uses only the archived `.env.example`, and points the clean checkout
at the explicit trusted model directory. It then:

1. measures health/readiness startup;
2. warms the model once;
3. runs exactly five one-row requests;
4. runs exactly five 10,000-row requests;
5. issues eight isolated requests through four concurrent workers;
6. samples container memory and records configured cgroup limits;
7. records request/response, first-page asset, artifact, and image sizes; and
8. removes, recreates, and smoke-tests the stack without rebuilding.

Median uses the middle of the five ordered samples. With five repetitions, nearest-rank
p95 is the slowest sample. The generated JSON and Markdown reports are written under
ignored `reports/generated/performance/`; the checkpoint summary records the accepted
measurements.

## Budgets

| Measurement | Gate budget |
|---|---:|
| Initial readiness | at most 30 seconds |
| Restart readiness | at most 30 seconds |
| One-row inference p95 | at most 2 seconds |
| 10,000-row inference p95 | at most 10 seconds |
| Measured API memory | below 512 MiB and below the 768 MiB container limit |
| First-page HTML, CSS, JavaScript, and font | at most 1 MiB uncompressed |
| 10,000-row JSON response | at most 16 MiB |
| API image | at most 600 MiB |
| Frontend image | at most 100 MiB |

These are demo budgets for the reference machine recorded in the Phase 10 checkpoint,
not universal latency guarantees. Any budget revision requires measured evidence and a
workflow update before Gate 10 is rerun.

## Full checkpoint

```bash
make gate-10
```

Gate 10 reruns Gate 9 because container packaging changes can invalidate the prior
security scan. It then performs the clean-checkout build and all performance,
concurrency, resource, restart, and reproducibility checks. Generated build and test
outputs can be removed with `make clean`.
