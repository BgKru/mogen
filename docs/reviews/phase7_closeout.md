# Phase 7 Close-out — 3D Viewer and Result Management

**Verified:** 2026-11-09
**Scope:** roadmap Phase 7, tasks 7.1–7.7; milestone M7 (Visualization Ready)
**Outcome:** Complete at its roadmap scope. No Phase 8+ work was started.

---

## 1. Baseline confirmed before work

The Phase 6 baseline from `HANDOFF.md` Section 5 was re-run on the running
eleven-service GPU stack before any change:

| Check | Result |
|---|---|
| `docker compose ... ps -a` | Nine services healthy; `migration` and `model-init` `Exited (0)` |
| Cleanup/object/scene worker `celery inspect ping` | 3/3 `pong` |
| Dispatcher/recovery heartbeat files | Fresh epoch values |
| `GET /health/ready`, `/health/dependencies` | `ready`; database and Redis `ok` |
| Frontend and `/api` proxy | `200`; JSON `NOT_FOUND` 404 through the proxy |
| Object worker logs | `triposr_model_loaded`, `object_generation_pipeline_ready` |
| Scene worker logs / tools | `scene_pipeline_ready`; COLMAP 4.2.1 and OpenMVS 2.4.0 |
| Backend suite | **491 passed, 1 warning** (316 database/API, 167 unit, 8 API-shell) |
| Frontend suite | **94 passed** across 15 files |
| Scene ML suite | **74 passed, 1 skipped** (the opt-in real reconstruction) |
| Object ML suite | **32 passed, 1 skipped** (the opt-in real-model test) |
| `ruff check`, `ruff format --check`, `alembic check` | Clean, 109 files formatted, no drift |

No Phase 2–6 behaviour was re-implemented. The retained failed task
`379073b3-…` and its workspace `/data/work/scene/379073b3-…` were not touched.

---

## 2. Delivered

### 2.1 Architecture

A new independent feature module `frontend/src/features/model-viewer/` follows
`03_frontend_specification.md` Section 12:

```text
features/model-viewer/
├── api/resultApi.ts              current-result read + authorized GLB blob
├── components/
│   ├── ModelViewer.tsx           viewport state, toolbar, loading/error overlays
│   ├── ModelCanvas.tsx           React Three Fiber canvas, lighting, background
│   ├── ModelScene.tsx            centring, camera fit, OrbitControls, grid
│   ├── ModelInfoPanel.tsx        result metadata, preserved-result state, download
│   ├── ViewerToolbar.tsx         reset, fit, grid, background, fullscreen
│   ├── ViewerLoading.tsx
│   └── ViewerError.tsx
├── hooks/
│   ├── useCurrentResult.ts       TanStack Query over GET /projects/{id}/result
│   └── useModelLoader.ts         download → blob URL → GLTFLoader → disposal
├── types/viewer.types.ts
└── utils/
    ├── modelBounds.ts            bounding box, camera distance, clipping planes
    └── modelCleanup.ts           geometry/material/texture disposal and statistics
```

The result workspace is the new protected route `/projects/{id}/result`
(`ModelViewerPage`), linked from the project details header, the project card,
and the existing generation panel. No backend, outbox, reconstruction-pipeline
or result/download-contract change was made; the viewer consumes the existing
`GET /projects/{id}/result`, `GET /projects/{id}/download` and
`GET /projects/{id}/status` endpoints through the shared API client.

### 2.2 Pinned dependencies

Added exactly, and recorded in `frontend/package.json` / `package-lock.json`:

| Package | Version | Reason |
|---|---|---|
| `three` | `0.187.0` | Approved 3D engine |
| `@react-three/fiber` | `9.8.2` | Approved React integration; peer React `>=19 <19.4` matches React 19.3.1 |
| `@react-three/drei` | `10.7.9` | `OrbitControls`; peer Three `>=0.159`, R3F `^9` |

No other dependency was added or loosened.

### 2.3 Task-by-task evidence

| Task | Implementation | Evidence |
|---|---|---|
| **7.1 Three.js integration** | React Three Fiber `Canvas`, `GLTFLoader`, perspective camera, neutral hemisphere + two directional lights, dark/light background, responsive full-size viewport | Real Edge run rendered both assets: object canvas 778×690 at 1440×900; WebGL 2 context created; no page errors |
| **7.2 Model loading** | Authenticated `GET /projects/{id}/download` via the shared Axios client (`responseType: blob`), temporary `URL.createObjectURL` fed to `GLTFLoader.loadAsync`, URL revoked in `finally`; loading overlay; stable download/parse/empty/unsupported error codes; geometry/material/texture disposal on replace and unmount | Unit tests: load success, download failure, parse failure, empty geometry, retry, disabled state, unmount disposal, result-change disposal; real browser: object loaded in 1.86 s, medium scene in 1.82 s, large scene in 2.43 s |
| **7.3 Viewer controls** | Drei `OrbitControls` (rotate/zoom/pan, damping), reset, fit-to-view, grid toggle, background toggle, fullscreen toggle; camera near/far derived from model radius; model centred by offset without modifying the asset | Browser pixel-diff checks: rotate changed, zoom changed, reset delta 0.10 (object) / 0.41 (scene), fit kept the model visible, grid and background changes detected, fullscreen button present |
| **7.4 Model information** | Project name, generation type, status, source-image count, format, file size, creation date, meshes, vertices, polygons, materials and textures; live Three.js measurements take precedence over persisted metadata, with metadata fallback | Panel text captured for both assets (object: 1 mesh / 23 039 vertices / 45 983 polygons; scene: 1 mesh / 202 493 vertices / 297 813 polygons / 1 texture) |
| **7.5 Download** | Prominent authenticated GLB link (`href` to the existing download endpoint, browser download attribute); same link remains available in the generation panel | Download event in Edge: object 921 436 bytes, scene 16 124 872 bytes; both `glTF` magic and **SHA-256 equal to the stored file** |
| **7.6 Result management** | Current result read via `GET /result` (`RESULT_NOT_FOUND` → empty state, not an error); processing and failed-regeneration banners; previous successful result stays visible; no canvas before a valid result | Page tests: loaded result, no result explanation, processing-without-result, failed regeneration preserving the previous result, missing project, result read failure; result query invalidated when status reaches `COMPLETED` |
| **7.7 Performance** | Measured on a real TripoSR object, a medium reconstructed scene (the Phase 6 proof asset) and the 100-image / 16 MB COLMAP+OpenMVS scene; no speculative optimisation added | Object: 1.86 s to loaded, 45.6 fps. Medium scene: 1.82 s, 74.3 fps. Large scene: 2.43 s, 16.0 fps. All under headless **SwiftShader software WebGL**; no device-GPU browser run was possible in this environment |

### 2.4 Viewer tests (TEST-AC-11)

35 new viewer cases in 7 new test files plus 1 new details-page navigation case and 1 extended generation-panel assertion:

- `utils/modelBounds.test.ts` (4) — bounds, offset preservation, empty object, camera/clipping maths.
- `utils/modelCleanup.test.ts` (4) — real GLB fixture parse and statistics, invalid GLB rejection, geometry/material/texture disposal, null safety.
- `hooks/useModelLoader.test.ts` (8) — authorized load, blob URL revocation, download/parse/empty errors, retry, disabled state, unmount and result-change disposal.
- `components/ViewerToolbar.test.tsx` (3) — labelled actions, toggle state, disabled state.
- `components/ModelViewer.test.tsx` (5) — loaded canvas, loading, error + retry, grid/background toggles, fullscreen-safe behaviour.
- `components/ModelInfoPanel.test.tsx` (4) — metadata, live measurements, preserved result, processing state.
- `pages/ModelViewerPage/ModelViewerPage.test.tsx` (7) — all page states above.
- `ProjectDetailsPage.test.tsx` and `GenerationPanel.test.tsx` — viewer navigation links.

A committed, lightweight triangle GLB fixture (base64) is parsed with the same
`GLTFLoader` used by the application; no WebGL is required for the unit suite.

---

## 3. Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| **FE-AC-14 GLB Viewer** | Satisfied | Real object and scene GLBs load and render in Edge; unit suite parses a real GLB fixture |
| **FE-AC-15 Viewer Controls** | Satisfied | Rotate, zoom, pan, reset and fit implemented; rotate/zoom/reset/fit verified by pixel changes in the browser |
| **FE-AC-16 Model Download** | Satisfied | Authenticated download link; downloaded SHA-256 equals the stored result for both assets |
| **FE-AC-17 Resource Cleanup** | Satisfied | Disposal tests for unmount and result change; blob URL revoked after parsing |
| **FE-AC-19 Code Quality** | Satisfied | lint, typecheck, format check and production build all clean |
| **FE-AC-04 API Integration** | Satisfied | Result metadata, status and GLB bytes all use the shared authenticated client / same-origin proxy |
| **UI-AC-09 Result Viewer** | Satisfied | Dedicated result workspace with the model as the primary element; both modes |
| **UI-AC-10 Viewer Controls** | Satisfied | Toolbar with reset, fit, grid, background and fullscreen; all labelled |
| **UI-AC-11 Download** | Satisfied | Prominent download button on the result page |
| **UI-AC-12 Responsive Layout** | Partially verified | Viewer uses a desktop/tablet grid and full-height viewport; no dedicated tablet browser measurement was executed |
| **UI-AC-13 Consistent Design** | Satisfied | Existing dark tokens, typography, badges, buttons and spacing reused |
| **UI-AC-14 Error Handling** | Satisfied | Download/parse/empty errors are readable Russian messages with retry; invalid GLB verified in the browser |
| **API-AC-13 Current result independent of latest task** | Satisfied | Viewer keeps and displays the current result after a failed regeneration (page test) |
| **API-AC-14 Download valid GLB** | Satisfied | `glTF` magic, exact size and SHA-256 match for both assets |
| **API-AC-16 No storage paths** | Satisfied | Viewer requests only `/result` and `/download`; no key or path is constructed or displayed |
| **INF-AC-02 Image Build** | Satisfied | `mogen-frontend:dev` rebuilt with the new pinned dependencies |
| **INF-AC-07 Frontend Startup** | Satisfied | Frontend `200`; `/api` proxy returns the backend JSON 404 |
| **INF-AC-15 Health Checks** | Satisfied | Nine services healthy; `migration`/`model-init` exited 0 |
| **TEST-AC-10 Frontend Tests** | Satisfied | 130 passed across 22 files |
| **TEST-AC-11 Viewer Tests** | Satisfied | 35 viewer unit cases with a real GLB fixture plus the real-browser proof |
| **SCENE-AC-22 Browser Compatibility** | **Closed** | The 16 MB COLMAP/OpenMVS scene (202 493 vertices, 297 813 triangles, embedded texture) loaded and was inspected in the application's Three.js viewer in Edge, with texture present and controls working |
| **M7 Visualization Ready** | Achieved | Both TripoSR objects and COLMAP/OpenMVS scenes load in the application viewer |

---

## 4. Verification executed

| Command | Result |
|---|---|
| `docker compose -f compose.yaml -f compose.gpu.yaml ps -a` | Nine healthy; `migration`/`model-init` `Exited (0)` |
| worker pings and heartbeat files | 3/3 pong; fresh epochs |
| `docker compose run --rm --no-deps api pytest` | **491 passed, 1 warning** in 125.78 s |
| `... api ruff check .` | All checks passed |
| `... api ruff format --check .` | 109 files already formatted |
| `... api alembic check` | No new upgrade operations |
| `docker run --rm mogen-object-worker:dev python -m pytest /opt/object_generation/tests -q` | 32 passed, 1 skipped |
| `docker run --rm mogen-scene-worker:dev python -m pytest /opt/scene_reconstruction/tests -q` | 74 passed, 1 skipped |
| `docker run --rm mogen-frontend:dev npm run lint` | Clean |
| `docker run --rm mogen-frontend:dev npm run typecheck` | Clean |
| `docker run --rm mogen-frontend:dev npm run format:check` | All files use Prettier style |
| `docker run --rm mogen-frontend:dev npm run test:run` | **130 passed** across 22 files |
| `docker run --rm mogen-frontend:dev npm run build` | Built; ~1.54 MB JS (436 kB gzip), Vite chunk-size warning |
| Edge + Playwright Core real-browser proof | Object, medium scene and large scene: loaded, controls, download SHA match; invalid GLB error state |
| `curl /health/ready`, `/health/dependencies`, frontend and proxy | Ready; database/Redis ok; 200/200; JSON 404 |

### Browser proof artefacts (out-of-tree, `.proof/` is gitignored)

- `.proof/viewer/object-verify.json`, `scene-medium-verify.json`, `scene-large-verify.json` — full metrics.
- `.proof/viewer/object-*.png`, `scene-medium-*.png`, `scene-large-*.png` — initial, rotated, zoomed, reset, fitted and light-background screenshots.
- `.proof/viewer/*-download.glb` — downloaded assets used for the SHA comparison.

Object: `load 1860 ms`, `45.6 fps`, 23 039 vertices / 45 983 triangles,
vertex colours, 7.30 % non-background pixels, 13 621 colours.
Medium scene: `load 1822 ms`, `74.3 fps`, 16 539 vertices / 28 991 triangles,
1 embedded texture, 3.46 % non-background pixels, 1 168 colours.
Large scene: `load 2426 ms`, `16.0 fps`, 202 493 vertices / 297 813 triangles,
1 embedded texture, 6.68 % non-background pixels, 4 118 colours.
All downloads matched the stored SHA-256 exactly.

---

## 5. Files

**Created**

- `frontend/src/features/model-viewer/**` (module above, 7 test files and the GLB fixture).
- `frontend/src/pages/ModelViewerPage/ModelViewerPage.tsx` and its test.
- `docs/reviews/phase7_closeout.md` (this file).

**Modified**

- `frontend/package.json`, `frontend/package-lock.json` — three pinned dependencies.
- `frontend/src/app/router/AppRouter.tsx` — result route.
- `frontend/src/pages/ProjectDetailsPage/ProjectDetailsPage.tsx` (+ test) — viewer link.
- `frontend/src/features/generation/components/GenerationPanel.tsx` (+ test) — viewer link.
- `frontend/src/features/projects/components/ProjectCard.tsx` — dashboard viewer link.
- `frontend/src/shared/api/queryKeys.ts` — result query key.
- `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` — state and next-phase handoff.
- `.proof/` proof scripts and evidence (gitignored, not deliverables).

No backend, database, outbox, worker or reconstruction-pipeline file changed.

---

## 6. Limitations and known issues

1. **New object generation could not be re-run during this phase.** A live OBJECT
   smoke task hung in `MODEL_GENERATION` while the host GPU was pinned at 100 %
   with 10.6 GB allocated and no CUDA compute process visible; the task lease
   and heartbeat stalled. The test project was deleted through the API, the
   worker was restarted, and `triposr_model_loaded` /
   `object_generation_pipeline_ready` were re-verified. This is a host/GPU
   environment condition outside Phase 7, not a viewer defect; it is reported so
   the event is not mistaken for a passing generation run.
2. **Viewer acceptance used byte-identical real assets.** Because of (1), the
   browser proof served copies of the retained real Phase 5 object result and
   the real Phase 6 scene result through isolated test projects and the existing
   authenticated API; the copied and downloaded SHA-256 values match the stored
   originals. All test rows and files were removed afterwards.
3. **Performance was measured under software WebGL.** Headless Edge used
   SwiftShader; 45.6 fps (object), 74.3 fps (medium scene) and 16.0 fps (large
   scene) are software-renderer floors, not device-GPU expectations. No
   optimisation was justified by these measurements.
4. **Bundle size.** Three.js raises the production bundle to ~1.54 MB (436 kB
   gzip); Vite warns about the chunk size. Route-level code splitting is
   deferred and not required for Phase 7 correctness.
5. **Fullscreen and tablet layout** were not measured in a real display session;
   the control is implemented and exposed, and the responsive grid is in place.
6. **Playwright is not a committed CI suite.** The Phase 7 real-browser proof is
   an out-of-tree verification script; `TEST-AC-19` (CI) remains open as before.
7. **Only the current result is exposed by the API.** "Previous result
   preservation" is verified as "the current successful result survives a failed
   regeneration"; no historical-result browsing exists, matching the contract.

---

## 7. Next

Phase 8 (reliability, security and optimization) per
`10_development_roadmap.md`; do not reopen Phase 7. The viewer is the starting
point for any later visual polish.
