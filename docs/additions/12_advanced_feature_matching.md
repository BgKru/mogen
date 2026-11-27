# 12 — Advanced Feature Matching Specification

## 1. Purpose and Scope

Introduce optional learned local-feature extraction and matching for scene reconstruction, with **ALIKED + LightGlue** as the first neural backend. Preserve the current COLMAP SIFT workflow as the default and fallback.

This specification changes only the feature extraction/matching portion of the existing scene pipeline. Sparse reconstruction, model selection, image undistortion, OpenMVS, export, task lifecycle, and Stage 1 image-quality analysis remain governed by the existing implementation and specifications (`07_scene_reconstruction.md` and `11_image_quality_analysis.md`).

Goals:

- Improve correspondence quality on difficult images (repetitive patterns, low texture, viewpoint and illumination changes) where learned features may outperform SIFT.
- Allow controlled selection and benchmarking of feature/matcher profiles.
- Feed verified correspondences into the existing COLMAP sparse reconstruction without changing downstream formats or interfaces.
- Keep SIFT + COLMAP as the stable production baseline.

Out of scope: changing image-quality scoring, image enhancement, camera models, mapper algorithms, OpenMVS, object generation, or automatic replacement of SIFT based on unvalidated heuristics.

## 2. Existing Components to Modify

The repository already implements the following; extend rather than duplicate them:

| Existing file | Required modification |
|---|---|
| `ml/scene_reconstruction/config.py` | Extend `MATCHING_STRATEGIES` and `SceneConfig`; validate and serialize feature/matcher profile settings. |
| `ml/scene_reconstruction/colmap_runner.py` | Keep native COLMAP command builders; add no neural logic here unless a small shared interface is required. The current extraction command is SIFT-specific. |
| `ml/scene_reconstruction/pipeline.py` | Dispatch feature extraction/matching through the selected backend; preserve current stage reporting, cancellation, checkpoints, and downstream COLMAP mapper flow. |
| `ml/scene_reconstruction/diagnostics.py` | Record selected backend/profile, dependency/model versions, feature and match statistics, fallback reason, and stage timings. |
| `ml/scene_reconstruction/preflight.py` | Validate neural runtime/model availability only when a neural backend is selected; do not make it a requirement for SIFT mode. |
| `backend/app/core/config.py` | Add validated settings for backend/profile and resource limits, mapped into `SceneConfig`. |
| `.env.example`, `.env.production.example` | Document new settings and safe defaults. |
| `ml/scene_reconstruction/requirements.txt` | Add a separately pinned, compatible neural-feature dependency set, or a dedicated optional requirements file if dependency conflicts require it. |
| `ml/scene_reconstruction/Dockerfile` | Install neural dependencies and model assets only in the scene worker image; preserve the existing pinned COLMAP/OpenMVS build. |
| `ml/scene_reconstruction/standalone.py` | Expose equivalent CLI selection/options for reproducible local benchmarks. |
| `ml/scene_reconstruction/tests/` | Add backend, database interoperability, dispatch, fallback, configuration, and benchmark-metric tests. |

Before editing, inspect current versions and runtime behavior in the repository. Do not assume current upstream package APIs are compatible with the pinned COLMAP build.

## 3. New Components

Create the smallest useful abstraction inside `ml/scene_reconstruction/`:

| Proposed file | Responsibility |
|---|---|
| `feature_matching.py` | Backend protocol/factory and orchestration-level result contract. |
| `neural_features.py` | ALIKED feature extraction and LightGlue matching adapter, including HLoc integration if selected. |
| `feature_profiles.py` | Validated profile definitions and profile-to-model parameters; avoid a general plugin framework. |

The implementation agent may adjust these names to match repository conventions, but must not create duplicate runners or move existing COLMAP orchestration unnecessarily.

### 3.1 Backend contract

Define a typed interface with operations equivalent to:

- `extract_features(images_dir, database_path, work_dir, config, callbacks) -> FeatureExtractionResult`
- `match_features(database_path, images_dir, work_dir, config, callbacks) -> FeatureMatchingResult`
- `verify_runtime(config) -> RuntimeInfo`

Results must expose backend/profile identifiers and measurable counts. Exceptions must map to the existing scene reconstruction error model. The contract must not expose raw tensors outside the neural adapter.

Implement at least:

- `COLMAP_SIFT`: current `ColmapRunner` commands, unchanged behavior.
- `ALIKED_LIGHTGLUE`: learned feature extraction and matching, then import verified features/matches into a COLMAP-compatible database.

Keep extraction and matching as distinct pipeline stages so existing progress reporting, timeouts, and diagnostics remain meaningful.

## 4. Architecture and Data Flow

### 4.1 Neural path

```text
Prepared images (existing dataset stage)
        |
        v
Selected feature backend
        |
        +-- COLMAP_SIFT ----------------> COLMAP feature_extractor
        |                                  |
        |                                  v
        |                            COLMAP matcher
        |
        +-- ALIKED_LIGHTGLUE ----------> ALIKED feature extraction
                                           |
                                           v
                                      Pair selection
                                           |
                                           v
                                      LightGlue matching
                                           |
                                           v
                                 Geometric verification
                                           |
                                           v
                          Import features + verified matches
                              into COLMAP database
                                           |
                                           v
                                Existing COLMAP mapper
                                           |
                                           v
                              Existing downstream pipeline
```

### 4.2 COLMAP database interoperability

The existing pipeline expects a COLMAP database at `paths["colmap"] / "database.db"`; `read_database_stats()` reads its image, keypoint, match, and two-view-geometry tables. The mapper consumes this database directly.

The neural adapter MUST produce a database accepted by the exact COLMAP 4.2.1 runtime in the worker image. Prefer a maintained HLoc/pycolmap integration that imports ALIKED features and LightGlue matches and performs COLMAP-compatible geometric verification. Do not implement a partial COLMAP SQLite schema by hand and do not assume raw LightGlue matches are equivalent to verified two-view geometries.

Implementation requirements:

1. Confirm the chosen HLoc/pycolmap versions support the installed COLMAP database schema and binary/runtime combination.
2. Register exactly the prepared image names and camera metadata expected by the existing `images/` directory and COLMAP database.
3. Import keypoints/descriptors with the correct feature dimensions and supported dtype/layout.
4. Import tentative matches, then run a supported geometric verification step (e.g. calibrated/uncalibrated two-view estimation) that populates COLMAP's verified geometry records.
5. Ensure the final database is readable by `read_database_stats()` and accepted by `colmap mapper`.
6. Keep database creation task-local. Build into a temporary database and atomically replace `database.db` only after validation; never leave a half-imported database eligible for checkpoint reuse.
7. Do not run COLMAP `feature_extractor` or native matcher after neural features have been imported; doing so would mix incompatible feature sets.

If HLoc cannot reliably interoperate with the pinned COLMAP 4.2.1 build, the agent must stop and report the incompatibility with a minimal reproduction. Do not silently write a custom database adapter without tests against the actual binary.

### 4.3 Pair selection

Support the existing `EXHAUSTIVE` and `SEQUENTIAL` concepts for neural matching, and add a configurable overlap-aware option only if implemented using a tested pair generator. For sequential matching, preserve image ordering and configurable temporal/window overlap. For exhaustive matching, enforce a configurable pair-count/resource limit before inference.

Pair generation must be deterministic for a fixed dataset and configuration. Avoid matching every possible pair for large image sets when the configured strategy does not require it.

## 5. Implementation Requirements

### 5.1 ALIKED + LightGlue

- Use ALIKED as the local feature extractor and LightGlue as the learned matcher.
- Pin compatible package versions and model checkpoints; record exact versions/revision identifiers in diagnostics.
- Use inference mode (`no_grad`/inference mode) and disable training functionality.
- Support configurable maximum keypoints and confidence/matching thresholds within validated bounds.
- Keep keypoint coordinates in the original image coordinate system expected by the COLMAP import layer. If images are resized for inference, store and apply the exact scale transform before import.
- Preserve per-image feature ordering and pair/image identity consistently.
- Perform geometric verification before mapper execution. Reject malformed, non-finite, out-of-bounds, or insufficient correspondences.
- Avoid persisting full descriptor tensors in diagnostics or API metadata.

### 5.2 Alternative configurations

Provide a limited, explicit profile set rather than arbitrary combinations of untested models:

| Profile | Extractor | Matcher | Purpose |
|---|---|---|---|
| `sift_default` | COLMAP SIFT | COLMAP exhaustive/sequential | Existing baseline and fallback. |
| `aliked_lightglue` | ALIKED | LightGlue | Primary learned configuration. |
| `aliked_lightglue_fast` | ALIKED with reduced keypoint budget | LightGlue | Lower latency/VRAM option. |

The fast profile must remain the same model family with a reduced feature budget; do not claim it is a separately trained model. Additional extractors/matchers may be added only after benchmark evidence and compatibility tests.

### 5.3 Matching strategy and fallback

- `COLMAP_SIFT` remains the default for existing deployments and configurations.
- Neural mode is explicitly opt-in until acceptance benchmarks pass.
- Fallback to SIFT may occur only when configured (`fallback_to_sift=true`) and before mapper execution.
- On fallback, discard the incomplete neural database and regenerate a clean SIFT database from scratch.
- Record fallback reason and actual backend used. Never report a neural run as successful if SIFT fallback produced the result.
- Do not fallback on invalid input datasets or deterministic configuration errors.

### 5.4 Checkpoint invalidation

Current `_sparse_stages()` reuses a database based on image/keypoint counts and verified-pair connectivity. This is insufficient when the feature backend or profile changes.

Extend checkpoint validation so feature extraction and matching checkpoints are reusable only when a manifest matches all relevant inputs:

- ordered image identity/content fingerprint (reuse the existing dataset fingerprint if available; otherwise add a deterministic hash manifest without duplicating Stage 1 analysis);
- backend and profile;
- extractor/matcher model versions and checkpoint identifiers;
- keypoint budget and matching thresholds;
- pair-generation strategy and its parameters;
- relevant preprocessing/resizing settings;
- COLMAP database schema/runtime version and geometric-verification settings.

If any value differs, invalidate both feature extraction and matching outputs and rebuild the database. Do not invalidate unrelated later outputs unless the existing pipeline's dependency rules require it. Never reuse neural features as SIFT features or vice versa.

## 6. Configuration

Add validated settings to `SceneConfig` and backend settings. Exact names may follow repository conventions, but the following semantics are required:

| Setting | Suggested default | Description |
|---|---:|---|
| `scene_feature_backend` | `COLMAP_SIFT` | `COLMAP_SIFT` or `ALIKED_LIGHTGLUE`. |
| `scene_feature_profile` | `sift_default` | `sift_default`, `aliked_lightglue`, or `aliked_lightglue_fast`. |
| `scene_feature_fallback_to_sift` | `true` | Allow explicit fallback from neural mode. |
| `scene_feature_max_keypoints` | `2048` | Neural maximum keypoints per image; tune by benchmark. |
| `scene_feature_image_max_size` | `1600` | Neural inference resize limit; 0 may mean no extra resize only if explicitly supported. |
| `scene_feature_pair_strategy` | `EXHAUSTIVE` | `EXHAUSTIVE` or `SEQUENTIAL` initially. |
| `scene_feature_sequential_overlap` | `5` | Number of neighboring images to pair for sequential mode. |
| `scene_feature_min_matches` | `30` | Minimum tentative/verified match threshold; define separate thresholds if needed. |
| `scene_feature_match_threshold` | profile-defined | LightGlue confidence threshold, validated to the supported range. |
| `scene_feature_device` | `auto` | `auto`, `cuda`, or `cpu`; explicit CUDA must fail clearly if unavailable. |
| `scene_feature_max_vram_mb` | `9000` | Soft neural-stage VRAM budget on the 12 GB RTX 3060; reserve memory for runtime overhead. |

The implementation must document the final parameter names and defaults in `.env.example`. Do not change the current SIFT feature-count or native COLMAP matching defaults.

`SceneConfig.as_manifest()` must include all settings that affect feature/match outputs, excluding secrets and machine-specific transient values.

## 7. API and Integration Requirements

- No public API change is required for the initial implementation. Select the backend through worker configuration.
- Preserve existing generation request/response schemas and task stage identifiers (`FEATURE_EXTRACTION`, `FEATURE_MATCHING`).
- Preserve the COLMAP sparse model output consumed by `reconstruction_selector.py` and `image_undistorter_command()`.
- Add selected backend/profile and compact match metrics to result diagnostics only; do not expose absolute paths, command lines, descriptors, or raw model internals.
- If a future per-task user-selectable profile is introduced, it requires a separate API contract and validation change; do not add it as part of this specification.

## 8. GPU/CPU Resource Management

Target hardware includes an RTX 3060 with 12 GB VRAM. This is a constraint, not proof that every ALIKED/LightGlue configuration fits.

- Load ALIKED and LightGlue lazily, only for neural mode.
- Run extraction and matching sequentially; do not keep both models resident if the implementation can safely unload/reload between stages.
- Use FP16/mixed precision only where supported and validated; retain FP32 fallback for unsupported operations or numerical instability.
- Provide CPU inference fallback when `device=auto`; CPU mode may be slow and must honor stage/task timeouts.
- Check available CUDA memory before model loading and before large batches. Reduce batch size or process images/pairs sequentially when necessary.
- Use bounded batches and configurable keypoint limits. Never load all image tensors or all pair tensors into GPU memory at once.
- Release tensors, model references, and cached allocations after each stage; call CUDA cache cleanup where appropriate, without treating it as a substitute for bounded allocation.
- Avoid concurrent neural scene tasks on one 12 GB GPU unless explicit GPU admission control exists. Respect current worker concurrency and deployment resource controls; do not introduce a second independent scheduler.
- Record device, precision mode, peak allocated/reserved VRAM when available, and CPU fallback status.
- Fail with a stable resource error or perform configured SIFT fallback on OOM. Do not retry the same OOM configuration indefinitely.

## 9. Error Handling

Add stable internal error codes where existing error categories cannot distinguish these cases:

- neural runtime/dependency unavailable;
- model checkpoint unavailable or checksum mismatch;
- CUDA unavailable when explicitly required;
- feature extraction failure;
- matching failure;
- geometric verification failure / insufficient verified pairs;
- COLMAP database import or compatibility failure;
- neural-stage resource exhaustion.

Requirements:

- Keep user-facing error messages generic and safe, consistent with existing exception handling.
- Preserve detailed stack traces and subprocess logs only in worker logs/task diagnostics, subject to existing retention rules.
- On any neural-stage failure, leave no partially valid database or checkpoint manifest.
- If fallback is enabled and the failure is recoverable, rebuild cleanly with SIFT and record the fallback.
- Cancellation and heartbeat polling must remain responsive during image and pair batches.
- Timeouts must use the existing per-stage timeout mechanism; add a separate neural timeout only if the existing stage budget proves insufficient.

## 10. Testing Requirements

### 10.1 Unit tests

- Backend/profile validation and defaults preserve SIFT behavior.
- Factory dispatch selects the correct backend.
- Neural command/config mapping and deterministic pair generation.
- Image resize coordinate restoration and feature shape/dtype validation.
- Threshold validation and insufficient-match handling.
- Checkpoint manifest equality/mismatch, including backend/profile/model version changes.
- Fallback rebuilds a clean SIFT database and records the actual backend/reason.
- Cancellation, timeout, CPU fallback, CUDA unavailable, and OOM handling.
- Diagnostics omit descriptors, tensors, absolute paths, and sensitive runtime details.

### 10.2 COLMAP interoperability tests

Use the actual pinned COLMAP 4.2.1 worker binary in an integration test:

1. Prepare a small multi-view image fixture.
2. Run ALIKED extraction and LightGlue matching.
3. Import and geometrically verify matches into a fresh database.
4. Assert `read_database_stats()` reports all images, non-zero keypoints, matched pairs, verified pairs, and expected connectivity.
5. Run `colmap mapper` against the generated database.
6. Assert a valid sparse model is produced and can be inspected by the existing reconstruction selector.

A mocked SQLite database is not sufficient proof of interoperability.

### 10.3 Quality benchmark

Create a reproducible benchmark command or test marker; do not make a large real reconstruction part of the default unit test suite.

Compare at least:

- existing COLMAP SIFT + exhaustive;
- existing COLMAP SIFT + sequential;
- ALIKED + LightGlue exhaustive;
- ALIKED + LightGlue sequential;
- fast ALIKED + LightGlue profile.

Use identical prepared images, camera settings, mapper settings, and hardware. Include multiple scenes with different texture, viewpoint overlap, lighting, and repetitive patterns. Record dataset provenance and image count.

Metrics:

- extraction and matching duration;
- keypoints per image;
- tentative and verified pair counts;
- largest connected image component / registered image ratio;
- sparse point count and reprojection error where available;
- successful reconstruction rate;
- peak VRAM and peak system RAM;
- total sparse-stage duration.

Compare results against the SIFT baseline. A higher match count alone is not evidence of better reconstruction. Do not define universal quality thresholds before collecting baseline data; report per-scene results and justify acceptance thresholds from benchmark evidence.

## 11. Acceptance Criteria

- Existing SIFT mode produces the same command sequence and remains the default.
- Neural backend is selectable through validated configuration and is isolated from the FastAPI runtime.
- ALIKED + LightGlue creates a valid COLMAP database using a supported import/geometric-verification path.
- The pinned COLMAP binary successfully runs its mapper on the neural database.
- Existing sparse reconstruction selection and OpenMVS stages consume the result without interface changes.
- Checkpoints are invalidated whenever backend/profile/model/pairing parameters change.
- Configured fallback rebuilds a clean SIFT database and is explicitly visible in diagnostics.
- Neural inference respects bounded memory, cancellation, timeouts, and CPU/GPU selection.
- Unit tests and actual-binary interoperability tests pass.
- Benchmark report compares neural profiles with both existing SIFT matching strategies on identical datasets.
- Neural mode is not made the production default until benchmark evidence demonstrates a meaningful improvement without unacceptable resource or reliability regressions.

## 12. AI Agent Implementation Instructions

1. Read `07_scene_reconstruction.md`, `ml/scene_reconstruction/README.md`, `ml/scene_reconstruction/config.py`, `colmap_runner.py`, `pipeline.py`, `diagnostics.py`, `preflight.py`, the worker Dockerfile, and current tests before editing.
2. Preserve the current COLMAP SIFT implementation as a working baseline. Do not refactor unrelated reconstruction stages.
3. Verify current upstream HLoc, ALIKED, LightGlue, pycolmap, PyTorch, CUDA, and COLMAP compatibility before selecting pins. Record tested versions; do not guess compatible versions.
4. Implement and test COLMAP database interoperability early, before completing configuration or UI work. This is the primary technical risk.
5. Add the backend abstraction with the smallest practical surface and keep current stage callbacks/checkpoint semantics.
6. Implement ALIKED + LightGlue and at least the standard and reduced-keypoint profiles. Keep native SIFT unchanged.
7. Add backend-aware checkpoint manifests and safe database replacement.
8. Add resource controls, runtime preflight, stable errors, and optional SIFT fallback.
9. Extend diagnostics and standalone CLI without changing public API contracts.
10. Run existing scene unit tests, new neural unit tests, actual COLMAP interoperability tests, and benchmark runs. Do not claim quality improvement without comparative measurements.
11. Update `ml/scene_reconstruction/README.md` and configuration examples with only the new backend setup, model acquisition, licensing, and benchmark instructions.
12. Do not proceed to object-generation, mesh/texture enhancement, neural scene reconstruction, or any other roadmap stage as part of this task.

**Deliverable:** `12_advanced_feature_matching.md` plus implementation-ready findings/compatibility notes if a required dependency cannot be validated. Do not implement code during this documentation task.

---

## 13. Implementation note (post-MVP, 2026-11-25)

The session instruction required implementing this increment, so the final line
above was superseded by an explicit implementation request. The compatibility
study was completed first; the plan and acceptance criteria are in
[`12_implementation_plan.md`](12_implementation_plan.md) and the evidence is in
[`../reviews/increment12_closeout.md`](../reviews/increment12_closeout.md).

**Dependencies and interoperability.** The pinned COLMAP 4.2.1 runtime accepts
a database produced by pycolmap 4.2.1 (`Database.write_keypoints`,
`write_matches`, `pycolmap.verify_matches`). The adapter uses that public API
directly, which is the same path HLoc wraps; the HLoc package itself was not
added because it would bring `gdown`, `plotly`, `scipy` and `h5py` only to reach
the import. The interoperability test uses the actual binary, not a mocked
database.

**Pins:** torch 2.14.1 / torchvision 0.29.2 (CUDA 13 wheels),
kornia 0.9.2, kornia-rs 0.2.0, opencv-python 5.1.0.95, matplotlib 3.11.2
(declared by LightGlue), pycolmap 4.2.1, LightGlue commit
`5a650c444718caffc2669dc0094cde908f42dd73`. ALIKED-N16 and LightGlue checkpoints
are baked into `/opt/neural_models` and checksum-verified at build and before
each neural stage.

**Settings.** In addition to the Section 6 table, `scene_feature_max_pairs`
(default 20 000) bounds the deterministic pair list before inference, fulfilling
the resource-limit requirement. `SceneConfig.as_manifest()` records every
feature value.

**Behavioural notes.** SIFT remains the default and its commands are unchanged.
Neural checkpoints are gated by `colmap/feature_manifest.json`; any backend,
profile, model, parameter, pair, resize or runtime change invalidates extraction,
matching and their dependent sparse/dense/OpenMVS outputs. Fallback deletes the
neural database and rebuilds SIFT cleanly, recording the reason and actual
backend. Descriptors are kept in a task-local `features.npz` for matching and are
never imported into COLMAP or exposed in diagnostics. `COLMAP_SIFT` continues to
use the existing `matching_strategy` setting, while neural pair selection uses
`scene_feature_pair_strategy`.

**Benchmark outcome.** On the eleven Sceaux photographs all five variants
registered 11/11 images; neural matching produced fewer sparse points
(≈1.4k–2.8k versus ≈7.7k–8k) and no demonstrated quality improvement, and
exhaustive neural matching was slower. Neural mode is therefore not the
production default; the full table is in the close-out review.

**Verification.** Scene suite 117 passed + 2 skipped (119 collected), actual-binary
interoperability 1 passed, backend 541 passed, image-quality 47 passed, Ruff
clean for changed code, `pip check` clean, live GPU neural task completed with
`image_quality.status="OK"`, and a no-GPU fallback drill rebuilt SIFT and
completed. Details and limitations are in
[`../reviews/increment12_closeout.md`](../reviews/increment12_closeout.md).

