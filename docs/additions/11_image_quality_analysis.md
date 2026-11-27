# 11 — Image Quality Analysis Addendum

**Status:** Implemented (1.0.0, 2026-11-24) — see Section 13 for the implementation note  
**Scope:** Additive specification for the existing Object Generation and Scene Reconstruction pipelines  
**Implementation mode:** Agent-driven, incremental changes  
**Related specifications:** `06_object_generation.md`, `07_scene_reconstruction.md`, `09_testing.md`

---

## 1. Purpose

Add a deterministic image-quality analysis stage that detects input photographs likely to reduce reconstruction quality and provides actionable diagnostics before expensive ML or photogrammetry processing starts.

This document specifies only new behavior. It does not redefine image decoding, file validation, source-image preservation, background removal, task orchestration, COLMAP, TripoSR, OpenMVS, storage, or result validation already specified elsewhere.

The analyzer must be advisory by default. It must not silently modify, discard, recompress, rotate, or replace source photographs.

## 2. Goals

1. Detect technically poor photographs before expensive processing.
2. Identify exact and near-duplicate photographs in scene datasets.
3. Produce per-image diagnostics with stable machine-readable codes.
4. Provide recommendations that explain how the input can be improved.
5. Preserve the existing pipeline behavior when analysis is disabled or unavailable.
6. Record enough diagnostic information to compare future algorithm changes.

## 3. Non-goals

The first increment must not:

- Predict whether COLMAP will successfully reconstruct a scene.
- Estimate scene coverage or camera trajectory from image quality metrics alone.
- Automatically remove near-duplicate images.
- Apply image enhancement, denoising, sharpening, super-resolution, exposure correction, or generative restoration.
- Introduce a single opaque quality score.
- Replace COLMAP feature extraction or matching.
- Change the TripoSR model input resolution or preprocessing algorithm.
- Add a new frontend workflow or public API endpoint unless the existing task/result contract is proven insufficient and a separate change is approved.

## 4. Integration boundaries

### 4.1. Scene Reconstruction

Integrate analysis after the existing dataset preparation has copied and decoded the task's immutable image snapshot, and before COLMAP feature extraction begins.

Relevant existing modules:

- `ml/scene_reconstruction/dataset.py` — prepared image metadata and task workspace.
- `ml/scene_reconstruction/preflight.py` — preflight orchestration.
- `ml/scene_reconstruction/pipeline.py` — pipeline stage ordering and diagnostics.
- `ml/scene_reconstruction/config.py` — validated pipeline configuration.
- `ml/scene_reconstruction/diagnostics.py` — persistent diagnostic structure.
- `ml/scene_reconstruction/tests/` — unit and pipeline tests.

Do not move or duplicate existing file decoding, SHA-256 exact-duplicate detection, image-count checks, or dimension validation.

### 4.2. Object Generation

Integrate a single-image analysis call into the existing image preparation stage, before TripoSR inference. The analysis must inspect the original decoded image, not a resized or background-removed intermediate.

Relevant existing modules:

- `ml/object_generation/preprocessing.py` — decoded image and preprocessing boundary.
- `ml/object_generation/pipeline.py` — stage orchestration and run manifest.
- `ml/object_generation/config.py` — validated object pipeline configuration.
- `ml/object_generation/tests/` — preprocessing and pipeline tests.

Do not alter the existing TripoSR preprocessing sequence as part of this increment.

### 4.3. Shared implementation

Create a small reusable package under `ml/`, for example:

```text
ml/
└── image_quality/
    ├── __init__.py
    ├── analyzer.py
    ├── metrics.py
    ├── duplicates.py
    ├── models.py
    └── tests/
```

The agent may adjust names to match repository conventions, but the shared analysis logic must not import either pipeline package. Pipeline-specific adapters may translate shared results into their existing diagnostics/manifest formats.

Avoid introducing a generic framework or plugin architecture for this first increment.

## 5. Analysis capabilities

### 5.1. Common per-image checks

Implement the following deterministic metrics:

| Check | Suggested method | Diagnostic purpose |
|---|---|---|
| Image dimensions | Existing decoded dimensions | Detect low-resolution inputs and extreme size differences |
| Blur / sharpness | Variance of Laplacian on a normalized grayscale thumbnail | Flag likely motion blur or out-of-focus images |
| Exposure | Luminance histogram and clipped dark/bright pixel ratios | Detect underexposure, overexposure and clipping |
| Contrast | Robust luminance percentile range or standard deviation | Detect images with insufficient tonal variation |
| Noise estimate | A documented high-frequency estimate on a normalized image | Flag severe noise without treating textured surfaces as noise automatically |
| Aspect ratio | Width-to-height ratio | Flag unusually extreme framing for user review |

Requirements:

- Use OpenCV only if it can be added without conflicting with the existing worker's pinned NumPy/Pillow/OpenCV dependencies. Otherwise implement the required metrics using already-compatible dependencies.
- Compute metrics on a bounded-size analysis copy to keep CPU and memory use predictable.
- Do not save the analysis copy as a replacement for the original.
- Record the metric algorithm/version and relevant thresholds in the report.
- A metric must be omitted, not fabricated, when it cannot be computed.

### 5.2. Scene-only near-duplicate detection

The existing SHA-256 check remains authoritative for exact byte duplicates.

Add perceptual near-duplicate detection as a separate diagnostic:

- Use a perceptual hash (pHash or an equivalent documented method) to generate candidate pairs.
- Use a second comparison, such as SSIM, only for candidate pairs if needed to reduce false positives.
- Return candidate pairs/clusters and similarity/distance values.
- Keep the comparison bounded for the configured maximum image count.
- Do not reject or automatically remove near-duplicates in this increment.
- Do not assume two similar images are useless: small camera movement may provide valid photogrammetric overlap.

The report must distinguish `EXACT_DUPLICATE` from `POSSIBLE_NEAR_DUPLICATE`.

### 5.3. Object-generation checks

For a single input image, run the common technical checks that are meaningful for one image:

- low resolution;
- blur / sharpness;
- exposure clipping and extreme luminance;
- insufficient contrast;
- extreme aspect ratio.

Do not run near-duplicate detection for the single-image workflow.

Do not infer object visibility, foreground correctness, or segmentation quality from the generic metrics. Those require a separately specified feature and must not be conflated with this analyzer.

## 6. Diagnostic model

Use explicit findings rather than a weighted total score.

Suggested immutable result types:

```python
@dataclass(frozen=True)
class ImageFinding:
    code: str
    severity: Literal["INFO", "WARNING", "ERROR"]
    message: str
    recommendation: str | None = None
    metric_name: str | None = None
    metric_value: float | int | str | None = None
    threshold: float | int | str | None = None

@dataclass(frozen=True)
class ImageQualityReport:
    image_id: str
    filename: str
    width: int
    height: int
    metrics: dict[str, float | int | str]
    findings: tuple[ImageFinding, ...]
    analyzer_version: str
```

The exact implementation may use Pydantic or dataclasses according to local conventions. Keep the serialized output JSON-compatible.

Initial stable finding codes:

- `LOW_RESOLUTION`
- `LIKELY_BLUR`
- `UNDEREXPOSED`
- `OVEREXPOSED`
- `HIGHLIGHT_CLIPPING`
- `SHADOW_CLIPPING`
- `LOW_CONTRAST`
- `HIGH_NOISE`
- `EXTREME_ASPECT_RATIO`
- `POSSIBLE_NEAR_DUPLICATE`

Do not add an `OVERALL_QUALITY_SCORE` finding.

Each finding must have a short user-facing explanation and a concrete recommendation. Avoid claiming that a finding guarantees reconstruction failure.

## 7. Thresholds and configuration

All thresholds must be configurable and validated. Do not hardcode thresholds in metric functions.

Add a configuration object for the analyzer with:

- `enabled`;
- maximum analysis dimension;
- minimum acceptable short-edge dimension;
- blur threshold;
- underexposure and overexposure thresholds;
- clipping ratio threshold;
- contrast threshold;
- noise threshold;
- aspect-ratio warning bounds;
- near-duplicate enable flag;
- perceptual-hash distance threshold;
- optional SSIM confirmation threshold.

The initial thresholds are provisional. The agent must document their units and default values, add tests for boundary behavior, and make it possible to tune them without changing metric code.

Do not copy a Laplacian-variance threshold from an unrelated image resolution or dataset. Normalize analysis dimensions and calibrate the default using representative project images. If no representative calibration set is available, choose conservative defaults and mark them provisional.

Configuration must be passed into the ML package by the existing worker/config adapter pattern. The shared analyzer must not read environment variables directly.

Add backend settings and environment-example entries only where the current configuration system requires them. Keep defaults backward-compatible: analysis may be enabled with warnings only, but it must not turn previously accepted images into hard failures by default.

## 8. Pipeline behavior

### 8.1. Scene pipeline

1. Run the existing dataset preparation and exact duplicate validation unchanged.
2. If quality analysis is enabled, analyze all prepared images.
3. Run scene-only near-duplicate candidate detection when enabled.
4. Attach reports to scene diagnostics and write a task-local JSON report under the existing workspace, e.g. `diagnostics/image_quality.json`.
5. Continue to COLMAP unless a pre-existing hard validation rule fails.
6. Keep quality warnings separate from fatal errors and from COLMAP reconstruction diagnostics.

### 8.2. Object pipeline

1. Decode the original image using the existing decoder.
2. Run the analyzer on the decoded original image.
3. Add the report to the existing run manifest and generated asset metadata where appropriate.
4. Continue the existing preprocessing and inference sequence unchanged.
5. Do not persist a second copy of the original image solely for analysis.

### 8.3. Failure handling

- An analyzer exception must not silently produce a clean report.
- When analysis is configured as advisory, log the failure, record `QUALITY_ANALYSIS_UNAVAILABLE`, and continue the existing generation pipeline.
- When analysis is explicitly configured as required for diagnostics, fail only the analysis stage with a stable internal error; do not mislabel it as an image-quality rejection.
- Never mark a photograph as invalid solely because a heuristic metric crosses a provisional threshold.
- Preserve cancellation and task heartbeat behavior. The analyzer must not introduce long uninterruptible work.

## 9. Persistence and privacy

- Store reports only in the task-specific workspace and existing task/result diagnostic metadata paths.
- Do not store full pixel arrays, thumbnails, or additional source-image copies in the report.
- Do not include absolute host paths in user-visible metadata.
- Preserve existing source-image bytes and EXIF metadata.
- Follow existing workspace cleanup and retention behavior; do not introduce a new long-term image retention policy.

## 10. Testing requirements

### 10.1. Unit tests

Add deterministic tests for:

- sharp and blurred synthetic images;
- dark, bright and clipped images;
- low-contrast images;
- high-noise images;
- extreme aspect ratios;
- images near every configured threshold;
- corrupt/unsupported inputs handled by existing validation rather than misreported as quality findings;
- metrics omitted when unavailable;
- stable finding codes and JSON serialization;
- analyzer disabled behavior;
- analyzer exception behavior.

For near-duplicate detection:

- exact duplicates remain handled by the existing SHA-256 path;
- resized/recompressed versions are candidates;
- different viewpoints of the same object are not automatically rejected;
- unrelated images are not grouped;
- pair count and runtime remain bounded at the configured maximum dataset size.

Avoid brittle tests that depend on exact floating-point metric values across different OpenCV/Pillow builds. Test ranges and finding behavior instead.

### 10.2. Integration tests

Add tests proving that:

- scene analysis runs after dataset preparation and before COLMAP;
- scene analysis findings are included in diagnostics;
- near-duplicate findings do not remove images or block COLMAP;
- object analysis runs before TripoSR inference;
- object analysis does not change the image passed to the existing preprocessing function;
- analysis failure in advisory mode does not break existing generation;
- disabling the analyzer preserves current pipeline behavior.

All tests must use synthetic or repository-owned fixtures. Do not download datasets during normal unit-test execution.

## 11. Acceptance criteria

The increment is complete when:

1. Both pipelines can invoke the shared analyzer without duplicating metric implementations.
2. Existing input validation and generation behavior remain unchanged by default.
3. Findings are deterministic for fixed inputs, configuration and analyzer version.
4. Scene near-duplicate detection reports candidates but does not delete or reject photographs.
5. Reports are JSON-serializable and stored only in task-scoped diagnostics.
6. Unit and integration tests cover all checks and failure modes listed above.
7. Existing object-generation and scene-reconstruction test suites continue to pass.
8. No aggregate quality score is introduced.
9. No new public endpoint or frontend redesign is introduced as part of this increment.
10. The implementation documentation records selected dependencies, default thresholds, calibration limitations and measured runtime on a representative dataset.

## 12. Agent execution instructions

Before editing:

1. Read `docs/AI_DEVELOPMENT_GUIDE.md`, `docs/HANDOFF.md`, `docs/specifications/06_object_generation.md`, `docs/specifications/07_scene_reconstruction.md`, and `docs/specifications/09_testing.md`.
2. Inspect the current implementations and tests listed in Section 4. Do not assume this addendum is more current than the code.
3. Confirm the dependency constraints of both ML worker images. Do not add a dependency to the backend API image unless it is required there.
4. Produce a short implementation plan identifying exact files to change and any schema/config migration implications.

During implementation:

- Make the smallest additive change possible.
- Do not rewrite existing dataset preparation or preprocessing.
- Do not change the TripoSR or COLMAP algorithms in this increment.
- Do not silently alter existing thresholds or failure semantics.
- Keep pipeline-specific integration thin and shared metric logic isolated.
- Add tests before broad integration.

After implementation:

1. Run the relevant unit tests for `ml/image_quality`, `ml/object_generation`, and `ml/scene_reconstruction`.
2. Run lint/type checks configured by the repository for the touched packages.
3. Run the repository's relevant CI checks where practical.
4. Report exact commands, pass/fail results, dependency changes, measured runtime and unresolved limitations.
5. Update this document only where implementation decisions differ, and add a concise implementation note to the existing handoff/roadmap rather than duplicating the full specification elsewhere.

Do not proceed to the next quality-improvement increment until this one is implemented, tested and reviewed.

---

## 13. Implementation note (1.0.0, 2026-11-24)

This section records the decisions taken while implementing Sections 1–12. It
supersedes nothing above; where a suggestion was adjusted, the adjustment and
its reason are stated here.

### 13.1. Package, dependencies and image layout

The shared package is `ml/image_quality/` with `analyzer.py`, `metrics.py`,
`duplicates.py`, `models.py`, `settings.py`, a `README.md`, a `pyproject.toml`
and `tests/`. It imports only NumPy and Pillow and never imports
`object_generation` or `scene_reconstruction`. The pipelines contain only thin
adapters that translate results into their existing diagnostics/manifest
formats.

**No dependency was added.** Both worker images already pin `numpy==2.3.5` and
`pillow==13.0.0`. A Python OpenCV binding is not installed in either image: the
scene image has the C++ COLMAP/OpenMVS OpenCV libraries only, and the object
image has no OpenCV at all. Adding `opencv-python` would have introduced a
second OpenCV/NumPy/FFmpeg family into both images for six cheap metrics, so the
metrics are implemented with NumPy/Pillow as Section 5.1 permits.

Both Dockerfiles copy the package to `/opt/image_quality` (the parent `/opt` is
already on `PYTHONPATH` in both workers), and the ML CI workflow runs its tests
in both worker images. The backend API image does not receive the package.

### 13.2. Integration points

**Scene reconstruction.** Analysis runs inside the existing `IMAGE_PREPARATION`
stage, after `prepare_dataset`/`check_dataset` and before COLMAP feature
extraction. No new `GenerationTask.stage` value was introduced: the persisted
stage list and the frontend stage labels are unchanged. The report is attached
to `ReconstructionDiagnostics.image_quality`, written to
`diagnostics/image_quality.json` in the task workspace, and exposed as result
metadata (`image_quality`, `image_quality_seconds`). Near-duplicate pairs and
clusters are reported as `POSSIBLE_NEAR_DUPLICATE`; no image is removed and
COLMAP still runs. `EXACT_DUPLICATE` is not emitted, because byte-identical
files are rejected earlier by the existing SHA-256 dataset check; the report
states the distinction explicitly under `duplicate_codes` and
`exact_duplicates`.

**Object generation.** The analyzer inspects the decoded original before
background removal, cropping or resizing. The report is added to `run.json` and
to the generated asset metadata under `image_quality`. The existing TripoSR
preprocessing sequence and the image passed to it are unchanged.

**Failure handling.** An advisory failure (the default) logs the exception and
records `QUALITY_ANALYSIS_UNAVAILABLE` in the diagnostics/manifest while the
pipeline continues. When `IMAGE_QUALITY_REQUIRED=true`, the analysis stage alone
fails with `QUALITY_ANALYSIS_FAILED`; this code is documented as an internal
analysis failure, never as an image-quality rejection. `SceneCancelled` and
pipeline errors are re-raised unchanged so cancellation and task timeouts are
not misclassified as analyzer failures. The scene adapter polls the pipeline
between images, so cancellation and heartbeats keep working during the bounded
loop.

**Configuration.** Thresholds are validated in `ImageQualityConfig` and again in
the backend `Settings`, passed to the workers through the existing
`build_config_from_settings` adapters, and documented in `.env.example` and the
Compose worker environments. The analyzer never reads the environment itself.
`IMAGE_QUALITY_SSIM_ENABLED` plus `IMAGE_QUALITY_SSIM_THRESHOLD` are used in the
backend because an empty environment value cannot express a nullable float
cleanly; the shared config still models `ssim_threshold: float | None`.

### 13.3. Defaults, calibration and limitations

The defaults are documented with units in `ml/image_quality/README.md`:
`min_short_edge=640 px`, `blur_threshold=100.0` (Laplacian variance on a 512 px
normalized copy), `underexposure=40`, `overexposure=215`, clip levels 5/250 with
a `0.15` clipped-pixel fraction, `contrast_threshold=35` (p95−p5), noise
`15.0` (Immerkær sigma), aspect bounds `0.2–5.0`, pHash distance `10` of 63 bits
and SSIM confirmation `0.92`.

The calibration set was the four repository object photographs in
`ml/object_generation/testdata/` and the eleven repository scene photographs in
`.proof/sceaux/`. Measured ranges on that set: Laplacian variance 597–5408 for
the object photographs and 828–1526 for the scene photographs; Immerkær noise
1.6–9.4; p95−p5 contrast 112–230; mean luminance 86–172. The defaults therefore
sit conservatively below or above the observed good-image range. The resolution
floor matches the existing scene dataset warning at 640 px.

Limitations are explicit: the calibration set is small and not a
consumer-camera corpus, thresholds are provisional, the noise estimator cannot
distinguish genuine fine texture from sensor noise, and pHash distances depend
on the resizing library (the analyzer version is recorded with every report).
All findings are `WARNING`s; no aggregate score exists and no photograph is
rejected because a heuristic crossed a threshold. A different camera,
resolution regime or subject class requires re-tuning through
`IMAGE_QUALITY_*`; no metric code needs to change.

### 13.4. Measured runtime

| Measurement | Result |
|---|---|
| Eleven Sceaux photographs (2832×2128), full per-image analysis plus pHash/SSIM candidate pass | 2.35 s total (~0.21 s/image) |
| Object photograph (2832×2128) | ~0.23 s |
| Object testdata photographs (480×360–1000×667) | ~0.03 s each |
| Bounded 100-image dataset (variants of the eleven scene photographs) | 21.3 s, 405 candidate pairs, 11 clusters; pair limit `100×99/2 = 4950` |

The 100-image probe held all decoded images in memory, so its ~2.0 GB peak RSS
is an upper bound of the probe, not of the pipeline: the scene adapter streams
one image at a time and retains only the ~64 KiB SSIM thumbnail per image
(~6.5 MiB for 100 images).

### 13.5. Verification executed

```text
docker run --rm -v "${PWD}/ml:/work/ml:ro" -w /work/ml/image_quality \
  -e PYTHONPATH=/work/ml:/work/ml/image_quality mogen-scene-worker:dev \
  python -m pytest -q -p no:cacheprovider            # 47 passed
docker run --rm -v "${PWD}/ml:/work/ml:ro" -w /work/ml/scene_reconstruction \
  -e PYTHONPATH=/work/ml:/app mogen-scene-worker:dev \
  python -m pytest -q -p no:cacheprovider            # 83 passed, 1 skipped (opt-in real reconstruction)
docker run --rm -v "${PWD}/ml:/work/ml:ro" -w /work/ml/object_generation \
  -e PYTHONPATH=/work/ml:/app:/opt/triposr mogen-object-worker:dev \
  python -m pytest -q -p no:cacheprovider            # 39 passed, 1 skipped (opt-in real model)
docker run --rm -v "${PWD}/ml/image_quality:/opt/image_quality:ro" -w /app \
  mogen-scene-worker:dev python -m pytest /opt/image_quality/tests -q  # CI-style: 47 passed
docker compose run --rm --no-deps -v "${PWD}/backend:/app" api pytest -q  # 526 passed
ruff check (image_quality, scene_reconstruction, changed object files)     # clean
```

Not executed in this session: rebuilding `mogen-object-worker:dev` and
`mogen-scene-worker:dev`. The existing images predate the `/opt/image_quality`
copy, so the stack must be rebuilt (`docker compose build object-worker
scene-worker`) before the live worker can import the new package. The real
TripoSR/COLMAP algorithms were not changed, so the opt-in real-model and real
reconstruction tests were not rerun as part of this increment.

One pre-existing lint finding remains outside the changed files: four untouched
`ml/object_generation/tests/*.py` modules report `I001` under the newer Ruff in
the worker image. They were left unchanged to keep this increment scoped.

### 13.6. Deviations from the suggested types

`ImageQualityReport` additionally records `unavailable_metrics` so an omitted
metric is visible rather than silent. `QualityAnalysisResult` records the
analyzer version, algorithms, thresholds, duplicate codes and near-duplicate
document at dataset level; per-image reports stay as specified. The object
worker passes the task identifier and original filename into the analyzer so
reports are attributable without exposing storage paths.

### 13.7. Rebuild and live verification (2026-11-25)

The two development worker images were rebuilt after the increment-11 code was
final, the stack was started, and every check that needs the images was rerun.

| Image | Image ID | Created | Size |
|---|---|---|---|
| `mogen-object-worker:dev` | `sha256:6382371a…` | 2026-11-24T20:53:20Z | 13.0 GB |
| `mogen-scene-worker:dev` | `sha256:20df133d…` | 2026-11-24T20:51:34Z | 11.1 GB |

- `import image_quality` reports analyzer version `1.0.0` in both images.
- `/opt/image_quality/tests`: **47 passed** in both images (JUnit: 47 tests, 0
  failures, 0 skips).
- `/opt/object_generation/tests`: **39 passed + 1 skipped** (40 collected).
- `/opt/scene_reconstruction/tests`: **82 passed + 1 skipped** (83 collected).
  Section 13.5 recorded "83 passed"; that figure was off by one. The Phase 10
  baseline was 75 passed + 1 skipped (76 collected), and this increment added
  seven net new test functions (eight definitions, one of which relocated
  `test_artifact_metadata_is_json_serialisable`). No test is missing and no
  behaviour is untested: the suite is green. The corrected count is used from
  here on.
- Backend: **526 passed**.
- Ruff is clean for every changed backend, scene and object file and for the
  whole `ml/image_quality` package. The four pre-existing `I001` findings in
  untouched `ml/object_generation/tests/*.py` modules remain unchanged.
- `alembic check` reported no schema drift; `pip check` found no broken
  requirements; `--verify-tools` reported COLMAP 4.2.1 and OpenMVS 2.4.0; all
  three workers answered `celery inspect ping`; the dispatcher and recovery
  heartbeat files were fresh; `cleanup_sessions_task`,
  `cleanup_storage_task` and `cleanup_scene_workspaces_task` were registered;
  all eleven services were healthy with `migration` and `model-init`
  `Exited (0)`.

Live tasks were created by a fresh user through the Vite proxy
(`http://localhost:5173`, so the CSRF origin matched):

- **OBJECT** task `65f55148-…` on project `92a31435-…`: `COMPLETED` in ~21 s
  (including a cold task start); result metadata contained
  `image_quality.status = "OK"` and
  `image_quality.report.analyzer_version = "1.0.0"`; findings were
  `LOW_RESOLUTION` (short edge 360 px, expected for the 480×360 fixture) and
  `SHADOW_CLIPPING` (`shadow_clipped_ratio = 0.2678`); the GLB was 1 528 660
  bytes. The photograph was not rejected and preprocessing/inference were
  unchanged.
- **SCENE** task `bd40768e-…` on project `1a289ea3-…`: `COMPLETED` in ~10 min;
  all **11/11** photographs were analysed, `unique_images = 11`,
  `image_quality.status = "OK"`,
  `image_quality.analyzer.version = "1.0.0"`, `near_duplicates` reported 0
  pairs and 0 clusters, and `image_quality_seconds = 3.193`; the GLB was
  1 466 476 bytes. No image was removed or rejected.
- **Calibration observations, recorded without changing any default:** the
  studio-backdrop object photograph legitimately triggers `SHADOW_CLIPPING`
  (a dark background), and Sceaux photographs `00007`–`00009` trigger
  `HIGHLIGHT_CLIPPING` (0.18–0.32, bright sky). Both are advisory `WARNING`s.
  The defaults in Section 13.3 stay as validated; no threshold was retuned from
  these anecdotes.

Opt-in real checks:

- Real TripoSR (`-m real_model`, `RUN_REAL_MODEL_TESTS=1`): **1 passed** in
  80.9 s.
- Real COLMAP/OpenMVS standalone on the eleven Sceaux photographs:
  `"status": "completed"`, **11/11 registered**, 8 016 sparse points, mean
  reprojection error 0.566879, GLB 941 152 bytes, and
  `diagnostics/image_quality.json` with status `OK`, 11 reports and 0
  near-duplicate pairs. The PowerShell wrapper reported exit code 1 because
  Docker writes stage progress to stderr, not because the run failed; the
  program printed its completed report and wrote both artefacts.

Rows and storage directories created by the live check were deleted using their
exact identifiers; the development database was otherwise untouched. The
development stack is left running for the next increment.
