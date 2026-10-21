# Phase 10 performance and reproducibility report

- **Status:** PASS
- **Measured:** 2026-10-21T16:33:53Z
- **Commit tested:** `2c479678f14297599c6b5130d1a2226f80ed485d`
- **Reference environment:** macOS 26.2 (Darwin 25.2.0, arm64), Python
  3.12.14, uv 0.12.21, Node 25.2.1, npm 11.6.2, and Docker
  client/server 29.8.2.

## Method

`make performance` first required a clean tracked checkout, created a temporary
`git archive` of the tested commit, and built both images from that archive with
`docker compose build --no-cache --pull`. The archived checkout contained no local
`.env`; Compose used the committed `.env.example` and an explicit absolute path to the
trusted, read-only model artifact.

After one warmup request, the harness measured exactly five one-row requests and five
maximum-size 10,000-row requests. It also ran eight one-row requests through four
concurrent workers, sampled container memory, inspected image and cgroup metadata,
measured first-page assets and response sizes, then removed and recreated the stack
without rebuilding. Median is the middle ordered sample; nearest-rank p95 is the
slowest of five samples.

## Timing results

| Measurement | Samples (seconds) | Median | p95 | Budget | Result |
|---|---|---:|---:|---:|---|
| Clean no-cache build | one complete build | 25.737 | — | recorded | PASS |
| Initial readiness | one complete start | 12.128 | — | 30.000 | PASS |
| One-row inference | 0.029196, 0.026774, 0.025855, 0.026057, 0.028691 | 0.026774 | 0.029196 | 2.000 | PASS |
| 10,000-row inference | 0.905242, 0.383124, 0.460334, 0.465052, 0.508530 | 0.465052 | 0.905242 | 10.000 | PASS |
| Stop/start readiness | one complete restart | 11.114 | — | 30.000 | PASS |

The post-restart prediction and frontend fetch both succeeded. Eight requests at four
workers returned eight distinct request IDs and the exact row ID assigned to each
request, so the concurrency isolation check passed.

## Resource and size results

| Measurement | Observed | Budget or configured limit | Result |
|---|---:|---:|---|
| API peak memory | 228.60 MiB | 512 MiB benchmark budget; 768 MiB container limit | PASS |
| Frontend peak memory | 12.05 MiB | 128 MiB container limit | PASS |
| API image | 514.01 MiB | 600 MiB | PASS |
| Frontend image | 87.55 MiB | 100 MiB | PASS |
| First-page assets | 314,468 bytes (307.10 KiB) | 1 MiB | PASS |
| 10,000-row request CSV | 7,891,039 bytes | 10 MiB upload limit | PASS |
| 10,000-row response JSON | 2,400,399 bytes (2.29 MiB) | 16 MiB | PASS |
| One-row response JSON | 622 bytes | recorded | PASS |

The API container was inspected with 2 CPUs, 768 MiB memory, and 256 PIDs. The
frontend was inspected with 0.5 CPU, 128 MiB memory, and 128 PIDs. Both configured
users were non-root: `app` for the API and `101:101` for the frontend.

First-page assets were 607 bytes of HTML, 259,628 bytes of JavaScript, 27,645 bytes of
CSS, and 26,588 bytes for the locally packaged Jost font. No external runtime URL was
present in the entry HTML or CSS.

## Image and artifact identity

| Item | Identity |
|---|---|
| API image | `sha256:43c6c77d721e93c47a0321baadd4771dd229e1f7d912ff33362706ae46348704` |
| Frontend image | `sha256:975b43e6ee5fc038b213cfae2f06b7d0e2abd1b572ff4b515a753512b8494478` |
| Model version | `ids-rf-v1.0.0` |
| Model manifest | `dfa7678b89009aa03af89957dde958af20af6f969decdd295ba7209eaa6c3601` |
| Model files | 2,918,419 bytes, excluding the manifest |

Every model file size and SHA-256 in `manifest.json` was recomputed before the
benchmark. The automated artifact test also wrote the same trained bundle twice and
confirmed byte-identical files and manifests. Dependency installation remained locked
to `uv.lock` and `frontend/package-lock.json`; every Docker base used a tag plus an
immutable manifest digest.

## Interpretation

All declared Phase 10 budgets passed with no violation. Results characterize this
arm64 reference machine and the checked demo limits; they are not universal service-
level guarantees. The generated JSON and Markdown reports under
`reports/generated/performance/` were transient inputs to this committed record and
were removed after verification.
