# 15 — Neural Scene Reconstruction Specification

## 1. Purpose and Scope

Add an optional neural scene-reconstruction path based on 3D Gaussian Splatting using Nerfstudio **Splatfacto**. Preserve the existing COLMAP + OpenMVS pipeline as the default mesh-reconstruction path.

The two representations serve different purposes:

- **Mesh (COLMAP + OpenMVS):** explicit geometry, UVs, materials, GLB export, downstream mesh editing.
- **Gaussian splat (Nerfstudio Splatfacto):** view-dependent radiance representation optimized for novel-view rendering; not a watertight mesh and not a drop-in GLB replacement.

Goals:

- Train a Splatfacto scene from the same prepared photographs and camera poses produced by the existing COLMAP stage.
- Reuse COLMAP sparse reconstruction and camera metadata where compatible; do not repeat feature extraction or pose estimation unnecessarily.
- Store, serve, and render a Gaussian-splat result as a distinct asset representation.
- Keep mesh reconstruction available independently and preserve existing result behavior for current projects.
- Provide optional mesh extraction only when supported by a selected representation/workflow; do not promise direct Splatfacto-to-mesh export in the initial implementation.

Out of scope: replacing COLMAP, changing Stage 2 feature matching, changing OpenMVS, adding object-generation models, changing Stage 4 mesh enhancement, or forcing all scene results into GLB.

## 2. Existing Components to Modify

The repository already has a complete scene mesh pipeline and a GLB-only result viewer. Extend the current task/result architecture without changing its existing mesh path.

| Existing file | Required modification |
|---|---|
| `ml/scene_reconstruction/config.py` | Add validated representation/method settings and a separate set of neural-stage limits; preserve current defaults. |
| `ml/scene_reconstruction/pipeline.py` | Add a representation-aware dispatcher after shared image preparation and COLMAP sparse reconstruction, or route to a separate neural pipeline before OpenMVS. Do not run OpenMVS stages for a splat-only result. |
| `ml/scene_reconstruction/dataset.py` | Expose a deterministic Nerfstudio data-preparation adapter using existing prepared images and COLMAP camera/model outputs; do not mutate originals. |
| `ml/scene_reconstruction/diagnostics.py` | Record method, model/config revision, training duration, iterations, Gaussian count, artifact size, device and peak VRAM/RAM. |
| `ml/scene_reconstruction/preflight.py` | Validate optional neural-worker availability, CUDA capability, model/runtime compatibility and writable cache/output paths only when splat mode is selected. |
| `ml/scene_reconstruction/README.md` | Document the optional neural worker, model setup, representation differences, export format, viewer requirements and benchmark procedure. |
| `backend/app/core/config.py` | Add representation selection and neural worker/resource settings; keep FastAPI free of Nerfstudio/PyTorch imports. |
| `backend/app/tasks/scene_pipeline.py` | Dispatch selected scene method through the existing worker lifecycle and artifact registration contract. |
| `backend/app/tasks/outbox_publisher.py` and `backend/app/tasks/celery_app.py` | If a separate queue is required for dependency/GPU isolation, route tasks deterministically based on the persisted algorithm/method selection. Do not allow incompatible workers to consume the same queue. |
| `backend/app/db/models/enums.py` and `backend/app/db/models/generation_result.py` | Add the new result format only with a database CHECK-constraint migration and backward-compatible API handling. |
| `backend/app/services/result_service.py` and result endpoints/schemas | Support a safe `.ply` artifact name, MIME type and authenticated download while retaining existing GLB behavior. |
| `frontend/src/features/model-viewer/hooks/useModelLoader.ts` | Dispatch loading by result format; retain the current GLTFLoader path unchanged for GLB. |
| `frontend/src/features/model-viewer/components/ModelViewer.tsx` and viewer lifecycle utilities | Add a Gaussian-splat rendering path and explicit GPU-resource disposal; do not treat a PLY splat as a triangle mesh. |
| `frontend/package.json` and viewer tests | Add a compatible, pinned splat-rendering dependency only after browser/build/license evaluation. |
| `backend/tests/`, `ml/scene_reconstruction/tests/`, `frontend/src/features/model-viewer/` | Add routing, result-format, worker, export, loading, rendering, cleanup and regression tests. |

Before editing, inspect the exact task-parameter creation, outbox routing, result-format CHECK constraint migration, result download path, viewer API and shared-volume topology. Adapt file locations to repository conventions; do not create duplicate result services or a second task lifecycle.

## 3. New Components

Keep neural-specific code isolated from the existing COLMAP/OpenMVS runtime.

| Proposed component | Responsibility |
|---|---|
| `ml/scene_reconstruction/neural_pipeline.py` | Orchestrate dataset conversion, Splatfacto training, checkpoint validation and export. |
| `ml/scene_reconstruction/nerfstudio_runner.py` | Run pinned Nerfstudio CLI/subprocess commands with timeout, cancellation, logs and output checks. |
| `ml/scene_reconstruction/splat_exporter.py` | Validate and atomically publish the exported Gaussian PLY plus compact metadata. |
| Dedicated neural worker image/environment | Pin Nerfstudio, PyTorch, CUDA extensions and gsplat independently from COLMAP/OpenMVS. |
| Frontend Gaussian-splat renderer adapter | Load the selected splat PLY, render it in the existing viewer shell and release GPU resources. |

Names may follow existing conventions. Do not add a general ML plugin framework. The neural worker may be a separate container/service or a dedicated image/queue, but must not force Nerfstudio dependencies into the FastAPI or current COLMAP/OpenMVS images.

## 4. Architecture and Data Flow

### 4.1 Shared preparation and method dispatch

```text
Uploaded photographs
        |
        v
Existing image preparation + Stage 1 quality analysis
        |
        v
Existing COLMAP feature matching + sparse reconstruction
        |
        v
Validated camera poses / intrinsics / sparse points
        |
        +-----------------------------+
        |                             |
        v                             v
COLMAP + OpenMVS mesh path      Nerfstudio data adapter
        |                             |
        v                             v
Existing dense/mesh stages      Splatfacto training
        |                             |
        v                             v
Existing GLB export             Gaussian PLY export
        |                             |
        v                             v
Existing GLB validation         PLY + metadata validation
        |                             |
        +--------------+--------------+
                       |
                       v
             Existing result registration
              with explicit asset format
```

The implementation may choose whether sparse reconstruction is shared by a single orchestration path or reused from a validated checkpoint. The neural path must consume the same prepared image identities and compatible camera coordinate conventions. It must not silently rerun COLMAP feature extraction/matching when valid outputs already exist.

### 4.2 Representation selection

Add a deployment-level setting initially; do not expose an unvalidated user-controlled algorithm selector in the public API.

- `mesh` selects the current COLMAP + OpenMVS pipeline and remains the default.
- `gaussian_splat` selects COLMAP sparse reconstruction plus Nerfstudio Splatfacto and Gaussian PLY output.

Persist the selected method in task parameters at task creation so retries, outbox routing and worker execution cannot disagree if environment configuration changes after enqueue. Existing tasks without this field must resolve to `mesh`.

If neural dependencies require a separate worker, add a dedicated queue and deterministic routing based on the persisted method. A worker configured for one method must reject tasks for the other method. Do not run a mixed set of incompatible workers against one queue.

### 4.3 Nerfstudio dataset conversion

- Convert the existing COLMAP sparse model and prepared images to the Nerfstudio input format using a pinned and tested `ns-process-data`/COLMAP import path.
- Prefer direct use of the validated COLMAP cameras and sparse points. Do not run an independent camera-pose estimator unless the existing sparse model is invalid and a separately approved recovery path exists.
- Ensure image filenames, camera intrinsics, distortion handling, image dimensions and pose transforms match the actual prepared images consumed by training.
- Validate coordinate handedness, camera-forward axis, world scale and transform direction with a small fixture before training.
- Do not apply image resizing/cropping a second time if the COLMAP dataset already contains undistorted/resized images. Camera intrinsics must be transformed consistently when a resize is unavoidable.
- Write the Nerfstudio dataset into the task-local workspace; never modify the source upload or shared COLMAP outputs.
- Preserve a manifest mapping source image identity to training image path and camera record.

### 4.4 Splatfacto training and export

- Use the `splatfacto` method as the initial implementation. Do not enable `splatfacto-big` on the 12 GB target by default.
- Invoke Nerfstudio through a controlled subprocess wrapper (`ns-train` or a pinned Python entry point); do not import its internal training classes into the existing pipeline until APIs are verified stable.
- Set explicit iteration, image scale, batch/cache, culling and checkpoint parameters. Record the effective resolved configuration, not only CLI arguments.
- Save checkpoints at configured intervals and support safe resume only when dataset fingerprint, camera metadata, Nerfstudio revision, gsplat version and full training configuration match.
- Export a Gaussian PLY from a completed checkpoint using the supported `ns-export gaussian-splat` command for the pinned version.
- Export to a temporary path, validate, compute SHA-256 and atomically move to the final task result path. A partial PLY must never be registered.
- Keep training checkpoints and intermediate renders in the task workspace; only the final PLY and compact metadata are registered as the user result. Retention follows the existing scene workspace policy.

### 4.5 Optional mesh extraction

Splatfacto Gaussian PLY is not a mesh. Do not pass it to the existing GLB validator, OpenMVS, mesh cleanup, or Three.js GLTFLoader.

The initial implementation must not promise direct Splatfacto mesh extraction. Nerfstudio's documented Splatfacto export is Gaussian PLY; its documented mesh export commands apply to supported NeRF methods and are not proof of a reliable Splatfacto-to-mesh conversion. If mesh output is required later, evaluate a separately validated depth-fusion or surface-reconstruction process with measurable geometry error and document it as a distinct conversion feature. Keep COLMAP + OpenMVS as the supported mesh-producing workflow.

## 5. Implementation Requirements

### 5.1 Nerfstudio / Splatfacto integration

- Pin an exact Nerfstudio release or commit, gsplat version, PyTorch build, CUDA runtime compatibility and all required compiled extensions.
- Verify the exact combination in the dedicated Linux worker image. Do not use floating `main`, unpinned pip dependencies or runtime compilation during a user task.
- Build/compile gsplat CUDA extensions during image build where feasible; otherwise run a startup smoke test and cache compiled artifacts in a versioned writable cache.
- Add a startup verification command that confirms the expected `ns-train`, `ns-export`, Splatfacto method registration, CUDA availability and gsplat kernel execution.
- Use the official Splatfacto implementation rather than reimplementing Gaussian training.
- Expose a small validated configuration surface: training iterations, image scale, maximum image dimension, checkpoint interval, Gaussian culling settings, export options and stage timeout.
- Keep model and dataset caches versioned and task-independent only where safe; task outputs remain isolated.

### 5.2 Input and camera validation

Before training, validate:

- COLMAP sparse model exists and passed the existing reconstruction validation.
- All selected images have valid camera records and corresponding files.
- At least the configured minimum number of registered images is met.
- Camera intrinsics are finite and consistent with image dimensions.
- Camera transforms are finite, non-degenerate and use the expected coordinate convention.
- Sparse point cloud contains a usable number of finite points for initialization.
- The dataset has sufficient overlap/registration coverage according to existing COLMAP diagnostics.

Reject unsupported camera models or distortion layouts unless the pinned Nerfstudio importer has explicit tested support. Do not silently reinterpret camera parameters.

### 5.3 Gaussian artifact contract

The initial user-facing artifact is a Gaussian PLY plus metadata. Define a versioned internal metadata schema containing:

- `representation`: `GAUSSIAN_SPLAT`;
- `method`: `NERFSTUDIO_SPLATFACTO`;
- Nerfstudio and gsplat versions/revisions;
- source dataset fingerprint;
- training configuration fingerprint and iteration count;
- Gaussian count and file size;
- coordinate transform / up-axis metadata if required by the selected viewer;
- export format and MIME type;
- training duration and available peak resource metrics.

Do not include absolute paths, raw camera/image data, credentials, full logs or model internals in public metadata.

Validate that the PLY is a supported Gaussian-splat PLY schema for the pinned exporter and chosen frontend renderer. A generic point-cloud PLY is not sufficient. Validate required properties, finite numeric values, plausible Gaussian count, non-zero file size and successful parsing with an independent test loader. Record the exact PLY schema/version; do not assume all Gaussian PLY dialects are interchangeable.

### 5.4 Frontend viewer integration

The current viewer uses `GLTFLoader` and assumes a triangle-mesh `Object3D`; it cannot render a Gaussian PLY as-is. Add explicit format dispatch based on `GenerationResultResponse.format` and/or a validated `metadata.representation` value.

- Preserve the current GLB loading, stats, camera controls and disposal behavior without regression.
- Add a Gaussian-splat renderer adapter using a maintained Three.js-compatible library selected after evaluating PLY dialect support, browser compatibility, license, bundle size and WebGL/WebGPU requirements.
- Do not choose a renderer solely because it supports generic PLY point clouds; it must support the actual Nerfstudio Gaussian PLY properties and rendering semantics.
- Load through the existing authenticated result-download client; do not expose storage paths or create public unauthenticated URLs.
- Provide loading, parse failure, unsupported format and WebGL/GPU capability states consistent with the existing viewer.
- Provide fit/reset and camera controls where supported. Do not show mesh triangle/vertex statistics for splats; show Gaussian count and artifact size instead.
- Dispose renderer resources, GPU buffers, textures, workers and object URLs on result change, route exit, failed load and component unmount.
- Handle large artifacts with bounded download/memory behavior. If the chosen renderer requires full-file buffering, set and validate a maximum supported artifact size.
- Keep splat-specific code lazy-loaded so ordinary GLB viewer bundles and routes do not pay the dependency cost.

### 5.5 Result storage and API compatibility

The current result schema and database constraint permit `GLB`, `OBJ` and `STL`; the current scene pipeline registers GLB and the viewer assumes GLB. Add a dedicated Gaussian format (suggested enum value `PLY`) only after all layers are updated.

- Add a forward-only Alembic migration to extend the `generation_results.format` CHECK constraint without invalidating existing rows.
- Keep existing `GLB` results and API response fields unchanged.
- Store the splat artifact with a `.ply` suffix and the correct MIME type (`application/octet-stream` unless the API's established MIME policy defines a more specific interoperable value).
- Ensure result filename generation, content disposition, download response, storage cleanup, result replacement and retention work with PLY.
- Include representation metadata in the response so the frontend selects the correct renderer.
- Do not return a PLY under `model/gltf-binary` or a `.glb` filename.
- Preserve transactional result registration and previous-result retention if the new neural pipeline fails.

## 6. Configuration

Add validated settings in backend configuration and map them into the scene worker configuration. Exact names may follow repository conventions; semantics are required.

| Setting | Suggested default | Description |
|---|---:|---|
| `SCENE_REPRESENTATION` | `mesh` | `mesh` or `gaussian_splat`; existing deployments remain mesh. |
| `SCENE_SPLAT_ENABLED` | `false` | Explicit opt-in capability gate. |
| `SCENE_SPLAT_WORKER_QUEUE` | `scene_gaussian_splat` | Dedicated queue when neural runtime is isolated. |
| `SCENE_SPLAT_MODEL` | `splatfacto` | Initial supported method; reject unsupported variants. |
| `SCENE_SPLAT_MAX_ITERATIONS` | `30000` | Starting value only; benchmark and expose a bounded range. |
| `SCENE_SPLAT_IMAGE_SCALE` | `1` | Explicit image downscale factor; validate camera transform consistency. |
| `SCENE_SPLAT_MAX_IMAGE_DIMENSION` | `1600` | Training image cap; tune against quality and VRAM. |
| `SCENE_SPLAT_CHECKPOINT_INTERVAL` | `5000` | Training checkpoint cadence. |
| `SCENE_SPLAT_MAX_VRAM_MB` | `9000` | Soft budget for a 12 GB card; enforce admission and bounded image scale. |
| `SCENE_SPLAT_DEVICE` | `cuda` | `cuda` or `cpu` only if CPU execution is explicitly supported and tested. |
| `SCENE_SPLAT_MAX_ARTIFACT_BYTES` | benchmark-derived | Reject artifacts exceeding viewer/storage limits. |
| `SCENE_SPLAT_TIMEOUT_SECONDS` | `14400` | Dedicated training budget bounded by task-level timeout. |

Include output-affecting settings and exact runtime/model versions in the checkpoint manifest. Do not include transient GPU free-memory values in the manifest. Neural mode remains disabled unless the worker image, model/runtime preflight and renderer capability are available.

## 7. API and Integration Requirements

- No new public generation endpoint is required. Reuse the existing scene task and result response, extending the result format safely.
- Persist method/representation in task parameters before publishing the outbox event.
- Route mesh and Gaussian tasks to compatible workers deterministically. A task retry must preserve its original representation regardless of later deployment configuration changes.
- Preserve existing task status, lease, heartbeat, cancellation and result-registration semantics.
- Add any new persistent stage identifiers only after checking stage storage/validation and frontend progress mapping. Do not overload `OPENMVS_*` stages for neural training.
- If the UI does not yet expose representation selection, keep the deployment setting internal and document the active mode in task/result metadata.
- Do not change object-generation task behavior.

## 8. GPU/CPU Resource Management

Target development hardware is an NVIDIA RTX 3060 with 12 GB VRAM. This is a constrained target, not a guarantee that every Splatfacto configuration fits.

- Start with standard `splatfacto`; do not enable `splatfacto-big` by default. Nerfstudio's method documentation lists approximately 6 GB for standard Splatfacto and approximately 12 GB for Splatfacto-big; treat these as upstream estimates, not MOGEN measurements.
- Use one neural scene task per 12 GB GPU. Do not overlap Splatfacto training with TripoSR, SF3D, Hunyuan3D, ALIKED/LightGlue or another CUDA-heavy workload on the same device without a shared admission controller.
- Keep Nerfstudio in a dedicated worker/process and isolate its PyTorch/gsplat dependencies from the COLMAP/OpenMVS image.
- Set explicit image scale, training iterations and maximum image dimensions. Reduce image scale before training when the memory preflight indicates insufficient headroom.
- Do not load all images as unbounded GPU tensors. Use the Splatfacto/Nerfstudio data manager and bounded image cache behavior supported by the pinned release.
- Record peak allocated/reserved CUDA memory, system RAM, device name, image scale and Gaussian count.
- Fail with a stable resource error on OOM; do not retry indefinitely with identical settings. Any automatic lower-resolution retry must be explicit, bounded, recorded and checkpoint-safe.
- CPU training is not an acceptance requirement and may be prohibitively slow. If offered, it must be explicitly configured and have a separate timeout; do not silently fall back from CUDA to CPU.
- Release model, dataset and CUDA resources after each task. Keep worker concurrency at one for a single 12 GB GPU.

## 9. Error Handling

Add stable internal error codes where existing categories do not distinguish these failures:

- neural worker disabled/unavailable;
- Nerfstudio/gsplat runtime or CUDA extension mismatch;
- unsupported COLMAP camera model or dataset conversion failure;
- invalid/missing camera poses or sparse initialization points;
- training timeout/cancellation;
- CUDA out-of-memory/resource exhaustion;
- checkpoint manifest mismatch/corruption;
- Gaussian export failure;
- unsupported or malformed Gaussian PLY schema;
- artifact exceeds configured size limit;
- result format/storage registration failure.

Requirements:

- Keep user-facing messages generic and consistent with existing error handling.
- Preserve sanitized subprocess logs and detailed tracebacks in worker diagnostics only.
- Do not register partial or unvalidated PLY files.
- On failure, preserve the project's previous current result using the existing transactional result service.
- Remove task-local partial exports on failure; retain diagnostics/checkpoints only under the existing workspace retention policy.
- Cancellation and heartbeat checks must remain responsive during dataset conversion, training checkpoints and export. If the training process cannot be interrupted immediately, terminate its process group using the existing runner's safe process-management pattern.

## 10. Testing Requirements

### 10.1 Unit tests (CPU, no training)

- `mesh` remains the default representation for existing tasks/configurations.
- Task parameters persist representation and retries do not change it after environment settings change.
- Outbox routing sends mesh and splat tasks to the correct queues; incompatible workers reject tasks.
- Dataset conversion preserves image identity, camera intrinsics, distortion, dimensions and coordinate transforms.
- Invalid camera models, missing poses, insufficient registered images and invalid sparse points fail before training.
- Checkpoint reuse requires exact dataset/runtime/config fingerprints.
- PLY parser validates the pinned Gaussian schema, required properties, finite values and size/count limits.
- Result format migration and API response preserve legacy GLB rows.
- MIME type, filename extension, authenticated download and cleanup work for PLY.
- Frontend format dispatch keeps GLB on GLTFLoader and PLY on the splat adapter.
- Viewer cleanup covers success, failed load, result switch, unmount and WebGL context loss.

### 10.2 Worker integration tests (opt-in, CUDA)

Use a small fixed multi-view dataset with a valid COLMAP sparse reconstruction.

1. Run the pinned Nerfstudio data conversion.
2. Train standard Splatfacto for a short smoke-test iteration count.
3. Save and reload a checkpoint using the same manifest.
4. Verify a changed dataset/config invalidates the checkpoint.
5. Export a Gaussian PLY using the pinned `ns-export` command.
6. Parse the output with an independent Gaussian-splat reader and validate all required properties.
7. Record training time, export time, Gaussian count, artifact size, peak VRAM and system RAM.
8. Cancel a training process and verify the worker recovers and no partial result is registered.

Do not make real GPU training part of ordinary unit CI.

### 10.3 Frontend integration tests

- Load a known small Gaussian PLY fixture exported by the pinned Nerfstudio version.
- Verify the selected renderer displays it and exposes splat-specific statistics.
- Verify GLB fixtures continue to load and retain all current viewer behavior.
- Verify unsupported PLY dialects produce a controlled error rather than a blank canvas.
- Verify GPU resources and object URLs are released after route changes/unmount.
- Run browser tests on the supported Chromium/WebGL configuration and document minimum browser/GPU requirements.

### 10.4 Quality and performance benchmark

Compare both representations on identical source image sets and the same validated COLMAP sparse model:

- COLMAP + OpenMVS textured mesh;
- Nerfstudio Splatfacto standard.

Include scenes with varied texture, lighting, camera overlap, reflective surfaces, thin structures and large spatial extent. Record dataset provenance and camera coverage.

Metrics:

- successful training/reconstruction rate;
- camera coverage and image registration ratio;
- training and total processing time;
- peak VRAM and system RAM;
- Gaussian count and PLY size;
- rendered quality at held-out camera views (PSNR, SSIM and LPIPS where reproducible);
- visual artifacts, floaters and temporal/view-dependent stability;
- mesh completeness/geometry metrics only for mesh output, not inferred from Gaussian count.

Use identical held-out views and rendering resolution. Do not compare mesh polygon count with Gaussian count as equivalent quality measures. Report the trade-offs; do not declare one representation universally superior.

## 11. Acceptance Criteria

- Existing COLMAP + OpenMVS remains the default and produces the same GLB contract.
- Neural reconstruction is opt-in and isolated from FastAPI and the existing COLMAP/OpenMVS dependency environment.
- Splatfacto consumes validated COLMAP cameras and sparse initialization without duplicating feature matching or camera estimation.
- Dataset conversion passes camera-coordinate and image-dimension integration tests.
- Standard Splatfacto trains and exports a valid Gaussian PLY on the target worker hardware under a documented configuration, or the feature remains explicitly marked unsupported for that hardware with measured blocker evidence.
- PLY schema, format, MIME type, storage and API metadata are correct; no PLY is mislabeled as GLB.
- The frontend renders the exported PLY through a dedicated splat renderer and releases GPU resources correctly.
- Existing GLB viewer tests and result APIs remain backward compatible.
- Task retries, checkpoints, cancellation, worker routing and previous-result preservation remain correct.
- Benchmarks compare mesh and splat outputs using representation-appropriate metrics.
- No automatic replacement of mesh reconstruction occurs; users/deployment configuration select the representation explicitly.

## 12. AI Agent Implementation Instructions

1. Read `07_scene_reconstruction.md`, `ml/scene_reconstruction/README.md`, `config.py`, `pipeline.py`, `dataset.py`, `diagnostics.py`, `preflight.py`, `backend/app/tasks/scene_pipeline.py`, `backend/app/tasks/outbox_publisher.py`, result storage/API code and the complete frontend model-viewer feature before editing.
2. Preserve COLMAP + OpenMVS as the regression baseline. Run existing scene, backend result, task lifecycle and frontend viewer tests before changes.
3. Verify the exact Nerfstudio, Splatfacto, gsplat, PyTorch and CUDA compatibility matrix. Pin tested versions and build a dedicated worker image; do not add Nerfstudio to the existing COLMAP/OpenMVS or FastAPI dependency sets by default.
4. Prove COLMAP-to-Nerfstudio dataset conversion and camera-coordinate correctness with a small fixture before implementing training orchestration.
5. Implement standard Splatfacto only. Keep `splatfacto-big` out of the 12 GB default profile.
6. Implement artifact export and independent Gaussian PLY validation before wiring result registration.
7. Extend result formats, database constraints, API downloads and storage naming atomically and backward-compatibly. Add migration tests for existing GLB records.
8. Add explicit task method persistence and deterministic worker/queue routing if separate worker isolation is used. Do not rely only on mutable environment variables after enqueue.
9. Implement a lazy-loaded frontend splat renderer only after confirming it supports the exact Nerfstudio PLY schema. Keep the existing GLB path untouched and add disposal tests.
10. Add bounded resource controls, cancellation, checkpoint manifests, diagnostics and stable errors.
11. Run CPU unit tests, opt-in GPU worker integration tests, browser viewer tests and representation-specific benchmarks. Record actual hardware measurements; do not claim RTX 3060 compatibility from upstream estimates alone.
12. Update only the relevant README, deployment and API documentation for the new optional representation, worker, PLY format and viewer requirements.
13. Do not implement an automatic Splatfacto-to-mesh converter or remove OpenMVS. Do not begin another roadmap stage. Stop after this stage and report the completed document and unresolved compatibility blockers.

## 13. References

- Nerfstudio repository and license: https://github.com/nerfstudio-project/nerfstudio
- Splatfacto method, memory profiles and Gaussian PLY export: https://docs.nerf.studio/nerfology/methods/splat.html
- Nerfstudio installation requirements: https://docs.nerf.studio/quickstart/installation.html
- Nerfstudio geometry export limitations and supported mesh workflows: https://docs.nerf.studio/quickstart/export_geometry.html

Verify current upstream documentation and exact dependency pins during implementation. Upstream memory figures are estimates and must not be represented as MOGEN benchmark results.
