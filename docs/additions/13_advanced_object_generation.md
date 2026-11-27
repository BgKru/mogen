# 13 — Advanced Object Generation

## 1. Purpose and Scope

Extend the existing single-image object-generation pipeline with alternative generators while preserving TripoSR as the default and fully supported baseline.

This specification adds:

- Stable Fast 3D (SF3D) as the preferred additional generator for the current 12 GB GPU target.
- Hunyuan3D as an optional, separately isolated integration, enabled only after hardware and license checks.
- A small generator contract and configuration-based selection.
- Model-specific preprocessing, loading, inference, output normalization, and benchmarking.

This specification does not redesign the task lifecycle, storage, public API, image-quality analysis, mesh/texture post-processing, or GLB validation. Reuse `06_object_generation.md`, the existing worker lifecycle, and the later mesh/texture specification (`14_mesh_texture_enhancement.md`). Do not implement scene reconstruction here.

Official references:

- TripoSR: https://github.com/VAST-AI-Research/TripoSR
- Stable Fast 3D: https://github.com/Stability-AI/stable-fast-3d
- SF3D model card: https://huggingface.co/stabilityai/stable-fast-3d
- Hunyuan3D-2.1: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
- Hunyuan3D-2.1 license: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE

Pin exact source commits, model revisions, and weight checksums during implementation. Do not use moving branches or download weights during task execution.

## 2. Existing Components to Modify

The following paths were verified in the repository. Extend them rather than creating a parallel task system.

| Existing path | Required change |
|---|---|
| `ml/object_generation/config.py` | Add generator selection and validated model-specific settings without changing existing TripoSR defaults. |
| `ml/object_generation/pipeline.py` | Resolve the configured generator, call the common contract, and record model identity and timings in `run.json` and result metadata. Keep the existing pipeline stages and callbacks. |
| `ml/object_generation/model_loader.py` | Keep TripoSR loading intact. Introduce or delegate to model-specific loaders; do not force SF3D/Hunyuan weights into the TripoSR cache. |
| `ml/object_generation/generator.py` | Preserve `TripoSRGenerator`; adapt it to the shared contract or provide a thin adapter. Do not replace its inference behavior. |
| `ml/object_generation/preprocessing.py` | Expose reusable decode/preprocessing primitives and add model-specific preparation only where required. Preserve current TripoSR behavior exactly. |
| `ml/object_generation/mesh_processor.py` | Extend validation only as needed to accept normalized outputs from all generators. Do not add mesh enhancement algorithms here. |
| `ml/object_generation/exporter.py` | Accept normalized mesh/material output and export valid GLB without stripping supported materials or textures. Preserve the current vertex-color path. |
| `ml/object_generation/exceptions.py` | Add stable, generator-neutral error codes and model-specific error mapping. |
| `backend/app/core/config.py` | Add validated environment-backed settings for generator selection, model paths/revisions, and optional adapters. Keep FastAPI free of ML imports. |
| `backend/app/tasks/object_pipeline.py` | Register the selected generator pipeline at worker startup; preserve `TaskContext`, cancellation, heartbeat, artifact registration, and cleanup behavior. |
| `ml/object_generation/Dockerfile` | Keep the existing TripoSR image reproducible. Add isolated model-specific build targets/images only when dependency compatibility is demonstrated. |
| `compose.yaml`, `compose.gpu.yaml` | Add opt-in worker/model-init services or profiles for alternative generators. Do not make additional workers start by default. |
| `.env.example`, `.env.production.example` | Document the new settings and safe defaults. |
| `ml/object_generation/tests/` | Add contract, adapter, configuration, output-normalization, and integration tests. |

Existing tests and behavior in `ml/object_generation/tests/` are regression requirements. Do not weaken or delete them to accommodate new generators.

## 3. New Components

Create only the components needed to isolate model-specific behavior. Exact names may be adjusted to match repository conventions, but responsibilities must remain separate.

| Proposed path | Responsibility |
|---|---|
| `ml/object_generation/generator_base.py` | Shared generator protocol and normalized generation result types. |
| `ml/object_generation/generator_factory.py` | Validate and instantiate the configured generator; reject unknown or unavailable names. |
| `ml/object_generation/sf3d/` | SF3D adapter, loader, model-specific preprocessing, dependency metadata, and tests. |
| `ml/object_generation/hunyuan3d/` | Optional Hunyuan3D adapter, loader, preprocessing, output conversion, and gated tests. |
| `ml/object_generation/normalization.py` | Convert generator-specific outputs into the common mesh/material representation accepted by the current exporter and validator. |
| `ml/object_generation/benchmarks/` | Reproducible benchmark runner and result schema; no production request path. |

Do not create a generic plugin framework, model marketplace, or public model-management API. A small factory with an explicit allowlist is sufficient.

## 4. Architecture and Data Flow

### 4.1. Generator contract

Define a typed contract equivalent to:

```python
class ObjectGenerator(Protocol):
    name: str
    revision: str

    def load(self, config: ObjectGenerationConfig) -> None: ...
    def generate(self, image: PreparedImage, *, started_at: float) -> GeneratorResult: ...
    def unload(self) -> None: ...
```

The exact `PreparedImage` type must reflect the existing preprocessing result. Avoid passing raw paths or accessing task storage from a model adapter.

`GeneratorResult` must contain:

- A mesh or a normalized scene/mesh object suitable for GLB export.
- Optional material and texture assets produced by the model.
- Model name and pinned revision.
- Inference and model-specific postprocessing durations.
- Peak CUDA allocated/reserved memory when available.
- Model-specific diagnostics in a JSON-serializable dictionary.

Adapters must not write to permanent storage, update database rows, report Celery progress, or manage task cancellation. Those remain responsibilities of the existing pipeline and worker adapter.

### 4.2. Selection and lifecycle

- `OBJECT_GENERATOR=triposr` remains the default.
- Supported values are an explicit allowlist: `triposr`, `sf3d`, and `hunyuan3d` only when its adapter is installed and enabled.
- Select one generator when the worker process starts. Do not switch model weights per task in a shared GPU process.
- Load the selected model once during worker bootstrap and fail readiness if the configured model cannot be loaded or verified.
- The existing `object_generation` queue, task type, task state transitions, and result registration remain unchanged for the default deployment.
- Alternative generators must not be silently substituted after a task has started. If a configured generator fails, return a stable task error; fallback to TripoSR is allowed only when explicitly enabled and before inference begins. Record the fallback reason and actual model used.
- Keep `TripoSRGenerator` as a first-class adapter and preserve existing model cache and checksum verification.

### 4.3. Processing flow

```text
Existing Celery object task
        |
        v
Existing image retrieval and task-scoped work directory
        |
        v
Shared image decode and validated source image
        |
        v
Selected generator's preprocessing adapter
        |
        v
Selected generator (TripoSR / SF3D / Hunyuan3D)
        |
        v
Output normalization (mesh + supported material/texture data)
        |
        v
Existing mesh validation and GLB export
        |
        v
Existing final GLB validation, storage, and result registration
```

The existing four persisted stages (`IMAGE_PREPARATION`, `MODEL_GENERATION`, `MODEL_EXPORT`, `RESULT_VALIDATION`) must remain stable. Add detailed substage timings to `run.json` and metadata instead of changing persisted stage enums.

## 5. Implementation Requirements

### 5.1. Stable Fast 3D adapter

Integrate the official Stability-AI SF3D implementation as an alternative single-image generator.

Requirements:

1. Pin the upstream repository commit and Hugging Face model revision. Verify downloaded files using a generated manifest with SHA-256 checksums.
2. Use the upstream model API (`SF3D.from_pretrained`, `run_image`) through a thin adapter. Do not copy the upstream model implementation into MOGEN unless a documented compatibility patch is unavoidable.
3. Convert the current preprocessed image to the input type expected by SF3D. Avoid applying background removal or foreground resizing twice. Support an adapter option that either consumes the shared prepared RGBA image or runs the model's own preprocessing, never both.
4. Configure texture baking resolution explicitly. The upstream default is 1024; start with 1024 on the 12 GB target and make it configurable.
5. Start with `remesh=none`. Expose triangle/quad remeshing only as optional model-level settings after measuring CPU time, vertex count, and output quality. Do not conflate this with Stage 4 mesh enhancement.
6. Preserve SF3D's UVs, material parameters, albedo texture, and any supported material maps during normalization and GLB export. Do not flatten textured output to vertex colors.
7. Validate the produced GLB through the existing `validate_glb` path and verify in the existing Three.js viewer.
8. Record the actual texture resolution, remesh mode, target vertex count, and whether model-side background removal was used.

SF3D is the recommended first alternative for the RTX 3060 12 GB environment. The upstream README reports approximately 6 GB VRAM for a single image under its default settings; treat this as an upstream estimate, not a MOGEN measurement. Verify peak allocated and reserved memory on the actual worker image before enabling it by default. SF3D requires access to gated model weights and its Stability AI Community License must be reviewed before distribution or hosted commercial use. Preserve required attribution and notices.

### 5.2. Hunyuan3D adapter (optional / gated)

Implement Hunyuan3D only as an isolated, opt-in adapter. Prefer a pinned official release and its documented shape-generation API. Keep shape generation and texture generation as separate capabilities.

Requirements:

1. Pin the exact Hunyuan3D release, source commit, shape checkpoint, and optional texture checkpoint independently.
2. Do not install Hunyuan3D dependencies into the existing TripoSR runtime until compatibility with its pinned PyTorch/CUDA stack is proven. The repository currently uses PyTorch 2.14.1 + CUDA 12.6 for TripoSR; the Hunyuan3D-2.1 README documents testing with PyTorch 2.5.1 + CUDA 12.4. Treat this as a dependency conflict risk, not a compatible combination.
3. Use a dedicated image/build target and worker process if dependency versions or native extensions conflict. Keep the FastAPI image free of these dependencies.
4. Initially implement shape generation only. Texture generation must be a separate opt-in operation because the official Hunyuan3D-2.1 model documentation reports approximately 10 GB VRAM for shape, 21 GB for texture, and 29 GB for shape plus texture. Do not enable texture generation on a 12 GB GPU.
5. Expose the upstream low-VRAM mode only if the selected pinned revision supports it. Do not claim it makes the full shape-plus-texture workflow fit into 12 GB.
6. Convert Hunyuan3D mesh outputs to the common normalized representation; preserve generated materials only when their format and semantics can be exported correctly.
7. Keep the adapter disabled by default and require an explicit configuration flag plus a startup capability check.
8. Add a mandatory license/territory gate. Hunyuan3D-2.1's published license explicitly excludes the European Union, United Kingdom, and South Korea. Do not enable or distribute this adapter for deployments in excluded territories without written authorization or a different applicable license. The implementation must not attempt to bypass this restriction. Re-check the license of the exact release before integration; do not assume 2.0 and 2.1 terms are interchangeable.

On the current RTX 3060 12 GB target, Hunyuan3D-2.1 shape-only execution is an experimental path with very limited VRAM headroom, not an acceptance requirement. The texture stage is out of scope for this hardware profile. A separate GPU with adequate headroom is required for reliable Hunyuan3D texture generation.

### 5.3. Output normalization

The normalizer must produce one consistent internal representation for downstream export:

- Triangle mesh geometry with finite vertices and valid face indices.
- Valid vertex normals when supplied; otherwise allow the existing downstream behavior to compute or validate them.
- UV coordinates when supplied by the generator.
- Material definitions and texture images with explicit color-space/semantic mapping.
- No external absolute paths or unresolved texture references.
- Explicit coordinate-system and scale metadata where upstream models differ.

Do not discard UVs, textures, PBR channels, or material assignments. Do not invent missing texture channels. If a generator produces multiple mesh parts, preserve valid material assignments and combine them only when doing so does not alter geometry or UV mapping. Reject unsupported output rather than silently degrading it.

The existing `validate_mesh` assumes a single trimesh-like triangle mesh and `export_glb` currently normalizes vertex colors. Extend this boundary carefully so textured SF3D/Hunyuan3D assets are accepted without breaking TripoSR. Add tests for both vertex-color and textured-material GLBs. Keep full GLB validation as the final authority.

### 5.4. Preprocessing policy

- Keep the shared source-image decode, size limits, and immutable original upload behavior.
- Preserve the current TripoSR preprocessing path byte-for-byte in behavior unless a regression test explicitly proves equivalence.
- Declare preprocessing capabilities per adapter: background removal, alpha handling, foreground crop/resize, input resolution, and color mode.
- Ensure background removal and foreground resizing execute exactly once.
- Do not apply Stage 1 image-quality rejection or enhancement rules here; consume the shared Stage 1 outputs only through the integration contract defined by `11_image_quality_analysis.md`.
- Record source dimensions and effective model input dimensions in the run manifest.

### 5.5. Metadata and reproducibility

Extend `run.json` and `GeneratedAsset.metadata` with a stable `generator` object:

```json
{
  "name": "sf3d",
  "revision": "<pinned-source-commit>",
  "model_id": "stabilityai/stable-fast-3d",
  "model_revision": "<pinned-model-revision>",
  "device": "cuda:0",
  "preprocessing_profile": "sf3d_default",
  "inference_seconds": 0.0,
  "postprocessing_seconds": 0.0,
  "peak_cuda_allocated_bytes": 0,
  "peak_cuda_reserved_bytes": 0
}
```

Use actual measured values; omit unavailable metrics instead of writing fabricated zeros. Preserve existing metadata keys for backward compatibility. Do not store secrets, Hugging Face tokens, full local paths, or raw exception traces in public result metadata.

## 6. Configuration

Add validated settings to `backend/app/core/config.py`, map them in `ObjectGenerationConfig`, and expose them in both environment example files.

Suggested settings:

| Setting | Default | Purpose |
|---|---|---|
| `OBJECT_GENERATOR` | `triposr` | Selected adapter; preserves current behavior. |
| `OBJECT_GENERATOR_FALLBACK` | `false` | Permit pre-inference fallback to TripoSR only. |
| `OBJECT_SF3D_ENABLED` | `false` | Explicitly allow SF3D. |
| `OBJECT_SF3D_MODEL_ID` | `stabilityai/stable-fast-3d` | SF3D model identifier. |
| `OBJECT_SF3D_MODEL_REVISION` | required when enabled | Immutable model revision. |
| `OBJECT_SF3D_MODEL_DIR` | `/models/sf3d` | Dedicated local cache. |
| `OBJECT_SF3D_MODEL_SHA256_MANIFEST` | required when enabled | Manifest/checksum file for model artifacts. |
| `OBJECT_SF3D_TEXTURE_RESOLUTION` | `1024` | Texture baking resolution. |
| `OBJECT_SF3D_REMESH` | `none` | `none`, `triangle`, or `quad`. |
| `OBJECT_SF3D_TARGET_VERTEX_COUNT` | `-1` | Optional target used only when remeshing is enabled. |
| `OBJECT_HUNYUAN3D_ENABLED` | `false` | Explicitly allow Hunyuan adapter. |
| `OBJECT_HUNYUAN3D_MODEL_REVISION` | required when enabled | Pinned upstream revision. |
| `OBJECT_HUNYUAN3D_MODEL_DIR` | `/models/hunyuan3d` | Dedicated model cache. |
| `OBJECT_HUNYUAN3D_MODE` | `shape` | Initially support `shape`; reject `shape_texture` on unsupported hardware. |
| `OBJECT_HUNYUAN3D_LOW_VRAM` | `false` | Use only if supported by the pinned release. |

Validate enum values, absolute model paths, positive texture resolution, legal remesh modes, model revision presence, and required checksum manifests. Reject selecting a disabled or uninstalled adapter during startup. Do not make `OBJECT_GENERATOR` a per-request frontend field in this stage; selection is deployment/worker configuration only.

## 7. API and Integration Requirements

- Do not change the public generation endpoint or request schema for this stage.
- Keep the existing `TaskType.OBJECT`, Celery task name, queue, task lifecycle, and `PipelineArtifact` contract.
- Register the configured adapter through the existing `_bootstrap()` path in `backend/app/tasks/object_pipeline.py`.
- Keep model-specific imports lazy and confined to the object-worker process.
- Preserve heartbeat, cooperative cancellation, task-scoped temporary directories, cleanup, transactional result registration, and current stable error behavior.
- Include generator identity and selected configuration in result metadata; never expose model cache paths or credentials.
- If separate worker images are necessary, document their queue routing and health checks. Do not route one task to two workers or allow workers with different generator configurations to race for the same queue. A deployment must have one unambiguous generator policy per object queue.

## 8. GPU/CPU Resource Management

Target hardware: NVIDIA RTX 3060, 12 GB VRAM.

### 8.1. General rules

- Keep object-worker concurrency at `1` for a single 12 GB GPU.
- Run only one GPU-heavy model at a time. Do not keep multiple generator weights resident on the same device.
- Measure peak allocated and reserved CUDA memory for model load, inference, and export separately.
- Use `torch.inference_mode()` or the upstream inference context.
- Use mixed precision only when the pinned model implementation supports it and quality tests pass. Do not force BF16/FP16 globally across all adapters.
- Clear references to temporary tensors and call `torch.cuda.empty_cache()` after a task where appropriate; do not treat it as a substitute for unloading model weights.
- Keep model loading and unloading explicit. Avoid loading every installed model at worker startup.
- CPU fallback must be explicit, logged, and model-specific. Do not silently move an out-of-memory CUDA task to CPU.
- On CUDA OOM, clean temporary state, preserve a stable `GPU_OUT_OF_MEMORY` error, and leave the worker healthy for subsequent tasks when possible.

### 8.2. Model-specific expectations

| Generator | Upstream VRAM information | MOGEN policy on 12 GB |
|---|---|---|
| TripoSR | Existing repository documents approximately 6 GB for a default run. | Existing verified baseline; preserve current settings and tests. |
| SF3D | Upstream README reports approximately 6 GB for a single image at default settings. | Preferred alternative; start with batch size 1, 1024 texture resolution, measure actual peak, and retain headroom. |
| Hunyuan3D-2.1 shape | Official README reports approximately 10 GB. | Experimental only; opt-in, isolated process, low-VRAM mode if supported, batch size 1. Do not promise reliable operation. |
| Hunyuan3D-2.1 texture | Official README reports approximately 21 GB; shape + texture approximately 29 GB. | Disabled on 12 GB hardware. |

All VRAM figures above are upstream-reported estimates, not verified MOGEN measurements. Benchmark the exact pinned commit, weights, CUDA stack, image size, and export settings on the target GPU before declaring support.

## 9. Error Handling

Add stable error codes where required; do not expose raw upstream tracebacks to users.

| Condition | Expected behavior |
|---|---|
| Unknown generator | Startup configuration error; worker must not accept tasks. |
| Adapter disabled or missing | Startup configuration error; no implicit fallback. |
| Missing weights/checksum mismatch | Fail worker readiness with a model-unavailable error. |
| Model access/token unavailable during model initialization | Fail model-init; never download during task execution. Never log the token. |
| Unsupported dependency/runtime combination | Fail image build or startup preflight with a clear diagnostic. |
| CUDA unavailable | Use CPU only when explicitly configured and supported; otherwise fail readiness. |
| CUDA OOM | Map to `GPU_OUT_OF_MEMORY`; release temporary allocations and keep task failure isolated. |
| Model inference failure | Map to a generator-neutral inference error; log sanitized model/revision and internal traceback. |
| Invalid or unsupported mesh/material output | Fail normalization/export; do not silently discard texture/material data. |
| Invalid GLB | Reuse existing final validation failure behavior; never register the asset. |
| Hunyuan license gate fails | Refuse adapter initialization; do not attempt inference. |
| Cancellation/lease loss | Preserve existing cancellation behavior and remove task-scoped temporary files. |

## 10. Testing Requirements

### 10.1. Unit tests (CPU, no model weights)

- Generator factory selects TripoSR by default and rejects unknown/disabled adapters.
- All adapters satisfy the common protocol.
- Existing TripoSR tests pass unchanged.
- Generator selection and model-specific configuration validation cover valid and invalid values.
- Preprocessing capability flags prevent duplicate background removal and resizing.
- Normalization preserves UV coordinates, material assignments, texture images, and vertex colors.
- Normalization rejects non-finite vertices, invalid faces, missing required textures, and unsupported material formats.
- Exported GLB contains expected materials/textures for textured test fixtures and vertex colors for the TripoSR fixture.
- Metadata contains generator identity, revision, timings, and only available resource metrics.
- Failure mapping, cancellation, and fallback policy are tested.
- Hunyuan license/territory gate can be tested with deterministic configuration fixtures; tests must not make legal assumptions based on geolocation inference.

### 10.2. Integration tests (opt-in, real weights)

Use a fixed, legally usable image corpus with expected outputs and pinned model versions.

For each enabled generator:

1. Verify model cache manifest and checksums.
2. Load model in the actual worker image.
3. Run inference on at least one object image and export GLB.
4. Validate GLB with the existing validator.
5. Load the GLB with the existing Three.js viewer test path.
6. Capture model-load time, preprocessing time, inference time, export time, peak allocated/reserved VRAM, output size, vertices/faces, materials, and textures.
7. Run two sequential tasks to verify model reuse and cleanup.
8. Verify a failed inference does not corrupt the next task.

Hunyuan3D tests are skipped unless the adapter is explicitly enabled, the required license gate is satisfied, and suitable hardware is available. Texture generation tests require a GPU with sufficient VRAM and are not part of RTX 3060 acceptance.

### 10.3. Benchmark protocol

Compare TripoSR and SF3D first; include Hunyuan3D only on suitable hardware and where legally permitted.

- Use the same source images, resolution, and background policy where possible.
- Include varied categories (rigid objects, organic objects, reflective objects, thin structures, and objects with occluded regions).
- Run at least three repetitions per image after one warm-up run.
- Report median and p95 latency, peak VRAM, output file size, vertex/face counts, and failure rate.
- Assess visual quality with a blinded side-by-side review using fixed camera views. If reference geometry exists, add geometric metrics such as Chamfer Distance/F-score; do not claim geometric accuracy from visual inspection alone.
- Record model and dependency revisions with every benchmark result.
- Do not select a new default based only on speed or polygon count. TripoSR remains default until the user explicitly approves a measured change.

## 11. Acceptance Criteria

- [ ] Existing TripoSR behavior, output, and tests remain compatible.
- [ ] `OBJECT_GENERATOR=triposr` remains the default and requires no new model downloads.
- [ ] SF3D can be selected through validated worker configuration and produces a valid textured GLB.
- [ ] SF3D UVs/materials/textures survive normalization, export, and Three.js loading.
- [ ] Generator identity, pinned revisions, timings, and available VRAM metrics are recorded.
- [ ] Model caches are separate, checksum-verified, and populated before worker startup.
- [ ] No model downloads occur during task execution.
- [ ] GPU-heavy inference is serialized for the 12 GB GPU profile.
- [ ] Hunyuan3D remains disabled by default and cannot initialize when its license gate fails.
- [ ] Hunyuan3D shape-only integration is isolated from the TripoSR runtime when dependency conflicts exist.
- [ ] Hunyuan3D texture generation is disabled for the 12 GB hardware profile.
- [ ] Existing Celery task lifecycle, progress stages, cancellation, storage, and GLB validation remain intact.
- [ ] CPU unit tests pass; real-model integration and benchmark reports are produced for every adapter declared supported.
- [ ] No public API or frontend changes are introduced in this stage.

## 12. AI Agent Implementation Instructions

1. Read `06_object_generation.md`, `docs/architecture/system_architecture.md`, `docs/architecture/data_flow.md`, and the existing object-generation code before editing.
2. Preserve the current TripoSR path as the regression baseline. Run its unit tests before changes and keep the results.
3. Implement the generator contract and factory with the smallest possible abstraction. Do not refactor unrelated task, storage, database, or API code.
4. Implement SF3D first. Verify its upstream commit, model access requirements, license, dependency compatibility, model cache layout, and real RTX 3060 memory use before adding it to the supported configuration allowlist.
5. Keep SF3D dependencies isolated if they conflict with the existing PyTorch 2.14.1/CUDA 12.6 worker. Do not casually upgrade or downgrade the TripoSR runtime.
6. Implement Hunyuan3D only after a separate license/territory review and hardware feasibility check. Keep it opt-in and isolated; if these checks cannot be satisfied, document the adapter as blocked rather than bypassing the gate.
7. Extend normalization/export without breaking the existing TripoSR vertex-color output. Add textured GLB fixtures and verify them through both the Python validator and Three.js.
8. Add configuration validation and environment examples. Do not expose model selection in the frontend or public API.
9. Add CPU unit tests first, then opt-in real-model tests and benchmark scripts. Do not download large model weights in ordinary CI.
10. Update the relevant worker image/Compose configuration only after the selected adapter's dependency lock is reproducible. Keep optional services disabled by default.
11. Run all existing object-generation tests, backend tests affected by settings, lint/type checks, and GLB viewer validation. Record exact commands and results.
12. Update `ml/object_generation/README.md` and operational documentation only for actual new setup steps, model access, cache population, license notices, and hardware limits. Do not copy this specification into implementation documentation.
13. Do not start Stage 4 work. Stop after delivering the implementation report and wait for approval.
