# Phase 9 security scan report

- **Status:** PASS
- **Scan date:** 2026-10-20
- **Policy:** no unresolved critical or fixable high dependency/image vulnerability;
  no detected credential in Git history or the working tree; runtime users must be
  non-root.
- **Exception review deadline:** 2026-11-20.

## Results

| Check | Pinned input/tool | Result |
|---|---|---|
| Python dependency audit | `uv.lock`, uv 0.12.21 | 43 packages; no known vulnerability or adverse project status |
| Frontend dependency audit | `frontend/package-lock.json`, npm 11.6.2 | 0 vulnerabilities |
| Git history secret scan | Gitleaks 8.30.1 | 20 commits / 1.08 MB; no leak |
| Working-tree secret scan | Gitleaks 8.30.1 | 1.54 MB; no leak |
| API image scan | Trivy 0.76.0, Debian 13.7 | 0 critical; 44 high occurrences covered by 8 explicit unfixed exceptions |
| Frontend image scan | Trivy 0.76.0, Alpine 3.24.2 | 0 critical/high |
| API runtime identity | `ids-demo-api:local` | configured user `app`; effective UID 100 |
| Frontend runtime identity | `ids-demo-frontend:local` | configured user `101:101`; effective UID 101 |

The exact lock audits and language-package portion of the image scan found no Python
or npm advisory. Trivy's API-image records are all operating-system package findings;
its report supplied no fixed version for any accepted occurrence. The policy evaluator
will fail if a fixed version appears, an exception expires, an unknown high advisory
appears, or any critical advisory appears.

## Time-bounded API base-image exceptions

| Advisory | Occurrences | Affected path | Decision and compensating control |
|---|---:|---|---|
| `CVE-2025-69720` | 4 | ncurses / `infocmp` CLI | CLI is never invoked; container is non-root, read-only, capability-free, and `no-new-privileges` |
| `CVE-2026-16742` | 2 | systemd libraries / `systemd-homed` | service is not started or exposed; the image runs only Uvicorn as non-root |
| `CVE-2026-54369` | 1 | libacl privileged pathname operations | no privileged ACL workflow or writable host path is present |
| `CVE-2026-76642` | 9 | util-linux privileged mount post-hooks | mount helpers are not invoked; all capabilities are dropped |
| `CVE-2026-78408` | 9 | util-linux `nsenter` cgroup operation | no host namespace access; non-root and capability-free |
| `CVE-2026-78409` | 9 | util-linux mount subdirectory resolution | mount operations are absent; root filesystem is read-only |
| `CVE-2026-78410` | 9 | util-linux restricted bind-mount hooks | mount operations are absent; model mount is read-only |
| `CVE-2026-9538` | 1 | Perl `Archive::Tar` | Perl is not invoked; archive/model uploads are rejected and CSV/JSON bodies are bounded |

Debian currently marks several of these stable-release issues as minor, postponed, or
without a DSA. The exceptions are nevertheless narrow and temporary. They are encoded
in [`configs/security-exceptions.json`](../../../configs/security-exceptions.json),
owned by the project maintainer, and expire on 2026-11-20. Rerunning `make security`
after a base refresh or advisory database change is mandatory; the gate prefers a fixed
base package over renewing an exception.

Authoritative advisory references used for the review include the Debian tracker for
[`CVE-2025-69720`](https://security-tracker.debian.org/tracker/CVE-2025-69720),
[`CVE-2026-54369`](https://security-tracker.debian.org/tracker/CVE-2026-54369),
[`CVE-2026-76642`](https://security-tracker.debian.org/tracker/CVE-2026-76642), and
[`CVE-2026-9538`](https://security-tracker.debian.org/tracker/CVE-2026-9538).

## Scan isolation and cleanup

Trivy receives `docker save` archives rather than the Docker socket. Gitleaks receives
the repository read-only and runs without network access; its output is always
redacted. Temporary image archives and JSON reports live under `mktemp -d` and are
removed by an exit trap. The advisory database cache lives only in ignored `.cache/`
and is removed by `make clean` after the checkpoint.
