# Browser end-to-end suite

Committed Playwright suite for the Phase 9 test matrix (roadmap 9.4, 9.5,
`TEST-AC-15`, `TEST-AC-20`). It drives the running application through its
public UI and HTTP interface; it never imports frontend internals.

## What it covers

| Spec | Workflows |
|---|---|
| `auth.spec.ts` | Registration, logout/session termination, login, wrong password (E2E-01..03) |
| `projects.spec.ts` | Project creation with an upload, dashboard listing, deletion, invalid content rejection (E2E-04..06, E2E-09) |
| `security.spec.ts` | Two-user isolation, missing/cross-session CSRF, invalid upload content, hostile filename neutralization, validation errors (9.5) |
| `model-viewer.spec.ts` | Result route protection and the "no result yet" state (E2E-12) |
| `object-generation.spec.ts` | Real TripoSR generation, live stages, viewer load, orbit/zoom/fit/reset, download and metadata match (E2E-07, E2E-13) |
| `scene-reconstruction.spec.ts` | Real COLMAP/OpenMVS reconstruction, viewer with embedded texture, download and metadata match (E2E-08, E2E-13) |
| `reliability.spec.ts` | Failed reconstruction and retry, deletion while processing (E2E-10, E2E-11) |

## Prerequisites

* The Compose stack is running (`docker compose -f compose.yaml -f compose.gpu.yaml up -d`).
* The base URL must be `http://localhost:5173` for the development stack. The
  API accepts that origin for CSRF-protected calls; `http://127.0.0.1:5173` is
  rejected by design. For the production HTTPS stack set
  `E2E_BASE_URL=https://localhost` and `E2E_IGNORE_HTTPS_ERRORS=true` (the local
  verification certificate is self-signed); for a real HTTPS deployment use the
  public origin and leave `E2E_IGNORE_HTTPS_ERRORS` unset.
* Browsers: locally the suite uses the installed Microsoft Edge
  (`E2E_BROWSER_CHANNEL=msedge` is the default). CI installs Chromium and sets
  `E2E_BROWSER_CHANNEL=chromium`.
* The real scene test needs the real Sceaux photographs. They are not committed
  (the dataset is ~34 MB). Point `E2E_SCENE_IMAGES` at a directory of
  overlapping photographs, or the test skips. The repository-relative default
  is `.proof/sceaux`.

## Commands

```bash
cd e2e
npm ci
npx playwright test --list                     # compile/type check without a browser
npx playwright test tests/auth.spec.ts tests/projects.spec.ts \
  tests/security.spec.ts tests/model-viewer.spec.ts
E2E_SCENE_IMAGES=../.proof/sceaux npx playwright test \
  tests/object-generation.spec.ts tests/scene-reconstruction.spec.ts
```

Run the suite against a stack with `AUTH_RATE_LIMIT_ENABLED=false`: the browser
suite registers more users from one address than the production limiter allows
in a minute. The limiter itself is covered by
`backend/tests/db/test_auth_rate_limit.py`, `backend/tests/unit/test_rate_limit.py`
and a recorded live probe in `docs/reviews/phase9_closeout.md`.

Screenshots, traces and the JSON report are written to `test-results/` and
`playwright-report/` (gitignored).
